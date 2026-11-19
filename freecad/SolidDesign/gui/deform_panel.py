# SPDX-License-Identifier: LGPL-2.1-or-later
"""Panels for Indent, Deform, Freeform and Surface Flatten."""

from PySide import QtCore, QtWidgets

from ..app import surfaces as app_surf
from . import preview as pv
from .panel import parts
from .surface_panel import _SurfacePanel


class IndentPanel(_SurfacePanel):
    """Target, tool, the tool's regions to keep (numbered in the view), then
    thickness and clearance (SolidWorks' order)."""
    TITLE = "Indent"
    ICON_NAME = "Indent"

    def build(self):
        g = self.group("Selections")
        self.target = self.bodies_box(g, "TargetBody", "The body to indent", label="Target",
                                      multiple=False)
        self.tool = self.bodies_box(g, "ToolBody", "The body whose shape is pressed in",
                                    label="Tool", multiple=False)
        g = self.group("Tool Regions",
                       "The tool's parts outside the target: the target wraps the ticked ones")
        self.region_list = QtWidgets.QListWidget()
        self.region_list.setMinimumHeight(70)
        self.region_list.itemChanged.connect(self._region_ticked)
        g.wide(self.region_list, "The regions, numbered in the view: untick one and the "
                                 "target is only cut there")
        g = self.group("Parameters")
        self.t, self.r_t = self.qty(g, "Thickness", "Thickness",
                                    "Wall thickness round the tool", step=0.5)
        self.c, _r = self.qty(g, "Clearance", "Clearance",
                              "Gap between the tool and the target", step=0.1)
        self.cut, _r = self.check(g, "Cut", "Cut",
                                  "Only cut the target where the tool is (no wall)")

    def refresh(self):
        cut = self.obj.Cut
        self.r_t.set_visible(not cut)
        self.region_list.setEnabled(not cut)

    def _regions(self):
        return getattr(self.obj.Proxy, "regions", []) or []

    def _excluded(self, solid):
        pts = [app_surf._vec(t) for t in self.obj.ExcludedPoints]
        return any(p is not None and solid.isInside(p, 1e-6, True) for p in pts)

    def after_preview(self):
        lst = self.region_list
        lst.blockSignals(True)
        lst.clear()
        for k, (pt, vol, solid) in enumerate(self._regions(), 1):
            it = QtWidgets.QListWidgetItem(u"Region {} — {:.4g} mm³".format(k, vol))
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Unchecked if self._excluded(solid) else
                             QtCore.Qt.Checked)
            lst.addItem(it)
        if not lst.count():
            it = QtWidgets.QListWidgetItem("Pick a target and a tool that touch it")
            it.setFlags(QtCore.Qt.NoItemFlags)
            lst.addItem(it)
        lst.blockSignals(False)

    def _region_ticked(self, _item):
        regs = self._regions()
        pts = []
        for k in range(self.region_list.count()):
            if k < len(regs) and self.region_list.item(k).checkState() != QtCore.Qt.Checked:
                pts.append(app_surf.vec_text(regs[k][0]))
        self.set_prop("ExcludedPoints", pts)

    def preview_layers(self):
        layers = super(IndentPanel, self).preview_layers()
        from pivy import coin
        regs = self._regions()
        sep = coin.SoSeparator()
        for k, (pt, _v, _s) in enumerate(regs, 1):
            sep.addChild(pv.label_node(str(k), pt))
        layers.append(("regions", sep if regs else None))
        return layers


def _point_text(v):
    return u"({:.4g}, {:.4g}, {:.4g})".format(v.x, v.y, v.z)


class DeformPanel(_SurfacePanel):
    """Deform type first, then its inputs, then the bodies (SolidWorks' order)."""
    TITLE = "Deform"
    ICON_NAME = "Deform"

    def build(self):
        from ..app import util
        obj = self.obj
        g = self.group("Deform Type")
        self.kind, _r = self.choice(g, "DeformType", None,
                                    "Point: push a point. Curve to curve: move curves onto "
                                    "others. Surface push: a tool body pushes in.")
        # Point ------------------------------------------------------------
        g = self.sec_point = self.group("Deform Point")

        def accept_point(sel):
            if not util.is_body_view(sel.obj) and not sel.obj.TypeId.startswith("Sketcher::"):
                return None
            el = sel.element()
            if el is not None and el.ShapeType == "Vertex":
                pt = el.Point
            elif sel.point is not None:
                pt = sel.point
            else:
                return None
            return app_surf.vec_text(pt), _point_text(pt)
        self.point = self.field(g, "Point", "DeformPoint", "point",
                                "Click a vertex or a face",
                                accept_point, "Where the push is: a vertex, or a point on a "
                                "face (where you click)")
        self.point.changed.connect(self._point_changed)
        self._loaders.append(lambda: self.point.set_items(
            [(app_surf.vec_text(obj.DeformPoint), _point_text(obj.DeformPoint))]
            if obj.DeformPoint.Length > 0 or obj.Distance.Value else []))
        self.dirn = self.ref_box(g, "DeformDirection", "Direction", "direction",
                                 "Click an edge or plane",
                                 "The push direction: an edge, axis or plane (its normal). "
                                 "Empty: square to the face", empty="Square to the face")
        self.dist, self.r_dist = self.qty(g, "Distance", "Distance", "How far the point moves",
                                          flip="ReverseDirection",
                                          flip_tip="Push the other way")
        # Curve to curve ---------------------------------------------------
        g = self.sec_curves = self.group("Deform Curves",
                                         "Initial curves move onto the target curves, in order")
        self.initial = self.sketches_box(g, "InitialCurves", "The curves that move")
        self.target = self.sketches_box(g, "TargetCurves",
                                        "Where they move to, in the same order")
        # Surface push -----------------------------------------------------
        g = self.sec_push = self.group("Tool Body", "The body that pushes into the others")
        self.tool = self.bodies_box(g, "ToolBody", "The tool body (a solid)", label="Tool",
                                    multiple=False)
        self.push = self.ref_box(g, "PushDirection", "Direction", "direction",
                                 "Click an edge or plane",
                                 "The push direction: an edge, axis or plane. Empty: from the "
                                 "tool towards the other bodies", empty="Towards the bodies")
        # Region -----------------------------------------------------------
        g = self.sec_region = self.group("Deform Region")
        self.radius, self.r_radius = self.qty(g, "Radius", "Radius",
                                              "How far round the point (or curves) the body "
                                              "follows")
        self.stiff, self.r_stiff = self.choice(g, "Stiffness", "Stiffness",
                                               "Minimum spreads the change widely, Maximum "
                                               "keeps it close")
        g = self.group("Bodies to Deform")
        self.bodies = self.bodies_box(g, "Bodies", "The bodies to deform (none picked: every "
                                      "body it reaches)", empty="Every body it reaches")

    def _point_changed(self):
        p = self.point.payloads()
        v = app_surf._vec(p[0]) if p else None
        if v is not None:
            self.set_prop("DeformPoint", v)

    def refresh(self):
        from ..core.features import morph
        k = self.obj.DeformType
        self.sec_point.setVisible(k == morph.POINT)
        self.sec_curves.setVisible(k == morph.CURVE_TO_CURVE)
        self.sec_push.setVisible(k == morph.SURFACE_PUSH)
        self.sec_region.setVisible(k != morph.SURFACE_PUSH)


class FreeformPanel(_SurfacePanel):
    """The face, then its control points: click on the face to add one; drag its
    arrow (or type its height) to pull it in or out."""
    TITLE = "Freeform"
    ICON_NAME = "Freeform"

    def build(self):
        from ..app import util
        g = self.group("Face")
        self.face = self.faces_list(g, "Items", "The face to change (its edges stay put)")
        self.cont, _r = self.choice(g, "Continuity", "Edges",
                                    "How the change meets the face's edges: Contact (a crease), "
                                    "Tangent (smooth) or Curvature (smoothest)")
        g = self.group("Control Points",
                       "Click on the face to add a point; drag its arrow or type how far it "
                       "moves")

        def accept(sel):
            if not util.is_body_view(sel.obj) or sel.elem_kind() != "Face" or \
                    sel.point is None:
                return "Click on the face." if util.is_body_view(sel.obj) else None
            v = self.obj.Items
            if not v or v[0] is None:
                return "Pick the face first."
            t = self.obj.Proxy.point_text(sel.point, 0.0)
            return t, _point_text(sel.point)
        self.points = self.list(g, "ControlPoints", "points", "Click on the face", accept,
                                "Control points; click one in the list to set its height",
                                empty="No points")
        self.points.changed.connect(self._points_changed)
        self.height = parts.QtWidgets.QDoubleSpinBox()
        self.height.setRange(-1e6, 1e6)
        self.height.setDecimals(3)
        self.height.setSuffix(" mm")
        self.height.setKeyboardTracking(False)
        self.r_height = g.row("Height", self.height,
                              "How far the selected point moves along the face's normal "
                              "(negative: in)")
        self.height.valueChanged.connect(self._height_changed)
        self.points.list.currentRowChanged.connect(lambda _r: self._show_height())
        self.reach = parts.QtWidgets.QSpinBox()
        self.reach.setRange(5, 100)
        self.reach.setSuffix(" %")
        self.reach.setValue(int(self.obj.Reach))
        self.reach.valueChanged.connect(lambda v: self.set_prop("Reach", int(v)))
        g.row("Reach", self.reach, "How far each point's pull spreads, as a share of the "
                                   "face's size")
        self._loaders.append(self._load_points)

    def _load_points(self):
        pts = self.obj.Proxy.points(self.obj)
        self.points.set_items([(self.obj.Proxy.point_text(c, h),
                                u"{}  {:+.4g} mm".format(_point_text(c), h)) for c, h in pts])
        self._show_height()

    def _points_changed(self):
        # The list gives each point's text (with its height); keep heights as they were.
        self.set_prop("ControlPoints", list(self.points.payloads()))
        self._show_height()

    def _row(self):
        lst = getattr(self.points, "list", None)
        r = lst.currentRow() if lst is not None else -1
        n = len(self.obj.ControlPoints)
        if r < 0 and n:
            r = n - 1
        return r if 0 <= r < n else None

    def _show_height(self):
        r = self._row()
        self.r_height.set_visible(r is not None)
        if r is None:
            return
        _c, h = self.obj.Proxy.points(self.obj)[r]
        self.height.blockSignals(True)
        self.height.setValue(h)
        self.height.blockSignals(False)

    def _height_changed(self, v):
        r = self._row()
        if r is not None:
            self.set_height(r, v)

    def set_height(self, r, v):
        pts = self.obj.Proxy.points(self.obj)
        if not 0 <= r < len(pts):
            return
        c, _h = pts[r]
        texts = list(self.obj.ControlPoints)
        texts[r] = self.obj.Proxy.point_text(c, v)
        self.set_prop("ControlPoints", texts)
        self.points.blockSignals(True)
        self._load_points()
        self.points.blockSignals(False)
        lst = getattr(self.points, "list", None)
        if lst is not None:
            lst.setCurrentRow(r)

    def drag_set(self, prop, v):
        """Drag arrows: one per control point (prop "Point<i>")."""
        if prop.startswith("Point"):
            sign = -1.0 if prop.endswith("-") else 1.0
            self.set_height(int(prop[5:-1]), sign * v)
            return True
        return False


class FlattenPanel(_SurfacePanel):
    """Faces, the point to flatten from, and the accuracy."""
    TITLE = "Surface Flatten"
    ICON_NAME = "SurfaceFlatten"

    def build(self):
        g = self.group("Flatten")
        self.faces = self.faces_list(g, "Items", "The faces to flatten (connected)")
        self.anchor = self.ref_box(g, "FlattenFrom", "From", "vertex",
                                   "Click a vertex or edge",
                                   "Where the flat shape touches the faces: a vertex, or an "
                                   "edge's middle. Empty: the first face's centre",
                                   kinds=("Vertex", "Edge"), datum=False,
                                   empty="First face's centre")
        self.acc = parts.QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.acc.setRange(0, 100)
        self.acc.setValue(int(self.obj.Accuracy))
        self.acc.valueChanged.connect(lambda v: self.set_prop("Accuracy", int(v)))
        g.row("Accuracy", self.acc, "Finer is truer to the faces, and slower")
