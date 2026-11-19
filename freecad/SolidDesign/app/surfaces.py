# SPDX-License-Identifier: LGPL-2.1-or-later
"""Knit, Planar, Filled, Trim and Extend surfaces; Delete Face; Thicken and
Thickened Cut (document objects)."""

import FreeCAD as App
import Part

from ..core import bodyops, regions, topo
from ..core.bodies import IdAllocator
from ..core.features import common
from ..core.features import surfaces as core
from . import feature, part as part_mod, refs, util


class _SurfaceTool(feature.FeatureProxy):
    def params(self, obj, base):
        p = core.Params()
        p.feature = obj.Name
        p.tag = obj.ID
        p.alloc = IdAllocator(obj.Name, IdAllocator.loads(obj.IdMemory), taken=base.ids())
        return p

    def done(self, obj, p, res, warns=()):
        mem = p.alloc.dumps()
        if obj.IdMemory != mem:
            obj.IdMemory = mem
        res.warnings.extend(w for w in warns if w)


def _sketch_parts(o):
    """(curves, points) of a sketch or other object: its edges and lone points."""
    shape = topo.shape_of(o)
    pts = []
    if o.TypeId.startswith("Sketcher::SketchObject"):
        pl = o.getGlobalPlacement()
        for g in o.Geometry:
            if isinstance(g, Part.Point) and not o.getConstruction(o.Geometry.index(g)):
                pts.append(pl.multVec(App.Vector(g.X, g.Y, g.Z)))
    return shape, pts


class KnitProxy(_SurfaceTool):
    TYPE = "Knit"
    LABELS = ("Surface-Knit",)

    def setup(self, obj):
        super(KnitProxy, self).setup(obj)
        a = util.add_prop
        g = "Knit"
        a(obj, "App::PropertyStringList", "Bodies", g, "Surface bodies to knit, by ID")
        a(obj, "App::PropertyBool", "CreateSolid", g, "Make a solid when the knit closes",
          False)
        a(obj, "App::PropertyBool", "MergeEntities", g, "Merge faces on one surface", True)
        a(obj, "App::PropertyLength", "GapTolerance", g, "Gaps up to this close are knitted",
          core.KNIT_TOL)

    def compute(self, obj, base):
        p = self.params(obj, base)
        p.bodies = list(obj.Bodies)
        p.solid = obj.CreateSolid
        p.merge = obj.MergeEntities
        p.tolerance = max(obj.GapTolerance.Value, 1e-7)
        res, preview = core.knit(p, base)
        self.done(obj, p, res)
        return res, preview


class PlanarProxy(_SurfaceTool):
    TYPE = "Planar"
    LABELS = ("Surface-Plane",)

    def setup(self, obj):
        super(PlanarProxy, self).setup(obj)
        a = util.add_prop
        g = "Planar Surface"
        a(obj, "App::PropertyLink", "Sketch", g, "A sketch whose closed regions become faces")
        a(obj, "App::PropertyLinkSub", "Items", g, "Closed, flat loops of model edges")

    def compute(self, obj, base):
        warns = []
        p = self.params(obj, base)
        if obj.Sketch is not None:
            faces, open_wires = regions.default_profile(obj.Sketch, obj.ID)
            if faces is None or open_wires:
                raise topo.GeometryError("{} isn't closed. A planar surface needs closed loops."
                                         .format(obj.Sketch.Label))
            p.wires.append(faces)
        edges, w = refs.get_refs(obj, "Items", "boundary edge", obj.BaseFeature)
        warns.extend(w)
        if edges:
            p.wires.append(Part.makeCompound([e for el in edges for e in el.Edges]))
        res, preview = core.planar(p, base)
        self.done(obj, p, res, warns)
        return res, preview


class FilledProxy(_SurfaceTool):
    TYPE = "Filled"
    LABELS = ("Surface-Fill",)

    def setup(self, obj):
        super(FilledProxy, self).setup(obj)
        a = util.add_prop
        g = "Patch Boundary"
        a(obj, "App::PropertyLinkSub", "Items", g, "Model edges around the patch")
        a(obj, "App::PropertyLink", "BoundarySketch", g, "Or: a sketch whose curves bound it")
        a(obj, "App::PropertyEnumeration", "Curvature", g,
          "Contact: the patch meets the edges. Tangent / Curvature: it continues the faces "
          "beside them smoothly", enum=core.CONTINUITY)
        a(obj, "App::PropertyBool", "Reverse", g, "Flip the patch's side", False)
        g = "Constraint Curves"
        a(obj, "App::PropertyLinkList", "Constraints", g,
          "Sketches whose curves and points the patch passes through")
        g = "Options"
        a(obj, "App::PropertyBool", "MergeResult", g,
          "Knit the patch into the surface its edges are on", True)
        a(obj, "App::PropertyBool", "CreateSolid", g,
          "Make a solid when the merged surface closes", False)

    def compute(self, obj, base):
        warns = []
        p = self.params(obj, base)
        edges, w = refs.get_refs(obj, "Items", "boundary edge", obj.BaseFeature)
        warns.extend(w)
        p.edges = [e for el in edges for e in el.Edges]
        if obj.BoundarySketch is not None:
            p.edges.extend(topo.shape_of(obj.BoundarySketch).Edges)
        for o in obj.Constraints:
            if o is None:
                continue
            curves, pts = _sketch_parts(o)
            if curves.Edges:
                p.curves.append(curves)
            p.points.extend(pts)
        p.continuity = obj.Curvature
        p.reverse = obj.Reverse
        p.merge = obj.MergeResult
        p.solid = obj.CreateSolid
        res, preview = core.filled(p, base)
        self.done(obj, p, res, warns)
        return res, preview


class TrimProxy(_SurfaceTool):
    TYPE = "Trim"
    LABELS = ("Surface-Trim",)

    def setup(self, obj):
        super(TrimProxy, self).setup(obj)
        a = util.add_prop
        g = "Trim"
        a(obj, "App::PropertyEnumeration", "TrimType", g,
          "Standard: a tool trims the surfaces. Mutual: surfaces trim each other",
          enum=core.TRIM_TYPES)
        a(obj, "App::PropertyLinkList", "TrimTools", g, "Planes and sketches that trim")
        a(obj, "App::PropertyLinkSub", "TrimFaces", g, "Faces of the model that trim")
        a(obj, "App::PropertyStringList", "TrimBodies", g, "Surface bodies that trim, by ID")
        a(obj, "App::PropertyStringList", "Bodies", g,
          "Mutual: the surfaces; Standard: the surfaces to trim (empty: all it cuts)")
        a(obj, "App::PropertyStringList", "PickedPoints", g,
          "Points on the picked pieces (x,y,z)")
        a(obj, "App::PropertyBool", "KeepSelections", g,
          "Keep the picked pieces (else remove them)", True)

    def tools(self, obj, base, warns):
        planes, sketches = [], []
        for o in obj.TrimTools:
            if o is None:
                continue
            if o.TypeId.startswith("Sketcher::SketchObject"):
                sketches.append((topo.shape_of(o), regions.sketch_normal(o)))
            else:
                from ..core import refgeom as core_ref
                shape = topo.shape_of(o)
                core_ref.plane_of(shape, "trim plane")
                planes.append(shape.Faces[0])
        faces, w = refs.get_refs(obj, "TrimFaces", "trim face", obj.BaseFeature)
        warns.extend(w)
        surfaces = []
        for bid in obj.TrimBodies:
            b = base.get(bid)
            if b is None:
                raise topo.GeometryError("A surface used to trim no longer exists.")
            surfaces.append(b.shape)
        if not (planes or sketches or faces or surfaces):
            return []
        big = topo.big_length(*[b.shape for b in base])
        return bodyops.trim_shapes(planes, faces, sketches, surfaces, big)

    def compute(self, obj, base):
        warns = []
        p = self.params(obj, base)
        p.kind = obj.TrimType
        p.bodies = [i for i in obj.Bodies if i not in obj.TrimBodies]
        if p.kind == core.STANDARD:
            p.tools = self.tools(obj, base, warns)
        p.points = [_vec(t) for t in obj.PickedPoints if _vec(t) is not None]
        p.keep = obj.KeepSelections
        res, preview = core.trim(p, base)
        self.done(obj, p, res, warns)
        return res, preview


def _vec(text):
    try:
        x, y, z = (float(v) for v in text.split(","))
        return App.Vector(x, y, z)
    except Exception:
        return None


def vec_text(v):
    return "{:.9g},{:.9g},{:.9g}".format(v.x, v.y, v.z)


class ExtendProxy(_SurfaceTool):
    TYPE = "Extend"
    LABELS = ("Surface-Extend",)

    def setup(self, obj):
        super(ExtendProxy, self).setup(obj)
        a = util.add_prop
        g = "Extend"
        a(obj, "App::PropertyLinkSub", "Items", g, "Open edges of surfaces to extend")
        a(obj, "App::PropertyLength", "Distance", g, "How far to extend", 5.0)
        a(obj, "App::PropertyEnumeration", "ExtensionType", g,
          "Same Surface: carry the surface on. Linear: go straight on, tangent to it",
          enum=core.EXTEND_TYPES)

    def compute(self, obj, base):
        warns = []
        p = self.params(obj, base)
        edges, w = refs.get_refs(obj, "Items", "edge to extend", obj.BaseFeature)
        warns.extend(w)
        p.edges = [e for el in edges for e in el.Edges]
        p.distance = obj.Distance.Value
        p.kind = obj.ExtensionType
        res, preview = core.extend(p, base)
        self.done(obj, p, res, warns)
        return res, preview


class DeleteFaceProxy(_SurfaceTool):
    TYPE = "DeleteFace"
    LABELS = ("DeleteFace",)

    def setup(self, obj):
        super(DeleteFaceProxy, self).setup(obj)
        a = util.add_prop
        g = "Delete Face"
        a(obj, "App::PropertyLinkSub", "Items", g, "Faces to delete")
        a(obj, "App::PropertyEnumeration", "DeleteType", g,
          "Delete: the faces go (a solid becomes a surface). Delete and Patch: the faces "
          "around heal over the gap. Delete and Fill: a patch fills it",
          enum=core.DELETE_TYPES)
        a(obj, "App::PropertyBool", "TangentFill", g, "Delete and Fill: a tangent patch",
          False)

    def compute(self, obj, base):
        warns = []
        p = self.params(obj, base)
        p.faces, w = refs.get_refs(obj, "Items", "face to delete", obj.BaseFeature)
        warns.extend(w)
        p.kind = obj.DeleteType
        p.continuity = core.TANGENT if obj.TangentFill else core.CONTACT
        res, preview = core.delete_face(p, base)
        self.done(obj, p, res, warns)
        return res, preview


class ThickenProxy(_SurfaceTool):
    TYPE = "Thicken"
    LABELS = ("Thicken", "Thicken-Cut")

    def setup(self, obj):
        super(ThickenProxy, self).setup(obj)
        a = util.add_prop
        g = "Thicken"
        a(obj, "App::PropertyEnumeration", "Mode", g, "Add (Thicken) or Cut (Thickened Cut)",
          enum=["Add", "Cut"])
        a(obj, "App::PropertyString", "Body", g, "The surface body to thicken, by ID", "")
        a(obj, "App::PropertyLength", "Thickness", g, "Thickness", 1.0)
        a(obj, "App::PropertyEnumeration", "ThickenSide", g,
          "Side 1 / Side 2: one side of the surface. Both Sides: half each",
          enum=core.SIDES)
        a(obj, "App::PropertyBool", "CreateSolid", g,
          "Create solid from enclosed volume (a closed surface)", False)
        a(obj, "App::PropertyBool", "MergeResult", g,
          "Fuse with the solids it touches (Thicken)", True)

    def default_label(self, obj):
        return self.LABELS[1] if obj.Mode == "Cut" else self.LABELS[0]

    def compute(self, obj, base):
        p = self.params(obj, base)
        p.bodies = [obj.Body]
        p.thickness = obj.Thickness.Value
        p.side = obj.ThickenSide
        p.solid = obj.CreateSolid
        p.merge = obj.MergeResult
        p.mode = obj.Mode
        p.scope = common.Scope()
        res, preview = core.thicken(p, base)
        self.done(obj, p, res)
        return res, preview

    def onChanged(self, obj, prop):
        if prop == "Mode" and "AutoLabel" in obj.PropertiesList and obj.AutoLabel:
            self.rename_for_mode(obj)

    def rename_for_mode(self, obj):
        import re
        prefix = self.default_label(obj)
        if obj.Label != obj.AutoLabel:
            return              # the user renamed it
        if re.match(re.escape(prefix) + r"\d+", obj.AutoLabel):
            return
        obj.AutoLabel = util.set_label(obj, prefix)


def _create(cls, doc, part, name, **props):
    obj = doc.addObject("Part::FeaturePython", name)
    cls(obj)
    for k, v in props.items():
        if k != "Items":
            setattr(obj, k, v)
    obj.AutoLabel = util.set_label(obj, obj.Proxy.default_label(obj))
    part_mod.insert_feature(part, obj)
    if "Items" in props and props["Items"]:
        refs.set_ref(obj, "Items", obj.BaseFeature, props["Items"])
    if App.GuiUp:
        from ..gui import viewproviders
        viewproviders.attach_feature(obj)
    return obj


def create_knit(doc, part, **props):
    return _create(KnitProxy, doc, part, "Knit", **props)


def create_planar(doc, part, **props):
    return _create(PlanarProxy, doc, part, "Planar", **props)


def create_filled(doc, part, **props):
    return _create(FilledProxy, doc, part, "Filled", **props)


def create_trim(doc, part, **props):
    return _create(TrimProxy, doc, part, "Trim", **props)


def create_extend(doc, part, **props):
    return _create(ExtendProxy, doc, part, "Extend", **props)


def create_delete_face(doc, part, **props):
    return _create(DeleteFaceProxy, doc, part, "DeleteFace", **props)


def create_thicken(doc, part, **props):
    return _create(ThickenProxy, doc, part, "Thicken", **props)
