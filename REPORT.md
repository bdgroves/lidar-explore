# Detecting trees in canopy height models — and finding out what the numbers mean

**A validation study using synthetic LiDAR, Finnish national canopy data, and
the Finnish Forest Centre forest inventory.**

Brooks Groves, GISP · August 2026
Repository: `github.com/bdgroves/lidar-explore`

---

## Summary

Individual tree detection from a canopy height model is easy to implement and
easy to score well on. This study set out to find how much of that score is
real. Working from a synthetic boreal forest with known ground truth, then
moving to Finnish Forest Centre canopy height models and stand inventory for a
3,600-hectare map sheet near Nuuksio National Park, it reached four conclusions:

1. **Recall can be inflated by noise; height error cannot.** Thinning the point
   cloud from 6.3 to 0.5 points/m² *raised* recall from 78.4% to 81.8% while
   precision fell and height RMSE quadrupled. Recall is the wrong metric for
   assessing data quality.

2. **CHM cell size mattered more than point density** across the range tested.

3. **A canopy-specific acquisition bias was invisible to ground calibration.**
   Bare-ground agreement between epochs was exact (+0.00 m) while canopy carried
   a large additive offset — detectable only by stratifying change by tree size,
   using an independent third epoch to define the strata.

4. **Detection measures height well and counts stems poorly.** Against real
   inventory: 16% of stems recovered, but detected-tree height within +1.19 m
   of inventory mean height at r = 0.962.

A fifth result is negative and reported as such: a harvest-targeting benchmark
against 5,059 professional cutting proposals showed no lift once stands were
filtered by development class.

---

## 1. Data

### 1.1 Synthetic sample

A generated boreal stand modelled on Haukkalampi, Nuuksio National Park
(60.32° N, 24.56° E), EPSG:3067. 1,034,754 points over 405 × 403 m — 6.34
points/m² — with 450 trees of known position, height and species (186 spruce,
182 pine, 82 birch). Fixed seed, fully reproducible.

Its purpose is a known answer. Its limitation is density: ~28 stems/ha, where
crowns barely overlap.

### 1.2 Finnish Forest Centre canopy height models

Map sheet L4132D (362000–368000 E, 6684000–6690000 N), 1 m rasters at three
epochs: 2008, 2015, 2020. Approximately 55–70 MB each, 6 km × 6 km, EPSG:3067.
Derived from licensed 5 p laser data and published open under CC BY 4.0.

The licensed 5 p point cloud is not practically obtainable from outside Finland
(payment plus Finnish strong authentication). The free 0.5 p product is 13×
sparser than the synthetic sample used here. The Forest Centre's finished CHM
is therefore the better free route, being derived from the licensed data.

### 1.3 Forest resource data (Metsävarakuviot)

1,840 stand polygons covering 2,165 ha — the private forest within the sheet.
Ten related tables including per-species inventory strata, proposed operations
for 2026–2035, and legal restrictions.

Four schema properties determine whether an analysis is valid:

| property | consequence |
|---|---|
| `treestand.type` 1 = observed, 2 = 2026 projection, 3 = 2036 projection | joining a projection compares a raster to a simulation |
| `treestandsummary` exists only for types 2 and 3 | observed inventory must come from `treestratum` |
| `treestratum.stemcount` is null | density derived as N = G/(π/4·d²) |
| observation dates span 1999–2024 | a 21-year gap reads as detection error |

Coverage is private forest only. State land, including Nuuksio National Park,
is administered separately and absent. This study therefore treats presence in
the dataset as a **whitelist**: a stand not in the file is not eligible. A
blacklist would fail open wherever coverage is missing.

---

## 2. Methods

### 2.1 Detection

Canopy height models were built with PDAL (`filters.hag_nn` over classified
ground, `writers.gdal` maximum aggregation). Trees were detected as local
maxima on a lightly smoothed CHM, using a window that scales with local canopy
height — taller pixels get a wider window, since crown width scales with tree
size. Window sizes are held constant in **metres**, not pixels, so results
remain comparable across CHM resolutions.

Minimum detection height 5 m. For context, the Forest Centre's own laser
interpretation uses 2 m to separate development classes T1/T2 and 7 m to
separate T2 from class 02.

### 2.2 Density study

The synthetic cloud was decimated to target densities of 0.5, 1, 2 and 4
points/m² and rebuilt at 1 m and 2 m CHM resolution, with detection re-scored
against the same 450 known trees at each combination. Holding the forest
constant and varying only density is the only way to attribute a change in
performance to density rather than to forest type, sensor or season.

### 2.3 Change detection

Epoch pairs were differenced pixel-for-pixel (identical grids, no resampling)
with two diagnostics:

**Ground offset.** Median difference over pixels that were bare ground in the
earlier epoch. Ground should read ~0 m in any flight, so a non-zero median is
processing bias, not vegetation. The detection window is deliberately
asymmetric — requiring both epochs near zero is circular, since an offset large
enough to matter would push the later epoch above threshold and hide itself.

**Height-stratified increment.** Real height growth declines steeply with tree
size: young stands add roughly half a metre a year, stands above 28 m are near
asymptotic. Gains that are flat across height bands, or that rise with height,
indicate bias rather than biology.

Stratifying by starting height and then measuring change from that same height
induces regression to the mean. Where a third epoch exists it is used to define
the bins, since its noise is uncorrelated with the noise in either endpoint.

### 2.4 Validation

Detections were aggregated to stand polygons by rasterising stand IDs and
looking up each detected stem's label. Per stand: detected stems/ha over
polygon area, mean height of detected stems, mean height over all CHM pixels,
and canopy fraction.

Inventory comparison used type-1 strata only, aggregated per stand with basal
area summed and height and age basal-area weighted, filtered to stands observed
within ±6 years of the CHM epoch. Classes A0 and T1 were excluded, their
attributes being documented as unusable by the producer.

---

## 3. Results

### 3.1 Baseline detection, synthetic

```
Ground truth 450    detected 358    TP 353    FP 5    FN 97
Recall 78.4%    Precision 98.6%    F1 87.4%
Height RMSE 0.44 m,  bias −0.24 m,  90% within ±0.77 m

By species:  spruce 88.2%    pine 73.1%    birch 68.3%
```

Species ordering is as expected: tall narrow spruce cones are the easiest
target, wide flat birch crowns the hardest.

### 3.2 Density: recall misleads, height error does not

| points/m² | detected | recall | precision | height RMSE |
|---|---|---|---|---|
| 0.49 | 400 | 81.8% | 92.0% | **1.63 m** |
| 1.05 | 366 | 78.9% | 97.0% | 1.14 m |
| 2.10 | 361 | 79.1% | 98.6% | 0.76 m |
| 3.16 | 362 | 78.2% | 97.2% | 0.60 m |
| 6.31 | 358 | 78.4% | 98.6% | **0.44 m** |

Recall *increases* as data thins. At 0.5 points/m² a 1 m CHM has more empty
cells than filled ones; nodata rendered as zero produces a rough surface with
extra local maxima. Some land near real trees, so recall rises. Precision falls
from 98.6% to 92.0% and false positives rise from 5 to 32. Height RMSE
quadruples.

F1 conceals this entirely: 86.6 at the sparsest density versus 87.4 at the
densest. **Position can be faked by noise. Height cannot.**

A 2 m CHM scored worse than 1 m at every density tested, with birch degrading
most — consistent with wide flat crowns being merged by coarse max-aggregation.

### 3.3 Cross-epoch canopy bias

Full sheet, three pairs:

| pair | mean height | net change | ground offset | bare-ground spread (p95) |
|---|---|---|---|---|
| 2008 → 2015 | 9.78 → 12.25 m | +2.47 m | +0.00 m | 1.33 m |
| 2015 → 2020 | 12.25 → 12.37 m | +0.12 m | +0.00 m | 0.76 m |
| 2008 → 2020 | 9.78 → 12.37 m | +2.59 m | +0.00 m | 1.35 m |

Ground calibration is exact in all three. Yet the middle period shows 0.024
m/yr against 0.35 m/yr in the first — a fifteen-fold deceleration that no
boreal forest exhibits, and harvest (3.6% vs 2.6%) is far too small to explain.

Stratifying 2008→2020 by height, with bins defined by the independent 2015
epoch:

| starting height | mean gain | m/yr |
|---|---|---|
| 3–8 m | +2.96 m | +0.247 |
| 8–15 m | +3.83 m | +0.319 |
| 15–22 m | +3.55 m | +0.296 |
| 22–28 m | +3.16 m | **+0.263** |
| 28–60 m | +3.69 m | **+0.308** |

Nearly flat across every band. Real increment should fall steeply; stands above
28 m should be near zero. A constant gain independent of tree size is an
additive offset. Since ground agreement is exact, the 2008 flight
under-measured **canopy specifically** — consistent with a different CHM
generation method rather than density alone.

The 2015→2020 pair fails in the opposite direction, showing −0.10 m/yr in the
22–28 m band. Standing forest does not lose height.

**Neither pair supports an absolute growth rate.** An additive offset preserves
ordering, so relative ranking survives; current annual increment does not.

A methodological note: an earlier run binned on the earlier endpoint rather
than an independent epoch, and regression to the mean inverted the conclusion —
the pair that appeared textbook-clean was the biased one.

### 3.4 Validation against inventory

Across 1,295 stands with usable, vintage-matched inventory (private forest,
development class other than A0/T1, observed within 6 years of the CHM):

**Stem density.** Inventory median 496 stems/ha; detected median 83; recovery
**16.3%**. By development class:

| class | inventory stems/ha | detected | recovery |
|---|---|---|---|
| 02 young thinning | 817 | 87 | 12% |
| 03 advanced thinning | 635 | 87 | 15% |
| 04 regeneration-mature | 444 | 70 | **17%** |

Recovery rises monotonically with maturity. Local maxima on a 1 m CHM resolve
dominant and codominant crowns; suppressed understory stems are invisible. As
stands mature and thin, remaining crowns are larger and better separated, so
more are resolved. This is the expected physics, measured across 1,295 stands.

**Height — and the estimator determines the sign.**

| estimator | value | vs inventory mean | correlation |
|---|---|---|---|
| mean over detected stems | 20.83 m | **+1.19 m** | **r = 0.962** |
| inventory mean height | 19.64 m | — | — |
| mean over all CHM pixels | 15.69 m | −3.95 m | r = 0.901 |

The two bracket the inventory value. Detected stems are crown apexes and sit
above a stem-weighted mean that includes shorter trees. Whole-pixel mean sits
below because it averages canopy gaps — mean canopy fraction is 0.90, so
roughly one pixel in ten is a gap. Same raster, opposite sign, and the
stem-based estimator correlates better.

**The headline result is therefore conditional on the estimator**, which is
worth stating explicitly: a CHM measures dominant canopy height to within about
1.2 m of inventory mean, at r = 0.96, while recovering about one stem in six.

Vintage filtering was not cosmetic. Restricting to inventory observed within
6 years of the CHM raised the detected-stem correlation from 0.907 to 0.962 —
219 of 1,779 stands carried measurements up to 21 years old, and their growth
since measurement was entering the comparison as apparent error.

### 3.5 Harvest targeting: a negative result

Stands were ranked for harvest and scored against operations proposed by
foresters for 2026–2035.

```
Cutting proposed across all stands ≥0.3 ha    1,158 of 1,579   (73%)
Cutting proposed within the eligible pool       471 of 472    (100%)

Top 15 ranked stands, also proposed:                  15
Precision                                           100%
Base rate within pool                               100%
Lift over random-in-pool                           1.00×
```

The benchmark is saturated. Once stands are filtered to development class 04,
essentially all are already on the foresters' cutting list, so precision near
100% is unavoidable and lift cannot exceed ~1.00×.

**The development class does the work; the CHM adds no discriminating power on
top of it.** This is a real finding about where value lies: the expensive
remote sensing input is redundant with a classification a forester already
made. Any claim that the model "agrees with professional judgement 100% of the
time" would be true and meaningless.

An earlier version of this benchmark reported 1.37× lift by computing the base
rate across all stands rather than the pool actually selected from — crediting
the ranking for exclusions the development class had already made.

---

## 4. Limitations

**Terrain is absent.** A canopy height model is height above ground; the ground
has been subtracted away. Slope, wetness and machine trafficability are
invisible, so no operability assessment is possible.

**No diameter, therefore no volume from remote sensing.** Volume figures in
this study come from the inventory, not from the CHM. Height alone gives an
ordering, not cubic metres.

**Species is not derived.** Detection recall differed sharply by species on
synthetic data (spruce 88%, birch 68%); whether that holds on real stands is
untested here.

**Stem density is derived, not counted.** Inventory `stemcount` is null in the
observed strata, so density comes from basal area and mean diameter. Finnish
mean diameter is basal-area weighted, making this a stand-level estimate.

**Point clouds are exercised only on synthetic data.** All real analysis uses
the Forest Centre's finished CHM raster. PDAL processing of real point clouds
remains untested.

**One sheet, one forest type.** Southern Finnish managed boreal forest,
spruce-dominated. Nothing here is established for other structures or regions.

---

## 5. What transfers

For anyone assessing canopy height data for forest inventory:

- Report height error, not recall, when characterising data quality. Recall can
  improve as data degrades.
- Verify cross-epoch calibration on *canopy*, not only on ground. Ground
  agreement is necessary and nowhere near sufficient.
- When stratifying change by size, define the strata from an independent
  observation or accept a known bias.
- State which height estimator produced a number. Detected-stem mean and
  whole-pixel mean differ by more than 5 m on the same raster and fall on
  opposite sides of the truth.
- Score predictions against the pool actually selected from.
- Treat absence from a coverage dataset as a block, not a gap, when the
  consequence of being wrong is operating on protected land.

---

## Attribution

Canopy height models and forest resource data:
**Suomen metsäkeskus / Finnish Forest Centre**, licensed CC BY 4.0.

Synthetic sample, analysis code and figures: this repository, reproducible from
`README.md`.
