# Worldforge Design and Roadmap

This document describes the current playable slice and tracks the work still needed to grow it. It is written for the project owner and future modders. The code and JSON data are the implementation; where this document marks a system as partial or open, the details below are a roadmap rather than a claim that the feature already works.

## Status key

- `[x]` Implemented in the current slice.
- `[~]` Partly implemented, stubbed, or awaiting broader content.
- `[ ]` Not implemented yet.
- `[?]` Needs a design decision before implementation.

## Product direction

Worldforge is a moddable, data-driven, top-down co-op RPG. A session supports up to eight connected players who share the world and combat encounter. The immediate target is a gray-box demo slice: create characters, enter a small area together, encounter mobs, and use the basic combat and character systems. Content should be authored in project data and original to Worldforge; avoid copying proprietary setting text, feature prose, or other protected material. Familiar tabletop concepts can inspire the rules, while the actual content and wording remain ours.

## Current playable slice

- `[x]` Start a single-player session or host/join a co-op session. Direct TCP supports a party limit of eight players including the host; Internet hosts may need to forward the configured port.
- `[~]` The current demo synchronizes one shared combat state for one session of up to eight players. When any player/enemy pair triggers combat, all connected players enter that shared encounter.
- `[x]` Create/select a character with class, race, subrace, subclass, parent races for a half-breed, abilities, skills, avatar, and starting equipment.
- `[x]` New characters start with 50 gold; quick-start demo characters start with 500.
- `[x]` Create a quick-start, higher-level, geared test character after choosing its class.
- `[x]` Move around a gray-box map with collision, map boundaries, and a camera that follows the local actor until the map edge.
- `[x]` Combat begins automatically when a conscious player comes within 20 feet of a conscious enemy with clear line of sight. Initiative is rolled in place; actors keep their world positions. Turns provide movement, an action, and a bonus action. Movement can be split around other turn actions.
- `[x]` Select a target and trigger the primary attack with `1`, force a ranged-weapon attack with `R`, or explicitly throw a throwable main-hand item with `T`. Ranged attacks can have disadvantage by range; melee attacks outside reach cannot hit. Clear line of sight is required.
- `[x]` Cast the implemented spells and abilities, use supported consumables, and display supported conditions such as burning.
- `[x]` Perception automatically reveals an NPC's title based on its information DCs; this check does not require line of sight.
- `[x]` Track downed players. They may wait for another player to revive them or release their spirit to the inn for a 10% unspent-XP loss. Being revived costs 2% XP. Revive healing is rolled as `2d4`.
- `[~]` Inventory and equipment support item instances, equipment slots, weapon sets, and dual wielding. Inventory capacity, item acquisition, and a finished inventory UX remain future work.
- `[~]` Hovering carried and equipped items shows their available data. Pool counts are visible in play; outdoor rest on `Z` checks distance and XP, while inn rest on `F` at the gray-box bed costs 10 gold. Both replenish spell and class pools. Camp-stage travel is not connected yet.
- `[x]` Hovering race, subrace, class, and subclass choices in character creation shows a short content summary.
- `[~]` A small original demo encounter and gray-box environment are present. Art, animation transitions, and variety are intentionally limited.
- `[~]` NPC behavior is a simple test behavior. More capable AI is explicitly deferred.

## Demo encounter loop decisions

The intended repeatable loop is:

1. The encounter factory creates and equips a random mob, then places it at a
   valid random position in the shared world.
2. A visible, conscious player within 20 feet starts combat in place for that
   shared session.
3. Defeating a mob awards 10 XP to each participant in that combat.
4. The next random mob spawns immediately after the kill. The defeated mob
   remains as a corpse with one shared loot container. It drops the NPC
   instance's carried items and equipped starting gear. Press `F` within 5
   feet to open it; each taken item is removed for everyone. Closing the loot
   panel or taking all starts a three-second despawn timer. Respawning does not
   wait for corpse cleanup.
5. Abilities default to one use per fight and can override that limit in data.
   Uses reset for a new fight.
6. Spells have no ranks or rank-specific slots. A character casts spells at
   their character level and spends points from one shared spell pool. Each
   class has a tuneable spell-point progression curve; the pool grows at every
   character level. Multiclass characters sum each class's curve at that
   class level. Resting replenishes the pool. Individual spells may later
   cost multiple points or require components, without introducing spell
   ranks. Configurable class resources use separate pools and can be spent by
   abilities; named feature implementations still need to be added.
7. Resting is the recovery and advancement loop: replenish the spell pool and
   allow characters with enough XP to level up. An outdoor rest costs XP: the
   rate starts at 1% of unspent XP and increases with consecutive outdoor
   rests, capped at 5%. Outdoor rest is allowed only when the party is more
   than 100 feet from every enemy. The planned camp flow transports the party
   to a separate stage without combat interruptions; the current prototype
   resolves outdoor rests in place. The cost has a 1 XP minimum
   when the character has less than 100 unspent XP. Resting inside an inn costs
   a flat 10 gold and resets the outdoor-rest rate to 1%. A character with no
   unspent XP cannot rest outdoors and must reach an inn. XP thresholds for
   leveling follow the fifth-edition curve. Recovery details beyond spell
   points remain open. Rest reports current XP-based level eligibility but
   does not apply a level-up.

The first repeatable encounter loop is wired: a victory awards XP once, keeps
the defeated mob in the world for looting, and immediately adds a factory
created NPC with its configured gear at a random clear map position. Corpse
loot is shared; its three-second despawn timer starts when looting ends. The
victory replay prompt is gone. Ability
use limits, shared spell-point spending, configurable class resource pools,
and rest cost/replenishment rules are implemented. Rest confirmation and
co-op party application are wired; camp-stage travel and applying earned
levels are not.

### Mob generation and loot

The encounter factory assigns a class, class-prioritized abilities, and
proficiency-filtered gear to each mob. Templates tune elite chance and base
item pools; elite stats stay level-bounded while item level and rarity shift up.
Rarity controls the count of eligible attributes, which apply to weapon damage,
attack rolls, AC, max HP, and saving throws. Corpse loot preserves those exact
item instances and IDs. Broader mob variety, drop tables, and gold drops remain
future work.

## Roadmap checklist

### Trainer, purchases, and level eligibility

- A single trainer stands beside the inn. Press `F` nearby to open a trainer
  screen modeled on the spellbook, with one tab for each class.
- Each class tab lists that class's spells and abilities, organized by level.
  XP-derived character level is the maximum purchase tier in every class;
  each class tracks its own purchased-spell progression toward that ceiling.
  A level 5 character with Wizard spells through level 4 can buy Wizard level 5
  spells. If they own Cleric spells only through level 2, they can buy Cleric
  level 3 spells. Buying a level-N spell requires at least one level-(N-1)
  spell from the same class. XP loss can lower the shared purchase ceiling,
  but does not remove owned spells or abilities; purchases above the new
  ceiling stay locked until eligibility is regained.
- XP is spent to buy spells and abilities. XP spending can lower level
  eligibility, as can outdoor resting and death. Releasing the spirit after
  death costs 10% XP; being revived by another player costs 2% XP.
- Character levels 4, 8, 12, 16, and 20 each grant two spendable attribute
  points. Each point raises one ability score by one; scores may be stored above
  30, but calculations cap at 30.
- Each spell and ability has a data-authored `xp_purchase_cost`; currently the
  tier-N default demo entries cost N × 10 XP. The primary class pays the base
  price; later classes pay 2x, 3x, and so on. Unlocking an additional class
  costs 500 XP for the second class, then triples for each later unlock.
  These values are configured in `data/progression.json`. Abilities can
  advance a tier for classes with no trainer-purchase spells at the prior tier.
- `[x]` Trainer screen, purchase validation, ownership ledgers, XP deleveling,
  explicit class unlock fees and class-order price multipliers, inn release,
  revival penalties, and character-sheet attribute-point spending are
  implemented. Applying earned levels and level-based HP growth remain open.

### 1. Make the demo slice easy to understand and extend

- `[x]` Add a short in-game controls panel covering movement, target selection, attack, throw, spell/ability controls, inventory, and turn advance (toggle with F1).
- `[~]` Use `F` as the shared nearby-interaction key. Inn beds open a confirmation prompt before charging 10 gold per character and resting; defeated corpses open a shared loot panel within 5 feet. Doors and chests still need interaction behavior.
- `[x]` Spell and ability selection uses four saved bars of ten numbered slots, stacked in the lower-left area when assigned; backtick selects the active bar for number-key use. The `-` key opens separate spell and ability pages; choose an available action and click a slot to assign it. F2 toggles hover tooltips.
- `[x]` Q/E bind to consumables from Inventory and use one item per press. Stackable consumables share an inventory row, decrement on use, and remain bound until the stack is empty.
- `[x]` Expand the play window to 1024x768 and the demo arena to 1600x1100 so the camera can scroll around a world larger than the viewport. Place action bars lower-left and combat log lower-right.
- `[x]` Spellbook has separate Prepared Spells, Spellbook, and Class Abilities pages. Players can toggle known spells as prepared and assign prepared spells or class abilities to the shared action bars.
- `[ ]` Add key remapping to the in-game Settings UI. Make rebinding approachable: select an action, press the desired key, clearly resolve conflicts, and provide a one-click restore-defaults option. Keep the defaults documented for players and modders.
- `[ ]` Add clear feedback for invalid actions: out of range, blocked line of sight, no action budget, invalid target, and insufficient resources.
- `[ ]` Improve the test encounter into a short repeatable demo loop with a clear start, victory state, and return/retry path.
- `[ ]` Add a second gray-box area or encounter to prove that maps and encounters can be added through data.
- `[ ]` Document how to launch host/client sessions and what router forwarding is needed for direct Internet hosting.
- `[ ]` Make a manual smoke-check list for the demo's critical flows (single player, two clients, character creation, combat, revive, save/reload). No automated test requirement is implied by this checklist.

### 2. Rest system — design and implement

- `[?]` Choose the rest types, their in-world duration, and what makes a location safe enough to rest.
- `[?]` Decide whether rests can be interrupted by encounters and what happens to each participant when a co-op party is not ready at the same time.
- `[~]` Rest replenishes the shared spell pool and configured class resource pools. Health, conditions, and consumables are not recovered; define those effects separately before adding them.
- `[x]` Outdoor rest requires more than 100 feet of distance from every enemy. It costs a percentage of unspent XP, starting at 1% and increasing with consecutive outdoor rests to a 5% cap; apply a 1 XP minimum when unspent XP is below 100. With zero unspent XP, outdoor rest is unavailable and the character must reach an inn. An inn rest costs a flat 10 gold and resets the outdoor rate to 1%.
- `[x]` Downed players may wait for revival or return to the inn by releasing their spirit for a 10% unspent-XP penalty.
- `[x]` Rest cost and pool replenishment rules are implemented in `resting.py` and connected to outdoor and inn actions. Camp-stage travel, a ready flow, health recovery, and condition recovery remain unimplemented.
- `[ ]` Add UI for starting a rest, party readiness, interruptions, and the resulting recovery summary.
- `[ ]` Persist and synchronize rest state safely in co-op so clients cannot recover twice from one rest.

### 3. XP, levels, and character progression

- `[~]` Actor storage tracks total XP and earned/spent-by-level ledgers. Combat awards update total and earned XP; outdoor rests separately track XP costs.
- `[x]` A defeated encounter awards 10 XP once to every player participant. Other XP sources remain undecided.
- `[x]` XP thresholds, current unspent-XP eligibility, per-item trainer prices, and ownership ledgers are implemented in `worldforge/core/progression.py` and the trainer action flow.
- `[~]` Attribute points are awarded at levels 4, 8, 12, 16, and 20 and can be spent from the character sheet. Applying earned character levels, hit point growth, subclass features, and other level-up choices remain open.
- `[x]` One map trainer has tabs for all classes. Spell/ability ownership is per character and retained after deleveling; current XP eligibility and the class purchase chain control access.
- `[x]` Implement one authoritative XP award path with duplicate-award protection.
- `[x]` Implement XP-based level eligibility, spell/ability purchases, and a player-facing trainer flow.
- `[ ]` Connect class and subclass progression data to actual unlocks/effects; current progression entries are mostly descriptive records.
- `[x]` Add the single trainer interaction and class-tab purchase interface. Attribute-point milestones replace the previous feat placeholders.
- `[ ]` Show character level and progression history on the character sheet.

### 4. Combat and abilities

- `[x]` The gray-box loop supports initiative, turns, movement/action/bonus-action budgets, attacks, basic spells, target selection, and a simple enemy response.
- `[x]` Attack resolution keeps room for future modifiers; ties to defense hit. Weapon damage uses weapon dice and the applicable ability modifier.
- `[x]` Weapon `2h` capability, weapon sets, ranged weapons, explicit thrown attacks, and the staff's off-hand-sensitive damage rule are represented in the current item/rule data.
- `[x]` Conditions include initial examples, including burning damage over time and attack disadvantage from off-balance.
- `[ ]` Expand spell/ability resolution so new effects can be authored without adding a bespoke branch to the main game loop for every effect.
- `[ ]` Add clear condition duration, stacking, expiry, and source attribution rules.
- `[ ]` Add more player and NPC actions to exercise the combat framework.
- `[x]` Abilities default to one use per combat (`uses_per_combat` can tune this); combat state resets the counter for a new fight.
- `[~]` Replace spell ranks/slots with one shared spell-point pool. Pool capacity is class-curve driven and casts consume configurable points; rest refills it. Spell effect scaling from character level and known-spell progression remain open.
- `[x]` Represent configurable class resources as pools separate from spell points; class curves define maxima and abilities can spend them. Specific feature content and progression still need implementation.
- `[ ]` Add flee, hide, and sneak states. Intended direction: sneaking can avoid detection while approaching, hiding uses cover or broken sight to avoid detection, and fleeing gives a way to disengage from an active encounter. Detection and escape rules still need design; these states are not wired yet.
- `[ ]` Improve target selection and combat feedback based on playtesting.
- `[ ]` Add reactions only when the core attack-and-turn loop is stable; reactions were intentionally deferred.
- `[ ]` Replace the dummy NPC behavior with richer AI after the demo mechanics are established.

### 5. Inventory, equipment, and item content

- `[x]` Equipment slots are represented, with slot validation, two ring slots, separate ranged slot, and melee/ranged weapon sets.
- `[x]` Item instances have unique IDs, so identical items can be carried separately. Carried unequipped items are stored on the actor.
- `[x]` Starting gear is class-based static data; unspecified slots remain empty. Character creation can also roll a fully equipped test actor.
- `[~]` Inventory is unlimited for now; corpse loot supports item acquisition, but general capacity rules are not implemented.
- `[x]` Inventory shows character stats, skills, saves, proficiencies, resources, equipped gear, carried items, and item details.
- `[ ]` Add item use/equip feedback and safeguards for invalid slot combinations or duplicate item instances.
- `[x]` Define initial rarity rolls and gear attributes. Mob equipment rolls rarity and eligible affixes at spawn; corpse loot preserves the generated item instances.
- `[ ]` Add more original sample items only as needed to exercise the systems; preserve a compact base list with data-driven attributes.

### 6. Character data, content, and mod support

- `[x]` Classes, races, subclasses, spells, items, encounters, and other content are stored in JSON data rather than being exclusively embedded in code.
- `[~]` The full base class roster and subclass identities/progression drafts exist, but many feature descriptions are not yet runnable mechanics.
- `[~]` Race/subrace traits and half-breed parent selection are available; racial bonuses are stored for later interpretation.
- `[ ]` Establish and document a stable schema/version policy for data mods, including validation errors that name the file and field.
- `[ ]` Document each new system as it is built: data fields and defaults, formulas and tuning points, save/network ownership, lifecycle, extension points, and known limits. Put modder instructions beside the relevant table and maintainer architecture notes in this document or the source module.
- `[ ]` Add a mod loading/override policy so users can safely add content without editing built-in files.
- `[ ]` Add examples for a new class, item, spell, condition, NPC, and encounter to the modding guide.
- `[ ]` Keep player-facing names intact where already established, while replacing copied rules text with original summaries and Worldforge-specific implementation.

### 7. Co-op, saving, and reliability

- `[x]` Direct host/client co-op works with a party limit of eight including the host.
- `[~]` Direct Internet connection depends on host network/router configuration; there is no relay service.
- `[ ]` Add reconnect handling and a clear response when the host disconnects or a client drops.
- `[ ]` Define host authority for combat rolls, inventory changes, XP awards, and rest results to prevent conflicting state.
- `[ ]` Review save/load behavior for party members, combat state, consumed items, and progression.
- `[ ]` Add a user-facing connection setup/help panel and expose the configured host port in one place.
- `[ ]` Consider a relay or matchmaking service only if direct hosting becomes a blocker; it requires infrastructure beyond the current local game.

### 8. Presentation and release polish

- `[~]` The project is intentionally gray-boxed and currently has limited sprites and effects.
- `[ ]` Replace placeholder map tiles and test shapes with a coherent starter tileset and collision layer.
- `[ ]` Expand animation feedback for idle, walk, melee, ranged attacks/projectiles, damage, and death using the agreed sprite-row layout.
- `[ ]` Add readable combat log/event feedback and improve status/health presentation.
- `[ ]` Add audio cues for attacks, hits, spells, turns, and important menu actions.
- `[ ]` Review accessibility basics: key rebinding, readable text sizing, color-independent condition indicators, and clear focus states.
- `[ ]` Package a playable demo build with a short setup guide and a sample mod.

## Explicitly deferred

- Reactions and opportunity attacks.
- Advanced NPC AI.
- A hosted relay/matchmaking service.
- A finished art pass.
- A fully designed inventory capacity/economy model.

These items can move back into active work when the core gray-box demo needs them or the design is ready.
