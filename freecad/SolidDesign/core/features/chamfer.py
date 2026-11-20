# SPDX-License-Identifier: LGPL-2.1-or-later
"""Chamfer (SolidWorks' Chamfer): Angle Distance, Distance Distance, Vertex,
Offset Face, Face Face."""

import math

import Part

from .. import topo
from . import common, edges as edgemod

ANGLE_DISTANCE = "Angle Distance"
DISTANCE_DISTANCE = "Distance Distance"
VERTEX = "Vertex"
OFFSET_FACE = "Offset Face"
FACE_FACE = "Face Face"
TYPES = [ANGLE_DISTANCE, DISTANCE_DISTANCE, VERTEX, OFFSET_FACE, FACE_FACE]


class Params(object):
    def __init__(self):
        self.kind = ANGLE_DISTANCE
        self.items = []
        self.d1 = 1.0
        self.d2 = 1.0
        self.d3 = 1.0
        self.angle = 45.0
        self.equal = True           # Equal distance
        self.flip = False           # Flip direction
        self.tangent = True
        self.feature = "Chamfer"
        self.tag = 1


def _faces_of(body, edge):
    """The faces of ``body`` on each side of ``edge``, in OCC's ancestor order
    (the first is the one the first distance is measured on)."""
    return [f for f in body.Faces if any(e.isSame(edge) for e in f.Edges)]


def _interior_angle(f1, f2, edge):
    """Angle between two faces across an edge, measured inside the material."""
    mid = edge.valueAt(0.5 * (edge.FirstParameter + edge.LastParameter))
    n1 = f1.normalAt(*f1.Surface.parameter(mid))
    n2 = f2.normalAt(*f2.Surface.parameter(mid))
    return math.pi - n1.getAngle(n2)


def _setbacks(p, body, edge):
    """(distance on the first face, distance on the second face) for an edge."""
    if p.kind in (DISTANCE_DISTANCE, FACE_FACE):
        a, b = p.d1, (p.d1 if p.equal else p.d2)
    elif p.kind == ANGLE_DISTANCE:
        if not 0 < p.angle < 90:
            raise topo.GeometryError("The angle must be between 0 and 90 degrees.")
        a, b = p.d1, p.d1 * math.tan(math.radians(p.angle))
    else:   # OFFSET_FACE: distances measured normal to the faces
        fs = _faces_of(body, edge)
        if len(fs) != 2 or any(f.Surface.TypeId != "Part::GeomPlane" for f in fs):
            raise topo.GeometryError("Offset Face needs edges between two planar faces in "
                                     "this version.")
        th = _interior_angle(fs[0], fs[1], edge)
        if not 1e-6 < th < math.pi - 1e-6:
            raise topo.GeometryError("Offset Face: the faces at an edge are tangent.")
        da, db = p.d1, (p.d1 if p.equal else p.d2)
        x = (db + da * math.cos(th)) / math.sin(th)        # setback on the first face
        y = x * math.cos(th) + da * math.sin(th)           # setback on the second face
        a, b = x, y
    if p.flip:
        a, b = b, a
    if a <= 0 or b <= 0:
        raise topo.GeometryError("The distances must be greater than zero.")
    return a, b


def _vertex_tool(body, v, d1, d2, d3):
    """The corner a vertex chamfer removes: a tetrahedron from the vertex to points
    at d1, d2, d3 along its three edges."""
    es = [e for e in body.Edges if any(x.isSame(v) for x in e.Vertexes)]
    if len(es) != 3 or any(e.Curve.TypeId not in ("Part::GeomLine", "Part::GeomLineSegment")
                           for e in es):
        raise topo.GeometryError("A vertex chamfer needs a corner where exactly three straight "
                                 "edges meet.")
    pts = []
    for e, d in zip(es, (d1, d2, d3)):
        other = e.Vertexes[1].Point if e.Vertexes[0].isSame(v) else e.Vertexes[0].Point
        dirv = other - v.Point
        if d >= dirv.Length:
            raise topo.GeometryError("A vertex chamfer distance is longer than its edge.")
        dirv.normalize()
        pts.append(v.Point + dirv * d)
    o = v.Point
    tris = [(o, pts[0], pts[1]), (o, pts[1], pts[2]), (o, pts[2], pts[0]),
            (pts[0], pts[1], pts[2])]
    faces = [Part.Face(Part.makePolygon([a, b, c, a])) for a, b, c in tris]
    return Part.makeSolid(Part.makeShell(faces))


def face_face_edges(shape, faces):
    """The edges shared by two of ``faces``, each with the face picked first
    (the one the first distance is measured on)."""
    out = []
    for i, f in enumerate(faces):
        for g in faces[i + 1:]:
            for e in f.Edges:
                if any(e.isSame(x) for x in g.Edges) and \
                        not any(e.isSame(x) for x, _ in out):
                    out.append((e, f))
    return out


def _face_face(p, shape, faces):
    """Chamfer the edges between the picked faces, the first distance on the face
    picked first."""
    pairs = face_face_edges(shape, faces)
    if not pairs:
        if len(faces) != 2:
            raise topo.GeometryError(
                "Face Face: the picked faces don't share an edge. To chamfer across a gap, "
                "pick two flat faces.")
        from . import blend
        d1 = p.d1
        d2 = p.d1 if p.equal else p.d2
        if p.flip:
            d1, d2 = d2, d1
        return blend.across_gap(shape, faces[0], faces[1], d1, d2, chamfer=True, tag=p.tag)
    r = shape
    for e, first in pairs:
        a, b = _setbacks(p, shape, e)
        cur = edgemod.find_in(r, e)
        here = edgemod.find_in(r, first)
        if cur is None or here is None:
            raise topo.GeometryError("The chamfers meet at a corner this version can't "
                                     "blend. Chamfer those edges in separate features.")
        owner = _faces_of(r, cur)
        if owner and not owner[0].isSame(here):
            a, b = b, a
        try:
            r = r.makeChamfer(a, b, [cur])
        except Exception:
            r = None
        if r is None or r.isNull() or not r.isValid():
            raise topo.GeometryError("The chamfer failed. The distances may be too large "
                                     "for the faces. Try smaller distances.")
    return r


def compute(p, base):
    if not p.items:
        raise topo.GeometryError("Pick the edges, faces or vertices to chamfer.")
    if p.kind == FACE_FACE:
        faces = [x for x in p.items if x.ShapeType == "Face"]
        if len(faces) < 2:
            raise topo.GeometryError("Face Face: pick at least two faces.")
        out = base.copy()
        res = common.Result(out)
        changed = []
        for bid, fs in edgemod.faces_by_body(base, faces).items():
            body = base.get(bid)
            shape = topo.tagged(body.shape, p.tag)
            own = [edgemod.find_in(shape, f) for f in fs]
            r = topo.refine(_face_face(p, shape, own), p.tag)
            out.replace(bid, r, p.feature)
            res.touched.append(bid)
            changed.append(r)
        return res, (topo.compound(changed, p.tag) if changed else None)
    groups = edgemod.by_body(base, p.items)
    out = base.copy()
    res = common.Result(out)
    changed = []
    for bid, picked in groups.items():
        body = base.get(bid)
        shape = topo.tagged(body.shape, p.tag)
        if p.kind == VERTEX:
            vs = [x for x in picked if x.ShapeType == "Vertex"]
            if not vs:
                raise topo.GeometryError("Vertex chamfer: pick vertices.")
            d2 = p.d1 if p.equal else p.d2
            d3 = p.d1 if p.equal else p.d3
            tools = [_vertex_tool(shape, v, p.d1, d2, d3) for v in vs]
            r = topo.refine(topo.cut(shape, tools, p.tag), p.tag)
        else:
            es = [x for x in picked if x.ShapeType == "Edge"]
            if not es:
                raise topo.GeometryError("Pick edges or faces to chamfer (or switch to Vertex).")
            if p.tangent:
                es = edgemod.tangent_chain(shape, es)
            # One OCC call per set of equal setbacks (Offset Face can differ per edge).
            sets = {}
            for e in es:
                a, b = _setbacks(p, shape, e)
                sets.setdefault((round(a, 9), round(b, 9)), []).append(e)
            r = shape
            for (a, b), group in sets.items():
                cur = [edgemod.find_in(r, e) for e in group]
                if any(c is None for c in cur):
                    raise topo.GeometryError("The chamfers meet at a corner this version can't "
                                             "blend. Chamfer those edges in separate features.")
                try:
                    r = r.makeChamfer(a, b, cur)
                except Exception:
                    r = None
                if r is None or r.isNull() or not r.isValid():
                    raise topo.GeometryError(
                        "The chamfer failed. The distances may be too large for the selected "
                        "edges. Try smaller distances.")
        out.replace(bid, r, p.feature)
        res.touched.append(bid)
        changed.append(r)
    return res, (topo.compound(changed, p.tag) if changed else None)

