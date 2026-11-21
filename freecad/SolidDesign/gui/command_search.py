# SPDX-License-Identifier: LGPL-2.1-or-later
"""Command search: press "/" (with no tool open) and type a tool's name.

A box opens over the 3D view, its top a third of the way down. Typing filters
Solid Design's tools by fuzzy match (the letters in order, best when they start
words or run together: "fl" finds Fillet and Flex, "lpat" Linear Pattern); Up and
Down choose, Enter runs the tool, Escape closes. Tools that can't run now (no
document, nothing to work on) are listed greyed and Enter skips them.

Only Solid Design's tools are listed: its SD_ commands, without the toolbar
drop-downs and without this search itself.
"""

import FreeCADGui as Gui

SHORTCUT = "/"
WIDTH = 440
ROWS = 9


# ------------------------------------------------------------------ matching

def fuzzy(query, text):
    """A score for ``query`` matching ``text`` (higher is better), or None when
    its letters don't all appear in order. Letters that start words, run on from
    the last match or start the text score more; gaps and a long text cost a
    little."""
    q = "".join(query.lower().split())
    t = text.lower()
    if not q:
        return 0.0
    s = _match(q, t, True)
    return s if s is not None else _match(q, t, False)


def _match(q, t, words):
    """fuzzy()'s scoring, taking each letter at its first place after the last
    one, or (``words``) at a word's start if one comes soon after."""
    score = 0.0
    i = 0
    last = -1
    for ch in q:
        j = t.find(ch, i)
        if j < 0:
            return None
        if words:
            k = j
            while k >= 0 and not (k == 0 or not t[k - 1].isalnum()):
                k = t.find(ch, k + 1)
            if k >= 0 and k - j <= 12:
                j = k
        if j == 0:
            score += 3.0
        elif not t[j - 1].isalnum():
            score += 2.0                        # starts a word
        if j == last + 1 and last >= 0:
            score += 1.5                        # runs on from the last letter
        elif last >= 0:
            score -= 0.05 * (j - last - 1)
        score += 1.0
        last = j
        i = j + 1
    return score - 0.01 * len(t)


def rank(query, entries):
    """``entries`` [(name, label, tip)] matching ``query``, best first. A match in
    the label counts; the tooltip only catches a whole word typed (so "boss" finds
    Extrude, whose tip says boss) and ranks below label matches."""
    out = []
    q = query.strip().lower()
    for e in entries:
        label, tip = e[1], e[2]
        s = fuzzy(q, label)
        if s is None and len(q) >= 3:
            words = tip.lower().replace("/", " ").replace("-", " ").split()
            if any(w.startswith(q) for w in words):
                s = -5.0
        if s is not None:
            out.append((s, label.lower(), e))
    out.sort(key=lambda r: (-r[0], r[1]))
    return [r[2] for r in out]


# ------------------------------------------------------------------ the tools

def entries():
    """[(command name, label, tooltip, icon path, active now)] for every tool."""
    from . import commands
    out = []
    for name in Gui.listCommands():
        if not name.startswith("SD_") or name in commands.GROUPS or name in (
                "SD_CommandSearch", "SD_CommandLine", "SD_RepeatLast"):
            continue
        try:
            c = Gui.Command.get(name)
            info = c.getInfo()
            label = info.get("menuText", "").replace("&", "").strip()
            if not label:
                continue
            out.append((name, label, info.get("toolTip", ""), info.get("pixmap", ""),
                        bool(c.isActive())))
        except Exception:
            pass
    return out


# ------------------------------------------------------------------ the box

def _view_widget():
    """The 3D view's widget, or None."""
    from PySide import QtWidgets
    try:
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        sub = mdi.activeSubWindow() if mdi is not None else None
        if sub is not None and sub.widget() is not None:
            return sub.widget()
    except Exception:
        pass
    return None


_box = [None]


def current():
    """The search box, if it has been opened (and Qt hasn't deleted it)."""
    from .command_line import _alive
    return _box[0] if _alive(_box[0]) else None


def show():
    """Open the search box over the 3D view."""
    if current() is None:
        _box[0] = _make_box()
    _box[0].open()
    return _box[0]


def _make_box():
    from PySide import QtCore, QtGui, QtWidgets

    class SearchBox(QtWidgets.QFrame):
        def __init__(self):
            super(SearchBox, self).__init__(Gui.getMainWindow(), QtCore.Qt.Popup)
            self.setObjectName("SD_CommandSearch")
            self.setFrameShape(QtWidgets.QFrame.StyledPanel)
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(6, 6, 6, 6)
            lay.setSpacing(4)
            self.edit = QtWidgets.QLineEdit()
            self.edit.setPlaceholderText("Search Solid Design's tools")
            self.list = QtWidgets.QListWidget()
            self.list.setIconSize(QtCore.QSize(20, 20))
            self.list.setUniformItemSizes(True)
            self.list.setFocusPolicy(QtCore.Qt.NoFocus)
            lay.addWidget(self.edit)
            lay.addWidget(self.list)
            self.edit.textChanged.connect(self.fill)
            self.edit.installEventFilter(self)
            self.list.itemClicked.connect(lambda it: self.run(it))
            self.tools = []

        # ---------------------------------------------------------- placing
        def open(self):
            self.tools = entries()
            self.edit.blockSignals(True)
            self.edit.clear()
            self.edit.blockSignals(False)
            self.fill("")
            self.place()
            self.show()
            self.raise_()
            self.activateWindow()
            self.edit.setFocus()

        def place(self):
            """Centred on the 3D view, its top a third of the way down."""
            w = _view_widget() or Gui.getMainWindow()
            r = w.rect()
            top_left = w.mapToGlobal(r.topLeft())
            row = self.list.sizeHintForRow(0) if self.list.count() else 24
            h = self.edit.sizeHint().height() + max(row, 20) * ROWS + 24
            width = min(WIDTH, max(260, r.width() - 40))
            self.setGeometry(top_left.x() + (r.width() - width) // 2,
                             top_left.y() + r.height() // 3, width, h)

        # ---------------------------------------------------------- listing
        def fill(self, text):
            self.list.clear()
            found = rank(text, self.tools) if text.strip() else \
                sorted(self.tools, key=lambda e: e[1].lower())
            for name, label, tip, pix, on in found:
                it = QtWidgets.QListWidgetItem(QtGui.QIcon(pix) if pix else QtGui.QIcon(), label)
                it.setData(QtCore.Qt.UserRole, name)
                it.setToolTip(tip)
                if not on:
                    it.setFlags(QtCore.Qt.NoItemFlags)      # greyed: can't run now
                self.list.addItem(it)
            self.pick(self._first_enabled())

        def _first_enabled(self):
            for i in range(self.list.count()):
                if self.list.item(i).flags() & QtCore.Qt.ItemIsEnabled:
                    return i
            return -1

        def pick(self, row):
            self.list.setCurrentRow(row)
            if row >= 0:
                self.list.scrollToItem(self.list.item(row))

        def step(self, d):
            n = self.list.count()
            row = self.list.currentRow()
            for _ in range(n):
                row = (row + d) % n if n else -1
                if row >= 0 and self.list.item(row).flags() & QtCore.Qt.ItemIsEnabled:
                    self.pick(row)
                    return

        # ---------------------------------------------------------- keys
        def eventFilter(self, obj, ev):
            if obj is self.edit and ev.type() == QtCore.QEvent.KeyPress:
                k = ev.key()
                if k in (QtCore.Qt.Key_Down, QtCore.Qt.Key_Tab):
                    self.step(1)
                    return True
                if k in (QtCore.Qt.Key_Up, QtCore.Qt.Key_Backtab):
                    self.step(-1)
                    return True
                if k in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                    self.run(self.list.currentItem())
                    return True
                if k == QtCore.Qt.Key_Escape:
                    self.close()
                    return True
            return super(SearchBox, self).eventFilter(obj, ev)

        def run(self, item):
            if item is None or not item.flags() & QtCore.Qt.ItemIsEnabled:
                return
            name = item.data(QtCore.Qt.UserRole)
            self.close()
            # After the box has gone, so the tool's panel takes the focus.
            QtCore.QTimer.singleShot(0, lambda: Gui.runCommand(name))

    return SearchBox()


class SearchCommand(object):
    """The "/" key: Solid Design's command search."""

    def GetResources(self):
        from .. import icon
        return {"Pixmap": icon("SolidDesign"), "MenuText": "Command Search",
                "ToolTip": "Find a Solid Design tool by typing its name, then press Enter to "
                           "start it.", "Accel": SHORTCUT}

    def IsActive(self):
        # Not while a tool (or a sketch) is open, and only in Solid Design.
        if Gui.Control.activeDialog():
            return False
        try:
            return type(Gui.activeWorkbench()).__name__ == "SolidDesignWorkbench"
        except Exception:
            return False

    def Activated(self):
        show()
