# SPDX-License-Identifier: LGPL-2.1-or-later
"""Pick by letters, like the link hints of Vimium and other keyboard browser
extensions: on the command line, ``sel=`` puts a short home-row label (jj, jf,
kd...) on every face, edge or vertex in view that the tool can use. Typing a
label picks that element and adds the comma, so

    :fillet 2 sel=jk,dl

fillets the two edges labelled jk and dl. ``e=``, ``f=`` and ``v=`` label only
edges, faces or vertices; ``:sel=jk,dl`` on its own just selects them, ready
for the next tool. Only what can be seen is labelled: an element hidden behind
the model, or facing away, gets none.
"""

import math

import FreeCAD as App
import FreeCADGui as Gui

# Home-row letters, easiest first: index fingers, then middle, ring, little,
# then the stretched index keys.
ALPHABET = "jfkdlsahg"
MIN_LENGTH = 2              # always two letters at least, so they become habit
SEL_KEYS = {"sel": None, "selection": None, "e": ("Edge",), "edges": ("Edge",),
            "f": ("Face",), "faces": ("Face",), "v": ("Vertex",), "vertices": ("Vertex",)}

# What each tool picks (a "Plane" is a planar face). Others: faces and edges.
TOOL_KINDS = {
    "SD_Fillet": ("Edge",), "SD_Chamfer": ("Edge",), "SD_VariableFillet": ("Edge",),
    "SD_Shell": ("Face",), "SD_Draft": ("Face",), "SD_MoveFace": ("Face",),
    "SD_DeleteFace": ("Face",), "SD_Dome": ("Face",), "SD_OffsetSurface": ("Face",),
    "SD_Thicken": ("Face",), "SD_SplitLine": ("Face",), "SD_ReplaceFace": ("Face",),
    "SD_Sketch": ("Plane",), "SD_HoleWizard": ("Plane",), "SD_Extrude": ("Plane",),
    "SD_Mirror": ("Plane",), "SD_Wrap": ("Face",),
    "SD_Plane": ("Face", "Edge", "Vertex"), "SD_Axis": ("Face", "Edge"),
    "SD_Point": ("Vertex", "Edge", "Face"), "SD_CoordinateSystem": ("Vertex",),
    "SD_CosmeticThread": ("Edge",),
}
DEFAULT_KINDS = ("Face", "Edge")
#: Tools that take a plane (an origin one, or one made with Plane) as well: sel=
#: labels the planes too, showing hidden ones while it does.
REF_PLANE_TOOLS = {"SD_Split", "SD_Mirror", "SD_Sketch", "SD_Plane", "SD_Axis", "SD_Point",
                   "SD_CoordinateSystem"}
REF_PLANE = "RefPlane"


# ------------------------------------------------------------------ labels

def codes(n, alphabet=ALPHABET, minimum=MIN_LENGTH):
    """``n`` labels, all the same length (so none starts another), easiest first:
    fewest stretches, then the home keys of the index fingers."""
    if n <= 0:
        return []
    k = len(alphabet)
    length = max(minimum, int(math.ceil(math.log(n, k))) if n > 1 else minimum)
    while k ** length < n:
        length += 1
    rank = {c: i for i, c in enumerate(alphabet)}
    out = [""]
    for _i in range(length):
        out = [s + c for s in out for c in alphabet]
    out.sort(key=lambda s: (sum(rank[c] for c in s), max(rank[c] for c in s), s))
    return out[:n]


def sel_kinds(key, cmd):
    """The element kinds a ``key=`` selection labels for tool ``cmd``, or None if
    ``key`` isn't a selection key."""
    key = (key or "").strip().lower()
    if key not in SEL_KEYS:
        return None
    if SEL_KEYS[key]:
        return SEL_KEYS[key]
    kinds = TOOL_KINDS.get(cmd, DEFAULT_KINDS)
    return kinds + (REF_PLANE,) if cmd in REF_PLANE_TOOLS else kinds


def split_selection(text):
    """(the line without its selection tokens, [(key, [codes...])])."""
    keep, sels = [], []
    for tok in text.strip().lstrip(":").split(" "):
        if "=" in tok and tok.split("=", 1)[0].strip().lower() in SEL_KEYS:
            k, v = tok.split("=", 1)
            sels.append((k.strip().lower(), [c for c in v.split(",") if c]))
        elif tok:
            keep.append(tok)
    return " ".join(keep), sels


# ------------------------------------------------------------------ what can be seen

class Hint(object):
    """A label on an element: ``code``, the body view ``obj`` and ``sub``
    ("Edge3"), and where it shows (pixels from the widget's top left)."""

    def __init__(self, obj, sub, kind, x, y):
        self.obj, self.sub, self.kind = obj, sub, kind
        self.x, self.y = x, y
        self.code = ""

    def key(self):
        return (self.obj.Document.Name, self.obj.Name, self.sub)


def _anchors(el, kind):
    """Points on an element to try, best first: a face's inside, an edge's
    middle, a vertex."""
    if kind == "Vertex":
        return [el.Point]
    if kind == "Edge":
        a, b = el.FirstParameter, el.LastParameter
        return [el.valueAt(a + (b - a) * t) for t in (0.5, 0.3, 0.7)]
    pts = []
    try:
        from ..core.features.profile import face_point
        pts.append(face_point(el))
    except Exception:
        pass
    u0, u1, v0, v1 = el.ParameterRange
    for fu, fv in ((0.5, 0.5), (0.3, 0.3), (0.7, 0.7), (0.3, 0.7), (0.7, 0.3)):
        p = el.Surface.value(u0 + (u1 - u0) * fu, v0 + (v1 - v0) * fv)
        try:
            if el.isInside(p, 1e-6, True):
                pts.append(p)
        except Exception:
            pass
    return pts


def _neighbours(shape, el, kind):
    """Names of the faces (and edges, for a vertex) an element lies on: a pick at
    an edge's middle often lands on the face beside it."""
    import Part
    out = set()
    kinds = (Part.Face,) if kind == "Edge" else (Part.Face, Part.Edge) if kind == "Vertex" \
        else ()
    for t in kinds:
        try:
            anc = shape.ancestorsOfType(el, t)
        except Exception:
            continue
        subs = shape.Faces if t is Part.Face else shape.Edges
        name = "Face" if t is Part.Face else "Edge"
        for a in anc:
            for i, s in enumerate(subs, 1):
                if s.isSame(a):
                    out.add("%s%d" % (name, i))
                    break
    return out


def visible(view, objs, kinds, ratio=1.0, height=None, hidden_too=False):
    """[Hint] for each element of ``objs`` of ``kinds`` that can be seen in
    ``view`` (no code yet). ``ratio``: view pixels per widget pixel. With
    ``hidden_too`` those behind the model or facing away get one as well, marked
    ``hidden``."""
    w, h = view.getSize()
    height = h / ratio if height is None else height
    try:
        to_eye = -App.Vector(view.getViewDirection())
    except Exception:
        to_eye = None
    out = []
    kinds = [k for k in kinds if k != REF_PLANE]
    for o in objs:
        shape = o.Shape
        for kind in kinds:
            planar = kind == "Plane"
            real = "Face" if planar else kind
            elems = {"Face": shape.Faces, "Edge": shape.Edges, "Vertex": shape.Vertexes}[real]
            for i, el in enumerate(elems, 1):
                sub = "%s%d" % (real, i)
                if planar and el.Surface.TypeId != "Part::GeomPlane":
                    continue
                if real == "Edge" and getattr(el, "Degenerated", False):
                    continue
                # A pick at an edge's middle often lands on a face beside it.
                near = _neighbours(shape, el, real) if real != "Face" else set()
                two_sided = shape.ShapeType == "Shell" or not shape.Solids
                spare = None                    # where a hidden one's label goes
                seen = False
                for p in _anchors(el, real):
                    gx, gy = view.getPointOnViewport(p)
                    if not (0 <= gx < w and 0 <= gy < h):
                        continue
                    if spare is None:
                        spare = (gx, gy)
                    if real == "Face" and to_eye is not None and not two_sided:
                        try:
                            u, v = el.Surface.parameter(p)
                            if el.normalAt(u, v).dot(to_eye) < -1e-6:
                                break           # facing away: can't be seen
                        except Exception:
                            pass
                    info = view.getObjectInfo((int(gx), int(gy)))
                    if info and info.get("Object") != o.Name:
                        continue                # something else is in front
                    hit = info.get("Component", "") if info else ""
                    # Nothing under it: an edge or vertex on the outline.
                    if hit == sub or (real != "Face" and (not info or hit in near)):
                        out.append(Hint(o, sub, real, gx / ratio, height - gy / ratio))
                        seen = True
                        break
                if not seen and hidden_too and spare is not None:
                    hh = Hint(o, sub, real, spare[0] / ratio, height - spare[1] / ratio)
                    hh.hidden = True
                    out.append(hh)
    return out


def ref_planes(doc):
    """The planes of the parts in ``doc``: the origin's, and those made with Plane."""
    from ..app import part as part_mod
    from ..app import util
    out = []
    for part in part_mod.find_parts(doc) if doc is not None else []:
        out += [o for o in getattr(part, "Origin", []) or [] if o.TypeId == "Part::DatumPlane"]
        out += [o for o in getattr(part, "Group", []) or []
                if util.role(o) == "refgeom" and getattr(o.Proxy, "KIND", "") == "plane"]
    return out


def plane_anchor(obj, size):
    """Where a plane's label goes: an origin plane (endless, all three through the
    origin) at a corner of the square it is drawn as, so their labels are apart;
    a plane made with Plane at its middle."""
    if obj.TypeId == "Part::DatumPlane":
        try:
            # As big as it's drawn (FreeCAD sizes the origin to the model).
            bb = obj.ViewObject.getBoundingBox()
            if bb.isValid() and bb.DiagonalLength < 1e6:
                size = 0.35 * bb.DiagonalLength / math.sqrt(2.0)
        except Exception:
            pass
        return obj.Placement.multVec(App.Vector(size, size, 0))
    from ..core import topo
    try:
        return topo.centroid(obj.Shape.Faces[0])
    except Exception:
        return obj.Placement.Base


def plane_hints(view, planes, ratio=1.0, height=None, size=20.0):
    """[Hint] for the planes in view (planes are see-through: no hiding test)."""
    w, h = view.getSize()
    height = h / ratio if height is None else height
    out = []
    for o in planes:
        gx, gy = view.getPointOnViewport(plane_anchor(o, size))
        if 0 <= gx < w and 0 <= gy < h:
            out.append(Hint(o, "", "Plane", gx / ratio, height - gy / ratio))
    return out


def preselect_color():
    """FreeCAD's preselection colour (Preferences → Display → Colors)."""
    from PySide import QtGui
    try:
        v = App.ParamGet("User parameter:BaseApp/Preferences/View").GetUnsigned(
            "HighlightColor", 0xE1E114FF)
    except Exception:
        v = 0xE1E114FF
    return QtGui.QColor((v >> 24) & 255, (v >> 16) & 255, (v >> 8) & 255)


class SeeThrough(object):
    """Bodies drawn see-through while their hidden elements are labelled. Only
    what's drawn changes (the materials in the scene), not the document."""

    def __init__(self):
        self.saved = []                 # (material node, its transparency values)

    def on(self, objs, amount=0.7):
        from pivy import coin
        self.off()
        for o in objs:
            try:
                sa = coin.SoSearchAction()
                sa.setType(coin.SoMaterial.getClassTypeId())
                sa.setInterest(coin.SoSearchAction.ALL)
                sa.apply(o.ViewObject.RootNode)
                paths = sa.getPaths()
                for i in range(paths.getLength()):
                    m = paths[i].getTail()
                    self.saved.append((m, list(m.transparency.getValues())))
                    m.transparency.setValue(max(amount, m.transparency.getValues()[0]
                                                if m.transparency.getNum() else 0.0))
            except Exception as e:
                App.Console.PrintLog("Solid Design: see-through: {}\n".format(e))

    def off(self):
        for m, vals in self.saved:
            try:
                m.transparency.setValues(0, len(vals), vals)
            except Exception:
                pass
        self.saved = []


def assign(hints, keep=None, centre=None):
    """Give each hint a code, easiest for those nearest ``centre``; hints for
    elements in ``keep`` ({key: code}, already picked) keep theirs."""
    keep = keep or {}
    taken = set(keep.values())
    rest = [h for h in hints if h.key() not in keep]
    if centre is not None:
        cx, cy = centre
        rest.sort(key=lambda h: (h.x - cx) ** 2 + (h.y - cy) ** 2)
    pool = [c for c in codes(len(rest) + len(taken)) if c not in taken]
    # Picked codes may be shorter or longer than the new set: keep the new
    # length for the rest, so none starts another.
    length = len(pool[0]) if pool else MIN_LENGTH
    pool = [c for c in pool if len(c) == length and not any(t.startswith(c) or
                                                             c.startswith(t) for t in taken)]
    if len(pool) < len(rest):
        pool = [c for c in codes(len(rest) + len(taken), minimum=length + 1) if c not in taken
                and not any(t.startswith(c) or c.startswith(t) for t in taken)]
    for h in hints:
        if h.key() in keep:
            h.code = keep[h.key()]
    for h, c in zip(rest, pool):
        h.code = c
    return hints


def view_objects(doc):
    """The bodies shown in ``doc``."""
    from ..app import util
    out = []
    for o in doc.Objects if doc is not None else []:
        try:
            if util.is_body_view(o) and o.ViewObject.Visibility and not o.Shape.isNull():
                out.append(o)
        except Exception:
            pass
    return out


# ------------------------------------------------------------------ drawing

def make_overlay(widget):
    """A layer over the 3D view that draws the labels. Clicks on a label are its
    own (``clicked`` sends the label); everywhere else they go to the view."""
    from PySide import QtCore, QtGui, QtWidgets

    class Overlay(QtWidgets.QWidget):
        clicked = QtCore.Signal(str)

        def __init__(self, parent):
            super(Overlay, self).__init__(parent)
            self.setObjectName("SD_HintOverlay")
            self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
            self.setFocusPolicy(QtCore.Qt.NoFocus)
            self.setCursor(QtCore.Qt.PointingHandCursor)
            f = QtGui.QFont(self.font())
            f.setBold(True)
            f.setStyleHint(QtGui.QFont.Monospace)
            f.setFamily("Monospace")
            f.setPointSizeF(max(8.0, f.pointSizeF()))
            self.label_font = f
            self.hints = []
            self.prefix = ""
            self.picked = set()         # codes
            self.hover = None           # the hint under the pointer
            self.setMouseTracking(True)
            self.hide()

        def set_state(self, hints, prefix, picked):
            self.hints, self.prefix, self.picked = hints, prefix, set(picked)
            if self.hover is not None and self.hover not in self.shown():
                self.set_hover(None)
            self.setGeometry(self.parentWidget().rect())
            rects = [r for r, _h in self.rects()]
            if rects:
                region = QtGui.QRegion()
                for r in rects:
                    # (a little round each, for the bigger label under the pointer)
                    region = region.united(QtGui.QRegion(r.toAlignedRect().adjusted(
                        -3, -3, 3, 3)))
                self.setMask(region)
            # With no label showing, nothing here takes a click.
            self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, not rects)
            self.update()
            refresh = getattr(self.parentWidget(), "refresh", None)
            if refresh is not None:         # on the top layer: its mask follows
                refresh()

        def shown(self):
            """The hints drawn now: those that start with what has been typed."""
            return [h for h in self.hints if h.code.startswith(self.prefix) or
                    h.code in self.picked]

        def rects(self):
            """[(rect, hint)] of the labels drawn now."""
            fm = QtGui.QFontMetrics(self.label_font)
            out = []
            for h in self.shown():
                w = fm.horizontalAdvance(h.code) + 8
                ht = fm.height() + 2
                if getattr(h, "anchor", "") == "corner":
                    # A badge with its bottom right at (x, y): what it's on still shows.
                    out.append((QtCore.QRectF(h.x - w, h.y - ht, w, ht), h))
                else:
                    out.append((QtCore.QRectF(h.x - w / 2.0, h.y - ht / 2.0, w, ht), h))
            return out

        def _at(self, ev):
            pos = ev.position() if hasattr(ev, "position") else ev.posF()
            return next((h for r, h in self.rects() if r.contains(pos)), None)

        def set_hover(self, h):
            """The label under the pointer stands out, and what it's on lights up
            in the view as if the pointer were over it."""
            if h is self.hover:
                return
            self.hover = h
            self.update()
            try:
                if h is None or getattr(h, "obj", None) is None:
                    Gui.Selection.removePreselection()
                else:
                    Gui.Selection.setPreselection(h.obj, h.sub)
            except Exception:
                pass

        def mouseMoveEvent(self, ev):
            self.set_hover(self._at(ev))
            ev.ignore()

        def leaveEvent(self, ev):
            self.set_hover(None)
            super(Overlay, self).leaveEvent(ev)

        def hideEvent(self, ev):
            self.set_hover(None)
            super(Overlay, self).hideEvent(ev)

        def mousePressEvent(self, ev):
            pos = ev.position() if hasattr(ev, "position") else ev.posF()
            for r, h in self.rects():
                if r.contains(pos):
                    self.clicked.emit(h.code)
                    ev.accept()
                    return
            ev.ignore()

        def paintEvent(self, _ev):
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing, True)
            p.setFont(self.label_font)
            fm = QtGui.QFontMetrics(self.label_font)
            hl = preselect_color()
            hl_text = QtGui.QColor(20, 20, 20) if hl.lightness() > 140 else \
                QtGui.QColor(250, 250, 250)
            for r, h in self.rects():
                picked = h.code in self.picked
                hidden = getattr(h, "hidden", False)
                text = None
                if h is self.hover:
                    # Under the pointer: FreeCAD's preselection colour, a step bigger.
                    r = r.adjusted(-2, -2, 2, 2)
                    p.setPen(QtGui.QPen(hl.darker(170), 2))
                    p.setBrush(hl)
                    text = hl_text
                elif picked:
                    p.setPen(QtGui.QPen(QtGui.QColor(20, 80, 30), 1))
                    p.setBrush(QtGui.QColor(120, 210, 120))
                elif hidden:
                    # Behind the model or facing away: dashed, greyed.
                    p.setPen(QtGui.QPen(QtGui.QColor(90, 100, 120), 1, QtCore.Qt.DashLine))
                    p.setBrush(QtGui.QColor(222, 228, 238, 230))
                    text = QtGui.QColor(70, 80, 100)
                else:
                    p.setPen(QtGui.QPen(QtGui.QColor(60, 60, 60), 1))
                    p.setBrush(QtGui.QColor(255, 255, 255))
                p.drawRoundedRect(r, 3, 3)
                x = r.left() + 4
                y = r.top() + 1 + fm.ascent()
                n = 0 if picked else len(self.prefix)
                for i, ch in enumerate(h.code):
                    # Letters already typed are greyed: what is left to type stands out.
                    p.setPen(QtGui.QColor(160, 160, 160) if i < n else
                             text or QtGui.QColor(20, 20, 20))
                    p.drawText(QtCore.QPointF(x, y), ch)
                    x += fm.horizontalAdvance(ch)
            p.end()

    return Overlay(widget)
