import pygame

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


def load_spritesheet(path):
    sheet = pygame.image.load(path).convert_alpha()
    columns = sheet.get_width() // CELL_SIZE
    rows = sheet.get_height() // CELL_SIZE
    frames = {}
    for name, (row, count) in ANIMATIONS.items():
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
    frames.setdefault('dead', frames.get('hurt', frames['idle']))
    return frames
