"""Pure rest economy rules, ready for stage and party UI integration.

This module deliberately does not move actors or start a rest session. The
calling game flow must first move an outdoor party to its camp stage, or
confirm that the inn interaction is available, then invoke ``resolve_rest``
once for each participating actor.
"""
from math import ceil

from progression import character_level_for_xp, initialize_resources

INN_REST_GOLD_COST = 10
OUTDOOR_REST_MIN_DISTANCE_FEET = 100
OUTDOOR_REST_MIN_RATE_PERCENT = 1
OUTDOOR_REST_MAX_RATE_PERCENT = 5


def unspent_xp(actor_data):
    """Calculate XP available to spend after level and rest costs."""
    earned = sum(max(0, int(value or 0))
                 for value in actor_data.get("xp_earned_by_level", {}).values())
    spent = sum(max(0, int(value or 0))
                for value in actor_data.get("xp_spent_by_level", {}).values())
    rest_spent = sum(max(0, int(value or 0))
                     for value in actor_data.get("xp_rest_spent_by_level", {}).values())
    if earned == 0 and not actor_data.get("xp_spent_by_level"):
        return max(0, int(actor_data.get("xp_total", 0) or 0))
    return max(0, earned - spent - rest_spent)


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

    ``location`` must be ``"outdoor"`` or ``"inn"``. This layer intentionally
    leaves health and condition recovery unchanged until those rules are set.
    """
    if location == "outdoor":
        if distance_to_nearest_enemy_feet is None or distance_to_nearest_enemy_feet <= OUTDOOR_REST_MIN_DISTANCE_FEET:
            return {"success": False, "reason": "An outdoor camp must be more than 100 feet from every enemy."}
        cost, rate = outdoor_rest_cost(actor_data)
        if cost is None:
            return {"success": False, "reason": "No unspent XP remains. Rest at an inn."}
        actor_data["xp_total"] = max(0, int(actor_data.get("xp_total", 0) or 0) - cost)
        level_key = str(max(1, int(actor_data.get("level", 1) or 1)))
        spent = actor_data.setdefault("xp_rest_spent_by_level", {})
        spent[level_key] = int(spent.get(level_key, 0) or 0) + cost
        actor_data["outdoor_rest_streak"] = max(0, int(actor_data.get("outdoor_rest_streak", 0) or 0)) + 1
        initialize_resources(actor_data, refill=True)
        return {"success": True, "location": location, "xp_cost": cost,
                "rate_percent": rate, "unspent_xp": unspent_xp(actor_data),
                "level_earned": character_level_for_xp(actor_data.get("xp_total", 0))}
    if location == "inn":
        gold = max(0, int(actor_data.get("gold", 0) or 0))
        if gold < INN_REST_GOLD_COST:
            return {"success": False, "reason": "An inn rest costs 10 gold."}
        actor_data["gold"] = gold - INN_REST_GOLD_COST
        actor_data["outdoor_rest_streak"] = 0
        initialize_resources(actor_data, refill=True)
        return {"success": True, "location": location,
                "gold_cost": INN_REST_GOLD_COST,
                "level_earned": character_level_for_xp(actor_data.get("xp_total", 0))}
    return {"success": False, "reason": "Unknown rest location."}
