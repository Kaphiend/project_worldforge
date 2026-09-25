"""Runtime controller interfaces shared by player and non-player actors."""
from worldforge.combat.rules import edge_distance_feet, selected_weapon
from worldforge.app.world import _hidden_from
from worldforge.actors.factory import item_definition
from worldforge.content.classes import ABILITIES, MOB_GENERATION_RULES


class Controller:
    """A controller chooses actions; the host remains responsible for resolving them."""

    kind = "base"

    def actions_for_turn(self, context):
        return []


class PlayerController(Controller):
    kind = "player"


class AIController(Controller):
    """Data-tuned tactical brain; action resolution stays in the host engine."""

    kind = "ai"

    def actions_for_turn(self, context):
        combat = context["combat"]
        actor_id = context["actor_id"]
        actor = combat["actors"][actor_id]
        actor_data = actor["data"]
        ai_rules = MOB_GENERATION_RULES.get("ai", {})
        profile = dict(ai_rules.get("default", {}))
        if isinstance(actor_data.get("ai"), dict):
            profile.update(actor_data["ai"])
        targets = [entry for entry in combat["actors"].values()
                   if entry["team"] == "players" and not entry["downed"]
                   and not _hidden_from(actor, entry, combat.get("arena"))]
        if not targets:
            return [{"type": "end_turn"}]
        policy = profile.get("target_policy", "nearest")
        if policy == "weakest":
            target = min(targets, key=lambda entry: (
                entry["data"].get("current_hp", 1) /
                max(1, entry["data"].get("max_hp", 1)),
                edge_distance_feet(actor, entry)))
        elif policy == "lowest_hp":
            target = min(targets, key=lambda entry: (
                entry["data"].get("current_hp", 1),
                edge_distance_feet(actor, entry)))
        elif policy == "highest_threat":
            target = max(targets, key=lambda entry: (
                int(entry["data"].get("level", 1) or 1),
                -edge_distance_feet(actor, entry)))
        else:
            target = min(targets, key=lambda entry: edge_distance_feet(actor, entry))
        target_id = target["id"]
        weapon, definition, _ = selected_weapon(actor_data)
        ranged = bool(weapon) and (
            actor_data.get("active_weapon_set") == "ranged"
            and weapon == actor_data.get("equipment", {}).get("ranged")
        )
        ranges = definition.get("ranges", {}) if definition else {}
        reach = float(ranges.get("melee", profile.get("melee_reach_feet", 5)))
        edge_distance = edge_distance_feet(actor, target)
        actions = self._tactical_abilities(actor_id, actor, target, profile)
        if actions and ABILITIES.get(
                actions[0].get("ability"), {}).get("action_cost") == "action":
            return actions + [{"type": "end_turn"}]
        if ranged:
            max_range = float(ranges.get("long", ranges.get("normal", 0)) or 0)
            if edge_distance > max_range and profile.get("close_when_out_of_range", True):
                actions.extend(self._move_toward(
                    actor, target, edge_distance - max_range,
                    context["pixels_per_foot"], combat))
            actions.append({"type": "attack", "target": target_id})
        elif definition and "thrown" in definition.get("tags", []) and edge_distance > reach:
            actions.append({"type": "throw", "target": target_id})
        elif edge_distance > reach:
            movement = combat["budgets"][actor_id]["movement"]
            actions.extend(self._move_toward(
                actor, target, edge_distance - reach,
                context["pixels_per_foot"], combat))
            if movement >= edge_distance - reach:
                actions.append({"type": "attack", "target": target_id})
        else:
            actions.append({"type": "attack", "target": target_id})

        equipment = actor_data.get("equipment", {}) or {}
        main = equipment.get("main_hand")
        off = equipment.get("off_hand")
        spent_bonus_action = bool(actions and ABILITIES.get(
            actions[0].get("ability"), {}).get("action_cost") == "bonus_action")
        if (profile.get("use_offhand_attacks", True) and main and off
                and not spent_bonus_action
                and main.get("id", id(main)) != off.get("id", id(off))
                and "light" in (item_definition(main).get("tags", []) or [])
                and "light" in (item_definition(off).get("tags", []) or [])
                and (actor_data.get("weapon_masteries", {}) or {}).get(
                    main.get("template_id", main.get("id"))) != "nick"):
            actions.append({"type": "offhand_attack", "target": target_id})
        actions.append({"type": "end_turn"})
        return actions

    @staticmethod
    def _move_toward(actor, target, desired_distance, pixels_per_foot, combat):
        """Return a movement action that closes only the required gap."""
        if desired_distance <= 0:
            return []
        actor_cx = actor["x"] + actor["width"] / 2
        actor_cy = actor["y"] + actor["height"] / 2
        target_cx = target["x"] + target["width"] / 2
        target_cy = target["y"] + target["height"] / 2
        dx, dy = target_cx - actor_cx, target_cy - actor_cy
        length = max(1.0, (dx * dx + dy * dy) ** 0.5)
        movement = combat["budgets"][actor["id"]]["movement"]
        travel = min(movement, desired_distance)
        pixels = travel * pixels_per_foot
        return [{"type": "move", "x": actor["x"] + dx / length * pixels,
                 "y": actor["y"] + dy / length * pixels}] if travel > 0 else []

    @staticmethod
    def _tactical_abilities(actor_id, actor, target, profile):
        """Use configured, known abilities when their tactical trigger fits."""
        known = set(actor["data"].get("known_abilities", []) or [])
        priorities = profile.get("ability_priority", []) or []
        hp_fraction = (actor["data"].get("current_hp", 1) /
                       max(1, actor["data"].get("max_hp", 1)))
        for ability_id in priorities:
            if ability_id not in known:
                continue
            definition = ABILITIES.get(ability_id, {})
            targeting = definition.get("targeting", {}) or {}
            mode = targeting.get("mode", "self")
            if mode == "self":
                target_id = actor_id
            elif mode in {"one_target", "one_enemy"}:
                target_id = target["id"]
            else:
                continue
            if (definition.get("healing") or any(
                    effect.get("kind") == "healing"
                    for effect in definition.get("effects", []) or [])):
                if hp_fraction > float(profile.get("heal_below_fraction", 0.4)):
                    continue
            if ability_id == "barbarian_rage" and any(
                    effect.get("source_id") == ability_id
                    for effect in actor["data"].get("active_effects", []) or []):
                continue
            return [{"type": "use_ability", "ability": ability_id,
                     "target": target_id}]
        return []


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
