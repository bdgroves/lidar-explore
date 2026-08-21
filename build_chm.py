"""
Build a Canopy Height Model (CHM) from a LiDAR point cloud using PDAL.

For each 1m grid cell:
  1. Compute height-above-ground for every point (HeightAboveGround dimension)
  2. Take the MAX height in each cell → that's the CHM

Also writes a bare-earth DEM (ground points only, mean elevation per cell) as a bonus.

Outputs (in ./data):
  chm.tif  — canopy height in meters
  dem.tif  — bare-earth elevation in meters
"""
import json
from pathlib import Path
import pdal


INPUT = "data/sample_forest.laz"
CHM_OUT = "data/chm.tif"
DEM_OUT = "data/dem.tif"
RES = 1.0  # meters per pixel


def build_chm() -> None:
    """CHM: height above ground, max per cell."""
    pipeline = {
        "pipeline": [
            {"type": "readers.las", "filename": INPUT},
            # Compute height-above-ground for every point using nearest ground neighbors.
            # Requires that ground points are already classified (class 2) — ours are.
            {"type": "filters.hag_nn", "count": 3},
            # Sanity range: drop anything absurd (birds, noise, negative)
            {"type": "filters.range", "limits": "HeightAboveGround[0:80]"},
            {
                "type": "writers.gdal",
                "filename": CHM_OUT,
                "resolution": RES,
                "output_type": "max",
                "dimension": "HeightAboveGround",
                "data_type": "float32",
                "nodata": -9999,
            },
        ]
    }
    print(f"Building CHM → {CHM_OUT}")
    n = pdal.Pipeline(json.dumps(pipeline)).execute()
    print(f"  processed {n:,} points")


def build_dem() -> None:
    """Bare-earth DEM: ground points only, mean elevation per cell."""
    pipeline = {
        "pipeline": [
            {"type": "readers.las", "filename": INPUT},
            {"type": "filters.range", "limits": "Classification[2:2]"},
            {
                "type": "writers.gdal",
                "filename": DEM_OUT,
                "resolution": RES,
                "output_type": "mean",
                "data_type": "float32",
                "nodata": -9999,
            },
        ]
    }
    print(f"Building DEM → {DEM_OUT}")
    n = pdal.Pipeline(json.dumps(pipeline)).execute()
    print(f"  used {n:,} ground points")


def preview() -> None:
    """Quick numeric preview of the CHM."""
    import numpy as np
    import rasterio

    with rasterio.open(CHM_OUT) as src:
        chm = src.read(1)
        chm = np.where(chm == src.nodata, np.nan, chm)
        print(f"\nCHM preview ({CHM_OUT}):")
        print(f"  shape:     {chm.shape}  ({src.width}×{src.height} pixels @ {RES}m)")
        print(f"  min/max:   {np.nanmin(chm):.1f}m / {np.nanmax(chm):.1f}m")
        print(f"  mean:      {np.nanmean(chm):.1f}m")
        print(f"  % > 5m:    {100 * np.nanmean(chm > 5):.1f}%  (canopy cover)")
        print(f"  % nodata:  {100 * np.mean(np.isnan(chm)):.1f}%")


if __name__ == "__main__":
    Path("data").mkdir(exist_ok=True)
    build_dem()
    build_chm()
    preview()
    print("\nDone. Open chm.tif in QGIS to see the forest from above.")
