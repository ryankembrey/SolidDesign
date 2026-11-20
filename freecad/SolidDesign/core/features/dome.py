# SPDX-License-Identifier: LGPL-2.1-or-later
"""Dome (SolidWorks' Insert > Features > Dome): a dome on a flat face.

On a round face the dome is part of a sphere (or, Elliptical dome, half an
ellipsoid: as high as asked, square to the face at its edge). On any other flat
face it rises smoothly from the face's edges to its top (square to the face at
the edge when Elliptical). Reverse makes it a dent instead.

Continuous dome (faces that aren't round): the outline rounds off as it rises,
so the dome slopes up evenly with no creases from the corners. A direction
leans the dome that way (its height still measured square to the face); a
constraint point puts the dome's top on that point (setting height and lean).
"""

import FreeCAD as App
import Part

from .. import topo
from . import common


class Params(object):
    def __init__(self):
        self.feature = "Dome"
        self.tag = 1
        self.alloc = None
        self.faces = []
        self.height = 5.0
        self.reverse = False
        self.elliptical = False
        self.continuous = False
        self.direction = None       # lean the dome this way
        self.point = None           # the dome's top goes here


def _round(face):
    """(centre, radius) when the face is a full circle, else None."""
    edges = face.OuterWire.Edges
    if len(edges) == 1 and edges[0].Curve.TypeId == "Part::GeomCircle" and edges[0].isClosed():
        c = edges[0].Curve
        return App.Vector(c.Center), c.Radius
    return None


def _refined(curves):
    """Cubic copies of the outline's curves with enough poles to bend smoothly."""
    out = []
    for cv in curves:
        c = cv.copy()
        if c.Degree < 3:
            c.increaseDegree(3)
        a, b = c.FirstParameter, c.LastParameter
        for i in range(1, 8):
            try:
                c.insertKnot(a + (b - a) * i / 8.0, 1, 1e-9)
            except Exception:
                pass
        out.append(c)
    return out


def leaned(solid, base_point, n, direction):
    """The dome sheared so it rises along ``direction``, its base kept on the face."""
    d = App.Vector(direction)
    if d.Length < 1e-12:
        return solid
    d.normalize()
    k = d.dot(n)
    if k < 0:
        d, k = -d, -k                   # an edge or axis can point either way
    if k < 0.05:
        raise topo.GeometryError("The dome's direction must point away from the face.")
    w = d * (1.0 / k) - n
    m = App.Matrix(1 + w.x * n.x, w.x * n.y, w.x * n.z, -w.x * n.dot(base_point),
                   w.y * n.x, 1 + w.y * n.y, w.y * n.z, -w.y * n.dot(base_point),
                   w.z * n.x, w.z * n.y, 1 + w.z * n.z, -w.z * n.dot(base_point),
                   0, 0, 0, 1)
    return solid.transformGeometry(m)


def dome_solid(face, h, elliptical, outward, continuous=False):
    """The dome's solid, standing on ``face`` (towards ``outward``)."""
    n = outward
    rc = _round(face)
    if rc is not None:
        c, r = rc
        if elliptical:
            # Half an ellipsoid: a quarter ellipse turned round the face's axis.
            u = face.OuterWire.Edges[0].valueAt(0) - c
            u.normalize()
            top, side = c + n * h, c + u * r
            if h >= r:
                ell = Part.Ellipse(top, side, c)
            else:
                ell = Part.Ellipse(side, top, c)
            arc = Part.ArcOfEllipse(ell, 0.0, 1.5707963267948966).toShape()
            a, b = arc.valueAt(arc.FirstParameter), arc.valueAt(arc.LastParameter)
            edges = [arc, Part.LineSegment(b, c).toShape(), Part.LineSegment(c, a).toShape()]
            prof = Part.Face(Part.Wire(Part.__sortEdges__(edges)))
            return prof.revolve(c, n, 360).Solids[0] if prof.revolve(c, n, 360).Solids else \
                Part.Solid(Part.Shell(prof.revolve(c, n, 360).Faces))
        R = (r * r + h * h) / (2.0 * h)
        centre = c + n * (h - R)
        ball = Part.makeSphere(R, centre)
        prism = Part.Face(face.OuterWire).extrude(n * (h * 1.5 + 1))
        return ball.common(prism)
    # Any other flat face: copies of its outline, shrunk towards its middle as they
    # rise, skinned into a smooth dome (square to the face at its edge when
    # elliptical, else a gentler rise).
    from .. import skin
    import math
    c = face.CenterOfMass
    base_curves = skin.oriented_curves(face.OuterWire)
    if continuous:
        base_curves = _refined(base_curves)
    # Round towards the largest circle about the middle that stays inside the outline,
    # so the dome never overhangs the face.
    radii = [face.OuterWire.distToShape(Part.Vertex(c))[0]] if continuous else [1.0]
    mean = max(min(radii), 1e-9)
    rows, params = [], []
    steps = 10
    for k in range(steps):
        phi = (math.pi / 2) * k / float(steps)
        if elliptical:
            scale, z = math.cos(phi), h * math.sin(phi)
        else:
            scale = math.cos(phi)
            z = h * (1 - scale * scale)
        if continuous and k:
            # Round the outline off as it rises: each pole moves towards that circle.
            t = math.sin(phi) ** 0.5
            row = []
            for cv in base_curves:
                poles = []
                for q in cv.getPoles():
                    r = q - c
                    r = r - n * r.dot(n)
                    if r.Length > 1e-12:
                        r = r * ((1 - t) + t * mean / r.Length)
                    poles.append(c + r * scale + n * z)
                row.append(skin._rebuild(cv, poles))
            rows.append(row)
        else:
            m = App.Matrix()
            m.move(-c)
            m.scale(scale, scale, scale)
            m.move(c + n * z)
            rows.append(skin.transformed(base_curves, m))
        params.append(k / float(steps))
    top = c + n * h
    rows.append([skin._rebuild(cv, [top] * cv.NbPoles) for cv in base_curves])
    params.append(1.0)
    return skin.build(rows, False, True, params=params)


def compute(p, base):
    if not p.faces:
        raise topo.GeometryError("Pick a flat face for the dome.")
    if p.height <= 0 and p.point is None:
        raise topo.GeometryError("The dome's height must be greater than zero.")
    from .edges import faces_by_body
    groups = faces_by_body(base, p.faces)
    out = base
    res_all = None
    tools = []
    for bid, faces in groups.items():
        body = base.get(bid)
        for f in faces:
            if f.Surface.TypeId != "Part::GeomPlane":
                raise topo.GeometryError("A dome needs a flat face in this version.")
            u0, u1, v0, v1 = f.ParameterRange
            n = f.normalAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))
            inside = body.shape.isInside(f.CenterOfMass + n * 1e-4, 1e-7, False)
            if inside:
                n = -n                              # point out of the body
            if p.reverse:
                n = -n
            h, lean = p.height, p.direction
            c = f.CenterOfMass
            if p.point is not None:
                h = (p.point - c).dot(n)
                if h <= 1e-9:
                    raise topo.GeometryError("The constraint point must be above the face.")
                lean = p.point - c
            try:
                t = dome_solid(f, h, p.elliptical, n, p.continuous)
                if lean is not None:
                    t = leaned(t, c, n, lean)
            except topo.GeometryError:
                raise
            except Exception as e:
                raise topo.GeometryError("The dome couldn't be made on this face: {}".format(
                    topo._msg(e)))
            if t.isNull() or t.Volume < 1e-9:
                raise topo.GeometryError("The dome came out empty; try another height.")
            tools.append((bid, topo.tagged(t, p.tag)))
    for bid, t in tools:
        scope = common.Scope(False, [bid])
        if p.reverse:
            r = common.apply_cut(out, t, p.feature, p.tag, scope, common.Keep(), p.alloc)
        else:
            r = common.apply_add(out, t, p.feature, p.tag, True, scope, p.alloc)
        if res_all is None:
            res_all = r
        else:
            res_all.touched.extend(r.touched)
            res_all.created.extend(r.created)
            res_all.warnings.extend(r.warnings)
            res_all.bodies = r.bodies
        out = r.bodies
    return res_all, topo.compound([t for _b, t in tools], p.tag)
