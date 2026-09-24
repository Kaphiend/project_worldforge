"""HUD and scene-level drawing for the active game frame."""
import math
import pygame
from worldforge.content.classes import NPCS, SCENARIOS
from worldforge.ui.sprite_sheet import load_spritesheet
from worldforge.actors.factory import effective_max_hp
from worldforge.core.progression import spell_point_max
from worldforge.app.actions import _active_actor_id
from worldforge.app.encounters import DEFAULT_SCENARIO
from worldforge.app.world import ACTOR_HITBOX_HEIGHT, ACTOR_HITBOX_WIDTH, ACTOR_SIZE, _attack_readiness_text, _perceived_title
from worldforge.app.rendering import _advance_character_animation, _fit_ui_text, _player_id, _wrap_ui_lines

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
    controls_visible = context["controls_visible"]
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
    quit_prompt = context["quit_prompt"]
    remote_players = context["remote_players"]
    save_notice_until = context["save_notice_until"]
    screen = context["screen"]
    selected_target = context["selected_target"]
    spellbook_ui = context["spellbook_ui"]
    sprite_frames = context["sprite_frames"]
    trainer_ui = context["trainer_ui"]

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
