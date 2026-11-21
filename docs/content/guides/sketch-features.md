# Sketches and sketch features

Most parts are built from sketches: a 2D profile on a plane, turned into a solid by a feature.

## Starting a sketch

Select a plane or a flat face and click [Sketch](../reference/tools/sketch.md). With nothing
selected, Sketch shows the origin planes and asks you to click one.

The Sketcher is FreeCAD's own: draw, constrain, then click **Close**.

## From sketch to feature

| To | Use |
| :-- | :-- |
| Push a profile straight out (or cut it in) | [Extrude](../reference/tools/extrude.md) |
| Turn a profile round an axis | [Revolve](../reference/tools/revolve.md) |
| Move a profile along a path | [Sweep](../reference/tools/sweep.md) |
| Blend between profiles | [Loft](../reference/tools/loft.md) |
| Pass through a network of curves | [Boundary](../reference/tools/boundary.md) |
| Grow a wall from a line | [Rib](../reference/tools/rib.md) |

Each opens in **Add**. Press **Cut** to take material away, or **Surface** for a surface body:
see [Add, Cut and Surface](../concepts/add-cut-surface.md).

## Three ways to start a feature

- **Sketch first:** select the sketch, then click the tool.
- **Face first:** select a plane or face and click the tool. It starts a sketch there; when you
  close it, the feature opens with it.
- **Tool first:** click the tool with nothing selected. With one sketch not used yet, it takes
  that; otherwise it asks for one.

## Using part of a sketch

One sketch can drive several features. In the feature's **Selected Contours** box, click the
regions or curves to use; the rest of the sketch is left alone.

## Editing

Double-click a feature to change it. Its sketch is under it in the tree: right-click the sketch in
the 3D view or the tree for **Edit Sketch**.
