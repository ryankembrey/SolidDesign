# SPDX-License-Identifier: LGPL-2.1-or-later
"""Offset Surface and Move Face (SolidWorks' Insert > Surface > Offset and
Insert > Face > Move Face).

- **Offset Surface:** faces (of solids or surfaces) offset by a distance into a
  new surface body; offset 0 copies them.
- **Move Face:** faces of a solid moved; the faces around them extend or trim:
  - Offset: along their normals by a distance;
  - Translate: planar faces along a direction by a distance (a plane only moves
    along its normal, so the part of the move along the face changes nothing);
  - Rotate: planar faces turned about an axis parallel to them.
"""

import math

import FreeCAD as App
import Part

from .. import topo
from ..bodies import SOLID, SURFACE
from . import common, edges as edgemod

OFFSET, TRANSLATE, ROTATE = "Offset", "Translate", "Rotate"
MOVE_TYPES = [OFFSET, TRANSLATE, ROTATE]


class OffsetParams(object):
    def __init__(self):
        self.faces = []
        self.distance = 1.0
        self.flip = False
        self.feature = "OffsetSurface"
        self.tag = 1
        self.alloc = None


def offset_surface(p, base):
    if not p.faces:
        raise topo.GeometryError("Pick the faces or surfaces to offset.")
    groups = edgemod.faces_by_body(base, p.faces)
    d = -p.distance if p.flip else p.distance
    made = []
    for bid, faces in groups.items():
        faces = [topo.tagged(f, p.tag) for f in faces]
        try:
            shell = Part.Shell(faces) if len(faces) > 1 else faces[0]
        except Exception:
            shell = Part.makeCompound(faces)
        if abs(d) < 1e-9:
            made.append(shell.copy())
            continue
        try:
            o = shell.makeOffsetShape(d, 1e-6, join=2)
        except Exception as e:
            raise topo.GeometryError("The faces couldn't be offset by {:g}: {}. Try a smaller "
                                     "distance.".format(d, topo._msg(e)))
        if o.isNull() or not o.Faces:
            raise topo.GeometryError("The offset made no faces. Try a smaller distance.")
        made.append(o)
    out = base.copy()
    res = common.Result(out)
    surfaces = [topo.tagged(m, p.tag) for m in made]
    ids = p.alloc.take(surfaces) if p.alloc is not None else \
        ["{}:{}".format(p.feature, i + 1) for i in range(len(surfaces))]
    for i, s in zip(ids, surfaces):
        out.add(i, s, p.feature, SURFACE)
        res.created.append(i)
    return res, topo.compound(surfaces, p.tag)


class MoveParams(object):
    def __init__(self):
        self.kind = OFFSET
        self.faces = []
        self.distance = 1.0
        self.direction = None       # Translate: vector
        self.axis = None            # Rotate: (point, unit direction)
        self.angle = 10.0
        self.flip = False
        self.feature = "MoveFace"
        self.tag = 1


def move_face(p, base):
    if not p.faces:
        raise topo.GeometryError("Pick the faces to move.")
    groups = edgemod.faces_by_body(base, p.faces)
    out = base.copy()
    res = common.Result(out)
    changed = []
    for bid, faces in groups.items():
        body = base.get(bid)
        if body.kind != SOLID:
            raise topo.GeometryError("Move Face works on solid bodies.")
        shape = topo.tagged(body.shape, p.tag)
        if p.kind == ROTATE:
            r = _rotate(shape, faces, p)
        else:
            offsets = {}
            for f in faces:
                f = edgemod.find_in(shape, f) or f
                offsets[f] = _offset_for(f, p)
            if all(abs(v) < 1e-12 for v in offsets.values()):
                raise topo.GeometryError("The move is square to the faces: it changes nothing.")
            r = topo.offset_faces(shape, offsets, p.tag)
        out.replace(bid, r, p.feature)
        res.touched.append(bid)
        changed.append(r)
    return res, topo.compound(changed, p.tag)


def _normal(f):
    u0, u1, v0, v1 = f.ParameterRange
    return f.normalAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))


def _offset_for(f, p):
    if p.kind == OFFSET:
        return -p.distance if p.flip else p.distance
    # Translate
    if f.Surface.TypeId != "Part::GeomPlane":
        raise topo.GeometryError("Translate moves planar faces in this version; use Offset "
                                 "for curved faces.")
    if p.direction is None:
        raise topo.GeometryError("Pick the direction to move the faces along.")
    d = App.Vector(p.direction)
    d.normalize()
    if p.flip:
        d = -d
    return d.dot(_normal(f)) * p.distance


def _rotate(shape, faces, p):
    if p.axis is None:
        raise topo.GeometryError("Pick the axis to turn the faces about.")
    if abs(p.angle) < 1e-9:
        raise topo.GeometryError("The angle must not be zero.")
    if abs(p.angle) >= 89:
        raise topo.GeometryError("The angle must be less than 89°.")
    pt, e = p.axis
    e = App.Vector(e)
    e.normalize()
    ang = -p.angle if p.flip else p.angle
    rot = App.Rotation(e, ang)
    r = shape
    for f0 in faces:
        f = edgemod.find_in(r, f0) or f0
        if f.Surface.TypeId != "Part::GeomPlane":
            raise topo.GeometryError("Rotate turns planar faces in this version.")
        n = _normal(f)
        if abs(n.dot(e)) > 1e-6:
            raise topo.GeometryError("The axis must be parallel to the faces it turns.")
        c = f.Vertexes[0].Point
        # The face's plane, turned about the axis.
        c2 = pt + rot.multVec(c - pt)
        n2 = rot.multVec(n)
        # Where the old and new planes meet: the hinge the face turns about.
        hinge_dir = n.cross(n2)
        hinge_dir.normalize()
        h1, h2 = n.dot(c), n2.dot(c2)
        hinge = (n2.cross(hinge_dir) * h1 + hinge_dir.cross(n) * h2) * \
            (1.0 / hinge_dir.dot(n.cross(n2)))
        pull = n2 - n * n2.dot(n)
        pull.normalize()
        idx = next(i for i, x in enumerate(r.Faces, 1) if x.isSame(f))
        r = topo.draft(r, [idx], hinge, pull, pull, abs(ang), p.tag)
    return r
