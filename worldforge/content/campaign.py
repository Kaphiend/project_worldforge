"""Active campaign manifest and campaign-scoped settings."""
import json
import os
import sys

from worldforge.core.runtime_paths import resource_path, user_data_path


DEFAULT_CAMPAIGN_ID = "demo_slice"
_roots = [resource_path("data", "mods")]
if getattr(sys, "frozen", False):
    _roots.append(user_data_path("mods"))


def _load_active_campaign():
    campaign_id = os.environ.get("WORLDFORGE_CAMPAIGN", DEFAULT_CAMPAIGN_ID).strip()
    if not campaign_id or any(part in campaign_id for part in ("/", "\\", "..")):
        raise ValueError("WORLDFORGE_CAMPAIGN must be a campaign folder name")
    manifest = None
    source = None
    for root in _roots:
        candidate = root / campaign_id / "campaign.json"
        if candidate.is_file():
            with candidate.open(encoding="utf-8") as stream:
                manifest = json.load(stream)
            source = candidate
    if manifest is None:
        raise FileNotFoundError(
            f"Campaign '{campaign_id}' has no campaign.json in configured mod folders")
    if not isinstance(manifest, dict):
        raise ValueError(f"{source} must contain a JSON object")
    required = ("id", "name", "starting_scenario", "safe_camp_arena",
                "scenarios", "map_connections", "party_limit",
                "enabled_systems", "rules")
    missing = [key for key in required if key not in manifest]
    if missing:
        raise ValueError(f"{source} is missing required fields: {', '.join(missing)}")
    if manifest["id"] != campaign_id:
        raise ValueError(f"{source}.id must match campaign folder '{campaign_id}'")
    if not isinstance(manifest["scenarios"], list) or not manifest["scenarios"]:
        raise ValueError(f"{source}.scenarios must be a non-empty list")
    if (any(not isinstance(value, str) or not value
            for value in manifest["scenarios"])
            or len(set(manifest["scenarios"])) != len(manifest["scenarios"])):
        raise ValueError(f"{source}.scenarios must contain unique non-empty IDs")
    if not isinstance(manifest["map_connections"], list):
        raise ValueError(f"{source}.map_connections must be a list")
    connection_fields = ("from", "exit", "to", "destination_exit")
    for index, connection in enumerate(manifest["map_connections"]):
        if (not isinstance(connection, dict)
                or any(not isinstance(connection.get(key), str)
                       or not connection.get(key)
                       for key in connection_fields)):
            raise ValueError(
                f"{source}.map_connections[{index}] needs non-empty string fields: "
                + ", ".join(connection_fields))
    if not isinstance(manifest["enabled_systems"], dict):
        raise ValueError(f"{source}.enabled_systems must be an object")
    if not isinstance(manifest["rules"], dict):
        raise ValueError(f"{source}.rules must be an object")
    try:
        manifest["party_limit"] = int(manifest["party_limit"])
    except (TypeError, ValueError):
        raise ValueError(f"{source}.party_limit must be a positive integer") from None
    if manifest["party_limit"] < 1:
        raise ValueError(f"{source}.party_limit must be a positive integer")
    manifest["_source"] = str(source)
    return manifest


ACTIVE_CAMPAIGN = _load_active_campaign()
CAMPAIGN_RULES = ACTIVE_CAMPAIGN["rules"]


def campaign_rule(name, default):
    """Return a validated scalar campaign rule with an engine fallback."""
    value = CAMPAIGN_RULES.get(name, default)
    try:
        if isinstance(default, bool):
            return value if isinstance(value, bool) else default
        return float(value) if isinstance(default, float) else int(value)
    except (TypeError, ValueError):
        return default


def campaign_setting(name, default=None):
    """Read list/object ruleset hooks without coercing JSON values."""
    value = CAMPAIGN_RULES.get(name, default)
    if isinstance(default, (list, dict)) and not isinstance(value, type(default)):
        return default
    return value


def system_enabled(name):
    """Return whether a campaign enables a named gameplay system."""
    return bool(ACTIVE_CAMPAIGN["enabled_systems"].get(name, False))
