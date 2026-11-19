# SPDX-License-Identifier: LGPL-2.1-or-later
"""Instant3D outside the panels: select an Extrude or a Revolve (in the tree or
the 3D view) and its depth arrows or angle rings show on the model; a Fillet's
radius, a Chamfer's distance, a Shell's thickness and a Blind hole's depth get an
arrow too. Drag one, or
click its value and type, and the feature changes when you let go (one undo
step), as SolidWorks' Instant3D does.
"""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore

from ..app import part as part_mod
from ..app import util
from . import handles as hmod


class _Instant3D(object):
    def __init__(self):
        self.obj = None
        self.set = None
        self._timer = QtCore.QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.update)

    # Selection observer
    def addSelection(self, doc, obj, sub, pnt):
        self._timer.start()

    def removeSelection(self, doc, obj, sub):
        self._timer.start()

    def setSelection(self, doc):
        self._timer.start()

    def clearSelection(self, doc):
        self._timer.start()

    # ------------------------------------------------------------------
    def target(self):
        """The one feature selected that has handles, or None."""
        if Gui.Control.activeDialog():
            return None
        try:
            sel = Gui.Selection.getSelectionEx()
        except Exception:
            return None
        objs = []
        for s in sel:
            o = s.Object
            if util.is_body_view(o):
                continue
            if o not in objs:
                objs.append(o)
        if len(objs) != 1:
            return None
        o = objs[0]
        t = getattr(getattr(o, "Proxy", None), "TYPE", "")
        if t not in ("Extrude", "Revolve") and t not in hmod.SPECS or not util.is_feature(o):
            return None
        if getattr(o, "RolledBack", False) or getattr(o, "Suppressed", False) or o.ErrorMessage:
            return None
        return o

    def update(self):
        if self.set is not None and (self.set.active is not None or self._held):
            return          # a drag is on: clicking the arrow may change the selection
        o = self.target()
        if o is self.obj and self.set is not None:
            return
        self.clear()
        if o is None:
            return
        self.obj = o
        part = part_mod.owner_part(o) if hasattr(part_mod, "owner_part") else None
        part = part or util.part_of(o)
        s = hmod.Handles()
        t = o.Proxy.TYPE
        if t == "Extrude" or t in hmod.SPECS:
            specs = hmod.extrude_specs if t == "Extrude" else hmod.SPECS[t]
            for prop, origin, d, value, factor, scale in specs(o, part):
                a = s.add(hmod.DragArrow(lambda v: None))
                a.prop = prop
                a.factor = factor
                a.place(origin, d, value, scale)
                a.attach()
        else:
            for prop, centre, axis, ref, radius, value in hmod.revolve_specs(o, part):
                r = s.add(hmod.RingHandle(lambda v: None))
                r.prop = prop
                r.place(centre, axis, ref, radius, value)
                r.attach()
        if not s.arrows:
            return
        s.on_release = self.release
        s.listen()
        self.set = s

    _held = False

    def release(self, h):
        """A drag (or a typed value) is done: change the feature, as one undo step."""
        o = self.obj
        if o is None or getattr(o, "Document", None) is None:
            return
        self._held = True
        QtCore.QTimer.singleShot(0, lambda: self._apply(o, h))

    def _apply(self, o, h):
        self._held = False
        try:
            cur = getattr(o, h.prop).Value
        except Exception:
            return
        if abs(cur - h.value) < 1e-9:
            return
        doc = o.Document
        doc.openTransaction("Change {}".format(h.prop))
        try:
            setattr(o, h.prop, h.value)
            doc.recompute()
        finally:
            doc.commitTransaction()
        # The model moved: put the handles where the feature now is, on the feature
        # (the click may have selected something else).
        self.clear()
        try:
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(o)
        except Exception:
            pass
        self._timer.start()

    def clear(self):
        if self.set is not None:
            self.set.stop()
        self.set = None
        self.obj = None


_inst = [None]


def install():
    if _inst[0] is None:
        _inst[0] = _Instant3D()
        Gui.Selection.addObserver(_inst[0])


def current():
    return _inst[0]
