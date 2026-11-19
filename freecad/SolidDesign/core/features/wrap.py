# SPDX-License-Identifier: LGPL-2.1-or-later
"""Wrap (SolidWorks' Insert > Features > Wrap): a sketch wrapped onto a face.

Emboss raises it, Deboss sinks it, Scribe only splits the face along it.

On a cylinder the sketch is rolled round it without stretching (the
Analytical method): a cylinder unrolls flat, so the sketch's two directions
become the angle round the axis (arc length) and the height along it. The
sketch's plane must run along the axis; it is rolled from the line where the
plane is nearest the axis. On a flat face the sketch is projected straight onto
it.
"""

import math

import FreeCAD as App
import Part

from .. import topo
from . import common

EMBOSS, DEBOSS, SCRIBE = "Emboss", "Deboss", "Scribe"
TYPES = [EMBOSS, DEBOSS, SCRIBE]
V2 = App.Base.Vector2d


class Params(object):
    def __init__(self):
        self.feature = "Wrap"
        self.tag = 1
        self.alloc = None
        self.faces = []             # the sketch's region faces (with holes)
        self.wires = []             # its open curves (Scribe only)
        self.plane = None           # (origin, normal) of the sketch plane
        self.target = None          # the face to wrap onto
        self.kind = EMBOSS
        self.depth = 1.0
        self.reverse = False


class _Roll(object):
    """Maps points of the sketch plane to the cylinder's (u, v) parameters."""

    def __init__(self, surf, plane_origin, plane_normal):
        self.s = surf
        a = App.Vector(surf.Axis).normalize()
        n = App.Vector(plane_normal).normalize()
        if abs(n.dot(a)) > 1e-6:
            raise topo.GeometryError("The sketch's plane must run along the cylinder's axis "
                                     "(parallel to it) to wrap.")
        c = App.Vector(surf.Center)
        # The foot of the axis on the plane: where the roll starts.
        d = (plane_origin - c).dot(n)
        self.foot = c + n * d
        self.radial = n if d >= 0 else -n           # from the axis towards the plane
        self.axis = a
        self.side = a.cross(self.radial)            # along the plane, square to the axis
        self.r = surf.Radius
        u0, _v0 = surf.parameter(c + self.radial * self.r)
        self.u0 = u0
        # Which way u turns: u grows towards +side?
        u1, _ = surf.parameter(c + (self.radial * math.cos(0.1) + self.side * math.sin(0.1))
                               * self.r)
        du = (u1 - u0 + math.pi) % (2 * math.pi) - math.pi
        self.sign = 1.0 if du > 0 else -1.0
        self.c = c

    def uv(self, p):
        rel = p - self.foot
        s = rel.dot(self.side)
        t = rel.dot(self.axis)
        _u, v0 = self.s.parameter(self.c)
        return self.u0 + self.sign * s / self.r, v0 + t

    def edge2d(self, e):
        """The edge as a 2D curve in (u, v)."""
        if e.Curve.TypeId == "Part::GeomLine":
            a = self.uv(e.valueAt(e.FirstParameter))
            b = self.uv(e.valueAt(e.LastParameter))
            return Part.Geom2d.Line2dSegment(V2(*a), V2(*b))
        n = max(16, int(e.Length / max(self.r * 0.05, 0.2)))
        n = min(n, 200)
        pts = [V2(*self.uv(e.valueAt(e.FirstParameter + (e.LastParameter - e.FirstParameter)
                                     * k / float(n)))) for k in range(n + 1)]
        closed = e.isClosed()
        bs = Part.Geom2d.BSplineCurve2d()
        if closed:
            bs.interpolate(pts[:-1], PeriodicFlag=True)
        else:
            bs.interpolate(pts)
        return bs

    def wire(self, w, surf):
        edges = []
        for e in w.OrderedEdges:
            c2 = self.edge2d(e)
            edges.append(c2.toShape(surf))
        return Part.Wire(edges)


def _cyl_like(surf, r):
    """The same cylinder (same axis and seam), radius r."""
    out = surf.copy()
    out.Radius = r
    return out


def _face_on(surf, roll, face):
    outer = roll.wire(face.OuterWire, surf)
    f = Part.Face(surf, outer)
    holes = [roll.wire(w, surf) for w in face.Wires if not w.isSame(face.OuterWire)]
    if holes:
        f = f.cutHoles(holes) if hasattr(f, "cutHoles") else f
    return f


def _raised(roll, surf, face, r2):
    """The solid between the wrapped region on the cylinder and on radius r2."""
    other = _cyl_like(surf, r2)
    f1 = _face_on(surf, roll, face)
    f2 = _face_on(other, roll, face)
    walls = []
    for w in face.Wires:
        w1 = roll.wire(w, surf)
        w2 = roll.wire(w, other)
        for a, b in zip(w1.OrderedEdges, w2.OrderedEdges):
            walls.extend(Part.makeRuledSurface(a, b).Faces)
    sh = Part.Shell([f1, f2] + walls)
    sh.sewShape()
    shells = sh.Shells if sh.ShapeType != "Shell" else [sh]
    if len(shells) != 1 or not shells[0].isClosed():
        raise topo.GeometryError("The wrapped sketch didn't close into a solid. Its contours "
                                 "must not cross each other or go more than once round.")
    s = Part.Solid(shells[0])
    if s.Volume < 0:
        s.reverse()
    return s


def compute(p, base, body_id):
    t = p.target
    if t is None:
        raise topo.GeometryError("Pick the face to wrap onto.")
    if not p.faces and not (p.kind == SCRIBE and p.wires):
        raise topo.GeometryError("The sketch needs closed contours to wrap.")
    if p.kind != SCRIBE and p.depth <= 0:
        raise topo.GeometryError("The depth must be greater than zero.")
    body = base.get(body_id)
    stype = t.Surface.TypeId
    tools = []
    curves = []
    if stype == "Part::GeomCylinder":
        surf = t.Surface
        roll = _Roll(surf, p.plane[0], p.plane[1])
        u0, u1, v0, v1 = t.ParameterRange
        q = t.valueAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))
        rel = q - App.Vector(surf.Center)
        ax = App.Vector(surf.Axis).normalize()
        radial = (rel - ax * rel.dot(ax)).normalize()
        eps = max(surf.Radius * 1e-4, 1e-5)
        outward = not body.shape.isInside(q + radial * eps, 1e-7, False)   # a shaft
        r = surf.Radius
        up = (p.kind == EMBOSS) != p.reverse
        r2 = r + p.depth if up == outward else r - p.depth
        if r2 <= 0:
            raise topo.GeometryError("The depth goes past the cylinder's axis.")
        for f in p.faces:
            if p.kind == SCRIBE:
                for w in f.Wires:
                    curves.append(roll.wire(w, surf))
            else:
                tools.append(_raised(roll, surf, f, r2))
        for w in p.wires:
            curves.append(roll.wire(w, surf))
    elif stype == "Part::GeomPlane":
        n = t.normalAt(0, 0)
        if body.shape.isInside(t.CenterOfMass + n * 1e-4, 1e-7, False):
            n = -n
        pn = App.Vector(p.plane[1]).normalize()
        if abs(abs(pn.dot(n)) - 1) > 1e-6:
            raise topo.GeometryError("To wrap onto a flat face, sketch on a plane parallel "
                                     "to it.")
        shift = n * (t.CenterOfMass - p.plane[0]).dot(n)
        up = (p.kind == EMBOSS) != p.reverse
        for f in p.faces:
            g = f.copy()
            g.translate(shift)
            if p.kind == SCRIBE:
                curves.extend(g.Wires)
            else:
                tools.append(g.extrude(n * (p.depth if up else -p.depth)))
        for w in p.wires:
            g = w.copy()
            g.translate(shift)
            curves.append(g)
    else:
        raise topo.GeometryError("Wrap works on cylindrical and flat faces in this version.")
    scope = common.Scope(False, [body_id])
    if p.kind == SCRIBE:
        edges = [e for w in curves for e in w.Edges]
        if not edges:
            raise topo.GeometryError("Nothing to scribe.")
        try:
            split = body.shape.generalFuse(edges)[0]
        except Exception as e:
            raise topo.GeometryError("The scribe couldn't split the face: {}".format(
                topo._msg(e)))
        if body.kind == "solid":
            if len(split.Solids) != 1:
                raise topo.GeometryError("The scribe couldn't split the face.")
            new = split.Solids[0]
        else:
            new = split.Shells[0] if len(split.Shells) == 1 else Part.makeCompound(
                split.Shells or split.Faces)
        out = base.copy()
        out.replace(body_id, topo.tagged(new, p.tag), p.feature)
        res = common.Result(out)
        res.touched.append(body_id)
        return res, topo.compound([Part.makeCompound(edges)], p.tag)
    if not tools:
        raise topo.GeometryError("The sketch has no closed contours to wrap.")
    tool = topo.tagged(tools[0] if len(tools) == 1 else Part.makeCompound(tools), p.tag)
    if up:
        res = common.apply_add(base, tool, p.feature, p.tag, True, scope, p.alloc)
    else:
        res = common.apply_cut(base, tool, p.feature, p.tag, scope, common.Keep(), p.alloc)
        if not res.touched:
            raise topo.GeometryError("The deboss doesn't reach the body.")
    return res, tool

