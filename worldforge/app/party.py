"""Helpers for resolving live party members and updating their positions."""
from copy import deepcopy

from worldforge.app.rendering import _player_id


def party_members(actor, local_player_id, remote_players, combat):
    """Return connected party members with their latest live positions."""
    players = []
    seen = set()
    fixed_members = (set(combat.get("rest_session", {}).get("participants", []))
                     if combat and combat.get("rest_session") else None)
    if combat:
        for player_id, entry in combat.get("actors", {}).items():
            if (entry.get("team") != "players" or player_id in seen
                    or (fixed_members is not None and player_id not in fixed_members)):
                continue
            if player_id == local_player_id:
                target = actor
                data = deepcopy(entry["data"])
                data["x"], data["y"] = actor.x, actor.y
            else:
                remote = next((item for item in remote_players
                               if _player_id(item) == player_id and item.get("actor")), None)
                if not remote:
                    continue
                target = remote["actor"]
                data = deepcopy(entry["data"])
                data["x"] = remote.get("x", data.get("x", 0))
                data["y"] = remote.get("y", data.get("y", 0))
            players.append((player_id, target, data))
            seen.add(player_id)
    if not players:
        players.append((local_player_id, actor, deepcopy(vars(actor))))
        seen.add(local_player_id)
    for remote in remote_players:
        player_id = _player_id(remote)
        if (player_id in seen or not remote.get("actor")
                or (fixed_members is not None and player_id not in fixed_members)):
            continue
        data = deepcopy(remote["actor"])
        data["x"] = remote.get("x", data.get("x", 0))
        data["y"] = remote.get("y", data.get("y", 0))
        players.append((player_id, remote["actor"], data))
    return players


def set_remote_position(remote, x, y):
    """Update host-side remote player snapshots, whether dict or Actor-backed."""
    remote["x"], remote["y"] = x, y
    remote_actor = remote.get("actor")
    if isinstance(remote_actor, dict):
        remote_actor["x"], remote_actor["y"] = x, y
    elif remote_actor is not None:
        remote_actor.x, remote_actor.y = x, y
