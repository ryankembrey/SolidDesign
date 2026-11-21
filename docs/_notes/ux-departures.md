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

- One isometric icon set, drawn by tools/make_icons.py (rules in
  tools/icon_kit.py). Redone 2026-11-20 at the owner's request: green always
  adds material, red always removes it, grey is existing material; any other
  tool uses its toolbar's one accent (Features blue, Bodies violet, Reference
  amber, Surfaces teal, Curves magenta, Evaluate slate). At most grey plus one
  colour per icon; no +/x badges.
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
- The temporary axis itself can be clicked (2026-11-21, owner's request): it turns
  green and stays (no fading, and hovering elsewhere doesn't replace it) until it
  is used or something else in the view is clicked, when it fades. The click
  selects nothing behind it. With a tool open, the click puts it in the tool's
  axis box (or the active box); with none, the next tool that asks for an axis
  (Revolve, Circular Pattern, Move/Copy rotation, Flex, Axis) starts with it.
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

### Neutral Plane, Parting Line, Step Draft and DraftXpert
- **SolidWorks:** manual Draft has Neutral Plane, Parting Line and Step Draft; DraftXpert too.
- **Solid Design:** Neutral Plane (face propagation: None, Along Tangent, All Faces, Inner
  Faces, Outer Faces) and Parting Line (None, Along Tangent). Parting lines must lie in one
  plane. Step Draft (perpendicular steps; SolidWorks also has tapered steps) and
  DraftXpert came later (see Stage 11).
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
  Linear type), or round their circles (Natural). Draft leans the rib's sides
  (thinner towards the model, or thicker with Draft outward).
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
  Custom sizing). Tapered Tap, Advanced and Legacy came later.
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
- **Look (2026-11-20, owner's request):** FreeCAD's own gizmos (PartDesign's), not
  our blue arrows: red, yellow under the pointer and while dragged, a constant
  size on screen, and a blue line for the dimension. Four kinds, as FreeCAD has
  them: Linear (an arrow: Extrude depth, Shell, Hole, Flex, Deform, Freeform,
  Mounting Boss, Snap Hook, Chamfer), Radial (an arrow on each face at the radius:
  a symmetric Fillet, an equal-distance Chamfer), Directed Rotation (an arrow at
  the end of the swept angle, with a blue circle and radii: Revolve) and Rotation
  (an arc with a ball: an Extrude's draft angle, new, as Pad's taper). Only the
  shapes are FreeCAD's; the dragging, snapping, typed values and undo stay ours.
  The arrows' stems are half FreeCAD's length (owner's request).
- **Every tool with a dimension you can point at has gizmos (2026-11-21):** besides
  the above, Draft (angle arc on the first face), Dome (height), Wrap (depth), Rib
  (thickness), Thread (offset and length), Variable fillet (start and end radii at
  the edge's ends), Extrude From Offset, Linear Pattern (spacing per direction),
  Circular Pattern (angle ring through the seed), Move/Copy (Delta X/Y/Z, which may
  go negative, or the distance along the picked edge; the angle ring round the
  picked axis), Move Face (offset, translate, rotate), Offset Surface (signed),
  Thicken, Extend (by distance), Ruled and Radiate surfaces, an Offset Distance
  plane, Helix height and Cosmetic Thread length. Not yet: asymmetric fillets and
  unequal chamfers keep one arrow (which face takes which distance is decided deep
  in the fillet code), and an At Angle plane has no angle gizmo.

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

### Plane: SolidWorks' three references (2026-11-21, owner's decision)
The owner overruled the type-first panel for Plane. It is now SolidWorks' own:
First, Second and Third Reference, each a box and the constraints that fit what
is in it (icon buttons, the chosen one named beside them), the distance or angle
under the reference whose constraint has one, and "Fully defined" at the top.
Picks fill the boxes in turn; taking one out closes the gap. The constraints are
guessed from what was picked, as SolidWorks does: a face Offset Distance; two
planes Mid Plane; a plane and an edge At Angle about the edge; a plane and a
point Parallel through the point; an edge and a point on it Perpendicular there
(off it: through both); three points Coincident; a plane and two points
Perpendicular through them; a cylinder and a plane or point Tangent. A new pick
guesses again; a constraint the user chose stays until then.
- **Departures:** Tangent works on cylinders only (not cones). Mid Plane of two
  planes that meet halves the angle inside the corner; Flip turns it round.
  SolidWorks' "number of planes" isn't there. An edge alone set to
  Perpendicular places the plane at the edge's start (SolidWorks waits for a
  point). A circle or other flat edge can be Coincident: the plane it lies in.
  Errors say what is wrong ("References 1 and 2 ask for different
  directions", "three points make a plane; pick 1 more") rather than only
  "not fully defined".
- Planes made with the old types still solve the old way; opening one in the
  panel turns it into the same plane, as constraints. Scripts can still give a
  type.

### Axis: SolidWorks' one box and five types (2026-11-21, owner's request)
- One Selections box (up to two references; a third pick keeps the last two) and
  the five types as buttons: One Line/Edge/Axis, Two Planes, Two Points/Vertices,
  Cylindrical/Conical Face, Point and Face/Plane. The type is pressed for you from
  what was picked, in either order (a face then a point is Point and Face), as
  SolidWorks does; pressing another overrides it until the next pick. "Fully
  defined" shows when the axis is made. A circular edge counts as One Line: its
  axis. Preselection and the right-click menu guess the same way.

### Point: type first  (PROPOSED: owner to decide)
- **SolidWorks:** one box; the point is solved from what is picked.
- **Solid Design:** pick a type, then the panel shows only the boxes that type
  needs. With a preselection the type is guessed.
- **Why:** kept from before; Plane and Axis moved to SolidWorks' way at the
  owner's request.

### Names in the 3D view (2026-11-21, owner's request)
- Planes, axes, points and coordinate systems show their names, as SolidWorks
  shows plane names. A plane's lies flat in the plane, inside its top-left
  corner (the origin planes' too, in FreeCAD's small fixed-size squares). An
  axis' runs along the axis near its end, turned about it to face the viewer and
  never upside down. A point's or coordinate system's sits just above it, facing
  the viewer. The text is the same size on screen at any zoom, hides with the
  object, and follows a rename. Solid Design > Reference Names turns them off.
- Like the geometry, a name behind a body is hidden. The origin axes keep
  FreeCAD's own small X/Y/Z labels.

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
  the direction), Follow Path and 1st Guide Curve, Follow 1st and 2nd Guide
  Curves. Orientation (Stage 11): Follow Path, Keep Normal Constant, Specify
  Direction Vector, Tangent to Adjacent Faces, Natural.
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
  Direction Vector, Tangency To Face; all with a tangent length. A closed loft has
  no ends to constrain.
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
- Open edges of a surface body, by a distance, Up To Point or Up To Surface. Same
  Surface carries an analytic surface on (a
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
  Merge result. Feature scope: All bodies, or the bodies picked.

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
  the edge when Elliptical). Continuous dome, a direction and a constraint point
  came in Stage 11.

### Wrap
- Emboss / Deboss / Scribe, on cylindrical faces (SolidWorks' Analytical method:
  the sketch rolls round without stretching) and flat faces (projected). The
  sketch's plane must run along the cylinder's axis; it is rolled from the line
  where the plane is nearest the axis. Cones and the Spline Surface method came in
  Stage 11. Scribed edges that cross the cylinder's
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
  is an error that says so. Direction 2 came in Stage 11.

### Table Driven
- Type X, Y in the table (a new empty row always waits at the bottom), in a
  coordinate system or the part's origin. Read File / Save File (Stage 11).

### Fill
- Boundary: a flat face or a sketch's closed region. Layouts: Perforation
  (stagger angle), Circular (loop spacing), Square, Polygon (sides). Margins keep
  instances, whole, clear of the boundary's edges and holes. Seed: the features
  picked, or Create seed cut (Circle, Square, Diamond, Polygon) cut through the
  body at every instance (Flip cut for the other way).

### Instances to Skip
- Linear, Circular and Curve Driven list every instance (with its row and
  column for Linear) to tick off; Pick Instances in the View (Stage 11) toggles
  them by clicking the model where they are.

### Variable Pattern
- Came in Stage 10 (a table of values per instance).

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
  Sweep, Trim and knit and Connecting surface came in Stage 11.
- **Radiate Surface:** parallel to a reference plane, outward from the body (out
  of the solid, or away from the surface's face); Reverse sends it inward.
  Propagate to tangent faces came in Stage 11.
- **Untrim Surface:** Internal edges (fill holes), All edges, External edges
  (grow, keep holes) by Distance %; a new surface body (Merge with original isn't
  there yet).
- **Mid-Surface:** face pairs found on the picked bodies (or among picked faces):
  parallel flat faces facing each other; with Recognition threshold 0, the
  thinnest walls only. Coaxial cylinders (a tube) pair too (Stage 11).
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
- **Indent:** came in Stage 9 (see there).

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
  plane) at the face. Modelled Thread follows the cone (Stage 10); Cosmetic Thread
  is its own reference geometry (Stage 10).
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
  curves in order (a reversed target is turned round); fixed curves hold the
  body still along them. Surface push uses a body of the part as the tool (SolidWorks also offers
  built-in sphere, ellipse, polygon and rectangle tools) and pushes along the
  direction picked, or from the tool towards the bodies. Deviation spreads the
  dent round the tool's rim, fading out over that distance; with none, the dent
  follows the tool to within the control net's spacing (a few percent of the
  overlap can stay at the rim). A finer control net is used round the tool and
  round a point push, so a point reaches its full distance. The changed faces
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
  them; Reach sets how far each point's pull spreads. Each point also has Move
  X/Y/Z: a sideways slide across the face (the part along the normal is dropped;
  Height does that). Control curves are sketches the face is pulled onto, where
  SolidWorks draws control curves on the face and drags points on them with a
  triad. A point on (or within a few control-net spacings of) an edge is refused.
- **Surface Flatten:** faces (connected) laid flat as a new surface body,
  touching the faces at the vertex (or edge middle) picked, or the first face's
  centre. Uses FreeCAD's flatmesh unwrapper; developable faces come out true,
  others are stretched as little as possible and a warning gives the change of
  area. Round faces are opened along their seams. Tear Edges cut the faces open
  along edges (relief cuts); a tear that stops inside the faces opens a slit. A
  closed set of faces (a whole body) needs tear edges, like a net, and says so.
- Toolbar: the five surface makers lead the Surfaces toolbar; the Flex/Scale
  drop-down is now Deform Bodies (Flex, Deform, Indent, Freeform, Scale); Surface
  Flatten is in More Surfaces.

## Stage 10: draggers, fillet options, fastening features, measured reference geometry

- **One dragger system.** Every drag handle is a `Dragger` (an arrow or a ring) built
  from a `Spec` and managed by one `FeatureDraggers` set, whether it shows in a
  panel or on a selected feature (Instant3D). Extrude and Revolve no longer have
  their own handle code. Mounting Boss and Snap Hook have a height arrow.
- **Fillet:** Symmetric | Asymmetric (a distance on each face, swapped with the
  flip button); Profile: Circular, Conic Rho (with rho) or Curvature Continuous.
  Variable Size takes points along the edges (position in percent, radius), as
  SolidWorks' variable radius points, listed and edited in the panel. Face
  Fillet takes a hold line (the round's size follows it). Face Fillet and Face
  Face chamfer also work across a gap between faces that don't touch (one flat
  face per set). The rounds that OCC's fillet can't make (asymmetric, conic,
  curvature continuous, variable points, hold line, gaps) are built from
  sections lofted along the edge and cut or added with a fuzzy boolean. Setback
  isn't there yet.
- **Patterns and Mirror repeat fillets and chamfers** by running them again on
  their edges moved into each instance's place.
- **Variable Pattern:** the feature (an Extrude or a Revolve), the dimensions that
  change (its own depth, angle, draft, thickness, and its sketch's *named*
  dimensions), and a table with one row per instance. SolidWorks picks the
  dimensions by clicking them in the view; here they come from a list. Sketch
  dimensions tied to external geometry are dropped in the instances' copies.
- **Mounting Boss, Snap Hook:** click on a face where it goes (the point, not a
  sketch point or an edge as SolidWorks asks). On a curved face the boss or hook
  reaches down to meet the face everywhere under it. Boss: Hole or Pin, drafted;
  fins tie it to the wall (number, length, height, thickness, a turn). Hook:
  beam height, thickness and width; the hook's overhang and height; it points
  along X, along an edge or plane, turned by an angle.
- **Lip/Groove:** the groove body, the lip body and the lip body's flat face where
  they meet. The lip is a band in from the face's outer edge (offset, width,
  height); the groove is the same band widened and deepened by the gap. SolidWorks
  asks for the lip's faces and edges separately.
- **Vent:** one sketch. Its outer loop is the vent, its lines are ribs and its
  inner loops spars (or kept solid: Fill-in), each with a width; it cuts to a
  depth. SolidWorks asks for the boundary, ribs, spars and fill-in boundaries one
  by one and also sets rib and spar depths.
- **Cosmetic Thread:** reference geometry, not a feature: it doesn't change the
  body. It shows the thread's minor diameter (shaft) or major diameter (hole) as
  dashed circles and lines, with the callout (size, class, length). Blind or Up
  To Next (to the end of the cylinder).
- **Tapered Tap:** Modelled Thread now cuts a tapered thread that follows the 1 in
  16 cone.
- **Bounding Box:** Best Fit (the smallest box over the bodies' main directions) or
  Reference Plane (square to a plane, turned in it to fit). Its length, width,
  thickness and volume are read-only properties and show in the panel; it can
  include surface bodies. **Center of Mass:** a point at the solid bodies' centre
  of mass (one density) that follows the model and works as any reference point.
- Toolbar: Thread is now a Threads drop-down (Thread, Cosmetic Thread); the new
  Fastening Features drop-down holds Mounting Boss, Snap Hook, Lip/Groove and
  Vent. Bounding Box and Center of Mass are in Reference Geometry; Variable
  Pattern is in Patterns.

## Stage 11: Split's face reach, and the options missing on existing tools

- **Split, faces and surfaces:** as soon as a face or surface body is picked, the
  panel asks how far it should cut: *Within their edges* (the default) or *Past
  their edges*. Within: holes in the face are patched first, so something poking
  through it is cut off; a sphere or torus face with a hole is patched to the
  whole sphere or torus, and a cylinder or cone face that goes all the way round
  is patched across its holes, so a cylinder poking out of a sphere is cut off by
  the sphere's face. Past: every face grows over its whole surface (a plane with
  no edges, a whole cylinder, sphere or torus, a cone up to its tip, a B-spline's
  whole patch) and cuts everything that would cross it. SolidWorks has no such
  choice: it only uses a face within its edges.
- **Draft, DraftXpert:** a Type in the same Draft panel rather than its own tabbed
  manager. A neutral plane and an angle; with no faces picked it drafts every
  face with less draft than the angle. Faces OpenCASCADE can't draft are left out
  and listed in a warning instead of failing the whole draft. Draft Analysis in
  the panel counts positive, negative, need-draft and straddle faces, with a
  button that picks the faces that need draft (SolidWorks colours them in the
  view).
- **Sweep orientation:** Specify Direction Vector (the profile keeps its top
  towards a direction), Tangent to Adjacent Faces (the path must be model edges;
  the face the path runs along most wins where two meet), Natural (the path's
  curvature turns it; on straight runs the nearest bend's direction carries
  over). Twist: Follow 1st and 2nd Guide Curves (the line between the two guides
  turns and scales the profile; other guides are not used then). Sweeps along a
  closed path with stations now close round the ring.
- **Loft, Tangency To Face:** the profile is a sketch drawn along a face's edges
  (SolidWorks: a face of the model as the profile); the loft leaves it carrying
  on the faces beside it.
- **Dome:** Continuous dome (faces that aren't round: the outline rounds off as
  it rises, never overhanging the face); Direction (the dome leans that way, a
  shear, its height still square to the face); a constraint point (the top goes
  through it: height and lean follow).
- **Wrap:** cones (rolled like a cylinder; horizontal lengths kept as arc lengths
  at each height) and the Spline Surface method: any face, the sketch projected
  along its normal, the raised or sunk part between the face and its offset.
- **Curve Driven Pattern, Direction 2:** a second curve; every instance along the
  first is carried along it without turning. Instances to Skip become i,j.
- **Table Driven Pattern:** Read File / Save File. Files are read as text: any
  line with X and Y (spaces, tabs, commas or semicolons; an index first is fine)
  is a point. SolidWorks' own .sldptab files are read when they're text.
- **Instances to Skip, in the view:** Pick Instances in the View (Linear,
  Circular, Curve Driven): while on, clicking the model where an instance is, or
  would be, leaves it out or puts it back; the instances are numbered in the view
  (skipped ones crossed). SolidWorks has pink dots to click instead.
- **Thicken:** Feature Scope, All bodies or the bodies picked (both modes).
- **Extend Surface:** Up To Point and Up To Surface (the extension goes past, then
  is cut back to the surface or plane).
- **Ruled Surface:** Sweep (one smooth surface, a line swept along the edge
  chain, leaving the first edge tangent to its face or along the reference
  vector); Trim and knit (strips that run into each other at a corner are cut
  back to the mitre; on by default); Connecting surface (fills the gaps at sharp
  corners with flat triangles).
- **Radiate Surface:** Propagate to tangent faces (follows edges meeting the
  picked ones smoothly).
- **Mid-Surface:** coaxial cylinders (a tube's inside and outside) pair: the
  cylinder halfway, over the height and turn they share.
- **Hole Wizard, Legacy:** a Type: Simple, Tapered (taper angle), Counterbored,
  Countersunk, Counterdrilled (a counterbore with a cone down to the hole). Sized
  only by its own dimensions; no standards.
- **Joining touching bodies:** when OpenCASCADE loses every solid fusing bodies
  that only touch (a ring sitting on a rim), it retries with a little tolerance
  and otherwise says so, instead of the bodies vanishing.
- **Scratch document:** operations that need a document (draft, sketch copies for
  Variable Pattern) use one hidden document that stays open for the session;
  opening and closing one each time ended the user's open transaction, so Cancel
  and Undo stopped working.

## Previews, labels and Through All (2026-11-21, owner's fixes)

- **Gizmo values** sit just past the gizmo's tip in FreeCAD's framed label (text on
  a white background, a constant size), on the side away from the gizmo as it
  points on screen; they follow when the view turns.
- **Unpicking empties the preview:** on an error a panel still keeps the last good
  result on screen (a value being typed doesn't blank it), but once every pick box
  is empty the result and the highlights go.
- **Fillet, Chamfer and Draft previews** are only the faces the feature makes (the
  rounds, bevels, drafted faces) in green, as SolidWorks' partial preview, not the
  whole changed body.
- **Cuts preview on the result:** while a preview takes material away, the bodies it
  changes are drawn as they come out (ghosted like the rest) and the old bodies are
  veiled (invisible but still pickable), so the removed material shows only its
  dashed red edges, not the old body's black edges inside it.
- **Through All** (Extrude, solid and surface, both directions) stops just past the
  far side of the model's bounding box along the direction, as SolidWorks, not at a
  length "longer than anything". Hole's Through All still goes the whole way.
  Sketch- and table-driven patterns now move copies only within the sketch's
  (table's) plane, so a cut keeps its depth wherever it lands.

## Command search (2026-11-21, owner's request)

- **"/" opens a command search** (SolidWorks has one in its title bar): a box over
  the 3D view, centred, its top a third of the way down. Typing filters Solid
  Design's tools by fuzzy match (letters in order, best at word starts: "lp" finds
  Linear Pattern); a whole word from a tool's tooltip finds it too, ranked lower
  ("boss" finds Extrude). Up/Down choose, Enter starts the tool, Escape closes.
  Tools that can't run now are greyed and skipped. Only Solid Design's tools are
  listed, not the toolbar drop-downs. "/" does nothing while a tool or a sketch is
  open, in other workbenches, or while typing in a field. Also in the Solid Design
  menu as Command Search.

## Command line and repeat (2026-11-21, owner's request)

Beyond SolidWorks, for power users; normal use is untouched (both keys act only when
typed in the 3D view, in Solid Design, with no tool or sketch open, and not in a
text field).

- **":" opens a command line** along the bottom of the 3D view (vim's): a tool,
  then values in order, option words and name=value pairs:
  `fillet 2`, `extrude 10 cut`, `extrude throughall`, `lp 20 4`,
  `chamfer d=1.5 flip`, `fillet Width/2`, `fillet =Width/2 + 1mm`.
  Tools match fuzzily; option names match by start or fuzzily, narrowed by the
  value's kind ("dra=3" is DraftAngle, not Draft); choices by their words, spaces
  and case ignored; yes/no options by name ("reverse", "noreverse"). Units work
  anywhere. A VarSet's variable makes a live expression (the feature follows it).
- **What it works on:** the selection; with none, what was under the pointer when
  ":" was pressed; with neither, the tool's panel opens with the values in,
  waiting for picks. A feature that builds cleanly is made with no panel (one undo
  step); one that doesn't opens its panel with the values in and the error shown.
- **Tab / Shift+Tab** complete tools, options, choices and variables (a tool's
  options are known before it's made: its class declares them to a recorder);
  **Up / Down** go through the history, kept between sessions; **Escape** closes.
- **"." repeats the last feature** (made from the line, or by OK in a panel) with
  the same settings, on the selection or what's under the pointer. From a panel it
  repeats what was changed there (and on the line before it), not the defaults.
- Also in the Solid Design menu: Command Line, Repeat Last Feature.

## What's Wrong and the health badge (2026-11-22, owner's request: "the best tool possible")

SolidWorks' What's Wrong lists features and messages. Solid Design's also says
why and what to do, shows it in the view, and has the fixes at hand.

- **Status bar badge**, always in sight: "No problems", or "1 error, 2 warnings"
  with the worst one's icon; a click opens What's Wrong. It follows every rebuild
  and the document shown.
- **The list** covers features, reference geometry and sketches (a sketch whose
  face is gone, or that won't solve, is listed, which SolidWorks only flags in the
  tree). A problem that follows from another is under it ("It may come right once
  Cut-Extrude1 is fixed: fix that first"), and the summary says how many to fix
  first. Rows wrap; Enter or a double-click edits.
- **Details** for the one picked: what happened, *Why* (where it can be told: the
  feature after the one the reference was picked on that changed the model where
  it was), *What to do*, and a key to what is drawn in the view.
- **In the view**, on top of the model, every line labelled in words:
  - dashed orange: where a lost face or edge was ("Lost fillet edge (was here)");
  - green: what it was repaired to ("Now uses this edge");
  - numbered yellow: what could replace it, when several could;
  - translucent blue: what the feature that changed it changed ("Changed by …");
  - magenta, with a dot: tiny edges and slivers from Check Geometry.
  When the repaired element is exactly where the lost one was, the details say so
  ("Good sign").
- **Buttons:** Edit; Looks Right (a repair checked: no more warning); Zoom to It;
  Roll Back to Here (and Roll to End while a part is rolled back); Suppress /
  Unsuppress (suppressed ones stay listed so they can be put back).
- **Check Geometry** (on demand): bodies that aren't valid solids, edges under
  0.01 mm, faces thinner than 0.005 mm, each with the feature that made it; Edit
  opens that feature. **Rebuild All** as before.
- **Repairs are remembered:** a reference found again by its fingerprint stays a
  warning until it is checked (Looks Right, OK in the feature's panel, or picking
  it again), instead of vanishing at the next rebuild. Fingerprints keep a few
  points along the element so where it was can be drawn after it is gone.
- **Departures:** no "will this break?" preview while editing yet, and no stress
  test (nudging dimensions to find fragile features); both are possible next steps.

## Picks show in the view; picking more edges at once (2026-11-21, owner's request)
- Whatever is in a tool's selection boxes is drawn in the selection blue as soon
  as it is picked (edges thick, faces tinted), in every tool. Fillet, Chamfer and
  Draft already drew their own.
- SolidWorks' edge helpers, for boxes that take several edges:
  - Right-click an edge while a tool is open (and its active box takes edges):
    Add/Remove This Edge, Select Tangency, Select Loop (round the face beside it
    that faces you), Select Other Loop (the face on its other side), Select Chain
    (open edges joined end to end; Select Closed Loop when they come back round).
    The count of edges each adds is shown. Elsewhere, FreeCAD's own menu, as before.
  - The chain button beside such a list offers the same for the last edge picked.
  - Edges already in the box are skipped, so a helper only adds.
- **Departure:** on a solid every corner has three edges, so Select Chain stops at
  once there; it is for the open edges of surfaces (and sketch curves). SolidWorks
  also has Select Partial Loop and Select Midpoint; not here.

## Preview colour follows what the tool does (2026-11-21, owner's request)
- Green adds, red removes, measured on the bodies the feature changes (their
  volume; their area when there are only surface bodies), not set per tool. So
  Delete Body, Keep Body, Combine Subtract or Common, Shell, a pattern or mirror
  of a cut, a face moved in, a groove or vent, and a fillet or chamfer on an
  outside edge preview red; a fillet in an inside corner, a face moved out or a
  boss preview green. A move or split, which neither adds nor removes, stays
  green. Fillet, Chamfer and Draft keep the old body drawn as it is while red
  (their edges and faces are picked on it); the other tools show the result
  with the removed material in dashed red, as cuts do.

## Picking by letters on the command line (2026-11-21, owner's idea)

No SolidWorks equivalent; it is Vimium's link hints, for CAD.
- `sel=` on the command line puts a home-row label (jj, jf, kd...) on every face,
  edge or vertex in view that the tool can use: Fillet and Chamfer label edges,
  Shell and Draft faces, Sketch and Hole planar faces, Plane all three; with no
  tool, faces and edges. `e=`, `f=`, `v=` label only edges, faces or vertices.
- Only what can be seen is labelled: an element behind the model, or facing away,
  gets none. Labels are two letters, three past 81, all the same length so none
  starts another; the easiest go nearest the middle of the view.
- Labels are white. Typing a label picks the element (it is selected, its label
  turns green) and adds the comma. Clicking a label does the same; clicking a
  green one takes it out again. Clicks anywhere else go to the view as usual.
  Tab-completing `sel=` shows the labels at once. Typing its first letter hides the labels that don't start with
  it. Backspace into a label unpicks it.
- Enter runs the tool on what was picked: `:fillet 2 sel=jk,dl`. `:sel=jk,dl`
  alone leaves them selected for the next tool. Esc drops the picks.
- Turning or zooming the view labels what can be seen then; picked elements keep
  their labels. The context toolbar stays away while the command line is open.

## Right-click menus in the 3D view (2026-11-21, owner's request)

Solid Design's own, made from scratch, one per thing under the pointer; FreeCAD's
menu is switched off for the click (setPopupMenuEnabled) only while Solid Design
is the workbench and no tool or sketch is open, and comes back otherwise (and when
leaving the workbench). Right-drag navigation is untouched: only a click opens one.
Right-clicking selects what's under the pointer, unless it's already selected (then
the menu acts on the selection), as SolidWorks. The context toolbar shows above it,
as SolidWorks' does.

- **Empty space:** Command Search, Command Line, Repeat <last feature>; Sketch,
  Part, Reference Geometry; View (fit, standard views, perspective/orthographic,
  draw style); Exit Isolate, Show Hidden Bodies; Rebuild, What's Wrong; Undo, Redo.
- **Face:** Sketch on Face, Extrude from Face, Edit <the feature that made it>;
  Fillet, Chamfer, Shell, More Face Tools (Draft, Dome, Move Face, Offset Surface,
  Delete Face, Replace Face, Thicken); Plane on Face, Normal To, Zoom to Selection,
  Measure; Select Tangency, Clarify Selection; Body (Hide, Isolate, Move/Copy,
  Combine, Split, Delete/Keep, Appearance, Random Color).
- **Edge:** Fillet, Chamfer, Edit <feature>; Reference Geometry (axis along, plane
  normal to, point on the edge), Zoom to Selection, Measure; Select Tangency,
  Clarify Selection; Body.
- **Vertex:** Point at Vertex, Coordinate System at Vertex, Edit <feature>; Zoom,
  Measure, Clarify Selection; Body.
- **A plane, axis or sketch:** Sketch on Plane / Edit Sketch, Extrude, Revolve;
  Edit; Normal To, Zoom; Hide, Delete.
- "The feature that made it" is the earliest feature whose own result (what it
  added, removed or changed) has a face (edge, vertex) through the clicked one.
