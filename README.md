# lidar-explore

<p align="center">
  <img src="assets/lidar-explore-banner.jpg" alt="LiDAR Explore: from point clouds to forest intelligence" width="100%"/>
</p>

**[Explore it live: brooksgroves.com/lidar-explore](https://brooksgroves.com/lidar-explore/)** — spin the
point cloud, thin the laser, click any stand. ·
[The story](https://brooksgroves.com/blog/finding-the-trees.html)

**Some people chase storms. I chase trees — through a million points of laser
noise and 36 million canopy pixels, into a national forest dataset, and out the other side with
numbers that survived contact with reality.**

This project starts in a calm, controlled sandbox — a synthetic Finnish forest
where every tree's exact location is already known — then drives straight into
the real thing: airborne LiDAR canopy height models over a 6x6 km slice of
Finland, validated stand-by-stand against the Finnish Forest Centre's
inventory (1,295 stands in the original run, 1,489 in the rebuild). No
held-out demo set. National data, real stands, and the Forest Centre's own
cutting proposals used as the benchmark.

> **Rebuilt October 2026.** The whole pipeline now reruns from the open data on
> GitHub Actions. Everything reproduced, and the Forest Centre's new data
> release corrected two claims this README used to make: the cutting proposals
> are simulated by the Forest Centre's planning calculation, not foresters'
> field calls, and nearly all of the "observed" inventory was interpreted from
> airborne laser data. See [Rebuilt from scratch](#rebuilt-from-scratch-october-2026).

The workflow mirrors what commercial forestry operators build at scale: raw
point cloud -> ground/canopy separation -> individual-tree detection ->
structured features in a warehouse -> stand-level management decisions.

![Validation map: detected-stem height bias across Sheet L4132D](data/web/map_L4132D_validation.jpg)
*Every stand on Sheet L4132D, colored by how far the LiDAR-detected height
missed the ground-truth inventory. Warm means the estimator ran hot, cool
means it ran cold — the map does not editorialize, and neither does the
report below.*

---

## Four things this chase found — each one busting something the last step seemed to prove

Storm chasers keep the instruments running through the wrong turns, because
the wrong turns are half the data. Same rule here: every result below
corrected something the previous one made look settled.

**1. The scoreboard lied. Recall is gameable; height error is not.**
78.4% recall, 98.6% precision on the synthetic sample — but that stand is
~28 stems/ha, so crowns barely overlap. Thinning the cloud to 0.5 p/m2
*raised* recall to 81.8% while precision fell to 92.0% and height RMSE
quadrupled from 0.44 m to 1.63 m. At that density about one cell in eight of
the 1 m CHM gets no return at all (13%; PDAL's writer fills the rest from
points within ~1.4 m), and nodata-as-zero turns those holes into spurious local
maxima, some of which land near real trees. Height RMSE is the honest density metric — recall just
looked honest.

**2. Resolution beat point count, every time.**
A 2 m CHM scored worse than 1 m at every density tested, and birch — wide,
flat crowns — degraded worst. Resolution was the binding constraint, not
point count.

**3. Cross-epoch bias hides exactly where ground calibration can't see it.**
On real Forest Centre CHMs for 2008/2015/2020, the bare-ground median offset
was +0.00 m for every epoch pair — perfect ground agreement, and it told us
nothing about canopy. Binning change on an *independent* third epoch (to kill
regression-to-the-mean) showed 2008-2020 gains nearly flat from 3 m up,
+0.25 to +0.32 m/yr including 28 m+ stands that should be near-asymptotic
(the 0–3 m band is slightly negative, likely harvests between flights). A
constant gain regardless of tree size looks like an additive offset, not
biology; the likeliest reading is that the 2008 flight under-measured canopy
while measuring ground correctly. Relative ranking survives an additive bias; absolute
current-annual-increment does not.

**4. Detection nails height, whiffs on stem count — and the plan already
knew.**

Original run below; the rebuild on the new data model reproduces it (16.2%,
+1.18 m at r = 0.959, −4.01 m at r = 0.906 over 1,489 stands — see
[Rebuilt from scratch](#rebuilt-from-scratch-october-2026)). Note that the
inventory is itself laser-interpreted, so height agreement is partly laser
against laser.

| | value |
|---|---|
| stem recovery, median | **16.3%** of inventory stems/ha |
| by class: 02 young / 03 advanced / 04 mature | 12% / 15% / **17%** |
| detected-stem height vs inventory mean | **+1.19 m**, r = **0.962** |
| whole-pixel CHM height vs inventory mean | -3.95 m, r = 0.901 |

All on the same 1,295 stands: private forest, usable development class, and
inventory observed within 6 years of the CHM epoch. Recovery rises
monotonically with maturity — fewer, larger, better-separated crowns are
easier to resolve — and the estimator matters: mean over *detected stems*
brackets inventory mean from above (crown apexes), while mean over *all
pixels* sits below it because it averages in canopy gaps. Same raster,
opposite sign; the stem-based estimator correlates better.

**Plus one clean negative result, reported because it's true, not because it
flatters the method.** Harvest ranking was benchmarked against 5,059
cutting proposals (old data model; the new one lists 1,320, all but one
simulated). Once stands are filtered to development class 04
(regeneration-mature) and to the stands the ranking could pick, 471 of 472
(rebuild: 545 of 547) eligible stands were already proposed for
cutting — base rate 100%, lift 1.00x. The development class determines the
list; the CHM adds no discriminating power on top of it. (The new data
release shows why: the proposals are simulated by the Forest Centre's planning
calculation from the inventory, so a mature stand is nearly always proposed.)

---

## Rebuilt from scratch, October 2026

`.github/workflows/rebuild.yml` reruns everything on a clean Linux machine:
the synthetic track from the sample in this repo, then the real track from
the open downloads (`fetch_open_data.py`: CHM index and every epoch for the
sheet, the stand inventory, the NLS 1 m DTM). Logs and tables land on the
[`rebuild-results`](../../tree/rebuild-results) branch, and
`build_web_data.py` writes the data behind the
[project page](https://brooksgroves.com/lidar-explore/) into `docs/data`.

| | original run | rebuilt |
|---|---|---|
| synthetic: recall / precision / height RMSE | 78.4% / 98.6% / 0.44 m | identical |
| density study, every row | (published table) | identical |
| stands on the sheet / private forest | 1,840 / 2,165 ha | identical |
| stands with a usable, fresh inventory | 1,295 | 1,489 |
| stem recovery, median | 16.3% | 16.2% |
| detected-stem height vs inventory | +1.19 m, r = 0.962 | +1.18 m, r = 0.959 |
| whole-pixel CHM height vs inventory | −3.95 m, r = 0.901 | −4.01 m, r = 0.906 |
| eligible class-04 stands already proposed | 471 of 472 | 545 of 547 |
| 2008→2020 gain, 3 m and up, binned on 2015 | +0.25 to +0.32 m/yr | +0.25 to +0.32 m/yr |
| class 04 with a cutting proposal (machine planning) | 653 | 653 (652 large enough to sample) |
| season: summer / dry / frozen | 609 / 43 / 1 | 608 / 43 / 1 |
| access: conventional / winch / steep | 476 / 145 / 32 | 476 / 145 / 31 |
| both wet and steep | 3 | 3 |
| WA FPA, committed snapshot | 1,024 apps, AUC 0.879 | identical |
| WA FPA, fresh pull | | 1,049 apps, AUC 0.878 |

What changed, and what it taught:

* **The Forest Centre moved its downloads.** The CHM index is now under
  `Latvusmalli/Latvusmalli_indeksi/` and the stand data under `MV/` (was
  `Metsavarakuviot/`). Both scripts point at the new addresses.
* **The stand data model changed (renewal begun 2025).** `treestand.type` became
  `treestandclass`, the date became `treedatadate`, development class and main
  species moved onto the tree stand, and cutting proposals got their own
  `cutting` table. `stand_validate.py` reads both models. Some stands now carry
  more than one inventory; the newest is used, which is why 1,489 stands
  qualify instead of 1,295.
* **The "ground truth" is laser-derived.** Of the 1,489 validated stands,
  1,488 have an inventory the Forest Centre *interpreted from airborne laser
  data*; one was measured in the field. (The field-measured inventories are
  mostly old, so the six-year freshness filter drops them.) Height agreement is
  therefore largely laser against laser. The stem-count shortfall is a
  different matter: the inventory's stem numbers come from models calibrated on
  field sample plots, which count the suppressed trees that individual-tree
  detection from above can't separate.
* **The cutting proposals are simulated.** In `cutting.type`, 1 means
  "simuloitu ehdotus, laskentasovellus": a proposal from the Forest Centre's
  planning calculation. All but one proposal on the sheet are type 1. That is
  the mechanism behind the saturated harvest benchmark.
* **Coverage is reported but not filtered.** 119 validated stands have under
  90% CHM coverage. Dropping them moves stem recovery from 16.2% to 16.7% and
  leaves the height result unchanged. The next version of the check should
  filter on `coverage_pct`.
* **New epochs exist.** The index now lists 2018, 2021 and 2024 partial tiles
  for L4132D and an `uusin` (latest) composite.
* **`stands_joined.gpkg` is reproducible.** It was first assembled by hand in
  QGIS; `build_stands_joined.py` now rebuilds it from the open stand data.

```powershell
pixi run synthetic    # inspect, DEM + CHM, detection, density study
pixi run fetch        # the open data for L4132D
pixi run validate     # stand validation, 2020 CHM
pixi run web          # docs/data for the project page
```

---

## Pipeline

```
SYNTHETIC TRACK (ground truth known)
  nuuksio_sample.laz
        |- inspect_laz.py        density, extent, classification
        |- nuuksio_workflow.py   PDAL: ground -> DEM, hag_nn -> CHM
        |- detect_trees.py       local-max detection, scored vs truth
        |- density_study.py      thin the cloud, measure error vs density
        \- load_to_snowflake.py  GEOGRAPHY table + spatial SQL

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
rasterio cleanly on Windows. Optional: QGIS for browsing rasters and building
figures like the one above, Snowflake for the warehouse step.

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

Read the RMSE column, not recall. See finding 1.

**Caveat carried throughout:** the synthetic stand is ~28 stems/ha. Real
managed Finnish forest on sheet L4132D measures ~496 stems/ha median and
~444 in mature class-04 stands. An earlier draft cited 800-1,500 — that
range applies to young unthinned stands, not forest at rotation age.

---

## Real data: Finnish Forest Centre

Two open datasets, CC BY 4.0, no registration, no API key.

**Latvusmalli** — 1 m canopy height model, 6 km x 6 km tiles, EPSG:3067,
derived from the licensed 5 p laser data. `fetch_metsakeskus.py` reads the
published GeoPackage index (download URL + precomputed stats per tile).

```powershell
python fetch_metsakeskus.py --sheet L4132D --year all --list
python fetch_metsakeskus.py --sheet L4132D --year 2020 --crop 364000 6685000 365000 6686000
```

**Metsavarakuviot** — stand polygons with inventory, proposed operations and
restrictions. Relational GeoPackage, ten tables.

Note: **MML "Laser scanning data 5 p" is not free** — it needs payment and
Finnish strong authentication, not practically available to non-residents.
The free 0.5 p product is 13x sparser than this project's synthetic sample.
The Forest Centre CHM is the better free route, being derived from the
licensed data.

### Schema gotchas that silently corrupt results

* `treestand.type` (old model) / `treestandclass` (new model): **1 = observed
  inventory, 2 = current state / projected to 2026, 3 = projected to 2036.**
  Joining a projection compares your raster to a simulation.
* `treestandsummary` exists **only for types 2 and 3**. Observed inventory is
  in `treestratum`, per species. `stemcount` was null there in the old model
  (the new one fills it for about a quarter of strata); density is derived as
  `N = G / (pi/4 * d^2)` from basal area and mean diameter, which runs low
  because the diameter is basal-area weighted.
* Observation dates span **1999-2024**. A 2020 raster against a 1999
  measurement reads as detection error when it is two decades of growth.
  `stand_validate.py` filters to +/-6 years (original run: 219 of 1,779 stands
  excluded; on the new data, using each stand's newest inventory, 28 of 1,821).
* Check where each inventory came from: in the new model
  `treestanddatasource` 1 = field-measured, 2 = remote-sensed. On L4132D the
  fresh inventories are almost all remote-sensed.
* Attributes for classes **A0 and T1 are documented as unusable** by the
  producer. Dropped, not silently compared.
* Metsavarakuviot covers **private** forest only — 2,165 ha of the 3,600 ha
  sheet. State land including Nuuksio National Park is absent, so absence is
  treated as a **whitelist block**. A blacklist would fail open on any gap.

### Development classes (kehitysluokka)

| code | Finnish | English |
|---|---|---|
| A0 | aukea | open / clearcut |
| T1 | pieni taimikko | seedlings <=1.3 m |
| T2 | varttunut taimikko | advanced seedlings >1.3 m |
| Y1 | ylispuustoinen taimikko | seedlings under overstory |
| 02 | nuori kasvatusmetsikko | young thinning stand |
| 03 | varttunut kasvatusmetsikko | advanced thinning stand |
| 04 | uudistuskypsa metsikko | **regeneration-mature** |

Class 04 replaced an earlier Chapman-Richards age model. The inventory's own
maturity class beats inverting a growth curve with an assumed site index
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

**Height-stratified increment** — real height growth declines steeply with
tree size. Gains flat across bands, or rising with height, indicate bias not
biology. Use `--bin-on` with a third epoch to define bins; otherwise
regression to the mean drags the top bands down and can invert the
conclusion. It did, in an earlier run: the pair that looked textbook-clean
was the biased one.

---

## Stand validation

```powershell
python stand_validate.py --year 2020 --top 15
```

Joins detection to stand polygons, compares against observed inventory,
scores ranking against the management plan. Writes
`data/stand_validation.csv`. The map at the top of this README is the visual
version of that file — every stand's detected-vs-inventory height bias,
mapped across the real tile.

---

## API

The validated stand data is also queryable live, not just through scripts:

```powershell
pixi run uvicorn api:app --reload
```

Then hit `http://127.0.0.1:8000/docs` for interactive Swagger docs, or:

```
GET /stands?developmentclass=04&limit=10   # filter stands by class, area, eligibility
GET /stands/{standid}                       # single stand, full detection + inventory record
GET /summary                                # live-computed validation stats for the current data
```

Built on FastAPI over the same `data/stand_validation.csv` that
`stand_validate.py` produces — no separate demo dataset, no mock data. The
`/summary` endpoint is explicit about which population it's scoring against,
since it's a live query rather than the hand-curated 1,295-stand set
documented above.

---

## Where do the machines go? Terrain planning for the stands already chosen

The harvest-ranking result above is a clean negative: filtered to development
class 04, the CHM adds no discriminating power over the inventory's own
maturity class. **Which** stand to cut is already decided.

Terrain answers a question the plan does not. In Nordic forestry the dominant
environmental problem is not stand selection, it is **rutting** -- a loaded
forwarder churning saturated soil, shearing roots and delivering sediment to
watercourses. The standard mitigation is timing: wet ground is cut frozen.

That needs a terrain model, which the CHM is not -- canopy height is height
*above* ground, so it carries no elevation. Finland's National Land Survey
publishes a 1 m DTM for the whole country, and CSC mirrors it as an open VRT
with no API key:

```
https://vm0160.kaj.pouta.csc.fi/mml/korkeusmalli/km2/2020/km2_2020.vrt
```

The VRT points at 60 tiles of 100 km each over plain HTTP. Reading the one
tile covering L4132D and windowing to the sheet takes 18 seconds and no full
download.

![Machine planning for sheet L4132D](data/web/machine_planning.jpg)

From that DTM, two measures per stand:

* **slope** -- an access problem. Steep ground limits machines and raises
  erosion risk.
* **TWI**, `ln(a / tan b)` -- a scheduling problem. High values mark where
  water collects.

Of **653 stands in class 04 with a cutting proposal**:

| Season (wetness) | n | | Access (slope) | n |
|---|---:|---|---|---:|
| summer-trafficable | 609 | | conventional | 476 |
| dry season preferred | 43 | | winch assist advised | 145 |
| frozen-ground only | 1 | | steep - review access | 32 |

**Only 3 stands are both wet and steep.** The two constraints land on almost
entirely different stands, so they decompose into separate planning problems
rather than one blended risk score.

### Two things this got wrong first

**Merging the constraints.** The first version summed wet and steep into one
"sensitivity" number and derived a single season label from it. Stands that
were 89% steep came out labelled `summer-trafficable`, because the season rule
only ever looked at wetness. Wet and steep have different mitigations --
schedule versus winch -- so they are now separate flags. A blended score
would have hidden exactly the stands that need attention.

**Counting nulls as findings.** The map first reported 45 wet and 178 steep
against the script's 44 and 177. Stands too small to sample (<5 cells) carry a
null label, and `!= "summer-trafficable"` is true for nulls. Two phantom
stands, from a comparison that treated missing as flagged.

### What this is not

The thresholds are **percentiles of this sheet**, not absolute limits.
Real bearing capacity depends on soil texture, machine weight, tyre and track
configuration and season -- none of which are in this data. The output ranks
these stands against each other; it is not a trafficability model, and the
class boundaries would need calibration against observed rutting before
anyone drove on them.

One structural caveat: TWI carries `tan(slope)` in its denominator, so wet and
steep are anti-correlated partly **by construction**. The near-total
separation between the two groups is therefore not an independent discovery,
though it is also consistent with the obvious hydrology -- water does not pool
on a 30-degree rock face.

```powershell
python machine_planning.py            # DTM -> slope + TWI -> per-stand stats
python machine_planning_fig.py        # the figure above
```

---

## Washington: testing terrain against a real regulator's decision

The machine-planning thresholds above are percentiles I chose. Nothing
external says a stand at the 85th percentile of wetness is actually a problem.
That is the weakest part of that analysis.

Washington supplies the missing standard. DNR publishes every **Forest
Practices Application** as an open polygon layer, and each carries
`UNSTABLE_SLOPE_FLG` — the agency's own determination, made by their staff
under the Forest Practices rules, of whether the proposal involves potentially
unstable slopes. That is a real label. So: **does terrain-derived slope
predict it?**

Study area is Pacific Cascade region, SW Washington, deliberately spanning the
steep Willapa Hills and the flat Cowlitz floodplain. The label there is almost
exactly balanced, so the baseline to beat is a coin flip.

![Slope vs DNR unstable-slope flag](data/web/wa_fpa.jpg)

**1,024 applications, base rate 50.6% flagged:**

| Metric | Not flagged | Flagged | AUC |
|---|---:|---:|---:|
| mean slope | 8.1° | 16.5° | 0.860 |
| 90th-pct slope | 15.3° | 27.9° | 0.857 |
| **max slope** | **24.9°** | **42.6°** | **0.879** |

A single threshold at 33.7° max slope classifies **80.4%** of applications
correctly against a 50.6% base rate. Unlike the Finnish harvest-ranking null,
terrain here carries real signal.

### The unit of analysis was wrong first

The first run scored 1,533 individual harvest units and got AUC 0.854. But
the flag never varies between units sharing an `FP_ID` — zero applications out
of 1,024. `UNSTABLE_SLOPE_FLG` is an **application** attribute, so unit-level
scoring is pseudo-replication: 1,533 rows are only 1,024 independent
decisions, and an application subdivided into 17 units would carry 17 times
the weight of one drawn as a single polygon.

Aggregating to the application — the actual unit of decision — the result is
both smaller and stronger: n=1,024, AUC 0.879. The script now reports both so
the difference is visible rather than buried.

### Why a high AUC here is not a discovery

The rules define unstable landforms **partly by gradient**. Recovering the
flag from slope is therefore closer to reproducing a known determination from
one of its own inputs than to finding something new. The honest claim is that
the pipeline reproduces an operational decision it was never shown — useful as
validation, not as insight.

The residual is the interesting part. At the best threshold, **127
applications are steep but not flagged** and **74 are flagged but not steep**.
Those are where gradient alone diverges from the rule, which also names
specific landforms — inner gorges, convergent headwalls, bedrock hollows —
that a 10 m DEM cannot resolve and a gradient threshold cannot express. A
1 m lidar DTM and curvature-based landform detection is the obvious next step,
and the flagged-but-flat group is the set to check it against.

```powershell
python wa_fpa.py --fetch     # DNR polygons + 3DEP DEM windows
python wa_fpa.py             # unit-level vs application-level test
python wa_fpa_fig.py         # figure + disagreement cases
```

---

## Snowflake

`load_to_snowflake.py` reprojects EPSG:3067 -> 4326, stages via
`write_pandas`, builds a `TO_GEOGRAPHY` table, runs spatial SQL.

Both coordinate systems are kept deliberately: `GEOGRAPHY` for true-metre
`ST_DWITHIN`, projected TM35FIN for equal-area grid binning. At 60 degrees N
a degree of longitude is about half a degree of latitude on the ground, so
lat/lon cells would be badly non-square.

Key-pair auth preferred, credentials from environment only. `write_pandas`
needs **pyarrow** and `quote_identifiers=False` — the default quotes
identifiers, creating case-sensitive columns that make every later `SELECT`
fail mysteriously.

`lidar_dbt/` takes the loaded stand data further — dbt models and singular
tests that encode this project's hard-won corrections (mismatched
populations, crossed columns, silent population drift) as checks that fail
the build instead of failing quietly. See `lidar_dbt/README.md`.

---

## Project structure

```
lidar-explore/
+-- api.py                     FastAPI service over the validated stand data
+-- data/                      generated + downloaded (gitignored)
+-- data/web/                  compressed figures for this README
+-- lidar_dbt/                 dbt models over the validated stand data
+-- generate_nuuksio.py        synthetic sample generator
+-- inspect_laz.py             point cloud summary
+-- nuuksio_workflow.py        DEM + CHM
+-- detect_trees.py            local-max detection + evaluation
+-- density_study.py           error vs point density
+-- load_to_snowflake.py       GEOGRAPHY load + spatial SQL
+-- fetch_metsakeskus.py       real CHM tile fetch + crop
+-- chm_change.py              multi-epoch change + bias diagnostics
+-- stand_validate.py          detection vs inventory, plan benchmark
+-- harvest_targeting.py       stand ranking + retention trees
+-- wa_fpa.py                  WA harvest applications vs terrain slope
+-- wa_fpa_fig.py              WA FPA figure + disagreement cases
+-- machine_planning.py        slope + TWI per stand, harvest scheduling
+-- machine_planning_fig.py    machine-planning figure
+-- make_maps.py               publication figures
+-- REPORT.md                  full write-up
+-- CLAUDE_CONTEXT.md          pickup prompts
```

---

## Notes / gotchas

* Never name a Python file after a stdlib module — hence `inspect_laz.py`.
* `filters.hag_nn` needs classified ground; add `filters.smrf` first if
  absent.
* `maximum_filter` defaults to reflect mode at borders and can create
  spurious edge peaks. Test by shifting the AOI: if clusters follow the edge
  it's an artifact, if they stay put it's geography.
* Binning change on the same epoch you are differencing induces regression
  to the mean. Bin on an independent epoch when one exists.
* One-sided sanity checks miss half the failure modes. A growth check
  bounded only above passed -0.10 m/yr in mature forest without comment.
* Sorted lists always look alarming at the top. An earlier concern about
  639 m3/ha volumes dissolved on seeing the median (206) and 95th pct (406).
* A stand can show near-zero detected stems for a reason that has nothing to
  do with the algorithm: it straddles the CHM tile boundary. `coverage_pct`
  (added to `stand_validate.py` and exposed via the API) catches this --
  110 of 1,840 stands have under 50% CHM coverage. One, stand 38780079,
  inventory says 462 stems/ha and 99% canopy cover, detector found 2 trees --
  because only 3.7% of that stand actually has CHM data. Check coverage
  before trusting a low-recovery outlier.

---

## Why this exists

I grew up reading ridgelines before I read screens. This project is the same
instinct pointed at a data pipeline instead of a trailhead: don't trust the
first number, chase it through a second dataset, and report what's actually
there even when it's a clean negative result. It's the same discipline
that goes into any production geospatial data pipeline — the chase just
happens to be more fun when the terrain is real.

---

## Related

**[project-kiva](https://github.com/bdgroves/project-kiva)** — the same
discipline pointed at archaeology instead of forestry. A 1,150-year-old floor
plan pulled out of raw laser returns at Chaco Canyon, the pyramids at Giza,
a documented failure under the rainforest at Tikal, and a 3DEP metadata trap
that turns five published "epochs" into two actual surfaces.

---

## Attribution

Canopy height models and forest resource data:
**Suomen metsakeskus / Finnish Forest Centre**, CC BY 4.0.
