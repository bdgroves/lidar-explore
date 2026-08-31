# lidar_forest — dbt models over the Nuuksio stand data

Transforms `LIDAR_DB.NUUKSIO.STANDS` (1,840 Finnish Forest Centre stand polygons
with CHM detection results) into analysis marts, and encodes the project's
hard-won corrections as tests that fail the build.

## Setup

```powershell
pixi add dbt-snowflake
# copy profiles_example.yml into ~/.dbt/profiles.yml, then:
$env:SNOWFLAKE_PRIVATE_KEY_PWD = "..."
dbt deps
dbt build          # run + test in dependency order
```

## Lineage

```
source: nuuksio.stands
        └─ stg_stands              typed passthrough, no filtering
             └─ int_stands_comparable    defines the population ONCE
                  ├─ fct_detection_by_class
                  ├─ fct_height_estimators
                  ├─ fct_benchmark_pools
                  └─ fct_volume_by_class
```

## Why these models exist

Each one closes a specific way this analysis produced a wrong number.

**`int_stands_comparable`** — the same statistic was once published on two
different subsets (n=1,295 and n=1,706) in the same repository. The population
is now defined once, with each exclusion named and flagged rather than applied
silently at the edge of a script.

**`fct_height_estimators`** — two defensible definitions of "mean canopy height"
from the same raster differ by five metres and fall on opposite sides of the
inventory value. The mart reports both, always, so a number can never be quoted
without its estimator.

**`fct_benchmark_pools`** — a harvest benchmark once reported 1.37x lift by using
the wrong denominator. This model shows every candidate pool side by side and
prints a saturation verdict, so a benchmark that cannot demonstrate skill says so
on its face.

## Tests

Generic tests cover uniqueness, nulls and accepted ranges. The four singular
tests encode physical and methodological expectations:

| test | what it catches |
|---|---|
| `assert_height_estimators_bracket` | crossed columns — a QGIS join once shifted values by two fields and rendered a plausible map |
| `assert_recovery_rises_with_maturity` | detection picking up noise rather than crowns |
| `assert_recovery_within_physical_bounds` | recovery above 100% (noise) or below 2% (broken) |
| `assert_no_silent_population_drift` | a filter change quietly halving the sample |

## Variables

| var | default | why |
|---|---|---|
| `max_obs_gap_years` | 6 | inventory spans 1999–2024; a 21-year gap reads as detection error. Tightening this from unlimited raised height correlation from 0.907 to 0.962 |
| `min_stand_ha` | 0.3 | below this, per-stand statistics are too noisy |
| `mature_class` | `'04'` | *uudistuskypsä*, regeneration-mature |

Sensitivity is testable: `dbt build --vars '{max_obs_gap_years: 3}'`.

## Attribution

Forest resource data: **Suomen metsäkeskus / Finnish Forest Centre**, CC BY 4.0.
