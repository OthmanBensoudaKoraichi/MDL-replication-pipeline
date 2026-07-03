"""Stage 9: resolve Needs_Motion_Reading orders by reading the granted motion.

Some orders GRANT a motion to appoint leadership/class counsel WITHOUT naming the
appointees -- extract_orders.py flags these Needs_Motion_Reading=true. For each such
order this step:

  1. parses the motion's docket number cited in the order text, handling the forms
     "[15]", "(Docket No. 14)", "[ECF No. 33]", "(Doc. 12)", "Dkt. 9";
  2. locates that motion in the SAME MDL (matching the docket number to the motion's
     filename / ECF header);
  3. reads the motion's OCR text;
  4. extracts the requested appointees with gpt-5.5 and folds them into the order
     (sets Appointments, records Motion_Read_From, flips Needs_Motion_Reading=false).

When no docket number is cited (e.g. "...motion for appointment of leadership is
granted"), it falls back to a filename keyword match over the MDL's OCR'd motions
(returned LOW CONFIDENCE). Orders whose motion can't be found / isn't OCR'd stay
flagged, with a reason. Rebuilds order_extractions.xlsx at the end.

Usage:
    python resolve_motions.py --dry-run         # list flagged orders + located motions
    python resolve_motions.py --workers 6
"""
import argparse
import csv
import importlib.util
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(it, **kw):
        return it

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORDERS_DIR = os.path.join(ROOT, "orders")
OCR_DIR = os.path.join(ROOT, "ocr")
LABELS = os.path.join(ROOT, "type_labels.csv")
JSONL = os.path.join(ROOT, "order_extractions.jsonl")
MODEL = "gpt-5.5"
MAX_OUT_TOKENS = 16000     # a recommended slate can list 50-100+ appointees

# reuse the Appointee schema + Excel builder from stage 8 (no duplication)
_spec = importlib.util.spec_from_file_location("eo", os.path.join(ROOT, "code", "extract_orders.py"))
eo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eo)
Appointee = eo.Appointee


class MotionAppointees(BaseModel):
    """Appointees the motion REQUESTS be appointed."""
    Appointments: Optional[List[Appointee]] = Field(
        None, description="One Appointee per person/firm the motion asks the court to appoint.")


MOTION_SYS = """You are reading the underlying document that a court order GRANTED or ADOPTED without naming the appointees in the order itself -- either the MOTION the court granted, or the SPECIAL MASTER'S / RULE 53 REPORT & RECOMMENDATION the court adopted. Extract the people and firms this document proposes or recommends be appointed to leadership or a committee, using these rules (same as for orders):

- Create one Appointee per attorney or firm the document proposes/recommends for a leadership position or committee (a Special Master report typically lists a recommended SLATE or roster -- enumerate EVERY person and firm on it). last_name / first_name = the person's name; leave both null for a firm-only appointee. If a name appears as an initial, a middle name, and a last name (e.g. "W. Mark Lanier"), treat the initial as first_name.
- appointee_type: "Individual" for a person, "Firm" for a law firm. "Mark Lanier of the Lanier Law Firm" is an Individual.
- firm: the law firm (the individual's firm if stated, or the firm itself).
- plaintiff_defendant: the side this appointee represents.
- appointment_types: the role(s) requested for THIS appointee, only from: [LeadCounsel, Management, Communications, ClassCounsel, LocalCounsel, Discovery, Motions, Fees, Expert, Bellwether, Coordination, Settlement, Trial, SettlementAdministration, ProSe, Vetting]. LeadCounsel = lead/co-lead counsel; Management = steering or executive committee (only Management, nothing else); Communications = liaison counsel. Do NOT include Special Master, mediator, claims/notice/settlement administrator, escrow agent.
- appoint: true (these are proposed appointments). interim: true if the motion requests an interim appointment.

Return JSON {Appointments: [...]}. If the document does not actually name proposed/recommended appointees, return an empty list."""

# docket-reference patterns inside an order's text
REF_PATTERNS = [
    re.compile(r"\[(\d{1,6})\]"),
    re.compile(r"\(\s*Docket\s*(?:No\.?|#)?\s*(\d{1,6})\s*\)", re.I),
    re.compile(r"\[\s*ECF\s*(?:No\.?|#)?\s*(\d{1,6})\s*\]", re.I),
    re.compile(r"\(\s*(?:ECF|Doc)\.?\s*(?:No\.?|#)?\s*(\d{1,6})\s*\)", re.I),
    re.compile(r"\b(?:Dkt|ECF|Doc)\.?\s*(?:No\.?|#)?\s*(\d{1,6})\b", re.I),
]
SUBJECT_KWS = ["steering committee", "executive committee", "lead counsel", "co-lead", "liaison",
               "leadership", "class counsel", "plaintiffs' counsel", "plaintiff's counsel"]


def docket_of_filename(fn):
    """Docket number embedded in a filename, both corpora's conventions."""
    m = re.search(r"[,_]\s*Doc(?:ket)?\.?\s*#?\s*(\d+)", fn, re.I)
    if m:
        return m.group(1)
    m = re.search(r"_\d+(?:md|mc|cv)\d+_(\d+)_", fn, re.I)   # US_DIS_..._05md1654_10_... (md/mc/cv)
    return m.group(1) if m else None


MOTION_WORD_RE = re.compile(r"\b(motion|application|petition)s?\b", re.I)


def cited_dockets(order_text, filename=""):
    """Docket numbers the order cites for the motion it grants. Collects any
    bracket/parenthetical docket reference within ~90 chars of a 'motion'/'application'/
    'petition' mention, plus a motion number embedded in the order's own filename.
    Returns candidates in document order (locate_motion tries each)."""
    nums = []

    def add(n):
        if n and n not in nums:
            nums.append(n)

    for m in MOTION_WORD_RE.finditer(order_text):
        seg = order_text[max(0, m.start() - 30): m.end() + 90]
        for pat in REF_PATTERNS:
            for r in pat.finditer(seg):
                add(r.group(1))
    fm = re.search(r"\bmot\.?\s*#?\s*(\d{1,6})", filename, re.I)
    if fm:
        add(fm.group(1))
    return nums


def mdl_docket_index(mdl):
    """{docket_number: [relpath, ...]} for every doc in this MDL."""
    idx = {}
    with open(LABELS, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rel = r["relpath"]
            mm = re.match(r"^(\d+)", rel)
            if not (mm and mm.group(1) == mdl):
                continue
            dn = docket_of_filename(rel.split("/", 1)[1])
            if dn:
                idx.setdefault(dn, []).append((rel, r["llm_type"]))
    return idx


def ocr_full_text(rel):
    folder, fn = rel.split("/", 1)
    stem = fn[:-4] if fn.lower().endswith(".pdf") else fn
    jp = os.path.join(OCR_DIR, folder, stem + ".json")
    if not os.path.exists(jp):
        return None
    d = json.load(open(jp, encoding="utf-8"))
    pages = sorted(d.get("pages", []), key=lambda p: p.get("page", 0))
    return "\n".join(p.get("text", "") for p in pages)


def order_text_of(rel):
    folder, fn = rel.split("/", 1)
    stem = fn[:-4] if fn.lower().endswith(".pdf") else fn
    jp = os.path.join(ORDERS_DIR, folder, stem + ".json")
    if os.path.exists(jp):
        return json.load(open(jp, encoding="utf-8")).get("text", "")
    return ocr_full_text(rel) or ""


def locate_motion(mdl, order_text, filename=""):
    """Return (motion_relpath, how) or (None, reason). Primary: the docket number cited
    in the order. Fallback (no number cited): filename keyword match over the MDL's
    OCR'd motions, returned LOW CONFIDENCE."""
    idx = mdl_docket_index(mdl)
    for dn in cited_dockets(order_text, filename):
        cands = idx.get(dn, [])
        motions = [rel for rel, lt in cands if lt == "MOTION"] or [rel for rel, lt in cands]
        for rel in motions:                                  # prefer a motion that already has OCR
            if ocr_full_text(rel) is not None:
                return rel, f"cited docket {dn}"
        for rel in motions:                                  # else take one we can OCR on demand
            if os.path.exists(os.path.join(ROOT, "files", rel)):
                return rel, f"cited docket {dn} (OCR'd on demand)"
        if cands:
            return None, f"cited docket {dn} found but no source PDF to OCR"
    # no-number fallback: match the order's subject keywords against the MDL's OCR'd motions
    kws = [k for k in SUBJECT_KWS if k in order_text.lower()]
    if kws:
        best, best_score = None, 0
        for cands in idx.values():
            for rel, lt in cands:
                if lt != "MOTION":
                    continue
                fnl = rel.split("/", 1)[1].lower()
                score = sum(1 for k in kws if k in fnl)
                if score > best_score and ocr_full_text(rel) is not None:
                    best, best_score = rel, score
        if best:
            return best, f"keyword fallback ({best_score} subject terms, no docket cited) -- LOW CONFIDENCE"
    return None, "no cited docket and no keyword match (no-number case)"


# ---- Special Master / Rule 53 report references (generalizes resolve to non-motion sources) ----
# An order that ADOPTS/APPROVES a Special Master's report names no appointees itself; the recommended
# slate lives in the report. Report docs are classified ORDER (classify_type keys on "report and
# recommendation"), so they are OCR'd whenever the MDL is processed -- available to read here.
REPORT_TRIGGER_RE = re.compile(
    r"(adopt|approv|accept|confirm|overrul\w*\s+(?:the\s+)?objection)[\w\s,'\-]{0,70}"
    r"(special\s*master|rule\s*53|report|recommendation)", re.I | re.S)
REPORT_FN_RE = re.compile(
    r"special\s*master|spec\.?\s*master|report\s*(?:and\s*)?recomm|recommendation|rule\s*53|\br\s*&\s*r\b", re.I)
REPORT_WORD_RE = re.compile(r"\b(report|recommendation|special\s*master|rule\s*53)\b", re.I)
SUBJ_VOCAB = {"committee", "committees", "chair", "chairs", "chairman", "member", "members", "leadership",
              "steering", "executive", "liaison", "lead", "colead", "co", "counsel", "plaintiff",
              "plaintiffs", "defendant", "defendants", "interim", "settlement", "discovery", "science",
              "class", "subscriber", "monitoring", "fee", "expense", "psc", "local", "trial", "bellwether"}


def subject_tokens(s):
    return {t for t in re.findall(r"[a-z]+", (s or "").lower()) if t in SUBJ_VOCAB}


def mdl_docs(mdl):
    """[(relpath, llm_type)] for every doc in this MDL (all types, incl. filtered-out)."""
    out = []
    with open(LABELS, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            mm = re.match(r"^(\d+)", r["relpath"])
            if mm and mm.group(1) == mdl:
                out.append((r["relpath"], r["llm_type"]))
    return out


def locate_report(mdl, order_text, filename=""):
    """Locate the Special Master / Rule 53 report an order ADOPTS. Returns (relpath, how) or
    (None, reason). Only fires when the order's text shows report-adoption language. Picks the
    report doc (by filename) whose SUBJECT best overlaps the order's subject -- so 'adopting the
    report on Committee Chairs/Members' maps to the committee report, not the leadership report.
    Language- and keyword-driven (no MDL-specific rules), so it generalizes to unseen MDLs."""
    if not REPORT_TRIGGER_RE.search(order_text):
        return None, "no report-adoption language"
    idx = mdl_docket_index(mdl)
    # 1) a docket number cited near a 'report'/'special master' mention
    nums = []
    for m in REPORT_WORD_RE.finditer(order_text):
        seg = order_text[max(0, m.start() - 40): m.end() + 60]
        for pat in REF_PATTERNS:
            for r in pat.finditer(seg):
                if r.group(1) not in nums:
                    nums.append(r.group(1))
    for dn in nums:
        for rel, _lt in idx.get(dn, []):
            if REPORT_FN_RE.search(rel.split("/", 1)[1]) and ocr_full_text(rel) is not None:
                return rel, f"adopts report at cited docket {dn}"
    # 2) keyword + subject-overlap over the MDL's OCR'd report docs
    order_subj = subject_tokens(filename + " " + order_text[:400])
    best, best_score = None, -1
    for rel, _lt in mdl_docs(mdl):
        fn = rel.split("/", 1)[1]
        if not REPORT_FN_RE.search(fn) or ocr_full_text(rel) is None:
            continue
        score = len(order_subj & subject_tokens(fn))
        if score > best_score:
            best, best_score = rel, score
    if best and best_score >= 1:
        return best, f"adopts Special Master/Rule 53 report (subject overlap {best_score})"
    if best:
        return best, "adopts a report (only OCR'd report in MDL; no subject overlap) -- LOW CONFIDENCE"
    return None, "report-adoption language but no OCR'd report doc found in MDL"


def locate_source(mdl, order_text, filename=""):
    """Find the document an order draws its appointees from: the granted MOTION first, then the
    adopted Special Master / Rule 53 REPORT."""
    rel, how = locate_motion(mdl, order_text, filename)
    if rel:
        return rel, how
    rel2, how2 = locate_report(mdl, order_text, filename)
    if rel2:
        return rel2, how2
    return None, f"{how}; {how2}"


# ---- on-demand OCR of referenced roster exhibits ----
# A report's recommended slate is often in a sub-docket EXHIBIT (Doc N-M) that the filter dropped as
# OTHER and never OCR'd. Those PDFs still live in files/, so we OCR them on demand (cached to ocr/).
ROSTER_KW_RE = re.compile(
    r"chair|member|committee|steering|executive|leadership|lead|counsel|liaison|position|recommend|"
    r"slate|schedule|roster|psc|class", re.I)


def _files_dir(mdl):
    for f in os.listdir(os.path.join(ROOT, "files")):
        if re.match(rf"^{mdl}\b", f) and os.path.isdir(os.path.join(ROOT, "files", f)):
            return f
    return None


def ocr_cache_path(rel):
    folder, fn = rel.split("/", 1)
    stem = fn[:-4] if fn.lower().endswith(".pdf") else fn
    return os.path.join(OCR_DIR, folder, stem + ".json")


def ondemand_ocr(rel):
    """OCR a PDF from files/ (e.g. a filtered-out exhibit) via LlamaParse, cache to ocr/, return text.
    Reuses existing OCR if present. None on failure."""
    existing = ocr_full_text(rel)
    if existing is not None:
        return existing
    path = os.path.join(ROOT, "files", rel)
    if not os.path.exists(path):
        return None
    try:
        import asyncio
        from llama_cloud import AsyncLlamaCloud

        async def _run():
            client = AsyncLlamaCloud(api_key=os.getenv("llamaparse_api_key"), max_retries=4)
            data = open(path, "rb").read()
            fobj = await client.files.create(file=(os.path.basename(path), data, "application/pdf"), purpose="parse")
            res = await client.parsing.parse(file_id=fobj.id, tier="fast", version="latest", expand=["text"])
            pages = getattr(getattr(res, "text", None), "pages", None) or []
            return ([{"page": p.page_number, "text": p.text or ""} for p in pages]
                    or [{"page": 1, "text": getattr(res, "text_full", "") or ""}])
        pages = asyncio.run(_run())
        cp = ocr_cache_path(rel)
        os.makedirs(os.path.dirname(cp), exist_ok=True)
        json.dump({"relpath": rel, "pages": pages}, open(cp + ".tmp", "w", encoding="utf-8"), ensure_ascii=False)
        os.replace(cp + ".tmp", cp)
        return "\n".join(p["text"] for p in pages)
    except Exception:  # noqa: BLE001
        return None


def roster_exhibits(mdl, report_rel):
    """Sibling sub-docket exhibits (Doc N-M) of a report at docket N whose filename is roster-like."""
    base = docket_of_filename(report_rel.split("/", 1)[1])
    fdir = _files_dir(mdl)
    if not base or not fdir:
        return []
    out = []
    for fn in sorted(os.listdir(os.path.join(ROOT, "files", fdir))):
        if fn.lower().endswith(".pdf") and re.search(rf"Doc\.?\s*#?\s*{base}-\d+\b", fn) and ROSTER_KW_RE.search(fn):
            out.append(f"{fdir}/{fn}")
    return out


def source_text(mdl, rel, how):
    """Text to extract appointees from. For an adopted REPORT, append its roster exhibits (the slate
    usually lives in a sub-docket exhibit), OCR'd on demand."""
    base = ocr_full_text(rel) or ondemand_ocr(rel) or ""   # OCR the motion/report on demand if it wasn't already
    if "report" in how.lower():
        for ex in roster_exhibits(mdl, rel):
            t = ondemand_ocr(ex)
            if t:
                base += f"\n\n--- EXHIBIT {os.path.basename(ex)} ---\n{t}"
    return base


def extract_from_motion(client, motion_text):
    comp = client.beta.chat.completions.parse(
        model=MODEL,
        messages=[{"role": "system", "content": MOTION_SYS},
                  {"role": "user", "content": motion_text[:60000]}],
        response_format=MotionAppointees,
        max_completion_tokens=MAX_OUT_TOKENS)
    return comp.choices[0].message.parsed


# ---- reappointment inheritance + fee/settlement exclusion (deterministic, no LLM) ----
# A reappointment/renewal order names no one; it points at a PRIOR appointing order (often by docket).
# Since we already extracted that prior order, we INHERIT its slate from our own jsonl -- no LLM call.
# A pure fee/settlement-approval order that appoints no one is dropped (project scope = appointments
# only). Inheritance is flagged for review: a later substitution (sometimes in a member case we don't
# hold) can change the slate, so an inherited roster may be slightly stale.
REAPPOINT_RE = re.compile(r"\b(re-?appoint\w*|renew\w*|re-?establish\w*|previously\s+appointed|prior\s+appointment)\b", re.I)
REAPPOINT_TITLE_RE = re.compile(r"re-?appoint|reappointment|renew", re.I)
APPOINT_TITLE_RE = re.compile(r"appoint|substitut", re.I)
# NOTE: the approval branches require "settlem..." (a settlement approval) -- the bare token "class"
# is deliberately NOT here, because "Order Approving Class Counsel" / "Granting Approval of Class
# Counsel" are Rule-23 class-counsel APPOINTMENT orders, not fee/settlement orders, and must not be dropped.
FEE_DROP_TITLE_RE = re.compile(
    r"\bfees?\b|attn?ys?_?\s*fee|dismissal|"
    r"settlem\w*.{0,18}(appr|aprvl|approv|app['_]?l|final|prelim)|"
    r"(appr|aprvl|approv|app['_]?l|final|prelim).{0,18}settlem\w*", re.I)
DOCKET_REF_RE = re.compile(r"(?:Docket|Doc|ECF|Dkt)\.?\s*(?:No\.?|#)?\s*(\d{1,6})", re.I)

PRIOR = {}   # (mdl, docket_str) -> {"appts","rel","order_no","date"} for extracted orders WITH appointees


def build_prior_index(recs):
    """Index every already-extracted appointment-bearing order by (mdl, docket) so a reappointment
    order can inherit the slate of the prior order it renews."""
    PRIOR.clear()
    for r in recs:
        appts = r.get("Appointments") or []
        if not appts:
            continue
        rel = r.get("Source_File", "")
        mdl = str(r.get("MDL_No") or (re.match(r"^(\d+)", rel).group(1) if re.match(r"^(\d+)", rel) else ""))
        dk = r.get("Docket_No")
        if dk is None or not mdl:
            continue
        PRIOR[(mdl, str(dk))] = {"appts": appts, "rel": rel,
                                 "order_no": r.get("Order_No") or f"{mdl}-{dk}", "date": r.get("Date") or ""}


def cited_order_dockets(text):
    """Every docket number an order cites anywhere in its text (for following a renewed prior order)."""
    nums = []
    for pat in list(REF_PATTERNS) + [DOCKET_REF_RE]:
        for m in pat.finditer(text or ""):
            n = m.group(1)
            if n not in nums:
                nums.append(n)
    return nums


def _iso(s):
    """YYYY-MM-DD prefix of a date string, or '' if it isn't a parseable ISO date (ISO strings compare
    lexicographically, so '' guards against empty / non-ISO dates being mis-ordered)."""
    m = re.match(r"\s*(\d{4}-\d{2}-\d{2})", str(s or ""))
    return m.group(1) if m else ""


def inherit_reappointment(mdl, rec, otext, allow_fallback):
    """Inherit the slate of the prior appointing order this reappointment renews. Prefer the cited
    prior-order docket (the order usually names it, e.g. 'Docket No. 64'), but never inherit from an
    order KNOWN to be dated on/after this one. Only when the TITLE clearly says reappoint/renew
    (allow_fallback) do we fall back to the most recent STRICTLY-EARLIER appointment-bearing order in
    the MDL whose roles overlap -- and the fallback needs a parseable date on both sides to order them
    safely. Returns a dict or None."""
    rdate = _iso(rec.get("Date"))
    cited = [d for d in cited_order_dockets(otext) if (mdl, d) in PRIOR and PRIOR[(mdl, d)]["appts"]]
    # drop cited dockets we KNOW are dated on/after this order (not the original appointment)
    cited_ok = [d for d in cited
                if not (rdate and _iso(PRIOR[(mdl, d)]["date"]) and _iso(PRIOR[(mdl, d)]["date"]) >= rdate)]
    pool = cited_ok or cited                       # if dates rule all out, fall back to the explicit citation
    if pool:
        best = max(pool, key=lambda d: len(PRIOR[(mdl, d)]["appts"]))    # the main appointing order
        p = PRIOR[(mdl, best)]
        return {"appts": [dict(a) for a in p["appts"]], "src_rel": p["rel"],
                "how": f"inherited from {p['order_no']} (reappointment; cited Docket {best})"}
    if not allow_fallback or not rdate:            # no docket cited and no comparable date -> too weak to guess
        return None
    rtypes = set(rec.get("Order_Types") or [])
    cands = []
    for (m, dk), p in PRIOR.items():
        pd = _iso(p["date"])
        if m != mdl or not pd or pd >= rdate:      # require a parseable, STRICTLY-earlier date
            continue
        roles = set().union(*[set(a.get("appointment_types") or []) for a in p["appts"]]) if p["appts"] else set()
        cands.append(((bool(roles & rtypes) if rtypes else True), pd, p))
    if not cands:
        return None
    cands.sort(key=lambda c: (c[0], c[1]), reverse=True)    # role-overlap first, then most recent
    p = cands[0][2]
    return {"appts": [dict(a) for a in p["appts"]], "src_rel": p["rel"],
            "how": f"inherited from {p['order_no']} (reappointment; no resolvable docket -- most recent prior appointment)"}


def decide_source(mdl, rec, otext, fn):
    """Decide how a flagged order gets its appointees, WITHOUT calling the LLM. kind:
    'read' (motion/report to LLM-extract), 'inherit' (deterministic slate from a prior order),
    'fee' (fee/settlement order -> exclude), 'none' (unresolved)."""
    src, how = locate_source(mdl, otext, fn)
    if src:
        return {"kind": "read", "source": src, "how": how}
    if REAPPOINT_RE.search(otext) or REAPPOINT_TITLE_RE.search(fn):
        inh = inherit_reappointment(mdl, rec, otext, bool(REAPPOINT_TITLE_RE.search(fn)))
        if inh:
            return {"kind": "inherit", "source": inh["src_rel"], "how": inh["how"], "appts": inh["appts"]}
    if FEE_DROP_TITLE_RE.search(fn) and not APPOINT_TITLE_RE.search(fn):
        return {"kind": "fee", "source": None, "how": "fee/settlement-approval order (no appointment) -- excluded"}
    return {"kind": "none", "source": None, "how": how}


def resolve_one(client, rec):
    rel = rec.get("Source_File", "")
    mdl = (rec.get("MDL_No") or (re.match(r"^(\d+)", rel).group(1) if re.match(r"^(\d+)", rel) else "")) or ""
    d = decide_source(mdl, rec, order_text_of(rel), os.path.basename(rel))
    if d["kind"] == "read":
        text = source_text(mdl, d["source"], d["how"])
        if not text:
            return rel, None, d["source"], "located but no readable text", "none"
        try:
            parsed = extract_from_motion(client, text)
            appts = [a.model_dump() for a in (parsed.Appointments or [])]
        except Exception as e:  # noqa: BLE001
            return rel, None, d["source"], f"extract error: {type(e).__name__}: {str(e)[:80]}", "none"
        return rel, appts, d["source"], d["how"], "read"
    if d["kind"] == "inherit":
        return rel, d["appts"], d["source"], d["how"], "inherit"
    if d["kind"] == "fee":
        return rel, [], None, d["how"], "fee"
    return rel, None, None, d["how"], "none"


def preflight_model(client, model, fallback="gpt-5"):
    """Confirm the chat model id resolves on this API key BEFORE spawning workers (fail fast).
    Returns the working id (the requested model, or the fallback), or None."""
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
    global MODEL
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=16,
                    help="concurrent LLM requests; raise for throughput (rate limits self-throttle via SDK retries)")
    ap.add_argument("--model", default=MODEL,
                    help="chat model id (default %(default)s; falls back to gpt-5 if unavailable)")
    ap.add_argument("--dry-run", action="store_true", help="locate motions, no LLM, no write")
    args = ap.parse_args()
    MODEL = args.model

    if not os.path.exists(JSONL):
        sys.exit("no order_extractions.jsonl -- run extract_orders.py first")
    recs = [json.loads(l) for l in open(JSONL, encoding="utf-8") if l.strip()]
    build_prior_index(recs)   # index extracted orders so reappointments can inherit a prior slate
    flagged = [r for r in recs if r.get("Needs_Motion_Reading") is True and not (r.get("Appointments") or [])]
    print(f"orders flagged Needs_Motion_Reading (no appointees): {len(flagged)}")
    if not flagged:
        print("nothing to resolve.")
        return 0

    if args.dry_run:
        from collections import Counter
        kc = Counter()
        for r in flagged:
            rel = r.get("Source_File", "")
            mdl = r.get("MDL_No") or (re.match(r"^(\d+)", rel).group(1) if re.match(r"^(\d+)", rel) else "")
            d = decide_source(mdl, r, order_text_of(rel), os.path.basename(rel))
            kc[d["kind"]] += 1
            extra = f"  ({len(d['appts'])} appointees)" if d["kind"] == "inherit" else ""
            print(f"  [{d['kind']:7}] {rel.split('/',1)[-1][:52]:52s} -> {d['how']}{extra}")
        print("\nplan: " + ", ".join(f"{k}={v}" for k, v in sorted(kc.items())))
        return 0

    load_dotenv(os.path.join(ROOT, ".env"))
    if not os.getenv("OPENAI_API_KEY"):
        print("missing OPENAI_API_KEY", file=sys.stderr)
        return 1
    from openai import OpenAI
    client = OpenAI(max_retries=5)

    chosen = preflight_model(client, MODEL)
    if not chosen:
        print(f"model '{MODEL}' (and fallback) unavailable -- aborting", file=sys.stderr)
        return 1
    if chosen != MODEL:
        print(f"  preflight: using fallback model '{chosen}'")
        MODEL = chosen

    by_src = {}      # src -> (appts, source, how, kind) for every flagged order we acted on
    resolved = located = inherited = excluded = 0
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(resolve_one, client, r) for r in flagged]
        for fut in tqdm(as_completed(futs), total=len(futs), unit="order", desc="resolve"):
            rel, appts, source, how, kind = fut.result()
            short = rel.split('/', 1)[-1][:48]
            with lock:
                if kind in ("read", "inherit") and appts is not None:
                    by_src[rel] = (appts, source, how, kind)
                    if kind == "inherit":
                        inherited += 1
                        print(f"  INHERITED {short} <- {how} ({len(appts)} appointees)")
                    else:
                        located += 1
                        if appts:
                            resolved += 1
                            print(f"  RESOLVED {short} <- {(source or '').split('/',1)[-1][:40]} ({len(appts)} appointees)")
                        else:
                            print(f"  read, no appointees {short}")
                elif kind == "fee":
                    excluded += 1
                    by_src[rel] = ([], None, how, "fee")
                    print(f"  EXCLUDED (fee/settlement) {short}")
                else:
                    print(f"  unresolved {short} :: {how}")   # stays flagged for retry

    # fold results back into the jsonl. read/inherit clear the flag (even with 0 appointees, so a
    # genuinely-empty source is not re-read); fee orders clear the flag with NO appointees so
    # keep_order drops them from the workbook as non-appointment orders.
    for r in recs:
        src = r.get("Source_File", "")
        if src not in by_src:
            continue
        appts, source, how, kind = by_src[src]
        r["Needs_Motion_Reading"] = False
        if kind == "fee":
            r["Motion_Read_Result"] = "excluded: fee/settlement order (no appointment)"
            r["Provenance"] = "excluded-fee"
            continue
        if appts:
            r["Appointments"] = appts
        r["Motion_Read_From"] = source
        low = " (low-confidence)" if "LOW CONFIDENCE" in (how or "") else ""
        if kind == "inherit":
            r["Motion_Read_Result"] = how
            r["Provenance"] = "inherited-reappointment (verify)"
            note = r.get("Notes") or ""
            r["Notes"] = (note + " | " if note else "") + f"[{how}] -- verify against any later substitution/removal"
        else:
            r["Motion_Read_Result"] = "appointees extracted" if appts else "motion read - no appointees named"
            r["Provenance"] = ("report-read" if "report" in (how or "").lower() else "motion-read") + low
    tmp = JSONL + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, JSONL)        # atomic: a crash mid-write can't truncate the live jsonl

    print(f"\nDONE: flagged {len(flagged)} | motion/report read {located} (with appointees {resolved}) "
          f"| inherited (reappointment) {inherited} | excluded (fee/settlement) {excluded} "
          f"| still unresolved {len(flagged) - located - inherited - excluded}")
    eo.build_excel()
    return 0


if __name__ == "__main__":
    sys.exit(main())
