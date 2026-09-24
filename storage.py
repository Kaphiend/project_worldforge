"""Character save files and session locks."""
import json
import sys
from runtime_paths import resource_path, user_data_path


SAVE_DIR = (user_data_path("saves") if getattr(sys, "frozen", False)
            else resource_path("saves"))


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
    if not isinstance(data.get('spell_hotbars'), list):
        data['spell_hotbars'] = []
    bars = data['spell_hotbars']
    while len(bars) < 4:
        bars.append([None] * 10)
    for bar_index in range(4):
        if not isinstance(bars[bar_index], list):
            bars[bar_index] = [None] * 10
        bars[bar_index] = (bars[bar_index] + [None] * 10)[:10]
    if not any(any(bar) for bar in bars):
        bars[0][0] = 'action:weapon_attack'
    elif not any(item in {'action:weapon_attack', 'action:ranged_weapon_attack'}
                 for bar in bars for item in bar if isinstance(item, str)):
        first_empty = next(((bar, slot) for bar in bars
                            for slot, item in enumerate(bar) if item is None), None)
        if first_empty:
            bar, slot = first_empty
            bars[bar][slot] = 'action:weapon_attack'
    if not isinstance(data.get('quick_items'), dict):
        data['quick_items'] = {}
    data['quick_items'].setdefault('q', None)
    data['quick_items'].setdefault('e', None)
    data.setdefault('skills', [])
    data.setdefault('xp_total', 0)
    data.setdefault('xp_earned_by_level', {})
    data.setdefault('xp_spent_by_level', {})
    data.setdefault('class_spell_purchases', {})
    data.setdefault('class_ability_purchases', {})
    data.setdefault('xp_rest_spent_by_level', {})
    data.setdefault('attribute_points_spent', {})
    data.setdefault('withdrawn', False)
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
            and (not spell.get('acquisition')
                 or spell.get('acquisition') == 'starting_cantrip')
        ]
    if not isinstance(data.get('known_spells'), list):
        data['known_spells'] = []
    class_names = {entry.get('name') for entry in data.get('classes', [])}
    if not class_names and data.get('char_class'):
        class_names.add(data['char_class'])
    class_names.update(class_id for class_id, ids in
                       (data.get('class_spell_purchases', {}) or {}).items() if ids)
    class_names.update(class_id for class_id, ids in
                       (data.get('class_ability_purchases', {}) or {}).items() if ids)
    for spell_id, spell in SPELLS.items():
        if spell.get('cantrip') and class_names.intersection(spell.get('classes', [])):
            if spell_id not in data['known_spells']:
                data['known_spells'].append(spell_id)
    if data.get('char_class'):
        class_names.add(data['char_class'])
    # Remove class spells that may have entered a legacy save through the old
    # trainer's unrestricted class tabs.
    data['known_spells'] = [
        spell_id for spell_id in data['known_spells']
        if spell_id in SPELLS
        and class_names.intersection(SPELLS[spell_id].get('classes', []))
    ]
    if not isinstance(data.get('prepared_spells'), list):
        data['prepared_spells'] = [
            spell_id for spell_id in data['known_spells']
            if SPELLS.get(spell_id, {}).get('acquisition') == 'starting_cantrip'
            or SPELLS.get(spell_id, {}).get('cantrip')
        ]
    data['prepared_spells'] = [spell_id for spell_id in data['prepared_spells']
                               if spell_id in data['known_spells']]
    if 'known_abilities' not in data:
        class_names = {entry.get('name') for entry in data.get('classes', [])}
        if not class_names and data.get('char_class'):
            class_names.add(data['char_class'])
        level = max(1, int(data.get('level', 1)))
        data['known_abilities'] = [
            ability_id for ability_id, ability in ABILITIES.items()
            if class_names.intersection(ability.get('classes', []))
            and ability.get('acquisition') != 'trainer_purchase'
            and ability.get('prerequisite_class_level', 1) <= level
        ]
    # Legacy saves already owned every option their former level granted.
    # Preserve those options and migrate their class ownership once.
    if not data['class_spell_purchases']:
        for spell_id in data.get('known_spells', []):
            spell = SPELLS.get(spell_id, {})
            if spell.get('acquisition') == 'trainer_purchase' and not spell.get('cantrip'):
                for class_id in class_names.intersection(spell.get('classes', [])):
                    data['class_spell_purchases'].setdefault(class_id, []).append(spell_id)
    if not data['class_ability_purchases']:
        for ability_id in data.get('known_abilities', []):
            ability = ABILITIES.get(ability_id, {})
            if ability.get('acquisition') == 'trainer_purchase':
                for class_id in class_names.intersection(ability.get('classes', [])):
                    data['class_ability_purchases'].setdefault(class_id, []).append(ability_id)
    data.setdefault('avatar', 'asset_pack/Soldier.png')
    # Earlier quick-start saves were level 3 but carried no XP balance.
    if (int(data.get('xp_total', 0) or 0) == 0
            and not data.get('xp_earned_by_level')
            and int(data.get('level', 1) or 1) > 1):
        from progression import XP_THRESHOLDS
        legacy_level = min(int(data['level']), len(XP_THRESHOLDS))
        data['xp_total'] = XP_THRESHOLDS[legacy_level - 1]
        data['xp_earned_by_level'] = {str(legacy_level): data['xp_total']}
    if not data.get('controller') or not isinstance(data.get('controller'), str):
        data['controller'] = 'player'
    elif data['controller'] == 'dm':
        data['controller'] = 'player'
    from progression import sync_progression_levels
    sync_progression_levels(data)
    # Migrate older saves that treated every learned spell as prepared. Keep
    # cantrips ready and retain the earliest leveled preparations up to cap.
    from progression import (is_cantrip, prepared_spell_limit,
                             spell_source_class)
    cantrips, leveled_by_class = [], {}
    for spell_id in data['prepared_spells']:
        definition = SPELLS.get(spell_id, {})
        if is_cantrip(definition):
            if spell_id not in cantrips:
                cantrips.append(spell_id)
            continue
        class_id = spell_source_class(data, spell_id)
        if class_id:
            leveled_by_class.setdefault(class_id, []).append(spell_id)
    trimmed = []
    for class_id, spell_ids in leveled_by_class.items():
        trimmed.extend(spell_ids[:prepared_spell_limit(data, class_id)])
    data['prepared_spells'] = cantrips + trimmed
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
