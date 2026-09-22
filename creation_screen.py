import pygame
from classes import RACES, CLASSES
from factory import (
    actor_factory, assign, apply_race_bonus,
    apply_class_proficiencies, starting_hp, save_actors,
    list_saves, load_actors, delete_actor, lock_actor
)


def run_creation():
    pygame.init()
    screen = pygame.display.set_mode((800, 600))
    font = pygame.font.SysFont(None, 36)
    clock = pygame.time.Clock()

    stage = 'menu'  # 'menu' -> 'name' -> 'race' -> 'class' -> 'abilities' -> 'done'
    actor = None
    name_text = ''
    ability_order = None
    current_ability_index = 0
    saves = list_saves()

    confirm_rect = pygame.Rect(300, 500, 200, 50)
    name_box = pygame.Rect(250, 250, 300, 50)
    new_char_rect = pygame.Rect(250, 500, 300, 50)
    start_rect = pygame.Rect(300, 500, 200, 50)


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
            rect = pygame.Rect(300, 100 + i * 60, 200, 50)
            buttons.append((rect, name))
        return buttons

    def roll_buttons():
        buttons = []
        for i, roll in enumerate(actor.unspent):
            rect = pygame.Rect(300, 150 + i * 60, 200, 50)
            buttons.append((rect, i, roll))
        return buttons

    race_buttons = make_buttons(RACES.keys())
    class_buttons = make_buttons(CLASSES.keys())

    running = True
    while running:
        if stage == 'menu':
            saves = list_saves()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                return None

            if event.type == pygame.KEYDOWN and stage == 'name':
                if event.key == pygame.K_BACKSPACE:
                    name_text = name_text[:-1]
                elif event.key == pygame.K_RETURN:
                    if name_text.strip():
                        actor = actor_factory(name_text.strip().title())
                        ability_order = list(actor.abilities.keys())
                        stage = 'race'
                elif event.unicode.isprintable() and len(name_text) < 20:
                    name_text += event.unicode

            if event.type == pygame.MOUSEBUTTONDOWN:
                if stage == 'menu':
                    for load_rect, delete_rect, save_id, name in menu_buttons():
                        if load_rect.collidepoint(event.pos):
                            actor = load_actors(save_id)
                            lock_actor(actor.id)
                            stage = 'done'
                        elif delete_rect.collidepoint(event.pos):
                            delete_actor(save_id)
                            saves = list_saves()
                    if new_char_rect.collidepoint(event.pos):
                        stage = 'name'

                elif stage == 'name':
                    if name_text.strip() and confirm_rect.collidepoint(event.pos):
                        actor = actor_factory(name_text.strip().title())
                        ability_order = list(actor.abilities.keys())
                        stage = 'race'

                elif stage == 'race':
                    for rect, race in race_buttons:
                        if rect.collidepoint(event.pos):
                            actor.race = race
                    if actor.race and confirm_rect.collidepoint(event.pos):
                        stage = 'class'

                elif stage == 'class':
                    for rect, cls in class_buttons:
                        if rect.collidepoint(event.pos):
                            actor.char_class = cls
                    if actor.char_class and confirm_rect.collidepoint(event.pos):
                        apply_race_bonus(actor)
                        apply_class_proficiencies(actor)
                        stage = 'abilities'

                elif stage == 'abilities' and current_ability_index < len(ability_order):
                    ability = ability_order[current_ability_index]
                    for rect, roll_index, roll in roll_buttons():
                        if rect.collidepoint(event.pos):
                            assign(actor, ability, roll_index)
                            current_ability_index += 1
                            break
                    if current_ability_index == len(ability_order):
                        actor.max_hp = starting_hp(actor)
                        actor.current_hp = actor.max_hp
                        save_actors(actor)
                        lock_actor(actor.id)
                        stage = 'done'

                elif stage == 'done':
                    if start_rect.collidepoint(event.pos):
                        running = False

        screen.fill((20, 20, 20))

        if stage == 'menu':
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

        elif stage == 'name':
            prompt = font.render("enter a name:", True, (255, 255, 255))
            screen.blit(prompt, (250, 190))
            pygame.draw.rect(screen, (60, 60, 60), name_box)
            text = font.render(name_text, True, (255, 255, 255))
            screen.blit(text, (name_box.x + 10, name_box.y + 10))
            if name_text.strip():
                pygame.draw.rect(screen, (100, 100, 180), confirm_rect)
                confirm_text = font.render("Confirm", True, (255, 255, 255))
                screen.blit(confirm_text, (confirm_rect.x + 40, confirm_rect.y + 10))

        elif stage == 'race':
            for rect, race in race_buttons:
                color = (90, 140, 90) if race == actor.race else (60, 60, 60)
                pygame.draw.rect(screen, color, rect)
                text = font.render(race.title(), True, (255, 255, 255))
                screen.blit(text, (rect.x + 10, rect.y + 10))
            if actor.race:
                pygame.draw.rect(screen, (100, 100, 180), confirm_rect)
                text = font.render("Confirm", True, (255, 255, 255))
                screen.blit(text, (confirm_rect.x + 40, confirm_rect.y + 10))

        elif stage == 'class':
            for rect, cls in class_buttons:
                color = (90, 140, 90) if cls == actor.char_class else (60, 60, 60)
                pygame.draw.rect(screen, color, rect)
                text = font.render(cls.title(), True, (255, 255, 255))
                screen.blit(text, (rect.x + 10, rect.y + 10))
            if actor.char_class:
                pygame.draw.rect(screen, (100, 100, 180), confirm_rect)
                text = font.render("Confirm", True, (255, 255, 255))
                screen.blit(text, (confirm_rect.x + 40, confirm_rect.y + 10))

        elif stage == 'abilities':
            if current_ability_index < len(ability_order):
                ability = ability_order[current_ability_index]
                prompt = font.render(f"pick a roll for {ability}", True, (255, 255, 255))
                screen.blit(prompt, (250, 80))
                for rect, roll_index, roll in roll_buttons():
                    pygame.draw.rect(screen, (60, 60, 60), rect)
                    text = font.render(str(roll), True, (255, 255, 255))
                    screen.blit(text, (rect.x + 85, rect.y + 10))

        elif stage == 'done':
            y = 80
            header = font.render(f"{actor.race.title()} {actor.char_class.title()} - saved", True, (255, 255, 255))
            screen.blit(header, (200, y))
            for ability, score in actor.abilities.items():
                y += 40
                line = font.render(f"{ability}: {score}", True, (255, 255, 255))
                screen.blit(line, (250, y))
            y += 40
            hp_line = font.render(f"hp: {actor.current_hp}/{actor.max_hp}", True, (255, 255, 255))
            screen.blit(hp_line, (250, y))
            pygame.draw.rect(screen, (100, 180, 100), start_rect)
            start_text = font.render("Start", True, (255, 255, 255))
            screen.blit(start_text, (start_rect.x + 65, start_rect.y + 10))

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()
    return actor