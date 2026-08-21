r"""
Point density study: how far does detection degrade as the point cloud thins?

Motivation: the free national LiDAR products vary enormously in density.
Finland's open "Laser scanning data 0.5 p" is 0.5 points/m2; USGS 3DEP is
typically 2-8+; our synthetic sample is ~6.4. Rather than guess how detection
behaves at each, we decimate our OWN sample - where ground truth is known -
and measure it.

Holding the forest constant and varying only density is the only way to
attribute a recall change to density rather than to forest type, sensor,
season, or terrain.

Two variables:
  - point density  (via PDAL filters.decimation)
  - CHM cell size  (1m is standard, but at low density a 1m grid is mostly
                    empty cells, so 2m may actually score better)

The local-max window is held constant in METERS, not pixels, so the 1m and 2m
runs are directly comparable.

Outputs:
  data/density_study.csv   - one row per (density, resolution)
  data/density_study.png   - recall/precision curves

Usage:
  python density_study.py            # full grid, ~10 PDAL runs
  python density_study.py --quick    # 1m only, fewer densities
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pdal
import rasterio
from scipy.ndimage import maximum_filter, gaussian_filter
import matplotlib.pyplot as plt

# Reuse the exact matcher from detect_trees so results are comparable
from detect_trees import match_to_truth

INPUT = "data/nuuksio_sample.laz"
TRUTH = "data/nuuksio_tree_truth.csv"
OUT_CSV = "data/density_study.csv"
FIG_OUT = "data/density_study.png"
TMP_CHM = "data/_tmp_density_chm.tif"

# Detection parameters, in meters so they survive a resolution change
WINDOW_M = 7.0          # local-max window width (matches detect_trees default)
MIN_HEIGHT_M = 6.0
SMOOTH_M = 0.6

TARGET_DENSITIES = [0.5, 1.0, 2.0, 4.0, None]   # None = full, no decimation
RESOLUTIONS = [1.0, 2.0]
QUICK_DENSITIES = [0.5, 2.0, None]


def source_stats():
    """Point count and extent of the input cloud, to get native density."""
    p = {"pipeline": [{"type": "readers.las", "filename": INPUT},
                      {"type": "filters.stats"}]}
    pipe = pdal.Pipeline(json.dumps(p))
    n = pipe.execute()
    meta = pipe.metadata["metadata"]
    bbox = meta["readers.las"]
    width = bbox["maxx"] - bbox["minx"]
    height = bbox["maxy"] - bbox["miny"]
    area = width * height
    return n, area, width, height


def build_chm(step: int, res: float) -> int:
    """Decimate by `step`, compute height above ground, rasterize at `res`."""
    stages = [{"type": "readers.las", "filename": INPUT}]
    if step > 1:
        stages.append({"type": "filters.decimation", "step": step})
    stages += [
        {"type": "filters.hag_nn", "count": 3},
        {"type": "filters.range", "limits": "HeightAboveGround[0:80]"},
        {"type": "writers.gdal",
         "filename": TMP_CHM,
         "resolution": res,
         "output_type": "max",
         "dimension": "HeightAboveGround",
         "data_type": "float32",
         "nodata": -9999},
    ]
    return pdal.Pipeline(json.dumps({"pipeline": stages})).execute()


def detect(res: float) -> pd.DataFrame:
    """Local-max detection on the temp CHM, window sized in meters."""
    with rasterio.open(TMP_CHM) as src:
        chm = src.read(1).astype(float)
        chm = np.where(chm == src.nodata, 0.0, chm)
        transform = src.transform

    # Convert meter-based parameters into pixels for this resolution.
    # Pick the ODD pixel count whose ground width is closest to WINDOW_M,
    # so the 1m and 2m runs use comparable windows (7m vs 6m, not 7m vs 10m).
    sigma_px = max(SMOOTH_M / res, 0.01)
    ideal = WINDOW_M / res
    candidates = [n for n in range(3, 41, 2)]
    win_px = min(candidates, key=lambda n: abs(n - ideal))

    smooth = gaussian_filter(chm, sigma=sigma_px)
    local_max = maximum_filter(smooth, size=win_px)
    peaks = (smooth == local_max) & (smooth >= MIN_HEIGHT_M)
    rows, cols = np.where(peaks)

    heights = chm[rows, cols]
    xs, ys = rasterio.transform.xy(transform, rows, cols)
    return pd.DataFrame({
        "x_tm35fin": np.array(xs),
        "y_tm35fin": np.array(ys),
        "height_m": heights,
    })


def evaluate(detected: pd.DataFrame, truth: pd.DataFrame) -> dict:
    det, matched = match_to_truth(detected, truth)
    n_truth, n_det = len(matched), len(det)
    tp = int(matched["detected"].sum())
    recall = tp / n_truth if n_truth else 0.0
    precision = tp / n_det if n_det else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    row = {"n_detected": n_det, "tp": tp, "fp": n_det - tp, "fn": n_truth - tp,
           "recall": recall, "precision": precision, "f1": f1}

    m = matched["detected"]
    if m.any():
        err = matched.loc[m, "detected_height_m"] - matched.loc[m, "height_m"]
        row["height_rmse"] = float((err ** 2).mean() ** 0.5)
        row["height_bias"] = float(err.mean())
    else:
        row["height_rmse"] = np.nan
        row["height_bias"] = np.nan

    for sp in ["spruce", "pine", "birch"]:
        s = matched["species"] == sp
        row[f"recall_{sp}"] = float(matched.loc[s, "detected"].mean()) if s.any() else np.nan
    return row


def run(densities, resolutions):
    n_pts, area, w, h = source_stats()
    native = n_pts / area
    print(f"Source: {n_pts:,} points over {w:.0f}m x {h:.0f}m "
          f"= {native:.2f} points/m2\n")

    truth = pd.read_csv(TRUTH)
    rows = []

    for target in densities:
        step = 1 if target is None else max(int(round(native / target)), 1)
        for res in resolutions:
            label = "native" if target is None else f"{target} p/m2"
            print(f"  {label:>10}  step={step:<3} res={res}m ... ", end="", flush=True)

            n_kept = build_chm(step, res)
            achieved = n_kept / area
            detected = detect(res)
            row = evaluate(detected, truth)
            row.update({"target_density": target if target else native,
                        "achieved_density": achieved,
                        "resolution_m": res,
                        "decimation_step": step,
                        "n_points": n_kept})
            rows.append(row)
            print(f"{achieved:.2f} p/m2, {row['n_detected']:3} detected, "
                  f"recall {row['recall']*100:.1f}%, "
                  f"precision {row['precision']*100:.1f}%")

    Path(TMP_CHM).unlink(missing_ok=True)
    for side in (".aux.xml",):
        Path(TMP_CHM + side).unlink(missing_ok=True)
    return pd.DataFrame(rows)


def report(df: pd.DataFrame):
    print("\n" + "=" * 72)
    print("DENSITY STUDY RESULTS")
    print("=" * 72)
    cols = ["achieved_density", "resolution_m", "n_detected",
            "recall", "precision", "f1", "height_rmse"]
    show = df[cols].copy()
    show["achieved_density"] = show["achieved_density"].round(2)
    for c in ["recall", "precision", "f1"]:
        show[c] = (show[c] * 100).round(1)
    show["height_rmse"] = show["height_rmse"].round(2)
    print(show.to_string(index=False))

    print("\nPer-species recall (%):")
    sp_cols = ["achieved_density", "resolution_m",
               "recall_spruce", "recall_pine", "recall_birch"]
    sp = df[sp_cols].copy()
    sp["achieved_density"] = sp["achieved_density"].round(2)
    for c in ["recall_spruce", "recall_pine", "recall_birch"]:
        sp[c] = (sp[c] * 100).round(1)
    print(sp.to_string(index=False))
    print("=" * 72)


def visualize(df: pd.DataFrame):
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))

    for res, grp in df.groupby("resolution_m"):
        g = grp.sort_values("achieved_density")
        axes[0].plot(g["achieved_density"], g["recall"] * 100,
                     marker="o", label=f"recall, {res}m CHM")
        axes[0].plot(g["achieved_density"], g["precision"] * 100,
                     marker="s", linestyle="--", alpha=0.6,
                     label=f"precision, {res}m CHM")

    axes[0].axvline(0.5, color="crimson", linestyle=":", linewidth=1.5)
    axes[0].text(0.55, 20, "Finland\nopen 0.5p", fontsize=8, color="crimson")
    axes[0].set_xscale("log")
    axes[0].set_xlabel("Point density (points/m$^2$, log scale)")
    axes[0].set_ylabel("Percent")
    axes[0].set_title("Detection performance vs point density")
    axes[0].set_ylim(0, 105)
    axes[0].grid(alpha=0.3)
    axes[0].legend(fontsize=8)

    best = df[df["resolution_m"] == df["resolution_m"].min()].sort_values("achieved_density")
    for sp, color in [("spruce", "#8b0000"), ("pine", "#ff8c00"), ("birch", "#c8a800")]:
        axes[1].plot(best["achieved_density"], best[f"recall_{sp}"] * 100,
                     marker="o", color=color, label=sp)
    axes[1].set_xscale("log")
    axes[1].set_xlabel("Point density (points/m$^2$, log scale)")
    axes[1].set_ylabel("Recall (%)")
    axes[1].set_title(f"Recall by species ({df['resolution_m'].min()}m CHM)")
    axes[1].set_ylim(0, 105)
    axes[1].grid(alpha=0.3)
    axes[1].legend(fontsize=9)

    plt.suptitle("How thin can the point cloud get before detection fails?",
                 fontsize=13, y=1.00)
    plt.tight_layout()
    plt.savefig(FIG_OUT, dpi=110, bbox_inches="tight")
    print(f"\nSaved {FIG_OUT}")
    plt.show()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quick", action="store_true",
                    help="fewer densities, 1m CHM only")
    ap.add_argument("--no-viz", action="store_true")
    args = ap.parse_args()

    if not Path(INPUT).exists():
        raise SystemExit(f"Missing {INPUT}")
    if not Path(TRUTH).exists():
        raise SystemExit(f"Missing {TRUTH}")

    densities = QUICK_DENSITIES if args.quick else TARGET_DENSITIES
    resolutions = [1.0] if args.quick else RESOLUTIONS

    results = run(densities, resolutions)
    results.to_csv(OUT_CSV, index=False)
    print(f"\nWrote {OUT_CSV}")
    report(results)

    if not args.no_viz:
        visualize(results)
