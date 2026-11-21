# Working on Solid Design (for AI agents)

A FreeCAD 1.1+ Python workbench that models parts the SolidWorks way, multi-body first. `README.md`
has the layout and how to run the tests.

## The owner's rules

- **Never open pull requests** on this repository. Hand over the changed files; the owner applies
  them locally.
- **Keep it LGPL-2.1-or-later.**
- **Log departures from SolidWorks** in `docs/_notes/ux-departures.md` for the owner to review.
- **After a small UI change, run the targeted test**, not the whole suite. Say what you ran.
- **The documentation is part of every change.** A tool isn't done until the site describes it.
  The docs site (`docs/`, published to GitHub Pages) is written and maintained by AI agents.

## Documentation: what to do when you change something

Most of the site is generated from the code by `docs/build.py` (see `docs/README.md`). Run it
after any change:

```bash
pixi run docs        # regenerate docs/ and build the site (docs/build/site)
pixi run serve       # the same, then preview at http://localhost:8000
pixi run docs-check  # fails if anything generated is out of date
```

Commit everything it changes, images and `docs/_data/` included.

| You changed | Also do |
| :-- | :-- |
| A tool's tooltip, icon, shortcut, toolbar or menu place | Run `pixi run docs`. Nothing to write by hand. |
| A panel's layout, a control or its tooltip | Run `pixi run docs`: the screenshot and the panel table are made again. Look at the picture, and fix the tool's `docs/_authored/tools/<slug>.md` if its steps no longer match. |
| A feature's properties | Run `pixi run docs`. Nothing by hand. |
| A new tool | Write `docs/_authored/tools/<slug>.md` (see below) and add a recipe to `RECIPES` in `docs/_pipeline/shots/tools.py` that opens it on a sample part. The build fails until both exist. |
| A renamed tool | Rename its `docs/_authored/tools/<slug>.md` to the new slug (the build says which). |
| How something works that a guide or concept page describes | Fix that page in the same change. Search `docs/content` for the tool's name. |
| Anything a user sees outside a tool (the tree, menus, badges, keys) | Update the guide that covers it, with a screenshot (`docs/_pipeline/shots/scenes.py`). |

### A tool's hand-written page (`docs/_authored/tools/<slug>.md`)

Placed on the tool's generated page. Its first paragraphs (before any heading) say what the tool is
for, in a sentence or three; the screenshot goes after them. Then:

- `## How to use it`: numbered steps, the way a user does it (select, click the tool, pick, set,
  OK).
- `## Good to know` (optional): the options worth knowing about, links to related tools.

Don't describe each control: the generated "The panel" table does, from the controls' own
tooltips. Write `{{ name }}` for a number that comes from the code (`values()` in
`docs/_pipeline/pages_tools.py` lists them, and can be extended): never type it.

### Screenshots

Every picture of the workbench on the site is made by a shot in `docs/_pipeline/shots/`:

- `tools.py`: one per tool, from `RECIPES`. A recipe builds a part with `ctx` (`ctx.plate()`,
  `ctx.sketch()`, `ctx.extrude()`...), selects, runs the tool (`ctx.run("SD_...")`), picks into
  its boxes (`ctx.pick(ctx.box("Name"), obj, sub)`) and leaves the panel open. The shot grabs the
  window and records the panel. A recipe should show the tool working: no error in the panel.
- `scenes.py`: everything else, as `@shot("<id>", "<what it shows>")` functions returning a
  `QImage`.

Use a shot in a page as `[![<what it shows>](../assets/shots/<id>.png)](../assets/shots/<id>.png)`
(adjust the `../`). The build fails if a page uses a shot that doesn't exist, or a shot isn't used.

- Never hand-make or edit a screenshot, and never put one in `docs/content` yourself.
- Look at every new or changed shot before you hand the change over.

### Never edit generated files

`docs/build.py` overwrites these, and deletes anything there it didn't write:

- `docs/content/reference/` (all of it)
- `docs/content/assets/shots/`, `docs/content/assets/icons/`, `docs/content/assets/logo.svg`
- `docs/content/changelog.md` (rebuilt from git tags each build, not committed)
- `docs/_data/catalog.json`, `docs/_data/panels.json`, `docs/_data/shots.json`
- the block between `# BEGIN GENERATED tools` and `# END GENERATED tools` in `docs/zensical.toml`

Each generated Markdown file starts with a comment naming its sources. Change those instead.

### Writing the hand-written pages

- Write for people modelling parts, not for developers. The site's purpose is to teach the
  workbench. Plain words, short sentences, sentence case headings, second person ("you").
- Use the workbench's own names for things, exactly as the UI shows them (**Extrude**, **Add**,
  **Feature Scope**, **Rollback bar**).
- Don't type numbers that come from the code: they go stale. Use `{{ name }}` in authored tool
  pages, or link to the generated page that shows them.
- Keep `docs/content/index.md` (the landing page) a short overview.
- Notes go in `docs/_notes/` (not published), never in `docs/content/`.

## Tests

```bash
freecadcmd tests/run.py                                        # headless
SD_TESTS=test_extrude freecadcmd tests/run.py                  # one module
xvfb-run -a -s "-screen 0 1600x1000x24" freecad tests/gui/explore.py   # GUI scenarios
```
