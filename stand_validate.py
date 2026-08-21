r"""
Validate CHM-derived tree detection against the Finnish Forest Centre's
stand inventory, and benchmark harvest targeting against the professional
management plan.

This is the first point in the project where detection can be checked against
something other than our own synthetic ground truth. The Forest Centre's
Metsavarakuviot dataset gives, per forest stand:

  * stemcount, meanheight, basalarea, volume   -- inventory attributes
  * developmentclass                            -- silvicultural stage
  * proposed operations for 2026-2035           -- a real management plan
  * restrictions                                -- legal / conservation limits

Three things happen here:

  1. WHITELIST. Only stands present in this file are eligible for harvest.
     Metsavarakuviot covers PRIVATE forest. State land -- including Nuuksio
     National Park -- is administered by Metsahallitus and simply is not in
     the file. So absence means "not private managed forest", which could be
     protected, state-owned, water, or built-up. Treating absence as a block
     fails safe; a blacklist would fail open on any coverage gap.

  2. VALIDATION. Detected stems/ha and CHM heights are compared against the
     inventory for the same polygons. This finally quantifies the overstory
     undercount that the density study predicted.

  3. BENCHMARK. Our harvest ranking is scored against the stands foresters
     actually proposed for cutting. Agreement is the real test; a ranked list
     nobody checks is just an opinion.

DEVELOPMENT CLASSES (kehitysluokka), used as the maturity gate:
    A0  aukea                    open / recently clearcut
    T1  pieni taimikko           seedlings, mean height <= 1.3m
    T2  varttunut taimikko       advanced seedlings, > 1.3m
    Y1  ylispuustoinen taimikko  seedlings under retained overstory
    S0  siemenpuumetsikko        seed-tree stand
    02  nuori kasvatusmetsikko   young thinning stand
    03  varttunut kasvatusmetsikko   advanced thinning stand
    04  uudistuskypsa metsikko   REGENERATION-MATURE -> harvest candidates
    05  suojuspuumetsikko        shelterwood

Class 04 replaces the Chapman-Richards age model used earlier: it is a
forester's own judgement that the stand has reached rotation age, which is
strictly better than inverting a growth curve with an assumed site index.

DATA QUALITY, per the Forest Centre specification: stand attributes are
interpreted from laser data for T2, 02, 03 and 04. Attributes estimated for
A0 and T1 are explicitly documented as not usable, so those are dropped
rather than silently compared.

Data: Suomen metsakeskus / Finnish Forest Centre, CC BY 4.0.
      Canopy height model likewise.

Usage:
  python stand_validate.py
  python stand_validate.py --year 2015          # match the 2015 inventory date
  python stand_validate.py --aoi 364000 6685000 366000 6687000
  python stand_validate.py --top 20 --no-viz
"""
import argparse
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.windows import from_bounds
from scipy.ndimage import maximum_filter, gaussian_filter
import matplotlib.pyplot as plt

GPKG = "data/MV_L4132D.gpkg"
TILE_DIR = Path("data/metsakeskus")
SHEET = "L4132D"

OUT_STANDS = "data/stand_validation.csv"
OUT_FIG = "data/stand_validation.png"

# Detection parameters (metres). MIN_TREE_H sits between the Forest Centre's
# own laser thresholds: 2m separates T1/T2, 7m separates T2 from class 02.
MIN_TREE_H = 5.0
SMOOTH_M = 0.5
WIN_MIN_M, WIN_MAX_M = 3.0, 11.0
WIN_SLOPE = 0.22

MAX_OBS_GAP_YEARS = 6       # reject inventory measured too long before the CHM
MIN_STAND_HA = 0.3          # below this, per-stand stats are too noisy
MIN_STEMS = 10
MATURE_CLASS = "04"         # uudistuskypsa -- regeneration-mature

# Development classes whose inventory attributes the producer flags as unusable
UNUSABLE_CLASSES = {"A0", "T1"}

CLASS_NAMES = {
    "A0": "open/clearcut", "T1": "seedling <1.3m", "T2": "seedling >1.3m",
    "Y1": "seedling w/ overstory", "S0": "seed-tree", "02": "young thinning",
    "03": "advanced thinning", "04": "regeneration-mature", "05": "shelterwood",
}
SPECIES = {1: "pine", 2: "spruce", 3: "b.birch", 4: "d.birch", 5: "aspen"}


# ----------------------------------------------------------------- stand load

def load_stands():
    """Stand polygons joined to OBSERVED inventory, with restrictions flagged."""
    try:
        import geopandas as gpd
    except ImportError:
        raise SystemExit("This needs geopandas:  pixi add geopandas")

    if not Path(GPKG).exists():
        raise SystemExit(f"Missing {GPKG}")

    gdf = gpd.read_file(GPKG, layer="stand")
    if gdf.crs is None:
        gdf = gdf.set_crs(3067)
    elif gdf.crs.to_epsg() != 3067:
        gdf = gdf.to_crs(3067)

    con = sqlite3.connect(GPKG)

    # OBSERVED inventory lives in treestratum, not treestandsummary.
    # treestandsummary exists ONLY for projected states (type 2 = 2026,
    # type 3 = 2036); type 1 (measured) has per-species strata instead.
    # Joining a summary would therefore mean comparing a 2020 raster to a
    # simulation of 2026 -- plausible-looking and wrong.
    #
    # stemcount is null in the strata, so density is derived from basal area
    # and mean diameter:   N = G / (pi/4 * d^2)
    # This is approximate: Finnish "keskilapimitta" is basal-area weighted,
    # so N is a stand-level estimate rather than a stem tally.
    strata = pd.read_sql_query("""
        SELECT ts.standid, ts.date AS obs_date,
               st.treespecies, st.storey, st.age,
               st.basalarea, st.meandiameter, st.meanheight, st.volume
        FROM treestand ts
        JOIN treestratum st ON st.treestandid = ts.treestandid
        WHERE ts.type = 1
          AND st.basalarea IS NOT NULL AND st.basalarea > 0
          AND st.meandiameter IS NOT NULL AND st.meandiameter > 0
    """, con)

    d_m = strata["meandiameter"] / 100.0                 # cm -> m
    strata["stems_ha"] = strata["basalarea"] / (np.pi / 4.0 * d_m ** 2)
    strata["ba_h"] = strata["basalarea"] * strata["meanheight"]
    strata["ba_age"] = strata["basalarea"] * strata["age"]

    g = strata.groupby("standid")
    inv = g.agg(
        obs_date=("obs_date", "first"),
        n_strata=("treespecies", "size"),
        basalarea=("basalarea", "sum"),
        stemcount=("stems_ha", "sum"),
        volume=("volume", "sum"),
        _bah=("ba_h", "sum"),
        _baa=("ba_age", "sum"),
    ).reset_index()
    inv["meanheight"] = inv["_bah"] / inv["basalarea"].clip(lower=1e-6)
    inv["meanage"] = inv["_baa"] / inv["basalarea"].clip(lower=1e-6)
    inv = inv.drop(columns=["_bah", "_baa"])

    # Dominant stratum: largest basal area. Its height is closer to what a
    # CHM actually sees than a mean that includes suppressed understory.
    dom = (strata.sort_values("basalarea", ascending=False)
                 .groupby("standid", as_index=False).first()
                 [["standid", "meanheight", "treespecies", "meandiameter"]]
                 .rename(columns={"meanheight": "dom_stratum_h",
                                  "treespecies": "dom_species",
                                  "meandiameter": "dom_diam"}))
    inv = inv.merge(dom, on="standid", how="left")
    inv["obs_year"] = pd.to_datetime(inv["obs_date"], errors="coerce").dt.year

    restricted = pd.read_sql_query(
        "SELECT DISTINCT standid, 1 AS restricted FROM restriction", con)

    # maintype 1 = hakkuu (cutting). Sub-types vary; any cutting proposal is
    # enough to call the stand "professionally proposed for harvest".
    ops = pd.read_sql_query("""
        SELECT standid,
               MAX(CASE WHEN maintype = 1 THEN 1 ELSE 0 END) AS op_cut,
               MIN(CASE WHEN maintype = 1 THEN proposalyear END) AS cut_year,
               COUNT(*) AS n_ops
        FROM operation GROUP BY standid
    """, con)
    con.close()

    gdf = (gdf.merge(inv, on="standid", how="left")
              .merge(restricted, on="standid", how="left")
              .merge(ops, on="standid", how="left"))
    gdf["restricted"] = gdf["restricted"].fillna(0).astype(int)
    gdf["op_cut"] = gdf["op_cut"].fillna(0).astype(int)
    gdf["n_ops"] = gdf["n_ops"].fillna(0).astype(int)
    return gdf


# ------------------------------------------------------------------ detection

def read_chm(year, aoi=None):
    p = TILE_DIR / f"CHM_{SHEET}_{year}.tif"
    if not p.exists():
        raise SystemExit(f"Missing {p}\n"
                         f"  python fetch_metsakeskus.py --sheet {SHEET} --year {year}")
    with rasterio.open(p) as src:
        if aoi:
            win = from_bounds(*aoi, src.transform)
            arr = src.read(1, window=win).astype("float32")
            tr = src.window_transform(win)
            bounds = aoi
        else:
            arr = src.read(1).astype("float32")
            tr = src.transform
            b = src.bounds
            bounds = (b.left, b.bottom, b.right, b.top)
        if src.nodata is not None:
            arr = np.where(arr == src.nodata, np.nan, arr)
    return arr, tr, bounds


def detect_stems(chm, transform):
    """Variable-window local maxima; window scales with canopy height."""
    res = abs(transform.a)
    filled = np.nan_to_num(chm, nan=0.0)
    smooth = gaussian_filter(filled, sigma=max(SMOOTH_M / res, 0.01))

    peaks = np.zeros(smooth.shape, dtype=bool)
    for lo, hi in [(5, 10), (10, 16), (16, 22), (22, 28), (28, 100)]:
        h_mid = (lo + min(hi, 40)) / 2.0
        win_m = float(np.clip(WIN_MIN_M + WIN_SLOPE * h_mid, WIN_MIN_M, WIN_MAX_M))
        win_px = max(int(round(win_m / res)), 3)
        if win_px % 2 == 0:
            win_px += 1
        local = maximum_filter(smooth, size=win_px)
        peaks |= (smooth >= lo) & (smooth < hi) & (smooth == local)

    peaks &= smooth >= MIN_TREE_H
    rows, cols = np.where(peaks)
    return rows, cols, chm[rows, cols].astype(float)


# ------------------------------------------------------------- stand analysis

def analyse(gdf, chm, transform, bounds, chm_year):
    """Rasterise stands, then aggregate detections and CHM stats per stand."""
    minx, miny, maxx, maxy = bounds
    sub = gdf.cx[minx:maxx, miny:maxy].reset_index(drop=True)
    if sub.empty:
        raise SystemExit("No stands intersect this AOI.")

    # Label raster: 0 = outside any stand (NOT private managed forest),
    # i>0 = index into sub, offset by one.
    shapes = ((geom, i + 1) for i, geom in enumerate(sub.geometry))
    labels = rasterize(shapes, out_shape=chm.shape, transform=transform,
                       fill=0, dtype="int32")

    rows, cols, heights = detect_stems(chm, transform)
    stem_lab = labels[rows, cols]

    n = len(sub)
    counts = np.bincount(stem_lab, minlength=n + 1)[1:]
    hsum = np.bincount(stem_lab, weights=heights, minlength=n + 1)[1:]

    # CHM pixel statistics per stand
    valid = np.isfinite(chm)
    flat_lab = np.where(valid, labels, 0).ravel()
    flat_chm = np.nan_to_num(chm, nan=0.0).ravel()
    px = np.bincount(flat_lab, minlength=n + 1)[1:]
    px_sum = np.bincount(flat_lab, weights=flat_chm, minlength=n + 1)[1:]
    px_tree = np.bincount(flat_lab, weights=(flat_chm > MIN_TREE_H).astype(float),
                          minlength=n + 1)[1:]

    res_area = abs(transform.a * transform.e)
    sub["poly_ha"] = sub.geometry.area / 10_000.0
    sub["px_ha"] = px * res_area / 10_000.0
    sub["det_stems"] = counts
    sub["det_stems_ha"] = counts / sub["poly_ha"].clip(lower=0.01)
    sub["det_mean_h"] = np.where(counts > 0, hsum / np.maximum(counts, 1), np.nan)
    sub["chm_mean_h"] = np.where(px > 0, px_sum / np.maximum(px, 1), np.nan)
    sub["canopy_frac"] = np.where(px > 0, px_tree / np.maximum(px, 1), np.nan)

    # Eligibility, in the order a forester would apply it
    sub["obs_gap"] = (chm_year - sub["obs_year"]).abs()
    sub["fresh_inv"] = sub["obs_gap"] <= MAX_OBS_GAP_YEARS
    sub["usable_inv"] = (~sub["developmentclass"].isin(UNUSABLE_CLASSES)
                         & sub["fresh_inv"])
    sub["big_enough"] = sub["poly_ha"] >= MIN_STAND_HA
    sub["has_stems"] = sub["det_stems"] >= MIN_STEMS
    sub["mature"] = sub["developmentclass"] == MATURE_CLASS
    sub["eligible"] = (sub["mature"] & (sub["restricted"] == 0)
                       & sub["usable_inv"] & sub["big_enough"] & sub["has_stems"])
    return sub, labels, (rows, cols, heights, stem_lab)


def rank(sub):
    """Rank eligible stands. Uses inventory volume where present, height otherwise."""
    e = sub[sub["eligible"]].copy()
    if e.empty:
        return e
    med = e["volume"].median()
    vol = e["volume"].astype(float).fillna(med if pd.notna(med) else 0.0)
    e["vol_pct"] = vol.rank(pct=True)
    e["h_pct"] = e["chm_mean_h"].rank(pct=True)
    e["priority"] = 0.6 * e["vol_pct"] + 0.4 * e["h_pct"]
    return e.sort_values("priority", ascending=False)


# --------------------------------------------------------------------- report

def report(sub, ranked, year, top_n):
    line = "=" * 74
    print(line)
    print(f"STAND VALIDATION vs Finnish Forest Centre inventory   (CHM {year})")
    print(line)

    print(f"\nStands intersecting AOI: {len(sub):,}   "
          f"{sub['poly_ha'].sum():,.0f} ha of private forest")

    print("\nDevelopment class distribution:")
    for cls, grp in sub.groupby("developmentclass", dropna=False):
        name = CLASS_NAMES.get(cls, "unclassified" if cls is None else "?")
        flag = "  [attrs unusable]" if cls in UNUSABLE_CLASSES else ""
        print(f"  {str(cls):>5} {name:<24} {len(grp):>5} stands "
              f"{grp['poly_ha'].sum():>8.1f} ha{flag}")

    print("\nInventory vintage (observed strata vs CHM epoch):")
    ov = sub["obs_year"].dropna()
    if len(ov):
        print(f"  observation years   {int(ov.min())} - {int(ov.max())}")
        print(f"  stands with inventory   {len(ov):>5} of {len(sub)}")
        print(f"  within {MAX_OBS_GAP_YEARS} yr of CHM      "
              f"{int(sub['fresh_inv'].sum()):>5}   <- usable for validation")
        stale = int((~sub['fresh_inv'] & sub['obs_year'].notna()).sum())
        print(f"  too stale, excluded     {stale:>5}")
        if stale:
            print("  (comparing a 2020 raster to a 1999 measurement would read as")
            print("   detection error when it is really 21 years of forest growth)")

    print("\nEligibility funnel:")
    print(f"  all stands                          {len(sub):>5}")
    print(f"  regeneration-mature (class 04)      {int(sub['mature'].sum()):>5}")
    m = sub['mature']
    print(f"    minus restricted                  {int((m & (sub['restricted']==0)).sum()):>5}")
    print(f"    minus tiny (<{MIN_STAND_HA} ha)             "
          f"{int((m & (sub['restricted']==0) & sub['big_enough']).sum()):>5}")
    print(f"    minus too few stems detected      {int(sub['eligible'].sum()):>5}  ELIGIBLE")

    # ---- validation ----
    v = sub[sub["usable_inv"] & sub["big_enough"]
            & sub["stemcount"].notna() & (sub["det_stems"] >= MIN_STEMS)].copy()
    print(f"\n{line}\nDETECTION vs INVENTORY   ({len(v)} stands with usable attributes)")
    print(line)
    if v.empty:
        print("  no comparable stands")
    else:
        v["stem_ratio"] = v["det_stems_ha"] / v["stemcount"].clip(lower=1)
        v["h_diff"] = v["chm_mean_h"] - v["meanheight"]
        print(f"\nStem density (stems/ha):")
        print(f"  inventory   mean {v['stemcount'].mean():7.0f}   "
              f"median {v['stemcount'].median():7.0f}")
        print(f"  detected    mean {v['det_stems_ha'].mean():7.0f}   "
              f"median {v['det_stems_ha'].median():7.0f}")
        print(f"  detection rate  {100*v['stem_ratio'].median():.1f}% of inventory stems (median)")
        print("  -> local maxima on a 1m CHM see dominant and codominant crowns only;")
        print("     suppressed understory stems are invisible. This is the expected")
        print("     direction and magnitude, not a failure.")

        print(f"\nMean canopy height (m):")
        print(f"  inventory   mean {v['meanheight'].mean():6.2f}")
        print(f"  CHM         mean {v['chm_mean_h'].mean():6.2f}")
        print(f"  difference  mean {v['h_diff'].mean():+6.2f}   "
              f"median {v['h_diff'].median():+6.2f}   sd {v['h_diff'].std():5.2f}")
        r = v[["chm_mean_h", "meanheight"]].corr().iloc[0, 1]
        print(f"  correlation r = {r:.3f}")

        # Two estimators from the same raster, on opposite sides of the truth.
        if "det_mean_h" in v and v["det_mean_h"].notna().any():
            dv = v[v["det_mean_h"].notna()]
            rd = dv[["det_mean_h", "meanheight"]].corr().iloc[0, 1]
            print(f"\n  Estimator comparison (n = {len(dv)}):")
            print(f"    detected stems only  {dv['det_mean_h'].mean():6.2f}m  "
                  f"({(dv['det_mean_h']-dv['meanheight']).mean():+.2f})  r = {rd:.3f}")
            print(f"    inventory mean       {dv['meanheight'].mean():6.2f}m")
            print(f"    all CHM pixels       {dv['chm_mean_h'].mean():6.2f}m  "
                  f"({(dv['chm_mean_h']-dv['meanheight']).mean():+.2f})  r = {r:.3f}")
            print("    -> crown apexes sit above a stem-weighted mean; whole-pixel")
            print("       mean sits below because it averages canopy gaps.")
        if abs(v["h_diff"].median()) > 2:
            print("  NOTE: CHM mean height includes gaps and understory pixels, while")
            print("        inventory meanheight is a stand-level stem-weighted mean.")
            print("        A systematic offset here is expected, not an error.")

        print("\nBy development class:")
        print(f"  {'class':>5} {'n':>5} {'inv_stems':>10} {'det_stems':>10} "
              f"{'rate':>6} {'inv_h':>7} {'chm_h':>7}")
        print("  " + "-" * 56)
        MIN_CLASS_N = 5     # a one-stand "class" is noise printed as a statistic
        for cls, g in v.groupby("developmentclass"):
            if len(g) < MIN_CLASS_N:
                continue
            print(f"  {str(cls):>5} {len(g):>5} {g['stemcount'].mean():>10.0f} "
                  f"{g['det_stems_ha'].mean():>10.0f} "
                  f"{100*g['stem_ratio'].median():>5.0f}% "
                  f"{g['meanheight'].mean():>7.2f} {g['chm_mean_h'].mean():>7.2f}")

    # ---- benchmark ----
    print(f"\n{line}\nBENCHMARK vs PROFESSIONAL MANAGEMENT PLAN\n{line}")
    # The honest denominator is the pool we actually chose FROM, not all
    # stands. Scoring against every stand inflates lift by crediting the
    # ranking for exclusions the development class already made.
    pool = sub[sub["eligible"]].copy()
    allc = sub[sub["big_enough"]].copy()
    print(f"\nCutting proposed (2026-2035):")
    print(f"  across all stands >= {MIN_STAND_HA} ha   "
          f"{int(allc['op_cut'].sum())} of {len(allc)}  ({100*allc['op_cut'].mean():.0f}%)")
    if len(pool):
        print(f"  within the ELIGIBLE pool          "
              f"{int(pool['op_cut'].sum())} of {len(pool)}  ({100*pool['op_cut'].mean():.0f}%)")

    if not ranked.empty and len(pool):
        k = min(top_n, len(ranked))
        picked = set(ranked.head(k)["standid"])
        hit = pool["standid"].isin(picked)
        tp = int((hit & (pool["op_cut"] == 1)).sum())
        fp = int((hit & (pool["op_cut"] == 0)).sum())
        base = pool["op_cut"].mean()          # base rate WITHIN the pool
        prec = tp / max(tp + fp, 1)
        lift = prec / base if base > 0 else float("nan")
        print(f"\nOur top {k} vs foresters' proposals (scored within eligible pool):")
        print(f"  also proposed for cutting   {tp:>4}")
        print(f"  not proposed                {fp:>4}")
        print(f"  precision                   {100*prec:.0f}%")
        print(f"  base rate within pool       {100*base:.0f}%")
        print(f"  lift over random-in-pool    {lift:.2f}x")
        if base > 0.85:
            print("  CAUTION: the eligible pool is already almost all proposed for")
            print("  cutting, so precision near 100% is close to unavoidable and lift")
            print("  cannot exceed ~%.2fx. The development class is doing the work;" % (1/base))
            print("  this benchmark cannot show the CHM adding much on top of it.")
        elif lift > 1.3:
            print("  -> ranking finds stands foresters independently flagged.")
        elif lift < 0.9:
            print("  -> ANTI-correlated with the plan. Investigate before trusting it.")
        else:
            print("  -> close to chance within the pool.")

        # What did class 04 alone achieve, without our scoring?
        m04 = allc[allc["developmentclass"] == MATURE_CLASS]
        if len(m04):
            print(f"\n  For comparison, development class 04 alone:")
            print(f"    {len(m04)} stands, {100*m04['op_cut'].mean():.0f}% proposed for cutting")
            print("    (this is the forester's own maturity call, so high agreement")
            print("     here mostly confirms the class is doing the work, not the CHM)")

    if not ranked.empty:
        print(f"\nTop {min(top_n, len(ranked))} harvest candidates:")
        print(f"  {'standid':>10} {'ha':>6} {'cls':>4} {'sp':>8} {'age':>4} "
              f"{'inv_h':>6} {'vol':>7} {'st/ha':>6} {'cut?':>5}")
        print("  " + "-" * 66)
        for _, r in ranked.head(top_n).iterrows():
            sp = SPECIES.get(r["maintreespecies"], "-")
            cut = "YES" if r["op_cut"] == 1 else "-"
            print(f"  {r['standid']:>10.0f} {r['poly_ha']:>6.2f} "
                  f"{str(r['developmentclass']):>4} {sp:>8} "
                  f"{(r['meanage'] if pd.notna(r['meanage']) else 0):>4.0f} "
                  f"{(r['meanheight'] if pd.notna(r['meanheight']) else 0):>6.1f} "
                  f"{(r['volume'] if pd.notna(r['volume']) else 0):>7.0f} "
                  f"{r['det_stems_ha']:>6.0f} {cut:>5}")
    print(line)


def visualize(sub, ranked, chm, bounds, top_n):
    import geopandas as gpd
    extent = [bounds[0], bounds[2], bounds[1], bounds[3]]
    fig, axes = plt.subplots(2, 2, figsize=(15, 13))

    ax = axes[0][0]
    ax.imshow(chm, cmap="Greys_r", extent=extent, origin="upper", vmin=0, vmax=30)
    sub.plot(ax=ax, facecolor="none", edgecolor="tab:blue", linewidth=0.4)
    ax.set_title(f"Private forest stands on CHM\n({len(sub):,} stands, "
                 f"{sub['poly_ha'].sum():,.0f} ha)")

    ax = axes[0][1]
    v = sub[sub["usable_inv"] & sub["stemcount"].notna() & (sub["det_stems"] >= MIN_STEMS)]
    if not v.empty:
        ax.scatter(v["stemcount"], v["det_stems_ha"], s=12, alpha=0.5,
                   c=v["chm_mean_h"], cmap="YlGn", vmin=5, vmax=25)
        lim = max(v["stemcount"].max(), v["det_stems_ha"].max()) * 1.05
        ax.plot([0, lim], [0, lim], "k--", lw=1, label="1:1")
        for frac, st in [(0.25, ":"), (0.5, "-.")]:
            ax.plot([0, lim], [0, lim * frac], st, lw=1, color="crimson",
                    label=f"{frac:.0%} detected")
        ax.set_xlabel("Inventory stems/ha")
        ax.set_ylabel("Detected stems/ha")
        ax.set_title("Detection vs inventory stem density")
        ax.legend(fontsize=8)

    ax = axes[1][0]
    if not v.empty:
        ax.scatter(v["meanheight"], v["chm_mean_h"], s=12, alpha=0.5, color="tab:green")
        lim = max(v["meanheight"].max(), v["chm_mean_h"].max()) * 1.05
        ax.plot([0, lim], [0, lim], "k--", lw=1, label="1:1")
        ax.set_xlabel("Inventory mean height (m)")
        ax.set_ylabel("CHM mean height (m)")
        ax.set_title("Height agreement")
        ax.legend(fontsize=8)

    ax = axes[1][1]
    ax.imshow(chm, cmap="Greys_r", extent=extent, origin="upper", vmin=0, vmax=30, alpha=0.5)
    sub.plot(ax=ax, facecolor="none", edgecolor="lightgrey", linewidth=0.3)
    prop = sub[sub["op_cut"] == 1]
    if not prop.empty:
        prop.plot(ax=ax, facecolor="tab:orange", alpha=0.35, edgecolor="none",
                  label="proposed for cutting")
    if not ranked.empty:
        ranked.head(top_n).plot(ax=ax, facecolor="none", edgecolor="crimson",
                                linewidth=1.8)
    ax.set_title(f"Our top {top_n} (red) vs proposed cuttings (orange)")

    for ax in [axes[0][0], axes[1][1]]:
        ax.set_xlabel("Easting (m, TM35FIN)")
        ax.set_ylabel("Northing (m, TM35FIN)")

    plt.suptitle("CHM detection validated against Finnish Forest Centre inventory\n"
                 "Data: Suomen metsakeskus / Finnish Forest Centre, CC BY 4.0",
                 fontsize=12, y=1.00)
    plt.tight_layout()
    plt.savefig(OUT_FIG, dpi=110, bbox_inches="tight")
    print(f"\nSaved {OUT_FIG}")
    plt.show()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", default="2020", help="CHM epoch (default 2020)")
    ap.add_argument("--aoi", nargs=4, type=float,
                    metavar=("MINX", "MINY", "MAXX", "MAXY"),
                    help="restrict to this box (default: whole sheet)")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--no-viz", action="store_true")
    args = ap.parse_args()

    print("Loading stands and inventory...")
    gdf = load_stands()
    print(f"  {len(gdf):,} stands, "
          f"{int(gdf['stemcount'].notna().sum()):,} with observed inventory, "
          f"{int(gdf['restricted'].sum())} restricted")

    print(f"Reading CHM {args.year}...")
    chm, transform, bounds = read_chm(args.year, args.aoi)
    print(f"  {chm.shape[1]} x {chm.shape[0]} px @ {abs(transform.a)}m")

    print("Detecting stems and aggregating to stands...")
    sub, labels, stems = analyse(gdf, chm, transform, bounds, int(args.year))
    ranked = rank(sub)

    report(sub, ranked, args.year, args.top)

    # obs_year/obs_gap/fresh_inv/usable_inv are exported so figures and the
    # report describe the SAME subset. Without them make_maps.py silently used
    # an unfiltered set and printed a different median than REPORT.md.
    cols = ["standid", "poly_ha", "developmentclass", "maintreespecies",
            "meanage", "meanheight", "stemcount", "basalarea", "volume",
            "det_stems", "det_stems_ha", "det_mean_h", "chm_mean_h",
            "canopy_frac", "restricted", "op_cut", "cut_year",
            "obs_year", "obs_gap", "fresh_inv", "usable_inv", "eligible"]
    cols = [c for c in cols if c in sub.columns]
    sub[cols].to_csv(OUT_STANDS, index=False)
    print(f"\nWrote {OUT_STANDS} ({len(sub):,} rows)")

    if not args.no_viz:
        visualize(sub, ranked, chm, bounds, args.top)
