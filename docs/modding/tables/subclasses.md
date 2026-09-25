# `subclasses.json`

Each top-level key is a subclass ID. The associated class in `classes.json`
must list that ID in its `subclasses` array or creation will never offer it.
Each record has `id`, `class`, `name`, `description`, and `features`. The
selectable built-in roster follows SRD 5.2.1. Former Worldforge subclasses
remain in the table with `selectable: false` for saved-character compatibility.

`features` is a map keyed by level-as-text. A level may contain one feature
object or a list of feature objects. Give each feature a stable `id`, `name`,
and short `summary`; features at the same level are separate trainer purchases.
Character creation chooses the subclass at level 3. Features appear as XP
purchases at the trainer when the character meets their class-level
prerequisite. Purchased entries are recorded on the character sheet. Their
summaries remain descriptive until a matching Python effect resolver is added.
Purchase IDs are `<subclass-id>_<feature-id>`; records without an `id` retain
the legacy `<subclass-id>_<level>` convention.

See [the SRD baseline and implementation limits](../../project/SRD-5.2.1.md)
for attribution and current runtime support.

To add a path: create a unique record, set `class` to the exact class ID, then
add its ID to that class's `subclasses` list. Because a class override replaces
the full class record, copy its full record before changing the list.
