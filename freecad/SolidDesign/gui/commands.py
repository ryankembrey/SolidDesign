# SPDX-License-Identifier: LGPL-2.1-or-later
"""Commands. Tooltips follow SolidWorks' style: what it does, in one sentence.

Each shape tool is one command (owner's decision, 2026-11-16: no separate Cut
entries). It opens in Add mode; Add | Cut is switched in the panel.
"""

import FreeCAD as App
import FreeCADGui as Gui

from .. import icon
from ..app import dressup as app_dressup
from ..app import extrude as app_extrude
from ..app import part as part_mod
from ..app import revolve as app_revolve
from ..app import util
from ..app import refs
from . import active


def _doc():
    return App.ActiveDocument


class NewPart(object):
    def GetResources(self):
        return {"Pixmap": icon("Part"), "MenuText": "Part",
                "ToolTip": "Creates a part with its origin, default planes and body folders."}

    def IsActive(self):
        return _doc() is not None

    def Activated(self):
        doc = _doc()
        doc.openTransaction("New Part")
        p = part_mod.create(doc)
        active.set_active(p)
        doc.recompute()
        doc.commitTransaction()


class NewSketch(object):
    def GetResources(self):
        return {"Pixmap": ":/icons/SketcherWorkbench.svg", "MenuText": "Sketch",
                "ToolTip": "Sketches on the selected plane or planar face.",
                "Accel": "S, K"}

    def IsActive(self):
        return _doc() is not None and not Gui.Control.activeDialog()

    def Activated(self):
        start_sketch(_doc(), then=None)


def _plane_selection():
    """(object, sub) of a selected plane or planar face, mapped for attachment."""
    from .plane_prompt import plane_target
    for s in Gui.Selection.getSelectionEx():
        subs = list(s.SubElementNames) or [""]
        for sub in subs:
            t = plane_target(s.Object, sub)
            if t is not None:
                return t
    return None


def start_sketch(doc, then=None, target=None):
    """New sketch on *target* or the selected plane/face, opened in the Sketcher;
    with neither, the planes show and one is asked for first (SolidWorks).
    ``then(sketch)`` runs when the sketch is closed."""
    part = active.active_part(doc)
    if target is None:
        target = _plane_selection()
    if target is None:
        from . import plane_prompt
        plane_prompt.prompt(doc, part, lambda t: start_sketch(doc, then, t))
        return None
    doc.openTransaction("New Sketch")
    sk = doc.addObject("Sketcher::SketchObject", "Sketch")
    sk.AttachmentSupport = [target]
    o = target[0]
    # A coordinate system: sketch on its XY plane (SolidWorks needs a plane first).
    sk.MapMode = "ObjectXY" if util.role(o) == "refgeom" and o.Proxy.KIND == "csys" \
        else "FlatFace"
    part_mod.add_to_part(part, sk)
    doc.recompute()
    doc.commitTransaction()
    Gui.Selection.clearSelection()
    if then is not None:
        _after_sketch[sk.Name] = then
        _install_gui_observer()
    Gui.ActiveDocument.setEdit(sk.Name)
    return sk


_after_sketch = {}
_gui_observer = [None]


class _GuiObserver(object):
    def slotResetEdit(self, vobj):
        try:
            obj = vobj.Object
        except Exception:
            return
        fn = _after_sketch.pop(obj.Name, None)
        if fn is not None and obj.Shape.Edges:
            from PySide import QtCore
            QtCore.QTimer.singleShot(0, lambda: fn(obj))


def _install_gui_observer():
    if _gui_observer[0] is None:
        _gui_observer[0] = _GuiObserver()
        Gui.addDocumentObserver(_gui_observer[0])


class SketchTool(object):
    """A sketch-based Add | Cut tool (Extrude, Revolve). Opens in Add mode."""

    def __init__(self, name, icon_name, tooltip, create, mode="Add"):
        self.name = name
        self.icon_name = icon_name
        self.tooltip = tooltip
        self.create = create
        self.mode = mode            # Surface: SolidWorks' Extruded Surface and the like

    def GetResources(self):
        return {"Pixmap": icon(self.icon_name), "MenuText": self.name, "ToolTip": self.tooltip}

    def IsActive(self):
        return _doc() is not None and not Gui.Control.activeDialog()

    def Activated(self):
        doc = _doc()
        sketch = None
        for s in Gui.Selection.getSelection():
            if s.TypeId.startswith("Sketcher::SketchObject"):
                sketch = s
                break
        part = active.active_part(doc)
        if sketch is None and _plane_selection() is not None:
            # SolidWorks: with a plane or face selected, the tool starts a sketch on
            # it and opens the feature when the sketch is closed.
            start_sketch(doc, then=lambda sk: open_feature(doc, part, self, sk))
            return
        if sketch is None:
            sketch = _unused_sketch(part)
        if sketch is None and not _unused_sketches(part):
            # Nothing to extrude yet: pick a plane, sketch, then the feature opens.
            start_sketch(doc, then=lambda sk: open_feature(doc, part, self, sk))
            return
        open_feature(doc, part, self, sketch)


def _unused_sketches(part):
    return [o for o in part.Group if o.TypeId.startswith("Sketcher::SketchObject")
            and not any(util.is_feature(u) for u in o.InList)]


def _unused_sketch(part):
    """With one unused sketch in the part, use it (spec 8.1)."""
    unused = _unused_sketches(part)
    return unused[0] if len(unused) == 1 else None


def open_feature(doc, part, tool, sketch):
    doc.openTransaction(tool.name)
    obj = tool.create(doc, part, getattr(tool, "mode", "Add"), sketch)
    _edit_new(doc, obj)
    if sketch is not None:
        sketch.ViewObject.Visibility = False
    return obj


def open_extrude(doc, part, mode, sketch):
    """Kept for scripts and tests."""
    doc.openTransaction("Extrude")
    obj = app_extrude.create(doc, part, mode, sketch)
    _edit_new(doc, obj)
    return obj


def _edit_new(doc, obj):
    from . import viewproviders
    viewproviders.attach_feature(obj, new=True)
    doc.recompute()
    Gui.Selection.clearSelection()
    Gui.ActiveDocument.setEdit(obj.Name, 0)


def _picked_items(part, kinds):
    """Preselected edges/faces/vertices, as names in the model at the rollback bar."""
    from .selection import map_to_feature
    base = part.Tip
    out = []
    if base is None:
        return out
    for s in Gui.Selection.getSelectionEx():
        o = s.Object
        for sub in s.SubElementNames:
            if not any(sub.startswith(k) for k in kinds):
                continue
            if util.is_body_view(o) and part_mod.source_part(o) is part:
                name = map_to_feature(o.getSubObject(sub), base)
            elif o is base:
                name = sub
            else:
                name = None
            if name and name not in out:
                out.append(name)
    return out


class EdgeTool(object):
    """Fillet, Chamfer: preselected edges and faces fill the panel."""

    def __init__(self, name, tooltip, create, kinds=("Edge", "Face")):
        self.name = name
        self.tooltip = tooltip
        self.create = create
        self.kinds = kinds

    def GetResources(self):
        return {"Pixmap": icon(self.name), "MenuText": self.name, "ToolTip": self.tooltip}

    def IsActive(self):
        doc = _doc()
        return doc is not None and not Gui.Control.activeDialog() and \
            bool(part_mod.find_parts(doc))

    def Activated(self):
        doc = _doc()
        part = active.active_part(doc)
        items = _picked_items(part, self.kinds + ("Vertex",))
        doc.openTransaction(self.name)
        obj = self.create(doc, part, items or None)
        _edit_new(doc, obj)


class FaceTool(EdgeTool):
    """Offset Surface, Move Face: preselected faces fill the panel."""

    def __init__(self, name, icon_name, tooltip, create):
        super(FaceTool, self).__init__(name, tooltip, create, kinds=("Face",))
        self.icon_name = icon_name

    def GetResources(self):
        return {"Pixmap": icon(self.icon_name), "MenuText": self.name, "ToolTip": self.tooltip}

    def Activated(self):
        doc = _doc()
        part = active.active_part(doc)
        items = _picked_items(part, ("Face",))
        doc.openTransaction(self.name)
        obj = self.create(doc, part, items or None)
        _edit_new(doc, obj)


class SplitLineTool(FaceTool):
    """Split Line: preselected faces are the faces to split; a selected sketch is
    projected (Projection)."""

    def __init__(self):
        from ..app import faceops as app_faceops
        super(SplitLineTool, self).__init__(
            "Split Line", "SplitLine",
            "Splits faces into more faces, without changing the body: by a projected sketch, "
            "where planes cut them, or along their silhouette.",
            app_faceops.create_split_line)

    def Activated(self):
        doc = _doc()
        part = active.active_part(doc)
        items = _picked_items(part, ("Face",))
        sketch = next((s for s in Gui.Selection.getSelection()
                       if s.TypeId.startswith("Sketcher::SketchObject")), None)
        doc.openTransaction(self.name)
        obj = self.create(doc, part, items or None, sketch)
        if sketch is not None:
            sketch.ViewObject.Visibility = False
        _edit_new(doc, obj)


class ThreadTool(object):
    """Thread: a preselected circular edge is where it starts."""

    def GetResources(self):
        return {"Pixmap": icon("Thread"), "MenuText": "Thread",
                "ToolTip": "Models a helical thread on a shaft or in a hole, starting at a "
                           "circular edge: cut into it, or grown out of it."}

    def IsActive(self):
        doc = _doc()
        return doc is not None and not Gui.Control.activeDialog() and \
            bool(part_mod.find_parts(doc))

    def Activated(self):
        from ..app import thread as app_thread
        doc = _doc()
        part = active.active_part(doc)
        edge = None
        for name in _picked_items(part, ("Edge",)):
            e = part.Tip.getSubObject(name) if part.Tip is not None else None
            if e is not None and hasattr(e.Curve, "Radius"):
                edge = (part.Tip, name)
                break
        doc.openTransaction("Thread")
        obj = app_thread.create(doc, part, edge)
        _edit_new(doc, obj)


class DraftTool(EdgeTool):
    """Draft: preselected faces are the faces to draft; a preselected plane is
    the neutral plane (SolidWorks takes both)."""

    def __init__(self):
        super(DraftTool, self).__init__(
            "Draft", "Tapers faces by an angle so the part releases from a mould: about a "
            "neutral plane, or about parting lines.", app_dressup.create_draft, kinds=("Face",))

    def Activated(self):
        doc = _doc()
        part = active.active_part(doc)
        planes = []
        for s in Gui.Selection.getSelectionEx(doc.Name):
            o = s.Object
            if o.TypeId == "Part::DatumPlane" or (util.role(o) == "refgeom" and
                                                  o.Proxy.KIND == "plane"):
                planes.append(o)
        items = _picked_items(part, self.kinds)
        doc.openTransaction(self.name)
        obj = self.create(doc, part, items or None)
        if planes:
            from ..app import refs
            refs.set_ref(obj, "NeutralPlane", planes[0], "")
        _edit_new(doc, obj)


def _classify(o, sub):
    """What a preselected item is, for guessing a Plane or Axis type."""
    if o.TypeId == "Part::DatumPlane" or (util.role(o) == "refgeom" and o.Proxy.KIND == "plane"):
        return "plane", (o, "")
    if o.TypeId == "Part::DatumLine" or (util.role(o) == "refgeom" and o.Proxy.KIND == "axis"):
        return "line", (o, "")
    if o.TypeId == "Part::DatumPoint" or (util.role(o) == "refgeom" and o.Proxy.KIND == "point"):
        return "point", (o, "")
    if not sub:
        return None, None
    el = o.getSubObject(sub)
    kind = None
    if sub.startswith("Face"):
        st = el.Surface.TypeId
        kind = "plane" if st == "Part::GeomPlane" else (
            "round" if st in ("Part::GeomCylinder", "Part::GeomCone") else None)
    elif sub.startswith("Edge"):
        kind = "line" if el.Curve.TypeId in ("Part::GeomLine", "Part::GeomLineSegment") \
            else "curve"
    elif sub.startswith("Vertex"):
        kind = "point"
    if kind is None:
        return None, None
    if util.is_body_view(o):
        from .selection import map_to_feature
        part = part_mod.source_part(o)
        name = map_to_feature(el, part.Tip) if part.Tip is not None else None
        return (kind, (part.Tip, name)) if name else (None, None)
    return kind, (o, sub)




POINT_GUESS = [(("point",), "On Point"), (("curve",), "Arc Center"),
               (("plane",), "Center of Face"), (("round",), "Center of Face"),
               (("line", "plane"), "Intersection"), (("curve", "plane"), "Intersection"),
               (("point", "plane"), "Projection"), (("line",), "Along Curve Distance")]

REFGEOM = {
    "plane": ("Plane", "Plane", "Adds a reference plane."),
    "axis": ("Axis", "Axis", "Adds a reference axis."),
    "point": ("Point", "Point", "Adds a reference point: an arc's centre, a face's centre, "
              "where an edge meets a face, a projection, or a distance along an edge."),
    "helix": ("Helix/Spiral", "Helix",
              "Adds a helix or spiral from a circle (a sketch with one circle, or a circular "
              "edge): a path for springs and threads."),
    "csys": ("Coordinate System", "CoordinateSystem",
             "Adds a coordinate system from an origin and X and Y directions (all optional). "
             "Sketches can be attached to it."),
    "bbox": ("Bounding Box", "BoundingBox",
             "Adds a box round the bodies: the smallest one, or one square to a plane. Its "
             "length, width and thickness follow the model."),
    "cosmetic": ("Cosmetic Thread", "CosmeticThread",
                 "Shows a thread on a shaft or in a hole without modelling it: pick the "
                 "circular edge where it starts."),
    "com": ("Center of Mass", "CenterOfMass",
            "Adds a point at the solid bodies' centre of mass; it follows the model and can "
            "be used like any point."),
}


class RefGeomTool(object):
    """Plane, Axis: the type is guessed from what is preselected (as SolidWorks
    guesses its constraints)."""

    def __init__(self, kind):
        self.kind = kind

    def GetResources(self):
        text, icon_name, tip = REFGEOM[self.kind]
        return {"Pixmap": icon(icon_name), "MenuText": text, "ToolTip": tip}

    def IsActive(self):
        return _doc() is not None and not Gui.Control.activeDialog()

    def Activated(self):
        from ..app import refgeom as app_refgeom
        from ..core import refgeom as core_ref
        doc = _doc()
        part = active.active_part(doc)
        picks = []
        for s in Gui.Selection.getSelectionEx():
            subs = s.SubElementNames or [""]
            for sub in subs:
                k, ref = _classify(s.Object, sub)
                if k is not None:
                    picks.append((k, ref))
        kinds = tuple(k for k, _r in picks)
        doc.openTransaction(REFGEOM[self.kind][0])
        if self.kind == "helix":
            circle = None
            for s in Gui.Selection.getSelectionEx():
                o = s.Object
                if o.TypeId.startswith("Sketcher::SketchObject") and not s.SubElementNames:
                    circle = (o, "")
                for sub in s.SubElementNames:
                    k, ref = _classify(o, sub)
                    if k == "curve" and hasattr(o.getSubObject(sub).Curve, "Radius"):
                        circle = ref
            obj = app_refgeom.create_helix(doc, part, None, [circle] if circle else [])
            if circle and circle[0].TypeId.startswith("Sketcher::SketchObject"):
                circle[0].ViewObject.Visibility = False
        elif self.kind == "cosmetic":
            edge = next((r for k, r in picks if k == "curve" and
                         hasattr(r[0].getSubObject(r[1]).Curve, "Radius")), None) \
                if picks else None
            obj = app_refgeom.create_cosmetic_thread(doc, part, edge)
        elif self.kind in ("bbox", "com"):
            ids = _selected_bodies(part)
            plane = next((r for k, r in picks if k == "plane"), None)
            if self.kind == "bbox":
                obj = app_refgeom.create_bounding_box(
                    doc, part, core_ref.REFERENCE_PLANE if plane else None,
                    [plane] if plane else [], ids)
            else:
                obj = app_refgeom.create_centre_of_mass(doc, part, ids)
        elif self.kind == "csys":
            # The first point is the origin; the first two directions are X and Y.
            origin = next((r for k, r in picks if k == "point"), None)
            dirs = [r for k, r in picks if k in ("line", "plane")][:2]
            dirs += [None] * (2 - len(dirs))
            obj = app_refgeom.create_csys(doc, part, None, [origin] + dirs)
        elif self.kind == "plane":
            # Up to three references in the order picked; their constraints are
            # guessed from what they are, as SolidWorks does.
            obj = app_refgeom.create_plane(doc, part, None, [r for _k, r in picks][:3])
        elif self.kind == "axis":
            # The type is guessed from what the references are, in either order.
            # A picked temporary axis counts as its face or edge.
            if not picks:
                from . import temp_axis
                ta = temp_axis.current()
                src = ta.picked() if ta is not None else None
                if src is not None:
                    k, ref = _classify(*src)
                    if k is not None:
                        picks = [(k, ref)]
                        ta.used()
            obj = app_refgeom.create_axis(doc, part, None, [r for _k, r in picks][:2])
        else:
            guesses = {"point": POINT_GUESS}[self.kind]
            kind = None
            for pattern, name in guesses:
                if pattern == kinds:
                    kind = name
                    break
            make = app_refgeom.create_point
            obj = make(doc, part, kind, [r for _k, r in picks] if kind else [])
        from . import viewproviders
        viewproviders.attach_refgeom(obj, new=True)
        doc.recompute()
        Gui.Selection.clearSelection()
        Gui.ActiveDocument.setEdit(obj.Name, 0)


def _selected_bodies(part):
    out = []
    for s in Gui.Selection.getSelection():
        if util.is_body_view(s) and part_mod.source_part(s) is part and s.BodyId in part.BodyIds:
            if s.BodyId not in out:
                out.append(s.BodyId)
    return out


def _selected_features(part):
    feats = util.features(part)
    return [s for s in Gui.Selection.getSelection()
            if s in feats and "ToolShape" in s.PropertiesList]


def _selected_plane_ref(part):
    """A selected plane or planar face, as a reference on the model at the bar."""
    for k, ref in [_classify(s.Object, sub) for s in Gui.Selection.getSelectionEx()
                   for sub in (s.SubElementNames or [""])]:
        if k == "plane":
            return ref
    return None


class ToolCommand(object):
    """A feature command that fills its panel from the selection."""

    def __init__(self, name, icon_name, tooltip, create, prefill=None, menu_text=None):
        self.name = name
        self.icon_name = icon_name
        self.tooltip = tooltip
        self.create = create
        self.prefill = prefill
        self.menu_text = menu_text or name

    def GetResources(self):
        return {"Pixmap": icon(self.icon_name), "MenuText": self.menu_text,
                "ToolTip": self.tooltip}

    def IsActive(self):
        doc = _doc()
        return doc is not None and not Gui.Control.activeDialog() and \
            bool(part_mod.find_parts(doc))

    def Activated(self):
        doc = _doc()
        part = active.active_part(doc)
        props = self.prefill(part) if self.prefill else {}
        doc.openTransaction(self.menu_text)
        obj = self.create(doc, part, **{k: v for k, v in props.items() if not k.startswith("_")})
        for k, v in props.items():
            if k.startswith("_ref_"):
                refs.set_ref(obj, k[5:], v[0], v[1])
        _edit_new(doc, obj)


class CurveTool(ToolCommand):
    """Insert > Curve: a curve in the history (reference geometry, not a body)."""

    def Activated(self):
        doc = _doc()
        part = active.active_part(doc)
        props = self.prefill(part) if self.prefill else {}
        doc.openTransaction(self.menu_text)
        obj = self.create(doc, part, **props)
        obj.ViewObject.Proxy._new = True
        doc.recompute()
        Gui.Selection.clearSelection()
        Gui.ActiveDocument.setEdit(obj.Name, 0)


def _bodies_prefill(prop="Bodies"):
    def fn(part):
        ids = _selected_bodies(part)
        return {prop: ids} if ids else {}
    return fn


def _pattern_prefill(part):
    out = {}
    feats = _selected_features(part)
    if feats:
        out["Features"] = feats
    ids = _selected_bodies(part)
    if ids:
        out["Bodies"] = ids
    return out


def _mirror_prefill(part):
    out = _pattern_prefill(part)
    ref = _selected_plane_ref(part)
    if ref is not None:
        out["_ref_MirrorPlane"] = ref
    return out


def _split_prefill(part):
    out = {}
    tools = [s for s in Gui.Selection.getSelection()
             if s.TypeId.startswith("Sketcher::SketchObject") or s.TypeId == "Part::DatumPlane"
             or (util.role(s) == "refgeom" and s.Proxy.KIND == "plane")]
    if tools:
        out["TrimTools"] = tools
    ids = _selected_bodies(part)
    if ids:
        out["TargetBodies"] = ids
    return out


def _items_prefill(kind):
    def fn(part):
        items = _picked_items(part, (kind,))
        return {"Items": items} if items else {}
    return fn


def _planar_prefill(part):
    out = _items_prefill("Edge")(part)
    sk = next((s for s in Gui.Selection.getSelection()
               if s.TypeId.startswith("Sketcher::SketchObject")), None)
    if sk is not None:
        out["Sketch"] = sk
    return out


def _trim_prefill(part):
    out = {}
    tools = [s for s in Gui.Selection.getSelection()
             if s.TypeId.startswith("Sketcher::SketchObject") or s.TypeId == "Part::DatumPlane"
             or (util.role(s) == "refgeom" and s.Proxy.KIND == "plane")]
    if tools:
        out["TrimTools"] = tools
    return out


def _thicken_prefill(mode):
    def fn(part):
        out = {"Mode": mode}
        ids = [i for i in _selected_bodies(part)]
        for s in Gui.Selection.getSelection():
            if util.is_body_view(s) and s.BodyId in ids and s.Kind == "surface":
                out["Body"] = s.BodyId
                break
        return out
    return fn


def _indent_prefill(part):
    """The first body picked is the target, the second the tool."""
    ids = _selected_bodies(part)
    out = {}
    if ids:
        out["TargetBody"] = ids[0]
    if len(ids) > 1:
        out["ToolBody"] = ids[1]
    return out


def _deform_prefill(part):
    """A clicked point on a body is the deform point."""
    out = {}
    for se in Gui.Selection.getSelectionEx("", 0):
        pts = list(getattr(se, "PickedPoints", []) or [])
        subs = list(se.SubElementNames)
        if pts and subs and util.is_body_view(se.Object):
            out["DeformPoint"] = pts[-1]
            break
    return out


def _variable_prefill(part):
    feats = _selected_features(part)
    return {"Features": feats[:1]} if feats else {}


def _fastening(name):
    def fn(doc, part, **props):
        from ..app import fastening
        return getattr(fastening, name)(doc, part, **props)
    return fn


def _placed_prefill(part):
    """A face clicked on a body places a boss or hook where it was clicked."""
    out = {}
    for se in Gui.Selection.getSelectionEx("", 0):
        pts = list(getattr(se, "PickedPoints", []) or [])
        subs = list(se.SubElementNames)
        if pts and subs and subs[-1].startswith("Face") and util.is_body_view(se.Object):
            items = _picked_items(part, ("Face",))
            if items:
                from ..app.surfaces import vec_text
                out["Items"] = items[:1]
                out["Position"] = vec_text(pts[-1])
            break
    return out


def _lip_prefill(part):
    ids = _selected_bodies(part)
    out = {}
    if ids:
        out["GrooveBody"] = ids[0]
    if len(ids) > 1:
        out["LipBody"] = ids[1]
    return out


def _vent_prefill(part):
    sk = next((s for s in Gui.Selection.getSelection()
               if s.TypeId.startswith("Sketcher::SketchObject")), None)
    return {"Sketch": sk} if sk is not None else {}


class FasteningGroup(object):
    """Fastening Features: one toolbar button with a drop-down (SolidWorks' flyout)."""

    def GetCommands(self):
        return ("SD_MountingBoss", "SD_SnapHook", "SD_LipGroove", "SD_Vent")

    def GetDefaultCommand(self):
        return 0

    def GetResources(self):
        return {"Pixmap": icon("MountingBoss"), "MenuText": "Fastening Features",
                "ToolTip": "Mounting boss, snap hook, lip/groove or vent.",
                "DropDownMenu": True, "Exclusive": False}

    def IsActive(self):
        return _doc() is not None and not Gui.Control.activeDialog()


class ThreadGroup(object):
    def GetCommands(self):
        return ("SD_Thread", "SD_CosmeticThread")

    def GetDefaultCommand(self):
        return 0

    def GetResources(self):
        return {"Pixmap": icon("Thread"), "MenuText": "Threads",
                "ToolTip": "A modelled thread, or a cosmetic one.",
                "DropDownMenu": True, "Exclusive": False}

    def IsActive(self):
        return _doc() is not None and not Gui.Control.activeDialog()


def _deform(name):
    def fn(doc, part, **props):
        from ..app import deform
        return getattr(deform, name)(doc, part, **props)
    return fn


class DeformGroup(object):
    def GetCommands(self):
        return ("SD_Flex", "SD_Deform", "SD_Indent", "SD_Freeform", "SD_Scale")

    def GetDefaultCommand(self):
        return 0

    def GetResources(self):
        return {"Pixmap": icon("Flex"), "MenuText": "Deform Bodies",
                "ToolTip": "Flex, Deform, Indent, Freeform or Scale bodies.",
                "DropDownMenu": True, "Exclusive": False}

    def IsActive(self):
        return _doc() is not None and not Gui.Control.activeDialog()


def _s2(name):
    def fn(doc, part, **props):
        from ..app import surfaces2
        return getattr(surfaces2, name)(doc, part, **props)
    return fn


def _surface_cut_prefill(part):
    out = {}
    for s in Gui.Selection.getSelection():
        if util.is_body_view(s) and s.Kind == "surface":
            out["CuttingBody"] = s.BodyId
            break
    planes = [s for s in Gui.Selection.getSelection()
              if s.TypeId == "Part::DatumPlane"
              or (util.role(s) == "refgeom" and s.Proxy.KIND == "plane")]
    if planes and "CuttingBody" not in out:
        out["_ref_CuttingPlane"] = (planes[0], [])
    return out


class MoreSurfacesGroup(object):
    """The less used surface tools, in one drop-down."""

    def GetCommands(self):
        return ("SD_RuledSurface", "SD_RadiateSurface", "SD_UntrimSurface", "SD_MidSurface",
                "SD_SurfaceFlatten")

    def GetDefaultCommand(self):
        return 0

    def GetResources(self):
        return {"Pixmap": icon("RuledSurface"), "MenuText": "More Surfaces",
                "ToolTip": "Ruled, Radiate, Untrim, Mid-Surface and Surface Flatten.",
                "DropDownMenu": True, "Exclusive": False}

    def IsActive(self):
        return _doc() is not None and not Gui.Control.activeDialog()


def _more(name):
    def fn(doc, part, **props):
        from ..app import morefeatures
        return getattr(morefeatures, name)(doc, part, **props)
    return fn


def _intersect_prefill(part):
    out = {}
    ids = _selected_bodies(part)
    if ids:
        out["Bodies"] = ids
    planes = [s for s in Gui.Selection.getSelection()
              if s.TypeId == "Part::DatumPlane"
              or (util.role(s) == "refgeom" and s.Proxy.KIND == "plane")]
    if planes:
        out["Planes"] = planes
    return out


def _wrap_prefill(part):
    out = _items_prefill("Face")(part)
    if "Items" in out:
        out["Items"] = out["Items"][:1]
    sk = next((s for s in Gui.Selection.getSelection()
               if s.TypeId.startswith("Sketcher::SketchObject")), None)
    if sk is not None:
        out["Sketch"] = sk
    return out


def _projected_prefill(part):
    out = {}
    sks = [s for s in Gui.Selection.getSelection() if s.TypeId.startswith("Sketcher::")]
    if sks:
        out["Sketch"] = sks[0]
    if len(sks) > 1:
        out["Sketch2"] = sks[1]
        out["Type"] = "Sketch on sketch"
    faces = _picked_items(part, ("Face",))
    if faces:
        out["_ref_Faces"] = (part.Tip, faces)
    return out


def _composite_prefill(part):
    out = {}
    objs = [s for s in Gui.Selection.getSelection() if util.is_curve(s)]
    if objs:
        out["Curves"] = objs
    edges = _picked_items(part, ("Edge",))
    if edges:
        out["_ref_Edges"] = (part.Tip, edges)
    return out


def _points_curve_prefill(part):
    out = {}
    pts = [s for s in Gui.Selection.getSelection()
           if util.role(s) == "refgeom" and s.Proxy.KIND == "point"]
    if pts:
        out["PointObjects"] = pts
    verts = _picked_items(part, ("Vertex",))
    if verts:
        out["_ref_Vertices"] = (part.Tip, verts)
    return out


def _first_sketch():
    return next((s for s in Gui.Selection.getSelection()
                 if s.TypeId.startswith("Sketcher::SketchObject")), None)


def _curve_prefill(part):
    out = _pattern_prefill(part)
    sk = _first_sketch()
    if sk is not None:
        out["CurveSketch"] = sk
    else:
        edges = _picked_items(part, ("Edge",))
        if edges:
            out["_ref_Curve"] = (part.Tip, edges)
    return out


def _sketch_pat_prefill(part):
    out = _pattern_prefill(part)
    sk = _first_sketch()
    if sk is not None:
        out["Sketch"] = sk
    return out


def _fill_prefill(part):
    out = _pattern_prefill(part)
    faces = _picked_items(part, ("Face",))
    if faces:
        out["_ref_Boundary"] = (part.Tip, faces[:1])
    return out


def _hole_create(doc, part, **props):
    from ..app import hole as app_hole
    sk = props.pop("Sketch", None)
    return app_hole.create(doc, part, sk, **props)


def _hole_prefill(part):
    for s in Gui.Selection.getSelection():
        if s.TypeId.startswith("Sketcher::SketchObject"):
            return {"Sketch": s}
    return {}


class RefGeomGroup(object):
    """Reference Geometry: one toolbar button with a drop-down (SolidWorks' flyout),
    Plane first and the default."""

    def GetCommands(self):
        return ("SD_Plane", "SD_Axis", "SD_CoordinateSystem", "SD_Point", "SD_BoundingBox",
                "SD_CenterOfMass")

    def GetDefaultCommand(self):
        return 0

    def GetResources(self):
        return {"Pixmap": icon("Plane"), "MenuText": "Reference Geometry",
                "ToolTip": "Adds reference geometry: a plane, an axis, a coordinate system, "
                           "a point, a bounding box or the centre of mass.",
                "DropDownMenu": True, "Exclusive": False}

    def IsActive(self):
        return _doc() is not None and not Gui.Control.activeDialog()


class CurvesGroup(object):
    """Insert > Curve as one toolbar button with a drop-down (SolidWorks' Curves
    flyout)."""

    def GetCommands(self):
        return ("SD_SplitLine", "SD_ProjectedCurve", "SD_CompositeCurve", "SD_CurveXYZ",
                "SD_CurvePoints", "SD_Helix")

    def GetDefaultCommand(self):
        return 0

    def GetResources(self):
        return {"Pixmap": icon("SplitLine"), "MenuText": "Curves",
                "ToolTip": "Curves: split line, projected, composite, through points, "
                           "helix/spiral.",
                "DropDownMenu": True, "Exclusive": False}

    def IsActive(self):
        return _doc() is not None and not Gui.Control.activeDialog()


class PatternGroup(object):
    """Linear Pattern with a drop-down of the other patterns (SolidWorks' flyout)."""

    def GetCommands(self):
        return ("SD_LinearPattern", "SD_CircularPattern", "SD_CurvePattern",
                "SD_SketchPattern", "SD_TablePattern", "SD_FillPattern", "SD_VariablePattern")

    def GetDefaultCommand(self):
        return 0

    def GetResources(self):
        return {"Pixmap": icon("LinearPattern"), "MenuText": "Patterns",
                "ToolTip": "Repeats features, faces or bodies: in lines, round an axis, along "
                           "a curve, at sketch points, from a table, or filling a face.",
                "DropDownMenu": True, "Exclusive": False}

    def IsActive(self):
        return _doc() is not None and not Gui.Control.activeDialog()


GROUPS = set()      # the toolbar drop-downs (not tools themselves)


def register():
    Gui.addCommand("SD_Part", NewPart())
    Gui.addCommand("SD_Sketch", NewSketch())
    Gui.addCommand("SD_Extrude", SketchTool(
        "Extrude", "ExtrudeAdd",
        "Extrudes a sketch or selected sketch contours in one or two directions to add "
        "material, or to cut it (Add | Cut in the panel).", app_extrude.create))
    Gui.addCommand("SD_Revolve", SketchTool(
        "Revolve", "RevolveAdd",
        "Revolves a sketch or selected sketch contours around an axis to add material, or to "
        "cut it (Add | Cut in the panel).", app_revolve.create))
    from ..app import sweep as app_sweep
    Gui.addCommand("SD_Sweep", SketchTool(
        "Sweep", "SweepAdd",
        "Sweeps a profile along a path to add material, or to cut it (Add | Cut in the "
        "panel).", app_sweep.create_sweep))
    Gui.addCommand("SD_Loft", SketchTool(
        "Loft", "LoftAdd",
        "Adds or cuts material between two or more profiles (Add | Cut in the panel).",
        app_sweep.create_loft))
    Gui.addCommand("SD_Boundary", SketchTool(
        "Boundary", "BoundaryAdd",
        "Adds or cuts material through curves in one or two directions (Add | Cut in the "
        "panel); with curves both ways the shape passes through the whole network.",
        app_sweep.create_boundary))
    for cmd, name, icon_name, what, create in (
            ("SD_ExtrudedSurface", "Extruded Surface", "ExtrudeSurface",
             "Extrudes a sketch's curves (open or closed) into a surface body.",
             app_extrude.create),
            ("SD_RevolvedSurface", "Revolved Surface", "RevolveSurface",
             "Revolves a sketch's curves around an axis into a surface body.",
             app_revolve.create),
            ("SD_SweptSurface", "Swept Surface", "SweepSurface",
             "Sweeps a profile's curves along a path into a surface body.",
             app_sweep.create_sweep),
            ("SD_LoftedSurface", "Lofted Surface", "LoftSurface",
             "Makes a surface body between two or more profiles.", app_sweep.create_loft),
            ("SD_BoundarySurface", "Boundary Surface", "BoundarySurface",
             "Makes a surface body through curves in one or two directions.",
             app_sweep.create_boundary)):
        Gui.addCommand(cmd, SketchTool(name, icon_name, what + " Surface in the feature's "
                                       "Add | Cut | Surface switch.", create, "Surface"))
    Gui.addCommand("SD_Shell", EdgeTool(
        "Shell", "Hollows a body, leaving open the faces you pick, with walls of the given "
        "thickness.", app_dressup.create_shell, kinds=("Face",)))
    from ..app import rib as app_rib
    Gui.addCommand("SD_Rib", SketchTool(
        "Rib", "Rib",
        "Grows a wall of material from open sketch lines until it meets the model: in the "
        "sketch plane, or out of it.", app_rib.create))
    Gui.addCommand("SD_Draft", DraftTool())
    Gui.addCommand("SD_Thread", ThreadTool())
    from ..app import faceops as app_faceops
    Gui.addCommand("SD_OffsetSurface", FaceTool(
        "Offset Surface", "OffsetSurface",
        "Offsets faces or surfaces by a distance into a new surface body (0: a copy).",
        app_faceops.create_offset_surface))
    Gui.addCommand("SD_SplitLine", SplitLineTool())
    Gui.addCommand("SD_MoveFace", FaceTool(
        "Move Face", "MoveFace",
        "Moves faces of a solid (offset, translate or rotate); the faces around them extend or "
        "trim to follow.", app_faceops.create_move_face))
    Gui.addCommand("SD_Fillet", EdgeTool(
        "Fillet", "Creates a rounded internal or external face along one or more edges.",
        app_dressup.create_fillet))
    Gui.addCommand("SD_Chamfer", EdgeTool(
        "Chamfer", "Creates a bevel on selected edges, faces or a vertex.",
        app_dressup.create_chamfer))
    from ..app import bodytools, pattern
    tools = [
        ("SD_Combine", "Combine", "Combine", "Combines bodies: adds them, subtracts some from "
         "a main body, or keeps what they have in common.", bodytools.create_combine,
         _bodies_prefill()),
        ("SD_DeleteBody", "DeleteBody", "Delete/Keep Body", "Deletes the selected bodies, or "
         "keeps only them.", bodytools.create_delete, _bodies_prefill()),
        ("SD_Split", "Split", "Split", "Splits bodies with planes, faces, surface bodies or "
         "sketches into separate bodies.", bodytools.create_split, _split_prefill),
        ("SD_MoveCopy", "MoveCopy", "Move/Copy Body", "Moves or copies bodies by a "
         "translation and a rotation.", bodytools.create_move, _bodies_prefill()),
        ("SD_LinearPattern", "LinearPattern", "Linear Pattern", "Repeats features or bodies "
         "in one or two directions.", pattern.create_linear, _pattern_prefill),
        ("SD_CircularPattern", "CircularPattern", "Circular Pattern", "Repeats features or "
         "bodies around an axis.", pattern.create_circular, _pattern_prefill),
        ("SD_Mirror", "Mirror", "Mirror", "Mirrors features or bodies about a face or plane.",
         pattern.create_mirror, _mirror_prefill),
        ("SD_CurvePattern", "CurvePattern", "Curve Driven Pattern", "Repeats features or "
         "bodies along a curve.", pattern.create_curve, _curve_prefill),
        ("SD_SketchPattern", "SketchPattern", "Sketch Driven Pattern", "Repeats features or "
         "bodies at a sketch's points.", pattern.create_sketch_pattern, _sketch_pat_prefill),
        ("SD_TablePattern", "TablePattern", "Table Driven Pattern", "Repeats features or "
         "bodies at X, Y positions you type in.", pattern.create_table, _pattern_prefill),
        ("SD_FillPattern", "FillPattern", "Fill Pattern", "Fills a face with features, or "
         "with cuts of a simple shape, in rows or rings.", pattern.create_fill,
         _fill_prefill),
        ("SD_VariablePattern", "VariablePattern", "Variable Pattern", "Repeats a feature "
         "with its dimensions changed per instance, from a table: position, size or depth.",
         pattern.create_variable, _variable_prefill),
        ("SD_HoleWizard", "HoleWizard", "Hole Wizard", "Inserts holes of a standard type "
         "and size at points on a face or a sketch.", _hole_create, _hole_prefill),
    ]
    from ..app import refgeom as app_ref
    curve_tools = [
        ("SD_ProjectedCurve", "ProjectedCurve", "Projected Curve", "Projects a sketch onto "
         "faces, or makes the curve where two sketches on crossing planes meet.",
         app_ref.create_projected_curve, _projected_prefill),
        ("SD_CompositeCurve", "CompositeCurve", "Composite Curve", "Joins edges and sketch "
         "curves end to end into one curve.", app_ref.create_composite_curve,
         _composite_prefill),
        ("SD_CurveXYZ", "CurveXYZ", "Curve Through XYZ Points", "A smooth curve through "
         "points you type.", app_ref.create_xyz_curve, None),
        ("SD_CurvePoints", "CurvePoints", "Curve Through Reference Points", "A smooth curve "
         "through vertices and reference points.", app_ref.create_points_curve,
         _points_curve_prefill),
    ]
    for cmd, icon_name, text, tip, create, prefill in curve_tools:
        Gui.addCommand(cmd, CurveTool(text, icon_name, tip, create, prefill))
    from ..app import surfaces as app_surf
    tools += [
        ("SD_Knit", "Knit", "Knit Surface", "Knits surfaces into one; closed, it can become "
         "a solid.", app_surf.create_knit, _bodies_prefill()),
        ("SD_PlanarSurface", "PlanarSurface", "Planar Surface", "Makes a flat surface inside "
         "a sketch's closed regions or closed, flat loops of edges.", app_surf.create_planar,
         _planar_prefill),
        ("SD_FilledSurface", "FilledSurface", "Filled Surface", "Patches a closed loop of "
         "edges with a surface, touching or tangent to the faces around it.",
         app_surf.create_filled, _items_prefill("Edge")),
        ("SD_TrimSurface", "TrimSurface", "Trim Surface", "Trims surfaces with a plane, "
         "sketch or surface, or with each other; click the pieces to keep or remove.",
         app_surf.create_trim, _trim_prefill),
        ("SD_ExtendSurface", "ExtendSurface", "Extend Surface", "Extends a surface past its "
         "open edges, on the same surface or straight on.", app_surf.create_extend,
         _items_prefill("Edge")),
        ("SD_DeleteFace", "DeleteFace", "Delete Face", "Deletes faces: leaves a gap (the body "
         "becomes a surface), heals it from the faces around, or fills it.",
         app_surf.create_delete_face, _items_prefill("Face")),
        ("SD_Intersect", "Intersect", "Intersect", "Makes solid bodies from the regions "
         "where solids, surfaces and planes meet; exclude the regions you don't want.",
         _more("create_intersect"), _intersect_prefill),
        ("SD_Dome", "Dome", "Dome", "Adds a dome (or a dent) on flat faces.",
         _more("create_dome"), _items_prefill("Face")),
        ("SD_Wrap", "Wrap", "Wrap", "Wraps a sketch onto a cylindrical or flat face: "
         "emboss, deboss or scribe it.", _more("create_wrap"), _wrap_prefill),
        ("SD_RuledSurface", "RuledSurface", "Ruled Surface", "Strips standing off edges: "
         "tangent or normal to the faces, or at an angle to a direction.",
         _s2("create_ruled"), _items_prefill("Edge")),
        ("SD_RadiateSurface", "RadiateSurface", "Radiate Surface", "A surface spreading "
         "outward from edges, parallel to a plane (a parting surface).",
         _s2("create_radiate"), _items_prefill("Edge")),
        ("SD_UntrimSurface", "UntrimSurface", "Untrim Surface", "A face back to the surface "
         "it lies on: holes filled, or grown past its edges.", _s2("create_untrim"),
         _items_prefill("Face")),
        ("SD_MidSurface", "MidSurface", "Mid-Surface", "Surfaces midway between the two "
         "sides of thin walls.", _s2("create_mid_surface"), _bodies_prefill()),
        ("SD_SurfaceCut", "SurfaceCut", "Cut With Surface", "Cuts bodies with a surface or "
         "plane, keeping one side.", _s2("create_cut_with_surface"), _surface_cut_prefill),
        ("SD_ReplaceFace", "ReplaceFace", "Replace Face", "Replaces faces of a solid with a "
         "surface: the solid grows out to it or is trimmed back.",
         _s2("create_replace_face"), _items_prefill("Face")),
        ("SD_Flex", "Flex", "Flex", "Bends, twists, tapers or stretches bodies along an "
         "axis.", _deform("create_flex"), _bodies_prefill()),
        ("SD_Scale", "Scale", "Scale", "Scales bodies about their centre, the origin or a "
         "coordinate system.", _deform("create_scale"), _bodies_prefill()),
        ("SD_Deform", "Deform", "Deform", "Pushes a point, moves curves onto others, or "
         "pushes a tool body in, and the body follows smoothly.", _deform("create_deform"),
         _deform_prefill),
        ("SD_Indent", "Indent", "Indent", "Presses a tool body's shape into a target body, "
         "with a wall round it, or cuts it in.", _deform("create_indent"), _indent_prefill),
        ("SD_Freeform", "Freeform", "Freeform", "Pushes or pulls a face at points you place "
         "on it; its edges stay put.", _deform("create_freeform"), _items_prefill("Face")),
        ("SD_SurfaceFlatten", "SurfaceFlatten", "Surface Flatten", "Lays faces out flat as "
         "a new surface body.", _deform("create_flatten"), _items_prefill("Face")),
        ("SD_MountingBoss", "MountingBoss", "Mounting Boss", "Adds a round boss on a face, "
         "with a hole or a pin and optional fins: click where it goes.",
         _fastening("create_mounting_boss"), _placed_prefill),
        ("SD_SnapHook", "SnapHook", "Snap Hook", "Adds a snap hook (a beam with a catch on its "
         "tip) on a face: click where it goes.", _fastening("create_snap_hook"),
         _placed_prefill),
        ("SD_LipGroove", "LipGroove", "Lip/Groove", "Where two bodies meet on a flat face, "
         "grows a lip out of one and cuts a matching groove in the other.",
         _fastening("create_lip_groove"), _lip_prefill),
        ("SD_Vent", "Vent", "Vent", "Cuts a vent from a sketch: its outer loop opens the "
         "wall, its lines stay as ribs and its inner loops as spars.",
         _fastening("create_vent"), _vent_prefill),
        ("SD_Thicken", "Thicken", "Thicken", "Thickens a surface body into a solid, or cuts "
         "the solids with it (Add | Cut in the panel).",
         app_surf.create_thicken, _thicken_prefill("Add")),
    ]
    for cmd, icon_name, text, tip, create, prefill in tools:
        Gui.addCommand(cmd, ToolCommand(text, icon_name, tip, create, prefill, text))
    Gui.addCommand("SD_Plane", RefGeomTool("plane"))
    Gui.addCommand("SD_Axis", RefGeomTool("axis"))
    Gui.addCommand("SD_Point", RefGeomTool("point"))
    Gui.addCommand("SD_CoordinateSystem", RefGeomTool("csys"))
    Gui.addCommand("SD_Helix", RefGeomTool("helix"))
    Gui.addCommand("SD_BoundingBox", RefGeomTool("bbox"))
    Gui.addCommand("SD_CosmeticThread", RefGeomTool("cosmetic"))
    Gui.addCommand("SD_CenterOfMass", RefGeomTool("com"))
    for name, group in (("SD_ReferenceGeometry", RefGeomGroup()),
                        ("SD_Patterns", PatternGroup()), ("SD_Curves", CurvesGroup()),
                        ("SD_MoreSurfaces", MoreSurfacesGroup()),
                        ("SD_DeformBodies", DeformGroup()),
                        ("SD_Fastening", FasteningGroup()), ("SD_Threads", ThreadGroup())):
        GROUPS.add(name)
        Gui.addCommand(name, group)
    from . import command_line, command_search
    Gui.addCommand("SD_CommandSearch", command_search.SearchCommand())
    Gui.addCommand("SD_CommandLine", command_line.LineCommand())
    Gui.addCommand("SD_RepeatLast", command_line.RepeatCommand())
