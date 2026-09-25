"""Host-owned world and combat updates performed once per frame."""
from copy import deepcopy

import pygame

from worldforge.app.actor_sync import _sync_local_actor
from worldforge.app.actions import _run_ai_turns
from worldforge.app.combat_flow import _log, _process_turn_start
from worldforge.app.encounters import (
    COMBAT_TRIGGER_RANGE_FEET,
    DEFAULT_SCENARIO,
    _combat_snapshot,
    _combat_trigger,
    _new_combat,
    advance_world_mob_patrol,
    combat_world_mobs,
    settle_victory,
)
from worldforge.app.party import add_joined_players, remove_disconnected_players
from worldforge.app.rendering import _player_id
from worldforge.app.requests import _handle_action_request
from worldforge.content.campaign import system_enabled


def _apply_network_request_result(updated, combat, vendor_state):
    """Apply router result metadata and return its notice, if any."""
    if updated and "_action_error" in updated:
        return combat, updated["_action_error"], 2400
    if updated and "_action_notice" in updated:
        notice = updated["_action_notice"]
        if updated.get("vendor_state_changed"):
            updated.pop("_action_notice", None)
            updated.pop("vendor_state_changed", None)
            combat = updated
        if updated.get("rest_state_changed"):
            updated.pop("_action_notice", None)
            updated.pop("rest_state_changed", None)
            combat = updated
        if updated.get("area_changed"):
            updated.pop("_action_notice", None)
            updated.pop("area_changed", None)
            vendor_state["buyback"] = {}
            updated["vendor_buyback"] = {}
            combat = updated
        if updated.get("sync_only"):
            combat = updated
        return combat, notice, 3000
    return updated, None, 0


def advance_host_world(actor, player_id, remote_players, combat,
                       combat_transport, vendor_state):
    """Advance authoritative multiplayer state and publish the new snapshot."""
    notice = None
    notice_duration = 0

    if combat and combat.get("rest_session"):
        session = combat["rest_session"]
        connected = {player_id}
        connected.update(_player_id(item) for item in remote_players
                         if item.get("actor"))
        departed = set(session.get("participants", [])) - connected
        if departed:
            if session.get("location") == "inn":
                from worldforge.app.rest_flow import cancel_inn_booking
                cancel_inn_booking(actor, player_id, remote_players, combat)
                session = None
            if session is None:
                departed = set()
        if departed:
            session["participants"] = [
                member for member in session.get("participants", [])
                if member not in departed]
            session["ready"] = [member for member in session.get("ready", [])
                                if member not in departed]
            for member in departed:
                combat.get("actors", {}).pop(member, None)
                for key in ("return_positions", "bed_by_actor", "costs", "paid"):
                    session.get(key, {}).pop(member, None)
        for member_id, entry in combat.get("actors", {}).items():
            if entry.get("team") != "players":
                continue
            if member_id == player_id:
                position = (actor.x, actor.y)
            else:
                remote = next((item for item in remote_players
                               if _player_id(item) == member_id), None)
                if not remote:
                    continue
                position = (remote.get("x", entry["x"]),
                            remote.get("y", entry["y"]))
            entry["x"], entry["y"] = position
            entry["data"]["x"], entry["data"]["y"] = position

    if combat and combat.get("active"):
        remove_disconnected_players(combat, remote_players, player_id)
        add_joined_players(combat, remote_players)
    for request in combat_transport["poll"]():
        updated = _handle_action_request(
            actor, player_id, request["player_id"], request["action"],
            remote_players, combat, vendor_state)
        combat, request_notice, duration = _apply_network_request_result(
            updated, combat, vendor_state)
        if request_notice is not None:
            notice, notice_duration = request_notice, duration

    if combat:
        now = pygame.time.get_ticks()
        advance_world_mob_patrol(combat, now)
        for mob_id, entry in list(combat.get("actors", {}).items()):
            expiry = entry.get("corpse_despawn_at")
            if (entry.get("team") == "enemies" and expiry is not None
                    and now >= expiry):
                del combat["actors"][mob_id]
        players_for_spawn = [_combat_snapshot(player_id, vars(actor))]
        players_for_spawn.extend(
            _combat_snapshot(_player_id(remote), remote["actor"])
            for remote in remote_players if remote.get("actor"))
        settle_victory(combat, players_for_spawn)

    if (system_enabled("combat")
            and (not combat or not combat.get("active"))
            and not (combat and combat.get("rest_session"))):
        world_mobs = combat_world_mobs(combat) if combat else None
        scenario_id = ((combat or {}).get("scenario_id")
                       or DEFAULT_SCENARIO)
        aggro_immune_until = (combat or {}).get("aggro_immune_until", 0)
        immune = pygame.time.get_ticks() < aggro_immune_until
        trigger = (None if immune else _combat_trigger(
            actor, player_id, remote_players, scenario_id=scenario_id,
            world_mobs=world_mobs))
        if trigger:
            spotted_player, enemy_id = trigger
            area_state = combat or {}
            combat = _new_combat(
                actor, player_id, remote_players, scenario_id=scenario_id,
                world_mobs=world_mobs)
            # Carry the creature that caused the encounter into the client
            # target-selection state, so the first attack input has a target.
            combat["aggro_target_id"] = enemy_id
            combat["aggro_player_id"] = spotted_player
            combat["world_areas"] = deepcopy(area_state.get("world_areas", {}))
            combat["world_area_items"] = deepcopy(
                area_state.get("world_area_items", {}))
            combat["world_area_chests"] = deepcopy(
                area_state.get("world_area_chests", {}))
            combat["chests"] = deepcopy(area_state.get(
                "chests", combat.get("chests", [])))
            combat["ground_items"] = deepcopy(area_state.get("ground_items", []))
            combat["vendor_buyback"] = deepcopy(
                area_state.get("vendor_buyback", {}))
            player_name = combat["actors"][spotted_player]["data"].get(
                "name", spotted_player)
            enemy_name = combat["actors"][enemy_id]["data"].get(
                "name", "An enemy")
            _log(combat, (f"{enemy_name} spots {player_name} within "
                          f"{COMBAT_TRIGGER_RANGE_FEET} feet. Combat begins!"))

    if combat:
        _process_turn_start(combat)
        _run_ai_turns(combat)
    if combat is not None:
        combat["vendor_buyback"] = deepcopy(vendor_state["buyback"])
    combat_transport["publish"](combat)
    _sync_local_actor(actor, combat, player_id, consume_position_sync=True)
    if combat:
        for entry in combat.get("actors", {}).values():
            if entry.get("team") == "players":
                entry.get("data", {}).pop("_force_position_sync", None)
        combat.pop("rest_position_sync", None)
    return combat, notice, notice_duration
