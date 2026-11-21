# SPDX-License-Identifier: LGPL-2.1-or-later
"""GUI smoke test for Plane, Axis, body tools, patterns, Mirror and Hole Wizard.

    xvfb-run -a -s "-screen 0 1600x1000x24" freecad tests/gui/smoke_tools.py

Each tool: open it the way a user does (command, with or without a selection),
pick in its panel (calling what a click calls), check the preview, OK, check
the bodies. Screenshots go to $SD_SHOTS (default /tmp/sd_tools).
"""

import math
import os
import sys
import time
import traceback

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
SHOTS = os.environ.get("SD_SHOTS", "/tmp/sd_tools")
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


def task_panel():
    for w in Gui.getMainWindow().findChildren(QtWidgets.QWidget):
        if w.metaObject().className() == "Gui::TaskView::TaskView" and w.isVisible():
            return w
    return None


def check_tips(name):
    """Every control in an open panel must say what it does."""
    from freecad.SolidDesign.gui import extrude_panel
    from freecad.SolidDesign.gui.panel.parts import untipped
    p = extrude_panel.LAST[0]
    if p is None or p._closing:
        return
    p.widget.grab().save(os.path.join(SHOTS, name + "_form.png"))   # the whole panel
    gaps = untipped(p.widget)
    check(not gaps, "%s: every control has a tooltip %s" % (
        name, [g.metaObject().className() + ":" + (getattr(g, "text", lambda: "")() or "")
               for g in gaps]))


def shot(name):
    check_tips(name)
    tp = task_panel()
    if tp is not None:
        tp.grab().save(os.path.join(SHOTS, name + "_panel.png"))
    Gui.getMainWindow().grab().save(os.path.join(SHOTS, name + "_window.png"))


def check_command_icons():
    """Every Solid Design command's icon exists (FreeCAD shows a blank one if not)."""
    from PySide import QtCore as _QtCore
    missing = []
    for name in Gui.listCommands():
        if not name.startswith("SD_"):
            continue
        pix = Gui.Command.get(name).getInfo()["pixmap"]
        if not (os.path.exists(pix) or _QtCore.QFile.exists(pix)):
            missing.append((name, pix))
    check(not missing, "every command has its icon %s" % missing)


def run():
    from freecad.SolidDesign.app import part as app_part
    from freecad.SolidDesign.app import util
    from freecad.SolidDesign.gui import extrude_panel
    from freecad.SolidDesign.gui.panel.base import task_buttons
    from freecad.SolidDesign.gui.selection import Sel
    from helpers import V, circle, extrude, plane, rect, sketch

    def panel():
        return extrude_panel.LAST[0]

    def ok_enabled():
        ok, _c = task_buttons()
        return ok is not None and ok.isEnabled()

    def finish(p, name):
        # The only stylesheets: the icon buttons' padding and the active selection box.
        from freecad.SolidDesign.gui.panel import parts as P
        allowed = {P.ICON_BUTTON_CSS, P.active_css("QLineEdit"), P.active_css("QListWidget")}
        styled = [x.metaObject().className() for x in [p.widget] + p.widget.findChildren(
            QtWidgets.QWidget) if x.styleSheet() and x.styleSheet() not in allowed]
        check(not styled, name + ": no other stylesheets in the panel " + ", ".join(styled))
        check(not p.error.isVisible(), name + ": no error ({})".format(p.error.value()))
        check(ok_enabled(), name + ": OK enabled")
        shot(name)
        p._click_ok()
        wait(700)
        check(not Gui.Control.activeDialog(), name + ": OK closes the panel")

    def volumes():
        return {b.id: b.shape.Volume for b in app_part.tip_bodies(part)}

    def view_of(bid):
        return [v for v in app_part.body_views(part) if v.BodyId == bid][0]

    def face_of(view, point, normal):
        for i, f in enumerate(view.Shape.Faces, 1):
            if f.isInside(point, 1e-6, True):
                u, v = f.Surface.parameter(point)
                if f.normalAt(u, v).getAngle(normal) < 1e-6:
                    return "Face%d" % i
        raise AssertionError("no face")

    mw = Gui.getMainWindow()
    mw.resize(1500, 950)
    Gui.activateWorkbench("SolidDesignWorkbench")
    check_command_icons()
    wait()
    doc = App.newDocument("Tools")
    Gui.runCommand("SD_Part")
    wait()
    part = app_part.find_parts(doc)[0]
    for x0, x1 in ((0, 40), (30, 70), (100, 140)):           # A, B overlap; C apart
        sk = sketch(doc, plane(part, "Top Plane"))
        rect(sk, x0, 0, x1, 20)
        app_part.add_to_part(part, sk)
        doc.recompute()
        extrude(doc, part, sk, Depth=10, MergeResult=False)
    ida, idb, idc = part.BodyIds
    Gui.ActiveDocument.ActiveView.viewIsometric()
    Gui.SendMsgToActiveView("ViewFit")
    wait()

    # ---- Plane: preselect the Top Plane -> Offset Distance guessed
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, plane(part, "Top Plane").Name)
    Gui.runCommand("SD_Plane")
    wait(900)
    p = panel()
    check(type(p).__name__ == "RefGeomPanel" and
          p.obj.Proxy.constraints(p.obj) == ["Offset Distance"],
          "Plane: preselected plane -> Offset Distance")
    p.dist.spin.setProperty("rawValue", 5.0)
    wait(600)
    pl = p.obj
    finish(p, "plane")
    check(abs(pl.Shape.Faces[0].CenterOfMass.z - 5) < 1e-6, "Plane1 at z = 5")

    # ---- Axis: pick two origin planes in the panel
    Gui.Selection.clearSelection()
    Gui.runCommand("SD_Axis")
    wait(900)
    p = panel()
    p.route(Sel(plane(part, "Front Plane")))
    wait(200)
    p.route(Sel(plane(part, "Right Plane")))
    wait(700)
    check(len(p.refs.items) == 2 and p.obj.Type == "Two Planes",
          "Axis: two planes picked -> Two Planes")
    ax = p.obj
    finish(p, "axis")

    # ---- Combine: preselect two bodies in the view
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, view_of(ida).Name)
    Gui.Selection.addSelection(doc.Name, view_of(idb).Name)
    Gui.runCommand("SD_Combine")
    wait(900)
    p = panel()
    check(type(p).__name__ == "CombinePanel" and len(p.bodies.items) == 2,
          "Combine: the two preselected bodies fill the panel")
    check(part.Tip is p.obj.BaseFeature, "Combine: the model shows the bodies before it")
    finish(p, "combine")
    v = volumes()
    check(len(v) == 2 and abs(v[ida] - (8000 + 8000 - 2000)) < 1e-6,
          "Combine Add: A + B = one body with A's ID")

    # ---- Split by Plane1 (picked in the panel), name a piece
    Gui.Selection.clearSelection()
    Gui.runCommand("SD_Split")
    wait(900)
    p = panel()
    p.route(Sel(pl))
    wait(900)
    check(p.pieces.count() == 4, "Split: 4 pieces listed (2 bodies x 2)")
    it = p.pieces.item(1)
    it.setText("Lid")
    wait(700)
    check("Lid" in dict(p.obj.PieceNames).values(), "Split: a renamed piece keeps its name")
    finish(p, "split")
    names = [app_part.clean_label(x.Label) for x in app_part.body_views(part)]
    check("Lid" in names and len(part.BodyIds) == 4, "Split: 4 bodies, one named Lid")

    # ---- Delete/Keep from the body context menu path (body preselected)
    victim = [b for b in part.BodyIds if b not in (ida, idc)][0]
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, view_of(victim).Name)
    Gui.runCommand("SD_DeleteBody")
    wait(900)
    p = panel()
    check(len(p.bodies.items) == 1, "Delete/Keep: the preselected body fills the panel")
    finish(p, "delete")
    check(victim not in part.BodyIds and len(part.BodyIds) == 3, "Delete: one body fewer")

    # ---- Move/Copy: copy C twice along Delta Y
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, view_of(idc).Name)
    Gui.runCommand("SD_MoveCopy")
    wait(900)
    p = panel()
    p.copy.setChecked(True)
    wait(200)
    p.copies.spin.setValue(2)
    p.dy.spin.setProperty("rawValue", 30.0)
    wait(800)
    check("result" in p.preview.layers, "Move/Copy: preview")
    finish(p, "movecopy")
    check(len(part.BodyIds) == 5, "Move/Copy: two copies added")

    # ---- Move/Copy Body, Constraints mode: C's bottom face onto A's top face
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, view_of(idc).Name)
    Gui.runCommand("SD_MoveCopy")
    wait(900)
    p = panel()
    p.mode_combo.setCurrentIndex(p.mode_combo.findText("Constraints"))
    wait(300)
    sec, kind, moving, fixed = p.mates[0][:4]
    check(sec.isVisible() and not p.sec_t.isVisible(), "Constraints: a constraint section "
          "shows, Translate hides")
    kind.setCurrentIndex(kind.findText("Coincident"))
    wait(300)
    vc = view_of(idc)
    p.activate(moving)
    p.route(Sel(vc, face_of(vc, V(120, 10, 0), V(0, 0, -1)), V(120, 10, 0)))
    wait(300)
    va = view_of(ida)
    zt = va.Shape.BoundBox.ZMax
    p.activate(fixed)
    p.route(Sel(va, face_of(va, V(10, 10, zt), V(0, 0, 1)), V(10, 10, zt)))
    wait(900)
    check(p.mates[1][0].isVisible(), "Constraints: the next empty constraint appears")
    finish(p, "constraints")
    zc = app_part.tip_bodies(part).get(idc).shape.BoundBox.ZMin
    check(abs(zc - zt) < 1e-5, "Constraints: C now sits on A's top (z = {:.3f})".format(zc))

    # ---- Hole Wizard: click two points on A's top face
    Gui.Selection.clearSelection()
    Gui.runCommand("SD_HoleWizard")
    wait(900)
    p = panel()
    check(type(p).__name__ == "HolePanel" and p.active_box is p.positions,
          "Hole Wizard: positions box active")
    va = view_of(ida)
    zt = va.Shape.BoundBox.ZMax
    top = face_of(va, V(10, 10, zt), V(0, 0, 1))
    p.route(Sel(va, top, V(10, 10, zt)))
    wait(700)
    p.route(Sel(va, top, V(20, 10, zt)))
    wait(900)
    check(p.obj.Sketch is not None and len(p.obj.Sketch.Geometry) == 2,
          "Hole Wizard: two clicks make two points in one sketch on the face")
    p.kind.setCurrentIndex(p.kind.findText("Hole"))
    p.end.setCurrentIndex(p.end.findText("Through All"))
    wait(800)
    hole = p.obj
    finish(p, "hole")
    check(hole.Label.startswith("M6 Clearance Hole"), "Hole: SolidWorks name " + hole.Label)

    # ---- Linear Pattern of the hole feature along X Axis (picked in the panel)
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, hole.Name)
    Gui.runCommand("SD_LinearPattern")
    wait(900)
    p = panel()
    check(len(p.feats.items) == 1, "Linear Pattern: the preselected feature fills the panel")
    p.activate(p.dir1)
    p.route(Sel(plane(part, "X Axis")))
    wait(300)
    p.sp1.spin.setProperty("rawValue", 5.0)
    p.n1.spin.setValue(2)
    wait(900)
    finish(p, "lpattern")

    # ---- Circular Pattern of body C's copy about Axis1
    last = part.BodyIds[-1]
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, view_of(last).Name)
    Gui.runCommand("SD_CircularPattern")
    wait(900)
    p = panel()
    p.activate(p.axis)
    p.route(Sel(ax))
    wait(300)
    p.n.spin.setValue(3)
    wait(900)
    n_before = len(part.BodyIds)
    finish(p, "cpattern")
    check(len(part.BodyIds) == n_before + 2, "Circular Pattern: two body copies")

    # ---- Mirror the hole about Right Plane
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, hole.Name)
    Gui.runCommand("SD_Mirror")
    wait(900)
    p = panel()
    p.activate(p.plane)
    rp = [o for o in part.Origin if o.Label == "Right Plane"][0]
    p.route(Sel(rp))
    wait(900)
    check(len(p.plane.items) == 1, "Mirror: plane picked")
    mirror = p.obj
    finish(p, "mirror")
    check(mirror.ErrorMessage == "" or "cuts nothing" in mirror.WarningMessage,
          "Mirror: computes (the mirrored hole falls off the part, with a warning)")

    # ---- Sweep: profile preselected, path picked in the panel
    import Part as _P
    path = sketch(doc, plane(part, "Front Plane"))
    path.addGeometry(_P.LineSegment(V(200, 0, 0), V(200, 20, 0)))
    prof = sketch(doc, plane(part, "Top Plane"))
    circle(prof, 200, 0, 2)
    for s in (path, prof):
        app_part.add_to_part(part, s)
    doc.recompute()
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, prof.Name)
    Gui.runCommand("SD_Sweep")
    wait(900)
    p = panel()
    check(type(p).__name__ == "SweepPanel" and p.obj.Sketch is prof,
          "Sweep: the preselected profile fills the panel")
    p.activate(p.path)
    p.route(Sel(path))
    wait(900)
    finish(p, "sweep")
    sw = [o for o in doc.Objects if o.Label == "Sweep1"][0]
    check(abs(sw.AddSubShape.Volume - math.pi * 4 * 20) < 1e-3, "Sweep: the tube's volume")

    # ---- Loft: two profiles, the second picked in the panel
    l1 = sketch(doc, plane(part, "Top Plane"))
    rect(l1, 240, 0, 250, 10)
    l2 = sketch(doc, plane(part, "Top Plane"),
                attach_offset=App.Placement(V(0, 0, 15), App.Rotation()))
    circle(l2, 245, 5, 3)
    for s in (l1, l2):
        app_part.add_to_part(part, s)
    doc.recompute()
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, l1.Name)
    Gui.runCommand("SD_Loft")
    wait(900)
    p = panel()
    p.activate(p.profiles)
    p.route(Sel(l2))
    wait(900)
    check(len(p.profiles.items) == 2, "Loft: two profiles in order")
    finish(p, "loft")

    # ---- Shell: the top face of a box body preselected
    lv = [v for v in app_part.body_views(part) if v.Shape.BoundBox.XMin > 99
          and v.Shape.BoundBox.XMax < 141 and v.Shape.BoundBox.ZMin > -1e-6][0]
    zt = lv.Shape.BoundBox.ZMax
    fb = [i for i, f in enumerate(lv.Shape.Faces, 1)
          if abs(f.CenterOfMass.z - zt) < 1e-6 and f.Surface.TypeId == "Part::GeomPlane"][0]
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, lv.Name, "Face%d" % fb)
    Gui.runCommand("SD_Shell")
    wait(900)
    p = panel()
    check(type(p).__name__ == "ShellPanel" and len(p.faces.items) == 1,
          "Shell: the preselected face fills Faces to remove")
    p.t.spin.setProperty("rawValue", 0.5)
    wait(900)
    finish(p, "shell")

    feats = [o for o in part.Group if util.is_feature(o) or util.role(o) == "refgeom"]
    log("HISTORY: " + ", ".join(o.Label for o in feats))
    check(all(not o.ErrorMessage for o in feats), "no feature in the history has an error")

    # ---- The newer tools, in a document of their own.
    doc = App.newDocument("Tools2")
    Gui.runCommand("SD_Part")
    wait()
    part = app_part.find_parts(doc)[0]

    # ---- Draft: a box's four sides preselected, the bottom face picked as the neutral plane
    s = sketch(doc, plane(part, "Top Plane"))
    rect(s, 200, 0, 240, 30)
    doc.recompute()
    from freecad.SolidDesign.app import part as _pm
    _pm.add_to_part(part, s)
    before = set(part.BodyIds)
    box = extrude(doc, part, s, Depth=20)
    wait(500)
    new = [b for b in part.BodyIds if b not in before]
    bv = view_of(new[0])
    Gui.Selection.clearSelection()
    for pt, n in ((V(220, 0, 10), V(0, -1, 0)), (V(240, 15, 10), V(1, 0, 0)),
                  (V(220, 30, 10), V(0, 1, 0)), (V(200, 15, 10), V(-1, 0, 0))):
        Gui.Selection.addSelection(doc.Name, bv.Name, face_of(bv, pt, n))
    Gui.runCommand("SD_Draft")
    wait(900)
    p = panel()
    check(type(p).__name__ == "DraftPanel" and len(p.faces.items) == 4,
          "Draft: the preselected faces fill Faces to Draft")
    p.route(Sel(bv, face_of(bv, V(220, 15, 0), V(0, 0, -1))))
    wait(500)
    p.angle.spin.setProperty("rawValue", 2.0)
    wait(900)
    finish(p, "draft")
    # The Parting Line groups have their tooltips too.
    Gui.ActiveDocument.setEdit([o for o in part.Group if getattr(getattr(o, "Proxy", None),
                                                                  "TYPE", "") == "Draft"][0].Name)
    wait(700)
    p = panel()
    p.kind.setCurrentText("Parting Line")
    wait(700)
    check_tips("draft_parting")
    p.kind.setCurrentText("Step Draft")
    wait(700)
    check_tips("draft_step")
    p.kind.setCurrentText("Neutral Plane")
    wait(700)
    p._click_ok()
    wait(700)

    # ---- Rib: a line across a channel
    for x0, x1, d in ((300, 340, 2), (300, 302, 12), (338, 340, 12)):
        s = sketch(doc, plane(part, "Top Plane"))
        rect(s, x0, 0, x1, 20)
        doc.recompute()
        _pm.add_to_part(part, s)
        extrude(doc, part, s, Depth=d)
    import Part
    s = sketch(doc, plane(part, "Front Plane"),
               attach_offset=App.Placement(V(0, 0, -10), App.Rotation()))
    s.addGeometry(Part.LineSegment(V(310, 8, 0), V(330, 8, 0)))
    _pm.add_to_part(part, s)
    doc.recompute()
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, s.Name)
    Gui.runCommand("SD_Rib")
    wait(900)
    p = panel()
    check(type(p).__name__ == "RibPanel" and p.sketch_box.items, "Rib: the selected sketch")
    finish(p, "rib")

    # ---- Fillet types: a variable fillet on an edge, then a full round on a block's top
    s = sketch(doc, plane(part, "Top Plane"))
    rect(s, 400, 0, 440, 6)
    doc.recompute()
    _pm.add_to_part(part, s)
    before = set(part.BodyIds)
    extrude(doc, part, s, Depth=20)
    wait(400)
    fv = view_of([b for b in part.BodyIds if b not in before][0])
    edge = [("Edge%d" % i) for i, e in enumerate(fv.Shape.Edges, 1)
            if abs(e.CenterOfMass.z - 20) < 1e-6 and abs(e.CenterOfMass.y) < 1e-6][0]
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, fv.Name, edge)
    Gui.runCommand("SD_Fillet")
    wait(900)
    p = panel()
    p.ftype.setCurrentText("Variable Size")
    wait(900)
    check(p.r_r0.widget.isVisible() and not p.r_radius.widget.isVisible(),
          "Variable Size shows the start and end radii")
    finish(p, "fillet_variable")
    Gui.Selection.clearSelection()
    Gui.runCommand("SD_Fillet")
    wait(900)
    p = panel()
    p.ftype.setCurrentText("Full Round Fillet")
    wait(500)
    fv = view_of(fv.BodyId)
    check(p.active_box is p.set1, "Full Round: the first side face box takes the picks")
    p.route(Sel(fv, face_of(fv, V(420, 0, 10), V(0, -1, 0))))
    wait(300)
    check(p.active_box is p.centre, "Full Round: then the centre face box")
    top = [i for i, f in enumerate(fv.Shape.Faces, 1)
           if f.Surface.TypeId == "Part::GeomPlane" and abs(f.CenterOfMass.z - 20) < 1e-6
           and f.normalAt(0, 0).z > 0.9]
    p.route(Sel(fv, "Face%d" % top[0]))
    wait(300)
    check(p.active_box is p.set2, "Full Round: then the second side")
    p.route(Sel(fv, face_of(fv, V(420, 6, 10), V(0, 1, 0))))
    wait(900)
    finish(p, "fillet_full_round")

    # ---- Offset Surface and Move Face on a block's top
    s = sketch(doc, plane(part, "Top Plane"))
    rect(s, 500, 0, 520, 10)
    doc.recompute()
    _pm.add_to_part(part, s)
    before = set(part.BodyIds)
    extrude(doc, part, s, Depth=10)
    wait(400)
    bid = [b for b in part.BodyIds if b not in before][0]
    mv = view_of(bid)
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, mv.Name, face_of(mv, V(510, 5, 10), V(0, 0, 1)))
    Gui.runCommand("SD_OffsetSurface")
    wait(900)
    p = panel()
    check(type(p).__name__ == "OffsetSurfacePanel" and len(p.faces.items) == 1,
          "Offset Surface: the preselected face")
    p.dist.spin.setProperty("rawValue", 5.0)
    wait(800)
    finish(p, "offset_surface")
    check("surface" in list(part.BodyKinds), "Offset Surface makes a surface body")
    mv = view_of(bid)
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, mv.Name, face_of(mv, V(510, 5, 10), V(0, 0, 1)))
    Gui.runCommand("SD_MoveFace")
    wait(900)
    p = panel()
    check(type(p).__name__ == "MoveFacePanel" and len(p.faces.items) == 1,
          "Move Face: the preselected face")
    p.dist.spin.setProperty("rawValue", 2.0)
    wait(800)
    p.kind.setCurrentText("Rotate")
    wait(500)
    check_tips("move_face_rotate")
    p.kind.setCurrentText("Offset")
    wait(800)
    finish(p, "move_face")
    check(abs(app_part.tip_bodies(part).get(bid).shape.BoundBox.ZMax - 12) < 1e-6,
          "Move Face: the top moved up 2")

    # ---- Split Line: a sketch above the block, projected onto its top
    sp = sketch(doc, plane(part, "Top Plane"),
                attach_offset=App.Placement(V(0, 0, 30), App.Rotation()))
    rect(sp, 505, 2, 515, 8)
    _pm.add_to_part(part, sp)
    doc.recompute()
    mv = view_of(bid)
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, sp.Name)
    Gui.Selection.addSelection(doc.Name, mv.Name, face_of(mv, V(510, 1, 12), V(0, 0, 1)))
    Gui.runCommand("SD_SplitLine")
    wait(900)
    p = panel()
    check(type(p).__name__ == "SplitLinePanel" and len(p.faces.items) == 1 and
          p.sketch.items, "Split Line: the preselected face and sketch")
    wait(800)
    for t in ("Silhouette", "Intersection"):
        p.kind.setCurrentText(t)
        wait(400)
        check_tips("split_line_" + t.lower())
    p.kind.setCurrentText("Projection")
    wait(900)
    finish(p, "split_line")
    check(len(app_part.tip_bodies(part).get(bid).shape.Faces) == 7,
          "Split Line: the top is split in two")

    # ---- Point and Coordinate System
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(doc.Name, bv.Name, "Vertex1")
    Gui.runCommand("SD_Point")
    wait(900)
    p = panel()
    check(type(p).__name__ == "RefGeomPanel" and p.TITLE == "Point", "Point opens its panel")
    finish(p, "point")
    Gui.Selection.clearSelection()
    Gui.runCommand("SD_CoordinateSystem")
    wait(900)
    p = panel()
    check(type(p).__name__ == "RefGeomPanel" and p.TITLE == "Coordinate System",
          "Coordinate System opens its panel")
    finish(p, "csys")

    feats = [o for o in part.Group if util.is_feature(o) or util.role(o) == "refgeom"]
    log("HISTORY: " + ", ".join(o.Label for o in feats))
    check(all(not o.ErrorMessage for o in feats), "no feature in the history has an error")


try:
    run()
except Exception:
    log("EXCEPTION\n" + traceback.format_exc())
    failures.append("exception")
log("RESULT", "FAIL" if failures else "OK", failures)
LOG.close()
os._exit(1 if failures else 0)

