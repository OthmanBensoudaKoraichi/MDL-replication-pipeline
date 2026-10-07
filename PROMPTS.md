# Pipeline prompts — verbatim

Every LLM prompt used to build the dataset, extracted **verbatim from the pipeline source** by
`code/make_prompts_md.py` (re-run it after any prompt change; the code is authoritative).
For what each stage does and how it was validated, see `METHODOLOGY.md`.

| Stage | File | Model |
|---|---|---|
| 2 · Document classification | `code/classify_type.py` | gpt-5.4-mini |
| 5 · UNCLEAR refinement | `code/refine_unclear.py` | gpt-5.4-mini |
| 6 · Order gate (screening) | `code/confirm_orders.py` | gpt-5.5 |
| 8 · Appointment extraction | `code/extract_orders.py` | gpt-5.5 |
| 9 · Motion / report resolution | `code/resolve_motions.py` | gpt-5.5 |
| Identity adjudication (dedup) | `code/dedup_v2.py` | gpt-5.5 (+ web search) |
| Attorney demographics | `code/attorney_demographics.py` | gpt-5.5 + web search |

## Stage 2 — Document classification (`code/classify_type.py`, gpt-5.4-mini)

**System prompt:**

```
You classify a U.S. multidistrict-litigation (MDL) court document into exactly ONE type, using ONLY its filename and page count. Judge the document TYPE only -- never its relevance or importance.

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

Return JSON {type}.
```

**User message** (per document):

```
FILENAME: {filename}
PAGES: {page_count}
```

Output is constrained to a JSON schema with a single `type` field.

## Stage 5 — UNCLEAR refinement (`code/refine_unclear.py`, gpt-5.4-mini)

**System prompt:**

```
You are given the first pages of a U.S. multidistrict-litigation (MDL) court document. Decide whether the document ITSELF is a court ORDER -- a ruling, opinion, judgment, or decision issued by the court (typically signed by a judge) -- as opposed to a motion, brief, memorandum, declaration, affidavit, notice, stipulation, transcript, exhibit, complaint, or other party filing.

A document that merely mentions, requests, or attaches an order is NOT itself an order (e.g. "Motion for an Order...", "Memorandum in support...", a proposed order attached as an exhibit). Judge only what the document is.

Return JSON {is_order: bool, reason: one short sentence}.
```

**User message:** the document's first pages (OCR text, capped at 12,000 characters), with a caveat prepended when the filename contains “proposed” — assembled by:

```python
def llm_is_order(client, text, proposed=False):
    user = text[:MAX_CHARS]
    if proposed:
        user = ("NOTE: this document's filename contains the word PROPOSED -- return "
                "is_order:true ONLY if the text shows it was actually entered/signed by a "
                "judge, not merely a party's proposed draft.\n\n") + user
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": SYS},
                  {"role": "user", "content": user}],
        response_format={"type": "json_schema",
                         "json_schema": {"name": "order_check", "strict": True, "schema": SCHEMA}},
        max_completion_tokens=MAX_OUT_TOKENS)
    d = json.loads(resp.choices[0].message.content or "{}")
    u = resp.usage
    return bool(d.get("is_order", False)), d.get("reason", ""), (u.prompt_tokens, u.completion_tokens)
```

## Stage 6 — Order gate / screening (`code/confirm_orders.py`, gpt-5.5)

**System prompt:**

```
You decide whether a U.S. MDL court document should be RETRIEVED into a leadership-APPOINTMENT dataset of court ORDERS. We care ONLY about orders that appoint, remove, or modify leadership/counsel -- NOT fees or settlements in themselves. Apply TWO tests.

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

Return JSON with: relevance, doc_kind, executed, needs_signature_check, evidence (a verbatim quote that decided Test B), reason (one sentence), confidence.
```

**User message** — assembled per document by:

```python
def build_user(fn, excerpt, sub, proposed):
    return (f"FILENAME: {fn}\n"
            f"sub_docket_in_name: {sub}\nproposed_in_name: {proposed}\n\n"
            f"{excerpt}")
```

## Stage 8 — Appointment extraction (`code/extract_orders.py`, gpt-5.5)

**System prompt** (includes the appointment-type vocabulary and all coding conventions):

```
You extract structured data from US federal MDL leadership orders. Follow these rules exactly and prefer null over guessing.

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
```

**User message** — assembled per order by:

```python
def build_user(filename, parsed_mdl, parsed_docket, parsed_order, order_text):
    return (
        f"Source filename: {filename}\n\n"
        "Possible identifiers parsed from filename/header (hints only):\n"
        f"- Parsed_MDL_No: {parsed_mdl}\n"
        f"- Parsed_Docket_No: {parsed_docket}\n"
        f"- Parsed_Order_No: {parsed_order}\n\n"
        f"Order text (Markdown):\n{order_text}"
    )
```

Output is constrained to the Pydantic `Extraction` schema defined in the same file.

## Stage 9 — Motion / Rule-53 report resolution (`code/resolve_motions.py`, gpt-5.5)

**System prompt:**

```
You are reading the underlying document that a court order GRANTED or ADOPTED without naming the appointees in the order itself -- either the MOTION the court granted, or the SPECIAL MASTER'S / RULE 53 REPORT & RECOMMENDATION the court adopted. Extract the people and firms this document proposes or recommends be appointed to leadership or a committee, using these rules (same as for orders):

- Create one Appointee per attorney or firm the document proposes/recommends for a leadership position or committee (a Special Master report typically lists a recommended SLATE or roster -- enumerate EVERY person and firm on it). last_name / first_name = the person's name; leave both null for a firm-only appointee. If a name appears as an initial, a middle name, and a last name (e.g. "W. Mark Lanier"), treat the initial as first_name.
- appointee_type: "Individual" for a person, "Firm" for a law firm. "Mark Lanier of the Lanier Law Firm" is an Individual.
- firm: the law firm (the individual's firm if stated, or the firm itself).
- plaintiff_defendant: the side this appointee represents.
- appointment_types: the role(s) requested for THIS appointee, only from: [LeadCounsel, Management, Communications, ClassCounsel, LocalCounsel, Discovery, Motions, Fees, Expert, Bellwether, Coordination, Settlement, Trial, SettlementAdministration, ProSe, Vetting]. LeadCounsel = lead/co-lead counsel; Management = steering or executive committee (only Management, nothing else); Communications = liaison counsel. Do NOT include Special Master, mediator, claims/notice/settlement administrator, escrow agent.
- appoint: true (these are proposed appointments). interim: true if the motion requests an interim appointment.

Return JSON {Appointments: [...]}. If the document does not actually name proposed/recommended appointees, return an empty list.
```

**User message:** the full text of the cited motion or report (first 60,000 characters).

## Identity adjudication — attorneys & firms (`code/dedup_v2.py`, gpt-5.5)

**System prompt — attorney pairs:**

```
You judge whether two references to MDL (multidistrict litigation) leadership attorneys are the SAME real person.
Evidence per side: name variants, law firm(s), MDL numbers (rough era: 1000s=1990s-2000s, 2000s=2005-2015, 3000s=2020s), mention count.
Rules:
- Name commonness matters: a rare distinctive name (e.g. 'Cabraser') can be the same person even across different firms/eras; a common name (Smith, Davis, Kelly, Miller) needs positive evidence (shared firm lineage, same MDL, compatible middle initials).
- Shared firm is NOT sufficient: relatives and colleagues share firms (father/son, siblings). Different generational suffixes (Jr vs Sr vs III vs IV) = DIFFERENT people. Different full first names at the same firm (e.g. Hugh vs Palmer) = likely different people unless one is a documented nickname/middle-name usage.
- OCR/extraction noise is common: token swaps ('Berman Steve'), typos (Becnel/Bencel), truncations, initials. A swap/typo variant with the same firm+MDL context = same person.
- Attorneys DO move firms over a career; firm difference alone never proves distinct.
- unsure means you genuinely cannot tell; do not guess.
Return verdicts for every pair given.
```

**System prompt — firm pairs:**

```
You judge whether two law-firm name clusters from MDL court records are the SAME firm (one lineage).
Evidence: name variants, MDL numbers (era), mention counts.
POLICY (important):
- Renames and continuations = SAME firm: e.g. 'Lerach Coughlin' -> 'Coughlin Stoia' -> 'Robbins Geller'; 'Pepper Hamilton' -> 'Troutman Pepper'; 'Cohen Milstein Hausfeld & Toll' -> 'Cohen Milstein Sellers & Toll'. Added/dropped partner surnames over time = same lineage.
- Branch offices / location or department tags = SAME firm ('Hausfeld LLP - DC' = 'Hausfeld LLP').
- Spin-offs are DIFFERENT firms: partners leaving to found a new firm ('Hausfeld LLP' != 'Cohen Milstein'; 'Kaiser Gornick' != 'Levin Simes'; 'Joseph Saveri Law Firm' != 'Saveri & Saveri').
- Different firms sharing common surnames are DIFFERENT ('Morgan & Morgan' != 'Morgan Law Firm Ltd'; two unrelated 'Smith' firms). Government offices of different states are DIFFERENT.
- Use your knowledge of the U.S. plaintiffs' bar. unsure means you cannot tell; do not guess.
Return verdicts for every pair given.
```

**User message:** candidate pairs are batched (14 per call) as numbered `PAIR k:` blocks, each side rendered with full context by:

```python
def render_att(e):
    fs = "; ".join(f for f, _ in e["firms"].most_common(3)) or "(no firm recorded)"
    names = ", ".join(n for n, _ in e["fulls"].most_common(3))
    sfx = f" [suffix {'/'.join(e['suffixes'])}]" if e["suffixes"] else ""
    return (f"names: {names}{sfx} | firm(s): {fs} | MDLs: {', '.join(e['mdls'][:10]) or '?'} "
            f"| corpus: {'/'.join(e['corpora'])} | mentions: {e['n']}")

def render_firm(e):
    names = ", ".join(n for n, _ in e["names"].most_common(3))
    return f"names: {names} | MDLs: {', '.join(e['mdls'][:12]) or '?'} | mentions: {e['n']}"
```

followed by `Return a verdict for each of the N pairs (id 0..N-1).` Output is a JSON array of `{id, verdict: same|distinct|unsure, confidence, reason}`.

**Web-grounded second pass** (pairs the batch pass judged `unsure`): one pair per call via the Responses API with the `web_search` tool, prompt =

```
{system prompt above}

A: {rendered entity A}
B: {rendered entity B}

Research if needed, then answer with JSON only: {"verdict":"same|distinct|unsure","confidence":"high|medium|low","reason":"..."}
```

Any pair still `unsure` after the web pass defaults to **distinct**.

## Attorney demographics (`code/attorney_demographics.py`, gpt-5.5 + web search)

**System prompt:**

```
You are a meticulous legal-research assistant building a dataset of MDL leadership attorneys for
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
undergrad_grad_year, bar_states:[...], sources:[...], confidence, notes}.
```

**User message** — assembled per canonical attorney by:

```python
def build_query(row):
    return (f"Attorney: {row.get('Canonical_Name','')}\n"
            f"Law firm(s): {row.get('Firms','') or 'unknown'}\n"
            f"Led leadership in MDL number(s): {row.get('MDLs','') or 'unknown'}\n"
            f"Find the demographic + education fields per the rules and return the JSON.")
```
