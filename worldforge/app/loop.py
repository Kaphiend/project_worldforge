"""Interactive Pygame frame loop and session-level drawing."""
import math
from copy import deepcopy
import pygame
from worldforge.content.classes import ARENAS, SCENARIOS, MOB_GENERATION_RULES
from worldforge.ui.sprite_sheet import load_spritesheet
from worldforge.core.storage import save_actor
from worldforge.actors.factory import equip_item, unequip_item
from worldforge.core.runtime_paths import asset_path
from worldforge.app.hud import draw_game_frame
from worldforge.app.actor_sync import _sync_local_actor
from worldforge.app.requests import _handle_action_request
from worldforge.app.combat_flow import _active_actor_id
from worldforge.app.item_actions import _use_item_outside_combat
from worldforge.app.encounters import (DEFAULT_SCENARIO, _new_combat,
                                      _new_world_state)
from worldforge.app.world import (ACTOR_SIZE, SCREEN_SIZE, _actor_hitbox,
                                  _camera_offset, _camera_offset_position,
                                  _move_actor, _walk_destination)
from worldforge.app.world import _stealth_check
from worldforge.app.rendering import (_advance_character_animation,
                                      _draw_players, _player_id,
                                      _smooth_combat_positions)
from worldforge.app.interaction_input import (actor_at_world_position,
                                              interact_nearby,
                                              target_at_screen_position)
from worldforge.app.hotbar_input import dispatch_hotbar_action
from worldforge.app.chat_input import handle_chat_event
from worldforge.app.host_tick import advance_host_world

def _copy_invite(text):
    try:
        pygame.scrap.init()
        pygame.scrap.put(pygame.SCRAP_TEXT, text.encode('utf-8') + b'\0')
        return True
    except (AttributeError, pygame.error):
        return False


def _draw_sword_cursor(screen):
    """Draw a small pixel-style sword with its tip at the mouse hotspot."""
    cursor = pygame.Surface((28, 32), pygame.SRCALPHA)
    # Blade points up-left; the dark outline keeps it visible over the world
    # while the pale center reads clearly over the dark UI panels.
    pygame.draw.polygon(cursor, (27, 31, 40),
                        ((2, 2), (9, 7), (16, 15), (13, 19), (7, 12)))
    pygame.draw.polygon(cursor, (191, 211, 222),
                        ((3, 3), (9, 8), (14, 15), (12, 16), (8, 11)))
    pygame.draw.line(cursor, (245, 250, 246), (4, 4), (11, 13), 1)
    # Crossguard, grip, and pommel.
    pygame.draw.line(cursor, (33, 29, 34), (10, 15), (18, 9), 4)
    pygame.draw.line(cursor, (214, 167, 83), (10, 15), (17, 10), 2)
    pygame.draw.line(cursor, (39, 30, 30), (14, 17), (23, 26), 5)
    pygame.draw.line(cursor, (130, 75, 47), (15, 18), (22, 25), 3)
    pygame.draw.circle(cursor, (39, 30, 30), (24, 27), 3)
    pygame.draw.circle(cursor, (214, 167, 83), (24, 27), 1)
    mouse_x, mouse_y = pygame.mouse.get_pos()
    screen.blit(cursor, (mouse_x - 2, mouse_y - 2))

def run_game(actor, get_other_players, send_state, multiplayer=True, combat_transport=None,
             party_status=None, invite_address=None):
    if not getattr(actor, "avatar", None):
        actor.avatar = 'asset_pack/Soldier.png'
    pygame.init()
    windowed_size = SCREEN_SIZE
    fullscreen = True
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    pygame.mouse.set_visible(False)
    clock = pygame.time.Clock()
    running = True
    speed = 5
    sprite_paths = dict.fromkeys((
        actor.avatar, 'asset_pack/Orc.png', 'asset_pack/Soldier.png',
        'asset_pack/Barbarian.png', 'asset_pack/Bard.png',
        'asset_pack/Cleric.png', 'asset_pack/Druid.png',
        'asset_pack/Fighter.png', 'asset_pack/Monk.png',
        'asset_pack/Paladin.png', 'asset_pack/Ranger.png',
        'asset_pack/Rogue.png', 'asset_pack/Sorcerer.png',
        'asset_pack/Warlock.png', 'asset_pack/Wizard.png',
        'asset_pack/Goblin.png',
    ))
    sprite_frames = {path: load_spritesheet(path) for path in sprite_paths}
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
    combat_render_positions = {}
    render_scenario_id = None
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
    combat = (_new_world_state(actor, player_id, get_other_players())
              if is_host else combat_transport["get"]())
    last_area_scenario_id = (combat or {}).get("scenario_id")
    vendor_state = {"buyback": {}}
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
    from worldforge.ui.inventory import InventoryScreen
    from worldforge.ui.spellbook import SpellbookUI, normalize_action_hotbars
    from worldforge.ui.trainer import TrainerUI
    from worldforge.ui.loot import LootUI
    from worldforge.ui.personal_storage import PersonalStorageUI
    from worldforge.ui.vendor import VendorUI
    from worldforge.ui.character_sheet import CharacterSheetUI
    from worldforge.ui.keybindings import KeyBindings
    from worldforge.ui.pause_menu import PauseMenuUI, open_overlay, pop_overlay
    inventory_ui = InventoryScreen()
    spellbook_ui = SpellbookUI()
    trainer_ui = TrainerUI()
    loot_ui = LootUI()
    storage_ui = PersonalStorageUI()
    vendor_ui = VendorUI()
    character_sheet_ui = CharacterSheetUI()
    pause_menu_ui = PauseMenuUI()
    keybindings = KeyBindings()
    screen_stack = []
    screen_uis = {
        "inventory": inventory_ui, "spellbook": spellbook_ui,
        "trainer": trainer_ui, "loot": loot_ui, "vendor": vendor_ui,
        "storage": storage_ui,
        "character_sheet": character_sheet_ui,
    }
    combat_log_rect = pygame.Rect(0, 0, 0, 0)
    combat_log_scroll = 0
    chat_mode = False
    chat_text = ""
    local_speech = None
    explore_destination = None

    def sync_screen_stack():
        active_screen = screen_stack[-1] if screen_stack else None
        for name, screen_ui in screen_uis.items():
            screen_ui.visible = active_screen == name
        pause_menu_ui.visible = active_screen == "pause"

    def push_screen(name, *, replace=False):
        open_overlay(screen_stack, name, replace=replace)
        sync_screen_stack()

    def pop_screen():
        pop_overlay(screen_stack)
        sync_screen_stack()

    def open_pause_menu():
        if not screen_stack:
            push_screen("pause")

    def handle_screen_navigation(event):
        """Handle modal stack navigation before a screen consumes input."""
        nonlocal interact_prompt
        if event.type != pygame.KEYDOWN:
            return False
        active_screen = screen_stack[-1] if screen_stack else None
        if active_screen == "remapper":
            result = keybindings.handle_event(event)
            if result == "close":
                pop_screen()
            return True
        if keybindings.matches(event, "inventory"):
            if active_screen == "inventory":
                if inventory_ui.attribute_screen:
                    inventory_ui.attribute_screen = False
                else:
                    pop_screen()
            else:
                push_screen("inventory")
            return True
        if keybindings.matches(event, "spellbook"):
            if active_screen == "spellbook":
                pop_screen()
            else:
                push_screen("spellbook", replace=(active_screen == "inventory"))
            return True
        if event.key == pygame.K_ESCAPE:
            if active_screen == "pause":
                pop_screen()
            elif active_screen == "loot":
                submit({"type": "loot_finish", "target": loot_ui.corpse_id})
                loot_ui.close()
                pop_screen()
            elif active_screen == "inventory" and inventory_ui.attribute_screen:
                inventory_ui.attribute_screen = False
            elif active_screen:
                if active_screen == "character_sheet":
                    character_sheet_ui.close()
                pop_screen()
            elif interact_prompt:
                interact_prompt = None
            elif selected_target:
                clear_selected_target()
            else:
                open_pause_menu()
            return True
        return False

    def clear_selected_target():
        nonlocal selected_target
        selected_target = None

    def submit(action):
        nonlocal combat, action_notice, action_notice_until
        nonlocal feedback_target_id, feedback_flash_until
        if is_host:
            updated = _handle_action_request(
                actor, player_id, player_id, action, remote_players, combat,
                vendor_state)
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
                if updated.get("vendor_state_changed"):
                    updated.pop("_action_notice", None)
                    updated.pop("vendor_state_changed", None)
                    combat = updated
                    _sync_local_actor(actor, combat, player_id)
                if updated.get("rest_state_changed"):
                    updated.pop("_action_notice", None)
                    updated.pop("rest_state_changed", None)
                    combat = updated
                    _sync_local_actor(actor, combat, player_id)
                if updated.get("area_changed"):
                    updated.pop("_action_notice", None)
                    updated.pop("area_changed", None)
                    vendor_state["buyback"] = {}
                    updated["vendor_buyback"] = {}
                    combat = updated
                    _sync_local_actor(actor, combat, player_id)
                return
            combat = updated
            _sync_local_actor(actor, combat, player_id)
        else:
            combat_transport["submit"](action)

    def use_bar_action(assigned_action):
        nonlocal action_notice, action_notice_until
        consumed, notice = dispatch_hotbar_action(
            assigned_action, selected_target, submit, toggle_sneaking,
            notify_missing_target=True)
        if notice:
            action_notice = "Select a target first."
            action_notice_until = pygame.time.get_ticks() + 1800
        return consumed

    def toggle_sneaking():
        nonlocal action_notice, action_notice_until
        if combat and combat.get("active"):
            action_notice = "You cannot sneak during combat. Use Hide instead."
        elif actor.downed:
            action_notice = "A downed character cannot sneak."
        else:
            actor.sneaking = not bool(getattr(actor, "sneaking", False))
            if actor.sneaking:
                actor.stealth_check_total = _stealth_check(vars(actor))["total"]
                action_notice = (
                    f"Sneaking (Stealth {actor.stealth_check_total}). Press K to stop.")
            else:
                actor.stealth_check_total = None
                action_notice = "You stop sneaking."
        action_notice_until = pygame.time.get_ticks() + 2200

    while running:
        dt = clock.tick(60)
        remote_players = get_other_players() if multiplayer else []
        if is_host:
            combat, host_notice, host_notice_duration = advance_host_world(
                actor, player_id, remote_players, combat, combat_transport,
                vendor_state)
            if host_notice is not None:
                action_notice = host_notice
                action_notice_until = (pygame.time.get_ticks()
                                       + host_notice_duration)
        else:
            latest = combat_transport["get"]()
            if latest is not None:
                area_changed = (latest.get("scenario_id")
                                != last_area_scenario_id)
                combat = latest
                last_area_scenario_id = combat.get("scenario_id")
                _sync_local_actor(actor, combat, player_id,
                                  consume_position_sync=True,
                                  force_position=area_changed)

        if loot_ui.visible:
            loot_container = ((combat or {}).get("actors", {}).get(
                loot_ui.corpse_id) or next((item for item in
                    (combat or {}).get("chests", [])
                    if item.get("id") == loot_ui.corpse_id), None))
            if not loot_container or not loot_container.get("loot"):
                loot_ui.close()
        if screen_stack and screen_stack[-1] == "loot" and not loot_ui.visible:
            pop_screen()

        if selected_target:
            available_targets = set((combat or {}).get("actors", {}))
            available_targets.update(_player_id(remote) for remote in remote_players)
            if selected_target not in available_targets:
                selected_target = None
            else:
                target_entry = (combat or {}).get("actors", {}).get(selected_target)
                if (target_entry and target_entry.get("team") == "enemies"
                        and (target_entry.get("downed")
                             or target_entry.get("data", {}).get("current_hp", 1) <= 0)):
                    selected_target = None

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
            SCENARIOS.get((combat or {}).get("scenario_id", DEFAULT_SCENARIO), {})
            .get("arena"), {})
        render_scenario = (combat or {}).get("scenario_id")
        scenario_changed = (render_scenario_id is not None
                            and render_scenario != render_scenario_id)
        render_scenario_id = render_scenario
        combat_render_positions = _smooth_combat_positions(
            combat, combat_render_positions, dt, reset=scenario_changed)
        local_draw_position = combat_render_positions.get(
            player_id, (actor.x, actor.y))
        camera = _camera_offset_position(
            *local_draw_position, current_arena, screen.get_size())

        for event in pygame.event.get():
            if keybindings.matches(event, "fullscreen"):
                if fullscreen:
                    screen = pygame.display.set_mode(
                        windowed_size, pygame.RESIZABLE)
                    fullscreen = False
                else:
                    windowed_size = screen.get_size()
                    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
                    fullscreen = True
            elif event.type == pygame.VIDEORESIZE and not fullscreen:
                windowed_size = (max(SCREEN_SIZE[0], event.w),
                                 max(SCREEN_SIZE[1], event.h))
                screen = pygame.display.set_mode(windowed_size, pygame.RESIZABLE)
            elif event.type == pygame.QUIT:
                exit_to_menu = False
                running = False
            elif chat_mode and event.type in (pygame.TEXTINPUT, pygame.KEYDOWN):
                handled, chat_text, speech = handle_chat_event(
                    event, chat_text, actor, local_animation, facing_left,
                    send_state, submit)
                if speech is not None:
                    local_speech = speech
                if handled and event.type == pygame.KEYDOWN and event.key in (
                        pygame.K_ESCAPE, pygame.K_RETURN, pygame.K_KP_ENTER):
                    chat_mode = False
            elif chat_mode:
                continue
            elif handle_screen_navigation(event):
                continue
            elif screen_stack and screen_stack[-1] == "remapper":
                if keybindings.handle_event(event) == "close":
                    pop_screen()
                continue
            elif screen_stack and screen_stack[-1] == "pause":
                pause_action = pause_menu_ui.handle_event(event)
                if pause_action == "resume":
                    pop_screen()
                elif pause_action == "save":
                    _sync_local_actor(actor, combat, player_id)
                    save_actor(actor)
                    save_notice_until = pygame.time.get_ticks() + 1800
                    pop_screen()
                elif pause_action == "menu":
                    exit_to_menu = True
                    running = False
                elif pause_action == "quit":
                    exit_to_menu = False
                    running = False
                elif pause_action == "remap":
                    push_screen("remapper")
                continue
            elif screen_stack and screen_stack[-1] == "character_sheet":
                character_sheet_ui.handle_event(event)
                if not character_sheet_ui.visible:
                    pop_screen()
                continue
            elif actor.downed:
                if keybindings.matches(event, "ranged"):
                    submit({"type": "release_spirit"})
                elif keybindings.matches(event, "return_menu"):
                    exit_to_menu = True
                    running = False
                continue
            elif event.type == pygame.MOUSEWHEEL:
                if loot_ui.visible:
                    container = ((combat or {}).get("actors", {}).get(
                        loot_ui.corpse_id) or next((item for item in
                            (combat or {}).get("chests", [])
                            if item.get("id") == loot_ui.corpse_id), None))
                    loot_ui.handle_event(
                        event, container.get("loot", []) if container else [])
                elif combat_log_rect.collidepoint(pygame.mouse.get_pos()):
                    log_count = sum(max(1, math.ceil(
                        font.size(str(message))[0] / 370))
                        for message in (combat or {}).get("log", []))
                    combat_log_scroll = max(0, min(max(0, log_count - 5),
                                                  combat_log_scroll + event.y))
            elif keybindings.matches(event, "controls"):
                controls_visible = not controls_visible
            elif keybindings.matches(event, "tooltips"):
                spellbook_ui.tooltips_enabled = not spellbook_ui.tooltips_enabled
            elif keybindings.matches(event, "cycle_bar"):
                spellbook_ui.cycle_bar(
                    vars(actor), filled_only=(not (
                        screen_stack and screen_stack[-1] == "spellbook")))
            elif (keybindings.matches(event, "sneak")
                  and not (combat and combat.get("active")) and not actor.downed
                  and not spellbook_ui.visible and not inventory_ui.visible
                  and not trainer_ui.visible and not loot_ui.visible
                  and not interact_prompt and not chat_mode):
                toggle_sneaking()
            elif spellbook_ui.visible:
                spell_data = vars(actor)
                spellbook_action = spellbook_ui.handle_event(event, spell_data)
                if spellbook_action:
                    submit(spellbook_action)
                actor.spell_hotbars = deepcopy(
                    spell_data.get("spell_hotbars", actor.spell_hotbars))
            elif vendor_ui.visible:
                vendor = next((item for item in current_arena.get("vendors", [])
                               if item.get("id") == vendor_ui.vendor_id), None)
                vendor_data = ((combat or {}).get("actors", {}).get(player_id, {})
                               .get("data", vars(actor)))
                buyback_by_actor = (combat or {}).get(
                    "vendor_buyback", vendor_state["buyback"])
                buyback = buyback_by_actor.get(player_id, [])
                vendor_action = vendor_ui.handle_event(
                    event, vendor, vendor_data, buyback)
                if vendor_action:
                    submit(vendor_action)
            elif trainer_ui.visible:
                trainer_data = ((combat or {}).get("actors", {}).get(player_id, {})
                                .get("data", vars(actor)))
                trainer_action = trainer_ui.handle_event(event, trainer_data)
                if trainer_action:
                    submit(trainer_action)
            elif interact_prompt:
                if (event.type == pygame.KEYDOWN and event.key == pygame.K_y
                        or keybindings.matches(event, "chat")):
                    if interact_prompt.get("type") == "inn_bed":
                        submit({"type": "rest_inn_checkin",
                                "bed_id": interact_prompt.get("bed_id")})
                    elif interact_prompt.get("type") == "innkeeper":
                        submit({"type": "inn_book_bed"})
                    elif interact_prompt.get("type") == "camp_exit":
                        submit({"type": "leave_camp"})
                    elif interact_prompt.get("type") == "area_exit":
                        submit({"type": "travel_exit",
                                "exit_id": interact_prompt.get("exit_id")})
                    interact_prompt = None
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_n:
                    interact_prompt = None
            elif loot_ui.visible:
                container = ((combat or {}).get("actors", {}).get(
                    loot_ui.corpse_id) or next((item for item in
                        (combat or {}).get("chests", [])
                        if item.get("id") == loot_ui.corpse_id), None))
                loot_action = loot_ui.handle_event(
                    event, container.get("loot", []) if container else [])
                if loot_action:
                    submit(loot_action)
                    if loot_action["type"] in {"loot_finish", "loot_take_all"}:
                        loot_ui.close()
            elif storage_ui.visible:
                storage_data = ((combat or {}).get("actors", {}).get(
                    player_id, {}).get("data", vars(actor)))
                storage_action = storage_ui.handle_event(event, storage_data)
                if storage_action:
                    submit(storage_action)
            elif (keybindings.matches(event, "quick_item_q")
                  or keybindings.matches(event, "quick_item_e")):
                key = ("q" if keybindings.matches(event, "quick_item_q")
                       else "e")
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
                                inventory_action.get("target"), player_id,
                                remote_players, current_arena)
                    submit(inventory_action)
                actor.quick_items = deepcopy(inventory_data.get(
                    "quick_items", actor.quick_items))
            elif keybindings.matches(event, "chat"):
                chat_mode, chat_text = True, ""
                pygame.key.start_text_input()
            elif keybindings.matches(event, "interact"):
                interact_prompt, notice, duration = interact_nearby(
                    actor, player_id, current_arena, combat, submit,
                    trainer_ui, vendor_ui, loot_ui, storage_ui)
                if notice:
                    action_notice = notice
                    action_notice_until = pygame.time.get_ticks() + duration
                if trainer_ui.visible:
                    push_screen("trainer", replace=True)
                elif vendor_ui.visible:
                    push_screen("vendor", replace=True)
                elif loot_ui.visible:
                    push_screen("loot", replace=True)
                elif storage_ui.visible:
                    push_screen("storage", replace=True)
            elif keybindings.matches(event, "camp"):
                submit({"type": "rest_outdoor"})
            elif event.type == pygame.QUIT:
                exit_to_menu = False
                running = False
            elif keybindings.matches(event, "return_menu"):
                exit_to_menu = True
                running = False
            elif (keybindings.matches(event, "retry")
                  and is_host and combat and combat.get("result")
                  and combat["result"].get("outcome") != "victory"):
                previous = combat
                combat = _new_combat(actor, player_id, remote_players,
                                     previous.get("scenario_id", DEFAULT_SCENARIO))
                combat["world_areas"] = deepcopy(previous.get("world_areas", {}))
                combat["world_area_items"] = deepcopy(
                    previous.get("world_area_items", {}))
                combat["world_area_chests"] = deepcopy(
                    previous.get("world_area_chests", {}))
                combat["chests"] = deepcopy(previous.get(
                    "chests", combat.get("chests", [])))
                combat["ground_items"] = deepcopy(
                    previous.get("ground_items", []))
                combat["vendor_buyback"] = deepcopy(
                    previous.get("vendor_buyback", {}))
            elif keybindings.matches(event, "save"):
                # The design calls for explicit saves and a session-end save,
                # rather than continuous autosaving.
                _sync_local_actor(actor, combat, player_id)
                save_actor(actor)
                save_notice_until = pygame.time.get_ticks() + 1800
            elif (keybindings.matches(event, "invite")
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
                selected_actor = actor_at_world_position(
                    world_click, actor, click_players,
                    (combat or {}).get("actors", {}).values())
                if selected_actor:
                    character_sheet_ui.open(selected_actor)
                    push_screen("character_sheet", replace=True)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                clicked = False
                assigned_action = spellbook_ui.hud_action_at(event.pos)
                if assigned_action and not spellbook_ui.visible:
                    use_bar_action(assigned_action)
                    clicked = True
                if not clicked:
                    selected_target, clicked = target_at_screen_position(
                        event.pos, actor, player_id, combat, remote_players,
                        drawn_positions, camera, local_draw_position,
                        combat_render_positions)
                if not clicked and combat and combat.get("active") and local_can_act:
                    submit({"type": "move",
                            "x": event.pos[0] + camera[0] - ACTOR_SIZE / 2,
                            "y": event.pos[1] + camera[1] - ACTOR_SIZE / 2})
                elif not clicked and not (combat and combat.get("active")):
                    explore_destination = (event.pos[0] + camera[0] - ACTOR_SIZE / 2,
                                           event.pos[1] + camera[1] - ACTOR_SIZE / 2)
            elif keybindings.matches(event, "ranged"):
                if selected_target:
                    submit({"type": "ranged_attack", "target": selected_target})
                elif actor.downed:
                    submit({"type": "release_spirit"})
            elif keybindings.matches(event, "fast_hands"):
                if combat and combat.get("active"):
                    submit({"type": "fast_hands"})
            elif event.type == pygame.KEYDOWN and event.key in (
                    pygame.K_0, pygame.K_1, pygame.K_2, pygame.K_3,
                    pygame.K_4, pygame.K_5, pygame.K_6, pygame.K_7,
                    pygame.K_8, pygame.K_9):
                slot_index = 9 if event.key == pygame.K_0 else event.key - pygame.K_1
                bars = normalize_action_hotbars(vars(actor).get("spell_hotbars"))
                hotbar_action = bars[spellbook_ui.active_bar][slot_index]
                if hotbar_action:
                    dispatch_hotbar_action(
                        hotbar_action, selected_target, submit, toggle_sneaking,
                        notify_missing_target=False)
            elif keybindings.matches(event, "throw"):
                if selected_target:
                    submit({"type": "throw", "target": selected_target})
            elif keybindings.matches(event, "end_turn"):
                if combat and combat.get("active") and local_can_act:
                    submit({"type": "end_turn"})

            if screen_stack and screen_stack[-1] in screen_uis:
                active_ui = screen_uis[screen_stack[-1]]
                if not active_ui.visible:
                    pop_screen()

        keys = pygame.key.get_pressed()
        moving = False
        if (not screen_stack and not chat_mode
                and combat and combat.get("active")
                and local_can_act and not actor.downed):
            key_dx = int(bool(keys[pygame.K_RIGHT]
                               or keys[keybindings.key("move_right")])) - int(
                bool(keys[pygame.K_LEFT]
                     or keys[keybindings.key("move_left")]))
            key_dy = int(bool(keys[pygame.K_DOWN]
                               or keys[keybindings.key("move_down")])) - int(
                bool(keys[pygame.K_UP]
                     or keys[keybindings.key("move_up")]))
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
        if (not screen_stack and not chat_mode and not actor.downed and
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
                scenario = SCENARIOS.get(
                    (combat or {}).get("scenario_id", DEFAULT_SCENARIO), {})
                for spawn in scenario.get("enemies", []):
                    occupied.append(_actor_hitbox(spawn.get("x", 0),
                                                  spawn.get("y", 0)))
            if (keys[keybindings.key("move_up")]
                    or keys[keybindings.key("move_left")]
                    or keys[keybindings.key("move_down")]
                    or keys[keybindings.key("move_right")] or keys[pygame.K_UP]
                    or keys[pygame.K_DOWN] or keys[pygame.K_LEFT]
                    or keys[pygame.K_RIGHT]):
                explore_destination = None
            sneak_factor = max(0.1, min(1.0, float(
                MOB_GENERATION_RULES.get("stealth", {}).get(
                    "exploration_speed_multiplier", 0.5))))
            if explore_destination:
                dx, dy = (explore_destination[0] - actor.x,
                          explore_destination[1] - actor.y)
                distance = math.hypot(dx, dy)
                explore_speed = speed * (sneak_factor if getattr(actor, "sneaking", False) else 1)
                if distance <= explore_speed:
                    explore_destination = None
                else:
                    step = min(explore_speed, distance)
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
                    actor, keys, speed * (sneak_factor if getattr(actor, "sneaking", False) else 1),
                    facing_left, current_arena, occupied,
                    {"up": keybindings.key("move_up"),
                     "down": keybindings.key("move_down"),
                     "left": keybindings.key("move_left"),
                     "right": keybindings.key("move_right")})
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
            snapshot_is_authoritative = (combat_is_active
                                        or bool(combat.get("rest_session")))
            remote_players = [
                {**remote,
                 "x": (combat_actors.get(_player_id(remote), {}).get(
                     "x", remote.get("x", 0)) if snapshot_is_authoritative
                     else remote.get("x", 0)),
                 "y": (combat_actors.get(_player_id(remote), {}).get(
                     "y", remote.get("y", 0)) if snapshot_is_authoritative
                     else remote.get("y", 0)),
                 "combat_animation": (combat_actors.get(
                     _player_id(remote), {}).get("animation_event")
                     if combat_is_active else None),
                 "facing": (combat_actors.get(_player_id(remote), {}).get(
                     "facing_left", remote.get("facing", False))
                     if combat_is_active else remote.get("facing", False)),
                 "downed": (combat_actors.get(_player_id(remote), {}).get(
                     "downed", (remote.get("actor") or {}).get("downed", False))
                     if snapshot_is_authoritative else
                     (remote.get("actor") or {}).get("downed", False))}
                for remote in remote_players
            ]

        camera = _camera_offset_position(
            *local_draw_position, current_arena, screen.get_size())
        drawn_positions = _draw_players(
            screen, actor, sprite, remote_players, remote_animations,
            remote_positions, dt, sprite_frames, frame_duration, current_arena,
            camera, local_speech, font, local_draw_position)
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
            "combat_positions": combat_render_positions,
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
            "remote_players": remote_players,
            "save_notice_until": save_notice_until,
            "screen": screen,
            "selected_target": selected_target,
            "spellbook_ui": spellbook_ui,
            "storage_ui": storage_ui,
            "sprite_frames": sprite_frames,
            "trainer_ui": trainer_ui,
            "vendor_ui": vendor_ui,
            "vendor_buyback": ((combat or {}).get("vendor_buyback", {})
                                .get(player_id, []) if combat else
                                vendor_state["buyback"].get(player_id, [])),
        })
        character_sheet_ui.draw(screen, font)
        if screen_stack and screen_stack[-1] == "pause":
            pause_menu_ui.draw(screen, font)
        elif screen_stack and screen_stack[-1] == "remapper":
            keybindings.draw(screen, font)
        _draw_sword_cursor(screen)
        pygame.display.flip()

    _sync_local_actor(actor, combat, player_id)
    save_actor(actor)
    pygame.mouse.set_visible(True)
    pygame.quit()
    return "menu" if exit_to_menu else "quit"
