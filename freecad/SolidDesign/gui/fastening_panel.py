# SPDX-License-Identifier: LGPL-2.1-or-later
"""Mounting Boss, Snap Hook, Lip/Groove and Vent panels."""

from ..app import refs, util
from ..app import surfaces as app_surf
from . import selection as selmod
from .surface_panel import _SurfacePanel

__all__ = ["MountingBossPanel", "SnapHookPanel", "LipGroovePanel", "VentPanel"]


def _point_text(v):
    return u"({:.4g}, {:.4g}, {:.4g})".format(v.x, v.y, v.z)


class _PlacedPanel(_SurfacePanel):
    """Click on a face: that face, and the point clicked, place the feature."""
    WHAT = "feature"

    def position_box(self, group):
        def accept(sel):
            if not util.is_body_view(sel.obj):
                return None
            if sel.elem_kind() != "Face" or sel.point is None:
                return "Click on a face."
            r = selmod._from_body(sel, self.obj.BaseFeature, "Face")
            if r is None or isinstance(r, str):
                return r
            return "{}|{}".format(r[1], app_surf.vec_text(sel.point)), _point_text(sel.point)
        box = self.field(group, "Position", "Position", "point", "Click on a face", accept,
                         "Where the {} stands: click on a face".format(self.WHAT))

        def store():
            got = box.payloads()
            if not got:
                return
            sub, pt = got[0].split("|", 1)
            refs.set_ref(self.obj, "Items", self.obj.BaseFeature, [sub])
            self.set_prop("Position", pt)
        box.changed.connect(store)

        def load():
            v = app_surf._vec(self.obj.Position)
            if v is not None:
                sub = self.obj.Items[1][0] if self.obj.Items and self.obj.Items[1] else ""
                box.set_items([("{}|{}".format(sub, self.obj.Position), _point_text(v))])
        self._loaders.append(load)
        self.check(group, "ReverseDirection", "Reverse direction",
                   "Stand the other way off the face")
        return box


class MountingBossPanel(_PlacedPanel):
    TITLE = "Mounting Boss"
    ICON_NAME = "MountingBoss"
    WHAT = "boss"

    def build(self):
        g = self.group("Position")
        self.position = self.position_box(g)
        g = self.group("Boss")
        self.kind, _r = self.choice(g, "BossType", None,
                                    "Hole: a hole down the boss for a screw or an insert. "
                                    "Pin: a pin on top.")
        self.qty(g, "Height", "Height", "Boss height, from the face")
        self.qty(g, "Diameter", "Diameter", "Boss diameter at the face")
        self.qty(g, "Draft", "Draft", "Draft on the boss's outside", unit="deg",
                 maximum=45)
        self.sec_hole = self.group("Hole")
        self.qty(self.sec_hole, "HoleDiameter", "Diameter", "Hole diameter at the top")
        self.qty(self.sec_hole, "HoleDepth", "Depth", "Hole depth, from the top")
        self.qty(self.sec_hole, "HoleDraft", "Draft", "Draft in the hole", unit="deg",
                 maximum=45)
        self.sec_pin = self.group("Pin")
        self.qty(self.sec_pin, "PinDiameter", "Diameter", "Pin diameter")
        self.qty(self.sec_pin, "PinHeight", "Height", "Pin height, above the boss")
        g = self.group("Fins", "Fins tie the boss to the wall round it")
        self.integer(g, "Fins", "Number", "Number of fins (0: none)", minimum=0)
        _f, self.r_fl = self.qty(g, "FinLength", "Length", "How far the fins reach out")
        _f, self.r_fh = self.qty(g, "FinHeight", "Height", "Fin height, from the face")
        _f, self.r_ft = self.qty(g, "FinThickness", "Thickness", "Fin thickness")
        _f, self.r_fa = self.qty(g, "FinAngle", "Angle", "Turns the fins round the boss",
                                 unit="deg", minimum=-360, maximum=360)

    def refresh(self):
        hole = self.obj.BossType == "Hole"
        self.sec_hole.setVisible(hole)
        self.sec_pin.setVisible(not hole)
        fins = self.obj.Fins > 0
        for r in (self.r_fl, self.r_fh, self.r_ft, self.r_fa):
            r.set_visible(fins)


class SnapHookPanel(_PlacedPanel):
    TITLE = "Snap Hook"
    ICON_NAME = "SnapHook"
    WHAT = "snap hook"

    def build(self):
        g = self.group("Position")
        self.position = self.position_box(g)
        self.ref_box(g, "HookDirection", "Hook points", "direction", "Click an edge or plane",
                     "The way the hook points: an edge, or a plane's normal. Empty: along X",
                     kinds=("Edge", "Face"), empty="Along X")
        self.qty(g, "HookAngle", "Angle", "Turns the hook about the face's normal", unit="deg",
                 minimum=-360, maximum=360)
        g = self.group("Hook")
        self.qty(g, "Height", "Total height", "Face to the hook's top")
        self.qty(g, "Thickness", "Thickness", "The beam's thickness, along the hook")
        self.qty(g, "Width", "Width", "The beam's width")
        self.qty(g, "Overhang", "Overhang", "How far the hook sticks out past the beam")
        self.qty(g, "LipHeight", "Hook height", "From the catch face to the top")


class LipGroovePanel(_SurfacePanel):
    TITLE = "Lip/Groove"
    ICON_NAME = "LipGroove"

    def build(self):
        g = self.group("Bodies")
        self.bodies_box(g, "GrooveBody", "The body the groove is cut into", label="Groove",
                        multiple=False)
        self.bodies_box(g, "LipBody", "The body the lip grows from", label="Lip",
                        multiple=False)
        self.faces_list(g, "Items", "The lip body's flat face where the two bodies meet",
                        hint="Click the mating face")
        g = self.group("Lip")
        self.qty(g, "LipOffset", "Offset", "The lip's distance in from the face's outer edge")
        self.qty(g, "LipWidth", "Width", "Lip width")
        self.qty(g, "LipHeight", "Height", "Lip height")
        self.qty(g, "Gap", "Gap", "Clearance round the lip, in the groove", step=0.05)


class VentPanel(_SurfacePanel):
    TITLE = "Vent"
    ICON_NAME = "Vent"

    def build(self):
        g = self.group("Sketch", "The outer loop is the vent; lines are ribs, inner loops "
                                 "spars")
        self.sketches_box(g, "Sketch", "The vent's sketch", multiple=False)
        self.qty(g, "Depth", "Depth", "How deep it cuts (the wall's thickness)",
                 flip="ReverseDirection", flip_tip="Cut the other way from the sketch")
        g = self.group("Ribs and Spars")
        self.qty(g, "RibWidth", "Rib width", "Width of the ribs (the sketch's lines)")
        self.qty(g, "SparWidth", "Spar width", "Width of the spars (inner loops)")
        self.choice(g, "InnerLoops", "Inner loops", "Spars: a ring of material along each "
                    "inner loop. Fill-in: the loop is kept solid")
