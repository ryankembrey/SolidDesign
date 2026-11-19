# SPDX-License-Identifier: LGPL-2.1-or-later
"""Boundary, Intersect, Dome and Wrap."""

import math
import unittest

import FreeCAD as App
import Part

from freecad.SolidDesign.app import part as app_part
from freecad.SolidDesign.app import morefeatures as more
from freecad.SolidDesign.app import refgeom, sweep as app_sweep
from freecad.SolidDesign.core import refgeom as core_ref
from helpers import V, circle, extrude, face_at, new_doc, plane, rect, sketch

PI = math.pi


class Case(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("S4")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)

    def bodies(self):
        return list(app_part.tip_bodies(self.part))

    def at(self, z, r=5):
        sk = sketch(self.doc, plane(self.part, "Top Plane"),
                    attach_offset=App.Placement(V(0, 0, z), App.Rotation()))
        circle(sk, 0, 0, r)
        self.doc.recompute()
        return sk


class TestBoundary(Case):
    def test_one_direction_is_a_loft(self):
        b = app_sweep.create_boundary(self.doc, self.part, profiles=[self.at(0), self.at(20)])
        self.doc.recompute()
        self.ok(b)
        self.assertEqual(b.Label, "Boundary1")
        self.assertAlmostEqual(self.bodies()[0].shape.Volume, PI * 25 * 20, 3)

    def test_two_directions_pass_through_every_curve(self):
        d2 = []
        for k in range(4):
            a = math.radians(90 * k + 10)
            d = V(math.cos(a), math.sin(a), 0)
            # a sketch on the plane through the axis and this direction
            sk = sketch(self.doc, plane(self.part, "Top Plane"))
            sk.MapMode = "Deactivated"
            sk.Placement = App.Placement(V(), App.Rotation(d, V(0, 0, 1),
                                                           d.cross(V(0, 0, 1)), "ZXY"))
            x0 = 5
            if k == 1:
                bc = Part.BSplineCurve()
                bc.interpolate([V(x0, 0, 0), V(x0 + 1, 5, 0), V(x0, 10, 0), V(x0 + 1, 15, 0),
                                V(x0, 20, 0)])
                sk.addGeometry(bc)
            else:
                sk.addGeometry(Part.LineSegment(V(x0, 0, 0), V(x0, 20, 0)))
            d2.append(sk)
        self.doc.recompute()
        for sk in d2:
            e = sk.Shape.Edges[0]
            self.assertAlmostEqual(e.valueAt(e.FirstParameter).z, 0, 6)
        b = app_sweep.create_boundary(self.doc, self.part,
                                      profiles=[self.at(0), self.at(10), self.at(20)],
                                      direction2=d2)
        self.doc.recompute()
        self.ok(b)
        s = self.bodies()[0].shape
        self.assertTrue(s.isValid())
        for sk in d2:
            e = sk.Shape.Edges[0]
            for t in (0.13, 0.5, 0.81):
                p = e.valueAt(e.FirstParameter + t * (e.LastParameter - e.FirstParameter))
                self.assertLess(s.distToShape(Part.Vertex(p))[0], 1e-5)
        self.assertGreater(s.Volume, PI * 25 * 20)
        b.Mode = "Cut"
        self.doc.recompute()
        self.assertIn("no body to cut", b.ErrorMessage.lower())


class TestIntersect(Case):
    def test_two_boxes_regions(self):
        a = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(a, 0, 0, 10, 10)
        b = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(b, 5, 5, 15, 15)
        self.doc.recompute()
        extrude(self.doc, self.part, a, Depth=10)
        extrude(self.doc, self.part, b, Depth=10, MergeResult=False)
        ids = [x.id for x in self.bodies()]
        f = more.create_intersect(self.doc, self.part, Bodies=ids, MergeResult=False)
        self.doc.recompute()
        self.ok(f)
        vols = sorted(round(x.shape.Volume, 3) for x in self.bodies())
        self.assertEqual(vols, [250.0, 750.0, 750.0])
        f.ExcludedPoints = [more.vec_text(V(2, 2, 5)), more.vec_text(V(12, 12, 5))]
        self.doc.recompute()
        self.ok(f)
        vols = sorted(round(x.shape.Volume, 3) for x in self.bodies())
        self.assertEqual(vols, [250.0])                # only the overlap is kept

    def test_surface_and_plane_close_a_region(self):
        from freecad.SolidDesign.app import surfaces
        a = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(a, 0, 0, 10, 10)
        self.doc.recompute()
        box = extrude(self.doc, self.part, a, Depth=10)
        top = face_at(box, V(5, 5, 10), V(0, 0, 1))
        surfaces.create_delete_face(self.doc, self.part, Items=[top])
        self.doc.recompute()
        sid = self.bodies()[0].id
        cut = refgeom.create_plane(self.doc, self.part, core_ref.OFFSET,
                                   [(plane(self.part, "Top Plane"), "")])
        cut.Distance = 6
        self.doc.recompute()
        f = more.create_intersect(self.doc, self.part, Bodies=[sid], Planes=[cut],
                                  IntersectMode="Create internal regions")
        self.doc.recompute()
        self.ok(f)
        b = self.bodies()
        self.assertEqual([x.kind for x in b], ["solid"])
        self.assertAlmostEqual(b[0].shape.Volume, 600, 3)


class TestDomeWrap(Case):
    def cyl(self):
        sk = self.at(0, 10)
        return extrude(self.doc, self.part, sk, Depth=40)

    def test_dome_on_round_and_square_faces(self):
        c = self.cyl()
        top = face_at(c, V(0, 0, 40), V(0, 0, 1))
        d = more.create_dome(self.doc, self.part, Items=[top], Distance=4)
        self.doc.recompute()
        self.ok(d)
        h, r = 4.0, 10.0
        cap = PI * h * h * (3 * ((r * r + h * h) / (2 * h)) - h) / 3
        s = self.bodies()[0].shape
        self.assertAlmostEqual(s.Volume, PI * 100 * 40 + cap, 3)
        self.assertAlmostEqual(s.BoundBox.ZMax, 44, 6)
        d.EllipticalDome = True
        self.doc.recompute()
        self.ok(d)
        self.assertAlmostEqual(self.bodies()[0].shape.Volume,
                               PI * 100 * 40 + 2 / 3.0 * PI * 100 * 4, 2)
        d.ReverseDirection = True
        d.EllipticalDome = False
        self.doc.recompute()
        self.ok(d)
        self.assertAlmostEqual(self.bodies()[0].shape.Volume, PI * 100 * 40 - cap, 3)

    def test_dome_on_a_square_face(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 20, 20)
        self.doc.recompute()
        box = extrude(self.doc, self.part, sk, Depth=10)
        top = face_at(box, V(10, 10, 10), V(0, 0, 1))
        d = more.create_dome(self.doc, self.part, Items=[top], Distance=3)
        self.doc.recompute()
        self.ok(d)
        s = self.bodies()[0].shape
        self.assertAlmostEqual(s.Volume, 4000 + 400 * 3 / 2.0, 1)   # rises as 1 - s^2
        self.assertAlmostEqual(s.BoundBox.ZMax, 13, 2)
        d.EllipticalDome = True
        self.doc.recompute()
        self.ok(d)
        self.assertGreater(self.bodies()[0].shape.Volume, 4000 + 600)

    def test_wrap_on_a_cylinder(self):
        c = self.cyl()
        side = face_at(c, V(10, 0, 20), V(1, 0, 0))
        sk = sketch(self.doc, plane(self.part, "Right Plane"),
                    attach_offset=App.Placement(V(0, 0, 10), App.Rotation()))
        rect(sk, -3, 10, 3, 20)          # 6 wide (round), 10 high
        self.doc.recompute()
        n = sk.getGlobalPlacement().Rotation.multVec(V(0, 0, 1))
        self.assertAlmostEqual(abs(n.x), 1, 6)
        w = more.create_wrap(self.doc, self.part, Sketch=sk, Items=[side], Depth=1)
        self.doc.recompute()
        self.ok(w)
        base_v = PI * 100 * 40
        ring = 0.6 / 2 * (121 - 100) * 10
        self.assertAlmostEqual(self.bodies()[0].shape.Volume, base_v + ring, 3)
        w.WrapType = "Deboss"
        self.doc.recompute()
        self.ok(w)
        self.assertAlmostEqual(self.bodies()[0].shape.Volume, base_v - 0.6 / 2 * (100 - 81) * 10,
                               3)
        w.WrapType = "Scribe"
        self.doc.recompute()
        self.ok(w)
        s = self.bodies()[0].shape
        self.assertGreater(len(s.Faces), 3)            # the side face is split
        self.assertAlmostEqual(s.Volume, base_v, 2)
