"""Host-side party synchronization and validated action requests."""
from copy import deepcopy
import uuid
import pygame
from worldforge.combat.rules import edge_distance_feet, initiative_for
from worldforge.content.classes import ABILITIES, CLASSES, SPELLS, ARENAS, SCENARIOS
from worldforge.actors.factory import equip_item, item_definition, unequip_item
from worldforge.core.progression import initialize_resources, class_unlocked_level, qualified_level, unspent_xp, spend_xp, charge_xp_penalty, sync_progression_levels, set_spell_prepared, class_unlock_cost, unlocked_classes, adjusted_purchase_cost, spend_attribute_point
from worldforge.app.actions import _active_actor_id, _advance_turn, _apply_action, _do_ability, _do_attack, _do_spell, _log, _remove_downed_from_order, _reject_action, _resolve_party_rest, _use_item_outside_combat
from worldforge.app.encounters import CORPSE_DESPAWN_MS, DEFAULT_SCENARIO, _combat_snapshot, _corpse_loot, _new_combat, _progression_sync_state, _random_mob_entry
from worldforge.app.world import ACTOR_SIZE, PIXELS_PER_FOOT, _movement_allowance
from worldforge.app.rendering import _player_id

def _add_joined_players(combat, remote_players):
    """Add players who accept an invite after combat has already begun."""
    additions = []
    for remote in remote_players:
        actor_data = remote.get('actor')
        actor_id = _player_id(remote)
        if not actor_data or actor_id in combat['actors']:
            continue
        entry = _combat_snapshot(actor_id, actor_data, 'players')
        combat['actors'][actor_id] = entry
        combat['budgets'][actor_id] = {
            'movement': _movement_allowance(entry['data']), 'action': True,
            'bonus_action': True, 'skip_next': False,
            'condition_tick_done': False,
        }
        additions.append(actor_id)
    if not additions:
        return

    active_id = _active_actor_id(combat)
    eligible = {actor_id: entry for actor_id, entry in combat['actors'].items()
                if not entry['downed']}
    rolls = {entry['id']: {key: entry[key] for key in ('total', 'natural', 'dexterity')}
             for entry in combat['order']}
    for actor_id in additions:
        if actor_id in eligible:
            rolls[actor_id] = initiative_for(eligible[actor_id]['data'])
    while True:
        tied = set()
        by_roll = {}
        for actor_id, roll in rolls.items():
            by_roll.setdefault((roll['total'], roll['dexterity']), []).append(actor_id)
        for group in by_roll.values():
            if len(group) > 1:
                tied.update(group)
        if not tied:
            break
        for actor_id in tied:
            rolls[actor_id] = initiative_for(eligible[actor_id]['data'])
    combat['order'] = [
        {'id': actor_id, **roll}
        for actor_id, roll in sorted(
            rolls.items(), key=lambda pair: (pair[1]['total'], pair[1]['dexterity']),
            reverse=True)
    ]
    if active_id in [entry['id'] for entry in combat['order']]:
        combat['turn_index'] = next(
            index for index, entry in enumerate(combat['order'])
            if entry['id'] == active_id)
    for actor_id in additions:
        _log(combat, f"{combat['actors'][actor_id]['data'].get('name', actor_id)} joins the party.")

def _remove_disconnected_players(combat, remote_players, host_id):
    connected = {_player_id(remote) for remote in remote_players}
    active_id = _active_actor_id(combat)
    old_index = combat.get('turn_index', 0)
    removed = [
        actor_id for actor_id, entry in combat['actors'].items()
        if entry['team'] == 'players' and actor_id != host_id
        and actor_id not in connected
    ]
    for actor_id in removed:
        name = combat['actors'][actor_id]['data'].get('name', actor_id)
        combat['actors'].pop(actor_id, None)
        combat['budgets'].pop(actor_id, None)
        combat.setdefault('removed_order', {}).pop(actor_id, None)
        combat['order'] = [entry for entry in combat['order']
                           if entry['id'] != actor_id]
        _log(combat, f"{name} disconnected and left the party.")
    if not any(entry['team'] == 'players' for entry in combat['actors'].values()):
        combat['active'] = False
        return
    remaining_ids = [entry['id'] for entry in combat['order']]
    if active_id in remaining_ids:
        combat['turn_index'] = remaining_ids.index(active_id)
    elif remaining_ids:
        combat['turn_index'] = min(old_index, len(remaining_ids) - 1)
    else:
        combat['active'] = False

def _settle_victory(combat, players):
    """Leave corpses in-world and immediately add the next random mob."""
    if (not combat or not combat.get("result")
            or combat["result"].get("outcome") != "victory"
            or combat.get("victory_settled")):
        return
    combat["victory_settled"] = True
    combat["active"] = False
    combat["result"] = None
    for entry in combat.get("actors", {}).values():
        if (entry.get("team") == "enemies" and entry.get("downed")
                and entry.get("corpse_despawn_at") is None):
            entry["corpse_despawn_at"] = None
            entry["loot"] = _corpse_loot(entry)
    arena = combat.get("arena", {})
    existing = [entry for entry in combat.get("actors", {}).values()
                if entry.get("team") == "enemies"]
    fresh = _random_mob_entry(arena, existing, players)
    if fresh:
        combat["actors"][fresh["id"]] = fresh
        _log(combat, f"A new {fresh['data'].get('name', 'mob')} appears elsewhere on the map.")
    else:
        _log(combat, "The defeated mob remains here; no clear spawn point was found.")
    combat["order"] = []
    combat["budgets"] = {}
    combat["turn_index"] = 0
    combat["ability_uses"] = {}

def _handle_action_request(actor, local_player_id, actor_id, action, remote_players, combat):
    if action.get("type") == "chat":
        speaker = (actor if actor_id == local_player_id else next(
            (remote.get("actor") for remote in remote_players
             if _player_id(remote) == actor_id), None))
        speaker_data = vars(speaker) if hasattr(speaker, "__dict__") else speaker or {}
        name = speaker_data.get("name", "Actor")
        text = str(action.get("text", "")).strip()[:160]
        if text.lower().startswith("/act "):
            emote = text[5:].strip()
            if emote and combat is not None:
                _log(combat, f"{name} acts {emote}.")
        return combat
    if action.get("type") == "rest_outdoor":
        return _resolve_party_rest(actor, local_player_id, remote_players,
                                   combat, "outdoor")
    if action.get("type") == "rest_inn":
        return _resolve_party_rest(actor, local_player_id, remote_players,
                                   combat, "inn")
    if action.get("type") == "increase_ability":
        entry = (combat or {}).get("actors", {}).get(actor_id)
        owner = (entry.get("data") if entry else
                 (actor if actor_id == local_player_id else next(
                     (remote.get("actor") for remote in remote_players
                      if _player_id(remote) == actor_id and remote.get("actor")), None)))
        if owner is None:
            return {"_action_error": "Character is unavailable."}
        data = owner if isinstance(owner, dict) else vars(owner)
        success, message = spend_attribute_point(data, action.get("ability"))
        if not success:
            return {"_action_error": message}
        if entry:
            entry["data"].update(data)
            return combat
        return _progression_sync_state(actor, local_player_id, remote_players)
    if action.get("type") == "prepare_spell":
        entry = (combat or {}).get("actors", {}).get(actor_id)
        owner = (entry.get("data") if entry else
                 (actor if actor_id == local_player_id else next(
                     (remote.get("actor") for remote in remote_players
                      if _player_id(remote) == actor_id and remote.get("actor")), None)))
        if owner is None:
            return {"_action_error": "Character is unavailable."}
        data = owner if isinstance(owner, dict) else vars(owner)
        success, message = set_spell_prepared(
            data, action.get("spell_id"), bool(action.get("prepare", True)))
        if not success:
            return {"_action_error": message}
        if entry:
            entry["data"].update(data)
            return combat
        return _progression_sync_state(actor, local_player_id, remote_players)
    if action.get("type") in {"loot_take", "loot_take_all", "loot_finish"}:
        if not combat or combat.get("active"):
            return {"_action_error": "There is no corpse available to loot."}
        corpse_id = action.get("target")
        corpse = combat.get("actors", {}).get(corpse_id)
        if (not corpse or corpse.get("team") != "enemies"
                or not corpse.get("downed")):
            return {"_action_error": "That corpse is no longer available."}
        now = pygame.time.get_ticks()
        expiry = corpse.get("corpse_despawn_at")
        if expiry is not None and now >= expiry:
            return {"_action_error": "That corpse has already been looted and is gone."}
        player_entry = combat.get("actors", {}).get(actor_id)
        owner = (player_entry.get("data") if player_entry else
                 (actor if actor_id == local_player_id else next(
                     (remote.get("actor") for remote in remote_players
                      if _player_id(remote) == actor_id and remote.get("actor")), None)))
        if owner is None:
            return {"_action_error": "Character is unavailable."}
        data = owner if isinstance(owner, dict) else vars(owner)
        if actor_id == local_player_id:
            loot_x, loot_y = actor.x, actor.y
        else:
            remote = next((item for item in remote_players
                           if _player_id(item) == actor_id), {})
            loot_x, loot_y = remote.get("x", data.get("x", 0)), remote.get("y", data.get("y", 0))
        loot_position = {"x": loot_x, "y": loot_y,
                         "width": ACTOR_SIZE, "height": ACTOR_SIZE}
        distance = edge_distance_feet(loot_position, corpse,
                                      PIXELS_PER_FOOT, ACTOR_SIZE)
        if distance > 5:
            return {"_action_error": "Move within 5 feet of the corpse to loot it."}

        loot = corpse.setdefault("loot", [])
        if action["type"] in {"loot_take", "loot_take_all"}:
            if action["type"] == "loot_take_all":
                claimed = list(loot)
                loot.clear()
            else:
                item_id = action.get("item_id")
                item = next((item for item in loot if item.get("id") == item_id), None)
                if item is None:
                    return {"_action_error": "That item has already been taken."}
                claimed = [item]
                loot.remove(item)
            inventory = data.setdefault("inventory", [])
            for item in claimed:
                definition = item_definition(item)
                template_id = item.get("template_id")
                quantity = max(1, int(item.get("quantity", 1) or 1))
                if definition.get("stackable") and template_id:
                    max_stack = max(1, int(definition.get("max_stack", 99)))
                    remaining = quantity
                    for existing in inventory:
                        if existing.get("template_id") != template_id:
                            continue
                        current = max(1, int(existing.get("quantity", 1) or 1))
                        added = min(remaining, max(0, max_stack - current))
                        existing["quantity"] = current + added
                        remaining -= added
                        if not remaining:
                            break
                    while remaining:
                        added = min(remaining, max_stack)
                        copy_item = deepcopy(item)
                        copy_item["id"] = uuid.uuid4().hex[:12]
                        copy_item["quantity"] = added
                        inventory.append(copy_item)
                        remaining -= added
                else:
                    inventory.append(deepcopy(item))
            if player_entry:
                player_entry["data"].update(data)
            for item in claimed:
                _log(combat, f"{data.get('name', actor_id)} takes {item.get('name', 'an item')} from the shared loot.")
            if action["type"] == "loot_take_all":
                corpse["corpse_despawn_at"] = now + CORPSE_DESPAWN_MS
            return combat

        if corpse.get("corpse_despawn_at") is None:
            corpse["corpse_despawn_at"] = now + CORPSE_DESPAWN_MS
        _log(combat, f"Looting {corpse.get('data', {}).get('name', 'the corpse')} ends.")
        return combat
    if action.get("type") in {"trainer_purchase", "unlock_class", "release_spirit"}:
        if combat and combat.get("active") and action.get("type") in {
                "trainer_purchase", "unlock_class"}:
            return {"_action_error": "You cannot train during combat."}
        entry = (combat or {}).get("actors", {}).get(actor_id)
        owner = (entry.get("data") if entry else
                 (actor if actor_id == local_player_id else next(
                     (remote.get("actor") for remote in remote_players
                      if _player_id(remote) == actor_id and remote.get("actor")), None)))
        if owner is None:
            return {"_action_error": "Character is unavailable."}
        data = owner if isinstance(owner, dict) else vars(owner)
        if action["type"] == "unlock_class":
            class_id = action.get("class_id")
            if class_id not in CLASSES:
                return {"_action_error": "That class is unavailable."}
            if class_id in unlocked_classes(data):
                return {"_action_notice": "That class is already unlocked."}
            cost = class_unlock_cost(data, class_id)
            if cost > unspent_xp(data):
                return {"_action_error": f"Not enough unspent XP ({cost} required)."}
            if not spend_xp(data, cost):
                return {"_action_error": "Could not spend XP for the class unlock."}
            data.setdefault("classes", []).append({"name": class_id, "level": 1})
            sync_progression_levels(data)
            initialize_resources(data)
            if entry:
                entry["data"].update(data)
            return combat or _progression_sync_state(
                actor, local_player_id, remote_players)
        if action["type"] == "trainer_purchase":
            class_id = action.get("class_id")
            kind, item_id = action.get("kind"), action.get("item_id")
            table = SPELLS if kind == "spell" else ABILITIES if kind == "ability" else {}
            definition = table.get(item_id)
            if (not definition or class_id not in definition.get("classes", [])
                    or definition.get("acquisition") != "trainer_purchase"):
                return {"_action_error": "That trainer option is unavailable."}
            if class_id not in unlocked_classes(data):
                return {"_action_error": "Unlock this class before buying its options."}
            purchase_key = ("class_spell_purchases" if kind == "spell"
                            else "class_ability_purchases")
            owned_key = "known_spells" if kind == "spell" else "known_abilities"
            purchases = data.setdefault(purchase_key, {})
            owned_for_class = purchases.setdefault(class_id, [])
            if item_id in owned_for_class:
                return {"_action_notice": "You already own that option."}
            tier = int(definition.get("prerequisite_class_level", 1))
            if tier > min(qualified_level(data), class_unlocked_level(data, class_id)):
                return {"_action_error": "Buy an option from each prior tier and meet its level requirement."}
            cost = adjusted_purchase_cost(data, class_id, definition)
            if cost is None:
                return {"_action_error": "This option has no XP price configured."}
            if cost > unspent_xp(data):
                return {"_action_error": f"Not enough unspent XP ({cost} required)."}
            owned_for_class.append(item_id)
            if item_id not in data.setdefault(owned_key, []):
                data[owned_key].append(item_id)
            spend_xp(data, cost)
            sync_progression_levels(data)
            if entry:
                entry["data"].update(data)
            if combat:
                _log(combat, f"{data.get('name', 'Actor')} learns {definition.get('name', item_id)} for {cost} XP.")
            return combat or _progression_sync_state(
                actor, local_player_id, remote_players)
        if not data.get("downed"):
            return {"_action_error": "You are not downed."}
        penalty = charge_xp_penalty(data, 10)
        data["downed"] = False
        data["current_hp"] = max(1, int(data.get("current_hp", 0) or 0))
        data["withdrawn"] = True
        arena = (combat or {}).get("arena") or ARENAS.get(
            SCENARIOS.get(DEFAULT_SCENARIO, {}).get("arena"), {})
        bed = next(iter(arena.get("inn_beds", [])), {})
        data["x"] = int(bed.get("respawn_x", bed.get("x", 130) + bed.get("width", 100) + 12))
        data["y"] = int(bed.get("respawn_y", bed.get("y", 170) + bed.get("height", 60) + 12))
        if not isinstance(owner, dict):
            owner.x, owner.y, owner.downed = data["x"], data["y"], False
            owner.current_hp, owner.withdrawn = data["current_hp"], True
        if entry:
            entry["x"], entry["y"], entry["downed"] = data["x"], data["y"], False
            if actor_id == local_player_id:
                actor.x, actor.y = data["x"], data["y"]
                actor.current_hp, actor.downed, actor.withdrawn = data["current_hp"], False, True
            _remove_downed_from_order(combat)
            _log(combat, f"{data.get('name', 'Actor')} releases their spirit and returns to the inn, losing {penalty} XP.")
        return combat or _progression_sync_state(
            actor, local_player_id, remote_players)
    if not combat or not combat.get("active"):
        if action.get("type") in {"equip_item", "unequip_item", "use_item"}:
            owner = actor if actor_id == local_player_id else next(
                (remote.get("actor") for remote in remote_players
                 if _player_id(remote) == actor_id and remote.get("actor")), None)
            if owner is None:
                return combat
            if action["type"] == "equip_item":
                equip_item(owner, action.get("item"), action.get("slot"))
            elif action["type"] == "unequip_item":
                unequip_item(owner, action.get("slot"))
            else:
                target_id = action.get("target")
                if target_id == actor_id:
                    target_id = owner.get("id") if isinstance(owner, dict) else owner.id
                _use_item_outside_combat(owner, action.get("item"), target_id,
                                          local_player_id, remote_players)
            if combat:
                changed = {"inventory", "equipment", "current_hp", "downed",
                           "xp_total", "xp_spent_by_level", "level", "classes",
                           "class_spell_purchases", "class_ability_purchases",
                           "known_spells", "prepared_spells", "known_abilities",
                           "withdrawn", "x", "y"}
                source = vars(owner) if not isinstance(owner, dict) else owner
                owner_entry = combat.get("actors", {}).get(actor_id)
                if owner_entry:
                    for key in changed:
                        if key in source:
                            owner_entry["data"][key] = deepcopy(source[key])
                selected_id = action.get("target")
                target_remote = next((remote.get("actor") for remote in remote_players
                                      if _player_id(remote) == selected_id and remote.get("actor")), None)
                target_entry = combat.get("actors", {}).get(selected_id)
                if target_remote and target_entry:
                    for key in changed:
                        if key in target_remote:
                            target_entry["data"][key] = deepcopy(target_remote[key])
                    target_entry["downed"] = bool(target_entry["data"].get("downed", False))
            return combat or _progression_sync_state(
                actor, local_player_id, remote_players)
        if action.get("type") not in {"attack", "ranged_attack", "throw", "cast_spell", "use_ability"}:
            return combat
        combat = _new_combat(actor, local_player_id, remote_players)
        _log(combat, "Combat started.")
        action_type = action.get('type')
        resolved = (
            _do_attack(combat, actor_id, action.get('target'),
                       attack_mode={"throw": "throw", "ranged_attack": "ranged"}.get(action_type, "primary"))
            if action_type in {"attack", "ranged_attack", "throw"} else
            _do_spell(combat, actor_id, action.get('spell'), action.get('target'))
            if action_type == 'cast_spell' else
            _do_ability(combat, actor_id, action.get('ability'), action.get('target'))
        )
        if not resolved:
            # Preserve the explanation without applying encounter spawn
            # positions to actors or leaving a failed encounter snapshot live.
            return {"_action_error": combat.get("log", ["Action failed."])[-1]}
        combat["budgets"][actor_id]["skip_next"] = True
        if combat.get("active"):
            current_id = _active_actor_id(combat)
            current = combat["actors"][current_id]
            if combat["budgets"][current_id].get("skip_next"):
                _advance_turn(combat)
        return combat
    if action.get("type") in {"equip_item", "unequip_item"}:
        entry = combat.get("actors", {}).get(actor_id)
        if entry:
            if action["type"] == "equip_item":
                equip_item(entry["data"], action.get("item"), action.get("slot"))
            else:
                unequip_item(entry["data"], action.get("slot"))
    elif actor_id == _active_actor_id(combat):
        _apply_action(combat, actor_id, action)
    elif action.get("type") in {"attack", "ranged_attack", "throw", "cast_spell", "use_ability", "use_item", "move"}:
        _reject_action(combat, "It is not your turn.", action.get("target") or actor_id)
    return combat
