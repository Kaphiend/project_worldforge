"""Melee, ranged, hide, and rogue combat actions."""
from copy import deepcopy
import uuid

from worldforge.actors.factory import item_definition, modifier
from worldforge.app.combat_flow import (
    _award_combat_xp, _debug_log, _log, _reject_action,
    _remove_downed_from_order,
)
from worldforge.app.rendering import _emit_animation
from worldforge.app.world import (ACTOR_SIZE, PIXELS_PER_FOOT, _hidden_from,
                                  _line_of_sight, _stealth_check,
                                  _actor_hitbox, _walk_destination)
from worldforge.combat.rules import (attack as resolve_attack, distance_feet,
                                     edge_distance_feet, proficiency_bonus,
                                     resolve_skill_check, selected_weapon)
from worldforge.combat.conditions import apply_condition
from worldforge.combat.spell_effects import _target_save_modifier
from worldforge.core.dice import roll_d20
from worldforge.content.classes import CLASSES, MOB_GENERATION_RULES
from worldforge.content.campaign import campaign_rule


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
    if ("rogue_sneak_attack" not in set(actor_data.get("class_features", []) or [])
            or actor_data.get("sneak_attack_enabled", True) is False):
        return 0
    return max(0, min(10, (_rogue_level(actor_data) + 1) // 2))


def _has_weapon_mastery(actor_data):
    return bool({"rogue_weapon_mastery", "fighter_weapon_mastery",
                 "ranger_weapon_mastery", "paladin_weapon_mastery"}.intersection(
        actor_data.get("class_features", []) or []))


def _cleave_available(combat, actor_id):
    budget = combat.get("budgets", {}).get(actor_id, {})
    turn_token = (int(combat.get("round", 1)), int(combat.get("turn_index", 0)))
    return budget.get("cleave_used_turn") != turn_token


def _resolve_cleave(combat, actor_id, first_target_id, weapon):
    """Attack the nearest eligible second target with Cleave once per turn."""
    actor = combat["actors"][actor_id]
    first = combat["actors"][first_target_id]
    budget = combat.get("budgets", {}).get(actor_id, {})
    definition = item_definition(weapon)
    reach = (definition.get("ranges", {}) or {}).get(
        "melee", campaign_rule("melee_reach_feet", 5))
    candidates = []
    for candidate_id, candidate in combat.get("actors", {}).items():
        if (candidate_id in {actor_id, first_target_id} or candidate.get("downed")
                or candidate.get("team") == actor.get("team")
                or _hidden_from(actor, candidate, combat.get("arena"))):
            continue
        adjacent_to_first = edge_distance_feet(first, candidate)
        if adjacent_to_first > 5 or edge_distance_feet(actor, candidate) > reach:
            continue
        if not _line_of_sight(actor, candidate, combat.get("arena")):
            continue
        candidates.append((adjacent_to_first, candidate_id, candidate))
    if not candidates:
        return False
    _, candidate_id, candidate = min(candidates, key=lambda row: (row[0], row[1]))
    budget["cleave_used"] = True
    budget["cleave_used_turn"] = (int(combat.get("round", 1)),
                                  int(combat.get("turn_index", 0)))
    distance = distance_feet(actor, candidate, PIXELS_PER_FOOT, ACTOR_SIZE)
    edge_distance = edge_distance_feet(actor, candidate)
    event = resolve_attack(
        actor["data"], candidate["data"], distance,
        melee_distance_feet=edge_distance, adjacent_distance_feet=edge_distance,
        line_of_sight=True, target_actor_id=candidate_id,
        weapon_override=weapon, damage_modifier_cap=0)
    if not event.get("success"):
        return False
    if event.get("hit"):
        candidate["downed"] = bool(candidate["data"].get("downed")
                                    or candidate["data"].get("current_hp", 1) <= 0)
        _emit_animation(combat, candidate_id,
                        "dead" if candidate["downed"] else "hurt")
        _log(combat, f"Cleave hits {event['target']} for {event['damage']} {event['damage_type']} damage.")
    else:
        _log(combat, f"Cleave misses {event['target']}.")
    return True


def _resolve_cunning_strike(combat, actor_id, actor_data, target_data, option):
    if option == "withdraw":
        actor_data["disengaged"] = True
        _log(combat, f"{actor_data.get('name', actor_id)} uses Cunning Strike: Withdraw.")
        return True
    save_ability = {"trip": "dexterity", "poison": "constitution"}.get(option)
    condition_id = {"trip": "prone", "poison": "poisoned"}.get(option)
    if not save_ability:
        return False
    dc = (8 + modifier((actor_data.get("abilities", {}) or {}).get(
        "dexterity", 10)) + proficiency_bonus(actor_data))
    natural, dice = roll_d20()
    save_modifier = _target_save_modifier(target_data, save_ability)
    save = natural + save_modifier
    _debug_log(combat, (f"Cunning Strike {option.title()} save: d20 {dice} -> {natural} "
                        f"+ {save_ability} modifier {save_modifier:+} = {save} vs DC {dc}."))
    if save < dc:
        apply_condition(target_data, condition_id, source_id="rogue_cunning_strike")
        _log(combat, f"Cunning Strike {option.title()} takes hold (save {dice}: {save} vs DC {dc}).")
    else:
        _log(combat, f"Cunning Strike {option.title()} is resisted (save {dice}: {save} vs DC {dc}).")
    return True


def _apply_weapon_mastery(combat, actor_id, target_id, weapon):
    """Resolve supported mastery properties after a proficient weapon hit."""
    actor = combat["actors"][actor_id]["data"]
    target_entry = combat["actors"][target_id]
    if not _has_weapon_mastery(actor):
        return
    template_id = (weapon or {}).get("template_id")
    mastery = (actor.get("weapon_masteries", {}) or {}).get(template_id)
    if not mastery:
        return
    definition = item_definition(weapon)
    weapon_class = definition.get("weapon_class")
    proficiencies = actor.get("weapon_prof", []) or []
    rogue_eligible = (actor.get("char_class") == "rogue"
                      and bool({"finesse", "light"}.intersection(
                          definition.get("tags", []) or [])))
    if weapon_class not in proficiencies and not rogue_eligible:
        return
    target = target_entry["data"]
    if mastery == "vex":
        target_effects = actor.setdefault("active_effects", [])
        if not any(effect.get("kind") == "next_attack_advantage"
                   and effect.get("source_id") == "weapon_mastery_vex"
                   for effect in target_effects):
            target_effects.append({"kind": "next_attack_advantage",
                                   "source_id": "weapon_mastery_vex",
                                   "target_id": target_id,
                                   "remaining_turns": 1})
        _log(combat, f"Vex grants {actor.get('name', actor_id)} advantage on their next attack against {target.get('name', target_id)}.")
    elif mastery == "sap":
        target.setdefault("active_effects", []).append({
            "kind": "attack_disadvantage_against_target",
            "source_id": "weapon_mastery_sap", "remaining_turns": 1})
        _log(combat, f"Sap hinders {target.get('name', target_id)}'s next attack.")
    elif mastery == "slow":
        target_budget = combat.setdefault("budgets", {}).get(target_id, {})
        target_budget["movement"] = max(0, int(target_budget.get("movement", 0)) - 10)
        _log(combat, f"Slow reduces {target.get('name', target_id)}'s movement by 10 feet this turn.")
    elif mastery == "push":
        size = str(target.get("size", target.get("size_category", "medium"))).casefold()
        if size in {"tiny", "small", "medium", "large"}:
            attacker_entry = combat["actors"][actor_id]
            dx = (target_entry["x"] + ACTOR_SIZE / 2) - (attacker_entry["x"] + ACTOR_SIZE / 2)
            dy = (target_entry["y"] + ACTOR_SIZE / 2) - (attacker_entry["y"] + ACTOR_SIZE / 2)
            length = (dx * dx + dy * dy) ** 0.5 or 1
            occupied = [_actor_hitbox(other["x"], other["y"])
                        for other_id, other in combat.get("actors", {}).items()
                        if other_id not in {actor_id, target_id} and not other.get("downed")]
            old_x, old_y = target_entry["x"], target_entry["y"]
            target_entry["x"], target_entry["y"] = _walk_destination(
                old_x, old_y, dx / length * 10 * PIXELS_PER_FOOT,
                dy / length * 10 * PIXELS_PER_FOOT,
                combat.get("arena"), occupied)
            target["x"], target["y"] = target_entry["x"], target_entry["y"]
            if (target_entry["x"], target_entry["y"]) != (old_x, old_y):
                _log(combat, f"Push moves {target.get('name', target_id)} away from the attacker.")
    elif mastery == "topple":
        abilities = actor.get("abilities", {}) or {}
        weapon_tags = set(definition.get("tags", []) or [])
        attack_ability = ("dexterity" if "finesse" in weapon_tags
                          and int(abilities.get("dexterity", 10))
                          >= int(abilities.get("strength", 10)) else "strength")
        dc = 8 + modifier(abilities.get(attack_ability, 10)) + proficiency_bonus(actor)
        natural, dice = roll_d20()
        save = natural + _target_save_modifier(target, "constitution")
        _debug_log(combat, (f"Topple save: d20 {dice} -> {natural} + Constitution "
                            f"modifier {_target_save_modifier(target, 'constitution'):+} "
                            f"= {save} vs DC {dc}."))
        if save < dc:
            apply_condition(target, "prone", source_id="weapon_mastery_topple")
            _log(combat, f"Topple knocks {target.get('name', target_id)} prone (save {dice}: {save} vs DC {dc}).")
        else:
            _log(combat, f"{target.get('name', target_id)} resists Topple (save {dice}: {save} vs DC {dc}).")


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
    _debug_log(combat, (f"Stealth check: d20 {check['dice']} -> {check['natural']} + "
                        f"Dexterity {check['ability_modifier']:+} + skill bonus "
                        f"{check['bonus'] - check['ability_modifier']:+} "
                        f"({'Expertise' if check.get('expertise') else 'Proficiency' if check.get('proficient') else 'untrained'}) = "
                        f"{check['total']} vs DC {hide_dc}."))
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
    check = resolve_skill_check(actor, "sleight of hand", "dexterity")
    bonus, natural, rolls = check["bonus"], check["natural"], check["dice"]
    _debug_log(combat, (f"Sleight of Hand check: d20 {rolls} -> {natural} + "
                        f"Dexterity {check['ability_modifier']:+} + skill bonus "
                        f"{bonus - check['ability_modifier']:+} "
                        f"({'Expertise' if check.get('expertise') else 'Proficiency' if check.get('proficient') else 'untrained'}) = {natural + bonus}."))
    budget["bonus_action"] = False
    _log(combat, f"{actor.get('name', actor_id)} uses Fast Hands for Sleight of Hand (d20 {rolls} + {bonus} = {natural + bonus}).")
    return True


def _do_attack(combat, actor_id, target_id, attack_mode="primary",
               cunning_strike=None):
    actor_entry = combat["actors"].get(actor_id)
    if actor_entry and target_id is None:
        # Attack hotkeys can arrive before the UI's aggro target selection is
        # synchronized. Resolve a missing target to the nearest visible foe.
        candidates = [entry for entry in combat.get("actors", {}).values()
                      if entry.get("team") != actor_entry.get("team")
                      and not entry.get("downed")
                      and entry.get("data", {}).get("current_hp", 1) > 0
                      and not entry.get("data", {}).get("withdrawn")
                      and not _hidden_from(actor_entry, entry,
                                           combat.get("arena"))]
        if candidates:
            target_id = min(candidates, key=lambda entry: edge_distance_feet(
                actor_entry, entry, PIXELS_PER_FOOT, ACTOR_SIZE))["id"]
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
    cunning_strike = (cunning_strike or
                      actor_entry["data"].get("pending_cunning_strike"))
    actor_data = actor_entry["data"]
    equipment = actor_data.get("equipment", {}) or {}
    if attack_mode == "offhand":
        off = equipment.get("off_hand")
        if not off or not item_definition(off).get("category") == "weapon":
            off = equipment.get("ranged_offhand")
        off_def = item_definition(off) if off else {}
        if not budget.get("bonus_action", False):
            _reject_action(combat, "Your Bonus Action is already spent this turn.", actor_id)
            return False
        if not budget.get("light_attack_available"):
            message = ("Your Attack action did not use a Light weapon."
                       if budget.get("light_attack_attempted") else
                       "Take the Attack action with a Light weapon first.")
            _reject_action(combat, message, actor_id)
            return False
        if (not off or "light" not in (off_def.get("tags", []) or [])
                or off.get("id", id(off)) == budget.get("light_attack_weapon_id")):
            _reject_action(combat, "Equip a different Light weapon in your other hand to make the off-hand attack.", actor_id)
            return False
    elif attack_mode != "offhand_nick" and not budget["action"]:
        _reject_action(combat, "Action already used this turn.", actor_id)
        return False
    modes = [attack_mode if attack_mode in ("throw", "ranged", "unarmed", "offhand", "offhand_nick") else "primary"]
    extra_count = _class_feature_attack_count(actor_data, attack_mode)
    modes.extend([modes[0]] * extra_count)
    # Nick moves the Light-property extra attack into the Attack action.
    mastery = (actor_data.get("weapon_masteries", {}) or {})
    main = (equipment.get("ranged") if actor_data.get("active_weapon_set") == "ranged"
            else equipment.get("main_hand"))
    off = equipment.get("off_hand")
    if not off or item_definition(off).get("category") != "weapon":
        off = equipment.get("ranged_offhand")
    main_def = item_definition(main) if main else {}
    off_def = item_definition(off) if off else {}
    if (attack_mode in {"primary", "ranged", "throw"} and main
            and "light" in (main_def.get("tags", []) or [])
            and "light" in (off_def.get("tags", []) or [])
            and main.get("id", id(main)) != off.get("id", id(off))
            and mastery.get(main.get("template_id", main.get("id"))) == "nick"
            and _has_weapon_mastery(actor_data)
            and not budget.get("nick_used", False)):
        modes.append("offhand_nick")
    sneak_dice = (0 if combat.setdefault("sneak_attack_used", {}).get(actor_id)
                  else _sneak_attack_dice(actor_entry["data"]))
    cunning_cost = 1 if cunning_strike in {"withdraw", "trip", "poison"} else 0
    if cunning_strike:
        if (cunning_strike not in {"withdraw", "trip", "poison"}
                or "rogue_cunning_strike" not in set(
                    actor_entry["data"].get("class_features", []) or [])):
            _reject_action(combat, "That Cunning Strike option is unavailable.", actor_id)
            return False
        if sneak_dice <= cunning_cost:
            _reject_action(combat, "Cunning Strike requires at least one remaining Sneak Attack die.", actor_id)
            return False
    thrown_item = None
    offhand_resolved = False
    nick_resolved = False
    for attack_index, mode in enumerate(modes):
        if target_entry["downed"] or target_entry["data"].get("current_hp", 1) <= 0:
            break
        if attack_index > 0:
            _log(combat, f"{actor_entry['data'].get('name', 'Actor')} makes a follow-up attack.")
        distance = distance_feet(actor_entry, target_entry, PIXELS_PER_FOOT, ACTOR_SIZE)
        edge_distance = edge_distance_feet(
            actor_entry, target_entry, PIXELS_PER_FOOT, ACTOR_SIZE)
        line_of_sight = _line_of_sight(actor_entry, target_entry, combat.get("arena"))
        target_budget = combat.get("budgets", {}).get(target_id, {})
        uncanny_dodge = (
            "rogue_uncanny_dodge" in set(
                target_entry["data"].get("class_features", []) or [])
            and target_budget.get("reaction", True) and line_of_sight)
        event = resolve_attack(
            actor_entry["data"], target_entry["data"], distance,
            melee_distance_feet=edge_distance, adjacent_distance_feet=edge_distance,
            line_of_sight=line_of_sight, attack_mode=mode,
            target_actor_id=target_id,
            unseen_attack=(isinstance(actor_entry["data"].get("hidden"), dict)
                           and _hidden_from(target_entry, actor_entry,
                                            combat.get("arena"))),
            sneak_attack_dice=(0 if combat["sneak_attack_used"].get(actor_id)
                               else sneak_dice - cunning_cost),
            sneak_attack_opportunity=any(
                ally_id != actor_id and ally.get("team") == actor_entry.get("team")
                and not ally.get("downed")
                and edge_distance_feet(ally, target_entry) <= campaign_rule("melee_reach_feet", 5)
                for ally_id, ally in combat.get("actors", {}).items()),
            damage_multiplier=0.5 if uncanny_dodge else 1.0)
        if not event.get("success"):
            _debug_log(combat, f"Attack could not resolve: {event.get('message', 'unknown reason')}.")
        if event.get("success"):
            _debug_log(combat, (
            f"Attack: {event.get('attacker')} vs {event.get('target')}; "
            f"d20 {event.get('rolls')} -> {event.get('natural')}; "
            f"ability modifier {event.get('ability_modifier', 0):+}, "
            f"proficiency {event.get('proficiency_bonus', 0):+}, "
            f"weapon bonus {event.get('weapon_attack_bonus', 0):+} = "
            f"{event.get('total')} vs AC {event.get('target_ac')} "
            f"({'critical' if event.get('critical') else 'hit' if event.get('hit') else 'miss'})."))
        if event.get("success") and event.get("hit"):
            _debug_log(combat, (
                f"Damage: weapon {event.get('damage_formula')} rolls "
                f"{event.get('damage_rolls', [])}; ability modifier "
                f"{event.get('damage_modifier', 0):+}, weapon bonus "
                f"{event.get('weapon_damage_bonus', 0):+}, style bonus "
                f"{event.get('style_damage_bonus', 0):+}, Sneak Attack rolls "
                f"{event.get('sneak_attack_rolls', [])}, feature rolls "
                f"{event.get('feature_bonus_rolls', [])}, Great Weapon Fighting rerolls "
                f"{event.get('great_weapon_rerolls', [])}; resistance "
                f"{'halved' if event.get('resisted') else 'none'}, "
                f"damage multiplier {event.get('damage_multiplier', 1)}; "
                f"final {event.get('damage', 0)} {event.get('damage_type', 'damage')}."))
        if not event.get("success"):
            if attack_index == 0:
                _reject_action(combat, event.get("message", "Attack unavailable."), target_id)
                return False
            break
        if mode == "offhand":
            offhand_resolved = True
        elif mode == "offhand_nick":
            nick_resolved = True
        elif attack_index == 0 and mode in {"primary", "ranged", "throw"}:
            trigger_weapon = (equipment.get("ranged") if mode == "ranged"
                              else (equipment.get("ranged") if actor_data.get("active_weapon_set") == "ranged"
                                    else equipment.get("main_hand")))
            trigger_def = item_definition(trigger_weapon) if trigger_weapon else {}
            budget["light_attack_attempted"] = True
            if "light" in (trigger_def.get("tags", []) or []):
                budget["light_attack_available"] = True
                budget["light_attack_weapon_id"] = trigger_weapon.get("id", id(trigger_weapon))
        if event.get("thrown"):
            thrown_item = deepcopy(
                actor_entry["data"].get("equipment", {}).get("main_hand"))
        budget["action"] = False
        budget.pop("additional_action_forbids_magic", None)
        if event.get("hit") and event.get("damage", 0) > 0 and uncanny_dodge:
            target_budget["reaction"] = False
            _log(combat, f"{target_entry['data'].get('name', target_id)} uses Uncanny Dodge and halves the damage.")
        if isinstance(actor_entry["data"].get("hidden"), dict):
            actor_entry["data"]["hidden"] = None
            actor_entry["data"]["sneaking"] = False
            actor_entry["data"]["stealth_check_total"] = None
            _log(combat, f"{actor_entry['data'].get('name', actor_id)} reveals their position.")
        if event.get("sneak_attack_damage"):
            combat["sneak_attack_used"][actor_id] = True
            if cunning_strike:
                _resolve_cunning_strike(
                    combat, actor_id, actor_entry["data"],
                    target_entry["data"], cunning_strike)
                actor_entry["data"].pop("pending_cunning_strike", None)
        if mode in {"ranged", "offhand", "offhand_nick"}:
            weapon = (equipment.get("ranged") if mode == "ranged" else
                      equipment.get("off_hand") if equipment.get("off_hand") and
                      item_definition(equipment["off_hand"]).get("category") == "weapon" else
                      equipment.get("ranged_offhand"))
            weapon_definition = item_definition(weapon) if weapon else {}
        else:
            weapon, weapon_definition, _ = selected_weapon(actor_entry["data"])
        if event.get("thrown"):
            weapon = actor_entry["data"].get("equipment", {}).get("main_hand")
            weapon_definition = item_definition(weapon) if weapon else {}
        if event.get("hit"):
            _apply_weapon_mastery(combat, actor_id, target_id, weapon)
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
            feature_note = (f" including {event['feature_bonus_damage']} bonus damage"
                            if event.get("feature_bonus_damage") else "")
            _log(combat, (f"{event['attacker']} {verdict} {event['target']} with "
                          f"{event['weapon']} (d20 {event['rolls']} = {event['total']}"
                          f"{defense}); {event['damage_rolls']} + modifier = "
                          f"{event['damage']} {event['damage_type']} damage"
                          f"{' (resistance)' if event.get('resisted') else ''}"
                          f"{sneak_note}{feature_note}."))
        else:
            graze_note = (f" Graze deals {event['graze_damage']} damage."
                          if event.get("graze_damage") else "")
            _log(combat, (f"{event['attacker']} misses {event['target']} with "
                          f"{event['weapon']} (d20 {event['rolls']} = {event['total']}"
                          f"{defense}).{graze_note}"))
            if event.get("graze_damage"):
                target_entry["downed"] = target_entry["data"].get("current_hp", 1) <= 0
                _emit_animation(combat, target_id,
                                "dead" if target_entry["downed"] else "hurt")
        if (event.get("hit") and not event.get("ranged")
                and (actor_entry["data"].get("weapon_masteries", {}) or {}).get(
                    (weapon or {}).get("template_id")) == "cleave"
                and _has_weapon_mastery(actor_entry["data"])
                and _cleave_available(combat, actor_id)):
            _resolve_cleave(combat, actor_id, target_id, weapon)
        for enemy in combat["actors"].values():
            if enemy["team"] == "enemies" and enemy["data"].get("current_hp", 1) <= 0:
                enemy["downed"] = True
    _remove_downed_from_order(combat)
    if offhand_resolved:
        budget["bonus_action"] = False
        budget["light_attack_available"] = False
    if nick_resolved:
        budget["nick_used"] = True
        budget["light_attack_available"] = False
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


def _opportunity_attacks_on_move(combat, mover_id, old_position, new_position):
    """Resolve one melee opportunity attack per eligible creature as a move ends."""
    mover = combat.get("actors", {}).get(mover_id)
    if not mover or mover["data"].get("disengaged"):
        return
    old_actor = {**mover, "x": old_position[0], "y": old_position[1]}
    new_actor = {**mover, "x": new_position[0], "y": new_position[1]}
    for attacker_id, attacker in list(combat.get("actors", {}).items()):
        if (attacker_id == mover_id or attacker.get("downed")
                or attacker.get("team") == mover.get("team")):
            continue
        budget = combat.setdefault("budgets", {}).get(attacker_id, {})
        if not budget.get("reaction", True):
            continue
        if _hidden_from(mover, attacker, combat.get("arena")):
            continue
        old_distance = edge_distance_feet(attacker, old_actor)
        new_distance = edge_distance_feet(attacker, new_actor)
        weapon, definition, _ = selected_weapon(attacker["data"])
        reach = (definition or {}).get("ranges", {}).get("melee", 5)
        if old_distance > reach or new_distance <= reach:
            continue
        if not _line_of_sight(attacker, mover, combat.get("arena")):
            continue
        distance = distance_feet(attacker, mover)
        budget["reaction"] = False
        event = resolve_attack(
            attacker["data"], mover["data"], distance,
            melee_distance_feet=old_distance,
            adjacent_distance_feet=old_distance,
            line_of_sight=True)
        if event.get("success"):
            _debug_log(combat, (
                f"Opportunity attack: {event.get('attacker')} vs {event.get('target')}; "
                f"d20 {event.get('rolls')} -> {event.get('natural')} + "
                f"attack modifier {event.get('attack_modifier', 0):+} = "
                f"{event.get('total')} vs AC {event.get('target_ac')}; "
                f"{'critical' if event.get('critical') else 'hit' if event.get('hit') else 'miss'}."))
            if event.get("hit"):
                _debug_log(combat, (f"Opportunity damage: formula "
                                    f"{event.get('damage_formula')}, rolls "
                                    f"{event.get('damage_rolls', [])}, ability modifier "
                                    f"{event.get('damage_modifier', 0):+} = "
                                    f"{event.get('damage')} {event.get('damage_type')}"))
        if not event.get("success"):
            budget["reaction"] = True
            continue
        mover["downed"] = bool(mover["data"].get("downed"))
        verdict = "hits" if event.get("hit") else "misses"
        suffix = (f" for {event['damage']} damage" if event.get("hit") else "")
        _log(combat, f"{event['attacker']} {verdict} {event['target']} with an opportunity attack{suffix}.")
        if event.get("hit"):
            _apply_weapon_mastery(combat, attacker_id, mover_id, weapon)
            if ((attacker["data"].get("weapon_masteries", {}) or {}).get(
                    (weapon or {}).get("template_id")) == "cleave"
                    and _has_weapon_mastery(attacker["data"])
                    and _cleave_available(combat, attacker_id)):
                _resolve_cleave(combat, attacker_id, mover_id, weapon)
        if mover["downed"]:
            _emit_animation(combat, mover_id, "dead")
            _log(combat, f"{mover['data'].get('name', mover_id)} is downed before moving.")
            return
