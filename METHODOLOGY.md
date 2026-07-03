# Methodology — MDL Leadership Data Pipeline

*Replication materials for "Who Leads in Mass Litigation? Evidence from MDL."*
This document describes, end to end, how a corpus of MDL (multidistrict-litigation) court-document
PDFs is turned into a structured, deduplicated, demographically-enriched dataset of leadership
appointments, and how that dataset is validated. For stage-level code detail see `METHOD.md`; for the
dated build/validation record see `VALIDATION_LOG.md`.

---

## 1. Data populations

Two near-disjoint sets of MDLs (only MDL 2357 overlaps), unified into one master list `MDL_merged.csv`
(809 MDLs = 200 old-only + 608 new-only + 1 both):

- **MDL_old (201 MDLs, "gold").** Hand-coded by human research assistants into an Airtable base
  (Orders / Appointments / Attorneys). The human coding is treated as ground truth and lives in
  `csvs_current_dataset/` (exported grids).
- **MDL_new (~609 MDLs).** Not previously hand-coded; the motivation for building an automated pipeline.

The **final dataset applies the automated pipeline uniformly to *all* MDLs (old + new)**, so the corpus
is single-method end to end. The human gold coding is retained separately (see §7) as the validation
benchmark and as reference tabs in the deliverable.

---

## 2. Document → data pipeline

A deterministic DAG; each stage is a pure function of the previous stage's durable output.
Models: **gpt-5.4-mini** for cheap classification, **gpt-5.5** (a reasoning model) for the precision-
critical gate/extraction/resolution. OCR via **LlamaParse** (fast tier) with a Tesseract fallback.

| # | Stage | What it does | Engine |
|---|---|---|---|
| 1 | `count_pages` | page-count cache | deterministic |
| 2 | `classify_type` | label each PDF ORDER / MOTION / UNCLEAR / OTHER by filename+body | gpt-5.4-mini |
| 3 | `filter_corpus` | drop OTHER, docket dumps, long UNCLEARs; hard-link the rest | deterministic |
| 4 | `ocr_llamaparse` | per-page text for every kept PDF | LlamaParse + Tesseract |
| 5 | `refine_unclear` | rescue orders mislabeled UNCLEAR (regex-gated LLM read) | gpt-5.4-mini |
| 6 | `confirm_orders` | **THE GATE** — keep only orders that *appoint/modify leadership* and were judge-signed; excludes fee/common-benefit and settlement-only orders | gpt-5.5 |
| 7 | `trim_orders` | cut each order at its judge-signature page (drops exhibits) | deterministic |
| 8 | `extract_orders` | structured extraction of order fields + appointees | gpt-5.5 |
| 9 | `resolve_motions` | for orders that appoint *by reference* to a motion/report, follow the citation, OCR it on demand, extract the named slate; inherit reappointments; exclude fee orders | gpt-5.5 |

**Scope:** plaintiff-side leadership (lead/co-lead/liaison counsel, PSC/PEC and other steering/
executive committees, Rule 23(g) class counsel). **Appointment orders only** — attorney-fee, common-
benefit, and pure settlement/judgment orders are deliberately excluded.

### Extraction schema
Each order yields order-level fields (date, judge, judge type, contested, Rule 23, OU_Create/Terminate
counts, order types, …) and a list of **appointees**. Each appointee carries: name (first/last/full),
firm, appointee type (Individual / Firm), plaintiff-vs-defendant, and one or more **appointment types**
from a fixed 16-label vocabulary (LeadCounsel, Management, ClassCounsel, Communications, Settlement,
SettlementAdministration, Coordination, Fees, Discovery, Motions, Expert, Trial, LocalCounsel,
Bellwether, Vetting, ProSe). Firm-level appointee rows are derived per (order × distinct firm).

**Operational conventions:** MDL number and docket are canonicalized from the filename (the model's
value is flagged in `Docket_Mismatch` when it disagrees); zero-appointee orders are dropped unless still
flagged for by-reference resolution; a `Provenance` field records how each order's appointees were
obtained (extracted / motion-read / inherited-reappointment / excluded-fee).

---

## 3. Entity resolution (dedup) — `code/dedup_v2.py`

Attorneys and firms are mentioned under many spellings, abbreviations, OCR errors, name-order swaps, and
firm renames. Dedup v2 is an **LLM-adjudicated** resolver (the earlier rules-only v1 under-merged badly —
recall 0.59):

1. **Normalize** (unicode→ascii, particles, suffix handling, doubled-token / surname-only salvage).
2. **Sub-entity aggregation** at *(name-key × firm-signature)* so two different people sharing a name
   become *visible, separable* entities rather than a silent fusion.
3. **Generous candidate generation** — unordered soundex-pair blocking (catches first/last swaps),
   last-name edit distance, anagram keys (transpositions), shared-rare-firm-token, token multisets. Rules
   only *propose* pairs; they never decide.
4. **gpt-5.5 adjudication of every candidate pair**, with firm/MDL context and explicit instructions on
   the hard cases (name commonness; relatives/colleagues at one firm; suffix conflicts = distinct; firm
   **renames/mergers = same lineage**, **spin-offs = distinct**). Verdicts are cached and auditable
   (`dedup_v2_adjudications.jsonl`, `dedup_v2_decisions.csv`).
5. **Web-grounded second pass** on `unsure` pairs (gpt-5.5 + web search). Anything still unsure defaults
   to **distinct** (splits are visible and fixable; wrong fusions silently corrupt counts).
6. **Guarded clustering** — confidence-ordered union with a veto that blocks transitive chains from
   fusing incompatible names / disjoint firms without a direct same-edge (the anti-"blob" mechanism).

Outputs: `canonical_attorneys_v2*.csv`, `canonical_firms_v2.csv`, and mention→ID maps
(`dedup_v2_{attorney,firm}_map.csv`) that link every appointment to its canonical entity.

---

## 4. Demographics — `code/attorney_demographics.py`

Per canonical attorney, a web-grounded gpt-5.5 lookup fills gender (inferred from bios/photos, **not
name guessing**), birth year, undergraduate + law school, and bar-state admissions, each with sources
and a confidence. For old attorneys the human-coded gold demographics are reused; only genuinely-new
attorneys are researched. Lookups are cached/frozen for reproducibility. Coverage: gender ~97%, law
school ~98%, bar states ~99%, birth year ~52% (birth year is genuinely hard to source publicly).

---

## 5. The deliverable — `unified_mdl_database.xlsx`

Built by `code/build_final_database.py`. Eight tabs:

- **MDLs** — the 809-MDL master list.
- **Orders** — all pipeline-extracted leadership orders (old + new; `Corpus` column).
- **Appointments** — every appointee, linked to `Unified_Attorney_ID` + `Unified_Firm_ID`.
- **Attorneys** — the canonical (v2) roster + demographics.
- **Firms** — the canonical (v2) firm roster.
- **Gold_Appointments**, **Gold_Attorneys** — the human hand-coding, retained for reference.
- **Role_Comparison** — per-attorney LLM-vs-human appointment-type agreement (see §7).

---

## 6. Validation

Because MDL_new has no human coding, quality is established on the MDL_old MDLs, where the pipeline output
can be compared directly to the gold. All 201 old MDLs were run through the pipeline for this purpose.

**Full-gold accuracy** (`code/compare_roles_vs_gold.py`, matched at attorney × MDL):
- Identity recall **87.1%**, precision **86.8%**.
- Appointment-type exact-set agreement **77.4%**; per-role recall is high on the roles that carry the
  paper's argument — Management 96%, LeadCounsel 96%, Communications 95%, Fees 97% — with two documented,
  systematic convention gaps: the model **over-tags ClassCounsel** (77%; the lead-also-class convention),
  and **folds SettlementAdministration into Settlement** (6% recall on that label).
- `appointment_type_comparison.csv` flags every disagreeing (attorney × MDL) with the exact roles the
  LLM added vs. missed — usable both as a QA column and as the paper's role-agreement evidence.

**Dedup accuracy vs. the human canonicalization** (pairwise, over old-corpus identities):
precision **0.923**, recall **0.865**, F1 **0.893** — versus rules-only v1 at P 0.904 / R 0.587. The
residual precision gap is largely a benchmark ceiling (gold distinguishes people by middle initials that
are absent from the underlying text; a few gold labeling errors), not correctable error.

**Old-vs-new distribution comparison** (`code/dist_compare.py`): the two corpora differ (new MDLs are
smaller and more class-action-oriented), but a same-cases method panel (gold vs. our extraction on the
same MDLs) shows the *method* reproduces the gold distributions; the differences are population, not
pipeline. One caveat surfaced: pre-2010 leadership-heavy MDLs in the extracted corpus are under-covered
(~16 MDLs) because older court documents are harder to obtain/OCR — relevant only to time-trend analyses.

**Replication figures** (`replication_mdl/code/analysis_ours.ipynb`): the paper's figures regenerate
on this dataset for `old` / `new` / `both` via a scope switch, using the canonical IDs directly. The
central Monte-Carlo result — observed repeat co-appointment far exceeds a capacity-constrained random null
(p ≈ 0) — holds in every scope, independently reproduced by the extracted corpus.

---

## 7. Known limitations

- **By-reference tail:** a residual set of orders appoint a body "by reference" (e.g. "the Court confirms
  its appointment of the PSC as class counsel") with no citable docket; these stay flagged, not resolved,
  because inheriting a possibly-stale prior slate would inject wrong names.
- **Role conventions:** ClassCounsel over-tagging and Settlement/SettlementAdministration conflation, as
  quantified in §6 — both fixable at the prompt level if those distinctions matter to a given analysis.
- **Firm lineage vs. legal entity:** renames/mergers are merged into one lineage (e.g. Cohen Milstein
  Hausfeld & Toll → Sellers & Toll); analyses that need strict legal entities should split by era.
- **Older-document coverage** (§6) biases pre-2010 time trends downward in the extracted corpus.
- **Human gold is not error-free** and is itself an imperfect benchmark; a handful of gold labels are
  demonstrably wrong (documented in the audit).

---

*Reproducibility: model IDs and prompt fingerprints are recorded per extracted record; LLM adjudications
and demographics lookups are cached so re-runs are deterministic. Raw court PDFs and the OCR corpus are
not distributed via git (size); the pipeline regenerates all downstream artifacts from them.*
