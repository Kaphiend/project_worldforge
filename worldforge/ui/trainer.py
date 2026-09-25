"""Spellbook-style interface for buying class spells and abilities.

The trainer list is assembled from the content tables so mods can add options
without changing this screen. Purchase checks remain authoritative in game.py.
"""
import pygame

from worldforge.content.classes import (ABILITIES, CLASSES, SPELLS, SUBCLASSES,
                                        skill_options, subclass_feature_items)
from worldforge.core.progression import (adjusted_purchase_cost, class_unlock_cost,
                         class_unlocked_level, qualified_level,
                         unlocked_classes, unspent_xp, levels_to_apply,
                         class_feature_definition, class_feature_choice_slots)
from worldforge.combat.rules import (ROGUE_WEAPON_MASTERY,
                                     FIGHTING_STYLE_OPTIONS,
                                     weapon_mastery_eligible)
from worldforge.core.progression import attribute_points_available


class TrainerUI:
    def __init__(self):
        self.visible = False
        self.class_id = next(iter(CLASSES), "")
        self.scroll = 0
        self.notice = ""
        self.section = "features"
        self.section_by_class = {}
        self._section_rects = {}
        self._attribute_rects = {}
        self.confirmation = None
        self._confirmation_rects = {}

    def _ask_confirmation(self, action, title, cost):
        self.confirmation = {"action": action, "title": title, "cost": cost}

    def _draw_confirmation(self, screen, font):
        if not self.confirmation:
            self._confirmation_rects = {}
            return
        veil = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 175))
        screen.blit(veil, (0, 0))
        rect = pygame.Rect(0, 0, min(460, screen.get_width() - 32), 190)
        rect.center = screen.get_rect().center
        pygame.draw.rect(screen, (35, 39, 45), rect, border_radius=8)
        pygame.draw.rect(screen, (220, 194, 136), rect, 2, border_radius=8)
        small = pygame.font.Font(None, 22)
        action_type = self.confirmation.get("action", {}).get("type")
        heading = ("Confirm purchase" if action_type in {
            "trainer_purchase", "unlock_class"} else
            "Confirm point spend" if action_type == "increase_ability" else
            "Confirm level up")
        screen.blit(small.render(heading, True, (255, 226, 165)),
                    (rect.x + 20, rect.y + 20))
        title = self._fit(self.confirmation["title"], small, rect.width - 40)
        screen.blit(small.render(title, True, (245, 245, 238)),
                    (rect.x + 20, rect.y + 60))
        screen.blit(small.render(self.confirmation["cost"], True, (220, 225, 226)),
                    (rect.x + 20, rect.y + 92))
        cancel = pygame.Rect(rect.x + 150, rect.bottom - 48, 110, 32)
        confirm = pygame.Rect(rect.x + 278, rect.bottom - 48, 140, 32)
        pygame.draw.rect(screen, (74, 76, 80), cancel, border_radius=4)
        pygame.draw.rect(screen, (73, 119, 78), confirm, border_radius=4)
        screen.blit(small.render("Cancel", True, (250, 250, 245)),
                    small.render("Cancel", True, (250, 250, 245)).get_rect(center=cancel.center))
        screen.blit(small.render("Confirm", True, (250, 250, 245)),
                    small.render("Confirm", True, (250, 250, 245)).get_rect(center=confirm.center))
        self._confirmation_rects = {"cancel": cancel, "confirm": confirm}

    @staticmethod
    def _panel_rect(width, height):
        panel = pygame.Rect(0, 0, min(1240, max(320, width - 24)),
                            min(744, max(400, height - 24)))
        panel.center = (width // 2, height // 2)
        return panel

    @staticmethod
    def _class_tab_rect(panel, index, count):
        step = (panel.width - 48) / max(1, count)
        return pygame.Rect(round(panel.x + 24 + index * step), panel.y + 58,
                           max(44, int(step - 6)), 32)

    @staticmethod
    def _visible_row_count(panel):
        return max(1, min(10, (panel.height - 280) // 38))

    def toggle(self, data=None):
        self.visible = not self.visible
        self.notice = ""
        if data and data.get("char_class") in CLASSES:
            self.class_id = data["char_class"]
            self.scroll = 0
        self.section = self.section_by_class.get(self.class_id, "features")

    def _items(self, data):
        if self.class_id not in unlocked_classes(data):
            return []
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
        owned_features = set(data.get("class_feature_purchases", {}).get(
            self.class_id, [])) | set(data.get("class_features", []) or [])
        progression = CLASSES[self.class_id].get("progression", {}) or {}
        for tier_key, features in progression.items():
            for feature in features or []:
                feature_id = feature.get("id")
                if not feature_id:
                    continue
                definition = class_feature_definition(self.class_id, feature)
                rows.append((int(feature.get("prerequisite_class_level", tier_key)),
                             definition.get("name", feature_id), "feature",
                             feature_id, definition, feature_id in owned_features))
        subclass_id = data.get("subclass")
        subclass = SUBCLASSES.get(subclass_id, {})
        if subclass.get("class") == self.class_id:
            for tier_key, feature_id, feature in subclass_feature_items(subclass_id):
                definition = {
                    **feature, "classes": [self.class_id],
                    "prerequisite_class_level": int(tier_key),
                    "acquisition": "trainer_purchase", "xp_purchase_cost": 10,
                }
                rows.append((int(tier_key), definition.get("name", feature_id),
                             "subclass feature", feature_id, definition,
                             feature_id in owned_features))
        skill_purchases = data.get("class_skill_purchases", {}).get(self.class_id, [])
        skill_limit = max(0, int(CLASSES[self.class_id].get("skill_choices", 0) or 0))
        known_skills = set(str(skill).casefold() for skill in data.get("skills", []) or [])
        for skill in skill_options(self.class_id):
            skill_id = str(skill).casefold()
            owned = skill_id in known_skills
            if not owned and len(skill_purchases) >= skill_limit:
                continue
            definition = {
                "name": skill.title(), "description": f"Train in {skill.title()}.",
                "classes": [self.class_id], "prerequisite_class_level": 1,
                "acquisition": "trainer_purchase", "xp_purchase_cost": 10,
            }
            rows.append((1, definition["name"], "skill", skill_id,
                         definition, owned))
        expertise_slots = sum(
            int((feature.get("effect", {}) or {}).get("count", 0) or 0)
            for tier, features in progression.items() for feature in features or []
            if feature.get("id") in owned_features
            and (feature.get("effect", {}) or {}).get("kind") == "expertise_choice")
        expertise_skills = {str(value).casefold() for value in
                            data.get("expertise_skills", []) or []}
        if len(expertise_skills) < expertise_slots:
            for skill in sorted(known_skills - expertise_skills):
                definition = {"name": f"Expertise: {skill.title()}",
                              "description": f"Double your proficiency bonus for {skill.title()} checks."}
                rows.append((1, definition["name"], "expertise_choice",
                             skill, definition, False))
        mastery_slots = class_feature_choice_slots(data, "weapon_mastery_choice")
        weapon_masteries = data.get("weapon_masteries", {}) or {}
        if len(weapon_masteries) < mastery_slots:
            for weapon_id, mastery in ROGUE_WEAPON_MASTERY.items():
                if (weapon_id in weapon_masteries
                        or not weapon_mastery_eligible(data, weapon_id)):
                    continue
                definition = {"name": f"{weapon_id.replace('_', ' ').title()} · {mastery.title()}",
                              "description": f"Choose {mastery.title()} mastery for this weapon."}
                rows.append((1, definition["name"], "mastery_choice",
                             weapon_id, definition, False))
        style_slots = class_feature_choice_slots(data, "fighting_style_choice")
        fighting_styles = set(data.get("fighting_styles", []) or [])
        if len(fighting_styles) < style_slots:
            for style_id, definition in FIGHTING_STYLE_OPTIONS.items():
                if style_id not in fighting_styles:
                    rows.append((1, definition["name"], "fighting_style_choice",
                                 style_id, definition, False))
        section_kinds = {
            "features": {"feature", "subclass feature"},
            "spells": {"spell"}, "abilities": {"ability"},
            "skills": {"skill"},
            "choices": {"expertise_choice", "mastery_choice",
                        "fighting_style_choice"},
        }
        if self.section != "ability_scores":
            rows = [row for row in rows
                    if row[2] in section_kinds.get(self.section, set())]
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

    @staticmethod
    def _fit(text, font, width):
        text = str(text)
        while text and font.size(text + "…")[0] > width:
            text = text[:-1]
        return text + ("…" if text else "")

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
        if self.confirmation:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.confirmation = None
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    action = self.confirmation["action"]
                    self.confirmation = None
                    return action
                return None
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._confirmation_rects.get("cancel", pygame.Rect(0, 0, 0, 0)).collidepoint(event.pos):
                    self.confirmation = None
                elif self._confirmation_rects.get("confirm", pygame.Rect(0, 0, 0, 0)).collidepoint(event.pos):
                    action = self.confirmation["action"]
                    self.confirmation = None
                    return action
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
        screen_height = surface.get_height() if surface else 600
        panel = self._panel_rect(screen_width, screen_height)
        level_up_rect = pygame.Rect(panel.right - 190, panel.y + 14, 164, 32)
        if (level_up_rect.collidepoint(x, y) and levels_to_apply(data) > 0
                and self.class_id in unlocked_classes(data)):
            self._ask_confirmation({"type": "level_up", "class_id": self.class_id},
                                   f"Apply level to {self.class_id.title()}?",
                                   "No XP or gold cost")
            return None
        for index, class_id in enumerate(CLASSES):
            rect = self._class_tab_rect(panel, index, len(CLASSES))
            if rect.collidepoint(x, y):
                self.class_id = class_id
                self.scroll = 0
                self.section = self.section_by_class.get(class_id, "features")
                return None
        if self.class_id not in unlocked_classes(data):
            unlock_rect = pygame.Rect(panel.right - 190, panel.y + 96,
                                      168, 30)
            if unlock_rect.collidepoint(x, y):
                cost = class_unlock_cost(data, self.class_id)
                self._ask_confirmation({"type": "unlock_class", "class_id": self.class_id},
                                       f"Unlock {self.class_id.title()}?",
                                       f"Cost: {cost} XP")
                return None
        for section, rect in self._section_rects.items():
            if rect.collidepoint(x, y):
                self.section = section
                self.section_by_class[self.class_id] = section
                self.scroll = 0
                return None
        if self.section == "ability_scores":
            for ability, rect in self._attribute_rects.items():
                if rect.collidepoint(x, y) and attribute_points_available(data) > 0:
                    current = int((data.get("abilities", {}) or {}).get(ability, 10))
                    self._ask_confirmation({"type": "increase_ability", "ability": ability},
                                           f"Increase {ability.title()} to {current + 1}?",
                                           "Cost: 1 ability point")
                    return None
            return None
        visible_count = self._visible_row_count(panel)
        if y >= panel.y + 222:
            visible_rows = self._items(data)[self.scroll:self.scroll + visible_count]
            for index, row in enumerate(visible_rows):
                row_rect = pygame.Rect(panel.x + 12,
                                       panel.y + 224 + index * 38,
                                       panel.width - 24, 34)
                buy_rect = pygame.Rect(panel.right - 120, row_rect.y + 2,
                                       82, 30)
                if buy_rect.collidepoint(x, y) and not row[5]:
                    _tier, name, kind, item_id, definition, _owned = row
                    if kind == "expertise_choice":
                        return {"type": "choose_expertise", "class_id": self.class_id,
                                "skill": item_id}
                    if kind == "mastery_choice":
                        return {"type": "choose_weapon_mastery",
                                "class_id": self.class_id, "weapon_id": item_id}
                    if kind == "fighting_style_choice":
                        return {"type": "choose_fighting_style",
                                "class_id": self.class_id, "style_id": item_id}
                    cost = adjusted_purchase_cost(data, self.class_id, definition)
                    self._ask_confirmation(
                        {"type": "trainer_purchase", "class_id": self.class_id,
                         "kind": kind, "item_id": item_id},
                        f"Purchase {name}?", f"Cost: {cost} XP")
                    return None
        return None

    def draw(self, screen, data, font):
        if not self.visible:
            return
        overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        screen.blit(overlay, (0, 0))
        panel = self._panel_rect(*screen.get_size())
        pygame.draw.rect(screen, (24, 28, 32), panel, border_radius=8)
        pygame.draw.rect(screen, (190, 180, 140), panel, 2, border_radius=8)
        title = pygame.font.Font(None, 30)
        screen.blit(title.render("Trainer", True, (250, 235, 190)),
                    (panel.x + 26, panel.y + 14))
        selected_title = self.class_id.title() if self.class_id else "No class"
        selected_tier = class_unlocked_level(data, self.class_id) if self.class_id else 0
        status = (f"Applied level {data.get('level', 1)}"
                  f"   Ready {levels_to_apply(data)}   XP {unspent_xp(data)}")
        screen.blit(font.render(status, True, (215, 225, 220)),
                    (panel.x + 180, panel.y + 20))
        hint_font = pygame.font.Font(None, 17)
        pending = levels_to_apply(data)
        level_up_rect = pygame.Rect(panel.right - 190, panel.y + 14, 164, 32)
        can_level = (pending > 0 and self.class_id in unlocked_classes(data))
        pygame.draw.rect(screen, (76, 120, 78) if can_level else (67, 70, 75),
                         level_up_rect, border_radius=4)
        level_label = f"Level Up · {pending}" if pending else "No Level Ready"
        screen.blit(hint_font.render(level_label, True, (250, 250, 245)),
                    (level_up_rect.x + 8, level_up_rect.y + 9))
        hover_title, hover_detail = "", ""
        mouse_pos = pygame.mouse.get_pos()
        acquired_classes = set(unlocked_classes(data))
        for index, class_id in enumerate(CLASSES):
            rect = self._class_tab_rect(panel, index, len(CLASSES))
            acquired = class_id in acquired_classes
            base_color = (82, 110, 88) if class_id == self.class_id else (55, 62, 68)
            pygame.draw.rect(screen, base_color if acquired else (43, 45, 48),
                             rect, border_radius=4)
            label = pygame.font.Font(None, 18).render(class_id.title()[:10], True,
                                                       (245, 245, 240))
            screen.blit(label, label.get_rect(center=rect.center))
            if rect.collidepoint(mouse_pos):
                hover_title = class_id.title()
                hover_detail = CLASSES[class_id].get("summary", "")
                if not acquired:
                    hover_detail += f" Unlock cost: {class_unlock_cost(data, class_id)} XP."
        owned_spells = set(data.get("class_spell_purchases", {}).get(self.class_id, []))
        owned_abilities = set(data.get("class_ability_purchases", {}).get(self.class_id, []))
        unlocked = self.class_id in unlocked_classes(data)
        if not unlocked:
            fee = class_unlock_cost(data, self.class_id)
            unlock_rect = pygame.Rect(panel.right - 190, panel.y + 92,
                                      168, 30)
            can_unlock = fee <= unspent_xp(data)
            pygame.draw.rect(screen, (76, 120, 78) if can_unlock else (72, 72, 72),
                             unlock_rect, border_radius=4)
            unlock_label = f"Unlock · {fee} XP"
            screen.blit(hint_font.render(unlock_label, True, (250, 250, 245)),
                        (unlock_rect.x + 9, unlock_rect.y + 8))
            screen.blit(hint_font.render(
                "Unlock this class before buying its options.",
                True, (205, 215, 200)), (panel.x + 26, panel.y + 101))
        else:
            screen.blit(hint_font.render(
                self._fit("Unlocked. Spells, cantrips, skills, features, and abilities cost XP.",
                          hint_font, panel.width - 250),
                True, (205, 215, 200)), (panel.x + 26, panel.y + 101))
        current_features = set(data.get("class_features", []) or [])
        granted = [feature.get("name", feature.get("id", "Feature"))
                   for features in (CLASSES.get(self.class_id, {}).get(
                       "progression", {}) or {}).values()
                   for feature in (features or [])
                   if feature.get("id") in current_features]
        subclass = SUBCLASSES.get(data.get("subclass"), {})
        if subclass.get("class") == self.class_id:
            granted.extend(
                feature.get("name", f"Level {tier}")
                for tier, feature_id, feature in subclass_feature_items(data.get("subclass"))
                if feature_id in current_features)
        if granted:
            status_text = self._fit("Purchased features: " + ", ".join(granted), hint_font,
                                    panel.width - 250)
            screen.blit(hint_font.render(status_text, True, (255, 220, 145)),
                        (panel.x + 26, panel.y + 126))
        section_names = (("features", "Features"), ("spells", "Spells"),
                         ("abilities", "Abilities"), ("skills", "Skills"),
                         ("choices", "Choices"),
                         ("ability_scores", "Ability Scores"))
        self._section_rects = {}
        tab_x = panel.x + 24
        for section, label in section_names:
            width = 132 if section == "ability_scores" else 96
            rect = pygame.Rect(tab_x, panel.y + 158, width, 30)
            self._section_rects[section] = rect
            pygame.draw.rect(screen,
                             (91, 116, 91) if section == self.section else (53, 60, 65),
                             rect, border_radius=4)
            screen.blit(hint_font.render(label, True, (245, 245, 240)),
                        hint_font.render(label, True, (245, 245, 240)).get_rect(center=rect.center))
            tab_x += width + 8
        if self.notice:
            notice_text = self._fit(self.notice, font, panel.width - 52)
            screen.blit(font.render(notice_text, True, (255, 215, 150)),
                        (panel.x + 26, panel.y + 192))
        if self.section == "ability_scores":
            available = attribute_points_available(data)
            point_label = self._fit(f"Unspent ability points: {available}",
                                    font, panel.width - 52)
            screen.blit(font.render(point_label, True, (255, 220, 145)),
                        (panel.x + 26, panel.y + 224))
            ability_names = (("strength", "Strength"), ("dexterity", "Dexterity"),
                             ("constitution", "Constitution"), ("intellect", "Intellect"),
                             ("wisdom", "Wisdom"), ("charisma", "Charisma"))
            abilities = data.get("abilities", {}) or {}
            self._attribute_rects = {}
            compact = panel.height < 590
            columns = 3 if compact else 2
            card_gap = 10 if compact else 40
            card_width = ((panel.width - 52 - (columns - 1) * card_gap) // columns)
            for index, (ability, label) in enumerate(ability_names):
                col, row = index % columns, index // columns
                card_height = 50 if compact else 58
                row_gap = 12 if compact else 18
                rect = pygame.Rect(panel.x + 26 + col * (card_width + card_gap),
                                   panel.y + (252 if compact else 263)
                                   + row * (card_height + row_gap),
                                   card_width, card_height)
                self._attribute_rects[ability] = rect
                can_spend = available > 0
                pygame.draw.rect(screen, (63, 94, 68) if can_spend else (48, 52, 56),
                                 rect, border_radius=5)
                score = int(abilities.get(ability, 10) or 10)
                card_text = self._fit(f"{label}  {score}", font,
                                      rect.width - 78)
                screen.blit(font.render(card_text, True, (245, 245, 240)),
                            (rect.x + 16, rect.y + 18))
                screen.blit(hint_font.render("+1", True, (255, 220, 145)),
                            (rect.right - 50, rect.y + 21))
            footer = "Spend one available point per click. Scores above 30 do not improve calculations."
            footer = self._fit(footer, hint_font, panel.width - 52)
            screen.blit(hint_font.render(footer, True, (205, 210, 210)),
                        (panel.x + 26, panel.bottom - 26))
            self._draw_confirmation(screen, font)
            self._draw_tooltip(screen, hover_title, hover_detail, mouse_pos)
            return
        rows = self._items(data)
        visible_count = self._visible_row_count(panel)
        self.scroll = min(self.scroll, max(0, len(rows) - visible_count))
        frontier = class_unlocked_level(data, self.class_id)
        ceiling = qualified_level(data)
        if not rows:
            empty_messages = {
                "features": "No class features are listed here yet.",
                "spells": "No trainer spells are available for this class.",
                "abilities": "No trainer abilities are available for this class.",
                "skills": "No skill selections remain for this class.",
                "choices": "Purchase a feature that grants a choice to unlock options here.",
            }
            message = ("Unlock this class to browse its options."
                       if not unlocked else
                       empty_messages.get(self.section, "No options are available."))
            message = self._fit(message, font, panel.width - 56)
            screen.blit(font.render(message, True, (210, 215, 215)),
                        (panel.x + 28, panel.y + 224))
        for index, row in enumerate(rows[self.scroll:self.scroll + visible_count]):
            tier, name, kind, item_id, definition, is_owned = row
            y = panel.y + 224 + index * 38
            row_rect = pygame.Rect(panel.x + 12, y, panel.width - 24, 34)
            can_buy = (kind in {"expertise_choice", "mastery_choice",
                                "fighting_style_choice"} and not is_owned) or (
                       not is_owned and tier <= frontier and tier <= ceiling
                       and adjusted_purchase_cost(data, self.class_id, definition) is not None
                       and unspent_xp(data) >= adjusted_purchase_cost(
                           data, self.class_id, definition))
            color = (51, 67, 58) if can_buy else (43, 47, 51)
            pygame.draw.rect(screen, color, row_rect, border_radius=4)
            suffix = "owned" if is_owned else f"level {tier} {kind}"
            button = pygame.Rect(panel.right - 120, y + 2, 82, 30)
            label_text = self._fit(f"{name}  ·  {suffix}", font,
                                   button.x - (panel.x + 22) - 12)
            screen.blit(font.render(label_text, True, (240, 240, 230)),
                        (panel.x + 22, y + 8))
            cost = adjusted_purchase_cost(data, self.class_id, definition)
            pygame.draw.rect(screen, (76, 120, 78) if can_buy else (72, 72, 72),
                             button, border_radius=4)
            label = ("Owned" if is_owned else "Choose" if kind in {"expertise_choice", "mastery_choice", "fighting_style_choice"}
                     else f"{cost} XP" if cost is not None else "No cost")
            screen.blit(pygame.font.Font(None, 16).render(label, True, (250, 250, 245)),
                        (button.x + 5, button.y + 9))
            if row_rect.collidepoint(mouse_pos):
                hover_title = name
                details = [definition.get("description", "No description available.")]
                if kind == "spell":
                    spell_level = int(definition.get(
                        "level", definition.get("tier", 0)) or 0)
                    details.append("Cantrip; no spell slot required." if spell_level == 0
                                   else f"Uses one level {spell_level} or higher spell slot.")
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
                  f"Level Up assigns a pending level to {selected_title}. Esc closes.")
        footer_font = pygame.font.Font(None, 17)
        footer = self._fit(footer, footer_font, panel.width - 52)
        screen.blit(footer_font.render(footer, True, (205, 210, 210)),
                    (panel.x + 26, panel.bottom - 26))
        self._draw_confirmation(screen, font)
        self._draw_tooltip(screen, hover_title, hover_detail, mouse_pos)
