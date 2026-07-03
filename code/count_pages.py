"""Pipeline stage 1: count the pages of every PDF and write a durable page cache.

Walks a source tree (default: files/, the corpus source of truth) and writes
page_counts.csv at the project root:

    relpath,pages      # relpath is relative to --root; pages = -1 if unreadable

This CSV is the deterministic input to classify_type.py (stage 2). Counting over
files/ (the input) rather than filtered_files/ (an output) keeps the pipeline a
clean DAG with no circular dependency.

Usage:
    python count_pages.py                 # scan files/, write page_counts.csv
    python count_pages.py --root files     # explicit
    python count_pages.py --out page_counts.csv
"""
import argparse
import csv
import os
import sys
from concurrent.futures import ProcessPoolExecutor

import fitz  # PyMuPDF

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def count(path):
    try:
        with fitz.open(path) as d:
            return (path, d.page_count, None)
    except Exception as e:  # noqa: BLE001
        return (path, -1, repr(e))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="files",
                    help="directory to scan, relative to project root (default: files)")
    ap.add_argument("--out", default="page_counts.csv",
                    help="output CSV, relative to project root (default: page_counts.csv)")
    args = ap.parse_args()

    scan_root = os.path.join(ROOT, args.root)
    out_path = os.path.join(ROOT, args.out)
    if not os.path.isdir(scan_root):
        sys.exit(f"not a directory: {scan_root}")

    pdfs = []
    for dp, _, fns in os.walk(scan_root):
        for fn in fns:
            if fn.lower().endswith(".pdf"):
                pdfs.append(os.path.join(dp, fn))

    rows = []
    total_pages = readable = failed = 0
    fail_list = []
    with ProcessPoolExecutor() as ex:
        for path, n, err in ex.map(count, pdfs, chunksize=50):
            rel = os.path.relpath(path, scan_root)
            rows.append((rel, n))
            if err:
                failed += 1
                fail_list.append((rel, err))
            else:
                total_pages += n
                readable += 1

    rows.sort()
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["relpath", "pages"])
        w.writerows(rows)

    print(f"scanned:          {os.path.relpath(scan_root, ROOT)}/")
    print(f"PDF files found:  {len(pdfs):,}")
    print(f"Readable PDFs:    {readable:,}")
    print(f"Failed to open:   {failed:,}  (written with pages=-1)")
    print(f"TOTAL PAGES:      {total_pages:,}")
    if readable:
        print(f"Avg pages/PDF:    {total_pages / readable:.1f}")
    print(f"wrote:            {os.path.relpath(out_path, ROOT)}  ({len(rows):,} rows)")
    if fail_list:
        print("\nFirst few failures:")
        for p, e in fail_list[:5]:
            print(" -", p, "::", e[:80])


if __name__ == "__main__":
    sys.exit(main())
