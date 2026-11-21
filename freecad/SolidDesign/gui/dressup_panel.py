# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fillet and Chamfer panels (SolidWorks' Fillet and Chamfer PropertyManagers).

While the panel is open the model shows the bodies *before* the feature, as in
SolidWorks, so every edge can still be picked; the result is the preview.
"""

import Part
from PySide import QtWidgets

from ..app import refs, util
from ..core.features import chamfer as core_chamfer
from ..core.features import fillet as core_fillet
from . import preview as pv
from . import selection as selmod
from .panel import parts
from .panel.base import FeaturePanel
from .sketch_panel import LAST
from .. import icon

__all__ = ["FilletPanel", "ChamferPanel"]


class _EdgePanel(FeaturePanel):
    EDIT_SHOWS_BASE = True
    CUT_VIEW = False
    OWN_PICKS = True
    KINDS = ("Edge", "Face")
    PLACEHOLDER = "Click edges or faces in the 3D view"

    def __init__(self, obj, is_new=False):
        LAST[0] = self
        self.ICON = icon(self.TITLE)
        super(_EdgePanel, self).__init__(obj, is_new)

    def build_items(self, title, tip):
        g = self.sec_items = self.group(title)
        self.items = self.list(g, "Items", "items", self.PLACEHOLDER, self._accept_item, tip)
        self.items.changed.connect(self._items_changed)
        self.tangent, self.r_tangent = self.check(g, "TangentPropagation", "Tangent propagation",
                                      "Also include the edges tangent to the ones you picked")

    def kinds(self):
        return self.KINDS

    def _accept_item(self, sel):
        k = sel.elem_kind()
        if not util.is_body_view(sel.obj) and not util.is_feature(sel.obj):
            return None
        if k not in self.kinds():
            if k:
                return "Pick {} here.".format(" or ".join(x.lower() + "s" for x in self.kinds()))
            return None
        base = self.obj.BaseFeature
        if sel.obj is self.obj:
            return "Pick on the model before this feature."
        if util.is_body_view(sel.obj):
            r = selmod._from_body(sel, base, k)
            if r is None or isinstance(r, str):
                return r
            return r[1], self.ref_text(r[0], r[1])
        if sel.obj is base:
            return sel.sub, self.ref_text(base, sel.sub)
        return "Pick on the model before this feature."

    def load_items(self):
        v = self.obj.Items
        subs = list(v[1]) if v and v[0] is not None else []
        self.items.set_items([(s, self.ref_text(v[0], s)) for s in subs])

    def _items_changed(self):
        subs = list(self.items.payloads())
        refs.set_ref(self.obj, "Items", self.obj.BaseFeature if subs else None, subs)
        self.changed()

    def preview_layers(self):
        layers = [("result", pv.result_node(self.changed_faces(), not self.removes()))]
        picks = []
        base = self.obj.BaseFeature
        for s in self.items.payloads():
            try:
                picks.append(Part.getShape(base, s, needSubElement=True))
            except Exception:
                pass
        layers.append(("picks", pv.shape_node(Part.makeCompound(picks), pv.REGION_PICKED, 0.0,
                                              line_width=4.0) if picks else None))
        return layers


class FilletPanel(_EdgePanel):
    TITLE = "Fillet"

    def build(self):
        g = self.sec_type = self.group("Fillet Type")
        self.ftype = parts.combo(core_fillet.TYPES, self.obj.FilletType)
        g.row("Type", self.ftype,
              "Constant Size: one radius. Variable Size: the radius changes from start to end "
              "along the edges. Face Fillet: rounds where two sets of faces meet. Full Round "
              "Fillet: replaces a centre face with a round between two side faces.")
        self.ftype.currentTextChanged.connect(lambda t: self.set_prop("FilletType", t))
        self.build_items("Items To Fillet", "The edges to round. A face rounds all its "
                         "edges. Click an item again to take it out.")
        g = self.sec_faces = self.group("Items To Fillet")
        self.set1 = self._faces_box(g, "FaceSet1", "Face set 1",
                                    "The first set of faces (a side face for a full round)")
        self.centre = self._faces_box(g, "CenterFaces", "Centre face set",
                                      "The face the full round replaces")
        self.set2 = self._faces_box(g, "FaceSet2", "Face set 2",
                                    "The second set of faces (the other side face for a full "
                                    "round)")
        self.hold = self._faces_box(self.sec_faces, "HoldLine", "Hold line",
                                    "Optional: edges on a face set where the round stops "
                                    "(its size follows them)", kind="Edge")
        g = self.sec_params = self.group("Fillet Parameters")
        self.method = parts.Switch(
            core_fillet.METHODS,
            tips={core_fillet.SYMMETRIC: "One radius",
                  core_fillet.ASYMMETRIC: "A distance on each face (an elliptical round)"})
        self.method.set_value(self.obj.FilletMethod)
        self.method.changed.connect(lambda m: self.set_prop("FilletMethod", m))
        self.r_method = g.wide(self.method)
        self.radius, self.r_radius = self.qty(g, "Radius", "Radius", "Radius of the rounds",
                                              step=0.5)
        self.dist2, self.r_dist2 = self.qty(g, "Distance2", "Distance 2",
                                            "Asymmetric: the distance on the second face",
                                            step=0.5, flip="FlipAsymmetric",
                                            flip_tip="Swap which face gets which distance")
        self.profile, self.r_profile = self.choice(
            g, "Profile", "Profile", "Circular: a round. Conic Rho: a conic, its shoulder set "
            "by rho. Curvature Continuous: a softer round that meets the faces without a "
            "jump in curvature.")
        self.rho, self.r_rho = self.qty(g, "ConicRho", "Rho", "Conic Rho: 0.05 (flat) to "
                                        "0.95 (sharp); 0.5 is a parabola", unit="",
                                        minimum=0.05, maximum=0.95, step=0.05)
        self.r0, self.r_r0 = self.qty(g, "StartRadius", "Start radius",
                                      "Radius at the start of the edges", step=0.5,
                                      flip="ReverseVariable",
                                      flip_tip="Swap the ends: the start radius goes to the "
                                               "other end")
        self.r1, self.r_r1 = self.qty(g, "EndRadius", "End radius",
                                      "Radius at the end of the edges", step=0.5)
        self.points = _VariablePoints(self, g)

    def _faces_box(self, group, prop, label, tip, kind="Face"):
        what = kind.lower() + "s"

        def accept(sel):
            if not util.is_body_view(sel.obj) or sel.elem_kind() != kind:
                return None if not sel.elem_kind() else "Pick {} here.".format(what)
            r = selmod._from_body(sel, self.obj.BaseFeature, kind)
            if r is None or isinstance(r, str):
                return r
            return r[1], self.ref_text(r[0], r[1])
        caption = QtWidgets.QLabel(label)
        group.wide(caption, tip)
        box = self.list(group, prop, what, "Click " + what, accept,
                        "{}. Click it again to take it out.".format(tip))
        box.caption = caption

        def store():
            subs = list(box.payloads())
            refs.set_ref(self.obj, prop, self.obj.BaseFeature if subs else None, subs)
            self.changed()
            # A full round takes one face per set: move on to the next empty set.
            if subs and self.obj.FilletType == core_fillet.FULL_ROUND:
                for b in (self.set1, self.centre, self.set2):
                    if not b.items:
                        self.activate(b)
                        break
        box.changed.connect(store)
        box.load = lambda: box.set_items(
            [(sub, self.ref_text(getattr(self.obj, prop)[0], sub))
             for sub in getattr(self.obj, prop)[1]] if getattr(self.obj, prop) and
            getattr(self.obj, prop)[0] is not None else [])
        return box

    def load(self):
        self.load_items()
        for b in (self.set1, self.centre, self.set2, self.hold):
            b.load()
        self.points.load()
        self.refresh()

    def refresh(self):
        t = self.ftype.currentText()
        edges = t in (core_fillet.CONSTANT, core_fillet.VARIABLE)
        self.sec_items.setVisible(edges)
        self.sec_faces.setVisible(not edges)
        full = t == core_fillet.FULL_ROUND
        for w in (self.centre, self.centre.caption):
            w.setVisible(full)
        self.set1.caption.setText("Side face set 1" if full else "Face set 1")
        self.set2.caption.setText("Side face set 2" if full else "Face set 2")
        var = t == core_fillet.VARIABLE
        const = t == core_fillet.CONSTANT
        face = t == core_fillet.FACE
        held = face and bool(self.obj.HoldLine and self.obj.HoldLine[0] is not None)
        for w in (self.hold, self.hold.caption):
            w.setVisible(face)
        asym = const and self.obj.FilletMethod == core_fillet.ASYMMETRIC
        self.r_method.set_visible(const)
        self.r_radius.set_visible((const or face) and not held)
        if self.r_radius.label is not None:
            self.r_radius.label.setText("Distance 1" if asym else "Radius")
        self.r_dist2.set_visible(asym)
        self.r_profile.set_visible(const)
        self.r_rho.set_visible(const and self.obj.Profile == core_fillet.blend.CONIC)
        self.r_r0.set_visible(var)
        self.r_r1.set_visible(var)
        self.points.set_visible(var)
        self.sec_params.setVisible(not full)


class _VariablePoints(object):
    """Variable Size: radii at points along the edges (percent of the way), a list
    with Add / Delete and the selected point's position and radius under it."""

    def __init__(self, panel, group):
        self.panel = panel
        cap = QtWidgets.QLabel("Radii along the edges")
        self.r_cap = group.wide(cap, "Extra radii between the start and the end")
        self.list = QtWidgets.QListWidget()
        self.list.setMaximumHeight(90)
        self.r_list = group.wide(self.list, "Radii along the edges: click one to change it")
        bar = QtWidgets.QWidget()
        lay = QtWidgets.QHBoxLayout(bar)
        lay.setContentsMargins(0, 0, 0, 0)
        self.b_add = QtWidgets.QPushButton("Add")
        self.b_add.setToolTip("Add a point halfway between its neighbours")
        self.b_del = QtWidgets.QPushButton("Delete")
        self.b_del.setToolTip("Delete the selected point")
        lay.addWidget(self.b_add)
        lay.addWidget(self.b_del)
        self.r_bar = group.wide(bar)
        self.pos = QtWidgets.QDoubleSpinBox()
        self.pos.setRange(0.5, 99.5)
        self.pos.setSuffix(" %")
        self.pos.setKeyboardTracking(False)
        self.r_pos = group.row("Position", self.pos, "How far along the edges, in percent")
        self.rad = QtWidgets.QDoubleSpinBox()
        self.rad.setRange(0.001, 1e6)
        self.rad.setDecimals(3)
        self.rad.setSuffix(" mm")
        self.rad.setKeyboardTracking(False)
        self.r_rad = group.row("Radius", self.rad, "The radius there")
        self.b_add.clicked.connect(self.add)
        self.b_del.clicked.connect(self.delete)
        self.list.currentRowChanged.connect(lambda _r: self.show())
        self.pos.valueChanged.connect(lambda _v: self.edit())
        self.rad.valueChanged.connect(lambda _v: self.edit())
        self.visible = True

    def data(self):
        return [(f * 100.0, r) for f, r in
                self.panel.obj.Proxy.variable_points(self.panel.obj)]

    def store(self, pts, select=None):
        pts = sorted(pts)
        self.panel.set_prop("VariablePoints", ["{:g}|{:g}".format(f, r) for f, r in pts])
        self.load(select)

    def load(self, select=None):
        pts = self.data()
        keep = self.list.currentRow() if select is None else select
        self.list.blockSignals(True)
        self.list.clear()
        for f, r in pts:
            self.list.addItem(u"{:g}% \u2014 R {:g} mm".format(f, r))
        if pts:
            self.list.setCurrentRow(max(0, min(keep if keep >= 0 else 0, len(pts) - 1)))
        self.list.blockSignals(False)
        self.show()

    def row(self):
        r = self.list.currentRow()
        return r if 0 <= r < len(self.data()) else None

    def show(self):
        r = self.row()
        on = self.visible and r is not None
        self.r_pos.set_visible(on)
        self.r_rad.set_visible(on)
        self.b_del.setEnabled(r is not None)
        if r is None:
            return
        f, rad = self.data()[r]
        for w, v in ((self.pos, f), (self.rad, rad)):
            w.blockSignals(True)
            w.setValue(v)
            w.blockSignals(False)

    def add(self):
        pts = self.data()
        o = self.panel.obj
        ends = [(0.0, o.StartRadius.Value)] + pts + [(100.0, o.EndRadius.Value)]
        gaps = [(b[0] - a[0], (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
                for a, b in zip(ends, ends[1:])]
        _w, f, r = max(gaps)
        pts.append((round(f, 2), round(r, 3)))
        self.store(pts, sorted(pts).index((round(f, 2), round(r, 3))))

    def delete(self):
        r = self.row()
        if r is None:
            return
        pts = self.data()
        del pts[r]
        self.store(pts, r)

    def edit(self):
        r = self.row()
        if r is None:
            return
        pts = self.data()
        pts[r] = (self.pos.value(), self.rad.value())
        self.store(pts, sorted(pts).index(pts[r]))

    def set_visible(self, on):
        self.visible = on
        for row in (self.r_cap, self.r_list, self.r_bar):
            row.set_visible(on)
        self.show()


class ChamferPanel(_EdgePanel):
    TITLE = "Chamfer"

    @staticmethod
    def _pick_kinds(t):
        if t == core_chamfer.VERTEX:
            return ("Vertex",)
        if t == core_chamfer.FACE_FACE:
            return ("Face",)
        return ("Edge", "Face")

    def kinds(self):
        return self._pick_kinds(self.obj.ChamferType)

    def build(self):
        g = self.sec_type = self.group("Chamfer Type")
        self.ctype = parts.combo(core_chamfer.TYPES, self.obj.ChamferType)
        g.row("Type", self.ctype,
              "Angle Distance: a distance and an angle. Distance Distance: a distance on "
              "each face. Vertex: three distances at a corner. Offset Face: the faces "
              "offset by the distance. Face Face: pick faces that meet; the edges between "
              "them are chamfered, the first distance on the face picked first.")
        self.ctype.currentTextChanged.connect(self._type_changed)
        self.build_items("Items To Chamfer", "The edges to chamfer, or corners for Vertex. "
                         "Click an item again to take it out.")
        g = self.sec_params = self.group("Chamfer Parameters")
        self.d1, self.r_d1 = self.qty(g, "Distance", "Distance", "Size of the chamfer",
                                      step=0.5, flip="FlipDirection",
                                      flip_tip="Measure the distance on the other face")
        self.flip = self.d1.flip
        self.angle, self.r_angle = self.qty(g, "Angle", "Angle", "Angle of the chamfer face",
                                            unit="deg", maximum=89.9, step=1.0)
        self.equal, self.r_equal = self.check(g, "EqualDistance", "Equal distance",
                                              "Use the same distance on every side")
        self.d2, self.r_d2 = self.qty(g, "Distance2", "Distance 2",
                                      "Size of the chamfer on the second face", step=0.5)
        self.d3, self.r_d3 = self.qty(g, "Distance3", "Distance 3",
                                      "Size of the chamfer along the third edge", step=0.5)

    def _type_changed(self, t):
        old = self._pick_kinds(self.obj.ChamferType)
        self.set_prop("ChamferType", t)
        new = self._pick_kinds(t)
        if old != new and self.items.items:
            # Edges can't be vertices (or faces for Face Face): the picks no longer fit.
            self.items.clear_items()
            self.items.say("Pick {} for this chamfer type.".format(
                " or ".join(x.lower() + "s" for x in new)))

    def load(self):
        self.load_items()
        self.refresh()

    def refresh(self):
        t = self.ctype.currentText()
        eq = self.equal.isChecked()
        self.r_angle.set_visible(t == core_chamfer.ANGLE_DISTANCE)
        self.r_equal.set_visible(t != core_chamfer.ANGLE_DISTANCE)
        self.r_d2.set_visible(t != core_chamfer.ANGLE_DISTANCE and not eq)
        self.r_d3.set_visible(t == core_chamfer.VERTEX and not eq)
        self.flip.setVisible(t != core_chamfer.VERTEX)
        vertex = t == core_chamfer.VERTEX
        ff = t == core_chamfer.FACE_FACE
        self.r_tangent.set_visible(not vertex and not ff)
        self.items.set_placeholder(
            what="vertices" if vertex else "faces" if ff else "edges",
            hint="Click vertices" if vertex else
            "Click two or more faces that meet" if ff else self.PLACEHOLDER)
