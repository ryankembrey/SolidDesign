# SPDX-License-Identifier: LGPL-2.1-or-later
"""Turning picks in the view or the tree into stored references (spec 7, 8.1).

The user clicks on *body views* (what's displayed). A reference must point at
the feature the edited feature builds on (its BaseFeature), never at its own
result, or the history would loop. Picks are mapped there: by shared topology
first, then by geometry. A pick made by the edited feature itself is refused
with a reason.
"""

import Part

from ..app import util


class Sel(object):
    """One pick: the object clicked, its sub-element, the 3D point."""
    __slots__ = ("obj", "sub", "point")

    def __init__(self, obj, sub="", point=None):
        self.obj = obj
        self.sub = sub or ""
        self.point = point

    def elem_kind(self):
        for k in ("Face", "Edge", "Vertex"):
            if self.sub.startswith(k):
                return k
        return ""

    def element(self):
        if not self.sub:
            return None
        try:
            return Part.getShape(self.obj, self.sub, needSubElement=True)
        except Exception:
            return None


def _same_geometry(a, b, tol=1e-6):
    if a.ShapeType != b.ShapeType:
        return False
    if a.ShapeType == "Vertex":
        return (a.Point - b.Point).Length < tol
    try:
        if a.ShapeType == "Face":
            if abs(a.Area - b.Area) > tol * max(1.0, a.Area):
                return False
            return (a.CenterOfMass - b.CenterOfMass).Length < tol * 10
        if a.ShapeType == "Edge":
            if abs(a.Length - b.Length) > tol * max(1.0, a.Length):
                return False
            return (a.CenterOfMass - b.CenterOfMass).Length < tol * 10
    except Exception:
        return False
    return False


def map_to_feature(elem, feature):
    """The name ("Face12") of ``elem`` in a feature's shape, or None.

    The same topology first (found by OpenCASCADE's own index, not by walking
    every element in Python), then the first element of the same geometry, in
    the shape's order. Only bodies whose box holds the pick's centre can have
    such an element, so only theirs are measured."""
    if feature is None or elem is None:
        return None
    shape = feature.Shape
    kind = elem.ShapeType
    try:
        k, i = shape.findSubShape(elem)
        if k == kind and i:
            return "{}{}".format(kind, i)
    except Exception:
        elems = shape.Faces if kind == "Face" else shape.Edges if kind == "Edge" \
            else shape.Vertexes
        for i, e in enumerate(elems, 1):
            if e.isSame(elem):
                return "{}{}".format(kind, i)
    try:
        c = elem.Point if kind == "Vertex" else elem.CenterOfMass
        from ..app import refs
        from ..core import topo
        children = refs._index(feature, shape).children
    except Exception:
        return _map_by_geometry(elem, shape, kind)
    for ch in children:
        bb = topo.bbox(ch)
        bb.enlarge(1e-4)
        if not bb.isInside(c):
            continue
        elems = ch.Faces if kind == "Face" else ch.Edges if kind == "Edge" else ch.Vertexes
        for e in elems:
            if _same_geometry(e, elem):
                try:
                    k, i = shape.findSubShape(e)
                    if k == kind and i:
                        return "{}{}".format(kind, i)
                except Exception:
                    pass
                return _map_by_geometry(elem, shape, kind)
    return None


def _map_by_geometry(elem, shape, kind):
    elems = shape.Faces if kind == "Face" else shape.Edges if kind == "Edge" else shape.Vertexes
    for i, e in enumerate(elems, 1):
        if _same_geometry(e, elem):
            return "{}{}".format(kind, i)
    return None


def feature_of_element(part, elem, before=None):
    """The feature that last touched a face or edge (made it or changed it): the
    latest feature above ``before`` whose result has it while its base doesn't.
    None when no feature above ``before`` has it."""
    face = elem
    if face is None:
        return None
    feats = util.features(part)
    if before in feats:
        feats = feats[:feats.index(before)]
    for f in reversed(feats):
        try:
            if f.Shape.isNull() or map_to_feature(face, f) is None:
                continue
        except Exception:
            continue
        base = getattr(f, "BaseFeature", None)
        if base is None or base.Shape.isNull() or map_to_feature(face, base) is None:
            return f
    return None


def _from_body(sel, base, kind):
    if not util.is_body_view(sel.obj) or sel.elem_kind() != kind:
        return None
    if base is None:
        return "There is no body before this feature to pick from."
    name = map_to_feature(sel.element(), base)
    if name is None:
        return ("That {} is made by this feature or a later one. Pick one that exists "
                "before it.".format(kind.lower()))
    return base, name


def face_ref(sel, base, editing):
    """(object, sub) for a face or plane pick, a refusal string, or None."""
    o = sel.obj
    if o is editing:
        return "A feature can't refer to its own faces."
    if o.TypeId in ("Part::DatumPlane", "App::Plane", "PartDesign::Plane") and not sel.sub:
        return o, ""
    if o.TypeId in ("Part::DatumPlane", "App::Plane"):
        return o, ""
    if util.role(o) == "refgeom" and o.Proxy.KIND == "plane":
        return o, ""
    r = _from_body(sel, base, "Face")
    if r is not None:
        return r
    if util.is_feature(o) and sel.elem_kind() == "Face":
        return o, sel.sub
    return None


def vertex_ref(sel, base, editing):
    o = sel.obj
    if o is editing:
        return "A feature can't refer to its own vertices."
    if o.TypeId in ("Part::DatumPoint", "App::Point") and not sel.elem_kind() == "Edge":
        return o, ""
    if o.TypeId.startswith("Sketcher::") and sel.elem_kind() == "Vertex":
        return o, sel.sub
    r = _from_body(sel, base, "Vertex")
    if r is not None:
        return r
    return None


def body_ref(sel, base_ids):
    """A body pick (in the view or the folder): ``(body ID,)``; a string says
    why the pick is refused; None, not a body."""
    o = sel.obj
    if not util.is_body_view(o):
        return None
    if o.BodyId not in base_ids:
        return "{} doesn't exist before this feature.".format(o.Label)
    return (o.BodyId,)


def sketch_ref(sel):
    o = sel.obj
    if o.TypeId.startswith("Sketcher::SketchObject"):
        return o
    return None
