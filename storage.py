"""Character save files and session locks."""
import json
from pathlib import Path


SAVE_DIR = Path("saves")
SAVE_DIR.mkdir(exist_ok=True)


def save_actor(actor):
    with (SAVE_DIR / f"{actor.id}.json").open("w") as save_file:
        json.dump(vars(actor), save_file, indent=2)


def load_actor(actor_id):
    from factory import Actor, EQUIPMENT_SLOTS, apply_starting_gear
    from classes import ABILITIES, SPELLS

    path = SAVE_DIR / f"{actor_id}.json"
    with path.open() as save_file:
        data = json.load(save_file)
    # Migrate saves produced before the design adopted the persistent downed state.
    if 'dead' in data:
        data.setdefault('downed', data['dead'])
        data.pop('dead', None)
    data.setdefault('classes', [])
    data.setdefault('skills', [])
    data.setdefault('xp_total', 0)
    data.setdefault('xp_earned_by_level', {})
    data.setdefault('xp_spent_by_level', {})
    data.setdefault('downed', data.get('current_hp', 1) <= 0)
    data.setdefault('conditions', [])
    data.setdefault('active_effects', [])
    if 'known_spells' not in data:
        class_names = {entry.get('name') for entry in data.get('classes', [])}
        if not class_names and data.get('char_class'):
            class_names.add(data['char_class'])
        level = max(1, int(data.get('level', 1)))
        data['known_spells'] = [
            spell_id for spell_id, spell in SPELLS.items()
            if class_names.intersection(spell.get('classes', []))
            and spell.get('prerequisite_class_level', 1) <= level
        ]
    if 'known_abilities' not in data:
        class_names = {entry.get('name') for entry in data.get('classes', [])}
        if not class_names and data.get('char_class'):
            class_names.add(data['char_class'])
        level = max(1, int(data.get('level', 1)))
        data['known_abilities'] = [
            ability_id for ability_id, ability in ABILITIES.items()
            if class_names.intersection(ability.get('classes', []))
            and ability.get('prerequisite_class_level', 1) <= level
        ]
    data.setdefault('avatar', 'asset_pack/Soldier.png')
    if not data.get('controller') or not isinstance(data.get('controller'), str):
        data['controller'] = 'player'
    elif data['controller'] == 'dm':
        data['controller'] = 'player'
    actor = Actor(**data)

    for slot in EQUIPMENT_SLOTS:
        actor.equipment.setdefault(slot, None)
    if not actor.starting_gear_applied:
        apply_starting_gear(actor)
        save_actor(actor)
    return actor


def list_actors():
    actors = []
    for path in SAVE_DIR.glob("*.json"):
        if (SAVE_DIR / f"{path.stem}.lock").exists():
            continue
        with path.open() as save_file:
            data = json.load(save_file)
        actors.append((data["id"], data["name"]))
    return sorted(actors, key=lambda actor: actor[1])


def lock_actor(actor_id):
    (SAVE_DIR / f"{actor_id}.lock").touch()


def unlock_actor(actor_id):
    (SAVE_DIR / f"{actor_id}.lock").unlink(missing_ok=True)


def delete_actor(actor_id):
    (SAVE_DIR / f"{actor_id}.json").unlink(missing_ok=True)
