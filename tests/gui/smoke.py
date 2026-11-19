# SPDX-License-Identifier: LGPL-2.1-or-later
"""GUI smoke test (spec 9.2). Run in a real FreeCAD on a virtual display:

    xvfb-run -a -s "-screen 0 1600x1000x24" freecad tests/gui/smoke.py

For each tool: open its panel and fill it the way a user does (calling what its
buttons call), check that the preview appears and OK makes the feature, check
the tree folders and their counts. Screenshots of each panel go to
$SD_SHOTS (default /tmp/sd_shots): look at them.
"""

import os
import sys
import time
import traceback

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
SHOTS = os.environ.get("SD_SHOTS", "/tmp/sd_shots")
os.makedirs(SHOTS, exist_ok=True)
LOG = open(os.path.join(SHOTS, "smoke.log"), "w")
failures = []


def log(*a):
    LOG.write(" ".join(str(x) for x in a) + "\n")
    LOG.flush()


def wait(ms=400):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.01)


def check(cond, what):
    log(("PASS " if cond else "FAIL ") + what)
    if not cond:
        failures.append(what)


def shot(widget, name):
    if name.endswith("_panel"):
        from freecad.SolidDesign.gui import extrude_panel
        from freecad.SolidDesign.gui.panel.parts import untipped
        p = extrude_panel.LAST[0]
        if p is not None and not p._closing:
            p.widget.grab().save(os.path.join(SHOTS, name + "_form.png"))   # the whole panel
            gaps = untipped(p.widget)
            check(not gaps, "%s: every control has a tooltip %s" % (
                name, [g.metaObject().className() + ":" + (getattr(g, "text", lambda: "")() or "")
                       for g in gaps]))
    path = os.path.join(SHOTS, name + ".png")
    widget.grab().save(path)
    log("shot", path)


def task_panel_widget():
    mw = Gui.getMainWindow()
    for w in mw.findChildren(QtWidgets.QWidget):
        if w.metaObject().className() == "Gui::TaskView::TaskView" and w.isVisible():
            return w
    return None


def tree_widget():
    mw = Gui.getMainWindow()
    for w in mw.findChildren(QtWidgets.QTreeWidget):
        if w.metaObject().className() == "Gui::TreeWidget" and w.isVisible():
            return w
    return None


def preview_look(node):
    """(face colour, face transparency, dashed edges) of a preview layer."""
    from pivy import coin
    mat = style = None
    for i in range(node.getNumChildren()):
        ch = node.getChild(i)
        if mat is None and ch.isOfType(coin.SoMaterial.getClassTypeId()):
            mat = ch
        if ch.isOfType(coin.SoSeparator.getClassTypeId()):
            for j in range(ch.getNumChildren()):
                if ch.getChild(j).isOfType(coin.SoDrawStyle.getClassTypeId()):
                    style = ch.getChild(j)
    col = tuple(round(c, 2) for c in mat.diffuseColor[0].getValue())
    return col, round(mat.transparency[0], 2), style is not None and \
        style.linePattern.getValue() == 0xF0F0


def tree_lines(tree):
    out = []

    def walk(item, depth):
        if item.isHidden():
            return
        out.append("  " * depth + item.text(0))
        for i in range(item.childCount()):
            walk(item.child(i), depth + 1)
    for i in range(tree.topLevelItemCount()):
        walk(tree.topLevelItem(i), 0)
    return out


def expand_all(tree):
    tree.expandAll()
    wait(200)


def run():
    from freecad.SolidDesign.gui import extrude_panel
    from freecad.SolidDesign.app import part as app_part
    from helpers import circle, plane, rect, sketch

    mw = Gui.getMainWindow()
    mw.resize(1500, 950)
    Gui.activateWorkbench("SolidDesignWorkbench")
    wait()
    doc = App.newDocument("Smoke")
    Gui.runCommand("SD_Part")
    wait()
    part = app_part.find_parts(doc)[0]
    check(part.Label == "Part1", "SD_Part makes Part1")

    # ---- 1. Extruded Boss/Base with a preselected sketch
    sk = sketch(doc, plane(part, "Top Plane"))
    rect(sk, 0, 0, 40, 20)
    app_part.add_to_part(part, sk)
    doc.recompute()
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, sk.Name)
    Gui.runCommand("SD_Extrude")
    wait(800)
    p = extrude_panel.LAST[0]
    check(p is not None and Gui.Control.activeDialog(), "Extruded Boss/Base opens its panel")
    check(p.sketch_box.items and p.sketch_box.items[0][0] == sk.Name,
          "the preselected sketch fills the Sketch box")
    p.d1.depth.spin.setProperty("rawValue", 12.0)
    wait(600)
    check(abs(p.obj.Depth.Value - 12.0) < 1e-9, "typing a depth sets the property")
    check("result" in p.preview.layers, "the preview appears")
    from freecad.SolidDesign.gui import preview as pv
    look = preview_look(p.preview.layers["result"])
    check(look == (tuple(round(c, 2) for c in pv.ADD_COLOR), pv.RESULT_TRANSPARENCY, True),
          "Add preview: transparent green, dashed edges %s" % (look,))
    check(not p.error.isVisible(), "no error shown")
    Gui.ActiveDocument.ActiveView.viewIsometric()
    Gui.SendMsgToActiveView("ViewFit")
    wait(300)
    shot(task_panel_widget() or p.widget, "01_boss_panel")
    shot(mw, "01_boss_window")
    p._click_ok()
    wait(600)
    check(not Gui.Control.activeDialog(), "OK closes the panel")
    boss = [o for o in doc.Objects if o.Label == "Boss-Extrude1"]
    check(len(boss) == 1 and abs(boss[0].Shape.Volume - 40 * 20 * 12) < 1e-6,
          "OK makes Boss-Extrude1 with the right volume")
    check(app_part.folder(part, "solid").Label == "Solid Bodies (1)", "folder shows 1 solid body")

    # ---- 2. Extruded Cut that splits the body: Bodies to Keep in the panel
    sk2 = sketch(doc, plane(part, "Top Plane"))
    rect(sk2, 18, -5, 22, 25)
    app_part.add_to_part(part, sk2)
    doc.recompute()
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, sk2.Name)
    Gui.runCommand("SD_Extrude")
    wait(800)
    p = extrude_panel.LAST[0]
    check(p.obj.Mode == "Add" and p.mode.mode() == "Add", "Extrude opens in Add mode")
    # The only stylesheets: the icon buttons' padding and the active selection box.
    from freecad.SolidDesign.gui.panel import parts as P
    allowed = {P.ICON_BUTTON_CSS, P.active_css("QLineEdit"), P.active_css("QListWidget")}
    styled = [x.objectName() or x.metaObject().className()
              for x in [p.widget] + p.widget.findChildren(QtWidgets.QWidget)
              if x.styleSheet() and x.styleSheet() not in allowed]
    check(not styled, "the panel sets no other stylesheets: " + ", ".join(styled))
    p.mode.buttons["Cut"].click()
    wait(600)
    check(p.obj.Mode == "Cut" and p.obj.Label.startswith("Cut-Extrude"),
          "switching to Cut makes it a Cut-Extrude")
    i = p.d1.cond.findText("Through All")
    p.d1.cond.setCurrentIndex(i)
    wait(700)
    check(p.obj.EndCondition == "Through All", "end condition set from the combo")
    look = preview_look(p.preview.layers["result"])
    check(look[0] == tuple(round(c, 2) for c in pv.CUT_COLOR) and look[2],
          "Cut preview: transparent red, dashed edges %s" % (look,))
    check(p.sec_keep.isVisible(), "Bodies to Keep shows when the cut splits the body")
    check(p.keep_list.count() == 2, "two pieces listed")
    p.keep_mode.buttons["Selected bodies"].click()
    wait(300)
    it = p.keep_list.item(1)
    it.setCheckState(QtCore.Qt.Unchecked)
    wait(700)
    check(len(p.obj.KeepBodies) == 1, "unticking a piece keeps only the other")
    shot(task_panel_widget() or p.widget, "02_cut_keep_panel")
    shot(mw, "02_cut_keep_window")
    # Mode switch keeps inputs and renames (the user hasn't renamed it).
    p.mode.buttons["Add"].click()
    wait(700)
    check(p.obj.Label.startswith("Boss-Extrude"), "switching to Add renames to Boss-Extrude")
    check(p.obj.EndCondition == "Through All", "switching mode keeps the end condition")
    p.mode.buttons["Cut"].click()
    wait(700)
    check(p.obj.Label.startswith("Cut-Extrude"), "and back to Cut-Extrude")
    p._click_ok()
    wait(700)
    check(len(part.BodyIds) == 1, "only the kept piece remains")

    # ---- 3. A failing feature: error in place, OK disabled; Cancel removes it
    sk3 = sketch(doc, plane(part, "Top Plane"))
    circle(sk3, 0, 0, 5)
    circle(sk3, 6, 0, 5)
    app_part.add_to_part(part, sk3)
    doc.recompute()
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, sk3.Name)
    n_before = len(doc.Objects)
    Gui.runCommand("SD_Extrude")
    wait(900)
    p = extrude_panel.LAST[0]
    check(p.error.isVisible() and "Selected Contours" in p.error.value(),
          "overlapping sketch: the error says to use Selected Contours")
    from freecad.SolidDesign.gui.panel.base import task_buttons
    ok, _c = task_buttons()
    check(ok is not None and not ok.isEnabled(), "OK is disabled while the feature fails")
    # Pick the lens region the way a click inside it would.
    p.activate(p.contours)
    wait(300)
    from freecad.SolidDesign.core import regions
    lens = [r for r in regions.regions(sk3) if abs(r.face.CenterOfMass.x - 3) < 1e-6][0]
    p.contours.set_items([(lens.key(), "")])
    p._contours_changed()
    wait(800)
    check(not p.error.isVisible(), "picking a region clears the error")
    ok, _c = task_buttons()
    check(ok is not None and ok.isEnabled(), "OK is enabled again")
    shot(task_panel_widget() or p.widget, "03_contours_panel")
    shot(mw, "03_contours_window")
    p._click_cancel()
    wait(700)
    check(len(doc.Objects) == n_before, "Cancel removes the new feature")

    # ---- 4. Edit an existing feature: the panel shows what was chosen
    from freecad.SolidDesign.app import util
    cut = [o for o in doc.Objects if util.is_feature(o) and o.Label.startswith("Cut-Extrude")][0]
    import re
    check(re.match(r"^Cut-Extrude\d+$", cut.Label) is not None,
          "the cut has a SolidWorks-style name: " + cut.Label)
    old = extrude_panel.LAST[0]
    Gui.ActiveDocument.setEdit(cut.Name, 0)
    wait(900)
    check(extrude_panel.LAST[0] is not old, "double-click/edit opens the feature's panel")
    p = extrude_panel.LAST[0]
    check(p.d1.cond.currentText() == "Through All", "edit: the panel shows the end condition")
    check(p.keep_mode.value() == "Selected bodies", "edit: Bodies to Keep shows Selected bodies")
    p._click_cancel()
    wait(600)
    check(not Gui.Control.activeDialog(), "Cancel on an edit closes the panel")

    # ---- 5. SolidWorks flow: plane selected -> Extruded Boss/Base starts a sketch on it,
    #         closing the sketch opens Extrude with it
    import Part as _Part
    top = plane(part, "Top Plane")
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, top.Name)
    old = extrude_panel.LAST[0]
    Gui.runCommand("SD_Extrude")
    wait(800)
    sk5 = Gui.ActiveDocument.getInEdit().Object if Gui.ActiveDocument.getInEdit() else None
    check(sk5 is not None and sk5.TypeId.startswith("Sketcher"),
          "with a plane selected, Extruded Boss/Base opens a sketch on it")
    if sk5 is not None:
        check(sk5.AttachmentSupport[0][0] is top, "the sketch is on the selected plane")
        sk5.addGeometry(_Part.Circle(App.Vector(60, 10, 0), App.Vector(0, 0, 1), 4))
        doc.recompute()
        Gui.ActiveDocument.resetEdit()
        wait(1200)
        p = extrude_panel.LAST[0]
        check(p is not old and p.obj.Sketch is sk5,
              "closing the sketch opens Extrude with that sketch")
        # Click inside a region in the view: the ray hits the sketch plane.
        p.activate(p.contours)
        wait(400)
        view = Gui.ActiveDocument.ActiveView
        view.viewTop()
        Gui.SendMsgToActiveView("ViewFit")
        wait(400)
        pt = view.getPointOnViewport(App.Vector(60, 10, 0))
        p._on_click({"State": "DOWN", "Button": "BUTTON1", "Position": (int(pt[0]), int(pt[1]))})
        wait(800)
        check(len(p.obj.Contours) == 1, "a click inside the circle picks its region")
        shot(mw, "05_region_click_window")
        p._click_ok()
        wait(700)

    # ---- 6. Revolve: the sketch's centerline is the axis; Add mode
    import Part as _P
    skr = sketch(doc, plane(part, "Front Plane"))
    rect(skr, 70, 0, 74, 6)
    skr.addGeometry(_P.LineSegment(App.Vector(64, -10, 0), App.Vector(64, 10, 0)), True)
    app_part.add_to_part(part, skr)
    doc.recompute()
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, skr.Name)
    Gui.runCommand("SD_Revolve")
    wait(900)
    p = extrude_panel.LAST[0]
    check(type(p).__name__ == "RevolvePanel", "Revolve opens its panel")
    check(p.axis_box.items and "centerline" in p.axis_box.items[0][1],
          "the sketch's centerline fills the axis box")
    p.d1.angle.spin.setProperty("rawValue", 180.0)
    wait(700)
    check(not p.error.isVisible() and "result" in p.preview.layers, "revolve preview, no error")
    shot(task_panel_widget() or p.widget, "06_revolve_panel")
    shot(mw, "06_revolve_window")
    p._click_ok()
    wait(700)
    rev = [o for o in doc.Objects if o.Label == "Revolve1"]
    import math as _m
    check(len(rev) == 1 and abs(rev[0].AddSubShape.Volume - _m.pi * (10 ** 2 - 6 ** 2) * 6 / 2)
          < 1e-3, "OK makes Revolve1, half a ring")

    # ---- 7. Fillet: a preselected edge fills the panel; the model shows the base
    from freecad.SolidDesign.gui import selection as selmod
    body = [v for v in app_part.body_views(part) if v.Shape.BoundBox.XMax < 19][0]
    ei = [i for i, e in enumerate(body.Shape.Edges, 1)
          if abs(e.CenterOfMass.z - 12) < 1e-6 and abs(e.CenterOfMass.x) < 1e-6][0]
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, body.Name, "Edge%d" % ei)
    Gui.runCommand("SD_Fillet")
    wait(900)
    p = extrude_panel.LAST[0]
    check(type(p).__name__ == "FilletPanel", "Fillet opens its panel")
    check(len(p.items.items) == 1, "the preselected edge fills Items To Fillet")
    check(part.Tip is p.obj.BaseFeature, "while editing, the model shows the bodies before it")
    p.radius.spin.setProperty("rawValue", 3.0)
    wait(700)
    check(not p.error.isVisible() and "result" in p.preview.layers, "fillet preview, no error")
    shot(task_panel_widget() or p.widget, "07_fillet_panel")
    shot(mw, "07_fillet_window")
    p._click_ok()
    wait(700)
    fil = [o for o in doc.Objects if o.Label == "Fillet1"]
    check(len(fil) == 1 and not fil[0].ErrorMessage and part.Tip is fil[0],
          "OK makes Fillet1 and the bar is back at the end")

    # ---- 8. Chamfer: pick edges in the panel; Vertex type wants vertices
    Gui.Selection.clearSelection()
    Gui.runCommand("SD_Chamfer")
    wait(900)
    p = extrude_panel.LAST[0]
    check(type(p).__name__ == "ChamferPanel", "Chamfer opens its panel")
    check(p.active_box is p.items, "the empty Items box is the active one")
    body = [v for v in app_part.body_views(part) if v.Shape.BoundBox.XMax < 19][0]
    ei = [i for i, e in enumerate(body.Shape.Edges, 1)
          if abs(e.CenterOfMass.z - 12) < 1e-6 and abs(e.CenterOfMass.y - 20) < 1e-6]
    p.route(selmod.Sel(body, "Edge%d" % ei[0]))
    wait(200)
    p.route(selmod.Sel(body, "Vertex1"))
    wait(800)
    check(len(p.items.items) == 1 and p.items.note.isVisible(),
          "an edge is taken; a vertex is refused, with the reason under the box")
    check(not p.error.isVisible(), "chamfer preview, no error")
    shot(task_panel_widget() or p.widget, "08_chamfer_panel")
    p._click_ok()
    wait(700)

    # ---- 9. The rollback bar can never land in the part's group (no dependency loop)
    bar = app_part.rollback_bar(part)
    part.Group = part.Group + [bar]
    check(bar not in part.Group, "a bar dropped into the part's group is taken out again")
    check(not bar.OutList and part not in bar.OutList, "the bar doesn't depend on the part")
    doc.recompute()
    check("Invalid" not in part.State, "recompute after the drop: no dependency loop")

    # ---- tree
    tree = tree_widget()
    if tree is not None:
        expand_all(tree)
        lines = tree_lines(tree)
        views = app_part.body_views(part)
        check(views and all(v.ViewObject.Deviation <= 0.05 + 1e-9 and
                            v.ViewObject.AngularDeflection.Value <= 8.0 + 1e-9 and
                            "SDFineMesh" in v.ViewObject.PropertiesList for v in views),
              "bodies are drawn with the fine tessellation")
        from freecad.SolidDesign.app.part import folder
        f = folder(part, "solid")
        check(f.ViewObject.Proxy.getIcon() == ":/icons/folder.svg",
              "body folders use FreeCAD's folder icon")
        check("SD_RollToEnd" not in Gui.listCommands(), "no Roll to End command")
        check(Gui.Command.get("SD_Sketch").getInfo()["pixmap"] == ":/icons/SketcherWorkbench.svg",
              "the sketch tool uses the Sketcher workbench icon")
        log("TREE:\n" + "\n".join(lines))
        check(any("Solid Bodies (2)" in l for l in lines), "tree shows Solid Bodies (2)")
        check(any(l.strip().startswith("Chamfer1") for l in lines[:6]),
              "the body changed last by Chamfer1 is named Chamfer1")
        check(not any("Surface Bodies" in l for l in lines), "empty Surface Bodies is hidden")
        idx = [i for i, l in enumerate(lines) if l.strip() in ("Front Plane", "Top Plane",
                                                                "Right Plane", "Origin")]
        check(len(idx) == 4, "the origin planes are in the tree")
        check(not any("Axis" in l for l in lines), "the axes are hidden, as in SolidWorks")
        check(lines[-1].strip() == "Rollback bar", "rolled to the end, the bar is last")
        check(lines[1].strip() == "Part1" and lines[2].strip().startswith("Solid Bodies"),
              "the body folders come first under the part")
        shot(tree, "04_tree")
        # Only rolled-back or suppressed items look greyed (SolidWorks): the part,
        # features, folders and bar stay "visible" while drawing nothing.
        from freecad.SolidDesign.app import util as u
        items = [part] + u.features(part) + [app_part.folder(part, "solid"),
                                              app_part.rollback_bar(part)]
        hidden = [o.Label for o in items if not o.ViewObject.isVisible()]
        check(not hidden, "nothing in the history looks hidden: " + ", ".join(hidden))

    # ---- save, close, reopen in the GUI: view providers restore, tree is the same
    import tempfile
    path = os.path.join(tempfile.mkdtemp(), "smoke.FCStd")
    doc.saveAs(path)
    before = tree_lines(tree) if tree is not None else []
    App.closeDocument(doc.Name)
    wait(300)
    doc = App.openDocument(path)
    wait(800)
    part = app_part.find_parts(doc)[0]
    check(type(part.ViewObject.Proxy).__name__ == "PartVP", "reopened: the part's view provider is restored")
    tree = tree_widget()
    if tree is not None:
        expand_all(tree)
        after = tree_lines(tree)
        check([l.strip() for l in after[1:]] == [l.strip() for l in before[1:]],
              "reopened: the tree is the same")
        shot(tree, "05_tree_reopened")
    feat = [o for o in doc.Objects if u.is_feature(o)][0]
    Gui.ActiveDocument.setEdit(feat.Name, 0)
    wait(900)
    check(Gui.Control.activeDialog(), "reopened: a feature's panel opens")
    extrude_panel.LAST[0]._click_cancel()
    wait(500)


try:
    run()
except Exception:
    log("EXCEPTION\n" + traceback.format_exc())
    failures.append("exception")
log("RESULT", "FAIL" if failures else "OK", failures)
LOG.close()
os._exit(1 if failures else 0)
