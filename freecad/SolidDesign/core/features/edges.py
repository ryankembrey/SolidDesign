# SPDX-License-Identifier: LGPL-2.1-or-later
"""Shared by edge features (Fillet, Chamfer): grouping picks by body, and
tangent propagation."""

from .. import topo


def _same(a, b, tol=1e-7):
    """Same edge or vertex by geometry (for shapes that don't share topology)."""
    if a.isSame(b):
        return True
    try:
        if a.ShapeType != b.ShapeType:
            return False
        if a.ShapeType == "Vertex":
            return (a.Point - b.Point).Length < tol
        if abs(a.Length - b.Length) > tol * max(1.0, a.Length):
            return False
        if (a.CenterOfMass - b.CenterOfMass).Length > tol * 10:
            return False
        ends_a = sorted((v.Point.x, v.Point.y, v.Point.z) for v in a.Vertexes)
        ends_b = sorted((v.Point.x, v.Point.y, v.Point.z) for v in b.Vertexes)
        return all(abs(x - y) < 1e-6 for pa, pb in zip(ends_a, ends_b) for x, y in zip(pa, pb))
    except Exception:
        return False


def find_in(shape, elem):
    """The element of ``shape`` that is ``elem`` (same topology, or same geometry)."""
    kind = elem.ShapeType
    pool = shape.Edges if kind == "Edge" else shape.Vertexes if kind == "Vertex" else shape.Faces
    for e in pool:
        if e.isSame(elem):
            return e
    for e in pool:
        if kind == "Face":
            try:
                if abs(e.Area - elem.Area) < 1e-9 * max(1.0, e.Area) and \
                        (e.CenterOfMass - elem.CenterOfMass).Length < 1e-6:
                    return e
            except Exception:
                pass
        elif _same(e, elem):
            return e
    return None


# Far enough to cover how boxes are made (an element on a body overlaps its box;
# one matched by geometry has its centre within 1e-6 of the body's element).
NEAR = 1e-4


def body_holding(base, elem):
    """(body, ``elem`` as an element of the body's own shape): the first body in
    order that holds it (find_in), or (None, None). Bodies whose box is nowhere
    near the element are passed over without looking at their elements."""
    try:
        eb = elem.BoundBox
    except Exception:
        eb = None
    for b in base:
        if eb is not None and topo.box_gap(topo.bbox(b.shape), eb, NEAR):
            continue
        found = find_in(b.shape, elem)
        if found is not None:
            return b, found
    return None, None


def faces_by_body(base, faces):
    """Group picked faces by body, as faces of that body's own shape."""
    out = {}
    for f in faces:
        b, found = body_holding(base, f)
        hit = (b.id, found) if b is not None else None
        if hit is None:
            raise topo.GeometryError("A picked face isn't on any body before this feature. "
                                     "Re-pick it.")
        out.setdefault(hit[0], []).append(hit[1])
    return out


def by_body(base, elems):
    """Group picked elements by the body that holds them.

    Faces count as all their edges. Returns {body_id: [edges or vertices of that
    body's own shape]} in the body set's order. Raises if a pick is in no body.
    """
    out = {}
    for el in elems:
        b, found = body_holding(base, el)
        hit = (b, found) if b is not None else None
        if hit is None:
            raise topo.GeometryError("A picked {} isn't on any body before this feature. "
                                     "Re-pick it.".format(el.ShapeType.lower()))
        b, found = hit
        items = found.Edges if found.ShapeType == "Face" else [found]
        lst = out.setdefault(b.id, [])
        for it in items:
            if not any(it.isSame(x) for x in lst):
                lst.append(it)
    order = {}
    for i, b in enumerate(base):
        order.setdefault(b.id, i)
    return dict(sorted(out.items(), key=lambda kv: order[kv[0]]))


def _tangent_at(edge, vertex):
    p = vertex.Point
    u0, u1 = edge.FirstParameter, edge.LastParameter
    if (edge.valueAt(u0) - p).Length < (edge.valueAt(u1) - p).Length:
        t = edge.tangentAt(u0)
    else:
        t = edge.tangentAt(u1)
    if t.Length > 0:
        t.normalize()
    return t


class _Same(object):
    """A set of shapes by isSame (same topology, any orientation), looked up by
    hash: isSame shapes share their hash (TShape and Location)."""

    def __init__(self, shapes=()):
        self._by = {}
        for x in shapes:
            self.add(x)

    def add(self, x):
        self._by.setdefault(x.hashCode(), []).append(x)

    def __contains__(self, x):
        return any(y.isSame(x) for y in self._by.get(x.hashCode(), ()))


def tangent_chain(shape, edges, tol=1e-6):
    """Add the edges tangent-continuous with the picks (SolidWorks' Tangent
    propagation): neighbours that meet a picked edge smoothly at a vertex.

    The edges at each vertex are found from a map made once, in the shape's
    edge order, so the result (and its order) is what going through every edge
    of the shape for every vertex gave, without doing that."""
    all_edges = shape.Edges
    at_vertex = {}                      # vertex hash -> [(vertex, edge index)]
    for i, f in enumerate(all_edges):
        for fv in f.Vertexes:
            at_vertex.setdefault(fv.hashCode(), []).append((fv, i))
    out = list(edges)
    seen = _Same(out)
    todo = list(edges)
    while todo:
        e = todo.pop()
        for v in e.Vertexes:
            t0 = _tangent_at(e, v)
            idx = sorted(set(i for fv, i in at_vertex.get(v.hashCode(), ()) if fv.isSame(v)))
            for i in idx:
                f = all_edges[i]
                if f in seen:
                    continue
                t1 = _tangent_at(f, v)
                if abs(abs(t0.dot(t1)) - 1.0) < tol:
                    out.append(f)
                    seen.add(f)
                    todo.append(f)
    return out


def tangent_faces(shape, faces, tol=1e-4):
    """Add the faces that meet the picks smoothly (SolidWorks' Select Tangency for
    faces): neighbours sharing an edge whose normals agree along it."""
    out = list(faces)
    todo = list(faces)
    while todo:
        f = todo.pop()
        for e in f.Edges:
            u = 0.5 * (e.FirstParameter + e.LastParameter)
            p = e.valueAt(u)
            for g in shape.ancestorsOfType(e, type(f)):
                if any(g.isSame(x) for x in out):
                    continue
                try:
                    n0 = f.normalAt(*f.Surface.parameter(p))
                    n1 = g.normalAt(*g.Surface.parameter(p))
                except Exception:
                    continue
                if n0.dot(n1) > 1.0 - tol:
                    out.append(g)
                    todo.append(g)
    return out


# ------------------------------------------------------------------ picking more edges
# SolidWorks' Select Tangency, Select Loop and Select Chain: from one picked edge,
# the edges that go with it. Names are "EdgeN" of ``shape``.

def edge_name(shape, edge):
    for i, e in enumerate(shape.Edges, 1):
        if e.isSame(edge):
            return "Edge%d" % i
    return None


def _faces_of(shape, edge):
    import Part
    try:
        return shape.ancestorsOfType(edge, Part.Face)
    except Exception:
        return []


def select_tangency(shape, edge):
    """The edge and every edge that runs on from it smoothly (tangent at the
    shared vertex), as far as that goes."""
    return [n for n in (edge_name(shape, e) for e in tangent_chain(shape, [edge])) if n]


def face_loops(shape, edge):
    """[(face, [edge names])]: for each face beside the edge, the loop of that
    face's edges the edge is in (its outline, or the rim of a hole in it)."""
    out = []
    for f in _faces_of(shape, edge):
        for w in f.Wires:
            if any(e.isSame(edge) for e in w.Edges):
                names = [edge_name(shape, e) for e in w.Edges]
                out.append((f, [n for n in names if n]))
                break
    return out


def select_chain(shape, edge):
    """(edge names, closed): the edges joined end to end with it, followed while
    the way on is clear: at each vertex just one edge of the same sort (an open
    edge of a surface goes on along open edges; a sketch's along its curves).
    Closed when it comes back round to where it started."""
    def faces(e):
        return len(_faces_of(shape, e))
    sort = min(faces(edge), 2)
    pool = [e for e in shape.Edges if min(faces(e), 2) == sort]
    chain = [edge]
    closed = False
    for end in (-1, 0):
        cur = edge
        v = edge.Vertexes[end] if edge.Vertexes else None
        while v is not None:
            nxt = [e for e in pool if not e.isSame(cur) and
                   any(ev.isSame(v) for ev in e.Vertexes)]
            if len(nxt) != 1:
                break
            e = nxt[0]
            if any(e.isSame(x) for x in chain):
                closed = True
                break
            if end == -1:
                chain.append(e)
            else:
                chain.insert(0, e)
            others = [ev for ev in e.Vertexes if not ev.isSame(v)]
            v, cur = (others[0] if others else None), e
        if closed:
            break
    return [n for n in (edge_name(shape, e) for e in chain) if n], closed


def is_concave(shape, edge, eps=1e-3):
    """For an edge between two faces of a solid: True for an inside corner (where
    a fillet adds material), False for an outside one, None when it can't be told
    (one face, tangent faces, no solid)."""
    faces = _faces_of(shape, edge)
    if len(faces) != 2 or not shape.Solids:
        return None
    a, b = edge.FirstParameter, edge.LastParameter
    m = edge.valueAt(0.5 * (a + b))
    normals = []
    for f in faces:
        try:
            u, v = f.Surface.parameter(m)
            normals.append(f.normalAt(u, v))
        except Exception:
            return None
    if abs(normals[0].dot(normals[1])) > 1 - 1e-6:
        return None
    # A step from the edge across the first face, square to the edge: the corner is
    # inside when that step rises off the second face (on the side its normal
    # points to, the outside of the solid).
    try:
        t = edge.tangentAt(0.5 * (a + b))
    except Exception:
        return None
    d = normals[0].cross(t)
    if d.Length < 1e-9:
        return None
    d.normalize()
    step = eps * max(1.0, shape.BoundBox.DiagonalLength * 1e-3)
    f0 = faces[0]
    if not f0.isInside(m + d * step, step * 0.5, True):
        d = -d
        if not f0.isInside(m + d * step, step * 0.5, True):
            return None
    return d.dot(normals[1]) > 0
