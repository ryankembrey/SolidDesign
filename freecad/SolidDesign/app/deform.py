# SPDX-License-Identifier: LGPL-2.1-or-later
"""Scale and Flex (document objects)."""

import math

import FreeCAD as App

from ..core import topo
from ..core.features import deform as core
from . import refs, util
from .surfaces import _SurfaceTool, _create

__all__ = ["create_scale", "create_flex"]


def _ids(obj, base):
    ids = [i for i in obj.Bodies if i]
    return ids or base.ids("solid")


class ScaleProxy(_SurfaceTool):
    TYPE = "Scale"
    LABELS = ("Scale",)

    def setup(self, obj):
        super(ScaleProxy, self).setup(obj)
        a = util.add_prop
        g = "Scale"
        a(obj, "App::PropertyStringList", "Bodies", g, "Bodies to scale (empty: all solids)")
        a(obj, "App::PropertyEnumeration", "ScaleAbout", g, "The point it scales about",
          enum=core.SCALE_ABOUT)
        a(obj, "App::PropertyLink", "CoordinateSystem", g, "Scale about this coordinate system")
        a(obj, "App::PropertyBool", "Uniform", g, "The same factor every way", True)
        a(obj, "App::PropertyFloat", "Factor", g, "Scale factor", 1.0)
        for ax in "XYZ":
            a(obj, "App::PropertyFloat", "Factor" + ax, g, "Scale factor along " + ax, 1.0)

    def compute(self, obj, base):
        p = self.params(obj, base)
        pl = App.Placement()
        if obj.ScaleAbout == core.CSYS:
            cs = obj.CoordinateSystem
            if cs is None:
                raise topo.GeometryError("Pick the coordinate system to scale about.")
            try:
                pl = cs.getGlobalPlacement()
            except Exception:
                pl = cs.Placement
        factors = obj.Factor if obj.Uniform else (obj.FactorX, obj.FactorY, obj.FactorZ)
        res = core.scale(base, _ids(obj, base), obj.ScaleAbout, pl, factors, obj.Name, obj.ID)
        self.done(obj, p, res)
        return res, None


class FlexProxy(_SurfaceTool):
    TYPE = "Flex"
    LABELS = ("Flex",)

    def setup(self, obj):
        super(FlexProxy, self).setup(obj)
        a = util.add_prop
        g = "Flex"
        a(obj, "App::PropertyStringList", "Bodies", g, "Bodies to flex (empty: all solids)")
        a(obj, "App::PropertyEnumeration", "FlexType", g, "Bend, twist, taper or stretch",
          enum=core.FLEX_TYPES)
        a(obj, "App::PropertyAngle", "Angle", g, "Bending / twisting angle", 90.0)
        a(obj, "App::PropertyFloat", "TaperFactor", g, "Tapering: size at the far trim plane",
          0.5)
        a(obj, "App::PropertyDistance", "StretchDistance", g, "Stretching: how much longer",
          10.0)
        g = "Trim Planes"
        a(obj, "App::PropertyLength", "TrimPlane1", g,
          "Where the flexing starts: in from the body's near end", 0.0)
        a(obj, "App::PropertyLength", "TrimPlane2", g,
          "Where it ends: in from the body's far end", 0.0)
        g = "Triad"
        a(obj, "App::PropertyLinkSub", "FlexAxis", g,
          "The flex axis: an edge or axis (none: along the body's longest side)")
        a(obj, "App::PropertyAngle", "TriadRotation", g,
          "Turns the bend's direction round the flex axis", 0.0)
        a(obj, "App::PropertyBool", "ReverseAxis", g, "Flex from the other end", False)

    def frame(self, obj, shape, warns):
        f = core.default_frame(shape)
        val = obj.FlexAxis
        if val and val[0] is not None:
            s, w = refs.get_ref(obj, "FlexAxis", "flex axis", obj.BaseFeature)
            if w:
                warns.append(w)
            if s is not None:
                from .pattern import direction_of
                _p, d = direction_of(s, "flex axis")
                z = App.Vector(d).normalize()
                x = App.Vector(1, 0, 0) if abs(z.x) < 0.9 else App.Vector(0, 1, 0)
                x = (x - z * x.dot(z)).normalize()
                f = App.Placement(f.Base, App.Rotation(x, z.cross(x), z, "ZXY"))
        if obj.ReverseAxis:
            f = f.multiply(App.Placement(App.Vector(), App.Rotation(App.Vector(1, 0, 0), 180)))
        if abs(obj.TriadRotation.Value) > 1e-12:
            f = f.multiply(App.Placement(App.Vector(),
                                         App.Rotation(App.Vector(0, 0, 1),
                                                      obj.TriadRotation.Value)))
        return f

    def compute(self, obj, base):
        warns = []
        p = self.params(obj, base)

        def make(shape):
            f = self.frame(obj, shape, warns)
            lo, hi = core.extent(shape, f)
            a = lo + obj.TrimPlane1.Value
            b = hi - obj.TrimPlane2.Value
            return core.Flex(obj.FlexType, f, a, b, angle=obj.Angle.Value,
                             factor=obj.TaperFactor, stretch=obj.StretchDistance.Value)
        if obj.FlexType == core.TAPERING and obj.TaperFactor <= 0:
            raise topo.GeometryError("The taper factor must be greater than zero.")
        res = core.flex(base, _ids(obj, base), make, obj.Name, obj.ID)
        self.done(obj, p, res, warns)
        return res, None


def create_scale(doc, part, **props):
    return _create(ScaleProxy, doc, part, "Scale", **props)


def create_flex(doc, part, **props):
    return _create(FlexProxy, doc, part, "Flex", **props)
