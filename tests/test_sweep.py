# SPDX-License-Identifier: LGPL-2.1-or-later
"""Sweep and Loft."""

import math
import unittest

import FreeCAD as App
import Part

from freecad.SolidDesign.app import sweep as app_sweep
from helpers import V, circle, extrude, new_doc, plane, rect, sketch, volumes

PI = math.pi


class Case(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("Sw")
        # Path: on the Front Plane (XZ), straight up 20 then a quarter arc.
        self.path = sketch(self.doc, plane(self.part, "Front Plane"))
        self.path.addGeometry(Part.LineSegment(V(0, 0, 0), V(0, 20, 0)))
        self.path.addGeometry(Part.ArcOfCircle(Part.Circle(V(10, 20, 0), V(0, 0, 1), 10),
                                               math.pi / 2, math.pi))
        self.doc.recompute()
        # Profile on the Top Plane at the path's start.
        self.prof = sketch(self.doc, plane(self.part, "Top Plane"))
        circle(self.prof, 0, 0, 2)
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)

    def total(self):
        return sum(volumes(self.part).values())


class TestSweep(Case):
    def sweep(self, mode="Add", **kw):
        f = app_sweep.create_sweep(self.doc, self.part, mode, self.prof)
        f.Path = (self.path, [])
        for k, v in kw.items():
            setattr(f, k, v)
        self.doc.recompute()
        return f

    def test_sweep_along_path(self):
        f = self.sweep()
        self.ok(f)
        self.assertEqual(f.Label, "Sweep1")
        length = 20 + PI * 10 / 2
        self.assertAlmostEqual(f.Shape.Volume, PI * 4 * length, 1)    # Pappus
        self.assertEqual(len(f.Shape.Solids), 1)

    def test_circular_profile_and_cut(self):
        sk = sketch(self.doc, plane(self.part, "Front Plane"))
        rect(sk, -10, -5, 20, 40)
        self.doc.recompute()
        block = extrude(self.doc, self.part, sk, EndCondition="Mid Plane", Depth=20)
        self.ok(block)
        f = app_sweep.create_sweep(self.doc, self.part, "Cut", None)
        f.ProfileType = "Circular Profile"
        f.Diameter = 4
        f.Path = (self.path, [])
        self.doc.recompute()
        self.ok(f)
        self.assertEqual(f.Label, "Cut-Sweep1")
        self.assertLess(self.total(), block.Shape.Volume)

    def test_keep_normal_constant(self):
        f = self.sweep(Orientation="Keep Normal Constant")
        self.ok(f)
        self.assertGreater(f.Shape.Volume, 0)

    def test_open_profile_makes_surface(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        sk.addGeometry(Part.LineSegment(V(-2, 0, 0), V(2, 0, 0)))
        self.doc.recompute()
        f = app_sweep.create_sweep(self.doc, self.part, "Add", sk)
        f.Path = (self.path, [])
        self.doc.recompute()
        self.ok(f)
        self.assertEqual(list(self.part.BodyKinds), ["surface"])

    def test_no_path(self):
        f = app_sweep.create_sweep(self.doc, self.part, "Add", self.prof)
        self.doc.recompute()
        self.assertIn("Pick a path", f.ErrorMessage)


class TestLoft(Case):
    def test_loft_two_profiles_and_point(self):
        top = sketch(self.doc, plane(self.part, "Top Plane"),
                     attach_offset=App.Placement(V(0, 0, 10), App.Rotation()))
        rect(top, -3, -3, 3, 3)
        self.doc.recompute()
        f = app_sweep.create_loft(self.doc, self.part, "Add", profiles=[self.prof, top])
        self.doc.recompute()
        self.ok(f)
        self.assertEqual(f.Label, "Loft1")
        self.assertEqual(len(f.Shape.Solids), 1)
        bb = f.Shape.BoundBox
        self.assertAlmostEqual(bb.ZMax, 10, 6)
        tip = sketch(self.doc, plane(self.part, "Top Plane"),
                     attach_offset=App.Placement(V(0, 0, 20), App.Rotation()))
        tip.addGeometry(Part.Point(V(0, 0, 0)))
        self.doc.recompute()
        f.Profiles = [self.prof, top, tip]
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(f.Shape.BoundBox.ZMax, 20, 6)

    def test_loft_with_holes_and_errors(self):
        a = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(a, -5, -5, 5, 5)
        circle(a, 0, 0, 2)
        b = sketch(self.doc, plane(self.part, "Top Plane"),
                   attach_offset=App.Placement(V(0, 0, 10), App.Rotation()))
        rect(b, -4, -4, 4, 4)
        circle(b, 0, 0, 1)
        self.doc.recompute()
        f = app_sweep.create_loft(self.doc, self.part, "Add", profiles=[a, b])
        self.doc.recompute()
        self.ok(f)
        outer = 10 / 3.0 * (100 + 64 + 80)
        inner = PI * 10 / 3.0 * (4 + 1 + 2)
        self.assertAlmostEqual(f.Shape.Volume, outer - inner, 1)
        f.Profiles = [a]
        self.doc.recompute()
        self.assertIn("at least two", f.ErrorMessage)


class TestSweepMore(Case):
    """Twist, guide curves, path tangency and the solid profile."""

    def straight(self, length=30):
        sk = sketch(self.doc, plane(self.part, "Front Plane"))
        sk.addGeometry(Part.LineSegment(V(0, 0, 0), V(0, length, 0)))
        self.doc.recompute()
        return sk

    def square(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, -2, -2, 2, 2)
        self.doc.recompute()
        return sk

    def make(self, prof, path, **kw):
        f = app_sweep.create_sweep(self.doc, self.part, kw.pop("mode", "Add"), prof)
        f.Path = (path, [])
        for k, v in kw.items():
            setattr(f, k, v)
        self.doc.recompute()
        return f

    @staticmethod
    def top(f, z):
        return sorted((round(v.Point.x, 4), round(v.Point.y, 4)) for v in f.Shape.Vertexes
                      if abs(v.Point.z - z) < 1e-6)

    def test_twist_degrees_and_turns(self):
        path = self.straight()
        f = self.make(self.square(), path, ProfileTwist="Specify Twist Value", TwistAngle=45)
        self.ok(f)
        r = 2 * math.sqrt(2)
        self.assertEqual(self.top(f, 30), [(-round(r, 4), 0.0), (0.0, -round(r, 4)),
                                           (0.0, round(r, 4)), (round(r, 4), 0.0)])
        self.assertAlmostEqual(f.Shape.Volume, 16 * 30, 3)
        f.TwistControl = "Turns"
        f.Turns = 0.125
        self.doc.recompute()
        self.ok(f)
        self.assertEqual(len(self.top(f, 30)), 4)
        self.assertAlmostEqual(abs(self.top(f, 30)[0][0]), r, 3)

    def test_twist_on_a_curved_path(self):
        f = self.make(self.square(), self.path, ProfileTwist="Specify Twist Value",
                      TwistAngle=180)
        self.ok(f)
        length = 20 + PI * 10 / 2
        self.assertAlmostEqual(f.Shape.Volume, 16 * length, 0)

    def test_guide_curve_scales_the_profile(self):
        path = self.straight()
        g = sketch(self.doc, plane(self.part, "Front Plane"))
        g.addGeometry(Part.LineSegment(V(2, 0, 0), V(4, 30, 0)))
        self.doc.recompute()
        f = self.make(self.prof, path, GuideCurves=[g])
        self.ok(f)
        cone = PI * 30 * (4 + 8 + 16) / 3.0
        self.assertAlmostEqual(f.Shape.Volume, cone, 2)
        self.assertAlmostEqual(f.Shape.BoundBox.XMax, 4, 4)
        plain = f.Shape.Volume
        f.StartTangency = "Path Tangent"
        self.doc.recompute()
        self.ok(f)
        self.assertNotAlmostEqual(f.Shape.Volume, plain, 3)
        self.assertAlmostEqual(f.Shape.Volume, plain, -1)

    def test_guide_must_touch_the_profile(self):
        path = self.straight()
        g = sketch(self.doc, plane(self.part, "Front Plane"))
        g.addGeometry(Part.LineSegment(V(3, 0, 0), V(4, 30, 0)))
        self.doc.recompute()
        f = self.make(self.prof, path, GuideCurves=[g])
        self.assertIn("doesn't touch the profile", f.ErrorMessage)

    def test_solid_profile_cut(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, -5, -10, 35, 10)
        self.doc.recompute()
        block = extrude(self.doc, self.part, sk, Depth=10)
        tsk = sketch(self.doc, plane(self.part, "Top Plane"),
                     attach_offset=App.Placement(V(0, 0, 5), App.Rotation()))
        circle(tsk, 0, 0, 2)
        self.doc.recompute()
        tool = extrude(self.doc, self.part, tsk, Depth=10, MergeResult=False)
        self.ok(tool)
        ids = list(self.part.BodyIds)
        path = sketch(self.doc, plane(self.part, "Top Plane"),
                      attach_offset=App.Placement(V(0, 0, 5), App.Rotation()))
        path.addGeometry(Part.LineSegment(V(0, 0, 0), V(30, 0, 0)))
        self.doc.recompute()
        f = self.make(None, path, mode="Cut", ProfileType="Solid Profile", ToolBody=ids[1])
        self.ok(f)
        v = volumes(self.part)
        self.assertAlmostEqual(v[ids[0]], 40 * 20 * 10 - (4 * 30 * 5 + PI * 4 * 5), 3)
        self.assertAlmostEqual(v[ids[1]], PI * 4 * 10, 3)      # the tool body stays whole
        f.ToolBody = ids[0]
        self.doc.recompute()
        self.assertIn("revolution", f.ErrorMessage)
        _ = block


class TestLoftMore(Case):
    def two(self):
        top = sketch(self.doc, plane(self.part, "Top Plane"),
                     attach_offset=App.Placement(V(0, 0, 20), App.Rotation()))
        circle(top, 0, 0, 2)
        self.doc.recompute()
        return top

    def test_normal_to_profile_bulges(self):
        f = app_sweep.create_loft(self.doc, self.part, "Add", profiles=[self.prof, self.two()])
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(f.Shape.Volume, PI * 4 * 20, 3)       # a cylinder
        f.StartConstraint = "Normal To Profile"
        f.StartDraftAngle = 30
        self.doc.recompute()
        self.ok(f)
        self.assertGreater(f.Shape.Volume, PI * 4 * 20 + 1)          # flares out
        f.StartDraftAngle = 0
        f.StartConstraint = "Direction Vector"
        self.doc.recompute()
        self.assertIn("direction vector", f.ErrorMessage)
        x = [o for o in self.part.Origin if o.TypeId == "Part::DatumLine"
             and o.Label.startswith("Z")][0]
        f.StartDirection = (x, [])
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(f.Shape.Volume, PI * 4 * 20, 2)

    def test_guide_curve_bulges_one_side(self):
        g = sketch(self.doc, plane(self.part, "Front Plane"))
        g.addGeometry(Part.ArcOfCircle(V(2, 0, 0), V(5, 10, 0), V(2, 20, 0)))
        self.doc.recompute()
        f = app_sweep.create_loft(self.doc, self.part, "Add", profiles=[self.prof, self.two()])
        f.GuideCurves = [g]
        self.doc.recompute()
        self.ok(f)
        mid = f.Shape.slice(V(0, 0, 1), 10)[0].BoundBox
        self.assertAlmostEqual(mid.XMax, 5, 3)
        self.assertLess(abs(mid.XMin + 2), 0.05)        # To Next Edge: the far side stays
        self.assertLess(f.Shape.distToShape(Part.Vertex(V(5, 0, 10)))[0], 1e-3)
        f.GuideInfluence = "To Next Guide"
        self.doc.recompute()
        self.ok(f)
        mid = f.Shape.slice(V(0, 0, 1), 10)[0].BoundBox
        self.assertAlmostEqual(mid.XMin, 1, 2)          # one guide moves the whole profile

    def test_guide_must_touch_every_profile(self):
        g = sketch(self.doc, plane(self.part, "Front Plane"))
        g.addGeometry(Part.LineSegment(V(3, 0, 0), V(2, 20, 0)))
        self.doc.recompute()
        f = app_sweep.create_loft(self.doc, self.part, "Add", profiles=[self.prof, self.two()])
        f.GuideCurves = [g]
        self.doc.recompute()
        self.assertIn("doesn't touch profile 1", f.ErrorMessage)
