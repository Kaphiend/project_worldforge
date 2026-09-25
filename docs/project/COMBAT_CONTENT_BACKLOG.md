# Combat content resolution backlog

This file separates content that currently has a runtime effect from content
that is only described in data. SRD 5.2.1 is the reference for recognizable
class roles; Worldforge can keep its own resource, XP, and turn-balance rules.
See [the SRD baseline and attribution](SRD-5.2.1.md).

## Implemented spell actions

The following entries in `data/spells.json` currently resolve in combat:

- Bard: Vicious Mockery, Healing Word.
- Cleric: Sacred Flame, Healing Word, Shield of Faith.
- Druid: Produce Flame, Entangle.
- Paladin: Cure Wounds, Divine Favor.
- Ranger: Cure Wounds, Entangle.
- Sorcerer: Fire Bolt, Magic Missile.
- Warlock: Eldritch Blast.
- Wizard: Fire Bolt, Magic Missile.
- Item effects: Healing Potion and Revival Scroll.

These are starter actions, not complete spell lists. Cantrip damage scaling,
concentration and interruption, higher-level casting, square/cone/line areas,
repeat saves, and several SRD conditions are still absent. Entangle currently
roots a failed target by setting movement to zero; it does not apply the full
Restrained condition or allow repeat saves. Produce Flame is implemented as an
attack and does not model holding the flame for light. Magic Missile is
resolved as one combined hit against one selected target.

## Spell resolutions to add

Prioritize these shared mechanics before adding many more spell records:

1. **Attack modifiers and conditions:** advantage/disadvantage on attacks,
   saving throws, and checks; prone, frightened, charmed, poisoned, blinded,
   restrained, and stunned; expiry and repeat-save rules.
2. **Ongoing spell state:** concentration ownership, interruption checks,
   replacement of a caster's current concentration, and early termination.
3. **Spell geometry:** square, cone, line, and sphere/circle placement with
   per-target saves and half damage where specified.
4. **Scaling and spell resources:** character-level cantrip scaling, upcasting,
   temporary hit points, and effects that create consumable items.
5. **Reactions:** defensive spells such as Shield need a response window when
   an attack hits, before damage is applied.

Useful next SRD spell actions, grouped by class:

- **Bard:** Dissonant Whispers (save, psychic damage, forced movement), Faerie
  Fire (area save and advantage while marked), and Bardic Inspiration (an
  ally's later d20 roll bonus).
- **Cleric:** Bless (concentration and repeated d4 roll bonuses), Guiding Bolt
  (spell attack plus a one-use advantage mark), and Sanctuary (attack-targeting
  restriction).
- **Druid:** Goodberry (create persistent consumables), Thunderwave (cube and
  forced movement), and Faerie Fire.
- **Paladin:** Divine Smite (trigger immediately after a weapon hit and spend
  spell points), plus Lay on Hands as a class resource rather than a spell.
- **Ranger:** Hunter's Mark (persistent target mark and per-hit damage),
  Goodberry, and Longstrider (timed movement bonus).
- **Sorcerer:** Shield (reaction), Burning Hands (cone save and half damage),
  and Metamagic (spell modification and sorcery-point spend).
- **Warlock:** Hex (concentration, target mark, and repeated bonus damage),
  Armor of Agathys (temporary HP and retaliation), and Eldritch Blast beam
  scaling.
- **Wizard:** Shield, Sleep (HP-based multi-target effect), Grease (area and
  prone saves), and familiar/summoning actions.

## Class abilities still needing executable resolutions

`data/abilities.json` now has executable starter actions for the four melee
classes. The class progression entries in `data/classes.json` also include
Worldforge feature drafts and SRD-inspired feature summaries; a summary alone
does not grant behavior. Remaining melee work:

- **Barbarian:** Rage, Reckless Attack, and a level-scaled Rage resource resolve.
  Danger Sense (Dexterity save advantage), rage extension/early ending, and
  higher-level damage/uses progression still need playtest and fuller rules.
- **Fighter:** Second Wind and Action Surge resolve with class-level resource
  pools. Level 5 Extra Attack, Tactical Shift, Champion critical range, and
  Archery, Defense, Dueling, Great Weapon Fighting, and Two-Weapon Fighting
  resolve. Protection remains a data choice without its reaction prompt and
  attack-imposition flow. Tactical Mind, Indomitable, higher-level Champion
  features, and general ability-check resolution remain queued. Fighter
  features still use Worldforge's XP trainer acquisition policy.
- **Monk:** Focus points, Flurry of Blows, Patient Defense, and level-based
  unarmed damage resolve. Step of the Wind, Deflect Attacks (reaction),
  Patient Defense's Dexterity-save advantage, Stunning Strike, and several
  later-level Focus options remain.
- **Rogue:** Sneak Attack scales by Rogue level and accepts advantage from
  Steady Aim as well as an adjacent ally or an unseen attack. Cunning Action
  Hide, Dash, and Disengage are wired; movement leaving melee reach triggers
  opportunity attacks unless the mover is disengaged. Reactions reset at each
  creature's turn. Uncanny Dodge automatically spends the target's reaction to
  halve a visible attack's damage; a player-choice reaction window remains a
  UI/networking improvement. Steady Aim, Trip/Poison/Withdraw Cunning Strike,
  Expertise selection, Evasion, Reliable Talent, Slippery Mind, Elusive, and
  Weapon Mastery choices/resolution for the supported weapon set (Nick, Push,
  Graze, Cleave, Sap, Slow, Topple, Vex) now resolve for characters with Weapon
  Mastery. Light-property off-hand attacks use a Bonus Action, and Nick moves
  that attack into the Attack action once per turn. Cleave automatically picks
  the nearest valid second target because the UI has no second-target prompt.
  Cunning Strike choices are hotbar abilities that queue a rider for the next
  eligible Sneak Attack. Finish Stroke of Luck, the remaining Cunning Strike
  riders and a player-choice reaction window. Uncanny Dodge currently triggers
  automatically on the first visible damaging hit when a reaction is ready.
  Opportunity attacks are checked from the movement start and final position;
  path crossings that leave and re-enter reach are not yet sampled. Reliable
  Talent and Expertise apply to skill checks currently implemented (Hide and
  Fast Hands); the game does not yet expose a general ability-check action.
  Fighter, Ranger, and Paladin Weapon Mastery choices are available from their
  trainer class features. Fighter, Ranger, and Paladin Fighting Style choices
  include Two-Weapon Fighting. The trainer has separate Features, Spells,
  Abilities, Skills, Choices, and Ability Scores tabs.

After the melee core, add these class actions:

- **Bard:** Bardic Inspiration uses, scaling, and later roll consumption;
  subclass inspiration effects.
- **Cleric:** Channel Divinity uses, Turn Undead, Divine Spark, and domain
  actions.
- **Druid:** Wild Shape forms and stat replacement, form duration, and Circle
  actions.
- **Paladin:** Lay on Hands pool, Divine Smite hit trigger, Channel Divinity,
  auras, and cleansing effects.
- **Ranger:** Hunter's Mark, Favored Enemy uses, weapon/fighting style support,
  and subclass actions.
- **Sorcerer:** Sorcery Points, Metamagic options, and Innate Sorcery duration.
- **Warlock:** Pact Magic recovery, invocations that modify attacks/spells, and
  subclass actions.
- **Wizard:** Arcane Recovery, spellbook preparation limits, and subclass
  actions.

## Shared engine hooks to build

- Resource pools now scale by class level and recover on the game's current
  rest flow. Short-rest versus long-rest recovery remains undifferentiated.
- Make ability actions able to add/restore an action budget, trigger an attack
  sequence, or consume the immediately preceding attack result. Action
  restoration and the Monk's two-hit sequence are implemented; hit-triggered
  abilities such as Divine Smite remain.
- Add more typed temporary effects for advantage/disadvantage, attack
  modifiers, temporary HP, forced movement, and reaction windows. Rage
  resistance and the current limited advantage effects are implemented.
- Define stacking/replacement behavior for repeated marks, blessings, and
  concentration effects; show remaining duration and resource use in the combat
  log and HUD.
