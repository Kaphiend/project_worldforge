"""Keyboard and submission behavior for the in-world chat entry."""
import time

import pygame


def handle_chat_event(event, chat_text, actor, local_animation, facing_left,
                      send_state, submit):
    """Handle one event while chat is open; return (handled, text, speech)."""
    if event.type == pygame.TEXTINPUT:
        return True, (chat_text + event.text)[:160], None
    if event.type != pygame.KEYDOWN:
        return False, chat_text, None

    if event.key == pygame.K_ESCAPE:
        pygame.key.stop_text_input()
        return True, "", None
    if event.key == pygame.K_BACKSPACE:
        return True, chat_text[:-1], None
    if event.key not in (pygame.K_RETURN, pygame.K_KP_ENTER):
        return False, chat_text, None

    message = chat_text.strip()
    if not message:
        pygame.key.stop_text_input()
        return True, "", None

    bubble_text = message
    is_emote = message.lower().startswith("/act ")
    if is_emote:
        emote = message[5:].strip()
        bubble_text = f"{actor.name} acts {emote}" if emote else ""
    speech = None
    if bubble_text:
        speech = {"text": bubble_text, "expires_at": time.time() + 2.5}
        send_state(actor.x, actor.y, local_animation["anim"], facing_left,
                   vars(actor), speech)
        submit({"type": "chat", "text": message})
    pygame.key.stop_text_input()
    return True, "", speech
