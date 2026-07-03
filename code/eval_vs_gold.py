r"""
================================================================================
 EVALUATION HARNESS — agreement between automated extraction and human gold coding
================================================================================
Deterministic, no LLM judge. Compares our pipeline output (order_extractions.jsonl)
to the human-coded Airtable export in csvs_current_dataset/. Auto-scopes to the
MDLs we extracted AND humans labeled; restrict with --mdls.

    python code/eval_vs_gold.py --mdls 1869,2262,...     # held-out evaluation

--------------------------------------------------------------------------------
 METRICS — three tiers, weighted by importance (Appointments > Orders > Attorneys).
 Identity (was the right THING found?) uses precision/recall/F1. Field VALUES use
 agreement rates. Names are matched on a normalized key (middle initials, suffixes,
 firm punctuation ignored) — spelling is cosmetic, not scored.

 TIER 1 — APPOINTMENTS (primary). Unit = (MDL, appointee). An appointee's roles are
 the UNION of roles assigned to that person/firm across the MDL (robust to which
 order we attribute them to).
   * Identity   : recall / precision / F1 of distinct appointees (the "who").
   * Role       : mean JACCARD overlap of role-sets on matched appointees (PARTIAL
                  credit: |gold∩ours| / |gold∪ours|; 1.0 = identical, 0.5 = one
                  set is twice the overlap, 0.0 = disjoint).
   * Side       : % plaintiff/defendant agreement on matched appointees.
   * Soft F1    : the partial-credit headline — a matched appointee contributes its
                  role-Jaccard instead of a full point, so "found but half-mis-roled"
                  counts as 0.5. soft_recall = Σ_matched J / |gold|, etc.
   * (secondary, descriptive only): interim / appoint-vs-remove agreement.

 TIER 2 — ORDERS. Unit = order (key MDL-Docket), among APPOINTMENT-BEARING gold
 orders. recall / precision / F1, plus agreement on the ANALYTIC fields
 (Order_Types [Jaccard], OU_Create, Contested, structural booleans). Judge/Date are
 reported as metadata, not headline.

 TIER 3 — ATTORNEYS. Distinct-individual recall/precision (the set of unique people).
 Downstream of appointments; exact canonical name + demographics are out of scope.

 Coordination↔Management: a documented one-time definitional reconciliation (the
 codebook author's call that our Management is correct for a committee named
 "Coordination"). Reported BOTH raw and reconciled; NOT an LLM judgment.

 All proportions carry a 95% Wilson confidence interval (small samples).
================================================================================
"""
import argparse
import collections
import csv
import json
import math
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLD_DIR = os.path.join(ROOT, "csvs_current_dataset")
OUT_DIR = os.path.join(ROOT, "eval")
GOLD_ORDERS_CSV = "Orders-Export view"
GOLD_APPTS_CSV = "Appointments-Grid view"

# ---------------- normalizers ----------------
_FIRM_SUFFIX = re.compile(
    r"\b(l\.?l\.?p|l\.?l\.?c|pllc|p\.?l\.?l\.?c|a\.?p\.?c|p\.?c|p\.?a|l\.?p\.?a|lp|ltd|co|chartered|llp|llc|pc|apc|pa)\b",
    re.I)
ROLE_VOCAB = {"leadcounsel", "management", "communications", "classcounsel", "localcounsel",
              "discovery", "motions", "fees", "expert", "bellwether", "coordination",
              "settlement", "trial", "settlementadministration", "prose", "vetting"}


def norm_firm(s):
    s = re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower())
    return re.sub(r"\s+", " ", _FIRM_SUFFIX.sub(" ", s)).strip()


def first_tok(s):
    s = (s or "").strip()
    return re.sub(r"[^a-z]", "", s.split()[0].lower()) if s.split() else ""


def last_norm(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


def as_bool(v):
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in ("checked", "true", "1", "yes")


def role_set(v):
    toks = v if isinstance(v, list) else re.split(r"[;,]", str(v or ""))
    return {re.sub(r"[^a-z]", "", t.lower()) for t in toks
            if re.sub(r"[^a-z]", "", t.lower()) in ROLE_VOCAB}


def jaccard(a, b):
    return len(a & b) / len(a | b) if (a | b) else 1.0


def reconcile(gold_roles):
    """coordination -> management (the documented Defense-Coordination-Committee call)."""
    return (gold_roles - {"coordination"}) | ({"management"} if "coordination" in gold_roles else set())


def is_individual(t, first, last):
    t = str(t or "").strip().lower()
    if t == "firm":
        return False
    if t == "individual":
        return True
    return bool((first or "").strip() or (last or "").strip())


def appointee_key(individual, first, last, firm):
    return ("ind", last_norm(last), first_tok(first)) if individual else ("firm", norm_firm(firm))


# ---- cosmetic-tolerant ENTITY matching (names are cosmetic; match on substance) ----
def _lev(a, b):
    if a == b:
        return 0
    if not a or not b:
        return max(len(a), len(b))
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[-1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _last_eq(a, b):
    """Surnames equal, tolerant of typos and truncation (OCR/coding)."""
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4 and (a.startswith(b) or b.startswith(a)):
        return True
    return min(len(a), len(b)) >= 5 and _lev(a, b) <= 1


def _init_ok(a, b):
    return (not a) or (not b) or a[0] == b[0]


STRICT = False   # set by --strict: exact-key matching only (no fuzzy) for the matching-sensitivity report


def person_pair(g, o):
    """g, o = (last, first) normalized. Tolerant of: first/last SWAP (present in gold), surname
    typos, and first-initial-only forms. Under --strict, requires exact (last, first)."""
    gl, gf = g
    ol, of = o
    if STRICT:
        return gl == ol and gf == of
    if _last_eq(gl, ol) and _init_ok(gf, of):
        return True
    if _last_eq(gf, ol) and _init_ok(gl, of):   # first/last swapped on one side (gold-first ~ our-last)
        return True
    return False


_FIRM_STOP = {"and", "the", "of", "at", "law", "offices", "office", "group", "firm"}


def _firm_tokens(s):
    return {t for t in s.split() if t and t not in _FIRM_STOP}


def firm_pair(a, b):
    """Firm names match if one's significant tokens subset the other (granularity differs:
    'cohen milstein' vs 'cohen milstein hausfeld toll'), tokens overlap >=50%, or a single-token
    name is a spelling variant ('pomeranz'/'pomerantz')."""
    ta, tb = _firm_tokens(a), _firm_tokens(b)
    if not ta or not tb:
        return a == b
    if STRICT:
        return ta == tb
    small, big = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if small <= big:
        return True
    if len(ta & tb) / len(ta | tb) >= 0.5:
        return True
    if len(ta) == 1 and len(tb) == 1:
        return _lev(next(iter(ta)), next(iter(tb))) <= 1
    return False


def keep_order(rec):
    """Mirror of extract_orders.keep_order: keep orders with appointees OR flagged
    Needs_Motion_Reading (real reappointment/by-reference orders). Drop clerical empties."""
    return bool(rec.get("Appointments") or []) or rec.get("Needs_Motion_Reading") is True


def dedup_within(app):
    """Collapse fuzzy-duplicate appointees WITHIN one source before cross-source comparison, so the
    metric counts DISTINCT people, not rows. (Gold contains the same person entered twice with typos
    across orders -- 'Mar/Mark Robinson', 'Cabreser/Cabraser' -- which would otherwise inflate its
    count and create phantom misses.) Uses the same tolerant entity match as the cross-source step."""
    groups = collections.defaultdict(list)
    for (mdl, key), e in app.items():
        groups[(mdl, key[0])].append((key, e))
    out = {}
    for (mdl, typ), items in groups.items():
        reps = []
        for key, e in items:
            idv = (key[1], key[2]) if typ == "ind" else key[1]
            merged = False
            for rk, re_ in reps:
                rv = (rk[1], rk[2]) if typ == "ind" else rk[1]
                if (person_pair(idv, rv) if typ == "ind" else firm_pair(idv, rv)):
                    re_["roles"] |= e["roles"]
                    re_["side"] = re_["side"] or e["side"]
                    re_["interim"] = re_["interim"] or e["interim"]
                    re_["appoint"] = re_["appoint"] or e["appoint"]
                    re_["remove"] = re_["remove"] or e["remove"]
                    merged = True
                    break
            if not merged:
                reps.append((key, dict(e)))
        for rk, re_ in reps:
            out[(mdl, rk)] = re_
    return out


def num(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


def wilson(k, n):
    """95% Wilson score interval for a proportion k/n -> (lo, hi) in percent."""
    if n == 0:
        return (None, None)
    z = 1.96
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(100 * (c - h), 1), round(100 * (c + h), 1))


def prf(matched, gold, our):
    r = matched / gold if gold else 0.0
    p = matched / our if our else 0.0
    f = 2 * r * p / (r + p) if (r + p) else 0.0
    return {"gold": gold, "ours": our, "matched": matched,
            "recall": round(r, 3), "recall_ci": wilson(matched, gold),
            "precision": round(p, 3), "precision_ci": wilson(matched, our),
            "f1": round(f, 3)}


# ---------------- loaders ----------------
def _resolve(stem):
    import glob
    c = glob.glob(os.path.join(GOLD_DIR, stem + "*.csv"))
    if not c:
        raise FileNotFoundError(f"no gold CSV matching '{stem}*.csv'")
    return max(c, key=os.path.getmtime)


def _csv(stem):
    with open(_resolve(stem), encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def docket_of(order_no):
    m = re.match(r"^\s*\d+\s*-\s*(\d+)", (order_no or "").strip())
    return m.group(1) if m else None


def mdl_of(rec):
    m = (rec.get("MDL_No") or "").strip()
    if m:
        return m
    mm = re.match(r"^(\d+)", rec.get("Source_File", ""))
    return mm.group(1) if mm else ""


# ---------------- main ----------------
def main():
    ap = argparse.ArgumentParser(description="Evaluate extraction vs human gold (deterministic).")
    ap.add_argument("--jsonl", default="order_extractions.jsonl")
    ap.add_argument("--mdls", help="restrict to these MDLs (comma-separated)")
    ap.add_argument("--tag", default="", help="suffix for output files, e.g. --tag heldout")
    ap.add_argument("--strict", action="store_true",
                    help="exact-key matching only (no fuzzy name/firm tolerance) -- for the matching-sensitivity report")
    args = ap.parse_args()
    global STRICT
    STRICT = args.strict

    gold_orders = [o for o in _csv(GOLD_ORDERS_CSV) if (o.get("Order_No") or "").strip()]
    gold_appts = _csv(GOLD_APPTS_CSV)
    ours = [json.loads(l) for l in open(os.path.join(ROOT, args.jsonl), encoding="utf-8") if l.strip()]
    ours = [r for r in ours if keep_order(r)]

    our_mdls = {mdl_of(r) for r in ours if mdl_of(r)}
    gold_mdls = {(o.get("MDL_No") or "").strip() for o in gold_orders}
    scope = our_mdls & gold_mdls
    if args.mdls:
        scope &= {s.strip() for s in args.mdls.split(",")}
    scope = sorted(scope, key=lambda x: int(x) if x.isdigit() else x)

    # ===== appointment aggregation: (mdl, appointee) -> {roles, side, interim, appoint, remove} =====
    def agg(side_rows):
        d = {}
        for mdl, key, roles, side, interim, appoint, remove in side_rows:
            e = d.get((mdl, key))
            if e is None:
                name = f"{key[2]} {key[1]}".strip() if key[0] == "ind" else key[1]
                e = d[(mdl, key)] = {"roles": set(), "side": "", "interim": False, "appoint": False,
                                     "remove": False, "_mdl": mdl, "_name": name}
            e["roles"] |= roles
            e["side"] = e["side"] or side
            e["interim"] = e["interim"] or interim
            e["appoint"] = e["appoint"] or appoint
            e["remove"] = e["remove"] or remove
        return d

    gold_rows, our_rows = [], []
    gA_count = collections.Counter()   # (mdl,docket) -> #gold appts (to find appointment-bearing orders)
    for a in gold_appts:
        mdl = (a.get("MDL_No (from Orders)") or "").strip()
        if mdl not in scope:
            continue
        ind = is_individual(a.get("Appointee Type"), a.get("First Name"), a.get("Last Name"))
        key = appointee_key(ind, a.get("First Name"), a.get("Last Name"), a.get("Firm"))
        side = (a.get("Plaintiff/Defendant") or "").strip()
        gold_rows.append((mdl, key, role_set(a.get("Appointment Types")), side,
                          as_bool(a.get("Interim")), as_bool(a.get("Appoint")), as_bool(a.get("Remove"))))
        if ind and (a.get("Firm") or "").strip():   # representation-agnostic: also register the firm as an entity
            gold_rows.append((mdl, ("firm", norm_firm(a.get("Firm"))), set(), side, False, False, False))
        dk = docket_of(a.get("Order No."))
        if dk:
            gA_count[(mdl, dk)] += 1
    for r in ours:
        mdl = mdl_of(r)
        if mdl not in scope:
            continue
        for a in (r.get("Appointments") or []):
            ind = is_individual(a.get("appointee_type"), a.get("first_name"), a.get("last_name"))
            key = appointee_key(ind, a.get("first_name"), a.get("last_name"), a.get("firm"))
            side = (a.get("plaintiff_defendant") or "").strip()
            our_rows.append((mdl, key, role_set(a.get("appointment_types")), side,
                             as_bool(a.get("interim")), as_bool(a.get("appoint")), as_bool(a.get("remove"))))
            if ind and (a.get("firm") or "").strip():   # representation-agnostic firm entity
                our_rows.append((mdl, ("firm", norm_firm(a.get("firm"))), set(), side, False, False, False))
    gold_app, our_app = dedup_within(agg(gold_rows)), dedup_within(agg(our_rows))

    # ----- TIER 1: appointments. Greedy 1-to-1 ENTITY match within each MDL, tolerant of
    # name-form/spelling/swap (names are cosmetic) -- measures EXTRACTION quality, not string match. -----
    gkeys, okeys = set(gold_app), set(our_app)
    matched_pairs = []                # (gold_entry, our_entry, is_individual)
    matched_g, matched_o = set(), set()
    for mdl in scope:
        for typ, pair_fn in (("ind", person_pair), ("firm", firm_pair)):
            gl = [(k, gold_app[k]) for k in gkeys if k[0] == mdl and k[1][0] == typ]
            ol = [(k, our_app[k]) for k in okeys if k[0] == mdl and k[1][0] == typ]
            used = set()
            for gk, ge in gl:
                gid = (gk[1][1], gk[1][2]) if typ == "ind" else gk[1][1]
                for i, (okk, oe) in enumerate(ol):
                    if i in used:
                        continue
                    oid = (okk[1][1], okk[1][2]) if typ == "ind" else okk[1][1]
                    if pair_fn(gid, oid):
                        used.add(i); matched_pairs.append((ge, oe, typ == "ind"))
                        matched_g.add(gk); matched_o.add(okk); break
    # split by entity type: INDIVIDUALS (the people) vs FIRMS (representation-agnostic -- a firm counts
    # whether gold/ours emitted it as a row or only as an individual's firm attribute).
    gi = sum(1 for k in gkeys if k[1][0] == "ind"); oi = sum(1 for k in okeys if k[1][0] == "ind")
    gf = sum(1 for k in gkeys if k[1][0] == "firm"); ofm = sum(1 for k in okeys if k[1][0] == "firm")
    mi = sum(1 for _g, _o, ind in matched_pairs if ind)
    mf = sum(1 for _g, _o, ind in matched_pairs if not ind)
    individuals = prf(mi, gi, oi)
    firms = prf(mf, gf, ofm)
    combined = prf(len(matched_pairs), len(gkeys), len(okeys))

    # role / side / soft are PEOPLE metrics -> individuals only (derived firm entities carry no roles)
    role_jacc, role_jacc_recon, side_ok, side_total = [], [], 0, 0
    soft_num_recon = 0.0
    role_disagree = []
    for g, o, ind in matched_pairs:
        if not ind:
            continue
        j = jaccard(g["roles"], o["roles"])
        jr = jaccard(reconcile(g["roles"]), o["roles"])
        role_jacc.append(j); role_jacc_recon.append(jr); soft_num_recon += jr
        if g["side"]:
            side_total += 1; side_ok += int(g["side"].lower() == o["side"].lower())
        if g["roles"] != o["roles"]:
            role_disagree.append([g["_mdl"], g["_name"], ",".join(sorted(g["roles"])),
                                  ",".join(sorted(o["roles"])), round(j, 2)])
    ni = len(role_jacc)
    appt = {
        "individuals": individuals, "firms": firms, "combined": combined,
        "role_jaccard_mean": round(sum(role_jacc) / ni, 3) if ni else None,
        "role_jaccard_mean_reconciled": round(sum(role_jacc_recon) / ni, 3) if ni else None,
        "side_agreement_pct": round(100 * side_ok / side_total, 1) if side_total else None,
        "soft_recall": round(soft_num_recon / gi, 3) if gi else None,
        "soft_precision": round(soft_num_recon / oi, 3) if oi else None,
    }
    sr, sp = appt["soft_recall"] or 0, appt["soft_precision"] or 0
    appt["soft_f1"] = round(2 * sr * sp / (sr + sp), 3) if (sr + sp) else 0.0
    inter_ok = sum(1 for g, o, ind in matched_pairs if ind and g["interim"] == o["interim"])
    appt["interim_agreement_pct"] = round(100 * inter_ok / ni, 1) if ni else None

    # ----- TIER 2: orders (appointment-bearing) -----
    gold_ord = {}
    for o in gold_orders:
        mdl = (o.get("MDL_No") or "").strip()
        dk = docket_of(o.get("Order_No"))
        if mdl in scope and dk and gA_count.get((mdl, dk)):   # appointment-bearing only
            gold_ord[(mdl, dk)] = o
    our_ord = {}
    for r in ours:
        mdl = mdl_of(r)
        dk = str(r["Docket_No"]) if r.get("Docket_No") is not None else docket_of(r.get("Order_No"))
        if mdl in scope and dk:
            our_ord[(mdl, dk)] = r
    gk, ok = set(gold_ord), set(our_ord)
    matched_ord = gk & ok
    order_identity = prf(len(matched_ord), len(gk), len(ok))

    ofield = collections.defaultdict(lambda: [0, 0])
    otype_jacc, otype_jacc_recon = [], []
    for key in matched_ord:
        g, o = gold_ord[key], our_ord[key]
        gs, os_ = role_set(g.get("Order_Types")), role_set(o.get("Order_Types"))
        if gs or os_:
            otype_jacc.append(jaccard(gs, os_)); otype_jacc_recon.append(jaccard(reconcile(gs), os_))
            ofield["Order_Types(exact)"][1] += 1; ofield["Order_Types(exact)"][0] += int(gs == os_)
        ofield["OU_Create"][1] += 1; ofield["OU_Create"][0] += int(num(g.get("OU_Create")) == num(o.get("OU_Create")))
        for f in ("Contested", "Rule_23", "OU_Functions", "Limit_Nonleader_Practice",
                  "IRPA_Duties_to_Clients", "OU_Duties_to_Nonclients"):
            ofield[f][1] += 1; ofield[f][0] += int(as_bool(g.get(f)) == as_bool(o.get(f)))
        if (g.get("Judge") or "").strip():
            ofield["Judge(meta)"][1] += 1
            ofield["Judge(meta)"][0] += int(g["Judge"].strip().lower() == str(o.get("Judge") or "").strip().lower())
        if (g.get("Date") or "").strip():
            ofield["Date(meta)"][1] += 1
            ofield["Date(meta)"][0] += int(g["Date"].strip()[:10] == str(o.get("Date") or "").strip()[:10])

    # ----- TIER 3: attorneys = the distinct individuals from Tier 1 -----
    attorneys = individuals

    # ----- per-MDL table -----
    per_mdl = []
    for m in scope:
        g_app = sum(1 for k in gkeys if k[0] == m)
        o_app = sum(1 for k in okeys if k[0] == m)
        mm = sum(1 for k in matched_g if k[0] == m)
        g_o = sum(1 for k in gk if k[0] == m)
        o_o = sum(1 for k in ok if k[0] == m)
        per_mdl.append({"mdl": m, "gold_appointees": g_app, "our_appointees": o_app, "matched": mm,
                        "gold_orders": g_o, "our_orders": o_o})

    # ===== write =====
    os.makedirs(OUT_DIR, exist_ok=True)
    sfx = ("_" + args.tag) if args.tag else ""
    metrics = {
        "scope_mdls": scope,
        "tier1_appointments": appt,
        "tier2_orders": {"identity": order_identity,
                         "field_agreement": {k: {"agree": v[0], "total": v[1],
                                                  "pct": round(100 * v[0] / v[1], 1) if v[1] else None,
                                                  "ci": wilson(v[0], v[1])} for k, v in sorted(ofield.items())},
                         "order_types_jaccard_mean": round(sum(otype_jacc) / len(otype_jacc), 3) if otype_jacc else None,
                         "order_types_jaccard_mean_reconciled": round(sum(otype_jacc_recon) / len(otype_jacc_recon), 3) if otype_jacc_recon else None},
        "tier3_attorneys": attorneys,
        "per_mdl": per_mdl,
    }
    with open(os.path.join(OUT_DIR, f"metrics{sfx}.json"), "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    with open(os.path.join(OUT_DIR, f"appt_missing{sfx}.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["MDL", "appointee", "gold_roles", "side"])
        for k in sorted(gkeys - matched_g):
            g = gold_app[k]; w.writerow([g["_mdl"], g["_name"], ",".join(sorted(g["roles"])), g["side"]])
    with open(os.path.join(OUT_DIR, f"appt_extra{sfx}.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["MDL", "appointee", "our_roles", "side"])
        for k in sorted(okeys - matched_o):
            o = our_app[k]; w.writerow([o["_mdl"], o["_name"], ",".join(sorted(o["roles"])), o["side"]])
    with open(os.path.join(OUT_DIR, f"role_disagreements{sfx}.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["MDL", "appointee", "gold_roles", "our_roles", "jaccard"])
        w.writerows(sorted(role_disagree))

    write_report(metrics, otype_jacc, otype_jacc_recon, role_jacc, role_jacc_recon, sfx)

    # ===== console =====
    a, oi_ = appt, order_identity
    print("=" * 74)
    print(f"HELD-OUT EVAL — {len(scope)} MDLs: {', '.join(scope)}")
    print("=" * 74)
    print("TIER 1  APPOINTMENTS  (primary)")
    ii, ff_, cc = a["individuals"], a["firms"], a["combined"]
    print(f"  INDIVIDUALS      recall {ii['recall']*100:5.1f}% {ii['recall_ci']}  "
          f"precision {ii['precision']*100:5.1f}% {ii['precision_ci']}  F1 {ii['f1']*100:.1f}%   "
          f"(gold {ii['gold']} / ours {ii['ours']} / matched {ii['matched']})")
    print(f"  FIRMS (repr-agnostic) recall {ff_['recall']*100:5.1f}%  precision {ff_['precision']*100:5.1f}%  F1 {ff_['f1']*100:.1f}%   "
          f"(gold {ff_['gold']} / ours {ff_['ours']} / matched {ff_['matched']})")
    print(f"  COMBINED         recall {cc['recall']*100:5.1f}%  precision {cc['precision']*100:5.1f}%  F1 {cc['f1']*100:.1f}%")
    print(f"  Role  (Jaccard)  {a['role_jaccard_mean']*100:.1f}%  (reconciled {a['role_jaccard_mean_reconciled']*100:.1f}%)   "
          f"Side {a['side_agreement_pct']}%   [interim {a['interim_agreement_pct']}%]")
    print(f"  SOFT  (role-weighted)  recall {a['soft_recall']*100:.1f}%  precision {a['soft_precision']*100:.1f}%  F1 {a['soft_f1']*100:.1f}%")
    print("TIER 2  ORDERS")
    print(f"  Identity         recall {oi_['recall']*100:5.1f}% {oi_['recall_ci']}  "
          f"precision {oi_['precision']*100:5.1f}% {oi_['precision_ci']}  F1 {oi_['f1']*100:.1f}%   "
          f"(gold {oi_['gold']} / ours {oi_['ours']} / matched {oi_['matched']})")
    for k, v in sorted(ofield.items()):
        if v[1]:
            print(f"     {k:28} {100*v[0]/v[1]:5.1f}%  ({v[0]}/{v[1]})")
    if otype_jacc:
        print(f"     Order_Types Jaccard         {sum(otype_jacc)/len(otype_jacc)*100:.1f}% (recon {sum(otype_jacc_recon)/len(otype_jacc_recon)*100:.1f}%)")
    print("TIER 3  ATTORNEYS (distinct individuals)")
    print(f"  recall {attorneys['recall']*100:.1f}%  precision {attorneys['precision']*100:.1f}%  F1 {attorneys['f1']*100:.1f}%")
    print(f"\n wrote eval/report{sfx}.md, metrics{sfx}.json, appt_missing/extra + role_disagreements")
    return 0


def write_report(M, otj, otjr, rj, rjr, sfx):
    a = M["tier1_appointments"]; ii = a["individuals"]; ff_ = a["firms"]; cc = a["combined"]
    o = M["tier2_orders"]; t = M["tier3_attorneys"]
    L = ["# Held-out evaluation — extraction vs human gold\n",
         f"**Scope:** {len(M['scope_mdls'])} MDLs never used in development: {', '.join(M['scope_mdls'])}\n",
         "Deterministic agreement (no LLM judge). Names matched on a normalized key (spelling/middle "
         "initials/suffixes ignored); firms compared representation-agnostically (row or attribute). "
         "95% Wilson CIs in brackets.\n",
         "\n## Tier 1 — Appointments (primary)\n",
         f"- **Individuals (the people):** recall **{ii['recall']*100:.1f}%** {ii['recall_ci']}, "
         f"precision **{ii['precision']*100:.1f}%** {ii['precision_ci']}, F1 {ii['f1']*100:.1f}% "
         f"(gold {ii['gold']}, ours {ii['ours']}, matched {ii['matched']})",
         f"- **Firms (representation-agnostic):** recall {ff_['recall']*100:.1f}%, precision {ff_['precision']*100:.1f}%, "
         f"F1 {ff_['f1']*100:.1f}% (gold {ff_['gold']}, ours {ff_['ours']}, matched {ff_['matched']})",
         f"- **Combined (individuals + firms):** recall {cc['recall']*100:.1f}%, precision {cc['precision']*100:.1f}%, "
         f"F1 {cc['f1']*100:.1f}%",
         f"- **Role accuracy (Jaccard, partial credit):** {a['role_jaccard_mean']*100:.1f}% "
         f"(reconciled {a['role_jaccard_mean_reconciled']*100:.1f}%)",
         f"- **Side agreement:** {a['side_agreement_pct']}%",
         f"- **Soft F1 (role-weighted headline):** recall {a['soft_recall']*100:.1f}%, "
         f"precision {a['soft_precision']*100:.1f}%, **F1 {a['soft_f1']*100:.1f}%**",
         f"- *(secondary) interim agreement: {a['interim_agreement_pct']}%*\n",
         "\n## Tier 2 — Orders (appointment-bearing)\n",
         f"- **Identity:** recall **{o['identity']['recall']*100:.1f}%** {o['identity']['recall_ci']}, "
         f"precision **{o['identity']['precision']*100:.1f}%** {o['identity']['precision_ci']}, "
         f"F1 {o['identity']['f1']*100:.1f}% (gold {o['identity']['gold']}, ours {o['identity']['ours']}, "
         f"matched {o['identity']['matched']})",
         "\n| analytic field | agreement | n |", "|---|---|---|"]
    for k, v in o["field_agreement"].items():
        if v["total"]:
            L.append(f"| {k} | {v['pct']}% {v['ci']} | {v['agree']}/{v['total']} |")
    if otj:
        L.append(f"\n*Order_Types mean Jaccard: {sum(otj)/len(otj)*100:.1f}% (reconciled {sum(otjr)/len(otjr)*100:.1f}%)*")
    L += ["\n## Tier 3 — Attorneys (distinct individuals)\n",
          f"- recall {t['recall']*100:.1f}% {t['recall_ci']}, precision {t['precision']*100:.1f}% {t['precision_ci']}, "
          f"F1 {t['f1']*100:.1f}% (downstream of appointments; exact names/demographics out of scope)\n",
          "\n## Per-MDL\n", "| MDL | gold appt | our appt | matched | gold ord | our ord |", "|---|---|---|---|---|---|"]
    for r in M["per_mdl"]:
        L.append(f"| {r['mdl']} | {r['gold_appointees']} | {r['our_appointees']} | {r['matched']} "
                 f"| {r['gold_orders']} | {r['our_orders']} |")
    L += ["\n## Files\n", f"- eval/metrics{sfx}.json, appt_missing{sfx}.csv, appt_extra{sfx}.csv, role_disagreements{sfx}.csv"]
    with open(os.path.join(OUT_DIR, f"report{sfx}.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    raise SystemExit(main())
