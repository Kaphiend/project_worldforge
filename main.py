from factory import actor_factory, save_actors, load_actors, list_saves, delete_actor
from creation import assign_screen


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