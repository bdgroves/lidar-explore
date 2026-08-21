import sqlite3
c = sqlite3.connect(r"data\MV_L4132D.gpkg")
q = lambda s: list(c.execute(s))

print("=== treestand columns ===")
for r in q("PRAGMA table_info(treestand)"): print(f"  {r[1]:28} {r[2]}")
print("  sample rows:")
for r in q("SELECT * FROM treestand LIMIT 5"): print("   ", r)

print("\n=== restriction codes (290 rows) ===")
for r in q("SELECT restrictiontype, restrictioncode, COUNT(*) FROM restriction GROUP BY 1,2 ORDER BY 3 DESC"):
    print(f"  type={r[0]}  code={r[1]:>4}  n={r[2]}")

print("\n=== operation types ===")
for r in q("SELECT maintype, operationtype, COUNT(*), MIN(proposalyear), MAX(proposalyear) FROM operation GROUP BY 1,2 ORDER BY 3 DESC LIMIT 15"):
    print(f"  main={r[0]} op={r[1]:>3}  n={r[2]:>5}  years {r[3]}-{r[4]}")

print("\n=== developmentclass ===")
for r in q("SELECT developmentclass, COUNT(*) FROM stand GROUP BY 1 ORDER BY 2 DESC"):
    print(f"  {str(r[0]):>6}  {r[1]}")

print("\n=== stand area ===")
for r in q("SELECT COUNT(*), ROUND(SUM(area),1), ROUND(AVG(area),2), ROUND(MIN(area),2), ROUND(MAX(area),2) FROM stand"):
    print(f"  n={r[0]}  total={r[1]} ha  mean={r[2]}  range {r[3]}-{r[4]}")
