# `abilities.json`

Abilities use the same supported `effects` vocabulary described in
[`spells.md`](spells.md), but are granted through the actor's `known_abilities`
list. Each top-level key is an ability ID.

- `classes`: class IDs that can learn it.
- `action_cost`: current caller expects values such as `action` or
  `bonus_action`; game code spends the corresponding turn budget.
- `uses_per_combat`: optional maximum uses per combat; defaults to `1`. Set to
  `null` for a pool-limited ability. Pair that with `resource_cost`, an object
  containing `class_id`, `resource_id`, and positive integer `amount`; the
  matching pool must be defined by that class's `class_resources` entry. Pool
  values are spent only after the ability resolves successfully.
- `targeting`: optional. Without it, the ability targets its user. Current
  targeted abilities use `mode: "one_target"` and `range_feet`.
- `prerequisite_class_level` and `acquisition`: set the tier and how the
  option is learned. `acquisition: "trainer_purchase"` displays the ability
  at the map trainer; `xp_purchase_cost` is its one-time XP price. The shared
  character XP ceiling and that class's sequential purchase chain gate access.
- `effects`: array of supported effect records. For a status effect, use
  `{ "kind": "condition", "condition_id": "off_balance" }` and make sure
  that condition exists.

Abilities do not become usable just because an ID is in JSON: include the class
in `classes`, and keep any new effect kinds inside the resolver's supported
list or add Python code first.
