# SPDX-License-Identifier: LGPL-2.1-or-later
"""Scale and Flex (SolidWorks' Insert > Features > Scale, Flex).

Scale: uniform (about the centroid, the origin or a coordinate system) keeps
every surface's kind; non-uniform turns them into B-splines.

Flex bends, twists, tapers or stretches bodies between two trim planes across a
flex axis. The body becomes B-spline geometry; each surface's control net is
refined, then every control point (and every edge's 2D curve stays as it was in
the surface's parameters) is moved by the deformation, and the faces are sewn
back into a solid.
"""

import math

import FreeCAD as App
import Part

from .. import topo
from ..bodies import SOLID
from . import common

V = App.Vector
BENDING, TWISTING, TAPERING, STRETCHING = "Bending", "Twisting", "Tapering", "Stretching"
FLEX_TYPES = [BENDING, TWISTING, TAPERING, STRETCHING]
CENTROID, ORIGIN, CSYS = "Centroid", "Origin", "Coordinate System"
SCALE_ABOUT = [CENTROID, ORIGIN, CSYS]


# ------------------------------------------------------------------ scale

def scaled(shape, about, factors, tag):
    """``factors``: one number, or (x, y, z) in the frame ``about`` (a Placement)."""
    if isinstance(factors, (int, float)):
        if factors <= 0:
            raise topo.GeometryError("The scale factor must be greater than zero.")
        out = shape.copy()
        out.scale(factors, about.Base)
        return topo.tagged(out, tag)
    fx, fy, fz = factors
    if min(fx, fy, fz) <= 0:
        raise topo.GeometryError("The scale factors must be greater than zero.")
    m = App.Matrix()
    m.scale(fx, fy, fz)
    to = about.toMatrix()
    t = to.multiply(m).multiply(to.inverse())
    try:
        out = shape.transformGeometry(t)
    except Exception as e:
        raise topo.GeometryError("Scaling failed: {}".format(topo._msg(e)))
    return topo.tagged(out, tag)


def mass_centre(shape):
    """The centre of mass of a body's solids (a compound has no CenterOfMass of its
    own), else the middle of its bounding box."""
    solids = shape.Solids
    if not solids:
        return shape.BoundBox.Center
    if len(solids) == 1:
        return solids[0].CenterOfMass
    total = sum(s.Volume for s in solids)
    if total <= 0:
        return shape.BoundBox.Center
    c = App.Vector()
    for s in solids:
        c += s.CenterOfMass * (s.Volume / total)
    return c


def scale(base, ids, about_kind, about_pl, factors, feature, tag):
    out = base.copy()
    res = common.Result(out)
    for bid in ids:
        b = base.get(bid)
        if b is None:
            raise topo.GeometryError("A body to scale no longer exists. Re-pick it.")
        pl = about_pl
        if about_kind == CENTROID:
            c = mass_centre(b.shape)
            pl = App.Placement(c, about_pl.Rotation)
        out.replace(bid, scaled(b.shape, pl, factors, tag), feature)
        res.touched.append(bid)
    if not res.touched:
        raise topo.GeometryError("Pick the bodies to scale.")
    return res


# ------------------------------------------------------------------ flex

class Flex(object):
    """The deformation, in a frame whose z is the flex axis; between z = a and b."""

    def __init__(self, kind, frame, a, b, angle=0.0, factor=1.0, stretch=0.0):
        self.kind = kind
        self.to = frame.toMatrix()
        self.back = self.to.inverse()
        self.a, self.b = a, b
        self.L = b - a
        if self.L <= 1e-9:
            raise topo.GeometryError("The trim planes must be apart along the flex axis.")
        self.angle = math.radians(angle)
        self.factor = factor
        self.stretch = stretch

    def local(self, p):
        x, y, z = p.x, p.y, p.z
        a, b, L = self.a, self.b, self.L
        if self.kind == STRETCHING:
            s = (L + self.stretch) / L
            if z <= a:
                return V(x, y, z)
            if z >= b:
                return V(x, y, z + self.stretch)
            return V(x, y, a + (z - a) * s)
        t = min(max((z - a) / L, 0.0), 1.0)
        if self.kind == TWISTING:
            phi = self.angle * t
            c, s = math.cos(phi), math.sin(phi)
            return V(x * c - y * s, x * s + y * c, z)
        if self.kind == TAPERING:
            k = 1 + (self.factor - 1) * t
            return V(x * k, y * k, z)
        # Bending round an axis parallel to y, at x = R, through the bent length.
        th = self.angle
        if abs(th) < 1e-12:
            return V(x, y, z)
        R = L / th
        if z <= a:
            return V(x, y, z)
        zz = min(z, b)
        phi = (zz - a) / R
        xb = R - (R - x) * math.cos(phi)
        zb = a + (R - x) * math.sin(phi)
        if z > b:
            # Past the second trim plane: carried on rigidly, turned by the angle.
            d = z - b
            xb += d * math.sin(th)
            zb += d * math.cos(th)
        return V(xb, y, zb)

    def __call__(self, p):
        return self.to.multVec(self.local(self.back.multVec(p)))


def _refined(bs, size, segs):
    """A B-spline surface with knots added so no span is longer than size/segs."""
    s = bs.copy()
    for get, ins, ra in ((s.getUKnots, s.insertUKnot, 0), (s.getVKnots, s.insertVKnot, 1)):
        ks = list(get())
        for k0, k1 in zip(ks[:-1], ks[1:]):
            mid_u = 0.5 * (k0 + k1)
            try:
                if ra == 0:
                    a = s.value(k0, s.getVKnots()[0])
                    b = s.value(k1, s.getVKnots()[0])
                else:
                    a = s.value(s.getUKnots()[0], k0)
                    b = s.value(s.getUKnots()[0], k1)
                span = max((b - a).Length, size / segs)
            except Exception:
                span = size
            n = min(int(span / (size / segs)) + 1, 64)
            for j in range(1, n):
                try:
                    ins(k0 + (k1 - k0) * j / float(n), 1, 1e-9)
                except Exception:
                    pass
            _ = mid_u
    return s


def _refine_near(s, focus):
    """More knots where the change is (within ``focus`` = (centre, radius)): a small
    bump needs a fine control net there to reach its full height."""
    c, r = focus
    u0, u1, v0, v1 = s.bounds()
    n = 40
    us, vs = [], []
    seen = []
    for i in range(n + 1):
        for j in range(n + 1):
            u = u0 + (u1 - u0) * i / n
            v = v0 + (v1 - v0) * j / n
            if (s.value(u, v) - c).Length < 1.3 * r:
                us.append(u)
                vs.append(v)
                seen.append((i, j))
    if not us:
        return s
    step = r / 24.0
    for get, ins, lo, hi, axis in ((s.getUKnots, s.insertUKnot, min(us), max(us), 0),
                                   (s.getVKnots, s.insertVKnot, min(vs), max(vs), 1)):
        pad = ((u1 - u0) if axis == 0 else (v1 - v0)) / n
        lo, hi = max(lo - pad, u0 if axis == 0 else v0), min(hi + pad, u1 if axis == 0 else v1)
        mid_other = 0.5 * (v0 + v1) if axis == 0 else 0.5 * (u0 + u1)
        try:
            a = s.value(lo, mid_other) if axis == 0 else s.value(mid_other, lo)
            b = s.value(hi, mid_other) if axis == 0 else s.value(mid_other, hi)
            span3 = max((b - a).Length, 2 * r)
        except Exception:
            span3 = 2 * r
        k = min(int(span3 / step) + 1, 96)
        known = list(get())
        for j in range(1, k):
            t = lo + (hi - lo) * j / float(k)
            if any(abs(t - x) < 1e-9 * max(1.0, abs(x)) for x in known):
                continue
            try:
                ins(t, 1, 1e-9)
            except Exception:
                pass
    return s


def _flex_face(face, fn, size, segs, focus=None):
    nf = face
    try:
        s = face.Surface
        if s.TypeId != "Part::GeomBSplineSurface":
            nf = face.toNurbs().Faces[0]
            s = nf.Surface
        else:
            s = s.copy()
    except TypeError:
        # A surface FreeCAD can't hand over as it is (seen on faces already
        # deformed once): its B-spline form.
        nf = face
        s = face.Surface.toBSpline()
    if s.TypeId != "Part::GeomBSplineSurface":
        s = s.toBSpline()
    natural = False
    try:
        full = Part.Face(s)
        natural = abs(full.Area - nf.Area) < 1e-7 * max(nf.Area, 1.0) and \
            len(nf.Wires) == 1
    except Exception:
        pass
    if s.UDegree < 3 or s.VDegree < 3:
        s.increaseDegree(max(s.UDegree, 3), max(s.VDegree, 3))
    s = _refined(s, size, segs)
    if focus is not None:
        # Only where the change stays inside the face: refined on its own, a face's
        # edge would no longer match its neighbour's.
        c, r = focus
        try:
            inside = Part.makeCompound(face.Edges).distToShape(Part.Vertex(c))[0] > 1.3 * r
        except Exception:
            inside = False
        if inside:
            s = _refine_near(s, focus)
    poles = s.getPoles()
    for i, row in enumerate(poles):
        for j, p in enumerate(row):
            s.setPole(i + 1, j + 1, fn(p))
    if natural:
        # The face is its whole surface (a cylinder's side, a box face): no
        # trimming to carry over, and no seam to rebuild.
        out = Part.Face(s)
        if nf.Orientation == "Reversed":
            out.reverse()
        return out
    wires = []
    for w in nf.Wires:
        edges = []
        for e in w.OrderedEdges:
            r = nf.curveOnSurface(e)
            if not r:
                raise topo.GeometryError("Couldn't flex an edge.")
            c2d, first, last = r[0], r[-2], r[-1]
            edges.append(c2d.toShape(s, first, last))
        wires.append(Part.Wire(edges))
    out = Part.Face(s, wires[0])
    if len(wires) > 1:
        out.cutHoles(wires[1:])
    if nf.Orientation == "Reversed":
        out.reverse()
    return out


def flexed(shape, fn, tag, segs=48, face_fn=None, focus=None):
    """``shape`` with every control point moved by ``fn``. ``face_fn(face)`` (when
    given) picks the function per face instead; None leaves that face as it is
    (a deformation that is zero on its edges)."""
    size = shape.BoundBox.DiagonalLength
    faces = []
    for f in shape.Faces:
        g = fn if face_fn is None else face_fn(f)
        faces.append(f if g is None else _flex_face(f, g, size, segs, focus))
    sh = Part.Shell(faces)
    try:
        sh.sewShape(1e-4 * size)
    except TypeError:
        sh.sewShape()
    shells = sh.Shells if sh.ShapeType != "Shell" else [sh]
    if shape.Solids:
        if len(shells) != 1 or not shells[0].isClosed():
            raise topo.GeometryError("The changed faces didn't close into a solid; try a "
                                     "smaller change.")
        so = Part.Solid(shells[0])
        if so.Volume < 0:
            so.reverse()
        try:
            so.fix(1e-7, 1e-7, 1e-7)
        except Exception:
            pass
        return topo.tagged(so, tag)
    return topo.tagged(shells[0] if len(shells) == 1 else Part.makeCompound(shells), tag)


def flex(base, ids, make_fn, feature, tag):
    out = base.copy()
    res = common.Result(out)
    for bid in ids:
        b = base.get(bid)
        if b is None:
            raise topo.GeometryError("A body to flex no longer exists. Re-pick it.")
        fn = make_fn(b.shape)
        out.replace(bid, flexed(b.shape, fn, tag), feature)
        res.touched.append(bid)
    if not res.touched:
        raise topo.GeometryError("Pick the bodies to flex.")
    return res


def default_frame(shape):
    """The flex triad: at the body's centre, its z along the body's longest side."""
    bb = shape.BoundBox
    c = shape.CenterOfMass if shape.Solids else bb.Center
    dims = [(bb.XLength, V(1, 0, 0)), (bb.YLength, V(0, 1, 0)), (bb.ZLength, V(0, 0, 1))]
    dims.sort(key=lambda t: -t[0])
    z = dims[0][1]
    x = dims[1][1]
    rot = App.Rotation(x, z.cross(x), z, "ZXY")
    return App.Placement(c, rot)


def extent(shape, frame):
    """The body's z range in the frame."""
    back = frame.inverse()
    zs = [back.multVec(v.Point).z for v in shape.Vertexes]
    bb = shape.BoundBox
    for x in (bb.XMin, bb.XMax):
        for y in (bb.YMin, bb.YMax):
            for z in (bb.ZMin, bb.ZMax):
                zs.append(back.multVec(V(x, y, z)).z)
    return min(zs), max(zs)
