# SPDX-License-Identifier: LGPL-2.1-or-later
"""What ``sel=`` picks: the command line's selection grammar.

A selection is parts separated by commas; each part is a source, then any
number of filters after colons:

    sel=jk                  the element labelled jk in the view
    sel=jk]]  sel=jk[       ...stepped to a neighbour (] clockwise, [ back), on screen
    sel=jk+                 ...stepped along tangent edges
    sel=jk,loop             a word after an edge: tangent, loop, otherloop, chain
    sel=new                 what the last feature made (of the kinds the tool takes)
    sel=last.top            faces of the last feature: top (its far end), caps, sides
    sel=@a                  register a (sel=jk,dl >a fills it)
    sel=edges               every edge of the bodies shown (faces, vertices; * for all)
    sel=edges:circular      ...that are circles or arcs
    sel=edges:r<5:top       ...of radius under 5, the highest of them
    sel=jk:edges            the edges of face jk
    sel=faces:par:z         faces lying flat (normal along Z); perp:z for walls

Everything resolves to (document, body view, element) keys, the same as a
click in the 3D view gives. No Qt here.
"""

import math
import re

import FreeCAD as App

from ..core import topo
from . import pick_tools

KINDS = {"edges": "Edge", "edge": "Edge", "e": "Edge", "faces": "Face", "face": "Face",
         "f": "Face", "vertices": "Vertex", "vertex": "Vertex", "v": "Vertex",
         "points": "Vertex"}
#: Sources are whole words, each with a letter labels never use (see hints.ALPHABET),
#: so none is ever read as a label; one-letter kinds are filters only (jk:e).
SOURCE_KINDS = {k: v for k, v in KINDS.items() if len(k) > 1}
LAST_FACES = ("last.top", "last.caps", "last.sides", "last")
TYPES = {
    "circular": ("Edge", ("Circle",)), "arc": ("Edge", ("Circle",)),
    "linear": ("Edge", ("Line", "LineSegment")), "straight": ("Edge", ("Line", "LineSegment")),
    "curved": ("Edge", None),
    "planar": ("Face", ("Plane",)), "flat": ("Face", ("Plane",)),
    "cylindrical": ("Face", ("Cylinder",)), "conical": ("Face", ("Cone",)),
    "spherical": ("Face", ("Sphere",)), "toroidal": ("Face", ("Toroid",)),
}
AXES = {"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0),
        "+z": (0, 0, 1), "-z": (0, 0, -1), "x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1),
        "top": (0, 0, 1), "bottom": (0, 0, -1), "right": (1, 0, 0), "left": (-1, 0, 0),
        "back": (0, 1, 0), "front": (0, -1, 0)}
EXTREMES = ("top", "bottom", "front", "back", "left", "right", "+x", "-x", "+y", "-y", "+z",
            "-z")
MEASURES = {"r": "radius", "len": "length", "length": "length", "area": "area",
            "x": "x", "y": "y", "z": "z", "d": "diameter"}
COMPARE = re.compile(r"^(r|d|len|length|area|x|y|z)(<=|>=|<|>|=)(-?[0-9.]+)$")
MOTIONS = "[]+"
TOL = 1e-6
NEAR = 1e-3                     # mm: "=" in a comparison, and ties at an extreme

#: The origin's planes by a word (a filter after a colon, a plane as a source).
ORIGIN_PLANES = {"front": "Front Plane", "top": "Top Plane", "right": "Right Plane"}

#: For completion and help: (what to type, what it is).
SOURCES = [("front", "the origin's Front Plane (top, right)"),("new", "what the last feature made"),
           ("last.top", "the far end of the last feature"),
           ("last.caps", "the end faces of the last feature"),
           ("last.sides", "the side faces of the last feature"),
           ("last", "every face the last feature made"),
           ("edges", "every edge of the bodies shown"),
           ("faces", "every face of the bodies shown"),
           ("vertices", "every vertex of the bodies shown"),
           ("*", "every face and edge of the bodies shown")]
FILTERS = [("circular", "circles and arcs"), ("linear", "straight edges"),
           ("curved", "edges that aren't straight"), ("concave", "inside corners"),
           ("convex", "outside corners"), ("planar", "flat faces"),
           ("cylindrical", "cylinders"), ("conical", "cones"), ("spherical", "spheres"),
           ("top", "the highest"), ("bottom", "the lowest"), ("front", "the most -Y"),
           ("back", "the most +Y"), ("left", "the most -X"), ("right", "the most +X"),
           ("largest", "the biggest"), ("smallest", "the smallest"),
           ("nearest", "the nearest the pointer"),
           ("par:", "parallel to an axis: par:z"), ("perp:", "square to an axis: perp:z"),
           ("edges", "the edges of what's picked"), ("faces", "the faces of what's picked"),
           ("vertices", "the vertices of what's picked"),
           ("r<", "radius under: r<5"), ("len>", "length over: len>10"),
           ("area>", "area over: area>100"), ("z=", "at a height: z=10")]


class Context(object):
    """What a selection is resolved against."""

    def __init__(self, doc, cmd=None, codes=None, point=None, view=None, kinds=None):
        self.doc = doc
        self.cmd = cmd
        self.codes = codes or {}            # label -> (doc, obj, sub)
        self.point = point                  # the 3D point under the pointer at ":"
        self.view = view
        self.kinds = tuple(k for k in (kinds or ("Face", "Edge")) if k != "RefPlane") or \
            ("Face", "Edge")


class Elem(object):
    __slots__ = ("obj", "sub", "el")

    def __init__(self, obj, sub, el):
        self.obj, self.sub, self.el = obj, sub, el

    @property
    def kind(self):
        return re.sub(r"\d+$", "", self.sub)

    def key(self):
        return (self.obj.Document.Name, self.obj.Name, self.sub)


def _elems_of(obj, kind):
    shape = obj.Shape
    lst = {"Face": shape.Faces, "Edge": shape.Edges, "Vertex": shape.Vertexes}[kind]
    out = []
    for i, el in enumerate(lst, 1):
        if kind == "Edge" and getattr(el, "Degenerated", False):
            continue
        out.append(Elem(obj, "%s%d" % (kind, i), el))
    return out


def _elem(key):
    doc, name, sub = key
    try:
        obj = App.getDocument(doc).getObject(name)
        return Elem(obj, sub, obj.Shape.getElement(sub) if sub else obj.Shape)
    except Exception:
        return None


def bodies(doc):
    from .hints import view_objects
    return view_objects(doc)


def centre(el):
    if el.ShapeType == "Vertex":
        return el.Point
    if el.ShapeType == "Edge":
        a, b = el.FirstParameter, el.LastParameter
        try:
            return el.valueAt(0.5 * (a + b))
        except Exception:
            return el.BoundBox.Center
    return topo.centroid(el)


def size(el):
    return el.Area if el.ShapeType == "Face" else el.Length if el.ShapeType == "Edge" else 0.0


def surface_type(el):
    try:
        if el.ShapeType == "Face":
            return type(el.Surface).__name__
        if el.ShapeType == "Edge":
            return type(el.Curve).__name__
    except Exception:
        pass
    return ""


# ------------------------------------------------------------------ the last feature

def _part(doc):
    from ..app import part as part_mod
    from . import active
    try:
        return active.active_part(doc, create=False)
    except Exception:
        parts = part_mod.find_parts(doc) if doc is not None else []
        return parts[0] if parts else None


def last_feature(doc):
    """The feature at the rollback bar (the one just made), or None."""
    from ..app import util
    part = _part(doc)
    if part is None:
        return None
    tip = getattr(part, "Tip", None)
    if tip is not None and util.is_feature(tip):
        return tip
    feats = util.features(part)
    return feats[-1] if feats else None


def _sig(el):
    c = centre(el)
    return (el.ShapeType, surface_type(el), round(c.x, 4), round(c.y, 4), round(c.z, 4),
            round(size(el), 4))


def new_elements(doc, kinds):
    """The elements of the bodies shown that the last feature made: those its base
    had nothing like (same kind, same place, same size)."""
    f = last_feature(doc)
    if f is None:
        return []
    base = getattr(f, "BaseFeature", None)
    before = set()
    if base is not None and not base.Shape.isNull():
        for k in kinds:
            lst = {"Face": base.Shape.Faces, "Edge": base.Shape.Edges,
                   "Vertex": base.Shape.Vertexes}[k]
            before.update(_sig(e) for e in lst)
    out = []
    for b in bodies(doc):
        for k in kinds:
            out += [e for e in _elems_of(b, k) if _sig(e.el) not in before]
    return out


def _sketch_of(f):
    for o in getattr(f, "OutList", []):
        if o.TypeId.startswith("Sketcher::SketchObject"):
            return o
    return None


def last_faces(doc, which):
    """Faces of the last feature: "last" all it made, "last.caps" its end faces,
    "last.sides" the rest, "last.top" the end farthest from its sketch."""
    faces = new_elements(doc, ("Face",))
    if which == "last" or not faces:
        return faces
    f = last_feature(doc)
    sk = _sketch_of(f) if f is not None else None
    planar = [e for e in faces if surface_type(e.el) == "Plane"]
    if sk is not None:
        pl = sk.getGlobalPlacement()
        n = pl.Rotation.multVec(App.Vector(0, 0, 1))
        origin = pl.Base
    else:
        biggest = max(planar, key=lambda e: e.el.Area) if planar else None
        n = biggest.el.normalAt(0, 0) if biggest is not None else App.Vector(0, 0, 1)
        origin = App.Vector()
    caps = [e for e in planar if abs(abs(e.el.normalAt(0, 0).dot(n)) - 1.0) < 1e-6]
    if which == "last.caps":
        return caps
    if which == "last.sides":
        ids = {e.key() for e in caps}
        return [e for e in faces if e.key() not in ids]
    # last.top: the cap farthest from the sketch (from the origin along Z without one)
    pool = caps or faces
    dist = [(abs((centre(e.el) - origin).dot(n)), e) for e in pool]
    far = max(d for d, _e in dist)
    return [e for d, e in dist if far - d <= NEAR]


# ------------------------------------------------------------------ registers

def to_items(keys):
    """Register items for selection keys: the element's name and fingerprint."""
    from ..app import refs
    out = []
    for k in keys:
        e = _elem(k)
        if e is None:
            continue
        out.append({"obj": k[1], "sub": k[2], "fp": refs.fingerprint(e.el)})
    return out


def from_items(doc, items):
    """Selection keys for register items: the named element if it still matches its
    fingerprint, else the one element that does. ([keys], number lost)."""
    from ..app import refs
    keys, lost = [], 0
    for it in items:
        obj = doc.getObject(it.get("obj", "")) if doc is not None else None
        if obj is None:
            lost += 1
            continue
        sub, fp = it.get("sub", ""), it.get("fp") or {}
        found = refs.find_element(obj, sub, fp)
        if found is None:
            lost += 1
            continue
        keys.append((doc.Name, obj.Name, found))
    return keys, lost


# ------------------------------------------------------------------ stepping

def _shares(a, b, kind):
    """Whether two elements share an edge (faces) or a vertex (edges, vertices)."""
    if kind == "Face":
        return any(x.isSame(y) for x in a.Edges for y in b.Edges)
    return any(x.isSame(y) for x in a.Vertexes for y in b.Vertexes)


def neighbours(e):
    """The elements next to ``e`` on its body: faces sharing an edge, edges sharing
    a vertex, vertices joined by an edge."""
    kind = e.kind
    out = []
    if kind == "Vertex":
        ends = []
        for ed in e.obj.Shape.Edges:
            if any(v.isSame(e.el) for v in ed.Vertexes):
                ends += [v for v in ed.Vertexes if not v.isSame(e.el)]
        for x in _elems_of(e.obj, "Vertex"):
            if any(x.el.isSame(v) for v in ends):
                out.append(x)
        return out
    for x in _elems_of(e.obj, kind):
        if x.sub != e.sub and _shares(e.el, x.el, kind):
            out.append(x)
    return out


def _screen(view, p):
    if view is not None:
        try:
            x, y = view.getPointOnViewport(p)
            return float(x), float(y)
        except Exception:
            pass
    return p.x, p.y


def ordered(e, view=None):
    """Its neighbours clockwise on screen, from twelve o'clock."""
    c = _screen(view, centre(e.el))
    def angle(n):
        x, y = _screen(view, centre(n.el))
        a = math.atan2(x - c[0], y - c[1])          # from up, clockwise (y is up)
        return a % (2 * math.pi)
    return sorted(neighbours(e), key=angle)


def _tangent_next(e, back=None):
    """The edge that carries on smoothly from an edge's far end (or None)."""
    from ..core.features import edges as core_edges
    el = e.el
    for v in el.Vertexes[::-1]:
        if back is not None and any(v.isSame(w) for w in back.el.Vertexes):
            continue
        t0 = core_edges._tangent_at(el, v)
        for x in _elems_of(e.obj, "Edge"):
            if x.sub == e.sub or (back is not None and x.sub == back.sub):
                continue
            if not any(xv.isSame(v) for xv in x.el.Vertexes):
                continue
            t1 = core_edges._tangent_at(x.el, v)
            if abs(abs(t0.dot(t1)) - 1.0) < 1e-6:
                return x
    return None


def step(e, motions, view=None):
    """``e`` moved by ``]``, ``[`` and ``+`` (or None when it can't go)."""
    net = motions.count("]") - motions.count("[")
    if net:
        ring = ordered(e, view)
        if not ring:
            return None
        e = ring[(net - 1) % len(ring)] if net > 0 else ring[::-1][(-net - 1) % len(ring)]
    back = None
    for _i in range(motions.count("+")):
        if e.kind != "Edge":
            return None
        nxt = _tangent_next(e, back)
        if nxt is None:
            return None
        back, e = e, nxt
    return e


# ------------------------------------------------------------------ filters

def _axis(word):
    v = AXES.get(word.lower())
    return App.Vector(*v) if v else None


def _direction(el):
    """A face's normal or a straight edge's direction, or None."""
    try:
        if el.ShapeType == "Face" and surface_type(el) == "Plane":
            u0, u1, v0, v1 = el.ParameterRange
            return el.normalAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))
        if el.ShapeType == "Edge" and surface_type(el) in ("Line", "LineSegment"):
            d = el.Vertexes[-1].Point - el.Vertexes[0].Point
            return d.normalize() if d.Length > TOL else None
    except Exception:
        pass
    return None


def measure(e, what):
    el = e.el
    if what in ("x", "y", "z"):
        return getattr(centre(el), what)
    if what == "length":
        return el.Length if el.ShapeType == "Edge" else None
    if what == "area":
        return el.Area if el.ShapeType == "Face" else None
    try:
        g = el.Curve if el.ShapeType == "Edge" else el.Surface
        r = g.Radius
    except Exception:
        return None
    return 2 * r if what == "diameter" else r


def _concave(e):
    """For an edge between two faces: whether the corner is inside (concave)."""
    from ..core.features import edges as core_edges
    try:
        return core_edges.is_concave(e.obj.Shape, e.el)
    except Exception:
        return None


def _convert(elems, kind):
    """The elements of ``kind`` on (or of) ``elems``."""
    out, seen = [], set()
    for e in elems:
        if e.kind == kind:
            cands = [e]
        elif kind == "Face":
            cands = [x for x in _elems_of(e.obj, "Face")
                     if any(s.isSame(e.el) for s in (x.el.Edges if e.kind == "Edge"
                                                       else x.el.Vertexes))]
        else:
            subs = e.el.Edges if kind == "Edge" else e.el.Vertexes
            cands = [x for x in _elems_of(e.obj, kind) if any(x.el.isSame(s) for s in subs)]
        for x in cands:
            if x.key() not in seen:
                seen.add(x.key())
                out.append(x)
    return out


def apply_filter(elems, f, ctx):
    """Narrow (or turn) ``elems`` by one filter; raises ValueError when ``f``
    means nothing."""
    w = f.lower()
    if w in KINDS:
        return _convert(elems, KINDS[w])
    if w in TYPES:
        kind, names = TYPES[w]
        keep = [e for e in elems if e.kind == kind]
        if names is None:
            return [e for e in keep if surface_type(e.el) not in ("Line", "LineSegment")]
        return [e for e in keep if surface_type(e.el) in names]
    if w in ("concave", "convex"):
        want = w == "concave"
        return [e for e in elems if e.kind == "Edge" and _concave(e) is want]
    if w in EXTREMES:
        d = _axis(w)
        if not elems:
            return []
        vals = [(centre(e.el).dot(d), e) for e in elems]
        top = max(v for v, _e in vals)
        return [e for v, e in vals if top - v <= NEAR]
    if w in ("largest", "smallest"):
        if not elems:
            return []
        vals = [(size(e.el), e) for e in elems]
        pick = max(v for v, _e in vals) if w == "largest" else min(v for v, _e in vals)
        return [e for v, e in vals if abs(v - pick) <= NEAR]
    if w == "nearest":
        if not elems or ctx.point is None:
            return elems[:1]
        import Part
        p = Part.Vertex(ctx.point)
        return [min(elems, key=lambda e: e.el.distToShape(p)[0])]
    if w.startswith("par:") or w.startswith("perp:"):
        d = _axis(w.split(":", 1)[1])
        if d is None:
            raise ValueError("\"{}\": par: and perp: take x, y, z, top, front...".format(f))
        out = []
        for e in elems:
            v = _direction(e.el)
            if v is None:
                # A cylinder round the axis is a wall too: its normals are all square to it.
                if w.startswith("perp:") and e.kind == "Face" and \
                        surface_type(e.el) == "Cylinder":
                    ax = e.el.Surface.Axis
                    if abs(abs(ax.dot(d)) - 1.0) < 1e-6:
                        out.append(e)
                continue
            along = abs(abs(v.dot(d)) - 1.0) < 1e-6
            square = abs(v.dot(d)) < 1e-6
            if (along if w.startswith("par:") else square):
                out.append(e)
        return out
    m = COMPARE.match(w)
    if m:
        what, op, num = MEASURES[m.group(1)], m.group(2), float(m.group(3))
        out = []
        for e in elems:
            v = measure(e, what)
            if v is None:
                continue
            ok = {"<": v < num - NEAR, ">": v > num + NEAR, "<=": v <= num + NEAR,
                  ">=": v >= num - NEAR, "=": abs(v - num) <= NEAR}[op]
            if ok:
                out.append(e)
        return out
    raise ValueError("\"{}\" isn't a filter.".format(f))


# ------------------------------------------------------------------ resolving

def split_part(part):
    """A part's source and its filters: "jk]:edges:top" -> ("jk]", ["edges", "top"]).
    par:/perp: keep their axis."""
    bits = part.split(":")
    src, filters = bits[0], []
    i = 1
    while i < len(bits):
        b = bits[i]
        if b.lower() in ("par", "perp") and i + 1 < len(bits):
            filters.append(b + ":" + bits[i + 1])
            i += 2
            continue
        filters.append(b)
        i += 1
    return src, filters


def code_and_motions(src):
    """"jk]]" -> ("jk", "]]")."""
    i = len(src)
    while i > 0 and src[i - 1] in MOTIONS:
        i -= 1
    return src[:i], src[i:]


def _source(src, ctx, prev):
    """The elements a part's source names. ``prev``: the part before (for words)."""
    low = src.lower()
    if low in ("new",):
        return new_elements(ctx.doc, [k if k != "Plane" else "Face" for k in ctx.kinds])
    if low in LAST_FACES:
        return last_faces(ctx.doc, low)
    if low == "*":
        return [e for b in bodies(ctx.doc) for k in ("Face", "Edge") for e in _elems_of(b, k)]
    if low in SOURCE_KINDS:
        return [e for b in bodies(ctx.doc) for e in _elems_of(b, SOURCE_KINDS[low])]
    if low.startswith("@"):
        from . import line_store
        items = line_store.registers(ctx.doc).get(low[1:])
        if items is None:
            raise ValueError("No register \"{}\".".format(low[1:]))
        keys, lost = from_items(ctx.doc, items)
        if lost and not keys:
            raise ValueError("Register \"{}\": its elements are gone.".format(low[1:]))
        return [x for x in (_elem(k) for k in keys) if x is not None]
    which = pick_tools.word(low)
    if which is not None:
        base = [e for e in prev if e.kind == "Edge"]
        if not base:
            raise ValueError("\"{}\" adds edges from an edge: pick one before it.".format(src))
        out = []
        for b in base:
            out += [x for x in (_elem((b.obj.Document.Name, b.obj.Name, n))
                                for n in pick_tools.expand(b.obj, b.sub, which)) if x]
        if not out:
            raise ValueError("No {} from that edge.".format(which))
        return out
    if low in ORIGIN_PLANES:
        from ..app import part as part_mod
        part = _part(ctx.doc)
        o = part_mod.origin_feature(part, ORIGIN_PLANES[low]) if part is not None else None
        if o is None:
            raise ValueError("No {}.".format(ORIGIN_PLANES[low]))
        return [Elem(o, "", o.Shape)]
    code, motions = code_and_motions(src)
    key = ctx.codes.get(code)
    if key is None:
        named = by_name(ctx.doc, src)
        if named is not None:
            obj, sub = named
            try:
                return [Elem(obj, sub, obj.Shape.getElement(sub) if sub else obj.Shape)]
            except Exception:
                raise ValueError("{} has no {}.".format(token_name(obj), sub))
        if is_code(src):
            raise ValueError("No label \"{}\" in view.".format(code))
        raise ValueError("No label or name \"{}\".".format(src))
    e = _elem(key)
    if e is None:
        raise ValueError("\"{}\" is gone.".format(code))
    if motions:
        moved = step(e, motions, ctx.view)
        if moved is None:
            raise ValueError("Can't step {} from \"{}\".".format(motions, code))
        e = moved
    return [e]


def _norm(s):
    return "".join(c for c in s.lower() if c.isalnum())


def named_objects(doc):
    """What can be picked by name: the bodies, and in each part its features,
    sketches, reference geometry and origin. [(name to type, object)]."""
    from ..app import part as part_mod
    from ..app import util
    out = []
    for part in part_mod.find_parts(doc) if doc is not None else []:
        for b in part_mod.body_views(part):
            out.append(b)
        out += list(getattr(part, "Origin", []) or [])
        for o in getattr(part, "Group", []) or []:
            if util.is_feature(o) or util.role(o) == "refgeom" or \
                    o.TypeId.startswith("Sketcher::SketchObject"):
                out.append(o)
    seen, res = set(), []
    for o in out:
        if o.Name in seen:
            continue
        seen.add(o.Name)
        res.append((token_name(o), o))
    return res


def token_name(obj):
    """An object's name as typed in sel=: its label without spaces."""
    from ..app import part as part_mod
    return "".join(part_mod.clean_label(obj.Label).split())


def by_name(doc, name):
    """(object, sub) a typed name means: "Plane1", "Front Plane" (any case,
    spaces and punctuation ignored), "Body.Edge3" for an element; or None."""
    obj_name, _dot, sub = name.partition(".")
    if sub and not re.match(r"^(Face|Edge|Vertex)\d+$", sub, re.I):
        obj_name, sub = name, ""            # a dot in the name itself
    n = _norm(obj_name)
    if not n:
        return None
    cands = named_objects(doc)
    hit = [o for t, o in cands if _norm(t) == n] or \
        [o for _t, o in cands if _norm(o.Name) == n]
    if not hit:
        return None
    sub = sub[:1].upper() + sub[1:].lower() if sub else ""
    if sub and sub.startswith("Vertex"):
        sub = "Vertex" + sub[6:]
    return hit[0], sub


def resolve_part(part, ctx, prev=()):
    src, filters = split_part(part)
    elems = _source(src, ctx, list(prev))
    for f in filters:
        elems = apply_filter(elems, f, ctx)
    return elems


def resolve(parts, ctx):
    """([keys], [problems]) for the parts of a selection, in order, without repeats."""
    keys, seen, problems = [], set(), []
    prev = []
    for part in parts:
        if not part:
            continue
        try:
            elems = resolve_part(part, ctx, prev)
        except ValueError as e:
            problems.append(str(e))
            continue
        if not elems:
            problems.append("\"{}\" picks nothing.".format(part))
        for e in elems:
            k = e.key()
            if k not in seen:
                seen.add(k)
                keys.append(k)
        # A word adds from the pick before it, and so does the next word
        # (sel=jk,loop,otherloop: both loops of jk).
        if pick_tools.word(split_part(part)[0].lower()) is None or ":" in part:
            prev = elems
    return keys, problems


def is_code(text):
    """Whether a part is a view label (letters of the labels' alphabet, any steps)."""
    from .hints import ALPHABET
    code, _m = code_and_motions(text)
    return bool(code) and all(c in ALPHABET for c in code) and ":" not in text
