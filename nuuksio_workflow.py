"""
Full Nuuksio workflow:
  1. Build bare-earth DEM (ground points, mean per cell) via PDAL
  2. Build canopy height model (height above ground, max per cell) via PDAL
  3. Visualize DEM + CHM + ground-truth trees

Outputs:
  data/nuuksio_dem.tif       - bare-earth DEM
  data/nuuksio_chm.tif       - canopy height model
  data/nuuksio_overview.png  - 3-panel visualization
"""
import json
from pathlib import Path
import numpy as np
import pdal
import rasterio
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource

INPUT = "data/nuuksio_sample.laz"
TRUTH = "data/nuuksio_tree_truth.csv"
DEM_OUT = "data/nuuksio_dem.tif"
CHM_OUT = "data/nuuksio_chm.tif"
FIG_OUT = "data/nuuksio_overview.png"
RES = 1.0  # meters per pixel


def build_dem():
    print(f"Building DEM → {DEM_OUT}")
    p = {
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
    n = pdal.Pipeline(json.dumps(p)).execute()
    print(f"  {n:,} ground points binned")


def build_chm():
    print(f"Building CHM → {CHM_OUT}")
    p = {
        "pipeline": [
            {"type": "readers.las", "filename": INPUT},
            # Height above ground, using nearest ground neighbors
            {"type": "filters.hag_nn", "count": 3},
            # Drop noise (birds, negative artifacts) and water surface (~0)
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
    n = pdal.Pipeline(json.dumps(p)).execute()
    print(f"  {n:,} points processed")


def load_raster(path):
    with rasterio.open(path) as src:
        arr = src.read(1)
        arr = np.where(arr == src.nodata, np.nan, arr)
        # rasterio arrays are top-left origin; extent for matplotlib:
        b = src.bounds
        return arr, [b.left, b.right, b.bottom, b.top]


def visualize():
    print("Rendering visualization...")
    dem, extent = load_raster(DEM_OUT)
    chm, _ = load_raster(CHM_OUT)
    truth = pd.read_csv(TRUTH)

    # rasterio reads top-to-bottom; flip for matplotlib origin='lower'
    dem_disp = np.flipud(dem)
    chm_disp = np.flipud(chm)

    fig, axes = plt.subplots(1, 3, figsize=(19, 6))

    # DEM with hillshade
    ls = LightSource(azdeg=315, altdeg=45)
    dem_fill = np.where(np.isnan(dem_disp), np.nanmean(dem_disp), dem_disp)
    hs = ls.hillshade(dem_fill, vert_exag=3)
    im0 = axes[0].imshow(dem_disp, cmap='terrain', extent=extent, origin='lower')
    axes[0].imshow(hs, cmap='gray', alpha=0.4, extent=extent, origin='lower')
    axes[0].set_title('Bare-earth DEM (m)\n(ridge + lake basin visible)')
    plt.colorbar(im0, ax=axes[0], shrink=0.75, label='Elevation (m)')

    # CHM
    im1 = axes[1].imshow(chm_disp, cmap='YlGn', extent=extent, origin='lower',
                          vmin=0, vmax=40)
    axes[1].set_title('Canopy Height Model (m)\n(each green blob = a tree)')
    plt.colorbar(im1, ax=axes[1], shrink=0.75, label='Height above ground (m)')

    # CHM + tree truth
    axes[2].imshow(chm_disp, cmap='YlGn', extent=extent, origin='lower',
                   vmin=0, vmax=40, alpha=0.7)
    colors = {'pine': '#ff8c00', 'spruce': '#8b0000', 'birch': '#ffd700'}
    for sp, c in colors.items():
        m = truth['species'] == sp
        axes[2].scatter(truth.loc[m, 'x_tm35fin'], truth.loc[m, 'y_tm35fin'],
                        c=c, s=8, label=f'{sp} ({m.sum()})',
                        edgecolor='black', linewidth=0.3)
    axes[2].set_title(f'CHM + Ground Truth\n({len(truth)} trees)')
    axes[2].legend(loc='lower right', fontsize=8, framealpha=0.9)
    axes[2].set_xlim(extent[0], extent[1])
    axes[2].set_ylim(extent[2], extent[3])

    for ax in axes:
        ax.set_xlabel('Easting (m, TM35FIN)')
        ax.set_ylabel('Northing (m, TM35FIN)')

    plt.suptitle('Nuuksio — Haukkalampi area', fontsize=13, y=1.02)
    plt.tight_layout()
    plt.savefig(FIG_OUT, dpi=110, bbox_inches='tight')
    print(f"Saved {FIG_OUT}")

    # Also print quick CHM stats
    print("\nCHM stats:")
    print(f"  mean:   {np.nanmean(chm):.1f}m")
    print(f"  max:    {np.nanmax(chm):.1f}m")
    print(f"  % >5m:  {100 * np.nanmean(chm > 5):.1f}%  (canopy cover)")

    plt.show()


if __name__ == "__main__":
    if not Path(INPUT).exists():
        raise SystemExit(f"Missing {INPUT}")
    if not Path(TRUTH).exists():
        raise SystemExit(f"Missing {TRUTH}")

    build_dem()
    build_chm()
    visualize()
