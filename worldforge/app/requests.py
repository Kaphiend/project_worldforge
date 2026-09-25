"""Host-side party synchronization and validated action requests."""
from copy import deepcopy
import pygame
from worldforge.combat.rules import initiative_for
from worldforge.content.classes import ARENAS, SCENARIOS
from worldforge.actors.factory import equip_item, unequip_item
from worldforge.app.actions import _apply_action
from worldforge.app.attack_actions import _do_attack
from worldforge.app.combat_flow import (
    _active_actor_id, _advance_turn, _log, _reject_action,
)
from worldforge.app.encounters import (CORPSE_DESPAWN_MS, DEFAULT_SCENARIO,
    _combat_snapshot, _corpse_loot, _new_combat, _progression_sync_state,
    _random_mob_entry, _world_mob_from_entry)
from worldforge.app.world import _movement_allowance
from worldforge.app.rendering import _player_id
from worldforge.app.travel import travel_party_through_exit
from worldforge.app.commerce import _vendor_action
from worldforge.app.rest_flow import (_camp_bed_checkin, _start_camp,
                                      _start_inn_checkin)
from worldforge.app.loot_actions import handle_loot_action
from worldforge.app.progression_requests import handle_progression_action
from worldforge.app.item_actions import _use_item_outside_combat
from worldforge.app.spell_actions import _do_ability, _do_spell

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
            entry["loot"] = _corpse_loot(entry)
            # Empty corpses have nothing for the player to interact with, so
            # begin their normal despawn countdown as soon as combat settles.
            entry["corpse_despawn_at"] = (
                pygame.time.get_ticks() + CORPSE_DESPAWN_MS
                if not entry["loot"] else None)
    arena = combat.get("arena", {})
    existing = [entry for entry in combat.get("actors", {}).values()
                if entry.get("team") == "enemies"]
    mob_pool = SCENARIOS.get(combat.get("scenario_id"), {}).get("mob_pool")
    fresh = _random_mob_entry(arena, existing, players, mob_pool)
    if fresh:
        combat["actors"][fresh["id"]] = fresh
        _log(combat, f"A new {fresh['data'].get('name', 'mob')} appears elsewhere on the map.")
    else:
        _log(combat, "The defeated mob remains here; no clear spawn point was found.")
    combat["order"] = []
    combat["budgets"] = {}
    combat["turn_index"] = 0
    combat["ability_uses"] = {}


def _handle_action_request(actor, local_player_id, actor_id, action,
                           remote_players, combat, vendor_state=None):
    if action.get("type") in {"vendor_buy", "vendor_sell", "vendor_buyback"}:
        return _vendor_action(actor, local_player_id, actor_id, action,
                              remote_players, combat, vendor_state)
    loot_result = handle_loot_action(
        actor, local_player_id, actor_id, action, remote_players, combat)
    if loot_result is not None:
        return loot_result
    progression_result = handle_progression_action(
        actor, local_player_id, actor_id, action, remote_players, combat)
    if progression_result is not None:
        return progression_result
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
        return _start_camp(actor, local_player_id, remote_players, combat)
    if action.get("type") == "travel_exit":
        return travel_party_through_exit(
            actor, local_player_id, actor_id, remote_players, combat,
            action.get("exit_id"))
    if action.get("type") == "rest_camp_checkin":
        return _camp_bed_checkin(
            actor, local_player_id, actor_id, remote_players, combat,
            action.get("bed_id"))
    if action.get("type") in {"rest_inn", "rest_inn_checkin"}:
        arena = (combat or {}).get("arena") or ARENAS.get(
            SCENARIOS.get(DEFAULT_SCENARIO, {}).get("arena"), {})
        bed_id = action.get("bed_id") or next(
            (item.get("id") for item in arena.get("inn_beds", [])), None)
        return _start_inn_checkin(actor, local_player_id, actor_id,
                                  remote_players, combat, bed_id)
    if not combat or not combat.get("active"):
        if action.get("type") == "flee":
            return {"_action_notice": "There is no combat to flee from."}
        if action.get("type") == "hide":
            return {"_action_notice": "Use K to sneak while exploring. Hide is a combat action."}
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
                                          local_player_id, remote_players,
                                          (combat or {}).get("arena"))
            if combat:
                changed = {"inventory", "equipment", "current_hp", "downed",
                           "xp_total", "xp_spent_by_level", "level", "classes",
                           "class_spell_purchases", "class_ability_purchases",
                           "class_feature_purchases", "class_skill_purchases",
                           "class_features", "skills",
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
        if action.get("type") == "fast_hands":
            return {"_action_notice": "Fast Hands is available during combat."}
        if action.get("type") not in {"attack", "unarmed_strike", "ranged_attack", "throw", "cast_spell", "use_ability"}:
            return combat
        previous = combat or {}
        scenario_id = previous.get("scenario_id", DEFAULT_SCENARIO)
        world_mobs = [_world_mob_from_entry(entry)
                      for entry in previous.get("actors", {}).values()
                      if entry.get("team") == "enemies"]
        combat = _new_combat(actor, local_player_id, remote_players,
                             scenario_id=scenario_id,
                             world_mobs=world_mobs if previous else None)
        combat["world_areas"] = deepcopy(previous.get("world_areas", {}))
        combat["world_area_items"] = deepcopy(
            previous.get("world_area_items", {}))
        combat["ground_items"] = deepcopy(previous.get("ground_items", []))
        combat["vendor_buyback"] = deepcopy(
            previous.get("vendor_buyback", {}))
        _log(combat, "Combat started.")
        action_type = action.get('type')
        resolved = (
            _do_attack(combat, actor_id, action.get('target'),
                       attack_mode={"throw": "throw", "ranged_attack": "ranged",
                                    "unarmed_strike": "unarmed"}.get(action_type, "primary"))
            if action_type in {"attack", "unarmed_strike", "ranged_attack", "throw"} else
            _do_spell(combat, actor_id, action.get('spell'), action.get('target'))
            if action_type == 'cast_spell' else
            _do_ability(combat, actor_id, action.get('ability'), action.get('target'))
            if action_type == 'use_ability' else
            False
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
    elif action.get("type") in {"attack", "ranged_attack", "throw", "cast_spell", "use_ability", "use_item", "move", "hide", "fast_hands", "flee"}:
        _reject_action(combat, "It is not your turn.", action.get("target") or actor_id)
    return combat
