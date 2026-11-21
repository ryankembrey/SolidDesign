# SPDX-License-Identifier: LGPL-2.1-or-later
"""What's wrong with a document, and what to do about it (What's Wrong and the
health badge use this).

Each problem is an Issue: what it is on (a feature, a reference geometry item, a
sketch, a body), how bad (error or warning), what happened in plain words, what
to do, and, where it can be told, why: the problem upstream it follows from, or
the feature before it that changed the model where a reference was. Lost and
repaired references carry where they were (from their fingerprints) and what
they are now, so the view can show both.
"""

import FreeCAD as App

from . import part as part_mod
from . import refs, util

ERROR, WARNING = "error", "warning"
TINY_EDGE = 0.01            # mm: shorter edges trouble fillets, shells and exports
SLIVER = 0.005              # mm: a face thinner than this (area / perimeter)

WORDS = {"Edge": "edge", "Face": "face", "Vertex": "vertex"}


class Issue(object):
    def __init__(self, obj, part, severity, message, kind="feature"):
        self.obj = obj
        self.part = part
        self.severity = severity
        self.message = message
        self.kind = kind            # feature, sketch, geometry
        self.hint = ""
        self.why = ""
        self.cause = None           # the Issue this one follows from
        self.children = []
        self.repaired = []          # refs.repairs() entries
        self.lost = []              # refs.lost() entries
        self.culprit = None         # the feature that changed the model there
        self.elements = []          # geometry check: [(shape, text)]

    @property
    def title(self):
        return part_mod.clean_label(self.obj.Label) if self.obj is not None else ""

    def is_error(self):
        return self.severity == ERROR


def _word(fp):
    return WORDS.get((fp or {}).get("kind", ""), "element")


def _items(part):
    """The part's features, reference geometry and sketches, in tree order, that
    are built now (not below the rollback bar, not suppressed)."""
    out = []
    for o in part.Group:
        if util.is_feature(o) or util.role(o) == "refgeom" or \
                o.TypeId.startswith("Sketcher::SketchObject"):
            if getattr(o, "RolledBack", False) or getattr(o, "Suppressed", False):
                continue
            out.append(o)
    return out


def _near(shape, pts, tol):
    import Part
    if shape is None or shape.isNull() or not pts:
        return False
    picks = pts if len(pts) <= 5 else [pts[0], pts[len(pts) // 4], pts[len(pts) // 2],
                                        pts[3 * len(pts) // 4], pts[-1]]
    for p in picks:
        try:
            if Part.Vertex(App.Vector(*p)).distToShape(shape)[0] <= tol:
                return True
        except Exception:
            pass
    return False


def culprit(obj, fp, origin=""):
    """The last feature between ``origin`` (the one the reference was picked on)
    and ``obj`` that changed the model where the reference (fingerprint ``fp``)
    was: most likely what lost or moved it."""
    part = util.part_of(obj)
    if part is None or not fp:
        return None
    feats = util.features(part)
    before = feats[:feats.index(obj)] if obj in feats else feats
    start = next((k for k, f in enumerate(before) if f.Name == origin), None)
    if start is not None:
        before = before[start + 1:]
    pts = fp.get("pts") or ([fp["c"]] if fp.get("c") else [])
    try:
        tol = 1e-3 * max(part_mod.body_views(part)[0].Shape.BoundBox.DiagonalLength, 1.0)
    except Exception:
        tol = 1e-3
    found = None
    for f in before:
        if _near(getattr(f, "AddSubShape", None), pts, tol):
            found = f
    return found


def _explain(issue):
    """The plain words: why (if known) and what to do."""
    o = issue.obj
    if issue.kind == "sketch":
        issue.hint = ("If the face or plane it was on is gone, edit the sketch's "
                      "attachment (Attachment editor) to put it back on one; otherwise "
                      "open the sketch and fix its geometry or constraints.")
        return
    if issue.repaired and not issue.is_error():
        r = issue.repaired[0]
        w = _word(r.get("old") or r.get("new"))
        issue.hint = ("An earlier change rebuilt this {w}, and Solid Design found it again "
                      "by its shape and place. Check that the green {w} is the one you "
                      "meant: if it is, press Looks Right; if not, Edit the feature and pick "
                      "it again.").format(w=w)
        issue.culprit = culprit(o, r.get("old"), r.get("origin", ""))
    elif issue.lost:
        r = issue.lost[0]
        w = _word(r.get("old"))
        if "could replace it" in (r.get("msg") or ""):
            issue.hint = ("Several {w}s now look like the lost one (numbered in the view). "
                          "Edit the feature and pick the right one.").format(w=w)
        else:
            issue.hint = ("The {w} it was built on isn't in the model any more. Edit the "
                          "feature and pick another, or Roll Back to Here to see the model "
                          "as it was just before it.").format(w=w)
        issue.culprit = culprit(o, r.get("old"), r.get("origin", ""))
    elif issue.is_error():
        issue.hint = "Edit the feature: its panel shows the problem and what it needs."
    else:
        issue.hint = "Edit the feature to look at it."
    if issue.culprit is not None:
        issue.why = u"{} changed the model there.".format(
            part_mod.clean_label(issue.culprit.Label))


def _issue_for(o, part, explain=True):
    if o.TypeId.startswith("Sketcher::SketchObject"):
        if o.isValid():
            return None
        status = (o.getStatusString() or "it can't be built").strip()
        i = Issue(o, part, ERROR, u"The sketch can't be built: {}".format(status), "sketch")
        if explain:
            _explain(i)
        return i
    err = getattr(o, "ErrorMessage", "") or ""
    warn = getattr(o, "WarningMessage", "") or ""
    if not err and not o.isValid():
        err = (o.getStatusString() or "It failed to rebuild.").strip()
    if not err and not warn:
        return None
    i = Issue(o, part, ERROR if err else WARNING, err or warn)
    i.repaired = refs.repairs(o) if "RefRepairs" in o.PropertiesList else []
    i.lost = refs.lost(o) if "RefLost" in o.PropertiesList else []
    if explain:
        _explain(i)
    return i


def issues(doc, explain=True):
    """[Issue] of every part, in model order; one that follows from another (it
    uses a broken sketch or feature, or lost a reference after an earlier error)
    is among that one's children instead."""
    top = []
    for part in part_mod.find_parts(doc):
        by_obj = {}
        last_error = None
        for o in _items(part):
            i = _issue_for(o, part, explain)
            if i is None:
                continue
            base = getattr(o, "BaseFeature", None)
            deps = [d for d in o.OutList if d is not base and d in by_obj and
                    by_obj[d].is_error()]
            if deps:
                i.cause = by_obj[deps[-1]]
            elif i.lost and last_error is not None:
                i.cause = last_error
            if i.cause is not None:
                root = i.cause
                while root.cause is not None:
                    root = root.cause
                root.children.append(i)
                # The problem upstream comes first: it is the likelier cause.
                i.why = (u"It may come right once {} is fixed: fix that first. {}".format(
                    i.cause.title, i.why)).strip()
            else:
                top.append(i)
            by_obj[o] = i
            if i.is_error():
                last_error = i
    return top


def flat(items):
    out = []
    for i in items:
        out.append(i)
        out.extend(flat(i.children))
    return out


def counts(doc):
    """(errors, warnings) in ``doc``."""
    all_ = flat(issues(doc, explain=False)) if doc is not None else []
    e = sum(1 for i in all_ if i.is_error())
    return e, len(all_) - e


# ------------------------------------------------------------------ geometry check

def check_geometry(doc):
    """[Issue] for bodies that would trouble later features: not a valid solid,
    edges shorter than TINY_EDGE, faces thinner than SLIVER. Each names the
    feature that made the element, where it can be told."""
    out = []
    for part in part_mod.find_parts(doc):
        for v in part_mod.body_views(part):
            sh = v.Shape
            if sh.isNull():
                continue
            if sh.Solids and not sh.isValid():
                i = Issue(v, part, ERROR, u"The body's geometry is not valid; features "
                          u"after it may fail on it.", "geometry")
                i.hint = ("Roll back to find the feature that first makes it invalid, and "
                          "change that feature (often a fillet or shell too big for the "
                          "model).")
                out.append(i)
            tiny = [e for e in sh.Edges if not getattr(e, "Degenerated", False) and
                    e.Length < TINY_EDGE]
            if tiny:
                i = Issue(v, part, WARNING, u"{} tiny edge{} (under {} mm).".format(
                    len(tiny), "s" if len(tiny) > 1 else "", TINY_EDGE), "geometry")
                i.elements = [(e, u"Tiny edge {:.4g} mm".format(e.Length)) for e in tiny]
                _made_by(i, part, tiny[0])
                i.hint = ("Tiny edges make fillets, chamfers and shells fail and slow the "
                          "model down. Usually two features almost line up: make them meet "
                          "exactly, or move one clear.")
                out.append(i)
            thin = []
            for f in sh.Faces:
                try:
                    per = sum(e.Length for e in f.Edges)
                    if per > 0 and f.Area / per < SLIVER:
                        thin.append(f)
                except Exception:
                    pass
            if thin:
                i = Issue(v, part, WARNING, u"{} sliver face{} (thinner than {} mm)."
                          .format(len(thin), "s" if len(thin) > 1 else "", SLIVER), "geometry")
                i.elements = [(f, u"Sliver face") for f in thin]
                _made_by(i, part, thin[0])
                i.hint = ("A face this thin comes from two features almost, but not quite, "
                          "meeting. Make them meet exactly or move one clear.")
                out.append(i)
    return out


def _made_by(issue, part, elem):
    try:
        f = part_mod.feature_of_element(part, elem)
    except Exception:
        f = None
    if f is not None:
        issue.culprit = f
        issue.why = u"Made by {}.".format(part_mod.clean_label(f.Label))
