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
- `spell_points_by_level`: optional level-indexed curve for this class's
  contribution to the character's shared spell-point pool. Index `0` is unused;
  index `N` is the contribution at class level `N`. Multiclass characters add
  the values for each class at its own class level. The demo baseline is one
  point per caster class level; tune the numbers directly for balance.
- `class_resources`: optional named pools separate from spell points, such as
  `lay_on_hands`. Each entry may define `name`, `max_by_level` (same indexing
  rule), and `recovery` (currently descriptive; defaults to `rest`). Runtime
  saves store current amounts by `class_id.resource_id`. Abilities can spend
  these pools with their `resource_cost` field. Add class data only when the
  rules and recovery cadence are defined; this project does not assume
  fifth-edition values for special pools.
- `progression`: map of class levels to arrays of feature entries. Entries
  usually have `id`, `name`, `summary`, and prerequisite data. Class features
  are purchased from the trainer with XP; class level alone grants none.
  `xp_purchase_cost` sets the price and defaults to `10`. Built-in selectable
  skill lists and subclass choices follow SRD 5.2.1; skills and features still
  require XP purchases. Former Worldforge subclasses remain nonselectable for
  old saves. Hide, Cunning Action's bonus-action Hide, Sneak Attack, and
  `extra_weapon_attack` currently have combat behavior; most other effects are
  descriptive until their resolver is implemented.
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
