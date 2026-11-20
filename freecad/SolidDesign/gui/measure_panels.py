# SPDX-License-Identifier: LGPL-2.1-or-later
"""Bounding Box and Center of Mass panels: what they measure, and what they found."""

from PySide import QtWidgets

from ..core import refgeom as core
from .panel import parts
from .surface_panel import _SurfacePanel

__all__ = ["panel_for"]


class _MeasuredPanel(_SurfacePanel):
    def preview_layers(self):
        return []           # the box or point itself shows as it changes

    def _result_label(self, group, tip):
        self.result = QtWidgets.QLabel("")
        self.result.setWordWrap(True)
        group.wide(self.result, tip)

    def after_preview(self):
        super(_MeasuredPanel, self).after_preview()
        self.show_result()


class BoundingBoxPanel(_MeasuredPanel):
    TITLE = "Bounding Box"
    ICON_NAME = "BoundingBox"

    def build(self):
        obj = self.obj
        g = self.group("Bounding Box")
        self.kind = parts.Switch(
            core.BOX_TYPES,
            tips={core.BEST_FIT: "The smallest box round the bodies",
                  core.REFERENCE_PLANE: "A box square to a plane, turned in it to fit"})
        self.kind.set_value(obj.Type)
        self.kind.changed.connect(lambda m: self.set_prop("Type", m))
        g.wide(self.kind)
        self.plane = self.ref_box(g, "Reference1", "Plane", "plane", "Click a plane or face",
                                  "The box sits square to this plane", kinds=("Face",))
        self.surf, _r = self.check(g, "IncludeSurfaces", "Include surface bodies",
                                   "Put the surface bodies in the box too")
        g = self.group("Bodies")
        self.bodies = self.bodies_box(g, "Bodies", "The bodies in the box (none picked: "
                                      "every body)", empty="Every body")
        g = self.group("Size")
        self._result_label(g, "Length, width and thickness of the box")

    def refresh(self):
        self.plane.row.set_visible(self.obj.Type == core.REFERENCE_PLANE)
        self.show_result()

    def show_result(self):
        o = self.obj
        if o.ErrorMessage:
            self.result.setText("")
            return
        self.result.setText(u"{:.6g} × {:.6g} × {:.6g} mm\nVolume {:.6g} mm³"
                            .format(o.Length.Value, o.Width.Value, o.Thickness.Value,
                                    o.BoxVolume.Value))


class CenterOfMassPanel(_MeasuredPanel):
    TITLE = "Center of Mass"
    ICON_NAME = "CenterOfMass"

    def build(self):
        g = self.group("Bodies")
        self.bodies = self.bodies_box(g, "Bodies", "The solid bodies it measures (none "
                                      "picked: every solid body)", empty="Every solid body")
        g = self.group("Position")
        self._result_label(g, "Where the centre of mass is")

    def refresh(self):
        self.show_result()

    def show_result(self):
        o = self.obj
        vs = o.Shape.Vertexes if not o.Shape.isNull() else []
        if o.ErrorMessage or not vs:
            self.result.setText("")
            return
        p = vs[0].Point
        self.result.setText("X {:.6g}   Y {:.6g}   Z {:.6g} mm".format(p.x, p.y, p.z))


class CosmeticThreadPanel(_MeasuredPanel):
    """The edge, how far it goes, and the thread's size; the callout shows below."""
    TITLE = "Cosmetic Thread"
    ICON_NAME = "CosmeticThread"

    def build(self):
        from ..core import threads
        obj = self.obj
        g = self.group("Thread Settings")
        self.edge = self.ref_box(g, "Reference1", "Edge", "edge", "Click a circular edge",
                                 "The circular edge where the thread starts: a shaft's end or "
                                 "a hole's rim", kinds=("Edge",), datum=False)
        self.end, _r = self.choice(g, "Type", "End", "Blind: a length. Up To Next: to the end "
                                   "of the cylinder", flip="Flip",
                                   flip_tip="Run the thread the other way from the edge")
        self.length, self.r_length = self.qty(g, "Length", "Length", "Thread length")
        g = self.group("Specification")
        self.series, _r = self.choice(g, "Series", "Type", "The thread standard and series")
        self.size = parts.combo([], None, "The thread size; it starts at the one nearest the "
                                          "cylinder")
        self.size.currentTextChanged.connect(
            lambda t: self.set_prop("Size", t) if t and not self._loading else None)
        g.row("Size", self.size, "The thread size")
        self.cls = QtWidgets.QLineEdit(obj.ThreadClass)
        self.cls.setPlaceholderText("6g, 6H, 2A...")
        self.cls.editingFinished.connect(lambda: self.set_prop("ThreadClass",
                                                               self.cls.text().strip()))
        g.row("Class", self.cls, "The tolerance class, for the callout")
        self._series = threads
        g = self.group("Callout")
        self._result_label(g, "The thread's callout, and the diameter it shows")

    def _fill_sizes(self):
        sizes = self._series.sizes(self.obj.Series)
        self.size.blockSignals(True)
        if [self.size.itemText(i) for i in range(self.size.count())] != sizes:
            self.size.clear()
            self.size.addItems(sizes)
        if self.obj.Size in sizes:
            self.size.setCurrentText(self.obj.Size)
        self.size.blockSignals(False)

    def refresh(self):
        self.r_length.set_visible(self.obj.Type == "Blind")
        self._fill_sizes()
        self.show_result()

    def show_result(self):
        o = self.obj
        self._fill_sizes()
        if o.ErrorMessage or not o.Callout:
            self.result.setText("")
            return
        self.result.setText(u"{}\n\u2300 {:.4g} mm shown".format(o.Callout, o.Diameter.Value))


def panel_for(obj):
    return {"bbox": BoundingBoxPanel, "com": CenterOfMassPanel,
            "cosmetic": CosmeticThreadPanel}[obj.Proxy.PANEL]
