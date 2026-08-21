import sqlite3, pandas as pd
c = sqlite3.connect(r"data\MV_L4132D.gpkg")
q = lambda s: pd.read_sql_query(s, c)

print("=== summaries per treestand type ===")
print(q("""SELECT ts.type, COUNT(*) n, MIN(ts.date) d0, MAX(ts.date) d1
           FROM treestand ts LEFT JOIN treestandsummary s
             ON s.treestandid = ts.treestandid
           WHERE s.treestandid IS NOT NULL GROUP BY ts.type""").to_string(index=False))

print("\n=== treestand rows by type (all) ===")
print(q("SELECT type, COUNT(*) n, MIN(date) d0, MAX(date) d1 FROM treestand GROUP BY type").to_string(index=False))

print("\n=== treestratum columns ===")
for r in c.execute("PRAGMA table_info(treestratum)"): print(f"  {r[1]:26} {r[2]}")

print("\n=== strata per treestand type ===")
print(q("""SELECT ts.type, COUNT(*) n FROM treestand ts
           JOIN treestratum st ON st.treestandid = ts.treestandid
           GROUP BY ts.type""").to_string(index=False))

print("\n=== sample type-1 strata ===")
print(q("""SELECT st.* FROM treestand ts JOIN treestratum st
           ON st.treestandid = ts.treestandid WHERE ts.type = 1 LIMIT 4""").to_string(index=False))
