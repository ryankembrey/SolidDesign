# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reference Plane and Axis: every type, use by sketches and Revolve, following
the model, rollback."""

import math
import unittest

import FreeCAD as App
import Part

from freecad.SolidDesign.app import part as app_part
from freecad.SolidDesign.app import refgeom, util
from freecad.SolidDesign.app import revolve as app_revolve
from freecad.SolidDesign.core import refgeom as core
from helpers import V, extrude, face_at, new_doc, plane, rect, sketch


def normal(obj):
    f = obj.Shape.Faces[0]
    return f.normalAt(0, 0)


def vertex_at(obj, p):
    for i, v in enumerate(obj.Shape.Vertexes, 1):
        if (v.Point - p).Length < 1e-6:
            return "Vertex%d" % i
    raise AssertionError(p)


def edge_at(obj, p):
    for i, e in enumerate(obj.Shape.Edges, 1):
        if (e.CenterOfMass - p).Length < 1e-6:
            return "Edge%d" % i
    raise AssertionError(p)


class TestRefGeom(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("Ref")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 20, 10)
        self.doc.recompute()
        self.box = extrude(self.doc, self.part, sk, Depth=5)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def ok(self, o):
        self.assertEqual(o.ErrorMessage, "", o.ErrorMessage)

    def test_offset_from_face(self):
        top = face_at(self.box, V(10, 5, 5), V(0, 0, 1))
        p = refgeom.create_plane(self.doc, self.part, core.OFFSET, [(self.box, top)])
        p.Distance = 7
        self.doc.recompute()
        self.ok(p)
        self.assertEqual(p.Label, "Plane1")
        self.assertIs(p.BaseFeature, self.box)
        self.assertAlmostEqual(p.Shape.Faces[0].CenterOfMass.z, 12)
        p.Flip = True
        self.doc.recompute()
        self.assertAlmostEqual(p.Shape.Faces[0].CenterOfMass.z, -2)

    def test_coincident_with_face(self):
        """A plane exactly on a planar face, without an offset of 0."""
        top = face_at(self.box, V(10, 5, 5), V(0, 0, 1))
        p = refgeom.create_plane(self.doc, self.part, core.COINCIDENT, [(self.box, top)])
        self.doc.recompute()
        self.ok(p)
        f = p.Shape.Faces[0]
        self.assertAlmostEqual(f.CenterOfMass.z, 5)
        self.assertAlmostEqual(abs(f.normalAt(0, 0).z), 1)
        self.assertNotIn("Distance", [r for r in core.PLANE_NEEDS[core.COINCIDENT]])

    def test_angle_three_points_parallel_normal_mid(self):
        top = face_at(self.box, V(10, 5, 5), V(0, 0, 1))
        e = edge_at(self.box, V(10, 0, 5))
        a = refgeom.create_plane(self.doc, self.part, core.ANGLE, [(self.box, top), (self.box, e)])
        a.Angle = 90
        self.doc.recompute()
        self.ok(a)
        self.assertAlmostEqual(abs(normal(a).y), 1, 6)
        pts = [vertex_at(self.box, V(0, 0, 5)), vertex_at(self.box, V(20, 0, 5)),
               vertex_at(self.box, V(0, 10, 0))]
        t = refgeom.create_plane(self.doc, self.part, core.THREE_POINTS,
                                 [(self.box, x) for x in pts])
        self.doc.recompute()
        self.ok(t)
        pr = refgeom.create_plane(self.doc, self.part, core.PARALLEL_AT_POINT,
                                  [(plane(self.part, "Top Plane"), ""),
                                   (self.box, vertex_at(self.box, V(20, 10, 5)))])
        self.doc.recompute()
        self.ok(pr)
        self.assertAlmostEqual(pr.Shape.Faces[0].CenterOfMass.z, 5)
        nc = refgeom.create_plane(self.doc, self.part, core.NORMAL_TO_CURVE,
                                  [(self.box, edge_at(self.box, V(10, 0, 5)))])
        self.doc.recompute()
        self.ok(nc)
        self.assertAlmostEqual(abs(normal(nc).x), 1, 6)
        bottom = face_at(self.box, V(10, 5, 0), V(0, 0, -1))
        mid = refgeom.create_plane(self.doc, self.part, core.MID_PLANE,
                                   [(self.box, top), (self.box, bottom)])
        self.doc.recompute()
        self.ok(mid)
        self.assertAlmostEqual(mid.Shape.Faces[0].CenterOfMass.z, 2.5)

    def test_axes(self):
        ax = refgeom.create_axis(self.doc, self.part, core.TWO_PLANES,
                                 [(plane(self.part, "Front Plane"), ""),
                                  (plane(self.part, "Right Plane"), "")])
        self.doc.recompute()
        self.ok(ax)
        d = ax.Shape.Edges[0].Curve.Direction
        self.assertAlmostEqual(abs(d.z), 1, 6)
        tp = refgeom.create_axis(self.doc, self.part, core.TWO_POINTS,
                                 [(self.box, vertex_at(self.box, V(0, 0, 0))),
                                  (self.box, vertex_at(self.box, V(0, 0, 5)))])
        self.doc.recompute()
        self.ok(tp)
        pf = refgeom.create_axis(self.doc, self.part, core.POINT_AND_FACE,
                                 [(self.box, vertex_at(self.box, V(20, 10, 5))),
                                  (self.box, face_at(self.box, V(10, 5, 5), V(0, 0, 1)))])
        self.doc.recompute()
        self.ok(pf)
        bad = refgeom.create_axis(self.doc, self.part, core.TWO_PLANES,
                                  [(plane(self.part, "Top Plane"), "")])
        self.doc.recompute()
        self.assertIn("pick", bad.ErrorMessage.lower())

    def test_used_by_sketch_and_revolve(self):
        top = face_at(self.box, V(10, 5, 5), V(0, 0, 1))
        p = refgeom.create_plane(self.doc, self.part, core.OFFSET, [(self.box, top)])
        p.Distance = 10
        self.doc.recompute()
        sk = sketch(self.doc, (p, "Face1"))
        rect(sk, 30, 0, 34, 4)
        self.doc.recompute()
        f = extrude(self.doc, self.part, sk, Depth=2, MergeResult=False)
        self.assertEqual(f.ErrorMessage, "")
        self.assertAlmostEqual(f.AddSubShape.BoundBox.ZMin, 15)
        # The plane is in the history between the box and the new feature.
        g = [o for o in self.part.Group if util.is_feature(o) or util.role(o) == "refgeom"]
        self.assertEqual([o.Label for o in g], ["Boss-Extrude1", "Plane1", "Boss-Extrude2"])
        ax = refgeom.create_axis(self.doc, self.part, core.TWO_PLANES,
                                 [(plane(self.part, "Front Plane"), ""),
                                  (plane(self.part, "Right Plane"), "")])
        self.doc.recompute()
        rs = sketch(self.doc, plane(self.part, "Front Plane"))
        rect(rs, 40, 0, 42, 2)
        self.doc.recompute()
        r = app_revolve.create(self.doc, self.part, "Add", rs)
        r.Axis = (ax, [])
        r.MergeResult = False
        self.doc.recompute()
        self.assertEqual(r.ErrorMessage, "")
        self.assertAlmostEqual(r.AddSubShape.Volume, math.pi * (42 ** 2 - 40 ** 2) * 2, 3)

    def test_follows_model_and_rolls_back(self):
        top = face_at(self.box, V(10, 5, 5), V(0, 0, 1))
        p = refgeom.create_plane(self.doc, self.part, core.OFFSET, [(self.box, top)])
        p.Distance = 1
        self.doc.recompute()
        self.box.Depth = 8                      # the face moves; the plane follows
        self.doc.recompute()
        self.assertAlmostEqual(p.Shape.Faces[0].CenterOfMass.z, 9)
        # Insert a cut before the plane: its base becomes the cut, the face follows.
        app_part.roll_to(self.part, self.box)
        self.doc.recompute()
        self.assertFalse(p.RolledBack)          # made at the bar: it counts as above it
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 2, 2, 4, 4)
        self.doc.recompute()
        cut = extrude(self.doc, self.part, sk, "Cut", EndCondition="Through All")
        g = [o.Label for o in self.part.Group if util.is_feature(o) or util.role(o) == "refgeom"]
        self.assertEqual(g, ["Boss-Extrude1", "Plane1", "Cut-Extrude1"])
        app_part.roll_to(self.part, None)
        self.doc.recompute()
        self.assertTrue(p.RolledBack)
        app_part.roll_to_end(self.part)
        self.doc.recompute()
        self.assertFalse(p.RolledBack)
        self.ok(p)
        del cut



class TestMeasured(unittest.TestCase):
    """Bounding Box and Center of Mass follow the bodies."""

    def setUp(self):
        self.doc, self.part = new_doc("Meas")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 20, 10)
        self.doc.recompute()
        self.box = extrude(self.doc, self.part, sk, Depth=5)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)

    def test_bounding_box_follows_the_model(self):
        bb = refgeom.create_bounding_box(self.doc, self.part)
        self.doc.recompute()
        self.ok(bb)
        self.assertAlmostEqual(bb.Length.Value, 20, 6)
        self.assertAlmostEqual(bb.Width.Value, 10, 6)
        self.assertAlmostEqual(bb.Thickness.Value, 5, 6)
        self.assertEqual(len(bb.Shape.Edges), 12)
        self.box.Depth = 8
        self.doc.recompute()
        self.ok(bb)
        self.assertAlmostEqual(bb.Width.Value, 10, 6)
        self.assertAlmostEqual(bb.Thickness.Value, 8, 6)
        self.assertAlmostEqual(bb.BoxVolume.Value, 20 * 10 * 8, 4)

    def test_bounding_box_turned_body_and_plane(self):
        sk = sketch(self.doc, plane(self.part, "Front Plane"))
        sk.addGeometry(Part.LineSegment(V(30, 0, 0), V(60, 20, 0)))
        sk.addGeometry(Part.LineSegment(V(60, 20, 0), V(57, 24.5, 0)))
        sk.addGeometry(Part.LineSegment(V(57, 24.5, 0), V(27, 4.5, 0)))
        sk.addGeometry(Part.LineSegment(V(27, 4.5, 0), V(30, 0, 0)))
        self.doc.recompute()
        bar = extrude(self.doc, self.part, sk, Depth=6, MergeResult=False)
        ids = list(self.part.BodyIds)
        bb = refgeom.create_bounding_box(self.doc, self.part, bodies=[ids[-1]])
        self.doc.recompute()
        self.ok(bb)
        side = math.hypot(30, 20)
        self.assertAlmostEqual(bb.Length.Value, side, 3)          # best fit: along the bar
        self.assertAlmostEqual(bb.Width.Value, 6, 3)
        self.assertAlmostEqual(bb.Thickness.Value, math.hypot(3, 4.5), 3)
        top = app_part.origin_feature(self.part, "Top Plane")
        bb.Type = core.REFERENCE_PLANE
        refgeom.refs.set_ref(bb, "Reference1", top, "")
        self.doc.recompute()
        self.ok(bb)
        # Square to the top plane: the bar's height and its footprint.
        self.assertAlmostEqual(bb.Length.Value, 33, 3)
        self.assertAlmostEqual(bb.Width.Value, 24.5, 3)
        self.assertAlmostEqual(bb.Thickness.Value, 6, 3)
        del bar

    def test_centre_of_mass(self):
        com = refgeom.create_centre_of_mass(self.doc, self.part)
        self.doc.recompute()
        self.ok(com)
        self.assertTrue((com.Shape.Vertexes[0].Point - V(10, 5, 2.5)).Length < 1e-6)
        self.box.Depth = 9
        self.doc.recompute()
        self.ok(com)
        self.assertTrue((com.Shape.Vertexes[0].Point - V(10, 5, 4.5)).Length < 1e-6)
        self.assertEqual(com.Proxy.KIND, "point")                 # usable as a point


    def test_cosmetic_thread(self):
        from freecad.SolidDesign.core import threads
        sk = sketch(self.doc, plane(self.part, "Top Plane"),
                    attach_offset=App.Placement(V(0, 0, 5), App.Rotation()))
        sk.addGeometry(Part.Circle(V(10, 5, 0), V(0, 0, 1), 5))       # an M10 shaft
        self.doc.recompute()
        shaft = extrude(self.doc, self.part, sk, Depth=20)
        top = next(i for i, e in enumerate(shaft.Shape.Edges, 1)
                   if hasattr(e.Curve, "Radius") and abs(e.Curve.Center.z - 25) < 1e-6)
        ct = refgeom.create_cosmetic_thread(self.doc, self.part, (shaft, "Edge%d" % top),
                                            Length=12, ThreadClass="6g")
        self.doc.recompute()
        self.ok(ct)
        self.assertEqual(ct.Size, "M10")
        self.assertAlmostEqual(ct.Diameter.Value, threads.minor(10, 1.5), 6)
        self.assertIn("M10 - 6g", ct.Callout)
        bb = ct.Shape.BoundBox
        self.assertAlmostEqual(bb.ZMax, 25, 6)
        self.assertAlmostEqual(bb.ZMin, 13, 6)                  # 12 down the shaft
        volume = sum(s.Volume for s in self.part.Shape.Solids)
        ct.Type = "Up To Next"
        self.doc.recompute()
        self.ok(ct)
        self.assertAlmostEqual(ct.Shape.BoundBox.ZMin, 5, 6)   # the whole shaft
        self.assertAlmostEqual(sum(s.Volume for s in self.part.Shape.Solids), volume, 6)


REEXPORTED = (Part,)


class TestPlaneConstraints(unittest.TestCase):
    """SolidWorks' Plane: up to three references, each with a constraint, guessed
    from what was picked and changeable; the order they were picked in doesn't
    matter. A 20 x 10 x 5 block from the origin."""

    def setUp(self):
        self.doc, self.part = new_doc("RefC")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 20, 10)
        self.doc.recompute()
        self.box = extrude(self.doc, self.part, sk, Depth=5)
        b = self.box
        self.top = (b, face_at(b, V(10, 5, 5), V(0, 0, 1)))
        self.bottom = (b, face_at(b, V(10, 5, 0), V(0, 0, -1)))
        self.side = (b, face_at(b, V(20, 5, 2.5), V(1, 0, 0)))
        self.front = (b, face_at(b, V(10, 0, 2.5), V(0, -1, 0)))
        self.edge_x = (b, edge_at(b, V(10, 0, 5)))          # along X, front top
        self.edge_up = (b, edge_at(b, V(20, 0, 2.5)))       # upright, front right

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def vtx(self, p):
        return (self.box, vertex_at(self.box, p))

    def make(self, refs, cons=(), **props):
        p = refgeom.create_plane(self.doc, self.part, None, refs, cons)
        for k, v in props.items():
            setattr(p, k, v)
        self.doc.recompute()
        return p

    def face(self, p):
        self.assertEqual(p.ErrorMessage, "", p.ErrorMessage)
        f = p.Shape.Faces[0]
        n = f.normalAt(0, 0)
        return f, n

    def guessed(self, refs):
        shapes = [Part.getShape(o, s, needSubElement=True) if s else o.Shape for o, s in refs]
        return core.guess(shapes)

    # ---- guessing, as SolidWorks starts each combination
    def test_guesses(self):
        g = self.guessed
        self.assertEqual(g([self.top]), [core.C_OFFSET])
        self.assertEqual(g([self.top, self.bottom]), [core.C_MID, core.C_MID])
        self.assertEqual(g([self.edge_x, self.top]), [core.C_COINCIDENT, core.C_ANGLE])
        self.assertEqual(g([self.vtx(V(20, 10, 5)), (plane(self.part, "Top Plane"), "")]),
                         [core.C_COINCIDENT, core.C_PARALLEL])
        pts = [self.vtx(V(0, 0, 5)), self.vtx(V(20, 0, 5)), self.vtx(V(0, 10, 0))]
        self.assertEqual(g(pts), [core.C_COINCIDENT] * 3)
        # A point on the edge: square to it there; off it: through both.
        self.assertEqual(g([self.edge_x, self.vtx(V(20, 0, 5))]),
                         [core.C_PERPENDICULAR, core.C_COINCIDENT])
        self.assertEqual(g([self.edge_x, self.vtx(V(20, 10, 0))]),
                         [core.C_COINCIDENT, core.C_COINCIDENT])
        # A plane and two points: square to the plane, through the points.
        self.assertEqual(g([self.top, self.vtx(V(0, 0, 5)), self.vtx(V(20, 10, 5))]),
                         [core.C_PERPENDICULAR, core.C_COINCIDENT, core.C_COINCIDENT])

    # ---- the planes the guesses make
    def test_one_face_offsets_it(self):
        f, n = self.face(self.make([self.top], Distance=7))
        self.assertAlmostEqual(f.CenterOfMass.z, 12)

    def test_face_and_point_parallel_through_it(self):
        f, n = self.face(self.make([(plane(self.part, "Top Plane"), ""),
                                    self.vtx(V(20, 10, 5))]))
        self.assertAlmostEqual(f.CenterOfMass.z, 5)
        self.assertAlmostEqual(abs(n.z), 1)

    def test_picked_in_any_order(self):
        """Edge then face is the same At Angle plane as face then edge."""
        a = self.make([self.top, self.edge_x], Angle=90)
        b = self.make([self.edge_x, self.top], Angle=90)
        _f, na = self.face(a)
        _f, nb = self.face(b)
        self.assertAlmostEqual(abs(na.y), 1, 6)
        self.assertAlmostEqual(abs(na.dot(nb)), 1, 6)

    def test_three_points(self):
        pts = [self.vtx(V(0, 0, 5)), self.vtx(V(20, 0, 5)), self.vtx(V(0, 10, 0))]
        f, n = self.face(self.make(pts))
        for p in (V(0, 0, 5), V(20, 0, 5), V(0, 10, 0)):
            self.assertAlmostEqual(f.Surface.projectPoint(p).distanceToPoint(p), 0, 6)

    def test_normal_to_edge_at_point(self):
        f, n = self.face(self.make([self.edge_x, self.vtx(V(20, 0, 5))]))
        self.assertAlmostEqual(abs(n.x), 1, 6)
        self.assertAlmostEqual(f.Surface.Position.x if hasattr(f.Surface, "Position")
                               else f.CenterOfMass.x, 20, 6)

    def test_through_edge_and_point(self):
        """The diagonal plane through the front top edge and the back bottom corner."""
        f, n = self.face(self.make([self.edge_x, self.vtx(V(20, 10, 0))]))
        for p in (V(0, 0, 5), V(20, 0, 5), V(20, 10, 0)):
            self.assertAlmostEqual(f.Surface.projectPoint(p).distanceToPoint(p), 0, 6)

    def test_two_faces_that_meet_halve_the_corner(self):
        """Mid Plane of the top and the right side: through their edge, at 45°,
        into the block."""
        f, n = self.face(self.make([self.top, self.side]))
        self.assertAlmostEqual(abs(n.x), math.sqrt(0.5), 6)
        self.assertAlmostEqual(abs(n.z), math.sqrt(0.5), 6)
        for p in (V(20, 0, 5), V(20, 10, 5), V(17, 5, 2)):
            self.assertAlmostEqual(f.Surface.projectPoint(p).distanceToPoint(p), 0, 6)

    def test_square_to_face_through_two_points(self):
        f, n = self.face(self.make([self.top, self.vtx(V(0, 0, 5)), self.vtx(V(20, 10, 5))]))
        self.assertAlmostEqual(n.z, 0, 6)
        self.assertAlmostEqual(f.Surface.projectPoint(V(20, 10, 0)).distanceToPoint(
            V(20, 10, 0)), 0, 6)

    def test_changed_constraint_is_kept(self):
        """Top face set to Coincident instead of the guessed Offset."""
        p = self.make([self.top], [core.C_COINCIDENT])
        f, n = self.face(p)
        self.assertAlmostEqual(f.CenterOfMass.z, 5)
        self.assertEqual(p.Proxy.constraints(p), [core.C_COINCIDENT])

    def test_a_constraint_that_doesnt_fit_is_guessed_again(self):
        """Mid Plane left over from a face, now that a point is there instead."""
        p = self.make([self.vtx(V(20, 10, 5)), self.top], [core.C_MID, ""])
        self.face(p)
        self.assertEqual(p.Proxy.constraints(p), [core.C_COINCIDENT, core.C_PARALLEL])

    def test_tangent_to_a_cylinder(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        sk.addGeometry(Part.Circle(V(40, 0, 0), V(0, 0, 1), 4))
        self.doc.recompute()
        cyl = extrude(self.doc, self.part, sk, Depth=10)
        round_face = (cyl, face_at(cyl, V(44, 0, 5), V(1, 0, 0)))
        f, n = self.face(self.make([round_face, (plane(self.part, "Right Plane"), "")]))
        self.assertAlmostEqual(abs(n.x), 1, 6)
        self.assertAlmostEqual(abs(f.CenterOfMass.x - 40), 4, 6)
        far = self.make([round_face, (plane(self.part, "Right Plane"), "")], Flip=True)
        g, _n = self.face(far)
        self.assertAlmostEqual(f.CenterOfMass.x + g.CenterOfMass.x, 80, 6)
        # Through a point outside it: touches the cylinder.
        t = self.make([round_face, self.vtx(V(20, 0, 5))])
        h, m = self.face(t)
        c = V(40, 0, 5)
        self.assertAlmostEqual(abs((c - h.Surface.projectPoint(c)).Length), 4, 6)

    def test_what_is_wrong_is_said(self):
        p = self.make([self.vtx(V(0, 0, 5)), self.vtx(V(20, 0, 5))])
        self.assertIn("three points", p.ErrorMessage)
        p = self.make([self.top, self.side], [core.C_PARALLEL, core.C_PARALLEL])
        self.assertIn("different directions", p.ErrorMessage)
        p = self.make([self.top, self.edge_x], [core.C_OFFSET, core.C_COINCIDENT])
        self.assertIn("don't lie in one plane", p.ErrorMessage)
        p = self.make([self.top, self.bottom, self.vtx(V(0, 0, 0))],
                      [core.C_ANGLE, core.C_OFFSET, core.C_COINCIDENT])
        self.assertIn("Only one reference", p.ErrorMessage)

    def test_old_types_read_as_constraints(self):
        a = refgeom.create_plane(self.doc, self.part, core.ANGLE, [self.top, self.edge_x])
        self.doc.recompute()
        self.assertEqual(a.Proxy.constraints(a), [core.C_ANGLE, core.C_COINCIDENT])
        # The same plane made either way.
        b = self.make([self.top, self.edge_x], list(core.FROM_TYPE[core.ANGLE]))
        fa, na = self.face(a)
        fb, nb = self.face(b)
        self.assertAlmostEqual(na.dot(nb), 1, 9)
        q = fb.CenterOfMass
        self.assertAlmostEqual(fa.Surface.projectPoint(q).distanceToPoint(q), 0, 9)
