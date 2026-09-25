# Campaigns

A campaign is a mod folder with a `campaign.json` manifest and data records for
its scenarios, arenas, and any added content. The current sample campaign is
`data/mods/demo_slice/`; it remains the default when the game starts.

Select another campaign by setting `WORLDFORGE_CAMPAIGN` to its mod-folder name
before launching:

```sh
WORLDFORGE_CAMPAIGN=my_campaign python main.py
```

In PowerShell:

```powershell
$env:WORLDFORGE_CAMPAIGN = "my_campaign"
python main.py
```

Frozen builds load manifests from the bundled mods and the user's Worldforge
`mods/` folder. Source builds use `data/mods/`.

## Manifest fields

`campaign.json` declares the campaign ID and name, its starting scenario, safe
camp arena, scenario roster, route graph, party cap, enabled systems, and
campaign-tunable rules. Map geometry and exit placement remain in arena data;
the manifest route graph is checked against those exits and controls which
routes the runtime accepts.

```json
{
  "id": "my_campaign",
  "name": "My Campaign",
  "starting_scenario": "village",
  "safe_camp_arena": "camp",
  "scenarios": ["village", "forest"],
  "map_connections": [
    {"from": "village", "exit": "north_gate", "to": "forest",
     "destination_exit": "south_gate"},
    {"from": "forest", "exit": "south_gate", "to": "village",
     "destination_exit": "north_gate"}
  ],
  "party_limit": 4,
  "enabled_systems": {
    "combat": true,
    "travel": true,
    "loot": true,
    "vendors": true,
    "training": true,
    "resting": true,
    "personal_storage": true
  },
  "rules": {
    "combat_trigger_range_feet": 20,
    "combat_join_range_feet": 50,
    "xp_debug_multiplier": 1.0,
    "death_release_xp_penalty_percent": 10,
    "revival_xp_penalty_percent": 2,
    "corpse_despawn_seconds": 3,
    "interaction_range_feet": 5,
    "melee_reach_feet": 5,
    "ranged_attack_disadvantage_distance_feet": 5,
    "thrown_normal_range_feet": 20,
    "thrown_long_range_feet": 60,
    "proficiency_bonus_base": 2,
    "proficiency_bonus_level_step": 4,
    "critical_hit_natural_roll": 20,
    "automatic_miss_natural_roll": 1,
    "level_xp_thresholds": [0, 300, 900, 2700, 6500, 14000, 23000, 34000, 48000, 64000, 85000, 100000, 120000, 140000, 165000, 195000, 225000, 265000, 305000, 355000],
    "attribute_score_milestones": [4, 8, 12, 16, 19],
    "attribute_points_per_milestone": 2,
    "mob_patrol_speed_feet_per_second": 6,
    "mob_patrol_waypoints_feet": [[0, 0], [11, 0], [11, 11], [0, 11]],
    "inn_rest_gold_cost": 10,
    "outdoor_rest_min_distance_feet": 100,
    "outdoor_rest_rate_min_percent": 1,
    "outdoor_rest_rate_max_percent": 5,
    "short_rest_cost_multiplier": 1.0,
    "long_rest_cost_multiplier": 2.0
  }
}
```

The `rules` object is the campaign ruleset hook for scalar gameplay
parameters. Omitted or invalid values use engine defaults. SRD-facing combat
defaults follow SRD 5.2.1 (for example, natural 1/20 attack results and the
proficiency bonus progression); game-specific values such as combat activation,
XP awards, interaction distances, and corpse cleanup are campaign policy.
Content-specific overrides belong on their records when available, such as a
weapon's `ranges` or an object's `interaction_range_feet`.

## Supported campaign rule hooks

| Hook | Meaning | Default |
|---|---|---:|
| `level_xp_thresholds` | Cumulative XP threshold for each character level (index 0 is level 1) | SRD advancement table |
| `attribute_score_milestones`, `attribute_points_per_milestone` | Attribute points granted at those applied levels | `[4, 8, 12, 16, 20]`, 2 |
| `proficiency_bonus_base`, `proficiency_bonus_level_step` | Proficiency bonus formula | 2, 4 |
| `critical_hit_natural_roll`, `automatic_miss_natural_roll` | Natural d20 attack thresholds | 20, 1 |
| `melee_reach_feet`, `ranged_attack_disadvantage_distance_feet` | Fallback reach and point-blank ranged disadvantage distance | 5, 5 |
| `thrown_normal_range_feet`, `thrown_long_range_feet` | Fallback thrown-weapon range when the item has none | 20, 60 |
| `combat_trigger_range_feet`, `combat_join_range_feet` | Demo encounter activation and joining distances | 20, 50 |
| `xp_debug_multiplier` | Multiplier applied to CR-derived encounter XP before party division | 1.0 |
| `death_release_xp_penalty_percent`, `revival_xp_penalty_percent` | Worldforge death/revival wallet adjustments | 10, 2 |
| `corpse_despawn_seconds`, `interaction_range_feet` | Fallback corpse lifetime and nearby interaction range | 3, 5 |
| `mob_patrol_speed_feet_per_second`, `mob_patrol_waypoints_feet` | Default idle patrol speed and loop offsets from each NPC's patrol origin | 6, square loop |
| `inn_rest_gold_cost` | Base inn price before rest-type multiplier | 10 gold |
| `outdoor_rest_min_distance_feet`, `outdoor_rest_rate_min_percent`, `outdoor_rest_rate_max_percent` | Outdoor safety gate and escalating XP base rate | 100, 1, 5 |
| `short_rest_cost_multiplier`, `long_rest_cost_multiplier` | Multipliers applied to both rest prices | 1.0, 2.0 |

Outdoor XP rest prices and paid trainer purchases are Worldforge behavior, not SRD rules. Inns retain their gold price; long rests use the larger configured multiplier for both currencies. The demo may raise `xp_debug_multiplier`
for faster iteration; a standard ruleset uses `1.0`. See
[`experience.md`](tables/experience.md) for per-creature CR rewards.

This is a parameter hook, not a scripting language: adding a new mechanic or
effect type still requires an engine implementation. Existing effect types
remain composable in spell/ability data; the supported vocabulary is listed in
the table references. Avoid treating demo economy values as SRD rules: XP
penalties for death/revival, paid trainer purchases, and outdoor-rest XP costs
are Worldforge extensions and should be removed or replaced when a campaign
wants stricter SRD advancement and rest behavior.

The current engine supports up to eight players. The starting scenario needs a
spawn point per party member, and the safe camp needs at least one bedroll per
member. Content table IDs are merged across mod folders, so use unique IDs
unless intentionally overriding a shared definition.

## Validate the campaign

Run the content validator from the project root before starting the game:

```sh
python -m worldforge.content.validate_campaign
```

It checks scenario and arena references, enemy and loot IDs, required sprite
files, map exits against the manifest route graph, safe-camp capacity, and
starting spawn capacity. It exits nonzero and lists the invalid references when
it finds a problem.

The included `demo_slice` manifest is the working example. It starts at
`first_contact`, links the roadside, forest, market, and inn maps, and enables
all implemented systems.
