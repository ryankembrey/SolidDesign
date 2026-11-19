# SPDX-License-Identifier: LGPL-2.1-or-later
"""Extrude: every option, and the multi-body cases (scope, merge, bodies to keep)."""

import json
import math
import unittest

import FreeCAD as App
import Part
import Sketcher

from freecad.SolidDesign.app import part as app_part
from freecad.SolidDesign.core import regions
from helpers import V, circle, extrude, new_doc, plane, rect, sketch, volumes

PI = math.pi


class Case(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("Ext")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def top_sketch(self, offset=0.0):
        sk = sketch(self.doc, plane(self.part, "Top Plane"),
                    attach_offset=App.Placement(V(0, 0, offset), App.Rotation()))
        return sk

    def box(self, x0=0, y0=0, x1=20, y1=10, depth=5, **kw):
        sk = self.top_sketch()
        rect(sk, x0, y0, x1, y1)
        self.doc.recompute()
        return extrude(self.doc, self.part, sk, Depth=depth, **kw)

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)

    def total(self):
        return sum(volumes(self.part).values())


class TestEndConditions(Case):
    def test_blind_reverse_mid(self):
        f = self.box(depth=5)
        self.ok(f)
        self.assertAlmostEqual(f.Shape.Volume, 1000)
        self.assertAlmostEqual(f.Shape.BoundBox.ZMax, 5)
        f.Reverse = True
        self.doc.recompute()
        self.assertAlmostEqual(f.Shape.BoundBox.ZMin, -5)
        f.EndCondition = "Mid Plane"
        f.Depth = 8
        self.doc.recompute()
        self.assertAlmostEqual(f.Shape.BoundBox.ZMin, -4)
        self.assertAlmostEqual(f.Shape.BoundBox.ZMax, 4)

    def test_direction_of_extrusion(self):
        import Part
        f = self.box(depth=10)
        ln = sketch(self.doc, plane(self.part, "Front Plane"))
        ln.addGeometry(Part.LineSegment(V(0, 0, 0), V(10, 10, 0)))
        self.doc.recompute()
        f.DirectionOfExtrusion = (ln, ["Edge1"])
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(f.Shape.Volume, 200 * 10 * math.sqrt(0.5), 3)
        self.assertAlmostEqual(f.Shape.BoundBox.XMax, 20 + 10 * math.sqrt(0.5), 4)
        f.Draft = True
        self.doc.recompute()
        self.assertIn("Draft works with the sketch's normal", f.ErrorMessage)

    def test_direction2(self):
        f = self.box(depth=5, Direction2=True, Depth2=2)
        self.ok(f)
        self.assertAlmostEqual(f.Shape.BoundBox.ZMin, -2)
        self.assertAlmostEqual(f.Shape.Volume, 1400)
        self.assertEqual(len(f.Shape.Solids), 1)
        self.assertEqual(len(f.Shape.Faces), 6)     # one clean solid, no seam faces

    def test_cut_through_all_both_and_flip(self):
        self.box(depth=5)
        sk = self.top_sketch(offset=2.5)
        circle(sk, 10, 5, 2)
        self.doc.recompute()
        c = extrude(self.doc, self.part, sk, "Cut", EndCondition="Through All - Both")
        self.ok(c)
        self.assertAlmostEqual(self.total(), 1000 - PI * 4 * 5, 4)
        self.assertEqual(c.Label, "Cut-Extrude1")
        c.FlipSideToCut = True
        self.doc.recompute()
        self.assertAlmostEqual(self.total(), PI * 4 * 5, 4)

    def test_up_to_vertex(self):
        self.box(depth=5)
        sk = self.top_sketch()
        rect(sk, 30, 0, 35, 5)
        self.doc.recompute()
        f = extrude(self.doc, self.part, sk, EndCondition="Up To Vertex")
        base = self.part.Tip.BaseFeature
        v = [i for i, x in enumerate(base.Shape.Vertexes, 1) if abs(x.Point.z - 5) < 1e-9][0]
        from freecad.SolidDesign.app import refs
        refs.set_ref(f, "UpToVertex", base, "Vertex%d" % v)
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(f.Shape.BoundBox.ZMax, 5)

    def test_up_to_surface_slanted_and_offset(self):
        from freecad.SolidDesign.app import refs
        # A wedge whose top face slopes; extrude a small boss up to it from below.
        sk = sketch(self.doc, plane(self.part, "Front Plane"))
        pts = [V(0, 0, 0), V(20, 0, 0), V(20, 10, 0), V(0, 5, 0)]
        for i in range(4):
            sk.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]))
        self.doc.recompute()
        w = extrude(self.doc, self.part, sk, Depth=10, Reverse=True)   # Front normal is -Y
        self.ok(w)
        self.assertAlmostEqual(w.Shape.BoundBox.YMax, 10)
        slanted = [i for i, f in enumerate(w.Shape.Faces, 1)
                   if abs(f.normalAt(0, 0).z) > 0.1 and abs(f.normalAt(0, 0).x) > 0.1][0]
        sk2 = self.top_sketch(offset=20)
        rect(sk2, 8, 2, 12, 6)
        self.doc.recompute()
        f = extrude(self.doc, self.part, sk2, "Cut", EndCondition="Up To Surface", Reverse=True)
        refs.set_ref(f, "UpToFace", w, "Face%d" % slanted)
        self.doc.recompute()
        # Nothing to cut above the wedge: a cut that stops at the slanted top touches
        # nothing, so it says so (and passes the bodies through).
        self.assertIn("doesn't touch", f.ErrorMessage)
        f.Mode = "Add"
        self.doc.recompute()
        self.ok(f)
        # Boss from z=20 down to the slope: slope z = 5 + x/4, so top of wedge at x=10 is 7.5
        boss = 4 * 4 * (20 - 7.5)
        self.assertAlmostEqual(self.total(), 10 * (5 + 10) / 2 * 20 + boss, 3)
        f.EndCondition = "Offset From Surface"
        f.Offset = 1
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(self.total(), 10 * (5 + 10) / 2 * 20 + boss - 16 * 1 / math.cos(math.atan(0.25)) * 1, 1)

    def test_up_to_next(self):
        self.box(depth=5)                            # plate at z 0..5
        sk = self.top_sketch(offset=-20)
        rect(sk, 2, 2, 6, 6)
        self.doc.recompute()
        f = extrude(self.doc, self.part, sk, EndCondition="Up To Next")
        self.ok(f)
        self.assertAlmostEqual(self.total(), 1000 + 16 * 20, 4)
        self.assertEqual(len(self.part.BodyIds), 1)  # merged into the plate
        # Cut Up To Next from the top: only the first plate, not a second one below.
        sk2 = self.top_sketch(offset=-40)
        rect(sk2, 0, 0, 20, 10)
        self.doc.recompute()
        extrude(self.doc, self.part, sk2, Depth=2, MergeResult=False)
        sk3 = self.top_sketch(offset=5)
        circle(sk3, 15, 5, 1)
        self.doc.recompute()
        c = extrude(self.doc, self.part, sk3, "Cut", EndCondition="Up To Next", Reverse=True)
        self.ok(c)
        vols = sorted(volumes(self.part).values())
        self.assertAlmostEqual(vols[0], 400.0)           # lower plate untouched
        self.assertAlmostEqual(vols[1], 1000 + 320 - PI * 5, 4)

    def test_up_to_body(self):
        a = self.box(0, 0, 10, 10, depth=5)
        b = self.box(0, 0, 10, 10, depth=2, MergeResult=False)
        # Move body B up: its own sketch offset.
        b.Sketch.AttachmentOffset = App.Placement(V(0, 0, 20), App.Rotation())
        a.Depth = 5
        self.doc.recompute()
        ids = list(self.part.BodyIds)
        self.assertEqual(len(ids), 2)
        sk = self.top_sketch(offset=5)
        circle(sk, 5, 5, 1)
        self.doc.recompute()
        f = extrude(self.doc, self.part, sk, EndCondition="Up To Body", UpToBody=ids[1],
                    MergeResult=False)
        self.ok(f)
        new = [i for i in self.part.BodyIds if i not in ids][0]
        bb = app_part.tip_bodies(self.part).get(new).shape.BoundBox
        self.assertAlmostEqual(bb.ZMin, 5)
        self.assertAlmostEqual(bb.ZMax, 20)

    def test_from_offset_and_vertex(self):
        sk = self.top_sketch()
        rect(sk, 0, 0, 10, 10)
        self.doc.recompute()
        f = extrude(self.doc, self.part, sk, Depth=5, From="Offset", FromOffset=3)
        self.ok(f)
        self.assertAlmostEqual(f.Shape.BoundBox.ZMin, 3)
        self.assertAlmostEqual(f.Shape.BoundBox.ZMax, 8)


class TestBodies(Case):
    def test_merge_keeps_first_id(self):
        self.box(0, 0, 10, 10, depth=5, MergeResult=False)
        self.box(20, 0, 30, 10, depth=5, MergeResult=False)
        ids = list(self.part.BodyIds)
        self.assertEqual(len(ids), 2)
        # A bridge touching both: they merge, keeping the first body's ID.
        sk = self.top_sketch()
        rect(sk, 5, 2, 25, 8)
        self.doc.recompute()
        f = extrude(self.doc, self.part, sk, Depth=5)
        self.ok(f)
        self.assertEqual(list(self.part.BodyIds), [ids[0]])
        # Merge result off: always a new body.
        f.MergeResult = False
        self.doc.recompute()
        self.assertEqual(len(self.part.BodyIds), 3)

    def test_two_regions_merge_separately(self):
        a = self.box(0, 0, 10, 10, depth=5, MergeResult=False)
        sk = self.top_sketch()
        rect(sk, 5, 2, 15, 8)
        rect(sk, 40, 0, 45, 5)
        self.doc.recompute()
        f = extrude(self.doc, self.part, sk, Depth=5)
        self.ok(f)
        self.assertEqual(len(self.part.BodyIds), 2)  # one merged, one new
        self.assertIn(self.part.BodyIds[0], (a.BodyIds[0],))

    def test_scope_selected(self):
        self.box(0, 0, 10, 10, depth=5, MergeResult=False)
        self.box(20, 0, 30, 10, depth=5, MergeResult=False)
        ida, idb = self.part.BodyIds
        sk = self.top_sketch()
        rect(sk, -5, 4, 35, 6)
        self.doc.recompute()
        c = extrude(self.doc, self.part, sk, "Cut", EndCondition="Through All - Both",
                    FeatureScope="Selected bodies", AutoSelect=False, ScopeBodies=[idb])
        self.ok(c)
        vols = volumes(self.part)
        self.assertAlmostEqual(vols[ida], 500.0)
        self.assertEqual(len(vols), 3)                  # B was split in two
        self.assertAlmostEqual(sum(v for k, v in vols.items() if k != ida), 400.0)

    def test_bodies_to_keep(self):
        self.box(0, 0, 30, 10, depth=5)
        bid = self.part.BodyIds[0]
        sk = self.top_sketch()
        rect(sk, 9, -5, 11, 15)
        self.doc.recompute()
        c = extrude(self.doc, self.part, sk, "Cut", EndCondition="Through All - Both")
        self.ok(c)
        pieces = json.loads(c.Pieces)
        self.assertEqual(len(pieces), 2)
        big = [p for p in pieces if p["id"] == bid][0]
        self.assertAlmostEqual(big["size"], 19 * 10 * 5)     # largest piece keeps the ID
        small = [p["id"] for p in pieces if p["id"] != bid][0]
        c.BodiesToKeep = "Selected bodies"
        c.KeepBodies = [small]
        self.doc.recompute()
        self.assertEqual(list(self.part.BodyIds), [small])
        # A recompute after an upstream change keeps the same piece.
        self.part.Group[self.part.Group.index(c) - 2]  # noqa (just to touch structure)
        first = [f for f in self.part.Group if hasattr(f, "Depth")][0]
        first.Depth = 6
        self.doc.recompute()
        self.assertEqual(list(self.part.BodyIds), [small])
        self.assertAlmostEqual(self.total(), 9 * 10 * 6)


class TestProfile(Case):
    def test_selected_contours(self):
        sk = self.top_sketch()
        circle(sk, 0, 0, 5)
        circle(sk, 6, 0, 5)
        self.doc.recompute()
        f = extrude(self.doc, self.part, sk, Depth=1)
        self.assertIn("Selected Contours", f.ErrorMessage)
        regs = regions.regions(sk)
        lens = [r for r in regs if abs(r.face.CenterOfMass.x - 3) < 1e-6][0]
        f.Contours = [lens.key()]
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(f.Shape.Volume, lens.face.Area)

    def test_nested_hole_and_open_sketch(self):
        sk = self.top_sketch()
        rect(sk, 0, 0, 10, 10)
        circle(sk, 5, 5, 2)
        self.doc.recompute()
        f = extrude(self.doc, self.part, sk, Depth=1)
        self.assertAlmostEqual(f.Shape.Volume, 100 - PI * 4)
        sk2 = self.top_sketch()
        sk2.addGeometry(Part.LineSegment(V(20, 0, 0), V(30, 0, 0)))
        self.doc.recompute()
        g = extrude(self.doc, self.part, sk2, Depth=1)
        # An open sketch makes a surface body (spec 3.4); a cut with it can't.
        self.ok(g)
        self.assertIn("surface", list(self.part.BodyKinds))
        self.assertEqual(app_part.folder(self.part, "surface").Label, "Surface Bodies (1)")
        g.Mode = "Cut"
        self.doc.recompute()
        self.assertIn("closed sketch", g.ErrorMessage)

    def test_no_sketch(self):
        from freecad.SolidDesign.app import extrude as app_extrude
        f = app_extrude.create(self.doc, self.part, "Add", None)
        self.doc.recompute()
        self.assertEqual(f.ErrorMessage, "Pick a sketch to extrude.")


class TestDraftThin(Case):
    def test_draft(self):
        f = self.box(0, 0, 10, 10, depth=5, Draft=True, DraftAngle=10)
        self.ok(f)
        d = 5 * math.tan(math.radians(10))
        top = 10 - 2 * d
        frustum = 5 / 3.0 * (100 + top * top + 10 * top)
        self.assertAlmostEqual(f.Shape.Volume, frustum, 4)
        f.DraftOutward = True
        self.doc.recompute()
        top = 10 + 2 * d
        self.assertAlmostEqual(f.Shape.Volume, 5 / 3.0 * (100 + top * top + 10 * top), 4)

    def test_draft_with_hole(self):
        """The holes of a drafted profile follow the draft (they grow as the
        outside shrinks), instead of failing."""
        sk = self.top_sketch()
        rect(sk, 0, 0, 20, 20)
        circle(sk, 10, 10, 3)
        self.doc.recompute()
        f = extrude(self.doc, self.part, sk, Depth=5, Draft=True, DraftAngle=10)
        self.ok(f)
        d = 5 * math.tan(math.radians(10))
        top = 20 - 2 * d
        block = 5 / 3.0 * (400 + top * top + 20 * top)
        r0, r1 = 3.0, 3.0 + d
        cone = PI * 5 / 3.0 * (r0 * r0 + r0 * r1 + r1 * r1)
        self.assertAlmostEqual(f.Shape.Volume, block - cone, 3)

    def test_thin_closed(self):
        f = self.box(0, 0, 10, 10, depth=5, Thin=True, ThinThickness=1)
        self.ok(f)
        self.assertAlmostEqual(f.Shape.Volume, (12 * 12 - 100) * 5, 4)   # outward, sharp corners
        f.ThinType = "Mid-Plane"
        self.doc.recompute()
        self.assertAlmostEqual(f.Shape.Volume, (11 * 11 - 9 * 9) * 5, 4)
        f.CapEnds = True
        f.CapThickness = 1
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(f.Shape.Volume, 11 * 11 * 5 - 9 * 9 * 3, 4)

    def test_thin_open(self):
        sk = self.top_sketch()
        sk.addGeometry(Part.LineSegment(V(0, 0, 0), V(10, 0, 0)))
        sk.addGeometry(Part.LineSegment(V(10, 0, 0), V(10, 10, 0)))
        sk.addConstraint(Sketcher.Constraint("Coincident", 0, 2, 1, 1))
        self.doc.recompute()
        f = extrude(self.doc, self.part, sk, Depth=2, Thin=True, ThinType="Mid-Plane",
                    ThinThickness=2)
        self.ok(f)
        self.assertEqual(len(f.Shape.Solids), 1)
        self.assertAlmostEqual(f.Shape.Volume, (10 * 2 + 10 * 2) * 2, 4)
