# Install

Solid Design needs **FreeCAD 1.1** or newer. It runs wherever FreeCAD does: Linux, Windows and
macOS.

## Download it

Get the workbench from [its GitHub page](https://github.com/ryankembrey/SolidDesign): click
**Code → Download ZIP** and unpack it, or clone it with git:

```bash
git clone https://github.com/ryankembrey/SolidDesign.git
```

## Put it in FreeCAD's Mod folder

FreeCAD loads workbenches from the `Mod` folder in your FreeCAD user folder. Move (or link) the
`SolidDesign` folder there:

=== "Linux"

    ```bash
    mkdir -p ~/.local/share/FreeCAD/v1-1/Mod
    ln -s "$PWD/SolidDesign" ~/.local/share/FreeCAD/v1-1/Mod/SolidDesign
    ```

=== "Windows"

    Move the `SolidDesign` folder into `%APPDATA%\FreeCAD\v1-1\Mod` (paste that into the
    Explorer address bar to get there; make the `Mod` folder if it isn't there).

=== "macOS"

    Move the `SolidDesign` folder into `~/Library/Application Support/FreeCAD/v1-1/Mod`.

If you're not sure where your user folder is, FreeCAD's Python console tells you:
`FreeCAD.getUserAppDataDir()`.

## Start it

Restart FreeCAD and choose **Solid Design** in the workbench list on the toolbar. Its toolbars
and the **Solid Design** menu appear.

Next: [around the workbench](interface.md).
