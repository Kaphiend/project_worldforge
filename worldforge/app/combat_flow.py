"""Shared combat logging, initiative, and turn lifecycle rules."""
import uuid

from worldforge.combat.conditions import tick_conditions
from worldforge.core.progression import (character_level_for_xp,
    charge_xp_penalty, qualified_level, sync_progression_levels)
from worldforge.app.rendering import _capture_hp, _emit_animation
from worldforge.app.world import _movement_allowance
from worldforge.content.campaign import campaign_rule
from worldforge.content.classes import EXPERIENCE_RULES


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
            penalty = charge_xp_penalty(
                entry["data"], campaign_rule("revival_xp_penalty_percent", 2))
            if penalty:
                _log(combat, f"{entry['data'].get('name', actor_id)} loses {penalty} XP after being revived.")

def _log(combat, message):
    combat.setdefault("log", []).append(message)
    combat["log"] = combat["log"][-8:]

def _award_combat_xp(combat, amount=None):
    """Award defeated-creature XP, divided among participants.

    ``amount`` is an optional explicit encounter award for scripted scenarios;
    normal victories use each defeated NPC's xp_reward or CR-derived value.
    """
    if combat.get("xp_awarded"):
        return
    combat["xp_awarded"] = True
    players = [(actor_id, entry) for actor_id, entry in
               combat.get("actors", {}).items()
               if entry.get("team") == "players"]
    if not players:
        return
    if amount is None:
        challenge_xp = EXPERIENCE_RULES.get("challenge_rating_xp", {})
        total_xp = 0
        for defeated in combat.get("actors", {}).values():
            if defeated.get("team") != "enemies" or not defeated.get("downed"):
                continue
            data = defeated.get("data", {})
            xp = data.get("xp_reward")
            if xp is None:
                cr = data.get("challenge_rating")
                xp = challenge_xp.get(str(cr), 0)
            total_xp += max(0, int(xp or 0))
        amount = round(total_xp * max(0, campaign_rule("xp_debug_multiplier", 1.0)))
    # Divide encounter XP evenly; distribute remainder deterministically.
    quotient, remainder = divmod(max(0, int(amount)), len(players))
    for index, (actor_id, entry) in enumerate(players):
        award = quotient + (1 if index < remainder else 0)
        if award <= 0:
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
        data["xp_total"] = int(data.get("xp_total", 0) or 0) + award
        by_level[level_key] = int(by_level.get(level_key, 0) or 0) + award
        sync_progression_levels(data)
        _log(combat, f"{data.get('name', actor_id)} gains {award} XP.")

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
        previous["data"].pop("disengaged", None)
        previous["data"].pop("pending_cunning_strike", None)
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
                      bonus_action=True, reaction=True, condition_tick_done=False,
                      movement_used=0, light_attack_available=False,
                      light_attack_attempted=False,
                      light_attack_weapon_id=None, nick_used=False,
                      cleave_used=False)
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
    combat.setdefault("sneak_attack_used", {})[actor_id] = False
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
                bonus_action=True, reaction=True, condition_tick_done=False,
                movement_used=0)
