# MDL pipeline — validation log & project state

Durable record so nothing is lost across context compaction. (Pipeline code is in `code/`;
eval outputs in `eval/`; this file is the human-readable index of what we've done.)

## ✅ FULL MDL_new RUN — COMPLETE & VERIFIED (2026-06-29)

The full-corpus MDL_new extraction is **done and reconciled**. Models: gpt-5.5 (gate/extract/resolve),
gpt-5.4-mini (classify/refine). OCR was pre-existing (not re-run). Total cost ≈ **$815** (under the
~$1,200 estimate). Quality is the held-out validation (~95% F1 / ~91% recall) transferred — there is
no gold on MDL_new (MDL_old and MDL_new are near-disjoint).

**Deliverables (at ROOT):** `order_extractions.jsonl` (MDL_new only; dev/holdout in
`order_extractions.jsonl.bak_devholdout`), `order_extractions.xlsx`, `canonical_attorneys.csv`,
`canonical_firms.csv`. Pre-retry roster backups: `canonical_*.csv.pre_retry`.

**VERIFIED FINAL NUMBERS** (via `code/sanity_check.py`, modeling `build_excel` exactly; every
workbook tab ties out to the jsonl):

| metric | value |
|---|---|
| Orders extracted (jsonl records) | **2,655** |
| Kept leadership orders (Orders tab) | **1,263** = 1,211 appt-bearing + 52 Needs_Motion (unresolved, kept) |
| Appointment rows (Appointments tab) | **10,191** = 6,684 individual/firm-appointee rows + 3,507 derived-firm rows |
| Canonical attorneys (deduped) | **2,162** |
| Canonical firms (deduped) | **1,248** |
| MDLs with ≥1 extracted order | **457** (folder-authoritative) |
| MDLs with ≥1 kept leadership order | **411** |
| MDL_new MDLs with no gate-passed order | 112 (of 569 targeted) |

**Coverage reconciliation:** `orders/` holds **716** MDL folders (whole-project history = 569 MDL_new
targets + 147 dev/holdout/gold whose extractions live in `.bak`). 716 − 569 = 147 non-target folders;
569 − 457 = 112 MDL_new targets with no gate-passed order; 147 + 112 = 259 folders with no jsonl row ✓.

**NUMBER CORRECTION:** the earlier headline "439 MDLs with leadership / 496 with orders" was **inflated
by a loose regex** (`\d{3,5}` matched docket numbers inside filenames). Authoritative folder-anchored
counts are **411 / 457**. The dataset did not shrink — it was mis-measured.

**Post-run cleanup done (2026-06-29):**
- Retried the run's **2 extract errors** scoped to `--mdls 2022,2275` (NOT `--all` — `--all` would have
  re-extracted 855 dev/holdout orders still in `orders/` and polluted the MDL_new jsonl). 0 errors on
  retry. MDL 2022 = preliminary-approval order, 0 appointees (dropped-empty); MDL 2275 = final-approval
  order naming Pomerantz LLP + Wohl & Fruchter LLP as plaintiff Co-Lead Counsel (kept). jsonl 2,653 → 2,655.
- Regenerated rosters from the complete jsonl. Person roster 2,163 → **2,162**: one correct merge —
  the truncated "Stephen A.Cor" folded into "Stephen A. Corr" (A0044; shared firm MELLON WEBSTER &
  SHELLY + MDL 1995; LLM medium-confidence, logged in `attorney_llm_adjudications.csv`). Firms unchanged
  at 1,248 (Pomerantz/Wohl folded into existing entries F0693/F0694; +2 mentions).

**FLAGS for the data-cleaning pass (marked, nothing dropped):**
- **52** orders still `Needs_Motion_Reading` with no appointees, across **40 MDLs** (the by-reference tail;
  cited motion/report not locatable). Kept in the Orders tab, flagged. **DECISION (2026-06-29): leave
  flagged, do NOT auto-resolve by description.** These appoint people by description ("the PSC / Lead
  Counsel as Class Counsel") with no cited docket. A description-based inheritance (match the body to the
  prior same-MDL order that named it) would touch ~35 of the 52, but was REJECTED: the formation→
  reappointment gaps are often multi-year (e.g. MDL 1741: 2006→2009), so the inherited slate risks being
  stale (members added/removed in between) — it would more likely inject wrong names than recover correct
  ones. The remaining 11 reference no nameable body (procedural/judgment orders the gate over-included).
- **18** `Docket_Mismatch` flags (model's docket ≠ filename's; filename docket used).
- **370** `Possible_Duplicate_Appointment` same-date rows (same appointee+role+side across >1 order on the
  same date; kept per gold convention, pre-identified for later dedup).

**DEMOGRAPHICS — DONE (2026-06-29):** ran on the UNIFIED roster, gold-aware (1,514 attorneys pre-seeded
from the gold Attorneys table so they were never re-researched; 1,743 web-researched via gpt-5.5 +
web_search). 0 errors. Output `canonical_attorneys_unified_demographics.csv`. Fill rates: Gender 97%,
Law School 98%, Undergrad 96%, Bar States 98%, Sources 99%, Birth Year 56% (birth year genuinely hard to
source). `attorney_demographics.py` gained `--in-csv/--out-csv/--cache`, `--workers` (parallel), and a
per-request `timeout=90` (a hung web_search had once stalled the run on the last 9). Pre-seeder:
`code/seed_demographics_from_gold.py`.

## ✅ UNIFIED CROSS-CORPUS ROSTER — MDL_old (gold) + MDL_new (extracted) (2026-06-29)

Goal: ONE database where an attorney/firm appearing in an old case **and** a new case has a SINGLE
canonical identity. Built by deduping a combined corpus in one pass.

**Sources (user decision: gold for old):** old half = human GOLD appointments
(`csvs_current_dataset/Appointments-Grid view.csv`, 185 MDLs, 6,144 appointee rows, hand-verified
names); new half = our extraction (`order_extractions.jsonl`), EXCLUDING MDLs already in gold so the
lone overlap (MDL 2357) isn't double-counted. Combined = `order_extractions_unified.jsonl` (3,389
records). Converter: `code/build_unified_corpus.py`. One dedup pass: `dedup_attorneys.py --jsonl
order_extractions_unified.jsonl --llm --out-suffix _unified`.

**Deliverables:** `canonical_attorneys_unified.csv`, `canonical_firms_unified.csv` (+ `_unified` audit/
review/adjudication logs). The MDL_new-only rosters (`canonical_*.csv`) are left intact alongside.

| | canonical | in BOTH corpora | old only | new only |
|---|---|---|---|---|
| **Attorneys** | **3,257** | **559** | 1,098 | 1,600 |
| **Firms** | **1,758** | **430** | 520 | 808 |

(individuals: 10,413 mentions → 3,459 exact-normalized → 3,257 canonical; 170 fuzzy merges + 107 LLM-
adjudicated weak pairs. firms: 10,485 mentions → 1,758 canonical.)

**Face validity (top shared attorneys):** Christopher Seeger (41 MDLs), James Cecchi (31), Richard
Arsenault (26), James Dugan / Dianne Nast (25), Steve Berman (22), Elizabeth Cabraser (20). **Top shared
firms:** Cohen Milstein Hausfeld & Toll (118), Hagens Berman (76), Lieff Cabraser (64), Motley Rice (54),
Seeger Weiss (51), Robbins Geller (48). These are the known MDL repeat-players → strong signal the
cross-corpus merge is correct.

**Validation vs gold:** humans recorded 1,600 distinct canonical attorneys in the gold; our unified
roster has 1,657 touching old (1,098 old-only + 559 both) — within ~3.6%, i.e. comparable granularity
(we merge marginally less aggressively than the humans).

**Tooling added:** `dedup_attorneys.py` gained `--out-suffix`, `--firms-only`, an MDLs column on the firm
roster, and zero-pad MDL normalization (`02000`→`2000`) in `load_mentions`. Report: `code/unified_report.py`.

## ✅ UNIFIED RELATIONAL DATABASE — one file, all tables, old+new (2026-06-29)

`unified_mdl_database.xlsx` (built by `code/build_unified_database.py`) — the single deliverable with
5 linked tabs spanning MDL_old (gold) + MDL_new (extracted):

| tab | rows | source |
|---|---|---|
| MDLs | 809 | MDL_merged.csv (old+new master) |
| Orders | 2,041 | gold 778 + new 1,263 (leadership orders; +Corpus col) |
| Appointments | 16,309 | gold 6,156 + new 10,153 (MDL 2357 from gold only) |
| Attorneys | 3,257 | unified cross-corpus roster + demographics |
| Firms | 1,758 | unified cross-corpus roster |

**Relational links:** every Appointments row carries `Unified_Attorney_ID` + `Unified_Firm_ID` into the
canonical rosters → join appointment → person (demographics) → firm, and appointment → order → MDL.
Individual-appt linkage **10,422 / 10,423 (99.99%)** (the 1 miss = a gold row with a blank MDL, excluded
from the dedup input — `Jonathan Cueno`). Gold rows also keep `Gold_Canonical_Name` for comparison.

**Linkage is EXACT, not fuzzy:** `build_unified_database.py` re-derives the dedup clustering read-only
(reusing the cached LLM adjudications in `attorney_llm_adjudications_unified.csv`) and VERIFIED it
reproduces `canonical_attorneys_unified.csv` with **0 ID mismatches** (3,257 attorneys, 1,758 firms) before
using its key→ID maps. Nothing existing was overwritten. `resolve_firms` gained an optional `return_keymap`.

## ✅ GOLD PIPELINE RUN + ALL-EXTRACTED REBUILD (2026-07-03)

Ran the full pipeline over all 201 old/gold MDLs (OCR'd 987 new docs; gated 597 → kept 122; freshly
extracted all 201 old at current gpt-5.5 prompts). Full-corpus `order_extractions.jsonl` = **3,632 orders**
(2,664 new + 962 old + 6 both); workbook Orders 2,037 / Appointments 18,886. Cost ~$145 (gate ~$14 +
OCR ~$30 + extract ~$99 + resolve). MDL_new-only jsonl backed up to `.bak_mdlnew_only`.

**FULL-GOLD EVAL (first across all 201, `code/compare_roles_vs_gold.py` → `appointment_type_comparison.csv`):**
identity recall 87.1% / precision 86.8% (attorney×MDL); role exact-set-match 77.4%. Per-role recall high
on the roles that matter (Management 96, LeadCounsel 96, Communications 95, Fees 97) with two documented
convention gaps: ClassCounsel over-tag (77%) and Settlement/**SettlementAdministration** conflation (LLM
folds SettlementAdmin into Settlement → 6% recall on that label). Each disagreeing row is flagged with the
exact roles added/missed. This is the per-row LLM-vs-human appointment-type flag Matt requested.

**DECISION (2026-07-03): final deliverable is ALL-EXTRACTED** (old + new LLM extraction), gold kept as
reference tabs. Dedup **v2 adopted** (LLM-adjudicated). Re-ran v2 on the all-extracted corpus:
**P=0.923 / R=0.865 / F1=0.893** (vs v1 P=0.904/R=0.587). Rosters: `canonical_attorneys_v2.csv` (3,178),
`canonical_firms_v2.csv` (1,545); mention→ID maps `dedup_v2_{attorney,firm}_map.csv`.

**FINAL `unified_mdl_database.xlsx` (`code/build_final_database.py`)** — 8 tabs: MDLs(809),
Orders(2,037), Appointments(18,886, linked to v2 IDs — 98% individual linkage), Attorneys(3,178 v2 +
demographics), Firms(1,545 v2), Gold_Appointments(6,156), Gold_Attorneys(1,610), Role_Comparison(3,148).
Prior gold-backed workbook backed up to `.bak_goldbacked`.

**PENDING:** (1) demographics for **353** v2 attorneys not matched to gold/prior-web by name (~$10-15 web);
(2) regenerate `datasets_ours` + notebook figures on the all-extracted data.

## 🔬 DEDUP FORENSIC AUDIT — why it was bad (2026-07-01)

Five-agent audit after the P.C. bug surfaced. **Decisive metric — our attorney clustering scored against
the HUMAN gold canonical names (old corpus, 1,793 mention-identities): pairwise precision 0.904 /
recall 0.587 / F1 0.712.** Cluster level: 79/1,585 gold attorneys SPLIT across our IDs (5.0%), 11/1,654 of
our IDs FUSE distinct people (0.7%). Dominant failure = UNDER-merging → repeat-player counts are
systematically UNDERSTATED (conservative bias for the paper, but the errors concentrate on prolific names).

**Attorney root causes:** (1) swap branch is DEAD CODE — blocking only on last-name keys, so "Berman
Steve" is never compared to "Steve Berman" (Steve Berman himself is split, A0030 vs A0852; ~15 gold splits);
(2) nickname table gaps + no prefix rule (Norm/Norman, Ernie/Ernest, Jerry/Jerrold, Russ/Russell…);
(3) plain Levenshtein≤1 + first-letter gate misses transpositions (Aimee/Amiee, Carl/Karl);
(4) last-name typos escape soundex blocks (Becnel/Bencel); (5) unicode/particles/degenerate mentions
(curly apostrophes, De Bartolomeo/Bartolomeo, "Zapala Zapala", surname-only); (6) INVISIBLE key-collision
fusions — all mentions sharing (first,last) fuse BEFORE matching, so two different "John Davis"/"Michael
Kelly"/"Jasper Ward" can never separate; 6 gold-proven, shows as Variants_Merged=1, never audited;
(7) "strong" nickname merges apply with ZERO context (87 such; 7 join disjoint-firm+MDL entities) while
shared firm/MDL "context" is treated as identity evidence — backwards for relatives/colleagues (Stranch
III vs IV welded via an initial-only bridge; Lambert; Fiske/Fisk); (8) the LLM saw only the weak residual
and its low-confidence rejections were silently dropped (D. Mathews/David Mathews: gold says same person).

**Firm root causes:** (1) positional sorted-token blocking is blind to exactly the pairs the subset rule
targets — **87–90 pairs the matcher itself would merge were never even compared**; transitively 164
Firm_IDs collapse to 77 true firms (~4.9% excess). High-impact splits: Lieff Cabraser 64|3, Zimmerman Reed
31|12, Robins Kaplan 21|9, Napoli 15|10, Milberg Tadler|Coleman 18|13, Kessler Topaz vs Barroway Topaz,
Lowey Dannenberg pair; (2) generic tokens count as identity (3 state-AG clusters fused; Gomez/Bonsignore
via {trial,lawyers}; NCLC/Chicago CLC); (3) single-token collapse (Morgan & Morgan absorbed Morgan Law
Firm; Geragos); (4) 2-token subset + residual suffixes (Saveri & Saveri fused with RIVAL Joseph Saveri Law
Firm — both appointed in the same antitrust MDLs); (5) short 2-surname names act as union-find hubs
(Phillips Grossman bridged Sanders↔Milberg lineages); (6) NO context gate for firms at all; (7) FIRM_STOP
still missing pllp/lpa/inc/plc + location tags (ca/dc/br). Of 197 multi-variant firm clusters: 185 correct,
10 wrong, 2 borderline. Pre-P.C.-fix damage: 17.7% of firm mentions were in wrong-membership clusters.

**Consequence for prior reporting:** the firm leaderboard is unreliable until re-dedup (Zimmerman Reed
truly ~43 MDLs, Robins Kaplan ~30, Napoli ~25 once splits merge). DECISION: rebuild dedup as
candidate-generation + LLM adjudication of ALL similar pairs (user directive). Audit artifacts:
scratchpad gold_benchmark.py, hunt1/hunt2_full.csv, undermerge_candidates_v2.csv.

## 🐛→✅ FIRM DEDUP BUG — single-letter suffix tokens (2026-07-01)

`firm_tokens` used `re.findall(r"[a-z]+", ...)`, so dotted legal suffixes split into single letters
("P.C."→`p`,`c`; "P.L.L.C."→`p`,`l`,`c`). Those letters weren't in FIRM_STOP, so every "P.C." firm shared
`{p,c}` and the ≥2-shared-token rule (plus the subset rule via a firm that reduced to just `{p,c}`)
transitively merged dozens of unrelated firms. **Worst case: the "Cohen Milstein" cluster wrongly absorbed
63 name-variants across 118 MDLs** (Lowey Dannenberg, The Miller Law Firm, Tostrud Law Group, …). 5 of 1,758
clusters affected.

**Fix:** drop single-letter tokens in `firm_tokens` (`len(t) > 1`). **Verified:** 0 bogus clusters remain
(was 5); firm roster 1,758→1,762; the Cohen Milstein blob corrected to **58 MDLs** (was an inflated 118),
and the true firm leaderboard is Hagens Berman 76 > Lieff Cabraser 64 > Lockridge Grindal Nauen 60 > Cohen
Milstein 58 (the old #1 at 118 was an artifact). Regenerated: `canonical_firms_unified.csv`,
`canonical_firms.csv` (MDL_new, 1,248→1,253), `unified_mdl_database.xlsx` (firm keymap re-verified 0
mismatches), `datasets_ours/*.csv`, and all `figures_ours/{old,new,both}/` (Fig 9 & 10 were distorted;
attorney/Monte-Carlo/entrant/gender/age figures unaffected). Backup: `canonical_firms_unified.csv.prebugfix`.

## ✅ YALE REPLICATION — re-run on our data, old / new / both (2026-07-01)

Adapted the Yale replication notebook (`replication_mdl/code/analysis.ipynb`) to our unified deduped
data. Deliverables: `replication_mdl/code/analysis_ours.ipynb` (scope switch: old|new|both, executed
for both), `replication_mdl/datasets_ours/*.csv` (exported unified tabs), `replication_mdl/
figures_ours/{old,new,both}/` (14 static PNGs each; the 2 bar-state choropleths are interactive plotly).

**Key adaptation:** the original notebook's two crude dedup steps — scraping a numeric attorney_id from
the `attorney` column, and clustering firm names by token overlap (Jaccard≥0.6) — are REMOVED; we use our
canonical `Unified_Attorney_ID` / `Unified_Firm_ID` (already on the Appointments tab), which also makes the
three scopes directly comparable. Everything else mirrors the paper (pelvic-mesh collapse→9999,
plaintiff-side focus, all 21 figures + cycling stat). `appoint` validity = gold "checked" / new Appoint==True.

**Bug found + fixed:** MDL date columns mix formats (old = `1991-07-29`, new = `2005-02-16 00:00:00`);
pandas inferred one format and coerced ALL 608 new dates to NaT, silently dropping new MDLs from Fig 12
(entrants) and the age figures. Fixed with `pd.to_datetime(..., format="mixed")`. All 3 scopes now run with
0 cell errors and complete figure sets.

**Headline results (validation that extracted-new reproduces the paper):** the Monte-Carlo test —
observed repeat co-appointment vs capacity-constrained random — is highly significant in EVERY scope:
old p=0.0000 (obs 1,558 vs null 583), new p=0.0000 (obs 1,100 vs null 310), both p=0.0000 (obs 3,953 vs
null 1,429). Cycling rate: old 0.83% / new 0.73% / both 1.23%. attorney×MDL rows: old 2,259 (154 MDLs) /
new 2,936 (300 MDLs) / both 5,195 (454 MDLs).

**FINALIZED (2026-06-29):** rebuilt after demographics completed — Attorneys tab now fully populated
(3,256/3,257 sourced). `unified_mdl_database.xlsx` is the final deliverable. Minor gold-data quirks flow
through (embedded newlines in a few names, some blank First Name) — gold-side data hygiene, not introduced here.

## DISTRIBUTION COMPARISON — old vs new (2026-06-29)

`code/dist_compare.py` (hand-rolled, self-validated tests; no scipy). Two panels disentangle method from
population. **Lead with effect sizes — at this N nearly everything is "significant".**

**PANEL A (method effect: gold vs OUR extraction on the SAME 150 old MDLs)** — core quantities are
statistically EQUIVALENT: individuals/order (5 vs 5, p=.68), orders/MDL (p=.67), individuals/MDL (p=.98),
contested (13.2 vs 12.0%, p=.50), side split (91/8 vs 89/9, V=.04), role mix small (Cramér's V=0.12). Two
method artifacts: **firm-typed appointee share 17%→26%** (representation: extraction tags more firm-level
appointees) and **OU_Create mean 2.13→1.28** (deliberate under-count; median identical at 1).

**PANEL B (gold-old vs extracted-new = population+method)** — larger differences, driven by POPULATION:
individuals/MDL median 14→10, individuals/order 5→4, role mix V=0.25 (new: Lead 13→21%, Class 15→26%,
Mgmt 43→36%), interim 10→17%. Contested (14 vs 12%) and side (90/92 P) still equivalent.

**Conclusion:** old≠new distributions, but the gaps are mostly the CASE MIX (MDL_new is smaller, more
class-action / lead-counsel-flavored; MDL_old is committee-heavy product-liability). The pipeline's own
fingerprints are narrow (firm-vs-individual tagging; conservative OU_Create) and the method is validated
(Panel A equivalence + held-out backtest ~95% F1). **For rate analyses, control for population (MDL type/era);
for entity/firm rosters, pooling is fine.** (Panel A .bak extraction may use slightly older prompts.)

**Caveats to note for the paper:**
- **Firm name changes are NOT merged** (correctly): e.g. "Cohen Milstein Hausfeld & Toll" (118), "Cohen
  Milstein Sellers & Toll" (61), and "Hausfeld LLP" (55) are kept distinct — different firm names/eras
  after Michael Hausfeld's 2008 departure. A judgment call for whichever the analysis treats as one entity.
- A few canonical **display names** picked a truncated variant (e.g. "W. Miles" for W. Daniel Miles III);
  the MERGE is correct, only the chosen label is the shorter form — cosmetic, fixable by preferring the
  longest variant as canonical.
- Old half uses human-coded appointments; new half uses extraction (validated ~95% F1) — mixed lineage by
  design (gold for old, extraction for new), which is how the paper uses the data.


## MDL populations (reconciled)

```
MDL_old.csv (master list)     = 201 MDLs   (true distinct MDL_NO; the 235-ish line count is
                                             inflated by newlines inside Notes/Comments cells)
  - have >=1 coded order        = 185   <- "gold-labeled" = the Orders/Appointments CSVs
  - Complete but Order_Count=0  =  16   <- coders reviewed, found NO appointment orders
                                          (e.g. 1880, 2099, 2826) -> negative controls, untested
used (extracted) by us          = 130   (all within the 185 gold)
untouched gold (185 - 130)      =  55
```
All 185 gold MDLs are in MDL_old (gold subset of master). The 16 zero-order MDLs are a useful
PRECISION test we haven't run: the pipeline should also yield ~0 appointments on them.

## Cases used so far: 130 distinct MDLs (of 185 gold-labeled)

Every MDL we have run the pipeline on, by batch. These are the **dev + validation sets** — keep
them straight. Authoritative source: distinct MDL_No in `order_extractions.jsonl` (= 130).

| batch | n | purpose | seed | MDLs |
|---|---|---|---|---|
| **dev** | 10 | prompt development (all extraction-prompt fixes tuned here) | 281835 | 2263, 2428, 2504, 2570, 2664, 2687, 2741, 2818, 2873, 2878 |
| **held** | 10 | 1st held-out; tuned the eval MATCHER (fuzzy names/swaps/dedup) | 424242 | 1869, 2262, 2295, 2387, 2420, 2492, 2543, 2695, 2740, 2850 |
| **batch2** | 20 | tuned the Rule-53 report resolver (2406); found 2848 gold error | 2026 | 1566, 2151, 2187, 2243, 2406, 2434, 2567, 2670, 2672, 2743, 2773, 2775, 2795, 2800, 2817, 2836, 2842, 2848, 2859, 2867 |
| **fresh** | 20 | tuned the firm-row decision (2724) + repr-agnostic eval | 7777 | 1720, 1917, 1964, 2244, 2286, 2440, 2460, 2522, 2545, 2551, 2591, 2592, 2627, 2667, 2724, 2785, 2801, 2816, 2875, 2886 |
| **blind** | 20 | TRUE blind (unfixed version); error-analysed afterward | 31415 | 1871, 2047, 2221, 2311, 2326, 2437, 2472, 2548, 2575, 2580, 2595, 2645, 2656, 2657, 2666, 2709, 2742, 2768, 2862, 2885 |
| **valid** | 20 | validate the firm-row/truncation FIX (≥3-order MDLs) | 271828 | 1663, 1700, 2034, 2036, 2179, 2185, 2296, 2323, 2325, 2338, 2391, 2441, 2516, 2599, 2626, 2734, 2753, 2789, 2819, 2846 |
| **small** | 30 | validate fixed pipeline on EASY end (1-2-order MDLs) | 161803 | 1431, 1570, 1738, 1913, 2002, 2009, 2272, 2331, 2353, 2418, 2436, 2493, 2542, 2566, 2590, 2613, 2633, 2669, 2673, 2693, 2744, 2767, 2796, 2797, 2807, 2814, 2820, 2865, 2874, 2887 |

`test_mdl_final/` sample deliverable = 3 MDLs from the valid batch (seed 7): **2179, 2391, 2516**.

## Pipeline (9 stages + 2 utilities), all in `code/`

1. `count_pages.py` (free) → page_counts.csv
2. `classify_type.py` (gpt-5.4-mini) → type_labels.csv  (Order/Motion/Other/Unclear)
3. `filter_corpus.py --apply` (free) → filtered_files/  (dedup, drop dockets/Other/long-Unclear/corrupt)
4. `ocr_llamaparse.py` (LlamaParse fast + Tesseract) → ocr/<MDL>/<doc>.json
5. `refine_unclear.py` then `--apply` (gpt-5.4-mini) → rescue orders mislabeled Unclear
6. `confirm_orders.py --model gpt-5.5 --include-motions` → order_status.csv  (THE GATE: relevance + executed)
7. `trim_orders.py` (free) → orders/<MDL>/<doc>.json  (cut at signature page)
8. `extract_orders.py` (gpt-5.5) → order_extractions.{jsonl,xlsx}  (the 3 Airtable tables)
9. `resolve_motions.py` (gpt-5.5) → reads cited MOTION or adopted Special-Master/Rule-53 REPORT
   (incl. on-demand OCR of roster exhibits) to fill Needs_Motion_Reading orders
- `make_dd_docx.py` → regenerates DATA_DICTIONARY.docx from the LIVE prompts
- `eval_vs_gold.py` → the evaluation harness (deterministic; `--mdls <list> --tag <name>`)

Run everything with the Framework Python: `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3`.

## Evaluation method (`code/eval_vs_gold.py`)

Deterministic (no LLM judge). Auto-scopes to MDLs extracted ∩ gold-labeled (`--mdls` restricts).
Names matched on a tolerant key (spelling/middle-initials/suffixes ignored; first/last SWAP tolerated;
within-source fuzzy dedup). Firms compared REPRESENTATION-AGNOSTICALLY (a firm counts whether it's a
separate row or an individual's `firm` attribute). Metrics, by tier:
- **Tier 1 Appointments (primary):** Individuals / Firms / Combined identity recall-precision-F1;
  role **Jaccard** (partial credit); side %; soft-F1 (role-weighted). 95% Wilson CIs.
- **Tier 2 Orders:** identity recall/precision/F1 (appointment-bearing) + analytic-field agreement
  (Order_Types Jaccard, OU_Create, Contested, structural booleans; Judge/Date = metadata).
- **Tier 3 Attorneys:** distinct-individual recall/precision (= Tier-1 individuals).
Why precision/recall not accuracy for identity: true-negatives unbounded. Accuracy IS used for field
values (closed value space on matched items).

## Validation results (FIXED pipeline = compact extraction + firm rows derived in build_excel)

| set | indiv R/P/F1 | firms F1 | orders F1 | notes |
|---|---|---|---|---|
| valid (≥3-order, 83% of all appts) | 86.4 / 86.4 / 86.4 | 87.2 | 90.3 | hard end; roles 90.4, side 100 |
| small (1-2-order, 17% of appts) | 97.1 / 86.3 / 91.4 | 96.1 | 86.0 | easy end; median per-MDL recall 100% |
| **population-weighted estimate** | **~88 / ~86 / ~87** | ~94-96 | ~89 | the number for the paper |

Prior (UNFIXED) blind-20 (≥3): individuals R82.9 / P92.7 / F87.5.  Truncation fix CONFIRMED: large
rosters now extract fully (e.g. 37/37, 29/29, 26/26) instead of ~half.
**Key finding:** precision is robust (~86-96%); residual recall gaps are characterized
(by-reference/exhibit rosters that yield ~0, a few order-coverage misses) — not random model error.

### Free re-eval vs CORRECTED gold (2026-06-28) — OLD-prompt extractions, gold corrections only

Ran `eval_vs_gold.py` on the EXISTING `order_extractions.jsonl` (old prompts) against the corrected
`csvs_current_dataset/`. Tags: `refresh_all` / `refresh_valid` / `refresh_small`.

| scope | indiv R/P/F1 | firms F1 | role Jac | orders F1 | OU_Create | Order_Types exact/Jac |
|---|---|---|---|---|---|---|
| full 130 (POOLED, incl. dev → optimistic) | 91.5/91.6/91.6 | 92.7 | 85.6 | 89.5 | 74.3% | 54.2%/74.0% |
| valid (≥3-order, held-out) | 86.4/86.4/86.4 | 87.2 | 90.4 | 90.3 | 67.2% | 52.8%/72.5% |
| small (1-2-order, held-out) | 97.1/86.3/91.4 | 96.1 | 92.6 | 86.0 | 74.4% | 67.4%/76.6% |

- The held-out valid/small numbers (and gold counts 361/207) are IDENTICAL to the pre-correction
  figures → **the CSV corrections did not move the held-out appointment scoring.**
- Full-130 (91.6 F1) pools in prompt-tuned dev MDLs → optimistic, NOT held-out.
- Still OLD prompts: `OU_Create` (74.3%) reflects the permissive prompt the conservative revision
  targets; CPA exclusion not yet applied. **Prompt-change effect requires re-extraction (the paid step).**
- Weakest analytic fields (subjective booleans, future tune/recode candidates): `Order_Types(exact)`,
  `OU_Duties_to_Nonclients` (54%), `OU_Functions` (63%).
- **PENDING DECISION:** paid re-extraction with new prompts — targeted (valid+small, 50 MDLs, ~$20)
  or full (130 MDLs, ~$54-95). Re-extraction universe = 810 gated orders, ~15.8M chars.

## Major decisions / fixes made (chronological)

- Appointment-ONLY gate (dropped fees/CBF/settlement unless they appoint counsel).
- Extraction prompt: roster enumeration (incl. CM Plans), interim rule, full_name field, by-reference
  prose extraction, role de-over-tagging (committee member ≠ LeadCounsel), 2-column-roster note.
- Stage-3 content-hash dedup; gate/trim restricted to filtered_files membership.
- Stage-6 gate built (relevance + executed; drop on positive non-order evidence, not signature-absence;
  memo-endorsement exception; head+early-body+middle+tail excerpt for long orders).
- Stage-7 trim cuts at signature markers (/s/, U.S.D.J., SO ORDERED).
- Stage-9 resolve_motions: reads cited motion AND adopted Special-Master/Rule-53 report (+ on-demand
  OCR of roster exhibits from files/).
- Docket bug fix (filename docket wins over body-text number).
- Zero-appointee keep-rule: drop orders with no appointees UNLESS flagged Needs_Motion_Reading.
- Firm representation: LLM emits compact individual-with-firm-attribute; firm Appointment rows DERIVED
  deterministically in build_excel (one per order×firm) — avoids output-token truncation on big rosters.
- 2026-06-26 prompt updates: OU_Create made more conservative (count only units the order CREATES,
  not appointments to pre-existing units; under-count when unsure); ATTORNEYS-AND-FIRMS-ONLY rule
  (exclude CPAs/accountants/economists/administrators etc. by title).
- 2026-06-28 pre-full-run hardening (see METHOD.md §13): raised worker defaults
  (classify 48 / refine 32 / confirm 32 / extract 24 / resolve 16); added `--all` to confirm/trim/
  extract (full corpus without a hand-maintained MDL list); added `--model` + a fail-fast preflight
  ping (gpt-5 fallback) to confirm/extract/resolve; fixed the stale confirm_orders docstring; added a
  stage 8->9 guard (build_excel warns loudly if kept orders are still Needs_Motion_Reading w/ no
  appointees); added within-MDL appointment dedup flag `Possible_Duplicate_Appointment` (same
  appointee+role+side on the SAME DATE across >1 order -> flagged, not dropped; 475/7120 on current data).
- 2026-06-28 DEFERRED to the full-corpus run (per user): attorney dedup, firm dedup, and attorney
  demographics lookup -- all to run ONCE over the whole corpus, not per-batch. Paid re-extraction with
  the new prompts also folds into that run.
- 2026-06-28 ADVERSARIAL AUDIT (8 dimensions, every finding re-verified): 16 high + 25 medium confirmed.
  Fixed dataset-corrupting bugs (cross-MDL dedup -> per-MDL; fee-regex no longer drops class-counsel
  orders; reappointment date guard; name/firm over-merge guards). [2026-06-29: the within-MDL same-date
  appointment dedup was reverted from an auto-COLLAPSE to a non-destructive FLAG -- all per-order rows
  kept like the gold tables; de-dup deferred to a later data-cleaning step.] Shipped transparency fixes (Provenance column; reproducibility recording; refine whole-doc
  gate; --llm hardening; docket-mismatch flag; eval --strict). See METHOD.md sec.15. All 19 methodology
  DECISIONS resolved with the user (METHOD sec.15c). Key validation numbers:
  * backtest on a random 20 of the 130 gold MDLs: individuals F1 95.1 (fuzzy) / 91.6 (strict-key) --
    matching tolerance ~3.5 pts; result robust. (3/20 were prompt-dev; strict-blind ~87%.) Audit report
    artifact + METHOD sec.15 hold the detail.
  * classifier-error sample (n=100): filename-vs-body type agreement 78%, but 0/100 recall-critical
    (no real order/motion mislabeled to the droppable 'other'). classify_error_sample.csv.
  * confirmed extraction reads each order in full to its signature (no truncation).
  No double-coding / no gate-drop audit (user decisions) -> disclosed as limitations, not measured.
- 2026-06-28 resolver enhancement (BUILT, resolve_motions.py): the 30 still-unresolved
  Needs_Motion_Reading orders now classify deterministically (no LLM): **6 reappointment** orders
  INHERIT the slate of the prior appointing order (cited prior-order docket preferred, e.g. Docket 64;
  title-confirmed reappointments may fall back to the most-recent prior matching order), tagged in
  Notes + Motion_Read_Result and flagged for review; **19 fee/settlement-approval** orders are
  EXCLUDED (flag cleared, no appointees -> dropped by keep_order); **5 genuine appoint-by-reference**
  with no findable motion stay flagged. Validated on gold 2522-436: inherit from cited Docket 64 ->
  recall 100% (7/7 gold names), precision 88% (1 stale: Christopher Walsh, removed by a cross-case
  substitution order not in our corpus -- the documented limitation). `resolve_motions.py --dry-run`
  prints the full plan (kind per order).

## PENDING / TODO

1. **Re-extract** the dev+validation MDLs with the updated prompts (OU_Create + attorney-only) and
   **re-run evals against the corrected gold** to get refreshed numbers. (Prompt edits only take
   effect on re-extraction.)
2. **Lay out / clean the codebase**, delete unused files, before the full-dataset run.
3. **Full-corpus run** (gate+extract on all ~700 MDLs; only OCR has been corpus-wide, and not even
   for the gold MDLs originally — they were in exclude_mdls.txt).
4. **Attorney/firm dedup — BUILT (2026-06-28): code/dedup_attorneys.py.** Deterministic-first entity
   resolution (Soundex+last[:4] blocking; nickname dict; EXACT-surname auto-merge guard; firm/MDL
   context; `--llm` adjudicates the weak residual). Prototype on the current 130-MDL roster: 4,074
   mentions -> 1,461 exact-normalized -> 1,388 canonical; 73 high-precision merges; 28 review pairs;
   firms 4,291 -> 751. Over-merge traps (Hellums/Hellmich, McCarley/McCauley) correctly routed to
   review, not merged. Writes canonical_attorneys.csv / canonical_firms.csv / *_audit / *_review.
   **Attorney demographics** (Gender, Birth_Year, schools, Bar_States, Sources) STILL TO BUILD --
   web-research per canonical attorney. Dedup + demographics both RUN during the MDL_new full-corpus run.
5. **DONE (2026-06-28) — MDL_merged.csv** (809 rows, 38 cols = MDL_old's 36 + YEARS_PENDING + a
   Source_Table provenance col). Joined on the MDL number embedded at the START of CAPTION/TITLE (both
   tables put it there; MASTER_DOCKET parsing was unreliable). **Finding: MDL_old (201) and MDL_new
   (609) are NEAR-DISJOINT** — only MDL 2357 in both; 200 old-only, 608 new-only. Likely complementary
   (MDL_new = MDLs not yet gold-coded), so the union is the full master list. 4 MDL_new "rows" were
   spreadsheet junk (=COUNTIF formulas) and dropped. Overlap conflicts kept MDL_old's value (cosmetic
   only). AWAITING user confirmation that the near-disjointness is expected.
   Original mapping spec: merge MDL_old.csv + MDL_new.xlsx into one file with MDL_old's columns + MDL_new's content.
   Column mapping (MDL_old ← MDL_new): CAPTION←TITLE, TYPE←MDL_TYPE, JUDGE←JUDGE, DISTRICT←DISTRICT,
   DATE_TRANSFERRED←DATE_TRANSFERRED, DATE_TERMINTAED←DATE_CLOSED, MASTER_DOCKET←MASTER_DOCKET_NO,
   Notes←NOTES, "Assigned to"←ASSIGNED, plus MDL_new.YEARS_PENDING (new). JOIN CHALLENGE: MDL_new has
   NO MDL number column — must join on TITLE/caption or MASTER_DOCKET_NO. NOTE: `TYPE`/`mdl_type` is a
   GIVEN (already present in the Order table); do NOT extract it or add it to the prompt.

## Known limitations / future improvements (validate any fix on a FRESH set)
- By-reference/exhibit rosters that resolve to ~0 (extend the resolver further).
- A few order-coverage misses (gold orders not extracted).
- Truncation-detection safety net (flag any extraction that hits the output-token cap).
