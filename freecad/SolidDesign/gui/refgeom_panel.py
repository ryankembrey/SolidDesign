# SPDX-License-Identifier: LGPL-2.1-or-later
"""Plane, Axis, Point, Coordinate System and Helix/Spiral panels.

Plane is SolidWorks' own: First, Second and Third Reference, each taking a
plane, face, edge or point, with buttons for the constraints that fit it. What
was picked sets the constraints to start with (Offset Distance for one face,
Mid Plane for two...), and the panel says when the plane is fully defined.
Axis is SolidWorks' too: one box for its references and the five types, the
type picked from what was clicked (two planes: Two Planes...) and pressable.
Point and the rest ask for the type first and then exactly the references that
type needs (see docs/_notes/ux-departures.md).
"""

import Part
from PySide import QtCore, QtWidgets

from .. import icon
from ..app import refs, util
from ..core import curves
from ..core import refgeom as core
from . import selection as selmod
from .panel import parts
from .panel.base import FeaturePanel
from .sketch_panel import LAST

__all__ = ["RefGeomPanel"]

PLACEHOLDER = {
    "plane": "Click a plane or planar face", "plane?": "Click a plane or planar face",
    "line": "Click a line, axis or straight edge", "point": "Click a vertex or point",
    "point?": "Click a point on it (optional)", "curve": "Click an edge",
    "round": "Click a cylindrical or conical face", "arc": "Click a circular edge or arc",
    "face": "Click a face", "surface": "Click a face or plane",
    "origin?": "Click a vertex or point", "xdir?": "Click an edge, axis or face",
    "ydir?": "Click an edge, axis or face",
    "circle": "Click a sketch with one circle, or a circular edge",
}

# (row label, what it holds, short hint for the field) for each kind of reference.
ROW = {
    "plane": ("Plane", "plane", "Click a plane or face"),
    "plane?": ("Plane", "plane", "Click a plane or face"),
    "line": ("Line", "line", "Click a line or edge"),
    "point": ("Point", "point", "Click a vertex or point"),
    "point?": ("Point (optional)", "point", "Click a point"),
    "curve": ("Edge", "edge", "Click an edge"),
    "round": ("Round face", "face", "Click a round face"),
    "arc": ("Arc", "arc", "Click a circular edge"),
    "face": ("Face", "face", "Click a face"),
    "surface": ("Face/Plane", "face", "Click a face or plane"),
    "origin?": ("Origin", "point", "Click a vertex or point"),
    "xdir?": ("X axis", "direction", "Click an edge or face"),
    "ydir?": ("Y axis", "direction", "Click an edge or face"),
    "circle": ("Circle", "circle", "Click a circle or sketch"),
}

# What an empty optional box means.
EMPTY = {"origin?": "Part origin", "xdir?": "Automatic", "ydir?": "Automatic"}

TITLES = {"plane": "Plane", "axis": "Axis", "point": "Point", "csys": "Coordinate System",
          "helix": "Helix/Spiral"}
ICONS = {"plane": "Plane", "axis": "Axis", "point": "Point", "csys": "CoordinateSystem",
         "helix": "Helix"}
NEEDS = {"plane": core.PLANE_NEEDS, "axis": core.AXIS_NEEDS, "point": core.POINT_NEEDS,
         "csys": core.CSYS_NEEDS, "helix": {t: ("circle",) for t in curves.HELIX_TYPES}}

# Whole datum objects each kind of reference accepts, and the element kinds.
WHOLE = {"plane": ("plane",), "line": ("line",), "point": ("point",), "curve": ("line",),
         "round": (), "arc": (), "face": ("plane",), "surface": ("plane",),
         "origin": ("point",), "xdir": ("line", "plane"), "ydir": ("line", "plane"),
         "circle": ()}
ELEMS = {"plane": ("Face",), "round": ("Face",), "line": ("Edge",), "curve": ("Edge",),
         "point": ("Vertex",), "arc": ("Edge",), "face": ("Face",), "surface": ("Face",),
         "origin": ("Vertex",), "xdir": ("Edge", "Face"), "ydir": ("Edge", "Face"),
         "circle": ("Edge",)}


# ------------------------------------------------------------------ plane constraints

_ICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
         'stroke="COLOR" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
         '{}</svg>')
CONSTRAINT_SVG = {
    core.C_COINCIDENT: '<path d="M3 15h18"/><circle cx="12" cy="15" r="3" fill="COLOR"/>',
    core.C_PARALLEL: '<path d="M5 19L13 5M11 19L19 5"/>',
    core.C_PERPENDICULAR: '<path d="M4 19h16M12 19V5"/>',
    core.C_OFFSET: '<path d="M3 4h18M3 20h18M12 7v10M9 10l3-3 3 3M9 14l3 3 3-3"/>',
    core.C_ANGLE: '<path d="M4 19h16M4 19L16 7"/><path d="M12 19a8 8 0 0 0-2.4-5.7"/>',
    core.C_MID: '<path d="M3 4h18M3 20h18"/><path d="M3 12h4M10 12h4M17 12h4"/>',
    core.C_TANGENT: '<circle cx="12" cy="14" r="6"/><path d="M3 8h18"/>',
}
CONSTRAINT_TIPS = {
    core.C_COINCIDENT: "Coincident: the plane passes through it",
    core.C_PARALLEL: "Parallel: the plane is parallel to it",
    core.C_PERPENDICULAR: "Perpendicular: the plane is square to it",
    core.C_OFFSET: "Offset Distance: parallel to it, a distance away",
    core.C_ANGLE: "At Angle: turned about an edge or axis (the other reference)",
    core.C_MID: "Mid Plane: halfway between two planes, or halving the angle where they "
                "meet",
    core.C_TANGENT: "Tangent: the plane touches the cylinder",
}
ORDINAL = ("First", "Second", "Third")
AXIS_TIPS = {
    core.LINE: "Along a straight edge, an axis or a sketch line (or a circular edge's axis)",
    core.TWO_PLANES: "Where two planes or planar faces meet",
    core.TWO_POINTS: "Through two points or vertices",
    core.CYLINDRICAL: "The axis of a cylindrical or conical face",
    core.POINT_AND_FACE: "Through a point, square to a plane or planar face",
}
FLIP_TEXT = {core.C_OFFSET: "Flip offset", core.C_ANGLE: "Flip angle",
             core.C_TANGENT: "Other side"}


class ConstraintBar(QtWidgets.QWidget):
    """Icon buttons for a reference's constraints (only those that fit it show),
    and the chosen one's name beside them, as SolidWorks has them."""
    changed = QtCore.Signal(str)

    def __init__(self, parent=None):
        super(ConstraintBar, self).__init__(parent)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.group = QtWidgets.QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = {}
        for name in CONSTRAINT_SVG:
            b = parts.icon_button(_ICON.format(CONSTRAINT_SVG[name]), CONSTRAINT_TIPS[name],
                                  checkable=True)
            b.name = name
            self.group.addButton(b)
            lay.addWidget(b)
            self.buttons[name] = b
            b.clicked.connect(lambda _c=False, n=name: self.changed.emit(n))
        self.label = QtWidgets.QLabel("")
        lay.addSpacing(6)
        lay.addWidget(self.label, 1)

    def show_for(self, kind, current):
        """Show the buttons that fit ``kind``; press ``current`` (no signal)."""
        allowed = core.CONSTRAINTS_FOR.get(kind, [])
        for name, b in self.buttons.items():
            b.setVisible(name in allowed)
            b.blockSignals(True)
            b.setChecked(name == current)
            b.blockSignals(False)
        self.label.setText(current or "")

    def value(self):
        b = self.group.checkedButton()
        return b.name if b is not None and b.isVisible() else None


class RefGeomPanel(FeaturePanel):
    EDIT_SHOWS_BASE = True

    def __init__(self, obj, is_new=False):
        LAST[0] = self
        self.kind = obj.Proxy.KIND
        self.TITLE = TITLES[self.kind]
        self.ICON = icon(ICONS[self.kind])
        super(RefGeomPanel, self).__init__(obj, is_new)

    def needs(self):
        return NEEDS[self.kind].get(self.obj.Type, ())

    def build(self):
        if self.kind == "plane":
            return self.build_plane()
        if self.kind == "axis":
            return self.build_axis()
        obj = self.obj
        g = self.sec = self.group("Type")
        self.type = parts.combo(obj.Proxy.TYPES, obj.Type)
        g.row("Type", self.type, "How the {} is defined; the references below follow from "
              "it".format(self.TITLE.lower()))
        self.type.currentTextChanged.connect(self._type_changed)
        g.setVisible(len(obj.Proxy.TYPES) > 1)
        g = self.sec_refs = self.group("References")
        self.ref_boxes = []
        for i in (1, 2, 3):
            b = self.field(g, "Reference %d" % i, "Reference%d" % i, "reference", "",
                           lambda s, i=i: self._accept(s, i),
                           "A reference the {} is built from".format(self.TITLE.lower()))
            b.changed.connect(lambda i=i: self._ref_changed(i))
            self.ref_boxes.append(b)
        self.ref_rows = [b.row for b in self.ref_boxes]
        g = self.sec_opts = self.group("Parameters" if self.kind == "helix" else "Options")
        if self.kind == "plane":
            self.dist, self.r_dist = self.qty(g, "Distance", "Distance",
                                              "Distance from the reference plane")
            self.angle, self.r_angle = self.qty(g, "Angle", "Angle",
                                                "Angle to the reference plane", unit="deg",
                                                maximum=360.0, step=5.0)
        if self.kind == "point":
            self.dist, self.r_dist = self.qty(g, "Distance", "Distance",
                                              "Distance along the edge from its start")
        if self.kind == "helix":
            self.build_helix(g)
        elif self.kind == "csys":
            self.flip_x, _r = self.check(g, "FlipX", "Reverse X direction",
                                         "Turn the X axis round")
            self.flip_y, _r = self.check(g, "FlipY", "Reverse Y direction",
                                         "Turn the Y axis round")
            self.flip, self.r_flip = self.check(g, "Flip", "Reverse Z direction",
                                                "Turn the Z axis round (Y turns with it, so "
                                                "the axes stay right-handed)")
        elif self.kind == "point":
            self.flip, self.r_flip = self.check(g, "Flip", "From the other end",
                                                "Measure the distance from the edge's other end")
        else:
            self.flip, self.r_flip = self.check(g, "Flip", "Flip",
                                                "Turn the {} the other way round".format(
                                                    self.TITLE.lower()))

    # ---------------------------------------------------------- plane
    def build_plane(self):
        """First, Second and Third Reference: a box, the constraints that fit what
        is in it, and the distance or angle when its constraint has one."""
        self.status = parts.Message("info")
        self.layout.addWidget(self.status)
        self.ref_boxes, self.bars, self.ref_groups = [], [], []
        self.dists, self.angles = [], []
        for i in (1, 2, 3):
            g = self.group("{} Reference".format(ORDINAL[i - 1]),
                           "A plane, face, edge or point the new plane is placed by")
            b = self.field(g, None, "Reference%d" % i, "reference",
                           "Click a plane, face, edge or point",
                           lambda s, i=i: self._accept_any(s, i),
                           "A plane, face, edge or point the new plane is placed by")
            b.changed.connect(lambda i=i: self._ref_changed(i))
            bar = ConstraintBar()
            bar.row = g.wide(bar)
            bar.changed.connect(lambda name, i=i: self._constraint_changed(i, name))
            d, d_row = self.qty(g, "Distance", "Distance", "Distance from the reference")
            a, a_row = self.qty(g, "Angle", "Angle", "Angle turned about the edge or axis",
                                unit="deg", maximum=360.0, step=5.0)
            d.row, a.row = d_row, a_row
            self.ref_boxes.append(b)
            self.bars.append(bar)
            self.ref_groups.append(g)
            self.dists.append(d)
            self.angles.append(a)
        self.ref_rows = [b.row for b in self.ref_boxes]
        self.dist, self.angle = self.dists[0], self.angles[0]
        self.r_dist, self.r_angle = self.dists[0].row, self.angles[0].row
        g = self.sec_opts = self.group("Options")
        self.flip, self.r_flip = self.check(g, "Flip", "Flip normal",
                                            "Turn the plane the other way round")
        self._compacting = False

    # ---------------------------------------------------------- axis
    def build_axis(self):
        """SolidWorks' Axis: the references in one box, and the type buttons with
        the one that fits them pressed."""
        self.status = parts.Message("info")
        self.layout.addWidget(self.status)
        g = self.group("Selections", "Up to two references the axis is made from")
        self.refs = self.list(g, "References", "references",
                              "Click an edge, a round face, two planes or two points",
                              lambda s: self._accept_any(s, 0),
                              "Up to two references: an edge or axis; a cylindrical or "
                              "conical face; two planes; two points; a point and a face")
        self.refs.changed.connect(self._axis_refs_changed)
        self.ref_boxes = [self.refs]
        g = self.sec_type = self.group("Type", "How the axis is made from the references; "
                                       "picked from what they are, or press another")
        self.type_group = QtWidgets.QButtonGroup(self.widget)
        self.type_group.setExclusive(True)
        self.type_buttons = {}
        for t in core.AXIS_TYPES:
            b = QtWidgets.QToolButton()
            b.setText(t)
            b.setCheckable(True)
            b.setToolButtonStyle(QtCore.Qt.ToolButtonTextOnly)
            b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            b.setMinimumHeight(parts.BUTTON)
            b.setToolTip(AXIS_TIPS[t])
            b.clicked.connect(lambda _c=False, t=t: self._axis_type_pressed(t))
            self.type_group.addButton(b)
            g.wide(b)
            self.type_buttons[t] = b
        g = self.sec_opts = self.group("Options")
        self.flip, self.r_flip = self.check(g, "Flip", "Reverse direction",
                                            "Turn the axis the other way round")

    def _axis_refs_changed(self):
        items = list(self.refs.items)
        if len(items) > 2:              # a third pick: keep the last two
            items = items[-2:]
            self.refs.set_items(items)
        for j in range(3):
            if j < len(items):
                (name, sub), _t = items[j]
                refs.set_ref(self.obj, "Reference%d" % (j + 1), self.doc.getObject(name), sub)
            else:
                refs.set_ref(self.obj, "Reference%d" % (j + 1), None)
        from ..app import refgeom as app_refgeom
        app_refgeom.guess_axis_type(self.obj)
        self.changed()

    def _axis_type_pressed(self, t):
        self.set_prop("Type", t)

    def _refresh_axis(self):
        for t, b in self.type_buttons.items():
            b.blockSignals(True)
            b.setChecked(t == self.obj.Type)
            b.blockSignals(False)

    def _accept_any(self, sel, i):
        """Anything a plane or axis can be made from: a plane, a planar or round
        face, an edge, a point, or a datum."""
        o = sel.obj
        if o is self.obj:
            return "A reference can't refer to itself."
        if not sel.sub:
            if o.TypeId in ("Part::DatumPlane", "Part::DatumLine", "Part::DatumPoint") or \
                    (util.role(o) == "refgeom" and o.Proxy.KIND in ("plane", "axis", "point")):
                return (o.Name, ""), self.ref_text(o, "")
            return None
        k = sel.elem_kind()
        if k not in ("Face", "Edge", "Vertex"):
            return None
        if o.TypeId.startswith("Sketcher::") and k in ("Edge", "Vertex"):
            target, sub = o, sel.sub
        elif util.is_body_view(o):
            r = selmod._from_body(sel, self.obj.BaseFeature, k)
            if r is None or isinstance(r, str):
                return r
            target, sub = r
        else:
            return None
        try:
            shape = Part.getShape(target, sub, needSubElement=True)
        except Exception:
            return None
        if core.ref_kind(shape) is None:
            return "Pick a plane, a planar or cylindrical face, an edge or a point."
        return (target.Name, sub), self.ref_text(target, sub)

    def _shapes(self):
        """The references' shapes, one per box (None where empty)."""
        return (self.obj.Proxy.resolved(self.obj, []) + [None] * 3)[:3]

    def _plane_ref_changed(self, i):
        if self._compacting:
            return
        # Keep the references in the first boxes, so an emptied box closes up.
        items = [b.items[0] for b in self.ref_boxes if b.items]
        self._compacting = True
        try:
            for j, b in enumerate(self.ref_boxes):
                want = [items[j]] if j < len(items) else []
                if [x[0] for x in b.items] != [x[0] for x in want]:
                    b.set_items(want)
        finally:
            self._compacting = False
        for j in range(3):
            if j < len(items):
                (name, sub), _t = items[j]
                refs.set_ref(self.obj, "Reference%d" % (j + 1), self.doc.getObject(name), sub)
            else:
                refs.set_ref(self.obj, "Reference%d" % (j + 1), None)
        # A new set of references: guess again, as SolidWorks does.
        self.obj.Constraints = []
        nxt = self.next_box_needing_input()
        if nxt is not None:
            self.activate(nxt)
        self.changed()

    def _constraint_changed(self, i, name):
        cons = self.obj.Proxy.constraints(self.obj)
        if i - 1 < len(cons):
            cons[i - 1] = name
            self.obj.Constraints = cons
        self.changed()

    def _refresh_plane(self):
        try:
            shapes = self._shapes()
            cons = iter(self.obj.Proxy.constraints(self.obj, shapes))
            per_box = [next(cons, None) if s is not None else None for s in shapes]
        except Exception:
            shapes, per_box = [None] * 3, [None] * 3
        live = [s for s in shapes if s is not None]
        used = None
        for j in range(3):
            filled = bool(self.ref_boxes[j].items)
            self.ref_groups[j].setVisible(j == 0 or filled or bool(self.ref_boxes[j - 1].items))
            c = per_box[j] if filled else None
            kind = core.ref_kind(shapes[j]) if filled else None
            self.bars[j].show_for(kind, c)
            self.bars[j].row.set_visible(filled and kind is not None)
            self.dists[j].row.set_visible(c == core.C_OFFSET)
            self.angles[j].row.set_visible(c == core.C_ANGLE)
            if c == core.C_OFFSET:
                self.dists[j].set_value(self.obj.Distance.Value)
                self.dist, self.r_dist = self.dists[j], self.dists[j].row
            if c == core.C_ANGLE:
                self.angles[j].set_value(self.obj.Angle.Value)
                self.angle, self.r_angle = self.angles[j], self.angles[j].row
            if c in FLIP_TEXT:
                used = c
        self.flip.setText(FLIP_TEXT.get(used, "Flip normal"))
        self.sec_opts.setVisible(bool(live))

    def after_preview(self):
        if self.kind == "axis":
            ok = not self.obj.ErrorMessage and bool(self.refs.items)
            self.status.set("Fully defined" if ok else "")
            return
        if self.kind != "plane":
            return
        ok = not self.obj.ErrorMessage and any(b.items for b in self.ref_boxes)
        self.status.set("Fully defined" if ok else "")
        # The constraints can only be read for sure once the references resolve.
        self._refresh_plane()

    def build_helix(self, g):
        self.pitch, self.r_pitch = self.qty(g, "Pitch", "Pitch", "Distance between turns",
                                            minimum=0.001, step=0.5)
        self.revs, self.r_revs = self.qty(g, "Revolutions", "Revolutions", "Number of turns",
                                          unit="", minimum=0.01, step=1.0)
        self.height, self.r_height = self.qty(g, "Height", "Height", "Height of the helix",
                                              minimum=0.001, step=1.0)
        self.start, _r = self.qty(g, "StartAngle", "Start angle",
                                  "Where the first turn starts, measured round from the "
                                  "circle's X direction", unit="deg", minimum=-360.0,
                                  maximum=360.0, step=15.0)
        self.flip, self.r_flip = self.check(g, "Flip", "Reverse direction",
                                            "Grow the helix the other way from the circle")
        self.cw, _r = self.check(g, "Clockwise", "Clockwise",
                                 "Turn clockwise (a left-hand helix); off: counterclockwise")
        t = self.sec_taper = self.group("Taper Helix", "Make the helix cone-shaped",
                                        checkable=True, prop="TaperHelix")
        self.taper, _r = self.qty(t, "TaperAngle", "Angle", "Taper angle", unit="deg",
                                  maximum=89.0, step=1.0)
        self.taper_out, _r = self.check(t, "TaperOutward", "Taper outward",
                                        "Wider at the end; off: narrower")

    def _accept(self, sel, i):
        needs = self.needs()
        if i > len(needs):
            return None
        want = needs[i - 1].rstrip("?")
        o = sel.obj
        if o is self.obj:
            return "A reference can't refer to itself."
        k = sel.elem_kind()
        base = self.obj.BaseFeature
        if want == "circle" and o.TypeId.startswith("Sketcher::SketchObject") and not sel.sub:
            return (o.Name, ""), o.Label        # a sketch with one circle
        # Whole datum objects: origin planes/axes/point and other reference geometry.
        whole = None
        if o.TypeId == "Part::DatumPlane" or (util.role(o) == "refgeom" and o.Proxy.KIND == "plane"):
            whole = "plane"
        elif o.TypeId == "Part::DatumLine" or (util.role(o) == "refgeom" and o.Proxy.KIND == "axis"):
            whole = "line"
        elif o.TypeId == "Part::DatumPoint" or (util.role(o) == "refgeom" and
                                                o.Proxy.KIND == "point"):
            whole = "point"
        if whole is not None:
            if whole in WHOLE[want]:
                return (o.Name, ""), self.ref_text(o, "")
            return "This reference needs: {}.".format(PLACEHOLDER[needs[i - 1]].lower()[6:])
        if k not in ELEMS[want]:
            return None if not k else "This reference needs: {}.".format(
                PLACEHOLDER[needs[i - 1]].lower()[6:])
        if o.TypeId.startswith("Sketcher::") and k in ("Edge", "Vertex"):
            return (o.Name, sel.sub), self.ref_text(o, sel.sub)
        if util.is_body_view(o):
            r = selmod._from_body(sel, base, k)
            if r is None or isinstance(r, str):
                return r
            return (r[0].Name, r[1]), self.ref_text(r[0], r[1])
        return None

    def _ref_changed(self, i):
        if self.kind == "plane":
            return self._plane_ref_changed(i)
        box = self.ref_boxes[i - 1]
        p = box.payloads()
        if p:
            refs.set_ref(self.obj, "Reference%d" % i, self.doc.getObject(p[0][0]), p[0][1])
        else:
            refs.set_ref(self.obj, "Reference%d" % i, None)
        # Move on to the next box needing a pick.
        nxt = self.next_box_needing_input()
        if nxt is not None:
            self.activate(nxt)
        self.changed()

    def _type_changed(self, t):
        self.set_prop("Type", t)
        for b in self.ref_boxes:
            b.say("")
        self.refresh()
        nxt = self.next_box_needing_input()
        if nxt is not None:
            self.activate(nxt)

    def next_box_needing_input(self):
        if self.kind == "axis":
            return self.refs if len(self.refs.items) < 2 else None
        if self.kind == "plane":
            # The first empty reference: picks go on into the next box.
            return next((b for b in self.ref_boxes if not b.items and
                         b.isVisibleTo(self.widget)), None)
        needs = self.needs()
        for i, b in enumerate(self.ref_boxes):
            if i < len(needs) and not needs[i].endswith("?") and not b.items:
                return b
        return None

    def load(self):
        if self.kind == "plane" and self.obj.Type != core.REFERENCES:
            # A plane made with the old types: the same plane, as constraints.
            cons = self.obj.Proxy.constraints(self.obj)
            self.obj.Type = core.REFERENCES
            self.obj.Constraints = cons
        if self.kind == "axis":
            items = []
            for i in (1, 2, 3):
                v = getattr(self.obj, "Reference%d" % i)
                if v and v[0] is not None:
                    sub = v[1][0] if v[1] else ""
                    items.append(((v[0].Name, sub), self.ref_text(v[0], sub)))
            self.refs.set_items(items)
            self.refresh()
            return
        for i, b in enumerate(self.ref_boxes, 1):
            v = getattr(self.obj, "Reference%d" % i)
            if v and v[0] is not None:
                sub = v[1][0] if v[1] else ""
                b.set_items([((v[0].Name, sub), self.ref_text(v[0], sub))])
        self.refresh()

    def refresh(self):
        if self.kind == "plane":
            return self._refresh_plane()
        if self.kind == "axis":
            return self._refresh_axis()
        needs = self.needs()
        for i, b in enumerate(self.ref_boxes):
            show = i < len(needs)
            b.row.set_visible(show)
            if show:
                label, what, hint = ROW[needs[i]]
                b.row.label.setText(label)
                b.set_placeholder(what=what, hint=hint,
                                  empty=EMPTY.get(needs[i], "None") if needs[i].endswith("?")
                                  else "")
        t = self.type.currentText()
        if self.kind == "plane":
            self.r_dist.set_visible(t == core.OFFSET)
            self.r_angle.set_visible(t == core.ANGLE)
        if self.kind == "helix":
            uses = {curves.PITCH_REVS: ("p", "n"), curves.HEIGHT_REVS: ("h", "n"),
                    curves.HEIGHT_PITCH: ("h", "p"), curves.SPIRAL: ("p", "n")}[t]
            self.r_pitch.set_visible("p" in uses)
            self.r_revs.set_visible("n" in uses)
            self.r_height.set_visible("h" in uses)
            self.r_flip.set_visible(t != curves.SPIRAL)
            self.sec_taper.setVisible(t != curves.SPIRAL)
        if self.kind == "point":
            self.r_dist.set_visible(t == core.ALONG_CURVE)
            self.r_flip.set_visible(t == core.ALONG_CURVE)
            self.sec_opts.setVisible(t == core.ALONG_CURVE)

    def preview_layers(self):
        return []
