# SPDX-License-Identifier: LGPL-2.1-or-later
"""More surface tools: Ruled, Radiate, Untrim, Mid-Surface; Replace Face and Cut
With Surface (SolidWorks' Insert > Surface and Insert > Face/Cut).

- **Ruled:** strips standing out from edges: tangent to the face beside them,
  normal to it, perpendicular to a direction, or tapered to it.
- **Radiate:** strips from edges going outward, parallel to a plane.
- **Untrim:** a face back to (part of) the surface it lies on: its holes filled
  (Internal edges), or its whole surface (All edges, with holes kept for
  External edges), grown by a percentage.
- **Mid-Surface:** surfaces midway between pairs of parallel flat faces (a sheet
  part's thickness).
- **Replace Face:** faces of a solid replaced by a surface: the solid grows out to
  the surface, or is trimmed back to it.
- **Cut With Surface:** solids cut by a surface or plane, one side kept.
"""

import FreeCAD as App
import Part

from .. import topo
from ..bodies import SOLID, SURFACE, pieces_of
from . import common
from .surfaces import _body_of_edges, _outward, _sew, _support

V = App.Vector

TANGENT, NORMAL, TAPERED, PERPENDICULAR = ("Tangent to Surface", "Normal to Surface",
                                           "Tapered to Vector", "Perpendicular to Vector")
SWEEP = "Sweep"
RULED_TYPES = [TANGENT, NORMAL, TAPERED, PERPENDICULAR, SWEEP]
ALL_EDGES, INTERNAL, EXTERNAL = "All edges", "Internal edges", "External edges"
UNTRIM_TYPES = [ALL_EDGES, INTERNAL, EXTERNAL]


class Params(object):
    def __init__(self):
        self.feature = "Surface"
        self.tag = 1
        self.alloc = None
        self.edges = []
        self.faces = []
        self.bodies = []
        self.kind = None
        self.distance = 10.0
        self.angle = 0.0
        self.direction = None           # App.Vector
        self.flip = False
        self.percent = 10.0
        self.merge = False
        self.surface = None             # a replacement / cutting surface (shape)
        self.threshold = 0.0            # Mid-Surface: thickest pair (0: any)
        self.trim_knit = False          # Ruled: trim the strips at corners and knit them
        self.connect = False            # Ruled: fill the gaps at sharp corners
        self.propagate = False          # Radiate: carry on along tangent edges
        self.scope = common.Scope()


def _new(p, base, shapes):
    out = base.copy()
    res = common.Result(out)
    ids = p.alloc.take(shapes) if p.alloc is not None else \
        ["{}:{}".format(p.feature, k + 1) for k in range(len(shapes))]
    for i, s in zip(ids, shapes):
        out.add(i, topo.tagged(s, p.tag), p.feature, SURFACE)
        res.created.append(i)
    return res


def _strip(e, dirs):
    """A ruled strip from an edge to its points moved by ``dirs`` (a function)."""
    first, last = e.FirstParameter, e.LastParameter
    n = 24
    far = []
    for k in range(n + 1):
        u = first + (last - first) * k / float(n)
        p = e.valueAt(u)
        far.append(p + dirs(p, u))
    straight = e.Curve.TypeId == "Part::GeomLine"
    if straight and ((far[-1] - far[0]).cross(far[n // 2] - far[0])).Length < 1e-9:
        f = Part.LineSegment(far[0], far[-1]).toShape()
    else:
        bc = Part.BSplineCurve()
        bc.interpolate(far)
        f = bc.toShape()
    return Part.makeRuledSurface(Part.Edge(e.Curve, first, last), f).Faces[0]


def _edge_faces(base, edges):
    """[(edge, the face beside it)]; on a solid, the first face."""
    out = []
    for e in edges:
        body, own = _body_of_edges(base, [e])
        if body is None:
            raise topo.GeometryError("Pick edges of the model.")
        out.append((own[0], _support(body.shape, own[0])))
    return out


def ruled(p, base):
    if not p.edges:
        raise topo.GeometryError("Pick the edges to rule from.")
    if p.distance <= 0:
        raise topo.GeometryError("The distance must be greater than zero.")
    if p.kind in (TAPERED, PERPENDICULAR) and p.direction is None:
        raise topo.GeometryError("Pick the reference vector (an edge, axis or plane).")
    import math
    sign = -1.0 if p.flip else 1.0
    if p.kind == SWEEP:
        shape = _swept_ruled(p, base, sign)
        return _new(p, base, [shape]), shape
    strips = []
    for e, face in _edge_faces(base, p.edges):
        if face is None:
            raise topo.GeometryError("An edge has no face beside it.")

        def dirs(pt, u, e=e, face=face):
            t = V(e.tangentAt(u)).normalize()
            if p.kind == TANGENT:
                o = _outward(face, e, pt)
                if o is None:
                    raise topo.GeometryError("Couldn't find the face's direction at an edge.")
                return o * (sign * p.distance)
            if p.kind == NORMAL:
                uu, vv = face.Surface.parameter(pt)
                return V(face.normalAt(uu, vv)) * (sign * p.distance)
            v = V(p.direction).normalize()
            side = t.cross(v)
            if side.Length < 1e-9:
                raise topo.GeometryError("The edge runs along the reference vector.")
            side.normalize()
            if p.kind == PERPENDICULAR:
                return side * (sign * p.distance)
            a = math.radians(p.angle)
            return (v * math.cos(a) + side * math.sin(a)) * (sign * p.distance)
        strips.append(_strip(e, dirs))
    if p.trim_knit:
        strips = _trim_at_corners(strips, [e for e, _f in _edge_faces(base, p.edges)], p.tag)
    if p.connect:
        strips = strips + _corner_fills(strips, [e for e, _f in _edge_faces(base, p.edges)])
    shape = _sew(strips, 1e-6, p.tag)
    return _new(p, base, [shape]), shape


def _swept_ruled(p, base, sign):
    """Sweep: one smooth ruled surface, a straight line swept along the edges (a
    chain), leaving the first edge tangent to the face beside it and keeping that
    angle to the path as it goes."""
    pairs = _edge_faces(base, p.edges)
    edges = [e for e, _f in pairs]
    try:
        chains = Part.sortEdges(edges)
    except Exception:
        chains = [edges]
    if len(chains) != 1:
        raise topo.GeometryError("Sweep: the edges must be one chain, end to end.")
    path = Part.Wire(chains[0])
    e0 = path.OrderedEdges[0]
    face = next((f for e, f in pairs if e.isSame(e0) or
                 e.distToShape(e0)[0] < 1e-9 and abs(e.Length - e0.Length) < 1e-9), pairs[0][1])
    start = path.OrderedVertexes[0].Point
    u = e0.Curve.parameter(start)
    if p.direction is not None:
        t = V(e0.tangentAt(u)).normalize()
        d = V(p.direction) - t * V(p.direction).dot(t)
        if d.Length < 1e-9:
            raise topo.GeometryError("The reference vector runs along the edge.")
        d.normalize()
    else:
        if face is None:
            raise topo.GeometryError("An edge has no face beside it.")
        d = _outward(face, e0, start)
        if d is None:
            raise topo.GeometryError("Couldn't find the face's direction at the edge.")
    line = Part.Wire([Part.LineSegment(start, start + d * (sign * p.distance)).toShape()])
    try:
        return topo.sweep(path, line, p.tag, False)
    except topo.GeometryError as e:
        raise topo.GeometryError("The ruled sweep failed: {}".format(e))


def _shared(e1, e2, tol=1e-7):
    for a in e1.Vertexes:
        for b in e2.Vertexes:
            if (a.Point - b.Point).Length < tol:
                return a.Point
    return None


def _away(e, c):
    """The edge's direction at its end ``c``, pointing along it away from ``c``."""
    u = e.Curve.parameter(c)
    t = V(e.tangentAt(u))
    mid = e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))
    if t.dot(mid - c) < 0:
        t = -t
    return t.normalize() if t.Length > 1e-12 else t


def _trim_at_corners(strips, edges, tag):
    """Where neighbouring strips run into each other at a corner, cut both back to
    the mitre between them (the plane halving the corner's angle)."""
    out = list(strips)
    for i in range(len(out)):
        for j in range(i + 1, len(out)):
            c = _shared(edges[i], edges[j])
            if c is None:
                continue
            a, b = _away(edges[i], c), _away(edges[j], c)
            n = a - b
            if n.Length < 1e-9:
                continue                    # the edges carry straight on: no corner
            n.normalize()
            size = 4 * (out[i].BoundBox.DiagonalLength + out[j].BoundBox.DiagonalLength)
            mitre = Part.Plane(c, n).toShape(-size, size, -size, size)
            for k in (i, j):
                try:
                    pieces = topo.slice_by(out[k], [mitre], tag).Faces
                except Exception:
                    continue
                if len(pieces) > 1:
                    mid = edges[k].valueAt(0.5 * (edges[k].FirstParameter +
                                                  edges[k].LastParameter))
                    out[k] = min(pieces, key=lambda f: f.distToShape(Part.Vertex(mid))[0])
    return out


def _corner_fills(strips, edges):
    """Faces filling the gap between neighbouring strips at a sharp corner: from the
    corner out to the two strips' far edges."""
    fills = []
    for i in range(len(strips)):
        for j in range(i + 1, len(strips)):
            c = _shared(edges[i], edges[j])
            if c is None:
                continue
            ends = []
            for s in (strips[i], strips[j]):
                far = [e for e in s.Edges if e.distToShape(Part.Vertex(c))[0] < 1e-7 and
                       not any(e.distToShape(x)[0] < 1e-9 and abs(e.Length - x.Length) < 1e-9
                               for x in edges)]
                if not far:
                    break
                g = far[0]
                q = [v.Point for v in g.Vertexes if (v.Point - c).Length > 1e-7]
                if q:
                    ends.append(q[0])
            if len(ends) != 2 or (ends[0] - ends[1]).Length < 1e-6:
                continue                # they already meet (or were trimmed to meet)
            try:
                tri = Part.Face(Part.makePolygon([c, ends[0], ends[1], c]))
                fills.append(tri)
            except Exception:
                pass
    return fills


def radiate(p, base):
    if not p.edges:
        raise topo.GeometryError("Pick the edges to radiate from.")
    if p.direction is None:
        raise topo.GeometryError("Pick the reference plane the surface lies parallel to.")
    if p.distance <= 0:
        raise topo.GeometryError("The distance must be greater than zero.")
    n = V(p.direction).normalize()
    sign = -1.0 if p.flip else 1.0
    strips = []
    edges = list(p.edges)
    if p.propagate:
        edges = _tangent_chain(base, edges)
    for e in edges:
        body, own = _body_of_edges(base, [e])
        if body is None:
            raise topo.GeometryError("Pick edges of the model.")
        e = own[0]
        face = _support(body.shape, e)

        def dirs(pt, u, e=e, face=face, body=body):
            t = V(e.tangentAt(u))
            d = n.cross(t)
            if d.Length < 1e-9:
                raise topo.GeometryError("An edge runs along the plane's normal; it can't "
                                         "radiate parallel to the plane.")
            d.normalize()
            if body.kind == SOLID:
                eps = max(body.shape.BoundBox.DiagonalLength * 1e-4, 1e-5)
                q = pt + d * eps
                if body.shape.isInside(q + n * eps, 1e-9, False) or \
                        body.shape.isInside(q - n * eps, 1e-9, False):
                    d = -d                          # out of the solid
            elif face is not None:
                eps = max(face.BoundBox.DiagonalLength * 1e-3, 1e-4)
                if face.distToShape(Part.Vertex(pt + d * eps))[0] < \
                        face.distToShape(Part.Vertex(pt - d * eps))[0]:
                    d = -d                          # away from the face
            return d * (sign * p.distance)
        strips.append(_strip(e, dirs))
    shape = _sew(strips, 1e-6, p.tag)
    return _new(p, base, [shape]), shape


def _tangent_chain(base, edges):
    """The picked edges and every edge meeting them smoothly, end to end."""
    out = list(edges)
    body, _own = _body_of_edges(base, edges[:1])
    if body is None:
        return out
    pool = list(body.shape.Edges)
    todo = list(edges)
    while todo:
        e = todo.pop()
        for g in pool:
            if any(g.isSame(x) or (g.distToShape(x)[0] < 1e-9 and abs(g.Length - x.Length)
                                   < 1e-9) for x in out):
                continue
            c = _shared(e, g)
            if c is None:
                continue
            try:
                te = V(e.tangentAt(e.Curve.parameter(c)))
                tg = V(g.tangentAt(g.Curve.parameter(c)))
            except Exception:
                continue
            if te.Length < 1e-12 or tg.Length < 1e-12:
                continue
            if abs(abs(te.normalize().dot(tg.normalize())) - 1) < 1e-6:
                out.append(g)
                todo.append(g)
    return out


def untrim(p, base):
    if not p.faces:
        raise topo.GeometryError("Pick the faces to untrim.")
    out_faces = []
    for f in p.faces:
        s = f.Surface
        if p.kind == INTERNAL:
            nf = Part.Face(s, f.OuterWire) if s.TypeId != "Part::GeomPlane" else \
                Part.Face(f.OuterWire)
            out_faces.append(nf)
            continue
        u0, u1, v0, v1 = f.ParameterRange
        du, dv = (u1 - u0) * p.percent / 100.0, (v1 - v0) * p.percent / 100.0
        try:
            bu0, bu1, bv0, bv1 = s.bounds()
        except Exception:
            bu0, bu1, bv0, bv1 = -1e100, 1e100, -1e100, 1e100
        nu0, nu1 = max(u0 - du, bu0), min(u1 + du, bu1)
        nv0, nv1 = max(v0 - dv, bv0), min(v1 + dv, bv1)
        import math
        if s.isUPeriodic() and nu1 - nu0 > 2 * math.pi - 1e-9:
            nu0, nu1 = u0, u0 + 2 * math.pi                     # once round
        if s.isVPeriodic() and nv1 - nv0 > 2 * math.pi - 1e-9:
            nv0, nv1 = v0, v0 + 2 * math.pi
        nf = s.toShape(nu0, nu1, nv0, nv1)
        if p.kind == EXTERNAL:
            holes = [w for w in f.Wires if not w.isSame(f.OuterWire)]
            if holes:
                nf.cutHoles(holes)
        out_faces.append(nf)
    shape = _sew([x for x in out_faces], 1e-6, p.tag)
    return _new(p, base, [shape]), shape


def _cylinder_pairs(faces):
    """[(thickness, key a, key b, mid face)] for coaxial cylindrical faces (a tube's
    inside and outside): the cylinder halfway between them, over the height and
    the turn they share."""
    import math
    cyl = [(k, f) for k, f in enumerate(faces) if f.Surface.TypeId == "Part::GeomCylinder"]
    out = []
    for ia, (ka, a) in enumerate(cyl):
        sa = a.Surface
        ax = V(sa.Axis).normalize()
        for kb, b in cyl[ia + 1:]:
            sb = b.Surface
            if abs(abs(V(sb.Axis).normalize().dot(ax)) - 1) > 1e-7:
                continue
            off = V(sb.Center) - V(sa.Center)
            if (off - ax * off.dot(ax)).Length > 1e-6:
                continue                            # not on one axis
            t = abs(sa.Radius - sb.Radius)
            if t < 1e-9:
                continue
            rm = 0.5 * (sa.Radius + sb.Radius)

            def span(f):
                hs = [(v.Point - V(sa.Center)).dot(ax) for v in f.Vertexes]
                for e in f.Edges:
                    if hasattr(e.Curve, "Center"):
                        hs.append((V(e.Curve.Center) - V(sa.Center)).dot(ax))
                return min(hs), max(hs)
            lo = max(span(a)[0], span(b)[0])
            hi = min(span(a)[1], span(b)[1])
            if hi - lo < 1e-6:
                continue
            mid = Part.Cylinder()
            mid.Center = V(sa.Center)
            mid.Axis = ax
            mid.Radius = rm
            # Only where both walls are: the turn they share, in the mid cylinder's angle.
            u0, u1 = 0.0, 2 * math.pi
            full = True
            for f in (a, b):
                fu0, fu1, fv0, fv1 = f.ParameterRange
                if fu1 - fu0 >= 2 * math.pi - 1e-6:
                    continue
                pa = f.Surface.value(fu0, 0.5 * (fv0 + fv1))
                ga, _v = mid.parameter(pa)
                ga = ga % (2 * math.pi)
                if full:
                    u0, u1, full = ga, ga + (fu1 - fu0), False
                else:
                    # Shift into the same turn, then overlap.
                    while ga < u0 - math.pi:
                        ga += 2 * math.pi
                    while ga > u0 + math.pi:
                        ga -= 2 * math.pi
                    u0, u1 = max(u0, ga), min(u1, ga + (fu1 - fu0))
            face = mid.toShape(u0, u1, lo, hi) if u1 - u0 > 1e-9 else None
            if face is not None and face.Area > 1e-9:
                out.append((t, ("c", ka), ("c", kb), face))
    return out


def mid_surface(p, base):
    """Surfaces midway between pairs of parallel flat faces facing each other."""
    if not p.faces:
        raise topo.GeometryError("Pick the faces (or a body) to find face pairs on.")
    planar = [f for f in p.faces if f.Surface.TypeId == "Part::GeomPlane"]
    cands = _cylinder_pairs(p.faces)
    for i, a in enumerate(planar):
        na = V(a.normalAt(0, 0))
        for j, b in enumerate(planar):
            if j <= i:
                continue
            nb = V(b.normalAt(0, 0))
            if na.dot(nb) > -1 + 1e-7:
                continue                            # not facing opposite ways
            d = (b.CenterOfMass - a.CenterOfMass).dot(na)
            if d >= -1e-9:
                continue                            # not facing each other
            t = -d
            ma = a.copy()
            ma.translate(-na * (t / 2.0))
            mb = b.copy()
            mb.translate(na * (t / 2.0))
            try:
                ov = ma.common(mb)
            except Exception:
                continue
            if ov.Area > 1e-9:
                cands.append((t, ("p", i), ("p", j), ov))
    if not cands:
        raise topo.GeometryError("No face pairs found: pick parallel flat faces facing each "
                                 "other (a wall's two sides), or a tube's inside and "
                                 "outside.")
    # The pairs a wall's thickness apart: up to the threshold, or (0) the thinnest.
    limit = p.threshold if p.threshold > 0 else min(c[0] for c in cands) * (1 + 1e-6) + 1e-9
    mids, used = [], set()
    for t, i, j, ov in sorted(cands, key=lambda c: c[0]):
        if t > limit or i in used or j in used:
            continue
        used.update((i, j))
        mids.extend(ov.Faces)
    if not mids:
        raise topo.GeometryError("No face pairs found: pick parallel flat faces facing each "
                                 "other (a wall's two sides).")
    shape = _sew(mids, 1e-6, p.tag)
    return _new(p, base, [shape]), shape


# ------------------------------------------------------------------ solids

def _side_pieces(shape, cutter, keep_behind, tag):
    """Pieces of ``shape`` sliced by ``cutter``, on the side behind its normal
    (or in front, when ``keep_behind`` is False)."""
    r = topo.slice_by(shape, [cutter], tag)
    keep = []
    for s in pieces_of(r, SOLID):
        from .intersect import inner_point
        ip = inner_point(s)
        d, pairs, info = cutter.distToShape(Part.Vertex(ip))
        q = pairs[0][0]
        f = None
        best = None
        for face in cutter.Faces:
            dd = face.distToShape(Part.Vertex(q))[0]
            if best is None or dd < best:
                best, f = dd, face
        uu, vv = f.Surface.parameter(q)
        n = V(f.normalAt(uu, vv))
        behind = (ip - q).dot(n) < 0
        if behind == keep_behind:
            keep.append(s)
    return keep


def cut_with_surface(p, base):
    if p.surface is None:
        raise topo.GeometryError("Pick the cutting surface or plane.")
    out = base.copy()
    res = common.Result(out)
    ids = p.scope.pick(base, SOLID)
    for bid in ids:
        b = base.get(bid)
        if not topo.touches(b.shape, p.surface):
            continue
        keep = _side_pieces(b.shape, p.surface, not p.flip, p.tag)
        pieces = pieces_of(topo.slice_by(b.shape, [p.surface], p.tag), SOLID)
        if len(pieces) < 2:
            continue
        if not keep:
            out.remove(bid)
            res.touched.append(bid)
            continue
        shape = keep[0] if len(keep) == 1 else Part.makeCompound(keep)
        out.replace(bid, topo.tagged(shape, p.tag), p.feature)
        res.touched.append(bid)
    if not res.touched:
        raise topo.GeometryError("The surface doesn't cut through any body. It must reach "
                                 "across the whole body.")
    return res, p.surface


def replace_face(p, base):
    """The faces' solid grows out (along the faces' normals) to the surface, or is
    trimmed back to it."""
    if not p.faces:
        raise topo.GeometryError("Pick the faces to replace.")
    if p.surface is None:
        raise topo.GeometryError("Pick the replacement surface.")
    from .edges import faces_by_body
    groups = faces_by_body(base, p.faces)
    out = base.copy()
    res = common.Result(out)
    size = max(b.shape.BoundBox.DiagonalLength for b in base) + \
        p.surface.BoundBox.DiagonalLength
    for bid, faces in groups.items():
        body = base.get(bid).shape
        grown = body
        normals = []
        for f in faces:
            if f.Surface.TypeId != "Part::GeomPlane":
                raise topo.GeometryError("Replace Face works on flat faces in this version.")
            n = V(f.normalAt(0, 0))
            if body.isInside(f.CenterOfMass + n * 1e-4, 1e-7, False):
                n = -n
            normals.append(n)
            grown = grown.fuse(f.extrude(n * size))
        try:
            grown = grown.removeSplitter()
        except Exception:
            pass
        # Keep the side of the surface the body is on (away from the faces).
        n = normals[0]
        cut = _side_pieces(grown, p.surface, True, p.tag)
        mid = faces[0].CenterOfMass - n * 1e-3
        # The surface's own normal may point either way: keep the pieces holding the
        # body's inside, away from the faces.
        inner = body.CenterOfMass if body.isInside(body.CenterOfMass, 1e-7, False) else mid
        pieces = pieces_of(topo.slice_by(grown, [p.surface], p.tag), SOLID)
        if len(pieces) < 2:
            raise topo.GeometryError("The replacement surface doesn't cut across the faces' "
                                     "body. It must reach past the faces' edges.")
        keep = [s for s in pieces if s.isInside(inner, 1e-6, True)]
        if not keep:
            keep = cut
        shape = keep[0] if len(keep) == 1 else keep[0].fuse(keep[1:])
        try:
            shape = shape.removeSplitter()
        except Exception:
            pass
        out.replace(bid, topo.tagged(shape, p.tag), p.feature)
        res.touched.append(bid)
    return res, p.surface
