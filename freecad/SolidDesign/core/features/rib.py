# SPDX-License-Identifier: LGPL-2.1-or-later
"""Rib (SolidWorks' Rib): a wall of material grown from an open sketch until it
meets the model.

- **Parallel to Sketch:** the rib lies in the sketch plane, from the sketch line
  to the model on the material side, its thickness across the plane.
- **Normal to Sketch:** the rib's thickness lies in the sketch plane, and it
  grows out of the plane to the model.

The ends of the sketch are extended until they meet the model: along their
tangents (SolidWorks' Linear type), or arcs round their circles (Natural). Only
the region the model closes off is kept: a rib that would run off the model is
refused. With Draft, the rib's sides lean so it gets thinner towards the model
(or thicker, Draft outward); the thickness is at the sketch.
"""

import FreeCAD as App
import Part

from .. import topo
from ..bodies import SOLID
from . import common

PARALLEL, NORMAL = "Parallel to Sketch", "Normal to Sketch"
DIRECTIONS = [PARALLEL, NORMAL]
FIRST, BOTH, SECOND = "First Side", "Both Sides", "Second Side"
SIDES = [FIRST, BOTH, SECOND]
LINEAR, NATURAL = "Linear", "Natural"
EXTEND_TYPES = [LINEAR, NATURAL]

TOL = 1e-6


class Params(object):
    def __init__(self):
        self.wires = []             # sketch wires (open or closed), placed
        self.origin = App.Vector()
        self.normal = App.Vector(0, 0, 1)
        self.thickness = 2.0
        self.side = BOTH
        self.direction = PARALLEL
        self.flip = False           # flip the material side
        self.extend = True          # extend the ends to the model
        self.extend_type = LINEAR
        self.draft = False
        self.draft_angle = 1.0
        self.draft_outward = False
        self.feature = "Rib"
        self.tag = 1
        self.scope = None           # common.Scope (all bodies by default)
        self.alloc = None


def compute(p, base):
    if p.thickness <= 0:
        raise topo.GeometryError("The rib thickness must be greater than zero.")
    if not p.wires:
        raise topo.GeometryError("The sketch has no lines to make a rib from.")
    solids = [b.shape for b in base.bodies(SOLID)]
    if not solids:
        raise topo.GeometryError("A rib needs a solid body to grow to.")
    model = Part.makeCompound(solids)
    n = App.Vector(p.normal)
    n.normalize()
    big = topo.big_length(model, *p.wires)
    tools = []
    for w in p.wires:
        tools.extend(_rib(p, w, n, model, big))
    tool = topo.fuse(tools[0], tools[1:], p.tag) if len(tools) > 1 else tools[0]
    tool = topo.refine(tool, p.tag)
    scope = p.scope or common.Scope()
    res = common.apply_add(base, tool, p.feature, p.tag, True, scope, p.alloc)
    return res, tool, tool


def _rib(p, wire, n, model, big):
    w = topo.tagged(wire, p.tag)
    across = _across(w, n)
    ext = _extended(w, model, big, p.extend_type) if p.extend else w
    if p.direction == PARALLEL:
        m = _material(w, across, model, big, p.flip)
        strip = topo.extrude(ext, m * big, p.tag)                   # in the sketch plane
        lo, hi = _span(p.side, p.thickness)
        slab = topo.extrude(strip.translated(n * lo), n * (hi - lo), p.tag)
    else:
        m = _material(w, n, model, big, p.flip)
        band = _band(ext, n, across, p.side, p.thickness, p.tag)
        slab = topo.extrude(band, m * big, p.tag)
    pieces = topo.cut(slab, [model], p.tag)
    keep = []
    for s in pieces.Solids:
        if s.distToShape(w)[0] > 1e-5:
            continue                    # beyond a wall, or past the model
        if _reach(s, w, m) > 0.98 * big:
            raise topo.GeometryError(
                "The rib runs off the model on the material side: nothing closes it off. "
                "Flip the material side, or move the sketch so the model surrounds it.")
        if s.distToShape(model)[0] > 1e-5:
            continue
        keep.append(s)
    if not keep:
        raise topo.GeometryError("The rib doesn't meet the model. Flip the material side, or "
                                 "move the sketch closer to the model.")
    if p.draft:
        # The line and its extensions are separate pieces: join them first, or the
        # faces between them would lean too.
        whole = topo.refine(topo.fuse(keep[0], keep[1:], p.tag), p.tag) if len(keep) > 1 \
            else keep[0]
        keep = [_draft_rib(s, model, m, _midpoint(w), p) for s in whole.Solids]
    return keep


def _draft_rib(piece, model, m, at, p):
    """Lean the rib's sides: thinner towards the model (thicker with Draft outward),
    the thickness kept at the sketch."""
    if not 0 < p.draft_angle < 45:
        raise topo.GeometryError("The rib's draft angle must be more than 0° and less than "
                                 "45°.")
    sides = []
    for i, f in enumerate(piece.Faces, 1):
        try:
            u0, u1, v0, v1 = f.ParameterRange
            n = f.normalAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))
        except Exception:
            continue
        if abs(n.dot(m)) > 1e-6:
            continue                    # the face at the sketch, or a floor
        c = f.CenterOfMass
        if model.isInside(c, 1e-6, True):
            continue                    # against the model (a wall the end meets)
        sides.append(i)
    if not sides:
        return piece
    pull = -m if p.draft_outward else m
    return topo.draft(piece, sides, at, m, pull, p.draft_angle, p.tag)


def _span(side, t):
    """(low, high) offsets of the thickness from the sketch plane or line."""
    if side == FIRST:
        return 0.0, t
    if side == SECOND:
        return -t, 0.0
    return -t / 2.0, t / 2.0


def _across(wire, n):
    """In the sketch plane, square to the wire's chord (the rib's sides)."""
    vs = wire.Vertexes
    if wire.isClosed() or len(vs) < 2:
        raise topo.GeometryError("A rib is made from open sketch lines, not closed profiles.")
    a, b = vs[0].Point, vs[-1].Point
    ends = _ends(wire)
    if ends is not None:
        a, b = ends[0][0], ends[1][0]
    c = b - a
    if c.Length < TOL:
        raise topo.GeometryError("The rib's sketch line has no length.")
    c.normalize()
    d = n.cross(c)
    d.normalize()
    return d


def _ends(wire):
    """[(point, outward tangent)] at the two ends of an open wire, or None."""
    edges = Part.__sortEdges__(wire.Edges) if hasattr(Part, "__sortEdges__") else wire.Edges
    if not edges:
        return None
    pts = [(e.Vertexes[0].Point, e.Vertexes[-1].Point) for e in edges]
    # The ends are the vertices used once.
    count = {}
    for a, b in pts:
        for q in (a, b):
            k = (round(q.x, 6), round(q.y, 6), round(q.z, 6))
            count[k] = count.get(k, 0) + 1
    out = []
    for e in edges:
        for q, at_start in ((e.Vertexes[0].Point, True), (e.Vertexes[-1].Point, False)):
            k = (round(q.x, 6), round(q.y, 6), round(q.z, 6))
            if count.get(k) == 1:
                u = e.FirstParameter if at_start else e.LastParameter
                t = e.tangentAt(u)
                if t.Length < TOL:
                    continue
                t.normalize()
                out.append((q, -t if at_start else t))
    return out if len(out) == 2 else None


def _hit(point, d, model, big):
    """Distance along d from point to the model, or None."""
    seg = Part.LineSegment(point + d * 1e-4, point + d * big).toShape()
    try:
        sec = seg.section(model)
    except Exception:
        return None
    ds = [(v.Point - point).dot(d) for v in sec.Vertexes]
    for e in sec.Edges:
        ds.extend((v.Point - point).dot(d) for v in e.Vertexes)
    ds = [x for x in ds if x > 1e-6]
    return min(ds) if ds else None


def _extended(wire, model, big, how=LINEAR):
    """The wire with its ends carried through the model they meet: along their
    tangents (Linear), or arcs round their circles (Natural). Pieces beyond a wall
    are dropped later, so going past is safe."""
    ends = _ends(wire)
    if ends is None:
        return wire
    edges = list(wire.Edges)
    for q, t in ends:
        if how == NATURAL:
            arc = _natural(wire, q, t, model)
            if arc is not None:
                edges.append(arc)
                continue
        if _hit(q, t, model, big) is not None:
            edges.append(Part.LineSegment(q, q + t * big).toShape())
    if len(edges) == len(wire.Edges):
        return wire
    try:
        return Part.Wire(Part.__sortEdges__(edges))
    except Exception:
        return Part.Compound(edges)


def _material(wire, d, model, big, flip):
    """The side of the sketch line the rib grows to: towards the model (the
    nearer hit from the middle of the line); Flip takes the other side."""
    mid = _midpoint(wire)
    plus, minus = _hit(mid, d, model, big), _hit(mid, -d, model, big)
    if plus is None and minus is None:
        out = App.Vector(d)
    elif minus is None or (plus is not None and plus <= minus):
        out = App.Vector(d)
    else:
        out = -d
    return -out if flip else out


def _midpoint(wire):
    edges = wire.Edges
    e = edges[len(edges) // 2]
    return e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))


def _band(ext, n, across, side, t, tag):
    """The rib's footprint in the sketch plane: the (extended) line thickened."""
    lo, hi = _span(side, t)
    ext = topo.tagged(ext, tag)
    edges = ext.Edges
    straight = all(e.Curve.TypeId in ("Part::GeomLine", "Part::GeomLineSegment") for e in edges)
    if straight and len(edges) == 1:
        return topo.extrude(ext.translated(across * lo), across * (hi - lo), tag)
    # Several edges or curves: offset both sides, then keep the wanted side.
    half = max(abs(lo), abs(hi))
    try:
        both = ext.makeOffset2D(half, 2, True, True, False)
    except Exception as e:
        raise topo.GeometryError("The rib's outline couldn't be thickened: {}".format(e))
    if side == BOTH:
        return both
    cutter = topo.extrude(ext.translated(n * -1.0), n * 2.0, tag)
    from BOPTools import SplitAPI
    parts = SplitAPI.slice(both, [cutter], "Split")
    want = across * (1.0 if side == FIRST else -1.0)
    mid = _midpoint(ext)
    faces = [f for f in parts.Faces if (f.CenterOfMass - mid).dot(want) > 0]
    if not faces:
        raise topo.GeometryError("The rib's outline couldn't be thickened on that side.")
    return Part.makeCompound(faces)


def _reach(solid, wire, m):
    """How far the solid goes from the sketch line along the material direction."""
    base = max((v.Point.dot(m) for v in wire.Vertexes))
    top = max(v.Point.dot(m) for v in solid.Vertexes)
    return top - base


def _natural(wire, q, t, model):
    """An arc end carried on round its circle into the model it meets, or None
    (not an arc, or the circle meets nothing)."""
    end_edge = None
    for e in wire.Edges:
        if any((v.Point - q).Length < 1e-7 for v in e.Vertexes):
            end_edge = e
    if end_edge is None or not hasattr(end_edge.Curve, "Radius"):
        return None
    c = end_edge.Curve
    circle = Part.Circle(App.Vector(c.Center), App.Vector(c.Axis), c.Radius)
    u0 = circle.parameter(q)
    # Which way round the circle is "onwards" from this end.
    sign = 1.0 if circle.tangent(u0)[0].dot(t) > 0 else -1.0
    try:
        hits = Part.Edge(circle).section(model).Vertexes
    except Exception:
        return None
    import math
    best = None
    for v in hits:
        du = (circle.parameter(v.Point) - u0) * sign
        du = du % (2 * math.pi)
        if du > 1e-6 and (best is None or du < best):
            best = du
    if best is None:
        return None
    # A little past the hit, into the wall.
    over = min(best + 0.05, 2 * math.pi - 1e-3)
    a, b = (u0, u0 + over) if sign > 0 else (u0 - over, u0)
    return Part.Edge(circle, a, b)
