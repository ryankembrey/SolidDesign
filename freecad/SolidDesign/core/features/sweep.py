# SPDX-License-Identifier: LGPL-2.1-or-later
"""Sweep and Loft (Add | Cut): SolidWorks' Swept/Lofted Boss/Base and Cut.

An open profile without Thin Feature makes a surface body (spec 3.4).

A plain sweep is OpenCASCADE's pipe shell. Twist, guide curves and path
tangency place copies of the profile along the path ("stations") and skin
through them (core/skin.py). A solid profile sweeps a tool body of revolution.
"""

import math

import FreeCAD as App
import Part

from .. import skin, topo
from ..bodies import SOLID
from . import common, sheet
from .profile import thin_faces

SKETCH_PROFILE = "Sketch Profile"
CIRCULAR_PROFILE = "Circular Profile"
SOLID_PROFILE = "Solid Profile"
PROFILE_TYPES = [SKETCH_PROFILE, CIRCULAR_PROFILE, SOLID_PROFILE]
FOLLOW_PATH = "Follow Path"
KEEP_NORMAL = "Keep Normal Constant"
ORIENTATIONS = [FOLLOW_PATH, KEEP_NORMAL]
NO_TWIST = "None"
TWIST_VALUE = "Specify Twist Value"
FOLLOW_GUIDE = "Follow Path and 1st Guide Curve"
TWISTS = [NO_TWIST, TWIST_VALUE, FOLLOW_GUIDE]
DEGREES = "Degrees"
TURNS = "Turns"
TWIST_UNITS = [DEGREES, TURNS]
NO_TANGENCY = "None"
PATH_TANGENT = "Path Tangent"
SWEEP_TANGENCY = [NO_TANGENCY, PATH_TANGENT]
NORMAL_TO_PROFILE = "Normal To Profile"
DIRECTION_VECTOR = "Direction Vector"
LOFT_TANGENCY = [NO_TANGENCY, NORMAL_TO_PROFILE, DIRECTION_VECTOR]
STATIONS = 48


class SweepParams(object):
    def __init__(self):
        self.mode = "Add"
        self.faces = []
        self.open_wires = []
        self.path = None            # Part.Wire
        self.axis = None            # (start, end): a helix's axis, to turn the profile about
        self.profile_type = SKETCH_PROFILE
        self.diameter = 5.0
        self.orientation = FOLLOW_PATH
        self.twist = NO_TWIST
        self.twist_angle = 0.0      # degrees, total along the path
        self.guides = []            # skin.Guide
        self.start_tangent = False
        self.end_tangent = False
        self.tool_body = None       # a solid (Solid Profile)
        self.thin = None
        self.merge = True
        self.scope = common.Scope()
        self.keep = common.Keep()
        self.flip = False
        self.feature = "Sweep"
        self.tag = 1
        self.alloc = None


class LoftParams(object):
    def __init__(self):
        self.mode = "Add"
        self.sections = []          # per profile: a Part.Face (with holes), a wire, or a vertex
        self.closed = False
        self.guides = []            # skin.Guide
        self.influence = skin.TO_NEXT_EDGE
        self.start = NO_TANGENCY    # LOFT_TANGENCY
        self.end = NO_TANGENCY
        self.start_dir = None       # App.Vector, for Direction Vector
        self.end_dir = None
        self.start_length = 1.0
        self.end_length = 1.0
        self.start_draft = 0.0      # degrees, outward
        self.end_draft = 0.0
        self.merge = True
        self.scope = common.Scope()
        self.keep = common.Keep()
        self.flip = False
        self.feature = "Loft"
        self.tag = 1
        self.alloc = None


def path_wire(edges):
    """One connected wire from path edges, in order."""
    if not edges:
        raise topo.GeometryError("Pick a path: a sketch, or connected edges.")
    try:
        groups = Part.sortEdges(list(edges))
    except Exception:
        groups = [list(edges)]
    if len(groups) != 1:
        raise topo.GeometryError("The path must be one connected chain of edges "
                                 "(it has {} pieces).".format(len(groups)))
    return Part.Wire(groups[0])


def _sweep_wire(path, wire, orientation, solid, tag, axis=None):
    normal = None
    if orientation == KEEP_NORMAL:
        normal = Part.Face(wire).normalAt(0, 0) if wire.isClosed() else \
            wire.Edges[0].tangentAt(wire.Edges[0].FirstParameter)
    try:
        s = topo.sweep(path, wire, tag, solid, normal, axis if normal is None else None)
    except topo.GeometryError as e:
        raise topo.GeometryError("{}. Check that the profile sits at the start of the path and "
                                 "the path has no corner the profile can't turn.".format(e))
    if solid and not s.Solids:
        raise topo.GeometryError("The sweep made no solid.")
    return s


def _circle_at_start(path, diameter):
    e = path.OrderedEdges[0] if hasattr(path, "OrderedEdges") else path.Edges[0]
    p = path.OrderedVertexes[0].Point if hasattr(path, "OrderedVertexes") else e.Vertexes[0].Point
    t = e.tangentAt(e.FirstParameter)
    if (e.valueAt(e.FirstParameter) - p).Length > 1e-7:
        t = -e.tangentAt(e.LastParameter)
    return Part.Face(Part.Wire(Part.makeCircle(diameter / 2.0, p, t)))


def sweep_tool(p):
    if p.path is None:
        raise topo.GeometryError("Pick a path.")
    surface = p.mode == sheet.SURFACE
    if p.profile_type == SOLID_PROFILE:
        if surface:
            raise topo.GeometryError("A swept surface needs a sketch or circular profile.")
        return solid_sweep(p)
    if p.profile_type == CIRCULAR_PROFILE:
        if p.diameter <= 0:
            raise topo.GeometryError("The diameter must be greater than zero.")
        faces, open_wires = [_circle_at_start(p.path, p.diameter)], []
    else:
        faces, open_wires = list(p.faces), list(p.open_wires)
    if p.thin is not None and not surface:
        faces, open_wires = thin_faces(faces, open_wires, p.thin, p.tag), []
    if not faces and not open_wires:
        raise topo.GeometryError("Pick a profile sketch, or use a Circular Profile.")
    if stations_needed(p):
        anchor = faces[0] if faces else open_wires[0]
        moves = stations(p, anchor)

        def along(w, solid):
            return _skin_wire(p, w, moves, solid)
    else:
        def along(w, solid):
            return _sweep_wire(p.path, w, p.orientation, solid, p.tag, p.axis)
    if surface:
        swept = [along(w, False) for w in sheet.wires_of(faces, open_wires)]
        return sheet.shells([f for x in swept for f in x.Faces], p.tag)
    parts = []
    for f in faces:
        outer = along(f.OuterWire, True)
        holes = [along(w, True) for w in f.Wires if not w.isSame(f.OuterWire)]
        parts.append(topo.cut(outer, holes, p.tag) if holes else outer)
    surfaces = [along(w, False) for w in open_wires]
    if parts and surfaces:
        raise topo.GeometryError("The profile has both closed and open contours. Pick regions "
                                 "in Selected Contours.")
    shapes = parts or surfaces
    return shapes[0] if len(shapes) == 1 else topo.compound(shapes, p.tag)


# ------------------------------------------------------------------ stations

def stations_needed(p):
    return bool(p.guides) or p.twist != NO_TWIST or p.start_tangent or p.end_tangent


def _frames(p, path, fs):
    """Origin and axes (t, r, b) along the path at fractions ``fs``: rotation
    minimising (as Follow Path), fixed (Keep Normal Constant), or turning about
    a helix's axis."""
    xs = [path.at(f) for f in fs]
    ts = [path.tangent_at(f) for f in fs]
    if p.orientation == KEEP_NORMAL:
        t0 = ts[0]
        r0 = _perp(t0)
        return [(x, t0, r0, t0.cross(r0)) for x in xs]
    if p.axis is not None:
        a0, a1 = p.axis
        d = (a1 - a0).normalize()
        out = []
        for x, t in zip(xs, ts):
            rel = x - a0
            r = rel - d * rel.dot(d)
            r = r - t * r.dot(t)
            r = r.normalize() if r.Length > 1e-12 else _perp(t)
            out.append((x, t, r, t.cross(r)))
        return out
    r = _perp(ts[0])
    out = [(xs[0], ts[0], r, ts[0].cross(r))]
    for i in range(len(xs) - 1):
        v1 = xs[i + 1] - xs[i]
        c1 = v1.dot(v1)
        if c1 < 1e-18:
            out.append((xs[i + 1], ts[i + 1], r, ts[i + 1].cross(r)))
            continue
        rl = r - v1 * (2.0 / c1 * v1.dot(r))
        tl = ts[i] - v1 * (2.0 / c1 * v1.dot(ts[i]))
        v2 = ts[i + 1] - tl
        c2 = v2.dot(v2)
        r = rl if c2 < 1e-18 else rl - v2 * (2.0 / c2 * v2.dot(rl))
        r = (r - ts[i + 1] * r.dot(ts[i + 1])).normalize()
        out.append((xs[i + 1], ts[i + 1], r, ts[i + 1].cross(r)))
    return out


def _perp(t):
    a = App.Vector(0, 0, 1) if abs(t.z) < 0.9 else App.Vector(1, 0, 0)
    return t.cross(a).normalize()


def _matrix(o, x, y, z):
    m = App.Matrix(x.x, y.x, z.x, o.x,
                   x.y, y.y, z.y, o.y,
                   x.z, y.z, z.z, o.z,
                   0, 0, 0, 1)
    return m


def _fit(g0, gi, follow):
    """A 2D map (a, b, c, d, e, f): (x, y) -> (a x + b y + e, c x + d y + f) taking
    the guide points at the start to those at the station."""
    n = len(g0)
    if n == 1:
        z, w = complex(*g0[0]), complex(*gi[0])
        if abs(z) < 1e-9:
            raise topo.GeometryError("The guide curve passes through the path; it can't "
                                     "scale the profile.")
        k = w / z if follow else abs(w) / abs(z)
        return (k.real if follow else k, -k.imag if follow else 0.0,
                k.imag if follow else 0.0, k.real if follow else k, 0.0, 0.0)
    if n == 2:
        z1, z2 = complex(*g0[0]), complex(*g0[1])
        w1, w2 = complex(*gi[0]), complex(*gi[1])
        if abs(z2 - z1) < 1e-9:
            raise topo.GeometryError("Two guide curves meet the profile at the same point.")
        a = (w2 - w1) / (z2 - z1)
        b = w1 - a * z1
        return (a.real, -a.imag, a.imag, a.real, b.real, b.imag)
    import numpy
    A = numpy.array([[x, y, 1.0] for x, y in g0])
    sol_x = numpy.linalg.lstsq(A, numpy.array([x for x, _y in gi]), rcond=None)[0]
    sol_y = numpy.linalg.lstsq(A, numpy.array([y for _x, y in gi]), rcond=None)[0]
    return (sol_x[0], sol_x[1], sol_y[0], sol_y[1], sol_x[2], sol_y[2])


def _cross(guide, o, n, near):
    """Where a guide curve crosses the plane through ``o`` with normal ``n``."""
    sec = guide.sec
    N = 240
    fs = [k / float(N) for k in range(N + 1)]
    ds = [(sec.at(f) - o).dot(n) for f in fs]
    roots = []
    for k in range(N):
        a, b = ds[k], ds[k + 1]
        if a == 0:
            roots.append(fs[k])
        elif a * b < 0:
            lo, hi, dlo = fs[k], fs[k + 1], a
            for _i in range(50):
                mid = 0.5 * (lo + hi)
                dm = (sec.at(mid) - o).dot(n)
                if dm * dlo <= 0:
                    hi = mid
                else:
                    lo, dlo = mid, dm
            roots.append(0.5 * (lo + hi))
    if abs(ds[-1]) < 1e-9:
        roots.append(1.0)
    if not roots:
        return None
    pts = [sec.at(f) for f in roots]
    return min(pts, key=lambda q: (q - near).Length)


def stations(p, anchor):
    """The matrices placing the profile at each station along the path (the
    first is the identity) and the stations' path fractions."""
    path = skin.Section(p.path)
    if path.corners():
        raise topo.GeometryError("Twist, guide curves and path tangency need a smooth path "
                                 "(it has a sharp corner).")
    n_st = max(STATIONS, 12 * len(path.curves))
    fs = [k / float(n_st) for k in range(n_st + 1)]
    frames = _frames(p, path, fs)
    x0, t0, r0, b0 = frames[0]
    F0inv = _matrix(x0, t0, r0, b0).inverse()
    mats = [_matrix(x, t, r, b).multiply(F0inv) for x, t, r, b in frames]
    if p.guides:
        if p.twist == TWIST_VALUE:
            raise topo.GeometryError("With guide curves the guides set the twist; choose "
                                     "None or Follow Path and 1st Guide Curve.")
        mats = _guided(p, anchor, frames, mats)
    elif p.twist == TWIST_VALUE and abs(p.twist_angle) > 1e-9:
        out = []
        for (x, t, _r, _b), m, f in zip(frames, mats, fs):
            rot = App.Placement(App.Vector(), App.Rotation(t, p.twist_angle * f), x).toMatrix()
            out.append(rot.multiply(m))
        mats = out
    elif p.twist == FOLLOW_GUIDE:
        raise topo.GeometryError("Follow Path and 1st Guide Curve needs a guide curve.")
    return mats, fs


def _guided(p, anchor, frames, mats):
    try:
        plane = anchor.Surface if anchor.ShapeType == "Face" else Part.Face(anchor).Surface
        n = App.Vector(plane.Axis)
    except Exception:
        n = frames[0][1]
    x0 = frames[0][0]
    c = anchor.CenterOfMass if anchor.ShapeType == "Face" else anchor.BoundBox.Center
    o = x0 - n * (x0 - c).dot(n)                    # the path's start, on the profile plane
    e1 = frames[0][2] - n * frames[0][2].dot(n)
    if e1.Length < 1e-9:
        e1 = _perp(n)
    e1.normalize()
    e2 = n.cross(e1)
    basis = _matrix(o, e1, e2, n)
    binv = basis.inverse()
    prof = anchor.OuterWire if anchor.ShapeType == "Face" else anchor
    g0, prev = [], []
    for g in p.guides:
        q = _cross(g, o, n, o)
        if q is None or prof.distToShape(Part.Vertex(q))[0] > 1e-4 * max(prof.BoundBox
                                                                          .DiagonalLength, 1):
            raise topo.GeometryError("{} doesn't touch the profile. A guide curve must cross "
                                     "the profile's plane on the profile.".format(g.label))
        g0.append(((q - o).dot(e1), (q - o).dot(e2)))
        prev.append(q)
    follow = p.twist == FOLLOW_GUIDE
    out = []
    for i, m in enumerate(mats):
        oi = m.multVec(o)
        ni = m.multVec(o + n) - oi
        e1i = m.multVec(o + e1) - oi
        e2i = m.multVec(o + e2) - oi
        gi = []
        for k, g in enumerate(p.guides):
            q = _cross(g, oi, ni, prev[k])
            if q is None:
                raise topo.GeometryError("{} ends before the path does; make it as long as "
                                         "the path.".format(g.label))
            prev[k] = q
            gi.append(((q - oi).dot(e1i), (q - oi).dot(e2i)))
        a, b, c2, d, e, f = _fit(g0, gi, follow)
        local = App.Matrix(a, b, 0, e,
                           c2, d, 0, f,
                           0, 0, 1, 0,
                           0, 0, 0, 1)
        out.append(m.multiply(basis.multiply(local.multiply(binv))))
    return out


def _skin_wire(p, wire, moves, solid):
    mats, fs = moves
    base = skin.oriented_curves(wire)
    rows = [skin.transformed(base, m) for m in mats]
    length = skin.Section(p.path).total
    start = end = None
    if p.start_tangent:
        t0 = skin.Section(p.path).tangent_at(0.0) * length
        start = (lambda _pt: t0)
    if p.end_tangent:
        t1 = skin.Section(p.path).tangent_at(1.0) * length
        end = (lambda _pt: t1)
    closed = wire.isClosed()
    try:
        return skin.build(rows, False, solid and closed, start, end, params=fs, tag=p.tag)
    except topo.GeometryError as e:
        raise topo.GeometryError("The sweep failed: {}".format(e))


# ------------------------------------------------------------------ solid profile

def _revolution_axis(tool):
    """(point, direction) of a body of revolution, or a clear error."""
    axes, normals, centres = [], [], []
    for f in tool.Faces:
        s = f.Surface
        t = s.TypeId
        if t in ("Part::GeomCylinder", "Part::GeomCone"):
            axes.append((App.Vector(s.Center) if t == "Part::GeomCylinder" else
                         App.Vector(s.Apex), App.Vector(s.Axis)))
        elif t == "Part::GeomToroid":
            axes.append((App.Vector(s.Center), App.Vector(s.Axis)))
        elif t == "Part::GeomSurfaceOfRevolution":
            axes.append((App.Vector(s.Location), App.Vector(s.Direction)))
        elif t == "Part::GeomPlane":
            normals.append(App.Vector(s.Axis))
        elif t == "Part::GeomSphere":
            centres.append(App.Vector(s.Center))
        else:
            raise topo.GeometryError("The tool body must be a body of revolution (a revolve, "
                                     "or a cylinder) made of lines and arcs.")
    if not axes:
        if centres:
            return centres[0], None                 # a ball: any axis through its centre
        raise topo.GeometryError("The tool body must be a body of revolution (a revolve, or "
                                 "a cylinder).")
    p0, d0 = axes[0]
    d0 = d0.normalize()
    for p1, d1 in axes[1:]:
        rel = p1 - p0
        if d1.normalize().cross(d0).Length > 1e-6 or (rel - d0 * rel.dot(d0)).Length > 1e-6:
            raise topo.GeometryError("The tool body's faces don't share one axis; it must be a "
                                     "body of revolution.")
    for nn in normals:
        if nn.normalize().cross(d0).Length > 1e-6:
            raise topo.GeometryError("The tool body has a flat face that isn't square to its "
                                     "axis; it must be a body of revolution.")
    for c in centres:
        rel = c - p0
        if (rel - d0 * rel.dot(d0)).Length > 1e-6:
            raise topo.GeometryError("The tool body's ball isn't on its axis.")
    return p0, d0


def solid_sweep(p):
    """Sweep a tool body of revolution along the path (SolidWorks' Solid Profile):
    the section through the tool's axis, square to the motion, swept along the
    path, plus the tool at both ends. Exact while the path runs square to the
    tool's axis (a cutter along a groove, round a cylinder)."""
    tool = p.tool_body
    if tool is None or not tool.Solids:
        raise topo.GeometryError("Pick the tool body: a solid body of revolution.")
    path = skin.Section(p.path)
    if path.corners():
        raise topo.GeometryError("A solid profile needs a smooth path (it has a sharp corner).")
    c, a = _revolution_axis(tool)
    t0 = path.tangent_at(0.0)
    if a is None:
        a = _perp(t0)
    m = t0 - a * t0.dot(a)
    if m.Length < 1e-6:
        raise topo.GeometryError("The path starts along the tool's axis; a solid profile "
                                 "sweep needs it to run across the axis.")
    m.normalize()
    big = tool.BoundBox.DiagonalLength * 4 + 10
    cut = Part.Plane(c, m).toShape(-big, big, -big, big)
    sec = tool.common(cut)
    if not sec.Faces:
        raise topo.GeometryError("The tool body doesn't reach the path's start plane.")
    face = sec.Faces[0] if len(sec.Faces) == 1 else sec.Faces[0].fuse(sec.Faces[1:]) \
        .removeSplitter().Faces[0]
    swept = _sweep_wire(p.path, face.OuterWire, p.orientation, True, p.tag, p.axis)
    # Where the tool ends up: sweep a little marker (its axis and the motion).
    marker = Part.Wire([Part.LineSegment(c + a, c).toShape(),
                        Part.LineSegment(c, c + m).toShape()])
    normal = None
    if p.orientation == KEEP_NORMAL:
        normal = face.normalAt(0, 0)
    last = topo.sweep(p.path, marker, p.tag, False, normal,
                      p.axis if normal is None else None, ends=True)
    edges = last.Edges
    corner = None
    if len(edges) == 2:
        for v1 in edges[0].Vertexes:
            for v2 in edges[1].Vertexes:
                if (v1.Point - v2.Point).Length < 1e-7:
                    corner = v1.Point
    if corner is None:
        raise topo.GeometryError("Couldn't place the tool at the path's end.")
    ends = []
    for e in edges:
        far = [v.Point for v in e.Vertexes if (v.Point - corner).Length > 1e-7]
        ends.append(far[0] if far else corner)
    a1, m1 = ends[0] - corner, ends[1] - corner
    if abs(a1.Length - 1) > 1e-3:
        a1, m1 = m1, a1
    a1.normalize()
    m1 = (m1 - a1 * m1.dot(a1)).normalize()
    R0 = _matrix(App.Vector(), a, m, a.cross(m))
    R1 = _matrix(App.Vector(), a1, m1, a1.cross(m1))
    rot = R1.multiply(R0.inverse())
    move = App.Matrix(rot)
    shift = corner - rot.multVec(c)
    move.move(shift)
    end_tool = tool.copy()
    end_tool.transformShape(move)
    out = topo.refine(topo.fuse(swept, [tool, end_tool], p.tag), p.tag)
    if not out.isValid():
        out.fix(1e-7, 1e-7, 1e-7)
    if not out.isValid():
        raise topo.GeometryError("The solid profile sweep made an invalid solid. Check that "
                                 "the path is smooth and starts in the tool body.")
    return out


def loft_tool(p):
    if p.guides or p.start != NO_TANGENCY or p.end != NO_TANGENCY:
        return _skinned_loft(p)
    secs = list(p.sections)
    if len(secs) < 2:
        raise topo.GeometryError("Pick at least two profiles, in order.")
    faces = [s for s in secs if s.ShapeType == "Face"]
    holes = [len(f.Wires) - 1 for f in faces]
    if len(set(holes)) > 1:
        raise topo.GeometryError("Every profile must have the same number of holes "
                                 "({}).".format(", ".join(str(h) for h in holes)))
    outers = []
    for s in secs:
        if s.ShapeType == "Face":
            outers.append(s.OuterWire)
        elif s.ShapeType == "Vertex":
            outers.append(s)
        else:
            outers.append(s)
    surface = p.mode == sheet.SURFACE
    solid = all(o.ShapeType == "Vertex" or o.isClosed() for o in outers) and not surface
    body = topo.loft(outers, p.tag, solid=solid, ruled=False, closed=p.closed)
    if solid and not body.Solids:
        raise topo.GeometryError("The loft made no solid. Check the profiles' order and "
                                 "their start points.")
    n = holes[0] if holes else 0
    if n and (solid or surface):
        cuts = []
        for k in range(n):
            ws = []
            for f in faces:
                inner = [w for w in f.Wires if not w.isSame(f.OuterWire)]
                inner.sort(key=lambda w: (round(w.BoundBox.Center.x, 6),
                                          round(w.BoundBox.Center.y, 6)))
                ws.append(inner[k])
            cuts.append(topo.loft(ws, p.tag, solid=not surface, ruled=False,
                                  closed=p.closed))
        if surface:     # the holes' walls are surfaces of their own
            return sheet.shells(body.Faces + [f for c in cuts for f in c.Faces], p.tag)
        body = topo.cut(body, cuts, p.tag)
    if surface:
        return sheet.shells(body.Faces, p.tag)
    return body


def _skinned_loft(p):
    secs = list(p.sections)
    if len(secs) < 2:
        raise topo.GeometryError("Pick at least two profiles, in order.")
    if p.closed and (p.start != NO_TANGENCY or p.end != NO_TANGENCY):
        raise topo.GeometryError("A closed loft has no start or end to constrain.")
    if p.closed and p.guides:
        raise topo.GeometryError("Guide curves work on open lofts in this version.")
    faces = [s for s in secs if s.ShapeType == "Face"]
    holes = [len(f.Wires) - 1 for f in faces]
    if len(set(holes)) > 1:
        raise topo.GeometryError("Every profile must have the same number of holes "
                                 "({}).".format(", ".join(str(h) for h in holes)))
    outer = [s.OuterWire if s.ShapeType == "Face" else s for s in secs]
    body = _skin_through(p, outer, p.guides)
    n = holes[0] if holes else 0
    if n:
        cuts = []
        for k in range(n):
            ws = []
            for f in faces:
                inner = [w for w in f.Wires if not w.isSame(f.OuterWire)]
                inner.sort(key=lambda w: (round(w.BoundBox.Center.x, 6),
                                          round(w.BoundBox.Center.y, 6)))
                ws.append(inner[k])
            cuts.append(_skin_through(p, ws, []))
        if p.mode == sheet.SURFACE:
            return sheet.shells(body.Faces + [f for c in cuts for f in c.Faces], p.tag)
        body = topo.cut(body, cuts, p.tag)
    if p.mode == sheet.SURFACE:
        return sheet.shells(body.Faces, p.tag)
    return body


def _skin_through(p, shapes, guides):
    sections = [skin.Section(s) for s in shapes]
    skin.align(sections)
    solid = all(s.is_point or s.closed for s in sections) and p.mode != sheet.SURFACE

    def constraint(kind, k, length, draft, direction):
        if kind == NO_TANGENCY:
            return None
        s = sections[k]
        if s.is_point:
            raise topo.GeometryError("A start or end constraint needs a profile, not a point.")
        nb = sections[1 if k == 0 else -2]
        towards = nb.centre() - s.centre()
        if kind == DIRECTION_VECTOR:
            if direction is None:
                raise topo.GeometryError("Pick the direction vector for the {} constraint."
                                         .format("start" if k == 0 else "end"))
            d = App.Vector(direction).normalize()
        else:
            try:
                d = Part.Face(s.wire()).normalAt(0, 0)
            except Exception:
                raise topo.GeometryError("Normal To Profile needs a flat profile.")
        if d.dot(towards) < 0:
            d = -d
        if k != 0:
            d = -d                                  # leaving the end, the loft travels along
        mag = length * max(towards.Length, 1e-6) * (len(sections) - 1)
        centre = s.centre()
        tan_draft = math.tan(math.radians(draft))

        def f(pt):
            if abs(tan_draft) < 1e-12:
                return d * mag
            out = pt - centre
            out = out - d * out.dot(d)
            if out.Length > 1e-12:
                out.normalize()
            return (d + out * (tan_draft if k == 0 else -tan_draft)) * mag
        return f
    start = constraint(p.start, 0, p.start_length, p.start_draft, p.start_dir)
    end = constraint(p.end, len(sections) - 1, p.end_length, p.end_draft, p.end_dir)
    if guides:
        return skin.guided_loft(sections, guides, p.influence, solid, start, end, tag=p.tag)
    return skin.loft(sections, p.closed, solid, start, end, tag=p.tag)


def compute(p, tool):
    """Apply a sweep or loft tool to the body set (shared Add | Cut rules)."""
    base = p.base
    if p.mode == sheet.SURFACE:
        if tool.Solids:
            tool = sheet.shell_of(tool, p.tag)
        res = common.apply_add(base, tool, p.feature, p.tag, False, p.scope, p.alloc)
        return res, tool
    if p.mode == "Add":
        res = common.apply_add(base, tool, p.feature, p.tag, p.merge, p.scope, p.alloc)
        return res, tool
    if not tool.Solids:
        raise topo.GeometryError("A cut needs a closed profile (an open one makes a surface).")
    if not base.ids(SOLID) and not base.ids():
        raise topo.GeometryError("There is no body to cut. Switch to Add, or make a body first.")
    res = common.apply_cut(base, tool, p.feature, p.tag, p.scope, p.keep, p.alloc, p.flip)
    if not res.touched:
        raise topo.GeometryError("The cut doesn't touch any body in its scope.")
    return res, common.removed_material(tool, base, p.scope, p.tag)

