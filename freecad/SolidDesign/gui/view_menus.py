# SPDX-License-Identifier: LGPL-2.1-or-later
"""Solid Design's own right-click menus in the 3D view, one for what's under the
pointer: empty space, a face, an edge, a vertex, or a plane, axis or sketch.

They replace FreeCAD's menu while Solid Design is the workbench and no tool or
sketch is open (FreeCAD's comes back otherwise): each right click switches the
view's own menu off or on before FreeCAD would open it. Right-drag navigation is
untouched: only a click (a press and release without moving) opens a menu.

As in SolidWorks, right-clicking something selects it, unless it's already part
of the selection (then the menu acts on everything selected). A few of FreeCAD's
own commands are reused (Normal To, Zoom to Selection, Measure, Clarify Selection,
the standard views, draw styles, appearance, undo).
"""

import FreeCAD as App
import FreeCADGui as Gui

CLICK_PX = 6            # a press and release this close is a click, not a drag

# FreeCAD's draw styles (Std_DrawStyle's entries).
DRAW_STYLES = [("Shaded With Edges", 6), ("Shaded", 5), ("Wireframe", 2),
               ("Hidden Line", 3)]


# ------------------------------------------------------------------ building

def _icon(pix):
    """A command's icon: a file (Solid Design's) or one of FreeCAD's by name."""
    from PySide import QtGui
    if not pix:
        return QtGui.QIcon()
    if pix.endswith(".svg") or pix.endswith(".png"):
        return QtGui.QIcon(pix)
    try:
        return Gui.getIcon(pix) or QtGui.QIcon()
    except Exception:
        return QtGui.QIcon()


class Menu(object):
    """A QMenu built from FreeCAD commands and functions."""

    def __init__(self, title=None, parent=None):
        from PySide import QtWidgets
        self.qmenu = QtWidgets.QMenu(parent)
        self.qmenu.setObjectName("SD_ViewMenu")
        if title:
            self.qmenu.setTitle(title)

    def section(self, text):
        """A bold title row (Qt's sections draw as a bare line in many styles)."""
        a = self.qmenu.addAction(text)
        a.setEnabled(False)
        a.setData("title")
        f = a.font()
        f.setBold(True)
        a.setFont(f)
        self.qmenu.addSeparator()
        return a

    def sep(self):
        self.qmenu.addSeparator()

    def cmd(self, name, label=None, arg=None):
        """A FreeCAD command, greyed when it can't run now; none if it doesn't exist."""
        c = Gui.Command.get(name)
        if c is None:
            return None
        info = c.getInfo()
        text = (label or info.get("menuText", name)).replace("&", "")
        if text[:1].isdigit() and text[1:2] == " ":
            text = text[2:]                     # "1 Front" in FreeCAD's View menu
        if info.get("shortcut"):
            text += "\t" + info["shortcut"]
        icon = _icon(info.get("pixmap", ""))
        a = self.qmenu.addAction(icon, text)
        a.setEnabled(bool(c.isActive()))
        a.setData(name)
        a.triggered.connect(lambda checked=False, n=name, x=arg:
                            Gui.runCommand(n) if x is None else Gui.runCommand(n, x))
        return a

    def fn(self, label, callback, shortcut="", enabled=True, icon=None):
        from PySide import QtGui
        a = self.qmenu.addAction(icon or QtGui.QIcon(), label + ("\t" + shortcut if shortcut
                                                                   else ""))
        a.setEnabled(enabled)
        a.triggered.connect(lambda checked=False: callback())
        return a

    def sub(self, title):
        m = Menu(title, self.qmenu)
        self.qmenu.addMenu(m.qmenu)
        return m

    def actions(self):
        return [a for a in self.qmenu.actions() if not a.isSeparator() and a.data() != "title"]

    def title(self):
        t = [a.text() for a in self.qmenu.actions() if a.data() == "title"]
        return t[0] if t else ""


# ------------------------------------------------------------------ what was clicked

class Hit(object):
    """What's under the pointer: a body's face, edge or vertex, another object, or
    nothing."""

    def __init__(self, doc=None, obj=None, sub=""):
        self.doc, self.obj, self.sub = doc, obj, sub

    @property
    def kind(self):
        """"space", "Face", "Edge", "Vertex" (of a body) or "object"."""
        from ..app import util
        if self.obj is None:
            return "space"
        if util.is_body_view(self.obj):
            for k in ("Face", "Edge", "Vertex"):
                if self.sub.startswith(k):
                    return k
        return "object"

    def element(self):
        import Part
        try:
            return Part.getShape(self.obj, self.sub, needSubElement=True)
        except Exception:
            return None


def hit_at(view, x, y):
    """What's at (x, y) in the view's widget (pixels from the top left)."""
    try:
        h = view.getSize()[1]
        info = view.getObjectInfo((int(x), int(h - y)))
    except Exception:
        info = None
    if not info:
        return Hit()
    doc = App.getDocument(info["Document"])
    obj = doc.getObject(info["Object"]) if doc else None
    return Hit(doc, obj, info.get("Component", "") or "")


def select_hit(hit):
    """Right-click selects what it's on, unless that's already selected."""
    if hit.obj is None:
        return
    for s in Gui.Selection.getSelectionEx():
        if s.Object is hit.obj and (not hit.sub or hit.sub in s.SubElementNames):
            return
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(hit.doc.Name, hit.obj.Name, hit.sub)


# ------------------------------------------------------------------ actions

_isolated = {}              # view name -> its visibility before Isolate


def isolate(views):
    """Show only ``views`` (bodies) until Exit Isolate."""
    from ..app import part as part_mod, util
    exit_isolate()
    keep = {v.Name for v in views}
    for v in views:
        p = util.part_of(v) or part_mod.source_part(v)
        for o in part_mod.body_views(p) if p is not None else []:
            if o.Name not in keep:
                _isolated[o.Name] = (o.Document.Name, o.ViewObject.Visibility)
                o.ViewObject.Visibility = False


def exit_isolate():
    for name, (dname, vis) in list(_isolated.items()):
        try:
            App.getDocument(dname).getObject(name).ViewObject.Visibility = vis
        except Exception:
            pass
    _isolated.clear()


def _selected_views():
    from ..app import util
    out = []
    for s in Gui.Selection.getSelectionEx():
        if util.is_body_view(s.Object) and s.Object not in out:
            out.append(s.Object)
    return out


def hide_bodies(views):
    for v in views:
        v.ViewObject.Visibility = False
    Gui.Selection.clearSelection()


def show_hidden_bodies(doc):
    from ..app import part as part_mod
    for p in part_mod.find_parts(doc):
        for v in part_mod.body_views(p):
            if not v.ViewObject.Visibility and v.Name not in _isolated:
                v.ViewObject.Visibility = True


def select_tangency(hit):
    """Add what's tangent to the picked face(s) or edge(s) to the selection."""
    from ..core.features import edges as core_edges
    body = hit.obj
    shape = body.Shape
    picked = []
    for s in Gui.Selection.getSelectionEx():
        if s.Object is body:
            picked += [n for n in s.SubElementNames if n[:4] == hit.sub[:4]]
    picked = picked or [hit.sub]
    elems = [shape.getElement(n) for n in picked]
    if hit.kind == "Face":
        found, pool, prefix = core_edges.tangent_faces(shape, elems), shape.Faces, "Face"
    else:
        found, pool, prefix = core_edges.tangent_chain(shape, elems), shape.Edges, "Edge"
    for e in found:
        for i, g in enumerate(pool, 1):
            if g.isSame(e):
                Gui.Selection.addSelection(hit.doc.Name, body.Name, "%s%d" % (prefix, i))
                break


def feature_of(hit):
    """The feature that made what was clicked, or None."""
    from ..app import part as part_mod
    elem = hit.element()
    part = part_mod.source_part(hit.obj)
    if elem is None or part is None:
        return None
    try:
        return part_mod.feature_of_element(part, elem)
    except Exception:
        return None


def edit(obj):
    Gui.Selection.clearSelection()
    Gui.ActiveDocument.setEdit(obj.Name, 0)


def body_name(view):
    from ..app import part as part_mod
    return part_mod.clean_label(view.Label)


def _last_label():
    from . import command_line
    last = command_line._last[0]
    if last is None:
        return None
    c = Gui.Command.get(last[0])
    return c.getInfo().get("menuText", last[0]).replace("&", "") if c else last[0]


# ------------------------------------------------------------------ the menus

def _keyboard(m):
    """The keyboard tools: search, command line, repeat."""
    from . import command_line, command_search
    m.fn("Command Search…", command_search.show, "/")
    m.fn("Command Line…", lambda: command_line.open_bar(None), ":")
    last = _last_label()
    m.fn("Repeat " + last if last else "Repeat Last Feature", command_line.repeat, ".",
         enabled=last is not None)


def _view(m):
    v = m.sub("View")
    for name in ("Std_ViewFitAll", "Std_ViewIsometric", "Std_ViewFront", "Std_ViewTop",
                 "Std_ViewRight"):
        v.cmd(name)
    v.sep()
    v.cmd("Std_PerspectiveCamera")
    v.cmd("Std_OrthographicCamera")
    d = v.sub("Draw Style")
    for label, i in DRAW_STYLES:
        d.cmd("Std_DrawStyle", label, i)


def _body(m, hit):
    """The body the clicked element belongs to (or the selected bodies)."""
    views = _selected_views() or [hit.obj]
    b = m.sub("Body: " + body_name(hit.obj) if len(views) == 1 else
              "%d Bodies" % len(views))
    b.fn("Hide", lambda: hide_bodies(views), "Space")
    b.fn("Isolate", lambda: isolate(views))
    b.sep()
    for name in ("SD_MoveCopy", "SD_Combine", "SD_Split", "SD_DeleteBody"):
        b.cmd(name)
    b.sep()
    b.cmd("Std_SetAppearance")
    b.cmd("Std_RandomColor")


def _select(m, hit):
    m.fn("Select Tangency", lambda: select_tangency(hit))
    m.cmd("Std_ClarifySelection")


def _look(m, normal_to=False):
    if normal_to:
        m.cmd("Std_AlignToSelection", "Normal To")
    m.cmd("Std_ViewFitSelection", "Zoom to Selection")
    m.cmd("Std_Measure")


def _edit_feature(m, hit):
    f = feature_of(hit)
    if f is not None:
        m.fn("Edit " + f.Label, lambda: edit(f))


def space_menu(hit):
    m = Menu()
    m.section("Solid Design")
    _keyboard(m)
    m.sep()
    m.cmd("SD_Sketch")
    m.cmd("SD_Part")
    r = m.sub("Reference Geometry")
    for name in ("SD_Plane", "SD_Axis", "SD_Point", "SD_CoordinateSystem"):
        r.cmd(name)
    m.sep()
    _view(m)
    if _isolated:
        m.fn("Exit Isolate", exit_isolate)
    m.fn("Show Hidden Bodies", lambda: show_hidden_bodies(App.ActiveDocument),
         enabled=App.ActiveDocument is not None)
    m.sep()
    m.cmd("SD_Rebuild")
    m.cmd("SD_WhatsWrong")
    m.sep()
    m.cmd("Std_Undo")
    m.cmd("Std_Redo")
    return m


def face_menu(hit):
    m = Menu()
    m.section("Face · " + body_name(hit.obj))
    m.cmd("SD_Sketch", "Sketch on Face")
    m.cmd("SD_Extrude", "Extrude from Face")
    _edit_feature(m, hit)
    m.sep()
    for name in ("SD_Fillet", "SD_Chamfer", "SD_Shell"):
        m.cmd(name)
    more = m.sub("More Face Tools")
    for name in ("SD_Draft", "SD_Dome", "SD_MoveFace", "SD_OffsetSurface", "SD_DeleteFace",
                 "SD_ReplaceFace", "SD_Thicken"):
        more.cmd(name)
    m.sep()
    m.cmd("SD_Plane", "Plane on Face")
    _look(m, normal_to=True)
    m.sep()
    _select(m, hit)
    m.sep()
    _body(m, hit)
    return m


def edge_menu(hit):
    m = Menu()
    m.section("Edge · " + body_name(hit.obj))
    m.cmd("SD_Fillet")
    m.cmd("SD_Chamfer")
    _edit_feature(m, hit)
    m.sep()
    r = m.sub("Reference Geometry")
    r.cmd("SD_Axis", "Axis Along Edge")
    r.cmd("SD_Plane", "Plane Normal to Edge")
    r.cmd("SD_Point", "Point on Edge")
    _look(m)
    m.sep()
    _select(m, hit)
    m.sep()
    _body(m, hit)
    return m


def vertex_menu(hit):
    m = Menu()
    m.section("Vertex · " + body_name(hit.obj))
    m.cmd("SD_Point", "Point at Vertex")
    m.cmd("SD_CoordinateSystem", "Coordinate System at Vertex")
    _edit_feature(m, hit)
    m.sep()
    _look(m)
    m.cmd("Std_ClarifySelection")
    m.sep()
    _body(m, hit)
    return m


def object_menu(hit):
    """A plane, axis, point or sketch (anything that isn't a body)."""
    obj = hit.obj
    m = Menu()
    m.section(obj.Label)
    sketch = obj.TypeId.startswith("Sketcher::")
    plane = "Plane" in obj.TypeId or getattr(getattr(obj, "Proxy", None), "KIND", "") == "plane"
    if sketch:
        m.fn("Edit Sketch", lambda: edit(obj))
        for name in ("SD_Extrude", "SD_Revolve"):
            m.cmd(name)
    else:
        if plane:
            m.cmd("SD_Sketch", "Sketch on Plane")
        if getattr(obj, "Proxy", None) is not None and hasattr(obj.ViewObject, "Proxy") and \
                hasattr(obj.ViewObject.Proxy, "setEdit"):
            m.fn("Edit " + obj.Label, lambda: edit(obj))
    m.sep()
    if plane or sketch:
        m.cmd("Std_AlignToSelection", "Normal To")
    m.cmd("Std_ViewFitSelection", "Zoom to Selection")
    m.sep()
    m.fn("Hide", lambda: hide_bodies([obj]), "Space")
    m.cmd("Std_Delete")
    return m


MENUS = {"space": space_menu, "Face": face_menu, "Edge": edge_menu, "Vertex": vertex_menu,
         "object": object_menu}


def menu_for(hit):
    """The menu for what was clicked (selecting it first)."""
    if hit.kind != "space":
        select_hit(hit)
    return MENUS[hit.kind](hit)


# ------------------------------------------------------------------ the mouse

def ours():
    """Whether a right click in the 3D view is Solid Design's now: its workbench,
    nothing being edited (no tool, no sketch)."""
    try:
        if type(Gui.activeWorkbench()).__name__ != "SolidDesignWorkbench":
            return False
        if Gui.Control.activeDialog() or Gui.ActiveDocument is None:
            return False
        if Gui.ActiveDocument.getInEdit() is not None:
            return False
        return hasattr(Gui.ActiveDocument.ActiveView, "setPopupMenuEnabled")
    except Exception:
        return False


_shown = [None]             # the menu last shown (for tests)


def _make_filter():
    from PySide import QtCore

    class Clicks(QtCore.QObject):
        def __init__(self):
            super(Clicks, self).__init__()
            self.press = None
            self.mine = False

        def eventFilter(self, obj, ev):
            t = ev.type()
            if t not in (QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonRelease):
                return False
            try:
                if ev.button() != QtCore.Qt.RightButton or \
                        obj.metaObject().className() != "QOpenGLWidget":
                    return False
            except Exception:
                return False
            pos = ev.position().toPoint() if hasattr(ev, "position") else ev.pos()
            if t == QtCore.QEvent.MouseButtonPress:
                self.press = (pos.x(), pos.y())
                self.mine = ours()
                try:
                    # Before FreeCAD's navigation sees the click: its menu or ours.
                    Gui.ActiveDocument.ActiveView.setPopupMenuEnabled(not self.mine)
                except Exception:
                    self.mine = False
                return False
            if self.mine and self.press is not None and \
                    abs(pos.x() - self.press[0]) + abs(pos.y() - self.press[1]) <= CLICK_PX:
                g = obj.mapToGlobal(pos)
                x, y = pos.x(), pos.y()
                QtCore.QTimer.singleShot(0, lambda: show_at(x, y, g))
            self.press = None
            return False

    return Clicks()


def show_at(x, y, global_pos, run=True):
    """Open the menu for what's at (x, y) in the 3D view."""
    view = Gui.ActiveDocument.ActiveView
    m = menu_for(hit_at(view, x, y))
    _shown[0] = m
    if run:
        m.qmenu.popup(global_pos)
    return m


_filter = [None]


def install():
    from PySide import QtWidgets
    if _filter[0] is None:
        _filter[0] = _make_filter()
        QtWidgets.QApplication.instance().installEventFilter(_filter[0])


def restore():
    """FreeCAD's own menus back in every 3D view (leaving the workbench). Runs while
    FreeCAD quits too, when a document's GUI side can already be gone while the
    document is still listed, so a missing one is skipped, never an error."""
    for d in list(App.listDocuments().values()):
        try:
            g = Gui.getDocument(d.Name)
            views = g.mdiViewsOfType("Gui::View3DInventor") if g else []
        except Exception:
            continue
        for v in views:
            try:
                v.setPopupMenuEnabled(True)
            except Exception:
                pass
