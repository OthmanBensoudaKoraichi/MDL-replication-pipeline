#!/usr/bin/env python3
"""
Generate PROMPTS.md: every LLM prompt in the pipeline, extracted VERBATIM from the source.

Constants (system prompts) and functions (user-message builders) are pulled out of the stage
files with `ast`, so the document cannot drift from the code — re-run this script after any
prompt change. The code remains authoritative.

Usage:  python3 code/make_prompts_md.py
Output: PROMPTS.md at the repo root.
"""
import ast
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "PROMPTS.md")


def extract(path, const_names=(), func_names=()):
    """Return ({const_name: string_value}, {func_name: source}) from a python file."""
    src = open(os.path.join(ROOT, path), encoding="utf-8").read()
    tree = ast.parse(src)
    consts, funcs = {}, {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in const_names \
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            consts[node.targets[0].id] = node.value.value
        if isinstance(node, ast.FunctionDef) and node.name in func_names:
            funcs[node.name] = ast.get_source_segment(src, node)
    missing = (set(const_names) - set(consts)) | (set(func_names) - set(funcs))
    if missing:
        raise SystemExit(f"{path}: could not extract {sorted(missing)}")
    return consts, funcs


def block(text, lang=""):
    return f"```{lang}\n{text.rstrip()}\n```\n"


parts = []
parts.append("""# Pipeline prompts — verbatim

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
""")

# ---- Stage 2: classification ----
c, _ = extract("code/classify_type.py", const_names=["SYS"])
parts.append("## Stage 2 — Document classification (`code/classify_type.py`, gpt-5.4-mini)\n")
parts.append("**System prompt:**\n\n" + block(c["SYS"]))
parts.append('**User message** (per document):\n\n' + block("FILENAME: {filename}\nPAGES: {page_count}") +
             "\nOutput is constrained to a JSON schema with a single `type` field.\n")

# ---- Stage 5: refine unclear ----
c, f = extract("code/refine_unclear.py", const_names=["SYS"], func_names=["llm_is_order"])
parts.append("## Stage 5 — UNCLEAR refinement (`code/refine_unclear.py`, gpt-5.4-mini)\n")
parts.append("**System prompt:**\n\n" + block(c["SYS"]))
parts.append("**User message:** the document's first pages (OCR text, capped at 12,000 characters), "
             "with a caveat prepended when the filename contains “proposed” — assembled by:\n\n"
             + block(f["llm_is_order"], "python"))

# ---- Stage 6: gate ----
c, f = extract("code/confirm_orders.py", const_names=["SYS"], func_names=["build_user"])
parts.append("## Stage 6 — Order gate / screening (`code/confirm_orders.py`, gpt-5.5)\n")
parts.append("**System prompt:**\n\n" + block(c["SYS"]))
parts.append("**User message** — assembled per document by:\n\n" + block(f["build_user"], "python"))

# ---- Stage 8: extraction ----
c, f = extract("code/extract_orders.py", const_names=["SYSTEM"], func_names=["build_user"])
parts.append("## Stage 8 — Appointment extraction (`code/extract_orders.py`, gpt-5.5)\n")
parts.append("**System prompt** (includes the appointment-type vocabulary and all coding conventions):\n\n"
             + block(c["SYSTEM"]))
parts.append("**User message** — assembled per order by:\n\n" + block(f["build_user"], "python") +
             "\nOutput is constrained to the Pydantic `Extraction` schema defined in the same file.\n")

# ---- Stage 9: motion resolution ----
c, _ = extract("code/resolve_motions.py", const_names=["MOTION_SYS"])
parts.append("## Stage 9 — Motion / Rule-53 report resolution (`code/resolve_motions.py`, gpt-5.5)\n")
parts.append("**System prompt:**\n\n" + block(c["MOTION_SYS"]))
parts.append("**User message:** the full text of the cited motion or report (first 60,000 characters).\n")

# ---- dedup adjudication ----
c, f = extract("code/dedup_v2.py", const_names=["SYS_ATT", "SYS_FIRM"],
               func_names=["render_att", "render_firm"])
parts.append("## Identity adjudication — attorneys & firms (`code/dedup_v2.py`, gpt-5.5)\n")
parts.append("**System prompt — attorney pairs:**\n\n" + block(c["SYS_ATT"]))
parts.append("**System prompt — firm pairs:**\n\n" + block(c["SYS_FIRM"]))
parts.append("**User message:** candidate pairs are batched (14 per call) as numbered `PAIR k:` blocks, "
             "each side rendered with full context by:\n\n"
             + block(f["render_att"] + "\n\n" + f["render_firm"], "python") +
             "\nfollowed by `Return a verdict for each of the N pairs (id 0..N-1).` Output is a JSON "
             "array of `{id, verdict: same|distinct|unsure, confidence, reason}`.\n\n"
             "**Web-grounded second pass** (pairs the batch pass judged `unsure`): one pair per call via the "
             "Responses API with the `web_search` tool, prompt =\n\n"
             + block('{system prompt above}\n\nA: {rendered entity A}\nB: {rendered entity B}\n\n'
                     'Research if needed, then answer with JSON only: {"verdict":"same|distinct|unsure",'
                     '"confidence":"high|medium|low","reason":"..."}') +
             "\nAny pair still `unsure` after the web pass defaults to **distinct**.\n")

# ---- demographics ----
c, f = extract("code/attorney_demographics.py", const_names=["SYS"], func_names=["build_query"])
parts.append("## Attorney demographics (`code/attorney_demographics.py`, gpt-5.5 + web search)\n")
parts.append("**System prompt:**\n\n" + block(c["SYS"]))
parts.append("**User message** — assembled per canonical attorney by:\n\n" + block(f["build_query"], "python"))

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(parts))
print(f"wrote {OUT} ({os.path.getsize(OUT):,} bytes)")
