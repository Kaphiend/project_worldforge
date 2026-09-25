# `scenarios.json`

Each top-level key is an area scenario ID. Add one scenario and one arena record
to make a new playable area, then add an `exits` record to an arena to connect
it to another scenario. The host preserves each area's living mobs, corpses,
and respawned roaming mobs while the party travels between areas.

- `name`, `description`, `objective`, `victory`: text shown to players.
- `arena`: exact ID from `arenas.json`.
- `player_spawns`: ordered array of `[x, y]` pixel positions. The host takes
  the first; joining player IDs use the following positions when a session
  starts. Provide up to eight positions for the current co-op limit.
- `enemies`: array of `{ "npc": "npc_id", "x": number, "y": number }`.
  `npc` must match `npcs.json`; coordinates are pixels, not feet. These are
  enemy positions in the shared world. Combat starts in place when a conscious
  player is within 20 feet edge-to-edge and has clear line of sight to a
  conscious enemy; the party is not moved to a separate battle stage.
- `mob_pool`: optional list of NPC IDs used for new roaming mobs after an
  encounter is won. An empty list disables roaming mob respawns in that area.
- `respawn_point`: optional `[x, y]` pixel location used when a character
  releases their spirit in an area without an inn bed.

A scenario is a set of references and placements, not an AI script. IDs in
`enemies` and `mob_pool` must match records in `npcs.json`.
