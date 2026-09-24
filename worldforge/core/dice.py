"""Dice helpers shared by character creation and combat."""
import random
import re


_DICE_EXPRESSION = re.compile(r"^(\d+)d(\d+)([+-]\d+)?$", re.IGNORECASE)


def roll_dice(expression, *, critical=False):
    """Roll notation such as ``d20``, ``2d6`` or ``1d8+2``.

    Critical hits double the dice count while preserving any flat modifier.
    Returns ``(total, individual_rolls)`` for clear combat-log output.
    """
    match = _DICE_EXPRESSION.fullmatch(str(expression).replace(" ", ""))
    if not match:
        raise ValueError(f"Invalid dice expression: {expression!r}")
    count, sides = int(match.group(1)), int(match.group(2))
    modifier = int(match.group(3) or 0)
    if count < 1 or sides < 2:
        raise ValueError(f"Invalid dice expression: {expression!r}")
    if critical:
        count *= 2
    rolls = [random.randint(1, sides) for _ in range(count)]
    return sum(rolls) + modifier, rolls


def roll_d20(advantage=0):
    """Roll a d20; advantage=1 keeps high, -1 keeps low, otherwise normal."""
    rolls = [random.randint(1, 20) for _ in range(2 if advantage else 1)]
    result = max(rolls) if advantage > 0 else min(rolls) if advantage < 0 else rolls[0]
    return result, rolls


def roll_dx(number, sides):
    """Compatibility helper returning each die result."""
    if number < 0 or sides < 1:
        raise ValueError("Dice count must be nonnegative and sides must be positive")
    return [random.randint(1, sides) for _ in range(number)]


def ability_modifier(score, maximum_score=30):
    """Calculate an ability modifier, ignoring stored score above the cap."""
    score = min(int(score), int(maximum_score))
    return (score - 10) // 2


def scale_dice_count(expression, multiplier):
    """Multiply the dice count in an expression without scaling its flat bonus."""
    match = _DICE_EXPRESSION.fullmatch(str(expression).replace(" ", ""))
    if not match:
        raise ValueError(f"Invalid dice expression: {expression!r}")
    count, sides = int(match.group(1)), int(match.group(2))
    modifier = match.group(3) or ""
    scaled_count = max(1, count * max(1, int(multiplier)))
    return f"{scaled_count}d{sides}{modifier}"


def ability_points():
    """Generate six 4d6-drop-lowest ability scores, with a floor of 8."""
    scores = []
    for _ in range(6):
        rolls = sorted(roll_dx(4, 6))
        scores.append(max(8, sum(rolls[1:])))
    return scores
