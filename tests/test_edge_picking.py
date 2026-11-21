# SPDX-License-Identifier: LGPL-2.1-or-later
"""Select Tangency, Select Loop and Select Chain: the edges that go with one
picked edge."""

import unittest

import FreeCAD as App
import Part

from freecad.SolidDesign.core.features import edges as E

V = App.Vector


def edge(shape, p0, p1):
    for e in shape.Edges:
        a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
        if ((a - p0).Length < 1e-6 and (b - p1).Length < 1e-6) or \
                ((a - p1).Length < 1e-6 and (b - p0).Length < 1e-6):
            return e
    raise AssertionError((p0, p1))


class TestEdgePicking(unittest.TestCase):
    def test_tangency_round_a_filleted_corner(self):
        box = Part.makeBox(40, 30, 10)
        filleted = box.makeFillet(3, [x for x in box.Edges
                                      if abs(x.CenterOfMass.z - 5) < 1e-6])
        top = [x for x in filleted.Edges if abs(x.CenterOfMass.z - 10) < 1e-6]
        names = E.select_tangency(filleted, top[0])
        self.assertEqual(len(names), 8, names)          # 4 straight + 4 round, all the way

    def test_loop_of_each_face(self):
        box = Part.makeBox(40, 30, 10)
        e = edge(box, V(0, 0, 10), V(40, 0, 10))       # front top
        loops = E.face_loops(box, e)
        self.assertEqual(len(loops), 2)
        self.assertTrue(all(len(names) == 4 for _f, names in loops))
        normals = sorted(tuple(round(c) for c in f.normalAt(0, 0)) for f, _n in loops)
        self.assertEqual(normals, [(0, -1, 0), (0, 0, 1)])

    def test_loop_round_a_hole(self):
        plate = Part.makeBox(40, 30, 10).cut(Part.makeCylinder(5, 10, V(20, 15, 0)))
        rim = [x for x in plate.Edges if x.Curve.TypeId == "Part::GeomCircle" and
               abs(x.CenterOfMass.z - 10) < 1e-6]
        loops = E.face_loops(plate, rim[0])
        top = [names for f, names in loops if abs(f.normalAt(0, 0).z - 1) < 1e-6
               if f.Surface.TypeId == "Part::GeomPlane"]
        self.assertEqual(len(top), 1)
        self.assertEqual(len(top[0]), len(rim))         # the hole's rim, not the outline

    def test_chain_round_an_open_edge(self):
        """An open box (five faces): its rim is one closed chain of open edges."""
        box = Part.makeBox(40, 30, 10)
        shell = Part.Shell([f for f in box.Faces if abs(f.CenterOfMass.z - 10) > 1e-6])
        e = edge(shell, V(0, 0, 10), V(40, 0, 10))
        names, closed = E.select_chain(shell, e)
        self.assertEqual(len(names), 4)
        self.assertTrue(closed)
        # On a solid every vertex has three edges: the chain stops at once.
        names, closed = E.select_chain(box, edge(box, V(0, 0, 10), V(40, 0, 10)))
        self.assertEqual((len(names), closed), (1, False))

    def test_chain_of_a_wire(self):
        w = Part.makePolygon([V(0, 0, 0), V(10, 0, 0), V(10, 10, 0), V(20, 10, 0)])
        names, closed = E.select_chain(w, w.Edges[1])
        self.assertEqual((sorted(names), closed), (["Edge1", "Edge2", "Edge3"], False))
