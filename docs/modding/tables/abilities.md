# `abilities.json`

Abilities use the same supported `effects` vocabulary described in
[`spells.md`](spells.md), but are granted through the actor's `known_abilities`
list. Each top-level key is an ability ID.

The built-in table now contains starter combat actions for Barbarian, Fighter,
Monk, and Rogue. These records are learned at character creation through each
class's `starting_abilities`; they are added to the first action bar. New
abilities may be trainer purchases or starter actions, but their runtime effect
must be supported before the record is usable.

- `classes`: class IDs that can learn it.
- `action_cost`: `action`, `bonus_action`, or `free`; the first two spend that
  turn budget. Free actions must be bounded by a resource or their effect.
- `uses_per_combat`: optional maximum uses per combat; defaults to `1`. Set to
  `null` for a pool-limited ability. Pair that with `resource_cost`, an object
  containing `class_id`, `resource_id`, and positive integer `amount`; the
  matching pool must be defined by that class's `class_resources` entry. Pool
  values are spent only after the ability resolves successfully.
- `targeting`: optional. Without it, the ability targets its user. Current
  targeted abilities use `mode: "one_target"` and `range_feet`. Add
  `target_team: "enemies"` to reject ally targets.
- `requires_action_spent`: require the actor to have already used its action;
  used by Action Surge and Flurry of Blows.
- `requires_not_heavy_armor`: reject use while heavy armor is equipped.
- `attack_sequence`: runs the configured number of attacks after spending the
  listed action/resource; currently used for Monk Flurry with unarmed strikes.
- `unique_active`: prevent applying another copy while this ability's timed
  effect remains active.
- `prerequisite_class_level` and `acquisition`: set the tier and how the
  option is learned. `acquisition: "trainer_purchase"` displays the ability
  at the map trainer; `xp_purchase_cost` is its one-time XP price. The shared
  character XP ceiling and that class's sequential purchase chain gate access.
- `effects`: array of supported effect records. For a status effect, use
  `{ "kind": "condition", "condition_id": "off_balance" }` and make sure
  that condition exists.

Supported effect kinds now include timed damage resistance, weapon damage
bonuses, attack advantage/disadvantage, healing with a class-level bonus, and
restoring the current action. Abilities do not become usable just because an ID
is in JSON: include the class in `classes`, and add code for any new effect
kind before relying on it.
