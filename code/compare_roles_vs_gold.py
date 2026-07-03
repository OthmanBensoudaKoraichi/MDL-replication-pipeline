#!/usr/bin/env python3
"""Full-gold role-agreement eval + per-appointment disagreement flag.

For the 201 old/gold MDLs we now have BOTH the human-coded appointments (gold) and a fresh LLM
extraction. This matches them at (MDL x attorney) and, for each, compares the set of appointment
TYPES (LeadCounsel / Management / ClassCounsel / ...). Outputs:
  - appointment_type_comparison.csv : one row per (MDL, attorney) with gold_roles, llm_roles, a
    disagreement FLAG, and the exact roles the LLM ADDED vs MISSED.
  - console: identity recall/precision + role exact-match rate + per-role confusion.
Match unit is (MDL, normalized attorney name); role vocab is identical on both sides.
"""
import csv, json, re, os
from collections import defaultdict, Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLD = os.path.join(ROOT, "csvs_current_dataset", "Appointments-Grid view.csv")
JSONL = os.path.join(ROOT, "order_extractions.jsonl")
OUT = os.path.join(ROOT, "appointment_type_comparison.csv")


def nm_mdl(x):
    return re.sub(r"^0+(\d)", r"\1", str(x or "").strip())


def nkey(fn, ln):
    return (re.sub(r"[^a-z]", "", str(fn or "").lower()), re.sub(r"[^a-z]", "", str(ln or "").lower()))


def split_roles(s):
    return {t.strip() for t in re.split(r"[;,]", str(s or "")) if t.strip() and t.strip().lower() != "nan"}


# old/gold MDL set
old_mdls = set()
for r in csv.DictReader(open(os.path.join(ROOT, "MDL_merged.csv"), encoding="utf-8-sig")):
    if (r.get("Source_Table") or "").strip() in ("old", "both"):
        old_mdls.add(nm_mdl(r.get("MDL_NO")))

# ---- gold: (mdl, namekey) -> {roles, display} ----
gold = defaultdict(lambda: {"roles": set(), "name": ""})
for r in csv.DictReader(open(GOLD, encoding="utf-8-sig")):
    fn, ln = r.get("First Name", ""), r.get("Last Name", "")
    if not (str(fn).strip() or str(ln).strip()):
        continue  # firm-only row
    if str(r.get("Appointee Type")).strip() == "Firm":
        continue
    mdl = nm_mdl(r.get("MDL_No (from Orders)"))
    k = (mdl, nkey(fn, ln))
    gold[k]["roles"] |= split_roles(r.get("Appointment Types"))
    gold[k]["name"] = (r.get("First_Last_Calculated") or f"{fn} {ln}").strip()

# ---- llm: (mdl, namekey) -> {roles, display}, old MDLs only ----
llm = defaultdict(lambda: {"roles": set(), "name": ""})
for line in open(JSONL, encoding="utf-8"):
    if not line.strip():
        continue
    rec = json.loads(line)
    mdl = nm_mdl((re.match(r"^(\d+)", rec.get("Source_File", "")) or [None, ""])[0])
    if mdl not in old_mdls:
        continue
    for a in rec.get("Appointments") or []:
        fn, ln = a.get("first_name", ""), a.get("last_name", "")
        if not (str(fn).strip() or str(ln).strip()):
            continue
        k = (mdl, nkey(fn, ln))
        llm[k]["roles"] |= set(a.get("appointment_types") or [])
        llm[k]["name"] = (a.get("full_name") or f"{fn} {ln}").strip()

# restrict gold to MDLs the LLM actually processed (fair role comparison; identity recall reported separately)
llm_mdls = {k[0] for k in llm}
keys = set(gold) | set(llm)

rows = []
matched = gold_only = llm_only = 0
agree = superset = subset = partial = disjoint = 0
role_conf = defaultdict(lambda: {"both": 0, "gold_only": 0, "llm_only": 0})   # per role
for k in sorted(keys):
    mdl, (nf, nl) = k
    g = gold.get(k); l = llm.get(k)
    gr = g["roles"] if g else set()
    lr = l["roles"] if l else set()
    name = (g or l)["name"]
    if g and l:
        matched += 1
        added = sorted(lr - gr); missed = sorted(gr - lr)
        if not added and not missed:
            flag = "agree"; agree += 1
        elif not missed:
            flag = "llm_added_role"; superset += 1
        elif not added:
            flag = "llm_missed_role"; subset += 1
        elif lr & gr:
            flag = "partial_disagree"; partial += 1
        else:
            flag = "disjoint"; disjoint += 1
        for role in gr | lr:
            if role in gr and role in lr: role_conf[role]["both"] += 1
            elif role in gr: role_conf[role]["gold_only"] += 1
            else: role_conf[role]["llm_only"] += 1
    elif g and mdl in llm_mdls:
        matched_flag = "gold_only_missed_by_llm"; gold_only += 1
        added, missed, flag = [], sorted(gr), matched_flag
    elif g:
        continue   # MDL not processed by LLM -> not a role-comparison case
    else:
        flag = "llm_only_not_in_gold"; llm_only += 1
        added, missed = sorted(lr), []
    rows.append({"MDL": mdl, "Attorney": name, "Gold_Roles": "; ".join(sorted(gr)),
                 "LLM_Roles": "; ".join(sorted(lr)), "Flag": flag,
                 "LLM_Added": "; ".join(added), "LLM_Missed": "; ".join(missed)})

with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=["MDL", "Attorney", "Gold_Roles", "LLM_Roles", "Flag", "LLM_Added", "LLM_Missed"])
    w.writeheader(); w.writerows(rows)

# ---- summary ----
gold_in_llm_mdls = sum(1 for k in gold if k[0] in llm_mdls)
print(f"gold MDLs: {len({k[0] for k in gold})} | LLM-processed old MDLs: {len(llm_mdls)}")
print(f"gold individual appts (in LLM-processed MDLs): {gold_in_llm_mdls} | LLM individual appts: {len(llm)}")
print(f"\nIDENTITY (attorney x MDL):")
print(f"  matched (in both)      : {matched}")
print(f"  gold-only (LLM missed) : {gold_only}   -> recall {matched/(matched+gold_only)*100:.1f}%")
print(f"  llm-only (not in gold) : {llm_only}   -> precision {matched/(matched+llm_only)*100:.1f}%")
print(f"\nROLE AGREEMENT on the {matched} matched attorneys:")
print(f"  exact agree        : {agree} ({agree/matched*100:.1f}%)")
print(f"  LLM added role(s)  : {superset} ({superset/matched*100:.1f}%)")
print(f"  LLM missed role(s) : {subset} ({subset/matched*100:.1f}%)")
print(f"  partial disagree   : {partial} ({partial/matched*100:.1f}%)")
print(f"  fully disjoint     : {disjoint} ({disjoint/matched*100:.1f}%)")
exact_or_partial = agree
print(f"  -> exact role-set match rate: {agree/matched*100:.1f}%")
print(f"\nPER-ROLE (on matched attorneys): both / gold-only(LLM missed) / llm-only(LLM added)")
for role, c in sorted(role_conf.items(), key=lambda kv: -(kv[1]['both']+kv[1]['gold_only'])):
    tot_gold = c["both"] + c["gold_only"]
    rec = c["both"] / tot_gold * 100 if tot_gold else 0
    print(f"  {role:24s} both={c['both']:4d}  gold_only={c['gold_only']:4d}  llm_only={c['llm_only']:4d}  (role recall {rec:.0f}%)")
print(f"\nwrote {os.path.relpath(OUT, ROOT)} ({len(rows)} rows)")
