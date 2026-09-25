"""Validate and apply transfers to actor-owned chests."""
from copy import deepcopy


def handle_storage_action(actor, actor_id, action, remote_players, combat):
    if action.get("type") not in {"storage_deposit", "storage_withdraw"}:
        return None
    if combat and combat.get("active"):
        return {"_action_error": "Personal storage is unavailable during combat."}
    entry = (combat or {}).get("actors", {}).get(actor_id)
    if not entry or entry.get("team") != "players":
        return {"_action_error": "That character is not available."}
    chest = next((item for item in (combat.get("arena", {}).get("personal_chests", [])
                                    if combat else [])
                  if item.get("id") == action.get("chest_id")), None)
    if not chest or chest.get("owner_id") != actor_id:
        return {"_action_error": "This personal chest is not assigned to you."}
    session = combat.get("rest_session") if combat else None
    if chest.get("storage_scope") == "inn":
        if (session and session.get("location") == "inn"
                and (actor_id not in session.get("paid", {})
                     or session.get("bed_by_actor", {}).get(actor_id)
                     != chest.get("bed_id"))):
            return {"_action_error": "Pay for your inn room before using its chest."}
    elif (chest.get("storage_scope") != "camp" or not session
            or session.get("location") != "outdoor" or session.get(
            "bed_by_actor", {}).get(actor_id) != chest.get("bed_id")):
        return {"_action_error": "You can only use your chest while at your assigned camp bed."}
    data = entry["data"]
    inventory = data.setdefault("inventory", [])
    storage = data.setdefault("personal_storage", [])
    source = inventory if action["type"] == "storage_deposit" else storage
    target = storage if action["type"] == "storage_deposit" else inventory
    item = next((item for item in source if item.get("id") == action.get("item_id")), None)
    if not item:
        return {"_action_error": "That item is no longer available."}
    source.remove(item)
    target.append(deepcopy(item))
    if action["type"] == "storage_deposit":
        quick = data.get("quick_items", {})
        for slot, item_id in list(quick.items()):
            if item_id == item.get("id"):
                quick[slot] = None
    return combat
