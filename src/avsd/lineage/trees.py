"""Module B2: transmission trees between agents (SPEC 6.4), `avsd lineage trees`.

Inputs: the information units and occurrences of `avsd.lineage.b2_units`
(data/interim/b2/), B1's memory presence under the chosen rule set (`rules`,
default v2, B1's main rule set chosen on the owner's labels on 2026-10-03;
the rule set is a parameter and every run records it), the room reconstruction
(`agent_room_intervals`, `roster_daily`) and explicit references
(`avsd.lineage.b2_refs`).

Steps (`run_trees`):

1. Candidate parents and exposure (`trees_core`, SPEC 6.4.2).
2. Time term (`trees_kernel`): the empirical serial-interval KDE per kernel key
   from edges with a single candidate parent (SPEC 11 fallback while module A
   is not validated). If module A has written
   outputs/tables/hawkes_kernels.parquet, `HawkesKernel` replaces the term for
   same-run-day chat edges of fitted rooms (`--hawkes auto`, the default).
3. gamma (SPEC 6.4.3): grid search on the tier-1 name-reference labels (the
   labels whose text the parent does not share by construction), maximising the
   log posterior of the labelled parent (provisional). `--gamma composite` (the
   final choice) picks the time term and gamma by parent accuracy on the
   owner's labels where they exist and Claude's blind labels elsewhere, the
   mean log posterior breaking ties; `--gamma hand` does the same on the
   owner's labels alone (at least 20). The ablation (time only, content only,
   both, baselines, and the KDE alone when the module A hook is on) is
   cross-fitted over two folds of child messages.
4. MAP forest and `posterior_samples` (200) independent parent draws (SPEC
   6.4.4); per-generation channel composition, offspring (observed and expected
   under the finite population), content change rate, independent share,
   attractor test.
5. The agent-level view (`trees_stats.agent_view`): a generation is one hop
   between actors (all humans count as one actor); edges between occurrences of
   the same actor are restatements, reported as restatement depth. H1 by kernel
   key on the edges between agents, on the determined paths (every edge on the
   path has a single candidate; the headline test), the MAP forest and the
   posterior draws, and H3 (`trees_stats`, SPEC 6.2); H3 compares the per-edge
   value-change rate of agent-to-agent retelling with B1's per-consolidation
   rate for quantity facts (outputs/tables/memory_by_anchor{_v2,_v3}.csv).
6. Validation (SPEC 6.4.5): explicit-reference accuracy and the ablation;
   synthetic trees with the real agent counts, event rates, channel mix and
   kernels (`trees_synth`), including the type I error of H1 under the null.
7. Sensitivity runs: time term without the hook, gamma = 1, content between
   agents only, env rule, exposure rules, agent-level trees, rule sets v1/v2/v3.
8. Outputs: outputs/tables/trees_*.csv, outputs/figures/F3_*, F4_*,
   outputs/qa/lineage_trees.md (aggregates only), data/labels/parents.csv
   (SPEC appendix C, explicit references; private).

Privacy (SPEC 0.2): outputs hold counts, rates and keyed unit ids only; no
values, text, 4-grams or human names. Humans are the category `human`. URL units
show a registrable domain only when at least 3 units share it.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import multiprocessing as mp
import os
import time
import zlib
from pathlib import Path

import numpy as np
import polars as pl

from avsd.config import load_config
from avsd.lineage import trees_stats as ts
from avsd.lineage.anchors import keyed_hash, load_salt
from avsd.lineage.trees_core import (
    CHAT, ENV, I64_MAX, L_B_DEFAULT, MEMORY, SEARCH, SRC_NAMES, Cands, Occ, Ragged, finish_cands, forest,
    map_choice, posterior, sample_choice, single_candidate_edges, unit_candidates,
)
from avsd.lineage.trees_kernel import KEY_CODE, KEYS, EmpiricalKernel, HawkesKernel

RULES = ("v1", "v2", "v3")
GAMMA_GRID = (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0)
TK_MARGIN = 30.0  # run days between a tree's root and the end of the data for T_k
ROOM_TOL_S = 2.0
B2_DIR = "b2"


# --- clock, rooms ---------------------------------------------------------------------------------------

class Clock:
    """Run-day clock: run day + fraction of that day's active time (SPEC 6.1, L_B in run days)."""

    def __init__(self, processed: Path):
        d = (pl.scan_parquet(processed / "events_unified.parquet").filter(pl.col("run_day").is_not_null())
             .group_by("run_day").agg(pl.col("t_active").min().alias("lo"), pl.col("t_active").max().alias("hi"))
             .sort("run_day").collect())
        self.rd = d["run_day"].to_numpy().astype(float)
        self.lo = d["lo"].to_numpy()
        self.span = np.maximum(d["hi"].to_numpy() - self.lo, 1.0)
        self.end = float(self.rd[-1] + 1.0)

    def pos(self, t: np.ndarray) -> np.ndarray:
        t = np.asarray(t, dtype=float)
        k = np.clip(np.searchsorted(self.lo, t, side="right") - 1, 0, len(self.lo) - 1)
        return self.rd[k] + np.clip((t - self.lo[k]) / self.span[k], 0.0, 1.0)


def chat_visibility(processed: Path, docs: pl.DataFrame, agent_ids: list[str]) -> dict[str, int]:
    """Agents that see each chat message (main rule): in the message's room when it was posted
    (+/- ROOM_TOL_S around room moves) and active that run day. Returns doc uid -> bit mask."""
    from avsd.events.unified import room_at

    iv = pl.read_parquet(processed / "agent_room_intervals.parquet")
    roster = (pl.read_parquet(processed / "roster_daily.parquet", columns=["run_day", "agent_id", "active"])
              .filter(pl.col("active")).select("run_day", "agent_id"))
    ag = pl.DataFrame({"agent_id": agent_ids, "aidx": np.arange(len(agent_ids), dtype=np.int64)})
    q = docs.select("doc_uid", "ts_utc", "room_id", "run_day").join(ag, how="cross")
    seen = pl.Series([False] * q.height)
    for off in (-ROOM_TOL_S, 0.0, ROOM_TOL_S):
        rows = q.select(pl.col("agent_id").alias("actor_id"),
                        (pl.col("ts_utc") + pl.duration(microseconds=int(off * 1e6))).alias("ts_utc"))
        r = room_at(iv, rows)
        seen = seen | (r == q["room_id"]).fill_null(False)
    q = q.with_columns(seen.alias("in_room")).join(roster.with_columns(pl.lit(True).alias("active")),
                                                    on=["run_day", "agent_id"], how="left")
    q = q.filter(pl.col("in_room") & pl.col("active").fill_null(False)).unique(["doc_uid", "aidx"])
    m = q.group_by("doc_uid").agg(pl.lit(2.0).pow(pl.col("aidx")).cast(pl.UInt64).sum().alias("mask"))
    return dict(zip(m["doc_uid"].to_list(), m["mask"].to_list()))


def room_spells(processed: Path, agent_ids: list[str], room_code: dict[str, int]) -> dict:
    """agent index -> room code -> (starts, ends) in microseconds (exposure rule `ever`)."""
    iv = pl.read_parquet(processed / "agent_room_intervals.parquet")
    a_index = {a: i for i, a in enumerate(agent_ids)}
    out: dict = {}
    lo, hi = np.iinfo(np.int64).min, I64_MAX
    for a, room, s, e in iv.select("agent_id", "room_id", pl.col("start").dt.epoch("us"),
                                   pl.col("end").dt.epoch("us")).sort("agent_id", "start").iter_rows():
        ai, rc = a_index.get(a), room_code.get(room)
        if ai is None or rc is None:
            continue
        out.setdefault(ai, {}).setdefault(rc, ([], []))
        out[ai][rc][0].append(lo if s is None else s)
        out[ai][rc][1].append(hi if e is None else e)
    return {a: {r: (np.array(s, dtype=np.int64), np.array(e, dtype=np.int64)) for r, (s, e) in d.items()}
            for a, d in out.items()}


# --- inputs --------------------------------------------------------------------------------------------

def _ragged(s: pl.Series) -> Ragged:
    lens = s.list.len().fill_null(0).to_numpy().astype(np.int64)
    vals = s.explode().drop_nulls().to_numpy().astype(np.int64) if lens.sum() else np.zeros(0, np.int64)
    return Ragged(vals, np.concatenate([[0], np.cumsum(lens)]))


def load_inputs(cfg: dict, rules: str = "v2", tag: str = "", exposure: str = "main", log=print) -> dict:
    """Occurrence arrays (`Occ`) and the frames the outputs need."""
    if rules not in RULES:
        raise ValueError(f"rules must be one of {RULES}")
    interim, processed = Path(cfg["paths"]["interim"]), Path(cfg["paths"]["processed"])
    d = interim / (B2_DIR + (f"_{tag}" if tag else ""))
    t0 = time.perf_counter()
    units = pl.read_parquet(d / "units.parquet").sort("uidx")
    occ_df = pl.read_parquet(d / "occurrences.parquet").sort("uidx", "ts_utc", "occ_uid")
    agents = pl.read_parquet(processed / "agents.parquet")
    agent_ids = sorted(agents["agent_id"].to_list())
    a_index = {a: i for i, a in enumerate(agent_ids)}
    rooms = sorted(set(occ_df["room_id"].drop_nulls().to_list())
                   | set(pl.read_parquet(processed / "agent_room_intervals.parquet")["room_id"].drop_nulls().to_list()))
    room_code = {r: i for i, r in enumerate(rooms)}
    clock = Clock(processed)
    n = occ_df.height
    # Chat timing for the module A hook.
    chat_t = (pl.scan_parquet(processed / "events_unified.parquet")
              .filter(pl.col("source").cast(pl.String) == "chat")
              .select(pl.col("event_uid").alias("doc_uid"), "realization_id", "t_in_day").collect())
    occ_df = occ_df.join(chat_t, on="doc_uid", how="left", maintain_order="left")
    # Memory presence under the rule set.
    pres = pl.read_parquet(d / "mem_presence.parquet")
    pres = pres.select(pl.col("agent_id").alias("actor_id"), "unit_id", pl.col(f"end_{rules}").alias("mem_end"),
                       *[c for c in ("restore_start", "restore_end") if c in pres.columns])
    occ_df = occ_df.join(pres, on=["actor_id", "unit_id"], how="left", maintain_order="left")
    occ_df = occ_df.with_columns(
        pl.when(pl.col("src") == "memory").then(pl.col("mem_end")).otherwise(None).alias("mem_end"))
    # Visibility masks of chat occurrences.
    chat_docs = (occ_df.filter(pl.col("src") == "chat").select("doc_uid", "ts_utc", "room_id", "run_day")
                 .unique("doc_uid"))
    vis = chat_visibility(processed, chat_docs, agent_ids)
    log(f"inputs: {units.height:,} units, {n:,} occurrences, visibility for {len(vis):,} chat messages "
        f"({time.perf_counter() - t0:.0f} s)")
    src = occ_df["src"].replace_strict({"chat": CHAT, "memory": MEMORY, "search": SEARCH}).to_numpy().astype(np.int8)
    actor = np.array([a_index.get(a, -1) for a in occ_df["actor_id"].to_list()], dtype=np.int16)
    ts_us = occ_df["ts_utc"].dt.epoch("us").to_numpy()
    t_act = occ_df["t_active"].to_numpy().astype(float)
    if np.isnan(t_act).any():
        raise ValueError(f"{int(np.isnan(t_act).sum())} occurrences lack t_active")
    uidx = occ_df["uidx"].to_numpy()
    start = np.searchsorted(uidx, np.arange(units.height + 1)).astype(np.int64)
    mem_end = occ_df["mem_end"].dt.epoch("us").fill_null(I64_MAX).to_numpy().astype(np.int64)
    mem_rs = {}
    if "restore_start" in occ_df.columns:
        rs = occ_df.select(pl.col("restore_start").list.eval(pl.element().dt.epoch("us")),
                           pl.col("restore_end").list.eval(pl.element().dt.epoch("us").fill_null(I64_MAX)))
        for i in np.flatnonzero((src == MEMORY) & rs["restore_start"].list.len().fill_null(0).to_numpy().astype(bool)):
            s_, e_ = rs["restore_start"][int(i)], rs["restore_end"][int(i)]
            mem_rs[int(i)] = (np.array(s_.to_list(), dtype=np.int64), np.array(e_.to_list(), dtype=np.int64))
    doc_uids = occ_df["doc_uid"].to_list()
    vis_arr = np.array([vis.get(u, 0) if s_ == CHAT else 0 for u, s_ in zip(doc_uids, src.tolist())],
                       dtype=np.uint64)
    pt_date = occ_df["ts_utc"].dt.convert_time_zone("America/Los_Angeles").dt.date().to_numpy().astype("datetime64[D]")
    # Env hits per (unit, agent).
    env_df = pl.read_parquet(d / "env_hits.parquet")
    ucol = "uidx"
    env_df = (env_df.with_columns(pl.col("agent_id").replace_strict(a_index, default=-1, return_dtype=pl.Int64)
                                  .alias("aidx"))
              .filter(pl.col("aidx") >= 0).sort(ucol, "aidx", "ts_utc"))
    eu, ea = env_df[ucol].to_numpy().astype(np.int64), env_df["aidx"].to_numpy()
    ets, et = env_df["ts_utc"].dt.epoch("us").to_numpy(), env_df["t_active"].to_numpy().astype(float)
    epos = clock.pos(et)
    env: dict = {}
    if len(eu):
        code = eu * 64 + ea
        brk = np.flatnonzero(np.diff(code)) + 1
        st = np.concatenate([[0], brk, [len(code)]])
        for a, b in zip(st[:-1], st[1:]):
            env[(int(eu[a]), int(ea[a]))] = (ets[a:b], et[a:b], epos[a:b])
    occ = Occ(
        start=start, ts=ts_us.astype(np.int64), t=t_act, pos=clock.pos(t_act), src=src, actor=actor, vis=vis_arr,
        room=np.array([room_code.get(r, -1) if r is not None else -1 for r in occ_df["room_id"].to_list()],
                      dtype=np.int32),
        vday=occ_df["village_day"].fill_null(-10**6).to_numpy().astype(np.int32),
        s0=occ_df["search_start_day"].fill_null(-1).to_numpy().astype(np.int32),
        s1=occ_df["search_end_day"].fill_null(-2).to_numpy().astype(np.int32),
        rz=occ_df["realization_id"].fill_null(-1).to_numpy().astype(np.int32),
        tin=occ_df["t_in_day"].fill_null(np.nan).to_numpy().astype(float),
        date=pt_date, mem_end=mem_end, mem_rs=mem_rs,
        qv_key=_ragged(occ_df["qv_key"]), qv_val=_ragged(occ_df["qv_val"]), grams=_ragged(occ_df["grams"]),
        env=env,
    )
    occ.win = _ragged(occ_df["win"])
    occ.unit = uidx.astype(np.int64)
    occ.room_ids = np.array(rooms, dtype=object)
    if exposure == "ever":
        occ.room_spells = room_spells(processed, agent_ids, room_code)
    roster = pl.read_parquet(processed / "roster_daily.parquet", columns=["run_day", "agent_id", "active"])
    log(f"inputs ready in {time.perf_counter() - t0:.0f} s; env hit groups {len(env):,}")
    return {"occ": occ, "units": units, "occ_df": occ_df.select("occ_uid", "doc_uid", "unit_id", "uidx", "src",
                                                                "actor_id", "actor_type", "ts_utc"),
            "agent_ids": agent_ids, "a_index": a_index, "clock": clock, "rooms": rooms, "room_code": room_code,
            "roster": roster, "dir": d, "rules": rules, "exposure": exposure}


# --- candidates in parallel -------------------------------------------------------------------------------

_G: dict = {}


def single_thread() -> None:
    """One BLAS/OpenMP thread in a worker process (numpy is loaded before the env variables apply)."""
    try:
        from threadpoolctl import threadpool_limits

        threadpool_limits(limits=1)
    except ImportError:  # pragma: no cover
        pass


def _cand_chunk(args) -> list[dict]:
    single_thread()
    units, L, env_rule, exposure = args
    occ = _G["occ"]
    return [unit_candidates(occ, int(u), L, env_rule, exposure) for u in units]


def build_cands(occ: Occ, n_workers: int, L: float, env_rule: str, exposure: str, log=print) -> Cands:
    t0 = time.perf_counter()
    units = np.arange(occ.n_units)
    sizes = np.diff(occ.start)
    order = units[np.argsort(-sizes, kind="stable")]
    chunks = [order[k::max(1, n_workers * 6)] for k in range(max(1, n_workers * 6))]
    _G["occ"] = occ
    if n_workers > 1:
        with mp.get_context("fork").Pool(n_workers) as pool:
            parts = [p for ch in pool.imap_unordered(_cand_chunk, [(c, L, env_rule, exposure) for c in chunks])
                     for p in ch]
    else:
        parts = _cand_chunk((units, L, env_rule, exposure))
    c = finish_cands(occ, parts)
    log(f"candidates: {c.n:,} rows for {len(np.unique(c.child)):,} children ({env_rule}, {exposure}) in "
        f"{time.perf_counter() - t0:.0f} s")
    return c


# --- labels --------------------------------------------------------------------------------------------------

def label_cases(inp: dict, c: Cands, refs: pl.DataFrame) -> dict[str, np.ndarray]:
    """Explicit-reference cases: (child occurrence, row of the labelled parent) where both messages are
    occurrences of the same unit and the labelled message is a candidate parent."""
    od = inp["occ_df"]
    chat = od.with_row_index("gi").filter(pl.col("src") == "chat").select("gi", "doc_uid", "uidx")
    by_doc: dict[str, list[tuple[int, int]]] = {}
    at: dict[tuple[str, int], int] = {}
    for gi, doc, u in chat.iter_rows():
        by_doc.setdefault(doc, []).append((int(u), int(gi)))
        at[(doc, int(u))] = int(gi)
    kids, starts = c.offsets()
    row_of_child = {int(k): (int(a), int(b)) for k, a, b in zip(kids, starts[:-1], starts[1:])}
    out = {k: [] for k in ("child", "row", "a", "b", "kind", "tier", "cluster")}
    for cu, pu, kind, tier in refs.select("child_uid", "parent_uid", "kind", "tier").iter_rows():
        for u, i in by_doc.get(cu, ()):
            j = at.get((pu, u))
            if j is None or i not in row_of_child:
                continue
            a, b = row_of_child[i]
            hit = np.flatnonzero(c.parent[a:b] == j)
            if not len(hit):
                continue
            out["child"].append(i)
            out["row"].append(a + int(hit[0]))
            out["a"].append(a)
            out["b"].append(b)
            out["kind"].append(kind)
            out["tier"].append(int(tier))
            out["cluster"].append(zlib.crc32(cu.encode()) & 0x7FFFFFFF)
    res = {k: np.array(v) for k, v in out.items()}
    res["n_children_msgs"] = len(set(res["cluster"].tolist())) if len(res["cluster"]) else 0
    return res


HAND_MIN_CASES = 20


CASE_KEYS = ("child", "row", "a", "b", "kind", "tier", "cluster")


def sheet_label_cases(inp: dict, c: Cands, path: Path, kind: str = "hand",
                      requests: Path | None = None) -> dict[str, np.ndarray]:
    """Cases from the human_parent column of a copy of data/labels/parents_review.csv: (child occurrence, row
    of the chosen parent: a candidate number or env). A uid in the sheet names a message or memory row, which
    can carry several units, so the item's occurrence comes from the sheet's request file (`requests`, with
    the occurrence index of each item; without it the uid must be unique) and a candidate is the occurrence
    of its uid in the same unit. Blank rows and rows marked none give no case; `labelled_clusters` keeps every
    labelled row (none included), so that a composite set can tell which rows a labeller answered."""
    import csv
    import json

    od = inp["occ_df"]
    uid, uidx = od["occ_uid"].to_list(), od["uidx"].to_list() if "uidx" in od.columns else None
    by_pair = {(u, x): i for i, (u, x) in enumerate(zip(uid, uidx))} if uidx is not None else {}
    by_uid = {u: i for i, u in enumerate(uid)}
    item_gi = {}
    if requests is not None and requests.exists():
        with open(requests, encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                item_gi[str(r["item"])] = (int(r["gi"]), r["child_uid"])
    kids, starts = c.offsets()
    row_of_child = {int(k): (int(a), int(b)) for k, a, b in zip(kids, starts[:-1], starts[1:])}
    out = {k: [] for k in CASE_KEYS}
    labelled, missing, answered = 0, 0, []
    with open(path, encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            lab = (r.get("human_parent") or "").strip().lower()
            if not lab:
                continue
            cu = (r.get("child_uid") or "").strip()
            answered.append(zlib.crc32(cu.encode()) & 0x7FFFFFFF)
            if lab == "none":
                continue
            labelled += 1
            hit_item = item_gi.get(str(r.get("item", "")).strip())
            if hit_item is not None and hit_item[1] == cu and uid[hit_item[0]] == cu:
                i = hit_item[0]
            elif not item_gi:
                i = by_uid.get(cu)
            else:
                i = None
            target = None
            if i is not None and lab == "env":
                target = ENV
            elif i is not None and lab.isdigit():
                pu = (r.get(f"cand_{int(lab)}_uid") or "").strip()
                target = ENV if pu == "env" else (by_pair.get((pu, uidx[i])) if uidx is not None else by_uid.get(pu))
            if i is None or target is None or i not in row_of_child:
                missing += 1
                continue
            a, b = row_of_child[i]
            hit = np.flatnonzero(c.parent[a:b] == target)
            if not len(hit):
                missing += 1
                continue
            out["child"].append(i)
            out["row"].append(a + int(hit[0]))
            out["a"].append(a)
            out["b"].append(b)
            out["kind"].append(kind)
            out["tier"].append(1)
            out["cluster"].append(zlib.crc32(cu.encode()) & 0x7FFFFFFF)
    res = {k: np.array(v, dtype=object if k == "kind" else np.int64) for k, v in out.items()}
    res["n_labelled"], res["n_unmatched"] = labelled, missing
    res["labelled_clusters"] = np.array(answered, dtype=np.int64)
    return res


def hand_label_cases(inp: dict, c: Cands, path: Path, requests: Path | None = None) -> dict[str, np.ndarray]:
    """The owner's labels in data/labels/parents_review.csv (kind "hand")."""
    return sheet_label_cases(inp, c, path, "hand", requests)


def label_requests_path(cfg: dict, tag: str = "") -> Path:
    """requests.jsonl of the parent labelling sheet (avsd.lineage.prelabel_parents prepare)."""
    from avsd.config import REPO_ROOT

    base = cfg.get("llm", {}).get("cache_dir")
    root = (REPO_ROOT / base) if base else Path(cfg["paths"]["interim"]) / "llm_cache"
    return Path(root).resolve() / ("parent_prelabel" + (f"_{tag}" if tag else "")) / "requests.jsonl"


def label_agreement_counts(owner_path: Path, other_path: Path) -> dict | None:
    """Agreement between the owner's and Claude's labels on the rows both answered (ENV candidates as env)."""
    import csv

    from avsd.lineage.prelabel_parents import label_agreement

    if not (owner_path.exists() and other_path.exists()):
        return None
    with open(owner_path, encoding="utf-8-sig") as f1, open(other_path, encoding="utf-8-sig") as f2:
        agree, both = label_agreement(list(csv.DictReader(f1)), list(csv.DictReader(f2)))
    return {"agree": agree, "both": both}


def composite_label_cases(owner: dict | None, claude: dict | None) -> dict | None:
    """The owner's label where the owner answered the row (none included), Claude's elsewhere (kind
    "composite")."""
    parts = [p for p in (owner, claude) if p is not None]
    if not parts:
        return None
    done = set(owner["labelled_clusters"].tolist()) if owner is not None else set()
    sel = []
    if owner is not None:
        sel.append({k: np.asarray(owner[k]) for k in CASE_KEYS})
    if claude is not None:
        keep = np.array([cl not in done for cl in np.asarray(claude["cluster"]).tolist()], dtype=bool)
        sel.append({k: np.asarray(claude[k])[keep] if len(claude[k]) else np.asarray(claude[k]) for k in CASE_KEYS})
    out = {k: np.concatenate([p[k] for p in sel]) for k in CASE_KEYS}
    out["kind"] = np.array(["composite"] * len(out["child"]), dtype=object)
    return out


def select_by_labels(c: Cands, cases: dict, sets: dict[str, np.ndarray], terms: list[tuple[str, np.ndarray]]
                     ) -> tuple[dict[str, tuple[str, float]], list[dict]]:
    """For each label set: the time term and gamma (GAMMA_GRID) with the highest parent accuracy (ties between
    candidates split evenly), the mean log posterior breaking ties. `terms` holds (name, K). Returns the best
    (term, gamma) per set and one row per term, gamma and set."""
    S = c.S.astype(float)
    rows, best = [], {}
    for name, K in terms:
        lk = np.log(np.maximum(K, 1e-300))
        for g in GAMMA_GRID:
            for lab, m in sets.items():
                if not m.any():
                    continue
                sc = score_cases(cases, m, lk + g * S)
                key = (float(sc["acc"].mean()), float(sc["logp"].mean()))
                rows.append({"time_term": name, "gamma": float(g), "label_set": lab, "n_cases": int(m.sum()),
                             "accuracy": key[0], "mean_logp": key[1]})
                if lab not in best or key > best[lab][0]:
                    best[lab] = (key, name, float(g))
    for r in rows:
        b = best.get(r["label_set"])
        r["best_for_set"] = bool(b and b[1] == r["time_term"] and b[2] == r["gamma"])
    return {k: (v[1], v[2]) for k, v in best.items()}, rows


def concat_cases(a: dict, b: dict) -> dict:
    out = {k: np.concatenate([np.asarray(a[k], dtype=object if k == "kind" else None),
                              np.asarray(b[k], dtype=object if k == "kind" else None)]) if len(a[k])
           else np.asarray(b[k]) for k in CASE_KEYS}
    out["n_children_msgs"] = len(set(out["cluster"].tolist()))
    return out


def _case_rows(cases: dict, sel: np.ndarray):
    a, b, r = cases["a"][sel], cases["b"][sel], cases["row"][sel]
    lens = b - a
    rows = np.concatenate([np.arange(x, y) for x, y in zip(a, b)]) if len(a) else np.zeros(0, np.int64)
    case_id = np.repeat(np.arange(len(a)), lens)
    starts = np.concatenate([[0], np.cumsum(lens)])
    true_pos = starts[:-1] + (r - a)
    return rows, case_id, starts, true_pos


def score_cases(cases: dict, sel: np.ndarray, logw_rows: np.ndarray) -> dict[str, np.ndarray]:
    """Per case: log P(labelled parent) and expected top-1 accuracy (ties split evenly)."""
    rows, case_id, starts, true_pos = _case_rows(cases, sel)
    if not len(rows):
        return {"logp": np.zeros(0), "acc": np.zeros(0), "n_cand": np.zeros(0)}
    lw = logw_rows[rows]
    mx = np.maximum.reduceat(lw, starts[:-1])
    z = np.log(np.add.reduceat(np.exp(lw - np.repeat(mx, np.diff(starts))), starts[:-1])) + mx
    logp = lw[true_pos] - z
    is_max = lw >= np.repeat(mx, np.diff(starts)) - 1e-9
    n_max = np.add.reduceat(is_max.astype(float), starts[:-1])
    acc = np.where(is_max[true_pos], 1.0 / n_max, 0.0)
    return {"logp": logp, "acc": acc, "n_cand": np.diff(starts)}


def cluster_ci(values: np.ndarray, clusters: np.ndarray, reps: int, rng: np.random.Generator) -> tuple[float, float]:
    if not len(values):
        return (np.nan, np.nan)
    boot = ts.ClusterBoot(clusters, reps, rng)
    return ts.ci(ts.boot_ratio(boot, values.astype(float), np.ones(len(values)), boot.inv))


def gamma_and_ablation(c: Cands, K: np.ndarray, cases: dict, rng: np.random.Generator, boot_reps: int,
                       default_gamma: float, occ: Occ, K_alt: np.ndarray | None = None,
                       rng_alt: np.random.Generator | None = None, gamma_set: str = "name_tier1",
                       fixed_gamma: float | None = None, alt_suffix: str = "_kde_only"
                       ) -> tuple[float, list[dict], list[dict], float | None]:
    """Grid search of gamma on tier-1 name labels, and the ablation on every label set (cross-fitted).
    K_alt (the KDE alone when the module A hook is on) adds grid columns and the methods "time_kde_only",
    "time+content_kde_only" and "time+content_other_agents_kde_only", with gamma chosen the same way on
    K_alt; their CIs use rng_alt, so the other rows do not change. gamma is chosen on `gamma_set`
    ("name_tier1", "hand" for the owner's labels or "composite") unless `fixed_gamma` is given. `alt_suffix`
    names the K_alt methods ("_kde_only", or "_module_a" when the KDE is the main time term). Returns gamma,
    the grid, the ablation rows and the gamma that K_alt would select (None without K_alt)."""
    logK = np.log(np.maximum(K, 1e-300))
    logK_alt = np.log(np.maximum(K_alt, 1e-300)) if K_alt is not None else None
    S = c.S.astype(float)
    grid_rows = []
    sel1 = (cases["kind"] == "name") & (cases["tier"] == 1) if len(cases["child"]) else np.zeros(0, bool)
    sel2 = (cases["kind"] == "name") & (cases["tier"] == 2) if len(cases["child"]) else sel1
    selh = (cases["kind"] == "hand") if len(cases["child"]) else sel1
    selc = (cases["kind"] == "claude") if len(cases["child"]) else sel1
    selx = (cases["kind"] == "composite") if len(cases["child"]) else sel1
    selg = {"hand": selh, "composite": selx}.get(gamma_set, sel1)
    fold = (cases["cluster"] % 2) if len(cases["child"]) else np.zeros(0, int)

    def best_gamma(mask, lk) -> float:
        if fixed_gamma is not None:
            return float(fixed_gamma)
        if not mask.any():
            return default_gamma
        lls = [score_cases(cases, mask, lk + g * S)["logp"].sum() for g in GAMMA_GRID]
        return float(GAMMA_GRID[int(np.argmax(lls))])

    terms = (("", logK),) + (((alt_suffix, logK_alt),) if logK_alt is not None else ())
    extra = tuple((n_, m_) for n_, m_ in (("hand", selh), ("claude", selc), ("composite", selx)) if m_.any())
    for g in GAMMA_GRID:
        r = {"gamma": g}
        for suf, lk in terms:
            for name, m in (("name_tier1", sel1), ("name_tier2", sel2)) + extra:
                sc = score_cases(cases, m, lk + g * S)
                if not suf:
                    r[f"{name}_n"] = int(m.sum())
                r[f"{name}_mean_logp{suf}"] = float(sc["logp"].mean()) if len(sc["logp"]) else np.nan
                r[f"{name}_accuracy{suf}"] = float(sc["acc"].mean()) if len(sc["acc"]) else np.nan
        grid_rows.append(r)
    gam = {suf: best_gamma(selg, lk) for suf, lk in terms}
    gam_fold = {suf: {f: best_gamma(selg & (fold != f), lk) for f in (0, 1)} for suf, lk in terms}
    gamma = gam[""]
    # Baselines need the parent time and speaker.
    par = np.where(c.parent >= 0, c.parent, c.child)
    t_par = np.where(c.parent >= 0, occ.t[par], -np.inf)
    other_chat = (c.parent >= 0) & (occ.src[par] == CHAT) & (occ.actor[par] != occ.actor[c.child])
    S_cross = np.where((c.parent >= 0) & (occ.actor[par] == occ.actor[c.child]), 0.0, S)
    abl = []
    sets = (("name_tier1", sel1),)
    if len(cases["child"]):
        sets += (("name_tier2", sel2), ("quote_tier1", (cases["kind"] == "quote") & (cases["tier"] == 1)),
                 ("hand", selh), ("claude", selc), ("composite", selx))
    methods = ("time", "content", "time+content", "time+content_other_agents", "uniform", "latest",
               "latest_other_agent_message")
    if logK_alt is not None:
        methods += tuple(m_ + alt_suffix for m_ in ("time", "time+content", "time+content_other_agents"))
    for name, m in sets:
        if not m.any():
            continue
        for method in methods:
            suf = alt_suffix if method.endswith(alt_suffix) else ""
            base = method.removesuffix(alt_suffix) if suf else method
            lk = logK_alt if suf else logK
            accs, lps = np.zeros(int(m.sum())), np.zeros(int(m.sum()))
            idx = np.flatnonzero(m)
            for f in (0, 1):
                fm = fold[idx] == f
                if not fm.any():
                    continue
                gsel = np.zeros(len(m), bool)
                gsel[idx[fm]] = True
                gf = gam_fold[suf][f] if name == gamma_set and fixed_gamma is None else gam[suf]
                gc = gf if gf > 0 else default_gamma
                if base == "time":
                    lw = lk
                elif base == "content":
                    lw = gc * S
                elif base == "time+content":
                    lw = lk + gf * S
                elif base == "time+content_other_agents":
                    lw = lk + gc * S_cross
                elif base == "uniform":
                    lw = np.zeros(c.n)
                elif base == "latest":
                    lw = np.where(np.isfinite(t_par), t_par, -1e18) * 1e-3
                else:
                    lw = np.where(other_chat, t_par * 1e-3, -1e18)
                sc = score_cases(cases, gsel, lw)
                accs[fm] = sc["acc"]
                lps[fm] = sc["logp"]
            row = {"label_set": name, "method": method, "n_cases": int(m.sum()),
                   "n_child_messages": int(len(np.unique(cases["cluster"][m]))),
                   "accuracy": float(accs.mean()), "mean_logp": float(lps.mean()) if base not in (
                       "latest", "latest_other_agent_message") else np.nan,
                   "mean_candidates": float(np.mean(cases["b"][m] - cases["a"][m]))}
            r_ci = rng_alt if (suf and rng_alt is not None) else rng
            row["accuracy_lo"], row["accuracy_hi"] = cluster_ci(accs, cases["cluster"][m], boot_reps, r_ci)
            abl.append(row)
    return gamma, grid_rows, abl, gam.get(alt_suffix)


# --- forests and their statistics ------------------------------------------------------------------------------

def make_forest(c: Cands, chosen: np.ndarray) -> ts.Forest:
    p, g, r = forest(c, chosen)
    return ts.Forest(chosen, p, g, r)


def susceptible_share(occ: Occ, roster: pl.DataFrame, a_index: dict, run_day_of: np.ndarray) -> np.ndarray:
    """Per occurrence: share of the agents active that run day that had no occurrence of the unit yet."""
    act = roster.filter(pl.col("active"))
    masks: dict[int, int] = {}
    for rd, a in act.select("run_day", "agent_id").iter_rows():
        if a in a_index:
            masks[int(rd)] = masks.get(int(rd), 0) | (1 << a_index[a])
    out = np.full(occ.n, np.nan)
    for u in range(occ.n_units):
        lo, hi = int(occ.start[u]), int(occ.start[u + 1])
        seen = 0
        for i in range(lo, hi):
            a = int(occ.actor[i])
            if a >= 0:
                seen |= 1 << a
            m = masks.get(int(run_day_of[i]), 0)
            na = bin(m).count("1")
            if na:
                out[i] = bin(m & ~seen).count("1") / na
    return out


def forest_stats(inp: dict, c: Cands, post: np.ndarray, chosen: np.ndarray, cfg_l: dict, rng, boot_reps: int,
                 perms: int, full: bool = True) -> dict:
    """Every SPEC 6.4.4 / 6.2 statistic of one forest in the agent-level view (`ts.agent_view`): one node per
    actor and unit (its first occurrence, the acquisition; all humans count as one actor), a generation is one
    transmission to a new actor, and later occurrences of an actor are re-mentions that keep its generation
    (reported as restatement depth). H1, T_k, the generation table and the attractor test use agent-level
    generations; H3 uses the MAP edges between agents. `full=False` gives the light set used for posterior
    draws and sensitivity runs."""
    occ: Occ = inp["occ"]
    clock: Clock = inp["clock"]
    L, min_e = float(cfg_l["L_B"]), int(cfg_l["min_edges"])
    f = make_forest(c, chosen)
    e_all = ts.edges(c, f)
    ok_all = ts.forward_mask(e_all, occ.pos, clock.end, L)
    av = ts.agent_view(f, occ.actor, occ.unit)
    e, sel = ts.agent_edges(e_all, av)
    ok = ok_all[sel]
    entries = av.acq
    fv = ts.Forest(f.chosen, f.parent, av.gen, av.root)
    out: dict = {"n_occ": occ.n, "n_acquisitions": int(av.acq.sum()),
                 "n_roots": int((av.acq & (f.parent == -1)).sum()), "n_env": int((av.acq & (f.parent == ENV)).sum()),
                 "n_env_all": int((f.parent == ENV).sum()),
                 "n_edges": len(e.child), "n_edges_all": len(e_all.child), "n_edges_forward": int(ok.sum()),
                 "max_gen": int(av.gen.max()) if occ.n else 0,
                 "max_gen_occurrence": int(f.gen.max()) if occ.n else 0,
                 "max_depth": int(np.bincount(av.owner[~av.acq], minlength=occ.n).max()) if occ.n else 0}
    out["gen_counts"] = np.bincount(av.gen[entries], minlength=1)
    out["h1_ad"] = ts.h1_ad_tests(e, ok, min_e, perms, rng)
    det = ts.determined_agent(c, f, av)
    out["det_edges"] = det[e.child]
    out["n_determined_edges"] = int((ok & det[e.child]).sum())
    out["h1_ad_det"] = ts.h1_ad_tests(e, ok & det[e.child], min_e, perms, rng)
    out["tk_det"] = ts.tk_analysis(occ.t, occ.pos, av.gen, av.root, clock.end, TK_MARGIN, min_e,
                                   boot_reps if full else 0, rng, node_mask=av.acq & det)
    out["tk"] = ts.tk_analysis(occ.t, occ.pos, av.gen, av.root, clock.end, TK_MARGIN, min_e,
                               boot_reps if full else 0, rng, node_mask=av.acq)
    # Edges re-pointed from the carrier to its actor's acquisition: consecutive intervals between agents, and
    # offspring per acquisition.
    e_acq = dataclasses.replace(e, parent=av.owner[e.parent])
    out["adjacent"] = ts.adjacent_correlation(e_acq, ok, boot_reps if full else 0, rng)
    # H3: agent-to-agent retelling.
    sel3 = np.isin(e_all.key, ts.AGENT_RETELL_KEYS)
    carried, changed, changes = ts.quantity_changes(e_all, occ.qv_key, occ.qv_val, sel3)
    out["h3"] = {"n_edges": int(sel3.sum()), "n_edges_carry": int((carried[sel3] > 0).sum()),
                 "contexts_carried": int(carried[sel3].sum()), "contexts_changed": int(changed[sel3].sum())}
    out["h3"]["c"] = out["h3"]["contexts_changed"] / out["h3"]["contexts_carried"] if out["h3"]["contexts_carried"] else np.nan
    if not full:
        out["edge_ch_counts"] = {ch: int((e.ch == k).sum()) for k, ch in enumerate(ts.H1_CHANNELS)}
        gi = np.minimum(av.gen, 10)
        kids = np.bincount(e_acq.parent, minlength=occ.n)
        okn = (occ.pos <= clock.end - L) & entries
        out["offspring_by_gen"] = [float(kids[(gi == g) & okn].mean()) if ((gi == g) & okn).any() else np.nan
                                   for g in range(11)]
        return out
    out["forest"] = f
    out["agent"] = av
    out["edges"] = e
    out["ok"] = ok
    out["edges_all"] = e_all
    out["ok_all"] = ok_all
    det_occ = ts.determined(c, f)
    out["det_all"] = det_occ[e_all.child]
    boot_e = ts.ClusterBoot(e.root[ok], boot_reps, rng)
    out["intervals"] = ts.interval_table(e, ok, boot_e, min_e)
    # H3 by channel, with CIs, and inheritance.
    h3_rows = []
    for name, keys in (("agent_retelling", ts.AGENT_RETELL_KEYS),
                       ("chat_to_chat_other", (KEY_CODE["chat>chat:other"],)),
                       ("chat_to_memory_other", (KEY_CODE["chat>memory:other"],)),
                       ("chat_same_agent", (KEY_CODE["chat>chat:self"], KEY_CODE["chat>memory:self"])),
                       ("own_memory_to_chat", (KEY_CODE["memory>chat"],)),
                       ("search_answer_to_agent", (KEY_CODE["search>chat"], KEY_CODE["search>memory"])),
                       ("chat_to_search_answer", (KEY_CODE["history>search"],))):
        m = np.isin(e_all.key, keys)
        cr, chg, chs = ts.quantity_changes(e_all, occ.qv_key, occ.qv_val, m)
        mm = m & (cr > 0)
        row = {"channel": name, "n_edges": int(m.sum()), "n_edges_with_shared_context": int(mm.sum()),
               "contexts_carried": int(cr[m].sum()), "contexts_changed": int(chg[m].sum())}
        row["c"] = row["contexts_changed"] / row["contexts_carried"] if row["contexts_carried"] else np.nan
        row["edge_change_share"] = float((chg[mm] > 0).mean()) if mm.any() else np.nan
        if mm.any():
            b = ts.ClusterBoot(e_all.root[mm], boot_reps, rng)
            row["c_lo"], row["c_hi"] = ts.ci(ts.boot_ratio(b, chg[mm].astype(float), cr[mm].astype(float), b.inv))
        row.update(ts.inheritance(e_all, occ.qv_key, occ.qv_val, chs))
        h3_rows.append(row)
    out["h3_rows"] = h3_rows
    # Per-generation table over acquisitions (roots, env_i children and children of another actor).
    var_new = (c.n_var_q[e_all.child] - c.S_q[e_all.row]).astype(np.int64)[sel]
    alt = c.subset(c.parent != ENV)
    alt_chosen = map_choice(alt, posterior(alt, inp["K"][c.parent != ENV], inp["gamma"]), occ.n)
    fa = make_forest(alt, alt_chosen)
    av_alt = ts.agent_view(fa, occ.actor, occ.unit)
    is_env = f.parent == ENV
    out["generations"] = ts.generation_table(e_acq, fv, occ.pos, clock.end, L, inp["susceptible"], var_new,
                                             c.n_var_q, av_alt.gen, av_alt.root, is_env, boot_reps, rng,
                                             node_mask=entries, alt_mask=entries)
    # Restatement chains, and H1 with occurrence-level generations for reference.
    out["restatement"] = ts.restatement_summary(av, f, occ.actor)
    p_occ = int(cfg_l.get("perms_sensitivity", perms))
    out["h1_ad_occ"] = ts.h1_ad_tests(e_all, ok_all, min_e, p_occ, rng)
    out["h1_ad_det_occ"] = ts.h1_ad_tests(e_all, ok_all & det_occ[e_all.child], min_e, p_occ, rng)
    # Attractor by agent-level generation.
    at = ts.attractor(occ.win, occ.unit, np.arange(occ.n))
    out["attractor"] = attractor_table(at, fv, occ, boot_reps, rng, min_e)
    return out


def attractor_table(at: dict, f: ts.Forest, occ: Occ, boot_reps: int, rng, min_n: int) -> list[dict]:
    rows = []
    gmax = min(int(f.gen.max()), 10)
    gi = np.minimum(f.gen, gmax)
    unit = occ.unit
    multi = np.zeros(occ.n_units, dtype=bool)
    np.logical_or.at(multi, unit[f.gen >= 1], True)
    use = multi[unit]
    boot = ts.ClusterBoot(unit[use], boot_reps, rng)
    for name in ("ttr", "sim"):
        v = at[name]
        ok = use & np.isfinite(v)
        for g in range(gmax + 1):
            m = ok & (gi == g)
            if m.sum() < 1:
                continue
            r = {"measure": "type_token_ratio" if name == "ttr" else "similarity_to_modal", "generation": g,
                 "n_nodes": int(m.sum()), "n_units": int(len(np.unique(unit[m]))), "mean": float(v[m].mean()),
                 "reported": int(m.sum()) >= min_n}
            if m.sum() >= min_n:
                r["mean_lo"], r["mean_hi"] = ts.ci(ts.boot_ratio(boot, v[m], np.ones(int(m.sum())),
                                                                  boot.cluster_index(unit[m])))
            rows.append(r)
        # Within-unit slope of the measure on generation.
        m = ok
        if m.sum() > 10:
            x, y, u = f.gen[m].astype(float), v[m], unit[m]
            xm = np.bincount(u, weights=x, minlength=occ.n_units) / np.maximum(np.bincount(u, minlength=occ.n_units), 1)
            ym = np.bincount(u, weights=y, minlength=occ.n_units) / np.maximum(np.bincount(u, minlength=occ.n_units), 1)
            xd, yd = x - xm[u], y - ym[u]
            slope = float((xd * yd).sum() / (xd * xd).sum()) if (xd * xd).sum() > 0 else np.nan
            k = boot.cluster_index(u)
            A = np.zeros((boot.C, 2))
            np.add.at(A, (k, 0), xd * yd)
            np.add.at(A, (k, 1), xd * xd)
            R = boot.matmul(A)
            with np.errstate(invalid="ignore", divide="ignore"):
                bs = R[:, 0] / R[:, 1]
            lo, hi = ts.ci(bs)
            rows.append({"measure": ("type_token_ratio" if name == "ttr" else "similarity_to_modal") + "_slope",
                         "generation": -1, "n_nodes": int(m.sum()), "n_units": int(len(np.unique(u))),
                         "mean": slope, "mean_lo": lo, "mean_hi": hi, "reported": True})
    return rows


# --- posterior draws ---------------------------------------------------------------------------------------------

def _sample_job(seeds: list[int]) -> list[dict]:
    single_thread()
    g = _G
    out = []
    for s in seeds:
        rng = np.random.default_rng([g["seed"], 7, s])
        chosen = sample_choice(g["c"], g["post"], g["inp"]["occ"].n, rng)
        st = forest_stats(g["inp"], g["c"], g["post"], chosen, g["cfg_l"], rng, 0, g["perms"], full=False)
        out.append(_light_row(s, st))
    return out


def _light_row(s: int, st: dict) -> dict:
    r = {"sample": s, "n_edges": st["n_edges"], "n_edges_all": st["n_edges_all"], "n_env": st["n_env"],
         "n_roots": st["n_roots"], "max_gen": st["max_gen"], "max_gen_occurrence": st["max_gen_occurrence"],
         "h3_c": st["h3"]["c"], "adjacent_rho": st["adjacent"]["rho"]}
    gc = st["gen_counts"]
    for g in range(8):
        r[f"nodes_gen{g}"] = int(gc[g]) if g < len(gc) else 0
    for row in st["h1_ad"]:
        r[f"h1_p_{row['channel']}"] = row["p_perm"]
        r[f"h1_ngen_{row['channel']}"] = row["n_generations"]
    for row in st["h1_ad_det"]:
        r[f"h1det_p_{row['channel']}"] = row["p_perm"]
    for f in st["tk"]["fits"]:
        r[f"tk_{f['quantity']}_{f['model']}_slope"] = f["slope"]
        if f["model"] == "quadratic":
            r[f"tk_{f['quantity']}_k2"] = f["k2"]
    for ch, v in st["edge_ch_counts"].items():
        r[f"edges_{ch}"] = v
    for g, v in enumerate(st["offspring_by_gen"][:6]):
        r[f"offspring_gen{g}"] = v
    return r


def posterior_draws(inp: dict, c: Cands, post: np.ndarray, cfg_l: dict, n_draws: int, perms: int, seed: int,
                    n_workers: int, log=print) -> pl.DataFrame:
    t0 = time.perf_counter()
    _G.update({"inp": inp, "c": c, "post": post, "cfg_l": cfg_l, "perms": perms, "seed": seed})
    seeds = list(range(n_draws))
    if n_workers > 1:
        chunks = [seeds[k::n_workers] for k in range(n_workers)]
        with mp.get_context("fork").Pool(min(n_workers, n_draws)) as pool:
            rows = [r for ch in pool.map(_sample_job, chunks) for r in ch]
    else:
        rows = _sample_job(seeds)
    log(f"posterior draws: {n_draws} in {time.perf_counter() - t0:.0f} s")
    return pl.DataFrame(rows).sort("sample")


# --- B1 comparison (H3) --------------------------------------------------------------------------------------------

def b1_quantity_c(outputs: Path, rules: str) -> list[dict]:
    """B1's per-consolidation value-change rate for quantity facts whose context stays (rule set `rules`)."""
    from scipy import stats

    sfx = "" if rules == "v1" else f"_{rules}"
    p = outputs / "tables" / f"memory_by_anchor{sfx}.csv"
    if not p.exists():
        return []
    df = pl.read_csv(p, infer_schema_length=10000)
    rows = []
    for t in ("number", "money", "percent", "time"):
        r = df.filter((pl.col("anchor_type") == t) & (pl.col("stratum") == "All standard"))
        if not r.height:
            continue
        r = r.row(0, named=True)
        n_tr, n_lost = float(r["n_trials"]), float(r["n_lost"])
        m = float(r["modified_share_of_losses"]) * n_lost
        kept = n_tr - n_lost
        c = m / (kept + m) if kept + m > 0 else np.nan
        lo, hi = (stats.binomtest(int(round(m)), int(round(kept + m))).proportion_ci(confidence_level=0.95, method="wilson")
                  if kept + m > 0 else (np.nan, np.nan))
        rows.append({"channel": f"memory_consolidation_b1_{t}", "rules": rules, "contexts_carried": int(round(kept + m)),
                     "contexts_changed": int(round(m)), "c": c, "c_lo": float(lo), "c_hi": float(hi),
                     "modification_rate_per_trial": float(r["modification_rate"]), "n_agents": int(r["n_agents"]),
                     "ci_note": "Wilson, units independent (B1 does not report a clustered CI for this ratio)"})
    tot_m = sum(r["contexts_changed"] for r in rows)
    tot_n = sum(r["contexts_carried"] for r in rows)
    if tot_n:
        lo, hi = stats.binomtest(tot_m, tot_n).proportion_ci(confidence_level=0.95, method="wilson")
        rows.append({"channel": "memory_consolidation_b1_quantities", "rules": rules, "contexts_carried": tot_n,
                     "contexts_changed": tot_m, "c": tot_m / tot_n, "c_lo": float(lo), "c_hi": float(hi),
                     "ci_note": "Wilson, units independent"})
    return rows


# --- the run --------------------------------------------------------------------------------------------------------

def lineage_cfg(cfg: dict) -> dict:
    lin = cfg.get("lineage", {})
    return {"L_B": float(lin.get("right_censor_run_days", L_B_DEFAULT)),
            "min_edges": int(lin.get("min_edges_per_generation", 30)),
            "gamma": float(lin.get("gamma", 1.0)),
            "samples": int(lin.get("posterior_samples", 200)),
            "boot_reps": int(lin.get("boot_reps", 500)),
            "perms": int(lin.get("h1_permutations", 499)),
            "perms_draws": int(lin.get("h1_permutations_draws", 99)),
            "perms_sensitivity": int(lin.get("h1_permutations_sensitivity", 199)),
            "draw_workers": int(lin.get("draw_workers", 24)),
            "kde_min_edges": int(lin.get("kde_min_edges", 50)),
            "synthetic_reps": int(lin.get("synthetic_reps", 100)),
            "synthetic_units": int(lin.get("synthetic_units", 20000))}


def unit_keys(units: pl.DataFrame, salt: bytes) -> list[str]:
    """Keyed public ids of units (outputs never show values)."""
    return [keyed_hash(salt, "b2unit", str(u), 12)[2:] for u in units["unit_id"].to_list()]


def run_trees(cfg: dict | None = None, *, rules: str = "v2", n_workers: int | None = None, tag: str = "",
              env_rule: str = "precede", exposure: str = "main", hawkes: str = "auto", synthetic: bool = True,
              sensitivity: bool = True, samples: int | None = None, write_outputs: bool = True,
              gamma_mode: str = "tier1", log=print) -> dict:
    """Module B2 on the real data (see the module docstring). Returns the summary rendered in the QA report.
    gamma_mode: "tier1" (grid on the tier-1 name-reference labels), "hand" (time term and gamma chosen on the
    owner's labels in data/labels/parents_review.csv, at least 20), "composite" (the same on the owner's label
    where it exists and Claude's from data/labels/parents_claude.csv elsewhere; the owner's choice of
    2026-10-03) or a number (fixed gamma)."""
    from avsd.lineage import b2_refs, trees_report, trees_synth

    cfg = cfg or load_config()
    t_start = time.perf_counter()
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(var, "1")
    n_workers = n_workers or int(os.environ.get("SLURM_CPUS_PER_TASK") or os.cpu_count() or 1)
    cl = lineage_cfg(cfg)
    if samples is not None:
        cl["samples"] = samples
    seed = int(cfg["seed"])
    rng = np.random.default_rng(seed)
    paths = cfg["paths"]
    interim, outputs, labels_dir = Path(paths["interim"]), Path(paths["outputs"]), Path(paths["labels"])
    salt = load_salt(interim)
    timings: dict[str, float] = {}

    t = time.perf_counter()
    inp = load_inputs(cfg, rules, tag, exposure, log)
    occ: Occ = inp["occ"]
    run_day_of = np.floor(occ.pos).astype(np.int64)
    inp["susceptible"] = susceptible_share(occ, inp["roster"], inp["a_index"], run_day_of)
    timings["inputs"] = time.perf_counter() - t

    t = time.perf_counter()
    c = build_cands(occ, n_workers, cl["L_B"], env_rule, exposure, log)
    timings["candidates"] = time.perf_counter() - t

    # Time term.
    single = single_candidate_edges(c)
    kernel = EmpiricalKernel(min_edges=cl["kde_min_edges"], seed=seed).fit(c.key[single], c.dt[single])
    hook, hk_info = None, None
    if hawkes != "off":
        hk_path = outputs / "tables" / "hawkes_kernels.parquet"
        hook = HawkesKernel.from_file(hk_path, kernel, room_names(cfg))
        hk_info = hawkes_file_info(hk_path) if hook is not None else None
        if hook is None and hawkes == "on":
            raise SystemExit(f"--hawkes on but {hk_path} does not exist")
    et = c.edge_times(occ)
    K = hook.density(et) if hook is not None else kernel.density(et)
    hook_used = dict(hook.used) if hook is not None else None
    hook_last = hook.last if hook is not None else None
    inp["K"] = K
    log(f"time term: {'module A hook + KDE' if hook else 'empirical KDE'}; single-candidate edges {len(single):,}")

    # Labels, gamma, ablation.
    t = time.perf_counter()
    refs_path = inp["dir"] / "explicit_refs.parquet"
    if refs_path.exists():
        refs = pl.read_parquet(refs_path)
    else:
        refs = b2_refs.explicit_refs(cfg)
        refs.write_parquet(refs_path)
    cases = label_cases(inp, c, refs)
    pre = "pilot_" if tag else ""
    hand_path, claude_path = labels_dir / f"{pre}parents_review.csv", labels_dir / f"{pre}parents_claude.csv"
    req_path = label_requests_path(cfg, tag)
    hand = sheet_label_cases(inp, c, hand_path, "hand", req_path) if hand_path.exists() else None
    claude = sheet_label_cases(inp, c, claude_path, "claude", req_path) if claude_path.exists() else None
    comp = composite_label_cases(hand, claude) if claude is not None else None
    for extra in (hand, claude, comp):
        if extra is not None and len(extra["child"]):
            cases = concat_cases(cases, extra)
    fixed = None
    if gamma_mode not in ("tier1", "hand", "composite"):
        fixed = float(gamma_mode)
    elif gamma_mode in ("hand", "composite"):
        n_sel = int((cases["kind"] == gamma_mode).sum()) if len(cases["child"]) else 0
        if n_sel < HAND_MIN_CASES:
            raise SystemExit(f"--gamma {gamma_mode} needs at least {HAND_MIN_CASES} labelled rows that match a "
                             f"candidate; found {n_sel}")
    K_kde = kernel.density(et) if hook is not None else None
    # Choice of the time term and gamma on the owner's labels or the composite set (parent accuracy, then the
    # mean log posterior).
    selection, sel_rows, hook_is_main = None, [], hook is not None
    if gamma_mode in ("hand", "composite"):
        terms = [("module A kernel + KDE", K), ("KDE only", K_kde)] if hook is not None else [("KDE only", K)]
        sets = {lab: cases["kind"] == kind for lab, kind in (("owner", "hand"), ("claude", "claude"),
                                                              ("composite", "composite"))
                if len(cases["child"]) and (cases["kind"] == kind).any()}
        best, sel_rows = select_by_labels(c, cases, sets, terms)
        key = "owner" if gamma_mode == "hand" else "composite"
        term, fixed = best[key]
        selection = {"label_set": key, "time_term": term, "gamma": fixed, "best_by_set": best}
        if hook is not None and term == "KDE only":
            K, K_kde, hook_is_main = K_kde, K, False
            inp["K"] = K
        log(f"label selection on {key}: time term {term}, gamma {fixed}")
    gamma, grid_rows, abl_rows, gamma_kde = gamma_and_ablation(
        c, K, cases, rng, cl["boot_reps"], cl["gamma"], occ, K_alt=K_kde, rng_alt=np.random.default_rng([seed, 7]),
        gamma_set=gamma_mode if gamma_mode in ("hand", "composite") else "name_tier1", fixed_gamma=fixed,
        alt_suffix="_kde_only" if hook_is_main else "_module_a")
    del K_kde
    inp["gamma"] = gamma
    timings["labels"] = time.perf_counter() - t
    log(f"labels: {len(refs):,} explicit references, {len(cases['child']):,} usable cases; gamma = {gamma}")

    # MAP forest and statistics.
    t = time.perf_counter()
    post = posterior(c, K, gamma)
    chosen = map_choice(c, post, occ.n)
    time_term = []
    if hook is not None:
        on_map = np.zeros(c.n, dtype=bool)
        on_map[chosen[chosen >= 0]] = True
        time_term = (hook.window_table(hook_last, scope="candidate_edges")
                     + hook.window_table(hook_last, mask=on_map, scope="map_edges"))
        del on_map, hook_last
    main = forest_stats(inp, c, post, chosen, cl, rng, cl["boot_reps"], cl["perms"], full=True)
    timings["map_stats"] = time.perf_counter() - t
    log(f"MAP forest: {main['n_edges']:,} transmission edges, {main['n_env']:,} env, max generation "
        f"{main['max_gen']} ({timings['map_stats']:.0f} s)")

    # Posterior draws.
    t = time.perf_counter()
    draws = posterior_draws(inp, c, post, cl, cl["samples"], cl["perms_draws"], seed,
                            min(n_workers, cl["draw_workers"]), log)
    timings["draws"] = time.perf_counter() - t

    # Synthetic validation.
    synth = None
    if synthetic:
        t = time.perf_counter()
        synth = trees_synth.run_synthetic(inp, c, main, kernel, gamma, cl, seed, n_workers, log)
        timings["synthetic"] = time.perf_counter() - t

    # Sensitivity runs.
    sens_rows = []
    if sensitivity:
        t = time.perf_counter()
        sens_rows = sensitivity_runs(cfg, inp, c, K, kernel, hook, gamma, cl, rules, env_rule, exposure, tag,
                                     n_workers, seed, log, hook_is_main=hook_is_main)
        timings["sensitivity"] = time.perf_counter() - t

    summary = {
        "rules": rules, "env_rule": env_rule, "exposure": exposure, "gamma": gamma, "hawkes_hook": hook is not None,
        "hawkes_used": hook_used, "time_term": time_term, "gamma_kde_only": gamma_kde, "gamma_mode": gamma_mode,
        "hook_is_main": hook_is_main, "label_selection": selection, "label_selection_rows": sel_rows,
        "label_agreement": label_agreement_counts(hand_path, claude_path),
        "hand_labels": ({"labelled": hand["n_labelled"], "matched": int(len(hand["child"])),
                         "unmatched": hand["n_unmatched"]} if hand is not None else None),
        "hawkes_file": hk_info,
        "cl": cl, "seed": seed,
        "n_units": inp["units"].height, "n_occ": occ.n, "cands": c.n, "cand_stats": c.stats,
        "units_by_kind": dict(inp["units"].group_by("unit_kind").len().iter_rows()),
        "units_by_type": dict(inp["units"].group_by("anchor_type").len().iter_rows()),
        "occ_by_src": {SRC_NAMES[k]: int((occ.src == k).sum()) for k in range(3)},
        "kernel": kernel.info, "grid": grid_rows, "ablation": abl_rows, "main": main, "draws": draws,
        "synthetic": synth, "sensitivity": sens_rows, "n_refs": refs.height, "n_cases": len(cases["child"]),
        "cases_by_kind": {f"{k}_tier{t_}": int(((cases["kind"] == k) & (cases["tier"] == t_)).sum())
                          for k in ("name", "quote") for t_ in (1, 2)} if len(cases["child"]) else {},
        "b1_c": b1_quantity_c(outputs, rules) + [r for alt in RULES if alt != rules for r in b1_quantity_c(outputs, alt)
                                                 if r["channel"] == "memory_consolidation_b1_quantities"],
        "timings": timings,
        "meta": json.loads((inp["dir"] / "meta.json").read_text()) if (inp["dir"] / "meta.json").exists() else {},
    }
    summary["unit_trees"] = unit_tree_table(inp, main, salt)
    if write_outputs:
        write_parents_labels(inp, c, cases, labels_dir / ("parents.csv" if not tag else "pilot_parents.csv"))
        write_private_state(inp, c, post, chosen, cases)
        save_summary(summary, inp["dir"] / "summary.pkl")
        trees_report.write_all(cfg, summary, inp, c, post, chosen, cases, refs, labels_dir, tag, log)
    timings["total"] = time.perf_counter() - t_start
    log(f"done in {timings['total']:.0f} s")
    return summary


def save_summary(summary: dict, path: Path) -> None:
    """The run summary (data/interim/b2, private), so that tables, figures and the QA report can be written
    again without recomputing (`--report-only`)."""
    import pickle

    from avsd.lineage.prelabel import _private_open

    keep = dict(summary)
    keep["main"] = {k: v for k, v in summary["main"].items() if k != "forest"}
    with _private_open(path, "wb") as fh:
        pickle.dump(keep, fh, protocol=pickle.HIGHEST_PROTOCOL)


def report_only(cfg: dict, tag: str = "", log=print) -> None:
    """Write the outputs of the last run again from its saved summary."""
    import pickle

    from avsd.lineage import trees_report

    d = Path(cfg["paths"]["interim"]) / (B2_DIR + (f"_{tag}" if tag else ""))
    with open(d / "summary.pkl", "rb") as fh:
        summary = pickle.load(fh)
    trees_report.write_all(cfg, summary, {"dir": d}, None, None, None, None, None, Path(cfg["paths"]["labels"]),
                           tag, log)


def unit_tree_table(inp: dict, main: dict, salt: bytes) -> pl.DataFrame:
    """One row per unit: keyed id, type, URL domain, counts, trees, agent-level depth and restatements
    (no values)."""
    occ: Occ = inp["occ"]
    f: ts.Forest = main["forest"]
    av: ts.AgentView = main["agent"]
    units = inp["units"]
    U = occ.n_units
    n_tree = np.bincount(occ.unit[av.acq & (f.parent < 0)], minlength=U)
    depth = np.zeros(U, dtype=np.int64)
    np.maximum.at(depth, occ.unit, av.gen)
    rem = np.bincount(av.owner[~av.acq], minlength=occ.n)
    rdepth = np.zeros(U, dtype=np.int64)
    np.maximum.at(rdepth, occ.unit, rem)
    n_env = np.bincount(occ.unit[av.acq & (f.parent == ENV)], minlength=U)
    n_edges = np.bincount(occ.unit[av.acq & (f.parent >= 0)], minlength=U)
    n_same = np.bincount(occ.unit[~av.acq], minlength=U)
    agents = np.zeros(U, dtype=np.int64)
    for u in range(U):
        a = occ.actor[occ.start[u]:occ.start[u + 1]]
        agents[u] = len(np.unique(a[a >= 0]))
    return pl.DataFrame({
        "unit": unit_keys(units, salt), "unit_kind": units["unit_kind"], "anchor_type": units["anchor_type"],
        "domain": units["domain"], "n_occurrences": np.diff(occ.start), "n_agents": agents,
        "n_chat": units["n_chat"], "n_memory": units["n_memory"], "n_search": units["n_search"],
        "n_human": units["n_human"], "n_trees": n_tree, "n_transmission_edges": n_edges,
        "n_remention": n_same, "n_independent": n_env, "max_generation": depth,
        "max_restatement_depth": rdepth,
    })


def write_parents_labels(inp: dict, c: Cands, cases: dict, path: Path) -> None:
    """SPEC appendix C: data/labels/parents.csv with the explicit-reference labels used (private)."""
    import csv

    from avsd.lineage.prelabel import _private_open

    if not len(cases["child"]):
        return
    uid = inp["occ_df"]["occ_uid"].to_list()
    with _private_open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["occurrence_uid", "parent_uid", "source", "notes"])
        seen = set()
        for i, r, kind, tier in zip(cases["child"], cases["row"], cases["kind"], cases["tier"]):
            par = int(c.parent[int(r)])
            key = (int(i), par)
            if key in seen:
                continue
            seen.add(key)
            w.writerow([uid[int(i)], uid[int(par)], "explicit_ref", f"{kind} tier {tier}"])


def write_private_state(inp: dict, c: Cands, post: np.ndarray, chosen: np.ndarray, cases: dict) -> None:
    """MAP parents and candidate rows for the label sheet (data/interim/b2, private)."""
    d = inp["dir"]
    od = inp["occ_df"]
    occ: Occ = inp["occ"]
    kids, starts = c.offsets()
    pl.DataFrame({"child": c.child, "parent": c.parent, "key": c.key, "dt": c.dt, "S": c.S, "post": post,
                  "K": inp["K"]}).write_parquet(d / "candidates.parquet")
    pl.DataFrame({"gi": np.arange(occ.n), "chosen": chosen}).write_parquet(d / "map_chosen.parquet")
    del od, kids, starts


def hawkes_file_info(path: Path) -> dict:
    """Modification time (ET) and sha256 of the module A kernel file a run used."""
    import datetime as dt
    import hashlib
    from zoneinfo import ZoneInfo

    when = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=ZoneInfo("America/New_York"))
    return {"modified": when.strftime("%Y-%m-%d %H:%M ET"), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def room_names(cfg: dict) -> dict[str, str]:
    T = Path(cfg["paths"]["tables"])
    r = pl.read_parquet(T / "chat_rooms.parquet", columns=["id", "name"])
    return dict(zip(r["id"].to_list(), r["name"].to_list()))


# --- sensitivity -----------------------------------------------------------------------------------------------------

def _sens_row(name: str, value: str, st: dict, gamma: float, extra: dict | None = None) -> dict:
    r = {"variant": name, "value": value, "gamma": gamma, "n_edges": st["n_edges"], "n_edges_all": st["n_edges_all"],
         "n_env": st["n_env"], "n_roots": st["n_roots"], "max_generation": st["max_gen"],
         "max_generation_occurrence": st["max_gen_occurrence"], "max_restatement_depth": st["max_depth"],
         "independent_share_of_acquisitions": st["n_env"] / max(st["n_env"] + st["n_edges"], 1),
         "h3_c_agent_retelling": st["h3"]["c"], "adjacent_rho": st["adjacent"]["rho"]}
    gc = st["gen_counts"]
    for g in range(6):
        r[f"nodes_gen{g}"] = int(gc[g]) if g < len(gc) else 0
    for row in st["h1_ad"]:
        r[f"h1_p_{row['channel']}"] = row["p_perm"]
        r[f"h1_ngen_{row['channel']}"] = row["n_generations"]
    for row in st["h1_ad_det"]:
        r[f"h1det_p_{row['channel']}"] = row["p_perm"]
    r["n_determined_edges"] = st["n_determined_edges"]
    for f in st["tk"]["fits"]:
        r[f"tk_{f['quantity']}_{f['model']}_slope"] = f["slope"]
    r.update(extra or {})
    return r


def sensitivity_runs(cfg, inp, c, K, kernel, hook, gamma, cl, rules, env_rule, exposure, tag, n_workers, seed, log,
                     hook_is_main: bool = True):
    """Main statistics with the KDE alone, other gamma values, content between agents only, the other env
    rule, the other exposure rules and the other B1 rule sets."""
    rows = []
    occ: Occ = inp["occ"]
    rng = np.random.default_rng([seed, 99])
    perms = cl["perms_sensitivity"]

    def stats_for(cc, KK, g):
        post = posterior(cc, KK, g)
        ch = map_choice(cc, post, occ.n)
        return forest_stats(inp, cc, post, ch, cl, rng, 0, perms, full=False)

    main_k = hook if (hook is not None and hook_is_main) else kernel
    rows.append(_sens_row("main", f"rules {rules}, env {env_rule}, exposure {exposure}, "
                          f"time term {'module A kernel + KDE' if main_k is hook else 'KDE'}", stats_for(c, K, gamma),
                          gamma))
    if hook is not None and hook_is_main:
        rows.append(_sens_row("time_term", "KDE only (module A hook off)",
                              stats_for(c, kernel.density(c.edge_times(occ)), gamma), gamma))
    elif hook is not None:
        rows.append(_sens_row("time_term", "module A kernel + KDE",
                              stats_for(c, hook.density(c.edge_times(occ)), gamma), gamma))
    if gamma != 0.0:
        rows.append(_sens_row("gamma", "0 (time only)", stats_for(c, K, 0.0), 0.0))
    if gamma != cl["gamma"]:
        rows.append(_sens_row("gamma", f"{cl['gamma']} (SPEC default)", stats_for(c, K, cl["gamma"]), cl["gamma"]))
    par = np.where(c.parent >= 0, c.parent, c.child)
    cx = c.subset(np.ones(c.n, dtype=bool))
    cx.S = np.where((c.parent >= 0) & (occ.actor[par] == occ.actor[c.child]), 0, c.S).astype(np.int32)
    g_x = gamma if gamma > 0 else cl["gamma"]
    rows.append(_sens_row("content", f"other agents only, gamma {g_x}", stats_for(cx, K, g_x), g_x))
    for alt_env in ("any", "precede"):
        if alt_env == env_rule:
            continue
        cc = build_cands(occ, n_workers, cl["L_B"], alt_env, exposure, log)
        KK = main_k.density(cc.edge_times(occ))
        rows.append(_sens_row("env_rule", alt_env, stats_for(cc, KK, gamma), gamma))
    for alt_exp in ("ever", "all"):
        if alt_exp == exposure:
            continue
        if alt_exp == "ever" and occ.room_spells is None:
            occ.room_spells = room_spells(Path(cfg["paths"]["processed"]), inp["agent_ids"], inp["room_code"])
        cc = build_cands(occ, n_workers, cl["L_B"], env_rule, alt_exp, log)
        KK = main_k.density(cc.edge_times(occ))
        rows.append(_sens_row("exposure", alt_exp, stats_for(cc, KK, gamma), gamma))
    for alt_rules in RULES:
        if alt_rules == rules:
            continue
        alt = load_inputs(cfg, alt_rules, tag, exposure, log=lambda m: None)
        alt["susceptible"] = inp["susceptible"]
        cc = build_cands(alt["occ"], n_workers, cl["L_B"], env_rule, exposure, log)
        KK = main_k.density(cc.edge_times(alt["occ"]))
        post = posterior(cc, KK, gamma)
        ch = map_choice(cc, post, alt["occ"].n)
        alt["K"], alt["gamma"] = KK, gamma
        st = forest_stats(alt, cc, post, ch, cl, rng, 0, perms, full=False)
        rows.append(_sens_row("rules", alt_rules, st, gamma))
    return rows


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Module B2: transmission trees (SPEC 6.4).")
    p.add_argument("--config", default=None)
    p.add_argument("--workers", type=int, default=0)
    p.add_argument("--rules", default="v2", choices=RULES, help="B1 rule set (v2: B1's main rule set since 2026-10-03)")
    p.add_argument("--env-rule", default="precede", choices=("precede", "any"))
    p.add_argument("--exposure", default="main", choices=("main", "ever", "all"))
    p.add_argument("--hawkes", default="auto", choices=("auto", "on", "off"))
    p.add_argument("--gamma", default="tier1",
                   help="tier1 (grid on tier-1 name labels); hand or composite (time term and gamma chosen on the "
                        "owner's labels, or on the owner's labels plus Claude's elsewhere); or a number")
    p.add_argument("--samples", type=int, default=None)
    p.add_argument("--synthetic-reps", type=int, default=None)
    p.add_argument("--synthetic-units", type=int, default=None)
    p.add_argument("--no-synthetic", action="store_true")
    p.add_argument("--no-sensitivity", action="store_true")
    p.add_argument("--pilot", action="store_true", help="use data/interim/b2_pilot (outputs get a pilot_ prefix)")
    p.add_argument("--report-only", action="store_true", help="write the outputs again from the saved summary")
    args = p.parse_args(argv)

    def log(msg: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    cfg = load_config(args.config)
    if args.report_only:
        report_only(cfg, "pilot" if args.pilot else "", log)
        return
    for k, v in (("synthetic_reps", args.synthetic_reps), ("synthetic_units", args.synthetic_units)):
        if v is not None:
            cfg.setdefault("lineage", {})[k] = v
    run_trees(cfg, rules=args.rules, n_workers=args.workers or None,
              tag="pilot" if args.pilot else "", env_rule=args.env_rule, exposure=args.exposure, hawkes=args.hawkes,
              synthetic=not args.no_synthetic, sensitivity=not args.no_sensitivity, samples=args.samples,
              gamma_mode=args.gamma, log=log)


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
