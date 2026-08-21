# lidar-explore

Learning airborne LiDAR point cloud processing with Python + PDAL, applied to
a synthetic Finnish boreal forest modeled on **Nuuksio National Park**
(Haukkalampi area, ~30 km NW of Helsinki).

The workflow mirrors what commercial forestry operators like Weyerhaeuser are
building at scale: from raw point cloud → ground/canopy separation → individual
tree detection → structured features loaded into a data warehouse.

---

## Pipeline

```
nuuksio_sample.laz  (raw point cloud)
        │
        ▼
   inspect_laz.py         → density, extent, classification breakdown
        │
        ▼
  nuuksio_workflow.py     → PDAL pipeline
        │                    ├─ filter to ground   → DEM (bare-earth raster)
        │                    └─ height-above-ground → CHM (canopy heights)
        ▼
  data/nuuksio_dem.tif
  data/nuuksio_chm.tif
        │
        ▼
   detect_trees.py        → local-max on CHM → detected tree tops
        │                    (matched against ground-truth CSV)
        ▼
  data/nuuksio_detected_trees.csv
        │
        ▼
  load_to_snowflake.py    → reproject 3067→4326, TO_GEOGRAPHY,
                             spatial SQL, round-trip visualization
```

---

## Prerequisites

- **[pixi](https://pixi.sh)** — package/env manager (handles PDAL, GDAL, PROJ
  cleanly on Windows without pip pain)
- **git**
- Optional: [QGIS](https://qgis.org) to visually browse the DEM/CHM GeoTIFFs
- Optional: a Snowflake account for the final step

---

## Setup

```powershell
git clone git@github.com:bdgroves/lidar-explore.git
cd lidar-explore

# Solve and install the pixi environment from pixi.lock
pixi install

# Activate the environment
pixi shell
```

You should see `(lidar-explore)` in your prompt. `python`, `pdal`, `gdalinfo`
etc. all resolve inside the env.

---

## Run the workflow

Run these in order from the project root, inside `pixi shell`:

```powershell
# 1. Inspect the sample point cloud
python inspect_laz.py

# 2. Build DEM + CHM + overview visualization
python nuuksio_workflow.py

# 3. Detect individual trees, compare against ground truth
python detect_trees.py

# 4. Load to Snowflake and run spatial queries (see auth section below)
python load_to_snowflake.py
```

Each step writes outputs into `data/` and opens a matplotlib window.

### Regenerating the sample data (optional)

The sample LiDAR file is committed to the repo, but if you want to modify or
regenerate it:

```powershell
python generate_nuuksio.py
```

The generator uses a fixed random seed so output is deterministic.

---

## Detection results

Running `detect_trees.py` on the committed sample gives:

```
Ground truth trees:  450
Detected peaks:      358
True positives:      353
False positives:     5
False negatives:     97

Recall:     78.4%    ← % of real trees found
Precision:  98.6%    ← % of detections that were real
F1:         87.4%

Recall by species:
  spruce:  88.2%   (tall narrow cones — easiest)
  pine  :  73.1%
  birch :  68.3%   (wide flat crowns — hardest)

Height RMSE: 0.44m, bias -0.24m
```

These numbers are in the same range as published Finnish forest inventory
studies using single-return local-max detection.

**Caveat worth stating plainly:** the synthetic stand is sparse — roughly
28 stems/ha at ground truth, where real Finnish boreal forest runs 800–1,500
stems/ha. Crowns barely overlap, which is the easy case for local-max
detection. Expect materially worse recall on real data.

---

## Snowflake integration

`load_to_snowflake.py` reprojects the detections from EPSG:3067 (TM35FIN) to
EPSG:4326 (WGS84, required by Snowflake `GEOGRAPHY`), stages them via
`write_pandas`, builds a typed table with `TO_GEOGRAPHY`, and runs spatial SQL.

Both coordinate systems are kept in the final table on purpose: `GEOGRAPHY` for
true-meter distance operations like `ST_DWITHIN`, and the projected TM35FIN
coords for equal-area grid binning. At 60°N a degree of longitude is about half
a degree of latitude on the ground, so lat/lon cells would be badly non-square.

### Auth

Credentials come from environment variables only — nothing is written to disk.
Key-pair auth is preferred: no password, no MFA prompt, works unattended.

```powershell
$env:SNOWFLAKE_ACCOUNT   = "<ORG>-<ACCOUNT>"
$env:SNOWFLAKE_USER      = "<USER>"
$env:SNOWFLAKE_ROLE      = "ACCOUNTADMIN"
$env:SNOWFLAKE_WAREHOUSE = "COMPUTE_WH"
$env:SNOWFLAKE_DATABASE  = "LIDAR_DB"
$env:SNOWFLAKE_SCHEMA    = "NUUKSIO"

$env:SNOWFLAKE_PRIVATE_KEY_FILE = "C:\Users\<you>\.snowflake\keys\rsa_key.p8"
$env:SNOWFLAKE_PRIVATE_KEY_PWD  = "<passphrase>"   # if key is encrypted
```

Setting `SNOWFLAKE_PRIVATE_KEY_FILE` selects `snowflake_jwt` automatically.
For password auth instead, set `SNOWFLAKE_AUTHENTICATOR=snowflake` and
`SNOWFLAKE_PASSWORD` — but note that an explicitly-set `SNOWFLAKE_AUTHENTICATOR`
overrides the key-file default, which is a common way to get a confusing
`250001 Incorrect username or password`.

Create the target objects once:

```sql
CREATE DATABASE IF NOT EXISTS LIDAR_DB;
CREATE SCHEMA IF NOT EXISTS LIDAR_DB.NUUKSIO;
```

Dry-run mode reprojects and previews without connecting at all:

```powershell
python load_to_snowflake.py --dry-run
```

### Query results

```
1. Height distribution
   6-10m      2 trees, mean 7.9m
   10-20m    37 trees, mean 17.9m
   20-30m   182 trees, mean 25.9m
   30m+     137 trees, mean 33.4m

2. Ten tallest trees — max 36.1m, matching the CHM max

3. Neighbors within 15m (ST_DWITHIN self-join)
   mean 1.43, max 6, 74 trees fully isolated

4. Stem density on a 50m grid
   62 occupied cells, densest 56 stems/ha, mean 23 stems/ha
```

Two readings worth noting. A 400 m plot on a 50 m grid is exactly 64 cells, and
the query found 62 occupied — the two empty cells are the lake, so the SQL
independently recovered the water body. And the height histogram is nearly empty
in the 6–10 m band despite `MIN_HEIGHT_M = 6.0`, which is where the 97 misses
live: the understory is what local-max is failing to see.

---

## Project structure

```
lidar-explore/
├── data/
│   ├── nuuksio_sample.laz              (committed: 8.9 MB input)
│   ├── nuuksio_tree_truth.csv          (committed: ground truth)
│   ├── nuuksio_dem.tif                 (generated, gitignored)
│   ├── nuuksio_chm.tif                 (generated, gitignored)
│   ├── nuuksio_detected_trees.csv      (generated, gitignored)
│   ├── nuuksio_detected_trees_wgs84.csv(generated, gitignored)
│   ├── nuuksio_overview.png            (generated, gitignored)
│   ├── nuuksio_detection.png           (generated, gitignored)
│   └── nuuksio_snowflake.png           (generated, gitignored)
├── generate_nuuksio.py            Synthetic sample generator
├── inspect_laz.py                 Point cloud summary
├── build_chm.py                   Earlier CHM script (WA sample era)
├── nuuksio_workflow.py            Main DEM + CHM + viz
├── detect_trees.py                Local-max tree detection + eval
├── load_to_snowflake.py           GEOGRAPHY load + spatial SQL
├── pixi.toml                      Environment spec
├── pixi.lock                      Resolved dependency lock
├── README.md
├── CLAUDE_CONTEXT.md              Pickup prompt for continuing with Claude
└── .gitignore
```

---

## What's coming next

The synthetic track is complete end to end. Two directions from here:

**1. Better detection — variable-window local max.** The fixed 7 m window is
tuned for the average crown, so it over-smooths short trees and can split wide
birch crowns. Standard fix is a window that scales with CHM height (taller
pixel → wider window). Target: recover some of the 97 understory misses without
giving up the 98.6% precision. This is measurable on the synthetic data because
we have ground truth.

**2. Real data.** The synthetic stand is sparse and clean. Real tiles bring
overlapping crowns, variable pulse density, noise, and files 30–100× larger.
Important: real data has **no ground truth**, so recall and precision become
uncomputable — the question shifts from "how accurate is detection" to "does
the pipeline survive real point clouds." Those are different projects.

---

## Getting real LiDAR

- **USGS 3DEP** (Washington / Pacific Northwest): `apps.nationalmap.gov/lidar-explorer/`
  Direct S3 downloads, no email queue. Also exposes EPT (Entwine Point Tile)
  endpoints that PDAL can read remotely with `readers.ept`, cropping to a small
  AOI without downloading the whole tile. Coordinate systems vary by project —
  usually a State Plane or UTM zone, so the scripts need a CRS parameter rather
  than the hardcoded EPSG:3067.
- **MML** (Finnish National Land Survey): `tiedostopalvelu.maanmittauslaitos.fi/tp/kartta`
  Toggle English (top-right). Product: **"Laser scanning data, 5 p"**. Zoom to a
  forested area, click a 3km × 3km tile, add to cart, checkout (free, no
  account). Download link arrives by email. Tiles are 300 MB – 1 GB — use PDAL
  `filters.crop` to slice a ~400 m × 400 m subset first. Coordinate system is
  EPSG:3067, same as the synthetic, so the scripts run nearly unchanged.

---

## Notes / gotchas

- **Never name a Python file the same as a stdlib module.** Especially
  `inspect.py`, `email.py`, `code.py`. Learned this the hard way — the file is
  `inspect_laz.py` deliberately.
- The `.pixi/` folder is huge and gitignored. `pixi install` recreates it from
  `pixi.lock` on any machine.
- The `filters.hag_nn` PDAL stage requires classified ground points. Our
  synthetic sample is pre-classified. Real MML tiles usually are too, but if
  yours isn't, add a `filters.smrf` stage before `hag_nn` to classify ground.
- `write_pandas` needs **pyarrow**, which conda-forge's
  `snowflake-connector-python` does not always pull in. It is now an explicit
  dependency in `pixi.toml`.
- `write_pandas` defaults to `quote_identifiers=True`, which creates
  case-sensitive quoted column names and makes every later `SELECT` fail
  mysteriously. This repo passes `False` and uses uppercase column names.
- `CURRENT_ACCOUNT()` returns the account *locator*, which is a different string
  from the `ORG-ACCOUNT` identifier used to connect. Both are correct.
