# Solid Design

A FreeCAD workbench that models parts the SolidWorks way, multi-body from the start.
The brief is `SOLID_DESIGN_SPEC.md` (kept by the owner). This README is for
development only; user docs come after the owner has tested each feature.

## Status

- **P0 foundations:** done. Part with origin and body folders; body sets with
  stable body IDs; rollback bar; the tagged TopoShape layer (`core/topo.py`) and
  reference storage with fingerprint repair; sketch regions; the shared panel
  framework and live preview.
- **P1:** all tools built, each with its panel, preview, tree entry and tests:
  Extrude and Revolve (Add | Cut), Fillet (constant radius), Chamfer, Hole Wizard
  (basic: Counterbore, Countersink, Hole, Straight Tap; ISO metric; Blind or
  Through All), Linear and Circular Pattern, Mirror (features and bodies),
  Reference Plane and Axis, Combine, Split, Delete/Keep Body, Move/Copy Body.
  Move/Copy Body has both modes (Translate/Rotate and Constraints).
- **P2:** Sweep and Loft (Add | Cut), Shell (with multi-thickness), surface
  bodies from open sketches (Extrude, Sweep), Draft (Neutral Plane, Parting
  Line), Rib, reference Point and Coordinate System, Helix/Spiral, Thread, full
  Hole Wizard (ISO and ANSI Inch, slots, all end conditions, options, modelled
  threads), Fillet (Variable Size, Face, Full Round), Offset Surface, Move Face,
  Split Line, Step Draft, Rib Natural type and draft, Instant3D drag handles
  (Extrude arrows, Revolve rings, on-screen values; also on a selected feature).
- **P3, next:** Boundary, Advanced Hole, the other patterns, Wrap, Dome,
  Intersect, the rest of Curves, surface tools, a context toolbar.

## Install for development

Link the repo into FreeCAD's user Mod folder (FreeCAD 1.1):

    ln -s "$PWD" ~/.local/share/FreeCAD/v1-1/Mod/SolidDesign

## Tests

Headless (geometry, document, topological naming):

    freecadcmd tests/run.py
    SD_TESTS=test_naming freecadcmd tests/run.py        # one module

GUI smoke tests on a virtual display; screenshots go to `$SD_SHOTS`
(default `/tmp/sd_shots`, `/tmp/sd_tools`) and should be looked at:

    xvfb-run -a -s "-screen 0 1600x1000x24" freecad tests/gui/smoke.py
    xvfb-run -a -s "-screen 0 1600x1000x24" freecad tests/gui/smoke_tools.py

## Layout

    freecad/SolidDesign/
      init_gui.py      workbench, toolbars, menus
      core/            geometry only (no FreeCADGui, no Qt)
        topo.py        the only module that calls shape operations
        bodies.py      body sets, IDs, ID rules
        regions.py     sketch regions for Selected Contours
        features/      one module per feature: compute(params, body_set)
      app/             document objects (no Qt)
      gui/             panels, panel framework, view providers, previews
        panel/parts.py the parts every panel is built from (groups, rows,
                       selection boxes); panel/base.py the panel base class
    tests/             headless tests; tests/gui for the GUI smoke test
    tools/make_icons.py  regenerates the SVG icons
    tools/panel_mockup.py  renders the panel parts in FreeCAD's task view
    docs/_notes/       unpublished notes (UX departures for the owner to review)
