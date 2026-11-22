# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Ryan Kembrey <ryan.FreeCAD@gmail.com>
# SPDX-FileNotice: Part of the Solid Design addon.

"""Other generated pages: the command line's words, keyboard shortcuts, drag
handles, toolbars, and the changelog."""

from __future__ import annotations

import re
import subprocess

from . import env, md
from .catalog import Catalog
from .pages_tools import icon_rel, load_panels


def _link(t) -> str:
    return f"[{t.label}](tools/{t.slug}.md)"


def command_line_page(cat: Catalog) -> str:
    cl = cat.data["command_line"]
    out = md.header("docs/_data/catalog.json (freecad/SolidDesign/gui/command_line.py)")
    out += "# Command line words\n\n"
    out += ("Every tool the command line runs, the word for it, and the values it takes in order "
            "without naming them. You can type any part of a tool's name: the line matches "
            "loosely, as command search does. [The command line](../guides/keyboard.md) explains "
            "the rest.\n\n")
    rows = []
    for t in cat.documented:
        kw = cl["keywords"].get(t.name)
        if not kw or not t.feature_type:
            continue
        main = cl["main"].get(t.name, [])
        rows.append([_link(t), f"`{kw}`", ", ".join(f"**{m}**" for m in main) or "–"])
    out += md.table(["Tool", "Word", "Values in order"], rows)
    sheet = cl.get("cheat_sheet") or []
    if sheet:
        out += ("## Cheat sheet\n\n"
                "The same as <kbd>:</kbd> `h` <kbd>Enter</kbd> shows over the 3D view "
                "(<kbd>Esc</kbd> closes it; `:h sel` goes to a part).\n\n")
        for part in sheet:
            out += f"### {part['title']}\n\n"
            out += md.table(["Type", "What it does"],
                            [[f"`{a}`", b] for a, b in part["rows"]])
    cmds = cl.get("commands") or {}
    if cmds:
        out += "## The line's own commands\n\n"
        out += ("Words that start a line and aren't tools. A short form does the same as "
                "the word it is next to.\n\n")
        seen, rows = {}, []
        for name, (usage, summary) in cmds.items():
            seen.setdefault((usage, summary), []).append(name)
        for (usage, summary), names in sorted(seen.items(), key=lambda kv: max(kv[1], key=len)):
            names.sort(key=len, reverse=True)
            rows.append([" · ".join(f"`{n}`" for n in names), f"`{usage}`", summary])
        out += md.table(["Command", "Example", "What it does"], rows)
    return out.rstrip("\n") + "\n"


def keyboard_page(cat: Catalog) -> str:
    out = md.header("docs/_data/catalog.json")
    out += "# Keyboard shortcuts\n\n"
    out += ("Shortcuts the workbench sets. They work in the 3D view with no tool open. You can "
            "change any of them in **Tools → Customize → Keyboard**.\n\n")
    rows = []
    for t in cat.tools.values():
        if t.shortcut:
            keys = " ".join(f"<kbd>{k.strip()}</kbd>" for k in t.shortcut.split(","))
            link = _link(t) if t in cat.documented else t.label
            rows.append([keys, link, t.tooltip])
    out += md.table(["Keys", "Tool", "What it does"], rows)
    out += ("The command line (<kbd>:</kbd>) and repeat (<kbd>.</kbd>) are keys of their own: "
            "see [the command line](../guides/keyboard.md).\n")
    return out


def handles_page(cat: Catalog) -> str:
    panels = load_panels()
    out = md.header("docs/_data/panels.json (recorded with the screenshots)")
    out += "# Drag handles\n\n"
    out += ("The tools whose features have drag handles in the 3D view, and what each handle "
            "sets. [Drag handles](../guides/drag-handles.md) explains how to use them.\n\n")
    rows = []
    for t in cat.documented:
        rec = panels.get(t.name)
        if rec and rec.get("handles"):
            rows.append([_link(t), ", ".join(f"**{h}**" for h in rec["handles"])])
    out += md.table(["Tool", "Handles set"], rows) if rows else "None recorded yet.\n"
    return out


def toolbars_page(cat: Catalog) -> str:
    wb = cat.data["workbench"]
    out = md.header("docs/_data/catalog.json (freecad/SolidDesign/init_gui.py)")
    out += "# Toolbars\n\n"
    out += ("The workbench's toolbars, left to right, and what is on each. A tool with ▾ is a "
            "drop-down: click its arrow for the tools in it.\n\n")
    for tb in wb["toolbars"]:
        out += f"## {tb['name'].replace('Solid Design ', '')}\n\n"
        rows = []
        for n in tb["commands"]:
            t = cat.tools.get(n)
            if t is None:
                continue
            ic = icon_rel(t)
            icon = f"![]({'../' + ic}){{ .tool-icon-small }}" if ic else ""
            if t.group:
                kids = [cat.tools[c] for c in t.group if c in cat.tools]
                rows.append([icon, f"**{t.label}** ▾", ", ".join(_link(k) for k in kids)])
            else:
                rows.append([icon, _link(t) if t in cat.documented else t.label, t.tooltip])
        out += md.table(["", "Tool", "What it does"], rows)
    return out


def index_page(cat: Catalog) -> str:
    out = md.header("docs/_pipeline/pages_extra.py")
    out += "# Reference\n\n"
    out += ("Everything in the workbench, made from its code, so it is always current.\n\n")
    out += ("- [Tools](tools/index.md): a page for every tool, with every control in its panel.\n"
            "- [Toolbars](toolbars.md): what's on each toolbar.\n"
            "- [Keyboard shortcuts](keyboard.md).\n"
            "- [Command line](command-line.md): the word for each tool, its values, and the "
            "cheat sheet.\n"
            "- [Drag handles](drag-handles.md): which tools have them, and what they set.\n\n")
    out += f"This describes Solid Design {cat.data.get('version', '')}.\n"
    return out


def write(out, cat: Catalog) -> None:
    out.write("content/reference/index.md", index_page(cat))
    out.write("content/reference/command-line.md", command_line_page(cat))
    out.write("content/reference/keyboard.md", keyboard_page(cat))
    out.write("content/reference/drag-handles.md", handles_page(cat))
    out.write("content/reference/toolbars.md", toolbars_page(cat))


# -- changelog ---------------------------------------------------------------------

_SKIP = re.compile(r"^(Bump version|Release version|Merge (pull request|branch))", re.I)


def _git(*args) -> str:
    return subprocess.run(["git", *args], cwd=env.REPO, capture_output=True, text=True,
                          check=True).stdout


def changelog_page() -> str:
    out = ("<!-- Generated by docs/build.py from the git history and its version tags. "
           "Not committed: it is rebuilt on every build. -->\n\n")
    out += "# Changelog\n\n"
    out += "What changed in each version of the workbench, newest first.\n\n"
    try:
        tags = [t for t in _git("tag", "--sort=-v:refname").split() if re.match(r"^v\d", t)]
    except (OSError, subprocess.CalledProcessError):
        tags = []
    if not tags:
        return out + ("No version has been tagged yet. See the "
                      f"[history on GitHub]({env.REPO_URL}/commits/main).\n")
    ranges = [("HEAD", tags[0], "Since " + tags[0])]
    ranges += [(tag, tags[i + 1] if i + 1 < len(tags) else None, tag) for i, tag in enumerate(tags)]
    for end, start, title in ranges:
        span = f"{start}..{end}" if start else end
        subjects = [s for s in _git("log", "--format=%s", "--no-merges", span).splitlines()
                    if s.strip() and not _SKIP.match(s)]
        if end == "HEAD":
            if not subjects:
                continue
            out += f"## {title}\n\nNot released yet.\n\n"
        else:
            date = _git("log", "-1", "--format=%cs", end).strip()
            out += f"## {title}\n\n*{date}*\n\n"
        out += "".join(f"- {md.cell(s)}\n" for s in subjects) or "- Version bump only.\n"
        out += "\n"
    return out


def write_changelog() -> None:
    """Write content/changelog.md directly (outside Output). It changes with every
    commit, so it is ignored by git and left out of the up-to-date check."""
    page = env.CONTENT / "changelog.md"
    text = changelog_page()
    if not page.exists() or page.read_text(encoding="utf-8") != text:
        page.write_text(text, encoding="utf-8")
