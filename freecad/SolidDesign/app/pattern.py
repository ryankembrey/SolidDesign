# SPDX-License-Identifier: LGPL-2.1-or-later
"""Linear Pattern, Circular Pattern and Mirror document objects.

Features to repeat are links to the seed features (so they recompute when the
seed changes); bodies are IDs. Directions, axes and mirror planes are references
that follow the model.
"""

import FreeCAD as App

from ..core import refgeom as core_ref
from ..core import topo
from ..core.bodies import IdAllocator
from ..core.features import edges as edgemod
from ..core.features import pattern as core
from . import feature, part as part_mod, refs, util


def direction_of(shape, what):
    """A direction from an edge or axis (its line) or a plane/face (its normal)."""
    try:
        return core_ref.line_of(shape, what)
    except topo.GeometryError:
        p, n, _x = core_ref.plane_of(shape, what)
        return p, n


class _Pattern(feature.FeatureProxy):
    def setup(self, obj):
        super(_Pattern, self).setup(obj)
        a = util.add_prop
        g = "Pattern"
        a(obj, "App::PropertyLinkList", "Features", g, "Features to repeat")
        a(obj, "App::PropertyStringList", "Bodies", g, "Bodies to repeat, by ID")
        a(obj, "App::PropertyLinkSub", "Faces", g,
          "Faces to repeat: every face of a boss, hole or pocket")

    def seeds(self, obj, base=None, warns=None):
        out = []
        if base is not None and obj.Faces and obj.Faces[0] is not None:
            faces, w = refs.get_refs(obj, "Faces", "face to repeat", obj.BaseFeature)
            if warns is not None:
                warns.extend(w)
            for bid, fs in edgemod.faces_by_body(base, faces).items():
                out.append(core.face_seed(bid, fs, base.get(bid).shape, obj.ID))
        for f in obj.Features:
            if f is None:
                continue
            if "ToolShape" not in f.PropertiesList or "Mode" not in f.PropertiesList:
                raise topo.GeometryError(
                    "{} can't be repeated: only features that add or cut a shape (Extrude, "
                    "Revolve, Hole) can. Pattern the bodies instead.".format(f.Label))
            if f.ErrorMessage:
                raise topo.GeometryError("{} has an error; fix it before repeating it."
                                         .format(f.Label))
            out.append(core.Seed(f.Label, f.ToolShape, f.Mode, getattr(f, "MergeResult", True)))
        return out

    def ref(self, obj, prop, what, warns):
        s, w = refs.get_ref(obj, prop, what, obj.BaseFeature)
        warns.append(w)
        if s is None:
            raise topo.GeometryError("Pick the {}.".format(what))
        return s

    def run(self, obj, base, moves, warns, merge=False):
        alloc = IdAllocator(obj.Name, IdAllocator.loads(obj.IdMemory), taken=base.ids())
        res, preview = core.repeat(base, self.seeds(obj, base, warns), list(obj.Bodies), moves,
                                   obj.Name, obj.ID, alloc, merge)
        mem = alloc.dumps()
        if obj.IdMemory != mem:
            obj.IdMemory = mem
        res.warnings.extend(w for w in warns if w)
        return res, preview


def _pairs(texts):
    out = set()
    for t in texts:
        try:
            i, j = (int(x) for x in t.split(","))
            out.add((i, j))
        except Exception:
            pass
    return out


def _numbers(texts):
    out = set()
    for t in texts:
        try:
            out.add(int(t))
        except Exception:
            pass
    return out


class LinearPatternProxy(_Pattern):
    TYPE = "LinearPattern"
    LABELS = ("LPattern",)

    def setup(self, obj):
        super(LinearPatternProxy, self).setup(obj)
        a = util.add_prop
        for n, g in (("", "Direction 1"), ("2", "Direction 2")):
            if n:
                a(obj, "App::PropertyBool", "Direction2", g, "Pattern in a second direction",
                  False)
                a(obj, "App::PropertyBool", "PatternSeedOnly", g,
                  "Repeat only the seed in Direction 2", False)
            a(obj, "App::PropertyLinkSub", "Direction{}Ref".format(n or "1"), g,
              "Edge, axis, or plane (its normal)")
            a(obj, "App::PropertyBool", "Reverse" + n, g, "Reverse direction", False)
            a(obj, "App::PropertyLength", "Spacing" + n, g, "Spacing", 10.0)
            a(obj, "App::PropertyInteger", "Instances" + n, g, "Number of instances (with the seed)",
              2)
        a(obj, "App::PropertyStringList", "InstancesToSkip", "Instances to Skip",
          "Instances left out, as i,j (the seed is 1,1)")

    def compute(self, obj, base):
        warns = []
        _p, d1 = direction_of(self.ref(obj, "Direction1Ref", "direction for Direction 1", warns),
                              "Direction 1")
        if obj.Reverse:
            d1 = -d1
        d2, s2, n2 = None, 0.0, 1
        if obj.Direction2:
            _p, d2 = direction_of(self.ref(obj, "Direction2Ref", "direction for Direction 2", warns),
                                  "Direction 2")
            if obj.Reverse2:
                d2 = -d2
            s2, n2 = obj.Spacing2.Value, obj.Instances2
        moves = core.linear(d1, obj.Spacing.Value, obj.Instances, d2, s2, n2, obj.PatternSeedOnly,
                            skip=_pairs(obj.InstancesToSkip))
        return self.run(obj, base, moves, warns)


class CircularPatternProxy(_Pattern):
    TYPE = "CircularPattern"
    LABELS = ("CirPattern",)

    def setup(self, obj):
        super(CircularPatternProxy, self).setup(obj)
        a = util.add_prop
        g = "Direction 1"
        a(obj, "App::PropertyLinkSub", "Axis", g, "Axis, straight or circular edge, round face")
        a(obj, "App::PropertyBool", "Reverse", g, "Reverse direction", False)
        a(obj, "App::PropertyAngle", "Angle", g, "Total angle (Equal spacing) or spacing", 360.0)
        a(obj, "App::PropertyInteger", "Instances", g, "Number of instances (with the seed)", 4)
        a(obj, "App::PropertyBool", "EqualSpacing", g, "Equal spacing", True)
        a(obj, "App::PropertyStringList", "InstancesToSkip", "Instances to Skip",
          "Instances left out, by number (the seed is 1)")

    def compute(self, obj, base):
        warns = []
        p, d = core_ref.line_of(self.ref(obj, "Axis", "pattern axis", warns), "pattern axis")
        if obj.Reverse:
            d = -d
        moves = core.circular(p, d, obj.Angle.Value, obj.Instances, obj.EqualSpacing,
                              skip=_numbers(obj.InstancesToSkip))
        return self.run(obj, base, moves, warns)


class MirrorProxy(_Pattern):
    TYPE = "Mirror"
    LABELS = ("Mirror",)

    def setup(self, obj):
        super(MirrorProxy, self).setup(obj)
        a = util.add_prop
        a(obj, "App::PropertyLinkSub", "MirrorPlane", "Mirror", "Mirror face or plane")
        a(obj, "App::PropertyBool", "MergeSolids", "Mirror",
          "Merge mirrored bodies with the originals they touch", True)

    def compute(self, obj, base):
        warns = []
        p, n, _x = core_ref.plane_of(self.ref(obj, "MirrorPlane", "mirror face or plane", warns),
                                     "mirror face or plane")
        return self.run(obj, base, [(p, n)], warns, obj.MergeSolids)


class _PointPattern(_Pattern):
    """Patterns placing the seed at points: the seed's centre is its reference."""

    def reference(self, obj, base, warns):
        seeds = self.seeds(obj, base, warns)
        shapes = [base.get(b).shape for b in obj.Bodies if base.get(b) is not None]
        return core.reference_point(seeds, shapes)


class CurvePatternProxy(_PointPattern):
    TYPE = "CurvePattern"
    LABELS = ("CrvPattern",)

    def setup(self, obj):
        super(CurvePatternProxy, self).setup(obj)
        a = util.add_prop
        g = "Direction 1"
        a(obj, "App::PropertyLinkSub", "Curve", g, "The curve: model edges")
        a(obj, "App::PropertyLink", "CurveSketch", g, "Or: a sketch (its curves, end to end)")
        a(obj, "App::PropertyBool", "Reverse", g, "Reverse direction", False)
        a(obj, "App::PropertyInteger", "Instances", g, "Number of instances (with the seed)", 4)
        a(obj, "App::PropertyBool", "EqualSpacing", g, "Spread over the whole curve", True)
        a(obj, "App::PropertyLength", "Spacing", g, "Distance along the curve", 10.0)
        a(obj, "App::PropertyEnumeration", "Alignment", g,
          "Tangent to curve: instances turn with the curve. Align to seed: they keep the "
          "seed's orientation", enum=core.ALIGNMENTS)
        a(obj, "App::PropertyStringList", "InstancesToSkip", "Instances to Skip",
          "Instances left out, by number (the seed is 1)")

    def curve(self, obj, warns):
        from ..core import skin
        edges = []
        if obj.CurveSketch is not None:
            edges = list(topo.shape_of(obj.CurveSketch).Edges)
        elif obj.Curve and obj.Curve[0] is not None:
            shapes, w = refs.get_refs(obj, "Curve", "curve", obj.BaseFeature)
            warns.extend(w)
            edges = [e for s in shapes for e in s.Edges]
        if not edges:
            raise topo.GeometryError("Pick the curve to pattern along: edges or a sketch.")
        import Part
        try:
            chains = Part.sortEdges(edges)
        except Exception:
            chains = [edges]
        if len(chains) != 1:
            raise topo.GeometryError("The curve must be one chain of edges, end to end.")
        return skin.Section(Part.Wire(chains[0]))

    def compute(self, obj, base):
        warns = []
        curve = self.curve(obj, warns)
        ref = self.reference(obj, base, warns)
        moves = core.curve_driven(curve, ref, obj.Instances, obj.Spacing.Value, obj.EqualSpacing,
                                  obj.Alignment, obj.Reverse, _numbers(obj.InstancesToSkip))
        return self.run(obj, base, moves, warns)


class SketchPatternProxy(_PointPattern):
    TYPE = "SketchPattern"
    LABELS = ("Sketch-Pattern",)

    def setup(self, obj):
        super(SketchPatternProxy, self).setup(obj)
        a = util.add_prop
        g = "Selections"
        a(obj, "App::PropertyLink", "Sketch", g, "The sketch whose points place the instances")

    def compute(self, obj, base):
        warns = []
        sk = obj.Sketch
        if sk is None:
            raise topo.GeometryError("Pick the sketch whose points place the instances.")
        pts = sketch_points(sk)
        if not pts:
            raise topo.GeometryError("{} has no points (sketch points, not construction)."
                                     .format(sk.Label))
        ref = self.reference(obj, base, warns)
        return self.run(obj, base, core.to_points(pts, ref), warns)


def sketch_points(sk):
    """The sketch's points (not construction), in global coordinates."""
    import Part
    pl = sk.getGlobalPlacement()
    out = []
    for i, g in enumerate(sk.Geometry):
        if isinstance(g, Part.Point) and not sk.getConstruction(i):
            out.append(pl.multVec(App.Vector(g.X, g.Y, g.Z)))
    return out


class TablePatternProxy(_PointPattern):
    TYPE = "TablePattern"
    LABELS = ("TPattern",)

    def setup(self, obj):
        super(TablePatternProxy, self).setup(obj)
        a = util.add_prop
        g = "Table"
        a(obj, "App::PropertyLink", "CoordinateSystem", g,
          "The coordinate system the X and Y values are in (none: the part's origin)")
        a(obj, "App::PropertyStringList", "Points", g, "Instance positions, as X,Y")

    def compute(self, obj, base):
        warns = []
        cs = obj.CoordinateSystem
        pl = App.Placement()
        if cs is not None:
            pl = cs.Placement if "Placement" in cs.PropertiesList else pl
            try:
                pl = cs.getGlobalPlacement()
            except Exception:
                pass
        pts = []
        for t in obj.Points:
            try:
                x, y = (float(v) for v in t.split(","))
            except Exception:
                raise topo.GeometryError("Table row \"{}\" isn't X,Y.".format(t))
            pts.append(pl.multVec(App.Vector(x, y, 0)))
        if not pts:
            raise topo.GeometryError("Add points to the table.")
        ref = self.reference(obj, base, warns)
        return self.run(obj, base, core.to_points(pts, ref), warns)


class FillPatternProxy(_PointPattern):
    TYPE = "FillPattern"
    LABELS = ("Fill Pattern",)

    def setup(self, obj):
        super(FillPatternProxy, self).setup(obj)
        a = util.add_prop
        g = "Fill Boundary"
        a(obj, "App::PropertyLinkSub", "Boundary", g, "A flat face to fill")
        a(obj, "App::PropertyLink", "BoundarySketch", g, "Or: a sketch's closed region")
        g = "Pattern Layout"
        a(obj, "App::PropertyEnumeration", "Layout", g,
          "Perforation: staggered rows. Circular: rings. Square: a grid. Polygon: "
          "polygon rings", enum=core.LAYOUTS)
        a(obj, "App::PropertyLength", "InstanceSpacing", g, "Between instances", 10.0)
        a(obj, "App::PropertyLength", "LoopSpacing", g, "Between rings (Circular, Polygon)",
          10.0)
        a(obj, "App::PropertyAngle", "StaggerAngle", g, "Perforation: how rows shift", 60.0)
        a(obj, "App::PropertyInteger", "PolygonSides", g, "Polygon: sides", 6)
        a(obj, "App::PropertyLength", "Margin", g, "Kept clear inside the boundary", 2.0)
        a(obj, "App::PropertyLinkSub", "PatternDirection", g,
          "The direction rows run: an edge (none: along the boundary's first straight edge)")
        g = "Seed"
        a(obj, "App::PropertyEnumeration", "SeedCut", g,
          "Create seed cut: cut this shape at every instance (None: repeat the features "
          "picked)", enum=core.SEED_SHAPES)
        a(obj, "App::PropertyLength", "SeedSize", g, "The seed cut's size (across)", 4.0)
        a(obj, "App::PropertyInteger", "SeedSides", g, "Polygon seed: sides", 6)
        a(obj, "App::PropertyBool", "FlipCut", g, "Cut the other way", False)

    def boundary(self, obj, warns):
        if obj.BoundarySketch is not None:
            from ..core import regions
            faces, _o = regions.default_profile(obj.BoundarySketch, obj.ID)
            if faces is None or not faces.Faces:
                raise topo.GeometryError("{} has no closed region to fill.".format(
                    obj.BoundarySketch.Label))
            return faces.Faces[0], None
        if not obj.Boundary or obj.Boundary[0] is None:
            raise topo.GeometryError("Pick the face (or sketch) to fill.")
        faces, w = refs.get_refs(obj, "Boundary", "fill boundary", obj.BaseFeature)
        warns.extend(w)
        if not faces:
            raise topo.GeometryError("Pick the face to fill.")
        return faces[0], faces[0]

    def direction(self, obj, face, warns):
        if obj.PatternDirection and obj.PatternDirection[0] is not None:
            s = self.ref(obj, "PatternDirection", "pattern direction", warns)
            return direction_of(s, "pattern direction")[1]
        for e in face.OuterWire.Edges:
            if e.Curve.TypeId == "Part::GeomLine":
                return (e.Vertexes[-1].Point - e.Vertexes[0].Point).normalize()
        return App.Vector(1, 0, 0)

    def compute(self, obj, base):
        warns = []
        face, model_face = self.boundary(obj, warns)
        d = self.direction(obj, face, warns)
        if obj.SeedCut != "None":
            return self.seed_cut(obj, base, face, model_face, d, warns)
        seeds = self.seeds(obj, base, warns)
        shapes = [base.get(b).shape for b in obj.Bodies if base.get(b) is not None]
        ref = core.reference_point(seeds, shapes)
        n = face.normalAt(0, 0)
        on = ref - n * (ref - face.CenterOfMass).dot(n)
        seed = (seeds[0].tool if seeds else shapes[0])
        bb = seed.BoundBox
        reach = 0.0                     # how far the seed spreads in the face's plane
        for x in (bb.XMin, bb.XMax):
            for y in (bb.YMin, bb.YMax):
                for z in (bb.ZMin, bb.ZMax):
                    rel = App.Vector(x, y, z) - on
                    reach = max(reach, (rel - n * rel.dot(n)).Length)
        reach /= 2 ** 0.5               # the box's corners overstate a round seed
        pts = core.fill_points(face, on, d, obj.Layout, obj.InstanceSpacing.Value,
                               obj.StaggerAngle.Value, obj.LoopSpacing.Value, obj.PolygonSides,
                               obj.Margin.Value + reach)
        moves = core.to_points(pts, on)
        return self.run(obj, base, moves, warns)

    def seed_cut(self, obj, base, face, model_face, d, warns):
        from ..core.features import common
        from ..core.features.edges import faces_by_body
        if model_face is None:
            raise topo.GeometryError("Create seed cut needs a face of the model as the "
                                     "boundary.")
        groups = faces_by_body(base, [model_face])
        bid = next(iter(groups))
        body = base.get(bid).shape
        n = face.normalAt(0, 0)
        if body.isInside(face.CenterOfMass + n * 1e-4, 1e-7, False):
            n = -n
        if obj.FlipCut:
            n = -n
        size = obj.SeedSize.Value
        if size <= 0:
            raise topo.GeometryError("The seed cut's size must be greater than zero.")
        pts = core.fill_points(face, face.CenterOfMass, d, obj.Layout,
                               obj.InstanceSpacing.Value, obj.StaggerAngle.Value,
                               obj.LoopSpacing.Value, obj.PolygonSides,
                               obj.Margin.Value + size / 2.0)
        if not pts:
            raise topo.GeometryError("No instance fits inside the boundary: make the spacing, "
                                     "margin or seed smaller.")
        depth = body.BoundBox.DiagonalLength
        tools = [core.seed_cut(obj.SeedCut, size, obj.SeedSides, p, n, d, depth) for p in pts]
        import Part
        tool = topo.tagged(Part.makeCompound(tools), obj.ID)
        alloc = IdAllocator(obj.Name, IdAllocator.loads(obj.IdMemory), taken=base.ids())
        res = common.apply_cut(base, tool, obj.Name, obj.ID, common.Scope(False, [bid]),
                               common.Keep(), alloc)
        mem = alloc.dumps()
        if obj.IdMemory != mem:
            obj.IdMemory = mem
        res.warnings.extend(w for w in warns if w)
        return res, tool


def _create(cls, doc, part, name, **props):
    obj = doc.addObject("Part::FeaturePython", name)
    cls(obj)
    obj.AutoLabel = util.set_label(obj, cls.LABELS[0])
    part_mod.insert_feature(part, obj)
    for k, v in props.items():
        setattr(obj, k, v)
    if App.GuiUp:
        from ..gui import viewproviders
        viewproviders.attach_feature(obj)
    return obj


def create_linear(doc, part, **props):
    return _create(LinearPatternProxy, doc, part, "LinearPattern", **props)


def create_circular(doc, part, **props):
    return _create(CircularPatternProxy, doc, part, "CircularPattern", **props)


def create_mirror(doc, part, **props):
    return _create(MirrorProxy, doc, part, "Mirror", **props)


def create_curve(doc, part, **props):
    return _create(CurvePatternProxy, doc, part, "CurvePattern", **props)


def create_sketch_pattern(doc, part, **props):
    return _create(SketchPatternProxy, doc, part, "SketchPattern", **props)


def create_table(doc, part, **props):
    return _create(TablePatternProxy, doc, part, "TablePattern", **props)


def create_fill(doc, part, **props):
    return _create(FillPatternProxy, doc, part, "FillPattern", **props)
