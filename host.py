import socket
import threading
import atexit
from main import run_game
from creation_screen import run_creation
from factory import unlock_actor

HOST = '127.0.0.1'
PORT = 5555

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((HOST, PORT))
server.listen(1)
print("waiting for client...")
conn, addr = server.accept()
print(f"connected: {addr}")

other_x, other_y = 400, 300  # blue player's state, updated by network
other_anim = 'idle'
other_facing = False


def listen():
    global other_x, other_y, other_anim, other_facing
    buffer = ""
    while True:
        data = conn.recv(1024)
        if not data:
            break
        buffer += data.decode()
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            x_str, y_str, anim, facing_str = line.split(",")
            other_x, other_y = int(x_str), int(y_str)
            other_anim = anim
            other_facing = facing_str == "1"


threading.Thread(target=listen, daemon=True).start()


def get_other_state():
    return other_x, other_y, other_anim, other_facing


def send_state(x, y, anim, facing):
    try:
        conn.sendall(f"{x},{y},{anim},{1 if facing else 0}\n".encode())
    except (BrokenPipeError, OSError):
        pass


actor = run_creation()
if actor is None:
    exit()
atexit.register(unlock_actor, actor.id)
actor.x, actor.y = 200, 300

run_game(actor, get_other_state, send_state, self_color=(200, 50, 50), other_color=(50, 50, 200))