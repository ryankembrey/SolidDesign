# SPDX-License-Identifier: LGPL-2.1-or-later
"""Split Line (SolidWorks' Split Line): splits faces of a body into more faces,
without changing its shape, for a parting line, a draft or a face to colour.

- **Projection:** a sketch projected onto the faces (both ways along the sketch's
  normal, or one way with Single direction).
- **Intersection:** where planes, faces or bodies cut the faces.
- **Silhouette:** the outline of the faces seen along a direction (where round
  faces turn away), e.g. the parting line of a shaft.
"""

import FreeCAD as App
import Part

from .. import topo
from ..bodies import SOLID
from . import common, edges as edgemod

PROJECTION, INTERSECTION, SILHOUETTE = "Projection", "Intersection", "Silhouette"
TYPES = [SILHOUETTE, PROJECTION, INTERSECTION]      # SolidWorks' order


class Params(object):
    def __init__(self):
        self.kind = PROJECTION
        self.faces = []             # faces to split (shapes from the model before)
        self.sketch = None          # Projection: the sketch's shape
        self.normal = None          # Projection: the sketch's normal
        self.single = False         # Projection: one direction only
        self.reverse = False        # Projection (single) / Silhouette: the other way
        self.tools = []             # Intersection: splitting shapes
        self.direction = None       # Silhouette: direction of pull (vector)
        self.feature = "SplitLine"
        self.tag = 1


def compute(p, base):
    if not p.faces:
        raise topo.GeometryError("Pick the faces to split.")
    groups = edgemod.faces_by_body(base, p.faces)
    out = base.copy()
    res = common.Result(out)
    changed = []
    for bid, faces in groups.items():
        body = base.get(bid)
        edges = _edges(p, faces)
        if not edges:
            raise topo.GeometryError(_nothing(p))
        shape = topo.tagged(body.shape, p.tag)
        before = len(shape.Faces)
        r = topo.general_fuse(shape, [topo.tagged(Part.makeCompound(edges), p.tag)], p.tag)
        kept = r.Solids if body.kind == SOLID else r.Shells or r.Faces
        if not kept:
            raise topo.GeometryError("The split line couldn't split the faces.")
        new = kept[0] if len(kept) == 1 else topo.compound(kept, p.tag)
        if len(new.Faces) <= before:
            raise topo.GeometryError(_nothing(p))
        if body.kind == SOLID and abs(new.Volume - shape.Volume) > 1e-6 * max(1.0, shape.Volume):
            raise topo.GeometryError("Splitting the faces changed the body; check the curves.")
        out.replace(bid, new, p.feature)
        res.touched.append(bid)
        changed.append(Part.makeCompound(edges))
    return res, topo.compound(changed, p.tag) if changed else None


def _nothing(p):
    if p.kind == PROJECTION:
        return "The sketch doesn't land on the faces. Check the faces, or Single direction."
    if p.kind == INTERSECTION:
        return "The splitting tools don't cut the faces."
    return "The faces have no silhouette along that direction (planar faces have none)."


def _edges(p, faces):
    out = []
    for f in faces:
        if p.kind == PROJECTION:
            out.extend(_project(p, f))
        elif p.kind == INTERSECTION:
            if not p.tools:
                raise topo.GeometryError("Pick the planes, faces or bodies that split the faces.")
            for t in p.tools:
                try:
                    out.extend(f.section(t).Edges)
                except Exception:
                    pass
        else:
            if p.direction is None:
                raise topo.GeometryError("Pick the direction of pull: a plane, face or edge.")
            out.extend(_silhouette(p, f))
    return [e for e in out if e.Length > 1e-7]


def _project(p, f):
    if p.sketch is None:
        raise topo.GeometryError("Pick the sketch to project.")
    n = App.Vector(p.normal)
    n.normalize()
    dirs = [-n if p.reverse else n] if p.single else [n, -n]
    origin = p.sketch.Vertexes[0].Point if p.sketch.Vertexes else App.Vector()
    out = []
    for d in dirs:
        try:
            pr = f.makeParallelProjection(p.sketch, d)
        except Exception:
            continue
        for e in pr.Edges:
            # Only what the sketch reaches travelling this way.
            if (e.CenterOfMass - origin).dot(d) < -1e-9 or f.distToShape(e)[0] > 1e-6:
                continue
            if not any(edgemod._same(e, x) for x in out):
                out.append(e)
    return out


def _silhouette(p, f):
    d = App.Vector(p.direction)
    d.normalize()
    if p.reverse:
        d = -d
    up = App.Vector(0, 0, 1) if abs(d.z) < 0.9 else App.Vector(1, 0, 0)
    try:
        r = f.reflectLines(d, App.Vector(), up, "OutLine", True, True)
    except Exception:
        return []
    return [e for e in r.Edges if f.distToShape(e)[0] < 1e-6]
