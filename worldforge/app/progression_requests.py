"""Character progression, trainer purchases, and downed character requests."""
from copy import deepcopy

from worldforge.app.combat_flow import _log, _remove_downed_from_order
from worldforge.app.encounters import DEFAULT_SCENARIO, _progression_sync_state
from worldforge.app.rendering import _player_id
from worldforge.content.classes import (ABILITIES, ARENAS, CLASSES, SCENARIOS,
                                        SPELLS, SUBCLASSES, skill_options,
                                        subclass_feature_items)
from worldforge.core.progression import (adjusted_purchase_cost, apply_level_up,
    charge_xp_penalty, class_feature_definition, class_unlock_cost,
    class_unlocked_level, initialize_resources, qualified_level,
    set_spell_prepared, spend_attribute_point, spend_xp, sync_progression_levels,
    unspent_xp, unlocked_classes)


def handle_progression_action(actor, local_player_id, actor_id, action,
                              remote_players, combat):
    action_type = action.get("type")
    if action_type not in {"increase_ability", "prepare_spell",
                           "trainer_purchase", "unlock_class", "level_up",
                           "release_spirit"}:
        return None
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
    if action.get("type") in {"trainer_purchase", "unlock_class", "level_up",
                               "release_spirit"}:
        if combat and combat.get("active") and action.get("type") in {
                "trainer_purchase", "unlock_class", "level_up"}:
            return {"_action_error": "You cannot train during combat."}
        entry = (combat or {}).get("actors", {}).get(actor_id)
        owner = (entry.get("data") if entry else
                 (actor if actor_id == local_player_id else next(
                     (remote.get("actor") for remote in remote_players
                      if _player_id(remote) == actor_id and remote.get("actor")), None)))
        if owner is None:
            return {"_action_error": "Character is unavailable."}
        data = owner if isinstance(owner, dict) else vars(owner)
        if action["type"] == "level_up":
            success, message = apply_level_up(data, action.get("class_id"))
            if not success:
                return {"_action_error": message}
            if entry:
                entry["data"].update(data)
                entry["max_hp"] = data.get("max_hp", entry.get("max_hp", 1))
                if not isinstance(owner, dict):
                    owner.max_hp = data["max_hp"]
                    owner.current_hp = data["current_hp"]
                    owner.level = data["level"]
                    owner.classes = deepcopy(data.get("classes", []))
                _log(combat, message)
                return combat
            if not isinstance(owner, dict):
                owner.max_hp = data["max_hp"]
                owner.current_hp = data["current_hp"]
                owner.level = data["level"]
                owner.classes = deepcopy(data.get("classes", []))
            synced = _progression_sync_state(actor, local_player_id, remote_players)
            synced["_action_notice"] = message
            return synced
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
            if class_id not in unlocked_classes(data):
                return {"_action_error": "Unlock this class before buying its options."}
            if kind in {"feature", "subclass feature"}:
                if kind == "feature":
                    feature = next((
                        {**feature, "prerequisite_class_level": int(tier_key)}
                        for tier_key, features in
                        (CLASSES.get(class_id, {}).get("progression", {}) or {}).items()
                        for feature in (features or [])
                        if feature.get("id") == item_id), None)
                else:
                    subclass_id = data.get("subclass")
                    subclass = SUBCLASSES.get(subclass_id, {})
                    if subclass.get("class") != class_id:
                        subclass = {}
                    feature = next((
                        {**feature, "prerequisite_class_level": int(tier)}
                        for tier, purchase_id, feature in subclass_feature_items(subclass_id)
                        if purchase_id == item_id), None)
                if not feature:
                    return {"_action_error": "That class feature is unavailable."}
                definition = class_feature_definition(class_id, feature)
                purchase_key, owned_key = "class_feature_purchases", "class_features"
            elif kind == "skill":
                if item_id not in {str(value).casefold() for value in skill_options(class_id)}:
                    return {"_action_error": "That skill is unavailable to this class."}
                definition = {
                    "name": item_id.title(), "classes": [class_id],
                    "prerequisite_class_level": 1,
                    "acquisition": "trainer_purchase", "xp_purchase_cost": 10,
                }
                purchase_key, owned_key = "class_skill_purchases", "skills"
                skill_limit = max(0, int(CLASSES[class_id].get("skill_choices", 0) or 0))
                already_purchased = data.get(purchase_key, {}).get(class_id, [])
                if (item_id in {str(value).casefold() for value in data.get("skills", [])}
                        or len(already_purchased) >= skill_limit):
                    return {"_action_error": "That skill is already trained or your class training slots are full."}
            else:
                table = SPELLS if kind == "spell" else ABILITIES if kind == "ability" else {}
                definition = table.get(item_id)
                if (not definition or class_id not in definition.get("classes", [])
                        or definition.get("acquisition") != "trainer_purchase"):
                    return {"_action_error": "That trainer option is unavailable."}
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
            if kind == "skill":
                data[owned_key] = sorted({str(value).casefold()
                                          for value in data[owned_key]})
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
        bed = next(iter(arena.get("inn_beds", [])), None)
        respawn = SCENARIOS.get(
            (combat or {}).get("scenario_id", DEFAULT_SCENARIO), {}).get(
                "respawn_point", [130, 170])
        if bed:
            data["x"] = int(bed.get(
                "respawn_x", bed.get("x", 130) + bed.get("width", 100) + 12))
            data["y"] = int(bed.get(
                "respawn_y", bed.get("y", 170) + bed.get("height", 60) + 12))
        else:
            data["x"], data["y"] = map(int, respawn)
        if not isinstance(owner, dict):
            owner.x, owner.y, owner.downed = data["x"], data["y"], False
            owner.current_hp, owner.withdrawn = data["current_hp"], True
        if entry:
            entry["x"], entry["y"], entry["downed"] = data["x"], data["y"], False
            if actor_id == local_player_id:
                actor.x, actor.y = data["x"], data["y"]
                actor.current_hp, actor.downed, actor.withdrawn = data["current_hp"], False, True
            _remove_downed_from_order(combat)
            destination = "the inn" if bed else "a safe place nearby"
            _log(combat, f"{data.get('name', 'Actor')} releases their spirit and returns to {destination}, losing {penalty} XP.")
        return combat or _progression_sync_state(
            actor, local_player_id, remote_players)
