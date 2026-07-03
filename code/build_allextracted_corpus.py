#!/usr/bin/env python3
"""Rebuild the dedup input as the FULL EXTRACTED corpus (old + new), replacing the prior
gold-old+new mix. Old records are tagged _corpus='old_extracted' and each individual appointee
gets _gold_canonical attached (matched to the human gold by MDL+name) so the gold-gate still works.
Writes order_extractions_unified.jsonl."""
import csv, json, re, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def nmdl(x): return re.sub(r"^0+(\d)", r"\1", str(x or "").strip())
def nkey(fn, ln): return (re.sub(r"[^a-z]","",str(fn or "").lower()), re.sub(r"[^a-z]","",str(ln or "").lower()))
old = set()
for r in csv.DictReader(open(os.path.join(ROOT,"MDL_merged.csv"),encoding="utf-8-sig")):
    if (r.get("Source_Table") or "").strip() in ("old","both"): old.add(nmdl(r.get("MDL_NO")))
# gold canonical by (mdl, namekey)
gold = {}
for r in csv.DictReader(open(os.path.join(ROOT,"csvs_current_dataset","Appointments-Grid view.csv"),encoding="utf-8-sig")):
    gc = (r.get("Canonical_Name (from Attorney)") or "").strip()
    if gc: gold[(nmdl(r.get("MDL_No (from Orders)")), nkey(r.get("First Name"), r.get("Last Name")))] = gc
out = open(os.path.join(ROOT,"order_extractions_unified.jsonl"),"w",encoding="utf-8")
n=nold=lab=0
for line in open(os.path.join(ROOT,"order_extractions.jsonl"),encoding="utf-8"):
    if not line.strip(): continue
    rec=json.loads(line)
    mdl=nmdl((re.match(r"^(\d+)",rec.get("Source_File","")) or [None,""])[0])
    is_old = mdl in old
    rec["_corpus"] = "old_extracted" if is_old else "new_extracted"
    if is_old:
        nold+=1
        for a in rec.get("Appointments") or []:
            gc = gold.get((mdl, nkey(a.get("first_name"), a.get("last_name"))))
            if gc: a["_gold_canonical"]=gc; lab+=1
    out.write(json.dumps(rec,ensure_ascii=False)+"\n"); n+=1
out.close()
print(f"wrote order_extractions_unified.jsonl: {n} records ({nold} old_extracted) | gold labels attached to {lab} old appointees")
