# SPDX-License-Identifier: LGPL-2.1-or-later
"""Boundary (Boss/Base, Cut, Surface): a shape through curves in one or two
directions (SolidWorks' Boundary).

With curves in one direction it is a loft through them (core/skin.py). With
curves in both directions it is a Gordon surface through the whole network:

    S = A + B - T

A skins the Direction 1 curves (interpolated across them), B skins the
Direction 2 curves, and T interpolates the network's crossing points in both
directions. Every curve is reparameterised first so the crossings sit at the
same parameters on every curve; then S passes exactly through every curve of
both directions.
"""

import FreeCAD as App
import Part

from .. import skin, topo

V = App.Vector


def _join(pieces, breaks):
    """One B-spline from ``pieces`` (each on [0, 1]) placed on the intervals
    between ``breaks``, joined with position continuity."""
    deg = max(c.Degree for c in pieces)
    pieces = [c.copy() for c in pieces]
    for c in pieces:
        if c.Degree < deg:
            c.increaseDegree(deg)
    poles, knots, mults = [], [], []
    for k, (c, a, b) in enumerate(zip(pieces, breaks[:-1], breaks[1:])):
        ps = c.getPoles()
        ks = [a + (b - a) * t for t in c.getKnots()]
        ms = list(c.getMultiplicities())
        if k == 0:
            poles.extend(ps)
            knots.extend(ks)
            mults.extend(ms)
        else:
            poles.extend(ps[1:])
            mults[-1] = deg                         # the joint: position only
            knots.extend(ks[1:])
            mults.extend(ms[1:])
    out = Part.BSplineCurve()
    out.buildFromPolesMultsKnots(poles, mults, knots, False, deg)
    return out


def _table_interp(table, x):
    for (x0, y0), (x1, y1) in zip(table[:-1], table[1:]):
        if x <= x1 + 1e-12:
            return y0 if x1 - x0 < 1e-15 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return table[-1][1]


def _reparam(sec, fracs, common):
    """The section as one B-spline whose crossings (at ``fracs``) sit at the
    ``common`` parameters, its own corners kept as joints."""
    table = sorted(set(zip([0.0] + list(fracs) + [1.0], [0.0] + list(common) + [1.0])))
    back = [(y, x) for x, y in table]
    cuts = {round(c, 10) for c in common} | {0.0}
    for f in sec.vertex_f:
        cuts.add(round(_table_interp(table, f), 10))
    cuts = sorted(c for c in cuts if c < 1 - 1e-9)
    pieces = sec.pieces([_table_interp(back, c) for c in cuts])
    return _join(pieces, cuts + [1.0])


def _surface_compatible(surfs):
    """Copies of B-spline surfaces sharing degrees and knot vectors."""
    surfs = [s.copy() for s in surfs]
    ud = max(s.UDegree for s in surfs)
    vd = max(s.VDegree for s in surfs)
    for s in surfs:
        if s.UDegree < ud or s.VDegree < vd:
            s.increaseDegree(ud, vd)
    for get, mults, insert in (("getUKnots", "getUMultiplicities", "insertUKnot"),
                               ("getVKnots", "getVMultiplicities", "insertVKnot")):
        need = {}
        for s in surfs:
            for k, m in zip(getattr(s, get)(), getattr(s, mults)()):
                key = round(k, 9)
                need[key] = max(need.get(key, 0), m)
        for s in surfs:
            have = {round(k, 9): m for k, m in zip(getattr(s, get)(), getattr(s, mults)())}
            for k, m in sorted(need.items()):
                if 1e-12 < k < 1 - 1e-12 and have.get(k, 0) < m:
                    getattr(s, insert)(k, m - have.get(k, 0), 1e-10)
    return surfs


def _transposed(s):
    t = s.copy()
    t.exchangeUV()
    return t


def _clamped(s):
    """A u-periodic surface as a clamped one on u in [0, 1]."""
    s.setUNotPeriodic()
    vk = s.getVKnots()
    s.segment(0.0, 1.0, vk[0], vk[-1])
    return s


def network(dir1, dir2, solid=True, tag=1):
    """The Gordon surface (or solid) through two families of curves."""
    C = [skin.Section(w) for w in dir1]
    D = [skin.Section(w) for w in dir2]
    if any(c.is_point for c in C + D):
        raise topo.GeometryError("With curves in both directions every curve must be a curve, "
                                 "not a point.")
    if any(d.closed for d in D):
        raise topo.GeometryError("Direction 2 curves must be open in this version.")
    closed = all(c.closed for c in C)
    if not closed and any(c.closed for c in C):
        raise topo.GeometryError("Direction 1 curves must all be closed, or all open.")
    size = max(max(s.wire().BoundBox.DiagonalLength for s in C + D), 1.0)
    tol = 1e-4 * size

    def cross(c, d, i, j):
        dist, pairs, _info = c.wire().distToShape(d.wire())
        if dist > tol:
            raise topo.GeometryError("Direction 1 curve {} and Direction 2 curve {} don't meet "
                                     "({:.3g} mm apart). Every curve must cross every curve of "
                                     "the other direction.".format(i + 1, j + 1, dist))
        return pairs[0][0]
    P = [[cross(c, d, i, j) for j, d in enumerate(D)] for i, c in enumerate(C)]
    # Closed Direction 1 curves start where the first Direction 2 curve crosses.
    for i, c in enumerate(C):
        if closed:
            f, _d = c.fraction_of(P[i][0])
            c.start_at(f)
    F = [[C[i].fraction_of(P[i][j])[0] for j in range(len(D))] for i in range(len(C))]
    for i, c in enumerate(C):
        row = F[i]
        if closed:
            row[0] = 0.0
            if len(row) > 1 and row[1] > row[-1]:
                c.reverse()
                c.start_at(0.0)
                F[i] = [0.0] + [C[i].fraction_of(P[i][j])[0] for j in range(1, len(D))]
        elif len(row) > 1 and row[0] > row[-1]:
            c.reverse()
            F[i] = [C[i].fraction_of(P[i][j])[0] for j in range(len(D))]
    G = [[D[j].fraction_of(P[i][j])[0] for i in range(len(C))] for j in range(len(D))]
    for j, d in enumerate(D):
        if len(G[j]) > 1 and G[j][0] > G[j][-1]:
            d.reverse()
            G[j] = [D[j].fraction_of(P[i][j])[0] for i in range(len(C))]
    for row in F:
        if any(b <= a + 1e-9 for a, b in zip(row[:-1], row[1:])):
            raise topo.GeometryError("The Direction 2 curves must cross every Direction 1 "
                                     "curve in the same order.")
    for row in G:
        if any(b <= a + 1e-9 for a, b in zip(row[:-1], row[1:])):
            raise topo.GeometryError("The Direction 1 curves must cross every Direction 2 "
                                     "curve in the same order.")
    if not closed and (any(r[0] > 1e-6 or r[-1] < 1 - 1e-6 for r in F)):
        raise topo.GeometryError("With open curves the network must be closed round its "
                                 "edge: the first and last Direction 2 curves must run along "
                                 "the ends of the Direction 1 curves.")
    if any(r[0] > 1e-6 or r[-1] < 1 - 1e-6 for r in G):
        raise topo.GeometryError("The first and last Direction 1 curves must run along the "
                                 "ends of the Direction 2 curves.")
    us = [sum(F[i][j] for i in range(len(C))) / len(C) for j in range(len(D))]
    vs = [sum(G[j][i] for j in range(len(D))) / len(D) for i in range(len(C))]
    if not closed:
        us[0], us[-1] = 0.0, 1.0
    else:
        us[0] = 0.0
    vs[0], vs[-1] = 0.0, 1.0
    if len(C) < 2 or len(D) < 2:
        raise topo.GeometryError("A network needs at least two curves in each direction.")
    Cc = [_reparam(c, F[i][1:] if closed else F[i][1:-1], us[1:] if closed else us[1:-1])
          for i, c in enumerate(C)]
    Dc = [_reparam(d, G[j][1:-1], vs[1:-1]) for j, d in enumerate(D)]
    A = skin.surfaces([[c] for c in skin.compatible(Cc)], False, params=vs)[0]
    if closed:
        uparams = us + [1.0]
        B0 = skin.surfaces([[d] for d in skin.compatible(Dc)], True, params=uparams)[0]
        B = _clamped(_transposed(B0))
        T0 = skin.surfaces([[A.uIso(u)] for u in us], True, params=uparams)[0]
        T = _clamped(_transposed(T0))
    else:
        B = _transposed(skin.surfaces([[d] for d in skin.compatible(Dc)], False,
                                      params=us)[0])
        T = _transposed(skin.surfaces([[A.uIso(u)] for u in us], False, params=us)[0])
    A, B, T = _surface_compatible([A, B, T])
    if A.NbUPoles != B.NbUPoles or A.NbVPoles != B.NbVPoles or \
            A.NbUPoles != T.NbUPoles or A.NbVPoles != T.NbVPoles:
        raise topo.GeometryError("Couldn't combine the two directions of curves.")
    pa, pb, pt = A.getPoles(), B.getPoles(), T.getPoles()
    poles = [[pa[i][j] + pb[i][j] - pt[i][j] for j in range(len(pa[0]))]
             for i in range(len(pa))]
    S = Part.BSplineSurface()
    S.buildFromPolesMultsKnots(poles, A.getUMultiplicities(), A.getVMultiplicities(),
                               A.getUKnots(), A.getVKnots(), False, False,
                               A.UDegree, A.VDegree)
    face = Part.Face(S)
    if not (solid and closed):
        return topo.tagged(face, tag)
    caps = []
    for v in (0.0, 1.0):
        edge = S.vIso(v).toShape()
        try:
            caps.append(Part.Face(Part.Wire([edge])))
        except Exception:
            caps.append(Part.makeFilledFace([edge]))
    sh = Part.Shell([face] + caps)
    sh.sewShape()
    shells = sh.Shells if sh.ShapeType != "Shell" else [sh]
    if len(shells) != 1 or not shells[0].isClosed():
        raise topo.GeometryError("The boundary's faces don't close into a solid.")
    so = Part.Solid(shells[0])
    if so.Volume < 0:
        so.reverse()
    return topo.tagged(so, tag)
