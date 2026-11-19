# SPDX-License-Identifier: LGPL-2.1-or-later
"""Drag handles in the 3D view (SolidWorks' Instant3D): arrows you drag to change
a length and rings you drag to change an angle, with the value shown beside
them. Clicking the value opens a box to type a new one.

An arrow sits where the length ends and points along it. Pressing on it and
dragging sets the length (snapped: 0.5 mm steps, 0.1 mm under 5 mm); the panel's
field follows, and the preview with it. Typing in the field moves the arrow.

The arrows are plain Coin geometry. The drag is read from FreeCAD's own view
event callbacks: Coin dragger callbacks called through pivy crash FreeCAD when a
real mouse drives them (they run without Python's lock).
"""

import FreeCAD as App
import FreeCADGui as Gui

ARROW_COLOR = (0.15, 0.40, 0.85)
HOT_COLOR = (0.95, 0.55, 0.10)
GRAB_PX = 9.0           # how near the pointer must be to the arrow to grab it


def snap(v):
    step = 0.1 if abs(v) < 5.0 else 0.5
    return round(v / step) * step


class DragArrow(object):
    """One arrow. ``on_drag(value)`` is called as it is dragged (value >= 0)."""

    def __init__(self, on_drag, label="", factor=1.0):
        from pivy import coin
        self.coin = coin
        self.on_drag = on_drag
        self.label = label
        self.factor = factor            # the value is factor x the arrow's distance
        self.scale = 1.0
        self.origin = App.Vector()
        self.direction = App.Vector(0, 0, 1)
        self.graph = None
        self.value = 0.0
        self.dragging = False
        self.root = coin.SoAnnotation()     # on top of the model and the preview
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        self.root.addChild(pick)
        self.xf = coin.SoTransform()
        self.root.addChild(self.xf)
        self.mat = coin.SoMaterial()
        self._colour(ARROW_COLOR)
        self.root.addChild(self.mat)
        self.slide = coin.SoTranslation()   # along the arrow: the value
        self.root.addChild(self.slide)
        self.root.addChild(self._arrow())
        self.text_xf = coin.SoTranslation()
        self.text_xf.translation.setValue(1.15, 0, 0)
        self.text = coin.SoText2()
        col = coin.SoBaseColor()
        col.rgb.setValue(0.1, 0.1, 0.1)
        font = coin.SoFont()
        font.size = 14
        for n in (col, font, self.text_xf, self.text):
            self.root.addChild(n)

    def _colour(self, c):
        self.mat.diffuseColor.setValue(*c)
        self.mat.emissiveColor.setValue(*[x * 0.4 for x in c])

    def _arrow(self):
        """An arrow along +X: a shaft from 0 to 0.8 and a cone to 1."""
        c = self.coin
        sep = c.SoSeparator()
        rot = c.SoRotationXYZ()
        rot.axis = c.SoRotationXYZ.Z
        rot.angle = -1.5707963
        sep.addChild(rot)                   # Y (Coin's cylinder and cone axis) onto X
        t1 = c.SoTranslation()
        t1.translation.setValue(0, 0.4, 0)
        sep.addChild(t1)
        cyl = c.SoCylinder()
        cyl.radius = 0.035
        cyl.height = 0.8
        sep.addChild(cyl)
        t2 = c.SoTranslation()
        t2.translation.setValue(0, 0.5, 0)
        sep.addChild(t2)
        cone = c.SoCone()
        cone.bottomRadius = 0.11
        cone.height = 0.2
        sep.addChild(cone)
        return sep

    # ------------------------------------------------------------ placing
    def place(self, origin, direction, value, scale):
        """Put the arrow's base at ``origin`` + the value along ``direction``."""
        if self.dragging:
            return
        d = App.Vector(direction)
        if d.Length < 1e-12:
            return
        d.normalize()
        self.origin, self.direction = App.Vector(origin), d
        self.scale = max(scale, 1e-6)
        q = App.Rotation(App.Vector(1, 0, 0), d).Q
        self.xf.translation.setValue(origin.x, origin.y, origin.z)
        self.xf.rotation.setValue(q[0], q[1], q[2], q[3])
        self.xf.scaleFactor.setValue(self.scale, self.scale, self.scale)
        self.set_value(value)

    def set_value(self, value):
        if self.dragging:
            return
        self._show(value)

    def _show(self, value):
        self.value = value
        self.slide.translation.setValue(value / self.factor / self.scale, 0, 0)
        txt = "{:g} mm".format(round(value, 4))
        self.text.string.setValue("{}: {}".format(self.label, txt) if self.label else txt)

    def label_point(self):
        """Where the value is written (the start of its text)."""
        return self.base() + self.direction * (1.15 * self.scale)

    def base(self):
        return self.origin + self.direction * (self.value / self.factor)

    def tip(self):
        return self.base() + self.direction * self.scale

    # ------------------------------------------------------------ dragging
    def grab(self, view, x, y):
        """Whether the pointer at (x, y) (view pixels) is on the arrow."""
        try:
            a = view.getPointOnViewport(self.base())
            b = view.getPointOnViewport(self.tip())
        except Exception:
            return False
        ax, ay, bx, by = float(a[0]), float(a[1]), float(b[0]), float(b[1])
        dx, dy = bx - ax, by - ay
        ll = dx * dx + dy * dy
        if ll < 1e-9:
            return (x - ax) ** 2 + (y - ay) ** 2 <= GRAB_PX ** 2
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / ll))
        px, py = ax + t * dx, ay + t * dy
        return (x - px) ** 2 + (y - py) ** 2 <= GRAB_PX ** 2

    def along(self, view, x, y):
        """How far along the arrow's line the pointer's ray passes closest."""
        try:
            p = view.getPoint(int(x), int(y))
            v = App.Vector(view.getViewDirection())
        except Exception:
            return None
        if v.Length < 1e-12:
            return None
        v.normalize()
        d = self.direction
        dv = d.dot(v)
        if abs(1 - dv * dv) < 1e-6:
            return None                     # looking straight down the arrow
        w = p - self.origin
        return (w.dot(d) - dv * w.dot(v)) / (1 - dv * dv)

    def start(self, view, x, y):
        s = self.along(view, x, y)
        if s is None:
            return False
        self.dragging = True
        self._grab_s = s
        self._grab_v = self.value
        self._colour(HOT_COLOR)
        return True

    def move(self, view, x, y):
        s = self.along(view, x, y)
        if s is None:
            return
        v = max(0.0, snap(self._grab_v + (s - self._grab_s) * self.factor))
        if abs(v - self.value) < 1e-9:
            return
        self._show(v)
        self.on_drag(v)

    def stop(self):
        self.dragging = False
        self._colour(ARROW_COLOR)

    # ------------------------------------------------------------ showing
    def attach(self):
        if self.graph is not None:
            return
        try:
            self.graph = Gui.ActiveDocument.ActiveView.getSceneGraph()
            self.graph.addChild(self.root)
        except Exception:
            self.graph = None

    def detach(self):
        if self.dragging:
            self.stop()
        if self.graph is not None:
            try:
                self.graph.removeChild(self.root)
            except Exception:
                pass
        self.graph = None

    def shown(self):
        return self.graph is not None


class RingHandle(object):
    """A ring for an angle round an axis: an arc from the start to the value, and a
    knob at its end to drag. ``on_drag(value)`` gets degrees (0 < value <= 360)."""

    def __init__(self, on_drag, label=""):
        from pivy import coin
        self.coin = coin
        self.on_drag = on_drag
        self.label = label
        self.graph = None
        self.value = 0.0
        self.dragging = False
        self.centre = App.Vector()
        self.axis = App.Vector(0, 0, 1)
        self.ref = App.Vector(1, 0, 0)
        self.radius = 10.0
        self.root = coin.SoAnnotation()
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        self.root.addChild(pick)
        self.mat = coin.SoMaterial()
        self.root.addChild(self.mat)
        style = coin.SoDrawStyle()
        style.lineWidth = 2.5
        self.root.addChild(style)
        self.coords = coin.SoCoordinate3()
        self.root.addChild(self.coords)
        self.line = coin.SoLineSet()
        self.root.addChild(self.line)
        knob = coin.SoSeparator()
        self.knob_xf = coin.SoTranslation()
        self.sphere = coin.SoSphere()
        knob.addChild(self.knob_xf)
        knob.addChild(self.sphere)
        self.root.addChild(knob)
        tsep = coin.SoSeparator()
        self.text_xf = coin.SoTranslation()
        self.text = coin.SoText2()
        col = coin.SoBaseColor()
        col.rgb.setValue(0.1, 0.1, 0.1)
        font = coin.SoFont()
        font.size = 14
        for n in (col, font, self.text_xf, self.text):
            tsep.addChild(n)
        self.root.addChild(tsep)
        self._colour(ARROW_COLOR)

    def _colour(self, c):
        self.mat.diffuseColor.setValue(*c)
        self.mat.emissiveColor.setValue(*[x * 0.4 for x in c])

    def place(self, centre, axis, ref, radius, value):
        if self.dragging:
            return
        a = App.Vector(axis)
        a.normalize()
        r = App.Vector(ref) - a * App.Vector(ref).dot(a)
        if r.Length < 1e-12:
            return
        r.normalize()
        self.centre, self.axis, self.ref = App.Vector(centre), a, r
        self.radius = max(radius, 1e-6)
        self.sphere.radius = self.radius * 0.06
        self.set_value(value)

    def set_value(self, value):
        if self.dragging:
            return
        self._show(value)

    def at(self, deg):
        rot = App.Rotation(self.axis, deg)
        return self.centre + rot.multVec(self.ref) * self.radius

    def knob(self):
        return self.at(self.value)

    def label_point(self):
        rot = App.Rotation(self.axis, self.value)
        return self.knob() + rot.multVec(self.ref) * (0.12 * self.radius)

    def _show(self, value):
        self.value = value
        n = max(2, int(abs(value) / 4.0) + 2)
        pts = [self.at(value * i / (n - 1)) for i in range(n)]
        self.coords.point.setNum(0)
        self.coords.point.setValues(0, len(pts), [(q.x, q.y, q.z) for q in pts])
        self.line.numVertices.setValue(len(pts))
        k = self.knob()
        self.knob_xf.translation.setValue(k.x, k.y, k.z)
        lp = self.label_point()
        self.text_xf.translation.setValue(lp.x, lp.y, lp.z)
        txt = u"{:g}\u00b0".format(round(value, 3))
        self.text.string.setValue("{}: {}".format(self.label, txt) if self.label else txt)

    # ------------------------------------------------------------ dragging
    def grab(self, view, x, y):
        try:
            k = view.getPointOnViewport(self.knob())
        except Exception:
            return False
        return (x - float(k[0])) ** 2 + (y - float(k[1])) ** 2 <= (1.6 * GRAB_PX) ** 2

    def angle(self, view, x, y):
        """The pointer's angle round the axis, from the ray meeting the ring's plane."""
        import math
        try:
            p = view.getPoint(int(x), int(y))
            v = App.Vector(view.getViewDirection())
        except Exception:
            return None
        v.normalize()
        den = v.dot(self.axis)
        if abs(den) < 1e-6:
            return None                 # the ring is edge-on
        q = p + v * ((self.centre - p).dot(self.axis) / den)
        w = q - self.centre
        y_dir = self.axis.cross(self.ref)
        return math.degrees(math.atan2(w.dot(y_dir), w.dot(self.ref)))

    def start(self, view, x, y):
        a = self.angle(view, x, y)
        if a is None:
            return False
        self.dragging = True
        self._last = a
        self._acc = self.value
        self._colour(HOT_COLOR)
        return True

    def move(self, view, x, y):
        a = self.angle(view, x, y)
        if a is None:
            return
        d = (a - self._last + 180.0) % 360.0 - 180.0
        self._last = a
        self._acc += d
        step = 1.0 if self._acc < 30 else 5.0
        v = min(360.0, max(step, round(self._acc / step) * step))
        if abs(v - self.value) < 1e-9:
            return
        self._show(v)
        self.on_drag(v)

    def stop(self):
        self.dragging = False
        self._colour(ARROW_COLOR)

    attach = DragArrow.attach
    detach = DragArrow.detach
    shown = DragArrow.shown


class Handles(object):
    """The arrows of one panel, and the mouse handling that drags them."""

    def __init__(self):
        self.arrows = []
        self.active = None
        self.view = None
        self._cbs = []

    def add(self, arrow):
        self.arrows.append(arrow)
        return arrow

    def listen(self):
        if self._cbs:
            return
        self._watch_release()
        try:
            from pivy import coin
            self.view = Gui.ActiveDocument.ActiveView
            self._cbs = [
                (coin.SoMouseButtonEvent.getClassTypeId(),
                 self.view.addEventCallbackPivy(coin.SoMouseButtonEvent.getClassTypeId(),
                                                self._button)),
                (coin.SoLocation2Event.getClassTypeId(),
                 self.view.addEventCallbackPivy(coin.SoLocation2Event.getClassTypeId(),
                                                self._motion)),
            ]
        except Exception:
            self._cbs = []

    def _watch_release(self):
        """FreeCAD's navigation takes the button release before the scene's event
        callbacks see it, so the end of a drag is caught on the view's widget."""
        from PySide import QtCore, QtWidgets
        handles = self

        class _Release(QtCore.QObject):
            def eventFilter(self, obj, ev):
                if ev.type() == QtCore.QEvent.MouseButtonRelease and \
                        ev.button() == QtCore.Qt.LeftButton and handles.active is not None:
                    QtCore.QTimer.singleShot(0, handles.end_drag)
                return False
        try:
            self._gl = [x for x in Gui.getMainWindow().findChildren(QtWidgets.QWidget)
                        if x.metaObject().className() == "QOpenGLWidget" and x.isVisible()][-1]
            self._release_filter = _Release()
            self._gl.installEventFilter(self._release_filter)
        except Exception:
            self._gl = None

    def end_drag(self):
        a = self.active
        if a is None:
            return
        a.stop()
        self.active = None
        if self.on_release is not None:
            self.on_release(a)

    def stop(self):
        if getattr(self, "_gl", None) is not None:
            try:
                self._gl.removeEventFilter(self._release_filter)
            except Exception:
                pass
            self._gl = None
        self.close_editor()
        for a in self.arrows:
            a.detach()
        if self.view is not None:
            for t, cb in self._cbs:
                try:
                    self.view.removeEventCallbackPivy(t, cb)
                except Exception:
                    pass
        self._cbs = []
        self.active = None

    on_release = None           # called with the handle when a drag ends

    def _button(self, node):
        from pivy import coin
        ev = node.getEvent()
        if ev.getButton() != coin.SoMouseButtonEvent.BUTTON1:
            return
        x, y = ev.getPosition().getValue()
        if ev.getState() == coin.SoButtonEvent.DOWN:
            for a in self.arrows:
                if a.shown() and self.on_label(a, x, y):
                    node.setHandled()
                    self.edit_value(a)
                    return
            for a in self.arrows:
                if a.shown() and a.grab(self.view, x, y) and a.start(self.view, x, y):
                    self.active = a
                    node.setHandled()
                    return
        elif self.active is not None:
            node.setHandled()
            self.end_drag()

    # ------------------------------------------------------------ typing a value
    def on_label(self, a, x, y):
        """Whether (x, y) is on the handle's value (its text starts at the anchor)."""
        try:
            q = self.view.getPointOnViewport(a.label_point())
        except Exception:
            return False
        qx, qy = float(q[0]), float(q[1])
        return qx - 4 <= x <= qx + 80 and qy - 6 <= y <= qy + 18

    def edit_value(self, a):
        """A box over the value to type a new one: Enter sets it, Escape doesn't."""
        from PySide import QtCore, QtWidgets
        self.close_editor()
        try:
            w = [x for x in Gui.getMainWindow().findChildren(QtWidgets.QWidget)
                 if x.metaObject().className() == "QOpenGLWidget" and x.isVisible()][-1]
            q = self.view.getPointOnViewport(a.label_point())
            h = self.view.getSize()[1]
        except Exception:
            return
        ed = QtWidgets.QLineEdit(w)
        ed.setText("{:g}".format(round(a.value, 4)))
        ed.setFixedWidth(90)
        ed.setToolTip("Type a value and press Enter (Escape: keep the old one)")
        ed.move(int(q[0]) - 4, int(h - q[1]) - 18)
        ed.selectAll()

        def apply():
            txt = ed.text().strip().lower().replace("mm", "").replace(u"\u00b0", "") \
                .replace("deg", "").strip()
            try:
                v = float(txt)
            except ValueError:
                ed.selectAll()          # not a number: leave the box open to fix it
                return
            self.close_editor()
            if v <= 0:
                return
            a.set_value(v)
            a.on_drag(v)
            if self.on_release is not None:
                self.on_release(a)
        ed.returnPressed.connect(apply)
        ed.editingFinished.connect(lambda: QtCore.QTimer.singleShot(0, self.close_editor))
        ed.installEventFilter(_EscapeCloses(self))
        ed.show()
        ed.setFocus()
        self.editor = ed

    editor = None

    def close_editor(self):
        if self.editor is not None:
            try:
                self.editor.hide()
                self.editor.deleteLater()
            except Exception:
                pass
        self.editor = None

    def _motion(self, node):
        if self.active is None:
            return
        x, y = node.getEvent().getPosition().getValue()
        self.active.move(self.view, x, y)
        node.setHandled()


def _escape_filter():
    from PySide import QtCore

    class _Filter(QtCore.QObject):
        def __init__(self, handles):
            super(_Filter, self).__init__()
            self.handles = handles

        def eventFilter(self, obj, ev):
            if ev.type() == QtCore.QEvent.KeyPress and ev.key() == QtCore.Qt.Key_Escape:
                QtCore.QTimer.singleShot(0, self.handles.close_editor)
                return True
            return False
    return _Filter


_filters = []


def _EscapeCloses(handles):
    f = _escape_filter()(handles)
    _filters.append(f)          # kept alive while the box is open
    del _filters[:-8]
    return f


# ------------------------------------------------------------------ where they go

def _scale(obj, part):
    from ..app import part as part_mod
    size = 0.0
    try:
        size = obj.Sketch.Shape.BoundBox.DiagonalLength
    except Exception:
        pass
    for b in part_mod.body_views(part) if part is not None else []:
        try:
            size = max(size, b.Shape.BoundBox.DiagonalLength)
        except Exception:
            pass
    return 0.15 * max(size, 10.0)


def extrude_specs(obj, part):
    """[(property, origin, direction, value, factor, scale)] for an Extrude's
    depth arrows (Blind and Mid Plane, from the sketch plane or an offset)."""
    from ..core import regions
    from ..core.features import extrude as core
    sk = getattr(obj, "Sketch", None)
    if sk is None or obj.From not in (core.FROM_SKETCH, core.FROM_OFFSET):
        return []
    try:
        shape = sk.Shape
        if shape.isNull() or not shape.Edges:
            return []
        n = regions.sketch_normal(sk)
        start = shape.BoundBox.Center
    except Exception:
        return []
    if obj.From == core.FROM_OFFSET:
        off = obj.FromOffset.Value
        start = start + n * (-off if obj.FromReverse else off)
    d1 = -n if obj.Reverse else n
    scale = _scale(obj, part)
    out = []
    c1 = obj.EndCondition
    if c1 in (core.BLIND, core.MID_PLANE):
        out.append(("Depth", start, d1, obj.Depth.Value, 2.0 if c1 == core.MID_PLANE else 1.0,
                    scale))
    if obj.Direction2 and c1 not in (core.MID_PLANE, core.THROUGH_ALL_BOTH) and \
            obj.EndCondition2 == core.BLIND:
        out.append(("Depth2", start, -d1, obj.Depth2.Value, 1.0, scale))
    return out


def revolve_specs(obj, part):
    """[(property, centre, axis, ref, radius, value)] for a Revolve's angle rings
    (Blind, both directions; Mid-Plane has none)."""
    from ..core.features import revolve as core
    sk = getattr(obj, "Sketch", None)
    if sk is None:
        return []
    try:
        point, d = obj.Proxy.axis(obj, [])
        c = sk.Shape.BoundBox.Center
    except Exception:
        return []
    d = App.Vector(d)
    d.normalize()
    if obj.Reverse:
        d = -d
    foot = point + d * (c - point).dot(d)
    ref = c - foot
    radius = ref.Length
    if radius < 1e-6:
        return []
    out = []
    if obj.EndCondition == core.BLIND:
        out.append(("Angle", foot, d, ref, radius, obj.Angle.Value))
    if obj.Direction2 and obj.EndCondition != core.MID_PLANE and \
            obj.EndCondition2 == core.BLIND:
        out.append(("Angle2", foot, -d, ref, radius, obj.Angle2.Value))
    return out


# ------------------------------------------------------------------ more features

def _sub_shape(obj, prop, index=0):
    """The ``index``-th element a LinkSub property names, on its object's shape."""
    import Part
    v = getattr(obj, prop, None)
    if not v or v[0] is None or len(v[1]) <= index:
        return None
    try:
        return Part.getShape(v[0], v[1][index], needSubElement=True)
    except Exception:
        return None


def _edge_frame(model, edge):
    """(midpoint, outward bisector) of an edge between two faces of ``model``."""
    import Part
    u0, u1 = edge.FirstParameter, edge.LastParameter
    m = edge.valueAt(0.5 * (u0 + u1))
    vm = Part.Vertex(m)
    n = App.Vector()
    for f in model.Faces:
        bb = f.BoundBox
        bb.enlarge(1e-6)
        if not bb.isInside(m):
            continue
        try:
            if f.distToShape(vm)[0] > 1e-6:
                continue
            u, v = f.Surface.parameter(m)
            nf = f.normalAt(u, v)
        except Exception:
            continue
        n = n + nf
    if n.Length < 1e-9:
        return None
    n.normalize()
    return m, n


def _model_before(obj):
    base = getattr(obj, "BaseFeature", None)
    try:
        return base.Shape if base is not None else None
    except Exception:
        return None


def _first_edge(obj, prop="Items"):
    v = getattr(obj, prop, None)
    if not v or v[0] is None:
        return None
    for i in range(len(v[1])):
        s = _sub_shape(obj, prop, i)
        if s is None:
            continue
        if s.ShapeType == "Edge":
            return s
        if s.ShapeType == "Face" and s.Edges:
            return s.Edges[0]
    return None


def edge_feature_specs(obj, part, prop):
    """An arrow out from the first picked edge's middle, along the faces' bisector,
    for a fillet radius or chamfer distance."""
    model = _model_before(obj)
    e = _first_edge(obj)
    if model is None or e is None:
        return []
    fr = _edge_frame(model, e)
    if fr is None:
        return []
    m, n = fr
    return [(prop, m, n, getattr(obj, prop).Value, 1.0, _scale(obj, part))]


def fillet_specs(obj, part):
    from ..core.features import fillet as core
    if obj.FilletType != core.CONSTANT:
        return []
    return edge_feature_specs(obj, part, "Radius")


def chamfer_specs(obj, part):
    from ..core.features import chamfer as core
    if obj.ChamferType not in (core.ANGLE_DISTANCE, core.DISTANCE_DISTANCE, core.OFFSET_FACE):
        return []
    return edge_feature_specs(obj, part, "Distance")


def shell_specs(obj, part):
    """An arrow from the first removed face's middle, into the wall (out of it for
    Shell outward)."""
    f = _sub_shape(obj, "Items")
    if f is None or f.ShapeType != "Face":
        return []
    try:
        u0, u1, v0, v1 = f.ParameterRange
        u, v = 0.5 * (u0 + u1), 0.5 * (v0 + v1)
        c = f.valueAt(u, v)
        n = f.normalAt(u, v)
    except Exception:
        return []
    d = n if obj.ShellOutward else -n
    return [("Thickness", c, d, obj.Thickness.Value, 1.0, _scale(obj, part))]


def hole_specs(obj, part):
    """A Blind hole's depth: an arrow from its first position, into the material."""
    from ..app import hole as app_hole
    from ..core import regions
    from ..core.features import hole as core
    sk = getattr(obj, "Sketch", None)
    if sk is None or obj.EndCondition != core.BLIND:
        return []
    try:
        pts = app_hole.sketch_points(sk)
        n = regions.sketch_normal(sk)
    except Exception:
        return []
    if not pts:
        return []
    d = n if obj.Reverse else -n
    return [("Depth", pts[0], d, obj.Depth.Value, 1.0, _scale(obj, part))]


SPECS = {"Fillet": fillet_specs, "Chamfer": chamfer_specs, "Shell": shell_specs,
         "Hole": hole_specs}


def field_for(panel, prop):
    """The panel's unit field for ``prop``, or None."""
    from .panel import parts
    try:
        for f in panel.widget.findChildren(parts.QuantityField):
            if f.prop == prop and f.obj is panel.obj:
                return f
    except Exception:
        pass
    return None


class PanelHandles(object):
    """Drag arrows for a panel whose feature has a SPECS entry: dragging one sets
    the panel's field (and so the preview), typing in the field moves it."""

    def __init__(self, panel, specs):
        self.panel, self.specs = panel, specs
        self.set = Handles()
        self.by_prop = {}
        self.released_at = 0.0
        self.set.on_release = self._released
        self.set.listen()

    def _released(self, _a):
        import time
        self.released_at = time.time()

    def busy(self):
        """A drag is on, or just ended: a click it made in the view isn't a pick."""
        import time
        return self.set.active is not None or time.time() - self.released_at < 0.5

    def place(self):
        try:
            specs = self.specs(self.panel.obj, self.panel.part)
        except Exception:
            specs = []
        shown = set()
        for prop, origin, d, value, factor, scale in specs:
            a = self.by_prop.get(prop)
            if a is None:
                a = self.set.add(DragArrow(lambda v, p=prop: self._dragged(p, v)))
                a.prop = prop
                self.by_prop[prop] = a
            a.factor = factor
            a.place(origin, d, value, scale)
            a.attach()
            shown.add(prop)
        for p, a in self.by_prop.items():
            if p not in shown:
                a.detach()

    def _dragged(self, prop, v):
        f = field_for(self.panel, prop)
        if f is not None:
            f.spin.setProperty("rawValue", float(v))
        else:
            self.panel.set_prop(prop, v)

    def arrows(self):
        return [a for a in self.by_prop.values() if a.shown()]

    def stop(self):
        self.set.stop()


def flex_specs(obj, part):
    """Flex's trim planes: an arrow at each end of the first body, pointing in along
    the flex axis; dragging moves the plane in from that end."""
    from ..core.features import deform as core
    try:
        base = obj.Proxy.base_bodies(obj)
        ids = [i for i in obj.Bodies if i] or base.ids("solid")
        shape = base.get(ids[0]).shape
        f = obj.Proxy.frame(obj, shape, [])
        lo, hi = core.extent(shape, f)
    except Exception:
        return []
    z = f.Rotation.multVec(App.Vector(0, 0, 1))
    p_lo = f.multVec(App.Vector(0, 0, lo))
    p_hi = f.multVec(App.Vector(0, 0, hi))
    sc = _scale(obj, part)
    return [("TrimPlane1", p_lo, z, obj.TrimPlane1.Value, 1.0, sc),
            ("TrimPlane2", p_hi, -z, obj.TrimPlane2.Value, 1.0, sc)]


SPECS["Flex"] = flex_specs
