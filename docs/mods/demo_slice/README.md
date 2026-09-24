# Demo slice mod notes

The matching data folder is loaded automatically; this document describes
the smallest complete example of an encounter.

1. `scenarios.json` defines the encounter ID `first_contact`.
2. Its `arena` value points to `roadside_clearing` in `arenas.json`.
3. Its enemy `npc` value points to `clearing_raider` in `npcs.json`.
4. The scenario also controls the player spawn ring, objective, and victory text.
5. The arena bounds are pixels. Rectangles in `obstacles` block movement and
   line of sight; rectangles in `decorations` are only visual.
6. NPC fields use the normal actor format. Its perception DCs drive the visible
   nameplate. `controller: "ai"` selects the intentionally simple pursuit AI.

Copy all three JSON files into a new mod folder to make a separate encounter.
Use new IDs and update every reference that points to them. See
[`../../modding/demo_slice.md`](../../modding/tables/demo_slice.md) for more context.
