"""Fitting windows, populations and their events for module A on the real data (SPEC 5.1, 5.2, 5.4).

Messages. Chat rows of the unified event table: agent messages (kind agent_msg),
human messages (human_msg; run markers typed by staff stay human) and the
auto-nudger's nudges (system_msg with subkind nudge). The bot's daily run
markers are left out.

Realizations (SPEC 5.2). Every run block is one realization on [0, T_d] with
t = 0 at its start. At the stage-0 pause gap (G = 30 min) the blocks are those
of run_periods.parquet; for another G they are rebuilt with
avsd.events.runs.find_blocks from the same rows as stage 0 (agent rows other
than memory snapshots). An agent message lies inside its block. An exogenous
message goes to the first included block of its Pacific date that ends at or
after it, at t = max(0, ts - start): messages posted before a run starts are
placed at t = 0, messages after the last included block of their date are
dropped.

Windows (SPEC 5.4). A goal window holds the realizations that start inside a
village goal (no realization spans a goal boundary in the pinned export); a
rolling window holds the realizations of 5 consecutive run days (1-5, 6-10, ...).

Groups (SPEC 5.1, docs/decisions.md). In each window every room with more than
10% of the window's agent messages is a population fitted on its own, named by
the room: the main room by volume, and best and rest in R2. A group's dimensions
are the agents with a message in its room in the window, its events their
messages in that room, its realizations those with at least one such message,
and its exogenous events the human messages and nudges posted in that room.

Presence (avsd.hawkes.model). An agent is present in a realization of a group
when it has an agent row inside the realization while in the group's room
(events_unified.agent_room_id; rows that agents.PRESENCE_EXCLUDE drops from the
roster do not count). This is roster_daily.active refined to the block and the
room. An agent with a message in the room is always present; on other
realizations it has no baseline and no excitation.

Merge rule for goal windows (SPEC 5.4). Each room's goal windows form a sequence
in goal order; two of them are adjacent when their goals are consecutive. While
a window has fewer than 500 agent messages in its room and an adjacent window,
the one with the fewest messages (the earlier on ties) is merged with its
adjacent window that has fewer messages (the earlier on ties). Windows that fail
the recovery check are merged by the same rule (`merge_units` with `fail`).
Rolling windows are never merged; their groups below 500 messages are listed and
not fitted.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

from avsd.hawkes.model import Day

TZ = "America/Los_Angeles"
EXO = ("human", "system")
MIN_SHARE = 0.10
MIN_MSGS = 500
ROLLING_DAYS = 5
STAGE0_GAP_MIN = 30.0


@dataclass(frozen=True)
class Window:
    """One fitted population: a window (goal or rolling) and a room."""

    kind: str                   # "goal" | "rolling"
    window_id: str              # g12, g35-36 | rd001-005
    group: str                  # room name
    room_id: str
    goals: tuple[int, ...]      # 1-based goal ordinals in start order; () for rolling
    run_days: tuple[int, int]   # first and last run day of the window (all rooms)
    date_start: date            # first and last Pacific run date of the window (inclusive)
    date_end: date
    n_msgs: int                 # agent messages of the group in the window
    share: float                # the group's share of the window's agent messages
    merged: str = ""            # "", "min_msgs", "recovery" or both, why goals were merged

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.window_id}:{self.group}"



@dataclass
class WindowData:
    window: Window
    agent_ids: list[str]        # dimension order (by agent name)
    agent_names: list[str]
    days: list[Day]
    realizations: list[int]     # realization id of each day
    day_dates: list[date]
    run_days: list[int]
    counts: dict = field(default_factory=dict)
    starts: list[float] = field(default_factory=list)  # day start, seconds since the epoch (UTC)
    present: np.ndarray | None = None   # (D, K) presence of each agent on each day (module docstring)

    @property
    def K(self) -> int:
        return len(self.agent_ids)

    @property
    def n_dates(self) -> int:
        """Distinct run dates (a date with an off-schedule extra block has two realizations)."""
        return len(set(self.day_dates))

    def clusters(self) -> np.ndarray:
        """(D,) run-date index of each day, the resampling unit of the run-day bootstrap."""
        return np.unique(np.array(self.day_dates, dtype="datetime64[D]"), return_inverse=True)[1].astype(np.int64)

    @property
    def n_events(self) -> int:
        return int(sum(d.agent_times.size for d in self.days))


def window_id(kind: str, lo: int, hi: int) -> str:
    if kind == "goal":
        return f"g{lo:02d}" if lo == hi else f"g{lo:02d}-{hi:02d}"
    return f"rd{lo:03d}-{hi:03d}"


# --- inputs --------------------------------------------------------------------------------


def load_goals(tables: Path) -> pl.DataFrame:
    """Village goals in start order: goal (1-based ordinal), start_time, end_time."""
    g = pl.read_parquet(Path(tables) / "village_goals.parquet", columns=["start_time", "end_time"])
    return g.sort("start_time").with_row_index("goal", offset=1).with_columns(pl.col("goal").cast(pl.Int32))


def load_messages(processed: Path, tables: Path) -> pl.DataFrame:
    """event_uid, kind (agent | human | system), ts_utc, date (PT), actor_id, room_id, room."""
    rooms = pl.read_parquet(Path(tables) / "chat_rooms.parquet", columns=["id", "name"])
    m = (
        pl.scan_parquet(Path(processed) / "events_unified.parquet")
        .filter((pl.col("source") == "chat")
                & ((pl.col("kind").is_in(["agent_msg", "human_msg"]))
                   | ((pl.col("kind") == "system_msg") & (pl.col("subkind") == "nudge"))))
        .select("event_uid", "kind", "ts_utc", "actor_id", "room_id")
        .collect()
    )
    kind = (pl.when(pl.col("kind") == "agent_msg").then(pl.lit("agent"))
            .when(pl.col("kind") == "human_msg").then(pl.lit("human")).otherwise(pl.lit("system")))
    return (
        m.with_columns(kind.alias("kind"), pl.col("ts_utc").dt.convert_time_zone(TZ).dt.date().alias("date"))
        .join(rooms.rename({"id": "room_id", "name": "room"}), on="room_id", how="left")
        .with_columns(pl.col("room").fill_null(pl.col("room_id")))
        .sort("ts_utc", "event_uid")
    )


def load_blocks(processed: Path, goals: pl.DataFrame, gap_min: float = STAGE0_GAP_MIN) -> pl.DataFrame:
    """Realizations: realization_id, date, run_day, start, end, goal (ordinal of the goal it starts in).
    gap_min other than 30 rebuilds the blocks from the stage-0 agent rows with find_blocks."""
    processed = Path(processed)
    if gap_min == STAGE0_GAP_MIN:
        b = pl.read_parquet(processed / "run_periods.parquet",
                            columns=["realization_id", "date", "run_day", "start", "end"])
    else:
        from avsd.events.runs import find_blocks

        rows = (pl.scan_parquet(processed / "events_unified.parquet")
                .filter((pl.col("actor_type") == "agent") & (pl.col("source") != "memory"))
                .select(pl.col("ts_pt").dt.date().alias("date"), "ts_utc").collect())
        b = find_blocks(rows, gap_min * 60.0, TZ)[0].select("realization_id", "date", "run_day", "start", "end")
    b = b.sort("start").join_asof(goals.select(pl.col("start_time").alias("_gs"), "goal"),
                                  left_on="start", right_on="_gs", strategy="backward").drop("_gs")
    return b.with_columns(pl.col("goal").fill_null(1).cast(pl.Int32))


def load_presence(processed: Path, blocks: pl.DataFrame) -> pl.DataFrame:
    """realization_id, actor_id, room_id: agents with an agent row inside each realization, by the
    room they were in (module docstring)."""
    from avsd.events.agents import presence_excluded

    processed = Path(processed)
    meta = pl.read_parquet(processed / "agents.parquet", columns=["agent_id", "name"])
    rows = (pl.scan_parquet(processed / "events_unified.parquet")
            .filter(pl.col("actor_type") == "agent")
            .select("actor_id", "ts_utc", pl.col("agent_room_id").alias("room_id"),
                    pl.col("ts_pt").dt.date().alias("date"))
            .collect())
    rows = rows.filter(~presence_excluded(pl.col("actor_id"), pl.col("date"), meta)).sort("ts_utc")
    b = blocks.sort("start").select("date", "start", "end", "realization_id")
    out = rows.join_asof(b, left_on="ts_utc", right_on="start", by="date", strategy="backward",
                         check_sortedness=False)
    out = out.filter(pl.col("realization_id").is_not_null() & (pl.col("ts_utc") <= pl.col("end")))
    return out.select("realization_id", "actor_id", "room_id").unique().sort("realization_id", "actor_id", "room_id")


def attach_agent_messages(msgs: pl.DataFrame, blocks: pl.DataFrame) -> pl.DataFrame:
    """Agent messages with realization_id, run_day and goal of the block that contains them."""
    a = msgs.filter(pl.col("kind") == "agent").sort("ts_utc")
    b = blocks.sort("start").select("date", "start", "end", "realization_id", "run_day", "goal")
    out = a.join_asof(b, left_on="ts_utc", right_on="start", by="date", strategy="backward", check_sortedness=False)
    bad = out.filter(pl.col("realization_id").is_null() | (pl.col("ts_utc") > pl.col("end")))
    if bad.height:
        raise ValueError(f"{bad.height} agent messages lie outside every run block")
    return out.drop("start", "end")


# --- windows and groups -------------------------------------------------------------------


@dataclass(frozen=True)
class _Unit:
    room: str
    lo: int     # first and last goal ordinal (goal) or rolling block index
    hi: int
    n: int
    reason: str = ""


def _groups(agent_msgs: pl.DataFrame, unit_col: str, min_share: float = MIN_SHARE) -> pl.DataFrame:
    """unit, room, room_id, n, share for rooms above min_share of their unit's agent messages."""
    tot = agent_msgs.group_by(unit_col).agg(pl.len().alias("tot"))
    return (
        agent_msgs.group_by(unit_col, "room", "room_id").agg(pl.len().alias("n"))
        .join(tot, on=unit_col)
        .with_columns((pl.col("n") / pl.col("tot")).alias("share"))
        .filter(pl.col("share") > min_share)
        .sort(unit_col, "n", descending=[False, True])
    )


def merge_units(units: list[_Unit], min_msgs: int = MIN_MSGS, fail: set[tuple[int, int]] | None = None,
                reason: str = "min_msgs") -> list[_Unit]:
    """The merge rule (module docstring) on one room's units. Without `fail`, units below min_msgs
    are merged until none of them has an adjacent unit. With `fail` (the (lo, hi) of failing
    units) one round runs: failing units, fewest messages first, each merge with their adjacent
    unit that has fewer messages; a unit made by a merge in this round takes no second merge
    (it is checked again first). Ties go to the earlier unit."""
    units = sorted(units, key=lambda u: u.lo)
    locked: set[tuple[int, int]] = set()

    def adjacent(i: int) -> list[int]:
        return [j for j in (i - 1, i + 1) if 0 <= j < len(units) and (units[j].lo, units[j].hi) not in locked
                and (units[j].hi + 1 == units[i].lo or units[i].hi + 1 == units[j].lo)]

    def order(k: int) -> tuple[int, int]:
        return units[k].n, units[k].lo

    def merge(i: int, j: int) -> None:
        a, b = sorted((units[i], units[j]), key=lambda u: u.lo)
        why = ",".join(sorted({*a.reason.split(","), *b.reason.split(","), reason} - {""}))
        units[min(i, j)] = _Unit(a.room, a.lo, b.hi, a.n + b.n, why)
        del units[max(i, j)]
        if fail is not None:
            locked.add((a.lo, b.hi))

    pending = set(fail) if fail is not None else set()
    while True:
        if fail is None:
            cand = [i for i, u in enumerate(units) if u.n < min_msgs and adjacent(i)]
        else:
            cand = [i for i, u in enumerate(units) if (u.lo, u.hi) in pending and adjacent(i)]
        if not cand:
            return units
        i = min(cand, key=order)
        j = min(adjacent(i), key=order)
        pending -= {(units[i].lo, units[i].hi), (units[j].lo, units[j].hi)}
        merge(i, j)


def goal_windows(agent_msgs: pl.DataFrame, blocks: pl.DataFrame, min_msgs: int = MIN_MSGS,
                 min_share: float = MIN_SHARE) -> list[Window]:
    """Goal windows per room after the 500-message merge (module docstring)."""
    groups = _groups(agent_msgs, "goal", min_share)
    units = [_Unit(r["room"], r["goal"], r["goal"], r["n"]) for r in groups.iter_rows(named=True)]
    out = []
    for room in sorted({u.room for u in units}):
        out += merge_units([u for u in units if u.room == room], min_msgs)
    return [_goal_window(u, agent_msgs, blocks) for u in sorted(out, key=lambda u: (u.lo, u.room))]


def _goal_window(u: _Unit, agent_msgs: pl.DataFrame, blocks: pl.DataFrame) -> Window:
    b = blocks.filter(pl.col("goal").is_between(u.lo, u.hi))
    a = agent_msgs.filter(pl.col("goal").is_between(u.lo, u.hi))
    room = a.filter(pl.col("room") == u.room)
    return Window("goal", window_id("goal", u.lo, u.hi), u.room, room["room_id"][0], tuple(range(u.lo, u.hi + 1)),
                  (int(b["run_day"].min()), int(b["run_day"].max())), b["date"].min(), b["date"].max(),
                  room.height, room.height / max(a.height, 1), u.reason)


def remerge_goal_windows(windows: list[Window], failed: set[str], agent_msgs: pl.DataFrame,
                         blocks: pl.DataFrame) -> list[Window]:
    """One merge round (merge_units with fail) for the goal windows whose keys are in `failed`;
    windows that are not merged are returned unchanged."""
    out: list[Window] = []
    for room in sorted({w.group for w in windows}):
        mine = [w for w in windows if w.group == room]
        fail = {(w.goals[0], w.goals[-1]) for w in mine if w.key in failed}
        if not fail:
            out += mine
            continue
        units = merge_units([_Unit(room, w.goals[0], w.goals[-1], w.n_msgs, w.merged) for w in mine],
                            fail=fail, reason="recovery")
        old = {(w.goals[0], w.goals[-1]): w for w in mine}
        out += [old.get((u.lo, u.hi)) or _goal_window(u, agent_msgs, blocks) for u in units]
    return sorted(out, key=lambda w: (w.goals[0], w.group))


def rolling_windows(agent_msgs: pl.DataFrame, blocks: pl.DataFrame, days: int = ROLLING_DAYS,
                    min_share: float = MIN_SHARE) -> list[Window]:
    """Blocks of `days` run days from run day 1 (the last may be shorter); one Window per room above
    min_share (all listed; the pipeline fits those with at least MIN_MSGS messages)."""
    a = agent_msgs.with_columns(((pl.col("run_day") - 1) // days).alias("block"))
    out = []
    for r in _groups(a, "block", min_share).iter_rows(named=True):
        b = blocks.filter(pl.col("run_day").is_between(r["block"] * days + 1, (r["block"] + 1) * days))
        lo, hi = int(b["run_day"].min()), int(b["run_day"].max())
        out.append(Window("rolling", window_id("rolling", lo, hi), r["room"], r["room_id"], (), (lo, hi),
                          b["date"].min(), b["date"].max(), r["n"], r["share"]))
    return sorted(out, key=lambda w: (w.run_days[0], w.group))


# --- events of one window --------------------------------------------------------------------


def window_data(w: Window, msgs: pl.DataFrame, agent_msgs: pl.DataFrame, blocks: pl.DataFrame,
                names: dict[str, str], presence: pl.DataFrame | None = None) -> WindowData:
    """Days of one window and group (module docstring). `agent_msgs` from attach_agent_messages
    with the same blocks; `presence` from load_presence on them (None: every agent present on every
    day)."""
    if w.kind == "goal":
        in_win = pl.col("goal").is_between(w.goals[0], w.goals[-1])
    else:
        in_win = pl.col("run_day").is_between(*w.run_days)
    a = agent_msgs.filter(in_win & (pl.col("room_id") == w.room_id))
    rids = a["realization_id"].unique()
    b = blocks.filter(pl.col("realization_id").is_in(rids.implode())).sort("start")
    ids = sorted(a["actor_id"].unique().to_list(), key=lambda i: (names.get(i, i), i))
    dim = {x: k for k, x in enumerate(ids)}
    x = msgs.filter((pl.col("kind") != "agent") & (pl.col("room_id") == w.room_id)
                    & pl.col("date").is_in(b["date"].unique().implode())).sort("ts_utc")
    x = x.join_asof(b.select("date", pl.col("end").alias("_end"), "realization_id", "start").sort("_end"),
                    left_on="ts_utc", right_on="_end", by="date", strategy="forward", check_sortedness=False)
    counts = {"dropped_after_run": int(x["realization_id"].null_count())}
    x = x.drop_nulls("realization_id")
    counts["clipped_to_start"] = int((x["ts_utc"] < x["start"]).sum())
    secs = (pl.col("ts_utc") - pl.col("start")).dt.total_microseconds() / 1e6
    a = a.join(b.select("realization_id", "start"), on="realization_id").with_columns(secs.alias("t"))
    x = x.with_columns(secs.clip(lower_bound=0.0).alias("t"))
    rid_list = b["realization_id"].to_list()
    present = np.ones((len(rid_list), len(ids)), bool)
    if presence is not None:
        p = presence.filter((pl.col("room_id") == w.room_id) & pl.col("realization_id").is_in(rids.implode()))
        on = set(p.select("realization_id", "actor_id").iter_rows())
        present = np.array([[(rid, i) in on for i in ids] for rid in rid_list], dtype=bool).reshape(present.shape)
    days = []
    a_parts = a.sort("ts_utc", "event_uid").partition_by("realization_id", as_dict=True)
    x_parts = x.sort("ts_utc", "event_uid").partition_by("realization_id", as_dict=True)
    empty = x.clear()
    for k, r in enumerate(b.iter_rows(named=True)):
        T = (r["end"] - r["start"]).total_seconds()
        ar = a_parts[(r["realization_id"],)]
        xr = x_parts.get((r["realization_id"],), empty)
        exo_t, exo_u = [], []
        for src in EXO:
            s = xr.filter(pl.col("kind") == src)
            exo_t.append(np.minimum(s["t"].to_numpy(), T)), exo_u.append(np.asarray(s["event_uid"].to_list(), object))
        dims = np.array([dim[i] for i in ar["actor_id"]], np.int64)
        present[k, dims] = True                  # an agent with a message in the room is present
        days.append(Day(T, np.minimum(ar["t"].to_numpy(), T), dims,
                        agent_uids=np.asarray(ar["event_uid"].to_list(), object),
                        exo_times=tuple(exo_t), exo_uids=tuple(exo_u), present=present[k].copy()))
    counts.update({src: int(sum(d.exo_times[h].size for d in days)) for h, src in enumerate(EXO)})
    starts = (b["start"].dt.epoch("us") / 1e6).to_list()
    return WindowData(w, ids, [names.get(i, i) for i in ids], days, rid_list,
                      b["date"].to_list(), b["run_day"].to_list(), counts, starts, present)


@dataclass
class Inputs:
    """Everything the windows need, loaded once per pause gap G. The thresholds come from the
    hawkes section of the config (min_agent_msgs_per_window, min_room_share, rolling_window_run_days)."""

    msgs: pl.DataFrame
    goals: pl.DataFrame
    blocks: pl.DataFrame
    agent_msgs: pl.DataFrame
    names: dict[str, str]
    gap_min: float = STAGE0_GAP_MIN
    min_msgs: int = MIN_MSGS
    min_share: float = MIN_SHARE
    rolling_days: int = ROLLING_DAYS
    presence: pl.DataFrame | None = None

    @classmethod
    def load(cls, cfg: dict, gap_min: float = STAGE0_GAP_MIN, msgs: pl.DataFrame | None = None) -> Inputs:
        processed, tables = Path(cfg["paths"]["processed"]), Path(cfg["paths"]["tables"])
        h = cfg.get("hawkes", {})
        goals = load_goals(tables)
        msgs = load_messages(processed, tables) if msgs is None else msgs
        blocks = load_blocks(processed, goals, gap_min)
        names = dict(pl.read_parquet(processed / "agents.parquet", columns=["agent_id", "name"]).iter_rows())
        return cls(msgs, goals, blocks, attach_agent_messages(msgs, blocks), names, gap_min,
                   int(h.get("min_agent_msgs_per_window", MIN_MSGS)), float(h.get("min_room_share", MIN_SHARE)),
                   int(h.get("rolling_window_run_days", ROLLING_DAYS)), load_presence(processed, blocks))

    def data(self, w: Window) -> WindowData:
        return window_data(w, self.msgs, self.agent_msgs, self.blocks, self.names, self.presence)

    def goal_windows(self) -> list[Window]:
        return goal_windows(self.agent_msgs, self.blocks, self.min_msgs, self.min_share)

    def rolling_windows(self) -> list[Window]:
        return rolling_windows(self.agent_msgs, self.blocks, self.rolling_days, self.min_share)

    def same_window(self, w: Window) -> Window:
        """w with run days and dates recomputed on these blocks (for another G)."""
        if w.kind == "goal":
            b = self.blocks.filter(pl.col("goal").is_between(w.goals[0], w.goals[-1]))
        else:
            b = self.blocks.filter(pl.col("run_day").is_between(*w.run_days))
        return replace(w, run_days=(int(b["run_day"].min()), int(b["run_day"].max())),
                       date_start=b["date"].min(), date_end=b["date"].max())
