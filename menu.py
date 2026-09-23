"""Startup menu and connection screens."""
import json
import socket
import threading

import pygame

from networking import HostSession, PORT


def select_mode(notice=""):
    """Return a selected mode and optional invitation address."""
    pygame.init()
    screen = pygame.display.set_mode((800, 600))
    pygame.display.set_caption("Worldforge")
    font = pygame.font.SysFont(None, 38)
    small = pygame.font.SysFont(None, 26)
    clock = pygame.time.Clock()
    stage, error = "mode", notice
    buttons = {
        "single": pygame.Rect(250, 180, 300, 58),
        "coop": pygame.Rect(250, 260, 300, 58),
        "host": pygame.Rect(250, 180, 300, 58),
        "join": pygame.Rect(250, 260, 300, 58),
        "connect": pygame.Rect(230, 390, 340, 54),
        "address": pygame.Rect(170, 285, 460, 55),
        "host_address": pygame.Rect(170, 285, 460, 55),
        "back": pygame.Rect(20, 20, 110, 44),
    }
    address_text = ""
    host_address_text = ""

    def draw_button(rect, label):
        pygame.draw.rect(screen, (58, 75, 105), rect, border_radius=8)
        image = font.render(label, True, (245, 245, 245))
        screen.blit(image, image.get_rect(center=rect.center))

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                return None
            if event.type == pygame.MOUSEBUTTONDOWN:
                if stage == "mode":
                    if buttons["single"].collidepoint(event.pos):
                        return "single", None
                    if buttons["coop"].collidepoint(event.pos):
                        stage = "coop"
                elif buttons["back"].collidepoint(event.pos):
                    stage, error = ("coop", "") if stage in ("address", "host_address") else ("mode", "")
                elif stage == "coop":
                    if buttons["host"].collidepoint(event.pos):
                        stage = "host_address"
                    if buttons["join"].collidepoint(event.pos):
                        stage = "address"
                        error = ""
                elif stage == "address" and buttons["connect"].collidepoint(event.pos):
                    if address_text.strip():
                        return "join", address_text.strip()
                    error = "Enter the host's invite address."
                elif stage == "host_address" and buttons["connect"].collidepoint(event.pos):
                    endpoint = host_address_text.strip()
                    if endpoint and not _valid_host_invite(endpoint):
                        error = f"Use a hostname/IP and port {PORT}."
                    else:
                        return "host", endpoint or None

            if stage == "address" and event.type == pygame.KEYDOWN:
                if event.key == pygame.K_BACKSPACE:
                    address_text = address_text[:-1]
                elif event.key == pygame.K_RETURN and address_text.strip():
                    return "join", address_text.strip()
                elif event.unicode.isprintable() and len(address_text) < 100:
                    address_text += event.unicode
            elif stage == "host_address" and event.type == pygame.KEYDOWN:
                if event.key == pygame.K_BACKSPACE:
                    host_address_text = host_address_text[:-1]
                elif event.key == pygame.K_RETURN:
                    endpoint = host_address_text.strip()
                    if endpoint and not _valid_host_invite(endpoint):
                        error = f"Use a hostname/IP and port {PORT}."
                    else:
                        return "host", endpoint or None
                elif event.unicode.isprintable() and len(host_address_text) < 100:
                    host_address_text += event.unicode

        screen.fill((22, 25, 33))
        title = font.render("Worldforge", True, (245, 245, 245))
        screen.blit(title, title.get_rect(center=(400, 100)))
        if stage == "mode":
            draw_button(buttons["single"], "Single Player")
            draw_button(buttons["coop"], "Co-op")
            if error:
                message = small.render(error, True, (255, 130, 130))
                screen.blit(message, message.get_rect(center=(400, 400)))
        elif stage == "coop":
            screen.blit(small.render("Choose how to start co-op", True, (210, 215, 225)), (280, 120))
            screen.blit(small.render("Up to 8 players total, including the host", True,
                                     (190, 210, 190)), (260, 155))
            draw_button(buttons["host"], "Host Game")
            draw_button(buttons["join"], "Join by Invite")
            draw_button(buttons["back"], "Back")
        elif stage == "address":
            screen.blit(small.render("Enter the host's IP address or hostname", True,
                                     (210, 215, 225)), (230, 220))
            screen.blit(small.render("Up to 8 players total, including the host", True,
                                     (190, 210, 190)), (260, 250))
            pygame.draw.rect(screen, (55, 60, 72), buttons["address"], border_radius=6)
            screen.blit(small.render(address_text or "example: 203.0.113.10:5555",
                                      True, (245, 245, 245)), (buttons["address"].x + 12,
                                                              buttons["address"].y + 16))
            draw_button(buttons["connect"], "Connect")
            draw_button(buttons["back"], "Back")
            if error:
                screen.blit(small.render(error, True, (255, 130, 130)), (230, 460))
        else:
            screen.blit(small.render("Public IP or hostname to share (optional)", True,
                                     (210, 215, 225)), (230, 220))
            pygame.draw.rect(screen, (55, 60, 72), buttons["host_address"], border_radius=6)
            screen.blit(small.render(host_address_text or "public-ip-or-hostname:5555",
                                      True, (245, 245, 245)),
                        (buttons["host_address"].x + 12, buttons["host_address"].y + 16))
            screen.blit(small.render("Forward TCP port 5555 on your router for Internet play.",
                                     True, (220, 195, 160)), (205, 355))
            if error:
                screen.blit(small.render(error, True, (255, 130, 130)), (230, 460))
            draw_button(buttons["connect"], "Create Co-op Game")
            draw_button(buttons["back"], "Back")
        pygame.display.flip()
        clock.tick(60)


def connect_session(mode, address=None):
    """Host a session or display a responsive screen while joining one."""
    if mode == "host":
        try:
            return HostSession(), None
        except OSError as exc:
            return None, str(exc)

    result = {"session": None, "error": None}
    done = threading.Event()
    cancelled = threading.Event()

    def connect():
        conn = None
        try:
            host, port = _split_invite_address(address)
            conn = socket.create_connection((host, port), timeout=10)
            buffer = ""
            while "\n" not in buffer:
                data = conn.recv(1024).decode()
                if not data:
                    raise OSError("The host closed the connection")
                buffer += data
            first_line, remainder = buffer.split("\n", 1)
            greeting = json.loads(first_line)
            if "error" in greeting:
                raise OSError(greeting["error"])
            if cancelled.is_set():
                conn.close()
                return
            conn.settimeout(None)
            result["session"] = {
                "socket": conn,
                "player_id": greeting["assigned_id"],
                "buffer": remainder,
            }
        except (OSError, ValueError, KeyError) as exc:
            if conn:
                conn.close()
            result["error"] = str(exc)
        finally:
            done.set()

    threading.Thread(target=connect, daemon=True).start()
    screen = pygame.display.get_surface()
    font = pygame.font.SysFont(None, 32)
    clock = pygame.time.Clock()
    while not done.is_set():
        for event in pygame.event.get():
            if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                cancelled.set()
                return None, "cancelled"
        screen.fill((22, 25, 33))
        image = font.render(f"Connecting to {address}...", True, (245, 245, 245))
        screen.blit(image, image.get_rect(center=(400, 280)))
        pygame.display.flip()
        clock.tick(30)

    if result["error"]:
        return None, result["error"]
    return result["session"], None


def _split_invite_address(address):
    """Accept a hostname/IP, host:port, or bracketed IPv6 invite endpoint."""
    address = address.strip()
    if address.startswith('[') and ']:' in address:
        host, port_text = address[1:].split(']:', 1)
        if port_text.isdigit():
            port = int(port_text)
            if 1 <= port <= 65535:
                return host, port
    elif address.count(':') == 1:
        host, port_text = address.rsplit(':', 1)
        if port_text.isdigit():
            port = int(port_text)
            if 1 <= port <= 65535:
                return host, port
    return address, PORT


def _valid_host_invite(address):
    if address.startswith('['):
        if ']:' not in address:
            return False
        host, port_text = address[1:].split(']:', 1)
    elif ':' in address:
        if address.count(':') != 1:
            return False
        host, port_text = address.rsplit(':', 1)
    else:
        return bool(address)
    return bool(host) and port_text.isdigit() and int(port_text) == PORT
