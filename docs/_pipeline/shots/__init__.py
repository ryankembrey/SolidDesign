# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the Solid Design addon.

"""Screenshots of the workbench, made by code.

A shot is a function that sets FreeCAD up the way a user would and returns the
image. All of them run inside a real FreeCAD on a virtual display (Xvfb), started
by engine.py; freecad_runner.py calls them one after another.

* tools.py: one shot per tool, ``tool-<tool slug>``: the tool's panel open on the
  sample part, with its preview. It also records the panel's groups and controls
  (with their tooltips) into ``_data/panels.json``, which the tool's page lists.
* scenes.py: everything else the guides show (the interface, the command line,
  What's Wrong...).

Each shot is written to docs/content/assets/shots/<id>.png. Pages use them as
``![...](../assets/shots/<id>.png)``. engine.py decides when to re-run them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

#: Where shots are written, relative to docs/content.
FOLDER = "assets/shots"


@dataclass(frozen=True)
class Shot:
    id: str
    fn: Callable
    about: str          # one line: what it shows (and the image's alt text)
    tool: str = ""      # the command a tool shot opens (its panel is recorded)


REGISTRY: dict[str, Shot] = {}


def shot(id: str, about: str, tool: str = ""):
    """Register the decorated function (``fn(ctx) -> QImage``) as the shot *id*."""

    def decorator(fn):
        if id in REGISTRY:
            raise ValueError(f"two shots are called {id!r}")
        REGISTRY[id] = Shot(id=id, fn=fn, about=about, tool=tool)
        return fn

    return decorator


def path(shot_id: str) -> str:
    return f"{FOLDER}/{shot_id}.png"


def tool_shot_id(slug: str) -> str:
    return f"tool-{slug}"
