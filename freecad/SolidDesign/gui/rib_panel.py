# SPDX-License-Identifier: LGPL-2.1-or-later
"""Rib panel (SolidWorks' Rib PropertyManager)."""

from ..app import part as part_mod
from . import selection as selmod
from .tool_panels import ToolPanel

__all__ = ["RibPanel"]


class RibPanel(ToolPanel):
    TITLE = "Rib"

    def build(self):
        g = self.group("Sketch")

        def accept(sel):
            sk = selmod.sketch_ref(sel)
            if sk is None:
                return None
            if sk is self.obj:
                return "Pick a sketch."
            return sk.Name, sk.Label
        self.sketch_box = self.field(g, "Sketch", "Sketch", "sketch", "Click a sketch", accept,
                                     "The open sketch lines the rib is made from")
        self.sketch_box.changed.connect(self._sketch_changed)
        self._loaders.append(lambda: self.sketch_box.set_items(
            [(self.obj.Sketch.Name, self.obj.Sketch.Label)] if self.obj.Sketch else []))

        g = self.group("Parameters")
        self.side, _r = self.choice(g, "ThicknessSide", "Thickness",
                                    "First Side or Second Side: the thickness goes to one side of "
                                    "the sketch line. Both Sides: centred on it.")
        self.t, _r = self.qty(g, "Thickness", "Rib thickness", "How thick the rib is", step=0.5)
        self.dir, _r = self.choice(g, "ExtrusionDirection", "Extrusion direction",
                                   "Parallel to Sketch: the rib lies in the sketch plane, from the "
                                   "line to the model. Normal to Sketch: it grows out of the "
                                   "sketch plane to the model.")
        self.flip, _r = self.check(g, "FlipMaterialSide", "Flip material side",
                                   "Grow the rib to the other side of the sketch line")
        self.ext, _r = self.choice(g, "ExtendType", "Type",
                                   "How the ends reach the model. Linear: along their "
                                   "tangents. Natural: arcs carry on round their circles.")
        d = self.group("Draft", "Lean the rib's sides", checkable=True, prop="Draft")
        self.dangle, _r = self.qty(d, "DraftAngle", "Angle", "Draft angle", unit="deg",
                                   maximum=44.0, step=0.5)
        self.dout, _r = self.check(d, "DraftOutward", "Draft outward",
                                   "Thicker towards the model; off: thinner")

    def _sketch_changed(self):
        p = self.sketch_box.payloads()
        sk = self.doc.getObject(p[0]) if p else None
        if sk is not None and self.part is not None and sk not in self.part.Group:
            part_mod.add_to_part(self.part, sk)
        if self.obj.Sketch is not sk:
            self.obj.Sketch = sk
        self.changed()
