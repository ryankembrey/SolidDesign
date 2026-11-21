# SPDX-License-Identifier: LGPL-2.1-or-later
"""Linear Pattern, Circular Pattern and Mirror document objects.

Features to repeat are links to the seed features (so they recompute when the
seed changes); bodies are IDs. Directions, axes and mirror planes are references
that follow the model.
"""

import FreeCAD as App

from ..core import refgeom as core_ref
from ..core import regions
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
            if getattr(getattr(f, "Proxy", None), "TYPE", "") in ("Fillet", "Chamfer"):
                if f.ErrorMessage:
                    raise topo.GeometryError("{} has an error; fix it before repeating it."
                                             .format(f.Label))
                out.append(_dressup_seed(f, obj, warns))
                continue
            if "ToolShape" not in f.PropertiesList or "Mode" not in f.PropertiesList:
                raise topo.GeometryError(
                    "{} can't be repeated: only features that add or cut a shape (Extrude, "
                    "Revolve, Hole), fillets and chamfers can. Pattern the bodies instead."
                    .format(f.Label))
            if f.ErrorMessage:
                raise topo.GeometryError("{} has an error; fix it before repeating it."
                                         .format(f.Label))
            out.append(core.Seed(f.Label, f.ToolShape, f.Mode, getattr(f, "MergeResult", True)))
        return out

    def seed_centre(self, obj, base):
        """Where the seed sits (the point the instances' centres are moved from), or
        None."""
        try:
            shapes = [base.get(b).shape for b in obj.Bodies if base.get(b) is not None]
            seeds = self.seeds(obj, base, [])
            c = core.reference_point(seeds, shapes) if (shapes or any(
                s.tool is not None for s in seeds)) else None
            if c is None:
                for f in obj.Features:
                    p = f.Proxy.params(f, []) if hasattr(f.Proxy, "params") else None
                    items = getattr(p, "items", None) or []
                    if items:
                        c = items[0].BoundBox.Center
                        break
            return c
        except Exception:
            return None

    def store_centres(self, obj, base, keyed, warns):
        """Where every instance sits (skipped ones too), so they can be shown in the
        view and clicked: [[key, x, y, z]] in InstanceCentres."""
        import json
        if "InstanceCentres" not in obj.PropertiesList:
            util.add_prop(obj, "App::PropertyString", "InstanceCentres", "Pattern",
                          "Where each instance sits (for picking them in the view)", "")
            util.hide_prop(obj, "InstanceCentres")
        c = self.seed_centre(obj, base)
        text = ""
        if c is not None:
            text = json.dumps([[k] + list(pl.multVec(c)) for k, pl in keyed])
        if obj.InstanceCentres != text:
            obj.InstanceCentres = text

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


def _dressup_seed(f, pattern, warns):
    """A fillet or chamfer to repeat: run again on its edges (faces, vertices) moved
    into each instance's place."""
    import copy
    from ..core.features import chamfer as core_chamfer
    from ..core.features import fillet as core_fillet
    w = []
    p = f.Proxy.params(f, w)
    if warns is not None:
        warns.extend(w)
    run = core_fillet.compute if f.Proxy.TYPE == "Fillet" else core_chamfer.compute
    lists = [a for a in ("items", "faces1", "faces2", "centre", "hold") if hasattr(p, a)]

    def redo(base, move):
        q = copy.copy(p)
        for a in lists:
            setattr(q, a, [move(x) for x in getattr(p, a)])
        q.feature, q.tag = pattern.Name, pattern.ID
        try:
            return run(q, base)
        except topo.GeometryError as e:
            raise topo.GeometryError("The repeated {} failed: {}".format(f.Label, e))
    return core.Seed(f.Label, None, "Dressup", redo=redo)


def read_table(text):
    """Points ("x,y") from a pattern table file: one point per line, X then Y,
    separated by spaces, tabs, commas or semicolons. Lines that aren't two numbers
    (headings, the seed's 'Point 0' label) are passed over."""
    import re
    out = []
    for line in text.splitlines():
        nums = re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", line)
        words = re.sub(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|[\s,;:]|mm", "", line)
        if len(nums) == 2 and not words:
            out.append("{:g},{:g}".format(float(nums[0]), float(nums[1])))
        elif len(nums) == 3 and not words:          # an index, then X and Y
            out.append("{:g},{:g}".format(float(nums[1]), float(nums[2])))
    return out


def table_text(points):
    """A pattern table file: one point per line, X and Y separated by a tab."""
    lines = []
    for t in points:
        x, _c, y = str(t).partition(",")
        lines.append("{}\t{}".format(x.strip() or "0", y.strip() or "0"))
    return "\n".join(lines) + "\n"


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
        every = core.linear(d1, obj.Spacing.Value, obj.Instances, d2, s2, n2, obj.PatternSeedOnly)
        slots = core.linear_slots(obj.Instances, n2, obj.PatternSeedOnly)[1:]
        self.store_centres(obj, base, [("{},{}".format(*k), m) for k, m in zip(slots, every)],
                           warns)
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
        every = core.circular(p, d, obj.Angle.Value, obj.Instances, obj.EqualSpacing)
        self.store_centres(obj, base, [(str(k), m) for k, m in enumerate(every, 2)], warns)
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
        g = "Direction 2"
        a(obj, "App::PropertyBool", "Direction2", g, "Pattern along a second curve too", False)
        a(obj, "App::PropertyLinkSub", "Curve2", g, "The second curve: model edges")
        a(obj, "App::PropertyLink", "CurveSketch2", g, "Or: a sketch")
        a(obj, "App::PropertyBool", "Reverse2", g, "Reverse direction 2", False)
        a(obj, "App::PropertyInteger", "Instances2", g, "Number of instances along it", 2)
        a(obj, "App::PropertyBool", "EqualSpacing2", g, "Spread over the whole curve", True)
        a(obj, "App::PropertyLength", "Spacing2", g, "Distance along the second curve", 10.0)
        a(obj, "App::PropertyStringList", "InstancesToSkip", "Instances to Skip",
          "Instances left out, by number (the seed is 1); with Direction 2, by i,j")

    def curve(self, obj, warns, n=""):
        from ..core import skin
        edges = []
        sk = getattr(obj, "CurveSketch" + n)
        ref = getattr(obj, "Curve" + n)
        if sk is not None:
            edges = list(topo.shape_of(sk).Edges)
        elif ref and ref[0] is not None:
            shapes, w = refs.get_refs(obj, "Curve" + n, "curve", obj.BaseFeature)
            warns.extend(w)
            edges = [e for s in shapes for e in s.Edges]
        if not edges and n:
            raise topo.GeometryError("Pick the curve for Direction 2: edges or a sketch.")
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
        if not getattr(obj, "Direction2", False):
            moves = core.curve_driven(curve, ref, obj.Instances, obj.Spacing.Value,
                                      obj.EqualSpacing, obj.Alignment, obj.Reverse,
                                      _numbers(obj.InstancesToSkip))
            every = core.curve_driven(curve, ref, obj.Instances, obj.Spacing.Value,
                                      obj.EqualSpacing, obj.Alignment, obj.Reverse)
            self.store_centres(obj, base, [(str(k), m) for k, m in enumerate(every, 2)], warns)
            return self.run(obj, base, moves, warns)
        # Two curves: every instance along the first is repeated along the second (the
        # second carries them as they are, without turning).
        curve2 = self.curve(obj, warns, "2")
        m1 = [App.Placement()] + core.curve_driven(curve, ref, obj.Instances,
                                                   obj.Spacing.Value, obj.EqualSpacing,
                                                   obj.Alignment, obj.Reverse)
        m2 = [App.Placement()] + (core.curve_driven(curve2, ref, obj.Instances2,
                                                    obj.Spacing2.Value, obj.EqualSpacing2,
                                                    core.TRANSLATE, obj.Reverse2)
                                  if obj.Instances2 > 1 else [])
        skip = _pairs(obj.InstancesToSkip)
        moves, keyed = [], []
        for j, b in enumerate(m2, 1):
            for i, a_ in enumerate(m1, 1):
                if (i, j) == (1, 1):
                    continue
                keyed.append(("{},{}".format(i, j), b.multiply(a_)))
                if (i, j) not in skip:
                    moves.append(b.multiply(a_))
        self.store_centres(obj, base, keyed, warns)
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
        n = sk.getGlobalPlacement().Rotation.multVec(App.Vector(0, 0, 1))
        return self.run(obj, base, core.to_points(pts, ref, normal=n), warns)


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
        n = pl.Rotation.multVec(App.Vector(0, 0, 1))
        return self.run(obj, base, core.to_points(pts, ref, normal=n), warns)


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


# ------------------------------------------------------------------ Variable Pattern

SKETCH_KEY = "Sketch:"
VARIABLE_TYPES = ("Extrude", "Revolve")


class _Instance(object):
    """A seed feature as it would be with other values: reads fall through to the
    feature, except the changed values; writes stay here, so the feature itself is
    never touched."""

    def __init__(self, feature, values, sketch):
        self.__dict__["_f"] = feature
        self.__dict__["_v"] = dict(values)
        if sketch is not None:
            self.__dict__["_v"]["Sketch"] = sketch
            self.__dict__["_v"]["Contours"] = []
        self.__dict__["_local"] = {}

    def __getattr__(self, name):
        d = self.__dict__
        if name in d["_local"]:
            return d["_local"][name]
        if name in d["_v"]:
            return d["_v"][name]
        return getattr(d["_f"], name)

    def __setattr__(self, name, value):
        self.__dict__["_local"][name] = value


def variable_dimensions(f):
    """[(key, label, current value)] that a Variable Pattern can change on ``f``: its
    lengths and angles, and its sketch's named dimensions."""
    out = []

    def on(name):
        return bool(getattr(f, name, False))
    wanted = []
    for n in ("", "2"):
        if n and not on("Direction2"):
            continue
        end = str(getattr(f, "EndCondition" + n, ""))
        for prop in ("Depth", "Angle"):
            if prop + n in f.PropertiesList and ("Blind" in end or "Mid" in end or
                                                 end in ("", "Two Directions")):
                wanted.append(prop + n)
        if "Offset" in end:
            wanted.append("Offset" + n)
        if on("Draft" + n):
            wanted.append("DraftAngle" + n)
    if on("Thin"):
        wanted.append("ThinThickness")
        if "Two" in str(getattr(f, "ThinType", "")):
            wanted.append("ThinThickness2")
        if on("CapEnds"):
            wanted.append("CapThickness")
    if str(getattr(f, "From", "")) == "Offset":
        wanted.append("FromOffset")
    for prop in wanted:
        if prop in f.PropertiesList:
            v = getattr(f, prop)
            if hasattr(v, "Value"):
                out.append((prop, prop, v.Value))
    sk = getattr(f, "Sketch", None)
    if sk is not None and sk.TypeId.startswith("Sketcher::SketchObject"):
        for i, c in enumerate(sk.Constraints):
            if c.Name and c.Type in ("Distance", "DistanceX", "DistanceY", "Radius", "Diameter",
                                     "Angle"):
                v = sk.getDatum(i)
                out.append((SKETCH_KEY + c.Name, "{} ({})".format(c.Name, sk.Label), v.Value))
    return out


def _scratch():
    return topo.scratch_doc()


def _solved_sketch(tmp, sk, values):
    """A copy of ``sk`` in the scratch document, with named dimensions changed."""
    copy = tmp.addObject("Sketcher::SketchObject", "Instance")
    copy.Placement = regions.sketch_placement(sk)
    copy.Geometry = sk.Geometry
    keep = []
    for c in sk.Constraints:
        ids = [c.First, c.Second, getattr(c, "Third", -2000)]
        if any(-2000 < g <= -3 for g in ids):
            continue                    # tied to external geometry: dropped in the copy
        keep.append(c)
    copy.Constraints = keep
    names = [c.Name for c in keep]
    for name, v in values.items():
        if name not in names:
            raise topo.GeometryError("{} has no dimension named {}.".format(sk.Label, name))
        i = names.index(name)
        unit = copy.getDatum(i).Unit
        copy.setDatum(i, App.Units.Quantity(v, unit))
    tmp.recompute()
    if not copy.Shape.Edges or "Invalid" in copy.State or "Error" in copy.State:
        raise topo.GeometryError("{} doesn't solve with those values.".format(sk.Label))
    return copy


class VariablePatternProxy(_Pattern):
    """SolidWorks' Variable Pattern: each row of the table is one more instance of a
    feature, with its dimensions (the feature's own, and its sketch's named ones)
    set to that row's values. Position dimensions in the sketch place each instance."""
    TYPE = "VariablePattern"
    LABELS = ("VPattern",)

    def setup(self, obj):
        super(VariablePatternProxy, self).setup(obj)
        a = util.add_prop
        g = "Table"
        a(obj, "App::PropertyStringList", "Dimensions", g,
          "The dimensions each instance changes: a feature property (Depth) or a sketch "
          "dimension (Sketch:Name)")
        a(obj, "App::PropertyStringList", "Instances", g,
          "One row per instance: its values, in the Dimensions' order, separated by ;")
        util.hide_prop(obj, "Bodies")
        util.hide_prop(obj, "Faces")

    def rows(self, obj):
        dims = [d for d in obj.Dimensions if d]
        out = []
        for n, t in enumerate(obj.Instances, 1):
            try:
                vals = [float(x) for x in str(t).split(";") if x.strip()]
            except ValueError:
                raise topo.GeometryError("Instance {} has a value that isn't a number."
                                         .format(n))
            if len(vals) != len(dims):
                raise topo.GeometryError("Instance {} has {} values; the table has {} "
                                         "dimensions.".format(n, len(vals), len(dims)))
            out.append(dict(zip(dims, vals)))
        return out

    def compute(self, obj, base):
        warns = []
        feats = [f for f in obj.Features if f is not None]
        if len(feats) != 1:
            raise topo.GeometryError("Pick the one feature to vary (an Extrude or a Revolve).")
        f = feats[0]
        if getattr(getattr(f, "Proxy", None), "TYPE", "") not in VARIABLE_TYPES:
            raise topo.GeometryError("{} can't be varied: Variable Pattern varies an Extrude "
                                     "or a Revolve.".format(f.Label))
        if f.ErrorMessage:
            raise topo.GeometryError("{} has an error; fix it first.".format(f.Label))
        if not obj.Dimensions:
            raise topo.GeometryError("Add the dimensions that change to the table.")
        rows = self.rows(obj)
        if not rows:
            raise topo.GeometryError("Add instances to the table: one row each.")
        props = [d for d in obj.Dimensions if not d.startswith(SKETCH_KEY)]
        for d in props:
            if d not in f.PropertiesList or not hasattr(getattr(f, d), "Unit"):
                raise topo.GeometryError("{} has no dimension {}.".format(f.Label, d))
        seeds = []
        tmp = _scratch()
        made = []
        try:
            for n, row in enumerate(rows, 1):
                vals = {d: App.Units.Quantity(v, getattr(f, d).Unit)
                        for d, v in row.items() if not d.startswith(SKETCH_KEY)}
                sk_vals = {d[len(SKETCH_KEY):]: v for d, v in row.items()
                           if d.startswith(SKETCH_KEY)}
                sk = _solved_sketch(tmp, f.Sketch, sk_vals) if sk_vals else None
                if sk is not None:
                    made.append(sk.Name)
                inst = _Instance(f, vals, sk)
                try:
                    f.Proxy.compute(inst, base)
                except topo.GeometryError as e:
                    raise topo.GeometryError("Instance {}: {}".format(n, e))
                tool = inst._local.get("ToolShape")
                if tool is None or tool.isNull():
                    raise topo.GeometryError("Instance {} made no shape.".format(n))
                seeds.append(core.Seed("{} ({})".format(f.Label, n), tool, f.Mode,
                                       getattr(f, "MergeResult", True)))
        finally:
            for n in made:
                try:
                    tmp.removeObject(n)
                except Exception:
                    pass
        alloc = IdAllocator(obj.Name, IdAllocator.loads(obj.IdMemory), taken=base.ids())
        res, preview = core.repeat(base, seeds, [], [App.Placement()], obj.Name, obj.ID, alloc)
        mem = alloc.dumps()
        if obj.IdMemory != mem:
            obj.IdMemory = mem
        res.warnings.extend(w for w in warns if w)
        return res, preview


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


def create_variable(doc, part, **props):
    return _create(VariablePatternProxy, doc, part, "VariablePattern", **props)
