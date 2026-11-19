# SPDX-License-Identifier: LGPL-2.1-or-later
"""Offset Surface, Move Face and Split Line document objects."""

import FreeCAD as App

from ..core import refgeom as core_ref
from ..core import topo
from ..core.bodies import IdAllocator
from ..core.features import faceops as core
from ..core.features import splitline as core_split
from . import feature, part as part_mod, refs, util


class OffsetSurfaceProxy(feature.FeatureProxy):
    TYPE = "OffsetSurface"
    LABELS = ("Surface-Offset",)

    def setup(self, obj):
        super(OffsetSurfaceProxy, self).setup(obj)
        a = util.add_prop
        g = "Offset Surface"
        a(obj, "App::PropertyLinkSub", "Items", g, "Faces or surfaces to offset")
        a(obj, "App::PropertyDistance", "Distance", g, "Offset distance (0: a copy)", 1.0)
        a(obj, "App::PropertyBool", "Flip", g, "Offset to the other side", False)

    def compute(self, obj, base):
        p = core.OffsetParams()
        p.faces, warns = refs.get_refs(obj, "Items", "face to offset", obj.BaseFeature)
        p.distance = obj.Distance.Value
        p.flip = obj.Flip
        p.feature = obj.Name
        p.tag = obj.ID
        p.alloc = IdAllocator(obj.Name, IdAllocator.loads(obj.IdMemory), taken=base.ids())
        res, preview = core.offset_surface(p, base)
        mem = p.alloc.dumps()
        if obj.IdMemory != mem:
            obj.IdMemory = mem
        res.warnings.extend(warns)
        return res, preview


class MoveFaceProxy(feature.FeatureProxy):
    TYPE = "MoveFace"
    LABELS = ("Move Face",)

    def setup(self, obj):
        super(MoveFaceProxy, self).setup(obj)
        a = util.add_prop
        g = "Move Face"
        a(obj, "App::PropertyEnumeration", "MoveType", g, "Offset, Translate or Rotate",
          enum=core.MOVE_TYPES)
        a(obj, "App::PropertyLinkSub", "Items", g, "Faces to move")
        a(obj, "App::PropertyLength", "Distance", g, "Distance (Offset, Translate)", 1.0)
        a(obj, "App::PropertyLinkSub", "Direction", g,
          "Translate: an edge, axis or face (its normal) to move along")
        a(obj, "App::PropertyLinkSub", "Axis", g, "Rotate: an edge or axis to turn about")
        a(obj, "App::PropertyAngle", "Angle", g, "Rotate: angle", 10.0)
        a(obj, "App::PropertyBool", "Flip", g, "The other way", False)

    def compute(self, obj, base):
        warns = []
        p = core.MoveParams()
        p.kind = obj.MoveType
        p.faces, w = refs.get_refs(obj, "Items", "face to move", obj.BaseFeature)
        warns.extend(w)
        p.distance = obj.Distance.Value
        p.angle = obj.Angle.Value
        p.flip = obj.Flip
        if p.kind == core.TRANSLATE:
            s, w = refs.get_ref(obj, "Direction", "direction", obj.BaseFeature)
            warns.append(w)
            if s is not None:
                p.direction = core_ref.direction_of(s, "direction")
        if p.kind == core.ROTATE:
            s, w = refs.get_ref(obj, "Axis", "axis", obj.BaseFeature)
            warns.append(w)
            if s is not None:
                p.axis = core_ref.line_of(s, "axis")
        p.feature = obj.Name
        p.tag = obj.ID
        res, preview = core.move_face(p, base)
        res.warnings.extend(x for x in warns if x)
        return res, preview


def _create(cls, doc, part, name, items=None):
    obj = doc.addObject("Part::FeaturePython", name)
    cls(obj)
    obj.AutoLabel = util.set_label(obj, cls.LABELS[0])
    part_mod.insert_feature(part, obj)
    if items:
        refs.set_ref(obj, "Items", obj.BaseFeature, items)
    if App.GuiUp:
        from ..gui import viewproviders
        viewproviders.attach_feature(obj)
    return obj


def create_offset_surface(doc, part, items=None):
    return _create(OffsetSurfaceProxy, doc, part, "OffsetSurface", items)


def create_move_face(doc, part, items=None):
    return _create(MoveFaceProxy, doc, part, "MoveFace", items)


class SplitLineProxy(feature.FeatureProxy):
    TYPE = "SplitLine"
    LABELS = ("Split Line",)

    def setup(self, obj):
        super(SplitLineProxy, self).setup(obj)
        a = util.add_prop
        g = "Split Line"
        a(obj, "App::PropertyEnumeration", "SplitType", g, "Silhouette, Projection or "
          "Intersection", enum=core_split.TYPES)
        a(obj, "App::PropertyLinkSub", "Items", g, "Faces to split")
        a(obj, "App::PropertyLink", "Sketch", g, "Projection: the sketch to project")
        a(obj, "App::PropertyBool", "SingleDirection", g, "Projection: project one way only",
          False)
        a(obj, "App::PropertyBool", "Reverse", g, "The other way", False)
        a(obj, "App::PropertyLinkSubList", "Tools", g,
          "Intersection: the planes, faces or bodies that split")
        a(obj, "App::PropertyLinkSub", "PullDirection", g,
          "Silhouette: direction of pull (a plane, face or edge)")

    def compute(self, obj, base):
        warns = []
        p = core_split.Params()
        p.kind = obj.SplitType
        p.faces, w = refs.get_refs(obj, "Items", "face to split", obj.BaseFeature)
        warns.extend(w)
        if p.kind == core_split.PROJECTION and obj.Sketch is not None:
            from ..core import regions
            p.sketch = topo.shape_of(obj.Sketch)
            p.normal = regions.sketch_normal(obj.Sketch)
        p.single = obj.SingleDirection
        p.reverse = obj.Reverse
        if p.kind == core_split.INTERSECTION:
            for o, subs in obj.Tools:
                if o is None:
                    continue
                subs = [s for s in (subs if isinstance(subs, (list, tuple)) else [subs]) if s]
                if subs:
                    p.tools.extend(topo.shape_of(o, s) for s in subs)
                else:
                    p.tools.append(topo.shape_of(o))
        if p.kind == core_split.SILHOUETTE:
            s, w = refs.get_ref(obj, "PullDirection", "direction of pull", obj.BaseFeature)
            warns.append(w)
            if s is not None:
                p.direction = core_ref.direction_of(s, "direction of pull")
        p.feature = obj.Name
        p.tag = obj.ID
        res, preview = core_split.compute(p, base)
        res.warnings.extend(x for x in warns if x)
        return res, preview


def create_split_line(doc, part, items=None, sketch=None):
    obj = _create(SplitLineProxy, doc, part, "SplitLine", items)
    obj.SplitType = core_split.PROJECTION
    if sketch is not None:
        obj.Sketch = sketch
        part_mod.add_to_part(part, sketch) if sketch not in part.Group else None
    return obj
