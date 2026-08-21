# lidar-explore

Learning airborne LiDAR and canopy-height processing with Python + PDAL, from a
synthetic Finnish boreal forest through to real national data validated against
the Finnish Forest Centre's forest inventory.

The workflow mirrors what commercial forestry operators are building at scale:
raw point cloud → ground/canopy separation → individual tree detection →
structured features in a warehouse → stand-level management decisions.

---

## What this project actually establishes

Four results, in the order found. Each corrected something believed earlier,
which is the point.

**1. Local-max detection scores well on sparse synthetic forest, and the score
is partly an artifact.** 78.4% recall, 98.6% precision on the synthetic sample —
but that stand is ~28 stems/ha, so crowns barely overlap. Thinning the cloud to
0.5 p/m² *raised* recall to 81.8% while precision fell to 92.0% and height RMSE
quadrupled from 0.44 m to 1.63 m. A sparse CHM has more empty cells than filled
ones; nodata-as-zero creates spurious local maxima, some of which land near real
trees. **Recall is gameable by noise; height error is not.** Height RMSE is the
honest density metric.

**2. Coarser CHM cells cost more than sparse points.** A 2 m CHM scored worse
than 1 m at every density tested, and birch — wide, flat crowns — degraded
worst. Resolution was the binding constraint, not point count.

**3. Cross-epoch canopy bias is invisible to ground calibration.** On real
Forest Centre CHMs for 2008/2015/2020, the bare-ground median offset was
+0.00 m for every epoch pair — perfect ground agreement. But binning change on
an *independent* third epoch (to remove regression to the mean) showed 2008→2020
gains nearly flat across every height band, +0.25 to +0.32 m/yr including 28 m+
stands that should be near-asymptotic. A constant gain regardless of tree size
is an additive offset: the 2008 flight under-measured **canopy** while measuring
**ground** correctly. The 2015→2020 pair has the opposite problem, showing
negative increment in mature bands — standing forest does not shrink.
**Neither pair supports an absolute growth rate.** Relative ranking survives an
additive bias; absolute current-annual-increment does not.

**4. Detection measures height well and counts stems poorly — quantified
against a national inventory.** Across real stands on sheet L4132D:

| | value |
|---|---|
| stem recovery, median | **16.3%** of inventory stems/ha |
| by class: 02 young / 03 advanced / 04 mature | 12% / 15% / **17%** |
| detected-stem height vs inventory mean | **+1.19 m**, r = **0.962** |
| whole-pixel CHM height vs inventory mean | −3.95 m, r = 0.901 |

All on the same 1,295 stands: private forest, usable development class, and
inventory observed within 6 years of the CHM epoch.

Recovery rises monotonically with maturity — fewer, larger, better-separated
crowns are easier to resolve. And the estimator matters: mean over *detected
stems* brackets inventory mean from above (crown apexes), while mean over *all
pixels* sits below it because it averages in canopy gaps. Same raster, opposite
sign, and the stem-based estimator correlates better.

Filtering to vintage-matched inventory measurably improved agreement: the
detected-stem correlation rose from 0.907 on all comparable stands to 0.962
once stands measured more than 6 years from the CHM epoch were dropped.

**Plus one clean negative result.** Harvest ranking was benchmarked against
5,059 real cutting proposals. Once stands are filtered to development class 04
(*uudistuskypsä*, regeneration-mature), **471 of 472 eligible stands were
already proposed for cutting** — base rate 100%, lift 1.00×. The forester's own
maturity call determines the list; the CHM adds no discriminating power on top.
Reported because it is true, not because it flatters the method.

---

## Pipeline

```
SYNTHETIC TRACK (ground truth known)
  nuuksio_sample.laz
        ├─ inspect_laz.py        density, extent, classification
        ├─ nuuksio_workflow.py   PDAL: ground → DEM, hag_nn → CHM
        ├─ detect_trees.py       local-max detection, scored vs truth
        ├─ density_study.py      thin the cloud, measure error vs density
        └─ load_to_snowflake.py  GEOGRAPHY table + spatial SQL

REAL TRACK (Finnish Forest Centre open data)
  fetch_metsakeskus.py     index-driven CHM tile download + crop
  chm_change.py            multi-epoch change, bias diagnostics
  stand_validate.py        detection vs inventory, targeting vs plan
  harvest_targeting.py     stand ranking with retention-tree selection
  make_maps.py             publication figures
```

---

## Setup

```powershell
git clone git@github.com:bdgroves/lidar-explore.git
cd lidar-explore
pixi install
pixi shell
```

Requires [pixi](https://pixi.sh) — handles PDAL, GDAL, PROJ, geopandas and
rasterio cleanly on Windows. Optional: QGIS for browsing rasters, Snowflake for
the warehouse step.

---

## Synthetic track

```powershell
python inspect_laz.py       # 1,034,754 pts over 405 x 403 m = 6.34 p/m2
python nuuksio_workflow.py  # DEM + CHM + overview
python detect_trees.py      # scored against 450 known trees
python density_study.py     # error vs point density
```

```
Ground truth 450   detected 358   TP 353   FP 5   FN 97
Recall 78.4%   Precision 98.6%   F1 87.4%   height RMSE 0.44m
spruce 88.2%   pine 73.1%   birch 68.3%
```

Density study, 1 m CHM:

```
 p/m2   detected  recall  precision  height RMSE
 0.49       400    81.8%     92.0%       1.63m
 1.05       366    78.9%     97.0%       1.14m
 2.10       361    79.1%     98.6%       0.76m
 3.16       362    78.2%     97.2%       0.60m
 6.31       358    78.4%     98.6%       0.44m
```

Read the RMSE column, not recall. See result 1.

**Caveat carried throughout:** the synthetic stand is ~28 stems/ha. Real managed
Finnish forest on sheet L4132D measures ~496 stems/ha median and ~444 in mature
class-04 stands. An earlier draft cited 800–1,500 — that range applies to young
unthinned stands, not forest at rotation age.

---

## Real data: Finnish Forest Centre

Two open datasets, CC BY 4.0, no registration, no API key.

**Latvusmalli** — 1 m canopy height model, 6 km × 6 km tiles, EPSG:3067,
derived from the licensed 5 p laser data. `fetch_metsakeskus.py` reads the
published GeoPackage index (download URL + precomputed stats per tile).

```powershell
python fetch_metsakeskus.py --sheet L4132D --year all --list
python fetch_metsakeskus.py --sheet L4132D --year 2020 --crop 364000 6685000 365000 6686000
```

**Metsävarakuviot** — stand polygons with inventory, proposed operations and
restrictions. Relational GeoPackage, ten tables.

Note: **MML "Laser scanning data 5 p" is not free** — it needs payment and
Finnish strong authentication, not practically available to non-residents. The
free 0.5 p product is 13× sparser than this project's synthetic sample. The
Forest Centre CHM is the better free route, being derived from the licensed data.

### Schema gotchas that silently corrupt results

* `treestand.type`: **1 = observed, 2 = projected to 2026, 3 = projected to
  2036.** Joining a projection compares your raster to a simulation.
* `treestandsummary` exists **only for types 2 and 3**. Observed inventory is in
  `treestratum`, per species, and `stemcount` there is null — derive density as
  `N = G / (π/4 · d²)` from basal area and mean diameter.
* Observation dates span **1999–2024**. A 2020 raster against a 1999
  measurement reads as detection error when it is two decades of growth.
  `stand_validate.py` filters to ±6 years (219 of 1,779 stands excluded).
* Attributes for classes **A0 and T1 are documented as unusable** by the
  producer. Dropped, not silently compared.
* Metsävarakuviot covers **private** forest only — 2,165 ha of the 3,600 ha
  sheet. State land including Nuuksio National Park is absent, so absence is
  treated as a **whitelist block**. A blacklist would fail open on any gap.

### Development classes (kehitysluokka)

| code | Finnish | English |
|---|---|---|
| A0 | aukea | open / clearcut |
| T1 | pieni taimikko | seedlings ≤1.3 m |
| T2 | varttunut taimikko | advanced seedlings >1.3 m |
| Y1 | ylispuustoinen taimikko | seedlings under overstory |
| 02 | nuori kasvatusmetsikkö | young thinning stand |
| 03 | varttunut kasvatusmetsikkö | advanced thinning stand |
| 04 | uudistuskypsä metsikkö | **regeneration-mature** |

Class 04 replaced an earlier Chapman-Richards age model. A forester's own
maturity judgement beats inverting a growth curve with an assumed site index
(which also clamped at age 181 for any stand taller than the assumed H100).

---

## Change detection

```powershell
python chm_change.py --all-pairs --by-height --no-viz
python chm_change.py --a 2008 --b 2020 --bin-on 2015 --by-height
```

Two diagnostics matter more than the change map itself:

**Ground offset** — median difference over pixels bare in the earlier epoch.
Non-zero means systematic processing bias. All three pairs returned +0.00 m,
and told us nothing about canopy.

**Height-stratified increment** — real height growth declines steeply with tree
size. Gains flat across bands, or rising with height, indicate bias not biology.
Use `--bin-on` with a third epoch to define bins; otherwise regression to the
mean drags the top bands down and can invert the conclusion. It did, in an
earlier run: the pair that looked textbook-clean was the biased one.

---

## Stand validation

```powershell
python stand_validate.py --year 2020 --top 15
```

Joins detection to stand polygons, compares against observed inventory, scores
ranking against the management plan. Writes `data/stand_validation.csv`.

---

## Snowflake

`load_to_snowflake.py` reprojects EPSG:3067 → 4326, stages via `write_pandas`,
builds a `TO_GEOGRAPHY` table, runs spatial SQL.

Both coordinate systems are kept deliberately: `GEOGRAPHY` for true-metre
`ST_DWITHIN`, projected TM35FIN for equal-area grid binning. At 60°N a degree
of longitude is about half a degree of latitude on the ground, so lat/lon cells
would be badly non-square.

Key-pair auth preferred, credentials from environment only. `write_pandas` needs
**pyarrow** and `quote_identifiers=False` — the default quotes identifiers,
creating case-sensitive columns that make every later `SELECT` fail mysteriously.

---

## Project structure

```
lidar-explore/
├── data/                      generated + downloaded (gitignored)
├── generate_nuuksio.py        synthetic sample generator
├── inspect_laz.py             point cloud summary
├── nuuksio_workflow.py        DEM + CHM
├── detect_trees.py            local-max detection + evaluation
├── density_study.py           error vs point density
├── load_to_snowflake.py       GEOGRAPHY load + spatial SQL
├── fetch_metsakeskus.py       real CHM tile fetch + crop
├── chm_change.py              multi-epoch change + bias diagnostics
├── stand_validate.py          detection vs inventory, plan benchmark
├── harvest_targeting.py       stand ranking + retention trees
├── make_maps.py               publication figures
├── REPORT.md                  full write-up
└── CLAUDE_CONTEXT.md          pickup prompts
```

---

## Notes / gotchas

* Never name a Python file after a stdlib module — hence `inspect_laz.py`.
* `filters.hag_nn` needs classified ground; add `filters.smrf` first if absent.
* `maximum_filter` defaults to reflect mode at borders and can create spurious
  edge peaks. Test by shifting the AOI: if clusters follow the edge it's an
  artifact, if they stay put it's geography.
* Binning change on the same epoch you are differencing induces regression to
  the mean. Bin on an independent epoch when one exists.
* One-sided sanity checks miss half the failure modes. A growth check bounded
  only above passed −0.10 m/yr in mature forest without comment.
* Sorted lists always look alarming at the top. An earlier concern about
  639 m³/ha volumes dissolved on seeing the median (206) and 95th pct (406).

---

## Attribution

Canopy height models and forest resource data:
**Suomen metsäkeskus / Finnish Forest Centre**, CC BY 4.0.
