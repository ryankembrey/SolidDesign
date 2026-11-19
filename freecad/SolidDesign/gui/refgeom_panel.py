# SPDX-License-Identifier: LGPL-2.1-or-later
"""Plane, Axis, Point, Coordinate System and Helix/Spiral panels.

SolidWorks asks for up to three references and offers constraints per
reference. Here the panel asks for the type first and then exactly the
references that type needs (see docs/_notes/ux-departures.md).
"""

from .. import icon
from ..app import refs, util
from ..core import curves
from ..core import refgeom as core
from . import selection as selmod
from .panel import parts
from .panel.base import FeaturePanel
from .sketch_panel import LAST

__all__ = ["RefGeomPanel"]

PLACEHOLDER = {
    "plane": "Click a plane or planar face", "plane?": "Click a plane or planar face",
    "line": "Click a line, axis or straight edge", "point": "Click a vertex or point",
    "point?": "Click a point on it (optional)", "curve": "Click an edge",
    "round": "Click a cylindrical or conical face", "arc": "Click a circular edge or arc",
    "face": "Click a face", "surface": "Click a face or plane",
    "origin?": "Click a vertex or point", "xdir?": "Click an edge, axis or face",
    "ydir?": "Click an edge, axis or face",
    "circle": "Click a sketch with one circle, or a circular edge",
}

# (row label, what it holds, short hint for the field) for each kind of reference.
ROW = {
    "plane": ("Plane", "plane", "Click a plane or face"),
    "plane?": ("Plane", "plane", "Click a plane or face"),
    "line": ("Line", "line", "Click a line or edge"),
    "point": ("Point", "point", "Click a vertex or point"),
    "point?": ("Point (optional)", "point", "Click a point"),
    "curve": ("Edge", "edge", "Click an edge"),
    "round": ("Round face", "face", "Click a round face"),
    "arc": ("Arc", "arc", "Click a circular edge"),
    "face": ("Face", "face", "Click a face"),
    "surface": ("Face/Plane", "face", "Click a face or plane"),
    "origin?": ("Origin", "point", "Click a vertex or point"),
    "xdir?": ("X axis", "direction", "Click an edge or face"),
    "ydir?": ("Y axis", "direction", "Click an edge or face"),
    "circle": ("Circle", "circle", "Click a circle or sketch"),
}

# What an empty optional box means.
EMPTY = {"origin?": "Part origin", "xdir?": "Automatic", "ydir?": "Automatic"}

TITLES = {"plane": "Plane", "axis": "Axis", "point": "Point", "csys": "Coordinate System",
          "helix": "Helix/Spiral"}
ICONS = {"plane": "Plane", "axis": "Axis", "point": "Point", "csys": "CoordinateSystem",
         "helix": "Helix"}
NEEDS = {"plane": core.PLANE_NEEDS, "axis": core.AXIS_NEEDS, "point": core.POINT_NEEDS,
         "csys": core.CSYS_NEEDS, "helix": {t: ("circle",) for t in curves.HELIX_TYPES}}

# Whole datum objects each kind of reference accepts, and the element kinds.
WHOLE = {"plane": ("plane",), "line": ("line",), "point": ("point",), "curve": ("line",),
         "round": (), "arc": (), "face": ("plane",), "surface": ("plane",),
         "origin": ("point",), "xdir": ("line", "plane"), "ydir": ("line", "plane"),
         "circle": ()}
ELEMS = {"plane": ("Face",), "round": ("Face",), "line": ("Edge",), "curve": ("Edge",),
         "point": ("Vertex",), "arc": ("Edge",), "face": ("Face",), "surface": ("Face",),
         "origin": ("Vertex",), "xdir": ("Edge", "Face"), "ydir": ("Edge", "Face"),
         "circle": ("Edge",)}


class RefGeomPanel(FeaturePanel):
    EDIT_SHOWS_BASE = True

    def __init__(self, obj, is_new=False):
        LAST[0] = self
        self.kind = obj.Proxy.KIND
        self.TITLE = TITLES[self.kind]
        self.ICON = icon(ICONS[self.kind])
        super(RefGeomPanel, self).__init__(obj, is_new)

    def needs(self):
        return NEEDS[self.kind].get(self.obj.Type, ())

    def build(self):
        obj = self.obj
        g = self.sec = self.group("Type")
        self.type = parts.combo(obj.Proxy.TYPES, obj.Type)
        g.row("Type", self.type, "How the {} is defined; the references below follow from "
              "it".format(self.TITLE.lower()))
        self.type.currentTextChanged.connect(self._type_changed)
        g.setVisible(len(obj.Proxy.TYPES) > 1)
        g = self.sec_refs = self.group("References")
        self.ref_boxes = []
        for i in (1, 2, 3):
            b = self.field(g, "Reference %d" % i, "Reference%d" % i, "reference", "",
                           lambda s, i=i: self._accept(s, i),
                           "A reference the {} is built from".format(self.TITLE.lower()))
            b.changed.connect(lambda i=i: self._ref_changed(i))
            self.ref_boxes.append(b)
        self.ref_rows = [b.row for b in self.ref_boxes]
        g = self.sec_opts = self.group("Parameters" if self.kind == "helix" else "Options")
        if self.kind == "plane":
            self.dist, self.r_dist = self.qty(g, "Distance", "Distance",
                                              "Distance from the reference plane")
            self.angle, self.r_angle = self.qty(g, "Angle", "Angle",
                                                "Angle to the reference plane", unit="deg",
                                                maximum=360.0, step=5.0)
        if self.kind == "point":
            self.dist, self.r_dist = self.qty(g, "Distance", "Distance",
                                              "Distance along the edge from its start")
        if self.kind == "helix":
            self.build_helix(g)
        elif self.kind == "csys":
            self.flip_x, _r = self.check(g, "FlipX", "Reverse X direction",
                                         "Turn the X axis round")
            self.flip_y, _r = self.check(g, "FlipY", "Reverse Y direction",
                                         "Turn the Y axis round")
            self.flip, self.r_flip = self.check(g, "Flip", "Reverse Z direction",
                                                "Turn the Z axis round (Y turns with it, so "
                                                "the axes stay right-handed)")
        elif self.kind == "point":
            self.flip, self.r_flip = self.check(g, "Flip", "From the other end",
                                                "Measure the distance from the edge's other end")
        else:
            self.flip, self.r_flip = self.check(g, "Flip", "Flip",
                                                "Turn the {} the other way round".format(
                                                    self.TITLE.lower()))

    def build_helix(self, g):
        self.pitch, self.r_pitch = self.qty(g, "Pitch", "Pitch", "Distance between turns",
                                            minimum=0.001, step=0.5)
        self.revs, self.r_revs = self.qty(g, "Revolutions", "Revolutions", "Number of turns",
                                          unit="", minimum=0.01, step=1.0)
        self.height, self.r_height = self.qty(g, "Height", "Height", "Height of the helix",
                                              minimum=0.001, step=1.0)
        self.start, _r = self.qty(g, "StartAngle", "Start angle",
                                  "Where the first turn starts, measured round from the "
                                  "circle's X direction", unit="deg", minimum=-360.0,
                                  maximum=360.0, step=15.0)
        self.flip, self.r_flip = self.check(g, "Flip", "Reverse direction",
                                            "Grow the helix the other way from the circle")
        self.cw, _r = self.check(g, "Clockwise", "Clockwise",
                                 "Turn clockwise (a left-hand helix); off: counterclockwise")
        t = self.sec_taper = self.group("Taper Helix", "Make the helix cone-shaped",
                                        checkable=True, prop="TaperHelix")
        self.taper, _r = self.qty(t, "TaperAngle", "Angle", "Taper angle", unit="deg",
                                  maximum=89.0, step=1.0)
        self.taper_out, _r = self.check(t, "TaperOutward", "Taper outward",
                                        "Wider at the end; off: narrower")

    def _accept(self, sel, i):
        needs = self.needs()
        if i > len(needs):
            return None
        want = needs[i - 1].rstrip("?")
        o = sel.obj
        if o is self.obj:
            return "A reference can't refer to itself."
        k = sel.elem_kind()
        base = self.obj.BaseFeature
        if want == "circle" and o.TypeId.startswith("Sketcher::SketchObject") and not sel.sub:
            return (o.Name, ""), o.Label        # a sketch with one circle
        # Whole datum objects: origin planes/axes/point and other reference geometry.
        whole = None
        if o.TypeId == "Part::DatumPlane" or (util.role(o) == "refgeom" and o.Proxy.KIND == "plane"):
            whole = "plane"
        elif o.TypeId == "Part::DatumLine" or (util.role(o) == "refgeom" and o.Proxy.KIND == "axis"):
            whole = "line"
        elif o.TypeId == "Part::DatumPoint" or (util.role(o) == "refgeom" and
                                                o.Proxy.KIND == "point"):
            whole = "point"
        if whole is not None:
            if whole in WHOLE[want]:
                return (o.Name, ""), self.ref_text(o, "")
            return "This reference needs: {}.".format(PLACEHOLDER[needs[i - 1]].lower()[6:])
        if k not in ELEMS[want]:
            return None if not k else "This reference needs: {}.".format(
                PLACEHOLDER[needs[i - 1]].lower()[6:])
        if o.TypeId.startswith("Sketcher::") and k in ("Edge", "Vertex"):
            return (o.Name, sel.sub), self.ref_text(o, sel.sub)
        if util.is_body_view(o):
            r = selmod._from_body(sel, base, k)
            if r is None or isinstance(r, str):
                return r
            return (r[0].Name, r[1]), self.ref_text(r[0], r[1])
        return None

    def _ref_changed(self, i):
        box = self.ref_boxes[i - 1]
        p = box.payloads()
        if p:
            refs.set_ref(self.obj, "Reference%d" % i, self.doc.getObject(p[0][0]), p[0][1])
        else:
            refs.set_ref(self.obj, "Reference%d" % i, None)
        # Move on to the next box needing a pick.
        nxt = self.next_box_needing_input()
        if nxt is not None:
            self.activate(nxt)
        self.changed()

    def _type_changed(self, t):
        self.set_prop("Type", t)
        for b in self.ref_boxes:
            b.say("")
        self.refresh()
        nxt = self.next_box_needing_input()
        if nxt is not None:
            self.activate(nxt)

    def next_box_needing_input(self):
        needs = self.needs()
        for i, b in enumerate(self.ref_boxes):
            if i < len(needs) and not needs[i].endswith("?") and not b.items:
                return b
        return None

    def load(self):
        for i, b in enumerate(self.ref_boxes, 1):
            v = getattr(self.obj, "Reference%d" % i)
            if v and v[0] is not None:
                sub = v[1][0] if v[1] else ""
                b.set_items([((v[0].Name, sub), self.ref_text(v[0], sub))])
        self.refresh()

    def refresh(self):
        needs = self.needs()
        for i, b in enumerate(self.ref_boxes):
            show = i < len(needs)
            b.row.set_visible(show)
            if show:
                label, what, hint = ROW[needs[i]]
                b.row.label.setText(label)
                b.set_placeholder(what=what, hint=hint,
                                  empty=EMPTY.get(needs[i], "None") if needs[i].endswith("?")
                                  else "")
        t = self.type.currentText()
        if self.kind == "plane":
            self.r_dist.set_visible(t == core.OFFSET)
            self.r_angle.set_visible(t == core.ANGLE)
        if self.kind == "helix":
            uses = {curves.PITCH_REVS: ("p", "n"), curves.HEIGHT_REVS: ("h", "n"),
                    curves.HEIGHT_PITCH: ("h", "p"), curves.SPIRAL: ("p", "n")}[t]
            self.r_pitch.set_visible("p" in uses)
            self.r_revs.set_visible("n" in uses)
            self.r_height.set_visible("h" in uses)
            self.r_flip.set_visible(t != curves.SPIRAL)
            self.sec_taper.setVisible(t != curves.SPIRAL)
        if self.kind == "point":
            self.r_dist.set_visible(t == core.ALONG_CURVE)
            self.r_flip.set_visible(t == core.ALONG_CURVE)
            self.sec_opts.setVisible(t == core.ALONG_CURVE)

    def preview_layers(self):
        return []
