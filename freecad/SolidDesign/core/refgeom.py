# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reference geometry (SolidWorks' Plane, Axis, Point and Coordinate System), as
pure functions of resolved shapes. A plane is an App.Placement whose Z axis is
the normal; an axis is (point, unit direction); a point is a vector; a
coordinate system is an App.Placement."""

import FreeCAD as App
import Part

from . import topo
from .features.profile import face_point

# Plane types (SolidWorks' constraints, one per type)
COINCIDENT = "Coincident"
OFFSET = "Offset Distance"
ANGLE = "At Angle"
THREE_POINTS = "Through Points"
PARALLEL_AT_POINT = "Parallel at Point"
NORMAL_TO_CURVE = "Normal to Curve"
MID_PLANE = "Mid Plane"
PLANE_TYPES = [COINCIDENT, OFFSET, ANGLE, THREE_POINTS, PARALLEL_AT_POINT, NORMAL_TO_CURVE, MID_PLANE]

# Axis types
LINE = "One Line/Edge/Axis"
TWO_PLANES = "Two Planes"
TWO_POINTS = "Two Points/Vertices"
CYLINDRICAL = "Cylindrical/Conical Face"
POINT_AND_FACE = "Point and Face/Plane"
AXIS_TYPES = [LINE, TWO_PLANES, TWO_POINTS, CYLINDRICAL, POINT_AND_FACE]

# Point types
ARC_CENTER = "Arc Center"
FACE_CENTER = "Center of Face"
INTERSECTION = "Intersection"
PROJECTION = "Projection"
ON_POINT = "On Point"
ALONG_CURVE = "Along Curve Distance"
POINT_TYPES = [ARC_CENTER, FACE_CENTER, INTERSECTION, PROJECTION, ON_POINT, ALONG_CURVE]

# Coordinate system types
ORIGIN_AXES = "Origin and Axes"
CSYS_TYPES = [ORIGIN_AXES]

# What each type needs, for the panel and for errors: (kind, ...) per reference.
PLANE_NEEDS = {
    COINCIDENT: ("plane",), OFFSET: ("plane",), ANGLE: ("plane", "line"), THREE_POINTS: ("point", "point", "point"),
    PARALLEL_AT_POINT: ("plane", "point"), NORMAL_TO_CURVE: ("curve", "point?"),
    MID_PLANE: ("plane", "plane"),
}
AXIS_NEEDS = {
    LINE: ("line",), TWO_PLANES: ("plane", "plane"), TWO_POINTS: ("point", "point"),
    CYLINDRICAL: ("round",), POINT_AND_FACE: ("point", "plane"),
}
POINT_NEEDS = {
    ARC_CENTER: ("arc",), FACE_CENTER: ("face",), INTERSECTION: ("curve", "surface"),
    PROJECTION: ("point", "surface"), ON_POINT: ("point",), ALONG_CURVE: ("curve",),
}
CSYS_NEEDS = {ORIGIN_AXES: ("origin?", "xdir?", "ydir?")}


# ------------------------------------------------------------------ reading shapes

def plane_of(shape, what="reference"):
    """(point, unit normal, x direction) of a planar face or plane."""
    faces = [shape] if shape.ShapeType == "Face" else shape.Faces
    if len(faces) != 1 or faces[0].Surface.TypeId != "Part::GeomPlane":
        raise topo.GeometryError("The {} must be a plane or a planar face.".format(what))
    f = faces[0]
    s = f.Surface
    u0, u1, v0, v1 = f.ParameterRange
    n = f.normalAt(0.5 * (u0 + u1), 0.5 * (v0 + v1)) if f.BoundBox.DiagonalLength < 1e9 \
        else App.Vector(s.Axis)
    c = face_point(f)
    try:
        x = App.Vector(s.XAxis)
    except Exception:
        x = _any_perp(n)
    return c, _unit(n), _unit(x - n * x.dot(n))


# Faces that have an axis (SolidWorks shows it as a temporary axis).
ROUND_SURFACES = ("Part::GeomCylinder", "Part::GeomCone", "Part::GeomToroid")


def axis_of_element(shape):
    """(point, unit direction) of the axis a round face or a circular edge has,
    or None (for the temporary axes, and to use one wherever an axis is asked)."""
    try:
        if shape.ShapeType == "Face" and shape.Surface.TypeId in ROUND_SURFACES:
            s = shape.Surface
            return App.Vector(s.Center if hasattr(s, "Center") else s.Location), _unit(s.Axis)
        if shape.ShapeType == "Edge":
            c = shape.Curve
            if c.TypeId in ("Part::GeomCircle", "Part::GeomArcOfCircle", "Part::GeomEllipse",
                            "Part::GeomArcOfEllipse"):
                return App.Vector(c.Center), _unit(c.Axis)
    except Exception:
        pass
    return None


def line_of(shape, what="reference"):
    """(point, unit direction) of a straight edge, an axis, or a round face's axis."""
    faces = [shape] if shape.ShapeType == "Face" else (
        shape.Faces if shape.ShapeType in ("Shell", "Compound") else [])
    if len(faces) == 1 and faces[0].Surface.TypeId in ROUND_SURFACES:
        s = faces[0].Surface
        return App.Vector(s.Center if hasattr(s, "Center") else s.Location), _unit(s.Axis)
    edges = [shape] if shape.ShapeType == "Edge" else shape.Edges
    if len(edges) != 1:
        raise topo.GeometryError("The {} must be one straight edge or axis.".format(what))
    e = edges[0]
    c = e.Curve
    if c.TypeId in ("Part::GeomLine", "Part::GeomLineSegment"):
        return e.Vertexes[0].Point if e.Vertexes else App.Vector(c.Location), _unit(c.Direction)
    if hasattr(c, "Axis") and hasattr(c, "Center"):     # circle or arc: its axis
        return App.Vector(c.Center), _unit(c.Axis)
    raise topo.GeometryError("The {} must be a straight edge, an axis, or a circular edge.".format(what))


def point_of(shape, what="reference"):
    vs = [shape] if shape.ShapeType == "Vertex" else shape.Vertexes
    if len(vs) != 1:
        raise topo.GeometryError("The {} must be one vertex or point.".format(what))
    return vs[0].Point


def _unit(v):
    v = App.Vector(v)
    if v.Length < 1e-12:
        raise topo.GeometryError("A reference has no direction.")
    return v.normalize()


def _any_perp(n):
    a = App.Vector(1, 0, 0) if abs(n.x) < 0.9 else App.Vector(0, 1, 0)
    return _unit(a - n * a.dot(n))


def placement(origin, normal, xdir=None):
    n = _unit(normal)
    x = _any_perp(n) if xdir is None or abs(xdir.dot(n)) > 1 - 1e-9 else \
        _unit(xdir - n * xdir.dot(n))
    y = n.cross(x)
    m = App.Matrix(x.x, y.x, n.x, origin.x,
                   x.y, y.y, n.y, origin.y,
                   x.z, y.z, n.z, origin.z,
                   0, 0, 0, 1)
    return App.Placement(m)


# ------------------------------------------------------------------ planes

def plane(kind, refs, distance=10.0, angle=45.0, flip=False):
    """``refs``: resolved shapes in the order of PLANE_NEEDS[kind]."""
    need = PLANE_NEEDS[kind]
    req = [k for k in need if not k.endswith("?")]
    if len([r for r in refs if r is not None]) < len(req):
        raise topo.GeometryError("{}: pick {}.".format(kind, _describe(need)))
    if kind == COINCIDENT:
        c, n, x = plane_of(refs[0], "first reference")
        return placement(c, -n if flip else n, x)
    if kind == OFFSET:
        c, n, x = plane_of(refs[0], "first reference")
        d = -distance if flip else distance
        return placement(c + n * d, n, x)
    if kind == ANGLE:
        c, n, x = plane_of(refs[0], "first reference")
        p, a = line_of(refs[1], "second reference")
        ang = -angle if flip else angle
        rot = App.Rotation(a, ang)
        n2 = rot.multVec(n)
        return placement(p, n2, a)
    if kind == THREE_POINTS:
        pts = [point_of(r, "reference") for r in refs[:3]]
        n = (pts[1] - pts[0]).cross(pts[2] - pts[0])
        if n.Length < 1e-9:
            raise topo.GeometryError("Through Points: the three points are in a line.")
        if flip:
            n = -n
        return placement(pts[0], n, pts[1] - pts[0])
    if kind == PARALLEL_AT_POINT:
        _c, n, x = plane_of(refs[0], "first reference")
        p = point_of(refs[1], "second reference")
        return placement(p, -n if flip else n, x)
    if kind == NORMAL_TO_CURVE:
        edges = [refs[0]] if refs[0].ShapeType == "Edge" else refs[0].Edges
        if len(edges) != 1:
            raise topo.GeometryError("Normal to Curve: the first reference must be one edge.")
        e = edges[0]
        if len(refs) > 1 and refs[1] is not None:
            p = point_of(refs[1], "second reference")
            u = e.Curve.parameter(p)
            if e.distToShape(Part.Vertex(p))[0] > 1e-6:
                raise topo.GeometryError("Normal to Curve: the point isn't on the curve.")
        else:
            u = e.FirstParameter
            p = e.valueAt(u)
        t = e.tangentAt(u)
        return placement(p, -t if flip else t)
    if kind == MID_PLANE:
        c1, n1, x1 = plane_of(refs[0], "first reference")
        c2, n2, _x2 = plane_of(refs[1], "second reference")
        if abs(abs(n1.dot(n2)) - 1) > 1e-7:
            raise topo.GeometryError("Mid Plane: the two references must be parallel.")
        mid = (c1 + c2) * 0.5
        return placement(mid, -n1 if flip else n1, x1)
    raise topo.GeometryError("Unknown plane type " + kind)


def _describe(need):
    words = {"plane": "a plane or planar face", "line": "a line, axis or straight edge",
             "point": "a vertex or point", "point?": "(optionally) a point on it",
             "curve": "an edge", "round": "a cylindrical or conical face",
             "arc": "a circular edge or arc", "face": "a face",
             "surface": "a face or plane", "origin?": "(optionally) the origin point",
             "xdir?": "(optionally) the X direction", "ydir?": "(optionally) the Y direction"}
    return ", then ".join(words[k] for k in need)


def plane_face(pl, size):
    """A square face showing a plane, ``size`` across, centred on its origin."""
    h = size / 2.0
    f = Part.makePlane(size, size, App.Vector(-h, -h, 0))
    # Baked into the geometry (Part::Feature resets a shape's own placement). A
    # rigid copy-transform keeps the face a true plane; transformGeometry would
    # turn it into a B-spline.
    f.transformShape(pl.toMatrix(), True)
    return f


# ------------------------------------------------------------------ axes

def axis(kind, refs, flip=False):
    need = AXIS_NEEDS[kind]
    if len([r for r in refs if r is not None]) < len(need):
        raise topo.GeometryError("{}: pick {}.".format(kind, _describe(need)))
    if kind == LINE:
        p, d = line_of(refs[0], "reference")
    elif kind == TWO_PLANES:
        c1, n1, _ = plane_of(refs[0], "first reference")
        c2, n2, _ = plane_of(refs[1], "second reference")
        d = n1.cross(n2)
        if d.Length < 1e-9:
            raise topo.GeometryError("Two Planes: the planes are parallel; they don't meet.")
        # The point of the intersection line nearest the origin.
        h1, h2 = n1.dot(c1), n2.dot(c2)
        p = (n2.cross(d) * h1 + d.cross(n1) * h2) * (1.0 / d.dot(d))
        d = _unit(d)
    elif kind == TWO_POINTS:
        a = point_of(refs[0], "first reference")
        b = point_of(refs[1], "second reference")
        if (b - a).Length < 1e-9:
            raise topo.GeometryError("Two Points: the points are the same.")
        p, d = a, _unit(b - a)
    elif kind == CYLINDRICAL:
        faces = [refs[0]] if refs[0].ShapeType == "Face" else refs[0].Faces
        if len(faces) != 1 or faces[0].Surface.TypeId not in (
                "Part::GeomCylinder", "Part::GeomCone"):
            raise topo.GeometryError("Pick a cylindrical or conical face.")
        s = faces[0].Surface
        p = App.Vector(s.Center) if hasattr(s, "Center") else App.Vector(s.Location)
        d = _unit(s.Axis)
    elif kind == POINT_AND_FACE:
        pt = point_of(refs[0], "first reference")
        c, n, _ = plane_of(refs[1], "second reference")
        p, d = pt, n
    else:
        raise topo.GeometryError("Unknown axis type " + kind)
    return p, (-d if flip else d)


def axis_edge(p, d, length, centre=None):
    """A line edge showing an axis, centred on the point of the axis nearest
    ``centre``."""
    if centre is not None:
        p = p + d * (centre - p).dot(d)
    return Part.LineSegment(p - d * (length / 2.0), p + d * (length / 2.0)).toShape()



# ------------------------------------------------------------------ points

def point(kind, refs, distance=10.0, flip=False):
    """``refs``: resolved shapes in the order of POINT_NEEDS[kind]."""
    need = POINT_NEEDS[kind]
    if len([r for r in refs if r is not None]) < len(need):
        raise topo.GeometryError("{}: pick {}.".format(kind, _describe(need)))
    if kind == ON_POINT:
        return point_of(refs[0], "reference")
    if kind == ARC_CENTER:
        e = _one_edge(refs[0], "Arc Center")
        c = e.Curve
        if not hasattr(c, "Center") or not hasattr(c, "Radius"):
            raise topo.GeometryError("Arc Center: pick a circular edge or arc.")
        return App.Vector(c.Center)
    if kind == FACE_CENTER:
        faces = [refs[0]] if refs[0].ShapeType == "Face" else refs[0].Faces
        if len(faces) != 1:
            raise topo.GeometryError("Center of Face: pick one face.")
        return faces[0].CenterOfMass
    if kind == INTERSECTION:
        e = _one_edge(refs[0], "Intersection")
        surf = refs[1]
        if surf.ShapeType != "Face" and len(surf.Faces) == 1:
            surf = surf.Faces[0]
        hits = _meets(e, surf)
        if not hits:
            raise topo.GeometryError("Intersection: the edge and the face don't meet. An edge "
                                     "is extended along its line or circle to meet a plane.")
        return hits[0]
    if kind == PROJECTION:
        p = point_of(refs[0], "first reference")
        surf = refs[1]
        if surf.ShapeType != "Face" and len(surf.Faces) == 1:
            surf = surf.Faces[0]
        if surf.ShapeType == "Face" and surf.Surface.TypeId == "Part::GeomPlane":
            c, n, _x = plane_of(surf)
            return p - n * (p - c).dot(n)
        try:
            u, v = surf.Surface.parameter(p)
            return surf.Surface.value(u, v)
        except Exception:
            raise topo.GeometryError("Projection: the point can't be projected onto that face.")
    if kind == ALONG_CURVE:
        e = _one_edge(refs[0], "Along Curve Distance")
        if distance > e.Length + 1e-9:
            raise topo.GeometryError("Along Curve Distance: {:g} is longer than the edge "
                                     "({:g}).".format(distance, e.Length))
        d = e.Length - distance if flip else distance
        return e.valueAt(e.getParameterByLength(d))
    raise topo.GeometryError("Unknown point type " + kind)


def _one_edge(shape, what):
    edges = [shape] if shape.ShapeType == "Edge" else shape.Edges
    if len(edges) != 1:
        raise topo.GeometryError("{}: pick one edge.".format(what))
    return edges[0]


def _meets(edge, face):
    """Points where an edge (carried along its own line or circle) meets a face or
    plane, nearest the edge first."""
    pts = []
    try:
        sec = edge.section(face)
        pts = [v.Point for v in sec.Vertexes]
    except Exception:
        pts = []
    if not pts and face.Surface.TypeId == "Part::GeomPlane":
        c, n, _x = plane_of(face)
        curve = edge.Curve
        if curve.TypeId in ("Part::GeomLine", "Part::GeomLineSegment"):
            p0 = edge.Vertexes[0].Point
            d = App.Vector(curve.Direction)
            den = d.dot(n)
            if abs(den) > 1e-12:
                pts = [p0 + d * ((c - p0).dot(n) / den)]
        else:
            try:
                pl = Part.Plane(c, n)
                pts = [App.Vector(q.X, q.Y, q.Z) for q in curve.intersect(pl)
                       if hasattr(q, "X")]
            except Exception:
                pts = []
    mid = edge.valueAt(0.5 * (edge.FirstParameter + edge.LastParameter))
    return sorted(pts, key=lambda q: (q - mid).Length)


# ------------------------------------------------------------------ coordinate systems

def direction_of(shape, what="reference"):
    """A direction from a straight edge or axis (its line), a round face (its
    axis) or a plane or planar face (its normal)."""
    try:
        return line_of(shape, what)[1]
    except topo.GeometryError:
        return plane_of(shape, what)[1]


def csys(refs, flip_x=False, flip_y=False, flip_z=False, origin=None):
    """A coordinate system (an App.Placement) from an optional origin point and
    optional X and Y directions (SolidWorks: any of them; the rest follow, right
    handed). ``origin``: the point used when no origin is picked."""
    refs = list(refs) + [None] * (3 - len(refs))
    o = point_of(refs[0], "origin") if refs[0] is not None else App.Vector(origin or App.Vector())
    x = direction_of(refs[1], "X direction") if refs[1] is not None else None
    y = direction_of(refs[2], "Y direction") if refs[2] is not None else None
    if x is not None and flip_x:
        x = -x
    if y is not None and flip_y:
        y = -y
    if x is None and y is None:
        x, y = App.Vector(1, 0, 0), App.Vector(0, 1, 0)
    elif y is None:
        y = _any_perp(x)
    elif x is None:
        x = _unit(y.cross(App.Vector(0, 0, 1))) if abs(y.z) < 0.99 else \
            _unit(y.cross(App.Vector(1, 0, 0)))
    else:
        if abs(abs(x.dot(y)) - 1.0) < 1e-9:
            raise topo.GeometryError("The X and Y directions are parallel.")
        y = _unit(y - x * y.dot(x))
    x = _unit(x)
    z = x.cross(y)
    if flip_z:
        # Keep it right handed: turning Z round turns Y round too.
        z, y = -z, -y
    m = App.Matrix(x.x, y.x, z.x, o.x,
                   x.y, y.y, z.y, o.y,
                   x.z, y.z, z.z, o.z,
                   0, 0, 0, 1)
    return App.Placement(m)


def csys_shape(size):
    """The three axes of a coordinate system, in its own frame (X, Y, Z edges)."""
    return Part.makeCompound([Part.LineSegment(App.Vector(), App.Vector(size, 0, 0)).toShape(),
                              Part.LineSegment(App.Vector(), App.Vector(0, size, 0)).toShape(),
                              Part.LineSegment(App.Vector(), App.Vector(0, 0, size)).toShape()])
