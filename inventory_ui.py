"""Gray-box inventory and equipment modal for the local actor."""
import pygame

from factory import equipment_slots, item_definition
from classes import SPELLS


class InventoryScreen:
    def __init__(self):
        self.visible = False
        self.selected_id = None
        self.scroll = 0
        self.rect = pygame.Rect(70, 54, 660, 492)
        self._slot_rects = {}
        self._item_rects = {}
        self._use_rect = pygame.Rect(500, 492, 120, 34)
        self._quick_rects = {}

    @staticmethod
    def _fit_text(text, font, max_width):
        value = str(text)
        if font.size(value)[0] <= max_width:
            return value
        while value and font.size(value + "…")[0] > max_width:
            value = value[:-1]
        return value + "…"

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
        if event.type != pygame.MOUSEBUTTONDOWN:
            return None
        if not self.rect.collidepoint(event.pos):
            return None
        if event.button == 3:
            quick = actor_data.get("quick_items")
            if not isinstance(quick, dict):
                quick = actor_data["quick_items"] = {"q": None, "e": None}
            for key, rect in self._quick_rects.items():
                if rect.collidepoint(event.pos):
                    quick[key] = None
                    return None
            return None
        if event.button != 1:
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
        item = next((entry for entry in actor_data.get("inventory", [])
                     if entry.get("id") == self.selected_id), None)
        if item and item_definition(item).get("consumable"):
            quick = actor_data.get("quick_items")
            if not isinstance(quick, dict):
                quick = actor_data["quick_items"] = {"q": None, "e": None}
            for key, rect in self._quick_rects.items():
                if rect.collidepoint(event.pos):
                    quick[key] = self.selected_id
                    return None
        if self._use_rect.collidepoint(event.pos) and self.selected_id:
            item = next((item for item in actor_data.get("inventory", [])
                         if item.get("id") == self.selected_id), None)
            if item and item_definition(item).get("consumable"):
                return {"type": "use_item", "item": self.selected_id}
        return None

    @staticmethod
    def _tooltip_lines(item):
        definition = item_definition(item)
        lines = [item.get("name") or definition.get("name", "Item")]
        if int(item.get("quantity", 1)) > 1:
            lines.append(f"Quantity: {item['quantity']}")
        category = definition.get("category") or definition.get("slot")
        if category:
            lines.append(str(category).replace("_", " ").title())
        description = item.get("description") or definition.get("description")
        if description:
            lines.append(str(description))
        damage = definition.get("damage_dice")
        if damage:
            lines.append(f"Damage: {damage} {definition.get('damage_type', '')}".strip())
        ranges = definition.get("ranges", {})
        if ranges:
            range_text = ", ".join(f"{name.replace('_', ' ')} {value} ft"
                                    for name, value in ranges.items())
            lines.append(f"Range: {range_text}")
        if definition.get("base_ac") is not None:
            lines.append(f"Armor class: {definition['base_ac']}")
        attributes = item.get("rolled_attributes") or {}
        for name, value in attributes.items():
            lines.append(f"{str(name).replace('_', ' ').title()}: {value}")
        tags = definition.get("tags") or item.get("tags") or []
        if tags:
            lines.append("Tags: " + ", ".join(str(tag).replace("_", " ") for tag in tags))
        effect_id = definition.get("effect_id")
        if effect_id in SPELLS:
            effect = SPELLS[effect_id]
            lines.append(effect.get("name", "Effect"))
            if effect.get("description"):
                lines.append(effect["description"])
        return lines

    @staticmethod
    def _draw_tooltip(screen, font, item, position):
        max_text_width = 290
        rendered_lines = []
        for raw_line in InventoryScreen._tooltip_lines(item):
            words = str(raw_line).split()
            current = ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if current and font.size(candidate)[0] > max_text_width:
                    rendered_lines.append(font.render(current, True, (245, 245, 230)))
                    current = word
                else:
                    current = candidate
            if current:
                rendered_lines.append(font.render(current, True, (245, 245, 230)))
        width = min(max_text_width, max((line.get_width() for line in rendered_lines), default=0)) + 20
        line_height = font.get_linesize()
        height = len(rendered_lines) * line_height + 16
        x = min(position[0] + 14, screen.get_width() - width - 8)
        y = min(position[1] + 14, screen.get_height() - height - 8)
        x, y = max(8, x), max(8, y)
        panel = pygame.Rect(x, y, width, height)
        pygame.draw.rect(screen, (24, 27, 34), panel, border_radius=5)
        pygame.draw.rect(screen, (205, 190, 135), panel, 1, border_radius=5)
        for index, line in enumerate(rendered_lines):
            screen.blit(line, (x + 10, y + 8 + index * line_height))

    def draw(self, screen, actor_data, font, tooltips_enabled=True):
        if not self.visible:
            return
        self.rect.center = (screen.get_width() // 2, screen.get_height() // 2)
        offset_x, offset_y = self.rect.x - 70, self.rect.y - 54
        veil = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 175))
        screen.blit(veil, (0, 0))
        pygame.draw.rect(screen, (36, 39, 45), self.rect, border_radius=8)
        pygame.draw.rect(screen, (175, 180, 190), self.rect, 2, border_radius=8)
        screen.blit(font.render("Inventory and Equipment  |  I or Esc to close", True,
                                (245, 235, 195)), (self.rect.x + 16, self.rect.y + 12))
        gold_label = font.render(f"Gold: {actor_data.get('gold', 0)}", True,
                                 (245, 220, 150))
        screen.blit(gold_label, (self.rect.right - gold_label.get_width() - 18,
                                 self.rect.y + 12))
        screen.blit(font.render("Equipment", True, (220, 230, 245)),
                    (92 + offset_x, 98 + offset_y))
        equipment = actor_data.get("equipment", {})
        self._slot_rects = {}
        for index, slot in enumerate(equipment_slots(actor_data)):
            col, row = index % 2, index // 2
            rect = pygame.Rect(92 + offset_x + col * 178,
                               122 + offset_y + row * 47, 164, 38)
            self._slot_rects[slot] = rect
            pygame.draw.rect(screen, (70, 74, 82), rect, border_radius=4)
            item = equipment.get(slot)
            label = f"{slot.replace('_', ' ').title()}: {item.get('name')}" if item else f"{slot.replace('_', ' ').title()}: Empty"
            screen.blit(font.render(self._fit_text(label, font, rect.width - 14),
                                    True, (245, 245, 245)),
                        (rect.x + 7, rect.y + 10))
        pygame.draw.line(screen, (100, 105, 115), (445 + offset_x, 106 + offset_y),
                         (445 + offset_x, 516 + offset_y), 1)
        screen.blit(font.render(f"Carried items ({len(actor_data.get('inventory', []))})", True,
                                (220, 230, 245)), (462 + offset_x, 98 + offset_y))
        self._item_rects = {}
        items = actor_data.get("inventory", [])
        visible_count = 13
        self.scroll = min(self.scroll, max(0, len(items) - visible_count))
        for index, item in enumerate(items[self.scroll:self.scroll + visible_count]):
            row = index
            rect = pygame.Rect(462 + offset_x, 122 + offset_y + row * 26, 242, 23)
            self._item_rects[item.get("id")] = rect
            selected = item.get("id") == self.selected_id
            pygame.draw.rect(screen, (83, 103, 125) if selected else (57, 60, 67), rect)
            label = item.get("name", "Item")
            if int(item.get("quantity", 1)) > 1:
                label = f"{label} x{item['quantity']}"
            screen.blit(font.render(self._fit_text(label, font, rect.width - 10),
                                    True, (245, 245, 245)),
                        (rect.x + 5, rect.y + 3))
        self._use_rect.topleft = (462 + offset_x, 492 + offset_y)
        self._use_rect.width = 94
        pygame.draw.rect(screen, (77, 110, 80), self._use_rect, border_radius=4)
        button_font = pygame.font.Font(None, 17)
        screen.blit(button_font.render(
            self._fit_text("Use selected", button_font, self._use_rect.width - 10),
            True, (250, 250, 250)),
                    (self._use_rect.x + 5, self._use_rect.y + 9))
        quick_items = actor_data.get("quick_items")
        if not isinstance(quick_items, dict):
            quick_items = actor_data["quick_items"] = {"q": None, "e": None}
        self._quick_rects = {}
        for index, key in enumerate(("q", "e")):
            rect = pygame.Rect(562 + offset_x + index * 72, 492 + offset_y, 66, 34)
            self._quick_rects[key] = rect
            pygame.draw.rect(screen, (67, 83, 100), rect, border_radius=4)
            pygame.draw.rect(screen, (165, 175, 190), rect, 1, border_radius=4)
            item = next((entry for entry in items
                         if entry.get("id") == quick_items.get(key)), None)
            label = f"{key.upper()}: {item.get('name', 'empty')}" if item else f"{key.upper()}: empty"
            screen.blit(font.render(self._fit_text(label, font, rect.width - 6),
                                    True, (240, 240, 240)),
                        (rect.x + 3, rect.y + 10))
        hint_font = pygame.font.Font(None, 14)
        screen.blit(hint_font.render("Click Q/E to bind; right-click to clear.",
                                     True, (190, 195, 205)),
                    (462 + offset_x, 466 + offset_y))
        mouse = pygame.mouse.get_pos()
        hovered = next((next((item for item in items if item.get("id") == item_id), None)
                        for item_id, rect in self._item_rects.items()
                        if rect.collidepoint(mouse)), None)
        if hovered is None:
            hovered = next((actor_data.get("equipment", {}).get(slot)
                            for slot, rect in self._slot_rects.items()
                            if rect.collidepoint(mouse)
                            and actor_data.get("equipment", {}).get(slot)), None)
        if hovered is None:
            quick_items = actor_data.get("quick_items", {})
            hovered = next((entry for key, rect in self._quick_rects.items()
                            if rect.collidepoint(mouse)
                            for entry in items if entry.get("id") == quick_items.get(key)), None)
        if hovered and tooltips_enabled:
            self._draw_tooltip(screen, font, hovered, mouse)
