"""Application entry point and session coordinator."""
import atexit

from creation_screen import run_creation
from game import run_game
from menu import connect_session, select_mode
from networking import MAX_PLAYERS, client_callbacks
from storage import unlock_actor


def _spawn_position(mode, session):
    if mode == "host":
        return 70, 120
    if mode == "join":
        player_number = int(session["player_id"].removeprefix("player"))
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
            party_status = lambda: min(8, 1 + len(get_other_players()))
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
        _close_session(session, mode)
        if game_result != "menu":
            break


if __name__ == "__main__":
    main()
