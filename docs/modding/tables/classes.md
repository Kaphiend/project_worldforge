# `classes.json`

Each top-level key is the class ID. Character creation stores this exact ID in
`actor.char_class`. Existing IDs are lowercase, singular class names; changing
one can invalidate existing saves and references.

## Fields

- `hit_die`: number of sides for the class HP die, for example `8`.
- `saves`: ability IDs that the class is trained to resist with.
- `armor_prof`, `weapon_prof`: category strings checked by combat/equipment code.
  Keep names consistent with the existing table, such as `light`, `shields`,
  `simple`, and `martial`.
- `skills`: list of skill names offered by the class trainer. The value
  `["any"]` means every skill in `worldforge/content/classes.py:ALL_SKILLS`.
- `skill_choices`: maximum number of distinct skills purchasable for this
  class. It cannot be greater than the list of selectable names.
- `starting_gear`: an object whose property name is the equipment slot. Each
  value normally looks like `{ "template_id": "sword_1h" }`. The template must
  exist in `equipment.json`, and the slot must be allowed by that template.
- `subclasses`: ordered list of IDs from `subclasses.json` that this class may
  choose. A missing referenced ID produces a broken/empty choice.
- `subclass_level`: documented level at which the subclass is chosen; built-in
  SRD 5.2.1 classes use level 3.
- `spellcasting_ability`: ability ID used for this class's spell attack and
  save DC, if it can cast.
- `spellcasting_progression`: `full`, `half`, or `pact`; determines which
  slot table applies. `spell_slots_by_caster_level` stores the SRD Spellcasting
  slot row for each combined caster level (one-based rows). Full and half
  casters share Spellcasting slots; half-caster levels combine and round down.
  Warlocks use `pact_slots_by_level` and `pact_slot_level_by_level`.
- `prepared_spells_by_level`, `cantrips_by_level`: level-indexed class limits;
  index zero is unused.
- `class_resources`: optional named pools separate from spell slots, such as
  `lay_on_hands`. Each entry may define `name`, `max_by_level` (same indexing
  rule), `recovery` (`short_rest`, `long_rest`, or `short_or_long_rest`), and
  optional `short_rest_recovery`. Runtime saves store current amounts by
  `class_id.resource_id`. Abilities can spend
  these pools with their `resource_cost` field. Add class data only when the
  rules and recovery cadence are defined; this project does not assume
  fifth-edition values for special pools.
- `starting_spells`, `starting_abilities`: optional lists of IDs granted to a
  new character of this class. Starter spells are learned/prepared, and starter
  abilities are learned; both are placed on the first hotbar at creation.
- `starting_features`: optional feature IDs added to a new character's owned
  feature list. Use only for features the class gets at its starting level.
- `progression`: map of class levels to arrays of feature entries. Entries
  usually have `id`, `name`, `summary`, and prerequisite data. Class features
  are normally purchased from the trainer with XP; only explicit
  `starting_features` are granted automatically.
  `xp_purchase_cost` sets the price and defaults to `10`. Starter spells and
  abilities listed separately above do not require trainer purchases. Built-in selectable
  skill lists and subclass choices follow SRD 5.2.1; purchased skills and
  features still require XP. Former Worldforge subclasses remain nonselectable
  for old saves. Hide, Sneak Attack, Rage, Reckless Attack, Second Wind, Action
  Surge, Fighter Extra Attack/Tactical Shift, Champion critical range, Monk
  Flurry/Patient Defense, Cunning Action: Dash, and `extra_weapon_attack`
  currently have combat behavior; most other feature effects are descriptive
  until their resolver is implemented. Fighter Fighting Styles Archery,
  Defense, Dueling, Great Weapon Fighting, and Two-Weapon Fighting have combat
  behavior; Protection awaits its reaction choice flow. Rogue combat
  supports Sneak Attack scaling, Cunning Action, Steady Aim, Cunning Strike
  Trip/Poison/Withdraw, Expertise, Evasion, Reliable Talent, Slippery Mind,
  Elusive, opportunity attacks, Expertise selection, and automatic Uncanny
  Dodge. Weapon Mastery supports Vex, Sap, Slow, and Topple; Stroke of Luck,
  remaining mastery/Cunning Strike riders, and player-choice reaction UI
  remain queued in `docs/project/COMBAT_CONTENT_BACKLOG.md`.
- `progression_policy`: currently descriptive purchase/unlock metadata; it does
  not add a shop or XP UI by itself.

## Add a class

Copy a whole class record, assign a new key, fill proficiencies and starting
gear, then give it at least one skill and class entry in any spells/abilities
that should allow it. Add matching subclass records if you want choices.
For a class with `skills: ["any"]`, add new global skill names to `ALL_SKILLS`
in `worldforge/content/classes.py` as well. Character saves store the class ID, so keep IDs stable.

Do not use comments in this JSON. For an override, copy the full class record:
mod records replace the entire class definition, not individual fields.
# Class selection summaries

Add a `summary` string to each class record. The character creator shows it
while a player hovers over that class. Subclass choices use their existing
`description` and the first feature summary as their hover text.

## Hover summaries

Add a `summary` string to each class record. The character creator displays it while the player hovers over that class. Subclass choices use their `description` plus the first feature summary.
