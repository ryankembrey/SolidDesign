# docs/

The source of the Solid Design documentation site, published to GitHub Pages
(https://ryankembrey.github.io/SolidDesign) by `.github/workflows/docs.yaml` on every push to
`main`. The site is built with [Zensical](https://zensical.org) from plain Markdown, with the same
tooling as the DFM Workbench's docs.

```bash
pixi run docs        # regenerate everything from the code, then build the site
pixi run serve       # the same, then preview at http://localhost:8000
pixi run docs-check  # exit 1 if anything generated is out of date
```

The first `pixi install` writes `pixi.lock` at the repository root: commit it, as CI installs
exactly what it pins.

## What's here

| Path | What it is | Written by |
| :-- | :-- | :-- |
| `zensical.toml` | Site configuration and navigation | Hand, except the `BEGIN GENERATED` block |
| `content/` | The site's pages and files | Mixed, see below |
| `content/reference/` | A page per tool, the tool index, toolbars, shortcuts, command line words, drag handles | `build.py` |
| `content/assets/shots/` | Screenshots of the workbench | `build.py`, in FreeCAD |
| `content/assets/icons/`, `content/assets/logo.svg` | The tools' icons, copied from the workbench | `build.py` |
| `content/changelog.md` | Changes per version, from git tags (not committed) | `build.py` |
| everything else in `content/` | Getting started, guides, concepts, the landing page | AI agents, by hand |
| `_authored/tools/<slug>.md` | What each tool is for and how to use it, placed on its page | AI agents, by hand |
| `_data/catalog.json` | The workbench read from its code: commands, toolbars, menus, feature properties | `build.py`, in freecadcmd |
| `_data/panels.json` | Every tool's panel: groups, controls, tooltips, drag handles | `build.py`, with the screenshots |
| `_data/shots.json` | The screenshots' fingerprint | `build.py` |
| `_pipeline/` | The generator (`build.py` runs it) | |
| `_notes/` | Notes for the owner and AI agents; never published | |
| `build/` | The built site (ignored by git) | `zensical` |

`AGENTS.md` at the repository root says what to update when the workbench changes.

## How the generator works

1. **Reading the workbench** (`_pipeline/catalog_runner.py`, under a second). It runs in FreeCAD's
   command line, `freecadcmd`, with a stand-in for `FreeCADGui` that records what the workbench
   registers: every command's name, tooltip, icon and shortcut, the toolbars and menus, and each
   feature class's properties (declared to a recorder, as the command line's completion does).
   The result is `_data/catalog.json`. Without FreeCAD, the committed file is used.
2. **Screenshots and panels** (`_pipeline/shots/`, a few minutes, only when something changed).
   FreeCAD runs on a virtual display. Each tool is opened the way a user opens it, on a sample
   part, and its window is grabbed; its panel is walked and recorded into `_data/panels.json`.
3. **Pages** (`_pipeline/pages_tools.py`, `pages_extra.py`). Each tool's page puts together its
   command, its hand-written text, its screenshot, where to find it, a table of its panel's
   controls (with their own tooltips), its drag handles, its command line options and its
   properties.

It writes a file only when its content changed, so a rebuild with nothing new leaves git clean,
and it deletes generated files it no longer writes.

The build fails when:

- a tool has no `_authored/tools/<slug>.md`, or one exists for no tool;
- a tool has no screenshot recipe (`RECIPES` in `_pipeline/shots/tools.py`) and isn't in `NO_SHOT`;
- a page uses a screenshot no shot makes, or a shot isn't used by any page;
- an authored page uses a `{{ value }}` the generator doesn't have.

## Screenshots

Every screenshot is made by code, in a real FreeCAD from the pixi environment on a virtual display.
You need Xvfb from your system (Debian/Ubuntu: `sudo apt install xvfb xauth`; Fedora:
`sudo dnf install xorg-x11-server-Xvfb xauth`). It works from a Wayland session too: FreeCAD always
runs on the virtual X display, never on your desktop.

- FreeCAD runs with a throwaway user folder, so your own settings and layout never show. The tree
  and the task panel are docked together on the left, as tabs.
- It uses a private font configuration with only the environment's fonts, so text renders the same
  on every machine.
- `_data/shots.json` holds a fingerprint of everything a shot could show (the workbench's code and
  icons, the shot code, `pixi.lock`). Only files git would commit count. When it matches, no
  FreeCAD runs.
- A retaken image replaces the old one only if it visibly differs.

```bash
python docs/build.py --shots                        # retake everything
python docs/build.py --no-shots                     # leave them alone
python docs/build.py --only=tool-fillet,interface   # retake some, while working on them
```

CI retakes them for the published site either way.

## Publishing

In the GitHub repository: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
The site then appears at https://ryankembrey.github.io/SolidDesign after the next push to `main`.
