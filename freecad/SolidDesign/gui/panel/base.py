# SPDX-License-Identifier: LGPL-2.1-or-later
"""The panel framework every tool shares (spec 8.1, 8.2).

Every panel is built the same way, from the parts in parts.py:

    error / warning line (only when there is something to say)
    Add | Cut switch (shape tools)
    groups, in SolidWorks' order, made with group(); rows with field(),
    list(), qty(), integer(), choice(), check() and flip(), each of which
    needs a tooltip

A FeaturePanel:
- opens a transaction, so Cancel undoes everything (a new feature disappears);
- while editing a feature that isn't last, rolls the part back to it (as
  SolidWorks does) and restores the bar on close;
- routes picks to selection boxes: the active box first; a pick that fits only
  one other box goes there; refusals are said under the box; filling a
  single-pick box moves on to the next empty one, as SolidWorks does;
- debounces previews and keeps the last good one on screen;
- shows errors in place, disables OK while the feature can't be made, and says
  why in OK's tooltip;
- Enter is OK, Escape is Cancel (FreeCAD's task panel buttons; no OK/Cancel in
  the 3D view, owner's decision 2026-11-17).
"""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from ...app import part as part_mod
from ...app import util
from ...core import topo
from .. import preview as pv
from ..selection import Sel
from . import parts
from .parts import Message

PREVIEW_DELAY_MS = 150

# Closed panels stay referenced for the session: if Python collected a panel (and
# its Python-created widgets) around the time Qt deleted them, PySide crashed.
_closed = []


def task_buttons():
    """(OK, Cancel) of the open task dialog, or (None, None)."""
    mw = Gui.getMainWindow()
    for bb in mw.findChildren(QtWidgets.QDialogButtonBox):
        p = bb.parent()
        if p is not None and p.metaObject().className() == "Gui::TaskView::TaskEditControl":
            ok = bb.button(QtWidgets.QDialogButtonBox.Ok)
            cancel = bb.button(QtWidgets.QDialogButtonBox.Cancel)
            if ok is not None or cancel is not None:
                return ok, cancel
    return None, None


def _close_dialog():
    if Gui.Control.activeDialog():
        Gui.Control.closeDialog()



def _unselect(doc, name, sub):
    try:
        Gui.Selection.removeSelection(doc, name, sub)
    except Exception:
        pass

class _DeleteGuard(QtCore.QObject):
    """While a panel is open, the Delete key never reaches FreeCAD's Delete
    command: it would delete what is selected in the tree (often the feature
    being edited), and its own undo step would end the panel's, so Cancel
    couldn't put the feature back. Delete still edits text, and still removes
    rows from a selection list (the list takes it itself)."""

    KEYS = (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace)

    def eventFilter(self, obj, ev):
        if ev.type() != QtCore.QEvent.ShortcutOverride:
            return False
        try:
            if ev.key() not in self.KEYS or ev.modifiers() != QtCore.Qt.NoModifier:
                return False
        except Exception:
            return False
        if isinstance(obj, (QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox,
                            QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit,
                            QtWidgets.QListWidget)):
            return False        # text editing, or a selection list's own Delete
        ev.accept()             # a plain key press now: no shortcut runs
        return True


class _DocWatch(object):
    """Tells a panel that its document is being closed."""

    def __init__(self, panel):
        self.panel = panel

    def slotDeletedDocument(self, doc):
        try:
            name = doc.Name
        except Exception:
            return
        if name == self.panel._doc_name:
            self.panel.document_closing()


class FeaturePanel(object):
    """Base class for a tool's task panel. Subclasses implement build() and load()."""

    TITLE = "Feature"
    ICON = ""
    # Show the model before the feature while editing (SolidWorks does for Fillet,
    # Chamfer...): every edge stays pickable; the result is the preview.
    EDIT_SHOWS_BASE = False
    # Every pick in the boxes is drawn in the selection blue; a panel that draws
    # its own (Fillet, Chamfer, Draft) says so.
    OWN_PICKS = False
    # When it takes material away, show the bodies as they come out with the old
    # ones veiled (see _cut_view). Off for tools picked on the old body's edges
    # and faces (Fillet, Chamfer, Draft): it stays as it is; only the colour says.
    CUT_VIEW = True

    def __init__(self, obj, is_new=False):
        # The handles shown for a selected feature give way to the panel's own.
        try:
            from .. import instant3d
            if instant3d.current() is not None:
                instant3d.current().clear()
        except Exception:
            pass
        self.obj = obj
        self.doc = obj.Document
        self._obj_name = obj.Name
        self._doc_name = self.doc.Name
        self.part = util.part_of(obj)
        self.is_new = is_new
        self._before = None
        if is_new:
            try:
                from .. import command_line
                self._before = command_line.snapshot(obj)
            except Exception:
                pass
        self.boxes = []
        self.active_box = None
        self.last_pick = {}         # box -> the last Sel it took (for Select Tangency...)
        self.preview = pv.Preview()
        self._closing = False
        self._recomputing = False
        self._pending = {}
        self._loading = True
        self._ghosted = {}
        self._old_tip = None
        if not is_new:
            self.doc.openTransaction("Edit " + obj.Label)
        self._delete_guard = _DeleteGuard()
        QtWidgets.QApplication.instance().installEventFilter(self._delete_guard)
        target = obj
        if self.EDIT_SHOWS_BASE:
            from ...app import feature as feature_mod
            feature_mod.EDITING.add(obj.Name)
            target = obj.BaseFeature
        if self.part is not None and self.part.Tip is not target:
            self._old_tip = self.part.Tip
            part_mod.roll_to(self.part, target)
        self._timer = QtCore.QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(PREVIEW_DELAY_MS)
        self._timer.timeout.connect(self.update_preview)

        self.widget, self.layout = parts.panel_form(self.TITLE, self.ICON or None)
        self.error = Message("error")
        self.warning = Message("warning")
        self.layout.addWidget(self.error)
        self.layout.addWidget(self.warning)
        self.build()
        self.layout.addStretch(1)
        self.form = self.widget
        self.load()
        self._loading = False
        self._ghost(True)
        Gui.Selection.addObserver(self)
        self._doc_watch = _DocWatch(self)
        App.addDocumentObserver(self._doc_watch)
        QtCore.QTimer.singleShot(0, self._after_show)

    # ------------------------------------------------------------ to override
    def build(self):
        pass

    def load(self):
        pass

    def preview_layers(self):
        """[(name, coin node)] drawn after each recompute."""
        return []

    def refresh(self):
        """Update visibility of rows and summaries after a change."""
        pass

    # ------------------------------------------------------------ text
    def body_label(self, bid):
        """A body's name as the user sees it while the panel is open."""
        from ..tool_panels import body_name_before
        return body_name_before(self.obj, bid)

    def ref_text(self, o, sub):
        """How a reference reads in a box: "Face4 · Body 1" for model geometry,
        "Edge3 · Sketch" for a sketch's, the object's name for a whole object."""
        if not sub:
            return o.Label
        owner = o.Label
        from ...app import refs, util
        if util.is_feature(o):
            try:
                import Part
                el = Part.getShape(o, sub, needSubElement=True)
                bid = refs.body_of_element(o, el)
                if bid:
                    owner = self.body_label(bid)
            except Exception:
                pass
        return u"{} \u00b7 {}".format(sub, owner)

    # ------------------------------------------------------------ building
    def group(self, title, tip="", checkable=False, prop=None):
        """A group, added to the panel. A checkable group is optional: *prop* is
        the bool property its check box sets; unchecked, its rows hide."""
        g = parts.Group(title, tip, checkable=checkable,
                        checked=bool(getattr(self.obj, prop)) if prop else True)
        if checkable and prop:
            g.toggled.connect(lambda on: self.set_prop(prop, on))
        self.layout.addWidget(g)
        return g

    def _register(self, box):
        box.activated.connect(self.activate)
        self.boxes.append(box)
        return box

    def field(self, group, label, name, what, hint, accept, tip, empty=None):
        """A one-item selection box: a row labelled *label* (None: across the
        group). *what* ("sketch") and *hint* ("Click a sketch") are its
        placeholders; *accept* is as for parts.SelectionField."""
        box = self._register(parts.SelectionField(name, what, hint, accept, tip, empty))
        box.row = group.row(label, box, tip) if label else group.wide(box)
        return box

    def list(self, group, name, what, hint, accept, tip, empty=None):
        """A several-item selection box, across the group."""
        box = self._register(parts.SelectionList(name, what, hint, accept, tip, empty))
        box.row = group.wide(box)
        menu = box.more_button.menu()
        menu.aboutToShow.connect(lambda b=box, m=menu: self._fill_more(b, m))
        box.changed.connect(lambda b=box: self._update_more(b))
        return box

    def _fill_more(self, box, menu):
        from .. import pick_tools
        menu.clear()
        sel = self.last_pick.get(box)
        if sel is not None:
            pick_tools.fill_menu(menu, self, box, sel.obj, sel.sub)

    def _update_more(self, box):
        """The chain button shows once the last pick is an edge still in the list."""
        sel = self.last_pick.get(box)
        on = sel is not None and sel.elem_kind() == "Edge" and bool(box.items)
        try:
            box.more_button.setVisible(on)
        except Exception:
            pass

    def qty(self, group, prop, label, tip, unit="mm", minimum=0.0, maximum=1e9, step=1.0,
            flip=None, flip_tip="Reverse direction"):
        """A unit field bound to *prop*; *flip*: a bool property for a flip
        button beside it. Returns (field, row)."""
        f = parts.QuantityField(self.obj, prop, unit=unit, minimum=minimum, maximum=maximum,
                                step=step)
        f.changed.connect(lambda v: self.set_prop(prop, v))
        f.connect_return(self.enter_pressed)
        control = f
        if flip:
            f.flip = self.flip_for(flip, flip_tip)
            control = parts.hbox(f, f.flip)
        return f, group.row(label, control, tip)

    def integer(self, group, prop, label, tip, minimum=1):
        f = parts.IntField(self.obj, prop, minimum=minimum)
        f.changed.connect(lambda v: self.set_prop(prop, v))
        return f, group.row(label, f, tip)

    def choice(self, group, prop, label, tip, flip=None, flip_tip="Reverse direction"):
        """A drop-down of an enumeration property; *label* None puts it across
        the group. Returns (combo, row)."""
        c = parts.combo(self.obj.getEnumerationsOfProperty(prop), getattr(self.obj, prop), tip)
        c.currentTextChanged.connect(lambda t: self.set_prop(prop, t))
        control = c
        if flip:
            c.flip = self.flip_for(flip, flip_tip)
            control = parts.hbox(c, c.flip)
        row = group.row(label, control, tip) if label else group.wide(control, tip)
        return c, row

    def check(self, group, prop, text, tip):
        """A check box bound to a bool property, across the group. Returns
        (check box, row)."""
        c = group.check(text, tip, getattr(self.obj, prop))
        c.toggled.connect(lambda on: self.set_prop(prop, on))
        return c, c.row

    def flip_for(self, prop, tip="Reverse direction"):
        """A flip button bound to a bool property (put it in a row with hbox)."""
        b = parts.flip_button(tip, getattr(self.obj, prop))
        b.toggled.connect(lambda on: self.set_prop(prop, on))
        return b

    # ------------------------------------------------------------ boxes
    def activate(self, box):
        if self.active_box is box:
            box.set_active(True)
            return
        for b in self.boxes:
            b.set_active(b is box)
        self.active_box = box
        self.on_box_activated(box)

    def on_box_activated(self, box):
        pass

    def visible_boxes(self):
        return [b for b in self.boxes if b.isVisibleTo(self.widget)]

    def next_box_needing_input(self):
        """The first visible empty box that must be filled (a box whose empty
        state means something, like "Whole sketch", needn't be)."""
        for b in self.visible_boxes():
            if not b.items and b.empty is None:
                return b
        return None

    # selection observer -------------------------------------------------
    def addSelection(self, doc, obj_name, sub, pnt):
        if self._closing or doc != self._doc_name:
            return
        obj = self.doc.getObject(obj_name)
        if obj is None:
            return
        if self._drag is not None and self._drag.busy():
            # The press that grabbed a drag arrow also clicked the model under it.
            QtCore.QTimer.singleShot(0, lambda: _unselect(doc, obj_name, sub))
            return
        sel = Sel(obj, sub, App.Vector(*pnt) if pnt else None)
        QtCore.QTimer.singleShot(0, lambda: self.route(sel))

    def route(self, sel):
        if self._closing:
            return
        taken = False
        filled = False
        box = self.active_box
        if box is not None and box.isVisibleTo(self.widget):
            r = box.offer(sel)
            if r is True:
                taken = filled = True
                self.last_pick[box] = sel
                self._update_more(box)
            elif isinstance(r, str):
                taken = True        # refused, and said so under the box
        if not taken:
            fits = []
            for b in self.visible_boxes():
                if b is box:
                    continue
                res = b.accept_fn(sel)
                if res is not None and not isinstance(res, str):
                    fits.append(b)
            if len(fits) == 1:
                self.last_pick[fits[0]] = sel
                fits[0].offer(sel)
                self._update_more(fits[0])
                self.activate(fits[0])
                box = fits[0]
                filled = True
            elif box is not None:
                box.say("That can't go in this box. {}".format(
                    "Click the box it's for first." if fits else "Pick something else."))
        # A one-item box, once filled, hands over to the next empty box; with
        # none empty, to the next list after it (where more picks go), so the
        # next click doesn't replace what was just picked (SolidWorks moves on too).
        if filled and not box.multiple and box.items:
            nxt = self.next_box_needing_input()
            if nxt is None:
                vis = self.visible_boxes()
                after = vis[vis.index(box) + 1:] if box in vis else []
                nxt = next((b for b in after if b.multiple), None)
            if nxt is not None and nxt is not box:
                self.activate(nxt)
        Gui.Selection.clearSelection()

    # ------------------------------------------------------------ changes
    def changed(self):
        """Call after writing a property: refresh the panel, schedule a preview."""
        if self._loading or self._closing:
            return
        before = set(self.visible_boxes())
        self.refresh()
        self._follow_boxes(before)
        self._show_picks()
        self._timer.start()

    def _follow_boxes(self, before):
        """A box that a choice just showed (Up To Surface shows the face box)
        becomes the active one when it needs a pick, as in SolidWorks; if the
        active box was hidden, the next box needing a pick takes over."""
        after = self.visible_boxes()
        appeared = [b for b in after if b not in before and not b.items and b.empty is None]
        if appeared:
            self.activate(appeared[0])
        elif self.active_box is not None and self.active_box not in after:
            nxt = self.next_box_needing_input()
            if nxt is not None:
                self.activate(nxt)

    def set_prop(self, name, value):
        if self._loading or self._closing:
            return
        if self._recomputing:
            # FreeCAD's recompute lets the GUI process events (its progress bar),
            # so a click can arrive mid-recompute. Changing the document then,
            # or starting a second recompute inside the first, can hang
            # FreeCAD: the change waits for the recompute to finish.
            self._pending[name] = value
            return
        try:
            if getattr(self.obj, name) != value:
                setattr(self.obj, name, value)
        except Exception as e:
            self.show_error("Can't set {}: {}".format(name, e))
            return
        self.changed()

    # ------------------------------------------------------------ preview
    def update_preview(self):
        from ...app import perf
        with perf.span("panel.preview", self.obj.Label if not self._closing else ""):
            self._update_preview()

    def _update_preview(self):
        if self._closing:
            return
        if self._recomputing:           # called again from inside a recompute
            self._timer.start()
            return
        self._recomputing = True
        try:
            # Only what changed since the last recompute: a feature's result depends
            # only on its properties and what it links to (and on the rollback bar
            # and EDITING, whose changes touch what they affect), so FreeCAD knows
            # what to rebuild. Touching the feature here rebuilt it on every
            # preview, and opening a panel and pressing OK each rebuilt it once
            # more for nothing.
            if self._stale():
                self.doc.recompute()
        except Exception as e:
            self.show_error("Recompute failed: {}".format(e))
            return
        finally:
            self._recomputing = False
            if self._pending:
                pending, self._pending = self._pending, {}
                QtCore.QTimer.singleShot(0, lambda: self._apply_pending(pending))
        err = self.obj.ErrorMessage
        self.show_error(err)
        self.show_warning(self.obj.WarningMessage)
        self._show_layers(err)
        self.after_preview()
        self.place_drag_handles()
        self._set_ok(not err, err)

    def _stale(self):
        """Whether anything in the document is waiting to be recomputed."""
        for o in self.doc.Objects:
            st = o.State
            if "Touched" in st or "Invalid" in st:
                return True
        return False

    def _show_layers(self, err):
        """Draw the preview layers. On error the last good result stays on screen
        (spec 8.2), so a value being typed doesn't blank it, but the other layers
        (what's picked) follow the panel, and once nothing is picked the result
        goes too: it showed picks that aren't there any more."""
        self._removing = None           # measured afresh for this result
        self._show_picks()
        try:
            layers = self.preview_layers()
        except Exception:
            layers = []
        gone = bool(err) and self.nothing_picked()
        for name, node in layers:
            if name == "result" and err:
                if gone:
                    self.preview.clear(name)
                continue
            self.preview.set(name, node)
        if not err:
            self._cut_view(self.CUT_VIEW and self.removes())
        elif gone:
            self._cut_view(False)

    # ------------------------------------------------------------ picks
    def _pick_shape(self, payload, base):
        """The face, edge or vertex a box's item names, or None (whole objects,
        bodies by ID)."""
        import Part
        try:
            if isinstance(payload, str):
                if base is not None and payload.startswith(("Edge", "Face", "Vertex")):
                    return Part.getShape(base, payload, needSubElement=True)
                return None
            if isinstance(payload, (tuple, list)) and len(payload) == 2 and \
                    all(isinstance(x, str) for x in payload) and payload[1]:
                o = self.doc.getObject(payload[0])
                if o is not None:
                    return Part.getShape(o, payload[1], needSubElement=True)
        except Exception:
            pass
        return None

    def _show_picks(self):
        """What is in the boxes, drawn in the selection blue (edges thick, faces
        tinted) as soon as it is picked, so a pick can be seen in the view."""
        if self.OWN_PICKS or self._closing:
            return
        import Part
        base = getattr(self.obj, "BaseFeature", None)
        shapes = []
        for b in self.visible_boxes():
            for payload, _t in b.items:
                sh = self._pick_shape(payload, base)
                if sh is not None and not sh.isNull():
                    shapes.append(sh)
        try:
            self.preview.set("picked", pv.shape_node(Part.makeCompound(shapes),
                                                     pv.REGION_PICKED, 0.4, line_width=4.0,
                                                     edge_color=pv.REGION_PICKED)
                             if shapes else None)
        except Exception:
            pass

    def changed_faces(self):
        """Of the bodies the feature changed (AddSubShape), the faces it made: what a
        fillet, chamfer or draft preview shows, not the whole body."""
        try:
            base = self.obj.BaseFeature
            return pv.new_faces(self.obj.AddSubShape, base.Shape if base is not None else None)
        except Exception:
            return self.obj.AddSubShape

    def nothing_picked(self):
        """Every pick box showing that needs a pick is empty."""
        need = [b for b in self.visible_boxes() if b.empty is None]
        return bool(need) and not any(b.items for b in need)

    def removes(self):
        """Whether the feature takes material away, so its preview is red (green
        when it adds): what it does to the bodies, measured, not what kind of
        tool it is. A Delete Body, a Common, a pattern of a cut, a face moved in,
        a fillet on an outside edge: the bodies come out smaller. Worked out
        once per preview (see _show_layers)."""
        if self._removing is None:
            self._removing = self.net_change() < 0
        return self._removing

    _removing = None

    def net_change(self):
        """How much the bodies the feature changes grow (+) or shrink (-): their
        volume, or their area when there are only surface bodies. 0 when it
        neither adds nor takes away (a move, a split) or can't be told."""
        try:
            changed = self._changed_bodies()
            if not changed:
                return 0.0
            before = self.obj.Proxy.base_bodies(self.obj)
            was = [before.get(i).shape for i in changed if i in before]
            now = [b for b in changed.values() if b is not None]
            solid = any(x.Solids for x in was + now)

            def amount(shapes):
                return sum(sum(v.Volume for v in x.Solids) if solid else x.Area
                           for x in shapes)
            a, b = amount(now), amount(was)
            if abs(a - b) <= 1e-9 * max(abs(a), abs(b), 1.0):
                return 0.0
            return a - b
        except Exception:
            return 0.0

    # ------------------------------------------------------------ cut view
    _veiled = None

    def _cut_view(self, on):
        """While the preview takes material away, the bodies it changes are drawn as
        they come out (ghosted like the rest), and as they were before it made
        invisible: so the removed material shows only its dashed red edges, not the
        old body's edges inside it. The old bodies stay pickable."""
        if self._veiled is None:
            self._veiled = {}
        changed = self._changed_bodies() if on else {}
        views = {getattr(v, "BodyId", None): v for v in part_mod.body_views(self.part)} \
            if self.part is not None else {}
        hide = {views[i].Name for i in changed if i in views}
        for name in [n for n in self._veiled if n not in hide]:
            self._unveil(name)
        for name in hide:
            if name not in self._veiled:
                self._veil(name)
        after = [b for b in changed.values() if b is not None]
        # The same bodies as last time: keep their mesh (meshing hundreds of
        # changed bodies again on every preview was most of its time).
        memo = getattr(self, "_after_memo", None)
        if memo is not None and len(memo[0]) == len(after) and all(
                topo.same_shape(a, b) for a, b in zip(memo[0], after)):
            node = memo[1]
        else:
            node = pv.body_node(after) if after else None
            self._after_memo = (after, node)
        self.preview.set("after", node)

    def _changed_bodies(self):
        """{body id: its shape after the feature, or None if it's gone} for the
        bodies the feature changes."""
        try:
            from ...core.bodies import BodySet
            shape = self.obj.Shape
            base = self.obj.BaseFeature
            base_shape = base.Shape if base is not None else None
            # Once per result: a preview asks twice (what it removes, the cut view).
            memo = getattr(self, "_changed_memo", None)
            if memo is not None and topo.same_shape(memo[0], shape) and (
                    (memo[1] is None and base_shape is None) or
                    (memo[1] is not None and base_shape is not None and
                     topo.same_shape(memo[1], base_shape))):
                return dict(memo[2])
            before = self.obj.Proxy.base_bodies(self.obj)
            after = BodySet.from_columns(shape, list(self.obj.BodyIds),
                                         list(self.obj.BodyKinds), list(self.obj.BodyFeatures))
        except Exception:
            return {}
        out = {}
        for i in before.ids():
            b = after.get(i)
            # same_shape, not isSame: a moved body (a pattern's) read back from
            # another feature has a new location object, though it is unchanged.
            if b is None or not topo.same_shape(b.shape, before.get(i).shape):
                out[i] = b.shape if b is not None else None
        for i in after.ids():
            if i not in before:
                out[i] = after.get(i).shape
        self._changed_memo = (shape, base_shape, dict(out))
        return out

    def _veil(self, name):
        v = self.doc.getObject(name)
        if v is None:
            return
        vo = v.ViewObject
        try:
            self._veiled[name] = (vo.Transparency, vo.LineMaterial, vo.PointMaterial)
            vo.Transparency = 100
            for prop in ("LineMaterial", "PointMaterial"):
                m = getattr(vo, prop)
                m.Transparency = 1.0
                setattr(vo, prop, m)
        except Exception:
            self._veiled.pop(name, None)

    def _unveil(self, name):
        saved = self._veiled.pop(name, None)
        v = self.doc.getObject(name)
        if saved is None or v is None:
            return
        try:
            vo = v.ViewObject
            vo.Transparency, vo.LineMaterial, vo.PointMaterial = saved
        except Exception:
            pass

    # ------------------------------------------------------------ drag handles
    _drag = None

    def place_drag_handles(self):
        """The feature's draggers (Instant3D), for every feature that has them
        (handles.SPECS): a drag sets the panel's field, typing moves the dragger."""
        if self._closing:
            return
        try:
            from .. import handles as hmod
            specs = hmod.SPECS.get(hmod.spec_key(self.obj))
            if specs is None:
                return
            if self._drag is None:
                if Gui.ActiveDocument is None:
                    return
                self._drag = hmod.FeatureDraggers(
                    self.obj, self.part, specs,
                    on_value=lambda prop, v: hmod.panel_value(self, prop, v))
            self._drag.place()
        except Exception:
            pass

    def draggers(self):
        """The feature's draggers (a FeatureDraggers), placing them if need be."""
        if self._drag is None:
            self.place_drag_handles()
        return self._drag

    def _apply_pending(self, pending):
        for name, value in pending.items():
            self.set_prop(name, value)

    def after_preview(self):
        pass

    def show_error(self, text):
        self.error.set(text)

    def show_warning(self, text):
        self.warning.set(text)

    def _set_ok(self, on, why=""):
        ok, _cancel = task_buttons()
        if ok is not None:
            ok.setEnabled(on)
            ok.setToolTip("" if on else "Can't make the feature yet: " + why)

    def offer_axis(self, sel, active_too=False):
        """Put a temporary axis (its face or edge, ``sel``) in the box that asks for
        an axis, or (``active_too``: the axis was clicked with this panel open)
        the active box. True if a box took it."""
        vis = self.visible_boxes()
        boxes = [b for b in vis if b.what == "axis"]
        if active_too and self.active_box in vis and self.active_box not in boxes:
            boxes.append(self.active_box)
        for b in boxes:
            if any(p[0] == (sel.obj.Name, sel.sub) for p, _t in b.items):
                return True
            res = b.accept_fn(sel)
            if res is not None and not isinstance(res, str):
                b.offer(sel)
                self.activate(b)
                Gui.Selection.clearSelection()
                return True
        return False

    def _take_picked_axis(self):
        """A temporary axis picked before the tool started: its axis box takes it."""
        try:
            from .. import temp_axis
            from ..selection import Sel
            ta = temp_axis.current()
            src = ta.picked() if ta is not None else None
            if src is not None and self.offer_axis(Sel(src[0], src[1])):
                ta.used()
        except Exception:
            pass

    def _after_show(self):
        if self._closing:
            return
        self._take_picked_axis()
        nxt = self.next_box_needing_input()
        if nxt is not None:
            self.activate(nxt)
        elif self.boxes:
            vis = self.visible_boxes()
            if vis:
                self.activate(vis[0])
        self.update_preview()

    def _click_ok(self):
        ok, _c = task_buttons()
        if ok is not None and ok.isEnabled():
            ok.click()

    def _click_cancel(self):
        _o, cancel = task_buttons()
        if cancel is not None:
            cancel.click()

    def enter_pressed(self):
        self._timer.stop()
        self.update_preview()
        self._click_ok()

    # ------------------------------------------------------------ ghosting
    def _ghost(self, on):
        if self.part is None:
            return
        if on:
            for v in part_mod.body_views(self.part):
                try:
                    # Only bodies that change: each write re-sends the body's
                    # materials, which adds up over hundreds of bodies.
                    t = v.ViewObject.Transparency
                    if t < 55:
                        self._ghosted[v.Name] = t
                        v.ViewObject.Transparency = 55
                except Exception:
                    pass
        else:
            for name, t in self._ghosted.items():
                v = self.doc.getObject(name)
                if v is not None:
                    try:
                        v.ViewObject.Transparency = t
                    except Exception:
                        pass
            self._ghosted = {}

    # ------------------------------------------------------------ closing
    def _cleanup(self):
        from ...app import feature as feature_mod
        feature_mod.EDITING.discard(self._obj_name)
        try:
            QtWidgets.QApplication.instance().removeEventFilter(self._delete_guard)
        except Exception:
            pass
        try:
            App.removeDocumentObserver(self._doc_watch)
        except Exception:
            pass
        # FreeCAD's task box deletes its contents from C++, but PySide still counts
        # our widgets as Python's: deleting them there crashed PySide now and then.
        # So the form leaves the task box before FreeCAD closes it, and stays
        # (hidden) with the closed panel for the session.
        _closed.append(self)
        try:
            self.widget.hide()
            self.widget.setParent(None)
        except Exception:
            pass
        self._closing = True
        self._timer.stop()
        for b in self.boxes:
            b.detach()
        try:
            Gui.Selection.removeObserver(self)
        except Exception:
            pass
        self.preview.clear()
        self.preview.detach()
        if self._drag is not None:
            try:
                self._drag.stop()
            except Exception:
                pass
            self._drag = None
        try:
            for name in list(self._veiled or {}):
                self._unveil(name)
            self._ghost(False)
        except Exception:       # the document is being closed
            pass
        try:
            self.on_close()
        except Exception:
            pass

    def document_closing(self):
        """The panel's document is being closed: close the panel, touching
        nothing in the document."""
        if self._closing:
            return
        self._ghosted = {}
        self._veiled = {}
        self._cleanup()
        QtCore.QTimer.singleShot(0, _close_dialog)

    def on_close(self):
        pass

    def accept(self):
        from ...app import perf
        with perf.span("panel.ok", self.obj.Label if not self._closing else ""):
            return self._accept_panel()

    def _accept_panel(self):
        if self._closing:
            return True
        self._timer.stop()
        self.update_preview()
        if self.obj.ErrorMessage:
            self.show_error(self.obj.ErrorMessage)
            return False
        self._cleanup()
        # OK in the feature's own panel: its repaired references have been seen.
        try:
            from ...app import refs as refs_mod
            if refs_mod.repairs(self.obj):
                refs_mod.accept_repairs(self.obj)
                self.obj.touch()
        except Exception:
            pass
        if self._old_tip is not None and self.part is not None:
            part_mod.roll_to(self.part, self._old_tip)
        self.doc.recompute()
        self.doc.commitTransaction()
        if self._before is not None:        # "." repeats it
            from .. import command_line
            command_line.remember_panel(self.obj, self._before)
        self._close_edit()
        return True

    def reject(self):
        if self._closing:
            return True
        self._cleanup()
        self.doc.abortTransaction()
        self.doc.recompute()
        self._close_edit()
        return True

    def _close_edit(self):
        # resetEdit closes the dialog it opened; closing it again here as well
        # deletes the panel twice and crashes Qt.
        gdoc = Gui.getDocument(self.doc.Name)
        if gdoc is not None and gdoc.getInEdit() is not None:
            gdoc.resetEdit()
        elif Gui.Control.activeDialog():
            QtCore.QTimer.singleShot(0, Gui.Control.closeDialog)

    def getStandardButtons(self):
        b = QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        return b.value if hasattr(b, "value") else int(b)

    def isAllowedAlterSelection(self):
        return True

    def isAllowedAlterView(self):
        return True

    def isAllowedAlterDocument(self):
        return False
