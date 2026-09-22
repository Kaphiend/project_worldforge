from armor import HeavyArmor, Unarmored

CLASSES = {
    'fighter': {
        'hit_die': 10,
        'saves': ['strength', 'constitution'],
        'armor_prof': ['light', 'medium', 'heavy', 'shields'],
        'weapon_prof': ['simple', 'martial'],
        'skills': ['acrobatics', 'athletics', 'intimidation', 'perception'],
        'starting_gear': {
            'armor': {'name': 'chain mail', 'category': 'heavy', 'base_ac': 16},
            'weapons': ['longsword', 'shield'],
        },
    },
    'wizard': {
        'hit_die': 6,
        'saves': ['intellect', 'wisdom'],
        'armor_prof': [],
        'weapon_prof': ['simple'],
        'skills': ['arcana', 'history', 'investigation', 'insight'],
        'starting_gear': {
            'armor': {'name': 'unarmored', 'category': 'unarmored', 'base_ac': 10},
            'weapons': ['dagger'],
        },
    },
}


RACES = {
    'human': {
    'bonuses': {},
    'size': 'medium',
    'speed': 30,
    },
    'dwarf': {
    'bonuses': {'constitution': 2},
    'size': 'medium',
    'speed': 25,
    },
    'elf': {
    'bonuses': {'dexterity': 2},
    'size': 'medium',
    'speed': 30,
    },
     }

