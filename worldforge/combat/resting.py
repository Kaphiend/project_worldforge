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

INN_REST_GOLD_COST = campaign_rule("inn_rest_gold_cost", 10)
OUTDOOR_REST_MIN_DISTANCE_FEET = campaign_rule(
    "outdoor_rest_min_distance_feet", 100)
OUTDOOR_REST_MIN_RATE_PERCENT = campaign_rule(
    "outdoor_rest_rate_min_percent", 1)
OUTDOOR_REST_MAX_RATE_PERCENT = campaign_rule(
    "outdoor_rest_rate_max_percent", 5)


def outdoor_rest_cost(actor_data):
    """Return (XP cost, current percentage rate), or (None, rate) if broke."""
    available = unspent_xp(actor_data)
    rate = min(OUTDOOR_REST_MAX_RATE_PERCENT,
               OUTDOOR_REST_MIN_RATE_PERCENT +
               max(0, int(actor_data.get("outdoor_rest_streak", 0) or 0)))
    if available <= 0:
        return None, rate
    cost = max(1, ceil(available * rate / 100))
    return min(cost, available), rate


def resolve_rest(actor_data, location, *, distance_to_nearest_enemy_feet=None):
    """Apply one rest's costs and resource recovery, returning a summary.

    ``location`` must be ``"outdoor"`` or ``"inn"``. A successful rest fully
    restores HP and clears conditions as well as replenishing resources.
    """
    if location == "outdoor":
        if distance_to_nearest_enemy_feet is None or distance_to_nearest_enemy_feet <= OUTDOOR_REST_MIN_DISTANCE_FEET:
            return {"success": False, "reason": (
                f"An outdoor camp must be more than "
                f"{OUTDOOR_REST_MIN_DISTANCE_FEET} feet from every enemy.")}
        cost, rate = outdoor_rest_cost(actor_data)
        if cost is None:
            return {"success": False, "reason": "No unspent XP remains. Rest at an inn."}
        actor_data["xp_total"] = max(0, int(actor_data.get("xp_total", 0) or 0) - cost)
        level_key = str(max(1, int(actor_data.get("level", 1) or 1)))
        spent = actor_data.setdefault("xp_rest_spent_by_level", {})
        spent[level_key] = int(spent.get(level_key, 0) or 0) + cost
        actor_data["outdoor_rest_streak"] = max(0, int(actor_data.get("outdoor_rest_streak", 0) or 0)) + 1
        sync_progression_levels(actor_data)
        initialize_resources(actor_data, refill=True)
        _restore_health_and_conditions(actor_data)
        return {"success": True, "location": location, "xp_cost": cost,
                "rate_percent": rate, "unspent_xp": unspent_xp(actor_data),
                "level_earned": qualified_level(actor_data)}
    if location == "inn":
        gold = max(0, int(actor_data.get("gold", 0) or 0))
        if gold < INN_REST_GOLD_COST:
            return {"success": False, "reason": (
                f"An inn rest costs {INN_REST_GOLD_COST} gold.")}
        actor_data["gold"] = gold - INN_REST_GOLD_COST
        actor_data["outdoor_rest_streak"] = 0
        sync_progression_levels(actor_data)
        initialize_resources(actor_data, refill=True)
        _restore_health_and_conditions(actor_data)
        return {"success": True, "location": location,
                "gold_cost": INN_REST_GOLD_COST,
                "level_earned": qualified_level(actor_data)}
    return {"success": False, "reason": "Unknown rest location."}


def resolve_paid_inn_rest(actor_data):
    """Complete recovery after an inn night's fee was paid during booking."""
    actor_data["outdoor_rest_streak"] = 0
    sync_progression_levels(actor_data)
    initialize_resources(actor_data, refill=True)
    _restore_health_and_conditions(actor_data)
    return {"success": True, "location": "inn", "gold_cost": 0,
            "level_earned": qualified_level(actor_data)}


def _restore_health_and_conditions(actor_data):
    if actor_data.get("downed"):
        actor_data["current_hp"] = 0
    else:
        actor_data["current_hp"] = effective_max_hp(actor_data)
    actor_data["conditions"] = []
