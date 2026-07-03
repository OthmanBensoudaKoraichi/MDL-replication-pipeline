"""D10 — estimate the Stage-2 (filename-only) TYPE-classifier error rate.

classify_type.py labels each doc order/motion/other/unclear from the FILENAME + page count alone,
never the body. This script samples N docs that have OCR text, RE-classifies each from the actual
document BODY with the same model, and reports the disagreement rate -- a proxy for the filename-only
mislabel rate (treating the body-based label as the better signal). The case that matters most for
recall is an order/motion the filename-classifier sent to 'other' (it gets dropped); that rate is
reported separately.

Default is a DRY RUN (no API). Pass --apply to run. Writes classify_error_sample.csv + prints a matrix.

Usage:
    python measure_classify.py --apply --n 100 --seed 20260628
"""
import argparse, csv, json, os, random, re, sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LABELS = os.path.join(ROOT, "type_labels.csv")
OCR_DIR = os.path.join(ROOT, "ocr")
MODEL = "gpt-5.4-mini"
TYPES = ["order", "motion", "other", "unclear"]

SYS = """You classify a U.S. multidistrict-litigation (MDL) court document into exactly ONE type, using
its TEXT. order = a ruling/opinion/judgment/order entered by the court. motion = a party's motion,
application, or petition (a request). other = a brief, memorandum, declaration, affidavit, notice,
exhibit, transcript, docket sheet, complaint, or other non-order/non-motion filing. unclear = genuinely
cannot tell. Judge the document's PRIMARY type from its content. Return JSON {"type": "..."}."""
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["type"],
          "properties": {"type": {"type": "string", "enum": TYPES}}}


def ocr_text(rel, limit=7000):
    folder, fn = rel.split("/", 1)
    stem = fn[:-4] if fn.lower().endswith(".pdf") else fn
    jp = os.path.join(OCR_DIR, folder, stem + ".json")
    if not os.path.exists(jp):
        return None
    try:
        pages = sorted(json.load(open(jp, encoding="utf-8")).get("pages", []), key=lambda p: p.get("page", 0))
    except Exception:
        return None
    return "\n".join(p.get("text", "") for p in pages)[:limit]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=20260628)
    args = ap.parse_args()

    rows = [r for r in csv.DictReader(open(LABELS, encoding="utf-8"))]
    cand = [r for r in rows if ocr_text(r["relpath"]) is not None]   # only docs we can re-read
    random.seed(args.seed)
    sample = random.sample(cand, min(args.n, len(cand)))
    print(f"labeled docs: {len(rows):,} | with OCR: {len(cand):,} | sampling {len(sample)}")
    if not args.apply:
        print("DRY RUN -- pass --apply to call the API.")
        return 0

    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    if not os.getenv("OPENAI_API_KEY"):
        print("missing OPENAI_API_KEY", file=sys.stderr); return 1
    from openai import OpenAI
    client = OpenAI(max_retries=5)

    out, agree = [], 0
    matrix = defaultdict(Counter)          # filename_label -> Counter(body_label)
    drop_miss = 0                          # filename said 'other' (dropped) but body says order/motion
    for i, r in enumerate(sample, 1):
        fname_lbl = (r["llm_type"] or "").lower()
        body = ocr_text(r["relpath"])
        try:
            resp = client.chat.completions.create(
                model=MODEL, messages=[{"role": "system", "content": SYS},
                                       {"role": "user", "content": body}],
                response_format={"type": "json_schema",
                                 "json_schema": {"name": "type", "strict": True, "schema": SCHEMA}},
                max_completion_tokens=2000)
            body_lbl = json.loads(resp.choices[0].message.content or "{}").get("type", "unclear")
        except Exception as e:  # noqa: BLE001
            body_lbl = f"ERROR:{type(e).__name__}"
        same = (fname_lbl == body_lbl)
        agree += same
        if not body_lbl.startswith("ERROR"):
            matrix[fname_lbl][body_lbl] += 1
            if fname_lbl == "other" and body_lbl in ("order", "motion"):
                drop_miss += 1
        out.append({"relpath": r["relpath"], "filename_label": fname_lbl, "body_label": body_lbl, "agree": int(same)})
        if i % 25 == 0:
            print(f"  [{i}/{len(sample)}] agree so far {agree}")

    with open(os.path.join(ROOT, "classify_error_sample.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["relpath", "filename_label", "body_label", "agree"])
        w.writeheader(); w.writerows(out)

    n = len(sample)
    print(f"\n=== filename-only classifier vs body re-classification (n={n}) ===")
    print(f"  overall agreement: {agree}/{n} = {100*agree/n:.0f}%  (disagreement = ~{100*(n-agree)/n:.0f}% filename-only error)")
    print(f"  RECALL-CRITICAL: filename said 'other' (DROPPED) but body is order/motion: {drop_miss}/{n} = {100*drop_miss/n:.1f}%")
    print("  confusion (filename_label -> body_label):")
    for fl in sorted(matrix):
        print(f"    {fl:8} -> " + ", ".join(f"{bl}:{c}" for bl, c in matrix[fl].most_common()))
    print("\nwrote classify_error_sample.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
