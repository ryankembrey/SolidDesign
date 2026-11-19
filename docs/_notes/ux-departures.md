# UX departures from SolidWorks (not published)

Each entry: the tool, what SolidWorks does, what Solid Design does instead, and why
(in terms of spec section 4.1). Names and results stay SolidWorks'. The owner can
overrule any entry.

## Owner decisions (2026-11-16)

- **One command per shape tool.** Spec 3.1 had toolbar/menu entries for each mode
  (Extruded Boss/Base and Extruded Cut). The owner decided against it: one
  *Extrude* (and one *Revolve*) command, opening in Add mode; Cut is chosen in the
  panel's Add | Cut switch.
- **No stylesheets in panels.** Panels take FreeCAD's theme. Where a state must
  stand out (the active selection box) the colour comes from the theme's palette.

## Owner decisions (2026-11-17): the standard panel

Approved from mockups rendered in OpenTheme (tools/panel_mockup.py). Every panel
is built from gui/panel/parts.py on the FeaturePanel base:

- Options sit in plain QGroupBoxes drawn by the theme, each a two-column grid
  with 1:1 column stretch (labels left, controls right).
- Optional groups (Direction 2, Thin Feature) are checkable group boxes;
  unchecked, their contents are hidden, as SolidWorks collapses them.
- Ordinary groups don't collapse (SolidWorks lets any group collapse). The
  one-line summaries of collapsed sections went with them.
- Every control has a tooltip: `row()`/`check()` refuse an empty one, and the GUI
  smoke tests fail on any control without one.
- Picks go in a SelectionField (one item, half width, in a row) or a
  SelectionList (several, across the group, in a group of its own titled with
  what it holds). The active box has a frame and light tint in the theme's
  selection colour, and its pick button stays pressed.
- Stylesheets only on two custom parts: the square icon buttons (`padding: 0`,
  as themes pad task-panel tool buttons until a 16 px icon is a dot) and the
  active selection box. A headless test fails on `setStyleSheet` anywhere else.
- Short field text ("No sketch", "Click a sketch"); the full sentence and the
  whole picked name are in the tooltip.
- References read "Face4 · Body 1" everywhere.

## Owner decisions (2026-11-17): icons and previews

- One isometric icon set, drawn by tools/make_icons.py: blue adds material, red
  removes it, grey is existing material, orange is reference geometry and
  accents, green is a surface body.
- The sketch tool uses the Sketcher workbench's icon; the body folders in the
  tree use FreeCAD's folder icon.
- No Roll to End command (toolbar or menu); it stays in the rollback bar's and
  features' context menus.
- Previews: material added is transparent green, material removed transparent
  red, both with dashed edges (SolidWorks uses yellow).
- Bodies are drawn finer than FreeCAD's default: deviation 0.05 %, angular
  deflection 8 degrees, set once per body so a value the user sets later stays.

## Behaviour added while using the workbench (2026-11-17)

These follow SolidWorks unless a line says otherwise.

- *Rollback* in a feature's context menu puts the bar just above it.
- Drop a feature on another in the tree to put it after that one.
- Delete on a body opens Delete/Keep Body with it picked.
- Deleting a feature relinks the next one without FreeCAD's "might break"
  warning.
- Hiding the Solid Bodies or Surface Bodies folder hides its bodies.
- Choosing Up To Surface, Vertex or Body makes that box the active one.
- Deleting a Part deletes everything in it (no SolidWorks equivalent).
- A second Part's planes are named "Top Plane" etc. too (an invisible character
  keeps FreeCAD's labels unique).
- After a cancelled feature, the next one reuses its number (FreeCAD keeps the
  old label reserved, so an invisible character is added).

## Owner's bug list (2026-11-17, evening)

- Plane has a *Coincident* type: exactly on the chosen face or plane.
- An axis is a dashed line drawn on top of the bodies.
- Temporary axes: resting the pointer on the same round face (cylinder, cone,
  torus) or circular edge or arc for 3 s shows its axis, dashed (passing over
  it shows nothing). The wait follows the axis: a cylinder's face, rim and seam
  count as one, and slips off it under 0.7 s don't restart the wait. It stays 3 s after the pointer leaves, then fades out; that
  face or edge can be picked wherever an axis is asked (Revolve, Circular
  Pattern, Move/Copy rotation, Axis).
- Sketches in a part don't hide the model, so a face can be sketched on.
  Editing a sketch a feature uses rolls the model back to just before that
  feature while it is open, as SolidWorks' Edit Sketch does.
- The planes and origin point are in an *Origin* folder (as FreeCAD's
  PartDesign has it); SolidWorks lists them loose under the part.

## Rollback bar (2026-11-18)

- Below the bar, features and planes are frozen, as SolidWorks has them: they
  keep their last result and aren't recomputed. Sketches attached to their
  faces stay attached; rolling forward recomputes them. (Before, a rolled-back
  feature became a copy of the one above, its faces vanished, and FreeCAD broke
  or re-attached the sketches on them.)
- The bar can be dropped onto a feature or between any two items of the tree.
  Its own menu has Roll to Previous, Roll Forward and Roll to End; a feature's
  has Rollback; the part's has Roll to Start and Roll to End.
- A new cut that would miss every body is flipped to cut into the material
  (a sketch on a face). Once the direction is set by hand, it is left alone.

## Sketch plane and references to bodies (2026-11-18)
- Sketch (or Extrude/Revolve with nothing to use) with no face or plane selected
  asks for a plane, as SolidWorks does: a Sketch panel with one selection box and
  Cancel. The origin planes show while it is open; a planar body face or a plane
  you made works too. An empty part is turned to the isometric view so the planes
  can be clicked.
- A new part's origin planes are hidden. They show only while that prompt is open,
  or when the user shows them; planes the user showed stay shown afterwards.
- In the Sketcher, a body's edges and vertices can be projected or intersected
  (external geometry). The link is moved straight away to the feature above the
  sketch, so the sketch follows the model and never depends on a later feature.
  An edge made only by a later feature is refused with a message.

## Draft (2026-11-18)

### Neutral Plane and Parting Line; no Step Draft yet
- **SolidWorks:** manual Draft has Neutral Plane, Parting Line and Step Draft; DraftXpert too.
- **Solid Design:** Neutral Plane (face propagation: None, Along Tangent, All Faces, Inner
  Faces, Outer Faces) and Parting Line (None, Along Tangent). Parting lines must lie in one
  plane. No Step Draft and no DraftXpert yet.
- **Why:** FreeCAD 1.1 has no draft in Python; OpenCASCADE's DraftAngle (reached through a
  PartDesign::Draft in a hidden scratch document) drafts about a plane only.

### Direction of pull defaults towards the faces
- **SolidWorks:** the arrow starts on the neutral plane's normal; you often press Reverse.
- **Solid Design:** it starts pointing from the neutral plane into the faces being drafted,
  so a neutral plane at the base tapers the part upwards (positive draft narrows along the
  pull). Reverse (next to the angle) flips it. Parting Line: the pull defaults to normal to
  the parting lines, into the material; Direction of Pull can be picked instead.
- **Why:** the first result is the one most moulds want.

### Faces after a draft are named by index
- Drafted faces keep their order, so references to them (a fillet after the draft) are
  stored by index and fingerprint, like faces made by a sweep. Tested: a fillet after a
  draft survives the box growing upstream.

## Rib (2026-11-18)
- Thickness: First Side, Both Sides, Second Side; Extrusion direction: Parallel to Sketch or
  Normal to Sketch; Flip material side.
- The material side starts towards the model (the nearer hit from the middle of the line).
- The ends are extended along their tangents only where they meet the model (SolidWorks'
  Linear type). No Natural type and no draft on ribs yet.
- A rib that would run off the model is refused with a message, rather than made open.
- Patterns and Mirror can repeat ribs (like extrudes).

## Reference Point and Coordinate System (2026-11-18)
- Point types: Arc Center, Center of Face, Intersection (edge and face or plane; a straight
  edge or circle meets a plane even beyond its ends), Projection, On Point, Along Curve
  Distance (From the other end flips it).
- Coordinate System: origin, X and Y directions, all optional (empty: the part origin and
  automatic axes); Reverse X, Y or Z. Z follows from X and Y, right-handed.
- **Departure:** Sketch with a coordinate system selected sketches on its XY plane.
  SolidWorks needs a plane for that.

## Panels: a filled box moves on (2026-11-18)
- After a one-item box (a plane, a sketch) is filled, the next click goes to the next empty
  box, or, with none empty, to the next list below it (Faces to Draft). Before, the next
  click replaced what was just picked.

## Helix/Spiral and Thread (2026-11-18)
- Helix/Spiral: Pitch and Revolution, Height and Revolution, Height and Pitch, Spiral;
  start angle, clockwise, reverse, taper (in or out). It sits in the history like a plane.
- **Departure:** the circle can be a circular edge of the model, not only a sketch circle.
- Sweep takes a helix as its path and turns the profile about the helix's axis, so springs
  and threads sweep cleanly.
- Thread: on a circular edge of a shaft or a hole; Cut Thread or Extrude Thread; Blind,
  Revolutions (turns of the helix: one lead each) or Up To Selection; offset from the edge;
  left hand; several starts. Sizes: ISO metric coarse and fine, UNC, UNF. The size starts at
  the one nearest the cylinder, with a warning when the cylinder doesn't match it.
- The thread is the 60° basic form, trimmed square at both ends (SolidWorks' "trim with
  start/end face" always on). No thread profiles from library files.

## Hole Wizard, full (2026-11-18)
- Types: Counterbore, Countersink, Hole, Straight Tap, Counterbore Slot, Countersink Slot,
  Slot. Standards: ISO, ANSI Inch (typical machinist-table dimensions; check them, or use
  Custom sizing). No Tapered Tap (pipe threads) or Legacy yet.
- End conditions: Blind, Through All, Up To Next, Up To Vertex, Up To Surface, Offset From
  Surface; each position gets its own depth.
- Options: near side countersink, far side countersink (Through All, Up To Next), head
  clearance. Custom sizing shows the standard's values greyed until it's turned on.
- Straight Tap: Tap Drill Diameter, Thread Diameter or Modelled Thread. FreeCAD has no
  cosmetic threads, so "cosmetic thread" isn't offered.

## Fillet types (2026-11-18)
- Variable Size: a start and an end radius along each chain of tangent edges (SolidWorks
  sets a radius per vertex; two is the usual case). The ends can be swapped.
- Face Fillet: rounds where two face sets meet; faces that don't share edges are refused for
  now (no fillet across a gap).
- Full Round: one face per set, planar parallel sides, a planar centre face (a straight
  rib's top). The panel moves on to the next set after each pick.

## Offset Surface, Move Face, Split Line (2026-11-18)
- Offset Surface: faces into a new surface body; 0 copies them.
- Move Face: Offset (any faces, curved too), Translate (planar faces; only the part of the
  move along the normal changes a plane), Rotate (planar faces, about an axis parallel to
  them; done as a draft about where the old and new planes meet).
- Split Line: Silhouette, Projection (both ways, or Single direction), Intersection. Split
  edges can be the parting lines of a Draft.
- Faces after Move Face and Draft are named by index (FreeCAD gives those operations no
  element map), with the fingerprint repair as backup.

## Step Draft, Rib Natural and draft (2026-11-18)
- Step Draft: parting lines at several heights, each square to the direction of pull (pick
  it); each height's faces turn about their own lines (SolidWorks' perpendicular steps). No
  tapered steps yet.
- Rib: Type Linear or Natural (arcs carry on round their circles to the model); Draft (an
  optional group): thinner towards the model, or thicker with Draft outward; the thickness
  is at the sketch.

## Instant3D drag handles (2026-11-18)
- In the Extrude panel, an arrow per direction with a depth (Blind, Mid Plane); in the
  Revolve panel, a ring per direction with an angle (Blind). Dragging snaps (0.5 mm, 0.1 mm
  under 5 mm; 1°, 5° above 30°); the panel's field and the preview follow.
- Click a handle's value to type a new one (Enter sets it, Escape doesn't).
- **Departure:** select an Extrude or Revolve in the tree and its handles show on the model
  without opening the feature; a drag (or a typed value) changes it as one undo step.
  SolidWorks shows Instant3D handles when you pick a face; here picking a face selects the
  body, so it's the feature in the tree. Double-clicking a feature still opens its panel
  (FreeCAD's convention) rather than SolidWorks' "show dimensions".
- The handles are drawn on top of the model, so the far one shows through it.

## Toolbars and menu (2026-11-18, owner's layout)
- Toolbars, left to right: Part, Sketch, Features, Bodies (solid body tools), Reference
  Geometry (one drop-down button, Plane first and the default), Surfaces (Offset Surface),
  Curves. The toolbars have new names ("Solid Design ...") so this order replaces where
  FreeCAD had remembered the old ones.
- A Solid Design menu in the menu bar has every tool in the same groups; SolidWorks' Insert
  menu stays too.

## All tools

### Rebuild errors
- **SolidWorks:** a red mark in the tree; details in a separate *What's Wrong* dialog.
- **Solid Design:** the error badge is on the feature and on the Part; the message
  goes in the feature's Description (Label2, the tree's Description column; not yet
  checked whether FreeCAD 1.1 shows it as the tooltip); *What's Wrong?* in the
  context menu opens the
  feature's panel with the error at the top. In the panel the error sits above OK,
  and OK is disabled with the reason in its tooltip.
- **Why:** a separate dialog interrupts; an error should say what is wrong where
  the fix is made.

### Selection boxes
- **SolidWorks:** coloured boxes; easy to fill the wrong one.
- **Solid Design:** the active box is framed and tinted in the theme's selection
  colour (no per-box colours, to keep to the theme); a pick that fits
  only one other box goes there and that box becomes active; a refused pick says
  why under the box ("That face is made by this feature..."). Filling a one-item
  box moves on to the next empty box that must be filled, as SolidWorks does.
- **Why:** easy to put a selection in the wrong box; hard to see which is active.

### Confirmation corner
- **SolidWorks:** OK/Cancel in the graphics area's top-right corner.
- **Solid Design:** none (owner's decision, 2026-11-17): FreeCAD's task panel OK
  and Cancel, Enter and Escape.

## Extrude

### Sketch box at the top
- **SolidWorks:** no sketch box; the sketch is implied, and appears only as the
  owner of Selected Contours at the bottom.
- **Solid Design:** a *Sketch* box at the top shows (and lets you change) the sketch.
- **Why:** the user can't see which sketch is being extruded without looking at
  the tree.

### Selected Contours by clicking regions
- **SolidWorks:** click regions or contours in the graphics area.
- **Solid Design:** same, and while the box is active every region of the sketch is
  drawn faintly, the picked ones strongly. A sketch that can't be used whole (open
  or overlapping contours) makes this box active by itself, with the reason.
- **Why:** previews that show what will happen; point at the fix.

### Bodies to Keep in the panel
- **SolidWorks:** a *Bodies to Keep* dialog after OK.
- **Solid Design:** a *Bodies to Keep* group appears in the panel as soon as the
  cut splits a body, before OK, with each piece listed and labelled in the view
  ("Body 1", "Body 2").
- **Why:** a modal dialog where a panel section will do; no preview of the choice.

### Feature Scope only when there is a choice
- **SolidWorks:** the Feature Scope group is shown in multi-body parts.
- **Solid Design:** hidden when the feature can only affect one body (one body
  before it, or Add with Merge result off).
- **Why:** shows options the user doesn't need; the model can answer it.

### Draft angle field always visible
- **SolidWorks:** the draft angle appears when Draft On/Off is pressed.
- **Solid Design:** a *Draft* check box with the angle beside it, disabled until
  the box is ticked.
- **Why:** keeps the panel from jumping; the option is visible where it is needed.
  (Small change; reverse it if the owner prefers SolidWorks' behaviour.)

## Tree

### Body names
- **SolidWorks:** a body is named after the last feature that changed it, and the
  feature can have the same name.
- **Solid Design:** same names, but FreeCAD refuses duplicate labels, so a body's
  label ends in an invisible zero-width space. Several bodies from one feature are
  "Cut-Extrude1[1]", "Cut-Extrude1[2]", as in SolidWorks.
- **Why:** not a UX change; a FreeCAD constraint.

### Rollback bar
- **SolidWorks:** drag the bar between features; right-click a feature >
  *Rollback* puts the bar just above it.
- **Solid Design:** *Roll to Here* puts the bar just above the feature (as
  SolidWorks); dragging the bar onto a feature puts it just below that feature
  (FreeCAD's tree only drops *onto* items, not between them).
- **Why:** FreeCAD tree mechanics.

## Revolve

### Axis picked automatically
- **SolidWorks:** uses the sketch's centerline when there is exactly one.
- **Solid Design:** same; the *Axis of Revolution* box shows it ("Sketch1
  centerline 1"). Not a departure; noted because centerlines aren't clickable in
  FreeCAD's 3D view outside the Sketcher, so a sketch with several centerlines
  needs a line, axis or straight edge picked instead.

## Fillet and Chamfer

### The model before the feature while editing
- **SolidWorks:** editing a fillet rolls the model back to just before it.
- **Solid Design:** same, for new and edited fillets and chamfers: every edge stays
  pickable, the picked edges are drawn thick, and the result is the green preview.
  Not a departure; noted because Extrude and Revolve show their result instead.

### Chamfer type as a list
- **SolidWorks:** the chamfer types are icon buttons.
- **Solid Design:** a drop-down with the same names, until there are icons for
  them.
- **Why:** temporary; no icons yet.

## Plane and Axis

### Type first, then exactly the references it needs  (PROPOSED: owner to decide)
- **SolidWorks:** up to three reference boxes; each offers constraints
  (coincident, parallel, perpendicular, distance, angle, mid plane) and the plane
  is solved from whichever combination is set.
- **Solid Design:** pick a type (Offset Distance, At Angle, Through Points,
  Parallel at Point, Normal to Curve, Mid Plane; for axes One Line/Edge/Axis, Two
  Planes, Two Points/Vertices, Cylindrical/Conical Face, Point and Face/Plane),
  then the panel shows only the boxes that type needs, labelled with what goes in
  them. With a preselection the type is guessed from it, as SolidWorks guesses
  its constraints.
- **Why:** the per-reference constraint grid lets the user build combinations
  that don't define a plane, and the error only says the plane is
  under-defined. This is a changed workflow, so it is listed for the owner to
  overrule; the same geometry results.

## Split

### No Cut Part button; pieces listed live
- **SolidWorks:** pick trim tools, press *Cut Part*, then tick the pieces to keep.
- **Solid Design:** the pieces are listed (and labelled in the view) as soon as
  the trim tools cut something, all ticked; untick the ones to throw away, and
  rename any by double-clicking its name.
- **Why:** a button press the software can do itself.

### A trim face cuts off what stands on it (2026-11-19, owner's rule)
- **SolidWorks:** a face used as a trim tool cuts only where the face itself is;
  the top face of a cube doesn't cut a cylinder standing on it (the face has a
  hole there).
- **Solid Design:** the face's inner loops are patched on its own surface first,
  so a protrusion is cut off as if the face were a plane there. Only inner loops
  count: the face must surround every edge the protrusion has on it. A boss that
  hangs over the face's outer edge, or one standing on another body's face, is
  not cut. A curved face is patched on its own surface; if that fails the split
  says so and suggests a plane or a surface body. When a patch was used, the
  pieces are refined, so the patch leaves no circular scar on the face around
  it (the cube's top is one face again).
- **Why:** the owner's request; it is what a user means by picking that face.

## Hole Wizard

### Type and positions on one panel
- **SolidWorks:** *Type* and *Positions* tabs; positions go in a 3D sketch.
- **Solid Design:** one panel. Click on a planar face to put a hole there (the
  points go into an ordinary sketch on that face, so they can be dimensioned in
  the Sketcher), or pick a sketch whose points place the holes.
- **Why:** switching tabs to finish one task; a 3D sketch that is easy to get
  wrong (spec 4.1 names this one).

## Patterns and Mirror

### What can be repeated
- **SolidWorks:** most features can be patterned.
- **Solid Design:** features that add or cut a shape (Extrude, Revolve, Hole
  Wizard) are repeated by repeating their operation (spec 7.6). Fillet and
  Chamfer can't be repeated yet; the panel says so and suggests patterning the
  bodies.
- **Why:** not a choice; a limit of this version.

### Pick a feature by clicking its face (2026-11-19)
- **SolidWorks:** in Features to Pattern/Mirror, clicking a face picks the
  feature that made it.
- **Solid Design:** clicking a face or edge picks the feature that *last touched*
  it (made or changed it), the latest feature above the one being edited. A cube
  top with a hole cut in it picks the cut. Clicking it again takes it out, as with
  tree picks. A vertex is refused with a note instead of being taken as a body.
- **Why:** the owner's request; the last feature to change a face is the one the
  user sees there.

## Move/Copy Body: Constraints

### Next constraint appears by itself
- **SolidWorks:** add a mate, then press Add for the next.
- **Solid Design:** up to six constraint sections; the next empty one appears as
  soon as the last is used. Moved with Copy, the copy goes to the one place the
  constraints define (Number of copies applies to Translate/Rotate).
- **Why:** a button press the software can do itself.

## Sweep and Loft (2026-11-19)

### How the new options are built
- A plain sweep is still OpenCASCADE's pipe shell, and a plain loft its
  ThruSections. Twist, guide curves and start/end tangency are built by
  Solid Design itself: copies of the profile are placed along the path (or
  between the profiles) and a B-spline surface is skinned through them, every
  pole interpolated with the end tangents given (`core/skin.py`). The shape
  passes through the copies exactly; between them it is smooth (48 or more
  copies on a sweep, 6 between each pair of loft profiles).
- Faces made this way, like sweeps, aren't named by history; references to them
  are kept by index and fingerprint.

### Sweep
- **Profile twist:** None, Specify Twist Value (Degrees or Turns, with a flip for
  the direction), Follow Path and 1st Guide Curve. SolidWorks also has Specify
  Direction Vector, Tangent to Adjacent Faces, Natural and Follow 1st and 2nd
  Guide Curves; not yet.
- **Guide curves:** sketches (each connected chain of curves is one guide), or a
  helix. SolidWorks makes the profile touch the guides by solving the profile
  sketch's pierce relations. Solid Design has no sketch solving there, so it
  transforms the profile instead: one guide scales it about the path (and turns
  it, with Follow Path and 1st Guide Curve); two guides scale, turn and move it
  keeping its shape; three or more distort it (affine) to touch all of them.
  Each guide must cross the profile's plane on the profile, and be as long as
  the path.
- **Start/End tangency:** None or Path Tangent; the group shows once there is a
  twist, guide curves or a tangency set, since a plain sweep is already square
  to its path.
- Twist, guide curves and tangency need a smooth path (no sharp corners).
- **Solid Profile:** a tool body of revolution (a revolve or a cylinder made of
  lines and arcs, as SolidWorks requires) swept along a smooth path. SolidWorks
  allows it only for cuts; Solid Design allows Add too (a ball swept along a
  path makes a pipe with round ends). The tool body is never cut by its own
  sweep (SolidWorks users hide it by hand). Exact while the path runs square to
  the tool's axis (a cutter along a groove, round a cylinder); a path that rises
  along the tool's axis is approximated.
- When a circular or solid profile is chosen and the sketch picked for the
  profile (perhaps by itself, as the newest) is then clicked as the path, it
  becomes the path.

### Loft
- **Start/End constraints:** None, Normal To Profile (with a draft angle, outwards),
  Direction Vector; both with a tangent length. SolidWorks also has Tangency To
  Face (when a profile is a face of the model); not yet. A closed loft has no
  ends to constrain.
- **Guide curves:** each must touch every profile. Influence: **To Next Edge**
  (the default here: a guide shapes the faces beside it, fading out at the
  profile's next corners, or half-way round a corner-less profile) or **To Next
  Guide** (its pull blends to the next guide; with one guide the whole profile
  moves). SolidWorks also has To Next Sharp and Global. Guide curves work on
  open lofts; the profiles' holes are lofted without them.
- Without constraints or guides the loft is OpenCASCADE's, as before.

## Shell: multi-thickness (2026-11-19)
- **SolidWorks:** each multi-thickness face has its own value, thicker or thinner.
- **Solid Design:** the same. The list shows each face's value; click a face in
  the list to see or change it (with none selected, the value goes to all of
  them). Thicker walls grow into the body; thinner walls are made by moving the
  hollow towards the face, and towards each group of thin faces so their shared
  corners open up too.
- **Limits:** multi-thickness faces must be planar; thinner faces need an inward
  shell. Thinning assumes the walls beside the face are square to it (a drafted
  side wall gets slightly thinner near a thinned face).

## Mirror and Patterns: Faces to Mirror/Pattern (2026-11-19)
- **SolidWorks:** faces of a feature can be mirrored or patterned when the
  feature itself can't be (imported bodies).
- **Solid Design:** pick every face of a boss, hole or pocket (its walls, and its
  top or floor). The faces' open edges are capped to make a solid: where it is
  material, its copies are added; where it is a gap, they are cut. Only the body
  the faces belong to is changed. A wall alone works when its open ends are flat
  loops (a hole's wall, a boss's side).

## Surface tools, Delete Face, Thicken (2026-11-19)

### Knit Surface
- Surface bodies sewn into one (the first picked keeps its ID); Create solid when
  they close, Merge entities, and a knitting tolerance (SolidWorks' Gap control).
  Faces of solids can't be knitted in this version: pick surface bodies.

### Planar Surface
- A sketch (its closed regions, with holes) or closed, flat loops of model edges.

### Filled Surface
- One closed loop of boundary edges (model edges, or a sketch). Curvature control
  is one setting for every edge (SolidWorks sets it per edge): Contact, Tangent
  or Curvature, tangent to the face beside each model edge. When OpenCASCADE
  can't make the patch tangent (a flat lid on vertical walls, for one), it falls
  back to Contact and says so.
- Constraint curves: sketches whose curves and points the patch passes through.
- Merge result knits the patch into the surface body its edges are on; Try to
  form solid then makes a solid if it closes.

### Trim Surface
- Standard (planes, sketches, faces or surface bodies trim the surfaces) or
  Mutual (picked surfaces trim each other; the kept pieces become one body, as
  in SolidWorks).
- **Pieces:** click on them in the view (the surface before the trim is shown
  while the panel is open); Keep selections or Remove selections. The click is
  stored as a point, and the piece under it is found again on every rebuild, so
  a piece stays picked while the surfaces change, as long as the point is still
  on it.

### Extend Surface
- Open edges of a surface body, by a distance (SolidWorks also has Up To Point
  and Up To Surface; not yet). Same Surface carries an analytic surface on (a
  cylinder stays a cylinder) past edges that are its own boundaries; elsewhere,
  and on B-spline surfaces, the edge goes on straight (Linear), with a note.

### Delete Face
- Delete: a solid with faces deleted becomes a surface body (as in SolidWorks).
- Delete and Patch: OpenCASCADE's defeaturing, so the faces around grow over
  the gap: removes bosses, holes and fillets.
- Delete and Fill: a patch over each gap (Tangent fill makes it tangent); a solid
  stays a solid when every gap closes.

### Thicken and Thickened Cut
- One Thicken tool with Add | Cut at the top of its panel (SolidWorks has two
  commands); Cut is Thickened Cut, and the feature is labelled Thicken-Cut.
- Side 1, Side 2 or Both Sides (half each); Create solid from enclosed volume for
  a closed surface. The surface body is used up, as in SolidWorks. Thicken has
  Merge result; Thickened Cut cuts every solid it reaches (no feature scope yet).

## Boundary, Intersect, Dome, Wrap (2026-11-19)

### Boundary (Add | Cut; open curves make a surface)
- **Direction 1 only:** a loft through the curves, with the Loft's start/end
  constraints.
- **Both directions:** a Gordon surface through the whole network: it passes
  exactly through every curve of both directions (`core/features/boundary.py`).
  Every Direction 2 curve must cross every Direction 1 curve, in the same order;
  with open Direction 1 curves the first and last Direction 2 curves must run
  along their ends (and the first and last Direction 1 curves along the
  Direction 2 curves' ends). Closed Direction 1 curves make a tube, capped into a
  solid. Start/end constraints and per-curve tangency (SolidWorks' Tangency To
  Face, curvature to face) aren't used with two directions in this version.
- Labels: Boundary1, Boundary-Cut1.

### Intersect
- As SolidWorks: solids, surfaces and planes; Create both / intersecting /
  internal regions; Cap planar openings; Regions to Exclude (ticked in a list,
  numbered in the view); Merge result; Consume surfaces. The picked solids are
  replaced by the result (the first keeps its ID).
- An excluded region is remembered by a point inside it, so it stays excluded
  while the model changes, as long as the point is still inside it.

### Dome
- Flat faces; Distance with a flip for a dent (SolidWorks' Reverse direction).
  On a round face: part of a sphere, or half an ellipsoid (Elliptical dome). On
  other faces the dome rises from the edges to the top (square to the face at
  the edge when Elliptical); SolidWorks' Continuous dome and constraint
  point/direction aren't there yet.

### Wrap
- Emboss / Deboss / Scribe, on cylindrical faces (SolidWorks' Analytical method:
  the sketch rolls round without stretching) and flat faces (projected). The
  sketch's plane must run along the cylinder's axis; it is rolled from the line
  where the plane is nearest the axis. Cones and SolidWorks' Spline Surface
  method (any face) aren't there yet. Scribed edges that cross the cylinder's
  seam split there too.

## Patterns II (2026-11-19)

### One toolbar button for the patterns
- **SolidWorks:** Linear Pattern's flyout holds the other patterns.
- **Solid Design:** the same: one Patterns button (Linear by default) with Circular,
  Curve Driven, Sketch Driven, Table Driven and Fill in its drop-down; Mirror keeps
  its own button. The menus list every pattern.

### Reference point
- Curve, Sketch, Table and Fill patterns place each instance by the seed's centre
  (SolidWorks' default, Centroid). Picking a vertex as the reference point isn't
  there yet.

### Curve Driven
- A sketch (its curves end to end) or model edges; Equal spacing spreads the
  instances from the seed to the end of the curve (round a closed curve);
  Alignment: Tangent to curve or Align to seed (SolidWorks' Curve method is
  always Transform curve here). An instance that would fall off the curve's end
  is an error that says so. Direction 2 isn't there yet.

### Table Driven
- Type X, Y in the table (a new empty row always waits at the bottom), in a
  coordinate system or the part's origin. Reading and saving .sldptab/.txt files
  isn't there yet.

### Fill
- Boundary: a flat face or a sketch's closed region. Layouts: Perforation
  (stagger angle), Circular (loop spacing), Square, Polygon (sides). Margins keep
  instances, whole, clear of the boundary's edges and holes. Seed: the features
  picked, or Create seed cut (Circle, Square, Diamond, Polygon) cut through the
  body at every instance (Flip cut for the other way).

### Instances to Skip
- Linear, Circular and Curve Driven list every instance (with its row and
  column for Linear) to tick off; SolidWorks has you click pink dots in the view.
  Clicking instances in the view isn't there yet.

### Variable Pattern
- Not yet: it needs the seed rebuilt with different dimensions for each instance,
  which comes with equations.

## Curves (2026-11-19)

- Curves (Projected, Composite, Through XYZ Points, Through Reference Points,
  Helix/Spiral) are reference geometry in the history, like SolidWorks': they
  aren't bodies. Sweep paths, guide curves, Boundary's Direction 2, Curve Driven
  Pattern and Composite Curve all take them, wherever a sketch is taken.
- The Curves toolbar is one button with a drop-down (SolidWorks' Curves flyout),
  Split Line first.
- **Projected Curve, Sketch on faces:** along the sketch's normal (Reverse
  direction, Bi-directional), landing where the sketch first meets the faces
  seen from the sketch: a line projected onto a cylinder lands on the near side
  only. **Sketch on sketch:** where the two sketches, pulled out along their
  planes' normals, meet.
- **Composite Curve:** model edges and sketches/curves; they must join end to end
  into one chain (the error says how many pieces there are).
- **Curve Through XYZ Points:** typed in a table (a new empty row always waits at
  the bottom); Closed curve. Reading and saving .sldcrv/.txt files isn't there
  yet.
- **Curve Through Reference Points:** model vertices in the order picked, then
  reference points; Closed curve.

## Surface tools II (2026-11-19)

- The Surfaces toolbar keeps the everyday tools as buttons; Ruled, Radiate,
  Untrim and Mid-Surface share one drop-down (the menus list everything). Replace
  Face sits with Delete Face and Move Face; Cut With Surface beside Thicken.
- **Ruled Surface:** Tangent to Surface, Normal to Surface, Tapered to Vector
  (angle), Perpendicular to Vector; Alternate side flips it. On a solid's edge the
  face used is the first beside it (SolidWorks lets you pick the other face).
  Sweep type, Trim and knit and Connecting surface aren't there yet.
- **Radiate Surface:** parallel to a reference plane, outward from the body (out
  of the solid, or away from the surface's face); Reverse sends it inward.
  Propagate to tangent faces isn't there yet.
- **Untrim Surface:** Internal edges (fill holes), All edges, External edges
  (grow, keep holes) by Distance %; a new surface body (Merge with original isn't
  there yet).
- **Mid-Surface:** face pairs found on the picked bodies (or among picked faces):
  parallel flat faces facing each other; with Recognition threshold 0, the
  thinnest walls only. Cylindrical pairs aren't paired yet.
- **Cut With Surface:** a surface body or a plane; keeps the side behind the
  surface's normal, Flip cut for the other. The surface must reach across the
  body. Feature scope: the bodies picked, or all.
- **Replace Face:** flat faces of a solid replaced by a surface body: the solid
  grows out from the faces (along their normals) to the surface, or is trimmed
  back to it, and the surface is used up (optional). SolidWorks extends the faces
  around along their own surfaces; here they grow straight out from the replaced
  faces, so drafted walls beside them grow without their draft.

## Scale and Flex (2026-11-19)

- One toolbar button with a drop-down (Flex first) in the Bodies toolbar.
- **Scale:** about each body's centroid, the origin or a coordinate system;
  uniform (keeps every surface's kind) or X, Y, Z factors (surfaces become
  B-splines). With no bodies picked, every solid is scaled.
- **Flex:** Bending, Twisting, Tapering (taper factor at the far trim plane),
  Stretching; trim planes measured in from the body's ends; the triad sits at the
  body's centre with its axis along the body's longest side, or along an edge or
  axis you pick, turned round it (bend direction) and reversible. SolidWorks
  drags the triad and trim planes in the view; here the trim planes have drag
  arrows (Stage 10) and the triad is set by numbers or a picked axis. The flexed body is B-spline geometry: control nets are
  refined and moved, so volumes come within about 0.05 % of exact on test
  shapes. Hard edges and the trim planes' "keep" areas outside the flexed span
  behave as in SolidWorks (unchanged before plane 1, carried along after plane 2).
- **Indent:** not yet (it needs SolidWorks' keep/remove selections on the target
  body's regions to make sense).

## Core feature gaps (2026-11-19)

- **Extrude, Direction of Extrusion:** a row in Direction 1 ("Normal to sketch"
  until something is picked). An edge or sketch line gives its direction, a plane
  or flat face its normal; the direction is turned to leave the sketch on the
  side the extrude goes. The depth is along that direction, as in SolidWorks.
  Draft can't be combined with it in this version (the error says so).
- **Chamfer, Face Face:** pick two or more faces that meet; every edge shared by
  two of them is chamfered, the first distance on the face picked first (Equal
  distance, Distance 2 and Flip as for Distance Distance). SolidWorks also
  chamfers between faces that don't touch; that isn't done yet, and the error
  says so. Picking an edge in Face Face mode is refused with "Pick faces here."
- **Hole Wizard, Tapered Tap:** NPT (ANSI Inch) and Rc / ISO 7-1 (ISO) pipe
  sizes; the Size list switches to pipe sizes. The hole narrows 1 in 16 on the
  diameter, from the tap drill (or the thread's major diameter at the gauge
  plane) at the face. A modelled thread isn't available for it yet: it warns and
  uses the tap drill. Cosmetic threads aren't drawn (no feature has them yet).
- **Hole Wizard, Advanced:** a Type in the same Hole Wizard rather than its own
  command. Near side and far side elements are a list (one line each:
  "Counterbore Ø11 × 6.4") with Add / Remove / Up / Down, and the selected
  element's type, diameter, depth and angle under it; the last near side element
  runs to the end condition, a countersink's depth comes from its angle and the
  element it opens into. Elements are typed dimensions, not picked from the
  standard's tables (it starts from the hole's counterbore and clearance hole).
  SolidWorks lays each element out with its own standard and size.
- **Hole Wizard layout:** the near and far side countersinks' diameter and angle
  sit on rows under their check boxes (shown while checked) instead of beside
  them, so the panel fits a narrow task pane.

## Stability and UX (2026-11-19)

- **Drag handles (Instant3D):** besides Extrude and Revolve, a Fillet's radius
  (Constant Size), a Chamfer's distance (Angle Distance, Distance Distance,
  Offset Face), a Shell's thickness, a Blind hole's depth and Flex's trim planes
  have arrows, in their panels and on a selected feature. The arrow for an edge
  feature starts at the first picked edge's middle and points out between its
  faces. A press that grabs an arrow isn't also taken as a pick in the panel.
- **Measure, Mass Properties, variables:** not in this workbench: FreeCAD's own
  Measure and Mass Properties (on its toolbars in every workbench) and its
  VarSet for global variables, used with the fx button on any field.
- **What's Wrong and Force Rebuild:** What's Wrong lists every feature with an
  error or warning; double-click to edit it. Force Rebuild rebuilds everything;
  it has no Ctrl+Q shortcut because Ctrl+Q quits FreeCAD.
- **Context toolbar:** clicking a body's face, edge or vertex in the 3D view shows
  a bar of the tools that fit by the pointer (flat face: Edit Feature, Sketch,
  Hole Wizard, Fillet, Shell, Move Face, Plane; curved face: Edit Feature,
  Fillet, Shell, Move Face, Delete Face, Axis; edge: Edit Feature, Fillet,
  Chamfer, Axis, Plane; vertex: Chamfer, Point, Plane). It fades as the pointer
  moves away and goes past about 170 px, when the selection changes or a tool
  starts. Not while a panel is open or a sketch is being edited. Solid Design >
  Context Toolbar turns it off (kept between sessions). SolidWorks also shows
  one for tree picks; this doesn't yet.

## Surface features, Deform, Indent, Freeform, Surface Flatten (2026-11-20)

- **Extruded, Revolved, Swept, Lofted and Boundary Surface:** not separate
  features. Extrude, Revolve, Sweep, Loft and Boundary have a third mode,
  Add | Cut | Surface, and the Surfaces toolbar's buttons open them in Surface
  (labels Surface-Extrude1, Surface-Revolve1, Surface-Sweep1, Surface-Loft1,
  Boundary-Surface1). Switching an existing feature between a solid and a
  surface is one click. In Surface mode the sketch's curves are swept (open
  sketches too), Thin Feature, Merge result, Feature scope and Bodies to Keep
  hide, and every end condition works (Up To Surface/Next/Body trim the sheet
  where it meets them). Extrude has Cap end (closed profiles: a closed surface).
  A closed loft's or sweep's holes become surfaces of their own walls.
- **Deform:** Point, Curve to curve, Surface push, in one panel (a type list).
  The deform point is a position (a vertex picked, or where a face is clicked);
  it doesn't follow the model. The direction is an edge, axis or plane, or
  square to the face when empty. Stiffness Minimum / Medium / Maximum sets how
  the change fades over the radius. Curve to curve pairs initial and target
  curves in order (a reversed target is turned round); there are no fixed curves
  yet. Surface push uses a body of the part as the tool (SolidWorks also offers
  built-in sphere, ellipse, polygon and rectangle tools) and pushes along the
  direction picked, or from the tool towards the bodies; there's no deform
  deviation yet, so the dent follows the tool to within the control net's
  spacing (a few percent of the overlap can stay at the rim). The changed faces
  become B-splines, like Flex; faces the change doesn't reach stay as they were.
  The distance has a drag arrow.
- **Indent:** Target and Tool are bodies; the tool's regions outside the target
  are listed, numbered in the view, all ticked: the target wraps the ticked ones
  with the wall thickness (rounded where it turns a corner) and is only cut at
  the unticked ones. Clearance is the gap off the tool; Cut only cuts. The tool
  body stays.
- **Freeform:** pick one face; click on it to add control points; each point has a
  height along the face's normal (typed, or dragged with its arrow). The face's
  edges stay put; Edges: Contact, Tangent or Curvature sets how the change meets
  them; Reach sets how far each point's pull spreads. SolidWorks drags control
  curves and points with a triad; there are no control curves here, and points
  only move along the normal. A point on (or within a few control-net spacings
  of) an edge is refused.
- **Surface Flatten:** faces (connected) laid flat as a new surface body,
  touching the faces at the vertex (or edge middle) picked, or the first face's
  centre. Uses FreeCAD's flatmesh unwrapper; developable faces come out true,
  others are stretched as little as possible and a warning gives the change of
  area. Round faces are opened along their seams; a closed body (a whole sphere)
  has to be split first. No relief cuts or tear lines yet.
- Toolbar: the five surface makers lead the Surfaces toolbar; the Flex/Scale
  drop-down is now Deform Bodies (Flex, Deform, Indent, Freeform, Scale); Surface
  Flatten is in More Surfaces.
