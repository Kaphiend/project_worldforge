"""Ground item pickup and corpse loot actions."""
from copy import deepcopy
import uuid
import pygame

from worldforge.actors.factory import item_definition
from worldforge.app.combat_flow import _log
from worldforge.app.encounters import CORPSE_DESPAWN_MS
from worldforge.app.rendering import _player_id
from worldforge.app.world import ACTOR_SIZE, PIXELS_PER_FOOT
from worldforge.combat.rules import edge_distance_feet


def handle_loot_action(actor, local_player_id, actor_id, action,
                       remote_players, combat):
    action_type = action.get("type")
    if action_type not in {"pickup_ground_item", "loot_take",
                           "loot_take_all", "loot_finish"}:
        return None
    if action.get("type") == "pickup_ground_item":
        if not combat or combat.get("active") or combat.get("rest_session"):
            return {"_action_error": "You cannot pick up items right now."}
        entry = combat.get("actors", {}).get(actor_id)
        if not entry or entry.get("team") != "players":
            return {"_action_error": "Character is unavailable."}
        ground_item = next((item for item in combat.get("ground_items", [])
                            if item.get("id") == action.get("item_id")), None)
        if not ground_item:
            return {"_action_error": "That item is no longer on the ground."}
        position = {"x": actor.x, "y": actor.y,
                    "width": ACTOR_SIZE, "height": ACTOR_SIZE}
        if actor_id != local_player_id:
            remote = next((item for item in remote_players
                           if _player_id(item) == actor_id), None)
            if not remote:
                return {"_action_error": "Character is unavailable."}
            position["x"] = remote.get("x", entry.get("x", 0))
            position["y"] = remote.get("y", entry.get("y", 0))
        if edge_distance_feet(position, ground_item, PIXELS_PER_FOOT,
                              ACTOR_SIZE) > 5:
            return {"_action_error": "Move within 5 feet of the item to pick it up."}
        ground_item = combat["ground_items"].pop(
            next(index for index, item in enumerate(combat["ground_items"])
                 if item.get("id") == action.get("item_id")))
        item = deepcopy(ground_item.get("item", {}))
        if not item:
            return {"_action_error": "That item is unavailable."}
        entry["data"].setdefault("inventory", []).append(item)
        _log(combat, f"{entry['data'].get('name', actor_id)} picks up {item.get('name', 'an item')}. It must be equipped from inventory.")
        return combat
    if action.get("type") in {"loot_take", "loot_take_all", "loot_finish"}:
        if not combat or combat.get("active"):
            return {"_action_error": "There is no corpse available to loot."}
        corpse_id = action.get("target")
        corpse = combat.get("actors", {}).get(corpse_id)
        if (not corpse or corpse.get("team") != "enemies"
                or not corpse.get("downed")):
            return {"_action_error": "That corpse is no longer available."}
        now = pygame.time.get_ticks()
        expiry = corpse.get("corpse_despawn_at")
        if expiry is not None and now >= expiry:
            return {"_action_error": "That corpse has already been looted and is gone."}
        player_entry = combat.get("actors", {}).get(actor_id)
        owner = (player_entry.get("data") if player_entry else
                 (actor if actor_id == local_player_id else next(
                     (remote.get("actor") for remote in remote_players
                      if _player_id(remote) == actor_id and remote.get("actor")), None)))
        if owner is None:
            return {"_action_error": "Character is unavailable."}
        data = owner if isinstance(owner, dict) else vars(owner)
        if actor_id == local_player_id:
            loot_x, loot_y = actor.x, actor.y
        else:
            remote = next((item for item in remote_players
                           if _player_id(item) == actor_id), {})
            loot_x, loot_y = remote.get("x", data.get("x", 0)), remote.get("y", data.get("y", 0))
        loot_position = {"x": loot_x, "y": loot_y,
                         "width": ACTOR_SIZE, "height": ACTOR_SIZE}
        distance = edge_distance_feet(loot_position, corpse,
                                      PIXELS_PER_FOOT, ACTOR_SIZE)
        if distance > 5:
            return {"_action_error": "Move within 5 feet of the corpse to loot it."}

        loot = corpse.setdefault("loot", [])
        if action["type"] in {"loot_take", "loot_take_all"}:
            if action["type"] == "loot_take_all":
                claimed = list(loot)
                loot.clear()
            else:
                item_id = action.get("item_id")
                item = next((item for item in loot if item.get("id") == item_id), None)
                if item is None:
                    return {"_action_error": "That item has already been taken."}
                claimed = [item]
                loot.remove(item)
            inventory = data.setdefault("inventory", [])
            for item in claimed:
                definition = item_definition(item)
                template_id = item.get("template_id")
                quantity = max(1, int(item.get("quantity", 1) or 1))
                if definition.get("stackable") and template_id:
                    max_stack = max(1, int(definition.get("max_stack", 99)))
                    remaining = quantity
                    for existing in inventory:
                        if existing.get("template_id") != template_id:
                            continue
                        current = max(1, int(existing.get("quantity", 1) or 1))
                        added = min(remaining, max(0, max_stack - current))
                        existing["quantity"] = current + added
                        remaining -= added
                        if not remaining:
                            break
                    while remaining:
                        added = min(remaining, max_stack)
                        copy_item = deepcopy(item)
                        copy_item["id"] = uuid.uuid4().hex[:12]
                        copy_item["quantity"] = added
                        inventory.append(copy_item)
                        remaining -= added
                else:
                    inventory.append(deepcopy(item))
            if not loot:
                # Taking the last individual item ends looting just like Take
                # All or Done, so the corpse gets the same cleanup timer.
                corpse["corpse_despawn_at"] = now + CORPSE_DESPAWN_MS
            if player_entry:
                player_entry["data"].update(data)
            for item in claimed:
                _log(combat, f"{data.get('name', actor_id)} takes {item.get('name', 'an item')} from the shared loot.")
            if action["type"] == "loot_take_all":
                corpse["corpse_despawn_at"] = now + CORPSE_DESPAWN_MS
            return combat

        if corpse.get("corpse_despawn_at") is None:
            corpse["corpse_despawn_at"] = now + CORPSE_DESPAWN_MS
        _log(combat, f"Looting {corpse.get('data', {}).get('name', 'the corpse')} ends.")
        return combat
