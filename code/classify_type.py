"""Classify every document's TYPE from its filename + page count, using
gpt-5.4-mini. Four categories:

    order    - a ruling/decision issued BY THE COURT
    motion   - a request filed BY A PARTY asking the court to act
    other    - CLEARLY neither an order nor a motion (declaration, transcript,
               exhibit, brief, notice, letter, complaint, answer, ...)
    unclear  - the filename is ambiguous/uninformative, or it COULD be an order
               or a motion but cannot be told apart

This is the type signal that drives the page filter: orders, motions and
UNCLEAR docs are kept at any length; only 'other' is dropped past a page
threshold. The bias is deliberately conservative -- a document is sent to
'other' only when the filename clearly rules out order/motion; otherwise it
goes to 'unclear' so we never drop a possible order/motion.

It judges ONLY document type, never relevance (the relevance call is what the
old step-1 filter got wrong). Output is slim: {type}.

Streams to filtered_files/type_labels.csv as it goes (resumable: already-labeled
docs are skipped). Token usage + a cost estimate are printed periodically.

Usage:
    python classify_type.py --dry-run
    python classify_type.py --limit 500      # metered batch
    python classify_type.py --workers 32     # full run
"""
import argparse, csv, json, os, re, sys, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(it, **kw): return it

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGECACHE = os.path.join(ROOT, "page_counts.csv")        # relpath, pages (stage 1 output)
OUT_CSV = os.path.join(ROOT, "type_labels.csv")
MODEL = "gpt-5.4-mini"
MAX_OUT_TOKENS = 3000     # generous cap: reasoning tokens share this budget

# rough gpt-5-mini-class rates ($/1M tokens) for the on-the-fly cost estimate;
# token counts printed are exact, only the $ is an estimate.
PRICE_IN, PRICE_OUT = 0.25, 2.00

# ---------- deterministic regex type (kept as a cross-check column) ----------
def clean(fn):
    t = fn[:-4] if fn.lower().endswith(".pdf") else fn
    t = re.sub(r"\(\d+\)$", "", t)
    t = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", t)
    t = re.sub(r"^\s*\d+\s*,\s*(?:Doc\.?\s*[\d\-]+|Docket\s*#\s*\d+)\s*,\s*", "", t, flags=re.I)
    t = re.sub(r"^US(?:_[A-Za-z0-9]+)*?_\d+[a-z]{2,4}\d+_[A-Za-z0-9]+_", "", t)
    t = re.sub(r"_\d+_\d+$", "", t)
    t = re.sub(r"^\s*\d+\s*,\s*", "", t)
    return re.sub(r"[_]+", " ", t).strip().lower()

ORDER_KW = re.compile(r"\b(order|ordered|opinion|judgment|pretrial order|case management order|"
                      r"cmo|minute order|minutes|scheduling order|memorandum opinion|"
                      r"memorandum and order|memorandum decision|report and recommendation|findings of fact)\b")
MOTION_KW = re.compile(r"\b(motion|mot|mtn|notice of motion|application|petition|cross-?motion)\b")
OTHER_KW = re.compile(r"\b(declaration|decl|affidavit|response|reply|opposition|opp|memorandum|memo|"
                      r"brief|transcript|notice|letter|exhibit|appendix|compendium|complaint|answer|"
                      r"objection|suggestions?|submission|stipulation|order to show cause|document)\b")

def regex_type(fn):
    s = clean(fn)
    p = lambda rx: (rx.search(s).start() if rx.search(s) else 10**9)
    po, pm, px = p(ORDER_KW), p(MOTION_KW), p(OTHER_KW)
    best = min(po, pm, px)
    if best == 10**9: return "OTHER"
    return "ORDER" if po == best else ("MOTION" if pm == best else "OTHER")

# ---------- LLM ----------
SYS = """You classify a U.S. multidistrict-litigation (MDL) court document into exactly ONE type, using ONLY its filename and page count. Judge the document TYPE only -- never its relevance or importance.

Types:
- "order": a ruling/decision ISSUED BY THE COURT -- order, opinion, judgment, pretrial order, case management order (CMO), minute order, MINUTE entry, scheduling order, letter order, memo-endorsed order, memorandum order/opinion/decision, stipulation-and-order, findings, report & recommendation.
- "motion": a request FILED BY A PARTY asking the court to act -- motion, application, petition, notice of motion, letter motion, and abbreviations like "Mtn"/"Mot".
- "other": a document that is CLEARLY neither an order nor a motion -- e.g. a declaration, affidavit, transcript, exhibit, appendix, complaint, answer, brief or memorandum of law, response, reply, opposition, notice (that is not a notice of motion), letter (that is not a letter order/motion), objection, stipulation without "and order". Use this ONLY when the filename clearly identifies such a non-order, non-motion document.
- "unclear": the filename is ambiguous, uninformative, abbreviated, truncated, or otherwise does not let you confidently decide -- AND in particular whenever the document could plausibly be an order or a motion but you cannot tell.

CRITICAL RULES:
- NEVER put a document in "other" if it could possibly be an order or a motion. When torn between "other" and order/motion, choose "unclear".
- Only choose "other" when the filename CLEARLY names a non-order, non-motion document (e.g. it plainly says Declaration, Transcript, Exhibit, Complaint, Answer, Brief).
- Classify by the PRIMARY document the filename names (its lead noun). "Order granting Motion to X" = order. "Motion for an order doing X" = motion. "Declaration/Memo/Exhibit in support of Motion" = other (it is clearly the support document, not the motion).
- The filename is authoritative; page count is only minor context.

Return JSON {type}."""

SCHEMA = {"type": "object", "properties": {
    "type": {"type": "string", "enum": ["order", "motion", "other", "unclear"]}},
    "required": ["type"], "additionalProperties": False}

def classify_one(client, relpath, pages):
    fn = os.path.basename(relpath)
    pg = "unknown" if pages < 0 else pages
    try:
        r = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": SYS},
                      {"role": "user", "content": f"FILENAME: {fn}\nPAGES: {pg}"}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": "doctype", "strict": True, "schema": SCHEMA}},
            max_completion_tokens=MAX_OUT_TOKENS)
        d = json.loads(r.choices[0].message.content or "{}")
        u = r.usage
        return ([relpath, pages, regex_type(fn), d.get("type", "unclear").upper()],
                (u.prompt_tokens, u.completion_tokens))
    except Exception as e:
        return ([relpath, pages, regex_type(fn), f"ERROR:{type(e).__name__}:{str(e)[:60]}"],
                (0, 0))

def load_pages():
    m = {}
    with open(PAGECACHE) as f:
        r = csv.reader(f); next(r)
        for rel, n in r:
            m[rel] = int(n)
    return m

def already_done():
    done = set()
    if os.path.exists(OUT_CSV):
        with open(OUT_CSV, newline="") as f:
            r = csv.reader(f); next(r, None)
            for row in r:
                if row: done.add(row[0])
    return done

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=48,
                    help="concurrent LLM requests; raise for throughput (rate limits self-throttle via SDK retries)")
    args = ap.parse_args()

    pages = load_pages()
    done = already_done()
    todo = [rel for rel in sorted(pages) if rel not in done]
    if args.limit: todo = todo[:args.limit]
    print(f"docs: {len(pages):,} | done: {len(done):,} | to do: {len(todo):,}")
    if args.dry_run or not todo: return 0

    load_dotenv(os.path.join(ROOT, ".env"))
    if not os.getenv("OPENAI_API_KEY"):
        print("Missing OPENAI_API_KEY", file=sys.stderr); return 1
    from openai import OpenAI
    client = OpenAI(max_retries=5)

    new = not os.path.exists(OUT_CSV)
    f = open(OUT_CSV, "a", newline="")
    w = csv.writer(f); lock = threading.Lock()
    if new:
        w.writerow(["relpath", "pages", "regex_type", "llm_type"]); f.flush()

    tot_in = tot_out = errs = n = 0
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(classify_one, client, rel, pages[rel]) for rel in todo]
            for fut in tqdm(as_completed(futs), total=len(futs), unit="doc", desc="type"):
                row, (pin, pout) = fut.result()
                with lock:
                    w.writerow(row); f.flush()
                tot_in += pin; tot_out += pout; n += 1
                if str(row[3]).startswith("ERROR"): errs += 1
                if n % 250 == 0:
                    est = tot_in/1e6*PRICE_IN + tot_out/1e6*PRICE_OUT
                    per = est/n
                    print(f"\n  [{n}] in={tot_in:,} out={tot_out:,} ~${est:.2f} so far | "
                          f"~${per*len(todo):.2f} projected for this run | errors={errs}")
    finally:
        f.close()
    est = tot_in/1e6*PRICE_IN + tot_out/1e6*PRICE_OUT
    print(f"\nDONE batch: {n} docs | in={tot_in:,} out={tot_out:,} tokens | "
          f"~${est:.2f} (est) | errors={errs} | -> {OUT_CSV}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
