#!/usr/bin/env python3
"""Dedup v2 — LLM-adjudicated entity resolution for attorneys and firms.

Design (agreed 2026-07-03):
  A. GENEROUS deterministic candidate generation (rules only propose, never decide):
     - hard normalization (unicode->ascii, particles, doubled tokens, surname-only salvage)
     - attorneys: unordered soundex-pair blocking (catches first/last swaps), last-name
       edit<=2, same-firm + weak name, token-multiset equality
     - firms: rare-token blocking (no positional keys); generic tokens never propose
  B. Sub-entity aggregation at (name-key x firm-signature) so same-name-different-people
     collisions become VISIBLE, adjudicated pairs instead of silent fusions.
  C. gpt-5.5 adjudicates EVERY candidate pair (batched, cached, auditable).
     Hard rules only where certain: suffix conflict (Jr/Sr/III/IV) = auto-distinct.
     Policy: firm renames/mergers = SAME lineage; spin-offs = DISTINCT.
             unsure defaults to DISTINCT.
  D. Web-grounded second pass (gpt-5.5 + web_search) for 'unsure' pairs.
  E. Greedy confidence-ordered clustering with consistency VETO (no transitive blobs:
     indirect incompatible given-names / disjoint firm-tokens require a direct edge).
  F. Gold gate: pairwise P/R vs human canonical names (old corpus). Adopt only if
     P>=0.95 and R>=0.85 (baseline v1: P=0.904 R=0.587).

Stages (resumable):
  python3 dedup_v2.py --stage candidates          # free: volumes + exact cost estimate
  python3 dedup_v2.py --stage adjudicate          # paid: LLM batch adjudication (cached)
  python3 dedup_v2.py --stage web                 # paid: web pass on unsure (cached)
  python3 dedup_v2.py --stage cluster             # free: cluster + guard + gold score + write v2 rosters
"""
import argparse, csv, json, os, re, sys, threading, unicodedata
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import combinations

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "code"))
from dedup_attorneys import soundex, lev, FIRM_STOP, firm_tokens  # reuse validated helpers

JSONL = os.path.join(ROOT, "order_extractions_unified.jsonl")
CAND_ATT = os.path.join(ROOT, "dedup_v2_candidates_attorneys.jsonl")
CAND_FIRM = os.path.join(ROOT, "dedup_v2_candidates_firms.jsonl")
CACHE = os.path.join(ROOT, "dedup_v2_adjudications.jsonl")          # every LLM decision, both kinds
WEBCACHE = os.path.join(ROOT, "dedup_v2_web_adjudications.jsonl")
OUT_ATT = os.path.join(ROOT, "canonical_attorneys_v2.csv")
OUT_FIRM = os.path.join(ROOT, "canonical_firms_v2.csv")
DECISIONS = os.path.join(ROOT, "dedup_v2_decisions.csv")            # full audit trail
MODEL = "gpt-5.5"
PRICE_IN, PRICE_OUT = 1.25, 10.0   # $/M tokens

# ---------------- normalization ----------------
PARTICLES = {"de", "del", "della", "van", "von", "der", "den", "da", "di", "la", "le", "st", "saint"}
SUFFIXES = {"jr": "jr", "sr": "sr", "ii": "2", "iii": "3", "iv": "4", "v": "5"}
GENERIC_FIRM = {"trial", "lawyers", "lawyer", "legal", "counsel", "justice", "national", "american",
                "consumer", "center", "centre", "complex", "litigation", "injury", "attorney",
                "general", "state", "states", "united", "advocates", "partners", "counselors",
                "international", "global", "us", "usa"} | {s for s in (
                "alabama alaska arizona arkansas california colorado connecticut delaware florida georgia "
                "hawaii idaho illinois indiana iowa kansas kentucky louisiana maine maryland massachusetts "
                "michigan minnesota mississippi missouri montana nebraska nevada hampshire jersey mexico "
                "york carolina dakota ohio oklahoma oregon pennsylvania rhode island tennessee texas utah "
                "vermont virginia washington west wisconsin wyoming new chicago boston angeles francisco "
                "diego orleans city county dc").split()}
EXTRA_STOP = {"pllp", "lpa", "aplc", "plc", "psc", "chtd", "lllp", "llp", "pc", "inc", "corp",
              "company", "corporation", "br", "fl", "ca", "dc", "dept", "division"}

def ascii_norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s.replace("’", "'")).strip()

def letters(s):
    return re.sub(r"[^a-z]", "", ascii_norm(s).lower())

def name_suffix(full):
    m = re.search(r"\b(jr|sr|ii|iii|iv|v)\.?\s*$", ascii_norm(full).lower().replace(",", " ").strip())
    return SUFFIXES.get(m.group(1)) if m else ""

def last_key(last):
    toks = re.findall(r"[a-z]+", ascii_norm(last).lower())
    toks = [t for t in toks if t not in PARTICLES and t not in SUFFIXES]
    return "".join(toks) or letters(last)

def given_toks(full, last):
    lk = last_key(last)
    toks = [letters(t) for t in re.findall(r"[A-Za-z']+", ascii_norm(full))]
    return [t for t in toks if t and t != lk and t not in PARTICLES and t not in SUFFIXES]

# nickname groups: v1's plus the audit's confirmed gaps; PLUS a prefix rule in related()
NICKS = [
    "william bill billy will willie", "robert bob bobby rob robbie", "richard rick dick rich richie",
    "james jim jimmy jamie", "john jack johnny jon jonathan", "joseph joe joey jos",
    "michael mike micky", "christopher chris kit", "daniel dan danny", "matthew matt",
    "anthony tony", "steven stephen steve", "edward ed eddie ted ned", "thomas tom tommy",
    "charles charlie chuck chas", "kenneth ken kenny", "ronald ron ronnie", "donald don donnie",
    "timothy tim", "gregory greg", "jeffrey jeff jeffery geoffrey geoff", "raymond ray",
    "lawrence larry laurence", "gerald jerry gerry gerard jerrold", "patrick pat paddy",
    "benjamin ben benny", "samuel sam sammy", "frederick fred freddy", "theodore theo ted",
    "andrew andy drew", "nicholas nick", "alexander alex sandy alexandra",
    "elizabeth liz beth betsy eliza lizzie", "margaret meg peggy maggie marge",
    "katherine kathryn kate katie kathy catherine cathy kay kathleen",
    "susan sue susie suzanne", "deborah deb debbie debra",
    "patricia pat patty tricia trish", "barbara barb", "jennifer jen jenny jenniffer",
    "victoria vicki vicky tori", "kimberly kim", "pamela pam", "cynthia cindy",
    "sandra sandy", "rebecca becky", "michelle shelly michele", "stephanie steph",
    "norman norm", "ernest ernie", "leonard lenny leo len", "maxwell max", "willard will",
    "russell russ", "bradford brad bradley", "douglas doug douglass", "vincent vince vinny",
    "eugene gene", "harold hal harry", "albert al bert", "arthur art", "walter walt wally",
    "francis frank fran francisco", "peter pete", "philip phil phillip", "dennis denny",
    "stanley stan", "howard howie", "irving irv", "melvin mel", "sheldon shelly",
    "solomon sol", "seymour sy", "hyman hy", "abraham abe", "isaac ike",
]
NICK = {}
for g in NICKS:
    ws = g.split()
    for w in ws:
        NICK.setdefault(w, set()).update(ws)

def given_related(a, b):
    """Is given-name token a compatible with b? exact / nick / initial / prefix / edit."""
    if not a or not b:
        return True                       # missing given name never blocks
    if a == b:
        return True
    if b in NICK.get(a, ()):
        return True
    if len(a) == 1 or len(b) == 1:
        return a[0] == b[0]
    if a.startswith(b) or b.startswith(a):
        return True
    if a[0] == b[0] and lev(a, b) <= 1:
        return True
    # transposition (Aimee/Amiee) without same-first-letter gate
    return sorted(a) == sorted(b) and lev(a, b) <= 2

def names_compatible(gA, gB):
    """Full given-token lists compatible? (used for candidate filter AND the cluster veto)"""
    fa = [t for t in gA if len(t) >= 2]
    fb = [t for t in gB if len(t) >= 2]
    if not fa or not fb:
        return True
    return any(given_related(a, b) for a in fa for b in fb) or bool(set(gA) & set(gB))

def firm_sig(firm):
    toks = {t for t in firm_tokens(firm) if t not in GENERIC_FIRM and t not in EXTRA_STOP}
    return frozenset(toks)

# ---------------- load mentions ----------------
def load_mentions():
    """Yield attorney + firm mentions with full provenance."""
    att, frm = [], []
    for line in open(JSONL, encoding="utf-8"):
        if not line.strip():
            continue
        rec = json.loads(line)
        mdl = re.sub(r"^0+(\d)", r"\1", str(rec.get("MDL_No") or
                     (re.match(r"^(\d+)", rec.get("Source_File", "")) or [None, ""])[0] or ""))
        corpus = rec.get("_corpus", "?")
        for a in rec.get("Appointments") or []:
            fn = ascii_norm(a.get("first_name")); ln = ascii_norm(a.get("last_name"))
            full = ascii_norm(a.get("full_name")) or f"{fn} {ln}".strip()
            firm = ascii_norm(a.get("firm"))
            roles = a.get("appointment_types") or []
            gold = ascii_norm(a.get("_gold_canonical"))
            if firm:
                frm.append({"firm": firm, "mdl": mdl, "corpus": corpus})
            if a.get("appointee_type") == "Firm" or not (fn or ln):
                continue
            f_tok = letters(fn.split()[0]) if fn.split() else ""
            l_key = last_key(ln)
            if f_tok and f_tok == l_key:                 # doubled token "Zapala Zapala"
                f_tok = ""
            att.append({"first": f_tok, "last": l_key, "full": full, "given": given_toks(full, ln),
                        "suffix": name_suffix(full), "firm": firm, "fsig": firm_sig(firm),
                        "mdl": mdl, "corpus": corpus, "roles": roles, "gold": gold})
    return att, frm

# ---------------- Stage B: sub-entity aggregation ----------------
def build_att_entities(mentions):
    """(first,last) name-keys -> sub-entities split by disjoint firm signature."""
    keys = defaultdict(list)
    for m in mentions:
        keys[(m["first"], m["last"])].append(m)
    ents = []
    for (f, l), ms in keys.items():
        # group mentions by firm-signature overlap OR shared MDL (union-find over mentions)
        idx = list(range(len(ms)))
        parent = idx[:]
        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]; x = parent[x]
            return x
        for i, j in combinations(idx, 2):
            a, b = ms[i], ms[j]
            if (a["fsig"] & b["fsig"]) or (not a["fsig"]) or (not b["fsig"]) or (a["mdl"] and a["mdl"] == b["mdl"]):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri
        groups = defaultdict(list)
        for i in idx:
            groups[find(i)].append(ms[i])
        for g in groups.values():
            fulls = Counter(m["full"] for m in g if m["full"])
            ents.append({
                "first": f, "last": l, "fulls": fulls,
                "given": set().union(*[set(m["given"]) for m in g]) if g else set(),
                "suffixes": {m["suffix"] for m in g if m["suffix"]},
                "firms": Counter(m["firm"] for m in g if m["firm"]),
                "fsig": frozenset().union(*[m["fsig"] for m in g]),
                "mdls": sorted({m["mdl"] for m in g if m["mdl"]}, key=lambda x: (len(x), x)),
                "corpora": sorted({m["corpus"] for m in g}),
                "roles": sorted({r for m in g for r in m["roles"]}),
                "golds": sorted({m["gold"] for m in g if m["gold"]}),
                "n": len(g),
            })
    return ents

def build_firm_entities(mentions):
    agg = {}
    for m in mentions:
        k = " ".join(sorted(firm_tokens(m["firm"])))
        if not k:
            continue
        e = agg.setdefault(k, {"names": Counter(), "mdls": set(), "corpora": set(), "n": 0})
        e["names"][m["firm"]] += 1
        if m["mdl"]:
            e["mdls"].add(m["mdl"])
        e["corpora"].add(m["corpus"])
        e["n"] += 1
    ents = []
    for k, e in agg.items():
        ents.append({"key": k, "names": e["names"], "sig": firm_sig(e["names"].most_common(1)[0][0]),
                     "alltoks": frozenset(k.split()), "mdls": sorted(e["mdls"], key=lambda x: (len(x), x)),
                     "corpora": sorted(e["corpora"]), "n": e["n"]})
    return ents

# ---------------- Stage A: candidate generation ----------------
def att_display(e):
    return e["fulls"].most_common(1)[0][0] if e["fulls"] else f"{e['first']} {e['last']}".strip()

def att_candidates(ents):
    """Generous pair proposal. Returns list of (i, j, why)."""
    seen, cands = set(), []
    def propose(i, j, why):
        if i == j:
            return
        p = (i, j) if i < j else (j, i)
        if p in seen:
            return
        seen.add(p)
        A, B = ents[p[0]], ents[p[1]]
        # cheap sanity: some name relation OR shared firm-token OR shared MDL
        last_ok = (A["last"] == B["last"] or soundex(A["last"]) == soundex(B["last"])
                   or lev(A["last"], B["last"]) <= 2
                   or (A["last"] and B["last"] and (A["last"].startswith(B["last"]) or B["last"].startswith(A["last"]))))
        swap_ok = (soundex(A["first"] or "") == soundex(B["last"]) and soundex(B["first"] or "") == soundex(A["last"])
                   and bool(A["first"]) and bool(B["first"]))
        ctx = bool(A["fsig"] & B["fsig"]) or bool(set(A["mdls"]) & set(B["mdls"]))
        first_ok = given_related(A["first"], B["first"]) or names_compatible(A["given"], B["given"])
        if swap_ok or (last_ok and (first_ok or ctx)):
            cands.append((p[0], p[1], why))
    # block 1: unordered soundex pair {sdx(first), sdx(last)} — catches swaps natively
    b1 = defaultdict(list)
    for i, e in enumerate(ents):
        k = frozenset({soundex(e["first"] or e["last"]), soundex(e["last"])})
        b1[k].append(i)
    for idxs in b1.values():
        if len(idxs) <= 40:
            for i, j in combinations(idxs, 2):
                propose(i, j, "sdx-pair")
    # block 2: last-name prefix (3) + first initial band, for typo lasts
    b2 = defaultdict(list)
    for i, e in enumerate(ents):
        if e["last"]:
            b2[(e["last"][:3], (e["first"] or " ")[0])].append(i)
            b2[(e["last"][:3], "*")].append(i)
    for idxs in b2.values():
        if len(idxs) <= 40:
            for i, j in combinations(idxs, 2):
                propose(i, j, "last3")
    # block 3: shared rare firm token (same-firm colleagues with mangled names)
    df = Counter(t for e in ents for t in e["fsig"])
    b3 = defaultdict(list)
    for i, e in enumerate(ents):
        for t in e["fsig"]:
            if df[t] <= 25:
                b3[t].append(i)
    for idxs in b3.values():
        if len(idxs) <= 60:
            for i, j in combinations(idxs, 2):
                A, B = ents[i], ents[j]
                if A["last"] and B["last"] and (soundex(A["last"]) == soundex(B["last"]) or lev(A["last"], B["last"]) <= 2
                                                or A["last"] == B["first"] or B["last"] == A["first"]):
                    propose(i, j, "firm+name")
    # block 4: identical token multiset of full name (order-insensitive)
    b4 = defaultdict(list)
    for i, e in enumerate(ents):
        toks = tuple(sorted([e["first"], e["last"]])) if e["first"] else (e["last"],)
        b4[toks].append(i)
    for idxs in b4.values():
        for i, j in combinations(idxs, 2):
            propose(i, j, "multiset")
    # block 5: last-name ANAGRAM key (sorted letters) — catches transpositions the
    # soundex/prefix blocks miss (Becnel/Bencel, Kirn/Krin)
    b5 = defaultdict(list)
    for i, e in enumerate(ents):
        if e["last"]:
            b5["".join(sorted(e["last"]))].append(i)
    for idxs in b5.values():
        if len(idxs) <= 40:
            for i, j in combinations(idxs, 2):
                propose(i, j, "anagram")
    # block 6: exact first + last initial (distinctive firsts w/ badly mangled lasts);
    # common-first buckets blow the cap and are skipped — those need firm context anyway
    b6 = defaultdict(list)
    for i, e in enumerate(ents):
        if e["first"] and len(e["first"]) >= 4 and e["last"]:
            b6[(e["first"], e["last"][0])].append(i)
    for idxs in b6.values():
        if len(idxs) <= 25:
            for i, j in combinations(idxs, 2):
                propose(i, j, "first+li")
    return cands

def firm_candidates(ents):
    seen, cands = set(), []
    df = Counter(t for e in ents for t in e["alltoks"])
    buckets = defaultdict(list)
    for i, e in enumerate(ents):
        for t in e["alltoks"]:
            if t not in GENERIC_FIRM and t not in EXTRA_STOP and df[t] <= 40:
                buckets[t].append(i)
    for idxs in buckets.values():
        if len(idxs) > 80:
            continue
        for i, j in combinations(idxs, 2):
            p = (i, j) if i < j else (j, i)
            if p in seen:
                continue
            A, B = ents[p[0]], ents[p[1]]
            sa, sb = A["sig"], B["sig"]
            if not sa or not sb:
                continue
            shared = sa & sb
            if not shared:
                continue
            jac = len(shared) / len(sa | sb)
            subset = sa <= sb or sb <= sa
            if subset or jac >= 0.34 or len(shared) >= 2:
                seen.add(p)
                cands.append((p[0], p[1], f"tok:{','.join(sorted(shared))[:40]}"))
    return cands

# ---------------- auto rules (only where certain) ----------------
def att_auto(A, B):
    """'distinct' | 'same' | None(-> LLM)."""
    if A["suffixes"] and B["suffixes"] and A["suffixes"].isdisjoint(B["suffixes"]):
        return "distinct", "suffix conflict (Jr/Sr/III/IV)"
    return None, ""

# ---------------- LLM adjudication ----------------
SYS_ATT = """You judge whether two references to MDL (multidistrict litigation) leadership attorneys are the SAME real person.
Evidence per side: name variants, law firm(s), MDL numbers (rough era: 1000s=1990s-2000s, 2000s=2005-2015, 3000s=2020s), mention count.
Rules:
- Name commonness matters: a rare distinctive name (e.g. 'Cabraser') can be the same person even across different firms/eras; a common name (Smith, Davis, Kelly, Miller) needs positive evidence (shared firm lineage, same MDL, compatible middle initials).
- Shared firm is NOT sufficient: relatives and colleagues share firms (father/son, siblings). Different generational suffixes (Jr vs Sr vs III vs IV) = DIFFERENT people. Different full first names at the same firm (e.g. Hugh vs Palmer) = likely different people unless one is a documented nickname/middle-name usage.
- OCR/extraction noise is common: token swaps ('Berman Steve'), typos (Becnel/Bencel), truncations, initials. A swap/typo variant with the same firm+MDL context = same person.
- Attorneys DO move firms over a career; firm difference alone never proves distinct.
- unsure means you genuinely cannot tell; do not guess.
Return verdicts for every pair given."""

SYS_FIRM = """You judge whether two law-firm name clusters from MDL court records are the SAME firm (one lineage).
Evidence: name variants, MDL numbers (era), mention counts.
POLICY (important):
- Renames and continuations = SAME firm: e.g. 'Lerach Coughlin' -> 'Coughlin Stoia' -> 'Robbins Geller'; 'Pepper Hamilton' -> 'Troutman Pepper'; 'Cohen Milstein Hausfeld & Toll' -> 'Cohen Milstein Sellers & Toll'. Added/dropped partner surnames over time = same lineage.
- Branch offices / location or department tags = SAME firm ('Hausfeld LLP - DC' = 'Hausfeld LLP').
- Spin-offs are DIFFERENT firms: partners leaving to found a new firm ('Hausfeld LLP' != 'Cohen Milstein'; 'Kaiser Gornick' != 'Levin Simes'; 'Joseph Saveri Law Firm' != 'Saveri & Saveri').
- Different firms sharing common surnames are DIFFERENT ('Morgan & Morgan' != 'Morgan Law Firm Ltd'; two unrelated 'Smith' firms). Government offices of different states are DIFFERENT.
- Use your knowledge of the U.S. plaintiffs' bar. unsure means you cannot tell; do not guess.
Return verdicts for every pair given."""

def pair_key(kind, ka, kb):
    a, b = sorted([ka, kb])
    return f"{kind}|{a}|{b}"

def att_ent_key(e):
    return f"{e['first']}.{e['last']}.{'-'.join(sorted(e['fsig']))[:60]}.{e['n']}"

def firm_ent_key(e):
    return e["key"][:80]

def render_att(e):
    fs = "; ".join(f for f, _ in e["firms"].most_common(3)) or "(no firm recorded)"
    names = ", ".join(n for n, _ in e["fulls"].most_common(3))
    sfx = f" [suffix {'/'.join(e['suffixes'])}]" if e["suffixes"] else ""
    return (f"names: {names}{sfx} | firm(s): {fs} | MDLs: {', '.join(e['mdls'][:10]) or '?'} "
            f"| corpus: {'/'.join(e['corpora'])} | mentions: {e['n']}")

def render_firm(e):
    names = ", ".join(n for n, _ in e["names"].most_common(3))
    return f"names: {names} | MDLs: {', '.join(e['mdls'][:12]) or '?'} | mentions: {e['n']}"

def load_cache(path):
    out = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            if line.strip():
                try:
                    d = json.loads(line)
                    out[d["pair_key"]] = d
                except Exception:
                    pass
    return out

def adjudicate(pairs, sys_prompt, cache, cache_path, workers, batch=14):
    """pairs: list of dicts {pair_key, a_txt, b_txt}. Returns cache updated."""
    todo = [p for p in pairs if p["pair_key"] not in cache]
    if not todo:
        print("  nothing to adjudicate (all cached)")
        return cache, 0.0
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    from openai import OpenAI
    client = OpenAI(max_retries=5, timeout=180.0)
    schema = {"type": "object", "additionalProperties": False, "required": ["verdicts"],
              "properties": {"verdicts": {"type": "array", "items": {
                  "type": "object", "additionalProperties": False,
                  "required": ["id", "verdict", "confidence", "reason"],
                  "properties": {"id": {"type": "integer"},
                                 "verdict": {"type": "string", "enum": ["same", "distinct", "unsure"]},
                                 "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                                 "reason": {"type": "string"}}}}}}
    batches = [todo[i:i + batch] for i in range(0, len(todo), batch)]
    lock = threading.Lock()
    f = open(cache_path, "a", encoding="utf-8")
    tin = tout = 0

    def run_batch(bs):
        lines = []
        for k, p in enumerate(bs):
            lines.append(f"PAIR {k}:\n  A: {p['a_txt']}\n  B: {p['b_txt']}")
        user = "\n\n".join(lines) + f"\n\nReturn a verdict for each of the {len(bs)} pairs (id 0..{len(bs)-1})."
        r = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": "verdicts", "strict": True, "schema": schema}},
            max_completion_tokens=6000)
        d = json.loads(r.choices[0].message.content or "{}")
        got = {v["id"]: v for v in d.get("verdicts", [])}
        return bs, got, r.usage.prompt_tokens, r.usage.completion_tokens

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(run_batch, b) for b in batches]
        for fut in as_completed(futs):
            try:
                bs, got, pin, pout = fut.result()
            except Exception as e:  # noqa: BLE001
                print(f"  batch error: {type(e).__name__}: {str(e)[:100]}", file=sys.stderr)
                continue
            with lock:
                tin += pin; tout += pout
                for k, p in enumerate(bs):
                    v = got.get(k, {"verdict": "unsure", "confidence": "low", "reason": "no verdict returned"})
                    row = {"pair_key": p["pair_key"], "verdict": v["verdict"],
                           "confidence": v["confidence"], "reason": v["reason"][:300],
                           "a": p["a_txt"][:200], "b": p["b_txt"][:200], "source": "llm-batch"}
                    cache[p["pair_key"]] = row
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                done += len(bs)
            if done % 280 < batch:
                print(f"  [{done}/{len(todo)}] ~${tin/1e6*PRICE_IN + tout/1e6*PRICE_OUT:.2f}")
    f.close()
    cost = tin / 1e6 * PRICE_IN + tout / 1e6 * PRICE_OUT
    print(f"  adjudicated {done:,} pairs | in={tin:,} out={tout:,} | ~${cost:.2f}")
    return cache, cost

def web_pass(pairs, cache, workers):
    """gpt-5.5 + web_search on unsure pairs, one per call."""
    todo = [p for p in pairs if p["pair_key"] not in cache]
    if not todo:
        print("  web pass: nothing to do")
        return cache
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    from openai import OpenAI
    client = OpenAI(max_retries=4, timeout=120.0)
    lock = threading.Lock()
    f = open(WEBCACHE, "a", encoding="utf-8")

    def run_one(p):
        q = (f"{p['sys']}\n\nA: {p['a_txt']}\nB: {p['b_txt']}\n\n"
             'Research if needed, then answer with JSON only: {"verdict":"same|distinct|unsure",'
             '"confidence":"high|medium|low","reason":"..."}')
        try:
            r = client.responses.create(model=MODEL, tools=[{"type": "web_search"}], input=q)
            txt = getattr(r, "output_text", "") or ""
        except Exception:
            try:
                r = client.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": q}],
                                                   max_completion_tokens=2500)
                txt = r.choices[0].message.content or ""
            except Exception as e2:  # noqa: BLE001
                return p, {"verdict": "unsure", "confidence": "low", "reason": f"error {type(e2).__name__}"}
        m = re.search(r"\{.*\}", txt, re.S)
        try:
            d = json.loads(m.group(0)) if m else {}
        except Exception:
            d = {}
        return p, {"verdict": d.get("verdict", "unsure"), "confidence": d.get("confidence", "low"),
                   "reason": str(d.get("reason", ""))[:300]}

    n = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(run_one, p) for p in todo]
        for fut in as_completed(futs):
            p, v = fut.result()
            with lock:
                row = {"pair_key": p["pair_key"], **v, "a": p["a_txt"][:200], "b": p["b_txt"][:200],
                       "source": "llm-web"}
                cache[p["pair_key"]] = row
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                n += 1
                if n % 25 == 0:
                    print(f"  web [{n}/{len(todo)}]")
    f.close()
    print(f"  web pass done: {n}")
    return cache

# ---------------- Stage E: guarded clustering ----------------
def guarded_clusters(n_ents, edges, incompatible, direct_ok):
    """edges: list of (conf_rank, i, j). Merge greedily by confidence; veto a merge if it would
    place an incompatible pair (per `incompatible(i,j)`) in one cluster WITHOUT a direct same-edge."""
    parent = list(range(n_ents))
    members = {i: {i} for i in range(n_ents)}
    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    vetoed = []
    for _, i, j in sorted(edges):
        ri, rj = find(i), find(j)
        if ri == rj:
            continue
        bad = None
        for x in members[ri]:
            for y in members[rj]:
                if (x, y) != (i, j) and (y, x) != (i, j) and incompatible(x, y) and not direct_ok(x, y):
                    bad = (x, y); break
            if bad:
                break
        if bad:
            vetoed.append((i, j, bad))
            continue
        parent[rj] = ri
        members[ri] |= members[rj]
        del members[rj]
    clusters = defaultdict(list)
    for i in range(n_ents):
        clusters[find(i)].append(i)
    return clusters, vetoed

# ---------------- Gold scoring ----------------
def score_gold(ents, ent_cluster):
    """Pairwise P/R vs human gold canonical names over old-corpus identities."""
    # one identity per (sub-entity, gold-label) — do NOT collapse duplicates: the
    # within-cell multiplicity IS the signal the pairwise counts are built from
    id_pairs = []
    for i, e in enumerate(ents):
        for g in e["golds"]:
            id_pairs.append((g, ent_cluster[i]))
    from math import comb
    gold_ct, ours_ct, cell_ct = Counter(), Counter(), Counter()
    for g, c in id_pairs:
        gold_ct[g] += 1; ours_ct[c] += 1; cell_ct[(g, c)] += 1
    TP = sum(comb(v, 2) for v in cell_ct.values())
    P_pairs = sum(comb(v, 2) for v in ours_ct.values())
    G_pairs = sum(comb(v, 2) for v in gold_ct.values())
    prec = TP / P_pairs if P_pairs else 1.0
    rec = TP / G_pairs if G_pairs else 1.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return prec, rec, f1, len(gold_ct), len(ours_ct), len(id_pairs)

# ---------------- main ----------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", default="candidates",
                    choices=["candidates", "adjudicate", "web", "cluster", "all"])
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    print("loading mentions...")
    att_m, frm_m = load_mentions()
    att_ents = build_att_entities(att_m)
    frm_ents = build_firm_entities(frm_m)
    print(f"attorney mentions {len(att_m):,} -> sub-entities {len(att_ents):,} "
          f"(v1 had 3,459 name-keys; extra = un-fused collisions)")
    print(f"firm mentions {len(frm_m):,} -> entities {len(frm_ents):,}")

    ac = att_candidates(att_ents)
    fc = firm_candidates(frm_ents)
    # apply auto rules
    att_pairs, auto_rows = [], []
    for i, j, why in ac:
        verdict, reason = att_auto(att_ents[i], att_ents[j])
        pk = pair_key("att", att_ent_key(att_ents[i]), att_ent_key(att_ents[j]))
        if verdict:
            auto_rows.append({"pair_key": pk, "verdict": verdict, "confidence": "high",
                              "reason": reason, "source": "rule", "i": i, "j": j})
        else:
            att_pairs.append({"pair_key": pk, "i": i, "j": j, "why": why,
                              "a_txt": render_att(att_ents[i]), "b_txt": render_att(att_ents[j])})
    firm_pairs = [{"pair_key": pair_key("firm", firm_ent_key(frm_ents[i]), firm_ent_key(frm_ents[j])),
                   "i": i, "j": j, "why": why,
                   "a_txt": render_firm(frm_ents[i]), "b_txt": render_firm(frm_ents[j])}
                  for i, j, why in fc]
    cache = load_cache(CACHE)
    n_new = sum(1 for p in att_pairs + firm_pairs if p["pair_key"] not in cache)
    est = n_new / 14 * (2600 / 1e6 * PRICE_IN + 1800 / 1e6 * PRICE_OUT)
    print(f"\ncandidates: attorneys {len(att_pairs):,} (+{len(auto_rows)} auto) | firms {len(firm_pairs):,}")
    print(f"not yet cached: {n_new:,} | est adjudication cost ~${est:.0f} | model {MODEL}")
    json.dump([{k: p[k] for k in ("pair_key", "i", "j", "why")} for p in att_pairs],
              open(CAND_ATT, "w"), indent=0)
    json.dump([{k: p[k] for k in ("pair_key", "i", "j", "why")} for p in firm_pairs],
              open(CAND_FIRM, "w"), indent=0)
    if args.stage == "candidates":
        return 0

    if args.stage in ("adjudicate", "all"):
        print("\nadjudicating attorneys...")
        cache, c1 = adjudicate(att_pairs, SYS_ATT, cache, CACHE, args.workers)
        print("adjudicating firms...")
        cache, c2 = adjudicate(firm_pairs, SYS_FIRM, cache, CACHE, args.workers)
        print(f"total adjudication cost ~${c1 + c2:.2f}")

    web = load_cache(WEBCACHE)
    if args.stage in ("web", "all"):
        unsure = [dict(p, sys=SYS_ATT) for p in att_pairs
                  if cache.get(p["pair_key"], {}).get("verdict") == "unsure"] + \
                 [dict(p, sys=SYS_FIRM) for p in firm_pairs
                  if cache.get(p["pair_key"], {}).get("verdict") == "unsure"]
        print(f"\nweb pass on {len(unsure)} unsure pairs...")
        web = web_pass(unsure, web, args.workers)

    if args.stage not in ("cluster", "all"):
        return 0

    # ---------- final verdict per pair: web overrides unsure; unsure -> distinct ----------
    def final_verdict(pk):
        v = web.get(pk) or cache.get(pk)
        if not v:
            return "distinct", "low", "unadjudicated"
        return v["verdict"], v["confidence"], v.get("source", "llm")

    CONF_RANK = {"high": 0, "medium": 1, "low": 2}
    # attorneys
    att_edges, att_direct = [], set()
    rows_log = []
    for p in att_pairs:
        v, conf, src = final_verdict(p["pair_key"])
        rows_log.append({"kind": "attorney", "pair_key": p["pair_key"], "verdict": v, "confidence": conf,
                         "source": src, "a": p["a_txt"][:160], "b": p["b_txt"][:160]})
        if v == "same" and conf in ("high", "medium"):
            att_edges.append((CONF_RANK[conf], p["i"], p["j"]))
            att_direct.add((p["i"], p["j"])); att_direct.add((p["j"], p["i"]))
    for r in auto_rows:
        rows_log.append({"kind": "attorney", "pair_key": r["pair_key"], "verdict": r["verdict"],
                         "confidence": "high", "source": "rule", "a": "", "b": ""})

    def att_incompatible(x, y):
        A, B = att_ents[x], att_ents[y]
        if A["suffixes"] and B["suffixes"] and A["suffixes"].isdisjoint(B["suffixes"]):
            return True
        # swap-aware: a swapped sub-entity ("Berman Steve") carries the SURNAME as its given
        # token — treat given∩other.last as compatibility, else the guard vetoes its own reunion
        if B["last"] in A["given"] or A["last"] in B["given"]:
            return False
        return not names_compatible(A["given"], B["given"])

    att_clusters, att_veto = guarded_clusters(len(att_ents), att_edges, att_incompatible,
                                              lambda x, y: (x, y) in att_direct)
    # firms
    frm_edges, frm_direct = [], set()
    for p in firm_pairs:
        v, conf, src = final_verdict(p["pair_key"])
        rows_log.append({"kind": "firm", "pair_key": p["pair_key"], "verdict": v, "confidence": conf,
                         "source": src, "a": p["a_txt"][:160], "b": p["b_txt"][:160]})
        if v == "same" and conf in ("high", "medium"):
            frm_edges.append((CONF_RANK[conf], p["i"], p["j"]))
            frm_direct.add((p["i"], p["j"])); frm_direct.add((p["j"], p["i"]))

    def frm_incompatible(x, y):
        return not (frm_ents[x]["sig"] & frm_ents[y]["sig"])

    frm_clusters, frm_veto = guarded_clusters(len(frm_ents), frm_edges, frm_incompatible,
                                              lambda x, y: (x, y) in frm_direct)

    with open(DECISIONS, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["kind", "pair_key", "verdict", "confidence", "source", "a", "b"])
        w.writeheader(); w.writerows(rows_log)

    # ---------- gold gate ----------
    ent_cluster = {}
    for root, idxs in att_clusters.items():
        for i in idxs:
            ent_cluster[i] = root
    prec, rec, f1, n_gold, n_ours, n_ids = score_gold(att_ents, ent_cluster)
    print(f"\nGOLD GATE (old corpus, {n_ids} identities): precision {prec:.3f} | recall {rec:.3f} | F1 {f1:.3f}")
    print(f"  gold clusters {n_gold} vs ours {n_ours} | baseline v1: P=0.904 R=0.587 F1=0.712")
    print(f"  veto log: attorneys {len(att_veto)} | firms {len(frm_veto)} (blob guard)")
    gate = prec >= 0.95 and rec >= 0.85

    # ---------- write v2 rosters ----------
    def write_att():
        rows, amap = [], []
        for cid, (root, idxs) in enumerate(
                sorted(att_clusters.items(), key=lambda kv: -sum(att_ents[i]["n"] for i in kv[1])), 1):
            aid = f"A{cid:04d}"
            names, firms, mdls, roles, corp, n = Counter(), Counter(), set(), set(), set(), 0
            for i in idxs:
                e = att_ents[i]
                names.update(e["fulls"]); firms.update(e["firms"])
                mdls |= set(e["mdls"]); roles |= set(e["roles"]); corp |= set(e["corpora"]); n += e["n"]
                for m in e["mdls"]:            # (first,last,mdl) -> Attorney_ID  (sub-entities partition mdls per name-key)
                    amap.append({"first": e["first"], "last": e["last"], "mdl": m, "Attorney_ID": aid})
            canon = max(names, key=lambda nm: (names[nm], len(nm))) if names else ""
            akas = [nm for nm, _ in names.most_common() if nm != canon][:3]
            rows.append({"Attorney_ID": aid, "Canonical_Name": canon,
                         "AKA_1": akas[0] if len(akas) > 0 else "", "AKA_2": akas[1] if len(akas) > 1 else "",
                         "AKA_3": akas[2] if len(akas) > 2 else "", "Variants_Merged": len(idxs),
                         "Firms": "; ".join(f for f, _ in firms.most_common(4)),
                         "N_MDLs": len(mdls), "N_Mentions": n,
                         "MDLs": ", ".join(sorted(mdls, key=lambda x: (len(x), x))),
                         "Roles": "; ".join(sorted(roles)), "Corpora": "/".join(sorted(corp)),
                         "Confidence": "merged" if len(idxs) > 1 else "high"})
        with open(OUT_ATT, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
        with open(os.path.join(ROOT, "dedup_v2_attorney_map.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["first", "last", "mdl", "Attorney_ID"])
            w.writeheader(); w.writerows(amap)
        return len(rows)

    def write_firm():
        rows, fmap = [], []
        for cid, (root, idxs) in enumerate(
                sorted(frm_clusters.items(), key=lambda kv: -sum(frm_ents[i]["n"] for i in kv[1])), 1):
            fid = f"F{cid:04d}"
            names, mdls, n = Counter(), set(), 0
            for i in idxs:
                e = frm_ents[i]
                names.update(e["names"]); mdls |= set(e["mdls"]); n += e["n"]
                fmap.append({"firm_key": e["key"], "Firm_ID": fid})   # sorted-token key -> Firm_ID
            canon = max(names, key=lambda nm: (names[nm], len(nm)))
            akas = [nm for nm, _ in names.most_common() if nm != canon][:3]
            rows.append({"Firm_ID": fid, "Canonical_Firm": canon,
                         "AKA_1": akas[0] if len(akas) > 0 else "", "AKA_2": akas[1] if len(akas) > 1 else "",
                         "AKA_3": akas[2] if len(akas) > 2 else "", "Variants_Merged": len(idxs),
                         "N_MDLs": len(mdls), "N_Mentions": n,
                         "MDLs": ", ".join(sorted(mdls, key=lambda x: (len(x), x)))})
        with open(OUT_FIRM, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
        with open(os.path.join(ROOT, "dedup_v2_firm_map.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["firm_key", "Firm_ID"])
            w.writeheader(); w.writerows(fmap)
        return len(rows)

    na, nf = write_att(), write_firm()
    print(f"\nwrote {os.path.basename(OUT_ATT)} ({na:,} canonical attorneys), "
          f"{os.path.basename(OUT_FIRM)} ({nf:,} canonical firms), decisions -> {os.path.basename(DECISIONS)}")
    print(f"GATE {'PASSED — safe to adopt' if gate else 'NOT PASSED — do not adopt yet; inspect decisions log'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
