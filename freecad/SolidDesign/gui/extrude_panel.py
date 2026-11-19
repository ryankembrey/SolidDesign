# SPDX-License-Identifier: LGPL-2.1-or-later
"""Extrude's panel: SolidWorks' Extrude PropertyManager, on the shared
sketch-feature panel (gui/sketch_panel.py)."""

from ..app import part as part_mod
from ..app import refs
from ..core.features import extrude as core
from . import selection as selmod
from .panel import parts
from .sketch_panel import LAST, SketchFeaturePanel
from .tool_panels import ToolPanel

__all__ = ["ExtrudePanel", "DirectionWidgets", "LAST"]

END_TIP = ("How far the extrusion goes: a depth, through everything, up to a face, "
           "vertex or body, or both ways from the sketch (Mid Plane)")


class DirectionWidgets(object):
    """The rows of Direction 1 or Direction 2."""

    def __init__(self, panel, group, n):
        self.p = panel
        self.g = group
        self.n = n
        obj = panel.obj
        other = " the other way" if n else ""
        self.cond, _r = panel.choice(
            group, "EndCondition" + n, "End condition", END_TIP + other,
            flip=None if n else "Reverse", flip_tip="Reverse the direction of the extrusion")
        self.flip = getattr(self.cond, "flip", None)
        self.depth, self.r_depth = panel.qty(group, "Depth" + n, "Depth",
                                             "Distance from the sketch to the end" + other)
        self.face = panel.field(group, "Face", "UpToFace" + n, "face", "Click a face or plane",
                                self._accept_face, "The face or plane the extrusion ends at")
        self.vertex = panel.field(group, "Vertex", "UpToVertex" + n, "vertex",
                                  "Click a vertex or point", self._accept_vertex,
                                  "The vertex or point the extrusion ends at")
        self.body = panel.field(group, "Body", "UpToBody" + n, "body", "Click a body",
                                self._accept_body, "The body the extrusion ends at")
        self.offset, self.r_offset = panel.qty(
            group, "Offset" + n, "Offset", "Distance from the face to the end of the extrusion",
            flip="ReverseOffset" + n, flip_tip="Measure the offset the other way")
        # Draft: a check box turning the angle on, and which way it tapers.
        self.draft_angle = parts.QuantityField(obj, "DraftAngle" + n, unit="deg", maximum=89.0,
                                               step=0.5)
        self.r_draft = group.check_row("Draft", self.draft_angle,
                                       "Taper the side faces by this angle",
                                       checked=getattr(obj, "Draft" + n))
        self.draft_on = self.r_draft.check
        self.outward, self.r_outward = panel.check(
            group, "DraftOutward" + n, "Draft outward",
            "Taper outwards, so the far end is bigger; off: it is smaller")
        # wiring
        self.draft_on.toggled.connect(lambda on: panel.set_prop("Draft" + n, on))
        self.draft_angle.changed.connect(lambda v: panel.set_prop("DraftAngle" + n, v))
        self.draft_angle.connect_return(panel.enter_pressed)
        self.face.changed.connect(self._face_changed)
        self.vertex.changed.connect(self._vertex_changed)
        self.body.changed.connect(self._body_changed)

    # picks -------------------------------------------------------------
    def _accept_face(self, sel):
        r = selmod.face_ref(sel, self.p.obj.BaseFeature, self.p.obj)
        if r is None or isinstance(r, str):
            return r
        return (r[0].Name, r[1]), self.p.ref_text(*r)

    def _accept_vertex(self, sel):
        r = selmod.vertex_ref(sel, self.p.obj.BaseFeature, self.p.obj)
        if r is None or isinstance(r, str):
            return r
        return (r[0].Name, r[1]), self.p.ref_text(*r)

    def _accept_body(self, sel):
        r = selmod.body_ref(sel, self.p.base_ids())
        if r is None or isinstance(r, str):
            return r
        return r[0], self.p.body_label(r[0])

    def _set_link(self, prop, box):
        p = box.payloads()
        if p:
            refs.set_ref(self.p.obj, prop, self.p.doc.getObject(p[0][0]), p[0][1])
        else:
            refs.set_ref(self.p.obj, prop, None)
        self.p.changed()

    def _face_changed(self):
        self._set_link("UpToFace" + self.n, self.face)

    def _vertex_changed(self):
        self._set_link("UpToVertex" + self.n, self.vertex)

    def _body_changed(self):
        p = self.body.payloads()
        self.p.set_prop("UpToBody" + self.n, p[0] if p else "")

    # state -------------------------------------------------------------
    def load(self):
        obj = self.p.obj
        n = self.n
        for prop, box in (("UpToFace" + n, self.face), ("UpToVertex" + n, self.vertex)):
            v = getattr(obj, prop)
            if v and v[0] is not None:
                sub = v[1][0] if v[1] else ""
                box.set_items([((v[0].Name, sub), self.p.ref_text(v[0], sub))])
        bid = getattr(obj, "UpToBody" + n)
        if bid:
            label = bid
            for v in part_mod.body_views(self.p.part) if self.p.part else []:
                if v.BodyId == bid:
                    label = part_mod.clean_label(v.Label)
            self.body.set_items([(bid, label)])

    def refresh(self):
        c = self.cond.currentText()
        self.r_depth.set_visible(c in (core.BLIND, core.MID_PLANE))
        self.face.row.set_visible(c in (core.UP_TO_SURFACE, core.OFFSET_FROM_SURFACE))
        self.vertex.row.set_visible(c == core.UP_TO_VERTEX)
        self.body.row.set_visible(c == core.UP_TO_BODY)
        self.r_offset.set_visible(c == core.OFFSET_FROM_SURFACE)
        self.r_outward.set_visible(self.draft_on.isChecked())


class ExtrudePanel(SketchFeaturePanel):
    TITLE = "Extrude"
    ICONS = ("ExtrudeAdd", "ExtrudeCut", "ExtrudeSurface")
    ref_box = ToolPanel.ref_box

    def build_parameters(self, L):
        # From ---------------------------------------------------------
        g = self.sec_from = self.group("From", "Where the extrusion starts")
        self.from_kind, _r = self.choice(
            g, "From", "Start", "Where the extrusion starts: the sketch plane, a face or "
            "plane, a vertex, or an offset from the sketch plane")
        self.from_face = self.field(g, "Face", "FromFace", "face", "Click a face or plane",
                                    lambda s: self._accept_ref(s, "face"),
                                    "The face or plane the extrusion starts from")
        self.from_vertex = self.field(g, "Vertex", "FromVertex", "vertex",
                                      "Click a vertex or point",
                                      lambda s: self._accept_ref(s, "vertex"),
                                      "The vertex or point the extrusion starts from")
        self.from_offset, self.r_from_offset = self.qty(
            g, "FromOffset", "Offset", "Distance from the sketch plane to the start",
            flip="FromReverse", flip_tip="Offset the start the other way")
        self.from_face.changed.connect(lambda: self._set_link("FromFace", self.from_face))
        self.from_vertex.changed.connect(lambda: self._set_link("FromVertex", self.from_vertex))

        # Direction 1 --------------------------------------------------
        self.sec_d1 = self.group("Direction 1")
        self.d1 = DirectionWidgets(self, self.sec_d1, "")
        self.dir_vec = self.ref_box(
            self.sec_d1, "DirectionOfExtrusion", "Direction", "direction",
            "Click an edge or plane", "Extrude along an edge or axis, or a plane's normal, "
            "instead of square to the sketch (none: square to it)", ("Edge", "Face"),
            empty="Normal to sketch")
        self.add_body_rows(self.sec_d1)
        self.cap_end, self.r_cap_end = self.check(
            self.sec_d1, "CapEnd", "Cap end",
            "Close both ends of a closed profile, so the surface is closed")

        # Direction 2 --------------------------------------------------
        self.sec_d2 = self.group("Direction 2", "Extrude the other way from the sketch too",
                                 checkable=True, prop="Direction2")
        self.d2 = DirectionWidgets(self, self.sec_d2, "2")
        # A new cut goes into the material: see after_preview.
        self._dir_state = "untried"         # untried | flipped | done
        self.d1.flip.toggled.connect(self._direction_chosen)

    def _direction_chosen(self, _on):
        if not self._flipping:
            self._dir_state = "done"        # the user chose: leave it alone

    _flipping = False

    def _flip_direction(self):
        self._flipping = True
        try:
            self.d1.flip.setChecked(not self.obj.Reverse)   # sets Reverse
        finally:
            self._flipping = False

    def after_preview(self):
        """A new cut that misses every body but would cut the other way is
        flipped, so a sketch on a face cuts into the material (SolidWorks does
        that); if the other way misses too, it goes back."""
        super(ExtrudePanel, self).after_preview()
        obj = self.obj
        misses = "doesn't touch any body" in (obj.ErrorMessage or "")
        if not self.is_new or obj.Mode != "Cut" or self._dir_state == "done":
            return
        if self._dir_state == "untried" and misses:
            self._dir_state = "flipped"
            self._flip_direction()
        elif self._dir_state == "flipped":
            if misses:
                self._flip_direction()
            self._dir_state = "done"

    def _mode_changed(self, mode):
        if mode == "Cut" and self._dir_state != "done":
            self._dir_state = "untried"
        super(ExtrudePanel, self)._mode_changed(mode)

    def load_parameters(self):
        obj = self.obj
        for prop, box in (("FromFace", self.from_face), ("FromVertex", self.from_vertex)):
            v = getattr(obj, prop)
            if v and v[0] is not None:
                sub = v[1][0] if v[1] else ""
                box.set_items([((v[0].Name, sub), self.ref_text(v[0], sub))])
        self.d1.load()
        self.d2.load()

    # ------------------------------------------------------------ drag handles
    def _handles(self):
        if getattr(self, "_h", None) is None:
            from .handles import DragArrow, Handles
            self._handle_set = Handles()
            self._h = (self._handle_set.add(DragArrow(lambda v: self._dragged(self.d1, v))),
                       self._handle_set.add(DragArrow(lambda v: self._dragged(self.d2, v))))
            self._handle_set.listen()
        return self._h

    def _dragged(self, widgets, v):
        widgets.depth.spin.setProperty("rawValue", float(v))

    def place_handles(self):
        """Arrows on the sketch, along each direction with a depth (Instant3D)."""
        if self._closing:
            return
        from .handles import extrude_specs
        h1, h2 = self._handles()
        shown = {}
        for prop, origin, d, value, factor, scale in extrude_specs(self.obj, self.part):
            h = h1 if prop == "Depth" else h2
            h.factor = factor
            h.place(origin, d, value, scale)
            h.attach()
            shown[prop] = True
        if "Depth" not in shown:
            h1.detach()
        if "Depth2" not in shown:
            h2.detach()

    def on_close(self):
        if getattr(self, "_handle_set", None) is not None:
            self._handle_set.stop()
        super(ExtrudePanel, self).on_close()

    def refresh_parameters(self):
        obj = self.obj
        self.r_cap_end.set_visible(obj.Mode == "Surface")
        self.place_handles()
        self.d1.refresh()
        self.d2.refresh()
        self.sec_d2.setVisible(obj.EndCondition not in (core.MID_PLANE, core.THROUGH_ALL_BOTH))
        k = self.from_kind.currentText()
        self.from_face.row.set_visible(k == core.FROM_SURFACE)
        self.from_vertex.row.set_visible(k == core.FROM_VERTEX)
        self.r_from_offset.set_visible(k == core.FROM_OFFSET)
