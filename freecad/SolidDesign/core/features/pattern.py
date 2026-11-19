# SPDX-License-Identifier: LGPL-2.1-or-later
"""Linear Pattern, Circular Pattern and Mirror.

Features are repeated by repeating their operation (spec 7.6): the seed
feature's tool shape is moved to each instance and added or cut with the seed's
own mode. Bodies are copied as new bodies (or merged, for Mirror's Merge solids).
"""

import FreeCAD as App
import Part

from .. import topo
from ..bodies import SOLID
from . import common


class Seed(object):
    """A feature to repeat: its tool shape, Add or Cut, and Merge result."""

    def __init__(self, label, tool, mode, merge=True, scope=None):
        self.label = label
        self.tool = tool
        self.mode = mode
        self.merge = merge
        self.scope = scope          # common.Scope, or None for all bodies


def face_seed(body_id, faces, body, tag):
    """A seed from faces of a body (SolidWorks' Faces to Mirror/Pattern): the faces
    and caps over their open edges make a solid. Inside the body, it is material
    to add (a boss); outside, a gap to cut (a hole, a pocket)."""
    edges = []
    for f in faces:
        for e in f.Edges:
            try:
                if e.isSeam(f):
                    continue            # a cylinder's seam is inside its own face
            except Exception:
                pass
            edges.append(e)
    boundary = []
    for i, e in enumerate(edges):
        if sum(1 for j, o in enumerate(edges) if j != i and o.isSame(e)) == 0:
            boundary.append(e)
    caps = []
    if boundary:
        try:
            loops = Part.sortEdges(boundary)
        except Exception:
            loops = [boundary]
        for loop in loops:
            w = Part.Wire(loop)
            if not w.isClosed():
                raise topo.GeometryError("The faces' open edges don't close into loops. Pick "
                                         "every face of the feature (its walls and its top or "
                                         "floor).")
            try:
                cap = Part.Face(w)
                if not cap.isValid() or cap.Area <= 0:
                    raise ValueError
            except Exception:
                try:
                    cap = Part.makeFilledFace(loop)
                except Exception:
                    raise topo.GeometryError("Couldn't close the faces' open side with a face.")
            caps.append(cap)
    shell = Part.Shell([f.copy() for f in faces] + caps)
    shell.sewShape()
    shells = shell.Shells if shell.ShapeType != "Shell" else [shell]
    if len(shells) != 1 or not shells[0].isClosed():
        raise topo.GeometryError("The faces to repeat don't enclose a feature. Pick every face "
                                 "of it (walls and top or floor); its open side must lie on "
                                 "the body.")
    tool = Part.Solid(shells[0])
    if tool.Volume < 0:
        tool.reverse()
    if tool.Volume < 1e-9:
        raise topo.GeometryError("The faces to repeat enclose no volume.")
    inside = body.common(tool).Volume
    mode = "Add" if inside > 0.5 * tool.Volume else "Cut"
    return Seed("the picked faces", topo.tagged(tool, tag), mode, True,
                common.Scope(False, [body_id]))


def linear(d1, spacing1, n1, d2=None, spacing2=0.0, n2=1, seed_only=False, skip=()):
    """Placements of the instances (the seed excluded), SolidWorks' order."""
    if n1 < 1 or n2 < 1:
        raise topo.GeometryError("The number of instances must be at least 1.")
    if n1 * n2 < 2:
        raise topo.GeometryError("A pattern needs at least 2 instances.")
    out = []
    for j in range(n2):
        for i in range(n1):
            if i == 0 and j == 0:
                continue
            if seed_only and i > 0 and j > 0:
                continue
            if (i + 1, j + 1) in skip:
                continue
            v = d1 * (spacing1 * i)
            if d2 is not None:
                v = v + d2 * (spacing2 * j)
            out.append(App.Placement(v, App.Rotation()))
    return out


def circular(point, axis, angle, n, equal=True, skip=()):
    """Instances about an axis. With Equal spacing ``angle`` is the total angle
    (360: n instances round the circle); without, it is the angle between them.
    ``skip``: instance numbers (the seed is 1) to leave out."""
    if n < 2:
        raise topo.GeometryError("A pattern needs at least 2 instances.")
    if equal:
        step = angle / n if abs(angle - 360.0) < 1e-9 else angle / (n - 1)
    else:
        step = angle
    return [App.Placement(App.Vector(), App.Rotation(axis, step * k), point)
            for k in range(1, n) if (k + 1) not in skip]


def linear_slots(n1, n2, seed_only=False):
    """The instance numbers (i, j) of a linear pattern, seed first: for listing."""
    out = []
    for j in range(n2):
        for i in range(n1):
            if seed_only and i > 0 and j > 0:
                continue
            out.append((i + 1, j + 1))
    return out


# ------------------------------------------------------------------ reference point

def reference_point(seeds, body_shapes):
    """Where the seed is: the centre of its shape (SolidWorks' seed centroid)."""
    shapes = [s.tool for s in seeds if s.tool is not None and not s.tool.isNull()]
    shapes += list(body_shapes)
    if not shapes:
        raise topo.GeometryError("Pick features, faces or bodies to pattern.")
    s = shapes[0]
    try:
        return s.CenterOfMass if s.Solids or s.Faces else s.BoundBox.Center
    except Exception:
        return s.BoundBox.Center


# ------------------------------------------------------------------ curve driven

TRANSLATE, TANGENT = "Align to seed", "Tangent to curve"
ALIGNMENTS = [TANGENT, TRANSLATE]


def curve_driven(curve, ref, n, spacing, equal, align, reverse=False, skip=()):
    """Instances along a curve (a skin.Section), from the point of the curve
    nearest the seed. ``spacing``: between instances, or (Equal spacing) ignored:
    the instances spread over the whole curve."""
    if n < 2:
        raise topo.GeometryError("A pattern needs at least 2 instances.")
    f0, _d = curve.fraction_of(ref)
    L = curve.total
    if equal:
        step = L / n if curve.closed else (L * (1 - f0) if not reverse else L * f0) / (n - 1)
    else:
        step = spacing
    sign = -1.0 if reverse else 1.0
    c0 = curve.at(f0)
    t0 = curve.tangent_at(f0)
    out = []
    for k in range(1, n):
        if (k + 1) in skip:
            continue
        f = f0 + sign * k * step / L
        if not curve.closed and (f < -1e-9 or f > 1 + 1e-9):
            raise topo.GeometryError("Instance {} falls off the end of the curve: make the "
                                     "spacing smaller or use fewer instances.".format(k + 1))
        f = min(max(f, 0.0), 1.0) if not curve.closed else f % 1.0
        c = curve.at(f)
        if align == TANGENT:
            t = curve.tangent_at(f)
            rot = App.Rotation(t0, t)
            # Turn about the seed's point on the curve, then carry it along.
            pl = App.Placement(c - c0, App.Rotation()).multiply(
                App.Placement(App.Vector(), rot, c0))
        else:
            pl = App.Placement(c - c0, App.Rotation())
        out.append(pl)
    return out


# ------------------------------------------------------------------ sketch / table

def to_points(points, ref, skip=()):
    """Moves taking the seed's reference point to each point (one at the
    reference is the seed itself)."""
    out = []
    for k, p in enumerate(points, 1):
        if (p - ref).Length < 1e-6 or k in skip:
            continue
        out.append(App.Placement(p - ref, App.Rotation()))
    if not out:
        raise topo.GeometryError("There are no points for instances besides the seed.")
    return out


# ------------------------------------------------------------------ fill

PERFORATION, CONCENTRIC, SQUARE, POLYGON = "Perforation", "Circular", "Square", "Polygon"
LAYOUTS = [PERFORATION, CONCENTRIC, SQUARE, POLYGON]


def _inside(face, p, clearance):
    """Whether p is on the face, at least ``clearance`` from its edges."""
    if not face.isInside(p, 1e-6, True):
        return False
    if clearance <= 0:
        return True
    v = Part.Vertex(p)
    return min(w.distToShape(v)[0] for w in face.Wires) >= clearance - 1e-9


def fill_points(face, origin, direction, layout, spacing, stagger=60.0, loop_spacing=None,
                sides=6, clearance=0.0):
    """Points filling a flat face, starting at ``origin`` (on the face)."""
    if face.Surface.TypeId != "Part::GeomPlane":
        raise topo.GeometryError("A fill pattern needs a flat boundary.")
    if spacing <= 0:
        raise topo.GeometryError("The instance spacing must be greater than zero.")
    n = face.normalAt(0, 0)
    d = direction - n * direction.dot(n)
    if d.Length < 1e-9:
        d = App.Vector(1, 0, 0) - n * n.x
        if d.Length < 1e-9:
            d = App.Vector(0, 1, 0)
    d.normalize()
    e = n.cross(d)
    origin = origin - n * (origin - face.CenterOfMass).dot(n)
    size = face.BoundBox.DiagonalLength
    reach = int(size / spacing) + 2
    pts = []
    import math
    if layout in (PERFORATION, SQUARE):
        if layout == SQUARE:
            row, shift = spacing, 0.0
        else:
            a = math.radians(stagger)
            row, shift = spacing * math.sin(a), spacing * math.cos(a)
        rows = int(size / max(row, 1e-9)) + 2
        for j in range(-rows, rows + 1):
            off = (shift * j) % spacing if layout == PERFORATION else 0.0
            for i in range(-reach, reach + 1):
                pts.append(origin + d * (i * spacing + off) + e * (j * row))
    else:
        ls = loop_spacing or spacing
        pts.append(origin)
        loops = int(size / ls) + 2
        for k in range(1, loops + 1):
            r = k * ls
            if layout == CONCENTRIC:
                m = max(int(round(2 * math.pi * r / spacing)), 1)
                for q in range(m):
                    a = 2 * math.pi * q / m
                    pts.append(origin + d * (r * math.cos(a)) + e * (r * math.sin(a)))
            else:
                corners = [origin + d * (r * math.cos(2 * math.pi * q / sides)) +
                           e * (r * math.sin(2 * math.pi * q / sides)) for q in range(sides)]
                for q in range(sides):
                    a, b = corners[q], corners[(q + 1) % sides]
                    m = max(int(round((b - a).Length / spacing)), 1)
                    for t in range(m):
                        pts.append(a + (b - a) * (t / float(m)))
    out = []
    for p in pts:
        if _inside(face, p, clearance) and all((p - q).Length > 1e-6 for q in out):
            out.append(p)
    out.sort(key=lambda p: ((p - origin).Length, p.x, p.y, p.z))
    return out


def seed_cut(shape, size, sides, point, normal, direction, depth):
    """A cut tool of a simple shape (SolidWorks' Create seed cut), at ``point`` on
    a face with ``normal`` (out of the body), going ``depth`` in."""
    import math
    d = direction - normal * direction.dot(normal)
    d.normalize()
    e = normal.cross(d)
    r = size / 2.0
    if shape == "Circle":
        w = Part.Wire(Part.makeCircle(r, point, normal))
    else:
        if shape == "Square":
            corners = [(r, r), (-r, r), (-r, -r), (r, -r)]
        elif shape == "Diamond":
            corners = [(r, 0), (0, r), (-r, 0), (0, -r)]
        else:
            corners = [(r * math.cos(2 * math.pi * k / sides), r * math.sin(2 * math.pi * k / sides))
                       for k in range(sides)]
        pts = [point + d * x + e * y for x, y in corners]
        w = Part.makePolygon(pts + [pts[0]])
    f = Part.Face(w)
    f.translate(normal * 1e-3 * max(size, 1))
    return f.extrude(-normal * (depth + 2e-3 * max(size, 1)))


SEED_SHAPES = ["None", "Circle", "Square", "Diamond", "Polygon"]


def _move(shape, how, tag):
    if isinstance(how, App.Placement):
        return topo.transformed(shape, how, tag)
    point, normal = how             # a mirror
    try:
        return topo.tagged(shape, tag).mirror(point, normal)
    except Exception as e:
        raise topo.GeometryError("Mirror failed: {}".format(e))


def repeat(base, seeds, body_ids, moves, feature, tag, alloc, merge_bodies=False):
    """Apply the pattern. ``moves``: Placements, or (point, normal) for a mirror.
    Returns (Result, preview)."""
    if not seeds and not body_ids:
        raise topo.GeometryError("Pick features, faces or bodies to pattern.")
    out = base
    res = common.Result(out)
    shown = []
    for s in seeds:
        if s.tool is None or s.tool.isNull():
            raise topo.GeometryError("{} has no result to repeat (fix it first).".format(s.label))
        tools = [_move(s.tool, m, tag) for m in moves]
        comp = topo.compound(tools, tag)
        shown.extend(tools)
        scope = s.scope or common.Scope()
        if s.mode in ("Add", "Surface"):
            r = common.apply_add(out, comp, feature, tag, s.merge and s.mode == "Add", scope,
                                 alloc)
        else:
            r = common.apply_cut(out, comp, feature, tag, scope, common.Keep(), alloc)
            if not r.touched:
                res.warnings.append("The repeated {} cuts nothing.".format(s.label))
        out = r.bodies
        res.touched.extend(r.touched)
        res.created.extend(r.created)
    for bid in body_ids:
        b = out.get(bid)
        if b is None:
            raise topo.GeometryError("A body picked to pattern no longer exists. Re-pick it.")
        copies = [_move(b.shape, m, tag) for m in moves]
        shown.extend(copies)
        if merge_bodies and b.kind == SOLID:
            r = common.apply_add(out, topo.compound(copies, tag), feature, tag, True,
                                 common.Scope(False, [bid]), alloc)
            out = r.bodies
            res.touched.extend(r.touched)
            continue
        out = out.copy()
        ids = alloc.take(copies, prefix="{}:{}".format(feature, bid))
        prev = bid
        for nid, s in zip(ids, copies):
            out.insert_after(prev, nid, s, feature)
            res.created.append(nid)
            prev = nid
    res.bodies = out
    return res, (topo.compound(shown, tag) if shown else None)
