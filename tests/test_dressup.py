# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fillet and Chamfer, including how their edge references follow the model."""

import math
import os
import tempfile
import unittest

import FreeCAD as App
import Part
import Sketcher

from freecad.SolidDesign.app import dressup
from freecad.SolidDesign.app import part as app_part
from freecad.SolidDesign.app import util
from helpers import V, circle, extrude, new_doc, plane, rect, sketch, volumes

PI = math.pi
FILLET_LOSS = (1 - PI / 4)      # area removed by a fillet of radius 1, per unit length


def edge_at(obj, point):
    for i, e in enumerate(obj.Shape.Edges, 1):
        if (e.CenterOfMass - point).Length < 1e-6:
            return "Edge%d" % i
    raise AssertionError("no edge at %s" % point)


def vertex_at(obj, point):
    for i, v in enumerate(obj.Shape.Vertexes, 1):
        if (v.Point - point).Length < 1e-6:
            return "Vertex%d" % i
    raise AssertionError("no vertex at %s" % point)


def face_at(obj, point):
    for i, f in enumerate(obj.Shape.Faces, 1):
        if (f.CenterOfMass - point).Length < 1e-6:
            return "Face%d" % i
    raise AssertionError("no face at %s" % point)


def face_with(obj, point):
    for i, f in enumerate(obj.Shape.Faces, 1):
        if f.isInside(point, 1e-6, True):
            return "Face%d" % i
    raise AssertionError("no face holds %s" % point)


class Case(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("Dress")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 20, 10)
        self.width = sk.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, 20.0))
        sk.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -1, 1))
        sk.addConstraint(Sketcher.Constraint("Horizontal", 0))
        sk.addConstraint(Sketcher.Constraint("Horizontal", 2))
        sk.addConstraint(Sketcher.Constraint("Vertical", 1))
        sk.addConstraint(Sketcher.Constraint("Vertical", 3))
        sk.addConstraint(Sketcher.Constraint("DistanceY", 1, 1, 1, 2, 10.0))
        self.base_sketch = sk
        self.doc.recompute()
        self.box = extrude(self.doc, self.part, sk, Depth=5)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)

    def total(self):
        return sum(volumes(self.part).values())


class TestFillet(Case):
    def test_one_edge(self):
        e = edge_at(self.box, V(20, 5, 5))           # top right edge, length 10
        f = dressup.create_fillet(self.doc, self.part, [e])
        f.Radius = 1
        self.doc.recompute()
        self.ok(f)
        self.assertEqual(f.Label, "Fillet1")
        self.assertAlmostEqual(self.total(), 1000 - FILLET_LOSS * 10, 4)
        self.assertEqual(list(self.part.BodyIds), list(self.box.BodyIds))   # same body

    def test_face_and_tangent_propagation(self):
        top = None
        for i, fc in enumerate(self.box.Shape.Faces, 1):
            if abs(fc.CenterOfMass.z - 5) < 1e-9:
                top = "Face%d" % i
        f = dressup.create_fillet(self.doc, self.part, [top])
        f.Radius = 1
        self.doc.recompute()
        self.ok(f)
        self.assertEqual(len(f.Shape.Solids), 1)
        self.assertLess(self.total(), 1000 - FILLET_LOSS * 60 + 1)

    def test_asymmetric_and_profiles(self):
        e = edge_at(self.box, V(20, 5, 5))           # top right edge, length 10
        f = dressup.create_fillet(self.doc, self.part, [e])
        f.Radius = 1
        f.FilletMethod = "Asymmetric"
        f.Distance2 = 2
        self.doc.recompute()
        self.ok(f)
        quarter_ellipse = 1 * 2 - math.pi * 1 * 2 / 4.0
        self.assertAlmostEqual(self.total(), 1000 - quarter_ellipse * 10, 3)
        f.FilletMethod = "Symmetric"
        f.Profile = "Conic Rho"
        f.ConicRho = 0.5
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(self.total(), 1000 - (0.5 - 1.0 / 3.0) * 10, 3)   # a parabola
        f.Profile = "Curvature Continuous"
        self.doc.recompute()
        self.ok(f)
        self.assertLess(1000 - self.total(), FILLET_LOSS * 10)       # softer than a round

    def test_variable_with_points(self):
        e = edge_at(self.box, V(20, 5, 5))
        f = dressup.create_fillet(self.doc, self.part, [e])
        f.FilletType = "Variable Size"
        f.StartRadius = 1
        f.EndRadius = 1
        f.VariablePoints = ["50|2"]
        self.doc.recompute()
        self.ok(f)
        loss = 1000 - self.total()
        self.assertGreater(loss, FILLET_LOSS * 10 * 1.5)
        self.assertLess(loss, FILLET_LOSS * 10 * 4)

    def test_face_fillet_hold_line_and_gap(self):
        top = face_with(self.box, V(10, 5, 5))
        right = face_with(self.box, V(20, 5, 2.5))
        f = dressup.create_fillet(self.doc, self.part, [])
        f.FilletType = "Face Fillet"
        from freecad.SolidDesign.app import refs
        refs.set_ref(f, "FaceSet1", self.box, [top])
        refs.set_ref(f, "FaceSet2", self.box, [right])
        sk = sketch(self.doc, plane(self.part, "Top Plane"),
                    attach_offset=App.Placement(V(0, 0, 5), App.Rotation()))
        sk.addGeometry(Part.LineSegment(V(18, 0, 0), V(18, 10, 0)))
        self.doc.recompute()
        refs.set_ref(f, "HoldLine", sk, ["Edge1"])
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(self.total(), 1000 - (4 - math.pi) * 10, 3)   # R2 held at x 18

    def test_too_large(self):
        e = edge_at(self.box, V(20, 5, 5))
        f = dressup.create_fillet(self.doc, self.part, [e])
        f.Radius = 50
        self.doc.recompute()
        self.assertIn("smaller radius", f.ErrorMessage)
        self.assertAlmostEqual(self.total(), 1000)   # bodies before pass through

    def test_multibody(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 30, 0, 40, 10)
        self.doc.recompute()
        b2 = extrude(self.doc, self.part, sk, Depth=5, MergeResult=False)
        e1 = edge_at(b2, V(20, 5, 5))
        e2 = edge_at(b2, V(40, 5, 5))
        f = dressup.create_fillet(self.doc, self.part, [e1, e2])
        f.Radius = 1
        self.doc.recompute()
        self.ok(f)
        vols = volumes(self.part)
        self.assertEqual(sorted(vols), sorted(b2.BodyIds))
        for v in vols.values():
            self.assertLess(v, 1000)


class TestFollow(Case):
    """SolidWorks: a fillet's edges are those of the model just before it."""

    def setUp(self):
        Case.setUp(self)
        self.f = dressup.create_fillet(self.doc, self.part, [edge_at(self.box, V(20, 5, 5))])
        self.f.Radius = 1
        self.doc.recompute()
        self.ok(self.f)

    def check(self, length=10.0, extra=0.0):
        self.ok(self.f)
        self.assertAlmostEqual(self.total(), 1000 * (self.box.Shape.Volume / 1000)
                               - FILLET_LOSS * length - extra, 3)

    def test_upstream_dimension(self):
        self.base_sketch.setDatum(self.width, App.Units.Quantity("25 mm"))
        self.doc.recompute()
        self.ok(self.f)
        bb = self.f.Shape.BoundBox
        self.assertAlmostEqual(bb.XMax, 25)
        self.assertAlmostEqual(self.total(), 1250 - FILLET_LOSS * 10, 3)

    def test_insert_before(self):
        app_part.roll_to(self.part, self.box)
        self.doc.recompute()
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        circle(sk, 5, 5, 2)
        self.doc.recompute()
        hole = extrude(self.doc, self.part, sk, "Cut", EndCondition="Through All")
        app_part.roll_to_end(self.part)
        self.doc.recompute()
        self.assertIs(self.f.BaseFeature, hole)
        self.assertIs(self.f.Items[0], hole)        # the reference followed the model
        self.ok(self.f)
        self.assertAlmostEqual(self.total(), 1000 - PI * 4 * 5 - FILLET_LOSS * 10, 3)

    def test_inserted_feature_changes_the_edge(self):
        """An inserted feature that shortens the edge: the fillet follows the new edge."""
        app_part.roll_to(self.part, self.box)
        self.doc.recompute()
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 15, 6, 25, 15)                       # notch the corner at x = 20, y 6..10
        self.doc.recompute()
        notch = extrude(self.doc, self.part, sk, "Cut", EndCondition="Through All")
        app_part.roll_to_end(self.part)
        self.doc.recompute()
        self.ok(notch)
        if self.f.ErrorMessage:
            self.assertIn("Re-pick", self.f.ErrorMessage)
        else:
            self.assertIs(self.f.Items[0], notch)

    def test_delete_before(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        circle(sk, 5, 5, 2)
        self.doc.recompute()
        app_part.roll_to(self.part, self.box)
        hole = extrude(self.doc, self.part, sk, "Cut", EndCondition="Through All")
        app_part.roll_to_end(self.part)
        self.doc.recompute()
        self.ok(self.f)
        self.doc.removeObject(hole.Name)
        self.doc.recompute()
        self.assertIs(self.f.BaseFeature, self.box)
        self.ok(self.f)
        self.assertAlmostEqual(self.total(), 1000 - FILLET_LOSS * 10, 3)

    def test_suppress_reorder_rollback_reopen(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        circle(sk, 5, 5, 2)
        self.doc.recompute()
        hole = extrude(self.doc, self.part, sk, "Cut", EndCondition="Through All")
        self.ok(hole)
        app_part.move_feature(self.part, hole, 1)       # before the fillet
        self.doc.recompute()
        self.ok(self.f)
        hole.Suppressed = True
        self.doc.recompute()
        self.ok(self.f)
        hole.Suppressed = False
        for feat in util.features(self.part):
            app_part.roll_to(self.part, feat)
            self.doc.recompute()
        self.ok(self.f)
        path = os.path.join(tempfile.mkdtemp(), "f.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.part = [o for o in self.doc.Objects if util.is_part(o)][0]
        self.f = [o for o in util.features(self.part) if o.Label == "Fillet1"][0]
        for o in self.doc.Objects:
            o.touch()
        self.doc.recompute()
        self.ok(self.f)
        self.assertAlmostEqual(self.total(), 1000 - PI * 4 * 5 - FILLET_LOSS * 10, 3)


class TestChamfer(Case):
    def test_distance_distance(self):
        e = edge_at(self.box, V(20, 5, 5))
        c = dressup.create_chamfer(self.doc, self.part, [e])
        c.ChamferType = "Distance Distance"
        c.Distance = 2
        self.doc.recompute()
        self.ok(c)
        self.assertAlmostEqual(self.total(), 1000 - 0.5 * 2 * 2 * 10, 4)
        c.EqualDistance = False
        c.Distance2 = 1
        self.doc.recompute()
        self.assertAlmostEqual(self.total(), 1000 - 0.5 * 2 * 1 * 10, 4)
        a = self.part.Shape.BoundBox
        c.FlipDirection = True
        self.doc.recompute()
        self.assertAlmostEqual(self.total(), 1000 - 0.5 * 2 * 1 * 10, 4)
        self.assertEqual(round(a.XMax, 6), round(self.part.Shape.BoundBox.XMax, 6))

    def test_angle_distance(self):
        c = dressup.create_chamfer(self.doc, self.part, [edge_at(self.box, V(20, 5, 5))])
        c.Distance = 2
        c.Angle = 30
        self.doc.recompute()
        self.ok(c)
        self.assertAlmostEqual(self.total(), 1000 - 0.5 * 2 * 2 * math.tan(math.radians(30)) * 10, 4)

    def test_offset_face_right_angle(self):
        c = dressup.create_chamfer(self.doc, self.part, [edge_at(self.box, V(20, 5, 5))])
        c.ChamferType = "Offset Face"
        c.Distance = 1.5
        self.doc.recompute()
        self.ok(c)
        self.assertAlmostEqual(self.total(), 1000 - 0.5 * 1.5 * 1.5 * 10, 4)

    def test_vertex(self):
        c = dressup.create_chamfer(self.doc, self.part, [vertex_at(self.box, V(20, 10, 5))])
        c.ChamferType = "Vertex"
        c.Distance = 2
        self.doc.recompute()
        self.ok(c)
        self.assertAlmostEqual(self.total(), 1000 - 2 * 2 * 2 / 6.0, 4)

    def test_face_face(self):
        top, side = face_at(self.box, V(10, 5, 5)), face_at(self.box, V(20, 5, 2.5))
        c = dressup.create_chamfer(self.doc, self.part, [top, side])
        c.ChamferType = "Face Face"
        c.EqualDistance = False
        c.Distance = 1
        c.Distance2 = 2
        self.doc.recompute()
        self.ok(c)
        self.assertAlmostEqual(self.total(), 1000 - 0.5 * 1 * 2 * 10, 4)
        topf = [f for f in self.part.Shape.Faces if abs(f.CenterOfMass.z - 5) < 1e-6][0]
        self.assertAlmostEqual(topf.BoundBox.XMax, 19, 6)     # first distance on the top
        c.Items = (self.box, [side, top])
        self.doc.recompute()
        self.ok(c)
        topf = [f for f in self.part.Shape.Faces if abs(f.CenterOfMass.z - 5) < 1e-6][0]
        self.assertAlmostEqual(topf.BoundBox.XMax, 18, 6)     # now on the side

    def test_face_face_needs_touching_faces(self):
        top, bottom = face_at(self.box, V(10, 5, 5)), face_at(self.box, V(10, 5, 0))
        c = dressup.create_chamfer(self.doc, self.part, [top, bottom])
        c.ChamferType = "Face Face"
        self.doc.recompute()
        self.assertIn("never meet", c.ErrorMessage)

    def test_face_face_across_a_gap(self):
        # A small chamfer first: then top and front don't touch.
        e = [i for i, x in enumerate(self.box.Shape.Edges, 1)
             if abs(x.CenterOfMass.y) < 1e-9 and abs(x.CenterOfMass.z - 5) < 1e-9][0]
        c1 = dressup.create_chamfer(self.doc, self.part, ["Edge%d" % e])
        c1.Distance = 0.5
        self.doc.recompute()
        self.ok(c1)
        top, front = face_with(c1, V(10, 5, 5)), face_with(c1, V(10, 0, 2))
        c = dressup.create_chamfer(self.doc, self.part, [top, front])
        c.ChamferType = "Face Face"
        c.Distance = 2
        self.doc.recompute()
        self.ok(c)
        self.assertAlmostEqual(self.total(), 1000 - 0.5 * 2 * 2 * 20, 4)


REEXPORTED = (Part,)
