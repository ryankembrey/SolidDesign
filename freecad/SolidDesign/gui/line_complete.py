# SPDX-License-Identifier: LGPL-2.1-or-later
"""Completion for the command line: what can come next at the cursor, for every
kind of word the line takes (tools, commands, feature and body names, options,
choices, variables, selection words and filters, registers, marks, aliases...).

``completions(text)`` gives [(what replaces the last word, what the list shows)].
``ghost(text, cands)`` gives the grey rest of the word Tab would add, when there
is only one way to go.
"""

import FreeCAD as App

from . import line_store

TREE_ARGS = {"edit", "suppress", "sup", "unsuppress", "unsup", "rollto"}
BODY_ARGS = {"hide", "show", "isolate"}
LIST_ARGS = {"suppress", "sup", "unsuppress", "unsup", "hide", "show", "isolate"}
LIMIT = 14


def norm(s):
    return "".join(c for c in s.lower() if c.isalnum())


def _fuzzy(word, text):
    from . import command_search
    return command_search.fuzzy(word, text)


def _match(word, cands):
    """The candidates that fit ``word``: those it starts first, then loose ones.
    ``cands``: [(key, put, shown)]."""
    w = word.lower()
    # The shortest first: what's typed is most of it ("fil": fillet before fillpattern).
    starts = [c for c in cands if c[0].lower().startswith(w)]
    if w:
        starts.sort(key=lambda c: (c[0].lower() != w, len(c[0])))
    rest = [c for c in cands if c not in starts and w and _fuzzy(word, c[0]) is not None]
    return [(put, shown) for _k, put, shown in starts + rest]


def _part():
    from .line_ex import _part as part
    try:
        return part()
    except Exception:
        return None


def _what(obj):
    from ..app import util
    if obj.TypeId.startswith("Sketcher::SketchObject"):
        return "sketch"
    if util.role(obj) == "refgeom":
        return "reference geometry"
    return "feature"


def _names(objs):
    from .line_ex import clean
    return [clean(o.Label) for o in objs]


# ------------------------------------------------------------------ first word

def first_words():
    """[(key, put, shown)] for the start of a line."""
    from . import command_line as cl
    from . import line_ex
    out = []
    seen = set()
    for name, (usage, summary) in sorted(line_ex.COMMANDS.items()):
        if name in seen:
            continue
        seen.add(name)
        out.append((name, name + " ", u"{}  —  {}".format(usage, summary)))
    for name, line in sorted(line_store.aliases().items()):
        out.append((name, name + " ", u"{}  —  alias: {}".format(name, line)))
    for n, kw, label, _tip in cl.tools():
        out.append((kw, kw + " ", u"{}  —  {}".format(kw, label)))
    part = _part()
    if part is not None:
        out.append(("last", "last ", u"last  —  the last feature: change its values"))
        for name in _names(line_ex.features(part)):
            out.append((name, name + " ", u"{}  —  change this feature's values".format(name)))
    return out


# ------------------------------------------------------------------ selections

def _named(cmd):
    """[(key, put, shown)] for picking by name: the origin's planes by a word, then
    everything in the tree by its name (planes first for a tool that cuts or
    mirrors with one)."""
    from . import hints
    from .line_select import named_objects
    from ..app import util
    doc = App.ActiveDocument
    words = [(w, w + ",", u"{}  —  {}".format(w, n)) for w, n in
             (("front", "Front Plane"), ("top", "Top Plane"), ("right", "Right Plane"))]
    planes, rest = [], []
    for t, o in named_objects(doc):
        if o.TypeId == "Part::DatumPlane" and t.lower() in ("frontplane", "topplane",
                                                           "rightplane"):
            continue                    # front, top, right say it shorter
        is_plane = o.TypeId == "Part::DatumPlane" or (
            util.role(o) == "refgeom" and getattr(o.Proxy, "KIND", "") == "plane")
        what = "plane" if is_plane else "body" if util.is_body_view(o) else _what(o)
        (planes if is_plane else rest).append((t, t + ",", u"{}  —  {}".format(t, what)))
    if cmd in hints.REF_PLANE_TOOLS:
        return words + planes, rest
    return [], words + planes + rest


def _sel_completions(key, value, cmd=None):
    """For a sel= word being typed: (head kept, [(key, put, shown)])."""
    from . import pick_tools
    from .hints import ALPHABET
    from .line_select import FILTERS, SOURCES
    head, _comma, part = value.rpartition(",")
    head = key + "=" + (head + "," if _comma else "")
    if ":" in part:
        src, _c, filt = part.rpartition(":")
        if src.split(":")[-1].lower() in ("par", "perp"):
            # par: and perp: take an axis
            axes = ["x", "y", "z", "top", "front", "right", "+x", "-x", "+y", "-y", "+z", "-z"]
            return head + src + ":", [(a, a, u"{}:{}  —  axis".format(src.split(":")[-1], a))
                                      for a in axes if a.startswith(filt.lower())]
        return head + src + ":", [(f, f, u":{}  —  {}".format(f, what)) for f, what in FILTERS]
    if part.startswith("@"):
        regs = line_store.registers(App.ActiveDocument)
        return head, [("@" + r, "@" + r + ",", u"@{}  —  register ({} picks)".format(r, len(v)))
                      for r, v in sorted(regs.items())]
    if part and all(c in ALPHABET for c in part.lower()):
        # A label being typed (the labels show in the view), unless it starts a name.
        try:
            first, last = _named(cmd)
        except Exception:
            first, last = [], []
        return head, [c for c in first + last if c[0].lower().startswith(part.lower())]
    words = [(w, w + ",", u"{}  —  adds {}".format(w, tip))
             for w, tip in pick_tools.WORDS.items()]
    srcs = [(s, s + ",", u"{}  —  {}".format(s, what)) for s, what in SOURCES
            if s not in ("front",)]
    regs = [("@" + r, "@" + r + ",", u"@{}  —  register".format(r))
            for r in sorted(line_store.registers(App.ActiveDocument))]
    try:
        first, last = _named(cmd)
    except Exception:
        first, last = [], []
    return head, first + srcs + words + regs + last


# ------------------------------------------------------------------ arguments of commands

def _arg_completions(cmd, words, word):
    """For a word after a command: [(key, put, shown)] (put replaces the last
    comma-separated name, for commands taking several)."""
    from . import command_line as cl
    from . import line_ex
    from . import line_help
    part = _part()
    if cmd in ("help", "h"):
        return [(t, t, u"{}  —  {}".format(t, title)) for t, title, _r in line_help.HELP]
    if cmd in TREE_ARGS:
        objs = line_ex.tree_objects(part) if cmd == "edit" else line_ex.features(part)
        out = [(n, n, u"{}  —  {}".format(n, _what(o))) for n, o in
               zip(_names(objs), objs)] if part is not None else []
        if cmd == "rollto":
            out.append(("end", "end", u"end  —  build every feature"))
        return out
    if cmd in BODY_ARGS:
        names = _names(line_ex.bodies(part)) if part is not None else []
        return [(n, n, u"{}  —  body".format(n)) for n in names]
    if cmd == "set":
        return _set_completions(word)
    if cmd == "unset":
        out = []
        for c, pv in sorted(line_store.defaults().items()):
            kw = norm(line_ex._label(c))
            for p in sorted(pv):
                out.append((kw + "." + p, kw + "." + p, u"{}.{}  —  default {}".format(
                    kw, p, pv[p])))
        return out
    if cmd in ("unalias",):
        return [(a, a, u"{}  —  {}".format(a, v))
                for a, v in sorted(line_store.aliases().items())]
    if cmd in ("unbind",):
        return [(k, k, u"{}  —  {}".format(k, v))
                for k, v in sorted(line_store.bindings().items())]
    if cmd in ("delmark", "mark"):
        return [(m, m, u"{}  —  saved view".format(m))
                for m in sorted(line_store.marks(App.ActiveDocument))]
    if cmd in ("delreg",):
        return [(r, r, u"{}  —  register".format(r))
                for r in sorted(line_store.registers(App.ActiveDocument))]
    if cmd == "yank":
        out = [("sel=", "sel=", u"sel=  —  pick what to measure")]
        if part is not None:
            if "." in word:
                name, _d, _p = word.partition(".")
                obj = line_ex.by_name(name, line_ex.tree_objects(part))
                if obj is not None:
                    for p in sorted(cl.settable(obj)):
                        n = name + "." + p
                        out.append((n, n + " ", u"{}  —  {}".format(n, "value")))
                return out
            for n in _names(line_ex.tree_objects(part)):
                out.append((n, n + ".", u"{}.  —  one of its values".format(n)))
        return out
    return []


def _set_completions(word):
    from . import command_line as cl
    from . import line_ex
    if "." in word.split("=", 1)[0] and "=" not in word:
        tool, _d, opt = word.partition(".")
        cmd = cl.find_tool(tool)
        if cmd is None:
            return []
        return [(tool + "." + p, tool + "." + p + "=", u"{}.{}=  —  {}".format(tool, p, k))
                for p, (k, _c) in sorted(cl.catalog(cmd).items())]
    if "=" in word:
        return []
    out = []
    for n, kw, label, _t in cl.tools():
        if cl._proxy_classes().get(n) is not None:
            out.append((kw, kw + ".", u"{}.  —  a default for {}".format(kw, label)))
    part = _part()
    if part is not None:
        for n in _names(line_ex.features(part)):
            out.append((n, n, u"{}  —  set values on it".format(n)))
    return out


# ------------------------------------------------------------------ options

def _option_completions(opts, main, word, vars_):
    """Options of a tool or feature: name=, choice words, yes/no flags, variables."""
    from . import command_search
    out = []
    if "=" in word:
        name, part = word.split("=", 1)
        from .command_line import _resolve
        prop = _resolve(name, opts) if opts else name
        kind, choices = opts.get(prop, (None, None))
        cands = [(c, "") for c in (choices or [])] if kind == "enum" else \
            [("yes", ""), ("no", "")] if kind == "bool" else []
        cands += [(v, "variable") for v in sorted(vars_)]
        for c, what in cands:
            if not part or norm(c).startswith(norm(part)) or command_search.fuzzy(part, c):
                put = "{}={} ".format(name, norm(c) if what == "" and kind == "enum" else c)
                out.append((put, u"{}={}".format(prop, c) + (u"  —  " + what if what else "")))
        return out[:LIMIT]
    cands = []
    for prop, (kind, choices) in sorted(opts.items(), key=lambda kv: (kv[0] not in main, kv[0])):
        cands.append((prop, prop + "=", u"{}=  —  {}{}".format(
            prop, kind, " (in order: %d)" % (main.index(prop) + 1) if prop in main else "")))
        if kind == "enum":
            for c in choices or ():
                cands.append((norm(c), norm(c) + " ", u"{}  —  {}".format(c, prop)))
        if kind == "bool":
            cands.append((norm(prop), norm(prop) + " ", u"{}  —  turns {} on".format(
                norm(prop), prop)))
    for v in sorted(vars_):
        cands.append((v, v + " ", u"{}  —  variable ({})".format(v, vars_[v])))
    if not word:
        return [(put, shown) for _k, put, shown in cands
                if put.endswith("=")][:LIMIT]
    return _match(word, cands)[:LIMIT]


# ------------------------------------------------------------------ the whole line

def completions(text):
    """[(text to put in place of the last word, what to show)] for the line so far."""
    from . import command_line as cl
    from . import line_ex
    from .hints import SEL_KEYS
    raw = text.lstrip(":")
    parts = raw.split(" ")
    word = parts[-1]
    if len(parts) == 1:
        if word.startswith("'"):
            m = line_store.marks(App.ActiveDocument)
            return [("'" + k, u"'{}  —  saved view".format(k)) for k in sorted(m)
                    if k.startswith(word[1:])]
        if not word:
            return []
        # A command's short form (reg, h) is the same line in the list: once.
        out, seen = [], set()
        for put, shown in _match(word, first_words()):
            if shown not in seen:
                seen.add(shown)
                out.append((put, shown))
        return out[:LIMIT]
    # The sel= being typed
    if "=" in word and word.split("=", 1)[0].lower() in SEL_KEYS:
        key, value = word.split("=", 1)
        cmd = cl.find_tool(line_ex.expand_alias(raw).split(" ")[0]) \
            if "=" not in parts[0] else None
        head, cands = _sel_completions(key, value, cmd)
        part = value.rpartition(",")[2]
        bit = part.rpartition(":")[2] if ":" in part else part
        return [(head + put, shown) for put, shown in _match(bit, cands)][:LIMIT]
    if word.startswith(">"):
        regs = sorted(line_store.registers(App.ActiveDocument))
        return [(">" + r + " ", u">{}  —  keep the picks in register {}".format(r, r))
                for r in regs if r.startswith(word[1:])]
    first = parts[0].lower()
    if first in line_ex.COMMANDS:
        name_part = word.rpartition(",")[2] if first in LIST_ARGS else word
        head = word[:len(word) - len(name_part)]
        if name_part.startswith("/"):
            return []
        cands = _arg_completions(first, parts[1:-1], word)
        if first in ("set",) and "." in word:
            head, name_part = "", word
        return [(head + put, shown) for put, shown in _match(name_part, cands)][:LIMIT]
    # A feature by name: its own options
    fl = line_ex.feature_line(raw)
    if fl is not None:
        obj = fl[0]
        opts = cl.settable(obj)
        main = cl._main(cl.command_for(obj) or "", obj)
        return _option_completions(opts, main, word, cl.variables(App.ActiveDocument))
    # A tool (or an alias for one)
    expanded = line_ex.expand_alias(raw)
    cmd = cl.find_tool(expanded.split(" ")[0])
    if cmd is None:
        return []
    opts = cl.catalog(cmd)
    main = [m for m in cl.MAIN.get(cmd, []) if m in opts]
    out = []
    if not word or "sel".startswith(norm(word)):
        out.append(("sel=", u"sel=  —  pick: labels in the view, new, edges:circular..."))
    out += _option_completions(opts, main, word, cl.variables(App.ActiveDocument))
    return out[:LIMIT]


def _common(strings):
    if not strings:
        return ""
    lo, hi = min(strings, key=str.lower), max(strings, key=str.lower)
    n = 0
    while n < min(len(lo), len(hi)) and lo[n].lower() == hi[n].lower():
        n += 1
    return lo[:n]


def tab_target(text, cands):
    """What Tab puts in place of the word being typed, or None to go through the
    list (from the top): the one candidate there is; else the only one the word
    starts; else the one that is all the others it starts begin with."""
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0][0]
    word = text.split(" ")[-1]
    starts = [put for put, _s in cands if put.lower().startswith(word.lower())]
    if len(starts) == 1 and word:
        return starts[0]
    # One of them is all that the rest share ("tan": tan, tangent): that one.
    common = _common([p.rstrip(" ") for p in starts])
    if len(starts) > 1 and len(common) > len(word):
        whole = [p for p in starts if p.rstrip(" ,").lower() == common.rstrip(",").lower()]
        if whole:
            return whole[0]
    return None


def ghost(text, cands):
    """The grey rest of the word Tab would add (see tab_target); a loose match
    shows as "→ word"."""
    put = tab_target(text, cands)
    if put is None:
        return ""
    put = put.rstrip(" ")
    word = text.split(" ")[-1]
    if put.lower().startswith(word.lower()):
        return put[len(word):]
    return u"  → " + put
