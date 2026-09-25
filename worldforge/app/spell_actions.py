"""Spell and class ability execution during combat."""
import math

from worldforge.actors.factory import item_definition
from worldforge.combat.rules import edge_distance_feet, speed_feet
from worldforge.combat.spell_effects import apply_ability_effects, resolve_spell
from worldforge.content.classes import ABILITIES, SPELLS
from worldforge.core.progression import spell_point_max
from worldforge.app.combat_flow import (
    _animate_hp_changes, _award_combat_xp, _log, _reject_action,
    _remove_downed_from_order, _restore_revived_order,
)
from worldforge.app.world import PIXELS_PER_FOOT, _hidden_from, _line_of_sight
from worldforge.app.rendering import _capture_hp


def _do_spell(combat, actor_id, spell_id, target_id=None):
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
    spell_cost = max(0, int(spell.get("spell_point_cost", 1)))
    spell_points = int(caster.get("spell_points", 0) or 0)
    if spell_points < spell_cost:
        _reject_action(
            combat,
            f"Not enough spell points for {spell['name']} ({spell_cost} needed; {spell_points} available).",
            actor_id)
        return False
    target_info = spell.get('targeting', {})
    action_cost = spell.get('casting_time', 'action')
    if action_cost not in ('action', 'bonus_action'):
        action_cost = 'action'
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
                           target_position=point, line_of_sight=line_of_sight)
    if not result.get('success'):
        _reject_action(combat, result.get('message', 'Spell failed.'),
                       target_id or actor_id)
        return False
    budget[action_cost] = False
    caster["spell_points"] = spell_points - spell_cost
    remaining_points = caster["spell_points"]
    if spell_cost:
        _log(combat, (f"{caster.get('name', 'Caster')} spends {spell_cost} spell point"
                      f"{'s' if spell_cost != 1 else ''} ({remaining_points}/"
                      f"{spell_point_max(caster)} left)."))
    else:
        _log(combat, f"{caster.get('name', 'Caster')} casts {spell['name']} without spending spell points.")
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
    if ability.get("cunning_strike_option"):
        actor_data["pending_cunning_strike"] = ability["cunning_strike_option"]
    if cost != "free":
        budget[cost] = False
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
    for effect in effects:
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
