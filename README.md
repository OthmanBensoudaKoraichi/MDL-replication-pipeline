# Who Leads in Mass Litigation? Evidence from MDL — replication materials

Code and data for *Who Leads in Mass Litigation? Evidence from MDL* by Othman Bensouda Koraichi,
Matthew Brundage, Gabriel Faria Bernardes, David Freeman Engstrom, C. Scott Hemphill, Brianne
Holland-Stergar, David L. Noll, and Adam Zimmerman.

The paper studies who gets appointed to plaintiffs' leadership in federal multidistrict litigation
(lead and liaison counsel, steering and executive committees, class counsel). This repository contains
the pipeline we used to build the appointment dataset from court orders, the dataset itself, and the
notebook that produces the paper's figures. Appendix A of the paper describes how the dataset was
built and validated; this README covers how to run things.

## Contents

| Path | What it is |
|---|---|
| `unified_mdl_database.xlsx` | The final dataset (see below). |
| `code/` | The pipeline scripts. |
| `PROMPTS.md` | Every prompt sent to a language model, copied from the code by `code/make_prompts_md.py`. |
| `MDL_merged.csv` | The 809 MDLs established between 2002 and 2026. |
| `csvs_current_dataset/` | The hand coding for about 200 MDLs (Orders, Appointments, Attorneys). |
| `gold_mdl_split.csv` | Which hand-coded MDLs were used during development and which 55 were held out for validation. |
| `order_extractions.jsonl`, `.xlsx` | Raw extraction output, one record per order. |
| `canonical_attorneys_v2_demographics.csv`, `canonical_firms_v2.csv` | Attorney and firm identities after name resolution. |
| `dedup_v2_*` | Name-resolution inputs, cached model decisions, and the name-to-ID maps. |
| `demographics_cache_v2.jsonl` | Cached attorney biography lookups. |
| `appointment_type_comparison.csv` | Role-by-role comparison of pipeline vs. hand coding for each attorney and MDL. |
| `replication_mdl/datasets_ours/` | The same dataset as CSVs, one file per workbook tab. |
| `replication_mdl/` | The figure notebook and the generated figures. |

The court documents themselves (about 41,000 PDFs) and their OCR text are too large for git and are
not included.

### The dataset

`unified_mdl_database.xlsx` has one tab per table:

- **MDLs**: the 809 MDLs with docket metadata.
- **Orders**: leadership orders (one row per order), with the source file each was extracted from.
- **Appointments**: one row per appointee per order. `Unified_Attorney_ID` and `Unified_Firm_ID` link
  to the Attorneys and Firms tabs.
- **Attorneys**, **Firms**: one row per resolved identity, with the name variants merged into it.
  Attorneys also carry gender, birth year, schools, and bar admissions where we could find them.
- **Gold_Appointments**, **Gold_Attorneys**: the hand coding, for reference.
- **Role_Comparison**: the contents of `appointment_type_comparison.csv`.

The `Corpus` column marks whether a row comes from an MDL in the hand-coded set (`old`) or not (`new`).
Both were coded by the same pipeline.

Each tab is also saved as a CSV in `replication_mdl/datasets_ours/` (`appointments.csv`, `firms.csv`,
`gold_attorneys.csv`, and so on), for anyone not using Excel. The figure notebook reads these CSVs.

## Setup

Python 3.12.

```bash
pip install -r requirements.txt
brew install tesseract   # OCR fallback, only needed for step 4
```

API keys go in a `.env` file at the repository root (see `.env.example`): `OPENAI_API_KEY` for the
GPT-5.4-mini and GPT-5.5 calls, and `llamaparse_api_key` for OCR.

## Running the pipeline

To rebuild from the documents, put the PDFs in `files/<MDL number>/` and run the steps in order. Each
step reads the previous step's output and caches what it has already done, so an interrupted run can be
restarted and only the remaining documents will be sent to the API.

```bash
python3 code/count_pages.py                        # 1. page counts
python3 code/classify_type.py                      # 2. order / motion / other (GPT-5.4-mini)
python3 code/filter_corpus.py --apply              # 3. drop non-orders and duplicates
python3 code/ocr_llamaparse.py --all --workers 24  # 4. OCR (LlamaParse, Tesseract fallback)
python3 code/refine_unclear.py --all --apply       # 5. reclassify unclear documents from their text
python3 code/confirm_orders.py --all --model gpt-5.5   # 6. keep only leadership orders
python3 code/trim_orders.py --all                  # 7. cut each order at the judge's signature
python3 code/extract_orders.py --all --model gpt-5.5   # 8. extract appointees and roles
python3 code/resolve_motions.py                    # 9. follow orders that appoint "by reference"
```

Then resolve names, add demographics, and build the workbook:

```bash
python3 code/build_allextracted_corpus.py   # combine extractions into one file for name resolution
python3 code/dedup_v2.py --stage all        # resolve attorney and firm names (GPT-5.5, web search for unclear pairs)
python3 code/attorney_demographics.py --apply \
    --in-csv canonical_attorneys_v2.csv \
    --out-csv canonical_attorneys_v2_demographics.csv \
    --cache demographics_cache_v2.jsonl
python3 code/compare_roles_vs_gold.py       # appointment_type_comparison.csv
python3 code/build_final_database.py        # unified_mdl_database.xlsx
python3 code/export_csvs.py                 # the same tabs as CSVs in replication_mdl/datasets_ours/
```

`code/dedup_v2_reverify.py` re-checks three kinds of borderline name matches with a web search; after
running it, run `dedup_v2.py --stage cluster` again. The model decisions behind the released files are
committed in the `dedup_v2_*` and `demographics_cache_v2.jsonl` caches, so these steps only call the API
for pairs or attorneys that aren't already cached.

## Figures

Open `replication_mdl/code/analysis_ours.ipynb`, set `SCOPE` to `"both"` (the full dataset), `"old"`, or
`"new"`, and run all cells. Figures are written to `replication_mdl/figures_ours/<scope>/`.
`replication_mdl/code/analysis.ipynb` is the earlier notebook that ran on the hand-coded data only
(`replication_mdl/datasets/`).

## Validation

Appendix A, Part XI reports how the pipeline compares with the hand coding on the 55 hand-coded MDLs
that were not used during development (listed in `gold_mdl_split.csv`). At the attorney × MDL level,
recall is 90.6% and precision is 93.3%. Agreement on lead counsel and steering-committee roles is
κ = 0.92 and 0.90. To rerun the comparison:

```bash
python3 code/eval_vs_gold.py --tag heldout55 \
    --mdls "$(awk -F, '$2=="heldout"{print $1}' gold_mdl_split.csv | paste -sd, -)"
```

The output goes to `eval/`. The committed `eval/report_heldout55.md` is the run behind Table 2.

## License

MIT. See `LICENSE`.
