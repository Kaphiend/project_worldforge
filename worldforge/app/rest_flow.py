"""Party camp and inn rest sessions."""
from copy import deepcopy

from worldforge.app.combat_flow import _log
from worldforge.app.encounters import (DEFAULT_SCENARIO, _combat_snapshot,
                                       _progression_sync_state)
from worldforge.app.party import party_members, set_remote_position
from worldforge.app.rendering import _player_id
from worldforge.app.world import ACTOR_SIZE, PIXELS_PER_FOOT
from worldforge.combat.resting import (INN_REST_GOLD_COST, outdoor_rest_cost, resolve_paid_inn_rest,
                                       resolve_rest)
from worldforge.combat.rules import edge_distance_feet
from worldforge.content.classes import ARENAS, NPCS, SCENARIOS
from worldforge.content.campaign import ACTIVE_CAMPAIGN


def _resolve_party_rest(actor, local_player_id, remote_players, combat,
                        location="outdoor", *, prepaid=False):
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
        result = (resolve_paid_inn_rest(data) if prepaid else resolve_rest(
            data, location, distance_to_nearest_enemy_feet=nearest_enemy))
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
            entry = combat["actors"][player_id]
            entry["data"].update(data)
            entry["downed"] = bool(data.get("downed", False))
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
    camp = ARENAS.get(ACTIVE_CAMPAIGN["safe_camp_arena"])
    if not camp:
        return {"_action_error": "There is no safe camp configured for this game."}
    players = party_members(actor, local_player_id, remote_players, combat)
    if any(
            data.get("downed")
            or (combat or {}).get("actors", {}).get(player_id, {}).get("downed")
            for player_id, _, data in players):
        return {"_action_error": "The party cannot travel to a safe camp while a member is downed. Revive them first."}
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
    camp_instance = deepcopy(camp)
    camp_instance["camp_beds"] = camp_instance.get("camp_beds", [])[:len(players)]
    camp_beds_by_id = {bed.get("id"): bed
                       for bed in camp_instance.get("camp_beds", [])}
    for player_id, _, data in players:
        bed = camp_beds_by_id.get(bed_by_actor[player_id])
        if bed:
            bed["owner_name"] = data.get("name") or player_id
    camp_instance["personal_chests"] = [
        {"id": f"camp_storage_{player_id}", "kind": "personal_chest",
         "storage_scope": "camp",
         "name": f"{data.get('name') or player_id}'s Chest",
         "owner_id": player_id, "owner_name": data.get("name") or player_id,
         "bed_id": bed_by_actor[player_id],
         "x": int(camp_beds_by_id[bed_by_actor[player_id]].get("x", 0)) + 120,
         "y": int(camp_beds_by_id[bed_by_actor[player_id]].get("y", 0)) - 4,
         "width": 48, "height": 40, "interaction_range_feet": 5}
        for player_id, _, data in players
        if bed_by_actor[player_id] in camp_beds_by_id
    ]
    return_mobs = ([deepcopy(entry) for entry in combat.get("actors", {}).values()
                    if entry.get("team") == "enemies"]
                   if combat else None)
    return_sync_only = bool((combat or {}).get("sync_only", False))
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
        if player_id != local_player_id:
            remote = next((item for item in remote_players
                           if _player_id(item) == player_id), None)
            if remote:
                set_remote_position(remote, x, y)
        entry = state["actors"].get(player_id)
        if entry is None:
            entry = _combat_snapshot(player_id, data, "players")
            state["actors"][player_id] = entry
        else:
            entry["data"].update(data)
        entry["x"], entry["y"] = x, y
    state.update(active=False, sync_only=True, order=[], budgets={}, turn_index=0,
                 arena=camp_instance, result=None)
    state["rest_session"] = {
        "location": "outdoor", "participants": participants, "ready": [],
        "costs": costs, "bed_by_actor": bed_by_actor,
        "return_positions": return_positions,
        "return_arena": deepcopy(arena), "return_mobs": return_mobs,
        "return_sync_only": return_sync_only,
    }
    state["_action_notice"] = (
        "The party reaches the safe camp. Each character must interact with their assigned bed; "
        "everyone will pay their own XP cost when the party rests.")
    state["rest_state_changed"] = True
    return state


INN_NIGHT_COST = INN_REST_GOLD_COST


def _book_inn_bed(actor, local_player_id, actor_id, remote_players, combat):
    if combat and combat.get("active"):
        return {"_action_error": "You cannot rest while combat is active."}
    state = _ensure_rest_state(actor, local_player_id, remote_players, combat)
    session = state.get("rest_session")
    if session and session.get("location") != "inn":
        return {"_action_error": "Finish or leave the current camp before checking into the inn."}
    arena = state.get("arena") or ARENAS.get(
        SCENARIOS.get(DEFAULT_SCENARIO, {}).get("arena"), {})
    innkeeper = next((item for item in arena.get("innkeepers", [])
                      if item.get("id") == "innkeeper"), None)
    if not innkeeper:
        return {"_action_error": "There is no innkeeper available."}
    players = party_members(actor, local_player_id, remote_players, state)
    member = next((record for record in players if record[0] == actor_id), None)
    if not member:
        return {"_action_error": "That character is not in the party."}
    _, target, data = member
    if edge_distance_feet(data, innkeeper, PIXELS_PER_FOOT, ACTOR_SIZE) > int(
            innkeeper.get("interaction_range_feet", 10)):
        return {"_action_error": "Move closer to the innkeeper to book a bed."}
    beds = arena.get("inn_beds", [])
    if not session:
        state["rest_session"] = {
            "location": "inn", "participants": [record[0] for record in players],
            "ready": [], "paid": {}, "bed_by_actor": {},
        }
        session = state["rest_session"]
    if actor_id not in session["participants"]:
        return {"_action_error": "You joined after the party began checking in. Try again after this rest."}
    if actor_id in session["paid"]:
        bed_id = session["bed_by_actor"].get(actor_id)
        bed = next((item for item in beds if item.get("id") == bed_id), {})
        state["_action_notice"] = f"Your room is paid for. Check in at {bed.get('name', 'your assigned bed')}."
        state["rest_state_changed"] = True
        return state
    if int(data.get("gold", 0) or 0) < INN_NIGHT_COST:
        return {"_action_error": (
            f"An inn night costs {INN_NIGHT_COST} gold; you do not have enough.")}
    assigned = set(session["bed_by_actor"].values())
    free_beds = [bed for bed in beds if bed.get("id") not in assigned]
    if not free_beds:
        return {"_action_error": "There are no unassigned beds available."}
    import random
    bed = random.choice(free_beds)
    data["gold"] = int(data.get("gold", 0) or 0) - INN_NIGHT_COST
    if isinstance(target, dict):
        target["gold"] = data["gold"]
    else:
        target.gold = data["gold"]
    if actor_id in state.get("actors", {}):
        state["actors"][actor_id]["data"]["gold"] = data["gold"]
    session["paid"][actor_id] = INN_NIGHT_COST
    session["bed_by_actor"][actor_id] = bed["id"]
    bed["owner_name"] = data.get("name") or actor_id
    for chest in arena.get("personal_chests", []):
        if chest.get("bed_id") == bed["id"]:
            chest["owner_id"] = actor_id
            chest["owner_name"] = bed["owner_name"]
    state["_action_notice"] = (
        f"{data.get('name', actor_id)} pays {INN_NIGHT_COST} gold and is assigned "
        f"{bed.get('name', 'a bed')}. Interact with it to check in.")
    state["rest_state_changed"] = True
    return state


def _start_inn_checkin(actor, local_player_id, actor_id, remote_players,
                       combat, bed_id):
    session = (combat or {}).get("rest_session")
    if not session or session.get("location") != "inn":
        return {"_action_error": "Book a bed with the innkeeper first."}
    if actor_id not in session.get("participants", []):
        return {"_action_error": "That character is not part of this inn booking."}
    assigned_bed_id = session.get("bed_by_actor", {}).get(actor_id)
    if not assigned_bed_id or actor_id not in session.get("paid", {}):
        return {"_action_error": "Pay the innkeeper before checking in."}
    if assigned_bed_id != bed_id:
        return {"_action_error": "Check in at your assigned bed."}
    arena = combat.get("arena", {})
    beds = arena.get("inn_beds", [])
    bed = next((item for item in beds if item.get("id") == bed_id), None)
    if not bed:
        return {"_action_error": "That inn bed is unavailable."}
    member = next((record for record in party_members(
        actor, local_player_id, remote_players, combat) if record[0] == actor_id), None)
    if not member:
        return {"_action_error": "That character is not in the party."}
    _, _, data = member
    if edge_distance_feet(data, bed, PIXELS_PER_FOOT, ACTOR_SIZE) > int(
            bed.get("interaction_range_feet", 5)):
        return {"_action_error": "Move closer to your assigned bed to check in."}
    if actor_id not in session["ready"]:
        session["ready"].append(actor_id)
    if not all(player_id in session["paid"] and player_id in session["ready"]
               for player_id in session["participants"]):
        combat["_action_notice"] = (
            f"{data.get('name', actor_id)} checked in "
            f"({len(session['ready'])}/{len(session['participants'])}). "
            "Waiting for the party to pay and check in.")
        combat["rest_state_changed"] = True
        return combat
    result = _resolve_party_rest(actor, local_player_id, remote_players,
                                 combat, "inn", prepaid=True)
    if "_action_error" in result:
        return result
    assigned_beds = set(session.get("bed_by_actor", {}).values())
    for bed in combat.get("arena", {}).get("inn_beds", []):
        if bed.get("id") in assigned_beds:
            bed.pop("owner_name", None)
    for chest in combat.get("arena", {}).get("personal_chests", []):
        if chest.get("bed_id") in assigned_beds:
            chest.pop("owner_id", None)
            chest.pop("owner_name", None)
    combat["rest_session"] = None
    combat["_action_notice"] = (
        f"Everyone checked in. Each guest paid {INN_NIGHT_COST} gold; "
        "the party rests at the inn.")
    combat["rest_state_changed"] = True
    return combat


def cancel_inn_booking(actor, local_player_id, remote_players, combat):
    """Refund paid guests and release their rooms when leaving before rest."""
    session = (combat or {}).get("rest_session")
    if not session or session.get("location") != "inn":
        return
    for player_id, amount in session.get("paid", {}).items():
        entry = combat.get("actors", {}).get(player_id)
        if entry:
            entry["data"]["gold"] = int(entry["data"].get("gold", 0) or 0) + amount
        if player_id == local_player_id:
            actor.gold += amount
        else:
            remote = next((item for item in remote_players
                           if _player_id(item) == player_id), None)
            target = remote.get("actor") if remote else None
            if target:
                if isinstance(target, dict):
                    target["gold"] = int(target.get("gold", 0) or 0) + amount
                else:
                    target.gold += amount
    bed_ids = set(session.get("bed_by_actor", {}).values())
    for bed in combat.get("arena", {}).get("inn_beds", []):
        if bed.get("id") in bed_ids:
            bed.pop("owner_name", None)
    for chest in combat.get("arena", {}).get("personal_chests", []):
        if chest.get("bed_id") in bed_ids:
            chest.pop("owner_id", None)
            chest.pop("owner_name", None)
    combat["rest_session"] = None


def _leave_camp(actor, local_player_id, actor_id, remote_players, combat):
    """Return the party from camp without charging XP or resting."""
    if not combat or combat.get("active"):
        return {"_action_error": "You cannot leave camp during combat."}
    session = combat.get("rest_session")
    if not session or session.get("location") != "outdoor":
        return {"_action_error": "The party is not at a safe camp."}
    if actor_id not in session.get("participants", []):
        return {"_action_error": "You are not part of this camp session."}
    for player_id, position in session.get("return_positions", {}).items():
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
        combat["sync_only"] = session.get("return_sync_only", False)
    combat["_action_notice"] = "The party leaves camp without resting; no XP was spent."
    combat["rest_state_changed"] = True
    return combat


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
        combat["sync_only"] = session.get("return_sync_only", False)
    combat["_action_notice"] = result.get(
        "_action_notice", "The party rests at the safe camp.")
    combat["rest_state_changed"] = True
    return combat
