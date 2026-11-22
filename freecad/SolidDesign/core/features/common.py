# SPDX-License-Identifier: LGPL-2.1-or-later
"""Options most features share (spec section 5.4), written once.

- Merge result (Add mode)
- Feature scope (Cut mode, and Add mode with Merge result)
- Bodies to Keep (a Cut that splits bodies)

These functions take a tool shape and a BodySet and return a new BodySet. The
provenance of every result body is known by construction (each body in scope is
handled on its own), so IDs follow the rules in core/bodies.py.
"""

from .. import topo
from ..bodies import SOLID, SURFACE, assign_by_overlap, pieces_of, split_pieces


class Scope(object):
    """Feature scope: All bodies, or Selected bodies (stored as body IDs).

    SolidWorks: bodies made after the feature was created (before it in the
    history) are included under All bodies and not under Selected bodies.
    """

    def __init__(self, all_bodies=True, ids=(), exclude=()):
        self.all = all_bodies
        self.ids = list(ids)
        self.exclude = list(exclude)    # never in scope (a sweep's tool body)

    def pick(self, body_set, kind=None):
        """Body IDs in scope, in the body set's order."""
        ids = [i for i in body_set.ids(kind) if i not in self.exclude]
        if self.all:
            return ids
        wanted = set(self.ids)
        return [i for i in ids if i in wanted]

    def missing(self, body_set):
        """Selected IDs that don't exist in the incoming body set."""
        if self.all:
            return []
        return [i for i in self.ids if i not in body_set]


class Keep(object):
    """Bodies to Keep: All bodies, or Selected bodies (piece IDs)."""

    def __init__(self, all_bodies=True, ids=()):
        self.all = all_bodies
        self.ids = set(ids)


class Result(object):
    """What a shared operation produced, for the feature and its panel."""

    def __init__(self, bodies):
        self.bodies = bodies
        self.pieces = []        # [(piece_id, shape, parent_id)] when bodies split
        self.touched = []       # IDs changed by the operation
        self.created = []       # IDs created
        self.warnings = []
        self.contact = None     # apply_cut: IDs of the bodies the tool touches


def apply_add(base, tool, feature, tag, merge, scope, alloc):
    """Add mode: fuse ``tool`` into the bodies it touches, or make new bodies.

    ``tool`` may hold several separate solids (e.g. two sketch regions); each
    group of tool solids and the scoped bodies they touch merges into one body
    that keeps the ID of the first body in scope order.
    """
    out = base.copy()
    res = Result(out)
    tsolids = topo.solids(tool)
    tsurfs = [] if tsolids else pieces_of(tool, SURFACE)
    if tsurfs:
        ids = alloc.take(tsurfs)
        for i, s in zip(ids, tsurfs):
            out.add(i, s, feature, SURFACE)
            res.created.append(i)
        return res
    if not tsolids:
        raise topo.GeometryError("The feature made no solid.")

    candidates = scope.pick(base, SOLID) if merge else []
    # touched[t] = scoped bodies each tool solid touches
    touched = []
    # topo.touches for every pair, with each box looked up once (a pattern merged
    # into hundreds of bodies is hundreds of thousands of pairs).
    cshapes = [base.get(bid).shape for bid in candidates]
    cboxes = [topo.bbox(s) for s in cshapes]
    for ts in tsolids:
        tb = topo.bbox(ts)
        row = []
        for bid, s, cb in zip(candidates, cshapes, cboxes):
            if topo.box_gap(cb, tb):
                continue
            try:
                if s.distToShape(ts)[0] <= topo.LIN_TOL:
                    row.append(bid)
            except Exception:
                pass
        touched.append(row)
    rank = {b: i for i, b in reversed(list(enumerate(candidates)))}

    # Group tool solids that share a body (union-find over tool solids).
    parent = list(range(len(tsolids)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner = {}
    for ti, bids in enumerate(touched):
        for bid in bids:
            if bid in owner:
                parent[find(ti)] = find(owner[bid])
            else:
                owner[bid] = ti
    groups = {}
    for ti in range(len(tsolids)):
        groups.setdefault(find(ti), []).append(ti)

    loose = []
    for g in groups.values():
        bids = sorted({b for ti in g for b in touched[ti]}, key=rank.__getitem__)
        if not bids:
            loose.extend(tsolids[ti] for ti in g)
            continue
        first = bids[0]
        others = [base.get(b).shape for b in bids[1:]] + [tsolids[ti] for ti in g]
        fused = topo.refine(topo.fuse(base.get(first).shape, others, tag), tag)
        parts = pieces_of(fused, SOLID)
        if len(parts) == 1:
            out.replace(first, parts[0], feature)
            alloc.keep(first, parts[0])
            for b in bids[1:]:
                out.remove(b)
            res.touched.append(first)
        else:
            # Touching only along an edge or a point: OCC leaves separate solids.
            inputs = [(b, base.get(b).shape) for b in bids]
            for b in bids:
                out.remove(b)
            for bid, s in assign_by_overlap(inputs, parts, alloc):
                if bid in out.deleted:
                    out.deleted.remove(bid)
                out.add(bid, s, feature)
                res.touched.append(bid)
    if loose:
        ids = alloc.take(loose)
        for i, s in zip(ids, loose):
            out.add(i, s, feature, SOLID)
            res.created.append(i)
    return res


def apply_cut(base, tool, feature, tag, scope, keep, alloc, flip=False):
    """Cut mode: remove ``tool`` from each body in scope.

    ``flip`` (Flip side to cut) keeps the material inside the tool instead.
    A body cut into pieces keeps its ID on the largest piece; the other pieces
    get new IDs. Bodies to Keep then removes the pieces not wanted.
    """
    out = base.copy()
    res = Result(out)
    if tool is None or tool.isNull() or not (tool.Solids or tool.Faces):
        raise topo.GeometryError("The cut made no tool shape.")
    if not flip:
        res.contact = set()
    parts_of_tool = topo.tool_parts(tool)
    for bid in scope.pick(base):
        body = base.get(bid)
        if not flip:
            if not topo.touches_any(body.shape, tool, parts_of_tool):
                alloc.keep(bid, body.shape)
                continue
            res.contact.add(bid)
        elif topo.boxes_apart(body.shape, tool):
            # Kept inside a tool it is nowhere near: nothing is left of it (what
            # the boolean would give, without running it).
            out.remove(bid)
            res.touched.append(bid)
            continue
        if flip:
            r = topo.common(body.shape, [tool], tag)
        else:
            r = topo.cut(body.shape, [tool], tag)
        if body.kind == SOLID:
            r = topo.refine(r, tag)
        parts = pieces_of(r, body.kind)
        parts = [p for p in parts if topo.size_of(p) > 1e-9]
        if not parts:
            out.remove(bid)
            res.touched.append(bid)
            continue
        if len(parts) == 1:
            if abs(topo.size_of(parts[0]) - topo.size_of(body.shape)) > 1e-9 or flip:
                out.replace(bid, parts[0], feature)
                res.touched.append(bid)
            alloc.keep(bid, parts[0])
            continue
        named = split_pieces(bid, parts, alloc)
        out.replace(bid, named[0][1], feature)
        res.touched.append(bid)
        out.insert_many_after(bid, [(pid, s, feature) for pid, s in named[1:]])
        res.created.extend(pid for pid, _s in named[1:])
        res.pieces.extend((pid, s, bid) for pid, s in named)

    if res.pieces and not keep.all:
        known = {p[0] for p in res.pieces}
        stale = [i for i in keep.ids if i not in known]
        if stale and not (keep.ids & known):
            res.warnings.append("The pieces picked in Bodies to Keep no longer exist; "
                                "all pieces were kept. Pick them again.")
        else:
            for pid, _s, _parent in res.pieces:
                if pid not in keep.ids:
                    out.remove(pid)
    return res


def removed_material(tool, base, scope, tag, cut=None):
    """What a cut takes away, for the preview (spec 8.2). ``cut``: the Result of
    the cut just made with this tool, which already knows what it touches."""
    contact = getattr(cut, "contact", None)
    if contact is not None:
        shapes = [base.get(b).shape for b in scope.pick(base, SOLID) if b in contact]
    else:
        shapes = [base.get(b).shape for b in scope.pick(base, SOLID)]
        shapes = [s for s in shapes if topo.touches(s, tool)]
    if not shapes:
        return tool
    try:
        parts = [topo.common(tool, [s], tag) for s in shapes]
        parts = [p for p in parts if p.Solids]
        return topo.compound(parts, tag) if parts else tool
    except topo.GeometryError:
        return tool
