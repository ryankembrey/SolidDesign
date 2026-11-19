# SPDX-License-Identifier: LGPL-2.1-or-later
"""Shell (SolidWorks' Shell): hollow a body, removing the picked faces; with
Multi-thickness, some faces get their own wall, thicker or thinner."""

import FreeCAD as App

from .. import topo
from ..bodies import SOLID
from . import common, edges as edgemod


class Params(object):
    def __init__(self):
        self.faces = []             # faces to remove (shapes from the model before)
        self.body = None            # body to hollow when no face is removed
        self.thickness = 1.0
        self.outward = False
        self.multi = []             # [(face, thickness)]
        self.feature = "Shell"
        self.tag = 1


def compute(p, base):
    if p.thickness <= 0:
        raise topo.GeometryError("The thickness must be greater than zero.")
    groups = edgemod.faces_by_body(base, p.faces) if p.faces else {}
    if not groups:
        if p.body is None:
            solids = base.ids(SOLID)
            if len(solids) != 1:
                raise topo.GeometryError("Pick faces to remove, or the body to hollow.")
            p.body = solids[0]
        if p.body not in base:
            raise topo.GeometryError("The body to shell no longer exists. Re-pick it.")
        groups = {p.body: []}
    if len(groups) > 1:
        raise topo.GeometryError("The faces to remove are on more than one body. Shell one "
                                 "body at a time.")
    bid, faces = list(groups.items())[0]
    body = base.get(bid)
    if body.kind != SOLID:
        raise topo.GeometryError("Only solid bodies can be shelled.")
    shape = topo.tagged(body.shape, p.tag)
    faces = [edgemod.find_in(shape, f) for f in faces]     # tagging may copy the shape
    off = p.thickness if p.outward else -p.thickness
    warnings = []
    try:
        if faces:
            r = shape.makeThickness(faces, off, 1e-3)
        else:
            other = shape.makeOffsetShape(off, 1e-3)
            r = topo.cut(other, [shape], p.tag) if p.outward else topo.cut(shape, [other], p.tag)
    except topo.GeometryError:
        raise
    except Exception:
        r = None
    if (r is None or r.isNull() or not r.isValid()) and faces and not p.outward:
        r = _fallback(shape, faces, p.thickness, p.tag)
        if r is not None:
            warnings.append("OpenCASCADE couldn't shell this body directly; it was shelled by "
                            "offsetting it, so the walls next to the open faces are approximate.")
    if r is not None and not r.isNull() and r.Solids and not p.outward:
        # OCC can return a "valid" but inside-out result when the wall is too thick.
        bb, ob = r.BoundBox, shape.BoundBox
        ob.enlarge(1e-6)
        if not ob.isInside(bb) or not 0 < r.Volume < shape.Volume - 1e-9:
            r = None
    if r is None or r.isNull() or not r.isValid() or not r.Solids:
        raise topo.GeometryError("The shell failed. The thickness ({:g}) may be more than a "
                                 "face or fillet radius allows: try a smaller thickness. Some "
                                 "lofted or blended faces can't be offset at all by "
                                 "OpenCASCADE; then shell before that feature.".format(
                                     p.thickness))
    # Multi-thickness: each listed face has its own wall, thicker or thinner.
    thick, thin = [], []
    for face, t in p.multi:
        if t <= 0:
            raise topo.GeometryError("A multi-thickness face's thickness must be greater than "
                                     "zero.")
        f = edgemod.find_in(body.shape, face)
        if f is None:
            raise topo.GeometryError("A multi-thickness face isn't on the shelled body.")
        if f.Surface.TypeId != "Part::GeomPlane":
            raise topo.GeometryError("Multi-thickness faces must be planar in this version.")
        if abs(t - p.thickness) < 1e-9:
            continue
        (thick if t > p.thickness else thin).append((f, t))
    for f, t in thick:
        n = f.normalAt(0, 0)
        slab = topo.common(topo.extrude(f, n * (-t), p.tag), [shape], p.tag)
        r = topo.refine(topo.fuse(r, [slab], p.tag), p.tag)
    if thin:
        if p.outward:
            raise topo.GeometryError("Thinner multi-thickness faces work on inward shells; "
                                     "untick Shell outward or make the face thicker.")
        r = _thinner(shape, r, thin, p.thickness, p.tag)
    out = base.copy()
    out.replace(bid, r, p.feature)
    res = common.Result(out)
    res.touched.append(bid)
    res.warnings.extend(warnings)
    return res, r


def _thinner(shape, shelled, thin, thickness, tag):
    """Thin the walls behind ``thin`` faces: the hollow, moved towards each face by
    the difference (and towards each group of them, so their shared corners
    open up too), is cut from the shell."""
    import itertools
    hollow = topo.cut(shape, [shelled], tag)
    if not hollow.Solids:
        raise topo.GeometryError("Couldn't find the shell's hollow to thin its walls.")
    shifts = [f.normalAt(0, 0) * (thickness - t) for f, t in thin]
    sizes = range(1, min(len(shifts), 4) + 1) if len(shifts) <= 4 else (1, 2)
    moved = []
    for k in sizes:
        for combo in itertools.combinations(shifts, k):
            v = App.Vector()
            for x in combo:
                v += x
            if v.Length > 1e-9:
                moved.append(topo.transformed(hollow, App.Placement(v, App.Rotation()), tag))
    out = topo.refine(topo.cut(shelled, moved, tag), tag)
    if not out.Solids or not out.isValid():
        raise topo.GeometryError("Thinning the multi-thickness faces failed.")
    return out


def _fallback(shape, faces, t, tag):
    """Hollow by subtracting an inward offset, then open each (planar) face through
    the wall over the hollow's footprint."""
    if any(f.Surface.TypeId != "Part::GeomPlane" for f in faces):
        return None
    try:
        inner = topo.tagged(shape.makeOffsetShape(-t, 1e-3), tag)
        if not inner.Solids or inner.Volume >= shape.Volume:
            return None
        cuts = [inner]
        for f in faces:
            n = f.normalAt(0, 0)
            prism = topo.extrude(f.translated(n * 0.01), n * (-(t + 0.02)), tag)
            cuts.append(topo.common(prism, [topo.transformed(inner, App.Placement(n * (t + 0.02),
                                                                                  App.Rotation()),
                                                             tag)], tag))
        r = topo.refine(topo.cut(shape, cuts, tag), tag)
        return r if r.isValid() and r.Solids else None
    except Exception:
        return None
