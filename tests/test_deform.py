# SPDX-License-Identifier: LGPL-2.1-or-later
"""Scale and Flex."""

import math
import unittest

import FreeCAD as App

from freecad.SolidDesign.app import deform
from freecad.SolidDesign.app import part as app_part
from helpers import V, circle, extrude, new_doc, plane, rect, sketch

PI = math.pi


class Case(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("Def")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 10, 10)
        self.doc.recompute()
        self.box = extrude(self.doc, self.part, sk, Depth=40)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)

    def shape(self):
        return list(app_part.tip_bodies(self.part))[0].shape


class TestScale(Case):
    def test_uniform_and_not(self):
        s = deform.create_scale(self.doc, self.part, Factor=2.0)
        self.doc.recompute()
        self.ok(s)
        self.assertAlmostEqual(self.shape().Volume, 4000 * 8, 3)
        bb = self.shape().BoundBox
        self.assertAlmostEqual(bb.Center.z, 20, 6)              # about its centroid
        s.ScaleAbout = "Origin"
        self.doc.recompute()
        self.assertAlmostEqual(self.shape().BoundBox.ZMax, 80, 6)
        s.Uniform = False
        s.FactorX, s.FactorY, s.FactorZ = 1.0, 2.0, 0.5
        self.doc.recompute()
        self.ok(s)
        self.assertAlmostEqual(self.shape().Volume, 4000, 3)


class TestFlex(Case):
    def test_twist_bend_taper_stretch(self):
        f = deform.create_flex(self.doc, self.part, FlexType="Twisting", Angle=90)
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(self.shape().Volume, 4000, -1)
        self.assertTrue(self.shape().isValid())
        f.FlexType = "Bending"
        self.doc.recompute()
        self.ok(f)
        bb = self.shape().BoundBox
        self.assertLess(bb.ZMax, 35)                            # bent over
        f.FlexType = "Tapering"
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(self.shape().Volume, 4000 * (1 - 0.5 + 0.25 / 3.0), 1)
        f.FlexType = "Stretching"
        f.TrimPlane1 = 10
        f.TrimPlane2 = 10
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(self.shape().Volume, 5000, 1)
        self.assertAlmostEqual(self.shape().BoundBox.ZMax, 50, 4)
