# SPDX-License-Identifier: LGPL-2.1-or-later
"""Labels beyond the 3D view, as Vimium puts them on a page's links: on the tree's
rows (for ":edit ", ":suppress "...), on an open panel's controls (":" with a
panel open) and on the toolbar buttons (":toolbar").

Each label is a WidgetHint placed in its host widget's coordinates; the hint
overlay (hints.make_overlay) draws them over the host.
"""

import FreeCAD as App
import FreeCADGui as Gui


class WidgetHint(object):
    """A label on a widget (or a tree row): ``code``, where it shows in ``host``
    coordinates, and what it is for (``target``: a widget, or a document object)."""

    def __init__(self, target, x, y, name="", host=None):
        self.target, self.x, self.y, self.name, self.host = target, x, y, name, host
        self.code = ""
        self.kind = "Widget"
        self.sub = name

    def key(self):
        t = self.target
        try:
            return ("tree", t.Document.Name, t.Name)
        except Exception:
            return ("widget", str(id(t)), self.name)


# ------------------------------------------------------------------ the tree

def tree_widget():
    from PySide import QtWidgets
    for t in Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget):
        if t.metaObject().className() == "Gui::TreeWidget" and t.isVisible():
            return t
    return None


def _items(tree):
    out = []

    def walk(it):
        out.append(it)
        if it.isExpanded():
            for i in range(it.childCount()):
                walk(it.child(i))
    for i in range(tree.topLevelItemCount()):
        walk(tree.topLevelItem(i))
    return out


def tree_hints(objs, part=None):
    """Labels on the tree rows of ``objs`` that can be seen (``part``'s row is
    opened first, so its features show). (tree, [hints])."""
    from ..app import part as part_mod
    tree = tree_widget()
    if tree is None:
        return None, []
    if part is not None:
        for it in _items(tree):
            if it.text(0) == part.Label and not it.isExpanded():
                tree.expandItem(it)
                tree.doItemsLayout()
                break
    by_label = {}
    for o in objs:
        by_label.setdefault(o.Label, o)
        by_label.setdefault(part_mod.clean_label(o.Label), o)
    vp = tree.viewport()
    out = []
    seen = set()
    for it in _items(tree):
        o = by_label.get(it.text(0))
        if o is None or o.Name in seen:
            continue
        r = tree.visualItemRect(it)
        if r.isEmpty() or r.bottom() < 0 or r.top() > vp.height():
            continue
        seen.add(o.Name)
        out.append(WidgetHint(o, r.left() + 10, r.center().y(), part_mod.clean_label(o.Label),
                              vp))
    return vp, out


# ------------------------------------------------------------------ a panel's controls

def _row_labels(form):
    """{control: the text of the row label beside it} for a panel built of
    parts.Group rows."""
    from PySide import QtWidgets
    from .panel import parts
    out = {}
    for g in form.findChildren(parts.Group):
        grid = getattr(g, "grid", None)
        if grid is None:
            continue
        for r in range(grid.rowCount()):
            a = grid.itemAtPosition(r, 0)
            b = grid.itemAtPosition(r, 1)
            wa = a.widget() if a is not None else None
            wb = b.widget() if b is not None else None
            if wa is None or wb is None or wa is wb:
                continue
            text = wa.text() if hasattr(wa, "text") else ""
            if not text:
                continue
            out[wb] = text.replace("&", "")
            for c in wb.findChildren(QtWidgets.QWidget):
                out.setdefault(c, text.replace("&", ""))
    return out


def controls(form):
    """[(widget, name)] of an open panel that a label can go to, top to bottom."""
    from PySide import QtWidgets
    from .panel import parts
    labels = _row_labels(form)
    out = []
    taken = set()

    def inside_selection(w):
        p = w.parentWidget()
        while p is not None and p is not form:
            if isinstance(p, (parts._Selection, QtWidgets.QAbstractSpinBox)):
                return True
            p = p.parentWidget()
        return False

    for w in form.findChildren(QtWidgets.QWidget):
        if not w.isVisible() or id(w) in taken:
            continue
        name = ""
        if isinstance(w, parts._Selection):
            name = labels.get(w) or (w.name or "")
        elif isinstance(w, QtWidgets.QGroupBox):
            if not w.isCheckable():
                continue
            name = w.title().replace("&", "")
        elif isinstance(w, (QtWidgets.QAbstractSpinBox, QtWidgets.QComboBox)):
            if inside_selection(w):
                continue
            name = labels.get(w, "")
        elif isinstance(w, QtWidgets.QAbstractButton):
            if inside_selection(w):
                continue
            name = w.text().replace("&", "") or labels.get(w, "") or w.toolTip()[:30]
        elif isinstance(w, QtWidgets.QLineEdit):
            if inside_selection(w) or isinstance(w.parentWidget(), QtWidgets.QAbstractSpinBox):
                continue
            name = labels.get(w, "")
        else:
            continue
        taken.add(id(w))
        out.append((w, name))
    out.sort(key=lambda wn: (wn[0].mapTo(form, wn[0].rect().topLeft()).y(),
                             wn[0].mapTo(form, wn[0].rect().topLeft()).x()))
    return out


def panel_hints(panel):
    """Labels on an open panel's controls. (host, [hints])."""
    from PySide import QtCore
    form = getattr(panel, "widget", None)
    if form is None:
        return None, []
    out = []
    for w, name in controls(form):
        # Just left of the control, so its text still shows.
        p = w.mapTo(form, QtCore.QPoint(0, w.height() // 2))
        out.append(WidgetHint(w, max(12, p.x() - 10), p.y(), name, form))
    return form, out


def go(w):
    """Go to a control: a field takes the keys, a button is pressed, a box becomes
    the active one, a list opens."""
    from PySide import QtWidgets
    from .panel import parts
    if isinstance(w, parts._Selection):
        w.activated.emit(w)
        return
    if isinstance(w, QtWidgets.QGroupBox):
        w.setChecked(not w.isChecked())
        return
    if isinstance(w, QtWidgets.QComboBox):
        w.setFocus()
        w.showPopup()
        return
    if isinstance(w, QtWidgets.QAbstractButton):
        w.click()
        return
    w.setFocus()
    le = w.lineEdit() if isinstance(w, QtWidgets.QAbstractSpinBox) else w
    try:
        le.selectAll()
    except Exception:
        pass


def set_value(w, text):
    """Type ``text`` into a control. Returns a problem, or ""."""
    from PySide import QtWidgets
    from . import command_line as cl
    from .panel import parts
    t = text.strip()
    if isinstance(w, parts.QuantityField) or (isinstance(w, QtWidgets.QAbstractSpinBox) and
                                              w.metaObject().className() ==
                                              "Gui::QuantitySpinBox"):
        spin = getattr(w, "spin", w)
        try:
            v = float(App.Units.Quantity(t).Value)
        except Exception:
            return "\"{}\" isn't a value.".format(t)
        if not spin.setProperty("rawValue", v):
            spin.setValue(v)
        return ""
    if isinstance(w, QtWidgets.QSpinBox):
        try:
            w.setValue(int(float(t)))
        except ValueError:
            return "\"{}\" isn't a whole number.".format(t)
        return ""
    if isinstance(w, QtWidgets.QDoubleSpinBox):
        try:
            w.setValue(float(App.Units.Quantity(t).Value))
        except Exception:
            return "\"{}\" isn't a value.".format(t)
        return ""
    if isinstance(w, parts.IntField):
        try:
            w.setValue(int(float(t)))
        except Exception:
            return "\"{}\" isn't a whole number.".format(t)
        return ""
    if isinstance(w, QtWidgets.QComboBox):
        items = [w.itemText(i) for i in range(w.count())]
        n = cl.norm(t)
        exact = [i for i, x in enumerate(items) if cl.norm(x) == n]
        starts = [i for i, x in enumerate(items) if cl.norm(x).startswith(n)]
        hits = exact or starts
        if not hits:
            return "\"{}\" isn't one of: {}.".format(t, ", ".join(items))
        if not exact and len(starts) > 1:
            return "\"{}\" could be {}.".format(t, ", ".join(items[i] for i in starts))
        w.setCurrentIndex(hits[0])
        return ""
    if isinstance(w, QtWidgets.QAbstractButton) and w.isCheckable():
        on = cl.norm(t) in ("yes", "on", "true", "1")
        if on != w.isChecked():
            w.click()
        return ""
    if isinstance(w, QtWidgets.QGroupBox):
        w.setChecked(cl.norm(t) in ("yes", "on", "true", "1"))
        return ""
    if isinstance(w, parts.Switch):
        for b in w.findChildren(QtWidgets.QAbstractButton):
            if cl.norm(b.text()) == cl.norm(t):
                b.click()
                return ""
        return "\"{}\" isn't a choice here.".format(t)
    if isinstance(w, QtWidgets.QLineEdit):
        w.setText(t)
        return ""
    return "That control takes no value."


def by_name(panel, name):
    """The control of an open panel a typed name means (its row label), or a
    problem string."""
    from . import command_line as cl
    form = getattr(panel, "widget", None)
    if form is None:
        return "No panel."
    named = {}
    for w, n in controls(form):
        if n and n not in named:
            named[n] = w
    r = cl._resolve(name, list(named))
    return named.get(r, r)


# ------------------------------------------------------------------ the toolbars

def toolbar_hints():
    """Labels on every toolbar button that can be seen. (main window, [hints])."""
    from PySide import QtCore, QtWidgets
    mw = Gui.getMainWindow()
    out = []
    for tb in mw.findChildren(QtWidgets.QToolBar):
        if not tb.isVisible():
            continue
        for b in tb.findChildren(QtWidgets.QToolButton):
            if not b.isVisible() or b.defaultAction() is None or b.width() < 8:
                continue
            a = b.defaultAction()
            if a.isSeparator() or not a.isEnabled():
                continue
            # A badge on the button's bottom right corner, hanging off it a little,
            # so the icon can still be seen.
            p = b.mapTo(mw, QtCore.QPoint(b.width() + 3, b.height() + 4))
            name = a.text().replace("&", "")
            h = WidgetHint(b, p.x(), p.y(), name, mw)
            h.anchor = "corner"
            out.append(h)
    return mw, out
