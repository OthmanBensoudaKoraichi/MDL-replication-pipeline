"""Attorney + firm entity resolution (deterministic-first; LLM only on the ambiguous residual).

Reads the RAW appointees from order_extractions.jsonl (which carry the per-MDL / per-firm context the
collapsed Attorneys tab has lost) and produces a canonical roster: one row per real person/firm, with
Canonical_Name + AKAs, the firms and MDLs they appear in, and a confidence flag.

Method (see METHOD.md):
  1. Aggregate raw mentions into exact-normalized entities (lowercase first-token + last name).
  2. BLOCK by last-name Soundex and last[:4] -> only plausible pairs are compared (not N^2).
  3. SCORE each pair: last names must match (exact / Soundex / edit<=1); first names relate as
     exact | nickname | given-token-subset (W. Mark <-> Mark) | initial | edit<=1.
       - exact/nick/subset  -> STRONG  : merge regardless of context.
       - initial/edit1       -> CONTEXT : merge ONLY if they share a firm or an MDL (guards the
                                          common-name over-merge trap, e.g. two different J. Millers).
       - otherwise            -> WEAK    : not auto-merged; written to the review file (LLM/human).
  4. Union-find the STRONG + CONTEXT merges -> clusters. Canonical = most frequent full name.
  5. (--llm) adjudicate the WEAK pairs with gpt-5.5, with firm/MDL context; log every decision.

Firms get the same treatment with token-subset / >=50%-overlap / single-token-edit matching.

Usage:
    python dedup_attorneys.py                 # deterministic only (free) -- the prototype
    python dedup_attorneys.py --llm            # also adjudicate WEAK pairs with gpt-5.5
    python dedup_attorneys.py --jsonl order_extractions.jsonl
Outputs (at ROOT): canonical_attorneys.csv, canonical_firms.csv, attorney_merge_audit.csv,
                   attorney_review_candidates.csv
"""
import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict, Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------- common nickname <-> formal map (bidirectional; common US legal first names) ----------
_NICK_GROUPS = [
    ("william", "bill", "billy", "will", "willy"), ("robert", "bob", "bobby", "rob", "robbie"),
    ("richard", "rich", "rick", "ricky", "dick"), ("james", "jim", "jimmy", "jamie"),
    ("joseph", "joe", "joey"), ("michael", "mike", "mikey"), ("christopher", "chris"),
    ("thomas", "tom", "tommy"), ("anthony", "tony"), ("david", "dave", "davey"),
    ("steven", "stephen", "steve"), ("edward", "ed", "eddie", "ted", "ned"),
    ("benjamin", "ben", "benji"), ("samuel", "sam", "sammy"), ("andrew", "andy", "drew"),
    ("matthew", "matt"), ("nicholas", "nick", "nicky"), ("gregory", "greg"),
    ("jeffrey", "geoffrey", "jeff"), ("kenneth", "ken", "kenny"), ("lawrence", "larry"),
    ("frederick", "fred", "freddy"), ("charles", "charlie", "chuck"), ("henry", "hank", "harry"),
    ("john", "jack", "johnny", "jon"), ("patrick", "pat"), ("ronald", "ron", "ronnie"),
    ("donald", "don", "donnie"), ("douglas", "doug"), ("philip", "phillip", "phil"),
    ("raymond", "ray"), ("eugene", "gene"), ("arthur", "art"), ("albert", "al"),
    ("daniel", "dan", "danny"), ("peter", "pete"), ("timothy", "tim"), ("ronald", "ron"),
    ("elizabeth", "liz", "beth", "betsy", "lisa", "eliza"), ("katherine", "catherine", "kate", "kathy", "cathy", "katie"),
    ("margaret", "meg", "peggy", "maggie"), ("susan", "sue", "susie"), ("jennifer", "jen", "jenny"),
    ("rebecca", "becky"), ("victoria", "vicky", "tori"), ("deborah", "debra", "debbie", "deb"),
    ("patricia", "pat", "patty", "trish"), ("barbara", "barb", "babs"), ("cynthia", "cindy"),
    ("theodore", "ted", "theo"), ("alexander", "alex", "al"), ("vincent", "vince"),
    ("francis", "frank", "fran"), ("frances", "fran", "francie"), ("gerald", "gerry", "jerry"),
]
NICK = defaultdict(set)
for grp in _NICK_GROUPS:
    for a in grp:
        NICK[a] |= set(grp) - {a}


def nick_equiv(a, b):
    return bool(a) and bool(b) and (b in NICK.get(a, ()) or a in NICK.get(b, ()))


def soundex(s):
    s = re.sub(r"[^a-z]", "", (s or "").lower())
    if not s:
        return ""
    codes = {**dict.fromkeys("bfpv", "1"), **dict.fromkeys("cgjkqsxz", "2"),
             **dict.fromkeys("dt", "3"), "l": "4", **dict.fromkeys("mn", "5"), "r": "6"}
    out = s[0].upper()
    prev = codes.get(s[0], "")
    for ch in s[1:]:
        c = codes.get(ch, "")
        if c and c != prev:
            out += c
        prev = "" if ch in "aeiouy" else (prev if ch in "hw" else c)
    return (out + "000")[:4]


def lev(a, b):
    if a == b:
        return 0
    if not a or not b:
        return len(a) + len(b)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def norm(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


def given_tokens(full, last):
    """Normalized given-name tokens of a full name, minus the surname token."""
    toks = [norm(t) for t in re.findall(r"[A-Za-z]+", full or "")]
    ln = norm(last)
    return {t for t in toks if t and t != ln}


# ---------- load raw mentions ----------
def load_mentions(jsonl):
    """Returns (individuals, firms). individuals: list of dicts {first,last,full,firm,mdl,roles}."""
    inds, firms = [], []
    for line in open(jsonl, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        mdl = str(rec.get("MDL_No") or (re.match(r"^(\d+)", rec.get("Source_File", "")) or [None, ""])[0] or "")
        mdl = re.sub(r"^0+(\d)", r"\1", mdl)   # normalize zero-padded MDL ids (02000 -> 2000) so they don't split
        for a in rec.get("Appointments") or []:
            fn = (a.get("first_name") or "").strip()
            ln = (a.get("last_name") or "").strip()
            firm = (a.get("firm") or "").strip()
            roles = a.get("appointment_types") or []
            if a.get("appointee_type") == "Firm" or not (fn or ln):
                if firm:
                    firms.append({"firm": firm, "mdl": mdl, "roles": roles})
            else:
                inds.append({"first": fn, "last": ln, "full": (a.get("full_name") or f"{fn} {ln}").strip(),
                             "firm": firm, "mdl": mdl, "roles": roles})
                if firm:
                    firms.append({"firm": firm, "mdl": mdl, "roles": roles})
    return inds, firms


# ---------- aggregate to exact-normalized entities ----------
def aggregate_individuals(inds):
    ent = {}
    for m in inds:
        key = (norm(m["first"]).split() and norm(m["first"]) or norm(m["first"]), norm(m["last"]))
        ftok = norm(m["first"])
        key = (ftok, norm(m["last"]))
        e = ent.setdefault(key, {"first_tok": ftok, "last": norm(m["last"]), "fulls": Counter(),
                                 "firms": set(), "firms_raw": Counter(), "mdls": set(), "roles": set(),
                                 "given": set(), "n": 0})
        e["fulls"][m["full"]] += 1
        e["given"] |= given_tokens(m["full"], m["last"])
        if m["firm"]:
            e["firms"].add(norm(m["firm"]))
            e["firms_raw"][m["firm"]] += 1
        if m["mdl"]:
            e["mdls"].add(m["mdl"])
        e["roles"] |= set(m["roles"])
        e["n"] += 1
    return list(ent.values())


# ---------- pairwise scoring ----------
def last_match(a, b):
    if a == b and a:
        return True
    if a and b and soundex(a) == soundex(b):
        return True
    return min(len(a), len(b)) >= 5 and lev(a, b) <= 1


def first_relation(A, B):
    a, b = A["first_tok"], B["first_tok"]
    ga, gb = A["given"], B["given"]
    if a and a == b:
        return "exact"
    if nick_equiv(a, b):
        return "nick"
    if ga and gb and (ga <= gb or gb <= ga) and (ga & gb):
        return "subset"                       # "W. Mark" <-> "Mark", added middle name, etc.
    if a and b and (len(a) == 1 or len(b) == 1) and a[0] == b[0]:
        return "initial"
    if a and b and a[0] == b[0] and lev(a, b) <= 1:
        return "edit1"
    return "none"


def classify_pair(A, B):
    """Return ('strong'|'context'|'weak'|None, reason). STRONG (auto-merge) requires an EXACT surname
    plus a compatible first name. A surname that matches only PHONETICALLY (Soundex) or by edit<=1 is
    never strong -- it needs a shared firm/MDL to merge, else it drops to WEAK (review). This guards
    the over-merge trap: Hellums vs Hellmich (same Soundex), McCarley vs McCauley (edit-1)."""
    la, lb = A["last"], B["last"]
    exact_last = bool(la) and la == lb
    fuzzy_last = (not exact_last) and last_match(la, lb)
    swap = (not exact_last and not fuzzy_last) and last_match(A["first_tok"], lb) and last_match(B["first_tok"], la)
    if not (exact_last or fuzzy_last or swap):
        return None, ""
    shared = bool(A["firms"] & B["firms"]) or bool(A["mdls"] & B["mdls"])
    ctx = "shared firm/MDL" if shared else "no shared firm/MDL"
    if swap:
        return ("context" if shared else "weak"), f"first/last swapped ({ctx})"
    rel = first_relation(A, B)
    if rel == "none":
        return None, ""
    if exact_last:
        if rel in ("exact", "nick"):
            return "strong", f"exact surname + first {rel}"
        # subset ("W. Mark" vs "Mark"), initial, or edit1: require a shared firm/MDL. A bare
        # given-token-subset over-merges without context (two unrelated "Robert <Last>" collapse).
        return ("context" if shared else "weak"), f"exact surname + first {rel} ({ctx})"
    return ("context" if shared else "weak"), f"fuzzy surname + first {rel} ({ctx})"


# ---------- union-find ----------
class UF:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def block_pairs(ents, key_fns):
    """Yield candidate index pairs that share any blocking key (dedup'd)."""
    seen = set()
    for kf in key_fns:
        buckets = defaultdict(list)
        for i, e in enumerate(ents):
            k = kf(e)
            if k:
                buckets[k].append(i)
        for idxs in buckets.values():
            for x in range(len(idxs)):
                for y in range(x + 1, len(idxs)):
                    pair = (idxs[x], idxs[y]) if idxs[x] < idxs[y] else (idxs[y], idxs[x])
                    if pair not in seen:
                        seen.add(pair)
                        yield pair


def resolve_individuals(ents):
    uf = UF(len(ents))
    audit, weak = [], []
    for i, j in block_pairs(ents, [lambda e: soundex(e["last"]), lambda e: e["last"][:4]]):
        level, reason = classify_pair(ents[i], ents[j])
        if level in ("strong", "context"):
            uf.union(i, j)
            audit.append((i, j, level, reason))
        elif level == "weak":
            weak.append((i, j, reason))
    clusters = defaultdict(list)
    for i in range(len(ents)):
        clusters[uf.find(i)].append(i)
    weak = [(i, j, r) for (i, j, r) in weak if uf.find(i) != uf.find(j)]   # drop already-merged pairs
    return clusters, audit, weak, uf


def display_name(ent):
    return ent["fulls"].most_common(1)[0][0] if ent["fulls"] else ""


def build_individual_rows(ents, clusters, audit):
    by_root_levels = defaultdict(set)
    # (audit indices map to roots via uf later; here just track if any 'context' merge in a cluster)
    rows, cid = [], 0
    for root, idxs in sorted(clusters.items(), key=lambda kv: -len(kv[1])):
        cid += 1
        names = Counter()
        firms_raw, mdls, roles, n = Counter(), set(), set(), 0
        for i in idxs:
            e = ents[i]
            names.update(e["fulls"])
            firms_raw.update(e["firms_raw"])
            mdls |= e["mdls"]
            roles |= e["roles"]
            n += e["n"]
        canon = names.most_common(1)[0][0]
        akas = [nm for nm, _ in names.most_common() if nm != canon][:3]
        conf = "high" if len(idxs) == 1 else "merged"
        rows.append({"Attorney_ID": f"A{cid:04d}", "Canonical_Name": canon,
                     "AKA_1": akas[0] if len(akas) > 0 else "", "AKA_2": akas[1] if len(akas) > 1 else "",
                     "AKA_3": akas[2] if len(akas) > 2 else "",
                     "Variants_Merged": len(idxs), "Firms": "; ".join(f for f, _ in firms_raw.most_common(4)),
                     "N_MDLs": len(mdls), "N_Mentions": n, "MDLs": ", ".join(sorted(mdls)),
                     "Roles": "; ".join(sorted(roles)), "Confidence": conf,
                     "Gender": "", "Birth_Year": "", "Undergrad_School": "", "Undergrad_Grad_Year": "",
                     "Law_School_Name": "", "Law_Grad_Year": "", "Bar_States": "", "Sources": "", "Notes": ""})
    return rows


# ---------- firms ----------
FIRM_STOP = {"and", "the", "of", "at", "law", "offices", "office", "group", "firm", "llp", "llc",
             "pc", "pa", "lp", "ltd", "co", "pllc", "apc", "associates", "attorneys", "a"}


def firm_tokens(s):
    # len>1 drops single-letter tokens produced by dotted suffixes ("P.C."->p,c ; "P.L.L.C."->p,l,c),
    # which otherwise made every "P.C." firm share {p,c} and merge into one bogus cluster.
    return [t for t in re.findall(r"[a-z]+", (s or "").lower()) if t not in FIRM_STOP and len(t) > 1]


def firm_match(a, b):
    ta, tb = set(firm_tokens(a)), set(firm_tokens(b))
    if not ta or not tb:
        return False
    shared = ta & tb
    if len(ta) == 1 and len(tb) == 1:                    # single-token firms: identical or 1-edit spelling
        return bool(shared) or lev(next(iter(ta)), next(iter(tb))) <= 1
    # multi-token firms must share >=2 significant tokens -- a single shared surname token is NOT enough
    # (it over-merges distinct firms that happen to share one name, e.g. "Smith & Jones" / "Smith & Brown").
    if len(shared) >= 2 and (ta <= tb or tb <= ta):
        return True
    if len(shared) >= 2 and len(shared) / len(ta | tb) >= 0.5:
        return True
    return False


def resolve_firms(firm_mentions, return_keymap=False):
    agg = {}
    for m in firm_mentions:
        k = " ".join(sorted(firm_tokens(m["firm"])))
        if not k:
            continue
        e = agg.setdefault(k, {"names": Counter(), "mdls": set(), "n": 0})
        e["names"][m["firm"]] += 1
        if m["mdl"]:
            e["mdls"].add(m["mdl"])
        e["n"] += 1
    agg_keys = list(agg.keys())       # token-key per ent index (for the optional keymap)
    ents = list(agg.values())
    uf = UF(len(ents))
    names = [e["names"].most_common(1)[0][0] for e in ents]
    # block on the 1st AND 2nd SORTED significant token (order-insensitive, so "Lieff Cabraser" and
    # "Cabraser Lieff" co-block); firm_match then requires >=2 shared tokens to actually merge.
    def fsorted(e):
        return sorted(firm_tokens(e["names"].most_common(1)[0][0]))
    for i, j in block_pairs(ents, [lambda e: (fsorted(e) + [""])[0], lambda e: (fsorted(e) + ["", ""])[1]]):
        if firm_match(names[i], names[j]):
            uf.union(i, j)
    clusters = defaultdict(list)
    for i in range(len(ents)):
        clusters[uf.find(i)].append(i)
    rows, cid, keymap = [], 0, {}
    for root, idxs in sorted(clusters.items(), key=lambda kv: -len(kv[1])):
        cid += 1
        fid = f"F{cid:04d}"
        nm, mdls, n = Counter(), set(), 0
        for i in idxs:
            nm.update(ents[i]["names"]); mdls |= ents[i]["mdls"]; n += ents[i]["n"]
            keymap[agg_keys[i]] = fid          # token-key -> Firm_ID (for relational linkage)
        canon = nm.most_common(1)[0][0]
        akas = [x for x, _ in nm.most_common() if x != canon][:3]
        rows.append({"Firm_ID": fid, "Canonical_Firm": canon,
                     "AKA_1": akas[0] if len(akas) > 0 else "", "AKA_2": akas[1] if len(akas) > 1 else "",
                     "AKA_3": akas[2] if len(akas) > 2 else "", "Variants_Merged": len(idxs),
                     "N_MDLs": len(mdls), "N_Mentions": n,
                     "MDLs": ", ".join(sorted(mdls, key=lambda x: (len(x), x)))})
    return (rows, keymap) if return_keymap else rows


def write_csv(path, rows, cols):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--jsonl", default="order_extractions.jsonl")
    ap.add_argument("--llm", action="store_true", help="adjudicate WEAK pairs with gpt-5.5 (default off)")
    ap.add_argument("--out-suffix", default="",
                    help="suffix for output filenames, e.g. '_unified' -> canonical_attorneys_unified.csv "
                         "(default: overwrite the standard canonical_*.csv)")
    ap.add_argument("--firms-only", action="store_true",
                    help="regenerate ONLY canonical_firms{suffix}.csv (deterministic, no LLM); leaves the "
                         "attorney roster untouched")
    args = ap.parse_args()
    jsonl = args.jsonl if os.path.isabs(args.jsonl) else os.path.join(ROOT, args.jsonl)
    sfx = args.out_suffix

    inds, firm_mentions = load_mentions(jsonl)

    if args.firms_only:
        firm_rows = resolve_firms(firm_mentions)
        write_csv(os.path.join(ROOT, f"canonical_firms{sfx}.csv"), firm_rows,
                  ["Firm_ID", "Canonical_Firm", "AKA_1", "AKA_2", "AKA_3", "Variants_Merged",
                   "N_MDLs", "N_Mentions", "MDLs"])
        print(f"firms-only: {len(firm_mentions):,} mentions -> {len(firm_rows):,} canonical "
              f"-> canonical_firms{sfx}.csv")
        return
    ents = aggregate_individuals(inds)
    clusters, audit, weak, uf = resolve_individuals(ents)

    if args.llm and weak:
        weak = adjudicate_weak(ents, weak, uf, clusters, out_suffix=sfx)   # may union more; recompute clusters
        clusters = defaultdict(list)
        for i in range(len(ents)):
            clusters[uf.find(i)].append(i)

    rows = build_individual_rows(ents, clusters, audit)
    firm_rows = resolve_firms(firm_mentions)

    write_csv(os.path.join(ROOT, f"canonical_attorneys{sfx}.csv"), rows,
              ["Attorney_ID", "Canonical_Name", "AKA_1", "AKA_2", "AKA_3", "Variants_Merged", "Firms",
               "N_MDLs", "N_Mentions", "MDLs", "Roles", "Confidence", "Gender", "Birth_Year",
               "Undergrad_School", "Undergrad_Grad_Year", "Law_School_Name", "Law_Grad_Year",
               "Bar_States", "Sources", "Notes"])
    write_csv(os.path.join(ROOT, f"canonical_firms{sfx}.csv"), firm_rows,
              ["Firm_ID", "Canonical_Firm", "AKA_1", "AKA_2", "AKA_3", "Variants_Merged", "N_MDLs", "N_Mentions", "MDLs"])
    write_csv(os.path.join(ROOT, f"attorney_merge_audit{sfx}.csv"),
              [{"Name_A": display_name(ents[i]), "Name_B": display_name(ents[j]),
                "Level": lv, "Reason": rs} for i, j, lv, rs in audit],
              ["Name_A", "Name_B", "Level", "Reason"])
    write_csv(os.path.join(ROOT, f"attorney_review_candidates{sfx}.csv"),
              [{"Name_A": display_name(ents[i]), "Firms_A": "; ".join(list(ents[i]["firms_raw"])[:2]),
                "Name_B": display_name(ents[j]), "Firms_B": "; ".join(list(ents[j]["firms_raw"])[:2]),
                "Reason": rs} for i, j, rs in weak],
              ["Name_A", "Firms_A", "Name_B", "Firms_B", "Reason"])

    n_merged = sum(1 for r in rows if r["Variants_Merged"] > 1)
    print(f"individuals: {len(inds):,} raw mentions -> {len(ents):,} exact-normalized -> {len(rows):,} canonical")
    print(f"  fuzzy merges applied (audit): {len(audit):,}  | clusters that merged >=2 variants: {n_merged:,}")
    print(f"  WEAK pairs flagged for review/LLM: {len(weak):,}{'  (LLM applied)' if args.llm else '  (run --llm to adjudicate)'}")
    print(f"firms: {len(firm_mentions):,} mentions -> {len(firm_rows):,} canonical")
    print("wrote canonical_attorneys.csv, canonical_firms.csv, attorney_merge_audit.csv, attorney_review_candidates.csv")
    # show a sample of the biggest merges so precision is eyeball-able
    big = sorted([r for r in rows if r["Variants_Merged"] > 1], key=lambda r: -r["Variants_Merged"])[:12]
    if big:
        print("\nsample merges (canonical <- AKAs):")
        for r in big:
            akas = ", ".join(a for a in (r["AKA_1"], r["AKA_2"], r["AKA_3"]) if a)
            print(f"  {r['Canonical_Name'][:32]:32} <- {akas[:60]}  [{r['N_MDLs']} MDLs]")
    return 0


def adjudicate_weak(ents, weak, uf, clusters, out_suffix=""):
    """Adjudicate the ambiguous (WEAK) pairs with gpt-5.5: a system role stating the same-person
    standard, structured output with an explicit CONFIDENCE, an abstain (merge only on high/medium
    confidence -- low confidence stays distinct), and a PERSISTED decision log so every LLM merge is
    auditable (attorney_llm_adjudications.csv)."""
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))
    from openai import OpenAI
    client = OpenAI(max_retries=5)
    SYS_J = ("You decide whether two mentions of an MDL leadership attorney are the SAME real person. "
             "Two different attorneys can share a surname; merge ONLY when the evidence -- a shared firm, "
             "a shared MDL, or a clearly compatible name (nickname/middle-initial) -- supports it. When "
             "in doubt, do NOT merge and report low confidence.")
    SCHEMA_J = {"type": "object", "additionalProperties": False, "required": ["same", "confidence"],
                "properties": {"same": {"type": "boolean"},
                               "confidence": {"type": "string", "enum": ["high", "medium", "low"]}}}
    log, kept = [], []
    for i, j, reason in weak:
        a, b = ents[i], ents[j]
        user = (f"A: name='{display_name(a)}', firms={list(a['firms_raw'])[:3]}, MDLs={sorted(a['mdls'])[:8]}\n"
                f"B: name='{display_name(b)}', firms={list(b['firms_raw'])[:3]}, MDLs={sorted(b['mdls'])[:8]}\n"
                f"Same real person? Return JSON.")
        same, conf = False, "low"
        try:
            r = client.chat.completions.create(
                model="gpt-5.5",
                messages=[{"role": "system", "content": SYS_J}, {"role": "user", "content": user}],
                response_format={"type": "json_schema",
                                 "json_schema": {"name": "same_person", "strict": True, "schema": SCHEMA_J}},
                max_completion_tokens=2000)
            d = json.loads(r.choices[0].message.content or "{}")
            same, conf = bool(d.get("same")), d.get("confidence", "low")
        except Exception as e:  # noqa: BLE001
            print(f"  llm error on {display_name(a)} / {display_name(b)}: {type(e).__name__}")
        merged = same and conf in ("high", "medium")      # abstain on low confidence
        log.append({"Name_A": display_name(a), "Name_B": display_name(b),
                    "same": same, "confidence": conf, "merged": merged})
        if merged:
            uf.union(i, j)
        else:
            kept.append((i, j, reason + f" | LLM: distinct (conf {conf})"))
    if log:
        write_csv(os.path.join(ROOT, f"attorney_llm_adjudications{out_suffix}.csv"), log,
                  ["Name_A", "Name_B", "same", "confidence", "merged"])
    return kept


if __name__ == "__main__":
    sys.exit(main())
