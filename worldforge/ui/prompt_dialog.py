"""Shared geometry for the map's Yes/No interaction prompt."""
import pygame


def interaction_prompt_rects(screen_size):
    width, height = 460, 152
    panel = pygame.Rect(0, 0, width, height)
    panel.center = (screen_size[0] // 2, screen_size[1] // 2)
    yes = pygame.Rect(panel.x + 112, panel.bottom - 42, 106, 30)
    no = pygame.Rect(panel.x + 242, panel.bottom - 42, 106, 30)
    return panel, yes, no
