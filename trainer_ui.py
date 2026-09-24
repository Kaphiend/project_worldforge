"""Spellbook-style interface for buying class spells and abilities.

The trainer list is assembled from the content tables so mods can add options
without changing this screen. Purchase checks remain authoritative in game.py.
"""
import pygame

from classes import ABILITIES, CLASSES, SPELLS
from progression import class_unlocked_level, purchase_cost, qualified_level, unspent_xp


class TrainerUI:
    def __init__(self):
        self.visible = False
        self.class_id = next(iter(CLASSES), "")
        self.scroll = 0
        self.notice = ""

    def toggle(self):
        self.visible = not self.visible
        self.notice = ""

    def _items(self, data):
        rows = []
        for kind, table, purchases_key in (
                ("spell", SPELLS, "class_spell_purchases"),
                ("ability", ABILITIES, "class_ability_purchases")):
            owned = set(data.get(purchases_key, {}).get(self.class_id, []))
            for item_id, definition in table.items():
                if (self.class_id not in definition.get("classes", [])
                        or definition.get("acquisition") != "trainer_purchase"):
                    continue
                tier = int(definition.get("prerequisite_class_level", 1))
                rows.append((tier, definition.get("name", item_id), kind,
                             item_id, definition, item_id in owned))
        return sorted(rows, key=lambda row: (row[0], row[1].lower()))

    @staticmethod
    def _wrap(text, font, width):
        lines, current = [], ""
        for word in str(text).split():
            candidate = f"{current} {word}".strip()
            if current and font.size(candidate)[0] > width:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines

    def _draw_tooltip(self, screen, title, detail, mouse_pos):
        if not title:
            return
        title_font = pygame.font.Font(None, 22)
        detail_font = pygame.font.Font(None, 18)
        lines = self._wrap(detail, detail_font, 310)[:9]
        width = min(350, max(title_font.size(title)[0],
                             max((detail_font.size(line)[0] for line in lines),
                                 default=0)) + 24)
        height = 14 + title_font.get_linesize() + len(lines) * detail_font.get_linesize() + 10
        mouse_x, mouse_y = mouse_pos
        x = mouse_x + 16
        y = mouse_y + 16
        if x + width > screen.get_width() - 8:
            x = mouse_x - width - 16
        if y + height > screen.get_height() - 8:
            y = screen.get_height() - height - 8
        x = max(8, x)
        tooltip = pygame.Surface((width, height), pygame.SRCALPHA)
        tooltip.fill((10, 13, 18, 248))
        pygame.draw.rect(tooltip, (220, 205, 155), tooltip.get_rect(),
                         1, border_radius=5)
        tooltip.blit(title_font.render(title, True, (255, 229, 155)), (10, 7))
        for index, line in enumerate(lines):
            tooltip.blit(detail_font.render(line, True, (240, 242, 238)),
                         (10, 7 + title_font.get_linesize()
                          + index * detail_font.get_linesize()))
        screen.blit(tooltip, (x, y))

    def handle_event(self, event, data):
        if not self.visible:
            return None
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_f):
                self.visible = False
                return None
            if event.key == pygame.K_UP:
                self.scroll = max(0, self.scroll - 1)
            elif event.key == pygame.K_DOWN:
                self.scroll += 1
        if event.type != pygame.MOUSEBUTTONDOWN:
            return None
        if event.button == 4:
            self.scroll = max(0, self.scroll - 2)
            return None
        if event.button == 5:
            self.scroll += 2
            return None
        x, y = event.pos
        surface = pygame.display.get_surface()
        screen_width = surface.get_width() if surface else 800
        for index, class_id in enumerate(CLASSES):
            rect = pygame.Rect(24 + index * 80, 86, 76, 32)
            if rect.collidepoint(x, y):
                self.class_id = class_id
                self.scroll = 0
                return None
        if y >= 142:
            visible_rows = self._items(data)[self.scroll: self.scroll + 10]
            for index, row in enumerate(visible_rows):
                row_rect = pygame.Rect(22, 145 + index * 38,
                                       screen_width - 44, 34)
                buy_rect = pygame.Rect(screen_width - 120, row_rect.y + 2,
                                       82, 30)
                if buy_rect.collidepoint(x, y) and not row[5]:
                    _tier, _name, kind, item_id, definition, _owned = row
                    return {"type": "trainer_purchase", "class_id": self.class_id,
                            "kind": kind, "item_id": item_id,
                            "xp_purchase_cost": purchase_cost(definition)}
        return None

    def draw(self, screen, data, font):
        if not self.visible:
            return
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        screen.blit(overlay, (0, 0))
        panel = pygame.Rect(10, 28, screen.get_width() - 20, screen.get_height() - 56)
        pygame.draw.rect(screen, (24, 28, 32), panel, border_radius=8)
        pygame.draw.rect(screen, (190, 180, 140), panel, 2, border_radius=8)
        title = pygame.font.Font(None, 30)
        screen.blit(title.render("Trainer", True, (250, 235, 190)), (26, 42))
        status = (f"Qualified level {qualified_level(data)}   XP {unspent_xp(data)}"
                  f"   {self.class_id.title()} tier {class_unlocked_level(data, self.class_id)}")
        screen.blit(font.render(status, True, (215, 225, 220)), (180, 48))
        hover_title, hover_detail = "", ""
        mouse_pos = pygame.mouse.get_pos()
        for index, class_id in enumerate(CLASSES):
            rect = pygame.Rect(24 + index * 80, 86, 76, 32)
            pygame.draw.rect(screen, (82, 110, 88) if class_id == self.class_id
                             else (55, 62, 68), rect, border_radius=4)
            label = pygame.font.Font(None, 18).render(class_id.title()[:10], True,
                                                       (245, 245, 240))
            screen.blit(label, label.get_rect(center=rect.center))
            if rect.collidepoint(mouse_pos):
                hover_title = class_id.title()
                hover_detail = CLASSES[class_id].get("summary", "")
        owned_spells = set(data.get("class_spell_purchases", {}).get(self.class_id, []))
        owned_abilities = set(data.get("class_ability_purchases", {}).get(self.class_id, []))
        rows = self._items(data)
        self.scroll = min(self.scroll, max(0, len(rows) - 10))
        frontier = class_unlocked_level(data, self.class_id)
        ceiling = qualified_level(data)
        for index, row in enumerate(rows[self.scroll:self.scroll + 10]):
            tier, name, kind, item_id, definition, is_owned = row
            y = 145 + index * 38
            row_rect = pygame.Rect(22, y, screen.get_width() - 44, 34)
            can_buy = (not is_owned and tier <= frontier and tier <= ceiling
                       and purchase_cost(definition) is not None
                       and unspent_xp(data) >= purchase_cost(definition))
            color = (51, 67, 58) if can_buy else (43, 47, 51)
            pygame.draw.rect(screen, color, row_rect, border_radius=4)
            suffix = "owned" if is_owned else f"level {tier} {kind}"
            screen.blit(font.render(f"{name}  ·  {suffix}", True,
                                    (240, 240, 230)), (32, y + 8))
            cost = purchase_cost(definition)
            button = pygame.Rect(screen.get_width() - 120, y + 2, 82, 30)
            pygame.draw.rect(screen, (76, 120, 78) if can_buy else (72, 72, 72),
                             button, border_radius=4)
            label = "Owned" if is_owned else (f"{cost} XP" if cost is not None else "No cost")
            screen.blit(pygame.font.Font(None, 16).render(label, True, (250, 250, 245)),
                        (button.x + 5, button.y + 9))
            if row_rect.collidepoint(mouse_pos):
                hover_title = name
                details = [definition.get("description", "No description available.")]
                if kind == "spell":
                    cast_cost = int(definition.get("spell_point_cost", 1) or 0)
                    details.append("Cast cost: " + ("no spell points" if cast_cost == 0
                                                    else f"{cast_cost} spell point(s)"))
                else:
                    uses = definition.get("uses_per_combat", 1)
                    details.append("Uses: " + ("resource-limited" if uses is None
                                               else f"{uses} per fight"))
                if is_owned:
                    details.append("Already learned.")
                elif tier > ceiling:
                    details.append(f"Locked: requires qualified level {tier}.")
                elif tier > frontier:
                    details.append(f"Locked: learn an option from tier {frontier} first.")
                elif cost is not None and cost > unspent_xp(data):
                    details.append(f"Requires {cost} XP; you have {unspent_xp(data)}.")
                else:
                    details.append(f"Available to learn for {cost} XP.")
                hover_detail = "  ".join(details)
        footer = ("Click an available price to learn it. Tiers unlock in order. "
                  "Feat choices at levels 4, 8, 12, 16, and 19 are not implemented. Esc closes.")
        screen.blit(pygame.font.Font(None, 17).render(footer, True, (205, 210, 210)),
                    (26, panel.bottom - 26))
        if self.notice:
            screen.blit(font.render(self.notice, True, (255, 215, 150)), (26, 120))
        self._draw_tooltip(screen, hover_title, hover_detail, mouse_pos)
