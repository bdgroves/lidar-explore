# Claude pickup prompts

Paste one of the blocks below into a fresh Claude conversation to continue.
Each is self-contained. Start by asking Claude to read `README.md`.

---

## Where the project stands

Complete and working end to end on synthetic data:

- Windows + pixi environment (`pixi install`), pyarrow included
- Synthetic Finnish boreal forest sample (Nuuksio/Haukkalampi, EPSG:3067,
  ~1M points, 450 known trees with species + heights as ground truth)
- DEM + CHM pipeline via PDAL `filters.hag_nn`
- Local-max tree detection: 78.4% recall, 98.6% precision, F1 87.4%,
  height RMSE 0.44m
- Snowflake load working: `TO_GEOGRAPHY` table `LIDAR_DB.NUUKSIO.NUUKSIO_TREES`,
  key-pair auth, four spatial queries, round-trip visualization

Known limitations, both documented in the README:

- The synthetic stand is sparse (~28 stems/ha vs 800–1,500 in real Finnish
  forest). Crowns barely overlap, so the F1 is flattering.
- The 97 missed trees are concentrated in the understory — the 6–10 m height
  band is nearly empty in the Snowflake histogram despite a 6.0 m detection
  threshold.

---

## Track A — variable-window detection

I'm continuing a LiDAR forestry project at
`git@github.com:bdgroves/lidar-explore.git` — please read `README.md` first.

The pipeline works end to end on synthetic data (see README for numbers). I want
to improve detection recall, currently 78.4%, with misses concentrated in the
understory and in wide birch crowns.

`detect_trees.py` uses a fixed local-max window (`WINDOW_RADIUS = 3`, so 7m).
I want to try a **variable window that scales with CHM height** — taller pixels
get a wider window, shorter pixels a narrower one — which is the standard fix in
the individual-tree-detection literature.

Please write this as a new script rather than editing `detect_trees.py`, so the
two are directly comparable on the same ground truth. Keep the same evaluation
and reporting format so the numbers line up side by side. The goal is to recover
understory misses without giving up the 98.6% precision.

---

## Track B — real point cloud data

I'm continuing a LiDAR forestry project at
`git@github.com:bdgroves/lidar-explore.git` — please read `README.md` first.

The pipeline works end to end on synthetic data. Now I want to run it on real
airborne LiDAR.

Important framing: real data has **no ground truth**, so recall and precision
can't be computed. The question changes from "how accurate is detection" to
"does the pipeline survive real point clouds" — variable pulse density, noise,
possibly unclassified ground, overlapping crowns, and files 30–100× larger.

What I need:

1. A fetch/crop step that pulls a small AOI (~400m × 400m) out of a real tile
   without downloading gigabytes — PDAL `readers.ept` against USGS 3DEP, or
   `filters.crop` on a downloaded MML tile.
2. The existing scripts generalized to take a CRS parameter instead of the
   hardcoded EPSG:3067, since 3DEP projects use State Plane or UTM.
3. A ground-classification fallback (`filters.smrf`) for tiles that arrive
   unclassified, since `filters.hag_nn` requires classified ground.
4. Sanity checks appropriate to unlabeled data: stem density vs published
   values for the forest type, height distribution shape, CHM artifacts.

---

## Conventions to keep

- Never write credentials into files. Environment variables only.
- Add new scripts rather than editing working ones, so results stay comparable.
- Match the existing style: module docstring, constants at top, small functions,
  `if __name__ == "__main__":`, printed summary blocks with `=` rules.
- Test each piece before moving to the next — dry-run flags where it makes sense.
