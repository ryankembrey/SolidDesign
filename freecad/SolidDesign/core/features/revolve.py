# SPDX-License-Identifier: LGPL-2.1-or-later
"""Revolve (Add | Cut): SolidWorks' Revolved Boss/Base and Revolved Cut.

``compute(params, base)`` takes resolved inputs and a BodySet and returns
(Result, tool, preview). Angles are in degrees.
"""

import math

import FreeCAD as App
import Part

from .. import topo
from ..bodies import SOLID
from . import common
from .profile import face_point, is_plane, plane_normal, plane_point, thin_faces

# End conditions, in SolidWorks' order.
BLIND = "Blind"
UP_TO_VERTEX = "Up To Vertex"
UP_TO_SURFACE = "Up To Surface"
OFFSET_FROM_SURFACE = "Offset From Surface"
MID_PLANE = "Mid-Plane"
END_CONDITIONS = [BLIND, UP_TO_VERTEX, UP_TO_SURFACE, OFFSET_FROM_SURFACE, MID_PLANE]
END_CONDITIONS_2 = [BLIND, UP_TO_VERTEX, UP_TO_SURFACE, OFFSET_FROM_SURFACE]

ANG_TOL = 1e-7


class Extent(object):
    def __init__(self, condition=BLIND, angle=360.0, face=None, vertex=None, offset=0.0,
                 reverse_offset=False):
        self.condition = condition
        self.angle = angle
        self.face = face
        self.vertex = vertex
        self.offset = offset
        self.reverse_offset = reverse_offset


class Params(object):
    def __init__(self):
        self.mode = "Add"
        self.faces = []
        self.open_wires = []
        self.axis_point = App.Vector()
        self.axis_dir = App.Vector(0, 0, 1)
        self.reverse = False
        self.dir1 = Extent()
        self.dir2 = None
        self.thin = None
        self.merge = True
        self.scope = common.Scope()
        self.keep = common.Keep()
        self.flip = False
        self.feature = "Revolve"
        self.tag = 1
        self.alloc = None


def _perp(v, d):
    """Component of v perpendicular to unit d."""
    return v - d * v.dot(d)


def _signed_angle(a, b, d):
    """Angle from a to b about unit d, in [0, 360)."""
    a = App.Vector(a)
    b = App.Vector(b)
    if a.Length < 1e-12 or b.Length < 1e-12:
        return 0.0
    a.normalize()
    b.normalize()
    ang = math.degrees(math.atan2(a.cross(b).dot(d), a.dot(b)))
    return ang % 360.0


def _profile_ref(faces, open_wires):
    shape = Part.makeCompound(list(faces) + list(open_wires))
    return shape.BoundBox.Center if not faces else topo.centroid(shape)


def check_axis(faces, open_wires, point, d):
    """The profile must stay on one side of the axis (SolidWorks refuses otherwise)."""
    shape = Part.makeCompound(list(faces) + list(open_wires))
    if not shape.Edges:
        return
    # The side of each point, measured in the plane of the profile.
    try:
        n = faces[0].normalAt(0, 0) if faces else None
    except Exception:
        n = None
    if n is None or abs(n.dot(d)) > 1e-6:
        return              # axis not in the profile's plane: nothing to check this way
    side = d.cross(n)
    pos = neg = False
    scale = max(shape.BoundBox.DiagonalLength, 1.0)
    for e in shape.Edges:
        try:
            pts = e.discretize(Number=24)
        except Exception:
            pts = [v.Point for v in e.Vertexes]
        for p in pts:
            s = (p - point).dot(side)
            if s > 1e-7 * scale:
                pos = True
            elif s < -1e-7 * scale:
                neg = True
    if pos and neg:
        raise topo.GeometryError("The profile crosses the axis of revolution. Pick an axis "
                                 "that lies along one side of the profile.")


def _revolve(faces, point, d, angle, tag):
    if angle <= ANG_TOL:
        raise topo.GeometryError("The angle must be greater than zero.")
    comp = topo.compound(faces, tag)
    try:
        r = comp.revolve(point, d, min(angle, 360.0))
    except Exception as e:
        raise topo.GeometryError("Revolve failed in OpenCASCADE: {}".format(e))
    if r.isNull() or not (r.Solids or r.Faces):
        raise topo.GeometryError("The revolve made no solid.")
    return r


def _rotated(faces, point, d, angle):
    out = []
    for f in faces:
        g = f.copy()
        g.rotate(point, d, angle)
        out.append(g)
    return out


def _angle_to(point, d, ref, target):
    return _signed_angle(_perp(ref - point, d), _perp(target - point, d), d)


def _plane_contains_axis(face, point, d):
    if not is_plane(face):
        return False
    n = plane_normal(face)
    return abs(n.dot(d)) < 1e-9 and abs((point - plane_point(face)).dot(n)) < 1e-7


def _direction_solid(p, faces, d, ext, tag, ref):
    point = p.axis_point
    c = ext.condition
    if c == BLIND:
        return _revolve(faces, point, d, ext.angle, tag)
    if c == UP_TO_VERTEX:
        if ext.vertex is None:
            raise topo.GeometryError("Up To Vertex: pick a vertex.")
        if _perp(ext.vertex - point, d).Length < 1e-9:
            raise topo.GeometryError("Up To Vertex: the vertex is on the axis.")
        a = _angle_to(point, d, ref, ext.vertex)
        if a <= ANG_TOL:
            raise topo.GeometryError("Up To Vertex: the vertex is in the plane of the profile.")
        return _revolve(faces, point, d, a, tag)
    if c in (UP_TO_SURFACE, OFFSET_FROM_SURFACE):
        if ext.face is None:
            raise topo.GeometryError("{}: pick a face or plane.".format(c))
        face = ext.face
        if c == OFFSET_FROM_SURFACE and ext.offset:
            off = ext.offset if ext.reverse_offset else -ext.offset
            try:
                if is_plane(face):
                    face = face.copy()
                    face.translate(plane_normal(face) * off)
                else:
                    face = face.makeOffsetShape(off, 1e-6).Faces[0]
            except Exception as e:
                raise topo.GeometryError("Offset From Surface: the surface can't be offset by "
                                         "that distance ({}).".format(e))
        elif _plane_contains_axis(face, point, d):
            v = _perp(face_point(face) - point, d)
            if v.Length > 1e-7:
                a = _angle_to(point, d, ref, point + v)
            else:
                # A plane centred on the axis (an origin plane): stop at the first
                # half of it reached in the direction of revolution.
                u = plane_normal(face).cross(d)
                angs = [_angle_to(point, d, ref, point + u), _angle_to(point, d, ref, point - u)]
                angs = [x for x in angs if x > ANG_TOL]
                a = min(angs) if angs else 0.0
            if a <= ANG_TOL:
                raise topo.GeometryError("Up To Surface: the plane is the plane of the profile.")
            return _revolve(faces, point, d, a, tag)
        # General surface: revolve almost all the way round, keep the part that
        # starts at the profile and ends at the surface.
        full = _revolve(faces, point, d, 359.9, tag)
        if is_plane(face):
            big = topo.big_length(full)
            tool = Part.Plane(plane_point(face), plane_normal(face)).toShape(-big, big, -big, big)
        else:
            tool = face
        pieces = topo.slice_by(full, [tool], tag).Solids
        if len(pieces) < 2:
            raise topo.GeometryError("{}: the revolve doesn't reach the surface.".format(c))
        probe = App.Vector(ref)
        probe = _rotated([Part.Vertex(probe)], point, d, 0.5)[0].Point
        keep = [s for s in pieces if s.isInside(probe, 1e-6, True)]
        if not keep:
            raise topo.GeometryError("{}: the revolve doesn't reach the surface.".format(c))
        return keep[0]
    if c == MID_PLANE:
        start = _rotated(faces, point, d, -ext.angle / 2.0)
        return _revolve(start, point, d, ext.angle, tag)
    raise topo.GeometryError("Unknown end condition " + c)


def tool_shape(p, base):
    tag = p.tag
    if p.thin is not None:
        faces = thin_faces(p.faces, p.open_wires, p.thin, tag)
    else:
        if p.open_wires and not p.faces:
            raise topo.GeometryError("The sketch is open. Close it, pick closed regions in "
                                     "Selected Contours, or tick Thin Feature.")
        faces = list(p.faces)
    if not faces:
        raise topo.GeometryError("Pick a sketch, or regions of one, to revolve.")
    d = App.Vector(p.axis_dir)
    if d.Length < 1e-12:
        raise topo.GeometryError("Pick an axis of revolution.")
    d.normalize()
    check_axis(faces, [], p.axis_point, d)
    if p.reverse:
        d = -d
    ref = _profile_ref(faces, [])
    first = _direction_solid(p, faces, d, p.dir1, tag, ref)
    parts = [first]
    full = p.dir1.condition == BLIND and p.dir1.angle >= 360.0 - ANG_TOL
    if p.dir2 is not None and p.dir1.condition != MID_PLANE and not full:
        parts.append(_direction_solid(p, faces, -d, p.dir2, tag, ref))
    if len(parts) == 1:
        return parts[0]
    return topo.refine(topo.fuse(parts[0], parts[1:], tag), tag)


def compute(p, base):
    """Run the revolve on ``base``. Returns (Result, tool, preview)."""
    tool = tool_shape(p, base)
    if p.mode == "Add":
        res = common.apply_add(base, tool, p.feature, p.tag, p.merge, p.scope, p.alloc)
        preview = tool
    else:
        if not base.ids(SOLID) and not base.ids():
            raise topo.GeometryError("There is no body to cut. Switch to Add, or make a body "
                                     "first.")
        res = common.apply_cut(base, tool, p.feature, p.tag, p.scope, p.keep, p.alloc, p.flip)
        if not res.touched:
            raise topo.GeometryError("The cut doesn't touch any body in its scope.")
        preview = common.removed_material(tool, base, p.scope, p.tag)
    return res, tool, preview
