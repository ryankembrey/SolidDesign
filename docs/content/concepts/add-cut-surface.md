# Add, Cut and Surface

Each shape tool (Extrude, Revolve, Sweep, Loft, Boundary, Thicken) is one tool with buttons at the
top of its panel, instead of SolidWorks' separate Boss, Cut and Surface commands:

- **Add** grows material. The preview is green.
- **Cut** takes material away. The preview is red.
- **Surface** makes a surface body.

The tools open in **Add**; the surface tools in the **Surfaces** toolbar open the same tool in
**Surface**. Switch at any time, even while editing a feature later.

## Which bodies change

- **Add**: with **Merge result** on, the new shape joins the bodies it touches; off, it's a new
  body.
- **Cut**: **Feature Scope** decides which bodies are cut: all of them, or the ones you pick.
- **Surface**: always a new surface body.

## Colours

Previews say what will happen before you click OK: green for material added, red for material
removed. Even tools that only remove (Delete/Keep Body, a cut) show their effect in red.
