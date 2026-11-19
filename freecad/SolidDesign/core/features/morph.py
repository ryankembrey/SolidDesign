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
    for a, b in zip(p.initial, p.target):
        pa = _wire_points(a)
        pb = _wire_points(b)
        if (pa[0] - pb[-1]).Length + (pa[-1] - pb[0]).Length < \
                (pa[0] - pb[0]).Length + (pa[-1] - pb[-1]).Length:
            pb = list(reversed(pb))     # the target runs the other way
        src.extend(pa)
        dsp.extend(qb - qa for qa, qb in zip(pa, pb))
    r, k = p.radius, p.stiffness
    try:
        import numpy as np
        S = np.array([[q.x, q.y, q.z] for q in src])
        D = np.array([[q.x, q.y, q.z] for q in dsp])

        def fn(q):
            x = np.array([q.x, q.y, q.z])
            d2 = ((S - x) ** 2).sum(axis=1)
            dmin = math.sqrt(d2.min())
            f = falloff(dmin / r, k)
            if f <= 0.0:
                return q
            w = 1.0 / (d2 + (1e-6 * r) ** 2) ** 1.5
            u = (w[:, None] * D).sum(axis=0) / w.sum()
            return q + V(*u) * f
    except ImportError:
        def fn(q):
            d2 = [(q - s).Length ** 2 for s in src]
            dmin = math.sqrt(min(d2))
            f = falloff(dmin / r, k)
            if f <= 0.0:
                return q
            ws = [1.0 / (x + (1e-6 * r) ** 2) ** 1.5 for x in d2]
            tot = sum(ws)
            u = V()
            for w, dd in zip(ws, dsp):
                u = u + dd * (w / tot)
            return q + u * f
    cloud = Part.makeCompound([Part.Vertex(q) for q in src])

    def reaches(shape):
        return shape.distToShape(cloud)[0] < r
    return fn, reaches, None


def push_field(p):
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

    def fn(q):
        if not inside(q):
            return q
        lo, hi = 0.0, span
        for _ in range(40):         # bisect to where the ray leaves the tool
            mid = 0.5 * (lo + hi)
            if inside(q + d * mid):
                lo = mid
            else:
                hi = mid
        return q + d * hi

    def reaches(shape):
        return topo.touches(shape, tool)
    return fn, reaches, None


def deform(p, base):
    """Returns (Result, preview)."""
    if p.kind == POINT:
        fn, reaches, _r = point_field(p)
    elif p.kind == CURVE_TO_CURVE:
        fn, reaches, _r = curve_field(p)
    elif p.kind == SURFACE_PUSH:
        fn, reaches, _r = push_field(p)
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
            s = flexed(b.shape, fn, p.tag, p.segs, face_fn=per_face)
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
        self.points = []            # [(App.Vector on the face, height)]
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
    if not p.points:
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
    pts = [V(c) for c, _h in p.points]
    hs = [h for _c, h in p.points]
    for c in pts:
        if blend(c) < 1e-6:
            raise topo.GeometryError("A control point sits on the face's edge, which stays "
                                     "put. Move it inwards.")

    def kern(a, b):
        return falloff((a - b).Length / support, MEDIUM)
    n = len(pts)
    A = np.array([[kern(pts[i], pts[j]) * blend(pts[i]) for j in range(n)] for i in range(n)])
    try:
        coef = np.linalg.solve(A, np.array(hs))
    except np.linalg.LinAlgError:
        coef = np.linalg.lstsq(A, np.array(hs), rcond=None)[0]
    surf = face.Surface

    def normal(q):
        try:
            u, v = surf.parameter(q)
            return face.normalAt(u, v)
        except Exception:
            return V(0, 0, 1)

    def fn(q):
        b = blend(q)
        if b <= 0.0:
            return q
        h = sum(c * kern(q, x) for c, x in zip(coef, pts))
        if abs(h) < 1e-15:
            return q
        return q + normal(q) * (h * b)
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
