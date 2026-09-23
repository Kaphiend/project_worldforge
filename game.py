"""Pygame gameplay loop."""
import math
import sys
from pprint import pprint
from copy import deepcopy
import uuid

import pygame

from combat import attack as resolve_attack
from combat import (distance_feet, edge_distance_feet, initiative_for,
                    selected_weapon, speed_feet)
from classes import ABILITIES, SPELLS, ARENAS, NPCS, SCENARIOS
from controllers import controller_for
from conditions import condition_names, has_condition, tick_conditions
from sprite_sheet import load_spritesheet
from spell_effects import apply_ability_effects, resolve_spell
from storage import save_actor


def _print_character_sheet(actor_data):
    print(f"Character sheet: {actor_data.get('name', 'Other player')}")
    pprint(actor_data)
    sys.stdout.flush()


def _copy_invite(text):
    try:
        pygame.scrap.init()
        pygame.scrap.put(pygame.SCRAP_TEXT, text.encode('utf-8') + b'\0')
        return True
    except (AttributeError, pygame.error):
        return False


def _handle_right_click(position, actor, remote_players, sprite_frames, multiplayer):
    own_rect = _target_clickbox(actor.x, actor.y)
    if own_rect.collidepoint(position):
        _print_character_sheet(vars(actor))
        return
    for remote in reversed(remote_players):
        rect = _target_clickbox(remote.get("x", 0), remote.get("y", 0))
        if rect.collidepoint(position) and remote.get("actor"):
            _print_character_sheet(remote["actor"])
            return


def _arena_bounds(arena):
    data = (arena or {}).get("bounds", {"x": 0, "y": 0, "width": 800, "height": 600})
    return pygame.Rect(data["x"], data["y"], data["width"], data["height"])


def _arena_obstacles(arena):
    return [pygame.Rect(item["x"], item["y"], item["width"], item["height"])
            for item in (arena or {}).get("obstacles", [])]


def _move_actor(actor, keys, speed, facing_left, arena, occupied=()):
    dx = int(bool(keys[pygame.K_RIGHT] or keys[pygame.K_d])) - int(
        bool(keys[pygame.K_LEFT] or keys[pygame.K_a]))
    dy = int(bool(keys[pygame.K_DOWN] or keys[pygame.K_s])) - int(
        bool(keys[pygame.K_UP] or keys[pygame.K_w]))
    if not dx and not dy:
        return False, facing_left
    moving_left = dx < 0
    if dx:
        facing_left = moving_left
    # Keep diagonal movement at the same speed as straight movement.
    scale = speed / math.hypot(dx, dy)
    dx, dy = round(dx * scale), round(dy * scale)
    bounds = _arena_bounds(arena)
    obstacles = _arena_obstacles(arena) + list(occupied)
    for axis, amount in (("x", dx), ("y", dy)):
        if not amount:
            continue
        current = getattr(actor, axis)
        candidate = current + amount
        limit = (bounds.left, bounds.right - ACTOR_SIZE) if axis == "x" else (
            bounds.top, bounds.bottom - ACTOR_SIZE)
        candidate = max(limit[0], min(limit[1], candidate))
        rect = _actor_hitbox(candidate if axis == "x" else actor.x,
                             candidate if axis == "y" else actor.y)
        if not any(rect.colliderect(obstacle) for obstacle in obstacles):
            setattr(actor, axis, candidate)
    return True, facing_left


def _camera_offset(actor, arena, viewport=(800, 600)):
    bounds = _arena_bounds(arena)
    width, height = viewport
    max_x = max(bounds.left, bounds.right - width)
    max_y = max(bounds.top, bounds.bottom - height)
    x = actor.x + ACTOR_SIZE / 2 - width / 2
    y = actor.y + ACTOR_SIZE / 2 - height / 2
    return round(max(bounds.left, min(max_x, x))), round(max(bounds.top, min(max_y, y)))


def _walk_destination(x, y, dx, dy, arena, occupied=()):
    bounds = _arena_bounds(arena)
    obstacles = _arena_obstacles(arena) + list(occupied)
    distance = math.hypot(dx, dy)
    steps = max(1, math.ceil(distance / 6))
    start_x, start_y = x, y
    target_x, target_y = start_x + dx, start_y + dy
    for step in range(1, steps + 1):
        candidate_x = x + dx / steps
        candidate_y = y + dy / steps
        candidate_x = max(bounds.left, min(bounds.right - ACTOR_SIZE, candidate_x))
        candidate_y = max(bounds.top, min(bounds.bottom - ACTOR_SIZE, candidate_y))
        rect = _actor_hitbox(candidate_x, candidate_y)
        if any(rect.colliderect(obstacle) for obstacle in obstacles):
            slides = [(candidate_x, y), (x, candidate_y)]
            clear_slides = [point for point in slides if not any(
                _actor_hitbox(point[0], point[1])
                .colliderect(obstacle) for obstacle in obstacles)]
            if not clear_slides:
                break
            candidate_x, candidate_y = min(
                clear_slides,
                key=lambda point: math.hypot(target_x - point[0], target_y - point[1]))
        x, y = candidate_x, candidate_y
    return x, y


def _advance_animation(animation, requested, dt, sprite_frames, frame_duration):
    if requested not in sprite_frames:
        requested = "idle"
    if requested != animation["anim"]:
        animation.update(anim=requested, index=0, time=0)
    animation["time"] += dt
    while animation["time"] >= frame_duration:
        animation["time"] -= frame_duration
        animation["index"] = (animation["index"] + 1) % len(sprite_frames[requested])
    return sprite_frames[requested][animation["index"]]


def _advance_character_animation(state, requested, event, dt, sprite_frames,
                                 frame_duration):
    if requested not in sprite_frames:
        requested = "idle"
    if requested == "dead":
        if event:
            state["event_serial"] = event.get("serial", state.get("event_serial"))
        if state.get("anim") != "dead":
            state.update(anim="dead", index=0, time=0, one_shot=False)
        frames = sprite_frames["dead"]
        state["time"] += dt
        while state["time"] >= frame_duration and state["index"] < len(frames) - 1:
            state["time"] -= frame_duration
            state["index"] += 1
        return frames[state["index"]]

    if event and event.get("serial") != state.get("event_serial"):
        state["event_serial"] = event.get("serial")
        name = event.get("name", "idle")
        if name == "idle":
            state.update(anim="idle", index=0, time=0, one_shot=False)
            state["event_duration"] = None
        elif name == "walk" and event.get("duration_ms"):
            state.update(anim="walk", index=0, time=0, one_shot=True,
                         event_elapsed=0)
            state["event_duration"] = event["duration_ms"]
        elif name in sprite_frames:
            state.update(anim=name, index=0, time=0, one_shot=True,
                         event_elapsed=0)
            state["event_duration"] = event.get("duration_ms")

    if state.get("one_shot"):
        name = state["anim"]
        frames = sprite_frames.get(name) or sprite_frames["idle"]
        state["time"] += dt
        state["event_elapsed"] = state.get("event_elapsed", 0) + dt
        while state["time"] >= frame_duration:
            state["time"] -= frame_duration
            if name == "walk":
                state["index"] = (state["index"] + 1) % len(frames)
            elif state["index"] + 1 < len(frames):
                state["index"] += 1
            else:
                state["one_shot"] = False
                break
        duration = state.get("event_duration")
        if duration is not None and state.get("event_elapsed", 0) >= duration:
            state["one_shot"] = False
        if state.get("one_shot"):
            return frames[state["index"]]

    return _advance_animation(state, requested, dt, sprite_frames, frame_duration)


def _emit_animation(combat, actor_id, name, duration_ms=None):
    entry = combat.get("actors", {}).get(actor_id)
    if not entry:
        return
    previous = entry.get("animation_event", {})
    entry["animation_event"] = {
        "name": name,
        "serial": int(previous.get("serial", 0)) + 1,
        "duration_ms": duration_ms,
    }


def _capture_hp(combat):
    return {actor_id: (entry["data"].get("current_hp", 0), entry["downed"])
            for actor_id, entry in combat.get("actors", {}).items()}


def _animate_hp_changes(combat, before):
    for actor_id, entry in combat.get("actors", {}).items():
        old_hp, old_downed = before.get(
            actor_id, (entry["data"].get("current_hp", 0), entry["downed"]))
        new_hp = entry["data"].get("current_hp", 0)
        entry["downed"] = bool(entry["downed"] or new_hp <= 0)
        if new_hp < old_hp:
            _emit_animation(combat, actor_id,
                            "dead" if entry["downed"] else "hurt")
        elif old_downed and not entry["downed"]:
            _emit_animation(combat, actor_id, "idle")


def _player_id(remote):
    return remote.get("id", str((remote.get("actor") or {}).get("id", "remote")))


def _smooth_remote_position(remote, positions, dt):
    player_id = _player_id(remote)
    target_x = float(remote.get("x", 0))
    target_y = float(remote.get("y", 0))
    position = positions.get(player_id)
    if position is None:
        position = {"x": target_x, "y": target_y}
        positions[player_id] = position
    else:
        # Ease toward each network snapshot over roughly 60 ms.
        amount = 1 - math.exp(-dt / 60)
        position["x"] += (target_x - position["x"]) * amount
        position["y"] += (target_y - position["y"]) * amount
    return position["x"], position["y"]


def _draw_players(screen, actor, local_sprite, remote_players, remote_animations,
                  remote_positions, dt, sprite_frames, frame_duration, arena=None,
                  camera=(0, 0)):
    arena = arena or {}
    camera_x, camera_y = camera
    screen.fill(tuple(arena.get("edge_color", [34, 49, 40])))
    bounds_data = arena.get("bounds", {"x": 0, "y": 0, "width": 800, "height": 600})
    bounds = pygame.Rect(bounds_data["x"], bounds_data["y"],
                         bounds_data["width"], bounds_data["height"])
    screen.fill(tuple(arena.get("ground_color", [64, 91, 67])),
                bounds.move(-camera_x, -camera_y))
    for decoration in arena.get("decorations", []):
        if decoration.get("kind") == "rect":
            pygame.draw.rect(screen, tuple(decoration.get("color", [80, 80, 80])),
                             pygame.Rect(decoration["x"] - camera_x,
                                         decoration["y"] - camera_y,
                                         decoration["width"], decoration["height"]))
    for obstacle in _arena_obstacles(arena):
        visible_obstacle = obstacle.move(-camera_x, -camera_y)
        pygame.draw.rect(screen, (67, 70, 58), visible_obstacle)
        pygame.draw.rect(screen, (117, 112, 86), visible_obstacle, 3)
    screen.blit(local_sprite, (round(actor.x - camera_x), round(actor.y - camera_y)))
    drawn_positions = {}
    for remote in remote_players:
        player_id = _player_id(remote)
        x, y = _smooth_remote_position(remote, remote_positions, dt)
        screen_x, screen_y = x - camera_x, y - camera_y
        drawn_positions[player_id] = (screen_x, screen_y)
        animation = remote_animations.setdefault(
            player_id, {"anim": "idle", "index": 0, "time": 0})
        remote_frames = next(iter(sprite_frames.values()))
        avatar = (remote.get("actor") or {}).get("avatar")
        if avatar in sprite_frames:
            remote_frames = sprite_frames[avatar]
        requested = "dead" if remote.get("downed") else remote.get("anim", "idle")
        remote_sprite = _advance_character_animation(
            animation, requested, remote.get("combat_animation"), dt,
            remote_frames, frame_duration)
        if remote.get("facing"):
            remote_sprite = pygame.transform.flip(remote_sprite, True, False)
        screen.blit(remote_sprite, (round(screen_x), round(screen_y)))
    return drawn_positions


PIXELS_PER_FOOT = 4
ACTOR_SIZE = 100
ACTOR_HITBOX_WIDTH = 40
ACTOR_HITBOX_HEIGHT = 48
TARGET_CLICK_WIDTH = 52
TARGET_CLICK_HEIGHT = 60


def _actor_hitbox(x, y):
    return pygame.Rect(round(x + (ACTOR_SIZE - ACTOR_HITBOX_WIDTH) / 2),
                       round(y + (ACTOR_SIZE - ACTOR_HITBOX_HEIGHT) / 2),
                       ACTOR_HITBOX_WIDTH, ACTOR_HITBOX_HEIGHT)


def _target_clickbox(x, y):
    return pygame.Rect(round(x + (ACTOR_SIZE - TARGET_CLICK_WIDTH) / 2),
                       round(y + (ACTOR_SIZE - TARGET_CLICK_HEIGHT) / 2),
                       TARGET_CLICK_WIDTH, TARGET_CLICK_HEIGHT)


def _movement_allowance(actor_data):
    bonus = sum(int(effect.get("feet", 0))
                for effect in actor_data.get("active_effects", [])
                if effect.get("kind") == "movement_bonus")
    return speed_feet(actor_data) + bonus


def _actor_data(actor):
    return deepcopy(vars(actor)) if not isinstance(actor, dict) else deepcopy(actor)


def _combat_snapshot(actor_id, data, team="players"):
    data = _actor_data(data)
    hitbox = {"offset_x": (ACTOR_SIZE - ACTOR_HITBOX_WIDTH) / 2,
              "offset_y": (ACTOR_SIZE - ACTOR_HITBOX_HEIGHT) / 2,
              "width": ACTOR_HITBOX_WIDTH, "height": ACTOR_HITBOX_HEIGHT}
    data["hitbox"] = hitbox
    return {"id": actor_id, "team": team, "data": data, "hitbox": hitbox,
            "x": float(data.get("x", 0)), "y": float(data.get("y", 0)),
            "width": ACTOR_SIZE, "height": ACTOR_SIZE,
            "downed": bool(data.get("downed", False) or data.get("current_hp", 1) <= 0)}


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


def _add_joined_players(combat, remote_players):
    """Add players who accept an invite after combat has already begun."""
    additions = []
    for remote in remote_players:
        actor_data = remote.get('actor')
        actor_id = _player_id(remote)
        if not actor_data or actor_id in combat['actors']:
            continue
        entry = _combat_snapshot(actor_id, actor_data, 'players')
        combat['actors'][actor_id] = entry
        combat['budgets'][actor_id] = {
            'movement': _movement_allowance(entry['data']), 'action': True,
            'bonus_action': True, 'skip_next': False,
            'condition_tick_done': False,
        }
        additions.append(actor_id)
    if not additions:
        return

    active_id = _active_actor_id(combat)
    eligible = {actor_id: entry for actor_id, entry in combat['actors'].items()
                if not entry['downed']}
    rolls = {entry['id']: {key: entry[key] for key in ('total', 'natural', 'dexterity')}
             for entry in combat['order']}
    for actor_id in additions:
        if actor_id in eligible:
            rolls[actor_id] = initiative_for(eligible[actor_id]['data'])
    while True:
        tied = set()
        by_roll = {}
        for actor_id, roll in rolls.items():
            by_roll.setdefault((roll['total'], roll['dexterity']), []).append(actor_id)
        for group in by_roll.values():
            if len(group) > 1:
                tied.update(group)
        if not tied:
            break
        for actor_id in tied:
            rolls[actor_id] = initiative_for(eligible[actor_id]['data'])
    combat['order'] = [
        {'id': actor_id, **roll}
        for actor_id, roll in sorted(
            rolls.items(), key=lambda pair: (pair[1]['total'], pair[1]['dexterity']),
            reverse=True)
    ]
    if active_id in [entry['id'] for entry in combat['order']]:
        combat['turn_index'] = next(
            index for index, entry in enumerate(combat['order'])
            if entry['id'] == active_id)
    for actor_id in additions:
        _log(combat, f"{combat['actors'][actor_id]['data'].get('name', actor_id)} joins the party.")


def _remove_disconnected_players(combat, remote_players, host_id):
    connected = {_player_id(remote) for remote in remote_players}
    active_id = _active_actor_id(combat)
    old_index = combat.get('turn_index', 0)
    removed = [
        actor_id for actor_id, entry in combat['actors'].items()
        if entry['team'] == 'players' and actor_id != host_id
        and actor_id not in connected
    ]
    for actor_id in removed:
        name = combat['actors'][actor_id]['data'].get('name', actor_id)
        combat['actors'].pop(actor_id, None)
        combat['budgets'].pop(actor_id, None)
        combat.setdefault('removed_order', {}).pop(actor_id, None)
        combat['order'] = [entry for entry in combat['order']
                           if entry['id'] != actor_id]
        _log(combat, f"{name} disconnected and left the party.")
    if not any(entry['team'] == 'players' for entry in combat['actors'].values()):
        combat['active'] = False
        return
    remaining_ids = [entry['id'] for entry in combat['order']]
    if active_id in remaining_ids:
        combat['turn_index'] = remaining_ids.index(active_id)
    elif remaining_ids:
        combat['turn_index'] = min(old_index, len(remaining_ids) - 1)
    else:
        combat['active'] = False


DEFAULT_SCENARIO = "first_contact"


def _new_combat(actor, local_player_id, remote_players, scenario_id=DEFAULT_SCENARIO):
    scenario = SCENARIOS.get(scenario_id)
    if scenario is None:
        raise ValueError(f"Unknown encounter scenario: {scenario_id}")
    actors = {local_player_id: _combat_snapshot(local_player_id, actor)}
    for remote in remote_players:
        if remote.get("actor"):
            remote_id = remote.get("id", remote["actor"].get("id", "remote"))
            actors[remote_id] = _combat_snapshot(remote_id, remote["actor"])

    player_spawns = scenario.get("player_spawns", [])
    for index, (player_key, entry) in enumerate(actors.items()):
        if player_spawns:
            entry["x"], entry["y"] = player_spawns[min(index, len(player_spawns) - 1)]
    for index, spawn in enumerate(scenario.get("enemies", [])):
        definition = NPCS.get(spawn.get("npc"))
        if definition is None:
            raise ValueError(f"Scenario {scenario_id!r} references missing NPC {spawn.get('npc')!r}")
        npc = deepcopy(definition)
        npc_id = spawn.get("id", f"{spawn.get('npc')}-{index + 1}")
        npc["id"] = npc_id
        npc["x"], npc["y"] = spawn.get("x", npc.get("x", 600)), spawn.get("y", npc.get("y", 280))
        npc.setdefault("max_hp", 10)
        npc.setdefault("current_hp", npc["max_hp"])
        npc.setdefault("downed", False)
        npc.setdefault("conditions", [])
        npc.setdefault("active_effects", [])
        npc.setdefault("abilities", {})
        npc.setdefault("equipment", {})
        npc.setdefault("inventory", [])
        # Re-key template-backed items for independent NPC instances.
        for equipped in npc["equipment"].values():
            if equipped:
                equipped["id"] = uuid.uuid4().hex[:12]
        entry = _combat_snapshot(npc_id, npc, "enemies")
        entry["width"] = entry["height"] = ACTOR_SIZE
        actors[npc_id] = entry
    order = _initiative_order({
        key: entry for key, entry in actors.items() if not entry["downed"]
    })
    return {
        "active": True, "round": 1, "order": order, "turn_index": 0,
        "removed_order": {},
        "actors": actors,
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


def _do_spell(combat, actor_id, spell_id, target_id=None):
    actor_entry = combat['actors'].get(actor_id)
    if not actor_entry or actor_entry['downed']:
        return False
    spell = SPELLS.get(spell_id)
    if not spell:
        _log(combat, 'Unknown spell.')
        return False
    budget = combat['budgets'][actor_id]
    if not budget.get('action'):
        _log(combat, 'Action already used this turn.')
        return False
    caster = actor_entry['data']
    target_info = spell.get('targeting', {})
    target_entry = combat['actors'].get(target_id) if target_id else None
    mode = target_info.get('mode')
    if mode not in ('self',) and not target_entry:
        _log(combat, 'Select a target first.')
        return False
    targets = [target_entry['data']] if target_entry else None
    point = None
    if mode == 'small_area':
        point = (target_entry['x'] + target_entry['width'] / 2,
                 target_entry['y'] + target_entry['height'] / 2)
        radius = int(target_info.get('radius_feet', 0)) * PIXELS_PER_FOOT
        targets = [entry['data'] for entry in combat['actors'].values()
                   if math.hypot(entry['x'] + entry['width'] / 2 - point[0],
                                 entry['y'] + entry['height'] / 2 - point[1]) <= radius]
    if mode == 'self':
        targets = [caster]
    hp_before = _capture_hp(combat)
    result = resolve_spell(spell_id, caster, targets,
                           target_position=point, line_of_sight=True)
    if not result.get('success'):
        _log(combat, result.get('message', 'Spell failed.'))
        return False
    budget['action'] = False
    for item in result['results']:
        details = []
        roll = item.get('roll')
        if roll:
            details.append(f"roll {roll.get('natural')} = {roll.get('total')}")
        for effect in item.get('effects', []):
            if effect.get('kind') == 'damage':
                details.append(f"{effect['amount']} {effect.get('damage_type', 'untyped')} damage")
            elif effect.get('kind') == 'healing':
                details.append(f"{effect['amount']} healing")
            elif effect.get('kind') == 'condition':
                details.append(effect['condition'].replace('_', ' '))
        suffix = '; ' + ', '.join(details) if details else ''
        _log(combat, f"{caster.get('name', 'Caster')} casts {spell['name']} on {item['target']}{suffix}.")
    for entry in combat['actors'].values():
        entry['downed'] = bool(
            entry['data'].get('downed', False)
            or entry['data'].get('current_hp', 1) <= 0)
    _remove_downed_from_order(combat)
    _restore_revived_order(combat)
    _animate_hp_changes(combat, hp_before)
    if all(entry['downed'] for entry in combat['actors'].values()
           if entry['team'] == 'enemies'):
        combat['active'] = False
        _log(combat, 'All enemies defeated. Combat ended.')
        combat["result"] = {"outcome": "victory", "message": combat.get("scenario", {}).get("victory", "Encounter complete.")}
    return True


def _do_ability(combat, actor_id, ability_id, target_id=None):
    actor_entry = combat['actors'].get(actor_id)
    ability = ABILITIES.get(ability_id)
    if not actor_entry or actor_entry['downed'] or not ability:
        return False
    actor_data = actor_entry['data']
    if ability_id not in actor_data.get('known_abilities', []):
        _log(combat, 'That ability is not available to this character.')
        return False
    target_info = ability.get('targeting', {})
    target_entry = combat['actors'].get(target_id) if target_id else None
    if target_info and target_info.get('mode') != 'self' and not target_entry:
        _log(combat, 'Select a target first.')
        return False
    if target_entry and target_info.get('range_feet') is not None:
        if edge_distance_feet(actor_entry, target_entry) > target_info['range_feet']:
            _log(combat, 'Target is outside ability range.')
            return False
    budget = combat['budgets'][actor_id]
    cost = ability.get('action_cost', 'action')
    if not budget.get(cost, False):
        _log(combat, f"{cost.replace('_', ' ').title()} already used this turn.")
        return False
    try:
        hp_before = _capture_hp(combat)
        effect_target = (target_entry['data']
                         if target_entry and target_info.get('mode') != 'self'
                         else actor_data)
        effects = apply_ability_effects(ability_id, actor_data, effect_target)
    except (KeyError, ValueError) as exc:
        _log(combat, f'Ability unavailable: {exc}')
        return False
    budget[cost] = False
    _log(combat, f"{actor_data.get('name', 'Actor')} uses {ability['name']}.")
    _animate_hp_changes(combat, hp_before)
    enemies = [entry for entry in combat["actors"].values()
               if entry["team"] == "enemies"]
    if enemies and all(entry["downed"] or entry["data"].get("current_hp", 1) <= 0
                       for entry in enemies):
        combat["active"] = False
        combat["result"] = {"outcome": "victory", "message": combat.get("scenario", {}).get("victory", "Encounter complete.")}
        _log(combat, "All enemies defeated. Combat ended.")
    return bool(effects) or not ability.get('effects')


def _log(combat, message):
    combat.setdefault("log", []).append(message)
    combat["log"] = combat["log"][-8:]


def _active_actor_id(combat):
    if not combat or not combat.get("active") or not combat.get("order"):
        return None
    return combat["order"][combat["turn_index"]]["id"]


def _advance_turn(combat):
    if not combat or not combat.get("active"):
        return
    previous_id = _active_actor_id(combat)
    if previous_id:
        previous = combat["actors"][previous_id]
        events = tick_conditions(previous["data"], "end")
        for event in events:
            if event.get("expired"):
                _log(combat, f"{event['condition'].replace('_', ' ').title()} fades.")
    for _ in range(len(combat["order"]) * 2):
        combat["turn_index"] += 1
        if combat["turn_index"] >= len(combat["order"]):
            combat["turn_index"] = 0
            combat["round"] += 1
        entry = combat["order"][combat["turn_index"]]
        actor_id = entry["id"]
        actor = combat["actors"][actor_id]
        budget = combat["budgets"][actor_id]
        if actor["downed"] or actor["data"].get("current_hp", 1) <= 0:
            _log(combat, f"{actor['data'].get('name', actor_id)} is downed; turn skipped.")
            continue
        if budget.pop("skip_next", False):
            _log(combat, f"{actor['data'].get('name', actor_id)} skips their first turn.")
            continue
        budget.update(movement=_movement_allowance(actor["data"]), action=True,
                      bonus_action=True, condition_tick_done=False)
        return
    _log(combat, "No active actors can take a turn.")
    combat["active"] = False


def _remove_downed_from_order(combat):
    """Keep downed PCs in the world state, but remove them from initiative."""
    active_id = _active_actor_id(combat)
    old_index = combat.get("turn_index", 0)
    removed = combat.setdefault('removed_order', {})
    for entry in combat.get('order', []):
        if combat['actors'][entry['id']]['downed']:
            removed[entry['id']] = entry
    combat["order"] = [entry for entry in combat.get("order", [])
                       if not combat["actors"][entry["id"]]["downed"]]
    if not combat["order"]:
        combat["active"] = False
        combat["turn_index"] = 0
        return
    remaining_ids = [entry["id"] for entry in combat["order"]]
    if active_id in remaining_ids:
        combat["turn_index"] = remaining_ids.index(active_id)
    elif old_index >= len(remaining_ids):
        combat["turn_index"] = 0
        combat["round"] += 1
    else:
        combat["turn_index"] = old_index


def _restore_revived_order(combat):
    active_id = _active_actor_id(combat)
    removed = combat.setdefault('removed_order', {})
    for actor_id, initiative in list(removed.items()):
        actor = combat['actors'][actor_id]
        if actor['downed'] or actor['data'].get('current_hp', 0) <= 0:
            continue
        combat['order'].append(initiative)
        combat['order'].sort(
            key=lambda entry: (entry['total'], entry['dexterity']), reverse=True)
        del removed[actor_id]
    if active_id in [entry['id'] for entry in combat['order']]:
        combat['turn_index'] = next(
            index for index, entry in enumerate(combat['order'])
            if entry['id'] == active_id)


def _process_turn_start(combat):
    """Apply start-of-turn condition primitives once on the authoritative host."""
    actor_id = _active_actor_id(combat)
    if actor_id is None:
        return
    budget = combat["budgets"][actor_id]
    if budget.get("condition_tick_done"):
        return
    budget["condition_tick_done"] = True
    entry = combat["actors"][actor_id]
    hp_before = _capture_hp(combat)
    for event in tick_conditions(entry["data"], "start"):
        _log(combat, (f"{entry['data'].get('name', actor_id)} takes {event['damage']} "
                      f"{event.get('damage_type', 'untyped')} damage from "
                      f"{event['condition'].replace('_', ' ')}."))
    _animate_hp_changes(combat, hp_before)
    if entry["data"].get("current_hp", 1) <= 0:
        entry["downed"] = True
        _log(combat, f"{entry['data'].get('name', actor_id)} is downed.")
        _remove_downed_from_order(combat)
        enemies = [actor for actor in combat["actors"].values()
                   if actor["team"] == "enemies"]
        if enemies and all(enemy["downed"] for enemy in enemies):
            combat["active"] = False
            _log(combat, "All enemies defeated. Combat ended.")
            combat["result"] = {"outcome": "victory", "message": combat.get("scenario", {}).get("victory", "Encounter complete.")}
            return
        if combat.get("active"):
            next_id = _active_actor_id(combat)
            next_entry = combat["actors"][next_id]
            combat["budgets"][next_id].update(
                movement=_movement_allowance(next_entry["data"]), action=True,
                bonus_action=True, condition_tick_done=False)


def _do_attack(combat, actor_id, target_id):
    actor_entry = combat["actors"].get(actor_id)
    target_entry = combat["actors"].get(target_id)
    if not actor_entry or not target_entry:
        return False
    if actor_entry["downed"] or target_entry["downed"]:
        _log(combat, "A downed actor cannot attack or be targeted.")
        return False
    budget = combat["budgets"][actor_id]
    if not budget["action"]:
        _log(combat, "Action already used this turn.")
        return False
    distance = distance_feet(actor_entry, target_entry, PIXELS_PER_FOOT, ACTOR_SIZE)
    edge_distance = edge_distance_feet(
        actor_entry, target_entry, PIXELS_PER_FOOT, ACTOR_SIZE)
    event = resolve_attack(
        actor_entry["data"], target_entry["data"], distance,
        melee_distance_feet=edge_distance, adjacent_distance_feet=edge_distance,
        line_of_sight=True)
    if not event.get("success"):
        _log(combat, event.get("message", "Attack unavailable."))
        return False
    budget["action"] = False
    weapon, weapon_definition, _ = selected_weapon(actor_entry["data"])
    ranged_attack = bool(weapon and (
        actor_entry["data"].get("active_weapon_set") == "ranged"
        or ("thrown" in weapon_definition.get("tags", [])
            and edge_distance > weapon_definition.get("ranges", {}).get("melee", 5))))
    if ranged_attack:
        _emit_animation(combat, actor_id, "ranged")
        family = weapon_definition.get("weapon_family")
        if family in ("bow", "crossbow"):
            combat["projectile_event"] = {
                "id": uuid.uuid4().hex,
                "origin": [actor_entry["x"] + ACTOR_SIZE / 2,
                           actor_entry["y"] + ACTOR_SIZE / 2],
                "target": [target_entry["x"] + ACTOR_SIZE / 2,
                           target_entry["y"] + ACTOR_SIZE / 2],
            }
    else:
        swing = int(actor_entry.get("melee_swing_count", 0))
        _emit_animation(combat, actor_id, "attack1" if swing % 2 == 0 else "attack2")
        actor_entry["melee_swing_count"] = swing + 1
    actor_entry["facing_left"] = target_entry["x"] < actor_entry["x"]
    if event["hit"]:
        if target_entry["data"].get("current_hp", 1) <= 0:
            target_entry["downed"] = True
        _emit_animation(combat, target_id,
                        "dead" if target_entry["downed"] else "hurt")
        verdict = "critical hit" if event["critical"] else "hit"
        defense = (f" vs AC {event['target_ac']}"
                   if target_entry["team"] == "players" else "")
        _log(combat, (f"{event['attacker']} {verdict} {event['target']} with "
                      f"{event['weapon']} (d20 {event['rolls']} = {event['total']}"
                      f"{defense}); {event['damage_rolls']} + modifier = "
                      f"{event['damage']} {event['damage_type']} damage."))
    else:
        defense = (f" vs AC {event['target_ac']}"
                   if target_entry["team"] == "players" else "")
        _log(combat, (f"{event['attacker']} misses {event['target']} with "
                      f"{event['weapon']} (d20 {event['rolls']} = {event['total']}"
                      f"{defense})."))
    for enemy in combat["actors"].values():
        if enemy["team"] == "enemies" and enemy["data"].get("current_hp", 1) <= 0:
            enemy["downed"] = True
    _remove_downed_from_order(combat)
    if all(entry["downed"] for entry in combat["actors"].values()
           if entry["team"] == "enemies"):
        combat["active"] = False
        _log(combat, "All enemies defeated. Combat ended.")
        combat["result"] = {"outcome": "victory", "message": combat.get("scenario", {}).get("victory", "Encounter complete.")}
    return True


def _apply_action(combat, actor_id, action):
    action_type = action.get("type")
    if action_type == "attack":
        _do_attack(combat, actor_id, action.get("target"))
    elif action_type == 'cast_spell':
        _do_spell(combat, actor_id, action.get('spell'), action.get('target'))
    elif action_type == 'use_ability':
        _do_ability(combat, actor_id, action.get('ability'), action.get('target'))
    elif action_type == "end_turn" and actor_id == _active_actor_id(combat):
        _advance_turn(combat)
    elif action_type == "move" and actor_id == _active_actor_id(combat):
        entry = combat["actors"].get(actor_id)
        if not entry or entry["downed"]:
            return
        if has_condition(entry["data"], "bound_in_briar"):
            _log(combat, f"{entry['data'].get('name', actor_id)} is bound in briar.")
            return
        budget = combat["budgets"][actor_id]
        arena = combat.get("arena") or ARENAS.get(
            SCENARIOS.get(combat.get("scenario_id", DEFAULT_SCENARIO), {}).get("arena"), {})
        bounds = _arena_bounds(arena)
        target_x = max(bounds.left, min(bounds.right - ACTOR_SIZE,
                                        action.get("x", entry["x"])))
        target_y = max(bounds.top, min(bounds.bottom - ACTOR_SIZE,
                                       action.get("y", entry["y"])))
        dx, dy = target_x - entry["x"], target_y - entry["y"]
        feet = math.hypot(dx, dy) / PIXELS_PER_FOOT
        if feet > budget["movement"] and feet:
            factor = budget["movement"] / feet
            dx, dy = dx * factor, dy * factor
            feet = budget["movement"]
        occupied = [
            _actor_hitbox(other["x"], other["y"])
            for other_id, other in combat["actors"].items()
            if other_id != actor_id and not other["downed"]
        ]
        dest_x, dest_y = _walk_destination(entry["x"], entry["y"], dx, dy,
                                            arena, occupied)
        traveled = math.hypot(dest_x - entry["x"], dest_y - entry["y"])
        feet = traveled / PIXELS_PER_FOOT
        old_x, old_y = entry["x"], entry["y"]
        entry["x"], entry["y"] = dest_x, dest_y
        entry["data"]["x"], entry["data"]["y"] = entry["x"], entry["y"]
        if traveled > 0:
            if dest_x != old_x:
                entry["facing_left"] = dest_x < old_x
            _emit_animation(combat, actor_id, "walk",
                            max(180, int(traveled / 5 * 1000 / 60)))
        budget["movement"] = max(0, budget["movement"] - feet)


def _handle_action_request(actor, local_player_id, actor_id, action, remote_players, combat):
    if not combat or not combat.get("active"):
        if action.get("type") not in {"attack", "cast_spell", "use_ability"}:
            return combat
        combat = _new_combat(actor, local_player_id, remote_players)
        _log(combat, "Combat started.")
        action_type = action.get('type')
        resolved = (
            _do_attack(combat, actor_id, action.get('target'))
            if action_type == 'attack' else
            _do_spell(combat, actor_id, action.get('spell'), action.get('target'))
            if action_type == 'cast_spell' else
            _do_ability(combat, actor_id, action.get('ability'), action.get('target'))
        )
        if not resolved:
            return None
        combat["budgets"][actor_id]["skip_next"] = True
        if combat.get("active"):
            current_id = _active_actor_id(combat)
            current = combat["actors"][current_id]
            if combat["budgets"][current_id].get("skip_next"):
                _advance_turn(combat)
        return combat
    if actor_id == _active_actor_id(combat):
        _apply_action(combat, actor_id, action)
    return combat


def _run_ai_turns(combat):
    """Run non-player controllers on the authoritative host."""
    max_actions = max(1, len(combat.get("order", [])) * 3)
    for _ in range(max_actions):
        if not combat or not combat.get("active"):
            return
        actor_id = _active_actor_id(combat)
        if actor_id is None:
            return
        entry = combat["actors"][actor_id]
        if entry["data"].get("controller", "player") != "ai":
            return
        brain = controller_for(entry["data"])
        actions = brain.actions_for_turn({
            "combat": combat,
            "actor_id": actor_id,
            "pixels_per_foot": PIXELS_PER_FOOT,
        })
        if not actions:
            _advance_turn(combat)
            continue
        for action in actions:
            if _active_actor_id(combat) != actor_id:
                break
            _apply_action(combat, actor_id, action)


def _sync_local_actor(actor, combat, actor_id):
    if not combat:
        return
    entry = combat.get("actors", {}).get(actor_id)
    if not entry:
        return
    actor.current_hp = entry["data"].get("current_hp", actor.current_hp)
    actor.downed = bool(entry["downed"])
    actor.conditions = deepcopy(entry["data"].get("conditions", []))
    actor.active_effects = deepcopy(entry["data"].get("active_effects", []))
    actor.x, actor.y = entry["x"], entry["y"]


def _draw_combat_ui(screen, font, combat, actor_id):
    if not combat:
        return
    panel = pygame.Surface((800, 112), pygame.SRCALPHA)
    panel.fill((0, 0, 0, 180))
    screen.blit(panel, (0, 488))
    if combat.get("active"):
        current = _active_actor_id(combat)
        budgets = combat.get("budgets", {}).get(current, {})
        header = (f"Round {combat['round']}  |  Turn: "
                  f"{combat['actors'][current]['data'].get('name', current)}")
        if current == actor_id:
            header += f"  |  Movement: {budgets.get('movement', 0):.0f} ft"
        screen.blit(font.render(header, True, (255, 230, 120)), (12, 494))
        order_parts = []
        for entry in combat["order"]:
            actor_entry = combat["actors"][entry["id"]]
            actor_name = actor_entry["data"].get("name", entry["id"])
            statuses = ", ".join(condition_names(actor_entry["data"]))
            if statuses:
                actor_name += f" [{statuses}]"
            order_parts.append(
                f"{actor_name} ({entry['total']})" if actor_entry["team"] == "players"
                else actor_name
            )
        order = "Initiative: " + "  >  ".join(order_parts)
        screen.blit(font.render(order[:100], True, (230, 230, 230)), (12, 518))
        hp_text = "Player HP: " + " | ".join(
            f"{entry['data'].get('name', key)} {entry['data'].get('current_hp', 0)}/"
            f"{entry['data'].get('max_hp', 0)}"
            f"{' [' + ', '.join(condition_names(entry['data'])) + ']' if condition_names(entry['data']) else ''}"
            for key, entry in combat["actors"].items() if entry["team"] == "players"
        )
        screen.blit(font.render(hp_text[:100], True, (210, 230, 255)), (12, 542))
    for index, message in enumerate(combat.get("log", [])[-2:]):
        screen.blit(font.render(message[:105], True, (255, 255, 255)),
                    (12, 566 + index * 17))


def run_game(actor, get_other_players, send_state, multiplayer=True, combat_transport=None,
             party_status=None, invite_address=None):
    pygame.init()
    screen = pygame.display.set_mode((800, 600))
    clock = pygame.time.Clock()
    running = True
    speed = 5
    sprite_frames = {
        actor.avatar: load_spritesheet(actor.avatar),
        'asset_pack/Orc.png': load_spritesheet('asset_pack/Orc.png'),
        'asset_pack/Soldier.png': load_spritesheet('asset_pack/Soldier.png'),
    }
    default_frames = sprite_frames.get(actor.avatar, sprite_frames['asset_pack/Soldier.png'])
    frame_duration = 120
    arrow_sheet = pygame.image.load("asset_pack/Arrow01.png").convert_alpha()
    arrow_bounds = arrow_sheet.get_bounding_rect(min_alpha=1)
    arrow_sprite = (arrow_sheet.subsurface(arrow_bounds).copy()
                    if arrow_bounds.width else arrow_sheet)
    arrow_sprite = pygame.transform.scale(arrow_sprite, (48, 10))

    facing_left = False
    local_animation = {"anim": "idle", "index": 0, "time": 0}
    remote_players = []
    remote_animations = {}
    remote_positions = {}
    enemy_animations = {}
    projectile_runtime = {"id": None, "started": 0}
    drawn_positions = {}
    combat_transport = combat_transport or {
        "host": True, "player_id": "host", "poll": lambda: [],
        "publish": lambda state: None, "get": lambda: None,
    }
    player_id = combat_transport["player_id"]
    if not multiplayer:
        player_id = actor.id
    is_host = combat_transport["host"]
    combat = None if is_host else combat_transport["get"]()
    selected_target = None
    font = pygame.font.Font(None, 20)
    save_notice_until = 0
    invite_notice = ''
    invite_notice_until = 0
    exit_to_menu = False

    def submit(action):
        nonlocal combat
        if is_host:
            combat = _handle_action_request(
                actor, player_id, player_id, action, remote_players, combat)
            _sync_local_actor(actor, combat, player_id)
        else:
            combat_transport["submit"](action)

    while running:
        dt = clock.tick(60)
        remote_players = get_other_players() if multiplayer else []
        if is_host:
            if combat and combat.get('active'):
                _remove_disconnected_players(combat, remote_players, player_id)
                _add_joined_players(combat, remote_players)
            for request in combat_transport["poll"]():
                combat = _handle_action_request(
                    actor, player_id, request["player_id"], request["action"],
                    remote_players, combat)
            if combat:
                _process_turn_start(combat)
                _run_ai_turns(combat)
            combat_transport["publish"](combat)
            _sync_local_actor(actor, combat, player_id)
        else:
            latest = combat_transport["get"]()
            if latest is not None:
                combat = latest
                _sync_local_actor(actor, combat, player_id)

        active_id = _active_actor_id(combat)
        local_can_act = (not combat or not combat.get("active") or
                         active_id == player_id)
        current_frames = sprite_frames.get(actor.avatar, default_frames)
        current_arena = (combat or {}).get("arena") or ARENAS.get(
            SCENARIOS.get(DEFAULT_SCENARIO, {}).get("arena"), {})
        camera = _camera_offset(actor, current_arena)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                exit_to_menu = False
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_m:
                exit_to_menu = True
                running = False
            elif (event.type == pygame.KEYDOWN and event.key == pygame.K_r
                  and is_host and combat and combat.get("result")):
                combat = _new_combat(actor, player_id, remote_players,
                                     combat.get("scenario_id", DEFAULT_SCENARIO))
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_F5:
                # The design calls for explicit saves and a session-end save,
                # rather than continuous autosaving.
                _sync_local_actor(actor, combat, player_id)
                save_actor(actor)
                save_notice_until = pygame.time.get_ticks() + 1800
            elif (event.type == pygame.KEYDOWN and event.key == pygame.K_c
                  and is_host and invite_address):
                lan_address, internet_address = invite_address
                copied_address = internet_address or lan_address
                copied = _copy_invite(copied_address)
                invite_notice = (
                    f"Copied {'Internet' if internet_address else 'LAN'} invite: {copied_address}"
                    if copied else f"Invite address: {copied_address}"
                )
                invite_notice_until = pygame.time.get_ticks() + 2500
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                world_click = (event.pos[0] + camera[0], event.pos[1] + camera[1])
                click_players = []
                for remote in remote_players:
                    remote_id = _player_id(remote)
                    if remote_id in drawn_positions:
                        remote = dict(remote)
                        remote["x"] = drawn_positions[remote_id][0] + camera[0]
                        remote["y"] = drawn_positions[remote_id][1] + camera[1]
                    click_players.append(remote)
                _handle_right_click(world_click, actor, click_players,
                                    current_frames, multiplayer)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                clicked = False
                own_rect = _target_clickbox(actor.x - camera[0],
                                            actor.y - camera[1])
                if own_rect.collidepoint(event.pos):
                    selected_target = player_id
                    clicked = True
                if not clicked:
                    enemy_entries = list((combat or {}).get("actors", {}).values())
                    if not combat:
                        scenario = SCENARIOS.get(DEFAULT_SCENARIO, {})
                        for index, spawn in enumerate(scenario.get("enemies", [])):
                            enemy_entries.append({
                                "id": spawn.get("id", f"{spawn.get('npc')}-{index + 1}"),
                                "team": "enemies", "x": spawn.get("x", 600),
                                "y": spawn.get("y", 280), "width": ACTOR_SIZE, "height": ACTOR_SIZE,
                            })
                    for enemy in enemy_entries:
                        if enemy.get("team") != "enemies":
                            continue
                        rect = _target_clickbox(enemy["x"] - camera[0],
                                                enemy["y"] - camera[1])
                        if rect.collidepoint(event.pos):
                            selected_target = enemy["id"]
                            clicked = True
                            break
                for remote in reversed(remote_players) if not clicked else ():
                    player_key = remote.get("id", (remote.get("actor") or {}).get("id", "remote"))
                    drawn = drawn_positions.get(player_key)
                    position = drawn or (remote.get("x", 0), remote.get("y", 0))
                    rect = _target_clickbox(*position)
                    if rect.collidepoint(event.pos):
                        selected_target = player_key
                        clicked = True
                        break
                if not clicked and combat and combat.get("active") and local_can_act:
                    submit({"type": "move",
                            "x": event.pos[0] + camera[0] - ACTOR_SIZE / 2,
                            "y": event.pos[1] + camera[1] - ACTOR_SIZE / 2})
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_1:
                if selected_target:
                    submit({"type": "attack", "target": selected_target})
            elif event.type == pygame.KEYDOWN and pygame.K_2 <= event.key <= pygame.K_9:
                spell_ids = actor.known_spells
                spell_index = event.key - pygame.K_2
                if spell_index < len(spell_ids):
                    submit({'type': 'cast_spell', 'spell': spell_ids[spell_index],
                            'target': selected_target})
            elif event.type == pygame.KEYDOWN and event.key in (pygame.K_q, pygame.K_e):
                ability_ids = actor.known_abilities
                ability_index = 0 if event.key == pygame.K_q else 1
                if ability_index < len(ability_ids):
                    submit({'type': 'use_ability', 'ability': ability_ids[ability_index],
                            'target': selected_target})
            elif event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if combat and combat.get("active") and local_can_act:
                    submit({"type": "end_turn"})

        keys = pygame.key.get_pressed()
        moving = False
        if (not actor.downed and
                (not combat or not combat.get("active"))):
            occupied = []
            for remote in remote_players:
                occupied.append(_actor_hitbox(remote.get("x", 0),
                                              remote.get("y", 0)))
            if combat and combat.get("result"):
                occupied.extend(
                    _actor_hitbox(entry["x"], entry["y"])
                    for entry in combat["actors"].values()
                    if entry["team"] == "enemies" and not entry["downed"]
                )
            else:
                for spawn in SCENARIOS.get(DEFAULT_SCENARIO, {}).get("enemies", []):
                    occupied.append(_actor_hitbox(spawn.get("x", 0),
                                                  spawn.get("y", 0)))
            moving, facing_left = _move_actor(actor, keys, speed, facing_left,
                                              current_arena, occupied)
        local_entry = (combat or {}).get("actors", {}).get(player_id)
        local_requested = ("dead" if actor.downed or
                           (local_entry and local_entry.get("downed")) else
                           "walk" if moving else "idle")
        sprite = _advance_character_animation(
            local_animation, local_requested,
            local_entry.get("animation_event") if local_entry else None,
            dt, sprite_frames.get(actor.avatar, default_frames), frame_duration)
        if local_entry and "facing_left" in local_entry:
            facing_left = local_entry["facing_left"]
        if facing_left:
            sprite = pygame.transform.flip(sprite, True, False)

        if not is_host and combat and combat.get("active"):
            snapshot = combat.get("actors", {}).get(player_id)
            if snapshot:
                actor.x, actor.y = snapshot["x"], snapshot["y"]
        send_state(actor.x, actor.y, local_animation["anim"], facing_left, vars(actor))

        if combat:
            combat_actors = combat.get("actors", {})
            remote_players = [
                {**remote,
                 "x": combat_actors.get(_player_id(remote), {}).get("x", remote.get("x", 0)),
                 "y": combat_actors.get(_player_id(remote), {}).get("y", remote.get("y", 0)),
                 "combat_animation": combat_actors.get(_player_id(remote), {}).get("animation_event"),
                 "facing": combat_actors.get(_player_id(remote), {}).get(
                     "facing_left", remote.get("facing", False)),
                 "downed": combat_actors.get(_player_id(remote), {}).get("downed",
                     (remote.get("actor") or {}).get("downed", False))}
                for remote in remote_players
            ]

        camera = _camera_offset(actor, current_arena)
        drawn_positions = _draw_players(
            screen, actor, sprite, remote_players, remote_animations,
            remote_positions, dt, sprite_frames, frame_duration, current_arena,
            camera)
        controls = ("WASD move | Click target | 1 attack | 2-9 spells | Q/E abilities | Enter end turn | F5 save"
                    if (actor.known_spells or actor.known_abilities)
                    else "WASD move | Click target | 1 attack | Enter end turn | F5 save")
        screen.blit(font.render(controls, True, (230, 230, 230)), (12, 12))
        if multiplayer:
            count = party_status() if party_status else 1 + len(remote_players)
            screen.blit(font.render(f"Party: {count}/8", True, (195, 220, 195)),
                        (12, 56))
            if is_host and invite_address:
                lan_address, internet_address = invite_address
                screen.blit(font.render(f"LAN invite: {lan_address}", True,
                                        (195, 220, 195)), (12, 76))
                internet_text = (f"Internet invite: {internet_address}"
                                 if internet_address else
                                 "Internet: forward TCP 5555, then share your public IP:5555")
                screen.blit(font.render(internet_text, True, (195, 220, 195)), (12, 96))
                copy_label = ("Press C to copy invite" if internet_address
                              else "Press C to copy LAN invite")
                screen.blit(font.render(copy_label, True, (195, 220, 195)),
                            (12, 116))
        spell_hints = [
            f"{index + 2}:{SPELLS[spell_id]['name']}"
            for index, spell_id in enumerate(actor.known_spells[:8])
            if spell_id in SPELLS
        ]
        ability_hints = [
            f"{key}:{ABILITIES[ability_id]['name']}"
            for key, index in (('Q', 0), ('E', 1))
            for ability_id in actor.known_abilities[index:index + 1]
            if ability_id in ABILITIES
        ]
        hotkey_hint = "  ".join(spell_hints + ability_hints)
        if hotkey_hint:
            screen.blit(font.render(hotkey_hint[:112], True, (205, 220, 245)), (12, 34))
        scenario = (combat or {}).get("scenario") or SCENARIOS.get(DEFAULT_SCENARIO, {})
        screen.blit(font.render(scenario.get("name", "Worldforge"), True,
                                (245, 245, 230)), (12, 46))
        if scenario.get("objective"):
            screen.blit(font.render(scenario["objective"], True, (230, 230, 205)), (12, 66))
        enemy_entries = list((combat or {}).get("actors", {}).values())
        if not combat:
            for index, spawn in enumerate(scenario.get("enemies", [])):
                definition = NPCS.get(spawn.get("npc"), {})
                enemy_entries.append({
                    "id": spawn.get("id", f"{spawn.get('npc')}-{index + 1}"),
                    "team": "enemies", "x": spawn.get("x", 600),
                    "y": spawn.get("y", 280), "width": ACTOR_SIZE, "height": ACTOR_SIZE,
                    "downed": False, "data": definition,
                })
        for enemy in enemy_entries:
            if enemy.get("team") != "enemies":
                continue
            rect = pygame.Rect(enemy["x"] - camera[0], enemy["y"] - camera[1],
                               enemy.get("width", 40), enemy.get("height", 40))
            avatar = enemy.get("data", {}).get("avatar")
            enemy_frames = sprite_frames.get(avatar, sprite_frames["asset_pack/Orc.png"])
            enemy_animation = enemy_animations.setdefault(
                enemy["id"], {"anim": "idle", "index": 0, "time": 0})
            requested = "dead" if enemy["downed"] else "idle"
            enemy_image = _advance_character_animation(
                enemy_animation, requested, enemy.get("animation_event"),
                dt, enemy_frames, frame_duration)
            enemy_image = pygame.transform.scale(enemy_image, rect.size)
            screen.blit(enemy_image, rect.topleft)
            pygame.draw.rect(screen, (225, 210, 180), rect, 2)
            screen.blit(font.render(enemy["data"].get("name", "Enemy"), True,
                                    (245, 245, 245)), (rect.x - 10, rect.y - 20))
        projectile = (combat or {}).get("projectile_event")
        if projectile:
            if projectile_runtime["id"] != projectile.get("id"):
                projectile_runtime.update(id=projectile.get("id"),
                                          started=pygame.time.get_ticks())
            elapsed = pygame.time.get_ticks() - projectile_runtime["started"]
            progress = min(1.0, elapsed / 280)
            if progress < 1:
                start_x, start_y = projectile["origin"]
                end_x, end_y = projectile["target"]
                world_x = start_x + (end_x - start_x) * progress
                world_y = start_y + (end_y - start_y) * progress
                angle = math.degrees(math.atan2(end_y - start_y, end_x - start_x))
                arrow = pygame.transform.rotate(arrow_sprite, -angle)
                screen.blit(arrow, arrow.get_rect(center=(round(world_x - camera[0]),
                                                          round(world_y - camera[1]))))
        if selected_target:
            target_entry = combat.get("actors", {}).get(selected_target) if combat else None
            if not target_entry and not combat:
                for index, spawn in enumerate(scenario.get("enemies", [])):
                    enemy_id = spawn.get("id", f"{spawn.get('npc')}-{index + 1}")
                    if enemy_id == selected_target:
                        target_entry = {"x": spawn.get("x", 600), "y": spawn.get("y", 280),
                                        "width": ACTOR_SIZE, "height": ACTOR_SIZE}
                        break
            if target_entry:
                target_center = (int(target_entry["x"] + target_entry.get("width", ACTOR_SIZE) / 2 - camera[0]),
                                 int(target_entry["y"] + target_entry.get("height", ACTOR_SIZE) / 2 - camera[1]))
            else:
                remote = next((p for p in remote_players if p.get("id") == selected_target), None)
                target_center = (int(remote.get("x", 0) + 50), int(remote.get("y", 0) + 50)) if remote else None
            if target_center:
                pygame.draw.circle(screen, (255, 230, 100), target_center, 27, 2)
        _draw_combat_ui(screen, font, combat, player_id)
        if combat and combat.get("result"):
            result = combat["result"]
            banner = pygame.Surface((560, 100), pygame.SRCALPHA)
            banner.fill((0, 0, 0, 205))
            screen.blit(banner, (120, 180))
            screen.blit(font.render(result.get("message", "Encounter complete."), True,
                                    (255, 235, 160)), (140, 198))
            prompt = "R: play again  |  M: return to menu" if is_host else "Waiting for host  |  M: return to menu"
            screen.blit(font.render(prompt, True, (240, 240, 240)), (140, 230))
        if pygame.time.get_ticks() < save_notice_until:
            notice = font.render("Character saved", True, (190, 245, 190))
            screen.blit(notice, (screen.get_width() - notice.get_width() - 12, 12))
        if pygame.time.get_ticks() < invite_notice_until:
            notice = font.render(invite_notice, True, (220, 240, 190))
            screen.blit(notice, (12, 140))
        pygame.display.flip()

    _sync_local_actor(actor, combat, player_id)
    save_actor(actor)
    pygame.quit()
    return "menu" if exit_to_menu else "quit"
