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


def faces_by_body(base, faces):
    """Group picked faces by body, as faces of that body's own shape."""
    out = {}
    for f in faces:
        hit = None
        for b in base:
            found = find_in(b.shape, f)
            if found is not None:
                hit = (b.id, found)
                break
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
        hit = None
        for b in base:
            found = find_in(b.shape, el)
            if found is not None:
                hit = (b, found)
                break
        if hit is None:
            raise topo.GeometryError("A picked {} isn't on any body before this feature. "
                                     "Re-pick it.".format(el.ShapeType.lower()))
        b, found = hit
        items = found.Edges if found.ShapeType == "Face" else [found]
        lst = out.setdefault(b.id, [])
        for it in items:
            if not any(it.isSame(x) for x in lst):
                lst.append(it)
    order = [b.id for b in base]
    return dict(sorted(out.items(), key=lambda kv: order.index(kv[0])))


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


def tangent_chain(shape, edges, tol=1e-6):
    """Add the edges tangent-continuous with the picks (SolidWorks' Tangent
    propagation): neighbours that meet a picked edge smoothly at a vertex."""
    out = list(edges)
    todo = list(edges)
    while todo:
        e = todo.pop()
        for v in e.Vertexes:
            t0 = _tangent_at(e, v)
            for f in shape.Edges:
                if any(f.isSame(x) for x in out):
                    continue
                if not any(fv.isSame(v) for fv in f.Vertexes):
                    continue
                t1 = _tangent_at(f, v)
                if abs(abs(t0.dot(t1)) - 1.0) < tol:
                    out.append(f)
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
