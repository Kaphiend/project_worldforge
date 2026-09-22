import pygame
from sprite_sheet import load_spritesheet


def run_game(actor, get_other_state, send_state, self_color=(200, 50, 50), other_color=(50, 50, 200)):
    pygame.init()
    screen = pygame.display.set_mode((800, 600))
    clock = pygame.time.Clock()
    running = True

    player_size = 40
    speed = 5

    sprite_frames = load_spritesheet("Soldier.png")
    frame_duration = 120  # ms per frame

    facing_left = False
    current_anim = 'idle'
    frame_index = 0
    time_since_frame = 0

    other_facing_left = False
    other_anim = 'idle'
    other_frame_index = 0
    other_time_since_frame = 0

    while running:
        dt = clock.tick(60)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        keys = pygame.key.get_pressed()
        moving = False
        if keys[pygame.K_LEFT] or keys[pygame.K_a]:
            actor.x -= speed
            facing_left = True
            moving = True
        if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
            actor.x += speed
            facing_left = False
            moving = True
        if keys[pygame.K_UP] or keys[pygame.K_w]:
            actor.y -= speed
            moving = True
        if keys[pygame.K_DOWN] or keys[pygame.K_s]:
            actor.y += speed
            moving = True

        new_anim = 'walk' if moving else 'idle'
        if new_anim != current_anim:
            current_anim = new_anim
            frame_index = 0
            time_since_frame = 0

        time_since_frame += dt
        if time_since_frame >= frame_duration:
            time_since_frame = 0
            frame_index = (frame_index + 1) % len(sprite_frames[current_anim])

        sprite = sprite_frames[current_anim][frame_index]
        if facing_left:
            sprite = pygame.transform.flip(sprite, True, False)

        send_state(actor.x, actor.y, current_anim, facing_left)
        other_x, other_y, recv_anim, recv_facing = get_other_state()

        if recv_anim != other_anim:
            other_anim = recv_anim
            other_frame_index = 0
            other_time_since_frame = 0
        other_facing_left = recv_facing

        other_time_since_frame += dt
        if other_time_since_frame >= frame_duration:
            other_time_since_frame = 0
            other_frame_index = (other_frame_index + 1) % len(sprite_frames[other_anim])

        other_sprite = sprite_frames[other_anim][other_frame_index]
        if other_facing_left:
            other_sprite = pygame.transform.flip(other_sprite, True, False)

        screen.fill((20, 20, 20))
        pygame.draw.circle(screen, (110, 100, 90), (700, 500), 20)
        screen.blit(sprite, (actor.x, actor.y))
        screen.blit(other_sprite, (other_x, other_y))
        pygame.display.flip()

    pygame.quit()