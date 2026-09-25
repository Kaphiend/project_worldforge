"""Party camp and inn rest sessions."""
from copy import deepcopy

from worldforge.app.combat_flow import _log
from worldforge.app.encounters import (DEFAULT_SCENARIO, _combat_snapshot,
                                       _progression_sync_state)
from worldforge.app.party import party_members, set_remote_position
from worldforge.app.rendering import _player_id
from worldforge.app.world import ACTOR_SIZE, PIXELS_PER_FOOT
from worldforge.combat.resting import outdoor_rest_cost, resolve_rest
from worldforge.combat.rules import edge_distance_feet
from worldforge.content.classes import ARENAS, NPCS, SCENARIOS


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
    prepared = []
    for player_id, target, data in players:
        # Inn proximity is checked at the specific bed when each character
        # checks in. Rechecking against the first bed here incorrectly rejects
        # guests who checked in at another bed in the same inn.
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
            actor_data = vars(target)
            actor_data.update({key: value for key, value in data.items()
                               if key in actor_data})
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

def _world_rest_mobs(combat, arena):
    if combat:
        return [entry for entry in combat.get("actors", {}).values()
                if entry.get("team") == "enemies" and not entry.get("downed")]
    scenario = SCENARIOS.get(DEFAULT_SCENARIO, {})
    mobs = []
    for index, spawn in enumerate(scenario.get("enemies", [])):
        definition = NPCS.get(spawn.get("npc"))
        if not definition:
            continue
        mob_data = deepcopy(definition)
        mob_data.update(x=spawn.get("x", 0), y=spawn.get("y", 0))
        mobs.append(_combat_snapshot(
            spawn.get("id", f"{spawn.get('npc')}-{index + 1}"), mob_data, "enemies"))
    return mobs


def _ensure_rest_state(actor, local_player_id, remote_players, combat):
    state = combat or _progression_sync_state(
        actor, local_player_id, remote_players)
    state.setdefault("actors", {})
    state.setdefault("vendor_buyback", {})
    return state


def _start_camp(actor, local_player_id, remote_players, combat):
    if combat and combat.get("active"):
        return {"_action_error": "You cannot set up camp while combat is active."}
    if combat and combat.get("rest_session"):
        return {"_action_error": "The party is already preparing to rest."}
    arena = (combat or {}).get("arena") or ARENAS.get(
        SCENARIOS.get(DEFAULT_SCENARIO, {}).get("arena"), {})
    camp = ARENAS.get("safe_camp")
    if not camp:
        return {"_action_error": "There is no safe camp configured for this game."}
    players = party_members(actor, local_player_id, remote_players, combat)
    beds = list(camp.get("camp_beds", []) or [])
    if len(beds) < len(players):
        return {"_action_error": "There are not enough beds at the safe camp for the party."}
    mobs = _world_rest_mobs(combat, arena)
    costs = {}
    for player_id, _, data in players:
        distances = [edge_distance_feet(data, mob, PIXELS_PER_FOOT, ACTOR_SIZE)
                     for mob in mobs]
        nearest = min(distances) if distances else float("inf")
        check = resolve_rest(
            deepcopy(data), "outdoor", distance_to_nearest_enemy_feet=nearest)
        if not check.get("success"):
            return {"_action_error": f"{data.get('name', player_id)} cannot camp: {check.get('reason', 'rest unavailable')}"}
        costs[player_id] = outdoor_rest_cost(data)[0]

    return_positions = {player_id: [data.get("x", 0), data.get("y", 0)]
                        for player_id, _, data in players}
    bed_by_actor = {player_id: beds[index].get("id")
                    for index, (player_id, _, _) in enumerate(players)}
    return_mobs = ([deepcopy(entry) for entry in combat.get("actors", {}).values()
                    if entry.get("team") == "enemies"]
                   if combat and not combat.get("sync_only") else None)
    state = _ensure_rest_state(actor, local_player_id, remote_players, combat)
    participants = [player_id for player_id, _, _ in players]
    # Keep only the party in the camp instance; saved enemies return with them.
    state["actors"] = {player_id: entry for player_id, entry in state["actors"].items()
                        if entry.get("team") == "players" and player_id in participants}
    for index, (player_id, target, data) in enumerate(players):
        bed = beds[index]
        x = int(bed.get("spawn_x", bed.get("x", 0) - ACTOR_SIZE))
        y = int(bed.get("spawn_y", bed.get("y", 0) + bed.get("height", 30)))
        data["x"], data["y"] = x, y
        data["_force_position_sync"] = True
        if isinstance(target, dict):
            target.update(data)
        else:
            actor_data = vars(target)
            actor_data.update({key: value for key, value in data.items()
                               if key in actor_data})
        entry = state["actors"].get(player_id)
        if entry is None:
            entry = _combat_snapshot(player_id, data, "players")
            state["actors"][player_id] = entry
        else:
            entry["data"].update(data)
        entry["x"], entry["y"] = x, y
    state.update(active=False, sync_only=True, order=[], budgets={}, turn_index=0,
                 arena=deepcopy(camp), result=None)
    state["rest_session"] = {
        "location": "outdoor", "participants": participants, "ready": [],
        "costs": costs, "bed_by_actor": bed_by_actor,
        "return_positions": return_positions,
        "return_arena": deepcopy(arena), "return_mobs": return_mobs,
    }
    state["_action_notice"] = (
        "The party reaches the safe camp. Each character must interact with their assigned bed; "
        "everyone will pay their own XP cost when the party rests.")
    state["rest_state_changed"] = True
    return state


def _start_inn_checkin(actor, local_player_id, actor_id, remote_players,
                       combat, bed_id):
    if combat and combat.get("active"):
        return {"_action_error": "You cannot rest while combat is active."}
    state = _ensure_rest_state(actor, local_player_id, remote_players, combat)
    session = state.get("rest_session")
    if session and session.get("location") != "inn":
        return {"_action_error": "Finish or leave the current camp before checking into the inn."}
    arena = state.get("arena") or ARENAS.get(
        SCENARIOS.get(DEFAULT_SCENARIO, {}).get("arena"), {})
    beds = arena.get("inn_beds", [])
    bed = next((item for item in beds if item.get("id") == bed_id), None)
    if not bed:
        return {"_action_error": "That inn bed is unavailable."}
    players = party_members(actor, local_player_id, remote_players, state)
    member = next((record for record in players if record[0] == actor_id), None)
    if not member:
        return {"_action_error": "That character is not in the party."}
    _, _, data = member
    distance = edge_distance_feet(data, bed, PIXELS_PER_FOOT, ACTOR_SIZE)
    if distance > int(bed.get("interaction_range_feet", 5)):
        return {"_action_error": "Move closer to the inn bed to check in."}
    if int(data.get("gold", 0) or 0) < 10:
        return {"_action_error": "An inn night costs 10 gold; you do not have enough."}
    if not session:
        state["rest_session"] = {
            "location": "inn", "participants": [record[0] for record in players],
            "ready": [], "bed_id": bed_id,
        }
        session = state["rest_session"]
    if actor_id not in session["participants"]:
        return {"_action_error": "You joined after the party began checking in. Try again after this rest."}
    if actor_id not in session["ready"]:
        session["ready"].append(actor_id)
    if not all(player_id in session["ready"] for player_id in session["participants"]):
        state["_action_notice"] = (
            f"{data.get('name', actor_id)} checked in "
            f"({len(session['ready'])}/{len(session['participants'])}). Waiting for the party.")
        state["rest_state_changed"] = True
        return state
    result = _resolve_party_rest(actor, local_player_id, remote_players,
                                 state, "inn")
    if "_action_error" in result:
        return result
    state["rest_session"] = None
    state["_action_notice"] = (
        f"Everyone checked in and paid 10 gold. {result.get('_action_notice', 'The party rests at the inn.')}")
    state["rest_state_changed"] = True
    return state


def _camp_bed_checkin(actor, local_player_id, actor_id, remote_players, combat,
                      bed_id):
    session = (combat or {}).get("rest_session")
    if not session or session.get("location") != "outdoor":
        return {"_action_error": "The party is not at a safe camp."}
    if actor_id not in session["participants"]:
        return {"_action_error": "You are not part of this camp session."}
    if session["bed_by_actor"].get(actor_id) != bed_id:
        return {"_action_error": "Use the bed assigned to your character."}
    bed = next((item for item in combat.get("arena", {}).get("camp_beds", [])
                if item.get("id") == bed_id), None)
    member = next((record for record in party_members(
        actor, local_player_id, remote_players, combat) if record[0] == actor_id), None)
    if not bed or not member:
        return {"_action_error": "Your assigned camp bed is unavailable."}
    _, _, data = member
    if edge_distance_feet(data, bed, PIXELS_PER_FOOT, ACTOR_SIZE) > int(
            bed.get("interaction_range_feet", 5)):
        return {"_action_error": "Move closer to your assigned bed to check in."}
    if actor_id not in session["ready"]:
        session["ready"].append(actor_id)
    if not all(player_id in session["ready"] for player_id in session["participants"]):
        cost = session["costs"].get(actor_id, 0)
        combat["_action_notice"] = (
            f"{data.get('name', actor_id)} is settled at camp ({len(session['ready'])}/"
            f"{len(session['participants'])}); their rest will cost {cost} XP.")
        combat["rest_state_changed"] = True
        return combat
    result = _resolve_party_rest(actor, local_player_id, remote_players,
                                 combat, "outdoor")
    if "_action_error" in result:
        return result
    session = deepcopy(session)
    for player_id, position in session["return_positions"].items():
        entry = combat.get("actors", {}).get(player_id)
        if entry:
            x, y = position
            entry["x"], entry["y"] = x, y
            entry["data"]["x"], entry["data"]["y"] = x, y
            entry["data"]["_force_position_sync"] = True
        if player_id == local_player_id:
            actor.x, actor.y = position
        else:
            remote = next((item for item in remote_players
                           if _player_id(item) == player_id), None)
            if remote and remote.get("actor"):
                set_remote_position(remote, *position)
    combat["arena"] = deepcopy(session["return_arena"])
    combat["rest_session"] = None
    combat["rest_position_sync"] = True
    if session.get("return_mobs") is not None:
        for mob in session["return_mobs"]:
            combat["actors"][mob["id"]] = mob
        combat["sync_only"] = False
    combat["_action_notice"] = result.get(
        "_action_notice", "The party rests at the safe camp.")
    combat["rest_state_changed"] = True
    return combat

