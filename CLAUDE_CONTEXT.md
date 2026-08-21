# Claude pickup prompts

Paste a block below into a fresh Claude conversation. Each is self-contained.
Ask Claude to read `README.md` and `REPORT.md` first.

---

## Where the project stands

**Synthetic track — complete.** PDAL DEM/CHM, local-max detection scored at
78.4% recall / 98.6% precision / 0.44 m height RMSE against 450 known trees.
Density study establishes that recall is gameable by noise in sparse CHMs while
height RMSE degrades honestly (0.44 m → 1.63 m from 6.3 to 0.5 p/m²).

**Snowflake — complete.** Detections load as `GEOGRAPHY`, key-pair auth,
`ST_DWITHIN` self-joins and equal-area grid density in SQL.

**Real track — complete through validation.** Finnish Forest Centre CHM for
sheet L4132D (2008/2015/2020, 1 m, EPSG:3067) plus Metsävarakuviot stand
polygons with inventory, operations and restrictions.

Established:
- 2008 epoch has a canopy-specific additive bias invisible to ground
  calibration; neither epoch pair supports an absolute growth rate
- detection recovers ~16% of inventory stems, rising 12% → 17% with maturity
- detected-stem height: +1.37 m vs inventory mean, r = 0.907
- whole-pixel CHM height: −3.81 m vs inventory mean, r = 0.841
- harvest benchmark saturated: 471/472 eligible stands already proposed for
  cutting, lift 1.00× — development class does the work, not the CHM

---

## Open threads, roughly by value

**A. Reconcile the two sample sizes.** Validation stats use 1,295 stands
(vintage-filtered); the height bracketing used 1,706 (unfiltered). Recompute the
bracketing on the filtered set and fold `det_mean_h` into the main report output
of `stand_validate.py` so the numbers are consistent.

**B. Find where the CHM adds value beyond development class.** The harvest
benchmark saturated because class 04 already determines the cutting list. The
CHM might discriminate *within* class 04 — which mature stands are most
valuable, or which have already been partially cut since the last inventory
(observation dates run to 2024, CHM is 2020, so some stands are stale in the
opposite direction). That is a question the inventory alone cannot answer.

**C. Thinning detection.** Class 03 stands proposed for thinning rather than
regeneration felling are a harder, more interesting target than clearfell
candidates, and the CHM may genuinely help identify stocking that warrants it.

**D. Species.** `treestratum.treespecies` gives per-species basal area. Detection
recall differed sharply by species in the synthetic run (spruce 88%, birch 68%).
Test whether that holds on real stands by grouping recovery rate by dominant
species.

**E. Point clouds, properly.** Everything real so far uses the finished CHM
raster, not point clouds — PDAL is exercised only on synthetic data. USGS 3DEP
offers free, unauthenticated, denser data over the Pacific Northwest, and
`readers.ept` can stream a cropped AOI without downloading a full tile. Requires
generalising the scripts to take a CRS parameter instead of hardcoded 3067.

---

## Conventions

- Never write credentials into files. Environment variables only.
- Add new scripts rather than editing working ones, so results stay comparable.
- Match existing style: module docstring, constants at top, small functions,
  `if __name__ == "__main__":`, printed summary blocks with `=` rules.
- Test each piece before moving on; dry-run flags where sensible.
- Build synthetic fixtures with known answers to test analysis code. Several
  real bugs were caught this way — a circular ground-offset detector, a
  one-sided plausibility check, a base rate computed on the wrong denominator.
- State what the data cannot support. The negative results here are the most
  defensible part of the project.
