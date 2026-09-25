"""Actor and item construction.

Modders normally change JSON templates, not these constructors. Add a field
here only when actors must save, sync, or calculate with new persistent data;
then update the matching loader/UI/rule and migration notes. Equipment slot
legality and the randomized fully geared demo actor are also defined here.
"""
from dataclasses import dataclass, field
from copy import deepcopy
from worldforge.content.classes import (EQUIPMENT_ITEMS, RACES, CLASSES,
                     NPCS, ITEM_ATTRIBUTES, MOB_GENERATION_RULES)
from worldforge.core.dice import ability_points, ability_modifier
from worldforge.core.progression import initialize_resources
import random
import uuid

EQUIPMENT_SLOTS = (
    'head', 'chest', 'hands', 'feet', 'belt', 'cape',
    'ring1', 'ring2', 'amulet', 'main_hand', 'off_hand', 'ranged',
)

@dataclass
class Actor:
    name: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    max_hp: int = 10
    current_hp: int =10
    classes: list = field(default_factory=list)
    level: int = 1
    class_levels_initialized: bool = True
    xp_total: int = 0
    xp_earned_by_level: dict = field(default_factory=dict)
    xp_spent_by_level: dict = field(default_factory=dict)
    xp_rest_spent_by_level: dict = field(default_factory=dict)
    class_spell_purchases: dict = field(default_factory=dict)
    class_ability_purchases: dict = field(default_factory=dict)
    withdrawn: bool = False
    downed: bool = False
    sneaking: bool = False
    stealth_check_total: int = None
    hidden: dict = None
    conditions: list = field(default_factory=list)
    active_effects: list = field(default_factory=list)
    known_spells: list = field(default_factory=list)
    prepared_spells: list = field(default_factory=list)
    # Weapon attacks are ready in slot 1; other spell/ability slots start empty.
    spell_hotbars: list = field(default_factory=lambda: [
        ["action:weapon_attack"] + [None] * 9, [None] * 10,
        [None] * 10, [None] * 10])
    quick_items: dict = field(default_factory=lambda: {"q": None, "e": None})
    known_abilities: list = field(default_factory=list)
    class_features: list = field(default_factory=list)
    class_feature_purchases: dict = field(default_factory=dict)
    class_skill_purchases: dict = field(default_factory=dict)
    spell_points: int = None
    class_resources: dict = field(default_factory=dict)
    attribute_points_spent: dict = field(default_factory=dict)
    # Class levels are selected when earned character levels are applied.
    # The XP-based level is permanent; trainer spending only affects purchase access.
    gold: int = 50
    outdoor_rest_streak: int = 0
    avatar: str = 'asset_pack/Soldier.png'
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
    subrace: str = ''
    subclass: str = ''
    parent_races: list = field(default_factory=list)
    char_class: str = ''
    skills: list = field(default_factory=list)
    controller: str = 'player'
    x: int = 400
    y: int = 300
    inventory: list = field(default_factory=list)
    equipment: dict = field(default_factory=lambda: {slot: None for slot in EQUIPMENT_SLOTS})
    active_weapon_set: str = 'melee'
    starting_gear_applied: bool = False

    def __post_init__(self):
        if self.classes:
            primary = self.classes[0]
            self.char_class = primary.get('name', self.char_class)
        elif self.char_class:
            self.classes = [{'name': self.char_class, 'level': max(1, self.level)}]
        initialize_resources(vars(self))
        if not self.controller:
            self.controller = 'player'


def actor_factory(name, controller='player'):
    return Actor(name, controller=controller)


def npc_factory(name, **actor_data):
    """Create an NPC with the same data model as a player character."""
    actor_data.setdefault('controller', 'ai')
    return Actor(name, **actor_data)


def create_npc_instance(template_id, x, y):
    """Create a class-aware, independently geared instance from an NPC template."""
    if template_id not in NPCS:
        raise KeyError(f"Unknown NPC template: {template_id}")
    template = deepcopy(NPCS[template_id])
    template.setdefault("controller", "ai")
    level = min(20, max(1, int(template.get("level", 1) or 1)))
    rules = MOB_GENERATION_RULES
    class_pool = [class_id for class_id in
                  template.get("class_pool", rules.get("class_pool", list(CLASSES)))
                  if class_id in CLASSES]
    class_id = template.get("char_class")
    if class_id not in CLASSES:
        class_id = random.choice(class_pool or list(CLASSES))
    template["char_class"] = class_id
    template["classes"] = [{"name": class_id, "level": level}]
    template["class_features"] = list(template.get("class_features", []) or [])
    class_data = CLASSES[class_id]
    for field_name in ("saves", "armor_prof", "weapon_prof"):
        template[field_name] = list(class_data.get(field_name, []))
    template["skills"] = list(template.get("skills", []) or [])

    supplied_abilities = template.get("abilities", {}) or {}
    scores = [int(supplied_abilities.get(name, 10) or 10) for name in ABILITY_NAMES]
    template["abilities"] = prioritize_ability_scores(scores, class_id)
    template["level"] = level

    tags = list(template.get("tags", []) or [])
    elite_chance = min(1.0, max(0.0, float(template.get("elite_chance", 0) or 0)))
    elite = bool(template.get("elite", False) or "elite" in tags
                 or random.random() < elite_chance)
    template["elite"] = elite
    if elite and "elite" not in tags:
        tags.append("elite")
    template["tags"] = tags
    if elite:
        elite_rules = rules.get("elite", {})
        priorities = class_ability_priorities(class_id)
        base_cap = int(elite_rules.get("ability_score_base_cap", 15))
        score_cap = min(30, base_cap + level)
        for index, amount_key in ((0, "primary_ability_bonus"),
                                  (1, "secondary_ability_bonus")):
            ability = priorities[index]
            amount = max(0, int(elite_rules.get(amount_key, 0)))
            base_score = int(template["abilities"].get(ability, 10))
            level_cap = max(base_score, score_cap)
            template["abilities"][ability] = min(
                level_cap, base_score + amount)
        hp_multiplier = max(1.0, float(elite_rules.get("hit_points_multiplier", 1.15)))
        template["max_hp"] = max(1, round(int(template.get("max_hp", 10)) * hp_multiplier))

    template["template_id"] = template_id
    template["elite"] = elite
    template["equipment"] = _generate_npc_equipment(template, template_id, class_id, level, elite)
    template.update(id=f"{template_id}-{uuid.uuid4().hex[:8]}", x=x, y=y,
                    downed=False)
    template["current_hp"] = effective_max_hp(template)
    template.setdefault("conditions", [])
    template.setdefault("active_effects", [])
    template.setdefault("inventory", [])
    initialize_resources(template, refill=True)
    return template


def _eligible_item_templates(slot, class_id, configured_pool=None):
    class_data = CLASSES.get(class_id, {})
    armor_proficiencies = set(class_data.get("armor_prof", []))
    weapon_proficiencies = set(class_data.get("weapon_prof", []))
    candidates = []
    ids = configured_pool if configured_pool is not None else EQUIPMENT_ITEMS.keys()
    for item_id in ids:
        definition = EQUIPMENT_ITEMS.get(item_id, {})
        if not definition or definition.get("category") == "consumable":
            continue
        allowed_slots = definition.get("allowed_slots", [])
        if slot not in allowed_slots:
            continue
        category = definition.get("category")
        if category == "weapon" and definition.get("weapon_class") not in weapon_proficiencies:
            continue
        if category == "shield" and "shields" not in armor_proficiencies:
            continue
        if category == "shield" and slot == "main_hand":
            continue
        if category in {"light", "medium", "heavy"} and category not in armor_proficiencies:
            continue
        if category == "armor_piece" or category == "accessory" or category == "focus":
            pass
        elif category not in {"weapon", "shield", "light", "medium", "heavy", "unarmored"}:
            continue
        candidates.append(item_id)
    return candidates


def _roll_item_rarity(elite=False):
    gear_rules = MOB_GENERATION_RULES.get("gear", {})
    tiers = list(gear_rules.get("rarity_tiers", ["common", "uncommon", "rare", "epic", "legendary"]))
    weights = gear_rules.get("rarity_weights", {})
    available = [(tier, max(0, float(weights.get(tier, 0)))) for tier in tiers]
    if not any(weight for _tier, weight in available):
        chosen = tiers[0] if tiers else "common"
    else:
        chosen = random.choices([tier for tier, _weight in available],
                                weights=[weight for _tier, weight in available], k=1)[0]
    if elite and tiers:
        shift = max(0, int(MOB_GENERATION_RULES.get("elite", {}).get("rarity_shift", 1)))
        chosen = tiers[min(len(tiers) - 1, tiers.index(chosen) + shift)]
    return chosen


def _roll_item_attributes(template_id, slot, item_level, rarity):
    definition = EQUIPMENT_ITEMS[template_id]
    rarity_counts = MOB_GENERATION_RULES.get("gear", {}).get(
        "attribute_count_by_rarity", {})
    count = max(0, int(rarity_counts.get(rarity, 0)))
    eligible = []
    for attribute_id, attribute in ITEM_ATTRIBUTES.items():
        if not (int(attribute.get("min_item_level", 1)) <= item_level
                <= int(attribute.get("max_item_level", 20))):
            continue
        if definition.get("category") not in attribute.get("allowed_categories", []):
            continue
        if slot not in attribute.get("allowed_slots", []):
            continue
        eligible.append((attribute_id, attribute))
    rolled, groups = {}, set()
    for _ in range(count):
        choices = [(attribute_id, attribute) for attribute_id, attribute in eligible
                   if attribute.get("group") not in groups]
        if not choices:
            break
        weights = [max(0.0, float(attribute.get("weight", 1)))
                   for _attribute_id, attribute in choices]
        if not any(weights):
            weights = None
        attribute_id, attribute = random.choices(
            choices, weights=weights, k=1)[0]
        value_range = attribute.get("value_range")
        if value_range:
            value = random.randint(int(value_range["min"]), int(value_range["max"]))
        else:
            value = int(attribute.get("effect", {}).get("multiplier", 1))
        rolled[attribute_id] = value
        groups.add(attribute.get("group"))
    return rolled


def _generated_item(template_id, slot, item_level, elite):
    definition = EQUIPMENT_ITEMS[template_id]
    rarity = _roll_item_rarity(elite)
    attributes = _roll_item_attributes(template_id, slot, item_level, rarity)
    affix_names = [ITEM_ATTRIBUTES[key].get("name", key)
                   for key in attributes if key in ITEM_ATTRIBUTES]
    item_name = " ".join(affix_names + [definition.get("name", template_id)])
    return {
        "id": uuid.uuid4().hex[:12], "template_id": template_id,
        "name": item_name, "slot": slot, "tags": list(definition.get("tags", [])),
        "rarity": rarity, "item_level": item_level,
        "rolled_attributes": attributes,
    }


def _generate_npc_equipment(template, template_id, class_id, level, elite):
    source = NPCS.get(template_id, {})
    requested_slots = (list(source.get("gear_slots") or [])
                       if "gear_slots" in source else [
                           slot for slot, item in
                           (source.get("equipment", {}) or {}).items() if item])
    pools = source.get("gear_pools", {}) or {}
    item_level = min(20, level + (int(MOB_GENERATION_RULES.get("elite", {}).get(
        "item_level_bonus", 2)) if elite else 0))
    equipment = {slot: None for slot in EQUIPMENT_SLOTS}
    for slot in requested_slots:
        if slot not in equipment or equipment.get(slot):
            continue
        candidate_ids = _eligible_item_templates(slot, class_id, pools.get(slot))
        if not candidate_ids:
            continue
        template_id_choice = random.choice(candidate_ids)
        item = _generated_item(template_id_choice, slot, item_level, elite)
        two_handed = is_two_handed(item_definition(item))
        if two_handed and slot in {"main_hand", "off_hand"}:
            other_hand = "off_hand" if slot == "main_hand" else "main_hand"
            if equipment.get(other_hand):
                continue
            equipment[slot] = item
            equipment[other_hand] = item
        else:
            equipment[slot] = item
    _enforce_two_handed_equipment(equipment)
    return equipment

def assign(actor, ability, roll_index):
    actor.abilities[ability] = actor.unspent.pop(roll_index)

def modifier(score):
    return ability_modifier(score)


ABILITY_NAMES = ("strength", "dexterity", "constitution", "intellect",
                 "wisdom", "charisma")


def class_ability_priorities(class_name):
    configured = MOB_GENERATION_RULES.get("ability_priorities", {}).get(class_name, [])
    valid = [name for name in configured if name in ABILITY_NAMES]
    casting_ability = CLASSES.get(class_name, {}).get("spellcasting_ability")
    if not valid and casting_ability in ABILITY_NAMES:
        valid = [casting_ability, "constitution"]
    return valid + [name for name in ABILITY_NAMES if name not in valid]


def prioritize_ability_scores(scores, class_name):
    """Place a score pool into abilities from most to least class useful."""
    if isinstance(scores, dict):
        values = [int(scores.get(name, 10) or 10) for name in ABILITY_NAMES]
    else:
        values = [int(value) for value in scores]
        values.extend([10] * max(0, len(ABILITY_NAMES) - len(values)))
        values = values[:len(ABILITY_NAMES)]
    values.sort(reverse=True)
    return dict(zip(class_ability_priorities(class_name), values))


def item_attribute_total(item, effect_kind):
    """Sum values for rolled attributes with the requested effect kind."""
    total = 0
    rolled = (item or {}).get("rolled_attributes", {}) or {}
    if not isinstance(rolled, dict):
        return 0
    for attribute_id, value in rolled.items():
        definition = ITEM_ATTRIBUTES.get(attribute_id, {})
        effect = definition.get("effect", {})
        if effect.get("kind") == effect_kind:
            if effect_kind == "weapon_damage_dice_multiplier":
                total = max(total, int(effect.get("multiplier", value) or 1))
            else:
                total += int(value or 0)
    return total


def effective_max_hp(actor):
    """Return base max HP plus gear and species bonuses."""
    equipment = actor.get("equipment", {}) if isinstance(actor, dict) else actor.equipment
    base = actor.get("max_hp", 1) if isinstance(actor, dict) else actor.max_hp
    bonuses = sum(item_attribute_total(item, "maximum_hp_bonus")
                  for item in _unique_equipped_items(equipment))
    from worldforge.combat.species import species_traits
    if "dwarven_toughness" in species_traits(actor):
        level = actor.get("level", 1) if isinstance(actor, dict) else actor.level
        bonuses += max(1, int(level or 1))
    return max(1, int(base or 1) + bonuses)


def _unique_equipped_items(equipment):
    seen, result = set(), []
    for item in (equipment or {}).values():
        if not item:
            continue
        item_id = item.get("id")
        identity = item_id if item_id is not None else id(item)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(item)
    return result


def _clamp_current_hp(actor):
    if isinstance(actor, dict):
        if "current_hp" in actor:
            actor["current_hp"] = min(int(actor["current_hp"]), effective_max_hp(actor))
    elif actor.current_hp is not None:
        actor.current_hp = min(int(actor.current_hp), effective_max_hp(actor))

def starting_hp(actor):
    hit_die = CLASSES[actor.char_class]['hit_die']
    return hit_die + modifier(actor.abilities['constitution'])

def apply_class_proficiencies(actor):
    cls = CLASSES[actor.char_class]
    actor.saves = list(cls['saves'])
    actor.armor_prof = list(cls['armor_prof'])
    actor.weapon_prof = list(cls['weapon_prof'])

def apply_starting_gear(actor):
    if actor.starting_gear_applied or not actor.char_class:
        return
    starting_gear = CLASSES[actor.char_class]['starting_gear']
    for slot, details in starting_gear.items():
        template_id = details.get('template_id')
        if template_id:
            item = add_equipment_item(actor, template_id=template_id)
            if not equip_item(actor, item['id'], slot):
                actor.inventory.remove(item)
                raise ValueError(f"Invalid starting gear slot {slot!r} for {template_id!r}")
            if slot == 'ranged':
                actor.active_weapon_set = 'ranged'
            continue

        # Accept legacy inline gear definitions in old class mods and saves.
        item_data = dict(details)
        name = item_data.pop('name')
        item_slot = item_data.pop('slot', slot)
        item = add_equipment_item(actor, name, item_slot, item_data)
        if not equip_item(actor, item['id'], slot):
            actor.inventory.remove(item)
            raise ValueError(f"Invalid starting gear slot {slot!r} for {name!r}")
        if slot == 'ranged':
            actor.active_weapon_set = 'ranged'
    actor.starting_gear_applied = True


def random_fully_geared_actor(name=None, avatars=None, class_name=None):
    """Build a geared level-three demo actor, with an optional chosen class."""
    race_options = [key for key, data in RACES.items()
                    if data.get('selectable', True)]
    race = random.choice(race_options)
    class_name = class_name if class_name in CLASSES else random.choice(list(CLASSES))
    if not name:
        name = f"Demo {class_name.title()} {uuid.uuid4().hex[:4]}"
    actor = actor_factory(name, controller='player')
    actor.race = race
    if RACES[race].get('half_breed'):
        parents = [key for key, data in RACES.items()
                   if not data.get('half_breed') and data.get('selectable', True)]
        actor.parent_races = random.choices(parents, k=2)
    elif RACES[race].get('subraces'):
        actor.subrace = random.choice(list(RACES[race]['subraces']))
    actor.char_class = class_name
    actor.gold = 500
    actor.level = 3
    actor.xp_total = 1700
    actor.xp_earned_by_level = {"3": 1700}
    actor.classes = [{'name': class_name, 'level': actor.level}]
    actor.abilities = prioritize_ability_scores(ability_points(), class_name)
    actor.skills = []
    subclass_ids = CLASSES[class_name].get('subclasses', [])
    if subclass_ids:
        actor.subclass = random.choice(subclass_ids)
    apply_class_proficiencies(actor)
    hit_die = CLASSES[class_name]['hit_die']
    con_mod = modifier(actor.abilities.get('constitution', 10))
    actor.max_hp = max(3, hit_die + con_mod + sum(
        max(1, random.randint(1, hit_die) + con_mod) for _ in range(actor.level - 1)))
    actor.current_hp = actor.max_hp
    actor.inventory = []
    actor.equipment = {slot: None for slot in EQUIPMENT_SLOTS}
    actor.starting_gear_applied = True

    fixed_slots = {
        'head': 'leather_cap', 'hands': 'travel_gloves', 'feet': 'trail_boots',
        'belt': 'utility_belt', 'cape': 'wool_cape', 'ring1': 'ring_guard',
        'ring2': 'ring_focus', 'amulet': 'brass_amulet',
    }
    for slot, template_id in fixed_slots.items():
        item = add_equipment_item(actor, template_id=template_id)
        equip_item(actor, item['id'], slot)

    chest_templates = ['unarmored', 'leather', 'chain_shirt', 'scale_mail', 'chain_mail']
    armor_proficiencies = set(actor.armor_prof)
    legal_chest = [template_id for template_id in chest_templates
                   if EQUIPMENT_ITEMS[template_id]['category'] in armor_proficiencies]
    chest_template = random.choice(legal_chest or ['unarmored'])
    item = add_equipment_item(actor, template_id=chest_template)
    equip_item(actor, item['id'], 'chest')

    main_candidates = _eligible_item_templates('main_hand', class_name)
    dex_favored = (class_ability_priorities(class_name).index('dexterity')
                   < class_ability_priorities(class_name).index('strength'))
    if dex_favored:
        finesse = [item_id for item_id in main_candidates
                   if 'finesse' in EQUIPMENT_ITEMS[item_id].get('tags', [])]
        main_candidates = finesse or main_candidates
    main_template = random.choice(main_candidates) if main_candidates else 'dagger'
    item = add_equipment_item(actor, template_id=main_template)
    equip_item(actor, item['id'], 'main_hand')
    offhand_candidates = _eligible_item_templates('off_hand', class_name)
    offhand_candidates = [item_id for item_id in offhand_candidates
                          if not is_two_handed(EQUIPMENT_ITEMS[item_id])]
    if offhand_candidates:
        item = add_equipment_item(actor, template_id=random.choice(offhand_candidates))
        equip_item(actor, item['id'], 'off_hand')
    _enforce_two_handed_equipment(actor.equipment)

    ranged_candidates = _eligible_item_templates('ranged', class_name)
    if ranged_candidates:
        ranged_template = random.choice(ranged_candidates)
        item = add_equipment_item(actor, template_id=ranged_template)
        equip_item(actor, item['id'], 'ranged')
        if 'ranged_offhand' in EQUIPMENT_ITEMS[ranged_template].get('allowed_slots', []):
            item = add_equipment_item(actor, template_id=ranged_template)
            equip_item(actor, item['id'], 'ranged_offhand')

    for _ in range(3):
        add_equipment_item(actor, template_id='healing_potion')
    add_equipment_item(actor, template_id='revival_scroll')

    actor.known_spells = []
    actor.prepared_spells = []
    actor.known_abilities = []
    initialize_resources(vars(actor), refill=True)
    if avatars:
        actor.avatar = random.choice(list(avatars))
    return actor


def add_equipment_item(actor, name=None, slot=None, details=None, template_id=None,
                       quantity=None):
    """Add an item instance, merging into catalog-defined stacks where possible."""
    if template_id:
        template = EQUIPMENT_ITEMS[template_id]
        name = name or template['name']
        slot = slot or template['slot']
        tags = list(template.get('tags', []))
        stackable = bool(template.get('stackable', False))
        max_stack = max(1, int(template.get('max_stack', 99)))
    else:
        tags = []
        stackable = bool((details or {}).get('stackable', False))
        max_stack = max(1, int((details or {}).get('max_stack', 99)))
    inventory = actor.setdefault('inventory', []) if isinstance(actor, dict) else actor.inventory
    requested = max(1, int(quantity if quantity is not None
                            else (details or {}).get('quantity', 1)))
    first = None
    if stackable and template_id:
        for existing in inventory:
            if existing.get('template_id') != template_id:
                continue
            current = max(1, int(existing.get('quantity', 1)))
            added = min(requested, max(0, max_stack - current))
            if added:
                existing['quantity'] = current + added
                requested -= added
                first = first or existing
            if not requested:
                return first

    while requested:
        stack_quantity = min(requested, max_stack) if stackable else 1
        item = {
            'id': uuid.uuid4().hex[:12],
            'name': name,
            'slot': slot,
            'tags': tags,
            'rarity': None,
            'rolled_attributes': {},
        }
        if stackable:
            item['quantity'] = stack_quantity
        if details:
            item.update({key: value for key, value in details.items()
                         if key not in {'name', 'quantity', 'stackable', 'max_stack'}})
        if template_id:
            item['template_id'] = template_id
        inventory.append(item)
        first = first or item
        requested -= stack_quantity
    return first


def item_definition(item):
    """Return catalog behavior when available, falling back to legacy data."""
    template_id = item.get('template_id')
    return EQUIPMENT_ITEMS.get(template_id, item)


def _enforce_two_handed_equipment(equipment):
    """Prevent generated loadouts from pairing a two-handed weapon with another item."""
    main = equipment.get('main_hand')
    off = equipment.get('off_hand')
    if not main or not off or main.get('id') == off.get('id'):
        return
    if is_two_handed(item_definition(main)):
        equipment['off_hand'] = main
    elif is_two_handed(item_definition(off)):
        equipment['main_hand'] = off


def equip_item(actor, item_id, slot):
    """Move an inventory item into a compatible equipment slot."""
    inventory = actor.setdefault('inventory', []) if isinstance(actor, dict) else actor.inventory
    equipment = (actor.setdefault('equipment', {name: None for name in EQUIPMENT_SLOTS})
                 if isinstance(actor, dict) else actor.equipment)
    item = next((entry for entry in inventory if entry['id'] == item_id), None)
    if item is None:
        return False
    definition = item_definition(item)
    allowed_slots = definition.get('allowed_slots')
    if allowed_slots is not None:
        valid_slots = set(allowed_slots)
    else:
        valid_slots = {item.get('slot')}
        if item.get('slot') == 'hand':
            valid_slots.update(('main_hand', 'off_hand'))
        if item.get('slot') == 'ranged':
            valid_slots.add('ranged_offhand')
        if item.get('slot') == 'ring':
            valid_slots.update(('ring1', 'ring2'))
    if slot not in valid_slots:
        return False
    if slot == 'ranged_offhand' and 'ranged_offhand' not in equipment_slots(actor):
        return False
    if slot == 'ranged_offhand':
        ranged_item = equipment.get('ranged')
        if not ranged_item or is_two_handed(item_definition(ranged_item)):
            return False
    if slot in equipment and equipment[slot] is not None:
        return False
    if any(equipped and equipped.get('id') == item_id for equipped in equipment.values()):
        return False
    two_handed = slot in ('main_hand', 'off_hand') and is_two_handed(definition)
    if two_handed and any(equipment.get(hand) for hand in ('main_hand', 'off_hand')):
        return False
    equipment[slot] = item
    if two_handed:
        equipment['off_hand' if slot == 'main_hand' else 'main_hand'] = item
    inventory.remove(item)
    _clamp_current_hp(actor)
    return True


def unequip_item(actor, slot):
    """Clear an equipment slot; the item remains among the actor's carried items."""
    inventory = actor.setdefault('inventory', []) if isinstance(actor, dict) else actor.inventory
    equipment = actor.setdefault('equipment', {name: None for name in EQUIPMENT_SLOTS}) if isinstance(actor, dict) else actor.equipment
    item = equipment.get(slot)
    if not item:
        return False
    item_id = item['id']
    for equipped_slot, equipped_item in list(equipment.items()):
        if equipped_item and equipped_item.get('id') == item_id:
            equipment[equipped_slot] = None
    inventory.append(item)
    _clamp_current_hp(actor)
    return True


def equipment_slots(actor):
    """Return visible slots, including a second ranged slot when eligible."""
    slots = list(EQUIPMENT_SLOTS)
    equipment = actor.get('equipment', {}) if isinstance(actor, dict) else actor.equipment
    ranged_item = equipment.get('ranged')
    if ranged_item and not is_two_handed(item_definition(ranged_item)):
        slots.append('ranged_offhand')
    return slots


def is_two_handed(item_data):
    return item_data.get('hands_required') == 2 or '2h' in item_data.get('tags', [])
