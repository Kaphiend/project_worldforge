"""Synchronization of local actors from authoritative world snapshots."""
from copy import deepcopy


def _sync_local_actor(actor, combat, actor_id, *, consume_position_sync=False,
                      force_position=False):
    if not combat:
        return
    entry = combat.get("actors", {}).get(actor_id)
    if not entry:
        return
    actor.current_hp = entry["data"].get("current_hp", actor.current_hp)
    actor.max_hp = entry["data"].get("max_hp", actor.max_hp)
    actor.downed = bool(entry["downed"])
    actor.conditions = deepcopy(entry["data"].get("conditions", []))
    actor.active_effects = deepcopy(entry["data"].get("active_effects", []))
    actor.inventory = deepcopy(entry["data"].get("inventory", actor.inventory))
    actor.personal_storage = deepcopy(entry["data"].get(
        "personal_storage", getattr(actor, "personal_storage", [])))
    inventory_ids = {item.get("id") for item in actor.inventory}
    quick_items = actor.quick_items if isinstance(actor.quick_items, dict) else {}
    actor.quick_items = {
        key: item_id if item_id in inventory_ids else None
        for key, item_id in {"q": None, "e": None, **quick_items}.items()
    }
    # Hotbar and quick-slot assignments are local control preferences. Keep
    # the local save authoritative instead of overwriting it from a network
    # combat snapshot that may predate the player's assignment.
    actor.equipment = deepcopy(entry["data"].get("equipment", actor.equipment))
    actor.abilities = deepcopy(entry["data"].get("abilities", actor.abilities))
    actor.attribute_points_spent = deepcopy(entry["data"].get(
        "attribute_points_spent", actor.attribute_points_spent))
    actor.active_weapon_set = entry["data"].get("active_weapon_set", actor.active_weapon_set)
    actor.xp_total = entry["data"].get("xp_total", actor.xp_total)
    actor.xp_earned_by_level = deepcopy(
        entry["data"].get("xp_earned_by_level", actor.xp_earned_by_level))
    actor.xp_spent_by_level = deepcopy(
        entry["data"].get("xp_spent_by_level", actor.xp_spent_by_level))
    actor.xp_rest_spent_by_level = deepcopy(
        entry["data"].get("xp_rest_spent_by_level", actor.xp_rest_spent_by_level))
    actor.spell_points = entry["data"].get("spell_points", actor.spell_points)
    actor.class_resources = deepcopy(
        entry["data"].get("class_resources", actor.class_resources))
    actor.gold = entry["data"].get("gold", actor.gold)
    actor.level = entry["data"].get("level", actor.level)
    actor.classes = deepcopy(entry["data"].get("classes", actor.classes))
    actor.class_spell_purchases = deepcopy(entry["data"].get(
        "class_spell_purchases", actor.class_spell_purchases))
    actor.class_ability_purchases = deepcopy(entry["data"].get(
        "class_ability_purchases", actor.class_ability_purchases))
    actor.class_feature_purchases = deepcopy(entry["data"].get(
        "class_feature_purchases", actor.class_feature_purchases))
    actor.class_skill_purchases = deepcopy(entry["data"].get(
        "class_skill_purchases", actor.class_skill_purchases))
    actor.skills = deepcopy(entry["data"].get("skills", actor.skills))
    actor.known_spells = deepcopy(entry["data"].get("known_spells", actor.known_spells))
    actor.prepared_spells = deepcopy(entry["data"].get("prepared_spells", actor.prepared_spells))
    actor.known_abilities = deepcopy(entry["data"].get("known_abilities", actor.known_abilities))
    actor.class_features = deepcopy(entry["data"].get(
        "class_features", actor.class_features))
    actor.expertise_skills = deepcopy(entry["data"].get(
        "expertise_skills", actor.expertise_skills))
    actor.fighting_styles = deepcopy(entry["data"].get(
        "fighting_styles", actor.fighting_styles))
    actor.weapon_masteries = deepcopy(entry["data"].get(
        "weapon_masteries", actor.weapon_masteries))
    actor.sneaking = bool(entry["data"].get("sneaking", actor.sneaking))
    actor.stealth_check_total = entry["data"].get(
        "stealth_check_total", actor.stealth_check_total)
    actor.hidden = deepcopy(entry["data"].get("hidden", actor.hidden))
    actor.withdrawn = bool(entry["data"].get("withdrawn", False))
    actor.outdoor_rest_streak = entry["data"].get(
        "outdoor_rest_streak", actor.outdoor_rest_streak)
    # Exploration owns the live position after a fight. The retained combat
    # snapshot is intentionally static while world mobs/corpses persist; copying
    # its old coordinates every frame makes exploration movement snap back.
    force_position_sync = (entry["data"].get("_force_position_sync")
                           or combat.get("rest_position_sync"))
    if (force_position or entry["data"].get("withdrawn") or combat.get("active")
            or force_position_sync):
        actor.x, actor.y = entry["x"], entry["y"]
    if consume_position_sync:
        entry["data"].pop("_force_position_sync", None)
        if combat.get("rest_position_sync"):
            combat.pop("rest_position_sync", None)
