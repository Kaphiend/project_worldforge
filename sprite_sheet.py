"""Load the project's fixed-cell character sheets into animation frame lists.

Current cells are 100 by 100 pixels. Update both row maps below when art uses
a different row order; keeping the returned keys (idle/walk/attack1/attack2/
ranged/hurt/dead) stable lets gameplay use new art without gameplay edits.
"""
import pygame
from runtime_paths import asset_path

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


def load_spritesheet(path):
    sheet = pygame.image.load(str(asset_path(path))).convert_alpha()
    columns = sheet.get_width() // CELL_SIZE
    rows = sheet.get_height() // CELL_SIZE
    frames = {}
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
