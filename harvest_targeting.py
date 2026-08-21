r"""
Harvest targeting from multi-epoch canopy height models.

The question a forestry operator actually asks is not "where are the trees" but
"which stands are ready, and within them, which stems come out and which stay".
This script answers that from two CHM epochs.

The decision rule is the standard silvicultural one. A stand is ready when its
CURRENT annual increment falls below its MEAN annual increment — the point of
culmination, after which you are storing wood at a declining rate and the site
is better replanted. We can observe both directly:

    mean annual increment (MAI)     = height_now / stand_age_proxy
    current annual increment (CAI)  = (height_now - height_then) / years

We have no stand age, so dominant height serves as the maturity proxy — standard
practice in even-aged boreal management, where site index is defined on dominant
height at a reference age.

Within a target stand, leave trees are selected rather than left to chance:
Finnish practice retains roughly 10 stems/ha, biased toward the largest and
most dispersed, for structural and habitat value.

Pipeline:
  1. Variable-window local maxima on the later CHM  -> individual stems
  2. Sample the earlier CHM at each stem            -> per-stem height growth
  3. Aggregate to stands on a grid                  -> density, dominant height, CAI
  4. Rank stands by readiness                       -> harvest priority
  5. Select retention stems inside target stands    -> leave trees

WHAT THIS DOES NOT KNOW — read before believing any output:
  * No terrain. The CHM is height above ground only, so slope, wetness and
    machine trafficability are invisible. Operability is unassessed.
  * No species. Value per cubic metre differs sharply between spruce, pine and
    birch, and the CHM cannot distinguish them.
  * No diameter. Volume needs DBH; height alone gives an ordering, not m3.
    This script deliberately reports height, never fabricated volume.
  * No land status. Sheet L4132D overlaps Nuuksio National Park and other
    protected land. Nothing here should be cut. A real system MUST join
    protection and ownership boundaries before proposing anything.
  * Detection under-counts. Local maxima merge adjacent crowns; suppressed
    understory stems are invisible. Densities are lower bounds.

Outputs:
  data/harvest_stems.csv      detected stems with height and growth
  data/harvest_stands.csv     stand-level metrics and priority
  data/harvest_targeting.png  maps

Usage:
  python harvest_targeting.py --aoi 364000 6685000 365000 6686000
  python harvest_targeting.py --aoi ... --stand-size 100 --top 15
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.windows import from_bounds
from scipy.ndimage import maximum_filter, gaussian_filter
import matplotlib.pyplot as plt

TILE_DIR = Path("data/metsakeskus")
SHEET = "L4132D"
STEMS_CSV = "data/harvest_stems.csv"
STANDS_CSV = "data/harvest_stands.csv"
FIG_OUT = "data/harvest_targeting.png"

MIN_TREE_H = 5.0        # below this is not a tree top worth detecting
SMOOTH_M = 0.5
STAND_M = 100.0         # stand cell size, metres
MIN_STEMS_PER_STAND = 20

# Variable local-max window: radius grows with canopy height, since crown
# width scales with tree size. A fixed window over-splits tall crowns and
# merges short ones.
WIN_MIN_M, WIN_MAX_M = 3.0, 11.0
WIN_SLOPE = 0.22        # metres of window per metre of height

# Site index H100: dominant height reached at age 100. 27m is a good southern
# Finland spruce site. Height development follows a Chapman-Richards curve,
# inverted below to estimate stand age from observed dominant height.
SITE_INDEX_H100 = 27.0
CR_K, CR_P = 0.023, 1.30
RETENTION_PER_HA = 10   # leave trees retained per hectare
MIN_HARVEST_DOM_H = 16.0   # below this nothing is merchantable, hard floor


def age_from_dominant_height(dom_h):
    """
    Invert a Chapman-Richards height curve to estimate stand age.

        H(age) = H100 * (1 - exp(-k*age))**p

    Approximate, and it assumes a single site index across the AOI, which is
    wrong in detail — site quality varies with soil and drainage. It is good
    enough to order stands by maturity, which is all it is used for.
    """
    h = np.clip(np.asarray(dom_h, dtype=float), 0.1, SITE_INDEX_H100 * 0.98)
    inner = 1.0 - (h / SITE_INDEX_H100) ** (1.0 / CR_P)
    return np.clip(-np.log(np.clip(inner, 1e-6, 1.0)) / CR_K, 1.0, 200.0)


def read_chm(year, aoi):
    p = TILE_DIR / f"CHM_{SHEET}_{year}.tif"
    if not p.exists():
        raise SystemExit(f"Missing {p}\n  python fetch_metsakeskus.py --sheet {SHEET} --year {year}")
    with rasterio.open(p) as src:
        win = from_bounds(*aoi, src.transform)
        arr = src.read(1, window=win).astype("float32")
        transform = src.window_transform(win)
        if src.nodata is not None:
            arr = np.where(arr == src.nodata, np.nan, arr)
    return arr, transform


def detect_stems(chm, transform):
    """Variable-window local maxima. Window radius scales with local height."""
    res = abs(transform.a)
    filled = np.nan_to_num(chm, nan=0.0)
    smooth = gaussian_filter(filled, sigma=max(SMOOTH_M / res, 0.01))

    # Bin heights and run an appropriately sized window per band, then combine.
    peaks = np.zeros(smooth.shape, dtype=bool)
    bands = [(5, 10), (10, 16), (16, 22), (22, 28), (28, 100)]
    for lo, hi in bands:
        h_mid = (lo + min(hi, 40)) / 2.0
        win_m = np.clip(WIN_MIN_M + WIN_SLOPE * h_mid, WIN_MIN_M, WIN_MAX_M)
        win_px = max(int(round(win_m / res)), 3)
        if win_px % 2 == 0:
            win_px += 1
        local = maximum_filter(smooth, size=win_px)
        band = (smooth >= lo) & (smooth < hi) & (smooth == local)
        peaks |= band

    peaks &= smooth >= MIN_TREE_H
    rows, cols = np.where(peaks)
    xs, ys = rasterio.transform.xy(transform, rows, cols)
    return pd.DataFrame({
        "x": np.asarray(xs), "y": np.asarray(ys),
        "row": rows, "col": cols,
        "height_m": chm[rows, cols].astype(float),
    })


def add_growth(stems, chm_then, years):
    """Sample the earlier epoch at each stem location."""
    h_then = chm_then[stems["row"].values, stems["col"].values].astype(float)
    stems = stems.copy()
    stems["height_then_m"] = h_then
    stems["growth_m"] = stems["height_m"] - h_then
    stems["cai_m_yr"] = stems["growth_m"] / years
    return stems


MIN_FOREST_FRAC = 0.35      # cell must be at least this fraction canopy
FOREST_H = 2.0              # pixels above this count as vegetated
MAX_WATER_FRAC = 0.40       # reject cells this waterlogged / open


def cell_cover(chm, transform, aoi, stand_m):
    """
    Per-cell land cover, so water and open ground stop masquerading as stands.

    The Forest Centre CHM has no nodata: water is simply 0 m. A cell straddling
    a shoreline therefore collects the shore trees, clears the stem minimum, and
    plots at its centroid — in the lake. Measuring the canopy fraction directly
    removes those, and lets density be computed over the FORESTED area rather
    than the whole cell, which is the honest denominator.
    """
    res = abs(transform.a)
    n = int(round(stand_m / res))
    minx, miny, maxx, maxy = aoi
    rows, cols = {}, {}
    out = []
    h, w = chm.shape
    for r0 in range(0, h - n + 1, n):
        for c0 in range(0, w - n + 1, n):
            blk = chm[r0:r0 + n, c0:c0 + n]
            veg = float(np.mean(blk > FOREST_H))
            flat = float(np.mean(blk <= 0.05))       # exactly-zero = water/bare
            x = minx + c0 * res
            y = maxy - (r0 + n) * res
            out.append({"stand_x": int(np.floor(x / stand_m) * stand_m),
                        "stand_y": int(np.floor(y / stand_m) * stand_m),
                        "forest_frac": veg, "flat_frac": flat,
                        "forest_ha": veg * (stand_m ** 2) / 10_000.0})
    return pd.DataFrame(out)


def build_stands(stems, aoi, stand_m, years, cover=None):
    minx, miny, maxx, maxy = aoi
    stems = stems.copy()
    stems["stand_x"] = (np.floor((stems["x"] - minx) / stand_m) * stand_m + minx).astype(int)
    stems["stand_y"] = (np.floor((stems["y"] - miny) / stand_m) * stand_m + miny).astype(int)

    ha = (stand_m ** 2) / 10_000.0
    g = stems.groupby(["stand_x", "stand_y"])
    stands = g.agg(
        n_stems=("height_m", "size"),
        mean_h=("height_m", "mean"),
        max_h=("height_m", "max"),
        mean_cai=("cai_m_yr", "mean"),
    ).reset_index()

    # Dominant height: mean of the tallest 100 stems/ha, standard forestry definition
    n_dom = max(int(round(100 * ha)), 3)
    dom = g["height_m"].apply(lambda s: s.nlargest(min(n_dom, len(s))).mean())
    stands = stands.merge(dom.rename("dom_h").reset_index(), on=["stand_x", "stand_y"])

    stands = stands[stands["n_stems"] >= MIN_STEMS_PER_STAND].copy()

    if cover is not None:
        stands = stands.merge(cover, on=["stand_x", "stand_y"], how="left")
        stands["forest_frac"] = stands["forest_frac"].fillna(1.0)
        stands["flat_frac"] = stands["flat_frac"].fillna(0.0)
        stands["forest_ha"] = stands["forest_ha"].fillna(ha)
    else:
        stands["forest_frac"] = 1.0
        stands["flat_frac"] = 0.0
        stands["forest_ha"] = ha

    # Density over FORESTED area, not cell area
    stands["stems_per_ha"] = stands["n_stems"] / stands["forest_ha"].clip(lower=0.01)

    stands["age_est"] = age_from_dominant_height(stands["dom_h"])
    stands["mai"] = stands["dom_h"] / stands["age_est"]
    stands["cai"] = stands["mean_cai"]

    # The absolute test CAI < MAI needs unbiased CAI, which cross-epoch canopy
    # bias destroys. An additive offset preserves ORDER though, so rank by CAI
    # percentile instead: slowest-growing mature stands rise to the top, and the
    # ranking survives a bias the absolute test would not.
    stands["cai_pct"] = stands["cai"].rank(pct=True)
    stands["slowness"] = 1.0 - stands["cai_pct"]
    stands["maturity_pct"] = stands["dom_h"].rank(pct=True)
    stands["priority"] = 0.55 * stands["slowness"] + 0.45 * stands["maturity_pct"]
    stands["ready"] = stands["cai"] < stands["mai"]     # kept for reference only

    # Hard gates
    stands.loc[stands["dom_h"] < MIN_HARVEST_DOM_H, "priority"] = 0.0
    stands.loc[stands["forest_frac"] < MIN_FOREST_FRAC, "priority"] = 0.0
    stands.loc[stands["flat_frac"] > MAX_WATER_FRAC, "priority"] = 0.0

    return stands.sort_values("priority", ascending=False).reset_index(drop=True)


def select_leave_trees(stems, target_stands, stand_m):
    """Retain the largest, most dispersed stems inside each target stand."""
    ha = (stand_m ** 2) / 10_000.0
    keep_n = max(int(round(RETENTION_PER_HA * ha)), 1)
    keys = set(zip(target_stands["stand_x"], target_stands["stand_y"]))
    stems = stems.copy()
    stems["in_target"] = [ (sx, sy) in keys
                           for sx, sy in zip(stems["stand_x"], stems["stand_y"]) ]
    stems["leave_tree"] = False
    for (sx, sy), grp in stems[stems["in_target"]].groupby(["stand_x", "stand_y"]):
        idx = grp.nlargest(keep_n, "height_m").index
        stems.loc[idx, "leave_tree"] = True
    stems["harvest"] = stems["in_target"] & ~stems["leave_tree"]
    return stems, keep_n


def apply_exclusions(stands, stand_m, exclude_path):
    """
    Drop stands intersecting protected or excluded land.

    This is a HARD requirement, not a refinement. Sheet L4132D overlaps Nuuksio
    National Park. A targeting system with no land-status layer will happily
    propose clearcutting protected forest, and no accuracy metric excuses that.
    Supply a polygon file (GeoPackage, shapefile, GeoJSON) in EPSG:3067.
    """
    if not exclude_path:
        print("\n" + "!" * 70)
        print("!! NO EXCLUSION LAYER SUPPLIED")
        print("!! Protected areas, other ownerships and buffers are NOT filtered.")
        print("!! Sheet L4132D overlaps Nuuksio National Park. Some stands below")
        print("!! may sit on land where harvesting is illegal.")
        print("!! Pass --exclude <polygons.gpkg> before acting on any of this.")
        print("!" * 70)
        return stands, 0

    try:
        import geopandas as gpd
        from shapely.geometry import box
    except ImportError:
        raise SystemExit("--exclude needs geopandas:  pixi add geopandas")

    if not Path(exclude_path).exists():
        raise SystemExit(f"Exclusion layer not found: {exclude_path}")

    ex = gpd.read_file(exclude_path)
    if ex.crs is None:
        print(f"  WARNING: {exclude_path} has no CRS; assuming EPSG:3067")
        ex = ex.set_crs(3067)
    elif ex.crs.to_epsg() != 3067:
        ex = ex.to_crs(3067)

    cells = gpd.GeoDataFrame(
        stands.copy(),
        geometry=[box(x, y, x + stand_m, y + stand_m)
                  for x, y in zip(stands["stand_x"], stands["stand_y"])],
        crs=3067)
    hit = gpd.sjoin(cells, ex[["geometry"]], how="inner", predicate="intersects")
    blocked = set(zip(hit["stand_x"], hit["stand_y"]))
    keep = ~cells.apply(lambda r: (r["stand_x"], r["stand_y"]) in blocked, axis=1)
    n_drop = int((~keep).sum())
    print(f"\nExclusions from {Path(exclude_path).name}: "
          f"{n_drop} stand(s) removed, {int(keep.sum())} remain")
    return stands[keep.values].reset_index(drop=True), n_drop


def check_cai_usable(stems, year_a, year_b):
    """
    Refuse to plan on a suppressed epoch pair.

    If tall stems show negative height change, the pair has a canopy bias and
    every CAI is understated — which makes every stand look culminated and the
    whole ranking meaningless.
    """
    tall = stems[stems["height_m"] >= 22]
    if len(tall) < 50:
        return True
    med = float(tall["cai_m_yr"].median())
    print(f"\nCAI sanity check ({year_a}->{year_b}):")
    print(f"  median increment, stems >=22m:  {med:+.3f} m/yr")
    print(f"  biologically plausible range:   0.00 to 0.25 m/yr")
    if med > 0.25:
        print("  FAIL. Mature stems show implausibly FAST height growth, so the")
        print("  earlier epoch under-measured canopy. Absolute CAI is inflated and")
        print("  the culmination test (CAI < MAI) cannot be trusted.")
        print("  Stands are therefore ranked by CAI PERCENTILE, which survives an")
        print("  additive bias. Treat absolute growth figures as unreliable.")
        return "rank_only"
    if med < -0.02:
        print("  FAIL. Mature stems show negative height change, so this epoch")
        print("  pair under-measures canopy. Every CAI is biased low, every stand")
        print("  will read as culminated, and the ranking below is not meaningful.")
        print("  Re-run with a different pair, e.g. --a 2008 --b 2020")
        return False
    print("  ok — mature increment is plausible")
    return True


def report(stems, stands, years, year_a, year_b, top_n, stand_m, keep_n):
    line = "=" * 70
    print(line)
    print(f"HARVEST TARGETING  {year_a} -> {year_b}  ({years} yr window)")
    print(line)

    print(f"\nStems detected      {len(stems):,}")
    print(f"  height    mean {stems['height_m'].mean():.1f}m  max {stems['height_m'].max():.1f}m")
    print(f"  growth    mean {stems['cai_m_yr'].mean():+.3f} m/yr")

    print(f"\nStands ({stand_m:.0f}m cells, >= {MIN_STEMS_PER_STAND} stems)   {len(stands):,}")
    print(f"  stems/ha  mean {stands['stems_per_ha'].mean():.0f}  "
          f"range {stands['stems_per_ha'].min():.0f}-{stands['stems_per_ha'].max():.0f}")
    print(f"  dom height mean {stands['dom_h'].mean():.1f}m")

    ready = stands[stands["priority"] > 0]
    too_young = int((stands["dom_h"] < MIN_HARVEST_DOM_H).sum())
    not_culm = int((~stands["ready"]).sum())
    n_open = int((stands["forest_frac"] < MIN_FOREST_FRAC).sum())
    n_water = int((stands["flat_frac"] > MAX_WATER_FRAC).sum())
    print(f"\nEligibility:")
    print(f"  below merchantable height ({MIN_HARVEST_DOM_H:.0f}m)   {too_young}")
    print(f"  under {MIN_FOREST_FRAC:.0%} canopy cover (open/clearcut)  {n_open}")
    print(f"  over {MAX_WATER_FRAC:.0%} water or bare ground          {n_water}")
    print(f"  ELIGIBLE                                {len(ready)} of {len(stands)}")
    print(f"  (reference: {not_culm} would fail an absolute CAI<MAI test)")

    if ready.empty:
        print("\n  No stand qualifies. Nothing to send robots to.")
        return

    print(f"\nTop {min(top_n, len(ready))} by maturity and slowing growth:")
    print(f"  {'easting':>8} {'northing':>9} {'st/ha':>6} {'dom_h':>6} "
          f"{'age':>5} {'for%':>5} {'CAI':>7} {'prio':>6}")
    print("  " + "-" * 64)
    for _, r in ready.head(top_n).iterrows():
        print(f"  {r['stand_x']:8.0f} {r['stand_y']:9.0f} "
              f"{r['stems_per_ha']:6.0f} {r['dom_h']:6.1f} {r['age_est']:5.0f} "
              f"{100*r['forest_frac']:5.0f} {r['cai']:+7.3f} {r['priority']:6.2f}")

    n_h = int(stems["harvest"].sum())
    n_l = int(stems["leave_tree"].sum())
    print(f"\nStem-level plan across top {top_n} stands:")
    print(f"  harvest      {n_h:,} stems")
    print(f"  retain       {n_l:,} stems  ({keep_n}/stand, ~{RETENTION_PER_HA}/ha)")
    if n_h:
        print(f"  mean height of harvested stems  {stems.loc[stems['harvest'],'height_m'].mean():.1f}m")
        print(f"  mean height of retained stems   {stems.loc[stems['leave_tree'],'height_m'].mean():.1f}m")
    print("\n  Reminder: no terrain, species, diameter or protection status.")
    print("  This is a candidate list for a forester to check, not a work order.")
    print(line)


def visualize(chm, transform, stems, stands, aoi, top_n, stand_m):
    extent = [aoi[0], aoi[2], aoi[1], aoi[3]]
    fig, axes = plt.subplots(1, 3, figsize=(19, 6.2))

    axes[0].imshow(chm, cmap="YlGn", extent=extent, origin="upper", vmin=0, vmax=30)
    axes[0].scatter(stems["x"], stems["y"], s=1.2, c="black", alpha=0.5)
    axes[0].set_title(f"Detected stems on CHM\n({len(stems):,} stems)")

    sc = axes[1].scatter(stands["stand_x"] + stand_m / 2, stands["stand_y"] + stand_m / 2,
                         c=stands["dom_h"], s=stand_m * 2.2, marker="s",
                         cmap="viridis", vmin=8, vmax=28)
    axes[1].set_title("Stand dominant height")
    plt.colorbar(sc, ax=axes[1], shrink=0.8, label="Dominant height (m)")

    axes[2].imshow(chm, cmap="Greys_r", extent=extent, origin="upper",
                   vmin=0, vmax=30, alpha=0.55)
    tgt = stands[stands["priority"] > 0].head(top_n)
    axes[2].scatter(tgt["stand_x"] + stand_m / 2, tgt["stand_y"] + stand_m / 2,
                    s=stand_m * 2.2, marker="s", facecolor="none",
                    edgecolor="crimson", linewidth=1.6, label="target stand")
    h = stems[stems["harvest"]]
    l = stems[stems["leave_tree"]]
    axes[2].scatter(h["x"], h["y"], s=2.5, c="darkorange", label=f"harvest ({len(h):,})")
    axes[2].scatter(l["x"], l["y"], s=26, c="royalblue", marker="^",
                    edgecolor="white", linewidth=0.4, label=f"leave ({len(l):,})")
    axes[2].legend(loc="lower right", fontsize=8, framealpha=0.9)
    axes[2].set_title("Harvest plan: target stands, take and leave")

    for ax in axes:
        ax.set_xlabel("Easting (m, TM35FIN)")
        ax.set_ylabel("Northing (m, TM35FIN)")
        ax.set_xlim(aoi[0], aoi[2])
        ax.set_ylim(aoi[1], aoi[3])

    plt.suptitle("Harvest targeting from canopy height change\n"
                 "Data: Suomen metsakeskus / Finnish Forest Centre, CC BY 4.0",
                 fontsize=12, y=1.02)
    plt.tight_layout()
    plt.savefig(FIG_OUT, dpi=110, bbox_inches="tight")
    print(f"\nSaved {FIG_OUT}")
    plt.show()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aoi", nargs=4, type=float, required=True,
                    metavar=("MINX", "MINY", "MAXX", "MAXY"))
    ap.add_argument("--a", default="2015", help="earlier epoch (default 2015)")
    ap.add_argument("--b", default="2020", help="later epoch (default 2020)")
    ap.add_argument("--stand-size", type=float, default=STAND_M)
    ap.add_argument("--top", type=int, default=10, help="stands to target")
    ap.add_argument("--exclude", metavar="POLYGONS",
                    help="polygon file (EPSG:3067) of protected/off-limits land; "
                         "any stand intersecting it is dropped")
    ap.add_argument("--force", action="store_true",
                    help="proceed even if the CAI sanity check fails")
    ap.add_argument("--no-viz", action="store_true")
    args = ap.parse_args()

    years = abs(int(args.b) - int(args.a))
    chm_b, transform = read_chm(args.b, args.aoi)
    chm_a, _ = read_chm(args.a, args.aoi)
    if chm_a.shape != chm_b.shape:
        raise SystemExit("Epoch grids differ — cannot compare stem by stem.")

    stems = detect_stems(chm_b, transform)
    if stems.empty:
        raise SystemExit("No stems detected — check the AOI is forested.")
    stems = add_growth(stems, chm_a, years)
    verdict = check_cai_usable(stems, args.a, args.b)
    if verdict is False and not args.force:
        raise SystemExit("\nStopping. Use a cleaner epoch pair, or --force to override.")

    cover = cell_cover(chm_b, transform, args.aoi, args.stand_size)
    stands = build_stands(stems, args.aoi, args.stand_size, years, cover)
    if stands.empty:
        raise SystemExit("No stands met the minimum stem count — try a larger AOI.")

    stands, _ = apply_exclusions(stands, args.stand_size, args.exclude)
    if stands.empty:
        raise SystemExit("All stands excluded.")

    stems["stand_x"] = (np.floor((stems["x"] - args.aoi[0]) / args.stand_size)
                        * args.stand_size + args.aoi[0]).astype(int)
    stems["stand_y"] = (np.floor((stems["y"] - args.aoi[1]) / args.stand_size)
                        * args.stand_size + args.aoi[1]).astype(int)
    eligible = stands[stands["priority"] > 0]
    stems, keep_n = select_leave_trees(stems, eligible.head(args.top), args.stand_size)

    report(stems, stands, years, args.a, args.b, args.top, args.stand_size, keep_n)

    stems.drop(columns=["row", "col"]).to_csv(STEMS_CSV, index=False)
    stands.to_csv(STANDS_CSV, index=False)
    print(f"\nWrote {STEMS_CSV} ({len(stems):,} rows)")
    print(f"Wrote {STANDS_CSV} ({len(stands):,} rows)")

    if not args.no_viz:
        visualize(chm_b, transform, stems, stands, args.aoi, args.top, args.stand_size)
