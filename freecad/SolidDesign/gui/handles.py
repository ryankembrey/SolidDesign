# SPDX-License-Identifier: LGPL-2.1-or-later
"""Draggers in the 3D view (SolidWorks' Instant3D), one system for every feature,
drawn as FreeCAD's own gizmos: red, yellow under the pointer or while dragged, a
constant size on screen, with a blue line for the dimension they set.

- ``Dragger`` is the one base class: a Coin graph drawn on top of the model, a
  value with its text beside it, the property it sets, and the grab / start /
  move / stop protocol a drag goes through. Its kinds, as FreeCAD's gizmos:
  ``ArrowDragger`` (Linear: a length, an arrow where the length ends),
  ``RadialDragger`` (Radial: a fillet's radius, an arrow on each face),
  ``RingDragger`` (Directed Rotation: an angle swept round an axis, an arrow at
  its end) and ``AngleDragger`` (Rotation: an angle at a point, an arc and ball).
- ``Spec`` says where one dragger goes and what it shows; ``SPECS`` maps each
  feature type to the function that lists its specs.
- ``DragSet`` holds the draggers shown together and reads the mouse: press on
  one and drag, or click its value and type.
- ``FeatureDraggers`` is what panels and Instant3D use: a feature's draggers,
  made and placed from its specs. In a panel a drag sets the panel's field
  (and so the preview); on a selected feature (Instant3D) the feature changes
  when the drag ends.

Dragging snaps lengths to 0.5 mm steps (0.1 mm under 5 mm), swept angles to 5
degrees (1 degree under 30) and draft angles to 1 degree (0.5 under 10). The drag
is read from FreeCAD's own view event callbacks: Coin dragger callbacks called
through pivy crash FreeCAD when a real mouse drives them (they run without
Python's lock), so FreeCAD's gizmo shapes are used for their look only.
"""

import FreeCAD as App
import FreeCADGui as Gui

GIZMO_COLOR = (0.90, 0.12, 0.12)        # red, as FreeCAD's own gizmos
HOT_COLOR = (1.00, 0.80, 0.00)          # yellow: under the pointer or being dragged
DIM_COLOR = (0.25, 0.55, 0.95)          # blue: the dimension a gizmo sets
TEXT_COLOR = (0.10, 0.10, 0.10)
GRAB_PX = 9.0           # how near the pointer must be to a dragger to grab it

# Sizes in SoAutoZoomTranslation units (see unit()). SoArrowGeometry's arrow runs
# from its origin along +Y: a stem of STEM_UNITS (half FreeCAD's 10) and a cone 2.5
# long, so its point is at ARROW_UNITS (its tipPosition field says 1.25 more: room
# FreeCAD leaves for a label). SoRotatorGeometry's arc has radius 8 about its
# origin, its ball at 45 degrees from +X.
STEM_UNITS = 5.0
ARROW_UNITS = STEM_UNITS + 2.5
LABEL_GAP = 1.23        # the value's label starts this far past a gizmo's point
ARC_UNITS = 8.0
LABEL_BG = (1.0, 1.0, 1.0)


def snap(v):
    step = 0.1 if abs(v) < 5.0 else 0.5
    return round(v / step) * step


def snap_angle(v):
    step = 0.5 if abs(v) < 10.0 else 1.0
    return round(v / step) * step


def unit(view):
    """The world length of one SoAutoZoomTranslation unit in ``view`` now. FreeCAD's
    node scales its children by 0.1 x the view's world width / (5 x aspect ratio),
    which is 2 % of the view's height: an arrow 13.75 units long is 0.275 x the
    view's height at any zoom. (With a perspective camera FreeCAD takes that at the
    world origin's depth; this takes it at the focal plane.)"""
    try:
        w, h = view.getSize()
        a = view.getPoint(int(w // 2), 0)
        b = view.getPoint(int(w // 2), int(h))
        return max(0.02 * (a - b).Length, 1e-9)
    except Exception:
        return 1.0


def _rot(frm, to):
    """A Coin rotation turning vector ``frm`` onto ``to`` (App.Vectors)."""
    q = App.Rotation(frm, to).Q
    return q


def _seg_px(view, a, b, x, y):
    """The distance in pixels from (x, y) to the segment a-b (world points)."""
    try:
        p = view.getPointOnViewport(a)
        q = view.getPointOnViewport(b)
    except Exception:
        return 1e9
    ax, ay, bx, by = float(p[0]), float(p[1]), float(q[0]), float(q[1])
    dx, dy = bx - ax, by - ay
    ll = dx * dx + dy * dy
    t = 0.0 if ll < 1e-9 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / ll))
    px, py = ax + t * dx, ay + t * dy
    return ((x - px) ** 2 + (y - py) ** 2) ** 0.5


def _ray_on_line(view, x, y, origin, d):
    """How far along the line origin + s d the pointer's ray passes closest."""
    try:
        p = view.getPoint(int(x), int(y))
        v = App.Vector(view.getViewDirection())
    except Exception:
        return None
    if v.Length < 1e-12:
        return None
    v.normalize()
    dv = d.dot(v)
    if abs(1 - dv * dv) < 1e-6:
        return None                     # looking straight down the line
    w = p - origin
    return (w.dot(d) - dv * w.dot(v)) / (1 - dv * dv)


def _ray_angle(view, x, y, centre, axis, ref):
    """The pointer's angle round ``axis`` through ``centre`` (degrees from ``ref``),
    where its ray meets the plane normal to the axis."""
    import math
    try:
        p = view.getPoint(int(x), int(y))
        v = App.Vector(view.getViewDirection())
    except Exception:
        return None
    if v.Length < 1e-12:
        return None
    v.normalize()
    den = v.dot(axis)
    if abs(den) < 1e-6:
        return None                     # the plane is edge-on
    q = p + v * ((centre - p).dot(axis) / den)
    w = q - centre
    return math.degrees(math.atan2(w.dot(axis.cross(ref)), w.dot(ref)))


# ================================================================== draggers

class Dragger(object):
    """The base of every dragger: FreeCAD's gizmo look (red, yellow when hot,
    constant size on screen, a blue line for the dimension it sets) with the value
    written beside it. Subclasses build their geometry in ``build()`` and implement
    ``apply(spec)``, ``grab``, ``start``, ``move``, ``_show`` and ``label_point``.

    The red parts are FreeCAD's own Coin shapes (SoArrowGeometry, SoRotatorGeometry)
    under its SoAutoZoomTranslation. Only their look is used: Coin dragger callbacks
    called through pivy crash FreeCAD when a real mouse drives them, so the mouse is
    read by DragSet."""

    KIND = ""
    lo, hi = 0.0, None      # the value's range (None: no bound)

    def __init__(self, on_drag, label=""):
        from pivy import coin
        self.coin = coin
        self.on_drag = on_drag          # called with the new value as it is dragged
        self.label = label
        self.prop = ""                  # the property it sets
        self.value = 0.0
        self.dragging = False
        self.hot = False
        self.graph = None
        self.root = coin.SoAnnotation()     # on top of the model and the preview
        pick = coin.SoPickStyle()
        pick.style = coin.SoPickStyle.UNPICKABLE
        self.root.addChild(pick)
        self.colour = coin.SoBaseColor()    # shared by every red part
        self.colour.rgb.setValue(*GIZMO_COLOR)
        self.build()

    def build(self):
        raise NotImplementedError

    # ------------------------------------------------------------ parts
    def _node(self, name):
        """A Coin node of one of FreeCAD's types, or None."""
        t = self.coin.SoType.fromName(name)
        if t.isBad() or not t.canCreateInstance():
            return None
        return t.createInstance()

    def gizmo(self):
        """A red part's frame: (separator, its SoTransform). Children added to the
        separator are in SoAutoZoomTranslation units, red."""
        c = self.coin
        sep = c.SoSeparator()
        xf = c.SoTransform()
        sep.addChild(xf)
        zoom = self._node("SoAutoZoomTranslation")
        if zoom is not None:
            sep.addChild(zoom)
        sep.addChild(self.colour)
        self.root.addChild(sep)
        return sep, xf

    def arrow(self, parent):
        """FreeCAD's arrow along +Y, 0 to ARROW_UNITS (a cone and a shaft if the
        type isn't there)."""
        node = self._node("SoArrowGeometry")
        if node is not None:
            node.cylinderHeight = STEM_UNITS
            parent.addChild(node)
            return
        c = self.coin
        sep = c.SoSeparator()
        t1 = c.SoTranslation()
        t1.translation.setValue(0, 1.25 + STEM_UNITS / 2.0, 0)
        cyl = c.SoCylinder()
        cyl.radius, cyl.height = 0.2, STEM_UNITS
        t2 = c.SoTranslation()
        t2.translation.setValue(0, STEM_UNITS / 2.0 + 1.25, 0)
        cone = c.SoCone()
        cone.bottomRadius, cone.height = 0.8, 2.5
        for n in (t1, cyl, t2, cone):
            sep.addChild(n)
        parent.addChild(sep)

    def dim_lines(self):
        """The blue lines that show the dimension: (coordinates, line set)."""
        c = self.coin
        sep = c.SoSeparator()
        col = c.SoBaseColor()
        col.rgb.setValue(*DIM_COLOR)
        style = c.SoDrawStyle()
        style.lineWidth = 2.0
        coords = c.SoCoordinate3()
        lines = c.SoLineSet()
        for n in (col, style, coords, lines):
            sep.addChild(n)
        self.root.addChild(sep)
        return coords, lines

    def _set_lines(self, coords, lines, polylines):
        pts = [p for pl in polylines for p in pl]
        coords.point.setNum(0)
        if pts:
            coords.point.setValues(0, len(pts), [(q.x, q.y, q.z) for q in pts])
        lines.numVertices.setNum(0)
        if polylines:
            lines.numVertices.setValues(0, len(polylines), [len(pl) for pl in polylines])

    def _text(self, parent, offset, axis=(0.0, 1.0, 0.0)):
        """The value's label, in ``parent`` (a gizmo, so ``offset`` is in units, to
        the tip; the label goes on past it along ``axis``):
        FreeCAD's framed label (text on a background, a constant size on screen),
        set beside the tip on the side away from the gizmo (see align_label)."""
        c = self.coin
        sep = c.SoSeparator()
        self.text_xf = c.SoTranslation()
        self.text = self._node("SoFrameLabel")
        self.framed = self.text is not None
        if self.framed:
            self.text.textColor.setValue(*TEXT_COLOR)
            self.text.backgroundColor.setValue(*LABEL_BG)
            self.text.frame = True
            self.text.border = True
            self.text.size = 11
            self.text.horAlignment = c.SoImage.LEFT
            self.text.vertAlignment = c.SoImage.HALF
            sep.addChild(self.text_xf)
        else:
            self.text = c.SoText2()
            col = c.SoBaseColor()
            col.rgb.setValue(*TEXT_COLOR)
            sep.addChild(col)
            sep.addChild(self.text_xf)
        sep.addChild(self.text)
        parent.addChild(sep)
        self._align = (1, 0)            # the label's side of its anchor: right, middle
        self._chars = 4
        self.text_xf.translation.setValue(*[a + LABEL_GAP * x for a, x in zip(offset, axis)])

    def _set_text(self, txt):
        txt = "{}: {}".format(self.label, txt) if self.label else txt
        self._chars = len(txt)
        self.text.string.setValue(txt)
        self.align_label(self._view())

    # ------------------------------------------------------------ the label
    def label_point(self, view=None):
        """Where the label is anchored (world): just past the tip."""
        raise NotImplementedError

    def label_out(self):
        """The way from the gizmo to its label (world): the label sits on that side
        of its anchor."""
        raise NotImplementedError

    def align_label(self, view):
        """Put the label on the side of its anchor away from the gizmo, as the
        gizmo points on screen now: to the right or left of an arrow pointing
        sideways, above or below one pointing up or down."""
        if view is None or not getattr(self, "framed", False):
            return
        try:
            p = self.label_point(view)
            a = view.getPointOnViewport(p)
            b = view.getPointOnViewport(p + self.label_out() * unit(view))
        except Exception:
            return
        dx, dy = float(b[0]) - float(a[0]), float(b[1]) - float(a[1])
        c = self.coin
        if abs(dx) >= abs(dy):
            align = (1 if dx >= 0 else -1, 0)
        else:
            align = (0, 1 if dy >= 0 else -1)
        if align == self._align:
            return
        self._align = align
        self.text.horAlignment = {1: c.SoImage.LEFT, -1: c.SoImage.RIGHT,
                                  0: c.SoImage.CENTER}[align[0]]
        self.text.vertAlignment = {1: c.SoImage.BOTTOM, -1: c.SoImage.TOP,
                                   0: c.SoImage.HALF}[align[1]]

    def label_rect(self, view):
        """(left, bottom, right, top) of the label in view pixels (y up), roughly:
        for clicking it and for the box to type in."""
        q = view.getPointOnViewport(self.label_point(view))
        x, y = float(q[0]), float(q[1])
        w, h = 7.0 * self._chars + 10.0, 18.0
        hx, vy = self._align
        x0 = x if hx > 0 else (x - w if hx < 0 else x - w / 2)
        y0 = y if vy > 0 else (y - h if vy < 0 else y - h / 2)
        return x0, y0, x0 + w, y0 + h

    # ------------------------------------------------------------ state
    def _colour(self):
        self.colour.rgb.setValue(*(HOT_COLOR if self.dragging or self.hot else GIZMO_COLOR))

    def highlight(self, on):
        """Yellow while the pointer is on it, as FreeCAD's gizmos."""
        if on != self.hot:
            self.hot = on
            self._colour()

    def accepts(self, v):
        """Whether a typed value is in range (a length with no lower bound may be
        negative; one starting at 0 must be more than 0)."""
        if self.lo is not None and (v < self.lo or (self.lo == 0.0 and v == 0.0)):
            return False
        return self.hi is None or v <= self.hi

    def set_value(self, value):
        if self.dragging:
            return
        self._show(value)

    def start_drag(self):
        self.dragging = True
        self._colour()

    def stop(self):
        self.dragging = False
        self.hot = False
        self._colour()

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

    @staticmethod
    def _view():
        try:
            return Gui.ActiveDocument.ActiveView
        except Exception:
            return None


class ArrowDragger(Dragger):
    """Linear (a length): FreeCAD's arrow, its base at origin + the value along its
    direction, and a blue line from the origin to it (``factor``: the value is
    factor x that distance, 2 for Mid Plane)."""

    KIND = "arrow"

    def build(self):
        self.factor = 1.0
        self.origin = App.Vector()
        self.direction = App.Vector(0, 0, 1)
        self.coords, self.lines = self.dim_lines()
        sep, self.xf = self.gizmo()
        self.arrow(sep)
        self._text(sep, (0.0, ARROW_UNITS, 0.0))

    def apply(self, spec):
        self.factor = spec.factor
        self.lo = spec.lo
        self.place(spec.origin, spec.direction, spec.value)

    def place(self, origin, direction, value):
        """Put the arrow's base at ``origin`` + the value along ``direction``."""
        if self.dragging:
            return
        d = App.Vector(direction)
        if d.Length < 1e-12:
            return
        d.normalize()
        self.origin, self.direction = App.Vector(origin), d
        q = _rot(App.Vector(0, 1, 0), d)
        self.xf.rotation.setValue(q[0], q[1], q[2], q[3])
        self.set_value(value)

    def _show(self, value):
        self.value = value
        b = self.base()
        self.xf.translation.setValue(b.x, b.y, b.z)
        self._set_lines(self.coords, self.lines,
                        [[self.origin, b]] if (b - self.origin).Length > 1e-9 else [])
        self._set_text("{:g} mm".format(round(value, 4)))

    def base(self):
        return self.origin + self.direction * (self.value / self.factor)

    @property
    def scale(self):
        """The arrow's length in the view now (world units)."""
        v = self._view()
        return ARROW_UNITS * unit(v) if v is not None else 1.0

    def tip(self, view=None):
        return self.base() + self.direction * (ARROW_UNITS * unit(view or self._view()))

    def label_point(self, view=None):
        """Where the value is written (the start of its text)."""
        return self.base() + self.direction * ((ARROW_UNITS + LABEL_GAP) *
                                               unit(view or self._view()))

    def label_out(self):
        return self.direction

    # ------------------------------------------------------------ dragging
    def grab(self, view, x, y):
        """Whether the pointer at (x, y) (view pixels) is on the arrow."""
        return _seg_px(view, self.base(), self.tip(view), x, y) <= GRAB_PX

    def start(self, view, x, y):
        s = _ray_on_line(view, x, y, self.origin, self.direction)
        if s is None:
            return False
        self._grab_s = s
        self._grab_v = self.value
        self.start_drag()
        return True

    def move(self, view, x, y):
        s = _ray_on_line(view, x, y, self.origin, self.direction)
        if s is None:
            return
        v = snap(self._grab_v + (s - self._grab_s) * self.factor)
        if self.lo is not None:
            v = max(self.lo, v)
        if abs(v - self.value) < 1e-9:
            return
        self._show(v)
        self.on_drag(v)


class RadialDragger(Dragger):
    """Radial (a fillet's radius, an equal chamfer's distance): an arrow on each of
    the edge's two faces, at the value from the edge and pointing away from it, with
    blue lines from the edge. Either arrow drags the value."""

    KIND = "radial"

    def build(self):
        self.origin = App.Vector()
        self.dirs = [App.Vector(1, 0, 0), App.Vector(0, 1, 0)]
        self._which = 0
        self.coords, self.lines = self.dim_lines()
        self.xfs = []
        for i in range(2):
            sep, xf = self.gizmo()
            self.arrow(sep)
            if i == 0:
                self._text(sep, (0.0, ARROW_UNITS, 0.0))
            self.xfs.append(xf)

    def apply(self, spec):
        self.place(spec.origin, spec.direction, spec.ref, spec.value)

    def place(self, origin, d1, d2, value):
        if self.dragging:
            return
        dirs = []
        for d in (d1, d2):
            d = App.Vector(d)
            if d.Length < 1e-12:
                return
            d.normalize()
            dirs.append(d)
        self.origin, self.dirs = App.Vector(origin), dirs
        for xf, d in zip(self.xfs, dirs):
            q = _rot(App.Vector(0, 1, 0), d)
            xf.rotation.setValue(q[0], q[1], q[2], q[3])
        self.set_value(value)

    @property
    def direction(self):
        return self.dirs[0]

    def base(self, i=0):
        return self.origin + self.dirs[i] * self.value

    @property
    def scale(self):
        v = self._view()
        return ARROW_UNITS * unit(v) if v is not None else 1.0

    def tip(self, view=None, i=0):
        return self.base(i) + self.dirs[i] * (ARROW_UNITS * unit(view or self._view()))

    def label_point(self, view=None):
        return self.base(0) + self.dirs[0] * ((ARROW_UNITS + LABEL_GAP) *
                                              unit(view or self._view()))

    def label_out(self):
        return self.dirs[0]

    def _show(self, value):
        self.value = value
        for i, xf in enumerate(self.xfs):
            b = self.base(i)
            xf.translation.setValue(b.x, b.y, b.z)
        self._set_lines(self.coords, self.lines,
                        [[self.origin, self.base(i)] for i in range(2)] if value > 1e-9 else [])
        self._set_text("{:g} mm".format(round(value, 4)))

    def grab(self, view, x, y):
        ds = [_seg_px(view, self.base(i), self.tip(view, i), x, y) for i in range(2)]
        i = 0 if ds[0] <= ds[1] else 1
        if ds[i] > GRAB_PX:
            return False
        self._which = i
        return True

    def start(self, view, x, y):
        self.grab(view, x, y)
        s = _ray_on_line(view, x, y, self.origin, self.dirs[self._which])
        if s is None:
            return False
        self._grab_s = s
        self._grab_v = self.value
        self.start_drag()
        return True

    def move(self, view, x, y):
        s = _ray_on_line(view, x, y, self.origin, self.dirs[self._which])
        if s is None:
            return
        v = max(0.0, snap(self._grab_v + (s - self._grab_s)))
        if abs(v - self.value) < 1e-9:
            return
        self._show(v)
        self.on_drag(v)


class RingDragger(Dragger):
    """Directed Rotation (an angle swept round an axis, a Revolve's): a blue circle
    through the profile with a blue radius at the start and at the value, and
    FreeCAD's arrow at the value's end, along the way the angle grows (degrees,
    0 < value <= 360)."""

    KIND = "ring"
    hi = 360.0

    def build(self):
        self.centre = App.Vector()
        self.axis = App.Vector(0, 0, 1)
        self.ref = App.Vector(1, 0, 0)
        self.radius = 10.0
        self.coords, self.lines = self.dim_lines()
        sep, self.xf = self.gizmo()
        self.arrow(sep)
        self._text(sep, (0.0, ARROW_UNITS, 0.0))

    def apply(self, spec):
        self.place(spec.origin, spec.direction, spec.ref, spec.radius, spec.value)

    def place(self, centre, axis, ref, radius, value):
        if self.dragging:
            return
        a = App.Vector(axis)
        if a.Length < 1e-12:
            return
        a.normalize()
        r = App.Vector(ref) - a * App.Vector(ref).dot(a)
        if r.Length < 1e-12:
            return
        r.normalize()
        self.centre, self.axis, self.ref = App.Vector(centre), a, r
        self.radius = max(radius, 1e-6)
        self.set_value(value)

    def at(self, deg):
        return self.centre + App.Rotation(self.axis, deg).multVec(self.ref) * self.radius

    def knob(self):
        return self.at(self.value)

    def tangent(self):
        """The way the angle grows, at the value's end."""
        return self.axis.cross(App.Rotation(self.axis, self.value).multVec(self.ref))

    def label_point(self, view=None):
        return self.knob() + self.tangent() * ((ARROW_UNITS + LABEL_GAP) *
                                               unit(view or self._view()))

    def label_out(self):
        return self.tangent()

    def _show(self, value):
        self.value = value
        k = self.knob()
        t = self.tangent()
        q = _rot(App.Vector(0, 1, 0), t)
        self.xf.rotation.setValue(q[0], q[1], q[2], q[3])
        self.xf.translation.setValue(k.x, k.y, k.z)
        circle = [self.at(i * 5.0) for i in range(73)]
        self._set_lines(self.coords, self.lines,
                        [circle, [self.centre, self.at(0.0)], [self.centre, k]])
        self._set_text(u"{:g}°".format(round(value, 3)))

    # ------------------------------------------------------------ dragging
    def grab(self, view, x, y):
        k = self.knob()
        tip = k + self.tangent() * (ARROW_UNITS * unit(view))
        return _seg_px(view, k, tip, x, y) <= GRAB_PX

    def angle(self, view, x, y):
        return _ray_angle(view, x, y, self.centre, self.axis, self.ref)

    def start(self, view, x, y):
        a = self.angle(view, x, y)
        if a is None:
            return False
        self._last = a
        self._acc = self.value
        self.start_drag()
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


class AngleDragger(Dragger):
    """Rotation (an angle at a point, an Extrude's draft): FreeCAD's arc with a ball,
    turning round ``axis`` about a pivot ``lift`` units past ``origin`` along
    ``ref``; at 0 the ball points along ``ref``. The value stays within [lo, hi]."""

    KIND = "angle"

    def build(self):
        import math
        c = self.coin
        self.origin = App.Vector()
        self.axis = App.Vector(1, 0, 0)
        self.ref = App.Vector(0, 0, 1)
        self.lift = 0.0
        self.lo, self.hi = 0.0, 89.0
        sep, self.xf = self.gizmo()
        self.lift_xf = c.SoTranslation()
        self.spin = c.SoRotationXYZ()
        self.spin.axis = c.SoRotationXYZ.Z
        fix = c.SoRotationXYZ()            # the arc's ball (at 45 degrees) onto +X
        fix.axis = c.SoRotationXYZ.Z
        fix.angle = -math.pi / 4
        for n in (self.lift_xf, self.spin):
            sep.addChild(n)
        arc = c.SoSeparator()
        arc.addChild(fix)
        node = self._node("SoRotatorGeometry")
        if node is not None:
            arc.addChild(node)
        else:
            t = c.SoTranslation()
            t.translation.setValue(ARC_UNITS * 0.7071, ARC_UNITS * 0.7071, 0)
            ball = c.SoSphere()
            ball.radius = 0.8
            arc.addChild(t)
            arc.addChild(ball)
        sep.addChild(arc)
        self._text(sep, (ARC_UNITS + 0.6, 0.0, 0.0), (1.0, 0.0, 0.0))

    def apply(self, spec):
        self.lo, self.hi = spec.lo, spec.hi
        self.place(spec.origin, spec.direction, spec.ref, spec.lift, spec.value)

    def place(self, origin, axis, ref, lift, value):
        if self.dragging:
            return
        a = App.Vector(axis)
        if a.Length < 1e-12:
            return
        a.normalize()
        r = App.Vector(ref) - a * App.Vector(ref).dot(a)
        if r.Length < 1e-12:
            return
        r.normalize()
        self.origin, self.axis, self.ref, self.lift = App.Vector(origin), a, r, lift
        q = App.Rotation(r, a.cross(r), a, "ZXY").Q      # local X: ref, Z: axis
        self.xf.rotation.setValue(q[0], q[1], q[2], q[3])
        self.xf.translation.setValue(origin.x, origin.y, origin.z)
        self.lift_xf.translation.setValue(lift, 0, 0)
        self.set_value(value)

    def pivot(self, view=None):
        return self.origin + self.ref * (self.lift * unit(view or self._view()))

    def ball(self, view=None):
        u = unit(view or self._view())
        d = App.Rotation(self.axis, self.value).multVec(self.ref)
        return self.pivot(view) + d * (ARC_UNITS * u)

    def label_point(self, view=None):
        u = unit(view or self._view())
        return self.pivot(view) + self.label_out() * ((ARC_UNITS + 0.6 + LABEL_GAP) * u)

    def label_out(self):
        return App.Rotation(self.axis, self.value).multVec(self.ref)

    def _show(self, value):
        import math
        self.value = value
        self.spin.angle = math.radians(value)
        self._set_text(u"{:g}°".format(round(value, 3)))

    def grab(self, view, x, y):
        u = unit(view)
        p = self.pivot(view)
        pts = [p + App.Rotation(self.axis, self.value + a).multVec(self.ref) * (ARC_UNITS * u)
               for a in range(-45, 46, 9)]
        return min(_seg_px(view, pts[i], pts[i + 1], x, y)
                   for i in range(len(pts) - 1)) <= GRAB_PX

    def angle(self, view, x, y):
        return _ray_angle(view, x, y, self.pivot(view), self.axis, self.ref)

    def start(self, view, x, y):
        a = self.angle(view, x, y)
        if a is None:
            return False
        self._last = a
        self._acc = self.value
        self.start_drag()
        return True

    def move(self, view, x, y):
        a = self.angle(view, x, y)
        if a is None:
            return
        d = (a - self._last + 180.0) % 360.0 - 180.0
        self._last = a
        self._acc += d
        v = min(self.hi, max(self.lo, snap_angle(self._acc)))
        if abs(v - self.value) < 1e-9:
            return
        self._show(v)
        self.on_drag(v)


DRAGGERS = {d.KIND: d for d in (ArrowDragger, RadialDragger, RingDragger, AngleDragger)}


# ================================================================== the set

class DragSet(object):
    """The draggers shown together, and the mouse handling that drags them."""

    def __init__(self):
        self.draggers = []
        self.active = None
        self.view = None
        self._cbs = []

    def add(self, dragger):
        self.draggers.append(dragger)
        return dragger

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
        for a in self.draggers:
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
            for a in self.draggers:
                if a.shown() and self.on_label(a, x, y):
                    node.setHandled()
                    self.edit_value(a)
                    return
            for a in self.draggers:
                if a.shown() and a.grab(self.view, x, y) and a.start(self.view, x, y):
                    self.active = a
                    node.setHandled()
                    return
        elif self.active is not None:
            node.setHandled()
            self.end_drag()

    # ------------------------------------------------------------ typing a value
    def on_label(self, a, x, y):
        """Whether (x, y) is on the handle's value label."""
        try:
            x0, y0, x1, y1 = a.label_rect(self.view)
        except Exception:
            return False
        return x0 - 3 <= x <= x1 + 3 and y0 - 3 <= y <= y1 + 3

    def edit_value(self, a):
        """A box over the value to type a new one: Enter sets it, Escape doesn't."""
        from PySide import QtCore, QtWidgets
        self.close_editor()
        try:
            w = [x for x in Gui.getMainWindow().findChildren(QtWidgets.QWidget)
                 if x.metaObject().className() == "QOpenGLWidget" and x.isVisible()][-1]
            x0, _y0, _x1, y1 = a.label_rect(self.view)
            h = self.view.getSize()[1]
        except Exception:
            return
        ed = QtWidgets.QLineEdit(w)
        ed.setText("{:g}".format(round(a.value, 4)))
        ed.setFixedWidth(90)
        ed.setToolTip("Type a value and press Enter (Escape: keep the old one)")
        ed.move(int(x0) - 2, int(h - y1) - 2)          # over the label
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
            if not a.accepts(v):
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
        x, y = node.getEvent().getPosition().getValue()
        if self.active is None:
            # Yellow under the pointer, as FreeCAD's gizmos (the first one only).
            hit = None
            for a in self.draggers:
                if hit is None and a.shown() and a.grab(self.view, x, y):
                    hit = a
            for a in self.draggers:
                a.highlight(a is hit)
                if a.shown():
                    a.align_label(self.view)    # the view may have turned
            return
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


# ================================================================== where they go

class Spec(object):
    """Where one dragger goes, by ``kind``:

    - "arrow" (Linear): ``origin``, ``direction``, ``value`` (a length), ``factor``.
    - "radial": ``origin`` (on the edge), ``direction`` and ``ref`` (away from the
      edge along its two faces), ``value`` (a length).
    - "ring" (Directed Rotation): ``origin`` (the centre), ``direction`` (the
      axis), ``ref`` (where 0 is), ``radius``, ``value`` (degrees).
    - "angle" (Rotation): ``origin``, ``direction`` (the axis), ``ref`` (where 0
      points), ``lift`` (the pivot's distance past origin along ref, in screen
      units), ``value`` (degrees) within ``lo`` and ``hi``.

    Draggers are a constant size on screen, so a spec gives no size."""

    def __init__(self, kind, prop, origin, direction, value, factor=1.0, ref=None,
                 radius=0.0, lift=0.0, lo=0.0, hi=89.0):
        self.kind = kind
        self.prop = prop
        self.origin = App.Vector(origin)
        self.direction = App.Vector(direction)
        if self.direction.Length > 1e-12:
            self.direction.normalize()
        self.value = value
        self.factor = factor
        self.ref = App.Vector(ref) if ref is not None else None
        self.radius = radius
        self.lift = lift
        self.lo, self.hi = lo, hi

    @classmethod
    def arrow(cls, prop, origin, direction, value, factor=1.0, lo=0.0):
        """``lo``: the least value (None: it may go negative)."""
        return cls("arrow", prop, origin, direction, value, factor, lo=lo, hi=None)

    @classmethod
    def radial(cls, prop, origin, d1, d2, value):
        return cls("radial", prop, origin, d1, value, ref=d2)

    @classmethod
    def ring(cls, prop, centre, axis, ref, radius, value):
        return cls("ring", prop, centre, axis, value, ref=ref, radius=radius)

    @classmethod
    def angle(cls, prop, origin, axis, ref, value, lift=0.0, lo=0.0, hi=89.0):
        return cls("angle", prop, origin, axis, value, ref=ref, lift=lift, lo=lo, hi=hi)


# ------------------------------------------------------------------ shared geometry
#
# Every spec below is built from these, so where a gizmo goes is worked out once:
# a face's point and normal, the faces at a point of an edge and the way across
# each, a line or plane from a reference, a ring round an axis through a point.

def _sub_shape(obj, prop, index=0):
    """The ``index``-th element a LinkSub property names, on its object's shape
    (the whole shape when it names none). Read only: references aren't repaired."""
    import Part
    v = getattr(obj, prop, None)
    if not v or v[0] is None:
        return None
    try:
        if not v[1]:
            return v[0].Shape if index == 0 else None
        if len(v[1]) <= index:
            return None
        return Part.getShape(v[0], v[1][index], needSubElement=True)
    except Exception:
        return None


def _model_before(obj):
    base = getattr(obj, "BaseFeature", None)
    try:
        return base.Shape if base is not None else None
    except Exception:
        return None


def _first(obj, prop, kind):
    """The first ``kind`` ("Face" or "Edge") a LinkSub names (a picked face's first
    edge for "Edge")."""
    v = getattr(obj, prop, None)
    if not v or v[0] is None:
        return None
    for i in range(max(1, len(v[1]))):
        s = _sub_shape(obj, prop, i)
        if s is None:
            continue
        if s.ShapeType == kind:
            return s
        found = s.Faces if kind == "Face" else s.Edges
        if found:
            return found[0]
    return None


def _first_edge(obj, prop="Items"):
    return _first(obj, prop, "Edge")


def _face_frame(face, near=None):
    """(point, outward normal) of a face: at its middle, or at the point on it
    nearest ``near``."""
    import Part
    try:
        if near is None:
            u0, u1, v0, v1 = face.ParameterRange
            u, v = 0.5 * (u0 + u1), 0.5 * (v0 + v1)
            p = face.valueAt(u, v)
        else:
            p = face.distToShape(Part.Vertex(near))[1][0][0]
            u, v = face.Surface.parameter(p)
        return App.Vector(p), face.normalAt(u, v)
    except Exception:
        return None


def _edge_at(edge, frac=0.5):
    """(point, unit tangent) at a fraction along an edge."""
    u = edge.FirstParameter + frac * (edge.LastParameter - edge.FirstParameter)
    try:
        t = edge.tangentAt(u)
    except Exception:
        return None
    if t.Length < 1e-12:
        return None
    t.normalize()
    return edge.valueAt(u), t


def _faces_at(shape, m):
    """The faces of ``shape`` through the point ``m``."""
    from .preview import touches
    return [f for f in shape.Faces if touches(f, m)]


def _away_in(face, m, t):
    """The direction at ``m`` (on ``face``'s edge with tangent ``t``) across the
    face, away from the edge."""
    import Part
    try:
        u, v = face.Surface.parameter(m)
        n = face.normalAt(u, v)
    except Exception:
        return None
    d = t.cross(n)
    if d.Length < 1e-9:
        return None
    d.normalize()
    eps = max(1e-3, 0.02 * face.BoundBox.DiagonalLength)
    for s in (d, -d):
        try:
            if face.distToShape(Part.Vertex(m + s * eps))[0] < 0.1 * eps:
                return s
        except Exception:
            pass
    return None


def _across(shape, edge, frac=0.5):
    """(point on the edge, [the way across each face of ``shape`` there, away from
    the edge])."""
    at = _edge_at(edge, frac) if edge is not None else None
    if shape is None or at is None:
        return None
    m, t = at
    dirs = [d for d in (_away_in(f, m, t) for f in _faces_at(shape, m)) if d is not None]
    return m, dirs


def _line(shape):
    """(point, unit direction) of a reference: a line's, or a plane's normal."""
    from ..core import refgeom as core_ref
    if shape is None:
        return None
    for get in (core_ref.line_of, core_ref.plane_of):
        try:
            r = get(shape)
            d = App.Vector(r[1])
            d.normalize()
            return App.Vector(r[0]), d
        except Exception:
            pass
    return None


def _bodies_centre(obj, ids=None):
    """The middle of the bounding box of the feature's bodies (``ids``, or the
    ones it names in Bodies), before it."""
    try:
        base = obj.Proxy.base_bodies(obj)
        ids = [i for i in (ids or getattr(obj, "Bodies", [])) if i in base] or base.ids()
        bb = App.BoundBox()
        for i in ids:
            bb.add(base.get(i).shape.BoundBox)
        return bb.Center if bb.isValid() else None
    except Exception:
        return None


def normal_arrow(obj, prop, face, flip=False, near=None, factor=1.0, lo=0.0):
    """Linear, along a face's normal (``flip``: into it), from its middle or the
    point nearest ``near``."""
    fr = _face_frame(face, near) if face is not None else None
    if fr is None:
        return []
    p, n = fr
    return [Spec.arrow(prop, p, -n if flip else n, feature_value(obj, prop), factor, lo)]


def ring_about(prop, point, axis, through, value):
    """Directed Rotation round the line (``point``, ``axis``), through ``through``."""
    d = App.Vector(axis)
    if d.Length < 1e-12:
        return []
    d.normalize()
    foot = point + d * (through - point).dot(d)
    ref = through - foot
    if ref.Length < 1e-6:
        return []
    return [Spec.ring(prop, foot, d, ref, ref.Length, value)]


def radial_specs(obj, prop, frac=0.5):
    """Radial: an arrow on each face of the first picked edge (at ``frac`` along
    it), at the value from the edge, where a round of that radius meets the face."""
    a = _across(_model_before(obj), _first_edge(obj), frac)
    if a is None or len(a[1]) != 2:
        return []
    m, (d1, d2) = a
    return [Spec.radial(prop, m, d1, d2, feature_value(obj, prop))]


def edge_out_arrow(obj, prop, edge, shape, past=False):
    """Linear, from an edge's middle across the first face of ``shape`` there,
    away from the edge (``past``: out beyond the edge instead)."""
    a = _across(shape, edge) if edge is not None else None
    if a is None or not a[1]:
        return []
    d = -a[1][0] if past else a[1][0]
    return [Spec.arrow(prop, a[0], d, feature_value(obj, prop))]


# ------------------------------------------------------------------ features

def revolve_specs(obj, part):
    """A Revolve's angle rings (Blind, both directions; Mid-Plane has none)."""
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
    if obj.Reverse:
        d = -d
    out = []
    if obj.EndCondition == core.BLIND:
        out += ring_about("Angle", point, d, c, obj.Angle.Value)
    if obj.Direction2 and obj.EndCondition != core.MID_PLANE and \
            obj.EndCondition2 == core.BLIND:
        out += ring_about("Angle2", point, -d, c, obj.Angle2.Value)
    return out


def edge_feature_specs(obj, part, prop):
    """An arrow out from the first picked edge's middle, along the faces' bisector
    (a fillet or chamfer whose two sizes differ)."""
    e = _first_edge(obj)
    model = _model_before(obj)
    if e is None or model is None:
        return []
    at = _edge_at(e)
    if at is None:
        return []
    n = App.Vector()
    for f in _faces_at(model, at[0]):
        fr = _face_frame(f, at[0])
        if fr is not None:
            n = n + fr[1]
    if n.Length < 1e-9:
        return []
    n.normalize()
    return [Spec.arrow(prop, at[0], n, feature_value(obj, prop))]


def fillet_specs(obj, part):
    """Symmetric Constant: the radius on both faces. Variable: the start and end
    radii at the ends of the first edge. Asymmetric: one arrow (which face takes
    which distance is the fillet's own business)."""
    from ..core.features import fillet as core
    if obj.FilletType == core.VARIABLE:
        ends = ("EndRadius", "StartRadius") if obj.ReverseVariable else \
            ("StartRadius", "EndRadius")
        return radial_specs(obj, ends[0], 0.0) + radial_specs(obj, ends[1], 1.0)
    if obj.FilletType != core.CONSTANT:
        return []
    if getattr(obj, "FilletMethod", core.SYMMETRIC) == core.SYMMETRIC:
        r = radial_specs(obj, "Radius")
        if r:
            return r
    return edge_feature_specs(obj, part, "Radius")


def chamfer_specs(obj, part):
    from ..core.features import chamfer as core
    if obj.ChamferType not in (core.ANGLE_DISTANCE, core.DISTANCE_DISTANCE, core.OFFSET_FACE):
        return []
    if obj.ChamferType == core.DISTANCE_DISTANCE and getattr(obj, "EqualDistance", False):
        r = radial_specs(obj, "Distance")
        if r:
            return r
    return edge_feature_specs(obj, part, "Distance")


def draft_specs(obj, part):
    """Rotation: the draft angle's arc on the first drafted face, its ball along
    the direction of pull at 0 and leaning off the face as the angle grows."""
    face = _first(obj, "Items", "Face")
    fr = _face_frame(face) if face is not None else None
    if fr is None:
        return []
    p, n = fr
    pull = _line(_sub_shape(obj, "PullDirection"))
    plane = _line(_sub_shape(obj, "NeutralPlane"))
    if pull is not None:
        d = pull[1]
    elif plane is not None:
        d = plane[1] if (p - plane[0]).dot(plane[1]) >= 0 else -plane[1]
    else:
        return []
    if obj.ReverseDirection:
        d = -d
    d = d - n * d.dot(n)                # along the face
    if d.Length < 1e-9:
        return []
    axis = d.cross(n)                   # leans the ball off the face
    return [Spec.angle("Angle", p, axis, d, obj.Angle.Value, lo=0.0, hi=89.0)]


def shell_specs(obj, part):
    """An arrow from the first removed face's middle, into the wall (out of it for
    Shell outward)."""
    return normal_arrow(obj, "Thickness", _first(obj, "Items", "Face"),
                        flip=not obj.ShellOutward)


def dome_specs(obj, part):
    """The dome's height, out of the face's middle (into it reversed)."""
    return normal_arrow(obj, "Distance", _first(obj, "Items", "Face"),
                        flip=obj.ReverseDirection)


def wrap_specs(obj, part):
    """Emboss or Deboss: the depth, at the face where the sketch lands."""
    from ..core.features import wrap as core
    if obj.WrapType == core.SCRIBE:
        return []
    sk = getattr(obj, "Sketch", None)
    near = sk.Shape.BoundBox.Center if sk is not None and not sk.Shape.isNull() else None
    flip = (obj.WrapType == core.DEBOSS) != bool(getattr(obj, "ReverseDirection", False))
    return normal_arrow(obj, "Depth", _first(obj, "Items", "Face"), flip=flip, near=near)


def rib_specs(obj, part):
    """The rib's thickness: across its line (Parallel to Sketch) or the sketch plane
    (Normal to Sketch), both ways for Both Sides."""
    from ..core import regions
    from ..core.features import rib as core
    sk = getattr(obj, "Sketch", None)
    try:
        w = sk.Shape.Wires[0]
        n = regions.sketch_normal(sk)
        vs = w.Vertexes
        mid = (vs[0].Point + vs[-1].Point) * 0.5 if len(vs) > 1 else w.BoundBox.Center
        d = core._across(w, n) if obj.ExtrusionDirection == core.PARALLEL else n
    except Exception:
        return []
    if obj.ThicknessSide == core.SECOND:
        d = -d
    f = 2.0 if obj.ThicknessSide == core.BOTH else 1.0
    return [Spec.arrow("Thickness", mid, d, obj.Thickness.Value, f)]


def _thread_site(obj, prop, bodies, flip):
    """Where a thread on the edge ``prop`` names starts, and which way it runs."""
    from ..core.features import thread as core
    e = _first_edge(obj, prop)
    try:
        return core.site(bodies, e, flip) if e is not None else None
    except Exception:
        return None


def thread_specs(obj, part):
    """The offset from the edge, then the Blind length from there, along the
    cylinder."""
    from ..core.features import thread as core
    s = _thread_site(obj, "Edge", obj.Proxy.base_bodies(obj), obj.ReverseDirection)
    if s is None:
        return []
    out = []
    start = s.centre
    if obj.Offset:
        d = -s.axis if obj.ReverseOffset else s.axis
        out.append(Spec.arrow("OffsetDistance", s.centre, d, obj.OffsetDistance.Value))
        start = s.centre + d * obj.OffsetDistance.Value
    if obj.EndCondition == core.BLIND:
        out.append(Spec.arrow("Length", start, s.axis, obj.Length.Value))
    return out


def cosmetic_thread_specs(obj, part):
    """A Blind cosmetic thread's length, from the edge along the cylinder."""
    from ..app.refgeom import _base_bodies
    s = _thread_site(obj, "Reference1", _base_bodies(obj), obj.Flip)
    if obj.Type != "Blind" or s is None:
        return []
    return [Spec.arrow("Length", s.centre, s.axis, obj.Length.Value)]


def helix_specs(obj, part):
    """The height, along the axis (for the types that set it)."""
    from ..core import curves
    if obj.Type not in (curves.HEIGHT_REVS, curves.HEIGHT_PITCH):
        return []
    try:
        a, b = obj.Proxy.axis_line(obj)
    except Exception:
        return []
    return [Spec.arrow("Height", a, b - a, obj.Height.Value)]


def plane_specs(obj, part):
    """Offset Distance: the distance, from the reference along its normal to the
    plane. At Angle: the angle, round the edge it turns about."""
    from ..core import refgeom as core_ref
    if obj.Shape.isNull():
        return []
    try:
        cons = obj.Proxy.constraints(obj)
    except Exception:
        return []
    shapes = [_sub_shape(obj, "Reference%d" % i) for i in (1, 2, 3)]
    by_ref = dict(zip([i for i, s in enumerate(shapes) if s is not None], cons))
    c = obj.Shape.BoundBox.Center
    for i, con in by_ref.items():
        if con == core_ref.C_OFFSET:
            ref = _line(shapes[i])
            if ref is None:
                return []
            p0, n = ref
            s = (c - p0).dot(n)
            d = n if s >= 0 else -n
            return [Spec.arrow("Distance", c - n * s, d, obj.Distance.Value)]
        if con == core_ref.C_ANGLE:
            axis = next((shapes[j] for j, k in by_ref.items()
                         if k == core_ref.C_COINCIDENT and j != i), None)
            try:
                p, a = core_ref.line_of(axis)
                _pc, n, _x = core_ref.plane_of(shapes[i])
            except Exception:
                return []
            # The arc starts in the reference plane, square to the edge, and turns
            # with the plane.
            w = n.cross(a)
            if w.Length < 1e-9:
                return []
            w.normalize()
            size = 0.25 * obj.Shape.BoundBox.DiagonalLength
            return ring_about("Angle", p, -a if obj.Flip else a, p + w * size,
                              obj.Angle.Value)
    return []


def linear_pattern_specs(obj, part):
    """Each direction's spacing: an arrow from the seed to the first copy."""
    c = _pattern_seed(obj)
    if c is None:
        return []
    out = []
    for prop, ref, rev in (("Spacing", "Direction1Ref", "Reverse"),
                           ("Spacing2", "Direction2Ref", "Reverse2")):
        if prop == "Spacing2" and not obj.Direction2:
            continue
        ln = _line(_sub_shape(obj, ref))
        if ln is not None:
            d = -ln[1] if getattr(obj, rev) else ln[1]
            out.append(Spec.arrow(prop, c, d, getattr(obj, prop).Value))
    return out


def circular_pattern_specs(obj, part):
    """The angle (between copies, or in all with equal spacing), round the axis
    through the seed."""
    c = _pattern_seed(obj)
    ln = _line(_sub_shape(obj, "Axis"))
    if c is None or ln is None:
        return []
    return ring_about("Angle", ln[0], -ln[1] if obj.Reverse else ln[1], c, obj.Angle.Value)


def _pattern_seed(obj):
    try:
        return obj.Proxy.seed_centre(obj, obj.Proxy.base_bodies(obj))
    except Exception:
        return None


def move_copy_specs(obj, part):
    """Translate/Rotate: Delta X, Y and Z from the bodies' middle (or the distance
    along the picked edge), and the angle round the picked axis."""
    if obj.MoveMode != "Translate/Rotate":
        return []
    c = _bodies_centre(obj)
    if c is None:
        return []
    out = []
    ln = _line(_sub_shape(obj, "TranslateReference"))
    if ln is not None:
        d = -ln[1] if obj.ReverseTranslate else ln[1]
        out.append(Spec.arrow("TranslateDistance", c, d, obj.TranslateDistance.Value))
    else:
        for prop, d in (("DeltaX", App.Vector(1, 0, 0)), ("DeltaY", App.Vector(0, 1, 0)),
                        ("DeltaZ", App.Vector(0, 0, 1))):
            out.append(Spec.arrow(prop, c, d, getattr(obj, prop).Value, lo=None))
    ax = _line(_sub_shape(obj, "RotateReference"))
    if ax is not None:
        out += ring_about("Angle", ax[0], ax[1], c, obj.Angle.Value)
    return out


def move_face_specs(obj, part):
    """Offset: along the first face's normal. Translate: along the picked direction.
    Rotate: round the picked axis."""
    from ..core.features import faceops as core
    face = _first(obj, "Items", "Face")
    if obj.MoveType == core.OFFSET:
        return normal_arrow(obj, "Distance", face, flip=obj.Flip)
    fr = _face_frame(face) if face is not None else None
    if fr is None:
        return []
    if obj.MoveType == core.TRANSLATE:
        ln = _line(_sub_shape(obj, "Direction"))
        if ln is None:
            return []
        d = -ln[1] if obj.Flip else ln[1]
        return [Spec.arrow("Distance", fr[0], d, obj.Distance.Value)]
    ax = _line(_sub_shape(obj, "Axis"))
    if ax is None:
        return []
    return ring_about("Angle", ax[0], -ax[1] if obj.Flip else ax[1], fr[0], obj.Angle.Value)


def offset_surface_specs(obj, part):
    """The offset, along the first face's normal (negative: the other way)."""
    return normal_arrow(obj, "Distance", _first(obj, "Items", "Face"), flip=obj.Flip, lo=None)


def thicken_specs(obj, part):
    """The thickness, along the sheet's normal (both ways for Both Sides)."""
    from ..core.features import surfaces as core
    try:
        sheet = obj.Proxy.base_bodies(obj).get(obj.Body).shape
    except Exception:
        return []
    if sheet is None or not sheet.Faces:
        return []
    both = obj.ThickenSide == core.BOTH
    return normal_arrow(obj, "Thickness", sheet.Faces[0], flip=obj.ThickenSide == core.SIDE2,
                        factor=2.0 if both else 1.0)


def extend_specs(obj, part):
    """Extend by a distance: an arrow out past the first picked edge, along the
    surface."""
    from ..core.features import surfaces as core
    if obj.EndCondition != core.DISTANCE:
        return []
    return edge_out_arrow(obj, "Distance", _first_edge(obj), _model_before(obj), past=True)


def flange_specs(obj, part):
    """Ruled and Radiate surfaces: the distance, from the first picked edge across
    the new surface."""
    new = getattr(obj, "AddSubShape", None)
    if new is None or new.isNull():
        return []
    return edge_out_arrow(obj, "Distance", _first_edge(obj), new)


def extrude_specs(obj, part):
    """An Extrude's From Offset, its depth arrows (Blind and Mid Plane), and with
    Draft on, the draft angle's arc past each arrow (as PartDesign's Pad shows its
    taper)."""
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
        side = sk.getGlobalPlacement().Rotation.multVec(App.Vector(1, 0, 0))
    except Exception:
        return []
    out = []
    if obj.From == core.FROM_OFFSET:
        d0 = -n if obj.FromReverse else n
        out.append(Spec.arrow("FromOffset", start, d0, obj.FromOffset.Value))
        start = start + d0 * obj.FromOffset.Value
    d1 = -n if obj.Reverse else n

    def draft(suffix, base, d):
        if getattr(obj, "Draft" + suffix, False):
            out.append(Spec.angle("DraftAngle" + suffix, base, side, d,
                                  getattr(obj, "DraftAngle" + suffix).Value,
                                  lift=ARROW_UNITS + 3.0, lo=0.0, hi=89.0))
    c1 = obj.EndCondition
    if c1 in (core.BLIND, core.MID_PLANE):
        f = 2.0 if c1 == core.MID_PLANE else 1.0
        out.append(Spec.arrow("Depth", start, d1, obj.Depth.Value, f))
        draft("", start + d1 * (obj.Depth.Value / f), d1)
    if obj.Direction2 and c1 not in (core.MID_PLANE, core.THROUGH_ALL_BOTH) and \
            obj.EndCondition2 == core.BLIND:
        out.append(Spec.arrow("Depth2", start, -d1, obj.Depth2.Value))
        draft("2", start - d1 * obj.Depth2.Value, -d1)
    return out


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
    return [Spec.arrow("Depth", pts[0], d, obj.Depth.Value)]


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
    return [Spec.arrow("TrimPlane1", p_lo, z, obj.TrimPlane1.Value),
            Spec.arrow("TrimPlane2", p_hi, -z, obj.TrimPlane2.Value)]


def deform_specs(obj, part):
    """Deform (Point): the distance arrow, from the point along the push."""
    from ..core.features import morph
    if obj.DeformType != morph.POINT:
        return []
    c = App.Vector(obj.DeformPoint)
    try:
        base = obj.Proxy.base_bodies(obj)
        from ..app.deform import _direction, _normal_at
        d = _direction(obj, "DeformDirection", "deform direction", obj.BaseFeature, [])
        if d is None:
            d = _normal_at(base, c)
    except Exception:
        return []
    if d is None:
        return []
    if obj.ReverseDirection:
        d = -d
    return [Spec.arrow("Distance", c, d, obj.Distance.Value)]


def freeform_specs(obj, part):
    """Freeform: an arrow at each control point, along the face's normal."""
    v = obj.Items
    if not v or v[0] is None:
        return []
    f = _sub_shape(obj, "Items")
    if f is None or f.ShapeType != "Face":
        return []
    out = []
    for i, (c, h) in enumerate(obj.Proxy.points(obj)):
        fr = _face_frame(f, c)
        if fr is None:
            continue
        # The arrow's base sits at the height; a negative height points it inwards
        # (its name says which way, so a drag keeps the sign).
        if h >= 0:
            out.append(Spec.arrow("Point%d+" % i, c, fr[1], h))
        else:
            out.append(Spec.arrow("Point%d-" % i, c, -fr[1], -h))
    return out


def placed_specs(obj, part):
    """Mounting Boss, Snap Hook: the height arrow, from the clicked point along the
    face's normal."""
    from ..app.surfaces import _vec
    c = _vec(obj.Position)
    if c is None:
        return []
    return normal_arrow(obj, "Height", _first(obj, "Items", "Face"), flip=obj.ReverseDirection,
                        near=c)


def spec_key(obj):
    """The SPECS key of a feature or reference geometry: its TYPE, or "Ref:" and
    its kind."""
    proxy = getattr(obj, "Proxy", None)
    t = getattr(proxy, "TYPE", "")
    if t:
        return t
    k = getattr(proxy, "KIND", "")
    return "Ref:" + k if k else ""


SPECS = {
    # Features
    "Extrude": extrude_specs, "Revolve": revolve_specs, "Fillet": fillet_specs,
    "Chamfer": chamfer_specs, "Draft": draft_specs, "Shell": shell_specs,
    "Dome": dome_specs, "Wrap": wrap_specs, "Rib": rib_specs, "Hole": hole_specs,
    "Thread": thread_specs, "MountingBoss": placed_specs, "SnapHook": placed_specs,
    "LinearPattern": linear_pattern_specs, "CircularPattern": circular_pattern_specs,
    # Bodies
    "MoveCopy": move_copy_specs, "MoveFace": move_face_specs, "Flex": flex_specs,
    "Deform": deform_specs, "Freeform": freeform_specs,
    # Surfaces
    "OffsetSurface": offset_surface_specs, "Thicken": thicken_specs,
    "Extend": extend_specs, "Ruled": flange_specs, "Radiate": flange_specs,
    # Reference geometry and curves
    "Ref:plane": plane_specs, "Ref:helix": helix_specs, "Ref:cosmetic": cosmetic_thread_specs,
}


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


class FeatureDraggers(object):
    """One feature's draggers, from its specs. ``on_value(prop, value)`` is called
    as a dragger moves (a panel sets its field); ``on_release(dragger)`` when a drag
    (or a typed value) is done (Instant3D changes the feature then)."""

    def __init__(self, obj, part, specs, on_value=None, on_release=None):
        import time
        self.obj, self.part, self.specs = obj, part, specs
        self.on_value = on_value
        self.release_hook = on_release
        self.set = DragSet()
        self.by_prop = {}
        self.released_at = 0.0
        self._time = time
        self.set.on_release = self._released
        self.set.listen()

    def _released(self, d):
        self.released_at = self._time.time()
        if self.release_hook is not None:
            self.release_hook(d)

    def busy(self):
        """A drag is on, or just ended: a click it made in the view isn't a pick."""
        return self.set.active is not None or self._time.time() - self.released_at < 0.5

    def place(self):
        try:
            specs = self.specs(self.obj, self.part)
        except Exception:
            specs = []
        shown = set()
        for s in specs:
            d = self.by_prop.get(s.prop)
            if d is not None and d.KIND != s.kind:
                d.detach()
                d = None
            if d is None:
                d = self.set.add(DRAGGERS[s.kind](
                    lambda v, p=s.prop: self.on_value(p, v) if self.on_value else None))
                d.prop = s.prop
                self.by_prop[s.prop] = d
            d.apply(s)
            d.attach()
            shown.add(s.prop)
        for p, d in self.by_prop.items():
            if p not in shown:
                d.detach()

    def get(self, prop):
        return self.by_prop.get(prop)

    def draggers(self):
        """The draggers showing now."""
        return [d for d in self.by_prop.values() if d.shown()]

    def stop(self):
        self.set.stop()


def panel_value(panel, prop, v):
    """A dragger in a panel moved: the panel's own hook, its field for the property,
    or the property itself."""
    hook = getattr(panel, "drag_set", None)
    if hook is not None and hook(prop, v):
        return
    f = field_for(panel, prop)
    if f is not None:
        f.spin.setProperty("rawValue", float(v))
    else:
        panel.set_prop(prop, v)


def feature_value(obj, prop):
    """The value a dragger's property has on the feature now."""
    if prop[:5] == "Point" and prop[-1:] in "+-" and "ControlPoints" in obj.PropertiesList:
        pts = obj.Proxy.points(obj)
        i = int(prop[5:-1])
        return abs(pts[i][1]) if i < len(pts) else 0.0
    v = getattr(obj, prop)
    return v.Value if hasattr(v, "Value") else float(v)


def set_feature_value(obj, prop, v):
    """Set what a dragger shows on the feature itself (Instant3D)."""
    if prop[:5] == "Point" and prop[-1:] in "+-" and "ControlPoints" in obj.PropertiesList:
        i = int(prop[5:-1])
        pts = obj.Proxy.moves(obj)
        if i < len(pts):
            texts = list(obj.ControlPoints)
            texts[i] = obj.Proxy.point_text(pts[i][0], -v if prop.endswith("-") else v,
                                            pts[i][2])
            obj.ControlPoints = texts
        return
    setattr(obj, prop, v)
