# SPDX-License-Identifier: LGPL-2.1-or-later
"""Rib document object.

Like Extrude, it keeps the material it adds (ToolShape, Mode "Add"), so Linear
and Circular Pattern and Mirror can repeat a rib.
"""

import FreeCAD as App
import Part

from ..core import regions, topo
from ..core.bodies import IdAllocator
from ..core.features import rib as core
from . import feature, part as part_mod, util


class RibProxy(feature.FeatureProxy):
    TYPE = "Rib"
    LABELS = ("Rib",)

    def setup(self, obj):
        super(RibProxy, self).setup(obj)
        a = util.add_prop
        g = "Rib"
        a(obj, "App::PropertyLink", "Sketch", g, "The rib's sketch (open lines)")
        a(obj, "App::PropertyLength", "Thickness", g, "Rib thickness", 2.0)
        a(obj, "App::PropertyEnumeration", "ThicknessSide", g,
          "Which side of the sketch line the thickness goes", enum=core.SIDES)
        a(obj, "App::PropertyEnumeration", "ExtrusionDirection", g,
          "Parallel to Sketch: the rib lies in the sketch plane. Normal to Sketch: it grows "
          "out of the plane.", enum=core.DIRECTIONS)
        a(obj, "App::PropertyBool", "FlipMaterialSide", g,
          "Grow the rib to the other side of the sketch line", False)
        a(obj, "App::PropertyEnumeration", "ExtendType", g,
          "How the ends reach the model: Linear (along their tangents) or Natural (arcs "
          "carry on round their circles)", enum=core.EXTEND_TYPES)
        a(obj, "App::PropertyBool", "Draft", "Draft", "Lean the rib's sides", False)
        a(obj, "App::PropertyAngle", "DraftAngle", "Draft", "Draft angle", 1.0)
        a(obj, "App::PropertyBool", "DraftOutward", "Draft",
          "Thicker towards the model (off: thinner)", False)
        a(obj, "App::PropertyEnumeration", "Mode", g, "Ribs add material", enum=["Add"])
        a(obj, "Part::PropertyPartShape", "ToolShape", "Result",
          "The material the rib adds, repeated by patterns and mirrors")
        util.hide_prop(obj, "Mode")
        util.hide_prop(obj, "ToolShape")

    def compute(self, obj, base):
        sketch = obj.Sketch
        if sketch is None:
            raise topo.GeometryError("Pick the rib's sketch.")
        p = core.Params()
        shape = topo.shape_of(sketch)
        if not shape.Edges:
            raise topo.GeometryError("{} is empty.".format(sketch.Label))
        p.wires = list(shape.Wires)
        loose = [e for e in shape.Edges
                 if not any(e.isSame(x) for w in shape.Wires for x in w.Edges)]
        p.wires.extend(Part.Wire([e]) for e in loose)
        if any(w.isClosed() for w in p.wires):
            raise topo.GeometryError("A rib is made from open sketch lines; {} has a closed "
                                     "profile. Use Extrude for that.".format(sketch.Label))
        p.origin = regions.sketch_placement(sketch).Base
        p.normal = regions.sketch_normal(sketch)
        p.thickness = obj.Thickness.Value
        p.side = obj.ThicknessSide
        p.direction = obj.ExtrusionDirection
        p.flip = obj.FlipMaterialSide
        p.extend_type = obj.ExtendType
        p.draft = obj.Draft
        p.draft_angle = obj.DraftAngle.Value
        p.draft_outward = obj.DraftOutward
        p.feature = obj.Name
        p.tag = obj.ID
        p.alloc = IdAllocator(obj.Name, IdAllocator.loads(obj.IdMemory), taken=base.ids())
        res, tool, preview = core.compute(p, base)
        obj.ToolShape = tool
        mem = p.alloc.dumps()
        if obj.IdMemory != mem:
            obj.IdMemory = mem
        return res, preview


def create(doc, part, mode="Add", sketch=None):
    """A new Rib in ``part`` at the rollback bar (``mode`` is ignored: ribs add)."""
    obj = doc.addObject("Part::FeaturePython", "Rib")
    RibProxy(obj)
    obj.ThicknessSide = core.BOTH
    obj.AutoLabel = util.set_label(obj, RibProxy.LABELS[0])
    if sketch is not None:
        obj.Sketch = sketch
    part_mod.insert_feature(part, obj, [sketch] if sketch is not None else [])
    if App.GuiUp:
        from ..gui import viewproviders
        viewproviders.attach_feature(obj)
    return obj
