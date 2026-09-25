"""Shared corpse-loot panel for the demo combat loop."""
import pygame


class LootUI:
    def __init__(self):
        self.visible = False
        self.corpse_id = None
        self.scroll = 0
        self.panel_rect = pygame.Rect(0, 0, 0, 0)
        self.item_rects = {}
        self.take_all_rect = pygame.Rect(0, 0, 0, 0)
        self.done_rect = pygame.Rect(0, 0, 0, 0)

    def open(self, corpse_id):
        self.visible = True
        self.corpse_id = corpse_id
        self.scroll = 0

    @staticmethod
    def _fit_text(text, font, max_width):
        value = str(text)
        if font.size(value)[0] <= max_width:
            return value
        while value and font.size(value + "…")[0] > max_width:
            value = value[:-1]
        return value + "…"

    def close(self):
        self.visible = False
        self.corpse_id = None

    def handle_event(self, event, loot):
        if not self.visible:
            return None
        if (event.type == pygame.KEYDOWN and event.key in (
                pygame.K_w, pygame.K_a, pygame.K_s, pygame.K_d,
                pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT, pygame.K_RIGHT)):
            # Treat an attempted move as an explicit close so the modal loot
            # panel never makes the character feel stuck.
            return {"type": "loot_finish", "target": self.corpse_id}
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE,
                                                           pygame.K_n):
            return {"type": "loot_finish", "target": self.corpse_id}
        if event.type == pygame.MOUSEWHEEL:
            self.scroll = max(0, self.scroll - event.y)
            return None
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None
        if self.take_all_rect.collidepoint(event.pos):
            return {"type": "loot_take_all", "target": self.corpse_id}
        if self.done_rect.collidepoint(event.pos):
            return {"type": "loot_finish", "target": self.corpse_id}
        for item_id, rect in self.item_rects.items():
            if rect.collidepoint(event.pos):
                return {"type": "loot_take", "target": self.corpse_id,
                        "item_id": item_id}
        return None

    def draw(self, screen, corpse, font):
        if not self.visible or not corpse:
            return
        veil = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 175))
        screen.blit(veil, (0, 0))
        width, height = min(520, screen.get_width() - 32), min(440, screen.get_height() - 32)
        self.panel_rect = pygame.Rect(0, 0, width, height)
        self.panel_rect.center = (screen.get_width() // 2, screen.get_height() // 2)
        pygame.draw.rect(screen, (31, 35, 42), self.panel_rect, border_radius=8)
        pygame.draw.rect(screen, (195, 185, 150), self.panel_rect, 2,
                         border_radius=8)
        small_font = pygame.font.Font(None, 18)
        item_font = pygame.font.Font(None, 19)
        title = corpse.get("data", {}).get("name", "Loot")
        screen.blit(font.render(f"Loot: {title}  |  Shared loot", True,
                                (255, 229, 165)),
                    (self.panel_rect.x + 18, self.panel_rect.y + 14))
        screen.blit(small_font.render(
            "Take items for yourself; everyone shares this container.", True,
            (205, 215, 228)), (self.panel_rect.x + 18, self.panel_rect.y + 42))
        items = corpse.get("loot", []) or []
        visible_count = max(1, min(9, (height - 142) // 32))
        self.scroll = min(self.scroll, max(0, len(items) - visible_count))
        self.item_rects = {}
        for index, item in enumerate(items[self.scroll:self.scroll + visible_count]):
            y = self.panel_rect.y + 76 + index * 32
            row = pygame.Rect(self.panel_rect.x + 18, y, width - 36, 28)
            self.item_rects[item.get("id")] = row
            pygame.draw.rect(screen, (54, 60, 70), row, border_radius=3)
            item_name = item.get("name", item.get("template_id", "Item"))
            quantity = int(item.get("quantity", 1) or 1)
            label = item_name + (f" x{quantity}" if quantity > 1 else "")
            slot = item.get("slot")
            if slot:
                label += f"  ·  {slot.replace('_', ' ')}"
            rarity_colors = {
                "common": (222, 226, 232), "uncommon": (125, 220, 142),
                "rare": (105, 174, 255), "epic": (202, 137, 255),
                "legendary": (255, 190, 80),
            }
            color = rarity_colors.get(str(item.get("rarity", "common")).lower(),
                                     (242, 244, 248))
            screen.blit(item_font.render(
                self._fit_text(label, item_font, row.width - 18), True, color),
                        (row.x + 9, row.y + 6))
        if not items:
            screen.blit(item_font.render("The corpse has been looted.", True,
                                         (210, 220, 232)),
                        (self.panel_rect.x + 18, self.panel_rect.y + 88))

        button_y = self.panel_rect.bottom - 52
        self.take_all_rect = pygame.Rect(self.panel_rect.x + 18, button_y,
                                         140, 34)
        self.done_rect = pygame.Rect(self.panel_rect.right - 138, button_y,
                                     120, 34)
        for rect, label, color in (
                (self.take_all_rect, "Take All", (78, 112, 82)),
                (self.done_rect, "Done", (76, 84, 98))):
            pygame.draw.rect(screen, color, rect, border_radius=4)
            pygame.draw.rect(screen, (180, 190, 205), rect, 1, border_radius=4)
            text = font.render(label, True, (250, 250, 245))
            screen.blit(text, text.get_rect(center=rect.center))
        screen.blit(small_font.render("Esc closes; corpse despawns 3 seconds after looting ends.",
                                      True, (190, 198, 210)),
                    (self.panel_rect.x + 18, button_y - 19))
