# SPDX-License-Identifier: LGPL-2.1-or-later
"""Renders the proposed standard panel parts in FreeCAD's real task view.

    SD_SHOTS=/tmp/mock xvfb-run -a -s "-screen 0 1600x1400x24" freecad tools/panel_mockup.py

Nothing is wired to a feature: the panels only show what the parts look like.
"""

import os
import time
import traceback

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from freecad.SolidDesign import icon
from freecad.SolidDesign.gui.panel import parts as P

WIDTH = int(os.environ.get("SD_WIDTH", "560"))
OUT = os.environ.get("SD_SHOTS", "/tmp/mock")
SUFFIX = os.environ.get("SD_SUFFIX", "")
os.makedirs(OUT, exist_ok=True)
LOG = open(os.path.join(OUT, "mockup%s.log" % SUFFIX), "w")


def wait(ms=300):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.01)


class Dialog(object):
    def __init__(self, form):
        self.form = form

    def getStandardButtons(self):
        return QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel

    def accept(self):
        Gui.Control.closeDialog()

    def reject(self):
        Gui.Control.closeDialog()


ADD_CUT_TIPS = {"Add": "Add material: the extrusion is fused to the bodies it touches",
                "Cut": "Remove material: the extrusion is cut from the bodies in the feature scope"}


DUMMY = []


def sel_field(what, hint, tip, empty=None):
    return P.SelectionField(what, what, hint, lambda s: None, tip, empty)


def sel_list(what, hint, tip, empty=None):
    return P.SelectionList(what, what, hint, lambda s: None, tip, empty)


def q(unit="mm", value=0.0, minimum=0.0, maximum=1e9):
    """A unit field bound to a throwaway property, so it shows the fx button."""
    obj = DUMMY[0]
    name = "Q%d" % len(obj.PropertiesList)
    obj.addProperty("App::PropertyAngle" if unit == "deg" else "App::PropertyLength", name)
    setattr(obj, name, value)
    return P.quantity(unit, value, minimum, maximum, obj=obj, prop=name)


def mode_switch(mode):
    s = P.Switch(["Add", "Cut"], tips=ADD_CUT_TIPS,
                 icons={"Add": icon("ExtrudeAdd"), "Cut": icon("ExtrudeCut")})
    s.set_value(mode)
    return s


def end_condition(current):
    c = P.combo(["Blind", "Through All", "Up To Next", "Up To Vertex", "Up To Surface",
                 "Offset From Surface", "Up To Body", "Mid Plane"], current)
    return P.hbox(c, P.flip_button("Reverse direction"))


def extrude_add():
    form, lay = P.panel_form("Extrude", icon("ExtrudeAdd"))
    lay.addWidget(mode_switch("Add"))

    g = P.Group("Sketch")
    sk = sel_field("sketch", "Click a sketch",
                          "The sketch to extrude. Press the button, then click a sketch.")
    sk.set_value("Sketch001", "Sketch001")
    g.row("Sketch", sk, "The sketch to extrude. Press the button, then click a sketch.")
    lay.addWidget(g)

    g = P.Group("From")
    g.row("Start", P.combo(["Sketch Plane", "Surface/Face/Plane", "Vertex", "Offset"]),
          "Where the extrusion starts: the sketch plane, a face, a vertex or an offset from the sketch")
    lay.addWidget(g)

    g = P.Group("Direction 1")
    g.row("End condition", end_condition("Blind"),
          "How far the extrusion goes. The arrows reverse it.")
    g.row("Depth", q("mm", 10.0), "Distance from the start to the end of the extrusion")
    g.check_row("Draft", q("deg", 1.0, 0, 89.99),
                    "Tapers the side faces by this angle")
    g.check("Merge result", "Fuse the extrusion with the bodies it touches. Off: it becomes a "
            "body of its own.", True)
    lay.addWidget(g)

    lay.addWidget(P.Group("Direction 2", "Extrude the other way too", checkable=True,
                          checked=False))
    lay.addWidget(P.Group("Thin Feature", "Extrude a wall of constant thickness from the "
                          "sketch's curves instead of filling it", checkable=True, checked=False))

    g = P.Group("Selected Contours")
    lst = sel_list("regions", "Click regions of the sketch in the 3D view",
                          "Extrude only some regions of the sketch. Empty: the whole sketch.",
                          empty="Whole sketch")
    g.wide(lst)
    lay.addWidget(g)
    lay.addStretch(1)
    return form


def extrude_cut():
    form, lay = P.panel_form("Extrude", icon("ExtrudeCut"))
    msg = P.Message()
    msg.set("Direction 2 doesn't reach Body 2: it ends inside it.", "warning")
    lay.addWidget(msg)
    lay.addWidget(mode_switch("Cut"))

    g = P.Group("Sketch")
    sk = sel_field("sketch", "Click a sketch",
                          "The sketch to extrude. Press the button, then click a sketch.")
    sk.set_value("Sketch002", "Sketch002")
    g.row("Sketch", sk, "The sketch to extrude. Press the button, then click a sketch.")
    lay.addWidget(g)

    g = P.Group("Direction 1")
    g.row("End condition", end_condition("Up To Surface"),
          "How far the extrusion goes. The arrows reverse it.")
    face = sel_field("face", "Click a face or plane",
                            "The face or plane the extrusion ends at")
    face.set_value("Face6", "Face6 · Body 1")
    g.row("Face", face, "The face or plane the extrusion ends at")
    g.check("Flip side to cut", "Remove the material outside the profile instead of inside it")
    lay.addWidget(g)

    g = P.Group("Direction 2", "Extrude the other way too", checkable=True, checked=True)
    g.row("End condition", end_condition("Through All"),
          "How far the extrusion goes the other way")
    lay.addWidget(g)

    g = P.Group("Thin Feature", "Extrude a wall of constant thickness", checkable=True,
                checked=True)
    g.row("Type", P.combo(["One-Direction", "Mid-Plane", "Two-Direction"]),
          "Which side of the sketch's curves the wall grows on")
    g.row("Thickness", P.hbox(q("mm", 2.0), P.flip_button("Grow the wall on the "
                                                                    "other side")),
          "Wall thickness. The arrows put it on the other side of the curves.")
    lay.addWidget(g)

    g = P.Group("Feature Scope")
    sw = P.Switch(["All bodies", "Selected bodies"],
                  tips={"All bodies": "Cut every body the extrusion passes through",
                        "Selected bodies": "Cut only the bodies listed below"})
    sw.set_value("Selected bodies")
    g.wide(sw)
    bodies = sel_list("bodies", "Click bodies in the 3D view or tree",
                             "The bodies this feature cuts")
    bodies.set_items([("b1", "Body 1"), ("b3", "Housing")])
    bodies.set_active(True)
    g.wide(bodies)
    g.check("Auto-select", "Pick the bodies the extrusion touches; untick to choose them",
            False)
    lay.addWidget(g)
    lay.addStretch(1)
    return form


def fillet():
    form, lay = P.panel_form("Fillet", icon("Fillet"))
    msg = P.Message()
    msg.set("Radius 6 mm is too large for Edge7: its faces are 4 mm wide.", "error")
    lay.addWidget(msg)

    g = P.Group("Items to Fillet")
    g.row("Radius", q("mm", 6.0), "Radius of the rounds")
    edges = sel_list("edges", "Click edges, faces or a body in the 3D view",
                            "The edges to round. A face rounds all its edges; a body all of its.")
    edges.set_items([("e12", "Edge12 · Body 1"), ("e7", "Edge7 · Body 1"),
                     ("f3", "Face3 · Body 2 (4 edges)")])
    edges.set_active(True)
    g.wide(edges)
    g.check("Tangent propagation", "Also round the edges tangent to the ones you picked", True)
    lay.addWidget(g)

    g = P.Group("Setback", "Corner blending where three rounded edges meet", checkable=True,
                checked=False)
    lay.addWidget(g)
    lay.addStretch(1)
    return form


def gallery():
    form, lay = P.panel_form("Panel parts")

    g = P.Group("Single pick: SelectionField")
    f1 = sel_field("sketch", "Click a sketch", "Empty, not picking")
    g.row("Empty", f1, "Empty, not picking")
    f2 = sel_field("sketch", "Click a sketch", "Picking")
    f2.set_active(True)
    g.row("Picking", f2, "Picking: clicks in the 3D view go here")
    f3 = sel_field("face", "Click a face", "Filled")
    f3.set_value("Face6", "Face6 · Body 1")
    g.row("Filled", f3, "Filled")
    lay.addWidget(g)

    g = P.Group("Several picks: SelectionList")
    l1 = sel_list("faces", "Click faces in the 3D view", "Empty")
    g.wide(l1)
    l2 = sel_list("faces", "Click faces in the 3D view", "Picking, empty")
    l2.set_active(True)
    g.wide(l2)
    lay.addWidget(g)

    g = P.Group("Rows")
    g.row("Choice", P.combo(["Blind", "Through All"]), "A drop-down")
    g.row("With flip", end_condition("Blind"), "A drop-down and a flip button")
    g.row("Quantity", q("mm", 10.0), "A unit field; the button sets an expression")
    g.check_row("Optional value", q("deg", 1.0), "A check box that turns a field on",
                checked=True)
    g.check("Option", "A check box across both columns", True)
    g.wide(P.Switch(["First", "Second", "Third"],
                    tips={"First": "One of a few choices"}), "One of a few choices")
    lay.addWidget(g)

    m1 = P.Message()
    m1.set("An error: the feature can't be made, OK is greyed out.", "error")
    m2 = P.Message()
    m2.set("A warning: made, but something is worth knowing.", "warning")
    lay.addWidget(m1)
    lay.addWidget(m2)
    lay.addStretch(1)
    return form


def task_view():
    for w in Gui.getMainWindow().findChildren(QtWidgets.QWidget):
        if w.metaObject().className() == "Gui::TaskView::TaskView" and w.isVisible():
            return w
    return None


def show(name, build):
    form = build()
    Gui.Control.showDialog(Dialog(form))
    wait(700)
    tv = task_view()
    if tv is None:
        LOG.write("no task view for %s\n" % name)
    else:
        # Crop to the panel's height.
        h = min(tv.height(), form.mapTo(tv, QtCore.QPoint(0, form.sizeHint().height())).y() + 12)
        tv.grab(QtCore.QRect(0, 0, tv.width(), h)).save(os.path.join(OUT, name + SUFFIX + ".png"))
        LOG.write("shot %s\n" % name)
    form.hide()
    form.setParent(None)
    show.keep.append(form)
    Gui.Control.closeDialog()
    wait(300)


show.keep = []


def main():
    mw = Gui.getMainWindow()
    mw.resize(1600, 1380)
    doc = App.newDocument("Mockup")
    DUMMY.append(doc.addObject("App::FeaturePython", "Values"))
    Gui.activateWorkbench("SolidDesignWorkbench")
    wait(800)
    docks = [d for d in mw.findChildren(QtWidgets.QDockWidget) if d.isVisible()]
    for d in docks:
        LOG.write("dock %r %r %d\n" % (d.objectName(), d.windowTitle(), d.width()))
    tasks = [d for d in docks if d.objectName() == "Tasks"]
    left = tasks or [d for d in docks if d.objectName() in ("Model", "Combo View")]
    if left:
        mw.resizeDocks(left, [WIDTH] * len(left), QtCore.Qt.Horizontal)
        for d in left:
            d.setMinimumWidth(WIDTH)
    wait(300)
    for d in left:
        LOG.write("after %r %d\n" % (d.objectName(), d.width()))
    for name, build in (("extrude_add", extrude_add), ("extrude_cut", extrude_cut),
                        ("fillet", fillet), ("gallery", gallery)):
        try:
            show(name, build)
        except Exception:
            LOG.write(traceback.format_exc())
    LOG.close()
    App.closeDocument(doc.Name)
    wait(200)
    mw.close()


QtCore.QTimer.singleShot(500, main)
