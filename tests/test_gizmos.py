# SPDX-License-Identifier: LGPL-2.1-or-later
"""Where each tool's gizmos go (gui/handles.py specs), checked without a view."""

import math
import unittest

import FreeCAD as App
import Part

from freecad.SolidDesign.app import bodytools, dressup, faceops, pattern, refgeom, rib
from freecad.SolidDesign.app import morefeatures as more
from freecad.SolidDesign.app import refs, surfaces, thread as app_thread
from freecad.SolidDesign.app import surfaces2 as s2
from freecad.SolidDesign.core import curves, refgeom as core_ref
from freecad.SolidDesign.gui import handles
from helpers import V, circle, extrude, face_at, new_doc, plane, rect, sketch


def edges_at(obj, z):
    return ["Edge%d" % i for i, e in enumerate(obj.Shape.Edges, 1)
            if abs(e.BoundBox.ZMin - z) < 1e-6 and abs(e.BoundBox.ZMax - z) < 1e-6]


class Case(unittest.TestCase):
    """A 20 x 10 x 10 box from the origin."""

    def setUp(self):
        self.doc, self.part = new_doc("Gz")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 20, 10)
        self.doc.recompute()
        self.box = extrude(self.doc, self.part, sk, Depth=10)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)

    def specs(self, obj):
        key = handles.spec_key(obj)
        self.assertIn(key, handles.SPECS)
        return {s.prop: s for s in handles.SPECS[key](obj, self.part)}

    def vec(self, a, b, places=6):
        for x, y in zip(a, b):
            self.assertAlmostEqual(x, y, places)

    def top(self):
        return face_at(self.box, V(10, 5, 10), V(0, 0, 1))


class TestFeatures(Case):
    def test_dome_height_out_of_the_face(self):
        d = more.create_dome(self.doc, self.part, Items=[self.top()], Distance=4)
        self.doc.recompute()
        s = self.specs(d)["Distance"]
        self.assertEqual(s.kind, "arrow")
        self.vec(s.origin, (10, 5, 10))
        self.vec(s.direction, (0, 0, 1))
        self.assertAlmostEqual(s.value, 4)
        d.ReverseDirection = True
        self.doc.recompute()
        self.vec(self.specs(d)["Distance"].direction, (0, 0, -1))

    def test_draft_angle_arc_on_the_face(self):
        side = face_at(self.box, V(10, 0, 5), V(0, -1, 0))
        d = dressup.create_draft(self.doc, self.part, [side])
        refs.set_ref(d, "NeutralPlane", self.box,
                     [face_at(self.box, V(10, 5, 0), V(0, 0, -1))])
        d.Angle = 3
        self.doc.recompute()
        s = self.specs(d)["Angle"]
        self.assertEqual(s.kind, "angle")
        self.vec(s.origin, (10, 0, 5))
        self.vec(s.ref, (0, 0, 1))                 # pull: up from the bottom plane
        self.assertAlmostEqual(abs(s.direction.x), 1.0)
        self.assertAlmostEqual(s.value, 3)
        # Leaning the ball by the angle takes it off the face (out of the part).
        lean = App.Rotation(s.direction, 10).multVec(s.ref)
        self.assertLess(lean.y, 0)

    def test_variable_fillet_radii_at_the_edge_ends(self):
        e = [n for n in edges_at(self.box, 10)
             if abs(self.box.Shape.getElement(n).BoundBox.YMin) < 1e-6][0]
        f = dressup.create_fillet(self.doc, self.part, [e])
        f.FilletType = "Variable Size"
        f.StartRadius, f.EndRadius = 1, 3
        self.doc.recompute()
        sp = self.specs(f)
        self.assertEqual(sorted(sp), ["EndRadius", "StartRadius"])
        a, b = sp["StartRadius"], sp["EndRadius"]
        self.assertEqual(a.kind, "radial")
        self.assertAlmostEqual(abs(a.origin.x - b.origin.x), 20)
        self.assertAlmostEqual((a.value, b.value), (1, 3))
        f.ReverseVariable = True
        self.doc.recompute()
        sp = self.specs(f)
        self.vec(sp["EndRadius"].origin, a.origin)

    def test_extrude_from_offset_then_depth(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 5, 5)
        self.doc.recompute()
        e = extrude(self.doc, self.part, sk, From="Offset", FromOffset=12, Depth=3)
        sp = self.specs(e)
        self.vec(sp["FromOffset"].origin, (2.5, 2.5, 0))
        self.vec(sp["FromOffset"].direction, (0, 0, 1))
        self.vec(sp["Depth"].origin, (2.5, 2.5, 12))

    def test_rib_thickness_across_its_line(self):
        sk = sketch(self.doc, plane(self.part, "Front Plane"),
                    attach_offset=App.Placement(V(0, 0, -5), App.Rotation()))
        sk.addGeometry(Part.LineSegment(V(5, 10, 0), V(15, 20, 0)))
        self.doc.recompute()
        r = rib.create(self.doc, self.part, sketch=sk)
        r.Thickness = 2
        self.doc.recompute()
        s = self.specs(r)["Thickness"]
        self.assertAlmostEqual(s.factor, 2.0)          # Both Sides
        line = sk.getGlobalPlacement().Rotation.multVec(V(1, 1, 0).normalize())
        self.assertAlmostEqual(s.direction.dot(line), 0.0)       # square to the line
        self.assertAlmostEqual(s.direction.y, 0.0)               # in the sketch plane
        r.ThicknessSide = "First Side"
        self.doc.recompute()
        self.assertAlmostEqual(self.specs(r)["Thickness"].factor, 1.0)

    def test_thread_offset_and_length_along_the_shaft(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"),
                    attach_offset=App.Placement(V(0, 0, 10), App.Rotation()))
        circle(sk, 10, 5, 3)
        self.doc.recompute()
        shaft = extrude(self.doc, self.part, sk, Depth=20)
        rim = next("Edge%d" % i for i, e in enumerate(shaft.Shape.Edges, 1)
                   if hasattr(e.Curve, "Radius") and abs(e.Curve.Center.z - 30) < 1e-6)
        t = app_thread.create(self.doc, self.part, (shaft, rim))
        t.Length = 8
        t.Offset, t.OffsetDistance = True, 2
        self.doc.recompute()
        sp = self.specs(t)
        self.vec(sp["OffsetDistance"].origin, (10, 5, 30))
        self.vec(sp["Length"].origin, (10, 5, 28))
        self.vec(sp["Length"].direction, (0, 0, -1))
        self.assertAlmostEqual(sp["Length"].value, 8)


class TestPatternsAndBodies(Case):
    def test_linear_pattern_spacing_from_the_seed(self):
        f = pattern.create_linear(self.doc, self.part, Bodies=list(self.part.BodyIds),
                                  Spacing=30, Instances=3)
        f.Direction1Ref = (plane(self.part, "X Axis"), [])
        self.doc.recompute()
        s = self.specs(f)["Spacing"]
        self.vec(s.origin, (10, 5, 5))
        self.vec(s.direction, (1, 0, 0))
        self.assertAlmostEqual(s.value, 30)

    def test_circular_pattern_ring_through_the_seed(self):
        f = pattern.create_circular(self.doc, self.part, Bodies=list(self.part.BodyIds),
                                    Angle=90, Instances=4)
        f.Axis = (plane(self.part, "Z Axis"), [])
        self.doc.recompute()
        s = self.specs(f)["Angle"]
        self.assertEqual(s.kind, "ring")
        self.vec(s.origin, (0, 0, 5))
        self.assertAlmostEqual(s.radius, math.hypot(10, 5))

    def test_move_copy_deltas_may_go_negative(self):
        ids = list(self.part.BodyIds)
        m = bodytools.create_move(self.doc, self.part, Bodies=ids, DeltaX=-4)
        sp = self.specs(m)
        self.assertEqual(sorted(sp), ["DeltaX", "DeltaY", "DeltaZ"])
        self.assertIsNone(sp["DeltaX"].lo)
        self.assertAlmostEqual(sp["DeltaX"].value, -4)
        self.vec(sp["DeltaX"].origin, (10, 5, 5))
        m.RotateReference = (plane(self.part, "Z Axis"), [])
        m.Angle = 30
        self.doc.recompute()
        self.assertEqual(self.specs(m)["Angle"].kind, "ring")

    def test_move_face_offset(self):
        m = faceops.create_move_face(self.doc, self.part, [self.top()])
        m.Distance = 2
        self.doc.recompute()
        s = self.specs(m)["Distance"]
        self.vec(s.origin, (10, 5, 10))
        self.vec(s.direction, (0, 0, 1))


class TestSurfacesAndReference(Case):
    def flat(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"),
                    attach_offset=App.Placement(V(0, 0, 30), App.Rotation()))
        rect(sk, 0, 0, 20, 10)
        self.doc.recompute()
        pl = surfaces.create_planar(self.doc, self.part, Sketch=sk)
        self.doc.recompute()
        sid = [i for i, k in zip(self.part.BodyIds, self.part.BodyKinds) if k == "surface"][0]
        return pl, sid

    def test_offset_surface_signed(self):
        f = faceops.create_offset_surface(self.doc, self.part, [self.top()])
        f.Distance = -3
        self.doc.recompute()
        s = self.specs(f)["Distance"]
        self.assertIsNone(s.lo)
        self.vec(s.direction, (0, 0, 1))
        self.assertAlmostEqual(s.value, -3)

    def test_thicken_along_the_sheet(self):
        _pl, sid = self.flat()
        t = surfaces.create_thicken(self.doc, self.part, Body=sid, Thickness=2)
        self.doc.recompute()
        s = self.specs(t)["Thickness"]
        self.assertAlmostEqual(abs(s.direction.z), 1.0)
        self.assertAlmostEqual(s.origin.z, 30)
        t.ThickenSide = "Both Sides"
        self.doc.recompute()
        self.assertAlmostEqual(self.specs(t)["Thickness"].factor, 2.0)

    def test_extend_out_past_the_edge(self):
        pl, _sid = self.flat()
        e = [n for n in edges_at(pl, 30)
             if abs(pl.Shape.getElement(n).CenterOfMass.x - 20) < 1e-6][0]
        x = surfaces.create_extend(self.doc, self.part, Items=[e], Distance=5)
        self.doc.recompute()
        s = self.specs(x)["Distance"]
        self.vec(s.origin, (20, 5, 30))
        self.vec(s.direction, (1, 0, 0))

    def test_radiate_out_across_the_new_flange(self):
        one = [n for n in edges_at(self.box, 10)
               if abs(self.box.Shape.getElement(n).CenterOfMass.y) < 1e-6]
        rd = s2.create_radiate(self.doc, self.part, Items=one, Distance=2)
        rd.ReferencePlane = (plane(self.part, "Top Plane"), [])
        self.doc.recompute()
        self.ok(rd)
        s = self.specs(rd)["Distance"]
        self.vec(s.origin, (10, 0, 10))
        self.vec(s.direction, (0, -1, 0))

    def test_offset_plane_from_its_reference(self):
        p = refgeom.create_plane(self.doc, self.part, core_ref.OFFSET, [(self.box, self.top())])
        p.Distance = 10
        self.doc.recompute()
        s = self.specs(p)["Distance"]
        self.assertAlmostEqual(s.origin.z, 10)
        self.vec(s.direction, (0, 0, 1))
        self.assertAlmostEqual(s.value, 10)

    def test_helix_height_along_its_axis(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        circle(sk, 0, 0, 10)
        self.doc.recompute()
        h = refgeom.create_helix(self.doc, self.part, None, [(sk, "")])
        h.Type = curves.HEIGHT_PITCH
        h.Height = 30
        self.doc.recompute()
        s = self.specs(h)["Height"]
        self.vec(s.origin, (0, 0, 0))
        self.assertAlmostEqual(abs(s.direction.z), 1.0)
        self.assertAlmostEqual(s.value, 30)

    def test_cosmetic_thread_length_down_the_shaft(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"),
                    attach_offset=App.Placement(V(0, 0, 10), App.Rotation()))
        circle(sk, 10, 5, 5)
        self.doc.recompute()
        shaft = extrude(self.doc, self.part, sk, Depth=20)
        top = next(i for i, e in enumerate(shaft.Shape.Edges, 1)
                   if hasattr(e.Curve, "Radius") and abs(e.Curve.Center.z - 30) < 1e-6)
        ct = refgeom.create_cosmetic_thread(self.doc, self.part, (shaft, "Edge%d" % top),
                                            Length=12)
        self.doc.recompute()
        s = self.specs(ct)["Length"]
        self.vec(s.origin, (10, 5, 30))
        self.vec(s.direction, (0, 0, -1))
        self.assertAlmostEqual(s.value, 12)

    def test_every_spec_copes_with_an_empty_feature(self):
        """A tool just made (nothing picked yet) shows no gizmos and doesn't fail."""
        made = [more.create_dome(self.doc, self.part), more.create_wrap(self.doc, self.part),
                dressup.create_draft(self.doc, self.part),
                dressup.create_fillet(self.doc, self.part),
                faceops.create_offset_surface(self.doc, self.part),
                faceops.create_move_face(self.doc, self.part),
                pattern.create_linear(self.doc, self.part),
                pattern.create_circular(self.doc, self.part),
                surfaces.create_thicken(self.doc, self.part),
                surfaces.create_extend(self.doc, self.part),
                s2.create_ruled(self.doc, self.part), s2.create_radiate(self.doc, self.part),
                refgeom.create_plane(self.doc, self.part, core_ref.OFFSET)]
        self.doc.recompute()
        for f in made:
            self.assertEqual(self.specs(f), {}, f.Label)


if __name__ == "__main__":
    unittest.main()
