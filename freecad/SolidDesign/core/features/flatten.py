# SPDX-License-Identifier: LGPL-2.1-or-later
"""Surface Flatten (SolidWorks' Surface Flatten): faces laid out flat, as a new
surface body, touching the original at the point they are flattened from.

The faces are meshed and unwrapped with FreeCAD's flatmesh (least-squares
conformal map, then relaxed to keep lengths). A developable face (a cylinder, a
cone, a ruled sheet) comes out true to size; any other face is stretched as
little as it can be, and the change of area is reported. Round faces are cut
open along their seams. Each run of the outline along one original edge
becomes one smooth curve (a straight edge stays straight).
"""

import math

import FreeCAD as App
import Part

from .. import topo

V = App.Vector


class Params(object):
    def __init__(self):
        self.faces = []             # Part.Faces, one connected set
        self.anchor = None          # App.Vector on the faces (None: the first face's centre)
        self.accuracy = 0.5         # 0 coarse .. 1 fine
        self.tears = []             # Part.Edges to cut the faces open along (relief cuts)
        self.feature = "Flatten"
        self.tag = 1
        self.alloc = None


def _on(edges, p, tol):
    v = Part.Vertex(p)
    return any(e.distToShape(v)[0] < tol for e in edges)


def _mesh(faces, tol, tears=()):
    """(points, triangles) of the faces, joined where they share edges, cut open
    along each face's seam and along the tear edges."""
    pts, tris = [], []
    index = {}

    def key(p):
        q = 1.0 / max(tol * 0.05, 1e-9)
        return (round(p.x * q), round(p.y * q), round(p.z * q))

    # A tear's ends stay joined unless they reach the outline (or another tear), so a
    # tear that stops inside the faces opens a slit rather than cutting a piece off.
    tears = list(tears)
    outline = _outline_edges(faces) if tears else []
    loose_ends = []
    for t in tears:
        for vx in t.Vertexes:
            others = [e for e in tears if not e.isSame(t)]
            if not _on(outline, vx.Point, tol * 0.1) and not _on(others, vx.Point, tol * 0.1):
                loose_ends.append(vx.Point)

    def torn(p):
        if not tears or not _on(tears, p, tol * 0.1):
            return False
        return not any((p - e).Length < tol * 0.1 for e in loose_ends)

    for fi, f in enumerate(faces):
        fp, ft = f.tessellate(tol)
        seams = [e for e in f.Edges if _is_seam(e, f)]
        u0, u1, v0, v1 = f.ParameterRange
        local = []
        on_seam = []
        for p in fp:
            on_seam.append(any(e.distToShape(Part.Vertex(p))[0] < tol * 0.1 for e in seams))
            local.append(p)
        dup = {}
        for t in ft:
            ids = []
            high = False
            if seams and any(on_seam[i] for i in t):
                c = (local[t[0]] + local[t[1]] + local[t[2]]) * (1.0 / 3.0)
                try:
                    u, v = f.Surface.parameter(c)
                except Exception:
                    u, v = u0, v0
                periodic_u = f.Surface.isUPeriodic() if hasattr(f.Surface, "isUPeriodic") \
                    else False
                mid = 0.5 * (u0 + u1) if periodic_u else 0.5 * (v0 + v1)
                high = (u if periodic_u else v) > mid
            for i in t:
                p = local[i]
                if high and on_seam[i]:
                    # The far side of the seam: its own copy of the point.
                    if i not in dup:
                        dup[i] = len(pts)
                        pts.append(p)
                    ids.append(dup[i])
                    continue
                k = key(p)
                if torn(p):
                    k = (fi,) + k           # each face keeps its own copy along a tear
                if k not in index:
                    index[k] = len(pts)
                    pts.append(p)
                ids.append(index[k])
            if len(set(ids)) == 3:
                tris.append(ids)
    if tears:
        pts, tris = _rejoin(faces, pts, tris, index, tears, tol)
    return pts, tris


def _rejoin(faces, pts, tris, index, tears, tol):
    """Along a tear each face got its own copy of a point; join the copies of two
    faces again where they share an edge that isn't torn (the hinges of a net)."""
    parent = list(range(len(pts)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    hinges = []                     # (face i, face j, edge) not torn
    for i, f in enumerate(faces):
        for j in range(i + 1, len(faces)):
            for e in f.Edges:
                if any(e.isSame(o) for o in faces[j].Edges) and \
                        not any(e.isSame(t) for t in tears):
                    hinges.append((i, j, e))
    by_key = {}
    for k, n in index.items():
        if len(k) == 4:             # (face, x, y, z): a torn copy
            by_key.setdefault(k[1:], []).append((k[0], n))
    for _k, copies in by_key.items():
        if len(copies) < 2:
            continue
        p = pts[copies[0][1]]
        v = Part.Vertex(p)
        for fi, a in copies:
            for fj, b in copies:
                if fi < fj and any((h[0], h[1]) == (fi, fj) and h[2].distToShape(v)[0] < tol * 0.1
                                   for h in hinges):
                    parent[find(a)] = find(b)
    roots = {}
    out_pts, remap = [], {}
    for i in range(len(pts)):
        r = find(i)
        if r not in roots:
            roots[r] = len(out_pts)
            out_pts.append(pts[r])
        remap[i] = roots[r]
    out_tris = []
    for t in tris:
        ids = [remap[i] for i in t]
        if len(set(ids)) == 3:
            out_tris.append(ids)
    return out_pts, out_tris


def _outline_edges(faces):
    """Edges used by one face of the set only (not seams): the set's open outline."""
    out = []
    edges = [(e, f) for f in faces for e in f.Edges if not _is_seam(e, f)]
    for i, (e, f) in enumerate(edges):
        if not any(j != i and e.isSame(o) for j, (o, _g) in enumerate(edges)):
            out.append(e)
    return out


def _is_seam(edge, face):
    try:
        return edge.isSeam(face)
    except Exception:
        return False


def _area3(a, b, c):
    return 0.5 * (b - a).cross(c - a).Length


def flatten(p):
    """(flat face, area change as a fraction, mesh size used)."""
    try:
        import flatmesh
        import numpy as np
    except ImportError:
        raise topo.GeometryError("Surface Flatten needs FreeCAD's flatmesh module, which this "
                                 "FreeCAD build doesn't have.")
    faces = [f for f in p.faces if f is not None]
    if not faces:
        raise topo.GeometryError("Pick the faces to flatten.")
    size = Part.makeCompound(faces).BoundBox.DiagonalLength
    acc = min(max(p.accuracy, 0.0), 1.0)
    tol = size * (0.004 - 0.0035 * acc)
    tears = [e for e in p.tears if e is not None]
    if not tears and not _outline_edges(faces) and len(faces) > 1:
        raise topo.GeometryError("The faces close up (a whole body): pick Tear edges to cut "
                                 "them open, as you would to make a net.")
    pts, tris = _mesh(faces, tol, tears)
    if len(tris) < 2:
        raise topo.GeometryError("The faces are too small to flatten.")
    P = np.array([[q.x, q.y, q.z] for q in pts])
    T = np.array(tris)
    try:
        un = flatmesh.FaceUnwrapper(P, T)
        un.findFlatNodes(5, 0.95)
        flat = np.array(un.ze_nodes)[:, :2]
        loops = un.getFlatBoundaryNodes()
    except Exception as e:
        raise topo.GeometryError("The faces couldn't be flattened ({}). A closed face (a whole "
                                 "sphere) must be split first.".format(e))
    if not loops:
        raise topo.GeometryError("The faces have no open edge to flatten from (a closed "
                                 "body). Pick Tear edges to cut them open.")
    # Map flat boundary points back to mesh nodes.
    def node_of(xy):
        return int(((flat - np.array(xy[:2])) ** 2).sum(axis=1).argmin())

    # Place: the anchor's node at the anchor, flat on the tangent plane there.
    anchor = V(p.anchor) if p.anchor is not None else faces[0].CenterOfMass
    k = int(((P - np.array([anchor.x, anchor.y, anchor.z])) ** 2).sum(axis=1).argmin())
    ftouch = min(faces, key=lambda f: f.distToShape(Part.Vertex(anchor))[0])
    try:
        u, v = ftouch.Surface.parameter(V(*P[k]))
        n = ftouch.normalAt(u, v)
    except Exception:
        n = V(0, 0, 1)
    tri = next(t for t in tris if k in t)
    j1, j2 = [i for i in tri if i != k][:2]
    d3 = V(*P[j1]) - V(*P[k])
    e1 = d3 - n * d3.dot(n)
    if e1.Length < 1e-12:
        e1 = n.cross(V(1, 0, 0)) if abs(n.x) < 0.9 else n.cross(V(0, 1, 0))
    e1.normalize()
    e2 = n.cross(e1)
    t2 = flat[j1] - flat[k]
    t2 = t2 / max(np.linalg.norm(t2), 1e-15)
    s3 = (V(*P[j1]) - V(*P[k])).cross(V(*P[j2]) - V(*P[k])).dot(n)
    a2, b2 = flat[j1] - flat[k], flat[j2] - flat[k]
    s2 = a2[0] * b2[1] - a2[1] * b2[0]
    mirror = -1.0 if s3 * s2 < 0 else 1.0
    origin = V(*P[k])
    fk = flat[k]

    def place(xy):
        d = np.array(xy[:2]) - fk
        a = d[0] * t2[0] + d[1] * t2[1]
        b = t2[0] * d[1] - t2[1] * d[0]
        return origin + e1 * a + e2 * (b * mirror)

    # The outline: one smooth curve per run along one original edge.
    edges3 = [e for f in faces for e in f.Edges]
    wires = []
    for loop in loops:
        ids = [node_of(q) for q in loop]
        if len(ids) > 1 and ids[0] == ids[-1]:
            ids = ids[:-1]
        # Each boundary segment belongs to the edge its middle lies on; node i
        # starts segment i.
        owner = []
        for a, b in zip(ids, ids[1:] + ids[:1]):
            q = Part.Vertex((V(*P[a]) + V(*P[b])) * 0.5)
            owner.append(min(range(len(edges3)), key=lambda m: edges3[m].distToShape(q)[0]))
        wires.append(_outline([place(flat[i]) for i in ids], owner, edges3))
    wires.sort(key=lambda w: -Part.Face(w).Area if w.isClosed() else 0)
    try:
        face = Part.Face(wires[0])
        if len(wires) > 1:
            face = Part.makeFace(wires, "Part::FaceMakerBullseye").Faces[0]
    except Exception as e:
        raise topo.GeometryError("The flat outline couldn't be made into a face ({}).".format(e))
    area3 = sum(f.Area for f in faces)
    change = (face.Area - area3) / max(area3, 1e-12)
    return topo.tagged(face, p.tag), change, tol


def _outline(points, owner, edges3):
    """A closed wire through ``points``: a curve for each run of segments on one
    edge (segment i runs from point i to point i + 1)."""
    n = len(points)
    if n < 3:
        raise topo.GeometryError("The flat outline is too coarse; raise the accuracy.")
    # Start where the owning edge changes, so no run is split across the loop's start.
    start = next((i for i in range(n) if owner[i] != owner[i - 1]), 0)
    pts = points[start:] + points[:start]
    own = owner[start:] + owner[:start]
    runs = []
    cur, cur_own = [pts[0]], own[0]
    for i in range(1, n):
        if own[i] != cur_own:
            cur.append(pts[i])              # the corner ends one run and starts the next
            runs.append((cur_own, cur))
            cur, cur_own = [pts[i]], own[i]
        else:
            cur.append(pts[i])
    cur.append(pts[0])
    runs.append((cur_own, cur))
    # Both sides of a tear belong to the same edge and meet at a sharp point: split
    # every run at sharp turns, so no curve (or straight line) cuts the corner off.
    split = []
    for which, run in runs:
        clean = [run[0]]
        for q in run[1:]:
            if (q - clean[-1]).Length > 1e-9:
                clean.append(q)
        cur = [clean[0]]
        for i in range(1, len(clean)):
            cur.append(clean[i])
            if 0 < i < len(clean) - 1:
                d1, d2 = clean[i] - clean[i - 1], clean[i + 1] - clean[i]
                if d1.getAngle(d2) > math.radians(25.0):
                    split.append((which, cur))
                    cur = [clean[i]]
        split.append((which, cur))
    edges = []
    for which, clean in split:
        if len(clean) < 2:
            continue
        chord = clean[-1] - clean[0]
        dev = 0.0
        if chord.Length > 1e-12:
            u = chord * (1.0 / chord.Length)
            dev = max(((q - clean[0]) - u * (q - clean[0]).dot(u)).Length for q in clean)
        closed = chord.Length < 1e-9
        if closed and len(clean) < 4:
            continue                        # nothing left of it
        straight = not closed and (_is_line(edges3[which]) or len(clean) == 2 or
                                   dev < 1e-4 * max(chord.Length, 1e-9))
        if straight:
            edges.append(Part.LineSegment(clean[0], clean[-1]).toShape())
        else:
            c = Part.BSplineCurve()
            if closed:
                c.interpolate(clean[:-1], PeriodicFlag=True)
            else:
                c.interpolate(clean)
            edges.append(c.toShape())
    try:
        return Part.Wire(edges)
    except Exception:
        return Part.makePolygon(points + [points[0]])


def _is_line(e):
    try:
        return e.Curve.TypeId in ("Part::GeomLine", "Part::GeomLineSegment")
    except Exception:
        return False


def compute(p, base):
    """Returns (Result, preview): the flat face as a new surface body."""
    from ..bodies import SURFACE
    from . import common
    face, change, _tol = flatten(p)
    out = base.copy()
    res = common.Result(out)
    sh = Part.Shell([face])
    bid = p.alloc.take([sh])[0]
    out.add(bid, topo.tagged(sh, p.tag), p.feature, SURFACE)
    res.created.append(bid)
    if abs(change) > 0.001:
        res.warnings.append("Flattening changed the area by {:+.2f}%: the faces aren't "
                            "developable, so the flat shape is stretched.".format(change * 100))
    return res, face


