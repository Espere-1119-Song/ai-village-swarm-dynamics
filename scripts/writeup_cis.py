"""95% confidence intervals for the values that reports/writeup.md marks with a CI placeholder.

CPU job on GRASP (about 3 minutes, peak memory about 4 GB):

    sbatch -A gu-account -p batch --exclude=al-l40s-0.grasp.maas -N 1 -c 4 --mem=32G -t 00:30:00 \
        -o logs/writeup_cis-%j.out --wrap 'cd $AVSD && . scripts/env.sh && python scripts/writeup_cis.py'

Everything comes from existing module outputs and intermediates; no model is refitted.

- Module A: run-date bootstrap replicates (data/interim/hawkes_fit/boot), final fits
  (data/interim/hawkes_fit/fits), first-run fits without presence masks (data/interim/hawkes_fit_v1),
  outputs/tables/hawkes_opportunity.csv.
- Module B1: data/interim/memory_facts{,_v2,_v3}.parquet (per unit: trials, first-loss event,
  restoration) and the live memory rows (avsd.lineage.memory.live_rows), which give each unit's
  entry consolidation and so whether a loss left later consolidations.
- Module B2: the MAP forest of the last run (data/interim/b2/summary.pkl) and the quantity contexts of
  the occurrences (data/interim/b2/occurrences.parquet).
- Modules D2 to D4: data/interim/depgraph/edges_main.parquet (touch rules v2) and the session table.

Writes outputs/tables/writeup_cis.csv (quantity, value, ci_lo, ci_hi, n, method, source) and nothing
else. Shares are proportions. Intervals are 95% percentile intervals. Item k draws its resamples from
SeedSequence(20261003, spawn_key=(k,)), so items do not depend on each other or on their order.
Recomputed point estimates are printed next to the values in the draft; only aggregates are printed.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import pickle
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import polars as pl

from avsd.config import load_config

SEED = 20261003
B = 10_000          # resamples where cheap
LEVEL = 0.95
Q = ((1 - LEVEL) / 2, (1 + LEVEL) / 2)
COLUMNS = ("quantity", "value", "ci_lo", "ci_hi", "n", "method", "source")


def rng_for(item: int) -> np.random.Generator:
    return np.random.default_rng(np.random.SeedSequence(SEED, spawn_key=(item,)))


def pct(x: np.ndarray) -> tuple[float, float]:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    lo, hi = np.quantile(x, Q)
    return float(lo), float(hi)


def row(quantity: str, value: float, lo: float, hi: float, n: str, method: str, source: str) -> dict:
    return {"quantity": quantity, "value": value, "ci_lo": lo, "ci_hi": hi, "n": n, "method": method,
            "source": source}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def boot_medians(x: np.ndarray, rng: np.random.Generator, reps: int = B) -> np.ndarray:
    idx = rng.integers(0, len(x), size=(reps, len(x)))
    return np.median(np.asarray(x, dtype=float)[idx], axis=1)


def weighted_gini(s: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Gini of the sample that repeats sorted value s[k] w[..., k] times (the D1 formula on the expanded
    sample); w may hold one row of weights per replicate."""
    w = np.atleast_2d(w).astype(np.float64)
    N = w.sum(1)
    S = w @ s
    a = np.cumsum(w, axis=1) - w
    with np.errstate(invalid="ignore", divide="ignore"):
        return ((w * (2 * a + w - N[:, None])) @ s) / (N * S)


# --- module A ---------------------------------------------------------------------------------------


def module_a(cfg: dict) -> list[dict]:
    from avsd.hawkes import pipeline as P
    from avsd.hawkes.model import spectral_radius

    P.apply_settings(cfg)
    tables = Path(cfg["paths"]["outputs"]) / "tables"
    interim = Path(cfg["paths"]["interim"])
    out: list[dict] = []
    wins = P.final_windows(cfg)
    names = ("baseline", "human", "system", "other_agents", "self")
    fits = {w.key: P.base_fit(cfg, w) for w in wins}
    boots = {}
    ref_reps, aligned = None, True
    for w in wins:
        b = P.boot_of(cfg, w)[0]
        if tuple(b.names) != names:
            raise ValueError(f"{w.key}: share names {b.names}")
        o = np.argsort(b.reps)
        boots[w.key] = (b.reps[o], b.shares[o], b.events[o], b.n[o], b.converged[o])
        if ref_reps is None:
            ref_reps = b.reps[o]
        aligned &= np.array_equal(b.reps[o], ref_reps)
    R = len(ref_reps)
    n_ev = np.array([fits[w.key].n_events for w in wins], dtype=float)
    est_w = np.array([fits[w.key].shares for w in wins])
    est = (est_w * n_ev[:, None]).sum(0) / n_ev.sum()
    win_tab = pl.read_csv(tables / "hawkes_windows.csv")
    tab_est = {c: float(np.average(win_tab[f"share_{c}"].to_numpy(), weights=win_tab["agent_events"].to_numpy()))
               for c in names}
    log(f"A1: {len(wins)} windows, {int(n_ev.sum()):,} agent messages, replicate indices aligned: {aligned} "
        f"({R} per window, indices {ref_reps.min()}-{ref_reps.max()})")
    src_boot = "data/interim/hawkes_fit/boot (run-date replicates), data/interim/hawkes_fit/fits"
    label = {"self": "self", "baseline": "baseline", "other_agents": "other agents", "human": "human",
             "system": "system"}
    if aligned:
        S = np.stack([boots[w.key][1] for w in wins])          # (W, R, 5)
        E = np.stack([boots[w.key][2] for w in wins])          # (W, R)
        pooled = (S * E[..., None]).sum(0) / E.sum(0)[:, None]
        fixed = (S * n_ev[:, None, None]).sum(0) / n_ev.sum()
        rng = rng_for(1)
        cnt = np.stack([np.bincount(rng.integers(0, len(wins), len(wins)), minlength=len(wins)) for _ in range(B)])
        wres = (cnt * n_ev) @ est_w / (cnt @ n_ev)[:, None]
        normal = []
        for k, c in enumerate(names):
            lo, hi = pct(pooled[:, k])
            flo, fhi = pct(fixed[:, k])
            wlo, whi = pct(wres[:, k])
            sd = float(pooled[:, k].std(ddof=1))
            nlo, nhi = max(est[k] - 1.96 * sd, 0.0), min(est[k] + 1.96 * sd, 1.0)
            inside = lo <= est[k] <= hi
            log(f"A1 {c}: estimate {est[k]:.4f} (window table {tab_est[c]:.4f}); combined replicates "
                f"[{lo:.4f}, {hi:.4f}]{'' if inside else ' (excludes the estimate)'}, replicate mean "
                f"{pooled[:, k].mean():.4f}, SD {sd:.4f}, share of replicates below the estimate "
                f"{(pooled[:, k] < est[k]).mean():.3f}; normal [{nlo:.4f}, {nhi:.4f}]; basic "
                f"[{2 * est[k] - hi:.4f}, {2 * est[k] - lo:.4f}]; fixed weights [{flo:.4f}, {fhi:.4f}]; "
                f"windows resampled [{wlo:.4f}, {whi:.4f}]")
            n_txt = f"{int(n_ev.sum()):,} agent messages in {len(wins)} goal windows; {R:,} run-date replicates per window"
            q = f"A: share of agent messages triggered by {label[c]}, event-weighted over the 43 goal windows"
            out.append(row(
                q, float(est[k]), lo, hi, n_txt,
                f"percentile over {R:,} combined replicates: replicate r of every window (run dates resampled, "
                "refit with the point estimator) pooled with replicate r's event counts as weights. Replicate "
                f"indices 0-{R - 1} exist in all {len(wins)} windows. Windows draw with their own seeds, so best "
                "and rest windows on the same dates are resampled independently"
                + ("" if inside else f". The interval excludes the estimate: the combined replicates average "
                   f"{pooled[:, k].mean():.4f} (replicate refits are biased, docs/decisions.md)"),
                f"{src_boot}; outputs/tables/hawkes_windows.csv"))
            normal.append(row(
                q + " (normal-interval alternative)", float(est[k]), nlo, nhi, n_txt,
                "estimate +/- 1.96 SD of the same combined replicates, clipped to [0, 1] (the alternative that "
                "hawkes_decomposition.csv keeps per window as normal_lo and normal_hi)",
                f"{src_boot}; outputs/tables/hawkes_windows.csv"))
        out += normal
    else:
        rng = rng_for(1)
        cnt = np.stack([np.bincount(rng.integers(0, len(wins), len(wins)), minlength=len(wins)) for _ in range(B)])
        wres = (cnt * n_ev) @ est_w / (cnt @ n_ev)[:, None]
        for k, c in enumerate(names):
            lo, hi = pct(wres[:, k])
            out.append(row(
                f"A: share of agent messages triggered by {label[c]}, event-weighted over the 43 goal windows",
                float(est[k]), lo, hi, f"{int(n_ev.sum()):,} agent messages in {len(wins)} goal windows",
                f"replicate indices not aligned across windows: {B:,} resamples of the windows, percentile",
                "outputs/tables/hawkes_windows.csv"))

    # A2: core rho of g35-39 best.
    w = next(x for x in wins if x.window_id == "g35-39" and x.group == "best")
    r = fits[w.key]
    core = r.core()
    K = r.K
    nb, conv = boots[w.key][3], boots[w.key][4]
    rho_c = np.array([spectral_radius(nb[k][:K, :K][np.ix_(core, core)]) for k in range(len(nb))])
    lo, hi = pct(rho_c)
    lo_c, hi_c = pct(rho_c[conv.astype(bool)])
    log(f"A2 core rho g35-39 best: {r.rho_core():.4f} over {core.size} of {K} agents "
        f"({', '.join(r.agent_names[i] for i in core)}); [{lo:.4f}, {hi:.4f}]; certified replicates only "
        f"({int(conv.sum())}) [{lo_c:.4f}, {hi_c:.4f}]; replicates above 1: {(rho_c > 1).mean():.3f}")
    out.append(row(
        "A: spectral radius over core agents (present on >= 80% of realizations), G35-39 best",
        float(r.rho_core()), lo, hi,
        f"{core.size} core agents of {K}; {r.n_dates} run dates; {len(nb):,} run-date replicates",
        f"percentile of the spectral radius of the core agents' N_AA block in each run-date bootstrap replicate "
        f"(core set fixed from the full-data fit; all {len(nb):,} replicates, {int(conv.sum())} Newton-certified)",
        f"data/interim/hawkes_fit/boot/{P.fname(w.key)}, data/interim/hawkes_fit/fits/{P.fname(w.key)}.pkl"))

    # A3: median self branching ratio of part-time agents with at least 21 events.
    cur = []
    for wd in wins:
        rr = fits[wd.key]
        pres = rr.presence
        for i in range(rr.K):
            if pres[i] < P.CORE_PRESENCE and int(round(rr.events_dim[i])) >= 21:
                cur.append((wd.key, rr.agent_names[i], float(rr.fit.n[i, i]), wd))
    v1dir = interim / "hawkes_fit_v1"
    w1 = {x.key: x for x in P.load_windows(v1dir / "goal_windows.parquet")}
    f1: dict = {}
    matched = []
    for key, name, n_cur, wd in cur:
        x = w1.get(key)
        if x is None or (x.date_start, x.date_end, x.room_id) != (wd.date_start, wd.date_end, wd.room_id):
            continue
        if key not in f1:
            f1[key] = P._load(v1dir / "fits" / f"{P.fname(key)}.pkl")
        r1 = f1[key]
        if name in r1.agent_names:
            i = r1.agent_names.index(name)
            matched.append((key, name, float(r1.fit.n[i, i]), n_cur))
    with_m = np.array([c[2] for c in cur])
    without = np.array([m[2] for m in matched])
    rng = rng_for(3)
    bw = boot_medians(without, rng)
    bm = boot_medians(with_m, rng)
    same37 = float(np.median([m[3] for m in matched]))
    log(f"A3: part-time dimensions with >= 21 events: {len(cur)} (median n_ii {np.median(with_m):.4f}); "
        f"{len(matched)} of them in first-run windows (first-run median {np.median(without):.4f}, current median "
        f"over the same {len(matched)}: {same37:.4f})")
    # The first run on its own windows, with presence recomputed for them (stated in the method text).
    from avsd.hawkes.windows import Inputs

    inp = Inputs.load(cfg)
    own = []
    for x in w1.values():
        r1 = P._load(v1dir / "fits" / f"{P.fname(x.key)}.pkl")
        pres = inp.data(x).present.mean(0)
        own += [float(r1.fit.n[i, i]) for i in range(r1.K)
                if pres[i] < P.CORE_PRESENCE and int(round(r1.events_dim[i])) >= 21]
    del inp
    lo_o, hi_o = pct(boot_medians(np.array(own), rng_for(30)))
    log(f"A3 check: first run on its own {len(w1)} windows, presence recomputed: {len(own)} dimensions, "
        f"median {np.median(own):.4f} [{lo_o:.4f}, {hi_o:.4f}]")
    out.append(row(
        "A: median self branching ratio n_ii of part-time agents with >= 21 events, without presence masks (first run)",
        float(np.median(without)), *pct(bw),
        f"{len(matched)} agent dimensions (the {len(cur)} part-time dimensions of the current run whose window "
        "and agent also exist in the first run)",
        f"bootstrap over dimensions ({B:,} resamples), percentile; first-run n_ii looked up by window and agent. "
        f"Over the first run's own {len(w1)} windows (presence recomputed for them) the median is "
        f"{np.median(own):.4f} [{lo_o:.4f}, {hi_o:.4f}] over {len(own)} dimensions; the masked median over the "
        f"same {len(matched)} dimensions is {same37:.4f}",
        "data/interim/hawkes_fit_v1/fits, data/interim/hawkes_fit/fits"))
    out.append(row(
        "A: median self branching ratio n_ii of part-time agents with >= 21 events, with presence masks",
        float(np.median(with_m)), *pct(bm),
        f"{len(cur)} agent dimensions (presence < 80% of the window's realizations, >= 21 events)",
        f"bootstrap over dimensions ({B:,} resamples), percentile",
        "data/interim/hawkes_fit/fits"))
    # A fresh generator from spawn key 3 repeats the first-run row's draws, so both medians come from the
    # same resampled dimension sets.
    with37 = np.array([m[3] for m in matched])
    bm37 = boot_medians(with37, rng_for(3))
    log(f"A3 same dimensions: masked median {same37:.4f} {pct(bm37)} over {len(matched)} dimensions")
    out.append(row(
        "A: median self branching ratio n_ii of part-time agents with >= 21 events, with presence masks, "
        "on the dimensions of the first-run row",
        same37, *pct(bm37),
        f"{len(matched)} agent dimensions (the same as the first-run row)",
        f"bootstrap over dimensions ({B:,} resamples), percentile; the same resampled dimension sets as the "
        "first-run row (spawn key 3), so the two medians are paired",
        "data/interim/hawkes_fit/fits, data/interim/hawkes_fit_v1/goal_windows.parquet"))

    # A4: median Spearman of the opportunity and Hawkes rankings.
    opp = pl.read_csv(tables / "hawkes_opportunity.csv")
    s = opp["spearman"].cast(pl.Float64).drop_nulls().drop_nans().to_numpy()
    bs = boot_medians(s, rng_for(4))
    log(f"A4: median Spearman {np.median(s):.4f} over {len(s)} windows, negative in {(s < 0).sum()}")
    out.append(row(
        "A: median Spearman correlation of the opportunity-model and Hawkes rankings",
        float(np.median(s)), *pct(bs), f"{len(s)} goal windows",
        f"bootstrap over windows ({B:,} resamples), percentile; per-window Spearman over agent pairs as tabulated",
        "outputs/tables/hawkes_opportunity.csv"))
    return out


# --- module B1 --------------------------------------------------------------------------------------


def entry_cons(cfg: dict) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Entry consolidation of every (agent, unit) of memory_facts and each agent's consolidation count.

    A unit enters at the start of its first presence spell, except that a unit that entered after the
    last consolidation and is absent at an undo row (revert, trunc_other, fork extending an older row)
    before the next consolidation is removed from tracking and enters again at its next spell
    (avsd.lineage.chains.run_chain). entry_cons = consolidations at or before the entry row."""
    from avsd.lineage.memory import live_rows

    interim = Path(cfg["paths"]["interim"])
    rows, _ = live_rows(pl.read_parquet(interim / "memory_versions.parquet"))
    rel = pl.col("rel").cast(pl.String)
    rows = rows.with_columns(
        pl.col("is_cons").cast(pl.Int64).cum_sum().over("agent_id").alias("c_at"),
        (rel.is_in(["revert", "trunc_other"]) | ((rel == "fork_append") & (pl.col("base_idx") != pl.col("idx") - 1)))
        .alias("undo"))
    K = rows.group_by("agent_id").agg(pl.col("is_cons").sum().cast(pl.Int64).alias("K"))
    r = rows.select("agent_id", "id", "c_at", "undo")
    sp = (pl.read_parquet(interim / "memory_facts.parquet",
                          columns=["agent_id", "unit_key", "spell", "spell_start_row_id", "spell_end_row_id"])
          .join(r.rename({"id": "spell_start_row_id", "c_at": "c_start", "undo": "u_start"}),
                on=["agent_id", "spell_start_row_id"], how="left")
          .join(r.rename({"id": "spell_end_row_id", "c_at": "c_end", "undo": "u_end"}),
                on=["agent_id", "spell_end_row_id"], how="left")
          .with_columns((pl.col("u_end").fill_null(False) & (pl.col("c_end") == pl.col("c_start"))).alias("untracked"))
          .select("agent_id", "unit_key", "spell", "c_start", "untracked"))
    if sp["c_start"].null_count():
        raise ValueError("spell rows outside the live memory rows")
    # Only an entry spell can end in an untracking, and the spell after it is the next entry, so the entry
    # is the first spell whose predecessors were all untracked and which is not untracked itself.
    ent = (sp.sort("agent_id", "unit_key", "spell")
           .with_columns(pl.col("untracked").cast(pl.Int64).cum_sum().over("agent_id", "unit_key").alias("_u"))
           .filter((pl.col("_u") - pl.col("untracked").cast(pl.Int64) == pl.col("spell")) & ~pl.col("untracked"))
           .group_by("agent_id", "unit_key").agg(pl.col("c_start").first().alias("entry_cons"),
                                                pl.col("spell").first().alias("entry_spell")))
    n_untr = int(ent.filter(pl.col("entry_spell") > 0).height)
    return ent, K, n_untr


def module_b1(cfg: dict) -> list[dict]:
    interim, processed = Path(cfg["paths"]["interim"]), Path(cfg["paths"]["processed"])
    ent, K, n_untr = entry_cons(cfg)
    agents = pl.read_parquet(processed / "agents.parquet").select("agent_id", pl.col("scaffold").cast(pl.String))
    std_ids = sorted(agents.filter(pl.col("scaffold") != "claude_code")["agent_id"].to_list())
    log(f"B1: entries for {ent.height:,} units ({n_untr:,} re-entered after an undo removed them from tracking); "
        f"{len(std_ids)} standard agents")
    targets = {  # the module's published counts for standard agents (QA sections 0 and 5)
        "v1": {"lost": 4_134_752, "later": 4_131_554, "restored": 758_165, "modified": 962_470},
        "v2": {"lost": 4_114_736, "later": 4_111_980, "restored": 604_728},
        "v3": {"lost": 4_126_997, "later": 4_123_882, "restored": 684_369},
    }
    draft = {"v1": (0.233, 0.184), "v2": (0.052, 0.147), "v3": (0.066, 0.166)}
    rng = rng_for(5)
    A = len(std_ids)
    W = np.stack([np.bincount(rng.integers(0, A, A), minlength=A) for _ in range(B)]).astype(np.float64)
    out = []
    for v in ("v1", "v2", "v3"):
        path = interim / ("memory_facts.parquet" if v == "v1" else f"memory_facts_{v}.parquet")
        f = (pl.read_parquet(path, columns=["agent_id", "unit_key", "spell", "trials", "lost_event", "restored"])
             .filter((pl.col("spell") == 0) & pl.col("trials").is_not_null())
             .join(ent, on=["agent_id", "unit_key"], how="left").join(K, on="agent_id", how="left"))
        cens = f.filter((pl.col("lost_event") == "none") & (pl.col("trials") != pl.col("K") - pl.col("entry_cons")))
        lost = (f.filter((pl.col("trials") > 0) & (pl.col("lost_event") != "none")
                         & pl.col("agent_id").is_in(std_ids))
                .with_columns((pl.col("entry_cons") + pl.col("trials") < pl.col("K")).alias("later")))
        n_rest_last = lost.filter(pl.col("restored") & ~pl.col("later")).height
        n_no_entry = int(lost["entry_cons"].null_count())
        if n_rest_last or n_no_entry:
            log(f"B1 {v}: {n_rest_last} restored units without a later consolidation, {n_no_entry} lost units "
                "without an entry (both expected 0)")
        per = (lost.group_by("agent_id").agg(pl.len().alias("lost"),
                                             (pl.col("lost_event") == "modified").sum().alias("modified"),
                                             pl.col("later").sum().alias("later"),
                                             (pl.col("restored") & pl.col("later")).sum().alias("restored"))
               .join(pl.DataFrame({"agent_id": std_ids}), on="agent_id", how="right").fill_null(0)
               .sort("agent_id"))
        tot = {c: int(per[c].sum()) for c in ("lost", "modified", "later", "restored")}
        ms, rs = tot["modified"] / tot["lost"], tot["restored"] / tot["later"]
        t = targets[v]
        log(f"B1 {v}: lost {tot['lost']:,} (module {t['lost']:,}), with later consolidations {tot['later']:,} "
            f"(module {t['later']:,}), restored {tot['restored']:,} (module {t['restored']:,}), modified "
            f"{tot['modified']:,}{' (module ' + format(t['modified'], ',') + ')' if 'modified' in t else ''}; "
            f"censored units whose trials disagree with K - entry {cens.height}; modified share {ms:.4f}, "
            f"restored share {rs:.4f} (draft {draft[v][0]}, {draft[v][1]})")
        mb = (W @ per["modified"].to_numpy()) / (W @ per["lost"].to_numpy())
        rb = (W @ per["restored"].to_numpy()) / (W @ per["later"].to_numpy())
        src = f"data/interim/{path.name}, data/interim/memory_versions.parquet (live rows)"
        out.append(row(
            f"B1: share of first losses that are modifications, rule set {v}", ms, *pct(mb),
            f"{A} standard agents; {tot['lost']:,} first losses",
            f"cluster bootstrap over standard agents ({B:,} resamples of {A} agents, ratio of summed counts), "
            "percentile", src))
        out.append(row(
            f"B1: share of lost units restored later, rule set {v}", rs, *pct(rb),
            f"{A} standard agents; {tot['later']:,} lost units with later consolidations",
            f"cluster bootstrap over standard agents ({B:,} resamples of {A} agents, ratio of summed counts), "
            "percentile; denominator = first losses before the agent's last consolidation", src))
    return out


# --- module B2 --------------------------------------------------------------------------------------


def module_b2(cfg: dict) -> list[dict]:
    from avsd.lineage import trees_stats as ts
    from avsd.lineage.trees import _ragged

    d = Path(cfg["paths"]["interim"]) / "b2"
    with open(d / "summary.pkl", "rb") as fh:
        summ = pickle.load(fh)
    main = summ["main"]
    out = []

    # B2-6: memory share of transmissions into generations 1 and 2 (agent-level view).
    e = main["edges"]
    ich = ts.H1_CHANNELS.index("chat_to_memory")
    sel = (e.gen == 1) | (e.gen == 2)
    gen, ch, root = e.gen[sel], e.ch[sel], e.root[sel]
    boot = ts.ClusterBoot(root, B, rng_for(6))
    Am = np.zeros((boot.C, 4))
    for j, g in enumerate((1, 2)):
        m = gen == g
        np.add.at(Am, (boot.inv[m], 2 * j), 1.0)
        np.add.at(Am, (boot.inv[m], 2 * j + 1), (ch[m] == ich).astype(float))
    Rm = boot.matmul(Am).astype(np.float64)
    tab = {int(r_["generation"]): r_ for r_ in main["generations"] if r_["generation"].isdigit()}
    for j, g in enumerate((1, 2)):
        m = gen == g
        est = float((ch[m] == ich).mean())
        lo, hi = pct(Rm[:, 2 * j + 1] / Rm[:, 2 * j])
        n_tr = int(m.sum())
        n_trees = len(np.unique(root[m]))
        log(f"B2 memory share g{g}: {est:.4f} (table {tab[g]['share_chat_to_memory']:.4f}), [{lo:.4f}, {hi:.4f}]; "
            f"{n_tr:,} transmissions, {n_trees:,} trees")
        out.append(row(
            f"B2: share of transmissions into generation {g} that go into another agent's memory", est, lo, hi,
            f"{n_tr:,} transmissions into generation {g} in {n_trees:,} trees",
            f"cluster bootstrap by agent-level tree root (Poisson(1) weights, {B:,} replicates, as in "
            "avsd.lineage.trees_stats), percentile; MAP forest of the last run",
            "data/interim/b2/summary.pkl (MAP forest edges)"))

    # B2-7: inheritance and reversion after a changed value (agent-to-agent retelling edges).
    occ = (pl.read_parquet(d / "occurrences.parquet", columns=["uidx", "ts_utc", "occ_uid", "qv_key", "qv_val"])
           .sort("uidx", "ts_utc", "occ_uid"))
    if occ.height != summ["n_occ"]:
        raise ValueError(f"{occ.height} occurrences against {summ['n_occ']} in the run")
    qk, qv = _ragged(occ["qv_key"]), _ragged(occ["qv_val"])
    del occ
    ea = main["edges_all"]
    sel3 = np.isin(ea.key, ts.AGENT_RETELL_KEYS)
    carried, changed, changes = ts.quantity_changes(ea, qk, qv, sel3)
    ref = next(r_ for r_ in main["h3_rows"] if r_["channel"] == "agent_retelling")
    log(f"B2 H3 check: contexts carried {int(carried[sel3].sum()):,} (run {ref['contexts_carried']:,}), changed "
        f"{int(changed[sel3].sum()):,} (run {ref['contexts_changed']:,})")
    kids_of: dict[int, list[int]] = defaultdict(list)
    for k, p in enumerate(ea.parent.tolist()):
        kids_of[p].append(k)
    roots, new_, old_ = [], [], []
    child = ea.child
    for k, key, new, old in changes:
        c = int(child[k])
        for k2 in kids_of.get(c, ()):
            g = int(child[k2])
            vals = {b for a, b in zip(qk[g].tolist(), qv[g].tolist()) if a == key}
            if not vals:
                continue
            roots.append(int(ea.root[k]))
            hit = bool(vals & new)
            new_.append(hit)
            old_.append(bool(vals & old) and not hit)
    roots, new_, old_ = np.array(roots), np.array(new_, float), np.array(old_, float)
    boot = ts.ClusterBoot(roots, B, rng_for(7))
    ones = np.ones(len(roots))
    ib = ts.boot_ratio(boot, new_, ones, boot.inv)
    rb = ts.boot_ratio(boot, old_, ones, boot.inv)
    n_trees = len(np.unique(roots))
    log(f"B2 inheritance: {len(roots):,} carried contexts (run {ref['n_grandchild_contexts']:,}) in {n_trees:,} trees; "
        f"inherited {new_.mean():.4f} (run {ref['inherited_share']:.4f}) {pct(ib)}, reverted {old_.mean():.4f} "
        f"(run {ref['reverted_share']:.4f}) {pct(rb)}")
    for name, est, bb in (("keep the new value", new_.mean(), ib), ("return to the parent's value", old_.mean(), rb)):
        out.append(row(
            f"B2: children of a node whose value changed on an agent-to-agent edge that {name}", float(est), *pct(bb),
            f"{len(roots):,} carried contexts in {n_trees:,} trees",
            f"cluster bootstrap by tree root of the changed edge (Poisson(1) weights, {B:,} replicates, as the H3 "
            "intervals), percentile; MAP forest of the last run",
            "data/interim/b2/summary.pkl (MAP forest edges), data/interim/b2/occurrences.parquet (quantity contexts)"))
    return out


# --- modules D2 to D4 ------------------------------------------------------------------------------


def module_d3(cfg: dict) -> list[dict]:
    from avsd.swarmsim.calibrate import goal_graphs
    from avsd.swarmsim.depgraph import stats_from_parts
    from avsd.swarmsim.depgraph_data import load_sessions

    T = Path(cfg["paths"]["tables"])
    interim = Path(cfg["paths"]["interim"])
    sessions = load_sessions(cfg)
    goals = pl.read_parquet(T / "village_goals.parquet", columns=["id", "start_time", "end_time"])
    edges = pl.read_parquet(interim / "depgraph" / "edges_main.parquet")
    gg = goal_graphs(sessions, edges, goals)
    gids = gg.goal_ids
    parts = [gg.parts[(g, "all")] for g in gids]
    obs = stats_from_parts(parts)
    G = len(gids)
    log(f"D3: {G} goals; mean parents {obs['mean_parents']:.5f}, edges skipping 2+ layers {obs['cross_layer_share']:.5f}, "
        f"out-degree Gini {obs['outdeg_gini']:.5f}; {int(obs['n_child_nodes']):,} steps with a parent, "
        f"{int(obs['n_edges']):,} edges, {int(obs['n_parent_nodes']):,} sessions with children")
    sum_in = np.array([p.indeg.sum() for p in parts], float)
    n_in = np.array([len(p.indeg) for p in parts], float)
    n_cross = np.array([p.n_cross for p in parts], float)
    n_edge = np.array([p.n_edges for p in parts], float)
    od_val = np.concatenate([p.outdeg for p in parts]).astype(float)
    od_goal = np.concatenate([np.full(len(p.outdeg), i) for i, p in enumerate(parts)])
    o = np.argsort(od_val, kind="stable")
    od_val, od_goal = od_val[o], od_goal[o]
    rng = rng_for(8)
    C = np.stack([np.bincount(rng.integers(0, G, G), minlength=G) for _ in range(B)]).astype(np.float64)
    mp = (C @ sum_in) / (C @ n_in)
    cl = (C @ n_cross) / (C @ n_edge)
    gi = np.concatenate([weighted_gini(od_val, C[i:i + 500][:, od_goal]) for i in range(0, B, 500)])
    gw = weighted_gini(od_val, np.ones((1, len(od_val))))[0]
    if abs(gw - obs["outdeg_gini"]) > 1e-9:
        raise ValueError(f"weighted Gini {gw} against {obs['outdeg_gini']}")

    # Session-level alternative: sessions resampled (Poisson(1) weights), each with its parent count, its
    # in-edges and its child count; the graphs stay fixed.
    goal_of = dict(zip(sessions["s"].to_list(), sessions["goal_id"].to_list(), strict=True))
    e = edges.with_columns(pl.col("parent").replace_strict(goal_of, default=None).alias("gp"),
                           pl.col("child").replace_strict(goal_of, default=None).alias("gc"))
    e = e.filter(pl.col("gp") == pl.col("gc"))
    layer = {}
    for g in gids:
        for s_, d_ in zip(gg.nodes[g].tolist(), gg.layer[g].tolist()):
            layer[int(s_)] = int(d_)
    lp = np.array([layer[int(x)] for x in e["parent"].to_list()])
    lc = np.array([layer[int(x)] for x in e["child"].to_list()])
    ch_ = e["child"].to_numpy().astype(np.int64)
    pa_ = e["parent"].to_numpy().astype(np.int64)
    n_s = int(sessions.height)
    indeg = np.bincount(ch_, minlength=n_s).astype(float)
    cross_in = np.bincount(ch_, weights=(lc - lp >= 2).astype(float), minlength=n_s)
    outdeg = np.bincount(pa_, minlength=n_s).astype(float)
    if (indeg.sum(), cross_in.sum()) != (obs["n_edges"], sum(p.n_cross for p in parts)) or \
            not np.array_equal(np.sort(outdeg[outdeg > 0]), od_val):
        raise ValueError("per-session counts do not reproduce the pooled graph parts")
    act = np.flatnonzero((indeg > 0) | (outdeg > 0))
    ind, cri, outd = indeg[act], cross_in[act], outdeg[act]
    has_p = (ind > 0).astype(float)
    po = np.flatnonzero(outd > 0)
    po = po[np.argsort(outd[po], kind="stable")]
    s_od = outd[po]
    rng = rng_for(9)
    mp_s, cl_s, gi_s = [], [], []
    for i in range(0, B, 250):
        Wp = rng.poisson(1.0, size=(min(250, B - i), len(act))).astype(np.float64)
        mp_s.append((Wp @ ind) / (Wp @ has_p))
        cl_s.append((Wp @ cri) / (Wp @ ind))
        gi_s.append(weighted_gini(s_od, Wp[:, po]))
    mp_s, cl_s, gi_s = np.concatenate(mp_s), np.concatenate(cl_s), np.concatenate(gi_s)
    out = []
    src = "data/interim/depgraph/edges_main.parquet (touch rules v2), session table (avsd.swarmsim.depgraph_data)"
    stats = (("mean parents per step (steps with >= 1 parent)", "mean_parents", mp, mp_s,
              f"{int(obs['n_child_nodes']):,} steps with a parent"),
             ("share of edges skipping 2 or more layers", "cross_layer_share", cl, cl_s,
              f"{int(obs['n_edges']):,} edges"),
             ("out-degree Gini (sessions with >= 1 child)", "outdeg_gini", gi, gi_s,
              f"{int(obs['n_parent_nodes']):,} sessions with children"))
    for name, key, bg, bs, nn in stats:
        log(f"D3 {key}: {obs[key]:.5f}; goals resampled {pct(bg)}; sessions resampled {pct(bs)}")
        out.append(row(f"D3: {name}, all edges, rules v2", float(obs[key]), *pct(bg),
                       f"{G} goals; {nn}",
                       f"bootstrap over goals ({B:,} resamples of the {G} goals, pooled statistic recomputed on the "
                       "resampled goals, a goal drawn twice counted twice), percentile", src))
        out.append(row(f"D3: {name}, all edges, rules v2 (session-level alternative)", float(obs[key]), *pct(bs),
                       f"{len(act):,} sessions with an edge in {G} goals; {nn}",
                       f"session cluster bootstrap (Poisson(1) weights, {B:,} replicates; each session carries its "
                       "parent count, its in-edges and its child count; graphs held fixed, so dependence between "
                       "sessions of a goal is ignored), percentile", src))
    return out


# --- driver -----------------------------------------------------------------------------------------


def render(r: dict) -> str:
    buf = io.StringIO(newline="")
    csv.DictWriter(buf, fieldnames=COLUMNS).writerow(
        {k: (f"{r[k]:.6f}" if isinstance(r[k], float) else r[k]) for k in COLUMNS})
    return buf.getvalue()


def write(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        csv.DictWriter(fh, fieldnames=COLUMNS).writeheader()
        for r in rows:
            fh.write(render(r))
    tmp.replace(path)


def add_missing(rows: list[dict], path: Path) -> int:
    """Insert the rows whose quantity the table lacks, each after the row computed before it; every line
    already in the table stays byte for byte."""
    with open(path, newline="", encoding="utf-8") as fh:
        lines = fh.readlines()
    have = [r["quantity"] for r in csv.DictReader(io.StringIO("".join(lines)))]
    if len(lines) != len(have) + 1:
        raise ValueError(f"{path}: rows span several lines")
    pos = {q: i + 1 for i, q in enumerate(have)}
    added, anchor = 0, 0
    for r in rows:
        q = r["quantity"]
        if q in pos:
            anchor = pos[q]
            continue
        anchor += 1
        lines.insert(anchor, render(r))
        pos = {k: (v + 1 if v >= anchor else v) for k, v in pos.items()}
        pos[q] = anchor
        added += 1
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        fh.writelines(lines)
    tmp.replace(path)
    return added


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", default=None)
    ap.add_argument("--only", nargs="*", choices=("a", "b1", "b2", "d3"), default=None,
                    help="compute these modules and print them; the table is written only by a full run")
    ap.add_argument("--add-missing", action="store_true",
                    help="with --only: insert the computed rows the table lacks and leave its other lines as they are")
    a = ap.parse_args(argv)
    if a.add_missing and a.only is None:
        ap.error("--add-missing needs --only")
    for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(v, "1")
    cfg = load_config(a.config)
    if int(cfg.get("seed", SEED)) != SEED:
        raise ValueError(f"config seed {cfg.get('seed')} is not {SEED}")
    t0 = time.time()
    todo = a.only or ["a", "b1", "b2", "d3"]
    fns = {"a": module_a, "b1": module_b1, "b2": module_b2, "d3": module_d3}
    rows: list[dict] = []
    for m in todo:
        t = time.time()
        rows += fns[m](cfg)
        log(f"{m} done in {time.time() - t:.0f} s")
    for r in rows:
        print(f"{r['quantity']}: {r['value']:.4f} [{r['ci_lo']:.4f}, {r['ci_hi']:.4f}] | n: {r['n']}")
    path = Path(cfg["paths"]["outputs"]) / "tables" / "writeup_cis.csv"
    if a.only is None:
        write(rows, path)
        log(f"wrote {path} ({len(rows)} rows) in {time.time() - t0:.0f} s")
    elif a.add_missing:
        log(f"added {add_missing(rows, path)} rows to {path}")


if __name__ == "__main__":
    main()
