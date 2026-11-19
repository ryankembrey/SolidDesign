# SPDX-License-Identifier: LGPL-2.1-or-later
"""Thread panel (SolidWorks' Thread PropertyManager)."""

from ..core import threads
from ..core.features import thread as core
from . import preview as pv
from .panel import parts
from .tool_panels import ToolPanel

__all__ = ["ThreadPanel"]


def _circular(shape):
    edges = [shape] if shape.ShapeType == "Edge" else shape.Edges
    if len(edges) != 1 or not hasattr(edges[0].Curve, "Radius"):
        return "Pick a circular edge: a shaft's end or a hole's rim."
    return None


class ThreadPanel(ToolPanel):
    TITLE = "Thread"

    def build(self):
        obj = self.obj
        g = self.group("Thread Location")
        self.edge = self.ref_box(g, "Edge", "Edge", "edge", "Click a circular edge",
                                 "The circular edge the thread starts at: a shaft's end or a "
                                 "hole's rim", ("Edge",), datum=False, check=_circular)
        self.off = parts.QuantityField(obj, "OffsetDistance")
        self.off.changed.connect(lambda v: self.set_prop("OffsetDistance", v))
        self.off_flip = self.flip_for("ReverseOffset", "Offset the other way")
        r = g.check_row("Offset", parts.hbox(self.off, self.off_flip),
                        "Start the thread away from the edge", obj.Offset)
        r.check.toggled.connect(lambda on: self.set_prop("Offset", on))
        g = self.group("End Condition")
        self.end, _r = self.choice(g, "EndCondition", "End condition",
                                   "Blind: a length. Revolutions: a number of turns. Up To "
                                   "Selection: to a face, plane or vertex.",
                                   flip="ReverseDirection",
                                   flip_tip="Thread the other way along the cylinder")
        self.length, self.r_length = self.qty(g, "Length", "Length", "Thread length")
        self.revs, self.r_revs = self.qty(g, "Revolutions", "Revolutions", "Number of turns",
                                          unit="", minimum=0.1)
        self.up_to = self.ref_box(g, "UpTo", "Up to", "face", "Click a face, plane or vertex",
                                  "The face, plane or vertex the thread ends at",
                                  ("Face", "Vertex"))
        g = self.group("Specification")
        self.series, _r = self.choice(g, "Series", "Type",
                                      "The thread standard: ISO metric coarse or fine, or "
                                      "Unified inch coarse (UNC) or fine (UNF)")
        self.size = parts.combo([], None, "The thread size; it starts at the one nearest the "
                                          "cylinder")
        self.size.currentTextChanged.connect(self._size_changed)
        g.row("Size", self.size, "The thread size")
        self.pitch = parts.QuantityField(obj, "Pitch", step=0.05)
        self.pitch.changed.connect(lambda v: self.set_prop("Pitch", v))
        r = g.check_row("Override pitch", self.pitch, "Use your own pitch instead of the size's",
                        obj.OverridePitch)
        r.check.toggled.connect(lambda on: self.set_prop("OverridePitch", on))
        self.method, _r = self.choice(g, "Method", "Thread method",
                                      "Cut Thread: cut the groove into the cylinder. Extrude "
                                      "Thread: grow the ridge out of it.")
        g = self.group("Thread Options")
        self.left, _r = self.check(g, "LeftHand", "Left-hand thread",
                                   "Turn the other way (off: a right-hand thread)")
        self.starts, _r = self.integer(g, "Starts", "Starts",
                                       "Number of threads side by side (a multi-start thread)")

    def _size_changed(self, text):
        if text and not self._loading:
            self.set_prop("Size", text)

    def _fill_sizes(self):
        sizes = threads.sizes(self.obj.Series)
        self.size.blockSignals(True)
        if [self.size.itemText(i) for i in range(self.size.count())] != sizes:
            self.size.clear()
            self.size.addItems(sizes)
        if self.obj.Size in sizes:
            self.size.setCurrentText(self.obj.Size)
        self.size.blockSignals(False)

    def refresh(self):
        t = self.end.currentText()
        self.r_length.set_visible(t == core.BLIND)
        self.r_revs.set_visible(t == core.REVOLUTIONS)
        self.up_to.row.set_visible(t == core.UP_TO)
        self._fill_sizes()

    def after_preview(self):
        # The size is picked from the cylinder on the first recompute, and the
        # pitch follows the size.
        self._fill_sizes()
        if not self.obj.OverridePitch:
            self.pitch.set_value(self.obj.Pitch.Value)

    def preview_layers(self):
        return [("result", pv.result_node(self.obj.AddSubShape,
                                          self.obj.Method == core.EXTRUDE))]
