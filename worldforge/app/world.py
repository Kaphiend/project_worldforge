"""Arena geometry, movement bounds, and perception helpers."""
import math

import pygame

from worldforge.actors.factory import item_definition, modifier
from worldforge.combat.rules import (edge_distance_feet, proficiency_bonus,
                                     resolve_skill_check,
                                     selected_weapon, speed_feet)
from worldforge.combat.species import species_traits

def _arena_bounds(arena):
    data = (arena or {}).get("bounds", {"x": 0, "y": 0, "width": 800, "height": 600})
    return pygame.Rect(data["x"], data["y"], data["width"], data["height"])

def _arena_obstacles(arena):
    arena = arena or {}
    obstacles = list(arena.get("obstacles", []))
    obstacles.extend(arena.get("inn_beds", []))
    obstacles.extend(arena.get("trainers", []))
    obstacles.extend(arena.get("vendors", []))
    obstacles.extend(arena.get("camp_beds", []))
    obstacles.extend(arena.get("chests", []))
    obstacles.extend(arena.get("personal_chests", []))
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

def _move_actor(actor, keys, speed, facing_left, arena, occupied=(),
                movement_keys=None):
    movement_keys = movement_keys or {}
    dx = int(bool(keys[pygame.K_RIGHT] or keys[movement_keys.get("right", pygame.K_d)])) - int(
        bool(keys[pygame.K_LEFT] or keys[movement_keys.get("left", pygame.K_a)]))
    dy = int(bool(keys[pygame.K_DOWN] or keys[movement_keys.get("down", pygame.K_s)])) - int(
        bool(keys[pygame.K_UP] or keys[movement_keys.get("up", pygame.K_w)]))
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
    return _camera_offset_position(actor.x, actor.y, arena, viewport)

def _camera_offset_position(x, y, arena, viewport=(1024, 768)):
    bounds = _arena_bounds(arena)
    width, height = viewport
    max_x = max(bounds.left, bounds.right - width)
    max_y = max(bounds.top, bounds.bottom - height)
    camera_x = x + ACTOR_SIZE / 2 - width / 2
    camera_y = y + ACTOR_SIZE / 2 - height / 2
    return (round(max(bounds.left, min(max_x, camera_x))),
            round(max(bounds.top, min(max_y, camera_y))))

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

PIXELS_PER_FOOT = 4

SCREEN_SIZE = (1280, 800)

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
    skills = {str(skill).casefold() for skill in actor_data.get("skills", []) or []}
    if "keen_senses" in species_traits(actor_data):
        skills.add("perception")
    if "perception" in skills:
        score += proficiency_bonus(actor_data)
    return score


def _stealth_check(actor_data):
    """Roll Dexterity (Stealth) using the actor's trained skill bonus."""
    return resolve_skill_check(actor_data, "stealth", "dexterity")


def _hidden_from(observer_entry, target_entry, arena):
    """Whether an observer has found a hidden target by sight or Perception."""
    hidden = target_entry.get("data", {}).get("hidden")
    if not isinstance(hidden, dict):
        return False
    if observer_entry.get("id") in hidden.get("detected_by", []):
        return False
    if not _line_of_sight(observer_entry, target_entry, arena):
        return True
    if _perception_score(observer_entry.get("data", {})) < int(
            hidden.get("stealth_total", 0)):
        return True
    detected_by = hidden.setdefault("detected_by", [])
    observer_id = observer_entry.get("id")
    if observer_id is not None and observer_id not in detected_by:
        detected_by.append(observer_id)
    return False

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
    base_speed = speed_feet(actor_data)
    from worldforge.combat.conditions import has_condition
    if has_condition(actor_data, "prone"):
        base_speed = int(base_speed / 2)
    bonus = 0
    for effect in actor_data.get("active_effects", []) or []:
        if effect.get("kind") != "movement_bonus":
            continue
        bonus += int(effect.get("feet", 0) or 0)
        multiplier = max(1.0, float(effect.get("multiplier", 1) or 1))
        bonus += int(base_speed * (multiplier - 1))
    return base_speed + bonus
