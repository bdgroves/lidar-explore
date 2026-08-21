"""
Synthetic LiDAR point cloud modeled on Nuuksio National Park, Finland.

Location: Haukkalampi area, ~30km NW of Helsinki
CRS: ETRS89 / TM35FIN (EPSG:3067) — Finland's national grid
Extent: 400m x 400m

Features (simulates what a real MML "Laser scanning data, 5 p" tile looks like):
  - Rolling terrain with a rocky ridge (Nuuksio is famous for these)
  - Lake basin in the NW quadrant (Haukkalampi)
  - Mixed boreal forest — Scots pine, Norway spruce, silver birch
    each with species-specific crown shapes
  - Ground vegetation layer (blueberry/lingonberry, class 3)
  - A handful of dead standing snags (broken-top trees)
  - High-altitude noise points (class 7) — birds/atmospheric
  - Water class (9) with sparse returns (LiDAR mostly absorbed by water)
  - Sparser tree density on the rocky ridge

Outputs:
  nuuksio_sample.laz          - the point cloud
  nuuksio_tree_truth.csv      - ground truth: tree positions, species, heights
"""
import csv
from pathlib import Path
import numpy as np
import laspy
from pyproj import CRS

rng = np.random.default_rng(1917)  # Finland's independence year, why not

# ------------------------------------------------------------------------
# Location — Nuuksio, Haukkalampi area in ETRS-TM35FIN
# ------------------------------------------------------------------------
ORIGIN_X = 365200.0   # TM35FIN easting
ORIGIN_Y = 6689400.0  # TM35FIN northing
SIZE_M = 400.0
LAKE_ELEV = 55.0      # Haukkalampi surface elevation


def terrain_z(x, y):
    """Rolling terrain with rocky ridge + lake basin in NW quadrant."""
    z = 78.0
    z += 12 * np.sin(x / 100) * np.cos(y / 120)
    # Rocky ridge running NW-SE
    ridge = np.exp(-((x - y * 0.7 - 100) / 60) ** 2)
    z += 10 * ridge
    # Micro-terrain (rocky texture)
    z += 1.5 * np.sin(x / 8) * np.cos(y / 7)
    # Lake basin — depression in NW
    dist_to_lake = np.hypot(x - 100, y - 320)
    z -= 22 * np.exp(-(dist_to_lake / 80) ** 2)
    return z


def is_water(x, y):
    return np.hypot(x - 100, y - 320) < 55


def ridge_intensity(x, y):
    """0-1, higher on the rocky ridge (fewer trees there)."""
    return np.exp(-((x - y * 0.7 - 100) / 55) ** 2)


# ------------------------------------------------------------------------
# Ground + water (class 2 / 9)
# ------------------------------------------------------------------------
n_ground = int(SIZE_M * SIZE_M * 4.5)   # ~4.5 pts/m^2 baseline
gx = rng.uniform(0, SIZE_M, n_ground)
gy = rng.uniform(0, SIZE_M, n_ground)

water = is_water(gx, gy)
# Water absorbs most LiDAR — keep only ~15% of returns over water
keep = ~water | (rng.uniform(0, 1, n_ground) < 0.15)
gx, gy, water = gx[keep], gy[keep], water[keep]

gz = np.where(water,
              LAKE_ELEV + rng.normal(0, 0.04, len(gx)),
              terrain_z(gx, gy) + rng.normal(0, 0.03, len(gx)))
gcls = np.where(water, 9, 2).astype(np.uint8)

# ------------------------------------------------------------------------
# Ground vegetation (class 3) — blueberry/lingonberry undergrowth
# ------------------------------------------------------------------------
n_low = int(SIZE_M * SIZE_M * 0.6)
lvx = rng.uniform(0, SIZE_M, n_low)
lvy = rng.uniform(0, SIZE_M, n_low)
mask = ~is_water(lvx, lvy)
lvx, lvy = lvx[mask], lvy[mask]
lvz = terrain_z(lvx, lvy) + rng.uniform(0.15, 1.0, len(lvx))

# ------------------------------------------------------------------------
# Trees — multi-species boreal
# ------------------------------------------------------------------------
# Realistic Finnish boreal density: 400-800 trees/ha for managed forest.
# We'll aim for ~450 trees over 16 ha = 28 trees/ha (mature stand, thinned).
TARGET_TREES = 450

# Oversample, then filter by water & ridge suitability
tx_c = rng.uniform(2, SIZE_M - 2, TARGET_TREES * 3)
ty_c = rng.uniform(2, SIZE_M - 2, TARGET_TREES * 3)
mask = ~is_water(tx_c, ty_c)
tx_c, ty_c = tx_c[mask], ty_c[mask]
# Ridge suitability — fewer trees on rocky ridge
keep_prob = 1.0 - 0.75 * ridge_intensity(tx_c, ty_c)
mask = rng.uniform(0, 1, len(tx_c)) < keep_prob
tx_c, ty_c = tx_c[mask], ty_c[mask]

tx = tx_c[:TARGET_TREES]
ty = ty_c[:TARGET_TREES]
N = len(tx)

# Species: pine 40%, spruce 40%, birch 20% (rough Nuuksio mix)
species = rng.choice(['pine', 'spruce', 'birch'], size=N, p=[0.40, 0.40, 0.20])

# Species-specific heights (meters), realistic Finnish ranges
heights = np.zeros(N)
for i, sp in enumerate(species):
    if sp == 'pine':
        heights[i] = np.clip(rng.gamma(5.5, 3.0) + 10, 12, 30)
    elif sp == 'spruce':
        heights[i] = np.clip(rng.gamma(7.0, 3.2) + 11, 15, 36)
    else:  # birch
        heights[i] = np.clip(rng.gamma(5.0, 2.8) + 12, 14, 28)


def crown_points(tx_i, ty_i, gz_i, h, sp):
    """Generate points for one tree crown with species-specific shape."""
    if sp == 'pine':
        # Pine: tall bare trunk, small round crown at top
        crown_start, max_r, ppm = 0.60, h * 0.10, 14
        n = int(h * ppm)
        hf = rng.beta(3, 1.5, n)  # bias high in crown
        h_abs = crown_start * h + hf * (1 - crown_start) * h
        frac_up = (h_abs - crown_start * h) / ((1 - crown_start) * h)
        r_max = max_r * np.sqrt(np.clip(1 - (2 * frac_up - 1) ** 2, 0.05, 1))
    elif sp == 'spruce':
        # Spruce: tight cone from near ground to peak
        crown_start, max_r, ppm = 0.18, h * 0.13, 28
        n = int(h * ppm)
        hf = rng.beta(1.6, 2.0, n)  # bias lower in crown
        h_abs = crown_start * h + hf * (1 - crown_start) * h
        frac_up = (h_abs - crown_start * h) / ((1 - crown_start) * h)
        r_max = max_r * (1 - frac_up) ** 0.6
    else:  # birch
        # Birch: wide rounded crown
        crown_start, max_r, ppm = 0.45, h * 0.22, 18
        n = int(h * ppm)
        hf = rng.beta(2.5, 2.0, n)
        h_abs = crown_start * h + hf * (1 - crown_start) * h
        frac_up = (h_abs - crown_start * h) / ((1 - crown_start) * h)
        r_max = max_r * np.sqrt(np.clip(1 - (2 * frac_up - 1) ** 2, 0.05, 1))

    r = np.clip(r_max, 0.05, None) * np.sqrt(rng.uniform(0, 1, n))
    theta = rng.uniform(0, 2 * np.pi, n)
    px = tx_i + r * np.cos(theta)
    py = ty_i + r * np.sin(theta)
    pz = gz_i + h_abs + rng.normal(0, 0.15, n)
    return px, py, pz


tree_gz = terrain_z(tx, ty)
vx_parts, vy_parts, vz_parts = [], [], []
for i in range(N):
    px, py, pz = crown_points(tx[i], ty[i], tree_gz[i], heights[i], species[i])
    vx_parts.append(px)
    vy_parts.append(py)
    vz_parts.append(pz)
vx = np.concatenate(vx_parts)
vy = np.concatenate(vy_parts)
vz = np.concatenate(vz_parts)

# ------------------------------------------------------------------------
# Dead standing snags — broken-top trees, sparser returns
# ------------------------------------------------------------------------
n_snags = 12
sx = rng.uniform(20, SIZE_M - 20, n_snags)
sy = rng.uniform(20, SIZE_M - 20, n_snags)
sh = rng.uniform(5, 14, n_snags)
snag_parts_x, snag_parts_y, snag_parts_z = [], [], []
for i in range(n_snags):
    gz_i = terrain_z(np.array([sx[i]]), np.array([sy[i]]))[0]
    n = int(sh[i] * 4)
    h_abs = rng.uniform(0.5, sh[i], n)
    r = 0.25 * rng.uniform(0, 1, n)
    theta = rng.uniform(0, 2 * np.pi, n)
    snag_parts_x.append(sx[i] + r * np.cos(theta))
    snag_parts_y.append(sy[i] + r * np.sin(theta))
    snag_parts_z.append(gz_i + h_abs)
snag_x = np.concatenate(snag_parts_x)
snag_y = np.concatenate(snag_parts_y)
snag_z = np.concatenate(snag_parts_z)

# ------------------------------------------------------------------------
# Noise (class 7) — birds, atmospheric hits
# ------------------------------------------------------------------------
n_noise = 25
nx = rng.uniform(0, SIZE_M, n_noise)
ny = rng.uniform(0, SIZE_M, n_noise)
nz = terrain_z(nx, ny) + rng.uniform(80, 220, n_noise)

# ------------------------------------------------------------------------
# Assemble
# ------------------------------------------------------------------------
all_x = np.concatenate([gx, lvx, vx, snag_x, nx]) + ORIGIN_X
all_y = np.concatenate([gy, lvy, vy, snag_y, ny]) + ORIGIN_Y
all_z = np.concatenate([gz, lvz, vz, snag_z, nz])
cls = np.concatenate([
    gcls,
    np.full(len(lvx), 3, dtype=np.uint8),
    np.full(len(vx), 5, dtype=np.uint8),
    np.full(len(snag_x), 5, dtype=np.uint8),
    np.full(len(nx), 7, dtype=np.uint8),
])

# Shuffle for realism
order = rng.permutation(len(all_x))
all_x, all_y, all_z, cls = all_x[order], all_y[order], all_z[order], cls[order]

# Intensity — varies plausibly by class
intensity = np.zeros(len(cls), dtype=np.uint16)
intensity[cls == 2] = rng.integers(10000, 26000, size=(cls == 2).sum())
intensity[cls == 9] = rng.integers(400, 3000, size=(cls == 9).sum())
intensity[cls == 3] = rng.integers(5000, 15000, size=(cls == 3).sum())
intensity[cls == 5] = rng.integers(3000, 18000, size=(cls == 5).sum())
intensity[cls == 7] = rng.integers(1000, 5000, size=(cls == 7).sum())

# ------------------------------------------------------------------------
# Write LAZ
# ------------------------------------------------------------------------
header = laspy.LasHeader(point_format=6, version="1.4")
header.add_crs(CRS.from_epsg(3067))  # ETRS89 / TM35FIN
header.offsets = np.array([ORIGIN_X, ORIGIN_Y, 50.0])
header.scales = np.array([0.001, 0.001, 0.001])

las = laspy.LasData(header)
las.x = all_x
las.y = all_y
las.z = all_z
las.classification = cls
las.intensity = intensity

out = Path("/home/claude/nuuksio_sample.laz")
las.write(out)

# ------------------------------------------------------------------------
# Ground truth CSV
# ------------------------------------------------------------------------
truth_path = Path("/home/claude/nuuksio_tree_truth.csv")
with open(truth_path, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["x_tm35fin", "y_tm35fin", "ground_z", "height_m", "top_z", "species"])
    for i in range(N):
        w.writerow([
            f"{tx[i] + ORIGIN_X:.3f}",
            f"{ty[i] + ORIGIN_Y:.3f}",
            f"{tree_gz[i]:.2f}",
            f"{heights[i]:.2f}",
            f"{tree_gz[i] + heights[i]:.2f}",
            species[i],
        ])

# ------------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------------
size_mb = out.stat().st_size / (1024 * 1024)
print(f"Wrote {out.name}  ({size_mb:.1f} MB)")
print(f"  Total points:  {len(all_x):,}")
for c, label in [(2, "ground"), (9, "water"), (3, "low veg"),
                 (5, "high veg + snags"), (7, "noise")]:
    n = (cls == c).sum()
    print(f"    class {c} ({label:<18}): {n:>9,}  ({100*n/len(all_x):4.1f}%)")

print(f"\nTree ground truth ({truth_path.name}): {N} trees")
for sp in ['pine', 'spruce', 'birch']:
    mask = species == sp
    if mask.any():
        h = heights[mask]
        print(f"  {sp:6}: {mask.sum():3d} trees, {h.min():.1f}-{h.max():.1f}m (mean {h.mean():.1f}m)")
