# `scenarios.json`

Each top-level key is a scenario ID. `game.py` chooses the default ID in
`DEFAULT_SCENARIO`; selecting a different scenario in the UI is not built yet.

- `name`, `description`, `objective`, `victory`: text shown to players.
- `arena`: exact ID from `arenas.json`.
- `player_spawns`: ordered array of `[x, y]` pixel positions. The host takes
  the first; joining player IDs use the following positions. `main.py` uses
  these when the game session starts. Provide up to eight positions for the
  current co-op limit.
- `enemies`: array of `{ "npc": "npc_id", "x": number, "y": number }`.
  `npc` must match `npcs.json`; coordinates are pixels, not feet. These are
  enemy positions in the shared world. Combat starts in place when a conscious
  player is within 20 feet edge-to-edge and has clear line of sight to a
  conscious enemy; the party is not moved to a separate battle stage.

A scenario is a set of references and placements, not an AI script. Add a new
scenario together with its NPC and arena records in your mod folder.
