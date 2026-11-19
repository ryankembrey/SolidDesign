# SPDX-License-Identifier: LGPL-2.1-or-later
"""Constraints for Move/Copy Body (SolidWorks' Constraints mode).

Each mate relates an entity on the moving bodies to a fixed entity. Entities are
planes (point, normal), lines (point, direction) or points. The mates are solved
together for one rigid motion with damped least squares (Levenberg-Marquardt);
with too few mates the body moves as little as possible.
"""

import math

import FreeCAD as App
import numpy as np

from . import refgeom, topo

COINCIDENT = "Coincident"
PARALLEL = "Parallel"
PERPENDICULAR = "Perpendicular"
DISTANCE = "Distance"
ANGLE = "Angle"
CONCENTRIC = "Concentric"
TYPES = [COINCIDENT, PARALLEL, PERPENDICULAR, DISTANCE, ANGLE, CONCENTRIC]

TOL = 1e-7


class Entity(object):
    """kind: 'plane', 'line' or 'point'; p: point; d: normal or direction."""

    def __init__(self, kind, p, d=None):
        self.kind = kind
        self.p = np.array([p.x, p.y, p.z], dtype=float)
        self.d = None if d is None else _unit(np.array([d.x, d.y, d.z], dtype=float))


def entity(shape, what):
    """An Entity from a face, edge, vertex or datum."""
    t = shape.ShapeType
    if t == "Vertex" or (t != "Face" and not shape.Edges and len(shape.Vertexes) == 1):
        return Entity("point", refgeom.point_of(shape, what))
    faces = [shape] if t == "Face" else (shape.Faces if t in ("Shell", "Compound") else [])
    if len(faces) == 1:
        st = faces[0].Surface.TypeId
        if st == "Part::GeomPlane":
            p, n, _x = refgeom.plane_of(faces[0], what)
            return Entity("plane", p, n)
        if st in ("Part::GeomCylinder", "Part::GeomCone"):
            p, d = refgeom.line_of(faces[0], what)
            return Entity("line", p, d)
        raise topo.GeometryError("The {} must be planar, cylindrical or conical.".format(what))
    p, d = refgeom.line_of(shape, what)
    return Entity("line", p, d)


class Mate(object):
    def __init__(self, kind, moving, fixed, value=0.0, flip=False):
        self.kind = kind
        self.moving = moving
        self.fixed = fixed
        self.value = value          # mm (Distance) or degrees (Angle)
        self.flip = flip            # Flip alignment


def _unit(v):
    n = np.linalg.norm(v)
    if n < 1e-15:
        raise topo.GeometryError("An entity has no direction.")
    return v / n


def _rot(w):
    """Rotation matrix of a rotation vector (Rodrigues)."""
    th = np.linalg.norm(w)
    if th < 1e-15:
        return np.eye(3)
    k = w / th
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(th) * K + (1 - math.cos(th)) * K.dot(K)


def _move(e, x, c):
    R = _rot(x[:3])
    p = R.dot(e.p - c) + c + x[3:]
    d = None if e.d is None else R.dot(e.d)
    return p, d


def _point_line(p, q, d):
    v = p - q
    return v - d * v.dot(d)


def _residuals(mates, x, c, signs):
    out = []
    for i, m in enumerate(mates):
        p, d = _move(m.moving, x, c)
        f = m.fixed
        k = m.kind
        a, b = m.moving.kind, f.kind
        if k in (COINCIDENT, DISTANCE):
            off = m.value if k == DISTANCE else 0.0
            if a == "plane" and b == "plane":
                s = signs[i]
                out.extend(d - s * f.d)
                # The gap is measured outward from the fixed face (along its normal).
                out.append((p - f.p).dot(f.d) - off)
            elif a == "point" and b == "plane":
                out.append((p - f.p).dot(f.d) - off)
            elif a == "plane" and b == "point":
                out.append((f.p - p).dot(d) - off)
            elif a == "point" and b == "point":
                out.extend(p - f.p)
            elif a == "point" and b == "line":
                out.extend(_point_line(p, f.p, f.d))
            elif a == "line" and b == "point":
                out.extend(_point_line(f.p, p, d))
            elif a == "line" and b == "line":
                out.extend(np.cross(d, f.d))
                out.extend(_point_line(p, f.p, f.d))
            elif a == "line" and b == "plane":
                out.append(d.dot(f.d))
                out.append((p - f.p).dot(f.d) - off)
            elif a == "plane" and b == "line":
                out.append(d.dot(f.d))
                out.append((f.p - p).dot(d) - off)
            else:
                raise topo.GeometryError("{} can't relate a {} and a {}.".format(k, a, b))
        elif k == PARALLEL:
            _need_dirs(m)
            if a == b:
                out.extend(d - signs[i] * f.d)
            else:
                out.append(d.dot(f.d))      # a line parallel to a plane
        elif k == PERPENDICULAR:
            _need_dirs(m)
            if a == b:
                out.append(d.dot(f.d))
            else:
                out.extend(np.cross(d, f.d))
        elif k == ANGLE:
            _need_dirs(m)
            out.append(d.dot(f.d) - math.cos(math.radians(m.value)) * signs[i])
        elif k == CONCENTRIC:
            if a != "line" or b != "line":
                raise topo.GeometryError("Concentric needs two round faces, circular edges or "
                                         "axes.")
            out.extend(d - signs[i] * f.d)
            out.extend(_point_line(p, f.p, f.d))
        else:
            raise topo.GeometryError("Unknown constraint " + k)
    return np.array(out, dtype=float)


def _need_dirs(m):
    if m.moving.d is None or m.fixed.d is None:
        raise topo.GeometryError("{} needs faces, edges or axes, not points.".format(m.kind))


def _signs(mates):
    """Alignment of each mate: SolidWorks' default for Coincident faces is
    anti-aligned (they sit face to face); for the others, whichever is nearer
    the start. Flip alignment reverses it."""
    out = []
    for m in mates:
        s = 1.0
        if m.moving.d is not None and m.fixed.d is not None:
            dot = float(m.moving.d.dot(m.fixed.d))
            if m.kind in (COINCIDENT, DISTANCE) and m.moving.kind == m.fixed.kind == "plane":
                s = -1.0
            else:
                s = 1.0 if dot >= 0 else -1.0
        out.append(-s if m.flip else s)
    return out


def solve(mates, centre, iterations=200):
    """The rigid motion (App.Placement) that satisfies the mates."""
    if not mates:
        raise topo.GeometryError("Add at least one constraint.")
    c = np.array([centre.x, centre.y, centre.z], dtype=float)
    signs = _signs(mates)
    x = np.zeros(6)
    lam = 1e-3
    r = _residuals(mates, x, c, signs)
    cost = r.dot(r)
    for _ in range(iterations):
        if cost < TOL * TOL:
            break
        J = np.zeros((len(r), 6))
        h = 1e-7
        for j in range(6):
            dx = np.zeros(6)
            dx[j] = h
            J[:, j] = (_residuals(mates, x + dx, c, signs) - r) / h
        A = J.T.dot(J)
        g = J.T.dot(r)
        while True:
            step = -np.linalg.solve(A + lam * (np.diag(np.diag(A)) + 1e-9 * np.eye(6)), g)
            xn = x + step
            rn = _residuals(mates, xn, c, signs)
            cn = rn.dot(rn)
            if cn < cost:
                x, r, cost = xn, rn, cn
                lam = max(lam / 10.0, 1e-12)
                break
            lam *= 10.0
            if lam > 1e12:
                break
        if lam > 1e12 or np.linalg.norm(step) < 1e-14:
            break
    if math.sqrt(cost) > 1e-5:
        raise topo.GeometryError("The constraints can't all be met together (they conflict, "
                                 "or a value is out of reach). Check them, or remove one.")
    R = _rot(x[:3])
    t = c + x[3:] - R.dot(c)
    m = App.Matrix(R[0, 0], R[0, 1], R[0, 2], t[0],
                   R[1, 0], R[1, 1], R[1, 2], t[1],
                   R[2, 0], R[2, 1], R[2, 2], t[2],
                   0, 0, 0, 1)
    return App.Placement(m)
