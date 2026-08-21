r"""
Canopy change detection across Finnish Forest Centre CHM epochs.

Sheet L4132D has full-coverage canopy height models for 2008, 2015 and 2020
on an identical 1 m grid, so the rasters difference pixel-for-pixel with no
resampling. Twelve years of canopy change over 3,600 hectares.

IMPORTANT CAVEAT, checked explicitly below:
Each epoch is a separate flight with its own sensor, point density and
processing chain. A difference raster therefore contains real change PLUS
methodological change, and the two are not separable from the rasters alone.
The tell is the ground: bare, unforested pixels should read ~0 m in every
epoch. If they don't, there is a systematic offset, and it must be reported
alongside any growth figure rather than quietly folded into it.

Change classes (after offset correction):
  harvest   large height loss, canopy removed
  loss      moderate height loss (thinning, windthrow, mortality)
  stable    within noise
  growth    moderate height gain
  regrowth  gain from a low starting height (replanting after clearcut)

Outputs:
  data/chm_change_<a>_<b>.tif   difference raster, metres
  data/chm_change.png           maps + histograms

Usage:
  python chm_change.py                          # 2008 vs 2020, full sheet
  python chm_change.py --a 2015 --b 2020
  python chm_change.py --aoi 364000 6685000 365000 6686000
  python chm_change.py --all-pairs              # every consecutive pair
"""
import argparse
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import from_bounds
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm

TILE_DIR = Path("data/metsakeskus")
SHEET = "L4132D"
FIG_OUT = "data/chm_change.png"

# Class thresholds in metres of height change
HARVEST_M = -5.0        # below this = canopy removed
LOSS_M = -1.5           # below this = measurable loss
GROWTH_M = 1.5          # above this = measurable gain
REGROWTH_START_M = 3.0  # gains from below this starting height = regrowth

GROUND_MAX_M = 0.5      # pixels this low in the EARLIER epoch are candidate bare ground
GROUND_DRIFT_M = 2.0    # how far those pixels may drift in the later epoch


def tile_path(year: str) -> Path:
    p = TILE_DIR / f"CHM_{SHEET}_{year}.tif"
    if not p.exists():
        raise SystemExit(
            f"Missing {p}\n"
            f"  python fetch_metsakeskus.py --sheet {SHEET} --year {year}"
        )
    return p


def read(year: str, aoi=None):
    """Read one epoch, optionally windowed to an AOI. Returns array, transform."""
    with rasterio.open(tile_path(year)) as src:
        if aoi:
            win = from_bounds(*aoi, src.transform)
            arr = src.read(1, window=win).astype("float32")
            transform = src.window_transform(win)
            bounds = aoi
        else:
            arr = src.read(1).astype("float32")
            transform = src.transform
            b = src.bounds
            bounds = (b.left, b.bottom, b.right, b.top)
        if src.nodata is not None:
            arr = np.where(arr == src.nodata, np.nan, arr)
    return arr, transform, bounds


def check_alignment(a, b, year_a, year_b):
    if a.shape != b.shape:
        raise SystemExit(
            f"Shape mismatch: {year_a} is {a.shape}, {year_b} is {b.shape}.\n"
            "These epochs are not on the same grid — reproject before differencing."
        )


def ground_offset(a, b):
    """
    Estimate systematic bias using pixels that are bare ground in the earlier epoch.

    Bare ground should measure ~0 m regardless of flight. A non-zero median
    difference over those pixels is a processing offset, not vegetation change.

    The window is deliberately asymmetric: requiring BOTH epochs to be near zero
    is circular, because an offset large enough to matter would push the later
    epoch above the threshold and hide itself. So ground is identified in epoch A
    and allowed to drift up to GROUND_DRIFT_M in epoch B. Genuine regrowth also
    lands in that window, but it is a minority and the median is robust to it.
    """
    bare = (a <= GROUND_MAX_M) & (b <= GROUND_MAX_M + GROUND_DRIFT_M) \
        & np.isfinite(a) & np.isfinite(b)
    n = int(bare.sum())
    if n < 1000:
        return 0.0, n, np.nan
    diff = b[bare] - a[bare]
    return float(np.median(diff)), n, float(np.percentile(np.abs(diff), 95))


def classify(a, b, diff):
    """Return an integer class raster: 0 harvest, 1 loss, 2 stable, 3 growth, 4 regrowth."""
    cls = np.full(diff.shape, 2, dtype="int8")          # stable
    cls[diff <= LOSS_M] = 1                             # loss
    cls[diff <= HARVEST_M] = 0                          # harvest
    cls[diff >= GROWTH_M] = 3                           # growth
    cls[(diff >= GROWTH_M) & (a < REGROWTH_START_M)] = 4  # regrowth from low canopy
    cls = np.where(np.isfinite(diff), cls, -1).astype("int8")
    return cls


# Starting-height bins for the stratified diagnostic
HEIGHT_BINS = [(0, 3), (3, 8), (8, 15), (15, 22), (22, 28), (28, 60)]


def by_height(a, diff, year_a, year_b, years_elapsed, bin_on=None, bin_year=None):
    """
    Break change down by starting height, to separate real growth from bias.

    Real height increment is strongly size-dependent: it peaks in young stands
    and decays toward zero at maturity. A sensor, density or seasonal difference
    between flights does not follow that curve.

    REGRESSION TO THE MEAN: binning by epoch A and then measuring (B - A) is
    biased. A pixel lands in a high bin partly because noise pushed it high, and
    that noise does not repeat, so it drifts down on remeasurement regardless of
    biology. The fix is to define the bins using an INDEPENDENT observation.
    When a third epoch exists, pass it as bin_on: its noise is uncorrelated with
    the noise in A and B, so the bins are unbiased. Falling back to (A+B)/2
    halves the effect but does not remove it.

    Plausible southern-boreal height increment, metres per year:
        0-3m    up to 0.6      3-8m    up to 0.6     8-15m   up to 0.5
        15-22m  up to 0.35    22-28m   up to 0.25   28m+     up to 0.15
    The floor is 0.0 everywhere: standing forest does not lose height without
    damage. Negative increment in a mature band is a data problem, not biology.
    """
    basis = a if bin_on is None else bin_on
    label = f"{year_a} height" if bin_on is None else f"{bin_year} height (independent)"
    if bin_on is None:
        print(f"\n  NOTE: bins defined by epoch {year_a}, which also enters the")
        print("        difference. Expect some regression-to-the-mean drag.")

    print(f"\nChange by starting height, binned on {label}:")
    print(f"  {'band':>12} {'pixels':>12} {'% area':>7} "
          f"{'mean gain':>10} {'m/yr':>7}  verdict")
    print("  " + "-" * 70)
    valid = np.isfinite(diff) & np.isfinite(basis)
    total = max(int(valid.sum()), 1)
    cap = {(0, 3): 0.6, (3, 8): 0.6, (8, 15): 0.5,
           (15, 22): 0.35, (22, 28): 0.25, (28, 60): 0.15}
    FLOOR = -0.02          # small negative tolerated as noise
    high, low = [], []
    for lo, hi in HEIGHT_BINS:
        m = (basis >= lo) & (basis < hi) & valid
        n = int(m.sum())
        if n == 0:
            continue
        gain = float(np.mean(diff[m]))
        rate = gain / years_elapsed
        c = cap[(lo, hi)]
        if rate > c:
            verdict = f"HIGH (max ~{c})"
            high.append((lo, hi, rate, c))
        elif rate < FLOOR:
            verdict = "NEGATIVE - trees do not shrink"
            low.append((lo, hi, rate))
        else:
            verdict = "ok"
        print(f"  {f'{lo}-{hi}m':>12} {n:12,} {100*n/total:6.1f}% "
              f"{gain:+9.2f}m {rate:+7.3f}  {verdict}")

    if not high and not low:
        print("\n  All bands within plausible increment — change looks real.")
        return
    if high:
        w = max(high, key=lambda x: x[2] / x[3])
        print(f"\n  {len(high)} band(s) above plausible increment.")
        print(f"  Worst: {w[0]}-{w[1]}m at {w[2]:+.3f} m/yr vs ~{w[3]:.2f} expected.")
        if w[0] >= 22:
            print("  Mature band inflated -> earlier epoch likely UNDER-measured canopy.")
    if low:
        w = min(low, key=lambda x: x[2])
        print(f"\n  {len(low)} band(s) show NEGATIVE increment.")
        print(f"  Worst: {w[0]}-{w[1]}m at {w[2]:+.3f} m/yr.")
        print("  Standing forest does not lose height. Likely causes:")
        print("    - leaf-on vs leaf-off acquisition (deciduous canopy collapses)")
        print("    - lower pulse density in the later epoch, missing crown apexes")
        print("    - different CHM processing or smoothing")
        print("  Growth rates from this pair are SUPPRESSED and should not be")
        print("  used as current annual increment for management decisions.")


def report(a, b, diff, cls, year_a, year_b, px_area_m2):
    line = "=" * 66
    print(line)
    print(f"CANOPY CHANGE  {year_a} -> {year_b}")
    print(line)

    valid = np.isfinite(diff)
    ha = px_area_m2 / 10_000.0

    print(f"\nEpoch means:  {year_a} {np.nanmean(a):5.2f}m   "
          f"{year_b} {np.nanmean(b):5.2f}m   "
          f"delta {np.nanmean(b) - np.nanmean(a):+5.2f}m")

    off, n_bare, spread = ground_offset(a, b)
    print(f"\nGround check (bare in {year_a}, allowed {GROUND_DRIFT_M}m drift by {year_b}):")
    print(f"  bare pixels     {n_bare:,} ({100*n_bare/valid.sum():.2f}% of area)")
    if n_bare >= 1000:
        print(f"  median offset   {off:+.2f}m   <- systematic bias between flights")
        print(f"  95th pct spread {spread:.2f}m")
        if abs(off) > 0.25:
            print("  WARNING: offset is large. Growth figures below are offset-corrected,")
            print("           but treat cross-epoch comparisons with caution.")
    else:
        print("  too few bare pixels to estimate an offset reliably")

    print("\nChange classes (offset-corrected):")
    names = {0: "harvest", 1: "loss", 2: "stable", 3: "growth", 4: "regrowth"}
    for k in [0, 1, 2, 3, 4]:
        m = cls == k
        pct = 100.0 * m.sum() / valid.sum() if valid.sum() else 0
        print(f"  {names[k]:9} {m.sum():10,} px  {m.sum()*ha:8.1f} ha  {pct:5.1f}%")

    grow = diff[(cls == 3) | (cls == 4)]
    lose = diff[(cls == 0) | (cls == 1)]
    print("\nMagnitudes:")
    if grow.size:
        print(f"  mean gain where growing  {grow.mean():+.2f}m")
    if lose.size:
        print(f"  mean loss where losing   {lose.mean():+.2f}m")
    print(f"  net change over all area {np.nanmean(diff):+.2f}m")
    print(line)


def visualize(a, b, diff, cls, bounds, year_a, year_b):
    extent = [bounds[0], bounds[2], bounds[1], bounds[3]]
    fig, axes = plt.subplots(2, 2, figsize=(14, 12))

    for ax, arr, title in [(axes[0][0], a, f"CHM {year_a}"),
                           (axes[0][1], b, f"CHM {year_b}")]:
        im = ax.imshow(arr, cmap="YlGn", extent=extent, origin="upper",
                       vmin=0, vmax=30)
        ax.set_title(f"{title}  (mean {np.nanmean(arr):.1f}m)")
        plt.colorbar(im, ax=ax, shrink=0.75, label="Height (m)")

    lim = 15
    im2 = axes[1][0].imshow(diff, cmap="RdBu_r", extent=extent, origin="upper",
                            vmin=-lim, vmax=lim)
    axes[1][0].set_title(f"Change {year_a} to {year_b}\n(red = loss, blue = gain)")
    plt.colorbar(im2, ax=axes[1][0], shrink=0.75, label="Height change (m)")

    colors = ["#8b0000", "#e08214", "#f0f0f0", "#66bd63", "#1a9850"]
    cmap = ListedColormap(colors)
    norm = BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5, 4.5], cmap.N)
    axes[1][1].imshow(np.where(cls >= 0, cls, np.nan), cmap=cmap, norm=norm,
                      extent=extent, origin="upper")
    axes[1][1].set_title("Change classes")
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in colors]
    axes[1][1].legend(handles, ["harvest", "loss", "stable", "growth", "regrowth"],
                      loc="lower right", fontsize=8, framealpha=0.9)

    for ax in axes.ravel():
        ax.set_xlabel("Easting (m, TM35FIN)")
        ax.set_ylabel("Northing (m, TM35FIN)")

    plt.suptitle(
        f"Nuuksio area canopy change, sheet {SHEET}\n"
        "Data: Suomen metsakeskus / Finnish Forest Centre, CC BY 4.0",
        fontsize=12, y=1.00)
    plt.tight_layout()
    plt.savefig(FIG_OUT, dpi=110, bbox_inches="tight")
    print(f"\nSaved {FIG_OUT}")
    plt.show()


def run_pair(year_a, year_b, aoi, do_viz, write_tif, stratify=False, bin_on=None):
    a, transform, bounds = read(year_a, aoi)
    b, _, _ = read(year_b, aoi)
    check_alignment(a, b, year_a, year_b)

    raw = b - a
    off, n_bare, _ = ground_offset(a, b)
    diff = raw - off        # remove systematic bias before classifying

    cls = classify(a, b, diff)
    px_area = abs(transform.a * transform.e)
    report(a, b, diff, cls, year_a, year_b, px_area)

    if stratify:
        elapsed = abs(int(year_b) - int(year_a))
        basis, basis_year = None, None
        if bin_on:
            try:
                basis, _, _ = read(bin_on, aoi)
                if basis.shape == a.shape:
                    basis_year = bin_on
                else:
                    print(f"  (bin epoch {bin_on} grid differs; falling back)")
                    basis = None
            except SystemExit:
                print(f"  (bin epoch {bin_on} unavailable; falling back)")
        by_height(a, diff, year_a, year_b, elapsed, basis, basis_year)

    if write_tif:
        out = f"data/chm_change_{year_a}_{year_b}.tif"
        prof = dict(driver="GTiff", height=diff.shape[0], width=diff.shape[1],
                    count=1, dtype="float32", crs="EPSG:3067",
                    transform=transform, nodata=-9999, compress="deflate")
        with rasterio.open(out, "w", **prof) as dst:
            dst.write(np.where(np.isfinite(diff), diff, -9999).astype("float32"), 1)
        print(f"Wrote {out}")

    if do_viz:
        visualize(a, b, diff, cls, bounds, year_a, year_b)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--a", default="2008", help="earlier epoch (default 2008)")
    ap.add_argument("--b", default="2020", help="later epoch (default 2020)")
    ap.add_argument("--aoi", nargs=4, type=float,
                    metavar=("MINX", "MINY", "MAXX", "MAXY"),
                    help="restrict to this box, EPSG:3067 (default: whole tile)")
    ap.add_argument("--all-pairs", action="store_true",
                    help="run 2008-2015, 2015-2020 and 2008-2020, no plots")
    ap.add_argument("--bin-on", metavar="YEAR",
                    help="define height bins from this third epoch, removing "
                         "regression-to-the-mean (e.g. --a 2008 --b 2020 --bin-on 2015)")
    ap.add_argument("--by-height", action="store_true",
                    help="break change down by starting height (bias diagnostic)")
    ap.add_argument("--no-viz", action="store_true")
    ap.add_argument("--no-tif", action="store_true")
    args = ap.parse_args()

    if args.all_pairs:
        for ya, yb in [("2008", "2015"), ("2015", "2020"), ("2008", "2020")]:
            run_pair(ya, yb, args.aoi, do_viz=False, write_tif=not args.no_tif,
                     stratify=args.by_height, bin_on=args.bin_on)
            print()
    else:
        run_pair(args.a, args.b, args.aoi,
                 do_viz=not args.no_viz, write_tif=not args.no_tif,
                 stratify=args.by_height, bin_on=args.bin_on)
