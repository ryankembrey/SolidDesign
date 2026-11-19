# SPDX-License-Identifier: LGPL-2.1-or-later
"""Surface mode of the sketch features (SolidWorks' Extruded, Revolved, Swept,
Lofted and Boundary Surface): the profile's curves swept into faces instead of
its regions into solids.

Helpers shared by those features: the profile as wires, trimming a long sheet
back to the part that starts at the profile, and sewing faces into shells.
"""

import Part

from .. import topo

SURFACE = "Surface"
MODES = ["Add", "Cut", SURFACE]


def wires_of(faces, open_wires):
    """Every curve of the profile: the regions' boundaries and the open chains."""
    out = []
    for f in faces:
        out.extend(f.Wires)
    out.extend(open_wires)
    return out


def shells(faces, tag, tol=1e-6):
    """Faces sewn into as few shells as they make (a compound when several)."""
    faces = [f for f in faces if f is not None and not f.isNull()]
    if not faces:
        raise topo.GeometryError("The surface came out empty.")
    sewn = Part.makeCompound(faces)
    try:
        sewn.sewShape(tol)
    except TypeError:
        sewn.sewShape()
    except Exception:
        pass
    out = list(sewn.Shells) if sewn.ShapeType != "Shell" else [sewn]
    inside = [g for s in out for g in s.Faces]
    # A face on its own is a one-face shell, so every piece reads as a surface body.
    out.extend(Part.Shell([f]) for f in sewn.Faces if not any(f.isSame(g) for g in inside))
    return topo.tagged(out[0] if len(out) == 1 else Part.makeCompound(out), tag)


def near(pieces, ref, tol=1e-6):
    """The pieces that touch ``ref`` (the profile): a long sheet cut by a surface
    or a body keeps the part that starts at the profile."""
    return [p for p in pieces if p.distToShape(ref)[0] <= tol]


def shell_of(solid_shape, tag):
    """A solid's boundary as a closed surface (Cap end)."""
    solids = solid_shape.Solids
    if not solids:
        raise topo.GeometryError("Cap end needs a closed profile.")
    out = []
    for s in solids:
        out.extend(s.Shells)
    return topo.tagged(out[0] if len(out) == 1 else Part.makeCompound(out), tag)


def trimmed(long_sheet, tools, profile, tag, what):
    """``long_sheet`` cut by ``tools`` (faces, or solids for Up To Next/Body), kept
    from the profile to the first crossing."""
    try:
        pieces = topo.slice_by(long_sheet, tools, tag).Faces
    except topo.GeometryError:
        pieces = topo.general_fuse(long_sheet, tools, tag).Faces
    keep = near(pieces, profile)
    if not keep or len(pieces) <= len(long_sheet.Faces):
        raise topo.GeometryError("{}: the surface doesn't reach it.".format(what))
    return shells(keep, tag)


def cut_by_bodies(long_sheet, bodies, profile, tag, what):
    """Up To Next / Up To Body: the sheet up to where it enters the bodies."""
    pieces = topo.cut(long_sheet, bodies, tag).Faces
    keep = near(pieces, profile)
    if not keep or abs(sum(f.Area for f in pieces) - long_sheet.Area) < 1e-9:
        raise topo.GeometryError("{}: nothing is in the way of the surface.".format(what))
    return shells(keep, tag)
