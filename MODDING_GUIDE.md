# Worldforge modder guide

This is the hands-on guide for changing the gray-box game. You do **not** need
to change Python for ordinary content edits. Start by copying an example JSON
record, changing its ID and values, then put it in a mod folder. Keep the game
closed while editing: data is read once when Python starts.

For the overall game direction and the checklist of unfinished systems, see
[`DESIGN.md`](DESIGN.md).

The built-in files are the default content. Put your own work in
`data/mods/my_mod/`; do not edit the built-in records just to try an idea.
The included example mod is `data/mods/demo_slice/`.

For a Windows, macOS, or Linux PyInstaller build, see
[`BUILDING.md`](BUILDING.md). Frozen builds keep bundled content read-only,
write saves under the user's Worldforge data folder, and load extra mods from
that folder's `mods/` directory.

## Documentation promise

New data-driven systems should include a matching reference under
`data/modding/`: field names, defaults, valid values, tuning behavior, and a
copyable example. New runtime systems should also be mapped in this guide or
`DESIGN.md`, including lifecycle, save/network ownership, extension points,
and current limits. Keep the docs updated in the same change as the code so
modders and maintainers can follow the implemented behavior.

## World interactions

`F` is the shared nearby-interaction key. The current implementation supports
inn beds: when the active character is within the bed's configured
`interaction_range_feet`, `F` opens a confirmation prompt. Confirm with `Y` or
Enter to attempt an inn rest; cancel with `N` or Escape. The rest costs 10 gold
per participating character, and the party rest is applied only when all
participants can pay and meet the bed-distance requirement. `Z` remains the
outdoor camp action.

Bed interaction range is configured on each arena's `inn_beds` entry. For
example:

```json
{"id":"inn_bed", "name":"Inn Bed", "x":130, "y":170,
 "width":100, "height":60, "interaction_range_feet":15}
```

Doors, chests, and corpse-loot interactions are planned to use this same `F`
interaction path; they do not have runtime behavior yet. When adding one,
prefer an explicit interaction type and keep proximity, confirmation, and
result feedback consistent with the inn-bed flow.

## Spell bars and saved assignments

Player spell and ability assignments are stored in the actor's `spell_hotbars`
save field as four lists of ten typed action IDs (`spell:<id>`,
`ability:<id>`, or `action:<id>`; `null` means an empty slot). Weapon Attack is
available on the Abilities page for every actor and assigned to slot 1 by
default. Ranged Weapon Attack appears when a ranged weapon is equipped, and
Throw Main-hand Weapon appears for a weapon tagged `thrown`. These system
actions are defined in `spellbook_ui.py` and can be extended there. Legacy untyped spell IDs are
migrated as spells. Assigned bars stack in the bottom-left area; only bars and
slots with assignments are drawn in the world HUD. A marker indicates which
bar the number keys currently use. The Prepared Spells page offers only IDs in
`prepared_spells`; the Spellbook page lets players prepare known spells, and
Class Abilities lists `known_abilities`. Assignment does not teach an action or
bypass runtime checks. Each bar maps left-to-right to keys
`1` through `9`, then `0`. Backtick cycles the active bar, `-` opens/closes the
spellbook, F2 toggles hover tooltips, and right-clicking a slot in the spellbook
clears it. The actor's `quick_items` field maps `q` and `e` to inventory item
IDs; only consumables can be assigned in the inventory UI, and the binding is
cleared when the item is consumed. Older character
saves are padded with four empty bars on load. The game window is 1024x768 and
the demo arena is 1600x1100, so the camera continues scrolling around the map.
For stack settings on item templates, see [`equipment.md`](data/modding/equipment.md).
Enter opens local chat input. Text appears above the speaker for 2.5 seconds;
`/act <emote>` shows a named emote bubble and submits a host-processed combat
log entry. Ordinary chat is not added to the combat event log. Network speech
uses an absolute expiry timestamp in each player's relayed state, and chat
commands use the existing combat-action request path.
The spellbook separates prepared spells (assignable and castable), all known
spells (click a row to toggle preparation), and class abilities. Prepared IDs
are saved in `prepared_spells`; old saves initialize that list from their known
spells. Spell records marked `cantrip: true` with `spell_point_cost: 0` use an action
without spending the shared spell pool. `starting_cantrip` acquisition is
granted to matching classes at character creation and added to older saves;
Trainer-purchase spells are unlocked at the map trainer using each record’s
`xp_purchase_cost`; starting cantrips are still granted by class data. The demo includes Arcane Spark and Frost Needle as
level-one caster attacks; tune damage, range, classes, and descriptions in
`data/spells.json`.
The map trainer charges per-item `xp_purchase_cost`. Current unspent XP sets
the shared purchase tier and class ownership ledgers enforce sequential tiers.
Creation hover text comes from each race, subrace, and class `summary`; subclass
choices use their existing `description` and a feature summary. Arena trainer
and respawn positions are configured in `arenas.json`.

## The safest way to make a mod

1. Create a new folder, for example `data/mods/my_forest/`.
2. Create only the JSON tables you need in that folder. The filename must match
a built-in table exactly, such as `npcs.json` or `arenas.json`.
3. Copy a whole working record from the matching JSON file or from
   `data/mods/demo_slice/`. Change IDs and references carefully.
4. Check every comma, quote, bracket, and reference. JSON uses double quotes;
   it does not allow comments or trailing commas.
5. Start the game again. If startup fails, the error normally names the file
   and the line where the JSON parser got confused.

### How mod loading works

`classes.py` loads each table from `data/<table>.json`, then reads matching
files in `data/mods/` in alphabetical folder order. A later mod replaces an
earlier record with the **same top-level ID**. The merge is shallow: replacing
one class replaces that class's entire record, including all its skills,
starting gear, subclasses, and progression. It does not merge individual
nested fields. Give new content a new ID whenever you are adding rather than
replacing.

Mods do not currently have an enabled/disabled menu. Every folder under
`data/mods/` is loaded. To temporarily turn off a mod, move its folder outside
`data/mods/`; do not rename individual JSON files to `.bak` inside the mod.

### Copyable starter mod

```text
data/mods/my_forest/
  README.md
  arenas.json
  npcs.json
  scenarios.json
```

```json
{
  "forest_path": {
    "name": "Forest Path",
    "bounds": {"x": 0, "y": 0, "width": 1200, "height": 800},
    "ground_color": [58, 92, 62],
    "edge_color": [30, 48, 34],
    "decorations": [],
    "obstacles": []
  }
}
```

Then make a scenario record whose `arena` is `forest_path`, and give it an
`enemies` entry whose `npc` exactly matches an ID in your `npcs.json`.
A scenario, arena, or NPC that refers to a misspelled ID will not be found.

## Put changes in the right place

| What you want to change | Edit this file or folder | Python required? |
|---|---|---|
| Add a weapon, armor, accessory, potion, or scroll | `data/mods/<name>/equipment.json` | No, if it uses supported item fields |
| Change weapon damage, reach, thrown range, tags, or hand count | `equipment.json` | No, for fields read by combat |
| Add or tune spells | `spells.json` | No, if the effect uses a supported resolver kind |
| Add class abilities | `abilities.json` | No, if the effects are supported |
| Add a status/condition | `conditions.json` | Only existing condition primitives work; new behavior needs code |
| Add an NPC | `npcs.json` | No, for existing actor fields and AI |
| Add a map | `arenas.json` | No, for rectangles and existing decoration kinds |
| Put NPCs on a map and set objective text | `scenarios.json` | No |
| Add or tune character classes | `classes.json` | Mostly; new skills may need a Python change |
| Add race/subrace choices | `races.json` | Mostly; new race rules may need code |
| Add subclass names and milestone descriptions | `subclasses.json` and class `subclasses` list | No for descriptions; code for mechanical powers |
| Change how a field is interpreted or invent a new effect | `combat.py`, `spell_effects.py`, `conditions.py`, or `game.py` | Yes |
| Change player creation steps or screen layout | `creation_flow.py`, `creation_screen.py` | Yes |
| Change sprite animation layout | `sprite_sheet.py` | Yes, and keep sheets compatible |
| Change connection limit or network protocol | `networking.py` | Yes |

The per-table references in [`data/modding/`](data/modding/README.md) list fields,
examples, and common mistakes. JSON cannot carry comments, so these sidecar
notes are the comments for the data files.

## File-by-file map

### Run the game and join a session

- `main.py` starts the main menu, character creation, and game loop. It chooses
  the player's initial position from the scenario's `player_spawns`. Change
  startup/session flow here only when you mean to change how every session works.
- `menu.py` draws single-player/host/join screens and validates invitation
  addresses. It is not the place for gameplay menus.
- `networking.py` hosts a direct TCP session, relays player state, and relays
  combat requests. `PORT` and `MAX_PLAYERS` are session-wide settings. It is
  authoritative for host/client communication; do not put game rules here.
- `client.py` and `host.py` are compatibility launch files. Both call
  `main.main()`; they are not separate game implementations.
- `runtime_paths.py` resolves bundled resource paths and the writable
  per-user data directory used by packaged builds.

### Actors, character setup, and saves

- `factory.py` defines the `Actor` data shape, default values, class starting
  equipment, item instances, legal equipment slots, and the randomized demo
  character. Add a new persistent actor field here before relying on it in
  saves or network state.
- `creation_flow.py` holds the rules and stages for making/loading a character.
  `creation_screen.py` draws and handles the buttons for those stages. When you
  add a stage, update both files: the flow decides what is valid; the screen
  lets the player choose it.
- `storage.py` saves `Actor` fields to `saves/<actor-id>.json`, loads them, and
  locks actors that are in use. If you add a field, use a default/migration so
  old saves can still load.
- `inventory_ui.py` is the current inventory modal. It sends equip, unequip,
  and item-use requests; it is not the source of equipment legality. That is
  in `factory.py`.

### Rules, combat, and effects

- `combat.py` is the source for attack rolls, damage, AC, initiative, movement
  speed, weapon selection, and distances. This is where a new weapon tag or
  new combat calculation must be interpreted. A JSON field by itself does not
  make a new rule work.
- `game.py` runs the Pygame frame loop, world movement, collision, target
  clicks, combat turns, animation requests, combat log, and display. Use it to
  connect a new action/input to the resolver. Keep data interpretation out of
  drawing code where possible.
- `spell_effects.py` resolves spell and ability targeting, attack/save rolls,
  and supported effect primitives. Add a new primitive here and update its
  data-side notes before using it in JSON.
- `conditions.py` applies conditions, recurring damage, expiration, and limited
  uses. It currently recognizes only the primitive kinds implemented there.
- `dice.py` parses dice strings such as `2d4+2`, rolls d20s, and generates
  ability scores. Use its notation rather than writing a separate dice parser.
- `controllers.py` selects an actor brain. The current AI is intentionally
  simple. `AIController.actions_for_turn` chooses actions; `game.py` validates
  and resolves them. New AI should return action dictionaries understood by
  the game instead of editing HP directly.

### Art and data loading

- `classes.py` loads all JSON tables and applies mod overrides. It also owns
  `ALL_SKILLS` and `skill_options()`: if you add a brand-new skill for the
  `"any"` picker, add it there too.
- `sprite_sheet.py` reads sprite sheets as 100-by-100 cells. The standard
  seven-row order is idle, walk, melee hit 1, melee hit 2, ranged, hurt, death.
  The included Orc sheet has six rows: idle, walk, two melee rows, hurt, death.
  Missing frames fall back to other frames. Update this module if a sheet has a
  different cell size or row order.
- `asset_pack/Orc.png` and `asset_pack/Soldier.png` are character sheets;
  `asset_pack/Arrow01.png` is the current projectile art. Character avatar paths
  are stored in NPC or actor data and must be paths the game can load.
- `data/README.md` is the short overview. Keep it as a quick entry point; use
  this guide and `data/modding/` for detailed instructions.
- `data/mods/demo_slice/README.md` explains the supplied encounter mod and its
  cross-file IDs. Add a `README.md` beside your own mod JSON so you remember
  what you changed.
- `saves/README.md` explains why saved actors belong in `saves/` and content
  templates belong in `data/mods/`. Save files are runtime data, not a mod API.
- `asset_pack/README.md` describes character-sheet dimensions, animation rows,
  the six-row Orc exception, and the current projectile graphic.

## Rules modders often trip over

- **IDs are references.** JSON object keys are IDs. `template_id`, `effect_id`,
  `condition_id`, class IDs, subclass IDs, NPC IDs, and arena IDs must exactly
  match another record where applicable.
- **A weapon field needs runtime support.** `damage_dice`, `ranges`, `tags`,
  `hands_required`, and `damage_profiles` only affect play where `combat.py`
  reads them. An invented key is saved in data but has no effect by itself.
- **Primary attack versus thrown attack.** Press **1** to attack with the active
  weapon set. A thrown-tagged weapon does not throw automatically when the
  target is out of melee reach. Press **T** to explicitly throw the main-hand
  weapon; it must have the `thrown` tag. This is the current gray-box rule.
- **Combat begins with the opening action.** A valid attack can start combat
  immediately. Range and line of sight are checked using actor collision
  hitboxes and arena obstacles. The player's exploration position is preserved.
- **Perception labels.** Put ordered `{ "dc": number, "title": "Text" }` entries
  in an NPC's `perception.levels`. The label shown is the highest DC the player's
  passive score meets. Passive Perception is 10 + Wisdom modifier, plus
  proficiency when `"perception"` is in the actor's `skills`. It ignores
  distance and sight. Keep DCs increasing for predictable tiers.
- **Spell math is data-selected but code-limited.** Existing resolution kinds
  are `automatic`, `healing`, `self_enchantment`, `utility`, `spell_attack`,
  and `saving_throw`. Existing effects include `damage`, `healing`, `condition`,
  `heal_caster_from_damage`, `next_weapon_hit_bonus`, `armor_bonus`,
  `movement_bonus`, and `send_message`. New strings outside this list need code.
- **Conditions are not fully generic.** `conditions.json` controls names,
  duration, reapplication, and describes primitives. At runtime `conditions.py`
  currently executes recurring `damage_over_time` and tracks
  `attack_disadvantage`; `game.py` interprets `bound_in_briar` as stopped
  movement. A new primitive needs matching Python behavior.
- **Progression text is not a power.** Class progression and subclass milestone
  entries are currently descriptive/unlock data. They do not automatically
  grant a mechanical effect. Spells and abilities with supported effects are
  separate records.
- **Starting items use catalog templates.** Put `{ "template_id": "dagger" }`
  in a class's `starting_gear`; the gear is added as a unique instance. The
  class key is the destination slot. Use exact supported slot names.
- **Mod overrides replace whole records.** If you override a class or weapon to
  change one value, copy the complete base record first. Otherwise fields you
  did not repeat disappear from that loaded definition.
- **Do not add comments inside JSON.** Put explanations in the matching
  `data/modding/*.md` file or your mod's `README.md`.

## A good first mod

Start by making a new NPC and a tiny scenario that uses an existing arena. Once
that works, copy the arena into your mod and customize it. Then make a weapon
or consumable. This order helps: if the NPC does not appear, you only need to
check a scenario/NPC ID; if the map also changed, there are more references to
inspect.

To make your NPC easier to identify at different Perception scores, add:

```json
"perception": {
  "levels": [
    {"dc": 10, "title": "Bandit"},
    {"dc": 14, "title": "Bandit Lookout"},
    {"dc": 18, "title": "Mara's Scout"}
  ]
}
```

To make a usable consumable, add a `category: "consumable"` equipment template
with `consumable: true` and an `effect_id`, then add that effect to
`spells.json`. For an effect kind the engine already supports, this can be done
without Python. Copy the healing potion and restorative revival records to see
working patterns.
