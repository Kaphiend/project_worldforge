"""Character creation state and rules, independent of the Pygame screen."""
from worldforge.content.classes import ABILITIES, RACES, CLASSES, SPELLS, skill_options
from worldforge.actors.factory import (
    actor_factory,
    apply_class_proficiencies,
    apply_starting_gear,
    assign,
    class_ability_priorities,
    starting_hp,
    random_fully_geared_actor,
)
from worldforge.core.storage import lock_actor, load_actor, save_actor, unlock_actor
from worldforge.core.progression import initialize_resources


class CharacterCreationFlow:
    def __init__(self):
        self.stage = "menu"
        self.actor = None
        self.ability_order = []
        self.current_ability_index = 0
        self.parent_selection = 0

    def begin_character(self, name):
        name = name.strip()
        if not name:
            return False
        self.actor = actor_factory(name.title())
        self.ability_order = list(self.actor.abilities)
        self.current_ability_index = 0
        self.stage = "race"
        return True

    def go_back(self):
        """Return to the previous creation step without losing current picks."""
        previous = {
            "quick_class": "menu",
            "quick_name": "quick_class",
            "name": "menu",
            "race": "name",
            "parents": "race",
            "subrace": "race",
            "class": ("parents" if self.actor and self.actor.race == "half-breed"
                      else "subrace" if self.actor and RACES.get(
                          self.actor.race, {}).get("subraces") else "race"),
            "subclass": "class",
            "skills": ("subclass" if self.actor and CLASSES.get(
                self.actor.char_class, {}).get("subclasses") else "class"),
            "abilities": ("skills" if self.actor and CLASSES.get(
                self.actor.char_class, {}).get("skill_choices", 0) else
                "subclass" if self.actor and CLASSES.get(
                    self.actor.char_class, {}).get("subclasses") else "class"),
            "avatar": "menu",
            "done": "menu",
        }
        if self.stage in ("avatar", "done") and self.actor:
            unlock_actor(self.actor.id)
        self.stage = previous.get(self.stage, "menu")
        if self.stage == "menu" and self.actor and self.actor.id:
            # A completed or loaded character is saved; an unfinished one has
            # not been committed yet and can be discarded safely.
            if self.actor.avatar:
                unlock_actor(self.actor.id)
            self.actor = None

    def select_race(self, race):
        if race in RACES and RACES[race].get('selectable', True):
            if self.actor.race != race:
                self.actor.subrace = None
                self.actor.parent_races = []
                self.actor.char_class = None
                self.actor.classes = []
                self.actor.subclass = None
                self.actor.skills = []
            self.actor.race = race

    def confirm_race(self):
        if not self.actor or not self.actor.race:
            return
        race_data = RACES[self.actor.race]
        if race_data.get('half_breed'):
            self.stage = 'parents'
        elif race_data.get('subraces'):
            self.stage = 'subrace'
        else:
            self.stage = 'class'

    def select_subrace(self, subrace):
        options = RACES.get(self.actor.race, {}).get('subraces', {})
        if subrace in options:
            self.actor.subrace = subrace

    def confirm_subrace(self):
        if self.actor and self.actor.subrace:
            self.stage = 'class'

    def select_parent(self, index, race):
        valid_parents = {
            name for name, data in RACES.items()
            if not data.get('half_breed') and data.get('selectable', True)
        }
        if self.actor and self.actor.race == 'half-breed' and index in (0, 1) and race in valid_parents:
            parents = list(self.actor.parent_races[:2])
            parents.extend([''] * (2 - len(parents)))
            parents[index] = race
            self.actor.parent_races = parents

    def focus_parent(self, index):
        if index in (0, 1):
            self.parent_selection = index

    def select_focused_parent(self, race):
        self.select_parent(self.parent_selection, race)

    def confirm_parents(self):
        if self.actor and len(self.actor.parent_races) == 2 and all(self.actor.parent_races):
            self.stage = 'class'

    def select_class(self, char_class):
        if char_class in CLASSES:
            if self.actor.char_class != char_class:
                self.actor.subclass = None
                self.actor.skills = []
            self.actor.char_class = char_class
            self.actor.classes = [{'name': char_class, 'level': 1}]
            self.actor.level = 1

    def confirm_class(self):
        if self.actor and self.actor.char_class:
            apply_class_proficiencies(self.actor)
            self.ability_order = class_ability_priorities(self.actor.char_class)
            if CLASSES[self.actor.char_class].get('subclasses'):
                self.stage = 'subclass'
            else:
                self.stage = 'skills' if CLASSES[self.actor.char_class].get('skill_choices', 0) else 'abilities'

    def select_subclass(self, subclass_id):
        if (self.actor and subclass_id in
                CLASSES.get(self.actor.char_class, {}).get('subclasses', [])):
            self.actor.subclass = subclass_id

    def confirm_subclass(self):
        if self.actor and self.actor.subclass:
            self.stage = 'skills' if CLASSES[self.actor.char_class].get('skill_choices', 0) else 'abilities'

    def select_skill(self, skill):
        if not self.actor:
            return
        # skill_options() expands classes.json's ["any"] sentinel (bard) to
        # the full skill list -- using the raw CLASSES[...]['skills'] list
        # here caps options at 1 entry and skill_choices can never be met.
        options = skill_options(self.actor.char_class)
        limit = int(CLASSES[self.actor.char_class].get('skill_choices', 0))
        if skill in self.actor.skills:
            self.actor.skills.remove(skill)
        elif skill in options and len(self.actor.skills) < limit:
            self.actor.skills.append(skill)

    def confirm_skills(self):
        if self.actor and len(self.actor.skills) == int(
                CLASSES[self.actor.char_class].get('skill_choices', 0)):
            self.stage = 'abilities'

    def assign_roll(self, roll_index):
        if self.stage != "abilities" or self.current_ability_index >= len(self.ability_order):
            return
        ability = self.ability_order[self.current_ability_index]
        if not 0 <= roll_index < len(self.actor.unspent):
            return
        assign(self.actor, ability, roll_index)
        self.current_ability_index += 1
        if self.current_ability_index == len(self.ability_order):
            self._finish_new_character()

    def _finish_new_character(self):
        self.actor.max_hp = starting_hp(self.actor)
        self.actor.current_hp = self.actor.max_hp
        apply_starting_gear(self.actor)
        class_name = self.actor.char_class
        self.actor.known_spells = [
            spell_id for spell_id, spell in SPELLS.items()
            if class_name in spell.get('classes', [])
            and spell.get('prerequisite_class_level', 1) <= self.actor.level
            and (not spell.get('acquisition')
                 or spell.get('acquisition') == 'starting_cantrip')
        ]
        self.actor.known_abilities = [
            ability_id for ability_id, ability in ABILITIES.items()
            if class_name in ability.get('classes', [])
            and ability.get('acquisition') != 'trainer_purchase'
            and ability.get('prerequisite_class_level', 1) <= self.actor.level
        ]
        # Starting cantrips are ready by default. Leveled spells are learned
        # from trainers and selected explicitly within the class prep limit.
        self.actor.prepared_spells = [
            spell_id for spell_id in self.actor.known_spells
            if SPELLS[spell_id].get("acquisition") == "starting_cantrip"
        ]
        initialize_resources(vars(self.actor), refill=True)
        self.stage = 'avatar'

    def choose_avatar(self, avatar):
        if self.stage != 'avatar' or avatar not in {
                'asset_pack/Orc.png', 'asset_pack/Soldier.png'}:
            return False
        self.actor.avatar = avatar
        save_actor(self.actor)
        lock_actor(self.actor.id)
        self.stage = "done"
        return True

    def create_random_fully_geared(self, avatars=None, class_name=None, name=None):
        if class_name not in CLASSES:
            return False
        if not name or not name.strip():
            return False
        self.actor = random_fully_geared_actor(name=name.strip(), avatars=avatars,
                                               class_name=class_name)
        save_actor(self.actor)
        lock_actor(self.actor.id)
        self.stage = 'done'
        return True

    def load_existing(self, actor_id):
        self.actor = load_actor(actor_id)
        self.actor.avatar = getattr(self.actor, 'avatar', 'asset_pack/Soldier.png')
        lock_actor(self.actor.id)
        self.stage = "done"
