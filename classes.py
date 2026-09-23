"""Load class and race definitions from JSON data and optional mods.

Mod data lives in ``data/mods/<mod-name>/`` and may override classes, races, or
equipment templates. Mod folders load alphabetically; later mods replace
definitions with the same key.
"""
import json
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parent / "data"
MODS_DIR = DATA_DIR / "mods"


def _load_table(filename):
    base_file = DATA_DIR / filename
    with base_file.open(encoding="utf-8") as data_file:
        definitions = json.load(data_file)
    if not isinstance(definitions, dict):
        raise ValueError(f"{base_file} must contain a JSON object")

    if MODS_DIR.exists():
        for mod_dir in sorted(path for path in MODS_DIR.iterdir() if path.is_dir()):
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
EQUIPMENT_ITEMS = _load_table("equipment.json")
SPELLS = _load_table("spells.json")
ABILITIES = _load_table("abilities.json")
CONDITIONS = _load_table("conditions.json")
NPCS = _load_table("npcs.json")
ARENAS = _load_table("arenas.json")
SCENARIOS = _load_table("scenarios.json")
