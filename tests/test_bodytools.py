# SPDX-License-Identifier: LGPL-2.1-or-later
"""Combine, Delete/Keep Body, Split, Move/Copy Body."""

import unittest

import FreeCAD as App

from freecad.SolidDesign.app import bodytools, refgeom
from freecad.SolidDesign.app import part as app_part
from freecad.SolidDesign.core import refgeom as core_ref
from helpers import V, circle, extrude, face_at, new_doc, plane, rect, sketch, volumes


class Case(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("BT")
        self.a = self.box(0, 0, 10, 10, 10)          # 1000
        self.b = self.box(5, 0, 15, 10, 10)          # overlaps a by 500
        self.c = self.box(30, 0, 40, 10, 10)         # separate
        self.ida, self.idb, self.idc = self.part.BodyIds

    def box(self, x0, y0, x1, y1, h):
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, x0, y0, x1, y1)
        self.doc.recompute()
        return extrude(self.doc, self.part, sk, Depth=h, MergeResult=False)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)


class TestCombine(Case):
    def test_add_subtract_common(self):
        f = bodytools.create_combine(self.doc, self.part, Operation="Add",
                                     Bodies=[self.ida, self.idb])
        self.doc.recompute()
        self.ok(f)
        v = volumes(self.part)
        self.assertEqual(sorted(v), sorted([self.ida, self.idc]))   # b used up, a keeps its ID
        self.assertAlmostEqual(v[self.ida], 1500)
        self.assertEqual(f.Label, "Combine1")
        f.Operation = "Subtract"
        f.MainBody = self.ida
        f.Bodies = [self.idb]
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(volumes(self.part)[self.ida], 500)
        f.Operation = "Common"
        f.MainBody = ""
        f.Bodies = [self.ida, self.idb]
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(volumes(self.part)[self.ida], 500)

    def test_add_not_touching(self):
        f = bodytools.create_combine(self.doc, self.part, Bodies=[self.ida, self.idc])
        self.doc.recompute()
        self.assertIn("don't touch", f.ErrorMessage)
        self.assertEqual(len(self.part.BodyIds), 3)


class TestDeleteKeep(Case):
    def test_delete_and_keep(self):
        f = bodytools.create_delete(self.doc, self.part, Bodies=[self.idb])
        self.doc.recompute()
        self.ok(f)
        self.assertEqual(list(self.part.BodyIds), [self.ida, self.idc])
        self.assertEqual(f.Label, "Body-Delete/Keep1")
        f.Type = "Keep Bodies"
        self.doc.recompute()
        self.assertEqual(list(self.part.BodyIds), [self.idb])


class TestSplit(Case):
    def test_split_by_plane_keep_and_names(self):
        p = refgeom.create_plane(self.doc, self.part, core_ref.OFFSET,
                                 [(plane(self.part, "Top Plane"), "")])
        p.Distance = 4
        self.doc.recompute()
        f = bodytools.create_split(self.doc, self.part, TrimTools=[p],
                                   TargetBodies=[self.idc])
        self.doc.recompute()
        self.ok(f)
        v = volumes(self.part)
        self.assertEqual(len(v), 4)
        self.assertAlmostEqual(v[self.idc], 600)          # the largest piece keeps the ID
        small = [k for k in v if k not in (self.ida, self.idb, self.idc)][0]
        self.assertAlmostEqual(v[small], 400)
        f.PieceNames = {small: "Lid"}
        self.doc.recompute()
        names = sorted(app_part.clean_label(x.Label) for x in app_part.body_views(self.part))
        self.assertIn("Lid", names)
        f.KeepAll = False
        f.KeepPieces = [small]
        self.doc.recompute()
        self.assertNotIn(self.idc, self.part.BodyIds)
        self.assertIn(small, self.part.BodyIds)

    def test_split_by_sketch_not_consumed(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        circle(sk, 35, 5, 2)
        self.doc.recompute()
        f = bodytools.create_split(self.doc, self.part, TrimTools=[sk],
                                   TargetBodies=[self.idc], ConsumeCutBodies=False)
        self.doc.recompute()
        self.ok(f)
        v = volumes(self.part)
        self.assertAlmostEqual(v[self.idc], 1000)       # kept whole
        self.assertEqual(len(v), 5)                     # plus the two pieces

    def test_nothing_cut(self):
        p = refgeom.create_plane(self.doc, self.part, core_ref.OFFSET,
                                 [(plane(self.part, "Top Plane"), "")])
        p.Distance = 50
        self.doc.recompute()
        f = bodytools.create_split(self.doc, self.part, TrimTools=[p])
        self.doc.recompute()
        self.assertIn("don't cut", f.ErrorMessage)


class TestSplitByFace(unittest.TestCase):
    """A trim face cuts off what stands on it, as a plane would, only when the
    face surrounds every edge the protrusion has on it."""

    def setUp(self):
        self.doc, self.part = new_doc("SF")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def box(self, x0, x1):
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, x0, 0, x1, 10)
        self.doc.recompute()
        return extrude(self.doc, self.part, sk, Depth=10, MergeResult=False)

    def boss(self, cx, cy):
        sk = sketch(self.doc, plane(self.part, "Top Plane"),
                    attach_offset=App.Placement(V(0, 0, 10), App.Rotation()))
        circle(sk, cx, cy, 2)
        self.doc.recompute()
        return extrude(self.doc, self.part, sk, Depth=5)

    def split_by_top(self, feat, x):
        top = face_at(feat, V(x, 1, 10), V(0, 0, 1))
        f = bodytools.create_split(self.doc, self.part)
        f.TrimFaces = (feat, [top])
        self.doc.recompute()
        return f

    def test_cylinder_on_a_cube_is_cut_off(self):
        self.box(0, 10)
        b = self.boss(5, 5)
        f = self.split_by_top(b, 1)
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)
        v = sorted(volumes(self.part).values())
        self.assertEqual(len(v), 2)
        self.assertAlmostEqual(v[0], 3.14159265 * 4 * 5, 3)
        self.assertAlmostEqual(v[1], 1000, 3)
        cube = [b.shape for b in app_part.tip_bodies(self.part)
                if abs(b.shape.Volume - 1000) < 1e-3][0]
        self.assertEqual(len(cube.Faces), 6, "no scar where the cylinder stood")
        tops = [g for g in cube.Faces if abs(g.CenterOfMass.z - 10) < 1e-6]
        self.assertEqual(len(tops), 1)
        self.assertAlmostEqual(tops[0].Area, 100, 6)
        self.assertEqual(len(tops[0].Wires), 1)
        cyl = [b.shape for b in app_part.tip_bodies(self.part)
               if abs(b.shape.Volume - 1000) > 1e-3][0]
        self.assertEqual(len(cyl.Faces), 3)

    def test_other_cubes_top_does_not_cut(self):
        a = self.box(0, 10)
        self.box(20, 30)
        self.boss(25, 5)
        f = self.split_by_top(a, 1)
        self.assertIn("don't cut", f.ErrorMessage)
        self.assertEqual(len(volumes(self.part)), 2)

    def test_boss_over_the_edge_is_not_cut(self):
        self.box(0, 10)
        b = self.boss(10, 5)                 # half on the face, half over the side
        f = self.split_by_top(b, 1)
        self.assertIn("don't cut", f.ErrorMessage)
        self.assertEqual(len(volumes(self.part)), 1)


    def test_extended_face_cuts_past_its_edges(self):
        a = self.box(0, 10)
        self.box(20, 30)
        self.boss(25, 5)
        f = self.split_by_top(a, 1)
        f.ExtendFaces = True
        self.doc.recompute()
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)
        v = sorted(volumes(self.part).values())
        self.assertEqual(len(v), 3)                     # the other boss is cut off
        self.assertAlmostEqual(v[0], 3.14159265 * 4 * 5, 3)

    def test_extended_face_cuts_a_boss_over_the_edge(self):
        self.box(0, 10)
        b = self.boss(10, 5)
        f = self.split_by_top(b, 1)
        f.ExtendFaces = True
        self.doc.recompute()
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)
        self.assertEqual(len(volumes(self.part)), 2)


class TestSplitByCurvedFace(unittest.TestCase):
    """A cylinder poking out of a sphere: the sphere's face cuts it off."""

    def setUp(self):
        from freecad.SolidDesign.app import revolve
        import Part
        self.doc, self.part = new_doc("SC")
        sk = sketch(self.doc, plane(self.part, "Front Plane"))
        sk.addGeometry(Part.ArcOfCircle(Part.Circle(V(0, 0, 0), V(0, 0, 1), 10),
                                        -3.14159265 / 2, 3.14159265 / 2))
        sk.addGeometry(Part.LineSegment(V(0, 10, 0), V(0, -10, 0)))
        self.doc.recompute()
        axis = sketch(self.doc, plane(self.part, "Front Plane"))
        axis.addGeometry(Part.LineSegment(V(0, -20, 0), V(0, 20, 0)))
        self.doc.recompute()
        self.ball = revolve.create(self.doc, self.part, sketch=sk)
        self.ball.Axis = (sk, ["Edge2"])
        self.doc.recompute()
        pin = sketch(self.doc, plane(self.part, "Top Plane"))
        circle(pin, 0, 0, 3)
        self.doc.recompute()
        self.pin = extrude(self.doc, self.part, pin, Depth=25)
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)

    def test_sphere_face_cuts_off_the_cylinder(self):
        sph = [i for i, g in enumerate(self.pin.Shape.Faces, 1)
               if g.Surface.TypeId == "Part::GeomSphere"]
        self.assertEqual(len(sph), 1)
        f = bodytools.create_split(self.doc, self.part)
        f.TrimFaces = (self.pin, ["Face%d" % sph[0]])
        self.doc.recompute()
        self.ok(f)
        v = sorted(volumes(self.part).values())
        self.assertEqual(len(v), 2)
        self.assertAlmostEqual(v[1], 4 / 3.0 * 3.14159265 * 1000, 2)   # the ball, whole
        f.ExtendFaces = True
        self.doc.recompute()
        self.ok(f)
        self.assertEqual(len(volumes(self.part)), 2)

    def test_extended_cylinder_cores_the_ball(self):
        cyl = [i for i, g in enumerate(self.pin.Shape.Faces, 1)
               if g.Surface.TypeId == "Part::GeomCylinder"]
        total = sum(volumes(self.part).values())
        f = bodytools.create_split(self.doc, self.part)
        f.TrimFaces = (self.pin, ["Face%d" % cyl[0]])
        f.ExtendFaces = True
        self.doc.recompute()
        self.ok(f)
        v = sorted(volumes(self.part).values())
        self.assertEqual(len(v), 2)       # the core (with the pin above it) and the rest
        self.assertAlmostEqual(sum(v), total, 3)
        self.assertGreater(v[1], 3500)


class TestMoveCopy(Case):
    def test_body_view_follows_the_move(self):
        """What the user sees (the body in the tree and the view) moves too."""
        f = bodytools.create_move(self.doc, self.part, Bodies=[self.idc], DeltaX=10)
        self.doc.recompute()
        self.ok(f)
        view = [v for v in app_part.body_views(self.part) if v.BodyId == self.idc][0]
        self.assertAlmostEqual(view.Shape.BoundBox.XMin, 40)
        f.DeltaX = 0
        self.doc.recompute()
        self.assertAlmostEqual(view.Shape.BoundBox.XMin, 30)

    def test_translate_rotate_copy(self):
        f = bodytools.create_move(self.doc, self.part, Bodies=[self.idc], DeltaX=10)
        self.doc.recompute()
        self.ok(f)
        bb = app_part.tip_bodies(self.part).get(self.idc).shape.BoundBox
        self.assertAlmostEqual(bb.XMin, 40)                 # moved, same ID
        self.assertEqual(f.Label, "Body-Move/Copy1")
        f.Copy = True
        f.Copies = 3
        self.doc.recompute()
        self.ok(f)
        v = volumes(self.part)
        self.assertEqual(len(v), 6)
        xs = sorted(round(b.shape.BoundBox.XMin, 6) for b in app_part.tip_bodies(self.part)
                    if b.id not in (self.ida, self.idb))
        self.assertEqual(xs, [30, 40, 50, 60])              # copy k moved k times
        ax = refgeom.create_axis(self.doc, self.part, core_ref.TWO_PLANES,
                                 [(plane(self.part, "Front Plane"), ""),
                                  (plane(self.part, "Right Plane"), "")])
        self.doc.recompute()
        g = bodytools.create_move(self.doc, self.part, Bodies=[self.ida], Angle=90)
        g.RotateReference = (ax, [])
        self.doc.recompute()
        self.ok(g)
        bb = app_part.tip_bodies(self.part).get(self.ida).shape.BoundBox
        self.assertAlmostEqual(bb.XMin, -10, 6)
        self.assertAlmostEqual(bb.YMax, 10, 6)

    def test_expression_drives_copies(self):
        f = bodytools.create_move(self.doc, self.part, Bodies=[self.idc], DeltaY=20, Copy=True)
        f.setExpression("Copies", "1 + 1")
        self.doc.recompute()
        self.ok(f)
        self.assertEqual(len(self.part.BodyIds), 5)
