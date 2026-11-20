# SPDX-License-Identifier: LGPL-2.1-or-later
"""Mounting Boss, Snap Hook, Lip/Groove and Vent (document objects)."""

import FreeCAD as App

from ..core import regions, topo
from ..core.features import fastening as core
from . import refs, util
from .surfaces import _SurfaceTool, _create, _vec, vec_text

__all__ = ["create_mounting_boss", "create_snap_hook", "create_lip_groove", "create_vent",
           "vec_text"]


def _face_and_point(obj, what):
    v = obj.Items
    if not v or v[0] is None:
        raise topo.GeometryError("Click on a face where the {} goes.".format(what))
    faces, warns = refs.get_refs(obj, "Items", "face", obj.BaseFeature)
    faces = [f for f in faces if f.ShapeType == "Face"]
    if not faces:
        raise topo.GeometryError("Click on a face where the {} goes.".format(what))
    f = faces[0]
    pt = _vec(obj.Position)
    if pt is None:
        pt = f.CenterOfMass
    # Onto the face (the click is on it; a moved model may have shifted it a little).
    try:
        pt = f.Surface.value(*f.Surface.parameter(pt))
    except Exception:
        pass
    return f, pt, warns


class _PlacedProxy(_SurfaceTool):
    def setup(self, obj):
        super(_PlacedProxy, self).setup(obj)
        a = util.add_prop
        g = "Position"
        a(obj, "App::PropertyLinkSub", "Items", g, "The face it stands on")
        a(obj, "App::PropertyString", "Position", g, "Where on the face (x,y,z)", "")
        a(obj, "App::PropertyBool", "ReverseDirection", g, "Stand the other way off the face",
          False)


class MountingBossProxy(_PlacedProxy):
    TYPE = "MountingBoss"
    LABELS = ("Mounting Boss",)

    def setup(self, obj):
        super(MountingBossProxy, self).setup(obj)
        a = util.add_prop
        g = "Boss"
        a(obj, "App::PropertyEnumeration", "BossType", g,
          "Hole: a hole down the boss (for a screw or insert). Pin: a pin on top",
          enum=core.BOSS_TYPES)
        a(obj, "App::PropertyLength", "Height", g, "Boss height, from the face", 10.0)
        a(obj, "App::PropertyLength", "Diameter", g, "Boss diameter at the face", 8.0)
        a(obj, "App::PropertyAngle", "Draft", g, "Draft on the boss's outside", 1.0)
        a(obj, "App::PropertyLength", "HoleDiameter", g, "Hole diameter at the top", 3.0)
        a(obj, "App::PropertyLength", "HoleDepth", g, "Hole depth, from the top", 8.0)
        a(obj, "App::PropertyAngle", "HoleDraft", g, "Draft in the hole", 0.5)
        a(obj, "App::PropertyLength", "PinDiameter", g, "Pin diameter", 3.0)
        a(obj, "App::PropertyLength", "PinHeight", g, "Pin height, above the boss", 4.0)
        g = "Fins"
        a(obj, "App::PropertyInteger", "Fins", g, "Number of fins (0: none)", 0)
        a(obj, "App::PropertyLength", "FinLength", g, "How far the fins reach out from the "
          "boss", 4.0)
        a(obj, "App::PropertyLength", "FinHeight", g, "Fin height, from the face", 6.0)
        a(obj, "App::PropertyLength", "FinThickness", g, "Fin thickness", 1.0)
        a(obj, "App::PropertyAngle", "FinAngle", g, "Turns the fins round the boss", 0.0)

    def compute(self, obj, base):
        p = core.BossParams()
        q = self.params(obj, base)
        p.feature, p.tag, p.alloc = q.feature, q.tag, q.alloc
        p.face, p.point, warns = _face_and_point(obj, "boss")
        p.reverse = obj.ReverseDirection
        p.kind = obj.BossType
        p.height, p.diameter, p.draft = obj.Height.Value, obj.Diameter.Value, obj.Draft.Value
        p.hole_diameter, p.hole_depth = obj.HoleDiameter.Value, obj.HoleDepth.Value
        p.hole_draft = obj.HoleDraft.Value
        p.pin_diameter, p.pin_height = obj.PinDiameter.Value, obj.PinHeight.Value
        p.fins = max(0, int(obj.Fins))
        p.fin_length, p.fin_height = obj.FinLength.Value, obj.FinHeight.Value
        p.fin_thickness, p.fin_angle = obj.FinThickness.Value, obj.FinAngle.Value
        res, preview = core.mounting_boss(p, base)
        self.done(obj, p, res, warns)
        return res, preview


class SnapHookProxy(_PlacedProxy):
    TYPE = "SnapHook"
    LABELS = ("Snap Hook",)

    def setup(self, obj):
        super(SnapHookProxy, self).setup(obj)
        a = util.add_prop
        g = "Position"
        a(obj, "App::PropertyLinkSub", "HookDirection", g,
          "The way the hook points: an edge or plane (empty: along X)")
        a(obj, "App::PropertyAngle", "HookAngle", g, "Turns the hook about the face's normal",
          0.0)
        g = "Hook"
        a(obj, "App::PropertyLength", "Height", g, "Total height, face to the hook's top", 15.0)
        a(obj, "App::PropertyLength", "Thickness", g, "Beam thickness (along the hook)", 2.0)
        a(obj, "App::PropertyLength", "Width", g, "Beam width", 6.0)
        a(obj, "App::PropertyLength", "Overhang", g, "How far the hook sticks out", 1.5)
        a(obj, "App::PropertyLength", "LipHeight", g, "The hook's height, catch to top", 3.0)

    def compute(self, obj, base):
        from ..core import refgeom as core_ref
        p = core.HookParams()
        q = self.params(obj, base)
        p.feature, p.tag, p.alloc = q.feature, q.tag, q.alloc
        p.face, p.point, warns = _face_and_point(obj, "snap hook")
        p.reverse = obj.ReverseDirection
        v = obj.HookDirection
        if v and v[0] is not None:
            s, w = refs.get_ref(obj, "HookDirection", "hook direction", obj.BaseFeature)
            if w:
                warns.append(w)
            if s is not None:
                p.direction = core_ref.direction_of(s, "hook direction")
        p.angle = obj.HookAngle.Value
        p.height, p.thickness, p.width = obj.Height.Value, obj.Thickness.Value, obj.Width.Value
        p.overhang, p.lip_height = obj.Overhang.Value, obj.LipHeight.Value
        res, preview = core.snap_hook(p, base)
        self.done(obj, p, res, warns)
        return res, preview


class LipGrooveProxy(_SurfaceTool):
    TYPE = "LipGroove"
    LABELS = ("Lip-Groove",)

    def setup(self, obj):
        super(LipGrooveProxy, self).setup(obj)
        a = util.add_prop
        g = "Bodies"
        a(obj, "App::PropertyString", "GrooveBody", g, "The body the groove is cut into", "")
        a(obj, "App::PropertyString", "LipBody", g, "The body the lip grows from", "")
        a(obj, "App::PropertyLinkSub", "Items", g,
          "The lip body's flat face where the two bodies meet")
        g = "Lip"
        a(obj, "App::PropertyLength", "LipOffset", g, "The lip's distance in from the face's "
          "outer edge", 0.5)
        a(obj, "App::PropertyLength", "LipWidth", g, "Lip width", 1.0)
        a(obj, "App::PropertyLength", "LipHeight", g, "Lip height", 1.5)
        a(obj, "App::PropertyLength", "Gap", g, "Clearance round the lip, in the groove", 0.1)

    def compute(self, obj, base):
        p = core.LipParams()
        q = self.params(obj, base)
        p.feature, p.tag, p.alloc = q.feature, q.tag, q.alloc
        p.lip_body, p.groove_body = obj.LipBody, obj.GrooveBody
        warns = []
        v = obj.Items
        if v and v[0] is not None:
            faces, warns = refs.get_refs(obj, "Items", "face", obj.BaseFeature)
            faces = [f for f in faces if f.ShapeType == "Face"]
            p.face = faces[0] if faces else None
        p.offset, p.width = obj.LipOffset.Value, obj.LipWidth.Value
        p.height, p.gap = obj.LipHeight.Value, obj.Gap.Value
        res, preview = core.lip_groove(p, base)
        self.done(obj, p, res, warns)
        return res, preview


class VentProxy(_SurfaceTool):
    TYPE = "Vent"
    LABELS = ("Vent",)

    def setup(self, obj):
        super(VentProxy, self).setup(obj)
        a = util.add_prop
        g = "Vent"
        a(obj, "App::PropertyLink", "Sketch", g,
          "The vent's sketch: a closed boundary, lines for ribs, inner loops for spars")
        a(obj, "App::PropertyLength", "Depth", g, "How deep it cuts (the wall's thickness)",
          3.0)
        a(obj, "App::PropertyBool", "ReverseDirection", g, "Cut the other way from the sketch",
          False)
        a(obj, "App::PropertyLength", "RibWidth", g, "Rib width", 1.0)
        a(obj, "App::PropertyLength", "SparWidth", g, "Spar width", 1.0)
        a(obj, "App::PropertyEnumeration", "InnerLoops", g,
          "Inner loops: Spars (a ring of material along them) or Fill-in (kept solid)",
          enum=core.INNER_LOOPS)

    def compute(self, obj, base):
        p = core.VentParams()
        q = self.params(obj, base)
        p.feature, p.tag, p.alloc = q.feature, q.tag, q.alloc
        if obj.Sketch is None:
            raise topo.GeometryError("Pick the vent's sketch.")
        p.shape = topo.shape_of(obj.Sketch)
        p.normal = regions.sketch_normal(obj.Sketch) \
            if obj.Sketch.TypeId.startswith("Sketcher::") else App.Vector(0, 0, 1)
        p.depth = obj.Depth.Value
        p.reverse = obj.ReverseDirection
        p.rib_width, p.spar_width = obj.RibWidth.Value, obj.SparWidth.Value
        p.inner = obj.InnerLoops
        res, preview = core.vent(p, base)
        self.done(obj, p, res)
        return res, preview


def create_mounting_boss(doc, part, **props):
    return _create(MountingBossProxy, doc, part, "MountingBoss", **props)


def create_snap_hook(doc, part, **props):
    return _create(SnapHookProxy, doc, part, "SnapHook", **props)


def create_lip_groove(doc, part, **props):
    return _create(LipGrooveProxy, doc, part, "LipGroove", **props)


def create_vent(doc, part, **props):
    return _create(VentProxy, doc, part, "Vent", **props)
