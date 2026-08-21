r"""
Fetch real Finnish canopy height model (Latvusmalli) tiles from the
Finnish Forest Centre open data service.

The Forest Centre publishes a GeoPackage index of every CHM tile, including
a direct download URL and precomputed height statistics. This script queries
that index locally, then downloads only the tiles you actually want.

Data: Suomen metsakeskus / Finnish Forest Centre, CC BY 4.0.
Attribution is required when publishing anything derived from it.

The CHM is a 1 m raster of canopy height above ground, derived from the
licensed 5 p laser data. Tiles are 6 km x 6 km, roughly 55-75 MB each.
Coordinate system is EPSG:3067, same as the synthetic sample.

Index download (once, ~70 MB zipped):
  https://avoin.metsakeskus.fi/aineistot/Latvusmalli/Latvusmalli_indeksi.zip
Unzip it and point INDEX_GPKG at the .gpkg inside.

Usage:
  # What tiles cover our Nuuksio study area, and what years exist?
  python fetch_metsakeskus.py --bbox 365200 6689400 365600 6689800 --list

  # Download every epoch for that sheet
  python fetch_metsakeskus.py --sheet L4132D --year all

  # Download one epoch and crop to a small AOI
  python fetch_metsakeskus.py --sheet L4132D --year 2020 \
      --crop 365200 6689400 365600 6689800

  # Find well-stocked forest tiles anywhere in the country
  python fetch_metsakeskus.py --tallest 15
"""
import argparse
import sqlite3
import sys
import urllib.request
from pathlib import Path

INDEX_GPKG = "data/Latvusmalli_indeksi.gpkg"
LAYER = "Latvusmalli_indeksi"
OUT_DIR = Path("data/metsakeskus")

FIELDS = """Tiedostonimi, Karttalehtitunnus, Vuosi, Tiedostokoko_KB,
            min_x, min_y, max_x, max_y,
            Min_pituus_m, Max_pituus_m, Keskipituus_m, pinta_ala_ha, Lataus_url"""


def connect():
    if not Path(INDEX_GPKG).exists():
        raise SystemExit(
            f"Missing {INDEX_GPKG}\n"
            "Download and unzip:\n"
            "  https://avoin.metsakeskus.fi/aineistot/Latvusmalli/Latvusmalli_indeksi.zip"
        )
    return sqlite3.connect(INDEX_GPKG)


def query(conn, where, params):
    sql = f"SELECT {FIELDS} FROM {LAYER} WHERE {where}"
    cols = ["name", "sheet", "year", "size_kb", "min_x", "min_y", "max_x", "max_y",
            "h_min", "h_max", "h_mean", "area_ha", "url"]
    return [dict(zip(cols, row)) for row in conn.execute(sql, params)]


def show(tiles, keep_order=False):
    if not tiles:
        print("  no tiles matched")
        return
    print(f"  {'file':28} {'year':>6} {'MB':>6} {'mean_h':>7} {'max_h':>6}")
    print("  " + "-" * 58)
    ordered = tiles if keep_order else sorted(tiles, key=lambda x: (x["sheet"], str(x["year"])))
    for t in ordered:
        print(f"  {t['name']:28} {str(t['year']):>6} "
              f"{t['size_kb']/1024:6.1f} {t['h_mean']:7.2f} {t['h_max']:6.2f}")


def download(tile) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dest = OUT_DIR / f"{tile['name']}.tif"
    if dest.exists():
        print(f"  already have {dest.name}")
        return dest

    total = tile["size_kb"] * 1024
    print(f"  downloading {dest.name} ({total/1e6:.0f} MB)")

    def hook(blocks, blocksize, _):
        got = blocks * blocksize
        pct = min(100.0, 100.0 * got / total) if total else 0
        print(f"\r    {pct:5.1f}%", end="", flush=True)

    tmp = dest.with_suffix(".tif.part")
    try:
        urllib.request.urlretrieve(tile["url"], tmp, reporthook=hook)
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"\n  download failed: {e}")
    tmp.rename(dest)
    print(f"\r    done -> {dest}")
    return dest


def crop(src_path: Path, bbox) -> Path:
    """Clip a downloaded tile to a bounding box, keeping CRS and resolution."""
    import rasterio
    from rasterio.windows import from_bounds

    minx, miny, maxx, maxy = bbox
    out = src_path.with_name(src_path.stem + "_crop.tif")
    with rasterio.open(src_path) as src:
        win = from_bounds(minx, miny, maxx, maxy, src.transform)
        data = src.read(1, window=win)
        profile = src.profile.copy()
        profile.update(height=data.shape[0], width=data.shape[1],
                       transform=src.window_transform(win), compress="deflate")
        with rasterio.open(out, "w", **profile) as dst:
            dst.write(data, 1)
    print(f"  cropped -> {out}  ({data.shape[1]} x {data.shape[0]} px)")
    return out


def summarize(path: Path):
    import numpy as np
    import rasterio
    with rasterio.open(path) as src:
        a = src.read(1).astype("float32")
        nod = src.nodata
        if nod is not None:
            a = np.where(a == nod, np.nan, a)
        print(f"\n  {path.name}")
        print(f"    size      {src.width} x {src.height} px @ {src.res[0]}m, {src.crs}")
        print(f"    height    mean {np.nanmean(a):.2f}m  max {np.nanmax(a):.2f}m")
        print(f"    canopy>5m {100*np.nanmean(a > 5):.1f}%")
        print(f"    nodata    {100*np.mean(np.isnan(a)):.1f}%")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sel = ap.add_argument_group("tile selection")
    sel.add_argument("--bbox", nargs=4, type=float, metavar=("MINX", "MINY", "MAXX", "MAXY"),
                     help="find tiles intersecting this box (EPSG:3067)")
    sel.add_argument("--sheet", help="map sheet id, e.g. L4132D")
    sel.add_argument("--tallest", type=int, metavar="N",
                     help="list the N tiles with greatest mean canopy height")
    sel.add_argument("--year", default="uusin",
                     help="2008 / 2015 / 2020 / uusin / all  (default: uusin = latest)")

    act = ap.add_argument_group("actions")
    act.add_argument("--list", action="store_true", help="list matches, download nothing")
    act.add_argument("--crop", nargs=4, type=float, metavar=("MINX", "MINY", "MAXX", "MAXY"),
                     help="after download, clip to this box")
    args = ap.parse_args()

    conn = connect()

    if args.tallest:
        # Exclude sliver tiles (coastal/border fragments) — a 1 MB tile with a
        # high mean is a handful of pixels, not a representative stand.
        tiles = query(conn,
                      "Vuosi = 'uusin' AND pinta_ala_ha > 3000 "
                      "ORDER BY Keskipituus_m DESC LIMIT ?",
                      (args.tallest,))
        print("\nTallest mean canopy, latest epoch (full 3600 ha tiles only):")
        show(tiles, keep_order=True)
        sys.exit(0)

    if args.bbox:
        minx, miny, maxx, maxy = args.bbox
        tiles = query(conn, "min_x <= ? AND max_x >= ? AND min_y <= ? AND max_y >= ?",
                      (maxx, minx, maxy, miny))
    elif args.sheet:
        tiles = query(conn, "Karttalehtitunnus = ?", (args.sheet,))
    else:
        raise SystemExit("Give one of --bbox, --sheet, or --tallest (see --help)")

    if args.year != "all":
        tiles = [t for t in tiles if str(t["year"]) == args.year]

    print(f"\nMatched {len(tiles)} tile(s):")
    show(tiles)

    if args.list or not tiles:
        sys.exit(0)

    total_mb = sum(t["size_kb"] for t in tiles) / 1024
    print(f"\nDownloading {len(tiles)} tile(s), {total_mb:.0f} MB total")
    for t in tiles:
        path = download(t)
        if args.crop:
            path = crop(path, args.crop)
        summarize(path)

    print("\nData: Suomen metsakeskus / Finnish Forest Centre, CC BY 4.0")
