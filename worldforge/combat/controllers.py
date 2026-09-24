"""Runtime controller interfaces shared by player and non-player actors."""
from worldforge.combat.rules import edge_distance_feet, selected_weapon


class Controller:
    """A controller chooses actions; the host remains responsible for resolving them."""

    kind = "base"

    def actions_for_turn(self, context):
        return []


class PlayerController(Controller):
    kind = "player"


class AIController(Controller):
    """Small default brain: pursue the nearest conscious player and attack."""

    kind = "ai"

    def actions_for_turn(self, context):
        combat = context["combat"]
        actor_id = context["actor_id"]
        actor = combat["actors"][actor_id]
        targets = [entry for entry in combat["actors"].values()
                   if entry["team"] == "players" and not entry["downed"]]
        if not targets:
            return [{"type": "end_turn"}]
        target = min(targets, key=lambda entry: edge_distance_feet(actor, entry))
        target_id = target["id"]
        weapon, definition, _ = selected_weapon(actor["data"])
        if weapon is None:
            return [{"type": "end_turn"}]

        ranged = (
            actor["data"].get("active_weapon_set") == "ranged"
            and weapon == actor["data"].get("equipment", {}).get("ranged")
        )
        ranges = definition.get("ranges", {})
        reach = ranges.get("melee", 5)
        edge_distance = edge_distance_feet(actor, target)
        if ranged or ("thrown" in definition.get("tags", []) and edge_distance > reach):
            return [{"type": "attack", "target": target_id}, {"type": "end_turn"}]

        actions = []
        if edge_distance > reach:
            actor_cx = actor["x"] + actor["width"] / 2
            actor_cy = actor["y"] + actor["height"] / 2
            target_cx = target["x"] + target["width"] / 2
            target_cy = target["y"] + target["height"] / 2
            dx, dy = target_cx - actor_cx, target_cy - actor_cy
            length = max(1.0, (dx * dx + dy * dy) ** 0.5)
            current_budget = combat["budgets"][actor_id]["movement"]
            travel_feet = min(current_budget, edge_distance - reach)
            travel_pixels = travel_feet * context["pixels_per_foot"]
            actions.append({
                "type": "move",
                "x": actor["x"] + dx / length * travel_pixels,
                "y": actor["y"] + dy / length * travel_pixels,
            })
            if edge_distance - travel_feet <= reach:
                actions.append({"type": "attack", "target": target_id})
        actions.append({"type": "end_turn"})
        return actions


class ScriptedController(Controller):
    kind = "scripted"

    def __init__(self, action_provider=None):
        self.action_provider = action_provider

    def actions_for_turn(self, context):
        return list(self.action_provider(context) or []) if self.action_provider else []


_DEFAULT_CONTROLLERS = {
    "player": PlayerController,
    "ai": AIController,
    "scripted": ScriptedController,
}


def controller_for(actor, custom_controllers=None):
    """Resolve a saved controller id to its runtime brain."""
    kind = actor.get("controller", "player")
    if custom_controllers and kind in custom_controllers:
        return custom_controllers[kind]
    controller_type = _DEFAULT_CONTROLLERS.get(kind, PlayerController)
    return controller_type()


def swap_controller(actor, controller_id):
    """Swap an actor's saved controller id and return the previous id."""
    if isinstance(actor, dict):
        previous = actor.get("controller", "player")
        actor["controller"] = controller_id
    else:
        previous = getattr(actor, "controller", "player")
        actor.controller = controller_id
    return previous
