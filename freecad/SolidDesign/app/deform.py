# SPDX-License-Identifier: LGPL-2.1-or-later
"""Scale, Flex, Indent and Deform (document objects)."""

import math

import FreeCAD as App
import Part

from ..core import topo
from ..core.features import deform as core
from . import refs, util
from .surfaces import _SurfaceTool, _create

__all__ = ["create_scale", "create_flex", "create_indent", "create_deform", "create_freeform"]


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


class IndentProxy(_SurfaceTool):
    """SolidWorks' Indent: the target takes the tool's shape, with a wall round the
    tool's regions that are kept."""
    TYPE = "Indent"
    LABELS = ("Indent",)

    def setup(self, obj):
        super(IndentProxy, self).setup(obj)
        a = util.add_prop
        g = "Indent"
        a(obj, "App::PropertyString", "TargetBody", g, "The body to indent, by ID", "")
        a(obj, "App::PropertyString", "ToolBody", g, "The body pressed in, by ID", "")
        a(obj, "App::PropertyStringList", "ExcludedPoints", g,
          "A point inside each tool region not kept (x,y,z)")
        a(obj, "App::PropertyLength", "Thickness", g, "Wall thickness round the tool", 1.0)
        a(obj, "App::PropertyLength", "Clearance", g, "Gap between the tool and the wall", 0.0)
        a(obj, "App::PropertyBool", "Cut", g, "Only cut the target (no wall)", False)

    def params(self, obj, base):
        from ..core.features import indent as core_i
        from .surfaces import _vec
        q = super(IndentProxy, self).params(obj, base)
        p = core_i.Params()
        p.feature, p.tag, p.alloc = q.feature, q.tag, q.alloc
        p.target = obj.TargetBody
        p.tool = obj.ToolBody
        p.excluded = [v for v in (_vec(t) for t in obj.ExcludedPoints) if v is not None]
        p.thickness = obj.Thickness.Value
        p.clearance = obj.Clearance.Value
        p.cut = obj.Cut
        return p

    def compute(self, obj, base):
        from ..core.features import indent as core_i
        p = self.params(obj, base)
        self.regions = []       # for the panel: (point inside, volume, solid)
        try:
            for r in core_i.regions(p, base):
                self.regions.append((core_i.inner_point(r), r.Volume, r))
        except topo.GeometryError:
            pass
        res, preview = core_i.compute(p, base)
        self.done(obj, p, res)
        return res, preview


def create_indent(doc, part, **props):
    return _create(IndentProxy, doc, part, "Indent", **props)


def _direction(obj, prop, what, base_feature, warns):
    v = getattr(obj, prop)
    if not v or v[0] is None:
        return None
    s, w = refs.get_ref(obj, prop, what, base_feature)
    if w:
        warns.append(w)
    if s is None:
        return None
    from .pattern import direction_of
    return App.Vector(direction_of(s, what)[1]).normalize()


def _normal_at(base, point):
    """The normal of the body face nearest ``point`` (outwards)."""
    best = None
    for b in base:
        for f in b.shape.Faces:
            d = f.distToShape(Part.Vertex(point))[0]
            if best is None or d < best[0]:
                best = (d, f)
    if best is None:
        return None
    f = best[1]
    try:
        u, v = f.Surface.parameter(point)
        return f.normalAt(u, v)
    except Exception:
        return None


class DeformProxy(_SurfaceTool):
    """SolidWorks' Deform: Point, Curve to curve, Surface push."""
    TYPE = "Deform"
    LABELS = ("Deform",)

    def setup(self, obj):
        super(DeformProxy, self).setup(obj)
        from ..core.features import morph
        a = util.add_prop
        g = "Deform"
        a(obj, "App::PropertyEnumeration", "DeformType", g,
          "Point: push a point. Curve to curve: move curves onto others. Surface push: a "
          "tool body pushes in", enum=morph.DEFORM_TYPES)
        a(obj, "App::PropertyStringList", "Bodies", g,
          "Bodies to deform (empty: every body the change reaches)")
        a(obj, "App::PropertyVector", "DeformPoint", g, "Point: where the push is")
        a(obj, "App::PropertyLinkSub", "DeformDirection", g,
          "Point: the direction (an edge, axis or plane); empty: square to the face")
        a(obj, "App::PropertyLength", "Distance", g, "Point: how far the point moves", 5.0)
        a(obj, "App::PropertyBool", "ReverseDirection", g, "The other way", False)
        a(obj, "App::PropertyLength", "Radius", g, "Deform region radius", 20.0)
        a(obj, "App::PropertyEnumeration", "Stiffness", g,
          "Minimum spreads the change widely, Maximum keeps it close", enum=morph.STIFFNESS,
          default=morph.MEDIUM)
        a(obj, "App::PropertyLinkList", "InitialCurves", g,
          "Curve to curve: the curves that move (sketches or curves)")
        a(obj, "App::PropertyLinkList", "TargetCurves", g,
          "Curve to curve: where they move to, in the same order")
        a(obj, "App::PropertyLinkList", "FixedCurves", g,
          "Curve to curve: curves that stay put")
        a(obj, "App::PropertyString", "ToolBody", g, "Surface push: the tool body, by ID", "")
        a(obj, "App::PropertyLinkSub", "PushDirection", g,
          "Surface push: the direction (an edge, axis or plane)")
        a(obj, "App::PropertyLength", "DeformDeviation", g,
          "Surface push: how far round the tool the dent spreads (0: the tool's own shape)",
          0.0)

    def compute(self, obj, base):
        from ..core.features import morph
        warns = []
        q = self.params(obj, base)
        p = morph.DeformParams()
        p.feature, p.tag, p.alloc = q.feature, q.tag, q.alloc
        p.kind = obj.DeformType
        p.bodies = [i for i in obj.Bodies if i]
        p.radius = obj.Radius.Value
        p.stiffness = obj.Stiffness
        sign = -1.0 if obj.ReverseDirection else 1.0
        if p.kind == morph.POINT:
            p.point = App.Vector(obj.DeformPoint)
            d = _direction(obj, "DeformDirection", "deform direction", obj.BaseFeature, warns)
            if d is None:
                d = _normal_at(base, p.point)
            p.direction = d * sign if d is not None else None
            p.distance = obj.Distance.Value
        elif p.kind == morph.CURVE_TO_CURVE:
            p.initial = [topo.shape_of(o) for o in obj.InitialCurves if o is not None]
            p.target = [topo.shape_of(o) for o in obj.TargetCurves if o is not None]
            p.fixed = [topo.shape_of(o) for o in getattr(obj, "FixedCurves", []) if o is not None]
        else:
            p.tool_id = obj.ToolBody
            b = base.get(obj.ToolBody) if obj.ToolBody else None
            if obj.ToolBody and b is None:
                raise topo.GeometryError("The tool body no longer exists. Pick it again.")
            p.tool = b.shape if b is not None else None
            d = _direction(obj, "PushDirection", "push direction", obj.BaseFeature, warns)
            if d is None and p.tool is not None:
                # Towards the bodies it pushes into.
                others = [x.shape for x in base if x.id != obj.ToolBody]
                if others:
                    d = Part.makeCompound(others).BoundBox.Center - p.tool.CenterOfMass
                    d = d.normalize() if d.Length > 1e-12 else None
            p.push = d * sign if d is not None else None
            p.deviation = getattr(obj, "DeformDeviation", App.Units.Quantity(0)).Value
        res, preview = morph.deform(p, base)
        self.done(obj, p, res, warns)
        return res, preview


class FreeformProxy(_SurfaceTool):
    """SolidWorks' Freeform: one face pushed in or out at control points."""
    TYPE = "Freeform"
    LABELS = ("Freeform",)

    def setup(self, obj):
        super(FreeformProxy, self).setup(obj)
        from ..core.features import morph
        a = util.add_prop
        g = "Freeform"
        a(obj, "App::PropertyLinkSub", "Items", g, "The face to change")
        a(obj, "App::PropertyStringList", "ControlPoints", g,
          "Points on the face and how far each moves: x,y,z|height[|dx,dy,dz sideways]")
        a(obj, "App::PropertyLinkList", "ControlCurves", g,
          "Curves (sketches) the face is pulled onto")
        a(obj, "App::PropertyEnumeration", "Continuity", g,
          "How the change meets the face's edges", enum=morph.CONTINUITY,
          default=morph.TANGENT)
        a(obj, "App::PropertyPercent", "Reach", g,
          "How far each point's change spreads, as a share of the face's size", 50)

    @staticmethod
    def moves(obj):
        """[(point, height, sideways vector)] from ControlPoints."""
        out = []
        for t in obj.ControlPoints:
            try:
                bits = str(t).split("|")
                x, y, z = (float(c) for c in bits[0].split(","))
                side = App.Vector()
                if len(bits) > 2 and bits[2].strip():
                    side = App.Vector(*(float(c) for c in bits[2].split(",")))
                out.append((App.Vector(x, y, z), float(bits[1]), side))
            except (ValueError, IndexError, TypeError):
                continue
        return out

    @classmethod
    def points(cls, obj):
        """[(point, height)]: the normal part only."""
        return [(c, h) for c, h, _s in cls.moves(obj)]

    @staticmethod
    def point_text(pt, h, side=None):
        t = "{:.6g},{:.6g},{:.6g}|{:.6g}".format(pt.x, pt.y, pt.z, h)
        if side is not None and side.Length > 1e-12:
            t += "|{:.6g},{:.6g},{:.6g}".format(side.x, side.y, side.z)
        return t

    def compute(self, obj, base):
        from ..core.features import morph
        from ..core.features.edges import faces_by_body
        warns = []
        q = self.params(obj, base)
        p = morph.FreeformParams()
        p.feature, p.tag, p.alloc = q.feature, q.tag, q.alloc
        faces, w = refs.get_refs(obj, "Items", "face to freeform", obj.BaseFeature)
        warns.extend(w)
        faces = [f for f in faces if f.ShapeType == "Face"]
        if len(faces) != 1:
            raise topo.GeometryError("Pick one face to freeform.")
        (bid, fs), = faces_by_body(base, faces).items()
        p.body, p.face = bid, fs[0]
        p.points = self.moves(obj)
        p.curves = [topo.shape_of(o) for o in getattr(obj, "ControlCurves", []) if o is not None]
        p.continuity = obj.Continuity
        p.reach = obj.Reach / 100.0
        res, preview = morph.freeform(p, base)
        self.done(obj, p, res, warns)
        return res, preview


def create_deform(doc, part, **props):
    return _create(DeformProxy, doc, part, "Deform", **props)


def create_freeform(doc, part, **props):
    return _create(FreeformProxy, doc, part, "Freeform", **props)


class FlattenProxy(_SurfaceTool):
    """SolidWorks' Surface Flatten: faces laid out flat as a new surface body."""
    TYPE = "Flatten"
    LABELS = ("Surface-Flatten",)

    def setup(self, obj):
        super(FlattenProxy, self).setup(obj)
        a = util.add_prop
        g = "Flatten"
        a(obj, "App::PropertyLinkSub", "Items", g, "The faces to flatten (connected)")
        a(obj, "App::PropertyLinkSub", "FlattenFrom", g,
          "A vertex (or an edge's middle) where the flat shape touches the faces")
        a(obj, "App::PropertyPercent", "Accuracy", g, "Finer is truer and slower", 50)
        a(obj, "App::PropertyLinkSub", "TearEdges", g,
          "Edges to cut the faces open along (relief cuts); a closed set needs them")

    def compute(self, obj, base):
        from ..core.features import flatten as core_f
        warns = []
        q = self.params(obj, base)
        p = core_f.Params()
        p.feature, p.tag, p.alloc = q.feature, q.tag, q.alloc
        faces, w = refs.get_refs(obj, "Items", "face to flatten", obj.BaseFeature)
        warns.extend(w)
        p.faces = [f for f in faces if f.ShapeType == "Face"]
        v = obj.FlattenFrom
        if v and v[0] is not None:
            s, w = refs.get_ref(obj, "FlattenFrom", "point to flatten from", obj.BaseFeature)
            if w:
                warns.append(w)
            if s is not None and s.ShapeType == "Vertex":
                p.anchor = s.Point
            elif s is not None and s.Edges:
                e = s.Edges[0]
                p.anchor = e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))
        p.accuracy = obj.Accuracy / 100.0
        t = getattr(obj, "TearEdges", None)
        if t and t[0] is not None:
            edges, w = refs.get_refs(obj, "TearEdges", "tear edge", obj.BaseFeature)
            warns.extend(w)
            p.tears = [e for e in edges if e.ShapeType == "Edge"]
        res, preview = core_f.compute(p, base)
        self.done(obj, p, res, warns)
        return res, preview


def create_flatten(doc, part, **props):
    return _create(FlattenProxy, doc, part, "Flatten", **props)
