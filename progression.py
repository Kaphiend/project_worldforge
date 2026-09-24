"""Character XP and class-driven resource progression.

Class resource curves are data, not rules hidden in the UI. A curve is a
level-indexed JSON array: index zero is unused, and index N is the capacity at
class level N. Multiclass spell capacity sums each class's contribution at its
own class level.
"""

import math

from classes import CLASSES
from classes import ABILITIES, SPELLS


# Cumulative character XP thresholds from the fifth-edition advancement table.
# Stored locally so progression is deterministic and can later be data-driven.
XP_THRESHOLDS = (
    0, 300, 900, 2700, 6500, 14000, 23000, 34000, 48000, 64000,
    85000, 100000, 120000, 140000, 165000, 195000, 225000, 265000,
    305000, 355000,
)
MAX_LEVEL = len(XP_THRESHOLDS)


def class_levels(actor_data):
    """Return each learned class's current unlocked tier for resource curves."""
    names = {entry.get("name") for entry in actor_data.get("classes", []) or []
             if entry.get("name")}
    if actor_data.get("char_class"):
        names.add(actor_data["char_class"])
    names.update(actor_data.get("class_spell_purchases", {}).keys())
    names.update(actor_data.get("class_ability_purchases", {}).keys())
    return {name: class_unlocked_level(actor_data, name) for name in names}


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


def unspent_xp(actor_data):
    """Return the current XP wallet after purchases, rests, and penalties."""
    earned = sum(max(0, int(value or 0))
                 for value in actor_data.get("xp_earned_by_level", {}).values())
    spent = sum(max(0, int(value or 0))
                for value in actor_data.get("xp_spent_by_level", {}).values())
    rest_spent = sum(max(0, int(value or 0))
                     for value in actor_data.get("xp_rest_spent_by_level", {}).values())
    # Old and quick-start saves may have a wallet without a complete earned
    # ledger. In that case xp_total is authoritative and already net of costs.
    if earned == 0:
        return max(0, int(actor_data.get("xp_total", 0) or 0))
    return max(0, earned - spent - rest_spent)


def qualified_level(actor_data):
    """Return the character-wide purchase ceiling from current unspent XP."""
    return character_level_for_xp(unspent_xp(actor_data))


def class_unlocked_level(actor_data, class_id):
    """Return a class's sequential tier frontier, capped by character level.

    Spell classes advance after at least one spell at the prior tier is owned.
    Classes with no purchase spells at that tier use a purchased class ability
    as the progression key, so martial classes can advance too.
    """
    ceiling = qualified_level(actor_data)
    frontier = 1
    spell_purchases = actor_data.get("class_spell_purchases", {}).get(class_id, [])
    ability_purchases = actor_data.get("class_ability_purchases", {}).get(class_id, [])
    for prior_tier in range(1, ceiling):
        tier_spells = [spell_id for spell_id, spell in SPELLS.items()
                       if class_id in spell.get("classes", [])
                       and spell.get("acquisition") == "trainer_purchase"
                       and not spell.get("cantrip")
                       and int(spell.get("prerequisite_class_level", 1)) == prior_tier]
        if tier_spells:
            advanced = any(spell_id in spell_purchases for spell_id in tier_spells)
        else:
            tier_abilities = [ability_id for ability_id, ability in ABILITIES.items()
                              if class_id in ability.get("classes", [])
                              and ability.get("acquisition") == "trainer_purchase"
                              and int(ability.get("prerequisite_class_level", 1)) == prior_tier]
            advanced = any(ability_id in ability_purchases
                           for ability_id in tier_abilities)
        if not advanced:
            break
        frontier = prior_tier + 1
    return min(ceiling, frontier)


def purchase_cost(definition):
    """Read a content item's XP purchase price; absent prices are unavailable."""
    try:
        return max(0, int(definition["xp_purchase_cost"]))
    except (KeyError, TypeError, ValueError):
        return None


def spend_xp(actor_data, amount):
    """Spend XP once from the wallet and append it to the purchase ledger."""
    amount = max(0, int(amount))
    balance = unspent_xp(actor_data)
    if amount > balance:
        return False
    level_key = str(qualified_level(actor_data))
    ledger = actor_data.setdefault("xp_spent_by_level", {})
    ledger[level_key] = int(ledger.get(level_key, 0) or 0) + amount
    actor_data["xp_total"] = max(0, int(actor_data.get("xp_total", balance) or 0) - amount)
    sync_progression_levels(actor_data)
    initialize_resources(actor_data)
    return True


def charge_xp_penalty(actor_data, percentage):
    """Charge a percentage loss from current XP, rounded up to one point."""
    balance = unspent_xp(actor_data)
    if balance <= 0:
        return 0
    amount = min(balance, max(1, math.ceil(balance * int(percentage) / 100)))
    return amount if spend_xp(actor_data, amount) else 0


def sync_progression_levels(actor_data):
    """Keep legacy level fields aligned with current XP and class frontiers."""
    actor_data["level"] = qualified_level(actor_data)
    entries = actor_data.get("classes", []) or []
    known_classes = {entry.get("name") for entry in entries if entry.get("name")}
    known_classes.update(actor_data.get("class_spell_purchases", {}).keys())
    known_classes.update(actor_data.get("class_ability_purchases", {}).keys())
    for class_id in known_classes:
        entry = next((item for item in entries if item.get("name") == class_id), None)
        if entry is None:
            entry = {"name": class_id, "level": 1}
            entries.append(entry)
        entry["level"] = class_unlocked_level(actor_data, class_id)
    actor_data["classes"] = entries


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
    curve. Current trainer spell and ability purchases use per-item
    `xp_purchase_cost` data instead; this helper remains for later class-level
    purchase rules.
    """
    current = max(0, int(current_class_level or 0))
    next_level = current + 1
    if next_level > MAX_LEVEL:
        return None
    prior_threshold = XP_THRESHOLDS[max(0, current - 1)]
    next_threshold = XP_THRESHOLDS[next_level - 1]
    return next_threshold - prior_threshold
