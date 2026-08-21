r"""
Load detected trees into Snowflake as GEOGRAPHY points and run spatial queries.

Pipeline:
  1. Read data/nuuksio_detected_trees.csv (EPSG:3067 / TM35FIN)
  2. Reproject to EPSG:4326 (WGS84) — Snowflake GEOGRAPHY requires lat/lon
  3. write_pandas → staging table
  4. CREATE TABLE ... TO_GEOGRAPHY(wkt) → typed spatial table
  5. Run spatial queries (height distribution, neighbor crowding, grid density)
  6. Pull results back and visualize

Credentials come from environment variables only — nothing is written to disk.

  $env:SNOWFLAKE_ACCOUNT   = "myorg-myaccount"
  $env:SNOWFLAKE_USER      = "brooksg@zillowgroup.com"
  $env:SNOWFLAKE_ROLE      = "MY_ROLE"
  $env:SNOWFLAKE_WAREHOUSE = "MY_WH"
  $env:SNOWFLAKE_DATABASE  = "MY_DB"
  $env:SNOWFLAKE_SCHEMA    = "MY_SCHEMA"

Auth is key-pair if a key file is set (preferred — no password, no MFA prompt):

  $env:SNOWFLAKE_PRIVATE_KEY_FILE = "C:\Users\brook\.ssh\snowflake_key.p8"
  $env:SNOWFLAKE_PRIVATE_KEY_PWD  = "..."   # only if the key is encrypted

Otherwise it falls back to password auth:

  $env:SNOWFLAKE_AUTHENTICATOR = "snowflake"
  $env:SNOWFLAKE_PASSWORD      = "..."

Usage:
  python load_to_snowflake.py --dry-run   # reproject + preview, no Snowflake
  python load_to_snowflake.py             # full load + queries + viz
  python load_to_snowflake.py --no-viz    # skip the matplotlib window
"""
import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer

IN_CSV = "data/nuuksio_detected_trees.csv"
WGS84_CSV = "data/nuuksio_detected_trees_wgs84.csv"
FIG_OUT = "data/nuuksio_snowflake.png"

SRC_CRS = "EPSG:3067"   # ETRS89 / TM35FIN — what the LiDAR is in
DST_CRS = "EPSG:4326"   # WGS84 — what Snowflake GEOGRAPHY requires

STAGE_TABLE = "NUUKSIO_TREES_STG"
FINAL_TABLE = "NUUKSIO_TREES"

GRID_M = 50             # cell size for the density query, in meters
NEIGHBOR_M = 15         # radius for the crowding query, in meters


# ---------------------------------------------------------------- reprojection

def reproject(df: pd.DataFrame) -> pd.DataFrame:
    """Add lon/lat and a WKT POINT column, keeping the projected coords."""
    tf = Transformer.from_crs(SRC_CRS, DST_CRS, always_xy=True)
    lon, lat = tf.transform(df["x_tm35fin"].to_numpy(), df["y_tm35fin"].to_numpy())

    out = pd.DataFrame({
        "TREE_ID": np.arange(1, len(df) + 1, dtype="int64"),
        "X_TM35FIN": df["x_tm35fin"].to_numpy(),
        "Y_TM35FIN": df["y_tm35fin"].to_numpy(),
        "LON": lon,
        "LAT": lat,
        "HEIGHT_M": df["height_m"].to_numpy().astype(float),
        "IS_TRUE_POSITIVE": df["is_true_positive"].to_numpy().astype(bool),
    })
    # WKT is lon-then-lat. Six decimals ≈ 0.1 m at this latitude — plenty.
    out["GEOM_WKT"] = [f"POINT({x:.6f} {y:.6f})" for x, y in zip(lon, lat)]
    return out


def preview(df: pd.DataFrame) -> None:
    print(f"  rows:      {len(df):,}")
    print(f"  lon range: {df['LON'].min():.6f} → {df['LON'].max():.6f}")
    print(f"  lat range: {df['LAT'].min():.6f} → {df['LAT'].max():.6f}")
    print(f"  height:    {df['HEIGHT_M'].min():.1f}m → {df['HEIGHT_M'].max():.1f}m")
    print(f"  true pos:  {int(df['IS_TRUE_POSITIVE'].sum())} / {len(df)}")
    print()
    print(df[["TREE_ID", "LON", "LAT", "HEIGHT_M", "GEOM_WKT"]].head(3).to_string(index=False))


# ------------------------------------------------------------------ connection

def connect():
    """Open a Snowflake connection from environment variables."""
    import snowflake.connector

    required = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER",
                "SNOWFLAKE_DATABASE", "SNOWFLAKE_SCHEMA"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise SystemExit(
            "Missing environment variables: " + ", ".join(missing) +
            "\nSee the docstring at the top of this file."
        )

    # Default to key-pair if a key file is configured, else password.
    key_file = os.environ.get("SNOWFLAKE_PRIVATE_KEY_FILE")
    default_auth = "snowflake_jwt" if key_file else "snowflake"
    auth = os.environ.get("SNOWFLAKE_AUTHENTICATOR", default_auth)

    kwargs = dict(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        schema=os.environ["SNOWFLAKE_SCHEMA"],
        authenticator=auth,
    )
    if os.environ.get("SNOWFLAKE_ROLE"):
        kwargs["role"] = os.environ["SNOWFLAKE_ROLE"]
    if os.environ.get("SNOWFLAKE_WAREHOUSE"):
        kwargs["warehouse"] = os.environ["SNOWFLAKE_WAREHOUSE"]

    if auth == "snowflake_jwt":
        if not key_file:
            raise SystemExit(
                "SNOWFLAKE_AUTHENTICATOR=snowflake_jwt requires "
                "SNOWFLAKE_PRIVATE_KEY_FILE (path to your .p8 private key)"
            )
        if not Path(key_file).exists():
            raise SystemExit(f"Private key not found: {key_file}")
        kwargs["private_key_file"] = key_file
        # Only needed if the key itself is passphrase-encrypted
        if os.environ.get("SNOWFLAKE_PRIVATE_KEY_PWD"):
            kwargs["private_key_file_pwd"] = os.environ["SNOWFLAKE_PRIVATE_KEY_PWD"]
        print(f"  using key pair: {key_file}")
    elif auth == "snowflake":
        pw = os.environ.get("SNOWFLAKE_PASSWORD")
        if not pw:
            raise SystemExit("SNOWFLAKE_AUTHENTICATOR=snowflake requires SNOWFLAKE_PASSWORD")
        kwargs["password"] = pw

    print(f"Connecting to {kwargs['account']} as {kwargs['user']} ({auth})...")
    conn = snowflake.connector.connect(**kwargs)

    cur = conn.cursor()
    cur.execute("SELECT CURRENT_ACCOUNT(), CURRENT_ROLE(), CURRENT_WAREHOUSE(), "
                "CURRENT_DATABASE(), CURRENT_SCHEMA()")
    acct, role, wh, db, sch = cur.fetchone()
    cur.close()
    print(f"  connected: {acct} | role={role} | wh={wh} | {db}.{sch}\n")
    return conn


# ------------------------------------------------------------------------ load

def load(conn, df: pd.DataFrame) -> None:
    """Stage the DataFrame, then build a typed GEOGRAPHY table from it."""
    try:
        from snowflake.connector.pandas_tools import write_pandas
    except ImportError:
        raise SystemExit(
            "write_pandas needs pyarrow.  Run:  pixi add pyarrow"
        )

    print(f"Writing {len(df):,} rows → {STAGE_TABLE}")
    ok, nchunks, nrows, _ = write_pandas(
        conn, df, STAGE_TABLE,
        auto_create_table=True,
        overwrite=True,
        quote_identifiers=False,   # keep plain uppercase identifiers
    )
    if not ok:
        raise SystemExit("write_pandas reported failure")
    print(f"  {nrows:,} rows in {nchunks} chunk(s)\n")

    print(f"Building {FINAL_TABLE} with GEOGRAPHY column")
    cur = conn.cursor()
    cur.execute(f"""
        CREATE OR REPLACE TABLE {FINAL_TABLE} AS
        SELECT
            TREE_ID,
            X_TM35FIN,
            Y_TM35FIN,
            HEIGHT_M,
            IS_TRUE_POSITIVE,
            TO_GEOGRAPHY(GEOM_WKT) AS GEOM
        FROM {STAGE_TABLE}
    """)
    cur.execute(f"SELECT COUNT(*), COUNT(GEOM) FROM {FINAL_TABLE}")
    total, with_geom = cur.fetchone()
    cur.close()
    print(f"  {total:,} rows, {with_geom:,} with valid geography\n")
    if total != with_geom:
        print("  WARNING: some geometries failed to parse\n")


# --------------------------------------------------------------------- queries

def q(conn, sql: str) -> pd.DataFrame:
    cur = conn.cursor()
    try:
        cur.execute(sql)
        return pd.DataFrame(cur.fetchall(),
                            columns=[c[0] for c in cur.description])
    finally:
        cur.close()


def run_queries(conn) -> dict:
    results = {}
    line = "=" * 60

    print(line)
    print("SPATIAL QUERIES")
    print(line)

    # 1. Height distribution by class
    print("\n1. Height distribution")
    df = q(conn, f"""
        SELECT
            CASE
                WHEN HEIGHT_M < 10 THEN 'a. 6-10m'
                WHEN HEIGHT_M < 20 THEN 'b. 10-20m'
                WHEN HEIGHT_M < 30 THEN 'c. 20-30m'
                ELSE 'd. 30m+'
            END AS HEIGHT_CLASS,
            COUNT(*) AS N,
            ROUND(AVG(HEIGHT_M), 1) AS MEAN_H
        FROM {FINAL_TABLE}
        GROUP BY 1 ORDER BY 1
    """)
    for _, r in df.iterrows():
        print(f"   {r['HEIGHT_CLASS']:10} {int(r['N']):4} trees, mean {r['MEAN_H']}m")

    # 2. Tallest trees, with real-world coordinates back out of GEOGRAPHY
    print("\n2. Ten tallest trees")
    df = q(conn, f"""
        SELECT TREE_ID,
               ROUND(HEIGHT_M, 1) AS HEIGHT_M,
               ROUND(ST_Y(GEOM), 6) AS LAT,
               ROUND(ST_X(GEOM), 6) AS LON
        FROM {FINAL_TABLE}
        ORDER BY HEIGHT_M DESC
        LIMIT 10
    """)
    print(df.to_string(index=False))

    # 3. Crowding — self-join with ST_DWITHIN
    print(f"\n3. Neighbors within {NEIGHBOR_M}m (ST_DWITHIN self-join)")
    crowd = q(conn, f"""
        SELECT a.TREE_ID,
               a.HEIGHT_M,
               ST_Y(a.GEOM) AS LAT,
               ST_X(a.GEOM) AS LON,
               COUNT(b.TREE_ID) AS N_NEIGHBORS
        FROM {FINAL_TABLE} a
        LEFT JOIN {FINAL_TABLE} b
          ON b.TREE_ID <> a.TREE_ID
         AND ST_DWITHIN(a.GEOM, b.GEOM, {NEIGHBOR_M})
        GROUP BY 1, 2, 3, 4
    """)
    crowd["N_NEIGHBORS"] = crowd["N_NEIGHBORS"].astype(int)
    print(f"   mean neighbors:  {crowd['N_NEIGHBORS'].mean():.2f}")
    print(f"   max neighbors:   {crowd['N_NEIGHBORS'].max()}")
    print(f"   isolated (0):    {(crowd['N_NEIGHBORS'] == 0).sum()} trees")
    results["crowding"] = crowd

    # 4. Density on a projected grid (equal-area, unlike lat/lon binning)
    print(f"\n4. Stem density on a {GRID_M}m grid")
    grid = q(conn, f"""
        SELECT FLOOR(X_TM35FIN / {GRID_M}) * {GRID_M} AS CELL_X,
               FLOOR(Y_TM35FIN / {GRID_M}) * {GRID_M} AS CELL_Y,
               COUNT(*) AS N_TREES,
               ROUND(AVG(HEIGHT_M), 1) AS MEAN_HEIGHT,
               ROUND(MAX(HEIGHT_M), 1) AS MAX_HEIGHT
        FROM {FINAL_TABLE}
        GROUP BY 1, 2
        ORDER BY N_TREES DESC
    """)
    grid["N_TREES"] = grid["N_TREES"].astype(int)
    ha = (GRID_M * GRID_M) / 10_000.0
    print(f"   occupied cells:  {len(grid)}")
    print(f"   densest cell:    {grid['N_TREES'].max()} trees "
          f"({grid['N_TREES'].max()/ha:.0f} stems/ha)")
    print(f"   mean density:    {grid['N_TREES'].mean()/ha:.0f} stems/ha")
    results["grid"] = grid

    print("\n" + line)
    return results


# ------------------------------------------------------------------- visualize

def visualize(crowd: pd.DataFrame, grid: pd.DataFrame) -> None:
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(15, 6))

    sc = axes[0].scatter(crowd["LON"], crowd["LAT"],
                         c=crowd["HEIGHT_M"], s=18, cmap="YlGn",
                         vmin=6, vmax=40, edgecolor="black", linewidth=0.2)
    axes[0].set_title("Trees from Snowflake GEOGRAPHY\n(colored by height)")
    axes[0].set_xlabel("Longitude (WGS84)")
    axes[0].set_ylabel("Latitude (WGS84)")
    plt.colorbar(sc, ax=axes[0], shrink=0.8, label="Height (m)")

    ha = (GRID_M * GRID_M) / 10_000.0
    sc2 = axes[1].scatter(grid["CELL_X"] + GRID_M / 2,
                          grid["CELL_Y"] + GRID_M / 2,
                          c=grid["N_TREES"] / ha,
                          s=380, marker="s", cmap="viridis")
    axes[1].set_title(f"Stem density, {GRID_M}m grid\n(SQL GROUP BY on TM35FIN coords)")
    axes[1].set_xlabel("Easting (m, TM35FIN)")
    axes[1].set_ylabel("Northing (m, TM35FIN)")
    plt.colorbar(sc2, ax=axes[1], shrink=0.8, label="Stems / ha")

    plt.suptitle("Nuuksio trees — round-tripped through Snowflake", fontsize=13, y=1.00)
    plt.tight_layout()
    plt.savefig(FIG_OUT, dpi=110, bbox_inches="tight")
    print(f"Saved {FIG_OUT}")
    plt.show()


# ------------------------------------------------------------------------ main

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="reproject and preview only, no Snowflake connection")
    ap.add_argument("--no-viz", action="store_true", help="skip matplotlib output")
    args = ap.parse_args()

    if not Path(IN_CSV).exists():
        raise SystemExit(f"Missing {IN_CSV} — run detect_trees.py first")

    print(f"Reading {IN_CSV}")
    trees = reproject(pd.read_csv(IN_CSV))
    trees.to_csv(WGS84_CSV, index=False)
    print(f"Reprojected {SRC_CRS} → {DST_CRS}, wrote {WGS84_CSV}\n")
    preview(trees)

    if args.dry_run:
        print("\n--dry-run: stopping before Snowflake.")
        sys.exit(0)

    conn = connect()
    try:
        load(conn, trees)
        results = run_queries(conn)
    finally:
        conn.close()
        print("\nConnection closed.")

    if not args.no_viz:
        visualize(results["crowding"], results["grid"])
