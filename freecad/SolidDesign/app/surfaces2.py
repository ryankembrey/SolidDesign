# SPDX-License-Identifier: LGPL-2.1-or-later
"""Ruled, Radiate, Untrim and Mid-Surface surfaces; Replace Face; Cut With
Surface (document objects)."""

import Part

from ..core import refgeom as core_ref
from ..core import topo
from ..core.features import common
from ..core.features import surfaces2 as core
from . import refs, util
from .surfaces import _SurfaceTool, _create

__all__ = ["create_ruled", "create_radiate", "create_untrim", "create_mid_surface",
           "create_replace_face", "create_cut_with_surface"]


class _Tool2(_SurfaceTool):
    def p2(self, obj, base):
        q = self.params(obj, base)
        p = core.Params()
        p.feature, p.tag, p.alloc = q.feature, q.tag, q.alloc
        self._p = q
        return p

    def done2(self, obj, res, warns=()):
        self.done(obj, self._p, res, warns)

    def elems(self, obj, prop, what, warns):
        val = getattr(obj, prop)
        if not val or val[0] is None:
            return []
        shapes, w = refs.get_refs(obj, prop, what, obj.BaseFeature)
        warns.extend(w)
        return shapes

    def vector(self, obj, prop, what, warns):
        val = getattr(obj, prop)
        if not val or val[0] is None:
            return None
        s, w = refs.get_ref(obj, prop, what, obj.BaseFeature)
        if w:
            warns.append(w)
        if s is None:
            return None
        from .pattern import direction_of
        return direction_of(s, what)[1]

    def surface_body(self, base, bid, what):
        if not bid:
            return None
        b = base.get(bid)
        if b is None:
            raise topo.GeometryError("The {} no longer exists. Pick it again.".format(what))
        return b


class RuledProxy(_Tool2):
    TYPE = "Ruled"
    LABELS = ("Ruled Surface",)

    def setup(self, obj):
        super(RuledProxy, self).setup(obj)
        a = util.add_prop
        g = "Ruled Surface"
        a(obj, "App::PropertyEnumeration", "RuledType", g, "How the strips stand off the edges",
          enum=core.RULED_TYPES)
        a(obj, "App::PropertyLinkSub", "Items", g, "Edges to rule from")
        a(obj, "App::PropertyLength", "Distance", g, "How far the strips reach", 10.0)
        a(obj, "App::PropertyLinkSub", "ReferenceVector", g,
          "Tapered / Perpendicular to Vector: an edge, axis or plane (its normal)")
        a(obj, "App::PropertyAngle", "Angle", g, "Tapered to Vector: the angle", 10.0)
        a(obj, "App::PropertyBool", "AlternateSide", g, "The other side", False)
        a(obj, "App::PropertyBool", "TrimAndKnit", g,
          "Several edges: cut the strips back where they cross at corners, and knit them",
          True)
        a(obj, "App::PropertyBool", "ConnectingSurface", g,
          "Several edges: fill the gaps between strips at sharp corners", False)
        if list(obj.getEnumerationsOfProperty("RuledType")) != core.RULED_TYPES:
            old = obj.RuledType
            obj.RuledType = core.RULED_TYPES
            obj.RuledType = old

    def compute(self, obj, base):
        warns = []
        p = self.p2(obj, base)
        p.edges = [e for s in self.elems(obj, "Items", "edge", warns) for e in s.Edges]
        p.kind = obj.RuledType
        p.trim_knit = getattr(obj, "TrimAndKnit", False)
        p.connect = getattr(obj, "ConnectingSurface", False)
        p.distance = obj.Distance.Value
        p.angle = obj.Angle.Value
        p.direction = self.vector(obj, "ReferenceVector", "reference vector", warns)
        p.flip = obj.AlternateSide
        res, preview = core.ruled(p, base)
        self.done2(obj, res, warns)
        return res, preview


class RadiateProxy(_Tool2):
    TYPE = "Radiate"
    LABELS = ("Radiate Surface",)

    def setup(self, obj):
        super(RadiateProxy, self).setup(obj)
        a = util.add_prop
        g = "Radiate Surface"
        a(obj, "App::PropertyLinkSub", "ReferencePlane", g, "The plane the surface lies "
          "parallel to")
        a(obj, "App::PropertyLinkSub", "Items", g, "Edges to radiate from")
        a(obj, "App::PropertyLength", "Distance", g, "How far it reaches", 10.0)
        a(obj, "App::PropertyBool", "Reverse", g, "Towards the faces instead", False)
        a(obj, "App::PropertyBool", "PropagateTangent", g,
          "Carry on along the edges meeting the picked ones smoothly", False)

    def compute(self, obj, base):
        warns = []
        p = self.p2(obj, base)
        p.edges = [e for s in self.elems(obj, "Items", "edge", warns) for e in s.Edges]
        p.propagate = getattr(obj, "PropagateTangent", False)
        val = obj.ReferencePlane
        if val and val[0] is not None:
            s, w = refs.get_ref(obj, "ReferencePlane", "reference plane", obj.BaseFeature)
            if w:
                warns.append(w)
            if s is not None:
                p.direction = core_ref.plane_of(s, "reference plane")[1]
        p.distance = obj.Distance.Value
        p.flip = obj.Reverse
        res, preview = core.radiate(p, base)
        self.done2(obj, res, warns)
        return res, preview


class UntrimProxy(_Tool2):
    TYPE = "Untrim"
    LABELS = ("Surface-Untrim",)

    def setup(self, obj):
        super(UntrimProxy, self).setup(obj)
        a = util.add_prop
        g = "Untrim Surface"
        a(obj, "App::PropertyLinkSub", "Items", g, "Faces to untrim")
        a(obj, "App::PropertyEnumeration", "UntrimType", g,
          "Internal edges: fill the holes. All edges: the whole surface, grown. External "
          "edges: grown, holes kept", enum=core.UNTRIM_TYPES)
        a(obj, "App::PropertyPercent", "DistancePercent", g, "How much bigger (All / External)",
          10)

    def compute(self, obj, base):
        warns = []
        p = self.p2(obj, base)
        p.faces = self.elems(obj, "Items", "face", warns)
        p.kind = obj.UntrimType
        p.percent = float(obj.DistancePercent)
        res, preview = core.untrim(p, base)
        self.done2(obj, res, warns)
        return res, preview


class MidSurfaceProxy(_Tool2):
    TYPE = "MidSurface"
    LABELS = ("Surface-MidSurface",)

    def setup(self, obj):
        super(MidSurfaceProxy, self).setup(obj)
        a = util.add_prop
        g = "Mid-Surface"
        a(obj, "App::PropertyStringList", "Bodies", g, "Bodies to find face pairs on, by ID")
        a(obj, "App::PropertyLinkSub", "Items", g, "Or: the faces to pair")
        a(obj, "App::PropertyLength", "Threshold", g,
          "Pairs up to this far apart (0: the thinnest)", 0.0)

    def compute(self, obj, base):
        warns = []
        p = self.p2(obj, base)
        faces = list(self.elems(obj, "Items", "face", warns))
        for bid in obj.Bodies:
            b = base.get(bid)
            if b is not None:
                faces.extend(b.shape.Faces)
        p.faces = faces
        p.threshold = obj.Threshold.Value
        res, preview = core.mid_surface(p, base)
        self.done2(obj, res, warns)
        return res, preview


def _cutter(obj, base, warns, body_prop, plane_prop, what):
    b = obj.Proxy.surface_body(base, getattr(obj, body_prop), what)
    if b is not None:
        if b.kind != "surface":
            raise topo.GeometryError("The {} must be a surface body.".format(what))
        return b.shape, b.id
    val = getattr(obj, plane_prop)
    if val and val[0] is not None:
        s, w = refs.get_ref(obj, plane_prop, what, obj.BaseFeature)
        if w:
            warns.append(w)
        if s is not None:
            o, n, _x = core_ref.plane_of(s, what)
            big = topo.big_length(*[bb.shape for bb in base])
            return Part.Plane(o, n).toShape(-big, big, -big, big), None
    return None, None


class CutWithSurfaceProxy(_Tool2):
    TYPE = "SurfaceCut"
    LABELS = ("SurfaceCut",)

    def setup(self, obj):
        super(CutWithSurfaceProxy, self).setup(obj)
        a = util.add_prop
        g = "Surface Cut"
        a(obj, "App::PropertyString", "CuttingBody", g, "The cutting surface body, by ID", "")
        a(obj, "App::PropertyLinkSub", "CuttingPlane", g, "Or: a plane or flat face")
        a(obj, "App::PropertyBool", "Flip", g, "Keep the other side", False)
        a(obj, "App::PropertyStringList", "Bodies", g, "Bodies to cut (empty: all)")

    def compute(self, obj, base):
        warns = []
        p = self.p2(obj, base)
        p.surface, _sid = _cutter(obj, base, warns, "CuttingBody", "CuttingPlane",
                                  "cutting surface")
        p.flip = obj.Flip
        p.scope = common.Scope(not obj.Bodies, list(obj.Bodies))
        res, preview = core.cut_with_surface(p, base)
        self.done2(obj, res, warns)
        return res, preview


class ReplaceFaceProxy(_Tool2):
    TYPE = "ReplaceFace"
    LABELS = ("Replace Face",)

    def setup(self, obj):
        super(ReplaceFaceProxy, self).setup(obj)
        a = util.add_prop
        g = "Replace Face"
        a(obj, "App::PropertyLinkSub", "Items", g, "Faces to replace")
        a(obj, "App::PropertyString", "ReplacementBody", g,
          "The replacement surface body, by ID", "")
        a(obj, "App::PropertyBool", "ConsumeSurface", g, "Use up the replacement surface",
          True)

    def compute(self, obj, base):
        warns = []
        p = self.p2(obj, base)
        p.faces = self.elems(obj, "Items", "face to replace", warns)
        b = self.surface_body(base, obj.ReplacementBody, "replacement surface")
        if b is None:
            raise topo.GeometryError("Pick the replacement surface body.")
        p.surface = b.shape
        res, preview = core.replace_face(p, base)
        if obj.ConsumeSurface:
            res.bodies.remove(b.id)
        self.done2(obj, res, warns)
        return res, preview


def create_ruled(doc, part, **props):
    return _create(RuledProxy, doc, part, "Ruled", **props)


def create_radiate(doc, part, **props):
    return _create(RadiateProxy, doc, part, "Radiate", **props)


def create_untrim(doc, part, **props):
    return _create(UntrimProxy, doc, part, "Untrim", **props)


def create_mid_surface(doc, part, **props):
    return _create(MidSurfaceProxy, doc, part, "MidSurface", **props)


def create_cut_with_surface(doc, part, **props):
    return _create(CutWithSurfaceProxy, doc, part, "SurfaceCut", **props)


def create_replace_face(doc, part, **props):
    return _create(ReplaceFaceProxy, doc, part, "ReplaceFace", **props)
