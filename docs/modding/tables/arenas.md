# `arenas.json`

Each top-level key is an arena ID referenced by `scenarios.json`.

- `name`: label for reference.
- `bounds`: `{ "x", "y", "width", "height" }` in pixels. This is the world
  rectangle; the camera stays inside it and actors cannot leave it.
- `ground_color`, `edge_color`: RGB arrays such as `[64, 91, 67]`.
- `decorations`: visual-only records. Current renderer draws `kind: "rect"`
  with x/y/width/height/color. Decorations do not block players or sight.
- `obstacles`: x/y/width/height rectangles. These block movement and block
  line of sight for ranged attacks and spells requiring it.
- `exits`: optional area connections. Each record has `id`, `name`, x/y/width/
  height, `interaction_range_feet`, `destination_scenario`, and
  `destination_spawn: [x, y]`. Press `F` nearby and confirm to move the
  connected party to that scenario. `party_spawn_spacing` sets the distance
  between party members at the destination. Add a matching exit to the target
  arena if travel should work both ways. Exits are rendered and do not block
  movement.
- `inn_beds`: optional gray-box bed rectangles with `id`, `name`, x/y/width/
  height, and `interaction_range_feet`. Beds block movement, are safe spawn
  exclusions. Each party member presses `F` nearby and confirms a 10-gold
  overnight stay; the rest begins after all connected members check in.
- `camp_beds`: beds in the arena selected by the active campaign's
  `safe_camp_arena`. Each has `id`, `name`,
  x/y/width/height, `spawn_x`, `spawn_y`, and `interaction_range_feet`. Every
  party member is assigned a bedroll and must press `F` nearby before the
  party rests. The campaign validator checks that this arena has enough
  bedrolls for its configured party limit.
- `trainers`: optional interaction rectangles with `id`, `name`, x/y/width/
  height, and `interaction_range_feet`. They block movement and open the
  data-driven class purchase screen with `F`. `xp_purchase_cost` is authored
  on each spell or ability, rather than on the trainer.
- `vendors`: optional interaction rectangles with `id`, `name`, x/y/width/
  height, and `interaction_range_feet`. `stock` is a list of `{ "id",
  "item_id", "price" }` records for unlimited purchases. The Market Square vendor
  sells healing potions and revival scrolls for 10 gold each. Any inventory
  item can be sold for 10 gold; each character's sold items stay in their
  buyback list for the current map session and can be bought back for 10 gold.
- `inn_beds[].respawn_x` / `respawn_y`: optional pixel coordinates used when a
  downed character releases their spirit and returns to the inn.

Keep all obstacle rectangles inside bounds. Avoid placing an obstacle over a
spawn point. A rectangle's visible decoration does not become solid unless you
also add an obstacle record.

To add an area, define its arena and scenario in `data/mods/<your-mod>/`, add
its starting enemy records and optional `mob_pool`, then connect it with an
exit in an existing arena. No Python changes are needed for map geometry,
enemy placements, exits, or supported interactions.
