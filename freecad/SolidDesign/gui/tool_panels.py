# SPDX-License-Identifier: LGPL-2.1-or-later
"""Panels for the body tools, patterns, mirror and the Hole Wizard.

They all show the model before the feature while open (EDIT_SHOWS_BASE), so the
bodies and faces to pick are the ones the feature works on; the result is the
green preview (red for the Hole Wizard, whose preview is the material removed).
"""

import json

import FreeCAD as App
import Part
from PySide import QtCore, QtWidgets

from .. import icon
from ..app import part as part_mod
from ..app import refs, util
from ..core import bodyops, regions
from ..core.features import hole as core_hole
from . import preview as pv
from . import selection as selmod
from .panel import parts
from .panel.base import FeaturePanel
from .sketch_panel import LAST

__all__ = ["CombinePanel", "DeleteBodyPanel", "SplitPanel", "MoveCopyPanel",
           "LinearPatternPanel", "CircularPatternPanel", "MirrorPanel", "HolePanel"]


def body_name_before(obj, bid):
    """A body's name as it is just before ``obj`` (what the user sees while the
    panel shows the model before the feature)."""
    base = obj.BaseFeature
    part = util.part_of(obj)
    if base is not None and part is not None and bid in list(base.BodyIds):
        ids = list(base.BodyIds)
        return part_mod.body_names(part, ids, list(base.BodyFeatures))[ids.index(bid)]
    return bid


class ToolPanel(FeaturePanel):
    EDIT_SHOWS_BASE = True
    ICON_NAME = ""
    PREVIEW_ADDS = True     # False: always material taken away (drawn red)

    def removes(self):
        if not self.PREVIEW_ADDS:
            return True
        return super(ToolPanel, self).removes()     # measured: see FeaturePanel

    def __init__(self, obj, is_new=False):
        LAST[0] = self
        self.ICON = icon(self.ICON_NAME or self.TITLE)
        self._loaders = []
        super(ToolPanel, self).__init__(obj, is_new)

    # ------------------------------------------------------------ building blocks
    def base_ids(self):
        b = self.obj.BaseFeature
        return list(b.BodyIds) if b is not None else []

    def bodies_box(self, group, prop, tip, label=None, multiple=True, empty=None,
                   hint="Click bodies in the 3D view or tree"):
        """Bodies by ID, picked in the view or in the body folders: a list, or
        (``multiple`` False) a field in a row labelled *label*."""
        def accept(sel):
            r = selmod.body_ref(sel, self.base_ids())
            if r is None or isinstance(r, str):
                return r
            return r[0], self.body_label(r[0])

        if multiple:
            box = self.list(group, prop, "bodies", hint, accept, tip, empty)
        else:
            box = self.field(group, label, prop, "body", "Click a body", accept, tip, empty)

        def store():
            ids = list(box.payloads())
            self.set_prop(prop, ids if multiple else (ids[0] if ids else ""))
        box.changed.connect(store)

        def load():
            v = getattr(self.obj, prop)
            ids = list(v) if isinstance(v, (list, tuple)) else ([v] if v else [])
            box.set_items([(i, self.body_label(i)) for i in ids])
        self._loaders.append(load)
        return box

    def features_box(self, group, tip, prop="Features", empty=None):
        """Earlier features to repeat, picked in the tree, or by clicking a face in
        the view: the feature that last touched that face is picked."""
        def accept(sel):
            o = sel.obj
            if sel.sub:
                kind = sel.elem_kind()
                if kind not in ("Face", "Edge"):
                    return "Click a face of the feature, or the feature in the tree."
                o = selmod.feature_of_element(self.part, sel.element(), self.obj)
                if o is None:
                    return "No feature above this one made that {}.".format(kind.lower())
            elif not util.is_feature(o):
                return None
            feats = util.features(self.part)
            if o is self.obj or (o in feats and self.obj in feats and
                                 feats.index(o) > feats.index(self.obj)):
                return "Pick a feature above this one."
            if "ToolShape" not in o.PropertiesList and \
                    getattr(getattr(o, "Proxy", None), "TYPE", "") not in ("Fillet", "Chamfer"):
                return "{} can't be repeated; pattern the bodies instead.".format(o.Label)
            return o.Name, o.Label

        box = self.list(group, prop, "features", "Click features in the tree, or their faces",
                        accept, tip, empty)
        box.changed.connect(lambda: self.set_prop(
            prop, [self.doc.getObject(n) for n in box.payloads()]))
        self._loaders.append(lambda: box.set_items(
            [(f.Name, f.Label) for f in getattr(self.obj, prop) if f is not None]))
        return box

    def faces_list(self, group, prop, tip, empty=None, hint="Click faces"):
        """Faces of the model before this feature, stored as one reference."""
        return self.elements_list(group, prop, tip, "Face", empty, hint)

    def elements_list(self, group, prop, tip, kind="Face", empty=None, hint=None, check=None):
        """Faces or edges of the model before this feature, stored as one
        reference. *check*: a function of the picked element returning a refusal."""
        what = kind.lower() + "s"

        def accept(sel):
            k = sel.elem_kind()
            if not util.is_body_view(sel.obj):
                return None
            if k != kind:
                return "Pick {} here.".format(what) if k else None
            if check is not None:
                why = check(sel.element(), sel.obj)
                if why:
                    return why
            r = selmod._from_body(sel, self.obj.BaseFeature, kind)
            if r is None or isinstance(r, str):
                return r
            return r[1], self.ref_text(r[0], r[1])
        box = self.list(group, prop, what, hint or "Click " + what, accept, tip, empty)

        def store():
            subs = list(box.payloads())
            refs.set_ref(self.obj, prop, self.obj.BaseFeature if subs else None, subs)
            self.changed()
        box.changed.connect(store)

        def load():
            v = getattr(self.obj, prop)
            if v and v[0] is not None:
                box.set_items([(sub, self.ref_text(v[0], sub)) for sub in v[1]])
        self._loaders.append(load)
        return box

    def ref_box(self, group, prop, label, what, hint, tip, kinds=("Face", "Edge", "Vertex"),
                datum=True, empty=None, check=None):
        """One geometric reference, following the model: a field in a row.
        *check*: a function of the picked element returning a refusal (a string)
        or None."""
        def accept(sel):
            o = sel.obj
            if o is self.obj:
                return "A feature can't refer to itself."
            if datum and (o.TypeId in ("Part::DatumPlane", "Part::DatumLine", "Part::DatumPoint")
                          or util.role(o) == "refgeom"):
                why = check(o.Shape) if check is not None else None
                if why:
                    return why
                return (o.Name, ""), self.ref_text(o, "")
            k = sel.elem_kind()
            if k not in kinds:
                return None
            if check is not None:
                try:
                    why = check(sel.element())
                except Exception:
                    why = None
                if why:
                    return why
            if o.TypeId.startswith("Sketcher::") and k in ("Edge", "Vertex"):
                return (o.Name, sel.sub), self.ref_text(o, sel.sub)
            if util.is_body_view(o):
                r = selmod._from_body(sel, self.obj.BaseFeature, k)
                if r is None or isinstance(r, str):
                    return r
                return (r[0].Name, r[1]), self.ref_text(r[0], r[1])
            return None

        box = self.field(group, label, prop, what, hint, accept, tip, empty)

        def store():
            p = box.payloads()
            if p:
                refs.set_ref(self.obj, prop, self.doc.getObject(p[0][0]), p[0][1])
            else:
                refs.set_ref(self.obj, prop, None)
            self.changed()
        box.changed.connect(store)

        def load():
            v = getattr(self.obj, prop)
            if v and v[0] is not None:
                sub = v[1][0] if v[1] else ""
                box.set_items([((v[0].Name, sub), self.ref_text(v[0], sub))])
        self._loaders.append(load)
        return box

    def load(self):
        for fn in self._loaders:
            fn()
        self.refresh()

    def preview_layers(self):
        return [("result", pv.result_node(self.obj.AddSubShape, not self.removes()))]


# ====================================================================== body tools

class CombinePanel(ToolPanel):
    TITLE = "Combine"

    def build(self):
        g = self.group("Operation Type")
        self.op, _r = self.choice(
            g, "Operation", "Operation",
            "Add: fuse the bodies into one. Subtract: cut the other bodies from the main "
            "body. Common: keep only where the bodies overlap.")
        self.sec_main = self.group("Main Body")
        self.main = self.bodies_box(self.sec_main, "MainBody",
                                    "The body the others are cut from", label="Main body",
                                    multiple=False)
        self.sec_bodies = self.group("Bodies to Combine")
        self.bodies = self.bodies_box(self.sec_bodies, "Bodies",
                                      "The bodies to combine. Click one again to take it out.")

    def refresh(self):
        self.sec_main.setVisible(self.op.currentText() == bodyops.SUBTRACT)


class DeleteBodyPanel(ToolPanel):
    TITLE = "Delete/Keep Body"
    ICON_NAME = "DeleteBody"

    def build(self):
        g = self.sec_bodies = self.group("Bodies to Delete/Keep")
        self.kind, _r = self.choice(
            g, "Type", "Type", "Delete the listed bodies, or keep them and delete the rest")
        self.bodies = self.bodies_box(g, "Bodies", "The bodies to delete or keep")


class SplitPanel(ToolPanel):
    TITLE = "Split"
    WITHIN = "Within their edges"
    EXTENDED = "Past their edges"

    def build(self):
        obj = self.obj
        g = self.group("Trim Tools")

        def accept_tool(sel):
            o = sel.obj
            if o.TypeId.startswith("Sketcher::SketchObject") or o.TypeId == "Part::DatumPlane" \
                    or (util.role(o) == "refgeom" and o.Proxy.KIND == "plane"):
                return ("obj", o.Name), o.Label
            if util.is_body_view(o):
                if o.Kind == "surface":
                    return ("body", o.BodyId), part_mod.clean_label(o.Label)
                if sel.elem_kind() == "Face":
                    r = selmod._from_body(sel, obj.BaseFeature, "Face")
                    if r is None or isinstance(r, str):
                        return r
                    return ("face", r[1]), self.ref_text(r[0], r[1])
            return None
        self.tools = self.list(g, "TrimTools", "trim tools",
                               "Click planes, faces, surface bodies or sketches", accept_tool,
                               "What the bodies are split with: planes, faces, surface bodies "
                               "or sketches")
        self.tools.changed.connect(self._tools_changed)
        # Asked as soon as a face or surface is picked: how far does it cut?
        self.reach_q = QtWidgets.QLabel("How far should the picked faces and surfaces cut?")
        self.reach_q.setWordWrap(True)
        g.wide(self.reach_q)
        self.reach = parts.Switch(
            [self.WITHIN, self.EXTENDED],
            tips={self.WITHIN: "Only where the face is. Holes in it are patched, so a "
                               "bit poking through it (a cylinder out of a sphere) is "
                               "cut off",
                  self.EXTENDED: "Grow each face over its whole surface (a plane without "
                                 "edges, a whole cylinder or sphere) and cut everything "
                                 "that would cross it"})
        self.reach.changed.connect(
            lambda m: self.set_prop("ExtendFaces", m == self.EXTENDED))
        self.r_reach = g.wide(self.reach, "How far the faces and surfaces cut")
        self.sec_targets = self.group("Target Bodies")
        self.targets = self.bodies_box(self.sec_targets, "TargetBodies",
                                       "The bodies to split. Empty: every body the tools cut.",
                                       empty="All bodies")
        g = self.sec_pieces = self.group("Resulting Bodies")
        self.consume, _r = self.check(g, "ConsumeCutBodies", "Consume cut bodies",
                                      "Delete the bodies that were split; off: keep them too")
        self.pieces = QtWidgets.QListWidget()
        self.pieces.setToolTip("Ticked pieces become bodies; double-click a name to change it. "
                               "They are numbered in the 3D view.")
        g.wide(self.pieces)
        self.pieces.itemChanged.connect(self._piece_changed)

    def load(self):
        obj = self.obj
        items = [(("obj", o.Name), o.Label) for o in obj.TrimTools]
        v = obj.TrimFaces
        if v and v[0] is not None:
            items += [(("face", sub), self.ref_text(v[0], sub)) for sub in v[1]]
        items += [(("body", b), self.body_label(b)) for b in obj.TrimBodies]
        self.tools.set_items(items)
        super(SplitPanel, self).load()

    def _tools_changed(self):
        objs, faces, bodies = [], [], []
        for kind, val in self.tools.payloads():
            if kind == "obj":
                objs.append(self.doc.getObject(val))
            elif kind == "face":
                faces.append(val)
            else:
                bodies.append(val)
        self.obj.TrimTools = objs
        refs.set_ref(self.obj, "TrimFaces", self.obj.BaseFeature if faces else None, faces)
        self.obj.TrimBodies = bodies
        self._show_reach()
        self.changed()

    def _piece_changed(self, it):
        pid = it.data(QtCore.Qt.UserRole)
        names = dict(self.obj.PieceNames)
        text = it.text().strip()
        if text and text != it.data(QtCore.Qt.UserRole + 1):
            names[pid] = text
        keep = [self.pieces.item(i).data(QtCore.Qt.UserRole) for i in range(self.pieces.count())
                if self.pieces.item(i).checkState() == QtCore.Qt.Checked]
        if not keep:
            self.show_error("Keep at least one piece.")
            self.refresh()
            return
        self.obj.PieceNames = names
        all_kept = len(keep) == self.pieces.count()
        self.obj.KeepAll = all_kept
        self.obj.KeepPieces = [] if all_kept else keep
        self.changed()

    def _show_reach(self):
        faced = any(k in ("face", "body") for k, _v in self.tools.payloads())
        self.reach_q.setVisible(faced)
        self.reach.setVisible(faced)
        self.reach.set_value(self.EXTENDED if getattr(self.obj, "ExtendFaces", False)
                             else self.WITHIN)

    def refresh(self):
        self._show_reach()
        try:
            pieces = json.loads(self.obj.Pieces or "[]")
        except ValueError:
            pieces = []
        self.pieces.blockSignals(True)
        self.pieces.clear()
        names = dict(self.obj.PieceNames)
        keep = set(self.obj.KeepPieces)
        for i, p in enumerate(pieces, 1):
            default = "Body {}".format(i)
            it = QtWidgets.QListWidgetItem(names.get(p["id"], default))
            it.setData(QtCore.Qt.UserRole, p["id"])
            it.setData(QtCore.Qt.UserRole + 1, default)
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEditable)
            it.setCheckState(QtCore.Qt.Checked if self.obj.KeepAll or p["id"] in keep
                             else QtCore.Qt.Unchecked)
            self.pieces.addItem(it)
        self.pieces.blockSignals(False)
        rows = max(2, min(self.pieces.count(), 6))
        self.pieces.setFixedHeight(max(self.pieces.sizeHintForRow(0),
                                       self.pieces.fontMetrics().height() + 4) * rows + 8)

    def after_preview(self):
        self.refresh()

    def preview_layers(self):
        layers = super(SplitPanel, self).preview_layers()
        try:
            pieces = json.loads(self.obj.Pieces or "[]")
        except ValueError:
            pieces = []
        from pivy import coin
        names = dict(self.obj.PieceNames)
        lab = coin.SoSeparator()
        for i, p in enumerate(pieces, 1):
            lab.addChild(pv.label_node(names.get(p["id"], "Body {}".format(i)),
                                       App.Vector(*p["c"])))
        layers.append(("labels", lab if pieces else None))
        return layers


class MoveCopyPanel(ToolPanel):
    TITLE = "Move/Copy Body"
    ICON_NAME = "MoveCopy"

    def build(self):
        g = self.sec_mode = self.group("Mode")
        self.mode_combo, _r = self.choice(
            g, "MoveMode", "Mode", "Translate/Rotate: move by distances and angles. "
            "Constraints: place the bodies by mating their faces, edges and points to others.")
        g = self.sec_bodies = self.group("Bodies to Move/Copy")
        self.bodies = self.bodies_box(g, "Bodies", "The bodies to move or copy")
        self.copy, _r = self.check(g, "Copy", "Copy",
                                   "Leave the bodies where they are and move copies of them")
        self.copies, self.r_copies = self.integer(g, "Copies", "Number of copies",
                                                  "How many copies, each one step further on")
        g = self.sec_t = self.group("Translate")
        self.tref = self.ref_box(g, "TranslateReference", "Along", "edge", "Click an edge or axis",
                                 "Move along this edge or axis by the distance. Empty: move by "
                                 "Delta X, Y and Z.", ("Edge",), empty="Delta X, Y, Z")
        self.tdist, self.r_tdist = self.qty(g, "TranslateDistance", "Distance",
                                            "How far to move along the edge or axis",
                                            flip="ReverseTranslate",
                                            flip_tip="Move the other way along the edge")
        self.dx, self.r_dx = self.qty(g, "DeltaX", "Delta X", "Distance to move along X",
                                      minimum=-1e9)
        self.dy, self.r_dy = self.qty(g, "DeltaY", "Delta Y", "Distance to move along Y",
                                      minimum=-1e9)
        self.dz, self.r_dz = self.qty(g, "DeltaZ", "Delta Z", "Distance to move along Z",
                                      minimum=-1e9)
        g = self.sec_r = self.group("Rotate")
        self.rref = self.ref_box(g, "RotateReference", "Axis", "axis", "Click an axis or edge",
                                 "The axis to turn the bodies about: an axis, a straight edge "
                                 "or a round face", ("Edge", "Face"), empty="No rotation")
        self.angle, _r = self.qty(g, "Angle", "Angle", "How far to turn the bodies", unit="deg",
                                  minimum=-360, maximum=360, step=5.0)
        # Constraints mode: one group per constraint; the next empty one is shown.
        self.mates = []
        for i in range(1, 7):
            g = self.group("Constraint %d" % i)
            kind, _r = self.choice(
                g, "MateType%d" % i, "Type",
                "Coincident, Parallel, Perpendicular, Distance, Angle or Concentric. All the "
                "constraints are met together.")
            moving = self._moving_box(g, i)
            fixed = self.ref_box(g, "MateFixed%d" % i, "Against", "reference",
                                 "Click what it goes against",
                                 "The face, edge or point it goes against, on a body that "
                                 "isn't moved", ("Face", "Edge", "Vertex"))
            val, r_val = self.qty(g, "MateValue%d" % i, "Value",
                                  "The distance or angle between them", unit="", minimum=-1e9)
            flip, r_flip = self.check(g, "MateFlip%d" % i, "Flip alignment",
                                      "Face the other way: aligned instead of opposed")
            self.mates.append((g, kind, moving, fixed, val, r_val, r_flip))

    def _moving_box(self, sec, i):
        """A face, edge or vertex on one of the bodies being moved."""
        prop = "MateMoving%d" % i

        def accept(sel):
            if not util.is_body_view(sel.obj) or not sel.elem_kind():
                return None
            if sel.obj.BodyId not in self.obj.Bodies:
                return "Pick on a body being moved (add it to the bodies first)."
            r = selmod._from_body(sel, self.obj.BaseFeature, sel.elem_kind())
            if r is None or isinstance(r, str):
                return r
            return (r[0].Name, r[1]), self.ref_text(r[0], r[1])

        box = self.field(sec, "Moving", prop, "reference", "Click a moving body",
                         accept, "A face, edge or vertex of a body being moved")

        def store():
            p = box.payloads()
            refs.set_ref(self.obj, prop, self.doc.getObject(p[0][0]) if p else None,
                         p[0][1] if p else "")
            self.changed()
        box.changed.connect(store)

        def load():
            v = getattr(self.obj, prop)
            if v and v[0] is not None and v[1]:
                box.set_items([((v[0].Name, v[1][0]), self.ref_text(v[0], v[1][0]))])
        self._loaders.append(load)
        return box

    def refresh(self):
        cons = self.mode_combo.currentText() == "Constraints"
        self.sec_t.setVisible(not cons)
        self.sec_r.setVisible(not cons)
        shown_empty = False
        for i, (g, kind, moving, fixed, val, r_val, r_flip) in enumerate(self.mates, 1):
            k = kind.currentText()
            used = k != "None"
            visible = cons and (used or not shown_empty)
            if cons and not used and not shown_empty:
                shown_empty = True
            g.setVisible(visible)
            r_val.set_visible(k in ("Distance", "Angle"))
            r_flip.set_visible(used)
            moving.row.set_visible(used)
            fixed.row.set_visible(used)
        self.r_copies.set_visible(self.copy.isChecked() and not cons)
        if cons:
            return
        along = bool(self.tref.items)
        for row in (self.r_dx, self.r_dy, self.r_dz):
            row.set_visible(not along)
        self.r_tdist.set_visible(along)


# ====================================================================== patterns

class LinearPatternPanel(ToolPanel):
    TITLE = "Linear Pattern"
    ICON_NAME = "LinearPattern"

    def build(self):
        g = self.group("Direction 1")
        self.dir1 = self.ref_box(g, "Direction1Ref", "Direction", "direction",
                                 "Click an edge or plane",
                                 "The direction of the pattern: a straight edge, an axis, or a "
                                 "plane (along its normal)", ("Edge", "Face"))
        self.sp1, _r = self.qty(g, "Spacing", "Spacing", "Distance between instances",
                                flip="Reverse", flip_tip="Pattern the other way")
        self.n1, _r = self.integer(g, "Instances", "Instances",
                                   "How many, counting the original")
        g = self.sec_d2 = self.group("Direction 2", "Pattern in a second direction too",
                                     checkable=True, prop="Direction2")
        self.dir2 = self.ref_box(g, "Direction2Ref", "Direction", "direction",
                                 "Click an edge or plane", "The second direction of the pattern",
                                 ("Edge", "Face"))
        self.sp2, _r = self.qty(g, "Spacing2", "Spacing",
                                "Distance between instances in the second direction",
                                flip="Reverse2", flip_tip="Pattern the other way")
        self.n2, _r = self.integer(g, "Instances2", "Instances",
                                   "How many in the second direction, counting the original")
        self.check(g, "PatternSeedOnly", "Pattern seed only",
                   "Repeat only the original in the second direction, not the whole first row")
        self.sec_f = self.group("Features to Pattern")
        self.feats = self.features_box(
            self.sec_f, "The features to repeat: click them in the tree, or click a face "
                        "they made")
        self.sec_fc = self.group("Faces to Pattern")
        self.faces = self.faces_list(
            self.sec_fc, "Faces", "Every face of a boss, hole or pocket to repeat (its walls "
            "and top or floor). Material is added where they bound material, cut where they "
            "bound a gap.", empty="None")
        self.sec_b = self.group("Bodies to Pattern")
        self.bodies = self.bodies_box(self.sec_b, "Bodies", "Whole bodies to repeat",
                                      empty="None")
        from .pattern_panels import SkipBox, pair_text
        from ..core.features import pattern as core_pat
        obj = self.obj
        self.skip = SkipBox(self, lambda: core_pat.linear_slots(
            obj.Instances, obj.Instances2 if obj.Direction2 else 1, obj.PatternSeedOnly),
            pair_text)

    def refresh(self):
        self.skip.refresh()


class CircularPatternPanel(ToolPanel):
    TITLE = "Circular Pattern"
    ICON_NAME = "CircularPattern"

    def build(self):
        g = self.sec_d = self.group("Direction 1")
        self.axis = self.ref_box(g, "Axis", "Axis", "axis", "Click an axis or edge",
                                 "The axis to pattern about: an axis, a straight edge or a "
                                 "round face", ("Edge", "Face"))
        self.angle, self.r_angle = self.qty(
            g, "Angle", "Angle", "The angle between instances; with Equal spacing, the total "
            "angle they spread over", unit="deg", maximum=360.0, step=5.0, flip="Reverse",
            flip_tip="Pattern the other way round")
        self.n, _r = self.integer(g, "Instances", "Instances", "How many, counting the original",
                                  minimum=2)
        self.equal, _r = self.check(g, "EqualSpacing", "Equal spacing",
                                    "Spread the instances evenly over the angle")
        self.sec_f = self.group("Features to Pattern")
        self.feats = self.features_box(
            self.sec_f, "The features to repeat: click them in the tree, or click a face "
                        "they made")
        self.sec_fc = self.group("Faces to Pattern")
        self.faces = self.faces_list(
            self.sec_fc, "Faces", "Every face of a boss, hole or pocket to repeat (its walls "
            "and top or floor). Material is added where they bound material, cut where they "
            "bound a gap.", empty="None")
        self.sec_b = self.group("Bodies to Pattern")
        self.bodies = self.bodies_box(self.sec_b, "Bodies", "Whole bodies to repeat",
                                      empty="None")
        from .pattern_panels import SkipBox
        self.skip = SkipBox(self, lambda: list(range(1, self.obj.Instances + 1)))

    def refresh(self):
        self.skip.refresh()


class MirrorPanel(ToolPanel):
    TITLE = "Mirror"

    def build(self):
        g = self.group("Mirror Face/Plane")
        self.plane = self.ref_box(g, "MirrorPlane", "Plane", "plane", "Click a plane or face",
                                  "The plane or planar face to mirror about", ("Face",))
        self.sec_f = self.group("Features to Mirror")
        self.feats = self.features_box(
            self.sec_f, "The features to mirror: click them in the tree, or click a face "
                        "they made")
        self.sec_fc = self.group("Faces to Mirror")
        self.faces = self.faces_list(
            self.sec_fc, "Faces", "Every face of a boss, hole or pocket to mirror (its walls "
            "and top or floor). Material is added where they bound material, cut where they "
            "bound a gap.", empty="None")
        self.sec_b = self.group("Bodies to Mirror")
        self.bodies = self.bodies_box(self.sec_b, "Bodies", "Whole bodies to mirror",
                                      empty="None")
        self.check(self.sec_b, "MergeSolids", "Merge solids",
                   "Fuse each mirrored body with its original where they touch")


# ====================================================================== Hole Wizard

def element_text(el, last_runs=False):
    """One line for an Advanced hole element: 'Counterbore \u00d811 \u00d7 6.4'."""
    t = u"{} \u00d8{:g}".format(el.kind, el.d)
    if el.kind == core_hole.E_COUNTERSINK:
        return t + u" \u2220{:g}\u00b0".format(el.angle)
    if last_runs:
        t += u" \u2192 end"
    else:
        t += u" \u00d7 {:g}".format(el.depth)
    if el.kind == core_hole.E_TAPERED:
        t += u" \u2220{:g}\u00b0".format(el.angle)
    return t


class HoleElements(object):
    """Advanced Hole's stack of elements, in a group: a list (one line each), buttons
    to add, remove and reorder, and the selected element's type, diameter, depth and
    angle under it. ``last_runs`` marks the near side list, whose last element runs
    to the end condition."""

    def __init__(self, panel, group, prop, last_runs, tip):
        self.panel, self.prop, self.last_runs = panel, prop, last_runs
        self.list = QtWidgets.QListWidget()
        self.list.setMaximumHeight(110)
        group.wide(self.list, tip)
        bar = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        self.b_add = QtWidgets.QPushButton("Add")
        self.b_del = QtWidgets.QPushButton("Remove")
        self.b_up = QtWidgets.QPushButton("Up")
        self.b_down = QtWidgets.QPushButton("Down")
        for b, t in ((self.b_add, "Add an element under the selected one (or at the end)"),
                     (self.b_del, "Remove the selected element"),
                     (self.b_up, "Move the selected element nearer the face"),
                     (self.b_down, "Move the selected element away from the face")):
            b.setToolTip(t)
            lay.addWidget(b)
        group.wide(bar)
        self.kind = parts.combo(core_hole.ELEMENT_KINDS, core_hole.E_HOLE)
        self.r_kind = group.row("Element", self.kind,
                                "Counterbore or Hole: a straight step. Countersink: a cone "
                                "down to the next element. Tapered: narrows by its angle.")
        self.d, self.r_d = self._spin(group, "Diameter", "mm",
                                      "Diameter at the top of the element")
        self.depth, self.r_depth = self._spin(group, "Depth", "mm",
                                              "How deep the element goes")
        self.angle, self.r_angle = self._spin(group, "Angle", "deg",
                                              "Included angle (Countersink, Tapered)")
        self.b_add.clicked.connect(self.add)
        self.b_del.clicked.connect(self.remove)
        self.b_up.clicked.connect(lambda: self.move(-1))
        self.b_down.clicked.connect(lambda: self.move(1))
        self.list.currentRowChanged.connect(lambda _r: self._show())
        self.kind.currentTextChanged.connect(lambda v: self._edit("kind", v))
        self.d.valueChanged.connect(lambda v: self._edit("d", v))
        self.depth.valueChanged.connect(lambda v: self._edit("depth", v))
        self.angle.valueChanged.connect(lambda v: self._edit("angle", v))
        panel._loaders.append(self.load)

    @staticmethod
    def _spin(group, label, unit, tip):
        f = QtWidgets.QDoubleSpinBox()
        f.setDecimals(3 if unit == "mm" else 2)
        f.setRange(0.0, 179.9 if unit == "deg" else 1e6)
        f.setSingleStep(0.5 if unit == "mm" else 1.0)
        f.setSuffix(" mm" if unit == "mm" else u"\u00b0")
        f.setKeyboardTracking(False)
        return f, group.row(label, f, tip)

    # ---- model
    def elements(self):
        out = []
        for t in getattr(self.panel.obj, self.prop):
            try:
                out.append(core_hole.Element.loads(t))
            except Exception:
                pass
        return out

    def _store(self, els, select=None):
        self.panel.set_prop(self.prop, [e.dumps() for e in els])
        self.load(select)

    def _row(self):
        r = self.list.currentRow()
        return r if 0 <= r < len(self.elements()) else None

    def add(self):
        els = self.elements()
        r = self._row()
        at = len(els) if r is None else r + 1
        ref = els[at - 1] if els and at > 0 else None
        els.insert(at, core_hole.Element(core_hole.E_HOLE, ref.d if ref else 6.6, 5.0, 90.0))
        self._store(els, at)

    def remove(self):
        r = self._row()
        if r is None:
            return
        els = self.elements()
        del els[r]
        self._store(els, min(r, len(els) - 1))

    def move(self, step):
        r = self._row()
        els = self.elements()
        if r is None or not 0 <= r + step < len(els):
            return
        els[r], els[r + step] = els[r + step], els[r]
        self._store(els, r + step)

    def count(self):
        return self.list.count()

    # ---- view
    def load(self, select=None):
        els = self.elements()
        keep = self.list.currentRow() if select is None else select
        self.list.blockSignals(True)
        self.list.clear()
        for i, el in enumerate(els):
            self.list.addItem(element_text(el, self.last_runs and i == len(els) - 1))
        if els:
            self.list.setCurrentRow(max(0, min(keep if keep is not None else 0, len(els) - 1)))
        self.list.blockSignals(False)
        self._show()

    def _show(self):
        els = self.elements()
        r = self._row()
        el = els[r] if r is not None else None
        for row in (self.r_kind, self.r_d, self.r_depth, self.r_angle):
            row.set_visible(el is not None)
        self.b_del.setEnabled(el is not None)
        self.b_up.setEnabled(el is not None and r > 0)
        self.b_down.setEnabled(el is not None and r < len(els) - 1)
        if el is None:
            return
        for w, v in ((self.kind, el.kind), (self.d, el.d), (self.depth, el.depth),
                     (self.angle, el.angle)):
            w.blockSignals(True)
            if w is self.kind:
                w.setCurrentText(v)
            else:
                w.setValue(v)
            w.blockSignals(False)
        last = self.last_runs and r == len(els) - 1
        self.r_depth.set_visible(el.kind != core_hole.E_COUNTERSINK and not last)
        self.r_angle.set_visible(el.kind in (core_hole.E_COUNTERSINK, core_hole.E_TAPERED))

    def _edit(self, attr, value):
        r = self._row()
        if r is None:
            return
        els = self.elements()
        setattr(els[r], attr, value)
        self.panel.set_prop(self.prop, [e.dumps() for e in els])
        last = self.last_runs and r == len(els) - 1
        self.list.item(r).setText(element_text(els[r], last))
        if attr == "kind":
            self._show()


class HolePanel(ToolPanel):
    """Type and positions on one panel (SolidWorks splits them across two tabs)."""
    TITLE = "Hole Wizard"
    ICON_NAME = "HoleWizard"
    PREVIEW_ADDS = False

    def build(self):
        obj = self.obj
        g = self.group("Hole Type")
        self.kind, _r = self.choice(g, "HoleType", "Type",
                                    "Counterbore, countersink, plain or tapped hole, or a slot")
        self.std, self.r_std = self.choice(g, "Standard", "Standard",
                                   "The standard the sizes come from: ISO, or ANSI Inch")
        g = self.sec_spec = self.group("Hole Specifications")
        self.size, _r = self.choice(g, "Size", "Size", "The fastener size")
        self.fit, self.r_fit = self.choice(g, "Fit", "Fit",
                                           "Close, normal or loose clearance for the fastener")
        self.thread_opt, self.r_thread = self.choice(
            g, "ThreadOption", "Thread",
            "Tap Drill Diameter: the drilled hole. Thread Diameter: the hole at the thread's "
            "size. Modelled Thread: the helical thread cut into it.")
        self.slot_len, self.r_slot_len = self.qty(g, "SlotLength", "Slot length",
                                                  "Slot length, centre to centre")
        self.slot_ang, self.r_slot_ang = self.qty(g, "SlotAngle", "Slot angle",
                                                  "Slot direction, from the sketch's X axis",
                                                  unit="deg", minimum=-360.0, maximum=360.0,
                                                  step=15.0)
        g = self.sec_legacy = self.group("Legacy Hole", "An older hole type, sized by its "
                                         "own dimensions")
        self.legacy, _r = self.choice(g, "LegacyType", "Type",
                                      "Simple, Tapered, Counterbored, Countersunk or "
                                      "Counterdrilled")
        self.taper, self.r_taper = self.qty(g, "TaperAngle", "Taper angle",
                                            "Tapered: how far the wall leans", unit="deg",
                                            maximum=44.0, step=0.5)
        self.cdrill, self.r_cdrill = self.qty(g, "CdrillAngle", "Counterdrill angle",
                                              "Counterdrilled: the cone down to the hole",
                                              unit="deg", maximum=179.0, step=1.0)
        c = self.sec_custom = self.group("Custom Sizing", "Use your own dimensions instead of "
                                         "the standard's", checkable=True, prop="CustomSizing")
        self.c_d, _r = self.qty(c, "HoleDiameter", "Hole diameter", "Diameter of the hole",
                                step=0.1)
        self.c_cbd, self.r_cbd = self.qty(c, "CboreDiameter", "Counterbore diameter",
                                          "Diameter of the counterbore", step=0.5)
        self.c_cbh, self.r_cbh = self.qty(c, "CboreDepth", "Counterbore depth",
                                          "Depth of the counterbore", step=0.5)
        self.c_csd, self.r_csd = self.qty(c, "CskDiameter", "Countersink diameter",
                                          "Diameter of the countersink at the face", step=0.5)
        self.c_csa, self.r_csa = self.qty(c, "CskAngle", "Countersink angle",
                                          "Included angle of the countersink", unit="deg",
                                          maximum=179.0, step=1.0)
        g = self.sec_end = self.group("End Condition")
        self.end, _r = self.choice(g, "EndCondition", "End condition",
                                   "Blind: to a depth. Through All: through everything. Up To "
                                   "Next: through the first body it meets. Up To Vertex, Up To "
                                   "Surface, Offset From Surface: to what you pick.",
                                   flip="Reverse", flip_tip="Drill the other way")
        self.depth, self.r_depth = self.qty(g, "Depth", "Depth", "Depth of the hole")
        self.tip, self.r_tip = self.qty(g, "TipAngle", "Tip angle",
                                        "Angle of the drill point at the bottom (0: flat)",
                                        unit="deg", maximum=180, step=1.0)
        self.tdepth, self.r_tdepth = self.qty(g, "ThreadDepth", "Thread depth",
                                              "How deep the modelled thread goes")
        self.up_to = self.ref_box(g, "UpTo", "Up to", "face", "Click a face, plane or vertex",
                                  "The vertex, face or plane the holes go up to",
                                  ("Face", "Vertex"))
        self.off, self.r_off = self.qty(g, "OffsetDistance", "Offset",
                                        "How far before the surface the holes stop")
        g = self.sec_opts = self.group("Options")
        self.near = self._csk_row(g, "NearSideCsk", "Near side countersink", "NearCskDiameter",
                                  "NearCskAngle", "A countersink where the hole starts")
        self.far = self._csk_row(g, "FarSideCsk", "Far side countersink", "FarCskDiameter",
                                 "FarCskAngle", "A countersink where the hole comes out "
                                 "(Through All, Up To Next)")
        self.clear_f = parts.QuantityField(obj, "HeadClearanceValue", step=0.5)
        self.clear_f.changed.connect(lambda v: self.set_prop("HeadClearanceValue", v))
        self.r_clear = g.check_row("Head clearance", self.clear_f,
                                   "Carry the counterbore or countersink up above the face, so "
                                   "the screw head has room", obj.HeadClearance)
        self.r_clear.check.toggled.connect(lambda on: self.set_prop("HeadClearance", on))
        g = self.sec_adv = self.group(
            "Near Side Elements", "Advanced: the steps of the hole from the face down; the "
            "last one runs to the end condition")
        self.near_els = HoleElements(self, g, "NearElements", True,
                                     "From the face down. The last element runs to the end "
                                     "condition.")
        g = self.sec_adv_far = self.group(
            "Far Side Elements", "Advanced: steps cut back from where the hole comes out "
            "(Through All, Up To Next)")
        self.far_els = HoleElements(self, g, "FarElements", False,
                                    "From the exit face back up the hole")
        p = self.sec_pos = self.group("Positions")

        def accept(sel):
            o = sel.obj
            if o.TypeId.startswith("Sketcher::SketchObject") and not sel.sub:
                return ("sketch", o.Name), o.Label
            if util.is_body_view(o) and sel.elem_kind() == "Face" and sel.point is not None:
                f = sel.element()
                if f is None or f.Surface.TypeId != "Part::GeomPlane":
                    return "Holes go on planar faces."
                r = selmod._from_body(sel, self.obj.BaseFeature, "Face")
                if r is None or isinstance(r, str):
                    return r
                pt = sel.point
                return ("click", r[1], round(pt.x, 6), round(pt.y, 6), round(pt.z, 6)), \
                    "Point on {}".format(r[1])
            return None
        self.positions = self.list(p, "Positions", "positions",
                                   "Click on a face to add a hole", accept,
                                   "Click on a planar face to add a hole there, or pick a sketch "
                                   "whose points are the hole centres")
        self.positions.changed.connect(self._positions_changed)

    def _csk_row(self, g, prop, text, dprop, aprop, tip):
        """A check box with the countersink's diameter and angle on rows under it
        (shown while it's on), so the panel stays narrow."""
        d = parts.QuantityField(self.obj, dprop, step=0.5)
        d.changed.connect(lambda v: self.set_prop(dprop, v))
        a = parts.QuantityField(self.obj, aprop, unit="deg", maximum=179.0)
        a.changed.connect(lambda v: self.set_prop(aprop, v))
        box = g.check(text, tip, getattr(self.obj, prop))
        r_d = g.row(u"    Diameter", d, "Diameter of the countersink at the face")
        r_a = g.row(u"    Angle", a, "Included angle of the countersink")

        class Rows(object):
            check = box
            r_diameter, r_angle = r_d, r_a

            @staticmethod
            def set_visible(on):
                box.row.set_visible(on)
                for r in (r_d, r_a):
                    r.set_visible(on and box.isChecked())

        box.toggled.connect(lambda on: self.set_prop(prop, on))     # refresh shows the rows
        for r in (r_d, r_a):
            r.set_visible(box.isChecked())
        return Rows

    def load(self):
        sk = self.obj.Sketch
        if sk is not None:
            self.positions.set_items([(("sketch", sk.Name), sk.Label)])
        super(HolePanel, self).load()

    def _refresh_sizes(self):
        """The Size list follows the standard."""
        want = list(self.obj.getEnumerationsOfProperty("Size"))
        have = [self.size.itemText(i) for i in range(self.size.count())]
        if have != want:
            self.size.blockSignals(True)
            self.size.clear()
            self.size.addItems(want)
            self.size.blockSignals(False)
        if self.size.currentText() != self.obj.Size:
            self.size.blockSignals(True)
            self.size.setCurrentText(self.obj.Size)
            self.size.blockSignals(False)

    def after_preview(self):
        # The standard's sizes show, greyed, until Custom sizing is on.
        if not self.obj.CustomSizing:
            for f, prop in ((self.c_d, "HoleDiameter"), (self.c_cbd, "CboreDiameter"),
                            (self.c_cbh, "CboreDepth"), (self.c_csd, "CskDiameter"),
                            (self.c_csa, "CskAngle")):
                f.set_value(getattr(self.obj, prop).Value)

    def _positions_changed(self):
        sk = self.obj.Sketch
        for item in list(self.positions.payloads()):
            if item[0] == "sketch":
                sk = self.doc.getObject(item[1])
            elif item[0] == "click":
                sk = self._add_point(sk, item[1], App.Vector(item[2], item[3], item[4]))
        if sk is not None and self.part is not None and sk not in self.part.Group:
            part_mod.add_to_part(self.part, sk)
        self.obj.Sketch = sk
        self.positions.set_items([(("sketch", sk.Name), sk.Label)] if sk is not None else [])
        self.changed()

    def _add_point(self, sk, face, point):
        """Add a point to the positions sketch, making one on the face if needed."""
        base = self.obj.BaseFeature
        f = Part.getShape(base, face, needSubElement=True)
        n = f.normalAt(*f.Surface.parameter(point))
        if sk is not None:
            pl = regions.sketch_placement(sk)
            sn = pl.Rotation.multVec(App.Vector(0, 0, 1))
            if abs(abs(sn.dot(n)) - 1) > 1e-7 or abs((point - pl.Base).dot(sn)) > 1e-6:
                sk = None       # another plane: a new sketch on this face
        if sk is None:
            sk = self.doc.addObject("Sketcher::SketchObject", "Sketch")
            sk.AttachmentSupport = [(base, face)]
            sk.MapMode = "FlatFace"
            if self.part is not None:
                part_mod.add_to_part(self.part, sk)
            sk.recompute()
        pl = regions.sketch_placement(sk)
        local = pl.inverse().multVec(point)
        sk.addGeometry(Part.Point(App.Vector(local.x, local.y, 0)))
        sk.recompute()
        try:
            sk.ViewObject.Visibility = False
        except Exception:
            pass
        return sk

    def refresh(self):
        H = core_hole
        self._refresh_sizes()
        t = self.kind.currentText()
        tap = t in H.TAPS
        slot = t in H.SLOTS
        adv = t == H.ADVANCED
        legacy = t == H.LEGACY
        lt = self.obj.LegacyType
        self.sec_legacy.setVisible(legacy)
        self.r_taper.set_visible(lt == H.L_TAPERED)
        self.r_cdrill.set_visible(lt == H.L_CDRILL)
        self.sec_spec.setVisible(not adv and not legacy)
        self.sec_custom.setVisible(not adv)
        # A legacy hole is always sized by its own dimensions: no check box then.
        if legacy and self.sec_custom.isCheckable():
            self.sec_custom.setCheckable(False)
            self.sec_custom._show_body(True)
        elif not legacy and not self.sec_custom.isCheckable():
            self.sec_custom.setCheckable(True)
            self.sec_custom.set_checked(self.obj.CustomSizing)
        self.sec_adv.setVisible(adv)
        self.sec_adv_far.setVisible(adv)
        self.r_std.set_visible(not adv and not legacy)
        for tbl, prop in ((self.near_els, "NearElements"), (self.far_els, "FarElements")):
            if adv and tbl.count() != len(getattr(self.obj, prop)):
                tbl.load()      # filled by the type change (Advanced starts from the hole)
        self.r_fit.set_visible(not tap)
        self.r_thread.set_visible(tap)
        self.r_slot_len.set_visible(slot)
        self.r_slot_ang.set_visible(slot)
        cb = t in (H.COUNTERBORE, H.CBORE_SLOT) or (legacy and lt in (H.L_CBORE, H.L_CDRILL))
        cs = t in (H.COUNTERSINK, H.CSK_SLOT) or (legacy and lt == H.L_CSK)
        self.r_cbd.set_visible(cb)
        self.r_cbh.set_visible(cb)
        self.r_csd.set_visible(cs)
        self.r_csa.set_visible(cs)
        e = self.end.currentText()
        blind = e == H.BLIND
        self.r_depth.set_visible(blind)
        self.r_tip.set_visible(blind and not slot)
        self.r_tdepth.set_visible(t in H.TAPS and blind and
                                  self.obj.ThreadOption == H.MODELLED)
        self.up_to.row.set_visible(e in (H.UP_TO_VERTEX, H.UP_TO_SURFACE,
                                         H.OFFSET_FROM_SURFACE))
        self.r_off.set_visible(e == H.OFFSET_FROM_SURFACE)
        self.far.set_visible(e in (H.THROUGH_ALL, H.UP_TO_NEXT) and not adv)
        self.near.set_visible(not adv)
        self.r_clear.set_visible(cb or cs)
        self.sec_opts.setVisible(not adv)
