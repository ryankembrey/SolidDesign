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


REEXPORTED = (Part,)
