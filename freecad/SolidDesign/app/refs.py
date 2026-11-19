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

import json

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


def fingerprint(elem, body_id=""):
    c = topo.centroid(elem) if elem.ShapeType != "Vertex" else elem.Point
    return {"kind": elem.ShapeType, "type": _type_name(elem), "dir": _orientation(elem),
            "c": [c.x, c.y, c.z], "size": _size(elem), "body": body_id or ""}


def _children(obj):
    shape = obj.Shape
    return shape.childShapes() if shape.ShapeType == "Compound" else [shape]


def body_of_element(obj, elem):
    """The body ID (from a feature's BodyIds) that holds an element, or ''."""
    ids = list(getattr(obj, "BodyIds", []) or [])
    if not ids or elem is None:
        return ""
    kind = elem.ShapeType
    children = _children(obj)
    for i, ch in enumerate(children):
        elems = ch.Faces if kind == "Face" else ch.Edges if kind == "Edge" else ch.Vertexes
        for e in elems:
            if e.isSame(elem):
                return ids[i] if i < len(ids) else ""
    from ..core.features.edges import find_in
    for i, ch in enumerate(children):           # shapes that don't share topology
        if find_in(ch, elem) is not None:
            return ids[i] if i < len(ids) else ""
    return ""


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
    setattr(obj, prop, (target, list(subs)))
    fps = []
    for sub in subs:
        try:
            elem = Part.getShape(target, sub, needSubElement=True)
            fps.append(fingerprint(elem, body_of_element(target, elem)))
        except Exception:
            fps.append(None)
    _store(obj, prop, fps)


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
    shape = base.Shape
    n = len(shape.Faces if kind == "Face" else shape.Edges if kind == "Edge" else shape.Vertexes)
    hits = []
    for i in range(1, n + 1):
        name = "{}{}".format(kind, i)
        m = _mapped(shape, name)
        if m == old or (m.startswith(old) and m[len(old):len(old) + 1] == ";"):
            hits.append(name)
    if len(hits) == 1:
        return hits[0]
    if not hits:
        for i in range(1, n + 1):
            name = "{}{}".format(kind, i)
            m = _mapped(shape, name)
            try:
                h = shape.getElementHistory(m) if m else None
            except Exception:
                h = None
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


def _candidates(target, fp):
    shape = target.Shape
    ids = list(getattr(target, "BodyIds", []) or [])
    if fp.get("body") and ids and fp["body"] in ids:
        ch = _children(target)
        idx = ids.index(fp["body"])
        if idx < len(ch):
            shape = ch[idx]
    kind = fp["kind"]
    elems = shape.Faces if kind == "Face" else shape.Edges if kind == "Edge" else shape.Vertexes
    return [e for e in elems if _type_name(e) == fp["type"] and _same_dir(_orientation(e), fp["dir"])]


def _match(target, fp):
    cands = _candidates(target, fp)
    if len(cands) <= 1:
        return cands
    c = App.Vector(*fp["c"])
    scale = max(target.Shape.BoundBox.DiagonalLength, 1e-6)
    near = []
    for e in cands:
        ec = topo.centroid(e) if e.ShapeType != "Vertex" else e.Point
        size = _size(e)
        if (ec - c).Length <= 0.01 * scale and (
                fp["size"] == 0 or abs(size - fp["size"]) <= 0.1 * max(fp["size"], 1e-9)):
            near.append(e)
    return near


def _index_of(target, elem):
    kind = elem.ShapeType
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
            e, _t, s, w = _resolve(None, "", fp, base, what)
            elems.append(e)
            subs.append(s)
            warns.append(w)
        setattr(obj, prop, (base, subs))
        _store(obj, prop, [fingerprint(e, body_of_element(base, e)) for e in elems])
        return elems, [w for w in warns if w]
    target, subs = val
    if not subs:
        return [topo.shape_of(target)], []
    fps = _load(obj, prop, len(subs))
    elems, new_subs, warns = [], [], []
    new_target = target
    for sub, fp in zip(subs, fps):
        e, t, s, w = _resolve(target, sub, fp, base, what)
        elems.append(e)
        new_subs.append(s)
        new_target = t
        if w:
            warns.append(w)
    if new_target is not target or list(new_subs) != list(subs):
        setattr(obj, prop, (new_target, new_subs))
    new_fps = [fingerprint(e, body_of_element(new_target, e)) for e in elems]
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
