# SPDX-License-Identifier: LGPL-2.1-or-later
"""Curve Driven, Sketch Driven, Table Driven and Fill pattern panels, and the
Instances to Skip list the Linear, Circular and Curve patterns share."""

from PySide import QtCore, QtWidgets

from ..app import util
from ..core.features import pattern as core
from .panel import parts
from .surface_panel import _SurfacePanel

__all__ = ["CurvePatternPanel", "SketchPatternPanel", "TablePatternPanel", "FillPatternPanel",
           "add_seed_groups", "SkipBox"]


def add_seed_groups(panel, word, verb="repeat"):
    """Features / Faces / Bodies to Pattern, the same on every pattern."""
    panel.sec_f = panel.group("Features to {}".format(word))
    panel.feats = panel.features_box(
        panel.sec_f, "The features to {}: click them in the tree, or click a face they "
        "made".format(verb))
    panel.sec_fc = panel.group("Faces to {}".format(word))
    panel.faces = panel.faces_list(
        panel.sec_fc, "Faces", "Every face of a boss, hole or pocket to {} (its walls and "
        "top or floor). Material is added where they bound material, cut where they bound "
        "a gap.".format(verb), empty="None")
    panel.sec_b = panel.group("Bodies to {}".format(word))
    panel.bodies = panel.bodies_box(panel.sec_b, "Bodies", "Whole bodies to {}".format(verb),
                                    empty="None")


class SkipBox(object):
    """Instances to Skip: every instance but the seed, ticked to leave it out."""

    def __init__(self, panel, slots, fmt=str):
        self.panel = panel
        self.slots = slots              # () -> [key], the seed first
        self.fmt = fmt
        g = panel.sec_skip = panel.group("Instances to Skip",
                                         "Tick the instances to leave out")
        self.list = QtWidgets.QListWidget()
        self.list.setMinimumHeight(70)
        self.list.itemChanged.connect(self._ticked)
        g.wide(self.list, "Every instance but the original: tick one to leave it out")
        self._keys = []

    def refresh(self):
        keys = [k for k in self.slots()][1:]
        skipped = set(self.panel.obj.InstancesToSkip)
        if keys == self._keys and all(
                (self.list.item(i).checkState() == QtCore.Qt.Checked) == (self.fmt(k) in skipped)
                for i, k in enumerate(keys)):
            return
        self._keys = keys
        self.list.blockSignals(True)
        self.list.clear()
        for k in keys:
            it = QtWidgets.QListWidgetItem("Instance {}".format(
                "({}, {})".format(*k) if isinstance(k, tuple) else k))
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked if self.fmt(k) in skipped else
                             QtCore.Qt.Unchecked)
            self.list.addItem(it)
        self.list.blockSignals(False)

    def _ticked(self, _item):
        out = [self.fmt(k) for i, k in enumerate(self._keys)
               if self.list.item(i).checkState() == QtCore.Qt.Checked]
        self.panel.set_prop("InstancesToSkip", out)


def pair_text(k):
    return "{},{}".format(*k)


class CurvePatternPanel(_SurfacePanel):
    TITLE = "Curve Driven Pattern"
    ICON_NAME = "CurvePattern"

    def build(self):
        g = self.group("Direction 1")
        self.curve = self.elements_list(g, "Curve", "The curve to pattern along: model edges, "
                                        "end to end", "Edge", empty="None")
        self.sketch = self.sketches_box(g, "CurveSketch", "Or a sketch: its curves, end to "
                                        "end", multiple=False, label="Sketch", empty="None")
        self.n, _r = self.integer(g, "Instances", "Instances", "How many, counting the original",
                                  minimum=2)
        self.equal, _r = self.check(g, "EqualSpacing", "Equal spacing",
                                    "Spread the instances over the whole curve")
        self.sp, self.r_sp = self.qty(g, "Spacing", "Spacing", "Distance along the curve",
                                      flip="Reverse", flip_tip="Pattern the other way")
        self.align, _r = self.choice(
            g, "Alignment", "Alignment",
            "Tangent to curve: each instance turns with the curve. Align to seed: they keep "
            "the original's orientation.")
        add_seed_groups(self, "Pattern")
        self.skip = SkipBox(self, lambda: list(range(1, self.obj.Instances + 1)))

    def refresh(self):
        self.r_sp.set_visible(not self.obj.EqualSpacing)
        self.skip.refresh()


class SketchPatternPanel(_SurfacePanel):
    TITLE = "Sketch Driven Pattern"
    ICON_NAME = "SketchPattern"

    def build(self):
        g = self.group("Selections")
        self.sketch = self.sketches_box(g, "Sketch", "The sketch whose points place the "
                                        "instances; the original's centre is the reference",
                                        multiple=False, label="Reference sketch")
        add_seed_groups(self, "Pattern")


class TablePatternPanel(_SurfacePanel):
    TITLE = "Table Driven Pattern"
    ICON_NAME = "TablePattern"

    def build(self):
        obj = self.obj
        g = self.group("Coordinate System")

        def accept(sel):
            o = sel.obj
            if util.role(o) == "refgeom" and o.Proxy.KIND == "csys":
                return o.Name, o.Label
            return None
        self.cs = self.field(g, "Coordinate system", "CoordinateSystem", "coordinate system",
                             "Click a coordinate system", accept,
                             "The X and Y values are in this coordinate system (none: the "
                             "part's origin)", empty="Part origin")
        self.cs.changed.connect(lambda: self.set_prop(
            "CoordinateSystem",
            self.doc.getObject(self.cs.payloads()[0]) if self.cs.payloads() else None))
        self._loaders.append(lambda: self.cs.set_items(
            [(obj.CoordinateSystem.Name, obj.CoordinateSystem.Label)]
            if obj.CoordinateSystem is not None else []))
        g = self.group("Points", "Where each instance's centre goes (the original's centre "
                       "is point 0)")
        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["X (mm)", "Y (mm)"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(120)
        self.table.itemChanged.connect(self._edited)
        g.wide(self.table, "Type the X and Y of each instance; the last row is always empty "
               "for a new point")
        add_seed_groups(self, "Pattern")
        self._loaders.append(self._load_table)

    def _load_table(self):
        self.table.blockSignals(True)
        rows = list(self.obj.Points)
        self.table.setRowCount(len(rows) + 1)
        for r, t in enumerate(rows + [","]):
            x, _c, y = t.partition(",")
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(x))
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(y))
        self.table.blockSignals(False)

    def _edited(self, _item):
        out = []
        for r in range(self.table.rowCount()):
            x = self.table.item(r, 0)
            y = self.table.item(r, 1)
            x = x.text().strip() if x else ""
            y = y.text().strip() if y else ""
            if not x and not y:
                continue
            try:
                out.append("{:g},{:g}".format(float(x or 0), float(y or 0)))
            except ValueError:
                continue
        self.set_prop("Points", out)
        QtCore.QTimer.singleShot(0, self._load_table)


class FillPatternPanel(_SurfacePanel):
    TITLE = "Fill Pattern"
    ICON_NAME = "FillPattern"

    def build(self):
        obj = self.obj
        g = self.group("Fill Boundary")
        self.boundary = self.ref_box(g, "Boundary", "Face", "face", "Click a flat face",
                                     "The flat face to fill", ("Face",), empty="None")
        self.sketch = self.sketches_box(g, "BoundarySketch", "Or a sketch's closed region",
                                        multiple=False, label="Sketch", empty="None")
        g = self.group("Pattern Layout")
        self.lay_sw, _r = self.choice(
            g, "Layout", "Layout",
            "Perforation: staggered rows, like a perforated sheet. Circular: rings round the "
            "original. Square: a square grid. Polygon: polygon rings.")
        self.sp, _r = self.qty(g, "InstanceSpacing", "Instance spacing", "Between instances")
        self.loop, self.r_loop = self.qty(g, "LoopSpacing", "Loop spacing", "Between rings")
        self.stag, self.r_stag = self.qty(g, "StaggerAngle", "Stagger angle",
                                          "How each row shifts against the last", unit="deg",
                                          maximum=90.0, step=5.0)
        self.sides, self.r_sides = self.integer(g, "PolygonSides", "Sides",
                                                "The polygon's sides", minimum=3)
        self.margin, _r = self.qty(g, "Margin", "Margins", "Kept clear inside the boundary")
        self.dir = self.ref_box(g, "PatternDirection", "Direction", "direction",
                                "Click an edge", "The direction the rows run (none: along "
                                "the boundary's first straight edge)", ("Edge",),
                                empty="Automatic")
        g = self.group("Seed")
        self.seed, _r = self.choice(
            g, "SeedCut", "Create seed cut",
            "Cut this shape at every instance; None repeats the features you pick below")
        self.size, self.r_size = self.qty(g, "SeedSize", "Size", "The seed cut's size, across")
        self.ssides, self.r_ssides = self.integer(g, "SeedSides", "Sides", "Polygon seed: sides",
                                                  minimum=3)
        self.flip, self.r_flip = self.check(g, "FlipCut", "Flip cut", "Cut the other way")
        add_seed_groups(self, "Pattern")

    def refresh(self):
        lay = self.obj.Layout
        self.r_loop.set_visible(lay in (core.CONCENTRIC, core.POLYGON))
        self.r_stag.set_visible(lay == core.PERFORATION)
        self.r_sides.set_visible(lay == core.POLYGON)
        cut = self.obj.SeedCut != "None"
        self.r_size.set_visible(cut)
        self.r_ssides.set_visible(self.obj.SeedCut == "Polygon")
        self.r_flip.set_visible(cut)
        for sec in (self.sec_f, self.sec_fc, self.sec_b):
            sec.setVisible(not cut)
