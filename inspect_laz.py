"""
Inspect a LAZ/LAS point cloud file.

Reads the first .laz or .las found in ./data and prints
size, density, extent, CRS, and classification breakdown.

Usage (from project root, inside pixi shell):
    python inspect.py
"""
from pathlib import Path
import laspy
import numpy as np


def main() -> None:
    data_dir = Path("data")
    if not data_dir.exists():
        raise SystemExit("No ./data folder found. Create it and drop a .laz file in.")

    laz_files = sorted(list(data_dir.glob("*.laz")) + list(data_dir.glob("*.las")))
    if not laz_files:
        raise SystemExit("No .laz or .las files found in ./data")

    path = laz_files[0]
    print(f"Reading: {path.name}\n")

    las = laspy.read(str(path))

    extent_x = las.header.maxs[0] - las.header.mins[0]
    extent_y = las.header.maxs[1] - las.header.mins[1]
    area_m2 = extent_x * extent_y
    density = len(las.points) / area_m2 if area_m2 > 0 else 0

    crs = las.header.parse_crs()
    crs_name = crs.name if crs is not None else "none"

    print(f"Points:     {len(las.points):,}")
    print(f"Density:    {density:.1f} pts/m²")
    print(f"Area:       {extent_x:.0f}m × {extent_y:.0f}m  ({area_m2/10000:.1f} ha)")
    print(f"Elevation:  {las.header.mins[2]:.1f}m to {las.header.maxs[2]:.1f}m  "
          f"(relief: {las.header.maxs[2] - las.header.mins[2]:.1f}m)")
    print(f"CRS:        {crs_name}")
    print(f"LAS ver:    {las.header.version}, point format: {las.header.point_format.id}")

    classes = {
        0: "never classified", 1: "unclassified", 2: "ground",
        3: "low veg", 4: "med veg", 5: "high veg",
        6: "building", 7: "noise", 9: "water",
    }

    print("\nClassifications:")
    vals, counts = np.unique(las.classification, return_counts=True)
    for c, n in zip(vals, counts):
        label = classes.get(int(c), "?")
        pct = 100 * n / len(las.points)
        print(f"  {int(c):>2} ({label:<16}): {n:>10,}  ({pct:5.1f}%)")

    # Quick sanity flags
    class5_pct = 100 * counts[vals == 5].sum() / len(las.points) if 5 in vals else 0
    class2_pct = 100 * counts[vals == 2].sum() / len(las.points) if 2 in vals else 0

    print()
    if density < 2:
        print("⚠  Low density — CHM will look chunky.")
    elif density >= 8:
        print("✓  Excellent density.")
    else:
        print("✓  Decent density.")

    if class5_pct < 5:
        print("⚠  Very little high vegetation — either not a forest, or not pre-classified.")
    else:
        print(f"✓  {class5_pct:.0f}% high veg — good forest tile.")

    if class2_pct < 5:
        print("⚠  Almost no ground points — we'd need to classify ground with PDAL SMRF.")
    else:
        print(f"✓  {class2_pct:.0f}% ground — good for CHM.")


if __name__ == "__main__":
    main()
