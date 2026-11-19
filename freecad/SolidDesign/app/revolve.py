# SPDX-License-Identifier: LGPL-2.1-or-later
"""Revolve document object: one feature, an Add or Cut mode (spec 3.1).

The axis is a link: (sketch, "AxisN") for the sketch's N-th centerline (1-based:
FreeCAD normalizes element names, so "Axis0" would be stored as "Axis"),
(sketch, "H_Axis"/"V_Axis"), (sketch, "EdgeN") for a sketch line, a datum or
origin axis, or a straight edge of the model before the feature.
"""

import FreeCAD as App

from ..core import refgeom as core_ref
from ..core import regions, topo
from ..core.features import revolve as core
from . import refs, sketchfeature, util


class RevolveProxy(sketchfeature.SketchFeatureProxy):
    TYPE = "Revolve"
    LABELS = ("Revolve", "Cut-Revolve", "Surface-Revolve")

    def setup(self, obj):
        super(RevolveProxy, self).setup(obj)
        a = util.add_prop
        g = "Revolve"
        a(obj, "App::PropertyLinkSub", "Axis", g, "Axis of revolution")
        a(obj, "App::PropertyBool", "Reverse", g, "Reverse Direction", False)
        for n, label in (("", "Direction 1"), ("2", "Direction 2")):
            g = label
            if n:
                a(obj, "App::PropertyBool", "Direction2", g, "Revolve the other way too", False)
            a(obj, "App::PropertyEnumeration", "EndCondition" + n, g, "End condition",
              enum=core.END_CONDITIONS if not n else core.END_CONDITIONS_2)
            a(obj, "App::PropertyAngle", "Angle" + n, g, "Angle", 360.0 if not n else 30.0)
            a(obj, "App::PropertyLinkSub", "UpToFace" + n, g, "Face or plane to revolve up to")
            a(obj, "App::PropertyLinkSub", "UpToVertex" + n, g, "Vertex to revolve up to")
            a(obj, "App::PropertyLength", "Offset" + n, g, "Offset From Surface distance", 0.0)
            a(obj, "App::PropertyBool", "ReverseOffset" + n, g, "Reverse offset", False)

    # ------------------------------------------------------------------ axis
    def axis(self, obj, warns):
        """(point, unit direction) of the axis, in global coordinates."""
        val = obj.Axis
        if not val or val[0] is None:
            raise topo.GeometryError("Pick an axis of revolution: a centerline, a line, an "
                                     "axis or a straight edge.")
        target, subs = val
        sub = subs[0] if subs else ""
        if target.TypeId.startswith("Sketcher::SketchObject") and (
                sub.startswith("Axis") or sub in ("H_Axis", "V_Axis")):
            pl = regions.sketch_placement(target)
            if sub == "H_Axis":
                p, d = App.Vector(), App.Vector(1, 0, 0)
            elif sub == "V_Axis":
                p, d = App.Vector(), App.Vector(0, 1, 0)
            else:
                try:
                    ax = target.getAxis(int(sub[4:]) - 1)
                except Exception:
                    raise topo.GeometryError("The centerline used as the axis no longer exists "
                                             "in {}. Pick the axis again.".format(target.Label))
                p, d = ax.Base, ax.Direction
            point = pl.multVec(p)
            d = pl.Rotation.multVec(d)
            d.normalize()
            return point, d
        shape, warn = refs.get_ref(obj, "Axis", "axis of revolution", obj.BaseFeature)
        warns.append(warn)
        # A straight line or edge, an axis, or a round face or circular edge (its
        # axis, the temporary axis SolidWorks shows).
        return core_ref.line_of(shape, "axis of revolution")

    def _extent(self, obj, n, warns):
        e = core.Extent()
        e.condition = getattr(obj, "EndCondition" + n)
        e.angle = getattr(obj, "Angle" + n).Value
        e.offset = getattr(obj, "Offset" + n).Value
        e.reverse_offset = getattr(obj, "ReverseOffset" + n)
        if e.condition in (core.UP_TO_SURFACE, core.OFFSET_FROM_SURFACE):
            e.face = self.face_ref(obj, "UpToFace" + n, "Up To Surface face", warns)
        elif e.condition == core.UP_TO_VERTEX:
            e.vertex = self.vertex_ref(obj, "UpToVertex" + n, "Up To Vertex vertex", warns)
        return e

    def compute(self, obj, base):
        warns = []
        p = core.Params()
        p.mode = obj.Mode
        p.tag = obj.ID
        p.feature = obj.Name
        p.faces, p.open_wires = self.profile(obj, warns)
        p.axis_point, p.axis_dir = self.axis(obj, warns)
        p.reverse = obj.Reverse
        p.dir1 = self._extent(obj, "", warns)
        if obj.Direction2 and obj.EndCondition != core.MID_PLANE:
            p.dir2 = self._extent(obj, "2", warns)
        p.thin = self.thin(obj)
        p.merge, p.scope, p.keep, p.flip, p.alloc = self.bodies_options(obj, base, warns)
        res, tool, preview = core.compute(p, base)
        self.finish(obj, res, p.alloc, warns, tool)
        return res, preview


def default_axis(sketch):
    """SolidWorks uses the sketch's centerline when there is exactly one."""
    if sketch is None:
        return None
    try:
        n = sketch.AxisCount
    except Exception:
        n = 0
    if n == 1:
        return "Axis1"
    return None


def create(doc, part, mode="Add", sketch=None):
    obj = sketchfeature.create(RevolveProxy, doc, part, mode, sketch, "Revolve")
    ax = default_axis(sketch)
    if ax:
        obj.Axis = (sketch, [ax])
    return obj
