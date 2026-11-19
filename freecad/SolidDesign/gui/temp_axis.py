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
        self.hover = [owner, seg, _now(), None]
        self.dwell.start(DWELL_MS)

    def left(self):
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
        self.key, self.seg = h[0], h[1]
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
        self.key, self.seg = (doc_name, obj_name), seg
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
        self.node, self.graph, self.material = node, graph, col

    def clear(self):
        self.timer.stop()
        self.fader.stop()
        if self.node is not None and self.graph is not None:
            try:
                self.graph.removeChild(self.node)
            except Exception:
                pass
        self.node = self.graph = self.material = self.key = self.seg = None


_temp = [None]


def install():
    if _temp[0] is None:
        _temp[0] = _TempAxes()
        Gui.Selection.addObserver(_temp[0])


def current():
    return _temp[0]
