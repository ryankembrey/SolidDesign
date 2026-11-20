# SPDX-License-Identifier: LGPL-2.1-or-later
"""Hole Wizard document object.

Positions are the points of a sketch (and its circle centres, when it has no
points). Clicking a face in the panel adds a point to that sketch (making one on
the face if needed), so positions stay parametric and editable in the Sketcher.
The hole goes into the material: opposite the sketch's normal, or along it with
Reverse Direction.
"""

import FreeCAD as App

from ..core import regions, topo
from ..core.bodies import IdAllocator
from ..core.features import common
from ..core.features import hole as core
from . import feature, part as part_mod, refs, util


def sketch_points(sk):
    """Global positions: the sketch's points, else its circle centres."""
    pl = regions.sketch_placement(sk)
    pts, centres = [], []
    for i, g in enumerate(sk.Geometry):
        try:
            if sk.getConstruction(i):
                continue
        except Exception:
            pass
        t = g.TypeId
        if t == "Part::GeomPoint":
            pts.append(pl.multVec(App.Vector(g.X, g.Y, g.Z)))
        elif t in ("Part::GeomCircle", "Part::GeomArcOfCircle"):
            centres.append(pl.multVec(g.Center))
    return pts or centres


class HoleProxy(feature.FeatureProxy):
    TYPE = "Hole"
    LABELS = ("M6 Clearance Hole",)

    def setup(self, obj):
        super(HoleProxy, self).setup(obj)
        a = util.add_prop
        g = "Hole"
        a(obj, "App::PropertyEnumeration", "HoleType", g, "Hole type", enum=core.TYPES)
        a(obj, "App::PropertyEnumeration", "Standard", g, "Standard", enum=core.STANDARDS)
        a(obj, "App::PropertyEnumeration", "Size", g, "Size", enum=core.SIZES)
        a(obj, "App::PropertyEnumeration", "Fit", g, "Fit", enum=core.FITS)
        a(obj, "App::PropertyEnumeration", "EndCondition", g, "End condition",
          enum=core.END_CONDITIONS)
        a(obj, "App::PropertyLength", "Depth", g, "Blind depth", 15.0)
        a(obj, "App::PropertyAngle", "TipAngle", g, "Drill tip angle (0: flat)", 118.0)
        a(obj, "App::PropertyBool", "Reverse", g, "Reverse Direction", False)
        a(obj, "App::PropertyLinkSub", "UpTo", g,
          "Vertex, face or plane (Up To Vertex, Up To Surface, Offset From Surface)")
        a(obj, "App::PropertyLength", "OffsetDistance", g, "Offset From Surface distance", 1.0)
        g = "Slot"
        a(obj, "App::PropertyLength", "SlotLength", g, "Slot length, centre to centre", 10.0)
        a(obj, "App::PropertyAngle", "SlotAngle", g, "Slot direction from the sketch's X axis",
          0.0)
        g = "Thread"
        a(obj, "App::PropertyEnumeration", "ThreadOption", g,
          "Straight Tap: the tap drill, the thread's diameter, or a modelled thread",
          enum=core.THREAD_OPTIONS)
        a(obj, "App::PropertyLength", "ThreadDepth", g, "Thread depth (Blind)", 12.0)
        g = "Custom Sizing"
        a(obj, "App::PropertyBool", "CustomSizing", g, "Use your own dimensions", False)
        a(obj, "App::PropertyLength", "HoleDiameter", g, "Hole diameter", 6.6)
        a(obj, "App::PropertyLength", "CboreDiameter", g, "Counterbore diameter", 11.0)
        a(obj, "App::PropertyLength", "CboreDepth", g, "Counterbore depth", 6.4)
        a(obj, "App::PropertyLength", "CskDiameter", g, "Countersink diameter", 13.44)
        a(obj, "App::PropertyAngle", "CskAngle", g, "Countersink angle", 90.0)
        g = "Legacy"
        a(obj, "App::PropertyEnumeration", "LegacyType", g,
          "Legacy hole: Simple, Tapered, Counterbored, Countersunk or Counterdrilled",
          enum=core.LEGACY_TYPES)
        a(obj, "App::PropertyAngle", "TaperAngle", g, "Legacy Tapered: the wall's angle", 2.0)
        a(obj, "App::PropertyAngle", "CdrillAngle", g,
          "Legacy Counterdrilled: the cone from the counterdrill down to the hole", 118.0)
        g = "Options"
        a(obj, "App::PropertyBool", "NearSideCsk", g, "Near side countersink", False)
        a(obj, "App::PropertyLength", "NearCskDiameter", g, "Near side countersink diameter",
          10.0)
        a(obj, "App::PropertyAngle", "NearCskAngle", g, "Near side countersink angle", 90.0)
        a(obj, "App::PropertyBool", "FarSideCsk", g, "Far side countersink (Through All, Up To "
          "Next)", False)
        a(obj, "App::PropertyLength", "FarCskDiameter", g, "Far side countersink diameter", 10.0)
        a(obj, "App::PropertyAngle", "FarCskAngle", g, "Far side countersink angle", 90.0)
        a(obj, "App::PropertyBool", "HeadClearance", g, "Head clearance (Counterbore, "
          "Countersink)", False)
        a(obj, "App::PropertyLength", "HeadClearanceValue", g, "Head clearance", 1.0)
        g = "Advanced"
        a(obj, "App::PropertyStringList", "NearElements", g,
          "Advanced: near side elements from the face down, as Kind|Diameter|Depth|Angle")
        a(obj, "App::PropertyStringList", "FarElements", g,
          "Advanced: far side elements from the exit face up, as Kind|Diameter|Depth|Angle")
        a(obj, "App::PropertyLink", "Sketch", "Positions", "Sketch whose points place the holes")
        # So patterns and mirrors can repeat it (a hole only cuts).
        a(obj, "App::PropertyEnumeration", "Mode", "Result", "Holes always cut", enum=["Cut"])
        a(obj, "Part::PropertyPartShape", "ToolShape", "Result", "The holes' material")
        for p in ("Mode", "ToolShape"):
            util.hide_prop(obj, p)
        if obj.Size != "M6" and not obj.AutoLabel and obj.Standard == core.ISO_STD:
            obj.Size = "M6"
        if obj.Fit != "Normal" and not obj.AutoLabel:
            obj.Fit = "Normal"

    def onDocumentRestored(self, obj):
        super(HoleProxy, self).onDocumentRestored(obj)
        if "NearElements" not in obj.PropertiesList:      # files from before Advanced
            g = "Advanced"
            util.add_prop(obj, "App::PropertyStringList", "NearElements", g,
                          "Advanced: near side elements from the face down")
            util.add_prop(obj, "App::PropertyStringList", "FarElements", g,
                          "Advanced: far side elements from the exit face up")
        self._sizes(obj)

    def _sizes(self, obj):
        """The Size list follows the standard (and pipe sizes for Tapered Tap)."""
        want = core.sizes(obj.Standard, obj.HoleType)
        if list(obj.getEnumerationsOfProperty("Size")) != want:
            cur = obj.Size
            obj.Size = want
            obj.Size = cur if cur in want else ("M6" if "M6" in want else want[len(want) // 2])

    def default_label(self, obj):
        return core.label(obj.HoleType, obj.Size, obj.Standard)

    def onChanged(self, obj, prop):
        if prop in ("Standard", "HoleType") and "Size" in obj.PropertiesList:
            self._sizes(obj)
        if prop == "HoleType" and obj.HoleType == core.ADVANCED and \
                "NearElements" in obj.PropertiesList and not obj.NearElements:
            # Start from what the hole was: a counterbore over its clearance hole.
            obj.NearElements = [e.dumps() for e in core.default_elements(obj.Standard,
                                                                         obj.Size)]
        if prop in ("HoleType", "Size", "Standard") and "AutoLabel" in obj.PropertiesList and \
                obj.AutoLabel:
            if obj.Label == obj.AutoLabel:
                obj.AutoLabel = util.set_label(obj, self.default_label(obj))

    def compute(self, obj, base):
        sk = obj.Sketch
        if sk is None:
            raise topo.GeometryError("Pick where the holes go: a sketch with points, or click "
                                     "on a face.")
        warns = []
        p = core.Params()
        p.kind = obj.HoleType
        p.standard = obj.Standard
        p.size = obj.Size
        p.fit = obj.Fit
        p.thread = obj.ThreadOption
        if p.kind == core.ADVANCED:
            p.near = [core.Element.loads(t) for t in obj.NearElements]
            p.far = [core.Element.loads(t) for t in obj.FarElements]
        std = core.sizing(p.kind, p.standard, p.size, p.fit, p.thread)
        if p.kind == core.ADVANCED:
            pass
        elif p.kind == core.LEGACY:
            import math
            p.legacy = obj.LegacyType
            p.cdrill_angle = obj.CdrillAngle.Value
            lt = p.legacy
            cb = (obj.CboreDiameter.Value, obj.CboreDepth.Value) \
                if lt in (core.L_CBORE, core.L_CDRILL) else None
            csk = obj.CskDiameter.Value if lt == core.L_CSK else None
            taper = 2 * math.tan(math.radians(obj.TaperAngle.Value)) if lt == core.L_TAPERED \
                else 0.0
            if lt == core.L_TAPERED and not 0 < obj.TaperAngle.Value < 45:
                raise topo.GeometryError("The taper angle must be between 0° and 45°.")
            p.custom = core.Sizing(obj.HoleDiameter.Value, cb, csk, obj.CskAngle.Value,
                                   taper=taper)
        elif obj.CustomSizing:
            cb = (obj.CboreDiameter.Value, obj.CboreDepth.Value) if std.cbore else None
            csk = obj.CskDiameter.Value if std.csk else None
            p.custom = core.Sizing(obj.HoleDiameter.Value, cb, csk, obj.CskAngle.Value,
                                   std.pitch, std.major, std.taper)
        else:
            # Show the standard's values (greyed); Custom sizing starts from them.
            _set(obj, "HoleDiameter", std.d)
            if std.cbore:
                _set(obj, "CboreDiameter", std.cbore[0])
                _set(obj, "CboreDepth", std.cbore[1])
            if std.csk:
                _set(obj, "CskDiameter", std.csk)
            _set(obj, "CskAngle", std.csk_angle)
        p.end = obj.EndCondition
        p.depth = obj.Depth.Value
        p.tip_angle = obj.TipAngle.Value
        if p.end in (core.UP_TO_VERTEX, core.UP_TO_SURFACE, core.OFFSET_FROM_SURFACE):
            s, w = refs.get_ref(obj, "UpTo", "end face or vertex", obj.BaseFeature)
            warns.append(w)
            p.up_to = s
        p.offset = obj.OffsetDistance.Value
        p.slot_length = obj.SlotLength.Value
        p.slot_angle = obj.SlotAngle.Value
        p.thread_depth = obj.ThreadDepth.Value
        if obj.NearSideCsk and p.kind != core.ADVANCED:
            p.near_csk = (obj.NearCskDiameter.Value, obj.NearCskAngle.Value)
        if obj.FarSideCsk and p.kind != core.ADVANCED:
            if p.end not in (core.THROUGH_ALL, core.UP_TO_NEXT):
                warns.append("A far side countersink needs Through All or Up To Next.")
            else:
                p.far_csk = (obj.FarCskDiameter.Value, obj.FarCskAngle.Value)
        if obj.HeadClearance and p.kind in (core.COUNTERBORE, core.COUNTERSINK, core.CBORE_SLOT,
                                            core.CSK_SLOT):
            p.head_clearance = obj.HeadClearanceValue.Value
        p.points = sketch_points(sk)
        pl = regions.sketch_placement(sk)
        n = regions.sketch_normal(sk)
        p.direction = n if obj.Reverse else -n
        p.x_dir = pl.Rotation.multVec(App.Vector(1, 0, 0))
        p.feature = obj.Name
        p.tag = obj.ID
        p.alloc = IdAllocator(obj.Name, IdAllocator.loads(obj.IdMemory), taken=base.ids())
        res, tool, preview = core.compute(p, base, common.Scope())
        obj.ToolShape = tool
        mem = p.alloc.dumps()
        if obj.IdMemory != mem:
            obj.IdMemory = mem
        res.warnings.extend(x for x in warns if x)
        return res, preview


def _set(obj, prop, v):
    if abs(getattr(obj, prop).Value - v) > 1e-9:
        setattr(obj, prop, v)


def create(doc, part, sketch=None, **props):
    obj = doc.addObject("Part::FeaturePython", "Hole")
    HoleProxy(obj)
    for k in ("Standard", "HoleType"):      # the Size list follows these
        if k in props:
            setattr(obj, k, props.pop(k))
    for k, v in props.items():
        setattr(obj, k, v)
    obj.AutoLabel = util.set_label(obj, core.label(obj.HoleType, obj.Size, obj.Standard))
    if sketch is not None:
        obj.Sketch = sketch
    part_mod.insert_feature(part, obj, [sketch] if sketch is not None else [])
    if App.GuiUp:
        from ..gui import viewproviders
        viewproviders.attach_feature(obj)
    return obj
