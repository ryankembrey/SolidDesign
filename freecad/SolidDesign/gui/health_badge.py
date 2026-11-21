# SPDX-License-Identifier: LGPL-2.1-or-later
"""The model's health in the status bar, always in sight: "No problems", or how
many errors and warnings, with the colour of the worst. A click opens What's
Wrong. It follows each rebuild and the document shown; it is there only for
documents with a Solid Design part."""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from ..app import health
from ..app import part as part_mod

_badge = [None]


def _make():
    class Badge(QtWidgets.QToolButton):
        def __init__(self):
            super(Badge, self).__init__()
            self.setObjectName("SD_HealthBadge")
            self.setAutoRaise(True)
            self.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
            self.setCursor(QtCore.Qt.PointingHandCursor)
            self.clicked.connect(self.open)
            self.counts = (0, 0)
            self.timer = QtCore.QTimer(self)
            self.timer.setSingleShot(True)
            self.timer.setInterval(150)
            self.timer.timeout.connect(self.update_now)

        def open(self):
            if Gui.Control.activeDialog():
                from . import evaluate
                if isinstance(evaluate.LAST[0], evaluate.WhatsWrongDialog) and \
                        evaluate.LAST[0].form.isVisible():
                    return
                try:
                    Gui.getMainWindow().statusBar().showMessage(
                        "Close the open tool first to see What's Wrong.", 5000)
                except Exception:
                    pass
                return
            Gui.runCommand("SD_WhatsWrong")

        def update_now(self):
            doc = App.ActiveDocument
            if doc is None or not part_mod.find_parts(doc):
                self.hide()
                return
            try:
                e, w = health.counts(doc)
            except Exception:
                return
            self.counts = (e, w)
            st = self.style()
            if e:
                ic = QtWidgets.QStyle.SP_MessageBoxCritical
            elif w:
                ic = QtWidgets.QStyle.SP_MessageBoxWarning
            else:
                ic = QtWidgets.QStyle.SP_DialogApplyButton
            self.setIcon(st.standardIcon(ic))
            words = []
            if e:
                words.append("{} error{}".format(e, "s" if e > 1 else ""))
            if w:
                words.append("{} warning{}".format(w, "s" if w > 1 else ""))
            self.setText(", ".join(words) if words else "No problems")
            self.setToolTip("What's Wrong: {}. Click to see them and fix them.".format(
                " and ".join(words)) if words else
                "Every feature rebuilt cleanly. Click for What's Wrong (and a geometry "
                "check).")
            self.show()

    return Badge()


class _Watch(object):
    def slotRecomputedDocument(self, doc):
        schedule()

    def slotDeletedDocument(self, doc):
        schedule()

    def slotCreatedDocument(self, doc):
        schedule()

    def slotActivateDocument(self, doc):
        schedule()


_watch = [None]


def schedule():
    b = current()
    if b is not None:
        b.timer.start()


def current():
    from .command_line import _alive
    return _badge[0] if _alive(_badge[0]) else None


def install():
    if current() is not None:
        return
    try:
        bar = Gui.getMainWindow().statusBar()
    except Exception:
        return
    b = _badge[0] = _make()
    bar.addPermanentWidget(b)
    b.hide()
    if _watch[0] is None:
        _watch[0] = _Watch()
        App.addDocumentObserver(_watch[0])
        try:
            mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
            mdi.subWindowActivated.connect(lambda _w: schedule())
        except Exception:
            pass
    schedule()
