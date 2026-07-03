#!/usr/bin/env python3
"""Build a UNIFIED mention corpus for cross-corpus attorney/firm dedup:
  - MDL_old half  : the human GOLD appointments (csvs_current_dataset/Appointments-Grid view.csv),
                    converted into the extraction jsonl schema.
  - MDL_new half  : our extraction (order_extractions.jsonl), EXCLUDING any MDL already in gold
                    (so the lone overlap MDL 2357 is not double-counted).
Writes order_extractions_unified.jsonl. Each record tagged _corpus = 'old_gold' | 'new_extracted'.
"""
import os, csv, json, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLD = os.path.join(ROOT, "csvs_current_dataset", "Appointments-Grid view.csv")
NEW = os.path.join(ROOT, "order_extractions.jsonl")
OUT = os.path.join(ROOT, "order_extractions_unified.jsonl")


def split_roles(s):
    return [t.strip() for t in re.split(r"[;,]", s or "") if t.strip()]


# ---- 1. gold (old) -> records grouped by order ----
gold_rows = []
with open(GOLD, encoding="utf-8-sig", newline="") as f:
    for r in csv.DictReader(f):
        gold_rows.append(r)

gold_mdls = set()
orders = {}   # (mdl, order_no) -> record
for r in gold_rows:
    mdl = (r.get("MDL_No (from Orders)") or "").strip()
    if not mdl:
        continue
    gold_mdls.add(mdl)
    ono = (r.get("Order No.") or r.get("Orders") or "").strip()
    fn = (r.get("First Name") or "").strip()
    ln = (r.get("Last Name") or "").strip()
    firm = (r.get("Firm") or "").strip()
    full = (r.get("First_Last_Calculated") or "").strip() or f"{fn} {ln}".strip()
    atype = (r.get("Appointee Type") or "").strip()
    # firm-only row (no individual name) -> mark Firm so load_mentions routes it to the firm pool
    if not (fn or ln) and firm and not atype:
        atype = "Firm"
    appt = {
        "first_name": fn, "last_name": ln, "full_name": full, "firm": firm,
        "appointee_type": atype, "plaintiff_defendant": (r.get("Plaintiff/Defendant") or "").strip(),
        "appointment_types": split_roles(r.get("Appointment Types", "")),
        "appoint": (r.get("Appoint") or "").strip().lower() in ("checked", "true", "1", "yes"),
        "remove": (r.get("Remove") or "").strip().lower() in ("checked", "true", "1", "yes"),
        "interim": (r.get("Interim") or "").strip().lower() in ("checked", "true", "1", "yes"),
        "_gold_canonical": (r.get("Canonical_Name (from Attorney)") or "").strip(),  # for later validation
    }
    key = (mdl, ono)
    rec = orders.setdefault(key, {"MDL_No": mdl, "Order_No": ono,
                                  "Source_File": f"{mdl} GOLD/{ono}", "_corpus": "old_gold",
                                  "Appointments": []})
    rec["Appointments"].append(appt)

# ---- 2. new (extraction), excluding MDLs already covered by gold ----
def mdl_of(rec):
    return str(rec.get("MDL_No") or (re.match(r"^(\d{2,5})\b", rec.get("Source_File", "")) or [None, ""])[0] or "")

n_new = n_new_skipped = 0
new_recs = []
for line in open(NEW, encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    rec = json.loads(line)
    if mdl_of(rec) in gold_mdls:
        n_new_skipped += 1
        continue
    rec["_corpus"] = "new_extracted"
    new_recs.append(rec)
    n_new += 1

# ---- 3. write combined ----
with open(OUT, "w", encoding="utf-8") as f:
    for rec in orders.values():
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    for rec in new_recs:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

gold_appt = sum(len(r["Appointments"]) for r in orders.values())
print(f"GOLD (old): {len(gold_mdls)} MDLs | {len(orders)} orders | {gold_appt} appointee rows")
print(f"NEW (extracted, MDLs not in gold): {n_new} orders kept | {n_new_skipped} records skipped (MDL in gold)")
print(f"new-extraction MDLs skipped because already in gold: "
      f"{sorted({mdl_of(json.loads(l)) for l in open(NEW, encoding='utf-8') if l.strip()} & gold_mdls)}")
print(f"wrote {os.path.relpath(OUT, ROOT)}: {len(orders) + n_new} total records")
