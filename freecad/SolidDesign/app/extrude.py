# SPDX-License-Identifier: LGPL-2.1-or-later
"""Extrude document object: one feature, an Add or Cut mode (spec 3.1)."""

import FreeCAD as App

from ..core import topo
from ..core.features import extrude as core
from . import refs, sketchfeature, util


class ExtrudeProxy(sketchfeature.SketchFeatureProxy):
    TYPE = "Extrude"
    LABELS = ("Boss-Extrude", "Cut-Extrude", "Surface-Extrude")
    CAP_ENDS = True

    def setup(self, obj):
        super(ExtrudeProxy, self).setup(obj)
        a = util.add_prop
        g = "Extrude"
        a(obj, "App::PropertyBool", "Reverse", g, "Reverse Direction", False)
        a(obj, "App::PropertyBool", "CapEnd", "Surface",
          "Surface mode: close both ends of a closed profile (a closed surface)", False)

        g = "From"
        a(obj, "App::PropertyEnumeration", "From", g, "Where the extrusion starts",
          enum=core.FROM_KINDS)
        a(obj, "App::PropertyLength", "FromOffset", g, "Offset of the start from the sketch", 0.0)
        a(obj, "App::PropertyBool", "FromReverse", g, "Reverse the start offset", False)
        a(obj, "App::PropertyLinkSub", "FromFace", g, "Face or plane to start from")
        a(obj, "App::PropertyLinkSub", "FromVertex", g, "Vertex to start from")
        a(obj, "App::PropertyLinkSub", "DirectionOfExtrusion", "Direction 1",
          "Extrude along an edge, axis or plane normal instead of the sketch's normal")

        for n, label in (("", "Direction 1"), ("2", "Direction 2")):
            g = label
            if n:
                a(obj, "App::PropertyBool", "Direction2", g, "Extrude in the other direction too",
                  False)
            a(obj, "App::PropertyEnumeration", "EndCondition" + n, g, "End condition",
              enum=core.END_CONDITIONS if not n else core.END_CONDITIONS_2)
            a(obj, "App::PropertyLength", "Depth" + n, g, "Depth", 10.0)
            a(obj, "App::PropertyLinkSub", "UpToFace" + n, g, "Face or plane to extrude up to")
            a(obj, "App::PropertyLinkSub", "UpToVertex" + n, g, "Vertex to extrude up to")
            a(obj, "App::PropertyString", "UpToBody" + n, g, "Body ID to extrude up to", "")
            a(obj, "App::PropertyLength", "Offset" + n, g, "Offset From Surface distance", 0.0)
            a(obj, "App::PropertyBool", "ReverseOffset" + n, g, "Reverse offset", False)
            a(obj, "App::PropertyBool", "Draft" + n, g, "Draft on/off", False)
            a(obj, "App::PropertyAngle", "DraftAngle" + n, g, "Draft angle", 1.0)
            a(obj, "App::PropertyBool", "DraftOutward" + n, g, "Draft outward", False)

    def _extent(self, obj, n, warns):
        e = core.Extent()
        e.condition = getattr(obj, "EndCondition" + n)
        e.depth = getattr(obj, "Depth" + n).Value
        e.offset = getattr(obj, "Offset" + n).Value
        e.reverse_offset = getattr(obj, "ReverseOffset" + n)
        if getattr(obj, "Draft" + n):
            e.draft = getattr(obj, "DraftAngle" + n).Value
            e.draft_outward = getattr(obj, "DraftOutward" + n)
        if e.condition in (core.UP_TO_SURFACE, core.OFFSET_FROM_SURFACE):
            e.face = self.face_ref(obj, "UpToFace" + n, "Up To Surface face", warns)
        elif e.condition == core.UP_TO_VERTEX:
            e.vertex = self.vertex_ref(obj, "UpToVertex" + n, "Up To Vertex vertex", warns)
        elif e.condition == core.UP_TO_BODY:
            e.body = getattr(obj, "UpToBody" + n)
        return e

    def compute(self, obj, base):
        from ..core import regions
        warns = []
        p = core.Params()
        p.mode = obj.Mode
        p.tag = obj.ID
        p.feature = obj.Name
        p.faces, p.open_wires = self.profile(obj, warns)
        sketch = obj.Sketch
        p.origin = regions.sketch_placement(sketch).Base
        p.normal = regions.sketch_normal(sketch)
        p.reverse = obj.Reverse
        v = obj.DirectionOfExtrusion
        if v and v[0] is not None:
            s, w = refs.get_ref(obj, "DirectionOfExtrusion", "direction of extrusion",
                                obj.BaseFeature)
            if w:
                warns.append(w)
            if s is not None:
                from .pattern import direction_of
                d = App.Vector(direction_of(s, "direction of extrusion")[1]).normalize()
                if d.dot(p.normal) < 0:
                    d = -d
                if abs(d.dot(p.normal)) < 1e-6:
                    raise topo.GeometryError("The direction of extrusion lies in the sketch's "
                                             "plane; pick one that leaves it.")
                p.direction = d
        p.from_kind = obj.From
        p.from_offset = obj.FromOffset.Value
        p.from_reverse = obj.FromReverse
        if p.from_kind == core.FROM_SURFACE:
            p.from_face = self.face_ref(obj, "FromFace", "From face", warns)
        elif p.from_kind == core.FROM_VERTEX:
            p.from_vertex = self.vertex_ref(obj, "FromVertex", "From vertex", warns)
        p.dir1 = self._extent(obj, "", warns)
        if obj.Direction2 and obj.EndCondition not in (core.MID_PLANE, core.THROUGH_ALL_BOTH):
            p.dir2 = self._extent(obj, "2", warns)
        p.thin = self.thin(obj) if p.mode != "Surface" else None
        p.cap_end = obj.CapEnd
        p.merge, p.scope, p.keep, p.flip, p.alloc = self.bodies_options(obj, base, warns)
        res, tool, preview = core.compute(p, base)
        self.finish(obj, res, p.alloc, warns, tool)
        return res, preview


def create(doc, part, mode="Add", sketch=None):
    """A new Extrude in ``part`` at the rollback bar."""
    return sketchfeature.create(ExtrudeProxy, doc, part, mode, sketch, "Extrude")
