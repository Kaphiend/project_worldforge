"""Pure rest economy rules, ready for stage and party UI integration.

This module deliberately does not move actors or start a rest session. The
calling game flow must first move an outdoor party to its camp stage, or
confirm that the inn interaction is available, then invoke ``resolve_rest``
once for each participating actor.
"""
from math import ceil

from worldforge.actors.factory import effective_max_hp
from worldforge.core.progression import (initialize_resources, qualified_level,
                         sync_progression_levels, unspent_xp)
from worldforge.content.campaign import campaign_rule
from worldforge.core.dice import roll_dice
from worldforge.core.progression import class_levels
from worldforge.content.classes import CLASSES

OUTDOOR_REST_MIN_DISTANCE_FEET = campaign_rule(
    "outdoor_rest_min_distance_feet", 100)
OUTDOOR_REST_MIN_RATE_PERCENT = campaign_rule(
    "outdoor_rest_rate_min_percent", 1)
OUTDOOR_REST_MAX_RATE_PERCENT = campaign_rule(
    "outdoor_rest_rate_max_percent", 5)
SHORT_REST_COST_MULTIPLIER = campaign_rule(
    "short_rest_cost_multiplier",
    campaign_rule("short_rest_xp_multiplier", 1.0))
LONG_REST_COST_MULTIPLIER = campaign_rule(
    "long_rest_cost_multiplier",
    campaign_rule("long_rest_xp_multiplier", 2.0))
INN_REST_GOLD_COST = campaign_rule("inn_rest_gold_cost", 10)


def rest_xp_cost(actor_data, rest_type="long_rest", *, location="outdoor"):
    """Return the tunable XP price curve for a short or long rest."""
    available = unspent_xp(actor_data)
    streak = (max(0, int(actor_data.get("outdoor_rest_streak", 0) or 0))
              if location == "outdoor" else 0)
    rate = min(OUTDOOR_REST_MAX_RATE_PERCENT,
               OUTDOOR_REST_MIN_RATE_PERCENT + streak)
    multiplier = (SHORT_REST_COST_MULTIPLIER if rest_type == "short_rest"
                  else LONG_REST_COST_MULTIPLIER)
    if available <= 0:
        return None, rate
    cost = max(1, ceil(available * rate / 100 * multiplier))
    return min(cost, available), rate


def outdoor_rest_cost(actor_data, rest_type="long_rest"):
    """Compatibility name for the outdoor XP cost query."""
    return rest_xp_cost(actor_data, rest_type, location="outdoor")


def inn_rest_gold_cost(rest_type="long_rest"):
    """Return the inn price with the same tunable short/long rest curve."""
    multiplier = (SHORT_REST_COST_MULTIPLIER if rest_type == "short_rest"
                  else LONG_REST_COST_MULTIPLIER)
    return max(1, ceil(INN_REST_GOLD_COST * multiplier))


def resolve_rest(actor_data, location, *, distance_to_nearest_enemy_feet=None,
                 rest_type="long_rest", hit_dice_spent=None):
    """Apply one rest's costs and resource recovery, returning a summary.

    ``location`` must be ``"outdoor"`` or ``"inn"``. Short rests recover
    short-rest resources and optionally spend hit dice; long rests restore HP,
    recover long-rest resources, and return half of expended Hit Dice.
    """
    if rest_type not in {"short_rest", "long_rest"}:
        return {"success": False, "reason": "Unknown rest type."}
    if location not in {"outdoor", "inn"}:
        return {"success": False, "reason": "Unknown rest location."}
    if location == "outdoor":
        if distance_to_nearest_enemy_feet is None or distance_to_nearest_enemy_feet <= OUTDOOR_REST_MIN_DISTANCE_FEET:
            return {"success": False, "reason": (
                f"An outdoor camp must be more than "
                f"{OUTDOOR_REST_MIN_DISTANCE_FEET} feet from every enemy.")}
    cost, rate = rest_xp_cost(actor_data, rest_type, location=location)
    gold_cost = 0
    if location == "outdoor":
        if cost is None:
            return {"success": False, "reason": "No unspent XP remains; resting requires XP."}
        actor_data["xp_total"] = max(0, int(actor_data.get("xp_total", 0) or 0) - cost)
        level_key = str(max(1, int(actor_data.get("level", 1) or 1)))
        spent = actor_data.setdefault("xp_rest_spent_by_level", {})
        spent[level_key] = int(spent.get(level_key, 0) or 0) + cost
        xp_cost = cost
    else:
        gold_cost = inn_rest_gold_cost(rest_type)
        if int(actor_data.get("gold", 0) or 0) < gold_cost:
            return {"success": False, "reason": f"An inn rest costs {gold_cost} gold; you do not have enough."}
        actor_data["gold"] = int(actor_data.get("gold", 0) or 0) - gold_cost
        xp_cost = 0
    if location == "outdoor":
        actor_data["outdoor_rest_streak"] = max(
            0, int(actor_data.get("outdoor_rest_streak", 0) or 0)) + 1
    else:
        actor_data["outdoor_rest_streak"] = 0
    sync_progression_levels(actor_data)
    rate_percent = rate

    resources = initialize_resources(actor_data, recovery=rest_type)
    if rest_type == "long_rest":
        _restore_health(actor_data)
        _recover_hit_dice(actor_data)
        hit_dice_result = {"spent": {}, "healing": 0, "rolls": []}
    else:
        hit_dice_result = _spend_hit_dice(actor_data, hit_dice_spent or {})
    return {"success": True, "location": location, "rest_type": rest_type,
            "xp_cost": xp_cost,
            "gold_cost": gold_cost,
            "rate_percent": rate_percent, "unspent_xp": unspent_xp(actor_data),
            "level_earned": qualified_level(actor_data),
            "hit_dice": hit_dice_result, "resources": resources}


def resolve_paid_inn_rest(actor_data, rest_type="long_rest", hit_dice_spent=None,
                          gold_cost=0):
    """Complete an inn rest after its gold price was paid during booking."""
    actor_data["outdoor_rest_streak"] = 0
    sync_progression_levels(actor_data)
    resources = initialize_resources(actor_data, recovery=rest_type)
    if rest_type == "long_rest":
        _restore_health(actor_data)
        _recover_hit_dice(actor_data)
        hit_dice_result = {"spent": {}, "healing": 0, "rolls": []}
    else:
        hit_dice_result = _spend_hit_dice(actor_data, hit_dice_spent or {})
    return {"success": True, "location": "inn", "rest_type": rest_type,
            "gold_cost": max(0, int(gold_cost or 0)),
            "resources": resources, "hit_dice": hit_dice_result,
            "level_earned": qualified_level(actor_data)}


def _hit_dice(actor_data):
    levels = class_levels(actor_data)
    remaining = actor_data.setdefault("hit_dice_remaining", {})
    definitions = {}
    for class_id, level in levels.items():
        sides = int(CLASSES.get(class_id, {}).get("hit_die", 8) or 8)
        key = f"{class_id}"
        definitions[key] = (max(0, int(level)), sides)
        remaining[key] = max(0, min(int(level), int(remaining.get(key, level))))
    for key in list(remaining):
        if key not in definitions:
            remaining.pop(key)
    return definitions, remaining


def _spend_hit_dice(actor_data, requested):
    definitions, remaining = _hit_dice(actor_data)
    constitution = (int(actor_data.get("abilities", {}).get("constitution", 10) or 10) - 10) // 2
    missing_hp = max(0, effective_max_hp(actor_data) - int(
        actor_data.get("current_hp", 0) or 0))
    rolls = []
    spent = {}
    total_healing = 0
    for class_id, (_, sides) in definitions.items():
        count = min(max(0, int(requested.get(class_id, 0) or 0)),
                    remaining.get(class_id, 0))
        for _ in range(count):
            if total_healing >= missing_hp:
                break
            total, dice = roll_dice(f"1d{sides}")
            healing = max(0, total + constitution)
            applied = min(missing_hp - total_healing, healing)
            rolls.append({"class_id": class_id, "die": sides, "rolls": dice,
                          "constitution_modifier": constitution,
                          "healing": applied})
            total_healing += applied
            remaining[class_id] -= 1
            spent[class_id] = spent.get(class_id, 0) + 1
    if not actor_data.get("downed"):
        actor_data["current_hp"] = min(
            effective_max_hp(actor_data),
            int(actor_data.get("current_hp", 0) or 0) + total_healing)
    return {"spent": spent, "healing": total_healing, "rolls": rolls}


def _recover_hit_dice(actor_data):
    definitions, remaining = _hit_dice(actor_data)
    total_dice = sum(maximum for maximum, _ in definitions.values())
    recover = max(1, total_dice // 2) if total_dice else 0
    for class_id, (maximum, _) in definitions.items():
        missing = maximum - remaining.get(class_id, 0)
        restored = min(missing, recover)
        remaining[class_id] = remaining.get(class_id, 0) + restored
        recover -= restored
        if recover <= 0:
            break


def _restore_health(actor_data):
    actor_data["downed"] = False
    actor_data["current_hp"] = effective_max_hp(actor_data)
