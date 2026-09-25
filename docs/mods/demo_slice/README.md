# Demo slice campaign notes

The `campaign.json` manifest makes this the default playable sample campaign.
It demonstrates a connected group of scenarios, combat, safe camping, an inn,
vendors, training, loot, and personal storage.

1. `scenarios.json` defines the encounter ID `first_contact`.
2. Its `arena` value points to `roadside_clearing` in `arenas.json`.
3. Its enemy `npc` value points to `clearing_raider` in `npcs.json`.
4. The scenario also controls the player spawn ring, objective, and victory text.
5. The arena bounds are pixels. Rectangles in `obstacles` block movement and
   line of sight; rectangles in `decorations` are only visual.
6. NPC fields use the normal actor format. Its perception DCs drive the visible
   nameplate. `controller: "ai"` selects the intentionally simple pursuit AI.

Copy the relevant content tables into a mod folder and add a `campaign.json`
manifest to make a separate campaign. Use unique IDs, then list the scenarios,
starting scenario, safe camp, map routes, party cap, enabled systems, and rules
in the manifest. Select it with `WORLDFORGE_CAMPAIGN=<folder>` and run
`python -m worldforge.content.validate_campaign`. See
[`../../modding/campaigns.md`](../../modding/campaigns.md) for the manifest
format and validator coverage.
