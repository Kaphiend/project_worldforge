# `conditions.json`

Each key is a condition ID used by spell/ability effects and stored on actors.
A condition record contains `name`, `description`, `duration`,
`reapplication`, `primitives`, and `removal`.

- `duration.turns`: number of affected turns, or `null` for no automatic expiry.
- `duration.tick`: currently descriptive; runtime checks phase/timing strings
  on primitives.
- `reapplication: "refresh_duration"`: refreshes the same condition rather
  than adding duplicates. For `attack_disadvantage`, its use count refreshes too.
- `primitives`: runtime only executes `damage_over_time` at start of turn.
  `attack_disadvantage` is tracked and consumed by attacks. `movement_set` is
  interpreted by `worldforge/app/actions.py` specifically for `bound_in_briar`.
- `removal`: documentation labels; not every listed removal method is wired.

Example recurring damage:

```json
"burning": {
  "name": "Burning",
  "description": "Takes fire damage each turn.",
  "duration": {"turns": 2, "tick": "start_of_affected_turn"},
  "reapplication": "refresh_duration",
  "primitives": [{"kind":"damage_over_time", "formula":"1d4", "damage_type":"fire", "timing":"start_of_affected_turn"}],
  "removal": ["duration_expired"]
}
```

Adding a new primitive needs a corresponding implementation in
`worldforge/combat/conditions.py` or `worldforge/app/actions.py`.
