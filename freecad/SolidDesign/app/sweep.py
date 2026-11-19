# SPDX-License-Identifier: LGPL-2.1-or-later
"""Sweep and Loft document objects (Add | Cut)."""

import Part

from ..core import regions, skin, topo
from ..core.features import sweep as core
from . import refs, sketchfeature, util


def _enum(obj, prop, values):
    """Keep an enumeration's choices current (older files lack new ones)."""
    if list(obj.getEnumerationsOfProperty(prop)) != list(values):
        old = getattr(obj, prop)
        setattr(obj, prop, list(values))
        if old in values:
            setattr(obj, prop, old)


def guides_of(objs):
    """Guide curves from sketches (each connected chain is one guide) or helices."""
    out = []
    for o in objs:
        if o is None:
            continue
        edges = [e for e in topo.shape_of(o).Edges]
        if not edges:
            raise topo.GeometryError("{} has no curves to guide with.".format(o.Label))
        try:
            chains = Part.sortEdges(edges)
        except Exception:
            chains = [edges]
        for k, ch in enumerate(chains):
            label = o.Label if len(chains) == 1 else "{} (curve {})".format(o.Label, k + 1)
            out.append(skin.Guide(Part.Wire(ch), label))
    return out


class SweepProxy(sketchfeature.SketchFeatureProxy):
    TYPE = "Sweep"
    LABELS = ("Sweep", "Cut-Sweep", "Surface-Sweep")

    def setup(self, obj):
        super(SweepProxy, self).setup(obj)
        a = util.add_prop
        g = "Sweep"
        a(obj, "App::PropertyEnumeration", "ProfileType", g, "Sketch or circular profile",
          enum=core.PROFILE_TYPES)
        a(obj, "App::PropertyLength", "Diameter", g, "Circular profile diameter", 5.0)
        a(obj, "App::PropertyLinkSub", "Path", g, "Path: a sketch, or connected edges")
        a(obj, "App::PropertyEnumeration", "Orientation", g, "Profile orientation",
          enum=core.ORIENTATIONS)
        a(obj, "App::PropertyString", "ToolBody", g, "Solid profile: the tool body, by ID")
        _enum(obj, "ProfileType", core.PROFILE_TYPES)
        g = "Twist"
        a(obj, "App::PropertyEnumeration", "ProfileTwist", g, "How the profile twists",
          enum=core.TWISTS)
        a(obj, "App::PropertyEnumeration", "TwistControl", g, "Twist in degrees or turns",
          enum=core.TWIST_UNITS)
        a(obj, "App::PropertyAngle", "TwistAngle", g, "Twist along the path", 90.0)
        a(obj, "App::PropertyFloat", "Turns", g, "Turns along the path", 1.0)
        a(obj, "App::PropertyBool", "ReverseTwist", g, "Twist the other way", False)
        g = "Guide Curves"
        a(obj, "App::PropertyLinkList", "GuideCurves", g,
          "Sketches whose curves the profile follows (it must touch them)")
        g = "Start/End Tangency"
        a(obj, "App::PropertyEnumeration", "StartTangency", g, "Start tangency",
          enum=core.SWEEP_TANGENCY)
        a(obj, "App::PropertyEnumeration", "EndTangency", g, "End tangency",
          enum=core.SWEEP_TANGENCY)

    def path(self, obj, warns):
        val = obj.Path
        if not val or val[0] is None:
            raise topo.GeometryError("Pick a path: a sketch, or connected edges.")
        target, subs = val
        if not subs and util.role(target) == "refgeom" and target.Proxy.KIND == "helix":
            self._axis = target.Proxy.axis_line(target)
        if not subs:
            edges = topo.shape_of(target).Edges
        else:
            elems, w = refs.get_refs(obj, "Path", "path edge", obj.BaseFeature)
            warns.extend(w)
            edges = [e for el in elems for e in el.Edges]
        return core.path_wire(edges)

    def compute(self, obj, base):
        warns = []
        p = core.SweepParams()
        p.mode = obj.Mode
        p.tag = obj.ID
        p.feature = obj.Name
        p.profile_type = obj.ProfileType
        p.diameter = obj.Diameter.Value
        p.orientation = obj.Orientation
        if p.profile_type == core.SKETCH_PROFILE:
            p.faces, p.open_wires = self.profile(obj, warns)
        self._axis = None
        p.path = self.path(obj, warns)
        p.axis = self._axis
        p.thin = self.thin(obj)
        p.twist = obj.ProfileTwist
        if obj.TwistControl == core.TURNS:
            p.twist_angle = obj.Turns * 360.0
        else:
            p.twist_angle = obj.TwistAngle.Value
        if obj.ReverseTwist:
            p.twist_angle = -p.twist_angle
        if p.profile_type != core.SOLID_PROFILE:
            p.guides = guides_of(obj.GuideCurves)
        p.start_tangent = obj.StartTangency == core.PATH_TANGENT
        p.end_tangent = obj.EndTangency == core.PATH_TANGENT
        if p.profile_type == core.SOLID_PROFILE:
            if not obj.ToolBody:
                raise topo.GeometryError("Pick the tool body: a body of revolution.")
            b = base.get(obj.ToolBody)
            if b is None:
                raise topo.GeometryError("The tool body no longer exists. Pick it again.")
            p.tool_body = b.shape
        p.merge, p.scope, p.keep, p.flip, p.alloc = self.bodies_options(obj, base, warns)
        if p.profile_type == core.SOLID_PROFILE:
            p.scope.exclude.append(obj.ToolBody)    # the tool body isn't cut by itself
        p.base = base
        tool = core.sweep_tool(p)
        res, preview = core.compute(p, tool)
        self.finish(obj, res, p.alloc, warns, tool)
        return res, preview


class LoftProxy(sketchfeature.SketchFeatureProxy):
    TYPE = "Loft"
    LABELS = ("Loft", "Cut-Loft", "Surface-Loft")

    def setup(self, obj):
        super(LoftProxy, self).setup(obj)
        a = util.add_prop
        a(obj, "App::PropertyLinkList", "Profiles", "Loft",
          "Profiles in order: sketches, or a point at either end")
        a(obj, "App::PropertyBool", "Closed", "Loft", "Close the loft back to the first profile",
          False)
        util.hide_prop(obj, "Sketch")
        g = "Guide Curves"
        a(obj, "App::PropertyLinkList", "GuideCurves", g,
          "Sketches whose curves the loft follows (each must touch every profile)")
        a(obj, "App::PropertyEnumeration", "GuideInfluence", g,
          "To Next Edge: a guide shapes the faces beside it. To Next Guide: it blends to "
          "the next guide.", enum=skin.INFLUENCES)
        for end in ("Start", "End"):
            g = "Start/End Constraints"
            a(obj, "App::PropertyEnumeration", end + "Constraint", g,
              "{} constraint".format(end), enum=core.LOFT_TANGENCY)
            a(obj, "App::PropertyLinkSub", end + "Direction", g,
              "Direction vector: an edge, axis or plane (its normal)")
            a(obj, "App::PropertyFloat", end + "TangentLength", g,
              "How far the constraint reaches into the loft", 1.0)
            a(obj, "App::PropertyAngle", end + "DraftAngle", g,
              "Tilts the loft outwards (Normal To Profile)", 0.0)

    def section(self, o):
        shape = topo.shape_of(o)
        if not shape.Edges and len(shape.Vertexes) == 1:
            return shape.Vertexes[0]
        if o.TypeId.startswith("Sketcher::SketchObject"):
            faces, open_wires = regions.default_profile(o, 1)
            if faces is not None:
                if len(faces.Faces) != 1:
                    raise topo.GeometryError("{} has {} contours; a loft profile needs one."
                                             .format(o.Label, len(faces.Faces)))
                return faces.Faces[0]
            if len(open_wires) == 1:
                return open_wires[0]
        raise topo.GeometryError("{} can't be a loft profile.".format(o.Label))

    def direction(self, obj, prop, warns):
        val = getattr(obj, prop)
        if not val or val[0] is None:
            return None
        s, w = refs.get_ref(obj, prop, "direction vector", obj.BaseFeature)
        if w:
            warns.append(w)
        if s is None:
            return None
        from . import pattern
        return pattern.direction_of(s, "direction vector")[1]

    def compute(self, obj, base):
        warns = []
        p = core.LoftParams()
        p.mode = obj.Mode
        p.tag = obj.ID
        p.feature = obj.Name
        p.sections = [self.section(o) for o in obj.Profiles if o is not None]
        p.closed = obj.Closed
        p.guides = guides_of(obj.GuideCurves)
        p.influence = obj.GuideInfluence
        for end in ("start", "end"):
            E = end.capitalize()
            kind = getattr(obj, E + "Constraint")
            setattr(p, end, kind)
            setattr(p, end + "_length", getattr(obj, E + "TangentLength"))
            setattr(p, end + "_draft", getattr(obj, E + "DraftAngle").Value)
            if kind == core.DIRECTION_VECTOR:
                setattr(p, end + "_dir", self.direction(obj, E + "Direction", warns))
        p.merge, p.scope, p.keep, p.flip, p.alloc = self.bodies_options(obj, base, warns)
        p.base = base
        tool = core.loft_tool(p)
        res, preview = core.compute(p, tool)
        self.finish(obj, res, p.alloc, warns, tool)
        return res, preview


def create_sweep(doc, part, mode="Add", sketch=None):
    return sketchfeature.create(SweepProxy, doc, part, mode, sketch, "Sweep")


def create_loft(doc, part, mode="Add", sketch=None, profiles=()):
    obj = sketchfeature.create(LoftProxy, doc, part, mode, None, "Loft")
    profs = list(profiles) or ([sketch] if sketch is not None else [])
    if profs:
        from . import part as part_mod
        for s in profs:
            if s.TypeId.startswith("Sketcher::") and s not in part.Group:
                part_mod.add_to_part(part, s)
        obj.Profiles = profs
    return obj


class BoundaryProxy(LoftProxy):
    """Boundary (SolidWorks' Boundary Boss/Base and Boundary Cut): curves in one
    direction loft like a Loft; with curves in a second direction too, the shape
    passes through the whole network."""
    TYPE = "Boundary"
    LABELS = ("Boundary", "Boundary-Cut", "Boundary-Surface")

    def setup(self, obj):
        super(BoundaryProxy, self).setup(obj)
        util.add_prop(obj, "App::PropertyLinkList", "Direction2", "Boundary",
                      "Direction 2 curves: sketches crossing every Direction 1 curve")
        for p in ("GuideCurves", "GuideInfluence", "Closed"):
            util.hide_prop(obj, p)

    def compute(self, obj, base):
        if not [o for o in obj.Direction2 if o is not None]:
            return super(BoundaryProxy, self).compute(obj, base)
        warns = []
        from ..core.features import boundary as core_b
        p = core.LoftParams()
        p.mode = obj.Mode
        p.tag = obj.ID
        p.feature = obj.Name
        dir1 = []
        for o in obj.Profiles:
            if o is None:
                continue
            s = self.section(o)
            dir1.append(s.OuterWire if s.ShapeType == "Face" else s)
        if obj.StartConstraint != core.NO_TANGENCY or obj.EndConstraint != core.NO_TANGENCY:
            warns.append("With curves in both directions the network sets the shape; the "
                         "start/end constraints are not used.")
        dir2 = [g.sec.wire() for g in guides_of(obj.Direction2)]
        p.merge, p.scope, p.keep, p.flip, p.alloc = self.bodies_options(obj, base, warns)
        p.base = base
        tool = core_b.network(dir1, dir2, p.mode != "Surface", p.tag)
        res, preview = core.compute(p, tool)
        self.finish(obj, res, p.alloc, warns, tool)
        return res, preview


def create_boundary(doc, part, mode="Add", sketch=None, profiles=(), direction2=()):
    obj = sketchfeature.create(BoundaryProxy, doc, part, mode, None, "Boundary")
    profs = list(profiles) or ([sketch] if sketch is not None else [])
    from . import part as part_mod
    for s in profs + list(direction2):
        if s.TypeId.startswith("Sketcher::") and s not in part.Group:
            part_mod.add_to_part(part, s)
    if profs:
        obj.Profiles = profs
    if direction2:
        obj.Direction2 = list(direction2)
    return obj
