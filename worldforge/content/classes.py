"""Load class and race definitions from JSON data and optional mods.

Mod data lives in ``data/mods/<mod-name>/`` and may override classes, races, or
equipment templates. Mod folders load alphabetically; later mods replace
definitions with the same key.
"""
import json
import sys
from worldforge.core.runtime_paths import resource_path, user_data_path


DATA_DIR = resource_path("data")
MODS_DIR = DATA_DIR / "mods"
USER_MODS_DIR = user_data_path("mods") if getattr(sys, "frozen", False) else None


def _load_table(filename):
    base_file = DATA_DIR / filename
    with base_file.open(encoding="utf-8") as data_file:
        definitions = json.load(data_file)
    if not isinstance(definitions, dict):
        raise ValueError(f"{base_file} must contain a JSON object")

    mod_roots = [MODS_DIR]
    if USER_MODS_DIR is not None:
        mod_roots.append(USER_MODS_DIR)
    mod_dirs = sorted(
        ((root_index, path) for root_index, root in enumerate(mod_roots)
         if root.exists() for path in root.iterdir() if path.is_dir()),
        key=lambda item: (item[1].name, item[0]),
    )
    for _, mod_dir in mod_dirs:
        mod_file = mod_dir / filename
        if not mod_file.exists():
            continue
        with mod_file.open(encoding="utf-8") as data_file:
            mod_definitions = json.load(data_file)
        if not isinstance(mod_definitions, dict):
            raise ValueError(f"{mod_file} must contain a JSON object")
        definitions.update(mod_definitions)
    return definitions


CLASSES = _load_table("classes.json")
RACES = _load_table("races.json")

# Every skill any class draws from. Collected from the fixed skill lists
# across classes.json; keep this in sync if a mod adds a new skill name.
ALL_SKILLS = [
    'acrobatics', 'animal handling', 'arcana', 'athletics', 'deception',
    'history', 'insight', 'intimidation', 'investigation', 'medicine',
    'nature', 'perception', 'performance', 'persuasion', 'religion',
    'sleight of hand', 'stealth', 'survival',
]


def skill_options(class_name):
    """Return the skill list offered for XP purchase by a class trainer.

    classes.json lets a class use the sentinel ``["any"]`` (bard) to mean
    "choose from every skill in the game" instead of a fixed short list.
    Without this, callers were treating ``["any"]`` as a literal one-item
    skill list, which made ``skill_choices: 3`` impossible to satisfy. Expand
    the sentinel here so the trainer receives the full option list.
    """
    listed = CLASSES[class_name].get('skills', [])
    if listed == ['any']:
        return ALL_SKILLS
    return listed


def subclass_feature_items(subclass_id):
    """Yield (level, purchase_id, feature) for both old and list-shaped data."""
    subclass = SUBCLASSES.get(subclass_id, {})
    for level, value in (subclass.get("features", {}) or {}).items():
        features = value if isinstance(value, list) else [value]
        for feature in features:
            if not isinstance(feature, dict):
                continue
            feature_id = feature.get("id")
            purchase_id = (f"{subclass_id}_{feature_id}" if feature_id
                           else f"{subclass_id}_{level}")
            yield str(level), purchase_id, feature

EQUIPMENT_ITEMS = _load_table("equipment.json")
SPELLS = _load_table("spells.json")
ABILITIES = _load_table("abilities.json")
CONDITIONS = _load_table("conditions.json")
NPCS = _load_table("npcs.json")
ARENAS = _load_table("arenas.json")
SCENARIOS = _load_table("scenarios.json")
SUBCLASSES = _load_table("subclasses.json")
PROGRESSION_RULES = _load_table("progression.json")
ITEM_ATTRIBUTES = _load_table("item_attributes.json")
MOB_GENERATION_RULES = _load_table("mob_generation.json")
