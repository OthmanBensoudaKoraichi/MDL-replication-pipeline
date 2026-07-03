"""OCR the filtered documents to plain text with LlamaParse (fast tier),
concurrently.

For each target MDL it reads filtered_files/<MDL>/<doc>.pdf, sends it to
LlamaParse (tier="fast", per-page text), and writes one JSON per doc to
ocr/<MDL>/<doc>.json:

    {
      "relpath": "<folder>/<file>.pdf",
      "mdl": "2263",
      "filename": "<file>.pdf",
      "n_pages": 8,
      "n_chars": 11113,
      "pages": [ {"page": 1, "chars": 1234, "text": "..."}, ... ]
    }

Per-page text + page numbers are kept so a downstream step can locate the
order's signature page (last page mentioning "judge"), trim trailing junk, and
record the derived span back into the same record. Re-runnable: a doc whose
.json already exists (non-empty) is skipped. A manifest at ocr/_manifest.csv
records per-doc status / chars / pages / errors.

Needs llamaparse_api_key in the project-root .env.

Usage:
    python ocr_llamaparse.py --dry-run            # list what would be parsed
    python ocr_llamaparse.py --limit 2            # parse just 2 (validation)
    python ocr_llamaparse.py --workers 8          # full run, 8 concurrent
    python ocr_llamaparse.py --mdls 2741,2818     # restrict to some MDLs
"""
import argparse
import asyncio
import csv
import json
import os
import re
import sys
import time

import fitz  # PyMuPDF: split large PDFs into page batches
from dotenv import load_dotenv

try:
    from tqdm import tqdm
except ImportError:  # minimal fallback bar
    class tqdm:  # noqa: N801
        def __init__(self, total=0, **k):
            self.total = total; self.n = 0
        def update(self, k=1):
            self.n += k
            if self.n % 25 == 0:
                print(f"  {self.n}/{self.total}")
        def write(self, m):
            print(m)
        def close(self):
            pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT, "filtered_files")
OUT_DIR = os.path.join(ROOT, "ocr")
MANIFEST = os.path.join(OUT_DIR, "_manifest.csv")

# the current working set (random sample of 10)
DEFAULT_MDLS = ["2263", "2428", "2504", "2570", "2664",
                "2687", "2741", "2818", "2873", "2878"]
TIER = "fast"
VERSION = "latest"
# Large/dense PDFs can stall in the fast-tier queue, so split them into page
# batches, parse each concurrently, and merge back. Docs <= threshold go whole.
CHUNK_THRESHOLD = 10   # pages: docs longer than this are split
CHUNK_SIZE = 10        # pages per batch (small batches clear the fast-tier queue fast)


def target_pdfs(mdls):
    """[(relpath, src_abs, out_abs)] for every kept PDF in the target MDLs."""
    want = set(mdls)
    out = []
    for folder in sorted(os.listdir(SRC_DIR)):
        d = os.path.join(SRC_DIR, folder)
        if not os.path.isdir(d):
            continue
        m = re.match(r"^(\d+)", folder)
        if not (m and m.group(1) in want):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.lower().endswith(".pdf"):
                rel = f"{folder}/{fn}"
                stem = fn[:-4] if fn.lower().endswith(".pdf") else fn
                out.append((rel, os.path.join(d, fn),
                            os.path.join(OUT_DIR, folder, stem + ".json")))
    return out


def already_done(out_abs):
    return os.path.exists(out_abs) and os.path.getsize(out_abs) > 0


def _page_count(src):
    with fitz.open(src) as d:
        return d.page_count


def _batch_bytes(src, start, end):
    """Bytes of a sub-PDF with 0-indexed pages [start, end)."""
    with fitz.open(src) as d, fitz.open() as nd:
        nd.insert_pdf(d, from_page=start, to_page=end - 1)
        return nd.tobytes()


async def _parse_payload(client, sem, name, data, tier, attempt_timeout, retries):
    """Upload bytes + parse one (sub-)PDF -> [(local_page_number, text)].

    Each attempt is bounded by attempt_timeout; a stalled job (LlamaCloud queue
    stalls are intermittent) is abandoned and a fresh one submitted, up to
    `retries` times. The semaphore slot is released between attempts.
    """
    last = None
    for attempt in range(1, retries + 1):
        try:
            async with sem:
                async def _fetch():
                    fobj = await client.files.create(
                        file=(name, data, "application/pdf"), purpose="parse")
                    return await client.parsing.parse(
                        file_id=fobj.id, tier=tier, version=VERSION, expand=["text"])
                res = await asyncio.wait_for(_fetch(), timeout=attempt_timeout)
            pages = getattr(getattr(res, "text", None), "pages", None) or []
            out = [(p.page_number, p.text or "") for p in pages]
            if not out:  # fallback if per-page text is unavailable
                out = [(1, getattr(res, "text_full", None) or "")]
            return out
        except Exception as e:  # noqa: BLE001 - timeout or transient API error -> retry
            last = e
            if attempt < retries:
                await asyncio.sleep(2 * attempt)
    raise last


def _ocr_tesseract(src, start, end):
    """Local OCR fallback for pages [start, end) (0-indexed) when LlamaParse fails
    on a batch. Uses the embedded text layer when a page has one, else Tesseract on
    a 300-DPI render. Returns [(local_page_number, text, source)]."""
    import io
    import pytesseract
    from PIL import Image
    out = []
    with fitz.open(src) as d:
        for i in range(start, end):
            pg = d[i]
            t = pg.get_text("text").strip()
            if len(t) >= 100:                       # good embedded text -> use it
                out.append((i - start + 1, t, "text-layer"))
            else:                                   # scanned/image page -> Tesseract
                pix = pg.get_pixmap(dpi=300)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                out.append((i - start + 1, pytesseract.image_to_string(img).strip(), "tesseract"))
    return out


async def _batch_with_fallback(client, sem, name, src, start, end, tier, attempt_timeout, retries):
    """Parse pages [start, end) with LlamaParse; on failure, OCR them locally.
    Returns (start, [(local_page_number, text, source)])."""
    data = await asyncio.to_thread(_batch_bytes, src, start, end)
    try:
        pages = await _parse_payload(
            client, sem, f"{name}.p{start+1}-{end}.pdf", data, tier, attempt_timeout, retries)
        return (start, [(pn, txt, "llamaparse") for pn, txt in pages])
    except Exception:  # noqa: BLE001 - LlamaParse stalled/failed -> local OCR fallback
        pages = await asyncio.to_thread(_ocr_tesseract, src, start, end)
        return (start, pages)


async def parse_one(client, sem, rel, src, out, tier, attempt_timeout, retries, results, lock, pbar):
    t0 = time.monotonic()
    name = os.path.basename(src)
    try:
        npages = await asyncio.to_thread(_page_count, src)
        if npages <= 0:
            raise RuntimeError("0 pages / unreadable")
        # always split into <=CHUNK_SIZE-page batches; each falls back to local OCR on failure
        starts = list(range(0, npages, CHUNK_SIZE))
        batches = await asyncio.gather(*[
            _batch_with_fallback(client, sem, name, src, s, min(s + CHUNK_SIZE, npages),
                                 tier, attempt_timeout, retries)
            for s in starts])

        # merge batches, renumbering local pages to global (1-indexed)
        page_list = []
        for off, pages in batches:
            for local_pn, text, source in pages:
                page_list.append({"page": off + local_pn, "chars": len(text),
                                  "source": source, "text": text})
        page_list.sort(key=lambda x: x["page"])
        fb = sum(1 for p in page_list if p["source"] != "llamaparse")

        mm = re.match(r"^(\d+)", rel)
        doc = {
            "relpath": rel,
            "mdl": mm.group(1) if mm else "",
            "filename": name,
            "n_pages": len(page_list),
            "n_chars": sum(p["chars"] for p in page_list),
            "n_batches": len(starts),
            "fallback_pages": fb,
            "pages": page_list,
        }
        os.makedirs(os.path.dirname(out), exist_ok=True)
        tmp = out + ".tmp"          # atomic write: a crash can't leave a half-written .json
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        os.replace(tmp, out)
        note = f"{fb} fallback (tesseract/text-layer) pages" if fb else ""
        row = [rel, "ok", doc["n_chars"], doc["n_pages"], round(time.monotonic() - t0, 1), note]
    except asyncio.TimeoutError:
        row = [rel, "error", 0, 0, round(time.monotonic() - t0, 1),
               f"timeout >{attempt_timeout}s after {retries} tries"]
    except Exception as e:  # noqa: BLE001
        row = [rel, "error", 0, 0, round(time.monotonic() - t0, 1),
               f"{type(e).__name__}: {str(e)[:160]}"]
    async with lock:
        results.append(row)
        pbar.update(1)
        if row[1] == "error":
            pbar.write(f"  ERROR {rel[:70]} :: {row[5]}")
    return row


async def run(pdfs, workers, tier, attempt_timeout, retries, pbar):
    key = os.getenv("llamaparse_api_key")
    if not key:
        sys.exit("missing llamaparse_api_key in .env")
    from llama_cloud import AsyncLlamaCloud
    client = AsyncLlamaCloud(api_key=key, max_retries=6)

    sem = asyncio.Semaphore(workers)
    lock = asyncio.Lock()
    results = []
    await asyncio.gather(*[
        parse_one(client, sem, rel, src, out, tier, attempt_timeout, retries, results, lock, pbar)
        for rel, src, out in pdfs])
    return results


def write_manifest(results):
    os.makedirs(OUT_DIR, exist_ok=True)
    have = {}
    if os.path.exists(MANIFEST):
        with open(MANIFEST, newline="") as f:
            for r in csv.reader(f):
                if r and r[0] != "relpath":
                    have[r[0]] = r
    for r in results:
        have[r[0]] = r
    tmp = MANIFEST + ".tmp"        # atomic: never lose the manifest to a mid-write crash
    with open(tmp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["relpath", "status", "chars", "pages", "seconds", "error"])
        for rel in sorted(have):
            w.writerow(have[rel])
    os.replace(tmp, MANIFEST)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mdls", help="comma-separated MDL numbers (default: the 10-sample)")
    ap.add_argument("--all", action="store_true", help="every MDL present in filtered_files/")
    ap.add_argument("--exclude-file", help="path to a file of MDL numbers (one per line) to SKIP; implies --all over the rest")
    ap.add_argument("--workers", type=int, default=24, help="concurrent requests (default 24)")
    ap.add_argument("--batch", type=int, default=1000, help="docs per asyncio group (bounds in-flight tasks; manifest saved each batch)")
    ap.add_argument("--tier", default=TIER, help="LlamaParse tier (default fast)")
    ap.add_argument("--attempt-timeout", type=float, default=120,
                    help="per-attempt hard timeout in seconds (default 120); a stalled job is abandoned and retried")
    ap.add_argument("--retries", type=int, default=3,
                    help="attempts per (sub-)doc before giving up (default 3)")
    ap.add_argument("--limit", type=int, help="only the first N not-yet-done docs")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    load_dotenv(os.path.join(ROOT, ".env"))

    all_mdls = sorted({m.group(1) for f in os.listdir(SRC_DIR)
                       if os.path.isdir(os.path.join(SRC_DIR, f)) and (m := re.match(r"^(\d+)", f))}, key=int)
    if args.mdls:
        mdls = [s.strip() for s in args.mdls.split(",")]
    elif args.exclude_file:
        excl = {l.strip() for l in open(args.exclude_file) if l.strip()}
        mdls = [x for x in all_mdls if x not in excl]
    elif args.all:
        mdls = all_mdls
    else:
        mdls = DEFAULT_MDLS

    allp = target_pdfs(mdls)
    todo = [(rel, src, out) for rel, src, out in allp if not already_done(out)]
    if args.limit:
        todo = todo[:args.limit]

    print(f"MDLs selected: {len(mdls):,}")
    print(f"target docs: {len(allp):,} | already done: {len(allp) - len([1 for r,s,o in allp if not already_done(o)]):,} | to parse now: {len(todo):,}")
    print(f"tier: {args.tier} | workers: {args.workers} | batch: {args.batch} | output: ocr/<MDL>/<doc>.json")
    if args.dry_run or not todo:
        for rel, _, _ in todo[:20]:
            print("   would parse:", rel[:90])
        if not args.dry_run and not todo:
            print("nothing to do.")
        return 0

    t0 = time.monotonic()
    pbar = tqdm(total=len(todo), unit="doc", desc="ocr")
    ok = partial = err = chars = 0
    for i in range(0, len(todo), args.batch):
        chunk = todo[i:i + args.batch]
        results = asyncio.run(run(chunk, args.workers, args.tier, args.attempt_timeout, args.retries, pbar))
        write_manifest(results)
        ok += sum(1 for r in results if r[1] == "ok")
        partial += sum(1 for r in results if r[1] == "partial")
        err += sum(1 for r in results if r[1] == "error")
        chars += sum(r[2] for r in results)
    pbar.close()
    print(f"\nDONE: ok={ok} partial={partial} error={err} | {chars:,} chars | "
          f"{time.monotonic()-t0:.0f}s | manifest: {os.path.relpath(MANIFEST, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
