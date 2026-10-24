#!/usr/bin/env python3
"""
Within-practice-area Monte Carlo: the capacity-constrained random benchmark
(identical stub-matching null to the pooled simulation in
replication_mdl/code/analysis_ours.ipynb, Figure 11), run SEPARATELY inside each
practice area (MDL TYPE from the master list). Reassignment is confined to MDLs
of the same practice area, so the null additionally conditions on specialization.

Statistic (same as pooled): additional co-appointments = sum over unordered
attorney pairs of max(shared MDLs - 1, 0).

Usage:  python3 code/mc_within_type.py [--scope both|old|new] [--draws 1000]
Reads:  replication_mdl/datasets_ours/{appointments,attorneys,mdls}.csv
"""
import argparse
import os
import re
from collections import Counter
from itertools import combinations

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "replication_mdl", "datasets_ours")
PELVIC = [2187, 2325, 2326, 2327, 2387, 2440]   # consolidated to one proceeding, as in the notebook
DRAWS_DEFAULT = 1000
MIN_TYPE_MDLS = 2


def build_edges(scope):
    """Distinct (attorney_id, mdl_no) edges — identical filters to analysis_ours.ipynb."""
    ap = pd.read_csv(os.path.join(DATA, "appointments.csv"), low_memory=False)
    if scope != "both":
        ap = ap[ap["Corpus"].astype(str).str.lower().eq(scope)]
    ap["mdl_no"] = pd.to_numeric(ap["MDL_No"], errors="coerce").astype("Int64").replace(PELVIC, 9999)
    aps = ap["Appoint"].astype(str).str.lower()
    ap = ap[aps.isin(["true", "checked"]) & ap["mdl_no"].notna()]
    ax = ap[ap["Appointee Type"].astype(str).str.strip().eq("Individual")
            & ap["Plaintiff/Defendant"].astype(str).str.strip().str.lower().eq("plaintiff")
            & ap["Unified_Attorney_ID"].notna()
            & ap["Unified_Attorney_ID"].astype(str).ne("")].copy()
    ax["attorney_id"] = ax["Unified_Attorney_ID"].astype(str)
    return ax[["attorney_id", "mdl_no"]].drop_duplicates()


def mdl_types():
    m = pd.read_csv(os.path.join(DATA, "mdls.csv"), low_memory=False)
    m["mdl_no"] = m["MDL_NO"].astype(str).str.extract(r"^(\d+)")[0]
    fix = {"Miscellanous": "Miscellaneous"}   # master-list spelling variant
    t = {}
    for k, v in zip(m["mdl_no"].astype(float).astype(int), m["TYPE"]):
        v = "" if pd.isna(v) else str(v).strip()
        v = fix.get(v, v)
        t[int(k)] = v if v and v.lower() != "nan" else "Unknown"
    t[9999] = "Products Liability"   # the consolidated pelvic-mesh proceedings
    return t


def additional_coappt(slates):
    pc = Counter()
    for atts in slates:
        for a, b in combinations(sorted(set(atts)), 2):
            pc[(a, b)] += 1
    return sum(max(c - 1, 0) for c in pc.values())


def run_mc(edges, draws, seed0):
    """Stub-matching null on one pool of edges; returns (observed, null mean, null sd, p)."""
    slates = edges.groupby("mdl_no")["attorney_id"].apply(list)
    observed = additional_coappt(slates.values)
    cap = edges.groupby("attorney_id")["mdl_no"].nunique()
    sizes = slates.apply(len).values
    stubs_master = np.repeat(np.asarray(cap.index.values, dtype=object), cap.values)
    sims = np.empty(draws)
    for i in range(draws):
        rng = np.random.default_rng(seed0 + i)
        stubs = stubs_master.copy()
        rng.shuffle(stubs)
        out, idx = [], 0
        for n in sizes:
            out.append(stubs[idx:idx + n]); idx += n
        sims[i] = additional_coappt(out)
    p = (np.sum(sims >= observed) + 1) / (draws + 1)
    return observed, sims.mean(), sims.std(), p


def main():
    apn = argparse.ArgumentParser()
    apn.add_argument("--scope", default="both", choices=["both", "old", "new"])
    apn.add_argument("--draws", type=int, default=DRAWS_DEFAULT)
    a = apn.parse_args()

    edges = build_edges(a.scope)
    tmap = mdl_types()
    edges["type"] = edges["mdl_no"].astype(int).map(tmap).fillna("Unknown")
    print(f"scope={a.scope}: {len(edges):,} attorney-MDL edges, "
          f"{edges['mdl_no'].nunique()} MDLs, {edges['attorney_id'].nunique():,} attorneys\n")

    obs_p, mean_p, sd_p, pv_p = run_mc(edges, a.draws, seed0=10_000)
    print(f"POOLED (re-verification): observed {obs_p:,.0f} | null mean {mean_p:,.0f} "
          f"(sd {sd_p:,.0f}) | x{obs_p/mean_p:.2f} | p={pv_p:.4f}\n")

    rows, tot_obs, tot_null = [], 0.0, 0.0
    for typ, g in sorted(edges.groupby("type"), key=lambda kv: -len(kv[1])):
        if g["mdl_no"].nunique() < MIN_TYPE_MDLS:
            continue
        obs, mu, sd, pv = run_mc(g, a.draws, seed0=20_000)
        tot_obs += obs; tot_null += mu
        rows.append({"practice_area": typ, "mdls": g["mdl_no"].nunique(),
                     "attorneys": g["attorney_id"].nunique(), "observed": obs,
                     "null_mean": round(mu, 1), "null_sd": round(sd, 1),
                     "multiplier": round(obs / mu, 2) if mu > 0 else float("nan"),
                     "p_value": round(pv, 4)})
    out = pd.DataFrame(rows)
    print(out.to_string(index=False))
    print(f"\nWITHIN-AREA AGGREGATE: observed {tot_obs:,.0f} | null {tot_null:,.0f} "
          f"| x{tot_obs/tot_null:.2f}")
    dest = os.path.join(ROOT, f"mc_within_type_{a.scope}.csv")
    out.to_csv(dest, index=False)
    print(f"written: {dest}")


if __name__ == "__main__":
    main()
