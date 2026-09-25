# Included example mod: `data/mods/demo_slice/`

This mod is deliberately small and is the best working example to copy.

- `scenarios.json` defines the roadside clearing and forest path encounters,
  plus peaceful market and inn areas.
- `arenas.json` defines the connected 1600-by-1100-and-larger areas, the
  separate Market Square vendor and Town Inn bed, exits, and scenery.
- `npcs.json` defines `clearing_raider`, its stats, Orc avatar, gear, simple AI
  controller, and two Perception title tiers.

IDs must match across these files. For example, changing the arena's key
requires changing the scenario's `arena` value. Changing the NPC's key requires
changing the scenario enemy's `npc` value. `first_contact` remains the game
start area; connect any added scenarios with arena `exits`.
