"""Encounter setup, mob lifecycle, and combat snapshot helpers."""
from copy import deepcopy
import math
import random
import pygame

from worldforge.actors.factory import create_npc_instance
from worldforge.app.combat_flow import _log
from worldforge.app.rendering import _player_id
from worldforge.app.world import (ACTOR_HITBOX_HEIGHT, ACTOR_HITBOX_WIDTH,
                                  ACTOR_SIZE, PIXELS_PER_FOOT, _actor_hitbox,
                                  _arena_bounds, _arena_obstacles,
                                  _line_of_sight, _movement_allowance,
                                  _walk_destination,
                                  _perception_score)
from worldforge.combat.rules import edge_distance_feet, initiative_for
from worldforge.content.classes import (ARENAS, MOB_GENERATION_RULES, NPCS,
                                        SCENARIOS)
from worldforge.content.campaign import (ACTIVE_CAMPAIGN, campaign_rule,
                                         campaign_setting)
from worldforge.core.progression import initialize_resources

DEFAULT_SCENARIO = ACTIVE_CAMPAIGN["starting_scenario"]

def _actor_data(actor):
    return deepcopy(vars(actor)) if not isinstance(actor, dict) else deepcopy(actor)

def _combat_snapshot(actor_id, data, team="players"):
    data = _actor_data(data)
    initialize_resources(data)
    if data.get("sneaking") and data.get("stealth_check_total") is not None:
        data.setdefault("hidden", {
            "stealth_total": int(data["stealth_check_total"]),
            "detected_by": [],
        })
    hitbox = {"offset_x": (ACTOR_SIZE - ACTOR_HITBOX_WIDTH) / 2,
              "offset_y": (ACTOR_SIZE - ACTOR_HITBOX_HEIGHT) / 2,
              "width": ACTOR_HITBOX_WIDTH, "height": ACTOR_HITBOX_HEIGHT}
    data["hitbox"] = hitbox
    return {"id": actor_id, "team": team, "data": data, "hitbox": hitbox,
            "x": float(data.get("x", 0)), "y": float(data.get("y", 0)),
            "width": ACTOR_SIZE, "height": ACTOR_SIZE,
            "downed": bool(data.get("downed", False) or data.get("current_hp", 1) <= 0)}

def _progression_sync_state(actor, local_player_id, remote_players):
    """Publish host-approved out-of-combat purchases to connected clients."""
    actors = {local_player_id: _combat_snapshot(local_player_id, actor)}
    for remote in remote_players:
        if remote.get("actor"):
            remote_id = _player_id(remote)
            actors[remote_id] = _combat_snapshot(remote_id, remote["actor"])
    return {"active": False, "sync_only": True, "actors": actors,
            "order": [], "log": [], "result": None,
            "scenario_id": DEFAULT_SCENARIO,
            "scenario": deepcopy(SCENARIOS.get(DEFAULT_SCENARIO, {})),
            "arena": deepcopy(ARENAS.get(
                SCENARIOS.get(DEFAULT_SCENARIO, {}).get("arena"), {}))}


def _scenario_world_mobs(scenario_id):
    """Build the initial persistent enemy set authored for one area."""
    scenario = SCENARIOS.get(scenario_id, {})
    mobs = []
    for index, spawn in enumerate(scenario.get("enemies", [])):
        npc_id = spawn.get("npc")
        if npc_id not in NPCS:
            continue
        mob_id = spawn.get("id", f"{npc_id}-{index + 1}")
        npc = create_npc_instance(
            npc_id, spawn.get("x", NPCS[npc_id].get("x", 0)),
            spawn.get("y", NPCS[npc_id].get("y", 0)))
        npc["id"] = mob_id
        entry = _combat_snapshot(mob_id, npc, "enemies")
        entry["perception_info"] = _mob_perception_info(NPCS[npc_id], npc)
        entry["patrol_origin"] = [entry["x"], entry["y"]]
        entry["patrol_waypoint"] = 0
        mobs.append(entry)
    return mobs


def _new_world_state(actor, local_player_id, remote_players,
                     scenario_id=DEFAULT_SCENARIO):
    """Create an exploration snapshot with this area's data and enemies."""
    scenario = SCENARIOS.get(scenario_id)
    if not scenario:
        raise ValueError(f"Unknown area scenario: {scenario_id}")
    state = _progression_sync_state(actor, local_player_id, remote_players)
    state.update(
        scenario_id=scenario_id, scenario=deepcopy(scenario),
        arena=deepcopy(ARENAS.get(scenario.get("arena"), {})),
        world_areas={}, world_area_items={}, world_area_chests={},
        chests=deepcopy(ARENAS.get(scenario.get("arena"), {}).get("chests", [])),
        ground_items=[], sync_only=True)
    state["actors"].update({entry["id"]: entry
                             for entry in _scenario_world_mobs(scenario_id)})
    return state

def _initiative_order(actors):
    rolls = {actor_id: initiative_for(entry["data"])
             for actor_id, entry in actors.items()}
    ordered = sorted(
        actors,
        key=lambda actor_id: (
            rolls[actor_id]["total"], rolls[actor_id]["dexterity"], actor_id
        ), reverse=True,
    )
    return [{"id": actor_id, **rolls[actor_id]} for actor_id in ordered]

COMBAT_TRIGGER_RANGE_FEET = campaign_rule("combat_trigger_range_feet", 20)
COMBAT_JOIN_RANGE_FEET = campaign_rule("combat_join_range_feet", 50)

CORPSE_DESPAWN_MS = campaign_rule("corpse_despawn_seconds", 3) * 1000

def _world_mob_from_entry(entry):
    """Convert an encounter enemy snapshot into persistent world-mob state."""
    return {
        "id": entry["id"], "team": "enemies", "x": entry["x"],
        "y": entry["y"], "width": entry.get("width", ACTOR_SIZE),
        "height": entry.get("height", ACTOR_SIZE),
        "downed": bool(entry.get("downed")),
        "data": deepcopy(entry.get("data", {})),
        "perception_info": deepcopy(entry.get("perception_info", {})),
        "corpse_despawn_at": entry.get("corpse_despawn_at"),
        "loot": deepcopy(entry.get("loot", [])),
        "patrol_origin": deepcopy(entry.get("patrol_origin")),
        "patrol_waypoint": entry.get("patrol_waypoint", 0),
    }

def _corpse_loot(entry):
    """Copy an NPC instance's carried and equipped gear into a shared drop list."""
    data = entry.get("data", {})
    items = [deepcopy(item) for item in data.get("inventory", [])]
    seen_ids = {item.get("id") for item in items if item.get("id") is not None}
    for slot, item in (data.get("equipment", {}) or {}).items():
        if item and item.get("id") not in seen_ids:
            dropped = deepcopy(item)
            dropped.setdefault("slot", slot)
            items.append(dropped)
            if item.get("id") is not None:
                seen_ids.add(item["id"])
    return items

def _mob_perception_info(template, npc):
    perception = deepcopy(template.get("perception", {}))
    if not npc.get("elite"):
        return perception
    levels = perception.setdefault("levels", [])
    if not levels:
        return perception
    final = max(levels, key=lambda level: int(level.get("dc", 10)))
    elite_bonus = max(0, int(MOB_GENERATION_RULES.get("elite", {}).get(
        "perception_dc_bonus", 3)))
    levels.append({
        "dc": int(final.get("dc", 10)) + elite_bonus,
        "title": f"Elite {final.get('title', npc.get('name', 'mob'))}",
    })
    return perception

def _random_mob_entry(arena, existing=(), players=(), mob_pool=None):
    """Create a fresh, equipped instance of a randomly selected NPC template."""
    if not NPCS:
        return None
    bounds = _arena_bounds(arena)
    obstacles = _arena_obstacles(arena)
    obstacles.extend(
        pygame.Rect(bed["x"], bed["y"], bed["width"], bed["height"])
        .inflate(160, 160)
        for bed in (arena or {}).get("inn_beds", []))
    occupied = [_actor_hitbox(item["x"], item["y"]) for item in existing]
    occupied.extend(_actor_hitbox(item["x"], item["y"]) for item in players)
    corpses = [item for item in existing
               if item.get("team") == "enemies" and item.get("downed")]
    if mob_pool is None:
        templates = list(NPCS.items())
    else:
        templates = [(npc_id, NPCS[npc_id]) for npc_id in mob_pool
                     if npc_id in NPCS]
    if not templates:
        return None
    random.shuffle(templates)
    spot = None
    for _ in range(80):
        x = random.randint(bounds.left, max(bounds.left, bounds.right - ACTOR_SIZE))
        y = random.randint(bounds.top, max(bounds.top, bounds.bottom - ACTOR_SIZE))
        box = _actor_hitbox(x, y)
        if not any(box.colliderect(rect) for rect in obstacles + occupied):
            # Keep the post-victory replacement mob outside the encounter
            # trigger radius so players can loot and move away before combat
            # starts again.
            candidate = {"x": x, "y": y, "width": ACTOR_SIZE,
                         "height": ACTOR_SIZE}
            safety_distance = COMBAT_TRIGGER_RANGE_FEET + 10
            if any(edge_distance_feet(candidate, player,
                                      PIXELS_PER_FOOT, ACTOR_SIZE)
                   <= safety_distance for player in players):
                continue
            # A replacement enemy must also stay clear of the corpses. A
            # player may need to cross the trigger radius while approaching
            # a body, especially after a ranged kill.
            if any(edge_distance_feet(candidate, corpse,
                                      PIXELS_PER_FOOT, ACTOR_SIZE)
                   <= safety_distance for corpse in corpses):
                continue
            spot = (x, y)
            break
    if spot is None:
        return None
    npc_id, definition = templates[0]
    npc = create_npc_instance(npc_id, spot[0], spot[1])
    mob_id = npc["id"]
    entry = _combat_snapshot(mob_id, npc, "enemies")
    entry["perception_info"] = _mob_perception_info(definition, npc)
    entry["width"] = entry["height"] = ACTOR_SIZE
    entry["patrol_origin"] = [spot[0], spot[1]]
    entry["patrol_waypoint"] = 0
    return entry


def combat_world_mobs(combat):
    """Collect engaged and non-engaged enemies into one persistent area list."""
    if not combat:
        return []
    mobs = [_world_mob_from_entry(entry)
            for entry in combat.get("actors", {}).values()
            if entry.get("team") == "enemies"]
    mobs.extend(deepcopy(combat.get("inactive_world_mobs", [])))
    return mobs


def advance_world_mob_patrol(combat, now):
    """Move idle enemies slowly around small four-point patrol loops."""
    if not combat or combat.get("active") or combat.get("rest_session"):
        return
    previous = combat.get("world_patrol_tick", now)
    elapsed = max(0, min(100, now - previous)) / 1000
    combat["world_patrol_tick"] = now
    if elapsed <= 0:
        return
    arena = combat.get("arena", {})
    enemies = [entry for entry in combat.get("actors", {}).values()
               if entry.get("team") == "enemies"]
    enemies.extend(combat.get("inactive_world_mobs", []))
    occupied = [_actor_hitbox(entry["x"], entry["y"])
                for entry in combat.get("actors", {}).values()
                if entry.get("team") == "players" and not entry.get("downed")]
    for entry in enemies:
        if entry.get("downed"):
            continue
        origin = entry.get("patrol_origin")
        if not isinstance(origin, (list, tuple)) or len(origin) < 2:
            origin = [entry["x"], entry["y"]]
            entry["patrol_origin"] = origin
        waypoints = (entry.get("patrol_waypoints_feet")
                     or entry.get("data", {}).get("patrol_waypoints_feet")
                     or campaign_setting("mob_patrol_waypoints_feet",
                                          [[0, 0], [11, 0], [11, 11], [0, 11]]))
        points = tuple((float(point[0]) * PIXELS_PER_FOOT,
                        float(point[1]) * PIXELS_PER_FOOT)
                       for point in waypoints
                       if isinstance(point, (list, tuple)) and len(point) >= 2)
        if not points:
            points = ((0, 0),)
        waypoint = int(entry.get("patrol_waypoint", 0)) % len(points)
        target_x = origin[0] + points[waypoint][0]
        target_y = origin[1] + points[waypoint][1]
        dx, dy = target_x - entry["x"], target_y - entry["y"]
        distance = math.hypot(dx, dy)
        speed = float(entry.get("patrol_speed_feet_per_second")
                       or entry.get("data", {}).get("patrol_speed_feet_per_second")
                       or campaign_rule("mob_patrol_speed_feet_per_second", 6))
        step = speed * PIXELS_PER_FOOT * elapsed
        if distance <= step or distance == 0:
            entry["patrol_waypoint"] = (waypoint + 1) % len(points)
            dx, dy = target_x - entry["x"], target_y - entry["y"]
            distance = math.hypot(dx, dy)
            step = min(step, distance)
        if distance:
            dx, dy = dx * min(1, step / distance), dy * min(1, step / distance)
            x, y = _walk_destination(
                entry["x"], entry["y"], dx, dy, arena, occupied)
            entry["x"], entry["y"] = x, y
            entry["data"]["x"], entry["data"]["y"] = x, y
        occupied.append(_actor_hitbox(entry["x"], entry["y"]))

def _new_combat(actor, local_player_id, remote_players, scenario_id=DEFAULT_SCENARIO,
                world_mobs=None):
    scenario = SCENARIOS.get(scenario_id)
    if scenario is None:
        raise ValueError(f"Unknown encounter scenario: {scenario_id}")
    actors = {local_player_id: _combat_snapshot(local_player_id, actor)}
    actors[local_player_id]["data"]["withdrawn"] = False
    for remote in remote_players:
        if remote.get("actor"):
            remote_id = remote.get("id", remote["actor"].get("id", "remote"))
            actors[remote_id] = _combat_snapshot(remote_id, remote["actor"])
            actors[remote_id]["data"]["withdrawn"] = False

    # Combat can be opened by a real-time attack. Preserve the exploration
    # positions so range and line of sight resolve where the attack was made;
    # resetting actors to scenario spawns here invalidates that opening attack.
    if world_mobs is None:
        enemy_sources = []
        for index, spawn in enumerate(scenario.get("enemies", [])):
            definition = NPCS.get(spawn.get("npc"))
            if definition is None:
                raise ValueError(f"Scenario {scenario_id!r} references missing NPC {spawn.get('npc')!r}")
            npc_id = spawn.get("id", f"{spawn.get('npc')}-{index + 1}")
            npc = create_npc_instance(
                spawn.get("npc"), spawn.get("x", definition.get("x", 600)),
                spawn.get("y", definition.get("y", 280)))
            npc["id"] = npc_id
            entry = _combat_snapshot(npc_id, npc, "enemies")
            entry["patrol_origin"] = [entry["x"], entry["y"]]
            entry["patrol_waypoint"] = 0
            enemy_sources.append(entry)
    else:
        enemy_sources = [deepcopy(entry) for entry in world_mobs]
    player_entries = [entry for entry in actors.values()
                      if entry.get("team") == "players" and not entry["downed"]]
    inactive_world_mobs = []
    nearby_enemy_sources = []
    for source in enemy_sources:
        distance = min((edge_distance_feet(player, source, PIXELS_PER_FOOT,
                                           ACTOR_SIZE)
                        for player in player_entries), default=float("inf"))
        if distance <= COMBAT_JOIN_RANGE_FEET:
            nearby_enemy_sources.append(source)
        else:
            inactive_world_mobs.append(_world_mob_from_entry(source))
    enemy_sources = nearby_enemy_sources
    for source in enemy_sources:
        npc_id = source["id"]
        npc = deepcopy(source["data"])
        npc.update(id=npc_id, x=source["x"], y=source["y"])
        npc["downed"] = bool(source.get("downed", npc.get("downed", False)))
        definition = NPCS.get(npc.get("template_id"), npc)
        npc.setdefault("max_hp", 10)
        npc.setdefault("current_hp", npc["max_hp"])
        npc.setdefault("downed", False)
        npc.setdefault("conditions", [])
        npc.setdefault("active_effects", [])
        npc.setdefault("abilities", {})
        npc.setdefault("equipment", {})
        npc.setdefault("inventory", [])
        # The snapshot deep copy isolates combat mutations; retain item IDs so
        # generated gear remains the same instance through combat and looting.
        entry = _combat_snapshot(npc_id, npc, "enemies")
        entry["perception_info"] = deepcopy(
            source.get("perception_info") or _mob_perception_info(definition, npc))
        entry["width"] = entry["height"] = ACTOR_SIZE
        if source.get("corpse_despawn_at"):
            entry["corpse_despawn_at"] = source["corpse_despawn_at"]
        if source.get("patrol_origin") is not None:
            entry["patrol_origin"] = deepcopy(source["patrol_origin"])
            entry["patrol_waypoint"] = source.get("patrol_waypoint", 0)
        if source.get("downed"):
            entry["loot"] = deepcopy(source.get("loot", []))
        actors[npc_id] = entry
    order = _initiative_order({
        key: entry for key, entry in actors.items() if not entry["downed"]
    })
    verbose_log = [
        (f"[DEBUG] Initiative: {actors[item['id']]['data'].get('name', item['id'])}: "
         f"d20 [{item['natural']}] -> {item['natural']} + Dexterity "
         f"{item['dexterity']:+} = {item['total']}.")
        for item in order
    ]
    return {
        "active": True, "round": 1, "order": order, "turn_index": 0,
        "removed_order": {},
        "actors": actors,
        "inactive_world_mobs": inactive_world_mobs,
        "ability_uses": {},
        "budgets": {
            key: {"movement": _movement_allowance(entry["data"]), "action": True,
                  "bonus_action": True, "reaction": True, "skip_next": False,
                  "condition_tick_done": False, "movement_used": 0}
            for key, entry in actors.items()
        },
        "log": [], "verbose_log": verbose_log, "scenario_id": scenario_id,
        "scenario": deepcopy(scenario),
        "arena": deepcopy(ARENAS.get(scenario.get("arena"), {})),
        "chests": deepcopy(ARENAS.get(scenario.get("arena"), {}).get("chests", [])),
        "world_area_chests": {},
        "result": None,
    }

def _combat_trigger(actor, local_player_id, remote_players,
                    scenario_id=DEFAULT_SCENARIO, world_mobs=None):
    """Return the first visible enemy/player pair within the encounter radius."""
    scenario = SCENARIOS.get(scenario_id, {})
    arena = ARENAS.get(scenario.get("arena"), {})
    players = [(local_player_id, _combat_snapshot(local_player_id, actor))]
    players.extend(
        (_player_id(remote), _combat_snapshot(_player_id(remote), remote["actor"]))
        for remote in remote_players if remote.get("actor")
    )
    if world_mobs is None:
        enemies = []
        for index, spawn in enumerate(scenario.get("enemies", [])):
            definition = NPCS.get(spawn.get("npc"))
            if not definition:
                continue
            enemy = deepcopy(definition)
            enemy_id = spawn.get("id", f"{spawn.get('npc')}-{index + 1}")
            enemy.update(id=enemy_id,
                         x=spawn.get("x", enemy.get("x", 600)),
                         y=spawn.get("y", enemy.get("y", 280)))
            enemy["downed"] = bool(enemy.get("downed", False)
                                   or enemy.get("current_hp", 1) <= 0)
            enemies.append(_combat_snapshot(enemy_id, enemy, "enemies"))
    else:
        sources = [entry for entry in world_mobs if not entry.get("downed")]
        enemies = [_combat_snapshot(entry["id"], entry["data"], "enemies")
                   for entry in sources]
        for source, enemy in zip((entry for entry in world_mobs
                                  if not entry.get("downed")), enemies):
            enemy["x"], enemy["y"] = source["x"], source["y"]
    for player_id, player in players:
        if player["downed"]:
            continue
        for enemy in enemies:
            if enemy["downed"]:
                continue
            if (edge_distance_feet(player, enemy, PIXELS_PER_FOOT, ACTOR_SIZE)
                    <= COMBAT_TRIGGER_RANGE_FEET
                    and _line_of_sight(player, enemy, arena)):
                stealth_total = (player["data"].get("stealth_check_total")
                                 if player["data"].get("sneaking") else None)
                hidden = player["data"].get("hidden")
                if isinstance(hidden, dict):
                    stealth_total = hidden.get("stealth_total")
                if (stealth_total is not None
                        and _perception_score(enemy["data"]) < int(stealth_total)):
                    continue
                return player_id, enemy["id"]
    return None


def settle_victory(combat, players):
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
            # Empty corpses have nothing to interact with, so start their
            # normal despawn countdown as soon as combat settles.
            entry["corpse_despawn_at"] = (
                pygame.time.get_ticks() + CORPSE_DESPAWN_MS
                if not entry["loot"] else None)
    arena = combat.get("arena", {})
    existing = combat_world_mobs(combat)
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
