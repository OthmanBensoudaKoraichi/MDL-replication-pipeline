"""Trim each ORDER to its signature page.

For every doc labelled ORDER in type_labels.csv within the target MDLs that has
OCR text (ocr/<MDL>/<doc>.json), find the LAST page whose text contains the word
"judge" -- the judge's signature page -- and treat that as the order's last page,
dropping the trailing pages (exhibits / attachments). If no page mentions
"judge", keep the whole document.

This produces the clean order text to feed the (downstream) structured extractor,
without the post-signature junk.

Writes orders/<MDL>/<doc>.json:
    {relpath, mdl, filename, n_pages, signature_page, judge_found, n_chars, text}
where text is pages 1..signature_page joined. A summary table goes to
orders/_spans.csv. Deterministic and free (no API); idempotent (overwrites).

Usage:
    python trim_orders.py                  # the 10-MDL working set
    python trim_orders.py --mdls 2741,2873
"""
import argparse
import csv
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OCR_DIR = os.path.join(ROOT, "ocr")
FILTERED = os.path.join(ROOT, "filtered_files")
OUT_DIR = os.path.join(ROOT, "orders")
LABELS = os.path.join(ROOT, "type_labels.csv")
SPANS = os.path.join(OUT_DIR, "_spans.csv")

DEFAULT_MDLS = ["2263", "2428", "2504", "2570", "2664",
                "2687", "2741", "2818", "2873", "2878"]
JUDGE_RE = re.compile(r"\bjudges?\b", re.I)
# Strong signature markers: a real judge's signature block, not a body mention of "judge".
# Catches the abbreviated forms (U.S.D.J. / U.S.M.J.) that \bjudges?\b misses.
SIG_RE = re.compile(
    r"(/s/|U\.?\s?S\.?\s?D\.?\s?J\b|U\.?\s?S\.?\s?M\.?\s?J\b|United States (?:District|Magistrate) Judge|"
    r"IT IS SO ORDERED|SO ORDERED|ORDERED,?\s+ADJUDGED)", re.I)


def all_order_mdls():
    """Every MDL with an ORDER doc (or a gate-kept doc) -- the universe for a --all full-corpus run."""
    out = set()
    with open(LABELS, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["llm_type"] == "ORDER":
                m = re.match(r"^(\d+)", r["relpath"])
                if m:
                    out.add(m.group(1))
    status = os.path.join(ROOT, "order_status.csv")
    if os.path.exists(status):
        with open(status, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("retrieve") == "1":
                    m = re.match(r"^(\d+)", r["relpath"])
                    if m:
                        out.add(m.group(1))
    return sorted(out)


def order_relpaths(mdls):
    """Docs to trim: every ORDER-labeled doc in the target MDLs, PLUS any doc the
    gate kept (retrieve=1 in order_status.csv) -- e.g. memo-endorsed motions, which
    are MOTION-labeled but are really orders."""
    want = set(mdls)
    out = set()
    with open(LABELS, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["llm_type"] != "ORDER":
                continue
            m = re.match(r"^(\d+)", r["relpath"])
            # only ORDER docs that survived the filter (propagates dedup / corrupt drops)
            if m and m.group(1) in want and os.path.exists(os.path.join(FILTERED, r["relpath"])):
                out.add(r["relpath"])
    status = os.path.join(ROOT, "order_status.csv")
    if os.path.exists(status):
        with open(status, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("retrieve") == "1":
                    m = re.match(r"^(\d+)", r["relpath"])
                    if m and m.group(1) in want:
                        out.add(r["relpath"])
    return sorted(out)


def ocr_json_path(rel):
    folder, fn = rel.split("/", 1)
    stem = fn[:-4] if fn.lower().endswith(".pdf") else fn
    return folder, fn, os.path.join(OCR_DIR, folder, stem + ".json")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mdls", help="comma-separated MDL numbers (default: the 10-sample)")
    ap.add_argument("--all", action="store_true",
                    help="every MDL with an ORDER/gate-kept doc (full corpus; overrides --mdls and the 10-sample default)")
    args = ap.parse_args()
    mdls = all_order_mdls() if args.all else (
        [s.strip() for s in args.mdls.split(",")] if args.mdls else DEFAULT_MDLS)

    rels = order_relpaths(mdls)
    spans = []
    missing = by_sig = by_judge = whole = 0
    for rel in rels:
        folder, fn, jp = ocr_json_path(rel)
        if not os.path.exists(jp):
            missing += 1
            continue
        with open(jp, encoding="utf-8") as f:
            d = json.load(f)
        pages = sorted(d.get("pages", []), key=lambda p: p.get("page", 0))
        n_pages = len(pages)
        # Prefer the last page bearing a real SIGNATURE marker (/s/, U.S.D.J., SO ORDERED...).
        # Only if none exists fall back to the last bare "judge" page; if neither, keep whole.
        # This stops over-cutting on a body mention of "judge" and catches "U.S.D.J." signatures.
        last_sig = max((p["page"] for p in pages if SIG_RE.search(p.get("text", ""))), default=None)
        if last_sig is not None:
            sig, method = last_sig, "signature"
            by_sig += 1
        else:
            last_judge = max((p["page"] for p in pages if JUDGE_RE.search(p.get("text", ""))), default=None)
            if last_judge is not None:
                sig, method = last_judge, "judge-word"
                by_judge += 1
            else:
                sig, method = n_pages, "whole"
                whole += 1
        judge_found = method != "whole"
        kept = [p for p in pages if p["page"] <= sig]
        text = "\n\n".join(p.get("text", "") for p in kept).strip()

        out = {
            "relpath": rel,
            "mdl": d.get("mdl", ""),
            "filename": fn,
            "n_pages": n_pages,
            "signature_page": sig,
            "judge_found": judge_found,
            "cut_method": method,
            "n_chars": len(text),
            "text": text,
        }
        stem = fn[:-4] if fn.lower().endswith(".pdf") else fn
        dest = os.path.join(OUT_DIR, folder, stem + ".json")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        spans.append([rel, n_pages, sig, int(judge_found), n_pages - sig, len(text)])

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(SPANS, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["relpath", "n_pages", "signature_page", "judge_found", "pages_dropped", "n_chars"])
        for row in sorted(spans):
            w.writerow(row)

    dropped = sum(r[4] for r in spans)
    print(f"orders processed:        {len(spans)}  (missing OCR: {missing})")
    print(f"  cut at signature marker: {by_sig}")
    print(f"  cut at bare 'judge' page:{by_judge}")
    print(f"  no marker (kept full):   {whole}")
    print(f"total trailing pages dropped: {dropped:,}")
    print(f"wrote orders/<MDL>/<doc>.json + {os.path.relpath(SPANS, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
