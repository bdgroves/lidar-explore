r"""
Load the real Finnish forest stands into Snowflake as GEOGRAPHY polygons and
run the analysis in SQL.

Until now only the 358 synthetic detections were in the warehouse. This loads
what actually matters: 1,840 real stand polygons for sheet L4132D with their
inventory attributes, detection results and management status.

Why bother, when it all fits in pandas? Because the questions worth asking are
spatial and relational — which eligible stands sit on the boundary of land the
inventory does not cover, how detection recovery varies with stand size and
maturity, whether harvest candidates cluster. Those are joins and adjacency
tests, which is what a warehouse is for.

Reprojects EPSG:3067 -> EPSG:4326 (Snowflake GEOGRAPHY requires WGS84) while
keeping the projected area, since GEOGRAPHY area calculations and the
inventory's own hectare figures are worth cross-checking against each other.

Credentials from environment variables only. Same as load_to_snowflake.py:

  $env:SNOWFLAKE_ACCOUNT   = "AMEJZES-CAB92741"
  $env:SNOWFLAKE_USER      = "BDGROVES"
  $env:SNOWFLAKE_ROLE      = "ACCOUNTADMIN"
  $env:SNOWFLAKE_WAREHOUSE = "COMPUTE_WH"
  $env:SNOWFLAKE_DATABASE  = "LIDAR_DB"
  $env:SNOWFLAKE_SCHEMA    = "NUUKSIO"
  $env:SNOWFLAKE_PRIVATE_KEY_FILE = "C:\Users\brook\.snowflake\keys\rsa_key.p8"
  $env:SNOWFLAKE_PRIVATE_KEY_PWD  = "..."

Usage:
  python load_stands_to_snowflake.py --dry-run
  python load_stands_to_snowflake.py
  python load_stands_to_snowflake.py --queries-only
"""
import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

GPKG = "data/stands_joined.gpkg"
LAYER = "stands"
STAGE_TABLE = "STANDS_STG"
FINAL_TABLE = "STANDS"

SRC_CRS = "EPSG:3067"
DST_CRS = "EPSG:4326"


# ---------------------------------------------------------------- preparation

def prepare() -> pd.DataFrame:
    try:
        import geopandas as gpd
    except ImportError:
        raise SystemExit("Needs geopandas:  pixi add geopandas")
    if not Path(GPKG).exists():
        raise SystemExit(
            f"Missing {GPKG}\n"
            "Built by the QGIS session; regenerate from MV_L4132D.gpkg + "
            "stand_validation.csv if absent."
        )

    g = gpd.read_file(GPKG, layer=LAYER)
    if g.crs is None:
        g = g.set_crs(3067)

    # Snowflake validates GEOGRAPHY strictly and rejects self-intersecting
    # rings outright, failing the whole DML. Source cadastral polygons often
    # contain slivers and bowties, so repair before loading rather than after.
    bad = ~g.geometry.is_valid
    n_bad = int(bad.sum())
    if n_bad:
        print(f"  invalid geometries: {n_bad} -> repairing with make_valid()")
        g.loc[bad, "geometry"] = g.loc[bad, "geometry"].make_valid()

    # make_valid can yield collections; keep only polygonal parts.
    def polys_only(geom):
        if geom is None or geom.is_empty:
            return geom
        if geom.geom_type in ("Polygon", "MultiPolygon"):
            return geom
        parts = [x for x in getattr(geom, "geoms", []) 
                 if x.geom_type in ("Polygon", "MultiPolygon")]
        if not parts:
            return None
        from shapely.ops import unary_union
        return unary_union(parts)

    g["geometry"] = g.geometry.apply(polys_only)

    # A tiny buffer(0) pass closes remaining ring-order and touching-vertex
    # issues that make_valid leaves behind.
    still_bad = ~g.geometry.is_valid
    if int(still_bad.sum()):
        print(f"  still invalid: {int(still_bad.sum())} -> buffer(0)")
        g.loc[still_bad, "geometry"] = g.loc[still_bad, "geometry"].buffer(0)

    before = len(g)
    g = g[g.geometry.notna() & ~g.geometry.is_empty].copy()
    if len(g) < before:
        print(f"  dropped {before - len(g)} empty geometries")

    # Projected area first — TM35FIN is equal-area enough at this scale, and it
    # gives an independent check on the GEOGRAPHY areas Snowflake computes.
    g["AREA_M2_PROJ"] = g.geometry.area
    g4326 = g.to_crs(DST_CRS)

    out = pd.DataFrame({
        "STANDID": g["standid"].astype("int64"),
        "DEVCLASS": g["devclass"].astype("string").fillna("NA"),
        "SPECIES": pd.to_numeric(g["species"], errors="coerce"),
        "POLY_HA": g["poly_ha"],
        "AREA_M2_PROJ": g["AREA_M2_PROJ"],
        "MEANHEIGHT": g["meanheight"],
        "STEMCOUNT": g["stemcount"],
        "BASALAREA": g["basalarea"],
        "VOLUME": g["volume"],
        "DET_STEMS_HA": g["det_stems_ha"],
        "DET_MEAN_H": g["det_mean_h"],
        "CHM_MEAN_H": g["chm_mean_h"],
        "CANOPY_FRAC": g["canopy_frac"],
        "OBS_GAP": g["obs_gap"],
        "USABLE_INV": g["usable_inv"].astype(bool),
        "ELIGIBLE": g["eligible"].astype(bool),
        "OP_CUT": g["op_cut"].astype(bool),
        "RESTRICTED": g["restricted"].astype(bool),
        "GEOM_WKT": g4326.geometry.to_wkt(rounding_precision=7),
    })
    return out.replace({np.nan: None})


def preview(df):
    print(f"  stands        {len(df):,}")
    print(f"  total area    {df['POLY_HA'].sum():,.0f} ha")
    print(f"  eligible      {int(df['ELIGIBLE'].sum())}")
    print(f"  with cut plan {int(df['OP_CUT'].sum())}")
    print(f"  wkt bytes     avg {df['GEOM_WKT'].str.len().mean():,.0f}, "
          f"max {df['GEOM_WKT'].str.len().max():,}")
    print()
    print(df[["STANDID", "DEVCLASS", "POLY_HA", "DET_STEMS_HA"]].head(3).to_string(index=False))


# ------------------------------------------------------------------ connection

def connect():
    import snowflake.connector
    req = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_DATABASE", "SNOWFLAKE_SCHEMA"]
    missing = [k for k in req if not os.environ.get(k)]
    if missing:
        raise SystemExit("Missing env vars: " + ", ".join(missing))

    key_file = os.environ.get("SNOWFLAKE_PRIVATE_KEY_FILE")
    auth = os.environ.get("SNOWFLAKE_AUTHENTICATOR",
                          "snowflake_jwt" if key_file else "snowflake")
    kw = dict(account=os.environ["SNOWFLAKE_ACCOUNT"], user=os.environ["SNOWFLAKE_USER"],
              database=os.environ["SNOWFLAKE_DATABASE"], schema=os.environ["SNOWFLAKE_SCHEMA"],
              authenticator=auth)
    for env, key in [("SNOWFLAKE_ROLE", "role"), ("SNOWFLAKE_WAREHOUSE", "warehouse")]:
        if os.environ.get(env):
            kw[key] = os.environ[env]
    if auth == "snowflake_jwt":
        if not Path(key_file or "").exists():
            raise SystemExit(f"Private key not found: {key_file}")
        kw["private_key_file"] = key_file
        if os.environ.get("SNOWFLAKE_PRIVATE_KEY_PWD"):
            kw["private_key_file_pwd"] = os.environ["SNOWFLAKE_PRIVATE_KEY_PWD"]
    elif auth == "snowflake":
        pw = os.environ.get("SNOWFLAKE_PASSWORD")
        if not pw:
            raise SystemExit("Password auth needs SNOWFLAKE_PASSWORD")
        kw["password"] = pw

    print(f"Connecting to {kw['account']} ({auth})...")
    conn = snowflake.connector.connect(**kw)
    cur = conn.cursor()
    cur.execute("SELECT CURRENT_ROLE(), CURRENT_WAREHOUSE(), CURRENT_DATABASE(), CURRENT_SCHEMA()")
    print("  {} | {} | {}.{}\n".format(*cur.fetchone()))
    cur.close()
    return conn


def load(conn, df):
    from snowflake.connector.pandas_tools import write_pandas
    print(f"Staging {len(df):,} rows -> {STAGE_TABLE}")
    ok, _, n, _ = write_pandas(conn, df, STAGE_TABLE, auto_create_table=True,
                               overwrite=True, quote_identifiers=False)
    if not ok:
        raise SystemExit("write_pandas failed")
    print(f"  {n:,} rows staged")

    cur = conn.cursor()
    # TRY_TO_GEOGRAPHY returns NULL on a bad polygon instead of aborting the
    # whole DML, so one malformed stand cannot cost us the other 1,839.
    cur.execute(f"""
        CREATE OR REPLACE TABLE {FINAL_TABLE} AS
        SELECT * EXCLUDE GEOM_WKT,
               TRY_TO_GEOGRAPHY(GEOM_WKT) AS GEOM
        FROM {STAGE_TABLE}
    """)
    cur.execute(f"SELECT COUNT(*), COUNT(GEOM) FROM {FINAL_TABLE}")
    total, valid = cur.fetchone()
    if total != valid:
        cur.execute(f"SELECT STANDID FROM {FINAL_TABLE} WHERE GEOM IS NULL LIMIT 10")
        ids = [r[0] for r in cur.fetchall()]
        print(f"  rejected standids (first 10): {ids}")
    cur.close()
    print(f"Built {FINAL_TABLE}: {total:,} rows, {valid:,} valid geographies\n")
    if total != valid:
        print(f"  {total - valid} polygon(s) still rejected; they are NULL in GEOM.")
        print("  Spatial queries below exclude them automatically.\n")


# --------------------------------------------------------------------- queries

def q(conn, sql):
    cur = conn.cursor()
    try:
        cur.execute(sql)
        return pd.DataFrame(cur.fetchall(), columns=[c[0] for c in cur.description])
    finally:
        cur.close()


QUERIES = [
    ("Geometry check: GEOGRAPHY area vs projected area", f"""
        SELECT ROUND(SUM(ST_AREA(GEOM)) / 10000, 1)        AS GEOG_HA,
               ROUND(SUM(AREA_M2_PROJ) / 10000, 1)         AS PROJ_HA,
               ROUND(100 * (SUM(ST_AREA(GEOM)) - SUM(AREA_M2_PROJ))
                     / SUM(AREA_M2_PROJ), 3)               AS PCT_DIFF
        FROM {FINAL_TABLE} WHERE GEOM IS NOT NULL
     """, "If PCT_DIFF is near zero the reprojection and GEOGRAPHY cast are sound."),

    ("Detection recovery by development class", f"""
        SELECT DEVCLASS,
               COUNT(*)                                    AS N,
               ROUND(SUM(POLY_HA), 0)                      AS HA,
               ROUND(AVG(STEMCOUNT), 0)                    AS INV_STEMS_HA,
               ROUND(AVG(DET_STEMS_HA), 0)                 AS DET_STEMS_HA,
               ROUND(100 * MEDIAN(DET_STEMS_HA / NULLIF(STEMCOUNT, 0)), 1) AS RECOVERY_PCT,
               ROUND(AVG(MEANHEIGHT), 1)                   AS INV_H,
               ROUND(AVG(DET_MEAN_H), 1)                   AS DET_H
        FROM {FINAL_TABLE}
        WHERE USABLE_INV AND STEMCOUNT > 0
        GROUP BY DEVCLASS
        HAVING COUNT(*) >= 5
        ORDER BY DEVCLASS
     """, "Recovery should rise with maturity: bigger, better-separated crowns."),

    ("Height estimators bracket the inventory", f"""
        SELECT ROUND(AVG(DET_MEAN_H), 2)                   AS DETECTED_STEMS,
               ROUND(AVG(MEANHEIGHT), 2)                   AS INVENTORY,
               ROUND(AVG(CHM_MEAN_H), 2)                   AS ALL_PIXELS,
               ROUND(AVG(DET_MEAN_H - MEANHEIGHT), 2)      AS DET_BIAS,
               ROUND(AVG(CHM_MEAN_H - MEANHEIGHT), 2)      AS PIX_BIAS,
               ROUND(CORR(DET_MEAN_H, MEANHEIGHT), 3)      AS R_DETECTED,
               ROUND(CORR(CHM_MEAN_H, MEANHEIGHT), 3)      AS R_PIXELS
        FROM {FINAL_TABLE}
        WHERE USABLE_INV AND MEANHEIGHT IS NOT NULL
     """, "Same raster, opposite sign. The estimator decides."),

    ("Does stand size affect detection?", f"""
        SELECT CASE WHEN POLY_HA < 0.5  THEN 'a. <0.5 ha'
                    WHEN POLY_HA < 1.0  THEN 'b. 0.5-1 ha'
                    WHEN POLY_HA < 2.0  THEN 'c. 1-2 ha'
                    ELSE                     'd. 2+ ha'  END AS SIZE_BAND,
               COUNT(*)                                    AS N,
               ROUND(100 * MEDIAN(DET_STEMS_HA / NULLIF(STEMCOUNT, 0)), 1) AS RECOVERY_PCT,
               ROUND(AVG(CANOPY_FRAC), 3)                  AS CANOPY_FRAC
        FROM {FINAL_TABLE}
        WHERE USABLE_INV AND STEMCOUNT > 0
        GROUP BY 1 ORDER BY 1
     """, "Small stands have proportionally more edge, so recovery may differ."),

    ("Edge effect: eligible stands touching non-inventory land", f"""
        WITH eligible AS (SELECT STANDID, GEOM, POLY_HA FROM {FINAL_TABLE}
                          WHERE ELIGIBLE AND GEOM IS NOT NULL),
             nbr AS (
               SELECT e.STANDID,
                      e.POLY_HA,
                      COUNT(o.STANDID) AS NEIGHBOURS
               FROM eligible e
               LEFT JOIN {FINAL_TABLE} o
                 ON o.STANDID <> e.STANDID AND o.GEOM IS NOT NULL
                AND ST_DWITHIN(e.GEOM, o.GEOM, 40)
               GROUP BY 1, 2)
        SELECT CASE WHEN NEIGHBOURS = 0 THEN 'isolated (0)'
                    WHEN NEIGHBOURS <= 2 THEN 'edge (1-2)'
                    WHEN NEIGHBOURS <= 5 THEN 'interior (3-5)'
                    ELSE                      'core (6+)' END AS POSITION,
               COUNT(*)                       AS STANDS,
               ROUND(SUM(POLY_HA), 1)         AS HA
        FROM nbr GROUP BY 1
        ORDER BY STANDS DESC
     """, "Eligible stands with few private neighbours sit on the whitelist boundary "
          "— i.e. against state or protected land. This is the park-creep effect, in SQL."),

    ("Volume concentration: where is the wood?", f"""
        SELECT DEVCLASS,
               COUNT(*)                                     AS N,
               ROUND(SUM(VOLUME * POLY_HA), 0)              AS TOTAL_M3,
               ROUND(100 * SUM(VOLUME * POLY_HA)
                     / SUM(SUM(VOLUME * POLY_HA)) OVER (), 1) AS PCT_OF_TOTAL,
               ROUND(AVG(VOLUME), 0)                        AS M3_PER_HA
        FROM {FINAL_TABLE}
        WHERE VOLUME IS NOT NULL AND USABLE_INV
        GROUP BY DEVCLASS HAVING COUNT(*) >= 5
        ORDER BY TOTAL_M3 DESC
     """, "Standing volume by class — VOLUME is m3/ha, so weight by area."),

    ("Benchmark honesty check", f"""
        SELECT 'all stands >=0.3ha' AS POOL,
               COUNT(*) AS N, SUM(IFF(OP_CUT, 1, 0)) AS PROPOSED,
               ROUND(100 * AVG(IFF(OP_CUT, 1, 0)), 1) AS PCT
        FROM {FINAL_TABLE} WHERE POLY_HA >= 0.3
        UNION ALL
        SELECT 'development class 04', COUNT(*), SUM(IFF(OP_CUT, 1, 0)),
               ROUND(100 * AVG(IFF(OP_CUT, 1, 0)), 1)
        FROM {FINAL_TABLE} WHERE DEVCLASS = '04'
        UNION ALL
        SELECT 'eligible pool', COUNT(*), SUM(IFF(OP_CUT, 1, 0)),
               ROUND(100 * AVG(IFF(OP_CUT, 1, 0)), 1)
        FROM {FINAL_TABLE} WHERE ELIGIBLE
     """, "The eligible pool is near-saturated, so precision there is close to free."),
]


def run_queries(conn):
    line = "=" * 74
    print(line); print("SPATIAL SQL"); print(line)
    for i, (title, sql, note) in enumerate(QUERIES, 1):
        print(f"\n{i}. {title}")
        try:
            df = q(conn, sql)
        except Exception as e:
            print(f"   query failed: {e}")
            continue
        print(df.to_string(index=False) if not df.empty else "   (no rows)")
        print(f"   -> {note}")
    print("\n" + line)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="prepare only, no connection")
    ap.add_argument("--queries-only", action="store_true", help="skip the load")
    args = ap.parse_args()

    if not args.queries_only:
        print(f"Reading {GPKG}")
        df = prepare()
        print(f"Reprojected {SRC_CRS} -> {DST_CRS}\n")
        preview(df)
        if args.dry_run:
            print("\n--dry-run: stopping before Snowflake.")
            sys.exit(0)

    conn = connect()
    try:
        if not args.queries_only:
            load(conn, df)
        run_queries(conn)
    finally:
        conn.close()
        print("Connection closed.")
