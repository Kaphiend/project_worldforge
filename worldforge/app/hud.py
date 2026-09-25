"""HUD and scene-level drawing for the active game frame."""
import math
import pygame
from worldforge.content.classes import NPCS, SCENARIOS
from worldforge.ui.sprite_sheet import load_spritesheet
from worldforge.actors.factory import effective_max_hp
from worldforge.core.progression import (spell_slot_summary, total_earned_xp,
                                         XP_THRESHOLDS, levels_to_apply)
from worldforge.app.combat_flow import _active_actor_id
from worldforge.app.encounters import DEFAULT_SCENARIO
from worldforge.app.world import ACTOR_HITBOX_HEIGHT, ACTOR_HITBOX_WIDTH, ACTOR_SIZE, _attack_readiness_text, _perceived_title
from worldforge.app.rendering import _advance_character_animation, _fit_ui_text, _player_id, _wrap_ui_lines
from worldforge.content.campaign import ACTIVE_CAMPAIGN, campaign_rule
from worldforge.ui.prompt_dialog import interaction_prompt_rects
from worldforge.combat.resting import inn_rest_gold_cost

def _draw_combat_ui(screen, font, combat, actor_id, observer_data, log_scroll=0,
                    verbose=False):
    if not combat:
        return pygame.Rect(0, 0, 0, 0)
    if verbose:
        panel_width = min(820, screen.get_width() - 32)
        panel_height = min(620, screen.get_height() - 32)
        panel_x = (screen.get_width() - panel_width) // 2
        panel_y = (screen.get_height() - panel_height) // 2
    else:
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
        f"Slots {spell_slot_summary(own_data)}")
    small_font = pygame.font.Font(None, 14)
    screen.blit(small_font.render(_fit_ui_text(
        small_font, resource_line, panel_width - 20), True, (210, 230, 255)),
                (panel_x + 10, panel_y + 30))
    log_lines = (combat.get("verbose_log", combat.get("log", []))
                 if verbose else combat.get("log", []))
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
    max_rows = max(5, (panel_height - 62) // 17) if verbose else 5
    end = max(0, len(wrapped_lines) - max(0, int(log_scroll)))
    visible = wrapped_lines[max(0, end - max_rows):end]
    for index, message in enumerate(visible):
        screen.blit(small_font.render(message, True, (245, 245, 245)),
                    (panel_x + 10, panel_y + 52 + index * 17))
    if verbose:
        label = pygame.font.Font(None, 17).render(
            "VERBOSE COMBAT LOG · F9 / Esc closes · Mouse wheel scrolls",
            True, (255, 220, 145))
        screen.blit(label, (panel_x + 10, panel_y + panel_height - 22))
    return panel_rect

def draw_game_frame(context):
    action_notice = context["action_notice"]
    action_notice_until = context["action_notice_until"]
    actor = context["actor"]
    arrow_sprite = context["arrow_sprite"]
    camera = context["camera"]
    chat_mode = context["chat_mode"]
    chat_text = context["chat_text"]
    combat = context["combat"]
    combat_log_scroll = context["combat_log_scroll"]
    verbose_combat_log = context.get("verbose_combat_log", False)
    controls_visible = context["controls_visible"]
    combat_positions = context.get("combat_positions", {})
    current_arena = context["current_arena"]
    drawn_positions = context["drawn_positions"]
    dt = context["dt"]
    enemy_animations = context["enemy_animations"]
    feedback_flash_until = context["feedback_flash_until"]
    feedback_target_id = context["feedback_target_id"]
    font = context["font"]
    frame_duration = context["frame_duration"]
    interact_prompt = context["interact_prompt"]
    inventory_ui = context["inventory_ui"]
    invite_address = context["invite_address"]
    invite_notice = context["invite_notice"]
    invite_notice_until = context["invite_notice_until"]
    is_host = context["is_host"]
    loot_ui = context["loot_ui"]
    multiplayer = context["multiplayer"]
    party_status = context["party_status"]
    player_id = context["player_id"]
    projectile_runtime = context["projectile_runtime"]
    remote_players = context["remote_players"]
    save_notice_until = context["save_notice_until"]
    screen = context["screen"]
    selected_target = context["selected_target"]
    spellbook_ui = context["spellbook_ui"]
    sprite_frames = context["sprite_frames"]
    trainer_ui = context["trainer_ui"]
    vendor_ui = context.get("vendor_ui")
    storage_ui = context.get("storage_ui")
    vendor_buyback = context.get("vendor_buyback", []) or []

    screen_spell_data = (combat.get("actors", {}).get(player_id, {}).get("data", {})
                         if combat and combat.get("active") else vars(actor))
    scenario = ((combat or {}).get("scenario")
                or SCENARIOS.get(DEFAULT_SCENARIO, {}))
    hud_font = pygame.font.Font(None, 18)
    hud_rows = [(scenario.get("name", "Worldforge"), (245, 245, 230), font)]
    if scenario.get("objective"):
        hud_rows.append((scenario["objective"], (230, 230, 205), hud_font))
    rest_session = (combat or {}).get("rest_session")
    if rest_session:
        ready_count = len(rest_session.get("ready", []))
        party_count = len(rest_session.get("participants", []))
        if rest_session.get("location") == "outdoor":
            bed_id = rest_session.get("bed_by_actor", {}).get(player_id)
            bed = next((item for item in current_arena.get("camp_beds", [])
                        if item.get("id") == bed_id), {})
            cost = rest_session.get("costs", {}).get(player_id, 0)
            bed_label = (f"{bed['owner_name']}'s bedroll"
                         if bed.get("owner_name") else
                         bed.get("name", "assigned bed"))
            text = (f"Safe camp · {bed_label} · "
                    f"your cost {cost} XP · {ready_count}/{party_count} checked in · "
                    "use your bed to rest, or F at Return to Map to leave")
        else:
            paid_count = len(rest_session.get("paid", {}))
            bed_id = rest_session.get("bed_by_actor", {}).get(player_id)
            bed = next((item for item in current_arena.get("inn_beds", [])
                        if item.get("id") == bed_id), {})
            assignment = (f"{bed.get('name')} assigned · " if bed else "")
            text = (f"Inn check-in · {assignment}{paid_count}/{party_count} paid · "
                    f"{ready_count}/{party_count} checked in · pay the innkeeper, then use your bed")
        hud_rows.append((text, (255, 220, 150), hud_font))
    if multiplayer:
        count = party_status() if party_status else 1 + len(remote_players)
        hud_rows.append((f"Party: {count}/{ACTIVE_CAMPAIGN['party_limit']}",
                         (195, 220, 195), hud_font))
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
    hud_rows.append((f"Spell slots: {spell_slot_summary(screen_spell_data)}",
                     (210, 225, 255), hud_font))
    hud_y = 12
    for text, color, row_font in hud_rows:
        for line in _wrap_ui_lines(row_font, text, screen.get_width() - 24):
            screen.blit(row_font.render(line, True, color), (12, hud_y))
            hud_y += row_font.get_linesize() + 1
    # A compact top-right XP meter stays visible in exploration and combat.
    level = max(1, int(screen_spell_data.get("level", 1) or 1))
    xp = total_earned_xp(screen_spell_data)
    threshold = XP_THRESHOLDS[level] if level < len(XP_THRESHOLDS) else None
    meter_width, meter_height = min(270, max(190, screen.get_width() // 4)), 38
    meter_x, meter_y = screen.get_width() - meter_width - 12, hud_y + 3
    meter = pygame.Rect(meter_x, meter_y, meter_width, meter_height)
    pygame.draw.rect(screen, (12, 16, 23), meter, border_radius=5)
    pygame.draw.rect(screen, (100, 117, 143), meter, 1, border_radius=5)
    pending_levels = levels_to_apply(screen_spell_data)
    if pending_levels:
        progress = 1.0
        xp_label = f"Level {level + pending_levels} ready · visit trainer"
    elif threshold is not None:
        previous = XP_THRESHOLDS[level - 1]
        progress = max(0.0, min(1.0, (xp - previous) / max(1, threshold - previous)))
        xp_label = f"Level {level}  ·  {xp:,} / {threshold:,} XP"
    else:
        progress, xp_label = 1.0, f"Level {level}  ·  MAX LEVEL"
    label_font = pygame.font.Font(None, 17)
    screen.blit(label_font.render(_fit_ui_text(label_font, xp_label, meter_width - 16),
                                  True, (238, 240, 246)), (meter_x + 8, meter_y + 5))
    track = pygame.Rect(meter_x + 8, meter_y + 25, meter_width - 16, 7)
    pygame.draw.rect(screen, (45, 51, 62), track, border_radius=3)
    fill = pygame.Rect(track.x, track.y, round(track.width * progress), track.height)
    if fill.width:
        pygame.draw.rect(screen, (220, 174, 77), fill, border_radius=3)
    hud_y = meter.bottom + 5
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
        enemy_x, enemy_y = combat_positions.get(
            enemy.get("id"), (enemy["x"], enemy["y"]))
        rect = pygame.Rect(enemy_x - camera[0], enemy_y - camera[1],
                           enemy.get("width", 40), enemy.get("height", 40))
        avatar = enemy.get("data", {}).get("avatar")
        if avatar and avatar not in sprite_frames:
            try:
                sprite_frames[avatar] = load_spritesheet(avatar)
            except (FileNotFoundError, pygame.error):
                pass
        enemy_frames = sprite_frames.get(avatar, sprite_frames["asset_pack/Goblin.png"])
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
    for innkeeper in current_arena.get("innkeepers", []):
        frames = sprite_frames.get(innkeeper.get("avatar"), sprite_frames.get(
            "asset_pack/Cleric.png", {}))
        if isinstance(frames, dict) and frames.get("idle"):
            size = (int(innkeeper.get("width", 100)),
                    int(innkeeper.get("height", 100)))
            state = enemy_animations.setdefault(
                f"innkeeper:{innkeeper.get('id')}",
                {"anim": "idle", "index": 0, "time": 0})
            frame = _advance_character_animation(
                state, "idle", None, dt, frames, frame_duration)
            image = pygame.transform.scale(frame, size)
            x, y = int(innkeeper.get("x", 0) - camera[0]), int(innkeeper.get("y", 0) - camera[1])
            screen.blit(image, (x, y))
            screen.blit(pygame.font.Font(None, 18).render(
                innkeeper.get("name", "Innkeeper"), True, (255, 245, 220)),
                (x - 2, y - 18))
    for group in ("trainers", "vendors"):
        for npc in current_arena.get(group, []):
            frames = sprite_frames.get(npc.get("avatar"), {})
            if not frames.get("idle"):
                continue
            size = (int(npc.get("width", 100)), int(npc.get("height", 100)))
            state = enemy_animations.setdefault(
                f"service_npc:{npc.get('id')}",
                {"anim": "idle", "index": 0, "time": 0})
            frame = _advance_character_animation(
                state, "idle", None, dt, frames, frame_duration)
            image = pygame.transform.scale(frame, size)
            x, y = int(npc.get("x", 0) - camera[0]), int(npc.get("y", 0) - camera[1])
            screen.blit(image, (x, y))
            screen.blit(pygame.font.Font(None, 18).render(
                npc.get("name", "NPC"), True, (255, 245, 220)),
                (x - 2, y - 18))
    for chest in (combat or {}).get("chests", current_arena.get("chests", [])):
        width, height = int(chest.get("width", 54)), int(chest.get("height", 38))
        rect = pygame.Rect(chest.get("x", 0) - camera[0],
                           chest.get("y", 0) - camera[1], width, height)
        body_color = (91, 68, 42) if not chest.get("opened") else (65, 59, 49)
        pygame.draw.rect(screen, body_color, rect, border_radius=3)
        pygame.draw.rect(screen, (218, 177, 91), rect, 2, border_radius=3)
        pygame.draw.line(screen, (218, 177, 91),
                         (rect.left + 2, rect.centery),
                         (rect.right - 2, rect.centery), 2)
        pygame.draw.rect(screen, (218, 177, 91),
                         pygame.Rect(rect.centerx - 3, rect.centery - 3, 6, 7))
    if combat and not combat.get("rest_session"):
        for ground_item in combat.get("ground_items", []):
            x, y = ground_item.get("x", 0), ground_item.get("y", 0)
            width = int(ground_item.get("width", 24))
            height = int(ground_item.get("height", 24))
            center = (round(x + width / 2 - camera[0]),
                      round(y + height / 2 - camera[1]))
            pygame.draw.circle(screen, (235, 196, 96), center, 14, 2)
            dropped_item_sprite = pygame.transform.rotate(arrow_sprite, 45)
            dropped_item_sprite = pygame.transform.smoothscale(
                dropped_item_sprite, (width + 12, height + 12))
            screen.blit(dropped_item_sprite,
                        dropped_item_sprite.get_rect(center=center))
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
            target_x, target_y = combat_positions.get(
                selected_target, (target_entry["x"], target_entry["y"]))
            target_width = target_entry.get("width", ACTOR_SIZE)
            target_height = target_entry.get("height", ACTOR_SIZE)
            target_rect = pygame.Rect(round(target_x - camera[0]),
                                      round(target_y - camera[1]),
                                      target_width, target_height)
            target_center = target_rect.center
            target_name = target_entry.get("data", {}).get("name")
        else:
            remote = next((p for p in remote_players if p.get("id") == selected_target), None)
            remote_position = (drawn_positions.get(selected_target)
                               if remote else None)
            target_center = ((int(remote_position[0] + ACTOR_SIZE / 2),
                              int(remote_position[1] + ACTOR_SIZE / 2))
                             if remote_position else
                             (int(remote.get("x", 0) + ACTOR_SIZE / 2 - camera[0]),
                              int(remote.get("y", 0) + ACTOR_SIZE / 2 - camera[1]))
                             if remote else None)
            target_rect = (pygame.Rect(
                round(remote_position[0]), round(remote_position[1]),
                ACTOR_SIZE, ACTOR_SIZE) if remote_position else
                pygame.Rect(int(remote.get("x", 0) - camera[0]),
                            int(remote.get("y", 0) - camera[1]),
                            ACTOR_SIZE, ACTOR_SIZE) if remote else None)
            if remote:
                target_name = (remote.get("actor") or {}).get("name") or remote.get("name")
        if selected_target == player_id:
            target_name = actor.name
        target_name = target_name or str(selected_target)
        if target_center:
            pulse = (math.sin(pygame.time.get_ticks() * math.tau / 1700) + 1) / 2
            flash_alpha = round(20 + pulse * 28)
            flash = pygame.Surface(target_rect.size, pygame.SRCALPHA)
            flash.fill((255, 183, 52, flash_alpha))
            pygame.draw.rect(flash, (255, 230, 154, 90 + round(pulse * 90)),
                             flash.get_rect(), 3, border_radius=12)
            screen.blit(flash, target_rect.topleft)
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
        screen, font, combat, player_id, vars(actor), combat_log_scroll,
        verbose_combat_log)
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
        panel_rect, yes_rect, no_rect = interaction_prompt_rects(screen.get_size())
        dialog = pygame.Surface(panel_rect.size, pygame.SRCALPHA)
        dialog.fill((18, 20, 22, 235))
        pygame.draw.rect(dialog, (195, 190, 165), dialog.get_rect(), 2)
        dialog_x, dialog_y = panel_rect.topleft
        screen.blit(dialog, panel_rect.topleft)
        dialog_font = pygame.font.Font(None, 18)
        if interact_prompt.get("type") == "area_exit":
            prompt_text = (f"Travel through {interact_prompt['name']}? "
                           "The connected party travels together.")
            confirm_text = "Y / Enter: travel     N / Esc: cancel"
        elif interact_prompt.get("type") == "camp_exit":
            prompt_text = "Leave the safe camp and return to the map without resting?"
            confirm_text = "Y / Enter: leave camp     N / Esc: cancel"
        elif interact_prompt.get("type") == "innkeeper":
            price_text = f"{inn_rest_gold_cost('long_rest')} gold"
            prompt_text = (f"Book a bed for a long rest ({price_text}). "
                           "Your party can check in together.")
            confirm_text = "Y / Enter: book a bed     N / Esc: cancel"
        elif interact_prompt.get("type") == "inn_bed":
            prompt_text = f"Check in at {interact_prompt['name']} after paying the innkeeper."
            confirm_text = "Y / Enter: check in     N / Esc: cancel"
        else:
            price_text = f"{inn_rest_gold_cost('long_rest')} gold"
            prompt_text = (f"Stay at {interact_prompt['name']}? Each party member "
                           f"must check in and pay {price_text} for a long rest.")
            confirm_text = "Y / Enter: check in     N / Esc: cancel"
        dialog_lines = _wrap_ui_lines(
            dialog_font, prompt_text, dialog.get_width() - 36)
        for line_index, line in enumerate(dialog_lines[:3]):
            screen.blit(dialog_font.render(line, True, (245, 235, 205)),
                        (dialog_x + 18, dialog_y + 18 + line_index * 20))
        for label, rect in (("Yes", yes_rect), ("No", no_rect)):
            pygame.draw.rect(screen, (73, 119, 78) if label == "Yes"
                             else (76, 78, 82), rect, border_radius=4)
            rendered = dialog_font.render(label, True, (250, 250, 245))
            screen.blit(rendered, rendered.get_rect(center=rect.center))
        screen.blit(dialog_font.render(confirm_text, True, (210, 220, 220)),
                    (dialog_x + 18, dialog_y + 92))
    inventory_data = (combat.get("actors", {}).get(player_id, {}).get("data", {})
                      if combat else vars(actor))
    inventory_ui.draw(screen, inventory_data, font,
                      spellbook_ui.tooltips_enabled)
    inventory_data["quick_items"] = actor.quick_items
    spellbook_ui.draw(screen, font, vars(actor))
    trainer_ui.draw(screen, vars(actor), font)
    if loot_ui.visible:
        loot_container = ((combat or {}).get("actors", {}).get(
            loot_ui.corpse_id) or next((item for item in
                (combat or {}).get("chests", [])
                if item.get("id") == loot_ui.corpse_id), None))
        if loot_container:
            loot_ui.draw(screen, loot_container, font)
        else:
            loot_ui.close()
    if vendor_ui and vendor_ui.visible:
        vendor = next((item for item in current_arena.get("vendors", [])
                       if item.get("id") == vendor_ui.vendor_id), None)
        vendor_data = ((combat or {}).get("actors", {}).get(player_id, {})
                       .get("data", vars(actor)))
        vendor_ui.draw(screen, font, vendor, vendor_data, vendor_buyback)
    if storage_ui and storage_ui.visible:
        title = "Personal Chest"
        chest = next((item for item in current_arena.get("personal_chests", [])
                      if item.get("id") == storage_ui.chest_id), None)
        if chest:
            title = chest.get("name", title)
        storage_ui.draw(screen, inventory_data, title)
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
            ("Tab ends your turn and restores movement next turn.", None),
            ("Z: travel to a safe camp beyond 100 ft from enemies; each party member pays XP and checks in at their bed.", None),
            ("F: use a nearby trainer, vendor, bed, corpse, dropped item, or area exit.", None),
            ("F2: toggle tooltips    -: spells and abilities    `: cycle hotbars", None),
            ("Spell and ability choices open above their hotbar slot; choose by number, then Y / Enter to confirm or Esc to cancel.", None),
            ("Enter: chat    /act <emote>: show an emote and add it to combat log", None),
            ("F9: open the large verbose combat log with roll math", None),
            ("Click a character to target it. Right-click a character or mob to inspect its debug data.", None),
            ("1-0: use assigned action; empty 1 uses primary weapon. R: ranged    T: throw", None),
            ("G: Thief Fast Hands Sleight of Hand check during combat.", None),
            ("WASD or click an open spot to move. Click an assigned bar slot or use its 1-0 hotkey.", None),
            ("K toggles slower sneaking outside combat. Hide needs cover and a DC 15 Stealth check.", None),
            ("Q / E: use bound consumables. In Inventory, select an item and click Q or E to bind it.", None),
            ("I: inventory    Tab: end your turn    F5: save character", None),
            ("F11: toggle fullscreen and windowed mode", None),
            ("M: return to menu    Esc: pause menu    F1: close this panel", None),
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
