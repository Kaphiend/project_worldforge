"""Melee, ranged, hide, and rogue combat actions."""
from copy import deepcopy
import uuid

from worldforge.actors.factory import item_definition
from worldforge.app.combat_flow import (
    _award_combat_xp, _log, _reject_action, _remove_downed_from_order,
)
from worldforge.app.rendering import _emit_animation
from worldforge.app.world import (ACTOR_SIZE, PIXELS_PER_FOOT, _hidden_from,
                                  _line_of_sight, _stealth_check)
from worldforge.combat.rules import (attack as resolve_attack, distance_feet,
                                     edge_distance_feet, selected_weapon)
from worldforge.combat.species import species_traits
from worldforge.content.classes import CLASSES, MOB_GENERATION_RULES


def _class_feature_attack_count(actor_data, attack_mode):
    if attack_mode == "throw":
        return 0
    owned = set(actor_data.get("class_features", []) or [])
    count = 0
    for class_data in CLASSES.values():
        progression = class_data.get("progression", {}) or {}
        for features in progression.values():
            for feature in features or []:
                if feature.get("id") not in owned:
                    continue
                effect = feature.get("effect", {}) or {}
                if effect.get("kind") == "extra_weapon_attack":
                    count += max(0, int(effect.get("amount", 0) or 0))
    return count


def _rogue_level(actor_data):
    levels = [int(item.get("level", 0) or 0)
              for item in actor_data.get("classes", []) or []
              if item.get("name") == "rogue"]
    if levels:
        return max(levels)
    return int(actor_data.get("level", 1) or 1) if actor_data.get(
        "char_class") == "rogue" else 0


def _sneak_attack_dice(actor_data):
    if "rogue_sneak_attack" not in set(actor_data.get("class_features", []) or []):
        return 0
    return max(0, min(10, (_rogue_level(actor_data) + 1) // 2))


def _do_hide(combat, actor_id):
    actor_entry = combat.get("actors", {}).get(actor_id)
    if not actor_entry or actor_entry.get("downed"):
        _reject_action(combat, "A downed actor cannot hide.", actor_id)
        return False
    actor_data = actor_entry["data"]
    budget = combat.get("budgets", {}).get(actor_id, {})
    cost = ("bonus_action" if "rogue_cunning_action" in
            set(actor_data.get("class_features", []) or []) else "action")
    if not budget.get(cost):
        _reject_action(combat, f"Your {cost.replace('_', ' ')} is already used.", actor_id)
        return False
    enemies = [entry for entry in combat.get("actors", {}).values()
               if entry.get("team") == "enemies" and not entry.get("downed")]
    if not enemies:
        _reject_action(combat, "There is no threat to hide from.", actor_id)
        return False
    # SRD 5.2.1 requires cover or heavy obscurement and that no enemy has
    # line of sight. Arena obstacles currently represent total cover.
    if any(_line_of_sight(enemy, actor_entry, combat.get("arena"))
           for enemy in enemies):
        _reject_action(combat, "You need cover or heavy obscurement and must be out of every enemy's sight.", actor_id)
        return False
    budget[cost] = False
    check = _stealth_check(actor_data)
    hide_dc = max(1, int(MOB_GENERATION_RULES.get("stealth", {}).get("hide_dc", 15)))
    if check["total"] < hide_dc:
        _log(combat, f"{actor_data.get('name', actor_id)} fails to hide (Stealth {check['total']}; DC {hide_dc}).")
        return True
    actor_data["hidden"] = {"stealth_total": check["total"], "detected_by": []}
    actor_data["sneaking"] = False
    actor_data["stealth_check_total"] = None
    _log(combat, f"{actor_data.get('name', actor_id)} hides (Stealth {check['total']}).")
    return True


def _do_fast_hands(combat, actor_id):
    """Take the Thief's bonus-action Sleight of Hand check."""
    entry = combat.get("actors", {}).get(actor_id)
    if not entry or entry.get("downed"):
        _reject_action(combat, "A downed actor cannot use Fast Hands.", actor_id)
        return False
    actor = entry["data"]
    if "fast_hands" not in actor.get("class_features", []) or actor.get("subclass") != "rogue_thief":
        _reject_action(combat, "Fast Hands is not available to this character.", actor_id)
        return False
    budget = combat.get("budgets", {}).get(actor_id, {})
    if not budget.get("bonus_action"):
        _reject_action(combat, "Your bonus action is already used.", actor_id)
        return False
    from worldforge.actors.factory import modifier
    from worldforge.combat.rules import proficiency_bonus
    from worldforge.core.dice import roll_d20
    skills = {str(value).casefold() for value in actor.get("skills", []) or []}
    bonus = modifier((actor.get("abilities", {}) or {}).get("dexterity", 10))
    if "sleight of hand" in skills:
        bonus += proficiency_bonus(actor)
    natural, rolls = roll_d20()
    if natural == 1 and "lucky" in species_traits(actor):
        natural, reroll = roll_d20()
        rolls += reroll
    budget["bonus_action"] = False
    _log(combat, f"{actor.get('name', actor_id)} uses Fast Hands for Sleight of Hand (d20 {rolls} + {bonus} = {natural + bonus}).")
    return True


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
    if _hidden_from(actor_entry, target_entry, combat.get("arena")):
        _reject_action(combat, "You have not found that hidden target.", target_id)
        return False
    if actor_entry["downed"] or target_entry["downed"]:
        _reject_action(combat, "A downed actor cannot attack or be targeted.",
                       target_id if target_entry["downed"] else actor_id)
        return False
    budget = combat["budgets"][actor_id]
    if not budget["action"]:
        _reject_action(combat, "Action already used this turn.", actor_id)
        return False
    modes = [attack_mode if attack_mode in ("throw", "ranged", "unarmed") else "primary"]
    extra_count = _class_feature_attack_count(actor_entry["data"], attack_mode)
    modes.extend([modes[0]] * extra_count)
    thrown_item = None
    for attack_index, mode in enumerate(modes):
        if target_entry["downed"] or target_entry["data"].get("current_hp", 1) <= 0:
            break
        if attack_index > 0:
            _log(combat, f"{actor_entry['data'].get('name', 'Actor')} makes a follow-up attack.")
        distance = distance_feet(actor_entry, target_entry, PIXELS_PER_FOOT, ACTOR_SIZE)
        edge_distance = edge_distance_feet(
            actor_entry, target_entry, PIXELS_PER_FOOT, ACTOR_SIZE)
        line_of_sight = _line_of_sight(actor_entry, target_entry, combat.get("arena"))
        event = resolve_attack(
            actor_entry["data"], target_entry["data"], distance,
            melee_distance_feet=edge_distance, adjacent_distance_feet=edge_distance,
            line_of_sight=line_of_sight, attack_mode=mode,
            unseen_attack=(isinstance(actor_entry["data"].get("hidden"), dict)
                           and _hidden_from(target_entry, actor_entry,
                                            combat.get("arena"))),
            sneak_attack_dice=(0 if combat.setdefault(
                "sneak_attack_used", {}).get(actor_id) else
                _sneak_attack_dice(actor_entry["data"])),
            sneak_attack_opportunity=any(
                ally_id != actor_id and ally.get("team") == actor_entry.get("team")
                and not ally.get("downed")
                and edge_distance_feet(ally, target_entry) <= 5
                for ally_id, ally in combat.get("actors", {}).items()))
        if not event.get("success"):
            if attack_index == 0:
                _reject_action(combat, event.get("message", "Attack unavailable."), target_id)
                return False
            break
        if event.get("thrown"):
            thrown_item = deepcopy(
                actor_entry["data"].get("equipment", {}).get("main_hand"))
        budget["action"] = False
        if isinstance(actor_entry["data"].get("hidden"), dict):
            actor_entry["data"]["hidden"] = None
            actor_entry["data"]["sneaking"] = False
            actor_entry["data"]["stealth_check_total"] = None
            _log(combat, f"{actor_entry['data'].get('name', actor_id)} reveals their position.")
        if event.get("sneak_attack_damage"):
            combat["sneak_attack_used"][actor_id] = True
        if mode == "ranged":
            weapon = actor_entry["data"].get("equipment", {}).get("ranged")
            weapon_definition = item_definition(weapon) if weapon else {}
        else:
            weapon, weapon_definition, _ = selected_weapon(actor_entry["data"])
        if event.get("thrown"):
            weapon = actor_entry["data"].get("equipment", {}).get("main_hand")
            weapon_definition = item_definition(weapon) if weapon else {}
        if event.get("ranged"):
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
        defense = (f" vs AC {event['target_ac']}"
                   if target_entry["team"] == "players" else "")
        if event["hit"]:
            target_entry["downed"] = bool(
                target_entry["data"].get("downed")
                or target_entry["data"].get("current_hp", 1) <= 0)
            _emit_animation(combat, target_id,
                            "dead" if target_entry["downed"] else "hurt")
            verdict = "critical hit" if event["critical"] else "hit"
            sneak_note = (f" including {event['sneak_attack_damage']} Sneak Attack damage"
                          if event.get("sneak_attack_damage") else "")
            _log(combat, (f"{event['attacker']} {verdict} {event['target']} with "
                          f"{event['weapon']} (d20 {event['rolls']} = {event['total']}"
                          f"{defense}); {event['damage_rolls']} + modifier = "
                          f"{event['damage']} {event['damage_type']} damage"
                          f"{' (resistance)' if event.get('resisted') else ''}{sneak_note}."))
        else:
            _log(combat, (f"{event['attacker']} misses {event['target']} with "
                          f"{event['weapon']} (d20 {event['rolls']} = {event['total']}"
                          f"{defense})."))
        for enemy in combat["actors"].values():
            if enemy["team"] == "enemies" and enemy["data"].get("current_hp", 1) <= 0:
                enemy["downed"] = True
    _remove_downed_from_order(combat)
    if thrown_item:
        equipment = actor_entry["data"].setdefault("equipment", {})
        thrown_id = thrown_item.get("id")
        for slot, equipped in list(equipment.items()):
            if equipped and equipped.get("id") == thrown_id:
                equipment[slot] = None
        if event.get("hit") and target_entry.get("team") == "enemies":
            target_entry["data"].setdefault("inventory", []).append(thrown_item)
            _log(combat, f"{event['target']} is carrying the thrown {thrown_item.get('name', 'weapon')}.")
        else:
            item_size = 24
            combat.setdefault("ground_items", []).append({
                "id": uuid.uuid4().hex,
                "item": thrown_item,
                "x": target_entry["x"] + ACTOR_SIZE / 2 - item_size / 2,
                "y": target_entry["y"] + ACTOR_SIZE / 2 - item_size / 2,
                "width": item_size,
                "height": item_size,
            })
            _log(combat, f"The thrown {thrown_item.get('name', 'weapon')} falls to the ground.")
    enemies = [entry for entry in combat["actors"].values()
               if entry["team"] == "enemies"]
    if enemies and all(entry["downed"] for entry in enemies):
        combat["active"] = False
        _log(combat, "All enemies defeated. Combat ended.")
        combat["result"] = {"outcome": "victory", "message": combat.get("scenario", {}).get("victory", "Encounter complete.")}
        _award_combat_xp(combat)
    return True

