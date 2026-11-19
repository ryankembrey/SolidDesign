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
                                    "turning about its own lines.")
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
        self.sec_plane.setVisible(not parting)
        self.sec_faces.setVisible(not parting)
        self.sec_pull.setVisible(parting)
        self.sec_lines.setVisible(parting)
        # With All, Inner or Outer faces no pick is needed.
        auto = self.obj.FacePropagation in (core.ALL, core.INNER, core.OUTER)
        self.faces.set_placeholder(empty="Found by Face propagation" if auto else "")

    def preview_layers(self):
        layers = [("result", pv.result_node(self.obj.AddSubShape, True))]
        picks = []
        base = self.obj.BaseFeature
        box = self.faces if self.kind.currentText() == core.NEUTRAL_PLANE else self.lines
        for s in box.payloads():
            try:
                picks.append(Part.getShape(base, s, needSubElement=True))
            except Exception:
                pass
        layers.append(("picks", pv.shape_node(Part.makeCompound(picks), pv.REGION_PICKED, 0.0,
                                              line_width=4.0) if picks else None))
        return layers
