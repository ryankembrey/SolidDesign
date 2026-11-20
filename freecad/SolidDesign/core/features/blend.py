# SPDX-License-Identifier: LGPL-2.1-or-later
"""The section fillet: fillets OpenCASCADE's rolling ball can't make.

Asymmetric fillets (a distance on each face), conic and curvature-continuous
profiles, variable size with radii at points along the edge, and face fillets
held to a hold line, all come from one construction:

- Along each chain of tangent edges, sections are cut square to the edge.
- In each section, the fillet touches face 1 at distance d1 and face 2 at d2
  from the edge (found on the faces themselves); the profile runs between the
  two touch points, tangent to the faces, through a control point where the
  faces' tangent lines meet.
- The region between the profile and the corner (outwards for a convex edge,
  inwards for a concave one) is lofted through the sections and cut away (or
  added).

Circular: a rational quadratic arc (an ellipse quadrant when d1 != d2, a true
circle when d1 == d2). Conic Rho: the same with the shoulder at rho of the way
from the chord to the corner. Curvature Continuous: a quintic whose curvature
is zero where it meets the faces.
"""

import math

import FreeCAD as App
import Part

from .. import topo

V = App.Vector

CIRCULAR = "Circular"
CONIC = "Conic Rho"
CURVATURE = "Curvature Continuous"
PROFILES = [CIRCULAR, CONIC, CURVATURE]


class Law(object):
    """The fillet's size along a chain, by fraction of its length (0..1).

    ``radius(f)`` for Circular round fillets (the touch distances follow from the
    angle between the faces), or ``distances(f)`` -> (d1, d2) directly."""

    def __init__(self, radius=None, distances=None, hold=None):
        self.radius = radius
        self.distances = distances
        self.hold = hold            # [Part.Edge]: a hold line (Face Fillet)

    @classmethod
    def constant_radius(cls, r):
        return cls(radius=lambda f: r)

    @classmethod
    def constant_distances(cls, d1, d2):
        return cls(distances=lambda f: (d1, d2))

    @classmethod
    def radius_points(cls, pts):
        """``pts``: [(fraction, radius)] including the ends; linear between them."""
        pts = sorted(pts)

        def r(f):
            if f <= pts[0][0]:
                return pts[0][1]
            for (fa, ra), (fb, rb) in zip(pts, pts[1:]):
                if f <= fb:
                    return ra + (rb - ra) * (f - fa) / max(fb - fa, 1e-12)
            return pts[-1][1]
        return cls(radius=r)

    def varies(self):
        return self.hold is not None or not (
            (self.radius is not None and abs(self.radius(0.0) - self.radius(1.0)) < 1e-12 and
             abs(self.radius(0.5) - self.radius(0.0)) < 1e-12) or
            (self.distances is not None and self.distances(0.0) == self.distances(1.0) ==
             self.distances(0.5)))


# ------------------------------------------------------------------ geometry

def _normal(face, p):
    u, v = face.Surface.parameter(p)
    return face.normalAt(u, v)


def _on_face(face, q):
    """(the nearest point of the face to q, how far)."""
    d, pairs, _info = face.distToShape(Part.Vertex(q))
    return pairs[0][0], d


def _into(face, c, t, n, probe):
    """The direction in the face, square to the edge, pointing into the face."""
    u = t.cross(n)
    if u.Length < 1e-12:
        raise topo.GeometryError("A fillet edge runs along a face's normal.")
    u.normalize()
    a = _on_face(face, c + u * probe)[1]
    b = _on_face(face, c - u * probe)[1]
    return u if a <= b else -u


def _towards(face, p, c):
    """At p on the face: the tangent direction towards c."""
    n = _normal(face, p)
    w = c - p
    w = w - n * w.dot(n)
    if w.Length < 1e-12:
        return None
    w.normalize()
    return w


def _meet(p1, v1, p2, v2):
    """Where two lines come nearest (the middle of their closest points)."""
    w = p1 - p2
    a, b, c = v1.dot(v1), v1.dot(v2), v2.dot(v2)
    d, e = v1.dot(w), v2.dot(w)
    den = a * c - b * b
    if abs(den) < 1e-12:
        return None
    s = (b * e - c * d) / den
    t = (a * e - b * d) / den
    if s <= 0 or t <= 0:
        return None
    return (p1 + v1 * s + p2 + v2 * t) * 0.5


def profile_curve(p1, k, p2, profile, rho=0.5):
    """The profile from p1 to p2 with tangents towards k."""
    if profile == CURVATURE:
        beta = 0.8
        poles = [p1, p1 + (k - p1) * (beta / 2.0), p1 + (k - p1) * beta,
                 p2 + (k - p2) * beta, p2 + (k - p2) * (beta / 2.0), p2]
        c = Part.BezierCurve()
        c.setPoles(poles)
        return c
    c = Part.BezierCurve()
    c.setPoles([p1, k, p2])
    if profile == CONIC:
        rho = min(max(rho, 0.01), 0.99)
        w = rho / (1.0 - rho)
    else:
        a, b = p1 - k, p2 - k
        phi = a.getAngle(b)
        w = math.sin(phi / 2.0)
    c.setWeight(2, w)
    return c


class _Chain(object):
    def __init__(self, edges, shape):
        self.edges = edges
        self.wire = Part.Wire(edges)
        self.closed = self.wire.isClosed()
        self.length = self.wire.Length
        self.faces = [_two_faces(shape, e) for e in edges]


def _two_faces(shape, e):
    fs = []
    for f in shape.ancestorsOfType(e, Part.Face):
        if not any(f.isSame(g) for g in fs):
            fs.append(f)
    if len(fs) != 2:
        raise topo.GeometryError("A fillet edge must lie between two faces.")
    return fs


def _ordered(f1, f2, c, t):
    """Face 1 and face 2 in a steady order along the chain: (n1 x n2) along t."""
    n1, n2 = _normal(f1, c), _normal(f2, c)
    return (f1, f2) if n1.cross(n2).dot(t) >= 0 else (f2, f1)


def _hold_distance(hold, c, t):
    """Where the plane through c square to t crosses the hold line: the distance."""
    best = None
    for e in hold:
        a, b = e.FirstParameter, e.LastParameter
        n = 48
        prev = None
        for i in range(n + 1):
            u = a + (b - a) * i / float(n)
            s = (e.valueAt(u) - c).dot(t)
            if prev is not None and (s == 0 or (s > 0) != (prev[1] > 0)):
                lo, hi = prev[0], u
                for _ in range(40):
                    mid = 0.5 * (lo + hi)
                    sm = (e.valueAt(mid) - c).dot(t)
                    if (sm > 0) == (prev[1] > 0):
                        lo = mid
                    else:
                        hi = mid
                q = e.valueAt(0.5 * (lo + hi))
                d = (q - c).Length
                if best is None or d < best:
                    best = d
            prev = (u, s)
    return best


def _section(f1, f2, c, t, law, f, profile, rho, extend):
    """One section's closed wire, and whether the edge there is convex."""
    n1, n2 = _normal(f1, c), _normal(f2, c)
    size_hint = 1.0
    if law.radius is not None:
        size_hint = law.radius(f)
    elif law.distances is not None:
        size_hint = max(law.distances(f))
    probe = max(size_hint, 1e-3) * 0.05
    u1 = _into(f1, c, t, n1, probe)
    u2 = _into(f2, c, t, n2, probe)
    if law.hold is not None:
        d = _hold_distance(law.hold, c, t)
        if d is None:
            raise topo.GeometryError("The hold line doesn't run along the whole fillet edge.")
        d1 = d2 = d
    elif law.radius is not None:
        r = law.radius(f)
        alpha = u1.getAngle(u2)                 # the angle inside the corner
        if alpha < 1e-3 or alpha > math.pi - 1e-3:
            raise topo.GeometryError("The faces beside a fillet edge are tangent: there's "
                                     "nothing to round.")
        d1 = d2 = r / math.tan(alpha / 2.0)
    else:
        d1, d2 = law.distances(f)
    if d1 <= 0 or d2 <= 0:
        raise topo.GeometryError("The fillet's sizes must be greater than zero.")
    p1, e1 = _on_face(f1, c + u1 * d1)
    p2, e2 = _on_face(f2, c + u2 * d2)
    if e1 > 0.25 * d1 or e2 > 0.25 * d2:
        raise topo.GeometryError("The fillet is wider than the faces beside the edge. Make "
                                 "it smaller.")
    v1, v2 = _towards(f1, p1, c), _towards(f2, p2, c)
    k = _meet(p1, v1, p2, v2) if v1 is not None and v2 is not None else None
    if k is None:
        k = c
    curve = profile_curve(p1, k, p2, profile, rho).toShape()
    m1, m2 = _normal(f1, p1), _normal(f2, p2)
    mid = (p1 + p2) * 0.5
    convex = (c - mid).dot(m1 + m2) > 0
    h = 1.5 * max(d1, d2)
    s = 1.0 if convex else -1.0
    q1, q2 = p1 + m1 * (s * h), p2 + m2 * (s * h)
    w = Part.Wire([curve, Part.LineSegment(p2, q2).toShape(),
                   Part.LineSegment(q2, q1).toShape(), Part.LineSegment(q1, p1).toShape()])
    if extend:
        w.translate(t * extend)
    return w, convex


def _sections(chain, law, profile, rho, dmax, extend=True):
    """The sections along a chain: [(wire, convex)]."""
    straight = all(e.Curve.TypeId in ("Part::GeomLine", "Part::GeomLineSegment")
                   for e in chain.edges)
    if straight and not law.varies() and len(chain.edges) == 1:
        n = 2
    else:
        n = int(min(40, max(8, chain.length / max(0.5 * dmax, 1e-6)))) + 1
    out = []
    count = n if not chain.closed else n - 1
    for i in range(count):
        f = i / float(n - 1)
        s = chain.length * f
        e, u = _locate(chain, s)
        c = e.valueAt(u)
        t = e.tangentAt(u)
        if t.dot(_chain_dir(chain, e, u)) < 0:
            t = -t
        fa, fb = chain.faces[chain.edges.index(e)]
        f1, f2 = _ordered(fa, fb, c, t)
        ext = 0.0
        if not extend:
            pass
        elif not chain.closed and i == 0:
            ext = -0.05 * dmax
        elif not chain.closed and i == count - 1:
            ext = 0.05 * dmax
        out.append(_section(f1, f2, c, t, law, f, profile, rho, ext))
    return out


def _chain_dir(chain, e, u):
    """The direction the chain runs at u on e (from its first edge to its last)."""
    i = chain.edges.index(e)
    a, b = e.valueAt(e.FirstParameter), e.valueAt(e.LastParameter)
    if len(chain.edges) == 1:
        return b - a
    nxt = chain.edges[i + 1] if i + 1 < len(chain.edges) else None
    prv = chain.edges[i - 1] if i > 0 else None
    if nxt is not None:
        end = b if min((b - v.Point).Length for v in nxt.Vertexes) < 1e-7 else a
        start = a if end is b else b
    else:
        start = a if min((a - v.Point).Length for v in prv.Vertexes) < 1e-7 else b
        end = b if start is a else a
    return end - start


def _locate(chain, s):
    """(edge, parameter) at arc length s along the chain."""
    run = 0.0
    for i, e in enumerate(chain.edges):
        if s <= run + e.Length or i == len(chain.edges) - 1:
            local = max(0.0, min(e.Length, s - run))
            d = _chain_dir(chain, e, e.FirstParameter)
            fwd = (e.valueAt(e.LastParameter) - e.valueAt(e.FirstParameter)).dot(d) >= 0
            L = local if fwd else e.Length - local
            try:
                u = e.getParameterByLength(L)
            except Exception:
                u = e.FirstParameter + (e.LastParameter - e.FirstParameter) * L / e.Length
            return e, u
        run += e.Length
    e = chain.edges[-1]
    return e, e.LastParameter


def chains_of(edges):
    """Edges grouped into connected chains, each sorted end to end."""
    left = list(edges)
    out = []
    while left:
        chain = [left.pop(0)]
        grown = True
        while grown:
            grown = False
            for e in list(left):
                ends = [v for x in (chain[0], chain[-1]) for v in x.Vertexes]
                if any(v.isSame(w) for v in e.Vertexes for w in ends):
                    left.remove(e)
                    chain.append(e)
                    grown = True
        out.append(Part.__sortEdges__(chain))
    return out


def blend(shape, edges, law, profile=CIRCULAR, rho=0.5, tag=1, dmax=1.0):
    """``shape`` with the edges filleted by the section construction."""
    r = shape
    for chain_edges in chains_of(edges):
        cur = []
        for e in chain_edges:
            hit = next((x for x in r.Edges if x.isSame(e)), None)
            if hit is None:
                hit = _find_edge(r, e)
            if hit is None:
                raise topo.GeometryError("The fillets meet at a corner this version can't "
                                         "blend. Fillet those edges in separate features.")
            cur.append(hit)
        chain = _Chain(Part.__sortEdges__(cur), r)
        secs = _sections(chain, law, profile, rho, dmax)
        convex = [cv for _w, cv in secs]
        if not chain.closed and not all(convex):
            # Added material mustn't run past the edge's ends.
            secs = _sections(chain, law, profile, rho, dmax, extend=False)
        if any(convex) and not all(convex):
            raise topo.GeometryError("A fillet edge turns from convex to concave: fillet its "
                                     "parts separately.")
        try:
            tool = topo.loft([w for w, _c in secs], tag, solid=True, ruled=False,
                             closed=chain.closed)
        except topo.GeometryError as e:
            raise topo.GeometryError("The fillet couldn't be built along the edge ({}).".format(e))
        if not tool.Solids:
            raise topo.GeometryError("The fillet couldn't be built along the edge.")
        # The tool meets the faces tangentially: a fuzzy boolean, or OpenCASCADE can
        # miss it on curved faces.
        fz = max(1e-4, 1e-6 * r.BoundBox.DiagonalLength)
        before = r.Volume
        r = topo.cut(r, [tool], tag, fz) if convex[0] else topo.fuse(r, [tool], tag, fz)
        if abs(r.Volume - before) < 1e-9:
            raise topo.GeometryError("The fillet's boolean found nothing to round. Try a "
                                     "slightly different size.")
        r = topo.refine(r, tag)
        if not r.isValid():
            r.fix(1e-7, 1e-7, 1e-7)
    return r


def _find_edge(shape, e):
    """The edge of ``shape`` that lies along ``e`` (after earlier fillets)."""
    mid = e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))
    best = None
    for x in shape.Edges:
        d = x.distToShape(Part.Vertex(mid))[0]
        if d < 1e-6 and abs(x.Length - e.Length) < 1e-6:
            return x
        if d < 1e-6 and (best is None or abs(x.Length - e.Length) < abs(best.Length - e.Length)):
            best = x
    return best


# ------------------------------------------------------------------ across a gap

def _plane_of(face):
    if face.Surface.TypeId != "Part::GeomPlane":
        return None
    u0, u1, v0, v1 = face.ParameterRange
    return face.valueAt(0.5 * (u0 + u1), 0.5 * (v0 + v1)), \
        face.normalAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))


def across_gap(shape, f1, f2, size1, size2=None, profile=CIRCULAR, rho=0.5, chamfer=False,
               tag=1):
    """A fillet (or chamfer) between two flat faces that don't touch: rounded (cut
    straight) about the line where their planes meet; the faces between them are
    used up. ``size1``: the radius (fillet), or the distance on face 1 (chamfer;
    ``size2`` on face 2)."""
    a = _plane_of(f1)
    b = _plane_of(f2)
    if a is None or b is None:
        raise topo.GeometryError("Across a gap, both faces must be flat in this version.")
    (o1, n1), (o2, n2) = a, b
    t = n1.cross(n2)
    if t.Length < 1e-9:
        raise topo.GeometryError("The faces are parallel: they never meet.")
    t.normalize()
    # A point on both planes: the one nearest the faces' middle.
    m = (f1.CenterOfMass + f2.CenterOfMass) * 0.5
    A = [[n1.x, n1.y, n1.z], [n2.x, n2.y, n2.z], [t.x, t.y, t.z]]
    rhs = [n1.dot(o1), n2.dot(o2), t.dot(m)]
    c = _solve3(A, rhs)
    u1 = t.cross(n1)
    if (f1.CenterOfMass - c).dot(u1) < 0:
        u1 = -u1
    u2 = t.cross(n2)
    if (f2.CenterOfMass - c).dot(u2) < 0:
        u2 = -u2
    alpha = u1.getAngle(u2)
    if chamfer:
        d1, d2 = size1, (size1 if size2 is None else size2)
    else:
        if alpha < 1e-3 or alpha > math.pi - 1e-3:
            raise topo.GeometryError("The faces are tangent: there's nothing to round.")
        d1 = d2 = size1 / math.tan(alpha / 2.0)
    p1, p2 = c + u1 * d1, c + u2 * d2
    for p, f, d, which in ((p1, f1, d1, 1), (p2, f2, d2, 2)):
        if f.distToShape(Part.Vertex(p))[0] > 1e-6 * max(1.0, d):
            raise topo.GeometryError("The {} doesn't reach face {}: make it larger, so it "
                                     "lands on the face.".format(
                                         "chamfer" if chamfer else "fillet", which))
    if chamfer:
        prof = Part.LineSegment(p1, p2).toShape()
    else:
        prof = profile_curve(p1, c, p2, profile, rho).toShape()
    convex = (c - (p1 + p2) * 0.5).dot(n1 + n2) > 0
    h = 1.5 * max(d1, d2) + (c - p1).Length
    s = 1.0 if convex else -1.0
    q1, q2 = p1 + n1 * (s * h), p2 + n2 * (s * h)
    wire = Part.Wire([prof, Part.LineSegment(p2, q2).toShape(),
                      Part.LineSegment(q2, q1).toShape(), Part.LineSegment(q1, p1).toShape()])
    span = [(v.Point - c).dot(t) for f in (f1, f2) for v in f.Vertexes]
    lo, hi = min(span), max(span)
    pad = 0.05 * (hi - lo) + 1e-3
    wire.translate(t * (lo - pad))
    tool = Part.Face(wire).extrude(t * (hi - lo + 2 * pad))
    fz = max(1e-4, 1e-6 * shape.BoundBox.DiagonalLength)
    before = shape.Volume
    r = topo.cut(shape, [tool], tag, fz) if convex else topo.fuse(shape, [tool], tag, fz)
    if abs(r.Volume - before) < 1e-9:
        raise topo.GeometryError("Nothing lies between the faces to round.")
    return topo.refine(r, tag)


def _solve3(A, b):
    import numpy as np
    x = np.linalg.solve(np.array(A), np.array(b))
    return V(*[float(v) for v in x])
