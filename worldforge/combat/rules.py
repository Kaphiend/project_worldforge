"""Data-driven combat calculations and turn-order helpers."""
import math

from worldforge.content.classes import EQUIPMENT_ITEMS, RACES
from worldforge.core.dice import roll_d20, roll_dice, scale_dice_count
from worldforge.actors.factory import (effective_max_hp, item_attribute_total, modifier,
                     _unique_equipped_items)
from worldforge.combat.conditions import consume_condition_use, has_condition
from worldforge.combat.species import damage_resistances, species_traits
from worldforge.content.campaign import campaign_rule


ROGUE_WEAPON_MASTERY = {
    "dagger": "nick", "handaxe": "vex", "light_hammer": "nick",
    "shortsword": "vex", "scimitar": "nick",
    "sword_1h": "sap", "sword_2h": "graze",
    "axe_1h": "topple", "axe_2h": "cleave", "hammer_1h": "push",
    "hammer_2h": "topple", "staff": "topple", "longbow": "slow",
    "crossbow": "vex",
}

FIGHTING_STYLE_OPTIONS = {
    "two_weapon_fighting": {
        "name": "Two-Weapon Fighting",
        "description": "Add your ability modifier to the damage of the extra Light-property attack if it is not already included.",
    },
}


def weapon_mastery_eligible(actor, weapon_id):
    """Whether actor has Weapon Mastery and is proficient with this template."""
    features = set(_value(actor, "class_features", []) or [])
    if not {"rogue_weapon_mastery", "fighter_weapon_mastery",
            "ranger_weapon_mastery", "paladin_weapon_mastery"}.intersection(features):
        return False
    definition = EQUIPMENT_ITEMS.get(weapon_id, {})
    if definition.get("category") != "weapon":
        return False
    if definition.get("weapon_class") in (_value(actor, "weapon_prof", []) or []):
        return True
    classes = {entry.get("name") for entry in _value(actor, "classes", []) or []}
    is_rogue = (_value(actor, "char_class", "") == "rogue" or "rogue" in classes)
    return ("rogue_weapon_mastery" in features and is_rogue
            and bool({"finesse", "light"}.intersection(
                definition.get("tags", []) or [])))


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
        if "speed_35" in species_traits(actor):
            return 35
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
    if definition.get("category") == "unarmed_strike":
        return True
    weapon_class = definition.get("weapon_class")
    proficiencies = _value(actor, "weapon_prof", []) or []
    if _value(actor, "char_class", "") == "warlock" and definition.get("weapon_family") == "sword":
        return True
    if (_value(actor, "char_class", "") == "rogue"
            and weapon_class == "martial"
            and bool({"finesse", "light"}.intersection(
                definition.get("tags", []) or []))):
        return True
    return weapon_class in proficiencies


def proficiency_bonus(actor):
    level = max(1, int(_value(actor, "level", 1) or 1))
    base = campaign_rule("proficiency_bonus_base", 2)
    step = max(1, campaign_rule("proficiency_bonus_level_step", 4))
    return base + (level - 1) // step


def resolve_skill_check(actor, skill, ability):
    """Roll a skill check with proficiency, Expertise, and Reliable Talent."""
    skills = {str(value).casefold() for value in _value(actor, "skills", []) or []}
    skill = str(skill).casefold()
    proficient = skill in skills
    expertise = skill in {
        str(value).casefold()
        for value in _value(actor, "expertise_skills", []) or []
    }
    bonus = modifier((_value(actor, "abilities", {}) or {}).get(ability, 10))
    if proficient:
        bonus += proficiency_bonus(actor) * (2 if expertise else 1)
    natural, dice = roll_d20()
    if (proficient and natural < 10 and "rogue_reliable_talent" in set(
            _value(actor, "class_features", []) or [])):
        natural = 10
    if natural == 1 and "lucky" in species_traits(actor):
        natural, reroll = roll_d20()
        dice += reroll
    return {"natural": natural, "dice": dice, "bonus": bonus,
            "total": natural + bonus, "proficient": proficient,
            "expertise": expertise}


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
    return weapon, definition, False


def _distance_disadvantage(definition, distance, ranged, adjacent_distance=None):
    if not ranged:
        return False
    ranges = definition.get("ranges", {})
    normal = ranges.get("normal", float("inf"))
    if distance > normal or (adjacent_distance if adjacent_distance is not None else distance) <= campaign_rule("ranged_attack_disadvantage_distance_feet", 5):
        return True
    # A second field often appears in content as a legacy long-range cap;
    # the requested rule permits attempts beyond it, still with disadvantage.
    return False


def attack(actor, target, distance_feet, *, melee_distance_feet=None,
           adjacent_distance_feet=None, line_of_sight=True,
           attack_mode="primary", unseen_attack=False,
           sneak_attack_dice=0, sneak_attack_opportunity=False,
           damage_multiplier=1.0, target_actor_id=None,
           weapon_override=None, damage_modifier_cap=None):
    """Resolve a primary, unarmed, or separately selected thrown attack.

    ``primary`` always uses the selected weapon set and never auto-throws a
    thrown-tagged hand weapon. ``throw`` explicitly uses any main-hand weapon
    and defaults to a 20/60 ft range when the template has no thrown range.
    """
    equipment = _equipment(actor)
    thrown_attack = attack_mode == "throw"
    unarmed_attack = attack_mode == "unarmed"
    if thrown_attack:
        weapon = equipment.get("main_hand")
        definition = _definition(weapon)
        dual_wield = False
        if not _is_weapon(weapon):
            return {"kind": "attack", "success": False,
                    "message": "You need a main-hand weapon to throw."}
    elif unarmed_attack:
        weapon = {"name": "Unarmed Strike", "category": "unarmed_strike",
                  "damage_dice": "1d1", "damage_type": "bludgeoning",
                  "ranges": {"melee": 5}}
        definition = weapon
        dual_wield = False
    elif attack_mode in {"offhand", "offhand_nick"}:
        weapon = weapon_override or equipment.get("off_hand")
        if not _is_weapon(weapon):
            weapon = equipment.get("ranged_offhand")
        definition = _definition(weapon)
        dual_wield = False
        if not _is_weapon(weapon):
            return {"kind": "attack", "success": False,
                    "message": "No off-hand weapon is equipped."}
    elif attack_mode == "ranged":
        weapon = equipment.get("ranged")
        definition = _definition(weapon)
        dual_wield = False
        if not _is_weapon(weapon):
            return {"kind": "attack", "success": False,
                    "message": "No ranged weapon is equipped."}
    else:
        weapon, definition, dual_wield = ((weapon_override, _definition(weapon_override), False)
                                         if weapon_override else selected_weapon(actor))
        if weapon is None:
            weapon = {"name": "Unarmed Strike", "category": "unarmed_strike",
                      "damage_dice": "1d1", "damage_type": "bludgeoning",
                      "ranges": {"melee": 5}}
            definition = weapon
            dual_wield = False
            unarmed_attack = True
    if weapon is None:
        return {"kind": "attack", "success": False, "message": "No attack weapon is equipped."}
    ranged_weapon = (attack_mode == "ranged"
                     or (_value(actor, "active_weapon_set", "melee") == "ranged"
                         and weapon == equipment.get("ranged"))
                     or (attack_mode in {"offhand", "offhand_nick"}
                         and weapon == equipment.get("ranged_offhand")))
    ranged = thrown_attack or ranged_weapon
    ranges = definition.get("ranges", {})
    reach = ranges.get("melee", 5)
    if thrown_attack:
        ranges = {"normal": ranges.get("thrown_normal", campaign_rule("thrown_normal_range_feet", 20)),
                  "long": ranges.get("thrown_long", campaign_rule("thrown_long_range_feet", 60))}
    melee_distance = distance_feet if melee_distance_feet is None else melee_distance_feet
    if ranged:
        if not line_of_sight:
            return {"kind": "attack", "success": False, "message": "No clear line of sight."}
    elif melee_distance > reach:
        return {"kind": "attack", "success": False, "message": "Target is outside melee reach."}

    abilities = _value(actor, "abilities", {}) or {}
    ability = "dexterity" if ranged_weapon and not thrown_attack else "strength"
    if "finesse" in definition.get("tags", []):
        ability = ("dexterity" if int(abilities.get("dexterity", 10))
                   > int(abilities.get("strength", 10)) else "strength")
    class_levels = {entry.get("name"): int(entry.get("level", 0) or 0)
                    for entry in _value(actor, "classes", []) or []}
    monk_level = class_levels.get(
        "monk", _value(actor, "level", 1)
        if _value(actor, "char_class", "") == "monk" else 0)
    if unarmed_attack and monk_level > 0:
        ability = ("dexterity" if int(abilities.get("dexterity", 10))
                   >= int(abilities.get("strength", 10)) else "strength")
    ability_mod = modifier(abilities.get(ability, 10))
    proficient = _proficient(actor, definition)
    proficiency = proficiency_bonus(actor) if proficient else 0
    weapon_attack_bonus = item_attribute_total(weapon, "weapon_attack_bonus")
    attack_definition = definition
    if thrown_attack:
        attack_definition = dict(definition, ranges=ranges)
    own_effects = _value(actor, "active_effects", []) or []
    target_effects = _value(target, "active_effects", []) or []
    attacker_advantage = bool(unseen_attack or any(
        effect.get("kind") == "next_attack_advantage"
        and (effect.get("target_id") is None
             or effect.get("target_id") == target_actor_id)
        for effect in own_effects))
    reckless = next((effect for effect in own_effects
                     if effect.get("kind") == "reckless_attack"), None)
    if (reckless and reckless.get("remaining_turns", 0) >= 2
            and ability == "strength" and not ranged and not unarmed_attack):
        attacker_advantage = True
    attacker_disadvantage = (
        _distance_disadvantage(attack_definition, distance_feet, ranged,
                               adjacent_distance_feet)
        or has_condition(actor, "off_balance")
        or has_condition(actor, "poisoned")
        or has_condition(actor, "prone")
        or any(effect.get("kind") == "attack_disadvantage"
               for effect in target_effects)
        or any(effect.get("kind") == "attack_disadvantage_against_target"
               for effect in target_effects))
    target_reckless = any(effect.get("kind") == "reckless_attack"
                          for effect in target_effects)
    if target_reckless:
        attacker_advantage = True
    if ("rogue_elusive" in set(_value(target, "class_features", []) or [])
            and not has_condition(target, "incapacitated")):
        attacker_advantage = False
    if has_condition(target, "prone"):
        if ranged:
            attacker_disadvantage = True
        elif (adjacent_distance_feet if adjacent_distance_feet is not None
              else distance_feet) <= 5:
            attacker_advantage = True
    attack_advantage = (0 if attacker_advantage == attacker_disadvantage
                        else 1 if attacker_advantage else -1)
    disadvantage = attack_advantage < 0
    natural, dice = roll_d20(attack_advantage)
    aimed = next((effect for effect in own_effects
                  if effect.get("kind") == "next_attack_advantage"
                  and (effect.get("target_id") is None
                       or effect.get("target_id") == target_actor_id)), None)
    if aimed:
        own_effects.remove(aimed)
    if natural == 1 and "lucky" in species_traits(actor):
        natural, reroll = roll_d20(attack_advantage)
        dice += reroll
    if has_condition(actor, "off_balance"):
        consume_condition_use(actor, "off_balance")
    critical = natural >= campaign_rule("critical_hit_natural_roll", 20)
    target_ac = armor_class(target)
    total = natural + ability_mod + proficiency + weapon_attack_bonus
    hit = (critical or (natural > campaign_rule("automatic_miss_natural_roll", 1)
                        and total >= target_ac))
    event = {
        "kind": "attack", "success": True, "attacker": _value(actor, "name", "Actor"),
        "target": _value(target, "name", "Target"), "weapon": definition.get("name", "Weapon"),
        "ranged": ranged, "thrown": thrown_attack,
        "rolls": dice, "natural": natural, "total": total, "target_ac": target_ac,
        "ability": ability, "ability_modifier": ability_mod,
        "proficiency_bonus": proficiency, "disadvantage": disadvantage,
        "weapon_attack_bonus": weapon_attack_bonus,
        "critical": critical, "hit": hit, "damage": 0, "graze_damage": 0,
        "damage_rolls": [],
        "damage_type": definition.get("damage_type", "untyped"),
    }
    if hit:
        if unarmed_attack:
            if monk_level > 0:
                martial_die = (6 if monk_level < 5 else 8 if monk_level < 11
                               else 10 if monk_level < 17 else 12)
                damage, damage_rolls = roll_dice(
                    f"1d{martial_die}", critical=critical)
                damage = max(0, damage + ability_mod)
            else:
                damage, damage_rolls = max(0, 1 + ability_mod), []
        else:
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
            damage_modifier = ability_mod
            if attack_mode in {"offhand", "offhand_nick"}:
                fighting_styles = {str(value).casefold() for value in
                                   _value(actor, "fighting_styles", []) or []}
                features = {str(value).casefold() for value in
                            _value(actor, "class_features", []) or []}
                has_two_weapon_fighting = bool({
                    "two_weapon_fighting", "two_weapon_fighting_style"
                }.intersection(fighting_styles | features))
                damage_modifier = (ability_mod if has_two_weapon_fighting
                                   else min(0, ability_mod))
            if damage_modifier_cap is not None:
                damage_modifier = min(int(damage_modifier_cap), ability_mod)
            damage = max(0, damage + damage_modifier + rolled_damage_bonus)
        sneak_damage, sneak_rolls = 0, []
        if (sneak_attack_dice and not unarmed_attack and not disadvantage
                and (attacker_advantage or sneak_attack_opportunity)
                and (not _is_weapon(weapon) or ranged
                     or "finesse" in definition.get("tags", []))):
            sneak_damage, sneak_rolls = roll_dice(
                f"{int(sneak_attack_dice)}d6", critical=critical)
            damage += sneak_damage
        bonus_effects = ([] if unarmed_attack else [
            effect for effect in (_value(actor, "active_effects", []) or [])
            if effect.get("kind") == "next_weapon_hit_bonus"])
        persistent_bonus_effects = ([] if unarmed_attack else [
            effect for effect in (_value(actor, "active_effects", []) or [])
            if effect.get("kind") == "weapon_damage_bonus"])
        resistances = damage_resistances(target)
        resisted = definition.get("damage_type", "untyped") in resistances
        if resisted:
            damage //= 2
        bonus_resisted = False
        feature_bonus_damage = 0
        bonus_rolls = []
        for effect in bonus_effects + persistent_bonus_effects:
            if effect.get("strength_based") and (
                    ability != "strength" or ranged or thrown_attack):
                continue
            if effect.get("amount_by_class_level"):
                class_id = effect.get("class_id")
                levels = {entry.get("name"): int(entry.get("level", 0) or 0)
                          for entry in _value(actor, "classes", []) or []}
                class_level = levels.get(
                    class_id, _value(actor, "level", 1)
                    if _value(actor, "char_class", "") == class_id else 0)
                level_amounts = effect["amount_by_class_level"]
                eligible = [int(level) for level in level_amounts
                            if int(level) <= class_level]
                bonus = (int(level_amounts[str(max(eligible))]) if eligible else 0)
                rolled = []
            elif effect.get("formula"):
                bonus, rolled = roll_dice(effect["formula"], critical=critical)
            else:
                bonus, rolled = int(effect.get("amount", 0)), []
            bonus_type = effect.get("damage_type", definition.get("damage_type", "untyped"))
            if bonus_type in resistances:
                bonus //= 2
                bonus_resisted = True
            damage += bonus
            feature_bonus_damage += bonus
            bonus_rolls.extend(rolled)
            if effect in bonus_effects:
                _value(actor, "active_effects", []).remove(effect)
        resisted = resisted or bonus_resisted
        damage = max(0, int(damage * max(0.0, float(damage_multiplier))))
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
        event.update(damage=damage, resisted=resisted,
                     damage_multiplier=damage_multiplier,
                     damage_rolls=damage_rolls + bonus_rolls + sneak_rolls,
                     feature_bonus_damage=feature_bonus_damage,
                     sneak_attack_damage=sneak_damage,
                     target_hp=_value(target, "current_hp", _value(target, "hp", 0)))
    elif (not unarmed_attack and proficient and ability_mod > 0
          and {"rogue_weapon_mastery", "fighter_weapon_mastery",
               "ranger_weapon_mastery", "paladin_weapon_mastery"}.intersection(
              _value(actor, "class_features", []) or [])
          and (_value(actor, "weapon_masteries", {}) or {}).get(
              weapon.get("template_id")) == "graze"):
        damage = ability_mod
        resisted = definition.get("damage_type", "untyped") in damage_resistances(target)
        if resisted:
            damage //= 2
        # Graze applies to a miss, so it does not trigger hit-only reactions.
        damage = max(0, int(damage))
        if isinstance(target, dict):
            hp_key = "current_hp" if "current_hp" in target else "hp"
            target[hp_key] = max(0, int(target.get(hp_key, 1)) - damage)
        else:
            target.current_hp = max(0, int(target.current_hp) - damage)
        event.update(damage=damage, graze_damage=damage, resisted=resisted,
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
