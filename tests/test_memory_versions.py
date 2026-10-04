import random
from datetime import datetime, timedelta, timezone

import numpy as np
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from avsd.events.memory_versions import (
    RELS,
    classify_memory_rows,
    last_session_label,
    prefix_hashes,
    render_qa,
    summarize,
)

T0 = datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc)
SID1 = "11111111-2222-4333-8444-555555555555"
SID2 = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def _agent_a() -> list[tuple[str, str]]:
    """Standard scaffold, pre-regime. (row id, content) in time order."""
    r0 = "Notes ü 😀: core facts.\n"
    r1 = r0 + f"\n\nPREVIOUS (NOW ENDED) COMPUTER USE SESSION ({SID1}) \nOpened the doc."
    r2 = r1 + "\n\nSelf-note: the PREVIOUS (NOW ENDED) block above is mine."
    r6 = "Consolidated ü: facts and doc.\n"
    r7 = r6 + "\n\nPREVIOUS (NOW ENDED) SESSION (Day 5, 10:00 to 12:00)\nWrote a page."
    return [
        ("a0", r0),             # first
        ("a1", r1),             # append_session, uuid label
        ("a2", r2),             # append_note (label text not at a line start)
        ("a3", r2),             # ident
        ("a4", r1),             # revert to a1 (2 back), trunc-shaped
        ("a5", r1[:-4]),        # trunc_other
        ("a6", r6),             # rewrite, generation 1
        ("a7", r7),             # append_session, label without uuid
        ("a8", "Short ü.\n"),   # rewrite, generation 2 (a dead branch)
        ("a9", r7 + "\n\nPREVIOUS (NOW ENDED) SESSION (" + SID2 + ")\nMore."),  # fork_append on a7
        ("a10", "Merged ü again.\n"),  # rewrite whose lineage parent is a6, not a8
    ]


def _agent_b() -> list[tuple[str, str]]:
    """Standard scaffold that enters the CONSOLIDATE regime at row b2."""
    b0 = "Start.\n"
    b1 = b0 + "\n\nPREVIOUS (NOW ENDED) COMPUTER USE SESSION (" + SID1 + ")\nx"
    b3 = "Cycle one.\n" + "\n\nPREVIOUS (NOW ENDED) SESSION (2026-04-01, 10:00 to 12:00 PT)\ny"
    return [("b0", b0), ("b1", b1), ("b2", "Cycle one.\n"), ("b3", b3), ("b4", "Cycle two.\n")]


def _agent_c() -> list[tuple[str, str]]:
    """Claude Code scaffold: whole-file rewrites, one right after another."""
    return [("c0", "# memory\nA"), ("c1", "# memory\nA"), ("c2", "# memory v2\nB"),
            ("c3", "# other\nC")]


def _agent_d() -> list[tuple[str, str]]:
    """Empty rows: a prefix of everything, but never a fork base."""
    return [("d0", ""), ("d1", "abc"), ("d2", "xyz"), ("d3", "xyz!"), ("d4", "")]


AGENTS = {"A": _agent_a(), "B": _agent_b(), "C": _agent_c(), "D": _agent_d()}


@pytest.fixture(scope="module")
def tables(tmp_path_factory):
    d = tmp_path_factory.mktemp("tables")
    meta, text = [], []
    for agent, rows in AGENTS.items():
        for i, (rid, content) in enumerate(rows):
            ts = T0 + timedelta(minutes=i)
            if rid == "b2":  # rewrite written 16 ms before the first CONSOLIDATE
                ts = T0 + timedelta(minutes=2) - timedelta(milliseconds=16)
            meta.append({"id": rid, "agent_id": agent, "created_at": ts,
                         "updated_at": ts, "content_len": len(content)})
            text.append({"id": rid, "content": content})
    order = list(range(len(meta)))
    random.Random(0).shuffle(order)  # the real text table is not in agent order
    pl.DataFrame([meta[i] for i in order]).with_columns(
        pl.col("created_at", "updated_at").dt.replace_time_zone("UTC")
    ).write_parquet(d / "agent_memories.parquet")
    pq.write_table(pa.Table.from_pylist([text[i] for i in order]),
                   d / "agent_memories_text.parquet", row_group_size=4)
    pl.DataFrame({
        "action_type": ["CONSOLIDATE", "CONSOLIDATE", "STOP_USING_COMPUTER"],
        "agent_id": ["B", "B", "A"],
        "created_at": [T0 + timedelta(minutes=2), T0 + timedelta(minutes=4), T0],
    }).with_columns(pl.col("created_at").dt.replace_time_zone("UTC")).write_parquet(
        d / "events.parquet")
    pl.DataFrame({"agent_id": ["C"]}).write_parquet(d / "claude_code_sessions.parquet")
    return d


@pytest.fixture(scope="module")
def df(tables):
    return classify_memory_rows(tables, n_workers=1)


def _rows(df):
    return {r["id"]: r for r in df.iter_rows(named=True)}


def test_prefix_hashes_match_slices():
    text = "aü😀b" * 50
    lens = np.array([0, 1, 2, 3, 7, 199])
    full, pref = prefix_hashes(text, lens)
    for n, h in zip(lens.tolist(), pref.tolist()):
        assert h == prefix_hashes(text[:n], np.array([], dtype=np.int64))[0]
    assert full == prefix_hashes(text, np.array([], dtype=np.int64))[0]
    assert full != pref[-1]


def test_last_session_label():
    assert last_session_label("x") == (-1, None)
    t = f"a\n\nPREVIOUS (NOW ENDED) COMPUTER USE SESSION ({SID1}) \nb"
    assert last_session_label(t) == (3, SID1)
    t2 = t + "\n\nPREVIOUS (NOW ENDED) SESSION (Day 3, 10:00 to 11:00)\nc"
    t2 += " note PREVIOUS (NOW ENDED) x"
    pos, sid = last_session_label(t2)
    assert t2[pos:].startswith("PREVIOUS (NOW ENDED) SESSION (Day 3") and sid is None


def test_relations(df):
    rel = dict(zip(df["id"], df["rel"]))
    assert [rel[i] for i, _ in AGENTS["A"]] == [
        "first", "append_session", "append_note", "ident", "revert", "trunc_other",
        "rewrite", "append_session", "rewrite", "fork_append", "rewrite",
    ]
    assert [rel[i] for i, _ in AGENTS["B"]] == [
        "first", "append_session", "rewrite", "append_session", "rewrite"]
    assert [rel[i] for i, _ in AGENTS["C"]] == ["first", "ident", "rewrite", "rewrite"]
    assert [rel[i] for i, _ in AGENTS["D"]] == [
        "first", "append_note", "rewrite", "append_note", "revert"]
    assert set(df["rel"].unique()) == set(RELS)
    pk = dict(zip(df["id"], df["pair_kind"]))
    assert (pk["a4"], pk["a5"], pk["a9"], pk["a0"]) == ("trunc", "trunc", "rewrite", None)


def test_bases_and_sessions(df):
    r = _rows(df)
    assert (r["a4"]["base_id"], r["a4"]["base_lag"]) == ("a1", 3)
    assert (r["a9"]["base_id"], r["a9"]["base_lag"], r["a9"]["prev_id"]) == ("a7", 2, "a8")
    assert r["a5"]["base_id"] == r["a5"]["prev_id"] == "a4"
    assert r["a0"]["prev_id"] is None and r["a0"]["base_id"] is None
    assert r["a1"]["session_id"] == SID1
    assert r["a7"]["has_session_block"] and r["a7"]["session_id"] is None
    assert r["a9"]["has_session_block"] and r["a9"]["session_id"] == SID2
    assert r["a2"]["session_id"] is None and not r["a2"]["has_session_block"]
    assert r["b3"]["rel"] == "append_session" and r["b3"]["session_id"] is None


def test_lineage(df):
    r = _rows(df)
    gens = df.filter(pl.col("is_generation"))["id"].to_list()
    assert sorted(gens) == sorted(["a0", "a6", "a8", "a10", "b0", "b2", "b4", "c0", "c2", "c3",
                                   "d0", "d2"])
    assert (r["a6"]["parent_gen_id"], r["a6"]["input_row_id"], r["a6"]["version_idx"]) == (
        "a0", "a5", 1)
    assert (r["a8"]["parent_gen_id"], r["a8"]["input_row_id"], r["a8"]["version_idx"]) == (
        "a6", "a7", 2)
    # The fork continues a6's lineage, so a10 descends from a6, not from a8.
    assert (r["a9"]["gen_id"], r["a9"]["version_idx"]) == ("a6", 1)
    assert (r["a10"]["parent_gen_id"], r["a10"]["input_row_id"], r["a10"]["version_idx"]) == (
        "a6", "a9", 2)
    # Identical rows resolve to the earliest copy as the rewrite input.
    assert (r["c2"]["input_row_id"], r["c2"]["parent_gen_id"]) == ("c0", "c0")
    assert r["c3"]["input_row_id"] == "c2" and r["c3"]["version_idx"] == 2
    assert r["a0"]["parent_gen_id"] is None and r["a0"]["version_idx"] == 0
    assert r["a3"]["gen_id"] == "a0" and r["a7"]["gen_id"] == "a6"


def test_scaffold_and_regime(df):
    r = _rows(df)
    assert {r[i]["scaffold"] for i, _ in AGENTS["C"]} == {"claude_code"}
    assert r["a0"]["scaffold"] == "standard"
    assert [r[i]["regime_cu"] for i, _ in AGENTS["B"]] == ["pre", "pre", "post", "post", "post"]
    assert {r[i]["regime_cu"] for i, _ in AGENTS["A"] + AGENTS["C"]} == {"pre"}


def test_workers_agree(tables, df):
    par = classify_memory_rows(tables, n_workers=2)
    assert par.equals(df)


def test_summarize(df):
    s = summarize(df)
    assert s["n_rows"] == df.height == sum(len(v) for v in AGENTS.values())
    assert sum(s["rel"].values()) == df.height
    assert s["rel"]["fork_append"] == 1 and s["rel"]["revert"] == 2
    assert s["revert_lag"] == {3: 1, 4: 1} and s["fork_lag"] == {2: 1}
    assert s["revert_pair_kind"]["trunc"] == 2
    assert s["rel_by_regime"]["post"]["rewrite"] == 2
    assert s["rel_by_scaffold"]["claude_code"]["rewrite"] == 2
    assert s["parent_gen_not_time_previous"] == 1  # a10
    assert s["rewrite_input_is_generation"] == 2  # c2 (via ident c1 -> c0), c3
    a = s["by_agent"].filter(pl.col("agent_id") == "A").row(0, named=True)
    assert (a["rows"], a["generations"], a["max_version_idx"]) == (11, 4, 2)
    md = render_qa(s, {"A": "Agent A"})
    assert "| Agent A | standard | 11 | 4 | 2 |" in md
