# Progression and rest rules

## Character XP

`progression.py` owns the current cumulative XP threshold table and helpers for
reading class levels, computing class-based pool capacities, and determining
the level earned from total XP. Class level entries are authoritative for
multiclass pool contributions; the legacy `char_class` plus `level` fields are
used when a save has no `classes` list.

Combat victory awards 10 XP once per combat to every actor on the player team.
The encounter stores an `xp_awarded` guard so another action or host frame
cannot pay twice. XP awards update `xp_total` and `xp_earned_by_level` using the
actor's current level. This code does not apply a new level automatically.

## Pool curves

See [`classes.md`](classes.md) for `spell_points_by_level` and
`class_resources`. Curves may be arrays indexed by class level (index zero is
unused) or objects keyed by level. Missing later array entries repeat the last
entry, so mods should include values through their intended maximum level.
Multiclass spell pool capacity is the sum of each class's curve at that class's
own level. Special class pools stay separate from spell points.

The current baseline gives caster classes one spell point per class level.
Known spells still come from the actor's existing `known_spells`; pool
progression does not grant spells. Spell effects are not yet scaled from
character level.

## Trainer multiclass costs

`progression.trainer_xp_cost(current_class_level)` returns the XP gap for the
next class level on the shared fifth-edition threshold curve. Each class is
independently capped at level 20; the sum of class levels has no cap. This is a
cost rule only: a trainer interaction, purchase ledger, and user interface have
not been implemented yet. Do not subtract XP or advance a class level from a
mod without an authoritative trainer transaction.

## Repeatable encounter loop

After a victory, the host retains the defeated NPC as a corpse for 30 seconds
and creates a new NPC through `factory.create_npc_instance`. The factory
selects from the loaded `npcs.json` templates, clones its equipment with fresh
item IDs, and places it at a random non-obstructed map position away from
players and living mobs. Add NPC template records to `npcs.json` or a mod's
`npcs.json` to expand the spawn variety. Since loot is not implemented yet,
the corpse timer starts at death; move that start point to loot completion when
the loot flow is added.

## Rest cost rules

`resting.py` contains the cost and recovery functions. Press `Z` to request an
outdoor rest; the host validates each connected character and rejects the
request during combat. Outdoor rests require a nearest-enemy distance strictly
greater than 100 feet, cost 1% of unspent XP at first, increase one percentage
point per consecutive outdoor rest up to 5%, and have a 1 XP minimum. A
character with no unspent XP cannot rest outdoors. Press `X` within the
configured range of an `inn_beds` entry to rest at the inn for 10 gold; this
resets the outdoor streak. Both types refill spell and configured class pools.

The current action does not move a party to a camp stage, heal HP, clear
conditions, or apply level-ups. Those behaviors need an explicit game-flow
implementation. Rest XP costs
are recorded in `xp_rest_spent_by_level`; the rate is based on earned minus
spent XP ledgers, with `xp_total` as a fallback for older records without an
earned ledger.
