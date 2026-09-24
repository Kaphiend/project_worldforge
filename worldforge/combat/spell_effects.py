"""Apply data-defined spell and class-ability effects after their rolls resolve."""
from copy import deepcopy
from math import floor

from worldforge.content.classes import ABILITIES, CONDITIONS, SPELLS
from worldforge.combat.rules import armor_class, distance_feet, edge_distance_feet, proficiency_bonus, resolve_healing_effect
from worldforge.combat.conditions import apply_condition
from worldforge.core.dice import roll_d20, roll_dice
from worldforge.actors.factory import modifier


def _effects_for(definition, outcome=None):
    effects = definition.get("effects", [])
    if isinstance(effects, dict):
        if outcome not in effects:
            raise ValueError(f"No effect branch for outcome {outcome!r}")
        effects = effects[outcome]
    if not isinstance(effects, list):
        raise ValueError("Effect entries must be a list or outcome map")
    return effects


def _damage(target, amount):
    if not isinstance(target, dict):
        current = max(0, int(getattr(target, "current_hp", 0)) - amount)
        target.current_hp = current
        if current <= 0:
            target.downed = True
        return
    hp_key = "current_hp" if "current_hp" in target else "hp"
    target[hp_key] = max(0, int(target.get(hp_key, 1)) - amount)
    if target[hp_key] <= 0:
        target["downed"] = True


def _apply(effect, caster, target, source_id, *, critical=False):
    kind = effect.get("kind")
    if kind == "damage":
        rolled_amount, rolls = roll_dice(effect["formula"], critical=critical)
        amount = floor(rolled_amount * effect.get("multiplier", 1))
        _damage(target, amount)
        return {"kind": kind, "amount": amount, "rolled_amount": rolled_amount,
                "rolls": rolls,
                "damage_type": effect.get("damage_type", "untyped")}
    if kind == "healing":
        amount, rolls = roll_dice(effect["formula"])
        restored = resolve_healing_effect(target, effect, amount)
        return {"kind": kind, "amount": restored, "rolls": rolls,
                "revived": bool(effect.get("can_revive") and restored > 0)}
    if kind == "condition":
        instance = apply_condition(target, effect["condition_id"], source_id=source_id)
        return {"kind": kind, "condition": effect["condition_id"],
                "remaining_turns": instance.get("remaining_turns")}
    if kind == "heal_caster_from_damage":
        amount, rolls = roll_dice(effect["formula"])
        restored = resolve_healing_effect(
            caster, {"kind": "healing", "can_revive": False}, amount)
        return {"kind": "healing", "amount": restored, "rolls": rolls}
    if kind in {"next_weapon_hit_bonus", "armor_bonus", "movement_bonus"}:
        record = deepcopy(effect)
        record.update(source_id=source_id, remaining_turns=effect.get("duration_turns", 1))
        target.setdefault("active_effects", []).append(record)
        return {"kind": kind, "active": True}
    if kind == "send_message":
        return {"kind": kind, "range_feet": effect.get("range_feet", 0)}
    raise ValueError(f"Unsupported data effect primitive: {kind!r}")


def apply_spell_effects(spell_id, caster, target, *, outcome=None, critical=False):
    """Apply a spell's selected outcome; attack/save rolls are resolved separately."""
    definition = SPELLS[spell_id]
    if target is None:
        target = caster
    applied = []
    for effect in _effects_for(definition, outcome):
        applied.append(_apply(effect, caster, target, spell_id, critical=critical))
    return applied


def apply_ability_effects(ability_id, actor, target=None):
    """Apply a class ability's data primitives to its chosen target."""
    definition = ABILITIES[ability_id]
    target = actor if target is None else target
    return [_apply(effect, actor, target, ability_id)
            for effect in definition.get("effects", [])]


def _actor_classes(actor):
    classes = actor.get("classes", [])
    names = [entry.get("name") for entry in classes if entry.get("name")]
    if not names and actor.get("char_class"):
        names = [actor["char_class"]]
    return names


def _spellcasting_modifier(caster, casting_class):
    from worldforge.content.classes import CLASSES

    ability = CLASSES[casting_class].get("spellcasting_ability")
    if not ability:
        raise ValueError(f"{casting_class} has no spellcasting ability configured")
    return modifier(caster.get("abilities", {}).get(ability, 10)), ability


def _target_save_modifier(target, ability):
    from worldforge.combat.rules import proficiency_bonus
    from worldforge.actors.factory import item_attribute_total, _unique_equipped_items

    abilities = target.get("abilities", {})
    save_proficiencies = target.get("saves", [])
    equipment = target.get("equipment", {}) or {}
    gear_bonus = sum(item_attribute_total(item, "saving_throw_bonus")
                     for item in _unique_equipped_items(equipment))
    return modifier(abilities.get(ability, 10)) + (
        proficiency_bonus(target) if ability in save_proficiencies else 0
    ) + gear_bonus


def resolve_spell(spell_id, caster, targets=None, *, casting_class=None,
                  line_of_sight=True, target_position=None, from_consumable=False):
    """Resolve an attack/save spell, then apply its data-driven effects.

    Casting actions and spell-point expenditure are handled by the caller.
    Targets can be one actor or a list. For area spells, the caller supplies
    ``target_position`` for range validation and the actors in the area.
    """
    spell = SPELLS[spell_id]
    if not from_consumable and spell_id not in (caster.get("known_spells", []) or []):
        return {"success": False, "message": "That spell is not learned."}
    target_info = spell.get("targeting", {})
    mode = target_info.get("mode")
    if mode == "self":
        targets = [caster]
    elif targets is None:
        return {"success": False, "message": "Choose a target."}
    if isinstance(targets, dict):
        targets = [targets]

    if not from_consumable:
        eligible_classes = [name for name in _actor_classes(caster)
                            if name in spell.get("classes", [])]
        if casting_class:
            if casting_class not in eligible_classes:
                return {"success": False, "message": "That class cannot cast this spell."}
        elif not eligible_classes:
            return {"success": False, "message": "The actor has no class access to this spell."}
        else:
            casting_class = eligible_classes[0]

    if target_info.get("requires_line_of_sight", False) and not line_of_sight:
        return {"success": False, "message": "No clear line of sight."}
    max_range = target_info.get("range_feet")
    if max_range is not None:
        point = target_position
        if point is not None:
            distance = distance_feet(caster, {"x": point[0], "y": point[1],
                                              "width": 0, "height": 0})
        elif targets:
            distance = max(edge_distance_feet(caster, target) for target in targets)
        else:
            distance = 0
        if distance > max_range:
            return {"success": False, "message": "Target is outside spell range."}

    resolution = spell.get("resolution", {})
    kind = resolution.get("kind", "automatic")
    results = []
    for target in targets:
        outcome = None
        critical = False
        roll_data = None
        if kind == "spell_attack":
            spell_mod, ability = _spellcasting_modifier(caster, casting_class)
            natural, dice = roll_d20()
            total = natural + spell_mod + proficiency_bonus(caster)
            hit = natural == 20 or (natural != 1 and total >= armor_class(target))
            critical = natural == 20
            outcome = "hit" if hit else "miss"
            roll_data = {"natural": natural, "dice": dice, "total": total,
                         "ability": ability, "target_ac": armor_class(target),
                         "critical": critical}
        elif kind == "saving_throw":
            ability = resolution["ability"]
            spell_mod, casting_ability = _spellcasting_modifier(caster, casting_class)
            dc = 8 + spell_mod + proficiency_bonus(caster)
            natural, dice = roll_d20()
            total = natural + _target_save_modifier(target, ability)
            outcome = "successful_save" if total >= dc else "failed_save"
            roll_data = {"natural": natural, "dice": dice, "total": total,
                         "ability": ability, "casting_ability": casting_ability,
                         "dc": dc}
        elif kind in {"healing", "self_enchantment", "utility", "automatic"}:
            outcome = None
        else:
            return {"success": False,
                    "message": f"Unsupported spell resolution kind: {kind}."}

        applied = apply_spell_effects(
            spell_id, caster, target, outcome=outcome, critical=critical)
        results.append({"target": target.get("name", "Target"),
                        "outcome": outcome, "roll": roll_data, "effects": applied})
    return {"success": True, "spell": spell_id, "results": results}
