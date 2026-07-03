#!/usr/bin/env python3
"""Pre-seed the demographics cache with GOLD attorney demographics, so the (paid, web-grounded)
demographics run SKIPS any unified-roster attorney we already have gold data for, and only researches
the rest (mostly the new-corpus attorneys).

Matches unified canonical attorneys -> gold Attorneys table by normalized name (canonical + AKAs +
first/last). For each match where gold has >=1 demographic field, writes a cache line keyed by the
UNIFIED Attorney_ID, in the schema attorney_demographics.py expects (gender/birth_year/.../sources).
"""
import os, csv, json, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLD_ATT = os.path.join(ROOT, "csvs_current_dataset", "Attorneys-Export view.csv")
UNIFIED = os.path.join(ROOT, "canonical_attorneys_unified.csv")
CACHE = os.path.join(ROOT, "demographics_cache_unified.jsonl")

SUFFIX = {"jr", "sr", "ii", "iii", "iv", "v"}
DEMO_GOLD_FIELDS = ["Gender", "Birth_Year", "Undergrad_School", "Undergrad_Grad_Year",
                    "Law_School_Name", "Law_Grad_Year", "Bar_States"]


def load(p):
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def key(name):
    """normalized name key: drop punctuation, suffixes, single-letter initials; keep first+last word."""
    toks = [t for t in re.sub(r"[^a-z ]", " ", (name or "").lower()).split()
            if t not in SUFFIX and len(t) > 1]
    if len(toks) >= 2:
        return f"{toks[0]} {toks[-1]}"
    return toks[0] if toks else ""


def keys_of(row, namecols):
    ks = set()
    for c in namecols:
        k = key(row.get(c, ""))
        if k:
            ks.add(k)
    # also first+last explicitly
    fl = key(f"{row.get('First_Name','')} {row.get('Last_Name','')}")
    if fl:
        ks.add(fl)
    return ks


def has_demo(g):
    return any((g.get(c) or "").strip() for c in DEMO_GOLD_FIELDS)


def to_cache(aid, g):
    bar = [s.strip() for s in re.split(r"[;,]", g.get("Bar_States") or "") if s.strip()]
    src = [s.strip() for s in re.split(r"\s*\|\s*|;", g.get("Sources") or "") if s.strip()]
    gender = (g.get("Gender") or "").strip().lower()
    gender = {"m": "male", "f": "female"}.get(gender, gender)
    return {
        "Attorney_ID": aid,
        "gender": gender if gender in ("male", "female") else "",
        "birth_year": (g.get("Birth_Year") or "").strip(),
        "undergrad_school": (g.get("Undergrad_School") or "").strip(),
        "undergrad_grad_year": (g.get("Undergrad_Grad_Year") or "").strip(),
        "law_school": (g.get("Law_School_Name") or g.get("Law_School") or "").strip(),
        "law_grad_year": (g.get("Law_Grad_Year") or "").strip(),
        "bar_states": bar,
        "sources": (src or []) + ["gold Attorneys table"],
        "confidence": "gold",
        "notes": "from gold Attorneys table" + (f"; {g.get('Notes')}" if (g.get("Notes") or "").strip() else ""),
    }


gold = load(GOLD_ATT)
uni = load(UNIFIED)

# build gold name-key -> list of gold rows (only those with demo data)
gold_index = {}
gold_with_demo = 0
for g in gold:
    if not has_demo(g):
        continue
    gold_with_demo += 1
    for k in keys_of(g, ["Canonical_Name", "AKA_1", "AKA_2", "AKA_3"]):
        gold_index.setdefault(k, []).append(g)

seeded, ambiguous, no_demo_match, unmatched = 0, 0, 0, 0
seen_aid = set()
with open(CACHE, "w", encoding="utf-8") as cf:
    for u in uni:
        aid = u.get("Attorney_ID")
        uks = keys_of(u, ["Canonical_Name", "AKA_1", "AKA_2", "AKA_3"])
        hits = []
        for k in uks:
            hits += gold_index.get(k, [])
        # dedupe gold hits by identity
        uniq = {id(g): g for g in hits}.values()
        if not uniq:
            unmatched += 1
            continue
        if len({g.get("Attorney_Identifier") for g in uniq}) > 1:
            ambiguous += 1
            # pick the gold row with the most demo fields filled (most informative)
            best = max(uniq, key=lambda g: sum(1 for c in DEMO_GOLD_FIELDS if (g.get(c) or "").strip()))
        else:
            best = next(iter(uniq))
        cf.write(json.dumps(to_cache(aid, best), ensure_ascii=False) + "\n")
        seeded += 1
        seen_aid.add(aid)

print(f"gold attorneys: {len(gold)} | with >=1 demographic field: {gold_with_demo}")
print(f"unified roster attorneys: {len(uni)}")
print(f"SEEDED (matched to gold w/ demo -> will SKIP in paid run): {seeded}")
print(f"   of which ambiguous (matched >1 gold name; took most-complete): {ambiguous}")
print(f"unmatched (NO gold demo -> WILL be researched): {unmatched}")
print(f"wrote {os.path.relpath(CACHE, ROOT)}")
