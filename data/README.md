# Game data

The game loads JSON tables from `data/` at startup. Mods can add or replace
entries by placing matching files under `data/mods/<mod-name>/`; folders load
alphabetically and later definitions replace matching IDs.

## Characters

`classes.json` defines twelve archetypes, proficiencies, selectable skills,
starting gear, and original level progression. `subclasses.json` defines
three original paths per class, with feature names and short summaries at
levels 3, 6, 10, and 14. Subclass choice and trained skills are selected during
character creation. These progression entries are descriptive data; class and
subclass feature effects are not yet implemented.

`races.json` contains ancestry and trait reference data, including a
Two-Parent Half-Breed choice. Ability bonuses are not automatically applied.

## Combat and items

`equipment.json` contains item templates, slot rules, damage dice, range, and
armor properties. Actor inventory entries are uniquely identified instances.
Rarity and rolled attributes remain empty placeholders; loot generation is not
implemented. Consumable templates can reference an effect in `spells.json`.
The demo includes healing potions and a revival scroll; each effect has its own
healing formula.

`spells.json` and `abilities.json` store original game effects. Spell attacks
use the caster's class spellcasting modifier plus proficiency; spell save DC is
8 plus those values. Burning deals 1d4 fire damage at the start of the affected
actor's turn for two turns; reapplication refreshes its duration. Spell-point
costs are not implemented.

NPC `perception.levels` is a list of `{dc, title}` records. A player's passive
perception is 10 plus Wisdom modifier and proficiency bonus when trained in
Perception. Nameplates show the highest title whose DC is met. This information
is automatic and ignores distance and line of sight. Arena obstacle rectangles
block attack and spell line of sight when a resolution requires it.

## Demo world and co-op

`scenarios.json` points to an arena and lists NPC spawns, player spawn
coordinates, objective, and victory text. `arenas.json` describes map bounds,
decorations, and solid obstacle rectangles. Exploration and combat movement
stay within bounds and collide with obstacles. Co-op supports up to eight
connected players including the host; invitations use direct TCP port 5555.
Internet hosts must forward that port and share their public address.
