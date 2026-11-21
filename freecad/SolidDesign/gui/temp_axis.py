# SPDX-License-Identifier: LGPL-2.1-or-later
"""Temporary axes: rest the pointer on a round face (cylinder, cone, torus) or a
circular edge or arc of a body for 3 seconds, and its axis is drawn as a dashed
line, on top of the model. It stays 3 seconds after the pointer leaves, then
fades away.

The wait follows the axis, not the exact face or edge: a hand never holds still,
so the pointer slips between a cylinder's face, its rim and its seam, or briefly
onto a neighbouring face. Elements of the same body on the same axis count as
one, and slips shorter than GRACE_MS don't restart the wait.

Wherever a tool asks for an axis (Revolve, Circular Pattern, Move/Copy's
rotation, Axis), clicking that face or edge uses this axis, so there is no need
to make an Axis first.

The axis itself can be clicked: it is picked (drawn green) and stays until it is
used or something else is clicked. With a tool open, the click puts it in the
tool's axis box; with none, the next tool that asks for an axis starts with it.
"""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore

from ..app import util
from ..core import refgeom as core_ref

DWELL_MS = 3000         # resting on the same face or edge this long shows its axis
LINGER_MS = 3000        # it stays this long after the pointer leaves,
FADE_MS = 400           # then fades out over this long
FADE_STEPS = 10
GRACE_MS = 700          # a slip off it shorter than this doesn't restart the wait
COLOR = (0.15, 0.35, 0.75)
PICKED_COLOR = (0.11, 0.68, 0.11)     # FreeCAD's selection green
HIT_PX = 6.0            # a click this near the dashed line picks the axis
CLICK_PX = 6            # a press and release this near is a click, not a drag


def axis_segment(shape):
    """(start, end) of the temporary axis for a round face or circular edge, long
    enough to show past the element, or None."""
    ax = core_ref.axis_of_element(shape)
    if ax is None:
        return None
    p, d = ax
    bb = shape.BoundBox
    corners = [App.Vector(x, y, z) for x in (bb.XMin, bb.XMax) for y in (bb.YMin, bb.YMax)
               for z in (bb.ZMin, bb.ZMax)]
    ts = [(c - p).dot(d) for c in corners]
    lo, hi = min(ts), max(ts)
    span = hi - lo
    if span < 1e-6 or shape.ShapeType == "Edge":
        # A flat circle (or ring): show the axis on both sides of its plane.
        r = max(bb.DiagonalLength * 0.4, 2.0)
        mid = sum(ts) / len(ts)
        lo, hi = mid - r, mid + r
    else:
        margin = max(span * 0.25, bb.DiagonalLength * 0.08, 1.0)
        lo, hi = lo - margin, hi + margin
    return p + d * lo, p + d * hi


def same_axis(a, b):
    """Whether two (start, end) segments lie on the same line."""
    (a0, a1), (b0, b1) = a, b
    da, db = a1 - a0, b1 - b0
    if da.Length < 1e-9 or db.Length < 1e-9:
        return False
    da, db = App.Vector(da).normalize(), App.Vector(db).normalize()
    tol = 1e-4 * max(1.0, (a1 - a0).Length)
    return da.cross(db).Length < 1e-6 and (b0 - a0).cross(da).Length < tol


def _now():
    return QtCore.QDateTime.currentMSecsSinceEpoch()


class _TempAxes(object):
    def __init__(self):
        self.node = None
        self.graph = None
        self.material = None
        self.key = None             # (doc, object) whose axis is shown
        self.seg = None             # and the shown axis
        self.sub = None             # the face or edge it is the axis of
        self.pinned = False         # clicked: stays until used or clicked off
        self.style = None
        self.hover = None           # waiting: [(doc, object), segment, since, away_since]
        self.dwell = self._timer(self._dwelt)
        self.timer = self._timer(self.fade)     # linger after the pointer leaves
        self.fader = QtCore.QTimer()
        self.fader.timeout.connect(self._fade_step)
        self._step = 0

    @staticmethod
    def _timer(slot):
        t = QtCore.QTimer()
        t.setSingleShot(True)
        t.timeout.connect(slot)
        return t

    # Selection observer -----------------------------------------------------
    def setPreselection(self, doc, obj, sub):
        QtCore.QTimer.singleShot(0, lambda: self.hovered(doc, obj, sub))

    def removePreselection(self, doc, obj, sub):
        QtCore.QTimer.singleShot(0, self.left)

    # ------------------------------------------------------------------------
    def hovered(self, doc_name, obj_name, sub):
        """The pointer is on an element: if it's on the shown axis, keep that; if
        it's round, wait to see whether the pointer rests on it."""
        if self.pinned:
            return                  # a picked axis stays; others wait for it to go
        owner = (doc_name, obj_name)
        seg = self._segment(doc_name, obj_name, sub)
        if seg is None:
            self.left()             # not round: like leaving
            return
        if self.node is not None and owner == self.key and same_axis(seg, self.seg):
            self._keep()
            self.hover = None
            self.dwell.stop()
            return
        h = self.hover
        if h is not None and h[0] == owner and same_axis(seg, h[1]) and (
                h[3] is None or _now() - h[3] <= GRACE_MS):
            h[3] = None             # back on it after a slip: keep waiting
            if not self.dwell.isActive():
                self.dwell.start(max(0, DWELL_MS - (_now() - h[2])))
            return
        self.hover = [owner, seg, _now(), None, sub]
        self.dwell.start(DWELL_MS)

    def left(self):
        if self.pinned:
            return
        if self.hover is not None and self.hover[3] is None:
            self.hover[3] = _now()
        if self.node is not None and not self.timer.isActive() \
                and not self.fader.isActive():
            self.timer.start(LINGER_MS)

    def _dwelt(self):
        h = self.hover
        if h is None:
            return
        away = h[3]
        if away is not None and _now() - away > GRACE_MS:
            self.hover = None       # it left for good
            return
        self.hover = None
        self.clear()
        self.key, self.seg, self.sub = h[0], h[1], h[4]
        self._draw(*h[1])
        if away is not None:        # in a slip right now: it may not come back
            self.timer.start(LINGER_MS)

    @staticmethod
    def _segment(doc_name, obj_name, sub):
        try:
            obj = App.getDocument(doc_name).getObject(obj_name)
        except Exception:
            return None
        if obj is None or not (util.is_body_view(obj) or util.is_feature(obj)) or not sub:
            return None
        try:
            el = obj.getSubObject(sub)
        except Exception:
            return None
        return axis_segment(el) if el is not None else None

    def show(self, doc_name, obj_name, sub):
        """Show an element's axis now (no waiting)."""
        seg = self._segment(doc_name, obj_name, sub)
        if seg is None:
            return
        self.hover = None
        self.dwell.stop()
        self.clear()
        self.key, self.seg, self.sub = (doc_name, obj_name), seg, sub
        self._draw(*seg)

    # Fading -------------------------------------------------------------------
    def _keep(self):
        """Back on the shown element: stop lingering or fading."""
        self.timer.stop()
        self.fader.stop()
        if self.material is not None:
            self.material.transparency.setValue(0.0)

    def fade(self):
        if self.node is None:
            return
        self._step = 0
        self.fader.start(max(1, FADE_MS // FADE_STEPS))

    def _fade_step(self):
        self._step += 1
        if self._step >= FADE_STEPS or self.material is None:
            self.clear()
            return
        self.material.transparency.setValue(float(self._step) / FADE_STEPS)

    def _draw(self, a, b):
        try:
            from pivy import coin
            view = Gui.ActiveDocument.ActiveView
            graph = view.getSceneGraph()
        except Exception:
            return
        node = coin.SoAnnotation()
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        col = coin.SoMaterial()
        col.diffuseColor.setValue(*COLOR)
        col.emissiveColor.setValue(*COLOR)
        col.transparency.setValue(0.0)
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        style = coin.SoDrawStyle()
        style.lineWidth = 1.6
        style.linePattern = 0xF0F0
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, 2, [(a.x, a.y, a.z), (b.x, b.y, b.z)])
        line = coin.SoLineSet()
        for n in (pick, light, col, style, coords, line):
            node.addChild(n)
        graph.addChild(node)
        self.node, self.graph, self.material, self.style = node, graph, col, style

    def clear(self):
        self.timer.stop()
        self.fader.stop()
        if self.node is not None and self.graph is not None:
            try:
                self.graph.removeChild(self.node)
            except Exception:
                pass
        self.node = self.graph = self.material = self.key = self.seg = None
        self.sub = self.style = None
        self.pinned = False

    # Picking the axis ---------------------------------------------------------
    def near(self, view, widget, x, y):
        """Whether (x, y), pixels in ``widget`` (the 3D view), is on the shown axis."""
        if self.node is None or self.seg is None:
            return False
        try:
            w, h = view.getSize()
            ratio = float(w) / max(1, widget.width())
            pts = []
            for p in self.seg:
                gx, gy = view.getPointOnViewport(p)
                pts.append((gx / ratio, (h - gy) / ratio))
        except Exception:
            return False
        (ax, ay), (bx, by) = pts
        dx, dy = bx - ax, by - ay
        ll = dx * dx + dy * dy
        t = 0.0 if ll < 1e-9 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / ll))
        px, py = ax + dx * t, ay + dy * t
        return ((x - px) ** 2 + (y - py) ** 2) ** 0.5 <= HIT_PX

    def source(self):
        """(object, sub) of the face or edge the shown axis belongs to, or None."""
        if self.key is None or not self.sub:
            return None
        try:
            obj = App.getDocument(self.key[0]).getObject(self.key[1])
        except Exception:
            return None
        return (obj, self.sub) if obj is not None else None

    def picked(self):
        """(object, sub) of the picked axis' face or edge, or None."""
        return self.source() if self.pinned else None

    def pick(self):
        """The axis was clicked: hold it, green. With a tool open it goes straight
        into the tool's axis box (and is used)."""
        if self.node is None:
            return
        self.pinned = True
        self.hover = None
        self.dwell.stop()
        self._keep()
        if self.material is not None:
            self.material.diffuseColor.setValue(*PICKED_COLOR)
            self.material.emissiveColor.setValue(*PICKED_COLOR)
        if self.style is not None:
            self.style.lineWidth = 2.6
        if Gui.Control.activeDialog():
            from .sketch_panel import LAST
            p = LAST[0]
            src = self.source()
            if p is not None and src is not None and hasattr(p, "offer_axis"):
                from .selection import Sel
                if p.offer_axis(Sel(src[0], src[1]), active_too=True):
                    self.used()

    def used(self):
        """A tool took the axis: it goes."""
        self.clear()

    def unpick(self):
        """Clicked off: it lets go and fades."""
        if not self.pinned:
            return
        self.pinned = False
        if self.material is not None:
            self.material.diffuseColor.setValue(*COLOR)
            self.material.emissiveColor.setValue(*COLOR)
        if self.style is not None:
            self.style.lineWidth = 1.6
        self.fade()


def _make_clicks():
    """Clicks in the 3D view: on the shown axis, pick it (the click goes no
    further, so nothing behind it is selected); anywhere else, let a picked axis
    go."""
    from PySide import QtWidgets

    class Clicks(QtCore.QObject):
        press = None

        def eventFilter(self, obj, ev):
            t = ev.type()
            if t not in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease):
                return False
            try:
                if ev.button() != QtCore.Qt.LeftButton or \
                        obj.metaObject().className() != "QOpenGLWidget":
                    return False
                ta = _temp[0]
                if ta is None or ta.node is None:
                    return False
                pos = ev.position() if hasattr(ev, "position") else ev.localPos()
                view = Gui.ActiveDocument.ActiveView
                if not hasattr(view, "getPointOnViewport"):
                    return False
            except Exception:
                return False
            on = ta.near(view, obj, pos.x(), pos.y())
            if t == QtCore.QEvent.MouseButtonPress:
                self.press = (pos.x(), pos.y(), on)
                return on               # ours: FreeCAD doesn't select behind it
            p, self.press = self.press, None
            if p is None:
                return False
            click = abs(pos.x() - p[0]) <= CLICK_PX and abs(pos.y() - p[1]) <= CLICK_PX
            if p[2]:
                if click:
                    QtCore.QTimer.singleShot(0, ta.pick)
                return True
            if click and ta.pinned:
                ta.unpick()             # clicked off it
            return False

    return Clicks()


_temp = [None]
_clicks = [None]


def install():
    if _temp[0] is None:
        _temp[0] = _TempAxes()
        Gui.Selection.addObserver(_temp[0])
    if _clicks[0] is None:
        from PySide import QtWidgets
        _clicks[0] = _make_clicks()
        QtWidgets.QApplication.instance().installEventFilter(_clicks[0])


def current():
    return _temp[0]
