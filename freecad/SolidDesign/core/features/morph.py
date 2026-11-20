# SPDX-License-Identifier: LGPL-2.1-or-later
"""Deform and Freeform (SolidWorks' Insert > Features > Deform and Freeform).

Both move a body's control points the way Flex does (deform.flexed): each face
becomes B-spline geometry, its control net is refined, every control point is
moved by a displacement field, and the faces are sewn back.

Deform:
- Point: a point pushed a distance along a direction; the region within the
  radius follows, smoothly to nothing at its edge (Stiffness sets how).
- Curve to curve: initial curves move onto target curves (paired in order);
  the body within the radius of the initial curves follows.
- Surface push: where a tool body overlaps the target, the target is pushed out
  along the push direction to the tool's surface.

Freeform: one face pushed in or out along its normal at control points; the
face's edges stay put, the change fading to them with contact, tangent or
curvature continuity.
"""

import math

import FreeCAD as App
import Part

from .. import topo
from ..bodies import SOLID
from . import common
from .deform import flexed

V = App.Vector

POINT, CURVE_TO_CURVE, SURFACE_PUSH = "Point", "Curve to curve", "Surface push"
DEFORM_TYPES = [POINT, CURVE_TO_CURVE, SURFACE_PUSH]
MINIMUM, MEDIUM, MAXIMUM = "Minimum", "Medium", "Maximum"
STIFFNESS = [MINIMUM, MEDIUM, MAXIMUM]
CONTACT, TANGENT, CURVATURE = "Contact", "Tangent", "Curvature"
CONTINUITY = [CONTACT, TANGENT, CURVATURE]


def falloff(s, stiffness=MEDIUM):
    """1 at s = 0, fading smoothly to 0 at s = 1 (and beyond). Minimum stiffness
    spreads the change widely; Maximum keeps it close to the point."""
    if s >= 1.0:
        return 0.0
    if s <= 0.0:
        return 1.0
    if stiffness == MINIMUM:
        return 1.0 - s * s * (3.0 - 2.0 * s)            # smoothstep
    if stiffness == MAXIMUM:
        return (1.0 - s) ** 4 * (1.0 + 4.0 * s)         # Wendland C2: sharper
    return (1.0 - s * s) ** 3                           # medium


class DeformParams(object):
    def __init__(self):
        self.kind = POINT
        self.bodies = []            # IDs (empty: every body the change reaches)
        # Point
        self.point = None           # App.Vector
        self.direction = None       # unit App.Vector
        self.distance = 5.0
        self.radius = 20.0
        self.stiffness = MEDIUM
        # Curve to curve
        self.initial = []           # [Part.Wire or Edge]
        self.target = []
        self.fixed = []             # curves that stay put
        self.deviation = 0.0        # Surface push: how far round the tool the dent spreads
        # Surface push
        self.tool = None            # a solid
        self.tool_id = ""
        self.push = None            # unit App.Vector
        self.feature = "Deform"
        self.tag = 1
        self.segs = 96


# ------------------------------------------------------------------ fields

def point_field(p):
    if p.point is None:
        raise topo.GeometryError("Pick the deform point: a vertex, or a point on a face.")
    if p.direction is None or p.direction.Length < 1e-12:
        raise topo.GeometryError("Pick the deform direction.")
    if p.radius <= 0:
        raise topo.GeometryError("The deform region radius must be greater than zero.")
    d = V(p.direction).normalize() * p.distance
    c, r, k = V(p.point), p.radius, p.stiffness

    def fn(q):
        return q + d * falloff((q - c).Length / r, k)

    def reaches(shape):
        return shape.distToShape(Part.Vertex(c))[0] < r
    return fn, reaches, (c, r)


def _wire_points(shape, n=40):
    edges = Part.__sortEdges__(shape.Edges) if len(shape.Edges) > 1 else shape.Edges
    if not edges:
        raise topo.GeometryError("A curve has no edges.")
    w = Part.Wire(edges)
    pts = w.discretize(Number=n)
    return pts


def curve_field(p):
    if not p.initial or not p.target:
        raise topo.GeometryError("Pick the initial curves and the target curves.")
    if len(p.initial) != len(p.target):
        raise topo.GeometryError("Curve to curve pairs the curves in order: pick as many "
                                 "target curves ({}) as initial curves ({})."
                                 .format(len(p.target), len(p.initial)))
    if p.radius <= 0:
        raise topo.GeometryError("The deform region radius must be greater than zero.")
    src, dsp = [], []
    near = 0
    for a, b in zip(p.initial, p.target):
        pa = _wire_points(a)
        pb = _wire_points(b)
        if (pa[0] - pb[-1]).Length + (pa[-1] - pb[0]).Length < \
                (pa[0] - pb[0]).Length + (pa[-1] - pb[-1]).Length:
            pb = list(reversed(pb))     # the target runs the other way
        src.extend(pa)
        dsp.extend(qb - qa for qa, qb in zip(pa, pb))
    near = len(src)                 # the moving samples; fixed ones follow
    for c in p.fixed:
        for q in _wire_points(c):
            src.append(q)
            dsp.append(V())
    r, k = p.radius, p.stiffness
    try:
        import numpy as np
        S = np.array([[q.x, q.y, q.z] for q in src])
        D = np.array([[q.x, q.y, q.z] for q in dsp])

        def fn(q):
            x = np.array([q.x, q.y, q.z])
            d2 = ((S - x) ** 2).sum(axis=1)
            dmin = math.sqrt(d2[:near].min())
            f = falloff(dmin / r, k)
            if f <= 0.0:
                return q
            w = 1.0 / (d2 + (1e-6 * r) ** 2) ** 1.5
            u = (w[:, None] * D).sum(axis=0) / w.sum()
            return q + V(*u) * f
    except ImportError:
        def fn(q):
            d2 = [(q - s).Length ** 2 for s in src]
            dmin = math.sqrt(min(d2[:near]))
            f = falloff(dmin / r, k)
            if f <= 0.0:
                return q
            ws = [1.0 / (x + (1e-6 * r) ** 2) ** 1.5 for x in d2]
            tot = sum(ws)
            u = V()
            for w, dd in zip(ws, dsp):
                u = u + dd * (w / tot)
            return q + u * f
    cloud = Part.makeCompound([Part.Vertex(q) for q in src[:near]])

    def reaches(shape):
        return shape.distToShape(cloud)[0] < r
    return fn, reaches, None


def push_field(p, targets=()):
    tool = p.tool
    if tool is None or not tool.Solids:
        raise topo.GeometryError("Pick the tool body (a solid) that pushes in.")
    if p.push is None or p.push.Length < 1e-12:
        raise topo.GeometryError("Pick the push direction.")
    d = V(p.push).normalize()
    bb = tool.BoundBox
    bb.enlarge(1e-6)
    span = bb.DiagonalLength * 2.0

    def inside(q):
        return bb.isInside(q) and tool.isInside(q, 1e-7, True)

    eps = 1e-7 * max(bb.DiagonalLength, 1e-6)

    def box_exit(q):
        """How far along d until the ray leaves the tool's bounding box."""
        t = span
        for c, dc, lo_, hi_ in ((q.x, d.x, bb.XMin, bb.XMax), (q.y, d.y, bb.YMin, bb.YMax),
                                (q.z, d.z, bb.ZMin, bb.ZMax)):
            if dc > 1e-12:
                t = min(t, (hi_ - c) / dc)
            elif dc < -1e-12:
                t = min(t, (lo_ - c) / dc)
        return max(t, 0.0)

    def exit_depth(q):
        if not inside(q):
            return 0.0
        far = box_exit(q) + eps
        # The first crossing of the tool's skin along the ray is where it leaves.
        try:
            sec = tool.section(Part.LineSegment(q, q + d * far).toShape())
            ts = [(v.Point - q).dot(d) for v in sec.Vertexes]
            ts = [t for t in ts if t > eps]
            if ts:
                return min(ts)
        except Exception:
            pass
        lo, hi = 0.0, far
        while hi - lo > eps:        # bisect to where the ray leaves the tool
            mid = 0.5 * (lo + hi)
            if inside(q + d * mid):
                lo = mid
            else:
                hi = mid
        return hi

    dev = max(p.deviation, 0.0)
    # A finer control net round the tool, so the dent follows its rim closely.
    focus = (tool.BoundBox.Center,
             0.5 * max(tool.BoundBox.XLength, tool.BoundBox.YLength, tool.BoundBox.ZLength) + dev)
    if dev <= 1e-9:
        def fn(q):
            return q + d * exit_depth(q)

        def reaches(shape):
            return topo.touches(shape, tool)
        return fn, reaches, focus

    # Deform deviation: the dent spreads round the tool, fading over the deviation.
    # The dent's depth is sampled where the bodies' faces are inside the tool.
    import numpy as np
    h = max(dev / 3.0, bb.DiagonalLength / 80.0)
    grown_bb = App.BoundBox(bb)
    grown_bb.enlarge(dev)
    pts, depth = [], []
    for shape in targets:
        for f in shape.Faces:
            if not f.BoundBox.intersect(grown_bb):
                continue
            u0, u1, v0, v1 = f.ParameterRange
            box = f.BoundBox
            nu = int(min(max(box.DiagonalLength / h, 8), 120))
            for i in range(nu + 1):
                for j in range(nu + 1):
                    u = u0 + (u1 - u0) * i / float(nu)
                    v = v0 + (v1 - v0) * j / float(nu)
                    q = f.valueAt(u, v)
                    if not bb.isInside(q):
                        continue
                    t = exit_depth(q)
                    if t > 0:
                        pts.append([q.x, q.y, q.z])
                        depth.append(t)
    P = np.array(pts) if pts else np.zeros((0, 3))
    T = np.array(depth)

    def fn(q):
        t = exit_depth(q)
        if len(T):
            x = np.array([q.x, q.y, q.z])
            dist = np.sqrt(((P - x) ** 2).sum(axis=1))
            s = dist / dev
            w = np.where(s < 1.0, (1.0 - s * s) ** 3, 0.0)
            t = max(t, float((T * w).max()))
        return q + d * t

    grown = tool.makeOffsetShape(dev, 1e-6) if dev > 0 else tool

    def reaches(shape):
        try:
            return topo.touches(shape, grown)
        except Exception:
            return topo.touches(shape, tool)
    return fn, reaches, focus


def deform(p, base):
    """Returns (Result, preview)."""
    if p.kind == POINT:
        fn, reaches, focus = point_field(p)
    elif p.kind == CURVE_TO_CURVE:
        fn, reaches, focus = curve_field(p)
    elif p.kind == SURFACE_PUSH:
        others = [b.shape for b in base if b.id != p.tool_id and
                  (not p.bodies or b.id in p.bodies)]
        fn, reaches, focus = push_field(p, others)
    else:
        raise topo.GeometryError("Unknown deform type " + p.kind)
    ids = [i for i in p.bodies if i] or [i for i in base.ids() if i != p.tool_id]
    out = base.copy()
    res = common.Result(out)
    changed = []
    for bid in ids:
        b = base.get(bid)
        if b is None:
            raise topo.GeometryError("A body to deform no longer exists. Re-pick it.")
        if bid == p.tool_id:
            continue
        if not reaches(b.shape):
            continue

        def per_face(f):
            return fn if reaches(f) else None
        try:
            s = flexed(b.shape, fn, p.tag, p.segs, face_fn=per_face, focus=focus)
        except topo.GeometryError as e:
            raise topo.GeometryError(str(e).replace("smaller change", "smaller distance or "
                                                    "a larger radius"))
        out.replace(bid, s, p.feature)
        res.touched.append(bid)
        changed.append(s)
    if not res.touched:
        raise topo.GeometryError("The deform doesn't reach any body. Move the point, or make "
                                 "the radius larger." if p.kind != SURFACE_PUSH else
                                 "The tool doesn't touch any body.")
    return res, topo.compound(changed, p.tag)


# ------------------------------------------------------------------ freeform

class FreeformParams(object):
    def __init__(self):
        self.face = None            # the Part.Face (of the body) to change
        self.body = ""              # its body ID
        self.points = []            # [(App.Vector on the face, height[, sideways App.Vector])]
        self.curves = []            # control curves: the face passes through them
        self.continuity = TANGENT   # at the face's edges
        self.reach = 0.5            # how far each point's change spreads, x face size
        self.spacing = 0.0          # the control net's spacing (set from the body)
        self.feature = "Freeform"
        self.tag = 1
        self.segs = 48


def _boundary_samples(face, n=600):
    """Points along the face's edges, and the largest gap between neighbours."""
    pts = []
    gap = 0.0
    total = sum(e.Length for e in face.Edges) or 1.0
    for e in face.Edges:
        k = max(4, int(n * e.Length / total))
        pts.extend(e.discretize(Number=k))
        gap = max(gap, e.Length / (k - 1))
    return pts, gap


def _edge_blend(s, continuity):
    """0 at the edge (s = 0), 1 well inside (s >= 1): the fade towards the edges."""
    if s <= 0.0:
        return 0.0
    if s >= 1.0:
        return 1.0
    if continuity == CONTACT:
        return s
    if continuity == TANGENT:
        return s * s * (3.0 - 2.0 * s)
    return s * s * s * (s * (6.0 * s - 15.0) + 10.0)     # zero slope and curvature


def freeform_field(p):
    face = p.face
    if face is None:
        raise topo.GeometryError("Pick the face to freeform.")
    if not p.points and not p.curves:
        raise topo.GeometryError("Add control points on the face, then pull them.")
    size = max(face.BoundBox.DiagonalLength, 1e-6)
    import numpy as np
    samples, gap = _boundary_samples(face)
    B = np.array([[q.x, q.y, q.z] for q in samples])
    band = 0.25 * size          # the fade from the edges reaches this far in
    # Closer than this is "on the edge": the samples are this coarse, and a control
    # point moved within a few net spacings of a trimmed edge would move the edge.
    margin = max(0.6 * gap, 3.0 * p.spacing)
    band = max(band, 2.0 * margin)

    def edge_dist(q):
        return math.sqrt((((B - np.array([q.x, q.y, q.z])) ** 2).sum(axis=1)).min())

    def blend(q):
        d = edge_dist(q)
        return _edge_blend((d - margin) / max(band - margin, 1e-9), p.continuity)

    support = max(p.reach, 0.05) * size
    surf = face.Surface

    def normal(q):
        try:
            u, v = surf.parameter(q)
            return face.normalAt(u, v)
        except Exception:
            return V(0, 0, 1)

    pts, hs, sides = [], [], []
    for item in p.points:
        c, h = V(item[0]), float(item[1])
        side = V(item[2]) if len(item) > 2 and item[2] is not None else V()
        if blend(c) < 1e-6:
            raise topo.GeometryError("A control point sits on the face's edge, which stays "
                                     "put. Move it inwards.")
        n = normal(c)
        side = side - n * side.dot(n)          # sideways only: in the face's plane
        pts.append(c)
        hs.append(h)
        sides.append(side)
    # Control curves: the face is pulled onto each curve. Sample it, find the point of
    # the face under each sample, and the move between them is one more control point.
    for crv in p.curves:
        for q in _wire_points(crv, 14):
            try:
                d, pairs, _info = face.distToShape(Part.Vertex(q))
                c = pairs[0][0]
            except Exception:
                continue
            if blend(c) < 0.05:
                continue                    # at the edge, which stays put
            n = normal(c)
            mv = q - c
            h = mv.dot(n)
            if any((c - x).Length < 0.5 * margin for x in pts):
                continue
            pts.append(c)
            hs.append(h)
            sides.append(mv - n * h)
    if not pts:
        raise topo.GeometryError("The control curves don't reach inside the face.")

    def kern(a, b):
        return falloff((a - b).Length / support, MEDIUM)
    n = len(pts)
    A = np.array([[kern(pts[i], pts[j]) * blend(pts[i]) for j in range(n)] for i in range(n)])
    rhs = np.array([[hs[i], sides[i].x, sides[i].y, sides[i].z] for i in range(n)])
    try:
        coef = np.linalg.solve(A, rhs)
    except np.linalg.LinAlgError:
        coef = np.linalg.lstsq(A, rhs, rcond=None)[0]
    P = np.array([[c.x, c.y, c.z] for c in pts])
    moves_side = bool(np.abs(coef[:, 1:]).max() > 1e-15)

    def fn(q):
        b = blend(q)
        if b <= 0.0:
            return q
        x = np.array([q.x, q.y, q.z])
        r = np.sqrt(((P - x) ** 2).sum(axis=1)) / support
        k = np.array([falloff(t, MEDIUM) for t in r])
        h, sx, sy, sz = k.dot(coef)
        out = q
        if abs(h) > 1e-15:
            out = out + normal(q) * (h * b)
        if moves_side:
            out = out + V(sx, sy, sz) * b
        return out
    return fn


def freeform(p, base):
    """Returns (Result, preview)."""
    if not p.body or p.body not in base:
        raise topo.GeometryError("Pick the face to freeform.")
    b = base.get(p.body)
    p.spacing = b.shape.BoundBox.DiagonalLength / float(p.segs)
    fn = freeform_field(p)
    target = p.face

    def per_face(f):
        return fn if f.isSame(target) or _same_face(f, target) else None
    s = flexed(b.shape, fn, p.tag, p.segs, face_fn=per_face)
    if b.kind == SOLID and not s.Solids:
        raise topo.GeometryError("The freeform didn't close into a solid; pull less.")
    out = base.copy()
    res = common.Result(out)
    out.replace(p.body, s, p.feature)
    res.touched.append(p.body)
    return res, s


def _same_face(a, b):
    try:
        return abs(a.Area - b.Area) < 1e-9 * max(a.Area, 1.0) and \
            (a.CenterOfMass - b.CenterOfMass).Length < 1e-7
    except Exception:
        return False
