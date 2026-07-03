"""Refinement stage: find court ORDERS hiding in the UNCLEAR bucket.

For each doc labelled UNCLEAR in type_labels.csv that is still in the working
corpus (present in filtered_files/), take the first N pages of text (default
N=3) -- from the OCR JSON in ocr/ when available (clean text incl. scanned
pages), else the PDF text layer. Then a cheap regex gate looks for the word
"order":

  - no "order" in the first N pages  -> leave it UNCLEAR (no LLM call)
  - "order" present                  -> gpt-5.4-mini reads those pages and
                                        decides whether the document IS a court order

Results stream to unclear_review.csv (NON-destructive; type_labels.csv is not
touched):

    relpath, n_chars, has_order, llm_is_order, final_label, reason

final_label is ORDER when the model confirms an order, else UNCLEAR. Resumable:
docs already in unclear_review.csv are skipped. Needs OPENAI_API_KEY in .env.

Usage:
    python refine_unclear.py --dry-run            # counts only, no API calls
    python refine_unclear.py --limit 60           # small metered sample
    python refine_unclear.py --workers 16         # full run
    python refine_unclear.py --all                # include UNCLEAR docs dropped by the filter
"""
import argparse
import csv
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import fitz  # PyMuPDF
from dotenv import load_dotenv

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(it, **kw):
        return it

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = os.path.join(ROOT, "files")
FILTERED = os.path.join(ROOT, "filtered_files")
OCR_DIR = os.path.join(ROOT, "ocr")
LABELS = os.path.join(ROOT, "type_labels.csv")
OUT_CSV = os.path.join(ROOT, "unclear_review.csv")
MODEL = "gpt-5.4-mini"
N_PAGES = 3
MAX_CHARS = 12000          # cap LLM input (first pages can be dense)
MAX_OUT_TOKENS = 2000
PRICE_IN, PRICE_OUT = 0.25, 2.00   # rough gpt-5-mini-class $/1M for the estimate

# words that flag a possible court order -- "order" + synonyms that title orders
# lacking the word "order" (Judgment, Opinion, Injunction, Decree...). Whole-word,
# so it won't match "border". The LLM still makes the final call on matches.
ORDER_RE = re.compile(
    r"\b(order(?:s|ed|ing)?|judgment|opinion|injunction|decree|mandate|adjudged|so\s+ordered)\b",
    re.I)

SYS = """You are given the first pages of a U.S. multidistrict-litigation (MDL) court document. Decide whether the document ITSELF is a court ORDER -- a ruling, opinion, judgment, or decision issued by the court (typically signed by a judge) -- as opposed to a motion, brief, memorandum, declaration, affidavit, notice, stipulation, transcript, exhibit, complaint, or other party filing.

A document that merely mentions, requests, or attaches an order is NOT itself an order (e.g. "Motion for an Order...", "Memorandum in support...", a proposed order attached as an exhibit). Judge only what the document is.

Return JSON {is_order: bool, reason: one short sentence}."""

SCHEMA = {"type": "object", "properties": {
    "is_order": {"type": "boolean"},
    "reason": {"type": "string"}},
    "required": ["is_order", "reason"], "additionalProperties": False}


def first_pages_text(rel, n):
    """First n pages of text, preferring the OCR JSON (clean text incl. scanned
    pages) and falling back to the PDF text layer. Returns (text, source)."""
    folder, fn = rel.split("/", 1)
    stem = fn[:-4] if fn.lower().endswith(".pdf") else fn
    jp = os.path.join(OCR_DIR, folder, stem + ".json")
    if os.path.exists(jp):
        try:
            d = json.load(open(jp, encoding="utf-8"))
            pages = sorted(d.get("pages", []), key=lambda p: p.get("page", 0))[:n]
            return "\n".join(p.get("text", "") for p in pages).strip(), "ocr"
        except Exception:
            pass
    try:
        with fitz.open(os.path.join(FILES, rel)) as doc:
            parts = [doc[i].get_text("text") for i in range(min(n, doc.page_count))]
            return "\n".join(parts).strip(), "pdf"
    except Exception:
        return "", "none"


def iter_unclear(mdls, include_dropped):
    want = set(mdls) if mdls else None
    with open(LABELS, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["llm_type"] != "UNCLEAR":
                continue
            rel = r["relpath"]
            if want and not (re.match(r"^(\d+)", rel) and re.match(r"^(\d+)", rel).group(1) in want):
                continue
            if not include_dropped and not os.path.exists(os.path.join(FILTERED, rel)):
                continue
            yield rel


def llm_is_order(client, text, proposed=False):
    user = text[:MAX_CHARS]
    if proposed:
        user = ("NOTE: this document's filename contains the word PROPOSED -- return "
                "is_order:true ONLY if the text shows it was actually entered/signed by a "
                "judge, not merely a party's proposed draft.\n\n") + user
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": SYS},
                  {"role": "user", "content": user}],
        response_format={"type": "json_schema",
                         "json_schema": {"name": "order_check", "strict": True, "schema": SCHEMA}},
        max_completion_tokens=MAX_OUT_TOKENS)
    d = json.loads(resp.choices[0].message.content or "{}")
    u = resp.usage
    return bool(d.get("is_order", False)), d.get("reason", ""), (u.prompt_tokens, u.completion_tokens)


def review_one(client, rel, n_pages):
    # Gate on the WHOLE document (the regex is free), not just the first pages -- an order whose
    # order-language appears past page 3 was previously missed. The LLM input stays bounded (MAX_CHARS).
    text, src = first_pages_text(rel, 10**9)
    has_order = 1 if ORDER_RE.search(text) else 0
    if not has_order:
        return [rel, src, len(text), 0, "", "UNCLEAR", "no order-language in document"], (0, 0)
    proposed = "proposed" in os.path.basename(rel).lower()
    try:
        is_order, reason, usage = llm_is_order(client, text, proposed)
    except Exception as e:  # noqa: BLE001
        return [rel, src, len(text), 1, "ERROR", "UNCLEAR", f"{type(e).__name__}: {str(e)[:100]}"], (0, 0)
    return ([rel, src, len(text), 1, str(is_order), "ORDER" if is_order else "UNCLEAR", reason], usage)


def apply_promotions():
    """Flip UNCLEAR -> ORDER in type_labels.csv for docs unclear_review.csv
    confirmed as orders. Idempotent; writes atomically. unclear_review.csv stays
    as the audit trail of why each doc was promoted."""
    if not os.path.exists(OUT_CSV):
        sys.exit(f"no {OUT_CSV} -- run the review first")
    promote = set()
    with open(OUT_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["final_label"] == "ORDER":
                promote.add(r["relpath"])

    with open(LABELS, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    header, data = rows[0], rows[1:]
    lt = header.index("llm_type")
    rp = header.index("relpath")
    flipped = 0
    for row in data:
        if row and row[rp] in promote and row[lt] == "UNCLEAR":
            row[lt] = "ORDER"
            flipped += 1

    tmp = LABELS + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(data)
    os.replace(tmp, LABELS)
    print(f"applied {flipped} UNCLEAR->ORDER promotions to type_labels.csv "
          f"({len(promote)} promoted in unclear_review.csv; already-ORDER skipped)")
    return 0


def already_done():
    done = set()
    if os.path.exists(OUT_CSV):
        with open(OUT_CSV, newline="", encoding="utf-8") as f:
            r = csv.reader(f)
            next(r, None)
            for row in r:
                if row:
                    done.add(row[0])
    return done


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mdls", help="comma-separated MDL numbers (default: all)")
    ap.add_argument("--workers", type=int, default=32,
                    help="concurrent LLM requests; raise for throughput (rate limits self-throttle via SDK retries)")
    ap.add_argument("--limit", type=int, help="only the first N not-yet-done docs")
    ap.add_argument("--pages", type=int, default=N_PAGES, help="first N pages to read (default 3)")
    ap.add_argument("--all", action="store_true", help="include UNCLEAR docs dropped by the filter")
    ap.add_argument("--apply", action="store_true",
                    help="apply unclear_review.csv ORDER promotions to type_labels.csv (no LLM)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.apply:
        return apply_promotions()

    n_pages = args.pages
    mdls = [s.strip() for s in args.mdls.split(",")] if args.mdls else None

    done = already_done()
    todo = [rel for rel in iter_unclear(mdls, args.all) if rel not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"UNCLEAR to review: {len(todo):,} (already done: {len(done):,}) | first {n_pages} pages | model {MODEL}")
    if args.dry_run or not todo:
        return 0

    load_dotenv(os.path.join(ROOT, ".env"))
    if not os.getenv("OPENAI_API_KEY"):
        print("missing OPENAI_API_KEY", file=sys.stderr)
        return 1
    from openai import OpenAI
    client = OpenAI(max_retries=5)

    new = not os.path.exists(OUT_CSV)
    f = open(OUT_CSV, "a", newline="", encoding="utf-8")
    w = csv.writer(f)
    lock = threading.Lock()
    if new:
        w.writerow(["relpath", "text_source", "n_chars", "has_order", "llm_is_order", "final_label", "reason"])
        f.flush()

    gated = order = stay = errs = tin = tout = n = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(review_one, client, rel, n_pages) for rel in todo]
        for fut in tqdm(as_completed(futs), total=len(futs), unit="doc", desc="refine"):
            row, (pin, pout) = fut.result()
            with lock:
                w.writerow(row)
                f.flush()
            n += 1
            tin += pin
            tout += pout
            if row[3] == 1 and row[4] != "ERROR":
                gated += 1
            if row[5] == "ORDER":
                order += 1
            elif row[4] == "ERROR":
                errs += 1
            else:
                stay += 1
            if n % 250 == 0:
                est = tin / 1e6 * PRICE_IN + tout / 1e6 * PRICE_OUT
                print(f"\n  [{n}] gated->LLM={gated} ORDER={order} stay-unclear={stay} err={errs} ~${est:.2f}")
    f.close()

    est = tin / 1e6 * PRICE_IN + tout / 1e6 * PRICE_OUT
    print(f"\nDONE: reviewed {n:,} | LLM-checked {gated:,} | promoted ORDER {order:,} | "
          f"stay UNCLEAR {stay:,} | errors {errs} | ~${est:.2f} | -> {os.path.relpath(OUT_CSV, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
