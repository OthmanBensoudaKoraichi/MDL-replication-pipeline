# MDL leadership-order pipeline — full method & codebase walkthrough

*Authoritative deep walkthrough of how ~41,000 MDL court-filing PDFs become the three
Airtable tables (Orders / Appointments / Attorneys), how every extracted variable is produced,
and how the system is evaluated against human gold coding.*

Companion docs: `README.md` (quick reproduction guide), `DATA_DICTIONARY.docx` (field dictionary +
verbatim live prompts), `VALIDATION_LOG.md` (batch lists, results, project state). This file is the
"why and how" narrative; those are the reference cards.

> **Run everything with the Framework Python** (plain `python3` is 3.9 and lacks deps):
> `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3`

---

## 0. The shape of the problem

We have a raw corpus `files/<MDL>/<doc>.pdf` (~700 MDLs, tens of thousands of PDFs). We want, for
each MDL, the **leadership-appointment orders** — orders where a judge appoints/removes/modifies
plaintiff- or defense-side counsel (lead/co-lead/liaison counsel, steering & executive committees,
PSC/DSC, Rule 23(g) class counsel) — coded into structured fields, plus the **people and firms**
appointed and **what role** each got.

The pipeline is a **clean DAG**: every stage is a pure function of the previous stage's durable
output, so the whole thing reproduces from `files/`. Cheap deterministic or `gpt-5.4-mini` stages do
broad winnowing; the expensive `gpt-5.5` model is spent only on the small set of documents that
survive the gate.

```
files/  ──1 count_pages──▶ page_counts.csv
        ──2 classify_type (gpt-5.4-mini)──▶ type_labels.csv
        ──3 filter_corpus──▶ filtered_files/        (hard links; drop junk)
        ──4 ocr_llamaparse (LlamaParse+Tesseract)──▶ ocr/<MDL>/<doc>.json
        ──5 refine_unclear (gpt-5.4-mini)──▶ type_labels.csv   (rescue mislabeled orders)
        ──6 confirm_orders (gpt-5.5) THE GATE──▶ order_status.csv
        ──7 trim_orders──▶ orders/<MDL>/<doc>.json  (cut at signature page)
        ──8 extract_orders (gpt-5.5)──▶ order_extractions.{jsonl,xlsx}   (THE 3 TABLES)
        ──9 resolve_motions (gpt-5.5)──▶ order_extractions.{jsonl,xlsx}  (follow cited motion/report)
utilities:  make_dd_docx.py (regenerates DATA_DICTIONARY.docx)   eval_vs_gold.py (scoring)
```

**Models in play (all OpenAI, via the `openai` SDK — *not* Claude):**
`gpt-5.4-mini` for the cheap high-volume judgments (stages 2 & 5); `gpt-5.5` for the accurate work
(stages 6, 8, 9); LlamaParse `fast` + Tesseract for OCR (stage 4). Stages 1, 3, 7 are deterministic.
`extract_orders.py` notes "*if gpt-5.5 404s, try gpt-5*" — **confirm these model IDs are enabled on
the API key before a billable full run.**

---

## 1. `count_pages.py` — page-count cache *(deterministic, free)*

Walks `files/` and writes `page_counts.csv` (`relpath,pages`) using PyMuPDF (`fitz`). A corrupt/
unreadable PDF gets `pages = -1` (never crashes the run; counted and reported, not fatal). Parallel
(`ProcessPoolExecutor`), idempotent, overwrites the CSV each run.

- **Variables:** `relpath` = path relative to `files/`; `pages` = `fitz.page_count` or `-1`.
- **Gotcha:** `pages = -1` is a *failure sentinel*, not a real count — stage 3 treats it as "corrupt"
  and drops the doc. The script must live in `code/` (ROOT is derived as its parent dir).

## 2. `classify_type.py` — TYPE classification *(gpt-5.4-mini)*

Labels every doc `order | motion | other | unclear` from **filename + page count only** (never reads
the PDF body). Streams to `type_labels.csv` (`relpath,pages,regex_type,llm_type`); resumable (skips
already-labeled relpaths).

- **Conservative by design:** "*NEVER put a document in 'other' if it could possibly be an order or a
  motion. When torn, choose 'unclear'.*" `other` is the **only droppable** type downstream, so this
  bias protects recall — a possible order is never silently discarded.
- **`regex_type`** is a deterministic keyword cross-check column only; it does **not** affect any
  keep/drop decision.
- **Gotcha:** label quality depends entirely on how descriptive filenames are. Failed API calls are
  written as `llm_type='ERROR:…'` and count as "done" on resume — to retry them you must remove those
  rows first. Audit the `other` bucket after a full run.

## 3. `filter_corpus.py` — build the working corpus *(deterministic, free)*

Hard-links the keepers from `files/` into `filtered_files/`. Dry-run by default; **`--apply`** to act.
Decision cascade (first match wins):

`docket-dump (filename regex)` ▶ `classify_error` ▶ `corrupt (pages≤0)` ▶ `other` ▶
`long_unclear (UNCLEAR & pages > --max-unclear-pages, default 50)` ▶ else **KEEP** (orders, motions,
short unclear). Survivors are de-duplicated by content **MD5**, scoped **per MDL** on
`(mdl, normalized basename)` — only within-MDL "(N)" copies (`X.pdf` vs `X (1).pdf`) collapse; a filing
cross-listed in two MDLs is kept under each (see §15a — this was corpus-wide and buggy before 2026-06-28).

- **Why hard links:** the filtered corpus costs ~no disk and `files/` is never mutated.
- **Gotcha:** correctness depends on `type_labels.csv` being **current** — any PDF added after
  stage 2 last ran has no label, defaults to `(-1,'UNCLEAR')`, hits the `corrupt` rule, and is
  dropped. Re-run stage 2 before filtering. De-dup is byte-identical only.

## 4. `ocr_llamaparse.py` — OCR to per-page text *(LlamaParse fast + Tesseract fallback)*

For each `filtered_files/<MDL>/<doc>.pdf` writes `ocr/<MDL>/<doc>.json` with per-page
`{page, chars, text, source}`. Docs are split into ≤10-page batches sent concurrently; any batch
LlamaParse fails on falls back to **local OCR** (embedded text layer if a page has ≥100 chars, else
Tesseract at 300 DPI). Maintains `ocr/_manifest.csv`. Resumable (skips non-empty existing JSON).

- **Provenance:** each page is tagged `llamaparse | text-layer | tesseract`; `fallback_pages` counts
  non-LlamaParse pages — a **data-quality flag** (high value = much text bypassed LlamaParse).
- **Full run:** use `--all --exclude-file exclude_mdls.txt --workers 24`. Default with no flags only
  does the 10-MDL sample. Needs `llamaparse_api_key` in `.env`; needs the Tesseract binary installed.
- **Gotcha:** re-run keys only on the JSON *existing and non-empty*; a stale/partial JSON is not
  detected — delete it to force a re-parse.

## 5. `refine_unclear.py` — rescue orders hiding in UNCLEAR *(gpt-5.4-mini)*

Second pass over `UNCLEAR` docs to recover real orders without re-running the whole classifier.
Reads the first 3 pages, applies a cheap whole-word **regex gate** (`order|judgment|opinion|
injunction|decree|…|so ordered`); only if the gate fires does it spend an LLM call asking "*is this
document itself a court ORDER?*". Non-destructive: results stream to `unclear_review.csv`. A separate
**`--apply`** pass (no LLM) flips confirmed `UNCLEAR→ORDER` in `type_labels.csv`.

- **`proposed` in the filename** triggers a stricter prompt (only count it as an order if the text
  shows a judge actually entered/signed it) — guards against proposed-order drafts.
- **Recall bound:** an order whose order-language appears only after page 3, or that uses none of the
  gate words, stays `UNCLEAR`. Two-phase by design — you must run `--apply` deliberately to commit.

## 6. `confirm_orders.py` — THE GATE *(gpt-5.5)* ← the precision filter

For every `ORDER`-labeled doc (and, with `--include-motions`, memo-endorsed motions matching a
disposition regex) the model applies two tests and the keep decision is computed **deterministically
in Python** so it can never drift from the prose:

- **TEST A — relevance:** does it appoint/remove/modify leadership or counsel (lead/co-lead/liaison,
  steering/executive committee, PSC/DSC, Rule 23(g) class counsel), or is it a generically-named
  order worth checking? Output enum: `leadership | generic_to_check | irrelevant`.
- **TEST B — executed:** did a judge actually sign/enter it? Output `doc_kind` (11-value enum) +
  `executed` bool + `needs_signature_check`.
- **Keep rule:** `retrieve = int(relevance != "irrelevant" AND doc_kind ∈ {executed_order,
  signed_stipulated_order, signed_proposed_order, endorsed_order})`. Only `retrieve=1` flows
  downstream.

Writes `order_status.csv` (`relpath,retrieve,relevance,doc_kind,executed,needs_signature_check,
confidence,reason,evidence`). Long docs (>14k chars) are sent as 4 labeled slices (head 6k + early-body
6k + middle 4k + tail 4k), not whole.

- **Scope note:** the SYS prompt (what actually governs) restricts to **leadership/counsel
  appointments only** and *excludes* pure attorney-fee / common-benefit / settlement-fee orders. (The
  module docstring's opening lines are stale on this point — trust the prompt.)
- **Gotchas:** `retrieve` ignores the `executed` bool (a wet-ink `executed_order` with
  `needs_signature_check` is still kept and queued for a human eyeball). Appending different
  `--model` runs into the same `--out` file mixes models. ERROR/MISSING_OCR rows are retried on rerun.

## 7. `trim_orders.py` — cut at the signature page *(deterministic, free)*

For each kept order, finds the **last** page with a signature marker and truncates there, dropping
trailing exhibits. Writes `orders/<MDL>/<doc>.json` (`text` = pages 1..sig joined) and `orders/_spans.csv`.

- **Three-tier cut:** (1) last page matching `SIG_RE` (`/s/`, `U.S.D.J.`, `United States District/
  Magistrate Judge`, `SO ORDERED`, `ORDERED, ADJUDGED`) → method `signature`; else (2) last page with
  bare word `judge` → `judge-word`; else (3) keep whole doc → `whole`.
- **Gotcha:** keys on the *last* match, assuming the genuine signature is final. A late "SO ORDERED"
  inside an attached prior order can push the cut too far; the `judge-word` fallback can over-cut.

## 8. `extract_orders.py` — STRUCTURED EXTRACTION *(gpt-5.5)* ← the heart

Per order, feeds the trimmed `orders/…json` text to `client.beta.chat.completions.parse(...,
response_format=MDLOrderOut)` (OpenAI native Pydantic structured output — no LangChain). Appends one
JSON record per order to `order_extractions.jsonl` (resumable), then `build_excel()` writes
`order_extractions.xlsx` (tabs: **Orders, Appointments, Attorneys**, + audit tabs `Dropped (Stage 6)`,
`Dropped (empty)`). `MAX_OUT_TOKENS=32000`, `--workers 8`.

**Pydantic schema = order-level fields + `Appointments: List[Appointee]`.** Out-of-vocabulary
`Order_Types`/`appointment_types` are silently dropped by field validators (controlled vocab enforced).

### 8a. How each ORDER-level variable is produced

| Field | How produced (prompt rule) |
|---|---|
| `MDL_No` | Model: "4–6 digit MDL number, digits only; prefer null over guessing." **Overridden** post-hoc by `canonical_ids()` from filename leading digits. |
| `Docket_No` | Model integer; **overridden** by `docket_from_filename()` — the filename docket is authoritative (corpus names files by docket). |
| `Order_No` | Recomputed by `canonical_ids()` as `<MDL>-<filename docket>` (e.g. `2434-65`). |
| `Date` | Issue/entry date, ISO `yyyy-mm-dd`; PACER header entry date preferred over signature date. |
| `Judge` / `Judge_Type` | Judge initials (1–4 chars); `Judge_Type` ∈ {`DJ`,`MJ`}; multiple signers → both types + "Multiple judges" in Notes. |
| `Contested` | True **only if apparent from the face of the order**: it makes/modifies appointments AND >1 attorney/firm sought the SAME appointment (competing applications) or it drew objections. No outside inference. |
| `Applications_Solicited` | True only if the order explicitly says the court invited/solicited applications. |
| `Resolve_Rule_23` / `Rule_23` | `Resolve_Rule_23` = a Rule 23 motion is resolved; `Rule_23` = Rule 23 is cited. |
| `MCL` | True if the text cites the Manual for Complex Litigation. |
| **`OU_Create`** | Integer count of **distinct organizational units the order CREATES for the first time** (must be named with "committee" or "counsel"). **Tuned to UNDER-count:** appointing to / naming / filling / re-filling / amending an *existing* unit = 0; only explicit establish/create text counts; when unsure, do not count. *(This is the 2026-06-26 conservative revision.)* |
| `OU_Terminate` | Units expressly abolished (rare). |
| `OU_Functions` / `OU_Duties_to_Nonclients` / `IRPA_Duties_to_Clients` / `Limit_Nonleader_Practice` | Booleans: functions specified for a unit / duties imposed toward non-clients / duties on individually-retained plaintiff attorneys / non-lead attorney practice restricted. |
| `OU_Plaintiff` / `OU_Defendant` | True if affected units are on that side. |
| **`Order_Types`** | List from a closed 15-term vocab `[LeadCounsel, Management, Communications, ClassCounsel, Discovery, Motions, Fees, Expert, Bellwether, Coordination, Settlement, Trial, SettlementAdministration, ProSe, Vetting]`. No generic words ("Appointment", "Leadership"). |
| `MDL_Type` | JPML classification; null if unknown. **NOTE: a *given*, already present in the Order table — not something we extract or prompt for at scale.** |
| `Needs_Motion_Reading` | True when the order **grants an appointment motion but doesn't name the appointees** (→ stage 9 resolves it); False when it names them; null if not an appointment order. |
| `Notes` | Freeform. |
| `Appointments_Count` | Derived in `build_excel` = number of appointee objects. |
| `Needs_Signature_Check` | From the stage-6 gate row, not the model. |
| `Possible_Duplicate` | Derived: flagged (never dropped) when an order shares (MDL, Date, normalized title) with another. |
| `Source_File` | The relpath, injected at write time. |

### 8b. How each APPOINTEE is produced (`Appointee` object → Appointments table)

`last_name`, `first_name`, `full_name` (the **full canonical name exactly as written** incl.
middle/initial/suffix — becomes the Attorneys `Canonical_Name`; null for firm-only),
`appointee_type` ∈ {`Individual`,`Firm`}, `firm`, `plaintiff_defendant`, `appointment_types`
(closed vocab = the 15 Order_Types **+ `LocalCounsel`**), `appoint`, `remove`, `interim`.

Key prompt rules:
- **"Mark Lanier of the Lanier Law Firm" → one `Individual`** (firm captured as the `firm` attribute),
  *not* a separate `Firm` row. The firm-level Appointment rows are **derived deterministically
  downstream** (see 8c) — this keeps model output compact and avoids token truncation on big rosters.
- **Role de-over-tagging:** a person listed *only* as a steering/executive committee member (PSC/PEC/
  DSC) is `Management` ONLY — do **not** also tag `LeadCounsel`.
- **Roster enumeration:** a visual N-row × 2-column roster must yield ~2N appointees, not N.
- **`interim`** is true for every appointee under a position/committee/structure labeled "interim";
  never inferred merely because an order is early/organizational — the word must be attached.
- **Attorneys-and-firms-only** *(2026-06-26 revision)*: exclude appointees who are clearly not lawyers/
  firms by title (CPA, accountant, economist, financial advisor, claims/notice/settlement
  administrator, guardian ad litem, Ph.D. expert, etc.). When in doubt that the appointee is a lawyer,
  do not include them.

### 8c. How the ATTORNEYS table and derived firm rows are produced (`build_excel`)

- **Derived firm Appointment rows:** for each order, one firm-level row per distinct normalized firm
  drawn from its individuals' `firm` attribute (carrying the UNION of those individuals' roles +
  the side/appoint/remove/interim of the first contributor); firms already emitted as standalone
  `Firm` appointees are skipped. `Appointment_ID` = `<Order_No>-<i>` (individuals) / `<Order_No>-F<j>`
  (firms). This expands the compact model output to the human convention (firms listed as appointees).
- **Attorneys roster (deduped):** individuals dedup by `('ind', norm(first), norm(last))` with
  `Canonical_Name = full_name`; firms by `('firm', norm_firm(firm))` (legal suffixes LLP/LLC/PC/…
  stripped). **Nickname/initial variants (Chris vs Christopher) intentionally do NOT auto-merge** —
  left for a manual `Canonical_Name`/`AKA` reconciliation step.
- **Demographic columns** (`Gender, Race, Birth_Year, Undergrad_School, Undergrad_Grad_Year,
  Law_School_Name, Law_Grad_Year, Bar_States, Sources, Notes, AKA_1..3`) are emitted **blank by
  design** — they are the target of the attorney-demographics lookup (a separate task), not model output.

### 8d. Critical operational gotchas (read before the full run)
1. **`DEFAULT_MDLS` (the 10-MDL sample, seed 281835) is the default** in `ocr_llamaparse.py`,
   `trim_orders.py`, `confirm_orders.py`, AND `extract_orders.py`. Running with no flags only
   processes those 10 MDLs. **For the full corpus pass `--all`** to stages 6→7→8 (and `ocr` stage 4;
   `resolve_motions` is already corpus-wide). `--all` derives every MDL from `type_labels.csv` /
   `orders/`, so you no longer hand-maintain an MDL list. *(2026-06-28: `--all` added.)*
2. Filename docket is treated as authoritative and silently overrides the model's docket — relies on
   the corpus naming convention; a misnamed file yields a wrong `Order_No`.
3. `keep_order()` (drop zero-appointee orders unless `Needs_Motion_Reading=True`) and the stage-6 gate
   apply **only to the XLSX, never the jsonl**, and `keep_order` **must run after stage 9**, or genuine
   `Needs_Motion_Reading` orders get dropped. So the correct order is 8 → 9 (stage 9 rebuilds the XLSX last).
4. Subjective fields (`Contested`, `OU_Create`, `interim`, LeadCounsel-vs-Management) lean on prompt
   adherence — spot-check against gold at scale.

## 9. `resolve_motions.py` — follow the cited motion / adopted report *(gpt-5.5)*

For orders flagged `Needs_Motion_Reading=True` with no appointees, it recovers the names from the
document the order points to:
- **`locate_motion`** — maps a docket the order cites (`[15]`, `(Doc. 12)`, `Dkt. 9`, "mot. #N" in the
  filename) to a `MOTION` doc in the **same MDL** with OCR; else a filename-keyword fallback (LOW
  CONFIDENCE).
- **`locate_report`** — if the order ADOPTS a **Special Master / Rule 53 report** (`REPORT_TRIGGER_RE`:
  adopt/approve/accept/confirm/overrule-objection near special-master/rule-53/report), picks the report
  with the highest subject-token overlap, and **OCRs roster exhibits on demand** (sibling `Doc N-M`
  exhibits whose filename matches chair/member/committee/slate/roster) via LlamaParse, caching to `ocr/`.

Reads the source with `gpt-5.5` (`MotionAppointees` schema, text truncated to 60k chars,
`MAX_OUT_TOKENS=16000`), folds appointees back onto the order, sets `Motion_Read_From` /
`Motion_Read_Result`, flips `Needs_Motion_Reading=False` (even if zero appointees found, so it's not
re-read), rewrites the jsonl atomically, and rebuilds the XLSX via the imported `extract_orders.build_excel`.

- **Gotchas:** only searches within the same MDL. Keyword/subject fallbacks are LOW CONFIDENCE (the
  rows to spot-check) and that confidence is printed but **not persisted** — capture the run log. A
  located-but-empty source looks identical to a silent miss.

## Utilities

- **`make_dd_docx.py`** *(deterministic)* — regenerates `DATA_DICTIONARY.docx`: pipeline overview,
  the four LLM prompts pulled **live** from the stage modules (so prompts can't drift from what runs),
  controlled vocabularies, and the field-by-field dictionary. The prompts are trustworthy; the
  pipeline table / model labels / vocab lists are hand-maintained constants — verify against the real
  stage code. Needs `python-docx`. (It `exec`-imports the stage modules to read their prompt strings.)

---

## 10. Evaluation methodology — `eval_vs_gold.py` *(deterministic, no LLM judge)*

Compares `order_extractions.jsonl` against the human gold CSVs in `csvs_current_dataset/`
(`Orders-Export view*.csv`, `Appointments-Grid view*.csv` — newest by mtime, BOM-tolerant). **Auto-scopes
to the intersection** of MDLs we extracted ∩ MDLs humans labeled (`--mdls` restricts further, for
held-out runs). Writes `eval/report{tag}.md`, `eval/metrics{tag}.json`, and discrepancy CSVs
(`appt_missing`, `appt_extra`, `role_disagreements`).

**Design principle: score SUBSTANCE, not spelling.** Names/firms are matched with cosmetic-tolerant
fuzzy logic so string differences (typos, middle initials, suffixes, first/last swaps, firm
granularity) are *not* penalized — we measure whether the right information was extracted.

### Matching
- **People** — `appointee_key = ('ind', last_norm, first_tok)`. `person_pair` matches if surnames are
  equal-tolerant (`_last_eq`: exact, or prefix with len≥4, or edit-distance ≤1 at len≥5) AND first
  initials are compatible (`_init_ok`) — **including the first/last SWAP** present in gold
  ("Saveri Richard" ↔ "Richard Saveri").
- **Firms** — `('firm', norm_firm)` (legal suffixes stripped). `firm_pair` matches on significant-token
  subset (either direction), or token-set Jaccard ≥ 0.5, or single-token edit-distance ≤1
  (pomeranz/pomerantz). **Representation-agnostic:** every individual's nonempty firm is *also*
  registered as a standalone firm entity on **both** sides — so a firm counts the same whether it
  appeared as its own row or only as an attorney's attribute.
- **`dedup_within`** — collapses fuzzy-duplicate appointees *within one source* before cross-source
  comparison (same person_pair/firm_pair logic), so gold double-entries don't inflate counts or
  create phantom misses.
- **Cross-source match** is greedy 1-to-1 within each `(mdl, type)`.

### Metrics, by tier (Appointments > Orders > Attorneys)
- **Tier 1 — Appointments (primary):**
  - **Identity recall / precision / F1** for Individuals, Firms, Combined. `recall = matched/gold`,
    `precision = matched/ours`, `F1 = 2PR/(P+R)`, each with a **95% Wilson CI**.
  - **Role Jaccard (partial credit)** — mean over matched individuals of `|roles∩|/|roles∪|`
    (1.0 identical, 0.0 disjoint). Reported **raw** and **reconciled** (the one documented codebook
    fix: gold `coordination → management`, the Defense-Coordination-Committee call).
  - **Side agreement %** (Plaintiff/Defendant on matched people).
  - **soft-F1** — like identity F1 but each matched person contributes its (reconciled) role-Jaccard
    instead of a full point, so "found but half-mis-roled" counts ~0.5. The single role-weighted headline.
- **Tier 2 — Orders:** identity recall/precision/F1 on `(mdl, docket)` keys (gold restricted to
  appointment-bearing orders; **exact** key match, not fuzzy) + **per-field agreement** on matched
  orders: `Order_Types` (exact set), `OU_Create` (integer), and boolean equality for `Contested`,
  `Rule_23`, `OU_Functions`, `Limit_Nonleader_Practice`, `IRPA_Duties_to_Clients`,
  `OU_Duties_to_Nonclients`; plus `Order_Types` Jaccard (raw + reconciled). `Judge`/`Date` are
  metadata-only (counted only when gold is nonempty).
- **Tier 3 — Attorneys:** aliased to Tier-1 individuals (distinct people). Exact canonical names +
  demographics explicitly out of scope (cosmetic).

### Why precision/recall and not "accuracy"
For **identity** (which people/firms/orders are present) the set of true negatives is unbounded — there
is no meaningful "number of correctly-omitted appointees" — so accuracy is undefined and recall (did we
find the real ones?) + precision (are ours real?) are the right pair. **Accuracy *is* used** for
**field values on matched items** (`Contested`, `OU_Create`, …), where the value space is closed and
agreement rate is exactly the quantity of interest.

### Eval gotchas
- Scope is the intersection — MDLs present on only one side are silently ignored (coverage gaps don't
  show as misses; that's why we also track per-MDL).
- Fuzzy thresholds can occasionally over-merge common surnames or short firm tokens; greedy matching is
  iteration-order-dependent when multiple candidates are compatible.
- Roles outside the 16-term `ROLE_VOCAB` are dropped from both sides before Jaccard.
- `keep_order` is applied to our records before scoring (mirrors stage 8).

---

## 11. Latest validation results

From `VALIDATION_LOG.md` (FIXED pipeline = compact extraction + firm rows derived in `build_excel`).
**These numbers predate the 2026-06-26 prompt revisions and the latest gold corrections — they are
being refreshed** (re-extract dev+validation MDLs, re-run eval vs corrected gold).

| set | indiv R/P/F1 | firms F1 | orders F1 | notes |
|---|---|---|---|---|
| valid (≥3-order, ~83% of all appts) | 86.4 / 86.4 / 86.4 | 87.2 | 90.3 | hard end; roles 90.4, side 100 |
| small (1–2-order, ~17% of appts) | 97.1 / 86.3 / 91.4 | 96.1 | 86.0 | easy end; median per-MDL recall 100% |
| **population-weighted estimate** | **~88 / ~86 / ~87** | ~94–96 | ~89 | the headline for the paper |

**Key finding:** precision is robust (~86–96%); residual recall gaps are *characterized* (by-reference/
exhibit rosters, a few order-coverage misses), not random model error. The dev/validation batches and
their seeds are recorded in `VALIDATION_LOG.md` — 130 of 185 gold MDLs used so far.

## 12. Known limitations / future improvements *(validate any fix on a FRESH set)*
- By-reference / exhibit rosters that resolve to ~0 (extend the stage-9 resolver further).
- A few order-coverage misses (gold orders not extracted).
- No truncation-detection safety net (flag any extraction that hits the output-token cap).
- 16 `Order_Count=0` MDLs in `MDL_old.csv` are untested negative controls (pipeline should yield ~0).

## 13. Pre-full-run hardening (2026-06-28)

Code changes made before the full-corpus run (all verified by `py_compile` + a no-API `--excel-only`
rebuild and `--all`/`--dry-run` smoke tests):

- **Higher worker defaults** (CLI-overridable; rate limits self-throttle via SDK retries): classify
  32→48, refine 16→32, confirm 16→32, extract 8→24, resolve 6→16.
- **`--all` flag** on `confirm_orders` / `trim_orders` / `extract_orders` — process every MDL in
  `type_labels.csv` / `orders/` instead of the 10-sample. (`ocr` already had `--all`.)
- **`--model` + fail-fast preflight** on `confirm_orders` / `extract_orders` / `resolve_motions`: a
  1-token ping confirms the model id resolves *before* spawning workers, with an automatic `gpt-5`
  fallback — no more discovering a bad model id mid-run.
- **`confirm_orders` docstring** corrected to match the live prompt (leadership-appointment orders
  ONLY; fees/common-benefit/settlement-only orders are NOT relevant).
- **Stage 8→9 guard:** `build_excel` prints a loud warning if any kept order is still
  `Needs_Motion_Reading=True` with no appointees — i.e. stage 9 (`resolve_motions`) hasn't fetched
  its cited motion/report yet. The workbook is not final until that warning clears.
- **Within-MDL same-date duplicate FLAG (non-destructive):** every per-order appointment row is KEPT —
  the gold tables' convention (one row per appointment event) — and de-duplication is left to a later
  data-cleaning step. The Appointments column `Possible_Duplicate_Appointment` only MARKS the same
  appointee+role+side appointed in >1 order on the SAME DATE (a likely duplicate/amended order), so the
  cleaning pass has the candidates ready; later-date reappointments are not flagged. Nothing is dropped
  and `Appointments_Count` stays the model's per-order appointee count. *(Decided 2026-06-29: match
  gold's no-dedup convention; the earlier auto-collapse was reverted. The eval still dedups both sides
  symmetrically for fair scoring, so this doesn't affect the validation numbers.)*

**Resolver enhancement (built) — the 30 unresolved `Needs_Motion_Reading` orders.** `resolve_motions`
now classifies each flagged order deterministically (no LLM) after the motion/report path fails:
- **Reappointment inheritance (6 orders):** an order that *renews/reappoints* a body names no one and
  points at a prior appointing order. The resolver follows the **cited prior-order docket** (e.g.
  `2522-436` → "Docket No. 64") and **inherits that order's slate from our own jsonl** — deterministic,
  no LLM. Title-confirmed reappointments without a resolvable docket fall back to the most-recent prior
  matching order. Every inherited slate is tagged in `Notes` + `Motion_Read_Result` and flagged for
  review. *Validated on gold `2522-436`: recall 100% (7/7), precision 88% (1 stale — Christopher Walsh,
  removed by a cross-case substitution order not in our corpus: the documented limitation).*
- **Fee/settlement exclusion (19 orders):** pure fee-award / settlement-approval orders that appoint no
  one are dropped (flag cleared → `keep_order` removes them as non-appointment orders). Distinguished
  by title (fee/approval keywords AND no appoint/reappoint), NOT by `Order_Types` (which is unreliable
  here — fee-approval orders carry `ClassCounsel`, common-benefit-committee reappointments carry `Fees`).
- **Still unresolved (5 orders):** genuine appoint-by-reference orders with no findable motion — stay
  flagged for a human. `resolve_motions.py --dry-run` prints the full plan (kind per order).

## 14. Attorney + firm entity resolution — `code/dedup_attorneys.py`

Builds the **canonical roster** (one row per real person/firm) from the raw appointees in the jsonl —
the unit the demographics lookup and the "who leads" analysis need. **Deterministic-first, LLM only on
the ambiguous residual** (`--llm`, default off), so the bulk is reproducible and auditable.

- **Blocking:** last-name Soundex + last[:4] (compares only plausible pairs, not N²).
- **Scoring:** surname must match; first names relate as exact / nickname (built-in dictionary) /
  given-token-subset (`W. Mark` ↔ `Mark`) / initial / edit≤1. **Auto-merge (STRONG) requires an EXACT
  surname** + compatible first name; a surname that matches only *phonetically or by edit≤1* must also
  share a firm or MDL, else it drops to the **review bucket** — this is the guard against over-merging
  look-alike surnames (Hellums vs Hellmich, McCarley vs McCauley), which is the dangerous error (it
  undercounts distinct leaders).
- **Context disambiguator:** shared firm / shared MDL gates the weaker matches.
- **Outputs:** `canonical_attorneys.csv` (Attorney_ID, Canonical_Name, AKA_1..3, firms, MDLs, roles,
  confidence, + blank demographic columns), `canonical_firms.csv`, `attorney_merge_audit.csv` (every
  merge + reason, to eyeball precision), `attorney_review_candidates.csv` (the weak pairs for `--llm`/human).
- **Prototype (current 130-MDL roster):** 4,074 mentions → 1,461 exact-normalized → 1,388 canonical;
  73 high-precision fuzzy merges; 28 review pairs; firms 4,291 → 751.

**Demographics lookup — `code/attorney_demographics.py`:** per canonical attorney, one web-grounded LLM
lookup (name + firms + MDLs for disambiguation) fills `Gender, Birth_Year, Undergrad/Law school` +
grad years, `Bar_States` with **source URLs + confidence**; gender is taken from a bio/pronouns, never
inferred from the first name; unknown stays blank; results are cached (frozen) and resumable; dry-run by
default. Both dedup and demographics run during the **MDL_new full-corpus extraction** (see
`FULL_RUN_PLAN.md`).

## 15. Audit findings, corrections, and limitations (for the paper)

A 2026-06-28 adversarial audit (8 review dimensions, every finding independently re-verified against the
code) produced 16 high + 25 medium confirmed issues. This section is the honest record a referee needs.

### 15a. Code bugs fixed (corpus-affecting; re-run the pipeline to realize them)
- **filter_corpus dedup was corpus-wide, not per-MDL** — it dropped 276 byte-identical files across
  *different* MDL folders (227 ORDER docs), removing orders from their true MDL and misattributing them
  to the alphabetically-first one. Now keyed on `(mdl, normalized basename)`: only within-MDL "(N)"
  copies collapse. (Re-run `filter_corpus --apply`; the previously-dropped cross-MDL ORDERs re-enter and
  need OCR/gate.)
- **Fee-exclusion regex dropped real "Approving Class Counsel" orders** — the bare token `class` in
  resolve_motions' `FEE_DROP_TITLE_RE` matched Rule-23 class-counsel *appointment* orders. Now the
  approval branches require `settlem…`; class-counsel orders are no longer dropped.
- **Within-MDL same-date duplicates are FLAGGED, not collapsed** (decided 2026-06-29): all per-order
  rows are kept (gold convention) and `Possible_Duplicate_Appointment` marks same-date repeats for a
  later data-cleaning pass. The earlier auto-collapse + phantom-drop was reverted at the user's request.
- **Reappointment inheritance** now parses dates and never inherits from an order dated on/after the
  reappointment; the no-docket fallback requires a parseable strictly-earlier date.
- **Attorney/firm dedup hardened** — single-token given-name subsets are context-gated (not auto-merged),
  and firm merges require ≥2 shared significant tokens with order-insensitive blocking (fewer over-merges).

### 15b. Transparency/reproducibility fixes — DONE 2026-06-28
- **Provenance column** added to Orders + Appointments tables (`extracted | motion-read | report-read |
  inherited-reappointment(verify) | excluded-fee`), set by extract (default `extracted`) and stamped by
  resolve_motions per resolution kind, with low-confidence resolver paths tagged.
- **Reproducibility recording**: each jsonl record now carries `_model` + `_prompt_sha`; the run prints
  the model id, prompt fingerprint, and openai SDK version.
- **`refine_unclear`** now runs its order-language gate over the WHOLE OCR text, not just the first 3
  pages (an order whose language appears later is no longer missed; the LLM input stays bounded).
- **`dedup_attorneys --llm`** hardened: a system role, structured output with a confidence + an explicit
  abstain (merge only on high/medium confidence), and a persisted decision log (`attorney_llm_adjudications.csv`).

### 15b-cont. Still queued
- **Determinism**: `temperature=0`/seed are NOT force-set (reasoning models reject the param and the live
  ids are untested here) — enable per call site once model support is confirmed; the `gpt-5` fallback is
  printed (recorded), not silent.
- **Eval coverage (tied to the reporting decisions below)**: report *unconditional* recall (absent gold
  MDLs/orders = recall 0); dedup our side on the exact key only; lead with RAW role-Jaccard; enforce a
  held-out MDL manifest. — to do alongside §15c reporting decisions.
- **confirm_orders** should emit explicit `MISSING_OCR` rows for motions skipped by the disposition
  pre-filter; **OCR fallback fraction** should be surfaced per doc downstream.

### 15c. Methodology decisions — RESOLVED (2026-06-28), the methods-and-limitations backbone

Co-author decisions on the 19 audit-raised methodology questions. These are what the paper should state.

**Validation & quality.**
- **Backtest, not new-set hand-coding.** MDL_new (the analysis set) has no human gold, so quality is
  validated by *backtesting on the gold MDLs*. On a random 20 of the 130 gold MDLs: individuals
  **F1 95.1** (R 95.3 / P 94.9), firms 93.9, orders 89.6, role-Jaccard 94.0. Caveat to disclose: 3 of
  the 20 were prompt-development MDLs, so this is not pristinely held-out; the strictly-blind figure is
  ~87% F1. MDL_new quality is this estimate *transferred* — state that explicitly.
- **Matching-sensitivity (disclose the technique).** Identity matching is cosmetic-tolerant (typos,
  initials, first/last swaps). Under **exact-key** matching the same backtest gives individuals
  **F1 91.6** vs 95.1 fuzzy — so the tolerance contributes ~3.5 pts; the result is robust. Report both;
  `eval_vs_gold.py --strict` reproduces the exact-match number.
- **No second coder / no κ (co-author decision).** The gold is single-coder; we will *not* double-code.
  Disclose this as a limitation and that subjective-field agreement is model-vs-one-coder, not chance-
  corrected. The single documented reconciliation (coordination→management) is a codebook entry.
- **Gold is not infallible.** Disclose that the human gold contains errors (e.g. MDL 2848, where 11
  plaintiff names were mis-filed under a defendants'-proposal docket); some scored "misses" are gold
  mistakes. The `appt_missing/extra` discrepancy CSVs are published for inspection.
- **No gate-drop audit (co-author decision).** The gate drops ~79% of docs and its corpus-wide false-
  negative rate is not separately measured; disclose as a limitation.
- **Headline = the random sample** (no arbitrary big-/small-MDL mixing weight); strata also reported.

**Measurement constructs (stated as-is, with honest labels).**
- **`Contested`** is kept as defined — true only from the face of the order; disclose it as a floor on
  contestation (off-record contests are not captured). *Not renamed* (co-author decision).
- **`OU_Create`** is intentionally conservative: the model tends to over-count organizational units
  relative to human coders, so the prompt instructs it to count only units the order itself CREATES.
  This aligns it with the human convention; disclose the counting rule.
- **Committees = `Management`.** Steering/executive committees (PSC/PEC/DSC) are coded `Management`, and
  committee *tier/hierarchy is not captured* — a stated codebook convention, not an omission.
- **`Applications_Solicited` and `Interim` are coded from THIS order's text** ("as stated in this
  order") — a floor; a separate earlier solicitation order, or a later order making an interim
  appointment permanent, is not reconciled across the MDL. Labeled as such in the data dictionary.
- **Scope = formal appointment orders only.** Pure attorney-fee / settlement-approval orders are
  excluded (they appoint no one); fee/common-benefit *committee appointments* are kept. State the scope.

**Reading, identification, reproducibility.**
- **Orders are read in full to the signature.** Stage 7 trims at the judge's signature (1,945/2,486 at a
  real signature marker, the rest kept whole), and the extractor reads the entire trimmed text — no
  truncation. (The 4-slice windowing is only the cheap *relevance gate*, which does not limit extracted data.)
- **Filename type-classifier measured (D10).** Filename-only labels agree 78% with a body re-read on a
  100-doc sample, but **0/100 were recall-critical** (no real order/motion was mislabeled to the only
  droppable type, "other"); the disagreement is harmless type-noise. Reported with `classify_error_sample.csv`.
- **Filename docket is authoritative but mismatches are flagged** (`Docket_Mismatch`) rather than silently
  overriding — filenames are reliable in this corpus; the flag surfaces the rare misnamed file.
- **Versions frozen & reported.** Model ids (gpt-5.4-mini / gpt-5.5), the extraction prompt hash, and the
  openai SDK version are recorded per record; OCR is LlamaParse `fast` + Tesseract. The published tables
  are built from the archived `ocr/` snapshot on disk (pin `version='latest'` to a dated version, and
  enable `temperature=0`/seed, once your model is confirmed to support them).
