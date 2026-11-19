# SPDX-License-Identifier: LGPL-2.1-or-later
"""Insert > Curve panels: Projected, Composite, Through XYZ Points, Through
Reference Points."""

from PySide import QtCore, QtWidgets

from ..app import util
from ..core import curves
from .panel import parts
from .surface_panel import _SurfacePanel

__all__ = ["panel_for"]


class _CurvePanel(_SurfacePanel):
    def preview_layers(self):
        return []           # the curve itself shows as it changes


class ProjectedCurvePanel(_CurvePanel):
    TITLE = "Projected Curve"
    ICON_NAME = "ProjectedCurve"

    def build(self):
        obj = self.obj
        g = self.group("Selections")
        self.kind = parts.Switch(
            curves.PROJECTED_TYPES,
            tips={curves.ON_FACES: "Project a sketch onto faces",
                  curves.ON_SKETCH: "Where two sketches on crossing planes meet, each pulled "
                                    "out along its plane's normal"})
        self.kind.set_value(obj.Type)
        self.kind.changed.connect(lambda m: self.set_prop("Type", m))
        g.wide(self.kind)
        self.sketch = self.sketches_box(g, "Sketch", "The sketch to project",
                                        multiple=False, label="Sketch")
        self.sketch2 = self.sketches_box(g, "Sketch2", "The second sketch", multiple=False,
                                         label="Second sketch")
        self.faces = self.elements_list(g, "Faces", "The faces the sketch lands on", "Face")
        self.rev, self.r_rev = self.check(g, "ReverseDirection", "Reverse direction",
                                          "Project the other way from the sketch")
        self.bi, self.r_bi = self.check(g, "Bidirectional", "Bi-directional",
                                        "Project both ways")

    def refresh(self):
        faces = self.obj.Type == curves.ON_FACES
        self.sketch2.row.set_visible(not faces)
        self.faces.setVisible(faces)
        self.r_rev.set_visible(faces)
        self.r_bi.set_visible(faces)


class CompositeCurvePanel(_CurvePanel):
    TITLE = "Composite Curve"
    ICON_NAME = "CompositeCurve"

    def build(self):
        g = self.group("Entities to Join")
        self.edges = self.elements_list(g, "Edges", "Model edges to join, end to end", "Edge",
                                        empty="None")
        self.curves = self.sketches_box(g, "Curves", "Sketches and curves to join, end to "
                                        "end", empty="None")


class _PointsTable(object):
    """A table of points the user types, a new empty row always at the bottom."""

    def __init__(self, panel, group, prop, columns, tip):
        self.panel, self.prop, self.n = panel, prop, len(columns)
        self.table = QtWidgets.QTableWidget(0, self.n)
        self.table.setHorizontalHeaderLabels(columns)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(140)
        self.table.itemChanged.connect(self._edited)
        group.wide(self.table, tip)
        panel._loaders.append(self.load)

    def load(self):
        t = self.table
        t.blockSignals(True)
        rows = list(getattr(self.panel.obj, self.prop))
        t.setRowCount(len(rows) + 1)
        for r, text in enumerate(rows + [",".join([""] * self.n)]):
            vals = text.split(",")
            for c in range(self.n):
                t.setItem(r, c, QtWidgets.QTableWidgetItem(vals[c] if c < len(vals) else ""))
        t.blockSignals(False)

    def _edited(self, _item):
        out = []
        for r in range(self.table.rowCount()):
            vals = []
            for c in range(self.n):
                it = self.table.item(r, c)
                vals.append(it.text().strip() if it else "")
            if not any(vals):
                continue
            try:
                out.append(",".join("{:g}".format(float(v or 0)) for v in vals))
            except ValueError:
                continue
        self.panel.set_prop(self.prop, out)
        QtCore.QTimer.singleShot(0, self.load)


class XYZCurvePanel(_CurvePanel):
    TITLE = "Curve Through XYZ Points"
    ICON_NAME = "CurveXYZ"

    def build(self):
        g = self.group("Points", "The curve passes through these, in order")
        self.points = _PointsTable(self, g, "Points", ["X (mm)", "Y (mm)", "Z (mm)"],
                                   "Type each point; the last row is always empty for a new "
                                   "point")
        self.closed, _r = self.check(g, "Closed", "Closed curve",
                                     "Join the last point back to the first, smoothly")


class PointsCurvePanel(_CurvePanel):
    TITLE = "Curve Through Reference Points"
    ICON_NAME = "CurvePoints"

    def build(self):
        g = self.group("Through Points", "The curve passes through these, in order")
        self.verts = self.elements_list(g, "Vertices", "Vertices of the model, in order",
                                        "Vertex", empty="None")

        def accept(sel):
            o = sel.obj
            if util.role(o) == "refgeom" and o.Proxy.KIND == "point":
                return o.Name, o.Label
            return None
        self.pts = self.list(g, "PointObjects", "points", "Click reference points", accept,
                             "Reference points, after the vertices", empty="None")
        self.pts.changed.connect(lambda: self.set_prop(
            "PointObjects", [self.doc.getObject(n) for n in self.pts.payloads()]))
        self._loaders.append(lambda: self.pts.set_items(
            [(o.Name, o.Label) for o in self.obj.PointObjects if o is not None]))
        self.closed, _r = self.check(g, "Closed", "Closed curve",
                                     "Join the last point back to the first, smoothly")


def panel_for(obj):
    return {"projected": ProjectedCurvePanel, "composite": CompositeCurvePanel,
            "xyz": XYZCurvePanel, "points": PointsCurvePanel}[obj.Proxy.CURVE]
