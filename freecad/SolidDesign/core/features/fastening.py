# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fastening features (SolidWorks' Insert > Fastening Feature): Mounting Boss,
Snap Hook, Lip/Groove and Vent. Plastic-part details, each built as a tool solid
and added to (or cut from) the bodies it sits on.

- **Mounting Boss**: a drafted round boss on a face, with a hole down its middle
  (for a screw or an insert) or a pin on top, and optional fins that tie it to
  the wall round it.
- **Snap Hook**: a cantilever beam with a hook on its tip (a flat catch face and a
  sloped lead-in), standing on a face.
- **Lip/Groove**: where two bodies meet on a flat face (the two halves of a
  housing), a lip grows out of one and a matching groove, a gap wider and deeper,
  is cut into the other.
- **Vent**: a sketch's outer loop is cut out of the wall, leaving ribs (the
  sketch's lines) and spars (its inner loops) of a given width; inner loops can be
  kept solid instead (fill-in).

On a curved face a boss or hook reaches down to the face everywhere under it, so
it always joins the body.
"""

import math

import FreeCAD as App
import Part

from .. import topo
from . import common

V = App.Vector

HOLE, PIN = "Hole", "Pin"
BOSS_TYPES = [HOLE, PIN]
SPARS, FILL_IN = "Spars", "Fill-in"
INNER_LOOPS = [SPARS, FILL_IN]


# ------------------------------------------------------------------ helpers

def _unit(v):
    v = V(v)
    if v.Length < 1e-12:
        raise topo.GeometryError("A direction has no length.")
    return v.normalize()


def frame(n, xhint=None, angle=0.0):
    """(x, y, z) with z along n, x from the hint (or the world X or Y) laid in the
    plane, turned by angle (degrees) about z."""
    z = _unit(n)
    x = V(xhint) if xhint is not None else V(1, 0, 0)
    x = x - z * x.dot(z)
    if x.Length < 1e-9:
        x = V(0, 1, 0) - z * z.y
        if x.Length < 1e-9:
            x = V(1, 0, 0) - z * z.x
    x.normalize()
    if angle:
        x = App.Rotation(z, angle).multVec(x)
    return x, z.cross(x), z


def placed(shape, origin, x, y, z):
    m = App.Matrix(x.x, y.x, z.x, origin.x, x.y, y.y, z.y, origin.y, x.z, y.z, z.z, origin.z,
                   0, 0, 0, 1)
    s = shape.copy()
    s.transformShape(m, True)
    return s


def normal_at(face, point):
    u, v = face.Surface.parameter(point)
    n = face.normalAt(u, v)
    return n


def embed_depth(face, point, n, reach):
    """How far below the plane through ``point`` (square to n) the face drops within
    ``reach`` of the point: a boss or hook goes this far down so it joins the face."""
    big = 10.0 * reach + face.BoundBox.DiagonalLength
    x, y, z = frame(n)
    worst = 0.0
    for i in range(16):
        a = 2 * math.pi * i / 16.0
        for r in (0.5 * reach, reach):
            q = point + x * (r * math.cos(a)) + y * (r * math.sin(a))
            seg = Part.LineSegment(q + z * big, q - z * big).toShape()
            try:
                hits = [(v.Point - point).dot(z) for v in seg.section(face).Vertexes]
            except Exception:
                hits = []
            if hits:
                worst = max(worst, -min(hits, key=abs))
    return max(worst, 0.0) + 1e-3 * max(reach, 1.0)


def _frustum(r0, r1, z0, z1):
    """A cone frustum along +Z: radius r0 at z0, r1 at z1."""
    if z1 - z0 <= 1e-9:
        raise topo.GeometryError("A boss part has no height.")
    if abs(r0 - r1) < 1e-9:
        return Part.makeCylinder(r0, z1 - z0, V(0, 0, z0))
    return Part.makeCone(r0, r1, z1 - z0, V(0, 0, z0))


def _add_then_cut(base, add, cut, feature, tag, alloc):
    res = common.apply_add(base, add, feature, tag, True, common.Scope(), alloc)
    if cut is None:
        return res
    ids = res.touched + res.created
    res2 = common.apply_cut(res.bodies, cut, feature, tag, common.Scope(False, ids),
                            common.Keep(), alloc)
    res2.touched = sorted(set(res.touched) | set(res2.touched), key=res2.bodies.ids().index)
    res2.created = [i for i in res.created + res2.created if i in res2.bodies]
    res2.warnings = res.warnings + res2.warnings
    return res2


# ------------------------------------------------------------------ Mounting Boss

class BossParams(object):
    def __init__(self):
        self.face = None            # the Part.Face it stands on
        self.point = None           # where on the face
        self.reverse = False
        self.kind = HOLE
        self.height = 10.0          # from the face
        self.diameter = 8.0         # at the face
        self.draft = 1.0            # degrees, on the boss's outside
        self.hole_diameter = 3.0
        self.hole_depth = 8.0       # from the boss's top
        self.hole_draft = 0.5
        self.pin_diameter = 3.0
        self.pin_height = 4.0
        self.fins = 0
        self.fin_length = 4.0       # out from the boss's wall
        self.fin_height = 6.0       # from the face
        self.fin_thickness = 1.0
        self.fin_angle = 0.0        # the first fin's direction, about the boss
        self.feature = "MountingBoss"
        self.tag = 1
        self.alloc = None


def boss_tools(p):
    """(material to add, material to cut or None), in place."""
    if p.face is None or p.point is None:
        raise topo.GeometryError("Click on a face where the boss goes.")
    if p.height <= 0 or p.diameter <= 0:
        raise topo.GeometryError("The boss needs a height and a diameter.")
    n = normal_at(p.face, p.point)
    if p.reverse:
        n = -n
    x, y, z = frame(n, None, p.fin_angle)
    R = p.diameter / 2.0
    reach = R + (p.fin_length if p.fins else 0.0)
    emb = embed_depth(p.face, p.point, z, reach)
    t = math.tan(math.radians(p.draft))
    r_top = R - p.height * t
    if r_top <= 0:
        raise topo.GeometryError("The draft closes the boss before its top; use less draft.")
    pieces = [_frustum(R + emb * t, r_top, -emb, p.height)]
    cut = None
    if p.kind == HOLE:
        if p.hole_diameter <= 0 or p.hole_depth <= 0:
            raise topo.GeometryError("The hole needs a diameter and a depth.")
        rh = p.hole_diameter / 2.0
        if rh >= r_top - 1e-6:
            raise topo.GeometryError("The hole is as wide as the boss's top; make it smaller "
                                     "or the boss wider.")
        rb = rh - p.hole_depth * math.tan(math.radians(p.hole_draft))
        if rb <= 0:
            raise topo.GeometryError("The hole's draft closes it before its depth.")
        cut = _frustum(rb, rh, p.height - p.hole_depth, p.height + 1e-3 * p.height)
    else:
        if p.pin_diameter <= 0 or p.pin_height <= 0:
            raise topo.GeometryError("The pin needs a diameter and a height.")
        if p.pin_diameter / 2.0 >= r_top + 1e-9:
            raise topo.GeometryError("The pin is wider than the boss's top.")
        pieces.append(_frustum(p.pin_diameter / 2.0, p.pin_diameter / 2.0, p.height - 1e-3,
                               p.height + p.pin_height))
    if p.fins:
        if p.fin_height > p.height + 1e-9:
            raise topo.GeometryError("The fins are taller than the boss.")
        if p.fin_thickness <= 0 or p.fin_length <= 0 or p.fin_height <= 0:
            raise topo.GeometryError("The fins need a length, a height and a thickness.")
        x0 = 0.5 * R
        for i in range(int(p.fins)):
            a = 360.0 * i / int(p.fins)
            fin = Part.makeBox(R + p.fin_length - x0, p.fin_thickness, p.fin_height + emb,
                               V(x0, -p.fin_thickness / 2.0, -emb))
            fin.rotate(V(), V(0, 0, 1), a)
            pieces.append(fin)
    add = pieces[0] if len(pieces) == 1 else topo.fuse(pieces[0], pieces[1:], p.tag)
    add = placed(topo.refine(add, p.tag), p.point, x, y, z)
    if cut is not None:
        cut = placed(cut, p.point, x, y, z)
    return topo.tagged(add, p.tag), (topo.tagged(cut, p.tag) if cut is not None else None)


def mounting_boss(p, base):
    add, cut = boss_tools(p)
    res = _add_then_cut(base, add, cut, p.feature, p.tag, p.alloc)
    return res, add


# ------------------------------------------------------------------ Snap Hook

class HookParams(object):
    def __init__(self):
        self.face = None
        self.point = None
        self.reverse = False
        self.direction = None       # the way the hook points (in the face's plane)
        self.angle = 0.0            # turns the hook about the face's normal
        self.height = 15.0          # total, face to the hook's top
        self.thickness = 2.0        # the beam, along the hook's direction
        self.width = 6.0            # across
        self.overhang = 1.5         # how far the hook sticks out past the beam
        self.lip_height = 3.0       # the hook's height (catch face to top)
        self.feature = "SnapHook"
        self.tag = 1
        self.alloc = None


def hook_tool(p):
    if p.face is None or p.point is None:
        raise topo.GeometryError("Click on a face where the snap hook goes.")
    for name in ("height", "thickness", "width", "overhang", "lip_height"):
        if getattr(p, name) <= 0:
            raise topo.GeometryError("The snap hook's {} must be more than zero."
                                     .format(name.replace("_", " ")))
    if p.lip_height >= p.height:
        raise topo.GeometryError("The hook is taller than the whole snap hook.")
    n = normal_at(p.face, p.point)
    if p.reverse:
        n = -n
    x, y, z = frame(n, p.direction, p.angle)
    reach = math.hypot(p.thickness + p.overhang, p.width / 2.0)
    emb = embed_depth(p.face, p.point, z, reach)
    T, H, O, L = p.thickness, p.height, p.overhang, p.lip_height
    catch = H - L
    flat = min(0.2 * L, 0.5)            # a short square face at the hook's tip
    pts = [V(0, 0, -emb), V(T, 0, -emb), V(T, 0, catch), V(T + O, 0, catch),
           V(T + O, 0, catch + flat), V(T, 0, H), V(0, 0, H)]
    prof = Part.Face(Part.makePolygon(pts + [pts[0]]))
    prof.translate(V(-T / 2.0, -p.width / 2.0, 0))
    solid = prof.extrude(V(0, p.width, 0))
    return topo.tagged(placed(solid, p.point, x, y, z), p.tag)


def snap_hook(p, base):
    tool = hook_tool(p)
    res = common.apply_add(base, tool, p.feature, p.tag, True, common.Scope(), p.alloc)
    return res, tool


# ------------------------------------------------------------------ Lip/Groove

class LipParams(object):
    def __init__(self):
        self.lip_body = ""
        self.groove_body = ""
        self.face = None            # the flat face of the lip body where they meet
        self.offset = 0.5           # the lip's distance in from the face's outer edge
        self.width = 1.0            # the lip's width
        self.height = 1.5           # how far the lip stands out
        self.gap = 0.1              # clearance round the lip, in the groove
        self.feature = "LipGroove"
        self.tag = 1
        self.alloc = None


def _ring(face, outer, inner):
    """The part of a flat face between ``outer`` and ``inner`` in from its outer edge."""
    w = face.OuterWire

    def shrunk(d):
        if d <= 1e-9:
            return Part.Face(w)
        try:
            o = w.makeOffset2D(-d, 0, False, False, False)
            return Part.Face(o.Wires[0]) if o.Wires else None
        except Exception:
            raise topo.GeometryError("The face is too small for the lip's offset and width.")
    a = shrunk(outer)
    b = shrunk(inner)
    if a is None:
        raise topo.GeometryError("The lip's offset is wider than the face.")
    ring = a.cut(b) if b is not None and b.Area > 1e-9 else a
    ring = ring.common(face)
    if not ring.Faces or ring.Area < 1e-9:
        raise topo.GeometryError("The lip falls outside the face: make the offset or the "
                                 "width smaller.")
    return ring


def lip_groove_tools(p, base):
    if not p.lip_body or not p.groove_body:
        raise topo.GeometryError("Pick the body that gets the groove and the one that gets "
                                 "the lip.")
    if p.lip_body == p.groove_body:
        raise topo.GeometryError("The lip and the groove go on two different bodies.")
    for bid in (p.lip_body, p.groove_body):
        if bid not in base:
            raise topo.GeometryError("A body picked for the lip or groove no longer exists.")
    f = p.face
    if f is None or f.Surface.TypeId != "Part::GeomPlane":
        raise topo.GeometryError("Pick the flat face of the lip body where the two bodies "
                                 "meet.")
    if p.width <= 0 or p.height <= 0 or p.gap < 0 or p.offset < 0:
        raise topo.GeometryError("The lip needs a width and a height.")
    lip_shape = base.get(p.lip_body).shape
    n = f.normalAt(0, 0)
    c = f.CenterOfMass
    # Outward from the lip body (towards the groove body).
    if lip_shape.isInside(c + n * 1e-3 * max(f.BoundBox.DiagonalLength, 1.0), 1e-9, False):
        n = -n
    lip_face = _ring(f, p.offset, p.offset + p.width)
    lip = lip_face.extrude(n * p.height)
    # The groove: the lip's ring widened by the gap, and as much deeper; cut from a hair
    # behind the face so it opens cleanly.
    g_face = _ring(f, max(p.offset - p.gap, 0.0), p.offset + p.width + p.gap)
    back = 1e-3 * max(p.height, 1.0)
    g_face.translate(-n * back)
    groove = g_face.extrude(n * (p.height + p.gap + back))
    return topo.tagged(lip, p.tag), topo.tagged(groove, p.tag)


def lip_groove(p, base):
    lip, groove = lip_groove_tools(p, base)
    res = common.apply_add(base, lip, p.feature, p.tag, True,
                           common.Scope(False, [p.lip_body]), p.alloc)
    if p.lip_body not in res.touched:
        raise topo.GeometryError("The lip doesn't stand on the lip body's face.")
    res2 = common.apply_cut(res.bodies, groove, p.feature, p.tag,
                            common.Scope(False, [p.groove_body]), common.Keep(), p.alloc)
    if p.groove_body not in res2.touched:
        res2.warnings.append("The groove doesn't reach the groove body: the bodies don't "
                             "meet at the face.")
    res2.touched = [i for i in res2.bodies.ids() if i in (p.lip_body, p.groove_body)]
    return res2, topo.compound([lip, groove], p.tag)


# ------------------------------------------------------------------ Vent

class VentParams(object):
    def __init__(self):
        self.shape = None           # the sketch's shape
        self.normal = V(0, 0, 1)    # the sketch's normal
        self.depth = 3.0            # how deep the vent cuts
        self.reverse = False
        self.rib_width = 1.0
        self.spar_width = 1.0
        self.inner = SPARS          # inner loops: rings of material, or kept solid
        self.feature = "Vent"
        self.tag = 1
        self.alloc = None


def vent_tool(p, base):
    if p.shape is None or not p.shape.Edges:
        raise topo.GeometryError("Pick the vent's sketch: a closed boundary, with lines "
                                 "for ribs and inner loops for spars.")
    if p.depth <= 0:
        raise topo.GeometryError("The vent needs a depth.")
    closed = [w for w in p.shape.Wires if w.isClosed()]
    if not closed:
        raise topo.GeometryError("The vent's sketch needs a closed boundary.")
    faces = []
    for w in closed:
        try:
            faces.append(Part.Face(w))
        except Exception:
            pass
    if not faces:
        raise topo.GeometryError("The vent's boundary isn't flat.")
    faces.sort(key=lambda f: -f.Area)
    boundary = faces[0]
    inner = [f for f in faces[1:] if boundary.common(f).Area > 0.999 * f.Area]
    ribs = [e for e in p.shape.Edges
            if not any(e.isSame(x) for w in closed for x in w.Edges)]
    keep = []
    for e in ribs:
        if p.rib_width <= 0:
            raise topo.GeometryError("The ribs need a width.")
        keep.append(_band(e, p.rib_width, boundary))
    for f in inner:
        if p.inner == FILL_IN:
            keep.append(f)
        else:
            if p.spar_width <= 0:
                raise topo.GeometryError("The spars need a width.")
            for e in f.Edges:
                keep.append(_band(e, p.spar_width, boundary))
    open_face = boundary
    if keep:
        keep = [k for k in keep if k is not None and k.Faces]
        if keep:
            solid = keep[0].fuse(keep[1:]) if len(keep) > 1 else keep[0]
            open_face = boundary.cut(solid)
    if not open_face.Faces:
        raise topo.GeometryError("The ribs and spars fill the whole vent.")
    n = _unit(p.normal)
    best = None
    back = 1e-3 * p.depth
    # Into the wall: away from the sketch's normal unless reversed; the other way when
    # that misses every body.
    for d in ((n, -n) if p.reverse else (-n, n)):
        f = open_face.copy()
        f.translate(-d * back)
        tool = f.extrude(d * (p.depth + back))
        hit = sum(topo.overlap_volume(b.shape, tool) for b in base if b.shape.Solids)
        if best is None or hit > best[0] + 1e-9:
            best = (hit, tool)
        if hit > 1e-9:
            break
    if best[0] <= 1e-9:
        raise topo.GeometryError("The vent doesn't cut into any body: put its sketch on a "
                                 "face of the wall.")
    return topo.tagged(best[1], p.tag)


def _band(edge, width, boundary):
    """A strip ``width`` wide along an edge, in the boundary's plane, clipped to it."""
    try:
        w = Part.Wire([edge])
        if w.isClosed():
            # A whole circle (or other closed curve): the ring either side of it.
            a = Part.Face(w.makeOffset2D(width / 2.0).Wires[0])
            inner = w.makeOffset2D(-width / 2.0)
            f = a.cut(Part.Face(inner.Wires[0])) if inner.Wires else a
        else:
            # A strip either side of the curve, in the boundary's plane.
            n = boundary.normalAt(0, 0)
            straight = edge.Curve.TypeId in ("Part::GeomLine", "Part::GeomLineSegment")
            k = 2 if straight else max(16, int(edge.Length / max(width / 4.0, 1e-3)))
            k = min(k, 200)
            ts = [edge.FirstParameter + (edge.LastParameter - edge.FirstParameter) * i /
                  float(k - 1) for i in range(k)]
            left, right = [], []
            for t in ts:
                q = edge.valueAt(t)
                d = edge.tangentAt(t)
                side = n.cross(d)
                side.normalize()
                left.append(q + side * (width / 2.0))
                right.append(q - side * (width / 2.0))
            # Run on a little past the ends, so a rib reaches right across.
            d0, d1 = edge.tangentAt(ts[0]), edge.tangentAt(ts[-1])
            ext = width
            left[0] = left[0] - d0 * ext
            right[0] = right[0] - d0 * ext
            left[-1] = left[-1] + d1 * ext
            right[-1] = right[-1] + d1 * ext
            loop = left + list(reversed(right))
            f = Part.Face(Part.makePolygon(loop + [loop[0]]))
    except Exception:
        f = None
    if f is None:
        return None
    return f.common(boundary)


def vent(p, base):
    tool = vent_tool(p, base)
    res = common.apply_cut(base, tool, p.feature, p.tag, common.Scope(), common.Keep(),
                           p.alloc)
    if not res.touched:
        raise topo.GeometryError("The vent doesn't cut into any body.")
    return res, tool
