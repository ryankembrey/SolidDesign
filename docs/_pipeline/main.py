# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Ryan Kembrey <ryan.FreeCAD@gmail.com>
# SPDX-FileNotice: Part of the Solid Design addon.

"""docs/build.py: regenerate everything in docs/ made from the code.

    --check        write nothing; exit 1 if a generated file is out of date
    --no-shots     leave the screenshots as they are (fast)
    --shots        retake every screenshot, even if nothing changed
    --only=a,b     retake only these screenshots (for working on a shot)
"""

from __future__ import annotations

import re
import time

from . import env

#: Paths under docs/ that only the generator writes. Anything in them it
#: didn't write (or keep) this run is deleted.
GENERATED = (
    "content/reference",
    "content/assets/shots",
    "content/assets/icons",
    "content/assets/logo.svg",
)


def _shot_references(registry) -> list[str]:
    """Screenshots used in the pages that no shot makes, and shots no page uses."""
    used = set()
    problems = []
    for page in sorted(env.CONTENT.rglob("*.md")):
        text = page.read_text(encoding="utf-8")
        for shot_id in re.findall(r"assets/shots/([a-z0-9-]+)\.png", text):
            used.add(shot_id)
            if shot_id not in registry:
                problems.append(f"{page.relative_to(env.DOCS)} uses screenshot {shot_id!r}, "
                                "which no shot in docs/_pipeline/shots makes")
    for shot_id in sorted(set(registry) - used):
        problems.append(f"screenshot {shot_id!r} isn't used by any page")
    return problems


def _only(argv) -> list[str] | None:
    for a in argv:
        if a.startswith("--only="):
            return [x for x in a.split("=", 1)[1].split(",") if x]
    return None


def main(argv: list[str]) -> int:
    check = "--check" in argv
    started = time.monotonic()
    from . import catalog, pages_extra, pages_tools
    from .output import Output

    out = Output(env.DOCS, check=check)
    notes = catalog.refresh(out)
    cat = catalog.load()

    from .shots import REGISTRY, engine, scenes, tools  # noqa: F401  (registers the shots)

    problems = pages_tools.problems(cat, tools)
    if problems:
        print("The tool pages can't be made:")
        for p in problems:
            print("  - " + p)
        return 2

    if "--no-shots" in argv:
        engine.run(out, check=True)  # keeps the images as they are
    elif _only(argv):
        notes += engine.run_only(out, _only(argv))
    else:
        notes += engine.run(out, check=check, force="--shots" in argv)

    out.write("content/assets/logo.svg", env.LOGO.read_bytes())
    pages_tools.write(out, cat)
    pages_extra.write(out, cat)
    pages_extra.write_changelog()  # not committed (see its docstring), so not checked

    problems = _shot_references(REGISTRY)
    if problems:
        print("Screenshots and pages don't match:")
        for p in problems:
            print("  - " + p)
        return 2
    out.prune(*GENERATED)

    seconds = time.monotonic() - started
    for note in notes:
        print(note)
    if check:
        if out.changed:
            print(f"docs/ is out of date ({len(out.changed)} files). Run `pixi run docs` and commit:")
            for line in out.changed:
                print("  " + line)
            return 1
        print(f"docs/ is up to date ({seconds:.1f}s).")
        return 0
    for line in out.changed:
        print("  " + line)
    print(f"docs/: {len(out.changed)} files changed ({seconds:.1f}s).")
    return 0
