# SPDX-License-Identifier: LGPL-2.1-or-later
"""Evaluate tools that aren't features: What's Wrong and Force Rebuild.

Measure, Mass Properties and variables (VarSet) are FreeCAD's own, on its
toolbars whatever the workbench.
"""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from .. import icon
from ..app import part as part_mod
from ..app import util
from .panel import parts

LAST = [None]       # the open dialog (for tests)


class _Dialog(object):
    """A task panel that isn't a feature's: a form of groups."""

    TITLE = ""
    ICON_NAME = ""

    def __init__(self, doc):
        self.doc = doc
        LAST[0] = self
        self.form, self.layout = parts.panel_form(self.TITLE, icon(self.ICON_NAME))
        self.error = parts.Message("error")
        self.layout.addWidget(self.error)
        self.build()
        self.layout.addStretch(1)

    def group(self, title, tip=""):
        g = parts.Group(title, tip)
        self.layout.addWidget(g)
        return g


# ====================================================================== what's wrong

def problems(doc):
    """[(feature, "error" or "warning", text)] of every part's features, in order."""
    out = []
    for part in part_mod.find_parts(doc):
        for f in util.features(part):
            if getattr(f, "RolledBack", False) or getattr(f, "Suppressed", False):
                continue
            if getattr(f, "ErrorMessage", ""):
                out.append((f, "error", f.ErrorMessage))
            elif getattr(f, "WarningMessage", ""):
                out.append((f, "warning", f.WarningMessage))
    return out


def force_rebuild(doc):
    """Rebuild every feature from scratch (SolidWorks' Force Rebuild)."""
    for o in doc.Objects:
        if util.is_feature(o) or o.TypeId.startswith("Sketcher::SketchObject"):
            o.touch()
    doc.recompute()


class WhatsWrongDialog(_Dialog):
    """SolidWorks' What's Wrong: every feature with an error or a warning; double-click
    one to edit it. Rebuild rebuilds everything first."""

    TITLE = "What's Wrong"
    ICON_NAME = "WhatsWrong"

    def __init__(self, doc):
        super(WhatsWrongDialog, self).__init__(doc)
        self.reload()

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Close

    def build(self):
        g = self.group("Errors and Warnings", "Features that failed or need a look")
        self.list = QtWidgets.QListWidget()
        self.list.setWordWrap(True)
        self.list.setMinimumHeight(220)
        g.wide(self.list, "Double-click a feature to edit it")
        self.list.itemDoubleClicked.connect(self._edit)
        self.rebuild = QtWidgets.QPushButton("Rebuild All")
        self.rebuild.setToolTip("Rebuild every feature from scratch, then list again")
        self.rebuild.clicked.connect(self._rebuild)
        g.wide(self.rebuild)

    def reload(self):
        self.items = problems(self.doc)
        self.list.clear()
        st = self.list.style()
        for f, kind, text in self.items:
            it = QtWidgets.QListWidgetItem(u"{}: {}".format(f.Label, text))
            it.setIcon(st.standardIcon(QtWidgets.QStyle.SP_MessageBoxCritical if kind == "error"
                                       else QtWidgets.QStyle.SP_MessageBoxWarning))
            it.setToolTip(text)
            self.list.addItem(it)
        if not self.items:
            it = QtWidgets.QListWidgetItem("Nothing is wrong: every feature rebuilt cleanly.")
            it.setFlags(QtCore.Qt.NoItemFlags)
            self.list.addItem(it)

    def _rebuild(self):
        force_rebuild(self.doc)
        self.reload()

    def _edit(self, item):
        i = self.list.row(item)
        if not 0 <= i < len(self.items):
            return
        f = self.items[i][0]
        Gui.Control.closeDialog()
        QtCore.QTimer.singleShot(0, lambda: f.ViewObject.Proxy.doubleClicked(f.ViewObject))

    def reject(self):
        Gui.Control.closeDialog()
        return True

    accept = reject


# ====================================================================== commands

class WhatsWrongCommand(object):
    def GetResources(self):
        return {"Pixmap": icon("WhatsWrong"), "MenuText": "What's Wrong",
                "ToolTip": "Lists the features with errors or warnings; double-click one to "
                           "edit it."}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        Gui.Control.showDialog(WhatsWrongDialog(App.ActiveDocument))


class RebuildCommand(object):
    def GetResources(self):
        return {"Pixmap": icon("Rebuild"), "MenuText": "Force Rebuild",
                "ToolTip": "Rebuilds every feature from scratch."}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        force_rebuild(App.ActiveDocument)


def register():
    Gui.addCommand("SD_WhatsWrong", WhatsWrongCommand())
    Gui.addCommand("SD_Rebuild", RebuildCommand())
