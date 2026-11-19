# SPDX-License-Identifier: LGPL-2.1-or-later
"""Pick a sketch plane: what Sketch (and Extrude, Revolve...) do with nothing
selected, as in SolidWorks.

The part's origin planes are hidden; while this panel is open they show, so one
can be clicked, and a planar face of a body or a reference plane works too.
When the panel closes, the planes go back to how they were.
"""

import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from ..app import util
from .panel import parts

# FreeCAD's isometric view (Std_ViewIsometric), as a camera rotation
ISOMETRIC_AXIS = (0.74290609, 0.30772209, 0.59447283)
ISOMETRIC_ANGLE = 1.2171158

_closed = []        # panels FreeCAD has closed: kept so PySide doesn't delete them early


def plane_target(obj, sub):
    """(object, sub) to attach a sketch to, for a plane or planar face pick, or None.
    A face of a body maps to the same face of the feature at the bar."""
    if obj is None:
        return None
    if obj.TypeId in ("Part::DatumPlane", "App::Plane"):
        return obj, ""
    if util.role(obj) == "refgeom" and obj.Proxy.KIND == "plane":
        return obj, "Face1"
    if util.role(obj) == "refgeom" and obj.Proxy.KIND == "csys":
        return obj, ""          # its XY plane
    if not sub.startswith("Face"):
        return None
    try:
        f = obj.getSubObject(sub)
    except Exception:
        return None
    if f is None or f.Surface.TypeId != "Part::GeomPlane":
        return None
    if util.is_body_view(obj):
        from ..app import part as part_mod
        from .selection import map_to_feature
        part = part_mod.source_part(obj)
        tip = part.Tip if part is not None else None
        name = map_to_feature(f, tip) if tip is not None else None
        if name:
            return tip, name
    return obj, sub


class PlanePrompt(object):
    def __init__(self, doc, part, then, title="Sketch"):
        self.doc = doc
        self.part = part
        self.then = then
        self.done = False
        self._closed_already = False
        self.form, lay = parts.panel_form(title, ":/icons/SketcherWorkbench.svg")
        self._form = self.form          # FreeCAD clears .form when it closes the dialog
        g = parts.Group("Sketch Plane")
        self.field = parts.SelectionField(
            "Plane", "plane", "Click a plane or face", lambda s: None,
            "The plane to sketch on: an origin plane, a plane you made, or a planar face of "
            "a body")
        self.field.set_active(True)
        g.row("Plane", self.field, "The plane to sketch on: an origin plane, a plane you "
              "made, or a planar face of a body")
        g.note("Click a plane or a planar face in the 3D view or the tree.")
        lay.addWidget(g)
        lay.addStretch(1)
        self._shown = []
        for o in part.Origin:
            if o.TypeId == "Part::DatumPlane" and o.ViewObject is not None and \
                    not o.ViewObject.Visibility:
                o.ViewObject.Visibility = True
                self._shown.append(o)
        Gui.Selection.clearSelection()
        Gui.Selection.addObserver(self)
        if self._shown and not self._anything_else_shown():
            QtCore.QTimer.singleShot(50, self._frame_planes)

    def _anything_else_shown(self):
        """Whether the 3D view shows anything besides the planes (then the view
        is left where the user has it)."""
        for o in self.doc.Objects:
            if o in self._shown or o.ViewObject is None or not o.ViewObject.Visibility:
                continue
            shape = getattr(o, "Shape", None)
            if shape is not None and not shape.isNull() and (shape.Faces or shape.Edges):
                return True
        return False

    def _frame_planes(self):
        # An empty part: show the planes from the corner, as a new SolidWorks part
        # does, rather than edge-on from the top. The camera is turned directly:
        # FreeCAD's animated turn would undo the fit.
        if self._closed_already:
            return
        try:
            from pivy import coin
            view = Gui.ActiveDocument.ActiveView
            view.getCameraNode().orientation.setValue(
                coin.SbRotation(coin.SbVec3f(*ISOMETRIC_AXIS), ISOMETRIC_ANGLE))
            view.fitAll()
        except Exception:
            pass

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Cancel

    # Selection observer -------------------------------------------------------
    def addSelection(self, doc, obj_name, sub, pnt):
        if self.done or doc != self.doc.Name:
            return
        target = plane_target(self.doc.getObject(obj_name), sub)
        if target is None:
            self.field.say("Pick a plane, or a flat face.")
            return
        self.done = True
        QtCore.QTimer.singleShot(0, lambda: self._finish(target))

    def _finish(self, target):
        self._close()
        self.then(target)

    def reject(self):
        self._close(from_freecad=True)
        return True

    def _close(self, from_freecad=False):
        if self._closed_already:
            return
        self._closed_already = True
        try:
            Gui.Selection.removeObserver(self)
        except Exception:
            pass
        for o in self._shown:       # the planes go back to hidden
            try:
                o.ViewObject.Visibility = False
            except Exception:
                pass
        self._shown = []
        Gui.Selection.clearSelection()
        form = self._form
        if form is not None:
            form.hide()
            form.setParent(None)
            _closed.append(form)
        if not from_freecad and Gui.Control.activeDialog():
            Gui.Control.closeDialog()


def prompt(doc, part, then, title="Sketch"):
    """Ask for a sketch plane; ``then((object, sub))`` with the pick."""
    if Gui.Control.activeDialog():
        return None
    p = PlanePrompt(doc, part, then, title)
    Gui.Control.showDialog(p)
    return p
