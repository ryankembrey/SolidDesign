# SPDX-License-Identifier: LGPL-2.1-or-later
"""Sketch regions and contours for Selected Contours (spec section 5.4).

A sketch's *regions* come from its planar arrangement: every sketch edge is
split against every other, and the pieces bound faces. This handles sketches
with overlapping or open geometry, as SolidWorks does.

A picked region is stored by what bounds it: the Sketcher geometry IDs of its
edges, plus a point inside it (in sketch coordinates). It is never stored by
region index (spec section 7).
"""

import re

import FreeCAD as App
import Part

from . import topo

_GEO_ID = re.compile(r"(?:^|;)g(\d+)")
POINT_TOL = 1e-5


class Region(object):
    __slots__ = ("face", "geo_ids", "point")

    def __init__(self, face, geo_ids, point):
        self.face = face            # Part.Face in global coordinates
        self.geo_ids = geo_ids      # frozenset of Sketcher geometry IDs
        self.point = point          # App.Vector, sketch coordinates (z = 0)

    def key(self):
        return encode(self.geo_ids, self.point)

    def __repr__(self):
        return "<Region ids={} area={:.3f}>".format(sorted(self.geo_ids), self.face.Area)


def encode(geo_ids, point):
    return "ids={};pt={:.6f},{:.6f}".format(",".join(str(i) for i in sorted(geo_ids)),
                                             point.x, point.y)


def decode(key):
    try:
        ids_part, pt_part = key.split(";")
        ids = frozenset(int(i) for i in ids_part[4:].split(",") if i)
        x, y = (float(v) for v in pt_part[3:].split(","))
        return ids, App.Vector(x, y, 0)
    except Exception:
        raise topo.GeometryError("A stored contour can't be read ({}). Re-pick it.".format(key))


def edge_geo_id(sketch_shape, index):
    """The Sketcher geometry ID behind ``EdgeN`` of a sketch's shape, or None."""
    try:
        name = sketch_shape.getElementMappedName("Edge{}".format(index))
    except Exception:
        return None
    if isinstance(name, (tuple, list)):
        name = name[0] if name else ""
    m = _GEO_ID.search(name or "")
    return int(m.group(1)) if m else None


def _inner_point(face):
    """A point strictly inside a face."""
    c = face.CenterOfMass
    try:
        if face.isInside(c, POINT_TOL, False):
            return c
    except Exception:
        pass
    try:
        pts, tris = face.tessellate(max(face.BoundBox.DiagonalLength / 50.0, 1e-3))
        best = None
        for t in tris:
            p = (pts[t[0]] + pts[t[1]] + pts[t[2]]) * (1.0 / 3.0)
            if face.isInside(p, POINT_TOL, False):
                area = ((pts[t[1]] - pts[t[0]]).cross(pts[t[2]] - pts[t[0]])).Length
                if best is None or area > best[0]:
                    best = (area, p)
        if best:
            return best[1]
    except Exception:
        pass
    return c


def sketch_placement(sketch):
    try:
        return sketch.getGlobalPlacement()
    except Exception:
        return sketch.Placement


def sketch_normal(sketch):
    return sketch_placement(sketch).Rotation.multVec(App.Vector(0, 0, 1))


def regions(sketch, tag=None):
    """All bounded regions of a sketch, in a stable order (by area, then position)."""
    shape = topo.shape_of(sketch)
    edges = shape.Edges
    if not edges:
        return []
    pl = sketch_placement(sketch)
    inv = pl.inverse()
    tag = tag or shape.Tag or 1
    # Bounding rectangle in sketch coordinates, a margin around the geometry.
    local = shape.copy()
    local.transformShape(inv.toMatrix(), False)
    bb = local.BoundBox
    margin = max(bb.DiagonalLength * 0.1, 1.0)
    big = Part.makePlane(bb.XLength + 2 * margin, bb.YLength + 2 * margin,
                         App.Vector(bb.XMin - margin, bb.YMin - margin, 0))
    big.Placement = pl
    corner = pl.multVec(App.Vector(bb.XMin - margin * 0.5, bb.YMin - margin * 0.5, 0))
    arranged = topo.general_fuse(big, edges, tag)

    found = []
    for f in arranged.Faces:
        try:
            if f.isInside(corner, POINT_TOL, True):
                continue            # the region outside every contour
        except Exception:
            continue
        ids = set()
        for e in f.Edges:
            mid = e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))
            for i, se in enumerate(edges, 1):
                box = App.BoundBox(se.BoundBox)
                box.enlarge(1e-5)
                if not box.isInside(mid):
                    continue
                try:
                    if se.distToShape(Part.Vertex(mid))[0] < 1e-6:
                        gid = edge_geo_id(shape, i)
                        if gid is not None:
                            ids.add(gid)
                except Exception:
                    pass
        p = inv.multVec(_inner_point(f))
        found.append(Region(f, frozenset(ids), App.Vector(p.x, p.y, 0)))
    found.sort(key=lambda r: (-round(r.face.Area, 6), round(r.point.x, 6), round(r.point.y, 6)))
    return found


def resolve(keys, sketch, tag=None):
    """The regions for stored keys.

    Returns (faces, repaired) where ``repaired`` lists keys matched only by
    their inside point (their bounding geometry changed). Raises GeometryError
    when a key matches no region.
    """
    regs = regions(sketch, tag)
    pl = sketch_placement(sketch)
    faces = []
    repaired = []
    for key in keys:
        ids, pt = decode(key)
        gp = pl.multVec(pt)
        same = [r for r in regs if r.geo_ids == ids]
        if len(same) == 1:
            faces.append(same[0].face)
            continue
        inside = [r for r in regs if r.face.isInside(gp, POINT_TOL, False)]
        if len(same) > 1:
            hit = [r for r in same if r in inside]
            if len(hit) == 1:
                faces.append(hit[0].face)
                continue
        if len(inside) == 1:
            faces.append(inside[0].face)
            repaired.append(key)
            continue
        raise topo.GeometryError(
            "A selected contour of {} no longer exists. Re-pick it in Selected Contours."
            .format(sketch.Label))
    return faces, repaired


def region_at(sketch, point, tag=None):
    """The region containing a global point, or None (used when picking)."""
    for r in regions(sketch, tag):
        if r.face.isInside(point, POINT_TOL, False):
            return r
    return None


def default_profile(sketch, tag):
    """The whole sketch as faces (nested contours become holes), as SolidWorks
    uses a sketch when no contours are selected.

    Raises GeometryError with a clear message for open or overlapping sketches.
    Returns (faces_compound, open_wires).
    """
    shape = topo.shape_of(sketch)
    if not shape.Edges:
        raise topo.GeometryError("{} is empty.".format(sketch.Label))
    wires = shape.Wires
    loose = [e for e in shape.Edges if not any(e.isSame(we) for w in wires for we in w.Edges)]
    closed = [w for w in wires if w.isClosed()]
    open_ = [w for w in wires if not w.isClosed()] + [Part.Wire(e) for e in loose]
    for i in range(len(closed)):
        for j in range(i + 1, len(closed)):
            try:
                if closed[i].distToShape(closed[j])[0] < 1e-7:
                    raise topo.GeometryError(
                        "{} has contours that touch or overlap. Pick the regions to use in "
                        "Selected Contours.".format(sketch.Label))
            except topo.GeometryError:
                raise
            except Exception:
                pass
    if not closed:
        return None, open_
    if open_:
        raise topo.GeometryError(
            "{} has both open and closed contours. Pick the regions to use in Selected "
            "Contours, or make every contour closed.".format(sketch.Label))
    faces = topo.make_faces(closed, tag)
    return faces, []
