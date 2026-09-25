"""Persistent keyboard bindings and a fixed-size remapping panel."""
import json

import pygame

from worldforge.core.runtime_paths import user_data_path


DEFAULT_BINDINGS = {
    "move_up": pygame.K_w,
    "move_down": pygame.K_s,
    "move_left": pygame.K_a,
    "move_right": pygame.K_d,
    "inventory": pygame.K_i,
    "spellbook": pygame.K_MINUS,
    "interact": pygame.K_f,
    "camp": pygame.K_z,
    "return_menu": pygame.K_m,
    "save": pygame.K_F5,
    "ranged": pygame.K_r,
    "throw": pygame.K_t,
    "fast_hands": pygame.K_g,
    "quick_item_q": pygame.K_q,
    "quick_item_e": pygame.K_e,
    "end_turn": pygame.K_TAB,
    "controls": pygame.K_F1,
    "tooltips": pygame.K_F2,
    "fullscreen": pygame.K_F11,
    "chat": pygame.K_RETURN,
    "sneak": pygame.K_k,
    "cycle_bar": pygame.K_BACKQUOTE,
    "invite": pygame.K_c,
    "retry": pygame.K_n,
}

LABELS = {
    "move_up": "Move up", "move_down": "Move down",
    "move_left": "Move left", "move_right": "Move right",
    "inventory": "Inventory", "spellbook": "Spellbook",
    "interact": "Interact", "camp": "Outdoor rest",
    "return_menu": "Return to menu", "save": "Save character",
    "ranged": "Ranged / release spirit", "throw": "Throw weapon",
    "fast_hands": "Fast Hands", "quick_item_q": "Quick item Q",
    "quick_item_e": "Quick item E", "end_turn": "End turn",
    "controls": "Controls panel", "tooltips": "Toggle tooltips",
    "fullscreen": "Toggle fullscreen", "chat": "Chat",
    "sneak": "Toggle sneak", "cycle_bar": "Cycle hotbar",
    "invite": "Copy host invite", "retry": "Retry encounter",
}


class KeyBindings:
    def __init__(self):
        self.path = user_data_path("settings") / "keybindings.json"
        self.values = dict(DEFAULT_BINDINGS)
        self._load()
        self.rows = []
        self.panel = pygame.Rect(0, 0, 760, 620)
        self.reset_rect = pygame.Rect(0, 0, 0, 0)
        self.capture_action = None
        self.scroll = 0
        self.notice = "Click a binding, then press a key. Escape cancels."

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        for action, name in data.items():
            if action not in DEFAULT_BINDINGS or not isinstance(name, str):
                continue
            try:
                key = pygame.key.key_code(name)
            except (ValueError, pygame.error):
                continue
            if key != pygame.K_ESCAPE and key not in self.values.values():
                self.values[action] = key

    def key(self, action):
        return self.values.get(action, DEFAULT_BINDINGS[action])

    def matches(self, event, action):
        return event.type == pygame.KEYDOWN and event.key == self.key(action)

    def save(self):
        payload = {action: pygame.key.name(key)
                   for action, key in self.values.items()}
        self.path.write_text(json.dumps(payload, indent=2) + "\n",
                             encoding="utf-8")

    def reset(self):
        self.values = dict(DEFAULT_BINDINGS)
        self.save()
        self.capture_action = None
        self.notice = "Default bindings restored."

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and self.capture_action:
            action = self.capture_action
            if event.key == pygame.K_ESCAPE:
                self.capture_action = None
                self.notice = "Binding cancelled."
                return "cancel_capture"
            reserved = {pygame.K_ESCAPE, pygame.K_y,
                        pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT,
                        pygame.K_RIGHT, *range(pygame.K_0, pygame.K_9 + 1)}
            if event.key in reserved:
                self.notice = "That key is reserved for menus, movement, or hotbars."
                return None
            conflict = next((name for name, key in self.values.items()
                             if key == event.key and name != action), None)
            if conflict:
                self.notice = f"Already used by {LABELS[conflict]}."
                return None
            self.values[action] = event.key
            self.capture_action = None
            self.save()
            self.notice = f"{LABELS[action]} set to {pygame.key.name(event.key)}."
            return None
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return "close"
        if event.type == pygame.MOUSEWHEEL:
            self.scroll = max(0, self.scroll - event.y)
            return None
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None
        for rect, action in self.rows:
            if rect.collidepoint(event.pos):
                self.capture_action = action
                self.notice = f"Press a key for {LABELS[action]}. Escape cancels."
                return None
        if self.reset_rect.collidepoint(event.pos):
            self.reset()
        return None

    def draw(self, screen, font):
        width, height = self.panel.size
        self.panel.center = screen.get_rect().center
        veil = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 190))
        screen.blit(veil, (0, 0))
        pygame.draw.rect(screen, (26, 31, 40), self.panel, border_radius=8)
        pygame.draw.rect(screen, (216, 192, 131), self.panel, 2, border_radius=8)
        screen.blit(font.render("KEY REMAPPER", True, (255, 230, 170)),
                    (self.panel.x + 22, self.panel.y + 16))
        small = pygame.font.Font(None, 19)
        self.rows = []
        row_top = self.panel.y + 62
        visible = 16
        self.scroll = min(self.scroll, max(0, len(LABELS) - visible))
        for row, action in enumerate(list(LABELS)[self.scroll:self.scroll + visible]):
            rect = pygame.Rect(self.panel.x + 22, row_top + row * 28,
                               width - 44, 25)
            self.rows.append((rect, action))
            pygame.draw.rect(screen, (46, 52, 64), rect, border_radius=3)
            label = LABELS[action]
            key_name = ("Press a key…" if action == self.capture_action else
                        pygame.key.name(self.key(action)).upper())
            screen.blit(small.render(label, True, (238, 240, 245)),
                        (rect.x + 10, rect.y + 4))
            key_image = small.render(key_name, True, (255, 220, 150))
            screen.blit(key_image, (rect.right - key_image.get_width() - 12,
                                    rect.y + 4))
        self.reset_rect = pygame.Rect(self.panel.x + 22, self.panel.bottom - 44,
                                      150, 30)
        pygame.draw.rect(screen, (67, 77, 93), self.reset_rect, border_radius=4)
        screen.blit(small.render("Restore defaults", True, (245, 245, 245)),
                    (self.reset_rect.x + 10, self.reset_rect.y + 7))
        notice = small.render(self.notice, True, (220, 225, 235))
        screen.blit(notice, (self.panel.x + 190, self.panel.bottom - 38))
