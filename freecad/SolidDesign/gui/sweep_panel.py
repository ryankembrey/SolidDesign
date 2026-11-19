# SPDX-License-Identifier: LGPL-2.1-or-later
"""Sweep, Loft and Shell panels."""

from ..app import refs, util
from ..core.features import sweep as core
from . import selection as selmod
from .panel import parts
from .sketch_panel import SketchFeaturePanel
from .tool_panels import ToolPanel

__all__ = ["SweepPanel", "LoftPanel", "ShellPanel"]


class SweepPanel(SketchFeaturePanel):
    TITLE = "Sweep"
    ICONS = ("SweepAdd", "SweepCut", "SweepSurface")
    SKETCH_TITLE = "Profile"
    SKETCH_LABEL = "Profile"
    SKETCH_TIP = "The sketch swept along the path. Press the button, then click a sketch."

    bodies_box = ToolPanel.bodies_box

    def build_profile_rows(self, g):
        self.ptype, _r = self.choice(
            g, "ProfileType", "Profile type",
            "Sketch profile: sweep a sketch. Circular profile: sweep a circle of the "
            "diameter, as for wires and pipes. Solid profile: sweep a tool body of "
            "revolution, as a cutter moving along a groove.")
        self.dia, self.r_dia = self.qty(g, "Diameter", "Diameter",
                                        "Diameter of the circular profile")
        self.tool = self.bodies_box(
            g, "ToolBody", "The tool body: a body of revolution (a revolve or a cylinder). "
            "It isn't cut by the sweep.", label="Tool body", multiple=False)

    def build_parameters(self, L):
        g = self.sec_pp = self.group("Path")
        self.path = self.list(g, "Path", "path", "Click a path sketch or edges",
                              self._accept_path,
                              "The path: a sketch, or connected edges of the model or a "
                              "sketch, in order")
        self.path.changed.connect(self._path_changed)
        g = self.sec_opt = self.group("Options")
        self.orient, _r = self.choice(
            g, "Orientation", "Orientation",
            "Follow Path: the profile turns with the path. Keep Normal Constant: it keeps "
            "facing the same way.")
        self.twist, self.r_twist = self.choice(
            g, "ProfileTwist", "Profile twist",
            "None: no twist. Specify Twist Value: turn the profile evenly along the path. "
            "Follow Path and 1st Guide Curve: turn it to keep touching the guide curve.")
        self.twist_unit, self.r_twist_unit = self.choice(
            g, "TwistControl", "Twist control", "Give the twist in degrees or in turns")
        self.twist_deg, self.r_twist_deg = self.qty(
            g, "TwistAngle", "Twist", "How far the profile turns along the whole path",
            unit="deg", minimum=-1e6, step=15.0, flip="ReverseTwist",
            flip_tip="Twist the other way")
        self.turns, self.r_turns = self.qty(
            g, "Turns", "Turns", "How many turns the profile makes along the path",
            unit="", minimum=-1e4, step=0.25, flip="ReverseTwist",
            flip_tip="Twist the other way")
        self.add_body_rows(g)
        g = self.sec_guides = self.group(
            "Guide Curves", "Curves the profile follows: it is scaled (and, with two or "
            "more, turned and moved) to keep touching them")
        self.guides = self.list(g, "GuideCurves", "guide curves",
                                "Click guide curve sketches", self._accept_guide,
                                "Sketches whose curves the profile follows; each must touch "
                                "the profile", empty="None")
        self.guides.changed.connect(lambda: self.set_prop(
            "GuideCurves", [self.doc.getObject(n) for n in self.guides.payloads()]))
        g = self.sec_tan = self.group("Start/End Tangency")
        self.t_start, _r = self.choice(
            g, "StartTangency", "Start tangency",
            "Path Tangent: the sweep leaves the start square to the path, even where "
            "guide curves flare it")
        self.t_end, _r = self.choice(g, "EndTangency", "End tangency",
                                     "Path Tangent: the sweep arrives square to the path")

    def _accept_guide(self, sel):
        o = sel.obj
        if sel.sub:
            return "Pick the whole guide curve sketch, in the tree or the view."
        if o is self.obj.Sketch:
            return "That is the profile."
        v = self.obj.Path
        if v and v[0] is o:
            return "That is the path."
        if util.is_curve(o):
            return o.Name, o.Label
        return None

    def _accept_path(self, sel):
        o = sel.obj
        if o is self.obj.Sketch and not sel.sub:
            if self.obj.ProfileType == core.SKETCH_PROFILE:
                return "That is the profile; pick the path."
            # A circular or solid profile has no sketch: the one picked for it
            # (perhaps by itself, as the newest) is the path.
            self.sketch_box.set_items([])
            self.obj.Sketch = None
        if o.TypeId.startswith("Sketcher::SketchObject") and not sel.sub:
            return ("sketch", o.Name, ""), o.Label
        if util.role(o) == "refgeom" and o.Proxy.KIND in ("helix", "curve"):
            return ("sketch", o.Name, ""), o.Label       # the whole curve
        if sel.elem_kind() != "Edge":
            return None
        if o.TypeId.startswith("Sketcher::"):
            return ("edge", o.Name, sel.sub), "{} {}".format(o.Label, sel.sub)
        if util.is_body_view(o):
            r = selmod._from_body(sel, self.obj.BaseFeature, "Edge")
            if r is None or isinstance(r, str):
                return r
            return ("edge", r[0].Name, r[1]), "{} {}".format(r[0].Label, r[1])
        return None

    def _path_changed(self):
        items = self.path.payloads()
        sketches = [i for i in items if i[0] == "sketch"]
        if sketches:
            # A whole sketch replaces any edges.
            last = sketches[-1]
            self.path.set_items([(last, self.doc.getObject(last[1]).Label)])
            self.obj.Path = (self.doc.getObject(last[1]), [])
        elif items:
            targets = {i[1] for i in items}
            if len(targets) > 1:
                self.path.say("The path's edges must come from one sketch or the model.")
                self.path.set_items(self.path.items[:-1])
                return
            refs.set_ref(self.obj, "Path", self.doc.getObject(items[0][1]), [i[2] for i in items])
        else:
            refs.set_ref(self.obj, "Path", None)
        self.changed()

    def load_parameters(self):
        self.guides.set_items([(o.Name, o.Label) for o in self.obj.GuideCurves
                               if o is not None])
        v = self.obj.Path
        if v and v[0] is not None:
            if v[1]:
                self.path.set_items([(("edge", v[0].Name, s), "{} {}".format(v[0].Label, s))
                                     for s in v[1]])
            else:
                self.path.set_items([(("sketch", v[0].Name, ""), v[0].Label)])

    def refresh_parameters(self):
        kind = self.ptype.currentText()
        circ = kind == core.CIRCULAR_PROFILE
        solid = kind == core.SOLID_PROFILE
        self.r_dia.set_visible(circ)
        self.tool.row.set_visible(solid)
        self.sketch_box.row.set_visible(not circ and not solid)
        self.sec_contours.setVisible(kind == core.SKETCH_PROFILE)
        self.sec_thin.setVisible(not solid and self.obj.Mode != "Surface")
        self.sec_guides.setVisible(not solid)
        twisting = self.twist.currentText() == core.TWIST_VALUE
        self.r_twist.set_visible(not solid)
        for f in (self.twist_deg, self.turns):
            if f.flip.isChecked() != self.obj.ReverseTwist:
                f.flip.blockSignals(True)
                f.flip.setChecked(self.obj.ReverseTwist)
                f.flip.blockSignals(False)
        self.r_twist_unit.set_visible(twisting and not solid)
        turns = self.twist_unit.currentText() == core.TURNS
        self.r_twist_deg.set_visible(twisting and not turns and not solid)
        self.r_turns.set_visible(twisting and turns and not solid)
        self.sec_tan.setVisible(not solid and bool(self.obj.GuideCurves or
                                                   self.obj.ProfileTwist != core.NO_TWIST or
                                                   self.obj.StartTangency != core.NO_TANGENCY or
                                                   self.obj.EndTangency != core.NO_TANGENCY))


class LoftPanel(SketchFeaturePanel):
    TITLE = "Loft"
    ICONS = ("LoftAdd", "LoftCut", "LoftSurface")
    PROFILES_TITLE = "Profiles"

    def build_parameters(self, L):
        g = self.sec_prof = self.group(self.PROFILES_TITLE)
        self.profiles = self.list(g, "Profiles", "profiles", "Click the profiles in order",
                                  self._accept_profile,
                                  "The sketches to loft through, in order; a point may start "
                                  "or end the loft")
        self.profiles.changed.connect(lambda: self.set_prop(
            "Profiles", [self.doc.getObject(n) for n in self.profiles.payloads()]))
        g = self.sec_cons = self.group(
            "Start/End Constraints", "How the loft leaves the first profile and reaches the "
            "last")
        self.cons = {}
        for end in ("Start", "End"):
            c, _r = self.choice(
                g, end + "Constraint", "{} constraint".format(end),
                "None: no constraint. Normal To Profile: the loft leaves the profile square to "
                "it. Direction Vector: it leaves along a direction you pick.")
            d = self.ref_box(g, end + "Direction", "Direction", "direction",
                             "Click an edge, axis or plane",
                             "The direction the loft leaves the profile in: an edge or axis, "
                             "or a plane's normal", ("Face", "Edge"))
            ln, r_ln = self.qty(g, end + "TangentLength", "Tangent length",
                                "How far the constraint reaches into the loft (1: normal)",
                                unit="", minimum=0.01, maximum=100.0, step=0.1)
            dr, r_dr = self.qty(g, end + "DraftAngle", "Draft angle",
                                "Tilts the loft outwards where it leaves the profile",
                                unit="deg", minimum=-89.0, maximum=89.0, step=1.0)
            self.cons[end] = (c, d, r_ln, r_dr)
        g = self.sec_guides = self.group(
            "Guide Curves", "Curves the loft follows between the profiles")
        self.guides = self.list(g, "GuideCurves", "guide curves", "Click guide curve sketches",
                                self._accept_guide,
                                "Sketches whose curves the loft follows; each must touch every "
                                "profile", empty="None")
        self.guides.changed.connect(lambda: self.set_prop(
            "GuideCurves", [self.doc.getObject(n) for n in self.guides.payloads()]))
        self.influence, self.r_influence = self.choice(
            g, "GuideInfluence", "Influence",
            "To Next Edge: a guide shapes only the faces beside it. To Next Guide: its pull "
            "blends to the next guide (with one guide, the whole profile moves).")
        g = self.sec_opt = self.group("Options")
        self.closed, self.r_closed = self.check(g, "Closed", "Close loft",
                                     "Join the last profile back to the first, making a ring")
        self.add_body_rows(g)

    ref_box = ToolPanel.ref_box

    def _accept_guide(self, sel):
        o = sel.obj
        if sel.sub:
            return "Pick the whole guide curve sketch, in the tree or the view."
        if o in self.obj.Profiles:
            return "That is a profile."
        if util.is_curve(o):
            return o.Name, o.Label
        return None

    def _accept_profile(self, sel):
        o = sel.obj
        if o.TypeId.startswith("Sketcher::SketchObject") or o.TypeId == "Part::DatumPoint":
            return o.Name, o.Label
        return None

    def load_parameters(self):
        self.profiles.set_items([(o.Name, o.Label) for o in self.obj.Profiles if o is not None])
        self.guides.set_items([(o.Name, o.Label) for o in self.obj.GuideCurves
                               if o is not None])

    def refresh_parameters(self):
        # A loft takes its profiles from the Profiles box, not one sketch.
        self.sec_sketch.setVisible(False)
        self.sec_contours.setVisible(False)
        self.sec_thin.setVisible(False)
        for end, (c, d, r_ln, r_dr) in self.cons.items():
            kind = c.currentText()
            d.row.set_visible(kind == core.DIRECTION_VECTOR)
            r_ln.set_visible(kind != core.NO_TANGENCY)
            r_dr.set_visible(kind == core.NORMAL_TO_PROFILE)
        self.r_influence.set_visible(bool(self.obj.GuideCurves))


class BoundaryPanel(LoftPanel):
    """Direction 1 and Direction 2 curves (SolidWorks' Boundary)."""
    TITLE = "Boundary"
    ICONS = ("BoundaryAdd", "BoundaryCut", "BoundarySurface")
    PROFILES_TITLE = "Direction 1"

    def build_parameters(self, L):
        super(BoundaryPanel, self).build_parameters(L)
        g = self.sec_dir2 = self.group(
            "Direction 2", "Curves crossing every Direction 1 curve: the shape passes "
            "through the whole network")

        def accept(sel):
            o = sel.obj
            if sel.sub:
                return "Pick the whole sketch, in the tree or the view."
            if o in self.obj.Profiles:
                return "That is a Direction 1 curve."
            if util.is_curve(o):
                return o.Name, o.Label
            return None
        self.dir2 = self.list(g, "Direction2", "curves", "Click Direction 2 sketches", accept,
                              "Sketches whose curves cross every Direction 1 curve; the "
                              "first and last run along the ends", empty="None")
        self.dir2.changed.connect(lambda: self.set_prop(
            "Direction2", [self.doc.getObject(n) for n in self.dir2.payloads()]))

    def load_parameters(self):
        super(BoundaryPanel, self).load_parameters()
        self.dir2.set_items([(o.Name, o.Label) for o in self.obj.Direction2 if o is not None])

    def refresh_parameters(self):
        super(BoundaryPanel, self).refresh_parameters()
        self.sec_guides.setVisible(False)
        self.r_closed.set_visible(False)
        self.sec_cons.setVisible(not self.obj.Direction2)


class ShellPanel(ToolPanel):
    TITLE = "Shell"

    def build(self):
        obj = self.obj
        g = self.sec_p = self.group("Parameters")
        self.t, _r = self.qty(g, "Thickness", "Thickness", "Wall thickness", step=0.5)
        self.out, _r = self.check(g, "ShellOutward", "Shell outward",
                                  "Grow the walls outwards, keeping the inside the same size")
        g = self.group("Faces to Remove")
        self.faces = self._faces_box(g, "Items", "faces", "Click faces to remove",
                                     "The faces to remove, opening the shell. Empty: hollow the "
                                     "body inside.", empty="None: hollow inside")
        g = self.sec_m = self.group(
            "Multi-thickness Settings",
            "Faces whose walls have their own thickness, thicker or thinner than the shell")
        self.multi = self._faces_box(g, "MultiFaces", "faces", "Click faces",
                                     "Faces whose walls get their own thickness. Click a face "
                                     "in the list to see or change its thickness.",
                                     empty="None")
        # Each multi-thickness face has its own value: the field shows and sets the
        # selected faces' (all of them when none is selected).
        self.mt = parts.QuantityField(obj, "Thickness", step=0.5, bind=False)
        self.mt.set_value(obj.MultiThickness[0] if obj.MultiThickness else
                          obj.Thickness.Value * 2)
        self.mt.changed.connect(self._multi_t)
        g.row("Thickness", self.mt,
              "Wall thickness of the selected faces in the list (of all of them when none "
              "is selected); thicker or thinner than the shell")
        self.multi.list.itemSelectionChanged.connect(self._multi_selected)

    def _values(self):
        """{face: thickness} as stored."""
        v = self.obj.MultiFaces
        subs = list(v[1]) if v and v[0] is not None else []
        ts = list(self.obj.MultiThickness)
        return {sub: (ts[i] if i < len(ts) else self.mt.value()) for i, sub in enumerate(subs)}

    def _label(self, sub, t):
        v = self.obj.MultiFaces
        base = self.ref_text(v[0], sub) if v and v[0] is not None else sub
        return u"{} \u2014 {:g} mm".format(base, t)

    def _relabel(self):
        vals = self._values()
        rows = [i.row() for i in self.multi.list.selectedIndexes()]
        self.multi.items = [(sub, self._label(sub, vals.get(sub, self.mt.value())))
                            for sub, _t in self.multi.items]
        self.multi.list.blockSignals(True)
        self.multi._refresh()
        for r in rows:
            if r < self.multi.list.count():
                self.multi.list.item(r).setSelected(True)
        self.multi.list.blockSignals(False)

    def _multi_selected(self):
        rows = sorted(i.row() for i in self.multi.list.selectedIndexes())
        if rows and rows[0] < len(self.multi.items):
            t = self._values().get(self.multi.items[rows[0]][0])
            if t is not None:
                self.mt.blockSignals(True)
                self.mt.set_value(t)
                self.mt.blockSignals(False)

    def _faces_box(self, group, prop, what, hint, tip, empty=None):
        def accept(sel):
            if not util.is_body_view(sel.obj) or sel.elem_kind() != "Face":
                return None if sel.elem_kind() != "Edge" else "Pick faces here."
            r = selmod._from_body(sel, self.obj.BaseFeature, "Face")
            if r is None or isinstance(r, str):
                return r
            return r[1], self.ref_text(r[0], r[1])
        box = self.list(group, prop, what, hint, accept, tip, empty)

        def store():
            subs = list(box.payloads())
            if prop == "MultiFaces":
                vals = self._values()
                refs.set_ref(self.obj, prop, self.obj.BaseFeature if subs else None, subs)
                self.set_prop("MultiThickness",
                              [float(vals.get(sub, self.mt.value())) for sub in subs])
                self._relabel()
                return
            refs.set_ref(self.obj, prop, self.obj.BaseFeature if subs else None, subs)
            self.changed()
        box.changed.connect(store)

        def load():
            v = getattr(self.obj, prop)
            if v and v[0] is not None:
                if prop == "MultiFaces":
                    vals = self._values()
                    box.set_items([(sub, self._label(sub, vals[sub])) for sub in v[1]])
                else:
                    box.set_items([(sub, self.ref_text(v[0], sub)) for sub in v[1]])
        self._loaders.append(load)
        return box

    def _multi_t(self, v):
        if not hasattr(self, "multi"):
            return
        rows = {i.row() for i in self.multi.list.selectedIndexes()}
        subs = list(self.multi.payloads())
        vals = self._values()
        ts = [float(v) if (not rows or k in rows) else float(vals.get(sub, v))
              for k, sub in enumerate(subs)]
        self.set_prop("MultiThickness", ts)
        self._relabel()

    def refresh(self):
        pass
