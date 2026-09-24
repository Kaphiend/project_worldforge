"""Interactive Pygame frame loop and session-level drawing."""
import math
import sys
import time
from pprint import pprint
from copy import deepcopy
import pygame
from worldforge.combat.rules import edge_distance_feet
from worldforge.content.classes import ARENAS, SCENARIOS
from worldforge.ui.sprite_sheet import load_spritesheet
from worldforge.core.storage import save_actor
from worldforge.actors.factory import equip_item, unequip_item
from worldforge.core.runtime_paths import asset_path
from worldforge.app.hud import draw_game_frame
from worldforge.app.requests import _add_joined_players, _handle_action_request, _remove_disconnected_players, _settle_victory
from worldforge.app.actions import _active_actor_id, _log, _process_turn_start, _run_ai_turns, _use_item_outside_combat
from worldforge.app.encounters import COMBAT_TRIGGER_RANGE_FEET, DEFAULT_SCENARIO, _combat_snapshot, _combat_trigger, _new_combat, _world_mob_from_entry
from worldforge.app.world import ACTOR_SIZE, PIXELS_PER_FOOT, SCREEN_SIZE, _actor_hitbox, _camera_offset, _move_actor, _target_clickbox, _walk_destination
from worldforge.app.rendering import _advance_character_animation, _draw_players, _player_id

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
    from worldforge.ui.inventory import InventoryScreen
    from worldforge.ui.spellbook import SpellbookUI, normalize_action_hotbars, action_definition
    from worldforge.ui.trainer import TrainerUI
    from worldforge.ui.loot import LootUI
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
        draw_game_frame({
            "action_notice": action_notice,
            "action_notice_until": action_notice_until,
            "actor": actor,
            "arrow_sprite": arrow_sprite,
            "camera": camera,
            "chat_mode": chat_mode,
            "chat_text": chat_text,
            "combat": combat,
            "combat_log_scroll": combat_log_scroll,
            "controls_visible": controls_visible,
            "current_arena": current_arena,
            "drawn_positions": drawn_positions,
            "dt": dt,
            "enemy_animations": enemy_animations,
            "feedback_flash_until": feedback_flash_until,
            "feedback_target_id": feedback_target_id,
            "font": font,
            "frame_duration": frame_duration,
            "interact_prompt": interact_prompt,
            "inventory_ui": inventory_ui,
            "invite_address": invite_address,
            "invite_notice": invite_notice,
            "invite_notice_until": invite_notice_until,
            "is_host": is_host,
            "loot_ui": loot_ui,
            "multiplayer": multiplayer,
            "party_status": party_status,
            "player_id": player_id,
            "projectile_runtime": projectile_runtime,
            "quit_prompt": quit_prompt,
            "remote_players": remote_players,
            "save_notice_until": save_notice_until,
            "screen": screen,
            "selected_target": selected_target,
            "spellbook_ui": spellbook_ui,
            "sprite_frames": sprite_frames,
            "trainer_ui": trainer_ui,
        })
        pygame.display.flip()

    _sync_local_actor(actor, combat, player_id)
    save_actor(actor)
    pygame.quit()
    return "menu" if exit_to_menu else "quit"
