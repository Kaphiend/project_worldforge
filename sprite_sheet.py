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
    frames = {}
    for name, (row, count) in ANIMATIONS.items():
        row_frames = []
        for col in range(count):
            rect = pygame.Rect(col * CELL_SIZE, row * CELL_SIZE, CELL_SIZE, CELL_SIZE)
            row_frames.append(sheet.subsurface(rect).copy())
        frames[name] = row_frames
    return frames