"""
Detect individual trees from the CHM and compare to ground truth.

Method: local-maximum filter on a Gaussian-smoothed CHM.
Each pixel that is the highest within a window of size = 2*R+1
and above a minimum height threshold is called a tree top.

Then match each detection to the nearest truth tree within MATCH_DIST.
Report: recall (% of real trees found), precision (% of detections that were real),
height accuracy, and per-species performance.
"""
from pathlib import Path
import numpy as np
import pandas as pd
import rasterio
from scipy.ndimage import maximum_filter, gaussian_filter
import matplotlib.pyplot as plt

CHM_PATH = "data/nuuksio_chm.tif"
TRUTH_PATH = "data/nuuksio_tree_truth.csv"
OUT_CSV = "data/nuuksio_detected_trees.csv"
FIG_OUT = "data/nuuksio_detection.png"

# Detection parameters (worth tuning!)
SMOOTH_SIGMA = 0.6      # gaussian smoothing before peak detection (pixels)
WINDOW_RADIUS = 3       # local-max window radius (pixels ≈ meters)
MIN_HEIGHT_M = 6.0      # trees shorter than this are ignored (skips snags)
MATCH_DIST_M = 3.0      # detection is a match if within this of a truth tree


def load_chm():
    with rasterio.open(CHM_PATH) as src:
        chm = src.read(1).astype(float)
        chm = np.where(chm == src.nodata, 0.0, chm)  # treat nodata as ground
        transform = src.transform
        bounds = src.bounds
    return chm, transform, bounds


def detect_tops(chm, transform):
    """Return DataFrame of detected trees with x, y, height."""
    # Smooth slightly to suppress single-pixel spikes / noise
    chm_smooth = gaussian_filter(chm, sigma=SMOOTH_SIGMA)

    # Local maximum filter: each pixel = max within its window
    win = 2 * WINDOW_RADIUS + 1
    local_max = maximum_filter(chm_smooth, size=win)

    # Peaks: pixel equals local max AND above threshold
    peaks = (chm_smooth == local_max) & (chm_smooth >= MIN_HEIGHT_M)
    rows, cols = np.where(peaks)

    # Use the original (unsmoothed) height at each peak — smoothing lowers heights
    heights = chm[rows, cols]

    # Convert pixel → world coords. rasterio's transform gives top-left origin.
    xs, ys = rasterio.transform.xy(transform, rows, cols)

    return pd.DataFrame({
        "x_tm35fin": np.array(xs),
        "y_tm35fin": np.array(ys),
        "height_m": heights,
    })


def match_to_truth(detected: pd.DataFrame, truth: pd.DataFrame):
    """
    Greedy nearest-neighbor matching:
    For each truth tree, find closest detection within MATCH_DIST.
    Each detection can only match one truth (highest priority to tallest truth).
    """
    truth_sorted = truth.sort_values("height_m", ascending=False).reset_index(drop=True)
    det = detected.copy().reset_index(drop=True)
    det["matched_truth"] = -1

    dx = det["x_tm35fin"].to_numpy()
    dy = det["y_tm35fin"].to_numpy()
    dh = det["height_m"].to_numpy()
    used = np.zeros(len(det), dtype=bool)

    match_truth_idx = np.full(len(truth_sorted), -1, dtype=int)
    for ti, row in truth_sorted.iterrows():
        d2 = (dx - row["x_tm35fin"]) ** 2 + (dy - row["y_tm35fin"]) ** 2
        d2[used] = np.inf
        j = int(np.argmin(d2))
        if d2[j] <= MATCH_DIST_M ** 2:
            match_truth_idx[ti] = j
            used[j] = True

    truth_sorted["detected_idx"] = match_truth_idx
    truth_sorted["detected"] = match_truth_idx >= 0
    # attach detected height where matched
    truth_sorted["detected_height_m"] = np.where(
        match_truth_idx >= 0, dh[match_truth_idx], np.nan
    )
    det["is_true_positive"] = used
    return det, truth_sorted


def report(det, truth_matched):
    n_truth = len(truth_matched)
    n_det = len(det)
    tp = int(truth_matched["detected"].sum())
    fp = n_det - tp
    fn = n_truth - tp

    recall = tp / n_truth if n_truth else 0
    precision = tp / n_det if n_det else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

    print("=" * 60)
    print("DETECTION RESULTS")
    print("=" * 60)
    print(f"  Ground truth trees:  {n_truth}")
    print(f"  Detected peaks:      {n_det}")
    print(f"  True positives:      {tp}")
    print(f"  False positives:     {fp}  (detections with no matching tree)")
    print(f"  False negatives:     {fn}  (real trees we missed)")
    print()
    print(f"  Recall:    {recall*100:5.1f}%   ← % of real trees found")
    print(f"  Precision: {precision*100:5.1f}%   ← % of detections that were real")
    print(f"  F1:        {f1*100:5.1f}%")
    print()

    # Per-species recall
    print("Recall by species (bigger trees are easier):")
    for sp in ["spruce", "pine", "birch"]:
        m = truth_matched["species"] == sp
        if m.any():
            r = truth_matched.loc[m, "detected"].mean()
            n = m.sum()
            mean_h = truth_matched.loc[m, "height_m"].mean()
            print(f"  {sp:6}: {r*100:5.1f}%  ({int(r*n)}/{n} found, avg height {mean_h:.1f}m)")

    # Height accuracy for matched trees
    m = truth_matched["detected"]
    if m.any():
        err = truth_matched.loc[m, "detected_height_m"] - truth_matched.loc[m, "height_m"]
        print()
        print("Height error (detected - truth), for matched trees:")
        print(f"  mean bias:  {err.mean():+.2f}m")
        print(f"  RMSE:       {(err**2).mean()**0.5:.2f}m")
        print(f"  90% within: ±{np.percentile(np.abs(err), 90):.2f}m")
    print("=" * 60)


def visualize(det, truth_matched, chm, bounds):
    extent = [bounds.left, bounds.right, bounds.bottom, bounds.top]
    chm_disp = np.flipud(chm)

    fig, axes = plt.subplots(1, 2, figsize=(15, 7))

    # Panel 1: detections on CHM
    axes[0].imshow(chm_disp, cmap="YlGn", extent=extent, origin="lower",
                    vmin=0, vmax=40, alpha=0.75)
    tp = det[det["is_true_positive"]]
    fp = det[~det["is_true_positive"]]
    axes[0].scatter(tp["x_tm35fin"], tp["y_tm35fin"], c="blue", s=12,
                    label=f"True positive ({len(tp)})",
                    edgecolor="white", linewidth=0.3)
    axes[0].scatter(fp["x_tm35fin"], fp["y_tm35fin"], c="red", s=25,
                    marker="x", label=f"False positive ({len(fp)})", linewidth=1.5)
    axes[0].set_title("Detections on CHM\n(blue = correct, red X = spurious)")
    axes[0].legend(loc="lower right", fontsize=9)
    axes[0].set_xlabel("Easting (m, TM35FIN)")
    axes[0].set_ylabel("Northing (m, TM35FIN)")

    # Panel 2: missed truth trees
    axes[1].imshow(chm_disp, cmap="YlGn", extent=extent, origin="lower",
                    vmin=0, vmax=40, alpha=0.75)
    found = truth_matched[truth_matched["detected"]]
    missed = truth_matched[~truth_matched["detected"]]
    axes[1].scatter(found["x_tm35fin"], found["y_tm35fin"], c="blue", s=8,
                    label=f"Found ({len(found)})",
                    edgecolor="white", linewidth=0.3)
    axes[1].scatter(missed["x_tm35fin"], missed["y_tm35fin"], c="orange", s=40,
                    marker="o", label=f"Missed ({len(missed)})",
                    edgecolor="black", linewidth=0.8, alpha=0.9)
    axes[1].set_title("Ground truth vs detections\n(orange = trees we missed)")
    axes[1].legend(loc="lower right", fontsize=9)
    axes[1].set_xlabel("Easting (m, TM35FIN)")
    axes[1].set_ylabel("Northing (m, TM35FIN)")

    plt.suptitle(
        f"Tree detection — window={2*WINDOW_RADIUS+1}m, min_height={MIN_HEIGHT_M}m",
        fontsize=12, y=1.00
    )
    plt.tight_layout()
    plt.savefig(FIG_OUT, dpi=110, bbox_inches="tight")
    print(f"\nSaved {FIG_OUT}")
    plt.show()


if __name__ == "__main__":
    if not Path(CHM_PATH).exists():
        raise SystemExit(f"Missing {CHM_PATH} — run nuuksio_workflow.py first")

    chm, transform, bounds = load_chm()
    detected = detect_tops(chm, transform)
    truth = pd.read_csv(TRUTH_PATH)

    detected, truth_matched = match_to_truth(detected, truth)
    detected.to_csv(OUT_CSV, index=False)
    print(f"Wrote {OUT_CSV}: {len(detected)} detections\n")

    report(detected, truth_matched)
    visualize(detected, truth_matched, chm, bounds)
