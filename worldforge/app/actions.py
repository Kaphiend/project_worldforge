"""Combat action validation, turn flow, and effect resolution."""
import pygame


from worldforge.content.classes import ARENAS, SCENARIOS
from worldforge.combat.controllers import controller_for
from worldforge.combat.conditions import has_condition
from worldforge.actors.factory import equip_item, unequip_item
from worldforge.app.encounters import DEFAULT_SCENARIO

from worldforge.app.world import (ACTOR_SIZE, PIXELS_PER_FOOT, _actor_hitbox,
                                  _arena_bounds, _walk_destination)
from worldforge.app.rendering import _emit_animation
from worldforge.app.attack_actions import _do_attack, _do_fast_hands, _do_hide
from worldforge.app.item_actions import _do_item
from worldforge.app.spell_actions import _do_ability, _do_spell
from worldforge.app.combat_flow import (
    _active_actor_id, _advance_turn, _log, _reject_action,
)

def _apply_action(combat, actor_id, action):
    action_type = action.get("type")
    if action_type == "flee" and actor_id == _active_actor_id(combat):
        # Retreat ends the encounter for the whole party. Keep the world state
        # intact, but suppress new encounter triggers briefly so nearby mobs
        # do not immediately pull the party back into combat.
        combat["aggro_immune_until"] = pygame.time.get_ticks() + 3000
        combat["active"] = False
        combat["result"] = None
        combat["order"] = []
        combat["budgets"] = {}
        combat["turn_index"] = 0
        for entry in combat.get("actors", {}).values():
            if entry.get("team") == "enemies":
                entry["data"].pop("hidden", None)
        _log(combat, "The party flees. Nearby enemies lose aggro for 3 seconds.")
    elif action_type == "hide":
        _do_hide(combat, actor_id)
    elif action_type == "fast_hands":
        _do_fast_hands(combat, actor_id)
    elif action_type == "attack":
        _do_attack(combat, actor_id, action.get("target"))
    elif action_type == "unarmed_strike":
        _do_attack(combat, actor_id, action.get("target"), attack_mode="unarmed")
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
