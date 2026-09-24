# Art asset notes for modders

The game currently uses pixel-art spritesheets and one projectile image. Keep
new artwork in this folder (or use a path that exists from the project root).
The engine loads the files directly; it does not build a texture atlas or read
an asset manifest.

## Character sheets

- `Soldier.png` is the standard seven-row sheet.
- `Orc.png` is the included six-row sheet; it has no dedicated ranged row.
- Cells are 100 x 100 pixels. Do not add spacing between cells unless you also
  change `worldforge/ui/sprite_sheet.py`.
- Standard row order, top to bottom: idle, walk, melee hit 1, melee hit 2,
  ranged attack, take damage, death.
- Six-row Orc order: idle, walk, melee hit 1, melee hit 2, take damage, death.
- Animation frame counts live in `worldforge/ui/sprite_sheet.py`. The loader uses only the
  first configured number of columns and falls back to other animations when a
  row is absent. Keep character sheets at least one cell wide and tall.

To add a character, place a compatible PNG here, then make its exact path
available in the avatar options in `worldforge/ui/creation_screen.py`, or reference it in an
NPC's `avatar` field. If your sheet has a new layout, add a layout mapping in
`worldforge/ui/sprite_sheet.py`; merely adding an image does not teach the loader its rows.

`Arrow01.png` is the current projectile graphic for bows and crossbows. Its
visible non-transparent bounds are cropped at load time and scaled in `worldforge/app/loop.py`.
Thrown weapons currently play the ranged animation but do not render a unique
weapon projectile; add that art/selection explicitly if you want it.
