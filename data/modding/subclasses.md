# `subclasses.json`

Each top-level key is a subclass ID. The associated class in `classes.json`
must list that ID in its `subclasses` array or creation will never offer it.
Each record has `id`, `class`, `name`, `description`, and `features`.

`features` is a map keyed by level-as-text. Each level contains a `name` and a
short `summary`. The current UI chooses a path at level 1, while these milestone
records describe later levels (currently 3, 6, 10, and 14). They are not
mechanically granted. Keep text original and treat new effects as design notes
until a Python resolver is added.

To add a path: create a unique record, set `class` to the exact class ID, then
add its ID to that class's `subclasses` list. Because a class override replaces
the full class record, copy its full record before changing the list.
