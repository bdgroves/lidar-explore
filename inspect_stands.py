import sqlite3
c = sqlite3.connect(r"data\MV_L4132D.gpkg")
print("--- LAYERS ---")
for r in c.execute("SELECT table_name, data_type, srs_id FROM gpkg_contents"):
    print(r)
print("--- TABLES ---")
for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'"):
    n = r[0]
    if not (n.startswith("gpkg_") or n.startswith("rtree_") or n.startswith("sqlite_")):
        cnt = c.execute(f"SELECT COUNT(*) FROM [{n}]").fetchone()[0]
        print(f"{n:40} {cnt:>8,} rows")
