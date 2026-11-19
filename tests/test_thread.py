# SPDX-License-Identifier: LGPL-2.1-or-later
"""Thread: cut and extruded, outside and inside, end conditions, hand, starts."""

import math
import unittest

import FreeCAD as App

from freecad.SolidDesign.app import thread as app_thread
from freecad.SolidDesign.core import threads
from helpers import V, circle, extrude, new_doc, plane, rect, sketch, volumes


def rim(obj, z, r=None):
    for i, e in enumerate(obj.Shape.Edges, 1):
        if hasattr(e.Curve, "Radius") and abs(e.BoundBox.ZMax - z) < 1e-6 and \
                abs(e.BoundBox.ZMin - z) < 1e-6 and (r is None or abs(e.Curve.Radius - r) < 1e-6):
            return "Edge%d" % i
    raise AssertionError("no rim at z=%s" % z)


def groove(r, pitch, length, internal=False):
    """Analytic volume of a cut thread's groove."""
    h = threads.depth(pitch, internal)
    flat = pitch / 8.0
    a = (flat + flat + 2 * h * math.tan(math.radians(30))) / 2.0 * h
    rc = r - h / 2.0 if not internal else r + h / 2.0
    return a * 2 * math.pi * rc * length / pitch


class TestThread(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("Th")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def total(self):
        return sum(volumes(self.part).values())

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)

    def shaft(self, d=10.0, h=20.0):
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        circle(sk, 0, 0, d / 2.0)
        self.doc.recompute()
        return extrude(self.doc, self.part, sk, Depth=h)

    def test_cut_thread_on_a_shaft(self):
        s = self.shaft()
        v0 = self.total()
        t = app_thread.create(self.doc, self.part, (s, rim(s, 20)))
        t.Length = 12
        self.doc.recompute()
        self.ok(t)
        self.assertEqual(t.Label, "Thread1")
        self.assertEqual(t.Size, "M10")
        removed = v0 - self.total()
        self.assertAlmostEqual(removed / groove(5, 1.5, 12), 1.0, 1)
        self.assertEqual(len(volumes(self.part)), 1)

    def test_extrude_revolutions_left_hand_two_starts(self):
        s = self.shaft(d=8.0)
        v0 = self.total()
        t = app_thread.create(self.doc, self.part, (s, rim(s, 20)))
        t.Method = "Extrude Thread"
        t.EndCondition = "Revolutions"
        t.Revolutions = 4
        t.LeftHand = True
        self.doc.recompute()
        self.ok(t)
        one = self.total() - v0
        self.assertGreater(one, 0)
        t.Starts = 2
        self.doc.recompute()
        self.ok(t)
        # Two starts on the same length: twice the ridges (the lead doubles, the
        # length is the same number of pitches).
        self.assertAlmostEqual((self.total() - v0) / one, 2.0, 1)

    def test_tapped_hole(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, -10, -10, 10, 10)
        circle(sk, 0, 0, 2.5)          # M6 tap drill 5.0
        self.doc.recompute()
        b = extrude(self.doc, self.part, sk, Depth=10)
        v0 = self.total()
        t = app_thread.create(self.doc, self.part, (b, rim(b, 10, 2.5)))
        t.EndCondition = "Up To Selection"
        bottom = [("Face%d" % i) for i, f in enumerate(b.Shape.Faces, 1)
                  if f.Surface.TypeId == "Part::GeomPlane" and abs(f.CenterOfMass.z) < 1e-6][0]
        from freecad.SolidDesign.app import refs
        refs.set_ref(t, "UpTo", b, [bottom])
        self.doc.recompute()
        self.ok(t)
        self.assertEqual(t.Size, "M6")
        removed = v0 - self.total()
        self.assertAlmostEqual(removed / groove(2.5, 1.0, 10, True), 1.0, 1)

    def test_size_mismatch_warns_and_override_pitch(self):
        s = self.shaft(d=11.0)
        t = app_thread.create(self.doc, self.part, (s, rim(s, 20)))
        self.doc.recompute()
        self.ok(t)
        self.assertIn("doesn't match", t.WarningMessage)
        t.OverridePitch = True
        t.Pitch = 1.0
        self.doc.recompute()
        self.ok(t)

    def test_offset_and_errors(self):
        s = self.shaft()
        t = app_thread.create(self.doc, self.part, (s, rim(s, 20)))
        t.Offset = True
        t.OffsetDistance = 5
        t.Length = 5
        self.doc.recompute()
        self.ok(t)
        t.Length = 0
        self.doc.recompute()
        self.assertIn("no length", t.ErrorMessage)
        t2 = app_thread.create(self.doc, self.part)
        self.doc.recompute()
        self.assertIn("circular edge", t2.ErrorMessage)


if __name__ == "__main__":
    unittest.main()
