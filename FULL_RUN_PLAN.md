# Full-corpus run plan — MDL_new (the analysis dataset)

The final extraction targets **MDL_new = 609 MDLs** (disjoint from the 201 gold MDLs in MDL_old).
This is the runbook + cost estimate. **Nothing here has been spent** — it's the plan to approve.

## Data status (already checked)

| | count |
|---|---|
| MDL_new MDLs | 609 |
| …with source PDFs in `files/` | **569** |
| …**with NO PDFs** (cannot be coded — disclose as a coverage gap) | **40** |
| …already OCR'd (`ocr/`) | **567** |
| …have PDFs but not yet OCR'd | 2 |
| MDL_new PDFs on disk | 31,658 |

So **stages 1–4 (count → classify → filter → OCR) are essentially already done for MDL_new** (567/569
OCR'd). The remaining work is the gate, extraction, resolution, dedup, and demographics.

## The run, stage by stage (use `--all`)

```bash
P=/Library/Frameworks/Python.framework/Versions/3.12/bin/python3
# stages 1–4: already done for MDL_new (only 2 MDLs need OCR top-up)
$P code/ocr_llamaparse.py --all --exclude-file exclude_mdls.txt --workers 24   # tops up the 2 missing
$P code/refine_unclear.py && $P code/refine_unclear.py --apply                  # rescue mislabeled orders
$P code/confirm_orders.py --model <MODEL> --include-motions --all               # STAGE 6 — the gate (cost driver)
$P code/trim_orders.py --all                                                    # free
$P code/extract_orders.py --all                                                 # STAGE 8 — extract (cost driver)
$P code/resolve_motions.py                                                      # STAGE 9 — motions/reports/reappt + fee-drop
$P code/dedup_attorneys.py --llm                                                # canonical roster (mostly free)
$P code/attorney_demographics.py --apply                                        # fill demographics (web-grounded)
```

## Cost estimate (gpt-5.5 prices $5/$30 per 1M; mini $0.25/$2)

Grounded in the actual dry-run volumes (gate candidates **25,643** to-do incl. motions; ~21% gate
retrieve rate on MDL_old → ~**4,500–5,000** orders to extract).

| Stage | Volume | gpt-5.4-mini | gpt-5.5 |
|---|---|---|---|
| 6 gate (`confirm_orders`) | ~25,600 docs | **~$40** | **~$750** |
| 8 extract (`extract_orders`) | ~4,500–5,000 orders | (always gpt-5.5) | **~$300–500** |
| 9 resolve (`resolve_motions`) | flagged subset | — | ~$10–20 |
| 5 refine / 1–4 / 7 trim | mostly done / free | ~$2–10 | — |
| dedup (`dedup_attorneys --llm`) | ~free + ~$1 | — | — |
| demographics (`attorney_demographics`) | ~3–5k attorneys | ~$150–250 + web-search fees | — |

**Bottom line:** ~**$675** (gate on mini) to ~**$1,400** (gate on gpt-5.5), all-in. The **gate model is a
~$700 swing** and the single biggest decision.

## Decisions to make before spending

1. **Gate model (stage 6) — the big lever.**
   - **gpt-5.5 (~$750):** matches the *validated* methodology (the 86–91% F1 numbers were produced with
     a gpt-5.5 gate). Higher precision; fewer real orders wrongly dropped. **Recommended** — the gate is
     the precision-critical filter and a weak gate's *false negatives (dropped real orders) are
     unrecoverable*.
   - **gpt-5.4-mini (~$40):** 17× cheaper. Risk: lower recall at the gate. A defensible hybrid is
     mini-gate → gpt-5.5 extract (extract re-reads, so gate *false positives* are caught downstream),
     but mini-gate *false negatives* are not. If chosen, validate the recall delta on a sample first.

2. **No gold exists on MDL_new (it is disjoint from MDL_old's gold).** ⚠️ This means **the eval cannot
   run on the analysis dataset** — extraction quality on MDL_new would be *inferred* from the MDL_old
   validation, not measured. A Harvard referee will ask for this. **Strong recommendation: hand-code a
   small random MDL_new gold sample (~15–20 MDLs) and run `eval_vs_gold.py --mdls <them>` to confirm the
   MDL_old numbers transfer.** Without it, the quality claim on MDL_new is unvalidated.

3. **Demographics method** (web-grounded LLM lookup with sources + confidence; gender from bios not
   names; unknown stays blank) — confirm this is the disclosed method, or swap to name-based gender
   inference (cheaper, less accurate, more reproducible) if you prefer.

## Disclosures the paper should carry (from this plan)
- **40 of 609 MDL_new MDLs have no source filings** → excluded; report the list and any selection it implies.
- **MDL_new quality is the MDL_old-validated estimate, transferred** (unless a MDL_new gold sample is coded).
- The **data-altering steps** (reappointment inheritance, fee-exclusion, same-date appointment dedup,
  code-derived firm rows) — disclose each with its audit tab (`Dropped (*)`, `attorney_merge_audit`,
  `Motion_Read_Result`, `Possible_Duplicate_Appointment`).
- **Model versions are post-training-cutoff and not seed-pinned** → some non-determinism; freeze versions
  and cache outputs (the demographics cache already does this).

## Recommended order of operations
1. Approve the gate model.
2. Hand-code a ~15–20-MDL MDL_new gold sample (or accept transferred validation).
3. Run gate → trim → extract → resolve on `--all`.
4. Run the MDL_new gold-sample eval to confirm quality transfers.
5. Dedup → demographics.
6. Write the methods/limitations section from the disclosures above.
