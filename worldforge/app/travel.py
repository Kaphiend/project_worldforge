"""Map transition rules and destination placement for connected areas."""
from copy import deepcopy

from worldforge.app.encounters import (DEFAULT_SCENARIO, _combat_snapshot,
                                       _scenario_world_mobs)
from worldforge.app.party import party_members, set_remote_position
from worldforge.app.rendering import _player_id
from worldforge.app.world import (ACTOR_SIZE, PIXELS_PER_FOOT, _actor_hitbox,
                                  _arena_bounds, _arena_obstacles)
from worldforge.combat.rules import edge_distance_feet
from worldforge.content.classes import ARENAS, SCENARIOS


def _persistent_area_enemies(entries):
    """Keep living mobs and corpses that still contain loot in area caches."""
    return [deepcopy(entry) for entry in entries
            if entry.get("team") == "enemies"
            and (not entry.get("downed") or bool(entry.get("loot")))]


def _area_arrival_spawn(destination_arena, source_id, source_exit):
    """Place arrivals just inside the reciprocal gateway, when one exists."""
    exits = destination_arena.get("exits", [])
    target_exit_id = source_exit.get("destination_exit_id")
    arrival_exit = next((item for item in exits
                         if target_exit_id and item.get("id") == target_exit_id), None)
    if arrival_exit is None:
        arrival_exit = next((item for item in exits
                             if item.get("destination_scenario") == source_id), None)
    if arrival_exit is None:
        return source_exit.get("destination_spawn", [40, 40])

    x, y = float(arrival_exit.get("x", 0)), float(arrival_exit.get("y", 0))
    width = float(arrival_exit.get("width", 0))
    height = float(arrival_exit.get("height", 0))
    bounds = _arena_bounds(destination_arena)
    center_x, center_y = x + width / 2, y + height / 2
    margin = ACTOR_SIZE + 20
    if x <= bounds.left:
        center_x = bounds.left + margin
    elif x + width >= bounds.right:
        center_x = bounds.right - margin
    elif y <= bounds.top:
        center_y = bounds.top + margin
    elif y + height >= bounds.bottom:
        center_y = bounds.bottom - margin
    return [round(center_x), round(center_y)]


def travel_party_through_exit(actor, local_player_id, actor_id, remote_players,
                              combat, exit_id):
    """Move the connected party through an arena exit into another data area."""
    if not combat or combat.get("active"):
        return {"_action_error": "You cannot travel to another area during combat."}
    if combat.get("rest_session"):
        return {"_action_error": "Finish the current rest before traveling."}
    arena = combat.get("arena", {})
    exit_record = next((item for item in arena.get("exits", [])
                        if item.get("id") == exit_id), None)
    if not exit_record:
        return {"_action_error": "That area exit is unavailable."}
    member = combat.get("actors", {}).get(actor_id)
    if member and member.get("team") != "players":
        return {"_action_error": "That character is not in the party."}
    if actor_id == local_player_id:
        data = deepcopy(member["data"] if member else vars(actor))
        data["x"], data["y"] = actor.x, actor.y
    else:
        remote = next((item for item in remote_players
                       if _player_id(item) == actor_id), None)
        if not remote or not remote.get("actor"):
            return {"_action_error": "That character is not in the party."}
        remote_actor = remote["actor"]
        data = deepcopy(member["data"] if member else
                        remote_actor if isinstance(remote_actor, dict)
                        else vars(remote_actor))
        data["x"] = remote.get("x", data.get("x", 0))
        data["y"] = remote.get("y", data.get("y", 0))
    if edge_distance_feet(data, exit_record, PIXELS_PER_FOOT, ACTOR_SIZE) > int(
            exit_record.get("interaction_range_feet", 8)):
        return {"_action_error": "Move closer to the exit to travel."}
    destination_id = exit_record.get("destination_scenario")
    destination = SCENARIOS.get(destination_id)
    if not destination:
        return {"_action_error": "The exit points to an unknown area."}
    destination_arena = ARENAS.get(destination.get("arena"))
    if not destination_arena:
        return {"_action_error": "The destination area has no arena."}
    players = party_members(actor, local_player_id, remote_players, combat)
    if not players:
        return {"_action_error": "There are no connected party members to travel."}

    world_areas = combat.setdefault("world_areas", {})
    world_area_items = combat.setdefault("world_area_items", {})
    source_id = combat.get("scenario_id", DEFAULT_SCENARIO)
    world_areas[source_id] = _persistent_area_enemies(
        combat.get("actors", {}).values())
    world_area_items[source_id] = deepcopy(combat.get("ground_items", []))
    destination_mobs = world_areas.get(destination_id)
    if destination_mobs is None:
        destination_mobs = _scenario_world_mobs(destination_id)
    destination_mobs = _persistent_area_enemies(destination_mobs)
    world_areas[destination_id] = deepcopy(destination_mobs)
    combat["ground_items"] = deepcopy(world_area_items.get(destination_id, []))

    base_x, base_y = _area_arrival_spawn(
        destination_arena, source_id, exit_record)
    spacing = max(60, int(exit_record.get("party_spawn_spacing", 65)))
    bounds = _arena_bounds(destination_arena)
    obstacles = _arena_obstacles(destination_arena)
    obstacles.extend(_actor_hitbox(entry["x"], entry["y"])
                     for entry in destination_mobs
                     if entry.get("team") == "enemies" and not entry.get("downed"))
    occupied = []
    offsets = [(0, 0)]
    for ring in range(1, max(3, len(players) + 1)):
        offsets.extend((dx * spacing, dy * spacing)
                       for dx, dy in ((-ring, -ring), (0, -ring), (ring, -ring),
                                      (-ring, 0), (ring, 0), (-ring, ring),
                                      (0, ring), (ring, ring)))
    for player_id, _target, player_data in players:
        x, y = None, None
        for offset_x, offset_y in offsets:
            candidate_x = max(bounds.left, min(bounds.right - ACTOR_SIZE,
                                               int(base_x + offset_x)))
            candidate_y = max(bounds.top, min(bounds.bottom - ACTOR_SIZE,
                                              int(base_y + offset_y)))
            rect = _actor_hitbox(candidate_x, candidate_y)
            if not any(rect.colliderect(obstacle)
                       for obstacle in obstacles + occupied):
                x, y = candidate_x, candidate_y
                break
        if x is None:
            x = max(bounds.left, min(bounds.right - ACTOR_SIZE, int(base_x)))
            y = max(bounds.top, min(bounds.bottom - ACTOR_SIZE, int(base_y)))
        occupied.append(_actor_hitbox(x, y))
        entry = combat["actors"].get(player_id)
        if not entry:
            entry = _combat_snapshot(player_id, player_data, "players")
            combat["actors"][player_id] = entry
        entry["x"], entry["y"] = x, y
        entry["data"]["x"], entry["data"]["y"] = x, y
        entry["data"]["_force_position_sync"] = True
        if player_id == local_player_id:
            actor.x, actor.y = x, y
        else:
            remote = next((item for item in remote_players
                           if _player_id(item) == player_id), None)
            if remote and remote.get("actor"):
                set_remote_position(remote, x, y)

    combat["actors"] = {player_id: entry for player_id, entry in
                        combat["actors"].items()
                        if entry.get("team") == "players"}
    combat["actors"].update({entry["id"]: deepcopy(entry)
                             for entry in destination_mobs})
    combat["scenario_id"] = destination_id
    combat["scenario"] = deepcopy(destination)
    combat["arena"] = deepcopy(destination_arena)
    combat.update(active=False, sync_only=True, order=[], budgets={},
                  turn_index=0, result=None, victory_settled=False)
    combat["rest_position_sync"] = True
    combat["_action_notice"] = f"The party travels to {destination.get('name', destination_id)}."
    combat["area_changed"] = True
    return combat
