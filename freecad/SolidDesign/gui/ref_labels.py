# SPDX-License-Identifier: LGPL-2.1-or-later
"""Names on reference geometry in the 3D view, as SolidWorks shows them: "Top
Plane" at a plane's corner, "Axis1" at an axis' end, beside a point or a
coordinate system's origin. The text stays the same size on screen however far
the view is zoomed. Turn them off in Solid Design > Reference Names.

A label is part of the object's own drawing, so it shows and hides with the
object. For the origin planes, which FreeCAD draws at a fixed size on screen,
it goes inside that scaled drawing, at the square's corner.
"""

import FreeCAD as App
import FreeCADGui as Gui

PARAMS = "User parameter:BaseApp/Preferences/Mod/SolidDesign"
NODE = "SD_RefLabel"
COLOR = (0.1, 0.28, 0.62)
FONT_SIZE = 12.0        # px
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

def _node(text, at):
    """A screen-size text at ``at`` (local coordinates), not pickable."""
    from pivy import coin
    sep = coin.SoSeparator()
    sep.setName(NODE)
    pick = coin.SoPickStyle()
    pick.style = coin.SoPickStyle.UNPICKABLE
    col = coin.SoBaseColor()
    col.rgb.setValue(*COLOR)
    font = coin.SoFont()
    font.name = "Sans"
    font.size = FONT_SIZE
    tr = coin.SoTranslation()
    tr.translation.setValue(at.x, at.y, at.z)
    txt = coin.SoText2()
    txt.string = str(text)
    for n in (pick, col, font, tr, txt):
        sep.addChild(n)
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
        for n in _children(sep):
            if n.getTypeId().getName().getString() == "Text2":
                out.append(n.string[0].getString().strip())
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

def anchor(obj):
    """(local point, text) of an object's label, or None."""
    import Part     # noqa: F401  (shapes)
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
            return inv.multVec(f.valueAt(u0, v1)), text           # its top-left corner
        if kind == "axis" and shape.Edges:
            return inv.multVec(shape.Edges[0].Vertexes[-1].Point), " " + text
        if kind == "point" and shape.Vertexes:
            return inv.multVec(shape.Vertexes[0].Point), "  " + text
        if kind == "csys" and shape.Edges:
            return inv.multVec(shape.Edges[0].Vertexes[0].Point), "  " + text
    except Exception:
        return None
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
        a = anchor(obj) if vo.Visibility else None
        if a is None:
            return
        at, text = a
        # Once, under the object's root (its display modes share nodes, so one
        # in each could be drawn twice); its view provider redoes it when the
        # object is shown or hidden.
        vo.RootNode.addChild(_node(text, at))
    except Exception as e:
        App.Console.PrintLog("Solid Design: label for {}: {}\n".format(obj.Name, e))


def _origin(obj, vo):
    """Inside FreeCAD's fixed-on-screen drawing of an origin plane, at the
    square's top-left corner."""
    from pivy import coin    # noqa: F401
    import FreeCAD
    scale = _find_type(vo.SwitchNode, "SoShapeScale")
    if scale is None:
        return
    shape = scale.getPart("shape", False)
    coords = _find_type(shape, "Coordinate3") if shape is not None else None
    if coords is None:
        return
    pts = [coords.point[i].getValue() for i in range(coords.point.getNum())]
    at = FreeCAD.Vector(min(p[0] for p in pts), max(p[1] for p in pts), 0)
    shape.addChild(_node(_clean(obj.Label), at))


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
