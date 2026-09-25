"""Spell and class ability execution during combat."""
import math

from worldforge.combat.rules import edge_distance_feet
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
    if not budget.get('action'):
        _reject_action(combat, 'Action already used this turn.', actor_id)
        return False
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
    target_entry = combat['actors'].get(target_id) if target_id else None
    mode = target_info.get('mode')
    if mode not in ('self',) and not target_entry:
        _reject_action(combat, 'Invalid target: select an available target first.', actor_id)
        return False
    if target_entry and target_entry["data"].get("withdrawn"):
        _reject_action(combat, "That character has left the fight.", target_id)
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
    budget['action'] = False
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
    if target_entry and _hidden_from(actor_entry, target_entry,
                                     combat.get("arena")):
        _reject_action(combat, "You have not found that hidden target.", target_id)
        return False
    if target_entry and target_info.get('range_feet') is not None:
        if edge_distance_feet(actor_entry, target_entry) > target_info['range_feet']:
            _reject_action(combat, 'Target is outside ability range.', target_id)
            return False
    budget = combat['budgets'][actor_id]
    cost = ability.get('action_cost', 'action')
    if not budget.get(cost, False):
        _reject_action(combat, f"{cost.replace('_', ' ').title()} already used this turn.", actor_id)
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
    budget[cost] = False
    if uses_limit is not None:
        actor_uses[ability_id] = uses_so_far + 1
    if resource_key:
        actor_data.setdefault("class_resources", {})[resource_key] -= resource_amount
    _log(combat, f"{actor_data.get('name', 'Actor')} uses {ability['name']}.")
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

