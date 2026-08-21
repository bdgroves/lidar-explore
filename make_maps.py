r"""
Publication figures for the lidar-explore write-up.

Reads whatever outputs already exist and builds clean, self-contained figures.
Each figure is skipped with a note if its inputs are missing, so this can be run
at any stage rather than only at the end.

  fig1_overview.png     real CHM, stand polygons, detections, harvest candidates
  fig2_validation.png   detection vs Forest Centre inventory
  fig3_density.png      error vs point density (synthetic, known truth)
  fig4_change.png       multi-epoch canopy change

Usage:
  python make_maps.py
  python make_maps.py --aoi 364000 6685000 365000 6686000
  python make_maps.py --only 2
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

OUT = Path("data")
TILES = OUT / "metsakeskus"
SHEET = "L4132D"
GPKG = OUT / "MV_L4132D.gpkg"
ATTRIB = "Data: Suomen metsakeskus / Finnish Forest Centre, CC BY 4.0"

# Muted palette that survives greyscale printing
CANOPY = LinearSegmentedColormap.from_list(
    "canopy", ["#f7f5ee", "#dfe6cf", "#a8c08a", "#5d8a4e", "#2f5233"])

mpl.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor": "#fdfcf8",
    "axes.edgecolor": "#5a5a52",
    "axes.labelcolor": "#2e2e2a",
    "axes.titlesize": 11,
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "font.size": 9,
    "axes.grid": True,
    "grid.color": "#e2ded2",
    "grid.linewidth": 0.6,
})


def stamp(fig, note=None, attrib=True):
    """
    Attribution line, below the axes rather than on top of their labels.

    attrib=False for figures built purely from the synthetic sample — claiming
    Forest Centre provenance on data they never produced is a licensing
    misstatement, not a harmless footer.
    """
    if attrib:
        txt = ATTRIB if note is None else f"{ATTRIB}   |   {note}"
    else:
        txt = note or ""
    fig.subplots_adjust(bottom=0.16)
    fig.text(0.99, 0.012, txt, ha="right", va="bottom",
             fontsize=7, color="#7a7a70")


def km_axes(ax, bounds):
    """
    Label axes in km so six-digit TM35FIN coordinates stay readable.

    Decimals scale with extent: northings run to seven digits, so rounding to
    whole km over a 2 km window prints the same tick label three times.
    """
    span = max(bounds[2] - bounds[0], bounds[3] - bounds[1])
    dp = 0 if span > 20000 else (1 if span > 3000 else 2)
    ax.set_xlabel("Easting (km, TM35FIN)")
    ax.set_ylabel("Northing (km, TM35FIN)")
    ax.xaxis.set_major_formatter(lambda v, _: f"{v/1000:.{dp}f}")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v/1000:.{dp}f}")
    ax.tick_params(axis="x", rotation=0)


def read_chm(year, aoi=None):
    import rasterio
    from rasterio.windows import from_bounds
    p = TILES / f"CHM_{SHEET}_{year}.tif"
    if not p.exists():
        return None, None, None
    with rasterio.open(p) as src:
        if aoi:
            win = from_bounds(*aoi, src.transform)
            arr = src.read(1, window=win).astype("float32")
            b = aoi
        else:
            arr = src.read(1).astype("float32")
            bb = src.bounds
            b = (bb.left, bb.bottom, bb.right, bb.top)
        if src.nodata is not None:
            arr = np.where(arr == src.nodata, np.nan, arr)
    return arr, [b[0], b[2], b[1], b[3]], b


# ------------------------------------------------------------------- figure 1

def fig_overview(aoi):
    chm, extent, bounds = read_chm("2020", aoi)
    if chm is None:
        print("  skip fig1: no CHM 2020")
        return
    csv = OUT / "stand_validation.csv"
    if not csv.exists():
        print("  skip fig1: run stand_validate.py first")
        return
    try:
        import geopandas as gpd
    except ImportError:
        print("  skip fig1: geopandas missing")
        return

    d = pd.read_csv(csv, dtype={"developmentclass": "string"})
    gdf = gpd.read_file(GPKG, layer="stand")
    if gdf.crs is None:
        gdf = gdf.set_crs(3067)

    # The stand layer already carries developmentclass, so merging the CSV copy
    # would yield developmentclass_x / _y and drop the plain name. Bring over
    # only the columns the polygons do not already have.
    want = ["eligible", "op_cut", "det_stems_ha", "chm_mean_h"]
    bring = [c for c in want if c in d.columns and c not in gdf.columns]
    gdf = gdf.merge(d[["standid"] + bring], on="standid", how="inner")
    if "developmentclass" in gdf.columns:
        gdf["developmentclass"] = gdf["developmentclass"].astype("string")
    sub = gdf.cx[bounds[0]:bounds[2], bounds[1]:bounds[3]]

    fig, axes = plt.subplots(1, 3, figsize=(16, 5.6))

    ax = axes[0]
    im = ax.imshow(chm, cmap=CANOPY, extent=extent, origin="upper", vmin=0, vmax=30)
    ax.set_title("Canopy height model, 2020\n1 m resolution, Forest Centre")
    plt.colorbar(im, ax=ax, shrink=0.78, label="Height above ground (m)")

    ax = axes[1]
    ax.imshow(chm, cmap="Greys_r", extent=extent, origin="upper",
              vmin=0, vmax=30, alpha=0.35)
    if not sub.empty:
        sub.plot(ax=ax, facecolor="none", edgecolor="#3f6ea8", linewidth=0.5)
    ax.set_title(f"Private forest stands\n{len(sub):,} in view — everything else\n"
                 "is outside the whitelist")

    ax = axes[2]
    ax.imshow(chm, cmap="Greys_r", extent=extent, origin="upper",
              vmin=0, vmax=30, alpha=0.3)
    if not sub.empty:
        sub.plot(ax=ax, facecolor="none", edgecolor="#cfcabb", linewidth=0.4)
        m = sub[sub["developmentclass"] == "04"]
        if not m.empty:
            m.plot(ax=ax, facecolor="#c98a3c", alpha=0.45, edgecolor="none")
        e = sub[sub["eligible"] == True]  # noqa: E712
        if not e.empty:
            e.plot(ax=ax, facecolor="none", edgecolor="#8c2f2f", linewidth=1.4)
    ax.set_title("Regeneration-mature (orange)\nand eligible after all gates (red)")

    for ax in axes:
        km_axes(ax, bounds)
        ax.set_xlim(bounds[0], bounds[2])
        ax.set_ylim(bounds[1], bounds[3])

    fig.suptitle("Sheet L4132D — canopy, ownership, and harvest eligibility",
                 fontsize=13, y=1.02)
    plt.tight_layout(rect=(0, 0.05, 1, 1))
    stamp(fig)
    p = OUT / "fig1_overview.png"
    plt.savefig(p, dpi=140, bbox_inches="tight")
    plt.close()
    print(f"  wrote {p}")


# ------------------------------------------------------------------- figure 2

def fig_validation():
    csv = OUT / "stand_validation.csv"
    if not csv.exists():
        print("  skip fig2: run stand_validate.py first")
        return
    # developmentclass MUST stay text: read_csv turns "02" into 2 unless
    # a letter class (T2/A0/Y1) happens to be present to force object dtype.
    d = pd.read_csv(csv, dtype={"developmentclass": "string"})
    v = d[(d.det_stems >= 10) & d.meanheight.notna() & d.stemcount.notna()].copy()
    # Match REPORT.md exactly: same vintage / usability filter, or the figure
    # prints a different median than the text for the same measurement.
    if "usable_inv" in v.columns:
        v = v[v["usable_inv"].astype(str).str.lower().isin(["true", "1"])]
        filt = "vintage-filtered, matches REPORT.md"
    else:
        filt = "UNFILTERED - rerun stand_validate.py to match REPORT.md"
    if v.empty:
        print("  skip fig2: no comparable stands")
        return

    fig, axes = plt.subplots(1, 3, figsize=(16, 5.2))

    # (a) stem density
    ax = axes[0]
    sc = ax.scatter(v.stemcount, v.det_stems_ha, s=9, alpha=0.45,
                    c=v.chm_mean_h, cmap=CANOPY, vmin=5, vmax=26,
                    edgecolor="none")
    lim = float(np.nanpercentile(v.stemcount, 99))
    ax.plot([0, lim], [0, lim], "-", color="#2e2e2a", lw=1, label="1:1")
    for f, st in [(0.5, "--"), (0.25, ":")]:
        ax.plot([0, lim], [0, lim * f], st, color="#8c2f2f", lw=1,
                label=f"{f:.0%} recovered")
    ax.set_xlim(0, lim); ax.set_ylim(0, lim * 0.6)
    ax.set_xlabel("Inventory stems/ha (Forest Centre)")
    ax.set_ylabel("Detected stems/ha (CHM local maxima)")
    med = 100 * (v.det_stems_ha / v.stemcount.clip(lower=1)).median()
    ax.set_title(f"(a) Stem recovery\nmedian {med:.0f}% of inventory stems")
    ax.legend(loc="upper left")
    plt.colorbar(sc, ax=ax, shrink=0.75, label="CHM mean height (m)")

    # (b) height, both estimators
    ax = axes[1]
    ax.scatter(v.meanheight, v.chm_mean_h, s=8, alpha=0.4, color="#7a8fa6",
               label="all CHM pixels", edgecolor="none")
    if "det_mean_h" in v:
        ax.scatter(v.meanheight, v.det_mean_h, s=8, alpha=0.5, color="#2f5233",
                   label="detected stems only", edgecolor="none")
    hi = float(np.nanpercentile(v.meanheight, 99)) * 1.15
    ax.plot([0, hi], [0, hi], "-", color="#2e2e2a", lw=1, label="1:1")
    ax.set_xlim(0, hi); ax.set_ylim(0, hi)
    ax.set_xlabel("Inventory mean height (m)")
    ax.set_ylabel("CHM-derived height (m)")
    ax.set_title("(b) The estimator decides the sign\n"
                 "stems sit above, pixel-mean below")
    ax.legend(loc="upper left")

    # (c) recovery by development class
    ax = axes[2]
    v["rate"] = 100 * v.det_stems_ha / v.stemcount.clip(lower=1)
    order = ["02", "03", "04"]
    g = [v.loc[v.developmentclass == c, "rate"].dropna() for c in order]
    keep = [(c, x) for c, x in zip(order, g) if len(x) > 5]
    if keep:
        names = [c for c, _ in keep]
        try:
            bp = ax.boxplot([x for _, x in keep], tick_labels=names,
                            patch_artist=True, showfliers=False, widths=0.55)
        except TypeError:                       # matplotlib < 3.9
            bp = ax.boxplot([x for _, x in keep], labels=names,
                            patch_artist=True, showfliers=False, widths=0.55)
        for i, (c, x) in enumerate(keep, start=1):
            ax.text(i, x.median(), f"{x.median():.0f}%", ha="center",
                    va="bottom", fontsize=8, color="#2e2e2a")
        for patch, col in zip(bp["boxes"], ["#a8c08a", "#5d8a4e", "#2f5233"]):
            patch.set_facecolor(col); patch.set_alpha(0.75)
        for med_ in bp["medians"]:
            med_.set_color("#2e2e2a"); med_.set_linewidth(1.4)
    else:
        ax.text(0.5, 0.5, "no class groups with n > 5", ha="center",
                va="center", transform=ax.transAxes, color="#8c2f2f")
    ax.set_xlabel("Development class  (02 young → 04 mature)")
    ax.set_ylabel("Stems recovered (%)")
    ax.set_title("(c) Recovery rises with maturity\nlarger, better-separated crowns")

    fig.suptitle("CHM tree detection validated against the Finnish forest inventory",
                 fontsize=13, y=1.03)
    plt.tight_layout(rect=(0, 0.05, 1, 1))
    stamp(fig, f"n = {len(v):,} stands, {filt}")
    p = OUT / "fig2_validation.png"
    plt.savefig(p, dpi=140, bbox_inches="tight")
    plt.close()
    print(f"  wrote {p}")


# ------------------------------------------------------------------- figure 3

def fig_density():
    csv = OUT / "density_study.csv"
    if not csv.exists():
        print("  skip fig3: run density_study.py first")
        return
    d = pd.read_csv(csv)
    one = d[d.resolution_m == d.resolution_m.min()].sort_values("achieved_density")

    fig, axes = plt.subplots(1, 3, figsize=(15.5, 4.8))

    ax = axes[0]
    ax.plot(one.achieved_density, one.recall * 100, "o-", color="#5d8a4e",
            label="recall")
    ax.plot(one.achieved_density, one.precision * 100, "s--", color="#8c2f2f",
            label="precision")
    ax.axvline(0.5, color="#c98a3c", ls=":", lw=1.4)
    ax.text(0.53, 30, "Finland\nfree 0.5p", fontsize=7, color="#c98a3c")
    ax.set_xscale("log"); ax.set_ylim(0, 105)
    ax.set_xlabel("Point density (pts/m², log)")
    ax.set_ylabel("Percent")
    ax.set_title("(a) Recall barely moves\nand rises as data thins")
    ax.legend()

    ax = axes[1]
    ax.plot(one.achieved_density, one.height_rmse, "o-", color="#2f5233")
    ax.axvline(0.5, color="#c98a3c", ls=":", lw=1.4)
    ax.set_xscale("log")
    ax.set_xlabel("Point density (pts/m², log)")
    ax.set_ylabel("Height RMSE (m)")
    ax.set_title("(b) Height error degrades cleanly\nthe honest density metric")

    ax = axes[2]
    for res, grp in d.groupby("resolution_m"):
        g = grp.sort_values("achieved_density")
        ax.plot(g.achieved_density, g.recall * 100, "o-",
                label=f"{res:.0f} m CHM")
    ax.set_xscale("log"); ax.set_ylim(0, 105)
    ax.set_xlabel("Point density (pts/m², log)")
    ax.set_ylabel("Recall (%)")
    ax.set_title("(c) Resolution beats density\n2 m cells lose everywhere")
    ax.legend()

    fig.suptitle("Detection error vs point density — synthetic forest, known ground truth",
                 fontsize=13, y=1.04)
    plt.tight_layout(rect=(0, 0.05, 1, 1))
    stamp(fig, "Synthetic sample, 450 known trees. No third-party data.",
          attrib=False)
    p = OUT / "fig3_density.png"
    plt.savefig(p, dpi=140, bbox_inches="tight")
    plt.close()
    print(f"  wrote {p}")


# ------------------------------------------------------------------- figure 4

def fig_change(aoi):
    a, extent, bounds = read_chm("2008", aoi)
    b, _, _ = read_chm("2020", aoi)
    if a is None or b is None or a.shape != b.shape:
        print("  skip fig4: need CHM 2008 and 2020 on the same grid")
        return
    diff = b - a

    fig, axes = plt.subplots(1, 3, figsize=(16, 5.4))

    for ax, arr, yr in [(axes[0], a, "2008"), (axes[1], b, "2020")]:
        im = ax.imshow(arr, cmap=CANOPY, extent=extent, origin="upper",
                       vmin=0, vmax=30)
        ax.set_title(f"Canopy height {yr}\nmean {np.nanmean(arr):.1f} m")
        plt.colorbar(im, ax=ax, shrink=0.78, label="Height (m)")

    ax = axes[2]
    im = ax.imshow(diff, cmap="RdBu_r", extent=extent, origin="upper",
                   vmin=-15, vmax=15)
    ax.set_title("Change 2008 → 2020\nred = loss, blue = gain")
    plt.colorbar(im, ax=ax, shrink=0.78, label="Height change (m)")

    for ax in axes:
        km_axes(ax, bounds)

    fig.suptitle("Twelve years of canopy change — and why the magnitude is not trustworthy",
                 fontsize=13, y=1.02)
    plt.tight_layout(rect=(0, 0.05, 1, 1))
    stamp(fig, "2008 epoch carries a canopy-specific bias; see REPORT.md")
    p = OUT / "fig4_change.png"
    plt.savefig(p, dpi=140, bbox_inches="tight")
    plt.close()
    print(f"  wrote {p}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aoi", nargs=4, type=float,
                    metavar=("MINX", "MINY", "MAXX", "MAXY"),
                    default=[364000, 6685000, 366000, 6687000],
                    help="map extent for figures 1 and 4 (default: 2x2 km)")
    ap.add_argument("--only", type=int, choices=[1, 2, 3, 4],
                    help="build a single figure")
    args = ap.parse_args()

    jobs = {1: lambda: fig_overview(args.aoi),
            2: fig_validation,
            3: fig_density,
            4: lambda: fig_change(args.aoi)}
    print("Building figures...")
    for k in ([args.only] if args.only else [1, 2, 3, 4]):
        jobs[k]()
    print("Done.")
