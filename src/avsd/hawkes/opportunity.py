"""Action-opportunity model, the scheduling check of module A (SPEC 5.6-4).

Agents act in their own loops, so part of when they post is set by the schedule. Conditional on
agent i taking an action at t_e, the model asks whether recent events of source j make that action
a message. Actions are the agent's rows of the SPEC's events table inside the window's
realizations: chat messages, session starts and ends, history searches, waits, pauses and other
main-loop events (no computer-use turns, no duplicate rows). The outcome is 1 for a message in the
group's room; messages in other rooms are left out. The features are the decayed counts of SPEC
5.6-4, x_{e,j,m} = sum over events l of source j earlier on the same realization of
exp(-beta_m (t_e - t_l)), for the window's agents and the exogenous sources. One L2-penalized
logistic regression per agent (standardized features, C = 1) gives coefficients gamma_ijm; the
integrated effect of one j event, I_ij = sum_m gamma_ijm (1 - exp(-beta_m L)) / beta_m (log-odds
times seconds over (0, L]), is the analogue of the branching ratio n_ij = sum_m alpha_ijm (1 -
exp(-beta_m L)). We compare the two j -> i rankings with Spearman correlations.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import polars as pl
from numba import njit
from scipy import stats

from avsd.hawkes.model import HawkesFit
from avsd.hawkes.windows import WindowData

ACTION_KINDS = ("agent_msg", "session_start", "session_end", "search_history", "wait", "pause", "other")
MIN_CLASS = 20      # each outcome at least this often for an agent's regression
C_L2 = 1.0


def load_actions(processed: Path) -> pl.DataFrame:
    """Agent action rows: actor_id, kind, room_id, realization_id, t (seconds since the block start)."""
    return (
        pl.scan_parquet(Path(processed) / "events_unified.parquet")
        .filter((pl.col("actor_type") == "agent") & pl.col("source").is_in(["chat", "event", "session"])
                & pl.col("dup_of_uid").is_null() & pl.col("kind").is_in(ACTION_KINDS) & pl.col("in_run"))
        .select("actor_id", pl.col("kind").cast(pl.String), "room_id", "realization_id", pl.col("t_in_day").alias("t"))
        .collect()
    )


@njit(cache=True)
def decayed_counts(src_t, src_j, act_t, n_src, beta):
    """x[a, j, m] = sum over source events l of source j with src_t[l] < act_t[a] of
    exp(-beta_m (act_t[a] - src_t[l])); src_t and act_t sorted ascending."""
    M = beta.size
    out = np.zeros((act_t.size, n_src, M))
    S = np.zeros((n_src, M))
    last = 0.0
    p = 0
    for a in range(act_t.size):
        t = act_t[a]
        while p < src_t.size and src_t[p] < t:
            for m in range(M):
                f = np.exp(-beta[m] * (src_t[p] - last))
                for j in range(n_src):
                    S[j, m] *= f
            last = src_t[p]
            for m in range(M):
                S[src_j[p], m] += 1.0
            p += 1
        for m in range(M):
            f = np.exp(-beta[m] * (t - last))
            for j in range(n_src):
                out[a, j, m] = S[j, m] * f
    return out


def design(data: WindowData, actions: pl.DataFrame, beta: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(X (n, K + H, M), y (n,), agent dimension (n,)) over the window's realizations."""
    K, H = data.K, len(data.days[0].exo_times) if data.days else 2
    dim = {a: k for k, a in enumerate(data.agent_ids)}
    act = actions.filter(pl.col("realization_id").is_in(data.realizations) & pl.col("actor_id").is_in(data.agent_ids))
    is_msg = pl.col("kind") == "agent_msg"
    act = act.filter(~is_msg | (pl.col("room_id") == data.window.room_id)).with_columns(is_msg.alias("y"))
    parts = act.sort("t").partition_by("realization_id", as_dict=True)
    Xs, ys, ds = [], [], []
    for rid, day in zip(data.realizations, data.days):
        a = parts.get((rid,))
        if a is None or a.is_empty():
            continue
        t = np.concatenate([day.agent_times, *day.exo_times])
        j = np.concatenate([day.agent_dims, *(np.full(x.size, K + h) for h, x in enumerate(day.exo_times))])
        o = np.argsort(t, kind="stable")
        Xs.append(decayed_counts(t[o], j[o].astype(np.int64), a["t"].to_numpy().astype(np.float64), K + H, beta))
        ys.append(a["y"].to_numpy()), ds.append(np.array([dim[x] for x in a["actor_id"]]))
    if not Xs:
        return np.empty((0, K + H, beta.size)), np.empty(0, bool), np.empty(0, np.int64)
    return np.concatenate(Xs), np.concatenate(ys), np.concatenate(ds)


def influence(X: np.ndarray, y: np.ndarray, beta: np.ndarray, max_lag: float, C: float = C_L2) -> np.ndarray | None:
    """I_j for one agent (module docstring), or None when an outcome is rarer than MIN_CLASS."""
    from sklearn.linear_model import LogisticRegression

    if y.sum() < MIN_CLASS or (~y).sum() < MIN_CLASS:
        return None
    n, J, M = X.shape
    Z = X.reshape(n, J * M)
    mu, sd = Z.mean(0), Z.std(0)
    ok = sd > 0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        lr = LogisticRegression(C=C, max_iter=5000).fit((Z[:, ok] - mu[ok]) / sd[ok], y)
    gamma = np.zeros(J * M)
    gamma[ok] = lr.coef_[0] / sd[ok]
    return (gamma.reshape(J, M) * (-np.expm1(-beta * max_lag)) / beta).sum(1)


def compare(data: WindowData, f: HawkesFit, actions: pl.DataFrame) -> dict:
    """Spearman correlations between the Hawkes and the action-opportunity j -> i rankings."""
    beta, L = f.spec.beta, f.spec.max_lag
    X, y, d = design(data, actions, beta)
    K = data.K
    infl = np.full((K, f.n.shape[1]), np.nan)
    for i in range(K):
        sel = d == i
        r = influence(X[sel], y[sel], beta, L)
        if r is not None:
            infl[i] = r
    fitted = ~np.isnan(infl[:, 0])
    off = ~np.eye(K, dtype=bool) & fitted[:, None]
    n_aa, i_aa = f.n[:, :K][off], infl[:, :K][off]
    out = {"n_actions": int(y.size), "msg_share": float(y.mean()) if y.size else float("nan"),
           "agents_fitted": int(fitted.sum()), "pairs": int(off.sum())}
    rho_s, p = stats.spearmanr(n_aa, i_aa) if off.sum() >= 5 else (float("nan"), float("nan"))
    out.update(spearman=float(rho_s), spearman_p=float(p))
    per = [stats.spearmanr(f.n[i, :K][off[i]], infl[i, :K][off[i]])[0] for i in range(K) if off[i].sum() >= 4]
    per = [x for x in per if np.isfinite(x)]
    out["spearman_per_agent_mean"] = float(np.mean(per)) if per else float("nan")
    out["n_agents_per_agent"] = len(per)
    if fitted.sum() >= 5:
        out["spearman_self"] = float(stats.spearmanr(np.diag(f.n)[fitted], np.diag(infl[:, :K])[fitted])[0])
    else:
        out["spearman_self"] = float("nan")
    top = [i for i in range(K) if off[i].sum() >= 2]
    agree = [int(np.argmax(np.where(off[i], f.n[i, :K], -np.inf)) == np.argmax(np.where(off[i], infl[i, :K], -np.inf)))
             for i in top]
    out["top_source_agree"] = float(np.mean(agree)) if agree else float("nan")
    out["n_top"] = len(agree)
    # Disagreements: pairs in the top decile of one ranking and the bottom half of the other.
    dis = []
    if off.sum() >= 10:
        rn = stats.rankdata(n_aa) / n_aa.size
        ri = stats.rankdata(i_aa) / i_aa.size
        cells = np.argwhere(off)
        for (i, j), a, b in zip(cells, rn, ri):
            if (a > 0.9 and b <= 0.5) or (b > 0.9 and a <= 0.5):
                dis.append({"target": data.agent_names[i], "source": data.agent_names[j], "hawkes_rank": float(a),
                            "opportunity_rank": float(b), "n": float(f.n[i, j]), "influence": float(infl[i, j])})
    out["n_disagree"] = len(dis)
    out["disagreements"] = dis
    out["influence"] = infl
    return out
