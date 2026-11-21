# SPDX-License-Identifier: LGPL-2.1-or-later
"""The context toolbar (SolidWorks' context toolbar): click a face, edge or vertex
of a body in the 3D view and a small bar of the tools that fit it shows by the
pointer. It fades as the pointer moves away and goes when it's far, when the
selection changes, or when a tool starts. Turn it off in Solid Design > Context
Toolbar.
"""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from ..app import part as part_mod
from ..app import util

PARAMS = "User parameter:BaseApp/Preferences/Mod/SolidDesign"
FADE_FROM = 30.0        # px from the bar where it starts to fade
GONE_AT = 170.0         # px from the bar where it goes

PLANAR_FACE = ["edit", "SD_Sketch", "SD_HoleWizard", "SD_Fillet", "SD_Shell", "SD_MoveFace",
               "SD_Plane"]
CURVED_FACE = ["edit", "SD_Fillet", "SD_Shell", "SD_MoveFace", "SD_DeleteFace", "SD_Axis"]
EDGE = ["edit", "SD_Fillet", "SD_Chamfer", "SD_Axis", "SD_Plane"]
VERTEX = ["SD_Chamfer", "SD_Point", "SD_Plane"]


def enabled():
    return App.ParamGet(PARAMS).GetBool("ContextToolbar", True)


def set_enabled(on):
    App.ParamGet(PARAMS).SetBool("ContextToolbar", bool(on))
    if not on and _inst[0] is not None:
        _inst[0].hide()


def tools_for(element):
    """The command names (and "edit") the bar offers for a picked element."""
    if element is None:
        return []
    t = element.ShapeType
    if t == "Face":
        try:
            planar = element.Surface.TypeId == "Part::GeomPlane"
        except Exception:
            planar = False
        return list(PLANAR_FACE if planar else CURVED_FACE)
    if t == "Edge":
        return list(EDGE)
    if t == "Vertex":
        return list(VERTEX)
    return []


def _info(name):
    try:
        return Gui.Command.get(name).getInfo()
    except Exception:
        return {}


class ContextBar(QtWidgets.QFrame):
    """A child of the main window, not a window of its own: Wayland ignores where an
    app moves its own top-level windows and can't fade them (Qt prints "This plugin
    does not support setting window opacity"), so it floats inside the main window
    and fades with an opacity effect, which works on every platform."""

    def __init__(self):
        super(ContextBar, self).__init__(Gui.getMainWindow())
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setFrameShadow(QtWidgets.QFrame.Raised)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.lay = QtWidgets.QHBoxLayout(self)
        self.lay.setContentsMargins(3, 3, 3, 3)
        self.lay.setSpacing(1)
        self.buttons = []
        self.feature = None
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(60)
        self.timer.timeout.connect(self._follow)
        self.setAutoFillBackground(True)
        self.fade = QtWidgets.QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.fade)
        self.set_opacity(1.0)
        self.hide()

    def set_opacity(self, v):
        self.fade.setOpacity(v)
        self.fade.setEnabled(v < 0.999)     # fully shown: draw it plainly

    def opacity(self):
        return self.fade.opacity() if self.fade.isEnabled() else 1.0

    # ---- contents
    def fill(self, tools, feature):
        for b in self.buttons:
            self.lay.removeWidget(b)
            b.deleteLater()
        self.buttons = []
        self.feature = feature
        for name in tools:
            if name == "edit":
                if feature is None:
                    continue
                b = self._button(name, "Edit Feature",
                                 u"Edit {}, the feature that made this".format(feature.Label),
                                 _feature_icon(feature))
            else:
                info = _info(name)
                if not info:
                    continue
                b = self._button(name, info.get("menuText", name), info.get("toolTip", ""),
                                 QtGui.QIcon(info.get("pixmap", "")))
            self.lay.addWidget(b)
            self.buttons.append(b)
        self.adjustSize()
        return bool(self.buttons)

    def _button(self, name, text, tip, ic):
        b = QtWidgets.QToolButton(self)
        b.setIcon(ic)
        b.setIconSize(QtCore.QSize(24, 24))
        b.setAutoRaise(True)
        b.setToolTip(u"{}: {}".format(text.replace("&", ""), tip) if tip else text)
        b.setFocusPolicy(QtCore.Qt.NoFocus)
        b.name = name
        b.clicked.connect(lambda _c=False, n=name: self.run(n))
        return b

    def run(self, name):
        self.hide()
        if name == "edit":
            f = self.feature
            if f is not None and getattr(f, "ViewObject", None) is not None:
                try:
                    f.ViewObject.Proxy.doubleClicked(f.ViewObject)
                except Exception:
                    Gui.ActiveDocument.setEdit(f.Name, 0)
            return
        Gui.runCommand(name)

    # ---- showing and fading
    def show_at(self, pos):
        """Shows the bar up and right of `pos` (global), kept inside the main window."""
        host = self.parentWidget()
        size = self.sizeHint()
        p = host.mapFromGlobal(pos) + QtCore.QPoint(18, -size.height() - 14)
        p.setX(max(0, min(p.x(), host.width() - size.width())))
        p.setY(max(0, min(p.y(), host.height() - size.height())))
        self.move(p)
        self.set_opacity(1.0)
        self.show()
        self.raise_()
        self.timer.start()

    def hide(self):
        try:
            self.timer.stop()
        except Exception:
            pass
        super(ContextBar, self).hide()

    def global_rect(self):
        return QtCore.QRect(self.mapToGlobal(QtCore.QPoint(0, 0)), self.size())

    def distance(self, p):
        """Pixels from the global point `p` to the bar (0 inside it)."""
        r = self.global_rect()
        dx = max(r.left() - p.x(), 0, p.x() - r.right())
        dy = max(r.top() - p.y(), 0, p.y() - r.bottom())
        return (dx * dx + dy * dy) ** 0.5

    def _follow(self):
        if Gui.Control.activeDialog():
            self.hide()
            return
        d = self.distance(QtGui.QCursor.pos())
        if d > GONE_AT:
            self.hide()
            return
        self.set_opacity(1.0 if d <= FADE_FROM else
                         max(0.15, 1.0 - (d - FADE_FROM) / (GONE_AT - FADE_FROM)))


def _feature_icon(feature):
    try:
        return QtGui.QIcon(feature.ViewObject.Proxy.getIcon())
    except Exception:
        return QtGui.QIcon()


class _Observer(object):
    """Shows the bar for a pick in the 3D view; hides it when the selection changes."""

    def __init__(self):
        self.bar = None
        self._pending = None
        self._timer = QtCore.QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._show)

    def addSelection(self, doc, obj, sub, pnt):
        self.hide()
        if not enabled() or not sub or not sub.startswith(("Face", "Edge", "Vertex")):
            return
        try:
            from . import command_line
            bar = command_line.current()
            if bar is not None and bar.isVisible():
                return          # picked by letters on the command line
        except Exception:
            pass
        self._pending = (doc, obj, sub)
        self._timer.start()

    def removeSelection(self, doc, obj, sub):
        self.hide()

    def setSelection(self, doc):
        self.hide()

    def clearSelection(self, doc):
        self.hide()

    def hide(self):
        if self.bar is not None:
            self.bar.hide()

    def _show(self):
        if self._pending is None:
            return
        docname, name, sub = self._pending
        self._pending = None
        if Gui.Control.activeDialog():
            return
        try:
            gdoc = Gui.getDocument(docname)
            if gdoc is not None and gdoc.getInEdit() is not None:
                return          # sketching or editing: not here
        except Exception:
            pass
        doc = App.getDocument(docname)
        obj = doc.getObject(name) if doc else None
        if obj is None or not util.is_body_view(obj):
            return
        try:
            elem = obj.Shape.getElement(sub)
        except Exception:
            return
        tools = tools_for(elem)
        feature = None
        if "edit" in tools and elem.ShapeType != "Vertex":
            try:
                from . import selection as selmod
                part = part_mod.source_part(obj)
                feature = selmod.feature_of_element(part, elem) if part is not None else None
            except Exception:
                feature = None
        if self.bar is None:
            self.bar = ContextBar()
        if self.bar.fill(tools, feature):
            self.bar.show_at(QtGui.QCursor.pos())


_inst = [None]


def install():
    if _inst[0] is None:
        _inst[0] = _Observer()
        Gui.Selection.addObserver(_inst[0])


def current():
    return _inst[0]


class ToggleCommand(object):
    """Solid Design > Context Toolbar: on or off (kept between sessions)."""

    def GetResources(self):
        from .. import icon
        return {"Pixmap": icon("ContextToolbar"), "MenuText": "Context Toolbar",
                "ToolTip": "Shows the tools that fit a face, edge or vertex by the pointer "
                           "when you click it.",
                "Checkable": enabled()}

    def IsActive(self):
        return True

    def Activated(self, checked=None):
        set_enabled(not enabled() if checked is None else bool(checked))
