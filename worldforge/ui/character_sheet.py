"""Read-only in-game character sheet modal."""
from copy import deepcopy
import pprint
import textwrap

import pygame

from worldforge.combat.rules import armor_class, modifier, speed_feet


def _actor_dict(actor_data):
    if isinstance(actor_data, dict):
        return deepcopy(actor_data)
    return deepcopy(vars(actor_data))


class CharacterSheetUI:
    def __init__(self):
        self.visible = False
        self.data = {}
        self.raw_data = {}
        self.scroll = 0
        self.panel = pygame.Rect(0, 0, 0, 0)
        self.close_rect = pygame.Rect(0, 0, 0, 0)
        self.content_lines = []

    def open(self, actor_data):
        self.raw_data = _actor_dict(actor_data)
        self.data = deepcopy(self.raw_data.get("data", self.raw_data))
        if isinstance(self.raw_data.get("data"), dict):
            self.data.setdefault("id", self.raw_data.get("id", "unknown"))
            self.data["loot"] = deepcopy(self.raw_data.get("loot", []))
        self.visible = True
        self.scroll = 0

    def close(self):
        self.visible = False
        self.data = {}
        self.raw_data = {}
        self.scroll = 0

    def handle_event(self, event):
        if not self.visible:
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self.close()
        elif event.type == pygame.MOUSEWHEEL:
            self.scroll = max(0, min(max(0, len(self.content_lines) - 1),
                                     self.scroll - event.y * 3))
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.close_rect.collidepoint(event.pos) or not self.panel.collidepoint(event.pos):
                self.close()

    def _lines(self):
        data = self.data
        abilities = data.get("abilities", {}) or {}
        classes = [item for item in data.get("classes", []) or []
                   if isinstance(item, dict) and item.get("name")]
        class_text = ", ".join(
            f"{item['name'].title()} {int(item.get('level', 1) or 1)}"
            for item in classes)
        if not class_text:
            class_text = str(data.get("char_class", "Unknown")).title()
        race = str(data.get("race", "Unknown")).replace("_", " ").title()
        if data.get("subrace"):
            race += f" ({str(data['subrace']).replace('_', ' ').title()})"
        max_hp = data.get("max_hp", data.get("current_hp", 0))
        initiative = modifier(abilities.get("dexterity", 10))

        lines = [
            ("section", "Character"),
            ("text", f"ID: {data.get('id', self.raw_data.get('id', 'unknown'))}"),
            ("text", f"Species: {race}"),
            ("text", f"Class: {class_text}"),
            ("text", f"Level: {data.get('level', 1)}    XP: {data.get('xp_total', 0)}"),
            ("section", "Combat Stats"),
            ("text", f"Hit Points: {data.get('current_hp', 0)} / {max_hp}    "
                     f"Armor Class: {armor_class(data)}"),
            ("text", f"Speed: {speed_feet(data)} ft    Initiative: "
                     f"{initiative:+d}"),
            ("section", "Abilities"),
            ("text", "    ".join(
                f"{name[:3].upper()} {int(abilities.get(name, 10) or 10)} "
                f"({modifier(abilities.get(name, 10) or 10):+d})"
                for name in ("strength", "dexterity", "constitution",
                             "intellect", "wisdom", "charisma"))),
        ]

        equipment = data.get("equipment", {}) or {}
        equipped = []
        for slot, item in equipment.items():
            if item:
                equipped.append(
                    f"{slot.replace('_', ' ').title()}: "
                    f"{item.get('name', item.get('template_id', 'Item'))}")
        lines.append(("section", "Equipment"))
        lines.extend(("text", item) for item in equipped or ["Nothing equipped."])

        skills = data.get("skills", []) or []
        if isinstance(skills, dict):
            skills = [name for name, trained in skills.items() if trained]
        lines.append(("section", "Skills and Conditions"))
        lines.append(("text", "Skills: " + (", ".join(
            str(skill).replace("_", " ").title() for skill in skills)
            if skills else "None")))
        conditions = [str(item.get("condition", item.get("name", "Condition")))
                      if isinstance(item, dict) else str(item)
                      for item in data.get("conditions", []) or []]
        lines.append(("text", "Conditions: " + (", ".join(conditions)
                                                  if conditions else "None")))

        inventory = data.get("inventory", []) or []
        lines.append(("section", f"Inventory ({len(inventory)} stacks)"))
        for item in inventory:
            name = item.get("name", item.get("template_id", "Item"))
            quantity = max(1, int(item.get("quantity", 1) or 1))
            lines.append(("text", f"{name} x{quantity}"))
        if not inventory:
            lines.append(("text", "Empty"))
        loot = data.get("loot", []) or []
        if loot:
            lines.append(("section", f"Unclaimed Loot ({len(loot)} items)"))
            for item in loot:
                name = item.get("name", item.get("template_id", "Item"))
                quantity = max(1, int(item.get("quantity", 1) or 1))
                lines.append(("text", f"{name} x{quantity}"))
        lines.append(("section", "Raw Debug Snapshot"))
        raw_text = pprint.pformat(self.raw_data, width=72, sort_dicts=True)
        for raw_line in raw_text.splitlines():
            wrapped = textwrap.wrap(raw_line, width=72, subsequent_indent="    ",
                                    break_long_words=True,
                                    break_on_hyphens=False)
            lines.extend(("raw", line) for line in (wrapped or [""]))
        return lines

    def draw(self, screen, font):
        if not self.visible:
            return
        width = min(620, screen.get_width() - 24)
        height = min(590, screen.get_height() - 24)
        self.panel = pygame.Rect(0, 0, max(1, width), max(1, height))
        self.panel.center = screen.get_rect().center
        veil = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 175))
        screen.blit(veil, (0, 0))
        pygame.draw.rect(screen, (20, 25, 33), self.panel, border_radius=7)
        pygame.draw.rect(screen, (180, 195, 218), self.panel, 2, border_radius=7)

        name = self.data.get("name", "Character")
        title = font.render(f"DEBUG INSPECTOR  |  {name}", True,
                            (255, 225, 155))
        screen.blit(title, (self.panel.x + 18, self.panel.y + 15))
        self.close_rect = pygame.Rect(self.panel.right - 42,
                                      self.panel.y + 9, 30, 28)
        pygame.draw.rect(screen, (65, 73, 87), self.close_rect, border_radius=4)
        close_text = font.render("X", True, (245, 245, 245))
        screen.blit(close_text, close_text.get_rect(center=self.close_rect.center))

        self.content_lines = self._lines()
        content_top = self.panel.y + 55
        content_bottom = self.panel.bottom - 26
        line_height = font.get_linesize() + 5
        visible = max(1, (content_bottom - content_top) // line_height)
        self.scroll = min(self.scroll, max(0, len(self.content_lines) - visible))
        debug_font = pygame.font.SysFont("monospace", 16)
        for row, (kind, text) in enumerate(
                self.content_lines[self.scroll:self.scroll + visible]):
            y = content_top + row * line_height
            color = ((240, 211, 145) if kind == "section" else
                     (185, 205, 225) if kind == "raw" else
                     (232, 236, 243))
            row_font = debug_font if kind == "raw" else font
            rendered = row_font.render(str(text), True, color)
            screen.blit(rendered, (self.panel.x + 20, y))
        hint = pygame.font.Font(None, 17).render(
            "Scroll to view more  ·  Esc or click outside to close", True,
            (170, 183, 204))
        screen.blit(hint, (self.panel.x + 18, self.panel.bottom - 21))
