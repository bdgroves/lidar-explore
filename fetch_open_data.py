r"""
Fetch every open input the real track needs, from scratch, so the whole
pipeline can be rebuilt anywhere (GitHub Actions runs this; see
.github/workflows/rebuild.yml).

  data/Latvusmalli_indeksi.gpkg          Forest Centre CHM tile index
  data/metsakeskus/CHM_L4132D_<year>.tif 1 m canopy height model, every epoch
  data/MV_L4132D.gpkg                    Metsavarakuviot stand inventory for the sheet
  data/metsakeskus/DTM_L4132D.tif        NLS 1 m DTM for the sheet, from CSC's open VRT

Data: Suomen metsakeskus / Finnish Forest Centre, CC BY 4.0;
      Maanmittauslaitos / National Land Survey of Finland, CC BY 4.0.

Files that already exist are skipped, so an interrupted run can restart.

Usage:
  python fetch_open_data.py                 # everything for L4132D
  python fetch_open_data.py --sheet L4132D --years 2008 2015 2020
"""
import argparse
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

import fetch_metsakeskus as fm

DATA = Path("data")
INDEX_ZIP_URL = "https://avoin.metsakeskus.fi/aineistot/Latvusmalli/Latvusmalli_indeksi.zip"
# avoin.metsakeskus.fi redirects into this public bucket; some networks are refused at
# the front door but not here.
S3 = "https://juuri-storagezone-files-prod.s3.eu-west-1.amazonaws.com/Public"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")
DTM_VRT = "https://vm0160.kaj.pouta.csc.fi/mml/korkeusmalli/km2/2020/km2_2020.vrt"

# The stand inventory is published per map sheet (karttalehti). The exact file
# name isn't documented in one place, so try the known patterns in order.
MV_CANDIDATES = [
    "https://avoin.metsakeskus.fi/aineistot/Metsavarakuviot/Karttalehti/MV_{sheet}.gpkg",
    "https://avoin.metsakeskus.fi/aineistot/Metsavarakuviot/Karttalehti/MV_{sheet}.zip",
    "https://avoin.metsakeskus.fi/aineistot/Metsavarakuviot/Karttalehti/{sheet}.gpkg",
    "https://avoin.metsakeskus.fi/aineistot/Metsavarakuviot/Karttalehti/{sheet}.zip",
]


def alternates(url: str):
    """The URL, then the same file straight from the storage bucket."""
    yield url
    pre = "https://avoin.metsakeskus.fi/aineistot/"
    if url.startswith(pre):
        yield S3 + "/" + url[len(pre):]


def get(url: str, dest: Path) -> bool:
    return any(get_one(u, dest) for u in alternates(url))


def get_one(url: str, dest: Path) -> bool:
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as f:
            shutil.copyfileobj(r, f, length=1 << 20)
    except Exception as e:                                     # noqa: BLE001
        tmp.unlink(missing_ok=True)
        print(f"  {url} -> {e}")
        return False
    tmp.replace(dest)
    print(f"  {url} -> {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
    return True


def unzip_first(zpath: Path, suffix: str, dest: Path) -> None:
    with zipfile.ZipFile(zpath) as z:
        name = next(n for n in z.namelist() if n.lower().endswith(suffix))
        with z.open(name) as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)
    print(f"  unzipped {name} -> {dest}")


def fetch_index() -> None:
    gpkg = Path(fm.INDEX_GPKG)
    if gpkg.exists():
        print(f"index present: {gpkg}")
        return
    z = DATA / "Latvusmalli_indeksi.zip"
    if not z.exists() and not get(INDEX_ZIP_URL, z):
        raise SystemExit("could not download the CHM index")
    unzip_first(z, ".gpkg", gpkg)
    z.unlink()


def fetch_chm(sheet: str, years) -> tuple:
    conn = fm.connect()
    tiles = fm.query(conn, "Karttalehtitunnus = ?", (sheet,))
    if not tiles:
        raise SystemExit(f"no CHM tiles for sheet {sheet}")
    fm.show(tiles)
    have = sorted({str(t["year"]) for t in tiles})
    want = [y for y in (years or have) if y in have]
    for t in tiles:
        if str(t["year"]) not in want:
            continue
        path = fm.OUT_DIR / f"{t['name']}.tif"
        if not path.exists() and not get(t["url"], path):
            raise SystemExit(f"could not download {t['name']}")
        std = fm.OUT_DIR / f"CHM_{sheet}_{t['year']}.tif"   # the name stand_validate.py reads
        if path != std and not std.exists():
            shutil.copyfile(path, std)
            print(f"  -> {std}")
    t = tiles[0]
    return t["min_x"], t["min_y"], t["max_x"], t["max_y"]


def fetch_mv(sheet: str) -> None:
    dest = DATA / f"MV_{sheet}.gpkg"
    if dest.exists():
        print(f"stands present: {dest}")
        return
    for pattern in MV_CANDIDATES:
        url = pattern.format(sheet=sheet)
        tmp = DATA / Path(url).name
        if get(url, tmp):
            if tmp.suffix == ".zip":
                unzip_first(tmp, ".gpkg", dest)
                tmp.unlink()
            elif tmp != dest:
                tmp.replace(dest)
            return
    raise SystemExit(f"could not find the Metsavarakuviot file for {sheet}; tried:\n  "
                     + "\n  ".join(p.format(sheet=sheet) for p in MV_CANDIDATES))


def fetch_dtm(sheet: str, bounds) -> None:
    import rasterio
    from rasterio.windows import from_bounds
    dest = fm.OUT_DIR / f"DTM_{sheet}.tif"
    if dest.exists():
        print(f"DTM present: {dest}")
        return
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        with rasterio.open("/vsicurl/" + DTM_VRT) as src:
            win = from_bounds(*bounds, src.transform)
            arr = src.read(1, window=win)
            prof = src.profile.copy()
            prof.update(driver="GTiff", height=arr.shape[0], width=arr.shape[1],
                        transform=src.window_transform(win), compress="deflate", tiled=True)
            prof.pop("blockxsize", None), prof.pop("blockysize", None)
    tmp = dest.with_suffix(".part.tif")
    with rasterio.open(tmp, "w", **prof) as d:
        d.write(arr, 1)
    tmp.replace(dest)
    print(f"  DTM -> {dest} ({arr.shape[1]} x {arr.shape[0]})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sheet", default="L4132D")
    ap.add_argument("--years", nargs="*", default=None, help="CHM epochs (default: all)")
    ap.add_argument("--skip-dtm", action="store_true")
    args = ap.parse_args()
    DATA.mkdir(exist_ok=True)
    fm.OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("== CHM index"); fetch_index()
    print("== CHM tiles"); bounds = fetch_chm(args.sheet, args.years)
    print("== stand inventory"); fetch_mv(args.sheet)
    if not args.skip_dtm:
        print("== DTM"); fetch_dtm(args.sheet, bounds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
