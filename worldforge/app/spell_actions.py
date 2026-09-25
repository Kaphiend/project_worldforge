"""Spell and class ability execution during combat."""
import math

from worldforge.actors.factory import item_definition
from worldforge.combat.rules import edge_distance_feet, speed_feet
from worldforge.combat.spell_effects import apply_ability_effects, resolve_spell
from worldforge.content.classes import ABILITIES, SPELLS
from worldforge.core.progression import (pact_slot_maxima, spell_slot_maxima,
                                         spell_source_class)
from worldforge.app.combat_flow import (
    _animate_hp_changes, _award_combat_xp, _debug_log, _log, _reject_action,
    _remove_downed_from_order, _restore_revived_order,
)
from worldforge.app.world import PIXELS_PER_FOOT, _hidden_from, _line_of_sight
from worldforge.app.rendering import _capture_hp


def _do_spell(combat, actor_id, spell_id, target_id=None, slot_level=None,
              slot_pool=None):
    actor_entry = combat['actors'].get(actor_id)
    if not actor_entry or actor_entry['downed']:
        return False
    spell = SPELLS.get(spell_id)
    if not spell:
        _reject_action(combat, 'Unknown spell.', actor_id)
        return False
    budget = combat['budgets'][actor_id]
    caster = actor_entry['data']
    prepared_spells = caster.get("prepared_spells", [])
    actor_classes = {item.get("name") for item in caster.get("classes", []) or []
                     if item.get("name")}
    if caster.get("char_class"):
        actor_classes.add(caster["char_class"])
    if not actor_classes.intersection(spell.get("classes", [])):
        _reject_action(combat, 'Your class cannot cast this spell.', actor_id)
        return False
    if spell_id not in prepared_spells:
        _reject_action(combat, f"{spell['name']} is not prepared.", actor_id)
        return False
    casting_class = spell_source_class(caster, spell_id)
    spell_level = max(0, int(spell.get("level", spell.get("tier", 0)) or 0))
    used_slot_level = 0
    requested_pool = slot_pool
    slot_pool = None
    if spell_level > 0:
        current_slots = caster.get("spell_slots", {}) or {}
        maxima = spell_slot_maxima(caster)
        available_levels = [int(level) for level, maximum in maxima.items()
                            if int(level) >= spell_level
                            and int(current_slots.get(level, 0) or 0) > 0]
        requested_slot = int(slot_level) if slot_level is not None else None
        pact_count, pact_level = pact_slot_maxima(caster)
        pact_available = (
            int(caster.get("pact_slots", 0) or 0) > 0
            and pact_count > 0 and pact_level >= spell_level
            and (requested_slot is None or requested_slot == pact_level)
        )
        if requested_pool == "spell_slots":
            if requested_slot in available_levels:
                used_slot_level = requested_slot
                slot_pool = "spell_slots"
        elif requested_pool == "pact_slots":
            if pact_available:
                used_slot_level = pact_level
                slot_pool = "pact_slots"
        elif requested_slot is not None:
            if requested_slot in available_levels:
                used_slot_level = requested_slot
                slot_pool = "spell_slots"
            elif pact_available:
                used_slot_level = pact_level
                slot_pool = "pact_slots"
        elif available_levels:
            used_slot_level = min(available_levels)
            slot_pool = "spell_slots"
        elif pact_available:
            used_slot_level = pact_level
            slot_pool = "pact_slots"
        if not slot_pool:
            _reject_action(combat, f"No available spell slot for {spell['name']}.", actor_id)
            return False
    target_info = spell.get('targeting', {})
    action_cost = spell.get('casting_time', 'action')
    if action_cost not in ('action', 'bonus_action'):
        action_cost = 'action'
    if (action_cost == "bonus_action"
            and budget.get("spell_cast_this_turn")):
        _reject_action(combat, "A Bonus Action spell prevents casting another spell this turn.", actor_id)
        return False
    if (action_cost == "action" and spell_level > 0
            and budget.get("bonus_action_spell_cast_this_turn")):
        _reject_action(combat, "After a Bonus Action spell, only an action cantrip can be cast this turn.", actor_id)
        return False
    if action_cost == "action" and budget.get("additional_action_forbids_magic"):
        _reject_action(combat, "Action Surge cannot be used to take the Magic action.", actor_id)
        return False
    if not budget.get(action_cost):
        _reject_action(combat, f"{action_cost.replace('_', ' ').title()} already used this turn.", actor_id)
        return False
    target_entry = combat['actors'].get(target_id) if target_id else None
    mode = target_info.get('mode')
    if mode not in ('self',) and not target_entry:
        _reject_action(combat, 'Invalid target: select an available target first.', actor_id)
        return False
    if target_entry and target_entry["data"].get("withdrawn"):
        _reject_action(combat, "That character has left the fight.", target_id)
        return False
    if target_entry and mode == 'one_ally' and target_entry['team'] != actor_entry['team']:
        _reject_action(combat, 'Choose an ally for this spell.', target_id)
        return False
    if target_entry and _hidden_from(actor_entry, target_entry,
                                     combat.get("arena")):
        _reject_action(combat, "You have not found that hidden target.", target_id)
        return False
    targets = [target_entry['data']] if target_entry else None
    point = None
    if mode == 'small_area':
        point = (target_entry['x'] + target_entry['width'] / 2,
                 target_entry['y'] + target_entry['height'] / 2)
        radius = int(target_info.get('radius_feet', 0)) * PIXELS_PER_FOOT
        targets = [entry['data'] for entry in combat['actors'].values()
                   if not entry['data'].get("withdrawn")
                   and (not target_info.get('exclude_caster') or entry is not actor_entry)
                   and math.hypot(entry['x'] + entry['width'] / 2 - point[0],
                                 entry['y'] + entry['height'] / 2 - point[1]) <= radius]
    if mode == 'self':
        targets = [caster]
    hp_before = _capture_hp(combat)
    line_of_sight = (True if mode == 'self' or not target_entry else
                     _line_of_sight(actor_entry, target_entry, combat.get('arena')))
    result = resolve_spell(spell_id, caster, targets,
                           target_position=point, line_of_sight=line_of_sight,
                           casting_class=casting_class,
                           cast_level=used_slot_level or spell_level)
    if not result.get('success'):
        _reject_action(combat, result.get('message', 'Spell failed.'),
                       target_id or actor_id)
        return False
    budget[action_cost] = False
    budget["spell_cast_this_turn"] = True
    if action_cost == "bonus_action":
        budget["bonus_action_spell_cast_this_turn"] = True
    if action_cost == "action":
        budget.pop("additional_action_forbids_magic", None)
    if used_slot_level:
        if slot_pool == "spell_slots":
            caster["spell_slots"][str(used_slot_level)] -= 1
            remaining = caster["spell_slots"][str(used_slot_level)]
            _log(combat, (f"{caster.get('name', 'Caster')} spends one level {used_slot_level} "
                          f"spell slot ({remaining} remaining)."))
        else:
            caster["pact_slots"] = max(0, int(caster.get("pact_slots", 0) or 0) - 1)
            _log(combat, (f"{caster.get('name', 'Caster')} spends one level {used_slot_level} "
                          f"Pact Magic slot ({caster['pact_slots']} remaining)."))
    else:
        _log(combat, f"{caster.get('name', 'Caster')} casts {spell['name']} as a cantrip.")
    for item in result['results']:
        details = []
        roll = item.get('roll')
        if roll:
            details.append(f"roll {roll.get('natural')} = {roll.get('total')}")
        for effect in item.get('effects', []):
            if effect.get('kind') == 'damage':
                details.append(f"{effect['amount']} {effect.get('damage_type', 'untyped')} damage")
            elif effect.get('kind') == 'healing':
                details.append(f"{effect['amount']} healing")
            elif effect.get('kind') == 'condition':
                details.append(effect['condition'].replace('_', ' '))
        suffix = '; ' + ', '.join(details) if details else ''
        _log(combat, f"{caster.get('name', 'Caster')} casts {spell['name']} on {item['target']}{suffix}.")
        roll = item.get("roll")
        if roll:
            if roll.get("target_ac") is not None:
                equation = (f"d20 {roll.get('dice')} -> {roll.get('natural')} + "
                            f"spell modifier {roll.get('modifier', 0):+} + "
                            f"proficiency {roll.get('proficiency', 0):+} = "
                            f"{roll.get('total')} vs AC {roll.get('target_ac')}.")
            else:
                equation = (f"d20 {roll.get('dice')} -> {roll.get('natural')} + "
                            f"save modifier {roll.get('modifier', 0):+} = "
                            f"{roll.get('total')} vs DC {roll.get('dc', '?')} "
                            f"(8 + spell modifier {roll.get('spell_modifier', 0):+} + "
                            f"proficiency {roll.get('proficiency', 0):+}).")
            _debug_log(combat, f"{spell['name']} {roll.get('ability', 'spell')} roll: {equation}")
        for effect in item.get("effects", []):
            if effect.get("rolls") is not None:
                bonuses = []
                if effect.get("spell_modifier"):
                    bonuses.append(f"spell modifier {effect['spell_modifier']:+}")
                if effect.get("class_level_bonus"):
                    bonuses.append(f"class level +{effect['class_level_bonus']}")
                _debug_log(combat, (f"{spell['name']} {effect.get('kind')} "
                                    f"{effect.get('formula', 'dice')}: "
                                    f"rolls {effect.get('rolls')}; "
                                    f"rolled {effect.get('rolled_amount', effect.get('amount'))}"
                                    f"{' + ' + ' + '.join(bonuses) if bonuses else ''}; "
                                    f"calculated {effect.get('calculated_amount', effect.get('amount'))}; "
                                    f"applied {effect.get('amount')}."))
    for entry in combat['actors'].values():
        entry['downed'] = bool(
            entry['data'].get('downed', False)
            or entry['data'].get('current_hp', 1) <= 0)
    _remove_downed_from_order(combat)
    _restore_revived_order(combat)
    _animate_hp_changes(combat, hp_before)
    enemies = [entry for entry in combat['actors'].values()
               if entry['team'] == 'enemies']
    if enemies and all(entry['downed'] for entry in enemies):
        combat['active'] = False
        _log(combat, 'All enemies defeated. Combat ended.')
        combat["result"] = {"outcome": "victory", "message": combat.get("scenario", {}).get("victory", "Encounter complete.")}
        _award_combat_xp(combat)
    return True

def _do_ability(combat, actor_id, ability_id, target_id=None):
    actor_entry = combat['actors'].get(actor_id)
    ability = ABILITIES.get(ability_id)
    if not actor_entry or actor_entry['downed'] or not ability:
        _reject_action(combat, 'Ability unavailable to this actor.', target_id or actor_id)
        return False
    if ability.get("cunning_strike_selector"):
        _reject_action(combat, "Choose a Cunning Strike option from the selection buttons.", actor_id)
        return False
    actor_data = actor_entry['data']
    actor_classes = {item.get("name") for item in actor_data.get("classes", []) or []
                     if item.get("name")}
    if actor_data.get("char_class"):
        actor_classes.add(actor_data["char_class"])
    if not actor_classes.intersection(ability.get("classes", [])):
        _reject_action(combat, "Your class cannot use this ability.", actor_id)
        return False
    required_level = int(ability.get("prerequisite_class_level", 0) or 0)
    class_levels = {item.get("name"): int(item.get("level", 0) or 0)
                    for item in actor_data.get("classes", []) or []}
    if actor_data.get("char_class"):
        class_levels.setdefault(actor_data["char_class"],
                                int(actor_data.get("level", 1) or 1))
    if required_level and max(
            (class_levels.get(class_id, 0)
             for class_id in ability.get("classes", [])), default=0) < required_level:
        _reject_action(combat, f"You need class level {required_level} to use {ability['name']}.", actor_id)
        return False
    required_feature = ability.get("requires_feature")
    if required_feature and required_feature not in set(
            actor_data.get("class_features", []) or []):
        _reject_action(combat, f"You must learn {required_feature.replace('_', ' ').title()} first.", actor_id)
        return False
    if ability_id not in actor_data.get('known_abilities', []):
        _reject_action(combat, 'That ability is not available to this character.', actor_id)
        return False
    if ability.get("sneak_attack_toggle"):
        enabled = not bool(actor_data.get("sneak_attack_enabled", True))
        actor_data["sneak_attack_enabled"] = enabled
        state = "enabled" if enabled else "disabled"
        _log(combat, f"{actor_data.get('name', actor_id)} {state} Sneak Attack.")
        _debug_log(combat, f"Sneak Attack rider toggle is now {state}.")
        return True
    uses_limit = ability.get("uses_per_combat", 1)
    actor_uses = combat.setdefault("ability_uses", {}).setdefault(actor_id, {})
    uses_so_far = int(actor_uses.get(ability_id, 0))
    if uses_limit is not None and uses_so_far >= max(0, int(uses_limit)):
        _reject_action(combat, f"{ability['name']} has already been used this fight.", actor_id)
        return False
    resource_cost = ability.get("resource_cost")
    resource_key = None
    resource_amount = 0
    if resource_cost:
        resource_class = resource_cost.get("class_id", actor_data.get("char_class", ""))
        resource_id = resource_cost.get("resource_id", "")
        resource_key = f"{resource_class}.{resource_id}"
        resource_amount = max(1, int(resource_cost.get("amount", 1)))
        available = int(actor_data.get("class_resources", {}).get(resource_key, 0))
        if available < resource_amount:
            _reject_action(combat, f"Not enough {resource_id.replace('_', ' ')} points.", actor_id)
            return False
    target_info = ability.get('targeting', {})
    target_entry = combat['actors'].get(target_id) if target_id else None
    if target_info and target_info.get('mode') != 'self' and not target_entry:
        _reject_action(combat, 'Invalid target: select an available target first.', actor_id)
        return False
    if target_entry and target_entry["data"].get("withdrawn"):
        _reject_action(combat, "That character has left the fight.", target_id)
        return False
    if target_entry and target_info.get("target_team") == "enemies" and target_entry.get("team") != "enemies":
        _reject_action(combat, "Choose an enemy target.", target_id)
        return False
    if target_entry and _hidden_from(actor_entry, target_entry,
                                     combat.get("arena")):
        _reject_action(combat, "You have not found that hidden target.", target_id)
        return False
    if target_entry and target_info.get('range_feet') is not None:
        if edge_distance_feet(actor_entry, target_entry) > target_info['range_feet']:
            _reject_action(combat, 'Target is outside ability range.', target_id)
            return False
    budget = combat['budgets'][actor_id]
    if ability.get("requires_stationary") and budget.get("movement_used", 0) > 0:
        _reject_action(combat, "You cannot use this ability after moving this turn.", actor_id)
        return False
    cost = ability.get('action_cost', 'action')
    turn_use_key = f"ability_{ability_id}_used_this_turn"
    if ability.get("once_per_turn") and budget.get(turn_use_key):
        _reject_action(combat, f"{ability['name']} can be used only once per turn.", actor_id)
        return False
    if cost != "free" and not budget.get(cost, False):
        _reject_action(combat, f"{cost.replace('_', ' ').title()} already used this turn.", actor_id)
        return False
    if ability.get("requires_action_spent") and budget.get("action", False):
        _reject_action(combat, "Use your action before this ability.", actor_id)
        return False
    if ability.get("requires_not_heavy_armor"):
        armor = item_definition((actor_data.get("equipment", {}) or {}).get("chest") or {})
        if armor.get("category") == "heavy":
            _reject_action(combat, f"{ability['name']} cannot be used in heavy armor.", actor_id)
            return False
    if ability.get("unique_active") and any(
            effect.get("source_id") == ability_id
            for effect in actor_data.get("active_effects", []) or []):
        _reject_action(combat, f"{ability['name']} is already active.", actor_id)
        return False
    if ability.get("attack_sequence") and target_entry and (
            target_entry.get("downed") or target_entry["data"].get("downed")):
        _reject_action(combat, "A downed target cannot be attacked.", target_id)
        return False
    try:
        hp_before = _capture_hp(combat)
        effect_target = (target_entry['data']
                         if target_entry and target_info.get('mode') != 'self'
                         else actor_data)
        effects = apply_ability_effects(ability_id, actor_data, effect_target)
    except (KeyError, ValueError) as exc:
        _reject_action(combat, f'Ability unavailable: {exc}', target_id or actor_id)
        return False
    # Movement bonuses belong in this turn's budget, not the persistent
    # effect list. Keep Disengage as a turn-scoped marker for the future
    # opportunity-attack resolver.
    actor_data["active_effects"] = [
        effect for effect in actor_data.get("active_effects", []) or []
        if not (effect.get("source_id") == ability_id
                and effect.get("kind") == "movement_bonus")]
    if any(effect.get("kind") == "disengage" for effect in effects):
        actor_data["disengaged"] = True
    if ability_id == "fighter_second_wind":
        fighter_level = max((int(entry.get("level", 0) or 0)
                             for entry in actor_data.get("classes", []) or []
                             if entry.get("name") == "fighter"), default=0)
        if fighter_level == 0 and actor_data.get("char_class") == "fighter":
            fighter_level = int(actor_data.get("level", 1) or 1)
        if fighter_level >= 5:
            from worldforge.combat.rules import speed_feet
            actor_data["disengaged"] = True
            budget["movement"] = int(budget.get("movement", 0)) + speed_feet(actor_data) // 2
    if ability.get("cunning_strike_option"):
        actor_data["pending_cunning_strike"] = ability["cunning_strike_option"]
    if cost != "free":
        budget[cost] = False
        if cost == "action":
            budget.pop("additional_action_forbids_magic", None)
    if ability.get("once_per_turn"):
        budget[turn_use_key] = True
    if uses_limit is not None:
        actor_uses[ability_id] = uses_so_far + 1
    if resource_key:
        actor_data.setdefault("class_resources", {})[resource_key] -= resource_amount
    details = [f"{effect['amount']} healing" for effect in effects
               if effect.get("kind") == "healing"]
    if any(effect.get("kind") == "restore_action" for effect in effects):
        details.append("action restored")
    suffix = f" ({'; '.join(details)})" if details else ""
    _log(combat, f"{actor_data.get('name', 'Actor')} uses {ability['name']}{suffix}.")
    if ability.get("attack_sequence"):
        from worldforge.app.attack_actions import _do_attack

        original_action = budget.get("action", False)
        sequence = ability["attack_sequence"]
        for _ in range(max(1, int(sequence.get("count", 1)))):
            target = combat["actors"].get(target_id)
            if not target or target.get("downed") or target["data"].get("current_hp", 1) <= 0:
                break
            budget["action"] = True
            _do_attack(combat, actor_id, target_id,
                       attack_mode=sequence.get("mode", "unarmed"))
            budget["action"] = original_action
        _animate_hp_changes(combat, hp_before)
        return True
    if any(effect.get("kind") == "restore_action" for effect in effects):
        budget["action"] = True
        if ability.get("forbid_magic_action"):
            budget["additional_action_forbids_magic"] = True
    for effect in effects:
        if effect.get("rolls") is not None:
            _debug_log(combat, (f"{ability['name']} {effect.get('kind')} roll: "
                                f"dice {effect.get('rolls')}; "
                                f"raw {effect.get('rolled_amount', effect.get('amount'))}, "
                                f"final {effect.get('amount')}."))
        if effect.get("kind") == "movement_bonus":
            multiplier = max(1.0, float(effect.get("multiplier", 1) or 1))
            bonus = int(effect.get("feet", 0) or 0)
            bonus += int(speed_feet(actor_data) * (multiplier - 1))
            budget["movement"] = int(budget.get("movement", 0)) + bonus
        elif effect.get("kind") == "end_movement":
            budget["movement"] = 0
    _animate_hp_changes(combat, hp_before)
    enemies = [entry for entry in combat["actors"].values()
               if entry["team"] == "enemies"]
    if enemies and all(entry["downed"] or entry["data"].get("current_hp", 1) <= 0
                       for entry in enemies):
        combat["active"] = False
        combat["result"] = {"outcome": "victory", "message": combat.get("scenario", {}).get("victory", "Encounter complete.")}
        _log(combat, "All enemies defeated. Combat ended.")
        _award_combat_xp(combat)
    return bool(effects) or not ability.get('effects')
