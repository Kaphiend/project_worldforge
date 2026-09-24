# Game data

For step-by-step modding help and a file-by-file code map, start with the
project's [`docs/modding/README.md`](../modding/README.md). Field-by-field notes for
each JSON table are in [`modding/`](../modding/tables/README.md).

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
`progression.json` contains tuneable multiclass unlock prices and class-order
price multipliers for trained spells and abilities.

## Combat and items

`equipment.json` contains item templates, slot rules, damage dice, range, and
armor properties. Actor inventory entries are uniquely identified instances.
`item_attributes.json` defines the initial rollable gear-effect pool: doubled
weapon damage dice, weapon attack and damage bonuses, armor class, maximum hit
points, and saving throws.
Each attribute declares eligible categories and slots, item-level bounds, a
uniqueness group, and its effect. `mob_generation.json` tunes class priorities,
elite scaling, rarity weights, and how many attributes each rarity can carry.
Generated attributes apply to combat stats. Defeated NPCs place
their carried inventory and equipped gear into one shared corpse container;
press `F` within 5 feet to loot it. Taking all or closing the loot panel starts
the corpse's three-second despawn timer. New mob instances use their NPC
template's equipment as their drops. Consumable templates can reference an effect in `spells.json`.
The demo includes healing potions and a revival scroll; each effect has its own
healing formula. Press 1 for the active weapon set's primary attack. Press T to
explicitly throw a thrown-tagged main-hand weapon; pressing 1 never auto-throws.

`spells.json` and `abilities.json` store original game effects. Spell attacks
use the caster's class spellcasting modifier plus proficiency; spell save DC is
8 plus those values. Burning deals 1d4 fire damage at the start of the affected
actor's turn for two turns; reapplication refreshes its duration. Spell-point
costs are charged from a shared class-curve pool; records set
`spell_point_cost` (default 1, cantrips 0). Resting replenishes the pool and
configured class resource pools. The game has no spell ranks, and implemented
spell effects do not yet scale with character level. See
[`modding/spells.md`](../modding/tables/spells.md) for supported effect records.

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
