# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Ryan Kembrey <ryan.FreeCAD@gmail.com>
# SPDX-FileNotice: Part of the Solid Design addon.

"""One screenshot per tool: its panel open on a sample part, with its preview.

``RECIPES`` maps each tool's command to a function that builds a part and opens
the tool the way a user does (select, then click the tool; pick in its boxes).
The shot then grabs the window and records the panel (scenes.record_panel) for
the tool's page. A recipe that returns an image itself (tools without a panel)
is used as it is.

The build fails when a documented tool has no recipe here, so a new tool gets
its picture. Tools with nothing to show are listed in ``NO_SHOT``.

Sample geometry: ``ctx.plate()`` is a 60 x 40 x 8 plate centred on the origin
(x -30..30, y -20..20, z 0..8), so the origin planes cut through its middle.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import shot, tool_shot_id
from .scenes import record_panel

TOP = (0, 0, 8)                  # a point on the plate's top face
UP, DOWN = (0, 0, 1), (0, 0, -1)
FRONT_EDGE = ((-30, -20, 8), (30, -20, 8))
RIGHT_EDGE = ((30, -20, 8), (30, 20, 8))
FRONT_FACE = ((0, -20, 4), (0, -1, 0))
RIGHT_FACE = ((30, 0, 4), (1, 0, 0))

#: Tools with nothing to picture: their page says what they do.
NO_SHOT = {"SD_Rebuild", "SD_RepeatLast"}


def _plate(ctx, **k):
    doc, part, f = ctx.plate(**k)
    return doc, part, ctx.bodies(part)[0]


def _top(ctx, v):
    return (v, ctx.face(v, TOP, UP))


# -- part, sketch, features --------------------------------------------------------------

def part(ctx):
    from .scenes import _expand_tree

    ctx.new_part()
    ctx.show_tree()
    _expand_tree(ctx)
    ctx.iso()
    return ctx.window()


def sketch(ctx):
    doc, part, v = _plate(ctx)
    ctx.iso()
    ctx.select(_top(ctx, v))
    ctx.run("SD_Sketch", 1.5)
    return ctx.window()


def extrude(ctx):
    doc, part = ctx.new_part()
    sk = ctx.sketch(part)
    ctx.rect(sk, -30, -20, 30, 20)
    ctx.circle(sk, 15, 0, 6)
    doc.recompute()
    ctx.select(sk)
    p = ctx.run("SD_Extrude")
    ctx.set_value(p.d1.depth, 12)
    ctx.iso()


def revolve(ctx):
    doc, part = ctx.new_part()
    sk = ctx.sketch(part, "Front Plane")
    ctx.rect(sk, 10, 0, 20, 15)
    doc.recompute()
    ctx.select(sk)
    ctx.run("SD_Revolve")
    ctx.pick(ctx.box("Axis"), ctx.axis(part, "Z"))
    ctx.iso()


def _sweep_parts(ctx, open_profile=False):
    doc, part = ctx.new_part()
    path = ctx.sketch(part, "Front Plane", label="Path")
    ctx.line(path, (0, 0), (30, 0))
    ctx.arc(path, 30, 20, 20, -90, 0)
    prof = ctx.sketch(part, "Right Plane", label="Profile")
    if open_profile:
        ctx.arc(prof, 0, 0, 4, 0, 180)
    else:
        ctx.circle(prof, 0, 0, 4)
    doc.recompute()
    return doc, part, prof, path


def sweep(ctx, command="SD_Sweep", open_profile=False):
    doc, part, prof, path = _sweep_parts(ctx, open_profile)
    ctx.select(prof)
    ctx.run(command)
    ctx.pick(ctx.box("Path"), path)
    ctx.iso()


def _loft_parts(ctx, open_profiles=False):
    doc, part = ctx.new_part()
    a = ctx.sketch(part, label="Bottom")
    b = ctx.sketch(part, at=(0, 0, 25), label="Top")
    if open_profiles:
        ctx.arc(a, 0, 0, 15, 0, 180)
        ctx.arc(b, 0, 0, 8, 0, 180)
    else:
        ctx.rect(a, -15, -10, 15, 10)
        ctx.circle(b, 0, 0, 7)
    doc.recompute()
    return doc, part, a, b


def loft(ctx, command="SD_Loft", open_profiles=False):
    doc, part, a, b = _loft_parts(ctx, open_profiles)
    ctx.select(a, b)
    ctx.run(command)
    box = ctx.box("Profiles")
    if len(box.items) < 2:
        box.clear_items()
        ctx.pick(box, a)
        ctx.pick(box, b)
    ctx.iso()


def boundary(ctx, command="SD_Boundary", open_profiles=False):
    doc, part, a, b = _loft_parts(ctx, open_profiles)
    ctx.select()
    ctx.run(command)
    box = ctx.box("Direction 1") if _has_box(ctx, "Direction 1") else ctx.box("Profiles")
    ctx.pick(box, a)
    ctx.pick(box, b)
    ctx.iso()


def _has_box(ctx, name):
    try:
        ctx.box(name)
        return True
    except LookupError:
        return False


def fillet(ctx):
    doc, part, v = _plate(ctx)
    ctx.select((v, ctx.edge(v, *FRONT_EDGE)), (v, ctx.edge(v, *RIGHT_EDGE)))
    p = ctx.run("SD_Fillet")
    ctx.set_value(p.radius if hasattr(p, "radius") else p.r, 4)
    ctx.iso()


def chamfer(ctx):
    doc, part, v = _plate(ctx)
    ctx.select((v, ctx.edge(v, *FRONT_EDGE)), (v, ctx.edge(v, *RIGHT_EDGE)))
    ctx.run("SD_Chamfer")
    ctx.iso()


def shell(ctx):
    doc, part, v = _plate(ctx, t=20)
    ctx.select((v, ctx.face(v, (0, 0, 20), UP)))
    ctx.run("SD_Shell")
    ctx.iso()


def draft(ctx):
    doc, part, v = _plate(ctx, t=20)
    sides = [ctx.face(v, (0, -20, 10)), ctx.face(v, (30, 0, 10)), ctx.face(v, (0, 20, 10)),
             ctx.face(v, (-30, 0, 10))]
    ctx.select(*[(v, f) for f in sides])
    ctx.run("SD_Draft")
    ctx.pick(ctx.box("Neutral Plane"), v, ctx.face(v, (0, 0, 0), DOWN))
    ctx.iso()


def rib(ctx):
    doc, part = ctx.new_part()
    base = ctx.rect(ctx.sketch(part), -20, -10, 20, 10)
    doc.recompute()
    ctx.extrude(part, base, 2)
    for x0 in (-20, 18):
        s = ctx.rect(ctx.sketch(part), x0, -10, x0 + 2, 10)
        doc.recompute()
        ctx.extrude(part, s, 12)
    s = ctx.sketch(part, "Front Plane")
    ctx.line(s, (-10, 8), (10, 8))
    doc.recompute()
    ctx.select(s)
    ctx.run("SD_Rib")
    ctx.iso()


def wrap(ctx):
    doc, part = ctx.new_part()
    cy = ctx.circle(ctx.sketch(part), 0, 0, 10)
    doc.recompute()
    ctx.extrude(part, cy, 30)
    w = ctx.sketch(part, "Right Plane", at=(0, 0, 12))
    ctx.rect(w, -3, 10, 3, 20)
    doc.recompute()
    v = ctx.bodies(part)[0]
    ctx.select(w, (v, ctx.face(v, (10, 0, 15), (1, 0, 0))))
    ctx.run("SD_Wrap")
    ctx.camera((-1, 0, -0.3))


def dome(ctx):
    doc, part, v = _plate(ctx)
    ctx.select(_top(ctx, v))
    p = ctx.run("SD_Dome")
    ctx.set_value(p.dist, 6)
    ctx.iso()


def _two_boxes(ctx, overlap=True):
    doc, part = ctx.new_part()
    a = ctx.rect(ctx.sketch(part), -20, -15, 10, 15)
    doc.recompute()
    ctx.extrude(part, a, 15)
    b = ctx.rect(ctx.sketch(part, at=(0, 0, 5)), (-5 if overlap else 15), -10, 25, 10)
    doc.recompute()
    ctx.extrude(part, b, 15, merge=False)
    return doc, part, ctx.bodies(part)


def intersect(ctx):
    doc, part, views = _two_boxes(ctx)
    ctx.select(*views)
    ctx.run("SD_Intersect", 1.5)
    ctx.iso()


def hole_wizard(ctx):
    doc, part, v = _plate(ctx, t=12)
    top = ctx.face(v, (0, 0, 12), UP)
    ctx.select()
    ctx.run("SD_HoleWizard", 1.5)
    ctx.pick(ctx.box("Positions"), v, top, (-15, 5, 12))
    ctx.pick(ctx.box("Positions"), v, top, (15, 5, 12), 1.5)
    ctx.iso()


def _shaft(ctx, r=5, h=24):
    doc, part = ctx.new_part()
    sk = ctx.circle(ctx.sketch(part), 0, 0, r)
    doc.recompute()
    ctx.extrude(part, sk, h)
    v = ctx.bodies(part)[0]
    top = [("Edge%d" % i) for i, e in enumerate(v.Shape.Edges, 1)
           if hasattr(e.Curve, "Radius") and abs(e.BoundBox.ZMin - h) < 1e-6][0]
    return doc, part, v, top


def thread(ctx):
    doc, part, v, top = _shaft(ctx)
    ctx.select((v, top))
    ctx.run("SD_Thread", 3.0)
    ctx.iso()


def cosmetic_thread(ctx):
    doc, part, v, top = _shaft(ctx)
    ctx.select((v, top))
    ctx.run("SD_CosmeticThread", 1.5)
    ctx.iso()


def mounting_boss(ctx):
    doc, part, v = _plate(ctx, t=4)
    ctx.select()
    ctx.run("SD_MountingBoss", 1.0)
    ctx.pick(ctx.box("Position"), v, ctx.face(v, (0, 0, 4), UP), (10, 0, 4), 1.5)
    ctx.iso()


def snap_hook(ctx):
    doc, part, v = _plate(ctx, t=4)
    ctx.select()
    ctx.run("SD_SnapHook", 1.0)
    ctx.pick(ctx.box("Position"), v, ctx.face(v, (0, 0, 4), UP), (10, 0, 4), 1.5)
    ctx.iso()


def lip_groove(ctx):
    doc, part = ctx.new_part()
    a = ctx.rect(ctx.sketch(part), -30, -20, 30, 20)
    doc.recompute()
    ctx.extrude(part, a, 15)
    b = ctx.rect(ctx.sketch(part, at=(0, 0, 15)), -30, -20, 30, 20)
    doc.recompute()
    ctx.extrude(part, b, 6, merge=False)
    views = ctx.bodies(part)
    lid = [b for b in views if b.Shape.BoundBox.ZMin > 14][0]
    ctx.select(*views)
    ctx.run("SD_LipGroove", 1.0)
    ctx.pick(ctx.box("Items"), lid, ctx.face(lid, (0, 0, 15), DOWN), None, 1.5)
    ctx.iso()


def vent(ctx):
    doc, part, v = _plate(ctx, t=3)
    sk = ctx.sketch(part, at=(0, 0, 3))
    ctx.circle(sk, 0, 0, 15)
    ctx.line(sk, (-15, 0), (15, 0))
    ctx.line(sk, (0, -15), (0, 15))
    ctx.circle(sk, 0, 0, 7)
    doc.recompute()
    ctx.select(sk)
    ctx.run("SD_Vent", 1.5)
    ctx.iso()


# -- patterns --------------------------------------------------------------------------

def _plate_with_hole(ctx, x=-20, y=-12, r=3, w=60, d=40):
    doc, part, f = ctx.plate(w=w, d=d)
    hs = ctx.circle(ctx.sketch(part, at=(0, 0, 8)), x, y, r)
    doc.recompute()
    hole = ctx.extrude(part, hs, 8, mode="Cut", Reverse=True)
    return doc, part, ctx.bodies(part)[0], hole


def _plate_with_boss(ctx, x=15, y=0):
    doc, part, f = ctx.plate()
    boss = ctx.boss(part, x, y, 5, 10, 8)
    return doc, part, ctx.bodies(part)[0], boss


def linear_pattern(ctx):
    doc, part, v, hole = _plate_with_hole(ctx)
    ctx.select(hole)
    p = ctx.run("SD_LinearPattern")
    ctx.pick(ctx.box("Direction 1"), v, ctx.edge(v, (-30, -20, 8), (30, -20, 8)))
    ctx.set_value(p.n1.spin if hasattr(p.n1, "spin") else p.n1, 4)
    ctx.iso()


def circular_pattern(ctx):
    doc, part, v, hole = _plate_with_hole(ctx, x=12, y=0, w=50, d=50)
    ctx.select(hole)
    ctx.run("SD_CircularPattern")
    ctx.pick(ctx.box("Axis"), ctx.axis(part, "Z"))
    ctx.iso()


def mirror(ctx):
    doc, part, v, boss = _plate_with_boss(ctx)
    ctx.select(boss, ctx.plane(part, "Right Plane"))
    ctx.run("SD_Mirror")
    ctx.iso()


def curve_pattern(ctx):
    doc, part, v, hole = _plate_with_hole(ctx, x=-24, y=0, w=60, d=40)
    track = ctx.sketch(part, at=(0, 0, 8))
    ctx.arc(track, 0, -40, 45, 58, 122)
    doc.recompute()
    ctx.select(track)
    ctx.run("SD_CurvePattern")
    ctx.pick(ctx.box("Features"), hole)
    ctx.iso()


def sketch_pattern(ctx):
    import FreeCAD as App
    import Part

    doc, part, v, hole = _plate_with_hole(ctx, x=-20, y=-12)
    pts = ctx.sketch(part, at=(0, 0, 8))
    for x, y in ((-20, -12), (0, 8), (20, -4), (10, 12)):
        pts.addGeometry(Part.Point(App.Vector(x, y, 0)))
    doc.recompute()
    ctx.select(pts)
    ctx.run("SD_SketchPattern")
    ctx.pick(ctx.box("Features"), hole)
    ctx.iso()


def table_pattern(ctx):
    doc, part, v, hole = _plate_with_hole(ctx)
    ctx.select(hole)
    p = ctx.run("SD_TablePattern")
    for row, (x, y) in enumerate(((20, 0), (40, 24))):
        p.table.item(row, 0).setText(str(x))
        ctx.pump(0.2)
        p.table.item(row, 1).setText(str(y))
        ctx.pump(0.6)
    ctx.iso()


def fill_pattern(ctx):
    doc, part, v = _plate(ctx, t=3)
    ctx.select(_top(ctx, v) if False else (v, ctx.face(v, (0, 0, 3), UP)))
    p = ctx.run("SD_FillPattern")
    p.seed.setCurrentText("Circle")
    ctx.pump(0.4)
    ctx.set_value(p.sp, 8)
    ctx.set_value(p.size, 3, 1.2)
    ctx.iso()


def variable_pattern(ctx):
    import Sketcher

    doc, part, f = ctx.plate()
    hs = ctx.circle(ctx.sketch(part, at=(0, 0, 8)), -20, 0, 4)
    hs.addConstraint(Sketcher.Constraint("DistanceX", 0, 3, -1, 1, 20))
    hs.renameConstraint(0, "Position")
    hs.addConstraint(Sketcher.Constraint("Radius", 0, 4))
    hs.renameConstraint(1, "Size")
    doc.recompute()
    hole = ctx.extrude(part, hs, 8, mode="Cut", Reverse=True)
    ctx.select(hole)
    p = ctx.run("SD_VariablePattern", 1.2)
    for _i in range(p.dim_pick.count()):
        if p.dim_pick.count() == 0:
            break
        idx = next((i for i in range(p.dim_pick.count())
                    if p.dim_pick.itemText(i).split(" (")[0] in ("Position", "Size")), None)
        if idx is None:
            break
        p.dim_pick.setCurrentIndex(idx)
        p._add_dim()
        ctx.pump(0.3)
    heads = [p.table.horizontalHeaderItem(c).text() for c in range(p.table.columnCount())]
    for _r in range(3):
        p._add_row()
        ctx.pump(0.3)
    values = {"Position": ("8", "-4", "-16"), "Size": ("3", "2.5", "2")}
    for c, h in enumerate(heads):
        for r, val in enumerate(values.get(h.split(" (")[0], ())):
            if r < p.table.rowCount() and h.split(" (")[0] in values:
                p.table.item(r, c).setText(val)
                ctx.pump(0.2)
    ctx.pump(1.2)
    ctx.iso()


# -- bodies -----------------------------------------------------------------------------

def combine(ctx):
    doc, part, views = _two_boxes(ctx)
    ctx.select(*views)
    ctx.run("SD_Combine", 1.2)
    ctx.iso()


def split(ctx):
    doc, part, v = _plate(ctx)
    ctx.select(v, ctx.plane(part, "Right Plane"))
    ctx.run("SD_Split", 1.2)
    ctx.iso()


def delete_body(ctx):
    doc, part, views = _two_boxes(ctx, overlap=False)
    ctx.select(views[1])
    ctx.run("SD_DeleteBody")
    ctx.iso()


def move_copy(ctx):
    doc, part, v = _plate(ctx)
    ctx.select(v)
    p = ctx.run("SD_MoveCopy")
    for name, value in (("dx", 20), ("dz", 15)):
        f = getattr(p, name, None)
        if f is not None:
            ctx.set_value(f, value)
    ctx.iso()


def flex(ctx):
    doc, part, v = _plate(ctx, w=80, d=16, t=6)
    ctx.select(v)
    ctx.run("SD_Flex", 1.5)
    ctx.iso()


def deform(ctx):
    doc, part, v = _plate(ctx, t=4)
    ctx.select((v, ctx.face(v, (0, 0, 4), UP), (5, 0, 4)))
    p = ctx.run("SD_Deform", 1.2)
    if not ctx.box("Point").items if _has_box(ctx, "Point") else False:
        ctx.pick(ctx.box("Point"), v, ctx.face(v, (0, 0, 4), UP), (5, 0, 4))
    ctx.set_value(p.dist, 6)
    ctx.set_value(p.radius, 15, 1.5)
    ctx.iso()


def indent(ctx):
    doc, part, f = ctx.plate(t=4)
    ctx.boss(part, 0, 0, 8, 10, -6, merge=False)
    views = ctx.bodies(part)
    ctx.select(*views)
    ctx.run("SD_Indent", 1.5)
    ctx.camera((-1, -1.2, 0.6))


def freeform(ctx):
    doc, part, v = _plate(ctx, t=4)
    top = ctx.face(v, (0, 0, 4), UP)
    ctx.select((v, top))
    p = ctx.run("SD_Freeform")
    ctx.pick(ctx.box("Points"), v, top, (5, 0, 4))
    try:
        p.height.setValue(6.0)
    except Exception:
        pass
    ctx.pump(1.2)
    ctx.iso()


def scale(ctx):
    doc, part, v = _plate(ctx)
    ctx.select(v)
    p = ctx.run("SD_Scale")
    for name in ("factor", "f", "scale"):
        if hasattr(p, name):
            ctx.set_value(getattr(p, name), 1.5, 1.2)
            break
    ctx.iso()


def move_face(ctx):
    doc, part, v = _plate(ctx)
    ctx.select((v, ctx.face(v, *RIGHT_FACE)))
    p = ctx.run("SD_MoveFace")
    ctx.set_value(p.dist, 8)
    ctx.iso()


def delete_face(ctx):
    doc, part, v, boss = _plate_with_boss(ctx)
    v = ctx.bodies(part)[0]
    ctx.select((v, ctx.face(v, (20, 0, 13), (1, 0, 0))), (v, ctx.face(v, (15, 0, 18), UP)))
    p = ctx.run("SD_DeleteFace")
    p.dtype.setCurrentText("Delete and Patch")
    ctx.pump(1.0)
    ctx.iso()


def replace_face(ctx):
    doc, part, v = _plate(ctx)
    _arch(ctx, part, 8)
    v = [b for b in ctx.bodies(part) if getattr(b, "Kind", "solid") == "solid"][0]
    sv = ctx.bodies(part, "surface")[0]
    ctx.select((v, ctx.face(v, TOP, UP)))
    ctx.run("SD_ReplaceFace")
    ctx.pick(ctx.box("Replacement"), sv, "Face1")
    ctx.iso()


# -- surfaces --------------------------------------------------------------------------

def extruded_surface(ctx):
    doc, part = ctx.new_part()
    sk = ctx.sketch(part)
    ctx.arc(sk, 0, 0, 15, 0, 180)
    doc.recompute()
    ctx.select(sk)
    p = ctx.run("SD_ExtrudedSurface")
    ctx.set_value(p.d1.depth, 20)
    ctx.iso()


def revolved_surface(ctx):
    doc, part = ctx.new_part()
    sk = ctx.sketch(part, "Front Plane")
    ctx.line(sk, (10, 0), (16, 20))
    ctx.line(sk, (0, -5), (0, 25), construction=True)
    doc.recompute()
    ctx.select(sk)
    ctx.run("SD_RevolvedSurface", 1.2)
    ctx.iso()


def swept_surface(ctx):
    sweep(ctx, "SD_SweptSurface", open_profile=True)


def lofted_surface(ctx):
    loft(ctx, "SD_LoftedSurface", open_profiles=True)


def boundary_surface(ctx):
    boundary(ctx, "SD_BoundarySurface", open_profiles=True)


def _flat_surface(ctx, hole=False, x0=-20, x1=20, z=10, doc_part=None):
    doc, part = doc_part or ctx.new_part()
    sk = ctx.sketch(part, at=(0, 0, z))
    ctx.rect(sk, x0, -15, x1, 15)
    if hole:
        ctx.circle(sk, (x0 + x1) / 2, 0, 6)
    doc.recompute()
    from freecad.SolidDesign.app import surfaces

    surfaces.create_planar(doc, part, Sketch=sk)
    doc.recompute()
    return doc, part, ctx.bodies(part, "surface")[-1]


def planar_surface(ctx):
    doc, part = ctx.new_part()
    sk = ctx.sketch(part)
    ctx.rect(sk, -20, -15, 20, 15)
    ctx.circle(sk, 0, 0, 6)
    doc.recompute()
    ctx.select(sk)
    ctx.run("SD_PlanarSurface")
    ctx.iso()


def offset_surface(ctx):
    doc, part, v = _plate(ctx)
    ctx.select(_top(ctx, v))
    p = ctx.run("SD_OffsetSurface")
    ctx.set_value(p.dist, 10)
    ctx.iso()


def filled_surface(ctx):
    doc, part, v = _plate(ctx)
    ctx.select()
    ctx.run("SD_FilledSurface")
    box = ctx.box("Patch Boundary") if _has_box(ctx, "Patch Boundary") else ctx.box("Edges")
    for a, b in (((-30, -20, 8), (30, -20, 8)), ((30, -20, 8), (30, 20, 8)),
                 ((30, 20, 8), (-30, 20, 8)), ((-30, 20, 8), (-30, -20, 8))):
        ctx.pick(box, v, ctx.edge(v, a, b))
    ctx.iso()


def extend_surface(ctx):
    doc, part, sv = _flat_surface(ctx)
    ctx.select((sv, ctx.edge(sv, (20, -15, 10), (20, 15, 10))))
    p = ctx.run("SD_ExtendSurface")
    ctx.set_value(p.dist, 10)
    ctx.iso()


def trim_surface(ctx):
    doc, part, sv = _flat_surface(ctx)
    ctx.select(ctx.plane(part, "Right Plane"))
    ctx.run("SD_TrimSurface")
    ctx.pick(ctx.box("Pieces"), sv, "Face1", (10, 0, 10))
    ctx.iso()


def untrim_surface(ctx):
    doc, part, sv = _flat_surface(ctx, hole=True)
    ctx.select((sv, "Face1"))
    ctx.run("SD_UntrimSurface", 1.2)
    ctx.iso()


def knit(ctx):
    doc, part, a = _flat_surface(ctx, x0=-20, x1=0)
    doc, part, b = _flat_surface(ctx, x0=0, x1=20, z=10, doc_part=(doc, part))
    ctx.select(*ctx.bodies(part, "surface"))
    ctx.run("SD_Knit", 1.2)
    ctx.iso()


def ruled_surface(ctx):
    doc, part, v = _plate(ctx)
    ctx.select((v, ctx.edge(v, *FRONT_EDGE)), (v, ctx.edge(v, *RIGHT_EDGE)))
    ctx.run("SD_RuledSurface", 1.2)
    ctx.iso()


def radiate_surface(ctx):
    doc, part, v = _plate(ctx)
    ctx.select((v, ctx.edge(v, (-30, -20, 0), (30, -20, 0))))
    ctx.run("SD_RadiateSurface", 1.0)
    ctx.pick(ctx.box("Reference Plane"), ctx.plane(part, "Top Plane"), "", None, 1.2)
    ctx.iso()


def mid_surface(ctx):
    doc, part, v = _plate(ctx, t=3)
    ctx.select(v)
    ctx.run("SD_MidSurface", 1.2)
    ctx.iso()


def surface_flatten(ctx):
    doc, part, v, top = _shaft(ctx, r=8, h=20)
    ctx.select((v, ctx.face(v, (8, 0, 10), (1, 0, 0))))
    ctx.run("SD_SurfaceFlatten", 1.5)
    ctx.iso()


def thicken(ctx):
    doc, part, sv = _flat_surface(ctx)
    ctx.select(sv)
    p = ctx.run("SD_Thicken")
    ctx.set_value(p.t, 4)
    ctx.iso()


def _arch(ctx, part, top):
    """A surface arching across the plate, from below its top to above it."""
    s = ctx.sketch(part, "Front Plane")
    ctx.arc(s, 0, top - 52, 50, 50, 130)
    part.Document.recompute()
    return ctx.extrude(part, s, 60, mode="Surface", merge=False, EndCondition="Mid Plane")


def surface_cut(ctx):
    doc, part, v = _plate(ctx, t=16)
    _arch(ctx, part, 16)
    solid = [b for b in ctx.bodies(part) if getattr(b, "Kind", "solid") == "solid"][0]
    sv = ctx.bodies(part, "surface")[0]
    ctx.select(solid, sv)
    ctx.run("SD_SurfaceCut", 1.2)
    ctx.iso()


def split_line(ctx):
    doc, part, v = _plate(ctx)
    s = ctx.sketch(part, at=(0, 0, 8))
    ctx.line(s, (-30, -8), (30, 12))
    doc.recompute()
    ctx.select(s, _top(ctx, v))
    ctx.run("SD_SplitLine")
    ctx.iso()


# -- reference geometry and curves --------------------------------------------------------

def plane(ctx):
    doc, part, v = _plate(ctx)
    ctx.select(_top(ctx, v))
    p = ctx.run("SD_Plane")
    if hasattr(p, "dist"):
        ctx.set_value(p.dist, 15)
    ctx.iso()


def axis(ctx):
    doc, part, v, boss = _plate_with_boss(ctx)
    v = ctx.bodies(part)[0]
    ctx.select((v, ctx.face(v, (20, 0, 13), (1, 0, 0))))
    ctx.run("SD_Axis")
    ctx.iso()


def point(ctx):
    doc, part, v, boss = _plate_with_boss(ctx)
    v = ctx.bodies(part)[0]
    top = [("Edge%d" % i) for i, e in enumerate(v.Shape.Edges, 1)
           if hasattr(e.Curve, "Radius") and abs(e.BoundBox.ZMin - 18) < 1e-6][0]
    ctx.select((v, top))
    ctx.run("SD_Point")
    ctx.iso()


def coordinate_system(ctx):
    doc, part, v = _plate(ctx)
    ctx.select((v, "Vertex1"))
    ctx.run("SD_CoordinateSystem")
    ctx.iso()


def helix(ctx):
    doc, part = ctx.new_part()
    sk = ctx.circle(ctx.sketch(part), 0, 0, 10)
    doc.recompute()
    ctx.select(sk)
    ctx.run("SD_Helix", 1.2)
    ctx.iso()


def bounding_box(ctx):
    doc, part, v, boss = _plate_with_boss(ctx)
    ctx.select()
    ctx.run("SD_BoundingBox")
    ctx.iso()


def center_of_mass(ctx):
    doc, part, v, boss = _plate_with_boss(ctx)
    ctx.select()
    ctx.run("SD_CenterOfMass")
    ctx.iso()


def projected_curve(ctx):
    doc, part = ctx.new_part()
    cy = ctx.circle(ctx.sketch(part), 0, 0, 15)
    doc.recompute()
    ctx.extrude(part, cy, 30)
    v = ctx.bodies(part)[0]
    s = ctx.sketch(part, "Front Plane", at=(0, 0, 30))
    ctx.arc(s, 0, 15, 8, 200, 340)
    doc.recompute()
    ctx.select(s, (v, ctx.face(v, (0, -15, 15), (0, -1, 0))))
    p = ctx.run("SD_ProjectedCurve", 1.2)
    if "Reverse" in p.error.value():
        p.set_prop("ReverseDirection", not p.obj.ReverseDirection)
        p.load()
        ctx.pump(1.2)
    ctx.iso()


def composite_curve(ctx):
    doc, part, v = _plate(ctx)
    ctx.select((v, ctx.edge(v, *FRONT_EDGE)), (v, ctx.edge(v, *RIGHT_EDGE)))
    ctx.run("SD_CompositeCurve")
    ctx.iso()


def curve_xyz(ctx):
    doc, part = ctx.new_part()
    ctx.select()
    p = ctx.run("SD_CurveXYZ")
    table = p.points.table
    rows = ((0, 0, 0), (20, 10, 5), (40, 0, 15), (60, 15, 20))
    for r, xyz in enumerate(rows):
        for c, val in enumerate(xyz):
            table.item(r, c).setText(str(val))
            ctx.pump(0.15)
    ctx.pump(1.0)
    ctx.iso()


def curve_points(ctx):
    doc, part, v = _plate(ctx)
    verts = []
    for pt in ((-30, -20, 8), (30, -20, 8), (30, 20, 8)):
        for i, vx in enumerate(v.Shape.Vertexes, 1):
            if (vx.Point - _vec(pt)).Length < 1e-6:
                verts.append((v, "Vertex%d" % i))
    ctx.select(*verts)
    ctx.run("SD_CurvePoints", 1.2)
    ctx.iso()


def _vec(p):
    import FreeCAD as App

    return App.Vector(*p)


# -- evaluate, keyboard and view tools ------------------------------------------------------

def whats_wrong(ctx):
    from . import scenes

    return scenes.whats_wrong_dialog(ctx)


def command_search(ctx):
    from . import scenes

    return scenes.command_search_box(ctx)


def command_line(ctx):
    from . import scenes

    return scenes.command_line_bar(ctx)


def context_toolbar(ctx):
    from . import scenes

    return scenes.context_toolbar_shot(ctx)


def reference_labels(ctx):
    from . import scenes

    return scenes.reference_labels_shot(ctx)


RECIPES = {
    "SD_Part": part, "SD_Sketch": sketch,
    "SD_Extrude": extrude, "SD_Revolve": revolve, "SD_Sweep": sweep, "SD_Loft": loft,
    "SD_Boundary": boundary, "SD_Fillet": fillet, "SD_Chamfer": chamfer, "SD_Rib": rib,
    "SD_Wrap": wrap, "SD_Draft": draft, "SD_Shell": shell, "SD_Dome": dome,
    "SD_Intersect": intersect, "SD_HoleWizard": hole_wizard, "SD_Thread": thread,
    "SD_CosmeticThread": cosmetic_thread, "SD_MountingBoss": mounting_boss,
    "SD_SnapHook": snap_hook, "SD_LipGroove": lip_groove, "SD_Vent": vent,
    "SD_Mirror": mirror, "SD_LinearPattern": linear_pattern,
    "SD_CircularPattern": circular_pattern, "SD_CurvePattern": curve_pattern,
    "SD_SketchPattern": sketch_pattern, "SD_TablePattern": table_pattern,
    "SD_FillPattern": fill_pattern, "SD_VariablePattern": variable_pattern,
    "SD_Combine": combine, "SD_Split": split, "SD_DeleteBody": delete_body,
    "SD_MoveCopy": move_copy, "SD_Flex": flex, "SD_Deform": deform, "SD_Indent": indent,
    "SD_Freeform": freeform, "SD_Scale": scale, "SD_MoveFace": move_face,
    "SD_DeleteFace": delete_face, "SD_ReplaceFace": replace_face,
    "SD_Plane": plane, "SD_Axis": axis, "SD_Point": point,
    "SD_CoordinateSystem": coordinate_system, "SD_BoundingBox": bounding_box,
    "SD_CenterOfMass": center_of_mass,
    "SD_ExtrudedSurface": extruded_surface, "SD_RevolvedSurface": revolved_surface,
    "SD_SweptSurface": swept_surface, "SD_LoftedSurface": lofted_surface,
    "SD_BoundarySurface": boundary_surface, "SD_PlanarSurface": planar_surface,
    "SD_OffsetSurface": offset_surface, "SD_FilledSurface": filled_surface,
    "SD_ExtendSurface": extend_surface, "SD_TrimSurface": trim_surface,
    "SD_UntrimSurface": untrim_surface, "SD_Knit": knit, "SD_RuledSurface": ruled_surface,
    "SD_RadiateSurface": radiate_surface, "SD_MidSurface": mid_surface,
    "SD_SurfaceFlatten": surface_flatten, "SD_Thicken": thicken,
    "SD_SurfaceCut": surface_cut, "SD_SplitLine": split_line,
    "SD_ProjectedCurve": projected_curve, "SD_CompositeCurve": composite_curve,
    "SD_CurveXYZ": curve_xyz, "SD_CurvePoints": curve_points, "SD_Helix": helix,
    "SD_WhatsWrong": whats_wrong, "SD_CommandSearch": command_search,
    "SD_CommandLine": command_line, "SD_ContextToolbar": context_toolbar,
    "SD_ReferenceLabels": reference_labels,
}


def _labels() -> dict[str, str]:
    """Each command's label, from the catalog (so the shot ids follow the names)."""
    p = Path(__file__).resolve().parents[2] / "_data" / "catalog.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {c["name"]: c["label"] for c in data.get("commands", [])}


def _register() -> None:
    from ..catalog import slug

    labels = _labels()
    for command, recipe in RECIPES.items():
        label = labels.get(command)
        if label is None:
            continue

        def fn(ctx, command=command, recipe=recipe):
            image = recipe(ctx)
            if image is not None:
                return image
            p = ctx.panel()
            if p is None:
                raise RuntimeError(f"{command} opened no panel")
            ctx.pump(0.8)
            ctx.record = record_panel(command, p)
            return ctx.window()

        shot(tool_shot_id(slug(label)), f"The {label} panel, open on a sample part",
             tool=command)(fn)


_register()
