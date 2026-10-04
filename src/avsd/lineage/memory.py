"""Module B1: memory chains, fact-unit retention and the H2 test (SPEC 6.2 H2, 6.3).

Path S (decisions "Module B1"): every memory row is a full snapshot, a
consolidation is a live REWRITE row, APPEND rows feed the next consolidation,
IDENT rows are no-ops, TRUNC/revert rows are undos, fork rows extend their
`base_id`, and rows of abandoned lineage branches are dropped. Fact units,
states and survival are defined in `avsd.lineage.anchors` and
`avsd.lineage.chains`; in short:

- Fact unit: (anchor type, normalised value or keyed hash, context key); the
  context key is part of the identity only for quantities (number, money,
  percent, time). A unit enters at its first appearance in the agent's memory
  (any row).
- Each later consolidation c of that agent is trial g = c - e (e = number of
  consolidations before entry). State: kept (in the output), modified (absent,
  but one of its contexts holds a value the previous version did not hold),
  dropped (absent otherwise), restored (back after a loss). Survival S is the
  number of consolidations survived before the first loss (dropped or
  modified); restorations are counted separately. `event = dropped` alone is
  reported as the cause-specific hazard.
- Strata: model family (standard scaffold), Opus 4.5 (Claude Code) on its own,
  regime_cu of the consolidation (pre/post perma-computer-use), unit entry
  kind and anchor type, and +/- CHANGELOG_WINDOW run days around each
  memory-category CHANGELOG entry (calendar strata are trial-level; risk sets
  handle units that cross a boundary).
- Statistics (`avsd.lineage.survival`): discrete Kaplan-Meier, hazards h_g
  with 95% cluster-bootstrap CIs (agents resampled, `seed`), the geometric
  (constant hazard) fit against a piecewise-constant hazard over g = 1, 2,
  3-4, 5-8, 9+ (likelihood ratio, naive, and a cluster-bootstrap Wald test),
  and a beta-geometric fit (heterogeneous constant hazards). Generations are
  reported only with at least `lineage.min_edges_per_generation` units at risk.
- Heterogeneity vs duration dependence: a beta-discrete-Weibull fit (shape c;
  c = 1 is the beta-geometric) per family, regime cohort and anchor type, with
  a cluster-bootstrap CI of c and the LR test of c = 1; and, for restored facts,
  the hazard of the second spell against the first at the same g.
- Monthly hazards (g = 1, 2, 3-4) of the consolidations in each PT calendar
  month, by family, for module C.

Pipeline (`run_memory`):

1. Lines. The text table is streamed by row group in spawned workers. Each
   live row contributes the raw lines of its own segment (the whole row for
   first/rewrite/trunc rows, the text from the line that holds the end of the
   base for appends and forks, nothing for reverts). A line is hashed (64-bit
   BLAKE2b) after removing scaffold session labels ("PREVIOUS (NOW ENDED) ...
   SESSION (...)"), together with its sensitivity flag (under a credential
   heading). Lines without letters or digits get hash 0.
2. Anchors. Each distinct line is extracted once (regex + spaCy, parallel).
   Steps 1-2 are cached under data/interim/b1_cache/ (line hashes and anchors
   only; no text).
3. Chains, one agent per worker.
4. Statistics, tables, figure, labelling file, memory_facts, QA report.

Rules v2 (`rules="v2"`, chains.py): a unit without an anchor in a consolidation
output still counts as present if its value occurs literally there, and a loss
is a modification only if the line that replaced the unit's line holds the
same context key with a new value. Rules v3 (`rules="v3"`): as v2, but a time,
number, money or percent unit needs its context word adjacent to the value.
The consolidation outputs' text is read again for the literal search (in
memory only). A v2 (v3) run writes every table, the figure, the QA report and
memory_facts with the suffix `_v2` (`_v3`), outputs/tables/memory_v1_v2.csv
(memory_v1_v2_v3.csv: the rule sets against each other on the same units,
computed in one pass) and data/labels/memory_pairs_rule_v2.csv (_v3; pair_id,
unit_key, rule_label_v2 or _v3; mode 600). Earlier outputs stay as they are.

Outputs: outputs/tables/memory_{hazard,retention,modification,by_anchor,h2,
changelog,bdw,repeat_spells}.csv, outputs/tables/memory_hazard_monthly.parquet
(and .csv), outputs/figures/F6_memory_retention.{pdf,png},
outputs/qa/lineage_memory.md, data/interim/memory_facts.parquet (one row per
presence spell of a unit, for module B2) and data/labels/memory_pairs.csv
(SPEC appendix C; prev_uid is the consolidation's input row, next_uid its
output). Outputs hold aggregates only; values in label files and
memory_facts are hashed for PERSON, email, phone and sensitive lines, URLs are
shown as domain plus hash in the label file, and context lemmas used by fewer
than CTX_MIN_AGENTS agents are hashed.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import multiprocessing as mp
import os
import re
import time
import warnings
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from scipy import stats

from avsd.config import load_config
from avsd.events.memory_versions import _LABEL as SESSION_LABEL
from avsd.lineage import survival as sv
from avsd.lineage.anchors import (
    PROPN_MARK, QUANTITY_TYPES, TYPES, AnchorExtractor, HeadingStack, display_value, keyed_hash,
    load_nlp, load_salt, url_domain,
)
from avsd.lineage.chains import (
    EVENT_DROPPED, EVENT_MODIFIED, KIND_COPY, KIND_EXT, KIND_FULL, REL_CODE,
    SRC_REAPPENDED, SRC_RECREATED, AgentInput, AgentResult, V2Data, run_chain,
)

EXTRACTOR_VERSION = "b1-anchors-v2"
CACHE_DIR = "b1_cache"
CHANGELOG_WINDOW = 5  # run days on each side of a memory CHANGELOG entry
CTX_MIN_AGENTS = 3  # context lemmas used by fewer agents are hashed in outputs
# Risk counts keep every trial index g = 1..max K individually (no overflow), so
# beta-geometric and BdW likelihoods are exact.
G_TABLE_BINS: tuple[tuple[int, int | None], ...] = (
    *[(g, g) for g in range(1, 21)], (21, 30), (31, 50), (51, 100), (101, 200), (201, 500),
    (501, 1000), (1001, None),
)
G_KM = 100  # retention curve length
BOOT_REPS = 2000
B_BDW = 500  # cluster-bootstrap refits per BdW scope
BDW_G_SHOW = (1, 2, 5, 10, 20)  # g at which observed and fitted hazards are tabulated
MIN_CLUSTERS_WALD = 5  # agents with trials needed for the cluster Wald test
MIN_CLUSTERS_CI = 5  # below this many agents, cluster-bootstrap CIs are flagged as unstable
N_PAIRS = 100
UNITS_PER_PAIR = 5
FAMILIES = ("Anthropic", "OpenAI", "Google", "Other")
CC_LABEL = "Claude Code"
ALL_LABEL = "All standard"
QUANTITY_CODES = frozenset(TYPES.index(t) for t in QUANTITY_TYPES)
_ALNUM = re.compile(r"[^\W_]")
_SPLIT_TS = "%Y-%m-%d %H:%M"


# --- step 1: line hashes per row ----------------------------------------------

def line_hash(clean: str, sensitive: bool) -> int:
    h = hashlib.blake2b((b"S" if sensitive else b"N") + clean.encode("utf-8", "surrogatepass"),
                        digest_size=8)
    v = int.from_bytes(h.digest(), "little", signed=True)
    return v or 1


def clean_line(line: str) -> str | None:
    """Line text used for anchors: session labels removed, stripped; None if no alnum."""
    if "PREVIOUS (NOW ENDED)" in line:
        line = SESSION_LABEL.sub(" ", line)
    s = line.strip()
    return s if s and _ALNUM.search(s) else None


def segment_lines(text: str, kind: int, base_len: int) -> tuple[np.ndarray, list[tuple[int, str, bool]]]:
    """Hashes of the raw lines of a row's segment and the (hash, text, sensitive) of each."""
    start = 0
    stack = HeadingStack()
    if kind == KIND_EXT and base_len > 0:
        start = text.rfind("\n", 0, base_len) + 1
        if start > 0:
            stack.feed_text(text, start)
    raw = text[start:].split("\n")
    hs = np.zeros(len(raw), dtype=np.int64)
    items = []
    for i, line in enumerate(raw):
        sens = stack.feed(line)
        clean = clean_line(line)
        if clean is None:
            continue
        h = line_hash(clean, sens)
        hs[i] = h
        items.append((h, clean, sens))
    return hs, items


def _segment_worker(path: str, rg: int, plan: dict[str, tuple[int, int]]
                    ) -> tuple[list[str], list[np.ndarray], list[tuple[int, str, bool]], dict]:
    tb = pq.ParquetFile(path).read_row_group(rg, columns=["id", "content"])
    ids, segs, new = [], [], []
    seen: set[int] = set()
    st = {"rows": 0, "seg_chars": 0, "seg_lines": 0, "empty_rows": 0}
    for rid, text in zip(tb.column("id").to_pylist(), tb.column("content").to_pylist()):
        p = plan.get(rid)
        if p is None:
            continue
        kind, base_len = p
        st["rows"] += 1
        if not text:
            st["empty_rows"] += 1
        if kind == KIND_COPY:
            ids.append(rid)
            segs.append(np.zeros(0, dtype=np.int64))
            continue
        text = text or ""
        hs, items = segment_lines(text, kind, base_len)
        st["seg_lines"] += len(hs)
        st["seg_chars"] += len(text) - (text.rfind("\n", 0, base_len) + 1 if kind == KIND_EXT and base_len else 0)
        for h, clean, sens in items:
            if h not in seen:
                seen.add(h)
                new.append((h, clean, sens))
        ids.append(rid)
        segs.append(hs)
    return ids, segs, new, st


# --- step 2: anchors per distinct line ------------------------------------------

_EXTRACTOR: AnchorExtractor | None = None


def _init_extractor(agent_names: list[str], salt: bytes) -> None:
    global _EXTRACTOR
    _EXTRACTOR = AnchorExtractor(agent_names, salt, load_nlp())


def _extract_worker(chunk: list[tuple[int, str, bool]]) -> tuple[np.ndarray, np.ndarray, list[str], list[str]]:
    res = _EXTRACTOR.extract([t for _, t, _ in chunk], [s for _, _, s in chunk])
    hs, ts, vs, cs = [], [], [], []
    for (h, _, _), anchors in zip(chunk, res):
        for t, v, c in anchors:
            hs.append(h)
            ts.append(t)
            vs.append(v)
            cs.append(c)
    return np.array(hs, dtype=np.int64), np.array(ts, dtype=np.int8), vs, cs


# --- inputs ------------------------------------------------------------------------

def live_rows(mv: pl.DataFrame) -> tuple[pl.DataFrame, dict]:
    """Live rows per agent with kind, base index and consolidation flag.

    Drops IDENT rows and rows whose lineage generation no later row descends
    from (the live generations are the parent chain of the agent's last row's
    generation). Bases that are IDENT rows resolve to the row they repeat.
    """
    mv = mv.sort("agent_id", "created_at", "id")
    gens = mv.filter(pl.col("is_generation"))
    parent = dict(zip(gens["id"].to_list(), gens["parent_gen_id"].to_list()))
    live: set[str] = set()
    for g in mv.group_by("agent_id", maintain_order=True).agg(pl.col("gen_id").last())["gen_id"]:
        while g is not None and g not in live:
            live.add(g)
            g = parent.get(g)
    ident_base = dict(mv.filter(pl.col("rel") == "ident").select("id", "base_id").iter_rows())
    df = mv.filter(pl.col("gen_id").is_in(list(live)) & (pl.col("rel") != "ident"))
    qa = {
        "rows": mv.height,
        "ident_rows": len(ident_base),
        "dead_rows": mv.height - len(ident_base) - df.height,
        "dead_generations": int(gens.filter(~pl.col("id").is_in(list(live))).height),
    }

    def resolve(b: str | None) -> str | None:
        while b in ident_base:
            b = ident_base[b]
        return b

    rel = df["rel"].cast(pl.String).to_list()
    kinds = [KIND_FULL if r in ("first", "rewrite", "trunc_other") else
             KIND_COPY if r == "revert" else KIND_EXT for r in rel]
    df = df.with_columns(
        pl.Series("base_res", [resolve(b) for b in df["base_id"].to_list()], dtype=pl.String),
        pl.Series("kind", kinds, dtype=pl.Int8),
        pl.Series("rel_code", [REL_CODE[r] for r in rel], dtype=pl.Int8),
        (pl.col("rel") == "rewrite").alias("is_cons"),
        pl.int_range(pl.len()).over("agent_id").alias("idx"),
    )
    pos = df.select(pl.col("id").alias("base_res"), pl.col("idx").alias("base_idx"))
    lens = mv.select(pl.col("id").alias("base_id"), pl.col("content_len").alias("base_len"))
    df = (df.join(pos, on="base_res", how="left", maintain_order="left")
          .join(lens, on="base_id", how="left", maintain_order="left")
          .with_columns(pl.col("base_idx").fill_null(-1), pl.col("base_len").fill_null(0)))
    bad = df.filter((pl.col("kind") != KIND_FULL) & (pl.col("base_idx") < 0)).height
    if bad:
        raise ValueError(f"{bad} live rows have a base outside the live rows")
    qa["live_rows"] = df.height
    qa["consolidations"] = int(df["is_cons"].sum())
    return df, qa


def _cache_paths(cfg: dict, pilot: bool = False) -> dict[str, Path]:
    d = Path(cfg["paths"]["interim"]) / (CACHE_DIR + ("_pilot" if pilot else ""))
    return {"dir": d, "meta": d / "meta.json", "rows": d / "row_segments.parquet",
            "flat": d / "row_segments.npy", "anchors": d / "line_anchors.parquet"}


def _rows_signature(ids: list[str]) -> str:
    h = hashlib.blake2b(digest_size=16)
    for x in ids:
        h.update(x.encode())
    return h.hexdigest()


def extract_lines_and_anchors(cfg: dict, rows: pl.DataFrame, agent_names: list[str], salt: bytes,
                              n_workers: int, reextract: bool, log, pilot: bool = False) -> dict:
    """Steps 1-2 with caching. Returns segments per row id and the anchors table."""
    cp = _cache_paths(cfg, pilot)
    sig = _rows_signature(rows["id"].to_list())
    if not reextract and cp["meta"].exists():
        meta = json.loads(cp["meta"].read_text())
        if meta.get("version") == EXTRACTOR_VERSION and meta.get("rows_signature") == sig:
            log("cache hit: reusing line hashes and anchors")
            idx = pl.read_parquet(cp["rows"])
            flat = np.load(cp["flat"])
            anchors = pl.read_parquet(cp["anchors"])
            return {"index": idx, "flat": flat, "anchors": anchors, "meta": meta, "cached": True}

    text_path = Path(cfg["paths"]["tables"]) / "agent_memories_text.parquet"
    pf = pq.ParquetFile(text_path)
    plan_all = dict(zip(rows["id"].to_list(),
                        zip(rows["kind"].to_list(), rows["base_len"].to_list())))
    text_ids = pq.read_table(text_path, columns=["id"]).column("id").to_pylist()
    tasks, start = [], 0
    for g in range(pf.metadata.num_row_groups):
        stop = start + pf.metadata.row_group(g).num_rows
        plan = {x: plan_all[x] for x in text_ids[start:stop] if x in plan_all}
        tasks.append((str(text_path), g, plan))
        start = stop
    t0 = time.perf_counter()
    seg_of: dict[str, np.ndarray] = {}
    line_text: dict[int, tuple[str, bool]] = {}
    st = Counter()
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(min(n_workers, len(tasks)), mp_context=ctx) as ex:
        futs = [ex.submit(_segment_worker, *t) for t in tasks]
        for f in as_completed(futs):
            ids, segs, new, s = f.result()
            seg_of.update(zip(ids, segs))
            for h, t, sens in new:
                if h not in line_text:
                    line_text[h] = (t, sens)
            st.update(s)
    missing = set(plan_all) - seg_of.keys()
    if missing:
        raise ValueError(f"{len(missing)} live rows not found in agent_memories_text")
    t1 = time.perf_counter()
    n_chars = sum(len(t) for t, _ in line_text.values())
    log(f"step 1: {st['rows']:,} rows, {len(line_text):,} distinct lines "
        f"({n_chars:,} chars) in {t1 - t0:.0f} s")

    # Step 2: longest lines first, in chunks of about CHUNK_CHARS characters.
    items = sorted(line_text.items(), key=lambda kv: -len(kv[1][0]))
    del line_text
    chunks, cur, size = [], [], 0
    for h, (t, sens) in items:
        cur.append((h, t, sens))
        size += len(t)
        if size >= 200_000 or len(cur) >= 4000:
            chunks.append(cur)
            cur, size = [], 0
    if cur:
        chunks.append(cur)
    del items
    parts_h, parts_t, vals, ctxs = [], [], [], []
    done = 0
    with ProcessPoolExecutor(n_workers, mp_context=ctx, initializer=_init_extractor,
                             initargs=(agent_names, salt)) as ex:
        for res in ex.map(_extract_worker, chunks, chunksize=1):
            parts_h.append(res[0])
            parts_t.append(res[1])
            vals.extend(res[2])
            ctxs.extend(res[3])
            done += 1
            if done % 500 == 0:
                log(f"step 2: {done:,}/{len(chunks):,} chunks, {time.perf_counter() - t1:.0f} s")
    t2 = time.perf_counter()
    anchors = pl.DataFrame({
        "line_hash": np.concatenate(parts_h) if parts_h else np.zeros(0, np.int64),
        "type": np.concatenate(parts_t) if parts_t else np.zeros(0, np.int8),
        "value": pl.Series(vals, dtype=pl.String),
        "ctx": pl.Series(ctxs, dtype=pl.String),
    })
    log(f"step 2: {anchors.height:,} line anchors in {t2 - t1:.0f} s")

    ids = rows["id"].to_list()
    lens = np.array([len(seg_of[x]) for x in ids], dtype=np.int64)
    starts = np.concatenate([[0], np.cumsum(lens)[:-1]]) if len(lens) else lens
    flat = np.concatenate([seg_of[x] for x in ids]) if ids else np.zeros(0, np.int64)
    idx = pl.DataFrame({"id": ids, "start": starts, "length": lens})
    meta = {
        "version": EXTRACTOR_VERSION, "rows_signature": sig,
        "created": datetime.now(timezone.utc).strftime(_SPLIT_TS),
        "rows": int(st["rows"]), "empty_rows": int(st["empty_rows"]),
        "segment_chars": int(st["seg_chars"]), "segment_lines": int(st["seg_lines"]),
        "distinct_lines": int(sum(len(c) for c in chunks)), "distinct_chars": int(n_chars),
        "lines_with_anchors": int(anchors["line_hash"].n_unique()),
        "seconds_lines": round(t1 - t0, 1), "seconds_anchors": round(t2 - t1, 1),
    }
    cp["dir"].mkdir(parents=True, exist_ok=True)
    idx.write_parquet(cp["rows"])
    np.save(cp["flat"], flat)
    anchors.write_parquet(cp["anchors"], compression="zstd")
    cp["meta"].write_text(json.dumps(meta, indent=1))
    return {"index": idx, "flat": flat, "anchors": anchors, "meta": meta, "cached": False}


def intern_anchors(anchors: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Global ids. Returns (line -> occurrence, occurrence table, unit table, ctx table)."""
    a = anchors.with_columns(
        (~pl.col("ctx").str.starts_with(PROPN_MARK)).alias("noun"),
        pl.col("ctx").str.strip_prefix(PROPN_MARK).alias("lemma"),
    )
    vals = a.select("value").unique().sort("value").with_row_index("value_id")
    lems = (a.filter(pl.col("lemma") != "").select("lemma").unique().sort("lemma")
            .with_row_index("ctx_id"))
    a = (a.join(vals, on="value", how="left")
         .join(lems, on="lemma", how="left")
         .with_columns(pl.col("value_id").cast(pl.Int64),
                       pl.col("ctx_id").cast(pl.Int64).fill_null(-1)))
    occ = (a.select("type", "value_id", "ctx_id").unique().sort("type", "value_id", "ctx_id")
           .with_row_index("occ_gid")
           .with_columns(
               pl.when(pl.col("type").is_in(list(QUANTITY_CODES))).then(pl.col("ctx_id"))
               .otherwise(-1).alias("unit_ctx"),
               pl.when(pl.col("ctx_id") >= 0).then(pl.col("type").cast(pl.Int64) * (1 << 32)
                                                   + pl.col("ctx_id")).otherwise(-1).alias("tc"),
           ))
    units = (occ.select("type", "value_id", "unit_ctx").unique().sort("type", "value_id", "unit_ctx")
             .with_row_index("unit_gid"))
    occ = occ.join(units, on=["type", "value_id", "unit_ctx"], how="left")
    line_occ = (a.join(occ.select("type", "value_id", "ctx_id", "occ_gid"),
                       on=["type", "value_id", "ctx_id"], how="left")
                .select("line_hash", "occ_gid", "lemma", "noun", "ctx_id")
                .unique(["line_hash", "occ_gid"]))
    units = units.join(vals, on="value_id", how="left")
    return line_occ, occ, units, lems


def _agent_inputs(rows_a: pl.DataFrame, index: dict[str, tuple[int, int]], flat: np.ndarray,
                  line_occ: pl.DataFrame, occ: pl.DataFrame, label_rows: frozenset[int],
                  v2_parts: dict | None = None) -> tuple[AgentInput, np.ndarray, pl.DataFrame]:
    """AgentInput for one agent; also its line hashes and its line -> occurrence rows.

    v2_parts (rules v2): {"texts": row id -> text, "units": unit table with
    unit_gid, value and lemma, "salt": bytes}.
    """
    segs = [flat[s:s + n] for s, n in (index[x] for x in rows_a["id"].to_list())]
    hashes = np.unique(np.concatenate(segs)) if segs else np.zeros(0, np.int64)
    hashes = hashes[hashes != 0]
    lo = line_occ.filter(pl.col("line_hash").is_in(hashes)).sort("line_hash", "occ_gid")
    occ_g = np.unique(lo["occ_gid"].to_numpy())
    local = np.searchsorted(occ_g, lo["occ_gid"].to_numpy())
    lh = lo["line_hash"].to_numpy()
    uniq_h, first = np.unique(lh, return_index=True)
    ptr = np.append(first, len(lh)).astype(np.int64)
    o = occ.filter(pl.col("occ_gid").is_in(occ_g)).sort("occ_gid")
    inp = AgentInput(
        agent_id=rows_a["agent_id"][0],
        rel=rows_a["rel_code"].to_numpy(),
        kind=rows_a["kind"].to_numpy(),
        base=rows_a["base_idx"].to_numpy().astype(np.int64),
        is_cons=rows_a["is_cons"].to_numpy(),
        seg=segs,
        line_hash=uniq_h.astype(np.int64),
        line_ptr=ptr,
        line_occ=local.astype(np.int32),
        occ_unit=o["unit_gid"].to_numpy().astype(np.int32),
        occ_tc=o["tc"].to_numpy().astype(np.int64),
        occ_val=o["value_id"].to_numpy().astype(np.int64),
        label_rows=label_rows,
    )
    if v2_parts is not None:
        ids = rows_a["id"].to_list()
        texts = v2_parts["texts"]
        cons_idx = np.flatnonzero(rows_a["is_cons"].to_numpy()).tolist()
        ui = (v2_parts["units"].filter(pl.col("unit_gid").is_in(np.unique(inp.occ_unit)))
              .select("unit_gid", "value", "lemma"))
        inp.v2 = V2Data(
            cons_text={k: texts.get(ids[k], "") for k in cons_idx},
            in_text={k: texts.get(ids[k - 1], "") for k in label_rows if k >= 1},
            unit_info={g: (v or "", lm or "") for g, v, lm in ui.iter_rows()},
            occ_type=o["type"].to_numpy().astype(np.int64),
            salt=v2_parts["salt"],
            versions=tuple(v2_parts.get("versions", ("v2",))),
            agent_names=tuple(v2_parts.get("agent_names", ())),
        )
    return inp, occ_g, lo


def _text_worker(path: str, rg: int, ids: list[str]) -> dict[str, str]:
    tb = pq.ParquetFile(path).read_row_group(rg, columns=["id", "content"])
    tb = tb.filter(pc.is_in(tb.column("id"), value_set=pa.array(ids, type=tb.schema.field("id").type)))
    return {i: (t or "") for i, t in zip(tb.column("id").to_pylist(), tb.column("content").to_pylist())}


def read_row_texts(text_path: Path, ids: set[str], n_workers: int) -> dict[str, str]:
    """Texts of the given memory rows, streaming the text table once by row group."""
    pf = pq.ParquetFile(text_path)
    text_ids = pq.read_table(text_path, columns=["id"]).column("id").to_pylist()
    tasks, start = [], 0
    for g in range(pf.metadata.num_row_groups):
        stop = start + pf.metadata.row_group(g).num_rows
        want = [x for x in text_ids[start:stop] if x in ids]
        if want:
            tasks.append((str(text_path), g, want))
        start = stop
    out: dict[str, str] = {}
    with ProcessPoolExecutor(max(1, min(n_workers, len(tasks))), mp_context=mp.get_context("spawn")) as ex:
        for f in as_completed([ex.submit(_text_worker, *t) for t in tasks]):
            out.update(f.result())
    return out


def _chain_worker(inp: AgentInput, occ_g: np.ndarray) -> tuple[AgentResult, np.ndarray]:
    return run_chain(inp), occ_g


def states_from_snapshots(snaps: list[tuple[str, str, int]], extractor: AnchorExtractor,
                          label_rows: frozenset[int] = frozenset()) -> tuple[AgentResult, pl.DataFrame]:
    """Steps 1-3 in process for one agent: snaps = (rel, text, base index) in time order.

    For tests and spot checks. IDENT rows must already be removed; the base of
    an append is the previous row, of a fork or revert an older one.
    Returns the chain result and the unit table (unit_gid, type, value_id, unit_ctx, value).
    """
    segs, kinds, line_text = [], [], {}
    for rel, text, b in snaps:
        kind = (KIND_FULL if rel in ("first", "rewrite", "trunc_other") else
                KIND_COPY if rel == "revert" else KIND_EXT)
        kinds.append(kind)
        if kind == KIND_COPY:
            segs.append(np.zeros(0, dtype=np.int64))
            continue
        hs, items = segment_lines(text, kind, len(snaps[b][1]) if b >= 0 else 0)
        segs.append(hs)
        for h, t, s in items:
            line_text.setdefault(h, (t, s))
    hs = list(line_text)
    res = extractor.extract([line_text[h][0] for h in hs], [line_text[h][1] for h in hs])
    recs = [(h, t, v, c) for h, an in zip(hs, res) for t, v, c in an]
    anchors = pl.DataFrame(recs, schema={"line_hash": pl.Int64, "type": pl.Int8, "value": pl.String,
                                         "ctx": pl.String}, orient="row")
    line_occ, occ, units, _ = intern_anchors(anchors)
    ids = [f"r{i}" for i in range(len(snaps))]
    rows_a = pl.DataFrame({
        "id": ids, "agent_id": ["agent"] * len(snaps),
        "rel_code": pl.Series([REL_CODE[r] for r, _, _ in snaps], dtype=pl.Int8),
        "kind": pl.Series(kinds, dtype=pl.Int8),
        "base_idx": pl.Series([b for _, _, b in snaps], dtype=pl.Int64),
        "is_cons": [r == "rewrite" for r, _, _ in snaps],
    })
    lens = np.array([len(s) for s in segs], dtype=np.int64)
    starts = np.concatenate([[0], np.cumsum(lens)[:-1]])
    index = {x: (int(s), int(n)) for x, s, n in zip(ids, starts, lens)}
    flat = np.concatenate(segs) if segs else np.zeros(0, np.int64)
    inp, _, _ = _agent_inputs(rows_a, index, flat, line_occ, occ, label_rows)
    return run_chain(inp), units


# --- statistics helpers -------------------------------------------------------------

def _wilson(d: np.ndarray, n: np.ndarray, z: float = 1.96) -> tuple[np.ndarray, np.ndarray]:
    with np.errstate(divide="ignore", invalid="ignore"):
        p = d / n
        den = 1 + z * z / n
        c = (p + z * z / (2 * n)) / den
        h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return c - h, c + h


def _boot_ci(stat_b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """2.5% and 97.5% percentiles over replicates; NaN where no replicate is defined."""
    if stat_b.shape[0] == 0:
        nan = np.full(stat_b.shape[1:], np.nan)
        return nan, nan
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN columns (bins without data)
        q = np.nanpercentile(stat_b, [2.5, 97.5], axis=0)
    return q[0], q[1]


def _fmt(x: float, nd: int = 3) -> str:
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "n/a"
    return f"{x:.{nd}f}"


def _fmt_p(p: float) -> str:
    if p is None or not np.isfinite(p):
        return "n/a"
    return "<1e-300" if p < 1e-300 else f"{p:.2g}"


class Scope:
    """A set of units with agent-level counts and its bootstrap weights."""

    def __init__(self, scope: str, stratum: str, rc: sv.RiskCounts, s: int, agents: np.ndarray,
                 w: np.ndarray | None, n_units: int) -> None:
        self.scope, self.stratum, self.agents = scope, stratum, agents
        self.n_ag = rc.n[s][agents]
        self.d_ag = rc.d[s][agents]
        self.m_ag = rc.dmod[s][agents]
        self.g_max = rc.g_max
        self.w = None if w is None else w[:, agents]
        self.n_units = n_units

    @property
    def cluster(self) -> bool:
        """Cluster bootstrap needs at least two agents with trials in this scope."""
        return self.w is not None and int((self.n_ag[:, 1:].sum(1) > 0).sum()) >= 2

    @property
    def n_contrib(self) -> int:
        return int((self.n_ag[:, 1:].sum(1) > 0).sum())

    def totals(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        return self.n_ag.sum(0), self.d_ag.sum(0), self.m_ag.sum(0)

    def binned(self, bins) -> dict[str, np.ndarray]:
        n, d, m = (sv.bin_sums(x, bins, self.g_max) for x in self.totals())
        nag = (sv.bin_sums(self.n_ag, bins, self.g_max) > 0).sum(0)
        h, mr = sv.hazard(n, d), sv.hazard(n, m)
        ms = sv.hazard(d, m)
        if self.cluster:
            nb = self.w @ sv.bin_sums(self.n_ag, bins, self.g_max)
            db = self.w @ sv.bin_sums(self.d_ag, bins, self.g_max)
            mb = self.w @ sv.bin_sums(self.m_ag, bins, self.g_max)
            h_lo, h_hi = _boot_ci(sv.hazard(nb, db))
            m_lo, m_hi = _boot_ci(sv.hazard(nb, mb))
            s_lo, s_hi = _boot_ci(sv.hazard(db, mb))
            method = "cluster_bootstrap"
        else:
            h_lo, h_hi = _wilson(d, n)
            m_lo, m_hi = _wilson(m, n)
            s_lo, s_hi = _wilson(m, d)
            method = "wilson"
        return {"n": n, "d": d, "m": m, "n_agents": nag, "h": h, "h_lo": h_lo, "h_hi": h_hi,
                "mr": mr, "mr_lo": m_lo, "mr_hi": m_hi, "ms": ms, "ms_lo": s_lo, "ms_hi": s_hi,
                "method": method}

    def km(self, g_km: int) -> dict[str, np.ndarray]:
        n, d, _ = self.totals()
        h = sv.hazard(n[1:g_km + 1], d[1:g_km + 1])
        s = sv.km(h)
        if self.cluster:
            hb = sv.hazard(self.w @ self.n_ag[:, 1:g_km + 1], self.w @ self.d_ag[:, 1:g_km + 1])
            lo, hi = _boot_ci(np.cumprod(1 - hb, axis=1))
        else:
            # Greenwood on the log scale, units independent (one agent).
            with np.errstate(divide="ignore", invalid="ignore"):
                var = np.cumsum(d[1:g_km + 1] / (n[1:g_km + 1] * (n[1:g_km + 1] - d[1:g_km + 1])))
            lo, hi = s * np.exp(-1.96 * np.sqrt(var)), np.minimum(1, s * np.exp(1.96 * np.sqrt(var)))
        return {"n": n[1:g_km + 1], "s": s, "lo": lo, "hi": hi}

    def h2(self, fit_betageom: bool = True) -> sv.H2Test:
        w = self.w if self.cluster else np.ones((1, len(self.agents)))
        return sv.h2_test(self.n_ag, self.d_ag, self.g_max, w, min_clusters=MIN_CLUSTERS_WALD,
                          fit_betageom=fit_betageom)


# --- the run ------------------------------------------------------------------------

def run_memory(cfg: dict | None = None, *, reextract: bool = False, n_workers: int | None = None,
               agent_filter: list[str] | None = None, write_outputs: bool = True, rules: str = "v1") -> dict:
    """Module B1 on the real data. Returns a summary dict (also rendered in the QA report).

    reextract: ignore the step 1-2 cache. agent_filter: agent names to keep
    (pilot runs; outputs are then written under outputs/qa/pilot_*). rules:
    "v1"; "v2" (literal presence fallback and line-aligned modification,
    `avsd.lineage.chains`), which also reads the consolidation outputs' text and
    writes `_v2` outputs plus a v1-v2 comparison next to the v1 ones; or "v3"
    (v2 with the context word required next to quantity values), which runs
    v1, v2 and v3 in one pass and writes `_v3` outputs and a v1-v2-v3 comparison.
    """
    if rules not in ("v1", "v2", "v3"):
        raise ValueError(f"rules must be v1, v2 or v3, not {rules!r}")
    cfg = cfg or load_config()
    t_start = time.perf_counter()
    timings: dict[str, float] = {}
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "POLARS_MAX_THREADS"):
        os.environ.setdefault(var, "1" if var != "POLARS_MAX_THREADS" else "4")
    if n_workers is None:
        n_workers = int(os.environ.get("SLURM_CPUS_PER_TASK") or os.cpu_count() or 1)
    seed = int(cfg["seed"])
    min_units = int(cfg.get("lineage", {}).get("min_edges_per_generation", 30))
    paths = cfg["paths"]
    interim, processed, outputs = Path(paths["interim"]), Path(paths["processed"]), Path(paths["outputs"])
    log_lines: list[str] = []

    def log(msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        log_lines.append(line)
        print(line, flush=True)

    salt = load_salt(interim)
    agents = pl.read_parquet(processed / "agents.parquet")
    agent_names = agents["name"].to_list()
    mv = pl.read_parquet(interim / "memory_versions.parquet")
    eu = (pl.scan_parquet(processed / "events_unified.parquet")
          .filter(pl.col("source") == "memory")
          .select(pl.col("event_uid").str.strip_prefix("memory:").alias("id"),
                  "run_day", "ts_pt", pl.col("regime_cu").cast(pl.String).alias("regime"))
          .collect())
    mv = mv.join(eu, on="id", how="left")
    if agent_filter:
        keep = agents.filter(pl.col("name").is_in(agent_filter))["agent_id"]
        mv = mv.filter(pl.col("agent_id").is_in(keep))
    rows, rows_qa = live_rows(mv)
    log(f"live rows {rows.height:,} of {mv.height:,}; consolidations {rows_qa['consolidations']:,}")
    timings["inputs"] = time.perf_counter() - t_start

    t = time.perf_counter()
    ex = extract_lines_and_anchors(cfg, rows, agent_names, salt, n_workers, reextract, log,
                                   pilot=bool(agent_filter))
    timings["lines_anchors"] = time.perf_counter() - t
    t = time.perf_counter()
    line_occ, occ, units_tab, lems = intern_anchors(ex["anchors"])
    index = {r[0]: (r[1], r[2]) for r in ex["index"].iter_rows()}
    flat = ex["flat"]
    timings["intern"] = time.perf_counter() - t
    log(f"interned {occ.height:,} occurrences, {units_tab.height:,} units")

    # Pairs to label: random live consolidations (seeded), extra candidates in reserve.
    rng = np.random.default_rng(seed)
    cons_rows = rows.filter(pl.col("is_cons")).select("id", "agent_id", "idx")
    pick = rng.choice(cons_rows.height, size=min(cons_rows.height, 3 * N_PAIRS), replace=False)
    cand = cons_rows[pick.tolist()].with_row_index("order")
    label_rows: dict[str, set[int]] = defaultdict(set)
    for a, i in cand.select("agent_id", "idx").iter_rows():
        label_rows[a].add(i)
    agent_ids = rows["agent_id"].unique(maintain_order=True).to_list()
    by_agent = {a: rows.filter(pl.col("agent_id") == a) for a in agent_ids}

    # Rules v2: texts of the consolidation outputs (and of the inputs of labelled pairs).
    v2_parts = None
    if rules in ("v2", "v3"):
        t = time.perf_counter()
        need = set(rows.filter(pl.col("is_cons"))["id"].to_list())
        for a, i in cand.select("agent_id", "idx").iter_rows():
            if i >= 1:
                need.add(by_agent[a]["id"][i - 1])
        texts = read_row_texts(Path(paths["tables"]) / "agent_memories_text.parquet", need, n_workers)
        units_v2 = (units_tab.select("unit_gid", "value", "unit_ctx")
                    .join(lems.select(pl.col("ctx_id").cast(pl.Int64).alias("unit_ctx"), "lemma"),
                          on="unit_ctx", how="left"))
        v2_parts = {"texts": texts, "units": units_v2, "salt": salt, "agent_names": tuple(agent_names),
                    "versions": ("v2",) if rules == "v2" else ("v2", "v3")}
        timings["texts"] = time.perf_counter() - t
        log(f"read {len(texts):,} texts ({sum(map(len, texts.values())):,} chars) for rules v2 "
            f"in {timings['texts']:.0f} s")

    # Step 3: chains.
    t = time.perf_counter()
    order = sorted(agent_ids, key=lambda a: -by_agent[a].height)
    results: dict[str, AgentResult] = {}
    occ_maps: dict[str, np.ndarray] = {}
    ctx_noun_agents: Counter = Counter()
    ctx_ex = mp.get_context("spawn")
    with ProcessPoolExecutor(min(n_workers, len(order)), mp_context=ctx_ex) as pool:
        futs = {}
        for a in order:
            inp, occ_g, lo = _agent_inputs(by_agent[a], index, flat, line_occ, occ,
                                           frozenset(label_rows.get(a, ())), v2_parts)
            ctx_noun_agents.update(lo.filter(pl.col("noun") & (pl.col("ctx_id") >= 0))
                                   ["ctx_id"].unique().to_list())
            futs[pool.submit(_chain_worker, inp, occ_g)] = a
        for f in as_completed(futs):
            res, occ_g = f.result()
            results[futs[f]] = res
            occ_maps[futs[f]] = occ_g
    timings["chains"] = time.perf_counter() - t
    log(f"chains done for {len(results)} agents in {timings['chains']:.0f} s")

    t = time.perf_counter()
    if rules in ("v2", "v3"):
        del v2_parts, texts
        sfx = rules[1:]
        view = {a: AgentResult(r.agent_id, r.n_cons, getattr(r, "units" + sfx), r.spells,
                               {**r.cons, **getattr(r, "cons" + sfx)}, getattr(r, "pairs" + sfx), r.qa)
                for a, r in results.items()}
        summary = analyse(cfg, rows, rows_qa, agents, view, units_tab, occ, lems, ctx_noun_agents,
                          cand, salt, seed, min_units, ex["meta"], write_outputs, agent_filter, log,
                          n_workers, rules=rules, results_v1=results)
        versions = ("v1", "v2") if rules == "v2" else ("v1", "v2", "v3")
        summary["comparison"] = compare_versions(cfg, results, agents, units_tab, summary, min_units,
                                                 write_outputs, agent_filter, versions, rows=rows,
                                                 seed=seed, n_workers=n_workers)
    else:
        summary = analyse(cfg, rows, rows_qa, agents, results, units_tab, occ, lems, ctx_noun_agents,
                          cand, salt, seed, min_units, ex["meta"], write_outputs, agent_filter, log,
                          n_workers)
    timings["analysis"] = time.perf_counter() - t
    timings["total"] = time.perf_counter() - t_start
    summary["timings"] = timings
    summary["cache_hit"] = ex["cached"]
    if write_outputs:
        qa_name = "lineage_memory.md" if rules == "v1" else f"lineage_memory_{rules}.md"
        qa_path = outputs / "qa" / (qa_name if not agent_filter else "pilot_" + qa_name)
        qa_path.parent.mkdir(parents=True, exist_ok=True)
        qa_path.write_text(render_qa(summary), encoding="utf-8")
        log(f"QA report: {qa_path}")
    return summary


def _strata_arrays(rows: pl.DataFrame, agent_ids: list[str], col: str, mapping) -> list[np.ndarray]:
    out = []
    for a in agent_ids:
        c = rows.filter((pl.col("agent_id") == a) & pl.col("is_cons"))
        out.append(np.array([mapping(v) for v in c[col].to_list()], dtype=np.int64))
    return out


def analyse(cfg, rows, rows_qa, agents, results, units_tab, occ, lems, ctx_noun_agents, cand, salt,
            seed, min_units, meta, write_outputs, agent_filter, log, n_workers: int = 1,
            rules: str = "v1", results_v1: dict[str, AgentResult] | None = None) -> dict:
    """Statistics and outputs for one rule set. For rules v2, `results` holds the
    v2 states (`units2`, `pairs2`) and `results_v1` the full chain results."""
    paths = cfg["paths"]
    outputs, interim, labels_dir = Path(paths["outputs"]), Path(paths["interim"]), Path(paths["labels"])
    prefix = "" if not agent_filter else "pilot_"
    suffix = "" if rules == "v1" else f"_{rules}"
    agent_ids = sorted(results)
    a_index = {a: i for i, a in enumerate(agent_ids)}
    A = len(agent_ids)
    ainfo = agents.select("agent_id", "name", "model_family", pl.col("scaffold").cast(pl.String))
    fam = dict(ainfo.select("agent_id", "model_family").iter_rows())
    scaffold = dict(ainfo.select("agent_id", "scaffold").iter_rows())
    name = dict(ainfo.select("agent_id", "name").iter_rows())
    group = {a: (CC_LABEL if scaffold.get(a) == "claude_code" else fam.get(a, "Other")) for a in agent_ids}
    std = np.array([i for a, i in a_index.items() if group[a] != CC_LABEL], dtype=np.int64)
    rows_by_agent = {a: rows.filter(pl.col("agent_id") == a) for a in agent_ids}

    # --- units table ---
    cols = defaultdict(list)
    for a in agent_ids:
        r = results[a]
        u = r.units
        k = len(u["unit"])
        rr = rows_by_agent[a]
        rel_names = rr["rel"].cast(pl.String).to_numpy()
        cols["agent"].append(np.full(k, a_index[a], dtype=np.int32))
        cols["K"].append(np.full(k, r.n_cons, dtype=np.int32))
        cols["entry_kind"].append(rel_names[u["entry_row"]] if k else np.array([], dtype=object))
        for key in ("unit", "entry_row", "entry_cons", "loss_cons", "event", "restore_cons",
                    "restore_src", "n_restore", "n_reloss", "reloss_cons", "n_fallback"):
            cols[key].append(u[key])
    U = {k: np.concatenate(v) for k, v in cols.items()}
    lost = U["loss_cons"] >= 0
    U["L"] = np.where(lost, U["loss_cons"] - U["entry_cons"], U["K"] - U["entry_cons"]).astype(np.int64)
    utype = units_tab.sort("unit_gid")["type"].to_numpy()
    U["type"] = utype[U["unit"]]
    ek = np.array(["first" if x == "first" else "session" if x == "append_session" else
                   "note" if x == "append_note" else "rewrite" if x == "rewrite" else
                   "fork" if x == "fork_append" else "other" for x in U["entry_kind"]], dtype=object)
    U["entry_kind"] = ek
    at_risk = U["L"] > 0
    is_std = np.isin(U["agent"], std)
    g_max = max(int(U["K"].max()) if len(U["K"]) else 1, 1)
    log(f"units tracked {len(U['unit']):,}; with >= 1 trial {int(at_risk.sum()):,}; max g {g_max:,}")

    rng = np.random.default_rng(seed + 1)
    W_all = {}

    def weights(sel_agents: np.ndarray, key: str) -> np.ndarray | None:
        if len(sel_agents) < 2:
            return None
        if key not in W_all:
            W_all[key] = sv.bootstrap_weights(sel_agents, A, BOOT_REPS, rng)
        return W_all[key]

    group_agents = {g: np.array([a_index[a] for a in agent_ids if group[a] == g], dtype=np.int64)
                    for g in (*FAMILIES, CC_LABEL)}
    group_agents[ALL_LABEL] = std

    def rc_for(mask: np.ndarray, strata=None, n_strata=1) -> sv.RiskCounts:
        return sv.risk_counts(U["entry_cons"][mask].astype(np.int64), U["L"][mask], U["event"][mask],
                              U["agent"][mask].astype(np.int64), A, g_max, strata, n_strata,
                              modified=(U["event"][mask] == EVENT_MODIFIED))

    scopes: list[Scope] = []
    base_mask = at_risk
    rc_all = rc_for(base_mask)
    for g in (ALL_LABEL, *FAMILIES, CC_LABEL):
        ag = group_agents[g]
        if len(ag) == 0:
            continue
        nu = int((base_mask & np.isin(U["agent"], ag)).sum())
        scopes.append(Scope("family", g, rc_all, 0, ag, weights(ag, g), nu))
    # Regime (trial-level), standard agents.
    reg = _strata_arrays(rows, agent_ids, "regime", lambda v: 1 if v == "post" else 0)
    rc_reg = rc_for(base_mask, reg, 2)
    for si, sname in enumerate(("pre", "post")):
        for g in (ALL_LABEL, *FAMILIES):
            ag = group_agents[g]
            if len(ag) == 0:
                continue
            sc = Scope(f"regime:{sname}", g, rc_reg, si, ag, weights(ag, g), -1)
            if sc.n_ag.sum() > 0:
                scopes.append(sc)
    # Memory-system epochs between memory-category CHANGELOG entries (trial-level).
    epoch_dates, epoch_labels = memory_epochs(cfg)
    ep = _strata_arrays(rows, agent_ids, "ts_pt",
                        lambda v: int(np.searchsorted(epoch_dates, np.datetime64(v.date()), side="right")) - 1)
    rc_ep = rc_for(base_mask, ep, len(epoch_dates))
    for j, lab in enumerate(epoch_labels):
        sc = Scope("memory_epoch", lab, rc_ep, j, std, weights(std, ALL_LABEL), -1)
        if sc.n_ag.sum() >= min_units:
            scopes.append(sc)
    # Entry kind (standard agents).
    for kind in ("first", "session", "note", "rewrite", "fork"):
        m = base_mask & is_std & (U["entry_kind"] == kind)
        if m.sum() == 0:
            continue
        rc = rc_for(m)
        scopes.append(Scope("entry_kind", kind, rc, 0, std, weights(std, ALL_LABEL), int(m.sum())))

    # --- hazard, modification, retention, H2 tables ---
    hz_rows, mod_rows, ret_rows, h2_rows = [], [], [], []
    h2_results: dict[tuple[str, str], sv.H2Test] = {}
    for sc in scopes:
        b = sc.binned(G_TABLE_BINS)
        for j, (lo, hi) in enumerate(G_TABLE_BINS):
            if b["n"][j] < min_units:
                continue
            g_label = str(lo) if lo == hi else (f"{lo}-{hi}" if hi else f"{lo}+")
            hz_rows.append({
                "scope": sc.scope, "stratum": sc.stratum, "g": g_label, "g_lo": lo, "g_hi": hi or "",
                "n_at_risk": int(b["n"][j]), "n_lost": int(b["d"][j]),
                "n_dropped": int(b["d"][j] - b["m"][j]), "n_modified": int(b["m"][j]),
                "h": b["h"][j], "h_lo": b["h_lo"][j], "h_hi": b["h_hi"][j],
                "n_agents": int(b["n_agents"][j]), "ci_method": b["method"],
            })
            if sc.scope in ("family", "entry_kind") or sc.scope.startswith("regime"):
                mod_rows.append({
                    "scope": sc.scope, "stratum": sc.stratum, "g": g_label, "g_lo": lo, "g_hi": hi or "",
                    "n_at_risk": int(b["n"][j]), "n_lost": int(b["d"][j]), "n_modified": int(b["m"][j]),
                    "modification_rate": b["mr"][j], "modification_rate_lo": b["mr_lo"][j],
                    "modification_rate_hi": b["mr_hi"][j], "modified_share_of_losses": b["ms"][j],
                    "modified_share_lo": b["ms_lo"][j], "modified_share_hi": b["ms_hi"][j],
                    "ci_method": b["method"],
                })
        if sc.scope in ("family", "entry_kind"):
            t2 = sc.h2()
            h2_results[(sc.scope, sc.stratum)] = t2
            k = sc.km(G_KM)
            geo = (1 - t2.h_geom) ** np.arange(1, G_KM + 1)
            gg = np.arange(1, G_KM + 1)
            bg = (np.cumprod(1 - t2.bg_alpha / (t2.bg_alpha + t2.bg_beta + gg - 1))
                  if np.isfinite(t2.bg_alpha) else np.full(G_KM, np.nan))
            for j in range(G_KM):
                if k["n"][j] < min_units:
                    break
                ret_rows.append({
                    "scope": sc.scope, "stratum": sc.stratum, "g": j + 1, "n_at_risk": int(k["n"][j]),
                    "retention": k["s"][j], "retention_lo": k["lo"][j], "retention_hi": k["hi"][j],
                    "geometric_fit": geo[j], "beta_geometric_fit": bg[j],
                })
        elif sc.scope.startswith("regime") or sc.scope == "memory_epoch":
            t2 = sc.h2(fit_betageom=False)
            h2_results[(sc.scope, sc.stratum)] = t2
        else:
            continue
        h2_rows.append(_h2_row(sc, t2))

    # --- by anchor type ---
    anchor_rows = []
    anchor_scopes: dict[str, Scope] = {}
    for ti, tname in enumerate(TYPES):
        mt = base_mask & (U["type"] == ti)
        if mt.sum() == 0:
            continue
        rc = rc_for(mt)
        for g in (ALL_LABEL, *FAMILIES, CC_LABEL):
            ag = group_agents[g]
            m = mt & np.isin(U["agent"], ag)
            if m.sum() == 0:
                continue
            sc = Scope("anchor_type", g, rc, 0, ag, weights(ag, g), int(m.sum()))
            if g == ALL_LABEL:
                anchor_scopes[tname] = sc
            n_tot = sc.n_ag.sum()
            if n_tot < min_units:
                continue
            b = sc.binned(sv.PIECEWISE_BINS)
            t2 = sc.h2()
            lost_m = m & (U["loss_cons"] >= 0)
            post_loss = lost_m & (U["K"] > U["loss_cons"])
            restored = post_loss & (U["restore_cons"] >= 0)
            row = {"anchor_type": tname, "stratum": g, "n_units": int(m.sum()),
                   "n_trials": int(n_tot), "n_lost": int(t2.n_events)}
            for j, lab in enumerate(("h1", "h2", "h3_4", "h5_8", "h9plus")):
                row[lab] = b["h"][j] if b["n"][j] >= min_units else np.nan
                row[f"{lab}_lo"] = b["h_lo"][j] if b["n"][j] >= min_units else np.nan
                row[f"{lab}_hi"] = b["h_hi"][j] if b["n"][j] >= min_units else np.nan
            row.update({
                "h_geometric": t2.h_geom, "lr": t2.lr, "p_lr": t2.p_lr, "wald": t2.wald, "p_wald": t2.p_wald,
                "modification_rate": float(sc.m_ag.sum() / n_tot) if n_tot else np.nan,
                "modified_share_of_losses": float(sc.m_ag.sum() / sc.d_ag.sum()) if sc.d_ag.sum() else np.nan,
                "restored_share_of_lost": float(restored.sum() / post_loss.sum()) if post_loss.sum() else np.nan,
                "reappended_share_of_restored": float(
                    (restored & (U["restore_src"] == SRC_REAPPENDED)).sum() / restored.sum())
                if restored.sum() else np.nan,
                "n_agents": int(len(np.unique(U["agent"][m]))),
            })
            anchor_rows.append(row)

    # --- heterogeneity vs duration dependence (BdW) ---
    c_switch = np.array([int(np.argmax(r == 1)) + 1 if (r == 1).any() else len(r) + 1 for r in reg],
                        dtype=np.int64)
    cs_u = c_switch[U["agent"]]
    room_pre = cs_u - 1 - U["entry_cons"]  # trials before the agent's first post consolidation
    cohorts = {}
    for cname, cm, L_c, ev_c in (
        ("pre", base_mask & is_std & (room_pre > 0), np.minimum(U["L"], room_pre),
         np.where(U["L"] <= room_pre, U["event"], 0)),
        ("post", base_mask & is_std & (room_pre <= 0), U["L"], U["event"]),
    ):
        rc = sv.risk_counts(U["entry_cons"][cm].astype(np.int64), L_c[cm], ev_c[cm].astype(np.int8),
                            U["agent"][cm].astype(np.int64), A, g_max,
                            modified=(ev_c[cm] == EVENT_MODIFIED))
        cohorts[cname] = Scope("regime_cohort", cname, rc, 0, std, weights(std, ALL_LABEL), int(cm.sum()))
    fam_sc = {sc.stratum: sc for sc in scopes if sc.scope == "family"}
    # (scope, stratum, counts, first g used). From g = 2 is the exact likelihood
    # conditional on surviving the first consolidation (a sensitivity check).
    bdw_scopes = ([("family", g, fam_sc[g], 1) for g in (ALL_LABEL, *FAMILIES, CC_LABEL) if g in fam_sc]
                  + [("regime_cohort", k, cohorts[k], 1) for k in ("pre", "post")]
                  + [("anchor_type", t, anchor_scopes[t], 1) for t in TYPES if t in anchor_scopes]
                  + [("family", ALL_LABEL, fam_sc[ALL_LABEL], 2)] * (ALL_LABEL in fam_sc)
                  + [("regime_cohort", k, cohorts[k], 2) for k in ("pre", "post")])
    t_bdw = time.perf_counter()
    bdw_out = bdw_rows(bdw_scopes, n_workers)
    log(f"BdW fits for {len(bdw_out)} scopes in {time.perf_counter() - t_bdw:.0f} s")

    # --- repeated spells (restored facts) ---
    # Spell 2 runs from the first restoration to the first re-loss, as the chain recorded them.
    restored_u = U["restore_cons"] >= 0
    U["L2"] = np.where(restored_u, np.where(U["reloss_cons"] >= 0, U["reloss_cons"] - U["restore_cons"],
                                            U["K"] - U["restore_cons"]), -1).astype(np.int64)
    U["ev2"] = (restored_u & (U["reloss_cons"] >= 0)).astype(np.int8)
    spell_check = {
        "restored": int(restored_u.sum()),
        "with_second_spell_trials": int((restored_u & (U["L2"] > 0)).sum()),
        "second_spell_lost": int((restored_u & (U["ev2"] == 1)).sum()),
        "relost_in_chain": int((restored_u & (U["n_reloss"] > 0)).sum()),
        "mismatch_vs_chain": None,
        "restoration_not_present": None,
    }
    if rules == "v1":
        # Cross-check against the row-level presence spells (v1 presence is anchor presence).
        l2_parts, ev2_parts, spell_bad = [], [], 0
        for a in agent_ids:
            L2s, ev2s, bad = second_spells(results[a])
            l2_parts.append(L2s)
            ev2_parts.append(ev2s)
            spell_bad += bad
        L2s = np.concatenate(l2_parts) if l2_parts else np.zeros(0, np.int64)
        ev2s = np.concatenate(ev2_parts) if ev2_parts else np.zeros(0, np.int8)
        spell_check["mismatch_vs_chain"] = int((restored_u & ((L2s != U["L2"]) | (ev2s != U["ev2"]))).sum())
        spell_check["restoration_not_present"] = int(spell_bad)
    rs_rows = repeat_spell_rows(U, base_mask, is_std, group_agents, fam_sc, A, g_max, weights, min_units)

    # --- monthly hazards for module C (trial-level, standard agents) ---
    monthly = monthly_hazard_table(rows, agent_ids, U, base_mask & is_std, A, g_max, group_agents,
                                   min_units)

    # --- CHANGELOG windows (standard agents) ---
    cl_rows = changelog_windows(cfg, rows, agent_ids, U, base_mask & is_std, A, std, seed, min_units,
                                g_max)

    # --- restoration summary ---
    rest = {}
    for g in (ALL_LABEL, *FAMILIES, CC_LABEL):
        m = base_mask & np.isin(U["agent"], group_agents[g]) & (U["loss_cons"] >= 0)
        pl_ = m & (U["K"] > U["loss_cons"])
        r_ = pl_ & (U["restore_cons"] >= 0)
        gaps = (U["restore_cons"] - U["loss_cons"])[r_]
        rest[g] = {
            "lost": int(m.sum()), "lost_with_later_trials": int(pl_.sum()), "restored": int(r_.sum()),
            "share": float(r_.sum() / pl_.sum()) if pl_.sum() else float("nan"),
            "reappended": int((r_ & (U["restore_src"] == SRC_REAPPENDED)).sum()),
            "recreated": int((r_ & (U["restore_src"] == SRC_RECREATED)).sum()),
            "gap_median": float(np.median(gaps)) if len(gaps) else float("nan"),
            "within_1": float((gaps == 1).mean()) if len(gaps) else float("nan"),
            "relost": int((U["n_reloss"][m] > 0).sum()),
        }

    # --- consolidation-level QA ---
    cons_tot = Counter()
    for a in agent_ids:
        for key, v in results[a].cons.items():
            if key != "row":
                cons_tot[key] += int(v.sum())
    chain_qa = Counter()
    for a in agent_ids:
        chain_qa.update(results[a].qa)
    # Verbatim line retention per consolidation (cross-check with schema_notes 4.2).
    line_acc: dict[tuple[str, str], Counter] = defaultdict(Counter)
    line_share: dict[tuple[str, str], list[float]] = defaultdict(list)
    units_in: dict[tuple[str, str], list[int]] = defaultdict(list)
    for a in agent_ids:
        r = results[a]
        if not len(r.cons["row"]):
            continue
        reg_a = rows_by_agent[a]["regime"].to_numpy()[r.cons["row"]]
        for regime in ("pre", "post"):
            m = reg_a == regime
            if not m.any():
                continue
            keys = [(group[a], regime)] + ([(ALL_LABEL, regime)] if group[a] != CC_LABEL else [])
            tot = r.cons["lines_old"][m] + r.cons["lines_new"][m]
            kept = r.cons["lines_old_kept"][m] + r.cons["lines_new_kept"][m]
            for key in keys:
                for col in ("lines_old", "lines_old_kept", "lines_new", "lines_new_kept"):
                    line_acc[key][col] += int(r.cons[col][m].sum())
                line_acc[key]["cons"] += int(m.sum())
                line_share[key].extend((kept[tot > 0] / tot[tot > 0]).tolist())
                units_in[key].extend(r.cons["units_in"][m].tolist())
    line_ret = []
    for (g, regime), acc in sorted(line_acc.items()):
        sh = np.array(line_share[(g, regime)])
        line_ret.append({
            "group": g, "regime": regime, "consolidations": acc["cons"],
            "old_kept": acc["lines_old_kept"] / acc["lines_old"] if acc["lines_old"] else float("nan"),
            "new_kept": acc["lines_new_kept"] / acc["lines_new"] if acc["lines_new"] else float("nan"),
            "share_median": float(np.median(sh)) if len(sh) else float("nan"),
            "share_q25": float(np.quantile(sh, 0.25)) if len(sh) else float("nan"),
            "share_q75": float(np.quantile(sh, 0.75)) if len(sh) else float("nan"),
            "units_in_median": float(np.median(units_in[(g, regime)])) if units_in[(g, regime)] else float("nan"),
        })

    # --- outputs ---
    tables_dir = outputs / "tables"
    out_files = {}
    if write_outputs:
        tables_dir.mkdir(parents=True, exist_ok=True)
        out_files["hazard"] = _write_csv(tables_dir / f"{prefix}memory_hazard{suffix}.csv", hz_rows)
        out_files["retention"] = _write_csv(tables_dir / f"{prefix}memory_retention{suffix}.csv", ret_rows)
        out_files["modification"] = _write_csv(tables_dir / f"{prefix}memory_modification{suffix}.csv", mod_rows)
        out_files["by_anchor"] = _write_csv(tables_dir / f"{prefix}memory_by_anchor{suffix}.csv", anchor_rows)
        out_files["h2"] = _write_csv(tables_dir / f"{prefix}memory_h2{suffix}.csv", h2_rows)
        out_files["changelog"] = _write_csv(tables_dir / f"{prefix}memory_changelog{suffix}.csv", cl_rows)
        out_files["bdw"] = _write_csv(tables_dir / f"{prefix}memory_bdw{suffix}.csv", bdw_out)
        out_files["repeat_spells"] = _write_csv(tables_dir / f"{prefix}memory_repeat_spells{suffix}.csv", rs_rows)
        monthly.write_parquet(tables_dir / f"{prefix}memory_hazard_monthly{suffix}.parquet")
        monthly.write_csv(tables_dir / f"{prefix}memory_hazard_monthly{suffix}.csv", float_precision=6)
        out_files["hazard_monthly"] = (str(tables_dir / f"{prefix}memory_hazard_monthly{suffix}.parquet")
                                       + " (+ .csv)")
        fig_base = outputs / "figures" / f"{prefix}F6_memory_retention{suffix}"
        plot_retention(scopes, h2_results, ret_rows, fig_base, min_units)
        out_files["figure"] = str(fig_base) + ".{pdf,png}"

    # --- labels and memory_facts ---
    ctx_common = np.zeros(lems.height, dtype=bool)
    for cid, nag in ctx_noun_agents.items():
        if nag >= CTX_MIN_AGENTS and 0 <= cid < len(ctx_common):
            ctx_common[cid] = True
    lemma = lems.sort("ctx_id")["lemma"].to_list()

    def ctx_display(cid: int) -> str:
        if cid < 0:
            return ""
        return lemma[cid] if ctx_common[cid] else keyed_hash(salt, "ctx", lemma[cid], 8)

    if rules == "v1":
        label_info = write_labels(results, rows_by_agent, cand, units_tab, occ, ctx_display, salt, seed,
                                  labels_dir / f"{prefix}memory_pairs.csv" if write_outputs else None)
    else:
        label_info = write_rule_version(results_v1, rows_by_agent, units_tab, ctx_display, salt,
                                        labels_dir / f"{prefix}memory_pairs.csv",
                                        labels_dir / f"{prefix}memory_pairs_rule_{rules}.csv" if write_outputs
                                        else None, rules)
    facts_info = write_facts(results, rows_by_agent, agent_ids, units_tab, ctx_display, U,
                             interim / f"{prefix}memory_facts{suffix}.parquet" if write_outputs else None)

    # --- summary for the QA report ---
    ts = rows["created_at"]
    per_group = {}
    for g in (ALL_LABEL, *FAMILIES, CC_LABEL):
        ag = group_agents[g]
        if len(ag) == 0:
            continue
        cons_g = sum(results[agent_ids[i]].n_cons for i in ag)
        m = np.isin(U["agent"], ag)
        per_group[g] = {"agents": int(len(ag)), "consolidations": int(cons_g),
                        "units": int(m.sum()), "units_at_risk": int((m & at_risk).sum()),
                        "unit_trials": int(U["L"][m & at_risk].sum())}
    type_counts = {TYPES[t]: int((U["type"] == t).sum()) for t in range(len(TYPES))}
    occ_types = dict(Counter(occ["type"].to_list()))
    empty_ctx = dict(occ.group_by("type").agg((pl.col("ctx_id") < 0).mean()).iter_rows())
    hashed_units = int(units_tab["value"].str.starts_with("h:").sum())
    missing = {
        "rows without run_day": int(rows["run_day"].null_count()),
        "rows without regime": int(rows["regime"].null_count()),
        "consolidations without run_day": int(rows.filter(pl.col("is_cons"))["run_day"].null_count()),
    }
    summary = {
        "seed": seed, "missing": missing, "rules": rules,
        "empty_ctx": {TYPES[int(k)]: float(v) for k, v in empty_ctx.items()},
    }
    summary.update({
        "rows_qa": rows_qa, "meta": meta, "n_agents": A, "agents_total": agents.height,
        "agent_names": {a: name.get(a, "?") for a in agent_ids}, "group": group,
        "time_range": (ts.min(), ts.max()), "per_group": per_group, "type_counts": type_counts,
        "occ_type_counts": {TYPES[k]: v for k, v in occ_types.items()},
        "n_units_total": int(len(U["unit"])), "n_units_at_risk": int(at_risk.sum()),
        "hashed_units": hashed_units, "n_occurrences": occ.height, "n_unit_keys": units_tab.height,
        "entry_kinds": dict(Counter(U["entry_kind"].tolist())),
        "events": {"dropped": int((U["event"] == EVENT_DROPPED).sum()),
                   "modified": int((U["event"] == EVENT_MODIFIED).sum()),
                   "censored": int(((U["event"] == 0) & at_risk).sum())},
        "restoration": rest, "cons_tot": dict(cons_tot), "chain_qa": dict(chain_qa),
        "line_retention": line_ret,
        "bdw_rows": bdw_out, "repeat_rows": rs_rows, "spell_check": spell_check,
        "monthly": {"rows": monthly.height, "months": monthly["date"].n_unique(),
                    "first": str(monthly["date"].min()), "last": str(monthly["date"].max()),
                    "null_h1": int(monthly["h1"].null_count())},
        "accounting": {
            "unit_trials_from_units": int(U["L"][at_risk].sum()),
            "unit_trials_from_consolidations": int(cons_tot.get("at_risk", 0)),
            "losses_from_units": int((U["event"] > 0).sum()),
            "losses_from_consolidations": int(cons_tot.get("dropped", 0) + cons_tot.get("modified", 0)),
        },
        "hazard_rows": hz_rows, "mod_rows": mod_rows, "anchor_rows": anchor_rows, "h2_rows": h2_rows,
        "changelog_rows": cl_rows, "labels": label_info, "facts": facts_info,
        "min_units": min_units, "out_files": out_files, "agent_filter": agent_filter,
        "ctx_common": int(ctx_common.sum()), "ctx_total": int(len(ctx_common)),
        "per_agent": {a: {"cons": results[a].n_cons, "units": int((U["agent"] == a_index[a]).sum())}
                      for a in agent_ids},
    })
    summary["verdict_lines"] = verdict_lines(summary)
    return summary


def verdict_lines(s: dict) -> list[str]:
    """Plain statements comparing the results with the expectations of SPEC 6.2 H2 and schema_notes."""
    out = []
    rq = s["rows_qa"]
    if not s["agent_filter"]:
        out.append(
            f"- Consolidations: {rq['consolidations']:,} live REWRITE rows; memory_versions has 85,603 "
            f"rewrites, so {85_603 - rq['consolidations']:,} sit on {rq['dead_generations']} abandoned "
            f"lineage branches (memory_versions QA: 3 generations whose parent is not the previous one in "
            f"time). Agents covered: {s['n_agents']} of {s['agents_total']}.")
    for r in s["h2_rows"]:
        if r["scope"] != "family":
            continue
        p = r["p_wald_cluster"] if np.isfinite(r["p_wald_cluster"]) else r["p_lr"]
        test = "cluster Wald" if np.isfinite(r["p_wald_cluster"]) else "LR"
        h1, h9 = r["h1"], r["h9plus"]
        trend = ("decreases" if h9 < h1 else "increases") if np.isfinite(h1) and np.isfinite(h9) else "n/a"
        best = min((("geometric", r["aic_geometric"]), ("beta-geometric", r["aic_betageom"]),
                    ("piecewise", r["aic_piecewise"])), key=lambda kv: kv[1] if np.isfinite(kv[1]) else 1e300)
        out.append(
            f"- {r['stratum']}: H2 (constant hazard) is {'rejected' if p < 0.05 else 'not rejected'} at 5% "
            f"({test} p = {_fmt_p(p)}; naive LR = {_fmt(r['lr'], 1)}, df {r['df']}). The hazard {trend} "
            f"from {_fmt(h1)} at g = 1 to {_fmt(h9)} at g >= 9; lowest AIC: {best[0]}.")
    fa = next((r for r in s["h2_rows"] if r["scope"] == "family" and r["stratum"] == ALL_LABEL), None)
    if fa and np.isfinite(fa["aic_betageom"]):
        a, b = fa["betageom_alpha"], fa["betageom_beta"]
        out.append(
            f"- Heterogeneity: for all standard agents the beta-geometric model (2 parameters) lowers AIC by "
            f"{fa['aic_geometric'] - fa['aic_betageom']:,.0f} against the geometric model and by "
            f"{fa['aic_piecewise'] - fa['aic_betageom']:,.0f} against the 5-bin piecewise hazard. Most of the "
            f"decline of h_g is therefore what a mix of units with different but constant hazards produces "
            f"(fitted mean hazard a / (a + b) = {a / (a + b):.3f}): units that survive early consolidations "
            f"are the durable ones. H2 fails at the population level, not necessarily for a single unit.")
    ek = {r["stratum"]: r for r in s["h2_rows"] if r["scope"] == "entry_kind"}
    if "rewrite" in ek or "session" in ek:
        parts = [f"{k} h1 = {_fmt(v['h1'])}" for k, v in ek.items() if np.isfinite(v["h1"])]
        out.append(
            "- Expectation (schema_notes 4.2): a rewrite keeps 40-70% of its input lines, so units already in "
            "consolidated memory should face a first-consolidation hazard of roughly 0.3-0.6, and units that "
            "arrive in appended session logs a higher one, because a consolidation compresses those logs. "
            "Observed by entry kind: " + "; ".join(parts) + ".")
    lr = {(r["group"], r["regime"]): r for r in s["line_retention"]}
    parts = [f"{reg} {_fmt(v['share_median'])} (IQR {_fmt(v['share_q25'])}-{_fmt(v['share_q75'])})"
             for reg in ("pre", "post") if (v := lr.get((ALL_LABEL, reg)))]
    if parts:
        out.append("- Verbatim line retention, standard agents (schema_notes 4.2: a rewrite keeps 40-70% of its "
                   "lines): median share of input lines kept unchanged per consolidation, " + "; ".join(parts)
                   + ". Unit-level retention is higher than line-level retention wherever rewrites rephrase "
                   "lines but keep their values.")
    reg = {r["scope"]: r for r in s["h2_rows"] if r["scope"].startswith("regime") and r["stratum"] == ALL_LABEL}
    if "regime:pre" in reg and "regime:post" in reg:
        a, b = reg["regime:pre"], reg["regime:post"]
        out.append(f"- Regime: before perma-computer-use h1 = {_ci(a, 'h1')}, h9+ = {_ci(a, 'h9plus')}; after it "
                   f"h1 = {_ci(b, 'h1')}, h2 = {_ci(b, 'h2')}, h9+ = {_ci(b, 'h9plus')}. After the switch "
                   "a consolidation follows every session, so one consolidation is a shorter time step, and "
                   "the consolidation right after a session keeps more of it than the next one does (the "
                   "hazard rises from g = 1 to g = 2), which no constant or monotone hazard model reproduces.")
    sig = []
    for r in s["changelog_rows"]:
        for lab, name in (("g1", "g = 1"), ("g2plus", "g >= 2")):
            lo, hi = r.get(f"diff_{lab}_lo"), r.get(f"diff_{lab}_hi")
            if lo is not None and np.isfinite(lo) and (lo > 0 or hi < 0):
                sig.append(f"{r['entry_id']} ({name}: {_fmt(r[f'diff_{lab}'])} [{_fmt(lo)}, {_fmt(hi)}])")
    tested = sum(1 for r in s["changelog_rows"] for lab in ("g1", "g2plus")
                 if np.isfinite(r.get(f"diff_{lab}_lo", np.nan)))
    out.append(f"- CHANGELOG memory entries: {tested} before/after hazard differences have a CI; "
               + (f"{len(sig)} exclude zero: " + "; ".join(sig) if sig else "none excludes zero")
               + ". Windows are short and other changes overlap, so these are associations.")
    ev = s["events"]
    tot = ev["dropped"] + ev["modified"]
    if tot:
        out.append(f"- Modifications are {ev['modified'] / tot:.1%} of first losses "
                   f"({ev['modified']:,} of {tot:,}); the rest are drops.")
    rs = s["restoration"].get(ALL_LABEL)
    if rs and rs["lost_with_later_trials"]:
        out.append(f"- Restoration: {rs['share']:.1%} of lost units with later consolidations come back "
                   f"({rs['reappended']:,} re-appended, {rs['recreated']:,} recreated by a consolidation).")
    bdw = {(r["scope"], r["stratum"], r["g_from"]): r for r in s.get("bdw_rows", [])}
    parts = []
    for key in ([("family", g, 1) for g in (ALL_LABEL, *FAMILIES, CC_LABEL)]
                + [("regime_cohort", k, 1) for k in ("pre", "post")]
                + [("family", ALL_LABEL, 2)] + [("regime_cohort", k, 2) for k in ("pre", "post")]):
        r = bdw.get(key)
        if r is not None:
            name = r["stratum"] if key[0] == "family" else f"{key[1]} cohort"
            parts.append(f"{name}{' from g = 2' if key[2] == 2 else ''} "
                         f"c = {_fmt(r['c'])} [{_fmt(r['c_lo'])}, {_fmt(r['c_hi'])}]")
    if parts:
        main = [r for r in s["bdw_rows"] if r["g_from"] == 1]
        below = [r for r in main if np.isfinite(r["c_hi"]) and r["c_hi"] < 1]
        cover = [r for r in main if np.isfinite(r["c_lo"]) and r["c_lo"] <= 1 <= r["c_hi"]]
        above = [r for r in main if np.isfinite(r["c_lo"]) and r["c_lo"] > 1]
        a_all = bdw.get(("family", ALL_LABEL, 1))
        out.append(
            "- Heterogeneity vs duration dependence (BdW): " + "; ".join(parts) + ". "
            f"Of {len(main)} main scopes, c lies below 1 in {len(below)}, covers 1 in {len(cover)} and "
            f"lies above 1 in {len(above)}"
            + (f"; for all standard agents the BdW improves AIC by "
               f"{a_all['aic_beta_geometric'] - a_all['aic_bdw']:,.0f} over the beta-geometric "
               f"(LR {_fmt(a_all['lr_c1'], 0)}, p {_fmt_p(a_all['p_c1'])}) and the lowest AIC is "
               f"{a_all['best_aic']}" if a_all else "") + ". " + IDENTIFICATION_NOTE)
    rr = [r for r in s.get("repeat_rows", []) if r["group"] == ALL_LABEL]
    if rr:
        def cell(subset: str, g: str) -> str:
            r = next((x for x in rr if x["subset"] == subset and x["g"] == g), None)
            if r is None:
                return f"g = {g}: n/a"
            return (f"g = {g}: spell 1 {_fmt(r['h_spell1'])}, spell 2 {_fmt(r['h_spell2'])}, difference "
                    f"{_fmt(r['diff'])} [{_fmt(r['diff_lo'])}, {_fmt(r['diff_hi'])}]")
        n_all = next((x["n_facts"] for x in rr if x["subset"] == "all restored"), 0)
        n_like = next((x["n_facts"] for x in rr if x["subset"] == "like for like"), 0)
        out.append(
            f"- Repeated spells (standard agents): {n_all:,} restored facts with a second spell; "
            + "; ".join(cell("all restored", g) for g in ("1", "2", "9+"))
            + f". Like-for-like subset ({n_like:,} facts): "
            + "; ".join(cell("like for like", g) for g in ("1", "2", "9+"))
            + ". Descriptive only: spell 1 is selected to end in a loss, which biases its hazards upward "
              "(a negative difference is expected even with no change), and some restorations are key "
              "collisions.")
    miss = s["missing"]
    out.append("- Missing values: " + ", ".join(f"{k} {v:,}" for k, v in miss.items()) + ".")
    return out


def _h2_row(sc: Scope, t2: sv.H2Test) -> dict:
    row = {"scope": sc.scope, "stratum": sc.stratum, "n_agents": sc.n_contrib,
           "n_units": sc.n_units if sc.n_units >= 0 else "", "n_trials": int(t2.n_trials),
           "n_lost": int(t2.n_events), "h_geometric": t2.h_geom}
    b = sc.binned(sv.PIECEWISE_BINS)  # same CIs as memory_hazard.csv (Wilson for one agent)
    for j, lab in enumerate(("h1", "h2", "h3_4", "h5_8", "h9plus")):
        row[lab] = b["h"][j]
        row[f"{lab}_lo"] = b["h_lo"][j]
        row[f"{lab}_hi"] = b["h_hi"][j]
    row.update({
        "ll_geometric": t2.ll_geom, "ll_piecewise": t2.ll_piecewise, "lr": t2.lr, "df": t2.df,
        "p_lr": t2.p_lr, "wald_cluster": t2.wald, "df_wald": t2.df_wald, "p_wald_cluster": t2.p_wald,
        "betageom_alpha": t2.bg_alpha, "betageom_beta": t2.bg_beta, "ll_betageom": t2.ll_betageom,
        "aic_geometric": t2.aic_geom, "aic_betageom": t2.aic_betageom, "aic_piecewise": t2.aic_piecewise,
        "ci_method": "cluster_bootstrap" if sc.cluster else "none (one agent)",
    })
    return row


def bdw_rows(bdw_scopes: list[tuple[str, str, Scope, int]], n_workers: int) -> list[dict]:
    """BdW vs beta-geometric vs piecewise per scope; c with cluster-bootstrap and profile CIs.

    The beta-geometric is the BdW with c = 1 fitted to the same counts, so the
    likelihood-ratio test of c = 1 has one degree of freedom (units treated as
    independent, hence anticonservative). The decision rule uses the
    cluster-bootstrap CI of c (agents resampled, B_BDW refits); for a single
    agent the profile-likelihood CI is the only one available. Each item is
    (scope, stratum, counts, g_from); g_from = 2 drops the first trial, which
    gives the likelihood conditional on surviving the first consolidation.
    `converged`: both fits pass `survival.bdw_newton_check`; `boundary`: the
    Beta mixing of the BdW fit sits at a limit of its range (`survival.bdw_boundary`),
    so c is weakly identified.
    """
    fits = []
    for _, _, sc, g_from in bdw_scopes:
        n, d, _ = sc.totals()
        n, d = n.copy(), d.copy()
        n[:g_from], d[:g_from] = 0, 0
        bg = sv.fit_bdw(n, d, c_fixed=1.0)
        bdw = sv.fit_bdw(n, d)
        if np.isfinite(bg.ll) and (not np.isfinite(bdw.ll) or bdw.ll < bg.ll):
            alt = sv.fit_bdw(n, d, start=(bg.alpha, bg.beta, 1.0))
            bdw = alt if not np.isfinite(bdw.ll) or alt.ll > bdw.ll else bdw
        fits.append((sc, n, d, bg, bdw, sv.bdw_profile_ci(n, d, bdw)))
    tasks = []
    for i, (sc, _, _, _, bdw, _) in enumerate(fits):
        if sc.cluster and np.isfinite(bdw.c):
            g_from = bdw_scopes[i][3]
            nag, dag = sc.n_ag.copy(), sc.d_ag.copy()
            nag[:, :g_from], dag[:, :g_from] = 0, 0
            tasks.append((i, nag, dag, sc.w[:B_BDW], (bdw.alpha, bdw.beta, bdw.c)))
    boots: dict[int, np.ndarray] = {}
    if tasks:
        with ProcessPoolExecutor(max(1, min(n_workers, len(tasks))), mp_context=mp.get_context("spawn")) as ex:
            futs = {ex.submit(sv.bdw_bootstrap, nag, dag, w, st): i for i, nag, dag, w, st in tasks}
            for f in as_completed(futs):
                boots[futs[f]] = f.result()
    out = []
    for i, (sc, n, d, bg, bdw, prof) in enumerate(fits):
        ll_pw, k_pw = sv.piecewise_loglik(n, d, sc.g_max)
        ll_geo = sv.geometric_loglik(n, d)
        lr = max(0.0, 2 * (bdw.ll - bg.ll)) if np.isfinite(bdw.ll) and np.isfinite(bg.ll) else np.nan
        if i in boots:
            cb = boots[i][:, 2]
            cb = cb[np.isfinite(cb)]
            c_lo, c_hi = np.percentile(cb, [2.5, 97.5]) if len(cb) > 20 else (np.nan, np.nan)
            method, n_boot = "cluster_bootstrap", int(len(cb))
        else:
            c_lo, c_hi = prof
            method, n_boot = "profile_likelihood (one agent)", 0
        if not np.isfinite(c_lo):
            verdict = "n/a"
        elif c_lo <= 1 <= c_hi:
            verdict = "heterogeneity alone (c consistent with 1)"
        elif c_hi < 1:
            verdict = "duration dependence: a fact's own hazard falls with g"
        else:
            verdict = "c > 1: a fact's own hazard rises with g"
        aic = {"bdw": 6 - 2 * bdw.ll, "beta_geometric": 4 - 2 * bg.ll,
               "piecewise": 2 * k_pw - 2 * ll_pw, "geometric": 2 - 2 * ll_geo}
        scope_name, stratum, _, g_from = bdw_scopes[i]
        row = {
            "scope": scope_name, "stratum": stratum, "g_from": g_from, "n_agents": sc.n_contrib,
            "n_units": int(n[g_from]) if g_from > 1 else (sc.n_units if sc.n_units >= 0 else ""),
            "n_trials": int(n[1:].sum()),
            "n_lost": int(d[1:].sum()),
            "c": bdw.c, "c_lo": c_lo, "c_hi": c_hi, "c_ci_method": method, "n_boot": n_boot,
            "c_lo_profile": prof[0], "c_hi_profile": prof[1],
            "alpha": bdw.alpha, "beta": bdw.beta, "bg_alpha": bg.alpha, "bg_beta": bg.beta,
            "ll_bdw": bdw.ll, "ll_beta_geometric": bg.ll, "ll_piecewise": ll_pw, "ll_geometric": ll_geo,
            "lr_c1": lr, "p_c1": float(stats.chi2.sf(lr, 1)) if np.isfinite(lr) else np.nan,
            "aic_bdw": aic["bdw"], "aic_beta_geometric": aic["beta_geometric"],
            "aic_piecewise": aic["piecewise"], "aic_geometric": aic["geometric"],
            "best_aic": min(aic, key=lambda k: aic[k] if np.isfinite(aic[k]) else np.inf),
            "converged": bool(bdw.converged and bg.converged), "boundary": sv.bdw_boundary(bdw.alpha, bdw.beta),
            "verdict": verdict,
        }
        g_show = np.array([g for g in BDW_G_SHOW if g_from <= g < len(n) and n[g] > 0], dtype=np.int64)
        h_bdw = sv.bdw_hazard(bdw.alpha, bdw.beta, bdw.c, g_show) if len(g_show) and np.isfinite(bdw.c) else []
        h_bg = sv.bdw_hazard(bg.alpha, bg.beta, 1.0, g_show) if len(g_show) and np.isfinite(bg.alpha) else []
        for j, g in enumerate(g_show.tolist()):
            row[f"h{g}_observed"] = d[g] / n[g]
            row[f"h{g}_bdw"] = h_bdw[j] if len(h_bdw) else np.nan
            row[f"h{g}_beta_geometric"] = h_bg[j] if len(h_bg) else np.nan
        out.append(row)
    return out


def second_spells(res: AgentResult) -> tuple[np.ndarray, np.ndarray, int]:
    """Second consolidation-level spell of every restored unit, aligned with `res.units`.

    The spell starts at the first restoring consolidation r1 (the unit is in
    R_r1) and its trial g is consolidation r1 + g. It ends with a loss at the
    first later consolidation whose output lacks the unit, or is censored after
    the agent's last consolidation. Presence comes from the row-level spells,
    so a loss here is the chain's first re-loss (checked by the caller).
    Returns L2 (-1 for units never restored), the event flag, and the number of
    restored units absent from R_r1 in the spells (expected 0).
    """
    u = res.units
    L2 = np.full(len(u["unit"]), -1, dtype=np.int64)
    ev2 = np.zeros(len(u["unit"]), dtype=np.int8)
    sel = np.flatnonzero(u["restore_cons"] >= 0)
    if not len(sel):
        return L2, ev2, 0
    K = res.n_cons
    crow = res.cons["row"].astype(np.int64)
    sp = res.spells
    order = np.lexsort((sp["start_row"], sp["unit"]))
    su = sp["unit"][order]
    ss = sp["start_row"][order].astype(np.int64)
    big = np.iinfo(np.int64).max
    se = np.where(sp["end_row"][order] < 0, big, sp["end_row"][order].astype(np.int64))
    uniq, first = np.unique(su, return_index=True)
    span = dict(zip(uniq.tolist(), zip(first.tolist(), np.append(first[1:], len(su)).tolist())))
    bad = 0
    for i in sel.tolist():
        r1 = int(u["restore_cons"][i])
        lo, hi = span.get(int(u["unit"][i]), (0, 0))
        starts, ends = ss[lo:hi], se[lo:hi]
        c = r1
        while True:
            row = crow[c - 1]
            j = int(np.searchsorted(starts, row, side="right")) - 1
            if j < 0 or ends[j] <= row:  # absent from R_c
                bad += c == r1
                L2[i], ev2[i] = c - r1, 1
                break
            if ends[j] == big:
                L2[i] = K - r1
                break
            c = int(np.searchsorted(crow, ends[j], side="left")) + 1
            if c > K:
                L2[i] = K - r1
                break
    return L2, ev2, bad


def repeat_spell_rows(U, base_mask, is_std, group_agents, fam_sc, A, g_max, weights, min_units) -> list[dict]:
    """First vs second spell hazards of the same restored facts, by g bin.

    Restored facts with at least one trial in the second spell. Spell 1 runs
    from entry to the first loss (always a loss, by selection), spell 2 from the
    restoring consolidation. CIs and the paired difference resample agents
    (Wilson for a single agent). `all facts` is the first-spell hazard of every
    fact in the group, for reference.
    """
    restored = base_mask & (U["restore_cons"] >= 0) & (U["L2"] > 0)
    like = (U["entry_kind"] == "rewrite") & (U["restore_src"] == SRC_RECREATED)
    scopes = [(ALL_LABEL, "all restored", restored & is_std, ALL_LABEL),
              (ALL_LABEL, "like for like", restored & is_std & like, ALL_LABEL)]
    scopes += [(g, "all restored", restored & np.isin(U["agent"], group_agents[g]), g)
               for g in (*FAMILIES, CC_LABEL) if len(group_agents[g])]
    out = []
    zero = np.zeros(len(U["L"]), dtype=np.int64)
    for group, subset, m, wkey in scopes:
        if m.sum() == 0:
            continue
        ag = group_agents[group]
        rc1 = sv.risk_counts(zero[m], U["L"][m], np.ones(int(m.sum()), dtype=np.int8),
                             U["agent"][m].astype(np.int64), A, g_max)
        rc2 = sv.risk_counts(zero[m], U["L2"][m], U["ev2"][m], U["agent"][m].astype(np.int64), A, g_max)
        s1 = Scope("spell1", group, rc1, 0, ag, weights(ag, wkey), int(m.sum()))
        s2 = Scope("spell2", group, rc2, 0, ag, weights(ag, wkey), int(m.sum()))
        b1, b2 = s1.binned(sv.PIECEWISE_BINS), s2.binned(sv.PIECEWISE_BINS)
        ref = fam_sc[group].binned(sv.PIECEWISE_BINS) if group in fam_sc else None
        diff_lo = diff_hi = np.full(len(sv.PIECEWISE_BINS), np.nan)
        if s1.cluster and s2.cluster:
            n1 = s1.w @ sv.bin_sums(s1.n_ag, sv.PIECEWISE_BINS, g_max)
            d1 = s1.w @ sv.bin_sums(s1.d_ag, sv.PIECEWISE_BINS, g_max)
            n2 = s2.w @ sv.bin_sums(s2.n_ag, sv.PIECEWISE_BINS, g_max)
            d2 = s2.w @ sv.bin_sums(s2.d_ag, sv.PIECEWISE_BINS, g_max)
            diff_lo, diff_hi = _boot_ci(sv.hazard(n2, d2) - sv.hazard(n1, d1))
        for j, (lo, hi) in enumerate(sv.PIECEWISE_BINS):
            if b1["n"][j] < min_units or b2["n"][j] < min_units:
                continue
            out.append({
                "group": group, "subset": subset, "n_facts": int(m.sum()),
                "g": str(lo) if lo == hi else (f"{lo}-{hi}" if hi else f"{lo}+"),
                "n_spell1": int(b1["n"][j]), "lost_spell1": int(b1["d"][j]),
                "h_spell1": b1["h"][j], "h_spell1_lo": b1["h_lo"][j], "h_spell1_hi": b1["h_hi"][j],
                "n_spell2": int(b2["n"][j]), "lost_spell2": int(b2["d"][j]),
                "h_spell2": b2["h"][j], "h_spell2_lo": b2["h_lo"][j], "h_spell2_hi": b2["h_hi"][j],
                "diff": b2["h"][j] - b1["h"][j], "diff_lo": diff_lo[j], "diff_hi": diff_hi[j],
                "h_all_facts_spell1": ref["h"][j] if ref is not None else np.nan,
                "ci_method": b1["method"],
            })
    return out


def monthly_hazards(e: np.ndarray, L: np.ndarray, event: np.ndarray, agent: np.ndarray, A: int, g_max: int,
                    cons_month: list[np.ndarray], month_dates: list[date],
                    group_agents: dict[str, np.ndarray], min_units: int) -> pl.DataFrame:
    """Hazards of the consolidations in each calendar month, by g bin and group.

    cons_month: per agent, the month index (into month_dates) of each
    consolidation c = 1..K. A hazard is null when its bin has fewer than
    `min_units` units at risk; n_at_risk counts all unit-trials of the month.
    """
    rc = sv.risk_counts(e, L, event, agent, A, g_max, cons_month, len(month_dates))
    bins = ((1, 1), (2, 2), (3, 4))
    recs = []
    for g in (ALL_LABEL, *FAMILIES):
        ag = group_agents.get(g, np.zeros(0, dtype=np.int64))
        for mi, day in enumerate(month_dates):
            n = rc.n[mi][ag].sum(0) if len(ag) else np.zeros(g_max + 2)
            dd = rc.d[mi][ag].sum(0) if len(ag) else np.zeros(g_max + 2)
            nb, db = sv.bin_sums(n, bins, g_max), sv.bin_sums(dd, bins, g_max)
            h = [float(db[j] / nb[j]) if nb[j] >= min_units else None for j in range(3)]
            recs.append((day, g, h[0], h[1], h[2], int(n[1:].sum())))
    return pl.DataFrame(recs, schema={"date": pl.Date, "group": pl.String, "h1": pl.Float64,
                                      "h2": pl.Float64, "h3_4": pl.Float64, "n_at_risk": pl.Int64},
                        orient="row")


def monthly_hazard_table(rows, agent_ids, U, mask, A, g_max, group_agents, min_units) -> pl.DataFrame:
    """memory_hazard_monthly: first day of each PT calendar month with consolidations."""
    cons = rows.filter(pl.col("is_cons"))
    first = cons["ts_pt"].min()
    last = cons["ts_pt"].max()
    n_months = (last.year - first.year) * 12 + last.month - first.month + 1
    month_dates = [date(first.year + (first.month - 1 + i) // 12, (first.month - 1 + i) % 12 + 1, 1)
                   for i in range(n_months)]
    cons_month = _strata_arrays(rows, agent_ids, "ts_pt",
                                lambda v: (v.year - first.year) * 12 + v.month - first.month)
    return monthly_hazards(U["entry_cons"][mask].astype(np.int64), U["L"][mask], U["event"][mask],
                           U["agent"][mask].astype(np.int64), A, g_max, cons_month, month_dates,
                           group_agents, min_units)


def memory_epochs(cfg) -> tuple[np.ndarray, list[str]]:
    """Start dates of the memory-system epochs (distinct memory CHANGELOG dates) and labels."""
    cl = pl.read_parquet(Path(cfg["paths"]["processed"]) / "changelog.parquet").filter(
        pl.col("categories").list.contains("memory"))
    dates = sorted(set(cl["date_start"].to_list()))
    labels = []
    for i, d in enumerate(dates):
        end = dates[i + 1] if i + 1 < len(dates) else None
        labels.append(f"[{d}, {end})" if end else f"[{d}, end]")
    return np.array(dates, dtype="datetime64[D]"), labels


def changelog_windows(cfg, rows, agent_ids, U, mask, A, std, seed, min_units, g_max: int) -> list[dict]:
    """Hazards in the CHANGELOG_WINDOW run days before vs after each memory-category entry."""
    processed = Path(cfg["paths"]["processed"])
    cl = pl.read_parquet(processed / "changelog.parquet").filter(
        pl.col("categories").list.contains("memory"))
    rp = pl.read_parquet(processed / "run_periods.parquet").select("date", "run_day").unique()
    rng = np.random.default_rng(seed + 2)
    w = sv.bootstrap_weights(std, A, BOOT_REPS, rng)
    out = []
    cons_rd = []
    for a in agent_ids:
        c = rows.filter((pl.col("agent_id") == a) & pl.col("is_cons"))
        cons_rd.append(c["run_day"].fill_null(-10_000).to_numpy().astype(np.int64))
    for r in cl.sort("date_start").iter_rows(named=True):
        ds, de = r["date_start"], r["date_end"] or r["date_start"]
        after_days = rp.filter(pl.col("date") >= ds)["run_day"]
        before_days = rp.filter(pl.col("date") <= de)["run_day"]
        if after_days.len() == 0 or before_days.len() == 0:
            continue
        rd0, rd1 = int(after_days.min()), int(before_days.max())
        b_lo, b_hi = rd0 - CHANGELOG_WINDOW, rd0 - 1
        a_lo, a_hi = rd1 + 1, rd1 + CHANGELOG_WINDOW
        strata = [np.where((x >= b_lo) & (x <= b_hi), 0, np.where((x >= a_lo) & (x <= a_hi), 1, -1))
                  for x in cons_rd]
        rc = sv.risk_counts(U["entry_cons"][mask].astype(np.int64), U["L"][mask], U["event"][mask],
                            U["agent"][mask].astype(np.int64), A, g_max, strata, 2,
                            modified=(U["event"][mask] == EVENT_MODIFIED))
        bins = ((1, 1), (2, None), (1, None))
        res = {}
        for s, side in ((0, "before"), (1, "after")):
            n = sv.bin_sums(rc.n[s], bins, g_max)  # (A, 3)
            d = sv.bin_sums(rc.d[s], bins, g_max)
            m = sv.bin_sums(rc.dmod[s], bins, g_max)
            res[side] = (n, d, m)
        n_cons = {side: int(sum(int((strata[i] == s).sum()) for i in std))
                  for s, side in ((0, "before"), (1, "after"))}
        n_ag = {side: int((res[side][0][:, 2] > 0).sum()) for side in ("before", "after")}
        row = {"entry_id": r["entry_id"], "date_start": str(ds), "date_end": str(de),
               "categories": ",".join(r["categories"]), "text_head": (r["text"] or "")[:70],
               "before_run_days": f"{b_lo}-{b_hi}", "after_run_days": f"{a_lo}-{a_hi}",
               "consolidations_before": n_cons["before"], "consolidations_after": n_cons["after"],
               "agents_before": n_ag["before"], "agents_after": n_ag["after"]}
        for j, lab in enumerate(("g1", "g2plus", "all")):
            for side in ("before", "after"):
                n, d, m = res[side]
                N, D, M = n[:, j].sum(), d[:, j].sum(), m[:, j].sum()
                row[f"n_{lab}_{side}"] = int(N)
                row[f"h_{lab}_{side}"] = D / N if N >= min_units else np.nan
                if lab == "all":
                    row[f"mod_rate_{side}"] = M / N if N >= min_units else np.nan
            nb, db = res["before"][0][:, j], res["before"][1][:, j]
            na, da = res["after"][0][:, j], res["after"][1][:, j]
            if nb.sum() >= min_units and na.sum() >= min_units:
                diff = da.sum() / na.sum() - db.sum() / nb.sum()
                lo = hi = p = np.nan
                # A paired agent bootstrap needs a few agents on each side.
                if (nb > 0).sum() >= 3 and (na > 0).sum() >= 3:
                    with np.errstate(all="ignore"):
                        diff_b = (w @ da) / (w @ na) - (w @ db) / (w @ nb)
                    diff_b = diff_b[np.isfinite(diff_b)]
                    if len(diff_b) > 10:
                        lo, hi = np.percentile(diff_b, [2.5, 97.5])
                        p = min(1.0, 2 * min((diff_b <= 0).mean(), (diff_b >= 0).mean()))
                row[f"diff_{lab}"], row[f"diff_{lab}_lo"], row[f"diff_{lab}_hi"] = diff, lo, hi
                row[f"p_{lab}"] = p
            else:
                row[f"diff_{lab}"] = row[f"diff_{lab}_lo"] = row[f"diff_{lab}_hi"] = np.nan
                row[f"p_{lab}"] = np.nan
        out.append(row)
    return out


def _write_csv(path: Path, rows: list[dict]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return str(path)
    keys = list(rows[0].keys())
    for r in rows[1:]:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=keys)
        wr.writeheader()
        for r in rows:
            wr.writerow({k: _csv_val(r.get(k, "")) for k in keys})
    return str(path)


def _csv_val(v):
    if isinstance(v, (float, np.floating)):
        return "" if not np.isfinite(v) else f"{float(v):.6g}"
    if isinstance(v, np.integer):
        return int(v)
    return v


# --- labels -----------------------------------------------------------------------

def write_labels(results, rows_by_agent, cand, units_tab, occ, ctx_display, salt, seed, path) -> dict:
    """data/labels/memory_pairs.csv: 100 consolidation pairs, up to 5 units each by rule label."""
    rng = np.random.default_rng(seed + 3)
    ut = units_tab.sort("unit_gid")
    u_type = ut["type"].to_numpy()
    u_val = ut["value"].to_list()
    u_ctx = ut["unit_ctx"].to_numpy()
    rows_out, counts = [], Counter()
    pair_id = 0
    for a, idx in cand.sort("order").select("agent_id", "idx").iter_rows():
        if pair_id >= N_PAIRS:
            break
        res = results.get(a)
        if res is None or idx not in res.pairs or not res.pairs[idx]:
            continue
        rr = rows_by_agent[a]
        next_uid = rr["id"][idx]
        prev_uid = rr["id"][idx - 1]
        by_lab = defaultdict(list)
        for u, lab, tc in res.pairs[idx]:
            by_lab[lab].append((u, tc))
        for lab in by_lab:
            by_lab[lab] = sorted(by_lab[lab])
            rng.shuffle(by_lab[lab])
        picked = []
        prio = ("modified", "restored", "dropped", "new", "kept")
        while len(picked) < UNITS_PER_PAIR and any(by_lab[lb] for lb in prio):
            for lab in prio:
                if by_lab[lab] and len(picked) < UNITS_PER_PAIR:
                    picked.append((*by_lab[lab].pop(), lab))
        pair_id += 1
        for u, tc, lab in picked:
            t = TYPES[int(u_type[u])]
            cid = int(u_ctx[u]) if u_ctx[u] >= 0 else (int(tc) & 0xFFFFFFFF if tc >= 0 else -1)
            key = f"{t}|{display_value(t, u_val[u], salt)}|{ctx_display(cid)}"
            rows_out.append({"pair_id": pair_id, "agent_id": a, "prev_uid": prev_uid,
                             "next_uid": next_uid, "unit_key": key, "rule_label": lab,
                             "human_label": "", "notes": ""})
            counts[lab] += 1
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=["pair_id", "agent_id", "prev_uid", "next_uid", "unit_key",
                                               "rule_label", "human_label", "notes"])
            wr.writeheader()
            wr.writerows(rows_out)
    return {"pairs": pair_id, "units": len(rows_out), "labels": dict(counts),
            "path": str(path) if path else None}


def _key_maker(units_tab: pl.DataFrame, ctx_display, salt: bytes):
    """unit_key as in the label file: type|displayed value|displayed context."""
    ut = units_tab.sort("unit_gid")
    u_type = ut["type"].to_numpy()
    u_val = ut["value"].to_list()
    u_ctx = ut["unit_ctx"].to_numpy()

    def key(u: int, tc: int) -> str:
        t = TYPES[int(u_type[u])]
        cid = int(u_ctx[u]) if u_ctx[u] >= 0 else (int(tc) & 0xFFFFFFFF if tc >= 0 else -1)
        return f"{t}|{display_value(t, u_val[u], salt)}|{ctx_display(cid)}"
    return key


def write_rule_version(results: dict[str, AgentResult], rows_by_agent, units_tab, ctx_display, salt,
                       pairs_path: Path, out_path: Path | None, version: str = "v2") -> dict:
    """data/labels/memory_pairs_rule_<version>.csv: rule_label_<version> for every unit of memory_pairs.csv.

    Units are found again by (pair, unit_key) in the chain's pair lists; the v1
    label recomputed in the same pass is checked against the file's rule_label.
    """
    col = f"rule_label_{version}"
    attr = "pairs" + version[1:]
    if not pairs_path.exists():
        return {"pairs": 0, "units": 0, "labels": {}, "checks": {"pairs_file_missing": 1}, "path": None,
                "agreement": {}}
    src = pl.read_csv(pairs_path, infer_schema_length=0)
    key = _key_maker(units_tab, ctx_display, salt)
    pos = {}
    for a, rr in rows_by_agent.items():
        for i, rid in enumerate(rr["id"].to_list()):
            pos[(a, rid)] = i
    cache: dict[tuple[str, int], tuple[dict, dict]] = {}
    out, st = [], Counter()
    for r in src.iter_rows(named=True):
        a, k = r["agent_id"], pos.get((r["agent_id"], r["next_uid"]))
        res = results.get(a)
        if res is None or k is None:
            st["pair_not_found"] += 1
            out.append({"pair_id": r["pair_id"], "unit_key": r["unit_key"], col: ""})
            continue
        if (a, k) not in cache:
            lab1 = {key(u, tc): lb for u, lb, tc in res.pairs.get(k, [])}
            lab2 = {key(u, tc): lb for u, lb, tc in (getattr(res, attr) or {}).get(k, [])}
            cache[(a, k)] = (lab1, lab2)
        lab1, lab2 = cache[(a, k)]
        l2 = lab2.get(r["unit_key"], "")
        st["unit_not_found"] += not l2
        st["v1_label_differs"] += lab1.get(r["unit_key"]) != r["rule_label"]
        st[f"{r['rule_label']}->{l2 or 'missing'}"] += 1
        out.append({"pair_id": r["pair_id"], "unit_key": r["unit_key"], col: l2})
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=["pair_id", "unit_key", col])
            wr.writeheader()
            wr.writerows(out)
        os.chmod(out_path, 0o600)
    return {"pairs": len({r["pair_id"] for r in out}), "units": len(out),
            "labels": dict(Counter(r[col] for r in out)), "checks": dict(st), "version": version,
            "path": str(out_path) if out_path else None}


def write_rule_v2(results, rows_by_agent, units_tab, ctx_display, salt, pairs_path: Path,
                  out_path: Path | None) -> dict:
    """`write_rule_version` for rules v2 (kept for callers of the v2 run)."""
    return write_rule_version(results, rows_by_agent, units_tab, ctx_display, salt, pairs_path, out_path, "v2")


def _kappa(a: list[str], b: list[str]) -> float:
    labs = sorted(set(a) | set(b))
    n = len(a)
    if n == 0:
        return float("nan")
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[lab] * cb[lab] for lab in labs) / (n * n)
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


def label_agreement(review_path: Path, rule_v2_rows: list[dict]) -> dict:
    """Agreement of rule labels v1 and v2 with the LLM pre-labels (read-only use of the review sheet)."""
    try:
        rv = pl.read_csv(review_path, infer_schema_length=0).select(
            "pair_id", "unit_key", "rule_label", "llm_label")
        mtime = datetime.fromtimestamp(review_path.stat().st_mtime, timezone.utc).strftime(_SPLIT_TS)
    except Exception as e:  # the sheet may be missing or being rewritten
        return {"error": f"{type(e).__name__}"}
    j = pl.DataFrame(rule_v2_rows, schema={"pair_id": pl.String, "unit_key": pl.String,
                                           "rule_label_v2": pl.String}).join(rv, on=["pair_id", "unit_key"],
                                                                            how="inner")
    j = j.filter(pl.col("llm_label").is_not_null() & (pl.col("llm_label") != ""))
    v1, v2, llm = j["rule_label"].to_list(), j["rule_label_v2"].to_list(), j["llm_label"].to_list()
    conf = {(a, b): n for a, b, n in j.group_by("rule_label_v2", "llm_label").len().iter_rows()}
    conf1 = {(a, b): n for a, b, n in j.group_by("rule_label", "llm_label").len().iter_rows()}
    return {"n": j.height, "sheet_mtime": mtime,
            "agree_v1": int(sum(x == y for x, y in zip(v1, llm))),
            "agree_v2": int(sum(x == y for x, y in zip(v2, llm))),
            "kappa_v1": _kappa(v1, llm), "kappa_v2": _kappa(v2, llm),
            "confusion_v2": {f"{a}|{b}": int(n) for (a, b), n in conf.items()},
            "confusion_v1": {f"{a}|{b}": int(n) for (a, b), n in conf1.items()}}


def label_agreement_all(labels_dir: Path, versions: tuple[str, ...], prefix: str = "") -> dict:
    """Agreement of each rule version's labels with the LLM pre-labels, for information only.

    v1 labels come from memory_pairs.csv, vK labels from memory_pairs_rule_vK.csv, the LLM labels
    from the review sheet (read only); rows are joined by (pair_id, unit_key).
    """
    review = labels_dir / f"{prefix}memory_pairs_review.csv"
    try:
        rv = pl.read_csv(review, infer_schema_length=0).select("pair_id", "unit_key", "llm_label")
        mtime = datetime.fromtimestamp(review.stat().st_mtime, timezone.utc).strftime(_SPLIT_TS)
        base = pl.read_csv(labels_dir / f"{prefix}memory_pairs.csv", infer_schema_length=0).select(
            "pair_id", "unit_key", pl.col("rule_label").alias("v1"))
    except Exception as e:
        return {"error": f"{type(e).__name__}"}
    for v in versions:
        if v == "v1":
            continue
        f = labels_dir / f"{prefix}memory_pairs_rule_{v}.csv"
        if not f.exists():
            return {"error": f"missing {f.name}"}
        base = base.join(pl.read_csv(f, infer_schema_length=0).select(
            "pair_id", "unit_key", pl.col(f"rule_label_{v}").alias(v)), on=["pair_id", "unit_key"], how="left")
    j = base.join(rv, on=["pair_id", "unit_key"], how="inner").filter(
        pl.col("llm_label").is_not_null() & (pl.col("llm_label") != ""))
    llm = j["llm_label"].to_list()
    out = {"n": j.height, "sheet_mtime": mtime, "agree": {}, "kappa": {}, "confusion": {}}
    for v in versions:
        lab = j[v].fill_null("").to_list()
        out["agree"][v] = int(sum(x == y for x, y in zip(lab, llm)))
        out["kappa"][v] = _kappa(lab, llm)
        out["confusion"][v] = {f"{a}|{b}": int(n) for a, b, n in
                               j.group_by(pl.col(v).fill_null(""), "llm_label").len().iter_rows()}
    return out


def _table_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def compare_versions(cfg, results: dict[str, AgentResult], agents: pl.DataFrame, units_tab: pl.DataFrame,
                     s_cur: dict, min_units: int, write_outputs: bool, agent_filter,
                     versions: tuple[str, ...] = ("v1", "v2"), rows: pl.DataFrame | None = None,
                     seed: int = 20261003, n_workers: int = 1) -> dict:
    """Rule versions against each other on the same units (all computed in one chain pass).

    Rescued losses (v1 losses that a later version keeps at the same consolidation), hazards by g
    bin and modified share per version and family, BdW c from g = 2 and the H2 outcome per version
    (earlier versions read from their tables, the last one from this run), the conclusions that
    hold or flip across versions, and agreement with the LLM pre-labels (for information only).
    """
    cur = versions[-1]
    prefix = "" if not agent_filter else "pilot_"
    tables = Path(cfg["paths"]["outputs"]) / "tables"
    agent_ids = sorted(results)
    ainfo = agents.select("agent_id", "model_family", pl.col("scaffold").cast(pl.String))
    fam = dict(ainfo.select("agent_id", "model_family").iter_rows())
    scaf = dict(ainfo.select("agent_id", "scaffold").iter_rows())
    group = {a: (CC_LABEL if scaf.get(a) == "claude_code" else fam.get(a, "Other")) for a in agent_ids}
    utype = units_tab.sort("unit_gid")["type"].to_numpy()
    cols = defaultdict(list)
    for i, a in enumerate(agent_ids):
        r = results[a]
        k = len(r.units["unit"])
        cols["agent"].append(np.full(k, i, dtype=np.int64))
        cols["K"].append(np.full(k, r.n_cons, dtype=np.int64))
        cols["type"].append(utype[r.units["unit"]] if k else np.zeros(0, np.int64))
        for v in versions:
            src = r.units if v == "v1" else getattr(r, "units" + v[1:])
            for key in ("entry_cons", "loss_cons", "event", "n_fallback"):
                cols[f"{key}_{v}"].append(src[key].astype(np.int64))
    U = {k: np.concatenate(v) for k, v in cols.items()}
    grp = np.array([group[agent_ids[i]] for i in U["agent"]], dtype=object)
    std = grp != CC_LABEL
    out_rows: list[dict] = []
    res: dict = {"versions": versions, "current": cur}

    # 1. v1 losses that later versions keep, and keeps of the previous version that the current one loses.
    lost1 = U["loss_cons_v1"] >= 0
    res["rescued"] = {}
    for v in versions[1:]:
        kept_v = lost1 & ((U[f"loss_cons_{v}"] < 0) | (U[f"loss_cons_{v}"] > U["loss_cons_v1"]))
        mod_to_drop = lost1 & (U["event_v1"] == EVENT_MODIFIED) & (U[f"loss_cons_{v}"] == U["loss_cons_v1"]) \
            & (U[f"event_{v}"] == EVENT_DROPPED)
        by_type = []
        for ti, tname in enumerate(TYPES):
            m = std & lost1 & (U["type"] == ti)
            if m.sum():
                by_type.append({"type": tname, "v1_losses": int(m.sum()), "kept": int((m & kept_v).sum())})
                out_rows.append({"metric": f"v1 losses kept in {v}", "scope": tname, "value": int((m & kept_v).sum()),
                                 "of": int(m.sum())})
        res["rescued"][v] = {"v1_losses": int((std & lost1).sum()), "kept": int((std & kept_v).sum()),
                             "by_type": by_type, "v1_modified": int((std & lost1 & (U["event_v1"] == EVENT_MODIFIED)).sum()),
                             "v1_modified_now_dropped": int((std & mod_to_drop).sum())}
        out_rows.append({"metric": f"v1 losses kept in {v}", "scope": ALL_LABEL,
                         "value": res["rescued"][v]["kept"], "of": res["rescued"][v]["v1_losses"]})
    if len(versions) >= 3:
        # Units the current rules lose at a consolidation where the previous version still kept them.
        prev = versions[-2]
        undone = std & (U[f"loss_cons_{cur}"] >= 0) & (
            (U[f"loss_cons_{prev}"] < 0) | (U[f"loss_cons_{prev}"] > U[f"loss_cons_{cur}"]))
        res["prev_kept_now_lost"] = {
            "prev": prev, "total": int(undone.sum()),
            "by_type": [{"type": tname, "lost_now": int((undone & (U["type"] == ti)).sum())}
                        for ti, tname in enumerate(TYPES) if (undone & (U["type"] == ti)).any()]}

    # 2. Hazards by g bin and modified share, per version and group.
    g_max = int(U["K"].max()) if len(U["K"]) else 1
    haz = []
    for g in (ALL_LABEL, *FAMILIES, CC_LABEL):
        sel = std if g == ALL_LABEL else grp == g
        row = {"group": g}
        for v in versions:
            L = np.where(U[f"loss_cons_{v}"] >= 0, U[f"loss_cons_{v}"] - U[f"entry_cons_{v}"],
                         U["K"] - U[f"entry_cons_{v}"])
            m = sel & (L > 0)
            if not m.any():
                continue
            rc = sv.risk_counts(U[f"entry_cons_{v}"][m], L[m], U[f"event_{v}"][m].astype(np.int8),
                                np.zeros(int(m.sum()), dtype=np.int64), 1, g_max)
            n, d, _ = rc.pooled(0)
            nb, db = sv.bin_sums(n, sv.PIECEWISE_BINS, g_max), sv.bin_sums(d, sv.PIECEWISE_BINS, g_max)
            for j, lab in enumerate(("h1", "h2", "h3_4", "h5_8", "h9plus")):
                row[f"{lab}_{v}"] = float(db[j] / nb[j]) if nb[j] >= min_units else float("nan")
            ev = U[f"event_{v}"][m]
            row[f"mod_share_{v}"] = float((ev == EVENT_MODIFIED).sum() / max(1, (ev > 0).sum()))
        haz.append(row)
        for lab in ("h1", "h2", "h3_4", "h5_8", "h9plus", "mod_share"):
            out_rows.append({"metric": lab, "scope": g,
                             **{v: row.get(f"{lab}_{v}", np.nan) for v in versions}})
    res["hazards"] = haz

    # 3. BdW c from g = 2 and H2 outcomes per version.
    def bdw_of(v: str) -> dict:
        rows_ = s_cur.get("bdw_rows", []) if v == cur else _table_rows(
            tables / f"{prefix}memory_bdw{'' if v == 'v1' else '_' + v}.csv")
        out = {}
        for r in rows_:
            if str(r.get("g_from")) == "2":
                out[(r["scope"], r["stratum"])] = (_num(r["c"]), _num(r["c_lo"]), _num(r["c_hi"]),
                                                   sv.bdw_boundary(_num(r.get("alpha")), _num(r.get("beta"))))
        return out

    def h2_of(v: str) -> dict:
        rows_ = s_cur.get("h2_rows", []) if v == cur else _table_rows(
            tables / f"{prefix}memory_h2{'' if v == 'v1' else '_' + v}.csv")
        return {(r["scope"], r["stratum"]): r for r in rows_}

    bdw_v = {v: bdw_of(v) for v in versions}
    h2_v = {v: h2_of(v) for v in versions}
    # Earlier versions were written by their own runs: their hazards, recomputed here, must match.
    res["consistency"] = {}
    for v in versions[:-1]:
        diffs = [abs(row.get(f"{lab}_{v}", np.nan) - _num(h2_v[v].get(("family", row["group"]), {}).get(lab)))
                 for row in haz for lab in ("h1", "h2", "h3_4", "h5_8", "h9plus")
                 if ("family", row["group"]) in h2_v[v]]
        diffs = [x for x in diffs if np.isfinite(x)]
        res["consistency"][v] = {"compared": len(diffs), "max_abs_diff": max(diffs) if diffs else float("nan")}
    res["bdw"] = []
    for key in (("family", ALL_LABEL), ("regime_cohort", "pre"), ("regime_cohort", "post")):
        row = {"scope": key[0], "stratum": key[1]}
        for v in versions:
            c, lo, hi, edge = bdw_v[v].get(key, (np.nan, np.nan, np.nan, False))
            row.update({f"c_{v}": c, f"c_lo_{v}": lo, f"c_hi_{v}": hi, f"boundary_{v}": edge})
        res["bdw"].append(row)
        out_rows.append({"metric": "BdW c (from g = 2)", "scope": f"{key[0]}:{key[1]}",
                         **{v: row[f"c_{v}"] for v in versions}})
    res["h2"] = []
    for g in (ALL_LABEL, *FAMILIES, CC_LABEL):
        row = {"stratum": g}
        for v in versions:
            r = h2_v[v].get(("family", g), {})
            pw, plr = _num(r.get("p_wald_cluster")), _num(r.get("p_lr"))
            aics = {"geometric": _num(r.get("aic_geometric")), "beta-geometric": _num(r.get("aic_betageom")),
                    "piecewise": _num(r.get("aic_piecewise"))}
            row.update({f"p_{v}": pw if np.isfinite(pw) else plr, f"test_{v}": "Wald" if np.isfinite(pw) else "LR",
                        f"h1_{v}": _num(r.get("h1")), f"h9_{v}": _num(r.get("h9plus")),
                        f"best_{v}": min(aics, key=lambda k: aics[k] if np.isfinite(aics[k]) else np.inf)
                        if r else "n/a"})
        res["h2"].append(row)

    # 3b. Survivors of the first consolidation with the clock restarted (g' = g - 1). The
    # beta-geometric is closed under conditioning on survival, so c' = 1 still means heterogeneity
    # alone, and unlike the from-g = 2 likelihood no unobserved first-trial mixing is left to fit.
    res["bdw_survivors"] = []
    if rows is not None:
        cs = []
        for a in agent_ids:
            reg = rows.filter((pl.col("agent_id") == a) & pl.col("is_cons"))["regime"].to_numpy()
            post_idx = np.flatnonzero(reg == "post")
            cs.append(int(post_idx[0]) + 1 if len(post_idx) else len(reg) + 1)
        cs_u = np.array(cs, dtype=np.int64)[U["agent"]]
        A = len(agent_ids)
        std_agents = np.unique(U["agent"][std])
        W = sv.bootstrap_weights(std_agents, A, B_BDW, np.random.default_rng(seed + 11))
        fits = []
        for v in versions:
            e = U[f"entry_cons_{v}"]
            L = np.where(U[f"loss_cons_{v}"] >= 0, U[f"loss_cons_{v}"] - e, U["K"] - e)
            ev = (U[f"event_{v}"] > 0).astype(np.int8)
            room = cs_u - 1 - e
            for scope, m0, Ls, evs in (("All standard", std, L, ev),
                                       ("pre cohort", std & (room > 0), np.minimum(L, room),
                                        np.where(L <= room, ev, 0).astype(np.int8)),
                                       ("post cohort", std & (room <= 0), L, ev)):
                m = m0 & (Ls >= 2)
                rc = sv.risk_counts(e[m] + 1, Ls[m] - 1, evs[m], U["agent"][m], A, g_max)
                n_ag, d_ag = rc.n[0], rc.d[0]
                n, d = n_ag.sum(0), d_ag.sum(0)
                bg = sv.fit_bdw(n, d, c_fixed=1.0)
                fit = sv.fit_bdw(n, d)
                if np.isfinite(bg.ll) and (not np.isfinite(fit.ll) or fit.ll < bg.ll):
                    alt = sv.fit_bdw(n, d, start=(bg.alpha, bg.beta, 1.0))
                    fit = alt if not np.isfinite(fit.ll) or alt.ll > fit.ll else fit
                fits.append((v, scope, n_ag, d_ag, bg, fit, int(m.sum())))
        boots: dict[int, np.ndarray] = {}
        with ProcessPoolExecutor(max(1, min(n_workers, len(fits))), mp_context=mp.get_context("spawn")) as ex:
            futs = {ex.submit(sv.bdw_bootstrap, f[2], f[3], W, (f[5].alpha, f[5].beta, f[5].c)): i
                    for i, f in enumerate(fits) if np.isfinite(f[5].c)}
            for fu in as_completed(futs):
                boots[futs[fu]] = fu.result()
        for i, (v, scope, n_ag_i, _, bg, fit, n_units) in enumerate(fits):
            cb = boots.get(i, np.zeros((0, 4)))[:, 2]
            cb = cb[np.isfinite(cb)]
            n_clusters = int((n_ag_i[:, 1:].sum(1) > 0).sum())
            lo, hi = (np.percentile(cb, [2.5, 97.5]) if len(cb) > 20 and n_clusters >= 2
                      else (np.nan, np.nan))
            lr = max(0.0, 2 * (fit.ll - bg.ll)) if np.isfinite(fit.ll) and np.isfinite(bg.ll) else np.nan
            row = {"version": v, "scope": scope, "units": n_units, "c": fit.c, "c_lo": lo, "c_hi": hi,
                   "alpha": fit.alpha, "beta": fit.beta, "lr_c1": lr,
                   "aic_gain_over_bg": (4 - 2 * bg.ll) - (6 - 2 * fit.ll),
                   "boundary": sv.bdw_boundary(fit.alpha, fit.beta)}
            res["bdw_survivors"].append(row)
            out_rows.append({"metric": "BdW c among survivors of g = 1 (clock restarted)", "scope": f"{scope}",
                             "version": v, "value": fit.c, "lo": lo, "hi": hi, "boundary": row["boundary"]})

    # 4. Conclusions across versions.
    concl = []

    def add(text: str, per: dict[str, bool | None]) -> None:
        vals = [x for x in per.values() if x is not None]
        concl.append({"conclusion": text, **{v: per.get(v) for v in versions},
                      "status": "holds in all" if vals and all(vals) else
                      "fails in all" if vals and not any(vals) else "flips"})

    fam_rows = [r for r in res["h2"] if r["stratum"] in FAMILIES or r["stratum"] == ALL_LABEL]

    def all_or_none(flags: list[bool]) -> bool | None:
        """All of the comparisons that have data; None when none has."""
        return all(flags) if flags else None

    def less(a: float, b: float) -> bool | None:
        return bool(a < b) if np.isfinite(a) and np.isfinite(b) else None

    add("H2 (constant hazard) rejected at 5% for all standard agents and every family",
        {v: all_or_none([r[f"p_{v}"] < 0.05 for r in fam_rows if np.isfinite(r[f"p_{v}"])]) for v in versions})
    add("Hazard lower at g >= 9 than at g = 1 in every family",
        {v: all_or_none([x for r in fam_rows if (x := less(r[f"h9_{v}"], r[f"h1_{v}"])) is not None])
         for v in versions})
    post = {v: h2_v[v].get(("regime:post", ALL_LABEL), {}) for v in versions}
    add("After the switch to perma-computer-use the hazard rises from g = 1 to g = 2",
        {v: less(_num(post[v].get("h1")), _num(post[v].get("h2"))) for v in versions})
    add("Most first losses are drops (modified share below one half)",
        {v: less(haz[0].get(f"mod_share_{v}", np.nan), 0.5) for v in versions})
    add("Beta-geometric fits better than geometric for all standard agents (AIC)",
        {v: less(_num(h2_v[v].get(("family", ALL_LABEL), {}).get("aic_betageom")),
                 _num(h2_v[v].get(("family", ALL_LABEL), {}).get("aic_geometric"))) for v in versions})
    for b in res["bdw"]:
        add(f"BdW c from g = 2 below 1 ({b['stratum']}{' cohort' if b['scope'] == 'regime_cohort' else ''}: "
            "duration dependence beyond heterogeneity)",
            {v: (b[f"c_hi_{v}"] < 1) if np.isfinite(b[f"c_hi_{v}"]) else None for v in versions})
    surv = {(r["version"], r["scope"]): r for r in res["bdw_survivors"]}
    for scope in ("All standard", "pre cohort", "post cohort"):
        if any((v, scope) in surv for v in versions):
            add(f"BdW c' among survivors of g = 1 below 1 ({scope}, clock restarted)",
                {v: (bool(surv[(v, scope)]["c_hi"] < 1) if np.isfinite(surv[(v, scope)]["c_hi"]) else None)
                 if (v, scope) in surv else None for v in versions})
    fam_h1 = {v: max((r for r in haz if r["group"] in FAMILIES), key=lambda r: r.get(f"h1_{v}", -1))["group"]
              for v in versions}
    add(f"OpenAI has the highest first-consolidation hazard among families (per version: {fam_h1})",
        {v: fam_h1[v] == "OpenAI" for v in versions})
    res["conclusions"] = concl
    for c_ in concl:
        out_rows.append({"metric": "conclusion", "scope": c_["conclusion"], "status": c_["status"],
                         **{v: c_[v] for v in versions}})

    # 5. Fallback use by anchor type in the current version; agreement with the LLM labels.
    fb = []
    for ti, tname in enumerate(TYPES):
        m = std & (U["type"] == ti)
        if m.sum():
            fb.append({"type": tname, "units": int(m.sum()),
                       "units_with_fallback": int((U[f"n_fallback_{cur}"][m] > 0).sum()),
                       "fallback_trials": int(U[f"n_fallback_{cur}"][m].sum())})
    res["fallback"] = fb
    res["agreement"] = label_agreement_all(Path(cfg["paths"]["labels"]), versions, prefix)
    ag = res["agreement"]
    if "n" in ag:
        out_rows.append({"metric": "agreement with LLM labels (information only)", "scope": f"{ag['n']} units",
                         **{v: ag["agree"][v] for v in versions}})
        out_rows.append({"metric": "Cohen's kappa with LLM labels (information only)", "scope": f"{ag['n']} units",
                         **{v: ag["kappa"][v] for v in versions}})
    if write_outputs:
        name = f"{prefix}memory_{'_'.join(versions)}.csv"
        res["path"] = _write_csv(tables / name, out_rows)
    return res


# --- memory_facts --------------------------------------------------------------------

def _stable_key(t: int, value: str, ctx: str) -> int:
    h = hashlib.blake2b(f"{TYPES[t]}\x00{value}\x00{ctx}".encode("utf-8", "surrogatepass"), digest_size=8)
    return int.from_bytes(h.digest(), "little", signed=True)


def write_facts(results, rows_by_agent, agent_ids, units_tab, ctx_display, U, path) -> dict:
    """One row per presence spell of a unit in an agent's memory (module B2 input)."""
    ut = units_tab.sort("unit_gid")
    u_type = ut["type"].to_numpy()
    u_val = ut["value"].to_list()
    u_ctx = ut["unit_ctx"].to_numpy()
    parts = []
    for a in agent_ids:
        sp = results[a].spells
        if len(sp["unit"]) == 0:
            continue
        rr = rows_by_agent[a].select(pl.col("id").alias("rid"), pl.col("created_at").alias("rts"))
        rr = rr.with_row_index("row", offset=0).with_columns(pl.col("row").cast(pl.Int32))
        df = pl.DataFrame({"unit_gid": sp["unit"].astype(np.int64), "start_row": sp["start_row"],
                           "end_row": sp["end_row"]})
        df = (df.join(rr.rename({"row": "start_row", "rid": "spell_start_row_id",
                                 "rts": "spell_start_ts"}), on="start_row", how="left")
              .join(rr.rename({"row": "end_row", "rid": "spell_end_row_id", "rts": "spell_end_ts"}),
                    on="end_row", how="left")
              .with_columns(pl.lit(a).alias("agent_id"),
                            pl.int_range(pl.len()).over("unit_gid").alias("spell"))
              .drop("start_row", "end_row"))
        parts.append(df)
    if not parts:
        return {"rows": 0, "units": 0, "path": None, "null_survival": 0}
    facts = pl.concat(parts)
    gid = facts["unit_gid"].unique().to_numpy()
    glist = gid.tolist()
    ctx = [ctx_display(int(u_ctx[g])) for g in glist]
    types_ = [TYPES[int(u_type[g])] for g in glist]
    vals_ = [u_val[g] for g in glist]
    info = pl.DataFrame({
        "unit_gid": gid,
        "unit_key": np.array([_stable_key(int(u_type[g]), v, c) for g, v, c in zip(glist, vals_, ctx)],
                             dtype=np.int64),
        "anchor_type": types_,
        "value": vals_,
        "ctx": ctx,
        "domain": [url_domain(v) if t == "url" else None for t, v in zip(types_, vals_)],
    })
    # Survival summary per (agent, unit).
    a_ids = np.array(agent_ids, dtype=object)
    surv = pl.DataFrame({
        "agent_id": a_ids[U["agent"]],
        "unit_gid": U["unit"].astype(np.int64),
        "entry_kind": U["entry_kind"].astype(str),
        "trials": U["L"],
        "lost_event": np.where(U["event"] == EVENT_DROPPED, "dropped",
                               np.where(U["event"] == EVENT_MODIFIED, "modified", "none")),
        "survived": np.where(U["event"] > 0, U["L"] - 1, U["L"]),
        "restored": U["restore_cons"] >= 0,
    })
    facts = (facts.join(info, on="unit_gid", how="left")
             .join(surv, on=["agent_id", "unit_gid"], how="left")
             .drop("unit_gid")
             .select("agent_id", "unit_key", "anchor_type", "value", "ctx", "domain", "spell",
                     "spell_start_row_id", "spell_start_ts", "spell_end_row_id", "spell_end_ts",
                     "entry_kind", "trials", "survived", "lost_event", "restored")
             .sort("agent_id", "spell_start_ts", "unit_key"))
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        facts.write_parquet(path, compression="zstd")
    return {"rows": facts.height, "units": int(facts.select("agent_id", "unit_key").n_unique()),
            "path": str(path) if path else None,
            "null_survival": int(facts["trials"].null_count())}


# --- figure ---------------------------------------------------------------------------

PENN_BLUE, PENN_RED = "#011F5B", "#990000"


def _tint(hex_color: str, t: float) -> str:
    """Mix a colour with white (t = 0 keeps it, t = 1 is white)."""
    rgb = [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(c + (255 - c) * t):02X}" for c in rgb)


STYLE = {
    "Anthropic": dict(color=PENN_BLUE, marker="o", ls="-", mfc=PENN_BLUE),
    "OpenAI": dict(color=PENN_RED, marker="s", ls="-", mfc=PENN_RED),
    "Google": dict(color=_tint(PENN_BLUE, 0.5), marker="^", ls="-", mfc=_tint(PENN_BLUE, 0.5)),
    "Other": dict(color=_tint(PENN_RED, 0.5), marker="D", ls="-", mfc=_tint(PENN_RED, 0.5)),
    CC_LABEL: dict(color=_tint(PENN_BLUE, 0.25), marker="v", ls=":", mfc="none"),
}


def plot_retention(scopes, h2_results, ret_rows, base: Path, min_units: int) -> None:
    """F6: (a) Kaplan-Meier retention with geometric fits, (b) hazard h_g with 95% CIs, by family."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.ticker import MaxNLocator

    plt.rcParams.update({
        "font.size": 11, "axes.edgecolor": PENN_BLUE, "axes.labelcolor": PENN_BLUE,
        "xtick.color": PENN_BLUE, "ytick.color": PENN_BLUE, "text.color": PENN_BLUE,
        "axes.titlecolor": PENN_BLUE, "legend.fontsize": 10.5, "pdf.fonttype": 42,
    })
    fam = {sc.stratum: sc for sc in scopes if sc.scope == "family"}
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.5, 4.8), constrained_layout=True)
    g_show, h_show = 30, 20
    y_min = 1.0
    handles, labels = [], []
    for g in (*FAMILIES, CC_LABEL):
        sc = fam.get(g)
        if sc is None:
            continue
        st = STYLE[g]
        pts = [r for r in ret_rows if r["scope"] == "family" and r["stratum"] == g and r["g"] <= g_show]
        if not pts:
            continue
        x = np.array([0] + [r["g"] for r in pts])
        y = np.array([1.0] + [r["retention"] for r in pts])
        lo = np.array([1.0] + [r["retention_lo"] for r in pts], dtype=float)
        hi = np.array([1.0] + [r["retention_hi"] for r in pts], dtype=float)
        y_min = min(y_min, float(np.nanmin(np.where(lo > 0, lo, y))))
        kw = dict(color=st["color"], ls=st["ls"], marker=st["marker"], mfc=st["mfc"], ms=4.5, lw=1.7)
        line, = ax1.plot(x, y, markevery=3, **kw)
        ax1.fill_between(x, np.where(lo > 0, lo, y), hi, color=st["color"], alpha=0.13, lw=0)
        t2 = h2_results.get(("family", g))
        if t2 is not None and np.isfinite(t2.h_geom):
            xx = np.linspace(0, g_show, 200)
            ax1.plot(xx, (1 - t2.h_geom) ** xx, color=st["color"], ls="--", lw=1.1)
        b = sc.binned(tuple((i, i) for i in range(1, h_show + 1)))
        ok = b["n"] >= min_units
        gx = np.arange(1, h_show + 1)[ok]
        ax2.plot(gx, b["h"][ok], markevery=1, **kw)
        ax2.fill_between(gx, b["h_lo"][ok], b["h_hi"][ok], color=st["color"], alpha=0.13, lw=0)
        if t2 is not None and np.isfinite(t2.h_geom):
            ax2.hlines(t2.h_geom, 0.6, h_show + 0.4, color=st["color"], ls="--", lw=1.1)
        n_ag = sc.n_contrib
        handles.append(line)
        labels.append(f"{g} ({n_ag} agent{'s' if n_ag != 1 else ''})")
    ax1.set_yscale("log")
    ax1.set_ylim(max(1e-4, y_min * 0.6), 1.15)
    ax1.set_xlim(0, g_show)
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.set_xlabel("Consolidations Since Entry, g")
    ax1.set_ylabel("Share of Fact Units Kept Through g")
    ax1.grid(True, which="major", color=_tint(PENN_BLUE, 0.88), lw=0.6)
    ax2.set_xlim(0.5, h_show + 0.5)
    ax2.set_ylim(0, None)
    ax2.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax2.set_xlabel("Consolidations Since Entry, g")
    ax2.set_ylabel("Hazard of Loss at Consolidation g")
    ax2.grid(True, color=_tint(PENN_BLUE, 0.88), lw=0.6)
    handles.append(Line2D([0], [0], color=PENN_BLUE, ls="--", lw=1.1))
    labels.append("Geometric Fit (Constant Hazard)")
    fig.legend(handles, labels, loc="outside lower center", ncol=3, frameon=False)
    for ax, letter in ((ax1, "a"), (ax2, "b")):
        ax.text(-0.12, 1.02, letter, transform=ax.transAxes, fontsize=14, fontweight="bold",
                color=PENN_BLUE, va="bottom")
    base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(base) + ".pdf")
    fig.savefig(str(base) + ".png", dpi=200)
    plt.close(fig)


# --- QA report -------------------------------------------------------------------------

def _md(header: list[str], rows: list[list]) -> str:
    def f(v):
        if isinstance(v, (int, np.integer)):
            return f"{int(v):,}"
        if isinstance(v, (float, np.floating)):
            return _fmt(float(v))
        return str(v)
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(f(v) for v in r) + " |" for r in rows]
    return "\n".join(out)


def _ci(r: dict, k: str) -> str:
    v, lo, hi = r.get(k), r.get(f"{k}_lo"), r.get(f"{k}_hi")
    if v is None or not np.isfinite(v):
        return "n/a"
    if lo is None or not np.isfinite(lo):
        return _fmt(v)
    return f"{_fmt(v)} [{_fmt(lo)}, {_fmt(hi)}]"


V2_RULES_NOTE = (
    "Rules v2: a unit with no anchor in a consolidation output still counts as present if "
    "its value occurs literally there (URL, date, time, email, phone, agent name and entity types: a surface "
    "form of the value anywhere, case-insensitive, whitespace-normalised, word-bounded; hashed values by "
    "hashing candidate strings; number, money and percent: the same value on a line that also holds the "
    "unit's context word). A loss is a modification only if the line that replaced the unit's line (patience "
    "alignment of lines kept verbatim; inside a changed block the line at the same offset, or the one sharing "
    "the most anchor keys) holds the unit's context key with a new value. Restorations stay anchor-based. "
    "Units, entries and consolidations are those of v1; v1 outputs are kept unchanged next to these.")


V3_RULES_NOTE = (
    "Rules v3: as v2, except that a time, number, money or percent unit counts as present through the "
    "fallback only if a line of the consolidation output holds the value (as the regex anchors normalise it) "
    "with the unit's context word adjacent to it: right after the value with up to two words between "
    "(\"56 new donors\"), or right before it with only punctuation between (\"Donors: 56\"), the rule of the "
    "pre-labelling evidence. Entity, agent, URL, date, email and phone units use the v2 fallback; "
    "modifications use the v2 line alignment; restorations stay anchor-based. v1, v2 and v3 are computed in "
    "one pass from the same entries, so per-unit comparisons are exact.")
RULES_NOTES = {"v2": V2_RULES_NOTE, "v3": V3_RULES_NOTE}


def _yn(x) -> str:
    return "n/a" if x is None else ("yes" if x else "no")


def _qa_comparison(s: dict) -> list[str]:
    """QA section 0 of a v2 or v3 run: the rule versions against each other on the same units."""
    c = s["comparison"]
    vs, cur = c["versions"], c["current"]
    later = vs[1:]
    out = [f"## 0. Rules {cur} against {' and '.join(vs[:-1])}", ""]
    out += [RULES_NOTES[v] for v in later if v in RULES_NOTES]
    out += [""]
    resc = c["rescued"]
    out += [
        "v1 first losses that a later rule set keeps at the same consolidation (standard agents): "
        + "; ".join(f"{v} {resc[v]['kept']:,} of {resc[v]['v1_losses']:,} "
                    f"({resc[v]['kept'] / max(1, resc[v]['v1_losses']):.1%})" for v in later)
        + ". v1 modifications that become drops: "
        + "; ".join(f"{v} {resc[v]['v1_modified_now_dropped']:,} of {resc[v]['v1_modified']:,}" for v in later)
        + ".",
        "",
    ]
    types = [x["type"] for x in resc[later[0]]["by_type"]]
    byt = {v: {x["type"]: x for x in resc[v]["by_type"]} for v in later}
    out += [_md(["type", "v1 losses"] + [f"kept in {v} (share)" for v in later],
                [[t, byt[later[0]][t]["v1_losses"]]
                 + [f"{byt[v][t]['kept']:,} ({byt[v][t]['kept'] / max(1, byt[v][t]['v1_losses']):.3f})" for v in later]
                 for t in types]), ""]
    if "prev_kept_now_lost" in c:
        pk = c["prev_kept_now_lost"]
        out += [f"Units that {cur} loses at a consolidation where {pk['prev']} still kept them: {pk['total']:,} "
                "(" + ", ".join(f"{x['type']} {x['lost_now']:,}" for x in pk["by_type"]) + ").", ""]
    out += [f"Hazards by g bin and modified share of first losses ({' / '.join(vs)}; point estimates, CIs in "
            f"section 4 and memory_hazard_{cur}.csv):", "",
            _md(["group", "h1", "h2", "h3-4", "h5-8", "h9+", "modified share"],
                [[h["group"]] + [" / ".join(_fmt(h.get(f"{lab}_{v}", np.nan)) for v in vs)
                                 for lab in ("h1", "h2", "h3_4", "h5_8", "h9plus", "mod_share")]
                 for h in c["hazards"]]), ""]
    out += ["BdW shape c from g = 2 (likelihood conditional on surviving the first consolidation), 95% "
            "cluster-bootstrap CIs; * marks a fit whose Beta parameters sit at the edge of the search range "
            "(the conditional likelihood leaves the mixing of the unobserved first trial free, so c is weakly "
            "identified there):", "",
            _md(["scope", "stratum"] + [f"c {v} [95% CI]" for v in vs],
                [[b["scope"], b["stratum"]] + [f"{_fmt(b[f'c_{v}'])} [{_fmt(b[f'c_lo_{v}'])}, {_fmt(b[f'c_hi_{v}'])}]"
                                               + ("*" if b.get(f"boundary_{v}") else "") for v in vs]
                 for b in c["bdw"]]), ""]
    if c.get("bdw_survivors"):
        sv_rows = {(r["version"], r["scope"]): r for r in c["bdw_survivors"]}
        out += ["BdW shape c' among the survivors of the first consolidation with the clock restarted "
                "(g' = g - 1; fitted in this pass for every rule set, so the rows are directly comparable). The "
                "beta-geometric is closed under conditioning on survival, so c' = 1 still means heterogeneity "
                "alone, and no unobserved first-trial mixing is left to fit. 95% cluster-bootstrap CIs; * as above:",
                "",
                _md(["scope"] + [f"c' {v} [95% CI]" for v in vs],
                    [[scope] + [(f"{_fmt(sv_rows[(v, scope)]['c'])} [{_fmt(sv_rows[(v, scope)]['c_lo'])}, "
                                 f"{_fmt(sv_rows[(v, scope)]['c_hi'])}]" + ("*" if sv_rows[(v, scope)]["boundary"] else ""))
                                if (v, scope) in sv_rows else "n/a" for v in vs]
                     for scope in ("All standard", "pre cohort", "post cohort")]), ""]
    out += ["H2 outcome by family: p of the constant-hazard test (cluster Wald, or LR for one agent), the "
            "hazard at g = 1 and at g >= 9, and the model with the lowest AIC:", "",
            _md(["group"] + [f"{v}: p; h1 -> h9+; best AIC" for v in vs],
                [[r["stratum"]] + [f"{_fmt_p(r[f'p_{v}'])} ({r[f'test_{v}']}); {_fmt(r[f'h1_{v}'])} -> "
                                   f"{_fmt(r[f'h9_{v}'])}; {r[f'best_{v}']}" for v in vs] for r in c["h2"]]), ""]
    out += ["Conclusions across rule sets:", "",
            _md(["conclusion", *vs, "status"],
                [[x["conclusion"], *[_yn(x[v]) for v in vs], x["status"]] for x in c["conclusions"]]), ""]
    cons = c.get("consistency", {})
    if cons:
        out += ["Reproducibility: hazards of the earlier rule sets recomputed in this pass against their own "
                "tables: " + "; ".join(f"{v} max |diff| {_fmt(x['max_abs_diff'], 6)} over {x['compared']} values"
                                       for v, x in cons.items()) + ".", ""]
    out += [f"Use of the literal fallback by anchor type under {cur} (standard agents): units kept at least once "
            "only by a literal match, and the number of such consolidation trials.", "",
            _md(["type", "units", "units with a fallback keep", "fallback trials"],
                [[x["type"], x["units"], x["units_with_fallback"], x["fallback_trials"]] for x in c["fallback"]]), ""]
    ag = c.get("agreement") or {}
    if "n" in ag:
        labs = ("kept", "modified", "dropped", "new", "restored")
        conf = ag["confusion"][cur]
        out += [
            f"For information only (rule sets are chosen from the owner's labels, not from these): agreement "
            f"with the LLM pre-labels on {ag['n']} units (review sheet as of {ag['sheet_mtime']} UTC, read only): "
            + "; ".join(f"{v} {ag['agree'][v]} (kappa {_fmt(ag['kappa'][v])})" for v in vs)
            + f". Confusion matrix of the {cur} labels (rows) against the LLM labels (columns):",
            "",
            _md([f"{cur} \\ LLM", *labs, "total", "agree"],
                [[a] + [conf.get(f"{a}|{b}", 0) for b in labs]
                 + [sum(conf.get(f"{a}|{b}", 0) for b in labs),
                    _fmt(conf.get(f"{a}|{a}", 0) / max(1, sum(conf.get(f"{a}|{b}", 0) for b in labs)))]
                 for a in labs]),
            "",
        ]
    elif ag:
        out += [f"Agreement with the LLM pre-labels: not available ({ag.get('error')}).", ""]
    return out


IDENTIFICATION_NOTE = (
    "Identification: in single-spell data heterogeneity and duration dependence trade off (a falling "
    "population hazard can come from either), so c rests on the functional form of the Beta mixing "
    "distribution; restorations give repeated spells of the same fact, which hold its heterogeneity fixed "
    "(section 8).")


def _qa_bdw_and_spells(s: dict) -> list[str]:
    """QA sections 7 (BdW) and 8 (repeated spells)."""
    out = [
        "## 7. Heterogeneity versus duration dependence (beta-discrete-Weibull)",
        "",
        "BdW (Fader, Hardie, Liu, Davin and Steenburgh 2018): each fact has its own theta ~ Beta(a, b) and "
        "S(g | theta) = (1 - theta)^(g^c). c = 1 is the beta-geometric (heterogeneity alone); c < 1 means a "
        "fact's own hazard falls with the consolidations it has survived. Maximum likelihood on the same risk "
        "sets as section 4 (right-censoring included, every g kept individually); regime cohorts are the "
        "facts whose first trial falls before (pre, censored at the agent's switch) or after (post) the "
        "agent's switch to perma-computer-use, so neither cohort is left-truncated. The CI of c resamples "
        f"agents ({B_BDW} refits); Claude Code (one agent) has only a profile-likelihood CI, which treats "
        "facts as independent. The LR test of c = 1 (df 1) treats facts as independent and is "
        "anticonservative at these sample sizes; the decision rule uses the CI: if it covers 1 the falling "
        "population hazard is consistent with heterogeneity alone, if it lies below 1 there is duration "
        "dependence beyond heterogeneity.",
        "",
        _md(["scope", "stratum", "from g", "agents", "facts", "c [95% CI]", "CI", "LR (c = 1)", "p",
             "AIC BdW - beta-geom", "AIC BdW - piecewise", "lowest AIC", "verdict"],
            [[r["scope"], r["stratum"], r["g_from"], r["n_agents"], r["n_units"],
              f"{_fmt(r['c'])} [{_fmt(r['c_lo'])}, {_fmt(r['c_hi'])}]",
              "bootstrap" if r["c_ci_method"] == "cluster_bootstrap" else "profile",
              _fmt(r["lr_c1"], 1), _fmt_p(r["p_c1"]),
              _fmt(r["aic_bdw"] - r["aic_beta_geometric"], 0), _fmt(r["aic_bdw"] - r["aic_piecewise"], 0),
              r["best_aic"], r["verdict"]] for r in s["bdw_rows"]]),
        "",
        "From g = 2 rows use the likelihood conditional on surviving the first consolidation (the same "
        "model, with the g = 1 term dropped). After the switch to perma-computer-use the hazard rises from "
        "g = 1 to g = 2 (section 6: the consolidation right after a session keeps that session's facts, "
        "the next one prunes them); a BdW can only produce that rise with c > 1, so c > 1 in scopes "
        "dominated by post-switch facts reflects this two-step pattern rather than facts that wear out.",
        "",
        "Observed and fitted hazards at g = 1, 2, 5, 10 (families and regime cohorts):",
        "",
        _md(["scope", "stratum", "from g", "g = 1 obs / BdW / BG", "g = 2", "g = 5", "g = 10"],
            [[r["scope"], r["stratum"], r["g_from"]]
             + [f"{_fmt(r.get(f'h{g}_observed', np.nan))} / {_fmt(r.get(f'h{g}_bdw', np.nan))} / "
                f"{_fmt(r.get(f'h{g}_beta_geometric', np.nan))}" if f"h{g}_observed" in r else "n/a"
                for g in (1, 2, 5, 10)]
             for r in s["bdw_rows"] if r["scope"] in ("family", "regime_cohort")]),
        "",
        IDENTIFICATION_NOTE,
        "",
        "## 8. Repeated spells of restored facts",
        "",
        "Facts that were lost and later restored, with at least one consolidation after the restoration. "
        "Spell 1 runs from entry to the first loss, spell 2 from the restoring consolidation to the next loss "
        "(or the agent's last consolidation); trial g counts consolidations from the start of each spell, so "
        "both hazards come from the same facts at the same g. `like for like` keeps facts whose first spell "
        "also began as new content of a consolidation output and whose restoration was recreated by a "
        "consolidation, so both spells start the same way. CIs and the paired difference (spell 2 - spell 1) "
        "resample agents. These are descriptions: spell 1 is selected to end in a loss, and early losses "
        "leave more time for a restoration, so spell-1 hazards of restored facts are biased upward and a "
        "negative difference is expected even if nothing about the fact changed; and a restoration can be a "
        "key collision rather than the same fact (restoration shares in section 5 are upper bounds).",
        "",
    ]
    sc = s["spell_check"]
    out += [
        _md(["check", "value"], [
            ["restored facts", sc["restored"]],
            ["with >= 1 trial in spell 2", sc["with_second_spell_trials"]],
            ["spell 2 ended in a loss", sc["second_spell_lost"]],
            ["re-lost facts in the chain (n_reloss > 0)", sc["relost_in_chain"]],
            ["facts where chain and row-level spells disagree (expected 0)",
             "n/a (v2 presence is not row-level)" if sc["mismatch_vs_chain"] is None else sc["mismatch_vs_chain"]],
            ["restored facts absent from the restoring output (expected 0)",
             "n/a" if sc["restoration_not_present"] is None else sc["restoration_not_present"]],
        ]),
        "",
        _md(["group", "subset", "facts", "g", "spell 1: n, h [95% CI]", "spell 2: n, h [95% CI]",
             "spell 2 - spell 1 [95% CI]", "all facts, spell 1"],
            [[r["group"], r["subset"], r["n_facts"], r["g"],
              f"{r['n_spell1']:,}, {_fmt(r['h_spell1'])} [{_fmt(r['h_spell1_lo'])}, {_fmt(r['h_spell1_hi'])}]",
              f"{r['n_spell2']:,}, {_fmt(r['h_spell2'])} [{_fmt(r['h_spell2_lo'])}, {_fmt(r['h_spell2_hi'])}]",
              f"{_fmt(r['diff'])} [{_fmt(r['diff_lo'])}, {_fmt(r['diff_hi'])}]",
              _fmt(r["h_all_facts_spell1"])] for r in s["repeat_rows"]]),
        "",
        f"Monthly hazards for module C: `outputs/tables/memory_hazard_monthly.parquet` (and .csv), "
        f"{s['monthly']['rows']:,} rows, {s['monthly']['months']} PT calendar months "
        f"({s['monthly']['first']} to {s['monthly']['last']}) x 5 groups, columns date, group, h1, h2, h3_4 "
        f"(hazards of the consolidations in that month, null below {s['min_units']} facts at risk; "
        f"{s['monthly']['null_h1']} null h1) and n_at_risk (all unit-trials of the month).",
        "",
    ]
    return out


def render_qa(s: dict) -> str:
    rq, meta, t = s["rows_qa"], s["meta"], s["timings"]
    t0, t1 = s["time_range"]
    out = [
        "# QA: memory chains (module B1, SPEC 6.3)" + (f", rules {s['rules']}" if s.get("rules", "v1") != "v1"
                                                       else ""),
        "",
        "Data: AI Digest, \"AI Village dataset\", 2026, https://theaidigest.org/village",
        "",
        "Aggregates only. No memory text, names, emails, phone numbers or credentials appear in this "
        "report or in outputs/; URLs appear only as domains, PERSON/email/phone values and every value "
        "on a credential line are keyed hashes.",
        "",
        f"Runtime {t['total']:.0f} s (inputs {t['inputs']:.0f}, lines + anchors {t['lines_anchors']:.0f}"
        f"{' (cache hit)' if s['cache_hit'] else ''}, interning {t['intern']:.0f}, chains {t['chains']:.0f}, "
        f"statistics and outputs {t['analysis']:.0f}). Line and anchor extraction when computed: "
        f"{meta.get('seconds_lines', 0):.0f} s + {meta.get('seconds_anchors', 0):.0f} s.",
        "",
    ]
    if s.get("comparison"):
        out += _qa_comparison(s)
    if s["agent_filter"]:
        out += [f"Pilot run on {len(s['agent_filter'])} agents.", ""]
    out += [
        "## 1. Inputs and coverage",
        "",
        _md(["item", "value", "expected"], [
            ["memory rows", rq["rows"], "246,151 (manifest)"],
            ["IDENT rows dropped (no-ops)", rq["ident_rows"], "6"],
            ["rows on abandoned lineage branches", rq["dead_rows"], "few (3 generations off the time order)"],
            ["dead generations", rq["dead_generations"], "<= 3"],
            ["live rows analysed", rq["live_rows"], ""],
            ["consolidations (live REWRITE rows)", rq["consolidations"], "85,603 rewrites minus dead"],
            ["agents with memory", s["n_agents"], f"{s['agents_total']} (all)"],
            ["rows with empty text (no anchors; kept in the chains)", meta.get("empty_rows", "n/a"),
             "a few (memory_versions treats null content as empty)"],
        ]),
        "",
        f"Time range of live rows: {t0:%Y-%m-%d %H:%M} to {t1:%Y-%m-%d %H:%M} UTC.",
        "",
        _md(["group", "agents", "consolidations", "units", "units with >= 1 trial", "unit-trials"],
            [[g, v["agents"], v["consolidations"], v["units"], v["units_at_risk"], v["unit_trials"]]
             for g, v in s["per_group"].items()]),
        "",
        "## 2. Lines, anchors and fact units",
        "",
        _md(["item", "value"], [
            ["segment characters read", meta.get("segment_chars", 0)],
            ["segment lines", meta.get("segment_lines", 0)],
            ["distinct lines extracted", meta.get("distinct_lines", 0)],
            ["distinct line characters", meta.get("distinct_chars", 0)],
            ["distinct lines with >= 1 anchor", meta.get("lines_with_anchors", 0)],
            ["distinct occurrences (type, value, context)", s["n_occurrences"]],
            ["distinct unit keys", s["n_unit_keys"]],
            ["unit keys with a hashed value", s["hashed_units"]],
            ["context lemmas shown in clear (>= 3 agents as a common noun)",
             f"{s['ctx_common']:,} of {s['ctx_total']:,}"],
            ["(agent, unit) pairs tracked", s["n_units_total"]],
            ["(agent, unit) pairs with >= 1 consolidation trial", s["n_units_at_risk"]],
        ]),
        "",
        "Units per anchor type ((agent, unit) pairs), distinct occurrences, and the share of occurrences "
        "without a context key (missing values; such units can be kept or dropped but never modified):",
        "",
        _md(["type", "units", "occurrences", "no context key"],
            [[k, s["type_counts"].get(k, 0), s["occ_type_counts"].get(k, 0),
              _fmt(s["empty_ctx"].get(k, float("nan")))] for k in TYPES]),
        "",
        "Entry kind of units (row where the unit first appeared): "
        + ", ".join(f"{k} {v:,}" for k, v in sorted(s["entry_kinds"].items())) + ".",
        "",
        "## 3. Chain checks",
        "",
    ]
    ct, cq = s["cons_tot"], s["chain_qa"]
    out += [
        _md(["check", "value"], [
            ["unit-trials (sum over consolidations of units at risk)", ct.get("at_risk", 0)],
            ["kept", ct.get("kept", 0)], ["dropped", ct.get("dropped", 0)],
            ["modified", ct.get("modified", 0)], ["restorations", ct.get("restored", 0)],
            ["units first seen in a consolidation output", ct.get("entered", 0)],
            ["never-lost units missing from the consolidation input (after a truncation)",
             ct.get("alive_missing_in", 0)],
            ["undo rows (revert, trunc_other)", cq.get("undo_rows", 0)],
            ["fork rows extending an older row", cq.get("fork_rows", 0)],
            ["units removed from tracking by an undo", cq.get("untracked_by_undo", 0)],
            ["first losses: dropped / modified / censored",
             f"{s['events']['dropped']:,} / {s['events']['modified']:,} / {s['events']['censored']:,}"],
            ["unit-trials: per-unit sum vs per-consolidation sum",
             f"{s['accounting']['unit_trials_from_units']:,} vs "
             f"{s['accounting']['unit_trials_from_consolidations']:,} ("
             f"{'ok' if s['accounting']['unit_trials_from_units'] == s['accounting']['unit_trials_from_consolidations'] else 'MISMATCH'})"],
            ["first losses: per-unit vs per-consolidation",
             f"{s['accounting']['losses_from_units']:,} vs {s['accounting']['losses_from_consolidations']:,} ("
             f"{'ok' if s['accounting']['losses_from_units'] == s['accounting']['losses_from_consolidations'] else 'MISMATCH'})"],
        ]),
        "",
        "## 4. Hazard of loss by model family (H2)",
        "",
        f"h_g = P(lost at consolidation g | kept through g - 1). 95% CIs resample agents within the group "
        f"({BOOT_REPS} replicates, seed {s.get('seed', '')}); Claude Code is one agent, so its CIs treat units "
        f"as independent (Wilson). Generations with fewer than {s['min_units']} units at risk are not reported.",
        "",
    ]
    fam_rows = [r for r in s["h2_rows"] if r["scope"] == "family"]
    out += [
        _md(["group", "agents", "unit-trials", "h1", "h2", "h3-4", "h5-8", "h9+", "geometric h"],
            [[r["stratum"], r["n_agents"], r["n_trials"], _ci(r, "h1"), _ci(r, "h2"), _ci(r, "h3_4"),
              _ci(r, "h5_8"), _ci(r, "h9plus"), _fmt(r["h_geometric"])] for r in fam_rows]),
        "",
        "H2 tests: geometric (constant hazard) vs piecewise-constant hazard over g = 1, 2, 3-4, 5-8, 9+. "
        "The likelihood-ratio test treats units as independent; the Wald test uses the cluster-bootstrap "
        "covariance. The beta-geometric model lets each unit keep a constant hazard drawn from a Beta "
        "distribution, which makes the population hazard decrease with g.",
        "",
        _md(["scope", "stratum", "LR", "df", "p (LR)", "Wald", "p (Wald, cluster)", "AIC geometric",
             "AIC beta-geometric", "AIC piecewise", "beta-geom a, b"],
            [[r["scope"], r["stratum"], _fmt(r["lr"], 1), r["df"], _fmt_p(r["p_lr"]),
              _fmt(r["wald_cluster"], 1), _fmt_p(r["p_wald_cluster"]), _fmt(r["aic_geometric"], 0),
              _fmt(r["aic_betageom"], 0), _fmt(r["aic_piecewise"], 0),
              f"{_fmt(r['betageom_alpha'], 3)}, {_fmt(r['betageom_beta'], 3)}"] for r in s["h2_rows"]]),
        "",
    ]
    out += [
        f"CIs and the Wald test resample agents. With fewer than {MIN_CLUSTERS_CI} agents carrying trials "
        f"(column `agents`) the bootstrap CIs are unstable; with fewer than {MIN_CLUSTERS_WALD} the Wald test "
        "is not computed. The naive LR test is anticonservative because units of one agent are dependent.",
        "",
        "Verbatim line retention per consolidation, from the cached line hashes (a cross-check that needs no "
        "anchors): share of the input lines that were already in the previous version (old) or arrived in "
        "appended text since then (new) and appear unchanged in the output.",
        "",
        _md(["group", "regime", "consolidations", "old lines kept", "new lines kept",
             "share of input lines kept: median [IQR]", "median units in the input"],
            [[r["group"], r["regime"], r["consolidations"], _fmt(r["old_kept"]), _fmt(r["new_kept"]),
              f"{_fmt(r['share_median'])} [{_fmt(r['share_q25'])}, {_fmt(r['share_q75'])}]",
              _fmt(r["units_in_median"], 0)] for r in s["line_retention"]]),
        "",
    ]
    out += ["## 5. Modification and restoration", ""]
    mods = [r for r in s["mod_rows"] if r["scope"] == "family" and r["g"] in ("1", "2", "3", "5", "10")]
    out += [
        _md(["group", "g", "units at risk", "modification rate", "modified share of losses"],
            [[r["stratum"], r["g"], r["n_at_risk"], _ci(r, "modification_rate"),
              f"{_fmt(r['modified_share_of_losses'])} [{_fmt(r['modified_share_lo'])}, "
              f"{_fmt(r['modified_share_hi'])}]"] for r in mods]),
        "",
        _md(["group", "lost", "lost with later trials", "restored", "share restored", "reappended",
             "recreated", "median gap (consolidations)", "share restored at the next consolidation",
             "re-lost after restoration"],
            [[g, v["lost"], v["lost_with_later_trials"], v["restored"], _fmt(v["share"]), v["reappended"],
              v["recreated"], _fmt(v["gap_median"], 1), _fmt(v["within_1"]), v["relost"]]
             for g, v in s["restoration"].items() if v["lost"]]),
        "",
        "A restoration is the same unit key reappearing. For quantities with a generic context key "
        "(e.g. a small count of tasks) a later, unrelated fact can share the key, so restoration shares are "
        "upper bounds; by anchor type they are in memory_by_anchor.csv.",
        "",
        "## 6. Regime (perma-computer-use), entry kind and memory-system epochs",
        "",
    ]
    reg_rows = [r for r in s["h2_rows"] if r["scope"].startswith("regime") or r["scope"] == "entry_kind"
                or r["scope"] == "memory_epoch"]
    out += [
        _md(["scope", "stratum", "agents", "unit-trials", "h1", "h2", "h3-4", "h5-8", "h9+", "geometric h"],
            [[r["scope"], r["stratum"], r["n_agents"], r["n_trials"], _ci(r, "h1"), _ci(r, "h2"),
              _ci(r, "h3_4"), _ci(r, "h5_8"), _ci(r, "h9plus"), _fmt(r["h_geometric"])] for r in reg_rows]),
        "",
        "Regime and epoch strata are trial-level: a consolidation counts in the regime (epoch) of its own "
        "row, so units that cross a boundary enter the later risk sets at their current g. Epochs run "
        "between consecutive dates of memory-category CHANGELOG entries (start date included). Entry kind "
        "is the relation of the row where the unit first appeared (session = scaffold session block, note = "
        "self-note append, rewrite = new in a consolidation output, first = the agent's first row).",
        "",
    ]
    out += _qa_bdw_and_spells(s)
    out += [
        f"## 9. Memory-category CHANGELOG entries (+/- {CHANGELOG_WINDOW} run days, standard agents)",
        "",
        "Consolidations whose run day falls in the window before the entry's first day or after its last "
        "day. Hazards need at least the reporting threshold of unit-trials; the difference (after - before) "
        "gets a paired agent-bootstrap CI only when at least 3 agents carry trials on each side.",
        "",
    ]
    out += [
        _md(["entry", "date", "cons before", "cons after", "h(g=1) before", "h(g=1) after",
             "diff [95% CI]", "h(g>=2) before", "h(g>=2) after", "diff [95% CI]"],
            [[r["entry_id"], r["date_start"], r["consolidations_before"], r["consolidations_after"],
              _fmt(r["h_g1_before"]), _fmt(r["h_g1_after"]),
              f"{_fmt(r['diff_g1'])} [{_fmt(r['diff_g1_lo'])}, {_fmt(r['diff_g1_hi'])}]",
              _fmt(r["h_g2plus_before"]), _fmt(r["h_g2plus_after"]),
              f"{_fmt(r['diff_g2plus'])} [{_fmt(r['diff_g2plus_lo'])}, {_fmt(r['diff_g2plus_hi'])}]"]
             for r in s["changelog_rows"]]),
        "",
        "## 10. By anchor type (standard agents pooled)",
        "",
    ]
    ar = [r for r in s["anchor_rows"] if r["stratum"] == ALL_LABEL]
    out += [
        _md(["type", "units", "unit-trials", "h1", "h2", "h9+", "geometric h", "modification rate",
             "restored share of lost"],
            [[r["anchor_type"], r["n_units"], r["n_trials"], _ci(r, "h1"), _ci(r, "h2"), _ci(r, "h9plus"),
              _fmt(r["h_geometric"]), _fmt(r["modification_rate"]), _fmt(r["restored_share_of_lost"])]
             for r in ar]),
        "",
        "## 11. Labelling file and memory_facts",
        "",
        (f"- `{s['labels']['path']}`: {s['labels']['pairs']} consolidation pairs (prev_uid = the "
         f"consolidation's input row, next_uid = its output), {s['labels']['units']} units, rule labels "
         f"{s['labels']['labels']}. human_label and notes are empty for the owner."
         if s.get("rules", "v1") == "v1" else
         f"- `{s['labels']['path']}` (mode 600): rule_label_{s['rules']} for the {s['labels']['units']} units of "
         f"memory_pairs.csv ({s['labels']['pairs']} pairs), labels {s['labels']['labels']}; checks "
         f"{ {k: v for k, v in s['labels']['checks'].items() if '->' not in k} } (all expected 0)."),
        f"- `{s['facts']['path']}`: {s['facts']['rows']:,} presence spells of {s['facts']['units']:,} "
        f"(agent, unit) pairs; rows without a survival record (units seen only in undone rows): "
        f"{s['facts']['null_survival']:,}.",
        "",
        "## 12. Outputs",
        "",
    ]
    out += [f"- {k}: `{v}`" for k, v in s["out_files"].items()]
    out += ["", "## 13. Per agent", ""]
    out += [_md(["agent", "group", "consolidations", "units"],
                [[s["agent_names"][a], s["group"][a], v["cons"], v["units"]]
                 for a, v in sorted(s["per_agent"].items(), key=lambda kv: s["agent_names"][kv[0]])])]
    out += ["", "## 14. Comparison with expectations and verdict", ""]
    out += s.get("verdict_lines", [])
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Module B1: memory chains (SPEC 6.3).")
    p.add_argument("--config", default=None)
    p.add_argument("--reextract", action="store_true")
    p.add_argument("--workers", type=int, default=None)
    p.add_argument("--agents", default="", help="Comma-separated agent names (pilot).")
    p.add_argument("--rules", choices=("v1", "v2", "v3"), default="v1",
                   help="v2: literal presence fallback and line-aligned modification; v3: v2 with the context "
                        "word next to quantity values. Writes _v2 / _v3 outputs next to v1.")
    args = p.parse_args(argv)
    cfg = load_config(args.config)
    agents = [a for a in args.agents.split(",") if a] or None
    s = run_memory(cfg, reextract=args.reextract, n_workers=args.workers, agent_filter=agents, rules=args.rules)
    print(json.dumps({k: v for k, v in s["timings"].items()}, indent=1))


if __name__ == "__main__":
    main()
