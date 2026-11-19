# SPDX-License-Identifier: LGPL-2.1-or-later
"""Curves (SolidWorks' Helix and Spiral), as pure functions of resolved shapes."""

import math

import FreeCAD as App
import Part

from . import topo

PITCH_REVS = "Pitch and Revolution"
HEIGHT_REVS = "Height and Revolution"
HEIGHT_PITCH = "Height and Pitch"
SPIRAL = "Spiral"
HELIX_TYPES = [PITCH_REVS, HEIGHT_REVS, HEIGHT_PITCH, SPIRAL]


def circle_of(shape, what="circle"):
    """(centre, radius, unit axis, unit x direction) of one circular edge, or of
    a sketch holding one circle."""
    edges = [shape] if shape.ShapeType == "Edge" else shape.Edges
    circles = [e for e in edges if hasattr(e.Curve, "Radius") and hasattr(e.Curve, "Center")]
    if len(circles) != 1:
        raise topo.GeometryError("The {} must be one circle (a circular edge, or a sketch "
                                 "with one circle).".format(what))
    c = circles[0].Curve
    axis = App.Vector(c.Axis)
    axis.normalize()
    try:
        x = App.Vector(c.XAxis)
    except Exception:
        x = App.Vector(1, 0, 0) if abs(axis.x) < 0.9 else App.Vector(0, 1, 0)
    x = x - axis * x.dot(axis)
    x.normalize()
    return App.Vector(c.Center), float(c.Radius), axis, x


def numbers(kind, pitch, revs, height):
    """(pitch, revolutions, height) from the two the type uses."""
    if kind == PITCH_REVS or kind == SPIRAL:
        if pitch <= 0 or revs <= 0:
            raise topo.GeometryError("The pitch and revolutions must be greater than zero.")
        return pitch, revs, pitch * revs
    if kind == HEIGHT_REVS:
        if height <= 0 or revs <= 0:
            raise topo.GeometryError("The height and revolutions must be greater than zero.")
        return height / revs, revs, height
    if kind == HEIGHT_PITCH:
        if height <= 0 or pitch <= 0:
            raise topo.GeometryError("The height and pitch must be greater than zero.")
        return pitch, height / pitch, height
    raise topo.GeometryError("Unknown helix type " + str(kind))


def frame(centre, axis, x, reverse=False, start_angle=0.0):
    """Placement of a helix: origin at the circle's centre, Z along its axis
    (or against it), X turned by the start angle."""
    z = -axis if reverse else App.Vector(axis)
    x = App.Rotation(z, start_angle).multVec(x)
    y = z.cross(x)
    m = App.Matrix(x.x, y.x, z.x, centre.x,
                   x.y, y.y, z.y, centre.y,
                   x.z, y.z, z.z, centre.z,
                   0, 0, 0, 1)
    return App.Placement(m)


def helix(circle, kind=PITCH_REVS, pitch=5.0, revs=4.0, height=20.0, reverse=False,
          start_angle=0.0, clockwise=False, taper=0.0, tag=1):
    """The helix (or spiral) wire, placed. ``taper``: degrees, positive outward."""
    centre, r, axis, x = circle_of(circle)
    p, n, h = numbers(kind, pitch, revs, height)
    pl = frame(centre, axis, x, reverse, start_angle)
    if kind == SPIRAL:
        w = _spiral(r, p, n, clockwise)
    else:
        if abs(taper) >= 89.0:
            raise topo.GeometryError("The taper angle must be less than 89°.")
        if taper < 0 and r + h * math.tan(math.radians(taper)) <= 1e-6:
            raise topo.GeometryError("The helix tapers to nothing before its end: use a "
                                     "smaller taper angle or height.")
        try:
            w = Part.makeHelix(p, h, r, float(taper), bool(clockwise))
        except Exception as e:
            raise topo.GeometryError("The helix couldn't be made: {}".format(e))
    w = Part.Wire(w.Edges) if w.ShapeType != "Wire" else w
    w.transformShape(pl.toMatrix(), True)
    w.Tag = int(tag)
    return w


def _spiral(r, pitch, revs, clockwise, per_turn=24):
    """A flat Archimedean spiral from radius r outwards, ``pitch`` apart."""
    pts = []
    n = max(8, int(per_turn * revs))
    sign = -1.0 if clockwise else 1.0
    for i in range(n + 1):
        t = revs * i / float(n)
        a = 2 * math.pi * t * sign
        rad = r + pitch * t
        pts.append(App.Vector(rad * math.cos(a), rad * math.sin(a), 0))
    bs = Part.BSplineCurve()
    bs.interpolate(pts)
    return Part.Wire([bs.toShape()])


# ------------------------------------------------------------------ Insert > Curve

ON_FACES = "Sketch on faces"
ON_SKETCH = "Sketch on sketch"
PROJECTED_TYPES = [ON_FACES, ON_SKETCH]


def projected_on_faces(curves, faces, direction, both=False):
    """A sketch's curves projected along ``direction`` onto faces (SolidWorks'
    Projected Curve, Sketch on faces): where they first land, seen from the
    sketch."""
    if not faces:
        raise topo.GeometryError("Pick the faces to project onto.")
    target = Part.makeCompound(faces)
    size = Part.makeCompound([target, curves]).BoundBox.DiagonalLength
    origin = curves.BoundBox.Center
    out = []
    for d in ([direction, -direction] if both else [direction]):
        d = App.Vector(d).normalize()
        try:
            r = target.makeParallelProjection(curves, d)
        except Exception as e:
            raise topo.GeometryError("The sketch couldn't be projected: {}".format(
                topo._msg(e)))
        for e in r.Edges:
            mid = e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))
            ahead = (mid - origin).dot(d)
            if ahead <= 1e-9 or target.distToShape(Part.Vertex(mid))[0] > 1e-5:
                continue
            # Hidden behind another part of the faces? Look back towards the sketch.
            back = Part.LineSegment(mid - d * (1e-3 * size), mid - d * ahead).toShape()
            if ahead > 2e-3 * size and back.distToShape(target)[0] < 1e-6:
                continue
            if all(not e.isSame(o) for o in out):
                out.append(e)
    if not out:
        raise topo.GeometryError("The sketch doesn't land on the faces when projected; check "
                                 "the direction (Reverse direction).")
    return Part.makeCompound(out)


def sketch_on_sketch(curves1, normal1, curves2, normal2):
    """Where two sketches' curves, pulled out along their own normals, meet
    (SolidWorks' Projected Curve, Sketch on sketch)."""
    if abs(abs(App.Vector(normal1).normalize().dot(App.Vector(normal2).normalize())) - 1) < 1e-9:
        raise topo.GeometryError("The two sketches are on parallel planes; they must cross.")
    size = Part.makeCompound([curves1, curves2]).BoundBox.DiagonalLength * 2 + 10

    def sheet(c, n):
        faces = []
        for e in c.Edges:
            moved = e.copy()
            moved.translate(-n * size)
            faces.extend(moved.extrude(n * (2 * size)).Faces)
        return Part.makeCompound(faces)
    s = sheet(curves1, App.Vector(normal1).normalize()).section(
        sheet(curves2, App.Vector(normal2).normalize()))
    if not s.Edges:
        raise topo.GeometryError("The two sketches' curves don't meet when pulled out along "
                                 "their planes' normals.")
    return Part.makeCompound(s.Edges)


def composite(edges):
    """Edges joined end to end into one curve (SolidWorks' Composite Curve)."""
    if not edges:
        raise topo.GeometryError("Pick the edges or sketches to join.")
    try:
        chains = Part.sortEdges(list(edges))
    except Exception:
        chains = [list(edges)]
    if len(chains) != 1:
        raise topo.GeometryError("The curves must join end to end into one chain ({} pieces "
                                 "now).".format(len(chains)))
    return Part.Wire(chains[0])


def through_points(points, closed=False):
    """A smooth curve through points, in order (Curve Through XYZ Points / Through
    Reference Points)."""
    pts = []
    for p in points:
        if not pts or (p - pts[-1]).Length > 1e-9:
            pts.append(App.Vector(p))
    if closed and len(pts) > 2 and (pts[0] - pts[-1]).Length < 1e-9:
        pts.pop()
    if len(pts) < 2:
        raise topo.GeometryError("A curve needs at least two different points.")
    if closed and len(pts) < 3:
        raise topo.GeometryError("A closed curve needs at least three points.")
    bc = Part.BSplineCurve()
    if len(pts) == 2 and not closed:
        return Part.Wire(Part.LineSegment(pts[0], pts[1]).toShape())
    bc.interpolate(pts, PeriodicFlag=closed)
    return Part.Wire(bc.toShape())
