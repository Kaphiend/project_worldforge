"""Character progression, trainer purchases, and downed character requests."""
from copy import deepcopy
import pygame

from worldforge.app.combat_flow import _log, _remove_downed_from_order
from worldforge.app.encounters import (DEFAULT_SCENARIO,
                                       _progression_sync_state,
                                       _scenario_world_mobs,
                                       combat_world_mobs)
from worldforge.app.party import set_remote_position
from worldforge.app.rendering import _player_id
from worldforge.content.classes import (ABILITIES, ARENAS, CLASSES, SCENARIOS,
                                        SPELLS, SUBCLASSES, skill_options,
                                        subclass_feature_items)
from worldforge.content.campaign import ACTIVE_CAMPAIGN, campaign_rule
from worldforge.combat.rules import (ROGUE_WEAPON_MASTERY,
                                     FIGHTING_STYLE_OPTIONS,
                                     weapon_mastery_eligible)
from worldforge.core.progression import (adjusted_purchase_cost, apply_level_up,
    charge_xp_penalty, class_feature_definition, class_unlock_cost,
    class_unlocked_level, initialize_resources, qualified_level,
    set_spell_prepared, spend_attribute_point, spend_xp, sync_progression_levels,
    unspent_xp, unlocked_classes, class_feature_choice_slots)


def _transport_party_to_inn(actor, local_player_id, remote_players, combat,
                            released_actor_id):
    """Move the whole party to the campaign inn when a spirit is released."""
    inn_scenario_id = next((scenario_id
                           for scenario_id in ACTIVE_CAMPAIGN["scenarios"]
                           if (ARENAS.get(SCENARIOS.get(
                               scenario_id, {}).get("arena"), {})
                               .get("innkeepers"))), None)
    if inn_scenario_id is None:
        return combat
    scenario = SCENARIOS[inn_scenario_id]
    arena = ARENAS.get(scenario.get("arena"), {})
    innkeeper = arena.get("innkeepers", [{}])[0]
    state = combat or _progression_sync_state(
        actor, local_player_id, remote_players)
    source_id = state.get("scenario_id", DEFAULT_SCENARIO)
    world_areas = state.setdefault("world_areas", {})
    if source_id != inn_scenario_id and source_id not in world_areas:
        world_areas[source_id] = combat_world_mobs(state)
        state.setdefault("world_area_items", {})[source_id] = deepcopy(
            state.get("ground_items", []))
        state.setdefault("world_area_chests", {})[source_id] = deepcopy(
            state.get("chests", []))
    world_areas.setdefault(inn_scenario_id, _scenario_world_mobs(inn_scenario_id))

    players = {player_id: entry for player_id, entry in
               state.get("actors", {}).items()
               if entry.get("team") == "players"}
    players.setdefault(local_player_id, {
        "id": local_player_id, "team": "players", "data": vars(actor),
        "downed": bool(actor.downed), "x": actor.x, "y": actor.y,
    })
    for remote in remote_players:
        if remote.get("actor"):
            player_id = _player_id(remote)
            players.setdefault(player_id, {
                "id": player_id, "team": "players",
                "data": remote["actor"] if isinstance(remote["actor"], dict)
                else vars(remote["actor"]),
                "downed": bool((remote["actor"].get("downed", False)
                                if isinstance(remote["actor"], dict)
                                else remote["actor"].downed)),
                "x": remote.get("x", 0), "y": remote.get("y", 0),
            })

    spawns = scenario.get("player_spawns", [])
    destination_mobs = world_areas[inn_scenario_id]
    state["actors"] = players
    for index, (player_id, entry) in enumerate(players.items()):
        if player_id == released_actor_id:
            x = int(innkeeper.get("x", 0) + innkeeper.get("width", 0) + 12)
            y = int(innkeeper.get("y", 0))
        else:
            x, y = spawns[index % len(spawns)] if spawns else (130, 170)
        entry["x"], entry["y"] = int(x), int(y)
        entry["data"]["x"], entry["data"]["y"] = int(x), int(y)
        entry["data"]["withdrawn"] = False
        entry["data"]["_force_position_sync"] = True
        if player_id == local_player_id:
            actor.x, actor.y = int(x), int(y)
            actor.withdrawn = False
        else:
            remote = next((item for item in remote_players
                           if _player_id(item) == player_id), None)
            if remote:
                set_remote_position(remote, int(x), int(y))
                remote_actor = remote.get("actor")
                if isinstance(remote_actor, dict):
                    remote_actor["withdrawn"] = False
                elif remote_actor is not None:
                    remote_actor.withdrawn = False
    for mob in destination_mobs:
        state["actors"][mob["id"]] = deepcopy(mob)
    state["inactive_world_mobs"] = []
    state["scenario_id"] = inn_scenario_id
    state["scenario"] = deepcopy(scenario)
    state["arena"] = deepcopy(arena)
    state.update(active=False, sync_only=True, order=[], budgets={}, turn_index=0,
                 result=None, victory_settled=False, rest_session=None,
                 rest_position_sync=True, area_changed=True)
    state["ground_items"] = deepcopy(state.get(
        "world_area_items", {}).get(inn_scenario_id, []))
    state["chests"] = deepcopy(state.get(
        "world_area_chests", {}).get(inn_scenario_id,
        arena.get("chests", [])))
    state["aggro_target_id"] = None
    state["aggro_player_id"] = None
    state["aggro_immune_until"] = pygame.time.get_ticks() + 3000
    return state


def handle_progression_action(actor, local_player_id, actor_id, action,
                              remote_players, combat):
    action_type = action.get("type")
    if action_type not in {"increase_ability", "prepare_spell", "choose_expertise",
                           "choose_weapon_mastery", "choose_fighting_style",
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
    if action_type == "choose_expertise":
        entry = (combat or {}).get("actors", {}).get(actor_id)
        owner = (entry.get("data") if entry else
                 (actor if actor_id == local_player_id else next(
                     (remote.get("actor") for remote in remote_players
                      if _player_id(remote) == actor_id and remote.get("actor")), None)))
        if owner is None:
            return {"_action_error": "Character is unavailable."}
        data = owner if isinstance(owner, dict) else vars(owner)
        class_id, skill = action.get("class_id"), str(action.get("skill", "")).casefold()
        if class_id not in unlocked_classes(data) or skill not in {
                str(value).casefold() for value in data.get("skills", []) or []}:
            return {"_action_error": "Choose a trained skill from an unlocked class."}
        owned = set(data.get("class_features", []) or [])
        owned.update(data.get("class_feature_purchases", {}).get(class_id, []))
        slots = sum(int((feature.get("effect", {}) or {}).get("count", 0) or 0)
                    for tier, features in (CLASSES.get(class_id, {}).get(
                        "progression", {}) or {}).items() for feature in features or []
                    if feature.get("id") in owned
                    and (feature.get("effect", {}) or {}).get("kind") == "expertise_choice")
        choices = data.setdefault("expertise_skills", [])
        if skill in choices:
            return {"_action_notice": "You already have Expertise in that skill."}
        if len(choices) >= slots:
            return {"_action_error": "You have no unassigned Expertise choices."}
        choices.append(skill)
        if entry:
            entry["data"].update(data)
            return combat
        return _progression_sync_state(actor, local_player_id, remote_players)
    if action_type == "choose_weapon_mastery":
        entry = (combat or {}).get("actors", {}).get(actor_id)
        owner = (entry.get("data") if entry else
                 (actor if actor_id == local_player_id else next(
                     (remote.get("actor") for remote in remote_players
                      if _player_id(remote) == actor_id and remote.get("actor")), None)))
        if owner is None:
            return {"_action_error": "Character is unavailable."}
        data = owner if isinstance(owner, dict) else vars(owner)
        class_id, weapon_id = action.get("class_id"), action.get("weapon_id")
        owned = set(data.get("class_features", []) or [])
        owned.update(data.get("class_feature_purchases", {}).get(class_id, []))
        slots = class_feature_choice_slots(data, "weapon_mastery_choice")
        masteries = data.setdefault("weapon_masteries", {})
        if (class_id not in unlocked_classes(data)
                or weapon_id not in ROGUE_WEAPON_MASTERY
                or not weapon_mastery_eligible(data, weapon_id)):
            return {"_action_error": "That weapon mastery choice is unavailable."}
        if weapon_id in masteries:
            return {"_action_notice": "That weapon already has a mastery choice."}
        if len(masteries) >= slots:
            return {"_action_error": "You have no unassigned Weapon Mastery choices."}
        masteries[weapon_id] = ROGUE_WEAPON_MASTERY[weapon_id]
        if entry:
            entry["data"].update(data)
            return combat
        return _progression_sync_state(actor, local_player_id, remote_players)
    if action_type == "choose_fighting_style":
        entry = (combat or {}).get("actors", {}).get(actor_id)
        owner = (entry.get("data") if entry else
                 (actor if actor_id == local_player_id else next(
                     (remote.get("actor") for remote in remote_players
                      if _player_id(remote) == actor_id and remote.get("actor")), None)))
        if owner is None:
            return {"_action_error": "Character is unavailable."}
        data = owner if isinstance(owner, dict) else vars(owner)
        class_id, style_id = action.get("class_id"), action.get("style_id")
        owned = set(data.get("class_features", []) or [])
        owned.update(data.get("class_feature_purchases", {}).get(class_id, []))
        slots = class_feature_choice_slots(data, "fighting_style_choice")
        styles = data.setdefault("fighting_styles", [])
        if (class_id not in unlocked_classes(data)
                or style_id not in FIGHTING_STYLE_OPTIONS):
            return {"_action_error": "That fighting style choice is unavailable."}
        if style_id in styles:
            return {"_action_notice": "You already know that fighting style."}
        if len(styles) >= slots:
            return {"_action_error": "You have no unassigned Fighting Style choices."}
        styles.append(style_id)
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
        penalty = charge_xp_penalty(
            data, campaign_rule("death_release_xp_penalty_percent", 10))
        data["downed"] = False
        data["current_hp"] = max(1, int(data.get("current_hp", 0) or 0))
        data["withdrawn"] = True
        arena = (combat or {}).get("arena") or ARENAS.get(
            SCENARIOS.get(DEFAULT_SCENARIO, {}).get("arena"), {})
        innkeeper = next(iter(arena.get("innkeepers", [])), None)
        respawn = SCENARIOS.get(
            (combat or {}).get("scenario_id", DEFAULT_SCENARIO), {}).get(
                "respawn_point", [130, 170])
        if innkeeper:
            # Place the respawn beside the keeper so the character can
            # immediately interact with them, without landing inside their
            # footprint.
            data["x"] = int(innkeeper.get("x", 0)
                            + innkeeper.get("width", 0) + 12)
            data["y"] = int(innkeeper.get("y", 0))
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
            # Releasing a spirit ends the current encounter for the party.
            # Keep enemy snapshots as world mobs, but clear their combat
            # target and briefly suppress an immediate re-aggro at the bed.
            combat["active"] = False
            combat["result"] = None
            combat["order"] = []
            combat["budgets"] = {}
            combat["turn_index"] = 0
            combat["aggro_target_id"] = None
            combat["aggro_player_id"] = None
            combat["aggro_immune_until"] = pygame.time.get_ticks() + 3000
            for enemy in combat.get("actors", {}).values():
                if enemy.get("team") == "enemies":
                    enemy.get("data", {}).pop("hidden", None)
            # The next encounter snapshot clears withdrawn for all players.
            # Keep the respawned player available for its trigger check too.
            data["withdrawn"] = False
            if actor_id == local_player_id:
                actor.withdrawn = False
        combat = _transport_party_to_inn(
            actor, local_player_id, remote_players, combat, actor_id)
        if combat:
            _log(combat, (f"{data.get('name', 'Actor')} releases their spirit. "
                          f"The party returns to the inn, losing {penalty} XP."))
        return combat or _progression_sync_state(
            actor, local_player_id, remote_players)
