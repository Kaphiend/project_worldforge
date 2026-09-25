# Art asset notes for modders

The game currently uses pixel-art spritesheets and one projectile image. Keep
new artwork in this folder (or use a path that exists from the project root).
The engine loads the files directly; it does not build a texture atlas or read
an asset manifest.

## Character sheets

Cells are 100 x 100 pixels. Do not add spacing between cells unless you also
change `worldforge/ui/sprite_sheet.py`. Seven-row sheets use this row order:
idle, walk, melee hit 1, melee hit 2, ranged attack, take damage, death. The
six-row Orc sheet omits the ranged row.

Frame counts for each sheet, in that row order:

| Sheet | Idle | Walk | Melee 1 | Melee 2 | Ranged | Hurt | Death |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Soldier | 6 | 8 | 6 | 6 | 9 | 4 | 4 |
| Orc (six rows) | 6 | 8 | 6 | 6 | — | 4 | 4 |
| Goblin | 7 | 7 | 7 | 5 | 6 | 3 | 4 |
| Barbarian | 8 | 8 | 7 | 6 | 6 | 3 | 4 |
| Bard | 8 | 8 | 6 | 6 | 6 | 3 | 4 |
| Cleric | 8 | 8 | 7 | 6 | 6 | 3 | 4 |
| Druid | 8 | 8 | 7 | 6 | 7 | 3 | 4 |
| Fighter | 8 | 8 | 5 | 6 | 7 | 3 | 4 |
| Monk | 8 | 8 | 6 | 7 | 7 | 3 | 4 |
| Paladin | 6 | 8 | 5 | 6 | 4 | 4 | 4 |
| Ranger | 8 | 8 | 5 | 6 | 7 | 3 | 4 |
| Rogue | 8 | 8 | 4 | 7 | 5 | 3 | 4 |
| Sorcerer | 8 | 8 | 6 | 6 | 5 | 3 | 4 |
| Warlock | 8 | 8 | 5 | 6 | 5 | 3 | 4 |
| Wizard | 6 | 8 | 5 | 5 | 2 | 3 | 3 |

New characters use the sheet matching their class; classes without a mapped
sheet use `Soldier.png`. `Goblin.png` is the fallback mob sheet and is assigned
to the demo raider. Animation mappings live in
`worldforge/ui/sprite_sheet.py`; keep its counts in sync with the sheet.

To add a character, place a compatible PNG here, then reference its exact path
in an NPC's `avatar` field. If your sheet has a new layout, add a layout mapping
in `worldforge/ui/sprite_sheet.py`; merely adding an image does not teach the
loader its rows.

`Arrow01.png` is the current projectile graphic for bows and crossbows. Its
visible non-transparent bounds are cropped at load time and scaled in `worldforge/app/loop.py`.
Thrown weapons currently play the ranged animation but do not render a unique
weapon projectile; add that art/selection explicitly if you want it.
