# `npcs.json`

NPCs use actor-like records. Give every NPC a stable top-level ID; a scenario
uses this ID in each enemy spawn's `npc` field.

Useful fields:

- `name`, `avatar`, `controller`: display name, image path, and controller ID.
  Built-ins are `ai`, `player`, and `scripted`; unknown values fall back to the
  player controller.
- `level`, `class_pool`: generated mobs use the template level and choose a
  class from this list (or the shared pool in `mob_generation.json`). Class
  priorities assign the template's six ability scores and class proficiencies.
- `elite_chance`: optional probability from 0 to 1. Elites receive the `elite`
  tag, a small level-bounded primary-stat increase, slightly more base HP,
  higher item level and a one-tier rarity shift. Gear rolls remain independent.
- `gear_slots`, `gear_pools`: slots to generate on each mob and optional lists
  of base item IDs per slot. Without a slot-specific pool, compatible items
  are selected from `equipment.json`; class proficiencies filter the choices.
  When `gear_slots` is omitted, the old `equipment` keys provide the slot list;
  generated mobs roll new base items for those slots.
- `max_hp`, `current_hp`, `abilities`, `level`: combat statistics.
- `weapon_prof`, `armor_prof`, `saves`, `skills`: the same shapes as actor data.
- `equipment`: slot-to-item objects. Templates need a `template_id`; inline
  legacy item values also work, but templates are easier to reuse.
- Defeated NPCs drop every item in `inventory` and every equipped item in
  `equipment`. Loot is one shared corpse container for the combatants; each
  item taken is removed for everyone. The corpse stays until looting ends,
  then despawns after three seconds. Put only the gear you intend to drop on
  the NPC; there is no separate random drop table or gold roll yet.
- `active_weapon_set`: `melee` or `ranged`.
- `known_spells`, `known_abilities`, `conditions`, `active_effects`,
  `inventory`: arrays initialized on every combat snapshot.
- `x`, `y`: spawn position in arena pixels. The scenario spawn can override it.
- `perception.levels`: increasing DC/title entries. Names shown to players are
  chosen automatically using their passive Perception, without sight/range.
  Elites add a higher-DC stage that reveals the `Elite` title prefix.

The gray-box AI attacks a conscious player with its selected weapon, moves
closer for melee, and ends its turn. It does not yet use spells, tactics,
cover, or healing. Set up a usable weapon and class proficiencies or the AI can
have no valid attack.
