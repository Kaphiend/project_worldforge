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
- `ai.default` configures the built-in tactical controller for NPCs unless an
  NPC overrides an option in its own `ai` object. `target_policy` supports
  `nearest`, `weakest` (lowest current-HP ratio), `lowest_hp`, and
  `highest_threat` (highest level, then nearest). `close_when_out_of_range`
  makes ranged users move into their weapon's listed long range;
  `use_offhand_attacks` uses an available bonus action for a legal Light
  weapon follow-up; `heal_below_fraction` is the self-healing threshold; and
  `ability_priority` is an ordered list of ability IDs the actor already knows.
  Built-in tactics use only valid prepared/known actor options and the normal
  combat resolver. Unknown abilities are ignored.
- `gear.rarity_tiers` and `gear.rarity_weights`: weighted rarity roll for each
  generated equipped item. Elite rolls shift upward by `rarity_shift` tiers.
- `gear.attribute_count_by_rarity`: maximum number of attributes generated
onto one item. The generator stops when no eligible unused group remains.

Attribute eligibility, value ranges, effect records, and optional per-affix
weights live in `item_attributes.json`. NPC templates select the slots and
optional base-item pools. Every generated item stores its item level, rarity,
attribute IDs, and rolled values, then drops from the corpse with the same
instance ID.
