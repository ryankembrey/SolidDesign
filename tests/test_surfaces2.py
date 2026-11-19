# SPDX-License-Identifier: LGPL-2.1-or-later
"""Ruled, Radiate, Untrim, Mid-Surface, Cut With Surface, Replace Face."""

import math
import unittest

import FreeCAD as App
import Part

from freecad.SolidDesign.app import part as app_part
from freecad.SolidDesign.app import refgeom, surfaces, surfaces2 as s2
from freecad.SolidDesign.core import refgeom as core_ref
from helpers import V, circle, extrude, face_at, new_doc, plane, rect, sketch

PI = math.pi


def edges_at(obj, z):
    return ["Edge%d" % i for i, e in enumerate(obj.Shape.Edges, 1)
            if abs(e.BoundBox.ZMin - z) < 1e-6 and abs(e.BoundBox.ZMax - z) < 1e-6]


class Case(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("S7")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 20, 10)
        self.doc.recompute()
        self.box = extrude(self.doc, self.part, sk, Depth=10)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)

    def bodies(self):
        return list(app_part.tip_bodies(self.part))

    def surface(self):
        return [b for b in self.bodies() if b.kind == "surface"]


class TestSurfaces2(Case):
    def test_ruled_and_radiate(self):
        r = s2.create_ruled(self.doc, self.part, Items=edges_at(self.box, 10),
                            RuledType="Normal to Surface", Distance=5)
        self.doc.recompute()
        self.ok(r)
        self.assertEqual(r.Label, "Ruled Surface1")
        self.assertAlmostEqual(self.surface()[0].shape.Area, 60 * 5, 6)
        r.RuledType = "Tapered to Vector"
        r.ReferenceVector = (plane(self.part, "Top Plane"), [])
        r.Angle = 30
        self.doc.recompute()
        self.ok(r)
        rd = s2.create_radiate(self.doc, self.part, Items=edges_at(self.box, 10), Distance=4)
        rd.ReferencePlane = (plane(self.part, "Top Plane"), [])
        self.doc.recompute()
        self.ok(rd)
        s = [b for b in self.surface() if abs(b.shape.BoundBox.ZMax - 10) < 1e-6
             and abs(b.shape.BoundBox.ZMin - 10) < 1e-6]
        self.assertEqual(len(s), 1)
        self.assertAlmostEqual(s[0].shape.optimalBoundingBox().XMin, -4, 2)   # outwards

    def test_untrim_and_mid_surface(self):
        hs = sketch(self.doc, plane(self.part, "Top Plane"))
        circle(hs, 10, 5, 2)
        self.doc.recompute()
        hole = extrude(self.doc, self.part, hs, "Cut", EndCondition="Through All")
        top = face_at(hole, V(3, 3, 10), V(0, 0, 1))
        u = s2.create_untrim(self.doc, self.part, Items=[top], UntrimType="Internal edges")
        self.doc.recompute()
        self.ok(u)
        self.assertAlmostEqual(self.surface()[0].shape.Area, 200, 6)
        m = s2.create_mid_surface(self.doc, self.part, Bodies=[self.bodies()[0].id])
        self.doc.recompute()
        self.ok(m)
        mid = [f for b in self.surface() for f in b.shape.Faces
               if abs(f.BoundBox.ZMin - 5) < 1e-6 and abs(f.BoundBox.ZMax - 5) < 1e-6]
        self.assertEqual(len(mid), 1)                   # midway through the 10 mm block
        self.assertAlmostEqual(mid[0].Area, 200 - PI * 4, 5)

    def test_cut_with_a_plane_and_replace_face(self):
        cut = refgeom.create_plane(self.doc, self.part, core_ref.OFFSET,
                                   [(plane(self.part, "Top Plane"), "")])
        cut.Distance = 6
        self.doc.recompute()
        c = s2.create_cut_with_surface(self.doc, self.part)
        c.CuttingPlane = (cut, [])
        self.doc.recompute()
        self.ok(c)
        self.assertAlmostEqual(self.bodies()[0].shape.Volume, 1200, 3)
        c.Flip = True
        self.doc.recompute()
        self.ok(c)
        self.assertAlmostEqual(self.bodies()[0].shape.Volume, 800, 3)

    def test_replace_face_with_a_surface(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"),
                    attach_offset=App.Placement(V(0, 0, 14), App.Rotation()))
        rect(sk, -5, -5, 25, 15)
        self.doc.recompute()
        pl = surfaces.create_planar(self.doc, self.part, Sketch=sk)
        self.doc.recompute()
        sid = self.surface()[0].id
        top = face_at(self.box, V(10, 5, 10), V(0, 0, 1))
        r = s2.create_replace_face(self.doc, self.part, Items=[top], ReplacementBody=sid)
        self.doc.recompute()
        self.ok(r)
        b = self.bodies()
        self.assertEqual([x.kind for x in b], ["solid"])          # the surface is used up
        self.assertAlmostEqual(b[0].shape.Volume, 20 * 10 * 14, 3)
        _ = pl
