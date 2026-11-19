# SPDX-License-Identifier: LGPL-2.1-or-later
"""Revolve: end conditions, axes, thin, multi-body, naming."""

import math
import unittest

import FreeCAD as App
import Part

from freecad.SolidDesign.app import refs
from freecad.SolidDesign.app import revolve as app_revolve
from helpers import V, extrude, new_doc, plane, rect, sketch, volumes

PI = math.pi


def ring(r0, r1, h, deg=360.0):
    return PI * (r1 * r1 - r0 * r0) * h * deg / 360.0


class Case(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("Rev")
        # Profile on the Front Plane (XZ): x 5..8, z 0..4; centerline along Z.
        self.sk = sketch(self.doc, plane(self.part, "Front Plane"))
        rect(self.sk, 5, 0, 8, 4)
        self.sk.addGeometry(Part.LineSegment(V(0, -10, 0), V(0, 10, 0)), True)
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def revolve(self, mode="Add", sk=None, **props):
        f = app_revolve.create(self.doc, self.part, mode, sk or self.sk)
        for k, v in props.items():
            setattr(f, k, v)
        self.doc.recompute()
        return f

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)


class TestRevolve(Case):
    def test_full_and_centerline_default(self):
        f = self.revolve()
        self.ok(f)
        self.assertEqual(f.Axis[1], ["Axis1"])          # the centerline, picked automatically
        self.assertEqual(f.Label, "Revolve1")
        self.assertAlmostEqual(f.Shape.Volume, ring(5, 8, 4), 4)

    def test_blind_reverse_mid_plane_dir2(self):
        f = self.revolve(Angle=90)
        self.ok(f)
        self.assertAlmostEqual(f.Shape.Volume, ring(5, 8, 4, 90), 4)
        f.EndCondition = "Mid-Plane"
        f.Angle = 120
        self.doc.recompute()
        self.assertAlmostEqual(f.Shape.Volume, ring(5, 8, 4, 120), 4)
        bb = f.Shape.BoundBox
        self.assertAlmostEqual(bb.YMin, -bb.YMax, 6)    # symmetric about the sketch plane
        f.EndCondition = "Blind"
        f.Angle = 90
        f.Direction2 = True
        f.Angle2 = 45
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(f.Shape.Volume, ring(5, 8, 4, 135), 4)

    def test_up_to_vertex_and_surface(self):
        # A post at +Y; revolve the ring up to a vertex/face of it.
        f = self.revolve(Angle=90)
        top = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(top, -1, 20, 1, 22)
        self.doc.recompute()
        post = extrude(self.doc, self.part, top, Depth=2, MergeResult=False)
        app = app_revolve.create(self.doc, self.part, "Add", self.sk)
        app.EndCondition = "Up To Vertex"
        base = app.BaseFeature
        vi = [i for i, v in enumerate(base.Shape.Vertexes, 1)
              if (v.Point - V(0, 20, 0)).Length < 1e-9]
        if vi:
            refs.set_ref(app, "UpToVertex", base, "Vertex%d" % vi[0])
            self.doc.recompute()
            self.ok(app)
            sweep = app.AddSubShape.Volume
            self.assertTrue(abs(sweep - ring(5, 8, 4, 90)) < 1e-3 or
                            abs(sweep - ring(5, 8, 4, 270)) < 1e-3, sweep)
        # Up To Surface: the Right Plane (YZ) contains the axis.
        app.EndCondition = "Up To Surface"
        refs.set_ref(app, "UpToFace", plane(self.part, "Right Plane"), "")
        self.doc.recompute()
        self.ok(app)
        self.assertAlmostEqual(app.AddSubShape.Volume, ring(5, 8, 4, 90), 3)
        del f, post

    def test_profile_crossing_axis(self):
        sk = sketch(self.doc, plane(self.part, "Front Plane"))
        rect(sk, -2, 0, 3, 4)
        sk.addGeometry(Part.LineSegment(V(0, -10, 0), V(0, 10, 0)), True)
        self.doc.recompute()
        f = self.revolve(sk=sk)
        self.assertIn("crosses the axis", f.ErrorMessage)

    def test_no_axis(self):
        sk = sketch(self.doc, plane(self.part, "Front Plane"))
        rect(sk, 5, 0, 8, 4)
        self.doc.recompute()
        f = self.revolve(sk=sk)
        self.assertIn("Pick an axis", f.ErrorMessage)
        refs.set_ref(f, "Axis", plane(self.part, "Z Axis"), "")
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(f.Shape.Volume, ring(5, 8, 4), 4)

    def test_cut_and_thin(self):
        f = self.revolve()
        sk = sketch(self.doc, plane(self.part, "Front Plane"))
        rect(sk, 6, 1, 7, 3)
        sk.addGeometry(Part.LineSegment(V(0, -10, 0), V(0, 10, 0)), True)
        self.doc.recompute()
        c = self.revolve("Cut", sk=sk)
        self.ok(c)
        self.assertEqual(c.Label, "Cut-Revolve1")
        self.assertAlmostEqual(sum(volumes(self.part).values()),
                               ring(5, 8, 4) - ring(6, 7, 2), 3)
        f.Thin = True
        f.ThinThickness = 0.5
        f.ThinType = "Mid-Plane"
        self.doc.recompute()
        self.ok(f)
        # A thin ring around the 3 x 4 rectangle profile, revolved.
        self.assertGreater(f.Shape.Volume, 0)
        self.assertLess(f.Shape.Volume, ring(5, 8, 4))
