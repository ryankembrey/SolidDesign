# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Ryan Kembrey <ryan.FreeCAD@gmail.com>
# SPDX-FileNotice: Part of the Solid Design addon.

"""Scene shots: the workbench in FreeCAD, and what every shot shares.

Run inside FreeCAD by freecad_runner.py. Each shot gets a Context and returns a
QImage. Parts are built with the workbench's own functions (the ones its
commands call), and tools are opened with their commands and driven through
their panels, the way a user does, so the pictures show the real thing.

Imported by the build too (to know the shot ids), where there is no FreeCAD:
so FreeCAD is only imported inside functions.
"""

from __future__ import annotations

import math
import time

from . import shot

# -- the context -----------------------------------------------------------------


class Context:
    """What the shots share: the main window, making parts, picking, grabbing."""

    def __init__(self, mw):
        self.mw = mw
        self.record = None      # a tool shot's panel record, for panels.json

    # -- waiting and the view ------------------------------------------------------

    def pump(self, seconds: float = 0.3) -> None:
        from PySide6 import QtWidgets

        end = time.monotonic() + seconds
        while time.monotonic() < end:
            QtWidgets.QApplication.processEvents()
            time.sleep(0.01)

    def view(self):
        import FreeCADGui as Gui

        return Gui.ActiveDocument.ActiveView

    def iso(self, fit=True) -> None:
        v = self.view()
        v.setAnimationEnabled(False)
        v.viewIsometric()
        if fit:
            v.fitAll()
        self.pump(0.3)

    def camera(self, direction, up=(0, 0, 1)) -> None:
        """Look along *direction* (from the eye to the model), *up* upwards."""
        import FreeCAD as App

        v = self.view()
        v.setAnimationEnabled(False)
        d = App.Vector(*direction).normalize()
        u = App.Vector(*up)
        # A rotation taking the camera's -Z to d and its Y to up.
        z = -d
        x = u.cross(z).normalize()
        y = z.cross(x)
        m = App.Matrix(x.x, y.x, z.x, 0, x.y, y.y, z.y, 0, x.z, y.z, z.z, 0, 0, 0, 0, 1)
        v.setCameraOrientation(App.Rotation(m).Q)
        v.fitAll()
        self.pump(0.3)

    def zoom(self, factor: float) -> None:
        """Zoom in (>1) or out (<1) about the view's centre."""
        cam = self.view().getCameraNode()
        try:
            h = cam.height.getValue()
            cam.height.setValue(h / factor)
        except Exception:
            try:
                cam.scaleHeight(1.0 / factor)
            except Exception:
                pass
        self.pump(0.2)

    # -- documents and parts ----------------------------------------------------------

    def new_part(self, name: str = "Part"):
        """A new document with a Part in it, made as the Part command does."""
        import FreeCAD as App
        import FreeCADGui as Gui
        from freecad.SolidDesign.app import part as part_mod

        doc = App.newDocument(name)
        Gui.runCommand("SD_Part")
        self.pump(0.3)
        part = part_mod.find_parts(doc)[0]
        return doc, part

    def plane(self, part, name: str):
        from freecad.SolidDesign.app import part as part_mod

        for o in part.Origin:
            if part_mod.clean_label(o.Label) == name:
                return o
        raise KeyError(name)

    def axis(self, part, letter: str):
        """The origin's X, Y or Z axis."""
        for o in part.Origin:
            if o.TypeId in ("Part::DatumLine", "App::Line") and o.Label.startswith(letter):
                return o
        raise KeyError(letter)

    def box(self, name: str):
        """The open panel's selection box called *name* (spaces and case don't
        matter; "Direction 1" finds Direction1Ref)."""
        def norm(t):
            return "".join(c for c in (t or "").lower() if c.isalnum())

        p = self.panel()
        want = norm(name)
        for b in p.boxes:
            if norm(b.name) == want:
                return b
        for b in p.boxes:
            if norm(b.name).startswith(want) or want in norm(b.what):
                return b
        raise LookupError(f"no box {name!r} in {[b.name for b in p.boxes]}")

    def sketch(self, part, plane="Top Plane", at=(0, 0, 0), rotation=None, label=None):
        """An empty sketch on an origin plane of *part*, its origin moved by *at*
        (in the plane's own coordinates: x, y, and z along its normal)."""
        import FreeCAD as App
        from freecad.SolidDesign.app import part as part_mod

        doc = part.Document
        sk = doc.addObject("Sketcher::SketchObject", "Sketch")
        if label:
            sk.Label = label
        sk.AttachmentSupport = [(self.plane(part, plane), "")]
        sk.MapMode = "FlatFace"
        sk.AttachmentOffset = App.Placement(App.Vector(*at), rotation or App.Rotation())
        part_mod.add_to_part(part, sk)
        return sk

    def rect(self, sk, x0, y0, x1, y1):
        import FreeCAD as App
        import Part
        import Sketcher

        V = App.Vector
        pts = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
        first = len(sk.Geometry)
        for i in range(4):
            sk.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]))
        for i in range(4):
            sk.addConstraint(Sketcher.Constraint("Coincident", first + i, 2, first + (i + 1) % 4, 1))
        return sk

    def circle(self, sk, cx, cy, r):
        import FreeCAD as App
        import Part

        sk.addGeometry(Part.Circle(App.Vector(cx, cy, 0), App.Vector(0, 0, 1), r))
        return sk

    def line(self, sk, p0, p1, construction=False):
        import FreeCAD as App
        import Part

        sk.addGeometry(Part.LineSegment(App.Vector(*p0, 0), App.Vector(*p1, 0)), construction)
        return sk

    def arc(self, sk, cx, cy, r, a0, a1):
        import FreeCAD as App
        import Part

        sk.addGeometry(Part.ArcOfCircle(Part.Circle(App.Vector(cx, cy, 0), App.Vector(0, 0, 1), r),
                                        math.radians(a0), math.radians(a1)))
        return sk

    def extrude(self, part, sk, depth=10.0, mode="Add", merge=True, **props):
        """An Extrude made as its command makes it (no panel)."""
        from freecad.SolidDesign.app import extrude as app_extrude

        doc = part.Document
        f = app_extrude.create(doc, part, mode, sk)
        f.Depth = depth
        if not merge and "MergeResult" in f.PropertiesList:
            f.MergeResult = False
        for k, v in props.items():
            setattr(f, k, v)
        doc.recompute()
        try:
            sk.ViewObject.Visibility = False     # as OK in the panel leaves it
        except Exception:
            pass
        return f

    def bodies(self, part, kind=None):
        """The part's body views (solid and surface), or only one *kind*."""
        from freecad.SolidDesign.app import part as part_mod

        out = part_mod.body_views(part)
        return [v for v in out if kind is None or getattr(v, "Kind", "solid") == kind]

    def plate(self, w=60.0, d=40.0, t=8.0, name="Part"):
        """The sample part most tool shots start from: a plate on the Top Plane,
        centred on the origin, from z = 0 up to *t*."""
        doc, part = self.new_part(name)
        sk = self.rect(self.sketch(part), -w / 2, -d / 2, w / 2, d / 2)
        doc.recompute()
        f = self.extrude(part, sk, t)
        return doc, part, f

    def boss(self, part, x, y, r, h, z, merge=True):
        sk = self.circle(self.sketch(part, at=(0, 0, z)), x, y, r)
        part.Document.recompute()
        return self.extrude(part, sk, h, merge=merge)

    # -- finding faces and edges ---------------------------------------------------

    @staticmethod
    def face(obj, point, normal=None):
        """The name of the face of *obj* through *point* (facing *normal*)."""
        import FreeCAD as App

        p = App.Vector(*point)
        n = App.Vector(*normal) if normal is not None else None
        for i, f in enumerate(obj.Shape.Faces, 1):
            if f.isInside(p, 1e-6, True):
                if n is None:
                    return "Face%d" % i
                u, v = f.Surface.parameter(p)
                if f.normalAt(u, v).getAngle(n) < 1e-6:
                    return "Face%d" % i
        raise LookupError(f"no face of {obj.Label} at {point}")

    @staticmethod
    def edge(obj, p0, p1=None):
        """The name of the edge of *obj* from *p0* to *p1* (or through *p0*)."""
        import FreeCAD as App

        a = App.Vector(*p0)
        b = App.Vector(*p1) if p1 is not None else None
        for i, e in enumerate(obj.Shape.Edges, 1):
            if b is None:
                if e.distToShape(_vertex(p0))[0] < 1e-6:
                    return "Edge%d" % i
                continue
            ends = [v.Point for v in e.Vertexes]
            if len(ends) == 2 and ((ends[0] - a).Length < 1e-6 and (ends[1] - b).Length < 1e-6
                                   or (ends[0] - b).Length < 1e-6 and (ends[1] - a).Length < 1e-6):
                return "Edge%d" % i
        raise LookupError(f"no edge of {obj.Label} at {p0}")

    @staticmethod
    def edge_through(obj, point):
        p = _vertex(point)
        for i, e in enumerate(obj.Shape.Edges, 1):
            if e.distToShape(p)[0] < 1e-6:
                return "Edge%d" % i
        raise LookupError(f"no edge of {obj.Label} through {point}")

    # -- selecting and tools --------------------------------------------------------

    def select(self, *items) -> None:
        """Select objects or (object, sub-element) pairs, as clicks would."""
        import FreeCADGui as Gui

        Gui.Selection.clearSelection()
        for it in items:
            it = it if isinstance(it, tuple) else (it,)
            obj = it[0]
            sub = it[1] if len(it) > 1 else ""
            at = it[2] if len(it) > 2 else None
            if at is not None:
                Gui.Selection.addSelection(obj.Document.Name, obj.Name, sub, *at)
            elif sub:
                Gui.Selection.addSelection(obj.Document.Name, obj.Name, sub)
            else:
                Gui.Selection.addSelection(obj.Document.Name, obj.Name)
        self.pump(0.1)

    def run(self, command: str, seconds: float = 0.9):
        """Run a command as its toolbar button does; returns its panel (or None)."""
        import FreeCADGui as Gui

        Gui.runCommand(command)
        self.pump(seconds)
        if self.panel() is not None:
            self.show_tasks()
        return self.panel()

    def panel(self):
        from freecad.SolidDesign.gui.sketch_panel import LAST

        p = LAST[0]
        return p if p is not None and not getattr(p, "_closing", False) else None

    def pick(self, box, obj, sub="", point=None, seconds=0.5) -> None:
        """A click in the 3D view while *box* is the active selection box."""
        import FreeCAD as App
        from freecad.SolidDesign.gui.selection import Sel

        p = self.panel()
        p.activate(box)
        p.route(Sel(obj, sub, App.Vector(*point) if point is not None else None))
        self.pump(seconds)

    def set_value(self, field, value, seconds=0.6) -> None:
        """Type *value* into a panel's unit field (or a plain spin box)."""
        from PySide6 import QtWidgets

        spin = getattr(field, "spin", field)
        if isinstance(spin, QtWidgets.QSpinBox):
            spin.setValue(int(value))
        elif isinstance(spin, QtWidgets.QDoubleSpinBox):
            spin.setValue(float(value))
        elif not spin.setProperty("rawValue", float(value)):
            spin.setValue(value)
        self.pump(seconds)

    def reset(self) -> None:
        """Close whatever the last shot opened."""
        import FreeCAD as App
        import FreeCADGui as Gui

        p = self.panel()
        try:
            if p is not None:
                p._click_cancel()
            elif Gui.Control.activeDialog():
                Gui.Control.closeDialog()
        except Exception:
            pass
        self.pump(0.3)
        try:
            Gui.Control.closeDialog()
        except Exception:
            pass
        for w in _top_dialogs():
            w.close()
        for name in list(App.listDocuments()):
            try:
                App.closeDocument(name)
            except Exception:
                pass
        Gui.Selection.clearSelection()
        self.pump(0.3)

    # -- grabbing -----------------------------------------------------------------

    def tidy(self) -> None:
        """Hide what sits over the 3D view that a user's FreeCAD wouldn't show."""
        from PySide6 import QtWidgets

        # FreeCAD 1.1's dock overlay leaves its empty title bars (a grip and
        # three small buttons) over the view.
        for w in self.mw.findChildren(QtWidgets.QWidget):
            if w.isVisible() and w.metaObject().className() == "Gui::OverlayTitleBar":
                w.hide()
        for tb in self.mw.findChildren(QtWidgets.QToolBar):
            if tb.isVisible() and (tb.isFloating() or tb.parentWidget() is not self.mw):
                tb.hide()

    def window(self):
        """The main window below its menus and toolbars: the panel (or tree)
        on the left, the 3D view on the right."""
        from PySide6 import QtCore, QtWidgets

        self.tidy()
        self.pump(0.4)
        mdi = self.mw.findChild(QtWidgets.QMdiArea)
        top = mdi.mapTo(self.mw, QtCore.QPoint(0, 0)).y()
        for dock in self.mw.findChildren(QtWidgets.QDockWidget):
            y = dock.mapTo(self.mw, QtCore.QPoint(0, 0)).y()
            if dock.isVisible() and not dock.isFloating() and y > 0:
                top = min(top, y)
        bottom = mdi.mapTo(self.mw, QtCore.QPoint(0, mdi.height())).y()
        img = self.mw.grab().toImage()
        return img.copy(0, top, img.width(), bottom - top)

    def screen(self):
        """The screen where the main window is, below its toolbars: for pop-ups
        that are windows of their own (the command search)."""
        from PySide6 import QtCore, QtWidgets

        self.pump(0.4)
        img = self.window()            # for the crop's size and place
        mdi = self.mw.findChild(QtWidgets.QMdiArea)
        top = img.height()
        top_left = self.mw.mapToGlobal(QtCore.QPoint(0, mdi.mapTo(self.mw, QtCore.QPoint(0, mdi.height())).y() - top))
        shot = QtWidgets.QApplication.primaryScreen().grabWindow(0)
        return shot.toImage().copy(top_left.x(), top_left.y(), img.width(), top)

    def full_window(self):
        self.tidy()
        self.pump(0.4)
        return self.mw.grab().toImage()

    def view_only(self):
        """The 3D view alone."""
        from PySide6 import QtWidgets

        self.tidy()
        self.pump(0.4)
        mdi = self.mw.findChild(QtWidgets.QMdiArea)
        return mdi.grab().toImage()

    def widget(self, w, margin=0):
        self.pump(0.3)
        return w.grab().toImage()

    def area(self, x, y, w, h):
        """A rectangle of the main window."""
        self.pump(0.4)
        return self.mw.grab().toImage().copy(x, y, w, h)

    def task_view(self):
        from PySide6 import QtWidgets

        for w in self.mw.findChildren(QtWidgets.QWidget):
            if w.metaObject().className() == "Gui::TaskView::TaskView" and w.isVisible():
                return w
        return None

    def dock(self, name):
        from PySide6 import QtWidgets

        for d in self.mw.findChildren(QtWidgets.QDockWidget):
            if d.objectName() == name:
                return d
        return None

    def show_tree(self) -> None:
        """Bring the Model tab (the tree) to the front of the left dock."""
        d = self.dock("Model")
        if d is not None:
            d.raise_()
        self.pump(0.2)

    def show_tasks(self) -> None:
        d = self.dock("Tasks")
        if d is not None:
            d.raise_()
        self.pump(0.2)


def _vertex(point):
    import FreeCAD as App
    import Part

    return Part.Vertex(App.Vector(*point))


def _top_dialogs():
    from PySide6 import QtWidgets

    return [w for w in QtWidgets.QApplication.topLevelWidgets()
            if isinstance(w, QtWidgets.QDialog) and w.isVisible()]


# -- recording a panel -----------------------------------------------------------------


def _text(w) -> str:
    t = w.text() if hasattr(w, "text") else ""
    return (t or "").replace("&", "").strip()


def _describe(w) -> dict:
    """What a panel control is, for its page: kind, choices, unit..."""
    from PySide6 import QtWidgets
    from freecad.SolidDesign.gui.panel import parts

    if isinstance(w, parts.Switch):
        return {"kind": "switch", "choices": list(w.buttons)}
    if isinstance(w, parts.QuantityField):
        return {"kind": "number", "unit": getattr(w, "unit", "") or "", "prop": w.prop}
    if isinstance(w, parts.IntField):
        return {"kind": "count", "prop": getattr(w, "prop", "")}
    if isinstance(w, parts.SelectionList):
        return {"kind": "picks", "name": w.name or "", "what": w.what or "", "hint": w.hint or "",
                "items": len(w.items)}
    if isinstance(w, parts.SelectionField):
        return {"kind": "pick", "name": w.name or "", "what": w.what or "", "hint": w.hint or "",
                "items": len(w.items)}
    if isinstance(w, QtWidgets.QComboBox):
        return {"kind": "choice", "choices": [w.itemText(i) for i in range(w.count())]}
    if isinstance(w, QtWidgets.QCheckBox):
        return {"kind": "check", "text": _text(w)}
    if isinstance(w, QtWidgets.QRadioButton):
        return {"kind": "option", "text": _text(w)}
    if isinstance(w, QtWidgets.QAbstractButton):
        return {"kind": "button", "text": _text(w)}
    if isinstance(w, QtWidgets.QAbstractSpinBox):
        return {"kind": "number"}
    if isinstance(w, QtWidgets.QTableWidget):
        heads = [w.horizontalHeaderItem(i).text() for i in range(w.columnCount())
                 if w.horizontalHeaderItem(i) is not None]
        return {"kind": "table", "columns": heads}
    if isinstance(w, QtWidgets.QAbstractItemView):
        return {"kind": "list"}
    if isinstance(w, QtWidgets.QLineEdit):
        return {"kind": "text"}
    if isinstance(w, QtWidgets.QLabel):
        return {"kind": "note", "text": _text(w)}
    # A row of several controls (a field and its flip button): describe the
    # main one, and say what else is there.
    inner = [c for c in w.findChildren(QtWidgets.QWidget, options=QtCore_children())
             if _is_control(c)]
    if inner:
        d = _describe(inner[0])
        extra = [_describe(c) for c in inner[1:]]
        if extra:
            d["with"] = extra
        return d
    return {"kind": "other"}


def QtCore_children():
    from PySide6 import QtCore

    return QtCore.Qt.FindChildOption.FindDirectChildrenOnly


def _is_control(w) -> bool:
    from PySide6 import QtWidgets
    from freecad.SolidDesign.gui.panel import parts

    return isinstance(w, (parts.Switch, parts.QuantityField, parts.IntField, parts._Selection,
                          QtWidgets.QComboBox, QtWidgets.QAbstractButton,
                          QtWidgets.QAbstractSpinBox, QtWidgets.QAbstractItemView,
                          QtWidgets.QLineEdit))


def _control(w, label=None, root=None) -> dict:
    d = _describe(w)
    d["tip"] = (w.toolTip() or (label.toolTip() if label is not None else "") or "").strip()
    if label is not None:
        d["label"] = _text(label)
        from PySide6 import QtWidgets

        if isinstance(label, QtWidgets.QCheckBox):
            d["optional"] = True        # a check box turns the control on
    d["shown"] = bool(w.isVisibleTo(root)) if root is not None else True
    return d


def _group(g, form) -> dict:
    from PySide6 import QtWidgets

    out = {"title": g.title().replace("&", ""), "tip": (g.toolTip() or "").strip(),
           "optional": g.isCheckable(), "shown": bool(g.isVisibleTo(form)), "rows": []}
    grid = getattr(g, "grid", None)
    if grid is None:
        lay = g.layout()
        for i in range(lay.count() if lay else 0):
            w = lay.itemAt(i).widget()
            if w is not None and _is_control(w):
                out["rows"].append(_control(w, root=g))
        return out
    seen = set()
    for r in range(grid.rowCount()):
        a = grid.itemAtPosition(r, 0)
        b = grid.itemAtPosition(r, 1)
        wa = a.widget() if a is not None else None
        wb = b.widget() if b is not None else None
        if wa is None and wb is None:
            continue
        if wa is not None and wa is wb or wb is None:     # across the group
            if id(wa) in seen:
                continue
            seen.add(id(wa))
            if isinstance(wa, QtWidgets.QLabel):
                if _text(wa):
                    out["rows"].append({"kind": "note", "text": _text(wa),
                                        "shown": bool(wa.isVisibleTo(g))})
                continue
            out["rows"].append(_control(wa, root=g))
            continue
        out["rows"].append(_control(wb, label=wa, root=g))
    return out


def record_panel(command: str, panel) -> dict:
    """The panel's groups and controls, top to bottom, as panels.json keeps them."""
    from PySide6 import QtWidgets
    from freecad.SolidDesign.gui.panel import parts

    form = panel.widget
    lay = form.layout()
    items = []
    for i in range(lay.count()):
        w = lay.itemAt(i).widget()
        if w is None:
            continue
        if isinstance(w, QtWidgets.QGroupBox):
            items.append({"group": _group(w, form)})
        elif isinstance(w, parts.Message):
            continue
        elif _is_control(w) or isinstance(w, QtWidgets.QWidget) and w.findChildren(parts.Switch):
            items.append({"control": _control(w, root=form)})
    handles = []
    try:
        drag = panel.draggers()
        for d in (drag.draggers() if drag is not None else []):
            if d.prop not in handles:
                handles.append(d.prop)
    except Exception:
        pass
    error = ""
    try:
        error = panel.error.value()
    except Exception:
        pass
    return {"command": command, "title": getattr(panel, "TITLE", ""), "items": items,
            "handles": handles, "error": error}


# -- guide shots --------------------------------------------------------------------


@shot("interface", "The Solid Design workbench: its toolbars along the top, the part in the tree "
                   "and the 3D view")
def interface(ctx):
    doc, part, f = ctx.plate()
    ctx.boss(part, 15, 0, 8, 12, 8)
    doc.recompute()
    ctx.show_tree()
    _expand_tree(ctx)
    ctx.iso()
    return ctx.full_window()


def _broken_part(ctx):
    """A plate with a boss whose top edge is filleted, then the boss suppressed:
    the fillet loses its edge (What's Wrong's usual case)."""
    doc, part, f = ctx.plate()
    boss = ctx.boss(part, 15, 0, 6, 10, 8)
    from freecad.SolidDesign.app import dressup

    rim = [("Edge%d" % i) for i, e in enumerate(boss.Shape.Edges, 1)
           if hasattr(e.Curve, "Radius") and abs(e.BoundBox.ZMin - 18) < 1e-6]
    fil = dressup.create_fillet(doc, part, rim)
    fil.Radius = 2
    doc.recompute()
    boss.Suppressed = True
    doc.recompute()
    return doc, part


def whats_wrong_dialog(ctx):
    doc, part = _broken_part(ctx)
    ctx.iso()
    ctx.select()
    ctx.run("SD_WhatsWrong", 1.5)
    from freecad.SolidDesign.gui import evaluate

    dlg = evaluate.LAST[0]
    try:
        tree = dlg.tree
        if tree.topLevelItemCount():
            tree.setCurrentItem(tree.topLevelItem(0))
    except Exception:
        pass
    ctx.pump(1.0)
    return ctx.window()


def command_search_box(ctx):
    from PySide6 import QtTest
    from freecad.SolidDesign.gui import command_search

    doc, part, f = ctx.plate()
    ctx.iso()
    box = command_search.show()
    ctx.pump(0.4)
    QtTest.QTest.keyClicks(box.edit, "pat")
    ctx.pump(0.5)
    img = ctx.screen()
    box.close()
    return img


def command_line_bar(ctx):
    from PySide6 import QtTest
    from freecad.SolidDesign.gui import command_line

    doc, part, f = ctx.plate()
    ctx.iso()
    bar = command_line.open_bar()
    ctx.pump(0.4)
    QtTest.QTest.keyClicks(bar.edit, "fillet 2 sel=")
    ctx.pump(1.0)
    img = ctx.screen()
    try:
        bar.close_bar() if hasattr(bar, "close_bar") else bar.hide()
    except Exception:
        pass
    return img


def context_toolbar_shot(ctx):
    from PySide6 import QtCore, QtGui

    doc, part, f = ctx.plate()
    ctx.iso()
    v = ctx.bodies(part)[0]
    view = ctx.mw.findChild(__import__("PySide6.QtWidgets", fromlist=["QMdiArea"]).QMdiArea)
    QtGui.QCursor.setPos(view.mapToGlobal(view.rect().center()))
    ctx.select((v, ctx.face(v, (0, 0, 8), (0, 0, 1))))
    ctx.pump(0.8)
    _ = QtCore
    return ctx.screen()


def reference_labels_shot(ctx):
    doc, part, f = ctx.plate()
    from freecad.SolidDesign.app import refgeom

    v = ctx.bodies(part)[0]
    refgeom.create_plane(doc, part, references=[(v, ctx.face(v, (0, 0, 8), (0, 0, 1)))])
    doc.recompute()
    ctx.iso()
    ctx.zoom(0.8)
    return ctx.view_only()


@shot("tree-bodies", "The tree of a part with two bodies: its origin, its Solid Bodies folder "
                     "and its features in order")
def tree_bodies(ctx):
    doc, part, f = ctx.plate()
    ctx.boss(part, 30, 0, 10, 12, 0, merge=False)
    doc.recompute()
    ctx.show_tree()
    ctx.iso()
    _expand_tree(ctx)
    return ctx.window()


def _expand_tree(ctx):
    from PySide6 import QtWidgets

    for t in ctx.mw.findChildren(QtWidgets.QTreeWidget):
        if t.metaObject().className() == "Gui::TreeWidget" and t.isVisible():
            t.expandAll()
    ctx.pump(0.3)


@shot("drag-handles", "Drag handles on a selected Extrude: arrows for its depth in the 3D view")
def drag_handles(ctx):
    doc, part, f = ctx.plate()
    ctx.iso()
    ctx.select(f)
    ctx.pump(1.0)
    return ctx.view_only()


@shot("rolled-back", "A part rolled back: the features after the rollback bar are greyed and "
                     "not built")
def rolled_back(ctx):
    doc, part, f = ctx.plate()
    boss = ctx.boss(part, 15, 0, 6, 10, 8)
    from freecad.SolidDesign.app import part as part_mod

    part_mod.roll_to(part, f)
    doc.recompute()
    _ = boss
    ctx.show_tree()
    _expand_tree(ctx)
    ctx.iso()
    return ctx.window()


@shot("plane-prompt", "Sketch with nothing selected: the origin planes show and the status bar "
                      "asks for one")
def plane_prompt(ctx):
    doc, part, f = ctx.plate()
    ctx.iso()
    ctx.select()
    ctx.run("SD_Sketch", 1.0)
    ctx.iso()
    return ctx.full_window()


@shot("health-badge", "The health badge in the status bar, counting a part's problems")
def health_badge(ctx):
    doc, part = _broken_part(ctx)
    ctx.pump(1.0)
    from freecad.SolidDesign.gui import health_badge as hb

    b = hb.current()
    if b is None:
        raise RuntimeError("no health badge")
    sb = ctx.mw.statusBar()
    from PySide6 import QtCore

    pos = b.mapTo(ctx.mw, QtCore.QPoint(0, 0))
    top = sb.mapTo(ctx.mw, QtCore.QPoint(0, 0)).y()
    img = ctx.mw.grab().toImage()
    left = max(0, pos.x() - 8)
    return img.copy(left, top, min(img.width() - left, b.width() + 16), sb.height())
