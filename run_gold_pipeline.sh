#!/bin/bash
# GOLD pipeline PHASE A (2026-07-03): filter -> OCR (988 missing) -> refine -> gate -> trim.
# Stops BEFORE extraction (the cost checkpoint). Every stage skips already-done work, so on the
# new MDLs these are no-ops; real work is the ~51 untouched + 988 un-OCR'd old docs.
set -uo pipefail
cd "/Users/othmanbensouda/Desktop/Data Collection MDL"
PY=/Library/Frameworks/Python.framework/Versions/3.12/bin/python3
LOG=gold_pipeline_run.log
echo "=== GOLD PIPELINE PHASE A  $(date) ===" | tee "$LOG"
stage() { echo -e "\n##### $1  [$(date +%H:%M:%S)] #####" | tee -a "$LOG"; }

stage "0. backup live jsonl (MDL_new-only snapshot)"
cp order_extractions.jsonl order_extractions.jsonl.bak_mdlnew_only && echo "backed up -> order_extractions.jsonl.bak_mdlnew_only" | tee -a "$LOG"

stage "1. filter_corpus --apply (free; adds MDL 2099 + any gaps)"
$PY code/filter_corpus.py --apply >>"$LOG" 2>&1; tail -3 "$LOG"

stage "2. OCR --all (existing skipped; ~988 old docs)"
$PY code/ocr_llamaparse.py --all --workers 24 >>"$LOG" 2>&1; tail -4 "$LOG"

stage "3. refine_unclear --all --apply (mini)"
$PY code/refine_unclear.py --all --apply --workers 32 >>"$LOG" 2>&1; tail -3 "$LOG"

stage "4. confirm_orders --all --model gpt-5.5 (gate; only never-gated docs)"
$PY code/confirm_orders.py --all --model gpt-5.5 --workers 32 >>"$LOG" 2>&1; tail -4 "$LOG"

stage "5. trim_orders (old MDLs)"
OLD=$($PY - <<'EOF'
import csv, re
old=set()
for r in csv.DictReader(open("MDL_merged.csv",encoding="utf-8-sig")):
    if (r.get("Source_Table") or "").strip() in ("old","both"):
        m=re.match(r"^(\d+)",str(r.get("MDL_NO") or "").strip())
        if m: old.add(m.group(1))
print(",".join(sorted(old,key=lambda x:(len(x),x))))
EOF
)
if $PY code/trim_orders.py --help 2>/dev/null | grep -q -- "--all"; then
  $PY code/trim_orders.py --all >>"$LOG" 2>&1
else
  $PY code/trim_orders.py --mdls "$OLD" >>"$LOG" 2>&1
fi
tail -3 "$LOG"

stage "6. CHECKPOINT — old gate-kept order volume (extract cost driver)"
$PY - <<'EOF' | tee -a "$LOG"
import csv, re
old=set()
for r in csv.DictReader(open("MDL_merged.csv",encoding="utf-8-sig")):
    if (r.get("Source_Table") or "").strip() in ("old","both"):
        m=re.match(r"^(\d+)",str(r.get("MDL_NO") or "").strip())
        if m: old.add(m.group(1))
kept=0
for r in csv.DictReader(open("order_status.csv",encoding="utf-8")):
    m=re.match(r"^(\d+)",r["relpath"])
    if m and m.group(1) in old and r.get("retrieve")=="1": kept+=1
print(f"OLD gate-kept orders to extract: {kept:,}  (~${kept*0.08:.0f} est extract cost)")
EOF
echo -e "\n=== PHASE A DONE $(date) — review checkpoint, then run extract ===" | tee -a "$LOG"

# ---- PHASE B (extract + resolve), invoked separately ----
