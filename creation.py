from classes import CLASSES, RACES
from factory import assign, starting_hp, save_actors, apply_race_bonus, starting_hp

def clear():
    print("\033[H\033[J", end="")


def pick_from(prompt, options):
    names = list(options)
    for i, n in enumerate(names, 1):
        print(f'{i}.{n.title()}')
    return names[ask_index(prompt, len(names))
                 ]

def ask_index(prompt, length):
    while True:
        choice = input(prompt)
        if choice.isdigit() and 1 <= int(choice) <= length:
            return int(choice) - 1
        print('not an option')


def draw_assign(actor, open_abilities):
    clear()
    print("rolls:", actor.unspent)
    for i, a in enumerate(open_abilities, 1):
        print(f"{i}. {a}: {actor.abilities[a]}")


def assign_screen(actor):
    clear()
    actor.race = pick_from('race:', RACES)
    clear()
    actor.char_class = pick_from('class:', CLASSES)
    start_pool = list(actor.unspent)
    start_abilities = dict(actor.abilities)
    while True:
        open_abilities = list(actor.abilities)
        while actor.unspent:
            draw_assign(actor, open_abilities)
            a = ask_index("stat: ", len(open_abilities))
            r = ask_index("roll: ", len(actor.unspent))
            assign(actor, open_abilities.pop(a), r)
        apply_race_bonus(actor)
        clear()
        for name, score in actor.abilities.items():
            print(f"{name}: {score}")
        if input("keep this? y/n: ").lower() == "y":
            actor.max_hp = actor.current_hp = starting_hp(actor)
            save_actors(actor)
            return
        
        actor.unspent = list(start_pool)
        actor.abilities = dict(start_abilities)