"""Character XP and class-driven resource progression.

Class resource curves are data, not rules hidden in the UI. A curve is a
level-indexed JSON array: index zero is unused, and index N is the capacity at
class level N. Multiclass spell capacity sums each class's contribution at its
own class level.
"""

from classes import CLASSES


# Cumulative character XP thresholds from the fifth-edition advancement table.
# Stored locally so progression is deterministic and can later be data-driven.
XP_THRESHOLDS = (
    0, 300, 900, 2700, 6500, 14000, 23000, 34000, 48000, 64000,
    85000, 100000, 120000, 140000, 165000, 195000, 225000, 265000,
    305000, 355000,
)
MAX_LEVEL = len(XP_THRESHOLDS)


def class_levels(actor_data):
    """Return class-ID to level mapping, with legacy single-class fallback."""
    result = {}
    for entry in actor_data.get("classes", []) or []:
        name = entry.get("name")
        if name:
            result[name] = result.get(name, 0) + max(0, int(entry.get("level", 0)))
    if not result and actor_data.get("char_class"):
        result[actor_data["char_class"]] = max(1, int(actor_data.get("level", 1)))
    return result


def character_level_for_xp(xp_total):
    """Return the highest level earned by cumulative XP (capped at 20)."""
    xp_total = max(0, int(xp_total or 0))
    level = 1
    for candidate, threshold in enumerate(XP_THRESHOLDS, start=1):
        if xp_total >= threshold:
            level = candidate
        else:
            break
    return level


def next_level_xp(level):
    """Return the cumulative XP threshold for the next level, or None at 20."""
    index = max(1, int(level or 1))
    return XP_THRESHOLDS[index] if index < MAX_LEVEL else None


def _curve_value(class_data, field_name, level):
    curve = class_data.get(field_name, []) or []
    level = max(0, int(level))
    if isinstance(curve, dict):
        return max(0, int(curve.get(str(level), curve.get(level, 0))))
    if level < len(curve):
        return max(0, int(curve[level]))
    return max(0, int(curve[-1])) if curve else 0


def spell_point_max(actor_data):
    """Sum class-level contributions to the character's shared spell pool."""
    total = 0
    for class_id, level in class_levels(actor_data).items():
        class_data = CLASSES.get(class_id, {})
        total += _curve_value(class_data, "spell_points_by_level", level)
    return total


def class_resource_maxima(actor_data):
    """Return named class pools and their capacities for this character."""
    maxima = {}
    for class_id, level in class_levels(actor_data).items():
        class_data = CLASSES.get(class_id, {})
        for resource_id, resource in class_data.get("class_resources", {}).items():
            key = f"{class_id}.{resource_id}"
            maxima[key] = {
                "class_id": class_id,
                "resource_id": resource_id,
                "name": resource.get("name", resource_id.replace("_", " ").title()),
                "maximum": _curve_value(resource, "max_by_level", level),
                "recovery": resource.get("recovery", "rest"),
            }
    return maxima


def initialize_resources(actor_data, *, refill=False):
    """Fill missing pools for a new/legacy actor and clamp current values."""
    spell_max = spell_point_max(actor_data)
    if refill or actor_data.get("spell_points") is None:
        actor_data["spell_points"] = spell_max
    else:
        actor_data["spell_points"] = max(0, min(spell_max, int(actor_data["spell_points"])))

    current = actor_data.setdefault("class_resources", {})
    maxima = class_resource_maxima(actor_data)
    for key, definition in maxima.items():
        maximum = definition["maximum"]
        if refill or key not in current:
            current[key] = maximum
        else:
            current[key] = max(0, min(maximum, int(current[key])))
    for key in list(current):
        if key not in maxima:
            current.pop(key)
    return {"spell_points": spell_max, "class_resources": maxima}


def xp_cost_for_next_level(level, xp_total):
    """Return the additional cumulative XP needed for the next level."""
    threshold = next_level_xp(level)
    return None if threshold is None else max(0, threshold - int(xp_total or 0))


def trainer_xp_cost(current_class_level):
    """XP spent at a class trainer to buy that class's next level.

    Costs use the incremental gaps in the shared fifth-edition XP threshold
    curve. Class levels advance independently, so total class levels can exceed
    20; each individual class remains capped at 20. The trainer UI/action that
    charges this cost is not implemented yet.
    """
    current = max(0, int(current_class_level or 0))
    next_level = current + 1
    if next_level > MAX_LEVEL:
        return None
    prior_threshold = XP_THRESHOLDS[max(0, current - 1)]
    next_threshold = XP_THRESHOLDS[next_level - 1]
    return next_threshold - prior_threshold
