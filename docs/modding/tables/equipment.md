# `equipment.json`

Each top-level key is an item template ID. Actors carry unique item instances
that refer back to the template through `template_id`; edit the template to
change all instances' behavior. An item instance's `id` is unique and should
not be reused as the template ID.

## Slot and category fields

- `name`: player-facing item label.
- `category`: runtime behavior family: `weapon`, `shield`, armor categories
  (`light`, `medium`, `heavy`, `unarmored`), accessory/armor piece, or
  `consumable`.
- `slot`: default slot used when making an instance.
- `allowed_slots`: the exact legal equipment slots. Use the current canonical
  slots: `head`, `chest`, `hands`, `feet`, `belt`, `cape`, `ring1`, `ring2`,
  `amulet`, `main_hand`, `off_hand`, `ranged`; eligible one-handed ranged
  weapons can also occupy `ranged_offhand`.
- `hands_required`: `1`, `2`, or `"flexible"`. Two-handed weapons use a shared
  item instance in both hand slots; they cannot occupy both slots as separate
  items.
- `tags`: rules flags interpreted by code. Current examples include `2h`,
  `thrown`, `finesse`, `light`, `heavy`, `ammunition`, `loading`, and
  `focus-capable`. Unknown tags are inert.

## Weapon values

- `weapon_class` is checked against an actor's `weapon_prof`.
- `weapon_family` is mainly descriptive and used by projectile animation
  selection; current families include bow/crossbow.
- `damage_dice` is parsed by `worldforge/core/dice.py`, for example `1d6` or `2d6`.
- `damage_type` is written into combat output; resistance math is not built.
- `ranges.melee` is melee reach in feet. For ranged weapons, use `ranges.normal`
  and optional `long`; `thrown_normal` and `thrown_long` define thrown ranges.
  The current rule allows attempts beyond normal range with disadvantage.
- `damage_profiles` is currently used by the staff rule. The exact keys are
  `off_hand_empty` and `off_hand_occupied`.
- `ammo_type` and `ammo_policy` are currently descriptive; normal ammo is
  unlimited in this demo.
- A `thrown` tag makes **T** available for an explicit throw. Main attack **1**
  does not auto-throw when a target is beyond melee reach.

## Armor and consumables

Armor templates use `base_ac`; medium armor may also use
`dexterity_bonus_cap`. Shields give `ac_bonus`, currently fixed to +2 by
`worldforge/combat/rules.py` when a shield is in a hand slot.

Consumables need `category: "consumable"`, `consumable: true`, and an
`effect_id` that exists in `spells.json`. The UI uses the effect's resolver and
consumes one item after success. Set `stackable: true` and `max_stack` to let
matching template instances share one inventory row; otherwise each instance
stays separate. `healing_potion` and `revival_scroll` stack to 20. The inventory
Q/E quick slots bind to a stack's stable item ID and stay bound as its quantity
decreases, clearing when the last item is consumed.

Adding a new property is not enough to create a rule. Search `worldforge/combat/rules.py`,
`worldforge/actors/factory.py`, and `worldforge/combat/rules.py` for the field you intend to change.
