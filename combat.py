"""Data-driven combat calculations and turn-order helpers."""
import math

from classes import EQUIPMENT_ITEMS, RACES
from dice import roll_d20, roll_dice, scale_dice_count
from factory import (effective_max_hp, item_attribute_total, modifier,
                     _unique_equipped_items)
from conditions import consume_condition_use, has_condition


def _value(actor, key, default=None):
    return actor.get(key, default) if isinstance(actor, dict) else getattr(actor, key, default)


def _equipment(actor):
    return _value(actor, "equipment", {}) or {}


def _definition(item):
    if not item:
        return {}
    return EQUIPMENT_ITEMS.get(item.get("template_id"), item)


def _is_weapon(item):
    return _definition(item).get("category") == "weapon"


def speed_feet(actor):
    explicit_speed = _value(actor, "speed")
    if isinstance(explicit_speed, (int, float)):
        return explicit_speed
    race = _value(actor, "race", "human")
    if race != "half-breed":
        return RACES.get(race, {}).get("speed", 30)
    parent_speeds = [RACES.get(name, {}).get("speed", 30)
                     for name in (_value(actor, "parent_races", []) or [])]
    if len(parent_speeds) == 2 and parent_speeds[0] == parent_speeds[1]:
        return parent_speeds[0]
    return 30


def armor_class(actor):
    equipment = _equipment(actor)
    armor = _definition(equipment.get("chest"))
    abilities = _value(actor, "abilities", {}) or {}
    dexterity = modifier(abilities.get("dexterity", 10))
    category = armor.get("category", "unarmored")
    base = armor.get("base_ac", 10)
    if category == "heavy":
        dexterity = 0
    elif category == "medium":
        dexterity = min(dexterity, armor.get("dexterity_bonus_cap", 2))
    shield_bonus = 2 if any(
        _definition(equipment.get(slot)).get("category") == "shield"
        for slot in ("main_hand", "off_hand")
    ) else 0
    item_bonus = sum(item_attribute_total(item, "armor_class_bonus")
                     for item in _unique_equipped_items(equipment))
    temporary_bonus = sum(
        int(effect.get("amount", 0)) for effect in (_value(actor, "active_effects", []) or [])
        if effect.get("kind") == "armor_bonus"
    )
    return base + dexterity + shield_bonus + temporary_bonus + item_bonus


def initiative_for(actor):
    dex = modifier((_value(actor, "abilities", {}) or {}).get("dexterity", 10))
    natural, dice = roll_d20()
    return {"total": natural + dex, "natural": natural, "dexterity": dex}


def _proficient(actor, definition):
    weapon_class = definition.get("weapon_class")
    proficiencies = _value(actor, "weapon_prof", []) or []
    if _value(actor, "char_class", "") == "warlock" and definition.get("weapon_family") == "sword":
        return True
    return weapon_class in proficiencies


def proficiency_bonus(actor):
    level = max(1, int(_value(actor, "level", 1) or 1))
    return 2 + (level - 1) // 4


def apply_healing(target, amount, *, can_revive=False):
    """Apply a resolved healing amount; revival is an explicit effect tag.

    ``amount`` is supplied by the spell/consumable resolver so dice, costs, and
    other modifiers stay data-driven. Ordinary healing cannot affect a downed
    actor; an effect marked ``can_revive`` can restore HP and clear that state.
    Returns the number of hit points actually restored.
    """
    if amount <= 0:
        return 0
    current_hp = int(_value(target, "current_hp", _value(target, "hp", 0)) or 0)
    downed = bool(_value(target, "downed", False)) or current_hp <= 0
    if downed and not can_revive:
        return 0
    max_hp = effective_max_hp(target)
    new_hp = min(max_hp, current_hp + int(amount))
    if isinstance(target, dict):
        hp_key = "current_hp" if "current_hp" in target else "hp"
        target[hp_key] = new_hp
        target["downed"] = new_hp <= 0
    else:
        target.current_hp = new_hp
        target.downed = new_hp <= 0
    return new_hp - current_hp


def resolve_healing_effect(target, effect_data, amount):
    """Apply one spell's already-rolled healing amount and effect tags.

    The roll itself belongs to that spell's own formula; this helper only
    applies the result and handles the optional revival effect.
    """
    tags = set(effect_data.get("effect_tags", []))
    is_healing = "healing" in tags or effect_data.get("kind") == "healing"
    if not is_healing:
        raise ValueError("Effect data does not include the healing tag.")
    can_revive = effect_data.get("can_revive", "can_revive" in tags)
    return apply_healing(target, amount, can_revive=can_revive)


def selected_weapon(actor):
    equipment = _equipment(actor)
    ranged = _value(actor, "active_weapon_set", "melee") == "ranged"
    weapon = equipment.get("ranged") if ranged else equipment.get("main_hand")
    if not _is_weapon(weapon) and ranged:
        weapon = equipment.get("main_hand")
        ranged = False
    if not _is_weapon(weapon):
        return None, None, False
    definition = _definition(weapon)
    offhand = equipment.get("off_hand")
    main = equipment.get("main_hand")
    dual_wield = (
        not ranged and offhand and _is_weapon(offhand)
        and main and offhand.get("id") != main.get("id")
    )
    return weapon, definition, dual_wield


def _distance_disadvantage(definition, distance, ranged, adjacent_distance=None):
    if not ranged:
        return False
    ranges = definition.get("ranges", {})
    normal = ranges.get("normal", float("inf"))
    if distance > normal or (adjacent_distance if adjacent_distance is not None else distance) <= 5:
        return True
    # A second field often appears in content as a legacy long-range cap;
    # the requested rule permits attempts beyond it, still with disadvantage.
    return False


def attack(actor, target, distance_feet, *, melee_distance_feet=None,
           adjacent_distance_feet=None, line_of_sight=True,
           attack_mode="primary"):
    """Resolve a primary weapon attack or a separately selected thrown attack.

    ``primary`` always uses the selected weapon set and never auto-throws a
    thrown-tagged hand weapon. ``throw`` explicitly uses the main-hand weapon
    and is only legal for a template tagged ``thrown``.
    """
    equipment = _equipment(actor)
    thrown_attack = attack_mode == "throw"
    if thrown_attack:
        weapon = equipment.get("main_hand")
        definition = _definition(weapon)
        dual_wield = False
        if not _is_weapon(weapon) or "thrown" not in definition.get("tags", []):
            return {"kind": "attack", "success": False,
                    "message": "Your main-hand weapon cannot be thrown."}
    elif attack_mode == "ranged":
        weapon = equipment.get("ranged")
        definition = _definition(weapon)
        dual_wield = False
        if not _is_weapon(weapon):
            return {"kind": "attack", "success": False,
                    "message": "No ranged weapon is equipped."}
    else:
        weapon, definition, dual_wield = selected_weapon(actor)
    if weapon is None:
        return {"kind": "attack", "success": False, "message": "No attack weapon is equipped."}
    ranged = (thrown_attack or attack_mode == "ranged" or
              (_value(actor, "active_weapon_set", "melee") == "ranged"
               and weapon == equipment.get("ranged")))
    ranges = definition.get("ranges", {})
    reach = ranges.get("melee", 5)
    if thrown_attack:
        ranges = {"normal": ranges.get("thrown_normal", 0),
                  "long": ranges.get("thrown_long", 0)}
    melee_distance = distance_feet if melee_distance_feet is None else melee_distance_feet
    if ranged:
        if not line_of_sight:
            return {"kind": "attack", "success": False, "message": "No clear line of sight."}
    elif melee_distance > reach:
        return {"kind": "attack", "success": False, "message": "Target is outside melee reach."}

    abilities = _value(actor, "abilities", {}) or {}
    ability = "dexterity" if ranged or dual_wield else "strength"
    ability_mod = modifier(abilities.get(ability, 10))
    proficient = _proficient(actor, definition)
    proficiency = proficiency_bonus(actor) if proficient else 0
    weapon_attack_bonus = item_attribute_total(weapon, "weapon_attack_bonus")
    attack_definition = definition
    if thrown_attack:
        attack_definition = dict(definition, ranges=ranges)
    disadvantage = (_distance_disadvantage(
        attack_definition, distance_feet, ranged, adjacent_distance_feet)
        or has_condition(actor, "off_balance"))
    natural, dice = roll_d20(-1 if disadvantage else 0)
    if has_condition(actor, "off_balance"):
        consume_condition_use(actor, "off_balance")
    critical = natural == 20
    target_ac = armor_class(target)
    total = natural + ability_mod + proficiency + weapon_attack_bonus
    hit = critical or (natural != 1 and total >= target_ac)
    event = {
        "kind": "attack", "success": True, "attacker": _value(actor, "name", "Actor"),
        "target": _value(target, "name", "Target"), "weapon": definition.get("name", "Weapon"),
        "ranged": ranged, "thrown": thrown_attack,
        "rolls": dice, "natural": natural, "total": total, "target_ac": target_ac,
        "ability": ability, "ability_modifier": ability_mod,
        "proficiency_bonus": proficiency, "disadvantage": disadvantage,
        "weapon_attack_bonus": weapon_attack_bonus,
        "critical": critical, "hit": hit, "damage": 0, "damage_rolls": [],
        "damage_type": definition.get("damage_type", "untyped"),
    }
    if hit:
        damage_expression = definition.get("damage_dice", "1d4")
        if definition.get("damage_profiles"):
            has_offhand = bool(_equipment(actor).get("off_hand"))
            damage_expression = definition["damage_profiles"][
                "off_hand_occupied" if has_offhand else "off_hand_empty"
            ]
        dice_multiplier = item_attribute_total(
            weapon, "weapon_damage_dice_multiplier") or 1
        if dice_multiplier > 1:
            damage_expression = scale_dice_count(damage_expression, dice_multiplier)
        damage, damage_rolls = roll_dice(damage_expression, critical=critical)
        rolled_damage_bonus = item_attribute_total(weapon, "weapon_damage_bonus")
        damage = max(0, damage + ability_mod + rolled_damage_bonus)
        bonus_effects = [effect for effect in (_value(actor, "active_effects", []) or [])
                         if effect.get("kind") == "next_weapon_hit_bonus"]
        bonus_rolls = []
        for effect in bonus_effects:
            bonus, rolled = roll_dice(effect["formula"])
            damage += bonus
            bonus_rolls.extend(rolled)
            _value(actor, "active_effects", []).remove(effect)
        if isinstance(target, dict):
            hp_key = "current_hp" if "current_hp" in target else "hp"
            target[hp_key] = max(0, int(target.get(hp_key, 1)) - damage)
            if target[hp_key] == 0:
                target["downed"] = True
        else:
            hp = max(0, int(getattr(target, "current_hp", 1)) - damage)
            target.current_hp = hp
            if hp == 0:
                target.downed = True
        event.update(damage=damage, damage_rolls=damage_rolls + bonus_rolls,
                     target_hp=_value(target, "current_hp", _value(target, "hp", 0)))
    return event


def distance_feet(actor_a, actor_b, pixels_per_foot=4, actor_size=100):
    """Gridless center-to-center distance, rounded up to whole feet."""
    ax, ay, aw, ah = _actor_bounds(actor_a, actor_size)
    bx, by, bw, bh = _actor_bounds(actor_b, actor_size)
    ax += aw / 2
    ay += ah / 2
    bx += bw / 2
    by += bh / 2
    return math.ceil(math.hypot(ax - bx, ay - by) / pixels_per_foot)


def edge_distance_feet(actor_a, actor_b, pixels_per_foot=4, default_size=100):
    """Return the nearest gap between actor rectangles, converted to feet."""
    def bounds(actor):
        return _actor_bounds(actor, default_size)

    ax, ay, aw, ah = bounds(actor_a)
    bx, by, bw, bh = bounds(actor_b)
    horizontal_gap = max(0, abs((ax + aw / 2) - (bx + bw / 2)) - (aw + bw) / 2)
    vertical_gap = max(0, abs((ay + ah / 2) - (by + bh / 2)) - (ah + bh) / 2)
    return math.ceil(math.hypot(horizontal_gap, vertical_gap) / pixels_per_foot)


def _actor_bounds(actor, default_size):
    x = _value(actor, "x", 0)
    y = _value(actor, "y", 0)
    hitbox = _value(actor, "hitbox")
    if hitbox:
        return (x + hitbox.get("offset_x", 0), y + hitbox.get("offset_y", 0),
                hitbox.get("width", default_size), hitbox.get("height", default_size))
    return (x, y, _value(actor, "width", default_size),
            _value(actor, "height", default_size))
