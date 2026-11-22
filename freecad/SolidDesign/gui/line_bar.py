# SPDX-License-Identifier: LGPL-2.1-or-later
"""The command line's bar: the field along the bottom of the 3D view, with its
suggestions, grey completion, labels, live preview and problems.

Modes:
    line        a tool, a command or a feature by name (":")
    panel       ":" with a panel open: labels on its controls
    toolbar     ":toolbar": labels on the toolbar buttons
    history     Ctrl+R: earlier lines, searched loosely
"""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from . import command_line as cl
from . import hints as hm
from . import line_complete, line_ex, line_select
from . import preview as pv

PREVIEW_DELAY = 350             # ms after the last key before the preview is made


class GhostEdit(QtWidgets.QLineEdit):
    """A line edit that draws the rest of the word Tab would add, in grey, after
    the text."""

    def __init__(self, parent=None):
        super(GhostEdit, self).__init__(parent)
        self.ghost = ""

    def set_ghost(self, text):
        if text != self.ghost:
            self.ghost = text
            self.update()

    def paintEvent(self, ev):
        super(GhostEdit, self).paintEvent(ev)
        if not self.ghost or self.cursorPosition() != len(self.text()):
            return
        p = QtGui.QPainter(self)
        col = self.palette().color(QtGui.QPalette.Text)
        col.setAlpha(110)
        p.setPen(col)
        r = self.cursorRect()
        fm = self.fontMetrics()
        x = r.center().x() + 1
        y = (self.height() + fm.ascent() - fm.descent()) // 2
        p.drawText(QtCore.QPoint(x, y), self.ghost)
        p.end()


def _sel_tokens(words):
    """[(index, key, value)] of the sel= words of a line."""
    out = []
    for i, w in enumerate(words):
        if "=" in w and w.split("=", 1)[0].strip().lower() in hm.SEL_KEYS:
            k, v = w.split("=", 1)
            out.append((i, k.strip().lower(), v))
    return out


def _starts_a_word(prefix):
    """Whether letters that could be a label could also be a word being typed
    (l... for loop): then no "no label" yet."""
    from . import pick_tools
    p = prefix.lower()
    words = list(pick_tools.WORDS) + list(pick_tools.WORD_ALIASES) + \
        [w for w, _x in line_select.SOURCES] + list(line_select.SOURCE_KINDS) + \
        list(line_select.ORIGIN_PLANES)
    try:
        words += [t.lower() for t, _o in line_select.named_objects(App.ActiveDocument)]
    except Exception:
        pass
    return any(w.startswith(p) for w in words)


def _is_selected(key):
    try:
        for s in Gui.Selection.getSelectionEx(key[0]):
            if s.ObjectName == key[1] and (not key[2] and not s.SubElementNames or
                                           key[2] in s.SubElementNames):
                return True
    except Exception:
        pass
    return False


class _Clicks(object):
    """Selection changes not made by the bar: clicks in the view or the tree."""

    def __init__(self, bar):
        self.bar = bar

    def _later(self, fn, *a):
        if getattr(self.bar, "_own", False) or getattr(self.bar, "_previewing", False):
            return
        QtCore.QTimer.singleShot(0, lambda: cl._alive(self.bar) and fn(*a))

    def addSelection(self, doc, obj, sub, pnt):
        self._later(self.bar.clicked, (doc, obj, sub or ""))

    def removeSelection(self, doc, obj, sub):
        self._later(self.bar.unclicked, (doc, obj, sub or ""))

    def clearSelection(self, doc):
        self._later(self.bar._resync)

    def setSelection(self, doc):
        self._later(self.bar._resync)


def register_tokens(text):
    return [w[1:] for w in text.split(" ") if len(w) > 1 and w.startswith(">")]


def strip_selection(text):
    """The line without its sel= and >register words."""
    return " ".join(w for w in text.split(" ") if w and not (
        "=" in w and w.split("=", 1)[0].strip().lower() in hm.SEL_KEYS) and
        not (w.startswith(">") and len(w) > 1))


class CommandBar(QtWidgets.QFrame):
    """``parent``: the top layer over the 3D view (see top_layer), whose
    coordinates are the view's."""

    def __init__(self, parent):
        super(CommandBar, self).__init__(parent)
        from .top_layer import view_of
        self.view = view_of(parent)
        self.setObjectName("SD_CommandLine")
        self.setAutoFillBackground(True)
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(6, 3, 6, 3)
        outer.setSpacing(1)
        self.msg = QtWidgets.QLabel()
        self.msg.setWordWrap(True)
        self.msg.hide()
        outer.addWidget(self.msg)
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.prompt = QtWidgets.QLabel(":")
        f = self.prompt.font()
        f.setBold(True)
        self.prompt.setFont(f)
        self.edit = GhostEdit()
        self.edit.setFrame(False)
        self.edit.installEventFilter(self)
        self.edit.textEdited.connect(lambda _t: self.suggest())
        self.edit.cursorPositionChanged.connect(lambda *_a: self.edit.update())
        row.addWidget(self.prompt)
        row.addWidget(self.edit, 1)
        outer.addLayout(row)
        self.list = QtWidgets.QListWidget(parent)
        self.list.setFocusPolicy(QtCore.Qt.NoFocus)
        self.list.itemClicked.connect(self._list_clicked)
        self.list.hide()
        self.mode = "line"
        self.under = None
        self.point = None
        self.panel = None
        self.hist = []
        self.hpos = 0
        self.cands = []
        self.cpos = -1
        self.typed = ""
        self.problems = []
        self.xray = False                               # hidden elements labelled too
        self.see_through = hm.SeeThrough()
        self.overlay = hm.make_overlay(parent)          # the 3D view's labels
        self.overlay.clicked.connect(self.hint_clicked)
        self.overlays = {}                              # other hosts: id -> overlay
        self.hints = []                                 # labels in the 3D view
        self.whints = []                                # labels on widgets / tree rows
        self.hint_kinds = None
        self.code_keys = {}                             # 3D label -> (doc, obj, sub)
        self.added = set()                              # what the bar has selected
        self._cam = None
        self.cam_timer = QtCore.QTimer(self)
        self.cam_timer.setInterval(250)
        self.cam_timer.timeout.connect(self._camera_moved)
        QtWidgets.QApplication.instance().focusChanged.connect(self._focus_moved)
        self.preview = pv.Preview()
        self.preview_timer = QtCore.QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(PREVIEW_DELAY)
        self.preview_timer.timeout.connect(self.update_preview)
        parent.installEventFilter(self)

    # ---------------------------------------------------------- opening and closing

    def start(self, under, mode="line", panel=None):
        self.under = under
        self.point = self._pointer_point()
        self.mode = mode
        self.panel = panel
        self.hist = cl.history()
        self.hpos = len(self.hist)
        self.hints, self.whints, self.code_keys = [], [], {}
        self.added = set()
        self.problems = []
        self.typed = ""
        self.hint_kinds = None
        self.edit.clear()
        self.edit.set_ghost("")
        self.say("")
        self._set_prompt()
        self.place()
        self.show()
        self.raise_()
        self.edit.setFocus()
        if mode == "panel":
            self._panel_hints()
        elif mode == "toolbar":
            self._toolbar_hints()
        self._watch(mode == "line")
        self.suggest()

    def _set_prompt(self):
        self.prompt.setText({"history": "history:", "panel": ":", "toolbar": "toolbar:"}
                            .get(self.mode, ":"))
        self.edit.setPlaceholderText({
            "line": u"fillet 2 sel=jk   ·   extrude 10 cut   ·   Fillet1 r=3   ·   "
                    u":h help   ·   Tab completes, ↑ history, Ctrl+R search, "
                    u"Ctrl+X hidden ones, Esc closes",
            "panel": u"a label goes to that control   ·   ds=10 sets it   ·   depth=10 by name",
            "toolbar": u"a label clicks that button   ·   or type its name, Enter   ·   "
                       u"Esc closes",
            "history": u"search earlier lines   ·   Enter takes one   ·   Esc goes back",
        }[self.mode])

    def _pointer_point(self):
        """The 3D point under the pointer as ":" was pressed (for :nearest)."""
        try:
            view = Gui.ActiveDocument.ActiveView
            w = self.view
            pos = w.mapFromGlobal(QtGui.QCursor.pos())
            ratio = float(view.getSize()[1]) / max(1, w.height())
            info = view.getObjectInfo((int(pos.x() * ratio), int((w.height() - pos.y()) * ratio)))
            if info:
                return App.Vector(info["x"], info["y"], info["z"])
        except Exception:
            pass
        return None

    def close_bar(self, keep=False):
        """Esc drops what the bar picked; Enter keeps it (the tool takes it, or it
        stays selected)."""
        if not keep:
            for k in list(self.added):
                try:
                    Gui.Selection.removeSelection(*k)
                except Exception:
                    pass
        self.added = set()
        self._show_planes([])
        self._watch(False)
        self.xray = False
        self.see_through.off()
        self.code_keys = {}
        self.hints, self.whints = [], []
        self.hint_kinds = None
        self.preview_timer.stop()
        self.preview.clear()
        self.preview.detach()
        self.show_hints(False)
        self._hide_widget_overlays()
        self.list.hide()
        self.hide()
        self.mode = "line"
        try:
            self.view.setFocus()
        except Exception:
            pass

    # ---------------------------------------------------------- layout

    def place(self):
        p = self.parentWidget()
        h = self.sizeHint().height()
        self.setGeometry(0, p.height() - h, p.width(), h)
        self._place_list()

    def _place_list(self):
        p = self.parentWidget()
        n = min(self.list.count(), 10)
        if not n or not self.isVisible():
            self.list.hide()
            return
        rh = max(self.list.sizeHintForRow(0), 18)
        h = rh * n + 6
        self.list.setGeometry(0, self.geometry().top() - h, min(p.width(), 620), h)
        self.list.show()
        self.list.raise_()

    def say(self, text, problem=False):
        """A line above the field: a problem (red) or a note; empty hides it."""
        if not text:
            if self.msg.isVisible():
                self.msg.hide()
                self.place()
            return
        self.msg.setText(text)
        pal = self.msg.palette()
        col = QtGui.QColor(190, 30, 30) if problem else self.palette().color(QtGui.QPalette.Text)
        pal.setColor(QtGui.QPalette.WindowText, col)
        self.msg.setPalette(pal)
        if not self.msg.isVisible():
            self.msg.show()
            self.place()

    # ---------------------------------------------------------- typing

    def suggest(self):
        text = self.edit.text()
        inserted = len(text) > len(self.typed)
        if self.mode == "history":
            self._history_suggest(text)
            return
        if self.mode == "toolbar":
            self._toolbar_follow(text, inserted)
            self.typed = text
            return
        if self.mode == "panel":
            self._panel_follow(text, inserted)
            self.typed = text
            return
        text = self.follow_hints(text, inserted)
        self.typed = text
        self.problems = self.sync(text)
        if self.overlay.isVisible():
            # The labels just picked turn green now (sync has selected them).
            self.overlay.set_state(self.hints, self.overlay.prefix, self._picked_codes())
        try:
            self.cands = line_complete.completions(self.typed)
        except Exception as e:
            App.Console.PrintLog("Solid Design: completion: {}\n".format(e))
            self.cands = []
        self.cpos = -1
        self._fill_list()
        self.say("; ".join(self.problems), True)
        self.preview.clear("line")
        self.preview_timer.start()

    def _fill_list(self):
        self.list.clear()
        for _put, shown in self.cands:
            self.list.addItem(shown)
        self.edit.set_ghost(line_complete.ghost(self.typed, self.cands))
        self._place_list()

    def _list_clicked(self, item):
        row = self.list.row(item)
        if self.mode == "toolbar":
            hits = getattr(self, "_tb_hits", [])
            if 0 <= row < len(hits):
                self._act_on(hits[row])
            return
        if 0 <= row < len(self.cands):
            self._take(self.cands[row][0])

    def _put(self, put):
        parts = self.typed.split(" ")
        parts[-1] = put.rstrip(" ")
        return " ".join(parts) + (" " if put.endswith(" ") else "")

    def _take(self, put):
        """Put a completion in place of the word being typed, then suggest again
        from there (a label it ends with isn't picked by it: the labels are
        picked by typing)."""
        text = self._put(put)
        self.edit.setText(text)
        self.typed = text
        self.suggest()

    def complete(self, d):
        """Tab: what the grey text shows, if any (the one way to go, or as far
        as the ways agree); else go through the list (Shift+Tab back)."""
        if self.mode in ("history", "toolbar"):
            self.cpos = (self.cpos + d) % max(1, len(self.cands))
            self.list.setCurrentRow(self.cpos)
            return
        if not self.cands:
            return
        target = line_complete.tab_target(self.typed, self.cands) if self.cpos < 0 else None
        if target is not None and d > 0:
            self._take(target)
            return
        self.cpos = (self.cpos + d) % len(self.cands)
        text = self._put(self.cands[self.cpos][0])
        self.edit.setText(text)
        self.edit.set_ghost("")
        self.list.setCurrentRow(self.cpos)
        self.follow_hints(text, inserted=False)
        self.sync(text)

    # ---------------------------------------------------------- labels in the view

    def _view_hints(self, kinds):
        """Find the 3D labels for ``kinds`` (picked ones keep theirs)."""
        self.hint_kinds = kinds
        try:
            view = Gui.ActiveDocument.ActiveView
            p = self.parentWidget()
            ratio = float(view.getSize()[0]) / max(1, p.width())
            bodies = hm.view_objects(App.ActiveDocument)
            found = hm.visible(view, bodies, kinds, ratio, p.height(),
                               hidden_too=self.xray)
            if hm.REF_PLANE in kinds:
                planes = hm.ref_planes(App.ActiveDocument)
                if self._show_planes(planes):
                    # Drawn just now: their size is known once the view has drawn them.
                    QtCore.QTimer.singleShot(80, self._place_planes)
                size = max([b.Shape.BoundBox.DiagonalLength for b in bodies] + [60.0]) * 0.3
                found += hm.plane_hints(view, planes, ratio, p.height(), size)
            else:
                self._show_planes([])
            # Labels typed in the line keep their elements (seen or not).
            keep = {self.code_keys[c]: c for c in self._typed_codes() if c in self.code_keys}
            self.hints = hm.assign(found, keep, (p.width() / 2.0, p.height() / 2.0))
            self.code_keys = {c: k for k, c in keep.items()}
            for h in self.hints:
                self.code_keys[h.code] = h.key()
            self._cam = self._camera()
        except Exception as e:
            App.Console.PrintLog("Solid Design: hints: {}\n".format(e))
            self.hints = []

    def _place_planes(self):
        """Move the planes' labels onto the planes as drawn (FreeCAD sizes the
        origin when it draws it)."""
        if not self.isVisible() or not self.hints:
            return
        try:
            view = Gui.ActiveDocument.ActiveView
            p = self.parentWidget()
            ratio = float(view.getSize()[0]) / max(1, p.width())
            planes = [h.obj for h in self.hints if h.kind == "Plane"]
            moved = {h.obj.Name: h for h in hm.plane_hints(view, planes, ratio, p.height())}
        except Exception:
            return
        for h in self.hints:
            m = moved.get(getattr(h.obj, "Name", None)) if h.kind == "Plane" else None
            if m is not None:
                h.x, h.y = m.x, m.y
        self.overlay.set_state(self.hints, self.overlay.prefix, self._picked_codes())

    def toggle_xray(self):
        """Ctrl+X: label what's hidden too (behind the model, or facing away),
        with the bodies drawn see-through; again to go back."""
        if self.mode != "line":
            return
        self.xray = not self.xray
        if self.xray:
            self.see_through.on(hm.view_objects(App.ActiveDocument))
        else:
            self.see_through.off()
        self.prompt.setText(u"hidden too  :" if self.xray else ":")
        words = self.edit.text().split(" ")
        key = words[-1].split("=", 1)[0].lower() if "=" in words[-1] else None
        if key not in hm.SEL_KEYS:
            # Not picking yet: start, as Tab to sel= would.
            text = self.edit.text()
            text += ("" if not text or text.endswith(" ") else " ") + "sel="
            self.edit.setText(text)
            self.typed = text
        self.hints = []
        self.hint_kinds = None
        self.suggest()
        n = sum(1 for h in self.hints if getattr(h, "hidden", False))
        self.say(u"Hidden ones labelled too ({}), dashed. Ctrl+X again: only what "
                 u"can be seen.".format(n) if self.xray else "")

    def _show_planes(self, planes):
        """Hidden planes are drawn while they have labels (as a selected one is:
        the document doesn't change)."""
        from .reveal import _Reveal
        want = {(o.Document.Name, o.Name): o.ViewObject for o in planes
                if getattr(o, "ViewObject", None) is not None and not o.ViewObject.Visibility}
        shown = getattr(self, "_planes_shown", {})
        for k in [k for k in shown if k not in want]:
            _Reveal._hide(k, shown.pop(k))
        new = False
        for k, vo in want.items():
            if k not in shown and _Reveal._show(vo):
                shown[k] = vo
                new = True
        self._planes_shown = shown
        return new

    def _typed_codes(self):
        out = set()
        for _i, _k, v in _sel_tokens(self.edit.text().split(" ")):
            for part in v.split(","):
                code, _m = line_select.code_and_motions(part.split(":")[0])
                if code:
                    out.add(code)
        return out

    def follow_hints(self, text, inserted):
        """Show the labels the word being typed can use; a whole label typed picks
        its element (in sel=) or puts its name in (after edit, suppress...)."""
        words = text.split(" ")
        last = words[-1]
        key = last.split("=", 1)[0].lower() if "=" in last else None
        first = words[0].lower() if len(words) > 1 else ""
        if key in hm.SEL_KEYS:
            self._hide_widget_overlays()
            return self._follow_sel(text, words, key, inserted)
        if first in line_complete.TREE_ARGS | line_complete.BODY_ARGS and "=" not in last \
                and not last.startswith("/"):
            return self._follow_tree(text, words, first, inserted)
        self.show_hints(False)
        self._hide_widget_overlays()
        return text

    def _follow_sel(self, text, words, key, inserted):
        cmd = cl.find_tool(line_ex.expand_alias(words[0]).split(" ")[0]) \
            if len(words) > 1 and "=" not in words[0] else None
        kinds = hm.sel_kinds(key, cmd)
        if kinds != self.hint_kinds or not self.hints:
            self.whints = []
            self._view_hints(kinds)
        value = words[-1].split("=", 1)[1]
        parts = value.split(",")
        cur = parts[-1]
        # ] [ + typed after a pick (the comma was added for it): step that pick.
        if cur and all(c in line_select.MOTIONS for c in cur) and len(parts) > 1 and \
                parts[-2] and line_select.is_code(parts[-2]):
            parts[-2] += cur
            parts[-1] = ""
            words[-1] = key + "=" + ",".join(parts)
            text = " ".join(words)
            self.edit.setText(text)
            cur = ""
        elif inserted and cur in self.code_keys:
            text += ","
            self.edit.setText(text)
            cur = ""
        prefix = cur if cur and all(c in hm.ALPHABET for c in cur.lower()) else ""
        if cur and not prefix:
            self.show_hints(False)          # a word, a filter or a register: no labels
            return text
        self.overlay.set_state(self.hints, prefix, self._picked_codes())
        self.show_hints(True)
        if prefix and not any(h.code.startswith(prefix) for h in self.hints) and \
                not _starts_a_word(prefix):
            self.say(u"No label \"{}\" in view.".format(prefix), True)
        return text

    def _picked_codes(self):
        return [c for c in self._typed_codes() if self.code_keys.get(c) in self.added]

    def _follow_tree(self, text, words, first, inserted):
        """After edit, suppress, rollto, hide...: labels on the tree's rows (and,
        for edit, on the faces in view)."""
        from . import widget_hints as wh
        part = line_ex._part()
        if part is None:
            return text
        if first in line_complete.BODY_ARGS:
            objs = line_ex.bodies(part)
        elif first == "edit":
            objs = line_ex.tree_objects(part)
        else:
            objs = line_ex.features(part)
        if not self.whints or self.hint_kinds != ("tree", first):
            host, self.whints = wh.tree_hints(objs, part)
            view = ("Face",) if first == "edit" else None
            self.hints = []
            if view:
                try:
                    v = Gui.ActiveDocument.ActiveView
                    p = self.parentWidget()
                    ratio = float(v.getSize()[0]) / max(1, p.width())
                    self.hints = hm.visible(v, hm.view_objects(App.ActiveDocument), view, ratio,
                                            p.height())
                except Exception:
                    self.hints = []
            hm.assign(self.whints + self.hints)
            self.code_keys = {h.code: h.key() for h in self.hints}
            self.hint_kinds = ("tree", first)
        last = words[-1]
        many = first in line_complete.LIST_ARGS
        cur = last.rpartition(",")[2] if many else last
        hit = next((h for h in self.whints + self.hints if h.code == cur), None) if cur else None
        if inserted and hit is not None:
            name = hit.name if hasattr(hit, "target") else self._feature_name_of(hit)
            if name:
                words[-1] = last[:len(last) - len(cur)] + name + ("," if many else "")
                text = " ".join(words)
                self.edit.setText(text)
                cur = ""
        prefix = cur if cur and all(c in hm.ALPHABET for c in cur.lower()) else ""
        if cur and not prefix:
            self._hide_widget_overlays()
            self.show_hints(False)
            return text
        self._show_widget_hints(self.whints, prefix)
        if self.hints:
            self.overlay.set_state(self.hints, prefix, [])
            self.show_hints(True)
        else:
            self.show_hints(False)
        return text

    def _feature_name_of(self, hint):
        f = self.feature_from_code(hint.code)
        return line_ex.clean(f.Label) if f is not None else ""

    def hint_clicked(self, code):
        """A label clicked: as if typed (in a panel or the toolbar: done at once)."""
        if self.mode in ("panel", "toolbar"):
            h = next((x for x in self.whints if x.code == code), None)
            if h is not None:
                self._act_on(h)
            return
        words = self.edit.text().split(" ")
        last = words[-1]
        if "=" in last and last.split("=", 1)[0].lower() in hm.SEL_KEYS:
            key, value = last.split("=", 1)
            parts = value.split(",")
            if code in self._picked_codes():
                parts = [c for c in parts if line_select.code_and_motions(c)[0] != code]
            else:
                parts[-1] = code
            words[-1] = key + "=" + ",".join(parts)
        else:
            many = words[0].lower() in line_complete.LIST_ARGS
            cur = last.rpartition(",")[2] if many else last
            words[-1] = last[:len(last) - len(cur)] + code
        text = " ".join(words)
        self.edit.setText(text)
        self.typed = text[:-1]              # as if the last letter was just typed
        self.edit.setFocus()
        self.suggest()

    def show_hints(self, on):
        if on:
            self.overlay.setGeometry(self.parentWidget().rect())
            self.overlay.show()
            self.overlay.raise_()
            self.raise_()
            if self.list.isVisible():
                self.list.raise_()
            self.cam_timer.start()
        else:
            self.overlay.hide()
            self.cam_timer.stop()

    def _overlay_for(self, host):
        o = self.overlays.get(id(host))
        if o is None or not cl._alive(o):
            o = hm.make_overlay(host)
            o.clicked.connect(self.hint_clicked)
            self.overlays[id(host)] = o
        return o

    def _show_widget_hints(self, whints, prefix):
        by_host = {}
        for h in whints:
            by_host.setdefault(id(h.host), (h.host, []))[1].append(h)
        for key, o in list(self.overlays.items()):
            if key not in by_host and cl._alive(o):
                o.hide()
        for _k, (host, hs) in by_host.items():
            o = self._overlay_for(host)
            o.set_state(hs, prefix, [])
            o.show()
            o.raise_()

    def _hide_widget_overlays(self):
        for o in self.overlays.values():
            if cl._alive(o):
                o.hide()

    def _camera(self):
        try:
            cam = Gui.ActiveDocument.ActiveView.getCameraNode()
            return (tuple(cam.position.getValue().getValue()),
                    tuple(cam.orientation.getValue().getValue()),
                    getattr(cam, "height", None) and cam.height.getValue(),
                    tuple(Gui.ActiveDocument.ActiveView.getSize()))
        except Exception:
            return None

    def _camera_moved(self):
        """The view turned or zoomed: label what can be seen now (picked elements
        keep their labels)."""
        if not self.overlay.isVisible() or self.hint_kinds is None or \
                self.hint_kinds[0] == "tree":
            return
        cam = self._camera()
        if cam == self._cam:
            return
        if getattr(self, "_moving", None) != cam:
            self._moving = cam              # wait until it stops
            return
        self._view_hints(self.hint_kinds)
        last = self.edit.text().split(" ")[-1]
        cur = last.split("=", 1)[1].split(",")[-1] if "=" in last else ""
        prefix = cur if cur and all(c in hm.ALPHABET for c in cur.lower()) else ""
        self.overlay.set_state(self.hints, prefix, self._picked_codes())

    # ---------------------------------------------------------- the selection

    def context(self, cmd=None):
        kinds = hm.sel_kinds("sel", cmd) if cmd else hm.DEFAULT_KINDS
        try:
            view = Gui.ActiveDocument.ActiveView
        except Exception:
            view = None
        return line_select.Context(App.ActiveDocument, cmd, dict(self.code_keys), self.point,
                                   view, kinds)

    def sync(self, text, final=False):
        """Select what the line's sel= words name (and unselect what they no
        longer do). Returns the problems."""
        words = text.split(" ")
        cmd = cl.find_tool(line_ex.expand_alias(words[0]).split(" ")[0]) \
            if len(words) > 1 and "=" not in words[0] else None
        ctx = self.context(cmd)
        want, problems = [], []
        for i, _key, value in _sel_tokens(words):
            parts = value.split(",")
            if i == len(words) - 1 and not final:
                # The part being typed counts once it is a whole label (with any
                # steps after it); a word or a filter, once the comma follows it.
                cur = parts.pop()
                if line_select.is_code(cur) and \
                        line_select.code_and_motions(cur)[0] in self.code_keys:
                    parts.append(cur)
            keys, probs = line_select.resolve(parts, ctx)
            want += [k for k in keys if k not in want]
            problems += probs
        self._own = True
        try:
            for k in [k for k in self.added if k not in want]:
                try:
                    Gui.Selection.removeSelection(*k)
                except Exception:
                    pass
                self.added.discard(k)
            for k in want:
                if k not in self.added:
                    try:
                        Gui.Selection.addSelection(*k)
                    except Exception:
                        continue
                    self.added.add(k)
        finally:
            self._own = False
        self._want = want
        return problems

    # ---------------------------------------------------------- clicks in the view

    def _watch(self, on):
        """While the line is open, a click on the model adds what was clicked to
        the sel= being typed (as its label, or its name if it has none), and a
        Ctrl+click on a pick takes it out."""
        w = getattr(self, "_watcher", None)
        if on and w is None:
            self._watcher = _Clicks(self)
            Gui.Selection.addObserver(self._watcher)
        elif not on and w is not None:
            try:
                Gui.Selection.removeObserver(w)
            except Exception:
                pass
            self._watcher = None

    def _sel_word(self):
        """(index of the sel= word being typed, its key, its value), or None."""
        words = self.edit.text().split(" ")
        toks = _sel_tokens(words)
        if not toks or toks[-1][0] != len(words) - 1:
            return None
        return toks[-1]

    def token_for(self, key):
        """What to type for an element: its label, else its name (Body.Edge3)."""
        code = next((c for c, k in self.code_keys.items() if k == key), None)
        if code:
            return code
        try:
            obj = App.getDocument(key[0]).getObject(key[1])
        except Exception:
            return None
        if obj is None:
            return None
        name = line_select.token_name(obj)
        return name + "." + key[2] if key[2] else name

    def clicked(self, key):
        """The user clicked ``key`` in the view (or the tree)."""
        if self.mode != "line" or not self.isVisible():
            return
        sw = self._sel_word()
        if sw is None:
            self._resync()
            return
        tok = self.token_for(key)
        if tok is None:
            return
        i, k, value = sw
        parts = value.split(",")
        if tok not in parts:
            cur = parts[-1]
            if cur == "" or (cur and all(c in hm.ALPHABET for c in cur.lower()) and
                             cur not in self.code_keys):
                parts[-1] = tok             # in place of an empty or half-typed part
            else:
                parts.append(tok)
            parts.append("")
        words = self.edit.text().split(" ")
        words[i] = k + "=" + ",".join(parts)
        text = " ".join(words)
        self.edit.setText(text)
        self.typed = text
        self.added.discard(key)             # selected by the click: sync keeps it
        self.suggest()
        self._refocus()

    def _focus_moved(self, old, new):
        """A click in the 3D view (to pick, or to turn it) takes the keyboard there;
        while the line is open it stays with the line."""
        try:
            if new is None or not self.isVisible() or new is self.edit:
                return
            if new is self.view or self.view.isAncestorOf(new):
                QtCore.QTimer.singleShot(0, lambda: self.isVisible() and self.edit.setFocus())
        except RuntimeError:
            pass                            # the bar is gone

    def _refocus(self):
        """Back to typing after a click in the view (which takes the focus as the
        button comes up)."""
        self.edit.setFocus()
        QtCore.QTimer.singleShot(50, lambda: self.isVisible() and self.edit.setFocus())

    def unclicked(self, key):
        """A pick Ctrl+clicked off: out of the line."""
        if self.mode != "line" or key not in self.added:
            return
        self.added.discard(key)
        tok = self.token_for(key)
        sw = self._sel_word() or next(iter(_sel_tokens(self.edit.text().split(" "))), None)
        if sw is None or tok is None:
            return
        i, k, value = sw
        parts = [x for x in value.split(",") if line_select.code_and_motions(x)[0] != tok]
        words = self.edit.text().split(" ")
        words[i] = k + "=" + ",".join(parts)
        text = " ".join(words)
        self.edit.setText(text)
        self.typed = text
        self.suggest()
        self._refocus()

    def _resync(self):
        """A click cleared the selection: the line's picks come back."""
        if not self.isVisible() or self.mode != "line":
            return
        self.added = set(k for k in self.added if _is_selected(k))
        self.sync(self.edit.text())
        self.overlay.set_state(self.hints, self.overlay.prefix, self._picked_codes())
        self._refocus()

    # The line's own commands ask these (see line_ex).
    def feature_from_code(self, code):
        """The feature that made the face labelled ``code`` in the view."""
        from ..app import part as part_mod
        key = self.code_keys.get(code)
        if key is None:
            h = next((x for x in self.whints if x.code == code), None)
            return h.target if h is not None else None
        try:
            obj = App.getDocument(key[0]).getObject(key[1])
            elem = obj.Shape.getElement(key[2])
            part = part_mod.source_part(obj)
            return part_mod.feature_of_element(part, elem)
        except Exception:
            return None

    def selection_keys(self):
        return list(getattr(self, "_want", []) or [])

    # ---------------------------------------------------------- live preview

    def update_preview(self):
        """Make the line's feature in the background, show it, say what's wrong."""
        from . import line_preview
        if self.mode != "line" or not self.isVisible():
            return
        self.preview.clear("line")
        text = line_ex.expand_alias(self.edit.text().strip())
        rest = strip_selection(text)
        words = rest.split(" ")
        if " " not in text or not rest or words[0].lower() in line_ex.COMMANDS or \
                rest.startswith("'"):
            return                          # the tool's name is still being typed
        fl = line_ex.feature_line(rest)
        had_focus = self.edit.hasFocus()
        try:
            if fl is not None:
                node, problem = line_preview.dry_edit(fl[0], fl[1])
            else:
                line = cl.parse(rest)
                if line.error:
                    if len(words) > 1:
                        self.say(line.error, True)
                    return
                self._previewing = True
                try:
                    node, problem = line_preview.dry_run(line.cmd, line, self.under)
                finally:
                    self._previewing = False
        except Exception as e:
            node, problem = None, str(e)
        if had_focus and not self.edit.hasFocus():
            self.edit.setFocus()            # running a tool puts the focus in the view
        if node is not None:
            self.preview.attach()
            self.preview.set("line", node)
        self.say("; ".join(list(self.problems) + ([problem] if problem else [])), True)

    # ---------------------------------------------------------- history search (Ctrl+R)

    def history_mode(self, on):
        self.mode = "history" if on else "line"
        self._set_prompt()
        self.preview.clear("line")
        self.show_hints(False)
        self._hide_widget_overlays()
        if on:
            self._before_search = self.edit.text()
            self.edit.clear()
            self.edit.set_ghost("")
            self._history_suggest("")
        else:
            self.suggest()

    def _history_suggest(self, text):
        from . import command_search
        entries = list(reversed(self.hist))          # newest first
        if text:
            # As a shell's Ctrl+R: lines with the text in them, newest first; then
            # those with its letters in order.
            t = text.lower()
            exact = [h for h in entries if t in h.lower()]
            loose = [h for h in entries if h not in exact and
                     command_search.fuzzy(text, h) is not None]
            entries = exact + loose
        self.cands = [(h, h) for h in entries[:30]]
        self.cpos = 0 if self.cands else -1
        self.list.clear()
        for _p, shown in self.cands:
            self.list.addItem(shown)
        if self.cands:
            self.list.setCurrentRow(0)
        self.edit.set_ghost("")
        self._place_list()

    # ---------------------------------------------------------- a panel's controls

    def _panel_hints(self):
        from . import widget_hints as wh
        host, self.whints = wh.panel_hints(self.panel)
        hm.assign(self.whints)
        self._show_widget_hints(self.whints, "")
        if not self.whints:
            self.say("This panel has no controls to label.", True)

    def _panel_follow(self, text, inserted):
        from . import widget_hints as wh
        last = text.split(" ")[-1]
        cur = last.split("=", 1)[0] if last else ""
        prefix = cur if cur and "=" not in last and all(c in hm.ALPHABET for c in cur.lower()) \
            else ""
        self._show_widget_hints(self.whints, prefix)
        names = []
        if self.panel is not None and getattr(self.panel, "widget", None) is not None:
            names = [n for _w, n in wh.controls(self.panel.widget) if n]
        self.cands = []
        if cur and "=" not in last and not prefix:
            self.cands = [(cl.norm(n) + "=", u"{}=  —  set {}".format(cl.norm(n), n))
                          for n in names if cl.norm(n).startswith(cl.norm(cur))][:10]
        self._fill_list()

    def _panel_enter(self, text):
        from . import widget_hints as wh
        codes = {h.code: h for h in self.whints}
        actions = []
        for tok in [t for t in text.split(" ") if t]:
            if "=" in tok:
                name, value = tok.split("=", 1)
                h = codes.get(name)
                w = h.target if h is not None else wh.by_name(self.panel, name)
                if isinstance(w, str):
                    self.say(w, True)
                    return
                actions.append((w, value))
            else:
                h = codes.get(tok)
                if h is None:
                    self.say(u"No label \"{}\".".format(tok), True)
                    return
                actions.append((h.target, None))
        self.close_bar(keep=True)
        for w, value in actions:
            if value is None:
                QtCore.QTimer.singleShot(0, lambda w=w: wh.go(w))
            else:
                problem = wh.set_value(w, value)
                if problem:
                    cl._say(problem)

    # ---------------------------------------------------------- the toolbar's buttons

    def _toolbar_hints(self):
        from . import widget_hints as wh
        host, self.whints = wh.toolbar_hints()
        hm.assign(self.whints)
        self._toolbar_follow("", False)

    def _toolbar_hits(self, cur):
        """The buttons for what's typed: labels it starts, then names that match
        it (typing a tool's name works too), each once."""
        from . import command_search
        by_code = [h for h in self.whints if cur and h.code.startswith(cur)] \
            if all(c in hm.ALPHABET for c in cur) else []
        if not cur:
            return list(self.whints)
        scored = [(command_search.fuzzy(cur, h.name), h) for h in self.whints
                  if h not in by_code and h.name]
        by_name = [h for sc, h in sorted([x for x in scored if x[0] is not None],
                                         key=lambda x: -x[0])]
        return by_code + by_name

    def _toolbar_follow(self, text, inserted):
        """A whole label clicks its button at once. The list says what each
        label is, and narrows as you type (by label or by name)."""
        cur = text.strip()
        h = next((x for x in self.whints if x.code == cur), None)
        if h is not None and inserted:
            self._act_on(h)
            return
        prefix = cur if all(c in hm.ALPHABET for c in cur) else ""
        hits = self._toolbar_hits(cur)
        self._tb_hits = hits
        self._show_widget_hints([x for x in self.whints if not cur or x in hits],
                                prefix if any(x.code.startswith(prefix) for x in hits) else "")
        self.cands = [(x.code, u"{}  —  {}".format(x.code, x.name)) for x in hits]
        self.cpos = 0 if hits else -1
        self.list.clear()
        for _p, shown in self.cands:
            self.list.addItem(shown)
        if hits:
            self.list.setCurrentRow(0)
        self.edit.set_ghost("")
        self._place_list()
        if cur and not hits:
            self.say(u"No button \"{}\".".format(cur), True)
        else:
            self.say("")

    def _toolbar_enter(self, text):
        """Enter: the button at the top of the list (or the one Tab went to)."""
        hits = getattr(self, "_tb_hits", [])
        if not hits:
            self.say(u"No button \"{}\".".format(text.strip()), True)
            return
        row = self.list.currentRow()
        self._act_on(hits[row] if 0 <= row < len(hits) else hits[0])

    def _act_on(self, h):
        from . import widget_hints as wh
        w = h.target
        self.close_bar(keep=True)
        QtCore.QTimer.singleShot(0, lambda: wh.go(w))

    # ---------------------------------------------------------- Enter

    def enter(self):
        text = self.edit.text().strip()
        if self.mode == "history":
            pick = self.cands[self.cpos][0] if 0 <= self.cpos < len(self.cands) else \
                getattr(self, "_before_search", "")
            self.mode = "line"
            self._set_prompt()
            self.edit.setText(pick)
            self.suggest()
            return
        if not text:
            self.close_bar()
            return
        if self.mode == "panel":
            self._panel_enter(text)
            return
        if self.mode == "toolbar":
            self._toolbar_enter(text)
            return
        full = line_ex.expand_alias(text)
        sel_problems = self.sync(full, final=True)
        if sel_problems:
            self.say("; ".join(sel_problems), True)
            return
        notes = [line_ex.store_register(r, self.selection_keys()) for r in register_tokens(full)]
        rest = strip_selection(full)
        if not rest:
            n = len(self.added)
            cl.add_history(text)
            self.close_bar(keep=True)
            cl._say(" ".join(notes) or ("{} picked.".format(n) if n != 1 else "1 picked."))
            return
        self.preview_timer.stop()
        self.preview.clear()
        try:
            r = line_ex.run(rest, self)
        except Exception as e:
            r = "{}: {}".format(type(e).__name__, e)
        if isinstance(r, line_ex.Action):
            cl.add_history(text)
            self._do(r, notes)
            return
        if r is not None:
            cl.add_history(text)
            self.close_bar(keep=True)
            cl._say(" ".join(notes + [r]).strip())
            return
        line = cl.parse(rest)
        if line.error:
            self.say(line.error, True)
            self.edit.selectAll()
            return
        cl.add_history(text)
        under = self.under
        self.close_bar(keep=True)
        QtCore.QTimer.singleShot(0, lambda: cl._say(" ".join(
            notes + [cl.execute(line.cmd, line=line, under=under)[1] or ""]).strip()))

    def _do(self, action, notes=()):
        from . import line_help
        if notes:
            cl._say(" ".join(notes))
        if action.kind == "help":
            parent = self.parentWidget()
            self.close_bar()
            line_help.show(parent, line_help.find(action.arg) if action.arg else None)
        elif action.kind == "toolbar":
            self.edit.clear()
            self.mode = "toolbar"
            self._set_prompt()
            self.list.hide()
            self.preview.clear()
            self.show_hints(False)
            self._toolbar_hints()
        else:
            self.close_bar(keep=True)

    # ---------------------------------------------------------- keys

    def eventFilter(self, obj, ev):
        if obj is self.parentWidget() and ev.type() == QtCore.QEvent.Resize:
            if self.isVisible():
                self.place()
            return False
        if obj is self.edit and ev.type() == QtCore.QEvent.KeyPress:
            k = ev.key()
            ctrl = bool(ev.modifiers() & QtCore.Qt.ControlModifier)
            if ctrl and k == QtCore.Qt.Key_R:
                self.history_mode(self.mode != "history")
                return True
            if ctrl and k == QtCore.Qt.Key_X and self.mode == "line" and \
                    not self.edit.hasSelectedText():
                self.toggle_xray()
                return True
            if k == QtCore.Qt.Key_Tab:
                self.complete(1)
                return True
            if k == QtCore.Qt.Key_Backtab:
                self.complete(-1)
                return True
            if k == QtCore.Qt.Key_Right and self.edit.ghost and \
                    self.edit.cursorPosition() == len(self.edit.text()):
                self.complete(1)
                return True
            if k in (QtCore.Qt.Key_Up, QtCore.Qt.Key_Down):
                if self.mode == "history":
                    self.complete(-1 if k == QtCore.Qt.Key_Up else 1)
                    return True
                if self.hist and self.mode == "line":
                    self.hpos = max(0, min(len(self.hist), self.hpos +
                                           (-1 if k == QtCore.Qt.Key_Up else 1)))
                    self.edit.setText(self.hist[self.hpos] if self.hpos < len(self.hist)
                                      else "")
                    self.typed = self.edit.text()
                    self.suggest()
                    return True
            if k in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                self.enter()
                return True
            if k == QtCore.Qt.Key_Escape:
                if self.mode == "history":
                    self.mode = "line"
                    self._set_prompt()
                    self.edit.setText(getattr(self, "_before_search", ""))
                    self.suggest()
                else:
                    self.close_bar()
                return True
        return super(CommandBar, self).eventFilter(obj, ev)
