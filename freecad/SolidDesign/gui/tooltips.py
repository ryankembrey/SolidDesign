# SPDX-License-Identifier: LGPL-2.1-or-later
"""Clean tooltips on the drop-down toolbar buttons (Reference Geometry, Patterns,
Curves, More Surfaces, Flex/Scale).

FreeCAD wraps a drop-down group's tooltip around its current command's tooltip,
which already has its title, so the name shows twice. Each such button gets its
current command's own tooltip instead, again whenever FreeCAD changes it (a
different command picked from the drop-down)."""

import re

import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

GROUPS = ("SD_ReferenceGeometry", "SD_Patterns", "SD_Curves", "SD_MoreSurfaces", "SD_Deform")
_NAME = re.compile(r"<i>(SD_\w+)</i>")


def _child(tip):
    for n in _NAME.findall(tip or ""):
        if n not in GROUPS:
            return n
    return None


def clean(action):
    """Give a group's toolbar action its current command's tooltip."""
    tip = action.toolTip()
    if not any("<i>{}</i>".format(g) in tip for g in GROUPS):
        return
    child = _child(tip)
    if child is None:
        return
    try:
        own = Gui.Command.get(child).getAction()[0].toolTip()
    except Exception:
        return
    if own and own != tip:
        action.setToolTip(own)


def _hook(action):
    if action.property("sdTipHooked"):
        return
    action.setProperty("sdTipHooked", True)
    action.changed.connect(lambda a=action: clean(a))


def fix_all():
    mw = Gui.getMainWindow()
    for tb in mw.findChildren(QtWidgets.QToolBar):
        for a in tb.actions():
            if any("<i>{}</i>".format(g) in a.toolTip() for g in GROUPS):
                _hook(a)
                clean(a)


def install():
    """After the toolbars are made (they are when the workbench activates)."""
    QtCore.QTimer.singleShot(0, fix_all)
