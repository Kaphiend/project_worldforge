"""Gray-box inventory and equipment modal for the local actor."""
import pygame

from worldforge.actors.factory import effective_max_hp, equipment_slots, item_definition, modifier
from worldforge.content.classes import ALL_SKILLS, ITEM_ATTRIBUTES, SPELLS
from worldforge.combat.rules import armor_class, proficiency_bonus, speed_feet
from worldforge.core.progression import (attribute_points_available, class_resource_maxima,
                         spell_point_max, unspent_xp)


class InventoryScreen:
    def __init__(self):
        self.visible = False
        self.selected_id = None
        self.scroll = 0
        self.sheet_scroll = 0
        self._sheet_viewport = pygame.Rect(0, 0, 0, 0)
        self.rect = pygame.Rect(70, 54, 660, 492)
        self._slot_rects = {}
        self._item_rects = {}
        self._use_rect = pygame.Rect(500, 492, 120, 34)
        self._quick_rects = {}
        self._ability_rects = {}

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
            mouse = pygame.mouse.get_pos()
            if self._sheet_viewport.collidepoint(mouse):
                self.sheet_scroll = max(0, self.sheet_scroll - event.y)
            else:
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
        if attribute_points_available(actor_data):
            for ability, rect in self._ability_rects.items():
                if rect.collidepoint(event.pos):
                    return {"type": "increase_ability", "ability": ability}
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
        if item.get("rarity"):
            lines.append(f"Rarity: {str(item['rarity']).title()}")
        if item.get("item_level") is not None:
            lines.append(f"Item level: {item['item_level']}")
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
        for attribute_id, value in attributes.items():
            attribute = ITEM_ATTRIBUTES.get(attribute_id, {})
            name = attribute.get("name", str(attribute_id).replace("_", " ").title())
            effect = attribute.get("effect", {}).get("kind")
            if effect == "weapon_damage_dice_multiplier":
                lines.append(f"{name}: x{attribute.get('effect', {}).get('multiplier', value)} weapon dice")
            elif effect == "weapon_damage_bonus":
                lines.append(f"{name}: +{value} weapon damage")
            elif effect == "weapon_attack_bonus":
                lines.append(f"{name}: +{value} to weapon attacks")
            elif effect == "armor_class_bonus":
                lines.append(f"{name}: +{value} AC")
            elif effect == "maximum_hp_bonus":
                lines.append(f"{name}: +{value} maximum HP")
            elif effect == "saving_throw_bonus":
                lines.append(f"{name}: +{value} saving throws")
            else:
                lines.append(f"{name}: {value}")
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
        self.rect.size = (min(1080, screen.get_width() - 32),
                          min(620, screen.get_height() - 32))
        self.rect.center = (screen.get_width() // 2, screen.get_height() // 2)
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

        # Keep the sheet, equipment, and carried items together in one modal.
        content_top = self.rect.y + 52
        sheet_x = self.rect.x + 18
        sheet_width = 242
        equipment_x = sheet_x + sheet_width + 16
        equipment_width = 304
        items_x = equipment_x + equipment_width + 18
        items_width = self.rect.right - items_x - 18
        divider_color = (100, 105, 115)
        pygame.draw.line(screen, divider_color, (equipment_x - 9, content_top),
                         (equipment_x - 9, self.rect.bottom - 18), 1)
        pygame.draw.line(screen, divider_color, (items_x - 9, content_top),
                         (items_x - 9, self.rect.bottom - 18), 1)

        sheet_title = font.render(self._fit_text(
            "Character · scroll for details", font, sheet_width), True,
            (220, 230, 245))
        screen.blit(sheet_title, (sheet_x, content_top - 2))
        name = str(actor_data.get("name", "Adventurer"))
        class_id = str(actor_data.get("char_class", ""))
        class_label = class_id.title() if class_id else "Untrained"
        class_levels = actor_data.get("classes", []) or []
        if class_levels:
            class_label = " / ".join(
                f"{entry.get('name', '').title()} {entry.get('level', 1)}"
                for entry in class_levels if entry.get("name")) or class_label
        race_id = str(actor_data.get("race", ""))
        ancestry = race_id.replace("-", " ").title() if race_id else "Unknown ancestry"
        if actor_data.get("subrace"):
            ancestry += " · " + str(actor_data["subrace"]).replace("_", " ").title()
        elif actor_data.get("parent_races"):
            ancestry += " · " + " / ".join(
                str(value).replace("-", " ").title()
                for value in actor_data["parent_races"] if value)
        small_font = pygame.font.Font(None, 18)
        label_font = pygame.font.Font(None, 16)
        screen.blit(font.render(self._fit_text(name, font, sheet_width), True,
                                (255, 225, 155)), (sheet_x, content_top + 28))
        screen.blit(small_font.render(self._fit_text(class_label, small_font, sheet_width),
                                      True, (235, 238, 242)),
                    (sheet_x, content_top + 54))
        screen.blit(small_font.render(self._fit_text(ancestry, small_font, sheet_width),
                                      True, (190, 202, 218)),
                    (sheet_x, content_top + 75))

        summary_y = content_top + 108
        summary = [
            (f"HP  {actor_data.get('current_hp', 0)} / {effective_max_hp(actor_data)}",
             f"AC  {armor_class(actor_data)}"),
            (f"Level  {actor_data.get('level', 1)}",
             f"Speed  {speed_feet(actor_data)} ft"),
            (f"Proficiency  +{proficiency_bonus(actor_data)}",
             f"Unspent XP  {unspent_xp(actor_data)}"),
        ]
        for row, values in enumerate(summary):
            card = pygame.Rect(sheet_x, summary_y + row * 38, sheet_width, 32)
            pygame.draw.rect(screen, (52, 57, 66), card, border_radius=4)
            screen.blit(small_font.render(values[0], True, (245, 245, 238)),
                        (card.x + 8, card.y + 4))
            second = small_font.render(values[1], True, (205, 215, 228))
            screen.blit(second, (card.right - second.get_width() - 8, card.y + 4))

        abilities = actor_data.get("abilities", {}) or {}
        ability_names = (("strength", "STR"), ("dexterity", "DEX"),
                         ("constitution", "CON"), ("intellect", "INT"),
                         ("wisdom", "WIS"), ("charisma", "CHA"))
        ability_y = summary_y + 126
        available_points = attribute_points_available(actor_data)
        if any(int(value or 0) > 30 for value in abilities.values()):
            ability_hint = "Scores can exceed 30; calculations cap at 30"
        elif available_points:
            ability_hint = f"{available_points} points · click a score to add +1"
        else:
            ability_hint = "Effective ability score cap: 30"
        screen.blit(label_font.render(self._fit_text(
            ability_hint, label_font, sheet_width), True, (255, 220, 145)),
            (sheet_x, ability_y - 15))
        self._ability_rects = {}
        for index, (key, short_name) in enumerate(ability_names):
            col, row = index % 2, index // 2
            card = pygame.Rect(sheet_x + col * 122, ability_y + row * 49, 116, 42)
            self._ability_rects[key] = card
            pygame.draw.rect(screen, (47, 52, 61), card, border_radius=4)
            hovered = available_points > 0 and card.collidepoint(pygame.mouse.get_pos())
            pygame.draw.rect(screen, (240, 204, 120) if hovered else (92, 101, 116),
                             card, 1, border_radius=4)
            score = int(abilities.get(key, 10) or 10)
            value = label_font.render(f"{short_name}  {score}", True,
                                       (242, 242, 235))
            mod = modifier(score)
            mod_label = f"{mod:+d}"
            mod_surface = label_font.render(mod_label, True, (255, 220, 145))
            screen.blit(value, (card.x + 7, card.y + 6))
            screen.blit(mod_surface, (card.x + 7, card.y + 23))
            if available_points:
                plus = label_font.render("+1", True, (180, 230, 190))
                screen.blit(plus, (card.right - plus.get_width() - 7, card.y + 23))

        # Detailed character statistics scroll independently from inventory.
        detail_top = ability_y + 3 * 49 + 2
        detail_bottom = self.rect.bottom - 18
        self._sheet_viewport = pygame.Rect(
            sheet_x, detail_top, sheet_width, max(1, detail_bottom - detail_top))
        skills = {str(value).casefold() for value in actor_data.get("skills", []) or []}
        saves = {str(value).casefold() for value in actor_data.get("saves", []) or []}
        abilities = actor_data.get("abilities", {}) or {}
        prof = proficiency_bonus(actor_data)
        skill_ability = {
            "acrobatics": "dexterity", "animal handling": "wisdom",
            "arcana": "intellect", "athletics": "strength",
            "deception": "charisma", "history": "intellect",
            "insight": "wisdom", "intimidation": "charisma",
            "investigation": "intellect", "medicine": "wisdom",
            "nature": "intellect", "perception": "wisdom",
            "performance": "charisma", "persuasion": "charisma",
            "religion": "intellect", "sleight of hand": "dexterity",
            "stealth": "dexterity", "survival": "wisdom",
        }
        details = []

        def add_section(title):
            details.append(("section", title, ""))

        def add_row(label, value, trained=False):
            details.append(("row", label, value, trained))

        add_section("Skills  ·  green = trained")
        wisdom_mod = modifier(abilities.get("wisdom", 10))
        passive_perception = int(actor_data.get(
            "perception_score", 10 + wisdom_mod + (prof if "perception" in skills else 0)))
        add_row("Passive Perception", str(passive_perception), "perception" in skills)
        for skill in ALL_SKILLS:
            ability = skill_ability.get(skill, "wisdom")
            bonus = modifier(abilities.get(ability, 10)) + (prof if skill in skills else 0)
            add_row(skill.title(), f"{bonus:+d}", skill in skills)
        add_section("Saving Throws")
        ability_labels = (("strength", "Strength"), ("dexterity", "Dexterity"),
                          ("constitution", "Constitution"), ("intellect", "Intellect"),
                          ("wisdom", "Wisdom"), ("charisma", "Charisma"))
        for ability, label in ability_labels:
            bonus = modifier(abilities.get(ability, 10)) + (prof if ability in saves else 0)
            add_row(label, f"{bonus:+d}", ability in saves)
        add_section("Proficiencies")
        add_row("Armor", ", ".join(str(value).title() for value in actor_data.get("armor_prof", []) or []) or "None")
        add_row("Weapons", ", ".join(str(value).title() for value in actor_data.get("weapon_prof", []) or []) or "None")
        add_section("Resources and Status")
        try:
            max_spell_points = spell_point_max(actor_data)
        except (KeyError, TypeError, ValueError):
            max_spell_points = int(actor_data.get("spell_points", 0) or 0)
        add_row("Spell Points", f"{actor_data.get('spell_points', 0)} / {max_spell_points}")
        resource_maxima = class_resource_maxima(actor_data)
        for resource_id, amount in (actor_data.get("class_resources", {}) or {}).items():
            current = amount
            definition = resource_maxima.get(resource_id, {})
            maximum = definition.get("maximum", current)
            resource_name = definition.get("name", resource_id).replace("_", " ").title()
            add_row(resource_name, f"{current} / {maximum}")
        conditions = actor_data.get("conditions", []) or []
        condition_names = [str(item.get("name", item.get("id", "Condition")))
                           if isinstance(item, dict) else str(item)
                           for item in conditions]
        add_row("Conditions", ", ".join(condition_names) or "None")
        add_section("Character Details")
        add_row("Subclass", str(actor_data.get("subclass") or "None").replace("_", " ").title())
        add_row("XP", f"{actor_data.get('xp_total', 0)} total · {unspent_xp(actor_data)} unspent")
        add_row("Weapon Set", str(actor_data.get("active_weapon_set", "melee")).title())

        detail_font = pygame.font.Font(None, 17)
        detail_line = 19
        detail_height = len(details) * detail_line
        max_scroll = max(0, (detail_height - self._sheet_viewport.height + detail_line - 1) // detail_line)
        self.sheet_scroll = min(self.sheet_scroll, max_scroll)
        screen.set_clip(self._sheet_viewport)
        y = self._sheet_viewport.y - self.sheet_scroll * detail_line
        for detail in details:
            if detail[0] == "section":
                label = detail_font.render(detail[1], True, (255, 225, 155))
                screen.blit(label, (sheet_x, y + 1))
                pygame.draw.line(screen, (85, 92, 104),
                                 (sheet_x, y + detail_line - 1),
                                 (sheet_x + sheet_width, y + detail_line - 1), 1)
                y += detail_line
                continue
            _, label, value, *flags = detail
            trained = bool(flags and flags[0])
            row = pygame.Rect(sheet_x, y, sheet_width, detail_line)
            if trained:
                pygame.draw.rect(screen, (48, 65, 67), row)
            marker = "● " if trained else "  "
            screen.blit(detail_font.render(
                self._fit_text(marker + label, detail_font, 160), True,
                (180, 230, 190) if trained else (220, 225, 233)), (sheet_x + 3, y + 2))
            value_surface = detail_font.render(str(value), True, (255, 220, 145))
            screen.blit(value_surface, (sheet_x + sheet_width - value_surface.get_width() - 4, y + 2))
            y += detail_line
        screen.set_clip(None)

        equipment_title = font.render("Equipment", True, (220, 230, 245))
        screen.blit(equipment_title, (equipment_x, content_top - 2))
        equipment = actor_data.get("equipment", {})
        self._slot_rects = {}
        slot_font = pygame.font.Font(None, 16)
        equipped_font = pygame.font.Font(None, 19)
        for index, slot in enumerate(equipment_slots(actor_data)):
            col, row = index % 2, index // 2
            rect = pygame.Rect(equipment_x + col * 151,
                               content_top + 28 + row * 47, 143, 38)
            self._slot_rects[slot] = rect
            pygame.draw.rect(screen, (70, 74, 82), rect, border_radius=4)
            item = equipment.get(slot)
            slot_label = slot.replace('_', ' ').title()
            if slot in {"ring1", "ring2"}:
                slot_label = f"Ring {slot[-1]}"
            screen.blit(slot_font.render(slot_label, True, (186, 197, 211)),
                        (rect.x + 7, rect.y + 3))
            item_name = item.get('name', 'Item') if item else "Empty"
            screen.blit(equipped_font.render(
                self._fit_text(item_name, equipped_font, rect.width - 14), True,
                (245, 245, 245) if item else (160, 165, 175)),
                (rect.x + 7, rect.y + 18))

        screen.blit(font.render(f"Carried items ({len(actor_data.get('inventory', []))})", True,
                                (220, 230, 245)), (items_x, content_top - 2))
        self._item_rects = {}
        items = actor_data.get("inventory", [])
        visible_count = max(1, min(15, (self.rect.height - 206) // 26))
        self.scroll = min(self.scroll, max(0, len(items) - visible_count))
        for index, item in enumerate(items[self.scroll:self.scroll + visible_count]):
            row = index
            rect = pygame.Rect(items_x, content_top + 28 + row * 26,
                               items_width, 23)
            self._item_rects[item.get("id")] = rect
            selected = item.get("id") == self.selected_id
            pygame.draw.rect(screen, (83, 103, 125) if selected else (57, 60, 67), rect)
            label = item.get("name", "Item")
            if int(item.get("quantity", 1)) > 1:
                label = f"{label} x{item['quantity']}"
            screen.blit(font.render(self._fit_text(label, font, rect.width - 10),
                                    True, (245, 245, 245)),
                        (rect.x + 5, rect.y + 3))
        controls_y = self.rect.bottom - 60
        self._use_rect.topleft = (items_x, controls_y)
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
        quick_font = pygame.font.Font(None, 17)
        for index, key in enumerate(("q", "e")):
            rect = pygame.Rect(items_x + 102 + index * 116, controls_y, 110, 34)
            self._quick_rects[key] = rect
            pygame.draw.rect(screen, (67, 83, 100), rect, border_radius=4)
            pygame.draw.rect(screen, (165, 175, 190), rect, 1, border_radius=4)
            item = next((entry for entry in items
                         if entry.get("id") == quick_items.get(key)), None)
            label = f"{key.upper()}: {item.get('name', 'empty')}" if item else f"{key.upper()}: empty"
            screen.blit(quick_font.render(
                self._fit_text(label, quick_font, rect.width - 8), True,
                (240, 240, 240)), (rect.x + 4, rect.y + 10))
        hint_font = pygame.font.Font(None, 14)
        screen.blit(hint_font.render("Click Q/E to bind; right-click to clear.",
                                     True, (190, 195, 205)),
                    (items_x, controls_y - 18))
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
