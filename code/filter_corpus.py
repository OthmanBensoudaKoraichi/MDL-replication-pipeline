"""Build the filtered corpus: files/<MDL>/*.pdf  ->  filtered_files/<MDL>/*.pdf,
applying the relevance filters. files/ is the untouched source of truth; kept
documents are HARD-LINKED into filtered_files/ (no extra disk).

Three drop rules:
  1. DOCKET DUMP    - the multi-hundred-page "Docket Entries"/"Master Docket"
                      exports (filename-detected). ~97 files.
  2. OTHER          - every document the type classifier (code/classify_type.py,
                      see type_labels.csv) labelled "other" -- i.e. CLEARLY
                      neither an order nor a motion -- dropped at any length.
  3. LONG UNCLEAR   - documents labelled "unclear" whose page count exceeds
                      --max-unclear-pages. Short unclear docs are kept (cheap to
                      keep, and they might be an order/motion).

Orders and motions are always kept.

The build is a reconcile: it links any kept doc that is missing and removes any
filtered_files doc that should now be dropped, so re-running with a different
threshold just adjusts the difference. (filtered_files contains only hard links;
removing one never touches the source in files/.)

SAFE BY DEFAULT: prints a summary and changes nothing. Pass --apply to act.
"""
import argparse
import csv
import hashlib
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = os.path.join(ROOT, "files")
OUT = os.path.join(ROOT, "filtered_files")
LABELS = os.path.join(ROOT, "type_labels.csv")

# ---- rule 1: docket-dump detection (filename only) ----
DUMP_RE = re.compile(r"^(master\s+)?docket(\s+entries)?(\s*[,(]|\s*$)", re.I)
DUMP_EXTRA_RE = re.compile(
    r"^master\s+docket\b|^mdl[-\s]*\d+[-\s]*docket\b|docket\s+summary|docket\s+report|"
    r"docket\s+sheet|consolidated\s+docket|docket\s+listing", re.I)


def title(fn):
    t = fn[:-4] if fn.lower().endswith(".pdf") else fn
    return re.sub(r"^\s*\d+\s*(?:,\s*|\s+)", "", t).strip()


def norm_base(fn):
    """Filename without extension or a trailing '(N)' copy marker, lowercased --
    so 'X.pdf', 'X (1).pdf' and 'X(2).pdf' share one key for de-duplication."""
    t = fn[:-4] if fn.lower().endswith(".pdf") else fn
    t = re.sub(r"\s*\(\d+\)\s*$", "", t)
    return t.strip().lower()


def file_hash(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_dump(fn):
    if "docket" not in fn.lower():
        return False
    t = title(fn)
    if "#" in t:
        return False
    return bool(DUMP_RE.match(t)) or bool(DUMP_EXTRA_RE.search(t))


def load_labels():
    """relpath -> (pages, llm_type)."""
    m = {}
    if not os.path.exists(LABELS):
        sys.exit(f"missing {LABELS} -- run code/classify_type.py first")
    with open(LABELS, newline="") as f:
        for row in csv.DictReader(f):
            try:
                pg = int(row["pages"])
            except ValueError:
                pg = -1
            m[row["relpath"]] = (pg, row["llm_type"])
    return m


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="actually link/remove files")
    ap.add_argument("--max-unclear-pages", type=int, default=50,
                    help="drop 'unclear' docs longer than this (default 50)")
    args = ap.parse_args()
    T = args.max_unclear_pages
    labels = load_labels()

    linked = removed = kept = 0
    drop_docket = drop_other = drop_long_unclear = drop_error = drop_corrupt = drop_dup = 0
    drop_examples = []
    seen_norm = {}   # normalized basename -> [(relpath, hash|None)]; hashing deferred to first collision

    for mdl in sorted(os.listdir(FILES)):
        mdl_dir = os.path.join(FILES, mdl)
        if not os.path.isdir(mdl_dir):
            continue
        for fn in sorted(os.listdir(mdl_dir)):
            if not fn.lower().endswith(".pdf"):
                continue
            relpath = f"{mdl}/{fn}"
            src = os.path.join(mdl_dir, fn)
            dest = os.path.join(OUT, mdl, fn)

            # decide drop / keep
            drop_reason = None
            pg, lt = labels.get(relpath, (-1, "UNCLEAR"))  # default keep if unlabeled
            if is_dump(fn):
                drop_reason = "docket"
            elif str(lt).startswith("ERROR"):
                drop_reason = "classify_error"     # classify_type API failure residue
            elif pg <= 0:
                drop_reason = "corrupt"            # unreadable PDF (pages == -1 / 0)
            elif lt == "OTHER":
                drop_reason = "other"
            elif lt == "UNCLEAR" and pg > T:
                drop_reason = "long_unclear"
            else:
                # de-duplicate WITHIN AN MDL only: drop a doc iff an already-kept doc IN THE SAME MDL
                # has identical content (the "(N)" copies). The key is (mdl, normalized basename), so a
                # filing cross-listed in two MDLs is kept under EACH -- never collapsed across folders.
                # (Collapsing across MDLs would drop an order from its true MDL and misattribute it to
                # the alphabetically-first one -- fatal for a per-MDL leadership analysis.) Hash only on
                # an in-MDL basename collision, so unique docs are never hashed.
                nb = (mdl, norm_base(fn))
                prev = seen_norm.get(nb)
                if prev is None:
                    seen_norm[nb] = [(relpath, None)]      # first sighting; defer hashing
                else:
                    h = file_hash(src)
                    resolved, is_dup = [], False
                    for prel, ph in prev:
                        if ph is None:
                            ph = file_hash(os.path.join(FILES, prel))
                        resolved.append((prel, ph))
                        if ph == h:
                            is_dup = True
                    seen_norm[nb] = resolved
                    if is_dup:
                        drop_reason = "duplicate"
                    else:
                        seen_norm[nb].append((relpath, h))

            if drop_reason:
                if drop_reason == "docket":
                    drop_docket += 1
                elif drop_reason == "other":
                    drop_other += 1
                elif drop_reason == "classify_error":
                    drop_error += 1
                elif drop_reason == "corrupt":
                    drop_corrupt += 1
                elif drop_reason == "duplicate":
                    drop_dup += 1
                    if len(drop_examples) < 12:
                        drop_examples.append(f"dup  {relpath}")
                else:
                    drop_long_unclear += 1
                if os.path.lexists(dest):
                    if args.apply:
                        os.remove(dest)
                    removed += 1
            else:
                if os.path.lexists(dest):
                    kept += 1
                else:
                    if args.apply:
                        os.makedirs(os.path.dirname(dest), exist_ok=True)
                        os.link(src, dest)
                    linked += 1

    print("=" * 64)
    print(f"max-unclear-pages threshold (T):     {T}")
    print(f"kept (already linked):               {kept:,}")
    print(f"newly linked:                        {linked:,}")
    print(f"removed from filtered_files:         {removed:,}")
    print(f"  dropped as docket dump:            {drop_docket}")
    print(f"  dropped as 'other' (any length):   {drop_other:,}")
    print(f"  dropped as long 'unclear' (>{T}p):  {drop_long_unclear:,}")
    print(f"  dropped as duplicate (content):    {drop_dup:,}")
    print(f"  dropped as corrupt (unreadable):   {drop_corrupt:,}")
    print(f"  dropped as classify ERROR:         {drop_error:,}")
    print(f"\nkept total in filtered_files:        {kept + linked:,}")
    print("\nsample of duplicate drops:")
    for e in drop_examples:
        print(f"    {e}")
    if not args.apply:
        print("\nDRY RUN — nothing changed. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
