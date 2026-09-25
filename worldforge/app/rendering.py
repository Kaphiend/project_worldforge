"""Pygame character rendering, animation, and shared text helpers."""
import time
import math
import pygame

from worldforge.app.world import ACTOR_SIZE, _arena_obstacles

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


def _smooth_combat_positions(combat, positions, dt, *, reset=False):
    """Ease displayed combat actors between authoritative turn snapshots."""
    if reset or not combat or not combat.get("active"):
        positions.clear()
        return {}
    amount = 1 - math.exp(-max(0, dt) / 140)
    visible = {}
    for actor_id, entry in combat.get("actors", {}).items():
        target_x, target_y = float(entry.get("x", 0)), float(entry.get("y", 0))
        point = positions.get(actor_id)
        if point is None:
            point = positions[actor_id] = {"x": target_x, "y": target_y}
        else:
            point["x"] += (target_x - point["x"]) * amount
            point["y"] += (target_y - point["y"]) * amount
            if abs(target_x - point["x"]) < 0.25:
                point["x"] = target_x
            if abs(target_y - point["y"]) < 0.25:
                point["y"] = target_y
        visible[actor_id] = (point["x"], point["y"])
    for actor_id in positions.keys() - visible.keys():
        positions.pop(actor_id, None)
    return visible

def _draw_players(screen, actor, local_sprite, remote_players, remote_animations,
                  remote_positions, dt, sprite_frames, frame_duration, arena=None,
                  camera=(0, 0), local_speech=None, font=None,
                  local_draw_position=None):
    arena = arena or {}
    camera_x, camera_y = camera
    screen.fill(tuple(arena.get("edge_color", [34, 49, 40])))
    bounds_data = arena.get("bounds", {"x": 0, "y": 0, "width": 800, "height": 600})
    bounds = pygame.Rect(bounds_data["x"], bounds_data["y"],
                         bounds_data["width"], bounds_data["height"])
    screen.fill(tuple(arena.get("ground_color", [64, 91, 67])),
                bounds.move(-camera_x, -camera_y))
    for decoration in arena.get("decorations", []):
        kind = decoration.get("kind")
        rect = pygame.Rect(decoration["x"] - camera_x,
                           decoration["y"] - camera_y,
                           decoration["width"], decoration["height"])
        color = tuple(decoration.get("color", [80, 80, 80]))
        if kind == "rect":
            pygame.draw.rect(screen, color, rect)
        elif kind == "ellipse":
            pygame.draw.ellipse(screen, color, rect)
            if decoration.get("outline"):
                pygame.draw.ellipse(screen, tuple(decoration["outline"]),
                                    rect, max(1, int(decoration.get(
                                        "outline_width", 3))))
    service_rects = {(int(item["x"]), int(item["y"]), int(item["width"]),
                      int(item["height"]))
                     for group in ("trainers", "vendors")
                     for item in arena.get(group, [])}
    for obstacle in _arena_obstacles(arena):
        if (obstacle.x, obstacle.y, obstacle.width, obstacle.height) in service_rects:
            continue
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
            (f"{bed['owner_name']}'s Bed" if bed.get("owner_name")
             else bed.get("name", "Inn Bed")), True, (255, 255, 255)),
            (rect.x, rect.y - 18))
    for bed in arena.get("camp_beds", []):
        rect = pygame.Rect(bed["x"] - camera_x, bed["y"] - camera_y,
                           bed["width"], bed["height"])
        pygame.draw.rect(screen, (118, 91, 62), rect, border_radius=5)
        pygame.draw.rect(screen, (221, 195, 147), rect, 2, border_radius=5)
        label = (f"{bed['owner_name']}'s Bedroll" if bed.get("owner_name")
                 else bed.get("name", "Bedroll"))
        screen.blit(pygame.font.Font(None, 16).render(
            label, True, (245, 231, 202)),
            (rect.x - 3, rect.y - 16))
    for chest in arena.get("personal_chests", []):
        rect = pygame.Rect(chest["x"] - camera_x, chest["y"] - camera_y,
                           chest["width"], chest["height"])
        pygame.draw.rect(screen, (105, 68, 39), rect, border_radius=4)
        pygame.draw.rect(screen, (210, 171, 103), rect, 2, border_radius=4)
        if chest.get("owner_name"):
            screen.blit(pygame.font.Font(None, 14).render(
                f"{chest['owner_name']}'s Chest", True, (245, 226, 190)),
                (rect.x - 6, rect.y - 14))
    for exit_record in arena.get("exits", []):
        rect = pygame.Rect(exit_record["x"] - camera_x,
                           exit_record["y"] - camera_y,
                           exit_record["width"], exit_record["height"])
        pygame.draw.rect(screen, (48, 112, 135), rect, border_radius=5)
        pygame.draw.rect(screen, (134, 221, 230), rect, 3, border_radius=5)
        screen.blit(pygame.font.Font(None, 17).render(
            exit_record.get("name", "Exit"), True, (225, 248, 250)),
            (rect.x - 3, rect.y - 18))
    local_x, local_y = local_draw_position or (actor.x, actor.y)
    screen.blit(local_sprite, (round(local_x - camera_x), round(local_y - camera_y)))
    font = font or pygame.font.Font(None, 18)
    _draw_speech_bubble(screen, font, local_speech, local_x, local_y,
                        ACTOR_SIZE, camera_x, camera_y)
    drawn_positions = {}
    for remote in remote_players:
        player_id = _player_id(remote)
        x, y = _smooth_remote_position(remote, remote_positions, dt)
        screen_x, screen_y = x - camera_x, y - camera_y
        drawn_positions[player_id] = (screen_x, screen_y)
        animation = remote_animations.setdefault(
            player_id, {"anim": "idle", "index": 0, "time": 0})
        remote_frames = sprite_frames.get(
            "asset_pack/Soldier.png", next(iter(sprite_frames.values())))
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
