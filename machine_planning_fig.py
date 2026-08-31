"""Figure for machine_planning: wetness raster + the two constraint classes."""
from pathlib import Path
import geopandas as gpd, numpy as np, pandas as pd, rasterio
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap

ROOT = Path(__file__).parent
df = pd.read_csv(ROOT/"data"/"machine_planning.csv")
st = gpd.read_file(ROOT/"data"/"stands_joined.gpkg", layer="stands")
with rasterio.open(ROOT/"data"/"machine_planning_twi.tif") as s:
    twi = s.read(1); ext = [s.bounds.left, s.bounds.right, s.bounds.bottom, s.bounds.top]
    crs = s.crs
st = st.to_crs(crs).merge(df[["standid","season","access","wet_frac","steep_frac"]],
                          on="standid", how="left")
sched = st[(st.devclass=="04") & (st.op_cut==1) & st.season.notna()]

fig, ax = plt.subplots(1, 2, figsize=(15, 7.6))

ax[0].imshow(np.clip(twi, 2, 14), extent=ext, cmap="YlGnBu", origin="upper")
sched.boundary.plot(ax=ax[0], color="0.25", linewidth=0.25)
wet = sched[sched.season != "summer-trafficable"]
wet.plot(ax=ax[0], facecolor="#d62728", edgecolor="k", linewidth=0.4, alpha=0.85)
ax[0].set_title(f"Wetness (TWI) — {len(wet)} scheduled stands need seasonal timing",
                fontsize=11)

steep = sched[sched.access != "conventional"]
sched.plot(ax=ax[1], facecolor="#eeeeee", edgecolor="0.7", linewidth=0.25)
steep.plot(ax=ax[1], column="steep_frac", cmap="OrRd", vmin=0, vmax=0.9,
           edgecolor="k", linewidth=0.3, legend=True,
           legend_kwds={"label":"fraction of stand on steep ground","shrink":0.6})
ax[1].set_title(f"Slope — {len(steep)} scheduled stands need access review", fontsize=11)

for a in ax:
    a.set_xticks([]); a.set_yticks([])
    a.set_xlim(ext[0], ext[1]); a.set_ylim(ext[2], ext[3])
fig.suptitle("Sheet L4132D — machine planning for 653 stands already scheduled for cutting",
             fontsize=13)
fig.text(0.5, 0.02,
         "Terrain from National Land Survey of Finland 1 m DTM (CC BY 4.0). "
         "Thresholds are percentiles of this sheet, not absolute bearing-capacity limits.",
         ha="center", fontsize=8, color="0.35")
fig.tight_layout(rect=[0,0.04,1,0.96])
out = ROOT/"data"/"machine_planning.png"
fig.savefig(out, dpi=125)
print("wrote", out)
