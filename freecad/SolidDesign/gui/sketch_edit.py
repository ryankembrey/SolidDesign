# SPDX-License-Identifier: LGPL-2.1-or-later
"""Sketching in a Solid Design part: the model stays in view.

FreeCAD's Sketcher hides every object that depends on the sketch while it is
edited. In a Part every body depends on every sketch (the body links the part,
the part holds the sketch), so all of the model disappeared, even the face being
sketched on. Sketches in a part don't hide their dependents.

A sketch can use the edges and vertices of a body (Sketcher's external geometry,
projection): the Sketcher links the body, and the link is moved at once to the
same element of the feature above the sketch, so the sketch uses the model as
it was before its own feature (as in SolidWorks) and follows it by name.

Editing a sketch that a feature already uses works as SolidWorks' Edit Sketch:
the model is rolled back to just before that feature while the sketch is open
(so the feature's own material doesn't cover the sketch), and rolled forward
when it is closed.
"""

import FreeCADGui as Gui
from PySide import QtCore

import FreeCAD as App

from ..app import part as part_mod
from ..app import util


def is_sketch(obj):
    return obj is not None and obj.TypeId.startswith("Sketcher::SketchObject")


def keep_model_visible(sketch):
    """Don't hide the model while *sketch* is edited."""
    try:
        vo = sketch.ViewObject
        if vo is not None and "HideDependent" in vo.PropertiesList and vo.HideDependent:
            vo.HideDependent = False
    except Exception:
        pass


def _first_user(part, sketch):
    """The first feature (in history order) that uses *sketch*, or None."""
    users = [o for o in sketch.InList if util.is_feature(o)]
    for f in util.features(part):
        if f in users:
            return f
    return None


class _Observer(object):
    def __init__(self):
        self.rolled = {}        # sketch name -> (part, tip before)

    def slotInEdit(self, vobj):
        try:
            obj = vobj.Object
        except Exception:
            return
        if not is_sketch(obj):
            return
        part = util.part_of(obj)
        if part is None:
            return
        keep_model_visible(obj)
        user = _first_user(part, obj)
        if user is None or getattr(user, "RolledBack", False):
            return          # no feature uses it yet, or it is already rolled back
        self.rolled[obj.Name] = (part, part.Tip)
        QtCore.QTimer.singleShot(0, lambda: self._roll(part, user.BaseFeature))

    @staticmethod
    def _roll(part, feat):
        try:
            part_mod.roll_to(part, feat)
            part.Document.recompute()
        except Exception as e:
            util.console_warning("could not roll back for the sketch: {}".format(e))

    def slotResetEdit(self, vobj):
        try:
            obj = vobj.Object
            name = obj.Name
        except Exception:
            return
        entry = self.rolled.pop(name, None)
        if entry is None:
            return
        part, tip = entry

        def restore():
            try:
                part_mod.roll_to(part, tip)
                part.Document.recompute()
            except Exception as e:
                util.console_warning("could not roll forward after the sketch: {}".format(e))
        QtCore.QTimer.singleShot(0, restore)


def feature_before(part, obj):
    """The last feature above *obj* in the part's history, or None."""
    group = list(part.Group)
    if obj not in group:
        return part.Tip
    feats = [o for o in group[:group.index(obj)] if util.is_feature(o)]
    return feats[-1] if feats else None


def _links(sketch):
    out = []
    for o, subs in sketch.ExternalGeometry:
        subs = subs if isinstance(subs, (list, tuple)) else [subs]
        for sub in (subs or [""]):
            out.append((o, sub))
    return out


def _defining(sketch, j):
    """Whether the j-th external link was added as defining geometry."""
    try:
        import Sketcher
        return bool(Sketcher.ExternalGeometryFacade(sketch.ExternalGeo[2 + j]).testFlag(
            "Defining"))
    except Exception:
        return False


def remap_external(sketch):
    """Point the sketch's new links to bodies at the feature above it. Returns the
    number of links moved.

    The Sketcher doesn't let its links be rewritten, so the links just added
    (the last ones) are removed and added again on the feature, in order, with
    the same projection or intersection and defining flags. Nothing is
    constrained to them yet.
    """
    part = util.part_of(sketch)
    if part is None or "ExternalGeometry" not in sketch.PropertiesList:
        return 0
    links = _links(sketch)
    k = len(links)
    while k > 0 and util.is_body_view(links[k - 1][0]):
        k -= 1
    trail = links[k:]
    if not trail:
        return 0
    base = feature_before(part, sketch)
    if base is None:
        return 0
    from .selection import map_to_feature
    types = list(sketch.ExternalTypes)
    flags = [(_defining(sketch, k + i), (types[k + i] == 1) if k + i < len(types) else False)
             for i in range(len(trail))]
    targets = []
    for o, sub in trail:
        try:
            name = map_to_feature(o.getSubObject(sub), base)
        except Exception:
            name = None
        if not name:
            util.console_warning("{}: {} {} is made by a later feature; the sketch can't "
                                 "follow it.".format(sketch.Label, part_mod.clean_label(o.Label),
                                                     sub))
            return 0
        targets.append(name)
    for _ in trail:
        sketch.delExternal(len(sketch.ExternalGeo) - 3)     # the last external geometry
    for name, (defining, inter) in zip(targets, flags):
        sketch.addExternal(base.Name, name, defining, inter)
    sketch.recompute()
    return len(trail)


class _AppObserver(object):
    def slotChangedObject(self, obj, prop):
        if prop != "ExternalGeometry" or not is_sketch(obj):
            return
        try:
            doc = obj.Document
            if doc.Restoring or doc.Transacting:
                return
            if not any(util.is_body_view(o) for o, _s in obj.ExternalGeometry):
                return
        except Exception:
            return
        name, doc_name = obj.Name, doc.Name

        def later():
            try:
                sk = App.getDocument(doc_name).getObject(name)
            except Exception:
                return
            if sk is not None:
                remap_external(sk)
        QtCore.QTimer.singleShot(0, later)


_observer = [None]


def install():
    if _observer[0] is None:
        _observer[0] = (_Observer(), _AppObserver())
        Gui.addDocumentObserver(_observer[0][0])
        App.addDocumentObserver(_observer[0][1])


