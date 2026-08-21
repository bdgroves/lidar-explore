import sqlite3
c = sqlite3.connect(r"data\MV_L4132D.gpkg")
for t in ["stand", "restriction", "treestandsummary", "operation"]:
    print(f"\n===== {t} =====")
    for r in c.execute(f"PRAGMA table_info([{t}])"):
        print(f"  {r[1]:32} {r[2]}")
    row = c.execute(f"SELECT * FROM [{t}] LIMIT 1").fetchone()
    cols = [d[0] for d in c.execute(f"SELECT * FROM [{t}] LIMIT 1").description]
    print("  --- sample ---")
    for k, v in zip(cols, row):
        s = str(v)
        if len(s) > 60:
            s = s[:60] + "..."
        print(f"  {k:32} {s}")
