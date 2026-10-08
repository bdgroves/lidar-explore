r"""
Rebuild data/stands_joined.gpkg (layer "stands"), the stand file that
machine_planning.py and load_stands_to_snowflake.py read.

It was first assembled by hand in a QGIS session. This makes it reproducible
from the open stand inventory alone, using stand_validate.load_stands() so the
columns mean exactly what they mean everywhere else in the project:

  standid, devclass, poly_ha, op_cut, restricted, obs_year, geometry

Data: Suomen metsakeskus / Finnish Forest Centre, CC BY 4.0.

    python build_stands_joined.py
"""
import sys

import stand_validate as sv

OUT = "data/stands_joined.gpkg"


def main() -> int:
    g = sv.load_stands()
    g["devclass"] = g["developmentclass"]
    g["poly_ha"] = g.geometry.area / 10_000.0
    keep = ["standid", "devclass", "poly_ha", "op_cut", "restricted", "obs_year", "geometry"]
    g[keep].to_file(OUT, layer="stands", driver="GPKG")
    sched = g[(g["devclass"] == "04") & (g["op_cut"] == 1)]
    print(f"wrote {OUT}: {len(g)} stands, {len(sched)} in class 04 with a cutting proposal")
    return 0


if __name__ == "__main__":
    sys.exit(main())
