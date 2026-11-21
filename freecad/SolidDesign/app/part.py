# SPDX-License-Identifier: LGPL-2.1-or-later
"""The Solid Design Part (spec section 5.1) and its tree helpers (section 6).

A Part is a Part::FeaturePython with a group extension. It holds:
- the origin: Front/Top/Right planes, three axes and the origin point;
- the feature history, in order (the Group order);
- the rollback bar (``Tip``: the feature the part is computed up to);
- its Shape: the compound of the bodies at the rollback bar, which is what
  other workbenches and exports see.

Bodies are shown through *body views*: one Part::FeaturePython per body, linked
to the Part (not in its Group, so there is no dependency loop). They live in the
Solid Bodies / Surface Bodies folders, which are views of the tip's body set.
"""

import FreeCAD as App
import Part

from ..core import bodies as core_bodies
from ..core.bodies import BodySet
from . import util

# Default planes keep SolidWorks' names on FreeCAD's axes (spec section 4):
# Front = XZ (seen from FreeCAD's Front view), Top = XY, Right = YZ.
# Rotations are those of FreeCAD's own App::Origin planes.
ORIGIN_PLANES = [
    ("Front Plane", "XZ_Plane", App.Rotation(0, 0, 90)),
    ("Top Plane", "XY_Plane", App.Rotation(0, 0, 0)),
    ("Right Plane", "YZ_Plane", App.Rotation(90, 0, 90)),
]
# Part::DatumLine runs along its local Z.
ORIGIN_AXES = [
    ("X Axis", "X_Axis", App.Rotation(App.Vector(0, 1, 0), 90)),
    ("Y Axis", "Y_Axis", App.Rotation(App.Vector(1, 0, 0), -90)),
    ("Z Axis", "Z_Axis", App.Rotation()),
]
AXIS_DIRS = {"X Axis": App.Vector(1, 0, 0), "Y Axis": App.Vector(0, 1, 0),
             "Z Axis": App.Vector(0, 0, 1)}


def fix_origin_axes(part):
    """Files from 0.1.0 had the axes pointing the wrong way: correct them."""
    for o in part.Origin:
        want = AXIS_DIRS.get(o.Label)
        if want is None or o.TypeId != "Part::DatumLine":
            continue
        got = o.Placement.Rotation.multVec(App.Vector(0, 0, 1))
        if (got - want).Length > 1e-9:
            rot = dict((lab, r) for lab, _n, r in ORIGIN_AXES)[o.Label]
            o.Placement = App.Placement(App.Vector(), rot)


# =================================================================== Part

class PartProxy(object):
    SD_ROLE = "part"

    def __init__(self, obj):
        obj.addExtension("App::GroupExtensionPython")
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        util.add_prop(obj, "App::PropertyLink", "Tip", "Part",
                      "Rollback bar: the feature the part is computed up to")
        util.add_prop(obj, "App::PropertyLinkList", "Origin", "Part",
                      "Origin planes, axes and point")
        util.add_prop(obj, "App::PropertyStringList", "BodyIds", "Part", "IDs of the final bodies")
        util.add_prop(obj, "App::PropertyStringList", "BodyKinds", "Part", "solid or surface")
        util.add_prop(obj, "App::PropertyStringList", "BodyFeatures", "Part",
                      "Last feature that changed each body")
        util.add_prop(obj, "App::PropertyMap", "BodyNames", "Part",
                      "Names the user gave to bodies (body ID -> name)")
        util.add_prop(obj, "App::PropertyInteger", "SchemaVersion", "Part",
                      "File format version", util.SCHEMA_VERSION)
        for p in ("Origin", "BodyIds", "BodyKinds", "BodyFeatures", "BodyNames",
                  "SchemaVersion"):
            util.hide_prop(obj, p)

    def onDocumentRestored(self, obj):
        self.setup(obj)
        fix_origin_axes(obj)
        if obj.SchemaVersion < util.SCHEMA_VERSION:
            obj.SchemaVersion = util.SCHEMA_VERSION
        install_observer()

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def execute(self, obj):
        tip = obj.Tip
        if tip is not None and util.is_feature(tip):
            shape = tip.Shape.copy(False)
            ids, kinds, feats = list(tip.BodyIds), list(tip.BodyKinds), list(tip.BodyFeatures)
        else:
            shape = Part.makeCompound([])
            ids, kinds, feats = [], [], []
        obj.Shape = shape
        if list(obj.BodyIds) != ids:
            obj.BodyIds = ids
        if list(obj.BodyKinds) != kinds:
            obj.BodyKinds = kinds
        if list(obj.BodyFeatures) != feats:
            obj.BodyFeatures = feats

    def onChanged(self, obj, prop):
        if "Tip" not in obj.PropertiesList or "Group" not in obj.PropertiesList:
            return
        if prop == "Tip" and not util.in_recompute(obj.Document):
            for f in util.features(obj):
                f.touch()
        elif prop == "Group" and not obj.Document.Restoring:
            # Only history objects belong in the group. FreeCAD's tree can drop the
            # rollback bar, a folder or a body into it; take them out again at once.
            group = list(obj.Group)
            stray = [o for o in group if util.role(o) in ("rollback", "folder", "body", "part")]
            if stray:
                bars = [o for o in stray if util.role(o) == "rollback"]
                obj.Group = [o for o in group if o not in stray]
                if bars and not obj.Document.Transacting:
                    # The bar was dropped between two items of the tree: roll to
                    # the last feature above where it was dropped.
                    above = [o for o in group[:group.index(bars[0])] if util.is_feature(o)]
                    roll_to(obj, above[-1] if above else None)
                return
            # A feature was deleted or the order changed: keep the chain and the bar valid.
            feats = util.features(obj)
            if obj.Tip is not None and obj.Tip not in feats:
                obj.Tip = feats[-1] if feats else None
            relink(obj)


def create(doc, label=None):
    """A new Part with its origin, folders and rollback bar."""
    install_observer()
    obj = doc.addObject("Part::FeaturePython", "Part")
    PartProxy(obj)
    obj.Label = label or util.next_label(doc, "Part")
    origin = []
    for lab, name, rot in ORIGIN_PLANES:
        p = doc.addObject("Part::DatumPlane", name)
        _plain_label(p, lab)
        p.MapMode = "Deactivated"
        p.Placement = App.Placement(App.Vector(), rot)
        origin.append(p)
    pt = doc.addObject("Part::DatumPoint", "Origin")
    _plain_label(pt, "Origin")
    pt.MapMode = "Deactivated"
    origin.append(pt)
    for lab, name, rot in ORIGIN_AXES:
        a = doc.addObject("Part::DatumLine", name)
        _plain_label(a, lab)
        a.MapMode = "Deactivated"
        a.Placement = App.Placement(App.Vector(), rot)
        origin.append(a)
    obj.Origin = origin
    obj.Group = origin
    for kind in (core_bodies.SOLID, core_bodies.SURFACE):
        f = doc.addObject("App::FeaturePython", "SolidBodies" if kind == core_bodies.SOLID
                          else "SurfaceBodies")
        FolderProxy(f, obj, kind)
    _make_origin_folder(obj)
    bar = doc.addObject("App::FeaturePython", "RollbackBar")
    RollbackBarProxy(bar, obj)
    if App.GuiUp:
        from ..gui import viewproviders
        viewproviders.attach_part(obj)
        for o in origin:
            o.ViewObject.Visibility = False
        viewproviders.attach_folder(folder(obj, core_bodies.SOLID))
        viewproviders.attach_folder(folder(obj, core_bodies.SURFACE))
        viewproviders.attach_folder(folder(obj, ORIGIN_FOLDER))
        viewproviders.attach_rollback(bar)
        viewproviders._label_origin(obj)
    obj.purgeTouched()
    return obj


def origin_feature(part, name):
    for o in part.Origin:
        if o.Name.startswith(name) or clean_label(o.Label) == name:
            return o
    return None


def _plain_label(obj, label):
    """Give *obj* exactly *label* as the user reads it. FreeCAD wants labels
    unique in a document, so a second part's "Top Plane" gets zero-width spaces
    after it (as bodies do) instead of becoming "Top Plane001"."""
    for k in range(50):
        want = label + _ZWSP * k
        obj.Label = want
        if obj.Label == want:
            return


def default_planes(part):
    return [o for o in part.Origin if o.TypeId == "Part::DatumPlane"]


# =================================================================== history

def relink(part):
    """Chain BaseFeature down the history (Group order). Reference geometry gets
    the feature just before it, so its references follow the model too."""
    prev = None
    for o in part.Group:
        if util.is_feature(o):
            if o.BaseFeature != prev:
                o.BaseFeature = prev
            prev = o
        elif util.role(o) == "refgeom":
            if o.BaseFeature != prev:
                o.BaseFeature = prev


def insert_feature(part, feat, sketches=()):
    """Insert a feature at the rollback bar, with its sketch(es) just before it.

    Sketches already in the part stay where they are (they may be shared).
    """
    sketches = [s for s in sketches if s not in part.Group]
    group = [o for o in part.Group if o is not feat and o not in sketches]
    idx = _bar_index(part, group)
    for s in sketches:
        if s.Document is part.Document:
            for o in s.InList:
                if o is not part and hasattr(o, "Group") and s in o.Group and not util.is_part(o):
                    o.Group = [x for x in o.Group if x is not s]
    new = group[:idx] + list(sketches) + [feat] + group[idx:]
    part.Group = new
    relink(part)
    part.Tip = feat


def _bar_index(part, group):
    """Where new things go: at the rollback bar, after whatever (sketches,
    reference geometry) already sits between the tip and the next feature."""
    tip = part.Tip
    start = group.index(tip) + 1 if tip is not None and tip in group else 0
    for i in range(start, len(group)):
        if util.is_feature(group[i]):
            return i
    return len(group)


def add_to_part(part, obj):
    """Put a non-feature object (a sketch, a plane) into the part at the rollback bar."""
    group = [o for o in part.Group if o is not obj]
    part.Group = group[:_bar_index(part, group)] + [obj] + group[_bar_index(part, group):]
    relink(part)
    if App.GuiUp and obj.TypeId.startswith("Sketcher::SketchObject"):
        from ..gui import sketch_edit
        sketch_edit.keep_model_visible(obj)


def remove_feature(part, feat):
    feats = util.features(part)
    if feat not in feats:
        return
    i = feats.index(feat)
    if part.Tip is feat:
        part.Tip = feats[i - 1] if i > 0 else None
    part.Group = [o for o in part.Group if o is not feat]
    relink(part)


def _link_targets(obj):
    """Objects an object links to, except through BaseFeature (which relink sets)."""
    out = []
    for name in obj.PropertiesList:
        if name == "BaseFeature":
            continue
        try:
            t = obj.getTypeIdOfProperty(name)
        except Exception:
            continue
        if not t.startswith("App::PropertyLink") and t != "App::PropertyXLink":
            continue
        val = getattr(obj, name)
        if val is None:
            continue
        items = val if isinstance(val, list) else [val]
        for it in items:
            o = it[0] if isinstance(it, tuple) else it
            if o is not None and hasattr(o, "TypeId"):
                out.append(o)
    return out


def feature_parents(feat):
    """Features a feature depends on, other than through BaseFeature (its parents
    in SolidWorks' terms: sketches' attachments, Up To faces...)."""
    seen = set()
    parents = []
    stack = [feat]
    while stack:
        o = stack.pop()
        for t in _link_targets(o):
            if t.Name in seen or t is feat:
                continue
            seen.add(t.Name)
            if util.is_feature(t):
                parents.append(t)
            elif not util.is_part(t):
                stack.append(t)
    return parents


def can_move(part, feat, new_index):
    """Whether moving ``feat`` to position ``new_index`` among the features keeps
    every parent before its children. Returns (ok, reason)."""
    feats = [f for f in util.features(part) if f is not feat]
    new_index = max(0, min(new_index, len(feats)))
    order = feats[:new_index] + [feat] + feats[new_index:]
    pos = {f.Name: i for i, f in enumerate(order)}
    for f in order:
        for par in feature_parents(f):
            if par.Name in pos and pos[par.Name] > pos[f.Name]:
                return False, "{} uses {}, which would come after it.".format(f.Label, par.Label)
    return True, ""


def move_feature(part, feat, new_index):
    """Reorder: put ``feat`` at ``new_index`` among the features (its own sketch moves
    with it). Raises ValueError when a parent would come after its child."""
    ok, why = can_move(part, feat, new_index)
    if not ok:
        raise ValueError(why)
    at_end = is_at_end(part)
    feats = [f for f in util.features(part) if f is not feat]
    new_index = max(0, min(new_index, len(feats)))
    own = [o for o in part.Group if not util.is_feature(o) and o in feat.OutList
           and o not in part.Origin
           and all(u is feat or not util.is_feature(u) for u in o.InList)]
    group = [o for o in part.Group if o is not feat and o not in own]
    if new_index < len(feats):
        idx = group.index(feats[new_index])
    else:
        idx = len(group)
    part.Group = group[:idx] + own + [feat] + group[idx:]
    relink(part)
    if at_end:
        part.Tip = util.features(part)[-1]
    for f in util.features(part):
        f.touch()


def roll_to(part, feat):
    """Move the rollback bar to just after ``feat`` (None: before every feature)."""
    if part.Tip is not feat:
        part.Tip = feat
    for f in util.features(part):
        f.touch()


def roll_to_end(part):
    feats = util.features(part)
    roll_to(part, feats[-1] if feats else None)


def is_at_end(part):
    feats = util.features(part)
    return not feats or part.Tip is feats[-1]


def tip_bodies(part):
    return BodySet.from_columns(part.Shape, list(part.BodyIds), list(part.BodyKinds),
                                list(part.BodyFeatures))


def find_parts(doc):
    return [o for o in doc.Objects if util.is_part(o)]


# =================================================================== folders

def _unlink_from_part(obj):
    """Folders and the rollback bar name their part by a string, not a link.

    A link back to the part made a dependency loop as soon as FreeCAD's tree put
    one of them into the part's group (a drop between items does that). Older
    files had the link: migrate them.
    """
    if "PartName" not in obj.PropertiesList:
        obj.addProperty("App::PropertyString", "PartName", "Part", "Name of the part")
        util.hide_prop(obj, "PartName")
    if "SourcePart" in obj.PropertiesList:
        p = obj.SourcePart
        if p is not None:
            obj.PartName = p.Name
        obj.SourcePart = None
        obj.removeProperty("SourcePart")


class FolderProxy(object):
    """Solid Bodies / Surface Bodies: a view of the tip's body set."""
    SD_ROLE = "folder"

    def __init__(self, obj, part, kind):
        obj.Proxy = self
        _unlink_from_part(obj)
        obj.addProperty("App::PropertyString", "Kind", "Folder", "solid or surface")
        obj.addProperty("App::PropertyInteger", "Revision", "Folder", "Bumped when bodies change")
        obj.PartName = part.Name
        obj.Kind = kind
        for p in ("Kind", "Revision"):
            util.hide_prop(obj, p)
        obj.Label = folder_title(kind, 0)

    def onDocumentRestored(self, obj):
        _unlink_from_part(obj)

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


ORIGIN_FOLDER = "origin"


def _make_origin_folder(part):
    f = part.Document.addObject("App::FeaturePython", "OriginFolder")
    FolderProxy(f, part, ORIGIN_FOLDER)
    _plain_label(f, "Origin")
    return f


def ensure_origin_folder(part):
    """Parts made before the Origin folder existed get one."""
    if folder(part, ORIGIN_FOLDER) is None:
        f = _make_origin_folder(part)
        if App.GuiUp:
            from ..gui import viewproviders
            viewproviders.attach_folder(f)
        return f
    return None


def folder_title(kind, n):
    if kind == ORIGIN_FOLDER:
        return "Origin"
    return "{} ({})".format("Solid Bodies" if kind == core_bodies.SOLID else "Surface Bodies", n)


def owner_part(obj):
    """The part a folder or the rollback bar belongs to."""
    name = getattr(obj, "PartName", "")
    return obj.Document.getObject(name) if name else None


def folder(part, kind):
    for o in part.Document.Objects:
        if util.role(o) == "folder" and o.Kind == kind and getattr(o, "PartName", "") == part.Name:
            return o
    return None


def rollback_bar(part):
    for o in part.Document.Objects:
        if util.role(o) == "rollback" and getattr(o, "PartName", "") == part.Name:
            return o
    return None


class RollbackBarProxy(object):
    SD_ROLE = "rollback"

    def __init__(self, obj, part):
        obj.Proxy = self
        _unlink_from_part(obj)
        obj.PartName = part.Name
        obj.Label = "Rollback bar"

    def onDocumentRestored(self, obj):
        _unlink_from_part(obj)

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


# =================================================================== body views

class BodyViewProxy(object):
    """One body of the part, shown in a body folder."""
    SD_ROLE = "body"

    def __init__(self, obj, part, body_id):
        obj.Proxy = self
        obj.addProperty("App::PropertyString", "PartName", "Body", "Name of the part")
        obj.addProperty("App::PropertyString", "BodyId", "Body", "Stable body ID")
        obj.addProperty("App::PropertyString", "Kind", "Body", "solid or surface")
        obj.PartName = part.Name
        obj.BodyId = body_id
        util.hide_prop(obj, "PartName")
        for p in ("BodyId", "Kind"):
            util.readonly_prop(obj, p)

    def onDocumentRestored(self, obj):
        _unlink_view(obj)

    def execute(self, obj):
        part = source_part(obj)
        if part is None:
            return
        ids = list(part.BodyIds)
        if obj.BodyId not in ids:
            obj.Shape = Part.Shape()
            return
        i = ids.index(obj.BodyId)
        shape = part.Shape
        children = shape.childShapes() if shape.ShapeType == "Compound" else [shape]
        if i < len(children):
            child = children[i]
            # A moved body (Move/Copy, patterns) carries its move as a placement.
            # Part::Feature replaces a new shape's placement with its own
            # Placement property, so that property takes the move.
            pl = child.Placement
            obj.Shape = child
            if not obj.Placement.isSame(pl, 1e-12):
                obj.Placement = pl
            kind = part.BodyKinds[i] if i < len(part.BodyKinds) else ""
            if obj.Kind != kind:
                obj.Kind = kind

    def onChanged(self, obj, prop):
        doc = obj.Document
        # Only a rename by the user counts: not undo/redo or a cancelled panel
        # (Transacting), not opening a file, not a recompute.
        if prop == "Label" and not _syncing[0] and "BodyId" in obj.PropertiesList and \
                not doc.Transacting and not doc.Restoring and not doc.Recomputing:
            part = source_part(obj)
            if part is not None and obj.BodyId:
                names = dict(part.BodyNames)
                label = clean_label(obj.Label)
                if names.get(obj.BodyId) != label:
                    names[obj.BodyId] = label
                    part.BodyNames = names

    def dumps(self):
        return None

    def loads(self, state):
        return None


_syncing = [False]


def source_part(view):
    """The part a body view shows a body of."""
    try:
        name = view.PartName if "PartName" in view.PropertiesList else ""
        if not name and "SourcePart" in view.PropertiesList and view.SourcePart is not None:
            return view.SourcePart
        return view.Document.getObject(name) if name else None
    except Exception:
        return None


def _unlink_view(obj):
    """A body view names its part by a string, not a link.

    The link made every body depend on the part, and so on every sketch in it:
    the Sketcher refused a body's edges as external geometry (a dependency
    loop) and hid the bodies while sketching. The view's shape is set by sync()
    after each recompute, so it needs no link. Older files had the link.
    """
    if "PartName" not in obj.PropertiesList:
        obj.addProperty("App::PropertyString", "PartName", "Body", "Name of the part")
        util.hide_prop(obj, "PartName")
    if "SourcePart" in obj.PropertiesList:
        p = obj.SourcePart
        if p is not None:
            obj.PartName = p.Name
        obj.SourcePart = None
        obj.removeProperty("SourcePart")


def body_views(part):
    return [o for o in part.Document.Objects
            if util.is_body_view(o) and getattr(o, "PartName", None) == part.Name] + \
        [o for o in part.InList if util.is_body_view(o) and "SourcePart" in o.PropertiesList
         and o.SourcePart is part]


def delete_contents(part):
    """Remove everything a part holds, before the part itself is removed: its
    bodies, features (last first), sketches and reference geometry, folders,
    rollback bar and origin."""
    doc = part.Document
    group = list(part.Group)
    origin = list(part.Origin)
    doomed = body_views(part)
    doomed += list(reversed([o for o in group if util.is_feature(o)]))
    doomed += [o for o in group if not util.is_feature(o) and o not in origin]
    doomed += [o for o in (folder(part, core_bodies.SOLID), folder(part, core_bodies.SURFACE),
                           folder(part, ORIGIN_FOLDER), rollback_bar(part)) if o is not None]
    names = [o.Name for o in doomed]
    part.Group = []
    part.Origin = []
    try:
        part.Tip = None
    except Exception:
        pass
    for name in names + [o.Name for o in origin]:
        if doc.getObject(name) is not None:
            doc.removeObject(name)


# FreeCAD refuses duplicate labels by default, but SolidWorks names a body after
# the feature that last changed it ("Fillet3" in the folder and in the history).
# Body labels always end in a zero-width space, so they never take a label a
# feature needs, while they read the same.
_ZWSP = u"\u200b"


def clean_label(label):
    return label.replace(_ZWSP, "")


def body_name(part, body_id, feature_name):
    names = dict(part.BodyNames)
    if body_id in names:
        return names[body_id]
    f = part.Document.getObject(feature_name) if feature_name else None
    if f is not None and "PieceNames" in f.PropertiesList and body_id in f.PieceNames:
        return f.PieceNames[body_id]        # named in Split's piece list
    return f.Label if f is not None else body_id


def ensure_view_providers(part):
    """Give view providers to objects made without the GUI (e.g. by a script)."""
    from ..gui import viewproviders as vp
    def need(o):
        return o is not None and o.ViewObject is not None and o.ViewObject.Proxy is None
    if need(part):
        vp.attach_part(part)
    for f in util.features(part):
        if need(f):
            vp.attach_feature(f)
    for kind in (core_bodies.SOLID, core_bodies.SURFACE):
        f = folder(part, kind)
        if need(f):
            vp.attach_folder(f)
        if f is not None and f.ViewObject is not None:
            show = kind in list(part.BodyKinds)
            if f.ViewObject.ShowInTree != show:
                f.ViewObject.ShowInTree = show
    for o in part.Origin:
        if o.TypeId == "Part::DatumLine" and o.ViewObject is not None and o.ViewObject.ShowInTree:
            o.ViewObject.ShowInTree = False
    f = folder(part, ORIGIN_FOLDER)
    if f is None:
        ensure_origin_folder(part)
    elif need(f):
        vp.attach_folder(f)
    bar = rollback_bar(part)
    if need(bar):
        vp.attach_rollback(bar)
    for v in body_views(part):
        if need(v):
            vp.attach_body(v)
    from ..gui import sketch_edit
    for o in part.Group:
        if util.role(o) == "refgeom" and need(o):
            vp.attach_refgeom(o)
        elif sketch_edit.is_sketch(o):
            sketch_edit.keep_model_visible(o)


def body_names(part, ids, feats):
    """Names for bodies, as the tree shows them. SolidWorks names a body after the
    last feature that changed it; several bodies from one feature are
    "Cut-Extrude1[1]", "Cut-Extrude1[2]"..."""
    names = [body_name(part, bid, feats[i] if i < len(feats) else "")
             for i, bid in enumerate(ids)]
    user = dict(part.BodyNames)
    counts = {}
    for i, n in enumerate(names):
        if ids[i] not in user:
            counts[n] = counts.get(n, 0) + 1
    seen = {}
    for i, n in enumerate(names):
        if ids[i] not in user and counts.get(n, 0) > 1:
            seen[n] = seen.get(n, 0) + 1
            names[i] = "{}[{}]".format(n, seen[n])
    return names


def sync(part):
    """Make the body views and folders match the part's final bodies."""
    doc = part.Document
    ids = list(part.BodyIds)
    kinds = list(part.BodyKinds)
    feats = list(part.BodyFeatures)
    views = {}
    for v in body_views(part):
        if v.BodyId in views or v.BodyId not in ids:
            doc.removeObject(v.Name)
        else:
            views[v.BodyId] = v
    _syncing[0] = True
    changed = False
    names = body_names(part, ids, feats)
    try:
        for i, bid in enumerate(ids):
            v = views.get(bid)
            if v is None:
                v = doc.addObject("Part::FeaturePython", "Body")
                BodyViewProxy(v, part, bid)
                if App.GuiUp:
                    from ..gui import viewproviders
                    viewproviders.attach_body(v)
                changed = True
            v.recompute()
            name = names[i]
            if clean_label(v.Label) != name or not v.Label.endswith(_ZWSP):
                n = 1
                v.Label = name + _ZWSP
                while clean_label(v.Label) != name and n < 20:
                    n += 1
                    v.Label = name + _ZWSP * n
            v.purgeTouched()
        if App.GuiUp:
            try:
                ensure_view_providers(part)
            except Exception as e:
                util.console_warning("view providers: {}".format(e))
        for kind in (core_bodies.SOLID, core_bodies.SURFACE):
            f = folder(part, kind)
            if f is None:
                continue
            title = folder_title(kind, kinds.count(kind))
            if f.Label != title:
                f.Label = title
            f.Revision = f.Revision + 1
            f.purgeTouched()
    finally:
        _syncing[0] = False
    return changed


class _Observer(object):
    def slotRecomputedDocument(self, doc):
        for p in find_parts(doc):
            try:
                sync(p)
            except Exception as e:
                util.console_error("could not update the body folders: {}".format(e))


_observer = [None]


def install_observer():
    if _observer[0] is None:
        _observer[0] = _Observer()
        App.addDocumentObserver(_observer[0])


def element_point(elem):
    """A point on a face, edge or vertex (inside it, not on its boundary)."""
    import Part
    if elem.ShapeType == "Vertex":
        return App.Vector(elem.Point)
    if elem.ShapeType == "Edge":
        return elem.valueAt(0.5 * (elem.FirstParameter + elem.LastParameter))
    u0, u1, v0, v1 = elem.ParameterRange
    p = elem.valueAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))
    if elem.isInside(p, 1e-6, True):
        return p
    return elem.distToShape(Part.Vertex(elem.CenterOfMass))[1][0][0]


def feature_of_element(part, elem, tol=1e-6):
    """The feature that made a face, edge or vertex of the model at the rollback bar:
    the earliest one whose own result (what it added, removed or changed) has an
    element of that kind through it. None when none does."""
    import Part
    kinds = {"Face": "Faces", "Edge": "Edges", "Vertex": "Vertexes"}
    attr = kinds.get(elem.ShapeType)
    if attr is None:
        return None
    p = element_point(elem)
    vp = Part.Vertex(p)
    feats = util.features(part)
    tip = part.Tip
    if tip in feats:
        feats = feats[:feats.index(tip) + 1]
    for f in feats:
        if getattr(f, "Suppressed", False):
            continue
        s = getattr(f, "AddSubShape", None)
        if s is None or s.isNull():
            continue
        for g in getattr(s, attr):
            bb = App.BoundBox(g.BoundBox)
            # Padded: a drawn shape's box comes from its display mesh.
            bb.enlarge(max(10 * tol, 0.01 * bb.DiagonalLength))
            if bb.isInside(p):
                try:
                    if g.distToShape(vp)[0] <= tol * 10:
                        return f
                except Exception:
                    pass
    return None
