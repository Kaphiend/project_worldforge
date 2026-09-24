# `spells.json`

Each top-level key is a spell/effect ID. Classes list the spell ID in their
known spells at creation; consumables can refer to the same record through
`equipment.json`'s `effect_id`.

- `name`, `description`: UI/log text.
- `classes`: exact class IDs permitted to cast this spell normally. A
  consumable bypasses class-known-spell checks.
- `casting_time`, `prerequisite_class_level`, `acquisition`: reference and
  progression fields. Spells have no ranks; casts use the character's level
  and one shared spell-point pool. Each class defines a tuneable point
  progression curve. `spell_point_cost` is the number of points charged
  for a successful cast (defaults to `1`; set it to `0` for a cantrip, or use a
  larger integer for a more expensive spell). A zero-cost spell still uses the
  normal spell action and targeting flow. Records with `cantrip: true` and
  `acquisition: "starting_cantrip"` are granted at character creation to
  matching classes and migrated onto older saves. The spellbook can prepare
  known spells. Spell records marked `acquisition: "trainer_purchase"` are
  sold by the map trainer. Set `xp_purchase_cost` on each record to its
  one-time XP price; this is separate from `spell_point_cost`, which is paid
  for each cast. Tier access uses `prerequisite_class_level` and the
  character's sequential purchase chain for that class. A character must own
  at least one purchase spell at each prior tier, and current unspent XP sets
  the shared tier ceiling. The demo's
  Arcane Spark and Frost Needle are starter attack cantrips. Consumable items
  that invoke a spell do not spend the character's pool. Component requirements
  are not wired. Existing `tier`
  values are legacy data and have no runtime effect.
- `targeting.mode`: currently used modes include `self`, `one_target`,
  `one_ally`, `small_area`. The game requires a selected actor for non-self
  actions; `small_area` centers on that selected actor.
- `targeting.range_feet`: maximum target distance. If omitted, no numeric limit
  is checked. `requires_line_of_sight` makes the arena obstacle test mandatory.
- `resolution.kind`: supported values are `automatic`, `healing`,
  `self_enchantment`, `utility`, `spell_attack`, and `saving_throw`.
  Saving throws also need an `ability` key.
- `effects`: either a list applied for every outcome or an object mapping
  `hit`/`miss`, `failed_save`/`successful_save`, etc. to lists of effects.

Supported effect records:

- `{ "kind": "damage", "formula": "1d6", "damage_type": "fire" }`
- `{ "kind": "healing", "formula": "2d4", "can_revive": true }`
- `{ "kind": "condition", "condition_id": "burning" }`
- `{ "kind": "heal_caster_from_damage", "formula": "1d4" }`
- `{ "kind": "next_weapon_hit_bonus", "formula": "1d4", "duration_turns": 1 }`
- `{ "kind": "armor_bonus", "amount": 2, "duration_turns": 1 }`
- `{ "kind": "movement_bonus", "feet": 10, "duration_turns": 1 }`
- `{ "kind": "send_message", "range_feet": 60 }`

Spell attacks use spellcasting modifier + proficiency; save DC is 8 + those
values. A success roll can still do zero damage or apply no effects. New target
modes, resolution kinds, or effect kinds require edits to `spell_effects.py`
and often `game.py`.
