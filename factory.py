from dataclasses import dataclass, field
from classes import EQUIPMENT_ITEMS, RACES, CLASSES
from dice import ability_points
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
    downed: bool = False
    conditions: list = field(default_factory=list)
    active_effects: list = field(default_factory=list)
    known_spells: list = field(default_factory=list)
    known_abilities: list = field(default_factory=list)
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
        if not self.controller:
            self.controller = 'player'


def actor_factory(name, controller='player'):
    return Actor(name, controller=controller)


def npc_factory(name, **actor_data):
    """Create an NPC with the same data model as a player character."""
    actor_data.setdefault('controller', 'ai')
    return Actor(name, **actor_data)

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


def add_equipment_item(actor, name=None, slot=None, details=None, template_id=None):
    """Add a uniquely identified item instance, optionally from the catalog."""
    if template_id:
        template = EQUIPMENT_ITEMS[template_id]
        name = name or template['name']
        slot = slot or template['slot']
        tags = list(template.get('tags', []))
    else:
        tags = []
    item = {
        'id': uuid.uuid4().hex[:12],
        'name': name,
        'slot': slot,
        'tags': tags,
        'rarity': None,
        'rolled_attributes': {},
    }
    if details:
        item.update({key: value for key, value in details.items() if key != 'name'})
    if template_id:
        item['template_id'] = template_id
    actor.inventory.append(item)
    return item


def item_definition(item):
    """Return catalog behavior when available, falling back to legacy data."""
    template_id = item.get('template_id')
    return EQUIPMENT_ITEMS.get(template_id, item)


def equip_item(actor, item_id, slot):
    """Move an inventory item into a compatible equipment slot."""
    item = next((entry for entry in actor.inventory if entry['id'] == item_id), None)
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
        ranged_item = actor.equipment.get('ranged')
        if not ranged_item or is_two_handed(item_definition(ranged_item)):
            return False
    if slot in actor.equipment and actor.equipment[slot] is not None:
        return False
    if any(equipped and equipped.get('id') == item_id for equipped in actor.equipment.values()):
        return False
    two_handed = slot in ('main_hand', 'off_hand') and is_two_handed(definition)
    if two_handed and any(actor.equipment.get(hand) for hand in ('main_hand', 'off_hand')):
        return False
    actor.equipment[slot] = item
    if two_handed:
        actor.equipment['off_hand' if slot == 'main_hand' else 'main_hand'] = item
    actor.inventory.remove(item)
    return True


def unequip_item(actor, slot):
    """Clear an equipment slot; the item remains among the actor's carried items."""
    item = actor.equipment.get(slot)
    if not item:
        return False
    item_id = item['id']
    for equipped_slot, equipped_item in list(actor.equipment.items()):
        if equipped_item and equipped_item.get('id') == item_id:
            actor.equipment[equipped_slot] = None
    actor.inventory.append(item)
    return True


def equipment_slots(actor):
    """Return visible slots, including a second ranged slot when eligible."""
    slots = list(EQUIPMENT_SLOTS)
    ranged_item = actor.equipment.get('ranged')
    if ranged_item and not is_two_handed(item_definition(ranged_item)):
        slots.append('ranged_offhand')
    return slots


def is_two_handed(item_data):
    return item_data.get('hands_required') == 2 or '2h' in item_data.get('tags', [])
