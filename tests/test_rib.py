# SPDX-License-Identifier: LGPL-2.1-or-later
"""Rib: parallel and normal to the sketch, sides, extension to the model."""

import math
import unittest

import FreeCAD as App
import Part

from freecad.SolidDesign.app import part as app_part, pattern, rib
from helpers import V, extrude, new_doc, plane, rect, sketch, volumes


def line(sk, a, b):
    return sk.addGeometry(Part.LineSegment(V(a[0], a[1], 0), V(b[0], b[1], 0)))


class TestRib(unittest.TestCase):
    def setUp(self):
        # A U channel: floor 40 x 20 x 2, walls 2 thick and 12 high at x = 0..2 and 38..40.
        self.doc, self.part = new_doc("Rb")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 40, 20)
        self.doc.recompute()
        self.floor = extrude(self.doc, self.part, sk, Depth=2)
        for x0 in (0, 38):
            s = sketch(self.doc, plane(self.part, "Top Plane"))
            rect(s, x0, 0, x0 + 2, 20)
            self.doc.recompute()
            extrude(self.doc, self.part, s, Depth=12)
        self.v0 = self.total()
        self.assertAlmostEqual(self.v0, 40 * 20 * 2 + 2 * 2 * 20 * 10, 3)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def total(self):
        return sum(volumes(self.part).values())

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)

    def front_sketch(self, y=10):
        """A sketch on a plane parallel to the Front Plane (XZ), at depth y."""
        s = sketch(self.doc, plane(self.part, "Front Plane"),
                   attach_offset=App.Placement(V(0, 0, -y), App.Rotation()))
        return s

    def test_parallel_to_sketch_fills_between_the_walls(self):
        # A line across the channel at height 8, shorter than the gap: it is
        # extended to the walls, and the rib fills down to the floor.
        s = self.front_sketch()
        line(s, (10, 8), (30, 8))
        self.doc.recompute()
        r = rib.create(self.doc, self.part, sketch=s)
        r.Thickness = 2
        self.doc.recompute()
        self.ok(r)
        self.assertEqual(r.Label, "Rib1")
        added = self.total() - self.v0
        self.assertAlmostEqual(added, 36 * 6 * 2, 2)       # 36 wide, 2..8 high, 2 thick
        self.assertEqual(len(volumes(self.part)), 1)

    def test_sides_and_flip(self):
        s = self.front_sketch()
        line(s, (10, 8), (30, 8))
        self.doc.recompute()
        r = rib.create(self.doc, self.part, sketch=s)
        r.Thickness = 3
        r.ThicknessSide = "First Side"
        self.doc.recompute()
        self.ok(r)
        bb1 = r.ToolShape.BoundBox
        r.ThicknessSide = "Second Side"
        self.doc.recompute()
        self.ok(r)
        bb2 = r.ToolShape.BoundBox
        self.assertAlmostEqual(bb1.YLength, 3, 4)
        self.assertAlmostEqual(bb2.YLength, 3, 4)
        self.assertAlmostEqual(abs(bb1.YMin - bb2.YMin), 3, 4)
        # Upwards nothing closes it off.
        r.FlipMaterialSide = True
        self.doc.recompute()
        self.assertIn("runs off the model", r.ErrorMessage)
        self.assertAlmostEqual(self.total(), self.v0, 3)

    def test_normal_to_sketch(self):
        # A sketch on a plane at height 10 (inside the channel), a line along y:
        # the rib grows down to the floor, 2 thick in x.
        s = sketch(self.doc, plane(self.part, "Top Plane"),
                   attach_offset=App.Placement(V(0, 0, 10), App.Rotation()))
        line(s, (20, 2), (20, 18))
        self.doc.recompute()
        r = rib.create(self.doc, self.part, sketch=s)
        r.ExtrusionDirection = "Normal to Sketch"
        r.Thickness = 2
        self.doc.recompute()
        self.ok(r)
        # Not extended (nothing to meet along y inside the channel ends): 16 long.
        bb = r.ToolShape.BoundBox
        self.assertAlmostEqual(bb.XLength, 2, 4)
        self.assertAlmostEqual(bb.ZMin, 2, 4)
        self.assertAlmostEqual(bb.ZMax, 10, 4)

    def test_draft(self):
        s = self.front_sketch()
        line(s, (10, 8), (30, 8))
        self.doc.recompute()
        r = rib.create(self.doc, self.part, sketch=s)
        r.Thickness = 3
        self.doc.recompute()
        plain = self.total() - self.v0
        r.Draft = True
        r.DraftAngle = 3
        self.doc.recompute()
        self.ok(r)
        thinner = self.total() - self.v0
        self.assertLess(thinner, plain)
        # Each side leans in over the 6 mm to the floor: a wedge per side.
        wedge = 0.5 * 6 * 6 * math.tan(math.radians(3)) * 36
        self.assertAlmostEqual(plain - thinner, 2 * wedge, 1)
        r.DraftOutward = True
        self.doc.recompute()
        self.ok(r)
        self.assertGreater(self.total() - self.v0, plain)

    def test_natural_extension_of_an_arc(self):
        """An arc whose circle meets a wall: Natural carries it round to the wall;
        Linear goes off along the tangent and misses (the rib is open)."""
        s = self.front_sketch()
        # An arc centred at (20, 2) radius 7, from 160° to 20°, inside the channel: its
        # circle crosses the floor but its tangents point up and away.
        import Part as _P
        arc = _P.ArcOfCircle(_P.Circle(V(20, 2, 0), V(0, 0, 1), 7), math.radians(20),
                             math.radians(160))
        s.addGeometry(arc)
        self.doc.recompute()
        r = rib.create(self.doc, self.part, sketch=s)
        r.ExtendType = "Natural"
        self.doc.recompute()
        self.ok(r)
        self.assertGreater(self.total(), self.v0)

    def test_closed_sketch_is_refused(self):
        s = self.front_sketch()
        rect(s, 10, 4, 20, 8)
        self.doc.recompute()
        r = rib.create(self.doc, self.part, sketch=s)
        self.doc.recompute()
        self.assertIn("open sketch lines", r.ErrorMessage)

    def test_rib_follows_the_wall_height_and_can_be_mirrored(self):
        s = self.front_sketch(y=5)
        line(s, (10, 8), (30, 8))
        self.doc.recompute()
        r = rib.create(self.doc, self.part, sketch=s)
        self.doc.recompute()
        self.ok(r)
        one = self.total() - self.v0
        m = pattern.create_mirror(self.doc, self.part, Features=[r])
        from freecad.SolidDesign.app import refs
        mid = self.doc.addObject("Part::Feature", "MidY")
        mid.Shape = Part.makePlane(100, 100, V(-50, 10, -50), V(0, 1, 0))
        refs.set_ref(m, "MirrorPlane", mid, ["Face1"])
        self.doc.recompute()
        self.ok(m)
        self.assertAlmostEqual(self.total() - self.v0, 2 * one, 2)


if __name__ == "__main__":
    unittest.main()
