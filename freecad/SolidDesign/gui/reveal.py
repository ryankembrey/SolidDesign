# SPDX-License-Identifier: LGPL-2.1-or-later
"""Hidden reference geometry shows while it is selected, as in SolidWorks: click
a hidden plane, axis, point or coordinate system in the tree (an origin one, or
one made with the reference geometry tools) and it shows in the 3D view, in the
selection colour, until it is no longer selected.

Only what is drawn changes: the object's display switch is turned on, not its
Visibility property, so the document isn't changed (nothing to save, nothing to
undo) and the object stays hidden as far as everything else is concerned.
"""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore

from ..app import util

#: Part datums the origin is made of.
_DATUMS = ("Part::DatumPlane", "Part::DatumLine", "Part::DatumPoint")


def is_reference(obj):
    """A plane, axis, point, coordinate system or curve made with the reference
    geometry tools, or one of a Solid Design part's origin planes, axes and point."""
    if obj is None:
        return False
    if util.role(obj) == "refgeom":
        return True
    if obj.TypeId in _DATUMS:
        for o in obj.InList:
            if util.is_part(o) and obj in (getattr(o, "Origin", None) or []):
                return True
    return False


class _Reveal(object):
    def __init__(self):
        self.shown = {}         # (doc, name) -> the view object, shown by us
        self._timer = QtCore.QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.update)

    # Selection observer: work out what to show once the selection has settled.
    def addSelection(self, doc, obj, sub, pnt):
        self._timer.start()

    def removeSelection(self, doc, obj, sub):
        self._timer.start()

    def setSelection(self, doc):
        self._timer.start()

    def clearSelection(self, doc):
        self._timer.start()

    def update(self):
        want = {}
        try:
            sel = Gui.Selection.getSelection()
        except Exception:
            sel = []
        for o in sel:
            vo = getattr(o, "ViewObject", None)
            if vo is None or not is_reference(o):
                continue
            key = (o.Document.Name, o.Name)
            if key in self.shown or not vo.Visibility:
                want[key] = vo
        for key in [k for k in self.shown if k not in want]:
            self._hide(key, self.shown.pop(key))
        for key, vo in want.items():
            if key not in self.shown and self._show(vo):
                self.shown[key] = vo

    @staticmethod
    def _show(vo):
        try:
            sw = vo.SwitchNode
            if sw.whichChild.getValue() >= 0:
                return False            # drawn already
            sw.whichChild = vo.DefaultMode
            return True
        except Exception as e:
            App.Console.PrintLog("Solid Design: showing a selected reference: {}\n".format(e))
            return False

    @staticmethod
    def _hide(key, vo):
        try:
            if App.getDocument(key[0]).getObject(key[1]) is None:
                return
            if vo.Visibility:
                return                  # shown for good meanwhile: leave it
            vo.SwitchNode.whichChild = -1
        except Exception:
            pass                        # its document or object is gone


_inst = [None]


def install():
    if _inst[0] is None:
        _inst[0] = _Reveal()
        Gui.Selection.addObserver(_inst[0])


def current():
    return _inst[0]
