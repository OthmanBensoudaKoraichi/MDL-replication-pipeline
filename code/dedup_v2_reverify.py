#!/usr/bin/env python3
"""Targeted web re-verification of the three residual dedup-v2 error slices:
  (i)   fuzzy-surname SAME verdicts  (edit-distance lasts; kills Coben/Cohan-type FPs)
  (ii)  same-firm DISTINCT/UNSURE verdicts on similar names (recovers Zonies/Mathews-type FNs)
  (iii) swap-shaped DISTINCT/UNSURE verdicts (recovers Berman Steve-type FNs)
Web verdicts land in dedup_v2_web_adjudications.jsonl, which final_verdict() prefers over the
batch cache — then re-run `dedup_v2.py --stage cluster`."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "code"))
import dedup_v2 as V

att_m, _ = V.load_mentions()
ents = V.build_att_entities(att_m)
cands = V.att_candidates(ents)
cache = V.load_cache(V.CACHE)
web = V.load_cache(V.WEBCACHE)

slices = []
for i, j, why in cands:
    A, B = ents[i], ents[j]
    pk = V.pair_key("att", V.att_ent_key(A), V.att_ent_key(B))
    v = (web.get(pk) or cache.get(pk) or {})
    verdict = v.get("verdict", "")
    fuzzy_last = A["last"] != B["last"]
    same_firm = bool(A["fsig"] & B["fsig"])
    swapish = (A["last"] in B["given"]) or (B["last"] in A["given"]) or \
              (A["first"] and B["first"] and A["first"] == B["last"] and B["first"] == A["last"])
    tag = None
    if verdict == "same" and fuzzy_last and not swapish:
        tag = "verify-fuzzy-same"          # slice (i)
    elif verdict in ("distinct", "unsure") and same_firm:
        tag = "recheck-samefirm-split"     # slice (ii)
    elif verdict in ("distinct", "unsure") and swapish:
        tag = "recheck-swap-split"         # slice (iii)
    if tag and pk not in web:              # don't redo pairs the web pass already judged
        slices.append({"pair_key": pk, "a_txt": V.render_att(A), "b_txt": V.render_att(B),
                       "sys": V.SYS_ATT + "\n\nEXTRA INSTRUCTION for this pair "
                       f"[{tag}]: use web search on the attorney names + firms to verify. "
                       "For fuzzy-surname pairs, actively check whether these are TWO DIFFERENT "
                       "attorneys who happen to have similar names (search both spellings' bios/bar "
                       "records). For same-firm splits, check the firm's roster: OCR-garbled variants "
                       "of one real attorney should be SAME; distinct colleagues/relatives are DISTINCT."})

from collections import Counter
print("re-verify slices:", Counter(s["sys"].split("[")[1].split("]")[0] for s in slices))
print(f"total pairs to web-verify: {len(slices)}")
if "--dry" in sys.argv:
    sys.exit(0)
V.web_pass(slices, web, workers=10)
print("done — now run: dedup_v2.py --stage cluster")
