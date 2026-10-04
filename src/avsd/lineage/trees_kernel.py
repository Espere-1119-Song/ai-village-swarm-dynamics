"""Time terms K_ij of the module B2 parent posterior (SPEC 6.4.3, 11).

A candidate edge j -> i has a kernel key (the channel by which the child could
have the information, the child's source and whether parent and child are the
same agent, `KEYS`) and a serial interval dt in active seconds (`t_active`,
SPEC 6.1). K is a density in 1/s, so terms of different keys compare as
likelihoods of the child's time.

`EmpiricalKernel` (default; the SPEC section 11 fallback while module A is not
validated): a Gaussian kernel density estimate of log10(dt) per key, fitted on
the edges whose child has exactly one candidate parent (SPEC 6.4.3: "first
estimated from edges with a single candidate parent"), K(dt) = f(log10 dt) /
(dt ln 10). A key with fewer than `min_edges` such edges uses the pooled edges
of its channel, then all edges. `refit` re-estimates with posterior weights
(optional; off by default).

`HawkesKernel` (hook for module A): the normalized kernels of module A for
same-run-day chat edges,
    g(tau) = sum_m w_m beta_m exp(-beta_m tau) / (1 - exp(-beta_m L)), 0 < tau <= L,
beta = 1/60, 1/600, 1/3600 per second, tau in t_in_day seconds of one run-day
realization. It reads `outputs/tables/hawkes_kernels.parquet` (window_kind,
window_id, group, date_start, date_end, source_class in self/other/human/system,
w_1m, w_10m, w_1h, L_s, expected_children, identified). An edge uses g when it
is a chat-to-chat edge with an agent child in the same realization, a goal
window matches the child's room and PT date together (group = the room's name
and date_start <= date <= date_end; goal windows of different rooms overlap in
dates) and the row for the edge's source class is identified
(expected_children >= 50). Everything else falls back to the empirical kernel:
cross-day edges, rooms and dates without a window, unidentified rows and
tau > L. `HawkesKernel.used` counts the edges of each branch, and
`window_table` counts chat edges by window.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

KEYS: tuple[str, ...] = (
    "chat>chat:other", "chat>chat:self", "chat>human", "chat>memory:other", "chat>memory:self",
    "memory>chat", "search>chat", "search>memory", "history>search", "env>chat", "env>memory",
)
KEY_CODE: dict[str, int] = {k: i for i, k in enumerate(KEYS)}
CHANNEL_OF_KEY: tuple[str, ...] = tuple(k.split(">")[0] for k in KEYS)
CHANNELS: tuple[str, ...] = ("chat", "memory", "search", "history", "env")
SOURCE_CLASSES: tuple[str, ...] = ("self", "other", "human", "system")
HAWKES_BETAS = (1 / 60, 1 / 600, 1 / 3600)
LOG_LO, LOG_HI, GRID = 0.0, 7.5, 1501  # log10 seconds: 1 s to about 1 year of active time
MIN_DT = 1.0
FLOOR = 1e-12


@dataclass
class EdgeTimes:
    """Candidate edges for a time term (one entry per edge)."""

    key: np.ndarray  # int8 KEY_CODE
    dt: np.ndarray  # float64 active seconds, child minus parent
    same_block: np.ndarray | None = None  # bool: same run-day realization
    tau: np.ndarray | None = None  # float64 t_in_day difference (s)
    source_class: np.ndarray | None = None  # int8 index into SOURCE_CLASSES, -1 if not a chat parent
    room: np.ndarray | None = None  # object: the child's room id
    child_date: np.ndarray | None = None  # datetime64[D]: the child's PT date

    def subset(self, m: np.ndarray) -> "EdgeTimes":
        return EdgeTimes(*(None if v is None else v[m] for v in
                           (self.key, self.dt, self.same_block, self.tau, self.source_class, self.room,
                            self.child_date)))


def _kde_grid(logdt: np.ndarray, weights: np.ndarray | None, max_points: int, rng: np.random.Generator
              ) -> np.ndarray:
    from scipy import stats

    x = np.asarray(logdt, dtype=float)
    w = None if weights is None else np.asarray(weights, dtype=float)
    if len(x) > max_points:
        p = None if w is None else w / w.sum()
        idx = rng.choice(len(x), size=max_points, replace=False, p=p)
        x, w = x[idx], None
    grid = np.linspace(LOG_LO, LOG_HI, GRID)
    if len(np.unique(x)) < 2:
        x = x + rng.normal(0, 0.05, size=len(x))
    kde = stats.gaussian_kde(x, weights=w)
    f = kde(grid)
    # Mass outside [LOG_LO, LOG_HI] is folded back so that the density integrates to about 1.
    area = np.trapezoid(f, grid)
    return np.maximum(f / max(area, FLOOR), FLOOR)


@dataclass
class EmpiricalKernel:
    """KDE of log10 serial intervals per kernel key (see the module docstring)."""

    min_edges: int = 50
    max_points: int = 20000
    seed: int = 20261003
    grids: dict[int, np.ndarray] = field(default_factory=dict)
    info: dict[int, dict] = field(default_factory=dict)

    def fit(self, key: np.ndarray, dt: np.ndarray, weights: np.ndarray | None = None) -> "EmpiricalKernel":
        rng = np.random.default_rng(self.seed)
        key = np.asarray(key, dtype=np.int64)
        ld = np.log10(np.maximum(np.asarray(dt, dtype=float), MIN_DT))
        w = None if weights is None else np.asarray(weights, dtype=float)
        ok = np.isfinite(ld) & (w > 0 if w is not None else True)
        key, ld = key[ok], ld[ok]
        w = None if w is None else w[ok]
        chan = np.array([CHANNELS.index(CHANNEL_OF_KEY[k]) for k in key], dtype=np.int64) if len(key) else key

        def eff(m):
            return float(m.sum()) if w is None else float(w[m].sum())

        pooled_all = None
        for k in range(len(KEYS)):
            m = key == k
            n_own = int(m.sum())
            src = "own"
            if eff(m) < self.min_edges:
                c = CHANNELS.index(CHANNEL_OF_KEY[k])
                m = chan == c
                src = "channel"
                if eff(m) < self.min_edges:
                    m = np.ones(len(key), dtype=bool)
                    src = "all"
            if not m.any():
                self.grids[k] = np.full(GRID, 1.0 / (LOG_HI - LOG_LO))
                self.info[k] = {"key": KEYS[k], "n_single": n_own, "fit_on": "uniform", "n_fit": 0}
                continue
            if src == "all" and pooled_all is not None:
                g = pooled_all
            else:
                g = _kde_grid(ld[m], None if w is None else w[m], self.max_points, rng)
                if src == "all":
                    pooled_all = g
            self.grids[k] = g
            q = np.quantile(10 ** ld[m], [0.25, 0.5, 0.75]) if m.any() else [np.nan] * 3
            self.info[k] = {"key": KEYS[k], "n_single": n_own, "fit_on": src, "n_fit": int(m.sum()),
                            "dt_q25_h": q[0] / 3600, "dt_median_h": q[1] / 3600, "dt_q75_h": q[2] / 3600}
        return self

    def density(self, e: EdgeTimes) -> np.ndarray:
        dt = np.maximum(np.asarray(e.dt, dtype=float), MIN_DT)
        ld = np.log10(dt)
        out = np.empty(len(dt), dtype=float)
        grid = np.linspace(LOG_LO, LOG_HI, GRID)
        for k in np.unique(e.key):
            m = e.key == k
            out[m] = np.interp(ld[m], grid, self.grids[int(k)], left=self.grids[int(k)][0],
                               right=FLOOR) / (dt[m] * np.log(10))
        return np.maximum(out, FLOOR * 1e-6)

    __call__ = density

    def sample(self, key: int, n: int, rng: np.random.Generator) -> np.ndarray:
        """Intervals (active seconds) drawn from the fitted density of a key (synthetic runs)."""
        grid = np.linspace(LOG_LO, LOG_HI, GRID)
        f = self.grids[int(key)]
        cdf = np.cumsum(f)
        cdf /= cdf[-1]
        u = rng.random(n)
        x = np.interp(u, cdf, grid) + rng.uniform(-0.5, 0.5, n) * (grid[1] - grid[0])
        return 10 ** x


def hawkes_g(tau: np.ndarray, w: np.ndarray, L: float, betas=HAWKES_BETAS) -> np.ndarray:
    """Module A's normalized kernel on (0, L] (0 outside)."""
    tau = np.asarray(tau, dtype=float)
    out = np.zeros_like(tau)
    ok = (tau > 0) & (tau <= L)
    for wm, b in zip(w, betas):
        out[ok] += wm * b * np.exp(-b * tau[ok]) / (1 - np.exp(-b * L))
    return out


class HawkesKernel:
    """Module A kernels for same-run-day chat edges, the empirical kernel for the rest.

    A chat-to-chat edge finds its goal window by the child's room and PT date together: the row whose group is
    the room's name and whose dates contain the child's date (goal windows of different rooms overlap in dates,
    for example the best and rest rooms in 2026). After `density`, `last` holds each edge's branch (an index
    into BRANCHES), its window (an index into `windows`, -1 for none) and its room (an index into `rooms`)."""

    CHAT_KEYS = (KEY_CODE["chat>chat:other"], KEY_CODE["chat>chat:self"])
    BRANCHES = ("hawkes", "kde_not_chat", "kde_cross_day", "kde_no_window", "kde_not_identified", "kde_beyond_L")

    def __init__(self, table, fallback: EmpiricalKernel, room_name: dict[str, str]):
        """table: rows of hawkes_kernels.parquet (polars DataFrame); room_name: room id -> room name (module A's
        group of a goal window is the name of its room, the room id when the room has no name)."""
        rows = table.filter(table["window_kind"] == "goal") if "window_kind" in table.columns else table
        self.rows: dict[tuple[str, str, str], tuple[np.ndarray, float, bool]] = {}
        wins = set()
        for r in rows.iter_rows(named=True):
            wid, grp = str(r["window_id"]), str(r["group"])
            L = r.get("L_s")
            self.rows[(wid, grp, str(r["source_class"]))] = (
                np.array([r["w_1m"], r["w_10m"], r["w_1h"]], dtype=float), float(L) if L else 10800.0,
                bool(r["identified"]))
            wins.add((grp, np.datetime64(r["date_start"], "D"), np.datetime64(r["date_end"], "D"), wid))
        # (group, first date, last date, window id), sorted by group and start.
        self.windows: list[tuple[str, np.datetime64, np.datetime64, str]] = sorted(wins)
        self.fallback = fallback
        self.room_name = {k: (v if v else k) for k, v in room_name.items()}
        self.rooms: list[str] = []
        self.used = {b: 0 for b in self.BRANCHES}
        self.last: dict[str, np.ndarray] | None = None

    @classmethod
    def from_file(cls, path: str | Path, fallback: EmpiricalKernel, room_name: dict[str, str]):
        """None when module A has not written the file yet."""
        import polars as pl

        path = Path(path)
        if not path.exists():
            return None
        table = pl.read_parquet(path)
        need = {"window_id", "group", "date_start", "date_end", "source_class", "w_1m", "w_10m", "w_1h",
                "identified"}
        if not need <= set(table.columns):
            raise ValueError(f"{path} lacks columns {sorted(need - set(table.columns))}")
        return cls(table, fallback, room_name)

    def window_of(self, group: str, d: np.datetime64) -> int:
        """Index into `windows` of the goal window of room `group` that contains date d (the latest start if
        several do), -1 for none."""
        best = -1
        for k, (g, lo, hi, _) in enumerate(self.windows):
            if g == group and lo <= d <= hi and (best < 0 or lo > self.windows[best][1]):
                best = k
        return best

    def density(self, e: EdgeTimes) -> np.ndarray:
        out = self.fallback.density(e)
        n = len(out)
        branch = np.full(n, self.BRANCHES.index("kde_not_chat"), dtype=np.int8)
        window = np.full(n, -1, dtype=np.int16)
        room = np.full(n, -1, dtype=np.int16)
        self.last = {"branch": branch, "window": window, "room": room}
        if e.same_block is None or e.source_class is None or e.child_date is None or e.room is None:
            self.used["kde_not_chat"] += n
            return out
        idx = np.flatnonzero(np.isin(e.key, self.CHAT_KEYS) & (e.source_class >= 0))
        if len(idx):
            r_u, r_inv = np.unique(np.array([("" if r is None else str(r)) for r in e.room[idx].tolist()],
                                            dtype=object).astype(str), return_inverse=True)
            names_u = [self.room_name.get(r, r) for r in r_u.tolist()]
            for nm in names_u:
                if nm not in self.rooms:
                    self.rooms.append(nm)
            rid = np.array([self.rooms.index(nm) for nm in names_u], dtype=np.int16)[r_inv]
            d = np.asarray(e.child_date[idx], dtype="datetime64[D]").astype(np.int64)
            d0 = int(d.min())
            span = int(d.max()) - d0 + 1
            pair_u, p_inv = np.unique(r_inv.astype(np.int64) * span + (d - d0), return_inverse=True)
            win_u = np.array([self.window_of(names_u[int(k) // span], np.datetime64(d0 + int(k) % span, "D"))
                              if names_u[int(k) // span] else -1 for k in pair_u.tolist()], dtype=np.int16)
            win = win_u[p_inv]
            window[idx], room[idx] = win, rid
            same = e.same_block[idx].astype(bool)
            branch[idx[~same]] = self.BRANCHES.index("kde_cross_day")
            m = same & (win < 0)
            branch[idx[m]] = self.BRANCHES.index("kde_no_window")
            cls_ = e.source_class[idx].astype(np.int64)
            tau = np.asarray(e.tau[idx], dtype=float)
            for k in np.unique(win[same & (win >= 0)]).tolist():
                grp, _, _, wid = self.windows[k]
                for c in np.unique(cls_[same & (win == k)]).tolist():
                    qs = np.flatnonzero(same & (win == k) & (cls_ == c))
                    row = self.rows.get((wid, grp, SOURCE_CLASSES[c]))
                    if row is None or not row[2]:
                        branch[idx[qs]] = self.BRANCHES.index("kde_not_identified")
                        continue
                    w, L, _ = row
                    t = tau[qs]
                    inside = (t > 0) & (t <= L)
                    branch[idx[qs[~inside]]] = self.BRANCHES.index("kde_beyond_L")
                    hit = idx[qs[inside]]
                    branch[hit] = self.BRANCHES.index("hawkes")
                    out[hit] = np.maximum(hawkes_g(t[inside], w, L), FLOOR * 1e-6)
        cnt = np.bincount(branch, minlength=len(self.BRANCHES))
        for b, v in zip(self.BRANCHES, cnt.tolist()):
            self.used[b] += int(v)
        return out

    __call__ = density

    def window_table(self, last: dict[str, np.ndarray], mask: np.ndarray | None = None, scope: str = "") -> list[dict]:
        """Chat-to-chat edges by goal window (window_id "none" with the room name: no window of that room on
        the child's date), with the time term each used, and a total row (window_id "all")."""
        br, win, room = last["branch"], last["window"], last["room"]
        if mask is not None:
            br, win, room = br[mask], win[mask], room[mask]
        chat = br != self.BRANCHES.index("kde_not_chat")
        cols = ("hawkes", "kde_cross_day", "kde_no_window", "kde_not_identified", "kde_beyond_L")

        def row(m, **kv):
            r = {"scope": scope, **kv, "n_chat_edges": int(m.sum())}
            for b in cols:
                r[b] = int((m & (br == self.BRANCHES.index(b))).sum())
            r["share_hawkes"] = r["hawkes"] / r["n_chat_edges"] if r["n_chat_edges"] else float("nan")
            return r

        out = []
        for k, (grp, lo, hi, wid) in enumerate(self.windows):
            m = chat & (win == k)
            ident = sorted(c for (w_, g_, c), v in self.rows.items() if w_ == wid and g_ == grp and v[2])
            out.append(row(m, window_id=wid, group=grp, date_start=str(lo), date_end=str(hi),
                           identified_classes=",".join(ident)))
        for j, nm in enumerate(self.rooms):
            m = chat & (win < 0) & (room == j)
            if m.any():
                out.append(row(m, window_id="none", group=nm, date_start="", date_end="", identified_classes=""))
        tot = row(chat, window_id="all", group="all", date_start="", date_end="", identified_classes="")
        tot["n_edges_all_keys"] = int(len(br))
        out.append(tot)
        return out
