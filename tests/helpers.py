# SPDX-License-Identifier: LGPL-2.1-or-later
"""Helpers for the headless tests (run in freecadcmd)."""

import FreeCAD as App
import Part
import Sketcher

from freecad.SolidDesign.app import extrude as app_extrude
from freecad.SolidDesign.app import part as app_part

V = App.Vector


def new_doc(name="T"):
    for d in list(App.listDocuments().values()):
        if d.Name == name:
            App.closeDocument(name)
    doc = App.newDocument(name)
    part = app_part.create(doc)
    return doc, part


def plane(part, name):
    for o in part.Origin:
        if app_part.clean_label(o.Label) == name:
            return o
    raise KeyError(name)


def sketch(doc, support, mapmode="FlatFace", label=None, attach_offset=None):
    sk = doc.addObject("Sketcher::SketchObject", "Sketch")
    if label:
        sk.Label = label
    obj, sub = support if isinstance(support, tuple) else (support, "")
    sk.AttachmentSupport = [(obj, sub)]
    sk.MapMode = mapmode
    if attach_offset is not None:
        sk.AttachmentOffset = attach_offset
    return sk


def rect(sk, x0, y0, x1, y1, constrain=False):
    pts = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
    first = len(sk.Geometry)
    for i in range(4):
        sk.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]))
    for i in range(4):
        sk.addConstraint(Sketcher.Constraint("Coincident", first + i, 2, first + (i + 1) % 4, 1))
    if constrain:
        sk.addConstraint(Sketcher.Constraint("Horizontal", first))
        sk.addConstraint(Sketcher.Constraint("Horizontal", first + 2))
        sk.addConstraint(Sketcher.Constraint("Vertical", first + 1))
        sk.addConstraint(Sketcher.Constraint("Vertical", first + 3))
        sk.addConstraint(Sketcher.Constraint("DistanceX", first, 1, first, 2, x1 - x0))
        sk.addConstraint(Sketcher.Constraint("DistanceY", first + 1, 1, first + 1, 2, y1 - y0))
    return list(range(first, first + 4))


def circle(sk, cx, cy, r):
    return sk.addGeometry(Part.Circle(V(cx, cy, 0), V(0, 0, 1), r))


def extrude(doc, part, sk, mode="Add", **props):
    f = app_extrude.create(doc, part, mode, sk)
    for k, v in props.items():
        setattr(f, k, v)
    doc.recompute()
    return f


def volumes(part):
    bs = app_part.tip_bodies(part)
    return {b.id: round(b.shape.Volume, 4) for b in bs}


def face_at(obj, point, normal=None):
    """Name of the face of ``obj`` that contains ``point``."""
    for i, f in enumerate(obj.Shape.Faces, 1):
        if f.isInside(point, 1e-6, True):
            if normal is None:
                return "Face%d" % i
            u, v = f.Surface.parameter(point)
            if f.normalAt(u, v).getAngle(normal) < 1e-6:
                return "Face%d" % i
    raise AssertionError("no face at %s" % point)
