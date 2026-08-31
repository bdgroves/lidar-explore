"""Figure + disagreement analysis for wa_fpa."""
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).parent
# aggregate to APPLICATION level: the flag is set per application, so scoring
# individual harvest units would pseudo-replicate multi-unit applications.
units = pd.read_csv(ROOT/"data"/"wa_fpa"/"fpa_slope.csv")
df = (units.groupby("FP_ID")
            .agg(flag=("flag","first"), acres=("acres","sum"),
                 slope_mean=("slope_mean","mean"), slope_max=("slope_max","max"),
                 classification=("classification","first"))
            .reset_index())
y = (df.flag == "Y").values
s = df.slope_max.values

# ROC by sweeping the threshold
th = np.linspace(0, 70, 400)
tpr = [(s[y] >= t).mean() for t in th]
fpr = [(s[~y] >= t).mean() for t in th]
r = pd.Series(s).rank().values
auc = (r[y].sum() - y.sum()*(y.sum()+1)/2) / (y.sum()*(~y).sum())

# operating point: threshold maximising (tpr - fpr)
j = int(np.argmax(np.array(tpr) - np.array(fpr)))
t_star = th[j]
pred = s >= t_star
acc = (pred == y).mean()

fig, ax = plt.subplots(1, 3, figsize=(16, 5))

bins = np.linspace(0, 75, 45)
ax[0].hist(s[~y], bins=bins, alpha=.65, label="not flagged", color="#4c78a8", density=True)
ax[0].hist(s[y],  bins=bins, alpha=.65, label="flagged unstable", color="#d62728", density=True)
ax[0].axvline(t_star, color="k", ls="--", lw=1.2, label=f"best split {t_star:.0f}°")
ax[0].set_xlabel("max slope in application (deg, 10 m DEM)")
ax[0].set_ylabel("density"); ax[0].legend(fontsize=8)
ax[0].set_title("Slope separates the two groups")

ax[1].plot(fpr, tpr, color="#d62728", lw=2)
ax[1].plot([0,1],[0,1],"k--",lw=1)
ax[1].set_xlabel("false positive rate"); ax[1].set_ylabel("true positive rate")
ax[1].set_title(f"ROC — AUC {auc:.3f}  (base rate {y.mean()*100:.1f}%)")

# where slope and DNR disagree
fp = df[(~y) & pred]; fn = df[y & (~pred)]
cats = ["agree: flat & not flagged", "agree: steep & flagged",
        "steep but NOT flagged", "flagged but NOT steep"]
vals = [int(((~y)&(~pred)).sum()), int((y&pred).sum()), len(fp), len(fn)]
cols = ["#9ecae1","#fc9272","#08519c","#a50f15"]
ax[2].barh(cats, vals, color=cols)
for i,v in enumerate(vals):
    ax[2].text(v+8, i, str(v), va="center", fontsize=9)
ax[2].set_xlabel("applications"); ax[2].set_title(f"Agreement at {t_star:.0f}° — {acc*100:.0f}% overall")
ax[2].invert_yaxis()

fig.suptitle("Does terrain slope predict DNR's unstable-slope flag? "
             "1,024 active harvest applications, SW Washington", fontsize=13)
fig.text(.5,.015,"Harvest units: WA DNR Forest Practices Applications (public). "
                 "Terrain: USGS 3DEP 1/3 arc-second. Slope is a proxy for the rule, not the rule.",
         ha="center", fontsize=8, color="0.35")
fig.tight_layout(rect=[0,.04,1,.94])
fig.savefig(ROOT/"data"/"wa_fpa"/"wa_fpa.png", dpi=125)

print(f"AUC {auc:.3f}   best split {t_star:.1f} deg   accuracy {acc*100:.1f}%")
print(f"\nsteep but NOT flagged: {len(fp)}")
print(fp[["FP_ID","acres","slope_mean","slope_max","classification"]].head(6).to_string(index=False))
print(f"\nflagged but NOT steep: {len(fn)}")
print(fn[["FP_ID","acres","slope_mean","slope_max","classification"]].head(6).to_string(index=False))
print("\nclassification within disagreements:")
print("  steep-not-flagged:", fp.classification.value_counts().to_dict())
print("  flagged-not-steep:", fn.classification.value_counts().to_dict())
