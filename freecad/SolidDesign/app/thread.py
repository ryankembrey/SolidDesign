# SPDX-License-Identifier: LGPL-2.1-or-later
"""Thread document object (SolidWorks' Thread)."""

import FreeCAD as App

from ..core import threads, topo
from ..core.features import thread as core
from . import feature, part as part_mod, refs, util


class ThreadProxy(feature.FeatureProxy):
    TYPE = "Thread"
    LABELS = ("Thread",)

    def setup(self, obj):
        super(ThreadProxy, self).setup(obj)
        a = util.add_prop
        g = "Thread Location"
        a(obj, "App::PropertyLinkSub", "Edge", g, "The circular edge the thread starts at")
        a(obj, "App::PropertyBool", "Offset", g, "Start the thread away from the edge", False)
        a(obj, "App::PropertyLength", "OffsetDistance", g, "How far from the edge", 0.0)
        a(obj, "App::PropertyBool", "ReverseOffset", g, "Offset the other way", False)
        g = "End Condition"
        a(obj, "App::PropertyEnumeration", "EndCondition", g, "How long the thread is",
          enum=core.END_CONDITIONS)
        a(obj, "App::PropertyLength", "Length", g, "Thread length (Blind)", 10.0)
        a(obj, "App::PropertyFloat", "Revolutions", g, "Number of turns (Revolutions)", 5.0)
        a(obj, "App::PropertyLinkSub", "UpTo", g, "Face, plane or vertex (Up To Selection)")
        a(obj, "App::PropertyBool", "ReverseDirection", g,
          "Thread the other way along the cylinder from the edge", False)
        g = "Specification"
        a(obj, "App::PropertyEnumeration", "Series", g, "Thread standard and series",
          enum=threads.SERIES)
        a(obj, "App::PropertyString", "Size", g, "Thread size (empty: the nearest one)", "")
        a(obj, "App::PropertyBool", "OverridePitch", g, "Use your own pitch", False)
        a(obj, "App::PropertyLength", "Pitch", g, "Pitch (Override pitch)", 1.0)
        a(obj, "App::PropertyEnumeration", "Method", g, "Cut the groove or grow the ridge",
          enum=core.METHODS)
        g = "Thread Options"
        a(obj, "App::PropertyBool", "LeftHand", g, "Left-hand thread", False)
        a(obj, "App::PropertyInteger", "Starts", g, "Number of starts", 1)

    def compute(self, obj, base):
        warns = []
        p = core.Params()
        edges, w = refs.get_refs(obj, "Edge", "thread edge", obj.BaseFeature)
        warns.extend(w)
        if not edges:
            raise topo.GeometryError("Pick the circular edge where the thread starts: a "
                                     "shaft's end or a hole's rim.")
        e = edges[0]
        p.edge = e if e.ShapeType == "Edge" else e.Edges[0]
        p.offset = obj.OffsetDistance.Value if obj.Offset else 0.0
        p.reverse_offset = obj.ReverseOffset
        p.end = obj.EndCondition
        p.length = obj.Length.Value
        p.revolutions = obj.Revolutions
        if p.end == core.UP_TO:
            s, w = refs.get_ref(obj, "UpTo", "end face", obj.BaseFeature)
            warns.append(w)
            p.up_to = s
        p.reverse = obj.ReverseDirection
        p.method = obj.Method
        p.left_hand = obj.LeftHand
        p.starts = obj.Starts
        p.feature = obj.Name
        p.tag = obj.ID
        # The size: as picked, or the nearest to the cylinder.
        site = core.site(base, p.edge, p.reverse)
        size = obj.Size
        if size not in threads.sizes(obj.Series):
            size = threads.nearest(obj.Series, 2 * site.radius, site.internal)
            obj.Size = size
        major, pitch, _tap = threads.spec(obj.Series, size)
        p.pitch = obj.Pitch.Value if obj.OverridePitch else pitch
        if not obj.OverridePitch and abs(obj.Pitch.Value - pitch) > 1e-9:
            obj.Pitch = pitch       # shown (greyed) in the panel; overriding starts from it
        res, tool, s = core.compute(p, base)
        nominal = major if not s.internal else _tap
        if abs(2 * s.radius - nominal) > 0.25 * pitch:
            warns.append("The {} ({:.2f} mm) doesn't match {} ({} {:g} mm); the thread "
                         "follows the cylinder.".format(
                             "hole" if s.internal else "shaft", 2 * s.radius, size,
                             "tap drill" if s.internal else "major diameter", nominal))
        res.warnings.extend(x for x in warns if x)
        return res, tool


def create(doc, part, edge=None):
    """A new Thread at the rollback bar; ``edge``: (object, "EdgeN") or None."""
    obj = doc.addObject("Part::FeaturePython", "Thread")
    ThreadProxy(obj)
    obj.AutoLabel = util.set_label(obj, ThreadProxy.LABELS[0])
    part_mod.insert_feature(part, obj)
    if edge is not None:
        refs.set_ref(obj, "Edge", edge[0], edge[1])
    if App.GuiUp:
        from ..gui import viewproviders
        viewproviders.attach_feature(obj)
    return obj
