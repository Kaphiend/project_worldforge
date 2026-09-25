# Worldforge Design and Roadmap

This document describes the current playable slice and tracks the work still needed to grow it. It is written for the project owner and future modders. The code and JSON data are the implementation; where this document marks a system as partial or open, the details below are a roadmap rather than a claim that the feature already works.

## Status key

- `[x]` Implemented in the current slice.
- `[~]` Partly implemented, stubbed, or awaiting broader content.
- `[ ]` Not implemented yet.
- `[?]` Needs a design decision before implementation.

## Product direction

Worldforge is a moddable, data-driven, top-down co-op RPG. A session supports up to eight connected players in a shared world and combat encounter. The immediate target is a gray-box demo slice: create characters, enter a small area together, encounter mobs, and use the basic combat and character systems. D&D SRD 5.2.1 is the baseline for class, species, and supported combat rules. Worldforge keeps its XP purchases and attribute-point advancement, writes original summaries, and tracks required SRD attribution in `docs/project/SRD-5.2.1.md`.

## Current code layout

Game code is grouped under `worldforge/` by app, actors, combat, core systems,
content, networking, and UI. `worldforge/app/game.py` preserves the `run_game`
entry point. The frame loop coordinates input and drawing; host-owned world
updates, input helpers, the HUD, action resolution, requests, encounter setup,
world geometry, and character rendering live in separate modules. Party
membership and connection lifecycle live in `party.py`; mob creation and
victory cleanup live in `encounters.py`. Project instructions and modding
references are collected under `docs/`; JSON content and art remain under
`data/` and `asset_pack/`.

## Current playable slice

- `[x]` Start a single-player session or host/join a co-op session. Direct TCP supports a party limit of eight players including the host; Internet hosts may need to forward the configured port.
- `[~]` The current demo synchronizes one shared combat state for one session of up to eight players. When any player/enemy pair triggers combat, all connected players enter that shared encounter.
- `[x]` Create/select a character with class, race, subrace, subclass, parent races for a half-breed, abilities, skills, avatar, and starting equipment. Starter ability scores are assigned to favor the chosen class.
- `[x]` New characters start with 50 gold; quick-start demo characters start with 500.
- `[x]` Create a quick-start, higher-level, geared test character after choosing its class.
- `[x]` Move around a gray-box map with collision, map boundaries, and a camera that follows the local actor until the map edge.
- `[x]` Combat begins automatically when a conscious player comes within 20 feet of a conscious enemy with clear line of sight. Initiative is rolled in place; actors keep their world positions. Turns provide movement, an action, and a bonus action. Movement can be split around other turn actions.
- `[x]` Select a target and trigger the primary attack with `1`, force a ranged-weapon attack with `R`, or explicitly throw a throwable main-hand item with `T`. Ranged attacks can have disadvantage by range; melee attacks outside reach cannot hit. Clear line of sight is required.
- `[~]` The spell and ability execution paths support data-defined effects. SRD-guided starter spells cover attacks, saves, healing, rooting, an AC ward, and a weapon blessing. Starter melee actions now exercise resistance, advantage, healing, action recovery, extra attacks, and class resource pools; broader class coverage remains open.
- `[x]` Perception automatically reveals an NPC's title in stages based on its information DCs; elite titles can add a further stage. This check does not require line of sight.
- `[x]` Track downed players. They may wait for another player to revive them or release their spirit to the inn for a 10% unspent-XP loss. Being revived costs 2% XP. Revive healing is rolled as `2d4`.
- `[~]` Inventory and equipment support item instances, equipment slots, weapon sets, dual wielding, equipment changes, consumable use, quick slots, and shared corpse loot. The character sheet shows abilities, skills, saves, proficiencies, resources, XP, class features, and gear. Inventory remains unlimited; broader acquisition and economy rules are open.
- `[x]` Item details and supported effects are shown in the inventory UI. Pool counts are visible in play. Outdoor rest on `Z` transports the party to safe camp, where each member uses an assigned bedroll and pays their XP cost. Inn rest requires each member to check in at the bed and pay gold. Short and long rest recovery differs; long rests cost more through campaign tuning.
- `[x]` Hovering race, subrace, class, and subclass choices in character creation shows a short content summary.
- `[~]` A small original demo encounter and gray-box environment are present. Art, animation transitions, and variety are intentionally limited.
- `[x]` NPCs have a simple pursuit-and-attack behavior. Spell use, tactics, cover, and healing are not supported; advanced AI is deferred.

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
6. Leveled spells use class-defined SRD Spellcasting slots; Warlocks use Pact
   Magic slots. Multiclass Spellcasting combines full and half caster levels.
   Spell records define level and optional upcast effects. Some class features,
   component requirements, and broader spell coverage remain incomplete.
7. Short and long rests recover different resources. A short rest can spend
   Hit Dice for healing; a long rest restores HP, half of spent Hit Dice,
   standard spell slots, and long-rest resources. Warlock Pact Magic and
   short-rest resources recover on short rests. Outdoor rests cost XP and rise with consecutive outdoor rests; inn rests cost
   gold. The campaign applies a larger multiplier to long rests at either
   location. Resting is available only with unspent XP.
   Rested conditions remain unless a rule clears them. XP thresholds for
   leveling follow the configured curve; level application remains at the trainer.

The repeatable encounter loop is wired: a victory awards XP once, keeps the
defeated mob in the world for looting, and adds a factory-created NPC at a
random clear position. Corpse loot is shared; its three-second despawn timer
starts when looting ends. Ability use limits, class spell slots, configurable class resource pools, rest
costs, and recovery are implemented. Inn confirmation, camp travel, party check-in, and co-op rest
application are wired. Applying earned levels remains open.

### Mob generation and loot

The encounter factory assigns a class, class-prioritized ability scores and
skills, and proficiency-filtered gear to each mob. Templates tune elite chance
and base item pools. Elites gain modest, level-bounded ability bonuses and base
HP; their gear item level and rarity shift up. Rarity controls how many eligible
attributes roll onto each item, with no repeated attribute group on the same
item. Current effects include doubled weapon dice, weapon damage and attack
bonuses, AC, maximum HP, and saving throw bonuses. Elite scaling affects base
stats; gear effects are applied independently. Perception reveals names in
stages, including elite titles. Corpse loot keeps the mob's actual item
instances and IDs. Broader mob variety, drop tables, and
gold drops remain future work.

## Roadmap checklist

### Trainer, purchases, and level eligibility

- A single trainer stands beside the inn. Press `F` nearby to open a trainer
  screen modeled on the spellbook, with one tab for each class.
- Each class tab lists that class's spells and abilities, organized by level.
  XP-based purchase eligibility and the character's applied level both limit
  class purchases. Each class tracks its applied level and purchased-spell
  progression.
  A level 5 character with Wizard spells through level 4 can buy Wizard level 5
  spells. If they own Cleric spells only through level 2, they can buy Cleric
  level 3 spells. Buying a level-N spell requires at least one level-(N-1)
  spell from the same class. XP loss can lower the trainer purchase ceiling,
  but does not remove owned spells or abilities; purchases above the new
  ceiling stay locked until eligibility is regained.
- XP is spent to buy spells and abilities. Spending XP, outdoor resting, and
  death can lower purchase eligibility, but never removes an applied character
  level. Releasing the spirit after death costs 10% XP; being revived by
  another player costs 2% XP.
- Character levels 4, 8, 12, 16, and 20 each grant two spendable attribute
  points. Each point raises one ability score by one; scores may be stored above
  30, but calculations cap at 30.
- Each trainer-purchasable spell and ability has a data-authored `xp_purchase_cost`; currently the
  tier-N default demo entries cost N × 10 XP. The primary class pays the base
  price; later classes pay 2x, 3x, and so on. Unlocking an additional class
  costs 500 XP for the second class, then triples for each later unlock.
  These values are configured in `data/progression.json`. Abilities can
  advance a tier for classes with no trainer-purchase spells at the prior tier.
- `[~]` Trainer purchase validation, ownership ledgers, XP eligibility,
  explicit class unlock fees and class-order price multipliers, inn release,
  revival penalties, and level application are implemented. Leveling grants
  fixed-average class Hit Die HP plus Constitution modifier (minimum +1), and
  raises current HP by the same amount. Subclass features and other level-based
  unlocks remain open.

### 1. Make the demo slice easy to understand and extend

- `[x]` Add a short in-game controls panel covering movement, target selection, attack, throw, spell/ability controls, inventory, and turn advance (toggle with F1).
- `[~]` `F` is the shared nearby-interaction key. Inn beds open a confirmation prompt before charging XP per character; defeated corpses open a shared loot panel within 5 feet; arena exits move the connected party between data-defined areas. Doors and chests still need interaction behavior.
- `[x]` Spell and ability selection uses four saved bars of ten numbered slots, stacked in the lower-left area when assigned; backtick selects the active bar for number-key use. The `-` key opens separate spell and ability pages; choose an available action and click a slot to assign it. F2 toggles hover tooltips.
- `[x]` Q/E bind to consumables from Inventory and use one item per press. Stackable consumables share an inventory row, decrement on use, and remain bound until the stack is empty.
- `[x]` Expand the play window to 1024x768 and the demo arena to 1600x1100 so the camera can scroll around a world larger than the viewport. Place action bars lower-left and combat log lower-right.
- `[x]` Spellbook has separate Prepared Spells, Spellbook, and Class Abilities pages. Players can toggle known spells as prepared and assign prepared spells or class abilities to the shared action bars.
- `[x]` Open a fixed-size key remapper from the Escape menu. Click an action, press an unused key, and restore defaults from one button; bindings persist in the user's settings file.
- `[x]` Invalid actions such as out-of-range attacks, blocked line of sight, spent action budgets, invalid targets, and insufficient resources are reported in the combat log; the affected target briefly flashes. Further tuning can follow playtesting.
- `[~]` The test encounter has a repeatable spawn, combat, victory, XP, and loot loop. A clearer first-time start and a deliberate return/retry flow remain open.
- `[x]` Add a second gray-box area connected by data-defined exits to prove that maps and encounters can be added through data.
- `[x]` Building and modding guides explain launching the app, host/client sessions, and router forwarding for direct Internet hosting.
- `[ ]` Make a manual smoke-check list for the demo's critical flows (single player, two clients, character creation, combat, revive, save/reload). No automated test requirement is implied by this checklist.

### 2. Rest system — design and implement

- `[x]` Outdoor and inn rests require every connected party member to check in. Outdoor travel requires every member to be over 100 feet from each living enemy; the safe-camp stage has one assigned bedroll per character and suppresses encounters while the party rests.
- `[~]` Short and long rest types are supported; elapsed time, interruptions, and rest exhaustion are not modeled. Short rests may spend Hit Dice for healing. Long rests restore HP and half of spent Hit Dice. Conditions only clear when their own rule says so.
- `[x]` Outdoor rest requires each party member to be more than 100 feet from every living enemy, transports them to the safe camp, and charges each member 1% of unspent XP, increasing with consecutive outdoor rests to a 5% cap; apply a 1 XP minimum when unspent XP is below 100. With zero unspent XP, outdoor rest is unavailable and the character must reach an inn. Each party member checks in and pays the configured inn gold price; short and long rest multipliers apply, and inn rests reset the outdoor streak.
- `[x]` Downed players may wait for revival or return to the inn by releasing their spirit for a 10% unspent-XP penalty.
- `[x]` Rest cost and recovery rules are implemented in `worldforge/combat/resting.py`. Safe-camp travel and camp-bed check-in are connected to outdoor rests; inn rests require each member's confirmed check-in and payment.
- `[x]` Inn and outdoor rests complete only after every connected party member is ready. Rest requests are handled through the host and results synchronize to the party.

### 3. XP, levels, and character progression

- `[x]` Actor storage tracks total XP and earned, trainer-spent, and rest-spent ledgers. Combat awards update total and earned XP.
- `[x]` A defeated encounter awards 10 XP once to every player participant. Other XP sources remain undecided.
- `[x]` XP thresholds, current unspent-XP eligibility, per-item trainer prices, and ownership ledgers are implemented in `worldforge/core/progression.py` and the trainer action flow.
- `[x]` Two attribute points are granted at applied levels 4, 8, 12, 16, and 20. A dedicated screen opened from Inventory/Character Sheet spends them one point at a time. Scores may be stored above 30, while calculations cap at 30.
- `[x]` The trainer offers earned but unapplied levels and lets the player assign each to an unlocked class. Applied levels remain permanent when XP is spent; spending XP lowers trainer purchase eligibility only.
- `[x]` One map trainer has tabs for all classes. Spell/ability ownership is per character and retained after deleveling; current XP eligibility and the class purchase chain control access.
- `[x]` Implement one authoritative XP award path with duplicate-award protection.
- `[x]` Implement permanent applied character levels, XP-based trainer purchase eligibility, and a player-facing trainer level-up flow.
- `[~]` Class and subclass features, skill proficiencies, spells, cantrips, and abilities are normally acquired with XP from the trainer. New characters receive configured starter spells and melee actions; Fighter's level-5 Second Windup remains a purchased feature that grants a follow-up weapon attack. Other progression effects remain descriptive until implemented.
- `[x]` Add the single trainer interaction and class-tab purchase interface. Attribute-point milestones replace the previous feat placeholders.
- `[~]` The character sheet shows level and XP totals. A progression history and earned/spent ledger view remain open.

### 4. Combat and abilities

- `[~]` The gray-box loop supports initiative, turns, movement/action/bonus-action budgets, attacks, data-defined spell and ability resolution, target selection, and a simple enemy response. New characters receive class-configured starter spells and melee actions on their first hotbar; broader spell and ability coverage remains open.
- `[x]` Attack resolution keeps room for future modifiers; ties to defense hit. Weapon damage uses weapon dice and the applicable ability modifier.
- `[x]` Weapon `2h` capability, weapon sets, ranged weapons, explicit thrown attacks, and the staff's off-hand-sensitive damage rule are represented in the current item/rule data.
- `[x]` Conditions include initial examples, including burning damage over time and attack disadvantage from off-balance.
- `[~]` Several spell and ability effects are data-driven through supported effect primitives. Adding unsupported targeting or effect behavior still requires code changes.
- `[~]` Basic duration, refresh, expiry, and recurring damage are implemented. Stacking and source attribution rules remain incomplete.
- `[~]` Add more player and NPC actions to exercise the combat framework. Spell starter actions now exercise attacks, saves, healing, conditions, and timed effects; class-specific martial actions remain open.
- `[x]` Abilities default to one use per combat (`uses_per_combat` can tune this); combat state resets the counter for a new fight.
- `[~]` Leveled spells use class-defined Spellcasting slots or Warlock Pact Magic slots. Short and long rests recover the matching pools; slot selection and broader spell coverage need more UI/content work.
- `[x]` Configurable class resources are separate pools with class-defined maxima and recovery cadence.
- `[~]` Sneak reduces exploration speed and contests mob passive Perception. Hide uses the SRD 5.2.1 cover/line-of-sight gate and DC 15 Dexterity (Stealth) check. Flee and active Search remain open; arena obstacles currently stand in for full cover.
- `[ ]` Improve target selection and combat feedback based on playtesting.
- `[ ]` Add reactions only when the core attack-and-turn loop is stable; reactions were intentionally deferred.
- `[ ]` Replace the dummy NPC behavior with richer AI after the demo mechanics are established.

### 5. Inventory, equipment, and item content

- `[x]` Equipment slots are represented, with slot validation, two ring slots, separate ranged slot, and melee/ranged weapon sets.
- `[x]` Item instances have unique IDs, so identical items can be carried separately. Carried unequipped items are stored on the actor.
- `[x]` Starting gear is class-based static data; unspecified slots remain empty. Character creation can also roll a fully equipped test actor.
- `[~]` Inventory is unlimited. Shared corpse loot grants item instances; the Market Square vendor supports purchases, sales, and session buyback. Inventory capacity and broader economy rules remain open.
- `[x]` Inventory shows character stats, skills, saves, proficiencies, resources, equipped gear, carried items, and item details.
- `[~]` Equipment legality and item-instance checks are enforced, and supported item use/equip actions report errors. More polished feedback and broader edge-case review remain open.
- `[x]` Define initial rarity rolls and gear attributes. Mob equipment rolls rarity and eligible affixes at spawn; corpse loot preserves the generated item instances.
- `[ ]` Add more original sample items only as needed to exercise the systems; preserve a compact base list with data-driven attributes.

### 6. Character data, content, and mod support

- `[x]` Classes, races, subclasses, spells, items, encounters, and other content are stored in JSON data rather than being exclusively embedded in code.
- `[~]` Class skill choices and selectable subclasses follow SRD 5.2.1. Rogue early features are drafted from the SRD; Hide, Cunning Action's bonus-action Hide, and purchased Sneak Attack have runtime support. Other class and subclass effects remain data descriptions until implemented.
- `[~]` Species and lineage choices follow SRD 5.2.1, without species ability bonuses. Runtime support includes passive Perception proficiency, speed, maximum HP, damage resistance, and Halfling Lucky attack rerolls; active and environment-dependent species traits remain descriptive.
- `[~]` Race/subrace traits and half-breed parent selection are available; racial bonuses are stored for later interpretation.
- `[ ]` Establish a stable schema/version policy for data mods and validation errors that identify the file and field.
- `[x]` Modding and architecture notes cover current data fields, tuning points, ownership, lifecycle, extension points, and known limits. Keep them current as systems change.
- `[x]` Mods load from separate folders; later alphabetic definitions override matching IDs. Packaged builds support per-user mods without editing built-in data. Schema validation and a version policy remain open.
- `[~]` The guide includes a complete demo encounter and examples for supported tables. Dedicated end-to-end examples for every content type remain open.
- `[ ]` Keep player-facing names intact where already established, while replacing copied rules text with original summaries and Worldforge-specific implementation.

### 7. Co-op, saving, and reliability

- `[x]` Direct host/client co-op works with a party limit of eight including the host.
- `[~]` Direct Internet connection depends on host network/router configuration; there is no relay service.
- `[ ]` Add reconnect handling and a clear response when the host disconnects or a client drops.
- `[~]` The host currently processes combat and mutating player requests, including loot, XP, and rest. Audit authority and synchronization for disconnects, duplicate requests, and conflicting state.
- `[~]` Save loading has defaults and migrations for older actor data, and the save directory is created automatically. Full review of co-op state, combat recovery, and all item/progression edge cases remains open.
- `[~]` The host/join UI and documentation explain direct connections; a consolidated connection help panel and a single visible port setting remain open.
- `[~]` No relay or matchmaking service is planned while direct hosting remains workable. Revisit only if direct hosting becomes a blocker; it requires infrastructure beyond the current local game.

### 8. Presentation and release polish

- `[~]` The project is intentionally gray-boxed and currently has limited sprites and effects.
- `[ ]` Replace placeholder map tiles and test shapes with a coherent starter tileset and collision layer.
- `[x]` Idle, walk, melee, ranged/projectile, damage, and death animation feedback use the current sprite-row layout. The art and transition polish remain limited.
- `[~]` Combat log, health, spell points, target feedback, and action errors are visible. Broader status presentation and playtest-driven readability improvements remain open.
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
