"""Validate the active campaign's content references and route graph.

Run with ``python -m worldforge.content.validate_campaign``.
"""
import sys

from worldforge.content.campaign import ACTIVE_CAMPAIGN
from worldforge.content.classes import (ARENAS, EQUIPMENT_ITEMS, NPCS,
                                        SCENARIOS)
from worldforge.core.runtime_paths import asset_path


def validate_active_campaign():
    campaign = ACTIVE_CAMPAIGN
    errors = []
    scenario_ids = set(campaign["scenarios"])
    if campaign["starting_scenario"] not in scenario_ids:
        errors.append("starting_scenario must be listed in scenarios")
    if campaign["starting_scenario"] not in SCENARIOS:
        errors.append(
            f"unknown starting scenario '{campaign['starting_scenario']}'")
    if campaign["safe_camp_arena"] not in ARENAS:
        errors.append(f"unknown safe camp arena '{campaign['safe_camp_arena']}'")

    for scenario_id in sorted(scenario_ids):
        scenario = SCENARIOS.get(scenario_id)
        if scenario is None:
            errors.append(f"unknown scenario '{scenario_id}'")
            continue
        arena_id = scenario.get("arena")
        arena = ARENAS.get(arena_id)
        if arena is None:
            errors.append(f"scenario '{scenario_id}' references unknown arena '{arena_id}'")
            continue
        for index, spawn in enumerate(scenario.get("enemies", [])):
            npc_id = spawn.get("npc")
            if npc_id not in NPCS:
                errors.append(
                    f"scenario '{scenario_id}' enemy {index} references unknown NPC '{npc_id}'")
            else:
                avatar = NPCS[npc_id].get("avatar")
                if avatar and not asset_path(avatar).is_file():
                    errors.append(
                        f"NPC '{npc_id}' has missing avatar '{avatar}'")
        for npc_id in scenario.get("mob_pool", []):
            if npc_id not in NPCS:
                errors.append(
                    f"scenario '{scenario_id}' mob_pool references unknown NPC '{npc_id}'")
            else:
                avatar = NPCS[npc_id].get("avatar")
                if avatar and not asset_path(avatar).is_file():
                    errors.append(
                        f"NPC '{npc_id}' has missing avatar '{avatar}'")
        for index, spawn in enumerate(scenario.get("player_spawns", [])):
            if not isinstance(spawn, (list, tuple)) or len(spawn) != 2:
                errors.append(
                    f"scenario '{scenario_id}' player_spawns[{index}] must be [x, y]")

        for group in ("trainers", "vendors", "innkeepers"):
            for npc in arena.get(group, []):
                avatar = npc.get("avatar")
                if avatar and not asset_path(avatar).is_file():
                    errors.append(
                        f"arena '{arena_id}' {group} '{npc.get('id')}' has missing avatar '{avatar}'")
        used_npc_ids = {spawn.get("npc") for spawn in scenario.get("enemies", [])}
        used_npc_ids.update(scenario.get("mob_pool", []))
        for npc_id in used_npc_ids.intersection(NPCS):
            npc = NPCS[npc_id]
            for slot, item in (npc.get("equipment", {}) or {}).items():
                template_id = item.get("template_id")
                if template_id and template_id not in EQUIPMENT_ITEMS:
                    errors.append(
                        f"NPC '{npc_id}' equipment '{slot}' references unknown item '{template_id}'")
        for group in ("chests", "personal_chests"):
            for chest in arena.get(group, []):
                for loot in chest.get("loot", []):
                    item_id = loot.get("template_id") or loot.get("item_id")
                    if item_id and item_id not in EQUIPMENT_ITEMS:
                        errors.append(
                            f"arena '{arena_id}' chest '{chest.get('id')}' references unknown item '{item_id}'")
                if (chest.get("kind") == "personal_chest"
                        and chest.get("storage_scope") not in {"inn", "camp"}):
                    errors.append(
                        f"arena '{arena_id}' personal chest '{chest.get('id')}' needs storage_scope 'inn' or 'camp'")
                if chest.get("kind") == "personal_chest":
                    beds = arena.get("inn_beds" if chest.get("storage_scope") == "inn"
                                     else "camp_beds", [])
                    if chest.get("bed_id") not in {bed.get("id") for bed in beds}:
                        errors.append(
                            f"arena '{arena_id}' personal chest '{chest.get('id')}' references an unknown bed")
        for vendor in arena.get("vendors", []):
            for stock in vendor.get("stock", []):
                item_id = stock.get("item_id")
                if item_id and item_id not in EQUIPMENT_ITEMS:
                    errors.append(
                        f"arena '{arena_id}' vendor '{vendor.get('id')}' references unknown item '{item_id}'")

    routes = {}
    for index, route in enumerate(campaign["map_connections"]):
        source_id = route.get("from")
        target_id = route.get("to")
        exit_id = route.get("exit")
        route_key = (source_id, exit_id)
        if route_key in routes:
            errors.append(f"duplicate map route from '{source_id}' through '{exit_id}'")
        routes[route_key] = route
        if source_id not in scenario_ids or target_id not in scenario_ids:
            errors.append(
                f"map_connections[{index}] must connect scenarios listed by the campaign")
            continue
        source_scenario = SCENARIOS.get(source_id, {})
        target_scenario = SCENARIOS.get(target_id, {})
        source_arena = ARENAS.get(source_scenario.get("arena"), {})
        target_arena = ARENAS.get(target_scenario.get("arena"), {})
        source_exit = next((item for item in source_arena.get("exits", [])
                            if item.get("id") == exit_id), None)
        destination_exit_id = route.get("destination_exit")
        destination_exit = next((item for item in target_arena.get("exits", [])
                                 if item.get("id") == destination_exit_id), None)
        if not source_exit:
            errors.append(
                f"route '{source_id}' -> '{target_id}' references missing exit '{exit_id}'")
            continue
        if source_exit.get("destination_scenario") != target_id:
            errors.append(
                f"exit '{source_id}.{exit_id}' does not lead to '{target_id}'")
        if source_exit.get("destination_exit_id") != destination_exit_id:
            errors.append(
                f"exit '{source_id}.{exit_id}' destination_exit_id does not match the manifest")
        if not destination_exit:
            errors.append(
                f"route '{source_id}' -> '{target_id}' references missing reciprocal exit '{destination_exit_id}'")
        elif (destination_exit.get("destination_scenario") != source_id
              or destination_exit.get("destination_exit_id") != exit_id):
            errors.append(
                f"exit '{target_id}.{destination_exit_id}' is not reciprocal to '{source_id}.{exit_id}'")

    for source_id in scenario_ids:
        arena_id = SCENARIOS.get(source_id, {}).get("arena")
        for exit_record in ARENAS.get(arena_id, {}).get("exits", []):
            target_id = exit_record.get("destination_scenario")
            if target_id in scenario_ids and (source_id, exit_record.get("id")) not in routes:
                errors.append(
                    f"exit '{source_id}.{exit_record.get('id')}' is missing from campaign map_connections")

    if campaign["party_limit"] > 8:
        errors.append("party_limit above 8 is not supported by current spawn and camp layouts")
    starting = SCENARIOS.get(campaign["starting_scenario"], {})
    if len(starting.get("player_spawns", [])) < campaign["party_limit"]:
        errors.append(
            "starting scenario needs at least one player spawn per party member")
    camp = ARENAS.get(campaign["safe_camp_arena"], {})
    if len(camp.get("camp_beds", [])) < campaign["party_limit"]:
        errors.append("safe camp needs at least one bedroll per party member")
    for system_name, enabled in campaign["enabled_systems"].items():
        if not isinstance(enabled, bool):
            errors.append(f"enabled_systems.{system_name} must be true or false")
    for rule_name, value in campaign["rules"].items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"rules.{rule_name} must be numeric")
    rest_min = campaign["rules"].get("outdoor_rest_rate_min_percent", 1)
    rest_max = campaign["rules"].get("outdoor_rest_rate_max_percent", 5)
    if (isinstance(rest_min, (int, float)) and not isinstance(rest_min, bool)
            and isinstance(rest_max, (int, float)) and not isinstance(rest_max, bool)
            and rest_max < rest_min):
        errors.append("maximum outdoor rest rate cannot be below the minimum")
    return errors


def main():
    errors = validate_active_campaign()
    if errors:
        print(f"Campaign '{ACTIVE_CAMPAIGN['name']}' has content errors:",
              file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Campaign '{ACTIVE_CAMPAIGN['name']}' content is valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
