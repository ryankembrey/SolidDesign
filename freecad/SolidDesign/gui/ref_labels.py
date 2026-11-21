# SPDX-License-Identifier: LGPL-2.1-or-later
"""Names on reference geometry in the 3D view, as SolidWorks shows them: lying
flat in a plane, inside its top-left corner; along an axis near its end, turned
to face the viewer and never upside down; just above a point or a coordinate
system's origin. The text stays the same size on screen however far the view is
zoomed. Turn them off in Solid Design > Reference Names.

A label is part of the object's own drawing, so it shows and hides with the
object. For the origin planes, which FreeCAD draws at a fixed size on screen,
it goes inside that scaled drawing, at the square's corner.
"""

import math

import FreeCAD as App
import FreeCADGui as Gui

PARAMS = "User parameter:BaseApp/Preferences/Mod/SolidDesign"
NODE = "SD_RefLabel"
COLOR = (0.1, 0.28, 0.62)
# Sizes in SoAutoZoomTranslation units (2 % of the view's height; see handles.unit).
TEXT = 1.1              # letter height
INSET = 0.6             # from a plane's corner
GAP = 0.45              # from an axis line, or above a point
AXIS_AT = 0.8           # how far along an axis its name starts
# The origin planes are drawn by FreeCAD in its own fixed-size units (their
# square runs 8 to 62).
ORIGIN_TEXT = 9.0
ORIGIN_INSET = 3.0
KINDS = ("plane", "axis", "point", "csys")


def enabled():
    return App.ParamGet(PARAMS).GetBool("ReferenceLabels", True)


def set_enabled(on):
    App.ParamGet(PARAMS).SetBool("ReferenceLabels", bool(on))
    for doc in App.listDocuments().values():
        for o in doc.Objects:
            if labelled(o):
                refresh(o)


def _clean(label):
    from ..app import part as part_mod
    return part_mod.clean_label(label)


def _origin_plane(obj):
    return obj.TypeId == "Part::DatumPlane"


def labelled(obj):
    """Whether ``obj`` gets a name in the view: our planes, axes, points and
    coordinate systems, and the origin planes."""
    from ..app import util
    if _origin_plane(obj):
        return True
    return util.role(obj) == "refgeom" and getattr(obj.Proxy, "KIND", "") in KINDS


# ------------------------------------------------------------------ nodes

def _fc_node(name):
    from pivy import coin
    t = coin.SoType.fromName(name)
    return t.createInstance() if not t.isBad() and t.canCreateInstance() else None


def _label_root():
    """The label's separator: named, not pickable, flat-coloured, drawn just in
    front of the face it lies on."""
    from pivy import coin
    sep = coin.SoSeparator()
    sep.setName(NODE)
    pick = coin.SoPickStyle()
    pick.style = coin.SoPickStyle.UNPICKABLE
    light = coin.SoLightModel()
    light.model = coin.SoLightModel.BASE_COLOR
    col = coin.SoBaseColor()
    col.rgb.setValue(*COLOR)
    off = coin.SoPolygonOffset()
    off.factor = -1.0
    off.units = -4.0
    for n in (pick, light, col, off):
        sep.addChild(n)
    return sep


def _text(text, size, x=0.0, y=0.0, centre=False):
    """[nodes]: flat text, ``size`` high, its baseline's start (or middle) at (x, y)."""
    from pivy import coin
    font = coin.SoFont()
    font.name = "Sans"
    font.size = size
    tr = coin.SoTranslation()
    tr.translation.setValue(x, y, 0)
    txt = coin.SoAsciiText()
    txt.string = str(text)
    txt.justification = coin.SoAsciiText.CENTER if centre else coin.SoAsciiText.LEFT
    return [font, tr, txt]


def _frame(origin, x, y=None):
    """An SoTransform to a frame at ``origin`` with its X along ``x`` (and Y along
    ``y``)."""
    from pivy import coin
    xf = coin.SoTransform()
    xf.translation.setValue(origin.x, origin.y, origin.z)
    if y is None:
        r = App.Rotation(App.Vector(1, 0, 0), x)
    else:
        n = x.cross(y)
        m = App.Matrix(x.x, y.x, n.x, 0, x.y, y.y, n.y, 0, x.z, y.z, n.z, 0, 0, 0, 0, 1)
        r = App.Placement(m).Rotation
    q = r.Q
    xf.rotation.setValue(q[0], q[1], q[2], q[3])
    return xf


def _plane_node(text, corner, x, y):
    """Flat in the plane, inside its top-left ``corner`` (X along its top edge,
    Y up its left edge)."""
    sep = _label_root()
    sep.addChild(_frame(corner, x, y))
    zoom = _fc_node("SoAutoZoomTranslation")
    if zoom is not None:
        sep.addChild(zoom)
    for n in _text(text, TEXT, INSET, -INSET - TEXT):
        sep.addChild(n)
    return sep


def _axis_node(text, a, b):
    """Along the axis from ``a`` to ``b``, near ``b``: turned about the axis to
    face the viewer, and read left to right whichever way the axis points on
    screen (both decided as it is drawn, by _facing)."""
    from pivy import coin
    d = b - a
    if d.Length < 1e-12:
        return None
    d.normalize()
    at = a + (b - a) * AXIS_AT
    sep = _label_root()
    frame = _frame(at, d)
    sep.addChild(frame)
    spin = coin.SoRotation()            # about the axis (local X), to face the viewer
    sw = coin.SoSwitch()
    sw.whichChild = 0
    cb = coin.SoCallback()
    cb.setCallback(_facing, (spin, sw, a, b, App.Rotation(App.Vector(1, 0, 0), d)))
    sep.addChild(cb)
    sep.addChild(spin)
    zoom = _fc_node("SoAutoZoomTranslation")
    if zoom is not None:
        sep.addChild(zoom)
    ahead = coin.SoSeparator()
    for n in _text(text, TEXT, 0, GAP):
        ahead.addChild(n)
    back = coin.SoSeparator()            # the axis points left on screen: turned round
    turn = coin.SoRotationXYZ()
    turn.axis = coin.SoRotationXYZ.Z
    turn.angle = math.pi
    back.addChild(turn)
    for n in _text(text, TEXT, 0, GAP):
        back.addChild(n)
    sw.addChild(ahead)
    sw.addChild(back)
    sep.addChild(sw)
    return sep


def _facing(data, action):
    """While drawing an axis' name: turn it about the axis so it faces the
    viewer, and round so it reads left to right."""
    try:
        from pivy import coin
        if not action.isOfType(coin.SoGLRenderAction.getClassTypeId()):
            return
        spin, sw, a, b, frame = data
        view = Gui.ActiveDocument.ActiveView
        # The text's normal (local Z) as near the viewer as a turn about X allows.
        t = frame.inverted().multVec(-App.Vector(view.getViewDirection()))
        if abs(t.y) + abs(t.z) > 1e-9:
            q = App.Rotation(App.Vector(1, 0, 0), math.degrees(math.atan2(-t.y, t.z))).Q
            cur = spin.rotation.getValue().getValue()
            if max(abs(x - y) for x, y in zip(cur, q)) > 1e-6:
                spin.rotation.setValue(q[0], q[1], q[2], q[3])
        pa, pb = view.getPointOnViewport(a), view.getPointOnViewport(b)
        want = 1 if pb[0] < pa[0] else 0
        if sw.whichChild.getValue() != want:
            sw.whichChild = want
    except Exception:
        pass


def _point_node(text, p):
    """Just above the point, facing the viewer."""
    from pivy import coin
    sep = _label_root()
    tr = coin.SoTranslation()
    tr.translation.setValue(p.x, p.y, p.z)
    sep.addChild(tr)
    bb = coin.SoVRMLBillboard()
    bb.axisOfRotation.setValue(0, 0, 0)
    sep.addChild(bb)
    zoom = _fc_node("SoAutoZoomTranslation")
    if zoom is not None:
        bb.addChild(zoom)
    for n in _text(text, TEXT, 0, GAP, centre=True):
        bb.addChild(n)
    return sep


def _children(node):
    """A node's children; for a nodekit (FreeCAD's fixed-size drawing of the
    origin planes is one), what is in its "shape" part."""
    from pivy import coin
    try:
        if node.getTypeId().isDerivedFrom(coin.SoBaseKit.getClassTypeId()):
            part = node.getPart("shape", False)
            return [part] if part is not None else []
        return [node.getChild(i) for i in range(node.getNumChildren())]
    except Exception:
        return []


def _walk(node, parent=None):
    """(parent, node) for every node under ``node``, depth first."""
    yield parent, node
    for c in _children(node):
        for x in _walk(c, node):
            yield x


def _labels(root):
    return [(par, n) for par, n in _walk(root)
            if n.getName() and n.getName().getString() == NODE]


def texts(obj):
    """The names drawn for ``obj`` (for tests, and to check what shows)."""
    out = []
    for _par, sep in _labels(obj.ViewObject.RootNode):
        found = []
        for _p, n in _walk(sep):
            if n.getTypeId().getName().getString() in ("Text2", "AsciiText"):
                t = n.string[0].getString().strip()
                if t not in found:      # an axis' name, either way round, is one
                    found.append(t)
        out.extend(found)
    return out


def _remove(root):
    for par, n in _labels(root):
        try:
            par.removeChild(n)
        except Exception:
            pass


def _find_type(node, name):
    """The first node of type ``name`` under ``node``, nodekits included."""
    return next((n for _p, n in _walk(node) if n.getTypeId().getName().getString() == name),
                None)


# ------------------------------------------------------------------ where each goes

def label_node(obj):
    """The node that names ``obj`` (in its local coordinates), or None."""
    shape = obj.Shape
    if shape.isNull():
        return None
    inv = obj.Placement.inverse()
    text = _clean(obj.Label)
    kind = getattr(obj.Proxy, "KIND", "")
    try:
        if kind == "plane" and shape.Faces:
            f = shape.Faces[0]
            u0, u1, v0, v1 = f.ParameterRange
            corner = inv.multVec(f.valueAt(u0, v1))
            x = inv.multVec(f.valueAt(u1, v1)) - corner
            y = corner - inv.multVec(f.valueAt(u0, v0))
            x.normalize()
            y.normalize()
            return _plane_node(text, corner, x, y)
        if kind == "axis" and shape.Edges:
            e = shape.Edges[0]
            return _axis_node(text, inv.multVec(e.Vertexes[0].Point),
                              inv.multVec(e.Vertexes[-1].Point))
        if kind == "point" and shape.Vertexes:
            return _point_node(text, inv.multVec(shape.Vertexes[0].Point))
        if kind == "csys" and shape.Edges:
            return _point_node(text, inv.multVec(shape.Edges[0].Vertexes[0].Point))
    except Exception as e:
        App.Console.PrintLog("Solid Design: label for {}: {}\n".format(obj.Name, e))
    return None


def refresh(obj):
    """Put (or take away) ``obj``'s name in the view, from its label and shape now."""
    vo = getattr(obj, "ViewObject", None)
    if vo is None:
        return
    try:
        _remove(vo.RootNode)
        if not enabled():
            return
        if _origin_plane(obj):
            _origin(obj, vo)
            return
        node = label_node(obj) if vo.Visibility else None
        if node is not None:
            # Once, under the object's root (its display modes share nodes, so
            # one in each could be drawn twice); its view provider redoes it
            # when the object is shown or hidden.
            vo.RootNode.addChild(node)
    except Exception as e:
        App.Console.PrintLog("Solid Design: label for {}: {}\n".format(obj.Name, e))


def _origin(obj, vo):
    """Flat in FreeCAD's fixed-size drawing of an origin plane, inside the
    square's top-left corner."""
    scale = _find_type(vo.SwitchNode, "SoShapeScale")
    if scale is None:
        return
    shape = scale.getPart("shape", False)
    coords = _find_type(shape, "Coordinate3") if shape is not None else None
    if coords is None:
        return
    pts = [coords.point[i].getValue() for i in range(coords.point.getNum())]
    x0, y1 = min(p[0] for p in pts), max(p[1] for p in pts)
    sep = _label_root()
    for n in _text(_clean(obj.Label), ORIGIN_TEXT, x0 + ORIGIN_INSET,
                   y1 - ORIGIN_INSET - ORIGIN_TEXT):
        sep.addChild(n)
    shape.addChild(sep)


def label_part(part):
    """Names on a part's origin planes (after they are made, or the file opened)."""
    for o in getattr(part, "Origin", []) or []:
        if _origin_plane(o):
            refresh(o)


# ------------------------------------------------------------------ following changes

class _Observer(object):
    """A renamed origin plane gets its new name (our own objects see to theirs)."""

    def slotChangedObject(self, obj, prop):
        if prop == "Label" and _origin_plane(obj):
            refresh(obj)


_obs = [None]


def install():
    if _obs[0] is None:
        _obs[0] = _Observer()
        App.addDocumentObserver(_obs[0])


class ToggleCommand(object):
    """Solid Design > Reference Names: on or off (kept between sessions)."""

    def GetResources(self):
        from .. import icon
        return {"Pixmap": icon("Plane"), "MenuText": "Reference Names",
                "ToolTip": "Shows the names of planes, axes, points and coordinate systems "
                           "in the 3D view.",
                "Checkable": enabled()}

    def IsActive(self):
        return True

    def Activated(self, checked=None):
        set_enabled(not enabled() if checked is None else bool(checked))
        try:
            Gui.updateGui()
        except Exception:
            pass
