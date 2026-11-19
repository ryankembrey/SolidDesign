# SPDX-License-Identifier: LGPL-2.1-or-later
"""Revolve's panel: SolidWorks' Revolve PropertyManager on the shared
sketch-feature panel."""

from ..app import refs, util
from ..core import refgeom as core_ref
from ..core.features import revolve as core
from . import selection as selmod
from .sketch_panel import SketchFeaturePanel

__all__ = ["RevolvePanel"]


def _ref_text(o, sub):
    if o.TypeId.startswith("Sketcher::") and sub.startswith("Axis"):
        return "{} centerline {}".format(o.Label, sub[4:])
    if sub in ("H_Axis", "V_Axis"):
        return "{} {} axis".format(o.Label, "horizontal" if sub == "H_Axis" else "vertical")
    return u"{} \u00b7 {}".format(sub, o.Label) if sub else o.Label


def _is_line(edge):
    try:
        return edge.ShapeType == "Edge" and edge.Curve.TypeId in ("Part::GeomLine",
                                                                  "Part::GeomLineSegment")
    except Exception:
        return False


class RevolveDirection(object):
    """The rows of Direction 1 or Direction 2."""

    def __init__(self, panel, group, n):
        self.p = panel
        self.g = group
        self.n = n
        other = " the other way" if n else ""
        self.cond, _r = panel.choice(
            group, "EndCondition" + n, "End condition",
            "How far the revolve turns: an angle, up to a face or vertex, or both ways "
            "from the sketch (Mid Plane)" + other,
            flip=None if n else "Reverse", flip_tip="Revolve the other way round the axis")
        self.flip = getattr(self.cond, "flip", None)
        self.angle, self.r_angle = panel.qty(group, "Angle" + n, "Angle",
                                             "How far the sketch turns" + other, unit="deg",
                                             maximum=360.0, step=5.0)
        self.face = panel.field(group, "Face", "UpToFace" + n, "face", "Click a face or plane",
                                self._accept_face, "The face or plane the revolve ends at")
        self.vertex = panel.field(group, "Vertex", "UpToVertex" + n, "vertex",
                                  "Click a vertex or point", self._accept_vertex,
                                  "The vertex or point the revolve ends at")
        self.offset, self.r_offset = panel.qty(
            group, "Offset" + n, "Offset", "Distance from the face to the end of the revolve",
            flip="ReverseOffset" + n, flip_tip="Measure the offset the other way")
        self.face.changed.connect(lambda: panel._set_link("UpToFace" + n, self.face))
        self.vertex.changed.connect(lambda: panel._set_link("UpToVertex" + n, self.vertex))

    def _accept_face(self, sel):
        return self.p._accept_ref(sel, "face")

    def _accept_vertex(self, sel):
        return self.p._accept_ref(sel, "vertex")

    def load(self):
        obj = self.p.obj
        for prop, box in (("UpToFace" + self.n, self.face), ("UpToVertex" + self.n, self.vertex)):
            v = getattr(obj, prop)
            if v and v[0] is not None:
                sub = v[1][0] if v[1] else ""
                box.set_items([((v[0].Name, sub), _ref_text(v[0], sub))])

    def refresh(self):
        c = self.cond.currentText()
        self.r_angle.set_visible(c in (core.BLIND, core.MID_PLANE))
        self.face.row.set_visible(c in (core.UP_TO_SURFACE, core.OFFSET_FROM_SURFACE))
        self.vertex.row.set_visible(c == core.UP_TO_VERTEX)
        self.r_offset.set_visible(c == core.OFFSET_FROM_SURFACE)


class RevolvePanel(SketchFeaturePanel):
    TITLE = "Revolve"
    ICONS = ("RevolveAdd", "RevolveCut")

    def build_parameters(self, L):
        self.sec_axis = self.group("Axis of Revolution")
        self.axis_box = self.field(
            self.sec_axis, "Axis", "Axis", "axis", "Click a line or axis", self._accept_axis,
            "The axis the sketch turns about: a centerline or line of the sketch, an axis, "
            "a straight edge, or a round face or circular edge (its axis)")
        self.axis_box.changed.connect(lambda: self._set_link("Axis", self.axis_box))

        self.sec_d1 = self.group("Direction 1")
        self.d1 = RevolveDirection(self, self.sec_d1, "")
        self.add_body_rows(self.sec_d1)

        self.sec_d2 = self.group("Direction 2", "Revolve the other way from the sketch too",
                                 checkable=True, prop="Direction2")
        self.d2 = RevolveDirection(self, self.sec_d2, "2")

    # ------------------------------------------------------------ drag handles
    def _handles(self):
        if getattr(self, "_h", None) is None:
            from .handles import Handles, RingHandle
            self._handle_set = Handles()
            self._h = (self._handle_set.add(RingHandle(lambda v: self._dragged(self.d1, v))),
                       self._handle_set.add(RingHandle(lambda v: self._dragged(self.d2, v))))
            self._handle_set.listen()
        return self._h

    def _dragged(self, widgets, v):
        widgets.angle.spin.setProperty("rawValue", float(v))

    def place_handles(self):
        """Rings round the axis, one per direction with an angle (Instant3D)."""
        if self._closing:
            return
        from .handles import revolve_specs
        r1, r2 = self._handles()
        shown = set()
        for prop, centre, axis, ref, radius, value in revolve_specs(self.obj, self.part):
            r = r1 if prop == "Angle" else r2
            r.place(centre, axis, ref, radius, value)
            r.attach()
            shown.add(prop)
        if "Angle" not in shown:
            r1.detach()
        if "Angle2" not in shown:
            r2.detach()

    def on_close(self):
        if getattr(self, "_handle_set", None) is not None:
            self._handle_set.stop()
        super(RevolvePanel, self).on_close()

    def _accept_axis(self, sel):
        o = sel.obj
        if o is self.obj:
            return "A feature can't use its own edges."
        if o.TypeId in ("Part::DatumLine", "App::Line") or (
                util.role(o) == "refgeom" and o.Proxy.KIND == "axis"):
            return (o.Name, ""), _ref_text(o, "")
        if o.TypeId.startswith("Sketcher::") and sel.elem_kind() == "Edge":
            e = sel.element()
            if e is None or not _is_line(e):
                return "The axis must be a straight line."
            return (o.Name, sel.sub), _ref_text(o, sel.sub)
        if util.is_body_view(o) and sel.elem_kind() in ("Edge", "Face"):
            e = sel.element()
            kind = sel.elem_kind()
            if e is None or not (_is_line(e) or core_ref.axis_of_element(e) is not None):
                return "The axis must be a straight edge, or a round face or circular edge " \
                    "(its axis)."
            r = selmod._from_body(sel, self.obj.BaseFeature, kind)
            if r is None or isinstance(r, str):
                return r
            text = self.ref_text(r[0], r[1])
            return (r[0].Name, r[1]), text if _is_line(e) else u"axis of " + text
        return None

    def load_parameters(self):
        v = self.obj.Axis
        if v and v[0] is not None:
            sub = v[1][0] if v[1] else ""
            self.axis_box.set_items([((v[0].Name, sub), _ref_text(v[0], sub))])
        self.d1.load()
        self.d2.load()

    def _set_link(self, prop, box):
        if prop != "Axis":
            return super(RevolvePanel, self)._set_link(prop, box)
        p = box.payloads()
        if p:
            o = self.doc.getObject(p[0][0])
            sub = p[0][1]
            if o.TypeId.startswith("Sketcher::") and (sub.startswith("Axis") or
                                                      sub in ("H_Axis", "V_Axis")):
                self.obj.Axis = (o, [sub])
            else:
                refs.set_ref(self.obj, "Axis", o, sub)
        else:
            refs.set_ref(self.obj, "Axis", None)
        self.changed()

    def _sketch_changed(self):
        super(RevolvePanel, self)._sketch_changed()
        # A new sketch with one centerline: use it, as SolidWorks does.
        from ..app.revolve import default_axis
        sk = self.obj.Sketch
        ax = default_axis(sk)
        if ax and not self.axis_box.items:
            self.obj.Axis = (sk, [ax])
            self.load_parameters()

    def refresh_parameters(self):
        self.place_handles()
        self.d1.refresh()
        self.d2.refresh()
        self.sec_d2.setVisible(self.obj.EndCondition != core.MID_PLANE)
