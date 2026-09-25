"""Party membership, connection lifecycle, and position helpers."""
from copy import deepcopy

from worldforge.app.combat_flow import _active_actor_id, _debug_log, _log
from worldforge.app.encounters import _combat_snapshot
from worldforge.app.rendering import _player_id
from worldforge.app.world import _movement_allowance
from worldforge.combat.rules import initiative_for


def add_joined_players(combat, remote_players):
    """Add players who accept an invite after combat has already begun."""
    additions = []
    for remote in remote_players:
        actor_data = remote.get('actor')
        actor_id = _player_id(remote)
        if not actor_data or actor_id in combat['actors']:
            continue
        entry = _combat_snapshot(actor_id, actor_data, 'players')
        combat['actors'][actor_id] = entry
        combat['budgets'][actor_id] = {
            'movement': _movement_allowance(entry['data']), 'action': True,
            'bonus_action': True, 'reaction': True, 'skip_next': False,
            'condition_tick_done': False, 'movement_used': 0,
        }
        additions.append(actor_id)
    if not additions:
        return

    active_id = _active_actor_id(combat)
    eligible = {actor_id: entry for actor_id, entry in combat['actors'].items()
                if not entry['downed']}
    rolls = {entry['id']: {key: entry[key] for key in ('total', 'natural', 'dexterity')}
             for entry in combat['order']}
    for actor_id in additions:
        if actor_id in eligible:
            rolls[actor_id] = initiative_for(eligible[actor_id]['data'])
            roll = rolls[actor_id]
            name = eligible[actor_id]['data'].get('name', actor_id)
            _debug_log(combat, (f"Initiative: {name}: d20 [{roll['natural']}] -> "
                                f"{roll['natural']} + Dexterity "
                                f"{roll['dexterity']:+} = {roll['total']}."))
    combat['order'] = [
        {'id': actor_id, **roll}
        for actor_id, roll in sorted(
            rolls.items(), key=lambda pair: (pair[1]['total'], pair[1]['dexterity'], pair[0]),
            reverse=True)
    ]
    if active_id in [entry['id'] for entry in combat['order']]:
        combat['turn_index'] = next(
            index for index, entry in enumerate(combat['order'])
            if entry['id'] == active_id)
    for actor_id in additions:
        _log(combat, f"{combat['actors'][actor_id]['data'].get('name', actor_id)} joins the party.")


def remove_disconnected_players(combat, remote_players, host_id):
    """Remove departed clients from the active party and turn order."""
    connected = {_player_id(remote) for remote in remote_players}
    active_id = _active_actor_id(combat)
    old_index = combat.get('turn_index', 0)
    removed = [actor_id for actor_id, entry in combat['actors'].items()
               if entry['team'] == 'players' and actor_id != host_id
               and actor_id not in connected]
    for actor_id in removed:
        name = combat['actors'][actor_id]['data'].get('name', actor_id)
        combat['actors'].pop(actor_id, None)
        combat['budgets'].pop(actor_id, None)
        combat.setdefault('removed_order', {}).pop(actor_id, None)
        combat['order'] = [entry for entry in combat['order']
                           if entry['id'] != actor_id]
        _log(combat, f"{name} disconnected and left the party.")
    if not any(entry['team'] == 'players' for entry in combat['actors'].values()):
        combat['active'] = False
        return
    remaining_ids = [entry['id'] for entry in combat['order']]
    if active_id in remaining_ids:
        combat['turn_index'] = remaining_ids.index(active_id)
    elif remaining_ids:
        combat['turn_index'] = min(old_index, len(remaining_ids) - 1)
    else:
        combat['active'] = False


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
