# Building Worldforge

Worldforge uses Pygame and can be packaged as a PyInstaller one-folder app.
Build on the operating system you intend to ship for; PyInstaller does not
cross-compile Windows, macOS, and Linux executables from one another.

## Requirements

- Python 3.10 or newer
- The packages in `requirements-build.txt`

## Build

From the repository root, create and activate a virtual environment, then run:

```sh
python -m pip install -r requirements-build.txt
python -m PyInstaller --clean --noconfirm worldforge.spec
```

The distributable folder is `dist/Worldforge/`. Launch `Worldforge` inside it
(`Worldforge.exe` on Windows). Copy the complete folder when distributing; the
executable depends on the adjacent runtime libraries and bundled resources.
The spec includes the JSON content tables and PNG art, and excludes character
saves. Add new runtime resource types to `worldforge.spec` when the game starts
loading them.

## Packaged data locations

In a source checkout, content is read from the project directory and saved
characters stay in `saves/`. In a frozen build, bundled content is read from
PyInstaller's temporary resource root. Character saves and user-created mods
go to the platform's per-user Worldforge data directory:

- Windows: `%APPDATA%/Worldforge/`
- macOS: `~/Library/Application Support/Worldforge/`
- Linux: `$XDG_DATA_HOME/Worldforge/`, or `~/.local/share/Worldforge/` when the
  environment variable is unset

Create a `mods/` directory there and add mod subfolders using the same JSON
table names as `data/mods/`. Bundled demo mods load first; user mods load after
them in alphabetical order and can override matching IDs. To reset packaged
character data, back up and remove the `saves/` directory in this location.
Custom sprite sheets can be placed under this same data root at the path used
by the mod (for example, `asset_pack/MySprite.png`).

## Release checks

1. Build from a clean virtual environment on each target operating system.
2. Run the app from outside the checkout to confirm it does not depend on the
   current working directory.
3. Create a character, quit, and relaunch to verify saves persist.
4. Add a small user mod under the documented per-user `mods/` directory and
   confirm its record is loaded.
5. Start a game and confirm both character sprites and the ranged projectile
   load from the packaged folder.

The build spec is maintained with the source. A release build itself must be
run on the target platform and is not implied by editing this file.
