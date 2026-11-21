# SPDX-License-Identifier: LGPL-2.1-or-later
"""The standard parts every Solid Design task panel is built from.

Rules, so every panel looks and behaves the same (approved by the owner,
2026-11-17):

- No stylesheets, except on two custom parts: the square icon buttons get
  ``padding: 0`` (themes pad task-panel tool buttons; OpenTheme by 10 px a
  side, which squeezes a 16 px icon in a 26 px button to a dot), and the
  active selection box gets a frame and tint in the theme's selection
  colour. Everything else is a stock Qt widget drawn by the theme; icons are
  monochrome SVGs in the theme's text colour.
- Options sit in QGroupBoxes (``Group``). Each group lays its rows out on a
  two-column grid with equal stretch: labels on the left half, controls on
  the right half.
- An optional group (Direction 2, Thin Feature) is a checkable QGroupBox;
  unchecked, its contents are hidden, as SolidWorks collapses them.
- Every row and check box carries a tooltip; ``row()`` and ``check()``
  refuse an empty one.
- Things picked in the 3D view or tree go in a ``SelectionField`` (one
  item) or a ``SelectionList`` (several). Both have the same pick button;
  pressed, with the box tinted, means "clicks in the 3D view go here".
"""

import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

MARGIN = 8          # inside a group
H_SPACING = 6
V_SPACING = 6
BUTTON = 26         # square icon buttons, the height of a line edit
# No padding on the square icon buttons (see above). It sets nothing else, so
# the theme's border, hover and pressed look stay.
ICON_BUTTON_CSS = "QToolButton { padding: 0px; }"

# -- icons -------------------------------------------------------------------

# A mouse pointer: "pick in the 3D view" (the DFM workbench's icon).
PICK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="COLOR"'
    ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M5 3l14 8-6.5 1.6L10 19z"/></svg>')

# Two opposed arrows: reverse the direction.
FLIP_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none" stroke="COLOR"'
    ' stroke-width="5" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M16 12V50M6 40l10 12 10-12"/><path d="M48 52V14M38 24l10-12 10 12"/></svg>')

# Three links of a chain: add the edges connected to one.
CHAIN_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="COLOR"'
    ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="2" y="9" width="8" height="6" rx="3"/><rect x="14" y="9" width="8" height="6"'
    ' rx="3"/><path d="M8 12h8"/></svg>')

# A cross: clear the list.
CLEAR_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="COLOR"'
    ' stroke-width="2" stroke-linecap="round"><path d="M7 7l10 10M17 7L7 17"/></svg>')


def text_color(role=QtGui.QPalette.WindowText):
    """The theme's text colour. Themes are stylesheets, which only reach a
    widget once it is polished, so a polished probe label is asked."""
    probe = QtWidgets.QLabel()
    probe.setAttribute(QtCore.Qt.WA_DontShowOnScreen)
    probe.ensurePolished()
    c = probe.palette().color(role)
    probe.deleteLater()
    return c


def _svg_pixmap(svg, size, ratio=2.0):
    pm = QtGui.QPixmap()
    pm.loadFromData(QtCore.QByteArray(svg.encode()), "SVG")
    if pm.isNull():
        return pm
    pm = pm.scaled(int(size * ratio), int(size * ratio), QtCore.Qt.KeepAspectRatio,
                   QtCore.Qt.SmoothTransformation)
    pm.setDevicePixelRatio(ratio)
    return pm


def svg_icon(svg, size=16, color=None):
    """A monochrome icon from an SVG with COLOR in it, in the theme's text colour,
    faded when disabled."""
    svg = svg.replace("COLOR", (color or text_color()).name())
    icon = QtGui.QIcon(_svg_pixmap(svg, size))
    faded = _svg_pixmap(svg.replace("<svg ", '<svg opacity="0.35" ', 1), size)
    if not faded.isNull():
        icon.addPixmap(faded, QtGui.QIcon.Disabled)
    return icon


def accent():
    """(frame, tint) colours for the active selection box: the theme's selection
    colour, and the field background a little towards it. Read from a styled
    probe list, so they follow any theme."""
    probe = QtWidgets.QListWidget()
    probe.setAttribute(QtCore.Qt.WA_DontShowOnScreen)
    probe.ensurePolished()
    pal = probe.palette()
    hl = pal.color(QtGui.QPalette.Highlight)
    base = pal.color(QtGui.QPalette.Base)
    probe.deleteLater()
    t = 0.14
    tint = QtGui.QColor(int(base.red() * (1 - t) + hl.red() * t),
                        int(base.green() * (1 - t) + hl.green() * t),
                        int(base.blue() * (1 - t) + hl.blue() * t))
    return hl.name(), tint.name()


def active_css(cls):
    """The active selection box's look: a frame in the theme's selection colour
    and a light tint, as SolidWorks colours its active box."""
    frame, tint = accent()
    return "%s { border: 1px solid %s; background-color: %s; }" % (cls, frame, tint)


# -- small widgets -------------------------------------------------------------

def icon_button(svg, tip, checkable=False):
    """A square tool button with a theme-coloured icon."""
    b = QtWidgets.QToolButton()
    b.setIcon(svg_icon(svg))
    b.setIconSize(QtCore.QSize(16, 16))
    b.setToolTip(tip)
    b.setCheckable(checkable)
    b.setFixedSize(BUTTON, BUTTON)
    b.setStyleSheet(ICON_BUTTON_CSS)
    b.setFocusPolicy(QtCore.Qt.TabFocus)
    return b


def pick_button(tip):
    return icon_button(PICK_SVG, tip, checkable=True)


def flip_button(tip="Reverse direction", checked=False):
    """Pressed while the direction is reversed."""
    b = icon_button(FLIP_SVG, tip, checkable=True)
    b.setChecked(checked)
    return b


def hbox(*widgets, stretch=0):
    """Widgets side by side in one grid cell; the one at *stretch* takes the room."""
    w = QtWidgets.QWidget()
    lay = QtWidgets.QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    for i, child in enumerate(widgets):
        lay.addWidget(child, 1 if i == stretch else 0)
    return w


def _tip(widget, tip):
    """Put *tip* on a widget and on its children that have none of their own."""
    if not widget.toolTip():
        widget.setToolTip(tip)
    for child in widget.findChildren(QtWidgets.QWidget):
        if not child.toolTip():
            child.setToolTip(tip)


def combo(items, current=None, tip=""):
    c = QtWidgets.QComboBox()
    c.addItems(list(items))
    if current in items:
        c.setCurrentIndex(list(items).index(current))
    c.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
    c.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
    c.setMinimumContentsLength(8)
    if tip:
        c.setToolTip(tip)
    return c


def checkbox(text, checked=False, tip=""):
    b = QtWidgets.QCheckBox(text)
    b.setChecked(bool(checked))
    if tip:
        b.setToolTip(tip)
    return b


# -- groups --------------------------------------------------------------------

class Row(object):
    """One row of a group: its label (may be None) and its control."""

    def __init__(self, label, widget):
        self.label = label
        self.widget = widget
        self.check = None

    def set_visible(self, on):
        for w in (self.label, self.widget):
            if w is not None:
                w.setVisible(on)

    def set_enabled(self, on):
        for w in (self.label, self.widget):
            if w is not None:
                w.setEnabled(on)


class Group(QtWidgets.QGroupBox):
    """A titled group of rows on a two-column grid with equal stretch.

    ``checkable`` makes it optional: its title gets a check box, and its
    rows are hidden while it is unchecked. Its ``toggled`` signal is
    QGroupBox's own.
    """

    def __init__(self, title, tip="", checkable=False, checked=True, parent=None):
        super(Group, self).__init__(title, parent)
        if tip:
            self.setToolTip(tip)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        outer.setSpacing(0)
        self.body = QtWidgets.QWidget(self)
        self.grid = QtWidgets.QGridLayout(self.body)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(H_SPACING)
        self.grid.setVerticalSpacing(V_SPACING)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)
        outer.addWidget(self.body)
        self._outer = outer
        self._n = 0
        if checkable:
            self.setCheckable(True)
            self.setChecked(checked)
            self._show_body(checked)
            self.toggled.connect(self._show_body)

    def _show_body(self, on):
        """Unchecked, only the title shows: no empty margin under it."""
        self.body.setVisible(on)
        m = MARGIN if on else 0
        self._outer.setContentsMargins(MARGIN, m, MARGIN, m)

    def set_checked(self, on):
        """Check or uncheck without emitting ``toggled``."""
        self.blockSignals(True)
        self.setChecked(bool(on))
        self.blockSignals(False)
        self._show_body(bool(on))

    def row(self, label, widget, tip):
        """``label`` on the left half, ``widget`` on the right. *tip* is required:
        it goes on both, so hovering either says what the option does."""
        if not tip:
            raise ValueError("Every row needs a tooltip: %r" % label)
        lab = QtWidgets.QLabel(label) if isinstance(label, str) else label
        lab.setToolTip(tip)
        _tip(widget, tip)
        self.grid.addWidget(lab, self._n, 0)
        self.grid.addWidget(widget, self._n, 1)
        self._n += 1
        return Row(lab, widget)

    def wide(self, widget, tip=None):
        """A control across both columns: a list, a switch, a check box."""
        if tip:
            _tip(widget, tip)
        self.grid.addWidget(widget, self._n, 0, 1, 2)
        self._n += 1
        return Row(None, widget)

    def check(self, text, tip, checked=False):
        """A check box across both columns. Returns the check box."""
        if not tip:
            raise ValueError("Every check box needs a tooltip: %r" % text)
        b = checkbox(text, checked, tip)
        b.row = self.wide(b)
        return b

    def check_row(self, text, widget, tip, checked=False):
        """A check box on the left that turns the control on the right on and
        off (Draft, Offset). The row's ``check`` is the check box."""
        b = checkbox(text, checked)
        widget.setEnabled(bool(checked))
        b.toggled.connect(widget.setEnabled)
        row = self.row(b, widget, tip)
        row.check = b
        return row

    def note(self, text):
        """A short muted line, for what a tooltip can't wait to say."""
        lab = QtWidgets.QLabel(text)
        lab.setWordWrap(True)
        lab.setForegroundRole(QtGui.QPalette.PlaceholderText)
        self.wide(lab)
        return lab


# -- choices ---------------------------------------------------------------------

class Switch(QtWidgets.QWidget):
    """Joined buttons, one pressed: Add | Cut, All bodies | Selected bodies."""
    changed = QtCore.Signal(str)

    def __init__(self, options, tips=None, icons=None, parent=None):
        super(Switch, self).__init__(parent)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.group = QtWidgets.QButtonGroup(self)
        self.buttons = {}
        for i, name in enumerate(options):
            b = QtWidgets.QToolButton(self)
            b.setText(name)
            b.setCheckable(True)
            b.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            b.setMinimumHeight(BUTTON)
            if icons and icons.get(name):
                b.setIcon(QtGui.QIcon(icons[name]))
                b.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
            b.setToolTip((tips or {}).get(name) or name)
            self.group.addButton(b, i)
            lay.addWidget(b)
            self.buttons[name] = b
            b.toggled.connect(lambda on, n=name: on and self.changed.emit(n))
        self.buttons[options[0]].setChecked(True)

    def value(self):
        for n, b in self.buttons.items():
            if b.isChecked():
                return n
        return None

    def set_value(self, name):
        """Press *name* without emitting ``changed``."""
        b = self.buttons.get(name)
        if b is not None and not b.isChecked():
            b.blockSignals(True)
            b.setChecked(True)
            b.blockSignals(False)
            for other in self.buttons.values():   # the group unchecks the rest
                if other is not b and other.isChecked():
                    other.blockSignals(True)
                    other.setChecked(False)
                    other.blockSignals(False)

    mode = value
    set_mode = set_value


def quantity(unit="mm", value=0.0, minimum=0.0, maximum=1e9, obj=None, prop=None, step=1.0):
    """FreeCAD's unit spin box. Bound to *obj*.*prop*, it shows the expression
    button and takes expressions and spreadsheet references."""
    s = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
    s.setProperty("unit", unit)
    s.setProperty("minimum", minimum)
    s.setProperty("maximum", maximum)
    s.setProperty("singleStep", step)
    s.setProperty("rawValue", float(value))
    s.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
    if obj is not None and prop:
        try:
            s.binding = Gui.ExpressionBinding(s).bind(obj, prop)
        except Exception:
            s.binding = None
        s.setProperty("rawValue", float(value))
    return s


class QuantityField(QtWidgets.QWidget):
    """A unit field bound to a property: the expression button shows, and
    expressions and spreadsheet references work."""
    changed = QtCore.Signal(float)

    def __init__(self, obj, prop, unit="mm", minimum=0.0, maximum=1e9, step=1.0, bind=True,
                 parent=None):
        super(QuantityField, self).__init__(parent)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        v = getattr(obj, prop)
        v = v.Value if hasattr(v, "Value") else float(v)
        self.spin = quantity(unit, v, minimum, maximum, obj if bind else None, prop, step)
        self.spin.setParent(self)
        lay.addWidget(self.spin)
        self.obj = obj
        self.prop = prop
        QtCore.QObject.connect(self.spin, QtCore.SIGNAL("valueChanged(double)"), self._emit)

    def _emit(self, v):
        self.changed.emit(float(v))

    def value(self):
        return float(self.spin.property("rawValue"))

    def set_value(self, v):
        self.spin.blockSignals(True)
        self.spin.setProperty("rawValue", float(v))
        self.spin.blockSignals(False)

    def text(self):
        return self.spin.text()

    def has_expression(self):
        try:
            return any(p == self.prop for p, _e in self.obj.ExpressionEngine)
        except Exception:
            return False

    def connect_return(self, fn):
        QtCore.QObject.connect(self.spin, QtCore.SIGNAL("returnPressed()"), fn)


class IntField(QtWidgets.QWidget):
    """An integer field (FreeCAD's IntSpinBox), bound to a property."""
    changed = QtCore.Signal(int)

    def __init__(self, obj, prop, minimum=1, maximum=10000, parent=None):
        super(IntField, self).__init__(parent)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        try:
            self.spin = Gui.UiLoader().createWidget("Gui::IntSpinBox")
            self.spin.setParent(self)
        except Exception:
            self.spin = QtWidgets.QSpinBox(self)
        self.spin.setRange(minimum, maximum)
        self.spin.setValue(int(getattr(obj, prop)))
        self.spin.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        try:
            self.spin.binding = Gui.ExpressionBinding(self.spin).bind(obj, prop)
        except Exception:
            pass
        lay.addWidget(self.spin)
        self.spin.valueChanged.connect(lambda v: self.changed.emit(int(v)))

    def value(self):
        return int(self.spin.value())


# -- messages -------------------------------------------------------------------------

class Message(QtWidgets.QWidget):
    """An error, warning or note line with the style's own icon; hidden when empty."""

    ICONS = {"error": QtWidgets.QStyle.SP_MessageBoxCritical,
             "warning": QtWidgets.QStyle.SP_MessageBoxWarning,
             "info": QtWidgets.QStyle.SP_MessageBoxInformation}

    def __init__(self, kind="error", parent=None):
        super(Message, self).__init__(parent)
        self.kind = kind
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(6)
        self.icon = QtWidgets.QLabel()
        self.icon.setAlignment(QtCore.Qt.AlignTop)
        self.text = QtWidgets.QLabel()
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        lay.addWidget(self.icon)
        lay.addWidget(self.text, 1)
        self.hide()

    def set(self, text, kind=None):
        kind = kind or self.kind
        size = self.fontMetrics().height() + 2
        self.icon.setPixmap(self.style().standardIcon(self.ICONS[kind]).pixmap(size, size))
        self.text.setText(text or "")
        self.setVisible(bool(text))

    def value(self):
        return self.text.text() if not self.isHidden() else ""


# -- selection --------------------------------------------------------------------

class _ClickEdit(QtWidgets.QLineEdit):
    """A line edit that says when it is clicked (clicking a box makes it active)."""
    pressed = QtCore.Signal()

    def mousePressEvent(self, ev):
        self.pressed.emit()
        super(_ClickEdit, self).mousePressEvent(ev)


class _ClickList(QtWidgets.QListWidget):
    pressed = QtCore.Signal()

    def mousePressEvent(self, ev):
        self.pressed.emit()
        super(_ClickList, self).mousePressEvent(ev)


class _Selection(QtWidgets.QWidget):
    """What a field and a list share: the pick button, the items, the note
    under the box when a pick is refused, and the active look.

    ``accept(sel)`` returns (payload, text) to take a pick, a string saying why
    it is refused, or None when the pick doesn't fit at all (so the panel can
    try another box).
    """
    activated = QtCore.Signal(object)   # the box, to make it the active one
    changed = QtCore.Signal()           # the user changed the items

    multiple = False

    def __init__(self, name, what, hint, accept, tip, empty=None, parent=None):
        super(_Selection, self).__init__(parent)
        self.name = name
        self.what = what
        self.hint = hint
        self.empty = empty
        self.accept_fn = accept
        self.items = []         # [(payload, text)]
        self.active = False
        self.tip = tip
        self.setToolTip(tip)
        self.button = pick_button(tip)
        self.button.clicked.connect(self._button_clicked)
        self.note = Message("warning")

    def _button_clicked(self, _checked=False):
        self.button.setChecked(self.active)    # the panel decides
        self.activated.emit(self)

    def set_placeholder(self, what=None, hint=None, empty=None):
        if what is not None:
            self.what = what
        if hint is not None:
            self.hint = hint
        if empty is not None:
            self.empty = empty or None
        self._refresh()

    def set_active(self, on):
        self.active = on
        self.button.setChecked(on)
        self._style_active(on)
        self._refresh()

    def payloads(self):
        return [p for p, _t in self.items]

    def set_items(self, items):
        """Show *items* (no ``changed``: for loading)."""
        self.items = list(items)
        self._refresh()

    def clear_items(self):
        self.items = []
        self._refresh()
        self.changed.emit()

    clear = clear_items

    def say(self, text):
        self.note.set(text)

    def offer(self, sel):
        """Try a pick. True if taken, a string if refused, None if unrelated."""
        res = self.accept_fn(sel)
        if res is None:
            return None
        if isinstance(res, str):
            self.say(res)
            return res
        payload, text = res
        self.say("")
        for i, (p, _t) in enumerate(self.items):
            if p == payload:
                if self.multiple:       # picking it again takes it out
                    del self.items[i]
                    self._refresh()
                    self.changed.emit()
                return True
        if self.multiple:
            self.items.append((payload, text))
        else:
            self.items = [(payload, text)]
        self._refresh()
        self.changed.emit()
        return True

    def detach(self):
        pass


class SelectionField(_Selection):
    """One picked item: a read-only field and the pick button.

    While picking, the button is pressed, the field is tinted and asks for
    the click.
    """

    def __init__(self, name, what, hint, accept, tip, empty=None, parent=None):
        """*what*: "sketch" (the field reads "No sketch"); *hint*: what to click,
        kept short as the field is half the panel wide ("Click a sketch")."""
        super(SelectionField, self).__init__(name, what, hint, accept, tip, empty, parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.edit = _ClickEdit()
        self.edit.setReadOnly(True)
        self.edit.setFocusPolicy(QtCore.Qt.NoFocus)
        self.edit.setToolTip(tip)
        self.edit.pressed.connect(lambda: self.activated.emit(self))
        row.addWidget(self.edit, 1)
        row.addWidget(self.button)
        lay.addLayout(row)
        lay.addWidget(self.note)
        self._refresh()

    def _style_active(self, on):
        self.edit.setStyleSheet(active_css("QLineEdit") if on else "")

    def _refresh(self):
        self.edit.setPlaceholderText(self.hint if self.active else
                                     (self.empty or "No %s" % self.what))
        self.edit.setText(self.items[0][1] if self.items else "")
        self.edit.setCursorPosition(0)
        # The name may not fit half a panel: the tooltip has it whole.
        self.edit.setToolTip("<b>%s</b><br>%s" % (self.items[0][1], self.tip) if self.items
                             else self.tip)


class SelectionList(_Selection):
    """Several picked items: a list that grows with them (2 to 6 rows), the
    pick button and a clear button beside it.

    Picking an item already in the list takes it out again, as in SolidWorks.
    Delete removes the selected rows; right-click offers Remove and Clear.
    """

    multiple = True
    MAX_ROWS = 6

    def __init__(self, name, what, hint, accept, tip, empty=None, parent=None):
        """*what*: "edges"; *hint*: what to click while picking; *empty*: what an
        empty list means, when it means something ("Whole sketch")."""
        super(SelectionList, self).__init__(name, what, hint, accept, tip, empty, parent)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.list = _ClickList()
        self.list.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.list.setUniformItemSizes(True)
        self.list.setToolTip(tip)
        self.list.pressed.connect(lambda: self.activated.emit(self))
        self.list.setContextMenuPolicy(QtCore.Qt.ActionsContextMenu)
        remove = QtGui.QAction("Remove", self.list)
        remove.setShortcut(QtGui.QKeySequence.Delete)
        remove.setShortcutContext(QtCore.Qt.WidgetShortcut)
        remove.triggered.connect(self.remove_selected)
        clear_all = QtGui.QAction("Clear", self.list)
        clear_all.triggered.connect(self.clear_items)
        self.list.addAction(remove)
        self.list.addAction(clear_all)
        buttons = QtWidgets.QVBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(4)
        self.clear_button = icon_button(CLEAR_SVG, "Clear the %s" % what)
        self.clear_button.clicked.connect(lambda _c=False: self.clear_items())
        # Select Tangency, Loop, Chain from the last edge picked (the panel fills
        # its menu and shows it once an edge is in the list).
        self.more_button = icon_button(CHAIN_SVG, "Add the edges connected to the last one "
                                                  "picked: tangency, loop, chain")
        self.more_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.more_button.setStyleSheet(ICON_BUTTON_CSS +
                                       " QToolButton::menu-indicator { image: none; width: 0; }")
        self.more_button.setMenu(QtWidgets.QMenu(self.more_button))
        self.more_button.hide()
        buttons.addWidget(self.button)
        buttons.addWidget(self.clear_button)
        buttons.addWidget(self.more_button)
        buttons.addStretch(1)
        row.addWidget(self.list, 1)
        row.addLayout(buttons)
        lay.addLayout(row)
        lay.addWidget(self.note)
        self._refresh()

    def _style_active(self, on):
        self.list.setStyleSheet(active_css("QListWidget") if on else "")

    def remove_selected(self):
        rows = sorted({i.row() for i in self.list.selectedIndexes()}, reverse=True)
        if not rows or not self.items:
            return
        for r in rows:
            if r < len(self.items):
                del self.items[r]
        self._refresh()
        self.changed.emit()

    def _refresh(self):
        self.list.clear()
        if self.items:
            for _p, text in self.items:
                self.list.addItem(text)
        else:
            text = self.hint if self.active else (self.empty or "No %s selected" % self.what)
            it = QtWidgets.QListWidgetItem(text)
            it.setFlags(QtCore.Qt.NoItemFlags)
            self.list.addItem(it)
        self.clear_button.setEnabled(bool(self.items))
        self._fit()
        # The theme styles the list only once it is shown: measure again then.
        QtCore.QTimer.singleShot(0, self._fit)

    def _fit(self):
        """As tall as its rows, 2 to 6; a scroll bar only past 6."""
        try:
            lst = self.list
            if not self.items and lst.count():   # the theme's colour, once styled
                lst.item(0).setForeground(lst.palette().brush(QtGui.QPalette.PlaceholderText))
            rows = max(2, min(len(self.items), self.MAX_ROWS))
            row_h = lst.sizeHintForRow(0)
            if lst.isVisible() and lst.count():
                row_h = max(row_h, lst.visualItemRect(lst.item(0)).height())
            row_h = max(row_h, self.fontMetrics().height() + 4)
            m = lst.contentsMargins()
            lst.setFixedHeight(row_h * rows + lst.frameWidth() * 2 + m.top() + m.bottom() + 2)
        except RuntimeError:        # deleted before the timer fired
            pass


def panel_form(title, icon=None):
    """The panel's widget: a vertical stack of groups, as in the DFM workbench."""
    form = QtWidgets.QWidget()
    form.setWindowTitle(title)
    if icon:
        form.setWindowIcon(QtGui.QIcon(icon))
    lay = QtWidgets.QVBoxLayout(form)
    lay.setContentsMargins(6, 6, 6, 6)
    lay.setSpacing(8)
    return form, lay


def untipped(root):
    """The controls under *root* with no tooltip: every one must say what it does.
    The insides of combo boxes and spin boxes (their list, the fx button) are
    covered by their owner's tooltip."""
    kinds = (QtWidgets.QAbstractButton, QtWidgets.QComboBox, QtWidgets.QAbstractSpinBox,
             QtWidgets.QLineEdit, QtWidgets.QAbstractItemView)
    owners = (QtWidgets.QComboBox, QtWidgets.QAbstractSpinBox)
    out = []
    for w in root.findChildren(QtWidgets.QWidget):
        if not isinstance(w, kinds) or w.toolTip():
            continue
        p = w.parentWidget()
        inside = False
        while p is not None and p is not root:
            if isinstance(p, owners):
                inside = True
                break
            p = p.parentWidget()
        if not inside:
            out.append(w)
    return out
