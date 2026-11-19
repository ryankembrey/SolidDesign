# SPDX-License-Identifier: LGPL-2.1-or-later
"""Live preview drawn straight into the 3D view (spec section 8.2).

Previews are coin nodes, not document objects, so they never enter the undo
history or the file. Material a feature adds is transparent green, material it
removes transparent red, both with dashed edges; sketch regions are blue.
"""

import FreeCADGui as Gui
from pivy import coin

ADD_COLOR = (0.18, 0.72, 0.30)
CUT_COLOR = (0.88, 0.16, 0.16)
RESULT_TRANSPARENCY = 0.55
REGION_COLOR = (0.35, 0.60, 0.95)
REGION_PICKED = (0.20, 0.45, 0.95)
LABEL_COLOR = (0.10, 0.10, 0.10)
DASH = 0xF0F0                   # coin line pattern: 4 on, 4 off
ANGULAR = 0.14                  # radians (8 degrees), as the bodies are drawn


def _view():
    try:
        return Gui.ActiveDocument.ActiveView
    except Exception:
        return None


def deflection(shape):
    """Chord error for drawing *shape*: fine enough that holes and fillets read
    round (0.05 % of its size, as the bodies are drawn)."""
    return max(shape.BoundBox.DiagonalLength * 0.0005, 0.001)


def _triangles(shape, dfl):
    """(points, triangle index triples) for the faces of *shape*."""
    try:
        import MeshPart
        mesh = MeshPart.meshFromShape(Shape=shape, LinearDeflection=dfl,
                                      AngularDeflection=ANGULAR, Relative=False)
        pts, tris = mesh.Topology
        return [(p.x, p.y, p.z) for p in pts], [tuple(t) for t in tris]
    except Exception:
        pass
    pts, tris = [], []
    for f in shape.Faces:
        try:
            v, t = f.tessellate(dfl)
        except Exception:
            continue
        base = len(pts)
        pts.extend((p.x, p.y, p.z) for p in v)
        tris.extend((base + a, base + b, base + c) for a, b, c in t)
    return pts, tris


def result_node(shape, add=True):
    """What a feature adds (transparent green) or removes (transparent red),
    with dashed edges."""
    return shape_node(shape, ADD_COLOR if add else CUT_COLOR, RESULT_TRANSPARENCY,
                      dashed=True)


def shape_node(shape, color, transparency=0.0, edges=True, deflection_=None, line_width=2.0,
               dashed=False):
    """A coin separator drawing a Part shape's faces (and edges)."""
    sep = coin.SoSeparator()
    if shape is None or shape.isNull():
        return sep
    dfl = deflection_ or deflection(shape)
    mat = coin.SoMaterial()
    mat.diffuseColor.setValue(*color)
    mat.ambientColor.setValue(*color)
    mat.emissiveColor.setValue(color[0] * 0.25, color[1] * 0.25, color[2] * 0.25)
    mat.transparency.setValue(transparency)
    hints = coin.SoShapeHints()
    hints.vertexOrdering = coin.SoShapeHints.COUNTERCLOCKWISE
    hints.shapeType = coin.SoShapeHints.UNKNOWN_SHAPE_TYPE
    sep.addChild(hints)
    sep.addChild(mat)
    pick = coin.SoPickStyle()
    pick.style = coin.SoPickStyle.UNPICKABLE
    sep.addChild(pick)
    if transparency > 0:
        # Draw translucent previews last, without hiding what's behind them.
        sep.renderCaching = coin.SoSeparator.OFF
    pts, tris = _triangles(shape, dfl)
    if pts and tris:
        coords = coin.SoCoordinate3()
        faces = coin.SoIndexedFaceSet()
        idx = []
        for a, b, c in tris:
            idx.extend((a, b, c, -1))
        coords.point.setValues(0, len(pts), pts)
        faces.coordIndex.setValues(0, len(idx), idx)
        sep.addChild(coords)
        sep.addChild(faces)
    if edges and shape.Edges:
        esep = coin.SoSeparator()
        emat = coin.SoMaterial()
        emat.diffuseColor.setValue(color[0] * 0.55, color[1] * 0.55, color[2] * 0.55)
        emat.emissiveColor.setValue(color[0] * 0.55, color[1] * 0.55, color[2] * 0.55)
        emat.transparency.setValue(0.0 if dashed else min(transparency, 0.3))
        style = coin.SoDrawStyle()
        style.lineWidth = line_width
        if dashed:
            style.linePattern = DASH
        esep.addChild(emat)
        esep.addChild(style)
        lpts = []
        counts = []
        for e in shape.Edges:
            try:
                d = e.discretize(QuasiDeflection=dfl)
            except Exception:
                try:
                    d = e.discretize(Deflection=dfl)
                except Exception:
                    continue
            if len(d) < 2:
                continue
            lpts.extend((p.x, p.y, p.z) for p in d)
            counts.append(len(d))
        if lpts:
            ec = coin.SoCoordinate3()
            ec.point.setValues(0, len(lpts), lpts)
            ls = coin.SoLineSet()
            ls.numVertices.setValues(0, len(counts), counts)
            esep.addChild(ec)
            esep.addChild(ls)
        sep.addChild(esep)
    return sep


def label_node(text, point, color=LABEL_COLOR):
    sep = coin.SoSeparator()
    t = coin.SoTranslation()
    t.translation.setValue(point.x, point.y, point.z)
    mat = coin.SoMaterial()
    mat.diffuseColor.setValue(*color)
    font = coin.SoFont()
    font.size = 14
    txt = coin.SoText2()
    txt.string = text
    txt.justification = coin.SoText2.CENTER
    for n in (t, mat, font, txt):
        sep.addChild(n)
    return sep


class Preview(object):
    """A set of named preview layers in the active 3D view."""

    def __init__(self):
        self.root = coin.SoSeparator()
        self.layers = {}
        self.view = None

    def attach(self):
        v = _view()
        if v is None or self.view is v:
            return
        self.detach()
        self.view = v
        try:
            v.getSceneGraph().addChild(self.root)
        except Exception:
            self.view = None

    def detach(self):
        if self.view is not None:
            try:
                self.view.getSceneGraph().removeChild(self.root)
            except Exception:
                pass
        self.view = None

    def set(self, name, node):
        self.attach()
        old = self.layers.pop(name, None)
        if old is not None:
            self.root.removeChild(old)
        if node is not None:
            self.layers[name] = node
            self.root.addChild(node)

    def clear(self, name=None):
        if name is None:
            self.root.removeAllChildren()
            self.layers.clear()
        else:
            self.set(name, None)
