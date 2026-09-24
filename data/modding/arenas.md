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
- `inn_beds`: optional gray-box bed rectangles with `id`, `name`, x/y/width/
  height, and `interaction_range_feet`. Beds block movement, are safe spawn
  exclusions, and enable the `F` inn-rest confirmation when a player is in range.
  Press `F` nearby to ask before paying 10 gold and refilling spell and class
  resource pools.
- `trainers`: optional interaction rectangles with `id`, `name`, x/y/width/
  height, and `interaction_range_feet`. They block movement and open the
  data-driven class purchase screen with `F`. `xp_purchase_cost` is authored
  on each spell or ability, rather than on the trainer.
- `inn_beds[].respawn_x` / `respawn_y`: optional pixel coordinates used when a
  downed character releases their spirit and returns to the inn.

Keep all obstacle rectangles inside bounds. Avoid placing an obstacle over a
spawn point. A rectangle's visible decoration does not become solid unless you
also add an obstacle record.
