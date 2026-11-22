# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reference storage (spec section 7).

References to faces, edges and vertices live in link properties
(App::PropertyLinkSub), never in strings, so FreeCAD keeps the mapped element
name behind them and updates the index ("Face7") when the model changes.

References follow the model, as in SolidWorks: a feature's face or edge
references always resolve against the model just before the feature (its
BaseFeature). When a feature is inserted, reordered or deleted before it, the
reference is carried forward to the new BaseFeature by element-map history (an
unchanged element's name in a later feature starts with its earlier name).

With every element we also keep a *fingerprint* (type, normal or axis,
centroid, size, body ID). When the mapped name can't be followed, the
fingerprint is tried within the same body:
- exactly one match: use it, and warn "reference repaired";
- none or several: fail clearly, so the user re-picks it in the panel.
Never pick silently between several matches.
"""

import bisect
import json
from collections import OrderedDict

import FreeCAD as App
import Part

from ..core import topo
from . import util


def _elem_kind(sub):
    for k in ("Face", "Edge", "Vertex"):
        if sub.startswith(k):
            return k
    return None


def _type_name(elem):
    try:
        if elem.ShapeType == "Face":
            return elem.Surface.TypeId
        if elem.ShapeType == "Edge":
            return elem.Curve.TypeId
    except Exception:
        pass
    return elem.ShapeType


def _orientation(elem):
    try:
        if elem.ShapeType == "Face":
            u0, u1, v0, v1 = elem.ParameterRange
            n = elem.normalAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))
            if elem.Surface.TypeId == "Part::GeomPlane":
                return [n.x, n.y, n.z]
            if hasattr(elem.Surface, "Axis"):
                a = elem.Surface.Axis
                return [a.x, a.y, a.z]
            return [n.x, n.y, n.z]
        if elem.ShapeType == "Edge":
            c = elem.Curve
            if hasattr(c, "Axis"):
                a = c.Axis
                return [a.x, a.y, a.z]
            if hasattr(c, "Direction"):
                a = c.Direction
                return [a.x, a.y, a.z]
    except Exception:
        pass
    return None


def _size(elem):
    try:
        if elem.ShapeType == "Face":
            return elem.Area
        if elem.ShapeType == "Edge":
            return elem.Length
    except Exception:
        pass
    return 0.0


SAMPLES = 24             # points kept along an edge, or round a face's outline


def outline(elem):
    """A few points along an element (round a face's outer edges), so where it was
    can be drawn after it is gone: [[x, y, z], ...]."""
    try:
        if elem.ShapeType == "Vertex":
            pts = [elem.Point]
        elif elem.ShapeType == "Edge":
            if getattr(elem, "Degenerated", False) or elem.Length <= 1e-9:
                pts = [elem.Vertexes[0].Point] if elem.Vertexes else []
            else:
                pts = elem.discretize(SAMPLES)
        else:
            # Edge by edge, never the wire at once: OCC can crash (not raise) on a
            # wire with a degenerate edge, as at the tip of a sweep.
            edges = [e for e in elem.OuterWire.OrderedEdges
                     if not getattr(e, "Degenerated", False) and e.Length > 1e-9]
            k = max(2, min(12, 96 // max(1, len(edges))))
            pts = []
            for e in edges:
                pts.extend(e.discretize(k))
    except Exception:
        return []
    return [[round(p.x, 4), round(p.y, 4), round(p.z, 4)] for p in pts]


def _fingerprint(elem, body_id=""):
    c = topo.centroid(elem) if elem.ShapeType != "Vertex" else elem.Point
    return {"kind": elem.ShapeType, "type": _type_name(elem), "dir": _orientation(elem),
            "c": [c.x, c.y, c.z], "size": _size(elem), "body": body_id or "",
            "pts": outline(elem)}


def _copy_fp(fp):
    return {k: ([list(p) for p in v] if k == "pts" else list(v) if isinstance(v, list) else v)
            for k, v in fp.items()}


def fingerprint(elem, body_id="", ix=None):
    """``ix``: the _Index of the shape ``elem`` is in, which keeps fingerprints
    already worked out (an element that didn't change isn't measured again)."""
    if ix is None:
        return _fingerprint(elem, body_id)
    try:
        h = elem.hashCode()
    except Exception:
        return _fingerprint(elem, body_id)
    for e, b, fp in ix.fps.get(h, ()):
        if b == body_id and e.isSame(elem):
            return _copy_fp(fp)
    fp = _fingerprint(elem, body_id)
    ix.fps.setdefault(h, []).append((elem, body_id, _copy_fp(fp)))
    return fp


# ------------------------------------------------------------------ shape indexes
# With hundreds of bodies, finding which body holds an element, or which element
# a mapped name now has, meant walking every element of the model for every
# reference on every recompute. An index is built once per feature shape (and
# rebuilt when the shape changes) and answers the same questions by lookup.

_INDEXES = OrderedDict()
_INDEXES_KEPT = 16


class _Index:
    def __init__(self, shape):
        self.shape = shape
        self.children = shape.childShapes() if shape.ShapeType == "Compound" else [shape]
        self._kinds = {}
        self._cum = {}
        self.fps = {}
        self._names = {}
        self._history = {}
        self._bbox = None

    def elements(self, kind):
        """{hashCode: [(element, child index)]} over the children's elements (in
        child order, so the first isSame match is the first child that has it)."""
        m = self._kinds.get(kind)
        if m is None:
            m = {}
            for i, ch in enumerate(self.children):
                elems = ch.Faces if kind == "Face" else ch.Edges if kind == "Edge" \
                    else ch.Vertexes
                for e in elems:
                    m.setdefault(e.hashCode(), []).append((e, i))
            self._kinds[kind] = m
        return m

    def _ranges(self, kind):
        """Running totals of each child's elements of a kind, when no element is
        in two children (the shape's own numbering is then child after child);
        else None (split pieces can share faces)."""
        if kind not in self._cum:
            cum, n = [], 0
            for ch in self.children:
                n += ch.countElement(kind)
                cum.append(n)
            self._cum[kind] = cum if n == self.shape.countElement(kind) else None
        return self._cum[kind]

    def child_of(self, elem):
        """The index of the first child holding ``elem`` (isSame), or None."""
        try:
            kind = elem.ShapeType
            cum = self._ranges(kind) if len(self.children) > 1 else None
            if cum is not None:
                # OpenCASCADE's own index of the element in the whole shape.
                k, i = self.shape.findSubShape(elem)
                if not i or k != kind:
                    return None
                return bisect.bisect_left(cum, i)
            hits = self.elements(kind).get(elem.hashCode(), ())
        except Exception:
            return None
        for e, i in hits:
            if e.isSame(elem):
                return i
        return None

    def names(self, kind):
        """Sorted [(mapped name, index name)] of one kind of element."""
        v = self._names.get(kind)
        if v is None:
            shape = self.shape
            n = shape.countElement(kind)
            try:
                rmap = shape.ElementReverseMap
            except Exception:
                rmap = {}
            v = []
            for i in range(1, n + 1):
                name = "{}{}".format(kind, i)
                m = rmap.get(name, "")
                if not isinstance(m, str):
                    m = _mapped(shape, name)     # several names: the one getElement gives
                if m:
                    v.append((m, name))
            v.sort()
            self._names[kind] = v
        return v

    def history(self, kind):
        """[(index name, history)] of one kind of element, in index order."""
        v = self._history.get(kind)
        if v is None:
            shape = self.shape
            v = []
            for i in range(1, shape.countElement(kind) + 1):
                name = "{}{}".format(kind, i)
                m = _mapped(shape, name)
                try:
                    h = shape.getElementHistory(m) if m else None
                except Exception:
                    h = None
                v.append((name, h))
            self._history[kind] = v
        return v

    def diagonal(self):
        if self._bbox is None:
            self._bbox = topo.bbox(self.shape).DiagonalLength
        return self._bbox


def _index(obj, shape=None):
    """The index of a feature's shape (``shape``: obj.Shape when already read)."""
    if shape is None:
        shape = obj.Shape
    try:
        key = (obj.Document.Name, obj.Name)
    except Exception:
        return _Index(shape)
    ix = _INDEXES.get(key)
    if ix is not None and topo.same_shape(ix.shape, shape):
        _INDEXES.move_to_end(key)
        return ix
    ix = _Index(shape)
    _INDEXES[key] = ix
    while len(_INDEXES) > _INDEXES_KEPT:
        _INDEXES.popitem(last=False)
    return ix


def clear_indexes():
    _INDEXES.clear()


def _children(obj):
    return _index(obj).children


def body_of_element(obj, elem, ix=None):
    """The body ID (from a feature's BodyIds) that holds an element, or ''."""
    ids = list(getattr(obj, "BodyIds", []) or [])
    if not ids or elem is None:
        return ""
    if ix is None:
        ix = _index(obj)
    i = ix.child_of(elem)
    if i is not None:
        return ids[i] if i < len(ids) else ""
    from ..core.features.edges import find_in
    for i, ch in enumerate(ix.children):        # shapes that don't share topology
        if find_in(ch, elem) is not None:
            return ids[i] if i < len(ids) else ""
    return ""


def _fingerprint_in(obj, elem):
    ix = _index(obj)
    return fingerprint(elem, body_of_element(obj, elem, ix), ix)


# ------------------------------------------------------------------ fingerprints

def _fps(obj):
    if "RefFingerprints" not in obj.PropertiesList:
        return {}
    return dict(obj.RefFingerprints)


def _store(obj, prop, fps):
    """fps: list (one per sub-element) of fingerprint dicts or None."""
    if "RefFingerprints" not in obj.PropertiesList:
        return
    m = dict(obj.RefFingerprints)
    if not fps or all(f is None for f in fps):
        m.pop(prop, None)
    else:
        m[prop] = json.dumps(fps if len(fps) > 1 else fps[0])
    if m != dict(obj.RefFingerprints):
        obj.RefFingerprints = m


def _load(obj, prop, n):
    try:
        v = json.loads(_fps(obj).get(prop, ""))
    except Exception:
        return [None] * n
    if isinstance(v, dict):
        v = [v]
    v = list(v) + [None] * max(0, n - len(v))
    return v[:n]


def set_ref(obj, prop, target, subs=""):
    """Store a reference (one sub-element, a list of them, or the whole object)."""
    if target is None:
        setattr(obj, prop, None)
        _store(obj, prop, None)
        return
    if isinstance(subs, str):
        subs = [subs] if subs else []
    if any(r.get("prop") == prop for r in repairs(obj)):
        accept_repairs(obj, prop)           # picked again: nothing left to check
    setattr(obj, prop, (target, list(subs)))
    fps = []
    for sub in subs:
        try:
            elem = Part.getShape(target, sub, needSubElement=True)
            fps.append(_fingerprint_in(target, elem))
        except Exception:
            fps.append(None)
    _store(obj, prop, fps)


# ------------------------------------------------------------------ what went wrong
# A feature keeps, in two hidden properties, what happened to its references:
# RefRepairs: references found again by their fingerprint, with where they were
#   (the old fingerprint, points included) and what they are now; kept, and
#   warned about, until the user checks them (What's Wrong > Looks Right, or OK
#   in the feature's panel, or picking the reference again).
# RefLost: references that couldn't be found at the last recompute, with what
#   they were; written afresh each recompute.

def _issues(obj, prop):
    if prop not in obj.PropertiesList:
        return []
    try:
        v = json.loads(getattr(obj, prop) or "[]")
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _set_issues(obj, prop, items):
    if prop not in obj.PropertiesList:
        return
    text = json.dumps(items)
    if getattr(obj, prop) != text:
        setattr(obj, prop, text)


def repairs(obj):
    """[{prop, what, old, new, sub, target, msg}] not yet checked."""
    return _issues(obj, "RefRepairs")


def lost(obj):
    """[{prop, what, old, target, msg}] from the last recompute."""
    return _issues(obj, "RefLost")


def _note_repair(obj, prop, what, old_fp, target, sub, elem, msg, origin=None):
    items = [r for r in repairs(obj) if not (r.get("prop") == prop and r.get("sub") == sub)]
    first = next((r for r in repairs(obj) if r.get("prop") == prop), None)
    # Repaired twice before it was checked: where it was first is what matters.
    old = first["old"] if first is not None and first.get("old") else old_fp
    items.append({"prop": prop, "what": what, "old": old,
                  "new": _fingerprint_in(target, elem),
                  "sub": sub, "target": target.Name if target is not None else "",
                  "origin": (first or {}).get("origin") or
                  (origin.Name if origin is not None else ""), "msg": msg})
    _set_issues(obj, "RefRepairs", items)


def _note_lost(obj, prop, what, fp, target, msg, origin=None):
    """``origin``: the feature the reference was picked on (what changed it is
    after that one)."""
    items = lost(obj)
    items.append({"prop": prop, "what": what, "old": fp,
                  "target": target.Name if target is not None else "",
                  "origin": origin.Name if origin is not None else "", "msg": msg})
    _set_issues(obj, "RefLost", items)


def start_recompute(obj):
    """Before a feature's recompute: forget the last one's lost references."""
    _set_issues(obj, "RefLost", [])


def accept_repairs(obj, prop=None):
    """The user checked them: no more warning (``prop``: just that reference's)."""
    _set_issues(obj, "RefRepairs", [r for r in repairs(obj)
                                    if prop is not None and r.get("prop") != prop])


def pending_warnings(obj):
    """The warnings of repairs not yet checked (each once)."""
    out = []
    for r in repairs(obj):
        m = r.get("msg") or "A reference was repaired. Check it."
        if m not in out:
            out.append(m)
    return out


def candidates(obj, issue):
    """The elements that could replace a lost reference (for "several could")."""
    try:
        target = obj.Document.getObject(issue.get("target") or "")
        fp = issue.get("old")
        if target is None or not fp:
            return []
        return _match(target, fp)
    except Exception:
        return []


# ------------------------------------------------------------------ following

def _mapped(shape, name):
    try:
        m = shape.getElementMappedName(name)
    except Exception:
        return ""
    if isinstance(m, (tuple, list)):
        m = m[0] if m else ""
    return m or ""


def follow(target, sub, base):
    """The name in ``base`` of the element ``sub`` of an earlier feature ``target``.

    Uses element-map history: an element that passed through later features
    unchanged keeps its earlier mapped name as a prefix. Returns None when it
    can't be followed (modified or gone).
    """
    kind = _elem_kind(sub)
    old = _mapped(target.Shape, sub)
    if not old or kind is None:
        return None
    ix = _index(base)
    names = ix.names(kind)
    hits = []
    # Exact matches and old + ";..." sort together, right after ``old``.
    i = bisect.bisect_left(names, (old,))
    while i < len(names) and names[i][0].startswith(old):
        m, name = names[i]
        if m == old or m[len(old):len(old) + 1] == ";":
            hits.append(name)
        i += 1
    if len(hits) == 1:
        return hits[0]
    if not hits:
        for name, h in ix.history(kind):
            if h and (h[1] == old or old in (h[2] or [])):
                hits.append(name)
        if len(hits) == 1:
            return hits[0]
    return None


def _same_dir(a, b, tol=1e-6):
    if a is None or b is None:
        return a is None and b is None
    va, vb = App.Vector(*a), App.Vector(*b)
    if va.Length < tol or vb.Length < tol:
        return True
    return abs(abs(va.normalize().dot(vb.normalize())) - 1.0) < tol


def _candidates(target, fp, ix=None):
    if ix is None:
        ix = _index(target)
    shape = ix.shape
    ids = list(getattr(target, "BodyIds", []) or [])
    if fp.get("body") and ids and fp["body"] in ids:
        idx = ids.index(fp["body"])
        if idx < len(ix.children):
            shape = ix.children[idx]
    kind = fp["kind"]
    elems = shape.Faces if kind == "Face" else shape.Edges if kind == "Edge" else shape.Vertexes
    return [e for e in elems if _type_name(e) == fp["type"] and _same_dir(_orientation(e), fp["dir"])]


def _near(e, fp, scale):
    c = App.Vector(*fp["c"])
    ec = topo.centroid(e) if e.ShapeType != "Vertex" else e.Point
    size = _size(e)
    return (ec - c).Length <= 0.01 * scale and (
        fp["size"] == 0 or abs(size - fp["size"]) <= 0.1 * max(fp["size"], 1e-9))


def _match(target, fp, ix=None):
    if ix is None:
        ix = _index(target)
    cands = _candidates(target, fp, ix)
    if len(cands) <= 1:
        return cands
    scale = max(ix.diagonal(), 1e-6)
    return [e for e in cands if _near(e, fp, scale)]


def _index_of(target, elem):
    kind = elem.ShapeType
    try:
        k, i = target.Shape.findSubShape(elem)
        return "{}{}".format(kind, i) if k == kind and i else None
    except Exception:
        pass
    elems = target.Shape.Faces if kind == "Face" else target.Shape.Edges if kind == "Edge" \
        else target.Shape.Vertexes
    for i, e in enumerate(elems, 1):
        if e.isSame(elem):
            return "{}{}".format(kind, i)
    return None


def _resolve(target, sub, fp, base, what):
    """Resolve one element. Returns (elem, target, sub, warning)."""
    # Carry a reference to an earlier feature forward to the feature just before.
    movable = (base is not None and target is not None and target is not base
               and util.is_feature(target) and util.is_feature(base) and sub)
    if target is None and base is not None and fp is not None:
        target, sub, movable = base, "", False
        found = _match(base, fp)
        if len(found) == 1:
            name = _index_of(base, found[0])
            return found[0], base, name, "The {} was lost and repaired from its fingerprint. " \
                                         "Check it.".format(what)
        raise topo.GeometryError("The {} no longer exists. Re-pick it.".format(what))
    if movable:
        name = follow(target, sub.lstrip("?"), base)
        if name is not None:
            return Part.getShape(base, name, needSubElement=True), base, name, None
        if fp is not None:
            found = _match(base, fp)
            if len(found) == 1:
                return found[0], base, _index_of(base, found[0]), (
                    "The {} changed before this feature and was matched again. Check it."
                    .format(what))
        raise topo.GeometryError("The {} ({}) was changed by a feature before this one. "
                                 "Re-pick it.".format(what, sub.lstrip("?")))
    elem = None
    try:
        if not sub.startswith("?"):
            elem = Part.getShape(target, sub, needSubElement=True)
            if elem.isNull():
                elem = None
    except Exception:
        elem = None
    if elem is not None and (fp is None or (_type_name(elem) == fp.get("type")
                                             and elem.ShapeType == fp.get("kind"))):
        return elem, target, sub, None
    if fp is None:
        raise topo.GeometryError("The {} ({} of {}) no longer exists. Re-pick it."
                                 .format(what, sub.lstrip("?"), target.Label))
    found = _match(target, fp)
    if len(found) == 1:
        return found[0], target, _index_of(target, found[0]), (
            "The {} was lost and repaired from its fingerprint. Check it.".format(what))
    if not found:
        raise topo.GeometryError("The {} ({} of {}) no longer exists. Re-pick it."
                                 .format(what, _elem_kind(sub.lstrip("?")) or sub, target.Label))
    raise topo.GeometryError("The {} was lost and {} elements could replace it. Re-pick it."
                             .format(what, len(found)))


def get_refs(obj, prop, what="reference", base=None):
    """Resolve every sub-element of a reference.

    Returns (elements, warnings). A reference without sub-elements returns the
    whole object's shape as the only element. ``base`` (the feature's
    BaseFeature) lets references to earlier features follow the model.
    Rewrites the property when references moved or were repaired.
    """
    val = getattr(obj, prop, None)
    if not val or val[0] is None:
        # The target was deleted. With fingerprints and a base, find it again there.
        try:
            stored = json.loads(_fps(obj).get(prop, ""))
        except Exception:
            stored = None
        if base is None or not stored:
            return [], []
        fps = stored if isinstance(stored, list) else [stored]
        elems, subs, warns = [], [], []
        for fp in fps:
            try:
                e, _t, s, w = _resolve(None, "", fp, base, what)
            except topo.GeometryError as ex:
                _note_lost(obj, prop, what, fp, base, str(ex))
                raise
            if w:
                _note_repair(obj, prop, what, fp, base, s, e, w)
            elems.append(e)
            subs.append(s)
            warns.append(w)
        setattr(obj, prop, (base, subs))
        _store(obj, prop, [_fingerprint_in(base, e) for e in elems])
        return elems, [w for w in warns if w]
    target, subs = val
    if not subs:
        return [topo.shape_of(target)], []
    fps = _load(obj, prop, len(subs))
    elems, new_subs, warns = [], [], []
    new_target = target
    for sub, fp in zip(subs, fps):
        try:
            e, t, s, w = _resolve(target, sub, fp, base, what)
        except topo.GeometryError as ex:
            _note_lost(obj, prop, what, fp, base if base is not None else target, str(ex),
                       origin=target)
            raise
        elems.append(e)
        new_subs.append(s)
        new_target = t
        if w:
            warns.append(w)
            _note_repair(obj, prop, what, fp, t, s, e, w, origin=target)
    if new_target is not target or list(new_subs) != list(subs):
        setattr(obj, prop, (new_target, new_subs))
    ix = _index(new_target) if elems else None
    new_fps = [fingerprint(e, body_of_element(new_target, e, ix), ix) for e in elems]
    if new_fps != fps:
        _store(obj, prop, new_fps)
    return elems, warns


def get_ref(obj, prop, what="reference", base=None):
    """One element (or the whole object's shape). Returns (shape, warning);
    (None, None) when nothing is stored."""
    elems, warns = get_refs(obj, prop, what, base)
    if not elems:
        return None, None
    return elems[0], (warns[0] if warns else None)


def find_element(target, sub, fp):
    """The name of the element of ``target`` a fingerprint means: ``sub`` while it
    still matches, else the one element that does; None when none (or several)
    do. For selections kept by name, such as the command line's registers."""
    try:
        elem = target.Shape.getElement(sub)
    except Exception:
        elem = None
    if elem is not None and not fp:
        return sub
    ix = _index(target) if fp else None
    if elem is not None and _still(target, elem, fp, ix):
        return sub
    cands = _match(target, fp, ix) if fp else []
    if elem is not None and (not fp or any(c.isSame(elem) for c in cands)):
        return sub
    if len(cands) == 1:
        return _index_of(target, cands[0])
    return None


def _still(target, elem, fp, ix):
    """True when ``elem`` is sure to be among _match(target, fp): of the
    fingerprint's body, type and direction, and near where it was (being near
    is enough either way: alone it is the only candidate, else it passes)."""
    try:
        if elem.ShapeType != fp["kind"] or _type_name(elem) != fp["type"] or \
                not _same_dir(_orientation(elem), fp["dir"]):
            return False
        ids = list(getattr(target, "BodyIds", []) or [])
        if fp.get("body") and ids and fp["body"] in ids:
            idx = ids.index(fp["body"])
            if idx < len(ix.children) and ix.child_of(elem) != idx:
                return False
        return _near(elem, fp, max(ix.diagonal(), 1e-6))
    except Exception:
        return False
