# SPDX-License-Identifier: LGPL-2.1-or-later
"""Hole Wizard (SolidWorks' Hole Wizard).

- Types: Counterbore, Countersink, Hole, Straight Tap, Tapered Tap (NPT and
  ISO 7 Rc pipe threads, 1:16 taper), the slot versions (Counterbore Slot,
  Countersink Slot, Slot), and Advanced (SolidWorks' Advanced Hole: a stack of
  near side and far side elements).
- Standards: ISO and ANSI Inch, with Close, Normal and Loose fits; Custom sizing
  overrides any diameter or depth.
- End conditions: Blind, Through All, Up To Next, Up To Vertex, Up To Surface,
  Offset From Surface; each position gets its own depth.
- Options: near side and far side countersinks, head clearance; for tapped
  holes the tap drill, the thread diameter, or a modelled thread.

ISO dimensions are the usual ISO values (ISO 273 clearance holes, counterbores for
ISO 4762 socket head cap screws, 90° countersinks for ISO 10642 flat heads). ANSI
Inch dimensions are typical machinist-table values (ASME B18.2.8 clearance holes,
counterbores for socket head cap screws, 82° countersinks for flat head screws):
check them against your fasteners, or use Custom sizing. Tapered pipe taps use
ASME B1.20.1 (NPT) and ISO 7-1 (Rc) gauge-plane diameters.
"""

import math

import FreeCAD as App
import Part

from .. import threads, topo
from . import common

HOLE = "Hole"
COUNTERBORE = "Counterbore"
COUNTERSINK = "Countersink"
STRAIGHT_TAP = "Straight Tap"
TAPERED_TAP = "Tapered Tap"
ADVANCED = "Advanced"
CBORE_SLOT = "Counterbore Slot"
CSK_SLOT = "Countersink Slot"
SLOT = "Slot"
LEGACY = "Legacy"
TYPES = [COUNTERBORE, COUNTERSINK, HOLE, STRAIGHT_TAP, TAPERED_TAP, CBORE_SLOT, CSK_SLOT,
         SLOT, ADVANCED, LEGACY]
# Legacy holes (SolidWorks' older hole types): sized by their own dimensions.
L_SIMPLE, L_TAPERED, L_CBORE, L_CSK, L_CDRILL = ("Simple", "Tapered", "Counterbored",
                                                 "Countersunk", "Counterdrilled")
LEGACY_TYPES = [L_SIMPLE, L_TAPERED, L_CBORE, L_CSK, L_CDRILL]
TAPS = (STRAIGHT_TAP, TAPERED_TAP)
SLOTS = (CBORE_SLOT, CSK_SLOT, SLOT)

ISO_STD = "ISO"
ANSI_INCH = "ANSI Inch"
STANDARDS = [ISO_STD, ANSI_INCH]
FITS = ["Close", "Normal", "Loose"]

BLIND = "Blind"
THROUGH_ALL = "Through All"
UP_TO_NEXT = "Up To Next"
UP_TO_VERTEX = "Up To Vertex"
UP_TO_SURFACE = "Up To Surface"
OFFSET_FROM_SURFACE = "Offset From Surface"
END_CONDITIONS = [BLIND, THROUGH_ALL, UP_TO_NEXT, UP_TO_VERTEX, UP_TO_SURFACE,
                  OFFSET_FROM_SURFACE]

TAP_DRILL = "Tap Drill Diameter"
THREAD_DIAMETER = "Thread Diameter"
MODELLED = "Modelled Thread"
THREAD_OPTIONS = [TAP_DRILL, THREAD_DIAMETER, MODELLED]

#        size: (pitch, tap drill, close, normal, loose, cbore dia, cbore depth, csk dia)
ISO = {
    "M2":   (0.40, 1.60, 2.2, 2.4, 2.6, 4.4, 2.2, 4.4),
    "M2.5": (0.45, 2.05, 2.7, 2.9, 3.1, 5.5, 2.7, 5.5),
    "M3":   (0.50, 2.50, 3.2, 3.4, 3.6, 6.5, 3.3, 6.72),
    "M4":   (0.70, 3.30, 4.3, 4.5, 4.8, 8.0, 4.4, 8.96),
    "M5":   (0.80, 4.20, 5.3, 5.5, 5.8, 10.0, 5.4, 11.2),
    "M6":   (1.00, 5.00, 6.4, 6.6, 7.0, 11.0, 6.4, 13.44),
    "M8":   (1.25, 6.80, 8.4, 9.0, 10.0, 15.0, 8.6, 17.92),
    "M10":  (1.50, 8.50, 10.5, 11.0, 12.0, 18.0, 10.6, 22.4),
    "M12":  (1.75, 10.20, 13.0, 13.5, 14.5, 20.0, 12.6, 26.88),
    "M16":  (2.00, 14.00, 17.0, 17.5, 18.5, 26.0, 16.6, 33.6),
    "M20":  (2.50, 17.50, 21.0, 22.0, 24.0, 33.0, 20.6, 40.32),
}
# Inches: size: (close, normal, loose, cbore dia, cbore depth, csk dia); thread from UNC.
_ANSI_IN = {
    "#4":   (0.116, 0.128, 0.140, 0.218, 0.112, 0.255),
    "#6":   (0.144, 0.150, 0.166, 0.250, 0.138, 0.307),
    "#8":   (0.170, 0.177, 0.199, 0.281, 0.164, 0.359),
    "#10":  (0.196, 0.201, 0.221, 0.312, 0.190, 0.411),
    "1/4":  (0.257, 0.266, 0.281, 0.375, 0.250, 0.531),
    "5/16": (0.323, 0.332, 0.344, 0.438, 0.312, 0.656),
    "3/8":  (0.386, 0.397, 0.406, 0.562, 0.375, 0.781),
    "1/2":  (0.516, 0.531, 0.562, 0.750, 0.500, 1.031),
    "5/8":  (0.656, 0.688, 0.719, 0.938, 0.625, 1.281),
    "3/4":  (0.781, 0.812, 0.844, 1.125, 0.750, 1.531),
}
_UNC_OF = {"#4": "#4-40", "#6": "#6-32", "#8": "#8-32", "#10": "#10-24", "1/4": "1/4-20",
           "5/16": "5/16-18", "3/8": "3/8-16", "1/2": "1/2-13", "5/8": "5/8-11",
           "3/4": "3/4-10"}
CSK_ANGLE = {ISO_STD: 90.0, ANSI_INCH: 82.0}
SIZES = list(ISO)       # ISO's, for files from before ANSI Inch

# Tapered pipe threads: the diameter shrinks 1 in 16 with depth (on the diameter).
TAPER = 1.0 / 16.0
# NPT (ASME B1.20.1), inches: size: (threads per inch, E0 pitch dia at the small end,
# L1 hand-tight engagement, tap drill)
_NPT = {
    "1/16 NPT": (27, 0.27118, 0.160, 0.2460), "1/8 NPT": (27, 0.36351, 0.1615, 0.3390),
    "1/4 NPT": (18, 0.47739, 0.2278, 0.4375), "3/8 NPT": (18, 0.61201, 0.240, 0.5781),
    "1/2 NPT": (14, 0.75843, 0.320, 0.7188), "3/4 NPT": (14, 0.96768, 0.339, 0.9219),
    "1 NPT": (11.5, 1.21363, 0.400, 1.1563),
}
# Rc (ISO 7-1), mm: size: (threads per inch, major diameter at the gauge plane, tap drill)
_RC = {
    "Rc 1/16": (28, 7.723, 6.6), "Rc 1/8": (28, 9.728, 8.4), "Rc 1/4": (19, 13.157, 11.2),
    "Rc 3/8": (19, 16.662, 14.75), "Rc 1/2": (14, 20.955, 18.25),
    "Rc 3/4": (14, 26.441, 23.75), "Rc 1": (11, 33.249, 30.0),
}


def sizes(standard, kind=None):
    if kind == TAPERED_TAP:
        return list(_RC) if standard == ISO_STD else list(_NPT)
    return list(ISO) if standard == ISO_STD else list(_ANSI_IN)


def taper_table(standard, size):
    """(pitch, major diameter at the face, tap drill) of a tapered pipe thread, mm."""
    if standard == ANSI_INCH:
        if size not in _NPT:
            raise topo.GeometryError("Unknown NPT size {}.".format(size))
        tpi, e0, l1, tap = _NPT[size]
        pitch = 1.0 / tpi
        e1 = e0 + l1 * TAPER                # pitch diameter at the gauge plane
        return pitch * threads.INCH, (e1 + 0.8 * pitch) * threads.INCH, tap * threads.INCH
    if size not in _RC:
        raise topo.GeometryError("Unknown Rc size {}.".format(size))
    tpi, major, tap = _RC[size]
    return threads.INCH / tpi, major, tap


def table(standard, size):
    """(pitch, major, tap drill, close, normal, loose, cbore dia, cbore depth, csk dia),
    in mm."""
    if standard == ANSI_INCH:
        if size not in _ANSI_IN:
            raise topo.GeometryError("Unknown ANSI Inch size {}.".format(size))
        major, pitch, tap = threads.spec(threads.UNC, _UNC_OF[size])
        return (pitch, major, tap) + tuple(x * threads.INCH for x in _ANSI_IN[size])
    if size not in ISO:
        raise topo.GeometryError("Unknown ISO size {}.".format(size))
    pitch, tap, close, normal, loose, cb_d, cb_h, csk = ISO[size]
    major = float(size[1:])
    return (pitch, major, tap, close, normal, loose, cb_d, cb_h, csk)


class Sizing(object):
    """The diameters and depths a hole is built from (from the standard, or custom)."""

    def __init__(self, d, cbore=None, csk=None, csk_angle=90.0, pitch=None, major=None,
                 taper=0.0):
        self.d = d                  # hole (or drill) diameter (at the face, when tapered)
        self.taper = taper          # diameter lost per unit of depth
        self.cbore = cbore          # (diameter, depth) or None
        self.csk = csk              # diameter or None
        self.csk_angle = csk_angle
        self.pitch = pitch          # tapped holes
        self.major = major


def sizing(kind, standard, size, fit, thread_option=TAP_DRILL):
    if kind == TAPERED_TAP:
        pitch, major, tap = taper_table(standard, size)
        return Sizing(major if thread_option == THREAD_DIAMETER else tap, None, None,
                      CSK_ANGLE[standard], pitch, major, TAPER)
    if kind in (ADVANCED, LEGACY):
        return Sizing(0.0)
    pitch, major, tap, close, normal, loose, cb_d, cb_h, csk = table(standard, size)
    d = {"Close": close, "Normal": normal, "Loose": loose}[fit]
    angle = CSK_ANGLE[standard]
    if kind == STRAIGHT_TAP:
        return Sizing(major if thread_option == THREAD_DIAMETER else tap, None, None, angle,
                      pitch, major)
    if kind in (COUNTERBORE, CBORE_SLOT):
        return Sizing(d, (cb_d, cb_h), None, angle)
    if kind in (COUNTERSINK, CSK_SLOT):
        return Sizing(d, None, csk, angle)
    return Sizing(d, None, None, angle)


def dims(kind, size, fit, standard=ISO_STD):
    """(hole diameter, counterbore (dia, depth) or None, countersink dia or None)."""
    s = sizing(kind, standard, size, fit)
    return s.d, s.cbore, s.csk


def label(kind, size, standard=ISO_STD):
    """SolidWorks' feature names."""
    screw = "Socket Head Cap Screw"
    if kind == COUNTERBORE:
        return "CBORE for {} {}".format(size, screw)
    if kind == CBORE_SLOT:
        return "CBORE Slot for {} {}".format(size, screw)
    if kind == COUNTERSINK:
        return "CSK for {} Flat Head Socket Screw".format(size)
    if kind == CSK_SLOT:
        return "CSK Slot for {} Flat Head Socket Screw".format(size)
    if kind == STRAIGHT_TAP:
        try:
            pitch = table(standard, size)[0]
        except topo.GeometryError:
            pitch = 0
        if standard == ANSI_INCH:
            return "{} Tapped Hole".format(_UNC_OF.get(size, size))
        return "{}x{:g} Tapped Hole".format(size, pitch)
    if kind == SLOT:
        return "{} Clearance Slot".format(size)
    if kind == TAPERED_TAP:
        if standard == ANSI_INCH and size in _NPT:
            return "{}-{:g} NPT Tapered Tap".format(size[:-4], _NPT[size][0])
        return "{} Tapered Tap".format(size)
    if kind == ADVANCED:
        return "Advanced Hole"
    if kind == LEGACY:
        return "Legacy Hole"
    return "{} Clearance Hole".format(size)


class Params(object):
    def __init__(self):
        self.kind = HOLE
        self.standard = ISO_STD
        self.size = "M6"
        self.fit = "Normal"
        self.custom = None          # a Sizing that replaces the standard's
        self.end = BLIND
        self.depth = 10.0
        self.tip_angle = 118.0
        self.up_to = None           # shape: vertex or face (Up To Vertex / Surface, Offset)
        self.offset = 0.0           # Offset From Surface
        self.slot_length = 10.0     # centre to centre
        self.slot_angle = 0.0       # degrees from the sketch's X axis
        self.x_dir = App.Vector(1, 0, 0)
        self.thread = TAP_DRILL
        self.thread_depth = 12.0    # tapped holes, Blind
        self.near_csk = None        # (diameter, angle) or None
        self.far_csk = None
        self.head_clearance = 0.0
        self.legacy = L_SIMPLE
        self.cdrill_angle = 118.0   # Counterdrilled: the step from the counterdrill down
        self.near = []              # Advanced: [Element], from the face down
        self.far = []               # Advanced: [Element], from the exit face up
        self.points = []            # App.Vector, on the face
        self.direction = App.Vector(0, 0, -1)    # into the material
        self.feature = "Hole"
        self.tag = 1
        self.alloc = None


# ------------------------------------------------------------------ advanced

E_COUNTERBORE = "Counterbore"
E_COUNTERSINK = "Countersink"
E_HOLE = "Hole"
E_TAPERED = "Tapered"
ELEMENT_KINDS = [E_COUNTERBORE, E_COUNTERSINK, E_HOLE, E_TAPERED]


class Element(object):
    """One step of an Advanced hole. A countersink's depth comes from its angle and
    the diameter of the element it opens into; a tapered element narrows by its
    included ``angle``; the other kinds ignore the angle."""

    def __init__(self, kind=E_HOLE, d=6.6, depth=5.0, angle=90.0):
        self.kind = kind
        self.d = float(d)
        self.depth = float(depth)
        self.angle = float(angle)

    def dumps(self):
        return "{}|{:g}|{:g}|{:g}".format(self.kind, self.d, self.depth, self.angle)

    @classmethod
    def loads(cls, text):
        bits = [b.strip() for b in str(text).split("|")]
        if not bits or bits[0] not in ELEMENT_KINDS:
            raise topo.GeometryError("Unknown hole element '{}'.".format(text))
        nums = []
        for b in bits[1:4]:
            try:
                nums.append(float(b))
            except ValueError:
                raise topo.GeometryError("Hole element '{}' has a bad number.".format(text))
        return cls(bits[0], *nums)


def default_elements(standard, size):
    """A counterbore over its clearance hole, from the standard (Advanced's start)."""
    try:
        sz = sizing(COUNTERBORE, standard, size, "Normal")
    except topo.GeometryError:
        sz = sizing(COUNTERBORE, ISO_STD, "M6", "Normal")
    return [Element(E_COUNTERBORE, sz.cbore[0], sz.cbore[1], 90.0),
            Element(E_HOLE, sz.d, 0.0, 118.0)]


def _tapered(d_top, angle, z_top, z_bottom):
    """A cone narrowing from d_top by an included ``angle``; (solid, bottom diameter)."""
    h = z_top - z_bottom
    d_bot = d_top - 2.0 * h * math.tan(math.radians(angle / 2.0))
    if d_bot <= 1e-3:
        raise topo.GeometryError("A tapered element closes up before its depth: make it "
                                 "shallower or its angle smaller.")
    return Part.makeCone(d_bot / 2.0, d_top / 2.0, h, App.Vector(0, 0, z_bottom)), d_bot


def advanced_hole(p, length, tag=1, exit_depth=None):
    """An Advanced hole at the origin, going down -Z: the near side elements stacked
    from the face, the last one running to the end condition; the far side elements
    stacked up from where the hole comes out."""
    near = list(p.near)
    far = list(p.far)
    if not near:
        raise topo.GeometryError("Add at least one near side element.")
    for el in near + far:
        if el.d <= 0:
            raise topo.GeometryError("Every hole element needs a diameter greater than zero.")
        if el.kind in (E_COUNTERSINK, E_TAPERED) and not 0 < el.angle < 180:
            raise topo.GeometryError("Element angles must be between 0 and 180 degrees.")
    if near[-1].kind == E_COUNTERSINK:
        raise topo.GeometryError("A countersink can't be the last near side element: add "
                                 "the hole under it.")
    parts = []
    z = 0.0
    d_end = near[-1].d
    for i, el in enumerate(near):
        below = near[i + 1] if i + 1 < len(near) else None
        if el.kind == E_COUNTERSINK:
            if below is None:
                raise topo.GeometryError("A countersink can't be the last near side "
                                         "element: add the hole under it.")
            if el.d <= below.d:
                raise topo.GeometryError("A countersink ({:g} mm) must be wider than the "
                                         "element under it ({:g} mm).".format(el.d, below.d))
            h = _sink_depth(el.d, below.d, el.angle)
            parts.append(_sink(el.d, below.d, 0.0, z, z - h))
            z -= h
            continue
        if below is not None and el.depth <= 0:
            raise topo.GeometryError("Every near side element but the last needs a depth "
                                     "(the last one runs to the end condition).")
        bottom = -length if below is None else z - el.depth
        if bottom >= z - 1e-9:
            raise topo.GeometryError("The near side elements go deeper than the hole. Make "
                                     "the hole deeper or the elements shallower.")
        if el.kind == E_TAPERED:
            solid, d_end = _tapered(el.d, el.angle, z, bottom)
            parts.append(solid)
        else:
            parts.append(_cyl(el.d / 2.0, bottom, z))
            d_end = el.d
        z = bottom
    if p.end == BLIND and p.tip_angle > 0:
        tip_h = (d_end / 2.0) / math.tan(math.radians(p.tip_angle / 2.0))
        parts.append(Part.makeCone(d_end / 2.0, 0.0, tip_h, App.Vector(0, 0, -length),
                                   App.Vector(0, 0, -1)))
    if far:
        if exit_depth is None:
            raise topo.GeometryError("Far side elements need an end condition where the "
                                     "hole comes out: Through All or Up To Next.")
        z = -exit_depth
        for i, el in enumerate(far):
            above_d = far[i + 1].d if i + 1 < len(far) else d_end
            if el.kind == E_COUNTERSINK:
                if el.d <= above_d:
                    raise topo.GeometryError("A far side countersink must be wider than the "
                                             "hole it opens into.")
                h = _sink_depth(el.d, above_d, el.angle)
                parts.append(_sink_up(el.d, above_d, 0.0, z, h))
                z += h
            else:
                if el.depth <= 0:
                    raise topo.GeometryError("Far side elements need a depth.")
                parts.append(_cyl(el.d / 2.0, z, z + el.depth))
                z += el.depth
        if z > -1e-9:
            raise topo.GeometryError("The far side elements reach the near face: make them "
                                     "shallower.")
    if len(parts) == 1:
        return topo.tagged(parts[0], tag)
    return topo.refine(topo.fuse(parts[0], parts[1:], tag), tag)


# ------------------------------------------------------------------ one hole

def _cyl(r, z0, z1):
    return Part.makeCylinder(r, z1 - z0, App.Vector(0, 0, z0))


def _stadium(w, length, z):
    """A slot outline at height z: width w, centres ``length`` apart along X."""
    r = w / 2.0
    a = length / 2.0
    if length <= 1e-9:
        return Part.Wire(Part.makeCircle(r, App.Vector(0, 0, z)))
    V = App.Vector
    e1 = Part.LineSegment(V(-a, -r, z), V(a, -r, z)).toShape()
    e2 = Part.ArcOfCircle(V(a, -r, z), V(a + r, 0, z), V(a, r, z)).toShape()
    e3 = Part.LineSegment(V(a, r, z), V(-a, r, z)).toShape()
    e4 = Part.ArcOfCircle(V(-a, r, z), V(-a - r, 0, z), V(-a, -r, z)).toShape()
    return Part.Wire([e1, e2, e3, e4])


def _prism(w, length, z0, z1):
    return Part.Face(_stadium(w, length, z0)).extrude(App.Vector(0, 0, z1 - z0))


def _sink(top_w, bottom_w, length, z_top, z_bottom):
    """A countersink: from width ``top_w`` at z_top down to ``bottom_w``."""
    if length <= 1e-9:
        return Part.makeCone(bottom_w / 2.0, top_w / 2.0, z_top - z_bottom,
                             App.Vector(0, 0, z_bottom))
    return Part.makeLoft([_stadium(bottom_w, length, z_bottom), _stadium(top_w, length, z_top)],
                         True, True)


def _sink_depth(outer, inner, angle):
    return (outer - inner) / 2.0 / math.tan(math.radians(angle / 2.0))


def one_hole(p, length, tag=1, sz=None, exit_depth=None):
    """The hole's solid at the origin, going down -Z from z = 0."""
    if p.kind == ADVANCED:
        return advanced_hole(p, length, tag, exit_depth)
    sz = sz or p.custom or sizing(p.kind, p.standard, p.size, p.fit, p.thread)
    slot = p.slot_length if p.kind in SLOTS else 0.0
    d = sz.d
    if d <= 0:
        raise topo.GeometryError("The hole diameter must be greater than zero.")
    d_end = d                   # diameter at the bottom (tapered holes narrow)
    if sz.taper:
        if exit_depth is not None:
            length = min(length, exit_depth + 0.5)
        d_end = d - length * sz.taper
        if d_end <= 0.25 * d:
            raise topo.GeometryError("The tapered hole is too deep for its size: it would "
                                     "close up. Make it shallower, or check it comes out of "
                                     "the body.")
        parts = [Part.makeCone(d_end / 2.0, d / 2.0, length, App.Vector(0, 0, -length))]
    else:
        parts = [_prism(d, slot, -length, 0.0)]
    top_w = d                    # width at the top face, for a near side countersink
    clear = max(0.0, p.head_clearance)
    if sz.cbore is not None:
        cd, ch = sz.cbore
        if cd <= d:
            raise topo.GeometryError("The counterbore must be wider than the hole.")
        if p.end == BLIND and length <= ch:
            raise topo.GeometryError("The hole depth must be more than the counterbore depth "
                                     "({:g} mm).".format(ch))
        parts.append(_prism(cd, slot, -ch, clear))
        if p.kind == LEGACY and p.legacy == L_CDRILL:
            # A counterdrill steps down to the hole with a cone, not a flat floor.
            if not 0 < p.cdrill_angle < 180:
                raise topo.GeometryError("The counterdrill angle must be between 0° and "
                                         "180°.")
            h = _sink_depth(cd, d, p.cdrill_angle)
            if p.end == BLIND and length <= ch + h:
                raise topo.GeometryError("The hole depth must be more than the counterdrill "
                                         "and its cone ({:g} mm).".format(ch + h))
            parts.append(_sink(cd, d, slot, -ch, -ch - h))
        top_w = cd
    if sz.csk is not None:
        if sz.csk <= d:
            raise topo.GeometryError("The countersink must be wider than the hole.")
        h = _sink_depth(sz.csk, d, sz.csk_angle)
        parts.append(_sink(sz.csk, d, slot, 0.0, -h))
        if clear > 0:
            parts.append(_prism(sz.csk, slot, 0.0, clear))
        top_w = sz.csk
    if p.near_csk is not None:
        nd, na = p.near_csk
        if nd <= top_w:
            raise topo.GeometryError("The near side countersink must be wider than the hole "
                                     "under it ({:g} mm).".format(top_w))
        parts.append(_sink(nd, top_w, slot, 0.0, -_sink_depth(nd, top_w, na)))
    if p.far_csk is not None and exit_depth is not None:
        fd, fa = p.far_csk
        d_exit = d - exit_depth * sz.taper
        if fd <= d_exit:
            raise topo.GeometryError("The far side countersink must be wider than the hole.")
        h = _sink_depth(fd, d_exit, fa)
        parts.append(_sink_up(fd, d_exit, slot, -exit_depth, h))
    if p.end == BLIND and p.tip_angle > 0 and not slot:
        tip_h = (d_end / 2.0) / math.tan(math.radians(p.tip_angle / 2.0))
        parts.append(Part.makeCone(d_end / 2.0, 0.0, tip_h, App.Vector(0, 0, -length),
                                   App.Vector(0, 0, -1)))
    if len(parts) == 1:
        return topo.tagged(parts[0], tag)
    return topo.refine(topo.fuse(parts[0], parts[1:], tag), tag)


def _sink_up(wide, narrow, slot, z_exit, h):
    """A far side countersink: wide at the exit face, narrowing back up the hole."""
    if slot <= 1e-9:
        return Part.makeCone(wide / 2.0, narrow / 2.0, h, App.Vector(0, 0, z_exit))
    return Part.makeLoft([_stadium(wide, slot, z_exit), _stadium(narrow, slot, z_exit + h)],
                         True, True)


# ------------------------------------------------------------------ depths

def _inside(point, d, solids, big):
    """[(t_in, t_out)] where the line from ``point`` along ``d`` is inside the solids."""
    seg = Part.LineSegment(point - d * 1e-6, point + d * big).toShape()
    out = []
    for s in solids:
        try:
            c = seg.common(s)
        except Exception:
            continue
        for e in c.Edges:
            ts = sorted((v.Point - point).dot(d) for v in e.Vertexes)
            if len(ts) == 2 and ts[1] - ts[0] > 1e-7:
                out.append((ts[0], ts[1]))
    return sorted(out)


def _to_surface(point, d, shape):
    faces = [shape] if shape.ShapeType == "Face" else shape.Faces
    if not faces:
        raise topo.GeometryError("Pick a face or plane to go up to.")
    f = faces[0]
    if f.Surface.TypeId == "Part::GeomPlane":
        n = f.normalAt(0, 0)
        den = d.dot(n)
        if abs(den) < 1e-9:
            raise topo.GeometryError("The surface is parallel to the holes; they never reach "
                                     "it.")
        return (f.Vertexes[0].Point - point).dot(n) / den
    ray = Part.LineSegment(point, point + d * 1e5).toShape()
    hits = [(v.Point - point).dot(d) for v in ray.section(f).Vertexes]
    hits = [t for t in hits if t > 1e-6]
    if not hits:
        raise topo.GeometryError("A hole never reaches the surface.")
    return min(hits)


def depths(p, solids):
    """(drill length, exit depth or None) for every position."""
    d = App.Vector(p.direction)
    d.normalize()
    big = topo.big_length(*solids) if solids else 1000.0
    out = []
    for pt in p.points:
        exit_depth = None
        if p.end == BLIND:
            L = p.depth
        elif p.end == THROUGH_ALL:
            segs = _inside(pt, d, solids, big)
            exit_depth = segs[-1][1] if segs else None
            L = big
        elif p.end == UP_TO_NEXT:
            segs = _inside(pt, d, solids, big)
            if not segs:
                raise topo.GeometryError("A hole doesn't go into any body (Up To Next).")
            L = segs[0][1]
            exit_depth = L
        elif p.end == UP_TO_VERTEX:
            if p.up_to is None:
                raise topo.GeometryError("Pick the vertex the holes go up to.")
            L = (p.up_to.Vertexes[0].Point - pt).dot(d)
        else:
            if p.up_to is None:
                raise topo.GeometryError("Pick the face or plane the holes go up to.")
            L = _to_surface(pt, d, p.up_to)
            if p.end == OFFSET_FROM_SURFACE:
                L -= p.offset
        if L <= 1e-6:
            raise topo.GeometryError("A hole has no depth: the end is behind its position. "
                                     "Check the end condition, or Reverse Direction.")
        out.append((L, exit_depth))
    return out


# ------------------------------------------------------------------ all holes

def tool_shape(p, base_shapes):
    if not p.points:
        raise topo.GeometryError("Pick where the holes go: a sketch with points, or click on a "
                                 "face.")
    if p.kind not in TAPS and p.thread == MODELLED:
        p.thread = TAP_DRILL
    sz = None if p.kind == ADVANCED else \
        (p.custom or sizing(p.kind, p.standard, p.size, p.fit, p.thread))
    solids = [s for b in base_shapes for s in b.Solids]
    down = App.Vector(p.direction)
    down.normalize()
    x = p.x_dir - down * p.x_dir.dot(down)
    if x.Length < 1e-9:
        x = App.Vector(1, 0, 0) if abs(down.x) < 0.9 else App.Vector(0, 1, 0)
        x = x - down * x.dot(down)
    x.normalize()
    x = App.Rotation(down, -p.slot_angle).multVec(x)
    # Local frame: -Z is down (into the material), X along the slot.
    z = -down
    y = z.cross(x)
    rot = App.Placement(App.Matrix(x.x, y.x, z.x, 0, x.y, y.y, z.y, 0, x.z, y.z, z.z, 0,
                                   0, 0, 0, 1)).Rotation
    tools = []
    cache = {}
    for pt, (L, exit_depth) in zip(p.points, depths(p, solids)):
        key = (round(L, 7), None if exit_depth is None else round(exit_depth, 7))
        if key not in cache:
            cache[key] = one_hole(p, L, p.tag, sz, exit_depth)
        tools.append(topo.transformed(cache[key], App.Placement(pt, rot), p.tag))
        if p.kind in TAPS and p.thread == MODELLED:
            tools.append(_thread(p, sz, pt, down, L, exit_depth))
    return topo.compound(tools, p.tag)


def _thread(p, sz, pt, down, L, exit_depth):
    """A modelled thread cut into a tapped hole, to the thread depth."""
    from . import thread as thr
    if p.end == BLIND:
        tl = min(p.thread_depth, L)
    else:
        tl = exit_depth if exit_depth is not None else L
    if tl <= 0:
        raise topo.GeometryError("The thread depth must be greater than zero.")
    r = sz.d / 2.0
    site = thr.Site(None, App.Vector(pt), r, App.Vector(down), True)
    h = threads.depth(sz.pitch, True)
    if sz.taper and exit_depth is not None:
        tl = min(tl, exit_depth)
    return thr._tool(site, App.Vector(pt), tl, sz.pitch, h, 1.0, False, 1, p.tag, sz.taper)


def compute(p, base, scope=None):
    if not base.ids():
        raise topo.GeometryError("There is no body to put holes in.")
    tool = tool_shape(p, [b.shape for b in base])
    res = common.apply_cut(base, tool, p.feature, p.tag, scope or common.Scope(),
                           common.Keep(), p.alloc)
    if not res.touched:
        raise topo.GeometryError("The holes don't touch any body. Check the points and the "
                                 "direction (Reverse Direction).")
    return res, tool, common.removed_material(tool, base, scope or common.Scope(), p.tag)
