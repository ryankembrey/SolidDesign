# SPDX-License-Identifier: LGPL-2.1-or-later
"""Knit, Planar, Filled, Trim and Extend surface panels; Delete Face; Thicken."""

import FreeCAD as App

from ..app import part as part_mod
from ..app import refs, util
from .. import icon
from ..app import surfaces as app_surf
from ..core.features import surfaces as core
from . import preview as pv
from . import selection as selmod
from .panel import parts
from .tool_panels import ToolPanel

__all__ = ["KnitPanel", "PlanarPanel", "FilledPanel", "TrimPanel", "ExtendPanel",
           "DeleteFacePanel", "ThickenPanel"]


def _is_sketch(o):
    return o.TypeId.startswith("Sketcher::SketchObject")


def _open_edge(edge, view):
    """A refusal unless the edge is open (one face beside it) on a surface body."""
    if getattr(view, "Kind", "") != "surface":
        return "Pick edges of a surface body."
    try:
        n = len(view.Shape.ancestorsOfType(edge, __import__("Part").Face))
    except Exception:
        n = 1
    return None if n == 1 else "Pick an open edge (the surface's boundary)."


class _SurfacePanel(ToolPanel):
    def surfaces_box(self, group, prop, tip, label=None, multiple=True, empty=None):
        """Surface bodies by ID."""
        box = self.bodies_box(group, prop, tip, label=label, multiple=multiple, empty=empty,
                              hint="Click surface bodies")
        inner = box.accept_fn

        def accept(sel):
            o = sel.obj
            if util.is_body_view(o) and getattr(o, "Kind", "") != "surface":
                return "That is a solid; pick a surface body."
            return inner(sel)
        box.accept_fn = accept
        return box

    def sketches_box(self, group, prop, tip, multiple=True, label="Sketch", empty=None):
        def accept(sel):
            o = sel.obj
            if util.is_curve(o):
                return o.Name, o.Label
            return None
        if multiple:
            box = self.list(group, prop, "sketches", "Click sketches", accept, tip, empty)
            box.changed.connect(lambda: self.set_prop(
                prop, [self.doc.getObject(n) for n in box.payloads()]))
            self._loaders.append(lambda: box.set_items(
                [(o.Name, o.Label) for o in getattr(self.obj, prop) if o is not None]))
        else:
            box = self.field(group, label, prop, "sketch", "Click a sketch", accept, tip, empty)
            box.changed.connect(lambda: self.set_prop(
                prop, self.doc.getObject(box.payloads()[0]) if box.payloads() else None))
            self._loaders.append(lambda: box.set_items(
                [(getattr(self.obj, prop).Name, getattr(self.obj, prop).Label)]
                if getattr(self.obj, prop) is not None else []))
        return box


class KnitPanel(_SurfacePanel):
    TITLE = "Knit Surface"
    ICON_NAME = "Knit"

    def build(self):
        g = self.group("Selections")
        self.bodies = self.surfaces_box(g, "Bodies", "The surfaces to knit into one; the "
                                        "first keeps its name")
        self.solid, _r = self.check(g, "CreateSolid", "Create solid",
                                    "Make a solid when the knitted surfaces close up")
        self.merge, _r = self.check(g, "MergeEntities", "Merge entities",
                                    "Merge faces lying on one surface")
        g = self.group("Gap Control")
        self.gap, _r = self.qty(g, "GapTolerance", "Knitting tolerance",
                                "Gaps up to this wide are closed", minimum=1e-7, step=0.01)


class PlanarPanel(_SurfacePanel):
    TITLE = "Planar Surface"
    ICON_NAME = "PlanarSurface"

    def build(self):
        g = self.group("Bounding Entities")
        self.sketch = self.sketches_box(g, "Sketch", "A sketch: its closed regions become "
                                        "flat faces", multiple=False, empty="None")
        self.edges = self.elements_list(g, "Items", "Or closed loops of model edges in one "
                                        "plane", "Edge", empty="None")


class FilledPanel(_SurfacePanel):
    TITLE = "Filled Surface"
    ICON_NAME = "FilledSurface"

    def build(self):
        g = self.group("Patch Boundary")
        self.edges = self.elements_list(g, "Items", "The edges around the patch: one closed "
                                        "loop", "Edge")
        self.sketch = self.sketches_box(g, "BoundarySketch", "Or a sketch whose curves make "
                                        "the loop", multiple=False, label="Sketch",
                                        empty="None")
        self.curv, _r = self.choice(
            g, "Curvature", "Curvature control",
            "Contact: the patch meets the edges. Tangent: it continues the faces beside them "
            "smoothly. Curvature: smoother still.")
        self.rev, _r = self.check(g, "Reverse", "Reverse surface", "Flip the patch's side")
        g = self.group("Constraint Curves")
        self.cons = self.sketches_box(g, "Constraints", "Sketches whose curves and points the "
                                      "patch passes through", empty="None")
        g = self.group("Options")
        self.merge, _r = self.check(g, "MergeResult", "Merge result",
                                    "Knit the patch into the surface its edges belong to")
        self.solid, self.r_solid = self.check(g, "CreateSolid", "Try to form solid",
                                              "Make a solid when the merged surface closes")

    def refresh(self):
        self.r_solid.set_visible(self.obj.MergeResult)


class TrimPanel(_SurfacePanel):
    """Trim tools, then click the pieces to keep or remove (SolidWorks' order)."""
    TITLE = "Trim Surface"
    ICON_NAME = "TrimSurface"
    EDIT_SHOWS_BASE = True

    def build(self):
        obj = self.obj
        g = self.group("Trim Type")
        self.ttype = parts.Switch(
            core.TRIM_TYPES,
            tips={core.STANDARD: "A plane, sketch or surface trims the surfaces",
                  core.MUTUAL: "The surfaces trim each other"})
        self.ttype.set_value(obj.TrimType)
        self.ttype.changed.connect(lambda m: self.set_prop("TrimType", m))
        g.wide(self.ttype)
        g = self.sec_tool = self.group("Trim Tool")

        def accept_tool(sel):
            o = sel.obj
            if _is_sketch(o) or o.TypeId == "Part::DatumPlane" \
                    or (util.role(o) == "refgeom" and o.Proxy.KIND == "plane"):
                return ("obj", o.Name), o.Label
            if util.is_body_view(o):
                if sel.elem_kind() == "Face" and o.Kind != "surface":
                    r = selmod._from_body(sel, obj.BaseFeature, "Face")
                    if r is None or isinstance(r, str):
                        return r
                    return ("face", r[1]), self.ref_text(r[0], r[1])
                if o.Kind == "surface" and self.active_box is self.tools:
                    return ("body", o.BodyId), part_mod.clean_label(o.Label)
            return None
        self.tools = self.list(g, "TrimTools", "trim tools",
                               "Click a plane, sketch, face or surface", accept_tool,
                               "What trims the surfaces: planes, sketches, faces or surface "
                               "bodies")
        self.tools.changed.connect(self._tools_changed)
        g = self.sec_mutual = self.group("Surfaces")
        self.bodies = self.surfaces_box(g, "Bodies", "Mutual: the surfaces that trim each "
                                        "other")
        g = self.group("Pieces")
        self.keep = parts.Switch(
            ["Keep selections", "Remove selections"],
            tips={"Keep selections": "The pieces you click stay; the rest go",
                  "Remove selections": "The pieces you click go"})
        self.keep.set_value("Keep selections" if obj.KeepSelections else "Remove selections")
        self.keep.changed.connect(
            lambda m: self.set_prop("KeepSelections", m == "Keep selections"))
        g.wide(self.keep)

        def accept_piece(sel):
            o = sel.obj
            if not util.is_body_view(o) or getattr(o, "Kind", "") != "surface":
                return None
            if sel.point is None:
                return "Click on the piece in the 3D view."
            pt = App.Vector(*sel.point) if not isinstance(sel.point, App.Vector) \
                else sel.point
            return app_surf.vec_text(pt), "{} at ({:.1f}, {:.1f}, {:.1f})".format(
                part_mod.clean_label(o.Label), pt.x, pt.y, pt.z)
        self.pieces = self.list(g, "PickedPoints", "pieces", "Click pieces in the 3D view",
                                accept_piece, "The pieces to keep or remove: click on them in "
                                "the 3D view")
        self.pieces.changed.connect(
            lambda: self.set_prop("PickedPoints", list(self.pieces.payloads())))

    def load(self):
        obj = self.obj
        items = [(("obj", o.Name), o.Label) for o in obj.TrimTools if o is not None]
        v = obj.TrimFaces
        if v and v[0] is not None:
            items += [(("face", sub), self.ref_text(v[0], sub)) for sub in v[1]]
        items += [(("body", b), self.body_label(b)) for b in obj.TrimBodies]
        self.tools.set_items(items)
        self.pieces.set_items([(t, "Piece at ({})".format(t)) for t in obj.PickedPoints])
        super(TrimPanel, self).load()

    def _tools_changed(self):
        objs, faces, bodies = [], [], []
        for kind, val in self.tools.payloads():
            if kind == "obj":
                objs.append(self.doc.getObject(val))
            elif kind == "face":
                faces.append(val)
            else:
                bodies.append(val)
        self.obj.TrimTools = objs
        refs.set_ref(self.obj, "TrimFaces", self.obj.BaseFeature if faces else None, faces)
        self.obj.TrimBodies = bodies
        self.changed()

    def refresh(self):
        mutual = self.obj.TrimType == core.MUTUAL
        self.sec_tool.setVisible(not mutual)
        self.sec_mutual.setVisible(mutual)

    def preview_layers(self):
        layers = super(TrimPanel, self).preview_layers()
        from pivy import coin
        sep = coin.SoSeparator()
        for k, t in enumerate(self.obj.PickedPoints, 1):
            p = app_surf._vec(t)
            if p is not None:
                sep.addChild(pv.label_node(str(k), p))
        layers.append(("picks", sep if self.obj.PickedPoints else None))
        return layers


class ExtendPanel(_SurfacePanel):
    TITLE = "Extend Surface"
    ICON_NAME = "ExtendSurface"

    def build(self):
        g = self.group("Edges to Extend")
        self.edges = self.elements_list(g, "Items", "The open edges of a surface to carry on",
                                        "Edge", check=_open_edge)
        g = self.group("End Condition")
        self.end = parts.Switch(
            core.EXTEND_ENDS,
            tips={core.DISTANCE: "Extend by a distance",
                  core.UP_TO_POINT: "Extend until it reaches a point",
                  core.UP_TO_SURFACE: "Extend until it meets a surface or plane"})
        self.end.set_value(getattr(self.obj, "EndCondition", core.DISTANCE))
        self.end.changed.connect(lambda m: self.set_prop("EndCondition", m))
        g.wide(self.end)
        self.dist, self.r_dist = self.qty(g, "Distance", "Distance", "How far to extend")
        self.upto = self.ref_box(g, "UpTo", "Up to", "target", "Click a point, face or plane",
                                 "The point, or the surface or plane, to extend up to",
                                 kinds=("Vertex", "Face"))
        g = self.group("Extension Type")
        self.etype = parts.Switch(
            core.EXTEND_TYPES,
            tips={core.SAME_SURFACE: "Carry the surface on as it goes (a cylinder stays a "
                                     "cylinder)",
                  core.LINEAR: "Go straight on, tangent to the surface at the edge"})
        self.etype.set_value(self.obj.ExtensionType)
        self.etype.changed.connect(lambda m: self.set_prop("ExtensionType", m))
        g.wide(self.etype)

    def refresh(self):
        end = self.obj.EndCondition
        self.r_dist.set_visible(end == core.DISTANCE)
        self.upto.row.set_visible(end != core.DISTANCE)


class DeleteFacePanel(_SurfacePanel):
    TITLE = "Delete Face"
    ICON_NAME = "DeleteFace"

    def build(self):
        g = self.group("Selections")
        self.faces = self.faces_list(g, "Items", "The faces to delete")
        g = self.group("Options")
        self.dtype, _r = self.choice(
            g, "DeleteType", "Option",
            "Delete: the faces go, and a solid becomes a surface body. Delete and Patch: the "
            "faces around heal over the gap (removes bosses, holes, fillets). Delete and "
            "Fill: a patch fills the gap.")
        self.tan, self.r_tan = self.check(g, "TangentFill", "Tangent fill",
                                          "Make the patch tangent to the faces around it")

    def refresh(self):
        self.r_tan.set_visible(self.obj.DeleteType == core.FILL)


class ThickenPanel(_SurfacePanel):
    TITLE = "Thicken"
    ICON_NAME = "Thicken"

    def build(self):
        obj = self.obj
        self.mode = parts.Switch(
            ["Add", "Cut"],
            tips={"Add": "Add material: the thickened surface becomes a solid, fused to "
                         "the solids it touches when Merge result is on",
                  "Cut": "Remove material: the thickened surface is cut from the solids"},
            icons={"Add": icon("Thicken"), "Cut": icon("ThickenCut")})
        self.mode.set_value(obj.Mode)
        self.mode.changed.connect(lambda m: self.set_prop("Mode", m))
        self.layout.addWidget(self.mode)
        g = self.group("Thicken Parameters")
        self.body = self.surfaces_box(g, "Body", "The surface to thicken; it is used up",
                                      label="Surface", multiple=False)
        self.side = parts.Switch(
            core.SIDES,
            tips={core.SIDE1: "Thicken on the surface's front side",
                  core.SIDE2: "Thicken on its back side",
                  core.BOTH: "Half on each side"})
        self.side.set_value(obj.ThickenSide)
        self.side.changed.connect(lambda m: self.set_prop("ThickenSide", m))
        g.wide(self.side)
        self.t, self.r_t = self.qty(g, "Thickness", "Thickness", "How thick", step=0.5)
        self.solid, _r = self.check(g, "CreateSolid", "Create solid from enclosed volume",
                                    "A closed surface: the solid inside it")
        self.merge, self.r_merge = self.check(g, "MergeResult", "Merge result",
                                              "Fuse with the solids it touches")
        g = self.sec_scope = self.group("Feature Scope", "Which solids it works on")
        self.all_b, _r = self.check(g, "AllBodies", "All bodies",
                                    "Work on every solid it reaches; untick to choose them")
        self.sec_scope_b = self.group("Bodies in Scope")
        self.scope_b = self.bodies_box(self.sec_scope_b, "ScopeBodies",
                                       "The solids it works on", hint="Click solids")

    def refresh(self):
        self.sec_scope_b.setVisible(not self.obj.AllBodies)
        solid = self.obj.CreateSolid
        self.side.setVisible(not solid)
        self.r_t.set_visible(not solid)
        self.r_merge.set_visible(self.obj.Mode == "Add")


class IntersectPanel(_SurfacePanel):
    """Selections, Intersect mode, then the regions to exclude (SolidWorks' order)."""
    TITLE = "Intersect"
    ICON_NAME = "Intersect"

    def build(self):
        from PySide import QtCore, QtWidgets
        obj = self.obj
        g = self.group("Selections")
        self.bodies = self.bodies_box(g, "Bodies", "Solids and surfaces to intersect",
                                      hint="Click solids or surfaces")

        def accept_plane(sel):
            o = sel.obj
            if o.TypeId == "Part::DatumPlane" or (util.role(o) == "refgeom" and
                                                  o.Proxy.KIND == "plane"):
                return o.Name, o.Label
            return None
        self.planes = self.list(g, "Planes", "planes", "Click planes", accept_plane,
                                "Planes that cut the selections into regions", empty="None")
        self.planes.changed.connect(lambda: self.set_prop(
            "Planes", [self.doc.getObject(n) for n in self.planes.payloads()]))
        self._loaders.append(lambda: self.planes.set_items(
            [(o.Name, o.Label) for o in obj.Planes if o is not None]))
        self.mode = parts.Switch(
            ["Both", "Intersecting", "Internal"],
            tips={"Both": core_int_mode("Both"),
                  "Intersecting": core_int_mode("Intersecting"),
                  "Internal": core_int_mode("Internal")})
        self.mode.set_value(_short(obj.IntersectMode))
        self.mode.changed.connect(lambda m: self.set_prop("IntersectMode", _long(m)))
        g.wide(self.mode)
        self.cap, _r = self.check(g, "CapPlanarOpenings", "Cap planar openings on surfaces",
                                  "Close the surfaces' flat openings so they bound regions")
        g = self.group("Regions to Exclude",
                       "Tick the regions to leave out; the rest become solid bodies")
        self.region_list = QtWidgets.QListWidget()
        self.region_list.setMinimumHeight(90)
        self.region_list.itemChanged.connect(self._region_ticked)
        g.wide(self.region_list, "The regions, numbered in the view: tick one to exclude it")
        self._qt = QtCore
        g = self.group("Options")
        self.merge, _r = self.check(g, "MergeResult", "Merge result",
                                    "Kept regions that touch become one body")
        self.consume, _r = self.check(g, "ConsumeSurfaces", "Consume surfaces",
                                      "The surfaces are used up")

    def _regions(self):
        return getattr(self.obj.Proxy, "regions", []) or []

    def _excluded(self, solid):
        pts = [app_surf._vec(t) for t in self.obj.ExcludedPoints]
        return any(p is not None and solid.isInside(p, 1e-6, True) for p in pts)

    def after_preview(self):
        QtCore = self._qt
        lst = self.region_list
        lst.blockSignals(True)
        lst.clear()
        for k, (pt, vol, kind, solid) in enumerate(self._regions(), 1):
            it = parts.QtWidgets.QListWidgetItem(
                u"Region {} \u2014 {:.4g} mm\u00b3 ({})".format(k, vol, kind))
            it.setFlags(it.flags() | QtCore.Qt.ItemIsUserCheckable)
            it.setCheckState(QtCore.Qt.Checked if self._excluded(solid) else
                             QtCore.Qt.Unchecked)
            lst.addItem(it)
        lst.blockSignals(False)

    def _region_ticked(self, _item):
        QtCore = self._qt
        regs = self._regions()
        pts = []
        for k in range(self.region_list.count()):
            if self.region_list.item(k).checkState() == QtCore.Qt.Checked and k < len(regs):
                pts.append(app_surf.vec_text(regs[k][0]))
        self.set_prop("ExcludedPoints", pts)

    def preview_layers(self):
        layers = super(IntersectPanel, self).preview_layers()
        from pivy import coin
        regs = self._regions()
        sep = coin.SoSeparator()
        for k, (pt, _v, _kind, _s) in enumerate(regs, 1):
            sep.addChild(pv.label_node(str(k), pt))
        layers.append(("regions", sep if regs else None))
        return layers


def _short(mode):
    return {"Create both": "Both", "Create intersecting regions": "Intersecting",
            "Create internal regions": "Internal"}.get(mode, "Both")


def _long(m):
    return {"Both": "Create both", "Intersecting": "Create intersecting regions",
            "Internal": "Create internal regions"}[m]


def core_int_mode(m):
    return {"Both": "Regions inside the solids, and hollows closed off by the selections",
            "Intersecting": "Regions inside the solids, split where the selections cross",
            "Internal": "Hollows closed off by the selections, inside no solid"}[m]


class DomePanel(_SurfacePanel):
    TITLE = "Dome"
    ICON_NAME = "Dome"

    def build(self):
        g = self.group("Parameters")
        self.faces = self.faces_list(g, "Items", "The flat faces to dome")
        self.dist, _r = self.qty(g, "Distance", "Distance", "The dome's height",
                                 flip="ReverseDirection",
                                 flip_tip="A dent instead of a dome")
        self.ell, _r = self.check(g, "EllipticalDome", "Elliptical dome",
                                  "Half an ellipsoid on a round face; square to the face at "
                                  "its edge on others")
        self.cont, self.r_cont = self.check(g, "ContinuousDome", "Continuous dome",
                                            "Faces that aren't round: the outline rounds off "
                                            "as it rises, with no creases from the corners")
        self.ref_box(g, "DomeDirection", "Direction", "direction",
                     "Click an edge, axis or plane",
                     "Lean the dome this way; empty: straight up from the face",
                     kinds=("Edge", "Face"), empty="Normal to face")
        self.ref_box(g, "ConstraintPoint", "Top at", "point", "Click a point or vertex",
                     "The dome's top goes through this point (it sets the height and lean)",
                     kinds=("Vertex",), empty="None")


class WrapPanel(_SurfacePanel):
    TITLE = "Wrap"
    ICON_NAME = "Wrap"

    def build(self):
        obj = self.obj
        g = self.group("Wrap Type")
        self.wtype = parts.Switch(
            ["Emboss", "Deboss", "Scribe"],
            tips={"Emboss": "Raise the sketch out of the face",
                  "Deboss": "Sink the sketch into the face",
                  "Scribe": "Only split the face along the sketch"})
        self.wtype.set_value(obj.WrapType)
        self.wtype.changed.connect(lambda m: self.set_prop("WrapType", m))
        g.wide(self.wtype)
        g = self.group("Wrap Parameters")
        self.sketch = self.sketches_box(g, "Sketch", "The sketch to wrap: on a plane along "
                                        "the cylinder's axis, or parallel to a flat face",
                                        multiple=False, label="Source sketch")
        self.face = self.ref_box(g, "Items", "Face", "face", "Click a face",
                                 "The cylindrical or flat face to wrap onto", ("Face",))
        self.depth, self.r_depth = self.qty(g, "Depth", "Depth", "How far it stands up or "
                                            "sinks in", flip="ReverseDirection",
                                            flip_tip="The other way")
        self.method, _r = self.choice(g, "WrapMethod", "Method",
                                      "Analytical: rolled round a cylinder or cone without "
                                      "stretching (flat faces: projected). Spline Surface: "
                                      "projected onto any face along the sketch's normal")

    def refresh(self):
        self.r_depth.set_visible(self.obj.WrapType != "Scribe")


class RuledPanel(_SurfacePanel):
    TITLE = "Ruled Surface"
    ICON_NAME = "RuledSurface"

    def build(self):
        g = self.group("Type")
        self.kind, _r = self.choice(
            g, "RuledType", "Type",
            "Tangent to Surface: carries on from the face beside the edge. Normal to Surface: "
            "stands square off it. Tapered / Perpendicular to Vector: at an angle to, or square "
            "to, a direction you pick. Sweep: one smooth surface swept along the edges, "
            "leaving the first at the face's tangent (or the vector).")
        g = self.group("Distance/Direction")
        self.dist, _r = self.qty(g, "Distance", "Distance", "How far the strips reach",
                                 flip="AlternateSide", flip_tip="The other side")
        self.vec = self.ref_box(g, "ReferenceVector", "Reference vector", "direction",
                                "Click an edge or plane", "The direction to taper to, or "
                                "stand square to: an edge or axis, or a plane's normal",
                                ("Edge", "Face"))
        self.ang, self.r_ang = self.qty(g, "Angle", "Angle", "The angle to the vector",
                                        unit="deg", minimum=-89.0, maximum=89.0, step=5.0)
        g = self.group("Edge Selection")
        self.edges = self.elements_list(g, "Items", "The edges the strips stand off", "Edge")
        g = self.sec_opts = self.group("Options")
        self.tk, self.r_tk = self.check(g, "TrimAndKnit", "Trim and knit",
                                        "Cut the strips back where they cross at corners, "
                                        "and knit them into one surface")
        self.cs, self.r_cs = self.check(g, "ConnectingSurface", "Connecting surface",
                                        "Fill the gaps between strips at sharp corners")

    def refresh(self):
        self.sec_opts.setVisible(self.obj.RuledType != "Sweep")
        vec = self.obj.RuledType in ("Tapered to Vector", "Perpendicular to Vector", "Sweep")
        self.vec.row.set_visible(vec)
        self.r_ang.set_visible(self.obj.RuledType == "Tapered to Vector")


class RadiatePanel(_SurfacePanel):
    TITLE = "Radiate Surface"
    ICON_NAME = "RadiateSurface"

    def build(self):
        g = self.group("Radiate Parameters")
        self.plane = self.ref_box(g, "ReferencePlane", "Reference plane", "plane",
                                  "Click a plane or flat face",
                                  "The surface lies parallel to this plane", ("Face",))
        self.edges = self.elements_list(g, "Items", "The edges to radiate from", "Edge")
        self.dist, _r = self.qty(g, "Distance", "Distance", "How far it reaches",
                                 flip="Reverse", flip_tip="Towards the faces instead")
        self.prop, _r = self.check(g, "PropagateTangent", "Propagate to tangent faces",
                                   "Carry on along the edges meeting the picked ones smoothly")


class UntrimPanel(_SurfacePanel):
    TITLE = "Untrim Surface"
    ICON_NAME = "UntrimSurface"

    def build(self):
        g = self.group("Selections")
        self.faces = self.faces_list(g, "Items", "The faces to untrim")
        g = self.group("Options")
        self.kind, _r = self.choice(
            g, "UntrimType", "Untrim",
            "Internal edges: fill the face's holes. All edges: the whole surface it lies on, "
            "grown by the percentage. External edges: grown, holes kept.")
        self.pct = parts.IntField(self.obj, "DistancePercent", minimum=0)
        self.pct.changed.connect(lambda v: self.set_prop("DistancePercent", v))
        self.r_pct = g.row("Distance %", self.pct, "How much bigger than the face, in each "
                           "direction")

    def refresh(self):
        self.r_pct.set_visible(self.obj.UntrimType != "Internal edges")


class MidSurfacePanel(_SurfacePanel):
    TITLE = "Mid-Surface"
    ICON_NAME = "MidSurface"

    def build(self):
        g = self.group("Selections")
        self.bodies = self.bodies_box(g, "Bodies", "Find the face pairs on these bodies",
                                      empty="None")
        self.faces = self.faces_list(g, "Items", "Or the faces to pair", empty="None")
        self.th, _r = self.qty(g, "Threshold", "Recognition threshold",
                               "Pair faces up to this far apart (0: the thinnest walls)")


class CutWithSurfacePanel(_SurfacePanel):
    TITLE = "Surface Cut"
    ICON_NAME = "SurfaceCut"
    PREVIEW_ADDS = False

    def build(self):
        g = self.group("Surface Cut Parameters")
        self.body = self.surfaces_box(g, "CuttingBody", "The surface that cuts",
                                      label="Surface", multiple=False, empty="None")
        self.plane = self.ref_box(g, "CuttingPlane", "Or plane", "plane",
                                  "Click a plane or flat face", "A plane that cuts",
                                  ("Face",), empty="None")
        self.flip, _r = self.check(g, "Flip", "Flip cut", "Keep the other side")
        g = self.group("Feature Scope")
        self.scope = self.bodies_box(g, "Bodies", "The bodies to cut (none picked: all)",
                                     empty="All bodies")


class ReplaceFacePanel(_SurfacePanel):
    TITLE = "Replace Face"
    ICON_NAME = "ReplaceFace"

    def build(self):
        g = self.group("Replace Face Parameters")
        self.faces = self.faces_list(g, "Items", "The faces to replace")
        self.body = self.surfaces_box(g, "ReplacementBody", "The surface that replaces them",
                                      label="Replacement", multiple=False)
        self.consume, _r = self.check(g, "ConsumeSurface", "Use up the replacement surface",
                                      "Hide it in the result, as SolidWorks does")


class ScalePanel(_SurfacePanel):
    TITLE = "Scale"
    ICON_NAME = "Scale"

    def build(self):
        obj = self.obj
        g = self.group("Bodies to Scale")
        self.bodies = self.bodies_box(g, "Bodies", "The bodies to scale (none picked: every "
                                      "solid)", empty="All solids")
        g = self.group("Scale Parameters")
        self.about, _r = self.choice(g, "ScaleAbout", "Scale about",
                                     "Centroid: each body's centre. Origin: the part's origin. "
                                     "Coordinate System: one you pick.")

        def accept(sel):
            o = sel.obj
            if util.role(o) == "refgeom" and o.Proxy.KIND == "csys":
                return o.Name, o.Label
            return None
        self.cs = self.field(g, "Coordinate system", "CoordinateSystem", "coordinate system",
                             "Click a coordinate system", accept,
                             "The coordinate system to scale about", empty="None")
        self.cs.changed.connect(lambda: self.set_prop(
            "CoordinateSystem",
            self.doc.getObject(self.cs.payloads()[0]) if self.cs.payloads() else None))
        self._loaders.append(lambda: self.cs.set_items(
            [(obj.CoordinateSystem.Name, obj.CoordinateSystem.Label)]
            if obj.CoordinateSystem is not None else []))
        self.uniform, _r = self.check(g, "Uniform", "Uniform scaling",
                                      "The same factor every way (keeps every surface's kind)")
        self.f, self.r_f = self.qty(g, "Factor", "Scale factor", "How many times bigger",
                                    unit="", minimum=1e-6, step=0.1)
        self.fx, self.r_fx = self.qty(g, "FactorX", "X", "Factor along X", unit="",
                                      minimum=1e-6, step=0.1)
        self.fy, self.r_fy = self.qty(g, "FactorY", "Y", "Factor along Y", unit="",
                                      minimum=1e-6, step=0.1)
        self.fz, self.r_fz = self.qty(g, "FactorZ", "Z", "Factor along Z", unit="",
                                      minimum=1e-6, step=0.1)

    def refresh(self):
        u = self.obj.Uniform
        self.r_f.set_visible(u)
        for r in (self.r_fx, self.r_fy, self.r_fz):
            r.set_visible(not u)
        self.cs.row.set_visible(self.obj.ScaleAbout == "Coordinate System")


class FlexPanel(_SurfacePanel):
    TITLE = "Flex"
    ICON_NAME = "Flex"

    def build(self):
        g = self.group("Flex Input")
        self.bodies = self.bodies_box(g, "Bodies", "The bodies to flex (none picked: every "
                                      "solid)", empty="All solids")
        self.kind, _r = self.choice(g, "FlexType", "Type",
                                    "Bending, twisting, tapering or stretching along the flex "
                                    "axis, between the trim planes")
        self.ang, self.r_ang = self.qty(g, "Angle", "Angle", "How far it bends or twists",
                                        unit="deg", minimum=-3600.0, maximum=3600.0, step=15.0)
        self.taper, self.r_taper = self.qty(g, "TaperFactor", "Taper factor",
                                            "Its size at the far trim plane (1: no taper)",
                                            unit="", minimum=0.01, step=0.1)
        self.stretch, self.r_stretch = self.qty(g, "StretchDistance", "Stretch distance",
                                                "How much longer", minimum=-1e6)
        g = self.group("Trim Planes", "Where the flexing starts and ends along the axis")
        self.t1, _r = self.qty(g, "TrimPlane1", "Trim plane 1", "In from the body's near end")
        self.t2, _r = self.qty(g, "TrimPlane2", "Trim plane 2", "In from the body's far end")
        g = self.group("Triad", "The flex axis and the way it bends")
        self.axis = self.ref_box(g, "FlexAxis", "Flex axis", "axis", "Click an edge or axis",
                                 "The axis it flexes along (none: the body's longest side)",
                                 ("Edge", "Face"), empty="Automatic")
        self.rot, self.r_rot = self.qty(g, "TriadRotation", "Rotation",
                                        "Turns the bend's direction round the flex axis",
                                        unit="deg", minimum=-360.0, maximum=360.0, step=15.0)
        self.rev, _r = self.check(g, "ReverseAxis", "Reverse axis", "Flex from the other end")

    def refresh(self):
        k = self.obj.FlexType
        self.r_ang.set_visible(k in ("Bending", "Twisting"))
        self.r_taper.set_visible(k == "Tapering")
        self.r_stretch.set_visible(k == "Stretching")
        self.r_rot.set_visible(k == "Bending")
