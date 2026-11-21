# SPDX-License-Identifier: LGPL-2.1-or-later
"""Extrude (Add | Cut): SolidWorks' Extruded Boss/Base and Extruded Cut.

``compute(params, base)`` takes resolved inputs (shapes and vectors, no
document objects) and a BodySet, and returns (Result, tool, preview).
"""

import math

import FreeCAD as App
import Part

from .. import topo
from ..bodies import SOLID
from . import common, sheet
from .profile import (THIN_MID, THIN_ONE, THIN_TWO, THIN_TYPES, Thin,
                      is_plane as _is_plane, plane_normal as _plane_normal,
                      plane_point as _plane_point, thin_faces)

REEXPORTED = (THIN_TYPES, Thin)   # used by app/extrude through this module

# End conditions, in SolidWorks' order.
BLIND = "Blind"
THROUGH_ALL = "Through All"
THROUGH_ALL_BOTH = "Through All - Both"
UP_TO_NEXT = "Up To Next"
UP_TO_VERTEX = "Up To Vertex"
UP_TO_SURFACE = "Up To Surface"
OFFSET_FROM_SURFACE = "Offset From Surface"
UP_TO_BODY = "Up To Body"
MID_PLANE = "Mid Plane"
END_CONDITIONS = [BLIND, THROUGH_ALL, THROUGH_ALL_BOTH, UP_TO_NEXT, UP_TO_VERTEX,
                  UP_TO_SURFACE, OFFSET_FROM_SURFACE, UP_TO_BODY, MID_PLANE]
# Direction 2 can't be Mid Plane or Through All - Both (they already use both sides).
END_CONDITIONS_2 = [c for c in END_CONDITIONS if c not in (MID_PLANE, THROUGH_ALL_BOTH)]

FROM_SKETCH = "Sketch Plane"
FROM_SURFACE = "Surface/Face/Plane"
FROM_VERTEX = "Vertex"
FROM_OFFSET = "Offset"
FROM_KINDS = [FROM_SKETCH, FROM_SURFACE, FROM_VERTEX, FROM_OFFSET]

class Extent(object):
    def __init__(self, condition=BLIND, depth=10.0, face=None, vertex=None, body=None,
                 offset=0.0, reverse_offset=False, draft=0.0, draft_outward=False):
        self.condition = condition
        self.depth = depth
        self.face = face            # Part.Face (Up To Surface, Offset From Surface)
        self.vertex = vertex        # App.Vector (Up To Vertex)
        self.body = body            # body ID (Up To Body)
        self.offset = offset
        self.reverse_offset = reverse_offset
        self.draft = draft          # degrees, 0 = none
        self.draft_outward = draft_outward


class Params(object):
    def __init__(self):
        self.mode = "Add"
        self.faces = []             # closed profile faces, global
        self.open_wires = []        # open profile wires (thin feature only)
        self.origin = App.Vector()  # a point on the sketch plane
        self.normal = App.Vector(0, 0, 1)
        self.direction = None       # extrude along this instead of the normal
        self.reverse = False
        self.from_kind = FROM_SKETCH
        self.from_offset = 0.0
        self.from_reverse = False
        self.from_face = None
        self.from_vertex = None
        self.dir1 = Extent()
        self.dir2 = None
        self.thin = None
        self.cap_end = False        # Surface mode: close the ends (a closed surface)
        self.merge = True
        self.scope = common.Scope()
        self.keep = common.Keep()
        self.flip = False
        self.feature = "Extrude"
        self.tag = 1
        self.alloc = None


# ---------------------------------------------------------------- profile

def _start_shift(p, base):
    """How far along the sketch normal the profile moves for the From option."""
    n = p.normal
    if p.from_kind == FROM_SKETCH:
        return 0.0
    if p.from_kind == FROM_OFFSET:
        return -p.from_offset if p.from_reverse else p.from_offset
    if p.from_kind == FROM_VERTEX:
        if p.from_vertex is None:
            raise topo.GeometryError("From: pick a vertex to start from.")
        return (p.from_vertex - p.origin).dot(n)
    if p.from_kind == FROM_SURFACE:
        f = p.from_face
        if f is None:
            raise topo.GeometryError("From: pick a face or plane to start from.")
        if not _is_plane(f):
            raise topo.GeometryError("From: only planar faces and planes are supported for "
                                     "Surface/Face/Plane in this version.")
        m = _plane_normal(f)
        if abs(abs(m.dot(n)) - 1.0) > 1e-7:
            raise topo.GeometryError("From: the face must be parallel to the sketch.")
        return (_plane_point(f) - p.origin).dot(n)
    raise topo.GeometryError("Unknown From option " + p.from_kind)


# ---------------------------------------------------------------- prisms

def _offset_wire(w, delta):
    """A closed planar wire grown (delta > 0) or shrunk, with sharp corners kept
    sharp, as a draft keeps them. None when it vanishes."""
    try:
        o = w.makeOffset2D(delta, 2)
    except Exception:
        return None
    wires = o.Wires if o is not None else []
    if len(wires) != 1 or not wires[0].isClosed():
        return None
    return wires[0]


def _prism(faces, d, length, tag, draft=0.0, outward=False):
    """Faces swept along unit ``d`` by ``length`` with an optional draft (degrees).

    With a draft, the far end is the profile offset by length * tan(angle):
    the outer boundary shrinks (or grows, outward) and each hole grows (or
    shrinks); the sides are ruled between the two. Every wire is offset on its
    own: offsetting a face with holes in one go gives separate faces with the
    holes lost.
    """
    if length <= topo.TOL:
        raise topo.GeometryError("The depth must be greater than zero.")
    comp = topo.compound(faces, tag)
    if not draft:
        return topo.extrude(comp, d * length, tag)
    delta = length * math.tan(topo.deg(draft))
    if not outward:
        delta = -delta
    out = []
    for f in faces:
        outer = f.OuterWire
        top = _offset_wire(outer, delta)
        if top is None:
            raise topo.GeometryError("Draft: the angle is too large for this depth; the end "
                                     "of the extrusion would vanish.")
        top.translate(d * length)
        solid = topo.loft([outer, top], tag)
        holes = []
        for w in f.Wires:
            if w.isSame(outer):
                continue
            tw = _offset_wire(w, -delta)
            if tw is None:
                raise topo.GeometryError("Draft: the angle closes a hole in the profile before "
                                         "the end of the extrusion. Use a smaller angle or "
                                         "depth.")
            tw.translate(d * length)
            holes.append(topo.loft([w, tw], tag))
        if holes:
            solid = topo.cut(solid, holes, tag)
        out.append(solid)
    return out[0] if len(out) == 1 else topo.compound(out, tag)


def _shift_faces(faces, vec):
    out = []
    for f in faces:
        g = f.copy()
        g.translate(vec)
        out.append(g)
    return out


def _nearest_pieces(pieces, faces):
    """Pieces at the smallest distance from the profile."""
    if not pieces:
        return []
    prof = Part.makeCompound(faces)
    dist = [(p.distToShape(prof)[0], p) for p in pieces]
    m = min(d for d, _ in dist)
    return [p for d, p in dist if d <= m + 1e-6]


def _trim_to_surface(prism, face, faces, tag, big):
    """Keep the part of a long prism between the profile and ``face``."""
    if _is_plane(face):
        n = _plane_normal(face)
        pt = _plane_point(face)
        pl = Part.Plane(pt, n)
        tool = pl.toShape(-big, big, -big, big)
    else:
        tool = face
    pieces = topo.slice_by(prism, [tool], tag).Solids
    keep = [p for p in pieces if p.distToShape(Part.makeCompound(faces))[0] < 1e-6]
    if not keep:
        raise topo.GeometryError("Up To Surface: the extrusion doesn't reach the surface.")
    if len(pieces) == 1:
        raise topo.GeometryError("Up To Surface: the surface doesn't cross the whole "
                                 "profile. Pick a larger surface or use another end condition.")
    return keep[0] if len(keep) == 1 else topo.fuse(keep[0], keep[1:], tag)


def through_length(prof, base, d, big):
    """Through All's length, as SolidWorks: from the profile to just past the far
    side of the model's bounding box along ``d`` (``big`` with no model yet)."""
    box = App.BoundBox()
    for b in base:
        if b.shape is not None and not b.shape.isNull():
            box.add(b.shape.BoundBox)
    if not box.isValid():
        return big
    pb = prof.BoundBox

    def corners(bb):
        return [App.Vector(x, y, z) for x in (bb.XMin, bb.XMax) for y in (bb.YMin, bb.YMax)
                for z in (bb.ZMin, bb.ZMax)]
    far = max(c.dot(d) for c in corners(box))
    near = min(c.dot(d) for c in corners(pb))
    margin = max(0.01, 1e-3 * box.DiagonalLength)
    return max(far - near, 0.0) + margin


def _direction_solid(p, base, faces, d, ext, tag, big, first):
    """The solid for one direction of the extrusion."""
    c = ext.condition
    if c == BLIND:
        return _prism(faces, d, ext.depth, tag, ext.draft, ext.draft_outward)
    if c in (THROUGH_ALL, THROUGH_ALL_BOTH):
        return _prism(faces, d, through_length(Part.makeCompound(faces), base, d, big), tag,
                      ext.draft, ext.draft_outward)
    if c == UP_TO_VERTEX:
        if ext.vertex is None:
            raise topo.GeometryError("Up To Vertex: pick a vertex.")
        L = (ext.vertex - p.origin).dot(d) - _start_shift(p, base) * p.normal.dot(d)
        if L <= topo.TOL:
            raise topo.GeometryError("Up To Vertex: the vertex is behind the start of the "
                                     "extrusion. Click Reverse Direction.")
        return _prism(faces, d, L, tag, ext.draft, ext.draft_outward)
    if c in (UP_TO_SURFACE, OFFSET_FROM_SURFACE):
        if ext.face is None:
            raise topo.GeometryError("{}: pick a face or plane.".format(c))
        face = ext.face
        if c == OFFSET_FROM_SURFACE and ext.offset:
            off = ext.offset if ext.reverse_offset else -ext.offset
            if _is_plane(face):
                n = _plane_normal(face)
                s = 1.0 if n.dot(d) > 0 else -1.0
                face = face.copy()
                face.translate(n * (off * s))
            else:
                try:
                    face = face.makeOffsetShape(off, 1e-6).Faces[0]
                except Exception as e:
                    raise topo.GeometryError("Offset From Surface: the surface can't be offset "
                                             "by that distance ({}).".format(e))
        if _is_plane(face):
            n = _plane_normal(face)
            if abs(abs(n.dot(d)) - 1.0) < 1e-9:
                L = (_plane_point(face) - _origin_of(faces)).dot(d)
                if L <= topo.TOL:
                    raise topo.GeometryError("{}: the surface is behind the profile. Click "
                                             "Reverse Direction.".format(c))
                return _prism(faces, d, L, tag, ext.draft, ext.draft_outward)
        long_ = _prism(faces, d, big, tag, ext.draft, ext.draft_outward)
        return _trim_to_surface(long_, face, faces, tag, big)
    if c in (UP_TO_NEXT, UP_TO_BODY):
        long_ = _prism(faces, d, big, tag, ext.draft, ext.draft_outward)
        if c == UP_TO_BODY:
            if not ext.body or ext.body not in base:
                raise topo.GeometryError("Up To Body: pick the body to extrude up to.")
            targets = [base.get(ext.body).shape]
            pieces = topo.cut(long_, targets, tag).Solids
            keep = _nearest_pieces(pieces, faces)
            if len(pieces) <= 1:
                raise topo.GeometryError("Up To Body: the extrusion doesn't reach the body.")
            return keep[0] if len(keep) == 1 else topo.fuse(keep[0], keep[1:], tag)
        targets = [b.shape for b in base.bodies(SOLID)]
        if p.mode == "Add" or not targets:
            pieces = topo.cut(long_, targets, tag).Solids if targets else []
            if len(pieces) <= 1:
                raise topo.GeometryError("Up To Next: nothing is in the way of the extrusion. "
                                         "Use Blind or another end condition.")
        else:
            pieces = []
            for t in targets:
                pieces.extend(topo.common(long_, [t], tag).Solids)
            if not pieces:
                raise topo.GeometryError("Up To Next: the cut doesn't reach any material.")
        keep = _nearest_pieces(pieces, faces)
        return keep[0] if len(keep) == 1 else topo.fuse(keep[0], keep[1:], tag)
    if c == MID_PLANE:
        if not first:
            raise topo.GeometryError("Mid Plane can't be used for Direction 2.")
        half = _shift_faces(faces, d * (-ext.depth / 2.0))
        if ext.draft:
            a = _prism(faces, d, ext.depth / 2.0, tag, ext.draft, ext.draft_outward)
            b = _prism(faces, -d, ext.depth / 2.0, tag, ext.draft, ext.draft_outward)
            return topo.refine(topo.fuse(a, [b], tag), tag)
        return _prism(half, d, ext.depth, tag)
    raise topo.GeometryError("Unknown end condition " + c)


# ---------------------------------------------------------------- surface mode

def _sheet_prism(prof, d, length, tag, draft=0.0, outward=False):
    """The profile's curves swept along ``d``: faces, not a solid."""
    faces, wires = prof
    if length <= topo.TOL:
        raise topo.GeometryError("The depth must be greater than zero.")
    if not draft:
        return topo.extrude(topo.compound(sheet.wires_of(faces, wires), tag), d * length, tag)
    if wires:
        raise topo.GeometryError("Draft needs closed curves; an open sketch can't be drafted.")
    delta = length * math.tan(topo.deg(draft))
    if not outward:
        delta = -delta
    out = []
    for f in faces:
        outer = f.OuterWire
        for w in f.Wires:
            sign = 1.0 if w.isSame(outer) else -1.0
            top = _offset_wire(w, sign * delta)
            if top is None:
                raise topo.GeometryError("Draft: the angle is too large for this depth; the "
                                         "end of the surface would vanish.")
            top.translate(d * length)
            out.extend(topo.loft([w, top], tag, solid=False).Faces)
    return sheet.shells(out, tag)


def _shift_prof(prof, vec):
    faces, wires = prof
    return _shift_faces(faces, vec), _shift_faces(wires, vec)


def _sheet_direction(p, base, prof, d, ext, tag, big, first):
    """One direction of a surface extrude."""
    ref = Part.makeCompound(sheet.wires_of(*prof))
    c = ext.condition

    def mk(pr, dd, length):
        return _sheet_prism(pr, dd, length, tag, ext.draft, ext.draft_outward)
    if c == BLIND:
        return mk(prof, d, ext.depth)
    if c in (THROUGH_ALL, THROUGH_ALL_BOTH):
        return mk(prof, d, through_length(ref, base, d, big))
    if c == UP_TO_VERTEX:
        if ext.vertex is None:
            raise topo.GeometryError("Up To Vertex: pick a vertex.")
        L = (ext.vertex - p.origin).dot(d) - _start_shift(p, base) * p.normal.dot(d)
        if L <= topo.TOL:
            raise topo.GeometryError("Up To Vertex: the vertex is behind the start of the "
                                     "extrusion. Click Reverse Direction.")
        return mk(prof, d, L)
    if c in (UP_TO_SURFACE, OFFSET_FROM_SURFACE):
        face = _target_face(ext, d, c)
        if _is_plane(face):
            n = _plane_normal(face)
            if abs(abs(n.dot(d)) - 1.0) < 1e-9:
                L = (_plane_point(face) - ref.Vertexes[0].Point).dot(d)
                if L <= topo.TOL:
                    raise topo.GeometryError("{}: the surface is behind the profile. Click "
                                             "Reverse Direction.".format(c))
                return mk(prof, d, L)
            tool = Part.Plane(_plane_point(face), n).toShape(-big, big, -big, big)
        else:
            tool = face
        return sheet.trimmed(mk(prof, d, big), [tool], ref, tag, c)
    if c in (UP_TO_NEXT, UP_TO_BODY):
        long_ = mk(prof, d, big)
        if c == UP_TO_BODY:
            if not ext.body or ext.body not in base:
                raise topo.GeometryError("Up To Body: pick the body to extrude up to.")
            targets = [base.get(ext.body).shape]
        else:
            targets = [b.shape for b in base.bodies(SOLID)]
            if not targets:
                raise topo.GeometryError("Up To Next: nothing is in the way of the surface. "
                                         "Use Blind or another end condition.")
        return sheet.cut_by_bodies(long_, targets, ref, tag, c)
    if c == MID_PLANE:
        if not first:
            raise topo.GeometryError("Mid Plane can't be used for Direction 2.")
        if ext.draft:
            a = mk(prof, d, ext.depth / 2.0)
            b = mk(prof, -d, ext.depth / 2.0)
            return sheet.shells(a.Faces + b.Faces, tag)
        return _sheet_prism(_shift_prof(prof, d * (-ext.depth / 2.0)), d, ext.depth, tag)
    raise topo.GeometryError("Unknown end condition " + c)


def _target_face(ext, d, c):
    if ext.face is None:
        raise topo.GeometryError("{}: pick a face or plane.".format(c))
    face = ext.face
    if c == OFFSET_FROM_SURFACE and ext.offset:
        off = ext.offset if ext.reverse_offset else -ext.offset
        if _is_plane(face):
            n = _plane_normal(face)
            s = 1.0 if n.dot(d) > 0 else -1.0
            face = face.copy()
            face.translate(n * (off * s))
        else:
            try:
                face = face.makeOffsetShape(off, 1e-6).Faces[0]
            except Exception as e:
                raise topo.GeometryError("Offset From Surface: the surface can't be offset "
                                         "by that distance ({}).".format(e))
    return face


def sheet_shape(p, base):
    """Surface mode: the profile's curves extruded into a surface body (closed at
    both ends with Cap end)."""
    tag = p.tag
    if p.cap_end:
        if not p.faces:
            raise topo.GeometryError("Cap end needs a closed sketch (or closed regions in "
                                     "Selected Contours).")
        solid = Params.__new__(Params)
        solid.__dict__.update(p.__dict__)
        solid.mode = "Add"
        solid.thin = None
        solid.open_wires = []
        return sheet.shell_of(tool_shape(solid, base), tag)
    prof = (list(p.faces), list(p.open_wires))
    if not prof[0] and not prof[1]:
        raise topo.GeometryError("Pick a sketch, or regions of one, to extrude.")
    n = App.Vector(p.normal)
    n.normalize()
    d = -n if p.reverse else n
    if p.direction is not None:
        if p.dir1.draft or (p.dir2 is not None and p.dir2.draft):
            raise topo.GeometryError("Draft works with the sketch's normal direction; clear "
                                     "the direction of extrusion or the draft.")
        d = App.Vector(p.direction).normalize()
        if p.reverse:
            d = -d
    shift = _start_shift(p, base)
    if abs(shift) > topo.TOL:
        prof = _shift_prof(prof, n * shift)
    shapes = [b.shape for b in base]
    big = topo.big_length(Part.makeCompound(sheet.wires_of(*prof)), *shapes)
    parts = [_sheet_direction(p, base, prof, d, p.dir1, tag, big, True)]
    if p.dir1.condition == THROUGH_ALL_BOTH:
        ref = Part.makeCompound(sheet.wires_of(*prof))
        parts.append(_sheet_prism(prof, -d, through_length(ref, base, -d, big), tag,
                                  p.dir1.draft, p.dir1.draft_outward))
    elif p.dir2 is not None and p.dir1.condition != MID_PLANE:
        parts.append(_sheet_direction(p, base, prof, -d, p.dir2, tag, big, False))
    if len(parts) == 1:
        return parts[0]
    return sheet.shells([f for x in parts for f in x.Faces], tag)


def _origin_of(faces):
    return faces[0].Vertexes[0].Point if faces and faces[0].Vertexes else App.Vector()


# ---------------------------------------------------------------- compute

def tool_shape(p, base):
    tag = p.tag
    if p.thin is not None:
        faces = thin_faces(p.faces, p.open_wires, p.thin, tag)
    else:
        if p.open_wires and not p.faces:
            # An open sketch without Thin Feature makes a surface body (spec 3.4).
            if p.mode != "Add":
                raise topo.GeometryError("A cut needs a closed sketch. Close it, pick closed "
                                         "regions in Selected Contours, or tick Thin Feature.")
            if p.dir1.condition not in (BLIND, MID_PLANE, THROUGH_ALL, THROUGH_ALL_BOTH) or \
                    p.dir1.draft or (p.dir2 is not None and p.dir2.condition != BLIND):
                raise topo.GeometryError("An open sketch makes a surface: use Blind, Mid Plane "
                                         "or Through All, without draft.")
        faces = list(p.faces) or list(p.open_wires)
    if not faces:
        raise topo.GeometryError("Pick a sketch, or regions of one, to extrude.")
    n = App.Vector(p.normal)
    n.normalize()
    d = -n if p.reverse else n
    if p.direction is not None:
        if p.dir1.draft or (p.dir2 is not None and p.dir2.draft):
            raise topo.GeometryError("Draft works with the sketch's normal direction; clear "
                                     "the direction of extrusion or the draft.")
        d = App.Vector(p.direction).normalize()
        if p.reverse:
            d = -d
    shift = _start_shift(p, base)
    if abs(shift) > topo.TOL:
        faces = _shift_faces(faces, n * shift)
    shapes = [b.shape for b in base]
    big = topo.big_length(Part.makeCompound(faces), *shapes)

    first = _direction_solid(p, base, faces, d, p.dir1, tag, big, True)
    parts = [first]
    if p.dir1.condition == THROUGH_ALL_BOTH:
        parts.append(_prism(faces, -d, through_length(Part.makeCompound(faces), base, -d, big),
                            tag, p.dir1.draft, p.dir1.draft_outward))
    elif p.dir2 is not None and p.dir1.condition != MID_PLANE:
        parts.append(_direction_solid(p, base, faces, -d, p.dir2, tag, big, False))
    tool = parts[0] if len(parts) == 1 else topo.refine(topo.fuse(parts[0], parts[1:], tag), tag)

    if p.thin is not None and p.thin.cap_ends:
        tool = _cap_ends(p, base, tool, d, tag)
    return tool


def _cap_ends(p, base, tool, d, tag):
    """Thin Feature with Cap ends: close a thin closed profile at both ends."""
    if p.open_wires or not p.faces:
        raise topo.GeometryError("Cap ends needs a closed profile.")
    t = p.thin
    if t.cap <= 0:
        raise topo.GeometryError("Cap ends: the cap thickness must be greater than zero.")
    full = Params.__new__(Params)
    full.__dict__.update(p.__dict__)
    full.thin = None
    # Outer boundary of the thin region, as a solid.
    if t.kind == THIN_ONE:
        grow = 0.0 if t.reverse else t.t1
    elif t.kind == THIN_MID:
        grow = t.t1 / 2.0
    else:
        grow = t.t2 if t.reverse else t.t1
    full.faces = [topo.offset2d(f, grow, tag, join=2).Faces[0] if grow else f for f in p.faces]
    outer = tool_shape(full, base)
    inner_faces = full.faces
    shrink = (t.t1 if t.kind != THIN_TWO else t.t1 + t.t2)
    if t.kind == THIN_MID:
        shrink = t.t1
    inner_faces = [topo.offset2d(f, -shrink, tag, join=2) for f in full.faces]
    inner_faces = [g.Faces[0] for g in inner_faces if g.Faces]
    if not inner_faces:
        return outer
    # The hollow is the outer solid shrunk by the cap at each end along d.
    hollow_src = Params.__new__(Params)
    hollow_src.__dict__.update(full.__dict__)
    hollow_src.faces = inner_faces
    hollow = tool_shape(hollow_src, base)
    span = _span(outer, d)
    lo = span[0] + t.cap
    hi = span[1] - t.cap
    if hi - lo <= topo.TOL:
        raise topo.GeometryError("Cap ends: the caps are thicker than the extrusion.")
    slab_faces = _shift_faces(inner_faces, d * (lo - _span(Part.makeCompound(inner_faces), d)[0]))
    slab = _prism(slab_faces, d, hi - lo, tag)
    cavity = topo.common(hollow, [slab], tag)
    return topo.refine(topo.cut(outer, [cavity], tag), tag)


def _span(shape, d):
    vals = [v.Point.dot(d) for v in shape.Vertexes]
    return min(vals), max(vals)


def compute(p, base):
    """Run the extrude on ``base`` (a BodySet). Returns (Result, tool, preview)."""
    if p.mode == sheet.SURFACE:
        tool = sheet_shape(p, base)
        res = common.apply_add(base, tool, p.feature, p.tag, False, p.scope, p.alloc)
        return res, tool, tool
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
