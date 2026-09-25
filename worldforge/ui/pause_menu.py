"""Fixed-size pause menu and access to the key remapper."""
import pygame


class PauseMenuUI:
    OPTIONS = (("resume", "Resume"), ("save", "Save character"),
               ("menu", "Quit to menu"), ("remap", "Key remapper"),
               ("quit", "Quit game"))

    def __init__(self):
        self.visible = False
        self.rect = pygame.Rect(0, 0, 420, 400)
        self.buttons = []

    def handle_event(self, event):
        if not self.visible:
            return None
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return "resume"
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None
        for rect, action in self.buttons:
            if rect.collidepoint(event.pos):
                return action
        return None

    def draw(self, screen, font):
        if not self.visible:
            return
        self.rect.center = screen.get_rect().center
        veil = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 190))
        screen.blit(veil, (0, 0))
        pygame.draw.rect(screen, (26, 31, 40), self.rect, border_radius=8)
        pygame.draw.rect(screen, (216, 192, 131), self.rect, 2, border_radius=8)
        title = font.render("PAUSED", True, (255, 230, 170))
        screen.blit(title, title.get_rect(center=(self.rect.centerx,
                                                  self.rect.y + 40)))
        self.buttons = []
        for index, (action, label) in enumerate(self.OPTIONS):
            rect = pygame.Rect(self.rect.x + 48, self.rect.y + 74 + index * 54,
                               self.rect.width - 96, 42)
            self.buttons.append((rect, action))
            pygame.draw.rect(screen, (67, 77, 93), rect, border_radius=5)
            text = font.render(label, True, (245, 245, 245))
            screen.blit(text, text.get_rect(center=rect.center))


def open_overlay(stack, page, *, replace=False):
    """Push a page over the current screen or start a fresh UI flow."""
    if replace:
        stack[:] = [page]
    elif not stack or stack[-1] != page:
        stack.append(page)


def pop_overlay(stack):
    if stack:
        stack.pop()
