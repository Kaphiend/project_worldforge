"""Pygame drawing and input for the staged character creator.

To add a creation choice, first add validation/state to ``creation_flow.py``
and its JSON table, then add the matching button and stage rendering here.
Keep screen coordinates inside the 800-by-600 window.
"""
import pygame
from classes import RACES, CLASSES, SUBCLASSES, skill_options
from creation_flow import CharacterCreationFlow
from storage import delete_actor, list_actors, unlock_actor


def run_creation(available_avatars=None):
    pygame.init()
    screen = pygame.display.set_mode((800, 600))
    font = pygame.font.SysFont(None, 36)
    clock = pygame.time.Clock()

    flow = CharacterCreationFlow()
    name_text = ''
    saves = list_actors()

    confirm_rect = pygame.Rect(300, 500, 200, 50)
    name_box = pygame.Rect(250, 250, 300, 50)
    new_char_rect = pygame.Rect(250, 500, 300, 50)
    random_char_rect = pygame.Rect(250, 430, 300, 50)
    start_rect = pygame.Rect(300, 500, 200, 50)
    avatar_options = [
        (pygame.Rect(150, 200, 220, 180), 'asset_pack/Orc.png', 'Orc'),
        (pygame.Rect(430, 200, 220, 180), 'asset_pack/Soldier.png', 'Soldier'),
    ]
    avatar_buttons = [option for option in avatar_options
                      if available_avatars is None or option[1] in available_avatars]


    def menu_buttons():
        buttons = []
        for i, (save_id, name) in enumerate(saves):
            load_rect = pygame.Rect(250, 100 + i * 60, 220, 50)
            delete_rect = pygame.Rect(480, 100 + i * 60, 70, 50)
            buttons.append((load_rect, delete_rect, save_id, name))
        return buttons

    def make_buttons(names):
        buttons = []
        for i, name in enumerate(names):
            column = i % 2
            row = i // 2
            rect = pygame.Rect(170 + column * 240, 100 + row * 62, 220, 50)
            buttons.append((rect, name))
        return buttons

    def make_parent_buttons():
        names = [name for name, data in RACES.items()
                 if not data.get('half_breed') and data.get('selectable', True)]
        return [(pygame.Rect(18 + (index % 3) * 258,
                             145 + (index // 3) * 58, 242, 48), name)
                for index, name in enumerate(names)]

    def fit_label(text, use_font, max_width):
        value = str(text)
        if use_font.size(value)[0] <= max_width:
            return value
        while value and use_font.size(value + '…')[0] > max_width:
            value = value[:-1]
        return value + '…'

    def fit_entry(text, use_font, max_width):
        value = str(text)
        while value and use_font.size(value)[0] > max_width:
            value = value[1:]
        return ('…' if value != str(text) else '') + value

    def wrap_lines(text, use_font, max_width):
        lines, current = [], ''
        for word in str(text).split():
            candidate = f"{current} {word}".strip()
            if current and use_font.size(candidate)[0] > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines

    def make_skill_buttons(skills):
        # ADJUST HERE if this layout ever gets tweaked. With the default
        # 2-column grid (see make_buttons above), row height is 62px
        # starting at y=100:
        #     bottom_y = 100 + ceil(len(skills) / 2) * 62
        # A short class list (<=7 skills, 4 rows) bottoms out at 348px --
        # fine on the 600px-tall screen with the Confirm button at y=500.
        # bard's expanded ["any"] list (18 skills, via skill_options()) is
        # 9 rows in 2 columns: bottom_y = 100 + 9*62 = 658, which runs off
        # the window and under the Confirm button. Switch to 3 columns once
        # the list is longer than 2 columns can hold without collision:
        #     10 skills is the largest count 2 columns keeps under y=490
        #     (100 + 5*62 = 410 < 490 for 10 skills / 2 cols = 5 rows)
        columns = 3 if len(skills) > 10 else 2
        button_width = 240 if columns == 3 else 220
        x_start = 20 if columns == 3 else 170
        x_gap = 260 if columns == 3 else 240
        # 3-column check: rightmost edge = x_start + 2*x_gap + button_width
        #                = 20 + 520 + 240 = 780, inside the 800px-wide window.
        # 18 skills / 3 cols = 6 rows: bottom_y = 100 + 6*62 = 472, clear of
        # the Confirm button at y=500. Re-check both bounds if skill_choices
        # or ALL_SKILLS grows.
        buttons = []
        for i, skill in enumerate(skills):
            column = i % columns
            row = i // columns
            rect = pygame.Rect(x_start + column * x_gap, 100 + row * 62,
                               button_width, 50)
            buttons.append((rect, skill))
        return buttons

    def roll_buttons():
        buttons = []
        for i, roll in enumerate(flow.actor.unspent):
            rect = pygame.Rect(300, 150 + i * 60, 200, 50)
            buttons.append((rect, i, roll))
        return buttons

    race_buttons = make_buttons(
        name for name, data in RACES.items() if data.get('selectable', True)
    )
    class_buttons = make_buttons(CLASSES.keys())

    running = True
    while running:
        if flow.stage == 'menu':
            saves = list_actors()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                if flow.actor:
                    unlock_actor(flow.actor.id)
                pygame.quit()
                return None

            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                if flow.actor:
                    unlock_actor(flow.actor.id)
                pygame.quit()
                return None

            if event.type == pygame.KEYDOWN and flow.stage in ('name', 'quick_name'):
                if event.key == pygame.K_BACKSPACE:
                    name_text = name_text[:-1]
                elif event.key == pygame.K_RETURN:
                    if name_text.strip():
                        if flow.stage == 'name':
                            flow.begin_character(name_text)
                        else:
                            flow.create_random_fully_geared(
                                avatars=[option[1] for option in avatar_buttons],
                                class_name=flow.quick_start_class, name=name_text)
                elif event.unicode.isprintable() and len(name_text) < 20:
                    name_text += event.unicode

            if event.type == pygame.MOUSEBUTTONDOWN:
                if flow.stage == 'menu':
                    for load_rect, delete_rect, save_id, name in menu_buttons():
                        if load_rect.collidepoint(event.pos):
                            flow.load_existing(save_id)
                            if (available_avatars is not None
                                    and flow.actor.avatar not in available_avatars):
                                flow.stage = 'avatar'
                        elif delete_rect.collidepoint(event.pos):
                            delete_actor(save_id)
                            saves = list_actors()
                    if new_char_rect.collidepoint(event.pos):
                        flow.stage = 'name'
                    elif random_char_rect.collidepoint(event.pos):
                        flow.stage = 'quick_class'

                elif flow.stage == 'quick_class':
                    for rect, cls in class_buttons:
                        if rect.collidepoint(event.pos):
                            flow.quick_start_class = cls
                            name_text = ''
                            flow.stage = 'quick_name'

                elif flow.stage == 'name':
                    if name_text.strip() and confirm_rect.collidepoint(event.pos):
                        flow.begin_character(name_text)

                elif flow.stage == 'quick_name':
                    if name_text.strip() and confirm_rect.collidepoint(event.pos):
                        flow.create_random_fully_geared(
                            avatars=[option[1] for option in avatar_buttons],
                            class_name=flow.quick_start_class, name=name_text)

                elif flow.stage == 'race':
                    for rect, race in race_buttons:
                        if rect.collidepoint(event.pos):
                            flow.select_race(race)
                    if flow.actor.race and confirm_rect.collidepoint(event.pos):
                        flow.confirm_race()

                elif flow.stage == 'subrace':
                    options = RACES[flow.actor.race].get('subraces', {})
                    for rect, subrace in make_buttons(options.keys()):
                        if rect.collidepoint(event.pos):
                            flow.select_subrace(subrace)
                    if flow.actor.subrace and confirm_rect.collidepoint(event.pos):
                        flow.confirm_subrace()

                elif flow.stage == 'parents':
                    for i in range(2):
                        rect = pygame.Rect(115 + i * 310, 78, 270, 42)
                        if rect.collidepoint(event.pos):
                            flow.focus_parent(i)
                    for rect, race in make_parent_buttons():
                        if rect.collidepoint(event.pos):
                            flow.select_focused_parent(race)
                    if len(flow.actor.parent_races) == 2 and all(flow.actor.parent_races) and confirm_rect.collidepoint(event.pos):
                        flow.confirm_parents()

                elif flow.stage == 'class':
                    for rect, cls in class_buttons:
                        if rect.collidepoint(event.pos):
                            flow.select_class(cls)
                    if flow.actor.char_class and confirm_rect.collidepoint(event.pos):
                        flow.confirm_class()

                elif flow.stage == 'subclass':
                    subclass_ids = CLASSES[flow.actor.char_class].get('subclasses', [])
                    for index, subclass_id in enumerate(subclass_ids):
                        rect = pygame.Rect(100, 100 + index * 115, 600, 95)
                        if rect.collidepoint(event.pos):
                            flow.select_subclass(subclass_id)
                    if flow.actor.subclass and confirm_rect.collidepoint(event.pos):
                        flow.confirm_subclass()

                elif flow.stage == 'skills':
                    for rect, skill in make_skill_buttons(skill_options(flow.actor.char_class)):
                        if rect.collidepoint(event.pos):
                            flow.select_skill(skill)
                    if (len(flow.actor.skills) == CLASSES[flow.actor.char_class].get('skill_choices', 0)
                            and confirm_rect.collidepoint(event.pos)):
                        flow.confirm_skills()

                elif flow.stage == 'abilities':
                    for rect, roll_index, roll in roll_buttons():
                        if rect.collidepoint(event.pos):
                            flow.assign_roll(roll_index)
                            break

                elif flow.stage == 'done':
                    if start_rect.collidepoint(event.pos):
                        running = False
                elif flow.stage == 'avatar':
                    for rect, avatar, _label in avatar_buttons:
                        if rect.collidepoint(event.pos):
                            flow.choose_avatar(avatar)

        screen.fill((20, 20, 20))

        if flow.stage == 'menu':
            for load_rect, delete_rect, save_id, name in menu_buttons():
                pygame.draw.rect(screen, (60, 60, 60), load_rect)
                text = font.render(fit_label(name.title(), font,
                                            load_rect.width - 20),
                                   True, (255, 255, 255))
                screen.blit(text, (load_rect.x + 10, load_rect.y + 10))
                pygame.draw.rect(screen, (140, 60, 60), delete_rect)
                del_text = font.render("X", True, (255, 255, 255))
                screen.blit(del_text, (delete_rect.x + 25, delete_rect.y + 10))
            pygame.draw.rect(screen, (100, 100, 180), new_char_rect)
            new_text = font.render(fit_label("New Character", font,
                                             new_char_rect.width - 20),
                                   True, (255, 255, 255))
            screen.blit(new_text, (new_char_rect.x + 40, new_char_rect.y + 10))
            pygame.draw.rect(screen, (90, 120, 90), random_char_rect)
            random_text = font.render(fit_label("Quick Start: Pick Class", font,
                                                random_char_rect.width - 20),
                                      True, (255, 255, 255))
            screen.blit(random_text, (random_char_rect.x + 35, random_char_rect.y + 10))

        elif flow.stage == 'quick_class':
            screen.blit(font.render("Choose a class for your demo character", True,
                                    (255, 255, 255)), (190, 35))
            for rect, cls in class_buttons:
                pygame.draw.rect(screen, (60, 60, 60), rect)
                screen.blit(font.render(cls.title(), True, (255, 255, 255)),
                            (rect.x + 10, rect.y + 10))

        elif flow.stage == 'name':
            prompt = font.render("enter a name:", True, (255, 255, 255))
            screen.blit(prompt, (250, 190))
            pygame.draw.rect(screen, (60, 60, 60), name_box)
            text = font.render(fit_entry(name_text, font, name_box.width - 20),
                               True, (255, 255, 255))
            screen.blit(text, (name_box.x + 10, name_box.y + 10))
            if name_text.strip():
                pygame.draw.rect(screen, (100, 100, 180), confirm_rect)
                confirm_text = font.render("Confirm", True, (255, 255, 255))
                screen.blit(confirm_text, (confirm_rect.x + 40, confirm_rect.y + 10))

        elif flow.stage == 'quick_name':
            prompt = font.render(
                f"Name your quick-start {flow.quick_start_class.title()}",
                True, (255, 255, 255))
            screen.blit(prompt, (190, 190))
            pygame.draw.rect(screen, (60, 60, 60), name_box)
            screen.blit(font.render(fit_entry(name_text, font,
                                              name_box.width - 20),
                                    True, (255, 255, 255)),
                        (name_box.x + 10, name_box.y + 10))
            if name_text.strip():
                pygame.draw.rect(screen, (100, 100, 180), confirm_rect)
                screen.blit(font.render("Create Character", True, (255, 255, 255)),
                            (confirm_rect.x + 12, confirm_rect.y + 10))

        elif flow.stage == 'race':
            for rect, race in race_buttons:
                color = (90, 140, 90) if race == flow.actor.race else (60, 60, 60)
                pygame.draw.rect(screen, color, rect)
                text = font.render(fit_label(race.title(), font,
                                             rect.width - 20),
                                   True, (255, 255, 255))
                screen.blit(text, (rect.x + 10, rect.y + 10))
            if flow.actor.race:
                pygame.draw.rect(screen, (100, 100, 180), confirm_rect)
                text = font.render("Confirm", True, (255, 255, 255))
                screen.blit(text, (confirm_rect.x + 40, confirm_rect.y + 10))

        elif flow.stage == 'subrace':
            prompt = font.render(fit_label(
                f"Choose a {flow.actor.race.title()} subrace:", font, 760),
                True, (255, 255, 255))
            screen.blit(prompt, (220, 35))
            for rect, subrace in make_buttons(RACES[flow.actor.race].get('subraces', {}).keys()):
                color = (90, 140, 90) if subrace == flow.actor.subrace else (60, 60, 60)
                pygame.draw.rect(screen, color, rect)
                screen.blit(font.render(fit_label(subrace.title(), font,
                                                 rect.width - 20),
                                        True, (255, 255, 255)),
                            (rect.x + 10, rect.y + 10))
            if flow.actor.subrace:
                pygame.draw.rect(screen, (100, 100, 180), confirm_rect)
                screen.blit(font.render("Confirm", True, (255, 255, 255)), (confirm_rect.x + 40, confirm_rect.y + 10))

        elif flow.stage == 'parents':
            screen.blit(font.render("Choose two parent races", True,
                                    (255, 255, 255)), (270, 14))
            screen.blit(pygame.font.SysFont(None, 24).render(
                "Select a parent above, then choose a race below.", True,
                (210, 215, 225)), (235, 47))
            for i in range(2):
                rect = pygame.Rect(115 + i * 310, 78, 270, 42)
                active = i == flow.parent_selection
                pygame.draw.rect(screen, (90, 140, 90) if active else (60, 60, 60), rect)
                parent = flow.actor.parent_races[i] if len(flow.actor.parent_races) > i else ''
                label = f"Parent {i + 1}: {parent.title() if parent else 'choose'}"
                screen.blit(font.render(fit_label(label, font, rect.width - 16),
                                        True, (255, 255, 255)),
                            (rect.x + 8, rect.y + 8))
            for rect, race in make_parent_buttons():
                selected = len(flow.actor.parent_races) > flow.parent_selection and flow.actor.parent_races[flow.parent_selection] == race
                pygame.draw.rect(screen, (90, 140, 90) if selected else (60, 60, 60), rect)
                screen.blit(font.render(fit_label(race.title(), font,
                                                  rect.width - 20),
                                        True, (255, 255, 255)),
                            (rect.x + 10, rect.y + 10))
            if len(flow.actor.parent_races) == 2 and all(flow.actor.parent_races):
                pygame.draw.rect(screen, (100, 100, 180), confirm_rect)
                screen.blit(font.render("Confirm", True, (255, 255, 255)), (confirm_rect.x + 40, confirm_rect.y + 10))

        elif flow.stage == 'class':
            for rect, cls in class_buttons:
                color = (90, 140, 90) if cls == flow.actor.char_class else (60, 60, 60)
                pygame.draw.rect(screen, color, rect)
                text = font.render(fit_label(cls.title(), font,
                                             rect.width - 20),
                                   True, (255, 255, 255))
                screen.blit(text, (rect.x + 10, rect.y + 10))
            if flow.actor.char_class:
                pygame.draw.rect(screen, (100, 100, 180), confirm_rect)
                text = font.render("Confirm", True, (255, 255, 255))
                screen.blit(text, (confirm_rect.x + 40, confirm_rect.y + 10))

        elif flow.stage == 'subclass':
            prompt = font.render(f"choose a {flow.actor.char_class.title()} path:",
                                 True, (255, 255, 255))
            screen.blit(prompt, (250, 35))
            for index, subclass_id in enumerate(
                    CLASSES[flow.actor.char_class].get('subclasses', [])):
                subclass = SUBCLASSES[subclass_id]
                rect = pygame.Rect(100, 100 + index * 115, 600, 95)
                color = (90, 140, 90) if subclass_id == flow.actor.subclass else (60, 60, 60)
                pygame.draw.rect(screen, color, rect)
                screen.blit(font.render(fit_label(subclass['name'], font,
                                                  rect.width - 28),
                                        True, (255, 255, 255)),
                            (rect.x + 14, rect.y + 10))
                description_font = pygame.font.SysFont(None, 21)
                for line_index, line in enumerate(wrap_lines(
                        subclass['description'], description_font,
                        rect.width - 28)[:2]):
                    screen.blit(description_font.render(line, True,
                                                       (220, 220, 220)),
                                (rect.x + 14, rect.y + 46 + line_index * 20))
            if flow.actor.subclass:
                pygame.draw.rect(screen, (100, 100, 180), confirm_rect)
                screen.blit(font.render("Confirm", True, (255, 255, 255)),
                            (confirm_rect.x + 40, confirm_rect.y + 10))

        elif flow.stage == 'skills':
            needed = CLASSES[flow.actor.char_class].get('skill_choices', 0)
            screen.blit(font.render(f"Choose {needed} trained skills ({len(flow.actor.skills)}/{needed})",
                                    True, (255, 255, 255)), (180, 45))
            for rect, skill in make_skill_buttons(skill_options(flow.actor.char_class)):
                selected = skill in flow.actor.skills
                pygame.draw.rect(screen, (90, 140, 90) if selected else (60, 60, 60), rect)
                screen.blit(font.render(fit_label(skill.title(), font,
                                                  rect.width - 20),
                                        True, (255, 255, 255)),
                            (rect.x + 10, rect.y + 10))
            if len(flow.actor.skills) == needed:
                pygame.draw.rect(screen, (100, 100, 180), confirm_rect)
                screen.blit(font.render("Confirm", True, (255, 255, 255)),
                            (confirm_rect.x + 40, confirm_rect.y + 10))

        elif flow.stage == 'abilities':
            if flow.current_ability_index < len(flow.ability_order):
                ability = flow.ability_order[flow.current_ability_index]
                prompt = font.render(f"pick a roll for {ability}", True, (255, 255, 255))
                screen.blit(prompt, (250, 80))
                for rect, roll_index, roll in roll_buttons():
                    pygame.draw.rect(screen, (60, 60, 60), rect)
                    text = font.render(str(roll), True, (255, 255, 255))
                    screen.blit(text, (rect.x + 85, rect.y + 10))

        elif flow.stage == 'done':
            actor = flow.actor
            ancestry = actor.race.title()
            if actor.subrace:
                ancestry += f" ({actor.subrace.title()})"
            if actor.parent_races:
                ancestry += " (" + " / ".join(race.title() for race in actor.parent_races) + ")"
            title_font = pygame.font.SysFont(None, 32)
            detail_font = pygame.font.SysFont(None, 25)
            title = f"{actor.name} — saved"
            screen.blit(title_font.render(title, True, (255, 255, 255)), (40, 24))
            identity = f"{ancestry}  |  {actor.char_class.title()}"
            identity_lines = wrap_lines(identity, detail_font, 710)
            identity_line_height = detail_font.get_linesize() + 2
            for line_index, line in enumerate(identity_lines):
                screen.blit(detail_font.render(line, True, (220, 225, 235)),
                            (40, 62 + line_index * identity_line_height))
            y = max(118, 62 + len(identity_lines) * identity_line_height + 5)
            if actor.subclass:
                subclass_name = SUBCLASSES.get(actor.subclass, {}).get('name', actor.subclass)
                screen.blit(detail_font.render(subclass_name, True, (210, 210, 210)),
                            (40, y))
                y += 34
            for index, (ability, score) in enumerate(actor.abilities.items()):
                col, row = index % 3, index // 3
                line = detail_font.render(f"{ability.title()}: {score}", True,
                                          (255, 255, 255))
                screen.blit(line, (100 + col * 220, y + row * 34))
            y += 82
            hp_line = detail_font.render(
                f"HP: {actor.current_hp}/{actor.max_hp}    Gold: {actor.gold}",
                True, (255, 255, 255))
            screen.blit(hp_line, (100, y))
            y += 40
            equipped_names = []
            for slot, item in actor.equipment.items():
                if item:
                    equipped_names.append(f"{slot.replace('_', ' ')}: {item['name']}")
            gear_lines = wrap_lines("Equipped: " + (", ".join(equipped_names) or "nothing"),
                                    detail_font, 710)
            gear_line_height = detail_font.get_linesize() + 2
            for line_index, line in enumerate(gear_lines[:3]):
                screen.blit(detail_font.render(line, True, (210, 210, 210)),
                            (40, y + line_index * gear_line_height))
            pygame.draw.rect(screen, (100, 180, 100), start_rect)
            start_text = font.render("Start", True, (255, 255, 255))
            screen.blit(start_text, (start_rect.x + 65, start_rect.y + 10))

        elif flow.stage == 'avatar':
            screen.blit(font.render('Choose this character’s avatar', True,
                                    (255, 255, 255)), (210, 100))
            for rect, _avatar, label in avatar_buttons:
                pygame.draw.rect(screen, (65, 75, 95), rect)
                pygame.draw.rect(screen, (180, 190, 210), rect, 2)
                screen.blit(font.render(label, True, (255, 255, 255)),
                            (rect.x + 65, rect.y + 135))

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()
    return flow.actor
