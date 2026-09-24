"""Encounter setup, mob lifecycle, and combat snapshot helpers."""
from copy import deepcopy
import random
import uuid

from worldforge.actors.factory import create_npc_instance
from worldforge.app.rendering import _player_id
from worldforge.app.world import (ACTOR_HITBOX_HEIGHT, ACTOR_HITBOX_WIDTH,
                                  ACTOR_SIZE, PIXELS_PER_FOOT, _actor_hitbox,
                                  _arena_bounds, _arena_obstacles,
                                  _line_of_sight, _movement_allowance)
from worldforge.combat.rules import edge_distance_feet, initiative_for
from worldforge.content.classes import (ARENAS, MOB_GENERATION_RULES, NPCS,
                                        SCENARIOS)
from worldforge.core.progression import initialize_resources

def _actor_data(actor):
    return deepcopy(vars(actor)) if not isinstance(actor, dict) else deepcopy(actor)

def _combat_snapshot(actor_id, data, team="players"):
    data = _actor_data(data)
    initialize_resources(data)
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

def _initiative_order(actors):
    rolls = {actor_id: initiative_for(entry["data"])
             for actor_id, entry in actors.items()}
    while True:
        ordered = sorted(
            actors,
            key=lambda actor_id: (
                rolls[actor_id]["total"], rolls[actor_id]["dexterity"]
            ), reverse=True,
        )
        tied = []
        for first, second in zip(ordered, ordered[1:]):
            a, b = rolls[first], rolls[second]
            if a["total"] == b["total"] and a["dexterity"] == b["dexterity"]:
                tied.extend((first, second))
        if not tied:
            return [{"id": actor_id, **rolls[actor_id]} for actor_id in ordered]
        for actor_id in set(tied):
            reroll = initiative_for(actors[actor_id]["data"])
            rolls[actor_id] = reroll

DEFAULT_SCENARIO = "first_contact"

COMBAT_TRIGGER_RANGE_FEET = 20

CORPSE_DESPAWN_MS = 3_000

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

def _random_mob_entry(arena, existing=(), players=()):
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
    templates = list(NPCS.items())
    random.shuffle(templates)
    spot = None
    for _ in range(80):
        x = random.randint(bounds.left, max(bounds.left, bounds.right - ACTOR_SIZE))
        y = random.randint(bounds.top, max(bounds.top, bounds.bottom - ACTOR_SIZE))
        box = _actor_hitbox(x, y)
        if not any(box.colliderect(rect) for rect in obstacles + occupied):
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
    return entry

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
            enemy_sources.append(_combat_snapshot(npc_id, npc, "enemies"))
    else:
        enemy_sources = [deepcopy(entry) for entry in world_mobs]
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
        if source.get("downed"):
            entry["loot"] = deepcopy(source.get("loot", []))
        actors[npc_id] = entry
    order = _initiative_order({
        key: entry for key, entry in actors.items() if not entry["downed"]
    })
    return {
        "active": True, "round": 1, "order": order, "turn_index": 0,
        "removed_order": {},
        "actors": actors,
        "ability_uses": {},
        "budgets": {
            key: {"movement": _movement_allowance(entry["data"]), "action": True,
                  "bonus_action": True, "skip_next": False,
                  "condition_tick_done": False}
            for key, entry in actors.items()
        },
        "log": [], "scenario_id": scenario_id,
        "scenario": deepcopy(scenario),
        "arena": deepcopy(ARENAS.get(scenario.get("arena"), {})),
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
                return player_id, enemy["id"]
    return None
