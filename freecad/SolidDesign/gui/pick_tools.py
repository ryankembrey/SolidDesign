# SPDX-License-Identifier: LGPL-2.1-or-later
"""Picking more edges at once in a tool's panel, as SolidWorks offers: Select
Tangency, Select Loop (the loop of the face beside the edge that faces you, or
the other one) and Select Chain. On the right-click menu of an edge while a tool
is open, and on the button beside a list of edges (for the last edge picked).
The edges go into the panel's box like picks, so the box's own rules apply."""

import FreeCAD as App
import FreeCADGui as Gui

from ..core.features import edges as core_edges
from .selection import Sel


def _to_eye():
    try:
        return -App.Vector(Gui.ActiveDocument.ActiveView.getViewDirection())
    except Exception:
        return None


def choices(obj, sub):
    """[(menu text, tip, [edge names])] for the edge ``sub`` of ``obj``."""
    try:
        shape = obj.Shape
        edge = shape.getElement(sub)
    except Exception:
        return []
    out = []
    tan = core_edges.select_tangency(shape, edge)
    if len(tan) > 1:
        out.append(("Select Tangency", "The edges that run on smoothly from this one", tan))
    loops = core_edges.face_loops(shape, edge)
    eye = _to_eye()
    if eye is not None and len(loops) > 1:
        def facing(fl):
            f = fl[0]
            try:
                m = edge.valueAt(0.5 * (edge.FirstParameter + edge.LastParameter))
                u, v = f.Surface.parameter(m)
                return f.normalAt(u, v).dot(eye)
            except Exception:
                return 0.0
        loops.sort(key=facing, reverse=True)
    for i, (_f, names) in enumerate(loops):
        out.append(("Select Loop" if i == 0 else "Select Other Loop",
                    "The loop of edges round the face beside this edge that faces you"
                    if i == 0 else "The loop round the face on the edge's other side", names))
    names, closed = core_edges.select_chain(shape, edge)
    if len(names) > 1:
        out.append(("Select Closed Loop" if closed else "Select Chain",
                    "The open edges joined end to end with this one", names))
    return out


def add_edges(panel, box, obj, names):
    """Put ``names`` of ``obj`` in ``box`` as if each were clicked, skipping those
    already in it. Returns how many went in."""
    have = {p for p, _t in box.items}
    added = 0
    for n in names:
        res = box.accept_fn(Sel(obj, n))
        if res is None or isinstance(res, str):
            continue
        payload, text = res
        if payload in have:
            continue
        if box.multiple:
            box.items.append((payload, text))
        else:
            box.items = [(payload, text)]
        have.add(payload)
        added += 1
    if added:
        box._refresh()
        box.changed.emit()
    return added


def fill_menu(qmenu, panel, box, obj, sub):
    """Fill ``qmenu`` with the choices for an edge; False if there are none."""
    from PySide import QtGui
    opts = choices(obj, sub)
    if not box.multiple:
        opts = []
    for text, tip, names in opts:
        a = qmenu.addAction("{}  ({})".format(text, len(names)))
        a.setToolTip(tip)
        a.triggered.connect(lambda _c=False, n=names: add_edges(panel, box, obj, n))
    if not opts:
        a = qmenu.addAction("No connected edges to add")
        a.setEnabled(False)
    return bool(opts)


def edge_box(panel):
    """The active box, if it takes several edges."""
    b = getattr(panel, "active_box", None)
    return b if b is not None and b.multiple and b.isVisibleTo(panel.widget) else None


def accepts_edge(panel, obj, sub):
    """Whether the panel's active box would take this edge."""
    b = edge_box(panel)
    if b is None or not sub.startswith("Edge"):
        return False
    res = b.accept_fn(Sel(obj, sub))
    return res is not None and not isinstance(res, str)


def current_panel():
    try:
        from .sketch_panel import LAST
        p = LAST[0]
        if p is not None and not getattr(p, "_closing", False) and Gui.Control.activeDialog():
            return p
    except Exception:
        pass
    return None
