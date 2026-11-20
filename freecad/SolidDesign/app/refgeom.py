# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reference Plane, Axis, Point and Coordinate System (SolidWorks' reference
geometry).

They sit in the part's history like features (rolled back with the bar) but
don't change bodies, so they aren't in the feature chain: each takes the
feature just before it as ``BaseFeature``, and its references follow the model
from there. Their Shape is the plane's face or the axis's edge, so sketches,
Revolve, Mirror and Patterns use them like any datum.
"""

import FreeCAD as App
import Part

from ..core import curves
from ..core import refgeom as core
from ..core import topo
from . import part as part_mod
from . import refs, util

from .feature import EDITING


class _RefGeomProxy(object):
    SD_ROLE = "refgeom"
    KIND = "plane"
    TYPES = core.PLANE_TYPES
    LABEL = "Plane"

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        a = util.add_prop
        g = "Reference"
        a(obj, "App::PropertyEnumeration", "Type", g, "How it is defined", enum=self.TYPES)
        for i in (1, 2, 3):
            a(obj, "App::PropertyLinkSub", "Reference%d" % i, g, "Reference %d" % i)
        a(obj, "App::PropertyBool", "Flip", g, "Flip", False)
        a(obj, "App::PropertyLink", "BaseFeature", "Base", "The feature just before it")
        a(obj, "App::PropertyString", "ErrorMessage", "Result", "Why it failed", "")
        a(obj, "App::PropertyString", "WarningMessage", "Result", "Warnings", "")
        a(obj, "App::PropertyMap", "RefFingerprints", "Result", "Fingerprints of references")
        a(obj, "App::PropertyBool", "RolledBack", "Result", "Below the rollback bar", False)
        a(obj, "App::PropertyString", "AutoLabel", "Base", "Automatic label", "")
        a(obj, "App::PropertyInteger", "SchemaVersion", "Base", "File format", util.SCHEMA_VERSION)
        for p in ("BaseFeature", "RefFingerprints", "RolledBack", "AutoLabel", "SchemaVersion"):
            util.hide_prop(obj, p)
        for p in ("ErrorMessage", "WarningMessage"):
            util.readonly_prop(obj, p)

    def onDocumentRestored(self, obj):
        self.setup(obj)
        # Newer versions add types (Coincident): planes from older files get them.
        if list(obj.getEnumerationsOfProperty("Type")) != list(self.TYPES):
            current = obj.Type
            obj.Type = list(self.TYPES)
            if current in self.TYPES:
                obj.Type = current

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def is_rolled_back(self, obj):
        """Below the bar: after the first feature that follows the tip. Items between
        the tip and the next feature were made at the bar and count as above it."""
        if obj.Name in EDITING:
            return False
        part = util.part_of(obj)
        if part is None:
            return False
        g = list(part.Group)
        return obj in g and g.index(obj) > part_mod._bar_index(part, g)

    def resolved(self, obj, warns):
        out = []
        for i in (1, 2, 3):
            s, w = refs.get_ref(obj, "Reference%d" % i, "reference %d" % i, obj.BaseFeature)
            if w:
                warns.append(w)
            out.append(s)
        while out and out[-1] is None:
            out.pop()
        return out

    def model_size(self, obj):
        base = obj.BaseFeature
        if base is not None and not base.Shape.isNull() and base.Shape.Solids:
            return base.Shape.BoundBox
        return None

    def execute(self, obj):
        rolled = self.is_rolled_back(obj)
        if obj.RolledBack != rolled:
            obj.RolledBack = rolled
        if rolled and not obj.Shape.isNull():
            return          # frozen below the rollback bar (see FeatureProxy.execute)
        warns = []
        try:
            shape = self.make(obj, self.resolved(obj, warns))
            err = ""
        except topo.GeometryError as e:
            shape, err = None, str(e)
        except Exception as e:
            shape, err = None, "Internal error: {}".format(e)
        if obj.ErrorMessage != err:
            obj.ErrorMessage = err
        w = "; ".join(warns)
        if obj.WarningMessage != w:
            obj.WarningMessage = w
        if shape is not None:
            obj.Shape = shape


class RefPlaneProxy(_RefGeomProxy):
    KIND = "plane"
    TYPES = core.PLANE_TYPES
    LABEL = "Plane"

    def setup(self, obj):
        super(RefPlaneProxy, self).setup(obj)
        util.add_prop(obj, "App::PropertyLength", "Distance", "Reference", "Offset distance", 10.0)
        util.add_prop(obj, "App::PropertyAngle", "Angle", "Reference", "Angle", 45.0)

    def make(self, obj, shapes):
        pl = core.plane(obj.Type, shapes, obj.Distance.Value, obj.Angle.Value, obj.Flip)
        bb = self.model_size(obj)
        size = max(20.0, 1.2 * bb.DiagonalLength) if bb is not None else 50.0
        if bb is not None:
            # Centre the face on the model's centre, projected onto the plane.
            n = pl.Rotation.multVec(App.Vector(0, 0, 1))
            c = bb.Center - n * (bb.Center - pl.Base).dot(n)
            pl = App.Placement(c, pl.Rotation)
        return core.plane_face(pl, size)


class RefAxisProxy(_RefGeomProxy):
    KIND = "axis"
    TYPES = core.AXIS_TYPES
    LABEL = "Axis"

    def make(self, obj, shapes):
        p, d = core.axis(obj.Type, shapes, obj.Flip)
        bb = self.model_size(obj)
        length = max(20.0, 1.2 * bb.DiagonalLength) if bb is not None else 50.0
        return core.axis_edge(p, d, length, bb.Center if bb is not None else None)


class RefPointProxy(_RefGeomProxy):
    KIND = "point"
    TYPES = core.POINT_TYPES
    LABEL = "Point"

    def setup(self, obj):
        super(RefPointProxy, self).setup(obj)
        util.add_prop(obj, "App::PropertyLength", "Distance", "Reference",
                      "Distance along the curve (Along Curve Distance)", 10.0)

    def make(self, obj, shapes):
        return Part.Vertex(core.point(obj.Type, shapes, obj.Distance.Value, obj.Flip))


class RefCSysProxy(_RefGeomProxy):
    KIND = "csys"
    TYPES = core.CSYS_TYPES
    LABEL = "Coordinate System"

    def setup(self, obj):
        super(RefCSysProxy, self).setup(obj)
        a = util.add_prop
        a(obj, "App::PropertyBool", "FlipX", "Reference", "Reverse the X direction", False)
        a(obj, "App::PropertyBool", "FlipY", "Reference", "Reverse the Y direction", False)

    def resolved(self, obj, warns):
        # Every reference is optional: keep their places (origin, X, Y).
        out = []
        for i in (1, 2, 3):
            s, w = refs.get_ref(obj, "Reference%d" % i, "reference %d" % i, obj.BaseFeature)
            if w:
                warns.append(w)
            out.append(s)
        return out

    def make(self, obj, shapes):
        part = util.part_of(obj)
        origin = None
        if part is not None:
            pt = part_mod.origin_feature(part, "Origin")
            if pt is not None and not pt.Shape.isNull() and pt.Shape.Vertexes:
                origin = pt.Shape.Vertexes[0].Point
        pl = core.csys(shapes, obj.FlipX, obj.FlipY, obj.Flip, origin)
        bb = self.model_size(obj)
        size = max(5.0, 0.25 * bb.DiagonalLength) if bb is not None else 10.0
        # Part::Feature places its Shape at its Placement: sketches attach to it.
        if not obj.Placement.isSame(pl, 1e-12):
            obj.Placement = pl
        return core.csys_shape(size)


class HelixProxy(_RefGeomProxy):
    """Helix/Spiral (SolidWorks' Insert > Curve > Helix/Spiral): a curve in the
    history, made from a circle (a sketch with one circle, or a circular edge).
    Sweep uses it as a path."""
    KIND = "helix"
    TYPES = curves.HELIX_TYPES
    LABEL = "Helix/Spiral"

    def setup(self, obj):
        super(HelixProxy, self).setup(obj)
        a = util.add_prop
        g = "Helix"
        a(obj, "App::PropertyLength", "Pitch", g, "Distance between turns", 5.0)
        a(obj, "App::PropertyFloat", "Revolutions", g, "Number of turns", 4.0)
        a(obj, "App::PropertyLength", "Height", g, "Height of the helix", 20.0)
        a(obj, "App::PropertyAngle", "StartAngle", g, "Where the first turn starts", 0.0)
        a(obj, "App::PropertyBool", "Clockwise", g,
          "Turn clockwise (a left-hand helix) instead of counterclockwise", False)
        a(obj, "App::PropertyBool", "TaperHelix", g, "Taper the helix", False)
        a(obj, "App::PropertyAngle", "TaperAngle", g, "Taper angle", 5.0)
        a(obj, "App::PropertyBool", "TaperOutward", g, "Taper outwards (wider at the end)",
          False)

    def axis_line(self, obj):
        """(start, end) of the helix's axis, for a sweep along it; None when unknown."""
        try:
            s, _w = refs.get_ref(obj, "Reference1", "circle", obj.BaseFeature)
            c, _r, a, _x = curves.circle_of(s)
            _p, _n, h = curves.numbers(obj.Type, obj.Pitch.Value, obj.Revolutions,
                                       obj.Height.Value)
        except Exception:
            return None
        if obj.Type == curves.SPIRAL:
            return None
        z = -a if obj.Flip else a
        return c, c + z * h

    def make(self, obj, shapes):
        if not shapes or shapes[0] is None:
            raise topo.GeometryError("Pick a circle: a sketch with one circle, or a circular "
                                     "edge.")
        taper = 0.0
        if obj.TaperHelix:
            taper = obj.TaperAngle.Value if obj.TaperOutward else -obj.TaperAngle.Value
        return curves.helix(shapes[0], obj.Type, obj.Pitch.Value, obj.Revolutions,
                            obj.Height.Value, obj.Flip, obj.StartAngle.Value, obj.Clockwise,
                            taper)


def _base_bodies(obj):
    """The bodies just before a piece of reference geometry."""
    from ..core.bodies import BodySet
    base = obj.BaseFeature
    if base is None or "BodyIds" not in base.PropertiesList:
        return BodySet()
    return BodySet.from_columns(base.Shape, list(base.BodyIds), list(base.BodyKinds),
                                list(base.BodyFeatures))


class _MeasuredProxy(_RefGeomProxy):
    """Reference geometry measured from the bodies (Bounding Box, Center of Mass):
    it follows them as they change."""
    PANEL = None
    ICON = None

    def setup(self, obj):
        super(_MeasuredProxy, self).setup(obj)
        a = util.add_prop
        a(obj, "App::PropertyStringList", "Bodies", "Reference",
          "The bodies it measures, by ID (empty: every solid body)")
        for i in (2, 3):
            util.hide_prop(obj, "Reference%d" % i)
        util.hide_prop(obj, "Flip")

    def bodies(self, obj, surfaces=False):
        from ..core.bodies import SOLID
        bs = _base_bodies(obj)
        want = [i for i in obj.Bodies if i]
        missing = [i for i in want if i not in bs]
        if missing:
            raise topo.GeometryError("A body it measures no longer exists. Pick the bodies "
                                     "again.")
        out = []
        for b in bs:
            if want and b.id not in want:
                continue
            if b.kind == SOLID or surfaces:
                out.append(b.shape)
        return out


class BoundingBoxProxy(_MeasuredProxy):
    """SolidWorks' Bounding Box: the smallest box round the bodies (Best Fit), or one
    square to a reference plane. Its sizes are read-only properties."""
    KIND = "bbox"
    TYPES = core.BOX_TYPES
    LABEL = "Bounding Box"
    PANEL = "bbox"
    ICON = "BoundingBox"

    def setup(self, obj):
        super(BoundingBoxProxy, self).setup(obj)
        a = util.add_prop
        g = "Reference"
        a(obj, "App::PropertyBool", "IncludeSurfaces", g, "Put the surface bodies in it too",
          False)
        g = "Size"
        a(obj, "App::PropertyLength", "Length", g, "The box's longest side", 0.0)
        a(obj, "App::PropertyLength", "Width", g, "The box's middle side", 0.0)
        a(obj, "App::PropertyLength", "Thickness", g, "The box's shortest side", 0.0)
        a(obj, "App::PropertyVolume", "BoxVolume", g, "The box's volume", 0.0)
        for p in ("Length", "Width", "Thickness", "BoxVolume"):
            util.readonly_prop(obj, p)

    def make(self, obj, shapes):
        plane = shapes[0] if shapes else None
        if obj.Type != core.REFERENCE_PLANE:
            plane = None
        pl, size = core.bounding_box(self.bodies(obj, obj.IncludeSurfaces), obj.Type, plane)
        l, w, t = sorted(size, reverse=True)
        for p, v in (("Length", l), ("Width", w), ("Thickness", t),
                     ("BoxVolume", l * w * t)):
            if abs(getattr(obj, p).Value - v) > 1e-9:
                setattr(obj, p, v)
        return core.box_edges(pl, size)


class CenterOfMassProxy(_MeasuredProxy):
    """SolidWorks' Center of Mass: a point at the solid bodies' centre of mass (one
    density), usable wherever a point is."""
    KIND = "point"
    TYPES = ["Center of Mass"]
    LABEL = "Center of Mass"
    PANEL = "com"
    ICON = "CenterOfMass"

    def setup(self, obj):
        super(CenterOfMassProxy, self).setup(obj)
        util.hide_prop(obj, "Reference1")
        util.hide_prop(obj, "Type")

    def make(self, obj, shapes):
        return Part.Vertex(core.centre_of_mass([s for sh in self.bodies(obj) for s in sh.Solids]))


class CosmeticThreadProxy(_RefGeomProxy):
    """SolidWorks' Cosmetic Thread: a thread shown on a shaft or in a hole without
    modelling it. It draws the thread's minor (shaft) or major (hole) diameter as
    dashed lines, and carries the callout."""
    KIND = "cosmetic"
    TYPES = ["Blind", "Up To Next"]
    LABEL = "Cosmetic Thread"
    PANEL = "cosmetic"
    ICON = "CosmeticThread"

    def setup(self, obj):
        super(CosmeticThreadProxy, self).setup(obj)
        from ..core import threads
        a = util.add_prop
        g = "Thread"
        a(obj, "App::PropertyEnumeration", "Series", g, "Thread standard and series",
          enum=threads.SERIES)
        a(obj, "App::PropertyString", "Size", g, "Thread size (empty: the nearest one)", "")
        a(obj, "App::PropertyLength", "Length", g, "Thread length (Blind)", 10.0)
        a(obj, "App::PropertyString", "ThreadClass", g, "Tolerance class, for the callout", "")
        a(obj, "App::PropertyLength", "Diameter", g,
          "The diameter shown: the minor diameter on a shaft, the major one in a hole", 0.0)
        a(obj, "App::PropertyString", "Callout", g, "The thread's callout", "")
        for p in ("Reference2", "Reference3"):
            util.hide_prop(obj, p)
        for p in ("Diameter", "Callout"):
            util.readonly_prop(obj, p)

    def make(self, obj, shapes):
        from ..core import threads
        from ..core.features import thread as core_thread
        if not shapes or shapes[0] is None or not shapes[0].Edges:
            raise topo.GeometryError("Pick the circular edge where the thread starts: a "
                                     "shaft's end or a hole's rim.")
        edge = shapes[0].Edges[0]
        site = core_thread.site(_base_bodies(obj), edge, obj.Flip)
        size = obj.Size
        if size not in threads.sizes(obj.Series):
            size = threads.nearest(obj.Series, 2 * site.radius, site.internal)
            obj.Size = size
        major, pitch, _tap = threads.spec(obj.Series, size)
        shown = major if site.internal else threads.minor(major, pitch)
        if obj.Type == "Blind":
            length = obj.Length.Value
        else:
            length = _cylinder_length(_base_bodies(obj), site)
        if length <= 1e-6:
            raise topo.GeometryError("The thread has no length.")
        cls = (" - " + obj.ThreadClass.strip()) if obj.ThreadClass.strip() else ""
        callout = u"{}{}  \u2193 {:g} mm".format(size, cls, round(length, 4))
        if obj.Callout != callout:
            obj.Callout = callout
        if abs(obj.Diameter.Value - shown) > 1e-9:
            obj.Diameter = shown
        return core.cosmetic_thread(site.centre, site.axis, shown / 2.0, length)


def _cylinder_length(bodies, site):
    """How far the cylindrical face goes from the edge along the thread's axis."""
    b = bodies.get(site.bid)
    best = 0.0
    for f in b.shape.Faces:
        s = f.Surface
        if s.TypeId != "Part::GeomCylinder" or abs(s.Radius - site.radius) > 1e-6:
            continue
        if abs(abs(s.Axis.dot(site.axis)) - 1) > 1e-6:
            continue
        if (s.Center - site.centre).cross(site.axis).Length > 1e-6:
            continue
        for v in f.Vertexes:
            best = max(best, (v.Point - site.centre).dot(site.axis))
        for e in f.Edges:
            try:
                best = max(best, (e.Curve.Center - site.centre).dot(site.axis))
            except AttributeError:
                pass
    return best


def _create(cls, doc, part, name, kind=None, references=()):
    obj = doc.addObject("Part::FeaturePython", name)
    cls(obj)
    if kind:
        obj.Type = kind
    obj.AutoLabel = util.set_label(obj, cls.LABEL)
    part_mod.add_to_part(part, obj)
    for i, ref in enumerate(references, 1):
        if ref is not None:
            target, sub = ref
            refs.set_ref(obj, "Reference%d" % i, target, sub)
    if App.GuiUp:
        from ..gui import viewproviders
        viewproviders.attach_refgeom(obj)
    return obj


def create_plane(doc, part, kind=None, references=()):
    """``references``: [(object, sub-element name or "")] in the type's order."""
    return _create(RefPlaneProxy, doc, part, "Plane", kind, references)


def create_axis(doc, part, kind=None, references=()):
    return _create(RefAxisProxy, doc, part, "Axis", kind, references)



def create_point(doc, part, kind=None, references=()):
    return _create(RefPointProxy, doc, part, "Point", kind, references)


def create_csys(doc, part, kind=None, references=()):
    """``references``: [origin point, X direction, Y direction], each optional
    (None keeps its place)."""
    return _create(RefCSysProxy, doc, part, "CoordinateSystem", kind, references)


def create_bounding_box(doc, part, kind=None, references=(), bodies=()):
    obj = _create(BoundingBoxProxy, doc, part, "BoundingBox", kind, references)
    if bodies:
        obj.Bodies = list(bodies)
    return obj


def create_centre_of_mass(doc, part, bodies=()):
    obj = _create(CenterOfMassProxy, doc, part, "CenterOfMass")
    if bodies:
        obj.Bodies = list(bodies)
    return obj


def create_cosmetic_thread(doc, part, edge=None, **props):
    """``edge``: (object, "EdgeN") or None."""
    obj = _create(CosmeticThreadProxy, doc, part, "CosmeticThread", None,
                  [edge] if edge is not None else [])
    for k, v in props.items():
        setattr(obj, k, v)
    return obj


def create_helix(doc, part, kind=None, references=()):
    """``references``: [(sketch, "") or (object, "EdgeN")] — the circle."""
    return _create(HelixProxy, doc, part, "Helix", kind, references)


# ------------------------------------------------------------------ Insert > Curve

class _CurveProxy(_RefGeomProxy):
    """A curve in the history (a sweep path, a guide curve, a curve to pattern
    along). Its own properties hold what it is built from."""
    KIND = "curve"
    TYPES = ["Curve"]
    LABEL = "Curve"
    CURVE = "curve"             # which curve tool: the panel and the icon

    def setup(self, obj):
        super(_CurveProxy, self).setup(obj)
        for i in (1, 2, 3):
            util.hide_prop(obj, "Reference%d" % i)
        util.hide_prop(obj, "Flip")

    def resolved(self, obj, warns):
        self._warns = warns
        return []

    def elems(self, obj, prop, what):
        val = getattr(obj, prop)
        if not val or val[0] is None:
            return []
        shapes, w = refs.get_refs(obj, prop, what, obj.BaseFeature)
        getattr(self, "_warns", []).extend(w)
        return shapes


class ProjectedCurveProxy(_CurveProxy):
    TYPES = curves.PROJECTED_TYPES
    CURVE = "projected"
    LABEL = "Curve"

    def setup(self, obj):
        super(ProjectedCurveProxy, self).setup(obj)
        a = util.add_prop
        g = "Projected Curve"
        a(obj, "App::PropertyLink", "Sketch", g, "The sketch to project")
        a(obj, "App::PropertyLink", "Sketch2", g, "Sketch on sketch: the second sketch")
        a(obj, "App::PropertyLinkSub", "Faces", g, "Sketch on faces: the faces to land on")
        a(obj, "App::PropertyBool", "ReverseDirection", g, "Project the other way", False)
        a(obj, "App::PropertyBool", "Bidirectional", g, "Project both ways", False)

    def make(self, obj, _shapes):
        from ..core import regions
        if obj.Sketch is None:
            raise topo.GeometryError("Pick the sketch to project.")
        c1 = topo.shape_of(obj.Sketch)
        n1 = regions.sketch_normal(obj.Sketch)
        if obj.Type == curves.ON_SKETCH:
            if obj.Sketch2 is None:
                raise topo.GeometryError("Pick the second sketch.")
            return curves.sketch_on_sketch(c1, n1, topo.shape_of(obj.Sketch2),
                                           regions.sketch_normal(obj.Sketch2))
        faces = self.elems(obj, "Faces", "face to project onto")
        d = -n1 if obj.ReverseDirection else n1
        return curves.projected_on_faces(c1, faces, d, obj.Bidirectional)


class CompositeCurveProxy(_CurveProxy):
    CURVE = "composite"
    LABEL = "CompCurve"

    def setup(self, obj):
        super(CompositeCurveProxy, self).setup(obj)
        a = util.add_prop
        g = "Composite Curve"
        a(obj, "App::PropertyLinkSub", "Edges", g, "Model edges to join")
        a(obj, "App::PropertyLinkList", "Curves", g, "Sketches and curves to join")

    def make(self, obj, _shapes):
        edges = [e for s in self.elems(obj, "Edges", "edge to join") for e in s.Edges]
        for o in obj.Curves:
            if o is not None:
                edges.extend(topo.shape_of(o).Edges)
        return curves.composite(edges)


class XYZCurveProxy(_CurveProxy):
    CURVE = "xyz"
    LABEL = "Curve"

    def setup(self, obj):
        super(XYZCurveProxy, self).setup(obj)
        a = util.add_prop
        g = "Curve Through XYZ Points"
        a(obj, "App::PropertyStringList", "Points", g, "The points, as X,Y,Z, in order")
        a(obj, "App::PropertyBool", "Closed", g, "Close the curve back to its start", False)

    def make(self, obj, _shapes):
        pts = []
        for t in obj.Points:
            try:
                x, y, z = (float(v) for v in t.split(","))
            except Exception:
                raise topo.GeometryError("Row \"{}\" isn't X,Y,Z.".format(t))
            pts.append(App.Vector(x, y, z))
        return curves.through_points(pts, obj.Closed)


class PointsCurveProxy(_CurveProxy):
    CURVE = "points"
    LABEL = "Curve"

    def setup(self, obj):
        super(PointsCurveProxy, self).setup(obj)
        a = util.add_prop
        g = "Curve Through Reference Points"
        a(obj, "App::PropertyLinkSub", "Vertices", g, "Model vertices, in order")
        a(obj, "App::PropertyLinkList", "PointObjects", g, "Reference points, after the vertices")
        a(obj, "App::PropertyBool", "Closed", g, "Close the curve back to its start", False)

    def make(self, obj, _shapes):
        pts = [s.Vertexes[0].Point for s in self.elems(obj, "Vertices", "point")]
        for o in obj.PointObjects:
            if o is not None:
                sh = topo.shape_of(o)
                if sh.Vertexes:
                    pts.append(sh.Vertexes[0].Point)
        return curves.through_points(pts, obj.Closed)


def _create_curve(cls, doc, part, name, **props):
    obj = doc.addObject("Part::FeaturePython", name)
    cls(obj)
    obj.AutoLabel = util.set_label(obj, cls.LABEL)
    part_mod.add_to_part(part, obj)
    for k, v in props.items():
        if k.startswith("_ref_"):
            refs.set_ref(obj, k[5:], v[0], v[1])
        else:
            setattr(obj, k, v)
    if App.GuiUp:
        from ..gui import viewproviders
        viewproviders.attach_refgeom(obj)
    return obj


def create_projected_curve(doc, part, **props):
    return _create_curve(ProjectedCurveProxy, doc, part, "ProjectedCurve", **props)


def create_composite_curve(doc, part, **props):
    return _create_curve(CompositeCurveProxy, doc, part, "CompositeCurve", **props)


def create_xyz_curve(doc, part, **props):
    return _create_curve(XYZCurveProxy, doc, part, "XYZCurve", **props)


def create_points_curve(doc, part, **props):
    return _create_curve(PointsCurveProxy, doc, part, "PointsCurve", **props)
