# `races.json`

Each top-level key is an ancestry ID. The creation screen lists records unless
`selectable` is explicitly `false`.

- `bonuses`: reference data keyed by ability ID (or `all`). It is shown/stored
  as race data, but the game does not automatically add these bonuses to rolled
  ability scores yet.
- `size`: descriptive text/value. Runtime speed logic does not use size.
- `speed`: movement speed in feet, read by combat movement. Use a number.
- `traits`: list of identifiers for future interpretation. Arbitrary new trait
  names are stored but have no behavior until Python supports them.
- `subraces`: map from subrace ID to a record with optional `bonuses` and
  `traits`. If this object is present, character creation requires a subrace.
- `half_breed: true`: sends creation to the two-parent selection stage.
  `parent_count` documents the count; current flow specifically asks for two.
- `selectable: false`: hides this ancestry in creation (useful for a template).

The special ID `half-breed` is also used in `combat.py` for parent-speed
handling. If you rename that ID, update Python. Parent speed is currently the
shared speed when both parents match, otherwise 30 feet.

Example subrace:

```json
"river": { "bonuses": {"dexterity": 1}, "traits": ["river_lore"] }
```

New bonuses/traits are reference data, not automatic character math.
