# SPDX-License-Identifier: LGPL-2.1-or-later
"""Surface tools: Knit, Planar, Filled, Trim, Extend; Delete Face; Thicken.

SolidWorks' Insert > Surface menu and Insert > Face > Delete, Insert > Boss/Base
> Thicken and Insert > Cut > Thicken.

- **Knit:** surface bodies sewn into one; closed, optionally a solid.
- **Planar:** a flat surface inside closed, coplanar edges or a sketch.
- **Filled Surface:** a patch inside a closed boundary of edges, touching
  (Contact) or tangent to (Tangent, Curvature) the faces beside them, and
  through constraint curves or points.
- **Trim:** surfaces cut by planes, sketches or surfaces (Standard) or by each
  other (Mutual); the picked pieces are kept or removed.
- **Extend:** surface edges carried on by a distance, on the same surface or
  straight on (Linear).
- **Delete Face:** Delete (a solid becomes a surface body), Delete and Patch (the
  faces around heal over the gap: OpenCASCADE's defeaturing), Delete and Fill (a
  filled patch over each gap, optionally tangent).
- **Thicken:** a surface body made a solid of a thickness, on side 1, side 2 or
  both; or the solid between a closed surface's faces. Thickened Cut cuts with
  it.
"""

import FreeCAD as App
import Part

from .. import topo
from ..bodies import SOLID, SURFACE, pieces_of
from . import common

STANDARD, MUTUAL = "Standard", "Mutual"
TRIM_TYPES = [STANDARD, MUTUAL]
SAME_SURFACE, LINEAR = "Same Surface", "Linear"
EXTEND_TYPES = [SAME_SURFACE, LINEAR]
DISTANCE, UP_TO_POINT, UP_TO_SURFACE = "Distance", "Up To Point", "Up To Surface"
EXTEND_ENDS = [DISTANCE, UP_TO_POINT, UP_TO_SURFACE]
CONTACT, TANGENT, CURVATURE = "Contact", "Tangent", "Curvature"
CONTINUITY = [CONTACT, TANGENT, CURVATURE]
_ORDER = {CONTACT: 0, TANGENT: 1, CURVATURE: 3}          # GeomAbs_C0, G1, G2
DELETE, PATCH, FILL = "Delete", "Delete and Patch", "Delete and Fill"
DELETE_TYPES = [DELETE, PATCH, FILL]
SIDE1, SIDE2, BOTH = "Side 1", "Side 2", "Both Sides"
SIDES = [SIDE1, SIDE2, BOTH]
KNIT_TOL = 1e-4


class Params(object):
    """What any surface tool may need; each uses its own part."""

    def __init__(self):
        self.feature = "Surface"
        self.tag = 1
        self.alloc = None
        self.bodies = []            # body IDs
        self.faces = []
        self.edges = []
        self.tools = []             # cutting shapes (Trim Standard)
        self.points = []            # App.Vector: trim pieces, fill constraint points
        self.curves = []            # fill constraint curves
        self.wires = []             # planar surface boundaries (edges or sketch shapes)
        self.solid = False
        self.merge = True
        self.tolerance = KNIT_TOL
        self.kind = None            # TRIM_TYPES, EXTEND_TYPES, DELETE_TYPES
        self.keep = True            # Trim: keep (or remove) the picked pieces
        self.continuity = CONTACT
        self.reverse = False
        self.distance = 5.0
        self.thickness = 1.0
        self.side = SIDE1
        self.mode = "Add"
        self.scope = common.Scope()


# ------------------------------------------------------------------ helpers

def _new_ids(p, shapes, base):
    if p.alloc is not None:
        return p.alloc.take(shapes)
    return ["{}:{}".format(p.feature, i + 1) for i in range(len(shapes))]


def _sew(faces, tol, tag):
    """Faces sewn into as few shells as they make."""
    faces = [f for f in faces if f is not None]
    if not faces:
        raise topo.GeometryError("Nothing is left to make a surface from.")
    try:
        sh = Part.Shell(faces)
    except Exception:
        sh = Part.makeCompound(faces)
    try:
        sh.sewShape(tol)
    except TypeError:
        sh.sewShape()
    out = [sh] if sh.ShapeType == "Shell" else (list(sh.Shells) or list(sh.Faces))
    return topo.tagged(out[0] if len(out) == 1 else Part.makeCompound(out), tag)


def free_edges(shape):
    """Edges with only one face beside them (the open boundary)."""
    out = []
    for e in shape.Edges:
        try:
            faces = shape.ancestorsOfType(e, Part.Face)
        except Exception:
            continue
        if len(faces) == 1:
            try:
                if e.isSeam(faces[0]):
                    continue
            except Exception:
                pass
            out.append(e)
    return out


def _solid_of(shape, what):
    shells = shape.Shells if shape.ShapeType != "Shell" else [shape]
    if not shells or any(not s.isClosed() for s in shells):
        n = len(free_edges(shape))
        raise topo.GeometryError("The {} isn't closed ({} open edge{}), so it can't be a "
                                 "solid. Close the gaps, or untick Create solid."
                                 .format(what, n, "" if n == 1 else "s"))
    solids = []
    for s in shells:
        so = Part.Solid(s)
        if so.Volume < 0:
            so.reverse()
        solids.append(so)
    return solids[0] if len(solids) == 1 else Part.makeCompound(solids)


def _body_of_edges(base, edges):
    """(body, the body's own edges) when every edge is on one body, else (None, [])."""
    for b in base:
        own = []
        for e in edges:
            hit = next((x for x in b.shape.Edges if x.isSame(e)), None)
            if hit is None:
                for x in b.shape.Edges:
                    if abs(x.Length - e.Length) < 1e-7 and \
                            (x.CenterOfMass - e.CenterOfMass).Length < 1e-6:
                        hit = x
                        break
            if hit is None:
                break
            own.append(hit)
        if len(own) == len(edges):
            return b, own
    return None, []


def _support(body_shape, edge):
    """The face of a body beside an edge (the first, on a solid)."""
    try:
        faces = body_shape.ancestorsOfType(edge, Part.Face)
    except Exception:
        return None
    return faces[0] if faces else None


def _fill(edges, supports, order, curves=(), points=()):
    """A patch inside ``edges``; tangent (order 1) or curvature (3) to ``supports``."""
    mf = Part.BRepOffsetAPI.MakeFilling()
    for e, s in zip(edges, supports):
        if order and s is not None:
            mf.add(e, s, order, True)
        else:
            mf.add(e, 0, True)
    for c in curves:
        for e in c.Edges:
            mf.add(e, 0, False)
    for pt in points:
        mf.add(App.Vector(pt))
    mf.build()
    r = mf.shape()
    if r.isNull() or not r.Faces:
        raise topo.GeometryError("The fill made no face.")
    return r.Faces[0]


def fill_patch(edges, supports, continuity, curves=(), points=()):
    """(face, warning): falls back to Contact when OpenCASCADE can't be tangent."""
    order = _ORDER.get(continuity, 0)
    try:
        return _fill(edges, supports, order, curves, points), None
    except Exception as e:
        if order == 0:
            raise topo.GeometryError("The boundary couldn't be filled: {}. It must be one "
                                     "closed loop of edges.".format(topo._msg(e)))
    try:
        face = _fill(edges, supports, 0, curves, points)
    except Exception as e:
        raise topo.GeometryError("The boundary couldn't be filled: {}.".format(topo._msg(e)))
    return face, ("The patch couldn't be {} to the faces around it; it only touches them "
                  "(Contact).".format(continuity.lower()))


def _loops(edges):
    try:
        groups = Part.sortEdges(list(edges))
    except Exception:
        groups = [list(edges)]
    return [Part.Wire(g) for g in groups]


# ------------------------------------------------------------------ Knit

def knit(p, base):
    ids = [i for i in p.bodies if i]
    if len(ids) < 1:
        raise topo.GeometryError("Pick the surfaces to knit.")
    faces = []
    for i in ids:
        b = base.get(i)
        if b is None:
            raise topo.GeometryError("A surface picked to knit no longer exists. Re-pick it.")
        if b.kind != SURFACE:
            raise topo.GeometryError("Only surface bodies can be knitted; {} is a solid."
                                     .format(i))
        faces.extend(f.copy() for f in b.shape.Faces)
    sewn = _sew(faces, p.tolerance, p.tag)
    warnings = []
    pieces = sewn.Shells if sewn.ShapeType == "Compound" else [sewn]
    if len(pieces) > 1:
        warnings.append("The surfaces knitted into {} separate pieces: they don't all meet "
                        "within the gap tolerance.".format(len(pieces)))
    out_shape = sewn
    if p.solid:
        out_shape = _solid_of(sewn, "knitted surface")
    if p.merge:
        try:
            out_shape = topo.refine(out_shape, p.tag)
        except topo.GeometryError:
            pass
    out = base.copy()
    out.replace(ids[0], out_shape, p.feature)
    for i in ids[1:]:
        out.remove(i)
    res = common.Result(out)
    res.touched.append(ids[0])
    res.warnings.extend(warnings)
    return res, out_shape


# ------------------------------------------------------------------ Planar

def planar(p, base):
    faces = []
    for shape in p.wires:
        if shape.Faces:
            faces.extend(shape.Faces)
            continue
        loops = _loops(shape.Edges)
        if any(not w.isClosed() for w in loops):
            raise topo.GeometryError("The boundary isn't closed. A planar surface needs closed "
                                     "loops of edges in one plane.")
        try:
            f = Part.makeFace(loops, "Part::FaceMakerBullseye")
        except Exception as e:
            raise topo.GeometryError("The edges aren't in one plane, or cross each other ({})."
                                     .format(topo._msg(e)))
        faces.extend(f.Faces)
    if not faces:
        raise topo.GeometryError("Pick a sketch, or closed edges in one plane.")
    for f in faces:
        if f.Surface.TypeId != "Part::GeomPlane":
            raise topo.GeometryError("The boundary isn't flat; use a Filled Surface instead.")
    shape = topo.tagged(faces[0] if len(faces) == 1 else Part.makeCompound(faces), p.tag)
    out = base.copy()
    res = common.Result(out)
    for i, f in zip(_new_ids(p, [shape], base), [shape]):
        out.add(i, f, p.feature, SURFACE)
        res.created.append(i)
    return res, shape


# ------------------------------------------------------------------ Filled

def filled(p, base):
    if not p.edges:
        raise topo.GeometryError("Pick the patch boundary: edges forming a closed loop.")
    loops = _loops(p.edges)
    if len(loops) != 1 or not loops[0].isClosed():
        raise topo.GeometryError("The patch boundary must be one closed loop of edges "
                                 "({} piece{} now).".format(len(loops),
                                                            "" if len(loops) == 1 else "s"))
    body, own = _body_of_edges(base, p.edges)
    supports = [_support(body.shape, e) if body is not None else None for e in own] \
        if body is not None else [None] * len(p.edges)
    edges = own if body is not None else list(p.edges)
    if p.continuity != CONTACT and not any(s is not None for s in supports):
        warn_support = ("The boundary has no faces beside it (sketch edges), so the patch "
                        "only touches it.")
    else:
        warn_support = None
    face, warn = fill_patch(edges, supports, p.continuity, p.curves, p.points)
    face = topo.tagged(face, p.tag)
    if p.reverse:
        face.reverse()
    out = base.copy()
    res = common.Result(out)
    for w in (warn_support, warn):
        if w:
            res.warnings.append(w)
    if p.merge and body is not None and body.kind == SURFACE:
        sewn = _sew([f.copy() for f in body.shape.Faces] + [face], p.tolerance, p.tag)
        if p.solid:
            sewn = _solid_of(sewn, "surface with the patch")
        out.replace(body.id, sewn, p.feature)
        res.touched.append(body.id)
        return res, face
    if p.solid:
        res.warnings.append("Create solid needs the boundary to be on a surface body (Merge "
                            "result); the patch is a surface of its own.")
    for i in _new_ids(p, [face], base):
        out.add(i, face, p.feature, SURFACE)
        res.created.append(i)
    return res, face


# ------------------------------------------------------------------ Trim

def _piece_at(pieces, pt, tol):
    best = None
    v = Part.Vertex(pt)
    for k, s in enumerate(pieces):
        d = s.distToShape(v)[0]
        if best is None or d < best[0]:
            best = (d, k)
    return best[1] if best is not None and best[0] < tol else None


def trim_pieces(p, base):
    """{body id: [pieces]} the trim makes (the panel lists and picks them)."""
    targets = [i for i in p.bodies if i]
    out = {}
    if p.kind == MUTUAL:
        if len(targets) < 2:
            raise topo.GeometryError("Mutual trim: pick two or more surfaces that cross.")
        shapes = {}
        for i in targets:
            b = base.get(i)
            if b is None or b.kind != SURFACE:
                raise topo.GeometryError("Mutual trim works on surface bodies; re-pick them.")
            shapes[i] = b.shape
        for i in targets:
            others = [shapes[j] for j in targets if j != i]
            r = topo.slice_by(shapes[i], others, p.tag)
            out[i] = [s for s in pieces_of(r, SURFACE) if s.Area > 1e-9]
        return out
    if not p.tools:
        raise topo.GeometryError("Pick the trim tool: a plane, sketch or surface.")
    cands = targets or base.ids(SURFACE)
    for i in cands:
        b = base.get(i)
        if b is None or b.kind != SURFACE:
            continue
        if any(t.isSame(b.shape) for t in p.tools):
            continue
        if not any(topo.touches(b.shape, t) for t in p.tools):
            continue
        r = topo.slice_by(b.shape, p.tools, p.tag)
        ps = [s for s in pieces_of(r, SURFACE) if s.Area > 1e-9]
        if len(ps) > 1:
            out[i] = ps
    if not out:
        raise topo.GeometryError("The trim tool doesn't cut any surface.")
    return out


def trim(p, base):
    pieces = trim_pieces(p, base)
    if not p.points:
        raise topo.GeometryError("Click the pieces to {} in the view.".format(
            "keep" if p.keep else "remove"))
    size = max(b.shape.BoundBox.DiagonalLength for b in base) if len(base) else 1.0
    tol = max(1e-3 * size, 1e-4)
    picked = {i: set() for i in pieces}
    for pt in p.points:
        best = None
        for i, ps in pieces.items():
            k = _piece_at(ps, pt, tol)
            if k is not None:
                d = ps[k].distToShape(Part.Vertex(pt))[0]
                if best is None or d < best[0]:
                    best = (d, i, k)
        if best is not None:
            picked[best[1]].add(best[2])
    if not any(picked.values()):
        raise topo.GeometryError("The picked points aren't on any trimmed piece any more. "
                                 "Pick the pieces again.")
    out = base.copy()
    res = common.Result(out)
    kept_all = []
    for i, ps in pieces.items():
        keep = [s for k, s in enumerate(ps) if (k in picked[i]) == p.keep]
        if p.kind == MUTUAL:
            kept_all.extend(keep)
            continue
        if not keep:
            out.remove(i)
            continue
        faces = [f.copy() for s in keep for f in s.Faces]
        out.replace(i, _sew(faces, p.tolerance, p.tag), p.feature)
        res.touched.append(i)
    if p.kind == MUTUAL:
        ids = list(pieces)
        if not kept_all:
            raise topo.GeometryError("Every piece would be removed.")
        sewn = _sew([f.copy() for s in kept_all for f in s.Faces], p.tolerance, p.tag)
        out.replace(ids[0], sewn, p.feature)
        for i in ids[1:]:
            out.remove(i)
        res.touched.append(ids[0])
    shown = [out.get(i).shape for i in res.touched if out.get(i) is not None]
    return res, topo.compound(shown, p.tag) if shown else None


# ------------------------------------------------------------------ Extend

def _outward(face, e, pt):
    """The direction in the face's surface, square to the edge, away from the face."""
    u, v = face.Surface.parameter(pt)
    n = face.normalAt(u, v)
    t = e.tangentAt(e.Curve.parameter(pt))
    o = n.cross(t)
    if o.Length < 1e-12:
        return None
    o.normalize()
    d = max(face.BoundBox.DiagonalLength * 1e-3, 1e-4)
    ins = face.distToShape(Part.Vertex(pt + o * d))[0]
    outs = face.distToShape(Part.Vertex(pt - o * d))[0]
    return o if ins > outs else -o


def _linear_strip(face, e, dist):
    first, last = e.FirstParameter, e.LastParameter
    n = 24
    pts, ext = [], []
    for k in range(n + 1):
        u = first + (last - first) * k / float(n)
        pt = e.valueAt(u)
        o = _outward(face, e, pt)
        if o is None:
            raise topo.GeometryError("Couldn't find which way the surface goes on at an edge.")
        pts.append(pt)
        ext.append(pt + o * dist)
    base_edge = Part.Edge(e.Curve, first, last)
    if e.Curve.TypeId == "Part::GeomLine" and all(
            ((q - ext[0]).cross(ext[-1] - ext[0])).Length < 1e-9 for q in ext):
        far = Part.LineSegment(ext[0], ext[-1]).toShape()
    else:
        bc = Part.BSplineCurve()
        bc.interpolate(ext, PeriodicFlag=False)
        far = bc.toShape()
    return Part.makeRuledSurface(base_edge, far).Faces[0]


def _same_surface_strip(face, e, dist):
    s = face.Surface
    if s.TypeId == "Part::GeomPlane":
        return None                 # straight on is the same plane
    if s.TypeId in ("Part::GeomBSplineSurface", "Part::GeomBezierSurface"):
        return None
    u0, u1, v0, v1 = face.ParameterRange
    a, b = e.valueAt(e.FirstParameter), e.valueAt(e.LastParameter)
    ua, va = s.parameter(a)
    ub, vb = s.parameter(b)
    mid = e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))
    um, vm = s.parameter(mid)
    tol = 1e-6

    def speed(du, dv):
        p0 = s.value(um, vm)
        p1 = s.value(um + du, vm + dv)
        return (p1 - p0).Length / max(abs(du) + abs(dv), 1e-12)
    if abs(ua - ub) < tol and abs(ua - um) < tol:          # an iso-u edge
        k = dist / max(speed(1e-4, 0), 1e-12)
        if abs(ua - u0) < tol:
            return s.toShape(u0 - k, u0, v0, v1)
        if abs(ua - u1) < tol:
            return s.toShape(u1, u1 + k, v0, v1)
    if abs(va - vb) < tol and abs(va - vm) < tol:          # an iso-v edge
        k = dist / max(speed(0, 1e-4), 1e-12)
        if abs(va - v0) < tol:
            return s.toShape(u0, u1, v0 - k, v0)
        if abs(va - v1) < tol:
            return s.toShape(u0, u1, v1, v1 + k)
    return None


def _reach(face, e, end, target):
    """How far an edge's extension must go to reach a point (Up To Point) or a
    surface (Up To Surface, the farthest point of the edge's)."""
    mid = e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))
    o = _outward(face, e, mid)
    if o is None:
        raise topo.GeometryError("Couldn't find which way the surface goes on at an edge.")
    if end == UP_TO_POINT:
        d = (target - mid).dot(o)
        if d <= 1e-9:
            raise topo.GeometryError("The point is behind the edge: pick one the surface "
                                     "would reach going on.")
        return d
    big = 10 * (face.BoundBox.DiagonalLength + target.BoundBox.DiagonalLength +
                (target.BoundBox.Center - mid).Length)
    far = 0.0
    for k in range(9):
        u = e.FirstParameter + (e.LastParameter - e.FirstParameter) * k / 8.0
        q = e.valueAt(u)
        ok = _outward(face, e, q) or o
        seg = Part.LineSegment(q, q + ok * big).toShape()
        try:
            hits = [(v.Point - q).dot(ok) for v in seg.section(target).Vertexes]
        except Exception:
            hits = []
        hits = [h for h in hits if h > 1e-9]
        if not hits:
            raise topo.GeometryError("The surface doesn't reach the picked surface going on "
                                     "from the edge.")
        far = max(far, min(hits))
    return far


def _trimmed_to(strip, e, target, tag):
    """The strip cut back to where it meets the target surface (the part by the edge)."""
    from .. import bodyops
    try:
        tool = bodyops.extended(target.Faces[0], 4 * strip.BoundBox.DiagonalLength) \
            if len(target.Faces) == 1 else target
        pieces = topo.slice_by(strip, [tool], tag).Faces
    except Exception:
        return strip
    if len(pieces) < 2:
        return strip
    mid = e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))
    return min(pieces, key=lambda f: f.distToShape(Part.Vertex(mid))[0])


def extend(p, base):
    if not p.edges:
        raise topo.GeometryError("Pick the surface edges to extend.")
    end = getattr(p, "end", DISTANCE)
    if end == UP_TO_POINT and getattr(p, "target", None) is None:
        raise topo.GeometryError("Pick the point to extend up to.")
    if end == UP_TO_SURFACE and getattr(p, "target", None) is None:
        raise topo.GeometryError("Pick the surface or plane to extend up to.")
    if end == DISTANCE and p.distance <= 0:
        raise topo.GeometryError("The distance must be greater than zero.")
    groups = {}
    for e in p.edges:
        body, own = _body_of_edges(base, [e])
        if body is None or body.kind != SURFACE:
            raise topo.GeometryError("Pick edges of a surface body (open edges).")
        groups.setdefault(body.id, []).append(own[0])
    out = base.copy()
    res = common.Result(out)
    shown = []
    for bid, edges in groups.items():
        shape = base.get(bid).shape
        strips = []
        for e in edges:
            face = _support(shape, e)
            if face is None or len(shape.ancestorsOfType(e, Part.Face)) != 1:
                raise topo.GeometryError("Only open edges of a surface can be extended.")
            strip = None
            dist = p.distance if end == DISTANCE else _reach(face, e, end, p.target)
            if end == UP_TO_SURFACE:
                dist *= 1.2                 # past it, then cut back to it
            if p.kind == SAME_SURFACE:
                strip = _same_surface_strip(face, e, dist)
                if strip is None and face.Surface.TypeId not in ("Part::GeomPlane",):
                    res.warnings.append("An edge couldn't continue on the same surface (it "
                                        "isn't one of the surface's own boundaries); it was "
                                        "extended straight on (Linear).")
            if strip is None:
                strip = _linear_strip(face, e, dist)
            if end == UP_TO_SURFACE:
                strip = _trimmed_to(strip, e, p.target, p.tag)
            strips.append(strip)
        shown.extend(strips)
        sewn = _sew([f.copy() for f in shape.Faces] + strips, p.tolerance, p.tag)
        if p.merge:
            try:
                sewn = topo.refine(sewn, p.tag)
            except topo.GeometryError:
                pass
        out.replace(bid, sewn, p.feature)
        res.touched.append(bid)
    return res, topo.compound(shown, p.tag)


# ------------------------------------------------------------------ Delete Face

def _faces_by_body(base, faces):
    from .edges import faces_by_body
    return faces_by_body(base, faces)


def delete_face(p, base):
    if not p.faces:
        raise topo.GeometryError("Pick the faces to delete.")
    groups = _faces_by_body(base, p.faces)
    out = base.copy()
    res = common.Result(out)
    shown = []
    for bid, gone in groups.items():
        b = base.get(bid)
        shape = topo.tagged(b.shape, p.tag)
        from .edges import find_in
        gone = [find_in(shape, g) or g for g in gone]
        rest = [f for f in shape.Faces if not any(f.isSame(g) for g in gone)]
        shown.extend(gone)
        if p.kind == PATCH:
            try:
                r = shape.defeaturing(gone)
            except Exception as e:
                raise topo.GeometryError("The faces around couldn't heal over the gap ({}). "
                                         "Try Delete and Fill.".format(topo._msg(e)))
            if r.isNull() or not r.isValid() or (b.kind == SOLID and not r.Solids):
                raise topo.GeometryError("The faces around couldn't heal over the gap. Try "
                                         "Delete and Fill, or delete fewer faces.")
            out.replace(bid, topo.tagged(r, p.tag), p.feature)
            res.touched.append(bid)
            continue
        if not rest:
            out.remove(bid)
            continue
        sewn = _sew([f.copy() for f in rest], p.tolerance, p.tag)
        if p.kind == FILL:
            patches = []
            for loop in _loops(free_edges(sewn)):
                if not loop.isClosed():
                    raise topo.GeometryError("A gap left by the deleted faces isn't one closed "
                                             "loop, so it can't be filled.")
                sup = [_support(sewn, e) for e in loop.Edges]
                face, warn = fill_patch(loop.Edges, sup, p.continuity)
                if warn:
                    res.warnings.append(warn)
                patches.append(face)
            sewn = _sew([f.copy() for f in sewn.Faces] + patches, p.tolerance, p.tag)
            shells = sewn.Shells if sewn.ShapeType != "Shell" else [sewn]
            if b.kind == SOLID and shells and all(s.isClosed() for s in shells):
                sewn = _solid_of(sewn, "filled body")
        out.replace(bid, sewn, p.feature)
        res.touched.append(bid)
    return res, topo.compound(shown, p.tag)


# ------------------------------------------------------------------ Thicken

def thicken_tool(p, base):
    if not p.bodies or not p.bodies[0]:
        raise topo.GeometryError("Pick the surface to thicken.")
    b = base.get(p.bodies[0])
    if b is None:
        raise topo.GeometryError("The surface to thicken no longer exists. Re-pick it.")
    if b.kind != SURFACE:
        raise topo.GeometryError("Thicken works on surface bodies.")
    shape = topo.tagged(b.shape, p.tag)
    closed = all(s.isClosed() for s in shape.Shells) and shape.Shells
    if p.solid:
        if not closed:
            raise topo.GeometryError("Create solid from enclosed volume needs a closed "
                                     "surface.")
        return b.id, _solid_of(shape, "surface")
    t = p.thickness
    if t <= 0:
        raise topo.GeometryError("The thickness must be greater than zero.")
    src = shape.Shells[0] if len(shape.Shells) == 1 else (
        shape.Faces[0] if len(shape.Faces) == 1 else shape)
    try:
        if p.side == BOTH:
            mid = src.makeOffsetShape(-t / 2.0, 1e-6, join=2)
            r = mid.makeOffsetShape(t, 1e-6, join=2, fill=True)
        else:
            d = t if p.side == SIDE1 else -t
            r = src.makeOffsetShape(d, 1e-6, join=2, fill=True)
    except Exception as e:
        raise topo.GeometryError("The surface couldn't be thickened by {:g}: {}. Try a smaller "
                                 "thickness.".format(t, topo._msg(e)))
    if r.isNull() or not r.Solids:
        raise topo.GeometryError("Thickening made no solid. Try a smaller thickness.")
    sol = r.Solids[0] if len(r.Solids) == 1 else Part.makeCompound(r.Solids)
    if sol.Volume < 0:
        sol.reverse()
    return b.id, topo.tagged(sol, p.tag)


def thicken(p, base):
    sid, tool = thicken_tool(p, base)
    rest = base.copy()
    rest.remove(sid)                    # the surface is used up, as in SolidWorks
    if p.mode == "Add":
        res = common.apply_add(rest, tool, p.feature, p.tag, p.merge, p.scope, p.alloc)
        return res, tool
    res = common.apply_cut(rest, tool, p.feature, p.tag, p.scope, common.Keep(), p.alloc)
    if not res.touched:
        raise topo.GeometryError("The thickened surface doesn't cut any body.")
    return res, common.removed_material(tool, rest, p.scope, p.tag)
