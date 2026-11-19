# SPDX-License-Identifier: LGPL-2.1-or-later
"""Skinning: a surface through a row of section curves, with end tangents.

FreeCAD's loft (BRepOffsetAPI_ThruSections) has no start/end constraints and no
guide curves, and its sweep (MakePipeShell) has no twist or guide curves. Both
are built here the classical way:

* every section becomes the same number of B-spline curves ("strips"), split at
  matching places (landmarks: corners when the counts agree, guide curves);
* the curves of one strip are made compatible (one degree, one knot vector);
* each pole is interpolated across the sections with one parameterisation, so
  every strip is a B-spline surface whose iso-curves at the sections *are* the
  section curves; an end tangent given to every pole makes the surface leave
  the section in that direction (SolidWorks' Normal to Profile, Path Tangent);
* strips and end caps are sewn into a shell, and a solid when closed.
"""

import math

import FreeCAD as App
import Part

from . import topo

V = App.Vector
TOL = 1e-7


# ------------------------------------------------------------------ curves

def _bspline(edge):
    """A non-rational B-spline of an edge, running the way the edge does in its wire."""
    c = edge.Curve
    if isinstance(c, Part.Line) or c.TypeId == "Part::GeomLine":
        bs = Part.BSplineCurve()
        a, b = edge.valueAt(edge.FirstParameter), edge.valueAt(edge.LastParameter)
        bs.buildFromPolesMultsKnots([a, b], [2, 2], [0.0, 1.0], False, 1)
    else:
        try:
            bs = c.toBSpline(edge.FirstParameter, edge.LastParameter)
        except Exception:
            bs = edge.toNurbs().Edges[0].Curve
        if bs.isPeriodic():
            bs.setNotPeriodic()
        if bs.isRational() or bs.Degree > 7:
            size = max(edge.BoundBox.DiagonalLength, 1.0)
            bs = bs.approximateBSpline(TOL * size, 40, 7, "C2")
    if edge.Orientation == "Reversed":
        bs.reverse()
    bs.scaleKnotsToBounds(0.0, 1.0)
    return bs


def _rebuild(bs, poles):
    out = Part.BSplineCurve()
    out.buildFromPolesMultsKnots(poles, bs.getMultiplicities(), bs.getKnots(), False, bs.Degree)
    return out


def transformed(curves, matrix):
    """The curves with every pole moved by ``matrix`` (B-splines are affine-invariant)."""
    return [_rebuild(c, [matrix.multVec(p) for p in c.getPoles()]) for c in curves]


def oriented_curves(wire):
    """The wire's edges as B-splines, in order, each running on from the last."""
    edges = wire.OrderedEdges if hasattr(wire, "OrderedEdges") else wire.Edges
    out = []
    for e in edges:
        bs = _bspline(e)
        if out and (bs.value(0.0) - out[-1].value(1.0)).Length > \
                (bs.value(1.0) - out[-1].value(1.0)).Length:
            bs.reverse()
        out.append(bs)
    if len(out) > 1 and (out[0].value(0.0) - out[1].value(0.0)).Length < TOL and \
            (out[0].value(1.0) - out[1].value(0.0)).Length > TOL:
        out[0].reverse()
    return out


def compatible(curves):
    """Copies of ``curves`` sharing one degree and one knot vector."""
    curves = [c.copy() for c in curves]
    deg = max(c.Degree for c in curves)
    for c in curves:
        if c.Degree < deg:
            c.increaseDegree(deg)
    need = {}
    for c in curves:
        for k, m in zip(c.getKnots(), c.getMultiplicities()):
            key = round(k, 9)
            need[key] = max(need.get(key, 0), m)
    for c in curves:
        have = {round(k, 9): m for k, m in zip(c.getKnots(), c.getMultiplicities())}
        for k, m in sorted(need.items()):
            if 0.0 < k < 1.0 and have.get(k, 0) < m:
                c.insertKnot(k, m - have.get(k, 0), 1e-10)
    return curves


# ------------------------------------------------------------------ sections

class Section(object):
    """A loft section: a closed or open chain of B-splines, or a point."""

    def __init__(self, shape):
        self.point = None
        self.curves = []
        if isinstance(shape, App.Vector):
            self.point = V(shape)
            return
        if shape.ShapeType == "Vertex":
            self.point = V(shape.Point)
            return
        wire = shape if shape.ShapeType == "Wire" else \
            shape.OuterWire if shape.ShapeType == "Face" else Part.Wire(shape.Edges)
        self.curves = oriented_curves(wire)
        self.closed = (self.curves[0].value(0.0) - self.curves[-1].value(1.0)).Length < 1e-6
        self._measure()

    def _measure(self):
        self.lengths = [Part.Edge(c).Length for c in self.curves]
        self.total = sum(self.lengths)
        acc, self.vertex_f = 0.0, [0.0]
        for l in self.lengths[:-1]:
            acc += l
            self.vertex_f.append(acc / self.total)

    @property
    def is_point(self):
        return self.point is not None

    def at(self, f):
        """The point at arc-length fraction ``f`` (wrapping when closed)."""
        if self.is_point:
            return V(self.point)
        i, u = self._locate(f)
        return self.curves[i].value(u)

    def _locate(self, f):
        if self.closed:
            f = f % 1.0
        f = min(max(f, 0.0), 1.0)
        target = f * self.total
        acc = 0.0
        for i, l in enumerate(self.lengths):
            if target <= acc + l + 1e-12 or i == len(self.lengths) - 1:
                local = min(max(target - acc, 0.0), l)
                e = Part.Edge(self.curves[i])
                u = e.getParameterByLength(local) if 0 < local < l else (0.0 if local <= 0 else 1.0)
                return i, u
            acc += l
        return len(self.curves) - 1, 1.0

    def tangent_at(self, f):
        i, u = self._locate(f)
        t = self.curves[i].tangent(u)[0]
        return V(t).normalize()

    def fraction_of(self, point):
        """The arc-length fraction of the point of the section nearest ``point``."""
        best = None
        acc = 0.0
        for c, l in zip(self.curves, self.lengths):
            u = c.parameter(point)
            d = (c.value(u) - point).Length
            if best is None or d < best[0] - 1e-12:
                part = Part.Edge(c, 0.0, u).Length if u > 1e-12 else 0.0
                best = (d, (acc + part) / self.total)
            acc += l
        return best[1], best[0]

    def wire(self):
        return Part.Wire([Part.Edge(c) for c in self.curves])

    def corners(self, tol_deg=1.0):
        """Fractions where the chain turns sharply (a path that isn't smooth)."""
        out = []
        for k in range(1, len(self.curves) + (1 if self.closed else 0)):
            a = self.curves[k - 1].tangent(1.0)[0]
            b = self.curves[k % len(self.curves)].tangent(0.0)[0]
            if V(a).getAngle(V(b)) > math.radians(tol_deg):
                out.append(self.vertex_f[k % len(self.curves)] if k < len(self.curves) else 0.0)
        return out

    def samples(self, n=48):
        if self.is_point:
            return [V(self.point)] * n
        if self.closed:
            return [self.at(k / float(n)) for k in range(n)]
        return [self.at(k / float(n - 1)) for k in range(n)]

    def centre(self):
        if self.is_point:
            return V(self.point)
        pts = self.samples(64)
        c = V()
        for p in pts:
            c += p
        return c * (1.0 / len(pts))

    def area_vector(self):
        pts = self.samples(64)
        c = self.centre()
        a = V()
        for i in range(len(pts)):
            a += (pts[i] - c).cross(pts[(i + 1) % len(pts)] - c)
        return a * 0.5

    def reverse(self):
        self.curves = [c.copy() for c in reversed(self.curves)]
        for c in self.curves:
            c.reverse()
        self._measure()

    def start_at(self, f):
        """Make the closed section start at fraction ``f``."""
        f = f % 1.0
        if f < 1e-9 or f > 1 - 1e-9:
            return
        i, u = self._locate(f)
        c = self.curves[i]
        cut = [] if u <= 1e-9 or u >= 1 - 1e-9 else None
        if cut is None:
            a, b = c.copy(), c.copy()
            a.segment(0.0, u)
            b.segment(u, 1.0)
            a.scaleKnotsToBounds(0.0, 1.0)
            b.scaleKnotsToBounds(0.0, 1.0)
            self.curves = [b] + self.curves[i + 1:] + self.curves[:i] + [a]
        else:
            j = i + 1 if u >= 1 - 1e-9 else i
            self.curves = self.curves[j:] + self.curves[:j]
        self._measure()

    def pieces(self, fractions):
        """The section cut at the sorted ``fractions`` (0 and, open, 1 included):
        one B-spline per piece. A piece never spans a corner: corners are always
        among the cut points."""
        out = []
        ends = list(fractions) + [1.0]
        bounds = [0.0]
        for l in self.lengths:
            bounds.append(bounds[-1] + l)
        for a, b in zip(ends[:-1], ends[1:]):
            mid = 0.5 * (a + b) * self.total
            i = next((k for k in range(len(self.lengths)) if mid <= bounds[k + 1]),
                     len(self.lengths) - 1)
            e = Part.Edge(self.curves[i])
            l = self.lengths[i]

            def param(x):
                local = x * self.total - bounds[i]
                if local <= l * 1e-9:
                    return 0.0
                if local >= l * (1 - 1e-9):
                    return 1.0
                return e.getParameterByLength(local)
            ua, ub = param(a), param(b)
            c = self.curves[i].copy()
            if ua > 0.0 or ub < 1.0:
                if ub - ua < 1e-12:
                    raise topo.GeometryError("Couldn't match the loft profiles' edges.")
                c.segment(ua, ub)
                c.scaleKnotsToBounds(0.0, 1.0)
            out.append(c)
        return out


def _shape_error(a, b):
    """How far apart matching points of two sections are."""
    sa, sb = a.samples(36), b.samples(36)
    return sum((p - q).Length for p, q in zip(sa, sb))


def align(sections):
    """Give every section the same winding about the direction of travel, and the
    least twist to the one before."""
    centres = [s.centre() for s in sections]

    def travel(k):
        a = centres[max(k - 1, 0)]
        b = centres[min(k + 1, len(sections) - 1)]
        return b - a
    prev = prev_sign = None
    for k, s in enumerate(sections):
        if s.is_point:
            continue
        if s.closed:
            sign = s.area_vector().dot(travel(k)) >= 0
        if prev is None:
            prev, prev_sign = s, (sign if s.closed else None)
            continue
        if s.closed and prev.closed:
            if sign != prev_sign:
                s.reverse()
            if len(s.curves) > 1:
                options = list(s.vertex_f)
            else:
                options = [k2 / 72.0 for k2 in range(72)]
            best = None
            for f in options:
                e = _shape_error(prev, _rotated_copy(s, f))
                if best is None or e < best[0] - 1e-9:
                    best = (e, f)
            s.start_at(best[1])
        elif not s.closed and not prev.closed:
            a0, a1 = prev.at(0.0), prev.at(1.0)
            if (s.at(0.0) - a0).Length + (s.at(1.0) - a1).Length > \
                    (s.at(1.0) - a0).Length + (s.at(0.0) - a1).Length:
                s.reverse()
        else:
            raise topo.GeometryError("Loft profiles must all be closed, or all open.")
        prev, prev_sign = s, prev_sign


def _rotated_copy(s, f):
    t = Section.__new__(Section)
    t.point = None
    t.curves = list(s.curves)
    t.closed = s.closed
    t._measure()
    t.start_at(f)
    return t


def _interp(table, x):
    """Piecewise-linear lookup in sorted ``(x, y)`` pairs."""
    for (x0, y0), (x1, y1) in zip(table[:-1], table[1:]):
        if x <= x1 + 1e-12:
            if x1 - x0 < 1e-15:
                return y0
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return table[-1][1]


def match(sections, landmarks=()):
    """Cut every section into the same number of pieces.

    ``landmarks``: lists, one per landmark, of the fraction on each section
    (``None`` for point sections) that must line up (guide curves). Corners line
    up when every section has the same number of edges. Returns (pieces per
    section, the common parameters of the cuts)."""
    real = [s for s in sections if not s.is_point]
    marks = [list(m) for m in landmarks]
    counts = {len(s.curves) for s in real}
    if len(counts) == 1 and counts.pop() > 1:
        idx = [i for i, s in enumerate(sections) if not s.is_point]
        for j in range(1, len(real[0].curves)):
            marks.append([sections[i].vertex_f[j] if i in idx else None
                          for i in range(len(sections))])
    # The common parameter of a landmark: the mean of its fractions.
    taus = []
    for m in marks:
        fs = [f for f in m if f is not None]
        taus.append(sum(fs) / len(fs))
    order = sorted(range(len(marks)), key=lambda j: taus[j])
    tables = []
    for i, s in enumerate(sections):
        if s.is_point:
            tables.append(None)
            continue
        t = [(0.0, 0.0)]
        for j in order:
            f = marks[j][i]
            if f is None:
                continue
            if f <= t[-1][0] + 1e-9:
                raise topo.GeometryError("The guide curves cross the profiles in a different "
                                         "order on different profiles.")
            t.append((f, taus[j]))
        t.append((1.0, 1.0))
        tables.append(t)
    cuts = {0.0}
    for j in order:
        cuts.add(round(taus[j], 10))
    for s, t in zip(sections, tables):
        if t is None:
            continue
        for f in s.vertex_f:
            cuts.add(round(_interp(t, f), 10))
    cuts = sorted(c for c in cuts if c < 1.0 - 1e-9)
    merged = []
    for c in cuts:
        if not merged or c - merged[-1] > 1e-7:
            merged.append(c)
    out = []
    for s, t in zip(sections, tables):
        if t is None:
            out.append(None)
            continue
        back = [(y, x) for x, y in t]
        out.append(s.pieces([_interp(back, c) for c in merged]))
    return out, merged


# ------------------------------------------------------------------ skinning

def _params(rows, closed):
    """Chord-length parameters of the sections (rows of strips of curves)."""
    centres = []
    for row in rows:
        pts = [p for c in row for p in c.getPoles()]
        c = V()
        for p in pts:
            c += p
        centres.append(c * (1.0 / len(pts)))
    d = [max((centres[k + 1] - centres[k]).Length, 1e-9) for k in range(len(rows) - 1)]
    if closed:
        d.append(max((centres[0] - centres[-1]).Length, 1e-9))
    total = sum(d)
    v, acc = [0.0], 0.0
    for x in d:
        acc += x
        v.append(acc / total)
    return v if closed else v[:len(rows)]


def surfaces(rows, closed=False, start=None, end=None, params=None):
    """B-spline surfaces through ``rows`` (sections, each a list of strip curves;
    the curves of one strip compatible across rows).

    ``start``/``end``: functions of a pole's position on the first/last section
    giving the surface's derivative there (d/dv, v in [0, 1]), or None."""
    n = len(rows)
    if n < 2 or (closed and n < 3):
        raise topo.GeometryError("A loft needs at least {} profiles.".format(3 if closed else 2))
    v = params or _params(rows, closed)
    out = []
    for j in range(len(rows[0])):
        strip = compatible([row[j] for row in rows])
        poles = [c.getPoles() for c in strip]
        ref = strip[0]
        vcurves = []
        for i in range(len(poles[0])):
            pts = [poles[k][i] for k in range(n)]
            bc = Part.BSplineCurve()
            if closed:
                bc.interpolate(Points=pts, PeriodicFlag=True, Parameters=v)
            elif start is not None or end is not None:
                tans = [V()] * n
                flags = [False] * n
                if start is not None:
                    tans[0], flags[0] = start(pts[0]), True
                if end is not None:
                    tans[-1], flags[-1] = end(pts[-1]), True
                if n == 2 and flags[0] != flags[-1]:
                    # Two points and one tangent: add the missing end as free.
                    pass
                bc.interpolate(Points=pts, Parameters=v, Tangents=tans, TangentFlags=flags,
                               Scale=False)
            else:
                bc.interpolate(Points=pts, Parameters=v)
            vcurves.append(bc)
        vc = vcurves[0]
        grid = [c.getPoles() for c in vcurves]
        s = Part.BSplineSurface()
        s.buildFromPolesMultsKnots(grid, ref.getMultiplicities(), vc.getMultiplicities(),
                                   ref.getKnots(), vc.getKnots(), False, closed,
                                   ref.Degree, vc.Degree)
        out.append(s)
    return out


def _cap(row):
    edges = [Part.Edge(c) for c in row]
    w = Part.Wire(edges)
    try:
        f = Part.Face(w)
        if f.isValid() and f.Area > 0:
            return f
    except Exception:
        pass
    return Part.makeFilledFace(edges)


def build(rows, closed=False, solid=True, start=None, end=None, params=None, tag=1):
    """The skinned shape: a solid (closed sections, capped) or a shell/face set."""
    surfs = surfaces(rows, closed, start, end, params)
    faces = [Part.Face(s) for s in surfs]
    caps_ok = solid and not closed
    if caps_ok:
        for row in (rows[0], rows[-1]):
            if all(len(c.getPoles()) and max((p - c.getPole(1)).Length for p in c.getPoles())
                   < 1e-9 for c in row):
                continue            # a point section: the surface closes itself there
            faces.append(_cap(row))
    sew = Part.Shell(faces)
    sew.sewShape()
    shells = sew.Shells if sew.ShapeType != "Shell" else [sew]
    if solid:
        if len(shells) != 1 or not shells[0].isClosed():
            raise topo.GeometryError("The loft's faces don't close into a solid. Check the "
                                     "profiles' order and that they are closed.")
        s = Part.Solid(shells[0])
        if s.Volume < 0:
            s.reverse()
        return topo.tagged(s, tag)
    if len(shells) == 1:
        return topo.tagged(shells[0], tag)
    return topo.tagged(Part.makeCompound(shells), tag)


def loft(sections, closed=False, solid=True, start=None, end=None, landmarks=(), tag=1):
    """Loft through Section objects (aligned already)."""
    pieces, _cuts = match(sections, landmarks)
    rows = _with_points(sections, pieces)
    return build(rows, closed, solid, start, end, tag=tag)


def _with_points(sections, pieces):
    """Rows of strip curves; a point section copies its neighbour's structure."""
    template = next(p for p in pieces if p is not None)
    rows = []
    for s, p in zip(sections, pieces):
        if p is None:
            rows.append([_rebuild(c, [V(s.point)] * c.NbPoles) for c in template])
        else:
            rows.append(p)
    return rows


# ------------------------------------------------------------------ guide curves

TO_NEXT_GUIDE = "To Next Guide"
TO_NEXT_EDGE = "To Next Edge"
INFLUENCES = [TO_NEXT_EDGE, TO_NEXT_GUIDE]


class Guide(object):
    """A guide curve: a chain of edges, measured along its length."""

    def __init__(self, shape, label="guide curve"):
        self.label = label
        self.sec = Section(shape)
        if self.sec.closed:
            raise topo.GeometryError("A guide curve must be open ({}).".format(label))

    def point_at_length(self, l):
        return self.sec.at(l / self.sec.total)

    def position(self, point):
        f, d = self.sec.fraction_of(point)
        return f * self.sec.total, d


def _greville(c):
    flat = []
    for k, m in zip(c.getKnots(), c.getMultiplicities()):
        flat.extend([k] * m)
    p = c.Degree
    return [sum(flat[i + 1:i + 1 + p]) / float(p) for i in range(c.NbPoles)]


def _weights(taus, guide_taus, bounds, influence, closed):
    """Weight of each guide at each common parameter."""
    out = []
    n = len(guide_taus)
    order = sorted(range(n), key=lambda g: guide_taus[g])
    for t in taus:
        w = [0.0] * n
        if influence == TO_NEXT_EDGE:
            for g, tg in enumerate(guide_taus):
                lo = max([b for b in bounds if b < tg - 1e-9] or ([None] if closed else [0.0]))
                hi = min([b for b in bounds if b > tg + 1e-9] or ([None] if closed else [1.0]))
                # A closed profile with no corners: the guide's influence fades out
                # half-way round, on the far side.
                if lo is None:
                    lo = max(b for b in bounds) - 1.0 if bounds else tg - 0.5
                if hi is None:
                    hi = min(b for b in bounds) + 1.0 if bounds else tg + 0.5
                for tt in (t, t - 1.0, t + 1.0) if closed else (t,):
                    if lo - 1e-12 <= tt <= tg and tg - lo > 1e-12:
                        w[g] = max(w[g], (tt - lo) / (tg - lo))
                    elif tg <= tt <= hi + 1e-12 and hi - tg > 1e-12:
                        w[g] = max(w[g], (hi - tt) / (hi - tg))
                    elif abs(tt - tg) < 1e-12:
                        w[g] = 1.0
                h = w[g]
                w[g] = h * h * (3 - 2 * h)          # eases in and out: no crease
        else:
            if n == 1:
                w[0] = 1.0
            else:
                ts = [guide_taus[g] for g in order]
                if closed:
                    ext = [(ts[-1] - 1.0, order[-1])] + list(zip(ts, order)) + \
                        [(ts[0] + 1.0, order[0])]
                else:
                    ext = [(-1e9, order[0])] + list(zip(ts, order)) + [(1e9, order[-1])]
                for (ta, ga), (tb, gb) in zip(ext[:-1], ext[1:]):
                    if ta - 1e-12 <= t <= tb + 1e-12:
                        if ga == gb or tb - ta > 1e8 or tb - ta < 1e-12:
                            w[ga] = 1.0
                        else:
                            f = (t - ta) / (tb - ta)
                            w[ga] += 1.0 - f
                            w[gb] += f
                        break
        out.append(w)
    return out


def guided_loft(sections, guides, influence=TO_NEXT_EDGE, solid=True, start=None, end=None,
                per_span=6, tag=1):
    """A loft that follows guide curves. The guides must touch every profile."""
    size = max(max(s.wire().BoundBox.DiagonalLength for s in sections if not s.is_point), 1.0)
    tol = 1e-4 * size
    def pierce(g, k, s):
        if s.is_point:
            l, d = g.position(s.point)
            if d > tol:
                raise topo.GeometryError("{} doesn't pass through profile {} (the point)."
                                         .format(g.label, k + 1))
            return None, l
        d, pairs, _info = s.wire().distToShape(g.sec.wire())
        if d > tol:
            raise topo.GeometryError("{} doesn't touch profile {} ({:.3g} mm away). A guide "
                                     "curve must touch every profile.".format(g.label, k + 1, d))
        l, _d = g.position(pairs[0][1])
        return pairs[0][0], l
    hits = [[pierce(g, k, s) for k, s in enumerate(sections)] for g in guides]
    # Closed profiles start at the first guide, so it lines up with the start.
    for k, s in enumerate(sections):
        if not s.is_point and s.closed:
            f, _d = s.fraction_of(hits[0][k][0])
            s.start_at(f)
    landmarks, along = [], []
    for gi, g in enumerate(guides):
        fs, ls = [], []
        for k, s in enumerate(sections):
            p, l = hits[gi][k]
            ls.append(l)
            if p is None:
                fs.append(None)
                continue
            f, _d = s.fraction_of(p)
            if s.closed and f > 1 - 1e-7:
                f = 0.0
            fs.append(f)
        along.append(ls)
        landmarks.append(fs)
    ends_ok = []
    for fs in landmarks:
        real = [f for f in fs if f is not None]
        at0 = all(f < 1e-7 for f in real)
        at1 = all(f > 1 - 1e-7 for f in real)
        if any(f < 1e-7 or f > 1 - 1e-7 for f in real) and not (at0 or at1):
            raise topo.GeometryError("A guide curve meets one profile at its end and another "
                                     "part-way along.")
        ends_ok.append(0.0 if at0 else 1.0 if at1 else None)
    marks = [fs for fs, e in zip(landmarks, ends_ok) if e is None]
    pieces, cuts = match(sections, marks)
    rows = _with_points(sections, pieces)
    v = _params(rows, False)
    base = surfaces(rows, False, None, None, v)
    gtaus, gstrip = [], []
    for fs, e in zip(landmarks, ends_ok):
        if e is not None:
            gtaus.append(e)
            gstrip.append(0 if e == 0.0 else -1)
            continue
        fsr = [f for f in fs if f is not None]
        t = round(sum(fsr) / len(fsr), 10)
        t = min(cuts, key=lambda c: abs(c - t))
        gtaus.append(t)
        gstrip.append(cuts.index(t))
    closed_sec = any(s.closed for s in sections if not s.is_point)
    vertex_taus = set()
    for t in cuts:
        if all(abs(t - gt) > 1e-9 for gt in gtaus):
            vertex_taus.add(t)
    if not closed_sec:
        vertex_taus.update([0.0, 1.0])
    bounds = sorted(vertex_taus)
    ends = list(cuts) + [1.0]
    all_rows, all_v = [rows[0]], [v[0]]
    for k in range(len(rows) - 1):
        for i in range(1, per_span + 1):
            t = i / float(per_span + 1)
            vv = v[k] + t * (v[k + 1] - v[k])
            row = [srf.vIso(vv) for srf in base]
            disp = []
            for gi, g in enumerate(guides):
                gp = g.point_at_length(along[gi][k] + t * (along[gi][k + 1] - along[gi][k]))
                at = row[gstrip[gi]].value(0.0 if gstrip[gi] >= 0 else 1.0)
                disp.append(gp - at)
            new = []
            for j, c in enumerate(row):
                a, b = ends[j], ends[j + 1]
                taus = [a + x * (b - a) for x in _greville(c)]
                ws = _weights(taus, gtaus, bounds, influence, closed_sec)
                poles = []
                for p, w in zip(c.getPoles(), ws):
                    q = V(p)
                    for wg, dg in zip(w, disp):
                        q += dg * wg
                    poles.append(q)
                new.append(_rebuild(c, poles) if not c.isRational() else c)
            all_rows.append(new)
            all_v.append(vv)
        all_rows.append(rows[k + 1])
        all_v.append(v[k + 1])
    return build(all_rows, False, solid, start, end, params=all_v, tag=tag)
