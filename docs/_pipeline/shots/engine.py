# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Ryan Kembrey <ryan.FreeCAD@gmail.com>
# SPDX-FileNotice: Part of the Solid Design addon.

"""Taking the screenshots: when, and how.

Shots are re-taken only when something they could show has changed: the
workbench's code and icons, the shot code itself or the pinned environment
(pixi.lock). A fingerprint of all of that is kept in docs/_data/shots.json. When
it matches and every image is there, nothing runs. Only files git would commit
count, so a machine with extra untracked files gets the same fingerprint as CI.

They are taken in FreeCAD from the pixi environment, under Xvfb, with a
throwaway FreeCAD user folder (nobody's own settings, recent files or toolbar
layout) and a private font configuration (the environment's fonts only). So
the same code gives the same pictures on any machine.

A new image replaces the old one only if it visibly differs, so rendering
noise doesn't turn into commits. The same run records each tool's panel into
docs/_data/panels.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .. import env
from . import REGISTRY, path

MANIFEST = "_data/shots.json"   # relative to docs/
PANELS = "_data/panels.json"    # relative to docs/
#: A pixel counts as changed past this difference (0-255) in any channel...
PIXEL_TOLERANCE = 40
#: ...and an image as changed when more than this many pixels did. Small on
#: purpose: a changed word in a label is a few hundred pixels and must count.
CHANGED_PIXELS = 50
#: The virtual screen; the window is sized inside it by freecad_runner.py.
SCREEN = "1920x1200x24"

_FINGERPRINT_PATHS = ("freecad/SolidDesign", "docs/_pipeline/shots", "pixi.lock")
_FINGERPRINT_SUFFIXES = {".py", ".ui", ".svg", ".qrc", ".png", ".lock", ".json"}


def _visible(paths) -> list[Path]:
    """Files under *paths* that git would commit (tracked, or new and not
    ignored). Without git, every file."""
    try:
        r = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *paths],
                           cwd=env.REPO, capture_output=True, timeout=60, check=True)
        found = [env.REPO / p for p in r.stdout.decode("utf-8").split("\0") if p]
    except (OSError, subprocess.SubprocessError):
        found = [p for rel in paths for p in ([env.REPO / rel] if (env.REPO / rel).is_file()
                                              else (env.REPO / rel).rglob("*"))]
    return sorted({p for p in found if p.is_file()})


def fingerprint() -> str:
    h = hashlib.sha256()
    for p in _visible(_FINGERPRINT_PATHS):
        if p.suffix.lower() not in _FINGERPRINT_SUFFIXES or "__pycache__" in p.parts:
            continue
        h.update(p.relative_to(env.REPO).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def _load_manifest() -> dict:
    p = env.DOCS / MANIFEST
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def _images_differ(old: bytes, new: bytes) -> bool:
    import numpy as np
    from PySide6 import QtGui

    a, b = QtGui.QImage(), QtGui.QImage()
    a.loadFromData(old)
    b.loadFromData(new)
    if a.isNull() or b.isNull() or a.size() != b.size():
        return True
    fmt = QtGui.QImage.Format.Format_RGBA8888
    a, b = a.convertToFormat(fmt), b.convertToFormat(fmt)

    def array(img):
        return np.frombuffer(img.constBits(), np.uint8, img.sizeInBytes()).reshape(img.height(), img.bytesPerLine())

    diff = np.abs(array(a).astype(np.int16) - array(b).astype(np.int16))
    changed = int((diff > PIXEL_TOLERANCE).reshape(a.height(), -1, 4).any(axis=2).sum())
    return changed > CHANGED_PIXELS


def _fonts_conf(tmp: Path) -> Path | None:
    """A fontconfig file that sees only the environment's fonts."""
    prefix = os.environ.get("CONDA_PREFIX")
    if not prefix or not (Path(prefix) / "fonts").is_dir():
        return None
    conf = tmp / "fonts.conf"
    aliases = "".join(
        f"<alias><family>{name}</family><prefer><family>{font}</family></prefer></alias>"
        for name, font in (("sans-serif", "Ubuntu"), ("Sans Serif", "Ubuntu"), ("Sans", "Ubuntu"),
                           ("serif", "DejaVu Serif"), ("monospace", "Ubuntu Mono"))
    )
    conf.write_text(
        '<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>'
        f"<dir>{prefix}/fonts</dir><cachedir>{tmp}/fc-cache</cachedir>{aliases}</fontconfig>",
        encoding="utf-8",
    )
    return conf


def _missing_tools() -> list[str]:
    missing = []
    if not os.environ.get("CONDA_PREFIX") or not env.freecad(gui=True):
        missing.append("FreeCAD from the pixi environment (run through `pixi run docs`)")
    if not shutil.which("xvfb-run"):
        missing.append("xvfb-run (Debian/Ubuntu: `sudo apt install xvfb xauth`; "
                       "Fedora: `sudo dnf install xorg-x11-server-Xvfb xauth`)")
    return missing


def take(ids: list[str], timeout: int = 3600) -> tuple[dict[str, bytes], dict[str, dict], dict[str, str]]:
    """Run FreeCAD and take *ids*; returns ({id: png bytes}, {command: panel record}, {id: error})."""
    with tempfile.TemporaryDirectory(prefix="sd-shots-") as tmp:
        tmp = Path(tmp)
        out = tmp / "out"
        home = tmp / "freecad-home"
        out.mkdir()
        home.mkdir()
        e = env.sealed_env(
            SD_REPO=str(env.REPO),
            SD_SHOTS_OUT=str(out),
            SD_SHOTS_IDS=",".join(ids),
            FREECAD_USER_HOME=str(home),
            # Qt's hashes are seeded at random per process: fix the seed.
            QT_HASH_SEED="0",
            OMP_NUM_THREADS="1",
        )
        # FreeCAD draws on Xvfb's X display, never on your desktop: on a Wayland
        # session (Sway, GNOME...) Qt would otherwise pick Wayland and open the
        # window there, where the compositor sizes it and the pictures change.
        e["QT_QPA_PLATFORM"] = "xcb"
        e["XDG_SESSION_TYPE"] = "x11"
        for var in ("WAYLAND_DISPLAY", "WAYLAND_SOCKET", "QT_WAYLAND_DISABLE_WINDOWDECORATION",
                    "QT_SCALE_FACTOR", "QT_SCREEN_SCALE_FACTORS", "QT_AUTO_SCREEN_SCALE_FACTOR",
                    "QT_ENABLE_HIGHDPI_SCALING", "QT_FONT_DPI", "QT_STYLE_OVERRIDE", "QT_QPA_PLATFORMTHEME"):
            e.pop(var, None)
        conf = _fonts_conf(tmp)
        if conf:
            e["FONTCONFIG_FILE"] = str(conf)
        runner = Path(__file__).with_name("freecad_runner.py")
        cmd = ["xvfb-run", "-a", "-s", f"-screen 0 {SCREEN}", env.freecad(gui=True), str(runner)]
        proc = subprocess.run(cmd, env=e, capture_output=True, text=True, timeout=timeout)
        try:
            results = json.loads((out / "results.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            results = {}
        running = out / "running.txt"
        if running.exists():
            # FreeCAD crashed: blame the shot it was taking, keep the ones before it.
            crashed = running.read_text(encoding="utf-8").strip()
            stack = (out / "crash.txt").read_text(encoding="utf-8", errors="replace") \
                if (out / "crash.txt").exists() else ""
            tail = (proc.stdout + proc.stderr)[-3000:]
            results[crashed] = (f"FreeCAD crashed while taking this shot:\n{tail}\n"
                                f"Python stack at the crash:\n{stack[-4000:]}")
            for i in ids:
                results.setdefault(i, f"not taken: FreeCAD crashed earlier, in {crashed}")
        elif not results:
            tail = (proc.stdout + proc.stderr)[-3000:]
            return {}, {}, {i: "FreeCAD stopped before taking any shot:\n" + tail for i in ids}
        images, panels, errors = {}, {}, {}
        for i in ids:
            status = results.get(i, "not taken")
            if status == "ok":
                images[i] = (out / f"{i}.png").read_bytes()
                rec = out / "panels" / f"{i}.json"
                if rec.exists():
                    data = json.loads(rec.read_text(encoding="utf-8"))
                    panels[data["command"]] = data
            else:
                errors[i] = status
        if "_runner" in results:
            errors["_runner"] = results["_runner"]
        return images, panels, errors


def run(out, check: bool, force: bool = False) -> list[str]:
    """Bring the screenshots (and panels.json) up to date, or with *check* only
    say whether they are. Returns notes to print."""
    ids = sorted(REGISTRY)
    outputs = [path(i) for i in ids]  # under docs/content
    current = fingerprint()
    manifest = _load_manifest()
    present = all((env.CONTENT / rel).exists() for rel in outputs) and (env.DOCS / PANELS).exists()
    fresh = manifest.get("fingerprint") == current and manifest.get("shots") == ids and present

    def keep_all():
        for rel in outputs:
            if (env.CONTENT / rel).exists():
                out.keep("content/" + rel)
        out.keep(MANIFEST)
        out.keep(PANELS)

    if (fresh and not force) or check:
        keep_all()
        if check and not fresh:
            return ["Screenshots are older than the code. `pixi run docs` retakes them "
                    "(CI retakes them for the site either way)."]
        return []

    missing = _missing_tools()
    if missing:
        keep_all()
        return ["Screenshots not retaken: this needs " + " and ".join(missing) + "."]

    print(f"Taking {len(ids)} screenshots in FreeCAD (a few minutes)...", flush=True)
    images, panels, errors = take(ids)
    notes = []
    for i in ids:
        rel = "content/" + path(i)
        if i in images:
            old = env.CONTENT / path(i)
            if old.exists() and not _images_differ(old.read_bytes(), images[i]):
                out.keep(rel)
            else:
                out.write(rel, images[i])
        else:
            if (env.CONTENT / path(i)).exists():
                out.keep(rel)  # keep the last good one
            notes.append(f"Screenshot {i} failed:\n{errors.get(i, '')}")
    # Panels whose shot failed keep their last record.
    old_panels = {}
    if (env.DOCS / PANELS).exists():
        old_panels = json.loads((env.DOCS / PANELS).read_text(encoding="utf-8"))
    tool_of = {s.tool: s.id for s in REGISTRY.values() if s.tool}
    merged = {c: panels.get(c) or old_panels.get(c) for c in sorted(tool_of)
              if panels.get(c) or old_panels.get(c)}
    out.write(PANELS, json.dumps(merged, indent=1, ensure_ascii=False) + "\n")
    if "_runner" in errors:
        notes.append("The screenshot runner failed:\n" + errors["_runner"])
    if not errors:
        out.write(MANIFEST, json.dumps({"fingerprint": current, "shots": ids}, indent=1) + "\n")
    else:
        out.keep(MANIFEST)
    return notes


def run_only(out, ids: list[str]) -> list[str]:
    """Retake only *ids* (while working on a shot); everything else is kept, and
    the fingerprint isn't updated, so the next full build still checks them all."""
    unknown = [i for i in ids if i not in REGISTRY]
    if unknown:
        return ["No such shots: " + ", ".join(unknown)]
    missing = _missing_tools()
    for i in REGISTRY:
        if (env.CONTENT / path(i)).exists():
            out.keep("content/" + path(i))
    out.keep(MANIFEST)
    out.keep(PANELS)
    if missing:
        return ["Screenshots not retaken: this needs " + " and ".join(missing) + "."]
    images, panels, errors = take(ids)
    for i, data in images.items():
        out.write("content/" + path(i), data)
    if panels:
        old = {}
        if (env.DOCS / PANELS).exists():
            old = json.loads((env.DOCS / PANELS).read_text(encoding="utf-8"))
        old.update(panels)
        out.write(PANELS, json.dumps(dict(sorted(old.items())), indent=1, ensure_ascii=False) + "\n")
    return [f"Screenshot {i} failed:\n{e}" for i, e in errors.items()]
