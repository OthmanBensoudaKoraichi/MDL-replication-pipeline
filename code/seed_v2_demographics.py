#!/usr/bin/env python3
"""Pre-seed demographics_cache_v2.jsonl (keyed by v2 Attorney_ID) with gold hand-coded + prior
web-researched demographics matched by normalized canonical name, so attorney_demographics.py on the
v2 roster only researches the genuinely-new attorneys."""
import csv, json, os, re
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def L(p,enc="utf-8-sig"):
    with open(p,encoding=enc,newline="") as f: return list(csv.DictReader(f))
def nname(s): return re.sub(r"[^a-z]","",str(s or "").lower())
gold={}
for r in L(os.path.join(ROOT,"csvs_current_dataset","Attorneys-Export view.csv")):
    k=nname(r.get("Canonical_Name"))
    if k and any((r.get(c) or "").strip() for c in ("Gender","Law_School_Name","Birth_Year","Bar_States")):
        gold.setdefault(k,r)
v1name={r["Attorney_ID"]:nname(r["Canonical_Name"]) for r in L(os.path.join(ROOT,"canonical_attorneys_unified.csv"))}
web={}
for line in open(os.path.join(ROOT,"demographics_cache_unified.jsonl"),encoding="utf-8"):
    if line.strip():
        try: d=json.loads(line)
        except: continue
        k=v1name.get(d.get("Attorney_ID"))
        if k and d.get("sources"): web.setdefault(k,d)
out=open(os.path.join(ROOT,"demographics_cache_v2.jsonl"),"w",encoding="utf-8")
g_n=w_n=0
for r in L(os.path.join(ROOT,"canonical_attorneys_v2.csv")):
    aid=r["Attorney_ID"]; k=nname(r.get("Canonical_Name"))
    if k in gold:
        gd=gold[k]; gen=(gd.get("Gender") or "").strip().lower(); gen={"m":"male","f":"female"}.get(gen,gen)
        bar=[s.strip() for s in re.split(r"[;,]", gd.get("Bar_States") or "") if s.strip()]
        e={"Attorney_ID":aid,"gender":gen if gen in ("male","female") else "","birth_year":(gd.get("Birth_Year") or "").strip(),
           "undergrad_school":(gd.get("Undergrad_School") or "").strip(),"undergrad_grad_year":(gd.get("Undergrad_Grad_Year") or "").strip(),
           "law_school":(gd.get("Law_School_Name") or gd.get("Law_School") or "").strip(),"law_grad_year":(gd.get("Law_Grad_Year") or "").strip(),
           "bar_states":bar,"sources":["gold Attorneys table"],"confidence":"gold","notes":"from gold"}
        out.write(json.dumps(e,ensure_ascii=False)+"\n"); g_n+=1
    elif k in web:
        d=dict(web[k]); d["Attorney_ID"]=aid
        out.write(json.dumps(d,ensure_ascii=False)+"\n"); w_n+=1
out.close()
tot=len(L(os.path.join(ROOT,"canonical_attorneys_v2.csv")))
print(f"seeded {g_n} gold + {w_n} web = {g_n+w_n} | to research: {tot-g_n-w_n}")
