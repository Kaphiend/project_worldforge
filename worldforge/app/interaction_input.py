"""Mouse and interaction-key handling for nearby world actors and objects."""
from copy import deepcopy

import pygame

from worldforge.app.world import ACTOR_SIZE, PIXELS_PER_FOOT, _target_clickbox
from worldforge.app.rendering import _player_id
from worldforge.combat.rules import edge_distance_feet
from worldforge.app.encounters import DEFAULT_SCENARIO
from worldforge.content.classes import SCENARIOS


def actor_at_world_position(position, actor, remote_players, world_actors=()):
    """Return the actor under a world-space right-click position."""
    own_rect = _target_clickbox(actor.x, actor.y)
    if own_rect.collidepoint(position):
        return vars(actor)
    for remote in reversed(remote_players):
        rect = _target_clickbox(remote.get("x", 0), remote.get("y", 0))
        if rect.collidepoint(position) and remote.get("actor"):
            return remote["actor"]
    for entry in reversed(list(world_actors)):
        if entry.get("team") != "enemies":
            continue
        rect = _target_clickbox(entry.get("x", 0), entry.get("y", 0))
        if rect.collidepoint(position):
            return deepcopy(entry)
    return None


def target_at_screen_position(position, actor, player_id, combat, remote_players,
                              drawn_positions, camera):
    """Resolve a left click to a local, enemy, or remote party target."""
    own_rect = _target_clickbox(actor.x - camera[0], actor.y - camera[1])
    if own_rect.collidepoint(position):
        return player_id, True
    enemies = list((combat or {}).get("actors", {}).values())
    if not combat:
        scenario = SCENARIOS.get(DEFAULT_SCENARIO, {})
        for index, spawn in enumerate(scenario.get("enemies", [])):
            enemies.append({
                "id": spawn.get("id", f"{spawn.get('npc')}-{index + 1}"),
                "team": "enemies", "x": spawn.get("x", 600),
                "y": spawn.get("y", 280), "width": ACTOR_SIZE,
                "height": ACTOR_SIZE,
            })
    for enemy in enemies:
        if enemy.get("team") != "enemies":
            continue
        rect = _target_clickbox(enemy["x"] - camera[0],
                                enemy["y"] - camera[1])
        if rect.collidepoint(position):
            return enemy["id"], True
    for remote in reversed(remote_players):
        player_key = _player_id(remote)
        target_position = drawn_positions.get(player_key)
        if target_position is None:
            target_position = (remote.get("x", 0), remote.get("y", 0))
        if _target_clickbox(*target_position).collidepoint(position):
            return player_key, True
    return None, False


def interact_nearby(actor, player_id, current_arena, combat, submit,
                    trainer_ui, vendor_ui, loot_ui):
    """Resolve the nearest nearby interaction and open its UI or submit it."""
    nearby = []
    interaction_actor = dict(vars(actor))
    local_entry = (combat or {}).get("actors", {}).get(player_id)
    if local_entry:
        interaction_actor["hitbox"] = deepcopy(
            local_entry.get("data", {}).get("hitbox"))
    interaction_actor["x"], interaction_actor["y"] = actor.x, actor.y
    for kind, items in (("trainer", current_arena.get("trainers", [])),
                        ("vendor", current_arena.get("vendors", [])),
                        ("camp_bed", current_arena.get("camp_beds", [])),
                        ("inn_bed", current_arena.get("inn_beds", [])),
                        ("exit", current_arena.get("exits", []))):
        for item in items:
            distance = edge_distance_feet(
                interaction_actor, item, PIXELS_PER_FOOT, ACTOR_SIZE)
            if distance <= int(item.get("interaction_range_feet", 5)):
                nearby.append((distance, kind, item))
    if (combat and not combat.get("active")
            and not combat.get("rest_session")):
        for ground_item in combat.get("ground_items", []):
            distance = edge_distance_feet(
                interaction_actor, ground_item, PIXELS_PER_FOOT, ACTOR_SIZE)
            if distance <= 5:
                nearby.append((distance, "ground_item", ground_item))
    for corpse in (combat or {}).get("actors", {}).values():
        if (combat and combat.get("active")
                or corpse.get("team") != "enemies"
                or not corpse.get("downed")):
            continue
        expiry = corpse.get("corpse_despawn_at")
        if expiry is not None and pygame.time.get_ticks() >= expiry:
            continue
        distance = edge_distance_feet(
            interaction_actor, corpse, PIXELS_PER_FOOT, ACTOR_SIZE)
        if distance <= 5:
            nearby.append((distance, "loot", corpse))

    interaction = min(nearby, default=None, key=lambda item: item[0])
    if not interaction:
        return None, "There is nothing nearby to interact with.", 2000
    kind, item = interaction[1], interaction[2]
    if kind == "trainer":
        trainer_ui.toggle(vars(actor))
    elif kind == "vendor":
        vendor_ui.open(item["id"])
    elif kind == "camp_bed":
        submit({"type": "rest_camp_checkin", "bed_id": item.get("id")})
    elif kind == "loot":
        if item.get("loot"):
            loot_ui.open(item["id"])
        else:
            # Start cleanup for legacy or partially synchronized empty corpses.
            submit({"type": "loot_finish", "target": item["id"]})
            return (None,
                    "There is nothing to loot. The empty corpse will disappear shortly.",
                    2400)
    elif kind == "ground_item":
        submit({"type": "pickup_ground_item", "item_id": item.get("id")})
    elif kind == "exit":
        return ({"type": "area_exit", "name": item.get("name", "Area Exit"),
                 "exit_id": item.get("id")}, None, 0)
    else:
        return ({"type": "inn_bed", "name": item.get("name", "Inn Bed"),
                 "bed_id": item.get("id")}, None, 0)
    return None, None, 0
