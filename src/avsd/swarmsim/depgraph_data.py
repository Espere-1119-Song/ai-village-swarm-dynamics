"""Data stage of D2: sessions, turns and raw artifact touches (SPEC 8.3).

`extract_touches(cfg, workers)` reads the turn table, the tool-output refs of the unified event
table and the provider responses, runs the touch rules of `avsd.swarmsim.touches` per agent (in
session and turn order, so the working directory, the GUI focus and the directory-to-remote map
carry over) and writes, under `data/interim/depgraph/` (private, gitignored):

- `touches.parquet`: one row per (turn, ref, mode, rule) with the session, the agent and the time;
- `session_gui.parquet`: GUI writes per session and how many had no focus to attach to;
- `repo_roots.parquet`: local repository roots per agent;
- `message_refs.parquet`: refs in the provider responses (cached; the slowest step).

`load_sessions(cfg)` gives one row per computer-use session with its agent, goal, era, start,
turn count and duration.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import os
import re
import time
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path
from typing import Any

import polars as pl
import pyarrow.parquet as pq

from avsd.swarmsim.touches import MAIN_RULES, AgentState, session_touches, text_refs

TURN_FIELDS = {"cmd": "command", "text": "text", "content": "content", "description": "description",
               "query": "query", "goal": "sessionGoal"}
_MSG_PREFILTER = re.compile(r"https?://|www\.|github\.com|gitlab\.com|google\.com/|~/|\./|"
                            r"/(?:home|tmp|root|workspace|workspaces|mnt|media|opt|srv|var|data|app|"
                            r"Users|scratch)/")
# Keys of a provider response whose values are tool-call arguments or metadata, not prose.
_SKIP_KEYS = frozenset({
    "input", "arguments", "functionCall", "function_call", "tool_calls", "action", "signature",
    "thoughtSignature", "usage", "usageMetadata", "encrypted_content", "partial_json", "id", "call_id",
    "name", "model", "modelVersion", "responseId", "status", "type", "role", "index", "finishReason",
    "stop_reason", "stop_sequence", "annotations", "logprobs",
})
_TEXT_KEYS = frozenset({"text", "thinking", "reasoning_content", "reasoning", "content", "refusal"})
MSG_CAP = 50_000


def paths(cfg: dict, rules: str = MAIN_RULES) -> dict[str, Path]:
    """Private files of the data stage; rule versions other than the main one get a suffix."""
    base = Path(cfg["paths"]["interim"]) / "depgraph"
    sfx = "" if rules == MAIN_RULES else f"_{rules}"
    return {
        "dir": base,
        "touches": base / f"touches{sfx}.parquet",
        "gui": base / f"session_gui{sfx}.parquet",
        "roots": base / f"repo_roots{sfx}.parquet",
        "msg": base / "message_refs.parquet",
    }


def narrative_text(raw: str | None, cap: int = MSG_CAP) -> str:
    """Text, thinking and reasoning parts of a raw provider response (tool-call arguments left out)."""
    if not raw:
        return ""
    try:
        import orjson

        obj = orjson.loads(raw)
    except Exception:  # noqa: BLE001
        return ""
    out: list[str] = []
    size = 0

    def walk(o: Any) -> None:
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
                if not isinstance(v, str):
                    walk(v)

    walk(obj)
    return "\n".join(out)[:cap]


def _msg_worker(args: tuple[str, int]) -> pl.DataFrame:
    path, rg = args
    tb = pq.ParquetFile(path).read_row_group(rg, columns=["id", "agent_messages"])
    ids = tb.column("id").to_pylist()
    msgs = tb.column("agent_messages").to_pylist()
    out_id, out_refs = [], []
    for i, raw in zip(ids, msgs, strict=True):
        if not raw or not _MSG_PREFILTER.search(raw):
            continue
        refs = text_refs(narrative_text(raw))
        if refs:
            out_id.append(i)
            out_refs.append(refs)
    return pl.DataFrame({"id": out_id, "msg": out_refs},
                        schema={"id": pl.String, "msg": pl.List(pl.String)})


def message_refs(cfg: dict, workers: int, force: bool = False, log=print) -> pl.DataFrame:
    """Refs in the provider responses of all turns (cached)."""
    p = paths(cfg)
    if p["msg"].exists() and not force:
        return pl.read_parquet(p["msg"])
    src = Path(cfg["paths"]["tables"]) / "computer_use_turns_text.parquet"
    n_rg = pq.ParquetFile(src).num_row_groups
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as ex:
        parts = list(ex.map(_msg_worker, [(str(src), rg) for rg in range(n_rg)], chunksize=1))
    df = pl.concat(parts) if parts else pl.DataFrame(schema={"id": pl.String, "msg": pl.List(pl.String)})
    p["dir"].mkdir(parents=True, exist_ok=True)
    df.write_parquet(p["msg"])
    log(f"message refs: {df.height:,} turns with refs from {n_rg} row groups in {time.time() - t0:.0f} s")
    return df


def load_sessions(cfg: dict) -> pl.DataFrame:
    """One row per computer-use session: agent, goal, era, start, turns, last turn and durations.

    `duration_min` is wall time from the session start to its last turn. `active_min` adds only
    the gaps between consecutive turns (and from the start to the first turn) that are at most
    the pause gap G (SPEC 4.2, `time.pause_gap_minutes`), so overnight or paused stretches do not
    count.
    """
    P, T = Path(cfg["paths"]["processed"]), Path(cfg["paths"]["tables"])
    gap_s = 60.0 * float((cfg.get("time") or {}).get("pause_gap_minutes", 30))
    eu = pl.scan_parquet(P / "events_unified.parquet")
    ses = (eu.filter(pl.col("source").cast(pl.String) == "session")
           .select("session_id", pl.col("actor_type").cast(pl.String), "ts_utc", "goal_id", "run_day",
                   pl.col("regime_cu").cast(pl.String), "model_family", "model")
           .collect())
    cus = pl.read_parquet(T / "computer_use_sessions.parquet", columns=["id", "agent_id", "created_at"])
    starts = cus.select(pl.col("id").alias("session_id"), pl.col("created_at").alias("start"))
    turns = (pl.scan_parquet(T / "computer_use_turns.parquet").select("session_id", "created_at")
             .join(starts.lazy(), on="session_id", how="inner")
             .sort("session_id", "created_at")
             .with_columns(pl.col("created_at").shift(1).over("session_id").alias("prev"))
             .with_columns(((pl.col("created_at") - pl.coalesce("prev", "start")).dt.total_seconds()).alias("gap"))
             .group_by("session_id")
             .agg(pl.len().alias("n_turns"), pl.col("created_at").max().alias("last_turn"),
                  (pl.col("gap").filter((pl.col("gap") >= 0) & (pl.col("gap") <= gap_s)).sum() / 60.0)
                  .alias("active_min"))
             .collect())
    s = (cus.rename({"id": "session_id", "created_at": "start"})
         .join(ses, on="session_id", how="left")
         .join(turns, on="session_id", how="left")
         .with_columns(pl.col("n_turns").fill_null(0).cast(pl.Int64),
                       ((pl.col("last_turn") - pl.col("start")).dt.total_seconds() / 60.0).alias("duration_min"))
         .sort("start", "session_id"))
    return s.with_row_index("s").with_columns(pl.col("s").cast(pl.Int64))


GUI_STATS = ("gui_writes", "gui_writes_unattributed", "gui_via_carry", "gui_via_narrative", "gui_shell",
             "gui_search", "gui_input", "gui_nav_extra", "gui_click_nonwrite")


def _agent_worker(args: tuple[str, pl.DataFrame, str]) -> tuple[str, pl.DataFrame, pl.DataFrame, list[str]]:
    agent, df, rules = args
    state = AgentState()
    rows: list[tuple] = []
    gui: list[tuple] = []
    for (sid,), g in df.group_by(["session_id"], maintain_order=True):
        recs = g.to_dicts()
        touches, st = session_touches(recs, state, rules)
        for i, t in touches:
            r = recs[i]
            rows.append((r["id"], sid, r["created_at"], t.ref, t.mode, t.rule, t.container_level, t.via))
        gui.append((sid, *[st[k] for k in GUI_STATS]))
    tdf = pl.DataFrame(rows, schema={"turn_id": pl.String, "session_id": pl.String,
                                     "ts": pl.Datetime("us", "UTC"), "ref": pl.String, "mode": pl.String,
                                     "rule": pl.String, "clevel": pl.Boolean, "via": pl.String}, orient="row")
    gdf = pl.DataFrame(gui, schema={"session_id": pl.String, **{k: pl.Int64 for k in GUI_STATS}}, orient="row")
    return agent, tdf, gdf, sorted(state.repo_roots)


def extract_touches(cfg: dict, workers: int, force: bool = False, log=print,
                    rules: str = MAIN_RULES) -> dict[str, pl.DataFrame]:
    """Raw touches of every turn under a rule version (cached under data/interim/depgraph/)."""
    p = paths(cfg, rules)
    if all(p[k].exists() for k in ("touches", "gui", "roots")) and not force:
        got = {k: pl.read_parquet(p[k]) for k in ("touches", "gui", "roots")}
        if "via" not in got["touches"].columns:          # caches written before rules v2
            got["touches"] = got["touches"].with_columns(pl.lit("").alias("via"))
        for k in GUI_STATS:
            if k not in got["gui"].columns:
                got["gui"] = got["gui"].with_columns(pl.lit(0, dtype=pl.Int64).alias(k))
        return got
    t0 = time.time()
    T, P = Path(cfg["paths"]["tables"]), Path(cfg["paths"]["processed"])
    aa = pl.col("agent_action")
    turns = (pl.scan_parquet(T / "computer_use_turns.parquet")
             .select("id", "session_id", pl.col("action_name").alias("action"), "created_at",
                     *[aa.str.json_path_match(f"$.{v}").alias(k) for k, v in TURN_FIELDS.items()])
             .collect())
    obs = (pl.scan_parquet(P / "events_unified.parquet")
           .filter((pl.col("source").cast(pl.String) == "turn") & (pl.col("refs_obs").list.len() > 0))
           .select(pl.col("event_uid").str.strip_prefix("turn:").alias("id"), pl.col("refs_obs").alias("obs"))
           .collect())
    msg = message_refs(cfg, workers, log=log)
    if rules != "v1":                      # rules v2 read game and terminal words of the provider response
        from avsd.swarmsim.gui_gap import message_flags

        msg = msg.join(message_flags(cfg, workers, log=log), on="id", how="full", coalesce=True)
    ses = pl.read_parquet(T / "computer_use_sessions.parquet", columns=["id", "agent_id", "created_at"]) \
        .rename({"id": "session_id", "created_at": "s_start"})
    turns = (turns.join(obs, on="id", how="left").join(msg, on="id", how="left")
             .join(ses, on="session_id", how="inner")
             .sort("agent_id", "s_start", "session_id", "created_at", "id"))
    log(f"turns loaded: {turns.height:,} in {time.time() - t0:.0f} s")
    jobs = [(a, g.drop("agent_id", "s_start"), rules)
            for (a,), g in turns.group_by(["agent_id"], maintain_order=True)]
    jobs.sort(key=lambda j: -j[1].height)
    del turns
    tparts, gparts, roots = [], [], []
    with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as ex:
        for agent, tdf, gdf, rts in ex.map(_agent_worker, jobs, chunksize=1):
            tparts.append(tdf.with_columns(pl.lit(agent).alias("agent_id")))
            gparts.append(gdf)
            roots += [(agent, r) for r in rts]
    out = {
        "touches": pl.concat(tparts).sort("ts", "turn_id"),
        "gui": pl.concat(gparts),
        "roots": pl.DataFrame(roots, schema={"agent_id": pl.String, "root": pl.String}, orient="row"),
    }
    p["dir"].mkdir(parents=True, exist_ok=True)
    for k, df in out.items():
        df.write_parquet(p[k])
    log(f"touches ({rules}): {out['touches'].height:,} rows in {time.time() - t0:.0f} s")
    return out


def default_workers() -> int:
    return int(os.environ.get("SLURM_CPUS_PER_TASK", "0")) or (os.cpu_count() or 1)
