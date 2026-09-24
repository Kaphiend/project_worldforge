# Included example mod: `data/mods/demo_slice/`

This mod is deliberately small and is the best working example to copy.

- `scenarios.json` defines `first_contact`, the current default scenario. It
  refers to arena `roadside_clearing` and NPC `clearing_raider`.
- `arenas.json` defines the 1200-by-800 pixel play area, decorative ground
  rectangles, and solid obstacle rectangles.
- `npcs.json` defines `clearing_raider`, its stats, Orc avatar, gear, simple AI
  controller, and two Perception title tiers.

IDs must match across all three files. For example, changing the arena's key
requires changing the scenario's `arena` value. Changing the NPC's key requires
changing the scenario enemy's `npc` value. Keep `first_contact` intact unless
also changing `worldforge/app/encounters.py:DEFAULT_SCENARIO` or adding scenario selection.
