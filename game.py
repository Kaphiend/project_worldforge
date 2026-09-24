"""Pygame gameplay loop."""
import math
import random
import sys
import time
from pprint import pprint
from copy import deepcopy
import uuid

import pygame

from combat import attack as resolve_attack
from combat import (distance_feet, edge_distance_feet, initiative_for,
                    proficiency_bonus, selected_weapon, speed_feet)
from classes import (ABILITIES, CLASSES, SPELLS, ARENAS, NPCS, SCENARIOS,
                     MOB_GENERATION_RULES)
from controllers import controller_for
from conditions import condition_names, has_condition, tick_conditions
from sprite_sheet import load_spritesheet
from spell_effects import apply_ability_effects, resolve_spell
from storage import save_actor
from factory import (create_npc_instance, effective_max_hp, equip_item,
                     item_definition, modifier, unequip_item)
from progression import (initialize_resources, spell_point_max,
                         class_unlocked_level, qualified_level,
                         unspent_xp, spend_xp, charge_xp_penalty,
                         sync_progression_levels, character_level_for_xp,
                         set_spell_prepared, class_unlock_cost,
                         unlocked_classes, adjusted_purchase_cost,
                         spend_attribute_point)
from resting import resolve_rest
from runtime_paths import asset_path


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


def _wrap_ui_lines(font, text, max_width):
    lines, current = [], ""
    for word in str(text).split():
        candidate = f"{current} {word}".strip()
        if current and font.size(candidate)[0] > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _fit_ui_text(font, text, max_width):
    value = str(text)
    if font.size(value)[0] <= max_width:
        return value
    while value and font.size(value + "…")[0] > max_width:
        value = value[:-1]
    return value + "…"


def _handle_right_click(position, actor, remote_players):
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
    arena = arena or {}
    obstacles = list(arena.get("obstacles", []))
    obstacles.extend(arena.get("inn_beds", []))
    obstacles.extend(arena.get("trainers", []))
    return [pygame.Rect(item["x"], item["y"], item["width"], item["height"])
            for item in obstacles]


def _overlap_area(first, second):
    overlap = first.clip(second)
    return overlap.width * overlap.height


def _can_occupy(candidate, current, fixed_obstacles, actor_obstacles):
    if any(candidate.colliderect(obstacle) for obstacle in fixed_obstacles):
        return False
    for obstacle in actor_obstacles:
        if (candidate.colliderect(obstacle)
                and _overlap_area(candidate, obstacle)
                >= _overlap_area(current, obstacle)):
            return False
    return True


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
    fixed_obstacles = _arena_obstacles(arena)
    actor_obstacles = list(occupied)
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
        current_rect = _actor_hitbox(actor.x, actor.y)
        if _can_occupy(rect, current_rect, fixed_obstacles, actor_obstacles):
            setattr(actor, axis, candidate)
    return True, facing_left


def _camera_offset(actor, arena, viewport=(1024, 768)):
    bounds = _arena_bounds(arena)
    width, height = viewport
    max_x = max(bounds.left, bounds.right - width)
    max_y = max(bounds.top, bounds.bottom - height)
    x = actor.x + ACTOR_SIZE / 2 - width / 2
    y = actor.y + ACTOR_SIZE / 2 - height / 2
    return round(max(bounds.left, min(max_x, x))), round(max(bounds.top, min(max_y, y)))


def _walk_destination(x, y, dx, dy, arena, occupied=()):
    bounds = _arena_bounds(arena)
    fixed_obstacles = _arena_obstacles(arena)
    actor_obstacles = list(occupied)
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
        current_rect = _actor_hitbox(x, y)
        if not _can_occupy(rect, current_rect, fixed_obstacles, actor_obstacles):
            slides = [(candidate_x, y), (x, candidate_y)]
            clear_slides = [
                point for point in slides
                if _can_occupy(_actor_hitbox(point[0], point[1]), current_rect,
                               fixed_obstacles, actor_obstacles)
            ]
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
        entry["downed"] = bool(entry["data"].get("downed", False) or new_hp <= 0)
        if new_hp < old_hp:
            _emit_animation(combat, actor_id,
                            "dead" if entry["downed"] else "hurt")
        elif old_downed and not entry["downed"]:
            _emit_animation(combat, actor_id, "idle")
            penalty = charge_xp_penalty(entry["data"], 2)
            if penalty:
                _log(combat, f"{entry['data'].get('name', actor_id)} loses {penalty} XP after being revived.")


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
                  camera=(0, 0), local_speech=None, font=None):
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
    for bed in arena.get("inn_beds", []):
        rect = pygame.Rect(bed["x"] - camera_x, bed["y"] - camera_y,
                           bed["width"], bed["height"])
        pygame.draw.rect(screen, (135, 135, 140), rect, border_radius=4)
        pygame.draw.rect(screen, (220, 220, 225), rect, 3, border_radius=4)
        pillow = pygame.Rect(rect.x + 7, rect.y + 6,
                             max(12, rect.width // 4), max(10, rect.height - 12))
        pygame.draw.rect(screen, (205, 205, 210), pillow, border_radius=3)
        screen.blit(pygame.font.Font(None, 17).render(
            bed.get("name", "Inn Bed"), True, (255, 255, 255)),
            (rect.x, rect.y - 18))
    for trainer in arena.get("trainers", []):
        rect = pygame.Rect(trainer["x"] - camera_x, trainer["y"] - camera_y,
                           trainer["width"], trainer["height"])
        pygame.draw.rect(screen, (102, 78, 52), rect, border_radius=4)
        pygame.draw.rect(screen, (210, 180, 125), rect, 3, border_radius=4)
        screen.blit(pygame.font.Font(None, 17).render(
            trainer.get("name", "Trainer"), True, (255, 245, 220)),
            (rect.x - 3, rect.y - 18))
    screen.blit(local_sprite, (round(actor.x - camera_x), round(actor.y - camera_y)))
    font = font or pygame.font.Font(None, 18)
    _draw_speech_bubble(screen, font, local_speech, actor.x, actor.y,
                        ACTOR_SIZE, camera_x, camera_y)
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
        _draw_speech_bubble(screen, font, remote.get("speech"), x, y,
                            ACTOR_SIZE, camera_x, camera_y)
    return drawn_positions


def _draw_speech_bubble(screen, font, speech, x, y, actor_size, camera_x, camera_y):
    if not speech or speech.get("expires_at", 0) <= time.time():
        return
    text = str(speech.get("text", ""))[:160]
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and font.size(candidate)[0] > 250:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if not lines:
        return
    width = min(270, max(font.size(line)[0] for line in lines) + 20)
    height = len(lines) * 19 + 12
    left = round(x + actor_size / 2 - camera_x - width / 2)
    top = round(y - camera_y - height - 8)
    rect = pygame.Rect(max(4, min(screen.get_width() - width - 4, left)),
                       max(4, top), width, height)
    bubble = pygame.Surface(rect.size, pygame.SRCALPHA)
    bubble.fill((248, 246, 232, 238))
    pygame.draw.rect(bubble, (35, 38, 44), bubble.get_rect(), 2, border_radius=6)
    screen.blit(bubble, rect.topleft)
    for index, line in enumerate(lines):
        screen.blit(font.render(line, True, (24, 26, 30)),
                    (rect.x + 10, rect.y + 6 + index * 19))


PIXELS_PER_FOOT = 4
SCREEN_SIZE = (1024, 768)
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


def _perception_score(actor_data):
    explicit = actor_data.get("perception_score")
    if isinstance(explicit, (int, float)):
        return int(explicit)
    wisdom = actor_data.get("abilities", {}).get("wisdom", 10)
    score = 10 + modifier(wisdom)
    if "perception" in {skill.casefold() for skill in actor_data.get("skills", [])}:
        score += proficiency_bonus(actor_data)
    return score


def _perceived_title(observer_data, perception_data):
    score = _perception_score(observer_data)
    known = [level for level in perception_data.get("levels", [])
             if score >= int(level.get("dc", 10))]
    if not known:
        return None
    return max(known, key=lambda level: int(level.get("dc", 10))).get("title")


def _line_of_sight(actor_a, actor_b, arena):
    def center(actor):
        hitbox = actor.get("hitbox") if isinstance(actor, dict) else None
        if hitbox:
            x = actor.get("x", 0) + hitbox.get("offset_x", 0)
            y = actor.get("y", 0) + hitbox.get("offset_y", 0)
            width, height = hitbox.get("width", ACTOR_SIZE), hitbox.get("height", ACTOR_SIZE)
        else:
            x, y = actor.get("x", 0), actor.get("y", 0)
            width, height = actor.get("width", ACTOR_SIZE), actor.get("height", ACTOR_SIZE)
        return round(x + width / 2), round(y + height / 2)
    first, second = center(actor_a), center(actor_b)
    return not any(obstacle.clipline(first, second)
                   for obstacle in _arena_obstacles(arena))


def _attack_readiness_text(actor_data, actor_x, actor_y, target_entry, arena):
    actor_entry = {
        "x": actor_x, "y": actor_y, "width": ACTOR_SIZE, "height": ACTOR_SIZE,
        "hitbox": {"offset_x": (ACTOR_SIZE - ACTOR_HITBOX_WIDTH) / 2,
                   "offset_y": (ACTOR_SIZE - ACTOR_HITBOX_HEIGHT) / 2,
                   "width": ACTOR_HITBOX_WIDTH, "height": ACTOR_HITBOX_HEIGHT},
    }
    edge_feet = edge_distance_feet(actor_entry, target_entry, PIXELS_PER_FOOT, ACTOR_SIZE)
    weapon, definition, _ = selected_weapon(actor_data)
    if not weapon or not definition:
        return f"Target: {edge_feet} ft | no attack weapon equipped"
    reach = definition.get("ranges", {}).get("melee", 5)
    ranged_set = (actor_data.get("active_weapon_set") == "ranged"
                  and weapon == actor_data.get("equipment", {}).get("ranged"))
    thrown = (not ranged_set and "thrown" in definition.get("tags", [])
              and edge_feet > reach)
    if not ranged_set and not thrown:
        state = "melee in reach" if edge_feet <= reach else f"melee needs <= {reach} ft"
        throw_hint = " | T throw" if "thrown" in definition.get("tags", []) else ""
        return f"Target: {edge_feet} ft | {definition.get('name', 'Weapon')} | {state}{throw_hint}"
    clear_sight = _line_of_sight(actor_entry, target_entry, arena)
    state = "clear sight" if clear_sight else "blocked sight"
    mode = "thrown" if thrown else "ranged"
    main_hand = actor_data.get("equipment", {}).get("main_hand")
    main_definition = item_definition(main_hand) if main_hand else {}
    throw_hint = " | T throw" if "thrown" in main_definition.get("tags", []) else ""
    return f"Target: {edge_feet} ft | {definition.get('name', 'Weapon')} {mode} | {state}{throw_hint}"


def _movement_allowance(actor_data):
    bonus = sum(int(effect.get("feet", 0))
                for effect in actor_data.get("active_effects", [])
                if effect.get("kind") == "movement_bonus")
    return speed_feet(actor_data) + bonus


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


def _settle_victory(combat, players):
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
            entry["corpse_despawn_at"] = None
            entry["loot"] = _corpse_loot(entry)
    arena = combat.get("arena", {})
    existing = [entry for entry in combat.get("actors", {}).values()
                if entry.get("team") == "enemies"]
    fresh = _random_mob_entry(arena, existing, players)
    if fresh:
        combat["actors"][fresh["id"]] = fresh
        _log(combat, f"A new {fresh['data'].get('name', 'mob')} appears elsewhere on the map.")
    else:
        _log(combat, "The defeated mob remains here; no clear spawn point was found.")
    combat["order"] = []
    combat["budgets"] = {}
    combat["turn_index"] = 0
    combat["ability_uses"] = {}


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


def _do_spell(combat, actor_id, spell_id, target_id=None):
    actor_entry = combat['actors'].get(actor_id)
    if not actor_entry or actor_entry['downed']:
        return False
    spell = SPELLS.get(spell_id)
    if not spell:
        _reject_action(combat, 'Unknown spell.', actor_id)
        return False
    budget = combat['budgets'][actor_id]
    if not budget.get('action'):
        _reject_action(combat, 'Action already used this turn.', actor_id)
        return False
    caster = actor_entry['data']
    prepared_spells = caster.get("prepared_spells", [])
    actor_classes = {item.get("name") for item in caster.get("classes", []) or []
                     if item.get("name")}
    if caster.get("char_class"):
        actor_classes.add(caster["char_class"])
    if not actor_classes.intersection(spell.get("classes", [])):
        _reject_action(combat, 'Your class cannot cast this spell.', actor_id)
        return False
    if spell_id not in prepared_spells:
        _reject_action(combat, f"{spell['name']} is not prepared.", actor_id)
        return False
    spell_cost = max(0, int(spell.get("spell_point_cost", 1)))
    spell_points = int(caster.get("spell_points", 0) or 0)
    if spell_points < spell_cost:
        _reject_action(
            combat,
            f"Not enough spell points for {spell['name']} ({spell_cost} needed; {spell_points} available).",
            actor_id)
        return False
    target_info = spell.get('targeting', {})
    target_entry = combat['actors'].get(target_id) if target_id else None
    mode = target_info.get('mode')
    if mode not in ('self',) and not target_entry:
        _reject_action(combat, 'Invalid target: select an available target first.', actor_id)
        return False
    if target_entry and target_entry["data"].get("withdrawn"):
        _reject_action(combat, "That character has left the fight.", target_id)
        return False
    targets = [target_entry['data']] if target_entry else None
    point = None
    if mode == 'small_area':
        point = (target_entry['x'] + target_entry['width'] / 2,
                 target_entry['y'] + target_entry['height'] / 2)
        radius = int(target_info.get('radius_feet', 0)) * PIXELS_PER_FOOT
        targets = [entry['data'] for entry in combat['actors'].values()
                   if not entry['data'].get("withdrawn")
                   and math.hypot(entry['x'] + entry['width'] / 2 - point[0],
                                 entry['y'] + entry['height'] / 2 - point[1]) <= radius]
    if mode == 'self':
        targets = [caster]
    hp_before = _capture_hp(combat)
    line_of_sight = (True if mode == 'self' or not target_entry else
                     _line_of_sight(actor_entry, target_entry, combat.get('arena')))
    result = resolve_spell(spell_id, caster, targets,
                           target_position=point, line_of_sight=line_of_sight)
    if not result.get('success'):
        _reject_action(combat, result.get('message', 'Spell failed.'),
                       target_id or actor_id)
        return False
    budget['action'] = False
    caster["spell_points"] = spell_points - spell_cost
    remaining_points = caster["spell_points"]
    if spell_cost:
        _log(combat, (f"{caster.get('name', 'Caster')} spends {spell_cost} spell point"
                      f"{'s' if spell_cost != 1 else ''} ({remaining_points}/"
                      f"{spell_point_max(caster)} left)."))
    else:
        _log(combat, f"{caster.get('name', 'Caster')} casts {spell['name']} without spending spell points.")
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
    enemies = [entry for entry in combat['actors'].values()
               if entry['team'] == 'enemies']
    if enemies and all(entry['downed'] for entry in enemies):
        combat['active'] = False
        _log(combat, 'All enemies defeated. Combat ended.')
        combat["result"] = {"outcome": "victory", "message": combat.get("scenario", {}).get("victory", "Encounter complete.")}
        _award_combat_xp(combat)
    return True


def _do_ability(combat, actor_id, ability_id, target_id=None):
    actor_entry = combat['actors'].get(actor_id)
    ability = ABILITIES.get(ability_id)
    if not actor_entry or actor_entry['downed'] or not ability:
        _reject_action(combat, 'Ability unavailable to this actor.', target_id or actor_id)
        return False
    actor_data = actor_entry['data']
    if ability_id not in actor_data.get('known_abilities', []):
        _reject_action(combat, 'That ability is not available to this character.', actor_id)
        return False
    uses_limit = ability.get("uses_per_combat", 1)
    actor_uses = combat.setdefault("ability_uses", {}).setdefault(actor_id, {})
    uses_so_far = int(actor_uses.get(ability_id, 0))
    if uses_limit is not None and uses_so_far >= max(0, int(uses_limit)):
        _reject_action(combat, f"{ability['name']} has already been used this fight.", actor_id)
        return False
    resource_cost = ability.get("resource_cost")
    resource_key = None
    resource_amount = 0
    if resource_cost:
        resource_class = resource_cost.get("class_id", actor_data.get("char_class", ""))
        resource_id = resource_cost.get("resource_id", "")
        resource_key = f"{resource_class}.{resource_id}"
        resource_amount = max(1, int(resource_cost.get("amount", 1)))
        available = int(actor_data.get("class_resources", {}).get(resource_key, 0))
        if available < resource_amount:
            _reject_action(combat, f"Not enough {resource_id.replace('_', ' ')} points.", actor_id)
            return False
    target_info = ability.get('targeting', {})
    target_entry = combat['actors'].get(target_id) if target_id else None
    if target_info and target_info.get('mode') != 'self' and not target_entry:
        _reject_action(combat, 'Invalid target: select an available target first.', actor_id)
        return False
    if target_entry and target_entry["data"].get("withdrawn"):
        _reject_action(combat, "That character has left the fight.", target_id)
        return False
    if target_entry and target_info.get('range_feet') is not None:
        if edge_distance_feet(actor_entry, target_entry) > target_info['range_feet']:
            _reject_action(combat, 'Target is outside ability range.', target_id)
            return False
    budget = combat['budgets'][actor_id]
    cost = ability.get('action_cost', 'action')
    if not budget.get(cost, False):
        _reject_action(combat, f"{cost.replace('_', ' ').title()} already used this turn.", actor_id)
        return False
    try:
        hp_before = _capture_hp(combat)
        effect_target = (target_entry['data']
                         if target_entry and target_info.get('mode') != 'self'
                         else actor_data)
        effects = apply_ability_effects(ability_id, actor_data, effect_target)
    except (KeyError, ValueError) as exc:
        _reject_action(combat, f'Ability unavailable: {exc}', target_id or actor_id)
        return False
    budget[cost] = False
    if uses_limit is not None:
        actor_uses[ability_id] = uses_so_far + 1
    if resource_key:
        actor_data.setdefault("class_resources", {})[resource_key] -= resource_amount
    _log(combat, f"{actor_data.get('name', 'Actor')} uses {ability['name']}.")
    _animate_hp_changes(combat, hp_before)
    enemies = [entry for entry in combat["actors"].values()
               if entry["team"] == "enemies"]
    if enemies and all(entry["downed"] or entry["data"].get("current_hp", 1) <= 0
                       for entry in enemies):
        combat["active"] = False
        combat["result"] = {"outcome": "victory", "message": combat.get("scenario", {}).get("victory", "Encounter complete.")}
        _log(combat, "All enemies defeated. Combat ended.")
        _award_combat_xp(combat)
    return bool(effects) or not ability.get('effects')


def _log(combat, message):
    combat.setdefault("log", []).append(message)
    combat["log"] = combat["log"][-8:]


def _award_combat_xp(combat, amount=10):
    """Award the fixed mob-victory XP once to every player in this combat."""
    if combat.get("xp_awarded"):
        return
    combat["xp_awarded"] = True
    for actor_id, entry in combat.get("actors", {}).items():
        if entry.get("team") != "players":
            continue
        data = entry["data"]
        by_level = data.setdefault("xp_earned_by_level", {})
        if not sum(max(0, int(value or 0)) for value in by_level.values()):
            recorded_costs = sum(max(0, int(value or 0)) for value in
                                 data.get("xp_spent_by_level", {}).values())
            recorded_costs += sum(max(0, int(value or 0)) for value in
                                  data.get("xp_rest_spent_by_level", {}).values())
            prior_wallet = max(0, int(data.get("xp_total", 0) or 0))
            if prior_wallet or recorded_costs:
                earned_key = str(character_level_for_xp(prior_wallet + recorded_costs))
                by_level[earned_key] = prior_wallet + recorded_costs
        level_key = str(max(1, int(qualified_level(data))))
        data["xp_total"] = int(data.get("xp_total", 0) or 0) + amount
        by_level[level_key] = int(by_level.get(level_key, 0) or 0) + amount
        sync_progression_levels(data)
        _log(combat, f"{data.get('name', actor_id)} gains {amount} XP.")


def _reject_action(combat, message, target_id=None):
    """Log an invalid action and publish its target for a brief red flash."""
    _log(combat, message)
    if target_id not in combat.get("actors", {}):
        target_id = _active_actor_id(combat)
    combat["action_feedback"] = {
        "id": uuid.uuid4().hex,
        "target_id": target_id,
    }


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
        if (combat['actors'][entry['id']]['downed']
                or combat['actors'][entry['id']]['data'].get('withdrawn')):
            removed[entry['id']] = entry
    combat["order"] = [entry for entry in combat.get("order", [])
                       if not combat["actors"][entry["id"]]["downed"]
                       and not combat["actors"][entry["id"]]["data"].get("withdrawn")]
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
    restored = False
    for actor_id, initiative in list(removed.items()):
        actor = combat['actors'][actor_id]
        if (actor['downed'] or actor['data'].get('current_hp', 0) <= 0
                or actor['data'].get('withdrawn')):
            continue
        combat['order'].append(initiative)
        combat['order'].sort(
            key=lambda entry: (entry['total'], entry['dexterity']), reverse=True)
        del removed[actor_id]
        restored = True
    if restored and any(entry.get("team") == "enemies" and not entry.get("downed")
                        for entry in combat.get("actors", {}).values()):
        combat["active"] = True
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
            _award_combat_xp(combat)
            return
        if combat.get("active"):
            next_id = _active_actor_id(combat)
            next_entry = combat["actors"][next_id]
            combat["budgets"][next_id].update(
                movement=_movement_allowance(next_entry["data"]), action=True,
                bonus_action=True, condition_tick_done=False)


def _do_attack(combat, actor_id, target_id, attack_mode="primary"):
    actor_entry = combat["actors"].get(actor_id)
    target_entry = combat["actors"].get(target_id)
    if not actor_entry or not target_entry:
        _reject_action(combat, 'Invalid target: select an available target first.',
                       actor_id)
        return False
    if target_entry["data"].get("withdrawn"):
        _reject_action(combat, "That character has left the fight.", target_id)
        return False
    if actor_entry["downed"] or target_entry["downed"]:
        _reject_action(combat, "A downed actor cannot attack or be targeted.",
                       target_id if target_entry["downed"] else actor_id)
        return False
    budget = combat["budgets"][actor_id]
    if not budget["action"]:
        _reject_action(combat, "Action already used this turn.", actor_id)
        return False
    distance = distance_feet(actor_entry, target_entry, PIXELS_PER_FOOT, ACTOR_SIZE)
    edge_distance = edge_distance_feet(
        actor_entry, target_entry, PIXELS_PER_FOOT, ACTOR_SIZE)
    line_of_sight = _line_of_sight(actor_entry, target_entry, combat.get("arena"))
    event = resolve_attack(
        actor_entry["data"], target_entry["data"], distance,
        melee_distance_feet=edge_distance, adjacent_distance_feet=edge_distance,
        line_of_sight=line_of_sight,
        attack_mode=attack_mode if attack_mode in ("throw", "ranged") else "primary")
    if not event.get("success"):
        _reject_action(combat, event.get("message", "Attack unavailable."), target_id)
        return False
    budget["action"] = False
    if attack_mode == "ranged":
        weapon = actor_entry["data"].get("equipment", {}).get("ranged")
        weapon_definition = item_definition(weapon) if weapon else {}
    else:
        weapon, weapon_definition, _ = selected_weapon(actor_entry["data"])
    ranged_attack = bool(event.get("ranged"))
    if event.get("thrown"):
        weapon = actor_entry["data"].get("equipment", {}).get("main_hand")
        weapon_definition = item_definition(weapon) if weapon else {}
    if ranged_attack:
        _emit_animation(combat, actor_id, "ranged")
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
    enemies = [entry for entry in combat["actors"].values()
               if entry["team"] == "enemies"]
    if enemies and all(entry["downed"] for entry in enemies):
        combat["active"] = False
        _log(combat, "All enemies defeated. Combat ended.")
        combat["result"] = {"outcome": "victory", "message": combat.get("scenario", {}).get("victory", "Encounter complete.")}
        _award_combat_xp(combat)
    return True


def _do_item(combat, actor_id, item_id, target_id=None):
    entry = combat.get("actors", {}).get(actor_id)
    if not entry or entry.get("downed"):
        _reject_action(combat, "A downed actor cannot use an item.", actor_id)
        return False
    budget = combat.get("budgets", {}).get(actor_id, {})
    if not budget.get("action"):
        _reject_action(combat, "Action already used this turn.", actor_id)
        return False
    item = next((item for item in entry["data"].get("inventory", [])
                 if item.get("id") == item_id), None)
    if not item:
        _reject_action(combat, "That item is not in your inventory.", actor_id)
        return False
    definition = item_definition(item)
    effect_id = definition.get("effect_id")
    if not effect_id or effect_id not in SPELLS:
        _reject_action(combat, "That item has no usable effect.", actor_id)
        return False
    target_entry = combat.get("actors", {}).get(target_id) if target_id else entry
    if not target_entry:
        _reject_action(combat, "Invalid target: select an available target first.", actor_id)
        return False
    if target_entry["data"].get("withdrawn"):
        _reject_action(combat, "That character has left the fight.", target_id)
        return False
    los = _line_of_sight(entry, target_entry, combat.get("arena"))
    hp_before = _capture_hp(combat)
    result = resolve_spell(effect_id, entry["data"], [target_entry["data"]],
                           line_of_sight=los, from_consumable=True)
    if not result.get("success"):
        _reject_action(combat, result.get("message", "Item could not be used."), target_id)
        return False
    stack_quantity = max(1, int(item.get("quantity", 1)))
    if stack_quantity > 1:
        item["quantity"] = stack_quantity - 1
    else:
        entry["data"]["inventory"].remove(item)
        quick_items = entry["data"].setdefault("quick_items", {})
        for key, quick_item in list(quick_items.items()):
            if quick_item == item_id:
                quick_items[key] = None
    budget["action"] = False
    for outcome in result.get("results", []):
        healing = sum(effect.get("amount", 0) for effect in outcome.get("effects", [])
                      if effect.get("kind") == "healing")
        _log(combat, f"{entry['data'].get('name', actor_id)} uses {definition.get('name', item.get('name'))} on {outcome['target']} ({healing} HP restored).")
    for current in combat["actors"].values():
        current["downed"] = bool(current["data"].get("downed", False)
                                  or current["data"].get("current_hp", 1) <= 0)
    _remove_downed_from_order(combat)
    _restore_revived_order(combat)
    _animate_hp_changes(combat, hp_before)
    return True


def _use_item_outside_combat(owner, item_id, target_id, local_player_id, remote_players):
    inventory = owner.get("inventory", []) if isinstance(owner, dict) else owner.inventory
    item = next((item for item in inventory if item.get("id") == item_id), None)
    if not item:
        return False
    definition = item_definition(item)
    effect_id = definition.get("effect_id")
    if not effect_id or effect_id not in SPELLS:
        return False
    owner_id = owner.get("id") if isinstance(owner, dict) else owner.id
    target = owner if target_id is None or target_id in (owner_id, local_player_id) else None
    if target is None:
        target = next((remote.get("actor") for remote in remote_players
                       if _player_id(remote) == target_id and remote.get("actor")), None)
    if target is None:
        return False
    caster_data = vars(owner) if not isinstance(owner, dict) else owner
    target_data = vars(target) if not isinstance(target, dict) else target
    arena = ARENAS.get(SCENARIOS.get(DEFAULT_SCENARIO, {}).get("arena"), {})
    was_downed = bool(target_data.get("downed") or target_data.get("current_hp", 1) <= 0)
    result = resolve_spell(effect_id, caster_data, [target_data],
                           line_of_sight=_line_of_sight(caster_data, target_data, arena),
                           from_consumable=True)
    if not result.get("success"):
        return False
    if was_downed and not target_data.get("downed") and target_data.get("current_hp", 0) > 0:
        penalty = charge_xp_penalty(target_data, 2)
        if penalty:
            target_data["last_revival_xp_penalty"] = penalty
    stack_quantity = max(1, int(item.get("quantity", 1)))
    if stack_quantity > 1:
        item["quantity"] = stack_quantity - 1
    else:
        inventory.remove(item)
        quick_items = caster_data.setdefault("quick_items", {})
        for key, quick_item in list(quick_items.items()):
            if quick_item == item_id:
                quick_items[key] = None
    if not isinstance(owner, dict):
        owner.current_hp = caster_data.get("current_hp", owner.current_hp)
        owner.downed = caster_data.get("downed", owner.downed)
    if not isinstance(target, dict):
        target.current_hp = target_data.get("current_hp", target.current_hp)
        target.downed = target_data.get("downed", target.downed)
    return True


def _apply_action(combat, actor_id, action):
    action_type = action.get("type")
    if action_type == "attack":
        _do_attack(combat, actor_id, action.get("target"))
    elif action_type == "ranged_attack":
        _do_attack(combat, actor_id, action.get("target"), attack_mode="ranged")
    elif action_type == "throw":
        _do_attack(combat, actor_id, action.get("target"), attack_mode="throw")
    elif action_type == 'cast_spell':
        _do_spell(combat, actor_id, action.get('spell'), action.get('target'))
    elif action_type == 'use_ability':
        _do_ability(combat, actor_id, action.get('ability'), action.get('target'))
    elif action_type == "use_item":
        _do_item(combat, actor_id, action.get("item"), action.get("target"))
    elif action_type == "equip_item":
        entry = combat["actors"].get(actor_id)
        if entry:
            equip_item(entry["data"], action.get("item"), action.get("slot"))
    elif action_type == "unequip_item":
        entry = combat["actors"].get(actor_id)
        if entry:
            unequip_item(entry["data"], action.get("slot"))
    elif action_type == "end_turn" and actor_id == _active_actor_id(combat):
        _advance_turn(combat)
    elif action_type == "move" and actor_id == _active_actor_id(combat):
        entry = combat["actors"].get(actor_id)
        if not entry or entry["downed"]:
            return
        if has_condition(entry["data"], "bound_in_briar"):
            _reject_action(combat,
                           f"{entry['data'].get('name', actor_id)} is bound in briar.",
                           actor_id)
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
    beds = arena.get("inn_beds", [])
    bed = beds[0] if beds else None
    prepared = []
    for player_id, target, data in players:
        if location == "inn":
            if not bed:
                return {"_action_error": "There is no inn bed in this area."}
            distance_to_bed = edge_distance_feet(
                data, bed, PIXELS_PER_FOOT, ACTOR_SIZE)
            if distance_to_bed > int(bed.get("interaction_range_feet", 5)):
                return {"_action_error": f"Move within {bed.get('interaction_range_feet', 5)} feet of the inn bed to rest."}
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
            vars(target).update(data)
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


def _handle_action_request(actor, local_player_id, actor_id, action, remote_players, combat):
    if action.get("type") == "chat":
        speaker = (actor if actor_id == local_player_id else next(
            (remote.get("actor") for remote in remote_players
             if _player_id(remote) == actor_id), None))
        speaker_data = vars(speaker) if hasattr(speaker, "__dict__") else speaker or {}
        name = speaker_data.get("name", "Actor")
        text = str(action.get("text", "")).strip()[:160]
        if text.lower().startswith("/act "):
            emote = text[5:].strip()
            if emote and combat is not None:
                _log(combat, f"{name} acts {emote}.")
        return combat
    if action.get("type") == "rest_outdoor":
        return _resolve_party_rest(actor, local_player_id, remote_players,
                                   combat, "outdoor")
    if action.get("type") == "rest_inn":
        return _resolve_party_rest(actor, local_player_id, remote_players,
                                   combat, "inn")
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
    if action.get("type") in {"loot_take", "loot_take_all", "loot_finish"}:
        if not combat or combat.get("active"):
            return {"_action_error": "There is no corpse available to loot."}
        corpse_id = action.get("target")
        corpse = combat.get("actors", {}).get(corpse_id)
        if (not corpse or corpse.get("team") != "enemies"
                or not corpse.get("downed")):
            return {"_action_error": "That corpse is no longer available."}
        now = pygame.time.get_ticks()
        expiry = corpse.get("corpse_despawn_at")
        if expiry is not None and now >= expiry:
            return {"_action_error": "That corpse has already been looted and is gone."}
        player_entry = combat.get("actors", {}).get(actor_id)
        owner = (player_entry.get("data") if player_entry else
                 (actor if actor_id == local_player_id else next(
                     (remote.get("actor") for remote in remote_players
                      if _player_id(remote) == actor_id and remote.get("actor")), None)))
        if owner is None:
            return {"_action_error": "Character is unavailable."}
        data = owner if isinstance(owner, dict) else vars(owner)
        if actor_id == local_player_id:
            loot_x, loot_y = actor.x, actor.y
        else:
            remote = next((item for item in remote_players
                           if _player_id(item) == actor_id), {})
            loot_x, loot_y = remote.get("x", data.get("x", 0)), remote.get("y", data.get("y", 0))
        loot_position = {"x": loot_x, "y": loot_y,
                         "width": ACTOR_SIZE, "height": ACTOR_SIZE}
        distance = edge_distance_feet(loot_position, corpse,
                                      PIXELS_PER_FOOT, ACTOR_SIZE)
        if distance > 5:
            return {"_action_error": "Move within 5 feet of the corpse to loot it."}

        loot = corpse.setdefault("loot", [])
        if action["type"] in {"loot_take", "loot_take_all"}:
            if action["type"] == "loot_take_all":
                claimed = list(loot)
                loot.clear()
            else:
                item_id = action.get("item_id")
                item = next((item for item in loot if item.get("id") == item_id), None)
                if item is None:
                    return {"_action_error": "That item has already been taken."}
                claimed = [item]
                loot.remove(item)
            inventory = data.setdefault("inventory", [])
            for item in claimed:
                definition = item_definition(item)
                template_id = item.get("template_id")
                quantity = max(1, int(item.get("quantity", 1) or 1))
                if definition.get("stackable") and template_id:
                    max_stack = max(1, int(definition.get("max_stack", 99)))
                    remaining = quantity
                    for existing in inventory:
                        if existing.get("template_id") != template_id:
                            continue
                        current = max(1, int(existing.get("quantity", 1) or 1))
                        added = min(remaining, max(0, max_stack - current))
                        existing["quantity"] = current + added
                        remaining -= added
                        if not remaining:
                            break
                    while remaining:
                        added = min(remaining, max_stack)
                        copy_item = deepcopy(item)
                        copy_item["id"] = uuid.uuid4().hex[:12]
                        copy_item["quantity"] = added
                        inventory.append(copy_item)
                        remaining -= added
                else:
                    inventory.append(deepcopy(item))
            if player_entry:
                player_entry["data"].update(data)
            for item in claimed:
                _log(combat, f"{data.get('name', actor_id)} takes {item.get('name', 'an item')} from the shared loot.")
            if action["type"] == "loot_take_all":
                corpse["corpse_despawn_at"] = now + CORPSE_DESPAWN_MS
            return combat

        if corpse.get("corpse_despawn_at") is None:
            corpse["corpse_despawn_at"] = now + CORPSE_DESPAWN_MS
        _log(combat, f"Looting {corpse.get('data', {}).get('name', 'the corpse')} ends.")
        return combat
    if action.get("type") in {"trainer_purchase", "unlock_class", "release_spirit"}:
        if combat and combat.get("active") and action.get("type") in {
                "trainer_purchase", "unlock_class"}:
            return {"_action_error": "You cannot train during combat."}
        entry = (combat or {}).get("actors", {}).get(actor_id)
        owner = (entry.get("data") if entry else
                 (actor if actor_id == local_player_id else next(
                     (remote.get("actor") for remote in remote_players
                      if _player_id(remote) == actor_id and remote.get("actor")), None)))
        if owner is None:
            return {"_action_error": "Character is unavailable."}
        data = owner if isinstance(owner, dict) else vars(owner)
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
            table = SPELLS if kind == "spell" else ABILITIES if kind == "ability" else {}
            definition = table.get(item_id)
            if (not definition or class_id not in definition.get("classes", [])
                    or definition.get("acquisition") != "trainer_purchase"):
                return {"_action_error": "That trainer option is unavailable."}
            if class_id not in unlocked_classes(data):
                return {"_action_error": "Unlock this class before buying its options."}
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
        bed = next(iter(arena.get("inn_beds", [])), {})
        data["x"] = int(bed.get("respawn_x", bed.get("x", 130) + bed.get("width", 100) + 12))
        data["y"] = int(bed.get("respawn_y", bed.get("y", 170) + bed.get("height", 60) + 12))
        if not isinstance(owner, dict):
            owner.x, owner.y, owner.downed = data["x"], data["y"], False
            owner.current_hp, owner.withdrawn = data["current_hp"], True
        if entry:
            entry["x"], entry["y"], entry["downed"] = data["x"], data["y"], False
            if actor_id == local_player_id:
                actor.x, actor.y = data["x"], data["y"]
                actor.current_hp, actor.downed, actor.withdrawn = data["current_hp"], False, True
            _remove_downed_from_order(combat)
            _log(combat, f"{data.get('name', 'Actor')} releases their spirit and returns to the inn, losing {penalty} XP.")
        return combat or _progression_sync_state(
            actor, local_player_id, remote_players)
    if not combat or not combat.get("active"):
        if action.get("type") in {"equip_item", "unequip_item", "use_item"}:
            owner = actor if actor_id == local_player_id else next(
                (remote.get("actor") for remote in remote_players
                 if _player_id(remote) == actor_id and remote.get("actor")), None)
            if owner is None:
                return combat
            if action["type"] == "equip_item":
                equip_item(owner, action.get("item"), action.get("slot"))
            elif action["type"] == "unequip_item":
                unequip_item(owner, action.get("slot"))
            else:
                target_id = action.get("target")
                if target_id == actor_id:
                    target_id = owner.get("id") if isinstance(owner, dict) else owner.id
                _use_item_outside_combat(owner, action.get("item"), target_id,
                                          local_player_id, remote_players)
            if combat:
                changed = {"inventory", "equipment", "current_hp", "downed",
                           "xp_total", "xp_spent_by_level", "level", "classes",
                           "class_spell_purchases", "class_ability_purchases",
                           "known_spells", "prepared_spells", "known_abilities",
                           "withdrawn", "x", "y"}
                source = vars(owner) if not isinstance(owner, dict) else owner
                owner_entry = combat.get("actors", {}).get(actor_id)
                if owner_entry:
                    for key in changed:
                        if key in source:
                            owner_entry["data"][key] = deepcopy(source[key])
                selected_id = action.get("target")
                target_remote = next((remote.get("actor") for remote in remote_players
                                      if _player_id(remote) == selected_id and remote.get("actor")), None)
                target_entry = combat.get("actors", {}).get(selected_id)
                if target_remote and target_entry:
                    for key in changed:
                        if key in target_remote:
                            target_entry["data"][key] = deepcopy(target_remote[key])
                    target_entry["downed"] = bool(target_entry["data"].get("downed", False))
            return combat or _progression_sync_state(
                actor, local_player_id, remote_players)
        if action.get("type") not in {"attack", "ranged_attack", "throw", "cast_spell", "use_ability"}:
            return combat
        combat = _new_combat(actor, local_player_id, remote_players)
        _log(combat, "Combat started.")
        action_type = action.get('type')
        resolved = (
            _do_attack(combat, actor_id, action.get('target'),
                       attack_mode={"throw": "throw", "ranged_attack": "ranged"}.get(action_type, "primary"))
            if action_type in {"attack", "ranged_attack", "throw"} else
            _do_spell(combat, actor_id, action.get('spell'), action.get('target'))
            if action_type == 'cast_spell' else
            _do_ability(combat, actor_id, action.get('ability'), action.get('target'))
        )
        if not resolved:
            # Preserve the explanation without applying encounter spawn
            # positions to actors or leaving a failed encounter snapshot live.
            return {"_action_error": combat.get("log", ["Action failed."])[-1]}
        combat["budgets"][actor_id]["skip_next"] = True
        if combat.get("active"):
            current_id = _active_actor_id(combat)
            current = combat["actors"][current_id]
            if combat["budgets"][current_id].get("skip_next"):
                _advance_turn(combat)
        return combat
    if action.get("type") in {"equip_item", "unequip_item"}:
        entry = combat.get("actors", {}).get(actor_id)
        if entry:
            if action["type"] == "equip_item":
                equip_item(entry["data"], action.get("item"), action.get("slot"))
            else:
                unequip_item(entry["data"], action.get("slot"))
    elif actor_id == _active_actor_id(combat):
        _apply_action(combat, actor_id, action)
    elif action.get("type") in {"attack", "ranged_attack", "throw", "cast_spell", "use_ability", "use_item", "move"}:
        _reject_action(combat, "It is not your turn.", action.get("target") or actor_id)
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
    actor.inventory = deepcopy(entry["data"].get("inventory", actor.inventory))
    inventory_ids = {item.get("id") for item in actor.inventory}
    quick_items = actor.quick_items if isinstance(actor.quick_items, dict) else {}
    actor.quick_items = {
        key: item_id if item_id in inventory_ids else None
        for key, item_id in {"q": None, "e": None, **quick_items}.items()
    }
    # Hotbar and quick-slot assignments are local control preferences. Keep
    # the local save authoritative instead of overwriting it from a network
    # combat snapshot that may predate the player's assignment.
    actor.equipment = deepcopy(entry["data"].get("equipment", actor.equipment))
    actor.abilities = deepcopy(entry["data"].get("abilities", actor.abilities))
    actor.attribute_points_spent = deepcopy(entry["data"].get(
        "attribute_points_spent", actor.attribute_points_spent))
    actor.active_weapon_set = entry["data"].get("active_weapon_set", actor.active_weapon_set)
    actor.xp_total = entry["data"].get("xp_total", actor.xp_total)
    actor.xp_earned_by_level = deepcopy(
        entry["data"].get("xp_earned_by_level", actor.xp_earned_by_level))
    actor.xp_spent_by_level = deepcopy(
        entry["data"].get("xp_spent_by_level", actor.xp_spent_by_level))
    actor.xp_rest_spent_by_level = deepcopy(
        entry["data"].get("xp_rest_spent_by_level", actor.xp_rest_spent_by_level))
    actor.spell_points = entry["data"].get("spell_points", actor.spell_points)
    actor.class_resources = deepcopy(
        entry["data"].get("class_resources", actor.class_resources))
    actor.gold = entry["data"].get("gold", actor.gold)
    actor.level = entry["data"].get("level", actor.level)
    actor.classes = deepcopy(entry["data"].get("classes", actor.classes))
    actor.class_spell_purchases = deepcopy(entry["data"].get(
        "class_spell_purchases", actor.class_spell_purchases))
    actor.class_ability_purchases = deepcopy(entry["data"].get(
        "class_ability_purchases", actor.class_ability_purchases))
    actor.known_spells = deepcopy(entry["data"].get("known_spells", actor.known_spells))
    actor.prepared_spells = deepcopy(entry["data"].get("prepared_spells", actor.prepared_spells))
    actor.known_abilities = deepcopy(entry["data"].get("known_abilities", actor.known_abilities))
    actor.withdrawn = bool(entry["data"].get("withdrawn", False))
    actor.outdoor_rest_streak = entry["data"].get(
        "outdoor_rest_streak", actor.outdoor_rest_streak)
    # Exploration owns the live position after a fight. The retained combat
    # snapshot is intentionally static while world mobs/corpses persist; copying
    # its old coordinates every frame makes exploration movement snap back.
    if entry["data"].get("withdrawn") or combat.get("active"):
        actor.x, actor.y = entry["x"], entry["y"]


def _draw_combat_ui(screen, font, combat, actor_id, observer_data, log_scroll=0):
    if not combat or combat.get("sync_only"):
        return pygame.Rect(0, 0, 0, 0)
    panel_width, panel_height = 390, 142
    panel_x = screen.get_width() - panel_width - 10
    panel_y = screen.get_height() - panel_height - 10
    panel_rect = pygame.Rect(panel_x, panel_y, panel_width, panel_height)
    panel = pygame.Surface((panel_width, panel_height), pygame.SRCALPHA)
    panel.fill((0, 0, 0, 180))
    screen.blit(panel, (panel_x, panel_y))
    if combat.get("active"):
        current = _active_actor_id(combat)
        budgets = combat.get("budgets", {}).get(current, {})
        header = (f"Round {combat['round']}  |  Turn: "
                  f"{combat['actors'][current]['data'].get('name', current)}")
        if current == actor_id:
            header += f"  |  Movement: {budgets.get('movement', 0):.0f} ft"
        small_font = pygame.font.Font(None, 14)
        screen.blit(small_font.render(_fit_ui_text(
            small_font, header, panel_width - 20), True, (255, 230, 120)),
                    (panel_x + 10, panel_y + 8))
    own_data = combat.get("actors", {}).get(actor_id, {}).get("data", observer_data)
    resource_line = (
        f"HP {own_data.get('current_hp', 0)}/{effective_max_hp(own_data)}  |  "
        f"Spell points {own_data.get('spell_points', 0)}/{spell_point_max(own_data)}")
    small_font = pygame.font.Font(None, 14)
    screen.blit(small_font.render(_fit_ui_text(
        small_font, resource_line, panel_width - 20), True, (210, 230, 255)),
                (panel_x + 10, panel_y + 30))
    log_lines = combat.get("log", [])
    wrapped_lines = []
    text_width = panel_width - 20
    for message in log_lines:
        words = str(message).split()
        wrapped = ""
        for word in words:
            candidate = f"{wrapped} {word}".strip()
            if wrapped and small_font.size(candidate)[0] > text_width:
                wrapped_lines.append(wrapped)
                wrapped = word
            else:
                wrapped = candidate
        if wrapped:
            wrapped_lines.append(wrapped)
    max_rows = 5
    end = max(0, len(wrapped_lines) - max(0, int(log_scroll)))
    visible = wrapped_lines[max(0, end - max_rows):end]
    for index, message in enumerate(visible):
        screen.blit(small_font.render(message, True, (245, 245, 245)),
                    (panel_x + 10, panel_y + 52 + index * 17))
    return panel_rect


def run_game(actor, get_other_players, send_state, multiplayer=True, combat_transport=None,
             party_status=None, invite_address=None):
    pygame.init()
    screen = pygame.display.set_mode(SCREEN_SIZE)
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
    arrow_sheet = pygame.image.load(str(asset_path("asset_pack/Arrow01.png"))).convert_alpha()
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
    last_combat_key_move = 0
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
    feedback_target_id = None
    feedback_flash_until = 0
    feedback_seen_id = None
    font = pygame.font.Font(None, 20)
    save_notice_until = 0
    invite_notice = ''
    invite_notice_until = 0
    action_notice = ""
    action_notice_until = 0
    controls_visible = False
    interact_prompt = None
    exit_to_menu = False
    quit_prompt = False
    from inventory_ui import InventoryScreen
    from spellbook_ui import SpellbookUI, normalize_action_hotbars, action_definition
    from trainer_ui import TrainerUI
    from loot_ui import LootUI
    inventory_ui = InventoryScreen()
    spellbook_ui = SpellbookUI()
    trainer_ui = TrainerUI()
    loot_ui = LootUI()
    combat_log_rect = pygame.Rect(0, 0, 0, 0)
    combat_log_scroll = 0
    chat_mode = False
    chat_text = ""
    local_speech = None
    explore_destination = None

    def submit(action):
        nonlocal combat, action_notice, action_notice_until
        nonlocal feedback_target_id, feedback_flash_until
        if is_host:
            updated = _handle_action_request(
                actor, player_id, player_id, action, remote_players, combat)
            if updated and "_action_error" in updated:
                action_notice = f"Combat log: {updated['_action_error']}"
                action_notice_until = pygame.time.get_ticks() + 2400
                feedback_target_id = action.get("target") or player_id
                feedback_flash_until = pygame.time.get_ticks() + 700
                return
            if updated and "_action_notice" in updated:
                action_notice = updated["_action_notice"]
                action_notice_until = pygame.time.get_ticks() + 3000
                if updated.get("sync_only"):
                    combat = updated
                return
            combat = updated
            _sync_local_actor(actor, combat, player_id)
        else:
            combat_transport["submit"](action)

    def use_bar_action(assigned_action):
        nonlocal action_notice, action_notice_until
        if not assigned_action:
            return False
        action_kind, action_id, definition = action_definition(assigned_action)
        if not definition:
            return False
        targeting = definition.get("targeting", {})
        if targeting.get("mode") != "self" and not selected_target:
            action_notice = "Select a target first."
            action_notice_until = pygame.time.get_ticks() + 1800
            return True
        if action_kind == "action":
            action_types = {"weapon_attack": "attack",
                            "ranged_weapon_attack": "ranged_attack",
                            "throw_weapon": "throw"}
            submit({"type": action_types[action_id], "target": selected_target})
        elif action_kind == "spell":
            submit({"type": "cast_spell", "spell": action_id,
                    "target": selected_target})
        else:
            submit({"type": "use_ability", "ability": action_id,
                    "target": selected_target})
        return True

    while running:
        dt = clock.tick(60)
        remote_players = get_other_players() if multiplayer else []
        if is_host:
            if combat and combat.get('active'):
                _remove_disconnected_players(combat, remote_players, player_id)
                _add_joined_players(combat, remote_players)
            for request in combat_transport["poll"]():
                updated = _handle_action_request(
                    actor, player_id, request["player_id"], request["action"],
                    remote_players, combat)
                if updated and "_action_error" in updated:
                    action_notice = updated["_action_error"]
                    action_notice_until = pygame.time.get_ticks() + 2400
                elif updated and "_action_notice" in updated:
                    action_notice = updated["_action_notice"]
                    action_notice_until = pygame.time.get_ticks() + 3000
                    if updated.get("sync_only"):
                        combat = updated
                else:
                    combat = updated
            if combat:
                now = pygame.time.get_ticks()
                for mob_id, entry in list(combat.get("actors", {}).items()):
                    expiry = entry.get("corpse_despawn_at")
                    if (entry.get("team") == "enemies" and expiry is not None
                            and now >= expiry):
                        del combat["actors"][mob_id]
                players_for_spawn = [_combat_snapshot(player_id, vars(actor))]
                players_for_spawn.extend(
                    _combat_snapshot(_player_id(remote), remote["actor"])
                    for remote in remote_players if remote.get("actor"))
                _settle_victory(combat, players_for_spawn)
            if not combat or not combat.get("active"):
                world_mobs = ([ _world_mob_from_entry(entry)
                                for entry in combat.get("actors", {}).values()
                                if entry.get("team") == "enemies"]
                              if combat and not combat.get("sync_only") else None)
                trigger = _combat_trigger(
                    actor, player_id, remote_players,
                    world_mobs=world_mobs)
                if trigger:
                    spotted_player, enemy_id = trigger
                    combat = _new_combat(
                        actor, player_id, remote_players,
                        world_mobs=world_mobs)
                    player_name = combat["actors"][spotted_player]["data"].get(
                        "name", spotted_player)
                    enemy_name = combat["actors"][enemy_id]["data"].get(
                        "name", "An enemy")
                    _log(combat, (f"{enemy_name} spots {player_name} within "
                                  f"{COMBAT_TRIGGER_RANGE_FEET} feet. Combat begins!"))
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

        action_feedback = (combat or {}).get("action_feedback", {})
        if action_feedback.get("id") and action_feedback["id"] != feedback_seen_id:
            feedback_seen_id = action_feedback["id"]
            feedback_target_id = action_feedback.get("target_id")
            feedback_flash_until = pygame.time.get_ticks() + 700

        active_id = _active_actor_id(combat)
        local_can_act = (not combat or not combat.get("active") or
                         active_id == player_id)
        current_frames = sprite_frames.get(actor.avatar, default_frames)
        current_arena = (combat or {}).get("arena") or ARENAS.get(
            SCENARIOS.get(DEFAULT_SCENARIO, {}).get("arena"), {})
        camera = _camera_offset(actor, current_arena, screen.get_size())

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                exit_to_menu = False
                running = False
            elif chat_mode and event.type == pygame.TEXTINPUT:
                chat_text = (chat_text + event.text)[:160]
            elif chat_mode and event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    chat_mode, chat_text = False, ""
                    pygame.key.stop_text_input()
                elif event.key == pygame.K_BACKSPACE:
                    chat_text = chat_text[:-1]
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    message = chat_text.strip()
                    if message:
                        bubble_text = message
                        if message.lower().startswith("/act "):
                            emote = message[5:].strip()
                            bubble_text = (f"{actor.name} acts {emote}" if emote
                                           else "")
                        if bubble_text:
                            local_speech = {"text": bubble_text,
                                            "expires_at": time.time() + 2.5}
                            send_state(actor.x, actor.y, local_animation["anim"],
                                       facing_left, vars(actor), local_speech)
                            if message.lower().startswith("/act "):
                                submit({"type": "chat", "text": message})
                            else:
                                # Ordinary speech is visible overhead but stays
                                # out of the combat event log.
                                submit({"type": "chat", "text": message})
                    chat_mode, chat_text = False, ""
                    pygame.key.stop_text_input()
            elif quit_prompt:
                if event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_y, pygame.K_RETURN, pygame.K_KP_ENTER):
                        running = False
                    elif event.key in (pygame.K_n, pygame.K_ESCAPE):
                        quit_prompt = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    panel_width, panel_height = 310, 112
                    panel_x = (screen.get_width() - panel_width) // 2
                    panel_y = screen.get_height() - panel_height - 32
                    yes_rect = pygame.Rect(panel_x + 28, panel_y + 64, 112, 32)
                    no_rect = pygame.Rect(panel_x + 170, panel_y + 64, 112, 32)
                    if yes_rect.collidepoint(event.pos):
                        running = False
                    elif no_rect.collidepoint(event.pos):
                        quit_prompt = False
            elif chat_mode:
                continue
            elif actor.downed:
                if event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                    submit({"type": "release_spirit"})
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_m:
                    exit_to_menu = True
                    running = False
                continue
            elif event.type == pygame.MOUSEWHEEL:
                if loot_ui.visible:
                    corpse = ((combat or {}).get("actors", {}).get(loot_ui.corpse_id))
                    loot_ui.handle_event(event, corpse.get("loot", []) if corpse else [])
                elif combat_log_rect.collidepoint(pygame.mouse.get_pos()):
                    log_count = sum(max(1, math.ceil(
                        font.size(str(message))[0] / 370))
                        for message in (combat or {}).get("log", []))
                    combat_log_scroll = max(0, min(max(0, log_count - 5),
                                                  combat_log_scroll + event.y))
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_F1:
                controls_visible = not controls_visible
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_F2:
                spellbook_ui.tooltips_enabled = not spellbook_ui.tooltips_enabled
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_BACKQUOTE:
                spellbook_ui.cycle_bar()
            elif spellbook_ui.visible:
                if event.type == pygame.KEYDOWN and event.key in (pygame.K_MINUS,
                                                                    pygame.K_ESCAPE):
                    spellbook_ui.toggle()
                else:
                    spell_data = vars(actor)
                    spellbook_action = spellbook_ui.handle_event(event, spell_data)
                    if spellbook_action:
                        submit(spellbook_action)
                    actor.spell_hotbars = deepcopy(
                        spell_data.get("spell_hotbars", actor.spell_hotbars))
            elif trainer_ui.visible:
                trainer_data = ((combat or {}).get("actors", {}).get(player_id, {})
                                .get("data", vars(actor)))
                trainer_action = trainer_ui.handle_event(event, trainer_data)
                if trainer_action:
                    submit(trainer_action)
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_MINUS:
                spellbook_ui.toggle()
            elif interact_prompt:
                if event.type == pygame.KEYDOWN and event.key in (
                        pygame.K_y, pygame.K_RETURN, pygame.K_KP_ENTER):
                    if interact_prompt.get("type") == "inn_bed":
                        submit({"type": "rest_inn"})
                    interact_prompt = None
                elif event.type == pygame.KEYDOWN and event.key in (
                        pygame.K_n, pygame.K_ESCAPE):
                    interact_prompt = None
            elif loot_ui.visible:
                corpse = ((combat or {}).get("actors", {}).get(loot_ui.corpse_id))
                loot_action = loot_ui.handle_event(
                    event, corpse.get("loot", []) if corpse else [])
                if loot_action:
                    submit(loot_action)
                    if loot_action["type"] in {"loot_finish", "loot_take_all"}:
                        loot_ui.close()
            elif event.type == pygame.KEYDOWN and event.key in (pygame.K_q, pygame.K_e):
                key = "q" if event.key == pygame.K_q else "e"
                item_id = actor.quick_items.get(key)
                if item_id:
                    target_id = player_id
                    if selected_target:
                        target_entry = (combat or {}).get("actors", {}).get(selected_target)
                        remote_target = next((remote for remote in remote_players
                                              if _player_id(remote) == selected_target), None)
                        if ((target_entry and target_entry.get("team") == "players")
                                or remote_target):
                            target_id = selected_target
                    submit({"type": "use_item", "item": item_id,
                            "target": target_id})
                else:
                    action_notice = f"No item is bound to {key.upper()}. Bind one in Inventory."
                    action_notice_until = pygame.time.get_ticks() + 2000
            elif inventory_ui.visible:
                inventory_data = (combat.get("actors", {}).get(player_id, {}).get("data", {})
                                  if combat else vars(actor))
                inventory_data["quick_items"] = actor.quick_items
                inventory_action = inventory_ui.handle_event(event, inventory_data)
                if inventory_action:
                    if inventory_action.get("type") == "use_item":
                        inventory_action["target"] = selected_target
                    if not is_host and not (combat and combat.get("active")):
                        if inventory_action["type"] == "equip_item":
                            equip_item(actor, inventory_action.get("item"),
                                       inventory_action.get("slot"))
                        elif inventory_action["type"] == "unequip_item":
                            unequip_item(actor, inventory_action.get("slot"))
                        elif inventory_action["type"] == "use_item":
                            _use_item_outside_combat(
                                actor, inventory_action.get("item"),
                                inventory_action.get("target"), player_id, remote_players)
                    submit(inventory_action)
                actor.quick_items = deepcopy(inventory_data.get(
                    "quick_items", actor.quick_items))
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_i:
                inventory_ui.toggle()
            elif event.type == pygame.KEYDOWN and event.key in (
                    pygame.K_RETURN, pygame.K_KP_ENTER):
                chat_mode, chat_text = True, ""
                pygame.key.start_text_input()
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_f:
                nearby = []
                for kind, items in (("trainer", current_arena.get("trainers", [])),
                                    ("inn_bed", current_arena.get("inn_beds", []))):
                    for item in items:
                        distance = edge_distance_feet(
                            vars(actor), item, PIXELS_PER_FOOT, ACTOR_SIZE)
                        if distance <= int(item.get("interaction_range_feet", 5)):
                            nearby.append((distance, kind, item))
                for corpse in (combat or {}).get("actors", {}).values():
                    if (combat and combat.get("active")
                            or corpse.get("team") != "enemies"
                            or not corpse.get("downed")):
                        continue
                    expiry = corpse.get("corpse_despawn_at")
                    if expiry is not None and pygame.time.get_ticks() >= expiry:
                        continue
                    distance = edge_distance_feet(
                        vars(actor), corpse, PIXELS_PER_FOOT, ACTOR_SIZE)
                    if distance <= 5:
                        nearby.append((distance, "loot", corpse))
                interaction = min(nearby, default=None, key=lambda item: item[0])
                if interaction and interaction[1] == "trainer":
                    trainer_ui.toggle(vars(actor))
                elif interaction and interaction[1] == "loot":
                    loot_ui.open(interaction[2]["id"])
                elif interaction:
                    bed = interaction[2]
                    interact_prompt = {"type": "inn_bed", "name": bed.get(
                        "name", "Inn Bed")}
                else:
                    action_notice = "There is nothing nearby to interact with."
                    action_notice_until = pygame.time.get_ticks() + 2000
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_z:
                submit({"type": "rest_outdoor"})
            elif event.type == pygame.QUIT:
                exit_to_menu = False
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_m:
                exit_to_menu = True
                running = False
            elif (event.type == pygame.KEYDOWN and event.key == pygame.K_n
                  and is_host and combat and combat.get("result")
                  and combat["result"].get("outcome") != "victory"):
                combat = _new_combat(actor, player_id, remote_players,
                                     combat.get("scenario_id", DEFAULT_SCENARIO))
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                if selected_target:
                    selected_target = None
                else:
                    quit_prompt = True
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
                _handle_right_click(world_click, actor, click_players)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                clicked = False
                assigned_action = spellbook_ui.hud_action_at(event.pos)
                if assigned_action and not spellbook_ui.visible:
                    use_bar_action(assigned_action)
                    clicked = True
                own_rect = _target_clickbox(actor.x - camera[0],
                                            actor.y - camera[1])
                if not clicked and own_rect.collidepoint(event.pos):
                    selected_target = player_id
                    clicked = True
                if not clicked:
                    enemy_entries = list((combat or {}).get("actors", {}).values())
                    if not combat or combat.get("sync_only"):
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
                elif not clicked and not (combat and combat.get("active")):
                    explore_destination = (event.pos[0] + camera[0] - ACTOR_SIZE / 2,
                                           event.pos[1] + camera[1] - ACTOR_SIZE / 2)
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                if selected_target:
                    submit({"type": "ranged_attack", "target": selected_target})
            elif event.type == pygame.KEYDOWN and event.key in (
                    pygame.K_0, pygame.K_1, pygame.K_2, pygame.K_3,
                    pygame.K_4, pygame.K_5, pygame.K_6, pygame.K_7,
                    pygame.K_8, pygame.K_9):
                slot_index = 9 if event.key == pygame.K_0 else event.key - pygame.K_1
                bars = normalize_action_hotbars(vars(actor).get("spell_hotbars"))
                hotbar_action = bars[spellbook_ui.active_bar][slot_index]
                if hotbar_action:
                    action_kind, action_id, definition = action_definition(hotbar_action)
                    targeting = definition.get("targeting", {})
                    needs_target = targeting.get("mode") != "self"
                    if ((action_kind == "spell" or targeting) and needs_target
                            and not selected_target):
                        continue
                    if action_kind == "action":
                        action_types = {
                            "weapon_attack": "attack",
                            "ranged_weapon_attack": "ranged_attack",
                            "throw_weapon": "throw",
                        }
                        submit({"type": action_types[action_id],
                                "target": selected_target})
                    elif action_kind == "spell":
                        submit({"type": "cast_spell", "spell": action_id,
                                "target": selected_target})
                    else:
                        submit({"type": "use_ability", "ability": action_id,
                                "target": selected_target})
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_t:
                if selected_target:
                    submit({"type": "throw", "target": selected_target})
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_LSHIFT:
                if combat and combat.get("active") and local_can_act:
                    submit({"type": "end_turn"})

        keys = pygame.key.get_pressed()
        moving = False
        if (not chat_mode and combat and combat.get("active")
                and local_can_act and not actor.downed):
            key_dx = int(bool(keys[pygame.K_RIGHT] or keys[pygame.K_d])) - int(
                bool(keys[pygame.K_LEFT] or keys[pygame.K_a]))
            key_dy = int(bool(keys[pygame.K_DOWN] or keys[pygame.K_s])) - int(
                bool(keys[pygame.K_UP] or keys[pygame.K_w]))
            now = pygame.time.get_ticks()
            if (key_dx or key_dy) and now - last_combat_key_move >= 90:
                current_entry = combat.get("actors", {}).get(player_id, {})
                current_x = current_entry.get("x", actor.x)
                current_y = current_entry.get("y", actor.y)
                frame_scale = max(0.25, min(1.5, dt / (1000 / 60)))
                step = speed * frame_scale * 6
                length = math.hypot(key_dx, key_dy)
                submit({"type": "move",
                        "x": current_x + key_dx / length * step,
                        "y": current_y + key_dy / length * step})
                last_combat_key_move = now
        if (not chat_mode and not actor.downed and
                (not combat or not combat.get("active") or actor.withdrawn)):
            occupied = []
            for remote in remote_players:
                occupied.append(_actor_hitbox(remote.get("x", 0),
                                              remote.get("y", 0)))
            if combat:
                occupied.extend(
                    _actor_hitbox(entry["x"], entry["y"])
                    for entry in combat["actors"].values()
                    if entry["team"] == "enemies" and not entry["downed"]
                )
            else:
                for spawn in SCENARIOS.get(DEFAULT_SCENARIO, {}).get("enemies", []):
                    occupied.append(_actor_hitbox(spawn.get("x", 0),
                                                  spawn.get("y", 0)))
            if (keys[pygame.K_w] or keys[pygame.K_a] or keys[pygame.K_s]
                    or keys[pygame.K_d] or keys[pygame.K_UP]
                    or keys[pygame.K_DOWN] or keys[pygame.K_LEFT]
                    or keys[pygame.K_RIGHT]):
                explore_destination = None
            if explore_destination:
                dx, dy = (explore_destination[0] - actor.x,
                          explore_destination[1] - actor.y)
                distance = math.hypot(dx, dy)
                if distance <= speed:
                    explore_destination = None
                else:
                    step = min(speed, distance)
                    path_x, path_y = _walk_destination(
                        actor.x, actor.y, dx / distance * step,
                        dy / distance * step, current_arena, occupied)
                    moving = (path_x != actor.x or path_y != actor.y)
                    actor.x, actor.y = path_x, path_y
                    facing_left = dx < 0 if dx else facing_left
                    if not moving:
                        explore_destination = None
            if not explore_destination:
                key_moving, facing_left = _move_actor(
                    actor, keys, speed, facing_left, current_arena, occupied)
                moving = moving or key_moving
        local_entry = (combat or {}).get("actors", {}).get(player_id)
        if actor.withdrawn and local_entry:
            local_entry["x"], local_entry["y"] = actor.x, actor.y
            local_entry["data"]["x"], local_entry["data"]["y"] = actor.x, actor.y
        local_requested = ("dead" if actor.downed or
                           (local_entry and local_entry.get("downed")) else
                           "walk" if moving else "idle")
        sprite = _advance_character_animation(
            local_animation, local_requested,
            local_entry.get("animation_event") if local_entry else None,
            dt, sprite_frames.get(actor.avatar, default_frames), frame_duration)
        # The combat entry is authoritative only while turns are active.
        # After victory it remains as a world/corpse snapshot, so its last
        # facing must not overwrite exploration movement every frame.
        if (combat and combat.get("active") and local_entry
                and "facing_left" in local_entry):
            facing_left = local_entry["facing_left"]
        if facing_left:
            sprite = pygame.transform.flip(sprite, True, False)

        if not is_host and combat and combat.get("active"):
            snapshot = combat.get("actors", {}).get(player_id)
            if snapshot:
                actor.x, actor.y = snapshot["x"], snapshot["y"]
        send_state(actor.x, actor.y, local_animation["anim"], facing_left,
                   vars(actor), local_speech)

        if combat:
            combat_actors = combat.get("actors", {})
            combat_is_active = bool(combat.get("active"))
            remote_players = [
                {**remote,
                 "x": combat_actors.get(_player_id(remote), {}).get("x", remote.get("x", 0)),
                 "y": combat_actors.get(_player_id(remote), {}).get("y", remote.get("y", 0)),
                 "combat_animation": combat_actors.get(_player_id(remote), {}).get("animation_event"),
                 "facing": (combat_actors.get(_player_id(remote), {}).get(
                     "facing_left", remote.get("facing", False))
                     if combat_is_active else remote.get("facing", False)),
                 "downed": combat_actors.get(_player_id(remote), {}).get("downed",
                     (remote.get("actor") or {}).get("downed", False))}
                for remote in remote_players
            ]

        camera = _camera_offset(actor, current_arena, screen.get_size())
        drawn_positions = _draw_players(
            screen, actor, sprite, remote_players, remote_animations,
            remote_positions, dt, sprite_frames, frame_duration, current_arena,
            camera, local_speech, font)
        screen_spell_data = (combat.get("actors", {}).get(player_id, {}).get("data", {})
                             if combat and combat.get("active") else vars(actor))
        scenario = (combat or {}).get("scenario") or SCENARIOS.get(DEFAULT_SCENARIO, {})
        hud_font = pygame.font.Font(None, 18)
        hud_rows = [(scenario.get("name", "Worldforge"), (245, 245, 230), font)]
        if scenario.get("objective"):
            hud_rows.append((scenario["objective"], (230, 230, 205), hud_font))
        if multiplayer:
            count = party_status() if party_status else 1 + len(remote_players)
            hud_rows.append((f"Party: {count}/8", (195, 220, 195), hud_font))
            if is_host and invite_address:
                lan_address, internet_address = invite_address
                hud_rows.append((f"LAN invite: {lan_address}",
                                 (195, 220, 195), hud_font))
                internet_text = (f"Internet invite: {internet_address}"
                                 if internet_address else
                                 "Internet: forward TCP 5555, then share your public IP:5555")
                hud_rows.append((internet_text, (195, 220, 195), hud_font))
                copy_label = ("Press C to copy invite" if internet_address
                              else "Press C to copy LAN invite")
                hud_rows.append((copy_label, (195, 220, 195), hud_font))
        hud_rows.append((f"Spell points: {screen_spell_data.get('spell_points', 0)}"
                         f"/{spell_point_max(screen_spell_data)}",
                         (210, 225, 255), hud_font))
        hud_y = 12
        for text, color, row_font in hud_rows:
            for line in _wrap_ui_lines(row_font, text, screen.get_width() - 24):
                screen.blit(row_font.render(line, True, color), (12, hud_y))
                hud_y += row_font.get_linesize() + 1
        live_combat = bool(combat and combat.get("active"))
        status_actor = ((combat or {}).get("actors", {}).get(player_id)
                        if live_combat else None)
        status_target = ((combat or {}).get("actors", {}).get(selected_target)
                         if live_combat else None)
        # Outside an active encounter, use the live exploration actor position
        # and current remote state instead of a retained combat snapshot.
        remote_target = None
        if selected_target and not status_target:
            remote_target = next((remote for remote in remote_players
                                  if _player_id(remote) == selected_target), None)
            if remote_target:
                remote_x, remote_y = remote_target.get("x", 0), remote_target.get("y", 0)
                if selected_target in drawn_positions:
                    remote_x = drawn_positions[selected_target][0] + camera[0]
                    remote_y = drawn_positions[selected_target][1] + camera[1]
                status_target = {
                    "x": remote_x, "y": remote_y,
                    "width": ACTOR_SIZE, "height": ACTOR_SIZE,
                    "hitbox": {"offset_x": (ACTOR_SIZE - ACTOR_HITBOX_WIDTH) / 2,
                               "offset_y": (ACTOR_SIZE - ACTOR_HITBOX_HEIGHT) / 2,
                               "width": ACTOR_HITBOX_WIDTH,
                               "height": ACTOR_HITBOX_HEIGHT},
                }
        if selected_target and not status_target and combat:
            retained_target = combat.get("actors", {}).get(selected_target)
            if retained_target and retained_target.get("team") == "enemies":
                status_target = retained_target
        if not status_target and selected_target:
            for index, spawn in enumerate(scenario.get("enemies", [])):
                enemy_id = spawn.get("id", f"{spawn.get('npc')}-{index + 1}")
                if enemy_id != selected_target:
                    continue
                definition = NPCS.get(spawn.get("npc"), {})
                target_x, target_y = spawn.get("x", 600), spawn.get("y", 280)
                status_target = {
                    "id": enemy_id, "x": target_x, "y": target_y,
                    "width": ACTOR_SIZE, "height": ACTOR_SIZE,
                    "hitbox": {"offset_x": (ACTOR_SIZE - ACTOR_HITBOX_WIDTH) / 2,
                               "offset_y": (ACTOR_SIZE - ACTOR_HITBOX_HEIGHT) / 2,
                               "width": ACTOR_HITBOX_WIDTH,
                               "height": ACTOR_HITBOX_HEIGHT},
                    "data": definition,
                }
                break
        if status_target:
            source_data = status_actor["data"] if status_actor else vars(actor)
            source_x = status_actor["x"] if status_actor else actor.x
            source_y = status_actor["y"] if status_actor else actor.y
            readiness = _attack_readiness_text(
                source_data, source_x, source_y, status_target, current_arena)
            for line in _wrap_ui_lines(hud_font, readiness,
                                       screen.get_width() - 24):
                screen.blit(hud_font.render(line, True, (255, 230, 150)),
                            (12, hud_y))
                hud_y += hud_font.get_linesize() + 1
        enemy_entries = list((combat or {}).get("actors", {}).values())
        if not combat or combat.get("sync_only"):
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
            if avatar and avatar not in sprite_frames:
                try:
                    sprite_frames[avatar] = load_spritesheet(avatar)
                except (FileNotFoundError, pygame.error):
                    pass
            enemy_frames = sprite_frames.get(avatar, sprite_frames["asset_pack/Orc.png"])
            enemy_animation = enemy_animations.setdefault(
                enemy["id"], {"anim": "idle", "index": 0, "time": 0})
            requested = "dead" if enemy["downed"] else "idle"
            enemy_image = _advance_character_animation(
                enemy_animation, requested, enemy.get("animation_event"),
                dt, enemy_frames, frame_duration)
            if enemy.get("facing_left", False):
                enemy_image = pygame.transform.flip(enemy_image, True, False)
            enemy_image = pygame.transform.scale(enemy_image, rect.size)
            screen.blit(enemy_image, rect.topleft)
            title = _perceived_title(
                vars(actor), enemy.get("perception_info") or
                enemy.get("data", {}).get("perception", {}))
            if title:
                title_font = pygame.font.Font(None, 16)
                title_text = _fit_ui_text(
                    title_font, title, max(40, min(220, screen.get_width() - 16)))
                title_surface = title_font.render(title_text, True, (245, 245, 245))
                title_x = max(8, min(screen.get_width() - title_surface.get_width() - 8,
                                     rect.x - 10))
                screen.blit(title_surface, (title_x, max(4, rect.y - 18)))
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
        if feedback_target_id and pygame.time.get_ticks() < feedback_flash_until:
            feedback_entry = (combat or {}).get("actors", {}).get(feedback_target_id)
            feedback_position = None
            if feedback_entry:
                feedback_position = (feedback_entry["x"], feedback_entry["y"],
                                     feedback_entry.get("width", ACTOR_SIZE),
                                     feedback_entry.get("height", ACTOR_SIZE))
            elif feedback_target_id == player_id:
                feedback_position = (actor.x, actor.y, ACTOR_SIZE, ACTOR_SIZE)
            else:
                remote = next((item for item in remote_players
                               if _player_id(item) == feedback_target_id), None)
                if remote:
                    feedback_position = (remote.get("x", 0), remote.get("y", 0),
                                         ACTOR_SIZE, ACTOR_SIZE)
                else:
                    for index, spawn in enumerate(scenario.get("enemies", [])):
                        enemy_id = spawn.get("id", f"{spawn.get('npc')}-{index + 1}")
                        if enemy_id == feedback_target_id:
                            feedback_position = (spawn.get("x", 600),
                                                 spawn.get("y", 280),
                                                 ACTOR_SIZE, ACTOR_SIZE)
                            break
            if not feedback_position:
                feedback_position = (actor.x, actor.y, ACTOR_SIZE, ACTOR_SIZE)
            if feedback_position:
                fx, fy, fw, fh = feedback_position
                remaining = (feedback_flash_until - pygame.time.get_ticks()) / 700
                flash = pygame.Surface((76, 76), pygame.SRCALPHA)
                alpha = max(0, min(210, int(210 * remaining)))
                pygame.draw.circle(flash, (255, 45, 45, alpha // 3), (38, 38), 32)
                pygame.draw.circle(flash, (255, 55, 55, alpha), (38, 38), 32, 4)
                screen.blit(flash, (int(fx + fw / 2 - camera[0] - 38),
                                    int(fy + fh / 2 - camera[1] - 38)))
        if selected_target:
            target_entry = combat.get("actors", {}).get(selected_target) if combat else None
            target_name = None
            if not target_entry and not combat:
                for index, spawn in enumerate(scenario.get("enemies", [])):
                    enemy_id = spawn.get("id", f"{spawn.get('npc')}-{index + 1}")
                    if enemy_id == selected_target:
                        target_entry = {"x": spawn.get("x", 600), "y": spawn.get("y", 280),
                                        "width": ACTOR_SIZE, "height": ACTOR_SIZE,
                                        "data": NPCS.get(spawn.get("npc"), {})}
                        break
            if target_entry:
                target_center = (int(target_entry["x"] + target_entry.get("width", ACTOR_SIZE) / 2 - camera[0]),
                                 int(target_entry["y"] + target_entry.get("height", ACTOR_SIZE) / 2 - camera[1]))
                target_name = target_entry.get("data", {}).get("name")
            else:
                remote = next((p for p in remote_players if p.get("id") == selected_target), None)
                target_center = (int(remote.get("x", 0) + 50), int(remote.get("y", 0) + 50)) if remote else None
                if remote:
                    target_name = (remote.get("actor") or {}).get("name") or remote.get("name")
            if selected_target == player_id:
                target_name = actor.name
            target_name = target_name or str(selected_target)
            if target_center:
                flash_alpha = 255 if (pygame.time.get_ticks() // 220) % 2 == 0 else 90
                flash = pygame.Surface((68, 68), pygame.SRCALPHA)
                pygame.draw.circle(flash, (255, 255, 255, flash_alpha),
                                   (34, 34), 28, 3)
                screen.blit(flash, (target_center[0] - 34,
                                    target_center[1] - 34))
            target_panel = pygame.Rect(16, screen.get_height() - 106, 300, 34)
            pygame.draw.rect(screen, (15, 18, 24, 225), target_panel,
                             border_radius=5)
            pygame.draw.rect(screen, (235, 240, 248), target_panel, 1,
                             border_radius=5)
            target_label = pygame.font.Font(None, 19).render(
                f"Target: {target_name}  ·  Esc to clear", True,
                (255, 255, 255))
            screen.blit(target_label, (target_panel.x + 10,
                                       target_panel.y + 9))
        combat_log_rect = _draw_combat_ui(
            screen, font, combat, player_id, vars(actor), combat_log_scroll)
        if (combat and combat.get("result")
                and combat["result"].get("outcome") != "victory"):
            result = combat["result"]
            banner = pygame.Surface((560, 130), pygame.SRCALPHA)
            banner.fill((0, 0, 0, 205))
            screen.blit(banner, (120, 180))
            banner_lines = _wrap_ui_lines(font,
                                          result.get("message", "Encounter complete."),
                                          520)
            for line_index, line in enumerate(banner_lines[:2]):
                screen.blit(font.render(line, True, (255, 235, 160)),
                            (140, 195 + line_index * 24))
            prompt = "N: retry  |  M: return to menu" if is_host else "Waiting for host  |  M: return to menu"
            screen.blit(font.render(_fit_ui_text(font, prompt, 520), True,
                                    (240, 240, 240)), (140, 250))
        if pygame.time.get_ticks() < save_notice_until:
            notice = font.render("Character saved", True, (190, 245, 190))
            screen.blit(notice, (screen.get_width() - notice.get_width() - 12, 12))
        if pygame.time.get_ticks() < invite_notice_until:
            for line in _wrap_ui_lines(hud_font, invite_notice,
                                       screen.get_width() - 24):
                screen.blit(hud_font.render(line, True, (220, 240, 190)),
                            (12, hud_y))
                hud_y += hud_font.get_linesize() + 1
        if pygame.time.get_ticks() < action_notice_until:
            for line in _wrap_ui_lines(hud_font, action_notice,
                                       screen.get_width() - 24):
                screen.blit(hud_font.render(line, True, (255, 215, 150)),
                            (12, hud_y))
                hud_y += hud_font.get_linesize() + 1
        if interact_prompt:
            dialog = pygame.Surface((460, 132), pygame.SRCALPHA)
            dialog.fill((18, 20, 22, 235))
            pygame.draw.rect(dialog, (195, 190, 165), dialog.get_rect(), 2)
            dialog_x = (screen.get_width() - dialog.get_width()) // 2
            dialog_y = (screen.get_height() - dialog.get_height()) // 2
            screen.blit(dialog, (dialog_x, dialog_y))
            dialog_font = pygame.font.Font(None, 18)
            dialog_lines = _wrap_ui_lines(
                dialog_font,
                f"Rest at {interact_prompt['name']}? It costs 10 gold per character.",
                dialog.get_width() - 36)
            for line_index, line in enumerate(dialog_lines[:3]):
                screen.blit(dialog_font.render(line, True, (245, 235, 205)),
                            (dialog_x + 18, dialog_y + 18 + line_index * 20))
            screen.blit(dialog_font.render(
                "Y / Enter: pay and rest     N / Esc: cancel", True,
                (210, 220, 220)), (dialog_x + 18, dialog_y + 92))
        inventory_data = (combat.get("actors", {}).get(player_id, {}).get("data", {})
                          if combat else vars(actor))
        inventory_ui.draw(screen, inventory_data, font,
                          spellbook_ui.tooltips_enabled)
        inventory_data["quick_items"] = actor.quick_items
        spellbook_ui.draw(screen, font, vars(actor))
        trainer_ui.draw(screen, vars(actor), font)
        if loot_ui.visible:
            loot_corpse = ((combat or {}).get("actors", {}).get(loot_ui.corpse_id))
            if loot_corpse:
                loot_ui.draw(screen, loot_corpse, font)
            else:
                loot_ui.close()
        if actor.downed:
            death_box = pygame.Surface((520, 160), pygame.SRCALPHA)
            death_box.fill((18, 8, 10, 238))
            pygame.draw.rect(death_box, (205, 90, 78), death_box.get_rect(), 2)
            death_x = (screen.get_width() - death_box.get_width()) // 2
            death_y = (screen.get_height() - death_box.get_height()) // 2
            screen.blit(death_box, (death_x, death_y))
            death_lines = ["You are downed.",
                           "Wait here for another player to revive you, or press R to release your spirit.",
                           "Releasing returns you to the inn and costs 10% of your unspent XP.",
                           "M returns to the menu."]
            for index, line in enumerate(death_lines):
                screen.blit(font.render(_fit_ui_text(font, line, 490), True,
                                        (255, 225, 215)),
                            (death_x + 16, death_y + 16 + index * 30))
        if chat_mode:
            prompt = pygame.Surface((screen.get_width() - 48, 38), pygame.SRCALPHA)
            prompt.fill((10, 12, 16, 220))
            screen.blit(prompt, (24, screen.get_height() - 54))
            chat_line = _fit_ui_text(
                font, f"Chat: {chat_text}_", screen.get_width() - 72)
            screen.blit(font.render(chat_line, True, (245, 245, 235)),
                        (36, screen.get_height() - 45))
        if controls_visible:
            help_lines = [
                ("CONTROLS", None),
                ("During combat, WASD or click an open spot to move; your remaining feet are shown below.", None),
                ("Left Shift ends your turn and restores movement next turn.", None),
                ("Z: camp outdoors when more than 100 ft from enemies; costs unspent XP.", None),
                ("F: interact. At the trainer, open class purchases; at the inn bed, confirm a 10-gold rest.", None),
                ("F2: toggle tooltips    -: spells and abilities    `: switch bars", None),
                ("Enter: chat    /act <emote>: show an emote and add it to combat log", None),
                ("Click a character to select a target. Right-click a player for details.", None),
                ("1-0: use assigned action; empty 1 uses primary weapon. R: ranged    T: throw", None),
                ("WASD or click an open spot to move. Click an assigned bar slot or use its 1-0 hotkey.", None),
                ("Q / E: use bound consumables. In Inventory, select an item and click Q or E to bind it.", None),
                ("I: inventory    Left Shift: end your turn    F5: save character", None),
                ("M: return to menu    Esc: quit game    F1: close this panel", None),
                ("When downed, wait for a revival or press R to return to the inn for a 10% XP loss.", None),
                ("Hover action-bar or spellbook entries for details when tooltips are on:", None),
            ]
            panel_width = min(700, screen.get_width() - 32)
            help_font = pygame.font.Font(None, 18)
            display_help = []
            for index, (line, definition) in enumerate(help_lines):
                row_font = font if index == 0 else help_font
                color = (255, 230, 150) if index == 0 else (238, 240, 245)
                for wrapped in _wrap_ui_lines(row_font, line, panel_width - 32):
                    display_help.append((wrapped, color, row_font, definition))
            panel_height = 24 + len(display_help) * 21
            panel_x = (screen.get_width() - panel_width) // 2
            panel_y = max(12, min((screen.get_height() - panel_height) // 2,
                                  screen.get_height() - panel_height - 12))
            panel = pygame.Surface((panel_width, panel_height), pygame.SRCALPHA)
            panel.fill((18, 22, 28, 238))
            screen.blit(panel, (panel_x, panel_y))
            hovered_definition = None
            for index, (line, color, row_font, definition) in enumerate(display_help):
                rendered = row_font.render(line, True, color)
                line_x, line_y = panel_x + 16, panel_y + 12 + index * 21
                screen.blit(rendered, (line_x, line_y))
                if (spellbook_ui.tooltips_enabled and definition
                        and rendered.get_rect(topleft=(line_x, line_y)).collidepoint(pygame.mouse.get_pos())):
                    hovered_definition = definition
            if hovered_definition:
                title = hovered_definition.get("name", "Ability")
                details = [hovered_definition.get("description", "No description available.")]
                cost = hovered_definition.get("casting_time", hovered_definition.get("action_cost"))
                if cost:
                    details.append(f"Cost: {str(cost).replace('_', ' ')}")
                targeting = hovered_definition.get("targeting", {})
                if targeting.get("range_feet") is not None:
                    details.append(f"Range: {targeting['range_feet']} ft")
                tooltip_lines = [title]
                for detail in details:
                    words = detail.split()
                    wrapped = ""
                    for word in words:
                        candidate = f"{wrapped} {word}".strip()
                        if wrapped and font.size(candidate)[0] > 340:
                            tooltip_lines.append(wrapped)
                            wrapped = word
                        else:
                            wrapped = candidate
                    if wrapped:
                        tooltip_lines.append(wrapped)
                tooltip_width = min(372, max(font.size(line)[0] for line in tooltip_lines) + 24)
                tooltip_line_height = font.get_linesize() + 1
                tooltip_height = len(tooltip_lines) * tooltip_line_height + 16
                mouse_x, mouse_y = pygame.mouse.get_pos()
                tooltip_x = min(mouse_x + 14, screen.get_width() - tooltip_width - 8)
                tooltip_y = min(mouse_y + 14, screen.get_height() - tooltip_height - 8)
                tooltip = pygame.Surface((tooltip_width, tooltip_height), pygame.SRCALPHA)
                tooltip.fill((8, 10, 14, 245))
                screen.blit(tooltip, (tooltip_x, tooltip_y))
                for index, line in enumerate(tooltip_lines):
                    color = (255, 230, 150) if index == 0 else (245, 245, 245)
                    screen.blit(font.render(line, True, color),
                                (tooltip_x + 12,
                                 tooltip_y + 8 + index * tooltip_line_height))
        if quit_prompt:
            panel_width, panel_height = 310, 112
            panel_x = (screen.get_width() - panel_width) // 2
            panel_y = screen.get_height() - panel_height - 32
            quit_panel = pygame.Surface((panel_width, panel_height), pygame.SRCALPHA)
            quit_panel.fill((15, 18, 24, 242))
            pygame.draw.rect(quit_panel, (225, 230, 238),
                             quit_panel.get_rect(), 2, border_radius=6)
            screen.blit(quit_panel, (panel_x, panel_y))
            question = font.render("Quit the game?", True, (255, 245, 220))
            screen.blit(question, question.get_rect(
                center=(screen.get_width() // 2, panel_y + 30)))
            yes_rect = pygame.Rect(panel_x + 28, panel_y + 64, 112, 32)
            no_rect = pygame.Rect(panel_x + 170, panel_y + 64, 112, 32)
            for rect, label in ((yes_rect, "Yes, quit"), (no_rect, "No, stay")):
                pygame.draw.rect(screen, (76, 87, 102), rect, border_radius=4)
                pygame.draw.rect(screen, (180, 190, 205), rect, 1,
                                 border_radius=4)
                text = font.render(label, True, (255, 255, 255))
                screen.blit(text, text.get_rect(center=rect.center))
        pygame.display.flip()

    _sync_local_actor(actor, combat, player_id)
    save_actor(actor)
    pygame.quit()
    return "menu" if exit_to_menu else "quit"
