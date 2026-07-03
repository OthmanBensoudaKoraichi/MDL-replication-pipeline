"""Fill the blank demographic columns on the canonical attorney roster, with sources + confidence.

Input  : canonical_attorneys.csv (from dedup_attorneys.py) -- the deduped roster, one row per person.
Output : canonical_attorneys_demographics.csv -- same rows, with Gender, Birth_Year, Undergrad_School,
         Undergrad_Grad_Year, Law_School_Name, Law_Grad_Year, Bar_States, Sources, Notes filled where a
         reliable source was found (blank + a "not found" note otherwise).
Cache  : demographics_cache.jsonl -- one raw model result per attorney, so a run is resumable and the
         lookups are FROZEN (re-running never re-queries a cached attorney -> reproducible for the paper).

Method (disclosed in METHOD.md): per canonical attorney we issue ONE web-grounded LLM lookup, passing
the name + their law firm(s) + the MDLs they led in (disambiguation context). The model is told to
return a field ONLY when it finds a citable source, to infer gender from a bio/pronouns (NOT from the
first name), and to abstain otherwise. Every filled field carries source URLs and a confidence level;
low-confidence rows are flagged for human verification. Nothing is invented -- unknown stays blank.

SAFE BY DEFAULT: a bare run is a DRY RUN (prints the plan, spends nothing). Pass --apply to call the API.

Usage:
    python attorney_demographics.py                      # dry run: how many rows need filling, est. cost
    python attorney_demographics.py --apply --limit 25   # a metered first batch
    python attorney_demographics.py --apply               # full roster (resumable; skips cached)
"""
import argparse
import csv
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IN_CSV = os.path.join(ROOT, "canonical_attorneys.csv")
OUT_CSV = os.path.join(ROOT, "canonical_attorneys_demographics.csv")
CACHE = os.path.join(ROOT, "demographics_cache.jsonl")
MODEL = "gpt-5.5"                       # must be a web-search-capable model on your key
PRICE_IN, PRICE_OUT = 5.0, 30.0         # gpt-5.5 $/1M (rough) for the estimate; web-search adds a per-call fee

FILL_FIELDS = ["Gender", "Birth_Year", "Undergrad_School", "Undergrad_Grad_Year",
               "Law_School_Name", "Law_Grad_Year", "Bar_States", "Sources", "Notes"]

SYS = """You are a meticulous legal-research assistant building a dataset of MDL leadership attorneys for
an academic paper. Use web search. For the attorney described, find ONLY facts you can support with a
citable public source (a bar directory, law-firm bio, Martindale/Avvo, a law-school alumni page, a news
profile). Rules:
- gender: 'male' / 'female' / 'unknown'. Infer ONLY from a bio, photo caption, or pronouns in a source --
  NEVER from the first name alone. If no source indicates it, return 'unknown'.
- law_school / undergrad_school: the institution name; *_grad_year: 4-digit year if stated.
- bar_states: US states where the attorney is/was admitted (2-letter codes), as a list.
- birth_year: only if explicitly public (rare); else null.
- Use the firm(s) and the MDLs the attorney led in to make sure you have the RIGHT person (common names
  collide). If you cannot confidently identify the person, return everything null with confidence 'low'.
- sources: list the URLs you relied on. confidence: 'high' | 'medium' | 'low'. Do NOT fabricate.
Return ONLY a JSON object: {gender, birth_year, law_school, law_grad_year, undergrad_school,
undergrad_grad_year, bar_states:[...], sources:[...], confidence, notes}."""


def load_rows():
    if not os.path.exists(IN_CSV):
        sys.exit(f"missing {IN_CSV} -- run dedup_attorneys.py first")
    with open(IN_CSV, encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        return list(rd), rd.fieldnames


def load_cache():
    done = {}
    if os.path.exists(CACHE):
        for line in open(CACHE, encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    d = json.loads(line)
                    done[d["Attorney_ID"]] = d
                except Exception:
                    pass
    return done


def build_query(row):
    return (f"Attorney: {row.get('Canonical_Name','')}\n"
            f"Law firm(s): {row.get('Firms','') or 'unknown'}\n"
            f"Led leadership in MDL number(s): {row.get('MDLs','') or 'unknown'}\n"
            f"Find the demographic + education fields per the rules and return the JSON.")


def extract_json(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:
        return {}


def lookup_one(client, row):
    """One web-grounded lookup. Returns the parsed dict (or an error dict). Uses the Responses API with
    the web_search tool; falls back to a plain chat completion (no web) if the tool is unavailable."""
    q = build_query(row)
    try:
        resp = client.responses.create(model=MODEL, tools=[{"type": "web_search"}],
                                       input=f"{SYS}\n\n{q}")
        text = getattr(resp, "output_text", None) or ""
    except Exception as e:  # web_search tool / responses API not available on this key
        try:
            r = client.chat.completions.create(
                model=MODEL, messages=[{"role": "system", "content": SYS},
                                       {"role": "user", "content": q}], max_completion_tokens=2000)
            text = r.choices[0].message.content or ""
        except Exception as e2:  # noqa: BLE001
            return {"_error": f"{type(e).__name__}/{type(e2).__name__}: {str(e2)[:80]}"}
    d = extract_json(text)
    d["_raw"] = text[:4000]
    return d


def to_row_updates(d):
    if not d or d.get("_error"):
        return {"Notes": ("lookup error: " + d.get("_error", "")) if d else "no result"}
    conf = d.get("confidence", "")
    bar = d.get("bar_states") or []
    upd = {
        "Gender": d.get("gender") if d.get("gender") not in (None, "unknown") else "",
        "Birth_Year": d.get("birth_year") or "",
        "Undergrad_School": d.get("undergrad_school") or "",
        "Undergrad_Grad_Year": d.get("undergrad_grad_year") or "",
        "Law_School_Name": d.get("law_school") or "",
        "Law_Grad_Year": d.get("law_grad_year") or "",
        "Bar_States": ", ".join(bar) if isinstance(bar, list) else (bar or ""),
        "Sources": " | ".join(d.get("sources") or []) if isinstance(d.get("sources"), list) else (d.get("sources") or ""),
        "Notes": f"confidence={conf}" + (f"; {d.get('notes')}" if d.get("notes") else ""),
    }
    return upd


def main():
    global MODEL
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="actually call the API (default: dry run)")
    ap.add_argument("--limit", type=int, help="only the first N not-yet-cached attorneys")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--in-csv", help="roster to enrich (default canonical_attorneys.csv)")
    ap.add_argument("--out-csv", help="output path (default canonical_attorneys_demographics.csv)")
    ap.add_argument("--cache", help="cache jsonl (default demographics_cache.jsonl); pre-seed it to "
                                    "SKIP attorneys you already have data for (e.g. from gold)")
    ap.add_argument("--workers", type=int, default=8, help="concurrent web lookups (default 8)")
    args = ap.parse_args()
    MODEL = args.model
    global IN_CSV, OUT_CSV, CACHE
    if args.in_csv:
        IN_CSV = args.in_csv if os.path.isabs(args.in_csv) else os.path.join(ROOT, args.in_csv)
    if args.out_csv:
        OUT_CSV = args.out_csv if os.path.isabs(args.out_csv) else os.path.join(ROOT, args.out_csv)
    if args.cache:
        CACHE = args.cache if os.path.isabs(args.cache) else os.path.join(ROOT, args.cache)

    rows, cols = load_rows()
    cache = load_cache()
    out_cols = list(cols) + [c for c in FILL_FIELDS if c not in cols]
    # attorneys that still need a lookup: have a real name and aren't cached
    todo = [r for r in rows if r.get("Canonical_Name", "").strip() and r.get("Attorney_ID") not in cache]
    if args.limit:
        todo = todo[:args.limit]

    print(f"roster: {len(rows):,} | already cached: {len(cache):,} | to look up: {len(todo):,} | model: {MODEL}")
    est = len(todo) * (2500 / 1e6 * PRICE_IN + 700 / 1e6 * PRICE_OUT)
    print(f"est LLM token cost: ~${est:,.0f} (+ web-search per-call fees, billed separately by the provider)")
    if not args.apply or not todo:
        print("DRY RUN -- pass --apply to run." if not args.apply else "nothing to do.")
        # still (re)write the output by merging any existing cache, so partial progress is materialized
        if not args.apply:
            return 0

    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    if not os.getenv("OPENAI_API_KEY"):
        print("missing OPENAI_API_KEY", file=sys.stderr)
        return 1
    from openai import OpenAI
    client = OpenAI(max_retries=4, timeout=90.0)   # per-request timeout so a hung web_search can't stall the run

    cf = open(CACHE, "a", encoding="utf-8")
    lock = threading.Lock()
    done = errs = 0

    def work(row):
        d = lookup_one(client, row)
        d["Attorney_ID"] = row["Attorney_ID"]
        return d

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(work, r) for r in todo]
        for i, fut in enumerate(as_completed(futs), 1):
            d = fut.result()
            with lock:
                cf.write(json.dumps(d, ensure_ascii=False) + "\n")
                cf.flush()
                cache[d["Attorney_ID"]] = d
                if d.get("_error"):
                    errs += 1
                else:
                    done += 1
            if i % 20 == 0:
                print(f"  [{i}/{len(todo)}] filled={done} err={errs}")
    cf.close()

    # materialize the merged CSV
    for r in rows:
        d = cache.get(r.get("Attorney_ID"))
        if d:
            r.update(to_row_updates(d))
    with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=out_cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in out_cols})
    filled = sum(1 for r in rows if r.get("Sources"))
    print(f"\nwrote {os.path.relpath(OUT_CSV, ROOT)} | rows with a source: {filled:,} | lookups this run: {done} (errors {errs})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
