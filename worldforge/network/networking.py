"""Local co-op hosting and player state relay."""
import json
import socket
import threading
from copy import deepcopy
from worldforge.content.campaign import ACTIVE_CAMPAIGN


HOST = "0.0.0.0"
PORT = 5555
MAX_PLAYERS = ACTIVE_CAMPAIGN["party_limit"]  # Includes the host.


def local_invite_address():
    """Return the LAN interface address friends on the same network can use."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # UDP connect selects the route without sending a packet.
        probe.connect(("192.0.2.1", 80))
        return probe.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        probe.close()


def _encode_message(message):
    return (json.dumps(message) + "\n").encode()


def _player_state(x, y, anim, facing, actor_data=None, speech=None):
    return {"x": x, "y": y, "anim": anim, "facing": facing,
            "actor": actor_data, "speech": speech}


class HostSession:
    """Relay player state between the host and several joining players."""

    def __init__(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((HOST, PORT))
        self.server.listen(MAX_PLAYERS - 1)
        self.server.settimeout(0.5)
        self.lock = threading.Lock()
        self.peers = {}
        self.states = {}
        self.actions = []
        self.combat_state = None
        self.host_state = self._empty_state("host")
        self.closed = False
        threading.Thread(target=self._accept_players, daemon=True).start()
        threading.Thread(target=self._broadcast_states, daemon=True).start()

    @staticmethod
    def _empty_state(player_id):
        return {"id": player_id, "x": 400, "y": 300, "anim": "idle", "facing": False, "actor": None}

    def _accept_players(self):
        while not self.closed:
            try:
                conn, _ = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            with self.lock:
                if 1 + len(self.peers) >= MAX_PLAYERS:
                    try:
                        conn.sendall(_encode_message({"error": "Game is full"}))
                    except OSError:
                        pass
                    conn.close()
                    continue

                player_number = 1
                while f"player{player_number}" in self.peers:
                    player_number += 1
                player_id = f"player{player_number}"
                self.peers[player_id] = conn
                self.states[player_id] = self._empty_state(player_id)

            try:
                conn.sendall(_encode_message({"assigned_id": player_id}))
            except OSError:
                self._remove_player(player_id)
                continue
            threading.Thread(target=self._receive_player, args=(player_id, conn), daemon=True).start()

    def _receive_player(self, player_id, conn):
        buffer = ""
        try:
            while not self.closed:
                data = conn.recv(4096)
                if not data:
                    break
                buffer += data.decode()
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    state = json.loads(line)
                    with self.lock:
                        if player_id in self.states:
                            if state.get("type") == "combat_action":
                                self.actions.append({"player_id": player_id,
                                                     "action": state.get("action", {})})
                            else:
                                state["id"] = player_id
                                self.states[player_id] = state
        except (OSError, ValueError, TypeError):
            pass
        finally:
            self._remove_player(player_id)

    def _remove_player(self, player_id):
        with self.lock:
            conn = self.peers.pop(player_id, None)
            self.states.pop(player_id, None)
        if conn:
            try:
                conn.close()
            except OSError:
                pass

    def _broadcast_states(self):
        while not self.closed:
            with self.lock:
                players = {"host": dict(self.host_state)}
                players.update({key: dict(value) for key, value in self.states.items()})
                peers = list(self.peers.items())
                combat_state = self.combat_state
            message = _encode_message({"players": players, "combat": combat_state})
            for player_id, conn in peers:
                try:
                    conn.sendall(message)
                except OSError:
                    self._remove_player(player_id)
            threading.Event().wait(0.05)

    def callbacks(self):
        def get_other_players():
            with self.lock:
                return [dict(state) for state in self.states.values() if state.get("actor")]

        def send_state(x, y, anim, facing, actor_data=None, speech=None):
            with self.lock:
                self.host_state.update(_player_state(x, y, anim, facing,
                                                     actor_data, speech))

        return get_other_players, send_state

    def player_count(self):
        """Return occupied party seats, including the host."""
        with self.lock:
            return 1 + len(self.peers)

    def invite_address(self, public_address=None):
        """Return LAN and optional Internet endpoints for the host's invite UI."""
        lan_address = f"{local_invite_address()}:{PORT}"
        if not public_address:
            return lan_address, None
        public_address = public_address.strip()
        if public_address.startswith('[') or public_address.count(':') == 1:
            internet_address = public_address
        else:
            internet_address = f"{public_address}:{PORT}"
        return lan_address, internet_address

    def combat_callbacks(self):
        def poll_actions():
            with self.lock:
                pending, self.actions = self.actions, []
            return pending

        def publish_combat(combat_state):
            public_state = deepcopy(combat_state)
            if public_state:
                # Area caches are host-owned and may contain full enemy
                # records for maps the party has not entered yet.
                public_state.pop("world_areas", None)
                enemy_ids = set()
                for entry in public_state.get("actors", {}).values():
                    if entry.get("team") == "enemies":
                        enemy_ids.add(entry["id"])
                public_state["order"] = [
                    ({"id": entry["id"]} if entry.get("id") in enemy_ids else entry)
                    for entry in public_state.get("order", [])
                ]
                for enemy_id in enemy_ids:
                    public_state.get("budgets", {}).pop(enemy_id, None)
            with self.lock:
                self.combat_state = public_state

        def get_combat():
            with self.lock:
                return deepcopy(self.combat_state)

        return poll_actions, publish_combat, get_combat

    def close(self):
        self.closed = True
        try:
            self.server.close()
        except OSError:
            pass
        with self.lock:
            peers = list(self.peers.values())
            self.peers.clear()
            self.states.clear()
        for conn in peers:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            conn.close()


def client_callbacks(session):
    conn = session["socket"]
    remote = {"players": {}, "combat": None, "player_id": session["player_id"]}
    remote_lock = threading.Lock()

    def listen():
        buffer = session.get("buffer", "")
        try:
            while True:
                data = conn.recv(4096)
                if not data:
                    break
                buffer += data.decode()
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    message = json.loads(line)
                    if "players" in message:
                        with remote_lock:
                            remote["players"] = message["players"]
                            remote["combat"] = message.get("combat")
        except (OSError, ValueError, TypeError):
            pass
        finally:
            with remote_lock:
                remote["players"] = {}

    threading.Thread(target=listen, daemon=True).start()

    def get_other_players():
        own_id = remote["player_id"]
        with remote_lock:
            players = dict(remote["players"])
        return [dict(state) for player_id, state in players.items()
                if player_id != own_id and state.get("actor")]

    def send_state(x, y, anim, facing, actor_data=None, speech=None):
        try:
            conn.sendall(_encode_message(_player_state(x, y, anim, facing,
                                                       actor_data, speech)))
        except OSError:
            pass

    def submit_action(action):
        try:
            conn.sendall(_encode_message({"type": "combat_action", "action": action}))
        except OSError:
            pass

    def get_combat():
        with remote_lock:
            return remote["combat"]

    return get_other_players, send_state, submit_action, get_combat
