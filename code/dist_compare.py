#!/usr/bin/env python3
"""Distributional comparison of OLD (gold, human-coded) vs NEW (LLM-extracted) MDL leadership data.

Two panels disentangle method from population:
  PANEL A (METHOD effect)     : gold  vs  OUR extraction, on the SAME old MDLs (.bak_devholdout).
                                Same cases, different method -> isolates extraction bias.
  PANEL B (what you asked)     : gold-old  vs  extracted-new. Different cases AND method combined.

Tests are hand-rolled (no scipy) and SELF-VALIDATED against known values. We lead with EFFECT SIZES
(medians / proportions / differences); at this N almost any difference is 'significant', so p-values
are reported but not the headline.
"""
import os, csv, json, re, math
from collections import Counter, defaultdict
import openpyxl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------- hand-rolled stats ----------------
def _sf(z):  # P(Z > |z|) two-tailed helper uses erfc
    return 0.5 * math.erfc(abs(z) / math.sqrt(2))


def gammln(x):
    cof = [76.18009172947146, -86.50532032941677, 24.01409824083091,
           -1.231739572450155, 0.1208650973866179e-2, -0.5395239384953e-5]
    y = x; tmp = x + 5.5; tmp -= (x + 0.5) * math.log(tmp); ser = 1.000000000190015
    for c in cof:
        y += 1; ser += c / y
    return -tmp + math.log(2.5066282746310005 * ser / x)


def gammq(a, x):
    if x <= 0 or a <= 0:
        return 1.0
    gln = gammln(a)
    if x < a + 1:                       # series -> P, return 1-P
        ap, s, d = a, 1.0 / a, 1.0 / a
        for _ in range(2000):
            ap += 1; d *= x / ap; s += d
            if abs(d) < abs(s) * 1e-14:
                break
        return 1.0 - s * math.exp(-x + a * math.log(x) - gln)
    tiny = 1e-300                        # continued fraction -> Q
    b = x + 1 - a; c = 1 / tiny; d = 1 / b; h = d
    for i in range(1, 2000):
        an = -i * (i - a); b += 2
        d = an * d + b; d = tiny if abs(d) < tiny else d
        c = b + an / c; c = tiny if abs(c) < tiny else c
        d = 1 / d; dl = d * c; h *= dl
        if abs(dl - 1) < 1e-14:
            break
    return math.exp(-x + a * math.log(x) - gln) * h


def chi2_p(chi2, df):
    return gammq(df / 2.0, chi2 / 2.0)


def chi2_test(table):
    R, C = len(table), len(table[0])
    rs = [sum(r) for r in table]; cs = [sum(table[r][c] for r in range(R)) for c in range(C)]
    tot = sum(rs); chi2 = 0.0
    for r in range(R):
        for c in range(C):
            e = rs[r] * cs[c] / tot
            if e > 0:
                chi2 += (table[r][c] - e) ** 2 / e
    df = (R - 1) * (C - 1)
    V = math.sqrt(chi2 / (tot * min(R - 1, C - 1))) if tot and min(R - 1, C - 1) else 0.0
    return chi2, df, chi2_p(chi2, df), V


def mannwhitney(x, y):
    n1, n2 = len(x), len(y)
    if not n1 or not n2:
        return float("nan"), float("nan")
    allv = sorted([(v, 0) for v in x] + [(v, 1) for v in y])
    ranks = [0.0] * len(allv); i = 0; tie = 0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        r = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            ranks[k] = r
        t = j - i + 1; tie += t ** 3 - t; i = j + 1
    R1 = sum(ranks[k] for k in range(len(allv)) if allv[k][1] == 0)
    U1 = R1 - n1 * (n1 + 1) / 2.0
    mu = n1 * n2 / 2.0; N = n1 + n2
    var = (n1 * n2 / 12.0) * ((N + 1) - tie / (N * (N - 1.0))) if N > 1 else 0.0
    if var <= 0:
        return U1, 1.0
    z = (U1 - mu) / math.sqrt(var)
    return U1, min(1.0, 2 * _sf(z))


def two_prop(s1, n1, s2, n2):
    if not n1 or not n2:
        return 1.0
    p = (s1 + s2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = (s1 / n1 - s2 / n2) / se
    return min(1.0, 2 * _sf(z))


# ---------------- self-validation ----------------
def _selftest():
    _, _, p1, _ = chi2_test([[1, 0], [0, 0]])  # degenerate guard (no crash)
    assert abs(chi2_p(3.841459, 1) - 0.05) < 0.002, chi2_p(3.841459, 1)
    assert abs(chi2_p(6.6349, 1) - 0.01) < 0.002, chi2_p(6.6349, 1)
    assert abs(chi2_p(9.21034, 2) - 0.01) < 0.002, chi2_p(9.21034, 2)
    c, df, p, V = chi2_test([[10, 20], [20, 10]])
    assert abs(c - 6.6667) < 0.01 and abs(p - 0.0098) < 0.002, (c, p)
    # MW known: x=[1,2,3,4], y=[5,6,7,8] -> U1=0, strong separation
    U, p = mannwhitney([1, 2, 3, 4], [5, 6, 7, 8])
    assert U == 0.0, U
    print("  self-test: stats OK (chi2 p@3.841/df1=%.4f, MW U=%g)" % (chi2_p(3.841459, 1), U))


# ---------------- data loaders ----------------
def load_csv(p):
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_xlsx(path, sheet):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet]
    it = ws.iter_rows(values_only=True)
    hdr = [str(c) if c is not None else "" for c in next(it)]
    return [dict(zip(hdr, [("" if v is None else v) for v in row])) for row in it]


def truthy(v):
    return str(v).strip().lower() in ("true", "checked", "1", "yes", "x")


def fnum(v):
    try:
        return float(str(v).strip())
    except Exception:
        return None


def split_roles(s):
    return [t.strip() for t in re.split(r"[;,]", str(s or "")) if t.strip()]


def nmdl(m):
    return re.sub(r"^0+(\d)", r"\1", str(m or "").strip())


ROLE_BUCKETS = ["LeadCounsel", "ClassCounsel", "Management", "Communications", "Liaison"]


def role_bucket(roles):
    return [r if r in ROLE_BUCKETS else "Other" for r in roles] or ["(none)"]


# Build a normalized dataset {orders:[...], appts:[...]} from a source.
def from_gold():
    go = load_csv(os.path.join(ROOT, "csvs_current_dataset", "Orders-Export view.csv"))
    ga = load_csv(os.path.join(ROOT, "csvs_current_dataset", "Appointments-Grid view.csv"))
    orders = [{"mdl": nmdl(r.get("MDL_No")), "order": (r.get("Order_No") or "").strip(),
               "contested": truthy(r.get("Contested")), "ou": fnum(r.get("OU_Create"))} for r in go]
    appts = []
    for r in ga:
        fn, ln = (r.get("First Name") or "").strip(), (r.get("Last Name") or "").strip()
        appts.append({"mdl": nmdl(r.get("MDL_No (from Orders)")), "order": (r.get("Order No.") or "").strip(),
                      "roles": split_roles(r.get("Appointment Types")), "side": (r.get("Plaintiff/Defendant") or "").strip(),
                      "is_firm": (r.get("Appointee Type") == "Firm") or not (fn or ln),
                      "interim": truthy(r.get("Interim")), "ind": bool(fn or ln) and r.get("Appointee Type") != "Firm"})
    return orders, appts


def from_jsonl(path, only_mdls=None):
    orders, appts = [], []
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        rec = json.loads(line)
        mdl = nmdl(rec.get("MDL_No") or (re.match(r"^(\d+)", rec.get("Source_File", "")) or [None, ""])[0])
        if only_mdls is not None and mdl not in only_mdls:
            continue
        ap = rec.get("Appointments") or []
        if not (ap or rec.get("Needs_Motion_Reading") is True):
            continue                              # keep_order policy: leadership orders only
        orders.append({"mdl": mdl, "order": (rec.get("Order_No") or "").strip(),
                       "contested": rec.get("Contested") is True, "ou": fnum(rec.get("OU_Create"))})
        for a in ap:
            fn, ln = (a.get("first_name") or "").strip(), (a.get("last_name") or "").strip()
            appts.append({"mdl": mdl, "order": (rec.get("Order_No") or "").strip(),
                          "roles": a.get("appointment_types") or [], "side": (a.get("plaintiff_defendant") or "").strip(),
                          "is_firm": a.get("appointee_type") == "Firm" or not (fn or ln),
                          "interim": a.get("interim") is True, "ind": bool(fn or ln) and a.get("appointee_type") != "Firm"})
    return orders, appts


# ---------------- metrics + comparison ----------------
def metrics(orders, appts):
    by_order = defaultdict(int)        # individuals per order
    for a in appts:
        if a["ind"]:
            by_order[(a["mdl"], a["order"])] += 1
    appt_bearing_orders = set(by_order)
    ind_per_order = [by_order[k] for k in appt_bearing_orders] or [0]
    orders_per_mdl = Counter(m for (m, o) in appt_bearing_orders)
    ind_per_mdl = defaultdict(int)
    for a in appts:
        if a["ind"]:
            ind_per_mdl[a["mdl"]] += 1
    return {
        "orders": orders, "appts": appts,
        "ind_per_order": ind_per_order,
        "orders_per_mdl": list(orders_per_mdl.values()) or [0],
        "ind_per_mdl": list(ind_per_mdl.values()) or [0],
        "contested": [1 if o["contested"] else 0 for o in orders],
        "ou": [o["ou"] for o in orders if o["ou"] is not None],
    }


def med(v):
    s = sorted(v); n = len(s)
    if not n:
        return float("nan")
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def mean(v):
    return sum(v) / len(v) if v else float("nan")


def role_counts(appts):
    c = Counter()
    for a in appts:
        for r in a["roles"]:
            c[r if r in ROLE_BUCKETS else "Other"] += 1
    return c


def side_counts(appts):
    c = Counter()
    for a in appts:
        s = a["side"]
        c["Plaintiff" if s.lower().startswith("p") else "Defendant" if s.lower().startswith("d") else "Other"] += 1
    return c


def compare(label, A, B):
    mA, mB = metrics(*A), metrics(*B)
    print(f"\n{'='*78}\n{label}\n{'='*78}")
    print(f"{'metric':32s} {'OLD/grp1':>14s} {'NEW/grp2':>14s} {'test':>10s} {'p':>9s}")

    def line(name, g1, g2, p, test):
        flag = ""
        print(f"{name:32s} {g1:>14s} {g2:>14s} {test:>10s} {p:>9}  {flag}")

    # counts (median [mean])
    for key, name in [("ind_per_order", "individuals / order"),
                      ("orders_per_mdl", "leadership orders / MDL"),
                      ("ind_per_mdl", "individuals / MDL"),
                      ("ou", "OU_Create / order")]:
        x, y = mA[key], mB[key]
        _, p = mannwhitney(x, y)
        line(name, f"{med(x):.2f} [{mean(x):.2f}]", f"{med(y):.2f} [{mean(y):.2f}]", f"{p:.3f}", "MannWhit")
    # contested rate
    cA, cB = mA["contested"], mB["contested"]
    line("contested rate (orders)", f"{100*sum(cA)/len(cA):.1f}%", f"{100*sum(cB)/len(cB):.1f}%",
         f"{two_prop(sum(cA),len(cA),sum(cB),len(cB)):.3f}", "2-prop z")
    # interim rate
    iA = [1 if a["interim"] else 0 for a in mA["appts"]]; iB = [1 if a["interim"] else 0 for a in mB["appts"]]
    line("interim rate (appts)", f"{100*sum(iA)/len(iA):.1f}%", f"{100*sum(iB)/len(iB):.1f}%",
         f"{two_prop(sum(iA),len(iA),sum(iB),len(iB)):.3f}", "2-prop z")
    # firm-share of appointees
    fA = [1 if a["is_firm"] else 0 for a in mA["appts"]]; fB = [1 if a["is_firm"] else 0 for a in mB["appts"]]
    line("firm-typed appointee share", f"{100*sum(fA)/len(fA):.1f}%", f"{100*sum(fB)/len(fB):.1f}%",
         f"{two_prop(sum(fA),len(fA),sum(fB),len(fB)):.3f}", "2-prop z")

    # role mix (chi-square over buckets)
    rcA, rcB = role_counts(mA["appts"]), role_counts(mB["appts"])
    cats = ROLE_BUCKETS + ["Other"]
    tbl = [[rcA.get(c, 0) for c in cats], [rcB.get(c, 0) for c in cats]]
    chi, df, p, V = chi2_test(tbl)
    tA, tB = sum(tbl[0]), sum(tbl[1])
    print(f"\n  ROLE MIX (chi2={chi:.1f}, df={df}, p={p:.2e}, Cramer's V={V:.3f}):")
    print(f"    {'role':16s} {'OLD':>10s} {'NEW':>10s}")
    for c in cats:
        print(f"    {c:16s} {100*rcA.get(c,0)/max(1,tA):>9.1f}% {100*rcB.get(c,0)/max(1,tB):>9.1f}%")
    # side mix
    scA, scB = side_counts(mA["appts"]), side_counts(mB["appts"])
    cats2 = ["Plaintiff", "Defendant", "Other"]
    chi, df, p, V = chi2_test([[scA.get(c, 0) for c in cats2], [scB.get(c, 0) for c in cats2]])
    print(f"\n  SIDE MIX (chi2={chi:.1f}, df={df}, p={p:.2e}, V={V:.3f}):  "
          + "  ".join(f"{c}: {100*scA.get(c,0)/max(1,sum(scA.values())):.0f}%/{100*scB.get(c,0)/max(1,sum(scB.values())):.0f}%" for c in cats2))


# ---------------- run ----------------
_selftest()
gold_o, gold_a = from_gold()
gold_mdls = {o["mdl"] for o in gold_o if o["mdl"]}
new_o, new_a = from_jsonl(os.path.join(ROOT, "order_extractions.jsonl"))
bak_o, bak_a = from_jsonl(os.path.join(ROOT, "order_extractions.jsonl.bak_devholdout"))
bak_mdls = {o["mdl"] for o in bak_o if o["mdl"]}

# PANEL A: method effect — gold restricted to the MDLs we also extracted (.bak), vs .bak
gold_o_sub = [o for o in gold_o if o["mdl"] in bak_mdls]
gold_a_sub = [a for a in gold_a if a["mdl"] in bak_mdls]
print(f"\nPANEL A scope: {len(bak_mdls)} MDLs present in BOTH gold and our extraction (.bak)")
compare("PANEL A — METHOD effect: GOLD vs OUR EXTRACTION on the SAME old MDLs",
        (gold_o_sub, gold_a_sub), (bak_o, bak_a))

# PANEL B: gold-old vs extracted-new
print(f"\n\nPANEL B scope: gold {len(gold_mdls)} old MDLs  vs  new {len({o['mdl'] for o in new_o})} MDLs")
compare("PANEL B — GOLD (old) vs EXTRACTED (new)  [population + method combined]",
        (gold_o, gold_a), (new_o, new_a))
