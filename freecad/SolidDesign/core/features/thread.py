# SPDX-License-Identifier: LGPL-2.1-or-later
"""Thread (SolidWorks' Thread): a modelled helical thread on a cylindrical face,
started from one of its circular edges.

- **Cut Thread** cuts the groove into the cylinder (a shaft's outside, or a hole's
  inside); **Extrude Thread** grows the ridge out of it.
- The profile is the 60° basic form (ISO 68-1), its depth from the size's pitch.
- End condition: Blind (a length), Revolutions, or Up To Selection (a face,
  plane or vertex). The thread is trimmed square at both ends.
- Right- or left-hand, one or more starts, an offset from the edge.
"""

import math

import FreeCAD as App
import Part

from .. import threads, topo
from ..bodies import SOLID
from . import common, edges as edgemod

CUT, EXTRUDE = "Cut Thread", "Extrude Thread"
METHODS = [CUT, EXTRUDE]
BLIND, REVOLUTIONS, UP_TO = "Blind", "Revolutions", "Up To Selection"
END_CONDITIONS = [BLIND, REVOLUTIONS, UP_TO]

TAN30 = math.tan(math.radians(30))


class Params(object):
    def __init__(self):
        self.edge = None            # a circular edge of the model before
        self.offset = 0.0           # start this far from the edge (along the thread)
        self.reverse_offset = False
        self.end = BLIND
        self.length = 10.0
        self.revolutions = 5.0
        self.up_to = None           # shape: face, plane or vertex
        self.pitch = 1.0
        self.method = CUT
        self.left_hand = False
        self.starts = 1
        self.reverse = False        # thread the other way from the edge
        self.feature = "Thread"
        self.tag = 1


class Site(object):
    """Where a thread goes: the cylinder, its axis, and which side the material is."""

    def __init__(self, bid, centre, radius, axis, internal):
        self.bid = bid
        self.centre = centre        # on the edge's plane
        self.radius = radius
        self.axis = axis            # unit, from the edge along the cylinder
        self.internal = internal    # a hole (material outside the cylinder)


def site(base, edge, reverse=False):
    """Find the body, cylinder and thread direction for a picked circular edge."""
    c = edge.Curve
    if not (hasattr(c, "Radius") and hasattr(c, "Center")):
        raise topo.GeometryError("Pick a circular edge of a cylinder (a shaft's end, or a "
                                 "hole's rim).")
    hit = None
    for b in base:
        found = edgemod.find_in(b.shape, edge)
        if found is not None:
            hit = (b, found)
            break
    if hit is None:
        raise topo.GeometryError("The thread's edge isn't on any body before this feature. "
                                 "Re-pick it.")
    body, e = hit
    if body.kind != SOLID:
        raise topo.GeometryError("Threads go on solid bodies.")
    centre, axis, r = App.Vector(c.Center), App.Vector(c.Axis), float(c.Radius)
    axis.normalize()
    cyl = None
    for f in body.shape.ancestorsOfType(e, Part.Face):
        s = f.Surface
        if s.TypeId == "Part::GeomCylinder" and abs(s.Radius - r) < 1e-6:
            cyl = f
            break
    if cyl is None:
        raise topo.GeometryError("The edge isn't the end of a cylindrical face. Pick the rim "
                                 "of a shaft or a hole.")
    mid = cyl.CenterOfMass
    d = axis if (mid - centre).dot(axis) >= 0 else -axis
    # Outward normal of the face: towards the axis means a hole.
    u, v = cyl.Surface.parameter(mid)
    n = cyl.normalAt(u, v)
    radial = (mid - centre) - d * (mid - centre).dot(d)
    internal = n.dot(radial) < 0
    return Site(body.id, centre, r, -d if reverse else d, internal)


def length_of(p, s, start):
    if p.end == BLIND:
        L = p.length
    elif p.end == REVOLUTIONS:
        L = p.revolutions * p.pitch * p.starts      # turns of the helix: one lead each
    else:
        if p.up_to is None:
            raise topo.GeometryError("Pick the face, plane or vertex the thread goes up to.")
        L = _distance_to(p.up_to, start, s.axis)
    if L <= 1e-6:
        raise topo.GeometryError("The thread has no length: check the end condition.")
    return L


def _distance_to(shape, start, d):
    if shape.ShapeType == "Vertex" or (not shape.Faces and len(shape.Vertexes) == 1):
        return (shape.Vertexes[0].Point - start).dot(d)
    faces = [shape] if shape.ShapeType == "Face" else shape.Faces
    f = faces[0]
    if f.Surface.TypeId == "Part::GeomPlane":
        n = f.normalAt(0, 0)
        den = d.dot(n)
        if abs(den) < 1e-9:
            raise topo.GeometryError("The end face is parallel to the thread; it never reaches "
                                     "it.")
        return (f.Vertexes[0].Point - start).dot(n) / den
    ray = Part.LineSegment(start, start + d * 1e5).toShape()
    pts = [v.Point for v in ray.section(f).Vertexes]
    if not pts:
        raise topo.GeometryError("The thread never reaches the end face.")
    return min((q - start).dot(d) for q in pts)


def compute(p, base):
    if p.pitch <= 0:
        raise topo.GeometryError("The pitch must be greater than zero.")
    if p.starts < 1:
        raise topo.GeometryError("A thread has at least one start.")
    if p.edge is None:
        raise topo.GeometryError("Pick the circular edge where the thread starts.")
    s = site(base, p.edge, p.reverse)
    off = -p.offset if p.reverse_offset else p.offset
    start = s.centre + s.axis * off
    L = length_of(p, s, start)
    h = threads.depth(p.pitch, s.internal)
    # Which way the profile grows from the cylinder: into the material to cut,
    # out of it to extrude.
    into_material = -1.0 if not s.internal else 1.0       # radial sign
    sign = into_material if p.method == CUT else -into_material
    if sign < 0 and h >= s.radius:
        raise topo.GeometryError("The thread is deeper than the cylinder's radius.")
    tool = _tool(s, start, L, p.pitch, h, sign, p.left_hand, p.starts, p.tag)
    body = base.get(s.bid)
    shape = topo.tagged(body.shape, p.tag)
    if p.method == CUT:
        r = topo.cut(shape, [tool], p.tag)
    else:
        r = topo.fuse(shape, [tool], p.tag)
    solids = r.Solids
    if not solids or not r.isValid():
        raise topo.GeometryError("The thread made an invalid solid. Try another pitch or "
                                 "length.")
    r = solids[0] if len(solids) == 1 else r
    out = base.copy()
    out.replace(s.bid, r, p.feature)
    res = common.Result(out)
    res.touched.append(s.bid)
    return res, tool, s


def _tool(s, start, L, pitch, h, sign, left, starts, tag):
    """The thread's material (to cut or add): profiles swept along helices, trimmed
    square to [start, start + L]."""
    r = s.radius
    d = s.axis
    x = _perp(d)
    lead = pitch * starts
    over = 0.1 * pitch
    # Profile in the (radial, axial) plane: narrow flat (p/8) at depth h, wider at
    # the cylinder, carried a little past it so the boolean is clean.
    flat = pitch / 8.0
    w_surf = flat / 2.0 + h * TAN30
    w_over = w_surf + over * TAN30
    far = r + sign * h
    near = r - sign * over
    z0 = -lead                  # start a turn early; trimmed below
    pts2d = [(far, -flat / 2.0), (far, flat / 2.0), (near, w_over), (near, -w_over)]
    height = L + 2 * lead
    frame = App.Placement(_matrix(start, x, d))
    pieces = []
    for k in range(starts):
        ang = 360.0 * k / starts
        rot = App.Rotation(App.Vector(0, 0, 1), ang)
        pts = [rot.multVec(App.Vector(rr, 0, z0 + zz)) for rr, zz in pts2d]
        prof = Part.makePolygon(pts + [pts[0]])
        helix = Part.makeHelix(lead, height, r, 0.0, bool(left))
        helix.rotate(App.Vector(), App.Vector(0, 0, 1), ang)
        helix.translate(App.Vector(0, 0, z0))
        prof.transformShape(frame.toMatrix(), True)
        helix.transformShape(frame.toMatrix(), True)
        ax = (frame.multVec(App.Vector(0, 0, z0)), frame.multVec(App.Vector(0, 0, z0 + height)))
        sw = topo.sweep(Part.Wire(helix.Edges), prof, tag, True, None, ax)
        if not sw.Solids:
            raise topo.GeometryError("The thread's sweep made no solid.")
        pieces.append(sw)
    tool = pieces[0] if len(pieces) == 1 else topo.fuse(pieces[0], pieces[1:], tag)
    big = r + h + 2 * pitch
    slab = Part.makeCylinder(big, L, start, d)
    trimmed = topo.common(tool, [slab], tag)
    if not trimmed.Solids:
        raise topo.GeometryError("The thread came out empty.")
    return trimmed


def _perp(d):
    a = App.Vector(1, 0, 0) if abs(d.x) < 0.9 else App.Vector(0, 1, 0)
    x = a - d * a.dot(d)
    x.normalize()
    return x


def _matrix(o, x, z):
    y = z.cross(x)
    return App.Matrix(x.x, y.x, z.x, o.x,
                      x.y, y.y, z.y, o.y,
                      x.z, y.z, z.z, o.z,
                      0, 0, 0, 1)
