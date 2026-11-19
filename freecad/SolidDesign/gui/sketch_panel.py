# SPDX-License-Identifier: LGPL-2.1-or-later
"""The panel shared by sketch-based Add | Cut tools (Extrude, Revolve...).

Same names and results as SolidWorks. Departures (listed in
docs/_notes/ux-departures.md):
- the sketch sits in a box at the top, so it's always clear what is used;
- Selected Contours are picked by clicking inside regions in the view, with
  every region shown and the picked ones highlighted;
- Bodies to Keep is a group of the panel, filled before OK with the pieces
  labelled in the view, not a dialog after OK.
"""

import json

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from .. import icon
from ..app import part as part_mod
from ..app import refs
from ..core import regions, topo
from ..core.bodies import BodySet
from ..core.features import profile as core
from . import preview as pv
from . import selection as selmod
from .panel import parts
from .panel.base import FeaturePanel


def _fmt_len(v):
    return App.Units.Quantity(v, App.Units.Length).UserString


def _fmt_ang(v):
    return App.Units.Quantity(v, App.Units.Angle).UserString


LAST = [None]   # the open panel, for the GUI smoke tests


class SketchFeaturePanel(FeaturePanel):
    """Mode, sketch, Thin Feature, Selected Contours, Feature Scope and Bodies to
    Keep: what every sketch-based Add | Cut tool shares. Subclasses add their own
    sections in build_parameters() and say where Merge result goes."""

    TITLE = "Feature"
    ICONS = ("ExtrudeAdd", "ExtrudeCut")
    SKETCH_TITLE = "Sketch"

    def __init__(self, obj, is_new=False):
        LAST[0] = self
        self.ICON = icon(self.ICONS[0] if obj.Mode == "Add" else self.ICONS[1])
        self._regions = []
        self._click_cb = None
        self._loaders = []          # for building blocks borrowed from ToolPanel
        super(SketchFeaturePanel, self).__init__(obj, is_new)

    # ------------------------------------------------------------ to override
    def build_parameters(self, layout):
        pass

    def load_parameters(self):
        pass

    def build_profile_rows(self, group):
        """Rows above the sketch field, in the sketch's group."""
        pass

    def refresh_parameters(self):
        pass

    def add_body_rows(self, group):
        """Merge result (Add) and Flip side to cut (Cut), in *group*."""
        self.merge, self.r_merge = self.check(
            group, "MergeResult", "Merge result",
            "Fuse the new material with the bodies it touches. Off: it becomes a body "
            "of its own.")
        self.flip_side, self.r_flip_side = self.check(
            group, "FlipSideToCut", "Flip side to cut",
            "Remove the material outside the profile instead of inside it")
        self._body_group = group

    # ------------------------------------------------------------ helpers
    def base_bodies(self):
        b = self.obj.BaseFeature
        if b is None:
            return BodySet()
        try:
            return BodySet.from_columns(b.Shape, list(b.BodyIds), list(b.BodyKinds),
                                        list(b.BodyFeatures))
        except topo.GeometryError:
            return BodySet()

    def base_ids(self):
        b = self.obj.BaseFeature
        return list(b.BodyIds) if b is not None else []

    SKETCH_LABEL = "Sketch"
    SKETCH_TIP = "The sketch to use. Press the button, then click a sketch in the 3D view or tree."

    def build(self):
        obj = self.obj
        L = self.layout
        self.mode = parts.Switch(
            ["Add", "Cut"],
            tips={"Add": "Add material: the new shape is fused to the bodies it touches",
                  "Cut": "Remove material: the shape is cut from the bodies in the feature scope"},
            icons={"Add": icon(self.ICONS[0]), "Cut": icon(self.ICONS[1])})
        self.mode.set_value(obj.Mode)
        self.mode.changed.connect(self._mode_changed)
        L.addWidget(self.mode)

        # Sketch (top) -------------------------------------------------
        self.sec_sketch = self.group(self.SKETCH_TITLE)
        self.build_profile_rows(self.sec_sketch)
        self.sketch_box = self.field(self.sec_sketch, self.SKETCH_LABEL, "Sketch", "sketch",
                                     "Click a sketch", self._accept_sketch, self.SKETCH_TIP)
        self.sketch_box.changed.connect(self._sketch_changed)

        self.build_parameters(L)

        # Thin Feature -------------------------------------------------
        g = self.sec_thin = self.group(
            "Thin Feature", "Make a wall of constant thickness from the sketch's curves "
            "instead of filling it", checkable=True, prop="Thin")
        self.thin_type, _r = self.choice(
            g, "ThinType", "Type", "Which side of the curves the wall grows on",
            flip="ThinReverse", flip_tip="Grow the wall on the other side of the curves")
        self.thin_flip = self.thin_type.flip
        self.thin_t1, _r = self.qty(g, "ThinThickness", "Thickness", "Wall thickness")
        self.thin_t2, self.r_thin_t2 = self.qty(g, "ThinThickness2", "Thickness 2",
                                                "Wall thickness on the second side")
        self.cap = None
        if "CapEnds" in obj.PropertiesList:
            self.cap, _r = self.check(g, "CapEnds", "Cap ends",
                                      "Close the ends of the thin feature with walls")
            self.cap_t, self.r_cap_t = self.qty(g, "CapThickness", "Cap thickness",
                                                "Thickness of the end caps")

        # Selected Contours --------------------------------------------
        g = self.sec_contours = self.group("Selected Contours")
        self.contours = self.list(
            g, "Contours", "regions", "Click inside regions of the sketch", lambda s: None,
            "Use only some regions of the sketch: click inside them in the 3D view. "
            "Empty: the whole sketch.", empty="Whole sketch")
        self.contours.changed.connect(self._contours_changed)

        # Feature Scope ------------------------------------------------
        g = self.sec_scope = self.group(
            "Feature Scope", "Which bodies the feature works on")
        self.scope_mode = parts.Switch(
            ["All bodies", "Selected bodies"],
            tips={"All bodies": "The feature works on every body it touches",
                  "Selected bodies": "The feature works only on the bodies you choose"})
        self.scope_mode.set_value(obj.FeatureScope)
        g.wide(self.scope_mode)
        self.auto, self.r_auto = self.check(
            g, "AutoSelect", "Auto-select",
            "Use the bodies the feature touches; untick to choose them")
        self.scope_box = self.list(g, "ScopeBodies", "bodies",
                                   "Click bodies in the 3D view or tree", self._accept_scope,
                                   "The bodies the feature works on")
        self.scope_mode.changed.connect(lambda m: self.set_prop("FeatureScope", m))
        self.scope_box.changed.connect(
            lambda: self.set_prop("ScopeBodies", list(self.scope_box.payloads())))

        # Bodies to Keep -----------------------------------------------
        g = self.sec_keep = self.group(
            "Bodies to Keep", "The cut splits a body: choose which pieces to keep")
        self.keep_mode = parts.Switch(
            ["All bodies", "Selected bodies"],
            tips={"All bodies": "Keep every piece the cut leaves",
                  "Selected bodies": "Keep only the ticked pieces; the others are deleted"})
        self.keep_mode.set_value(obj.BodiesToKeep)
        g.wide(self.keep_mode)
        self.keep_list = QtWidgets.QListWidget()
        self.keep_list.setToolTip("Tick the pieces to keep. They are numbered in the 3D view.")
        g.wide(self.keep_list)
        self.keep_mode.changed.connect(
            lambda m: self._keep_mode_changed(m == "All bodies"))
        self.keep_list.itemChanged.connect(self._keep_item_changed)

    # ------------------------------------------------------------ load
    def load(self):
        obj = self.obj
        if obj.Sketch is not None:
            self.sketch_box.set_items([(obj.Sketch.Name, obj.Sketch.Label)])
        self.load_parameters()
        for fn in self._loaders:
            fn()
        self._load_contours()
        self.scope_box.set_items([(i, self.body_label(i)) for i in obj.ScopeBodies])
        self.refresh()

    def _load_contours(self):
        items = []
        for i, key in enumerate(self.obj.Contours, 1):
            items.append((key, "Region {}".format(i)))
        self.contours.set_items(items)

    # ------------------------------------------------------------ refresh
    def refresh(self):
        obj = self.obj
        add = obj.Mode == "Add"
        first = obj.BaseFeature is None or not self.base_ids()
        n_bodies = len(self.base_ids())
        if getattr(self, "_body_group", None) is not None:
            self.r_merge.set_visible(add and not first)
            self.r_flip_side.set_visible(not add)
        self.refresh_parameters()
        # Thin
        self.r_thin_t2.set_visible(self.thin_type.currentText() == core.THIN_TWO)
        if self.cap is not None:
            self.r_cap_t.set_visible(self.cap.isChecked())
        # Scope: only when there is a choice to make (spec 8.1, auto-select the obvious).
        uses_scope = (not add) or obj.MergeResult
        self.sec_scope.setVisible(uses_scope and n_bodies > 1)
        sel = obj.FeatureScope == "Selected bodies"
        self.r_auto.set_visible(sel)
        self.scope_box.row.set_visible(sel and not obj.AutoSelect)
        # Bodies to Keep: shown only when the cut splits a body.
        self._refresh_keep()
        # Icon follows the mode.
        self.widget.setWindowIcon(QtGui.QIcon(icon(self.ICONS[0] if add else self.ICONS[1])))

    def _pieces(self):
        try:
            return json.loads(self.obj.Pieces or "[]")
        except ValueError:
            return []

    def _refresh_keep(self):
        pieces = self._pieces()
        show = self.obj.Mode == "Cut" and len(pieces) > 1
        self.sec_keep.setVisible(show)
        if not show:
            return
        sel = self.obj.BodiesToKeep == "Selected bodies"
        self.keep_list.setEnabled(sel)
        keep = set(self.obj.KeepBodies)
        self.keep_list.blockSignals(True)
        self.keep_list.clear()
        for i, p in enumerate(pieces, 1):
            it = QtWidgets.QListWidgetItem("Body {}  ({})".format(i, self.body_label(p["parent"])))
            it.setData(QtCore.Qt.UserRole, p["id"])
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked if (not sel or p["id"] in keep)
                             else QtCore.Qt.Unchecked)
            self.keep_list.addItem(it)
        self.keep_list.blockSignals(False)
        rows = min(max(self.keep_list.count(), 2), 6)
        self.keep_list.setFixedHeight(max(self.keep_list.sizeHintForRow(0),
                                          self.keep_list.fontMetrics().height() + 4) * rows + 8)

    # ------------------------------------------------------------ handlers
    def _mode_changed(self, mode):
        self.set_prop("Mode", mode)

    def _accept_sketch(self, sel):
        sk = selmod.sketch_ref(sel)
        if sk is None:
            return None
        if sk is self.obj:
            return "Pick a sketch."
        return sk.Name, sk.Label

    def _sketch_changed(self):
        p = self.sketch_box.payloads()
        sk = self.doc.getObject(p[0]) if p else None
        if sk is not None and self.part is not None and sk not in self.part.Group:
            part_mod.add_to_part(self.part, sk)
        if self.obj.Sketch is not sk:
            self.obj.Sketch = sk
            self.obj.Contours = []
            self._load_contours()
        self.changed()

    def _accept_ref(self, sel, kind):
        fn = selmod.face_ref if kind == "face" else selmod.vertex_ref
        r = fn(sel, self.obj.BaseFeature, self.obj)
        if r is None or isinstance(r, str):
            return r
        o, sub = r
        return (o.Name, sub), self.ref_text(o, sub)

    def _set_link(self, prop, box):
        p = box.payloads()
        if p:
            refs.set_ref(self.obj, prop, self.doc.getObject(p[0][0]), p[0][1])
        else:
            refs.set_ref(self.obj, prop, None)
        self.changed()

    def _accept_scope(self, sel):
        r = selmod.body_ref(sel, self.base_ids())
        if r is None or isinstance(r, str):
            return r
        return r[0], self.body_label(r[0])

    def _contours_changed(self):
        keys = [k for k in self.contours.payloads()]
        if list(self.obj.Contours) != keys:
            self.obj.Contours = keys
        self._load_contours()
        self._draw_regions()
        self.changed()

    def _keep_mode_changed(self, all_on):
        self.set_prop("BodiesToKeep", "All bodies" if all_on else "Selected bodies")
        if not all_on and not self.obj.KeepBodies:
            self.obj.KeepBodies = [p["id"] for p in self._pieces()]

    def _keep_item_changed(self, it):
        ids = []
        for i in range(self.keep_list.count()):
            x = self.keep_list.item(i)
            if x.checkState() == QtCore.Qt.Checked:
                ids.append(x.data(QtCore.Qt.UserRole))
        if not ids:
            self.show_error("Keep at least one body.")
            self._refresh_keep()
            return
        self.set_prop("KeepBodies", ids)

    # ------------------------------------------------------------ contours in the view
    def on_box_activated(self, box):
        if box is self.contours:
            self._start_region_picking()
        else:
            self._stop_region_picking()

    def _start_region_picking(self):
        sk = self.obj.Sketch
        if sk is None:
            self.contours.say("Pick the sketch first.")
            return
        try:
            self._regions = regions.regions(sk, self.obj.ID)
        except topo.GeometryError as e:
            self.contours.say(str(e))
            self._regions = []
        self._draw_regions()
        if self._click_cb is None:
            try:
                view = Gui.ActiveDocument.ActiveView
                self._click_view = view
                self._click_cb = view.addEventCallback("SoMouseButtonEvent", self._on_click)
            except Exception:
                self._click_cb = None

    def _stop_region_picking(self):
        if self._click_cb is not None:
            try:
                self._click_view.removeEventCallback("SoMouseButtonEvent", self._click_cb)
            except Exception:
                pass
            self._click_cb = None
        self.preview.clear("regions")

    def _draw_regions(self):
        if self.active_box is not self.contours or not self._regions:
            self.preview.clear("regions")
            return
        from pivy import coin
        root = coin.SoSeparator()
        picked = set(self.obj.Contours)
        picked_ids = [regions.decode(k) for k in picked]
        for r in self._regions:
            hit = any(ids == r.geo_ids for ids, _pt in picked_ids)
            root.addChild(pv.shape_node(r.face, pv.REGION_PICKED if hit else pv.REGION_COLOR,
                                        0.25 if hit else 0.8, edges=False))
        self.preview.set("regions", root)

    def _on_click(self, info):
        if info.get("State") != "DOWN" or info.get("Button") != "BUTTON1":
            return
        sk = self.obj.Sketch
        if sk is None or not self._regions:
            return
        try:
            view = self._click_view
            pos = info["Position"]
            p1 = view.getPoint(pos)
            d = view.getViewDirection()
            pl = regions.sketch_placement(sk)
            n = pl.Rotation.multVec(App.Vector(0, 0, 1))
            den = d.dot(n)
            if abs(den) < 1e-9:
                return
            t = (pl.Base - p1).dot(n) / den
            pt = p1 + d * t
        except Exception:
            return
        for r in self._regions:
            if r.face.isInside(pt, regions.POINT_TOL, False):
                key = r.key()
                keys = list(self.obj.Contours)
                same = [k for k in keys if regions.decode(k)[0] == r.geo_ids]
                if same:
                    keys = [k for k in keys if k not in same]
                else:
                    keys.append(key)
                self.contours.set_items([(k, "") for k in keys])
                self._contours_changed()
                return

    # ------------------------------------------------------------ preview
    def preview_layers(self):
        shape = self.obj.AddSubShape
        add = self.obj.Mode == "Add"
        node = pv.result_node(shape, add)
        layers = [("result", node)]
        labels = None
        pieces = self._pieces()
        if not add and len(pieces) > 1:
            from pivy import coin
            labels = coin.SoSeparator()
            for i, p in enumerate(pieces, 1):
                labels.addChild(pv.label_node("Body {}".format(i), App.Vector(*p["c"])))
        layers.append(("labels", labels))
        return layers

    def after_preview(self):
        self._refresh_keep()
        # Point at the fix: an error about contours opens Selected Contours.
        if "Selected Contours" in (self.obj.ErrorMessage or "") and \
                self.active_box is not self.contours:
            self.activate(self.contours)
            return
        if self.active_box is self.contours:
            self._start_region_picking()

    def on_close(self):
        self._stop_region_picking()
