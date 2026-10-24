#!/usr/bin/env python3
"""
Entry-rate baseline (null) for the paper's entry figure: what share of MDL leadership
participants would be "new" each year under random assignment, absent any relational
or exclusionary structure?

Null (the same capacity-constrained stub-matching used for the co-appointment Monte
Carlo): hold fixed (i) the set of MDLs each year and each MDL's slate size, and
(ii) each attorney's total number of MDL participations; randomize which attorneys
fill which slates. For each randomized allocation we recompute both entry measures:

  - first-ever share: of the attorneys active in year t, the share whose first
    appearance is in year t;
  - rolling 3-year share: of the attorneys active in year t, the share with no
    appearance in t-1..t-3 (reported from the first year with a full lookback).

1,000 draws give a null mean curve and a 95% band. The null reproduces the
mechanical early-series decline (everyone is "new" at the start of the series), so
departures of the observed curve from the band are interpretable as non-random
entry structure, conditional on observed capacities and slate sizes.

Usage:  python3 code/mc_entry_baseline.py [--scope both|old|new] [--draws 1000]
Writes: replication_mdl/figures_ours/<scope>/fig14_entry_null.png + mc_entry_null_<scope>.csv
"""
import argparse
import os
from collections import defaultdict

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from mc_within_type import build_edges, DATA, ROOT   # same edge construction as the notebook

DRAWS_DEFAULT = 1000


def mdl_years():
    m = pd.read_csv(os.path.join(DATA, "mdls.csv"), low_memory=False)
    m["mdl_no"] = pd.to_numeric(m["MDL_NO"].astype(str).str.extract(r"^(\d+)")[0], errors="coerce")
    dt = pd.to_datetime(m["DATE_TRANSFERRED"], errors="coerce", format="mixed")
    df_ = pd.to_datetime(m["DATE_FILED"], errors="coerce", format="mixed")
    yr = dt.fillna(df_).dt.year
    out = {int(k): int(v) for k, v in zip(m["mdl_no"], yr) if pd.notna(k) and pd.notna(v)}
    out[9999] = min(out.get(p) for p in (2187, 2325, 2326, 2327, 2387, 2440) if out.get(p))
    return out


def entry_curves(att_years):
    """att_years: dict attorney -> set of active years. Returns (first_ever, rolling) Series."""
    active = defaultdict(set)          # year -> attorneys active that year
    for a, ys in att_years.items():
        for y in ys:
            active[y].add(a)
    years = sorted(active)
    first = {a: min(ys) for a, ys in att_years.items()}
    fe = {y: np.mean([first[a] == y for a in active[y]]) for y in years}
    y0 = years[0] + 3
    ro = {}
    for y in years:
        if y < y0:
            continue
        ro[y] = np.mean([not (att_years[a] & {y - 1, y - 2, y - 3}) for a in active[y]])
    return pd.Series(fe), pd.Series(ro)


def main():
    apn = argparse.ArgumentParser()
    apn.add_argument("--scope", default="both", choices=["both", "old", "new"])
    apn.add_argument("--draws", type=int, default=DRAWS_DEFAULT)
    a = apn.parse_args()

    edges = build_edges(a.scope)
    ym = mdl_years()
    edges = edges[edges["mdl_no"].astype(int).map(ym).notna()].copy()
    edges["year"] = edges["mdl_no"].astype(int).map(ym).astype(int)

    # observed
    obs_ay = defaultdict(set)
    for r in edges.itertuples():
        obs_ay[r.attorney_id].add(r.year)
    obs_fe, obs_ro = entry_curves(obs_ay)

    # null machinery: slates (per MDL) with their years; attorney capacities
    slates = edges.groupby("mdl_no").agg(n=("attorney_id", "nunique"), year=("year", "first"))
    cap = edges.groupby("attorney_id")["mdl_no"].nunique()
    stubs_master = np.repeat(np.asarray(cap.index.values, dtype=object), cap.values)
    sizes = slates["n"].values
    years_per_mdl = slates["year"].values

    fe_draws, ro_draws = [], []
    for i in range(a.draws):
        rng = np.random.default_rng(30_000 + i)
        stubs = stubs_master.copy()
        rng.shuffle(stubs)
        ay = defaultdict(set)
        idx = 0
        for n, y in zip(sizes, years_per_mdl):
            for att in stubs[idx:idx + n]:
                ay[att].add(y)
            idx += n
        fe, ro = entry_curves(ay)
        fe_draws.append(fe); ro_draws.append(ro)

    FE = pd.DataFrame(fe_draws); RO = pd.DataFrame(ro_draws)
    out = pd.DataFrame({
        "obs_first_ever": obs_fe, "null_first_ever_mean": FE.mean(),
        "null_first_ever_lo": FE.quantile(0.025), "null_first_ever_hi": FE.quantile(0.975),
        "obs_rolling3": obs_ro, "null_rolling3_mean": RO.mean(),
        "null_rolling3_lo": RO.quantile(0.025), "null_rolling3_hi": RO.quantile(0.975),
    }).sort_index()
    dest_csv = os.path.join(ROOT, f"mc_entry_null_{a.scope}.csv")
    out.to_csv(dest_csv, index_label="year")

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), sharey=True)
    for ax, (ocol, mcol, lo, hi, title) in zip(axes, [
            ("obs_first_ever", "null_first_ever_mean", "null_first_ever_lo", "null_first_ever_hi",
             "First-ever MDL appearance"),
            ("obs_rolling3", "null_rolling3_mean", "null_rolling3_lo", "null_rolling3_hi",
             "No appearance in prior 3 years")]):
        sub = out.dropna(subset=[ocol])
        ax.fill_between(sub.index, sub[lo], sub[hi], alpha=0.25, color="grey",
                        label="null 95% band (random assignment)")
        ax.plot(sub.index, sub[mcol], color="grey", lw=1.2, ls="--", label="null mean")
        ax.plot(sub.index, sub[ocol], color="blue" if "ever" in ocol else "red",
                marker="o", ms=3.5, lw=1.4, label="observed")
        ax.set_title(title); ax.set_xlabel("Year"); ax.grid(True, ls=":")
        ax.set_ylim(0, 1.05)
    axes[0].set_ylabel("Share of new MDL participants")
    axes[0].legend(frameon=True, fontsize=8)
    fig.suptitle(f"Entry into MDL leadership: observed vs. capacity-constrained random baseline  [{a.scope}]")
    fig.tight_layout()
    dest_png = os.path.join(ROOT, "replication_mdl", "figures_ours", a.scope, "fig14_entry_null.png")
    fig.savefig(dest_png, dpi=200)
    print(f"written: {dest_png}\n         {dest_csv}")
    tail = out.dropna(subset=["obs_rolling3"]).tail(8)
    print("\nlast years, rolling-3 (observed vs null mean):")
    print(tail[["obs_rolling3", "null_rolling3_mean", "null_rolling3_lo"]].round(3).to_string())


if __name__ == "__main__":
    main()
