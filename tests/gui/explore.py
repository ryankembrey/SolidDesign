# SPDX-License-Identifier: LGPL-2.1-or-later
"""A user session: work the workbench the way a person does, and report what breaks.

    SD_SHOTS=/tmp/sd_explore xvfb-run -a -s "-screen 0 1600x1000x24" freecad tests/gui/explore.py

Each scenario uses the commands, panels, tree actions, undo/redo and files as a
user would. Anything that goes wrong is logged: a failed expectation, a Python
exception, or an error in FreeCAD's Report view. SD_ONLY=name1,name2 runs some.
"""

import math
import os
import sys
import time
import traceback

import FreeCAD as App
import Part
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
SHOTS = os.environ.get("SD_SHOTS", "/tmp/sd_explore")
ONLY = [n for n in os.environ.get("SD_ONLY", "").split(",") if n]
os.makedirs(SHOTS, exist_ok=True)
LOG = open(os.path.join(SHOTS, "explore.log"), "w")
problems = []
current = [""]


def log(*a):
    LOG.write(" ".join(str(x) for x in a) + "\n")
    LOG.flush()


def wait(ms=400):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.01)


def expect(cond, what):
    log(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        problems.append("%s: %s" % (current[0], what))
    return cond


def report_text():
    for w in Gui.getMainWindow().findChildren(QtWidgets.QTextEdit):
        if w.metaObject().className() == "Gui::DockWnd::ReportOutput":
            return w.toPlainText()
    return ""


def shot(name):
    Gui.getMainWindow().grab().save(os.path.join(SHOTS, current[0] + "_" + name + ".png"))


# ----------------------------------------------------------------- helpers

from freecad.SolidDesign.app import part as app_part        # noqa: E402
from freecad.SolidDesign.app import util                     # noqa: E402
from freecad.SolidDesign.gui import extrude_panel           # noqa: E402
from freecad.SolidDesign.gui.panel.base import task_buttons  # noqa: E402
from freecad.SolidDesign.gui.selection import Sel           # noqa: E402
from helpers import V, circle, face_at, plane, rect, sketch   # noqa: E402


def panel():
    p = extrude_panel.LAST[0]
    return p if p is not None and not p._closing else None


def ok_enabled():
    ok, _c = task_buttons()
    return ok is not None and ok.isEnabled()


def new_doc(name):
    for d in list(App.listDocuments().values()):
        if d.Name == name:
            App.closeDocument(name)
    doc = App.newDocument(name)
    Gui.runCommand("SD_Part")
    wait(200)
    return doc, app_part.find_parts(doc)[0]


def close_panel(ok=True):
    p = panel()
    if p is None and not Gui.Control.activeDialog():
        return
    if p is not None:
        p._click_ok() if ok else p._click_cancel()
    elif Gui.Control.activeDialog():
        okb, cancel = task_buttons()
        b = okb if ok else cancel
        if b is not None:
            b.click()
        else:
            Gui.Control.closeDialog()
    wait(500)


def run_cmd(name, ms=700):
    Gui.runCommand(name)
    wait(ms)
    return panel()


def select(doc, obj, sub=""):
    Gui.Selection.clearSelection()
    if sub:
        Gui.Selection.addSelection(doc.Name, obj.Name, sub)
    else:
        Gui.Selection.addSelection(doc.Name, obj.Name)


def pick(p, obj, sub="", point=None):
    """A click in the view, as the panel receives it."""
    p.route(Sel(obj, sub, point))
    wait(500)


def body_views(part):
    return app_part.body_views(part)


def view_named(part, label):
    for v in body_views(part):
        if app_part.clean_label(v.Label) == label:
            return v
    return None


def plate_sketch(doc, part, w=40, d=30, holes=()):
    sk = sketch(doc, plane(part, "Top Plane"))
    rect(sk, 0, 0, w, d)
    for x, y, r in holes:
        circle(sk, x, y, r)
    app_part.add_to_part(part, sk)
    doc.recompute()
    return sk


def extrude_ui(doc, part, sk, depth=10.0, mode="Add", ok=True):
    """Extrude a sketch through the command and panel, as a user does."""
    select(doc, sk)
    p = run_cmd("SD_Extrude")
    if p is None:
        return None
    if mode == "Cut":
        p.mode.buttons["Cut"].click()
        wait(300)
    p.d1.depth.spin.setProperty("rawValue", float(depth))
    wait(500)
    obj = p.obj
    if ok:
        close_panel(True)
    return obj


def context_action(obj, text):
    """Run an entry of an object's context menu in the tree."""
    menu = QtWidgets.QMenu()
    vp = obj.ViewObject.Proxy
    vp.setupContextMenu(obj.ViewObject, menu)
    for a in menu.actions():
        if a.text() == text:
            a.trigger()
            wait(500)
            return True
    return False


def tree_widget():
    for w in Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget):
        if w.metaObject().className() == "Gui::TreeWidget" and w.isVisible():
            return w
    return None


def tree_lines():
    t = tree_widget()
    out = []
    if t is None:
        return out

    def walk(item, depth):
        out.append("  " * depth + item.text(0))
        for i in range(item.childCount()):
            walk(item.child(i), depth + 1)
    for i in range(t.topLevelItemCount()):
        walk(t.topLevelItem(i), 0)
    return out


def errors_in_doc(doc):
    out = []
    for o in doc.Objects:
        if "Invalid" in o.State or "Error" in o.State:
            out.append("%s %s" % (o.Label, o.State))
        msg = getattr(o, "ErrorMessage", "")
        if msg:
            out.append("%s: %s" % (o.Label, msg))
    return out


# ----------------------------------------------------------------- scenarios

SCENARIOS = []


def scenario(fn):
    SCENARIOS.append(fn)
    return fn


@scenario
def sketch_on_plane_then_extrude():
    """Select Top Plane, press Extrude: a sketch starts; closing it opens Extrude."""
    doc, part = new_doc("S1")
    top = plane(part, "Top Plane")
    select(doc, top)
    Gui.runCommand("SD_Extrude")
    wait(600)
    sk = Gui.ActiveDocument.getInEdit()
    expect(sk is not None and sk.Object.TypeId.startswith("Sketcher"), "a sketch is in edit")
    if sk is None:
        return
    sk = sk.Object
    rect(sk, 0, 0, 30, 20)
    sk.recompute()
    Gui.ActiveDocument.resetEdit()
    wait(1000)
    p = panel()
    expect(p is not None and p.obj.Sketch is sk, "closing the sketch opens Extrude with it")
    if p is None:
        return
    expect(ok_enabled(), "OK is enabled")
    close_panel(True)
    expect(len(body_views(part)) == 1, "one body after OK")
    expect(not errors_in_doc(doc), "no errors: %s" % errors_in_doc(doc))
    expect(sk.ViewObject.Visibility is False, "the sketch is hidden after the feature")


@scenario
def sketch_tool_then_extrude_with_no_selection():
    """Sketch with nothing selected: the planes show and one is asked for; then
    Extrude with nothing selected uses the one unused sketch."""
    doc, part = new_doc("S2")
    wait(300)
    expect(not any(o.ViewObject.Visibility for o in part.Origin),
           "a new part's origin is hidden")
    Gui.Selection.clearSelection()
    Gui.runCommand("SD_Sketch")
    wait(500)
    expect(Gui.ActiveDocument.getInEdit() is None, "no sketch yet: a plane is asked for")
    planes = [o for o in part.Origin if o.TypeId == "Part::DatumPlane"]
    expect(all(o.ViewObject.Visibility for o in planes), "the planes show to be picked")
    expect(Gui.Control.activeDialog(), "the plane prompt is open")
    shot("prompt")
    Gui.Selection.addSelection(doc.Name, plane(part, "Front Plane").Name)
    wait(800)
    vp = Gui.ActiveDocument.getInEdit()
    expect(vp is not None, "picking a plane opens the sketch")
    expect(vp is not None and vp.Object.AttachmentSupport[0][0] is plane(part, "Front Plane"),
           "on the picked plane")
    if vp is None:
        return
    sk = vp.Object
    rect(sk, 0, 0, 20, 20)
    Gui.ActiveDocument.resetEdit()
    wait(500)
    expect(not any(o.ViewObject.Visibility for o in planes), "the planes hide again")
    Gui.Selection.clearSelection()
    p = run_cmd("SD_Extrude")
    expect(p is not None and p.obj.Sketch is sk, "the one unused sketch is used")
    close_panel(True)
    expect(len(body_views(part)) == 1, "one body")


@scenario
def plane_prompt_cancel_and_extrude_with_nothing():
    doc, part = new_doc("S2b")
    planes = [o for o in part.Origin if o.TypeId == "Part::DatumPlane"]
    Gui.Selection.clearSelection()
    Gui.runCommand("SD_Sketch")
    wait(500)
    close_panel(False)
    expect(not Gui.Control.activeDialog(), "Cancel closes the prompt")
    expect(not any(o.ViewObject.Visibility for o in planes), "and the planes hide")
    expect(not [o for o in doc.Objects if o.TypeId.startswith("Sketcher")], "no sketch made")
    # Extrude with nothing at all: a plane is asked for, then the sketch, then Extrude.
    Gui.runCommand("SD_Extrude")
    wait(500)
    expect(Gui.Control.activeDialog() and Gui.ActiveDocument.getInEdit() is None,
           "Extrude with nothing asks for a plane")
    Gui.Selection.addSelection(doc.Name, plane(part, "Top Plane").Name)
    wait(800)
    vp = Gui.ActiveDocument.getInEdit()
    expect(vp is not None, "then sketches")
    if vp is None:
        return
    rect(vp.Object, 0, 0, 10, 10)
    vp.Object.recompute()
    Gui.ActiveDocument.resetEdit()
    wait(900)
    p = panel()
    expect(p is not None and p.obj.Sketch is vp.Object, "then Extrude opens with it")
    close_panel(True)
    expect(len(body_views(part)) == 1, "one body")
    # The planes stay hidden from now on.
    expect(not any(o.ViewObject.Visibility for o in planes), "the planes stay hidden")


@scenario
def sketch_uses_body_edges():
    """Sketcher external geometry / projection from a Solid Design body."""
    doc, part = new_doc("S2c")
    sk = plate_sketch(doc, part)
    f1 = extrude_ui(doc, part, sk, 10)
    v = body_views(part)[0]
    select(doc, v, face_at(v, V(20, 15, 10)))
    Gui.runCommand("SD_Sketch")
    wait(800)
    vp = Gui.ActiveDocument.getInEdit()
    expect(vp is not None, "sketch on the top face")
    s2 = vp.Object
    e = None
    for i, ed in enumerate(v.Shape.Edges, 1):
        a, b = ed.Vertexes[0].Point, ed.Vertexes[-1].Point
        if abs(a.z - 10) < 1e-6 and abs(b.z - 10) < 1e-6 and abs(a.y) < 1e-6 and abs(b.y) < 1e-6:
            e = "Edge%d" % i
    try:
        s2.addExternal(v.Name, e)
        added = True
    except Exception as ex:
        log("  addExternal:", ex)
        added = False
    expect(added, "the Sketcher accepts a body edge as external geometry")
    wait(600)
    links = [(o.Name, subs) for o, subs in s2.ExternalGeometry]
    log("  external links:", links)
    expect(links and links[0][0] == f1.Name, "the link moves to the feature (%s)" % links)
    expect(len(s2.ExternalGeo) >= 3, "the edge is projected (%d external)" % len(s2.ExternalGeo))
    Gui.ActiveDocument.resetEdit()
    wait(500)
    f1.Depth = 20
    doc.recompute()
    wait(300)
    expect("Invalid" not in s2.State, "the sketch follows the plate (%s)" % s2.State)
    ext = s2.ExternalGeo[-1] if s2.ExternalGeo else None
    log("  external after:", ext)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def extrude_pick_sketch_in_panel():
    doc, part = new_doc("S3")
    sk1 = plate_sketch(doc, part)
    sk2 = plate_sketch(doc, part, 10, 10)
    Gui.Selection.clearSelection()
    p = run_cmd("SD_Extrude")
    expect(p is not None and p.obj.Sketch is None, "two unused sketches: none chosen")
    expect(not ok_enabled(), "OK disabled without a sketch")
    expect(p.active_box is p.sketch_box, "the sketch box waits for a pick")
    Gui.Selection.addSelection(doc.Name, sk2.Name)
    wait(600)
    expect(p.obj.Sketch is sk2, "clicking a sketch in the tree fills the box")
    expect(ok_enabled(), "OK enabled once a sketch is picked")
    close_panel(True)
    expect(not errors_in_doc(doc), "no errors: %s" % errors_in_doc(doc))
    _ = sk1


@scenario
def edit_and_cancel():
    doc, part = new_doc("S4")
    sk = plate_sketch(doc, part)
    f = extrude_ui(doc, part, sk, 10)
    vol = body_views(part)[0].Shape.Volume
    f.ViewObject.Proxy.doubleClicked(f.ViewObject)
    wait(700)
    p = panel()
    expect(p is not None and p.obj is f, "double-click opens the feature's panel")
    p.d1.depth.spin.setProperty("rawValue", 25.0)
    wait(600)
    close_panel(False)
    expect(abs(f.Depth.Value - 10) < 1e-9, "Cancel restores the depth (%s)" % f.Depth)
    expect(abs(body_views(part)[0].Shape.Volume - vol) < 1e-6, "Cancel restores the body")
    f.ViewObject.Proxy.doubleClicked(f.ViewObject)
    wait(700)
    p = panel()
    p.d1.depth.spin.setProperty("rawValue", 25.0)
    wait(600)
    close_panel(True)
    expect(abs(f.Depth.Value - 25) < 1e-9, "OK keeps the new depth")
    expect(body_views(part)[0].Shape.Volume > vol * 2, "the body grew")


@scenario
def undo_redo():
    doc, part = new_doc("S5")
    sk = plate_sketch(doc, part)
    doc.recompute()
    f = extrude_ui(doc, part, sk, 10)
    name = f.Name
    expect(len(body_views(part)) == 1, "one body")
    doc.undo()
    doc.recompute()
    wait(500)
    expect(doc.getObject(name) is None, "undo removes the feature")
    expect(len(body_views(part)) == 0, "undo removes the body (%d)" % len(body_views(part)))
    doc.redo()
    doc.recompute()
    wait(500)
    expect(doc.getObject(name) is not None, "redo brings it back")
    expect(len(body_views(part)) == 1, "redo brings the body back (%d)" % len(
        body_views(part)))
    expect(not errors_in_doc(doc), "no errors: %s" % errors_in_doc(doc))
    lines = tree_lines()
    expect(any("Solid Bodies (1)" in l for l in lines), "tree: Solid Bodies (1)")


@scenario
def save_and_reopen():
    doc, part = new_doc("S6")
    sk = plate_sketch(doc, part, holes=[(20, 15, 5)])
    f = extrude_ui(doc, part, sk, 10)
    e = f.Shape.Edges
    edge = None
    for i, ed in enumerate(e, 1):
        if ed.Curve.TypeId.endswith("Line") and abs(ed.BoundBox.ZMin - 10) < 1e-6:
            edge = "Edge%d" % i
            break
    select(doc, body_views(part)[0], edge or "Edge1")
    p = run_cmd("SD_Fillet")
    expect(p is not None and p.items.items, "Fillet with an edge preselected")
    p.radius.spin.setProperty("rawValue", 2.0)
    wait(500)
    close_panel(True)
    path = os.path.join(SHOTS, "s6.FCStd")
    doc.saveAs(path)
    App.closeDocument(doc.Name)
    wait(300)
    doc = App.openDocument(path)
    wait(1500)
    part = app_part.find_parts(doc)[0]
    expect(len(body_views(part)) == 1, "reopened: one body")
    expect(all(v.ViewObject.Proxy is not None for v in doc.Objects
               if v.ViewObject is not None and (util.is_feature(v) or util.is_body_view(v))),
           "reopened: view providers attached")
    doc.recompute()
    expect(not errors_in_doc(doc), "reopened: no errors %s" % errors_in_doc(doc))
    fil = [o for o in doc.Objects if util.is_feature(o) and o.Label.startswith("Fillet")][0]
    fil.ViewObject.Proxy.doubleClicked(fil.ViewObject)
    wait(800)
    p = panel()
    expect(p is not None and p.items.items, "reopened: Fillet edits with its edge")
    close_panel(True)
    expect(not errors_in_doc(doc), "after edit: no errors %s" % errors_in_doc(doc))
    lines = tree_lines()
    expect(any(l.strip().startswith("Fillet1") for l in lines), "tree shows Fillet1")
    shot("reopened")


@scenario
def rollback_and_insert():
    doc, part = new_doc("S7")
    sk = plate_sketch(doc, part)
    f1 = extrude_ui(doc, part, sk, 10)
    sk2 = sketch(doc, plane(part, "Top Plane"))
    circle(sk2, 20, 15, 4)
    app_part.add_to_part(part, sk2)
    doc.recompute()
    f2 = extrude_ui(doc, part, sk2, 30)
    # SolidWorks' Rollback: the bar goes just above the feature.
    expect(context_action(f2, "Rollback"), "Rollback in the context menu")
    doc.recompute()
    wait(300)
    expect(part.Tip is f1, "the bar is after the first feature")
    expect(f2.RolledBack, "the second feature is rolled back")
    expect(abs(body_views(part)[0].Shape.Volume - 40 * 30 * 10) < 1e-3,
           "the body is the plate only")
    sk3 = sketch(doc, plane(part, "Top Plane"))
    rect(sk3, 0, 0, 5, 5)
    app_part.add_to_part(part, sk3)
    doc.recompute()
    f3 = extrude_ui(doc, part, sk3, 5, mode="Cut")
    feats = util.features(part)
    expect(feats.index(f3) == feats.index(f1) + 1, "the new feature goes at the bar")
    expect(part.Tip is f3, "the bar moves below the new feature")
    expect(context_action(part, "Roll to End"), "Roll to End on the part")
    doc.recompute()
    expect(part.Tip is f2, "rolled to the end")
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def multibody_cut_with_scope():
    doc, part = new_doc("S8")
    sk = sketch(doc, plane(part, "Top Plane"))
    rect(sk, 0, 0, 10, 10)
    rect(sk, 20, 0, 30, 10)
    app_part.add_to_part(part, sk)
    doc.recompute()
    extrude_ui(doc, part, sk, 10)
    expect(len(body_views(part)) == 2, "two bodies from two rectangles")
    sk2 = sketch(doc, plane(part, "Top Plane"))
    rect(sk2, -5, 3, 35, 7)
    app_part.add_to_part(part, sk2)
    doc.recompute()
    select(doc, sk2)
    p = run_cmd("SD_Extrude")
    p.mode.buttons["Cut"].click()
    wait(300)
    p.d1.cond.setCurrentIndex(p.d1.cond.findText("Through All"))
    wait(400)
    expect(p.sec_scope.isVisible(), "Feature Scope shows with two bodies")
    p.scope_mode.buttons["Selected bodies"].click()
    wait(300)
    p.auto.setChecked(False)
    wait(300)
    expect(p.scope_box.isVisible(), "the scope list shows")
    v = body_views(part)[0]
    p.activate(p.scope_box)
    log("  scope: base ids", list(p.obj.BaseFeature.BodyIds), "view", v.BodyId,
        "accept", p._accept_scope(Sel(v)))
    pick(p, v)
    expect(len(p.scope_box.items) == 1, "picking a body adds it")
    close_panel(True)
    vols = sorted(round(b.Shape.Volume) for b in body_views(part))
    expect(vols == [600, 1000] or len(body_views(part)) == 3,
           "only the selected body is cut: %s" % vols)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def fillet_survives_sketch_change():
    doc, part = new_doc("S9")
    sk = sketch(doc, plane(part, "Top Plane"))
    rect(sk, 0, 0, 40, 30, constrain=True)
    app_part.add_to_part(part, sk)
    doc.recompute()
    f = extrude_ui(doc, part, sk, 10)
    top = None
    for i, ed in enumerate(f.Shape.Edges, 1):
        bb = ed.BoundBox
        if abs(bb.ZMin - 10) < 1e-6 and abs(bb.ZMax - 10) < 1e-6 and abs(bb.YMin) < 1e-6 \
                and abs(bb.YMax) < 1e-6:
            top = "Edge%d" % i
    select(doc, body_views(part)[0], top)
    p = run_cmd("SD_Fillet")
    p.radius.spin.setProperty("rawValue", 3.0)
    wait(500)
    close_panel(True)
    vol = body_views(part)[0].Shape.Volume
    # Make the plate wider: the fillet must stay on the same edge.
    for i, c in enumerate(sk.Constraints):
        if c.Type == "DistanceX":
            sk.setDatum(i, App.Units.Quantity("60 mm"))
    doc.recompute()
    wait(400)
    expect(not errors_in_doc(doc), "no errors after the sketch change %s" % errors_in_doc(doc))
    expect(body_views(part)[0].Shape.Volume > vol * 1.3, "the body follows the sketch")


@scenario
def revolve_about_origin_axis():
    doc, part = new_doc("S10")
    sk = sketch(doc, plane(part, "Front Plane"))
    rect(sk, 10, 0, 20, 15)
    app_part.add_to_part(part, sk)
    doc.recompute()
    select(doc, sk)
    p = run_cmd("SD_Revolve")
    expect(p is not None, "Revolve opens")
    expect(not ok_enabled(), "no axis yet: OK disabled")
    axes = [o for o in part.Origin if o.TypeId == "Part::DatumLine"]
    yaxis = [a for a in axes if "Y" in a.Label or "Z" in a.Label]
    log("  axes:", [a.Label for a in axes])
    p.activate(p.axis_box)
    target = [a for a in axes if a.Label.startswith("Z")] or yaxis
    pick(p, target[0])
    expect(p.axis_box.items, "picking an origin axis fills Axis")
    expect(ok_enabled(), "OK enabled: %s" % p.error.value())
    close_panel(True)
    expect(len(body_views(part)) == 1 and body_views(part)[0].Shape.Volume > 1000,
           "a revolved body")


@scenario
def hole_by_clicking_a_face():
    doc, part = new_doc("S11")
    sk = plate_sketch(doc, part)
    f = extrude_ui(doc, part, sk, 10)
    v = body_views(part)[0]
    top = face_at(v, V(20, 15, 10))
    Gui.Selection.clearSelection()
    p = run_cmd("SD_HoleWizard")
    expect(p is not None, "Hole Wizard opens")
    p.activate(p.positions)
    pick(p, v, top, V(10, 10, 10))
    pick(p, v, top, V(30, 20, 10))
    expect(p.obj.Sketch is not None, "a positions sketch is made")
    close_panel(True)
    expect(body_views(part)[0].Shape.Volume < 40 * 30 * 10 - 50, "material removed")
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))
    _ = f


@scenario
def body_tools_from_context_menu():
    doc, part = new_doc("S12")
    sk = sketch(doc, plane(part, "Top Plane"))
    rect(sk, 0, 0, 10, 10)
    rect(sk, 20, 0, 30, 10)
    app_part.add_to_part(part, sk)
    doc.recompute()
    extrude_ui(doc, part, sk, 10)
    v1, v2 = body_views(part)[:2]
    expect(context_action(v1, "Move/Copy Body"), "Move/Copy from the body's menu")
    p = panel()
    expect(p is not None and p.bodies.items, "the body is in the panel")
    p.dz.spin.setProperty("rawValue", 15.0)
    wait(500)
    close_panel(True)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))
    v1 = body_views(part)[0]
    select(doc, v1)
    Gui.Selection.addSelection(doc.Name, body_views(part)[1].Name)
    p = run_cmd("SD_Combine")
    expect(p is not None and len(p.bodies.items) == 2, "Combine with two preselected bodies")
    close_panel(True)
    expect(len(body_views(part)) == 1 or errors_in_doc(doc), "combined: one body")
    log("  after combine:", errors_in_doc(doc))
    expect(context_action(body_views(part)[0], "Isolate"), "Isolate")
    expect(context_action(body_views(part)[0], "Hide"), "Hide")
    expect(not body_views(part)[0].ViewObject.Visibility, "hidden")


@scenario
def patterns_and_mirror():
    doc, part = new_doc("S13")
    sk = plate_sketch(doc, part, 60, 20)
    extrude_ui(doc, part, sk, 5)
    sk2 = sketch(doc, plane(part, "Top Plane"))
    circle(sk2, 5, 10, 2)
    app_part.add_to_part(part, sk2)
    doc.recompute()
    cut = extrude_ui(doc, part, sk2, 5, mode="Cut")
    select(doc, cut)
    p = run_cmd("SD_LinearPattern")
    expect(p is not None and p.feats.items, "the selected cut fills Features to Pattern")
    xaxis = [o for o in part.Origin if o.TypeId == "Part::DatumLine" and o.Label.startswith("X")]
    p.activate(p.dir1)
    pick(p, xaxis[0])
    p.n1.spin.setValue(4)
    p.sp1.spin.setProperty("rawValue", 12.0)
    wait(600)
    expect(ok_enabled(), "pattern OK: %s" % p.error.value())
    close_panel(True)
    vol = body_views(part)[0].Shape.Volume
    expect(abs(vol - (60 * 20 * 5 - 4 * 3.14159 * 4 * 5)) < 1.0, "four holes (%.1f)" % vol)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


def face_of(obj, point, normal):
    """Name of the face of ``obj`` through ``point`` facing ``normal``."""
    for i, f in enumerate(obj.Shape.Faces, 1):
        if f.isInside(point, 1e-6, True):
            u, v = f.Surface.parameter(point)
            if f.normalAt(u, v).getAngle(normal) < 1e-6:
                return "Face%d" % i
    return ""


@scenario
def mirror_feature_picked_by_face():
    """In Features to Mirror, clicking a face picks the feature that last touched it."""
    doc, part = new_doc("S13F")
    sk = plate_sketch(doc, part, 60, 20)
    plate = extrude_ui(doc, part, sk, 5)
    sk2 = sketch(doc, plane(part, "Top Plane"),
                 attach_offset=App.Placement(App.Vector(0, 0, 5), App.Rotation()))
    circle(sk2, 10, 10, 3)
    app_part.add_to_part(part, sk2)
    doc.recompute()
    boss = extrude_ui(doc, part, sk2, 5)
    sk3 = sketch(doc, plane(part, "Top Plane"))
    circle(sk3, 25, 10, 2)
    app_part.add_to_part(part, sk3)
    doc.recompute()
    cut = extrude_ui(doc, part, sk3, 5, mode="Cut")
    Gui.Selection.clearSelection()
    p = run_cmd("SD_Mirror")
    expect(p is not None, "Mirror opens")
    if p is None:
        return
    view = body_views(part)[0]
    V = App.Vector
    p.activate(p.feats)
    pick(p, view, face_of(view, V(10, 10, 10), V(0, 0, 1)))
    expect(p.feats.payloads() == [boss.Name],
           "the boss top picks the boss (%s)" % p.feats.payloads())
    pick(p, view, face_of(view, V(30, 0, 2), V(0, -1, 0)))
    expect(plate.Name in p.feats.payloads(),
           "the plate side picks the plate (%s)" % p.feats.payloads())
    # the plate top was last touched by the boss (its hole) and the cut
    pick(p, view, face_of(view, V(50, 15, 5), V(0, 0, 1)))
    expect(cut.Name in p.feats.payloads(),
           "the plate top picks the cut, which last changed it (%s)" % p.feats.payloads())
    p.feats.clear_items()
    edge = ""
    for i, e in enumerate(view.Shape.Edges, 1):
        if abs(e.CenterOfMass.z - 10) < 1e-6:
            edge = "Edge%d" % i            # the boss's top rim
    pick(p, view, edge)
    expect(boss.Name in p.feats.payloads(), "the boss rim picks the boss (%s)"
           % p.feats.payloads())
    pick(p, view, "Vertex1")
    expect(not p.bodies.payloads(), "a vertex doesn't fall through to Bodies (%s)"
           % p.bodies.payloads())
    shot("mirror_feature_by_face")
    close_panel(False)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def mirror_faces_in_panel():
    """Faces to Mirror: the boss's faces are mirrored onto the other side."""
    doc, part = new_doc("S13G")
    sk = plate_sketch(doc, part, 60, 20)
    extrude_ui(doc, part, sk, 5)
    sk2 = sketch(doc, plane(part, "Top Plane"),
                 attach_offset=App.Placement(App.Vector(0, 0, 5), App.Rotation()))
    circle(sk2, 10, 10, 3)
    app_part.add_to_part(part, sk2)
    doc.recompute()
    extrude_ui(doc, part, sk2, 5)
    before = body_views(part)[0].Shape.Volume
    right = plane(part, "Right Plane")
    select(doc, right)
    p = run_cmd("SD_Plane")
    p.dist.spin.setProperty("rawValue", 30.0)
    wait(400)
    close_panel(True)
    mid = [o for o in part.Group if util.role(o) == "refgeom"][0]
    Gui.Selection.clearSelection()
    p = run_cmd("SD_Mirror")
    p.activate(p.plane)
    pick(p, mid)
    view = body_views(part)[0]
    V = App.Vector
    p.activate(p.faces)
    pick(p, view, face_of(view, V(13, 10, 7), V(1, 0, 0)))
    pick(p, view, face_of(view, V(10, 10, 10), V(0, 0, 1)))
    expect(len(p.faces.items) == 2, "two faces of the boss (%s)" % p.faces.items)
    expect(ok_enabled(), "mirror OK: %s" % p.error.value())
    shot("mirror_faces")
    close_panel(True)
    after = body_views(part)[0].Shape.Volume
    expect(abs(after - before - 3.14159265 * 9 * 5) < 1e-3,
           "a second boss (%.3f -> %.3f)" % (before, after))
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


def surface_views(part):
    return [v for v in body_views(part) if v.Kind == "surface"]


@scenario
def surface_tools_through_panels():
    """Delete Face, Filled Surface, Planar, Trim, Extend, Knit and Thicken, the way
    a user drives them: preselections and clicks in the view."""
    doc, part = new_doc("SRF")
    sk = plate_sketch(doc, part, 40, 30)
    extrude_ui(doc, part, sk, 10)
    v = body_views(part)[0]
    select(doc, v, face_at(v, V(20, 15, 10)))
    p = run_cmd("SD_DeleteFace")
    expect(p is not None and len(p.faces.items) == 1, "Delete Face with the top face")
    expect(not shown(p.r_tan), "Tangent fill only for Delete and Fill")
    expect(ok_enabled(), "delete OK: %s" % p.error.value())
    shot("delete_face")
    close_panel(True)
    expect([x.Kind for x in body_views(part)] == ["surface"], "the box is an open surface")

    Gui.Selection.clearSelection()
    p = run_cmd("SD_FilledSurface")
    v = body_views(part)[0]
    p.activate(p.edges)
    for a, b in ((V(0, 0, 10), V(40, 0, 10)), (V(40, 0, 10), V(40, 30, 10)),
                 (V(40, 30, 10), V(0, 30, 10)), (V(0, 30, 10), V(0, 0, 10))):
        pick(p, v, edge_at(v, a, b))
    expect(len(p.edges.items) == 4, "four boundary edges (%s)" % p.edges.items)
    p.solid.setChecked(True)
    wait(700)
    expect(ok_enabled(), "fill OK: %s" % p.error.value())
    close_panel(True)
    b = body_views(part)[0]
    expect(b.Kind == "solid" and abs(b.Shape.Volume - 12000) < 1e-3,
           "the patch closes it into a solid (%s %.3f)" % (b.Kind, b.Shape.Volume))

    flat = sketch(doc, plane(part, "Top Plane"), attach_offset=App.Placement(
        V(0, 0, 30), App.Rotation()))
    rect(flat, 0, 0, 20, 10)
    app_part.add_to_part(part, flat)
    doc.recompute()
    select(doc, flat)
    p = run_cmd("SD_PlanarSurface")
    expect(p is not None and p.sketch.items, "Planar Surface with the sketch")
    expect(ok_enabled(), "planar OK: %s" % p.error.value())
    close_panel(True)
    sv = surface_views(part)
    expect(len(sv) == 1 and abs(sv[0].Shape.Area - 200) < 1e-6, "a 20 x 10 surface")

    right = plane(part, "Right Plane")
    select(doc, right)
    p = run_cmd("SD_Plane")
    p.dist.spin.setProperty("rawValue", 5.0)
    wait(400)
    close_panel(True)
    cutter = [o for o in part.Group if util.role(o) == "refgeom"][-1]
    select(doc, cutter)
    p = run_cmd("SD_TrimSurface")
    expect(p is not None and p.tools.items, "Trim with the plane")
    sv = surface_views(part)[0]
    p.activate(p.pieces)
    pick(p, sv, face_of(sv, V(2, 5, 30), V(0, 0, 1)) or "Face1", V(2, 5, 30))
    expect(len(p.pieces.items) == 1, "a piece is picked (%s)" % p.error.value())
    wait(600)
    expect(ok_enabled(), "trim OK: %s" % p.error.value())
    p.keep.set_value("Remove selections")
    p.keep.changed.emit("Remove selections")
    wait(600)
    shot("trim")
    close_panel(True)
    sv = surface_views(part)[0]
    expect(abs(sv.Shape.Area - 150) < 1e-6, "the picked piece is removed (%.3f)"
           % sv.Shape.Area)

    sv = surface_views(part)[0]
    far = edge_at(sv, V(20, 0, 30), V(20, 10, 30))
    select(doc, sv, far)
    p = run_cmd("SD_ExtendSurface")
    expect(p is not None and len(p.edges.items) == 1, "Extend with the edge")
    p.dist.spin.setProperty("rawValue", 4.0)
    wait(600)
    expect(ok_enabled(), "extend OK: %s" % p.error.value())
    close_panel(True)
    sv = surface_views(part)[0]
    expect(abs(sv.Shape.Area - 190) < 1e-6, "extended by 4 (%.3f)" % sv.Shape.Area)

    select(doc, sv)
    p = run_cmd("SD_Thicken")
    expect(p is not None and p.obj.Body, "Thicken with the surface")
    p.t.spin.setProperty("rawValue", 2.0)
    wait(600)
    expect(ok_enabled(), "thicken OK: %s" % p.error.value())
    shot("thicken")
    close_panel(True)
    expect(not surface_views(part), "the surface is used up")
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def thicken_add_and_cut_modes():
    """One Thicken tool: Add | Cut in its panel (Thickened Cut is its Cut mode)."""
    doc, part = new_doc("THK")
    sk = plate_sketch(doc, part, 40, 30)
    extrude_ui(doc, part, sk, 20)
    top = sketch(doc, plane(part, "Top Plane"), attach_offset=App.Placement(
        V(0, 0, 20), App.Rotation()))
    rect(top, 0, 0, 40, 30)
    app_part.add_to_part(part, top)
    doc.recompute()
    select(doc, top)
    p = run_cmd("SD_PlanarSurface")
    close_panel(True)
    expect(len(surface_views(part)) == 1, "a surface on the top")
    expect("SD_ThickenCut" not in Gui.listCommands(), "no separate Thickened Cut command")
    select(doc, surface_views(part)[0])
    p = run_cmd("SD_Thicken")
    expect(p is not None and p.mode.value() == "Add", "Thicken opens in Add")
    expect(shown(p.r_merge), "Add: Merge result shows")
    p.mode.buttons["Cut"].click()
    wait(400)
    expect(p.obj.Mode == "Cut" and not shown(p.r_merge), "Cut: no Merge result")
    p.side.buttons["Both Sides"].click()
    p.t.spin.setProperty("rawValue", 4.0)
    wait(800)
    expect(ok_enabled(), "thickened cut OK: %s" % p.error.value())
    expect(p.obj.Label.startswith("Thicken-Cut"), "labelled as a cut (%s)" % p.obj.Label)
    shot("thicken_cut")
    close_panel(True)
    vol = sum(b.Shape.Volume for b in body_views(part) if b.Kind == "solid")
    expect(abs(vol - (24000 - 1200 * 2)) < 1e-3, "2 mm cut off the top (%.3f)" % vol)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def surface_features_through_panels():
    """Extruded and Revolved Surface from the Surfaces toolbar: the feature's panel
    opens in Surface; solid-only rows hide; switching modes keeps working."""
    doc, part = new_doc("SFX")
    sk = sketch(doc, plane(part, "Top Plane"))
    sk.addGeometry(Part.ArcOfCircle(Part.Circle(V(0, 0, 0), V(0, 0, 1), 10), 0, math.pi))
    app_part.add_to_part(part, sk)
    doc.recompute()
    select(doc, sk)
    p = run_cmd("SD_ExtrudedSurface")
    expect(p is not None and p.obj.Mode == "Surface", "opens in Surface")
    expect(p.mode.value() == "Surface", "the switch shows Surface")
    expect(not p.sec_thin.isVisible() and shown(p.r_cap_end), "no Thin Feature; Cap end")
    expect(not shown(p.r_merge), "no Merge result for a surface")
    p.d1.depth.spin.setProperty("rawValue", 15.0)
    wait(700)
    expect(ok_enabled(), "extruded surface OK: %s" % p.error.value())
    expect(p.obj.Label.startswith("Surface-Extrude"), "label (%s)" % p.obj.Label)
    shot("extruded_surface")
    close_panel(True)
    srf = surface_views(part)
    expect(len(srf) == 1 and abs(srf[0].Shape.Area - math.pi * 10 * 15) < 1e-4,
           "a half-cylinder surface (%s)" % [x.Shape.Area for x in srf])
    rv = sketch(doc, plane(part, "Front Plane"))
    rv.addGeometry(Part.LineSegment(V(30, 0, 0), V(35, 10, 0)))
    rv.addGeometry(Part.LineSegment(V(25, -5, 0), V(25, 20, 0)), True)
    app_part.add_to_part(part, rv)
    doc.recompute()
    select(doc, rv)
    p = run_cmd("SD_RevolvedSurface")
    wait(700)
    expect(p is not None and p.obj.Mode == "Surface", "Revolved Surface opens in Surface")
    expect(ok_enabled(), "revolved surface OK: %s" % p.error.value())
    p.mode.buttons["Add"].click()
    wait(700)
    expect(not ok_enabled(), "an open profile can't be a solid revolve")
    p.mode.buttons["Surface"].click()
    wait(700)
    expect(ok_enabled(), "back to a surface")
    close_panel(True)
    expect(len(surface_views(part)) == 2, "two surface bodies")
    expect(not body_views(part) or all(b.Kind == "surface" for b in body_views(part)),
           "no solids")
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def deform_tools_through_panels():
    """Indent, Deform, Freeform and Surface Flatten, driven through their panels."""
    from freecad.SolidDesign.app import part as ap
    doc, part = new_doc("DEF")
    sk = plate_sketch(doc, part, 60, 40)
    extrude_ui(doc, part, sk, 4)
    bs = sketch(doc, plane(part, "Top Plane"), attach_offset=App.Placement(
        V(0, 0, -6), App.Rotation()))
    circle(bs, 30, 20, 6)
    app_part.add_to_part(part, bs)
    doc.recompute()
    select(doc, bs)
    p = run_cmd("SD_Extrude")
    p.d1.depth.spin.setProperty("rawValue", 10.0)
    p.merge.setChecked(False)
    wait(500)
    close_panel(True)
    views = body_views(part)
    expect(len(views) == 2, "a plate and a boss (%d)" % len(views))
    Gui.Selection.clearSelection()
    for v in views:
        Gui.Selection.addSelection(doc.Name, v.Name)
    p = run_cmd("SD_Indent")
    expect(p is not None and p.obj.TargetBody and p.obj.ToolBody, "Indent with target and tool")
    wait(800)
    expect(p.region_list.count() == 1 and p.region_list.item(0).checkState() ==
           QtCore.Qt.Checked, "one tool region, kept")
    expect(ok_enabled(), "indent OK: %s" % p.error.value())
    p.cut.setChecked(True)
    wait(600)
    expect(not shown(p.r_t), "Cut: no thickness")
    p.cut.setChecked(False)
    wait(600)
    shot("indent")
    close_panel(True)
    plate = [v for v in body_views(part) if v.Shape.BoundBox.XLength > 50][0]
    expect(abs(plate.Shape.BoundBox.ZMin + 7) < 1e-4, "the plate wraps the boss (%.3f)"
           % plate.Shape.BoundBox.ZMin)

    Gui.Selection.clearSelection()
    p = run_cmd("SD_Deform")
    expect(p is not None and p.kind.currentText() == "Point", "Deform opens on Point")
    p.activate(p.point)
    pick(p, plate, face_at(plate, V(10, 10, 4)), V(10, 10, 4))
    p.dist.spin.setProperty("rawValue", 3.0)
    p.radius.spin.setProperty("rawValue", 8.0)
    wait(900)
    expect(ok_enabled(), "deform OK: %s" % p.error.value())
    arrows = p._drag.draggers() if p._drag else []
    expect(len(arrows) == 1 and arrows[0].prop == "Distance", "a distance arrow")
    p.kind.setCurrentText("Curve to curve")
    wait(400)
    expect(p.sec_curves.isVisible() and not p.sec_point.isVisible(), "curve rows show")
    p.kind.setCurrentText("Point")
    wait(900)
    shot("deform")
    close_panel(True)
    plate = [v for v in body_views(part) if v.Shape.BoundBox.XLength > 50][0]
    expect(abs(plate.Shape.BoundBox.ZMax - 7) < 0.1, "a 3 mm bump (%.3f)"
           % plate.Shape.BoundBox.ZMax)

    top = face_at(plate, V(40, 30, 4))
    select(doc, plate, top)
    p = run_cmd("SD_Freeform")
    expect(p is not None and p.face.items, "Freeform with the face")
    p.activate(p.points)
    pick(p, plate, top, V(45, 30, 4))
    expect(len(p.obj.ControlPoints) == 1, "a control point (%s)" % list(p.obj.ControlPoints))
    p.height.setValue(4.0)
    wait(900)
    expect(ok_enabled(), "freeform OK: %s" % p.error.value())
    arrows = p._drag.draggers() if p._drag else []
    expect(len(arrows) == 1, "an arrow on the point")
    if arrows:
        arrows[0].on_drag(5.0)
        wait(900)
        expect(abs(p.obj.Proxy.points(p.obj)[0][1] - 5.0) < 1e-9, "dragging sets the height")
    shot("freeform")
    close_panel(True)
    plate = [v for v in body_views(part) if v.Shape.BoundBox.XLength > 50][0]
    expect(plate.Shape.isValid() and plate.Shape.BoundBox.ZMax > 8.5, "pulled up (%.3f)"
           % plate.Shape.BoundBox.ZMax)

    boss = [v for v in body_views(part) if v.Shape.BoundBox.XLength < 20][0]
    side = face_at(boss, V(36, 20, 0))
    select(doc, boss, side)
    p = run_cmd("SD_SurfaceFlatten")
    expect(p is not None and p.faces.items, "Flatten with the face")
    wait(900)
    expect(ok_enabled(), "flatten OK: %s" % p.error.value())
    shot("flatten")
    close_panel(True)
    flat = surface_views(part)
    expect(len(flat) == 1 and abs(flat[0].Shape.Area - 2 * math.pi * 6 * 10) < 0.5,
           "a flat sheet of the same area (%s)" % [x.Shape.Area for x in flat])
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))
    _ = ap


@scenario
def delete_and_patch_a_boss():
    doc, part = new_doc("SRF2")
    sk = plate_sketch(doc, part, 40, 30)
    extrude_ui(doc, part, sk, 10)
    bs = sketch(doc, plane(part, "Top Plane"), attach_offset=App.Placement(
        V(0, 0, 10), App.Rotation()))
    circle(bs, 20, 15, 4)
    app_part.add_to_part(part, bs)
    doc.recompute()
    extrude_ui(doc, part, bs, 6)
    v = body_views(part)[0]
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, v.Name, face_of(v, V(24, 15, 13), V(1, 0, 0)))
    Gui.Selection.addSelection(doc.Name, v.Name, face_of(v, V(20, 15, 16), V(0, 0, 1)))
    p = run_cmd("SD_DeleteFace")
    expect(p is not None and len(p.faces.items) == 2, "the boss's two faces")
    p.dtype.setCurrentText("Delete and Patch")
    wait(700)
    expect(ok_enabled(), "patch OK: %s" % p.error.value())
    close_panel(True)
    b = body_views(part)[0]
    expect(abs(b.Shape.Volume - 12000) < 1e-3 and len(b.Shape.Faces) == 6,
           "the boss is gone, the top healed (%.3f, %d faces)" % (b.Shape.Volume,
                                                                   len(b.Shape.Faces)))
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))

@scenario
def stage4_tools_through_panels():
    """Boundary, Intersect (excluding a region), Dome and Wrap through their panels."""
    import Part as _P
    from PySide import QtCore
    doc, part = new_doc("S4G")
    c1 = sketch(doc, plane(part, "Top Plane"))
    circle(c1, 0, 0, 5)
    c2 = sketch(doc, plane(part, "Top Plane"), attach_offset=App.Placement(
        V(0, 0, 20), App.Rotation()))
    circle(c2, 0, 0, 3)
    for o in (c1, c2):
        app_part.add_to_part(part, o)
    doc.recompute()
    Gui.Selection.clearSelection()
    p = run_cmd("SD_Boundary")
    expect(p is not None and p.sec_dir2.isVisible(), "Boundary shows Direction 2")
    expect(not p.sec_guides.isVisible(), "no guide curves group (Direction 2 does that)")
    p.activate(p.profiles)
    pick(p, c1)
    pick(p, c2)
    wait(600)
    expect(ok_enabled(), "boundary OK: %s" % p.error.value())
    shot("boundary")
    close_panel(True)
    vol = body_views(part)[0].Shape.Volume
    expect(abs(vol - 3.14159265 * 20 / 3.0 * (25 + 15 + 9)) < 1e-2,
           "a cone frustum (%.3f)" % vol)

    # Intersect two overlapping boxes, excluding one region.
    a = sketch(doc, plane(part, "Top Plane"), attach_offset=App.Placement(
        V(0, 0, 40), App.Rotation()))
    rect(a, 0, 0, 10, 10)
    b = sketch(doc, plane(part, "Top Plane"), attach_offset=App.Placement(
        V(0, 0, 45), App.Rotation()))
    rect(b, 5, 5, 15, 15)
    for o in (a, b):
        app_part.add_to_part(part, o)
    doc.recompute()
    extrude_ui(doc, part, a, 10)
    fb = extrude_ui(doc, part, b, 10)
    fb.MergeResult = False
    doc.recompute()
    views = [v for v in body_views(part) if v.Shape.BoundBox.ZMin > 39]
    Gui.Selection.clearSelection()
    for v in views:
        Gui.Selection.addSelection(doc.Name, v.Name)
    p = run_cmd("SD_Intersect")
    expect(p is not None and len(p.bodies.items) == 2, "Intersect with the two boxes")
    wait(800)
    n = p.region_list.count()
    expect(n == 3, "three regions listed (%d)" % n)
    if n:
        p.region_list.item(0).setCheckState(QtCore.Qt.Checked)
        wait(800)
    expect(len(p.obj.ExcludedPoints) == 1, "ticking a region excludes it")
    expect(ok_enabled(), "intersect OK: %s" % p.error.value())
    shot("intersect")
    close_panel(True)
    kept = [v for v in body_views(part) if v.Shape.BoundBox.ZMin > 39]
    expect(len(kept) == 1 and abs(kept[0].Shape.Volume - 1000) < 1e-3,
           "one merged body without the excluded region (%s)"
           % [round(v.Shape.Volume, 3) for v in kept])

    # Dome on the boundary's top, Wrap on a cylinder.
    top_v = [v for v in body_views(part) if v.Shape.BoundBox.ZMax < 21][0]
    select(doc, top_v, face_of(top_v, V(0, 0, 20), V(0, 0, 1)))
    p = run_cmd("SD_Dome")
    expect(p is not None and len(p.faces.items) == 1, "Dome with the top face")
    p.dist.spin.setProperty("rawValue", 2.0)
    wait(600)
    expect(ok_enabled(), "dome OK: %s" % p.error.value())
    close_panel(True)
    zmax = max(v.Shape.BoundBox.ZMax for v in body_views(part) if v.Shape.BoundBox.ZMin < 1)
    expect(abs(zmax - 22) < 1e-3, "the dome rises 2 (%.4f)" % zmax)

    cy = sketch(doc, plane(part, "Top Plane"), attach_offset=App.Placement(
        V(60, 0, 0), App.Rotation()))
    circle(cy, 0, 0, 10)
    app_part.add_to_part(part, cy)
    doc.recompute()
    fc = extrude_ui(doc, part, cy, 30)
    fc.MergeResult = False
    doc.recompute()
    w = sketch(doc, plane(part, "Right Plane"), attach_offset=App.Placement(
        V(0, 0, 70), App.Rotation()))
    rect(w, -3, 10, 3, 20)
    app_part.add_to_part(part, w)
    doc.recompute()
    cv = [v for v in body_views(part) if v.Shape.BoundBox.XMin > 45][0]
    before = cv.Shape.Volume
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, w.Name)
    Gui.Selection.addSelection(doc.Name, cv.Name, face_of(cv, V(70, 0, 15), V(1, 0, 0)))
    p = run_cmd("SD_Wrap")
    expect(p is not None and p.sketch.items and p.obj.Items, "Wrap with the sketch and face")
    wait(600)
    expect(ok_enabled(), "wrap OK: %s" % p.error.value())
    shot("wrap")
    close_panel(True)
    cv = [v for v in body_views(part) if v.Shape.BoundBox.XMin > 45][0]
    expect(abs(cv.Shape.Volume - before - 0.6 / 2 * 21 * 10) < 1e-2,
           "the sketch stands 1 mm proud (%.3f)" % (cv.Shape.Volume - before))
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))

@scenario
def more_patterns_through_panels():
    """Instances to skip, Curve, Table and Fill patterns through their panels."""
    import Part as _P
    from PySide import QtCore, QtWidgets
    doc, part = new_doc("P5")
    sk = plate_sketch(doc, part, 100, 40)
    extrude_ui(doc, part, sk, 5)
    hs = sketch(doc, plane(part, "Top Plane"))
    circle(hs, 10, 10, 3)
    app_part.add_to_part(part, hs)
    doc.recompute()
    hole = extrude_ui(doc, part, hs, 5, mode="Cut")
    hole.EndCondition = "Through All"
    doc.recompute()
    vol0 = body_views(part)[0].Shape.Volume
    hv = 3.14159265 * 9 * 5

    select(doc, hole)
    p = run_cmd("SD_LinearPattern")
    x = [o for o in part.Origin if o.Label.startswith("X")][0]
    p.activate(p.dir1)
    pick(p, x)
    p.n1.spin.setValue(4)
    wait(700)
    expect(p.skip.list.count() == 3, "three instances to skip (%d)" % p.skip.list.count())
    p.skip.list.item(1).setCheckState(QtCore.Qt.Checked)
    wait(700)
    expect(list(p.obj.InstancesToSkip) == ["3,1"], "skipping (3, 1) (%s)"
           % list(p.obj.InstancesToSkip))
    expect(ok_enabled(), "pattern OK: %s" % p.error.value())
    close_panel(True)
    v = body_views(part)[0].Shape.Volume
    expect(abs(vol0 - v - 2 * hv) < 1e-3, "two more holes, one skipped (%.3f)" % (vol0 - v))

    track = sketch(doc, plane(part, "Top Plane"), attach_offset=App.Placement(
        V(0, 0, 5), App.Rotation()))
    track.addGeometry(_P.LineSegment(V(10, 30, 0), V(90, 30, 0)))
    app_part.add_to_part(part, track)
    doc.recompute()
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, track.Name)
    p = run_cmd("SD_CurvePattern")
    expect(p is not None and p.sketch.items, "Curve pattern with the sketch")
    p.activate(p.feats)
    pick(p, hole)
    wait(700)
    expect(ok_enabled() or "falls" in p.error.value() or "cuts nothing" in p.error.value(),
           "curve pattern computes (%s)" % p.error.value())
    close_panel(False)

    Gui.Selection.clearSelection()
    select(doc, hole)
    p = run_cmd("SD_TablePattern")
    expect(p is not None and p.feats.items, "Table pattern with the hole")
    p.table.item(0, 0).setText("50")
    wait(200)
    p.table.item(0, 1).setText("20")
    wait(700)
    expect(list(p.obj.Points) == ["50,20"], "a typed point (%s)" % list(p.obj.Points))
    expect(p.table.rowCount() == 2, "a new empty row appears")
    expect(ok_enabled(), "table OK: %s" % p.error.value())
    close_panel(True)

    v = body_views(part)[0]
    select(doc, v, face_at(v, V(70, 35, 5)))
    p = run_cmd("SD_FillPattern")
    expect(p is not None and p.obj.Boundary, "Fill with the top face")
    p.seed.setCurrentText("Circle")
    wait(400)
    expect(not p.sec_f.isVisible(), "a seed cut hides the features to repeat")
    p.sp.spin.setProperty("rawValue", 8.0)
    p.size.spin.setProperty("rawValue", 3.0)
    wait(900)
    expect(ok_enabled(), "fill OK: %s" % p.error.value())
    shot("fill")
    close_panel(True)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))

@scenario
def curves_through_panels():
    """Curve Through XYZ Points typed in, a Projected Curve and a Composite Curve
    from preselections, and a sweep along the typed curve."""
    import Part as _P
    doc, part = new_doc("C6")
    Gui.Selection.clearSelection()
    p = run_cmd("SD_CurveXYZ")
    expect(p is not None, "Curve Through XYZ Points opens")
    if p is None:
        return
    for r, (x, y, z) in enumerate(((0, 0, 0), (10, 5, 2), (20, 0, 8))):
        for c, v in enumerate((x, y, z)):
            p.points.table.item(r, c).setText(str(v))
            wait(100)
    wait(600)
    expect(len(p.obj.Points) == 3, "three typed points (%s)" % list(p.obj.Points))
    expect(ok_enabled(), "curve OK: %s" % p.error.value())
    curve = p.obj
    close_panel(True)
    expect(curve.Label.startswith("Curve") and not curve.ErrorMessage, "the curve is made")

    sk0 = sketch(doc, plane(part, "Top Plane"))
    circle(sk0, 40, 0, 10)
    app_part.add_to_part(part, sk0)
    doc.recompute()
    extrude_ui(doc, part, sk0, 30)
    line = sketch(doc, plane(part, "Right Plane"), attach_offset=App.Placement(
        V(0, 0, 60), App.Rotation()))
    line.addGeometry(_P.LineSegment(V(-5, 5, 0), V(5, 25, 0)))
    app_part.add_to_part(part, line)
    doc.recompute()
    v = body_views(part)[0]
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, line.Name)
    Gui.Selection.addSelection(doc.Name, v.Name, face_of(v, V(50, 0, 15), V(1, 0, 0)))
    p = run_cmd("SD_ProjectedCurve")
    expect(p is not None and p.sketch.items and p.faces.items, "Projected Curve prefilled")
    wait(600)
    if p.error.value():
        p.rev.setChecked(not p.rev.isChecked())
        wait(600)
    expect(ok_enabled(), "projected OK: %s" % p.error.value())
    shot("projected")
    close_panel(True)

    a = sketch(doc, plane(part, "Top Plane"), attach_offset=App.Placement(
        V(0, 0, 50), App.Rotation()))
    a.addGeometry(_P.LineSegment(V(0, 0, 0), V(20, 0, 0)))
    b = sketch(doc, plane(part, "Top Plane"), attach_offset=App.Placement(
        V(0, 0, 50), App.Rotation()))
    b.addGeometry(_P.LineSegment(V(20, 0, 0), V(20, 20, 0)))
    for o in (a, b):
        app_part.add_to_part(part, o)
    doc.recompute()
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, a.Name)
    Gui.Selection.addSelection(doc.Name, b.Name)
    p = run_cmd("SD_CompositeCurve")
    expect(p is not None and len(p.curves.items) == 2, "Composite with the two sketches")
    expect(ok_enabled(), "composite OK: %s" % p.error.value())
    comp = p.obj
    close_panel(True)
    expect(abs(comp.Shape.Length - 40) < 1e-6, "one 40 mm curve")

    prof = sketch(doc, plane(part, "Right Plane"))
    circle(prof, 0, 0, 1)
    app_part.add_to_part(part, prof)
    doc.recompute()
    select(doc, prof)
    p = run_cmd("SD_Sweep")
    p.activate(p.path)
    pick(p, curve)
    wait(700)
    expect(p.path.items, "the typed curve is the path")
    expect(ok_enabled(), "sweep along the curve OK: %s" % p.error.value())
    close_panel(True)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))

@scenario
def surfaces2_through_panels():
    """Ruled, Radiate, Untrim, Mid-Surface, Cut With Surface and Replace Face from
    preselections."""
    doc, part = new_doc("S7G")
    sk = plate_sketch(doc, part, 40, 30)
    extrude_ui(doc, part, sk, 10)
    v = body_views(part)[0]
    top_edges = [edge_at(v, V(0, 0, 10), V(40, 0, 10)), edge_at(v, V(40, 0, 10), V(40, 30, 10))]
    Gui.Selection.clearSelection()
    for e in top_edges:
        Gui.Selection.addSelection(doc.Name, v.Name, e)
    p = run_cmd("SD_RuledSurface")
    expect(p is not None and len(p.edges.items) == 2, "Ruled with two edges")
    expect(not p.vec.row.widget.isVisible() if hasattr(p.vec.row, "widget") else True,
           "no vector for Tangent to Surface")
    expect(ok_enabled(), "ruled OK: %s" % p.error.value())
    close_panel(True)

    v = body_views(part)[0]
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, v.Name, face_at(v, V(20, 15, 10)))
    p = run_cmd("SD_UntrimSurface")
    expect(p is not None and p.faces.items, "Untrim with the top face")
    expect(ok_enabled(), "untrim OK: %s" % p.error.value())
    close_panel(True)

    solid = [x for x in body_views(part) if x.Kind == "solid"][0]
    select(doc, solid)
    p = run_cmd("SD_MidSurface")
    expect(p is not None and p.bodies.items, "Mid-Surface with the body")
    expect(ok_enabled(), "mid-surface OK: %s" % p.error.value())
    close_panel(True)

    top = plane(part, "Top Plane")
    select(doc, top)
    p = run_cmd("SD_Plane")
    p.dist.spin.setProperty("rawValue", 6.0)
    wait(400)
    close_panel(True)
    cutter = [o for o in part.Group if util.role(o) == "refgeom"][-1]
    select(doc, cutter)
    p = run_cmd("SD_SurfaceCut")
    expect(p is not None and p.plane.items, "Cut With Surface with the plane")
    wait(600)
    expect(ok_enabled(), "surface cut OK: %s" % p.error.value())
    shot("surface_cut")
    close_panel(True)
    solid = [x for x in body_views(part) if x.Kind == "solid"][0]
    expect(abs(solid.Shape.Volume - 40 * 30 * 6) < 1e-3, "cut to 6 mm (%.3f)"
           % solid.Shape.Volume)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))

@scenario
def flex_and_scale_through_panels():
    """Flex (types switch the rows) and Scale on a preselected body."""
    doc, part = new_doc("F8")
    sk = plate_sketch(doc, part, 10, 10)
    extrude_ui(doc, part, sk, 40)
    v = body_views(part)[0]
    select(doc, v)
    p = run_cmd("SD_Flex")
    expect(p is not None and p.bodies.items, "Flex with the body")
    expect(shown(p.r_ang) and not shown(p.r_taper), "Bending shows the angle only")
    p.kind.setCurrentText("Tapering")
    wait(700)
    expect(shown(p.r_taper) and not shown(p.r_ang), "Tapering shows the taper factor")
    expect(ok_enabled(), "flex OK: %s" % p.error.value())
    arrows = sorted(p._drag.draggers(), key=lambda a: a.prop) if p._drag else []
    expect([a.prop for a in arrows] == ["TrimPlane1", "TrimPlane2"],
           "the trim planes have arrows (%s)" % [a.prop for a in arrows])
    if len(arrows) == 2:
        expect(abs(arrows[0].origin.z) < 1e-6 and arrows[0].direction.z > 0.99 and
               abs(arrows[1].origin.z - 40) < 1e-6, "one at each end, pointing in")
        arrows[0].on_drag(5.0)
        wait(800)
        expect(abs(p.obj.TrimPlane1.Value - 5.0) < 1e-9, "dragging moves trim plane 1")
        arrows[0].on_drag(0.0)
        wait(800)
    shot("flex")
    close_panel(True)
    vol = body_views(part)[0].Shape.Volume
    expect(abs(vol - 4000 * (1 - 0.5 + 0.25 / 3.0)) < 0.5, "tapered (%.2f)" % vol)
    v = body_views(part)[0]
    select(doc, v)
    p = run_cmd("SD_Scale")
    expect(p is not None and not shown(p.r_fx), "Scale: uniform by default")
    p.f.spin.setProperty("rawValue", 2.0)
    wait(700)
    expect(ok_enabled(), "scale OK: %s" % p.error.value())
    close_panel(True)
    vol2 = body_views(part)[0].Shape.Volume
    expect(abs(vol2 - vol * 8) < 1.0, "eight times the volume (%.2f)" % vol2)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))

@scenario
def stage9_through_panels():
    """Extrude along an edge; Face Face chamfer; Tapered Tap and Advanced holes."""
    doc, part = new_doc("G9")
    sk = plate_sketch(doc, part, 40, 30)
    ln = sketch(doc, plane(part, "Front Plane"))
    ln.addGeometry(Part.LineSegment(V(0, 0, 0), V(10, 10, 0)))
    app_part.add_to_part(part, ln)
    doc.recompute()
    select(doc, sk)
    p = run_cmd("SD_Extrude")
    p.d1.depth.spin.setProperty("rawValue", 10.0)
    wait(400)
    p.activate(p.dir_vec)
    pick(p, ln, "Edge1")
    wait(600)
    expect(p.obj.DirectionOfExtrusion and p.obj.DirectionOfExtrusion[0] is ln,
           "the direction of extrusion takes the sketch line")
    expect(ok_enabled(), "slanted extrude OK: %s" % p.error.value())
    close_panel(True)
    bb = body_views(part)[0].Shape.BoundBox
    expect(abs(bb.XMax - (40 + 10 * math.sqrt(0.5))) < 1e-3, "leans along the line (%.3f)"
           % bb.XMax)
    # A plain block for the rest.
    doc2, part2 = new_doc("G9b")
    sk2 = plate_sketch(doc2, part2, 40, 30)
    extrude_ui(doc2, part2, sk2, 20)
    v = body_views(part2)[0]
    Gui.Selection.clearSelection()
    p = run_cmd("SD_Chamfer")
    p.ctype.setCurrentText("Face Face")
    wait(300)
    expect(not shown(p.r_tangent), "Face Face hides tangent propagation")
    p.activate(p.items)
    pick(p, v, face_at(v, V(20, 15, 20)))
    pick(p, v, face_at(v, V(40, 15, 10)))
    expect(len(p.items.items) == 2, "two faces picked (%s)" % p.items.items)
    pick(p, v, edge_at(v, V(0, 0, 20), V(40, 0, 20)))
    expect(len(p.items.items) == 2, "an edge is refused for Face Face")
    p.d1.spin.setProperty("rawValue", 2.0)
    wait(700)
    expect(ok_enabled(), "face face chamfer OK: %s" % p.error.value())
    shot("chamfer_face_face")
    close_panel(True)
    vol = body_views(part2)[0].Shape.Volume
    expect(abs(vol - (24000 - 2 * 2 / 2.0 * 30)) < 1e-3, "one edge chamfered (%.3f)" % vol)
    v = body_views(part2)[0]
    Gui.Selection.clearSelection()
    p = run_cmd("SD_HoleWizard")
    p.activate(p.positions)
    pick(p, v, face_at(v, V(15, 15, 20)), V(10, 10, 20))
    w0 = p.form.minimumSizeHint().width()
    expect(w0 <= 380, "the Hole Wizard fits a narrow task pane (%d)" % w0)
    p.near.check.setChecked(True)
    wait(500)
    expect(shown(p.near.r_diameter) and shown(p.near.r_angle), "countersink rows show")
    p.near.check.setChecked(False)
    wait(500)
    p.kind.setCurrentText("Tapered Tap")
    wait(700)
    sizes = [p.size.itemText(i) for i in range(p.size.count())]
    expect("Rc 1/4" in sizes and "M6" not in sizes, "pipe sizes for Tapered Tap (%s)" % sizes)
    expect(shown(p.r_thread) and not shown(p.r_fit), "a tap: thread row, no fit")
    expect(ok_enabled(), "tapered tap OK: %s" % p.error.value())
    expect("Tapered Tap" in p.obj.Label, "label (%s)" % p.obj.Label)
    p.kind.setCurrentText("Advanced")
    wait(800)
    expect(not p.sec_spec.isVisible() and p.sec_adv.isVisible(), "Advanced shows elements")
    expect(p.near_els.count() == 2, "starts as counterbore over hole (%d)"
           % p.near_els.count())
    p.near_els.list.setCurrentRow(0)
    p.near_els.b_add.click()
    wait(300)
    expect(p.near_els.list.currentRow() == 1, "the new element is selected")
    p.near_els.kind.setCurrentText("Countersink")
    wait(300)
    p.near_els.d.setValue(10.0)
    wait(800)
    expect(len(p.obj.NearElements) == 3 and p.obj.NearElements[1].startswith("Countersink"),
           "a countersink between them (%s)" % list(p.obj.NearElements))
    expect(not shown(p.near_els.r_depth) and shown(p.near_els.r_angle),
           "a countersink's depth is set by its angle")
    p.near_els.list.setCurrentRow(2)
    wait(200)
    expect(not shown(p.near_els.r_depth), "the last element runs to the end: no depth")
    texts = [p.near_els.list.item(i).text() for i in range(3)]
    log("  elements:", texts)
    w1 = p.form.minimumSizeHint().width()
    expect(w1 <= 380, "Advanced fits a narrow task pane (%d)" % w1)
    expect(ok_enabled(), "advanced OK: %s" % p.error.value())
    shot("advanced_hole")
    close_panel(True)
    expect(not errors_in_doc(doc2), "no errors %s" % errors_in_doc(doc2))
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def close_document_with_panel_open():
    doc, part = new_doc("S14")
    sk = plate_sketch(doc, part)
    select(doc, sk)
    p = run_cmd("SD_Extrude")
    expect(p is not None, "panel open")
    App.closeDocument(doc.Name)
    wait(800)
    expect(not Gui.Control.activeDialog(), "the panel closes with the document")
    expect(App.ActiveDocument is None or App.ActiveDocument.Name != "S14", "document closed")


@scenario
def two_documents():
    d1, p1 = new_doc("S15a")
    sk = plate_sketch(d1, p1)
    extrude_ui(d1, p1, sk, 5)
    d2, p2 = new_doc("S15b")
    sk2 = plate_sketch(d2, p2, 10, 10)
    f = extrude_ui(d2, p2, sk2, 5)
    expect(f is not None and f.Document is d2, "Extrude works in the second document")
    expect(len(body_views(p1)) == 1 and len(body_views(p2)) == 1, "each has its body")
    App.setActiveDocument(d1.Name)
    Gui.activateView("Gui::View3DInventor", True)
    wait(300)
    fe = [o for o in d1.Objects if util.is_feature(o)][0]
    fe.ViewObject.Proxy.doubleClicked(fe.ViewObject)
    wait(700)
    p = panel()
    expect(p is not None and p.obj.Document is d1, "editing in the first document")
    close_panel(True)
    expect(not errors_in_doc(d1) and not errors_in_doc(d2), "no errors")


@scenario
def delete_middle_feature():
    doc, part = new_doc("S16")
    sk = plate_sketch(doc, part)
    f1 = extrude_ui(doc, part, sk, 10)
    sk2 = sketch(doc, plane(part, "Top Plane"))
    rect(sk2, 5, 5, 15, 15)
    app_part.add_to_part(part, sk2)
    doc.recompute()
    f2 = extrude_ui(doc, part, sk2, 5, mode="Cut")
    sk3 = sketch(doc, plane(part, "Top Plane"))
    rect(sk3, 25, 5, 35, 15)
    app_part.add_to_part(part, sk3)
    doc.recompute()
    f3 = extrude_ui(doc, part, sk3, 20)
    name = f2.Name
    select(doc, f2)
    Gui.runCommand("Std_Delete")
    wait(800)
    doc.recompute()
    expect(not [d for d in DIALOGS if d[0] == current[0]],
           "no 'might break' warning: the next feature is relinked")
    expect(doc.getObject(name) is None, "the cut is deleted")
    expect(f3.BaseFeature is f1, "the next feature is relinked to the one before")
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))
    expect(len(body_views(part)) == 1, "one body")


@scenario
def suppress_and_whats_wrong():
    doc, part = new_doc("S17")
    sk = plate_sketch(doc, part)
    f1 = extrude_ui(doc, part, sk, 10)
    sk2 = sketch(doc, plane(part, "Top Plane"))
    rect(sk2, 5, 5, 15, 15)
    app_part.add_to_part(part, sk2)
    doc.recompute()
    f2 = extrude_ui(doc, part, sk2, 5, mode="Cut")
    expect(context_action(f2, "Suppress"), "Suppress in the menu")
    doc.recompute()
    expect(f2.Suppressed, "suppressed")
    expect(abs(body_views(part)[0].Shape.Volume - 12000) < 1e-3, "the cut is gone")
    expect(context_action(f2, "Unsuppress"), "Unsuppress")
    doc.recompute()
    expect(abs(body_views(part)[0].Shape.Volume - 11500) < 1e-3, "the cut is back")
    # Break it: a cut that misses everything.
    f2.Depth = 0
    doc.recompute()
    msg = f2.ErrorMessage
    expect(bool(msg), "a zero-depth cut reports an error")
    if msg:
        expect(context_action(f2, "What's Wrong?"), "What's Wrong? in the menu")
        p = panel()
        expect(p is not None and p.error.value(), "What's Wrong? opens the panel with the error")
        close_panel(False)
    _ = f1


@scenario
def edit_sketch_of_feature():
    doc, part = new_doc("S18")
    sk = plate_sketch(doc, part)
    f = extrude_ui(doc, part, sk, 10)
    Gui.ActiveDocument.setEdit(sk.Name)
    wait(600)
    expect(Gui.ActiveDocument.getInEdit() is not None, "the sketch opens")
    sk.addGeometry(__import__("Part").Circle(V(20, 15, 0), V(0, 0, 1), 4))
    Gui.ActiveDocument.resetEdit()
    wait(600)
    doc.recompute()
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))
    expect(body_views(part)[0].Shape.Volume < 12000 - 400, "the new circle is a hole")
    expect(not sk.ViewObject.Visibility, "the sketch hides again after editing")
    _ = f


@scenario
def plane_and_sketch_on_it():
    doc, part = new_doc("S19")
    sk = plate_sketch(doc, part)
    f = extrude_ui(doc, part, sk, 10)
    v = body_views(part)[0]
    top = face_at(v, V(20, 15, 10))
    select(doc, v, top)
    p = run_cmd("SD_Plane")
    expect(p is not None and p.ref_boxes[0].items, "Plane with a face preselected")
    p.dist.spin.setProperty("rawValue", 15.0)
    wait(500)
    close_panel(True)
    pl = [o for o in part.Group if util.role(o) == "refgeom"]
    expect(len(pl) == 1, "a plane is made")
    select(doc, pl[0])
    Gui.runCommand("SD_Sketch")
    wait(600)
    vp = Gui.ActiveDocument.getInEdit()
    expect(vp is not None, "sketching on the plane")
    if vp is not None:
        circle(vp.Object, 20, 15, 5)
        Gui.ActiveDocument.resetEdit()
        wait(500)
        f2 = extrude_ui(doc, part, vp.Object, 5)
        expect(f2 is not None and not f2.ErrorMessage, "extrude from the plane's sketch")
        expect(len(body_views(part)) == 2, "a second body, above the plate (%d)" % len(
            body_views(part)))
    _ = f


@scenario
def keyboard_in_panel():
    doc, part = new_doc("S20")
    sk = plate_sketch(doc, part)
    select(doc, sk)
    p = run_cmd("SD_Extrude")
    spin = p.d1.depth.spin
    spin.setFocus()
    spin.selectAll()
    QtTest = __import__("PySide6.QtTest", fromlist=["QtTest"])
    QtTest.QTest.keyClicks(spin, "12")
    QtTest.QTest.keyClick(spin, QtCore.Qt.Key_Return)
    wait(900)
    expect(not Gui.Control.activeDialog(), "Enter in a field is OK")
    feats = util.features(part)
    expect(feats and abs(feats[-1].Depth.Value - 12) < 1e-6, "typed depth kept (%s)" % (
        feats[-1].Depth if feats else None))


@scenario
def switch_workbench_and_back():
    doc, part = new_doc("S21")
    sk = plate_sketch(doc, part)
    extrude_ui(doc, part, sk, 10)
    Gui.activateWorkbench("PartDesignWorkbench")
    wait(500)
    Gui.activateWorkbench("SolidDesignWorkbench")
    wait(500)
    select(doc, sk)
    p = run_cmd("SD_Extrude")
    expect(p is not None, "Extrude works after switching workbenches")
    close_panel(False)


def edge_at(obj, p0, p1):
    """Name of the straight edge of ``obj`` from p0 to p1 (either way)."""
    for i, e in enumerate(obj.Shape.Edges, 1):
        a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
        if ((a - p0).Length < 1e-6 and (b - p1).Length < 1e-6) or \
                ((a - p1).Length < 1e-6 and (b - p0).Length < 1e-6):
            return "Edge%d" % i
    return None


@scenario
def up_to_surface_and_direction2():
    doc, part = new_doc("R1")
    sk = plate_sketch(doc, part)
    extrude_ui(doc, part, sk, 20)
    sk2 = sketch(doc, plane(part, "Top Plane"))
    circle(sk2, 60, 15, 5)
    app_part.add_to_part(part, sk2)
    doc.recompute()
    select(doc, sk2)
    p = run_cmd("SD_Extrude")
    p.d1.cond.setCurrentIndex(p.d1.cond.findText("Up To Surface"))
    wait(400)
    expect(p.active_box is p.d1.face, "choosing Up To Surface makes the face box active")
    v = body_views(part)[0]
    pick(p, v, face_at(v, V(20, 15, 20)), V(20, 15, 20))
    expect(p.d1.face.items, "a clicked face fills the box")
    expect(ok_enabled(), "OK enabled: %s" % p.error.value())
    p.sec_d2.setChecked(True)
    wait(300)
    expect(p.obj.Direction2, "ticking Direction 2 sets it")
    p.d2.depth.spin.setProperty("rawValue", 5.0)
    wait(600)
    close_panel(True)
    vs = sorted(round(b.Shape.BoundBox.ZMax - b.Shape.BoundBox.ZMin, 3) for b in body_views(part))
    expect(25.0 in vs, "the boss goes from -5 to 20 (heights %s)" % vs)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def thin_feature_from_open_sketch():
    doc, part = new_doc("R2")
    import Part as _P
    sk = sketch(doc, plane(part, "Top Plane"))
    sk.addGeometry(_P.LineSegment(V(0, 0, 0), V(30, 0, 0)))
    sk.addGeometry(_P.LineSegment(V(30, 0, 0), V(30, 20, 0)))
    app_part.add_to_part(part, sk)
    doc.recompute()
    select(doc, sk)
    p = run_cmd("SD_Extrude")
    log("  open sketch error:", p.error.value())
    p.sec_thin.setChecked(True)
    wait(600)
    expect(p.obj.Thin, "ticking Thin Feature sets it")
    expect(ok_enabled(), "a thin feature from an open sketch: %s" % p.error.value())
    close_panel(True)
    expect(len(body_views(part)) == 1 and body_views(part)[0].Kind == "solid",
           "one solid body")
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def mid_plane_and_mode_switch_on_edit():
    doc, part = new_doc("R3")
    sk = plate_sketch(doc, part)
    f1 = extrude_ui(doc, part, sk, 10)
    sk2 = sketch(doc, plane(part, "Top Plane"))
    rect(sk2, 10, 10, 20, 20)
    app_part.add_to_part(part, sk2)
    doc.recompute()
    f2 = extrude_ui(doc, part, sk2, 30)
    expect(f2.Label.startswith("Boss-Extrude"), "an Add extrude is a Boss-Extrude")
    f2.ViewObject.Proxy.doubleClicked(f2.ViewObject)
    wait(700)
    p = panel()
    p.mode.buttons["Cut"].click()
    wait(300)
    p.d1.cond.setCurrentIndex(p.d1.cond.findText("Mid Plane"))
    wait(600)
    expect(p.obj.Label.startswith("Cut-Extrude"), "switching to Cut on edit renames it")
    expect(not p.sec_d2.isVisible(), "Mid Plane hides Direction 2")
    close_panel(True)
    expect(abs(body_views(part)[0].Shape.Volume - (12000 - 100 * 10)) < 1e-3,
           "a through cut (%.1f)" % body_views(part)[0].Shape.Volume)
    expect(f2.ViewObject.Proxy.getIcon().endswith("ExtrudeCut.svg"), "the icon is the cut's")
    _ = f1


@scenario
def chamfer_and_shell():
    doc, part = new_doc("R4")
    sk = plate_sketch(doc, part)
    extrude_ui(doc, part, sk, 20)
    v = body_views(part)[0]
    e = edge_at(v, V(0, 0, 20), V(40, 0, 20))
    select(doc, v, e)
    p = run_cmd("SD_Chamfer")
    expect(p is not None and len(p.items.items) == 1, "Chamfer with the edge")
    close_panel(True)
    expect(not errors_in_doc(doc), "chamfer: no errors %s" % errors_in_doc(doc))
    v = body_views(part)[0]
    top = face_at(v, V(20, 20, 20))
    select(doc, v, top)
    p = run_cmd("SD_Shell")
    expect(p is not None and len(p.faces.items) == 1, "Shell with the top face (%s)" % (
        p.faces.items if p else None))
    p.t.spin.setProperty("rawValue", 2.0)
    wait(800)
    expect(ok_enabled(), "shell OK: %s" % (p.error.value() if p else ""))
    close_panel(True)
    expect(not errors_in_doc(doc), "shell: no errors %s" % errors_in_doc(doc))


@scenario
def shell_multi_thickness_per_face():
    """Each multi-thickness face keeps its own value: one thinner, one thicker."""
    doc, part = new_doc("R4m")
    sk = plate_sketch(doc, part)
    extrude_ui(doc, part, sk, 20)
    v = body_views(part)[0]
    select(doc, v, face_at(v, V(20, 15, 20)))
    p = run_cmd("SD_Shell")
    p.t.spin.setProperty("rawValue", 2.0)
    wait(600)
    p.activate(p.multi)
    pick(p, v, face_at(v, V(20, 15, 0)))
    p.multi.list.item(0).setSelected(True)
    p.mt.spin.setProperty("rawValue", 0.5)
    wait(500)
    pick(p, v, face_at(v, V(40, 15, 10)))
    p.multi.list.clearSelection()
    p.multi.list.item(1).setSelected(True)
    p.mt.spin.setProperty("rawValue", 4.0)
    wait(700)
    expect(list(p.obj.MultiThickness) == [0.5, 4.0],
           "each face keeps its own thickness (%s)" % list(p.obj.MultiThickness))
    texts = [p.multi.list.item(i).text() for i in range(p.multi.list.count())]
    expect(len(texts) == 2 and "0.5 mm" in texts[0] and "4 mm" in texts[1],
           "the list shows each face's thickness (%s)" % texts)
    p.multi.list.clearSelection()
    p.multi.list.item(0).setSelected(True)
    wait(200)
    expect(abs(p.mt.value() - 0.5) < 1e-9, "selecting a face shows its value")
    expect(ok_enabled(), "shell OK: %s" % p.error.value())
    shot("shell_multi")
    close_panel(True)
    vol = body_views(part)[0].Shape.Volume
    want = 40 * 30 * 20 - 34 * 26 * 19.5
    expect(abs(vol - want) < 1e-3, "thinner floor, thicker side (%.3f, want %.3f)" % (vol, want))
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


def _width_at(shape, z):
    box = App.BoundBox()
    for w in shape.slice(V(0, 0, 1), z):
        box.add(w.BoundBox)
    return box.XLength


@scenario
def draft_neutral_plane():
    doc, part = new_doc("D1")
    sk = plate_sketch(doc, part)
    extrude_ui(doc, part, sk, 20)
    v = body_views(part)[0]
    sides = [face_at(v, V(20, 0, 10)), face_at(v, V(40, 15, 10)), face_at(v, V(20, 30, 10)),
             face_at(v, V(0, 15, 10))]
    Gui.Selection.clearSelection()
    for f in sides:
        Gui.Selection.addSelection(doc.Name, v.Name, f)
    p = run_cmd("SD_Draft")
    expect(p is not None and p.TITLE == "Draft", "Draft opens its panel")
    expect(len(p.faces.items) == 4, "the preselected faces are the faces to draft (%s)" % (
        p.faces.items,))
    expect(p.active_box is p.plane, "the neutral plane box waits for a pick")
    expect(not p.sec_lines.isVisible() and p.sec_plane.isVisible(),
           "Neutral Plane shows its own groups")
    pick(p, v, face_at(v, V(20, 15, 0)))
    expect(p.plane.items, "a planar face is the neutral plane")
    pick(p, v, face_at(v, V(20, 0, 10)))
    expect(len(p.faces.items) == 4 or len(p.faces.items) == 3, "faces box untouched or toggled")
    if len(p.faces.items) == 3:
        pick(p, v, face_at(v, V(20, 0, 10)))     # put it back
    p.angle.spin.setProperty("rawValue", 3.0)
    wait(900)
    expect(ok_enabled(), "draft OK: %s" % p.error.value())
    shot("panel")
    close_panel(True)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))
    v = body_views(part)[0]
    w0, w1 = _width_at(v.Shape, 0.01), _width_at(v.Shape, 19.99)
    expect(abs(w0 - 40) < 0.05 and w1 < w0 - 1.5, "it tapers upwards (%.3f to %.3f)" % (w0, w1))
    scratch = [d for n, d in App.listDocuments().items() if n.startswith("SDScratch")]
    expect(len(scratch) <= 1 and all(not d.Objects for d in scratch),
           "one scratch document at most, left empty")
    expect(App.ActiveDocument is doc, "the document stays active")
    Gui.ActiveDocument.ActiveView.viewIsometric()
    Gui.SendMsgToActiveView("ViewFit")
    wait(300)
    shot("result")


@scenario
def draft_parting_line():
    doc, part = new_doc("D2")
    sk = plate_sketch(doc, part)
    extrude_ui(doc, part, sk, 20)
    v = body_views(part)[0]
    Gui.Selection.clearSelection()
    p = run_cmd("SD_Draft")
    p.kind.setCurrentText("Parting Line")
    wait(400)
    expect(p.sec_lines.isVisible() and not p.sec_plane.isVisible(),
           "Parting Line shows the parting lines")
    expect(p.active_box is p.lines, "the parting lines box takes the picks")
    for a, b in ((V(0, 0, 20), V(40, 0, 20)), (V(40, 0, 20), V(40, 30, 20)),
                 (V(40, 30, 20), V(0, 30, 20)), (V(0, 30, 20), V(0, 0, 20))):
        pick(p, v, edge_at(v, a, b))
    expect(len(p.lines.items) == 4, "four parting lines (%d)" % len(p.lines.items))
    p.angle.spin.setProperty("rawValue", 2.0)
    wait(900)
    expect(ok_enabled(), "parting line draft OK: %s" % p.error.value())
    shot("panel")
    close_panel(True)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))
    v = body_views(part)[0]
    w0, w1 = _width_at(v.Shape, 0.01), _width_at(v.Shape, 19.99)
    expect(abs(w1 - 40) < 0.05 and w0 < w1 - 1.0,
           "it narrows away from the parting line (%.3f at the base)" % w0)


@scenario
def rib_in_a_channel():
    doc, part = new_doc("RB1")
    sk = plate_sketch(doc, part, 40, 20)
    extrude_ui(doc, part, sk, 2)
    for x0 in (0, 38):
        s = sketch(doc, plane(part, "Top Plane"))
        rect(s, x0, 0, x0 + 2, 20)
        app_part.add_to_part(part, s)
        doc.recompute()
        extrude_ui(doc, part, s, 12)
    v0 = sum(b.Shape.Volume for b in body_views(part))
    s = sketch(doc, plane(part, "Front Plane"),
               attach_offset=App.Placement(V(0, 0, -10), App.Rotation()))
    s.addGeometry(Part.LineSegment(V(10, 8, 0), V(30, 8, 0)))
    app_part.add_to_part(part, s)
    doc.recompute()
    select(doc, s)
    p = run_cmd("SD_Rib")
    expect(p is not None and p.TITLE == "Rib", "Rib opens its panel")
    expect(p.sketch_box.items, "with the selected sketch")
    p.t.spin.setProperty("rawValue", 3.0)
    wait(900)
    expect(ok_enabled(), "rib OK: %s" % p.error.value())
    shot("panel")
    close_panel(True)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))
    vs = body_views(part)
    added = sum(b.Shape.Volume for b in vs) - v0
    expect(len(vs) == 1 and abs(added - 36 * 6 * 3) < 0.5,
           "the rib fills the channel, one body (%.2f added)" % added)
    rib_obj = [o for o in doc.Objects if getattr(getattr(o, "Proxy", None), "TYPE", "") == "Rib"]
    expect(rib_obj and s in rib_obj[0].ViewObject.claimChildren(), "the sketch sits under the rib")
    Gui.ActiveDocument.ActiveView.viewIsometric()
    Gui.SendMsgToActiveView("ViewFit")
    wait(300)
    shot("result")


@scenario
def point_and_coordinate_system():
    doc, part = new_doc("PC1")
    sk = plate_sketch(doc, part, holes=[(20, 15, 5)])
    extrude_ui(doc, part, sk, 10)
    v = body_views(part)[0]
    rim = [("Edge%d" % i) for i, e in enumerate(v.Shape.Edges, 1)
           if hasattr(e.Curve, "Radius") and abs(e.BoundBox.ZMax - 10) < 1e-6][0]
    select(doc, v, rim)
    run_cmd("SD_Point")
    dlg = Gui.Control.activeDialog()
    expect(dlg, "Point opens its panel")
    pts = [o for o in doc.Objects if getattr(getattr(o, "Proxy", None), "KIND", "") == "point"]
    expect(pts and pts[0].Type == "Arc Center", "a circular edge makes an Arc Center point (%s)"
           % (pts[0].Type if pts else None))
    shot("point_panel")
    close_panel(True)
    q = pts[0].Shape.Vertexes[0].Point if pts and pts[0].Shape.Vertexes else None
    expect(q is not None and q.isEqual(V(20, 15, 10), 1e-6), "at the hole's centre (%s)" % q)
    corner = [("Vertex%d" % i) for i, x in enumerate(v.Shape.Vertexes, 1)
              if x.Point.isEqual(V(40, 30, 10), 1e-9)][0]
    select(doc, v, corner)
    run_cmd("SD_CoordinateSystem")
    css = [o for o in doc.Objects if getattr(getattr(o, "Proxy", None), "KIND", "") == "csys"]
    expect(css and Gui.Control.activeDialog(), "Coordinate System opens its panel")
    shot("csys_panel")
    close_panel(True)
    c = css[0]
    expect(not c.ErrorMessage and c.Placement.Base.isEqual(V(40, 30, 10), 1e-6),
           "its origin is the picked vertex (%s)" % c.Placement.Base)
    expect(list(c.ViewObject.LineColorArray)[:1] and len(c.ViewObject.LineColorArray) == 3,
           "X, Y and Z have their own colours")
    select(doc, c)
    Gui.runCommand("SD_Sketch")
    wait(900)
    ed = Gui.ActiveDocument.getInEdit()
    expect(ed is not None, "a sketch on the coordinate system opens")
    sk2 = ed.Object if ed is not None else None
    expect(sk2 is not None and sk2.MapMode == "ObjectXY" and
           sk2.Placement.Base.isEqual(V(40, 30, 10), 1e-6), "on its XY plane")
    Gui.ActiveDocument.resetEdit()
    wait(400)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))
    Gui.ActiveDocument.ActiveView.viewIsometric()
    Gui.SendMsgToActiveView("ViewFit")
    wait(300)
    shot("result")


@scenario
def helix_and_thread():
    doc, part = new_doc("HT1")
    sk = sketch(doc, plane(part, "Top Plane"))
    circle(sk, 0, 0, 5)
    app_part.add_to_part(part, sk)
    doc.recompute()
    extrude_ui(doc, part, sk, 20)
    v = body_views(part)[0]
    v0 = v.Shape.Volume
    top = [("Edge%d" % i) for i, e in enumerate(v.Shape.Edges, 1)
           if hasattr(e.Curve, "Radius") and abs(e.BoundBox.ZMin - 20) < 1e-6][0]
    select(doc, v, top)
    p = run_cmd("SD_Thread", 1500)
    expect(p is not None and p.TITLE == "Thread", "Thread opens its panel")
    expect(p.edge.items, "with the preselected edge")
    wait(1500)
    expect(p.size.currentText() == "M10", "the size is the nearest to the shaft (%s)" %
           p.size.currentText())
    p.length.spin.setProperty("rawValue", 12.0)
    wait(2000)
    expect(ok_enabled(), "thread OK: %s" % p.error.value())
    shot("thread_panel")
    close_panel(True)
    wait(1500)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))
    v = body_views(part)[0]
    expect(v.Shape.Volume < v0 - 50, "the groove is cut (%.1f removed)" % (v0 - v.Shape.Volume))
    # A helix round a circle sketch beside the shaft.
    s2 = sketch(doc, plane(part, "Top Plane"))
    circle(s2, 30, 0, 6)
    app_part.add_to_part(part, s2)
    doc.recompute()
    select(doc, s2)
    run_cmd("SD_Helix")
    hx = [o for o in doc.Objects if getattr(getattr(o, "Proxy", None), "KIND", "") == "helix"]
    expect(hx and Gui.Control.activeDialog(), "Helix/Spiral opens its panel")
    shot("helix_panel")
    close_panel(True)
    h = hx[0]
    expect(not h.ErrorMessage and abs(h.Shape.BoundBox.ZMax - 20) < 1e-6,
           "a 4-turn, 5 mm pitch helix, 20 high (%s)" % h.ErrorMessage)
    expect(s2 in h.ViewObject.claimChildren(), "the circle's sketch sits under the helix")
    Gui.ActiveDocument.ActiveView.viewIsometric()
    Gui.SendMsgToActiveView("ViewFit")
    wait(300)
    shot("result")


def mouse_drag(arrow, mm):
    """Press on an arrow's shaft and drag it ``mm`` along itself, with mouse events
    sent to the 3D view."""
    from PySide import QtCore as Qc, QtGui as Qg, QtWidgets as Qw
    v = Gui.ActiveDocument.ActiveView
    w = [x for x in Gui.getMainWindow().findChildren(Qw.QWidget)
         if x.metaObject().className() == "QOpenGLWidget" and x.isVisible()][-1]
    h = v.getSize()[1]
    a3 = arrow.base() + arrow.direction * (0.5 * arrow.scale)
    b3 = a3 + arrow.direction * mm

    def px(q):
        s = v.getPointOnViewport(q)
        return Qc.QPointF(s[0], h - s[1])

    def ev(t, pos, btn, btns):
        e = Qg.QMouseEvent(t, pos, w.mapToGlobal(pos), btn, btns, Qc.Qt.NoModifier)
        Qw.QApplication.sendEvent(w, e)
    a, b = px(a3), px(b3)
    ev(Qc.QEvent.MouseMove, a, Qc.Qt.NoButton, Qc.Qt.NoButton)
    ev(Qc.QEvent.MouseButtonPress, a, Qc.Qt.LeftButton, Qc.Qt.LeftButton)
    for i in range(1, 11):
        ev(Qc.QEvent.MouseMove, a + (b - a) * (i / 10.0), Qc.Qt.NoButton, Qc.Qt.LeftButton)
    ev(Qc.QEvent.MouseButtonRelease, b, Qc.Qt.LeftButton, Qc.Qt.NoButton)


def ring_drag(ring, degrees):
    """Press on a ring's knob and drag it round by ``degrees``, with mouse events."""
    from PySide import QtCore as Qc, QtGui as Qg, QtWidgets as Qw
    v = Gui.ActiveDocument.ActiveView
    w = [x for x in Gui.getMainWindow().findChildren(Qw.QWidget)
         if x.metaObject().className() == "QOpenGLWidget" and x.isVisible()][-1]
    h = v.getSize()[1]

    def px(q):
        s = v.getPointOnViewport(q)
        return Qc.QPointF(s[0], h - s[1])

    def ev(t, pos, btn, btns):
        e = Qg.QMouseEvent(t, pos, w.mapToGlobal(pos), btn, btns, Qc.Qt.NoModifier)
        Qw.QApplication.sendEvent(w, e)
    start = ring.value
    a = px(ring.at(start))
    ev(Qc.QEvent.MouseMove, a, Qc.Qt.NoButton, Qc.Qt.NoButton)
    ev(Qc.QEvent.MouseButtonPress, a, Qc.Qt.LeftButton, Qc.Qt.LeftButton)
    for i in range(1, 13):
        ev(Qc.QEvent.MouseMove, px(ring.at(start + degrees * i / 12.0)), Qc.Qt.NoButton,
           Qc.Qt.LeftButton)
    b = px(ring.at(start + degrees))
    ev(Qc.QEvent.MouseButtonRelease, b, Qc.Qt.LeftButton, Qc.Qt.NoButton)


@scenario
def instant3d_on_a_selected_feature():
    doc, part = new_doc("I3E")
    sk = plate_sketch(doc, part)
    f = extrude_ui(doc, part, sk, 10)
    Gui.ActiveDocument.ActiveView.viewIsometric()
    Gui.SendMsgToActiveView("ViewFit")
    wait(400)
    select(doc, f)
    wait(400)
    from freecad.SolidDesign.gui import instant3d
    i3 = instant3d.current()
    expect(i3.set is not None and len(i3.set.draggers()) == 1, "selecting an Extrude shows its "
           "depth arrow")
    shot("selected")
    mouse_drag(i3.set.draggers()[0], 5.0)
    wait(900)
    expect(abs(f.Depth.Value - 15.0) < 1e-6, "dragging it changes the feature (%s)" %
           f.Depth.Value)
    expect(abs(body_views(part)[0].Shape.BoundBox.ZLength - 15.0) < 1e-6,
           "and the model follows")
    expect(i3.set is not None, "the arrow stays on the feature after the drag")
    if abs(f.Depth.Value - 15.0) < 1e-6:            # don't undo the extrude itself
        doc.undo()
        doc.recompute()
        wait(400)
        expect(abs(f.Depth.Value - 10.0) < 1e-6, "one undo puts it back (%s)" %
               f.Depth.Value)
    # Typing: click the value, type, Enter.
    select(doc, f)
    wait(400)
    a = i3.set.draggers()[0]
    i3.set.set.edit_value(a)
    ed = i3.set.set.editor
    expect(ed is not None and ed.isVisible(), "clicking the value opens a box")
    ed.setText("22")
    ed.returnPressed.emit()
    wait(900)
    expect(abs(f.Depth.Value - 22.0) < 1e-6, "typing a value sets it (%s)" % f.Depth.Value)
    Gui.Selection.clearSelection()
    wait(300)
    expect(i3.set is None, "the arrow goes with the selection")
    # Opening the feature: the panel's own arrows, not two sets.
    select(doc, f)
    wait(300)
    Gui.ActiveDocument.setEdit(f.Name, 0)
    wait(900)
    expect(i3.set is None, "editing the feature hides the selection's arrows")
    close_panel(False)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def handles_on_more_features():
    """Fillet radius, Chamfer distance, Shell thickness and Hole depth arrows: in
    their panels and on a selected feature (Instant3D)."""
    doc, part = new_doc("I3M")
    sk = plate_sketch(doc, part)
    extrude_ui(doc, part, sk, 20)
    Gui.ActiveDocument.ActiveView.viewIsometric()
    Gui.SendMsgToActiveView("ViewFit")
    wait(300)
    v = body_views(part)[0]
    select(doc, v, edge_at(v, V(0, 0, 20), V(40, 0, 20)))
    p = run_cmd("SD_Fillet")
    p.radius.spin.setProperty("rawValue", 2.0)
    wait(900)
    arrows = p._drag.draggers() if p._drag else []
    expect(len(arrows) == 1 and arrows[0].prop == "Radius", "the fillet shows a radius arrow")
    if arrows:
        a = arrows[0]
        expect(abs(a.origin.z - 20) < 1e-6 and abs(a.origin.y) < 1e-6,
               "it starts on the edge (%s)" % a.origin)
        expect(a.direction.z > 0.5 and a.direction.y < -0.5, "pointing out between the faces "
               "(%s)" % a.direction)
        before = p.obj.Radius.Value
        mouse_drag(a, 1.5)
        wait(900)
        expect(p.obj.Radius.Value > before + 0.5, "dragging grows the radius (%s -> %s)"
               % (before, p.obj.Radius.Value))
        shot("fillet_arrow")
    log("  fillet:", p.obj.ErrorMessage, p.obj.Radius.Value, ok_enabled())
    close_panel(True)
    log("  after close:", Gui.Control.activeDialog(), panel())
    fil = p.obj
    select(doc, fil)
    wait(400)
    from freecad.SolidDesign.gui import instant3d
    i3 = instant3d.current()
    expect(i3.set is not None and len(i3.set.draggers()) == 1, "a selected fillet shows its arrow")
    Gui.Selection.clearSelection()
    wait(300)
    v = body_views(part)[0]
    select(doc, v, face_at(v, V(20, 15, 20)))
    p = run_cmd("SD_Shell")
    p.t.spin.setProperty("rawValue", 2.0)
    wait(900)
    arrows = p._drag.draggers() if p._drag else []
    expect(len(arrows) == 1 and arrows[0].direction.z < -0.99, "the shell's arrow goes into "
           "the wall")
    close_panel(False)
    v = body_views(part)[0]
    Gui.Selection.clearSelection()
    p = run_cmd("SD_HoleWizard")
    p.activate(p.positions)
    pick(p, v, face_at(v, V(20, 15, 20)), V(20, 15, 20))
    wait(700)
    arrows = p._drag.draggers() if p._drag else []
    expect(len(arrows) == 1 and arrows[0].prop == "Depth", "a blind hole shows its depth")
    p.end.setCurrentText("Through All")
    wait(800)
    expect(not (p._drag.draggers() if p._drag else []), "Through All has no depth arrow")
    close_panel(True)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def dropdown_tooltips_name_once():
    """The drop-down buttons' tooltips name their command once, as the others do."""
    names = ("Reference Geometry", "Patterns", "Curves", "More Surfaces", "Deform Bodies")
    seen = {}
    for tb in Gui.getMainWindow().findChildren(QtWidgets.QToolBar):
        if not tb.windowTitle().startswith("Solid Design"):
            continue
        for a in tb.actions():
            if a.text() in names:
                seen[a.text()] = a.toolTip()
    expect(sorted(seen) == sorted(names), "all five drop-downs are on the toolbars (%s)"
           % sorted(seen))
    for n, tip in sorted(seen.items()):
        expect(tip.count("<b>") == 1 and tip.count("<i>") == 1,
               "%s: one title, one command name (%s)" % (n, tip[:120]))


@scenario
def context_toolbar():
    """Clicking a face shows the tools that fit it by the pointer; Edit Feature opens
    the feature that made it; it goes when the pointer leaves or a panel opens."""
    from freecad.SolidDesign.gui import context_bar
    from PySide import QtGui as Qg
    doc, part = new_doc("CTX")
    sk = plate_sketch(doc, part, 40, 30)
    f = extrude_ui(doc, part, sk, 10)
    v = body_views(part)[0]
    obs = context_bar.current()
    expect(obs is not None, "the context toolbar is installed")
    mw = Gui.getMainWindow()
    centre = mw.mapToGlobal(mw.rect().center())
    Qg.QCursor.setPos(centre)
    select(doc, v, face_at(v, V(20, 15, 10)))
    wait(400)
    bar = obs.bar
    expect(bar is not None and bar.isVisible(), "picking a face shows the bar")
    names = [b.name for b in bar.buttons] if bar else []
    expect(names[:2] == ["edit", "SD_Sketch"] and "SD_HoleWizard" in names,
           "a flat face: Edit Feature, Sketch, Hole Wizard... (%s)" % names)
    expect(bar.feature is f, "Edit Feature is the extrude (%s)" % getattr(bar.feature, "Label",
                                                                        None))
    expect(all(b.toolTip() for b in bar.buttons), "every button says what it does")
    shot("context_face")
    if bar is not None:
        bar.grab().save(os.path.join(SHOTS, "context_bar.png"))
    select(doc, v, edge_at(v, V(0, 0, 10), V(40, 0, 10)))
    wait(400)
    names = [b.name for b in bar.buttons]
    expect("SD_Chamfer" in names and "SD_Sketch" not in names, "an edge: Fillet, Chamfer... "
           "(%s)" % names)
    Qg.QCursor.setPos(bar.frameGeometry().center() + QtCore.QPoint(400, 300))
    wait(300)
    expect(not bar.isVisible(), "it goes when the pointer moves well away")
    select(doc, v, edge_at(v, V(0, 0, 10), V(40, 0, 10)))
    wait(400)
    [b for b in bar.buttons if b.name == "SD_Fillet"][0].click()
    wait(800)
    p = panel()
    expect(p is not None and p.TITLE == "Fillet" and len(p.items.items) == 1,
           "Fillet opens with the edge")
    expect(not bar.isVisible(), "the bar goes when a tool starts")
    close_panel(False)
    select(doc, v, face_at(v, V(20, 15, 10)))
    wait(400)
    [b for b in bar.buttons if b.name == "edit"][0].click()
    wait(900)
    p = panel()
    expect(p is not None and p.obj is f, "Edit Feature opens the extrude")
    close_panel(False)
    context_bar.set_enabled(False)
    select(doc, v, face_at(v, V(20, 15, 10)))
    wait(400)
    expect(not bar.isVisible(), "turned off, it doesn't show")
    context_bar.set_enabled(True)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def whats_wrong_and_rebuild():
    """What's Wrong lists a broken feature; double-clicking it edits it; Force Rebuild
    runs every feature again."""
    from freecad.SolidDesign.gui import evaluate
    doc, part = new_doc("WW")
    f1, f2, f3 = three_features(doc, part)
    f2.Depth = 0
    doc.recompute()
    wait(300)
    Gui.runCommand("SD_WhatsWrong")
    wait(600)
    d = evaluate.LAST[0]
    expect(isinstance(d, evaluate.WhatsWrongDialog), "What's Wrong opens")
    expect(len(d.items) == 1 and d.items[0][0] is f2, "it lists the broken cut (%s)"
           % [(x.Label, k) for x, k, _t in d.items])
    shot("whats_wrong")
    d.list.itemDoubleClicked.emit(d.list.item(0))
    wait(900)
    p = panel()
    expect(p is not None and p.obj is f2, "double-clicking edits it")
    close_panel(False)
    f2.Depth = 5
    doc.recompute()
    Gui.runCommand("SD_WhatsWrong")
    wait(600)
    d = evaluate.LAST[0]
    expect(not d.items and d.list.count() == 1, "fixed: nothing is wrong")
    close_panel(False)
    vol = body_views(part)[0].Shape.Volume
    Gui.runCommand("SD_Rebuild")
    wait(600)
    expect(abs(body_views(part)[0].Shape.Volume - vol) < 1e-6, "Force Rebuild gives the same "
           "model")
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))
    _ = (f1, f3)


@scenario
def revolve_angle_ring():
    doc, part = new_doc("I3R")
    sk = sketch(doc, plane(part, "Front Plane"))
    rect(sk, 10, 0, 20, 10)
    app_part.add_to_part(part, sk)
    doc.recompute()
    select(doc, sk)
    p = run_cmd("SD_Revolve")
    pick(p, plane(part, "Top Plane"))       # nothing: keep the sketch's state
    axis = [o for o in part.Origin if app_part.clean_label(o.Label) == "Z Axis"]
    if axis:
        p.activate(p.axis_box)
        pick(p, axis[0])
    wait(900)
    expect(not p.obj.ErrorMessage, "revolve about Z: %s" % p.obj.ErrorMessage)
    p.d1.angle.spin.setProperty("rawValue", 90.0)
    wait(900)
    r1 = p.draggers().get("Angle")
    expect(r1 is not None and type(r1).__name__ == "RingDragger", "the angle is a ring")
    expect(r1.shown() and abs(r1.value - 90.0) < 1e-6, "a ring shows the angle (%s)" % r1.value)
    Gui.ActiveDocument.ActiveView.viewTop()
    Gui.SendMsgToActiveView("ViewFit")
    wait(600)
    ring_drag(r1, 45.0)
    wait(900)
    expect(abs(p.obj.Angle.Value - 135.0) < 1e-6, "dragging the knob round sets the angle "
           "(%s)" % p.obj.Angle.Value)
    shot("ring")
    close_panel(True)
    expect(not r1.shown(), "the ring goes with the panel")
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def extrude_drag_handles():
    doc, part = new_doc("I3D")
    sk = plate_sketch(doc, part)
    select(doc, sk)
    p = run_cmd("SD_Extrude")
    dr = p.draggers()
    h1 = dr.get("Depth")
    expect(h1 is not None and h1.shown() and dr.get("Depth2") is None,
           "an arrow shows for Direction 1")
    from freecad.SolidDesign.gui import handles as hm
    expect(isinstance(h1, hm.Dragger) and isinstance(h1, hm.ArrowDragger),
           "it is one of the shared draggers")
    Gui.ActiveDocument.ActiveView.viewIsometric()
    Gui.SendMsgToActiveView("ViewFit")
    wait(600)
    # Drag with the mouse: press on the arrow's shaft, move 13.5 mm along it.
    mouse_drag(h1, 13.5)
    wait(900)
    expect(abs(p.obj.Depth.Value - 23.5) < 1e-6, "dragging with the mouse sets the depth, "
           "snapped (%s)" % p.obj.Depth.Value)
    expect(abs(float(p.d1.depth.spin.property("rawValue")) - 23.5) < 1e-6,
           "and the Depth field follows")
    v = p.obj.AddSubShape
    expect(not v.isNull() and abs(v.BoundBox.ZLength - 23.5) < 1e-6,
           "and the preview (%s)" % (v.BoundBox.ZLength if not v.isNull() else None))
    p.d1.depth.spin.setProperty("rawValue", 12.0)
    wait(700)
    expect(abs(h1.value - 12.0) < 1e-6, "typing a depth moves the arrow (%s)" % h1.value)
    p.sec_d2.setChecked(True)
    wait(700)
    h2 = dr.get("Depth2")
    expect(h2 is not None and h2.shown(), "Direction 2 gets its own arrow")
    mouse_drag(h2, -1.0)
    wait(900)
    expect(abs(p.obj.Depth2.Value - 9.0) < 1e-6, "dragging it sets Depth 2 (%s)" %
           p.obj.Depth2.Value)
    shot("handles")
    p.sec_d2.setChecked(False)
    wait(400)
    p.d1.cond.setCurrentText("Through All")
    wait(700)
    expect(not h1.shown(), "no arrow without a depth (Through All)")
    p.d1.cond.setCurrentText("Mid Plane")
    wait(700)
    expect(h1.shown() and h1.factor == 2.0, "Mid Plane: the arrow is at half the depth")
    close_panel(True)
    expect(not h1.shown() and not h2.shown(), "the arrows go when the panel closes")
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def sweep_and_loft():
    doc, part = new_doc("R5")
    import Part as _P
    path = sketch(doc, plane(part, "Top Plane"))
    path.addGeometry(_P.LineSegment(V(0, 0, 0), V(40, 0, 0)))
    app_part.add_to_part(part, path)
    prof = sketch(doc, plane(part, "Right Plane"))
    circle(prof, 0, 0, 3)
    app_part.add_to_part(part, prof)
    doc.recompute()
    select(doc, prof)
    p = run_cmd("SD_Sweep")
    expect(p is not None and p.obj.Sketch is prof, "Sweep with the profile")
    expect(p.active_box is p.path, "then it waits for the path")
    pick(p, path)
    expect(p.path.items, "the path is picked")
    expect(ok_enabled(), "sweep OK: %s" % p.error.value())
    close_panel(True)
    s1 = sketch(doc, plane(part, "Top Plane"))
    rect(s1, 60, -5, 70, 5)
    s2 = sketch(doc, plane(part, "Top Plane"), attach_offset=App.Placement(
        V(0, 0, 20), App.Rotation()))
    circle(s2, 65, 0, 3)
    for o in (s1, s2):
        app_part.add_to_part(part, o)
    doc.recompute()
    Gui.Selection.clearSelection()
    p = run_cmd("SD_Loft")
    expect(p is not None, "Loft opens")
    p.activate(p.profiles)
    pick(p, s1)
    pick(p, s2)
    expect(len(p.profiles.items) == 2, "two profiles")
    expect(ok_enabled(), "loft OK: %s" % p.error.value())
    close_panel(True)
    expect(len(body_views(part)) == 2, "two bodies")
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def stage10_through_panels():
    """Fillet methods and profiles, Bounding Box, Center of Mass, Mounting Boss, Snap
    Hook, Cosmetic Thread, Vent, Variable Pattern, Lip/Groove, and the new Freeform,
    Deform and Flatten rows, through their panels."""
    import Sketcher
    doc, part = new_doc("S10")
    sk = plate_sketch(doc, part, 60, 40)
    extrude_ui(doc, part, sk, 4)
    plate = body_views(part)[0]

    # Fillet: asymmetric, conic, variable with a point.
    select(doc, plate, edge_at(plate, V(0, 0, 4), V(60, 0, 4)))
    p = run_cmd("SD_Fillet")
    expect(p is not None and p.items.items, "Fillet with the edge")
    p.radius.spin.setProperty("rawValue", 1.0)
    p.method.buttons["Asymmetric"].click()
    wait(600)
    expect(shown(p.r_dist2), "Asymmetric shows Distance 2")
    p.profile.setCurrentText("Conic Rho")
    wait(600)
    expect(shown(p.r_rho), "Conic shows Rho")
    expect(ok_enabled(), "asymmetric conic fillet OK: %s" % p.error.value())
    p.method.buttons["Symmetric"].click()
    p.ftype.setCurrentText("Variable Size")
    wait(600)
    p.points.b_add.click()
    wait(900)
    expect(len(p.obj.VariablePoints) == 1, "a variable point (%s)" % list(p.obj.VariablePoints))
    expect(ok_enabled(), "variable fillet OK: %s" % p.error.value())
    close_panel(False)

    # Bounding Box and Center of Mass.
    Gui.Selection.clearSelection()
    p = run_cmd("SD_BoundingBox", 1000)
    expect(p is not None and abs(p.obj.Length.Value - 60) < 1e-6, "a 60 long box")
    expect("60" in p.result.text(), "the size shows (%s)" % p.result.text())
    shot("bounding_box")
    close_panel(True)
    p = run_cmd("SD_CenterOfMass", 1000)
    expect(p is not None and "X 30" in p.result.text(), "the centre shows (%s)"
           % (p.result.text() if p else ""))
    close_panel(True)

    # Mounting Boss and Snap Hook: click where they go.
    plate = body_views(part)[0]
    top = face_at(plate, V(30, 20, 4))
    Gui.Selection.clearSelection()
    p = run_cmd("SD_MountingBoss")
    expect(p is not None, "Mounting Boss opens")
    p.activate(p.position)
    pick(p, plate, top, V(15, 20, 4))
    p.set_prop("Draft", 0.0)
    wait(900)
    expect(ok_enabled(), "boss OK: %s" % p.error.value())
    arrows = p._drag.draggers() if p._drag else []
    expect([a.prop for a in arrows] == ["Height"], "a height arrow (%s)"
           % [a.prop for a in arrows])
    p.set_prop("Fins", 3)
    wait(900)
    expect(ok_enabled(), "boss with fins OK: %s" % p.error.value())
    shot("mounting_boss")
    close_panel(True)
    plate = body_views(part)[0]
    expect(abs(plate.Shape.BoundBox.ZMax - 14) < 1e-6, "a 10 mm boss (%.3f)"
           % plate.Shape.BoundBox.ZMax)
    top = face_at(plate, V(45, 30, 4))
    Gui.Selection.clearSelection()
    p = run_cmd("SD_SnapHook")
    p.activate(p.position)
    pick(p, plate, top, V(45, 30, 4))
    wait(900)
    expect(ok_enabled(), "snap hook OK: %s" % p.error.value())
    close_panel(True)

    # Cosmetic Thread on the boss's top edge.
    plate = body_views(part)[0]
    rim = next(("Edge%d" % i for i, e in enumerate(plate.Shape.Edges, 1)
                if hasattr(e.Curve, "Radius") and abs(e.Curve.Radius - 4) < 1e-6 and
                abs(e.Curve.Center.z - 14) < 1e-6), None)
    expect(rim is not None, "the boss's rim")
    select(doc, plate, rim)
    p = run_cmd("SD_CosmeticThread", 1000)
    expect(p is not None and p.obj.Callout.startswith("M8"), "an M8 callout (%s)"
           % (p.obj.Callout if p else ""))
    shot("cosmetic_thread")
    close_panel(True)

    # Vent: a slot with a rib.
    vs = sketch(doc, plane(part, "Top Plane"), attach_offset=App.Placement(V(0, 0, 4),
                                                                           App.Rotation()))
    rect(vs, 22, 4, 40, 14)
    vs.addGeometry(Part.LineSegment(V(31, 4, 0), V(31, 14, 0)))
    app_part.add_to_part(part, vs)
    doc.recompute()
    select(doc, vs)
    p = run_cmd("SD_Vent", 1000)
    expect(p is not None and p.obj.Sketch is vs, "Vent with the sketch")
    expect(ok_enabled(), "vent OK: %s" % p.error.value())
    close_panel(True)
    plate = body_views(part)[0]
    expect(not plate.Shape.isInside(V(26, 9, 2), 1e-6, True) and
           plate.Shape.isInside(V(31, 9, 2), 1e-6, True), "the vent's open, its rib stays")

    # Variable Pattern: a pin, repeated with its position and depth changed.
    ps = sketch(doc, plane(part, "Top Plane"), attach_offset=App.Placement(V(0, 0, 4),
                                                                           App.Rotation()))
    ps.addGeometry(Part.Circle(V(5, 35, 0), V(0, 0, 1), 1.5))
    ps.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 0, 3, 5))
    ps.renameConstraint(0, "X")
    ps.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 0, 3, 35))
    app_part.add_to_part(part, ps)
    doc.recompute()
    pin = extrude_ui(doc, part, ps, 3)
    v0 = sum(s.Volume for s in part.Shape.Solids)
    select(doc, pin)
    p = run_cmd("SD_VariablePattern", 1000)
    expect(p is not None and p.obj.Features == [pin], "Variable Pattern with the pin")
    i = p.dim_pick.findData("Sketch:X")
    expect(i >= 0, "the sketch's X is offered")
    p.dim_pick.setCurrentIndex(i)
    p._add_dim()
    p.dim_pick.setCurrentIndex(p.dim_pick.findData("Depth"))
    p._add_dim()
    p._add_row()
    wait(300)
    p.table.item(0, 0).setText("12")
    p.table.item(0, 1).setText("6")
    wait(1200)
    expect(list(p.obj.Instances) == ["12;6"], "the row (%s)" % list(p.obj.Instances))
    expect(ok_enabled(), "variable pattern OK: %s" % p.error.value())
    shot("variable_pattern")
    close_panel(True)
    added = sum(s.Volume for s in part.Shape.Solids) - v0
    expect(abs(added - math.pi * 2.25 * 6) < 1e-3, "one more pin, 6 tall (%.4f)" % added)

    # Lip/Groove opens and asks for its bodies.
    Gui.Selection.clearSelection()
    p = run_cmd("SD_LipGroove")
    expect(p is not None and p.error.value(), "Lip/Groove asks for bodies")
    close_panel(False)
    expect(not [o for o in doc.Objects if "LipGroove" in o.Name], "cancel removes it")

    # Freeform sideways, Deform's new rows, Flatten's tear edges.
    plate = body_views(part)[0]
    top = face_at(plate, V(50, 8, 4))
    select(doc, plate, top)
    p = run_cmd("SD_Freeform")
    p.activate(p.points)
    pick(p, plate, top, V(50, 8, 4))
    p.side[0].setValue(1.0)
    wait(600)
    expect(any(str(t).endswith("|1,0,0") for t in p.obj.ControlPoints),
           "a sideways move (%s)" % list(p.obj.ControlPoints))
    close_panel(False)
    Gui.Selection.clearSelection()
    p = run_cmd("SD_Deform")
    p.kind.setCurrentText("Surface push")
    wait(300)
    expect(shown(p.r_dev), "Surface push shows Deviation")
    p.kind.setCurrentText("Curve to curve")
    wait(300)
    expect(p.fixed.isVisible(), "Curve to curve shows fixed curves")
    close_panel(False)
    select(doc, plate, top)
    p = run_cmd("SD_SurfaceFlatten")
    expect(p is not None and p.tears.isVisible(), "Flatten shows tear edges")
    close_panel(False)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def stage11_through_panels():
    """Split's face reach, DraftXpert, the new sweep, loft, dome, wrap, pattern, thicken,
    extend, ruled, radiate and legacy hole options, through their panels."""
    doc, part = new_doc("S11")
    sk = plate_sketch(doc, part, 40, 30)
    extrude_ui(doc, part, sk, 10)
    plate = body_views(part)[0]

    # Split: picking a face asks how far it should cut.
    Gui.Selection.clearSelection()
    p = run_cmd("SD_Split")
    expect(p is not None and not p.reach.isVisible(), "no question before a face is picked")
    top = face_at(plate, V(20, 15, 10))
    p.activate(p.tools)
    pick(p, plate, top, V(20, 15, 10))
    wait(500)
    expect(p.reach.isVisible() and p.reach_q.isVisible(), "the face-reach question shows")
    p.reach.buttons[p.EXTENDED].click()
    wait(600)
    expect(p.obj.ExtendFaces, "Past their edges sets Extend Faces")
    close_panel(False)

    # DraftXpert: the analysis and the button that picks the faces needing draft.
    Gui.Selection.clearSelection()
    p = run_cmd("SD_Draft")
    p.kind.setCurrentText("DraftXpert")
    wait(400)
    expect(p.sec_analysis.isVisible(), "DraftXpert shows its analysis")
    bottom = face_at(plate, V(20, 15, 0))
    p.activate(p.plane)
    pick(p, plate, bottom, V(20, 15, 0))
    wait(900)
    expect("4 need draft" in p.analysis.text(), "four walls need draft (%s)" % p.analysis.text())
    p.add_needed.click()
    wait(1200)
    expect(len(p.obj.Items[1]) == 4 if p.obj.Items else False, "the four walls picked")
    expect(ok_enabled(), "DraftXpert OK: %s" % p.error.value())
    close_panel(False)

    # Dome: the new rows.
    select(doc, plate, top)
    p = run_cmd("SD_Dome")
    expect(p is not None and shown(p.r_cont), "Continuous dome row")
    p.cont.setChecked(True)
    wait(900)
    expect(ok_enabled(), "continuous dome OK: %s" % p.error.value())
    close_panel(False)

    # Thicken scope, Extend end condition, Ruled options, Radiate propagate: rows show.
    Gui.Selection.clearSelection()
    p = run_cmd("SD_Thicken")
    p.all_b.setChecked(False)
    wait(400)
    expect(p.sec_scope_b.isVisible(), "Thicken asks for the bodies in scope")
    close_panel(False)
    p = run_cmd("SD_ExtendSurface")
    p.end.buttons["Up To Surface"].click()
    wait(400)
    expect(p.upto.row.widget.isVisible() and not shown(p.r_dist), "Up To Surface shows Up to")
    close_panel(False)
    p = run_cmd("SD_RuledSurface")
    expect(p.sec_opts.isVisible(), "Ruled shows trim and knit")
    p.kind.setCurrentText("Sweep")
    wait(400)
    expect(not p.sec_opts.isVisible() and p.vec.row.widget.isVisible(), "Sweep's rows")
    close_panel(False)
    p = run_cmd("SD_RadiateSurface")
    expect(p.prop.isVisible(), "Radiate shows propagate")
    close_panel(False)

    # Legacy hole: its own rows, the custom sizes always shown.
    select(doc, plate, top)
    p = run_cmd("SD_HoleWizard")
    p.kind.setCurrentText("Legacy")
    wait(500)
    expect(p.sec_legacy.isVisible() and not p.sec_spec.isVisible() and
           not p.sec_custom.isCheckable(), "Legacy hole rows")
    p.legacy.setCurrentText("Counterdrilled")
    wait(500)
    expect(shown(p.r_cdrill) and shown(p.r_cbd), "counterdrill rows")
    close_panel(False)

    # Curve pattern Direction 2 and click-to-skip on a linear pattern.
    hs = sketch(doc, plane(part, "Top Plane"), attach_offset=App.Placement(V(0, 0, 10),
                                                                           App.Rotation()))
    circle(hs, 5, 5, 1.5)
    app_part.add_to_part(part, hs)
    doc.recompute()
    hole = extrude_ui(doc, part, hs, 4, mode="Cut")
    select(doc, hole)
    p = run_cmd("SD_LinearPattern", 1000)
    x = [o for o in part.Origin if o.Label.startswith("X")][0]
    p.obj.Direction1Ref = (x, [])
    p.set_prop("Instances", 3)
    p.set_prop("Spacing", 10.0)
    wait(1200)
    expect(ok_enabled(), "linear pattern OK: %s" % p.error.value())
    p.skip.pick_btn.setChecked(True)
    plate = body_views(part)[0]
    pick(p, plate, face_at(plate, V(25, 5, 10)) or "", V(25, 5, 10))
    wait(1200)
    expect(list(p.obj.InstancesToSkip) == ["3,1"], "clicked the third instance off (%s)"
           % list(p.obj.InstancesToSkip))
    pick(p, plate, face_at(plate, V(25, 5, 10)) or "", V(25, 5, 10))
    wait(1200)
    expect(list(p.obj.InstancesToSkip) == [], "and back on")
    close_panel(False)
    select(doc, hole)
    p = run_cmd("SD_CurvePattern", 1000)
    expect(p is not None and hasattr(p, "sec_d2"), "Curve pattern has Direction 2")
    close_panel(False)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


def shown(row):
    """Whether a panel row is showing."""
    return row.widget.isVisible()


@scenario
def sweep_twist_guide_and_tool_body():
    """Twist and a guide curve on a sweep; a solid profile cut; a loft with a
    constraint and a guide curve, all through the panels."""
    doc, part = new_doc("R5b")
    import Part as _P
    path = sketch(doc, plane(part, "Front Plane"))
    path.addGeometry(_P.LineSegment(V(0, 0, 0), V(0, 30, 0)))
    prof = sketch(doc, plane(part, "Top Plane"))
    rect(prof, -2, -2, 2, 2)
    guide = sketch(doc, plane(part, "Front Plane"))
    guide.addGeometry(_P.LineSegment(V(2, 0, 0), V(4, 30, 0)))
    for o in (path, prof, guide):
        app_part.add_to_part(part, o)
    doc.recompute()
    select(doc, prof)
    p = run_cmd("SD_Sweep")
    pick(p, path)
    expect(not shown(p.r_twist_deg), "no twist rows until a twist is chosen")
    p.twist.setCurrentText("Specify Twist Value")
    wait(500)
    expect(shown(p.r_twist_deg) and p.sec_tan.isVisible(),
           "Specify Twist Value shows the angle and the tangency group")
    p.twist_deg.spin.setProperty("rawValue", 45.0)
    wait(700)
    expect(ok_enabled(), "twisted sweep OK: %s" % p.error.value())
    p.twist_unit.setCurrentText("Turns")
    wait(400)
    expect(shown(p.r_turns) and not shown(p.r_twist_deg), "Turns replaces the angle")
    shot("sweep_twist")
    close_panel(True)
    tops = sorted(round(abs(v.Point.x), 3) for v in body_views(part)[0].Shape.Vertexes
                  if abs(v.Point.z - 30) < 1e-6)
    expect(tops and tops[-1] < 2.01, "one full turn ends square (%s)" % tops)

    # A guide curve on a circle profile.
    prof2 = sketch(doc, plane(part, "Top Plane"))
    circle(prof2, 0, 0, 2)
    app_part.add_to_part(part, prof2)
    doc.recompute()
    select(doc, prof2)
    p = run_cmd("SD_Sweep")
    pick(p, path)
    p.activate(p.guides)
    pick(p, guide)
    expect(p.guides.items, "the guide curve is picked")
    expect(ok_enabled(), "guided sweep OK: %s" % p.error.value())
    shot("sweep_guide")
    close_panel(True)

    # A solid profile cut: a ball on a block.
    blk = sketch(doc, plane(part, "Top Plane"))
    rect(blk, 20, -10, 60, 10)
    app_part.add_to_part(part, blk)
    doc.recompute()
    extrude_ui(doc, part, blk, 10)
    rev = sketch(doc, plane(part, "Front Plane"))
    rev.addGeometry(_P.ArcOfCircle(_P.Circle(V(25, 10, 0), V(0, 0, 1), 2), -math.pi / 2, math.pi / 2))
    rev.addGeometry(_P.LineSegment(V(25, 8, 0), V(25, 12, 0)))
    app_part.add_to_part(part, rev)
    doc.recompute()
    from freecad.SolidDesign.app import revolve as app_revolve
    r = app_revolve.create(doc, part, "Add", rev)
    r.MergeResult = False
    r.Axis = (rev, ["Edge2"])
    doc.recompute()
    expect(not r.ErrorMessage, "the ball tool body revolves (%s)" % r.ErrorMessage)
    tool_id = [i for i in part.BodyIds][-1]
    track = sketch(doc, plane(part, "Top Plane"), attach_offset=App.Placement(
        V(0, 0, 10), App.Rotation()))
    track.addGeometry(_P.LineSegment(V(25, 0, 0), V(55, 0, 0)))
    app_part.add_to_part(part, track)
    doc.recompute()
    Gui.Selection.clearSelection()
    p = run_cmd("SD_Sweep")
    p.mode.buttons["Cut"].click()
    wait(300)
    p.ptype.setCurrentText("Solid Profile")
    wait(400)
    expect(shown(p.tool.row) and not shown(p.sketch_box.row),
           "Solid Profile asks for a tool body instead of a sketch")
    p.activate(p.path)
    pick(p, track)
    expect(p.path.items, "the track is picked as the path (%s)" % p.path.note.text.text())
    p.obj.ToolBody = tool_id
    p.changed()
    wait(800)
    shot("sweep_solid_profile")
    expect(ok_enabled(), "solid profile cut OK: %s" % p.error.value())
    close_panel(True)
    tool_left = [b for b in app_part.tip_bodies(part) if b.id == tool_id]
    expect(tool_left and abs(tool_left[0].shape.Volume - 4 / 3.0 * 3.14159265 * 8) < 1e-3,
           "the tool body is left whole")

    # A loft with a start constraint and a guide curve.
    l1 = sketch(doc, plane(part, "Top Plane"), attach_offset=App.Placement(
        V(0, 0, 40), App.Rotation()))
    circle(l1, 0, 0, 2)
    l2 = sketch(doc, plane(part, "Top Plane"), attach_offset=App.Placement(
        V(0, 0, 60), App.Rotation()))
    circle(l2, 0, 0, 2)
    lg = sketch(doc, plane(part, "Front Plane"))
    lg.addGeometry(_P.ArcOfCircle(V(2, 40, 0), V(5, 50, 0), V(2, 60, 0)))
    for o in (l1, l2, lg):
        app_part.add_to_part(part, o)
    doc.recompute()
    Gui.Selection.clearSelection()
    p = run_cmd("SD_Loft")
    p.activate(p.profiles)
    pick(p, l1)
    pick(p, l2)
    c, d, r_ln, r_dr = p.cons["Start"]
    expect(not shown(r_ln), "no constraint rows for None")
    c.setCurrentText("Normal To Profile")
    wait(500)
    expect(shown(r_ln) and shown(r_dr) and not shown(d.row),
           "Normal To Profile shows length and draft")
    c.setCurrentText("Direction Vector")
    wait(500)
    expect(shown(d.row) and not shown(r_dr), "Direction Vector asks for a direction")
    c.setCurrentText("None")
    wait(300)
    p.activate(p.guides)
    pick(p, lg)
    wait(600)
    expect(shown(p.r_influence), "a guide shows the influence choice")
    expect(ok_enabled(), "guided loft OK: %s" % p.error.value())
    shot("loft_guide")
    close_panel(True)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def split_and_rename():
    doc, part = new_doc("R6")
    sk = plate_sketch(doc, part)
    extrude_ui(doc, part, sk, 10)
    right = plane(part, "Right Plane")
    sk2 = sketch(doc, plane(part, "Top Plane"))
    rect(sk2, -10, -10, -5, -5)
    app_part.add_to_part(part, sk2)
    doc.recompute()
    from freecad.SolidDesign.app import refgeom as app_refgeom
    select(doc, right)
    p = run_cmd("SD_Plane")
    p.dist.spin.setProperty("rawValue", 15.0)
    wait(400)
    close_panel(True)
    pl = [o for o in part.Group if util.role(o) == "refgeom"][0]
    select(doc, pl)
    p = run_cmd("SD_Split")
    expect(p is not None and p.tools.items, "Split with the plane")
    wait(600)
    expect(p.pieces.count() == 2, "two pieces listed (%d)" % (p.pieces.count() if p else -1))
    if p.pieces.count() == 2:
        it = p.pieces.item(0)
        it.setText("Left")
        wait(400)
    close_panel(True)
    names = sorted(app_part.clean_label(v.Label) for v in body_views(part))
    expect("Left" in names, "the renamed piece keeps its name (%s)" % names)
    v = view_named(part, "Left") or body_views(part)[0]
    v.Label = "Bracket"
    doc.recompute()
    wait(300)
    names = sorted(app_part.clean_label(x.Label) for x in body_views(part))
    expect("Bracket" in names, "renaming a body in the tree sticks (%s)" % names)
    sk3 = sketch(doc, plane(part, "Top Plane"))
    rect(sk3, 1, 1, 3, 3)
    app_part.add_to_part(part, sk3)
    doc.recompute()
    extrude_ui(doc, part, sk3, 5, mode="Cut")
    names = sorted(app_part.clean_label(x.Label) for x in body_views(part))
    expect("Bracket" in names, "a later feature keeps the user's name (%s)" % names)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))
    _ = app_refgeom


@scenario
def undo_and_recompute_with_panel_open():
    doc, part = new_doc("R7")
    sk = plate_sketch(doc, part)
    f = extrude_ui(doc, part, sk, 10)
    f.ViewObject.Proxy.doubleClicked(f.ViewObject)
    wait(600)
    p = panel()
    p.d1.depth.spin.setProperty("rawValue", 20.0)
    wait(500)
    Gui.runCommand("Std_Refresh")
    wait(300)
    Gui.runCommand("Std_Undo")
    wait(500)
    expect(panel() is not None or not Gui.Control.activeDialog(), "still sane after Undo")
    close_panel(False)
    doc.recompute()
    expect(abs(f.Depth.Value - 10) < 1e-6, "Cancel after Undo leaves the depth (%s)" % f.Depth)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))
    t = [v.ViewObject.Transparency for v in body_views(part)]
    expect(all(x == 0 for x in t), "bodies are no longer ghosted (%s)" % t)


@scenario
def ghosting_restored():
    doc, part = new_doc("R8")
    sk = plate_sketch(doc, part)
    f = extrude_ui(doc, part, sk, 10)
    v = body_views(part)[0]
    v.ViewObject.Transparency = 20
    f.ViewObject.Proxy.doubleClicked(f.ViewObject)
    wait(600)
    expect(v.ViewObject.Transparency >= 55, "ghosted while editing")
    close_panel(True)
    v = body_views(part)[0]
    expect(v.ViewObject.Transparency == 20, "the user's transparency comes back (%s)" %
           v.ViewObject.Transparency)


@scenario
def delete_used_sketch():
    doc, part = new_doc("R9")
    sk = plate_sketch(doc, part)
    f = extrude_ui(doc, part, sk, 10)
    select(doc, sk)
    Gui.runCommand("Std_Delete")
    wait(800)
    doc.recompute()
    log("  dialogs:", [d for d in DIALOGS if d[0] == current[0]])
    expect([d for d in DIALOGS if d[0] == current[0]], "deleting a used sketch warns")
    expect(doc.getObject("Sketch") is None, "answering Yes deletes the sketch")
    expect(bool(f.ErrorMessage), "the feature says its sketch is gone (%r)" % f.ErrorMessage)
    log("  message:", f.ErrorMessage, "| state", f.State)
    f.ViewObject.Proxy.doubleClicked(f.ViewObject)
    wait(700)
    p = panel()
    expect(p is not None and p.active_box is p.sketch_box, "editing it asks for a sketch")
    sk2 = plate_sketch(doc, part, 20, 20)
    pick(p, sk2)
    expect(ok_enabled(), "a new sketch fixes it: %s" % (p.error.value() if p else ""))
    close_panel(True)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def circular_pattern_of_cut():
    doc, part = new_doc("R10")
    sk = sketch(doc, plane(part, "Top Plane"))
    circle(sk, 0, 0, 30)
    app_part.add_to_part(part, sk)
    doc.recompute()
    extrude_ui(doc, part, sk, 5)
    sk2 = sketch(doc, plane(part, "Top Plane"))
    circle(sk2, 20, 0, 3)
    app_part.add_to_part(part, sk2)
    doc.recompute()
    cut = extrude_ui(doc, part, sk2, 5, mode="Cut")
    select(doc, cut)
    p = run_cmd("SD_CircularPattern")
    zaxis = [o for o in part.Origin if o.TypeId == "Part::DatumLine" and o.Label.startswith("Z")]
    p.activate(p.axis)
    pick(p, zaxis[0])
    p.n.spin.setValue(6)
    wait(800)
    expect(ok_enabled(), "pattern OK: %s" % p.error.value())
    close_panel(True)
    import math
    want = math.pi * 900 * 5 - 6 * math.pi * 9 * 5
    expect(abs(body_views(part)[0].Shape.Volume - want) < 1.0, "six holes")


@scenario
def second_part():
    doc, part = new_doc("R11")
    sk = plate_sketch(doc, part)
    extrude_ui(doc, part, sk, 10)
    Gui.runCommand("SD_Part")
    wait(300)
    parts = app_part.find_parts(doc)
    expect(len(parts) == 2, "a second part")
    p2 = parts[1]
    sk2 = sketch(doc, plane(p2, "Top Plane"))
    rect(sk2, 0, 0, 5, 5)
    app_part.add_to_part(p2, sk2)
    doc.recompute()
    f = extrude_ui(doc, p2, sk2, 5)
    expect(f is not None and util.part_of(f) is p2, "the extrude goes in the second part")
    expect(len(body_views(part)) == 1 and len(body_views(p2)) == 1, "one body each")


def three_features(doc, part):
    sk = plate_sketch(doc, part)
    f1 = extrude_ui(doc, part, sk, 10)
    sk2 = sketch(doc, plane(part, "Top Plane"))
    rect(sk2, 5, 5, 15, 15)
    app_part.add_to_part(part, sk2)
    doc.recompute()
    f2 = extrude_ui(doc, part, sk2, 5, mode="Cut")
    sk3 = sketch(doc, plane(part, "Top Plane"))
    rect(sk3, 25, 5, 35, 15)
    app_part.add_to_part(part, sk3)
    doc.recompute()
    f3 = extrude_ui(doc, part, sk3, 20)
    return f1, f2, f3


@scenario
def drag_rollback_bar_and_reorder():
    doc, part = new_doc("T1")
    f1, f2, f3 = three_features(doc, part)
    bar = app_part.rollback_bar(part)
    vp = f1.ViewObject.Proxy
    expect(vp.canDropObject(bar), "the bar can be dropped on a feature")
    vp.dropObject(f1.ViewObject, bar)
    wait(400)
    expect(part.Tip is f1, "dropping the bar on Boss-Extrude1 rolls back to it")
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))
    lines = [l.strip() for l in tree_lines()]
    i_bar = lines.index("Rollback bar") if "Rollback bar" in lines else -1
    i_f1 = [i for i, l in enumerate(lines) if l == f1.Label]
    expect(i_f1 and i_bar == i_f1[0] + 1 + 1 or i_bar > i_f1[0],
           "the tree shows the bar after it (%s)" % lines[-12:])
    context_action(part, "Roll to End")
    # Reorder: drop the boss (f3) on the plate (f1): it goes before the cut.
    vp1 = f1.ViewObject.Proxy
    expect(vp1.canDropObject(f3), "a feature can be dropped on another to reorder")
    vp1.dropObject(f1.ViewObject, f3)
    wait(400)
    feats = util.features(part)
    expect(feats.index(f3) == 1 and feats.index(f2) == 2, "reordered: %s" % [
        f.Label for f in feats])
    expect(not errors_in_doc(doc), "no errors after reorder %s" % errors_in_doc(doc))
    doc.undo()
    doc.recompute()
    wait(300)
    feats = util.features(part)
    expect(feats.index(f2) == 1, "undo puts the order back: %s" % [f.Label for f in feats])


@scenario
def edit_rolled_back_feature():
    doc, part = new_doc("T2")
    f1, f2, f3 = three_features(doc, part)
    context_action(f2, "Rollback")
    expect(part.Tip is f1, "rolled back above the cut")
    f3.ViewObject.Proxy.doubleClicked(f3.ViewObject)
    wait(700)
    p = panel()
    expect(p is not None and p.obj is f3, "a rolled-back feature can be edited")
    expect(part.Tip is f3, "while editing, the bar is below it")
    close_panel(True)
    expect(part.Tip is f1, "after editing, the bar goes back")
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def undo_after_edit():
    doc, part = new_doc("T3")
    sk = plate_sketch(doc, part)
    f = extrude_ui(doc, part, sk, 10)
    f.ViewObject.Proxy.doubleClicked(f.ViewObject)
    wait(600)
    p = panel()
    p.d1.depth.spin.setProperty("rawValue", 30.0)
    wait(500)
    close_panel(True)
    expect(abs(f.Depth.Value - 30) < 1e-6, "edited to 30")
    names = doc.UndoNames
    expect(names and names[0].startswith("Edit"), "one undo step for the edit (%s)" % names[:3])
    doc.undo()
    doc.recompute()
    wait(300)
    expect(abs(f.Depth.Value - 10) < 1e-6, "undo restores the depth (%s)" % f.Depth)
    expect(abs(body_views(part)[0].Shape.Volume - 12000) < 1e-3, "and the body")


@scenario
def export_part():
    doc, part = new_doc("T4")
    sk = sketch(doc, plane(part, "Top Plane"))
    rect(sk, 0, 0, 10, 10)
    rect(sk, 20, 0, 30, 10)
    app_part.add_to_part(part, sk)
    doc.recompute()
    extrude_ui(doc, part, sk, 10)
    import Part as _P
    total = sum(v.Shape.Volume for v in body_views(part))
    expect(abs(part.Shape.Volume - total) < 1e-6 if not part.Shape.isNull() else False,
           "the Part's shape is its bodies (%.1f vs %.1f)" % (
               0 if part.Shape.isNull() else part.Shape.Volume, total))
    path = os.path.join(SHOTS, "t4.step")
    import Import
    Import.export([part], path)
    sh = _P.read(path)
    expect(len(sh.Solids) == 2 and abs(sh.Volume - total) < 1e-3,
           "STEP export of the part has both bodies (%d solids)" % len(sh.Solids))


@scenario
def delete_body_with_key():
    doc, part = new_doc("T5")
    sk = sketch(doc, plane(part, "Top Plane"))
    rect(sk, 0, 0, 10, 10)
    rect(sk, 20, 0, 30, 10)
    app_part.add_to_part(part, sk)
    doc.recompute()
    extrude_ui(doc, part, sk, 10)
    v = body_views(part)[1]
    select(doc, v)
    Gui.runCommand("Std_Delete")
    wait(900)
    p = panel()
    expect(p is not None and p.TITLE == "Delete/Keep Body" and len(p.bodies.items) == 1,
           "Delete on a body opens Delete/Keep Body with it")
    close_panel(True)
    expect(len(body_views(part)) == 1, "one body left")


@scenario
def delete_part():
    doc, part = new_doc("T6")
    sk = plate_sketch(doc, part)
    extrude_ui(doc, part, sk, 10)
    n = len(doc.Objects)
    select(doc, part)
    Gui.runCommand("Std_Delete")
    wait(900)
    left = [o.Name for o in doc.Objects]
    log("  left after deleting the part:", left)
    expect(len(left) < n, "deleting the part removes it")
    expect(not [o for o in doc.Objects if util.is_body_view(o) or util.is_feature(o)],
           "no stray bodies or features left (%s)" % left)
    doc.undo()
    doc.recompute()
    wait(500)
    parts = app_part.find_parts(doc)
    expect(len(parts) == 1 and len(body_views(parts[0])) == 1,
           "undo brings the part back with its body")
    expect(not errors_in_doc(doc), "no errors after undo %s" % errors_in_doc(doc))


@scenario
def rename_feature_renames_body():
    doc, part = new_doc("T7")
    sk = plate_sketch(doc, part)
    f = extrude_ui(doc, part, sk, 10)
    f.Label = "Plate"
    doc.recompute()
    wait(300)
    names = [app_part.clean_label(v.Label) for v in body_views(part)]
    expect(names == ["Plate"], "the body takes the feature's new name (%s)" % names)
    lines = tree_lines()
    expect(any(l.strip() == "Plate" for l in lines), "tree shows Plate")


@scenario
def many_features_speed():
    doc, part = new_doc("T8")
    sk = plate_sketch(doc, part, 200, 40)
    extrude_ui(doc, part, sk, 10)
    t0 = time.time()
    for i in range(12):
        s2 = sketch(doc, plane(part, "Top Plane"))
        circle(s2, 10 + i * 15, 20, 4)
        app_part.add_to_part(part, s2)
        doc.recompute()
        extrude_ui(doc, part, s2, 10, mode="Cut")
    t1 = time.time()
    first = util.features(part)[0]
    first.Depth = 12
    t2 = time.time()
    doc.recompute()
    t3 = time.time()
    log("  13 features made in %.1f s; full recompute %.2f s" % (t1 - t0, t3 - t2))
    expect(t3 - t2 < 5, "recompute of 13 features under 5 s (%.2f)" % (t3 - t2))
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def cancel_new_feature():
    doc, part = new_doc("T9")
    sk = plate_sketch(doc, part)
    n_objects = len(doc.Objects)
    select(doc, sk)
    p = run_cmd("SD_Extrude")
    expect(not sk.ViewObject.Visibility, "the sketch is hidden while extruding")
    close_panel(False)
    expect(len(doc.Objects) == n_objects, "Cancel leaves nothing behind (%d vs %d)" % (
        len(doc.Objects), n_objects))
    expect(sk.ViewObject.Visibility, "Cancel shows the sketch again")
    expect(not body_views(part), "no body")
    f = extrude_ui(doc, part, sk, 10)
    expect(app_part.clean_label(f.Label) == "Boss-Extrude1",
           "the next one is Boss-Extrude1 (%r)" % f.Label)
    names = [app_part.clean_label(v.Label) for v in body_views(part)]
    expect(names == ["Boss-Extrude1"], "its body is Boss-Extrude1 (%s)" % names)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))
    _ = p


@scenario
def sketch_on_face_follows_model():
    doc, part = new_doc("U1")
    sk = plate_sketch(doc, part)
    f1 = extrude_ui(doc, part, sk, 10)
    v = body_views(part)[0]
    top = face_at(v, V(20, 15, 10))
    select(doc, v, top)
    Gui.runCommand("SD_Extrude")
    wait(700)
    vp = Gui.ActiveDocument.getInEdit()
    expect(vp is not None, "a face selected + Extrude: a sketch on the face")
    if vp is None:
        return
    sk2 = vp.Object
    log("  attached to:", [(o.Label, subs) for o, subs in sk2.AttachmentSupport])
    circle(sk2, 20, 15, 5)
    sk2.recompute()
    Gui.ActiveDocument.resetEdit()
    wait(900)
    p = panel()
    expect(p is not None and p.obj.Sketch is sk2, "closing it opens Extrude")
    if p is None:
        return
    close_panel(True)
    zmax = body_views(part)[0].Shape.BoundBox.ZMax
    expect(abs(zmax - 20) < 1e-6, "the boss sits on the face (top at %.2f)" % zmax)
    f1.ViewObject.Proxy.doubleClicked(f1.ViewObject)
    wait(600)
    p = panel()
    p.d1.depth.spin.setProperty("rawValue", 15.0)
    wait(500)
    close_panel(True)
    zmax = body_views(part)[0].Shape.BoundBox.ZMax
    expect(abs(zmax - 25) < 1e-6, "the boss follows the face when the plate grows (%.2f)" % zmax)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def mirror_and_pattern_bodies():
    doc, part = new_doc("U2")
    sk = sketch(doc, plane(part, "Top Plane"))
    rect(sk, 5, 0, 15, 10)
    app_part.add_to_part(part, sk)
    doc.recompute()
    extrude_ui(doc, part, sk, 10)
    v = body_views(part)[0]
    select(doc, v)
    p = run_cmd("SD_Mirror")
    expect(p is not None and p.bodies.items, "Mirror with the body preselected")
    p.activate(p.plane)
    pick(p, plane(part, "Right Plane"))
    p.check_merge = None
    wait(500)
    expect(ok_enabled(), "mirror OK: %s" % p.error.value())
    close_panel(True)
    expect(len(body_views(part)) == 2, "two bodies after mirroring (%d)" % len(
        body_views(part)))
    select(doc, body_views(part)[0])
    p = run_cmd("SD_LinearPattern")
    expect(p is not None and p.bodies.items, "Linear Pattern with a body preselected")
    yaxis = [o for o in part.Origin if o.TypeId == "Part::DatumLine" and o.Label.startswith("Y")]
    p.activate(p.dir1)
    pick(p, yaxis[0])
    p.n1.spin.setValue(3)
    p.sp1.spin.setProperty("rawValue", 20.0)
    wait(700)
    expect(ok_enabled(), "pattern OK: %s" % p.error.value())
    close_panel(True)
    expect(len(body_views(part)) == 4, "four bodies (%d)" % len(body_views(part)))
    names = sorted(app_part.clean_label(x.Label) for x in body_views(part))
    log("  bodies:", names)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


def two_bodies(doc, part, name="Two"):
    sk = sketch(doc, plane(part, "Top Plane"))
    rect(sk, 0, 0, 10, 10)
    rect(sk, 20, 0, 30, 10)
    app_part.add_to_part(part, sk)
    doc.recompute()
    return extrude_ui(doc, part, sk, 10)


@scenario
def hide_part_and_folder():
    doc, part = new_doc("V1")
    two_bodies(doc, part)
    f = app_part.folder(part, "solid")
    f.ViewObject.Visibility = False
    wait(300)
    vis = [v.ViewObject.Visibility for v in body_views(part)]
    expect(not any(vis), "hiding Solid Bodies hides the bodies (%s)" % vis)
    f.ViewObject.Visibility = True
    wait(300)
    vis = [v.ViewObject.Visibility for v in body_views(part)]
    expect(all(vis), "showing it shows them (%s)" % vis)
    select(doc, part)
    Gui.runCommand("Std_ToggleVisibility")
    wait(300)
    vis = [v.ViewObject.Visibility for v in body_views(part)]
    expect(not any(vis), "hiding the part hides its bodies (%s)" % vis)
    Gui.runCommand("Std_ToggleVisibility")
    wait(300)
    vis = [v.ViewObject.Visibility for v in body_views(part)]
    expect(all(vis), "showing the part shows them (%s)" % vis)


@scenario
def escape_cancels():
    doc, part = new_doc("V2")
    sk = plate_sketch(doc, part)
    select(doc, sk)
    p = run_cmd("SD_Extrude")
    QtTest = __import__("PySide6.QtTest", fromlist=["QtTest"])
    QtTest.QTest.keyClick(p.d1.depth.spin, QtCore.Qt.Key_Escape)
    wait(800)
    expect(not Gui.Control.activeDialog(), "Escape closes the panel")
    expect(not [o for o in doc.Objects if util.is_feature(o)], "and cancels the feature")


@scenario
def pick_bodies_in_fields():
    doc, part = new_doc("V3")
    two_bodies(doc, part)
    sk = sketch(doc, plane(part, "Front Plane"))
    rect(sk, 0, -20, 30, -12)
    app_part.add_to_part(part, sk)
    doc.recompute()
    select(doc, sk)
    p = run_cmd("SD_Extrude")
    p.d1.cond.setCurrentIndex(p.d1.cond.findText("Up To Body"))
    wait(400)
    expect(p.active_box is p.d1.body, "Up To Body makes the body box active")
    pick(p, body_views(part)[0])
    expect(p.d1.body.items, "picking a body fills Up To Body")
    log("  up to body:", p.obj.UpToBody, p.error.value())
    close_panel(False)
    Gui.Selection.clearSelection()
    p = run_cmd("SD_Combine")
    p.op.setCurrentIndex(p.op.findText("Subtract"))
    wait(400)
    expect(p.sec_main.isVisible(), "Subtract shows Main Body")
    p.activate(p.main)
    pick(p, body_views(part)[0])
    expect(p.main.items, "picking the main body fills its field")
    p.activate(p.bodies)
    pick(p, body_views(part)[1])
    expect(p.bodies.items, "picking a body to combine")
    log("  combine:", p.obj.MainBody, list(p.obj.Bodies), p.error.value())
    close_panel(False)


@scenario
def hole_relabels_with_size():
    doc, part = new_doc("V4")
    sk = plate_sketch(doc, part)
    extrude_ui(doc, part, sk, 10)
    v = body_views(part)[0]
    top = face_at(v, V(20, 15, 10))
    Gui.Selection.clearSelection()
    p = run_cmd("SD_HoleWizard")
    p.activate(p.positions)
    pick(p, v, top, V(10, 10, 10))
    p.size.setCurrentIndex(p.size.findText("M8"))
    wait(600)
    log("  hole label:", p.obj.Label)
    expect("M8" in p.obj.Label, "the label follows the size (%s)" % p.obj.Label)
    close_panel(True)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def broken_then_fixed():
    doc, part = new_doc("V5")
    f1, f2, f3 = three_features(doc, part)
    f2.Depth = 0
    doc.recompute()
    wait(300)
    expect(bool(f2.ErrorMessage), "the cut is broken")
    expect(not f3.ErrorMessage, "the next feature carries on (%r)" % f3.ErrorMessage)
    icon = f2.ViewObject.Proxy.getIcon()
    expect(icon.endswith("_error.svg"), "the broken feature shows the error icon (%s)" % icon)
    picon = part.ViewObject.Proxy.getIcon()
    expect(picon.endswith("_error.svg"), "the part shows it too (%s)" % picon)
    f2.ViewObject.Proxy.doubleClicked(f2.ViewObject)
    wait(700)
    p = panel()
    expect(p is not None and p.error.value(), "editing shows the error")
    expect(not ok_enabled(), "OK disabled while broken")
    p.d1.depth.spin.setProperty("rawValue", 5.0)
    wait(700)
    expect(ok_enabled(), "fixing it enables OK")
    close_panel(True)
    expect(not errors_in_doc(doc), "all fine again %s" % errors_in_doc(doc))
    icon = f2.ViewObject.Proxy.getIcon()
    expect(not icon.endswith("_error.svg"), "the error icon goes (%s)" % icon)
    _ = f1


@scenario
def undo_redo_many():
    doc, part = new_doc("V6")
    f1, f2, f3 = three_features(doc, part)
    vol = body_views(part)[0].Shape.Volume
    for _ in range(6):
        doc.undo()
    doc.recompute()
    wait(300)
    left = [o.Label for o in doc.Objects if util.is_feature(o)]
    log("  after 6 undos:", left, len(body_views(part)))
    for _ in range(6):
        doc.redo()
    doc.recompute()
    wait(400)
    expect(len(util.features(part)) == 3, "redo brings all three back")
    vols = [round(v.Shape.Volume, 3) for v in body_views(part)]
    expect(len(vols) == 2 and abs(sum(vols) - (12000 - 500 + 2000)) < 1e-3 or
           abs(vols[0] - vol) < 1e-3, "the same bodies again (%s vs %.1f)" % (vols, vol))
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))
    lines = tree_lines()
    expect(not any("Solid Bodies (0)" in l for l in lines), "the folder count is right")


@scenario
def reopen_rolled_back():
    doc, part = new_doc("V7")
    f1, f2, f3 = three_features(doc, part)
    context_action(f2, "Rollback")
    path = os.path.join(SHOTS, "v7.FCStd")
    doc.saveAs(path)
    App.closeDocument(doc.Name)
    wait(300)
    doc = App.openDocument(path)
    wait(1200)
    part = app_part.find_parts(doc)[0]
    feats = util.features(part)
    expect(part.Tip is feats[0], "the bar is where it was saved")
    expect(feats[1].RolledBack and feats[2].RolledBack, "the features below are rolled back")
    expect(abs(body_views(part)[0].Shape.Volume - 12000) < 1e-3, "the body is the plate")
    context_action(part, "Roll to End")
    expect(len(body_views(part)) == 1 and body_views(part)[0].Shape.Volume > 12000,
           "rolled to the end: the boss is back")
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def draft_arrow_clicks():
    """Clicking the draft angle's up arrow quickly, many times."""
    doc, part = new_doc("W1")
    sk = plate_sketch(doc, part, holes=[(20, 15, 4)])
    select(doc, sk)
    p = run_cmd("SD_Extrude")
    p.d1.draft_on.setChecked(True)
    wait(500)
    spin = p.d1.draft_angle.spin
    QtTest = __import__("PySide6.QtTest", fromlist=["QtTest"]).QTest
    opt = QtWidgets.QStyleOptionSpinBox()
    spin.initStyleOption(opt) if hasattr(spin, "initStyleOption") else None
    up = spin.style().subControlRect(QtWidgets.QStyle.CC_SpinBox, opt,
                                     QtWidgets.QStyle.SC_SpinBoxUp, spin)
    pos = up.center() if up.isValid() and not up.isEmpty() else QtCore.QPoint(
        spin.width() - 6, 4)
    t0 = time.time()
    for _ in range(12):
        QtTest.mouseClick(spin, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, pos, 20)
        QtWidgets.QApplication.processEvents()
    t1 = time.time()
    wait(1500)
    t2 = time.time()
    log("  12 clicks took %.2f s; settled in %.2f s; angle %s; error %r" % (
        t1 - t0, t2 - t1, p.obj.DraftAngle, p.error.value()))
    expect(t1 - t0 < 5, "clicking stays responsive (%.2f s)" % (t1 - t0))
    expect(p.obj.DraftAngle.Value > 1.5, "the angle went up (%s)" % p.obj.DraftAngle)
    close_panel(True)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def sketch_on_face_keeps_body_visible():
    doc, part = new_doc("W2")
    sk = plate_sketch(doc, part)
    extrude_ui(doc, part, sk, 10)
    v = body_views(part)[0]
    select(doc, v, face_at(v, V(20, 15, 10)))
    Gui.runCommand("SD_Sketch")
    wait(900)
    expect(Gui.ActiveDocument.getInEdit() is not None, "sketching on the face")
    expect(v.ViewObject.Visibility, "the body stays visible while sketching")
    expect(not any(o.ViewObject.Visibility for o in part.Origin),
           "a face was picked: the planes aren't shown")
    shot("sketching")
    Gui.ActiveDocument.resetEdit()
    wait(500)
    expect(v.ViewObject.Visibility, "and after")


@scenario
def planes_the_user_shows_stay_shown():
    """Planes the user shows stay shown after the plane prompt."""
    doc, part = new_doc("S2c")
    top = plane(part, "Top Plane")
    top.ViewObject.Visibility = True
    Gui.Selection.clearSelection()
    Gui.runCommand("SD_Sketch")
    wait(500)
    expect(Gui.Control.activeDialog(), "the plane prompt is open")
    close_panel(False)
    wait(300)
    expect(top.ViewObject.Visibility, "the plane the user showed stays shown")
    expect(not plane(part, "Front Plane").ViewObject.Visibility, "the others hide again")


@scenario
def edit_used_sketch_rolls_back():
    doc, part = new_doc("W4")
    f1, f2, f3 = three_features(doc, part)
    sk2 = f2.Sketch
    Gui.ActiveDocument.setEdit(sk2.Name)
    wait(900)
    expect(part.Tip is f1, "editing the cut's sketch rolls back above the cut (%s)" % (
        part.Tip.Label if part.Tip else None))
    vis = [v.ViewObject.Visibility for v in body_views(part)]
    expect(vis and all(vis), "the model stays visible (%s)" % vis)
    shot("editing")
    import Part as _P
    sk2.addGeometry(_P.Circle(V(30, 25, 0), V(0, 0, 1), 2))
    Gui.ActiveDocument.resetEdit()
    wait(900)
    expect(part.Tip is f3, "closing it rolls forward (%s)" % (part.Tip.Label if part.Tip else None))
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))
    vol = sum(v.Shape.Volume for v in body_views(part))
    expect(vol < 12000 - 500 + 2000 - 50, "the new circle cuts too (%.1f)" % vol)


@scenario
def axis_dashed_on_top():
    doc, part = new_doc("W5")
    sk = sketch(doc, plane(part, "Top Plane"))
    circle(sk, 0, 0, 10)
    app_part.add_to_part(part, sk)
    doc.recompute()
    extrude_ui(doc, part, sk, 20)
    v = body_views(part)[0]
    side = [("Face%d" % i) for i, f in enumerate(v.Shape.Faces, 1)
            if f.Surface.TypeId == "Part::GeomCylinder"][0]
    select(doc, v, side)
    p = run_cmd("SD_Axis")
    expect(p is not None and p.obj.Type.startswith("Cylindrical"), "Axis from a round face (%s)" % (
        p.obj.Type if p else None))
    close_panel(True)
    ax = [o for o in part.Group if util.role(o) == "refgeom"][0]
    expect(ax.ViewObject.DrawStyle == "Dashed", "the axis is dashed")
    ov = getattr(ax.ViewObject.Proxy, "_overlay", None)
    expect(ov is not None and str(ov.getTypeId().getName()) == "Annotation",
           "drawn on top of the bodies")
    Gui.ActiveDocument.ActiveView.viewIsometric()
    Gui.SendMsgToActiveView("ViewFit")
    wait(400)
    shot("axis")
    ax.ViewObject.Visibility = False
    wait(200)
    expect(not ax.ViewObject.Visibility, "the axis can be hidden")


@scenario
def temporary_axis_on_hover():
    doc, part = new_doc("W6")
    sk = sketch(doc, plane(part, "Top Plane"))
    circle(sk, 0, 0, 10)
    app_part.add_to_part(part, sk)
    doc.recompute()
    extrude_ui(doc, part, sk, 20)
    v = body_views(part)[0]
    side = [("Face%d" % i) for i, f in enumerate(v.Shape.Faces, 1)
            if f.Surface.TypeId == "Part::GeomCylinder"][0]
    from freecad.SolidDesign.gui import temp_axis
    t = temp_axis.current()
    Gui.ActiveDocument.ActiveView.viewIsometric()
    Gui.SendMsgToActiveView("ViewFit")
    wait(300)
    flat = [("Face%d" % i) for i, f in enumerate(v.Shape.Faces, 1)
            if f.Surface.TypeId == "Part::GeomPlane"][0]

    def leave():
        if hasattr(Gui.Selection, "clearPreselection"):
            Gui.Selection.clearPreselection()
        else:
            t.removePreselection(doc.Name, v.Name, side)

    rim = [("Edge%d" % i) for i, e in enumerate(v.Shape.Edges, 1)
           if e.Curve.TypeId == "Part::GeomCircle"][0]
    # Passing over the cylinder doesn't show its axis.
    Gui.Selection.setPreselection(v, side)
    wait(1500)
    expect(t.node is None, "passing over a cylinder shows nothing yet")
    Gui.Selection.setPreselection(v, flat)
    wait(1200)
    Gui.Selection.setPreselection(v, side)
    wait(2000)
    expect(t.node is None, "moving off it and back starts the wait again")
    wait(1300)
    expect(t.node is not None, "resting on it for 3 seconds shows its axis")
    t.clear()
    # A shaky hand: the pointer slips onto the rim, the top face and back.
    Gui.Selection.setPreselection(v, side)
    for _ in range(6):
        wait(250)
        Gui.Selection.setPreselection(v, rim)
        wait(150)
        Gui.Selection.setPreselection(v, flat)
        wait(100)
        Gui.Selection.setPreselection(v, side)
    wait(400)
    expect(t.node is not None, "slips onto the rim and top don't restart the wait")
    shot("hover")
    leave()
    wait(1500)
    expect(t.node is not None, "it stays a moment after the pointer leaves")
    Gui.Selection.setPreselection(v, side)
    wait(2500)
    expect(t.node is not None, "coming back to it keeps it")
    leave()
    wait(3150)
    expect(t.node is not None and t.material.transparency[0] > 0.0,
           "3 seconds after leaving it fades (%s)" % (
               t.material.transparency[0] if t.material else None))
    shot("fading")
    wait(600)
    expect(t.node is None, "and is gone")
    # Revolve about it: a profile beside the cylinder, the round face as the axis.
    sk2 = sketch(doc, plane(part, "Front Plane"))
    rect(sk2, 15, 0, 20, 5)
    app_part.add_to_part(part, sk2)
    doc.recompute()
    select(doc, sk2)
    p = run_cmd("SD_Revolve")
    p.activate(p.axis_box)
    pick(p, body_views(part)[0], side)
    expect(p.axis_box.items, "a round face is taken as the axis")
    expect(ok_enabled(), "revolve about the face's axis: %s" % p.error.value())
    close_panel(True)
    expect(not errors_in_doc(doc), "no errors %s" % errors_in_doc(doc))


@scenario
def origin_folder():
    doc, part = new_doc("W7")
    sk = plate_sketch(doc, part)
    extrude_ui(doc, part, sk, 10)
    t = tree_widget()
    part_item = None
    for i in range(t.topLevelItemCount()):
        top = t.topLevelItem(i)
        for j in range(top.childCount()):
            if top.child(j).text(0) == "Part1":
                part_item = top.child(j)
    part_item.setExpanded(True)
    wait(300)
    kids = [app_part.clean_label(part_item.child(i).text(0)) for i in range(
        part_item.childCount()) if not part_item.child(i).isHidden()]
    log("  part children:", kids)
    expect(kids[:2] == ["Solid Bodies (1)", "Origin"], "folders first, then Origin (%s)" % kids)
    expect(not any(k in kids for k in ("Front Plane", "Top Plane", "Right Plane")),
           "the planes aren't loose under the part")
    of = [part_item.child(i) for i in range(part_item.childCount())
          if app_part.clean_label(part_item.child(i).text(0)) == "Origin"][0]
    of.setExpanded(True)
    wait(300)
    inner = [app_part.clean_label(of.child(i).text(0)) for i in range(of.childCount())
             if not of.child(i).isHidden()]
    expect(inner == ["Front Plane", "Top Plane", "Right Plane", "Origin"],
           "the folder holds the planes and the origin (%s)" % inner)
    folder = app_part.folder(part, app_part.ORIGIN_FOLDER)
    folder.ViewObject.Visibility = True
    folder.ViewObject.Visibility = False
    folder.ViewObject.Visibility = True
    wait(200)
    planes = [o for o in part.Origin if o.TypeId == "Part::DatumPlane"]
    expect(all(o.ViewObject.Visibility for o in planes), "showing the folder shows the planes")
    axes = [o for o in part.Origin if o.TypeId == "Part::DatumLine"]
    expect(not any(o.ViewObject.Visibility for o in axes), "the axes stay hidden")
    shot("tree")
    # An older file, made before the folder: it gets one when opened.
    doc.removeObject(folder.Name)
    path = os.path.join(SHOTS, "w7.FCStd")
    doc.saveAs(path)
    App.closeDocument(doc.Name)
    wait(300)
    doc = App.openDocument(path)
    wait(1500)
    part = app_part.find_parts(doc)[0]
    expect(app_part.folder(part, app_part.ORIGIN_FOLDER) is not None,
           "an older file gets the Origin folder")


def sketch_on_face(doc, part, body, point, draw):
    """Pick a face, press Extrude: sketch on it, close it, OK the extrude."""
    select(doc, body, face_at(body, point))
    Gui.runCommand("SD_Extrude")
    wait(700)
    vp = Gui.ActiveDocument.getInEdit()
    if vp is None:
        return None
    draw(vp.Object)
    vp.Object.recompute()
    Gui.ActiveDocument.resetEdit()
    wait(900)
    return panel()


@scenario
def rollback_on_a_real_model():
    """The owner's report: rolling back broke the model (sketch on a face lost)."""
    doc, part = new_doc("X1")
    sk = plate_sketch(doc, part)
    extrude_ui(doc, part, sk, 10)
    p = sketch_on_face(doc, part, body_views(part)[0], V(20, 15, 10),
                       lambda s: circle(s, 20, 15, 6))
    p.d1.depth.spin.setProperty("rawValue", 15.0)
    wait(500)
    close_panel(True)
    p = sketch_on_face(doc, part, body_views(part)[0], V(20, 15, 25),
                       lambda s: circle(s, 20, 15, 2))
    p.mode.buttons["Cut"].click()
    wait(300)
    p.d1.cond.setCurrentIndex(p.d1.cond.findText("Through All"))
    wait(600)
    close_panel(True)
    feats = util.features(part)
    expect(len(feats) == 3 and not errors_in_doc(doc), "the model is built %s" % errors_in_doc(doc))
    final = round(sum(v.Shape.Volume for v in body_views(part)), 3)
    before = len(report_text())
    stages = []
    for f in reversed(feats):
        expect(context_action(f, "Rollback"), "Rollback on %s" % f.Label)
        stages.append(round(sum(v.Shape.Volume for v in body_views(part)), 3))
        expect(not errors_in_doc(doc), "rolled above %s: no errors %s" % (f.Label, errors_in_doc(doc)))
    expect(stages[-1] == 0 and not body_views(part), "at the top: no bodies (%s)" % stages)
    bar = app_part.rollback_bar(part)
    for _ in range(3):
        expect(context_action(bar, "Roll Forward"), "Roll Forward on the bar")
        expect(not errors_in_doc(doc), "rolling forward: no errors %s" % errors_in_doc(doc))
    expect(round(sum(v.Shape.Volume for v in body_views(part)), 3) == final,
           "rolled forward step by step: the same model")
    expect(context_action(bar, "Roll to Previous"), "Roll to Previous on the bar")
    expect(part.Tip is feats[1], "one back")
    expect(context_action(part, "Roll to Start"), "Roll to Start")
    expect(context_action(part, "Roll to End"), "Roll to End")
    expect(round(sum(v.Shape.Volume for v in body_views(part)), 3) == final,
           "rolled to the end: the same model")
    for s in [o for o in doc.Objects if o.TypeId.startswith("Sketcher")]:
        expect("Invalid" not in s.State, "%s is fine" % s.Label)
    new = report_text()[before:]
    expect("subshape not found" not in new, "no attachment errors in the Report view")
    feats[0].ViewObject.Proxy.doubleClicked(feats[0].ViewObject)
    wait(700)
    p = panel()
    p.d1.depth.spin.setProperty("rawValue", 20.0)
    wait(600)
    close_panel(True)
    expect(not errors_in_doc(doc), "editing the first feature: no errors %s" % errors_in_doc(doc))
    zmax = max(v.Shape.BoundBox.ZMax for v in body_views(part))
    expect(abs(zmax - 35) < 1e-6, "the boss and hole follow the thicker plate (%.2f)" % zmax)


@scenario
def move_translate_ok():
    doc, part = new_doc("W3")
    sk = plate_sketch(doc, part, 10, 10)
    extrude_ui(doc, part, sk, 10)
    v = body_views(part)[0]
    select(doc, v)
    p = run_cmd("SD_MoveCopy")
    p.dx.spin.setProperty("rawValue", 25.0)
    wait(600)
    log("  preview bb:", p.obj.AddSubShape.BoundBox if not p.obj.AddSubShape.isNull() else None)
    close_panel(True)
    bb = body_views(part)[0].Shape.BoundBox
    log("  after OK:", bb, "DeltaX", p.obj.DeltaX, "tip", part.Tip.Label,
        "feature shape", p.obj.Shape.BoundBox, "Bodies", list(p.obj.Bodies),
        "base ids", list(p.obj.BaseFeature.BodyIds), "ids", list(p.obj.BodyIds))
    expect(abs(bb.XMin - 25) < 1e-6, "OK moves the body (XMin %.2f)" % bb.XMin)


# ----------------------------------------------------------------- runner

DIALOGS = []


def answer_dialogs():
    """Modal message boxes a user would see: log them and press the default
    (or Yes/OK) button, so the session goes on."""
    w = QtWidgets.QApplication.activeModalWidget()
    if isinstance(w, QtWidgets.QMessageBox):
        text = w.text().replace("\n", " ")[:200]
        log("  DIALOG:", w.windowTitle(), "|", text)
        DIALOGS.append((current[0], w.windowTitle(), text))
        b = w.button(QtWidgets.QMessageBox.Yes) or w.button(QtWidgets.QMessageBox.Ok) or \
            w.defaultButton()
        if b is not None:
            b.click()
        else:
            w.reject()


def main():
    timer = QtCore.QTimer()
    timer.timeout.connect(answer_dialogs)
    timer.start(150)
    main.timer = timer
    mw = Gui.getMainWindow()
    mw.resize(1500, 950)
    Gui.activateWorkbench("SolidDesignWorkbench")
    wait(500)
    for fn in SCENARIOS:
        if ONLY and fn.__name__ not in ONLY:
            continue
        current[0] = fn.__name__
        log("==", fn.__name__)
        before = len(report_text())
        try:
            fn()
        except Exception:
            tb = traceback.format_exc()
            log(tb)
            problems.append("%s: exception %s" % (fn.__name__, tb.strip().splitlines()[-1]))
        wait(300)
        try:
            if Gui.Control.activeDialog():
                close_panel(False)
        except Exception:
            pass
        new = report_text()[before:]
        bad = [l for l in new.splitlines() if any(k in l for k in (
            "Traceback", "Error", "error", "Exception", "exception"))]
        if bad:
            log("  REPORT:\n    " + "\n    ".join(new.splitlines()[-40:]))
            problems.append("%s: report view: %s" % (fn.__name__, bad[0][:160]))
        for d in list(App.listDocuments().values()):
            try:
                App.closeDocument(d.Name)
            except Exception:
                pass
        wait(200)
    log("DIALOGS", DIALOGS)
    log("PROBLEMS", len(problems))
    for p in problems:
        log("  -", p)
    LOG.close()
    os._exit(1 if problems else 0)


QtCore.QTimer.singleShot(500, main)
