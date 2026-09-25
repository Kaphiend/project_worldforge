# `experience.json`

`challenge_rating_xp` maps a monster's Challenge Rating string to its SRD XP
value. New CRs or campaign-specific reward tables can be added in a mod by
overriding this record. Values are the total XP for defeating one creature,
before the party split.

NPC records may set either `xp_reward` (an explicit override) or
`challenge_rating` (looked up in this table). `xp_reward` takes precedence.
The engine sums XP for defeated enemies in the encounter, then divides the
award evenly among player participants, distributing any remainder one point
at a time in stable player order.

The campaign rule `xp_debug_multiplier` defaults to `1.0`, the normal ruleset
value. The demo campaign sets it higher to speed up progression while testing;
set it back to `1.0` for standard CR-based awards. Do not put a flat victory XP
amount in campaign rules.
