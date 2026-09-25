"""Dispatch typed hotbar actions from mouse and keyboard input."""
from worldforge.ui.spellbook import action_definition


ACTION_TYPES = {
    "weapon_attack": "attack",
    "unarmed_strike": "unarmed_strike",
    "ranged_weapon_attack": "ranged_attack",
    "throw_weapon": "throw",
    "hide": "hide",
    "flee": "flee",
}


def dispatch_hotbar_action(assigned_action, selected_target, submit,
                           toggle_sneaking, *, notify_missing_target):
    """Dispatch a hotbar entry; return (consumed, missing-target-notice)."""
    if not assigned_action:
        return False, None
    action_kind, action_id, definition = action_definition(assigned_action)
    if not definition:
        return False, None

    targeting = definition.get("targeting", {})
    needs_target = targeting.get("mode") != "self"
    # Number-key behavior historically skipped target-required actions without
    # a target, while clicking a hotbar slot displayed a short notice.
    target_required_for_input = (
        needs_target if notify_missing_target
        else bool(action_kind == "spell" or targeting) and needs_target)
    if target_required_for_input and not selected_target:
        if notify_missing_target:
            return True, "Select a target first."
        return False, None

    if action_kind == "action":
        if action_id == "sneak":
            toggle_sneaking()
        else:
            action_type = ACTION_TYPES.get(action_id)
            if not action_type:
                return False, None
            submit({"type": action_type, "target": selected_target})
    elif action_kind == "spell":
        submit({"type": "cast_spell", "spell": action_id,
                "target": selected_target})
    else:
        submit({"type": "use_ability", "ability": action_id,
                "target": selected_target})
    return True, None
