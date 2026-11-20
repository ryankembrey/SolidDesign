# SPDX-License-Identifier: LGPL-2.1-or-later
"""Draft panel (SolidWorks' manual Draft PropertyManager).

While it is open the model shows the bodies before the draft, so every face can
still be picked; the drafted bodies are the preview.
"""

import Part

from ..app import refs, util
from ..core.features import draft as core
from . import preview as pv
from . import selection as selmod
from .panel import parts
from .tool_panels import ToolPanel

__all__ = ["DraftPanel"]


def _planar(shape):
    faces = [shape] if shape.ShapeType == "Face" else shape.Faces
    if len(faces) != 1 or faces[0].Surface.TypeId != "Part::GeomPlane":
        return "Pick a plane or a planar face."
    return None


def _direction(shape):
    """A direction of pull: a straight edge, an axis, a round face, or a plane."""
    if shape.ShapeType == "Face" or (shape.Faces and not shape.Edges[1:]):
        f = shape if shape.ShapeType == "Face" else shape.Faces[0]
        if f.Surface.TypeId in ("Part::GeomPlane", "Part::GeomCylinder", "Part::GeomCone"):
            return None
        return "Pick a plane, a planar or round face, or a straight edge."
    edges = [shape] if shape.ShapeType == "Edge" else shape.Edges
    if len(edges) == 1 and (edges[0].Curve.TypeId in ("Part::GeomLine", "Part::GeomLineSegment")
                            or hasattr(edges[0].Curve, "Axis")):
        return None
    return "Pick a plane, a planar or round face, or a straight edge."


class DraftPanel(ToolPanel):
    TITLE = "Draft"

    def build(self):
        obj = self.obj
        g = self.group("Type of Draft")
        self.kind, _r = self.choice(g, "DraftType", None,
                                    "Neutral Plane: faces turn about where they meet a plane. "
                                    "Parting Line: faces turn about the edges you pick. Step "
                                    "Draft: parting lines at several heights, each step "
                                    "turning about its own lines. DraftXpert: a neutral plane; "
                                    "the faces that need draft are found for you, and faces "
                                    "that can't be drafted are left out and listed.")
        g = self.group("Draft Angle")
        self.angle, _r = self.qty(g, "Angle", "Angle",
                                  "How far the faces lean. The part gets narrower along the "
                                  "direction of pull.", unit="deg", minimum=0.0,
                                  maximum=core.MAX_ANGLE, step=0.5, flip="ReverseDirection",
                                  flip_tip="Reverse the direction of pull")
        # Neutral Plane
        g = self.sec_plane = self.group("Neutral Plane")
        self.plane = self.ref_box(g, "NeutralPlane", "Plane", "plane",
                                  "Click a plane or planar face",
                                  "The faces turn about where they meet this plane. Its normal is "
                                  "the direction of pull, pointing away from it into the faces.",
                                  ("Face",), check=_planar)
        # Parting Line
        g = self.sec_pull = self.group("Direction of Pull")
        self.pull = self.ref_box(g, "PullDirection", "Direction", "direction",
                                 "Click an edge, axis or face",
                                 "The direction the mould opens: a straight edge, an axis, or a "
                                 "face (its normal). Empty: normal to the parting lines.",
                                 ("Face", "Edge"), check=_direction,
                                 empty="Normal to lines")
        g = self.sec_lines = self.group("Parting Lines")
        self.lines = self._items_box(g, "PartingLines", "Edge", "edges", "Click edges",
                                     "The edges the faces turn about: in one plane, or (Step "
                                     "Draft) square to the pull at several heights. Click an "
                                     "edge again to take it out.")
        self.other, _r = self.check(g, "OtherFace", "Other face",
                                    "Draft the faces on the other side of the parting lines")
        # Faces
        g = self.sec_faces = self.group("Faces to Draft")
        self.faces = self._items_box(g, "Items", "Face", "faces", "Click faces",
                                     "The faces to lean. Click a face again to take it out.")
        self.prop = parts.combo(core.PROPAGATION, obj.FacePropagation,
                                "Faces added to the ones you picked")
        self.prop.currentTextChanged.connect(self._propagation)
        self.prop_row = g.row("Face propagation", self.prop,
                              "Along Tangent: faces meeting the picks smoothly. All Faces: every "
                              "face parallel to the direction of pull. Inner Faces: the walls of "
                              "holes and pockets. Outer Faces: the outside walls.")
        # Parting lines share the propagation (None or Along Tangent).
        self.prop2 = parts.combo(core.PROPAGATION_PARTING,
                                 obj.FacePropagation if obj.FacePropagation in
                                 core.PROPAGATION_PARTING else core.NONE,
                                 "Faces added to the ones next to the parting lines")
        self.prop2.currentTextChanged.connect(self._propagation)
        self.prop2_row = self.sec_lines.row("Face propagation", self.prop2,
                                            "Along Tangent: also the faces meeting them "
                                            "smoothly")
        # DraftXpert: what the faces have now.
        g = self.sec_analysis = self.group("Draft Analysis",
                                           "How much draft the faces have now, for this "
                                           "angle and direction of pull")
        from PySide import QtWidgets
        self.analysis = QtWidgets.QLabel("")
        self.analysis.setWordWrap(True)
        g.wide(self.analysis, "Faces with enough draft towards the pull (positive), away "
                              "from it (negative), too little (need draft), or some of each "
                              "(straddle)")
        self.add_needed = QtWidgets.QPushButton("Pick the Faces That Need Draft")
        self.add_needed.setToolTip("Put every face with too little draft in Faces to Draft")
        self.add_needed.clicked.connect(self._pick_needed)
        g.wide(self.add_needed)

    def _xpert_state(self):
        """(base BodySet, pull) for the analysis, or None."""
        from ..core import refgeom as core_ref
        obj = self.obj
        try:
            base = obj.Proxy.base_bodies(obj)
            p = core.Params()
            s, _w = refs.get_ref(obj, "NeutralPlane", "neutral plane", obj.BaseFeature)
            if s is None:
                return None
            pt, n, _x = core_ref.plane_of(s, "neutral plane")
            p.plane = (pt, n)
            p.reverse = obj.ReverseDirection
            p.faces, _w = refs.get_refs(obj, "Items", "face", obj.BaseFeature)
            return base, core.xpert_pull(p, base)[2]
        except Exception:
            return None

    def _show_analysis(self):
        st = self._xpert_state()
        if st is None:
            self.analysis.setText("Pick the neutral plane to see the faces' draft.")
            self.add_needed.setEnabled(False)
            return
        base, pull = st
        counts = {core.POSITIVE: 0, core.NEGATIVE: 0, core.NEEDS: 0, core.STRADDLE: 0}
        for b in base:
            if b.kind != "solid":
                continue
            for k, v in core.analysis(b.shape, pull, self.obj.Angle.Value).items():
                counts[k] += len(v)
        self.analysis.setText(u"{} positive \u00b7 {} negative \u00b7 {} need draft \u00b7 "
                              u"{} straddle".format(counts[core.POSITIVE],
                                                    counts[core.NEGATIVE],
                                                    counts[core.NEEDS],
                                                    counts[core.STRADDLE]))
        self.add_needed.setEnabled(counts[core.NEEDS] > 0)

    def _pick_needed(self):
        st = self._xpert_state()
        base_obj = self.obj.BaseFeature
        if st is None or base_obj is None:
            return
        base, pull = st
        whole = base_obj.Shape.Faces
        subs = list(self.faces.payloads())
        for b in base:
            if b.kind != "solid":
                continue
            for i in core.analysis(b.shape, pull, self.obj.Angle.Value)[core.NEEDS]:
                f = b.shape.Faces[i - 1]
                j = next((k for k, g in enumerate(whole, 1) if g.isSame(f) or
                          (abs(g.Area - f.Area) < 1e-9 and
                           g.CenterOfMass.distanceToPoint(f.CenterOfMass) < 1e-9)), None)
                if j is not None and "Face%d" % j not in subs:
                    subs.append("Face%d" % j)
        refs.set_ref(self.obj, "Items", base_obj if subs else None, subs)
        self.faces.set_items([(sub, self.ref_text(base_obj, sub)) for sub in subs])
        self.changed()

    def _items_box(self, group, prop, kind, what, hint, tip, empty=None):
        def accept(sel):
            k = sel.elem_kind()
            if not util.is_body_view(sel.obj) and not util.is_feature(sel.obj):
                return None
            if k != kind:
                return "Pick {} here.".format(what) if k else None
            if sel.obj is self.obj:
                return "Pick on the model before this feature."
            r = selmod._from_body(sel, self.obj.BaseFeature, kind)
            if r is None and sel.obj is self.obj.BaseFeature:
                r = (sel.obj, sel.sub)
            if r is None or isinstance(r, str):
                return r or "Pick on the model before this feature."
            return r[1], self.ref_text(r[0], r[1])
        box = self.list(group, prop, what, hint, accept, tip, empty)

        def store():
            subs = list(box.payloads())
            refs.set_ref(self.obj, prop, self.obj.BaseFeature if subs else None, subs)
            self.changed()
        box.changed.connect(store)

        def load():
            v = getattr(self.obj, prop)
            if v and v[0] is not None:
                box.set_items([(sub, self.ref_text(v[0], sub)) for sub in v[1]])
        self._loaders.append(load)
        return box

    def _propagation(self, text):
        self.set_prop("FacePropagation", text)

    def refresh(self):
        parting = self.kind.currentText() in (core.PARTING_LINE, core.STEP_DRAFT)
        xpert = self.kind.currentText() == core.DRAFTXPERT
        self.sec_plane.setVisible(not parting)
        self.sec_faces.setVisible(not parting)
        self.sec_analysis.setVisible(xpert)
        self.prop_row.set_visible(not xpert)
        if xpert:
            self._show_analysis()
            self.faces.set_placeholder(empty="The faces that need draft")
            return
        self.sec_pull.setVisible(parting)
        self.sec_lines.setVisible(parting)
        # With All, Inner or Outer faces no pick is needed.
        auto = self.obj.FacePropagation in (core.ALL, core.INNER, core.OUTER)
        self.faces.set_placeholder(empty="Found by Face propagation" if auto else "")

    def preview_layers(self):
        layers = [("result", pv.result_node(self.obj.AddSubShape, True))]
        picks = []
        base = self.obj.BaseFeature
        box = self.faces if self.kind.currentText() in (core.NEUTRAL_PLANE, core.DRAFTXPERT) \
            else self.lines
        for s in box.payloads():
            try:
                picks.append(Part.getShape(base, s, needSubElement=True))
            except Exception:
                pass
        layers.append(("picks", pv.shape_node(Part.makeCompound(picks), pv.REGION_PICKED, 0.0,
                                              line_width=4.0) if picks else None))
        return layers
