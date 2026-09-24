# Progression, trainer purchases, rests, and death

## XP and level eligibility

`progression.py` owns the cumulative XP threshold table and computes the
character's qualified level from unspent XP (earned XP minus trainer purchases
and outdoor-rest costs). The current wallet is also stored as `xp_total`.
Combat victory awards 10 XP to each player participant, once per encounter.

The trainer charges the per-option `xp_purchase_cost` stored on each
trainer-purchasable spell or ability. A purchase lowers unspent XP immediately
and can lower the character's qualified level. Owned content remains in
`known_spells` / `known_abilities`; class ownership is also recorded in
`class_spell_purchases` / `class_ability_purchases`.

The shared qualified level is the maximum tier purchasable in every class. Each
class has an independent sequential tier chain: own at least one spell at a
tier to unlock the next tier in that class. A class with no purchase spells at
a tier can use a trainer-purchased ability at that tier as the chain key.
Abilities and spells require the current shared level ceiling and their class
frontier. Previously purchased content stays usable after XP loss. Newly
purchased spells are added to the prepared list.

Legacy saves without ownership ledgers retain their existing known trainer
content and migrate it into the matching class ownership maps. Quick-start
characters start with 900 XP and level 3. Feat choices at levels 4, 8, 12, 16,
and 19 remain placeholders; the trainer does not grant them.

## Class resource curves

See [`classes.md`](classes.md) for `spell_points_by_level` and
`class_resources`. Curves may be arrays indexed by class level (index zero is
unused) or objects keyed by level. The shared spell pool is the sum of each
class's curve at that class's currently unlocked class tier. Special pools
remain separate from spell points.

## Trainer map content

A trainer entry is defined in an arena's `trainers` array. Use `F` within its
`interaction_range_feet` to open class tabs. The screen lists trainer-purchasable
spells and abilities from the content tables, including their per-item XP
prices. The game validates class membership, price, current XP, and sequential
tier access when it processes each purchase.

## Death and revival

When downed, a player can wait for another player to revive them or press `R`
to release their spirit. Release returns the character to the inn's configured
`respawn_x` / `respawn_y` (or just beyond the bed if omitted), restores 1 HP,
and costs 10% of current unspent XP. Penalties round up and cost at least 1 XP
when any XP remains. A character revived by another player loses 2% of their
unspent XP with the same rounding rule. Releasing removes that character from
the current fight; they can join a later fight.

## Rest cost rules

`resting.py` contains the rest costs and resource recovery. Press `Z` to request
an outdoor rest; the host requires the nearest enemy to be more than 100 feet
away. The cost begins at 1% of unspent XP, rises by one percentage point per
consecutive outdoor rest up to 5%, and has a 1 XP minimum. A character with no
unspent XP cannot rest outdoors. Press `F` near an inn bed to confirm an inn
rest for 10 gold; this resets the outdoor streak. Both types refill spell and
configured class pools. Inn rest is available without XP if the character has
the gold.

Health recovery, condition removal, a party-ready flow, camp-stage travel, and
separate concurrent party combats remain future work. The current demo shares
one combat state among connected players.
