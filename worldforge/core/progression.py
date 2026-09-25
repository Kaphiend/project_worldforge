"""Character XP and class-driven resource progression.

Class resource curves are data, not rules hidden in the UI. A curve is a
level-indexed JSON array: index zero is unused, and index N is the capacity at
class level N. Multiclass spell capacity sums each class's contribution at its
own class level.
"""

import math

from worldforge.content.classes import CLASSES, PROGRESSION_RULES
from worldforge.content.classes import ABILITIES, SPELLS
from worldforge.core.dice import ability_modifier


# Cumulative character XP thresholds from the fifth-edition advancement table.
# Stored locally so progression is deterministic and can later be data-driven.
XP_THRESHOLDS = (
    0, 300, 900, 2700, 6500, 14000, 23000, 34000, 48000, 64000,
    85000, 100000, 120000, 140000, 165000, 195000, 225000, 265000,
    305000, 355000,
)
def class_levels(actor_data):
    """Return levels actually assigned to each class for resource curves."""
    levels = {entry.get("name"): max(0, int(entry.get("level", 0) or 0))
              for entry in actor_data.get("classes", []) or []
              if entry.get("name")}
    primary = actor_data.get("char_class")
    if primary and primary not in levels:
        levels[primary] = max(1, int(actor_data.get("level", 1) or 1))
    return {name: level for name, level in levels.items() if level > 0}


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


def earned_level(actor_data):
    """Return the highest level earned from gross XP."""
    earned_xp = sum(max(0, int(value or 0))
                    for value in actor_data.get("xp_earned_by_level", {}).values())
    if earned_xp == 0:
        spent_xp = sum(max(0, int(value or 0)) for value in
                       (actor_data.get("xp_spent_by_level", {}) or {}).values())
        spent_xp += sum(max(0, int(value or 0)) for value in
                        (actor_data.get("xp_rest_spent_by_level", {}) or {}).values())
        earned_xp = max(0, int(actor_data.get("xp_total", 0) or 0)) + spent_xp
    return character_level_for_xp(earned_xp)


def total_earned_xp(actor_data):
    """Return gross XP earned, including any XP later spent."""
    earned = sum(max(0, int(value or 0))
                 for value in (actor_data.get("xp_earned_by_level", {}) or {}).values())
    if earned:
        return earned
    spent = sum(max(0, int(value or 0)) for value in
                (actor_data.get("xp_spent_by_level", {}) or {}).values())
    spent += sum(max(0, int(value or 0)) for value in
                 (actor_data.get("xp_rest_spent_by_level", {}) or {}).values())
    return max(0, int(actor_data.get("xp_total", 0) or 0)) + spent


def levels_to_apply(actor_data):
    """Return earned levels not yet applied at the trainer."""
    applied = max(1, int(actor_data.get("level", 1) or 1))
    return max(0, earned_level(actor_data) - applied)


def class_feature_definition(class_id, feature):
    """Normalize progression data into a purchasable trainer option."""
    return {
        **feature,
        "classes": [class_id],
        "acquisition": "trainer_purchase",
        "xp_purchase_cost": max(0, int(feature.get("xp_purchase_cost", 10) or 0)),
    }


def apply_level_up(actor_data, class_id):
    """Apply one earned level to an unlocked class and grant fixed-average HP."""
    if actor_data.get("downed"):
        return False, "You cannot apply a level while downed."
    if class_id not in unlocked_classes(actor_data):
        return False, "Unlock that class before assigning a level."
    if levels_to_apply(actor_data) < 1:
        return False, "No earned levels are waiting to be applied."
    entry = next((item for item in actor_data.get("classes", []) or []
                  if item.get("name") == class_id), None)
    if entry is None:
        entry = {"name": class_id, "level": 0}
        actor_data.setdefault("classes", []).append(entry)
    from worldforge.content.classes import CLASSES
    class_data = CLASSES.get(class_id, {})
    hit_die = max(1, int(class_data.get("hit_die", 8) or 8))
    con = int((actor_data.get("abilities", {}) or {}).get("constitution", 10) or 10)
    con_modifier = ability_modifier(min(30, con))
    hp_gain = max(1, hit_die // 2 + 1 + con_modifier)
    entry["level"] = max(0, int(entry.get("level", 0) or 0)) + 1
    actor_data["max_hp"] = max(1, int(actor_data.get("max_hp", 1) or 1) + hp_gain)
    actor_data["current_hp"] = min(
        actor_data["max_hp"], max(0, int(actor_data.get("current_hp", 0) or 0)) + hp_gain)
    actor_data["level"] = max(1, int(actor_data.get("level", 1) or 1)) + 1
    initialize_resources(actor_data)
    message = f"{class_id.title()} level applied. Maximum HP +{hp_gain}."
    return True, message


def attribute_points_earned(actor_data):
    """Return permanent attribute points granted by applied character level."""
    level = max(1, int(actor_data.get("level", 1) or 1))
    rules = PROGRESSION_RULES.get("attribute_points", {})
    per_milestone = max(0, int(rules.get("points_per_milestone", 2)))
    milestones = rules.get("milestones", [4, 8, 12, 16, 20])
    return sum(per_milestone for milestone in milestones
               if level >= int(milestone))


def attribute_points_available(actor_data):
    spent = sum(max(0, int(value or 0)) for value in
                (actor_data.get("attribute_points_spent", {}) or {}).values())
    return max(0, attribute_points_earned(actor_data) - spent)


def spend_attribute_point(actor_data, ability):
    """Spend one earned point to increase one stored ability score by one."""
    valid_abilities = {"strength", "dexterity", "constitution", "intellect",
                       "wisdom", "charisma"}
    if ability not in valid_abilities:
        return False, "Choose a valid ability score."
    if attribute_points_available(actor_data) < 1:
        return False, "No attribute points are available to spend."
    actor_data.setdefault("abilities", {})[ability] = (
        int(actor_data.get("abilities", {}).get(ability, 10) or 10) + 1)
    spent = actor_data.setdefault("attribute_points_spent", {})
    spent[ability] = int(spent.get(ability, 0) or 0) + 1
    return True, ""


def class_unlocked_level(actor_data, class_id):
    """Return a class's sequential tier frontier, capped by character level.

    Classes advance after buying at least one prior-tier spell, ability, or
    class feature. This also provides a progression path for martial classes.
    """
    assigned_class_level = class_levels(actor_data).get(class_id, 0)
    # A class unlock grants its first level; later tiers require both that
    # class level and the character's XP-qualified level.
    ceiling = min(qualified_level(actor_data), assigned_class_level)
    frontier = 1
    spell_purchases = actor_data.get("class_spell_purchases", {}).get(class_id, [])
    ability_purchases = actor_data.get("class_ability_purchases", {}).get(class_id, [])
    feature_purchases = actor_data.get("class_feature_purchases", {}).get(class_id, [])
    for prior_tier in range(1, ceiling):
        tier_spells = [spell_id for spell_id, spell in SPELLS.items()
                       if class_id in spell.get("classes", [])
                       and spell.get("acquisition") == "trainer_purchase"
                       and not spell.get("cantrip")
                       and int(spell.get("prerequisite_class_level", 1)) == prior_tier]
        tier_abilities = [ability_id for ability_id, ability in ABILITIES.items()
                          if class_id in ability.get("classes", [])
                          and ability.get("acquisition") == "trainer_purchase"
                          and int(ability.get("prerequisite_class_level", 1)) == prior_tier]
        tier_features = [feature.get("id")
                         for feature in (CLASSES.get(class_id, {}).get(
                             "progression", {}) or {}).get(str(prior_tier), [])
                         if feature.get("id")]
        # SRD class tables do not provide a purchasable feature at every
        # level. Worldforge's custom XP rule requires a purchase when a tier
        # offers one, but empty tiers must remain traversable.
        if not (tier_spells or tier_abilities or tier_features):
            frontier = prior_tier + 1
            continue
        advanced = (any(spell_id in spell_purchases for spell_id in tier_spells)
                    or any(ability_id in ability_purchases for ability_id in tier_abilities)
                    or any(feature_id in feature_purchases for feature_id in tier_features))
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


def unlocked_classes(actor_data):
    """Return acquired classes in progression order, preserving the primary."""
    entries = [entry.get("name") for entry in actor_data.get("classes", []) or []
               if entry.get("name") in CLASSES]
    primary = actor_data.get("char_class")
    if primary in CLASSES:
        entries = [primary] + [class_id for class_id in entries if class_id != primary]
    for key in ("class_spell_purchases", "class_ability_purchases",
                "class_feature_purchases", "class_skill_purchases"):
        for class_id, purchases in (actor_data.get(key, {}) or {}).items():
            if purchases and class_id in CLASSES and class_id not in entries:
                entries.append(class_id)
    return entries


def class_unlock_cost(actor_data, class_id):
    """Calculate the XP fee for unlocking the next additional class."""
    if class_id not in CLASSES or class_id in unlocked_classes(actor_data):
        return 0
    rules = PROGRESSION_RULES.get("multiclassing", {})
    base = max(0, int(rules.get("first_additional_class_xp_cost", 500)))
    multiplier = max(1, int(rules.get("class_unlock_xp_multiplier", 3)))
    additional_classes = max(0, len(unlocked_classes(actor_data)) - 1)
    return base * multiplier ** additional_classes


def class_purchase_multiplier(actor_data, class_id):
    """Return 1x for primary class, then 2x, 3x, etc. for later classes."""
    acquired = unlocked_classes(actor_data)
    if class_id not in acquired:
        return 1
    index = acquired.index(class_id)
    if index == 0:
        return 1
    rules = PROGRESSION_RULES.get("multiclassing", {})
    first = max(1, int(rules.get(
        "first_additional_class_purchase_multiplier", 2)))
    step = max(0, int(rules.get("subsequent_purchase_multiplier_step", 1)))
    return first + (index - 1) * step


def adjusted_purchase_cost(actor_data, class_id, definition):
    """Apply the class-order XP multiplier to a spell or ability cost."""
    cost = purchase_cost(definition)
    if cost is None:
        return None
    return cost * class_purchase_multiplier(actor_data, class_id)


def is_cantrip(spell):
    """Cantrips are always available and do not use prepared-spell slots."""
    return (spell.get("acquisition") == "starting_cantrip"
            or bool(spell.get("cantrip"))
            or int(spell.get("level", spell.get("tier", 1)) or 0) == 0)


def prepared_spell_limit(actor_data, class_id=None):
    """Return the prepared leveled-spell limit for the actor's casting class.

    This first playable rule uses class level plus the class's casting ability
    modifier, with a minimum of one. Keeping the formula here makes the limit
    easy to replace or move into content data as Worldforge's progression
    rules are tuned.
    """
    class_id = class_id or actor_data.get("char_class")
    class_data = CLASSES.get(class_id, {})
    casting_ability = class_data.get("spellcasting_ability")
    if not casting_ability:
        return 0
    scores = actor_data.get("abilities", {}) or {}
    ability_mod = ability_modifier(scores.get(casting_ability, 10) or 10)
    level = class_levels(actor_data).get(class_id, 0)
    return max(1, level + ability_mod)


def spell_source_class(actor_data, spell_id):
    """Find the actor's learned casting class that grants a spell."""
    spell_classes = set(SPELLS.get(spell_id, {}).get("classes", []))
    learned = {entry.get("name") for entry in actor_data.get("classes", []) or []
               if entry.get("name")}
    if actor_data.get("char_class"):
        learned.add(actor_data["char_class"])
    purchases = actor_data.get("class_spell_purchases", {}) or {}
    learned.update(class_id for class_id, ids in purchases.items() if ids)
    learned.update(class_id for class_id, ids in
                   (actor_data.get("class_ability_purchases", {}) or {}).items()
                   if ids)
    purchased_classes = [class_id for class_id, ids in purchases.items()
                         if spell_id in ids and class_id in learned
                         and class_id in spell_classes
                         and CLASSES.get(class_id, {}).get("spellcasting_ability")]
    if purchased_classes:
        return purchased_classes[0]
    candidates = [class_id for class_id in learned & spell_classes
                  if CLASSES.get(class_id, {}).get("spellcasting_ability")]
    primary = actor_data.get("char_class")
    if primary in candidates:
        return primary
    return next((class_id for class_id in CLASSES if class_id in candidates), None)


def prepared_leveled_spells(actor_data, class_id=None):
    """Return prepared leveled spells, optionally for one casting class."""
    prepared = actor_data.get("prepared_spells", []) or []
    return [spell_id for spell_id in prepared
            if spell_id in SPELLS and not is_cantrip(SPELLS[spell_id])
            and (class_id is None
                 or spell_source_class(actor_data, spell_id) == class_id)]


def set_spell_prepared(actor_data, spell_id, prepare=True):
    """Prepare or unprepare a known spell, enforcing the class limit."""
    if spell_id not in actor_data.get("known_spells", []):
        return False, "That spell is not in your spellbook."
    class_id = spell_source_class(actor_data, spell_id)
    if not class_id:
        return False, "Your class cannot prepare this spell."
    prepared = actor_data.setdefault("prepared_spells", [])
    if prepare:
        if spell_id in prepared:
            return True, ""
        if not is_cantrip(SPELLS[spell_id]):
            limit = prepared_spell_limit(actor_data, class_id)
            if len(prepared_leveled_spells(actor_data, class_id)) >= limit:
                return False, f"You can prepare only {limit} leveled spell(s)."
        prepared.append(spell_id)
    elif spell_id in prepared:
        if is_cantrip(SPELLS[spell_id]):
            return False, "Cantrips are always available and cannot be unprepared."
        prepared.remove(spell_id)
    return True, ""


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
    """Keep the permanently applied character level across XP transactions."""
    actor_data["level"] = max(1, int(actor_data.get("level", 1) or 1))
    entries = actor_data.get("classes", []) or []
    if not actor_data.get("class_levels_initialized", False):
        primary = actor_data.get("char_class")
        old_primary = next((entry for entry in entries
                            if entry.get("name") == primary), None)
        starting_class_level = max(
            1, int((old_primary or {}).get("level", 1) or 1))
        actor_data["level"] = min(actor_data["level"], starting_class_level)
        known = {entry.get("name") for entry in entries if entry.get("name")}
        for key in ("class_spell_purchases", "class_ability_purchases",
                    "class_feature_purchases", "class_skill_purchases"):
            known.update(class_id for class_id, owned in
                         (actor_data.get(key, {}) or {}).items()
                         if owned and class_id in CLASSES)
        if primary in CLASSES:
            known.add(primary)
        normalized = []
        class_order = ([primary] if primary in CLASSES else [])
        class_order.extend(class_id for class_id in CLASSES
                           if class_id in known and class_id != primary)
        for class_id in class_order:
            if class_id not in known:
                continue
            normalized.append({"name": class_id,
                               "level": actor_data["level"] if class_id == primary else 1})
        actor_data["classes"] = normalized
        actor_data["class_levels_initialized"] = True
    else:
        actor_data["classes"] = entries
        # Before class unlock granted a level, unlocked secondary classes
        # were persisted at zero. Treat those existing unlocks as level one.
        for entry in entries:
            if (entry.get("name") != actor_data.get("char_class")
                    and entry.get("name") in CLASSES
                    and int(entry.get("level", 0) or 0) < 1):
                entry["level"] = 1


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
