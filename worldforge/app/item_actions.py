"""Combat and exploration use of inventory items."""
from worldforge.actors.factory import item_definition
from worldforge.app.combat_flow import (
    _animate_hp_changes, _log, _reject_action, _remove_downed_from_order,
    _restore_revived_order,
)
from worldforge.app.encounters import DEFAULT_SCENARIO
from worldforge.app.rendering import _capture_hp, _player_id
from worldforge.app.world import _line_of_sight
from worldforge.combat.spell_effects import resolve_spell
from worldforge.content.campaign import campaign_rule
from worldforge.content.classes import ARENAS, SCENARIOS, SPELLS
from worldforge.core.progression import charge_xp_penalty


def _do_item(combat, actor_id, item_id, target_id=None):
    entry = combat.get("actors", {}).get(actor_id)
    if not entry or entry.get("downed"):
        _reject_action(combat, "A downed actor cannot use an item.", actor_id)
        return False
    budget = combat.get("budgets", {}).get(actor_id, {})
    if not budget.get("action"):
        _reject_action(combat, "Action already used this turn.", actor_id)
        return False
    item = next((item for item in entry["data"].get("inventory", [])
                 if item.get("id") == item_id), None)
    if not item:
        _reject_action(combat, "That item is not in your inventory.", actor_id)
        return False
    definition = item_definition(item)
    effect_id = definition.get("effect_id")
    if not effect_id or effect_id not in SPELLS:
        _reject_action(combat, "That item has no usable effect.", actor_id)
        return False
    target_entry = combat.get("actors", {}).get(target_id) if target_id else entry
    if not target_entry:
        _reject_action(combat, "Invalid target: select an available target first.", actor_id)
        return False
    if target_entry["data"].get("withdrawn"):
        _reject_action(combat, "That character has left the fight.", target_id)
        return False
    los = _line_of_sight(entry, target_entry, combat.get("arena"))
    hp_before = _capture_hp(combat)
    result = resolve_spell(effect_id, entry["data"], [target_entry["data"]],
                           line_of_sight=los, from_consumable=True)
    if not result.get("success"):
        _reject_action(combat, result.get("message", "Item could not be used."), target_id)
        return False
    stack_quantity = max(1, int(item.get("quantity", 1)))
    if stack_quantity > 1:
        item["quantity"] = stack_quantity - 1
    else:
        entry["data"]["inventory"].remove(item)
        quick_items = entry["data"].setdefault("quick_items", {})
        for key, quick_item in list(quick_items.items()):
            if quick_item == item_id:
                quick_items[key] = None
    budget["action"] = False
    for outcome in result.get("results", []):
        healing = sum(effect.get("amount", 0) for effect in outcome.get("effects", [])
                      if effect.get("kind") == "healing")
        _log(combat, f"{entry['data'].get('name', actor_id)} uses {definition.get('name', item.get('name'))} on {outcome['target']} ({healing} HP restored).")
    for current in combat["actors"].values():
        current["downed"] = bool(current["data"].get("downed", False)
                                  or current["data"].get("current_hp", 1) <= 0)
    _remove_downed_from_order(combat)
    _restore_revived_order(combat)
    _animate_hp_changes(combat, hp_before)
    return True

def _use_item_outside_combat(owner, item_id, target_id, local_player_id,
                             remote_players, arena=None):
    inventory = owner.get("inventory", []) if isinstance(owner, dict) else owner.inventory
    item = next((item for item in inventory if item.get("id") == item_id), None)
    if not item:
        return False
    definition = item_definition(item)
    effect_id = definition.get("effect_id")
    if not effect_id or effect_id not in SPELLS:
        return False
    owner_id = owner.get("id") if isinstance(owner, dict) else owner.id
    target = owner if target_id is None or target_id in (owner_id, local_player_id) else None
    if target is None:
        target = next((remote.get("actor") for remote in remote_players
                       if _player_id(remote) == target_id and remote.get("actor")), None)
    if target is None:
        return False
    caster_data = vars(owner) if not isinstance(owner, dict) else owner
    target_data = vars(target) if not isinstance(target, dict) else target
    arena = arena or ARENAS.get(
        SCENARIOS.get(DEFAULT_SCENARIO, {}).get("arena"), {})
    was_downed = bool(target_data.get("downed") or target_data.get("current_hp", 1) <= 0)
    result = resolve_spell(effect_id, caster_data, [target_data],
                           line_of_sight=_line_of_sight(caster_data, target_data, arena),
                           from_consumable=True)
    if not result.get("success"):
        return False
    if was_downed and not target_data.get("downed") and target_data.get("current_hp", 0) > 0:
        penalty = charge_xp_penalty(
            target_data, campaign_rule("revival_xp_penalty_percent", 2))
        if penalty:
            target_data["last_revival_xp_penalty"] = penalty
    stack_quantity = max(1, int(item.get("quantity", 1)))
    if stack_quantity > 1:
        item["quantity"] = stack_quantity - 1
    else:
        inventory.remove(item)
        quick_items = caster_data.setdefault("quick_items", {})
        for key, quick_item in list(quick_items.items()):
            if quick_item == item_id:
                quick_items[key] = None
    if not isinstance(owner, dict):
        owner.current_hp = caster_data.get("current_hp", owner.current_hp)
        owner.downed = caster_data.get("downed", owner.downed)
    if not isinstance(target, dict):
        target.current_hp = target_data.get("current_hp", target.current_hp)
        target.downed = target_data.get("downed", target.downed)
    return True
