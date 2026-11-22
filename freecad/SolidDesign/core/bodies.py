# SPDX-License-Identifier: LGPL-2.1-or-later
"""Body sets and stable body IDs (spec section 5.2).

A *body* is one solid or one surface (a shell or face set) with an ID that lasts
its whole life. Features never refer to bodies by index; they store IDs.

ID rules (SolidWorks' where it has one):
- A feature that creates bodies names them ``<FeatureName>:<n>``. ``n`` is kept
  across recomputes by matching each new body to the bodies this feature made
  last time (nearest centroid, similar size), so editing upstream doesn't
  renumber them.
- When bodies merge, the result keeps the ID of the first body in the feature's
  scope order.
- When a body splits, the largest piece keeps the ID; the other pieces get new
  IDs (matched to last time's pieces the same way).
- When the provenance of a result isn't known by construction, the input with
  the largest volume overlap gives its ID (``assign_by_overlap``).
"""

import json
from collections import OrderedDict

import FreeCAD as App
import Part

from . import topo

SOLID = "solid"
SURFACE = "surface"


def kind_of(shape):
    return SOLID if shape.Solids else SURFACE


class Body(object):
    __slots__ = ("id", "shape", "kind", "feature")

    def __init__(self, body_id, shape, kind=None, feature=""):
        self.id = body_id
        self.shape = shape
        self.kind = kind or kind_of(shape)
        self.feature = feature      # Name of the last feature that changed it

    def __repr__(self):
        return "<Body {} {} by {}>".format(self.id, self.kind, self.feature)


class BodySet(object):
    """An ordered mapping of body ID to Body, plus the IDs a feature deleted."""

    def __init__(self, bodies=None):
        self._b = OrderedDict()
        self.deleted = []
        for b in bodies or []:
            self._b[b.id] = b

    # -- access
    def __len__(self):
        return len(self._b)

    def __iter__(self):
        return iter(self._b.values())

    def __contains__(self, body_id):
        return body_id in self._b

    def get(self, body_id):
        return self._b.get(body_id)

    def ids(self, kind=None):
        return [b.id for b in self._b.values() if kind is None or b.kind == kind]

    def bodies(self, kind=None):
        return [b for b in self._b.values() if kind is None or b.kind == kind]

    def copy(self):
        bs = BodySet([Body(b.id, b.shape, b.kind, b.feature) for b in self])
        return bs

    # -- edits (they keep order: a replaced body stays where it was)
    def add(self, body_id, shape, feature, kind=None):
        if body_id in self._b:
            raise ValueError("Duplicate body ID " + body_id)
        self._b[body_id] = Body(body_id, shape, kind, feature)

    def replace(self, body_id, shape, feature):
        b = self._b[body_id]
        self._b[body_id] = Body(body_id, shape, kind_of(shape), feature)
        return b

    def remove(self, body_id):
        if body_id in self._b:
            del self._b[body_id]
            self.deleted.append(body_id)

    def insert_many_after(self, after_id, items):
        """Add bodies [(id, shape, feature)] just after another one, in order (one
        rebuild of the order, not one per body)."""
        items = list(items)
        old = list(self._b.items())
        self._b.clear()
        done = False
        for k, v in old:
            self._b[k] = v
            if k == after_id:
                for body_id, shape, feature in items:
                    self._b[body_id] = Body(body_id, shape, None, feature)
                done = True
        if not done:
            for body_id, shape, feature in items:
                self._b[body_id] = Body(body_id, shape, None, feature)

    def insert_after(self, after_id, body_id, shape, feature):
        """Add a body just after another one (split pieces stay together)."""
        items = list(self._b.items())
        self._b.clear()
        done = False
        for k, v in items:
            self._b[k] = v
            if k == after_id:
                self._b[body_id] = Body(body_id, shape, None, feature)
                done = True
        if not done:
            self._b[body_id] = Body(body_id, shape, None, feature)

    # -- storage on a feature
    def to_compound(self, tag):
        shapes = [b.shape for b in self]
        if not shapes:
            return Part.makeCompound([])
        return topo.compound(shapes, tag)

    def columns(self):
        return ([b.id for b in self], [b.kind for b in self], [b.feature for b in self])

    @classmethod
    def from_columns(cls, compound, ids, kinds, features):
        bs = cls()
        if compound is None or compound.isNull() or not ids:
            return bs
        children = compound.childShapes() if compound.ShapeType == "Compound" else [compound]
        if len(children) != len(ids):
            raise topo.GeometryError(
                "The stored bodies don't match their IDs ({} shapes, {} IDs). "
                "Recompute the part.".format(len(children), len(ids)))
        for i, s in enumerate(children):
            if not s.Tag and compound.Tag:
                s.Tag = compound.Tag
            kind = kinds[i] if i < len(kinds) else None
            feat = features[i] if i < len(features) else ""
            bs._b[ids[i]] = Body(ids[i], s, kind, feat)
        return bs


# ---------------------------------------------------------------- ID memory

class IdAllocator(object):
    """Gives IDs to bodies a feature makes, the same ones on every recompute.

    ``memory`` is what the feature stored last time: {id: [x, y, z, size]}.
    """

    def __init__(self, feature_name, memory=None, taken=()):
        self.feature = feature_name
        self.memory = dict(memory or {})
        self.used = set(taken)
        self.new_memory = {}
        self._by_prefix = None

    def _remembered(self, prefix):
        """Remembered IDs with a prefix, in memory order (indexed once: a split of
        hundreds of bodies takes IDs once per body)."""
        if self._by_prefix is None:
            self._by_prefix = {}
            for k in self.memory:
                self._by_prefix.setdefault(k.rsplit(":", 1)[0], []).append(k)
        return self._by_prefix.get(prefix, ())

    @staticmethod
    def loads(text):
        try:
            return json.loads(text) if text else {}
        except ValueError:
            return {}

    def dumps(self):
        return json.dumps(self.new_memory, sort_keys=True)

    def _record(self, body_id, shape):
        c = topo.centroid(shape)
        self.new_memory[body_id] = [round(c.x, 6), round(c.y, 6), round(c.z, 6),
                                    round(topo.size_of(shape), 6)]
        self.used.add(body_id)

    def keep(self, body_id, shape):
        """Record a body that keeps an existing ID (so memory stays complete)."""
        self._record(body_id, shape)
        return body_id

    def take(self, shapes, prefix=None):
        """IDs for new bodies, in the order of ``shapes``.

        Each shape is matched to the closest remembered body with the same
        prefix; unmatched shapes get the next free number.
        """
        prefix = prefix or self.feature
        cands = {k: self.memory[k] for k in self._remembered(prefix) if k not in self.used}
        ids = [None] * len(shapes)
        taken_k = set()
        if cands and shapes:
            left = len(shapes)
            for i, k in _best_pairs(shapes, cands):
                if ids[i] is None and k not in taken_k:
                    ids[i] = k
                    taken_k.add(k)
                    left -= 1
                    if not left or len(taken_k) == len(cands):
                        break               # nothing more can be matched
        n = 1
        for i, s in enumerate(shapes):
            if ids[i] is None:
                while True:
                    cand = "{}:{}".format(prefix, n)
                    n += 1
                    if cand not in self.used and cand not in taken_k and cand not in self.memory:
                        break
                ids[i] = cand
            self._record(ids[i], s)
        return ids


def _best_pairs(shapes, cands):
    """(shape index, remembered ID) pairs, best first: nearest centre for the size,
    skipping sizes too different. Greedy matching takes them in this order.

    Worked out for all pairs at once (400 new bodies against 400 remembered ones
    is 160,000 pairs); the same scores, in the same order (ties by index, then
    ID), as scoring each pair in turn."""
    keys = list(cands)
    cs = [topo.centroid(s) for s in shapes]
    sizes = [topo.size_of(s) for s in shapes]
    if len(shapes) * len(keys) > 4000000:          # too many to hold: one at a time
        pairs = []
        for i, c in enumerate(cs):
            size = sizes[i]
            for k in keys:
                m = cands[k]
                d = (App.Vector(m[0], m[1], m[2]) - c).Length
                ratio = (min(size, m[3]) / max(size, m[3])) if max(size, m[3]) > 0 else 1.0
                if ratio < 0.2:
                    continue
                pairs.append((d / max(ratio, 1e-6), i, k))
        pairs.sort()
        return [(i, k) for _s, i, k in pairs]
    import numpy as np
    mem = np.array([cands[k] for k in keys], dtype=float)           # [x, y, z, size]
    pts = np.array([[c.x, c.y, c.z] for c in cs], dtype=float)
    sz = np.array(sizes, dtype=float)
    diff = mem[None, :, :3] - pts[:, None, :]
    d = np.sqrt(diff[..., 0] * diff[..., 0] + diff[..., 1] * diff[..., 1] +
                diff[..., 2] * diff[..., 2])
    hi = np.maximum(sz[:, None], mem[None, :, 3])
    lo = np.minimum(sz[:, None], mem[None, :, 3])
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(hi > 0, lo / np.where(hi > 0, hi, 1.0), 1.0)
    ii, kk = np.nonzero(ratio >= 0.2)
    score = d[ii, kk] / np.maximum(ratio[ii, kk], 1e-6)
    rank = np.empty(len(keys), dtype=int)
    rank[np.argsort(np.array(keys, dtype=object), kind="stable")] = np.arange(len(keys))
    order = np.lexsort((rank[kk], ii, score))
    return [(int(ii[j]), keys[kk[j]]) for j in order]


# ---------------------------------------------------------------- ID rules

def split_pieces(body_id, pieces, alloc):
    """IDs for the pieces of a body that was split: the largest keeps the ID.

    Returns [(id, shape)] with the kept piece first, the rest by size.
    """
    order = sorted(pieces, key=topo.size_of, reverse=True)
    first = order[0]
    alloc.keep(body_id, first)
    rest = order[1:]
    ids = alloc.take(rest, prefix=body_id) if rest else []
    return [(body_id, first)] + list(zip(ids, rest))


def assign_by_overlap(inputs, results, alloc):
    """Give result shapes the IDs of the inputs they overlap most.

    ``inputs``: [(id, shape)] in scope order. Each input ID goes to at most one
    result (the one it overlaps most); results with no overlap get new IDs.
    Returns [(id, shape)] in the order of ``results``.
    """
    scores = []
    for ri, r in enumerate(results):
        for ii, (iid, ishape) in enumerate(inputs):
            v = topo.overlap_volume(r, ishape)
            if v > 0:
                scores.append((-v, ii, ri, iid))
    scores.sort()
    out = [None] * len(results)
    used_inputs = set()
    for _v, _ii, ri, iid in scores:
        if out[ri] is None and iid not in used_inputs:
            out[ri] = iid
            used_inputs.add(iid)
            alloc.keep(iid, results[ri])
    fresh = [r for ri, r in enumerate(results) if out[ri] is None]
    fresh_ids = alloc.take(fresh) if fresh else []
    it = iter(fresh_ids)
    for ri in range(len(results)):
        if out[ri] is None:
            out[ri] = next(it)
    return list(zip(out, results))


def pieces_of(shape, kind):
    """The separate bodies inside a boolean result."""
    if shape is None or shape.isNull():
        return []
    if kind == SOLID:
        return list(shape.Solids)
    if shape.Shells:
        return list(shape.Shells)
    return list(shape.Faces)
