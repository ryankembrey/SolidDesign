# SPDX-License-Identifier: LGPL-2.1-or-later
"""Evaluate tools that aren't features: What's Wrong and Force Rebuild.

What's Wrong lists every problem in the document (features, reference geometry,
sketches), with what follows from another nested under it. Picking one says what
happened, why (where it can be told) and what to do, shows it in the view with a
label on each thing drawn and a key to the colours, and offers what fixes it:
Edit, Looks Right (a repaired reference checked), Roll Back to Here, Suppress,
Zoom to It. Check Geometry looks for invalid bodies, tiny edges and slivers.

Measure, Mass Properties and variables (VarSet) are FreeCAD's own, on its
toolbars whatever the workbench.
"""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from .. import icon
from ..app import health
from ..app import part as part_mod
from ..app import refs, util
from .panel import parts

LAST = [None]       # the open dialog (for tests)

# What is drawn in the view, and the key's words for it.
LOST_COLOR = (0.88, 0.30, 0.10)         # where a lost reference was: dashed
NOW_COLOR = (0.11, 0.62, 0.18)          # what it was repaired to: solid
MAYBE_COLOR = (0.93, 0.66, 0.05)        # what could replace it: numbered
CHANGED_COLOR = (0.30, 0.55, 0.95)      # what the feature before it changed
GEOMETRY_COLOR = (0.80, 0.20, 0.75)     # tiny edges, slivers
MAX_LABELS = 12


def _hex(c):
    return "#%02x%02x%02x" % tuple(int(255 * x) for x in c)


class _Dialog(object):
    """A task panel that isn't a feature's: a form of groups."""

    TITLE = ""
    ICON_NAME = ""

    def __init__(self, doc):
        self.doc = doc
        LAST[0] = self
        self.form, self.layout = parts.panel_form(self.TITLE, icon(self.ICON_NAME))
        self.error = parts.Message("error")
        self.layout.addWidget(self.error)
        self.build()
        self.layout.addStretch(1)

    def group(self, title, tip=""):
        g = parts.Group(title, tip)
        self.layout.addWidget(g)
        return g


def force_rebuild(doc):
    """Rebuild every feature from scratch (SolidWorks' Force Rebuild)."""
    for o in doc.Objects:
        if util.is_feature(o) or o.TypeId.startswith("Sketcher::SketchObject"):
            o.touch()
    doc.recompute()


def problems(doc):
    """[(object, "error" or "warning", text)] of every problem, in order."""
    return [(i.obj, i.severity, i.message) for i in health.flat(health.issues(doc, False))]


# ====================================================================== drawing

def _coin():
    from pivy import coin
    return coin


def _on_top(*children):
    """Drawn over the model, so what is inside or behind it still shows."""
    coin = _coin()
    sep = coin.SoAnnotation()
    pick = coin.SoPickStyle()
    pick.style = coin.SoPickStyle.UNPICKABLE
    light = coin.SoLightModel()
    light.model = coin.SoLightModel.BASE_COLOR
    sep.addChild(pick)
    sep.addChild(light)
    for c in children:
        sep.addChild(c)
    return sep


def _line(pts, color, dashed=False, width=3.0, closed=False):
    coin = _coin()
    sep = coin.SoSeparator()
    col = coin.SoBaseColor()
    col.rgb.setValue(*color)
    style = coin.SoDrawStyle()
    style.lineWidth = width
    style.pointSize = 9
    if dashed:
        style.linePattern = 0xF0F0
    coords = coin.SoCoordinate3()
    pts = [tuple(p) for p in pts]
    if closed and len(pts) > 2:
        pts.append(pts[0])
    coords.point.setValues(0, len(pts), pts)
    for n in (col, style, coords):
        sep.addChild(n)
    if len(pts) == 1:
        sep.addChild(coin.SoPointSet())
    else:
        ls = coin.SoLineSet()
        ls.numVertices.setValue(len(pts))
        sep.addChild(ls)
    return sep


def _label(text, p, color, below=False):
    """A framed label (text on white, the same size at any zoom) at ``p``, above
    it (or ``below``)."""
    coin = _coin()
    sep = coin.SoSeparator()
    tr = coin.SoTranslation()
    tr.translation.setValue(*tuple(p))
    sep.addChild(tr)
    t = coin.SoType.fromName("SoFrameLabel")
    if not t.isBad() and t.canCreateInstance():
        lab = t.createInstance()
        lab.string.setValue(text)
        lab.textColor.setValue(*[0.6 * c for c in color])
        lab.backgroundColor.setValue(1.0, 1.0, 1.0)
        lab.frame = True
        lab.border = True
        lab.size = 11
        lab.horAlignment = coin.SoImage.LEFT
        lab.vertAlignment = coin.SoImage.TOP if below else coin.SoImage.BOTTOM
    else:
        col = coin.SoBaseColor()
        col.rgb.setValue(*color)
        sep.addChild(col)
        lab = coin.SoText2()
        lab.string = text
    sep.addChild(lab)
    return sep


def _at(pts, frac=0.5):
    return pts[min(len(pts) - 1, int(len(pts) * frac))] if pts else None


def _shape_pts(shape):
    return refs.outline(shape) or []


def same_place(a, b, tol=1e-3):
    """Whether two outlines (lists of points) lie on each other."""
    if not a or not b:
        return False
    va = [App.Vector(*p) for p in a]
    vb = [App.Vector(*p) for p in b]
    return all(min((p - q).Length for q in vb) <= tol for p in va) and \
        all(min((p - q).Length for q in va) <= tol for p in vb)


class Picture(object):
    """What a problem shows in the view: nodes and the key's lines."""

    same = False            # a repaired reference lies where the lost one was

    def __init__(self):
        self.nodes = []
        self.key = []           # (color, dashed, words)
        self.points = []        # for Zoom to It

    def add(self, pts, color, dashed, label, closed=False, width=3.0, at=0.5, below=False):
        """A line through ``pts``, labelled at ``at`` of the way along, above the
        line (or ``below``), so two labels on the same place don't cover each
        other."""
        if not pts:
            return
        self.nodes.append(_line(pts, color, dashed, width, closed))
        self.points.extend(pts)
        if label:
            self.nodes.append(_label(label, _at(pts, at), color, below))

    def legend(self, color, dashed, words):
        if (color, dashed, words) not in self.key:
            self.key.append((color, dashed, words))

    def node(self):
        return _on_top(*self.nodes) if self.nodes else None


def picture(issue):
    """The view's picture of a problem, with a label on everything drawn."""
    pic = Picture()
    o = issue.obj
    for r in issue.repaired:
        old, new = r.get("old") or {}, r.get("new") or {}
        word = health.WORDS.get(old.get("kind") or new.get("kind"), "element")
        what = r.get("what") or word
        face = (old.get("kind") or new.get("kind")) == "Face"
        pic.add(old.get("pts"), LOST_COLOR, True, u"Lost {} (was here)".format(what),
                closed=face, at=0.3)
        pic.add(new.get("pts"), NOW_COLOR, False, u"Now uses this {}".format(word),
                closed=face, width=4.0, at=0.7, below=True)
        pic.legend(LOST_COLOR, True, u"Where the lost {} was".format(what))
        pic.legend(NOW_COLOR, False, u"The {} it was repaired to".format(word))
        if same_place(old.get("pts"), new.get("pts")):
            pic.same = True
    for r in issue.lost:
        old = r.get("old") or {}
        word = health.WORDS.get(old.get("kind"), "element")
        what = r.get("what") or word
        face = old.get("kind") == "Face"
        pic.add(old.get("pts"), LOST_COLOR, True, u"Lost {} (was here)".format(what),
                closed=face)
        pic.legend(LOST_COLOR, True, u"Where the lost {} was".format(what))
        cands = refs.candidates(o, r)
        if len(cands) > 1:
            for k, e in enumerate(cands[:MAX_LABELS], 1):
                pic.add(_shape_pts(e), MAYBE_COLOR, False, str(k), closed=face, width=4.0)
            pic.legend(MAYBE_COLOR, False, u"{}s that could replace it (numbered)".format(
                word.capitalize()))
    for k, (e, text) in enumerate(issue.elements):
        pts = _shape_pts(e)
        pic.add(pts, GEOMETRY_COLOR, False, text if k < MAX_LABELS else "",
                closed=e.ShapeType == "Face", width=4.0)
        if pts:         # a dot too: a tiny edge is too small to see as a line
            pic.nodes.append(_line([_at(pts)], GEOMETRY_COLOR, width=1.0))
        pic.legend(GEOMETRY_COLOR, False, issue.message.rstrip("."))
    c = issue.culprit
    shape = getattr(c, "AddSubShape", None) if c is not None and issue.kind != "geometry" \
        else None
    if shape is not None and not shape.isNull() and pic.nodes:
        from . import preview as pv
        pic.nodes.insert(0, pv.shape_node(shape, CHANGED_COLOR, 0.8, edges=True,
                                          line_width=1.5, edge_color=CHANGED_COLOR))
        bb = shape.BoundBox
        pic.nodes.append(_label(u"Changed by {}".format(part_mod.clean_label(c.Label)),
                                bb.Center, CHANGED_COLOR))
        pic.points.extend([[bb.XMin, bb.YMin, bb.ZMin], [bb.XMax, bb.YMax, bb.ZMax]])
        pic.legend(CHANGED_COLOR, False, u"What {} changed".format(
            part_mod.clean_label(c.Label)))
    return pic


def zoom_to(points):
    """Fit the view round ``points`` ([x, y, z]), with room to spare."""
    if not points:
        return
    try:
        coin = _coin()
        view = Gui.ActiveDocument.ActiveView
        bb = App.BoundBox()
        for p in points:
            bb.add(App.Vector(*p))
        size = max(bb.DiagonalLength, 1.0)
        sep = coin.SoSeparator()
        cube = coin.SoCube()
        cube.width = cube.height = cube.depth = size * 1.6
        tr = coin.SoTranslation()
        tr.translation.setValue(bb.Center.x, bb.Center.y, bb.Center.z)
        sep.addChild(tr)
        sep.addChild(cube)
        region = view.getViewer().getSoRenderManager().getViewportRegion()
        view.getCameraNode().viewAll(sep, region)
    except Exception:
        try:
            Gui.SendMsgToActiveView("ViewFit")
        except Exception:
            pass


# ====================================================================== what's wrong

class WhatsWrongDialog(_Dialog):
    """SolidWorks' What's Wrong, and more: what happened, why, what to do, shown
    in the view, with the fixes at hand."""

    TITLE = "What's Wrong"
    ICON_NAME = "WhatsWrong"

    def __init__(self, doc):
        from . import preview as pv
        self.preview = pv.Preview()
        self.items = []             # every Issue listed (problems, then geometry)
        self.geometry = None        # the last geometry check, or None
        self.suppressed = []        # suppressed here, to unsuppress here
        self._by_item = {}
        super(WhatsWrongDialog, self).__init__(doc)
        self.form.installEventFilter(self._shown_filter())
        preview = self.preview
        self.form.destroyed.connect(lambda *_a: preview.clear())
        self.reload()

    def _shown_filter(self):
        """However the panel goes (Close, another tool, the document closed), what
        it drew goes with it; shown again, it is drawn again."""
        dialog = self

        class Shown(QtCore.QObject):
            def eventFilter(self, obj, ev):
                if ev.type() == QtCore.QEvent.Hide:
                    dialog._close()
                elif ev.type() == QtCore.QEvent.Show and dialog._pic is None:
                    QtCore.QTimer.singleShot(0, lambda: dialog._select(
                        dialog.tree.currentItem()))
                return False
        self._shown = Shown()
        return self._shown

    _pic = None

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Close

    # ------------------------------------------------------------ building
    def build(self):
        self.summary = parts.Message("info")
        self.layout.addWidget(self.summary)
        g = self.group("Problems", "Problems in the model; one that follows from another "
                       "is under it")
        self.tree = parts.wrapped_tree()
        self.tree.currentItemChanged.connect(lambda cur, _prev: self._select(cur))
        self.tree.itemDoubleClicked.connect(lambda it, _col: self._edit())
        self.tree.installEventFilter(self._keys())
        self.tree.viewport().installEventFilter(self._resized())
        g.wide(self.tree, "Pick one to see it in the view; double-click (or Enter) to edit")
        self.list = self.tree           # the old name
        g = self.sec_detail = self.group("Details")
        self.detail = QtWidgets.QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(QtCore.Qt.RichText)
        self.detail.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        g.wide(self.detail)
        self.key = QtWidgets.QLabel("")
        self.key.setWordWrap(True)
        self.key.setTextFormat(QtCore.Qt.RichText)
        g.wide(self.key, "What the colours in the view mean")
        box = QtWidgets.QWidget()
        grid = QtWidgets.QGridLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        self.b_edit = self._button("Edit", "Open the feature to fix it (or double-click it)",
                                   self._edit)
        self.b_ok = self._button("Looks Right", "The repaired reference is the right one: "
                                 "stop warning about it", self._looks_right)
        self.b_zoom = self._button("Zoom to It", "Fit the view round what is shown",
                                   self._zoom)
        self.b_roll = self._button("Roll Back to Here", "Move the rollback bar to just before "
                                   "it, to see the model as that feature found it",
                                   self._roll)
        self.b_supp = self._button("Suppress", "Leave the feature out of the model for now; "
                                   "the features after it are built without it",
                                   self._suppress)
        for k, b in enumerate((self.b_edit, self.b_ok, self.b_zoom, self.b_roll, self.b_supp)):
            grid.addWidget(b, k // 3, k % 3)
        g.wide(box)
        g = self.group("Checks")
        row = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        self.b_geom = self._button("Check Geometry", "Look for invalid bodies, edges too "
                                   "short and faces too thin: they make later features fail",
                                   self._check_geometry)
        self.rebuild = self._button("Rebuild All", "Rebuild every feature from scratch, then "
                                    "list again", self._rebuild)
        h.addWidget(self.b_geom)
        h.addWidget(self.rebuild)
        g.wide(row)

    def _resized(self):
        dialog = self

        class Resized(QtCore.QObject):
            def eventFilter(self, obj, ev):
                if ev.type() == QtCore.QEvent.Resize:
                    QtCore.QTimer.singleShot(0, dialog._fit_rows)
                return False
        self._resize_filter = Resized()
        return self._resize_filter

    def _fit_rows(self):
        """Each row's words wrapped to the list's width, the row as tall as they
        are, and the list as tall as its rows (within reason, so the details
        below stay in sight). Wrapped here, not by Qt: under a style sheet it
        wraps some rows and cuts others short."""
        try:
            tree = self.tree
            fm = tree.fontMetrics()
            width = tree.viewport().width()
            icon_w = tree.iconSize().width() if tree.iconSize().width() > 0 else 16
            line_h = fm.lineSpacing()
            total = 0
            it_iter = QtWidgets.QTreeWidgetItemIterator(tree)
            while it_iter.value() is not None:
                it = it_iter.value()
                text = it.data(0, QtCore.Qt.UserRole)
                if text is None:
                    text = it.text(0)
                    it.setData(0, QtCore.Qt.UserRole, text)
                depth, p = 0, it.parent()
                while p is not None:
                    depth, p = depth + 1, p.parent()
                w = max(60, width - tree.indentation() * (depth + 1) - icon_w - 16)
                lines = _wrap(text, fm, w)
                it.setText(0, u"\n".join(lines))
                h = max(len(lines) * line_h, icon_w) + 10      # and the 2 px padding
                it.setSizeHint(0, QtCore.QSize(w, h))
                total += h
                it_iter += 1
            tree.doItemsLayout()
            tree.setFixedHeight(max(60, min(240, total + 2 * tree.frameWidth() + 4)))
        except RuntimeError:
            pass

    def _button(self, text, tip, fn):
        b = QtWidgets.QPushButton(text)
        b.setToolTip(tip)
        b.clicked.connect(lambda _c=False: fn())
        return b

    def _keys(self):
        dialog = self

        class Keys(QtCore.QObject):
            def eventFilter(self, obj, ev):
                if ev.type() == QtCore.QEvent.KeyPress and \
                        ev.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                    dialog._edit()
                    return True
                return False
        self._key_filter = Keys()
        return self._key_filter

    # ------------------------------------------------------------ listing
    def reload(self, keep=None):
        """List the problems again (keep the one picked, if still there)."""
        if keep is None:
            cur = self.current()
            keep = cur.obj if cur is not None else None
        found = health.issues(self.doc)
        self.tree.blockSignals(True)
        self.tree.clear()
        self._by_item = {}
        self.items = []
        st = self.tree.style()
        icons = {health.ERROR: st.standardIcon(QtWidgets.QStyle.SP_MessageBoxCritical),
                 health.WARNING: st.standardIcon(QtWidgets.QStyle.SP_MessageBoxWarning)}

        def add(issue, parent):
            it = QtWidgets.QTreeWidgetItem([u"{}: {}".format(issue.title, issue.message)])
            it.setIcon(0, icons[issue.severity])
            it.setToolTip(0, issue.message)
            (parent.addChild(it) if parent is not None else self.tree.addTopLevelItem(it))
            self._by_item[id(it)] = issue
            self.items.append(issue)
            for c in issue.children:
                add(c, it)
            return it

        for i in found:
            add(i, None)
        if self.geometry is not None:
            head = QtWidgets.QTreeWidgetItem([u"Geometry check: {}".format(
                u"{} found".format(len(self.geometry)) if self.geometry else
                u"nothing found")])
            head.setFlags(QtCore.Qt.ItemIsEnabled)
            f = head.font(0)
            f.setBold(True)
            head.setFont(0, f)
            self.tree.addTopLevelItem(head)
            for i in self.geometry:
                add(i, head)
        if self.suppressed:
            head = QtWidgets.QTreeWidgetItem([u"Suppressed here: {}".format(
                ", ".join(part_mod.clean_label(o.Label) for o in self.suppressed))])
            head.setFlags(QtCore.Qt.ItemIsEnabled)
            head.setToolTip(0, "Pick one of these features in the list to unsuppress it")
            self.tree.addTopLevelItem(head)
            for o in self.suppressed:
                i = health.Issue(o, util.part_of(o), health.WARNING, "Suppressed")
                i.hint = "It is left out of the model. Press Unsuppress to put it back."
                add(i, head)
        if not self.items:
            it = QtWidgets.QTreeWidgetItem(["Nothing is wrong: every feature rebuilt cleanly."])
            it.setFlags(QtCore.Qt.NoItemFlags)
            self.tree.addTopLevelItem(it)
        self.tree.expandAll()
        self.tree.blockSignals(False)
        self._fit_rows()
        self._summary(found)
        # Pick one: the one picked before, else the first problem.
        target = None
        it_iter = QtWidgets.QTreeWidgetItemIterator(self.tree)
        while it_iter.value() is not None:
            it = it_iter.value()
            iss = self._by_item.get(id(it))
            if iss is not None and (target is None or iss.obj is keep):
                if target is None or iss.obj is keep:
                    target = it
                if iss.obj is keep:
                    break
            it_iter += 1
        if target is not None:
            self.tree.setCurrentItem(target)
        self._select(target)

    def _summary(self, found):
        all_ = health.flat(found)
        e = sum(1 for i in all_ if i.is_error())
        w = len(all_) - e
        geo = len(self.geometry or [])
        geo_words = u" The geometry check found {} thing{} to look at.".format(
            geo, "s" if geo > 1 else "") if geo else ""
        if not all_:
            self.summary.set(u"Every feature rebuilt cleanly.{}".format(geo_words)
                             if geo else "Nothing is wrong: every feature rebuilt cleanly.",
                             "warning" if geo else "info")
            return
        words = []
        if e:
            words.append("{} error{}".format(e, "s" if e > 1 else ""))
        if w:
            words.append("{} warning{}".format(w, "s" if w > 1 else ""))
        roots = len(found)
        tail = "" if roots == len(all_) else u" ({} to fix first)".format(roots)
        self.summary.set(u"{}{}. Pick one to see it in the view.{}".format(
            " and ".join(words), tail, geo_words), "error" if e else "warning")

    def current(self):
        it = self.tree.currentItem()
        return self._by_item.get(id(it)) if it is not None else None

    # ------------------------------------------------------------ the one picked
    def _select(self, it):
        issue = self._by_item.get(id(it)) if it is not None else None
        self.preview.clear()
        self._pic = None
        if issue is None:
            self.detail.setText("")
            self.key.setText("")
            self.sec_detail.setVisible(bool(self._rolled_parts()))
            for b in (self.b_edit, self.b_ok, self.b_zoom, self.b_supp):
                b.setEnabled(False)
            self._roll_button(None)
            return
        self.sec_detail.setVisible(True)
        pic = picture(issue)
        self._pic = pic
        node = pic.node()
        if node is not None:
            self.preview.set("problem", node)
        html = [u"<b>{}</b> &nbsp;<span style='color:{}'>{}</span>".format(
            issue.title, "#c62828" if issue.is_error() else "#b26a00",
            "error" if issue.is_error() else "warning")]
        html.append(u"<p style='margin-top:4px'>{}</p>".format(issue.message))
        if issue.why:
            html.append(u"<p><b>Why:</b> {}</p>".format(issue.why))
        if pic.same:
            html.append(u"<p><b>Good sign:</b> the repaired {} is exactly where the lost one "
                        u"was, so it is very likely the right one.</p>".format(
                            health.WORDS.get((issue.repaired[0].get("new") or {}).get("kind"),
                                             "element")))
        if issue.hint:
            html.append(u"<p><b>What to do:</b> {}</p>".format(issue.hint))
        self.detail.setText(u"".join(html))
        if pic.key:
            rows = [u"<tr><td style='color:{}; font-weight:bold; padding-right:6px'>{}</td>"
                    u"<td>{}</td></tr>".format(_hex(c), u"- - -" if dashed else u"━━━",
                                               words)
                    for c, dashed, words in pic.key]
            self.key.setText(u"<b>In the view:</b><table>{}</table>".format("".join(rows)))
        else:
            self.key.setText(u"<i>Nothing to show in the view for this one.</i>")
        feature = util.is_feature(issue.obj)
        in_part = issue.part is not None and issue.kind != "geometry"
        self.b_edit.setEnabled(issue.kind != "geometry" or issue.culprit is not None)
        self.b_edit.setToolTip("Open {} to fix it".format(
            issue.title if issue.kind != "geometry" else
            (part_mod.clean_label(issue.culprit.Label) if issue.culprit else "it")))
        self.b_ok.setEnabled(bool(issue.repaired))
        self.b_zoom.setEnabled(bool(pic.points))
        self._roll_button(issue if in_part and feature else None)
        self.b_supp.setEnabled(feature and in_part or issue.obj in self.suppressed)
        self.b_supp.setText("Unsuppress" if getattr(issue.obj, "Suppressed", False)
                            else "Suppress")

    def _rolled(self, issue):
        return issue.part is not None and not part_mod.is_at_end(issue.part)

    def _rolled_parts(self):
        return [p for p in part_mod.find_parts(self.doc) if not part_mod.is_at_end(p)]

    def _roll_button(self, issue):
        """Roll Back to Here for a feature; Roll to End whenever a part is rolled
        back (a rolled-back feature isn't built, so it isn't listed to pick)."""
        rolled = self._rolled_parts()
        if rolled:
            self.b_roll.setText("Roll to End")
            self.b_roll.setToolTip("Move the rollback bar back to the end: the whole model")
            self.b_roll.setEnabled(True)
        else:
            self.b_roll.setText("Roll Back to Here")
            self.b_roll.setToolTip("Move the rollback bar to just before it, to see the "
                                   "model as that feature found it")
            self.b_roll.setEnabled(issue is not None)

    # ------------------------------------------------------------ actions
    def _edit(self):
        issue = self.current()
        if issue is None:
            return
        target = issue.obj if issue.kind != "geometry" else issue.culprit
        if target is None:
            return
        # Not now: this can run inside the tree's own double-click, and closing the
        # dialog deletes the tree, so Qt would carry on in a deleted widget and
        # FreeCAD would crash. Once the click is over, close, then edit.
        QtCore.QTimer.singleShot(0, lambda: _close_then_edit(target))

    def _looks_right(self):
        issue = self.current()
        if issue is None or not issue.repaired:
            return
        refs.accept_repairs(issue.obj)
        issue.obj.touch()
        self.doc.recompute()
        self.reload()

    def _zoom(self):
        if self._pic is not None:
            zoom_to(self._pic.points)

    def _roll(self):
        issue = self.current()
        rolled = self._rolled_parts()
        if rolled:
            for p in rolled:
                part_mod.roll_to_end(p)
            self.doc.recompute()
            self.reload(keep=issue.obj if issue is not None else None)
            return
        if issue is None or issue.part is None:
            return
        part = issue.part
        feats = util.features(part)
        k = feats.index(issue.obj) if issue.obj in feats else 0
        part_mod.roll_to(part, feats[k - 1] if k > 0 else None)
        self.doc.recompute()
        self.reload(keep=issue.obj)
        if not part_mod.is_at_end(part):
            self.summary.set(u"Rolled back to just before {}: the model as it found it. "
                             u"Roll to End when you're done.".format(issue.title), "info")

    def _suppress(self):
        issue = self.current()
        if issue is None:
            return
        o = issue.obj
        if getattr(o, "Suppressed", False):
            o.Suppressed = False
            if o in self.suppressed:
                self.suppressed.remove(o)
        else:
            o.Suppressed = True
            if o not in self.suppressed:
                self.suppressed.append(o)
        self.doc.recompute()
        self.reload(keep=o)

    def _check_geometry(self):
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            self.geometry = health.check_geometry(self.doc)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.reload(keep=self.geometry[0].obj if self.geometry else None)

    def _rebuild(self):
        force_rebuild(self.doc)
        if self.geometry is not None:
            self.geometry = health.check_geometry(self.doc)
        self.reload()

    # ------------------------------------------------------------ closing
    def _close(self):
        self._pic = None
        self.preview.clear()
        try:
            self.preview.detach()
        except Exception:
            pass

    def reject(self):
        self._close()
        Gui.Control.closeDialog()
        return True

    accept = reject


def _wrap(text, fm, width):
    """``text`` broken into lines no wider than ``width`` pixels, at spaces."""
    lines, cur = [], ""
    for word in text.split(" "):
        trial = word if not cur else cur + " " + word
        if cur and fm.horizontalAdvance(trial) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines or [""]


def _close_then_edit(f):
    try:
        d = LAST[0]
        if isinstance(d, WhatsWrongDialog):
            d._close()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        if f.Document is not None:
            f.ViewObject.Proxy.doubleClicked(f.ViewObject)
    except Exception as e:
        App.Console.PrintWarning("Solid Design: can't edit {}: {}\n".format(
            getattr(f, "Label", "?"), e))


# ====================================================================== commands

class WhatsWrongCommand(object):
    def GetResources(self):
        return {"Pixmap": icon("WhatsWrong"), "MenuText": "What's Wrong",
                "ToolTip": "Lists what's wrong in the model, why, and what to do: shows each "
                           "problem in the view and offers the fix."}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        Gui.Control.showDialog(WhatsWrongDialog(App.ActiveDocument))


class RebuildCommand(object):
    def GetResources(self):
        return {"Pixmap": icon("Rebuild"), "MenuText": "Force Rebuild",
                "ToolTip": "Rebuilds every feature from scratch."}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        force_rebuild(App.ActiveDocument)


def register():
    Gui.addCommand("SD_WhatsWrong", WhatsWrongCommand())
    Gui.addCommand("SD_Rebuild", RebuildCommand())
