# SPDX-License-Identifier: LGPL-2.1-or-later
"""Hole Wizard (full): ANSI Inch, slots, end conditions, options, custom sizing,
modelled threads."""

import math
import unittest

import FreeCAD as App
import Part

from freecad.SolidDesign.app import hole as app_hole, refs
from freecad.SolidDesign.core import threads
from freecad.SolidDesign.core.features import hole as core
from helpers import V, extrude, new_doc, plane, rect, sketch, volumes

PI = math.pi


class TestHoleFull(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("HoleF")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 60, 30)
        self.doc.recompute()
        self.plate = extrude(self.doc, self.part, sk, Depth=20)
        self.v0 = self.total()
        top = sketch(self.doc, plane(self.part, "Top Plane"),
                     attach_offset=App.Placement(V(0, 0, 20), App.Rotation()))
        top.addGeometry(Part.Point(V(15, 15, 0)))
        self.doc.recompute()
        self.pts = top

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def total(self):
        return sum(volumes(self.part).values())

    def removed(self):
        return self.v0 - self.total()

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)

    def hole(self, **props):
        h = app_hole.create(self.doc, self.part, self.pts, **props)
        self.doc.recompute()
        self.ok(h)
        return h

    def test_ansi_inch(self):
        h = self.hole(Standard="ANSI Inch", HoleType="Hole", Size="1/4",
                      EndCondition="Through All")
        self.assertEqual(h.Size, "1/4")
        d = 0.266 * 25.4
        self.assertAlmostEqual(self.removed(), PI * (d / 2) ** 2 * 20, 2)
        h.HoleType = "Straight Tap"
        self.doc.recompute()
        self.ok(h)
        self.assertIn("1/4-20", h.Label)
        tap = threads.spec(threads.UNC, "1/4-20")[2]
        self.assertAlmostEqual(self.removed(), PI * (tap / 2) ** 2 * 20, 2)
        h.HoleType = "Countersink"
        self.doc.recompute()
        self.ok(h)
        self.assertAlmostEqual(h.CskAngle.Value, 82.0, 6)

    def test_standard_switch_keeps_a_valid_size(self):
        h = self.hole(HoleType="Hole", Size="M8", EndCondition="Through All")
        h.Standard = "ANSI Inch"
        self.doc.recompute()
        self.ok(h)
        self.assertIn(h.Size, core.sizes("ANSI Inch"))

    def test_slot(self):
        h = self.hole(HoleType="Slot", Size="M6", EndCondition="Through All", SlotLength=10)
        d = 6.6
        area = PI * (d / 2) ** 2 + 10 * d
        self.assertAlmostEqual(self.removed(), area * 20, 2)
        bb = h.ToolShape.BoundBox
        self.assertAlmostEqual(bb.XLength, 10 + d, 4)
        h.SlotAngle = 90
        self.doc.recompute()
        self.assertAlmostEqual(h.ToolShape.BoundBox.YLength, 10 + d, 4)
        h.HoleType = "Counterbore Slot"
        self.doc.recompute()
        self.ok(h)
        h.HoleType = "Countersink Slot"
        self.doc.recompute()
        self.ok(h)
        self.assertGreater(self.removed(), area * 20)

    def test_up_to_next_and_surface(self):
        # A second plate above a gap: Up To Next stops at the first plate's bottom.
        sk = sketch(self.doc, plane(self.part, "Top Plane"),
                    attach_offset=App.Placement(V(0, 0, -30), App.Rotation()))
        rect(sk, 0, 0, 60, 30)
        self.doc.recompute()
        extrude(self.doc, self.part, sk, Depth=10)
        v0 = self.total()
        h = self.hole(HoleType="Hole", Size="M6", EndCondition="Up To Next")
        a = PI * 3.3 ** 2
        self.assertAlmostEqual(v0 - self.total(), a * 20, 2)
        h.EndCondition = "Through All"
        self.doc.recompute()
        self.assertAlmostEqual(v0 - self.total(), a * 30, 2)
        bottom2 = [("Face%d" % i) for i, f in enumerate(self.plate.Shape.Faces, 1)
                   if abs(f.CenterOfMass.z) < 1e-6][0]
        h.EndCondition = "Offset From Surface"
        refs.set_ref(h, "UpTo", self.plate, [bottom2])
        h.OffsetDistance = 5
        self.doc.recompute()
        self.ok(h)
        self.assertAlmostEqual(v0 - self.total(), a * 15, 2)

    def test_near_and_far_side_countersinks(self):
        h = self.hole(HoleType="Hole", Size="M6", EndCondition="Through All")
        base = self.removed()
        h.NearSideCsk = True
        h.NearCskDiameter = 10
        h.FarSideCsk = True
        h.FarCskDiameter = 10
        self.doc.recompute()
        self.ok(h)
        hgt = (10 - 6.6) / 2.0       # 90 degrees
        cone = PI * hgt / 3 * (5 ** 2 + 5 * 3.3 + 3.3 ** 2) - PI * 3.3 ** 2 * hgt
        self.assertAlmostEqual(self.removed() - base, 2 * cone, 2)
        h.EndCondition = "Blind"
        h.Depth = 10
        self.doc.recompute()
        self.assertIn("far side", h.WarningMessage)

    def test_custom_sizing_and_head_clearance(self):
        h = self.hole(HoleType="Counterbore", Size="M6", EndCondition="Through All")
        self.assertAlmostEqual(h.CboreDiameter.Value, 11.0, 6)
        h.CustomSizing = True
        h.CboreDiameter = 12
        h.CboreDepth = 5
        self.doc.recompute()
        self.ok(h)
        expect = PI * 3.3 ** 2 * 15 + PI * 6 ** 2 * 5
        self.assertAlmostEqual(self.removed(), expect, 2)
        h.HoleDiameter = 13
        self.doc.recompute()
        self.assertIn("wider than the hole", h.ErrorMessage)

    def test_modelled_thread(self):
        h = self.hole(HoleType="Straight Tap", Size="M6", EndCondition="Blind", Depth=15,
                      TipAngle=0)
        drilled = self.removed()
        h.ThreadOption = "Modelled Thread"
        h.ThreadDepth = 10
        self.doc.recompute()
        self.ok(h)
        extra = self.removed() - drilled
        self.assertGreater(extra, 5)
        h.ThreadOption = "Thread Diameter"
        self.doc.recompute()
        self.assertAlmostEqual(self.removed(), PI * 3 ** 2 * 15, 2)


if __name__ == "__main__":
    unittest.main()
