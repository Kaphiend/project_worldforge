"""Vendor transactions and session buyback handling."""
from copy import deepcopy
import uuid

from worldforge.app.encounters import DEFAULT_SCENARIO, _progression_sync_state
from worldforge.app.rendering import _player_id
from worldforge.app.world import ACTOR_SIZE, PIXELS_PER_FOOT
from worldforge.combat.rules import edge_distance_feet
from worldforge.content.classes import ARENAS, EQUIPMENT_ITEMS, SCENARIOS


def _vendor_action(actor, local_player_id, actor_id, action, remote_players,
                   combat, vendor_state):
    """Validate and apply one session-only vendor transaction."""
    if combat and combat.get("active"):
        return {"_action_error": "You cannot trade during combat."}
    vendor_state = vendor_state if isinstance(vendor_state, dict) else {}
    buyback = vendor_state.setdefault("buyback", {}).setdefault(actor_id, [])
    entry = (combat or {}).get("actors", {}).get(actor_id)
    owner = (entry.get("data") if entry else
             actor if actor_id == local_player_id else next(
                 (remote.get("actor") for remote in remote_players
                  if _player_id(remote) == actor_id and remote.get("actor")), None))
    if owner is None:
        return {"_action_error": "Character is unavailable."}
    data = owner if isinstance(owner, dict) else vars(owner)
    if data.get("downed"):
        return {"_action_error": "A downed character cannot trade."}
    arena = (combat or {}).get("arena") or ARENAS.get(
        SCENARIOS.get(DEFAULT_SCENARIO, {}).get("arena"), {})
    vendor_id = action.get("vendor_id")
    vendor = next((item for item in arena.get("vendors", [])
                   if item.get("id") == vendor_id), None)
    if not vendor:
        return {"_action_error": "That vendor is unavailable on this map."}
    trade_position = data
    if actor_id == local_player_id:
        trade_position = dict(data, x=actor.x, y=actor.y)
        if entry:
            trade_position["hitbox"] = entry.get("data", {}).get("hitbox")
    distance = edge_distance_feet(
        trade_position, vendor, PIXELS_PER_FOOT, ACTOR_SIZE)
    if distance > int(vendor.get("interaction_range_feet", 5)):
        return {"_action_error": "Move closer to the vendor to trade."}

    trade = action.get("type")
    price = 10
    if trade == "vendor_buy":
        stock = next((item for item in vendor.get("stock", [])
                      if item.get("id") == action.get("stock_id")), None)
        if not stock:
            return {"_action_error": "That item is not sold by this vendor."}
        template_id = stock.get("item_id")
        definition = EQUIPMENT_ITEMS.get(template_id)
        if not definition:
            return {"_action_error": "The vendor's item definition is missing."}
        price = max(0, int(stock.get("price", price) or 0))
        quantity = int(action.get("quantity", 1) or 1)
        if not 1 <= quantity <= 99:
            return {"_action_error": "Purchase quantity must be between 1 and 99."}
        if quantity > 1 and not definition.get("stackable"):
            return {"_action_error": "Only stackable items can be purchased in multiples."}
        total_price = price * quantity
        if int(data.get("gold", 0) or 0) < total_price:
            return {"_action_error": f"You need {total_price} gold to buy that item."}
        item = {"id": uuid.uuid4().hex[:12], "template_id": template_id,
                "name": definition.get("name", template_id), "quantity": quantity}
        data["gold"] = int(data.get("gold", 0) or 0) - total_price
        inventory = data.setdefault("inventory", [])
        if definition.get("stackable"):
            remaining = quantity
            max_stack = max(1, int(definition.get("max_stack", 99) or 99))
            for stack in inventory:
                if stack.get("template_id") != template_id:
                    continue
                quantity = max(1, int(stack.get("quantity", 1) or 1))
                added = min(remaining, max_stack - quantity)
                if added > 0:
                    stack["quantity"] = quantity + added
                    remaining -= added
                if not remaining:
                    break
            while remaining:
                quantity = min(remaining, max_stack)
                stack = deepcopy(item)
                stack["quantity"] = quantity
                inventory.append(stack)
                remaining -= quantity
        else:
            inventory.append(item)
        message = f"Bought {quantity} {item['name']} for {total_price} gold."
    elif trade == "vendor_sell":
        item_id = action.get("item_id")
        item = next((item for item in data.get("inventory", [])
                     if item.get("id") == item_id), None)
        if not item:
            return {"_action_error": "That item is no longer in your inventory."}
        sold = deepcopy(item)
        quantity = max(1, int(item.get("quantity", 1) or 1))
        if quantity > 1:
            item["quantity"] = quantity - 1
            sold["id"] = uuid.uuid4().hex[:12]
            sold["quantity"] = 1
        else:
            data["inventory"].remove(item)
            quick = data.setdefault("quick_items", {})
            for key, bound_id in list(quick.items()):
                if bound_id == item_id:
                    quick[key] = None
        buyback.append(sold)
        data["gold"] = int(data.get("gold", 0) or 0) + price
        message = f"Sold {sold.get('name', sold.get('template_id', 'item'))} for 10 gold."
    elif trade == "vendor_buyback":
        item_id = action.get("item_id")
        item = next((item for item in buyback if item.get("id") == item_id), None)
        if not item:
            return {"_action_error": "That item is no longer in buyback."}
        if int(data.get("gold", 0) or 0) < price:
            return {"_action_error": "You need 10 gold to buy that item back."}
        buyback.remove(item)
        data["gold"] = int(data.get("gold", 0) or 0) - price
        data.setdefault("inventory", []).append(item)
        message = f"Bought back {item.get('name', item.get('template_id', 'item'))} for 10 gold."
    else:
        return {"_action_error": "Unknown vendor transaction."}

    if combat and entry:
        combat["vendor_buyback"] = deepcopy(vendor_state["buyback"])
        combat["_action_notice"] = message
        combat["vendor_state_changed"] = True
        return combat
    snapshot = _progression_sync_state(actor, local_player_id, remote_players)
    snapshot["vendor_buyback"] = deepcopy(vendor_state["buyback"])
    snapshot["_action_notice"] = message
    snapshot["vendor_state_changed"] = True
    return snapshot
