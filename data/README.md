# Game data

`classes.json`, `races.json`, `equipment.json`, `spells.json`,
`abilities.json`, `conditions.json`, `npcs.json`, `arenas.json`, and
`scenarios.json` contain the built-in data.
The game loads these JSON files at startup.

Mods can add or replace definitions by placing matching JSON files in
`data/mods/<mod-name>/`. Mod folders load alphabetically, and later definitions
replace entries with the same key. A mod can include only the tables it changes.
The included `demo_slice` mod is a complete example: it defines the First Contact
scenario, its roadside arena, and an AI raider. Edit those JSON files to change
the demo encounter or copy the pattern to create another scenario.

Class records describe twelve broad character archetypes, their baseline
proficiencies, skills, and starting equipment. Every class has an original
level-by-level feature track. These are trainer purchase options, not automatic
grants; each class track unlocks sequentially and spends XP earned at the current
character level. Feature summaries define the concepts; their combat effects
will be implemented by the Worldforge rules resolver. Subclasses remain an empty
extension point.

`spells.json` stores original spell entries and their resolution modes. Each
healing entry carries its own formula. `abilities.json` uses the same effect
vocabulary for non-spell class abilities. `conditions.json` combines supported
effect primitives with display names and durations. Burning deals 1d4 fire
damage at the start of the affected actor's turn for two turns; reapplication
refreshes its duration. A consumable can point to a spell's effect data.

Spell attacks use the caster's class spellcasting modifier plus proficiency;
spell save DC is 8 plus those values. New level-one characters receive their
class's current core spells and abilities as known options. Click a target, then
use 1 for the equipped weapon, 2-9 for spells, Q/E for abilities, and Enter to
end a turn. Spell-point costs remain unwired while the resource scheme is
undecided. Each local or co-op connection controls one character. The existing
Each local or co-op connection controls one character. `scenarios.json` points
to an arena and lists NPC spawn records (`npc`, `x`, `y`), player spawn
coordinates, an objective, and a victory message. `arenas.json` describes the
play bounds, ground/edge colors, decorations, and solid obstacle rectangles.
The camera follows the local actor, stopping at map edges; both exploration and
combat movement stay inside the bounds and collide with solid obstacles.
`npcs.json` uses
actor fields such as `max_hp`, `abilities`, `equipment`, and `controller`;
equipment may reference an `equipment.json` `template_id`. The demo includes
eight player spawn positions to match the co-op cap. Victory offers the host a
rematch and lets everyone return to the session menu with M.

Co-op supports up to eight connected players including the host. Invitations
use a direct TCP address on port 5555; Internet hosts must forward that port
and share their public IP or hostname. There is no relay service in this build.

`equipment.json` stores item templates: category, valid slots, hand requirements,
tags, damage dice, ranges, ammunition, and armor properties. Actor inventory
entries are unique instances. Rarity and rolled attributes are empty placeholders
for future loot generation.

`races.json` currently contains the four design-document examples plus the
two-parent Half-Breed option. Trait identifiers are generic data labels; the game
does not interpret their effects yet. Ability bonuses remain reference data and
are not automatically applied.
