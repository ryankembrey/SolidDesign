# SPDX-License-Identifier: LGPL-2.1-or-later
"""Indent (SolidWorks' Indent): a target body pressed into the shape of a tool
body. The tool's regions outside the target are listed; the target grows round
the regions kept (a wall of the given thickness, a clearance off the tool) and is
cut where the tool goes through it. With Cut, the target is only cut, the
clearance bigger than the tool.

The tool body is left as it is.
"""

import Part

from .. import topo
from ..bodies import SOLID
from . import common
from .intersect import inner_point


class Params(object):
    def __init__(self):
        self.target = ""            # body ID
        self.tool = ""              # body ID
        self.excluded = []          # points inside the tool regions not kept
        self.thickness = 1.0
        self.clearance = 0.0
        self.cut = False
        self.feature = "Indent"
        self.tag = 1
        self.alloc = None


def _offset(solid, d, tag, what):
    """A solid grown by ``d`` (rounded where it turns a corner)."""
    if d <= 1e-9:
        return solid
    try:
        s = solid.makeOffsetShape(d, 1e-6, join=0)
    except Exception as e:
        raise topo.GeometryError("Indent: the {} can't be grown by {:g} mm ({}).".format(
            what, d, e))
    if s.isNull() or not s.Solids:
        raise topo.GeometryError("Indent: the {} can't be grown by {:g} mm.".format(what, d))
    return topo.tagged(s, tag)


def _bodies(p, base):
    if not p.target or p.target not in base:
        raise topo.GeometryError("Pick the target body.")
    if not p.tool or p.tool not in base:
        raise topo.GeometryError("Pick the tool body (the shape to press in).")
    if p.target == p.tool:
        raise topo.GeometryError("The tool must be another body than the target.")
    t, k = base.get(p.target), base.get(p.tool)
    if t.kind != SOLID or k.kind != SOLID:
        raise topo.GeometryError("Indent works on solid bodies.")
    if not topo.touches(t.shape, k.shape):
        raise topo.GeometryError("The tool doesn't touch the target.")
    return t.shape, k.shape


def regions(p, base):
    """The tool's regions outside the target: [solid]."""
    target, tool = _bodies(p, base)
    out = topo.cut(tool, [target], p.tag).Solids
    out = [s for s in out if s.Volume > 1e-9]
    return sorted(out, key=lambda s: (round(s.CenterOfMass.z, 6), round(s.CenterOfMass.y, 6),
                                      round(s.CenterOfMass.x, 6)))


def _excluded(solid, points):
    return any(solid.isInside(pt, 1e-6, True) for pt in points)


def compute(p, base):
    """Returns (Result, preview)."""
    if p.thickness < 0 or p.clearance < 0:
        raise topo.GeometryError("Thickness and clearance can't be negative.")
    target, tool = _bodies(p, base)
    tag = p.tag
    hole = _offset(tool, p.clearance, tag, "tool")
    if p.cut:
        r = topo.cut(target, [hole], tag)
        preview = topo.common(hole, [target], tag)
    else:
        if p.thickness <= 1e-9:
            raise topo.GeometryError("The thickness must be greater than zero.")
        keep = [s for s in regions(p, base) if not _excluded(s, p.excluded)]
        if not keep:
            r = topo.cut(target, [hole], tag)
            preview = None
        else:
            walls = [_offset(s, p.clearance + p.thickness, tag, "kept region") for s in keep]
            grown = topo.fuse(target, walls, tag)
            r = topo.cut(grown, [hole], tag)
            preview = topo.cut(topo.compound(walls, tag), [hole, target], tag)
    r = topo.refine(r, tag)
    solids = r.Solids
    if not solids:
        raise topo.GeometryError("Nothing is left of the target.")
    out = base.copy()
    res = common.Result(out)
    if len(solids) == 1:
        out.replace(p.target, solids[0], p.feature)
        p.alloc.keep(p.target, solids[0])
    else:
        from ..bodies import split_pieces
        named = split_pieces(p.target, solids, p.alloc)
        out.replace(p.target, named[0][1], p.feature)
        out.insert_many_after(p.target, [(pid, s, p.feature) for pid, s in named[1:]])
        res.created.extend(pid for pid, _s in named[1:])
    res.touched.append(p.target)
    return res, preview


REEXPORTED = (inner_point, Part)
