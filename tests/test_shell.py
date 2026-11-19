# SPDX-License-Identifier: LGPL-2.1-or-later
"""Shell."""

import unittest

import FreeCAD as App

from freecad.SolidDesign.app import dressup, refs
from helpers import V, extrude, face_at, new_doc, plane, rect, sketch, volumes


class TestShell(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("Sh")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 20, 10)
        self.doc.recompute()
        self.box = extrude(self.doc, self.part, sk, Depth=10)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def total(self):
        return sum(volumes(self.part).values())

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)

    def test_open_top(self):
        top = face_at(self.box, V(10, 5, 10), V(0, 0, 1))
        s = dressup.create_shell(self.doc, self.part, [top])
        self.doc.recompute()
        self.ok(s)
        self.assertEqual(s.Label, "Shell1")
        self.assertAlmostEqual(self.total(), 2000 - 18 * 8 * 9, 3)
        self.assertEqual(list(self.part.BodyIds), list(self.box.BodyIds))
        s.ShellOutward = True
        self.doc.recompute()
        self.ok(s)
        self.assertAlmostEqual(self.box.Shape.BoundBox.XLength + 2,
                               s.Shape.BoundBox.XLength, 6)

    def test_hollow_closed_and_multi_thickness(self):
        s = dressup.create_shell(self.doc, self.part, [])
        s.Thickness = 1
        self.doc.recompute()
        self.ok(s)
        self.assertAlmostEqual(self.total(), 2000 - 18 * 8 * 8, 3)
        top = face_at(self.box, V(10, 5, 10), V(0, 0, 1))
        bottom = face_at(self.box, V(10, 5, 0), V(0, 0, -1))
        refs.set_ref(s, "Items", self.box, [top])
        refs.set_ref(s, "MultiFaces", self.box, [bottom])
        s.MultiThickness = [3.0]
        self.doc.recompute()
        self.ok(s)
        self.assertAlmostEqual(self.total(), 2000 - 18 * 8 * 7, 3)

    def test_thinner_faces(self):
        """Thinner multi-thickness faces, alone and meeting at a corner."""
        top = face_at(self.box, V(10, 5, 10), V(0, 0, 1))
        bottom = face_at(self.box, V(10, 5, 0), V(0, 0, -1))
        side = face_at(self.box, V(20, 5, 5), V(1, 0, 0))
        s = dressup.create_shell(self.doc, self.part, [top])
        s.Thickness = 2
        self.doc.recompute()
        self.ok(s)
        self.assertAlmostEqual(self.total(), 2000 - 16 * 6 * 8, 3)
        refs.set_ref(s, "MultiFaces", self.box, [bottom])
        s.MultiThickness = [0.5]
        self.doc.recompute()
        self.ok(s)
        self.assertAlmostEqual(self.total(), 2000 - 16 * 6 * 9.5, 3)
        refs.set_ref(s, "MultiFaces", self.box, [bottom, side])
        s.MultiThickness = [0.5, 1.0]
        self.doc.recompute()
        self.ok(s)
        # The hollow grows to 17 x 6 x 9.5: the corner where the two thin walls
        # meet opens up too.
        self.assertAlmostEqual(self.total(), 2000 - 17 * 6 * 9.5, 3)
        refs.set_ref(s, "MultiFaces", self.box, [bottom, side])
        s.MultiThickness = [0.5, 4.0]          # one thinner, one thicker
        self.doc.recompute()
        self.ok(s)
        self.assertAlmostEqual(self.total(), 2000 - 14 * 6 * 9.5, 3)
        s.ShellOutward = True
        self.doc.recompute()
        self.assertIn("inward", s.ErrorMessage)

    def test_lofted_body_kernel_limit(self):
        """A square-to-circle loft can't be offset by OpenCASCADE at all (FreeCAD's own
        Thickness fails too): the error says so and the bodies pass through."""
        from freecad.SolidDesign.app import sweep as app_sweep
        from helpers import circle
        a = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(a, 40, 0, 50, 10)
        b = sketch(self.doc, plane(self.part, "Top Plane"),
                   attach_offset=App.Placement(V(0, 0, 15), App.Rotation()))
        circle(b, 45, 5, 3)
        self.doc.recompute()
        lo = app_sweep.create_loft(self.doc, self.part, "Add", profiles=[a, b])
        lo.MergeResult = False
        self.doc.recompute()
        self.ok(lo)
        fb = [i for i, f in enumerate(lo.Shape.Faces, 1)
              if abs(f.CenterOfMass.z) < 1e-6 and f.CenterOfMass.x > 39][0]
        s = dressup.create_shell(self.doc, self.part, ["Face%d" % fb])
        s.Thickness = 0.5
        self.doc.recompute()
        self.assertIn("shell before that feature", s.ErrorMessage)
        self.assertEqual(len(self.part.BodyIds), 2)

    def test_too_thick(self):
        top = face_at(self.box, V(10, 5, 10), V(0, 0, 1))
        s = dressup.create_shell(self.doc, self.part, [top])
        s.Thickness = 30
        self.doc.recompute()
        self.assertIn("smaller thickness", s.ErrorMessage)
