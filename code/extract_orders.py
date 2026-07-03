"""Stage 7: structured extraction of MDL leadership-order data into the three
Airtable tables (Orders, Appointments, Attorneys).

Reads the signature-trimmed order text from orders/<MDL>/<doc>.json and, per
order, asks gpt-5.5 to fill an MDLOrderOut schema (order-level fields + a list of
structured Appointee objects) via the OpenAI SDK's native Pydantic structured
output -- no LangChain.

Each order's full extraction streams to order_extractions.jsonl (resumable). The
Excel workbook order_extractions.xlsx is then built from it with three tabs:
  - Orders       : one row per order
  - Appointments : one row per appointed/removed person or firm (linked by Order_No)
  - Attorneys    : deduped roster of appointees (names filled; demographics blank
                   for later research)

Needs OPENAI_API_KEY in .env.

Usage:
    python extract_orders.py --dry-run         # count inputs, no API calls
    python extract_orders.py --limit 3          # small metered validation
    python extract_orders.py --workers 8        # full run
    python extract_orders.py --contains appoint # spot-check appointment orders
    python extract_orders.py --excel-only       # rebuild the workbook from the jsonl
"""
import argparse
import collections
import csv
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(it, **kw):
        return it

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORDERS_DIR = os.path.join(ROOT, "orders")
JSONL = os.path.join(ROOT, "order_extractions.jsonl")
XLSX = os.path.join(ROOT, "order_extractions.xlsx")
MODEL = "gpt-5.5"           # if this 404s, try "gpt-5"
MAX_OUT_TOKENS = 32000      # reasoning + nested JSON; emitting both Individual+Firm rows ~doubles a large roster
PRICE_IN, PRICE_OUT = 5.0, 30.0   # gpt-5.5 $/1M (rough) for the cost estimate

DEFAULT_MDLS = ["2263", "2428", "2504", "2570", "2664",
                "2687", "2741", "2818", "2873", "2878"]

# ---------- controlled vocabularies ----------
ORDER_TYPES = ["LeadCounsel", "Management", "Communications", "ClassCounsel", "Discovery",
               "Motions", "Fees", "Expert", "Bellwether", "Coordination", "Settlement",
               "Trial", "SettlementAdministration", "ProSe", "Vetting"]
# the Appointments table also allows LocalCounsel
APPT_TYPES = ["LeadCounsel", "Management", "Communications", "ClassCounsel", "LocalCounsel",
              "Discovery", "Motions", "Fees", "Expert", "Bellwether", "Coordination",
              "Settlement", "Trial", "SettlementAdministration", "ProSe", "Vetting"]
OrderTypeLiteral = Literal[tuple(ORDER_TYPES)]            # type: ignore[valid-type]
AppointmentTypeLiteral = Literal[tuple(APPT_TYPES)]       # type: ignore[valid-type]
JudgeTypeLiteral = Literal["DJ", "MJ"]
SideLiteral = Literal["Plaintiff", "Defendant"]
AppointeeTypeLiteral = Literal["Individual", "Firm"]
ALLOWED_ORDER_TYPES = set(ORDER_TYPES)
ALLOWED_APPT_TYPES = set(APPT_TYPES)


class Appointee(BaseModel):
    """One person or firm appointed (or removed) in the order."""
    last_name: Optional[str] = Field(None, description="Appointee's last name; null for a firm-only appointee.")
    first_name: Optional[str] = Field(None, description="Appointee's first name; null for a firm-only appointee.")
    full_name: Optional[str] = Field(None, description="The person's FULL canonical name exactly as written in the order -- including any middle name/initial, prefix, and suffix (e.g. 'Philip F. Cossich Jr', 'Daniel E. Becnel, Jr.', 'W. Mark Lanier'). This becomes the Attorneys Canonical_Name. Null for a firm-only appointee.")
    appointee_type: Optional[AppointeeTypeLiteral] = Field(None, description="Individual for a person, Firm for a law firm.")
    firm: Optional[str] = Field(None, description="Law firm name (the individual's firm if stated, or the firm itself when appointee_type is Firm).")
    plaintiff_defendant: Optional[SideLiteral] = Field(None, description="Which side this appointee represents.")
    appointment_types: Optional[List[AppointmentTypeLiteral]] = Field(None, description="Role(s) given to THIS appointee, only from the allowed list (includes LocalCounsel).")
    appoint: Optional[bool] = Field(None, description="True if being appointed (the usual case).")
    remove: Optional[bool] = Field(None, description="True if being removed/terminated from a role.")
    interim: Optional[bool] = Field(None, description="True if the appointment is interim.")

    @field_validator("appointment_types", mode="before")
    @classmethod
    def _filter_appt_types(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v = [v]
        keep = [s for s in v if isinstance(s, str) and s.strip() in ALLOWED_APPT_TYPES]
        return keep or None


class MDLOrderOut(BaseModel):
    """Structured extraction for a single MDL order."""
    MDL_No: Optional[str] = Field(None, description="Four to six digit MDL number, digits only; prefer null over guessing.")
    Docket_No: Optional[int] = Field(None, description="Sequential docket number as integer; prefer null over guessing.")
    Order_No: Optional[str] = Field(None, description="Auto format MDL-Docket like 2434-65 when both parts are present; else null.")
    Date: Optional[str] = Field(None, description="Date the court issued the order (issue/entry date). ISO yyyy-mm-dd if possible.")
    Judge: Optional[str] = Field(None, description="Judge initials as they appear (e.g., MJD or CS).")
    Judge_Type: Optional[List[JudgeTypeLiteral]] = Field(None, description="DJ for District Judge, MJ for Magistrate Judge. Include both if multiple judges sign.")
    Contested: Optional[bool] = Field(None, description="True only if it is apparent FROM THE FACE OF THE ORDER that the court's action was contested: the order makes/modifies appointments AND shows more than one attorney or firm sought the SAME appointment, or the appointment drew objections. Do not infer from outside knowledge.")
    Applications_Solicited: Optional[bool] = Field(None, description="True only if the order explicitly says applications were invited; do not infer.")
    Resolve_Rule_23: Optional[bool] = Field(None, description="True only if it resolves a motion under Rule 23.")
    Rule_23: Optional[bool] = Field(None, description="True if the text cites Rule 23.")
    MCL: Optional[bool] = Field(None, description="True if the text cites the Manual for Complex Litigation (MCL).")
    OU_Functions: Optional[bool] = Field(None, description="True if order specifies functions for any organizational unit.")
    OU_Duties_to_Nonclients: Optional[bool] = Field(None, description="True if order imposes duties toward non-clients.")
    IRPA_Duties_to_Clients: Optional[bool] = Field(None, description="True if order imposes duties on individually retained plaintiff attorneys.")
    Limit_Nonleader_Practice: Optional[bool] = Field(None, description="True if order restricts non-lead attorneys' practice (e.g., must consult lead or cannot file).")
    OU_Create: Optional[int] = Field(None, description="Number of DISTINCT organizational units (named with 'committee' or 'counsel': lead/liaison counsel, PSC/PEC, executive/settlement/discovery/fee/science committee, etc.) this order CREATES for the first time. Count a unit ONLY when the order's text establishes/creates it -- NOT merely because the order appoints people to, names, fills, or refers to a body (those usually pre-exist). Reappointing/confirming/restating/renewing/amending/adding-members-to an EXISTING unit creates 0 new units. Tend to UNDER-count; if it is unclear whether a unit is newly created vs an appointment to a pre-existing one, do not count it.")
    OU_Terminate: Optional[int] = Field(None, description="Count distinct units terminated (rare).")
    OU_Plaintiff: Optional[bool] = None
    OU_Defendant: Optional[bool] = None
    Order_Types: Optional[List[OrderTypeLiteral]] = Field(None, description="Order-level categories; select only from allowed list; prefer null over guessing.")
    MDL_Type: Optional[List[str]] = Field(None, description="JPML classification; do not retrieve if unknown; null is fine.")
    Appointments: Optional[List[Appointee]] = Field(None, description="One object per person/firm appointed or removed in this order. Empty if the order grants a motion without naming appointees.")
    Needs_Motion_Reading: Optional[bool] = Field(None, description="True if the order GRANTS a motion to appoint leadership/class counsel but does NOT itself state the appointees -- a human must read the underlying motion. False if the order names them. Null if not an appointment order.")
    Notes: Optional[str] = Field(None, description="Freeform notes; include 'Multiple judges' if applicable.")

    @field_validator("Order_Types", mode="before")
    @classmethod
    def _filter_order_types(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            v = [v]
        keep = [s for s in v if isinstance(s, str) and s.strip() in ALLOWED_ORDER_TYPES]
        return keep or None


# ---------- Prompt ----------
SYSTEM = """You extract structured data from US federal MDL leadership orders. Follow these rules exactly and prefer null over guessing.

Date:
- Return the date the court issued/entered the order. PACER header entry date > signature date if present. Format ISO yyyy-mm-dd when possible.

Judge and Judge_Type:
- Judge is initials from the order/docket, from 1 to 4 characters. Judge_Type is DJ (District Judge) or MJ (Magistrate Judge). If multiple judges sign, include both types and add "Multiple judges" in Notes.

Contested:
- True only if it is apparent FROM THE FACE OF THE ORDER that the court's action was contested: the order makes or modifies appointments AND the order itself indicates that more than one attorney or law firm sought the SAME appointment (competing applications), or that the appointment drew objections. Do not infer from outside knowledge; it must be visible in the order text.

Applications_Solicited:
- True only if the order explicitly states that the court invited/solicited applications. Do not infer.

Organizational units (OU_*):
- OU_Create: count the number of DISTINCT organizational units this order CREATES for the first time. An organizational unit is a distinctly-named leadership body or counsel role-group, and (as with the role vocab) it must be named with the word "committee" or "counsel" (lead counsel, liaison counsel, PSC/PEC, executive committee, settlement/discovery/fee/science committee, etc.) -- each distinct such unit created = 1. Count a unit ONLY when the order's own text ESTABLISHES/CREATES it (e.g. "the Court hereby establishes a Plaintiffs' Steering Committee", "the Court creates a Settlement Committee"). Tend to UNDER-count rather than over-count: do NOT increment OU_Create merely because the order APPOINTS attorneys to a body, names a body, fills seats on it, or refers to it -- those bodies were usually established by a PRIOR order. Do NOT count a unit recognized/created by a prior order: reappointing, re-confirming, restating, renewing, amending the membership of, or adding members to an EXISTING unit (a renewed CM Plan, "amending the leadership structure", a final-approval order confirming existing class counsel, "appointing additional members to the PSC") = 0 new units. When the text does not make clear that a unit is being created for the first time (vs. an appointment to a pre-existing unit), do NOT count it.
- OU_Terminate: count units expressly abolished (rare).
- OU_Functions: True if functions for any unit are specified.
- OU_Duties_to_Nonclients: True if duties toward non-clients are imposed on court-appointed leaders or committees.
- IRPA_Duties_to_Clients: True if duties on individually retained plaintiff attorneys are imposed.
- Limit_Nonleader_Practice: True if non-lead attorneys' practice is restricted (e.g., must consult lead, cannot file).
- OU_Plaintiff / OU_Defendant: True if affected units are on that side.

Order_Types (CRUCIAL): order-level categories, chosen ONLY from:
  [LeadCounsel, Management, Communications, ClassCounsel, Discovery, Motions, Fees, Expert, Bellwether, Coordination, Settlement, Trial, SettlementAdministration, ProSe, Vetting].
- Do NOT output generic words like "Appointment", "Leadership", "Order", "Committee". Map each role to a category.

Definitions (apply to Order_Types AND to each appointee's appointment_types):
- LeadCounsel: day-to-day conduct of litigation, typically called "lead counsel" or "co-lead counsel". It can also be named interim lead counsel, interim co-lead counsel.
- Management: overall management of the litigation. This includes steering committee and executive committee. This means that if you see a steering committee or an executive committee, it is only Management, and nothing else.
- Communications: communications among attorneys/parties; use for liaison counsel (not if solely coordinating state actions). It can also be named interim liaison counsel.
- ClassCounsel: counsel for a certified class under Rule 23, including class settlements.
- LocalCounsel: locally-admitted local counsel (appointee-level only).
- Discovery / Motions / Fees / Expert / Bellwether / Coordination / Settlement / SettlementAdministration / Trial / ProSe / Vetting: per their plain meaning in MDL practice. "Coordination" means coordination with foreign or state-court litigation. These classifications should be named only when the words "committee" or "counsel" is also present. For example, "discovery committee", "motions committee", "state case liaison counsel"... Otherwise, if the word "committee" or "counsel" does not appear, then do not assign those roles.
- Note: A lawyer or firm appointed as LeadCounsel is usually appointed to one or more Management committees. A typical MDL includes one or more lead counsels who are also appointed to a plaintiff's steering committee, plaintiff's executive committee, or similar Management committee.
- ATTORNEYS AND LAW FIRMS ONLY: every appointee MUST be a practicing attorney or a law firm. EXCLUDE anyone whose title or stated role shows they are NOT an attorney/law firm -- e.g. a CPA or accountant, an economist, a financial advisor or expert, a data/claims/notice/settlement administrator, a guardian ad litem, or any other non-legal professional. Judge by the title/credential next to the name (e.g. "Jane Doe, CPA" or "John Roe, Ph.D." -> exclude) and by the function they are appointed to. If in doubt that the appointee is a lawyer or law firm, do not include them.
- Be careful, the following roles are not leadership appointments and should not be included :  Special Master, mediator, Claims Administrator, notice administrator, settlement administrator, Escrow Agent, Opt Out Administrator
- Refinement on the LeadCounsel/Management note above: tag a lead with Management ONLY when the order actually lists that lead AS a member of a steering/executive committee. If a lead counsel is named SEPARATELY from the committee roster, tag LeadCounsel only -- do not assume Management. CONVERSELY (the more common error to avoid): a person listed ONLY as a member of a steering/executive committee (PSC, PEC, DSC, etc.) is Management ONLY -- do NOT also tag them LeadCounsel. Assign LeadCounsel exclusively to attorneys the order explicitly names as lead or co-lead counsel; membership on a committee, by itself, is never LeadCounsel. Keep ClassCounsel (Rule 23 class counsel) distinct from LeadCounsel. When one appointee genuinely holds more than one role (e.g. LeadCounsel and SettlementAdministration), assign every role that is explicit -- do not collapse to a single dominant one.

Appointments (one Appointee object per distinct person OR firm appointed or removed):
- ENUMERATE ROSTERS: if the order or plan LISTS the membership of any committee (PSC/DSC, Plaintiffs'/Defendants' Steering Committee, Executive Committee, liaison group) -- including a Name->Firm table, schedule, or exhibit -- create one Appointee for EVERY person and firm listed, even when the document RESTATES or CONFIRMS an existing structure rather than making a first-time appointment. A Case Management Plan / Pretrial Order that sets out the leadership roster IS an appointment record; never return an empty Appointments list merely because the document reprints the structure.
- MULTI-COLUMN ROSTERS (critical for completeness): leadership rosters are very often laid out in TWO (or more) side-by-side COLUMNS, where each attorney is followed by their own "and the law firm of <Firm>" block, address, phone, and email. OCR interleaves these columns, so two different attorneys (e.g. "Thomas M. Sobol, Esquire ... Hagens Berman" on the left and "David F. Sorensen, Esquire ... Berger & Montague" on the right) can appear adjacent in the text. Extract EVERY attorney from EVERY column -- treat each "Name, Esquire / and the law firm of X" block as its OWN Appointee. Do NOT merge two side-by-side attorneys into one, and do NOT stop after the first column. If a roster visually has N rows by 2 columns, you should produce ~2N appointees, not N.
- Create one entry per attorney or firm appointed to a leadership position or committee. last_name / first_name = the person's name; leave both null for a firm-only appointee. If a name appears as an initial, a middle name, and a last name (e.g. "W. Mark Lanier"), treat the initial as first_name.
- full_name = the COMPLETE canonical name exactly as written in the order body, with every middle name/initial, prefix, and suffix kept (e.g. "W. Mark Lanier", "Philip F. Cossich Jr", "Daniel E. Becnel, Jr.", "J. Liat Rome"). full_name preserves elements that the first/last split drops (e.g. the middle "Mark"). Do not shorten to a signature-block or table-header abbreviation. This is the field that feeds the Attorneys Canonical_Name.
- appointee_type: "Individual" for a person, "Firm" for a law firm. If a name appears as so-and-so of a certain law firm (e.g. "Mark Lanier of the Lanier Law Firm"), classify as an individual, not firm, appointment.
- Do NOT create a separate Firm appointee for a firm whose named individual is already an Individual appointee in this same order -- put that firm in the individual's `firm` field instead (the firm-level row is added downstream from this attribute). Only create a standalone Firm appointee when the firm itself is appointed with NO named individual. (This keeps the output compact: a 60-person roster is ~60 appointees, not 120 -- avoiding output-token truncation on very large rosters.)
- firm: the law firm (the individual's firm if stated, or the firm itself).
- plaintiff_defendant: the side this appointee represents.
- appointment_types: the role(s) THIS appointee receives, from the allowed list above (includes LocalCounsel).
- appoint: true if being appointed (usual). remove: true if removed/terminated.
- interim: true for EVERY appointee whose position, committee, or the leadership structure being created is labeled "interim" -- e.g. an order that appoints "interim case leadership", creates an "Interim Steering Committee", or names "Interim Lead Counsel" makes ALL the attorneys it appoints under that interim framing interim=true, not only those individually called interim. (Only if an order clearly mixes an interim body with a SEPARATE, explicitly-permanent body should you confine interim to the interim one.) Never infer interim merely because the order is early/organizational; the word "interim" must be attached to the appointment, committee, position, or leadership structure.
- Extract named lead/class counsel even when they appear in the PROSE of a final-approval, fee, or settlement order (e.g. "the Court confirms X and Y as Class Counsel"), not only in a standalone appointment section.
- If the order grants a motion to appoint, OR confirms/adopts appointments made in a PRIOR order or motion BY REFERENCE, without naming the appointees in its own text, leave Appointments empty and set Needs_Motion_Reading=true (a later step reads the referenced filing).

Needs_Motion_Reading:
- True when the order grants an appointment motion but does not state the appointees (detail is in the motion). False when the order names them. Null if not an appointment order.

Citations:
- Rule_23 true if Rule 23 is cited; Resolve_Rule_23 true only if a Rule 23 motion is resolved.

General: if the text does not explicitly support a value, return null. Return a single JSON object matching the schema exactly.
"""


def build_user(filename, parsed_mdl, parsed_docket, parsed_order, order_text):
    return (
        f"Source filename: {filename}\n\n"
        "Possible identifiers parsed from filename/header (hints only):\n"
        f"- Parsed_MDL_No: {parsed_mdl}\n"
        f"- Parsed_Docket_No: {parsed_docket}\n"
        f"- Parsed_Order_No: {parsed_order}\n\n"
        f"Order text (Markdown):\n{order_text}"
    )


def parse_ids_from_context(filename, text):
    ctx = f"{filename}\n{text}"
    mdl = docket = None
    m = re.search(r"MDL\s*No\.?\s*(\d{2,6}).{0,80}?Doc\.?\s*(\d{1,5})", ctx, re.IGNORECASE | re.DOTALL)
    if m:
        mdl, docket = m.group(1), m.group(2)
    else:
        m = re.search(r"\b(\d{2,6})\D+Doc\.?\s*(\d{1,5})\b", ctx, re.IGNORECASE)
        if m:
            mdl, docket = m.group(1), m.group(2)
        else:
            m = re.search(r"\b(\d{2,6})[-–](\d{1,5})\b", ctx)
            if m:
                mdl, docket = m.group(1), m.group(2)
    order_no = f"{mdl}-{docket}" if mdl and docket else None
    return mdl, docket, order_no


def docket_from_filename(filename):
    """Authoritative docket number from the filename (this corpus names files by docket):
    '2428, Doc. 33, ...' -> 33, 'Doc. 1112' -> 1112, and the US_DIS_..._05md1654_10_ form -> 10."""
    fn = os.path.basename(filename or "")
    m = re.search(r"[,_]\s*Doc(?:ket)?\.?\s*#?\s*(\d+)", fn, re.I)
    if m:
        return m.group(1)
    m = re.search(r"_\d+(?:md|mc|cv)\d+_(\d+)_", fn, re.I)
    return m.group(1) if m else None


def canonical_ids(rec):
    """Prefer the FILENAME docket over the model's Docket_No. The model occasionally lifts a
    number from the order body (e.g. it keyed '2428, Doc. 33' as 2428-416); the filename docket
    is the reliable identifier in this corpus. Recomputes Order_No. Idempotent; only overrides
    when the filename actually yields a docket."""
    dk = docket_from_filename(rec.get("Source_File", ""))
    if not dk:
        return rec
    model_dk = rec.get("Docket_No")        # the model's own docket, before we override with the filename's
    if model_dk not in (None, "") and str(model_dk).strip() != str(int(dk)):
        rec["Docket_Mismatch"] = f"model={model_dk} / filename={int(dk)}"   # flag (don't hide) the disagreement
    rec["Docket_No"] = int(dk)
    mdl = rec.get("MDL_No")
    if not mdl:
        m = re.match(r"^(\d+)", os.path.basename(rec.get("Source_File", "")))
        if m:
            mdl = rec["MDL_No"] = m.group(1)
    if mdl:
        rec["Order_No"] = f"{mdl}-{dk}"
    return rec


def keep_order(rec):
    """Project policy (Bernardes/Noll, 2026-06-25): drop orders that contribute no appointment data
    -- the clerical 'unnamed records' and procedural orders that name no one. BUT keep:
      - any order that appoints someone (has appointees), and
      - any order flagged Needs_Motion_Reading=True -- a real appointment/REAPPOINTMENT order whose
        appointees are stated by reference (e.g. 'the Court confirms its appointment of Class
        Counsel', or a renewed CM Plan). These are genuine leadership orders the humans also keep;
        dropping them would MISS real orders, so they stay (flagged for follow-up).

    MUST run AFTER resolve_motions (stage 9): a motion-cited Needs_Motion_Reading order gets its
    appointees filled there. build_excel only filters the XLSX (never the jsonl) and stage 9 rebuilds
    the XLSX last, so 8 -> 9 yields the correct workbook. Mirrored in code/eval_vs_gold.py."""
    return bool(rec.get("Appointments") or []) or rec.get("Needs_Motion_Reading") is True


# ---------- Excel export (Orders / Appointments / Attorneys) ----------
ORDERS_COLS = ["Order_No", "MDL_No", "Docket_No", "Date", "Judge", "Judge_Type", "Contested",
               "OU_Create", "OU_Terminate", "OU_Functions", "OU_Duties_to_Nonclients",
               "OU_Plaintiff", "OU_Defendant", "Order_Types", "Appointments_Count",
               "Applications_Solicited", "Resolve_Rule_23", "IRPA_Duties_to_Clients",
               "Limit_Nonleader_Practice", "Rule_23", "MCL", "MDL Type", "Notes",
               "Needs_Motion_Reading", "Needs_Signature_Check", "Possible_Duplicate", "Source_File",
               "Provenance"]
APPTS_COLS = ["Appointment_ID", "Order_No", "Last Name", "First Name", "Appoint", "Remove",
              "Interim", "Appointment Types", "Plaintiff/Defendant", "Appointee Type", "Firm",
              "First_Last_Calculated", "MDL_No", "MDL Type", "Possible_Duplicate_Appointment",
              "Provenance"]
ATTORNEYS_COLS = ["Attorney_Identifier", "Canonical_Name", "First_Name", "Last_Name", "Firm",
                  "Gender", "Race", "Birth_Year", "Undergrad_Grad_Year", "Law_Grad_Year",
                  "Undergrad_School", "Law_School_Name", "Bar_States", "Sources", "Notes",
                  "AKA_1", "AKA_2", "AKA_3"]


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, list):
        return "; ".join(str(x) for x in v)
    return v


_FIRM_SUFFIX_RE = re.compile(
    r"\b(l\.?l\.?p|l\.?l\.?c|pllc|p\.?l\.?l\.?c|a\.?p\.?c|p\.?c|p\.?a|l\.?p\.?a|lp|ltd|co|chartered|llp|llc|pc|apc|pa)\b",
    re.I)


def _norm_name(s):
    """Lowercase, drop punctuation/extra spaces -- so 'Green, Eric D.' ~ 'Eric D Green'.
    (Nickname/initial variants like 'Chris' vs 'Christopher' still differ -- that is the
    manual Canonical_Name step.)"""
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _norm_firm(s):
    """Firm key: lowercase, strip punctuation and legal-entity suffixes (LLP/PC/APC...)
    so 'Hamner Law Offices APC' ~ 'Hamner Law Offices'."""
    s = re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower())
    s = _FIRM_SUFFIX_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


GATE_STATUS = os.path.join(ROOT, "order_status.csv")


def load_gate_status():
    """relpath -> gate row (Stage 6). Empty dict if the gate hasn't run."""
    g = {}
    if os.path.exists(GATE_STATUS):
        with open(GATE_STATUS, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                g[r["relpath"]] = r
    return g


def build_excel():
    import pandas as pd
    if not os.path.exists(JSONL):
        print("no order_extractions.jsonl yet")
        return
    recs = []
    for line in open(JSONL, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            recs.append(json.loads(line))
        except json.JSONDecodeError:
            print("  warn: skipped a malformed jsonl line (partial write?)")

    # Stage-6 gate: keep only retrieve=1 orders; collect the drops for an audit tab.
    gate = load_gate_status()
    dropped_rows = []
    if gate:
        n_before = len(recs)
        recs = [r for r in recs if gate.get(r.get("Source_File", ""), {}).get("retrieve") == "1"]
        for rel, gr in gate.items():
            if gr.get("retrieve") == "0":
                dropped_rows.append({"Source_File": rel, "Relevance": gr.get("relevance", ""),
                                     "Doc_Kind": gr.get("doc_kind", ""), "Reason": gr.get("reason", "")})
        print(f"gate filter: kept {len(recs)} of {n_before} extracted orders "
              f"({len(dropped_rows)} dropped by Stage 6)")
    else:
        print("note: no order_status.csv -- building from all extractions (gate not applied)")

    # correct identifiers from the filename (Docket_No / Order_No), then drop zero-appointee orders
    # (project policy; runs after stage 9 so motion-resolved appointees are already folded in).
    for r in recs:
        canonical_ids(r)
    n_mismatch = sum(1 for r in recs if r.get("Docket_Mismatch"))
    if n_mismatch:
        print(f"docket mismatch: {n_mismatch} order(s) where the model's docket != the filename's "
              f"(filename used; flagged in Docket_Mismatch in the jsonl for review)")
    empty_dropped = [{"Source_File": r.get("Source_File", ""), "Order_No": r.get("Order_No", ""),
                      "Reason": ("still flagged Needs_Motion_Reading (appointees in a referenced "
                                 "filing not located)" if r.get("Needs_Motion_Reading") is True
                                 else "no appointees (appointment-only dataset)")}
                     for r in recs if not keep_order(r)]
    if empty_dropped:
        recs = [r for r in recs if keep_order(r)]
        print(f"zero-appointee filter: dropped {len(empty_dropped)} orders with no appointees")

    # Stage 8->9 guard: kept orders still flagged Needs_Motion_Reading with NO appointees mean the
    # appointees live in a cited motion / adopted Special-Master report that stage 9 hasn't fetched.
    unresolved = [r for r in recs if r.get("Needs_Motion_Reading") is True and not (r.get("Appointments") or [])]
    if unresolved:
        print(f"\n  !! STAGE 9 NOT COMPLETE: {len(unresolved)} kept order(s) are still flagged "
              f"Needs_Motion_Reading with NO appointees.\n     Run `python code/resolve_motions.py` to "
              f"fetch each one's cited motion / adopted report and extract its appointees. The workbook "
              f"is NOT final until stage 9 has resolved (or exhausted) these.\n")

    orders, appts, attorneys = [], [], {}
    for r in recs:
        order_no = r.get("Order_No") or ""
        mdl_no = r.get("MDL_No") or ""
        mdl_type = _cell(r.get("MDL_Type"))
        applist = r.get("Appointments") or []
        prov = _cell(r.get("Provenance")) or "extracted"   # how this order's appointees were obtained
        orders.append({
            "Order_No": order_no, "MDL_No": mdl_no, "Docket_No": _cell(r.get("Docket_No")),
            "Date": _cell(r.get("Date")), "Judge": _cell(r.get("Judge")), "Judge_Type": _cell(r.get("Judge_Type")),
            "Contested": _cell(r.get("Contested")), "OU_Create": _cell(r.get("OU_Create")),
            "OU_Terminate": _cell(r.get("OU_Terminate")), "OU_Functions": _cell(r.get("OU_Functions")),
            "OU_Duties_to_Nonclients": _cell(r.get("OU_Duties_to_Nonclients")),
            "OU_Plaintiff": _cell(r.get("OU_Plaintiff")), "OU_Defendant": _cell(r.get("OU_Defendant")),
            "Order_Types": _cell(r.get("Order_Types")), "Appointments_Count": len(applist),
            "Applications_Solicited": _cell(r.get("Applications_Solicited")),
            "Resolve_Rule_23": _cell(r.get("Resolve_Rule_23")), "IRPA_Duties_to_Clients": _cell(r.get("IRPA_Duties_to_Clients")),
            "Limit_Nonleader_Practice": _cell(r.get("Limit_Nonleader_Practice")), "Rule_23": _cell(r.get("Rule_23")),
            "MCL": _cell(r.get("MCL")), "MDL Type": mdl_type, "Notes": _cell(r.get("Notes")),
            "Needs_Motion_Reading": _cell(r.get("Needs_Motion_Reading")),
            "Needs_Signature_Check": gate.get(r.get("Source_File", ""), {}).get("needs_signature_check", ""),
            "Possible_Duplicate": "", "Source_File": r.get("Source_File", ""), "Provenance": prov,
        })
        for i, a in enumerate(applist, 1):
            fn = (a.get("first_name") or "").strip()
            ln = (a.get("last_name") or "").strip()
            firm = (a.get("firm") or "").strip()
            fullname = (a.get("full_name") or "").strip()   # full canonical: middle/prefix/suffix kept
            full = f"{fn} {ln}".strip()
            canonical = full if (fn or ln) else firm
            appts.append({
                "Appointment_ID": f"{order_no}-{i}" if order_no else f"?-{i}", "Order_No": order_no,
                "Last Name": ln, "First Name": fn, "Appoint": _cell(a.get("appoint")),
                "Remove": _cell(a.get("remove")), "Interim": _cell(a.get("interim")),
                "Appointment Types": _cell(a.get("appointment_types")),
                "Plaintiff/Defendant": _cell(a.get("plaintiff_defendant")),
                "Appointee Type": _cell(a.get("appointee_type")), "Firm": firm,
                "First_Last_Calculated": canonical, "MDL_No": mdl_no, "MDL Type": mdl_type,
                "Possible_Duplicate_Appointment": "", "Provenance": prov,
            })
            # dedup into the Attorneys roster (normalized keys; firm backfilled from later rows).
            # Nickname/initial variants (e.g. "Chris" vs "Christopher") still split -- that is the
            # intended manual Canonical_Name / AKA step, not an automatic merge.
            if a.get("appointee_type") == "Firm" or (not fn and not ln):
                key, canon, af, al = ("firm", _norm_firm(firm)), firm, "", ""
            else:
                # Canonical_Name = the full canonical name (middle/prefix/suffix); dedup key
                # stays normalized first+last so name-form variants still merge.
                key, canon, af, al = ("ind", _norm_name(fn), _norm_name(ln)), (fullname or full), fn, ln
            if canon:
                if key not in attorneys:
                    attorneys[key] = {"Attorney_Identifier": canon, "Canonical_Name": canon,
                                      "First_Name": af, "Last_Name": al, "Firm": firm}
                elif firm and not attorneys[key].get("Firm"):
                    attorneys[key]["Firm"] = firm    # backfill a firm a later occurrence supplies

        # derive a firm-level Appointment row per distinct firm (human convention lists firms as
        # appointees). The LLM emits compact individual-with-firm-attribute rows; we expand here, so
        # large rosters never blow the output-token budget. One firm row per (order, distinct firm),
        # carrying the union of that firm's individuals' roles; skip firms already emitted standalone.
        standalone = {_norm_firm((a.get("firm") or "")) for a in applist
                      if a.get("appointee_type") == "Firm"
                      or not ((a.get("first_name") or "").strip() or (a.get("last_name") or "").strip())}
        derived = {}
        for a in applist:
            fn2 = (a.get("first_name") or "").strip(); ln2 = (a.get("last_name") or "").strip()
            firm2 = (a.get("firm") or "").strip()
            if not (fn2 or ln2) or not firm2:
                continue
            nf = _norm_firm(firm2)
            if not nf or nf in standalone:
                continue
            d = derived.setdefault(nf, {"firm": firm2, "roles": [], "side": a.get("plaintiff_defendant"),
                                        "appoint": a.get("appoint"), "remove": a.get("remove"),
                                        "interim": a.get("interim")})
            for rt in (a.get("appointment_types") or []):
                if rt not in d["roles"]:
                    d["roles"].append(rt)
        for j, d in enumerate(derived.values(), 1):
            appts.append({
                "Appointment_ID": f"{order_no}-F{j}" if order_no else f"?-F{j}", "Order_No": order_no,
                "Last Name": "", "First Name": "", "Appoint": _cell(d["appoint"]),
                "Remove": _cell(d["remove"]), "Interim": _cell(d["interim"]),
                "Appointment Types": _cell(d["roles"]), "Plaintiff/Defendant": _cell(d["side"]),
                "Appointee Type": "Firm", "Firm": d["firm"], "First_Last_Calculated": d["firm"],
                "MDL_No": mdl_no, "MDL Type": mdl_type, "Possible_Duplicate_Appointment": "", "Provenance": prov,
            })

    # flag likely-duplicate orders (same MDL + same date + same normalized title) for review
    # -- e.g. the 592/593 pair. Conservative: flags, never drops (amended/interim versions are
    # legitimately distinct and a human decides).
    def _norm_title(sf):
        t = os.path.basename(sf or "").lower()
        t = re.sub(r"\.pdf$", "", t)
        t = re.sub(r"^\s*\d+\s*,?\s*doc\.?\s*[\d-]+\s*,?", "", t)   # strip "NNNN, Doc. M,"
        t = re.sub(r"\b(amended|second|2nd|third|3rd|interim|proposed|\(\d+\))\b", "", t)
        return re.sub(r"[^a-z0-9]+", " ", t).strip()
    sig = collections.defaultdict(list)
    for o in orders:
        sig[(o["MDL_No"], o["Date"], _norm_title(o["Source_File"]))].append(o)
    for grp in sig.values():
        if len(grp) > 1:
            for o in grp:
                o["Possible_Duplicate"] = f"shares date+title with {len(grp)-1} other order(s)"

    # within-MDL same-date duplicate FLAG (non-destructive). We KEEP every per-order appointment row --
    # the gold tables' convention (one row per appointment event) -- and leave de-duplication to a later
    # data-cleaning step. We only MARK, in Possible_Duplicate_Appointment, the same appointee+role+side
    # appointed in >1 order ON THE SAME DATE (a likely duplicate/amended order), so that later cleaning
    # has the candidates pre-identified. A genuine reappointment on a LATER date is not flagged.
    def _appt_ident(a):
        if a.get("Appointee Type") == "Firm" or not (a.get("First Name") or a.get("Last Name")):
            return ("firm", _norm_firm(a.get("Firm", "")))
        return ("ind", _norm_name(a.get("First Name", "")), _norm_name(a.get("Last Name", "")))
    order_date = {o.get("Order_No", ""): o.get("Date", "") for o in orders}
    by_key = collections.defaultdict(list)
    for a in appts:
        roles = tuple(sorted(s.strip().lower() for s in str(a.get("Appointment Types", "")).split(";") if s.strip()))
        side = str(a.get("Plaintiff/Defendant", "")).strip().lower()
        ono = a.get("Order_No", "")
        by_key[(a.get("MDL_No", ""), _appt_ident(a), roles, side, order_date.get(ono, ""))].append(a)
    n_flag = 0
    for key, rows in by_key.items():
        date = key[4]
        onos = sorted({r.get("Order_No", "") for r in rows if r.get("Order_No")})
        if date and len(onos) > 1:           # same appointee+role+side, same DATE, >1 distinct order
            for r in rows:
                r["Possible_Duplicate_Appointment"] = (
                    f"same appointee+role+side on {date} across {len(onos)} orders: {', '.join(onos)}")
                n_flag += 1
    dup_dropped = []     # NOTHING dropped -- every row kept (gold convention); the column above only flags
    if n_flag:
        print(f"within-MDL same-date duplicate flag: {n_flag} appointment row(s) marked (kept, not dropped)")

    df_o = pd.DataFrame(orders).reindex(columns=ORDERS_COLS)
    df_a = pd.DataFrame(appts).reindex(columns=APPTS_COLS)
    df_t = pd.DataFrame(list(attorneys.values())).reindex(columns=ATTORNEYS_COLS)
    df_d = pd.DataFrame(dropped_rows).reindex(
        columns=["Source_File", "Relevance", "Doc_Kind", "Reason"]) if dropped_rows else None
    df_e = pd.DataFrame(empty_dropped).reindex(
        columns=["Source_File", "Order_No", "Reason"]) if empty_dropped else None
    df_dup = pd.DataFrame(dup_dropped).reindex(
        columns=["Appointment_ID", "Order_No", "MDL_No", "Name_or_Firm", "Appointment Types",
                 "Date", "Kept_Under", "Reason"]) if dup_dropped else None
    with pd.ExcelWriter(XLSX, engine="openpyxl") as xw:
        df_o.to_excel(xw, sheet_name="Orders", index=False)
        df_a.to_excel(xw, sheet_name="Appointments", index=False)
        df_t.to_excel(xw, sheet_name="Attorneys", index=False)
        if df_d is not None:
            df_d.to_excel(xw, sheet_name="Dropped (Stage 6)", index=False)
        if df_e is not None:
            df_e.to_excel(xw, sheet_name="Dropped (empty)", index=False)
        if df_dup is not None:
            df_dup.to_excel(xw, sheet_name="Dropped (dup appt)", index=False)
    print(f"wrote {os.path.relpath(XLSX, ROOT)}  "
          f"(Orders={len(df_o)}, Appointments={len(df_a)}, Attorneys={len(df_t)}"
          f"{', Dropped(gate)=' + str(len(df_d)) if df_d is not None else ''}"
          f"{', Dropped(empty)=' + str(len(df_e)) if df_e is not None else ''}"
          f"{', Dropped(dupAppt)=' + str(len(df_dup)) if df_dup is not None else ''})")


# ---------- runner ----------
def all_order_mdls():
    """Every MDL with a trimmed order under orders/ -- the universe for a --all full-corpus run."""
    out = set()
    if os.path.isdir(ORDERS_DIR):
        for folder in os.listdir(ORDERS_DIR):
            m = re.match(r"^(\d+)", folder)
            if m and os.path.isdir(os.path.join(ORDERS_DIR, folder)):
                out.add(m.group(1))
    return sorted(out)


def iter_orders(mdls, contains=None):
    want = set(mdls)
    out = []
    for folder in sorted(os.listdir(ORDERS_DIR)):
        d = os.path.join(ORDERS_DIR, folder)
        if not os.path.isdir(d):
            continue
        m = re.match(r"^(\d+)", folder)
        if not (m and m.group(1) in want):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".json") and (not contains or contains.lower() in fn.lower()):
                out.append(os.path.join(d, fn))
    return out


def extract_one(client, json_path):
    with open(json_path, encoding="utf-8") as f:
        o = json.load(f)
    rel = o.get("relpath", os.path.basename(json_path))
    filename = o.get("filename", os.path.basename(json_path))
    text = o.get("text", "")
    pm, pd_, po = parse_ids_from_context(filename, text)
    try:
        comp = client.beta.chat.completions.parse(
            model=MODEL,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": build_user(filename, pm or "null", pd_ or "null", po or "null", text)}],
            response_format=MDLOrderOut,
            max_completion_tokens=MAX_OUT_TOKENS)
        msg = comp.choices[0].message
        if getattr(msg, "refusal", None):
            return rel, None, f"refusal: {msg.refusal[:100]}", (0, 0)
        u = comp.usage
        return rel, msg.parsed, "", (u.prompt_tokens, u.completion_tokens)
    except Exception as e:  # noqa: BLE001
        return rel, None, f"{type(e).__name__}: {str(e)[:140]}", (0, 0)


def already_done():
    done = set()
    if os.path.exists(JSONL):
        with open(JSONL, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        done.add(json.loads(line).get("Source_File", ""))
                    except Exception:
                        pass
    return done


def preflight_model(client, model, fallback="gpt-5"):
    """Confirm the chat model id resolves on this API key BEFORE spawning workers (fail fast, not
    mid-run after spending). Returns the working id (the requested model, or the fallback), or None."""
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
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mdls", help="comma-separated MDL numbers (default: the 10-sample)")
    ap.add_argument("--all", action="store_true",
                    help="every MDL present in orders/ (full corpus; overrides --mdls and the 10-sample default)")
    ap.add_argument("--contains", help="only orders whose filename contains this substring")
    ap.add_argument("--workers", type=int, default=24,
                    help="concurrent LLM requests; raise for throughput (rate limits self-throttle via SDK retries)")
    ap.add_argument("--limit", type=int, help="only the first N not-yet-done orders")
    ap.add_argument("--dry-run", action="store_true", help="count inputs, no API calls")
    ap.add_argument("--excel-only", action="store_true", help="rebuild the workbook from the jsonl (no API)")
    ap.add_argument("--model", default=MODEL,
                    help="chat model id (default %(default)s; falls back to gpt-5 if unavailable)")
    args = ap.parse_args()

    if args.excel_only:
        build_excel()
        return 0

    MODEL = args.model
    mdls = all_order_mdls() if args.all else (
        [s.strip() for s in args.mdls.split(",")] if args.mdls else DEFAULT_MDLS)
    done = already_done()
    gate = load_gate_status()          # Stage 6: only extract retrieve=1 orders
    paths = iter_orders(mdls, args.contains)
    gated_out = 0
    todo = []
    for p in paths:
        rel = json.load(open(p, encoding="utf-8")).get("relpath", p)
        if gate and gate.get(rel, {}).get("retrieve") != "1":
            gated_out += 1
            continue
        if rel not in done:
            todo.append(p)
    if args.limit:
        todo = todo[:args.limit]

    kept = len(paths) - gated_out
    print(f"orders found: {len(paths):,} | gate-kept: {kept:,} (dropped by gate: {gated_out:,}) | "
          f"already extracted: {len(done):,} | to do: {len(todo):,}")
    print(f"model: {MODEL} | workers: {args.workers} | out: {os.path.relpath(JSONL, ROOT)}")
    if args.dry_run or not todo:
        return 0

    load_dotenv(os.path.join(ROOT, ".env"))
    if not os.getenv("OPENAI_API_KEY"):
        print("missing OPENAI_API_KEY", file=sys.stderr)
        return 1
    from openai import OpenAI
    client = OpenAI(max_retries=5)

    chosen = preflight_model(client, MODEL)
    if not chosen:
        print(f"model '{MODEL}' (and fallback) unavailable -- aborting before any extraction", file=sys.stderr)
        return 1
    if chosen != MODEL:
        print(f"  preflight: using fallback model '{chosen}'")
        MODEL = chosen

    import hashlib
    _sys_sha = hashlib.sha1(SYSTEM.encode("utf-8")).hexdigest()[:12]   # prompt fingerprint, recorded per record
    print(f"  reproducibility: model={MODEL} prompt_sha={_sys_sha} openai={__import__('openai').__version__}")

    f = open(JSONL, "a", encoding="utf-8")
    lock = threading.Lock()
    ok = errs = tin = tout = n = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(extract_one, client, p) for p in todo]
        for fut in tqdm(as_completed(futs), total=len(futs), unit="order", desc="extract"):
            rel, result, err, (pin, pout) = fut.result()
            n += 1
            tin += pin
            tout += pout
            with lock:
                if result is not None:
                    rec = result.model_dump()
                    rec["Source_File"] = rel
                    rec["Provenance"] = "extracted"
                    rec["_model"], rec["_prompt_sha"] = MODEL, _sys_sha   # reproducibility provenance
                    canonical_ids(rec)          # prefer the filename docket over a body-text number
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    f.flush()
                    ok += 1
                else:
                    errs += 1
                    print(f"  ERR {rel[:70]} :: {err}")
            if n % 25 == 0:
                est = tin / 1e6 * PRICE_IN + tout / 1e6 * PRICE_OUT
                print(f"\n  [{n}] ok={ok} err={errs} ~${est:.2f}")
    f.close()

    est = tin / 1e6 * PRICE_IN + tout / 1e6 * PRICE_OUT
    print(f"\nDONE: extracted {ok:,} | errors {errs} | in={tin:,} out={tout:,} | ~${est:.2f}")
    build_excel()
    return 0


if __name__ == "__main__":
    sys.exit(main())
