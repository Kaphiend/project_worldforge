"""Combat action validation, turn flow, and effect resolution."""
import math
from copy import deepcopy
import uuid


from worldforge.combat.rules import attack as resolve_attack
from worldforge.combat.rules import distance_feet, edge_distance_feet, selected_weapon
from worldforge.content.classes import ABILITIES, SPELLS, ARENAS, NPCS, SCENARIOS
from worldforge.combat.controllers import controller_for
from worldforge.combat.conditions import has_condition, tick_conditions
from worldforge.combat.spell_effects import apply_ability_effects, resolve_spell
from worldforge.actors.factory import equip_item, item_definition, unequip_item
from worldforge.core.progression import spell_point_max, qualified_level, charge_xp_penalty, sync_progression_levels, character_level_for_xp
from worldforge.combat.resting import resolve_rest
from worldforge.app.encounters import DEFAULT_SCENARIO, _combat_snapshot, _progression_sync_state

from worldforge.app.world import ACTOR_SIZE, PIXELS_PER_FOOT, _actor_hitbox, _arena_bounds, _line_of_sight, _movement_allowance, _walk_destination
from worldforge.app.rendering import _capture_hp, _emit_animation, _player_id

def _animate_hp_changes(combat, before):
    for actor_id, entry in combat.get("actors", {}).items():
        old_hp, old_downed = before.get(
            actor_id, (entry["data"].get("current_hp", 0), entry["downed"]))
        new_hp = entry["data"].get("current_hp", 0)
        entry["downed"] = bool(entry["data"].get("downed", False) or new_hp <= 0)
        if new_hp < old_hp:
            _emit_animation(combat, actor_id,
                            "dead" if entry["downed"] else "hurt")
        elif old_downed and not entry["downed"]:
            _emit_animation(combat, actor_id, "idle")
            penalty = charge_xp_penalty(entry["data"], 2)
            if penalty:
                _log(combat, f"{entry['data'].get('name', actor_id)} loses {penalty} XP after being revived.")

def _do_spell(combat, actor_id, spell_id, target_id=None):
    actor_entry = combat['actors'].get(actor_id)
    if not actor_entry or actor_entry['downed']:
        return False
    spell = SPELLS.get(spell_id)
    if not spell:
        _reject_action(combat, 'Unknown spell.', actor_id)
        return False
    budget = combat['budgets'][actor_id]
    if not budget.get('action'):
        _reject_action(combat, 'Action already used this turn.', actor_id)
        return False
    caster = actor_entry['data']
    prepared_spells = caster.get("prepared_spells", [])
    actor_classes = {item.get("name") for item in caster.get("classes", []) or []
                     if item.get("name")}
    if caster.get("char_class"):
        actor_classes.add(caster["char_class"])
    if not actor_classes.intersection(spell.get("classes", [])):
        _reject_action(combat, 'Your class cannot cast this spell.', actor_id)
        return False
    if spell_id not in prepared_spells:
        _reject_action(combat, f"{spell['name']} is not prepared.", actor_id)
        return False
    spell_cost = max(0, int(spell.get("spell_point_cost", 1)))
    spell_points = int(caster.get("spell_points", 0) or 0)
    if spell_points < spell_cost:
        _reject_action(
            combat,
            f"Not enough spell points for {spell['name']} ({spell_cost} needed; {spell_points} available).",
            actor_id)
        return False
    target_info = spell.get('targeting', {})
    target_entry = combat['actors'].get(target_id) if target_id else None
    mode = target_info.get('mode')
    if mode not in ('self',) and not target_entry:
        _reject_action(combat, 'Invalid target: select an available target first.', actor_id)
        return False
    if target_entry and target_entry["data"].get("withdrawn"):
        _reject_action(combat, "That character has left the fight.", target_id)
        return False
    targets = [target_entry['data']] if target_entry else None
    point = None
    if mode == 'small_area':
        point = (target_entry['x'] + target_entry['width'] / 2,
                 target_entry['y'] + target_entry['height'] / 2)
        radius = int(target_info.get('radius_feet', 0)) * PIXELS_PER_FOOT
        targets = [entry['data'] for entry in combat['actors'].values()
                   if not entry['data'].get("withdrawn")
                   and math.hypot(entry['x'] + entry['width'] / 2 - point[0],
                                 entry['y'] + entry['height'] / 2 - point[1]) <= radius]
    if mode == 'self':
        targets = [caster]
    hp_before = _capture_hp(combat)
    line_of_sight = (True if mode == 'self' or not target_entry else
                     _line_of_sight(actor_entry, target_entry, combat.get('arena')))
    result = resolve_spell(spell_id, caster, targets,
                           target_position=point, line_of_sight=line_of_sight)
    if not result.get('success'):
        _reject_action(combat, result.get('message', 'Spell failed.'),
                       target_id or actor_id)
        return False
    budget['action'] = False
    caster["spell_points"] = spell_points - spell_cost
    remaining_points = caster["spell_points"]
    if spell_cost:
        _log(combat, (f"{caster.get('name', 'Caster')} spends {spell_cost} spell point"
                      f"{'s' if spell_cost != 1 else ''} ({remaining_points}/"
                      f"{spell_point_max(caster)} left)."))
    else:
        _log(combat, f"{caster.get('name', 'Caster')} casts {spell['name']} without spending spell points.")
    for item in result['results']:
        details = []
        roll = item.get('roll')
        if roll:
            details.append(f"roll {roll.get('natural')} = {roll.get('total')}")
        for effect in item.get('effects', []):
            if effect.get('kind') == 'damage':
                details.append(f"{effect['amount']} {effect.get('damage_type', 'untyped')} damage")
            elif effect.get('kind') == 'healing':
                details.append(f"{effect['amount']} healing")
            elif effect.get('kind') == 'condition':
                details.append(effect['condition'].replace('_', ' '))
        suffix = '; ' + ', '.join(details) if details else ''
        _log(combat, f"{caster.get('name', 'Caster')} casts {spell['name']} on {item['target']}{suffix}.")
    for entry in combat['actors'].values():
        entry['downed'] = bool(
            entry['data'].get('downed', False)
            or entry['data'].get('current_hp', 1) <= 0)
    _remove_downed_from_order(combat)
    _restore_revived_order(combat)
    _animate_hp_changes(combat, hp_before)
    enemies = [entry for entry in combat['actors'].values()
               if entry['team'] == 'enemies']
    if enemies and all(entry['downed'] for entry in enemies):
        combat['active'] = False
        _log(combat, 'All enemies defeated. Combat ended.')
        combat["result"] = {"outcome": "victory", "message": combat.get("scenario", {}).get("victory", "Encounter complete.")}
        _award_combat_xp(combat)
    return True

def _do_ability(combat, actor_id, ability_id, target_id=None):
    actor_entry = combat['actors'].get(actor_id)
    ability = ABILITIES.get(ability_id)
    if not actor_entry or actor_entry['downed'] or not ability:
        _reject_action(combat, 'Ability unavailable to this actor.', target_id or actor_id)
        return False
    actor_data = actor_entry['data']
    if ability_id not in actor_data.get('known_abilities', []):
        _reject_action(combat, 'That ability is not available to this character.', actor_id)
        return False
    uses_limit = ability.get("uses_per_combat", 1)
    actor_uses = combat.setdefault("ability_uses", {}).setdefault(actor_id, {})
    uses_so_far = int(actor_uses.get(ability_id, 0))
    if uses_limit is not None and uses_so_far >= max(0, int(uses_limit)):
        _reject_action(combat, f"{ability['name']} has already been used this fight.", actor_id)
        return False
    resource_cost = ability.get("resource_cost")
    resource_key = None
    resource_amount = 0
    if resource_cost:
        resource_class = resource_cost.get("class_id", actor_data.get("char_class", ""))
        resource_id = resource_cost.get("resource_id", "")
        resource_key = f"{resource_class}.{resource_id}"
        resource_amount = max(1, int(resource_cost.get("amount", 1)))
        available = int(actor_data.get("class_resources", {}).get(resource_key, 0))
        if available < resource_amount:
            _reject_action(combat, f"Not enough {resource_id.replace('_', ' ')} points.", actor_id)
            return False
    target_info = ability.get('targeting', {})
    target_entry = combat['actors'].get(target_id) if target_id else None
    if target_info and target_info.get('mode') != 'self' and not target_entry:
        _reject_action(combat, 'Invalid target: select an available target first.', actor_id)
        return False
    if target_entry and target_entry["data"].get("withdrawn"):
        _reject_action(combat, "That character has left the fight.", target_id)
        return False
    if target_entry and target_info.get('range_feet') is not None:
        if edge_distance_feet(actor_entry, target_entry) > target_info['range_feet']:
            _reject_action(combat, 'Target is outside ability range.', target_id)
            return False
    budget = combat['budgets'][actor_id]
    cost = ability.get('action_cost', 'action')
    if not budget.get(cost, False):
        _reject_action(combat, f"{cost.replace('_', ' ').title()} already used this turn.", actor_id)
        return False
    try:
        hp_before = _capture_hp(combat)
        effect_target = (target_entry['data']
                         if target_entry and target_info.get('mode') != 'self'
                         else actor_data)
        effects = apply_ability_effects(ability_id, actor_data, effect_target)
    except (KeyError, ValueError) as exc:
        _reject_action(combat, f'Ability unavailable: {exc}', target_id or actor_id)
        return False
    budget[cost] = False
    if uses_limit is not None:
        actor_uses[ability_id] = uses_so_far + 1
    if resource_key:
        actor_data.setdefault("class_resources", {})[resource_key] -= resource_amount
    _log(combat, f"{actor_data.get('name', 'Actor')} uses {ability['name']}.")
    _animate_hp_changes(combat, hp_before)
    enemies = [entry for entry in combat["actors"].values()
               if entry["team"] == "enemies"]
    if enemies and all(entry["downed"] or entry["data"].get("current_hp", 1) <= 0
                       for entry in enemies):
        combat["active"] = False
        combat["result"] = {"outcome": "victory", "message": combat.get("scenario", {}).get("victory", "Encounter complete.")}
        _log(combat, "All enemies defeated. Combat ended.")
        _award_combat_xp(combat)
    return bool(effects) or not ability.get('effects')

def _log(combat, message):
    combat.setdefault("log", []).append(message)
    combat["log"] = combat["log"][-8:]

def _award_combat_xp(combat, amount=10):
    """Award the fixed mob-victory XP once to every player in this combat."""
    if combat.get("xp_awarded"):
        return
    combat["xp_awarded"] = True
    for actor_id, entry in combat.get("actors", {}).items():
        if entry.get("team") != "players":
            continue
        data = entry["data"]
        by_level = data.setdefault("xp_earned_by_level", {})
        if not sum(max(0, int(value or 0)) for value in by_level.values()):
            recorded_costs = sum(max(0, int(value or 0)) for value in
                                 data.get("xp_spent_by_level", {}).values())
            recorded_costs += sum(max(0, int(value or 0)) for value in
                                  data.get("xp_rest_spent_by_level", {}).values())
            prior_wallet = max(0, int(data.get("xp_total", 0) or 0))
            if prior_wallet or recorded_costs:
                earned_key = str(character_level_for_xp(prior_wallet + recorded_costs))
                by_level[earned_key] = prior_wallet + recorded_costs
        level_key = str(max(1, int(qualified_level(data))))
        data["xp_total"] = int(data.get("xp_total", 0) or 0) + amount
        by_level[level_key] = int(by_level.get(level_key, 0) or 0) + amount
        sync_progression_levels(data)
        _log(combat, f"{data.get('name', actor_id)} gains {amount} XP.")

def _reject_action(combat, message, target_id=None):
    """Log an invalid action and publish its target for a brief red flash."""
    _log(combat, message)
    if target_id not in combat.get("actors", {}):
        target_id = _active_actor_id(combat)
    combat["action_feedback"] = {
        "id": uuid.uuid4().hex,
        "target_id": target_id,
    }

def _active_actor_id(combat):
    if not combat or not combat.get("active") or not combat.get("order"):
        return None
    return combat["order"][combat["turn_index"]]["id"]

def _advance_turn(combat):
    if not combat or not combat.get("active"):
        return
    previous_id = _active_actor_id(combat)
    if previous_id:
        previous = combat["actors"][previous_id]
        events = tick_conditions(previous["data"], "end")
        for event in events:
            if event.get("expired"):
                _log(combat, f"{event['condition'].replace('_', ' ').title()} fades.")
    for _ in range(len(combat["order"]) * 2):
        combat["turn_index"] += 1
        if combat["turn_index"] >= len(combat["order"]):
            combat["turn_index"] = 0
            combat["round"] += 1
        entry = combat["order"][combat["turn_index"]]
        actor_id = entry["id"]
        actor = combat["actors"][actor_id]
        budget = combat["budgets"][actor_id]
        if actor["downed"] or actor["data"].get("current_hp", 1) <= 0:
            _log(combat, f"{actor['data'].get('name', actor_id)} is downed; turn skipped.")
            continue
        if budget.pop("skip_next", False):
            _log(combat, f"{actor['data'].get('name', actor_id)} skips their first turn.")
            continue
        budget.update(movement=_movement_allowance(actor["data"]), action=True,
                      bonus_action=True, condition_tick_done=False)
        return
    _log(combat, "No active actors can take a turn.")
    combat["active"] = False

def _remove_downed_from_order(combat):
    """Keep downed PCs in the world state, but remove them from initiative."""
    active_id = _active_actor_id(combat)
    old_index = combat.get("turn_index", 0)
    removed = combat.setdefault('removed_order', {})
    for entry in combat.get('order', []):
        if (combat['actors'][entry['id']]['downed']
                or combat['actors'][entry['id']]['data'].get('withdrawn')):
            removed[entry['id']] = entry
    combat["order"] = [entry for entry in combat.get("order", [])
                       if not combat["actors"][entry["id"]]["downed"]
                       and not combat["actors"][entry["id"]]["data"].get("withdrawn")]
    if not combat["order"]:
        combat["active"] = False
        combat["turn_index"] = 0
        return
    remaining_ids = [entry["id"] for entry in combat["order"]]
    if active_id in remaining_ids:
        combat["turn_index"] = remaining_ids.index(active_id)
    elif old_index >= len(remaining_ids):
        combat["turn_index"] = 0
        combat["round"] += 1
    else:
        combat["turn_index"] = old_index

def _restore_revived_order(combat):
    active_id = _active_actor_id(combat)
    removed = combat.setdefault('removed_order', {})
    restored = False
    for actor_id, initiative in list(removed.items()):
        actor = combat['actors'][actor_id]
        if (actor['downed'] or actor['data'].get('current_hp', 0) <= 0
                or actor['data'].get('withdrawn')):
            continue
        combat['order'].append(initiative)
        combat['order'].sort(
            key=lambda entry: (entry['total'], entry['dexterity']), reverse=True)
        del removed[actor_id]
        restored = True
    if restored and any(entry.get("team") == "enemies" and not entry.get("downed")
                        for entry in combat.get("actors", {}).values()):
        combat["active"] = True
    if active_id in [entry['id'] for entry in combat['order']]:
        combat['turn_index'] = next(
            index for index, entry in enumerate(combat['order'])
            if entry['id'] == active_id)

def _process_turn_start(combat):
    """Apply start-of-turn condition primitives once on the authoritative host."""
    actor_id = _active_actor_id(combat)
    if actor_id is None:
        return
    budget = combat["budgets"][actor_id]
    if budget.get("condition_tick_done"):
        return
    budget["condition_tick_done"] = True
    entry = combat["actors"][actor_id]
    hp_before = _capture_hp(combat)
    for event in tick_conditions(entry["data"], "start"):
        _log(combat, (f"{entry['data'].get('name', actor_id)} takes {event['damage']} "
                      f"{event.get('damage_type', 'untyped')} damage from "
                      f"{event['condition'].replace('_', ' ')}."))
    _animate_hp_changes(combat, hp_before)
    if entry["data"].get("current_hp", 1) <= 0:
        entry["downed"] = True
        _log(combat, f"{entry['data'].get('name', actor_id)} is downed.")
        _remove_downed_from_order(combat)
        enemies = [actor for actor in combat["actors"].values()
                   if actor["team"] == "enemies"]
        if enemies and all(enemy["downed"] for enemy in enemies):
            combat["active"] = False
            _log(combat, "All enemies defeated. Combat ended.")
            combat["result"] = {"outcome": "victory", "message": combat.get("scenario", {}).get("victory", "Encounter complete.")}
            _award_combat_xp(combat)
            return
        if combat.get("active"):
            next_id = _active_actor_id(combat)
            next_entry = combat["actors"][next_id]
            combat["budgets"][next_id].update(
                movement=_movement_allowance(next_entry["data"]), action=True,
                bonus_action=True, condition_tick_done=False)

def _do_attack(combat, actor_id, target_id, attack_mode="primary"):
    actor_entry = combat["actors"].get(actor_id)
    target_entry = combat["actors"].get(target_id)
    if not actor_entry or not target_entry:
        _reject_action(combat, 'Invalid target: select an available target first.',
                       actor_id)
        return False
    if target_entry["data"].get("withdrawn"):
        _reject_action(combat, "That character has left the fight.", target_id)
        return False
    if actor_entry["downed"] or target_entry["downed"]:
        _reject_action(combat, "A downed actor cannot attack or be targeted.",
                       target_id if target_entry["downed"] else actor_id)
        return False
    budget = combat["budgets"][actor_id]
    if not budget["action"]:
        _reject_action(combat, "Action already used this turn.", actor_id)
        return False
    distance = distance_feet(actor_entry, target_entry, PIXELS_PER_FOOT, ACTOR_SIZE)
    edge_distance = edge_distance_feet(
        actor_entry, target_entry, PIXELS_PER_FOOT, ACTOR_SIZE)
    line_of_sight = _line_of_sight(actor_entry, target_entry, combat.get("arena"))
    event = resolve_attack(
        actor_entry["data"], target_entry["data"], distance,
        melee_distance_feet=edge_distance, adjacent_distance_feet=edge_distance,
        line_of_sight=line_of_sight,
        attack_mode=attack_mode if attack_mode in ("throw", "ranged") else "primary")
    if not event.get("success"):
        _reject_action(combat, event.get("message", "Attack unavailable."), target_id)
        return False
    budget["action"] = False
    if attack_mode == "ranged":
        weapon = actor_entry["data"].get("equipment", {}).get("ranged")
        weapon_definition = item_definition(weapon) if weapon else {}
    else:
        weapon, weapon_definition, _ = selected_weapon(actor_entry["data"])
    ranged_attack = bool(event.get("ranged"))
    if event.get("thrown"):
        weapon = actor_entry["data"].get("equipment", {}).get("main_hand")
        weapon_definition = item_definition(weapon) if weapon else {}
    if ranged_attack:
        _emit_animation(combat, actor_id, "ranged")
        combat["projectile_event"] = {
            "id": uuid.uuid4().hex,
            "origin": [actor_entry["x"] + ACTOR_SIZE / 2,
                       actor_entry["y"] + ACTOR_SIZE / 2],
            "target": [target_entry["x"] + ACTOR_SIZE / 2,
                       target_entry["y"] + ACTOR_SIZE / 2],
        }
    else:
        swing = int(actor_entry.get("melee_swing_count", 0))
        _emit_animation(combat, actor_id, "attack1" if swing % 2 == 0 else "attack2")
        actor_entry["melee_swing_count"] = swing + 1
    actor_entry["facing_left"] = target_entry["x"] < actor_entry["x"]
    if event["hit"]:
        if target_entry["data"].get("current_hp", 1) <= 0:
            target_entry["downed"] = True
        _emit_animation(combat, target_id,
                        "dead" if target_entry["downed"] else "hurt")
        verdict = "critical hit" if event["critical"] else "hit"
        defense = (f" vs AC {event['target_ac']}"
                   if target_entry["team"] == "players" else "")
        _log(combat, (f"{event['attacker']} {verdict} {event['target']} with "
                      f"{event['weapon']} (d20 {event['rolls']} = {event['total']}"
                      f"{defense}); {event['damage_rolls']} + modifier = "
                      f"{event['damage']} {event['damage_type']} damage."))
    else:
        defense = (f" vs AC {event['target_ac']}"
                   if target_entry["team"] == "players" else "")
        _log(combat, (f"{event['attacker']} misses {event['target']} with "
                      f"{event['weapon']} (d20 {event['rolls']} = {event['total']}"
                      f"{defense})."))
    for enemy in combat["actors"].values():
        if enemy["team"] == "enemies" and enemy["data"].get("current_hp", 1) <= 0:
            enemy["downed"] = True
    _remove_downed_from_order(combat)
    enemies = [entry for entry in combat["actors"].values()
               if entry["team"] == "enemies"]
    if enemies and all(entry["downed"] for entry in enemies):
        combat["active"] = False
        _log(combat, "All enemies defeated. Combat ended.")
        combat["result"] = {"outcome": "victory", "message": combat.get("scenario", {}).get("victory", "Encounter complete.")}
        _award_combat_xp(combat)
    return True

def _do_item(combat, actor_id, item_id, target_id=None):
    entry = combat.get("actors", {}).get(actor_id)
    if not entry or entry.get("downed"):
        _reject_action(combat, "A downed actor cannot use an item.", actor_id)
        return False
    budget = combat.get("budgets", {}).get(actor_id, {})
    if not budget.get("action"):
        _reject_action(combat, "Action already used this turn.", actor_id)
        return False
    item = next((item for item in entry["data"].get("inventory", [])
                 if item.get("id") == item_id), None)
    if not item:
        _reject_action(combat, "That item is not in your inventory.", actor_id)
        return False
    definition = item_definition(item)
    effect_id = definition.get("effect_id")
    if not effect_id or effect_id not in SPELLS:
        _reject_action(combat, "That item has no usable effect.", actor_id)
        return False
    target_entry = combat.get("actors", {}).get(target_id) if target_id else entry
    if not target_entry:
        _reject_action(combat, "Invalid target: select an available target first.", actor_id)
        return False
    if target_entry["data"].get("withdrawn"):
        _reject_action(combat, "That character has left the fight.", target_id)
        return False
    los = _line_of_sight(entry, target_entry, combat.get("arena"))
    hp_before = _capture_hp(combat)
    result = resolve_spell(effect_id, entry["data"], [target_entry["data"]],
                           line_of_sight=los, from_consumable=True)
    if not result.get("success"):
        _reject_action(combat, result.get("message", "Item could not be used."), target_id)
        return False
    stack_quantity = max(1, int(item.get("quantity", 1)))
    if stack_quantity > 1:
        item["quantity"] = stack_quantity - 1
    else:
        entry["data"]["inventory"].remove(item)
        quick_items = entry["data"].setdefault("quick_items", {})
        for key, quick_item in list(quick_items.items()):
            if quick_item == item_id:
                quick_items[key] = None
    budget["action"] = False
    for outcome in result.get("results", []):
        healing = sum(effect.get("amount", 0) for effect in outcome.get("effects", [])
                      if effect.get("kind") == "healing")
        _log(combat, f"{entry['data'].get('name', actor_id)} uses {definition.get('name', item.get('name'))} on {outcome['target']} ({healing} HP restored).")
    for current in combat["actors"].values():
        current["downed"] = bool(current["data"].get("downed", False)
                                  or current["data"].get("current_hp", 1) <= 0)
    _remove_downed_from_order(combat)
    _restore_revived_order(combat)
    _animate_hp_changes(combat, hp_before)
    return True

def _use_item_outside_combat(owner, item_id, target_id, local_player_id, remote_players):
    inventory = owner.get("inventory", []) if isinstance(owner, dict) else owner.inventory
    item = next((item for item in inventory if item.get("id") == item_id), None)
    if not item:
        return False
    definition = item_definition(item)
    effect_id = definition.get("effect_id")
    if not effect_id or effect_id not in SPELLS:
        return False
    owner_id = owner.get("id") if isinstance(owner, dict) else owner.id
    target = owner if target_id is None or target_id in (owner_id, local_player_id) else None
    if target is None:
        target = next((remote.get("actor") for remote in remote_players
                       if _player_id(remote) == target_id and remote.get("actor")), None)
    if target is None:
        return False
    caster_data = vars(owner) if not isinstance(owner, dict) else owner
    target_data = vars(target) if not isinstance(target, dict) else target
    arena = ARENAS.get(SCENARIOS.get(DEFAULT_SCENARIO, {}).get("arena"), {})
    was_downed = bool(target_data.get("downed") or target_data.get("current_hp", 1) <= 0)
    result = resolve_spell(effect_id, caster_data, [target_data],
                           line_of_sight=_line_of_sight(caster_data, target_data, arena),
                           from_consumable=True)
    if not result.get("success"):
        return False
    if was_downed and not target_data.get("downed") and target_data.get("current_hp", 0) > 0:
        penalty = charge_xp_penalty(target_data, 2)
        if penalty:
            target_data["last_revival_xp_penalty"] = penalty
    stack_quantity = max(1, int(item.get("quantity", 1)))
    if stack_quantity > 1:
        item["quantity"] = stack_quantity - 1
    else:
        inventory.remove(item)
        quick_items = caster_data.setdefault("quick_items", {})
        for key, quick_item in list(quick_items.items()):
            if quick_item == item_id:
                quick_items[key] = None
    if not isinstance(owner, dict):
        owner.current_hp = caster_data.get("current_hp", owner.current_hp)
        owner.downed = caster_data.get("downed", owner.downed)
    if not isinstance(target, dict):
        target.current_hp = target_data.get("current_hp", target.current_hp)
        target.downed = target_data.get("downed", target.downed)
    return True

def _apply_action(combat, actor_id, action):
    action_type = action.get("type")
    if action_type == "attack":
        _do_attack(combat, actor_id, action.get("target"))
    elif action_type == "ranged_attack":
        _do_attack(combat, actor_id, action.get("target"), attack_mode="ranged")
    elif action_type == "throw":
        _do_attack(combat, actor_id, action.get("target"), attack_mode="throw")
    elif action_type == 'cast_spell':
        _do_spell(combat, actor_id, action.get('spell'), action.get('target'))
    elif action_type == 'use_ability':
        _do_ability(combat, actor_id, action.get('ability'), action.get('target'))
    elif action_type == "use_item":
        _do_item(combat, actor_id, action.get("item"), action.get("target"))
    elif action_type == "equip_item":
        entry = combat["actors"].get(actor_id)
        if entry:
            equip_item(entry["data"], action.get("item"), action.get("slot"))
    elif action_type == "unequip_item":
        entry = combat["actors"].get(actor_id)
        if entry:
            unequip_item(entry["data"], action.get("slot"))
    elif action_type == "end_turn" and actor_id == _active_actor_id(combat):
        _advance_turn(combat)
    elif action_type == "move" and actor_id == _active_actor_id(combat):
        entry = combat["actors"].get(actor_id)
        if not entry or entry["downed"]:
            return
        if has_condition(entry["data"], "bound_in_briar"):
            _reject_action(combat,
                           f"{entry['data'].get('name', actor_id)} is bound in briar.",
                           actor_id)
            return
        budget = combat["budgets"][actor_id]
        arena = combat.get("arena") or ARENAS.get(
            SCENARIOS.get(combat.get("scenario_id", DEFAULT_SCENARIO), {}).get("arena"), {})
        bounds = _arena_bounds(arena)
        target_x = max(bounds.left, min(bounds.right - ACTOR_SIZE,
                                        action.get("x", entry["x"])))
        target_y = max(bounds.top, min(bounds.bottom - ACTOR_SIZE,
                                       action.get("y", entry["y"])))
        dx, dy = target_x - entry["x"], target_y - entry["y"]
        feet = math.hypot(dx, dy) / PIXELS_PER_FOOT
        if feet > budget["movement"] and feet:
            factor = budget["movement"] / feet
            dx, dy = dx * factor, dy * factor
            feet = budget["movement"]
        occupied = [
            _actor_hitbox(other["x"], other["y"])
            for other_id, other in combat["actors"].items()
            if other_id != actor_id and not other["downed"]
        ]
        dest_x, dest_y = _walk_destination(entry["x"], entry["y"], dx, dy,
                                            arena, occupied)
        traveled = math.hypot(dest_x - entry["x"], dest_y - entry["y"])
        feet = traveled / PIXELS_PER_FOOT
        old_x, old_y = entry["x"], entry["y"]
        entry["x"], entry["y"] = dest_x, dest_y
        entry["data"]["x"], entry["data"]["y"] = entry["x"], entry["y"]
        if traveled > 0:
            if dest_x != old_x:
                entry["facing_left"] = dest_x < old_x
            _emit_animation(combat, actor_id, "walk",
                            max(180, int(traveled / 5 * 1000 / 60)))
        budget["movement"] = max(0, budget["movement"] - feet)

def _resolve_party_rest(actor, local_player_id, remote_players, combat,
                        location="outdoor"):
    if combat and combat.get("active"):
        return {"_action_error": "You cannot rest while combat is active."}

    players = []
    if combat:
        for player_id, entry in combat.get("actors", {}).items():
            if entry.get("team") != "players":
                continue
            data = deepcopy(entry["data"])
            if player_id == local_player_id:
                data["x"], data["y"] = actor.x, actor.y
                target = vars(actor)
            else:
                remote = next((item for item in remote_players
                               if _player_id(item) == player_id), None)
                if not remote or not remote.get("actor"):
                    continue
                data["x"] = remote.get("x", data.get("x", 0))
                data["y"] = remote.get("y", data.get("y", 0))
                target = entry["data"]
            players.append((player_id, target, data))
    else:
        players.append((local_player_id, vars(actor), deepcopy(vars(actor))))
        for remote in remote_players:
            if remote.get("actor"):
                players.append((_player_id(remote), remote["actor"],
                                deepcopy(remote["actor"])))

    mobs = []
    if combat:
        mobs = [entry for entry in combat.get("actors", {}).values()
                if entry.get("team") == "enemies" and not entry.get("downed")]
    else:
        scenario = SCENARIOS.get(DEFAULT_SCENARIO, {})
        for index, spawn in enumerate(scenario.get("enemies", [])):
            definition = NPCS.get(spawn.get("npc"))
            if not definition:
                continue
            mob_data = deepcopy(definition)
            mob_data.update(x=spawn.get("x", mob_data.get("x", 0)),
                            y=spawn.get("y", mob_data.get("y", 0)))
            mobs.append(_combat_snapshot(
                spawn.get("id", f"{spawn.get('npc')}-{index + 1}"),
                mob_data, "enemies"))

    arena = (combat.get("arena") if combat else None) or ARENAS.get(
        SCENARIOS.get(DEFAULT_SCENARIO, {}).get("arena"), {})
    beds = arena.get("inn_beds", [])
    bed = beds[0] if beds else None
    prepared = []
    for player_id, target, data in players:
        if location == "inn":
            if not bed:
                return {"_action_error": "There is no inn bed in this area."}
            distance_to_bed = edge_distance_feet(
                data, bed, PIXELS_PER_FOOT, ACTOR_SIZE)
            if distance_to_bed > int(bed.get("interaction_range_feet", 5)):
                return {"_action_error": f"Move within {bed.get('interaction_range_feet', 5)} feet of the inn bed to rest."}
        distances = [edge_distance_feet(data, mob, PIXELS_PER_FOOT, ACTOR_SIZE)
                     for mob in mobs]
        nearest_enemy = min(distances) if distances else float("inf")
        result = resolve_rest(
            data, location, distance_to_nearest_enemy_feet=nearest_enemy)
        if not result.get("success"):
            return {"_action_error": result.get("reason", "Rest failed.")}
        prepared.append((player_id, target, data, result))

    total_cost = 0
    for player_id, target, data, result in prepared:
        total_cost += result.get("xp_cost" if location == "outdoor" else "gold_cost", 0)
        if isinstance(target, dict):
            target.update(data)
        else:
            vars(target).update(data)
        if combat and player_id in combat.get("actors", {}):
            combat["actors"][player_id]["data"].update(data)
    if combat:
        cost_label = "XP" if location == "outdoor" else "gold"
        _log(combat, f"The party rests at {'camp' if location == 'outdoor' else 'the inn'}. {total_cost} {cost_label} spent.")
    if location == "outdoor":
        notice = f"Outdoor rest complete. {total_cost} XP spent; spell and class pools replenished."
    else:
        notice = f"Inn rest complete. {total_cost} gold spent; spell and class pools replenished."
    if combat:
        return {"_action_notice": notice}
    sync_state = _progression_sync_state(actor, local_player_id, remote_players)
    sync_state["_action_notice"] = notice
    return sync_state

def _run_ai_turns(combat):
    """Run non-player controllers on the authoritative host."""
    max_actions = max(1, len(combat.get("order", [])) * 3)
    for _ in range(max_actions):
        if not combat or not combat.get("active"):
            return
        actor_id = _active_actor_id(combat)
        if actor_id is None:
            return
        entry = combat["actors"][actor_id]
        if entry["data"].get("controller", "player") != "ai":
            return
        brain = controller_for(entry["data"])
        actions = brain.actions_for_turn({
            "combat": combat,
            "actor_id": actor_id,
            "pixels_per_foot": PIXELS_PER_FOOT,
        })
        if not actions:
            _advance_turn(combat)
            continue
        for action in actions:
            if _active_actor_id(combat) != actor_id:
                break
            _apply_action(combat, actor_id, action)
