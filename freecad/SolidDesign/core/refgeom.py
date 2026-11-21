# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reference geometry (SolidWorks' Plane, Axis, Point and Coordinate System), as
pure functions of resolved shapes. A plane is an App.Placement whose Z axis is
the normal; an axis is (point, unit direction); a point is a vector; a
coordinate system is an App.Placement."""

import math

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
# SolidWorks' way, and the one the panel uses: up to three references, each with
# its own constraint (see "Planes from constraints" below). The types above are
# kept for planes made before it and for scripts.
REFERENCES = "References"
PLANE_TYPES = [REFERENCES, COINCIDENT, OFFSET, ANGLE, THREE_POINTS, PARALLEL_AT_POINT,
               NORMAL_TO_CURVE, MID_PLANE]

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

def plane(kind, refs, distance=10.0, angle=45.0, flip=False, constraints=()):
    """``refs``: resolved shapes in the order of PLANE_NEEDS[kind]; for
    REFERENCES, in pick order, each with its entry of ``constraints`` ("" or a
    missing entry: guessed)."""
    if kind == REFERENCES:
        return plane_from(refs, constraints, distance, angle, flip)
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


# ------------------------------------------------------------------ planes from constraints
# SolidWorks' Plane: up to three references, each with a constraint that fits
# what it is. The constraints only have to agree; the order they were picked in
# doesn't matter.

C_COINCIDENT = "Coincident"
C_PARALLEL = "Parallel"
C_PERPENDICULAR = "Perpendicular"
C_OFFSET = "Offset Distance"
C_ANGLE = "At Angle"
C_MID = "Mid Plane"
C_TANGENT = "Tangent"

# What each kind of reference can be (the first is the panel's order).
CONSTRAINTS_FOR = {
    "plane": [C_COINCIDENT, C_PARALLEL, C_PERPENDICULAR, C_OFFSET, C_ANGLE, C_MID],
    "line": [C_COINCIDENT, C_PERPENDICULAR, C_PARALLEL],
    "curve": [C_PERPENDICULAR, C_COINCIDENT],
    "point": [C_COINCIDENT],
    "round": [C_TANGENT, C_COINCIDENT],
}
KIND_WORDS = {"plane": "plane or planar face", "line": "straight edge or axis",
              "curve": "edge", "point": "point or vertex", "round": "cylindrical face"}

# Planes made with the old types, as constraints (the panel turns them into these).
FROM_TYPE = {
    COINCIDENT: (C_COINCIDENT,), OFFSET: (C_OFFSET,), ANGLE: (C_ANGLE, C_COINCIDENT),
    THREE_POINTS: (C_COINCIDENT,) * 3, PARALLEL_AT_POINT: (C_PARALLEL, C_COINCIDENT),
    NORMAL_TO_CURVE: (C_PERPENDICULAR, C_COINCIDENT), MID_PLANE: (C_MID, C_MID),
}

_LIN = 1e-6         # mm
_ANG = 1e-7         # 1 - |cos| for parallel


def _single(shape):
    """The one face, edge or vertex a reference is, or None."""
    if shape is None:
        return None
    if shape.ShapeType in ("Face", "Edge", "Vertex"):
        return shape
    for subs in (shape.Faces, shape.Edges, shape.Vertexes):
        if subs:
            return subs[0] if len(subs) == 1 else None
    return None


def ref_kind(shape):
    """"plane", "line", "curve", "point", "round" (a cylinder or cone), or None."""
    s = _single(shape)
    if s is None:
        return None
    if s.ShapeType == "Face":
        t = s.Surface.TypeId
        if t == "Part::GeomPlane":
            return "plane"
        if t in ("Part::GeomCylinder", "Part::GeomCone"):
            return "round"
        return None
    if s.ShapeType == "Edge":
        return "line" if s.Curve.TypeId in ("Part::GeomLine", "Part::GeomLineSegment") \
            else "curve"
    return "point"


def _parallel(a, b):
    return 1.0 - abs(a.dot(b)) < _ANG


def _on_line(q, p, d):
    w = q - p
    return (w - d * w.dot(d)).Length < _LIN


def guess(shapes):
    """The constraints SolidWorks would start with for these references, one per
    shape (None for a shape that can't be used)."""
    kinds = [ref_kind(s) for s in shapes]
    out = [None] * len(kinds)
    idx = {}
    for i, k in enumerate(kinds):
        idx.setdefault(k, []).append(i)
    n = len([k for k in kinds if k])
    planes, lines, curves_, points, rounds = (idx.get(k, []) for k in
                                              ("plane", "line", "curve", "point", "round"))

    def put(ids, c):
        for i in ids:
            out[i] = c

    if n == 1:
        put(planes, C_OFFSET)
        put(lines + curves_, C_PERPENDICULAR)
        put(points, C_COINCIDENT)
        put(rounds, C_TANGENT)
    elif len(planes) == 2 and n == 2:
        put(planes, C_MID)
    elif len(planes) == 1 and len(lines) == 1 and n == 2:
        put(planes, C_ANGLE)
        put(lines, C_COINCIDENT)
    elif len(planes) == 1 and rounds and n == 2:
        put(planes, C_PARALLEL)
        put(rounds, C_TANGENT)
    elif len(rounds) == 1 and len(points) == 1 and n == 2:
        put(rounds, C_TANGENT)
        put(points, C_COINCIDENT)
    elif len(planes) == 1 and len(points) == 1 and n == 2:
        put(planes, C_PARALLEL)
        put(points, C_COINCIDENT)
    elif (lines or curves_) and len(points) == 1 and n == 2:
        put(points, C_COINCIDENT)
        if curves_:
            put(curves_, C_PERPENDICULAR)
        else:
            # A point on the line: the plane square to the line there; off it:
            # the plane through both.
            p, d = line_of(shapes[lines[0]])
            put(lines, C_PERPENDICULAR if _on_line(point_of(shapes[points[0]]), p, d)
                else C_COINCIDENT)
    else:
        # Points and lines lie in it; a plane among them is square to it when two
        # other references place it, otherwise it is parallel to it.
        put(points + lines, C_COINCIDENT)
        put(curves_, C_PERPENDICULAR)
        put(rounds, C_COINCIDENT)
        put(planes, C_PERPENDICULAR if n - len(planes) >= 1 and n >= 3 or len(planes) >= 2
            else C_PARALLEL)
    return out


def effective(shapes, constraints):
    """The constraint each reference is under: its own where it fits, else the
    guess for the whole set."""
    g = guess(shapes)
    out = []
    for i, s in enumerate(shapes):
        c = constraints[i] if i < len(constraints) else ""
        k = ref_kind(s)
        out.append(c if c and k and c in CONSTRAINTS_FOR[k] else g[i])
    return out


def plane_from(refs, constraints=(), distance=10.0, angle=45.0, flip=False):
    """A plane from references and their constraints (SolidWorks' Plane)."""
    items = [(i, s) for i, s in enumerate(refs) if s is not None]
    if not items:
        raise topo.GeometryError("Pick a plane, face, edge or point to start from.")
    shapes = [s for _i, s in items]
    cons = effective(shapes, [constraints[i] if i < len(constraints) else ""
                              for i, _s in items])
    kinds = []
    for (i, s), c in zip(items, cons):
        k = ref_kind(s)
        if k is None:
            raise topo.GeometryError(
                "Reference {} can't place a plane: pick a plane, a planar or cylindrical "
                "face, an edge or a point.".format(i + 1))
        kinds.append(k)
    refs_ = list(zip(kinds, shapes, cons, [i + 1 for i, _s in items]))
    valued = [r for r in refs_ if r[2] in (C_OFFSET, C_ANGLE)]
    if len(valued) > 1:
        raise topo.GeometryError("Only one reference can set a distance or an angle.")
    if any(r[2] == C_MID for r in refs_):
        return _mid(refs_, flip)
    if any(r[2] == C_ANGLE for r in refs_):
        return _at_angle(refs_, angle, flip)
    if any(r[2] == C_TANGENT for r in refs_):
        return _tangent(refs_, flip)
    return _solve(refs_, distance, flip)


def _mid(refs_, flip):
    mids = [r for r in refs_ if r[2] == C_MID]
    if len(mids) != 2 or len(refs_) != 2:
        raise topo.GeometryError("Mid Plane: pick two planes or planar faces, both set to "
                                 "Mid Plane.")
    c1, n1, x1 = plane_of(mids[0][1], "first reference")
    c2, n2, _x2 = plane_of(mids[1][1], "second reference")
    if _parallel(n1, n2):
        mid = (c1 + c2) * 0.5
        return placement(mid, -n1 if flip else n1, x1)
    # Two planes that meet: the plane that halves the angle between them, through
    # the line where they meet (between two sides of a block: the one inside it).
    d = n1.cross(n2)
    h1, h2 = n1.dot(c1), n2.dot(c2)
    p = (n2.cross(d) * h1 + d.cross(n1) * h2) * (1.0 / d.dot(d))
    m = _unit(n1 - n2)
    return placement(p, -m if flip else m, _unit(d))


def _line_ref(r):
    """(point, direction) of a line, a round face's axis or a straight edge."""
    return line_of(r[1], "reference {}".format(r[3]))


def _at_angle(refs_, angle, flip):
    pl = [r for r in refs_ if r[2] == C_ANGLE][0]
    rest = [r for r in refs_ if r is not pl]
    axes = [r for r in rest if r[0] in ("line", "round") and r[2] == C_COINCIDENT]
    if len(axes) != 1 or len(rest) != 1:
        raise topo.GeometryError("At Angle: pick one edge or axis to turn about, set to "
                                 "Coincident.")
    _c, n, _x = plane_of(pl[1], "reference {}".format(pl[3]))
    p, a = _line_ref(axes[0])
    if _parallel(n, a):
        raise topo.GeometryError("At Angle: the edge is square to the plane, so turning "
                                 "about it changes nothing.")
    n2 = App.Rotation(a, -angle if flip else angle).multVec(n)
    return placement(p, n2, a)


def _tangent(refs_, flip):
    t = [r for r in refs_ if r[2] == C_TANGENT]
    rest = [r for r in refs_ if r[2] != C_TANGENT]
    if len(t) != 1 or len(rest) != 1:
        raise topo.GeometryError("Tangent: pick a cylindrical face, and a plane or a point "
                                 "to say which tangent plane.")
    f = _single(t[0][1])
    s = f.Surface
    if s.TypeId != "Part::GeomCylinder":
        raise topo.GeometryError("Tangent works on cylindrical faces.")
    p0, d, r = App.Vector(s.Center), _unit(s.Axis), s.Radius
    side = -1.0 if flip else 1.0
    k, shape, c, num = rest[0]
    if k == "plane" and c in (C_PARALLEL, C_PERPENDICULAR):
        _c, n, _x = plane_of(shape, "reference {}".format(num))
        if c == C_PARALLEL:
            if abs(n.dot(d)) > 1e-7:
                raise topo.GeometryError("Tangent: the plane must be parallel to the "
                                         "cylinder's axis.")
            u = n
        else:
            if _parallel(n, d):
                raise topo.GeometryError("Tangent: the plane is square to the cylinder's "
                                         "axis; every tangent plane is square to it.")
            u = _unit(n.cross(d))
        return placement(p0 + u * (r * side), u, d)
    if k == "point" and c == C_COINCIDENT:
        q = point_of(shape)
        w = (q - p0) - d * (q - p0).dot(d)
        h = w.Length
        if h < r - _LIN:
            raise topo.GeometryError("Tangent: the point is inside the cylinder, so no "
                                     "tangent plane passes through it.")
        w = _unit(w)
        if h - r <= _LIN:
            u = w
        else:
            # From a point outside, two planes touch the cylinder; Flip picks the other.
            u = App.Rotation(d, side * math.degrees(math.acos(r / h))).multVec(w)
        return placement(q, u, d)
    raise topo.GeometryError("Tangent: the other reference must be a plane (Parallel or "
                             "Perpendicular) or a point (Coincident).")


def _curve_at(shape, near):
    """(point, unit tangent) of an edge at the point nearest ``near``, or at its start."""
    e = _single(shape)
    u = e.FirstParameter if near is None else e.Curve.parameter(near)
    if near is not None and not (e.FirstParameter - 1e-9 <= u <= e.LastParameter + 1e-9):
        u = e.FirstParameter if (e.valueAt(e.FirstParameter) - near).Length <= \
            (e.valueAt(e.LastParameter) - near).Length else e.LastParameter
    return e.valueAt(u), _unit(e.tangentAt(u))


def _solve(refs_, distance, flip):
    """Coincident, Parallel, Perpendicular and Offset: each reference fixes the
    normal, asks the normal to be square to a direction, or puts a point in the
    plane; together they must give exactly one plane."""
    fixed, square, points, xdirs = [], [], [], []
    loose = []          # where a lone edge or line puts it, if nothing else does
    first_point = next((point_of(r[1]) for r in refs_
                        if r[0] == "point" and r[2] == C_COINCIDENT), None)
    offset = any(r[2] == C_OFFSET for r in refs_)
    for k, s, c, num in refs_:
        what = "reference {}".format(num)
        if k == "plane":
            pc, n, x = plane_of(s, what)
            if c in (C_COINCIDENT, C_PARALLEL, C_OFFSET):
                fixed.append((n, num))
                xdirs.append(x)
                if c == C_COINCIDENT:
                    points.append(pc)
                elif c == C_OFFSET:
                    points.append(pc + n * (-distance if flip else distance))
            elif c == C_PERPENDICULAR:
                square.append(n)
        elif k in ("line", "round"):
            p, d = line_of(s, what)
            if c == C_COINCIDENT:
                square.append(d)
                points.append(p)
                xdirs.append(d)
            elif c == C_PARALLEL:
                square.append(d)
                xdirs.append(d)
            elif c == C_PERPENDICULAR:
                fixed.append((d, num))
                loose.append(p)
        elif k == "curve":
            if c == C_PERPENDICULAR:
                p, t = _curve_at(s, first_point)
                fixed.append((t, num))
                loose.append(p)
            else:
                pl = _single(s).findPlane()
                if pl is None:
                    raise topo.GeometryError("Reference {}: the edge doesn't lie in a "
                                             "plane.".format(num))
                fixed.append((_unit(pl.Axis), num))
                points.append(_single(s).valueAt(_single(s).FirstParameter))
        else:
            points.append(point_of(s, what))
    # The normal.
    if fixed:
        n = fixed[0][0]
        for v, num in fixed[1:]:
            if not _parallel(n, v):
                raise topo.GeometryError("References {} and {} ask for different "
                                         "directions; change one's constraint."
                                         .format(fixed[0][1], num))
    else:
        n = None
        for i in range(len(square)):
            for j in range(i + 1, len(square)):
                if not _parallel(square[i], square[j]):
                    n = square[i].cross(square[j])
                    break
            if n is not None:
                break
        if n is None and square:
            for i in range(len(points)):
                for j in range(i + 1, len(points)):
                    w = points[j] - points[i]
                    if w.Length > _LIN and not _parallel(_unit(w), square[0]):
                        n = square[0].cross(w)
                        break
                if n is not None:
                    break
        if n is None and not square and len(points) >= 3:
            for j in range(1, len(points)):
                for k in range(j + 1, len(points)):
                    m = (points[j] - points[0]).cross(points[k] - points[0])
                    if m.Length > _LIN * _LIN:
                        n = m
                        break
                if n is not None:
                    break
            if n is None:
                raise topo.GeometryError("The points are in a line; a plane through them "
                                         "can turn about it. Pick a point off the line.")
        if n is None:
            raise topo.GeometryError(_underdefined(refs_))
        n = _unit(n)
        xdirs.append(next((points[j] - points[0] for j in range(1, len(points))
                           if (points[j] - points[0]).Length > _LIN), None))
    for v in square:
        if abs(v.dot(n)) > 1e-7:
            raise topo.GeometryError("The references don't agree: no plane meets them all. "
                                     "Change a constraint.")
    # Where it is.
    if not points:
        if not loose:
            raise topo.GeometryError("Not fully defined: pick a point or an edge for the "
                                     "plane to pass through.")
        points = loose[:1]
    o = points[0]
    for q in points[1:]:
        if abs((q - o).dot(n)) > _LIN * max(1.0, (q - o).Length):
            raise topo.GeometryError("The references don't lie in one plane. Change a "
                                     "constraint or pick something else.")
    if flip and not offset:
        n = -n
    x = next((v for v in xdirs if v is not None and v.Length > _LIN and
              not _parallel(_unit(v), n)), None)
    return placement(o, n, x)


def _underdefined(refs_):
    kinds = [r[0] for r in refs_]
    if kinds and all(k == "point" for k in kinds):
        return "Not fully defined: three points make a plane; pick {} more.".format(
            3 - len(kinds))
    return "Not fully defined: add a reference, or change a constraint."


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


# ------------------------------------------------------------------ Bounding Box

BEST_FIT = "Best Fit"
REFERENCE_PLANE = "Reference Plane"
BOX_TYPES = [BEST_FIT, REFERENCE_PLANE]


def _cloud(shapes):
    """Points on the shapes (vertices and a tessellation): for searching orientations."""
    import numpy as np
    pts = []
    for s in shapes:
        tol = max(s.BoundBox.DiagonalLength / 400.0, 1e-4)
        try:
            pts.extend(s.tessellate(tol)[0])
        except Exception:
            pass
        pts.extend(v.Point for v in s.Vertexes)
        for e in s.Edges:
            try:
                pts.extend(e.discretize(Deflection=tol))
            except Exception:
                pass
    if not pts:
        raise topo.GeometryError("There is nothing to put a box round.")
    return np.array([[p.x, p.y, p.z] for p in pts])


def _frame(z, x=None):
    z = _unit(z)
    if x is None or abs(x.dot(z)) > 1 - 1e-9:
        x = _any_perp(z)
    x = _unit(x - z * x.dot(z))
    return x, z.cross(x), z


def _best_turn(P, x, y, z):
    """The turn about z (0..90 degrees) that makes the box's footprint smallest."""
    import numpy as np
    X = np.array([x.x, x.y, x.z])
    Y = np.array([y.x, y.y, y.z])
    u, v = P.dot(X), P.dot(Y)

    def area(a):
        c, s = math.cos(a), math.sin(a)
        uu, vv = c * u + s * v, -s * u + c * v
        return (uu.max() - uu.min()) * (vv.max() - vv.min())
    best = min((area(math.radians(d)), math.radians(d)) for d in range(0, 90, 2))[1]
    step = math.radians(1.0)
    while step > math.radians(0.01):
        cands = [best - step, best, best + step]
        best = min(cands, key=area)
        step *= 0.5
    c, s = math.cos(best), math.sin(best)
    return x * c + y * s, y * c - x * s


def _directions(shapes, P):
    """Directions worth trying as a box side: the bodies' principal axes, and the
    normals of their biggest flat faces."""
    import numpy as np
    out = [App.Vector(1, 0, 0), App.Vector(0, 1, 0), App.Vector(0, 0, 1)]
    c = P.mean(axis=0)
    w, vecs = np.linalg.eigh(np.cov((P - c).T))
    out.extend(App.Vector(*vecs[:, i]) for i in range(3))
    flat = []
    for s in shapes:
        for f in s.Faces:
            if f.Surface.TypeId == "Part::GeomPlane":
                flat.append((f.Area, f.normalAt(0, 0)))
            elif f.Surface.TypeId in ("Part::GeomCylinder", "Part::GeomCone"):
                flat.append((f.Area, f.Surface.Axis))
    flat.sort(key=lambda t: -t[0])
    out.extend(n for _a, n in flat[:12])
    return out


def bounding_box(shapes, kind=BEST_FIT, plane=None):
    """(placement of the box's corner, (dx, dy, dz)) round the shapes. Best fit: the
    smallest box over the bodies' natural directions; Reference plane: square to the
    plane, turned in it to the smallest footprint."""
    shapes = [s for s in shapes if s is not None and not s.isNull()]
    if not shapes:
        raise topo.GeometryError("There are no bodies to put a box round.")
    P = _cloud(shapes)
    if kind == REFERENCE_PLANE:
        if plane is None:
            raise topo.GeometryError("Pick the reference plane the box sits square to.")
        _p, n, _x = plane_of(plane, "reference plane")
        cands = [n]
    else:
        cands = _directions(shapes, P)
    best = None
    import numpy as np
    for n in cands:
        x, y, z = _frame(App.Vector(n))
        x, y = _best_turn(P, x, y, z)
        M = np.array([[x.x, x.y, x.z], [y.x, y.y, y.z], [z.x, z.y, z.z]])
        L = P.dot(M.T)
        size = L.max(axis=0) - L.min(axis=0)
        vol = float(size[0] * size[1] * size[2])
        if best is None or vol < best[0] - 1e-9 * max(vol, 1.0):
            best = (vol, x, y, z)
    _v, x, y, z = best
    # Exact extents for the chosen frame (the cloud is a little inside curved faces).
    pl = App.Placement(App.Matrix(x.x, y.x, z.x, 0, x.y, y.y, z.y, 0, x.z, y.z, z.z, 0,
                                  0, 0, 0, 1))
    inv = pl.inverse().toMatrix()
    lo, hi = None, None
    for s in shapes:
        t = s.copy()
        t.transformShape(inv, True)
        try:
            bb = t.optimalBoundingBox(True, False)
        except Exception:
            bb = t.BoundBox
        lo = App.Vector(bb.XMin, bb.YMin, bb.ZMin) if lo is None else \
            App.Vector(min(lo.x, bb.XMin), min(lo.y, bb.YMin), min(lo.z, bb.ZMin))
        hi = App.Vector(bb.XMax, bb.YMax, bb.ZMax) if hi is None else \
            App.Vector(max(hi.x, bb.XMax), max(hi.y, bb.YMax), max(hi.z, bb.ZMax))
    corner = pl.multVec(lo)
    return App.Placement(corner, pl.Rotation), (hi.x - lo.x, hi.y - lo.y, hi.z - lo.z)


def box_edges(placement, size):
    """The 12 edges of a box: what the bounding box shows."""
    dx, dy, dz = size
    pts = [App.Vector(x, y, z) for z in (0, dz) for y in (0, dy) for x in (0, dx)]
    pairs = [(0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7),
             (0, 4), (1, 5), (2, 6), (3, 7)]
    edges = []
    for a, b in pairs:
        if (pts[a] - pts[b]).Length > 1e-9:
            edges.append(Part.LineSegment(placement.multVec(pts[a]),
                                          placement.multVec(pts[b])).toShape())
    if not edges:
        raise topo.GeometryError("The bodies have no size.")
    return Part.makeCompound(edges)


def centre_of_mass(solids):
    """The centre of mass of solids of one density."""
    solids = [s for s in solids if s is not None and s.Volume > 1e-12]
    if not solids:
        raise topo.GeometryError("There is no solid body: the centre of mass needs one.")
    total = sum(s.Volume for s in solids)
    c = App.Vector()
    for s in solids:
        c += s.CenterOfMass * (s.Volume / total)
    return c


def cosmetic_thread(centre, axis, radius, length):
    """What a cosmetic thread shows: its diameter as circles at both ends and four
    lines along it."""
    a = _unit(axis)
    end = centre + a * length
    x = _any_perp(a)
    y = a.cross(x)
    edges = [Part.makeCircle(radius, centre, a), Part.makeCircle(radius, end, a)]
    for d in (x, y, -x, -y):
        edges.append(Part.LineSegment(centre + d * radius, end + d * radius).toShape())
    return Part.makeCompound(edges)
