# MDL Leadership Data Pipeline — Replication Materials

Replication code and data for **"Who Leads in Mass Litigation? Evidence from MDL."**

This repository turns a corpus of MDL (multidistrict-litigation) court-document PDFs into a structured,
deduplicated, demographically-enriched dataset of **plaintiff leadership appointments** (lead/liaison
counsel, steering/executive committees, Rule 23(g) class counsel), and reproduces the paper's figures.

**Read [`METHODOLOGY.md`](METHODOLOGY.md) first** — it is the self-contained account of what the pipeline
does and how it was validated. [`METHOD.md`](METHOD.md) is the deep stage-by-stage code reference;
[`VALIDATION_LOG.md`](VALIDATION_LOG.md) is the dated build/validation record.

## What's here

- **`code/`** — the full pipeline (document → data), the LLM-adjudicated deduper, demographics, the
  deliverable builders, and the evaluation harnesses.
- **`unified_mdl_database.xlsx`** — **the deliverable.** All-extracted (old + new) leadership dataset,
  deduped and demographically enriched, with the human gold coding and an LLM-vs-human role comparison as
  reference tabs (8 tabs: MDLs, Orders, Appointments, Attorneys, Firms, Gold_Appointments,
  Gold_Attorneys, Role_Comparison).
- **`canonical_attorneys_v2_demographics.csv`, `canonical_firms_v2.csv`** — the canonical rosters.
- **`appointment_type_comparison.csv`** — per-attorney LLM-vs-gold appointment-type agreement flag.
- **`MDL_merged.csv`** — the 809-MDL master list (old + new).
- **`csvs_current_dataset/`** — the human hand-coded gold (Orders / Appointments / Attorneys).
- **`replication_mdl/`** — the paper's replication notebook adapted to this dataset
  (`code/analysis_ours.ipynb`, scope switch old/new/both) + the generated figures (`figures_ours/`).

**Not distributed via git** (size): the raw PDFs (`files/`), the OCR corpus (`ocr/`), the working corpus
(`filtered_files/`), and large regenerable label files (`page_counts.csv`, `type_labels.csv`,
`order_status.csv`). The pipeline regenerates every downstream artifact from `files/`. **`.env` is never
committed.**

## The pipeline (document → data)

Deterministic DAG; each stage is a pure function of the previous stage's durable output. Models:
gpt-5.4-mini (classification), gpt-5.5 (gate/extraction/resolution), LlamaParse (OCR).

```
  files/                 --1 count_pages----> page_counts.csv
  + page_counts.csv      --2 classify_type--> type_labels.csv               (gpt-5.4-mini)
  + type_labels.csv      --3 filter_corpus--> filtered_files/               (drop + dedup)
  filtered_files/        --4 ocr_llamaparse-> ocr/<MDL>/<doc>.json          (LlamaParse + Tesseract)
  type_labels + ocr/     --5 refine_unclear-> type_labels.csv               (gpt-5.4-mini)
  ocr/ + type_labels     --6 confirm_orders-> order_status.csv  THE GATE    (gpt-5.5)
  ocr/ (retrieve=1)      --7 trim_orders----> orders/<MDL>/<doc>.json       (deterministic)
  orders/                --8 extract_orders-> order_extractions.{jsonl,xlsx}(gpt-5.5)
  order_extractions      --9 resolve_motions-> order_extractions.{jsonl,xlsx}(gpt-5.5)
```

Then, on the extracted corpus:

```
  order_extractions.jsonl  --> build_allextracted_corpus.py --> dedup_v2.py       (LLM-adjudicated dedup)
  canonical_*_v2 + gold    --> seed_v2_demographics + attorney_demographics.py    (web-grounded demographics)
  everything               --> build_final_database.py       --> unified_mdl_database.xlsx
  vs gold                  --> compare_roles_vs_gold.py       --> appointment_type_comparison.csv
```

## Setup

```bash
python3 -m pip install -r requirements.txt
# OCR (stage 4) also needs the Tesseract binary as a fallback: brew install tesseract
```

Create `.env` in the project root (never committed):

```
OPENAI_API_KEY=...        # gpt-5.4-mini (2,5) and gpt-5.5 (6,8,9, dedup, demographics)
llamaparse_api_key=...    # LlamaParse OCR (stage 4)
```

## Reproduce

Document→data pipeline (regenerates from `files/`, which you must supply):

```bash
P=python3
$P code/count_pages.py
$P code/classify_type.py
$P code/filter_corpus.py --apply
$P code/ocr_llamaparse.py --all --workers 24
$P code/refine_unclear.py --all --apply
$P code/confirm_orders.py --all --model gpt-5.5
$P code/trim_orders.py --all
$P code/extract_orders.py --all --model gpt-5.5
$P code/resolve_motions.py
```

Dedup → demographics → final workbook:

```bash
$P code/build_allextracted_corpus.py
$P code/dedup_v2.py --stage all              # candidates → LLM adjudicate → web → cluster → gold-gate
$P code/seed_v2_demographics.py
$P code/attorney_demographics.py --in-csv canonical_attorneys_v2.csv \
     --out-csv canonical_attorneys_v2_demographics.csv --cache demographics_cache_v2.jsonl --apply
$P code/build_final_database.py              # -> unified_mdl_database.xlsx
$P code/compare_roles_vs_gold.py             # -> appointment_type_comparison.csv (LLM-vs-gold role flag)
```

Figures — open `replication_mdl/code/analysis_ours.ipynb`, set `SCOPE` to `"old" | "new" | "both"`,
Run All (writes `replication_mdl/figures_ours/<scope>/`).

Billable stages are **resumable** — re-running only processes what isn't already cached.

## Headline validation (against the human gold, all 201 old MDLs)

- Extraction identity: recall **87%**, precision **87%** (attorney × MDL).
- Appointment-type agreement: **77%** exact set match; 94–97% recall on the core leadership roles.
- Dedup (LLM-adjudicated) vs. human canonicalization: precision **0.92**, recall **0.87**, F1 **0.89**.
- Central result (repeat co-appointment ≫ chance, Monte-Carlo p ≈ 0) reproduces in old, new, and both.

See [`METHODOLOGY.md`](METHODOLOGY.md) §6 for the full validation and known limitations.
