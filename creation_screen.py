import pygame
from classes import RACES, CLASSES
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

            if event.type == pygame.KEYDOWN and flow.stage == 'name':
                if event.key == pygame.K_BACKSPACE:
                    name_text = name_text[:-1]
                elif event.key == pygame.K_RETURN:
                    if name_text.strip():
                        flow.begin_character(name_text)
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

                elif flow.stage == 'name':
                    if name_text.strip() and confirm_rect.collidepoint(event.pos):
                        flow.begin_character(name_text)

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
                        rect = pygame.Rect(140 + i * 260, 70, 240, 45)
                        if rect.collidepoint(event.pos):
                            flow.focus_parent(i)
                    for rect, race in make_buttons(
                        name for name, data in RACES.items()
                        if not data.get('half_breed') and data.get('selectable', True)
                    ):
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
                text = font.render(name.title(), True, (255, 255, 255))
                screen.blit(text, (load_rect.x + 10, load_rect.y + 10))
                pygame.draw.rect(screen, (140, 60, 60), delete_rect)
                del_text = font.render("X", True, (255, 255, 255))
                screen.blit(del_text, (delete_rect.x + 25, delete_rect.y + 10))
            pygame.draw.rect(screen, (100, 100, 180), new_char_rect)
            new_text = font.render("New Character", True, (255, 255, 255))
            screen.blit(new_text, (new_char_rect.x + 40, new_char_rect.y + 10))

        elif flow.stage == 'name':
            prompt = font.render("enter a name:", True, (255, 255, 255))
            screen.blit(prompt, (250, 190))
            pygame.draw.rect(screen, (60, 60, 60), name_box)
            text = font.render(name_text, True, (255, 255, 255))
            screen.blit(text, (name_box.x + 10, name_box.y + 10))
            if name_text.strip():
                pygame.draw.rect(screen, (100, 100, 180), confirm_rect)
                confirm_text = font.render("Confirm", True, (255, 255, 255))
                screen.blit(confirm_text, (confirm_rect.x + 40, confirm_rect.y + 10))

        elif flow.stage == 'race':
            for rect, race in race_buttons:
                color = (90, 140, 90) if race == flow.actor.race else (60, 60, 60)
                pygame.draw.rect(screen, color, rect)
                text = font.render(race.title(), True, (255, 255, 255))
                screen.blit(text, (rect.x + 10, rect.y + 10))
            if flow.actor.race:
                pygame.draw.rect(screen, (100, 100, 180), confirm_rect)
                text = font.render("Confirm", True, (255, 255, 255))
                screen.blit(text, (confirm_rect.x + 40, confirm_rect.y + 10))

        elif flow.stage == 'subrace':
            prompt = font.render(f"choose a {flow.actor.race.title()} subrace:", True, (255, 255, 255))
            screen.blit(prompt, (220, 35))
            for rect, subrace in make_buttons(RACES[flow.actor.race].get('subraces', {}).keys()):
                color = (90, 140, 90) if subrace == flow.actor.subrace else (60, 60, 60)
                pygame.draw.rect(screen, color, rect)
                screen.blit(font.render(subrace.title(), True, (255, 255, 255)), (rect.x + 10, rect.y + 10))
            if flow.actor.subrace:
                pygame.draw.rect(screen, (100, 100, 180), confirm_rect)
                screen.blit(font.render("Confirm", True, (255, 255, 255)), (confirm_rect.x + 40, confirm_rect.y + 10))

        elif flow.stage == 'parents':
            screen.blit(font.render("choose two parent races:", True, (255, 255, 255)), (250, 20))
            for i in range(2):
                rect = pygame.Rect(140 + i * 260, 70, 240, 45)
                active = i == flow.parent_selection
                pygame.draw.rect(screen, (90, 140, 90) if active else (60, 60, 60), rect)
                parent = flow.actor.parent_races[i] if len(flow.actor.parent_races) > i else ''
                label = f"Parent {i + 1}: {parent.title() if parent else 'choose'}"
                screen.blit(font.render(label, True, (255, 255, 255)), (rect.x + 8, rect.y + 8))
            for rect, race in make_buttons(
                name for name, data in RACES.items()
                if not data.get('half_breed') and data.get('selectable', True)
            ):
                selected = len(flow.actor.parent_races) > flow.parent_selection and flow.actor.parent_races[flow.parent_selection] == race
                pygame.draw.rect(screen, (90, 140, 90) if selected else (60, 60, 60), rect)
                screen.blit(font.render(race.title(), True, (255, 255, 255)), (rect.x + 10, rect.y + 10))
            if len(flow.actor.parent_races) == 2 and all(flow.actor.parent_races):
                pygame.draw.rect(screen, (100, 100, 180), confirm_rect)
                screen.blit(font.render("Confirm", True, (255, 255, 255)), (confirm_rect.x + 40, confirm_rect.y + 10))

        elif flow.stage == 'class':
            for rect, cls in class_buttons:
                color = (90, 140, 90) if cls == flow.actor.char_class else (60, 60, 60)
                pygame.draw.rect(screen, color, rect)
                text = font.render(cls.title(), True, (255, 255, 255))
                screen.blit(text, (rect.x + 10, rect.y + 10))
            if flow.actor.char_class:
                pygame.draw.rect(screen, (100, 100, 180), confirm_rect)
                text = font.render("Confirm", True, (255, 255, 255))
                screen.blit(text, (confirm_rect.x + 40, confirm_rect.y + 10))

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
            y = 80
            actor = flow.actor
            ancestry = actor.race.title()
            if actor.subrace:
                ancestry += f" ({actor.subrace.title()})"
            if actor.parent_races:
                ancestry += " (" + " / ".join(race.title() for race in actor.parent_races) + ")"
            header = font.render(f"{ancestry} {actor.char_class.title()} - saved", True, (255, 255, 255))
            screen.blit(header, (200, y))
            for ability, score in actor.abilities.items():
                y += 40
                line = font.render(f"{ability}: {score}", True, (255, 255, 255))
                screen.blit(line, (250, y))
            y += 40
            hp_line = font.render(f"hp: {actor.current_hp}/{actor.max_hp}", True, (255, 255, 255))
            screen.blit(hp_line, (250, y))
            y += 35
            equipped_names = []
            for slot, item in actor.equipment.items():
                if item:
                    equipped_names.append(f"{slot.replace('_', ' ')}: {item['name']}")
            gear_line = font.render("Equipped: " + (", ".join(equipped_names) or "nothing"), True, (210, 210, 210))
            screen.blit(gear_line, (40, y))
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
