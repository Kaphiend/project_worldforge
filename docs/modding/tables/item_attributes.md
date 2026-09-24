# `item_attributes.json`

Each top-level key defines one attribute that mob gear generation can roll
onto an item instance. The starter pool is deliberately small:

- `double_weapon_dice`: doubles a weapon's damage dice, available from item
  level 5.
- `weapon_damage_bonus`: adds 1–3 damage to weapon hits.
- `weapon_attack_bonus`: adds +1–2 to weapon attack rolls.
- `armor_class_bonus`: adds 1–3 AC to defensive equipment.
- `maximum_hp_bonus`: adds 2–8 maximum HP while the item is equipped.
- `saving_throw_bonus`: adds +1–2 to saving throws while equipped.

Attribute records support these fields:

- `name`, `description`: display name and player-facing explanation.
- `group`: uniqueness key. A generated item must not receive two attributes
  from the same group.
- `allowed_categories`, `allowed_slots`: both filters must match the base
  item's template and equipped slot.
- `min_item_level`, `max_item_level`: inclusive level range for generation.
- `value_range`: optional inclusive integer range rolled for this attribute.
- `effect`: effect kind and any fixed parameters, such as the damage-dice
  multiplier.
- `weight`: optional relative pick weight within the eligible attribute pool;
  omitted weights default to 1.

Generated item instances store `rolled_attributes` as a map from attribute ID
to its rolled value. Combat applies weapon damage dice multipliers before
critical-hit doubling, flat weapon damage after the dice roll, and equipped
bonuses to AC, max HP, and saving throws. Distinct equipment items stack;
duplicate slot references to the same item instance count once. A mob's item
instances keep their generated IDs and attributes when dropped on death.
