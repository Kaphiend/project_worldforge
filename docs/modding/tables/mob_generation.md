# `mob_generation.json`

This table controls generated mob classes, stealth tuning, and gear:

- `class_pool`: classes eligible for a generated mob. An NPC template can
  narrow this with its own `class_pool`.
- `ability_priorities`: ability order used to assign the NPC template's scores
  from highest to lowest for each generated class. Quick-start characters use
  the same class priorities when assigning their rolled scores.
- `elite`: primary and secondary score increases, level-based score cap, base
  HP multiplier, item-level bonus, rarity shift, and elite-title Perception DC.
- `stealth.hide_dc` sets the minimum total for the combat Hide action;
  `stealth.exploration_speed_multiplier` sets the movement factor while Sneaking.
- `gear.rarity_tiers` and `gear.rarity_weights`: weighted rarity roll for each
  generated equipped item. Elite rolls shift upward by `rarity_shift` tiers.
- `gear.attribute_count_by_rarity`: maximum number of attributes generated
  onto one item. The generator stops when no eligible unused group remains.

Attribute eligibility, value ranges, effect records, and optional per-affix
weights live in `item_attributes.json`. NPC templates select the slots and
optional base-item pools. Every generated item stores its item level, rarity,
attribute IDs, and rolled values, then drops from the corpse with the same
instance ID.
