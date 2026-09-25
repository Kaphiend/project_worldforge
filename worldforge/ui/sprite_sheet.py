"""Load the project's fixed-cell character sheets into animation frame lists.

Current cells are 100 by 100 pixels. Update both row maps below when art uses
a different row order; keeping the returned keys (idle/walk/attack1/attack2/
ranged/hurt/dead) stable lets gameplay use new art without gameplay edits.
"""
import pygame
from worldforge.core.runtime_paths import asset_path

CELL_SIZE = 100

ANIMATIONS = {
    'idle': (0, 6),
    'walk': (1, 8),
    'attack1': (2, 6),
    'attack2': (3, 6),
    'ranged': (4, 9),
    'hurt': (5, 4),
    'dead': (6, 4),
}

# The included Orc sheet is a compact six-row variant: it omits a dedicated
# ranged pose, placing hurt and death in rows five and six instead.
SIX_ROW_ANIMATIONS = {
    'idle': (0, 6),
    'walk': (1, 8),
    'attack1': (2, 6),
    'attack2': (3, 6),
    'hurt': (4, 4),
    'dead': (5, 4),
}

# The supplied wizard reference is an annotated JPEG rather than a raw sheet.
# Its extracted rows contain the distinct frames visible in the image.
WIZARD_ANIMATIONS = {
    'idle': (0, 6),
    'walk': (1, 8),
    'attack1': (2, 5),
    'attack2': (3, 5),
    'ranged': (4, 2),
    'hurt': (5, 3),
    'dead': (6, 3),
}

PALADIN_ANIMATIONS = {
    'idle': (0, 6),
    'walk': (1, 8),
    'attack1': (2, 5),
    'attack2': (3, 6),
    'ranged': (4, 4),
    'hurt': (5, 4),
    'dead': (6, 4),
}

ROSTER_FRAME_COUNTS = {
    'Sorcerer.png': (8, 8, 6, 6, 5, 3, 4),
    'Ranger.png': (8, 8, 5, 6, 7, 3, 4),
    'Monk.png': (8, 8, 6, 7, 7, 3, 4),
    'Druid.png': (8, 8, 7, 6, 7, 3, 4),
    'Warlock.png': (8, 8, 5, 6, 5, 3, 4),
    'Rogue.png': (8, 8, 4, 7, 5, 3, 4),
    'Fighter.png': (8, 8, 5, 6, 7, 3, 4),
    'Cleric.png': (8, 8, 7, 6, 6, 3, 4),
    'Barbarian.png': (8, 8, 7, 6, 6, 3, 4),
    'Bard.png': (8, 8, 6, 6, 6, 3, 4),
}
_ANIMATION_NAMES = ('idle', 'walk', 'attack1', 'attack2', 'ranged', 'hurt', 'dead')
ROSTER_ANIMATIONS = {
    filename: {name: (row, count)
               for row, (name, count) in enumerate(zip(_ANIMATION_NAMES, counts))}
    for filename, counts in ROSTER_FRAME_COUNTS.items()
}

GOBLIN_ANIMATIONS = {
    'idle': (0, 7),
    'walk': (1, 7),
    'attack1': (2, 7),
    'attack2': (3, 5),
    'ranged': (4, 6),
    'hurt': (5, 3),
    'dead': (6, 4),
}


def load_spritesheet(path):
    sheet = pygame.image.load(str(asset_path(path))).convert_alpha()
    columns = sheet.get_width() // CELL_SIZE
    rows = sheet.get_height() // CELL_SIZE
    frames = {}
    normalized_path = path.replace('\\', '/')
    filename = normalized_path.rsplit('/', 1)[-1]
    if filename == 'Wizard.png':
        layout = WIZARD_ANIMATIONS
    elif filename == 'Paladin.png':
        layout = PALADIN_ANIMATIONS
    elif filename == 'Goblin.png':
        layout = GOBLIN_ANIMATIONS
    elif filename in ROSTER_ANIMATIONS:
        layout = ROSTER_ANIMATIONS[filename]
    else:
        layout = ANIMATIONS if rows >= 7 else SIX_ROW_ANIMATIONS
    for name, (row, count) in layout.items():
        if row >= rows:
            continue
        row_frames = []
        for col in range(min(count, columns)):
            rect = pygame.Rect(col * CELL_SIZE, row * CELL_SIZE, CELL_SIZE, CELL_SIZE)
            row_frames.append(sheet.subsurface(rect).copy())
        frames[name] = row_frames
    # Sheets can omit trailing animation rows or frames. Keep every animation
    # usable by falling back to the nearest available idle frame.
    if not frames.get('idle'):
        frames['idle'] = [sheet.subsurface((0, 0, CELL_SIZE, CELL_SIZE)).copy()]
    frames.setdefault('walk', frames['idle'])
    frames.setdefault('attack1', frames['idle'])
    frames.setdefault('attack2', frames['attack1'])
    frames.setdefault('ranged', frames['attack2'])
    frames.setdefault('hurt', frames['idle'])
    frames.setdefault('dead', frames.get('hurt', frames['idle']))
    return frames
