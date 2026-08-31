"""
scripts/machine_planning.py

Where should the harvester and forwarder actually drive?

stand_validate.py already showed the canopy model adds nothing to WHICH stand
to cut -- once you filter to development class 04, essentially every eligible
stand is already in the management plan (lift 1.00x). The forester's maturity
call decides that.

Terrain answers a different question the plan does not: given a stand IS going
to be cut, how likely is the ground to be damaged by machines? In Nordic
practice the dominant environmental problem is rutting -- heavy forwarders
churning saturated soil, which shears roots and delivers sediment to
watercourses. The standard mitigation is scheduling: wet sites are cut in
winter on frozen ground, dry sites can take summer traffic.

This derives two terrain measures from the National Land Survey 1 m DTM and
ranks the already-scheduled stands by ground sensitivity:

  slope   -- steep ground limits machine access and raises erosion risk
  TWI     -- topographic wetness index, ln(a / tan b), where a is upslope
             contributing area per unit contour width. High TWI = water
             collects here.

Thresholds are deliberately RELATIVE (percentiles of this sheet), not
absolute. Absolute rutting thresholds depend on soil texture, machine weight,
tyre/track configuration and season, none of which are in this data. The
output ranks stands against each other; it is not a bearing-capacity model.

    pixi run python scripts/machine_planning.py
"""
from pathlib import Path

import click
import geopandas as gpd
import numpy as np
import rasterio
import richdem as rd
from rasterio.enums import Resampling
from rasterio.features import geometry_mask

ROOT = Path(__file__).parent
DTM = ROOT / "data" / "metsakeskus" / "DTM_L4132D.tif"
STANDS = ROOT / "data" / "stands_joined.gpkg"


def load_dtm(path, factor):
    """Read the DTM, optionally downsampled, as a masked float array."""
    with rasterio.open(path) as src:
        h, w = src.height // factor, src.width // factor
        arr = src.read(1, out_shape=(h, w), resampling=Resampling.average)
        transform = src.transform * src.transform.scale(factor, factor)
        nodata = src.nodata
        crs = src.crs
    arr = arr.astype(np.float32)
    arr[arr == nodata] = np.nan
    return arr, transform, crs, abs(transform.a)


@click.command()
@click.option("--factor", default=2, show_default=True,
              help="Downsample factor on the 1 m DTM (2 -> 2 m working grid)")
@click.option("--out-prefix", default="data/machine_planning", show_default=True)
def main(factor, out_prefix):
    """Rank scheduled stands by terrain-driven ground-damage sensitivity."""
    click.echo(f"reading {DTM.name}")
    dem, transform, crs, cell = load_dtm(DTM, factor)
    click.echo(f"  grid {dem.shape} at {cell:g} m")

    # --- slope -----------------------------------------------------------
    filled = np.where(np.isnan(dem), np.nanmin(dem), dem)
    rda = rd.rdarray(filled.astype(np.float64), no_data=-9999)
    rda.geotransform = (transform.c, cell, 0, transform.f, 0, -cell)
    slope = np.array(rd.TerrainAttribute(rda, attrib="slope_degrees"))

    # --- wetness ---------------------------------------------------------
    click.echo("  filling depressions + flow accumulation")
    rd.FillDepressions(rda, epsilon=True, in_place=True)
    acc = np.array(rd.FlowAccumulation(rda, method="Dinf"))

    # TWI = ln(a / tan b); a = accumulated cells * cell area / cell width
    a = np.maximum(acc, 1.0) * cell
    tanb = np.tan(np.radians(np.maximum(slope, 0.10)))   # floor avoids /0 on flats
    twi = np.log(a / tanb)
    click.echo(f"  slope p50/p95: {np.nanpercentile(slope,50):.1f} / "
               f"{np.nanpercentile(slope,95):.1f} deg")
    click.echo(f"  TWI   p50/p95: {np.nanpercentile(twi,50):.1f} / "
               f"{np.nanpercentile(twi,95):.1f}")

    # relative thresholds for this sheet
    wet_cut = np.nanpercentile(twi, 85)
    steep_cut = np.nanpercentile(slope, 95)
    click.echo(f"  wet threshold  TWI > {wet_cut:.2f} (85th pct)")
    click.echo(f"  steep threshold slope > {steep_cut:.2f} deg (95th pct)")

    # --- per-stand zonal stats ------------------------------------------
    stands = gpd.read_file(STANDS, layer="stands").to_crs(crs)
    click.echo(f"  {len(stands)} stands")

    rows = []
    for idx, row in stands.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        try:
            m = geometry_mask([geom], out_shape=dem.shape, transform=transform,
                              invert=True, all_touched=False)
        except Exception:
            continue
        if m.sum() < 5:
            continue
        s, t = slope[m], twi[m]
        rows.append({
            "standid": row.get("standid"),
            "devclass": row.get("devclass"),
            "poly_ha": row.get("poly_ha"),
            "op_cut": row.get("op_cut"),
            "restricted": row.get("restricted"),
            "n_cells": int(m.sum()),
            "slope_mean": float(np.nanmean(s)),
            "slope_p95": float(np.nanpercentile(s, 95)),
            "twi_mean": float(np.nanmean(t)),
            "wet_frac": float(np.nanmean(t > wet_cut)),
            "steep_frac": float(np.nanmean(s > steep_cut)),
        })

    df = gpd.pd.DataFrame(rows)

    # Wet and steep are DIFFERENT problems with different mitigations, so they
    # get separate flags rather than one blended score:
    #   wet   -> a scheduling problem. Cut on frozen ground.
    #   steep -> an access problem. Winch assist, or leave it.
    # Merging them into a single "sensitivity" number was the first thing this
    # script got wrong: stands that were 89% steep came out labelled
    # "summer-trafficable" because the season rule only looked at wetness.
    df["season"] = np.where(df["wet_frac"] > 0.25, "frozen-ground only",
                    np.where(df["wet_frac"] > 0.10, "dry season preferred",
                             "summer-trafficable"))
    df["access"] = np.where(df["steep_frac"] > 0.30, "steep - review access",
                    np.where(df["steep_frac"] > 0.10, "winch assist advised",
                             "conventional"))
    df["flags"] = ((df["season"] != "summer-trafficable").astype(int)
                   + (df["access"] != "conventional").astype(int))

    out_csv = ROOT / f"{out_prefix}.csv"
    df.sort_values(["flags","wet_frac","steep_frac"], ascending=False).to_csv(out_csv, index=False)
    click.echo(f"\nwrote {out_csv}  ({len(df)} stands)")

    sched = df[(df["devclass"] == "04") & (df["op_cut"] == 1)]
    click.echo(f"\nstands in devclass 04 with a cutting proposal: {len(sched)}")
    if len(sched):
        click.echo("\n-- season (wetness) --")
        click.echo(sched["season"].value_counts().to_string())
        click.echo("\n-- access (slope) --")
        click.echo(sched["access"].value_counts().to_string())
        cols = ["standid","poly_ha","slope_mean","wet_frac","steep_frac","season","access"]
        click.echo("\nwettest scheduled stands (schedule for frozen ground):")
        click.echo(sched.nlargest(8, "wet_frac")[cols].to_string(index=False))
        click.echo("\nsteepest scheduled stands (access review):")
        click.echo(sched.nlargest(8, "steep_frac")[cols].to_string(index=False))
        both = sched[(sched["season"] != "summer-trafficable")
                     & (sched["access"] != "conventional")]
        click.echo(f"\nstands that are BOTH wet and steep: {len(both)}")

    # write rasters for mapping
    prof = {"driver":"GTiff","height":dem.shape[0],"width":dem.shape[1],
            "count":1,"dtype":"float32","crs":crs,"transform":transform,
            "nodata":-9999,"compress":"deflate"}
    for name, arr in [("slope", slope), ("twi", twi)]:
        with rasterio.open(ROOT / f"{out_prefix}_{name}.tif", "w", **prof) as d:
            d.write(arr.astype("float32"), 1)
    click.echo(f"wrote {out_prefix}_slope.tif and _twi.tif")


if __name__ == "__main__":
    main()
