"""Application entry point and session coordinator."""
import atexit

from worldforge.content.classes import SCENARIOS
from worldforge.ui.creation_screen import BACK_TO_MODE, run_creation
from worldforge.app.game import DEFAULT_SCENARIO, run_game
from worldforge.ui.menu import connect_session, select_mode
from worldforge.network.networking import MAX_PLAYERS, client_callbacks
from worldforge.core.storage import unlock_actor


def _spawn_position(mode, session):
    # player_spawns in scenarios.json is the co-op spawn ring: 8 points for
    # the 8-player party cap (host + 7 joiners). Host always takes spawns[0];
    # a joiner's "playerN" id (N starts at 1, see networking.py) maps
    # straight to spawns[N]. Falls back to the old grid math if a scenario
    # doesn't define spawns, so nothing breaks on empty/short spawn lists.
    spawns = SCENARIOS.get(DEFAULT_SCENARIO, {}).get("player_spawns") or []
    if mode == "host":
        if spawns:
            return tuple(spawns[0])
        return 70, 120
    if mode == "join":
        player_number = int(session["player_id"].removeprefix("player"))
        if spawns:
            return tuple(spawns[player_number % len(spawns)])
        player_index = player_number % MAX_PLAYERS
        return 70 + (player_index % 4) * 180, 120 + (player_index // 4) * 230
    return 200, 300


def _close_session(session, mode):
    if not session:
        return
    if mode == "host":
        session.close()
    else:
        session["socket"].close()


def main():
    notice = ""
    while True:
        choice = select_mode(notice)
        notice = ""
        if choice is None:
            break
        mode, address = choice
        session = None

        if mode in ("host", "join"):
            session, error = connect_session(mode, address)
            if error:
                if error == "cancelled":
                    break
                notice = error
                continue

        actor = run_creation()
        if actor == BACK_TO_MODE:
            _close_session(session, mode)
            continue
        if actor is None:
            _close_session(session, mode)
            break
        atexit.register(unlock_actor, actor.id)
        actor.x, actor.y = _spawn_position(mode, session)

        if mode == "host":
            get_other_players, send_state = session.callbacks()
            poll_actions, publish_combat, get_combat = session.combat_callbacks()
            combat_transport = {
                "host": True, "player_id": "host", "poll": poll_actions,
                "publish": publish_combat, "get": get_combat,
            }
            party_status = session.player_count
            invite_address = session.invite_address(address)
        elif mode == "join":
            get_other_players, send_state, submit_action, get_combat = client_callbacks(session)
            combat_transport = {
                "host": False, "player_id": session["player_id"],
                "submit": submit_action, "get": get_combat,
            }
            party_status = lambda: min(MAX_PLAYERS, 1 + len(get_other_players()))
            invite_address = None
        else:
            get_other_players, send_state = lambda: [], lambda *args: None
            combat_transport = {
                "host": True, "player_id": "host", "poll": lambda: [],
                "publish": lambda state: None, "get": lambda: None,
            }
            party_status = None
            invite_address = None

        game_result = run_game(
            actor, get_other_players, send_state, multiplayer=mode != "single",
            combat_transport=combat_transport, party_status=party_status,
            invite_address=invite_address)
        # atexit.register(unlock_actor, ...) above is only a safety net for
        # a crash or a window-close quit -- it doesn't fire on "return to
        # menu", since the process keeps running through the `while True`
        # loop. Without this explicit call, this actor's .lock file is
        # never removed, so list_actors() in creation_screen.py hides it
        # for the rest of this run every time a player backs out to menu
        # instead of quitting.
        unlock_actor(actor.id)
        _close_session(session, mode)
        if game_result != "menu":
            break


if __name__ == "__main__":
    main()
