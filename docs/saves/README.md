# Saved characters

The game creates one `<actor-id>.json` file per saved character in this folder.
These files are runtime saves, not mod data. Do not put NPC, class, or item
content here; put that in `data/mods/<your-mod>/` instead.

The save mirrors the actor fields defined by `worldforge/actors/factory.py:Actor`, including
ability scores, class/subclass IDs, equipment, inventory instances, conditions,
and current position. If you hand-edit a save, keep valid JSON and do not
change item instance IDs unless you intend to make a distinct item. The loader
has a few migrations for older actor fields, but it is not a general save-file
validator. Make a backup before experimenting with a save.
