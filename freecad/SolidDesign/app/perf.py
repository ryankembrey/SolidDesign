# SPDX-License-Identifier: LGPL-2.1-or-later
"""Speed tracing for Solid Design: where the time goes, and how often things are
recomputed.

Off, it costs one boolean test per traced call. On, it records:

- **spans**: named, nested pieces of work (opening a panel, a feature's execute,
  a recompute, a preview), each with its time and what it was inside;
- **counts**: how often each feature was recomputed, per document recompute;
- with ``cprofile``, a full Python profile of each top-level span.

Turn it on with the environment variable ``SD_PROFILE=1`` (or ``cprofile``)
before starting FreeCAD, from Solid Design → Performance Trace, or from Python:

    from freecad.SolidDesign.app import perf
    perf.start()            # perf.start(cprofile=True) for a full profile
    ...                     # do the slow thing
    print(perf.stop())      # the report; also written to perf.report_path()

A top-level span slower than ``SLOW`` seconds is reported in the Report view as
it happens, with what took the time inside it. In the GUI, the time until FreeCAD
is idle again (redrawing, tessellating) is added to each top-level span.

Usage in the code:

    with perf.span("panel.open", obj.Label):
        ...

    @perf.traced("part.sync")
    def sync(part): ...
"""

import collections
import contextlib
import functools
import io
import os
import tempfile
import time

import FreeCAD as App

#: A top-level span slower than this (seconds) is reported as it happens.
SLOW = 0.5

_on = [False]
_cprofile = [False]
_stack = []                 # open spans: [Span]
_done = []                  # finished top-level spans
_totals = collections.OrderedDict()     # name -> [count, total, own, max]
_counts = collections.Counter()         # (kind, name) -> n
_profiles = []              # (span, pstats text)
_started = [0.0]
MAX_KEPT = 200              # top-level spans kept for the report


class Span(object):
    __slots__ = ("name", "detail", "t0", "dt", "children", "idle")

    def __init__(self, name, detail=""):
        self.name, self.detail = name, str(detail) if detail else ""
        self.t0 = time.perf_counter()
        self.dt = 0.0
        self.children = []
        self.idle = None            # GUI: seconds until the event loop was idle again


def enabled():
    return _on[0]


def start(cprofile=False):
    """Start tracing (clears what was recorded)."""
    reset()
    _cprofile[0] = bool(cprofile)
    _on[0] = True
    _started[0] = time.perf_counter()
    _watch_documents(True)


def stop():
    """Stop tracing; returns the report (and writes it to report_path())."""
    text = report()
    _on[0] = False
    _watch_documents(False)
    try:
        with open(report_path(), "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass
    return text


def reset():
    del _stack[:]
    del _done[:]
    _totals.clear()
    _counts.clear()
    del _profiles[:]


def report_path():
    return os.path.join(tempfile.gettempdir(), "SolidDesign-perf.txt")


def count(kind, name=""):
    """Count an event (a feature recomputed, a document recompute...)."""
    if _on[0]:
        _counts[(kind, name)] += 1


@contextlib.contextmanager
def span(name, detail=""):
    """Time the block as ``name`` (``detail``: which one, e.g. a feature's label)."""
    if not _on[0]:
        yield
        return
    s = Span(name, detail)
    top = not _stack
    prof = None
    if top and _cprofile[0]:
        import cProfile
        prof = cProfile.Profile()
        prof.enable()
    _stack.append(s)
    try:
        yield
    finally:
        s.dt = time.perf_counter() - s.t0
        if _stack and _stack[-1] is s:
            _stack.pop()
        if prof is not None:
            prof.disable()
            _keep_profile(s, prof)
        _add_total(s)
        if _stack:
            _stack[-1].children.append(s)
        else:
            _done.append(s)
            if len(_done) > MAX_KEPT:
                del _done[0]
            _until_idle(s)
            if s.dt >= SLOW:
                App.Console.PrintMessage(u"Solid Design perf: slow: {}\n".format(
                    _tree_text(s, depth=3)))


def traced(name, detail=None):
    """Decorator: a span round each call. ``detail(*args)`` names which one."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **k):
            if not _on[0]:
                return fn(*a, **k)
            try:
                d = detail(*a) if detail else ""
            except Exception:
                d = ""
            with span(name, d):
                return fn(*a, **k)
        return wrapper
    return deco


def _add_total(s):
    own = s.dt - sum(c.dt for c in s.children)
    t = _totals.get(s.name)
    if t is None:
        _totals[s.name] = [1, s.dt, own, s.dt]
    else:
        t[0] += 1
        t[1] += s.dt
        t[2] += own
        t[3] = max(t[3], s.dt)


def _keep_profile(s, prof):
    import pstats
    out = io.StringIO()
    pstats.Stats(prof, stream=out).sort_stats("cumulative").print_stats(30)
    _profiles.append((s, out.getvalue()))
    if len(_profiles) > 20:
        del _profiles[0]


def _until_idle(s):
    """GUI: how long until FreeCAD has drawn the result (tessellation, redraws)."""
    if not App.GuiUp:
        return
    try:
        from PySide import QtCore
    except Exception:
        return
    t_end = time.perf_counter()

    def idle():
        s.idle = time.perf_counter() - t_end
    QtCore.QTimer.singleShot(0, idle)


# ------------------------------------------------------------------ documents

class _DocWatch(object):
    """Times each document recompute and counts what it recomputed.

    FreeCAD 1.1 doesn't tell Python when a recompute starts, so its span opens
    as the first object finishes, taking in that object's own span (a feature's
    execute) and starting where that one started."""

    def __init__(self):
        self.open = {}

    def _begin(self, doc):
        s = Span("document.recompute", doc.Name)
        siblings = _stack[-1].children if _stack else _done
        if siblings and siblings[-1].name == "feature" and \
                time.perf_counter() - (siblings[-1].t0 + siblings[-1].dt) < 0.05:
            first = siblings.pop()
            s.t0 = first.t0
            s.children.append(first)
        self.open[doc.Name] = s
        _stack.append(s)
        count("document recomputes", doc.Name)

    def slotBeforeRecomputeDocument(self, doc):      # (if FreeCAD sends it)
        if _on[0] and doc.Name not in self.open:
            self._begin(doc)

    def slotRecomputedObject(self, obj):
        if not _on[0]:
            return
        count("objects recomputed", "{} [{}]".format(obj.Label.rstrip(u"\u200b"), obj.Name))
        if obj.Document.Name not in self.open:
            self._begin(obj.Document)

    def slotRecomputedDocument(self, doc):
        s = self.open.pop(doc.Name, None)
        if s is None:
            return
        s.dt = time.perf_counter() - s.t0
        if s in _stack:
            # Spans opened inside it and left open (they shouldn't be) close with it.
            while _stack and _stack[-1] is not s:
                _stack.pop()
            _stack.pop()
        _add_total(s)
        if _stack:
            _stack[-1].children.append(s)
        else:
            _done.append(s)
            _until_idle(s)


_watcher = [None]


def _watch_documents(on):
    if on and _watcher[0] is None:
        _watcher[0] = _DocWatch()
        App.addDocumentObserver(_watcher[0])
    elif not on and _watcher[0] is not None:
        try:
            App.removeDocumentObserver(_watcher[0])
        except Exception:
            pass
        _watcher[0] = None


# ------------------------------------------------------------------ report

def _ms(t):
    return "{:8.1f} ms".format(t * 1000.0)


def _tree_text(s, depth=4, indent=0, min_share=0.02):
    line = u"{}{} {}{}{}".format(
        "  " * indent, _ms(s.dt), s.name, " " + s.detail if s.detail else "",
        "  (+{} until idle)".format(_ms(s.idle).strip()) if s.idle else "")
    out = [line]
    if depth > 0:
        # Children by name, biggest first, small ones folded.
        groups = collections.OrderedDict()
        for c in s.children:
            groups.setdefault((c.name, c.detail), []).append(c)
        items = sorted(groups.items(), key=lambda kv: -sum(c.dt for c in kv[1]))
        for (name, detail), cs in items:
            total = sum(c.dt for c in cs)
            if s.dt and total < s.dt * min_share:
                continue
            if len(cs) == 1:
                out.append(_tree_text(cs[0], depth - 1, indent + 1, min_share))
            else:
                out.append(u"{}{} {}{} ×{}".format("  " * (indent + 1), _ms(total), name,
                                                   " " + detail if detail else "", len(cs)))
    return "\n".join(out)


def report():
    """What was recorded, as text: the slowest actions with what was inside them,
    totals per kind of work, and recompute counts."""
    lines = ["Solid Design performance trace",
             "recorded for {:.1f} s".format(time.perf_counter() - _started[0]), ""]
    tops = sorted(_done, key=lambda s: -(s.dt + (s.idle or 0.0)))[:15]
    lines.append("Slowest actions (with what took the time inside):")
    for s in tops:
        lines.append(_tree_text(s, depth=4, indent=1))
    lines.append("")
    lines.append("Totals by kind of work:")
    lines.append("  {:>8} {:>12} {:>12} {:>12}  {}".format("calls", "total", "own", "max",
                                                          "span"))
    for name, (n, total, own, mx) in sorted(_totals.items(), key=lambda kv: -kv[1][1]):
        lines.append("  {:>8} {} {} {}  {}".format(n, _ms(total), _ms(own), _ms(mx), name))
    lines.append("")
    lines.append("Counts:")
    by_kind = collections.OrderedDict()
    for (kind, name), n in sorted(_counts.items()):
        by_kind.setdefault(kind, []).append((name, n))
    for kind, items in by_kind.items():
        total = sum(n for _nm, n in items)
        lines.append("  {} {}".format(total, kind))
        for name, n in sorted(items, key=lambda x: -x[1])[:25]:
            lines.append("      {:>5}  {}".format(n, name))
    if _profiles:
        lines.append("")
        lines.append("Python profiles of the slowest actions:")
        for s, text in sorted(_profiles, key=lambda p: -p[0].dt)[:5]:
            lines.append("---- {} {} ({})".format(s.name, s.detail, _ms(s.dt).strip()))
            lines.append(text)
    return "\n".join(lines) + "\n"


def stats():
    """{span name: (calls, total seconds)} and the counts, for tests."""
    return ({k: (v[0], v[1]) for k, v in _totals.items()}, dict(_counts))


def _from_environment():
    v = os.environ.get("SD_PROFILE", "").strip().lower()
    if v and v not in ("0", "no", "off", "false"):
        start(cprofile=(v == "cprofile"))


_from_environment()
