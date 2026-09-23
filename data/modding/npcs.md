# `npcs.json`

NPCs use actor-like records. Give every NPC a stable top-level ID; a scenario
uses this ID in each enemy spawn's `npc` field.

Useful fields:

- `name`, `avatar`, `controller`: display name, image path, and controller ID.
  Built-ins are `ai`, `player`, and `scripted`; unknown values fall back to the
  player controller.
- `max_hp`, `current_hp`, `abilities`, `level`: combat statistics.
- `weapon_prof`, `armor_prof`, `saves`, `skills`: the same shapes as actor data.
- `equipment`: slot-to-item objects. Templates need a `template_id`; inline
  legacy item values also work, but templates are easier to reuse.
- `active_weapon_set`: `melee` or `ranged`.
- `known_spells`, `known_abilities`, `conditions`, `active_effects`,
  `inventory`: arrays initialized on every combat snapshot.
- `x`, `y`: spawn position in arena pixels. The scenario spawn can override it.
- `perception.levels`: increasing DC/title entries. Names shown to players are
  chosen automatically using their passive Perception, without sight/range.

The gray-box AI attacks a conscious player with its selected weapon, moves
closer for melee, and ends its turn. It does not yet use spells, tactics,
cover, or healing. Set up a usable weapon and class proficiencies or the AI can
have no valid attack.
