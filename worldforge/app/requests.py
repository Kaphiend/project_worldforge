"""Route and validate host-side gameplay requests."""
from copy import deepcopy
from worldforge.content.classes import ARENAS, SCENARIOS
from worldforge.actors.factory import equip_item, unequip_item
from worldforge.app.actions import _apply_action
from worldforge.app.attack_actions import _do_attack
from worldforge.app.combat_flow import (
    _active_actor_id, _advance_turn, _log, _reject_action,
)
from worldforge.app.encounters import (DEFAULT_SCENARIO, _combat_snapshot,
    _new_combat, _progression_sync_state, combat_world_mobs)
from worldforge.app.rendering import _player_id
from worldforge.app.travel import travel_party_through_exit
from worldforge.app.commerce import _vendor_action
from worldforge.app.rest_flow import (_book_inn_bed, _camp_bed_checkin, _leave_camp, _start_camp,
                                      _start_inn_checkin)
from worldforge.app.loot_actions import handle_loot_action
from worldforge.app.progression_requests import handle_progression_action
from worldforge.app.item_actions import _use_item_outside_combat
from worldforge.app.storage_actions import handle_storage_action
from worldforge.app.spell_actions import _do_ability, _do_spell
from worldforge.content.campaign import system_enabled

def _handle_action_request(actor, local_player_id, actor_id, action,
                           remote_players, combat, vendor_state=None):
    action_type = action.get("type")
    if (action_type in {"attack", "unarmed_strike", "ranged_attack", "offhand_attack", "throw",
                        "cast_spell", "use_ability"}
            and not system_enabled("combat")):
        return {"_action_error": "Combat is disabled in the active campaign."}
    if (action_type in {"vendor_buy", "vendor_sell", "vendor_buyback"}
            and not system_enabled("vendors")):
        return {"_action_error": "Vendors are disabled in the active campaign."}
    if (action_type in {"trainer_purchase", "unlock_class", "level_up",
                        "choose_expertise", "choose_weapon_mastery",
                        "choose_fighting_style"}
            and not system_enabled("training")):
        return {"_action_error": "Training is disabled in the active campaign."}
    if (action_type in {"rest_outdoor", "rest_camp_checkin", "inn_book_bed",
                        "rest_inn", "rest_inn_checkin", "leave_camp"}
            and not system_enabled("resting")):
        return {"_action_error": "Resting is disabled in the active campaign."}
    if action_type in {"travel_exit", "leave_camp"} and not system_enabled("travel"):
        return {"_action_error": "Travel is disabled in the active campaign."}
    if (isinstance(action_type, str) and action_type.startswith("storage_")
            and not system_enabled("personal_storage")):
        return {"_action_error": "Personal storage is disabled in the active campaign."}
    if ((isinstance(action_type, str) and action_type.startswith("loot_"))
            or action_type == "pickup_ground_item") and not system_enabled("loot"):
        return {"_action_error": "Loot is disabled in the active campaign."}
    if action.get("type") in {"vendor_buy", "vendor_sell", "vendor_buyback"}:
        return _vendor_action(actor, local_player_id, actor_id, action,
                              remote_players, combat, vendor_state)
    storage_result = handle_storage_action(actor, actor_id, action,
                                           remote_players, combat)
    if storage_result is not None:
        return storage_result
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
        return _start_camp(actor, local_player_id, remote_players, combat,
                           action.get("rest_type", "long_rest"))
    if action.get("type") == "travel_exit":
        return travel_party_through_exit(
            actor, local_player_id, actor_id, remote_players, combat,
            action.get("exit_id"))
    if action.get("type") == "rest_camp_checkin":
        return _camp_bed_checkin(
            actor, local_player_id, actor_id, remote_players, combat,
            action.get("bed_id"), action.get("hit_dice_spent"))
    if action.get("type") == "leave_camp":
        return _leave_camp(actor, local_player_id, actor_id,
                           remote_players, combat)
    if action.get("type") == "inn_book_bed":
        return _book_inn_bed(actor, local_player_id, actor_id,
                             remote_players, combat,
                             action.get("rest_type", "long_rest"))
    if action.get("type") in {"rest_inn", "rest_inn_checkin"}:
        arena = (combat or {}).get("arena") or ARENAS.get(
            SCENARIOS.get(DEFAULT_SCENARIO, {}).get("arena"), {})
        bed_id = action.get("bed_id") or next(
            (item.get("id") for item in arena.get("inn_beds", [])), None)
        return _start_inn_checkin(actor, local_player_id, actor_id,
                                  remote_players, combat, bed_id,
                                  action.get("hit_dice_spent"))
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
                           "class_features", "expertise_skills",
                           "fighting_styles",
                           "weapon_masteries", "skills",
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
        if action.get("type") == "offhand_attack":
            return {"_action_notice": "Attack with a Light weapon first to unlock the off-hand attack."}
        if action.get("type") not in {"attack", "unarmed_strike", "ranged_attack", "throw", "cast_spell", "use_ability"}:
            return combat
        previous = combat or {}
        scenario_id = previous.get("scenario_id", DEFAULT_SCENARIO)
        world_mobs = combat_world_mobs(previous)
        combat = _new_combat(actor, local_player_id, remote_players,
                             scenario_id=scenario_id,
                             world_mobs=world_mobs if previous else None)
        combat["world_areas"] = deepcopy(previous.get("world_areas", {}))
        combat["world_area_items"] = deepcopy(
            previous.get("world_area_items", {}))
        combat["world_area_chests"] = deepcopy(
            previous.get("world_area_chests", {}))
        combat["chests"] = deepcopy(previous.get(
            "chests", combat.get("chests", [])))
        combat["ground_items"] = deepcopy(previous.get("ground_items", []))
        combat["vendor_buyback"] = deepcopy(
            previous.get("vendor_buyback", {}))
        _log(combat, "Combat started.")
        action_type = action.get('type')
        resolved = (
            _do_attack(combat, actor_id, action.get('target'),
                       attack_mode={"throw": "throw", "ranged_attack": "ranged",
                                    "offhand_attack": "offhand",
                                    "unarmed_strike": "unarmed"}.get(action_type, "primary"),
                       cunning_strike=action.get("cunning_strike"))
            if action_type in {"attack", "unarmed_strike", "ranged_attack", "offhand_attack", "throw"} else
            _do_spell(combat, actor_id, action.get('spell'), action.get('target'),
                      action.get('slot_level'), action.get('slot_pool'))
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
    elif action.get("type") in {"attack", "ranged_attack", "offhand_attack", "throw", "cast_spell", "use_ability", "use_item", "move", "hide", "fast_hands", "flee"}:
        _reject_action(combat, "It is not your turn.", action.get("target") or actor_id)
    return combat
