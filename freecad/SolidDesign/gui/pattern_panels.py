# SPDX-License-Identifier: LGPL-2.1-or-later
"""Curve Driven, Sketch Driven, Table Driven and Fill pattern panels, and the
Instances to Skip list the Linear, Circular and Curve patterns share."""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from ..app import util
from ..core.features import pattern as core
from .panel import parts
from .surface_panel import _SurfacePanel

__all__ = ["CurvePatternPanel", "SketchPatternPanel", "TablePatternPanel", "FillPatternPanel",
           "VariablePatternPanel", "add_seed_groups", "SkipBox"]


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
        self.pick_btn = QtWidgets.QPushButton("Pick Instances in the View")
        self.pick_btn.setCheckable(True)
        self.pick_btn.setToolTip("While on, clicking the model where an instance is (or "
                                 "would be) leaves it out, or puts it back")
        g.wide(self.pick_btn)
        self.picking = False
        self.pick_btn.toggled.connect(self._toggle_pick)
        self._keys = []
        # The panel's clicks come here while picking; the instances are numbered in the
        # view.
        route, layers = panel.route, panel.preview_layers

        def routed(sel):
            if self.picking:
                self.pick(sel)
            else:
                route(sel)

        def with_marks():
            out = layers()
            out.append(("instances", self.marks()))
            return out
        panel.route = routed
        panel.preview_layers = with_marks

    def _toggle_pick(self, on):
        self.picking = bool(on)
        self.panel.update_preview()

    def centres(self):
        import json
        try:
            return [(str(k), App.Vector(x, y, z))
                    for k, x, y, z in json.loads(getattr(self.panel.obj, "InstanceCentres", "")
                                                 or "[]")]
        except (ValueError, TypeError):
            return []

    def pick(self, sel):
        """Toggle the instance nearest the click."""
        cs = self.centres()
        if not cs or sel.point is None:
            return
        key, c = min(cs, key=lambda kc: (kc[1] - sel.point).Length)
        gaps = [(a[1] - b[1]).Length for a in cs for b in cs if a is not b]
        reach = 0.6 * min(gaps) if gaps else float("inf")
        if (c - sel.point).Length > max(reach, 1e-6):
            return
        skipped = list(self.panel.obj.InstancesToSkip)
        if key in skipped:
            skipped.remove(key)
        else:
            skipped.append(key)
        Gui.Selection.clearSelection()
        self.panel.set_prop("InstancesToSkip", skipped)

    def marks(self):
        from . import preview as pv
        from pivy import coin
        cs = self.centres()
        if not cs:
            return None
        skipped = set(self.panel.obj.InstancesToSkip)
        node = coin.SoSeparator()
        for k, c in cs:
            node.addChild(pv.label_node((u"\u2715 " + k) if k in skipped else k, c))
        return node

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
        g = self.sec_d2 = self.group("Direction 2", "Pattern along a second curve too",
                                     checkable=True, prop="Direction2")
        self.curve2 = self.elements_list(g, "Curve2", "The second curve: model edges, end "
                                         "to end", "Edge", empty="None")
        self.sketch2 = self.sketches_box(g, "CurveSketch2", "Or a sketch", multiple=False,
                                         label="Sketch", empty="None")
        self.n2, _r = self.integer(g, "Instances2", "Instances", "How many along the second "
                                   "curve, counting the first row", minimum=1)
        self.equal2, _r = self.check(g, "EqualSpacing2", "Equal spacing",
                                     "Spread them over the whole second curve")
        self.sp2, self.r_sp2 = self.qty(g, "Spacing2", "Spacing", "Distance along the second "
                                        "curve", flip="Reverse2",
                                        flip_tip="Pattern the other way")
        add_seed_groups(self, "Pattern")
        self.skip = SkipBox(self, self._slots, self._fmt)

    def _slots(self):
        if self.obj.Direction2:
            return [(i, j) for j in range(1, self.obj.Instances2 + 1)
                    for i in range(1, self.obj.Instances + 1)]
        return list(range(1, self.obj.Instances + 1))

    def _fmt(self, k):
        return pair_text(k) if isinstance(k, tuple) else str(k)

    def refresh(self):
        self.r_sp.set_visible(not self.obj.EqualSpacing)
        self.r_sp2.set_visible(not self.obj.EqualSpacing2)
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
        read = QtWidgets.QPushButton("Read File...")
        read.setToolTip("Read the points from a table file (.sldptab or .txt: X and Y on "
                        "each line)")
        read.clicked.connect(self._read)
        save = QtWidgets.QPushButton("Save File...")
        save.setToolTip("Save the points as a table file (.sldptab or .txt)")
        save.clicked.connect(self._save)
        g.wide(parts.hbox(read, save), "Read or save the points as a table file")
        add_seed_groups(self, "Pattern")
        self._loaders.append(self._load_table)

    FILES = "Pattern tables (*.sldptab *.txt *.csv);;All files (*)"

    def _read(self):
        from ..app import pattern as app_pattern
        name, _f = QtWidgets.QFileDialog.getOpenFileName(self.widget, "Read Pattern Table",
                                                         "", self.FILES)
        if not name:
            return
        try:
            with open(name, "rb") as fh:
                raw = fh.read()
            text = raw.decode("utf-8") if b"\x00" not in raw else raw.decode("utf-16")
        except (IOError, OSError, UnicodeDecodeError) as e:
            self.show_error("Couldn't read {}: {}".format(name, e))
            return
        pts = app_pattern.read_table(text)
        if not pts:
            self.show_error("No X Y points found in that file. A table has one point per "
                            "line: X then Y.")
            return
        self.set_prop("Points", pts)
        self._load_table()

    def _save(self):
        from ..app import pattern as app_pattern
        name, _f = QtWidgets.QFileDialog.getSaveFileName(self.widget, "Save Pattern Table",
                                                         "pattern.sldptab", self.FILES)
        if not name:
            return
        try:
            with open(name, "w") as fh:
                fh.write(app_pattern.table_text(self.obj.Points))
        except (IOError, OSError) as e:
            self.show_error("Couldn't save {}: {}".format(name, e))

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


class VariablePatternPanel(_SurfacePanel):
    """The feature, the dimensions that change (columns), and one row per instance.
    New rows start from the feature's own values."""
    TITLE = "Variable Pattern"
    ICON_NAME = "VariablePattern"

    def build(self):
        g = self.group("Feature to Vary", "An Extrude or a Revolve")
        self.feats = self.features_box(g, "The feature to vary: click it in the tree, or a "
                                       "face it made")
        g = self.group("Dimensions", "The feature's own, and its sketch's named dimensions")
        self.dim_pick = QtWidgets.QComboBox()
        self.dim_pick.setToolTip("A dimension of the feature to change per instance")
        add = QtWidgets.QPushButton("Add")
        add.setToolTip("Add this dimension as a column")
        add.clicked.connect(self._add_dim)
        drop = QtWidgets.QPushButton("Remove")
        drop.setToolTip("Remove the selected column")
        drop.clicked.connect(self._drop_dim)
        g.wide(parts.hbox(self.dim_pick, add, drop), "Pick a dimension and Add it")
        g = self.group("Instances", "One row per instance; the original isn't in the table")
        self.table = QtWidgets.QTableWidget(0, 0)
        self.table.setMinimumHeight(140)
        self.table.itemChanged.connect(self._edited)
        g.wide(self.table, "Type each instance's values")
        new_row = QtWidgets.QPushButton("Add Instance")
        new_row.setToolTip("A new row, from the last row's values (or the feature's)")
        new_row.clicked.connect(self._add_row)
        del_row = QtWidgets.QPushButton("Delete Instance")
        del_row.clicked.connect(self._del_row)
        g.wide(parts.hbox(new_row, del_row), "Add or delete instances")
        self._loaders.append(self._load)

    # ---------------------------------------------------------- helpers
    def _feature(self):
        fs = [f for f in self.obj.Features if f is not None]
        return fs[0] if fs else None

    def _dims(self):
        from ..app import pattern as app_pattern
        f = self._feature()
        if f is None:
            return []
        try:
            return app_pattern.variable_dimensions(f)
        except Exception:
            return []

    def _current(self):
        return {k: v for k, _l, v in self._dims()}

    def _labels(self):
        return {k: l for k, l, _v in self._dims()}

    def _load(self):
        dims = self._dims()
        self.dim_pick.blockSignals(True)
        self.dim_pick.clear()
        for k, l, _v in dims:
            if k not in self.obj.Dimensions:
                self.dim_pick.addItem(l, k)
        self.dim_pick.blockSignals(False)
        cols = list(self.obj.Dimensions)
        labels = self._labels()
        self.table.blockSignals(True)
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels([labels.get(c, c) for c in cols])
        rows = [str(t).split(";") for t in self.obj.Instances]
        self.table.setRowCount(len(rows))
        for r, vals in enumerate(rows):
            for c in range(len(cols)):
                self.table.setItem(r, c, QtWidgets.QTableWidgetItem(
                    vals[c].strip() if c < len(vals) else ""))
        self.table.blockSignals(False)

    def _store(self):
        out = []
        for r in range(self.table.rowCount()):
            vals = []
            for c in range(self.table.columnCount()):
                it = self.table.item(r, c)
                vals.append(it.text().strip() if it else "")
            out.append(";".join(vals))
        self.set_prop("Instances", out)

    def _edited(self, _item):
        self._store()

    def _add_dim(self):
        k = self.dim_pick.currentData()
        if not k:
            return
        cur = self._current().get(k, 0.0)
        self.set_prop("Dimensions", list(self.obj.Dimensions) + [k])
        self.set_prop("Instances", ["{};{:g}".format(t, cur) if str(t) else "{:g}".format(cur)
                                    for t in self.obj.Instances])
        self._load()

    def _drop_dim(self):
        c = self.table.currentColumn()
        dims = list(self.obj.Dimensions)
        if not 0 <= c < len(dims):
            return
        del dims[c]
        rows = []
        for t in self.obj.Instances:
            vals = str(t).split(";")
            if c < len(vals):
                del vals[c]
            rows.append(";".join(vals))
        self.set_prop("Dimensions", dims)
        self.set_prop("Instances", rows)
        self._load()

    def _add_row(self):
        if self.obj.Instances:
            last = str(self.obj.Instances[-1])
        else:
            cur = self._current()
            last = ";".join("{:g}".format(cur.get(k, 0.0)) for k in self.obj.Dimensions)
        self.set_prop("Instances", list(self.obj.Instances) + [last])
        self._load()

    def _del_row(self):
        r = self.table.currentRow()
        rows = list(self.obj.Instances)
        if 0 <= r < len(rows):
            del rows[r]
            self.set_prop("Instances", rows)
            self._load()

    def refresh(self):
        # The feature may have changed: offer its dimensions.
        have = [self.dim_pick.itemData(i) for i in range(self.dim_pick.count())]
        want = [k for k, _l, _v in self._dims() if k not in self.obj.Dimensions]
        if have != want:
            self._load()
