from dataclasses import dataclass, field
from dice import ability_points, roll_dx
from pathlib import Path
import json

SAVE_DIR = Path('saves')
SAVE_DIR.mkdir(exist_ok=True)

@dataclass
class Actor:
    name: str
    max_hp: int = 10
    current_hp: int =10
    abilities: dict = field(default_factory= lambda:
                 {
        'strength': 8, 'dexterity': 8, 'constitution': 8,
        'intellect': 8, 'wisdom': 8, 'charisma': 8,
                })
    unspent: list = field(default_factory=ability_points)
    controller: object = None

def actor_factory(name):
    return Actor(name)

def save_actors(actor):
    path = SAVE_DIR / f"{actor.name.lower()}.json"
    with open(path, 'w') as f:
        json.dump(vars(actor), f, indent=2)

def load_actors(name):
    path = SAVE_DIR / f'{name.lower()}.json'
    with open(path) as f:
        return Actor(**json.load(f))

def list_saves():
    return sorted(p.stem for p in SAVE_DIR.glob('*.json'))

def delete_actor(name):
    path = SAVE_DIR / f'{name.lower()}.json'
    path.unlink(missing_ok=True)

def assign(actor, ability, roll_index):
    actor.abilities[ability] = actor.unspent.pop(roll_index)

def modifier(score):
    return (score - 10)//2

def starting_hp(actor):
    return 8 + modifier(actor.abilities['constitution'])
