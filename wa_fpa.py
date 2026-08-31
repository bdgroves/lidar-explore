"""
wa_fpa.py

Does terrain-derived slope predict which Washington timber harvest
applications DNR flags as involving potentially unstable slopes?

The Finnish harvest-ranking result in this repo was a clean null: the canopy
model added nothing over the forester's own maturity call (lift 1.00x). That
analysis had a weakness -- the "sensitivity" thresholds were percentiles I
chose, with no external standard to check them against.

Washington fixes that. DNR publishes every Forest Practices Application as an
open polygon layer, and each one carries UNSTABLE_SLOPE_FLG: the agency's own
determination, made by their staff under the Forest Practices rules, of
whether the unit involves potentially unstable slopes. That is a real label,
not one I invented, so "does terrain predict it?" is a question with an
answer that can come out either way.

Study area is Pacific Cascade region, SW Washington, spanning the steep
Willapa Hills through the flat Cowlitz floodplain -- deliberately chosen for
terrain contrast. The label is almost perfectly balanced there (50.3% Y),
so the baseline to beat is a coin flip.

    pixi run python wa_fpa.py --fetch      # download FPAs + DEM
    pixi run python wa_fpa.py              # run the test
"""
import json
from pathlib import Path

import click
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import requests
import richdem as rd
from rasterio.features import geometry_mask
from rasterio.merge import merge
from rasterio.windows import from_bounds
from shapely.geometry import shape

ROOT = Path(__file__).parent
DATA = ROOT / "data" / "wa_fpa"
FPA_URL = ("https://gis.dnr.wa.gov/site2/rest/services/Public_Forest_Practices/"
           "WADNR_PUBLIC_FP_FPA/MapServer/4/query")
DEM_URL = ("https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/"
           "current/{t}/USGS_13_{t}.tif")

WEST, SOUTH, EAST, NORTH = -123.60, 46.20, -122.55, 46.70
TILES = ["n47w124", "n47w123"]


def fetch_fpas(path):
    """Page the ArcGIS REST layer; it caps at 1000 features per request."""
    feats, offset = [], 0
    while True:
        p = {"f": "geojson", "where": "REGION_NM='PACIFIC CASCADE'",
             "geometry": f"{WEST},{SOUTH},{EAST},{NORTH}",
             "geometryType": "esriGeometryEnvelope", "inSR": 4326,
             "spatialRel": "esriSpatialRelIntersects", "outFields": "*",
             "outSR": 4326, "resultOffset": offset, "resultRecordCount": 1000}
        j = requests.get(FPA_URL, params=p, timeout=180).json()
        got = j.get("features", [])
        feats += got
        click.echo(f"    +{len(got)} (total {len(feats)})")
        if len(got) < 1000:
            break
        offset += 1000
    gdf = gpd.GeoDataFrame.from_features(feats, crs="EPSG:4326")
    gdf.to_file(path, driver="GPKG", layer="fpa")
    return gdf


def fetch_dem(path):
    """Range-request the study window out of each 1/3 arc-second COG."""
    parts = []
    for t in TILES:
        url = DEM_URL.format(t=t)
        with rasterio.open(url) as src:
            win = from_bounds(WEST, SOUTH, EAST, NORTH, src.transform)
            win = win.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
            data = src.read(1, window=win)
            prof = src.profile.copy()
            prof.update(height=data.shape[0], width=data.shape[1],
                        transform=src.window_transform(win), compress="deflate")
        p = path.parent / f"_dem_{t}.tif"
        with rasterio.open(p, "w", **prof) as d:
            d.write(data, 1)
        parts.append(p)
        click.echo(f"    {t}: {data.shape}")
    srcs = [rasterio.open(p) for p in parts]
    mosaic, tr = merge(srcs)
    prof = srcs[0].profile.copy()
    prof.update(height=mosaic.shape[1], width=mosaic.shape[2],
                transform=tr, compress="deflate")
    with rasterio.open(path, "w", **prof) as d:
        d.write(mosaic[0], 1)
    for s in srcs:
        s.close()
    for p in parts:
        p.unlink()


@click.command()
@click.option("--fetch", is_flag=True, help="Download FPA polygons and DEM first")
def main(fetch):
    DATA.mkdir(parents=True, exist_ok=True)
    fpa_p, dem_p = DATA / "fpa.gpkg", DATA / "dem.tif"

    if fetch or not fpa_p.exists():
        click.echo("fetching FPA polygons...")
        fetch_fpas(fpa_p)
    if fetch or not dem_p.exists():
        click.echo("fetching DEM windows...")
        fetch_dem(dem_p)

    gdf = gpd.read_file(fpa_p, layer="fpa")
    click.echo(f"\n{len(gdf)} harvest units")

    # project to metric before measuring slope
    with rasterio.open(dem_p) as src:
        dem = src.read(1).astype(np.float32)
        transform, crs, nod = src.transform, src.crs, src.nodata
    dem[dem == nod] = np.nan
    dem[dem < -100] = np.nan

    # 1/3 arc-second: cell is ~10 m N-S, less E-W at this latitude
    lat = (NORTH + SOUTH) / 2
    cy = abs(transform.e) * 110540
    cx = abs(transform.a) * 111320 * np.cos(np.radians(lat))
    click.echo(f"DEM {dem.shape}, cell ~{cx:.1f} x {cy:.1f} m")

    filled = np.where(np.isnan(dem), np.nanmin(dem), dem)
    rda = rd.rdarray(filled.astype(np.float64), no_data=-9999)
    # richdem assumes square cells; use the mean and note the small anisotropy
    rda.geotransform = (transform.c, (cx + cy) / 2, 0, transform.f, 0, -(cx + cy) / 2)
    slope = np.array(rd.TerrainAttribute(rda, attrib="slope_degrees"))

    # Zonal stats, windowed. Masking the full 61 Mpx grid once per unit was the
    # first version and took tens of minutes for 1,605 units: each call
    # allocated a whole-grid boolean array. Rasterising inside each polygon's
    # own bounding window is the same answer, orders of magnitude cheaper.
    inv = ~transform
    rows = []
    for _, r in gdf.iterrows():
        g = r.geometry
        if g is None or g.is_empty:
            continue
        minx, miny, maxx, maxy = g.bounds
        c0, r1 = inv * (minx, miny)
        c1, r0 = inv * (maxx, maxy)
        c0, c1 = int(np.floor(min(c0, c1))), int(np.ceil(max(c0, c1)))
        r0, r1 = int(np.floor(min(r0, r1))), int(np.ceil(max(r0, r1)))
        c0, r0 = max(c0, 0), max(r0, 0)
        c1, r1 = min(c1, dem.shape[1]), min(r1, dem.shape[0])
        if c1 <= c0 or r1 <= r0:
            continue
        win_tr = rasterio.transform.from_origin(
            transform.c + c0 * transform.a, transform.f + r0 * transform.e,
            transform.a, -transform.e)
        try:
            m = geometry_mask([g], out_shape=(r1 - r0, c1 - c0),
                              transform=win_tr, invert=True, all_touched=True)
        except Exception:
            continue
        if m.sum() < 4:
            continue
        s = slope[r0:r1, c0:c1][m]
        rows.append({"FP_ID": r.get("FP_ID"),
                     "flag": r.get("UNSTABLE_SLOPE_FLG"),
                     "classification": r.get("CLASSIFICATION"),
                     "acres": r.get("TIMHARV_RPT_AREA"),
                     "n_cells": int(m.sum()),
                     "slope_mean": float(np.nanmean(s)),
                     "slope_p90": float(np.nanpercentile(s, 90)),
                     "slope_max": float(np.nanmax(s)),
                     "frac_over_30": float(np.nanmean(s > 30))})
    df = pd.DataFrame(rows)
    df = df[df["flag"].isin(["Y", "N"])]
    df.to_csv(DATA / "fpa_slope.csv", index=False)
    click.echo(f"scored {len(df)} units -> {DATA/'fpa_slope.csv'}")

    def auc_of(frame, col):
        yy = (frame["flag"] == "Y").values
        r = frame[col].rank().values
        n1, n0 = yy.sum(), (~yy).sum()
        return (r[yy].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)

    # UNSTABLE_SLOPE_FLG is set per APPLICATION, not per harvest unit -- it never
    # varies between units sharing an FP_ID. Scoring units would pseudo-replicate:
    # 1,533 units are only ~1,024 independent decisions, and multi-unit
    # applications would get extra weight purely for being subdivided.
    varies = df.groupby("FP_ID")["flag"].nunique().gt(1).sum()
    click.echo(f"\nFP_IDs whose flag varies between units: {varies} "
               f"(0 => flag is an application attribute)")
    app = df.groupby("FP_ID").agg(flag=("flag", "first"),
                                  acres=("acres", "sum"),
                                  slope_mean=("slope_mean", "mean"),
                                  slope_p90=("slope_p90", "max"),
                                  slope_max=("slope_max", "max"),
                                  frac_over_30=("frac_over_30", "max"))
    click.echo(f"{len(df)} units -> {len(app)} applications")

    for label, frame in [("per unit (pseudo-replicated)", df),
                         ("per application (correct)", app)]:
        yy = (frame["flag"] == "Y").values
        click.echo(f"\n-- {label} --  n={len(frame)}  base rate Y={yy.mean()*100:.1f}%")
        click.echo("                    flagged N   flagged Y   separation")
        for col in ["slope_mean", "slope_p90", "slope_max", "frac_over_30"]:
            a, b = frame.loc[~yy, col], frame.loc[yy, col]
            click.echo(f"  {col:<16} {a.median():9.2f} {b.median():11.2f} "
                       f"     AUC {auc_of(frame, col):.3f}")

    app.to_csv(DATA / "fpa_slope_by_application.csv")
    click.echo(f"\nwrote {DATA/'fpa_slope_by_application.csv'}")
    click.echo("AUC 0.50 = no better than a coin flip; 1.00 = perfect separation.")


if __name__ == "__main__":
    main()
