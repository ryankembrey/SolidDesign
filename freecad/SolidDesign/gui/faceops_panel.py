# SPDX-License-Identifier: LGPL-2.1-or-later
"""Offset Surface and Move Face panels."""

from PySide import QtWidgets

from ..app import refs, util
from ..core.features import faceops as core
from . import preview as pv
from . import selection as selmod
from .tool_panels import ToolPanel

__all__ = ["OffsetSurfacePanel", "MoveFacePanel"]


class _FacesPanel(ToolPanel):
    def faces_box(self, group, tip):
        def accept(sel):
            k = sel.elem_kind()
            if not util.is_body_view(sel.obj):
                return None
            if k != "Face":
                return "Pick faces here." if k else None
            r = selmod._from_body(sel, self.obj.BaseFeature, "Face")
            if r is None or isinstance(r, str):
                return r
            return r[1], self.ref_text(r[0], r[1])
        box = self.list(group, "Items", "faces", "Click faces", accept, tip)

        def store():
            subs = list(box.payloads())
            refs.set_ref(self.obj, "Items", self.obj.BaseFeature if subs else None, subs)
            self.changed()
        box.changed.connect(store)

        def load():
            v = self.obj.Items
            if v and v[0] is not None:
                box.set_items([(sub, self.ref_text(v[0], sub)) for sub in v[1]])
        self._loaders.append(load)
        return box


class OffsetSurfacePanel(_FacesPanel):
    TITLE = "Offset Surface"
    ICON_NAME = "OffsetSurface"

    def build(self):
        g = self.group("Offset Parameters")
        self.faces = self.faces_box(g, "The faces or surfaces to offset into a new surface "
                                       "body. Click a face again to take it out.")
        self.dist, _r = self.qty(g, "Distance", "Distance",
                                 "How far to offset them (0: a copy of the faces)",
                                 minimum=-1e9, step=0.5, flip="Flip",
                                 flip_tip="Offset to the other side")


class MoveFacePanel(_FacesPanel):
    TITLE = "Move Face"
    ICON_NAME = "MoveFace"

    def build(self):
        g = self.group("Move Face")
        self.kind, _r = self.choice(g, "MoveType", "Type",
                                    "Offset: along the faces' normals. Translate: along a "
                                    "direction. Rotate: about an axis. The faces around them "
                                    "extend or trim to follow.")
        self.faces = self.faces_box(g, "The faces to move. Click a face again to take it out.")
        g = self.sec_params = self.group("Parameters")
        self.dist, self.r_dist = self.qty(g, "Distance", "Distance", "How far to move the faces",
                                          step=0.5, flip="Flip",
                                          flip_tip="Move them the other way")
        self.direction = self.ref_box(g, "Direction", "Direction", "direction",
                                      "Click an edge, axis or face",
                                      "The direction to move along: a straight edge, an axis, "
                                      "or a face (its normal)", ("Edge", "Face"))
        self.axis = self.ref_box(g, "Axis", "Axis", "axis", "Click an edge or axis",
                                 "The axis to turn the faces about; parallel to them",
                                 ("Edge",))
        self.angle, self.r_angle = self.qty(g, "Angle", "Angle", "How far to turn the faces",
                                            unit="deg", minimum=-89.0, maximum=89.0, step=1.0)

    def refresh(self):
        t = self.kind.currentText()
        self.direction.row.set_visible(t == core.TRANSLATE)
        self.axis.row.set_visible(t == core.ROTATE)
        self.r_angle.set_visible(t == core.ROTATE)
        self.r_dist.set_visible(t != core.ROTATE)

    def preview_layers(self):
        return [("result", pv.result_node(self.obj.AddSubShape, not self.removes()))]


class SplitLinePanel(_FacesPanel):
    TITLE = "Split Line"
    ICON_NAME = "SplitLine"
    PREVIEW_ADDS = True

    def build(self):
        from ..core.features import splitline as core_split
        self.core = core_split
        g = self.group("Type of Split")
        self.kind, _r = self.choice(g, "SplitType", None,
                                    "Silhouette: the outline of round faces seen along a "
                                    "direction. Projection: a sketch projected onto the faces. "
                                    "Intersection: where planes or faces cut them.")
        g = self.group("Selections")

        def accept_sketch(sel):
            sk = selmod.sketch_ref(sel)
            if sk is None:
                return None
            return sk.Name, sk.Label
        self.sketch = self.field(g, "Sketch", "Sketch", "sketch", "Click a sketch",
                                 accept_sketch, "The sketch to project onto the faces")
        self.sketch.changed.connect(self._sketch_changed)
        self._loaders.append(lambda: self.sketch.set_items(
            [(self.obj.Sketch.Name, self.obj.Sketch.Label)] if self.obj.Sketch else []))
        self.pull = self.ref_box(g, "PullDirection", "Direction", "direction",
                                 "Click a plane, face or edge",
                                 "Direction of pull: the faces are split where they turn away "
                                 "from it", ("Face", "Edge"))

        def accept_tool(sel):
            o = sel.obj
            if o.TypeId in ("Part::DatumPlane",) or (util.role(o) == "refgeom" and
                                                     o.Proxy.KIND == "plane"):
                return (o.Name, ""), self.ref_text(o, "")
            if util.is_body_view(o) and sel.elem_kind() == "Face":
                r = selmod._from_body(sel, self.obj.BaseFeature, "Face")
                if r is None or isinstance(r, str):
                    return r
                return (r[0].Name, r[1]), self.ref_text(r[0], r[1])
            return None
        self.tools_caption = QtWidgets.QLabel("Splitting planes and faces")
        g.wide(self.tools_caption, "The planes or faces that split the faces where they cut "
                                   "them")
        self.tools = self.list(g, "Tools", "tools", "Click planes or faces", accept_tool,
                               "The planes or faces that split the faces where they cut them")
        self.tools.changed.connect(self._tools_changed)
        self._loaders.append(lambda: self.tools.set_items(
            [((o.Name, s), self.ref_text(o, s)) for o, subs in self.obj.Tools if o is not None
             for s in ((subs if isinstance(subs, (list, tuple)) else [subs]) or [""])]))
        self.faces_caption = QtWidgets.QLabel("Faces to split")
        g.wide(self.faces_caption, "The faces to split")
        self.faces = self.faces_box(g, "The faces to split. Click a face again to take it out.")
        self.single, self.r_single = self.check(g, "SingleDirection", "Single direction",
                                                "Project only one way along the sketch's "
                                                "normal")
        self.rev, self.r_rev = self.check(g, "Reverse", "Reverse direction",
                                          "Project (or look) the other way")

    def _sketch_changed(self):
        p = self.sketch.payloads()
        sk = self.doc.getObject(p[0]) if p else None
        if sk is not None and self.part is not None and sk not in self.part.Group:
            from ..app import part as part_mod
            part_mod.add_to_part(self.part, sk)
        if self.obj.Sketch is not sk:
            self.obj.Sketch = sk
        self.changed()

    def _tools_changed(self):
        items = []
        for name, sub in self.tools.payloads():
            items.append((self.doc.getObject(name), [sub] if sub else []))
        self.set_prop("Tools", items)

    def refresh(self):
        t = self.kind.currentText()
        c = self.core
        self.sketch.row.set_visible(t == c.PROJECTION)
        self.pull.row.set_visible(t == c.SILHOUETTE)
        self.tools.setVisible(t == c.INTERSECTION)
        self.tools_caption.setVisible(t == c.INTERSECTION)
        self.r_single.set_visible(t == c.PROJECTION)
        self.r_rev.set_visible(t == c.SILHOUETTE or (t == c.PROJECTION and
                                                     self.obj.SingleDirection))

    def preview_layers(self):
        return [("result", pv.shape_node(self.obj.AddSubShape, pv.REGION_PICKED, 0.0,
                                         line_width=4.0)
                 if not self.obj.AddSubShape.isNull() else None)]
