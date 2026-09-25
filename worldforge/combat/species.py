"""Species trait lookups shared by combat and perception rules."""
from worldforge.content.classes import RACES


def species_traits(actor):
    """Return the selected species and lineage traits for an actor."""
    if not isinstance(actor, dict):
        actor = vars(actor)
    race_id = actor.get("race", "")
    race = RACES.get(race_id, {})
    traits = set(race.get("traits", []) or [])
    subrace_id = actor.get("subrace")
    subrace = (race.get("subraces", {}).get(subrace_id, {})
               if subrace_id else {})
    traits.update(subrace.get("traits", []) or [])
    return traits


def damage_resistances(actor):
    """Damage types halved by passive species traits."""
    if not isinstance(actor, dict):
        actor = vars(actor)
    traits = species_traits(actor)
    resistances = set()
    trait_types = {
        "fire_resistance": "fire", "poison_resistance": "poison",
        "necrotic_resistance": "necrotic", "dwarven_resilience": "poison",
    }
    resistances.update(value for trait, value in trait_types.items() if trait in traits)
    ancestry = {
        "black": "acid", "copper": "acid", "blue": "lightning",
        "bronze": "lightning", "brass": "fire", "gold": "fire",
        "red": "fire", "green": "poison", "silver": "cold", "white": "cold",
    }
    if "damage_resistance" in traits:
        color = actor.get("subrace")
        if color in ancestry:
            resistances.add(ancestry[color])
    resistances.update(
        damage_type
        for effect in actor.get("active_effects", []) or []
        if effect.get("kind") == "damage_resistance"
        for damage_type in effect.get("damage_types", []) or [])
    return resistances
