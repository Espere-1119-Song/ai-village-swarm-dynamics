"""Module A on the real data: `avsd hawkes fit --window goal|rolling` (SPEC 5).

Windows, populations, events and presence follow avsd.hawkes.windows. Every fit uses
kernel_sharing="class" (the owner's choice), the exogenous sources human and system, the fixed
betas, L = 3 h, 8 hourly baseline bins, l1 = 0, per-agent presence (an agent's exposure counts only
on the realizations it is present), three starts and the Newton-certified stopping rule
(docs/decisions.md). Stages, each resumable (results under <paths.interim>/hawkes_fit/):

accept   goal windows: fit, recovery_check on mae4 with 20 replicates (SPEC 5.6-1; 20 more when
         the mean is within 2 standard errors of the bar), and merge rounds (windows.merge_units)
         until every window passes or has no neighbour left
boot     run-day bootstrap of every final goal window: 1,000 replicates drawn by run date, each
         fitted from fit()'s three starts and from the full-data fit, keeping the best
         (avsd.hawkes.bootstrap)
matched  matched-truth arms of every final goal window (avsd.hawkes.matched)
sens     L in {1, 6} h at G = 30 min, G in {15, 60} min at L = 3 h, and the variant that ties
         exogenous shapes resting on fewer than 50 expected children to the other-agent shape
valid    time-rescaling (pool="concat"), tier-1 explicit-reference check, action-opportunity model
rolling  rolling windows (5 run days) with at least 500 agent messages in the group
assemble outputs (avsd.hawkes.report)

Stages other than accept and assemble run in shards (--shard i/n), so several jobs can share
them: `python -m avsd.hawkes.pipeline <stage> [--shard i/n] [--workers w] [--reverse]`. --reverse walks
a shard's tasks from the end, so a second job can help a slow one (finished tasks are skipped; results
do not depend on the order). Worker processes are
spawned, not forked: polars, which builds each window's events, can deadlock in a forked child.
Every task gets the config and its settings as arguments and loads what it needs once per process.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import argparse
import os
import pickle
import time
import zlib
from dataclasses import dataclass, field, replace
from multiprocessing import get_context
from pathlib import Path

import numpy as np
import polars as pl
from numba import njit

from avsd.config import load_config
from avsd.hawkes.bootstrap import BootstrapResult, bootstrap_reps
from avsd.hawkes.gof import time_rescaling
from avsd.hawkes.matched import ARMS, arm_truth, run_replicate
from avsd.hawkes.model import HawkesFit, HawkesSpec, Packed, _posterior, decompose, fit, pack, spectral_radius
from avsd.hawkes.validate import Recovery, explosion_caps, pool_exogenous, recovery_check
from avsd.hawkes.windows import EXO, STAGE0_GAP_MIN, Inputs, Window, WindowData, remerge_goal_windows

# Defaults; apply_settings() replaces them from the hawkes section of the config in the driver and
# in every worker process.
SEED = 20261003
BAR = 0.05                 # SPEC 5.6-1, on mae4
N_REC = 20                 # recovery replicates per window
N_REC_EXTRA = 20           # more replicates when the mean mae4 is within BORDER_SE standard errors of BAR
BORDER_SE = 2.0
CORE_PRESENCE = 0.8        # "core" agents: present on at least this share of a window's realizations
N_BOOT = 1000
MATCHED_REPS = 8
IDENTIFIED = 50.0          # expected children a class shape needs (docs/decisions.md)
MIN_MSGS = 500
PARENT_MIN = 0.01
L_HOURS = (1.0, 6.0)
G_MIN = (15.0, 60.0)
QQ_PROBS = np.linspace(0.005, 0.995, 100)
STAGES = ("accept", "boot", "matched", "sens", "valid", "rolling", "assemble")


def sens_variants() -> tuple[str, ...]:
    return tuple(f"L{x:g}" for x in L_HOURS) + tuple(f"G{x:g}" for x in G_MIN) + ("tie",)


_DEFAULTS = {"SEED": SEED, "BAR": BAR, "N_REC": N_REC, "N_REC_EXTRA": N_REC_EXTRA, "BORDER_SE": BORDER_SE,
             "CORE_PRESENCE": CORE_PRESENCE, "N_BOOT": N_BOOT, "MATCHED_REPS": MATCHED_REPS,
             "IDENTIFIED": IDENTIFIED, "MIN_MSGS": MIN_MSGS, "PARENT_MIN": PARENT_MIN, "L_HOURS": L_HOURS,
             "G_MIN": G_MIN}


def apply_settings(cfg: dict) -> None:
    """Module settings from cfg["hawkes"] (configs/default.yaml) and cfg["seed"]; a key the config
    leaves out takes its default."""
    global SEED, BAR, N_REC, N_REC_EXTRA, BORDER_SE, CORE_PRESENCE, N_BOOT, MATCHED_REPS, IDENTIFIED, MIN_MSGS
    global PARENT_MIN, L_HOURS, G_MIN
    h, d = cfg.get("hawkes", {}), _DEFAULTS
    if h.get("kernel_sharing", "class") != "class" or float(h.get("l1", 0.0)) != 0.0:
        raise ValueError("the real-data pipeline fits kernel_sharing='class' with l1 = 0 (docs/decisions.md)")
    SEED = int(cfg.get("seed", d["SEED"]))
    BAR = float(h.get("recovery_bar_mae4", d["BAR"]))
    N_REC = int(h.get("recovery_reps", d["N_REC"]))
    N_REC_EXTRA = int(h.get("recovery_reps_borderline", d["N_REC_EXTRA"]))
    BORDER_SE = float(h.get("recovery_borderline_se", d["BORDER_SE"]))
    CORE_PRESENCE = float(h.get("core_presence", d["CORE_PRESENCE"]))
    N_BOOT = int(h.get("bootstrap_reps", d["N_BOOT"]))
    MATCHED_REPS = int(h.get("matched_reps", d["MATCHED_REPS"]))
    IDENTIFIED = float(h.get("identified_children", d["IDENTIFIED"]))
    MIN_MSGS = int(h.get("min_agent_msgs_per_window", d["MIN_MSGS"]))
    PARENT_MIN = float(h.get("parent_prob_min", d["PARENT_MIN"]))
    L_HOURS = tuple(float(x) for x in h.get("sensitivity_max_lag_hours", d["L_HOURS"]))
    G_MIN = tuple(float(x) for x in h.get("sensitivity_gap_minutes", d["G_MIN"]))


# --- configuration, paths, storage ------------------------------------------------------------


def spec_of(cfg: dict, max_lag_hours: float | None = None) -> HawkesSpec:
    s = HawkesSpec.from_config(cfg)
    return s if max_lag_hours is None else HawkesSpec(s.betas, max_lag_hours * 3600.0, s.n_bins, s.bin_width)


def work_dir(cfg: dict) -> Path:
    """<paths.interim>/hawkes_fit, or hawkes.work_dir when the config sets it."""
    return Path(cfg.get("hawkes", {}).get("work_dir") or Path(cfg["paths"]["interim"]) / "hawkes_fit")


def fname(key: str) -> str:
    return key.replace(":", "__")


def _save(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as fh:
        pickle.dump(obj, fh, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)


class _Unpickler(pickle.Unpickler):
    """Resolves classes of this module that were pickled while it ran as __main__ (python -m)."""

    def find_class(self, module, name):
        if module in ("__main__", "__mp_main__") and name in ("FitResult",):
            return FitResult
        return super().find_class(module, name)


def _load(path: Path):
    with open(path, "rb") as fh:
        return _Unpickler(fh).load()


def window_seed(key: str, salt: str) -> int:
    return int(zlib.crc32(f"{SEED}:{key}:{salt}".encode()))


# --- one fit --------------------------------------------------------------------------------------


@dataclass
class FitResult:
    window: Window
    variant: str                 # base, L1, L6, G15, G60, tie
    agent_ids: list[str]
    agent_names: list[str]
    n_days: int                  # realizations
    hours: float                 # summed day lengths
    counts: dict                 # exogenous events, clipped and dropped rows
    fit: HawkesFit
    shares: np.ndarray           # share_names order (baseline, human, system, other_agents, self)
    by_dim: np.ndarray           # (K, 5)
    events_dim: np.ndarray       # (K,)
    children: np.ndarray         # expected children per kernel class (class_names order)
    src_events: np.ndarray       # (K + H,) events of each source
    secs: float
    day_bounds: list[tuple[float, float]] = field(default_factory=list)  # (start, epoch s; T) per day
    note: str = ""
    present: np.ndarray | None = None   # (n_days, K) presence of each agent on each realization
    n_dates: int = 0                    # distinct run dates

    @property
    def key(self) -> str:
        return self.window.key

    @property
    def K(self) -> int:
        return len(self.agent_ids)

    @property
    def presence(self) -> np.ndarray:
        """(K,) share of the window's realizations on which each agent is present."""
        return self.present.mean(0) if self.present is not None else np.ones(self.K)

    def core(self, share: float | None = None) -> np.ndarray:
        """Agents present on at least `share` (CORE_PRESENCE) of the realizations."""
        return np.flatnonzero(self.presence >= (CORE_PRESENCE if share is None else share))

    def rho_core(self, share: float | None = None) -> float:
        """Spectral radius of N_AA over the core agents (a sensitivity row next to rho)."""
        idx = self.core(share)
        return spectral_radius(self.fit.n[np.ix_(idx, idx)]) if idx.size else float("nan")

    @property
    def n_events(self) -> int:
        return int(round(self.events_dim.sum()))

    @property
    def shares4(self) -> np.ndarray:
        return pool_exogenous(self.shares)

    def identified(self) -> dict[str, bool]:
        return {c: bool(k >= IDENTIFIED) for c, k in zip(self.fit.class_names, self.children)}


def expected_children(f: HawkesFit, pk: Packed) -> tuple[np.ndarray, np.ndarray]:
    """Expected children per kernel class (sum over its cells of n_ij times the events of source j
    on the days target i is present) and the events per source."""
    by_day = pk.source_counts()                          # (D, K + H)
    seen = pk.present.T.astype(np.float64) @ by_day      # (K, K + H)
    kids = np.bincount(f.classes.ravel(), weights=(f.n * seen).ravel(), minlength=len(f.class_names))
    return kids, by_day.sum(0)


def _bounds(d: WindowData) -> list[tuple[float, float]]:
    return [(float(s), float(day.T)) for s, day in zip(d.starts, d.days)]


def fit_window(d: WindowData, spec: HawkesSpec, variant: str = "base", tie_exo: tuple[str, ...] = ()) -> FitResult:
    t0 = time.time()
    pk = pack(d.days, d.K, spec, exo_names=EXO)
    f = fit(pk, d.K, spec, kernel_sharing="class", tie_exo=tie_exo)
    dec = decompose(pk, f, min_prob=1.0)
    kids, src = expected_children(f, pk)
    return FitResult(d.window, variant, d.agent_ids, d.agent_names, len(d.days), float(pk.day_T.sum() / 3600),
                     dict(d.counts), f, np.array(list(dec.shares.values())), dec.by_dim, dec.n_events, kids, src,
                     time.time() - t0, _bounds(d), present=pk.present.copy(), n_dates=d.n_dates)


# --- process-level inputs (loaded once per process) ---------------------------------------------


class _Ctx:
    cfg: dict = {}
    inputs: dict[float, Inputs] = {}
    actions: pl.DataFrame | None = None
    labels: pl.DataFrame | None = None


def _use(cfg: dict) -> None:
    if not _Ctx.cfg:
        _Ctx.cfg = cfg
        apply_settings(cfg)


def ctx_inputs(gap: float = STAGE0_GAP_MIN) -> Inputs:
    if gap not in _Ctx.inputs:
        base = _Ctx.inputs.get(STAGE0_GAP_MIN)
        _Ctx.inputs[gap] = Inputs.load(_Ctx.cfg, gap, msgs=base.msgs if base is not None else None)
    return _Ctx.inputs[gap]


def ctx_valid_inputs() -> tuple[pl.DataFrame, pl.DataFrame]:
    """Tier-1 labels and agent actions (validation 3 and 4)."""
    from avsd.hawkes.opportunity import load_actions

    if _Ctx.labels is None:
        _Ctx.labels = ensure_labels(_Ctx.cfg)
    if _Ctx.actions is None:
        _Ctx.actions = load_actions(_Ctx.cfg["paths"]["processed"])
    return _Ctx.labels, _Ctx.actions


def _data(w: Window, gap: float = STAGE0_GAP_MIN) -> WindowData:
    inp = ctx_inputs(gap)
    return inp.data(inp.same_window(w) if gap != STAGE0_GAP_MIN else w)


def _call(fn, args):
    _use(args[0])
    return fn(*args)


def run_tasks(tasks: list, workers: int, label: str) -> list:
    """Run (fn, args) tasks, args[0] the config, in a pool of spawned processes when workers > 1
    (largest tasks first: callers sort them by cost)."""
    if not tasks:
        return []
    t0 = time.time()
    print(f"[{label}] {len(tasks)} tasks on {workers} workers", flush=True)
    for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(v, "1")   # spawned workers inherit one BLAS thread each (Newton steps call eigh)
    if workers <= 1:
        out = [_call(fn, args) for fn, args in tasks]
    else:
        with get_context("spawn").Pool(min(workers, len(tasks))) as pool:
            out = pool.starmap(_call, tasks, chunksize=1)
    print(f"[{label}] done in {time.time() - t0:.0f}s", flush=True)
    return out


@njit(cache=True)
def _argmax_parent(p0, pp, ptr):
    """Per target, the pair index of its most probable parent, or -1 for the background."""
    out = np.full(p0.size, -1, np.int64)
    for k in range(p0.size):
        best = p0[k]
        for p in range(ptr[k], ptr[k + 1]):
            if pp[p] > best:
                best = pp[p]
                out[k] = p
    return out


@njit(cache=True)
def _argmax_other(pp, ptr, par_src, tgt_dim):
    """Per target, the pair index of its most probable parent among the other speakers' events
    (the target's own messages and the background left out), or -1 when it has none."""
    out = np.full(tgt_dim.size, -1, np.int64)
    for k in range(tgt_dim.size):
        best = -1.0
        for p in range(ptr[k], ptr[k + 1]):
            if par_src[p] != tgt_dim[k] and pp[p] > best:
                best = pp[p]
                out[k] = p
    return out


def warm_up() -> None:
    """Compile the numba kernels (cache=True) in the parent before the pool starts, so that workers
    only read the on-disk cache and never write it concurrently."""
    from avsd.hawkes.matched import expected_counts
    from avsd.hawkes.model import Day
    from avsd.hawkes.opportunity import decayed_counts

    rng = np.random.default_rng(SEED)
    days = [Day(3600.0, np.sort(rng.uniform(0, 3600, 40)), rng.integers(0, 2, 40),
                exo_times=(np.sort(rng.uniform(0, 3600, 3)), np.sort(rng.uniform(0, 3600, 2))))]
    pk = pack(days, 2, exo_names=EXO)
    f = fit(pk, 2, kernel_sharing="class")
    decompose(pk, f), time_rescaling(pk, f), bootstrap_reps(pk, f, 0, 1, SEED)
    expected_counts(f.mu, f.alpha, [3600.0], [days[0].exo_times], f.spec)
    decayed_counts(np.array([1.0, 2.0]), np.array([0, 1]), np.array([1.5, 3.0]), 2, f.spec.beta)
    _argmax_parent(np.array([0.5]), np.array([0.5]), np.array([0, 1]))
    _argmax_other(np.array([0.5]), np.array([0, 1]), np.array([1]), np.array([0]))


def _cost(w: Window) -> float:
    return float(w.n_msgs) * (1.0 + (w.run_days[1] - w.run_days[0]) / 10.0)


# --- stage: accept --------------------------------------------------------------------------------


def fit_path(cfg: dict, w: Window) -> Path:
    return work_dir(cfg) / "fits" / f"{fname(w.key)}.pkl"


def _fit_task(cfg: dict, w: Window) -> str:
    path = fit_path(cfg, w)
    if not path.exists():
        _save(fit_window(_data(w), spec_of(cfg)), path)
    return w.key


def _rec_task(cfg: dict, w: Window, start: int, n: int) -> str:
    path = work_dir(cfg) / "recovery" / f"{fname(w.key)}__{start:02d}.pkl"
    if path.exists():
        return w.key
    r: FitResult = _load(fit_path(cfg, w))
    d = _data(w)
    pk = pack(d.days, d.K, r.fit.spec, exo_names=EXO)
    t0 = time.time()
    rec = recovery_check(pk, r.fit, n_rep=n, seed=window_seed(w.key, "rec"), start=start)
    _save((rec, time.time() - t0), path)
    return w.key


def recovery_of(cfg: dict, w: Window) -> tuple[Recovery, float]:
    parts = sorted((work_dir(cfg) / "recovery").glob(f"{fname(w.key)}__*.pkl"))
    got = [_load(p) for p in parts]
    return Recovery.concat([r for r, _ in got]), float(sum(s for _, s in got))


def borderline(r: Recovery) -> bool:
    """The mean mae4 lies within BORDER_SE Monte Carlo standard errors of the bar (and no replicate
    exploded, which fails the window anyway)."""
    return not r.exploded.any() and abs(r.mae4_mean - BAR) < BORDER_SE * r.mae4_se


def recovery_row(r: Recovery) -> dict:
    """SPEC 5.6-1 summary of one window's recovery check: mean mae4 with its standard error, the bias of
    every share and of n by cell type, exploded replicates and the objective decreases of the refits."""
    ok = ~r.exploded
    return {"n_reps": int(r.mae4.size), "n_exploded": int(r.exploded.sum()), "mae4": r.mae4_mean,
            "mae4_se": r.mae4_se, "mae4_max": float(r.mae4[ok].max()) if ok.any() else float("nan"),
            "mae": float(r.mae[ok].mean()) if ok.any() else float("nan"),
            **{f"bias_{c}": v for c, v in r.bias.items()}, **r.n_bias_summary(),
            "rec_converged": float(r.converged[ok].mean()) if ok.any() else float("nan"),
            "rec_violations": None if r.n_violations is None else int(r.n_violations.sum())}


def _rec_tasks(cfg: dict, windows: list[Window], lo: int, hi: int) -> list:
    out = []
    for w in sorted(windows, key=_cost, reverse=True):
        step = 1 if w.n_msgs > 20000 else 5
        out += [(_rec_task, (cfg, w, s, min(step, hi - s))) for s in range(lo, hi, step)]
    return out


def run_accept(cfg: dict, workers: int) -> list[Window]:
    """Fit and recovery-check the goal windows and merge failing ones (one merge round at a time,
    windows.merge_units) until every window passes or has no neighbour left. A window whose mean
    mae4 over N_REC replicates lies within BORDER_SE standard errors of the bar gets N_REC_EXTRA more
    before the decision. Writes accept.parquet (every round) and goal_windows.parquet (the final
    windows)."""
    wd = work_dir(cfg)
    inp = ctx_inputs()
    windows = inp.goal_windows()
    log, rnd = [], 0
    while True:
        todo = sorted(windows, key=_cost, reverse=True)
        run_tasks([(_fit_task, (cfg, w)) for w in todo], workers, f"accept fit r{rnd}")
        run_tasks(_rec_tasks(cfg, todo, 0, N_REC), workers, f"accept recovery r{rnd}")
        rec = {w.key: recovery_of(cfg, w) for w in windows}
        more = [w for w in windows if rec[w.key][0].mae4.size < N_REC + N_REC_EXTRA and borderline(rec[w.key][0])]
        if more and N_REC_EXTRA > 0:
            run_tasks(_rec_tasks(cfg, more, N_REC, N_REC + N_REC_EXTRA), workers, f"accept borderline r{rnd}")
            rec.update({w.key: recovery_of(cfg, w) for w in more})
        failed = {k for k, (r, _) in rec.items() if r.failed(BAR)}
        for w in windows:
            r, secs = rec[w.key]
            log.append({"round": rnd, "key": w.key, "window_id": w.window_id, "group": w.group, "n_msgs": w.n_msgs,
                        **recovery_row(r), "passed": w.key not in failed, "merged": w.merged, "rec_secs": secs})
        new = remerge_goal_windows(windows, failed, inp.agent_msgs, inp.blocks)
        print(f"[accept] round {rnd}: {len(windows)} windows, failed {sorted(failed)}", flush=True)
        if {w.key for w in new} == {w.key for w in windows}:
            break
        windows, rnd = new, rnd + 1
    pl.DataFrame(log).write_parquet(wd / "accept.parquet")
    save_windows(windows, wd / "goal_windows.parquet")
    return windows


def save_windows(windows: list[Window], path: Path) -> None:
    rows = [{"kind": w.kind, "window_id": w.window_id, "group": w.group, "room_id": w.room_id,
             "goals": list(w.goals), "run_day_start": w.run_days[0], "run_day_end": w.run_days[1],
             "date_start": w.date_start, "date_end": w.date_end, "n_msgs": w.n_msgs, "share": w.share,
             "merged": w.merged} for w in windows]
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows, schema_overrides={"goals": pl.List(pl.Int64)}).write_parquet(path)


def load_windows(path: Path) -> list[Window]:
    return [Window(r["kind"], r["window_id"], r["group"], r["room_id"], tuple(r["goals"] or ()),
                   (r["run_day_start"], r["run_day_end"]), r["date_start"], r["date_end"], r["n_msgs"], r["share"],
                   r["merged"]) for r in pl.read_parquet(path).iter_rows(named=True)]


def final_windows(cfg: dict) -> list[Window]:
    path = work_dir(cfg) / "goal_windows.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path}: run the accept stage first")
    return load_windows(path)


def base_fit(cfg: dict, w: Window) -> FitResult:
    return _load(fit_path(cfg, w))


# --- stage: boot ----------------------------------------------------------------------------------


def _boot_task(cfg: dict, w: Window, start: int, stop: int) -> str:
    path = work_dir(cfg) / "boot" / fname(w.key) / f"{start:04d}.pkl"
    if path.exists():
        return w.key
    r = base_fit(cfg, w)
    d = _data(w)
    pk = pack(d.days, d.K, r.fit.spec, exo_names=EXO)
    t0 = time.time()
    b = bootstrap_reps(pk, r.fit, start, stop, window_seed(w.key, "boot"), clusters=d.clusters())
    _save((b, b.events, time.time() - t0), path)
    return w.key


def boot_tasks(cfg: dict) -> list:
    tasks = []
    for w in sorted(final_windows(cfg), key=_cost, reverse=True):
        step = 5 if w.n_msgs > 20000 else 20 if w.n_msgs > 4000 else 50
        tasks += [(_boot_task, (cfg, w, s, min(s + step, N_BOOT))) for s in range(0, N_BOOT, step)]
    return tasks


def boot_of(cfg: dict, w: Window) -> tuple[BootstrapResult, np.ndarray, float] | None:
    parts = sorted((work_dir(cfg) / "boot" / fname(w.key)).glob("*.pkl"))
    if not parts:
        return None
    got = [_load(p) for p in parts]
    return (BootstrapResult.concat([b for b, _, _ in got]), np.concatenate([x for _, x, _ in got]),
            float(sum(s for _, _, s in got)))


# --- stage: matched -------------------------------------------------------------------------------


def _matched_task(cfg: dict, w: Window, arm: str, reps: int) -> str:
    path = work_dir(cfg) / "matched" / fname(w.key) / f"{arm}.pkl"
    if path.exists():
        return w.key
    r = base_fit(cfg, w)
    d = _data(w)
    pk = pack(d.days, d.K, r.fit.spec, exo_names=EXO)
    t0 = time.time()
    mu, alpha, rise = arm_truth(arm, r.fit, pk, iters=20 if w.n_msgs > 20000 else 30)
    rows = []
    if arm == "fit" or not (np.allclose(alpha, r.fit.alpha) and np.allclose(mu, r.fit.mu)):
        Ts, exo = pk.day_T.tolist(), pk.exo_times()
        for rep in range(reps):
            seed = [SEED, 5151, zlib.crc32(w.key.encode()), ARMS.index(arm), rep]
            try:
                res = run_replicate(mu, alpha, Ts, exo, d.K, EXO, r.fit.spec, seed, present=pk.present,
                                    caps=explosion_caps(pk))
            except RuntimeError as e:     # an exploding cascade (validate.explosion_caps)
                res = {"error": str(e)}
            rows.append({"key": w.key, "arm": arm, "rep": rep, "self_rise": rise, **res})
    _save((rows, time.time() - t0), path)
    return w.key


def matched_tasks(cfg: dict) -> list:
    return [(_matched_task, (cfg, w, arm, MATCHED_REPS)) for w in sorted(final_windows(cfg), key=_cost, reverse=True)
            for arm in ARMS]


# --- stage: sens ----------------------------------------------------------------------------------


def _sens_task(cfg: dict, w: Window, variant: str) -> str:
    path = work_dir(cfg) / "sens" / fname(w.key) / f"{variant}.pkl"
    if path.exists():
        return w.key
    base = base_fit(cfg, w)
    res: FitResult | None
    if variant == "tie":
        tie = tuple(c for c, ok in base.identified().items() if c in EXO and not ok)
        res = fit_window(_data(w), base.fit.spec, "tie", tie) if tie else None
    elif variant.startswith("L"):
        res = fit_window(_data(w), spec_of(cfg, float(variant[1:])), variant)
    else:
        d = _data(w, float(variant[1:]))
        if _bounds(d) == base.day_bounds:
            res = replace(base, variant=variant, note="same realizations as G = 30 min")
        else:
            res = fit_window(d, base.fit.spec, variant)
    _save(res, path)
    return w.key


def sens_tasks(cfg: dict) -> list:
    return [(_sens_task, (cfg, w, v)) for w in sorted(final_windows(cfg), key=_cost, reverse=True)
            for v in sens_variants()]


def sens_of(cfg: dict, w: Window, variant: str) -> FitResult | None:
    path = work_dir(cfg) / "sens" / fname(w.key) / f"{variant}.pkl"
    return _load(path) if path.exists() else None


# --- stage: valid ---------------------------------------------------------------------------------


def labels_path(cfg: dict) -> Path:
    return work_dir(cfg) / "parent_labels.parquet"


def ensure_labels(cfg: dict) -> pl.DataFrame:
    """Tier-1 parent labels (avsd.hawkes.references), computed once and kept in data/."""
    path = labels_path(cfg)
    if not path.exists():
        from avsd.hawkes.references import load_label_rows, tier1_labels

        t0 = time.time()
        rows, names = load_label_rows(cfg["paths"]["processed"], cfg["paths"]["tables"])
        lab = tier1_labels(rows, names)
        path.parent.mkdir(parents=True, exist_ok=True)
        lab.write_parquet(path)
        print(f"[valid] {lab.height} tier-1 labels in {time.time() - t0:.0f}s", flush=True)
    return pl.read_parquet(path)


def reference_check(pk: Packed, f: HawkesFit, d: WindowData, labels: pl.DataFrame) -> dict:
    """Most probable Hawkes parent and the baseline against the tier-1 labels of the window's events."""
    uids = pk.ev_uid[pk.tgt_ev].astype(str)
    lab = labels.with_columns(("chat:" + pl.col("child_id")).alias("uid")).filter(pl.col("uid").is_in(uids.tolist()))
    out = {"n_labels": lab.height}
    if lab.is_empty():
        return out | {"rows": pl.DataFrame()}
    w = np.ones(pk.tgt_dim.size)
    p0, pp = _posterior(f.mu, f.alpha, w, pk.tgt_dim, pk.tgt_bin, pk.ptr, pk.par_src, pk.phi)
    best = _argmax_parent(p0, pp, pk.ptr)
    idx = {u: k for k, u in enumerate(uids)}
    k = np.array([idx[u] for u in lab["uid"]])
    other = _argmax_other(pp, pk.ptr, pk.par_src, pk.tgt_dim)
    hawkes = np.where(best[k] >= 0, pk.ev_uid[pk.par_ev[np.maximum(best[k], 0)]].astype(str), "background")
    hawkes_other = np.where(other[k] >= 0, pk.ev_uid[pk.par_ev[np.maximum(other[k], 0)]].astype(str), "none")
    cand = [set(pk.ev_uid[pk.par_ev[pk.ptr[j]:pk.ptr[j + 1]]].astype(str)) for j in k]
    parent = np.array(("chat:" + lab["parent_id"]).to_list(), dtype=object)
    base = [None if b is None else "chat:" + b for b in lab["baseline_id"].to_list()]
    self_parent = (best[k] >= 0) & (pk.par_src[np.maximum(best[k], 0)] == pk.tgt_dim[k])
    rows = pl.DataFrame({
        "realization": np.array(d.realizations)[pk.tgt_day[k]], "label": lab["label"],
        "hawkes_match": hawkes == parent, "hawkes_other_match": hawkes_other == parent,
        "baseline_match": [b == p for b, p in zip(base, parent)],
        "in_candidates": [p in c for p, c in zip(parent, cand)],
        "argmax_background": best[k] < 0, "argmax_self": self_parent,
    })
    return out | {"rows": rows}


def _valid_task(cfg: dict, w: Window) -> str:
    path = work_dir(cfg) / "valid" / f"{fname(w.key)}.pkl"
    if path.exists():
        return w.key
    from avsd.hawkes.opportunity import compare

    r = base_fit(cfg, w)
    d = _data(w)
    pk = pack(d.days, d.K, r.fit.spec, exo_names=EXO)
    t0 = time.time()
    rs = time_rescaling(pk, r.fit, pool="concat")
    qq = np.array([np.quantile(x, QQ_PROBS) if x.size else np.full(QQ_PROBS.size, np.nan) for x in rs.increments])
    labels, actions = ctx_valid_inputs()
    out = {"key": w.key, "ks": rs.ks_stat, "ks_p": rs.ks_pvalue, "ks_n": rs.n, "qq": qq,
           "qq_pooled": np.quantile(rs.pooled, QQ_PROBS) if rs.pooled.size else None,
           "refs": reference_check(pk, r.fit, d, labels), "opp": compare(d, r.fit, actions)}
    out["secs"] = time.time() - t0
    _save(out, path)
    return w.key


def valid_tasks(cfg: dict) -> list:
    return [(_valid_task, (cfg, w)) for w in sorted(final_windows(cfg), key=_cost, reverse=True)]


def valid_of(cfg: dict, w: Window) -> dict | None:
    path = work_dir(cfg) / "valid" / f"{fname(w.key)}.pkl"
    return _load(path) if path.exists() else None


# --- stage: rolling ---------------------------------------------------------------------------------


def rolling_path(cfg: dict, w: Window) -> Path:
    return work_dir(cfg) / "rolling" / f"{fname(w.key)}.pkl"


def _rolling_task(cfg: dict, w: Window) -> str:
    path = rolling_path(cfg, w)
    if not path.exists():
        _save(fit_window(_data(w), spec_of(cfg)), path)
    return w.key


def rolling_windows(cfg: dict) -> list[Window]:
    path = work_dir(cfg) / "rolling_windows.parquet"
    if not path.exists():
        save_windows(ctx_inputs().rolling_windows(), path)
    return load_windows(path)


def rolling_tasks(cfg: dict) -> list:
    return [(_rolling_task, (cfg, w)) for w in sorted(rolling_windows(cfg), key=_cost, reverse=True)
            if w.n_msgs >= MIN_MSGS]


# --- driver -----------------------------------------------------------------------------------------


def _shard(tasks: list, shard: tuple[int, int]) -> list:
    i, n = shard
    return tasks[i::n]


def run_stage(cfg: dict, stage: str, workers: int = 1, shard: tuple[int, int] = (0, 1), reverse: bool = False) -> None:
    _Ctx.cfg, _Ctx.inputs, _Ctx.labels, _Ctx.actions = cfg, {}, None, None
    apply_settings(cfg)
    t0 = time.time()
    ctx_inputs()
    if stage == "valid":
        ensure_labels(cfg)
    warm_up()
    if stage == "accept":
        run_accept(cfg, workers)
    elif stage == "assemble":
        from avsd.hawkes.report import assemble

        assemble(cfg)
    else:
        make = {"boot": boot_tasks, "matched": matched_tasks, "sens": sens_tasks, "valid": valid_tasks,
                "rolling": rolling_tasks}[stage]
        tasks = _shard(make(cfg), shard)
        label = f"{stage} {shard[0]}/{shard[1]}" + (" reversed" if reverse else "")
        run_tasks(tasks[::-1] if reverse else tasks, workers, label)
    stamp = work_dir(cfg) / "runtime" / f"{stage}_{shard[0]}of{shard[1]}{'_rev' * reverse}.txt"
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(f"{stage} shard {shard[0]}/{shard[1]}{' reversed' if reverse else ''} workers {workers}: "
                     f"{time.time() - t0:.0f} s\n")


def run_all(cfg: dict, window: str, workers: int) -> None:
    """`avsd hawkes fit`: every stage of the goal windows, or the rolling windows; then assemble."""
    stages = ("accept", "boot", "matched", "sens", "valid") if window == "goal" else ("rolling",)
    for s in (*stages, "assemble"):
        run_stage(cfg, s, workers)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("stage", choices=STAGES)
    ap.add_argument("--shard", default="0/1", help="i/n: run every n-th task from the i-th")
    ap.add_argument("--workers", type=int, default=int(os.environ.get("SLURM_CPUS_PER_TASK", "1")))
    ap.add_argument("--config", default=None)
    ap.add_argument("--reverse", action="store_true", help="walk the shard's tasks from the end")
    a = ap.parse_args(argv)
    i, n = (int(x) for x in a.shard.split("/"))
    run_stage(load_config(a.config), a.stage, a.workers, (i, n), a.reverse)


if __name__ == "__main__":
    # Run from the imported module, so that pickled results and tasks refer to avsd.hawkes.pipeline.
    from avsd.hawkes import pipeline as _pipeline

    _pipeline.main()
