#!/usr/bin/env python3
"""
Paper-styled versions of the article's Figure 7 (entry) and Figure 8 (judges),
with the reviewer fixes applied:
  - Fig 7: rolling 3-year series starts at the first year with a full lookback
    (no hardcoded start year);
  - Fig 8: duplicate MDL-judge rows dropped before the merge (judge counts not
    inflated by the number of orders per MDL).

Same computations as replication_mdl/code/analysis_ours.ipynb (scope "both"),
rendered with the article's serif style and no scope tag in the title.

Usage:  python3 code/make_paper_figs.py
Writes: paper_figures/fig7_entry.png, paper_figures/fig8_judges.png
"""
import os
from collections import defaultdict

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from mc_within_type import build_edges, DATA, ROOT
from mc_entry_baseline import mdl_years, entry_curves

plt.rcParams.update({
    "font.family": "Times New Roman", "font.size": 11,
    "axes.labelsize": 12, "axes.titlesize": 13,
    "xtick.labelsize": 9, "ytick.labelsize": 10,
    "figure.dpi": 300, "axes.linewidth": 0.8, "axes.edgecolor": "black",
    "axes.spines.top": False, "axes.spines.right": False,
})

OUT = os.path.join(ROOT, "paper_figures")
os.makedirs(OUT, exist_ok=True)

edges = build_edges("both")

# ---------------- Figure 7: entry ----------------
ym = mdl_years()
e = edges[edges["mdl_no"].astype(int).map(ym).notna()].copy()
e["year"] = e["mdl_no"].astype(int).map(ym).astype(int)
ay = defaultdict(set)
for r in e.itertuples():
    ay[r.attorney_id].add(r.year)
fe, ro = entry_curves(ay)

plt.figure(figsize=(7.5, 4))
plt.plot(fe.index, fe.values, marker="o", color="blue", label="First-Ever MDL Appearance")
plt.plot(ro.index, ro.values, marker="o", color="red", label="No Appearance in Prior 3 Years")
plt.xlabel("Year"); plt.ylabel("Share of New MDL Participants")
plt.title("Entry into MDL: Naive vs Rolling 3-Year")
plt.ylim(0, 1.1); plt.grid(True, linestyle=":"); plt.legend(frameon=True)
plt.tight_layout(); plt.savefig(os.path.join(OUT, "fig7_entry.png")); plt.close()
print(f"fig7: first-ever {fe.index.min()}-{fe.index.max()}, rolling starts {ro.index.min()}")

# ---------------- Figure 8: judges ----------------
o = pd.read_csv(os.path.join(DATA, "orders.csv"), low_memory=False)
o["mdl_no"] = pd.to_numeric(o["MDL_No"], errors="coerce").astype("Int64")
o = o[["mdl_no", "Judge"]].dropna().rename(columns={"Judge": "judge"})
o["judge"] = o["judge"].astype(str).str.strip()
df = edges.merge(o.drop_duplicates(), on="mdl_no", how="left").dropna(subset=["judge", "attorney_id", "mdl_no"])
df = df[df["judge"].ne("") & df["judge"].str.lower().ne("nan")]
first = df.groupby("attorney_id")["mdl_no"].min().rename("first_mdl")
df = df.merge(first, on="attorney_id"); df["ft"] = (df["mdl_no"] == df["first_mdl"]).astype(int)
je = df.groupby("judge").agg(total=("attorney_id", "count"), ft=("ft", "sum")).reset_index()
je["share"] = je["ft"] / je["total"]; je = je[je["total"] >= 10]
print(f"fig8: qualifying judges (>=10 appointments): {len(je)}")

from matplotlib.ticker import MaxNLocator
plt.figure(figsize=(8, 4))
plt.hist(je["share"], bins=20, edgecolor="black")
plt.xlabel("Share of Leadership Slots Given to First-Time Leaders"); plt.ylabel("Number of Judges")
plt.title("Judges Vary in Openness to First-Time MDL Leaders")
plt.gca().yaxis.set_major_locator(MaxNLocator(integer=True))
plt.grid(True, linestyle=":"); plt.tight_layout()
plt.savefig(os.path.join(OUT, "fig8_judges.png")); plt.close()
print("written to", OUT)
