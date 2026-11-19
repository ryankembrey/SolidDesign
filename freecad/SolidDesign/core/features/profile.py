# SPDX-License-Identifier: LGPL-2.1-or-later
"""Profile helpers shared by sketch-based features (Extrude, Revolve...):
the Thin Feature bands, and plane queries."""

import FreeCAD as App
import Part

from .. import topo

THIN_ONE = "One-Direction"
THIN_MID = "Mid-Plane"
THIN_TWO = "Two-Direction"
THIN_TYPES = [THIN_ONE, THIN_MID, THIN_TWO]


class Thin(object):
    def __init__(self, kind=THIN_ONE, t1=1.0, t2=1.0, reverse=False, cap_ends=False, cap=1.0):
        self.kind = kind
        self.t1 = t1
        self.t2 = t2
        self.reverse = reverse
        self.cap_ends = cap_ends
        self.cap = cap


def face_point(f):
    """A representative point of a face: its centre, or for an infinite face (a
    datum plane) its surface's position (an infinite face's centre is garbage)."""
    try:
        if f.BoundBox.DiagonalLength < 1e9:
            return f.CenterOfMass
    except Exception:
        pass
    s = f.Surface
    return App.Vector(s.Position if hasattr(s, "Position") else s.Location)


def is_plane(f):
    try:
        return f.Surface.TypeId == "Part::GeomPlane" or isinstance(f.Surface, Part.Plane)
    except Exception:
        return False


def plane_normal(f):
    u0, u1, v0, v1 = f.ParameterRange
    return f.normalAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))


def plane_point(f):
    try:
        return f.Surface.Position
    except Exception:
        return f.Vertexes[0].Point


def thin_faces(faces_in, open_wires, t, tag):
    """The thin feature's profile: bands along the sketch contours."""
    faces = []
    if t.kind == THIN_ONE:
        a, b = (0.0, t.t1) if not t.reverse else (-t.t1, 0.0)
    elif t.kind == THIN_MID:
        a, b = -t.t1 / 2.0, t.t1 / 2.0
    else:
        a, b = -t.t2, t.t1
        if t.reverse:
            a, b = -t.t1, t.t2
    if b - a <= 0:
        raise topo.GeometryError("Thin Feature: the thickness must be greater than zero.")
    for f in faces_in:
        outer = f if b == 0 else topo.offset2d(f, b, tag, join=2)
        inner = f if a == 0 else topo.offset2d(f, a, tag, join=2) if a > 0 or _can_shrink(f, a) else None
        if inner is None or inner.isNull() or not inner.Faces:
            raise topo.GeometryError("Thin Feature: the thickness is larger than the profile.")
        band = topo.cut(outer, [inner], tag)
        faces.extend(band.Faces)
    for w in open_wires:
        sides = []
        if b > 0:
            sides.append(topo.offset2d(w, b, tag, join=2, fill=True, open_result=True))
        if a < 0:
            sides.append(topo.offset2d(w, a, tag, join=2, fill=True, open_result=True))
        for s in sides:
            faces.extend(s.Faces)
        if len(sides) == 2:
            fused = topo.refine(topo.fuse(sides[0], [sides[1]], tag), tag)
            faces = faces[:len(faces) - len(sides[0].Faces) - len(sides[1].Faces)] + list(fused.Faces)
    if not faces:
        raise topo.GeometryError("Thin Feature: the sketch gave no contour to thicken.")
    return faces


def _can_shrink(f, a):
    try:
        s = f.makeOffset2D(a, 2)
        return bool(s.Faces)
    except Exception:
        return False
