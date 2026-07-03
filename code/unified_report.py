#!/usr/bin/env python3
"""Report on the UNIFIED cross-corpus roster: how many attorneys/firms are shared between
MDL_old (gold) and MDL_new (extracted), and the top shared entities."""
import os, csv, json, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLD = os.path.join(ROOT, "csvs_current_dataset", "Appointments-Grid view.csv")
NEW = os.path.join(ROOT, "order_extractions.jsonl")
ATT = os.path.join(ROOT, "canonical_attorneys_unified.csv")
FIRM = os.path.join(ROOT, "canonical_firms_unified.csv")


def load(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def nm(m):
    """normalize MDL id: strip zero-padding (02000 -> 2000), matching load_mentions."""
    return re.sub(r"^0+(\d)", r"\1", (m or "").strip())


# corpus MDL sets
gold_mdls = set()
for r in load(GOLD):
    m = nm(r.get("MDL_No (from Orders)") or "")
    if m:
        gold_mdls.add(m)
new_mdls = set()
for line in open(NEW, encoding="utf-8"):
    if line.strip():
        rec = json.loads(line)
        m = nm(str(rec.get("MDL_No") or (re.match(r"^(\d{2,5})\b", rec.get("Source_File", "")) or [None, ""])[0] or ""))
        if m:
            new_mdls.add(m)
new_only_mdls = new_mdls - gold_mdls
print(f"gold (old) MDLs: {len(gold_mdls)} | new MDLs: {len(new_mdls)} | new-not-in-gold: {len(new_only_mdls)}")


def classify(mdls_str):
    mdls = {nm(m) for m in (mdls_str or "").split(",") if m.strip()}
    in_old = bool(mdls & gold_mdls)
    in_new = bool(mdls & new_only_mdls)
    if in_old and in_new:
        return "both"
    if in_old:
        return "old_only"
    if in_new:
        return "new_only"
    return "unknown"


def report(path, namecol, label):
    rows = load(path)
    buckets = {"both": [], "old_only": [], "new_only": [], "unknown": []}
    for r in rows:
        buckets[classify(r.get("MDLs", r.get("MDLs", "")))].append(r)
    print(f"\n=== {label}: {len(rows):,} canonical ===")
    for k in ("both", "old_only", "new_only", "unknown"):
        print(f"   {k:9s}: {len(buckets[k]):,}")
    both = sorted(buckets["both"], key=lambda r: -int(r.get("N_MDLs") or 0))[:15]
    print(f"   --- top shared ({label}) across BOTH corpora ---")
    for r in both:
        print(f"     {r.get(namecol):42s} N_MDLs={r.get('N_MDLs'):>3}  MDLs={r.get('MDLs','')[:60]}")


# firms csv has no MDLs column? check
firm_rows = load(FIRM)
print("\nfirm columns:", list(firm_rows[0].keys()) if firm_rows else "(none)")
report(ATT, "Canonical_Name", "ATTORNEYS")
if firm_rows and "MDLs" in firm_rows[0]:
    report(FIRM, "Canonical_Firm", "FIRMS")
else:
    print("\n(note: canonical_firms_unified.csv has no MDLs column -> can't classify firms by corpus; "
          "showing top firms by N_MDLs instead)")
    top = sorted(firm_rows, key=lambda r: -int(r.get("N_MDLs") or 0))[:15]
    for r in top:
        print(f"   {r.get('Canonical_Firm'):46s} N_MDLs={r.get('N_MDLs'):>3} N_Mentions={r.get('N_Mentions')}")
