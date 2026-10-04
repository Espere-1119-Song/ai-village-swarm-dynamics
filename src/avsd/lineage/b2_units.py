"""Module B2 inputs: information units and their occurrences (SPEC 6.4.1, 6.4.2).

Stages of `build_units` (cached under <paths.interim>/b2/; only data/ holds text):

E1  Chat and search-answer text. Every chat message of an agent or a human
    (rows of the scaffolding bot are left out) and every SEARCH_HISTORY answer
    that is not a "no transcript" placeholder is cut into lines as in B1
    (`memory.clean_line`, `anchors.HeadingStack`, pieces of at most
    `anchors.MAX_PIECE_CHARS`). Each piece goes through the B1 extractor
    (regex anchors, spaCy NER and context keys, same salt, so PERSON, email and
    phone values and every value on a credential line are keyed hashes) with
    character spans, and is cut into word 4-grams. Grams never cross a URL,
    email, phone number, id, path or credential-like span
    (`prelabel.credential_spans`), and a gram made only of stop words, digits
    and agent-name tokens is dropped.
S1  Typed units. Unit identity follows B1 (`memory_facts`): (type, value), and
    for time, money, percent and number also the context key in B1's display
    form (the lemma when at least 3 agents use it as a noun in memory, else its
    keyed hash). Left out: agent names (every agent knows them from its
    prompt), quantities without a context key, hashed numbers (9 or more
    digits), every value on a credential line, anchors that overlap a
    credential-like span, and dates that name the occurrence's own day +/- 1
    (or its month): today's date is known without transmission. Memory
    occurrences are B1 presence spells: the first memory version that holds the
    unit in each agent's memory (`memory_facts`, spell 0).
G   4-gram units. Word 4-grams in 2 to 4 chat messages (fewer than 5, SPEC
    6.4.1) by at least two speakers (all humans count as one speaker). Grams
    with the same set of messages form one unit, represented by the smallest
    gram id.
E2  Memory. One scan of every live memory row (B1 `live_rows`, own text
    segments as in B1) finds, for each agent, the first and the last row that
    holds a candidate gram. The rows where a selected unit first appears are
    read again to cut the content window: the lines that carry the unit (B1
    line hashes and `line_anchors` for typed units, the gram for gram units).
S2  Selection (both kinds): at least one chat occurrence, at least
    `lineage.min_occurrences` (3) occurrences, at least 2 agents and at most
    `lineage.max_unit_occurrences` occurrences.
E3  Turns (env_i, SPEC 6.4.2). Each computer-use turn that does not mirror a
    chat message or an event (`dup_of_uid`) gives an observation text: the tool
    output, the error text and the text of the provider response (text,
    thinking and reasoning parts; tool-call arguments, which hold what the
    agent typed or sent, are left out). A hit is a turn of agent a whose
    observation text holds a unit that a also has an occurrence of: typed
    values by the regex anchors (quantities only with the context word next to
    the value, `anchors.ctx_adjacent`), entity and person values through
    capitalised word n-grams (`anchors.name_candidates`, persons by keyed
    hash), grams by token 4-grams.
E4  Content features of each occurrence window (chat: the message; search:
    the line of the first match +/- 1; memory: the lines that carry the unit):
    quantity values under their context key, rare 4-grams (fewer than 5 chat
    messages, SPEC 6.4.3) and the tokens within WINDOW_TOKENS of the anchor
    (attractor test, SPEC 6.4.4). Tokens and grams are stored as 64-bit ids.

Summaries are not occurrences (docs/decisions.md "Summaries are not
transmission parents"; schema_notes 4.3): no evidence that they enter prompts.
Agents read summary text only through tools, which E3 counts as env_i.

Privacy (SPEC 0.2): PERSON, email and phone values are keyed hashes before they
leave the worker processes; URLs and entity names stay in data/ only (as in B1).
Credential-like strings never become units or grams. Nothing here writes to
outputs/.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import hashlib
import itertools
import json
import multiprocessing as mp
import os
import re
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl
import pyarrow.parquet as pq

from avsd.lineage.anchors import (
    _ALPHA, _EMAIL, _PHONE, CRED_LINE, HASHED_TYPES, MAX_PIECE_CHARS, NER_TYPES, PROPN_MARK,
    QUANTITY_TYPES, TYPE_CODE, TYPES, AnchorExtractor, HeadingStack, _overlaps, ctx_adjacent, keyed_hash,
    literal_surfaces, load_nlp, load_salt, name_candidates, norm_entity, url_domain,
)
from avsd.lineage.chains import KIND_COPY
from avsd.lineage.memory import (
    SESSION_LABEL, _cache_paths, _stable_key, clean_line, live_rows, read_row_texts, segment_lines,
)
from avsd.lineage.prelabel import credential_spans

B2_DIR = "b2"
EXTRACT_VERSION = "b2-units-v1"
GRAM_N = 4
RARE_MAX_MSGS = 5  # a 4-gram is rare in fewer than this many chat messages (SPEC 6.4.1)
GRAM_UNIT_MIN_MSGS = 2
WINDOW_TOKENS = 20
TURN_FIELD_CAP = 50_000  # chars of each observation field scanned per turn
LINE_CAP = 2000  # chars per line piece in the turn scan
SEARCH_PLACEHOLDER = re.compile(r"(?i)^\s*(?:no (?:chat )?transcript|no messages|no history)")
ENTITY_KINDS = ("org", "gpe", "product", "event", "work_of_art")
EXCLUDED_TYPES = frozenset({"agent"})
QUANTITY_CODES = frozenset(TYPE_CODE[t] for t in QUANTITY_TYPES)
DATE_CODE = TYPE_CODE["date"]
VILLAGE_DAY1 = date(2025, 4, 2)
_TOK = re.compile(r"[^\W_]+(?:['’][^\W_]+)?")
_P1 = np.uint64(0x9E3779B97F4A7C15)
_EMPTY_I64 = np.zeros(0, dtype=np.int64)
# Keys of a provider response whose values the agent produced (tool calls) or that carry no text.
_SKIP_KEYS = frozenset({
    "input", "arguments", "functionCall", "function_call", "tool_calls", "action", "signature",
    "thoughtSignature", "usage", "usageMetadata", "encrypted_content", "partial_json", "id", "call_id",
    "name", "model", "modelVersion", "responseId", "status", "type", "role", "index", "finishReason",
    "stop_reason", "stop_sequence", "annotations", "logprobs",
})
_TEXT_KEYS = frozenset({"text", "thinking", "reasoning_content", "reasoning", "content", "refusal"})


# --- tokens and grams -----------------------------------------------------------------------------

_TOKCACHE: dict[str, int] = {}
_UNINFORMATIVE: frozenset[str] = frozenset()


def token_id(tok: str) -> int:
    v = _TOKCACHE.get(tok)
    if v is None:
        v = int.from_bytes(hashlib.blake2b(tok.encode("utf-8", "surrogatepass"), digest_size=8).digest(),
                           "little")
        if len(_TOKCACHE) < 4_000_000:
            _TOKCACHE[tok] = v
    return v


def tokens(text: str) -> list[str]:
    return _TOK.findall(text.lower())


def token_ids(toks: list[str]) -> np.ndarray:
    return np.fromiter((token_id(t) for t in toks), dtype=np.uint64, count=len(toks))


def gram_ids_from(ids: np.ndarray, informative: np.ndarray | None = None) -> np.ndarray:
    """Ids of consecutive token 4-grams (a polynomial hash mod 2**64); grams whose tokens are all
    uninformative are dropped when `informative` (one flag per token) is given."""
    if len(ids) < GRAM_N:
        return _EMPTY_I64
    with np.errstate(over="ignore"):
        h = ids[:-3].copy()
        for k in range(1, GRAM_N):
            h = h * _P1 + ids[k:len(ids) - GRAM_N + 1 + k]
    out = h.view(np.int64)
    if informative is not None:
        inf = informative.astype(np.int8)
        keep = np.convolve(inf, np.ones(GRAM_N, dtype=np.int8), mode="valid") > 0
        out = out[keep]
    return out


def in_sorted(x: np.ndarray, sorted_ref: np.ndarray) -> np.ndarray:
    """Membership of x in a sorted array (np.isin sorts the reference on every call)."""
    if not len(x) or not len(sorted_ref):
        return np.zeros(len(x), dtype=bool)
    pos = np.searchsorted(sorted_ref, x)
    pos[pos >= len(sorted_ref)] = 0
    return sorted_ref[pos] == x


def set_uninformative(words) -> None:
    global _UNINFORMATIVE
    _UNINFORMATIVE = frozenset(words)


def default_uninformative(agent_names) -> frozenset[str]:
    """Stop words, and the tokens of agent names (a gram of names and digits is not a phrase)."""
    try:
        from spacy.lang.en.stop_words import STOP_WORDS
    except ImportError:  # pragma: no cover
        STOP_WORDS = set()
    out = {w.lower() for w in STOP_WORDS}
    for n in agent_names:
        out.update(tokens(n))
    out.update({"claude", "gemini", "gpt", "grok", "deepseek", "kimi", "glm", "opus", "sonnet", "haiku",
                "fable", "flash", "pro", "luna", "sol", "terra", "astra", "muse", "spark"})
    return frozenset(out)


def text_grams(text: str, drop: list[tuple[int, int]] | None = None) -> np.ndarray:
    """Unique 4-gram ids of `text`; grams do not cross a span in `drop`."""
    segs: list[str] = []
    last = 0
    for s, e in sorted(drop or ()):
        if s > last:
            segs.append(text[last:s])
        last = max(last, e)
    segs.append(text[last:])
    parts = []
    for seg in segs:
        toks = tokens(seg)
        if len(toks) >= GRAM_N:
            inf = np.fromiter((t not in _UNINFORMATIVE and not t.isdigit() for t in toks), dtype=bool,
                              count=len(toks))
            parts.append(gram_ids_from(token_ids(toks), inf))
    if not parts:
        return _EMPTY_I64
    return np.unique(np.concatenate(parts))


def token_window(text: str, center: int, width: int = WINDOW_TOKENS) -> np.ndarray:
    """Ids of the tokens within `width` tokens of character position `center`."""
    ms = list(_TOK.finditer(text))
    if not ms:
        return _EMPTY_I64
    starts = np.fromiter((m.start() for m in ms), dtype=np.int64, count=len(ms))
    k = int(np.searchsorted(starts, center, side="right")) - 1
    k = max(k, 0)
    lo, hi = max(0, k - width), min(len(ms), k + width + 1)
    return token_ids([m.group(0).lower() for m in ms[lo:hi]]).view(np.int64)


# --- provider responses -----------------------------------------------------------------------------

def narrative_text(raw: str | None, cap: int = TURN_FIELD_CAP) -> str:
    """Text, thinking and reasoning parts of a raw provider response; tool-call arguments left out."""
    if not raw:
        return ""
    try:
        import orjson

        obj = orjson.loads(raw)
    except Exception:
        try:
            obj = json.loads(raw)
        except Exception:
            return ""
    out: list[str] = []
    size = 0

    def walk(o) -> None:
        nonlocal size
        if size >= cap:
            return
        if isinstance(o, dict):
            for k, v in o.items():
                if k in _SKIP_KEYS:
                    continue
                if isinstance(v, str):
                    if k in _TEXT_KEYS and v:
                        out.append(v)
                        size += len(v)
                elif isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                if isinstance(v, str):
                    continue
                walk(v)

    walk(obj)
    return "\n".join(out)[:cap]


# --- E1: anchors and grams of chat and search text ----------------------------------------------------

_EX: AnchorExtractor | None = None


def _init_worker(agent_names: list[str], salt: bytes, with_nlp: bool, uninformative: frozenset[str]) -> None:
    global _EX
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    _EX = AnchorExtractor(agent_names, salt, load_nlp() if with_nlp else None)
    set_uninformative(uninformative)


def anchor_spans_claims(ex: AnchorExtractor, text: str, doc, sensitive: bool):
    """Anchors of one piece with spans, and the spans claimed without an anchor (ids, paths).

    Rows: (start, end, type, raw value, stored value, context). Same rules as
    `prelabel.anchor_spans` (B1 `AnchorExtractor.anchors_for`)."""
    found, claimed = ex.regex_anchors(text)
    anchored = {(s, e) for s, e, _, _ in found}
    extra = [(s, e) for s, e in claimed if (s, e) not in anchored]
    if doc is not None:
        for ent in doc.ents:
            kind = NER_TYPES.get(ent.label_)
            if kind is None or _overlaps(claimed, ent.start_char, ent.end_char):
                continue
            v = norm_entity(ent.text)
            if v is not None:
                found.append((ent.start_char, ent.end_char, kind, v))
    if not found:
        return [], extra
    sensitive = sensitive or bool(CRED_LINE.search(text))
    ctx = ex.context_keys(doc, [(s, e) for s, e, _, _ in found]) if doc is not None else [""] * len(found)
    out = []
    for (s, e, kind, v), c in zip(found, ctx):
        stored = keyed_hash(ex.salt, kind, v) if (kind in HASHED_TYPES or sensitive) else v
        out.append((s, e, kind, v, stored, c))
    return out, extra


def _pieces(t: str) -> list[tuple[int, str]]:
    if len(t) <= MAX_PIECE_CHARS:
        return [(0, t)]
    out, start = [], 0
    while start < len(t):
        end = min(len(t), start + MAX_PIECE_CHARS)
        if end < len(t):
            cut = t.rfind(" ", start + MAX_PIECE_CHARS // 2, end)
            end = cut + 1 if cut > 0 else end
        out.append((start, t[start:end]))
        start = end
    return out


def display_lines(text: str) -> tuple[list[str], list[bool]]:
    """Lines of a text as B1 sees them (session labels blanked) and their heading sensitivity."""
    stack = HeadingStack()
    lines, sens = [], []
    for raw in (text or "").split("\n"):
        s = stack.feed(raw)
        line = SESSION_LABEL.sub(" ", raw) if "PREVIOUS (NOW ENDED)" in raw else raw
        lines.append(line)
        sens.append(s)
    return lines, sens


def _e1_worker(chunk: list[tuple[int, str]]) -> dict:
    ex = _EX
    pieces: list[str] = []
    meta: list[tuple[int, int, int, bool]] = []  # (k, line, offset, sensitive)
    masks: list[list[tuple[int, int]]] = []
    line_rows: list[tuple[int, int, int, int]] = []
    for k, (di, text) in enumerate(chunk):
        lines, sens_l = display_lines(text or "")
        disp = "\n".join(lines)
        pos = 0
        for ln, (line, s) in enumerate(zip(lines, sens_l)):
            clean = clean_line(line)
            if clean is not None:
                off = pos + len(line) - len(line.lstrip())
                s2 = s or bool(CRED_LINE.search(clean))
                line_rows.append((di, ln, pos, pos + len(line)))
                for p0, piece in _pieces(clean):
                    pieces.append(piece)
                    meta.append((k, ln, off + p0, s2))
            pos += len(line) + 1
        masks.append(credential_spans(disp, sens_l))
    has_alpha = [_ALPHA.search(p) is not None for p in pieces]
    nlp = ex.nlp
    docs = iter(nlp.pipe((p for p, a in zip(pieces, has_alpha) if a), batch_size=256)
                if nlp is not None else ())
    a_doc, a_line, a_s, a_e, a_t, a_v, a_c, a_m, a_h = [], [], [], [], [], [], [], [], []
    g_doc, g_line, g_parts = [], [], []
    for piece, (k, ln, base, sens), alpha in zip(pieces, meta, has_alpha):
        doc = next(docs) if (alpha and nlp is not None) else None
        found, extra = anchor_spans_claims(ex, piece, doc, sens)
        di = chunk[k][0]
        mk = masks[k]
        drop = list(extra)
        for s, e, kind, _raw, stored, c in found:
            gs, ge = base + s, base + e
            a_doc.append(di)
            a_line.append(ln)
            a_s.append(gs)
            a_e.append(ge)
            a_t.append(TYPE_CODE[kind])
            a_v.append(stored)
            a_c.append(c.removeprefix(PROPN_MARK))
            a_m.append(any(gs < me and ms < ge for ms, me in mk))
            a_h.append(kind not in HASHED_TYPES and stored.startswith("h:"))
            if kind in ("url", "email", "phone"):
                drop.append((s, e))
        for ms, me in mk:
            if ms < base + len(piece) and base < me:
                drop.append((max(0, ms - base), min(len(piece), me - base)))
        g = text_grams(piece, drop)
        if len(g):
            g_doc.append(np.full(len(g), di, dtype=np.int32))
            g_line.append(np.full(len(g), ln, dtype=np.int32))
            g_parts.append(g)
    return {
        "anchors": (a_doc, a_line, a_s, a_e, a_t, a_v, a_c, a_m, a_h),
        "grams": (np.concatenate(g_doc) if g_doc else np.zeros(0, np.int32),
                  np.concatenate(g_line) if g_line else np.zeros(0, np.int32),
                  np.concatenate(g_parts) if g_parts else _EMPTY_I64),
        "lines": line_rows,
    }


def _chunks_by_size(items: list[tuple[int, str]], target_chars: int = 400_000, max_items: int = 3000
                    ) -> list[list[tuple[int, str]]]:
    items = sorted(items, key=lambda x: -len(x[1] or ""))
    out, cur, size = [], [], 0
    for it in items:
        cur.append(it)
        size += len(it[1] or "")
        if size >= target_chars or len(cur) >= max_items:
            out.append(cur)
            cur, size = [], 0
    if cur:
        out.append(cur)
    return out


def extract_texts(docs: list[tuple[int, str]], agent_names: list[str], salt: bytes, n_workers: int,
                  uninformative: frozenset[str], log=print, with_nlp: bool = True) -> dict[str, pl.DataFrame]:
    """E1 over (doc index, text) pairs: anchors, grams and line offsets."""
    chunks = _chunks_by_size(docs)
    parts_a: list[tuple] = []
    parts_g: list[tuple] = []
    lines: list[tuple[int, int, int, int]] = []
    t0 = time.perf_counter()
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(max(1, min(n_workers, len(chunks))), mp_context=ctx, initializer=_init_worker,
                             initargs=(agent_names, salt, with_nlp, uninformative)) as ex:
        for k, res in enumerate(ex.map(_e1_worker, chunks, chunksize=1)):
            parts_a.append(res["anchors"])
            parts_g.append(res["grams"])
            lines.extend(res["lines"])
            if (k + 1) % 50 == 0:
                log(f"E1: {k + 1}/{len(chunks)} chunks, {time.perf_counter() - t0:.0f} s")
    flat = [list(itertools.chain.from_iterable(p[k] for p in parts_a)) for k in range(9)]
    anchors = pl.DataFrame({
        "doc": pl.Series(flat[0], dtype=pl.Int32), "line": pl.Series(flat[1], dtype=pl.Int32),
        "start": pl.Series(flat[2], dtype=pl.Int32), "end": pl.Series(flat[3], dtype=pl.Int32),
        "type": pl.Series(flat[4], dtype=pl.Int8), "stored": pl.Series(flat[5], dtype=pl.String),
        "lemma": pl.Series(flat[6], dtype=pl.String), "masked": pl.Series(flat[7], dtype=pl.Boolean),
        "sens_hashed": pl.Series(flat[8], dtype=pl.Boolean),
    })
    grams = pl.DataFrame({
        "doc": np.concatenate([p[0] for p in parts_g]) if parts_g else np.zeros(0, np.int32),
        "line": np.concatenate([p[1] for p in parts_g]) if parts_g else np.zeros(0, np.int32),
        "gram": np.concatenate([p[2] for p in parts_g]) if parts_g else _EMPTY_I64,
    })
    line_df = pl.DataFrame(lines, schema={"doc": pl.Int32, "line": pl.Int32, "start": pl.Int32, "end": pl.Int32},
                           orient="row")
    log(f"E1: {len(docs):,} docs, {anchors.height:,} anchors, {grams.height:,} line grams in "
        f"{time.perf_counter() - t0:.0f} s")
    return {"anchors": anchors, "grams": grams, "lines": line_df}


# --- helpers ----------------------------------------------------------------------------------------------

def village_day_of(d: date) -> int:
    return (d - VILLAGE_DAY1).days + 1


def own_day_values(d: date, vday: int) -> set[str]:
    """Date values that name the day itself (+/- 1) or its month: known without transmission."""
    out = set()
    for k in (-1, 0, 1):
        x = d + timedelta(days=k)
        out.add(x.isoformat())
        out.add(f"--{x.month:02d}-{x.day:02d}")
        out.add(f"day:{vday + k}")
    out.add(f"{d.year}-{d.month:02d}")
    return out


def ctx_display_fn(common: set[str], salt: bytes):
    cache: dict[str, str] = {}

    def disp(lemma: str) -> str:
        if not lemma:
            return ""
        v = cache.get(lemma)
        if v is None:
            v = cache[lemma] = lemma if lemma in common else keyed_hash(salt, "ctx", lemma, 8)
        return v

    return disp


def key_hash(*parts: str) -> int:
    h = hashlib.blake2b("\x00".join(parts).encode("utf-8", "surrogatepass"), digest_size=8)
    return int.from_bytes(h.digest(), "little", signed=True)


def _paths(cfg: dict, tag: str = "") -> dict[str, Path]:
    d = Path(cfg["paths"]["interim"]) / (B2_DIR + (f"_{tag}" if tag else ""))
    return {"dir": d, "meta": d / "meta.json"}


def _write(df: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(path, compression="zstd")


# --- E2: memory --------------------------------------------------------------------------------------------

def _mem_scan_worker(path: str, rg: int, plan: dict[str, tuple[int, int, int]], cand: np.ndarray
                     ) -> tuple[np.ndarray, np.ndarray]:
    """Rows of one row group that hold candidate grams: (row index, gram) pairs, unique per row."""
    tb = pq.ParquetFile(path).read_row_group(rg, columns=["id", "content"])
    cache: dict[int, np.ndarray] = {}
    rows, grams = [], []
    for rid, text in zip(tb.column("id").to_pylist(), tb.column("content").to_pylist()):
        p = plan.get(rid)
        if p is None:
            continue
        kind, base_len, gidx = p
        if kind == KIND_COPY:
            continue
        _, items = segment_lines(text or "", kind, base_len)
        hits = []
        for h, clean, _ in items:
            got = cache.get(h)
            if got is None:
                g = text_grams(clean)
                got = g[in_sorted(g, cand)] if len(g) else _EMPTY_I64
                cache[h] = got
            if len(got):
                hits.append(got)
        if hits:
            u = np.unique(np.concatenate(hits))
            rows.append(np.full(len(u), gidx, dtype=np.int64))
            grams.append(u)
    if not rows:
        return np.zeros(0, np.int64), _EMPTY_I64
    return np.concatenate(rows), np.concatenate(grams)


def memory_gram_scan(cfg: dict, rows: pl.DataFrame, cand: np.ndarray, n_workers: int, uninformative,
                     log=print) -> pl.DataFrame:
    """(agent_id, gram, first_idx, last_idx) over live memory rows."""
    text_path = Path(cfg["paths"]["tables"]) / "agent_memories_text.parquet"
    pf = pq.ParquetFile(text_path)
    plan_all = {rid: (int(k), int(b), i) for i, (rid, k, b) in
                enumerate(rows.select("id", "kind", "base_len").iter_rows())}
    text_ids = pq.read_table(text_path, columns=["id"]).column("id").to_pylist()
    tasks, start = [], 0
    for g in range(pf.metadata.num_row_groups):
        stop = start + pf.metadata.row_group(g).num_rows
        plan = {x: plan_all[x] for x in text_ids[start:stop] if x in plan_all}
        if plan:
            tasks.append((str(text_path), g, plan))
        start = stop
    t0 = time.perf_counter()
    r_parts, g_parts = [], []
    cand = np.unique(cand)
    with ProcessPoolExecutor(max(1, min(n_workers, len(tasks))), mp_context=mp.get_context("spawn"),
                             initializer=set_uninformative, initargs=(uninformative,)) as ex:
        futs = [ex.submit(_mem_scan_worker, *t, cand) for t in tasks]
        for f in as_completed(futs):
            r, g = f.result()
            r_parts.append(r)
            g_parts.append(g)
    ridx = np.concatenate(r_parts) if r_parts else np.zeros(0, np.int64)
    gram = np.concatenate(g_parts) if g_parts else _EMPTY_I64
    log(f"E2: memory gram scan, {len(tasks)} row groups, {len(ridx):,} row-gram hits in "
        f"{time.perf_counter() - t0:.0f} s")
    info = rows.select(pl.col("agent_id"), pl.col("idx").cast(pl.Int64)).with_row_index("ridx")
    hits = pl.DataFrame({"ridx": ridx, "gram": gram}).with_columns(pl.col("ridx").cast(pl.UInt32))
    hits = hits.join(info, on="ridx", how="left")
    return hits.group_by("agent_id", "gram").agg(pl.col("idx").min().alias("first_idx"),
                                                pl.col("idx").max().alias("last_idx"))


def locate(text: str, type_name: str, stored: str, salt: bytes) -> int:
    """Character position of a typed value in a text (-1 if not found)."""
    low = text.lower()
    if stored.startswith("h:"):
        if type_name == "email":
            for m in _EMAIL.finditer(text):
                if keyed_hash(salt, "email", m.group(0).lower()) == stored:
                    return m.start()
        elif type_name == "phone":
            for m in _PHONE.finditer(text):
                d = re.sub(r"\D", "", m.group(0))
                d = d[1:] if len(d) == 11 and d.startswith("1") else d
                if len(d) >= 10 and keyed_hash(salt, "phone", d) == stored:
                    return m.start()
        elif type_name in ("person", *ENTITY_KINDS):
            for v in name_candidates(text):
                if keyed_hash(salt, type_name, v) == stored:
                    i = low.find(v)
                    return i if i >= 0 else 0
        return -1
    if type_name in QUANTITY_TYPES:
        sv = [stored]
        if type_name == "money" and ":" in stored:
            sv.append(stored.split(":", 1)[1])
        if type_name == "time":
            sv += literal_surfaces("time", stored)
        for s in sv:
            i = low.find(s.lower())
            if i >= 0:
                return i
        return -1
    for sf in literal_surfaces(type_name, stored):
        i = low.find(sf)
        if i >= 0:
            return i
    return -1


def locate_gram(text: str, gram: int) -> int:
    ms = list(_TOK.finditer(text))
    if len(ms) < GRAM_N:
        return -1
    ids = token_ids([m.group(0).lower() for m in ms])
    g = gram_ids_from(ids)
    hit = np.flatnonzero(g == gram)
    return ms[int(hit[0])].start() if len(hit) else -1


# --- E3: turns ------------------------------------------------------------------------------------------------

_MATCH: dict | None = None
_PAIRS: np.ndarray = _EMPTY_I64
_HCACHE: dict[tuple[str, str], str] = {}


def _init_turn_worker(agent_names: list[str], salt: bytes, matcher: dict, uninformative, pairs: np.ndarray) -> None:
    global _EX, _MATCH, _PAIRS
    _EX = AnchorExtractor(agent_names, salt, None)
    _MATCH = matcher
    _PAIRS = pairs
    set_uninformative(uninformative)


def _hashed(kind: str, v: str) -> str:
    key = (kind, v)
    h = _HCACHE.get(key)
    if h is None:
        h = keyed_hash(_EX.salt, kind, v)
        if len(_HCACHE) < 2_000_000:
            _HCACHE[key] = h
    return h


def observation_hits(text: str, m: dict, ex: AnchorExtractor) -> set[int]:
    """Unit indices whose value occurs in an observation text (see E3 in the module docstring)."""
    out: set[int] = set()
    if not text:
        return out
    use_regex = bool(m["url"] or m["date"] or m["quant"] or m["email"] or m["phone"])
    use_names = bool(m["ent"] or m["person"])
    g_sorted, g_unit = m["gram_ids"], m["gram_unit"]
    for line in text.split("\n"):
        if not line.strip():
            continue
        for p0 in range(0, len(line), LINE_CAP):
            piece = line[p0:p0 + LINE_CAP]
            if use_regex:
                found, _ = ex.regex_anchors(piece)
                for s, e, kind, v in found:
                    if kind == "url":
                        out.update(m["url"].get(v, ()))
                    elif kind == "date":
                        out.update(m["date"].get(v, ()))
                    elif kind in QUANTITY_TYPES:
                        for u, lemma in m["quant"].get((TYPE_CODE[kind], v), ()):
                            if lemma and ctx_adjacent(piece, s, e, lemma):
                                out.add(u)
                    elif kind == "email" and m["email"]:
                        out.update(m["email"].get(_hashed("email", v), ()))
                    elif kind == "phone" and m["phone"]:
                        out.update(m["phone"].get(_hashed("phone", v), ()))
            if use_names and any(c.isupper() for c in piece):
                for v in name_candidates(piece):
                    if m["ent"]:
                        out.update(m["ent"].get(v, ()))
                    if m["person"]:
                        out.update(m["person"].get(_hashed("person", v), ()))
            if len(g_sorted):
                g = text_grams(piece)
                if len(g):
                    pos = np.searchsorted(g_sorted, g)
                    pos[pos >= len(g_sorted)] = 0
                    ok = g_sorted[pos] == g
                    for p in pos[ok]:
                        out.update(g_unit[int(p)])
    return out


def _turn_worker(path: str, rg: int, agent_idx: np.ndarray, n_units: int) -> tuple[int, np.ndarray, np.ndarray]:
    tb = pq.ParquetFile(path).read_row_group(rg, columns=["output", "error", "agent_messages"])
    outs = tb.column("output").to_pylist()
    errs = tb.column("error").to_pylist()
    msgs = tb.column("agent_messages").to_pylist()
    rows, units = [], []
    for k in range(len(outs)):
        a = int(agent_idx[k])
        if a < 0:
            continue
        text = "\n".join(x for x in ((outs[k] or "")[:TURN_FIELD_CAP], (errs[k] or "")[:TURN_FIELD_CAP],
                                     narrative_text(msgs[k])) if x)
        hits = observation_hits(text, _MATCH, _EX)
        if not hits:
            continue
        codes = np.array(sorted(a * n_units + u for u in hits), dtype=np.int64)
        keep = codes[in_sorted(codes, _PAIRS)]
        for c in keep:
            rows.append(k)
            units.append(int(c) - a * n_units)
    return rg, np.array(rows, dtype=np.int32), np.array(units, dtype=np.int32)


# --- the build ------------------------------------------------------------------------------------------------

def _docs(cfg: dict, date_range: tuple[date, date] | None) -> pl.DataFrame:
    """Chat messages (agent and human) and search answers with their timing."""
    P = Path(cfg["paths"]["processed"])
    T = Path(cfg["paths"]["tables"])
    eu = pl.scan_parquet(P / "events_unified.parquet")
    base = ["event_uid", "actor_id", "actor_type", "ts_utc", "t_active", "run_day", "village_day", "room_id",
            "search_start_day", "search_end_day"]
    src, kind_, at = (pl.col(c).cast(pl.String) for c in ("source", "kind", "actor_type"))
    chat = eu.filter((src == "chat") & at.is_in(["agent", "human"])).select(*base).collect()
    srch = eu.filter((src == "event") & (kind_ == "search_history")).select(*base).collect()
    if date_range is not None:
        lo, hi = date_range

        def rng(df):
            d = pl.col("ts_utc").dt.convert_time_zone("America/Los_Angeles").dt.date()
            return df.filter((d >= lo) & (d <= hi))

        chat, srch = rng(chat), rng(srch)
    cm = pl.read_parquet(T / "chat_messages.parquet", columns=["id", "content"]).select(
        (pl.lit("chat:") + pl.col("id")).alias("event_uid"), pl.col("content").alias("text"))
    chat = chat.join(cm, on="event_uid", how="inner").with_columns(pl.lit("chat").alias("kind"))
    ids = srch["event_uid"].str.strip_prefix("event:")
    ans = (pl.scan_parquet(T / "events_text.parquet").select("id", "answer")
           .filter(pl.col("id").is_in(ids.implode())).collect()
           .select((pl.lit("event:") + pl.col("id")).alias("event_uid"), pl.col("answer").alias("text")))
    srch = (srch.join(ans, on="event_uid", how="inner")
            .filter(pl.col("text").is_not_null() & (pl.col("text").str.len_chars() >= 40)
                    & ~pl.col("text").str.contains(SEARCH_PLACEHOLDER.pattern))
            .with_columns(pl.lit("search").alias("kind")))
    docs = pl.concat([chat, srch], how="vertical_relaxed").sort("ts_utc", "event_uid")
    docs = docs.with_columns(
        pl.col("ts_utc").dt.convert_time_zone("America/Los_Angeles").dt.date().alias("pt_date"),
        pl.col("actor_type").cast(pl.String),
    ).with_row_index("doc").with_columns(pl.col("doc").cast(pl.Int32))
    return docs


def build_units(cfg: dict, n_workers: int | None = None, *, date_range: tuple[date, date] | None = None,
                tag: str = "", force: bool = False, log=print) -> dict:
    """Run E1-E4 (see the module docstring); returns paths and counts. Cached by stage."""
    lin = cfg.get("lineage", {})
    min_occ = int(lin.get("min_occurrences", 3))
    max_occ = int(lin.get("max_unit_occurrences", 200))
    n_workers = n_workers or int(os.environ.get("SLURM_CPUS_PER_TASK") or os.cpu_count() or 1)
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(var, "1")
    paths = _paths(cfg, tag)
    d = paths["dir"]
    d.mkdir(parents=True, exist_ok=True)
    interim, processed = Path(cfg["paths"]["interim"]), Path(cfg["paths"]["processed"])
    salt = load_salt(interim)
    agents = pl.read_parquet(processed / "agents.parquet")
    agent_names = agents["name"].to_list()
    agent_ids = sorted(agents["agent_id"].to_list())
    a_index = {a: i for i, a in enumerate(agent_ids)}
    uninf = default_uninformative(agent_names)
    set_uninformative(uninf)
    stats: dict = {"version": EXTRACT_VERSION, "date_range": [str(x) for x in date_range] if date_range else None,
                   "min_occurrences": min_occ, "max_unit_occurrences": max_occ}
    t_all = time.perf_counter()

    # --- E1 -------------------------------------------------------------------------------------
    docs = _docs(cfg, date_range)
    e1_ok = (not force and (d / "e1_anchors.parquet").exists() and (d / "e1_docs.parquet").exists()
             and pl.read_parquet(d / "e1_docs.parquet", columns=["event_uid"])["event_uid"].to_list()
             == docs["event_uid"].to_list())
    if e1_ok:
        log("E1: cache hit")
        anchors = pl.read_parquet(d / "e1_anchors.parquet")
        grams = pl.read_parquet(d / "e1_grams.parquet")
        lines = pl.read_parquet(d / "e1_lines.parquet")
    else:
        e1 = extract_texts(list(zip(docs["doc"].to_list(), docs["text"].to_list())), agent_names, salt,
                           n_workers, uninf, log)
        anchors, grams, lines = e1["anchors"], e1["grams"], e1["lines"]
        _write(docs.drop("text"), d / "e1_docs.parquet")
        _write(anchors, d / "e1_anchors.parquet")
        _write(grams, d / "e1_grams.parquet")
        _write(lines, d / "e1_lines.parquet")
    stats["docs"] = {k: int(v) for k, v in docs.group_by("kind").len().iter_rows()}
    stats["e1_anchors"] = anchors.height
    stats["e1_line_grams"] = grams.height

    # --- S1: typed units --------------------------------------------------------------------------
    t = time.perf_counter()
    mf_path = interim / "memory_facts.parquet"
    mf = pl.scan_parquet(mf_path)
    common = set(mf.select(pl.col("ctx").unique()).collect()["ctx"].drop_nulls().to_list())
    common = {c for c in common if c and not c.startswith("h:")}
    disp = ctx_display_fn(common, salt)
    dmeta = docs.select("doc", "event_uid", "kind", "actor_id", "actor_type", "pt_date", "village_day")
    a = anchors.join(dmeta, on="doc", how="left")
    excl_types = [TYPE_CODE[x] for x in EXCLUDED_TYPES]
    a = a.filter(~pl.col("type").is_in(excl_types) & ~pl.col("masked") & ~pl.col("sens_hashed"))
    a = a.filter(~(pl.col("type").is_in(list(QUANTITY_CODES)) & (pl.col("lemma") == "")))
    # Own-day dates.
    dd = a.filter(pl.col("type") == DATE_CODE).select("doc", "stored", "pt_date", "village_day").unique()
    own = [s in own_day_values(pd_, int(vd) if vd is not None else village_day_of(pd_))
           for s, pd_, vd in dd.select("stored", "pt_date", "village_day").iter_rows()]
    drop_dates = dd.filter(pl.Series(own, dtype=pl.Boolean)).select("doc", "stored").with_columns(
        pl.lit(DATE_CODE, dtype=pl.Int8).alias("type"), pl.lit(True).alias("_own"))
    a = (a.join(drop_dates, on=["doc", "type", "stored"], how="left")
         .filter(pl.col("_own").is_null()).drop("_own"))
    combos = a.select("type", "stored", "lemma").unique()
    keys = []
    for tc, sv, lm in combos.iter_rows():
        c = disp(lm) if tc in QUANTITY_CODES else ""
        keys.append((tc, sv, lm, _stable_key(int(tc), sv, c), c))
    kdf = pl.DataFrame(keys, schema={"type": pl.Int8, "stored": pl.String, "lemma": pl.String,
                                     "unit_id": pl.Int64, "ctx": pl.String}, orient="row")
    a = a.join(kdf, on=["type", "stored", "lemma"], how="left")
    text_occ = (a.group_by("doc", "unit_id").agg(pl.col("start").min().alias("pos"), pl.col("line").min()
                                                 .alias("line"))
                .join(dmeta, on="doc", how="left"))
    lemma_of = (a.filter(pl.col("type").is_in(list(QUANTITY_CODES)))
                .group_by("unit_id").agg(pl.col("lemma").mode().first().alias("lemma")))
    tinfo = (a.group_by("unit_id").agg(pl.col("type").first(), pl.col("stored").first(), pl.col("ctx").first()))

    # Memory occurrences (B1 presence spells).
    mf0 = (mf.filter(pl.col("spell") == 0)
           .select("agent_id", pl.col("unit_key").alias("unit_id"), "anchor_type", "value", "ctx",
                   pl.col("spell_start_row_id").alias("mem_row"), pl.col("spell_start_ts").alias("ts_utc"))
           .collect())
    if date_range is not None:
        dloc = pl.col("ts_utc").dt.convert_time_zone("America/Los_Angeles").dt.date()
        mf0 = mf0.filter((dloc >= date_range[0]) & (dloc <= date_range[1]))
    mf0 = mf0.filter(~pl.col("anchor_type").is_in(list(EXCLUDED_TYPES)))
    mf0 = mf0.filter(~(pl.col("anchor_type").is_in(list(QUANTITY_TYPES)) & (pl.col("ctx") == "")))
    mf0 = mf0.filter(~(~pl.col("anchor_type").is_in(list(HASHED_TYPES)) & pl.col("value").str.starts_with("h:")))
    mdate = mf0.filter(pl.col("anchor_type") == "date").with_columns(
        pl.col("ts_utc").dt.convert_time_zone("America/Los_Angeles").dt.date().alias("pt_date"))
    own_m = [v in own_day_values(pd_, village_day_of(pd_)) for v, pd_ in mdate.select("value", "pt_date").iter_rows()]
    bad = mdate.filter(pl.Series(own_m, dtype=pl.Boolean)).select("agent_id", "unit_id")
    mf0 = mf0.join(bad, on=["agent_id", "unit_id"], how="anti")
    log(f"S1: text anchor occurrences {text_occ.height:,}; memory first appearances {mf0.height:,} "
        f"({time.perf_counter() - t:.0f} s)")

    def counts(occ_text: pl.DataFrame, occ_mem: pl.DataFrame) -> pl.DataFrame:
        tx = occ_text.select("unit_id", "kind", "actor_id", "actor_type")
        mm = occ_mem.select("unit_id", pl.lit("memory").alias("kind"), "agent_id").rename(
            {"agent_id": "actor_id"}).with_columns(pl.lit("agent").alias("actor_type"))
        allo = pl.concat([tx, mm], how="vertical_relaxed")
        return allo.group_by("unit_id").agg(
            (pl.col("kind") == "chat").sum().alias("n_chat"),
            (pl.col("kind") == "search").sum().alias("n_search"),
            (pl.col("kind") == "memory").sum().alias("n_memory"),
            (pl.col("actor_type") == "human").sum().alias("n_human"),
            pl.col("actor_id").filter(pl.col("actor_type") == "agent").n_unique().alias("n_agents"),
            pl.len().alias("n_occ"),
        )

    ct = counts(text_occ, mf0)
    stats["typed_candidates"] = ct.height

    def select(c: pl.DataFrame) -> pl.DataFrame:
        return c.filter((pl.col("n_chat") >= 1) & (pl.col("n_occ") >= min_occ) & (pl.col("n_agents") >= 2)
                        & (pl.col("n_occ") <= max_occ))

    stats["typed_size_excluded"] = int(ct.filter((pl.col("n_chat") >= 1) & (pl.col("n_agents") >= 2)
                                                 & (pl.col("n_occ") > max_occ)).height)
    typed = select(ct).join(tinfo, on="unit_id", how="left").join(lemma_of, on="unit_id", how="left")
    typed = typed.with_columns(pl.lit("typed").alias("unit_kind"),
                               pl.col("type").map_elements(lambda x: TYPES[x], return_dtype=pl.String)
                               .alias("anchor_type"))
    log(f"S1: typed units selected {typed.height:,} of {ct.height:,} candidates")

    # --- G: 4-gram candidates ------------------------------------------------------------------------
    t = time.perf_counter()
    chat_docs = docs.filter(pl.col("kind") == "chat").select(
        "doc", pl.when(pl.col("actor_type") == "human").then(pl.lit("human")).otherwise(pl.col("actor_id"))
        .alias("speaker"))
    cg = grams.join(chat_docs, on="doc", how="inner").select("doc", "gram", "speaker").unique(["doc", "gram"])
    gc = cg.group_by("gram").agg(pl.len().alias("n_msgs"), pl.col("speaker").n_unique().alias("n_speakers"))
    common_grams = np.sort(gc.filter(pl.col("n_msgs") >= RARE_MAX_MSGS)["gram"].to_numpy())
    np.save(d / "common_grams.npy", common_grams)
    cand_g = gc.filter((pl.col("n_msgs") >= GRAM_UNIT_MIN_MSGS) & (pl.col("n_msgs") < RARE_MAX_MSGS)
                       & (pl.col("n_speakers") >= 2))
    sig = (cg.join(cand_g.select("gram"), on="gram", how="semi").sort("doc")
           .group_by("gram").agg(pl.col("doc").sort().alias("docs")))
    sig = sig.with_columns(pl.col("docs").cast(pl.List(pl.String)).list.join(",").alias("_sig"))
    reps = sig.group_by("_sig").agg(pl.col("gram").min().alias("gram"), pl.len().alias("n_grams"))
    rep_grams = np.sort(reps["gram"].to_numpy())
    stats["gram_candidates"] = {"grams": int(cand_g.height), "units": int(reps.height)}
    log(f"G: {cand_g.height:,} candidate grams in {reps.height:,} message sets ({time.perf_counter() - t:.0f} s)")

    # --- E2: memory -----------------------------------------------------------------------------------
    t = time.perf_counter()
    # Live rows of the full history (consolidation counts and bases need every row); a pilot range
    # only limits which rows are scanned.
    rows, _ = live_rows(pl.read_parquet(interim / "memory_versions.parquet"))
    rows_scan = rows
    if date_range is not None:
        dloc = pl.col("created_at").dt.convert_time_zone("America/Los_Angeles").dt.date()
        rows_scan = rows.filter((dloc >= date_range[0]) & (dloc <= date_range[1]))
    scan_path = d / "e2_mem_grams.parquet"
    if not force and scan_path.exists() and (d / "e2_cand.npy").exists() and \
            np.array_equal(np.load(d / "e2_cand.npy"), rep_grams):
        mem_g = pl.read_parquet(scan_path)
        log("E2: memory gram scan cache hit")
    else:
        mem_g = memory_gram_scan(cfg, rows_scan, rep_grams, n_workers, uninf, log)
        _write(mem_g, scan_path)
        np.save(d / "e2_cand.npy", rep_grams)
    rows_t = rows.select("id", "agent_id", pl.col("idx").cast(pl.Int64), "created_at", "is_cons", "kind",
                         "base_len")
    mem_g = (mem_g.join(rows_t.select("agent_id", pl.col("idx").alias("first_idx"), pl.col("id").alias("mem_row"),
                                      pl.col("created_at").alias("ts_utc")), on=["agent_id", "first_idx"],
                        how="left"))
    # Presence end: the first consolidation after the last row that holds the gram.
    cons = rows_t.filter(pl.col("is_cons")).select("agent_id", pl.col("idx").alias("c_idx"),
                                                   pl.col("created_at").alias("c_ts")).sort("c_idx")
    mem_g = (mem_g.sort("last_idx")
             .join_asof(cons, left_on="last_idx", right_on="c_idx", by="agent_id", strategy="forward",
                        allow_exact_matches=False)
             .rename({"c_ts": "gram_end_ts"}).drop("c_idx"))
    log(f"E2: {mem_g.height:,} agent-gram first appearances ({time.perf_counter() - t:.0f} s)")

    # Gram unit occurrences.
    rep_map = sig.join(reps.select("_sig", pl.col("gram").alias("unit_gram")), on="_sig").select("gram", "unit_gram")
    g_chat = (cg.join(rep_map, on="gram", how="inner").select("doc", pl.col("unit_gram").alias("unit_id"))
              .unique().join(dmeta, on="doc", how="left"))
    sg = grams.join(docs.filter(pl.col("kind") == "search").select("doc"), on="doc", how="semi")
    g_srch = (sg.filter(pl.col("gram").is_in(rep_grams)).group_by("doc", "gram").agg(pl.col("line").min())
              .select("doc", pl.col("gram").alias("unit_id"), "line").join(dmeta, on="doc", how="left"))
    g_mem = mem_g.select("agent_id", pl.col("gram").alias("unit_id"), "mem_row", "ts_utc", "gram_end_ts")
    gtext = pl.concat([g_chat.with_columns(pl.lit(None, pl.Int32).alias("line")).select(g_srch.columns),
                       g_srch], how="vertical_relaxed")
    cgc = counts(gtext, g_mem)
    gsel = select(cgc).with_columns(pl.lit("gram").alias("unit_kind"), pl.lit("gram").alias("anchor_type"))
    stats["gram_size_excluded"] = int(cgc.filter((pl.col("n_chat") >= 1) & (pl.col("n_agents") >= 2)
                                                 & (pl.col("n_occ") > max_occ)).height)
    log(f"S2: gram units selected {gsel.height:,} of {cgc.height:,}")
    clash = set(typed["unit_id"].to_list()) & set(gsel["unit_id"].to_list())
    if clash:
        raise ValueError(f"{len(clash)} unit ids are shared by a typed unit and a gram unit")

    # --- unit table and occurrences ------------------------------------------------------------------
    units = pl.concat([
        typed.select("unit_id", "unit_kind", "anchor_type", pl.col("stored").alias("value"), "ctx", "lemma",
                     "n_chat", "n_search", "n_memory", "n_human", "n_agents", "n_occ"),
        gsel.select("unit_id", "unit_kind", "anchor_type", pl.lit(None, pl.String).alias("value"),
                    pl.lit("").alias("ctx"), pl.lit("").alias("lemma"), "n_chat", "n_search", "n_memory",
                    "n_human", "n_agents", "n_occ"),
    ], how="vertical_relaxed").sort("unit_id").with_row_index("uidx").with_columns(pl.col("uidx").cast(pl.Int32))
    units = units.with_columns(pl.struct("anchor_type", "value").map_elements(
        lambda r: url_domain(r["value"]) if r["anchor_type"] == "url" and r["value"] else None,
        return_dtype=pl.String).alias("domain"))
    sel_ids = units.select("unit_id")
    t_occ = pl.concat([
        text_occ.join(sel_ids, on="unit_id", how="semi").select("doc", "unit_id", "line", "pos"),
        gtext.join(gsel.select("unit_id"), on="unit_id", how="semi").select(
            "doc", "unit_id", "line", pl.lit(None, pl.Int32).alias("pos")),
    ], how="vertical_relaxed").unique(["doc", "unit_id"])
    m_occ = pl.concat([
        mf0.join(typed.select("unit_id"), on="unit_id", how="semi").select(
            "agent_id", "unit_id", "mem_row", "ts_utc", pl.lit(None, pl.Datetime("us", "UTC")).alias("gram_end_ts")),
        g_mem.join(gsel.select("unit_id"), on="unit_id", how="semi").select(
            "agent_id", "unit_id", "mem_row", "ts_utc", "gram_end_ts"),
    ], how="vertical_relaxed")
    stats["units"] = {k: int(v) for k, v in units.group_by("unit_kind").len().iter_rows()}
    stats["units_by_type"] = {k: int(v) for k, v in units.group_by("anchor_type").len().iter_rows()}
    stats["occurrences"] = {"text": t_occ.height, "memory": m_occ.height}

    # --- memory presence per rule version (typed) ------------------------------------------------------
    t = time.perf_counter()
    presence = memory_presence(cfg, rows_t, m_occ, typed.select("unit_id"), date_range)
    _write(presence, d / "mem_presence.parquet")
    log(f"memory presence for {presence.height:,} agent-units ({time.perf_counter() - t:.0f} s)")

    # --- E2b + E4: windows and features --------------------------------------------------------------
    t = time.perf_counter()
    common_g = common_grams
    feats_t = text_features(docs, t_occ, units, anchors, grams, lines, common_g, disp, salt)
    feats_m = memory_features(cfg, rows_t, m_occ, units, common_g, disp, salt, n_workers, log)
    log(f"E4: features for {feats_t.height:,} text and {feats_m.height:,} memory occurrences "
        f"({time.perf_counter() - t:.0f} s)")
    occ_text = (t_occ.join(docs.drop("text"), on="doc", how="left")
                .join(feats_t, on=["doc", "unit_id"], how="left")
                .select(pl.col("event_uid").str.replace(r"^event:", "search:").alias("occ_uid"), "unit_id",
                        pl.col("kind").alias("src"), "actor_id", "actor_type", "ts_utc", "t_active", "run_day",
                        "village_day", "room_id", "search_start_day", "search_end_day",
                        pl.col("event_uid").alias("doc_uid"), "qv_key", "qv_val", "grams", "win"))
    occ_text = occ_text.with_columns(
        pl.when(pl.col("actor_type") == "human").then(pl.lit("human")).otherwise(pl.col("actor_id")).alias("actor_id"))
    mem_time = (pl.scan_parquet(processed / "events_unified.parquet").filter(pl.col("source").cast(pl.String) == "memory")
                .select(pl.col("event_uid").str.strip_prefix("memory:").alias("mem_row"), "t_active", "run_day",
                        "village_day").collect())
    occ_mem = (m_occ.join(mem_time, on="mem_row", how="left")
               .join(feats_m, on=["agent_id", "unit_id"], how="left")
               .select((pl.lit("memory:") + pl.col("mem_row") + pl.lit("#") + pl.col("unit_id").cast(pl.String))
                       .alias("occ_uid"), "unit_id", pl.lit("memory").alias("src"),
                       pl.col("agent_id").alias("actor_id"), pl.lit("agent").alias("actor_type"), "ts_utc",
                       "t_active", "run_day", "village_day", pl.lit(None, pl.String).alias("room_id"),
                       pl.lit(None, pl.Int32).alias("search_start_day"), pl.lit(None, pl.Int32).alias("search_end_day"),
                       (pl.lit("memory:") + pl.col("mem_row")).alias("doc_uid"), "qv_key", "qv_val", "grams", "win"))
    occ = pl.concat([occ_text, occ_mem], how="vertical_relaxed").join(
        units.select("unit_id", "uidx"), on="unit_id", how="left").sort("unit_id", "ts_utc", "occ_uid")
    _write(units, d / "units.parquet")
    _write(occ, d / "occurrences.parquet")
    stats["occ_rows"] = occ.height
    stats["occ_by_src"] = {k: int(v) for k, v in occ.group_by("src").len().iter_rows()}

    # --- E3: turns ----------------------------------------------------------------------------------
    t = time.perf_counter()
    env = turn_scan(cfg, units, occ, lemma_lookup(units), a_index, agent_names, salt, n_workers, uninf,
                    date_range, log)
    _write(env, d / "env_hits.parquet")
    stats["env_hits"] = env.height
    log(f"E3: {env.height:,} env hits ({time.perf_counter() - t:.0f} s)")
    stats["seconds"] = round(time.perf_counter() - t_all, 1)
    paths["meta"].write_text(json.dumps(stats, indent=1, default=str))
    return {"dir": str(d), "stats": stats}


def lemma_lookup(units: pl.DataFrame) -> dict[int, str]:
    return {int(u): (lm or "") for u, lm in units.select("uidx", "lemma").iter_rows()}


# --- memory presence ---------------------------------------------------------------------------------------

def memory_presence(cfg: dict, rows_t: pl.DataFrame, m_occ: pl.DataFrame, typed_ids: pl.DataFrame,
                    date_range=None) -> pl.DataFrame:
    """Per (agent, unit): entry time, end of presence under rules v1, v2 and v3 (B1 first loss; null
    if never lost) and B1's later anchor spells (restorations). Gram units end where the gram does."""
    interim = Path(cfg["paths"]["interim"])
    pairs = m_occ.select("agent_id", "unit_id", "ts_utc", "gram_end_ts")
    typed_pairs = pairs.join(typed_ids, on="unit_id", how="semi")
    cons = rows_t.filter(pl.col("is_cons")).sort("agent_id", "idx").with_columns(
        pl.int_range(1, pl.len() + 1).over("agent_id").alias("c_no"))
    cons_upto = rows_t.sort("agent_id", "idx").with_columns(
        pl.col("is_cons").cast(pl.Int32).cum_sum().over("agent_id").alias("entry_cons"))
    out = typed_pairs.select("agent_id", "unit_id", pl.col("ts_utc").alias("entry_ts"))
    for ver, fname in (("v1", "memory_facts.parquet"), ("v2", "memory_facts_v2.parquet"),
                       ("v3", "memory_facts_v3.parquet")):
        p = interim / fname
        if not p.exists():
            out = out.with_columns(pl.lit(None, pl.Datetime("us", "UTC")).alias(f"end_{ver}"))
            continue
        f = (pl.scan_parquet(p).filter(pl.col("spell") == 0)
             .select("agent_id", pl.col("unit_key").alias("unit_id"), "spell_start_row_id", "survived", "lost_event")
             .collect().join(typed_pairs.select("agent_id", "unit_id"), on=["agent_id", "unit_id"], how="semi"))
        f = (f.join(cons_upto.select("agent_id", pl.col("id").alias("spell_start_row_id"), "entry_cons"),
                    on=["agent_id", "spell_start_row_id"], how="left")
             .with_columns(pl.when(pl.col("lost_event") != "none")
                           .then(pl.col("entry_cons") + pl.col("survived") + 1).alias("c_no"))
             .join(cons.select("agent_id", "c_no", pl.col("created_at").alias(f"end_{ver}")),
                   on=["agent_id", "c_no"], how="left"))
        out = out.join(f.select("agent_id", "unit_id", f"end_{ver}"), on=["agent_id", "unit_id"], how="left")
    sp = (pl.scan_parquet(interim / "memory_facts.parquet").filter(pl.col("spell") >= 1)
          .select("agent_id", pl.col("unit_key").alias("unit_id"), "spell_start_ts", "spell_end_ts").collect()
          .join(typed_pairs.select("agent_id", "unit_id"), on=["agent_id", "unit_id"], how="semi")
          .sort("spell_start_ts")
          .group_by("agent_id", "unit_id").agg(pl.col("spell_start_ts").alias("restore_start"),
                                               pl.col("spell_end_ts").alias("restore_end")))
    out = out.join(sp, on=["agent_id", "unit_id"], how="left")
    grams_p = (pairs.join(typed_ids, on="unit_id", how="anti")
               .select("agent_id", "unit_id", pl.col("ts_utc").alias("entry_ts"),
                       *[pl.col("gram_end_ts").alias(f"end_{v}") for v in ("v1", "v2", "v3")]))
    return pl.concat([out, grams_p], how="diagonal_relaxed")


# --- E4 features ------------------------------------------------------------------------------------------

def _qv(types, lemmas, values, disp) -> tuple[list[int], list[int]]:
    ks, vs = [], []
    for tc, lm, v in zip(types, lemmas, values):
        if tc in QUANTITY_CODES and lm:
            ks.append(key_hash(TYPES[tc], disp(lm)))
            vs.append(key_hash(v))
    return ks, vs


def _rare(g: np.ndarray, common: np.ndarray) -> list[int]:
    """Grams not in the sorted array of common grams (5 or more chat messages)."""
    if not len(g):
        return []
    return g[~in_sorted(g, common)].tolist()


def _doc_tokens(text: str) -> tuple[np.ndarray, np.ndarray]:
    ms = list(_TOK.finditer(text))
    starts = np.fromiter((m.start() for m in ms), dtype=np.int64, count=len(ms))
    return starts, token_ids([m.group(0).lower() for m in ms])


def _window(starts: np.ndarray, ids: np.ndarray, center: int, width: int = WINDOW_TOKENS) -> list[int]:
    if not len(ids):
        return []
    k = max(int(np.searchsorted(starts, center, side="right")) - 1, 0)
    return ids[max(0, k - width):min(len(ids), k + width + 1)].view(np.int64).tolist()


def _gram_pos(starts: np.ndarray, ids: np.ndarray, gram: int) -> int:
    if len(ids) < GRAM_N:
        return -1
    hit = np.flatnonzero(gram_ids_from(ids) == gram)
    return int(starts[hit[0]]) if len(hit) else -1


def text_features(docs, t_occ, units, anchors, grams, lines, common, disp, salt) -> pl.DataFrame:
    """Features of chat (whole message) and search (line of the first match +/- 1) windows."""
    uinfo = {int(u): k for u, k in units.select("unit_id", "unit_kind").iter_rows()}
    need = t_occ.select("doc", "unit_id", "line", "pos").sort("doc")
    need_docs = need["doc"].unique().implode()
    dd = docs.filter(pl.col("doc").is_in(need_docs)).select("doc", "kind", "text")
    an = (anchors.filter(pl.col("doc").is_in(need_docs) & pl.col("type").is_in(list(QUANTITY_CODES))
                         & ~pl.col("masked") & ~pl.col("sens_hashed") & (pl.col("lemma") != ""))
          .group_by("doc").agg("line", "type", "lemma", "stored"))
    an_map = {r[0]: r[1:] for r in an.iter_rows()}
    gr = grams.filter(pl.col("doc").is_in(need_docs)).group_by("doc").agg("line", "gram")
    gr_map = {r[0]: (np.array(r[1], dtype=np.int32), np.array(r[2], dtype=np.int64)) for r in gr.iter_rows()}
    ln = lines.filter(pl.col("doc").is_in(need_docs)).group_by("doc").agg("line", "start")
    ln_map = {r[0]: dict(zip(r[1], r[2])) for r in ln.iter_rows()}
    by_doc: dict[int, list] = defaultdict(list)
    for doc, uid, line, pos in need.iter_rows():
        by_doc[doc].append((uid, line, pos))
    rows = []
    for doc, kind, text in dd.iter_rows():
        text = text or ""
        starts, ids = _doc_tokens(text)
        a = an_map.get(doc)
        g = gr_map.get(doc)
        cache: dict = {}

        def feats(wl):
            key = None if wl is None else tuple(sorted(wl))
            if key in cache:
                return cache[key]
            if a is not None:
                ls, ts, lms, svs = a
                keep = [k for k in range(len(ls)) if wl is None or ls[k] in wl]
                qk, qv = _qv([ts[k] for k in keep], [lms[k] for k in keep], [svs[k] for k in keep], disp)
            else:
                qk, qv = [], []
            if g is not None:
                gl, gg = g
                gsel = gg if wl is None else gg[np.isin(gl, list(wl))]
                rare = _rare(np.unique(gsel), common)
            else:
                rare = []
            cache[key] = (qk, qv, rare)
            return cache[key]

        for uid, line, pos in by_doc.get(doc, ()):
            if uinfo[int(uid)] == "gram":
                p = _gram_pos(starts, ids, int(uid))
                if line is None and p >= 0:
                    line = text.count("\n", 0, p)
            else:
                p = int(pos) if pos is not None else -1
            wl = {line - 1, line, line + 1} if (kind == "search" and line is not None) else None
            qk, qv, rare = feats(wl)
            if p < 0 and line is not None:
                p = ln_map.get(doc, {}).get(line, 0)
            rows.append((doc, uid, qk, qv, rare, _window(starts, ids, max(p, 0))))
    return pl.DataFrame(rows, schema={"doc": pl.Int32, "unit_id": pl.Int64, "qv_key": pl.List(pl.Int64),
                                      "qv_val": pl.List(pl.Int64), "grams": pl.List(pl.Int64),
                                      "win": pl.List(pl.Int64)}, orient="row")


_COMMON: np.ndarray = _EMPTY_I64
_SALT = b""


def _init_mem_worker(common: np.ndarray, salt: bytes, uninformative) -> None:
    global _COMMON, _SALT
    _COMMON, _SALT = common, salt
    set_uninformative(uninformative)


def _mem_window_worker(path: str, rg: int, todo: dict[str, tuple[int, int, list]]) -> list[tuple]:
    """Windows of the memory occurrences whose entry rows are in one row group.

    todo: row id -> (kind, base_len, [(agent, unit id, unit kind, type, value, line positions)]);
    positions index the raw lines of the row's own segment (B1), None for gram units."""
    tb = pq.ParquetFile(path).read_row_group(rg, columns=["id", "content"])
    out = []
    for rid, text in zip(tb.column("id").to_pylist(), tb.column("content").to_pylist()):
        job = todo.get(rid)
        if job is None:
            continue
        kind, base_len, occs = job
        text = text or ""
        seg_start = text.rfind("\n", 0, int(base_len)) + 1 if (int(kind) == 1 and base_len) else 0
        raw = text[seg_start:].split("\n")
        line_grams: dict[int, set] = {}
        for agent, uid, ukind, atype, val, pick in occs:
            if pick is None:
                pick = []
                for i, ln_ in enumerate(raw):
                    if len(pick) >= 3:
                        break
                    if i not in line_grams:
                        c = clean_line(ln_)
                        line_grams[i] = set(text_grams(c).tolist()) if c else set()
                    if uid in line_grams[i]:
                        pick.append(i)
            pick = [i for i in pick if i < len(raw)]
            wtext = "\n".join(raw[i] for i in pick)
            if not wtext:
                out.append((agent, uid, pick, [], []))
                continue
            starts, ids = _doc_tokens(wtext)
            p = locate(wtext, atype, val, _SALT) if ukind == "typed" else _gram_pos(starts, ids, uid)
            out.append((agent, uid, pick, _rare(text_grams(wtext), _COMMON), _window(starts, ids, max(p, 0))))
    return out


def memory_features(cfg, rows_t, m_occ, units, common, disp, salt, n_workers, log) -> pl.DataFrame:
    """Window of each memory occurrence: the lines of its entry row that carry the unit.

    Typed units: the row's own segment lines (B1 cache `row_segments`) whose B1 line anchors hold
    the unit; gram units: the segment lines whose grams hold the gram (found while reading the row)."""
    cp = _cache_paths(cfg)
    uinfo = {int(u): (k, at, v, c) for u, k, at, v, c in
             units.select("unit_id", "unit_kind", "anchor_type", "value", "ctx").iter_rows()}
    need = m_occ.join(rows_t.select(pl.col("id").alias("mem_row"), "kind", "base_len"), on="mem_row", how="left")
    need = need.filter(pl.col("mem_row").is_not_null() & pl.col("kind").is_not_null())
    seg_idx = pl.read_parquet(cp["rows"]).filter(pl.col("id").is_in(need["mem_row"].unique().implode()))
    flat = np.load(cp["flat"], mmap_mode="r")
    segs = {rid: np.asarray(flat[st:st + ln]) for rid, st, ln in seg_idx.iter_rows()}
    all_h = np.unique(np.concatenate(list(segs.values()))) if segs else _EMPTY_I64
    all_h = all_h[all_h != 0]
    la_sub = (pl.scan_parquet(cp["anchors"]).filter(pl.col("line_hash").is_in(pl.Series(all_h).implode()))
              .with_columns(pl.col("ctx").str.strip_prefix(PROPN_MARK).alias("lemma"))
              .select("line_hash", "type", pl.col("value").alias("stored"), "lemma").collect())
    lem = la_sub.select("lemma").unique()
    lem = lem.with_columns(pl.Series("_d", [disp(x) for x in lem["lemma"].to_list()], dtype=pl.String))
    la_sub = la_sub.join(lem, on="lemma", how="left").with_columns(
        pl.when(pl.col("type").is_in(list(QUANTITY_CODES))).then(pl.col("_d")).otherwise(pl.lit("")).alias("_c"))
    # (line hash, unit) pairs for typed units.
    tv = units.filter(pl.col("unit_kind") == "typed").select(
        pl.col("anchor_type").replace_strict(TYPE_CODE, return_dtype=pl.Int8).alias("type"),
        pl.col("value").alias("stored"), "unit_id", pl.col("ctx").alias("_c"))
    carry = la_sub.join(tv, on=["type", "stored", "_c"], how="inner").select("line_hash", "unit_id").unique()
    carry_set = set(zip(carry["line_hash"].to_list(), carry["unit_id"].to_list()))
    by_row: dict[str, list] = defaultdict(list)
    row_kind: dict[str, tuple[int, int]] = {}
    for agent, uid, row, kind, base_len in need.select("agent_id", "unit_id", "mem_row", "kind", "base_len").iter_rows():
        ukind, atype, val, _c = uinfo[int(uid)]
        if ukind == "typed":
            sg = segs.get(row)
            pick = [] if sg is None else [i for i, h in enumerate(sg.tolist()) if h and (h, int(uid)) in carry_set][:3]
        else:
            pick = None
        by_row[row].append((agent, int(uid), ukind, atype, val, pick))
        row_kind[row] = (int(kind), int(base_len or 0))
    text_path = Path(cfg["paths"]["tables"]) / "agent_memories_text.parquet"
    pf = pq.ParquetFile(text_path)
    text_ids = pq.read_table(text_path, columns=["id"]).column("id").to_pylist()
    tasks, start = [], 0
    for g in range(pf.metadata.num_row_groups):
        stop = start + pf.metadata.row_group(g).num_rows
        todo = {x: (*row_kind[x], by_row[x]) for x in text_ids[start:stop] if x in by_row}
        if todo:
            tasks.append((str(text_path), g, todo))
        start = stop
    per: list[tuple] = []
    with ProcessPoolExecutor(max(1, min(n_workers, len(tasks))), mp_context=mp.get_context("spawn"),
                             initializer=_init_mem_worker, initargs=(common, salt, _UNINFORMATIVE)) as ex:
        for f in as_completed([ex.submit(_mem_window_worker, *t) for t in tasks]):
            per.extend(f.result())
    row_of = {(a, u): r for r, occs in by_row.items() for a, u, *_ in occs}
    q = (la_sub.filter(pl.col("type").is_in(list(QUANTITY_CODES)) & (pl.col("lemma") != "")
                       & ~pl.col("stored").str.starts_with("h:"))
         .group_by("line_hash").agg("type", "lemma", "stored"))
    qmap = {int(h): (t_, l_, s_) for h, t_, l_, s_ in q.iter_rows()}
    rows, n_lines = [], 0
    for agent, uid, pick, rare, win in per:
        sg = segs.get(row_of.get((agent, uid)))
        wh = [int(sg[i]) for i in pick if sg is not None and i < len(sg) and sg[i] != 0]
        n_lines += bool(pick)
        ts, lms, svs = [], [], []
        for h in wh:
            x = qmap.get(h)
            if x:
                ts += x[0]
                lms += x[1]
                svs += x[2]
        qk, qv = _qv(ts, lms, svs, disp)
        rows.append((agent, uid, qk, qv, rare, win))
    log(f"E2b: windows for {len(rows):,} memory occurrences; {n_lines:,} with lines")
    return pl.DataFrame(rows, schema={"agent_id": pl.String, "unit_id": pl.Int64, "qv_key": pl.List(pl.Int64),
                                      "qv_val": pl.List(pl.Int64), "grams": pl.List(pl.Int64),
                                      "win": pl.List(pl.Int64)}, orient="row")


# --- E3 driver ---------------------------------------------------------------------------------------------

def build_matcher(units: pl.DataFrame, lemmas: dict[int, str]) -> dict:
    m: dict = {"url": defaultdict(list), "date": defaultdict(list), "quant": defaultdict(list),
               "ent": defaultdict(list), "person": defaultdict(list), "email": defaultdict(list),
               "phone": defaultdict(list)}
    g_ids, g_units = [], []
    for uidx, kind, atype, val, uid in units.select("uidx", "unit_kind", "anchor_type", "value", "unit_id").iter_rows():
        uidx = int(uidx)
        if kind == "gram":
            g_ids.append(int(uid))
            g_units.append(uidx)
            continue
        if atype == "url":
            m["url"][val].append(uidx)
        elif atype == "date":
            m["date"][val].append(uidx)
        elif atype in QUANTITY_TYPES:
            m["quant"][(TYPE_CODE[atype], val)].append((uidx, lemmas.get(uidx, "")))
        elif atype in ENTITY_KINDS:
            m["ent"][val].append(uidx)
        elif atype in ("person", "email", "phone"):
            m[atype][val].append(uidx)
    gid = np.array(g_ids, dtype=np.int64)
    order = np.argsort(gid, kind="stable")
    if len(gid) and len(np.unique(gid)) != len(gid):
        raise ValueError("gram unit ids are not unique")
    m["gram_ids"] = gid[order]
    m["gram_unit"] = [(g_units[i],) for i in order]
    return {k: (dict(v) if isinstance(v, defaultdict) else v) for k, v in m.items()}


def turn_scan(cfg, units, occ, lemmas, a_index, agent_names, salt, n_workers, uninf, date_range, log) -> pl.DataFrame:
    """E3: env hits (agent_id, unit_id, ts_utc, t_active, turn_uid)."""
    processed, tables = Path(cfg["paths"]["processed"]), Path(cfg["paths"]["tables"])
    n_units = units.height
    matcher = build_matcher(units, lemmas)
    ag = occ.filter(pl.col("actor_type") == "agent").select("actor_id", "uidx").unique()
    pairs = np.unique(np.array([a_index[a] * n_units + int(u) for a, u in ag.iter_rows() if a in a_index],
                               dtype=np.int64))
    tt = (pl.scan_parquet(processed / "events_unified.parquet").filter(pl.col("source").cast(pl.String) == "turn")
          .select(pl.col("event_uid").str.strip_prefix("turn:").alias("id"), "actor_id", "ts_utc", "t_active",
                  "dup_of_uid").collect())
    if date_range is not None:
        dloc = pl.col("ts_utc").dt.convert_time_zone("America/Los_Angeles").dt.date()
        tt = tt.filter((dloc >= date_range[0]) & (dloc <= date_range[1]))
    tt = tt.with_columns(pl.when(pl.col("dup_of_uid").is_null())
                         .then(pl.col("actor_id").replace_strict(a_index, default=-1, return_dtype=pl.Int32))
                         .otherwise(-1).alias("aidx"))
    path = tables / "computer_use_turns_text.parquet"
    pf = pq.ParquetFile(path)
    ids = pq.read_table(path, columns=["id"]).column("id").to_pylist()
    pos_df = pl.DataFrame({"id": ids}).with_row_index("gpos").join(tt.select("id", "aidx"), on="id", how="left")
    aidx_all = pos_df.sort("gpos")["aidx"].fill_null(-1).to_numpy()
    tasks, start = [], 0
    offsets = []
    for g in range(pf.metadata.num_row_groups):
        stop = start + pf.metadata.row_group(g).num_rows
        sl = aidx_all[start:stop]
        if (sl >= 0).any():
            tasks.append((str(path), g, sl.astype(np.int16)))
        offsets.append(start)
        start = stop
    t0 = time.perf_counter()
    r_parts, u_parts = [], []
    with ProcessPoolExecutor(max(1, min(n_workers, len(tasks))), mp_context=mp.get_context("spawn"),
                             initializer=_init_turn_worker, initargs=(agent_names, salt, matcher, uninf, pairs)) as ex:
        futs = [ex.submit(_turn_worker, p, g, sl, n_units) for p, g, sl in tasks]
        done = 0
        for f in as_completed(futs):
            rg, r, u = f.result()
            r_parts.append(r.astype(np.int64) + offsets[rg])
            u_parts.append(u)
            done += 1
            if done % 20 == 0:
                log(f"E3: {done}/{len(tasks)} row groups, {time.perf_counter() - t0:.0f} s")
    gpos = np.concatenate(r_parts) if r_parts else np.zeros(0, np.int64)
    uix = np.concatenate(u_parts) if u_parts else np.zeros(0, np.int32)
    hits = pl.DataFrame({"gpos": gpos.astype(np.uint32), "uidx": uix.astype(np.int32)})
    hits = (hits.join(pos_df.select("gpos", "id"), on="gpos", how="left")
            .join(tt.select("id", "actor_id", "ts_utc", "t_active"), on="id", how="left")
            .join(units.select("uidx", "unit_id"), on="uidx", how="left")
            .select(pl.col("actor_id").alias("agent_id"), "unit_id", "uidx", "ts_utc", "t_active",
                    (pl.lit("turn:") + pl.col("id")).alias("turn_uid"))
            .sort("agent_id", "unit_id", "ts_utc"))
    return hits


def main(argv: list[str] | None = None) -> None:
    import argparse

    from avsd.config import load_config

    p = argparse.ArgumentParser(description="Module B2 information units and occurrences (SPEC 6.4.1).")
    p.add_argument("--config", default=None)
    p.add_argument("--workers", type=int, default=0)
    p.add_argument("--pilot", default="", help="PT date range a:b (YYYY-MM-DD); outputs go to b2_pilot/")
    p.add_argument("--force", action="store_true")
    args = p.parse_args(argv)
    cfg = load_config(args.config)
    dr, tag = None, ""
    if args.pilot:
        a, b = args.pilot.split(":")
        dr, tag = (date.fromisoformat(a), date.fromisoformat(b)), "pilot"

    def log(msg: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    res = build_units(cfg, args.workers or None, date_range=dr, tag=tag, force=args.force, log=log)
    log(json.dumps(res["stats"], default=str))


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
