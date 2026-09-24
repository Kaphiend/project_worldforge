"""Spell and ability book plus numbered action bars saved on each actor."""
import pygame
from worldforge.content.classes import ABILITIES, CLASSES, SPELLS
from worldforge.actors.factory import item_definition
from worldforge.core.progression import (prepared_leveled_spells, prepared_spell_limit,
                         spell_source_class)

BAR_COUNT = 4
SLOTS_PER_BAR = 10
SLOT_WIDTH = 46
SLOT_HEIGHT = 38
SLOT_GAP = 4

SYSTEM_ACTIONS = {
    "weapon_attack": {
        "name": "Weapon Attack",
        "description": "Attack with the currently selected primary weapon.",
        "action_cost": "action",
        "targeting": {"mode": "one_target"},
    },
    "ranged_weapon_attack": {
        "name": "Ranged Weapon Attack",
        "description": "Attack with the equipped ranged weapon.",
        "action_cost": "action",
        "targeting": {"mode": "one_target"},
    },
    "throw_weapon": {
        "name": "Throw Main-hand Weapon",
        "description": "Throw a main-hand weapon with the thrown property.",
        "action_cost": "action",
        "targeting": {"mode": "one_target"},
    },
}


def normalize_action_hotbars(value):
    """Return a safe 4x10 typed action grid, migrating old spell-only saves."""
    source = value if isinstance(value, list) else []
    bars = []
    for bar_index in range(BAR_COUNT):
        source_bar = (source[bar_index] if bar_index < len(source)
                      and isinstance(source[bar_index], list) else [])
        row = []
        for slot_index in range(SLOTS_PER_BAR):
            action = source_bar[slot_index] if slot_index < len(source_bar) else None
            if isinstance(action, dict):
                kind, action_id = action.get("kind"), action.get("id")
                action = f"{kind}:{action_id}" if kind and action_id else None
            elif isinstance(action, str) and ":" not in action and action in SPELLS:
                action = f"spell:{action}"
            if isinstance(action, str):
                kind, _, action_id = action.partition(":")
                if not ((kind == "spell" and action_id in SPELLS)
                        or (kind == "ability" and action_id in ABILITIES)
                        or (kind == "action" and action_id in SYSTEM_ACTIONS)):
                    action = None
            else:
                action = None
            row.append(action)
        bars.append(row)
    return bars


def action_definition(action):
    if not action:
        return None, None, None
    kind, _, action_id = action.partition(":")
    table = (SPELLS if kind == "spell" else ABILITIES if kind == "ability"
             else SYSTEM_ACTIONS if kind == "action" else {})
    return kind, action_id, table.get(action_id)


def _slot_label(index):
    return "0" if index == 9 else str(index + 1)


def _wrap_lines(font, text, max_width):
    lines, current = [], ""
    for word in str(text).split():
        candidate = f"{current} {word}".strip()
        if current and font.size(candidate)[0] > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _fit_line(font, text, max_width):
    value = str(text)
    if font.size(value)[0] <= max_width:
        return value
    while value and font.size(value + "…")[0] > max_width:
        value = value[:-1]
    return value + "…"


def _draw_tooltip(screen, font, definition, position, kind="spell"):
    lines = [definition.get("name", kind.title())]
    description = definition.get("description", "No description available.")
    current = ""
    for word in description.split():
        candidate = f"{current} {word}".strip()
        if current and font.size(candidate)[0] > 320:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if kind == "spell":
        cost = max(0, int(definition.get("spell_point_cost", 1)))
        lines.append(f"Spell points: {cost}")
    elif definition.get("action_cost"):
        lines.append(f"Action: {str(definition['action_cost']).replace('_', ' ')}")
    if definition.get("casting_time"):
        lines.append(f"Casting time: {definition['casting_time'].replace('_', ' ')}")
    targeting = definition.get("targeting", {})
    if targeting.get("range_feet") is not None:
        lines.append(f"Range: {targeting['range_feet']} ft")
    width = min(350, max(font.size(line)[0] for line in lines) + 20)
    line_height = font.get_linesize()
    height = len(lines) * line_height + 12
    x = min(position[0] + 14, screen.get_width() - width - 6)
    y = min(position[1] + 14, screen.get_height() - height - 6)
    panel = pygame.Surface((width, height), pygame.SRCALPHA)
    panel.fill((8, 10, 14, 245))
    pygame.draw.rect(panel, (130, 145, 170), panel.get_rect(), 1)
    screen.blit(panel, (x, y))
    for index, line in enumerate(lines):
        color = (255, 225, 150) if index == 0 else (240, 242, 248)
        screen.blit(font.render(line, True, color),
                    (x + 10, y + 6 + index * line_height))


class SpellbookUI:
    def __init__(self):
        self.visible = False
        self.active_bar = 0
        self.page = "prepared"
        self.selected_action = None
        self.scroll = 0
        self.slot_rects = []
        self.spell_rects = []
        self.page_rects = []
        self.tooltips_enabled = True
        self.hud_slot_rects = []

    def toggle(self):
        self.visible = not self.visible
        self.selected_action = None

    def cycle_bar(self):
        self.active_bar = (self.active_bar + 1) % BAR_COUNT

    def handle_event(self, event, actor_data):
        if event.type == pygame.MOUSEWHEEL and self.visible:
            known = self._known_actions(actor_data)
            self.scroll = max(0, min(max(0, len(known) - 12), self.scroll - event.y))
            return
        if event.type != pygame.MOUSEBUTTONDOWN:
            return
        bars = normalize_action_hotbars(actor_data.get("spell_hotbars"))
        if self.visible and event.button == 3:
            for rect, slot_index in self.slot_rects:
                if rect.collidepoint(event.pos):
                    bars[self.active_bar][slot_index] = None
                    actor_data["spell_hotbars"] = bars
                    self.selected_action = None
                    return
        if event.button != 1 or not self.visible:
            return
        for rect, page in self.page_rects:
            if rect.collidepoint(event.pos):
                self.page = page
                self.selected_action = None
                self.scroll = 0
                return
        for rect, action in self.spell_rects:
            if rect.collidepoint(event.pos):
                if action.startswith("prepare:"):
                    spell_id = action.partition(":")[2]
                    return {"type": "prepare_spell", "spell_id": spell_id,
                            "prepare": spell_id not in actor_data.get(
                                "prepared_spells", [])}
                self.selected_action = action
                return
        if self.selected_action:
            for rect, slot_index in self.slot_rects:
                if rect.collidepoint(event.pos):
                    bars[self.active_bar][slot_index] = self.selected_action
                    actor_data["spell_hotbars"] = bars
                    self.selected_action = None
                    return

    def _known_actions(self, actor_data):
        if self.page in {"prepared", "spellbook"}:
            known = actor_data.get("known_spells", [])
            ids = (actor_data.get("prepared_spells", [])
                   if self.page == "prepared" else known)
            if self.page == "spellbook":
                return [(f"prepare:{item_id}", SPELLS[item_id])
                        for item_id in ids if item_id in SPELLS]
            return [(f"spell:{item_id}", SPELLS[item_id])
                    for item_id in ids if item_id in SPELLS]
        actions = [(f"ability:{item_id}", ABILITIES[item_id])
                   for item_id in actor_data.get("known_abilities", [])
                   if item_id in ABILITIES]
        # Generic weapon actions share the ability page and the same bars as
        # class abilities, so every actor can assign their attacks consistently.
        actions.insert(0, ("action:weapon_attack", SYSTEM_ACTIONS["weapon_attack"]))
        equipment = actor_data.get("equipment", {})
        if equipment.get("ranged"):
            actions.insert(1, ("action:ranged_weapon_attack",
                               SYSTEM_ACTIONS["ranged_weapon_attack"]))
        main_hand = equipment.get("main_hand")
        if main_hand and "thrown" in item_definition(main_hand).get("tags", []):
            actions.insert(2, ("action:throw_weapon", SYSTEM_ACTIONS["throw_weapon"]))
        return actions

    def draw_bar(self, screen, font, actor_data):
        bars = normalize_action_hotbars(actor_data.get("spell_hotbars"))
        actor_data["spell_hotbars"] = bars
        total = SLOTS_PER_BAR * SLOT_WIDTH + (SLOTS_PER_BAR - 1) * SLOT_GAP
        left_half = screen.get_width() // 2
        x0 = 12 + max(0, (left_half - total) // 2)
        mouse = pygame.mouse.get_pos()
        hovered = None
        self.hud_slot_rects = []
        visible_bars = [index for index, bar in enumerate(bars) if any(bar)]
        if visible_bars:
            label = font.render(f"Active bar {self.active_bar + 1}/4 (`)", True,
                                (255, 220, 130))
            label_y = (screen.get_height() - SLOT_HEIGHT - 12
                       - max(0, len(visible_bars) - 1) * (SLOT_HEIGHT + 6) - 20)
            screen.blit(label, (12, label_y))
        for row, bar_index in enumerate(reversed(visible_bars)):
            y = screen.get_height() - SLOT_HEIGHT - 12 - row * (SLOT_HEIGHT + 6)
            active = bar_index == self.active_bar
            tag = font.render(f"{bar_index + 1}{'*' if active else ''}", True,
                              (255, 220, 130) if active else (190, 202, 220))
            screen.blit(tag, (x0 - 15, y + 10))
            for slot_index, action in enumerate(bars[bar_index]):
                if not action:
                    continue
                rect = pygame.Rect(x0 + slot_index * (SLOT_WIDTH + SLOT_GAP), y,
                                   SLOT_WIDTH, SLOT_HEIGHT)
                self.hud_slot_rects.append((rect, action))
                selected = rect.collidepoint(mouse)
                pygame.draw.rect(screen, (48, 57, 75), rect, border_radius=4)
                border = ((255, 218, 130) if active else (125, 145, 175))
                if selected:
                    border = (255, 245, 205)
                pygame.draw.rect(screen, border, rect, 2, border_radius=4)
                screen.blit(font.render(_slot_label(slot_index), True,
                                        (255, 220, 130)), (rect.x + 4, rect.y + 3))
                kind, action_id, definition = action_definition(action)
                action_label = _fit_line(font, definition.get("name", action_id),
                                         rect.width - 8)
                screen.blit(font.render(action_label, True, (242, 244, 250)),
                            (rect.x + 4, rect.y + 19))
                if selected and self.tooltips_enabled:
                    hovered = (definition, kind)
        if hovered:
            _draw_tooltip(screen, font, hovered[0], mouse, hovered[1])

    def hud_action_at(self, position):
        """Return an assigned HUD action clicked by the player, if any."""
        return next((action for rect, action in self.hud_slot_rects
                     if rect.collidepoint(position)), None)

    def draw_book(self, screen, font, actor_data):
        if not self.visible:
            return
        width, height = 660, min(620, screen.get_height() - 60)
        left, top = (screen.get_width() - width) // 2, (screen.get_height() - height) // 2
        panel = pygame.Surface((width, height), pygame.SRCALPHA)
        panel.fill((14, 18, 25, 245))
        pygame.draw.rect(panel, (145, 160, 185), panel.get_rect(), 2)
        screen.blit(panel, (left, top))
        screen.blit(font.render("SPELLBOOK  |  - or Esc to close", True,
                                (255, 225, 150)), (left + 18, top + 14))
        guide_font = pygame.font.Font(None, 16)
        screen.blit(guide_font.render(
            "Click a known spell to prepare or unprepare it.",
            True, (210, 220, 235)), (left + 18, top + 40))
        screen.blit(guide_font.render(
            "Leveled spells use your class preparation limit; cantrips are free.",
            True, (210, 220, 235)), (left + 18, top + 57))
        self.page_rects = []
        tabs_y = top + 78
        pages = (("prepared", "Prepared Spells"),
                 ("spellbook", "Spellbook"),
                 ("abilities", "Class Abilities"))
        for page_index, (page, label) in enumerate(pages):
            rect = pygame.Rect(left + 18 + page_index * 150, tabs_y, 140, 28)
            self.page_rects.append((rect, page))
            pygame.draw.rect(screen, (65, 76, 96) if self.page == page else (34, 40, 52),
                             rect, border_radius=3)
            pygame.draw.rect(screen, (160, 175, 200), rect, 1, border_radius=3)
            screen.blit(font.render(label, True, (240, 240, 245)),
                        (rect.x + 12, rect.y + 6))
        known = self._known_actions(actor_data)
        if self.page == "prepared":
            class_ids = {entry.get("name") for entry in actor_data.get("classes", []) or []
                         if entry.get("name")}
            if actor_data.get("char_class"):
                class_ids.add(actor_data["char_class"])
            casting_classes = [class_id for class_id in CLASSES
                               if class_id in class_ids
                               and CLASSES[class_id].get("spellcasting_ability")]
            counts = [f"{class_id.title()} "
                      f"{len(prepared_leveled_spells(actor_data, class_id))}/"
                      f"{prepared_spell_limit(actor_data, class_id)}"
                      for class_id in casting_classes]
            count_text = ("Prepared: " + ", ".join(counts)
                          if counts else "No spellcasting class")
            count_text += "  (cantrips don't count)"
            screen.blit(guide_font.render(count_text, True, (255, 225, 150)),
                        (left + 18, top + 101))
        row_top = top + (132 if self.page == "prepared" else 114)
        visible_count = max(1, (height - (228 if self.page == "prepared" else 210)) // 30)
        self.scroll = min(self.scroll, max(0, len(known) - visible_count))
        self.spell_rects = []
        mouse = pygame.mouse.get_pos()
        hovered_definition = None
        hovered_kind = "spell"
        for row, (action, definition) in enumerate(known[self.scroll:self.scroll + visible_count]):
            rect = pygame.Rect(left + 18, row_top + row * 30, width - 36, 28)
            self.spell_rects.append((rect, action))
            hovered = rect.collidepoint(mouse)
            color = ((67, 78, 100) if action == self.selected_action else
                     (45, 52, 67) if hovered else (30, 36, 48))
            pygame.draw.rect(screen, color, rect, border_radius=3)
            pygame.draw.rect(screen, (100, 115, 140), rect, 1, border_radius=3)
            prefix = "PREPARED  " if action.startswith("prepare:") and action[8:] in actor_data.get("prepared_spells", []) else (
                "PREPARE  " if action.startswith("prepare:") else "")
            label = _fit_line(font, prefix + definition.get("name", action),
                              rect.width - 18)
            screen.blit(font.render(label, True,
                                    (242, 244, 250)), (rect.x + 9, rect.y + 6))
            if hovered and self.tooltips_enabled:
                hovered_definition = definition
                hovered_kind = "spell" if self.page != "abilities" else "ability"
        if not known:
            message = ("No prepared spells. Prepare known spells in the Spellbook page."
                       if self.page == "prepared" else
                       "No spells known yet. Learn spells from a trainer."
                       if self.page == "spellbook" else
                       "No class abilities known yet. Learn them from a trainer.")
            for message_index, line in enumerate(
                    _wrap_lines(font, message, width - 36)[:3]):
                screen.blit(font.render(line, True, (210, 220, 235)),
                            (left + 18, top + 142 + message_index * 23))
        page_y = top + height - 66
        screen.blit(font.render(f"Bar {self.active_bar + 1}/4", True,
                                (255, 225, 150)), (left + 18, page_y - 23))
        total = SLOTS_PER_BAR * 46 + (SLOTS_PER_BAR - 1) * 4
        slot_left = left + (width - total) // 2
        bars = normalize_action_hotbars(actor_data.get("spell_hotbars"))
        actor_data["spell_hotbars"] = bars
        self.slot_rects = []
        for slot_index, action in enumerate(bars[self.active_bar]):
            rect = pygame.Rect(slot_left + slot_index * 50, page_y, 46, 38)
            self.slot_rects.append((rect, slot_index))
            selected = bool(action and action == self.selected_action)
            pygame.draw.rect(screen, (62, 76, 100) if selected else (35, 43, 57),
                             rect, border_radius=3)
            pygame.draw.rect(screen, (220, 190, 125) if selected else (105, 125, 155),
                             rect, 1, border_radius=3)
            screen.blit(font.render(_slot_label(slot_index), True, (255, 220, 130)),
                        (rect.x + 2, rect.y + 2))
            if action:
                _, action_id, definition = action_definition(action)
                screen.blit(font.render(definition.get("name", action_id)[:4],
                                        True, (240, 243, 248)), (rect.x + 2, rect.y + 20))
        screen.blit(font.render("Right-click an occupied slot to clear it.", True,
                                (180, 192, 210)), (left + 18, top + height - 22))
        if hovered_definition:
            _draw_tooltip(screen, font, hovered_definition, mouse, hovered_kind)

    def draw(self, screen, font, actor_data):
        self.draw_bar(screen, font, actor_data)
        self.draw_book(screen, font, actor_data)
