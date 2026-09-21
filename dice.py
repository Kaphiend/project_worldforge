import random

def roll_dx(number, sides):
    rolls = []
    for roll in range(number):
        roll = random.randint(1,sides)
        rolls.append(roll)
    return rolls


def ability_points():
    ability_rolls = []
    for score in range(0,6):
        score = roll_dx(4,6)
        score.sort()
        top = score[1:]
        final = max(8,sum(top))
        ability_rolls.append(final)
    return ability_rolls
