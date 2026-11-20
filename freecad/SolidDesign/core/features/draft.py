# SPDX-License-Identifier: LGPL-2.1-or-later
"""Draft (SolidWorks' manual Draft): tapers faces by an angle so a moulded part
releases from its mould.

- **Neutral Plane:** the faces turn about where they meet the neutral plane.
  Face propagation adds faces: Along Tangent, All Faces (every face parallel to
  the direction of pull), Inner Faces or Outer Faces.
- **Parting Line:** the faces next to the parting lines, on one side, turn about
  those lines. The parting lines must lie in one plane (OpenCASCADE drafts about
  a plane).
- **DraftXpert:** a neutral plane and an angle; with no faces picked it drafts
  every face that has less draft than the angle. Faces OpenCASCADE can't draft
  are left out and listed, instead of the whole draft failing; the panel shows a
  draft analysis of the faces.
- **Step Draft:** parting lines at several heights (each square to the direction
  of pull); the faces at each height turn about their own lines, leaving steps
  between them (SolidWorks' perpendicular steps).

Positive draft makes the part narrower along the direction of pull.
"""

import FreeCAD as App
import Part

from .. import topo
from ..bodies import SOLID
from . import common, edges as edgemod

NEUTRAL_PLANE = "Neutral Plane"
PARTING_LINE = "Parting Line"
STEP_DRAFT = "Step Draft"
DRAFTXPERT = "DraftXpert"
TYPES = [NEUTRAL_PLANE, PARTING_LINE, STEP_DRAFT, DRAFTXPERT]

# Draft analysis (SolidWorks' colours): enough draft towards the pull, enough
# away from it, not enough (needs draft), or some of each (straddle).
POSITIVE, NEGATIVE, NEEDS, STRADDLE = "Positive", "Negative", "Needs draft", "Straddle"

NONE, TANGENT, ALL, INNER, OUTER = ("None", "Along Tangent", "All Faces", "Inner Faces",
                                    "Outer Faces")
PROPAGATION = [NONE, TANGENT, ALL, INNER, OUTER]
PROPAGATION_PARTING = [NONE, TANGENT]

TOL = 1e-6
MAX_ANGLE = 89.0


class Params(object):
    def __init__(self):
        self.kind = NEUTRAL_PLANE
        self.angle = 1.0
        self.plane = None           # neutral plane: (point, unit normal)
        self.faces = []             # faces to draft (shapes from the model before)
        self.edges = []             # parting lines (edges from the model before)
        self.pull = None            # direction of pull (vector) or None: from the plane
        self.reverse = False
        self.other_face = False     # Parting Line: draft the faces on the other side
        self.propagation = NONE
        self.feature = "Draft"
        self.tag = 1


def compute(p, base):
    if not 0 < p.angle <= MAX_ANGLE:
        raise topo.GeometryError("The draft angle must be more than 0° and at most {:g}°."
                                 .format(MAX_ANGLE))
    if p.kind == PARTING_LINE:
        groups, point, normal, pull = _parting(p, base)
        steps = [(point, normal, pull, groups)]
    elif p.kind == STEP_DRAFT:
        steps = _steps(p, base)
    elif p.kind == DRAFTXPERT:
        return _xpert(p, base)
    else:
        groups, point, normal, pull = _neutral(p, base)
        steps = [(point, normal, pull, groups)]
    out = base.copy()
    res = common.Result(out)
    changed = []
    bids = []
    for _pt, _n, _d, groups in steps:
        bids.extend(b for b in groups if b not in bids)
    for bid in bids:
        body = base.get(bid)
        if body.kind != SOLID:
            raise topo.GeometryError("Only solid bodies can be drafted.")
        shape = body.shape
        r = shape
        # A draft keeps the faces' order, so indices into the original body still
        # name the right faces after an earlier step.
        for point, normal, pull, groups in steps:
            if bid not in groups:
                continue
            idx = [_index(shape, f) for f in groups[bid]]
            r = topo.draft(r, idx, point, normal, pull, p.angle, p.tag)
        out.replace(bid, r, p.feature)
        res.touched.append(bid)
        changed.append(r)
    preview = topo.compound(changed, p.tag) if changed else None
    return res, preview


# ------------------------------------------------------------------ neutral plane

def _neutral(p, base):
    if p.plane is None:
        raise topo.GeometryError("Pick the neutral plane: a plane or a planar face.")
    if not p.faces and p.propagation not in (ALL, INNER, OUTER):
        raise topo.GeometryError("Pick the faces to draft.")
    point, normal = p.plane
    groups = edgemod.faces_by_body(base, p.faces) if p.faces else {}
    if not groups:
        solids = base.ids(SOLID)
        if len(solids) != 1:
            raise topo.GeometryError("Pick at least one face to draft, so the body is known.")
        groups = {solids[0]: []}
    pull = _pull(p, normal, [f for fs in groups.values() for f in fs] or
                 [base.get(b).shape for b in groups], point)
    out = {}
    for bid, faces in groups.items():
        shape = base.get(bid).shape
        out[bid] = _propagate(shape, faces, p.propagation, pull)
        if not out[bid]:
            raise topo.GeometryError("No face is parallel to the direction of pull, so there "
                                     "is nothing to draft.")
        for f in out[bid]:
            if _parallel_to_plane(f, pull):
                raise topo.GeometryError("A face to draft is parallel to the neutral plane; "
                                         "it can't be drafted. Pick the side faces.")
    return out, point, normal, pull


def _pull(p, normal, shapes, point):
    """The direction of pull: given, or the neutral plane's normal turned towards
    the faces being drafted (so a neutral plane at the base tapers the part
    upwards); Reverse flips it."""
    if p.pull is not None:
        d = App.Vector(p.pull)
    else:
        d = App.Vector(normal)
        c = _centre(shapes)
        s = (c - point).dot(d)
        if s < -TOL * max(1.0, _size(shapes)):
            d = -d
    if d.Length < TOL:
        raise topo.GeometryError("The direction of pull has no length.")
    d.normalize()
    return -d if p.reverse else d


def _centre(shapes):
    pts = []
    for s in shapes:
        try:
            pts.append(s.CenterOfMass)
        except Exception:
            pts.append(s.BoundBox.Center)
    c = App.Vector()
    for q in pts:
        c += q
    return c * (1.0 / max(1, len(pts)))


def _size(shapes):
    box = App.BoundBox()
    for s in shapes:
        box.add(s.BoundBox)
    return box.DiagonalLength if box.isValid() else 1.0


# ------------------------------------------------------------------ parting line

def _edges_by_body(p, base):
    if not p.edges:
        raise topo.GeometryError("Pick the parting lines: the edges the faces turn about.")
    by_body = {}
    for e in p.edges:
        hit = None
        for b in base:
            found = edgemod.find_in(b.shape, e)
            if found is not None:
                hit = (b.id, found)
                break
        if hit is None:
            raise topo.GeometryError("A parting line isn't on any body before this feature. "
                                     "Re-pick it.")
        lst = by_body.setdefault(hit[0], [])
        if not any(hit[1].isSame(x) for x in lst):
            lst.append(hit[1])
    return by_body


def _faces_beside(shape, es, point, pull, other):
    """The faces next to the parting lines, on the pull side (or the other)."""
    side = -1.0 if other else 1.0
    faces = []
    for e in es:
        for f in shape.ancestorsOfType(e, Part.Face):
            if _parallel_to_plane(f, pull):
                continue
            if (_face_mid(f) - point).dot(pull) * side > TOL:
                if not any(f.isSame(x) for x in faces):
                    faces.append(f)
                break
    return faces


def _steps(p, base):
    """Step Draft: the parting lines grouped by height along the pull, each group
    drafted about its own plane."""
    by_body = _edges_by_body(p, base)
    edges = [e for es in by_body.values() for e in es]
    if p.pull is not None:
        d = App.Vector(p.pull)
    else:
        plane = _plane_through(edges)
        if plane is None:
            raise topo.GeometryError("Pick the direction of pull for a step draft.")
        d = App.Vector(plane[1])
        c = _centre([base.get(b).shape for b in by_body])
        if (c - plane[0]).dot(d) < 0:
            d = -d
    d.normalize()
    if p.reverse:
        d = -d
    heights = {}
    for bid, es in by_body.items():
        for e in es:
            pts = [v.Point for v in e.Vertexes] + [
                e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))]
            hs = [q.dot(d) for q in pts]
            if max(hs) - min(hs) > 1e-6:
                raise topo.GeometryError("Each parting line of a step draft must be square to "
                                         "the direction of pull (tapered steps aren't supported "
                                         "yet).")
            key = round(hs[0], 6)
            heights.setdefault(key, {}).setdefault(bid, []).append(e)
    steps = []
    for h in sorted(heights):
        point = d * h
        groups = {}
        for bid, es in heights[h].items():
            shape = base.get(bid).shape
            faces = _faces_beside(shape, es, point, d, p.other_face)
            if p.propagation == TANGENT:
                faces = _tangent_faces(shape, faces)
            if faces:
                groups[bid] = faces
        if groups:
            steps.append((point, d, d, groups))
    if not steps:
        raise topo.GeometryError("No face next to the parting lines lies on that side. Try "
                                 "Other face, or Reverse direction.")
    return steps


def _parting(p, base):
    if not p.edges:
        raise topo.GeometryError("Pick the parting lines: the edges the faces turn about.")
    by_body = {}
    for e in p.edges:
        hit = None
        for b in base:
            found = edgemod.find_in(b.shape, e)
            if found is not None:
                hit = (b.id, found)
                break
        if hit is None:
            raise topo.GeometryError("A parting line isn't on any body before this feature. "
                                     "Re-pick it.")
        lst = by_body.setdefault(hit[0], [])
        if not any(hit[1].isSame(x) for x in lst):
            lst.append(hit[1])
    edges = [e for es in by_body.values() for e in es]
    plane = _plane_through(edges)
    if plane is None:
        raise topo.GeometryError("The parting lines must lie in one plane (in this version). "
                                 "Split a face with a plane first, or use a neutral plane.")
    point, normal = plane
    pull = _pull(p, normal, [base.get(b).shape for b in by_body], point) \
        if p.pull is not None else _parting_pull(p, normal, edges, by_body, base, point)
    out = {}
    for bid, es in by_body.items():
        shape = base.get(bid).shape
        side = -1.0 if p.other_face else 1.0
        faces = []
        for e in es:
            pick = None
            for f in shape.ancestorsOfType(e, Part.Face):
                if _parallel_to_plane(f, pull):
                    continue
                off = (_face_mid(f) - point).dot(pull)
                if off * side > TOL:
                    pick = f
                    break
            if pick is not None and not any(pick.isSame(x) for x in faces):
                faces.append(pick)
        if p.propagation == TANGENT:
            faces = _tangent_faces(shape, faces)
        if not faces:
            raise topo.GeometryError("No face next to the parting lines lies on that side. "
                                     "Try Other face, or Reverse direction.")
        out[bid] = faces
    return out, point, normal, pull


def _parting_pull(p, normal, edges, by_body, base, point):
    """Default direction of pull for a parting line: the plane's normal, towards
    more of the material (the side that gets drafted unless Other face)."""
    d = App.Vector(normal)
    c = _centre([base.get(b).shape for b in by_body])
    if (c - point).dot(d) < 0:
        d = -d
    d.normalize()
    return -d if p.reverse else d


def _plane_through(edges):
    try:
        pl = Part.Shape(edges).findPlane() if len(edges) else None
    except Exception:
        pl = None
    if pl is None:
        # One straight edge (or collinear edges) defines no plane on its own.
        return None
    n = App.Vector(pl.Axis)
    n.normalize()
    return App.Vector(pl.Position), n


# ------------------------------------------------------------------ faces

def _index(shape, face):
    for i, f in enumerate(shape.Faces, 1):
        if f.isSame(face):
            return i
    found = edgemod.find_in(shape, face)
    for i, f in enumerate(shape.Faces, 1):
        if found is not None and f.isSame(found):
            return i
    raise topo.GeometryError("A face to draft isn't on its body. Re-pick it.")


def _samples(face, n=3):
    u0, u1, v0, v1 = face.ParameterRange
    out = []
    for i in range(n):
        for j in range(n):
            u = u0 + (u1 - u0) * (i + 0.5) / n
            v = v0 + (v1 - v0) * (j + 0.5) / n
            try:
                q = face.valueAt(u, v)
                if face.isInside(q, 1e-6, True):
                    out.append((u, v))
            except Exception:
                pass
    return out or [(0.5 * (u0 + u1), 0.5 * (v0 + v1))]


def _along_pull(face, pull, tol=1e-6):
    """Whether the face contains the direction of pull (a wall: planes and
    cylinders parallel to it), so it can be drafted."""
    try:
        return all(abs(face.normalAt(u, v).dot(pull)) < tol for u, v in _samples(face))
    except Exception:
        return False


def _parallel_to_plane(face, pull, tol=1e-6):
    """A face square to the pull (a floor or a top): nothing to draft."""
    if face.Surface.TypeId != "Part::GeomPlane":
        return False
    try:
        return abs(abs(face.normalAt(0, 0).dot(pull)) - 1.0) < tol
    except Exception:
        return False


def _face_mid(face):
    u, v = _samples(face, 1)[0]
    try:
        return face.valueAt(u, v)
    except Exception:
        return face.CenterOfMass


def _tangent_faces(shape, faces):
    """Faces meeting the picks smoothly across an edge (SolidWorks' Along Tangent)."""
    out = list(faces)
    todo = list(faces)
    while todo:
        f = todo.pop()
        for e in f.Edges:
            for g in shape.ancestorsOfType(e, Part.Face):
                if any(g.isSame(x) for x in out):
                    continue
                if _tangent_across(f, g, e):
                    out.append(g)
                    todo.append(g)
    return out


def _tangent_across(f, g, e, tol=1e-4):
    try:
        q = e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))
        uf = f.Surface.parameter(q)
        ug = g.Surface.parameter(q)
        nf, ng = f.normalAt(*uf), g.normalAt(*ug)
        return abs(abs(nf.dot(ng)) - 1.0) < tol
    except Exception:
        return False


def _propagate(shape, faces, how, pull):
    if how == NONE:
        return list(faces)
    if how == TANGENT:
        return _tangent_faces(shape, faces)
    walls = [f for f in shape.Faces if _along_pull(f, pull)]
    if how == ALL:
        out = walls
    else:
        outer, inner = _classify(shape, walls, pull)
        out = outer if how == OUTER else inner
    for f in faces:                     # picks always count
        if not any(f.isSame(x) for x in out):
            out.append(f)
    return out


def _classify(shape, walls, pull):
    """Split walls into outer faces (on the outside of the part's section) and
    inner faces (holes and pockets)."""
    outer, inner = [], []
    for f in walls:
        q = _face_mid(f)
        h = q.dot(pull)
        try:
            wires = shape.slice(pull, h)
            sec = Part.makeFace(wires, "Part::FaceMakerBullseye") if wires else None
        except Exception:
            sec = None
        if sec is None or sec.isNull():
            outer.append(f)
            continue
        on_outer = False
        for face in sec.Faces:
            try:
                if face.OuterWire.distToShape(Part.Vertex(q))[0] < 1e-5:
                    on_outer = True
                    break
            except Exception:
                pass
        (outer if on_outer else inner).append(f)
    return outer, inner


# ------------------------------------------------------------------ DraftXpert

def face_draft(face, pull, angle):
    """Which of POSITIVE, NEGATIVE, NEEDS or STRADDLE a face is, for ``pull`` and the
    required ``angle`` (degrees). Floors and tops (square to the pull) are
    POSITIVE or NEGATIVE as they face."""
    import math
    lim = math.sin(math.radians(angle)) - 1e-9
    kinds = set()
    for u, v in _samples(face):
        try:
            d = face.normalAt(u, v).dot(pull)
        except Exception:
            continue
        kinds.add(POSITIVE if d >= lim else NEGATIVE if d <= -lim else NEEDS)
    if not kinds:
        return NEEDS
    if POSITIVE in kinds and NEGATIVE in kinds:
        return STRADDLE
    if NEEDS in kinds:
        return NEEDS if len(kinds) == 1 else STRADDLE
    return kinds.pop()


def analysis(shape, pull, angle):
    """{kind: [face index from 1]} for a body."""
    out = {POSITIVE: [], NEGATIVE: [], NEEDS: [], STRADDLE: []}
    for i, f in enumerate(shape.Faces, 1):
        out[face_draft(f, pull, angle)].append(i)
    return out


def xpert_pull(p, base):
    """The neutral plane (point, normal) and pull DraftXpert uses."""
    if p.plane is None:
        raise topo.GeometryError("Pick the neutral plane: a plane or a planar face.")
    point, normal = p.plane
    shapes = list(p.faces) or [b.shape for b in base if b.kind == SOLID]
    return point, normal, _pull(p, normal, shapes, point)


def _xpert(p, base):
    point, normal, pull = xpert_pull(p, base)
    if p.faces:
        groups = edgemod.faces_by_body(base, p.faces)
    else:
        groups = {}
        for b in base:
            if b.kind != SOLID:
                continue
            need = [b.shape.Faces[i - 1] for i in analysis(b.shape, pull, p.angle)[NEEDS]]
            need = [f for f in need if _along_pull(f, pull, 1e-3)]
            if need:
                groups[b.id] = need
        if not groups:
            raise topo.GeometryError("Every face already has at least {:g}° of draft."
                                     .format(p.angle))
    out = base.copy()
    res = common.Result(out)
    changed, skipped = [], []
    for bid, faces in groups.items():
        shape = base.get(bid).shape
        faces = [f for f in faces if not _parallel_to_plane(f, pull)]
        idx = [_index(shape, f) for f in faces]
        try:
            r = topo.draft(shape, idx, point, normal, pull, p.angle, p.tag)
        except topo.GeometryError:
            # One at a time: keep each face that drafts with the ones kept so far.
            ok, r = [], None
            for i in idx:
                try:
                    r = topo.draft(shape, ok + [i], point, normal, pull, p.angle, p.tag)
                    ok.append(i)
                except topo.GeometryError:
                    skipped.append(i)
            if r is None:
                continue
        out.replace(bid, r, p.feature)
        res.touched.append(bid)
        changed.append(r)
    if not changed:
        raise topo.GeometryError("None of the faces could be drafted about this neutral plane.")
    if skipped:
        res.warnings.append("DraftXpert left out {} face{} it couldn't draft (Face{})."
                            .format(len(skipped), "s" if len(skipped) > 1 else "",
                                    ", Face".join(str(i) for i in skipped)))
    return res, topo.compound(changed, p.tag)
