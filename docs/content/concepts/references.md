# How features remember picks

A fillet remembers the edges you picked, a sketch the face it sits on. When the model changes, those
edges and faces are rebuilt and their FreeCAD names (Edge7, Face3) can change, which breaks many
models. Solid Design remembers more than the name.

## A fingerprint of each pick

With every pick, the feature keeps a fingerprint: what kind of element it is, its shape, its size,
where it sits, and points along it. After a change it looks for the element with the same
fingerprint, so it finds the same edge even with a new name.

## Found again, or lost

- **Found again:** the element changed (moved, resized) but one clearly matches. The feature uses
  it and warns you, so you can check. Press **Looks Right** in What's Wrong to accept it.
- **Lost:** nothing matches, or several match equally. The feature can't be built until you pick
  again. What's Wrong shows where it was, and which earlier feature changed the model there.

See [when something breaks](../guides/fixing-problems.md).
