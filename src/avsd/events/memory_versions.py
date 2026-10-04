"""Memory snapshot versions for module B1, path S (SPEC 6.3.1).

Every `agent_memories` row is a full memory snapshot (schema_notes 4.2). Rows
are ordered per agent by (created_at, id), and each row gets one relation to
the earlier rows of its agent:

- `first`: the agent's first row. Generation 0.
- `append_session` / `append_note`: the previous row is a proper prefix. The
  appended text holds a scaffold session block ("PREVIOUS (NOW ENDED) ...
  SESSION (...)" at a line start) or is a self-note.
- `ident`: identical to the previous row. Not a version.
- `revert`: equal to a row 2..REVERT_WINDOW back (an undo); that row is the base.
- `trunc_other`: a proper prefix of the previous row that is not a revert.
- `fork_append`: extends a row 2..FORK_WINDOW back instead of the previous
  one; that older row is the base.
- `rewrite`: anything else, i.e. an LLM consolidation. A generation.

Generations are `first` and `rewrite` rows. Each row inherits the lineage
generation `gen_id` of its base, so a fork that extends a row from before the
latest rewrite continues the older lineage. A rewrite's input is the previous
row (identical rows resolved to the earliest copy), its parent generation is
that input's `gen_id`, and `version_idx` is its depth in the lineage.
`pair_kind` keeps the plain previous-row class (append, rewrite, ident, trunc)
used in the schema_notes 4.2 counts.

The text table is stored in id order, so every agent spans all row groups.
It is streamed once, one row group per worker, and only 64-bit SHA-1 hashes
leave the worker: the full content plus the prefixes at the lengths that the
comparisons need. Those lengths are known in advance from `content_len`
(previous row, next row, the FORK_WINDOW earlier rows). Equal hashes of a
prefix and a whole row mean `startswith`.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import hashlib
import multiprocessing as mp
import os
import re
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import polars as pl
import pyarrow.parquet as pq

from avsd.config import load_config

RELS = (
    "first", "append_session", "append_note", "rewrite", "ident", "revert",
    "trunc_other", "fork_append",
)
PAIR_KINDS = ("append", "rewrite", "ident", "trunc")
GENERATION_RELS = ("first", "rewrite")
REVERT_WINDOW = 6  # rows back compared for equality (1 back is `ident`)
FORK_WINDOW = 50  # rows back searched for a prefix
# The scaffold writes a memory row ~16 ms before its STOP/CONSOLIDATE event, so
# the rewrite of an agent's first CONSOLIDATE cycle precedes that event.
REGIME_TOLERANCE_S = 1.0

# Previous-row classes and rare relations verified on the pinned export
# (schema_notes 4.2, decisions "Module B1").
EXPECTED_PAIR_KINDS = {"append": 160_323, "rewrite": 85_657, "ident": 6, "trunc": 119}
EXPECTED_REVERT, EXPECTED_FORK = 113, 53

# Labels: "PREVIOUS (NOW ENDED) COMPUTER USE SESSION (<uuid>)" until
# 2026-03-24, "PREVIOUS (NOW ENDED) SESSION (<uuid>)" briefly, then
# "PREVIOUS (NOW ENDED) SESSION (Day N, HH:MM to HH:MM)" or a PT date range.
_LABEL_HEAD = "PREVIOUS (NOW ENDED) "
_LABEL = re.compile(r"PREVIOUS \(NOW ENDED\) (?:COMPUTER USE )?SESSION \(([^)\n]*)\)")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


# --- worker side: one row group of the text table -------------------------

def _h64(h) -> int:
    return int.from_bytes(h.digest()[:8], "little", signed=True)


def prefix_hashes(text: str, lens: np.ndarray) -> tuple[int, np.ndarray]:
    """Hash of `text` and of `text[:L]` for each sorted L < len(text), in one pass."""
    h = hashlib.sha1()
    out = np.empty(len(lens), dtype=np.int64)
    start = 0
    for i, n in enumerate(lens.tolist()):
        h.update(text[start:n].encode("utf-8", "surrogatepass"))
        out[i] = _h64(h)  # digest() does not finalize the hash object
        start = n
    h.update(text[start:].encode("utf-8", "surrogatepass"))
    return _h64(h), out


def last_session_label(text: str) -> tuple[int, str | None]:
    """Char offset of the last session-block label at a line start (-1 if none) and its UUID."""
    end = len(text)
    while (pos := text.rfind(_LABEL_HEAD, 0, end)) >= 0:
        if pos == 0 or text[pos - 1] == "\n":
            m = _LABEL.match(text, pos)
            if m:
                inner = m.group(1).strip()
                return pos, inner if _UUID.fullmatch(inner) else None
        end = pos
    return -1, None


def _hash_row_group(
    path: str, rg: int, ids: list[str], lens: list[int], needs: list[np.ndarray]
) -> tuple[np.ndarray, list[np.ndarray], np.ndarray, list[str | None]]:
    tb = pq.ParquetFile(path).read_row_group(rg, columns=["id", "content"])
    got = tb.column("id").to_pylist()
    if got != ids:
        raise ValueError(f"row group {rg}: ids differ from the planned order")
    full = np.empty(len(ids), dtype=np.int64)
    label_pos = np.empty(len(ids), dtype=np.int64)
    prefs, sids = [], []
    for i, text in enumerate(tb.column("content").to_pylist()):
        text = text or ""
        if len(text) != lens[i]:
            raise ValueError(f"row {ids[i]}: content_len {lens[i]} != text length {len(text)}")
        full[i], p = prefix_hashes(text, needs[i])
        label_pos[i], sid = last_session_label(text)
        prefs.append(p)
        sids.append(sid)
    return full, prefs, label_pos, sids


# --- driver ----------------------------------------------------------------

def _needed_lengths(lens: np.ndarray, bounds: list[tuple[int, int]]) -> list[np.ndarray]:
    """Prefix lengths each row must hash: shorter rows among the FORK_WINDOW
    before it (the previous row included) and the next row."""
    need: list[np.ndarray] = [None] * len(lens)  # type: ignore[list-item]
    for s, e in bounds:
        for k in range(s, e):
            cand = lens[max(s, k - FORK_WINDOW):k]
            if k + 1 < e:
                cand = np.append(cand, lens[k + 1])
            need[k] = np.unique(cand[cand < lens[k]])
    return need


def _hash_all(
    text_path: Path, ids: list[str], lens: np.ndarray, need: list[np.ndarray], n_workers: int
) -> tuple[np.ndarray, list[np.ndarray], np.ndarray, list[str | None]]:
    pos_of = {x: i for i, x in enumerate(ids)}
    pf = pq.ParquetFile(text_path)
    text_ids = pq.read_table(text_path, columns=["id"]).column("id").to_pylist()
    if len(text_ids) != len(ids) or set(text_ids) != pos_of.keys():
        raise ValueError("agent_memories and agent_memories_text ids differ")
    tasks, positions, start = [], [], 0
    for g in range(pf.metadata.num_row_groups):
        stop = start + pf.metadata.row_group(g).num_rows
        g_ids = text_ids[start:stop]
        pos = [pos_of[x] for x in g_ids]
        tasks.append((str(text_path), g, g_ids, lens[pos].tolist(), [need[p] for p in pos]))
        positions.append(pos)
        start = stop

    n = len(ids)
    full = np.empty(n, dtype=np.int64)
    label_pos = np.empty(n, dtype=np.int64)
    prefs: list[np.ndarray] = [None] * n  # type: ignore[list-item]
    sids: list[str | None] = [None] * n

    def scatter(pos, res):
        f, p, lp, sd = res
        full[pos], label_pos[pos] = f, lp
        for i, k in enumerate(pos):
            prefs[k], sids[k] = p[i], sd[i]

    if n_workers <= 1:
        for pos, t in zip(positions, tasks):
            scatter(pos, _hash_row_group(*t))
    else:
        # spawn: polars' thread pool makes fork unsafe.
        with ProcessPoolExecutor(n_workers, mp_context=mp.get_context("spawn")) as ex:
            for pos, res in zip(positions, ex.map(_hash_row_group, *zip(*tasks))):
                scatter(pos, res)
    return full, prefs, label_pos, sids


def _classify(
    lens: np.ndarray,
    bounds: list[tuple[int, int]],
    need: list[np.ndarray],
    full: np.ndarray,
    prefs: list[np.ndarray],
    label_pos: np.ndarray,
) -> dict[str, np.ndarray]:
    n = len(lens)
    rel = np.empty(n, dtype=object)
    pair = np.full(n, None, dtype=object)
    base = np.full(n, -1, dtype=np.int64)
    has_block = np.zeros(n, dtype=bool)

    def pref_at(k: int, length: int) -> int | None:
        i = int(np.searchsorted(need[k], length))
        return int(prefs[k][i]) if i < len(need[k]) and need[k][i] == length else None

    for s, e in bounds:
        rel[s] = "first"
        for k in range(s + 1, e):
            p, lk, lp, hk = k - 1, int(lens[k]), int(lens[k - 1]), int(full[k])
            if lk == lp and hk == full[p]:
                pair[k], rel[k], base[k] = "ident", "ident", p
                continue
            if lp < lk and pref_at(k, lp) == full[p]:
                block = label_pos[k] >= lp
                pair[k], base[k], has_block[k] = "append", p, block
                rel[k] = "append_session" if block else "append_note"
                continue
            is_trunc = lk < lp and pref_at(p, lk) == hk
            pair[k] = "trunc" if is_trunc else "rewrite"
            rev = next(
                (j for j in range(k - 2, max(s, k - REVERT_WINDOW) - 1, -1)
                 if lens[j] == lk and full[j] == hk),
                -1,
            )
            if rev >= 0:
                rel[k], base[k] = "revert", rev
                continue
            if is_trunc:
                rel[k], base[k] = "trunc_other", p
                continue
            fork = next(
                (j for j in range(k - 2, max(s, k - FORK_WINDOW) - 1, -1)
                 if 0 < lens[j] < lk and pref_at(k, int(lens[j])) == full[j]),
                -1,
            )
            if fork >= 0:
                rel[k], base[k] = "fork_append", fork
                has_block[k] = label_pos[k] >= lens[fork]
            else:
                rel[k], base[k] = "rewrite", p
    return {"rel": rel, "pair": pair, "base": base, "has_block": has_block}


def _lineage(
    rel: np.ndarray, base: np.ndarray, bounds: list[tuple[int, int]]
) -> dict[str, np.ndarray]:
    n = len(rel)
    gen = np.full(n, -1, dtype=np.int64)
    depth = np.zeros(n, dtype=np.int64)
    parent = np.full(n, -1, dtype=np.int64)
    inp = np.full(n, -1, dtype=np.int64)
    for s, e in bounds:
        for k in range(s, e):
            if rel[k] == "first":
                gen[k] = k
            elif rel[k] == "rewrite":
                i = k - 1
                while rel[i] == "ident":
                    i = base[i]
                gen[k], inp[k], parent[k] = k, i, gen[i]
                depth[k] = depth[gen[i]] + 1
            else:
                gen[k] = gen[base[k]]
                depth[k] = depth[gen[k]]
    return {"gen": gen, "depth": depth, "parent": parent, "input": inp}


def _agent_regimes(tables_dir: Path) -> pl.DataFrame:
    cons = (
        pl.scan_parquet(tables_dir / "events.parquet")
        .filter((pl.col("action_type") == "CONSOLIDATE") & pl.col("agent_id").is_not_null())
        .group_by("agent_id")
        .agg(pl.col("created_at").min().alias("first_consolidate"))
    )
    cc = (
        pl.scan_parquet(tables_dir / "claude_code_sessions.parquet")
        .select("agent_id").unique().with_columns(pl.lit("claude_code").alias("scaffold"))
    )
    return cons.join(cc, on="agent_id", how="full", coalesce=True).collect()


def classify_memory_rows(tables_dir: Path, n_workers: int | None = None) -> pl.DataFrame:
    """One row per memory snapshot with its relation, base and lineage generation.

    Reads `agent_memories`, `agent_memories_text`, `events` (first CONSOLIDATE
    per agent) and `claude_code_sessions` from `tables_dir`. With n_workers > 1
    the row groups are hashed in spawned processes, so a calling script needs
    the `if __name__ == "__main__":` guard.
    """
    tables_dir = Path(tables_dir)
    if n_workers is None:
        n_workers = int(os.environ.get("SLURM_CPUS_PER_TASK") or os.cpu_count() or 1)
    meta = (
        pl.read_parquet(
            tables_dir / "agent_memories.parquet",
            columns=["id", "agent_id", "created_at", "content_len"],
        )
        .sort("agent_id", "created_at", "id")
    )
    if not meta["id"].is_unique().all():
        raise ValueError("duplicate memory ids")
    ids = meta["id"].to_list()
    lens = meta["content_len"].fill_null(0).to_numpy().astype(np.int64)
    agent_codes = meta["agent_id"].rle_id().to_numpy()
    cut = np.flatnonzero(np.diff(agent_codes)) + 1
    starts = np.concatenate([[0], cut]).tolist()
    bounds = list(zip(starts, starts[1:] + [len(ids)]))

    need = _needed_lengths(lens, bounds)
    full, prefs, label_pos, sids = _hash_all(
        tables_dir / "agent_memories_text.parquet", ids, lens, need, n_workers
    )
    c = _classify(lens, bounds, need, full, prefs, label_pos)
    lin = _lineage(c["rel"], c["base"], bounds)

    pos = np.arange(len(ids))
    id_arr = np.array(ids, dtype=object)

    def ref(idx: np.ndarray) -> list[str | None]:
        return [id_arr[i] if i >= 0 else None for i in idx.tolist()]

    prev = np.where(np.isin(pos, starts), -1, pos - 1)
    is_gen = np.isin(c["rel"], GENERATION_RELS)
    sid = [s if b else None for s, b in zip(sids, c["has_block"].tolist())]
    df = meta.with_columns(
        pl.Series("prev_id", ref(prev), dtype=pl.String),
        pl.Series("base_id", ref(c["base"]), dtype=pl.String),
        pl.Series(
            "base_lag",
            [k - b if b >= 0 else None for k, b in enumerate(c["base"].tolist())],
            dtype=pl.Int32,
        ),
        pl.Series("rel", c["rel"].tolist(), dtype=pl.Enum(RELS)),
        pl.Series("pair_kind", c["pair"].tolist(), dtype=pl.Enum(PAIR_KINDS)),
        pl.Series("is_generation", is_gen, dtype=pl.Boolean),
        pl.Series("version_idx", lin["depth"], dtype=pl.Int32),
        pl.Series("gen_id", ref(lin["gen"]), dtype=pl.String),
        pl.Series("parent_gen_id", ref(lin["parent"]), dtype=pl.String),
        pl.Series("input_row_id", ref(lin["input"]), dtype=pl.String),
        pl.Series("has_session_block", c["has_block"], dtype=pl.Boolean),
        pl.Series("session_id", sid, dtype=pl.String),
    )
    reg = _agent_regimes(tables_dir)
    df = (
        df.join(reg, on="agent_id", how="left")
        .with_columns(pl.col("scaffold").fill_null("standard"))
        .with_columns(
            pl.when(
                (pl.col("scaffold") != "claude_code")
                & (pl.col("created_at") >= pl.col("first_consolidate")
                   - pl.duration(milliseconds=int(REGIME_TOLERANCE_S * 1000)))
            ).then(pl.lit("post")).otherwise(pl.lit("pre")).alias("regime_cu"),
        )
    )
    return df.select(
        "id", "agent_id", "created_at", "prev_id", "base_id", "rel", "is_generation",
        "version_idx", "parent_gen_id", "input_row_id", "session_id", "content_len",
        "pair_kind", "base_lag", "gen_id", "has_session_block", "scaffold", "regime_cu",
    )


# --- QA ---------------------------------------------------------------------

def _counts(df: pl.DataFrame, col: str, keys: tuple[str, ...]) -> dict[str, int]:
    got = dict(df.group_by(col).len().iter_rows())
    return {k: int(got.get(k, 0)) for k in keys}


def summarize(df: pl.DataFrame) -> dict:
    """Aggregate counts for QA: relations overall, by era, scaffold and agent."""
    gens = df.filter(pl.col("is_generation"))
    prev_gen = (
        gens.sort("agent_id", "created_at", "id")
        .with_columns(pl.col("id").shift(1).over("agent_id").alias("time_prev_gen"))
    )
    rewrites = df.filter(pl.col("rel") == "rewrite")
    is_gen_ids = set(gens["id"].to_list())

    def lag(r: str) -> dict[int, int]:
        vc = df.filter(pl.col("rel") == r)["base_lag"].value_counts().sort("base_lag")
        return dict(vc.iter_rows())

    by_agent = (
        df.group_by("agent_id")
        .agg(
            pl.len().alias("rows"),
            pl.col("is_generation").sum().alias("generations"),
            pl.col("version_idx").max().alias("max_version_idx"),
            *[(pl.col("rel") == r).sum().alias(r) for r in RELS],
            pl.col("scaffold").first(),
            pl.col("created_at").min().alias("first_row"),
        )
        .sort("first_row")
    )
    return {
        "n_rows": df.height,
        "n_agents": df["agent_id"].n_unique(),
        "time_range": (df["created_at"].min(), df["created_at"].max()),
        "rel": _counts(df, "rel", RELS),
        "pair_kind": _counts(df, "pair_kind", PAIR_KINDS),
        "rel_by_regime": {
            r: _counts(df.filter(pl.col("regime_cu") == r), "rel", RELS) for r in ("pre", "post")
        },
        "rel_by_scaffold": {
            s: _counts(df.filter(pl.col("scaffold") == s), "rel", RELS)
            for s in ("standard", "claude_code")
        },
        "revert_pair_kind": _counts(df.filter(pl.col("rel") == "revert"), "pair_kind", PAIR_KINDS),
        "revert_lag": lag("revert"),
        "fork_lag": lag("fork_append"),
        "fork_with_session_block": int(
            df.filter((pl.col("rel") == "fork_append") & pl.col("has_session_block")).height
        ),
        "append_session_with_uuid": int(
            df.filter((pl.col("rel") == "append_session") & pl.col("session_id").is_not_null())
            .height
        ),
        "rewrite_input_is_generation": int(rewrites["input_row_id"].is_in(list(is_gen_ids)).sum()),
        "parent_gen_not_time_previous": int(
            prev_gen.filter(
                pl.col("parent_gen_id").is_not_null()
                & (pl.col("parent_gen_id") != pl.col("time_prev_gen"))
            ).height
        ),
        "by_agent": by_agent,
    }


def _md_table(header: list[str], rows: list[list]) -> str:
    def fmt(v):
        return f"{v:,}" if isinstance(v, int) else str(v)
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(fmt(v) for v in r) + " |" for r in rows]
    return "\n".join(lines)


def render_qa(summary: dict, agent_names: dict[str, str], runtime_s: float | None = None) -> str:
    """Markdown QA report. Aggregates and agent (model) names only."""
    s = summary
    exp_rel = {
        "append_session + append_note": (
            s["rel"]["append_session"] + s["rel"]["append_note"], EXPECTED_PAIR_KINDS["append"]),
        "revert": (s["rel"]["revert"], EXPECTED_REVERT),
        "fork_append": (s["rel"]["fork_append"], EXPECTED_FORK),
        "rewrite + fork_append": (
            s["rel"]["rewrite"] + s["rel"]["fork_append"], EXPECTED_PAIR_KINDS["rewrite"]),
    }
    t0, t1 = s["time_range"]
    out = [
        "# QA: memory versions (module B1, path S)",
        "",
        "Data: AI Digest, \"AI Village dataset\", 2026, https://theaidigest.org/village",
        "",
        f"Rows {s['n_rows']:,} (manifest 246,151), agents {s['n_agents']}, "
        f"created_at {t0:%Y-%m-%d %H:%M} to {t1:%Y-%m-%d %H:%M} UTC."
        + (f" Runtime {runtime_s:.0f} s." if runtime_s is not None else ""),
        "",
        "## Previous-row classes vs schema_notes 4.2",
        "",
        _md_table(["pair_kind", "rows", "expected"],
                  [[k, s["pair_kind"][k], EXPECTED_PAIR_KINDS[k]] for k in PAIR_KINDS]),
        "",
        "## Relations",
        "",
        _md_table(["rel", "rows", "pre", "post", "standard", "claude_code"],
                  [[r, s["rel"][r], s["rel_by_regime"]["pre"][r], s["rel_by_regime"]["post"][r],
                    s["rel_by_scaffold"]["standard"][r], s["rel_by_scaffold"]["claude_code"][r]]
                   for r in RELS]),
        "",
        _md_table(["check", "rows", "expected"], [[k, a, b] for k, (a, b) in exp_rel.items()]),
        "",
        f"- Reverts by previous-row class: {s['revert_pair_kind']}. Rows back: {s['revert_lag']}.",
        f"- Forks by rows back to their base: {s['fork_lag']}. "
        f"With a session block: {s['fork_with_session_block']}.",
        f"- append_session rows whose label carries a session UUID: "
        f"{s['append_session_with_uuid']:,} (later labels give a day/time range only).",
        f"- Rewrites whose input row is itself a generation: {s['rewrite_input_is_generation']:,}.",
        f"- Generations whose lineage parent is not the previous generation in time: "
        f"{s['parent_gen_not_time_previous']:,}.",
        "",
        "## Per agent",
        "",
    ]
    rows = [
        [agent_names.get(r["agent_id"], "unknown"), r["scaffold"], r["rows"], r["generations"],
         r["max_version_idx"], r["append_session"] + r["append_note"], r["rewrite"],
         r["revert"] + r["trunc_other"], r["fork_append"], r["ident"]]
        for r in s["by_agent"].iter_rows(named=True)
    ]
    out.append(_md_table(
        ["agent", "scaffold", "rows", "generations", "max version", "append", "rewrite",
         "revert+trunc", "fork", "ident"], rows))
    return "\n".join(out) + "\n"


def build_memory_versions(cfg: dict | None = None, n_workers: int | None = None) -> pl.DataFrame:
    """Write data/interim/memory_versions.parquet and outputs/qa/memory_versions.md."""
    cfg = cfg or load_config()
    t = time.perf_counter()
    df = classify_memory_rows(cfg["paths"]["tables"], n_workers)
    runtime = time.perf_counter() - t
    out = cfg["paths"]["interim"] / "memory_versions.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out, compression="zstd")
    agents = pl.read_parquet(cfg["paths"]["tables"] / "agents.parquet", columns=["id", "name"])
    names = dict(agents.iter_rows())
    qa = cfg["paths"]["outputs"] / "qa" / "memory_versions.md"
    qa.parent.mkdir(parents=True, exist_ok=True)
    qa.write_text(render_qa(summarize(df), names, runtime), encoding="utf-8")
    return df


if __name__ == "__main__":
    build_memory_versions()
