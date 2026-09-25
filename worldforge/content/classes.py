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


ENTITY_TABLES = {
    "abilities.json", "arenas.json", "classes.json", "conditions.json",
    "equipment.json", "experience.json", "item_attributes.json", "npcs.json", "races.json",
    "scenarios.json", "spells.json", "subclasses.json",
}


def _validate_table(filename, definitions, source):
    """Validate table record shapes and report the originating file/path."""
    if not isinstance(definitions, dict):
        raise ValueError(f"{source} must contain a JSON object")

    if filename in ENTITY_TABLES:
        for record_id, record in definitions.items():
            if not isinstance(record, dict):
                raise ValueError(
                    f"{source}: {record_id} must be a JSON object")

    if filename == "subclasses.json":
        for subclass_id, subclass in definitions.items():
            features = subclass.get("features", {})
            if not isinstance(features, dict):
                raise ValueError(
                    f"{source}: {subclass_id}.features must be an object keyed by level")
            for level, tier in features.items():
                path = f"{subclass_id}.features.{level}"
                try:
                    parsed_level = int(level)
                except (TypeError, ValueError):
                    raise ValueError(
                        f"{source}: {path} has a level that must be an integer") from None
                if parsed_level < 1:
                    raise ValueError(
                        f"{source}: {path} level must be greater than zero")
                entries = tier if isinstance(tier, list) else [tier]
                if not isinstance(tier, (dict, list)):
                    raise ValueError(
                        f"{source}: {path} must be a feature object or a list of feature objects")
                for index, feature in enumerate(entries):
                    feature_path = (f"{path}[{index}]" if isinstance(tier, list)
                                    else path)
                    if not isinstance(feature, dict):
                        raise ValueError(
                            f"{source}: {feature_path} must be a JSON object")
                    if ("summary" in feature
                            and not isinstance(feature["summary"], str)):
                        raise ValueError(
                            f"{source}: {feature_path}.summary must be a string")
                    if ("id" in feature
                            and not isinstance(feature["id"], str)):
                        raise ValueError(
                            f"{source}: {feature_path}.id must be a string")


def _load_table(filename):
    base_file = DATA_DIR / filename
    with base_file.open(encoding="utf-8") as data_file:
        definitions = json.load(data_file)
    _validate_table(filename, definitions, base_file)

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
        _validate_table(filename, mod_definitions, mod_file)
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
EXPERIENCE_RULES = _load_table("experience.json")
