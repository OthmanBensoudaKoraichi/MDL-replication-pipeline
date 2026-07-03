"""Stage 6: the ORDER GATE -- the precision step before extraction.

For every doc labelled ORDER in type_labels.csv (within the target MDLs) that has
OCR text, decide whether to RETRIEVE it into the leadership-APPOINTMENT dataset.
Two tests, and a doc is retrieved only if it passes BOTH:

  TEST A  RELEVANCE  -- the order appoints, removes, or modifies leadership /
                       counsel (lead/co-lead/liaison counsel, steering or
                       executive committees, PSC/DSC, or Rule 23(g) class
                       counsel), OR is a generically-named order worth checking.
                       APPOINTMENTS ONLY: attorney's-fee awards, common-benefit /
                       holdback / timekeeping orders, and settlement/judgment
                       orders that do NOT change the leadership roster are NOT
                       relevant -- nor are routine discovery/scheduling,
                       transfers, bills of costs, pleadings, sealing, individual
                       settlements, etc. (Matches the live SYS prompt below.)
  TEST B  EXECUTED   -- a judge actually SIGNED/ENTERED it. Signed stipulated and
                       signed proposed orders count. Unsigned proposed orders,
                       unsigned stipulations, magistrate R&Rs, orders embedded as
                       exhibits, orders to show cause, and motions do NOT.

The model returns the relevance + doc_kind + execution signals; `retrieve` is
then computed deterministically (relevance != irrelevant AND doc_kind in the
keep set), so the rule can never drift from the model's prose.

Streams one decision per doc to order_status.csv (resumable):
    relpath, retrieve, relevance, doc_kind, executed, needs_signature_check,
    confidence, reason, evidence

Only retrieve=1 docs should flow on to trim_orders.py / extract_orders.py.
`needs_signature_check` marks kept orders whose signature wasn't in the text
(wet-ink / text / minute orders) -- a small human-eyeball queue.

--model lets you A/B the cheap vs strong model (gpt-5.4-mini vs gpt-5.5).

Usage:
    python confirm_orders.py --dry-run
    python confirm_orders.py --model gpt-5.4-mini --out order_status_mini.csv
    python confirm_orders.py --model gpt-5.5      --out order_status_gpt55.csv
"""
import argparse
import csv
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(it, **kw):
        return it

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OCR_DIR = os.path.join(ROOT, "ocr")
FILTERED = os.path.join(ROOT, "filtered_files")
LABELS = os.path.join(ROOT, "type_labels.csv")
DEFAULT_MDLS = ["2263", "2428", "2504", "2570", "2664",
                "2687", "2741", "2818", "2873", "2878"]
HEAD_CHARS, TAIL_CHARS = 6000, 4000
MAX_OUT_TOKENS = 5000          # small JSON + reasoning-model budget
PRICE = {"gpt-5.4-mini": (0.25, 2.00), "gpt-5.5": (5.0, 30.0)}

KEEP_KINDS = {"executed_order", "signed_stipulated_order", "signed_proposed_order", "endorsed_order"}
# cheap pre-filter for motions: only gate a motion if its text shows disposition language
DISPOSITION_RE = re.compile(
    r"\b(grant(?:s|ed)?|approv(?:e|ed|ing)|so ordered|it is so ordered|allowed|entered|adjudged|decreed)\b", re.I)

SYS = """You decide whether a U.S. MDL court document should be RETRIEVED into a leadership-APPOINTMENT dataset of court ORDERS. We care ONLY about orders that appoint, remove, or modify leadership/counsel -- NOT fees or settlements in themselves. Apply TWO tests.

TEST A — RELEVANCE (subject). Relevant ONLY if the order appoints, removes, replaces, or modifies leadership/counsel:
- lead, co-lead, or liaison counsel; a steering or executive committee; a PSC/DSC or other organizational unit; OR class counsel under Rule 23(g). An order that certifies a class AND names/appoints class counsel IS relevant (the class-counsel appointment counts, even if class certification is the order's main subject).
- A settlement-approval or final-judgment order is relevant ONLY when it appoints, confirms, or removes counsel or a committee; if it merely approves a settlement, awards fees, or enters judgment WITHOUT changing the leadership roster, it is NOT relevant.
- A generically-named order that MIGHT contain a leadership appointment: "Case Management Order #X", "Pretrial Order", "Miscellaneous Order", or any generic title -> treat as relevant (retrieve to check the contents).
NOT relevant (we do NOT collect these): attorney's-fee awards, common-benefit-fund / assessment / holdback / timekeeping orders, bills of costs, routine discovery, scheduling, motions to dismiss / summary judgment, pleadings, summons/service, transfer orders, notices of appearance, sealing/administrative orders, and settlement or individual-case merits orders that do NOT appoint, remove, or modify counsel or a committee. When in doubt on a generic order, keep.

TEST B — IS IT AN EXECUTED ORDER? Keep ONLY:
- An order SIGNED / ENTERED BY THE JUDGE -- including a stipulated order SIGNED by the judge, and a proposed order SIGNED by the judge.
Do NOT keep: an unsigned proposed order, a stipulation NOT signed by the judge, a Magistrate Judge's Report & Recommendation, an order reproduced only as an exhibit/attachment to a party filing, an order to show cause, or ANY motion.

MEMO-ENDORSEMENT EXCEPTION: a MOTION that bears the COURT'S OWN disposition -- the judge's "GRANTED" / "ALLOWED" / "SO ORDERED" written on or appended to the motion, carrying the judge's signature or a filed/entered date -- IS an executed order (a "memo-endorsed" or "so-ordered" motion). Classify it doc_kind=endorsed_order and keep it (subject to Test A). Do NOT be fooled by the movant's own words: "respectfully request", "wherefore", "movant moves/requests", or an attached "[Proposed] Order" containing "IT IS SO ORDERED" is the party ASKING, not the court granting -- that stays doc_kind=motion and is dropped. The genuine endorsement is the COURT's, is short, and is attributable to the judge (name/signature or the docket's entered date), not to the movant.

EXECUTION evidence: a typeset "/s/ Judge", a named judge signature/title block, "SO ORDERED" / "IT IS ORDERED" with a FILED or FILLED date, or a docket text/minute order entered by the court.

CLASSIFY AS unsigned_proposed_order ONLY when there is a POSITIVE proposed signal: the filename or caption says "Proposed" / "[PROPOSED]", OR it is a sub-docket attachment (e.g. "Doc. 210-1") filed with a motion. A blank date or signature line ALONE does NOT make a document proposed.

WET-INK EXCEPTION (critical): if a document is titled "ORDER ..." (NOT "Proposed"), has a clean docket number (not a sub-docket attachment), and contains decretal language ("GRANTED", "the Court appoints", "IT IS ORDERED"), then EVEN IF its date and signature line are blank (e.g. "THUS DONE AND SIGNED this ___ day of ___") -- a scanned wet-ink signature OCR dropped -- classify it executed_order with needs_signature_check=true. Do NOT classify such a document as unsigned_proposed_order or drop it. (A real entered order and a party's proposed draft can have byte-identical blank signature blocks; the filename/caption and clean-vs-sub docket are what separate them.)

A document is retrieved only when relevance is not "irrelevant" AND doc_kind is one of {executed_order, signed_stipulated_order, signed_proposed_order, endorsed_order}.

Return JSON with: relevance, doc_kind, executed, needs_signature_check, evidence (a verbatim quote that decided Test B), reason (one sentence), confidence."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["relevance", "doc_kind", "executed", "needs_signature_check",
                 "evidence", "reason", "confidence"],
    "properties": {
        "relevance": {"type": "string",
                      "enum": ["leadership", "generic_to_check", "irrelevant"]},
        "doc_kind": {"type": "string",
                     "enum": ["executed_order", "signed_stipulated_order", "signed_proposed_order",
                              "endorsed_order", "unsigned_proposed_order", "unsigned_stipulation",
                              "report_recommendation", "embedded_exhibit_order", "show_cause", "motion", "other"]},
        "executed": {"type": "boolean"},
        "needs_signature_check": {"type": "boolean"},
        "evidence": {"type": "string"},
        "reason": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
}

FIELDS = ["relpath", "retrieve", "relevance", "doc_kind", "executed",
          "needs_signature_check", "confidence", "reason", "evidence"]


FULL_LIMIT = 14000      # send whole doc if it fits; else head + early-body + middle + tail
MID_CHARS = 4000
EARLY_CHARS = 6000      # chars HEAD_CHARS..HEAD_CHARS+EARLY -- the common appointment/fee "dead zone"


def ocr_excerpt(rel):
    """Return (excerpt, fn). Short docs are sent whole; long docs are sent as a
    labelled head + an EARLY-BODY slice (where appointments/fee awards usually sit
    in MDL orders) + a centered middle slice + the signature tail. The early-body
    slice closes the dead zone between the head and the middle that previously hid
    operative text in long (25+ page) orders."""
    folder, fn = rel.split("/", 1)
    stem = fn[:-4] if fn.lower().endswith(".pdf") else fn
    jp = os.path.join(OCR_DIR, folder, stem + ".json")
    if not os.path.exists(jp):
        return None
    d = json.load(open(jp, encoding="utf-8"))
    pages = sorted(d.get("pages", []), key=lambda p: p.get("page", 0))
    text = "\n".join(p.get("text", "") for p in pages)
    if len(text) <= FULL_LIMIT:
        return f"FULL DOCUMENT TEXT:\n{text}", fn
    early = text[HEAD_CHARS:HEAD_CHARS + EARLY_CHARS]
    mid = len(text) // 2
    middle = text[mid - MID_CHARS // 2: mid + MID_CHARS // 2]
    excerpt = (f"HEAD (caption / docket / parties, first {HEAD_CHARS} chars):\n{text[:HEAD_CHARS]}\n\n"
               f"EARLY BODY (chars {HEAD_CHARS}-{HEAD_CHARS + EARLY_CHARS}, where appointments/fees usually sit):\n{early}\n\n"
               f"MIDDLE (centered slice of the body):\n{middle}\n\n"
               f"TAIL (signature region, last {TAIL_CHARS} chars):\n{text[-TAIL_CHARS:]}")
    return excerpt, fn


def _ocr_full_text(rel):
    folder, fn = rel.split("/", 1)
    stem = fn[:-4] if fn.lower().endswith(".pdf") else fn
    jp = os.path.join(OCR_DIR, folder, stem + ".json")
    if not os.path.exists(jp):
        return None
    d = json.load(open(jp, encoding="utf-8"))
    return " ".join(p.get("text", "") for p in d.get("pages", []))


def all_label_mdls():
    """Every MDL present in type_labels.csv -- the universe for a --all full-corpus run."""
    out = set()
    with open(LABELS, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            m = re.match(r"^(\d+)", r["relpath"])
            if m:
                out.add(m.group(1))
    return sorted(out)


def candidate_relpaths(mdls, include_motions=False):
    """ORDER docs in the target MDLs. With include_motions, also MOTION docs whose
    OCR text shows disposition language (granted / so ordered / allowed) -- the cheap
    regex pre-filter that narrows motions before the LLM decides if a motion is
    memo-endorsed (an order) or just a party's request (dropped)."""
    want = set(mdls)
    orders, motions = [], []
    with open(LABELS, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            m = re.match(r"^(\d+)", r["relpath"])
            if not (m and m.group(1) in want):
                continue
            # only consider docs that survived the filter (so the dedup / corrupt /
            # docket-dump drops in filter_corpus propagate to the order pipeline)
            if not os.path.exists(os.path.join(FILTERED, r["relpath"])):
                continue
            if r["llm_type"] == "ORDER":
                orders.append(r["relpath"])
            elif include_motions and r["llm_type"] == "MOTION":
                motions.append(r["relpath"])
    if not include_motions:
        return orders
    kept = [rel for rel in motions
            if (t := _ocr_full_text(rel)) and DISPOSITION_RE.search(t)]
    print(f"  motion pre-filter: {len(kept):,} of {len(motions):,} motions carry disposition language")
    return orders + kept


def build_user(fn, excerpt, sub, proposed):
    return (f"FILENAME: {fn}\n"
            f"sub_docket_in_name: {sub}\nproposed_in_name: {proposed}\n\n"
            f"{excerpt}")


def gate_one(client, model, rel):
    ht = ocr_excerpt(rel)
    if ht is None:
        return [rel, "", "", "MISSING_OCR", "", "", "", "no ocr json", ""], (0, 0)
    excerpt, fn = ht
    sub = bool(re.search(r"Doc\.?\s*\d+\s*-\s*\d+", fn))
    proposed = bool(re.search(r"proposed", fn, re.I))
    try:
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": SYS},
                      {"role": "user", "content": build_user(fn, excerpt, sub, proposed)}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": "gate", "strict": True, "schema": SCHEMA}},
            max_completion_tokens=MAX_OUT_TOKENS)
        d = json.loads(r.choices[0].message.content or "{}")
        u = r.usage
        retrieve = int(d.get("relevance") != "irrelevant" and d.get("doc_kind") in KEEP_KINDS)
        return ([rel, retrieve, d.get("relevance", ""), d.get("doc_kind", ""),
                 d.get("executed", ""), d.get("needs_signature_check", ""),
                 d.get("confidence", ""), str(d.get("reason", ""))[:300],
                 str(d.get("evidence", ""))[:200]],
                (u.prompt_tokens, u.completion_tokens))
    except Exception as e:  # noqa: BLE001
        return [rel, "", "", f"ERROR:{type(e).__name__}", "", "", "", str(e)[:150], ""], (0, 0)


def already_done(out_csv):
    done = set()
    if os.path.exists(out_csv):
        with open(out_csv, newline="", encoding="utf-8") as f:
            r = csv.reader(f)
            next(r, None)
            for row in r:
                if row and not str(row[3]).startswith("ERROR") and row[3] != "MISSING_OCR":
                    done.add(row[0])
    return done


def preflight_model(client, model, fallback="gpt-5"):
    """Confirm the chat model id resolves on this API key BEFORE spawning workers (fail fast, not
    mid-run). Returns the working id (the requested model, or the fallback), or None."""
    tries = [model] + ([fallback] if fallback and fallback != model else [])
    for m in tries:
        try:
            client.chat.completions.create(
                model=m, messages=[{"role": "user", "content": "ping"}], max_completion_tokens=16)
            return m
        except Exception as e:  # noqa: BLE001
            msg = str(e).lower()
            if any(t in msg for t in ("max_tokens", "max_completion_tokens", "could not finish", "output limit")):
                return m    # reasoning model: the request was VALID, it just hit the tiny token cap -> available
            print(f"  preflight: model '{m}' unavailable ({type(e).__name__}: {str(e)[:90]})", file=sys.stderr)
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="gpt-5.4-mini")
    ap.add_argument("--out", default="order_status.csv")
    ap.add_argument("--mdls", help="comma-separated MDL numbers (default: the 10-sample)")
    ap.add_argument("--all", action="store_true",
                    help="every MDL in type_labels.csv (full corpus; overrides --mdls and the 10-sample default)")
    ap.add_argument("--include-motions", action="store_true",
                    help="also gate MOTION docs that pass the disposition pre-filter (catches memo-endorsed orders)")
    ap.add_argument("--workers", type=int, default=32,
                    help="concurrent LLM requests; raise for throughput (rate limits self-throttle via SDK retries)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    mdls = all_label_mdls() if args.all else (
        [s.strip() for s in args.mdls.split(",")] if args.mdls else DEFAULT_MDLS)
    out_csv = args.out if os.path.isabs(args.out) else os.path.join(ROOT, args.out)

    rels = candidate_relpaths(mdls, args.include_motions)
    done = already_done(out_csv)
    todo = [r for r in rels if r not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"candidate docs: {len(rels):,} | done: {len(done):,} | to do: {len(todo):,} | "
          f"model: {args.model} | include_motions: {args.include_motions} | out: {os.path.relpath(out_csv, ROOT)}")
    if args.dry_run or not todo:
        return 0

    load_dotenv(os.path.join(ROOT, ".env"))
    if not os.getenv("OPENAI_API_KEY"):
        print("missing OPENAI_API_KEY", file=sys.stderr)
        return 1
    from openai import OpenAI
    client = OpenAI(max_retries=5)
    chosen = preflight_model(client, args.model)
    if not chosen:
        print(f"model '{args.model}' (and fallback) unavailable -- aborting", file=sys.stderr)
        return 1
    if chosen != args.model:
        print(f"  preflight: using fallback model '{chosen}'")
        args.model = chosen
    pin_rate, pout_rate = PRICE.get(args.model, (0.0, 0.0))

    new = not os.path.exists(out_csv)
    f = open(out_csv, "a", newline="", encoding="utf-8")
    w = csv.writer(f)
    lock = threading.Lock()
    if new:
        w.writerow(FIELDS)
        f.flush()

    keep = drop = flag = errs = tin = tout = n = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(gate_one, client, args.model, r) for r in todo]
        for fut in tqdm(as_completed(futs), total=len(futs), unit="doc", desc="gate"):
            row, (pin, pout) = fut.result()
            with lock:
                w.writerow(row)
                f.flush()
            n += 1
            tin += pin
            tout += pout
            if str(row[3]).startswith("ERROR"):
                errs += 1
            elif row[1] == 1:
                keep += 1
                if row[5] in (True, "True", "true"):
                    flag += 1
            elif row[1] == 0:
                drop += 1
            if n % 50 == 0:
                est = tin / 1e6 * pin_rate + tout / 1e6 * pout_rate
                print(f"\n  [{n}] keep={keep} drop={drop} flag={flag} err={errs} ~${est:.2f}")
    f.close()

    est = tin / 1e6 * pin_rate + tout / 1e6 * pout_rate
    print(f"\nDONE: {n} docs | keep={keep} drop={drop} flag(needs_sig_check)={flag} | "
          f"errors={errs} | in={tin:,} out={tout:,} | ~${est:.2f} | -> {os.path.relpath(out_csv, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
