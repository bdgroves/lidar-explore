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
sample_forest.laz  (raw point cloud)
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
   [next: load to Snowflake as GEOGRAPHY]
```

---

## Prerequisites

- **[pixi](https://pixi.sh)** — package/env manager (handles PDAL, GDAL, PROJ
  cleanly on Windows without pip pain)
- **git**
- Optional: [QGIS](https://qgis.org) to visually browse the DEM/CHM GeoTIFFs

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

## Sample results

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

---

## Project structure

```
lidar-explore/
├── data/
│   ├── nuuksio_sample.laz         (committed: 8.9 MB input)
│   ├── nuuksio_tree_truth.csv     (committed: ground truth)
│   ├── nuuksio_dem.tif            (generated, gitignored)
│   ├── nuuksio_chm.tif            (generated, gitignored)
│   ├── nuuksio_detected_trees.csv (generated, gitignored)
│   ├── nuuksio_overview.png       (generated, gitignored)
│   └── nuuksio_detection.png      (generated, gitignored)
├── generate_nuuksio.py            Synthetic sample generator
├── inspect_laz.py                 Point cloud summary
├── build_chm.py                   Earlier CHM script (WA sample era)
├── nuuksio_workflow.py            Main DEM + CHM + viz
├── detect_trees.py                Local-max tree detection + eval
├── pixi.toml                      Environment spec
├── pixi.lock                      Resolved dependency lock
├── README.md
├── CLAUDE_CONTEXT.md              Pickup prompt for continuing with Claude
└── .gitignore
```

---

## What's coming next

The last leg of the original plan: load detected trees into **Snowflake** as
`GEOGRAPHY` points and run spatial queries alongside other warehouse data.
Rough shape:

1. Reproject detected trees from EPSG:3067 (TM35FIN) → EPSG:4326 (WGS84).
   Snowflake `GEOGRAPHY` requires WGS84.
2. Write to a staging table via `write_pandas`.
3. `CREATE TABLE trees AS SELECT height_m, TO_GEOGRAPHY(geom_wkt) AS geom ...`
4. Run spatial queries: `ST_DWITHIN`, tree density per hex, join to other layers.

See `CLAUDE_CONTEXT.md` for a pickup prompt to continue this in a fresh chat.

---

## Getting real Finnish LiDAR

The committed sample is synthetic (fully reproducible, with known ground truth
for evaluation). For real data:

- **MML** (Finnish National Land Survey): `tiedostopalvelu.maanmittauslaitos.fi/tp/kartta`
  - Toggle English (top-right)
  - Product: **"Laser scanning data, 5 p"**
  - Zoom to a forested area, click a 3km × 3km tile, add to cart, checkout
    (free, no account). Download link comes by email.
  - Real tiles are 300 MB – 1 GB. Use PDAL `filters.crop` to slice out a
    ~400m × 400m subset before running these scripts.
- Coordinate system: **EPSG:3067** (ETRS89 / TM35FIN) — same as our synthetic
- Once cropped, the scripts run unchanged.

Alternative: **USGS 3DEP** via `apps.nationalmap.gov/lidar-explorer/` for
Washington / Pacific Northwest data (no email queue, direct S3 downloads).

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
