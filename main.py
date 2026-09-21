from factory import starting_hp, actor_factory, save_actors, load_actors, list_saves, delete_actor, assign

def clear():
    print("\033[H\033[J", end="")


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
    start_pool = list(actor.unspent)
    start_abilities = dict(actor.abilities)
    while True:
        open_abilities = list(actor.abilities)
        while actor.unspent:
            draw_assign(actor, open_abilities)
            a = ask_index("stat: ", len(open_abilities))
            r = ask_index("roll: ", len(actor.unspent))
            assign(actor, open_abilities.pop(a), r)
        clear()
        for name, score in actor.abilities.items():
            print(f"{name}: {score}")
        if input("keep this? y/n: ").lower() == "y":
            actor.max_hp = actor.current_hp = starting_hp(actor)
            save_actors(actor)
            return
        
        actor.unspent = list(start_pool)
        actor.abilities = dict(start_abilities)


def pick_char():
    saves = list_saves()
    options = saves + ['new character', 'delete character']
    for i, opt in enumerate(options, 1):
        print(f'{i}.{opt.title()}')

    while True:
        choice = input('pick:')
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            break
        print('not an option')
    picked = options[int(choice) - 1]
    if picked == 'new character':
        name = input('character name:\n').strip().title()
        actor = actor_factory(name)
        save_actors(actor)
        return actor
    if picked == 'delete character':
        delete_char()
        return pick_char()
    return load_actors(picked)


def delete_char():
    saves = list_saves()
    for i, s in enumerate(saves, 1):
        print(f'{i}.{s.title()}')
    choice = input('delete which? (blank to cancel):\n')
    if not (choice.isdigit() and 1 <= int(choice) <= len(saves)):
        return
    target = saves[int(choice) - 1]
    if input(f'Delete {target.title()}? y/n: \n').lower() == 'y':
        delete_actor(target)


actor = pick_char()
if actor.unspent:
    assign_screen(actor)
print(vars(actor))