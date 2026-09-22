from dataclasses import dataclass, field
from classes import RACES, CLASSES
from dice import ability_points
from pathlib import Path
import json
import uuid

SAVE_DIR = Path('saves')
SAVE_DIR.mkdir(exist_ok=True)

@dataclass
class Actor:
    name: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    max_hp: int = 10
    current_hp: int =10
    abilities: dict = field(default_factory= lambda:
                 {
        'strength': 8, 'dexterity': 8, 'constitution': 8,
        'intellect': 8, 'wisdom': 8, 'charisma': 8,
                })
    unspent: list = field(default_factory=ability_points)
    saves: list = field(default_factory=list)
    armor_prof: list = field(default_factory=list)
    weapon_prof: list = field(default_factory=list)
    race: str = ''
    char_class: str = ''
    controller: object = None
    x: int = 400
    y: int = 300

def actor_factory(name):
    return Actor(name)

def save_actors(actor):
    path = SAVE_DIR / f"{actor.id}.json"
    with open(path, 'w') as f:
        json.dump(vars(actor), f, indent=2)

def load_actors(actor_id):
    path = SAVE_DIR / f'{actor_id}.json'
    with open(path) as f:
        return Actor(**json.load(f))

def list_saves():
    saves = []
    for path in SAVE_DIR.glob('*.json'):
        lock_path = SAVE_DIR / f'{path.stem}.lock'
        if lock_path.exists():
            continue
        with open(path) as f:
            data = json.load(f)
        saves.append((data['id'], data['name']))
    return sorted(saves, key=lambda s: s[1])

def lock_actor(actor_id):
    (SAVE_DIR / f'{actor_id}.lock').touch()

def unlock_actor(actor_id):
    (SAVE_DIR / f'{actor_id}.lock').unlink(missing_ok=True)

def delete_actor(actor_id):
    path = SAVE_DIR / f'{actor_id}.json'
    path.unlink(missing_ok=True)

def assign(actor, ability, roll_index):
    actor.abilities[ability] = actor.unspent.pop(roll_index)

def modifier(score):
    return (score - 10)//2

def starting_hp(actor):
    return 8 + modifier(actor.abilities['constitution'])

def apply_race_bonus(actor):
    bonuses = RACES[actor.race]['bonuses']
    for ability, amount in bonuses.items():
        actor.abilities[ability] += amount

def starting_hp(actor):
    hit_die = CLASSES[actor.char_class]['hit_die']
    return hit_die + modifier(actor.abilities['constitution'])

def apply_class_proficiencies(actor):
    cls = CLASSES[actor.char_class]
    actor.saves = list(cls['saves'])
    actor.armor_prof = list(cls['armor_prof'])
    actor.weapon_prof = list(cls['weapon_prof'])

def apply_starting_gear(actor):
    gear = CLASSES[actor.char_class]['starting_gear']
    actor.armor = dict(gear['armor'])
    actor.weapons = list(gear['weapons'])

def pick_char():
    saves = list_saves()
    options = saves + [('new', 'new character'), ('delete', 'delete character')]
    for i, (_, name) in enumerate(options, 1):
        print(f'{i}.{name.title()}')

    while True:
        choice = input('pick:')
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            break
        print('not an option')
    picked_id, picked_name = options[int(choice) - 1]
    if picked_id == 'new':
        name = input('character name:\n').strip().title()
        actor = actor_factory(name)
        save_actors(actor)
        return actor
    if picked_id == 'delete':
        delete_char()
        return pick_char()
    return load_actors(picked_id)

def delete_char():
    saves = list_saves()
    for i, (_, name) in enumerate(saves, 1):
        print(f'{i}.{name.title()}')
    choice = input('delete which? (blank to cancel):\n')
    if not (choice.isdigit() and 1 <= int(choice) <= len(saves)):
        return
    target_id, target_name = saves[int(choice) - 1]
    if input(f'Delete {target_name.title()}? y/n: \n').lower() == 'y':
        delete_actor(target_id)