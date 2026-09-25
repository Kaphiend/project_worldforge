"""Actor-owned personal chest modal."""
import pygame


class PersonalStorageUI:
    def __init__(self):
        self.visible = False
        self.chest_id = None
        self.selected_inventory = None
        self.selected_storage = None
        self.rows = {}
        self.list_rects = {}
        self.scroll = {"inventory": 0, "storage": 0}
        self.deposit_rect = pygame.Rect(0, 0, 0, 0)
        self.withdraw_rect = pygame.Rect(0, 0, 0, 0)

    def open(self, chest_id):
        self.visible = True
        self.chest_id = chest_id
        self.selected_inventory = self.selected_storage = None
        self.scroll = {"inventory": 0, "storage": 0}

    def close(self):
        self.visible = False
        self.chest_id = None

    def handle_event(self, event, actor_data):
        if not self.visible:
            return None
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_i):
            self.close()
            return None
        if event.type == pygame.MOUSEWHEEL:
            mouse = pygame.mouse.get_pos()
            for side, rect in self.list_rects.items():
                if rect.collidepoint(mouse):
                    self.scroll[side] = max(0, self.scroll.get(side, 0) - event.y)
                    break
            return None
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None
        for key, rect in self.rows.items():
            if rect.collidepoint(event.pos):
                side, item_id = key
                if side == "inventory":
                    self.selected_inventory = item_id
                else:
                    self.selected_storage = item_id
                return None
        if self.deposit_rect.collidepoint(event.pos) and self.selected_inventory:
            return {"type": "storage_deposit", "item_id": self.selected_inventory,
                    "chest_id": self.chest_id}
        if self.withdraw_rect.collidepoint(event.pos) and self.selected_storage:
            return {"type": "storage_withdraw", "item_id": self.selected_storage,
                    "chest_id": self.chest_id}
        return None

    def draw(self, screen, actor_data, title="Personal Chest"):
        if not self.visible:
            return
        veil = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 175))
        screen.blit(veil, (0, 0))
        panel = pygame.Rect(0, 0, 720, 480)
        panel.center = screen.get_rect().center
        pygame.draw.rect(screen, (31, 35, 42), panel, border_radius=8)
        pygame.draw.rect(screen, (195, 185, 150), panel, 2, border_radius=8)
        font = pygame.font.Font(None, 22)
        screen.blit(font.render(title, True, (255, 229, 165)), (panel.x + 20, panel.y + 15))
        self.rows = {}
        self.list_rects = {}
        for side, label, items, x in (
                ("inventory", "Inventory", actor_data.get("inventory", []), panel.x + 20),
                ("storage", "Chest", actor_data.get("personal_storage", []), panel.x + 370)):
            screen.blit(font.render(label, True, (225, 225, 215)), (x, panel.y + 50))
            self.list_rects[side] = pygame.Rect(x, panel.y + 82, 320, 300)
            self.scroll[side] = min(self.scroll.get(side, 0), max(0, len(items) - 10))
            start = self.scroll[side]
            for index, item in enumerate(items[start:start + 10]):
                row = pygame.Rect(x, panel.y + 82 + index * 30, 320, 26)
                key = (side, item.get("id"))
                selected = (self.selected_inventory if side == "inventory"
                            else self.selected_storage) == item.get("id")
                pygame.draw.rect(screen, (78, 84, 94) if selected else (49, 54, 63), row)
                screen.blit(pygame.font.Font(None, 18).render(
                    f"{item.get('name', item.get('id', 'Item'))} x{item.get('quantity', 1)}",
                    True, (235, 235, 225)), (row.x + 7, row.y + 5))
                self.rows[key] = row
        self.deposit_rect = pygame.Rect(panel.x + 230, panel.bottom - 54, 110, 34)
        self.withdraw_rect = pygame.Rect(panel.x + 380, panel.bottom - 54, 110, 34)
        for rect, label in ((self.deposit_rect, "Deposit"), (self.withdraw_rect, "Withdraw")):
            pygame.draw.rect(screen, (83, 105, 86), rect, border_radius=5)
            screen.blit(pygame.font.Font(None, 19).render(label, True, (255, 255, 245)),
                        (rect.x + 18, rect.y + 8))
        screen.blit(pygame.font.Font(None, 17).render("Esc: close · scroll either list", True, (205, 210, 215)),
                    (panel.x + 20, panel.bottom - 45))
