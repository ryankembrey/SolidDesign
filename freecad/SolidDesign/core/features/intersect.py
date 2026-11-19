# SPDX-License-Identifier: LGPL-2.1-or-later
"""Intersect (SolidWorks' Insert > Features > Intersect).

The picked solids, surfaces and planes cut space into regions. Intersecting
regions are inside a picked solid; internal regions are hollows closed off by
the selections and inside no solid. The regions not excluded become solid
bodies, merged where they touch (Merge result) or one body each. The picked
solids are replaced by the result; picked surfaces are used up when Consume
surfaces is on.
"""

import FreeCAD as App
import Part

from .. import topo
from ..bodies import SOLID, SURFACE
from . import common

INTERSECTING = "Create intersecting regions"
INTERNAL = "Create internal regions"
BOTH = "Create both"
MODES = [BOTH, INTERSECTING, INTERNAL]


class Params(object):
    def __init__(self):
        self.feature = "Intersect"
        self.tag = 1
        self.alloc = None
        self.bodies = []            # body IDs (solids and surfaces)
        self.planes = []            # plane faces (any size; made big here)
        self.mode = BOTH
        self.cap = False            # Cap planar openings on surfaces
        self.excluded = []          # App.Vector: a point inside each excluded region
        self.merge = True
        self.consume = True


def inner_point(solid):
    """A point well inside a solid (its centre of mass when that is inside)."""
    c = solid.CenterOfMass
    if solid.isInside(c, 1e-7, False):
        return c
    size = solid.BoundBox.DiagonalLength
    for f in solid.Faces:
        u0, u1, v0, v1 = f.ParameterRange
        for (a, b) in ((0.5, 0.5), (0.3, 0.6), (0.6, 0.3)):
            u, v = u0 + a * (u1 - u0), v0 + b * (v1 - v0)
            try:
                p = f.valueAt(u, v)
                n = f.normalAt(u, v)
            except Exception:
                continue
            for d in (1e-3, 1e-2, 5e-2):
                q = p - n * (d * size)
                if solid.isInside(q, 1e-7, False):
                    return q
    return c


def _caps(shape):
    """Flat faces closing a surface's planar openings."""
    from .surfaces import free_edges
    out = []
    try:
        loops = Part.sortEdges(free_edges(shape))
    except Exception:
        return out
    for loop in loops:
        w = Part.Wire(loop)
        if not w.isClosed():
            continue
        try:
            f = Part.Face(w)
            if f.isValid() and f.Area > 0 and f.Surface.TypeId == "Part::GeomPlane":
                out.append(f)
        except Exception:
            pass
    return out


def regions(p, base):
    """[(solid, kind, inside_ids)]: every region, kind 'intersecting' or
    'internal', in a fixed order."""
    solids, others = [], []
    for i in p.bodies:
        b = base.get(i)
        if b is None:
            raise topo.GeometryError("A body picked to intersect no longer exists. Re-pick it.")
        if b.kind == SOLID:
            solids.append((i, b.shape))
        else:
            s = b.shape
            others.append(s)
            if p.cap:
                others.extend(_caps(s))
    shapes = [s for _i, s in solids] + others
    if not shapes and not p.planes:
        raise topo.GeometryError("Pick the solids, surfaces or planes to intersect.")
    every = shapes + list(p.planes)
    bb = None
    for s in shapes:
        b = s.BoundBox
        bb = b if bb is None else bb.united(b)
    if bb is None:
        raise topo.GeometryError("Pick at least one body besides the planes.")
    grow = max(bb.DiagonalLength, 1.0)
    big = grow * 4
    planes = []
    for f in p.planes:
        pl = f.Surface
        n = App.Vector(pl.Axis)
        o = App.Vector(pl.Position)
        planes.append(Part.Plane(o, n).toShape(-big, big, -big, big))
    box = Part.makeBox(bb.XLength + 2 * grow, bb.YLength + 2 * grow, bb.ZLength + 2 * grow,
                       App.Vector(bb.XMin - grow, bb.YMin - grow, bb.ZMin - grow))
    _ = every
    try:
        gf = box.generalFuse([s for _i, s in solids] + others + planes)[0]
    except Exception as e:
        raise topo.GeometryError("The selections couldn't be intersected: {}".format(
            topo._msg(e)))
    out = []
    outer = box.Faces
    for r in gf.Solids:
        ip = inner_point(r)
        inside = [i for i, s in solids if s.isInside(ip, 1e-7, False)]
        if inside:
            kind = "intersecting"
        else:
            touches_outside = any(any(_on(f, o) for o in outer) for f in r.Faces)
            if touches_outside:
                continue
            kind = "internal"
        out.append((r, kind, inside))
    out.sort(key=lambda t: (round(t[0].CenterOfMass.z, 4), round(t[0].CenterOfMass.y, 4),
                            round(t[0].CenterOfMass.x, 4)))
    return out


def _on(f, outer):
    """Whether face ``f`` lies on face ``outer`` of the bounding box."""
    if f.Surface.TypeId != "Part::GeomPlane":
        return False
    n1, n2 = f.Surface.Axis, outer.Surface.Axis
    if abs(abs(n1.dot(n2)) - 1) > 1e-9:
        return False
    return abs((f.CenterOfMass - outer.CenterOfMass).dot(n2)) < 1e-7


def wanted(p, regs):
    keep = []
    for r, kind, inside in regs:
        if p.mode == INTERSECTING and kind != "intersecting":
            continue
        if p.mode == INTERNAL and kind != "internal":
            continue
        keep.append((r, kind, inside))
    return keep


def compute(p, base):
    regs = wanted(p, regions(p, base))
    if not regs:
        raise topo.GeometryError("The selections make no {}.".format(
            "closed region" if p.mode != INTERSECTING else "intersecting region"))
    kept = []
    for r, _kind, _inside in regs:
        if any(r.isInside(pt, 1e-6, True) for pt in p.excluded):
            continue
        kept.append(r)
    if not kept:
        raise topo.GeometryError("Every region is excluded; keep at least one.")
    if p.merge and len(kept) > 1:
        fused = kept[0].fuse(kept[1:])
        try:
            fused = fused.removeSplitter()
        except Exception:
            pass
        shapes = list(fused.Solids)
    else:
        shapes = kept
    out = base.copy()
    res = common.Result(out)
    reuse = [i for i in p.bodies if base.get(i).kind == SOLID]
    if p.consume:
        for i in p.bodies:
            if base.get(i).kind == SURFACE:
                out.remove(i)
    shapes = [topo.tagged(s, p.tag) for s in shapes]
    for k, s in enumerate(shapes):
        if k < len(reuse):
            out.replace(reuse[k], s, p.feature)
            res.touched.append(reuse[k])
        else:
            i = p.alloc.take([s])[0] if p.alloc is not None else \
                "{}:{}".format(p.feature, k + 1)
            out.add(i, s, p.feature, SOLID)
            res.created.append(i)
    for i in reuse[len(shapes):]:
        out.remove(i)
    return res, topo.compound(shapes, p.tag)
