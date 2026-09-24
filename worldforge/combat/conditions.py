"""Data-backed condition state and the initial condition primitives."""
from worldforge.content.classes import CONDITIONS
from worldforge.core.dice import roll_dice


def _get(actor, key, default=None):
    return actor.get(key, default) if isinstance(actor, dict) else getattr(actor, key, default)


def _set(actor, key, value):
    if isinstance(actor, dict):
        actor[key] = value
    else:
        setattr(actor, key, value)


def condition_ids(actor):
    return {entry.get("id") for entry in (_get(actor, "conditions", []) or [])}


def condition_names(actor):
    return [CONDITIONS[entry["id"]]["name"]
            for entry in (_get(actor, "conditions", []) or [])
            if entry.get("id") in CONDITIONS]


def has_condition(actor, condition_id):
    return condition_id in condition_ids(actor)


def apply_condition(actor, condition_id, *, source_id=None):
    """Attach a condition; reapplication follows its data-defined policy."""
    definition = CONDITIONS.get(condition_id)
    if definition is None:
        raise KeyError(f"Unknown condition: {condition_id}")
    active = list(_get(actor, "conditions", []) or [])
    existing = next((entry for entry in active if entry.get("id") == condition_id), None)
    turns = definition.get("duration", {}).get("turns")
    if existing and definition.get("reapplication") == "refresh_duration":
        existing["remaining_turns"] = turns
        existing["source_id"] = source_id
        for primitive in definition.get("primitives", []):
            if primitive.get("kind") == "attack_disadvantage":
                existing["uses"] = primitive.get("uses", 1)
    elif not existing:
        instance = {"id": condition_id, "remaining_turns": turns, "source_id": source_id}
        for primitive in definition.get("primitives", []):
            if primitive.get("kind") == "attack_disadvantage":
                instance["uses"] = primitive.get("uses", 1)
        active.append(instance)
    _set(actor, "conditions", active)
    return existing or active[-1]


def remove_condition(actor, condition_id):
    active = list(_get(actor, "conditions", []) or [])
    remaining = [entry for entry in active if entry.get("id") != condition_id]
    _set(actor, "conditions", remaining)
    return len(remaining) != len(active)


def tick_conditions(actor, phase):
    """Resolve condition primitives at turn start/end; return log-ready events."""
    events = []
    active = list(_get(actor, "conditions", []) or [])
    for instance in list(active):
        condition_id = instance.get("id")
        definition = CONDITIONS.get(condition_id)
        if not definition:
            active.remove(instance)
            continue
        for primitive in definition.get("primitives", []):
            if primitive.get("kind") == "damage_over_time" and phase == "start":
                if primitive.get("timing") == "start_of_affected_turn":
                    damage, dice = roll_dice(primitive["formula"])
                    hp = int(_get(actor, "current_hp", 0) or 0)
                    hp = max(0, hp - damage)
                    _set(actor, "current_hp", hp)
                    if hp <= 0:
                        _set(actor, "downed", True)
                    events.append({"condition": condition_id, "damage": damage,
                                   "dice": dice, "damage_type": primitive.get("damage_type")})
        if phase == "end":
            remaining = instance.get("remaining_turns")
            if remaining is not None:
                instance["remaining_turns"] = max(0, remaining - 1)
                if instance["remaining_turns"] == 0:
                    active.remove(instance)
                    events.append({"condition": condition_id, "expired": True})
    _set(actor, "conditions", active)
    active_effects = list(_get(actor, "active_effects", []) or [])
    if phase == "end":
        for effect in list(active_effects):
            remaining = effect.get("remaining_turns")
            if remaining is not None:
                effect["remaining_turns"] = max(0, remaining - 1)
                if effect["remaining_turns"] == 0:
                    active_effects.remove(effect)
    _set(actor, "active_effects", active_effects)
    return events


def consume_condition_use(actor, condition_id, uses=1):
    """Consume a limited-use condition primitive such as the next attack penalty."""
    active = list(_get(actor, "conditions", []) or [])
    instance = next((entry for entry in active if entry.get("id") == condition_id), None)
    if not instance:
        return False
    instance["uses"] = instance.get("uses", uses) - 1
    if instance["uses"] <= 0:
        active.remove(instance)
    _set(actor, "conditions", active)
    return True
