# SPDX-License-Identifier: LGPL-2.1-or-later
"""Hole Wizard (basic): types, sizes, end conditions, positions, patterning."""

import math
import unittest

import FreeCAD as App
import Part

from freecad.SolidDesign.app import hole as app_hole
from freecad.SolidDesign.app import pattern
from freecad.SolidDesign.core.features import hole as core
from helpers import V, extrude, new_doc, plane, rect, sketch, volumes

PI = math.pi


class TestHole(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("Hole")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 60, 30)
        self.doc.recompute()
        self.plate = extrude(self.doc, self.part, sk, Depth=20)
        top = sketch(self.doc, plane(self.part, "Top Plane"),
                     attach_offset=App.Placement(V(0, 0, 20), App.Rotation()))
        top.addGeometry(Part.Point(V(15, 15, 0)))
        top.addGeometry(Part.Point(V(45, 15, 0)))
        self.doc.recompute()
        self.pts = top

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def total(self):
        return sum(volumes(self.part).values())

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)

    def test_clearance_through_all(self):
        h = app_hole.create(self.doc, self.part, self.pts, HoleType="Hole", Size="M6",
                            EndCondition="Through All")
        self.doc.recompute()
        self.ok(h)
        self.assertEqual(h.Label, "M6 Clearance Hole1")
        self.assertAlmostEqual(self.total(), 36000 - 2 * PI * 3.3 ** 2 * 20, 3)

    def test_counterbore_blind_with_tip(self):
        h = app_hole.create(self.doc, self.part, self.pts, HoleType="Counterbore", Size="M8",
                            Depth=15)
        self.doc.recompute()
        self.ok(h)
        self.assertEqual(h.Label, "CBORE for M8 Socket Head Cap Screw1")
        r, cr, ch = 4.5, 7.5, 8.6
        tip = PI * r * r * (r / math.tan(math.radians(59))) / 3.0
        one = PI * cr * cr * ch + PI * r * r * (15 - ch) + tip
        self.assertAlmostEqual(self.total(), 36000 - 2 * one, 2)

    def test_countersink_and_tap_and_rename(self):
        h = app_hole.create(self.doc, self.part, self.pts, HoleType="Countersink", Size="M5",
                            EndCondition="Through All")
        self.doc.recompute()
        self.ok(h)
        self.assertTrue(h.Label.startswith("CSK for M5"))
        h.HoleType = "Straight Tap"
        self.doc.recompute()
        self.ok(h)
        self.assertTrue(h.Label.startswith("M5x0.8 Tapped Hole"))
        self.assertAlmostEqual(self.total(), 36000 - 2 * PI * 2.1 ** 2 * 20, 3)

    def test_errors_and_reverse(self):
        h = app_hole.create(self.doc, self.part, None)
        self.doc.recompute()
        self.assertIn("Pick where the holes go", h.ErrorMessage)
        h.Sketch = self.pts
        h.Reverse = True                  # pointing away from the plate
        self.doc.recompute()
        self.assertIn("don't touch", h.ErrorMessage)
        h.Reverse = False
        h.HoleType = "Counterbore"
        h.Depth = 5
        self.doc.recompute()
        self.assertIn("counterbore depth", h.ErrorMessage)

    def test_circle_centres_and_pattern(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"),
                    attach_offset=App.Placement(V(0, 0, 20), App.Rotation()))
        sk.addGeometry(Part.Circle(V(10, 10, 0), V(0, 0, 1), 2))
        self.doc.recompute()
        h = app_hole.create(self.doc, self.part, sk, HoleType="Hole", Size="M4",
                            EndCondition="Through All")
        self.doc.recompute()
        self.ok(h)
        lp = pattern.create_linear(self.doc, self.part, Features=[h], Spacing=10, Instances=3)
        lp.Direction1Ref = (plane(self.part, "X Axis"), [])
        self.doc.recompute()
        self.assertEqual(lp.ErrorMessage, "")
        self.assertAlmostEqual(self.total(), 36000 - 3 * PI * 2.25 ** 2 * 20, 3)

    def test_tapered_tap(self):
        h = app_hole.create(self.doc, self.part, self.pts, HoleType="Tapered Tap",
                            Size="Rc 1/4", Depth=15, TipAngle=0)
        self.doc.recompute()
        self.ok(h)
        self.assertEqual(h.Label, "Rc 1/4 Tapered Tap1")
        D = 11.2
        d = D - 15 / 16.0
        one = PI * 15 / 12.0 * (D * D + D * d + d * d)
        self.assertAlmostEqual(self.total(), 36000 - 2 * one, 2)
        h.Standard = "ANSI Inch"
        self.assertEqual(h.Size, "3/8 NPT")             # the middle of the pipe sizes
        h.Size = "1/4 NPT"
        h.ThreadOption = "Thread Diameter"
        self.doc.recompute()
        self.ok(h)
        self.assertTrue(h.Label.startswith("1/4-18 NPT Tapered Tap"))
        major = core.taper_table("ANSI Inch", "1/4 NPT")[1]
        self.assertAlmostEqual(major, 13.6, 0)            # 1/4 NPT: about 0.54 in at the face
        h.ThreadOption = "Modelled Thread"
        self.doc.recompute()
        self.ok(h)
        self.assertIn("modelled thread isn't available", h.WarningMessage)
        h.EndCondition = "Through All"
        h.ThreadOption = "Tap Drill Diameter"
        self.doc.recompute()
        self.ok(h)

    def test_advanced(self):
        h = app_hole.create(self.doc, self.part, self.pts, HoleType="Advanced",
                            EndCondition="Through All")
        self.assertEqual(len(h.NearElements), 2)          # starts as counterbore over hole
        h.NearElements = ["Countersink|14|0|90", "Counterbore|11|4|0", "Hole|6.6|0|0"]
        h.FarElements = ["Counterbore|9|3|0"]
        self.doc.recompute()
        self.ok(h)
        self.assertEqual(h.Label, "Advanced Hole1")
        csk = PI * 1.5 / 12.0 * (14 * 14 + 14 * 11 + 11 * 11)
        one = csk + PI * 5.5 ** 2 * 4 + PI * 3.3 ** 2 * (20 - 5.5 - 3) + PI * 4.5 ** 2 * 3
        self.assertAlmostEqual(self.total(), 36000 - 2 * one, 2)
        h.NearElements = ["Hole|6.6|0|0", "Countersink|14|0|90"]
        self.doc.recompute()
        self.assertIn("countersink can't be the last", h.ErrorMessage)
        h.NearElements = ["Hole|6.6|0|0"]
        h.EndCondition = "Blind"
        self.doc.recompute()
        self.assertIn("Far side elements need", h.ErrorMessage)

    def test_table(self):
        for std in core.STANDARDS:
            for s in core.sizes(std, core.TAPERED_TAP):
                pitch, major, tap = core.taper_table(std, s)
                self.assertGreater(major, tap)
                self.assertGreater(tap, 0.75 * major)
        for s in core.SIZES:
            for t in core.TYPES:
                if t in (core.TAPERED_TAP, core.ADVANCED):
                    continue
                d, cb, csk = core.dims(t, s, "Normal")
                self.assertGreater(d, 0)
                if cb:
                    self.assertGreater(cb[0], d)
                if csk:
                    self.assertGreater(csk, d)
