"""Gray-box inventory and equipment modal for the local actor."""
import pygame

from factory import equipment_slots, item_definition


class InventoryScreen:
    def __init__(self):
        self.visible = False
        self.selected_id = None
        self.scroll = 0
        self.rect = pygame.Rect(70, 54, 660, 492)
        self._slot_rects = {}
        self._item_rects = {}
        self._use_rect = pygame.Rect(500, 492, 120, 34)

    def toggle(self):
        self.visible = not self.visible
        self.selected_id = None

    def handle_event(self, event, actor_data):
        if not self.visible:
            return None
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_ESCAPE, pygame.K_i):
            self.visible = False
            return None
        if event.type == pygame.MOUSEWHEEL:
            self.scroll = max(0, self.scroll - event.y)
            return None
        if event.type != pygame.MOUSEBUTTONDOWN or event.button != 1:
            return None
        if not self.rect.collidepoint(event.pos):
            return None
        for slot, rect in self._slot_rects.items():
            if rect.collidepoint(event.pos):
                equipped = actor_data.get("equipment", {}).get(slot)
                if equipped:
                    return {"type": "unequip_item", "slot": slot}
                if self.selected_id:
                    return {"type": "equip_item", "item": self.selected_id, "slot": slot}
        for item_id, rect in self._item_rects.items():
            if rect.collidepoint(event.pos):
                self.selected_id = item_id
                return None
        if self._use_rect.collidepoint(event.pos) and self.selected_id:
            item = next((item for item in actor_data.get("inventory", [])
                         if item.get("id") == self.selected_id), None)
            if item and item_definition(item).get("consumable"):
                return {"type": "use_item", "item": self.selected_id}
        return None

    def draw(self, screen, actor_data, font):
        if not self.visible:
            return
        veil = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 175))
        screen.blit(veil, (0, 0))
        pygame.draw.rect(screen, (36, 39, 45), self.rect, border_radius=8)
        pygame.draw.rect(screen, (175, 180, 190), self.rect, 2, border_radius=8)
        screen.blit(font.render("Inventory and Equipment  |  I or Esc to close", True,
                                (245, 235, 195)), (self.rect.x + 16, self.rect.y + 12))
        screen.blit(font.render("Equipment", True, (220, 230, 245)), (92, 98))
        equipment = actor_data.get("equipment", {})
        self._slot_rects = {}
        for index, slot in enumerate(equipment_slots(actor_data)):
            col, row = index % 2, index // 2
            rect = pygame.Rect(92 + col * 178, 122 + row * 47, 164, 38)
            self._slot_rects[slot] = rect
            pygame.draw.rect(screen, (70, 74, 82), rect, border_radius=4)
            item = equipment.get(slot)
            label = f"{slot.replace('_', ' ').title()}: {item.get('name')}" if item else f"{slot.replace('_', ' ').title()}: Empty"
            screen.blit(font.render(label[:24], True, (245, 245, 245)), (rect.x + 7, rect.y + 10))
        pygame.draw.line(screen, (100, 105, 115), (445, 106), (445, 516), 1)
        screen.blit(font.render(f"Carried items ({len(actor_data.get('inventory', []))})", True,
                                (220, 230, 245)), (462, 98))
        self._item_rects = {}
        items = actor_data.get("inventory", [])
        visible_count = 13
        self.scroll = min(self.scroll, max(0, len(items) - visible_count))
        for index, item in enumerate(items[self.scroll:self.scroll + visible_count]):
            row = index
            rect = pygame.Rect(462, 122 + row * 26, 242, 23)
            self._item_rects[item.get("id")] = rect
            selected = item.get("id") == self.selected_id
            pygame.draw.rect(screen, (83, 103, 125) if selected else (57, 60, 67), rect)
            label = item.get("name", "Item")
            screen.blit(font.render(label[:31], True, (245, 245, 245)), (rect.x + 5, rect.y + 3))
        pygame.draw.rect(screen, (77, 110, 80), self._use_rect, border_radius=4)
        screen.blit(font.render("Use selected", True, (250, 250, 250)),
                    (self._use_rect.x + 15, self._use_rect.y + 9))
        screen.blit(font.render("Select an item, then click an empty compatible slot to equip it.",
                                True, (190, 195, 205)), (92, 506))
