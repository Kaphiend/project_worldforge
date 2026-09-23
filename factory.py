"""Actor and item construction.

Modders normally change JSON templates, not these constructors. Add a field
here only when actors must save, sync, or calculate with new persistent data;
then update the matching loader/UI/rule and migration notes. Equipment slot
legality and the randomized fully geared demo actor are also defined here.
"""
from dataclasses import dataclass, field
from copy import deepcopy
from classes import ABILITIES, EQUIPMENT_ITEMS, RACES, CLASSES, SPELLS, NPCS
from dice import ability_points
from progression import initialize_resources
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
    xp_total: int = 0
    xp_earned_by_level: dict = field(default_factory=dict)
    xp_spent_by_level: dict = field(default_factory=dict)
    xp_rest_spent_by_level: dict = field(default_factory=dict)
    downed: bool = False
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
    spell_points: int = None
    class_resources: dict = field(default_factory=dict)
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
            self.level = sum(max(0, int(entry.get('level', 0))) for entry in self.classes)
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
    """Create a positioned, independently equipped instance from an NPC table entry."""
    if template_id not in NPCS:
        raise KeyError(f"Unknown NPC template: {template_id}")
    instance = deepcopy(NPCS[template_id])
    instance.update(id=f"{template_id}-{uuid.uuid4().hex[:8]}", x=x, y=y,
                    downed=False)
    instance['current_hp'] = int(instance.get('max_hp', 10))
    instance.setdefault('conditions', [])
    instance.setdefault('active_effects', [])
    instance.setdefault('abilities', {})
    instance.setdefault('equipment', {})
    instance.setdefault('inventory', [])
    for item in instance['equipment'].values():
        if item:
            item['id'] = uuid.uuid4().hex[:12]
    return instance

def assign(actor, ability, roll_index):
    actor.abilities[ability] = actor.unspent.pop(roll_index)

def modifier(score):
    return (score - 10)//2

def racial_bonus_data(actor):
    """Return selected ancestry bonus data without interpreting or applying it."""
    if not actor or not actor.race:
        return {}
    race_data = RACES[actor.race]
    result = {'race': dict(race_data.get('bonuses', {}))}
    if actor.subrace:
        result['subrace'] = dict(
            race_data.get('subraces', {}).get(actor.subrace, {}).get('bonuses', {})
        )
    if actor.parent_races:
        result['parents'] = [
            {'race': name, 'bonuses': dict(RACES[name].get('bonuses', {}))}
            for name in actor.parent_races
        ]
    return result

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
    actor.classes = [{'name': class_name, 'level': actor.level}]
    actor.abilities = dict(zip(actor.abilities, ability_points()))
    actor.skills = random.sample(
        CLASSES[class_name].get('skills', []),
        min(CLASSES[class_name].get('skill_choices', 0),
            len(CLASSES[class_name].get('skills', []))))
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

    chest_templates = ['leather', 'chain_shirt', 'scale_mail', 'chain_mail']
    armor_proficiencies = set(actor.armor_prof)
    legal_chest = [template_id for template_id in chest_templates
                   if EQUIPMENT_ITEMS[template_id]['category'] in armor_proficiencies]
    chest_template = random.choice(legal_chest or ['leather'])
    item = add_equipment_item(actor, template_id=chest_template)
    equip_item(actor, item['id'], 'chest')

    main_template = random.choice(['dagger', 'sword_1h', 'axe_1h', 'hammer_1h', 'staff'])
    item = add_equipment_item(actor, template_id=main_template)
    equip_item(actor, item['id'], 'main_hand')
    offhand_template = random.choice(['shield', 'dagger', 'sword_1h', 'axe_1h', 'hammer_1h'])
    item = add_equipment_item(actor, template_id=offhand_template)
    equip_item(actor, item['id'], 'off_hand')

    ranged_template = random.choice(['longbow', 'crossbow'])
    item = add_equipment_item(actor, template_id=ranged_template)
    equip_item(actor, item['id'], 'ranged')
    if ranged_template == 'crossbow':
        item = add_equipment_item(actor, template_id='crossbow')
        equip_item(actor, item['id'], 'ranged_offhand')

    for _ in range(3):
        add_equipment_item(actor, template_id='healing_potion')
    add_equipment_item(actor, template_id='revival_scroll')

    class_spell_ids = [spell_id for spell_id, spell in SPELLS.items()
                       if class_name in spell.get('classes', [])
                       and spell.get('prerequisite_class_level', 1) <= actor.level
                       and (not spell.get('acquisition')
                            or spell.get('acquisition') == 'starting_cantrip')]
    actor.known_spells = class_spell_ids
    actor.prepared_spells = list(class_spell_ids)
    actor.known_abilities = [ability_id for ability_id, ability in ABILITIES.items()
                             if class_name in ability.get('classes', [])
                             and ability.get('prerequisite_class_level', 1) <= actor.level]
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
