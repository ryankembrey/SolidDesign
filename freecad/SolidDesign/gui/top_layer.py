# SPDX-License-Identifier: LGPL-2.1-or-later
"""A layer over a 3D view that stays in front of FreeCAD's overlaid docks.

With docks overlaid (View → Overlay), the tree and the task panel are children of
the main window raised over the 3D view, so anything inside the view's widget is
behind them. The command line's bar, its suggestions, its labels and its cheat
sheet live here instead: a child of the main window kept exactly over the view
and in front of the rest. Its coordinates are the view's.

The layer takes clicks only where one of its widgets is (its mask is theirs);
everywhere else they go to whatever is under it, as before.
"""

import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

#: How often the layer checks it is still in front and over the view (ms).
WATCH = 250

_layers = {}            # id(view widget) -> layer


def _alive(w):
    from .command_line import _alive as alive
    return alive(w)


class Layer(QtWidgets.QWidget):
    def __init__(self, view):
        super(Layer, self).__init__(Gui.getMainWindow())
        self.setObjectName("SD_TopLayer")
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.view = view
        view.installEventFilter(self)
        view.destroyed.connect(self._view_gone)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(WATCH)
        self.timer.timeout.connect(self._watch)
        self.hide()
        self.follow()

    # ---- the view's place
    def follow(self):
        """Over the view, exactly."""
        if not _alive(self.view):
            return
        mw = self.parentWidget()
        tl = self.view.mapTo(mw, QtCore.QPoint(0, 0))
        r = QtCore.QRect(tl, self.view.size())
        if r != self.geometry():
            self.setGeometry(r)

    def _view_gone(self, *_a):
        _layers.pop(getattr(self, "_key", None), None)
        self.deleteLater()

    def eventFilter(self, obj, ev):
        t = ev.type()
        if obj is self.view:
            if t in (QtCore.QEvent.Resize, QtCore.QEvent.Move):
                self.follow()
            elif t in (QtCore.QEvent.Show, QtCore.QEvent.Hide):
                self.refresh()
            return False
        if t in (QtCore.QEvent.ShowToParent, QtCore.QEvent.HideToParent,
                 QtCore.QEvent.Move, QtCore.QEvent.Resize):
            self.refresh()          # at once: a widget shown here can take the focus
        return False

    def childEvent(self, ev):
        if ev.type() == QtCore.QEvent.ChildAdded and isinstance(ev.child(), QtWidgets.QWidget):
            ev.child().installEventFilter(self)
        super(Layer, self).childEvent(ev)
        if ev.type() in (QtCore.QEvent.ChildAdded, QtCore.QEvent.ChildRemoved):
            QtCore.QTimer.singleShot(0, self.refresh)

    # ---- what shows
    def region(self):
        """Where its widgets are: their own masks if they have one; a widget that
        lets clicks through counts only where its mask says."""
        out = QtGui.QRegion()
        for c in self.children():
            if not isinstance(c, QtWidgets.QWidget) or c.isHidden():
                continue
            m = c.mask()
            if not m.isEmpty():
                out = out.united(m.translated(c.pos()))
            elif not c.testAttribute(QtCore.Qt.WA_TransparentForMouseEvents):
                out = out.united(QtGui.QRegion(c.geometry()))
        return out

    def refresh(self):
        if getattr(self, "_busy", False) or not _alive(self) or not _alive(self.view):
            return
        self._busy = True
        try:
            self._refresh()
        finally:
            self._busy = False

    def _refresh(self):
        r = self.region()
        if r.isEmpty() or not self.view.isVisible():
            self.timer.stop()
            self.hide()
            return
        self.follow()
        self.setMask(r)
        if self.isHidden():
            self.show()
        self.raise_()
        self.timer.start()

    def _watch(self):
        """FreeCAD raises its overlaid docks again now and then, and the view moves
        when docks change: keep up."""
        if not self.isVisible():
            self.timer.stop()
            return
        self.follow()
        mw = self.parentWidget()
        ws = [c for c in mw.children() if isinstance(c, QtWidgets.QWidget) and
              not c.isWindow() and c.isVisible()]
        if ws and ws[-1] is not self:
            self.raise_()


def for_view(view):
    """The layer over a 3D view's widget (made the first time)."""
    key = id(view)
    layer = _layers.get(key)
    if layer is None or not _alive(layer) or layer.view is not view:
        layer = Layer(view)
        layer._key = key
        _layers[key] = layer
    return layer


def view_of(widget):
    """The 3D view widget under a layer (or the widget itself)."""
    return getattr(widget, "view", widget)
