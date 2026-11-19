# SPDX-License-Identifier: LGPL-2.1-or-later
"""Intersect, Dome and Wrap (document objects)."""

import FreeCAD as App

from ..core import regions, topo
from ..core.features import dome as core_dome
from ..core.features import intersect as core_int
from ..core.features import wrap as core_wrap
from ..core.features.edges import faces_by_body
from . import refs, util
from .surfaces import _SurfaceTool, _create, _vec, vec_text

__all__ = ["create_intersect", "create_dome", "create_wrap", "vec_text"]


class IntersectProxy(_SurfaceTool):
    TYPE = "Intersect"
    LABELS = ("Intersect",)

    def setup(self, obj):
        super(IntersectProxy, self).setup(obj)
        a = util.add_prop
        g = "Selections"
        a(obj, "App::PropertyStringList", "Bodies", g, "Solids and surfaces to intersect, by ID")
        a(obj, "App::PropertyLinkList", "Planes", g, "Planes to intersect with")
        a(obj, "App::PropertyEnumeration", "IntersectMode", g,
          "Intersecting regions: inside the solids. Internal regions: hollows closed off "
          "by the selections", enum=core_int.MODES)
        a(obj, "App::PropertyBool", "CapPlanarOpenings", g,
          "Close the surfaces' flat openings", False)
        g = "Regions"
        a(obj, "App::PropertyStringList", "ExcludedPoints", g,
          "A point inside each excluded region (x,y,z)")
        g = "Options"
        a(obj, "App::PropertyBool", "MergeResult", g, "Merge the kept regions where they touch",
          True)
        a(obj, "App::PropertyBool", "ConsumeSurfaces", g, "The surfaces are used up", True)

    def params(self, obj, base):
        p = core_int.Params()
        q = super(IntersectProxy, self).params(obj, base)
        p.feature, p.tag, p.alloc = q.feature, q.tag, q.alloc
        p.bodies = [i for i in obj.Bodies if i]
        p.planes = []
        for o in obj.Planes:
            if o is None:
                continue
            from ..core import refgeom as core_ref
            shape = topo.shape_of(o)
            core_ref.plane_of(shape, "plane")
            p.planes.append(shape.Faces[0])
        p.mode = obj.IntersectMode
        p.cap = obj.CapPlanarOpenings
        p.excluded = [v for v in (_vec(t) for t in obj.ExcludedPoints) if v is not None]
        p.merge = obj.MergeResult
        p.consume = obj.ConsumeSurfaces
        return p

    def regions(self, obj, base):
        """For the panel: [(solid, kind)] of the regions it could keep."""
        p = self.params(obj, base)
        return [(r, k) for r, k, _i in core_int.wanted(p, core_int.regions(p, base))]

    def compute(self, obj, base):
        p = self.params(obj, base)
        # For the panel's region list: every region it could keep, before exclusion.
        self.regions = []
        try:
            for r, kind, _i in core_int.wanted(p, core_int.regions(p, base)):
                self.regions.append((core_int.inner_point(r), r.Volume, kind, r))
        except topo.GeometryError:
            pass
        res, preview = core_int.compute(p, base)
        self.done(obj, p, res)
        return res, preview


class DomeProxy(_SurfaceTool):
    TYPE = "Dome"
    LABELS = ("Dome",)

    def setup(self, obj):
        super(DomeProxy, self).setup(obj)
        a = util.add_prop
        g = "Dome"
        a(obj, "App::PropertyLinkSub", "Items", g, "Flat faces to dome")
        a(obj, "App::PropertyLength", "Distance", g, "The dome's height", 5.0)
        a(obj, "App::PropertyBool", "ReverseDirection", g, "A dent instead of a dome", False)
        a(obj, "App::PropertyBool", "EllipticalDome", g,
          "Half an ellipsoid (round faces) or square to the face at its edge", False)

    def compute(self, obj, base):
        warns = []
        p = core_dome.Params()
        q = self.params(obj, base)
        p.feature, p.tag, p.alloc = q.feature, q.tag, q.alloc
        p.faces, w = refs.get_refs(obj, "Items", "face to dome", obj.BaseFeature)
        warns.extend(w)
        p.height = obj.Distance.Value
        p.reverse = obj.ReverseDirection
        p.elliptical = obj.EllipticalDome
        res, preview = core_dome.compute(p, base)
        self.done(obj, p, res, warns)
        return res, preview


class WrapProxy(_SurfaceTool):
    TYPE = "Wrap"
    LABELS = ("Wrap",)

    def setup(self, obj):
        super(WrapProxy, self).setup(obj)
        a = util.add_prop
        g = "Wrap"
        a(obj, "App::PropertyEnumeration", "WrapType", g,
          "Emboss raises the sketch, Deboss sinks it, Scribe splits the face along it",
          enum=core_wrap.TYPES)
        a(obj, "App::PropertyLink", "Sketch", g, "The sketch to wrap")
        a(obj, "App::PropertyLinkSub", "Items", g, "The face to wrap onto")
        a(obj, "App::PropertyLength", "Depth", g, "How far it stands up or sinks in", 1.0)
        a(obj, "App::PropertyBool", "ReverseDirection", g, "The other way", False)

    def compute(self, obj, base):
        warns = []
        p = core_wrap.Params()
        q = self.params(obj, base)
        p.feature, p.tag, p.alloc = q.feature, q.tag, q.alloc
        sk = obj.Sketch
        if sk is None:
            raise topo.GeometryError("Pick the sketch to wrap.")
        faces, open_wires = regions.default_profile(sk, obj.ID) if \
            topo.shape_of(sk).Edges else (None, [])
        p.faces = list(faces.Faces) if faces is not None else []
        p.wires = list(open_wires or [])
        if p.wires and obj.WrapType != core_wrap.SCRIBE:
            warns.append("Open curves in the sketch are only used by Scribe.")
        pl = regions.sketch_placement(sk)
        p.plane = (pl.Base, regions.sketch_normal(sk))
        faces_t, w = refs.get_refs(obj, "Items", "face to wrap onto", obj.BaseFeature)
        warns.extend(w)
        if not faces_t:
            raise topo.GeometryError("Pick the face to wrap onto.")
        groups = faces_by_body(base, faces_t[:1])
        bid, fs = next(iter(groups.items()))
        p.target = fs[0]
        p.kind = obj.WrapType
        p.depth = obj.Depth.Value
        p.reverse = obj.ReverseDirection
        res, preview = core_wrap.compute(p, base, bid)
        self.done(obj, p, res, warns)
        return res, preview


def create_intersect(doc, part, **props):
    return _create(IntersectProxy, doc, part, "Intersect", **props)


def create_dome(doc, part, **props):
    return _create(DomeProxy, doc, part, "Dome", **props)


def create_wrap(doc, part, **props):
    sk = props.get("Sketch")
    obj = _create(WrapProxy, doc, part, "Wrap", **props)
    if sk is not None and App.GuiUp:
        sk.ViewObject.Visibility = False
    return obj
