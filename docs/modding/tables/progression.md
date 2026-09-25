# Progression, trainer purchases, rests, and death

## XP and level eligibility

`worldforge/core/progression.py` owns the cumulative XP threshold table and computes the
character's qualified level from unspent XP (earned XP minus trainer purchases
and outdoor-rest costs). The current wallet is also stored as `xp_total`.
Combat victory awards 10 XP to each player participant, once per encounter.

Character levels 4, 8, 12, 16, and 20 each grant two attribute points. Each
point raises one stored ability score by one. Spending is host-validated from
the character sheet. Stored scores may exceed 30, but ability modifiers and
other calculations use a maximum effective score of 30. These points are
based on gross earned XP, so spending XP or resting does not remove points
already earned.

`data/progression.json` sets the first additional-class unlock fee and its
multiplier. Defaults are 500 XP for the second class, then a threefold increase
for each later class (1,500 XP for the third, 4,500 XP for the fourth). Unlock
the class in its trainer tab before purchasing its options. Acquired classes
are stored in the actor's ordered `classes` list, with the original class first.

The trainer charges the per-option `xp_purchase_cost` stored on each
trainer-purchasable spell or ability, multiplied by class order: 1x for the
original class, 2x for the second, 3x for the third, and so on. Both the unlock
fee and purchase multiplier are host-validated. A purchase lowers unspent XP
immediately and can lower the character's qualified level. Owned content remains in
`known_spells` / `known_abilities`; class ownership is also recorded in
`class_spell_purchases` / `class_ability_purchases`.

The shared qualified level is the maximum tier purchasable in every class. Each
class has an independent sequential tier chain: own at least one spell at a
tier to unlock the next tier in that class. A class with no purchase spells at
a tier can use a trainer-purchased ability at that tier as the chain key.
Abilities and spells require the current shared level ceiling and their class
frontier. Previously purchased content stays usable after XP loss. Newly
purchased spells enter the spellbook unprepared; each class has its own
preparation limit of class level plus its casting ability modifier, with
cantrips excluded.

Legacy saves without ownership ledgers retain their existing known trainer
content and migrate it into the matching class ownership maps. Quick-start
characters start with 900 XP and level 3. Attribute point milestones use
levels 4, 8, 12, 16, and 20; points are spent from the character sheet.

## Class resource curves

See [`classes.md`](classes.md) for `spell_points_by_level` and
`class_resources`. Curves may be arrays indexed by class level (index zero is
unused) or objects keyed by level. The shared spell pool is the sum of each
class's curve at that class's currently unlocked class tier. Special pools
remain separate from spell points.

## Trainer map content

A trainer entry is defined in an arena's `trainers` array. Use `F` within its
`interaction_range_feet` to open class tabs. The screen lists trainer-purchasable
spells and abilities from the content tables, including their scaled XP prices.
A locked class must be unlocked for the displayed fee first. The game validates
class unlocks, price multipliers, current XP, and sequential tier access when
it processes each purchase.

Tune multiclass costs in `data/progression.json`:

- `first_additional_class_xp_cost`: one-time price to unlock the second class.
- `class_unlock_xp_multiplier`: multiplier applied for each already unlocked
  additional class; `3` gives 500, 1,500, 4,500, and so on.
- `first_additional_class_purchase_multiplier`: price multiplier for the
  second class's options; `2` means twice the listed `xp_purchase_cost`.
- `subsequent_purchase_multiplier_step`: amount added to the option multiplier
  for each later class; `1` gives 2x, 3x, 4x, etc.

## Death and revival

When downed, a player can wait for another player to revive them or press `R`
to release their spirit. Release returns the character to the inn's configured
`respawn_x` / `respawn_y` (or just beyond the bed if omitted), restores 1 HP,
and costs 10% of current unspent XP. Penalties round up and cost at least 1 XP
when any XP remains. A character revived by another player loses 2% of their
unspent XP with the same rounding rule. Releasing removes that character from
the current fight; they can join a later fight.

## Rest cost rules

`resting.py` contains the rest costs and resource recovery. Press `Z` to travel
to safe camp; every party member must be more than 100 feet from every living
enemy and able to pay before travel begins. At camp, each member checks in at
their assigned bedroll. The individual XP cost begins at 1% of unspent XP,
rises by one percentage point per consecutive outdoor rest up to 5%, and has a
1 XP minimum. A character with no unspent XP cannot camp. At an inn, each
party member interacts with the bed and pays 10 gold for the night. Both types
refill spell and configured class pools only after every connected member
checks in. Inn rest resets the outdoor streak.

Health recovery and condition removal remain future work. The current demo
shares rest readiness and combat state among connected players.
