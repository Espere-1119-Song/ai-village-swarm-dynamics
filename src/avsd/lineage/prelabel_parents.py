"""Labelling sheet for the parents of 50 module B2 occurrences, with local LLM pre-labels (SPEC 6.4.5).

SPEC 6.4.5: explicit references give part of the parent labels automatically
(`avsd.lineage.b2_refs`); the owner labels the parents of 50 more occurrences
by hand. The owner chose a local open-weight model for pre-labels and no paid
API (decisions 2026-10-01); the model only runs inference (SPEC 0.2). The
model, revision, decoding and caching follow `avsd.lineage.prelabel` (B1).

Stages (`python -m avsd.lineage.prelabel_parents <stage>`, scripts/prelabel_parents.sbatch):

1. prepare (project env, CPU, after `avsd lineage trees`). Sample: agent
   occurrences with at least two candidate parents (counting env_i) and no
   explicit-reference label, stratified by the channel of the MAP parent
   (seed from the config). Each item shows the child and up to MAX_CANDS
   candidates (all candidates when fewer; otherwise the most probable ones,
   always with the MAP parent and env_i), each as an excerpt of about
   WINDOW_CHARS characters around the unit (marked ⟦ ⟧). Credential-like
   strings are masked (`prelabel.mask_text`); humans are shown as "human".
   Writes requests.jsonl under data/interim/llm_cache/parent_prelabel/.
2. infer (vLLM env, one GPU): greedy JSON-schema decoding, cached per request.
   The owner's re-check of 2026-10-01 adds two stronger models on the same
   requests (`--model qwen35_122b|gptoss_120b`, or `prelabel infer --task
   parents` in scripts/prelabel_strong.sbatch): each labels independently, with
   the reasoning, sampling and retry settings of `avsd.lineage.prelabel.MODELS`,
   and its final answer must validate against OUTPUT_SCHEMA with a choice that
   names a candidate, ENV or NONE (PARENT_TASK). Outputs are cached in
   cache_<model>.jsonl next to the Qwen3-14B cache.
3. report (project env): data/labels/parents_review.csv (UTF-8 with BOM, mode
   600), parents_review_README.md (Chinese guide), outputs/qa/parent_prelabel.md
   (counts only). With the strong models' answers: their choices, a suggested
   parent where they agree, and review_priority 1 where they disagree with each
   other or with the MAP parent (2 otherwise); the first sheet is kept as
   parents_review_qwen14b.csv. Without them: 1 when the MAP posterior is below
   0.6 or Qwen3-14B disagrees with the MAP parent, else 2.
4. metrics (after the owner fills human_parent): accuracy of the MAP parent and
   of each model against the owner's labels, written to
   outputs/tables/trees_parent_label_metrics.csv.
5. claude (owner's design of 2026-10-03: Claude blind-labels all 50 rows, the
   owner audits 15): maps data/labels/claude_blind/b2.csv through
   parents_blind_map.json into data/labels/parents_claude.csv, like
   `scripts/blind_labels.py merge` does for the owner's labels. `avsd lineage
   trees --gamma composite` then uses the owner's label where it exists and
   Claude's elsewhere.

Top-level imports are standard library only, because the infer stage runs in a
separate vLLM environment.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from avsd.lineage.prelabel import (
    GPT_OSS_120B, MODEL_ID, MODEL_REVISION, MODELS, QWEN35_122B, SHEET_PREFIX, STRONG, LabelTask, _gpu_name, _now,
    _private_open, _read_jsonl, _structured_kwargs, answer_attempts, download, load_model_cache, split_answer,
)

CACHE_SUBDIR = "parent_prelabel"
TAG = ""  # "pilot": read data/interim/b2_pilot and write pilot_ files (testing only)
PROMPT_VERSION = "b2-parent-v1"
N_ITEMS = 50
MAX_CANDS = 6
WINDOW_CHARS = 320
MAX_TOKENS = 256
REVIEW_FILE = "parents_review.csv"
BACKUP_FILE = "parents_review_qwen14b.csv"  # the sheet before the strong-model re-check
README_FILE = "parents_review_README.md"
BLIND_FILE = "parents_blind.csv"  # the owner's blind copy (scripts/blind_labels.py): shuffled candidates
BLIND_MAP_FILE = "parents_blind_map.json"  # child_uid -> {blind candidate number: sheet candidate number}
CLAUDE_FILE = "parents_claude.csv"  # Claude's blind labels mapped to the review sheet's numbering, private
CLAUDE_BLIND = "claude_blind/b2.csv"
BLIND_MAP = "parents_blind_map.json"
GEMINI_FILE = "parents_gemini.csv"  # Gemini rater (scripts/gemini_label.py), private
GEMINI_PROMPT_VERSION = "b2-gemini-v1"
QA_FILE = "parent_prelabel.md"
METRICS_FILE = "trees_parent_label_metrics.csv"
STRATA = {"chat_other": 14, "chat_self": 6, "chat_to_memory": 10, "memory": 8, "env": 6, "search": 4, "history": 2}
CONFIDENCES = ("low", "medium", "high")
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "choice": {"type": "string"},
        "confidence": {"type": "string", "enum": list(CONFIDENCES)},
        "rationale": {"type": "string"},
    },
    "required": ["choice", "confidence", "rationale"],
    "additionalProperties": False,
}
SYSTEM_PROMPT = ("You decide where an AI agent got a piece of information from. Reply with one JSON object and "
                 "nothing else.")
TASK = (
    "Several AI agents work together in a chat village. Each also has its own long-term memory notes, can search "
    "the chat history (an assistant writes the answer), and uses a computer.\n"
    "The CHILD below mentions a piece of information, marked ⟦ ⟧. The CANDIDATES are the earlier places where the "
    "agent could have got it: chat messages it could see, its own memory notes, its own search answers, and its "
    "own computer screen or tool output (ENV, an independent observation).\n"
    "Pick the candidate the CHILD most likely took the information from. Shared wording, shared numbers and a "
    "direct reply are strong evidence; being the most recent message is weak evidence. Choose ENV when the agent "
    "most likely saw it itself on its computer. Choose NONE when no candidate fits.\n"
    "Reply with {\"choice\": \"<candidate number, ENV or NONE>\", \"confidence\": \"low|medium|high\", "
    "\"rationale\": \"<at most 25 words>\"}."
)
CHANNEL_NAME = {
    "chat>chat:other": "chat message by another agent", "chat>chat:self": "its own earlier chat message",
    "chat>human": "chat message", "chat>memory:other": "chat message by another agent",
    "chat>memory:self": "its own earlier chat message", "memory>chat": "its own memory notes",
    "search>chat": "its own search-history answer", "search>memory": "its own search-history answer",
    "history>search": "chat message in the searched period", "env>chat": "ENV: its own computer",
    "env>memory": "ENV: its own computer",
}


def cache_dir(cfg: dict) -> Path:
    from avsd.config import REPO_ROOT

    base = cfg.get("llm", {}).get("cache_dir")
    root = (REPO_ROOT / base) if base else Path(cfg["paths"]["interim"]) / "llm_cache"
    return Path(root).resolve() / (CACHE_SUBDIR + (f"_{TAG}" if TAG else ""))


def sampling_params(seed: int) -> dict:
    return {"temperature": 0.0, "max_tokens": MAX_TOKENS, "seed": int(seed)}


def request_key(messages: list[dict], seed: int) -> str:
    blob = json.dumps({"model": MODEL_ID, "revision": MODEL_REVISION, "messages": messages,
                       "chat_template_kwargs": {"enable_thinking": False}, "sampling": sampling_params(seed),
                       "schema": OUTPUT_SCHEMA, "prompt_version": PROMPT_VERSION}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --- excerpts -------------------------------------------------------------------------------------------------

def _excerpt(text: str, pos: int, span: int, mask_fn) -> str:
    """About WINDOW_CHARS characters around [pos, pos + span), the span marked ⟦ ⟧, credentials masked."""
    text = text or ""
    if pos < 0:
        pos, span = 0, 0
    a = max(0, pos - WINDOW_CHARS // 2)
    b = min(len(text), pos + span + WINDOW_CHARS // 2)
    seg = text[a:pos] + "⟦" + text[pos:pos + span] + "⟧" + text[pos + span:b] if span else text[a:b]
    seg = mask_fn(seg).replace("\n", " ↵ ")
    return ("…" if a > 0 else "") + seg + ("…" if b < len(text) else "")


def _locate(text: str, unit: dict, salt: bytes) -> tuple[int, int]:
    from avsd.lineage.b2_units import GRAM_N, _TOK, gram_ids_from, locate, token_ids

    if unit["unit_kind"] == "gram":
        ms = list(_TOK.finditer(text or ""))
        if len(ms) >= GRAM_N:
            g = gram_ids_from(token_ids([m.group(0).lower() for m in ms]))
            import numpy as np

            hit = np.flatnonzero(g == unit["unit_id"])
            if len(hit):
                k = int(hit[0])
                return ms[k].start(), ms[k + GRAM_N - 1].end() - ms[k].start()
        return -1, 0
    p = locate(text or "", unit["anchor_type"], unit["value"] or "", salt)
    if p < 0:
        return -1, 0
    m = re.match(r"[^\s,;:)\]]+(?:\s[^\s,;:)\]]+){0,3}", (text or "")[p:])
    return p, (len(m.group(0)) if m else 1)


# --- stage 1: prepare ---------------------------------------------------------------------------------------------

def prepare(cfg: dict, log=print) -> dict:
    import numpy as np
    import polars as pl

    from avsd.lineage.anchors import display_value, load_salt
    from avsd.lineage.prelabel import mask_text
    from avsd.lineage.trees_kernel import KEYS
    from avsd.lineage.trees_stats import CH_OF_KEY, H1_CHANNELS

    paths = cfg["paths"]
    d = Path(paths["interim"]) / ("b2" + (f"_{TAG}" if TAG else ""))
    salt = load_salt(Path(paths["interim"]))
    seed = int(cfg["seed"])
    occ = pl.read_parquet(d / "occurrences.parquet").sort("uidx", "ts_utc", "occ_uid").with_row_index("gi")
    units = pl.read_parquet(d / "units.parquet")
    cand = pl.read_parquet(d / "candidates.parquet")
    chosen = pl.read_parquet(d / "map_chosen.parquet")["chosen"].to_numpy()
    refs = pl.read_parquet(d / "explicit_refs.parquet")
    env_hits = pl.read_parquet(d / "env_hits.parquet")
    agents = pl.read_parquet(Path(paths["processed"]) / "agents.parquet")
    name = dict(zip(agents["agent_id"].to_list(), agents["name"].to_list()))
    child = cand["child"].to_numpy()
    n_cand = np.bincount(child, minlength=occ.height)
    labelled = set(refs["child_uid"].to_list())
    doc = occ["doc_uid"].to_list()
    src = occ["src"].to_list()
    actor_type = occ["actor_type"].to_list()
    key = cand["key"].to_numpy()
    par = cand["parent"].to_numpy()
    post = cand["post"].to_numpy()
    # Stratum of each eligible child: the channel of its MAP parent.
    strata: dict[str, list[int]] = {k: [] for k in STRATA}
    for i in np.flatnonzero(n_cand >= 2):
        if actor_type[i] != "agent" or doc[i] in labelled or chosen[i] < 0:
            continue
        r = int(chosen[i])
        if par[r] == -2:
            st = "env"
        else:
            ch = CH_OF_KEY[int(key[r])]
            st = H1_CHANNELS[ch] if ch >= 0 else None
        if st in strata:
            strata[st].append(int(i))
    rng = np.random.default_rng([seed, 64])
    pick: list[tuple[str, int]] = []
    want = dict(STRATA)
    spare = 0
    for st, n in want.items():
        pool = strata[st]
        k = min(n, len(pool))
        spare += n - k
        pick += [(st, int(x)) for x in rng.choice(pool, size=k, replace=False)] if k else []
    if spare:
        rest = [(st, i) for st, pool in strata.items() for i in pool if (st, i) not in set(pick)]
        if rest:
            sel = rng.choice(len(rest), size=min(spare, len(rest)), replace=False)
            pick += [rest[int(s)] for s in sel]
    log(f"prepare: {len(pick)} items; eligible by stratum " + ", ".join(f"{k} {len(v)}" for k, v in strata.items()))
    # Texts.
    need_docs = set()
    rows_of: dict[int, list[int]] = {}
    for _, i in pick:
        rr = np.flatnonzero(child == i)
        rr = rr[np.argsort(-post[rr])]
        keep = list(rr[:MAX_CANDS])
        for extra in (int(chosen[i]),) + tuple(int(x) for x in rr if par[x] == -2):
            if extra not in keep:
                keep = keep[:MAX_CANDS - 1] + [extra]
        keep = sorted(set(keep), key=lambda x: (par[x] == -2, -post[x]))
        rows_of[i] = keep
        need_docs.add(doc[i])
        need_docs.update(doc[int(par[x])] for x in keep if par[x] >= 0)
    texts = _texts(cfg, need_docs)
    umap = {int(u): r for u, r in zip(units["uidx"].to_list(), units.iter_rows(named=True))}
    uidx = occ["uidx"].to_numpy()
    ts_ = occ["ts_utc"].to_list()
    actors = occ["actor_id"].to_list()
    occ_uid = occ["occ_uid"].to_list()
    turn_texts = _turn_texts(cfg, env_hits, [(int(uidx[i]), actors[i], ts_[i]) for _, i in pick
                                             if any(par[x] == -2 for x in rows_of[i])], units)
    out = cache_dir(cfg)
    out.mkdir(parents=True, exist_ok=True)
    reqs = []
    for k, (st, i) in enumerate(pick):
        u = umap[int(uidx[i])]

        def who(j):
            return "human" if actors[j] == "human" else name.get(actors[j], "agent")

        def exc(j):
            t = texts.get(doc[j], "")
            p, span = _locate(t, u, salt)
            return _excerpt(t, p, span, mask_text)

        cands = []
        for q, r in enumerate(rows_of[i], start=1):
            if par[r] == -2:
                tx = turn_texts.get((int(uidx[i]), actors[i], ts_[i]), "")
                p, span = _locate(tx, u, salt)
                cands.append({"n": q, "row": int(r), "uid": "env", "who": who(i), "channel": "ENV: its own computer",
                              "key": KEYS[int(key[r])], "dt_h": float(cand["dt"][int(r)]) / 3600, "post": float(post[r]),
                              "excerpt": _excerpt(tx, p, span, mask_text) if tx else "(turn text not available)"})
            else:
                j = int(par[r])
                cands.append({"n": q, "row": int(r), "uid": occ_uid[j], "who": who(j),
                              "channel": CHANNEL_NAME.get(KEYS[int(key[r])], KEYS[int(key[r])]),
                              "key": KEYS[int(key[r])], "dt_h": float(cand["dt"][int(r)]) / 3600,
                              "post": float(post[r]), "excerpt": exc(j)})
        map_n = next((cc["n"] for cc in cands if cc["row"] == int(chosen[i])), None)
        lines = [TASK, "", f"CHILD ({who(i)}, {src[i]}): {exc(i)}", "", "CANDIDATES:"]
        for cc in cands:
            lines.append(f"[{cc['n']}] {cc['channel']} ({cc['who']}), {cc['dt_h']:.2f} active hours before: "
                         f"{cc['excerpt']}")
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "\n".join(lines)}]
        reqs.append({"item": k + 1, "stratum": st, "gi": int(i), "child_uid": occ_uid[i], "child_src": src[i],
                     "child_agent": who(i), "child_excerpt": exc(i), "unit_kind": u["unit_kind"],
                     "unit_type": u["anchor_type"],
                     "unit_value": ("gram" if u["unit_kind"] == "gram" else display_value(u["anchor_type"], u["value"] or "", salt)),
                     "candidates": cands, "map_n": map_n, "map_post": float(post[int(chosen[i])]),
                     "messages": messages, "key": request_key(messages, seed)})
    with _private_open(out / "requests.jsonl", "w", encoding="utf-8") as f:
        for r in reqs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    stats = {"items": len(reqs), "eligible": {k: len(v) for k, v in strata.items()}, "seed": seed, "created": _now()}
    (out / "prepare_stats.json").write_text(json.dumps(stats, indent=1))
    log(f"prepare: wrote {len(reqs)} requests")
    return stats


def _texts(cfg: dict, docs: set[str]) -> dict[str, str]:
    """Full text of chat messages, search answers and memory rows (memory:<row id>)."""
    import polars as pl

    from avsd.lineage.memory import read_row_texts

    T = Path(cfg["paths"]["tables"])
    out: dict[str, str] = {}
    chat = [x[5:] for x in docs if x.startswith("chat:")]
    if chat:
        cm = pl.read_parquet(T / "chat_messages.parquet", columns=["id", "content"]).filter(pl.col("id").is_in(chat))
        out.update({"chat:" + i: c or "" for i, c in cm.iter_rows()})
    ev = [x[6:] for x in docs if x.startswith("event:")]
    if ev:
        et = (pl.scan_parquet(T / "events_text.parquet").select("id", "answer").filter(pl.col("id").is_in(ev)).collect())
        out.update({"event:" + i: a or "" for i, a in et.iter_rows()})
    mem = {x[7:] for x in docs if x.startswith("memory:")}
    if mem:
        tx = read_row_texts(T / "agent_memories_text.parquet", mem, 4)
        out.update({"memory:" + k: v for k, v in tx.items()})
    return out


def _turn_texts(cfg: dict, env_hits, wanted: list[tuple[int, str, object]], units) -> dict:
    """Observation text of the earliest env hit before each child (key (unit, agent, child time))."""
    import polars as pl

    from avsd.lineage.b2_units import TURN_FIELD_CAP, narrative_text

    if not wanted:
        return {}
    T = Path(cfg["paths"]["tables"])
    picks = {}
    for u, a, t in wanted:
        h = env_hits.filter((pl.col("uidx") == u) & (pl.col("agent_id") == a) & (pl.col("ts_utc") < t)).sort("ts_utc")
        if h.height:
            picks[(u, a, t)] = h["turn_uid"][0].removeprefix("turn:")
    ids = list(set(picks.values()))
    tt = (pl.scan_parquet(T / "computer_use_turns_text.parquet").filter(pl.col("id").is_in(ids)).collect())
    by = {r["id"]: "\n".join(x for x in ((r["output"] or "")[:TURN_FIELD_CAP], (r["error"] or "")[:TURN_FIELD_CAP],
                                         narrative_text(r["agent_messages"])) if x)
          for r in tt.iter_rows(named=True)}
    return {k: by.get(v, "") for k, v in picks.items()}


# --- stage 2: infer (vLLM env) --------------------------------------------------------------------------------

def infer(cfg: dict, model_dir: str | Path, max_model_len: int = 8192, gpu_memory_utilization: float = 0.90,
          log=print) -> dict:
    out = cache_dir(cfg)
    reqs = _read_jsonl(out / "requests.jsonl")
    if not reqs:
        raise SystemExit(f"no requests in {out}; run the prepare stage first")
    seed = int(cfg["seed"])
    cached = {e["key"] for e in _read_jsonl(out / "cache.jsonl") if e.get("output") is not None}
    todo = [r for r in reqs if r["key"] not in cached]
    run = {"started": _now(), "model": MODEL_ID, "revision": MODEL_REVISION, "requests": len(reqs),
           "cached": len(reqs) - len(todo), "prompt_version": PROMPT_VERSION}
    t0 = time.perf_counter()
    if todo:
        from vllm import LLM, SamplingParams

        llm = LLM(model=str(model_dir), tokenizer=str(model_dir), dtype="bfloat16", seed=seed,
                  max_model_len=max_model_len, gpu_memory_utilization=gpu_memory_utilization, enforce_eager=True,
                  enable_prefix_caching=True, tensor_parallel_size=1)
        tok = llm.get_tokenizer()
        prompts = [tok.apply_chat_template(r["messages"], tokenize=False, add_generation_prompt=True,
                                           enable_thinking=False) for r in todo]
        sp = SamplingParams(temperature=0.0, max_tokens=MAX_TOKENS, seed=seed, **_structured_kwargs(OUTPUT_SCHEMA))
        outs = llm.generate(prompts, sp, use_tqdm=False)
        with _private_open(out / "cache.jsonl", "a", encoding="utf-8") as f:
            for r, p, o in zip(todo, prompts, outs):
                c = o.outputs[0]
                f.write(json.dumps({"key": r["key"], "created": _now(), "model": MODEL_ID, "revision": MODEL_REVISION,
                                    "prompt_version": PROMPT_VERSION, "messages": r["messages"], "prompt": p,
                                    "sampling": sampling_params(seed), "schema": OUTPUT_SCHEMA, "output": c.text,
                                    "finish_reason": c.finish_reason}, ensure_ascii=False) + "\n")
        run["generated"] = len(todo)
    run["gpu"] = _gpu_name()
    run["seconds"] = round(time.perf_counter() - t0, 1)
    run["slurm_job"] = os.environ.get("SLURM_JOB_ID", "")
    with _private_open(out / "runs.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(run) + "\n")
    log(f"infer: {run.get('generated', 0)} generated, {run['cached']} cached, {run['seconds']} s, {run['gpu']}")
    return run


# --- stage 3: report ----------------------------------------------------------------------------------------------

def parse_choice(text: str | None, n_cands: int) -> dict:
    try:
        o = json.loads(text or "")
    except (TypeError, ValueError):
        return {"choice": "", "confidence": "", "rationale": "", "error": "unparsable"}
    ch = str(o.get("choice", "")).strip().upper().strip("[]")
    if ch not in ("ENV", "NONE") and not (ch.isdigit() and 1 <= int(ch) <= n_cands):
        ch = ""
    return {"choice": ch, "confidence": o.get("confidence", ""), "rationale": " ".join(str(o.get("rationale", "")).split()[:30])}


def choice_ok(answer: str, req: dict) -> bool:
    """The answer is exactly one OUTPUT_SCHEMA object whose choice names a candidate, ENV or NONE."""
    try:
        o = json.loads(answer)
    except (TypeError, ValueError):
        return False
    if not (isinstance(o, dict) and set(o) == set(OUTPUT_SCHEMA["required"]) and o["confidence"] in CONFIDENCES
            and isinstance(o["rationale"], str) and isinstance(o["choice"], str)):
        return False
    return bool(parse_choice(answer, len(req.get("candidates") or []))["choice"])


# The parent sheet as a task of `avsd.lineage.prelabel.infer` (the re-check models). The cache key
# includes the prompt version, as the Qwen3-14B keys of this module do.
PARENT_TASK = LabelTask("parents", OUTPUT_SCHEMA, PROMPT_VERSION, choice_ok, key_prompt_version=True)

# b2-gemini-v1 (2026-10-01, Gemini rater): the TASK above with the candidates of the owner's blind sheet in
# its shuffled order, without posteriors or the MAP parent; ⟦ ⟧ stays, since it is the only pointer to the
# information for low-frequency phrases (their value is not shown); personal data replaced.
GEMINI_NOTE = ("… marks cut text, ↵ a line break and «masked» a hidden credential. [PERSON_1], [EMAIL_1] and "
               "[PHONE_1] stand for redacted personal data; the same placeholder means the same person, address "
               "or number.")


def blind_candidates(row: dict) -> list[int]:
    """Candidate numbers present in a blind-sheet row (1 to MAX_CANDS)."""
    return [j for j in range(1, MAX_CANDS + 1) if (row.get(f"cand_{j}_excerpt") or row.get(f"cand_{j}_channel")
                                                 or "").strip()]


def gemini_b2_messages(row: dict, redactor) -> tuple[list[dict], list[int], Counter]:
    """Chat messages for one blind-sheet row (b2-gemini-v1), the candidate numbers offered, and the number
    of placeholders by kind. Candidates keep the blind sheet's order and numbering."""
    from avsd.lineage.prelabel import uncell

    cands = blind_candidates(row)
    fields = {"child": uncell(row.get("child_excerpt")), **{f"c{j}": uncell(row.get(f"cand_{j}_excerpt"))
                                                           for j in cands}}
    red, counts = redactor.redact(fields)
    lines = [TASK, GEMINI_NOTE, "",
             f"CHILD ({row.get('child_agent', '')}, {row.get('child_source', '')}): {red['child']}", "", "CANDIDATES:"]
    for j in cands:
        try:
            dt = f"{float(row.get(f'cand_{j}_dt_h') or 0):.2f}"
        except ValueError:
            dt = "?"
        lines.append(f"[{j}] {row.get(f'cand_{j}_channel', '')} ({row.get(f'cand_{j}_who', '')}), {dt} active hours "
                     f"before: {red[f'c{j}']}")
    return ([{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "\n".join(lines)}], cands,
            counts)


def gemini_parent(choice: str, blind_to_sheet: dict[str, str], sheet_row: dict) -> str:
    """A Gemini choice in blind numbering as the review sheet's label: its candidate number, env or none."""
    ch = (choice or "").strip().lower().strip("[]")
    if ch in ("", "env", "none"):
        return ch
    k = blind_to_sheet.get(ch)
    if k is None:
        return ""
    cands = [{"n": q, "uid": (sheet_row.get(f"cand_{q}_uid") or "").strip()} for q in range(1, MAX_CANDS + 1)]
    return normalize_label(k, cands)


def strong_answers(reqs: list[dict], out: Path, seed: int) -> dict[str, list[dict | None]]:
    """Per re-check model with a cache file: per request the parsed choice of the first attempt that
    validates (choice '' when none does), with attempt, attempts, finish_reason and output_tokens;
    None when the request was never generated."""
    res: dict[str, list[dict | None]] = {}
    for k in STRONG:
        spec = MODELS[k]
        cache = load_model_cache(out, spec)
        if not cache:
            continue
        rows: list[dict | None] = []
        for r in reqs:
            e, a, n = answer_attempts(spec, r["messages"], seed, cache, PARENT_TASK, r)
            if e is None:
                rows.append(None)
                continue
            ans, _ = split_answer(e["output"], spec.reasoning)
            p = parse_choice(ans if a is not None else None, len(r["candidates"]))
            p.update(attempt=a, attempts=n, finish_reason=e.get("finish_reason"),
                     output_tokens=int(e.get("output_tokens") or 0))
            rows.append(p)
        res[k] = rows
    return res


README_TEXT = """# parents_review.csv labelling guide

This sheet has {n} rows. Each row is one occurrence (CHILD) of an information unit and serves to validate the inferred parents. CHILD is a place where an agent mentions a piece of information (the anchor marked ⟦ ⟧: a URL, number, date, name or rare phrase) in chat, memory or a search answer. cand_1 to cand_{m} are the earlier sources the agent could see under the rules: chat messages in its room (its own earlier messages included), its own memory, its own search answers, and env (its own computer output or its description of the screen, that is, independent observation). Each candidate gives the channel, speaker, lead in active hours, posterior probability and an excerpt of about 300 characters; … marks a cut, ↵ a line break and «masked» a masked credential. Humans always show as human.

model_map is the inferred parent (a candidate number or env) and model_post its posterior. Three local models labelled every row independently without seeing model_map, the posterior or each other: llm_* from Qwen3-14B, qwen35_* from Qwen3.5-122B-A10B and gptoss_* from gpt-oss-120b (the last two reason before answering). suggested_parent holds the parent when the two stronger models agree. The labels are suggestions only. The first column, review_priority, sorts the sheet: priority 1: {n1} rows, where the two stronger models disagree with each other or with model_map; priority 2: {n2} rows, where both agree with model_map. Please label all {n} rows if you can.

Fill human_parent with:
- a candidate number (1 to {m}): CHILD most likely got the information from this candidate;
- env: the agent saw it on its own computer (independent observation);
- none: no candidate looks like the source;
- nothing, with the reason in notes, when it cannot be judged; empty rows are left out.
Judge by matching content (the same number, the same wording, a direct reply), not by recency alone. If the anchor itself is wrong, judge the source of the information and write bad_unit in notes.

The sheet holds excerpts with personal data. Keep it in `data/labels/` (git-ignored); never share, upload or commit it. Do not edit child_uid or the candidate uids.

When done, on GRASP (`cd ~/ai-village-swarm-dynamics`):
1. `source scripts/env.sh && python -m avsd.lineage.prelabel_parents metrics` writes the accuracy of the inferred parents and the model labels against the human labels, with 95% intervals, to `outputs/tables/trees_parent_label_metrics.csv`.
2. `avsd lineage trees --gamma composite` chooses the time term and γ on these labels and reruns the transmission trees.
"""


README_TEXT_QWEN14B = """# parents_review.csv labelling guide

This sheet has {n} rows. Each row is one occurrence (CHILD) of an information unit and serves to validate the inferred parents. CHILD is a place where an agent mentions a piece of information (the anchor marked ⟦ ⟧: a URL, number, date, name or rare phrase) in chat, memory or a search answer. cand_1 to cand_{m} are the earlier sources the agent could see under the rules: chat messages in its room (its own earlier messages included), its own memory, its own search answers, and env (its own computer output or its description of the screen, that is, independent observation). Each candidate gives the channel, speaker, lead in active hours, posterior probability and an excerpt of about 300 characters; … marks a cut, ↵ a line break and «masked» a masked credential. Humans always show as human.

model_map is the inferred parent (a candidate number or env) and model_post its posterior. llm_choice, llm_confidence and llm_rationale are suggestions from the local model Qwen3-14B. The first column, review_priority, sorts the sheet: 1 marks rows with a posterior below 0.6 or a model that disagrees, 2 the rest. Please label all 50 rows if you can.

Fill human_parent with:
- a candidate number (1 to {m}): CHILD most likely got the information from this candidate;
- env: the agent saw it on its own computer (independent observation);
- none: no candidate looks like the source;
- nothing, with the reason in notes, when it cannot be judged; empty rows are left out.
Judge by matching content (the same number, the same wording, a direct reply), not by recency alone. If the anchor itself is wrong, judge the source of the information and write bad_unit in notes.

The sheet holds excerpts with personal data. Keep it in `data/labels/` (git-ignored); never share, upload or commit it. Do not edit child_uid or the candidate uids.

When done, on GRASP (`cd ~/ai-village-swarm-dynamics`):
1. `source scripts/env.sh && python -m avsd.lineage.prelabel_parents metrics` writes the accuracy of the inferred parents and the model labels against the human labels, with 95% intervals, to `outputs/tables/trees_parent_label_metrics.csv`.
2. `avsd lineage trees --gamma composite` chooses the time term and γ on these labels and reruns the transmission trees.
"""


def normalize_label(choice: str, cands: list[dict]) -> str:
    """'env' for ENV or the number of the env candidate, 'none', or the candidate number."""
    ch = (choice or "").strip().lower().strip("[]")
    if ch in ("env", "none", ""):
        return ch
    if ch.isdigit():
        for c in cands:
            if c["n"] == int(ch):
                return "env" if c["uid"] == "env" else ch
    return ch


def _sheet_norm(r: dict, v: str) -> str:
    return normalize_label(v, [{"n": q, "uid": r.get(f"cand_{q}_uid", "").strip()} for q in range(1, MAX_CANDS + 1)])


def label_agreement(owner_rows: list[dict], other_rows: list[dict]) -> tuple[int, int]:
    """(agreeing, both labelled) between the human_parent columns of two copies of the review sheet, with the
    number of an ENV candidate counted as env."""
    other = {r["child_uid"].strip(): r for r in other_rows}
    agree = both = 0
    for r in owner_rows:
        o = other.get(r["child_uid"].strip())
        a, b = r.get("human_parent", "").strip().lower(), (o or {}).get("human_parent", "").strip().lower()
        if a and b:
            both += 1
            agree += _sheet_norm(r, a) == _sheet_norm(r, b)
    return agree, both


def claude_sheet(cfg: dict, log=print) -> dict:
    """data/labels/parents_claude.csv: the review sheet with Claude's blind labels (claude_blind/b2.csv, in the
    blind sheet's shuffled numbering) mapped back through parents_blind_map.json into human_parent, as
    scripts/blind_labels.py merge does for the owner's labels."""
    labels = Path(cfg["paths"]["labels"])
    mapping = json.loads((labels / BLIND_MAP).read_text())
    with open(labels / CLAUDE_BLIND, encoding="utf-8-sig", newline="") as f:
        claude = {r["child_uid"].strip(): r for r in csv.DictReader(f)}
    with open(labels / REVIEW_FILE, encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        cols, rows = list(rd.fieldnames or []), list(rd)
    out = []
    for r in rows:
        cu = r["child_uid"].strip()
        c = claude.get(cu)
        h = (c or {}).get("claude_parent", "").strip().lower()
        if h and h not in ("env", "none"):
            if h not in mapping.get(cu, {}):
                raise SystemExit(f"Claude's label {h!r} for item {c.get('item')} is not a candidate")
            h = mapping[cu][h]
        out.append(dict(r, human_parent=h, notes=f"claude confidence {c.get('confidence', '')}" if c else ""))
    dest = labels / CLAUDE_FILE
    with _private_open(dest, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)
    agree, both = label_agreement(rows, out)
    res = {"rows": len(out), "labelled": sum(1 for o in out if o["human_parent"]), "owner_agree": agree,
           "owner_both": both}
    log(f"claude: {dest} ({res['labelled']} of {res['rows']} rows labelled); agreement with the owner {agree} of {both}")
    return res


def _cell(v) -> str:
    s = "" if v is None else str(v)
    return " " + s if s[:1] in ("=", "+", "-", "@") else s


def _wilson(k: int, n: int) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    z, p = 1.959964, k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / (1 + z * z / n)
    return max(0.0, c - h), min(1.0, c + h)


def report(cfg: dict, log=print) -> dict:
    """The parent sheet, its guide and the QA note (counts only).

    With every request answered by both re-check models (`strong_answers`): their choices, a suggested
    parent where they agree, and priority 1 where they disagree with each other or with the MAP
    parent; the first sheet is copied to BACKUP_FILE before it is replaced. human_parent and notes are
    carried over by child_uid."""
    import shutil

    from avsd.lineage.prelabel import mask_text

    out = cache_dir(cfg)
    reqs = _read_jsonl(out / "requests.jsonl")
    seed = int(cfg["seed"])
    cache = {e["key"]: e for e in _read_jsonl(out / "cache.jsonl") if e.get("output") is not None}
    strong = strong_answers(reqs, out, seed)
    recheck = all(k in strong and all(x is not None for x in strong[k]) for k in STRONG)
    labels_dir = Path(cfg["paths"]["labels"])
    pre = f"{TAG}_" if TAG else ""
    dest = labels_dir / (pre + REVIEW_FILE)
    old = {}
    if dest.exists():
        with open(dest, encoding="utf-8-sig") as f:
            rd = csv.DictReader(f)
            for r in rd:
                old[r["child_uid"].strip()] = (r.get("human_parent", ""), r.get("notes", ""))
            old_cols = list(rd.fieldnames or [])
        backup = labels_dir / (pre + BACKUP_FILE)
        if recheck and "qwen35_choice" not in old_cols and not backup.exists():
            shutil.copyfile(dest, backup)
            os.chmod(backup, 0o600)
            log(f"report: copied the Qwen3-14B sheet to {backup}")
    header = ["review_priority", "item", "stratum", "child_uid", "child_agent", "child_source", "unit_type",
              "unit_value", "child_excerpt"]
    for q in range(1, MAX_CANDS + 1):
        header += [f"cand_{q}_uid", f"cand_{q}_channel", f"cand_{q}_who", f"cand_{q}_dt_h", f"cand_{q}_post",
                   f"cand_{q}_excerpt"]
    header += ["model_map", "model_post", "llm_choice", "llm_confidence", "llm_rationale"]
    if recheck:
        header += ["suggested_parent"] + [f"{SHEET_PREFIX[k]}_{c}" for k in STRONG
                                          for c in ("choice", "confidence", "rationale")]
    header += ["human_parent", "notes"]
    rows, agree, n_llm = [], 0, 0
    lab: dict[str, list[str]] = {"map": [], "qwen3_14b": [], **{k: [] for k in STRONG}}
    for i, r in enumerate(reqs):
        e = cache.get(r["key"])
        p = parse_choice(e["output"] if e else None, len(r["candidates"]))
        map_label = normalize_label(str(r["map_n"]), r["candidates"])
        llm_label = normalize_label(p["choice"], r["candidates"])
        lab["map"].append(map_label)
        lab["qwen3_14b"].append(llm_label)
        if llm_label:
            n_llm += 1
            agree += llm_label == map_label
        row = [None, r["item"], r["stratum"], r["child_uid"], r["child_agent"], r["child_src"], r["unit_type"],
               r["unit_value"], r["child_excerpt"]]
        for q in range(MAX_CANDS):
            if q < len(r["candidates"]):
                c = r["candidates"][q]
                row += [c["uid"], c["channel"], c["who"], f"{c['dt_h']:.3f}", f"{c['post']:.3f}", c["excerpt"]]
            else:
                row += [""] * 6
        row += [map_label, f"{r['map_post']:.3f}", llm_label, p["confidence"], p["rationale"]]
        if recheck:
            sl = {}
            for k in STRONG:
                x = strong[k][i]
                sl[k] = normalize_label(x["choice"], r["candidates"]) if x["attempt"] is not None else ""
                lab[k].append(sl[k])
            a, b = sl[QWEN35_122B.key], sl[GPT_OSS_120B.key]
            sug = a if a and a == b else ""
            row[0] = "1" if (not sug or sug != map_label) else "2"
            row.append(sug)
            for k in STRONG:
                x = strong[k][i]
                ok = x["attempt"] is not None
                row += [sl[k], x["confidence"] if ok else "",
                        (mask_text(x["rationale"]) if x["rationale"] else "") if ok else "(no valid model output)"]
        else:
            row[0] = "1" if (r["map_post"] < 0.6 or (llm_label and llm_label != map_label)) else "2"
        h, nt = old.get(r["child_uid"], ("", ""))
        row += [h, nt]
        rows.append(row)
    rows.sort(key=lambda x: (x[0], int(x[1])))
    with _private_open(dest, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for row in rows:
            w.writerow([_cell(v) for v in row])
    n1 = sum(1 for r in rows if r[0] == "1")
    readme = labels_dir / (pre + README_FILE)
    with _private_open(readme, "w", encoding="utf-8") as f:
        f.write(README_TEXT.format(n=len(rows), m=MAX_CANDS, n1=n1, n2=len(rows) - n1) if recheck
                else README_TEXT_QWEN14B.format(n=len(rows), m=MAX_CANDS))
    strata = Counter(r["stratum"] for r in reqs)
    qa = ["# QA: parent labelling sheet for module B2 (SPEC 6.4.5)", "",
          'Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village', "",
          f"Items: {len(rows)} (by MAP channel: " + ", ".join(f"{k} {v}" for k, v in sorted(strata.items())) + ").",
          f"Qwen3-14B pre-labels parsed: {n_llm} of {len(rows)}; agreement with the MAP parent: {agree} of {n_llm}.",
          f"Priority 1 rows: {n1}.",
          (f"Qwen3-14B: {MODEL_ID} (revision {MODEL_REVISION[:12]}), prompt {PROMPT_VERSION}, greedy decoding, "
           "thinking disabled, inference only. The sheet and its guide are private files under data/labels/ "
           "and are not copied elsewhere."), ""]
    if recheck:
        qa += _recheck_qa(reqs, strong, lab, out, seed, n1)
    qpath = Path(cfg["paths"]["outputs"]) / "qa" / (pre + QA_FILE)
    qpath.parent.mkdir(parents=True, exist_ok=True)
    qpath.write_text("\n".join(qa), encoding="utf-8")
    log(f"report: {dest} ({len(rows)} rows, priority 1: {n1}), {readme}, {qpath}")
    return {"rows": len(rows), "agree": agree, "n_llm": n_llm, "recheck": recheck, "priority1": n1, "labels": lab}


def _recheck_qa(reqs: list[dict], strong: dict, lab: dict[str, list[str]], out: Path, seed: int, n1: int) -> list[str]:
    """QA lines for the re-check by the two strong models (counts only)."""
    from avsd.lineage.prelabel import model_sampling, runs_file

    names = {"map": "MAP parent", "qwen3_14b": "Qwen3-14B", QWEN35_122B.key: "Qwen3.5-122B",
             GPT_OSS_120B.key: "gpt-oss-120b"}
    n = len(reqs)
    L = ["## Re-check with two stronger models", "",
         ("The owner asked on 2026-10-01 that two stronger local open-weight models re-check the pre-labels. Each "
          "model answered the same 50 cached requests (the prompts of Qwen3-14B) on its own; the prompts show "
          "neither the MAP parent, the posteriors nor the Qwen3-14B choice, but the candidates are listed in "
          "descending posterior order with ENV last, so candidate 1 is usually the MAP parent. Settings as in "
          "B1 (`avsd.lineage.prelabel.MODELS`); a final answer counts when it is one JSON object of the schema "
          "whose choice names a candidate, ENV or NONE."), "",
         "| model | valid answers | attempts used | output tokens per request (mean, max) | runs |",
         "|---|---|---|---|---|"]
    for k in STRONG:
        spec = MODELS[k]
        xs = [x for x in strong[k] if x]
        val = Counter(x["attempt"] for x in xs if x["attempt"] is not None)
        toks = [x["output_tokens"] for x in xs] or [0]
        runs = [x for x in _read_jsonl(out / runs_file(spec)) if x.get("generated")]
        smp = model_sampling(spec, seed)
        L.append(f"| {spec.name} (`{spec.revision[:12]}`; " + ", ".join(f"{a}={b}" for a, b in spec.template_kwargs)
                 + f"; temperature {smp['temperature']:g}) | {sum(val.values())} / {n} | "
                 + ", ".join(f"attempt {a + 1}: {v}" for a, v in sorted(val.items()))
                 + f" | {sum(toks) / len(toks):,.0f}, {max(toks):,} | "
                 + (", ".join(f"job {x.get('slurm_job')} on {x.get('gpu', '?').split(',')[0]}" for x in runs) or "-")
                 + " |")
    keys = ["map", "qwen3_14b", *STRONG]
    L += ["", "Agreement between labellers (items where both give a choice; 95% Wilson interval):", "",
          "| pair | items | same choice | share | 95% CI |", "|---|---|---|---|---|"]
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            idx = [j for j in range(n) if lab[a][j] and lab[b][j]]
            k_ = sum(1 for j in idx if lab[a][j] == lab[b][j])
            lo, hi = _wilson(k_, len(idx))
            L.append(f"| {names[a]} / {names[b]} | {len(idx)} | {k_} | "
                     f"{k_ / len(idx) if idx else float('nan'):.2f} | {lo:.2f} to {hi:.2f} |")
    q, g, m = lab[QWEN35_122B.key], lab[GPT_OSS_120B.key], lab["map"]
    sug = [x if x and x == y else "" for x, y in zip(q, g)]

    def kind(x: str) -> str:
        return "(none)" if not x else x if x in ("env", "none") else "candidate 1" if x == "1" else "other candidate"

    L += ["", (f"Strong models agree on {sum(1 for x in sug if x)} of {n} items; their shared choice equals the "
               f"MAP parent on {sum(1 for x, y in zip(sug, m) if x and x == y)}. Priority 1 rows (they disagree "
               f"with each other or with the MAP parent): {n1}."), "",
          "Choices by kind (candidate 1 is the highest-posterior candidate that is not ENV):", "",
          "| labeller | candidate 1 | other candidate | env | none | (none) |", "|---|---|---|---|---|---|"]
    for a in keys:
        c = Counter(kind(x) for x in lab[a])
        L.append(f"| {names[a]} | " + " | ".join(str(c.get(t, 0)) for t in
                                                ("candidate 1", "other candidate", "env", "none", "(none)")) + " |")
    by_st = defaultdict(lambda: [0, 0, 0])
    for r, s_, mm in zip(reqs, sug, m):
        st = by_st[r["stratum"]]
        st[0] += 1
        st[1] += bool(s_)
        st[2] += bool(s_) and s_ == mm
    L += ["", "By MAP channel (stratum): items, strong models agree, their choice equals the MAP parent:", "",
          "| stratum | items | agree | = MAP |", "|---|---|---|---|"]
    L += [f"| {k} | {v[0]} | {v[1]} | {v[2]} |" for k, v in sorted(by_st.items())]
    L.append("")
    return L


# --- stage 4: metrics -------------------------------------------------------------------------------------------------

def metrics(cfg: dict, log=print) -> list[dict]:
    """Accuracy of the MAP parent and of each model's pre-label against the owner's human_parent (rows
    with a label only); the re-check models when the sheet has their columns, their suggested parent on
    the rows that have one, and Gemini (GEMINI_FILE) on the rows it labelled."""
    from scipy import stats

    dest = Path(cfg["paths"]["labels"]) / REVIEW_FILE
    with open(dest, encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        rows = [r for r in rd if r.get("human_parent", "").strip()]
        cols = set(rd.fieldnames or [])

    def norm(r: dict, v: str) -> str:
        cands = [{"n": q, "uid": r.get(f"cand_{q}_uid", "").strip()} for q in range(1, MAX_CANDS + 1)]
        return normalize_label(v, cands)

    out = []
    labellers = [("model_map", "model_map"), ("llm", "llm_choice")]
    labellers += [(k, f"{SHEET_PREFIX[k]}_choice") for k in STRONG if f"{SHEET_PREFIX[k]}_choice" in cols]
    if "suggested_parent" in cols:
        labellers.append(("suggested_parent", "suggested_parent"))
    gem_path = Path(cfg["paths"]["labels"]) / GEMINI_FILE
    if gem_path.exists():  # scored on the rows it labelled
        with open(gem_path, encoding="utf-8-sig") as f:
            gem = {(r.get("child_uid") or "").strip(): r.get("gemini_parent") or "" for r in csv.DictReader(f)}
        for r in rows:
            if r["child_uid"].strip() in gem:
                r["_gemini"] = gem[r["child_uid"].strip()]
        labellers.append(("gemini", "_gemini"))
    for name, col in labellers:
        sub = ([r for r in rows if (r.get(col) or "").strip()] if name == "suggested_parent"
               else [r for r in rows if col in r] if name == "gemini" else rows)
        k = sum(1 for r in sub if norm(r, r.get(col) or "") == norm(r, r["human_parent"]))
        n = len(sub)
        lo, hi = stats.binomtest(k, n).proportion_ci(confidence_level=0.95, method="wilson") if n else (float("nan"), float("nan"))
        out.append({"labeller": name, "n_labelled": n, "agree_with_owner": k, "accuracy": k / n if n else float("nan"),
                    "accuracy_lo": float(lo), "accuracy_hi": float(hi)})
    p = Path(cfg["paths"]["outputs"]) / "tables" / METRICS_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    log(f"metrics: {p}")
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Parent labelling sheet for module B2 (SPEC 6.4.5).")
    ap.add_argument("--config", default=None)
    ap.add_argument("--pilot", action="store_true", help="use the pilot run (testing)")
    sub = ap.add_subparsers(dest="stage", required=True)
    sub.add_parser("prepare")
    sp = sub.add_parser("infer")
    sp.add_argument("--model", choices=sorted(MODELS), default="qwen3_14b",
                    help="qwen3_14b (this module's greedy run) or a re-check model (avsd.lineage.prelabel.infer)")
    sp.add_argument("--model-dir", default=None, help="default ~/models/<model dir>")
    sub.add_parser("report")
    sub.add_parser("metrics")
    sub.add_parser("claude", help="map Claude's blind labels into data/labels/parents_claude.csv")
    sp = sub.add_parser("download")
    sp.add_argument("--dest", default=str(Path.home() / "models" / "Qwen3-14B"))
    args = ap.parse_args(argv)
    global TAG
    TAG = "pilot" if args.pilot else ""
    if args.stage == "download":
        download(MODEL_ID, MODEL_REVISION, args.dest)
        return
    from avsd.config import load_config

    cfg = load_config(args.config)
    if args.stage == "prepare":
        prepare(cfg)
    elif args.stage == "infer":
        spec = MODELS[args.model]
        model_dir = args.model_dir or str(Path.home() / "models" / spec.dir_name)
        if args.model == "qwen3_14b":
            infer(cfg, model_dir)
        else:
            from avsd.lineage import prelabel

            prelabel.infer(cfg, model_dir, spec, tasks=[(PARENT_TASK, cache_dir(cfg))])
    elif args.stage == "report":
        report(cfg)
    elif args.stage == "claude":
        claude_sheet(cfg)
    else:
        metrics(cfg)


if __name__ == "__main__":
    main(sys.argv[1:])
