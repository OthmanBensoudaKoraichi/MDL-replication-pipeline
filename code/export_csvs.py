#!/usr/bin/env python3
"""Export every tab of unified_mdl_database.xlsx to replication_mdl/datasets_ours/ as CSV.

The figure notebook (replication_mdl/code/analysis_ours.ipynb) reads appointments, orders,
attorneys and mdls from here; the other tabs are exported so the full dataset is available
without Excel. Re-run after build_final_database.py.

Usage:  python3 code/export_csvs.py
"""
import csv
import os

import openpyxl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "unified_mdl_database.xlsx")
OUT = os.path.join(ROOT, "replication_mdl", "datasets_ours")

TABS = {
    "MDLs": "mdls",
    "Orders": "orders",
    "Appointments": "appointments",
    "Attorneys": "attorneys",
    "Firms": "firms",
    "Gold_Appointments": "gold_appointments",
    "Gold_Attorneys": "gold_attorneys",
    "Role_Comparison": "role_comparison",
}


def cell(v):
    # spreadsheet formulas carried over from the source MDL list have no cached value
    if v is None or (isinstance(v, str) and v.startswith("=")):
        return ""
    return v


wb = openpyxl.load_workbook(SRC, read_only=True)
os.makedirs(OUT, exist_ok=True)
for tab, name in TABS.items():
    path = os.path.join(OUT, f"{name}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        n = -1
        for row in wb[tab].iter_rows(values_only=True):
            w.writerow([cell(v) for v in row])
            n += 1
    print(f"{name}.csv  {n:,} rows")
