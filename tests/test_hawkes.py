import dataclasses

import numpy as np
import polars as pl
import pytest
from scipy import integrate, stats

from avsd.config import load_config
from avsd.hawkes import (
    SHARES, STARTS, BootstrapResult, Day, HawkesFit, HawkesSpec, Recovery, bootstrap_reps, compensator_at_events,
    decompose, fit, kernel_classes, label_shares, loglik, pack, pool_exogenous, recovery_check, select_l1,
    share_names, simulate, time_rescaling,
)
from avsd.hawkes.model import NEWTON_TOL, _fit_pack

SEED = 20261003
SPEC = HawkesSpec()
H = 3600.0


def _sources(day, K):
    """(time, source) of every agent and exogenous event of a day."""
    return list(zip(day.agent_times, day.agent_dims)) + [
        (t, K + h) for h, x in enumerate(day.exo_times) for t in x]


def _ref_intensity(day, K, i, s, mu, alpha, spec=SPEC):
    b = min(int(s // spec.bin_width), spec.n_bins - 1)
    if s == day.T and s > 0 and s % spec.bin_width == 0 and s // spec.bin_width <= spec.n_bins - 1:
        b -= 1
    lam = mu[i, b]
    for tl, j in _sources(day, K):
        dt = s - tl
        if 0 < dt <= spec.max_lag:
            lam += np.sum(alpha[i, j] * spec.beta * np.exp(-spec.beta * dt))
    return lam


def _ref_loglik(days, K, mu, alpha, spec=SPEC):
    """Slow pure-numpy log-likelihood straight from the SPEC 5.2 formulas."""
    ll = 0.0
    for day in days:
        for t, i in zip(day.agent_times, day.agent_dims):
            ll += np.log(_ref_intensity(day, K, i, t, mu, alpha, spec))
        src = _sources(day, K)
        for i in range(K):
            for b in range(spec.n_bins):
                hi = day.T if b == spec.n_bins - 1 else min(day.T, (b + 1) * spec.bin_width)
                ll -= mu[i, b] * max(hi - b * spec.bin_width, 0.0)
            for tl, j in src:
                ll -= np.sum(alpha[i, j] * (1 - np.exp(-spec.beta * min(spec.max_lag, day.T - tl))))
    return ll


def _tiny_days(rng, K=3):
    days = []
    for T in (2.5 * H, 7 * H, 9.3 * H):
        n = rng.integers(8, 20)
        at = np.sort(rng.uniform(0, T, n))
        at[1] = at[2]                      # tie
        at[-1] = T                         # event at exactly T_d
        days.append(Day(T, at, rng.integers(0, K, n), np.sort(rng.uniform(0, T, rng.integers(2, 6)))))
    days.append(Day(1.5 * H, np.empty(0), np.empty(0, np.int64), rng.uniform(0, 1.5 * H, 4)))
    return days


def _tiny_params(rng, K=3):
    return rng.uniform(1e-4, 1e-3, (K, SPEC.n_bins)), rng.uniform(0, 0.05, (K, K + 1, SPEC.M))


def _params_from_n(n, w):
    """alpha_ij^(m) = n_ij * w_ijm / (1 - exp(-beta_m L))."""
    return n[..., None] * w / -np.expm1(-SPEC.beta * SPEC.max_lag)


def _fixed(mu, alpha):
    """A HawkesFit at given parameters (no EM)."""
    return HawkesFit(SPEC, mu, alpha, np.empty(0), np.empty(0), 0, True, 0)


def _mean_delay(alpha):
    """Mean delay (s) of all excitation pooled, each kernel truncated at L."""
    trunc = -np.expm1(-SPEC.beta * SPEC.max_lag)
    mass = (alpha * trunc).sum((0, 1))
    md = 1 / SPEC.beta - SPEC.max_lag * np.exp(-SPEC.beta * SPEC.max_lag) / trunc
    return float((mass * md).sum() / mass.sum())


# --- 1. likelihood and compensator -----------------------------------------


def test_loglik_matches_reference():
    rng = np.random.default_rng(SEED)
    days = _tiny_days(rng)
    for _ in range(3):
        mu, alpha = _tiny_params(rng)
        assert loglik(days, 3, mu, alpha) == pytest.approx(_ref_loglik(days, 3, mu, alpha), rel=1e-9)


def test_compensator_matches_quadrature():
    rng = np.random.default_rng(SEED + 1)
    days = _tiny_days(rng)
    mu, alpha = _tiny_params(rng)
    pk = pack(days, 3)
    lam = compensator_at_events(pk, _fixed(mu, alpha))
    day = days[2]
    ev = np.flatnonzero(pk.tgt_day == 2)
    src_t = np.concatenate([day.agent_times, day.human_times])
    brk = np.unique(np.concatenate([src_t, src_t + SPEC.max_lag, np.arange(1, 9) * H]))
    for k in ev[::3]:
        t, i = pk.ev_t[pk.tgt_ev[k]], pk.tgt_dim[k]
        pts = brk[(brk > 0) & (brk < t)]
        edges = np.concatenate([[0.0], pts, [t]])
        ref = sum(integrate.quad(lambda s: _ref_intensity(day, 3, i, s, mu, alpha), a, b,
                                 epsabs=0, epsrel=1e-11, limit=200)[0]
                  for a, b in zip(edges[:-1], edges[1:]) if b > a)
        assert lam[k] == pytest.approx(ref, rel=1e-8)


# --- shared simulated data --------------------------------------------------

K4 = 4


def _truth():
    n_aa = np.array([[0.15, 0.20, 0.00, 0.00],
                     [0.00, 0.10, 0.25, 0.00],
                     [0.20, 0.00, 0.00, 0.15],
                     [0.00, 0.15, 0.10, 0.10]])
    n_aa *= 0.5 / np.abs(np.linalg.eigvals(n_aa)).max()
    n = np.hstack([n_aa, [[0.35], [0.25], [0.30], [0.15]]])
    shapes = np.array([[0.7, 0.2, 0.1], [0.2, 0.6, 0.2], [0.1, 0.3, 0.6]])
    w = shapes[np.arange(K4 * (K4 + 1)).reshape(K4, K4 + 1) % 3]
    profile = np.array([2.5, 1.5, 1, 1, 1, 1, 1, 1])
    mu = np.array([3.0, 4.0, 2.5, 3.5])[:, None] * profile / H
    return mu, _params_from_n(n, w), n


def _simulate(n_days, seed, human_rate=8 / H):
    mu, alpha, _ = _truth()
    rng = np.random.default_rng(seed)
    Ts = rng.uniform(4 * H, 8 * H, n_days)
    hum = [np.sort(rng.uniform(0, T, rng.poisson(human_rate * T))) for T in Ts]
    return simulate(mu, alpha, list(Ts), hum, rng)


@pytest.fixture(scope="module")
def recovery():
    days, labels = _simulate(60, SEED)
    pk = pack(days, K4)
    return days, labels, pk, fit(pk, K4)


def test_simulator_at_true_parameters():
    """Checks the simulator itself, which the recovery tests cannot: at the true
    parameters the compensator increments are Exp(1), and background events per
    (agent, hour bin) are Poisson(mu * exposure)."""
    mu, alpha, _ = _truth()
    days, labels = _simulate(200, SEED + 7)
    pk = pack(days, K4)
    res = time_rescaling(pk, _fixed(mu, alpha))
    assert np.all(res.ks_pvalue > 1e-3), res.ks_pvalue
    assert res.pooled.mean() == pytest.approx(1.0, abs=0.02)
    bg = np.concatenate(labels) < 0
    cell = np.concatenate([d.agent_dims * SPEC.n_bins + SPEC.bins(d.agent_times, d.T) for d in days])
    obs = np.bincount(cell[bg], minlength=mu.size)
    exp = (mu * pk.E.sum(0)).ravel()
    assert stats.chi2.sf(((obs - exp) ** 2 / exp).sum(), mu.size) > 1e-3


# --- 2. EM monotonicity -----------------------------------------------------


@pytest.mark.parametrize("l1,accelerate", [(0.0, False), (5.0, False), (0.0, True), (5.0, True)])
def test_em_monotone(l1, accelerate):
    days, _ = _simulate(15, SEED + 2)
    f = fit(days, K4, l1=l1, tol=0.0, max_iter=150, accelerate=accelerate)
    assert f.n_iter == 150 and f.loglik.size == 151
    assert f.n_violations == 0
    obj = f.objective
    assert np.all(np.diff(obj) >= -1e-9 * np.abs(obj[:-1]))
    if l1 == 0:
        np.testing.assert_array_equal(f.loglik, f.objective)
    else:
        assert f.alpha.sum() < fit(days, K4, tol=0.0, max_iter=150, accelerate=accelerate).alpha.sum()


def test_squarem_reaches_em_fixed_point():
    days, _ = _simulate(15, SEED + 5)
    pk = pack(days, K4)
    a = fit(pk, K4)
    e = fit(pk, K4, tol=1e-10, xtol=np.inf, max_iter=20000, accelerate=False)
    assert a.converged and a.n_iter < e.n_iter / 5
    assert a.loglik[-1] == pytest.approx(e.loglik[-1], abs=1.0)
    assert np.abs(a.n - e.n).max() < 0.03


# --- 3. parameter recovery --------------------------------------------------


def _share_err(days, labels, pk, f):
    true = label_shares(days, labels, K4)
    got = decompose(pk, f).shares
    return np.array([got[s] - true[s] for s in SHARES])


def test_recovery(recovery):
    """Checks the implementation on a data-rich fixture (17k events). This is not
    the SPEC 5.6-1 acceptance test, which recovery_check runs per window at the
    window's real size (small windows fail it; see test_small_window_recovery)."""
    days, labels, pk, f = recovery
    _, alpha_true, n_true = _truth()
    assert f.converged and f.n_violations == 0
    err = _share_err(days, labels, pk, f)
    assert np.abs(err).mean() < 0.05 and np.abs(err).max() < 0.1, err
    err = np.abs(f.n - n_true)
    assert err.mean() < 0.05 and err.max() < 0.15, np.round(f.n, 3)
    assert f.n[n_true == 0].mean() < 0.04
    assert np.corrcoef(f.n.ravel(), n_true.ravel())[0, 1] > 0.9
    assert f.rho == pytest.approx(0.5, abs=0.1)
    # Baseline and kernel shapes are only weakly identified per cell at this size
    # (single n_ij delays can be off by 3x); coarse pooled summaries are recovered.
    prof = f.mu.sum(0)
    assert prof[0] > 1.8 * np.median(prof[2:]) and prof[1] > np.median(prof[2:]), prof
    assert _mean_delay(f.alpha) == pytest.approx(_mean_delay(alpha_true), rel=0.5)


def test_default_stop_is_near_the_maximum(recovery):
    """Iterating on from the default fit gains little and moves nothing. The SPEC
    5.3 objective-only rule (relative change 1e-6) stops several nats short."""
    _, _, pk, f = recovery
    g = fit(pk, K4, xtol=1e-6, init=(f.mu, f.alpha))
    assert g.converged
    assert g.loglik[-1] - f.loglik[-1] < 0.02
    a, b = decompose(pk, f).shares, decompose(pk, g).shares
    assert max(abs(a[s] - b[s]) for s in SHARES) < 0.005
    assert f.rho == pytest.approx(g.rho, abs=0.005)
    spec_rule = fit(pk, K4, tol=1e-6, xtol=np.inf)
    assert spec_rule.converged and g.loglik[-1] - spec_rule.loglik[-1] > 1.0


def test_time_rescaling_on_correct_model(recovery):
    _, _, pk, f = recovery
    res = time_rescaling(pk, f)
    assert (res.n == pk.counts(np.ones(pk.n_days))).all()
    assert np.all(res.ks_pvalue > 1e-3), res.ks_pvalue
    assert time_rescaling(pk, f, pool="day").n.sum() == res.n.sum()
    # Power: a Poisson model with the per-bin rates is rejected.
    counts = np.zeros((K4, SPEC.n_bins))
    np.add.at(counts, (pk.tgt_dim, pk.tgt_bin), 1.0)
    poisson = _fixed(counts / pk.E.sum(0), np.zeros_like(f.alpha))
    assert time_rescaling(pk, poisson).ks_pvalue.min() < 1e-6


def test_decomposition_and_parents(recovery):
    _, _, pk, f = recovery
    dec = decompose(pk, f)
    assert sum(dec.shares.values()) == pytest.approx(1.0)
    assert np.allclose(dec.by_dim.sum(1), 1.0)
    assert set(dec.parents.columns) == {"event_uid", "parent_uid", "prob"}
    assert dec.parents["prob"].min() >= 0.01
    tot = dec.parents.group_by("event_uid").agg(p=pl.col("prob").sum())
    assert tot["p"].max() <= 1 + 1e-9 and tot.height == pk.tgt_ev.size


def test_parent_probabilities_sum_to_one():
    rng = np.random.default_rng(SEED + 6)
    days = _tiny_days(rng)
    uids = [np.array([f"x{d}_{k}" for k in range(day.agent_times.size)]) for d, day in enumerate(days)]
    days = [Day(day.T, day.agent_times, day.agent_dims, day.human_times, agent_uids=u)
            for day, u in zip(days, uids)]
    par = decompose(days, fit(days, 3), min_prob=0.0).parents
    tot = par.group_by("event_uid").agg(p=pl.col("prob").sum())
    assert tot.height == sum(u.size for u in uids)
    np.testing.assert_allclose(tot["p"].to_numpy(), 1.0, rtol=1e-12)
    assert par.filter(pl.col("parent_uid").str.starts_with("x")).height > 0


def test_bootstrap_chunks_are_independent():
    days, _ = _simulate(12, SEED + 3)
    f = fit(days, K4)
    pk = pack(days, K4)
    whole = bootstrap_reps(pk, f, 0, 4, SEED, xtol=1e-4)
    parts = BootstrapResult.concat([bootstrap_reps(pk, f, 2, 4, SEED, xtol=1e-4),
                                    bootstrap_reps(pk, f, 0, 2, SEED, xtol=1e-4)])
    np.testing.assert_array_equal(whole.shares, parts.shares)
    np.testing.assert_array_equal(whole.n, parts.n)
    assert whole.converged.all()
    ci = whole.ci()
    assert ci["shares"].shape == (4, 2) and ci["n"].shape == (K4, K4 + 1, 2)
    assert np.all(ci["shares"][:, 0] <= ci["shares"][:, 1])
    assert np.allclose(whole.shares.sum(1), 1.0)
    whole.converged[2] = False
    with pytest.warns(RuntimeWarning, match="1 of 4"):
        whole.ci()


# --- 3b. small windows and SPEC 5.6-1 ----------------------------------------


def test_select_l1_and_recovery_check():
    days, _ = _simulate(6, SEED + 8)
    pk = pack(days, K4)
    assert np.allclose(pk.day_T, [d.T for d in days])
    assert all(np.array_equal(h, d.human_times) for h, d in zip(pk.human_times(), days))
    sel = select_l1(pk, K4, grid=(1e4, 0.0, 5.0), n_folds=3)
    assert sel.folds.tolist() == [0, 1, 2, 0, 1, 2] and sel.grid.tolist() == [0.0, 5.0, 1e4]
    assert np.isfinite(sel.score).all() and sel.l1 == sel.grid[np.argmax(sel.score)]
    assert sel.score[-1] < sel.score[0]        # no excitation predicts held-out days worse
    f = fit(pk, K4, l1=sel.l1)
    rec = recovery_check(pk, f, n_rep=2, seed=SEED)
    assert rec.shares.shape == rec.true_shares.shape == (2, 4)
    assert np.allclose(rec.true_shares.sum(1), 1.0) and np.allclose(rec.shares.sum(1), 1.0)
    assert rec.converged.all() and rec.mae.shape == (2,) and list(rec.bias) == list(SHARES)


@pytest.mark.xfail(strict=True, reason="small windows miss SPEC 5.6-1; see avsd.hawkes.validate")
def test_small_window_recovery():
    """Realistic goal-window shape: K=10 agents, 5 run days of about 3.5 h, about
    3.2k agent messages, a dense truth like the real unpenalized fits, and an
    independent kernel shape in every cell. Share MAE is about 0.09 because
    self-excitation is credited to other agents, and a CV-chosen L1 does not fix
    it. kernel_sharing="class" gives 0.08 here (the truth has no class
    structure). On the class-structured grid truths of
    scripts/hawkes_recovery_grid.py class sharing halves the per-cell error but
    its SPEC four-way MAE is still 0.054-0.069 by K; whether a real window meets
    the bar depends on its own regime (scripts/hawkes_matched_recovery.py). This
    test turns XPASS when that changes."""
    K = 10
    rng = np.random.default_rng(SEED + 10)
    n_aa = rng.gamma(0.5, 1, (K, K)) * (rng.uniform(size=(K, K)) < 0.5) + np.diag(rng.uniform(0.5, 1.5, K))
    n_aa *= 0.85 / np.abs(np.linalg.eigvals(n_aa)).max()
    n = np.hstack([n_aa, rng.uniform(0.3, 1.0, (K, 1))])
    alpha = _params_from_n(n, rng.dirichlet(np.ones(3), (K, K + 1)))
    mu = rng.uniform(0.5, 1.5, (K, 1)) * np.full((K, SPEC.n_bins), 75 / 3.5 / K / H)
    Ts = rng.uniform(3.15 * H, 3.85 * H, 5)
    hum = [np.sort(rng.uniform(0, T, rng.poisson(3 * T / H))) for T in Ts]
    days, labels = simulate(mu, alpha, list(Ts), hum, rng)
    true = label_shares(days, labels, K)
    got = decompose(days, fit(days, K)).shares
    assert np.mean([abs(got[s] - true[s]) for s in SHARES]) < 0.05


# --- 5. kernel sharing and several exogenous sources -------------------------

EXO = ("human", "system")


def _shared_alpha(n, wc, sharing, exo=EXO):
    """alpha_ij^(m) = n_ij w_{c(i,j),m} / (1 - exp(-beta_m L))."""
    cls, _ = kernel_classes(n.shape[0], exo, sharing)
    return SPEC.alpha_from(n, wc[cls])


def _tiny_exo_days(rng, K=3):
    """_tiny_days with a sparse second exogenous source."""
    return [Day(d.T, d.agent_times, d.agent_dims,
                exo_times=(d.human_times, np.sort(rng.uniform(0, d.T, rng.integers(1, 4)))))
            for d in _tiny_days(rng, K)]


def _truth_shared():
    """K4 agents, a human and a system source, one kernel shape per class."""
    _, _, n = _truth()
    n = np.hstack([n, [[0.30], [0.20], [0.40], [0.25]]])
    wc = np.array([[0.2, 0.5, 0.3],     # self
                   [0.6, 0.3, 0.1],     # other agents
                   [0.5, 0.4, 0.1],     # human
                   [0.8, 0.15, 0.05]])  # system
    mu = _truth()[0]
    return mu, _shared_alpha(n, wc, "class"), n, wc


def _simulate_shared(n_days, seed, rates=(8 / H, 3 / H)):
    mu, alpha, _, _ = _truth_shared()
    rng = np.random.default_rng(seed)
    Ts = rng.uniform(4 * H, 8 * H, n_days)
    exo = [tuple(np.sort(rng.uniform(0, T, rng.poisson(r * T))) for r in rates) for T in Ts]
    return simulate(mu, alpha, list(Ts), exo, rng)


@pytest.fixture(scope="module")
def shared_recovery():
    days, labels = _simulate_shared(60, SEED + 23)
    pk = pack(days, K4, exo_names=EXO)
    return days, labels, pk, fit(pk, K4, kernel_sharing="class")


def test_shared_loglik_matches_reference():
    rng = np.random.default_rng(SEED + 20)
    days = _tiny_exo_days(rng)
    for sharing, C in (("class", 4), ("global", 1)):
        mu = rng.uniform(1e-4, 1e-3, (3, SPEC.n_bins))
        alpha = _shared_alpha(rng.uniform(0, 0.3, (3, 5)), rng.dirichlet(np.ones(3), C), sharing)
        assert loglik(days, 3, mu, alpha) == pytest.approx(_ref_loglik(days, 3, mu, alpha), rel=1e-9)
    f = fit(days, 3, kernel_sharing="class")
    assert f.n_violations == 0 and f.class_names == ("self", "other", *EXO) and f.w.shape == (4, SPEC.M)
    assert f.loglik[-1] == pytest.approx(_ref_loglik(days, 3, f.mu, f.alpha), rel=1e-9)
    live = f.n > 0                         # every live cell has its class's kernel shape
    np.testing.assert_allclose(f.weights[live], f.w[f.classes][live], rtol=1e-9, atol=1e-12)
    np.testing.assert_allclose(f.w.sum(1), 1.0)


def test_ecm_mstep_reaches_the_maximum_of_q():
    """Each CM cycle raises the penalized Q of the module docstring, and the
    cycles converge to its maximum over n >= 0 and the simplex."""
    from scipy.optimize import minimize

    from avsd.hawkes.model import _class_sum, _ecm
    rng = np.random.default_rng(SEED + 22)
    K, M = 3, SPEC.M
    cls, names = kernel_classes(K, EXO, "class")
    C, nc = len(names), K * (K + 2)
    S, G, lam = rng.gamma(1.0, 5.0, (K, K + 2, M)), rng.uniform(5, 50, (K + 2, M)), 2.0

    def q(n, wc):
        return ((S.sum(-1) * np.log(n)).sum() + (_class_sum(S, cls, C) * np.log(wc)).sum()
                - (n * ((wc[cls] * G).sum(-1) + lam)).sum())

    n, wc = np.full((K, K + 2), 0.1), np.full((C, M), 1 / M)
    qs = [q(n, wc)]
    for _ in range(300):
        n, wc = _ecm(n, wc, S, G, cls, C, lam, 1)
        qs.append(q(n, wc))
    assert np.all(np.diff(qs) >= -1e-12 * abs(qs[0]))

    def neg(z):
        v = z[nc:].reshape(C, M)
        e = np.exp(v - v.max(1, keepdims=True))
        return -q(np.exp(z[:nc]).reshape(K, K + 2), e / e.sum(1, keepdims=True))

    z0 = np.log(np.concatenate([np.full(nc, 0.1), np.full(C * M, 1 / M)]))
    best = minimize(neg, z0, method="BFGS", options={"gtol": 1e-9})
    assert qs[-1] == pytest.approx(-best.fun, rel=1e-9)


@pytest.mark.parametrize("sharing,l1,accelerate,scope", [
    ("class", 0.0, False, "all"), ("class", 5.0, False, "all"), ("class", 0.0, True, "all"),
    ("class", 5.0, True, "all"), ("global", 0.0, True, "all"), ("cell", 5.0, True, "all"),
    ("class", 5.0, True, "cross"), ("cell", 5.0, False, "cross")])
def test_ecm_monotone(sharing, l1, accelerate, scope):
    days, _ = _simulate_shared(15, SEED + 21)
    f = fit(days, K4, l1=l1, tol=0.0, max_iter=150, accelerate=accelerate, kernel_sharing=sharing,
            l1_scope=scope)
    assert f.n_violations == 0 and f.objective.size == f.n_iter + 1 >= 100
    obj = f.objective
    assert np.all(np.diff(obj) >= -1e-9 * np.abs(obj[:-1]))
    if l1 == 0:
        np.testing.assert_array_equal(f.loglik, f.objective)
    else:
        pen = f.n.sum() if scope == "all" else f.n[:, :K4].sum() - np.trace(f.n)
        assert f.loglik[-1] - f.objective[-1] == pytest.approx(l1 * pen, rel=1e-9)


def test_l1_scope_leaves_self_and_exogenous_unpenalized():
    days, _ = _simulate_shared(15, SEED + 26)
    pk = pack(days, K4, exo_names=EXO)
    one = ("default",)
    free = fit(pk, K4, kernel_sharing="class", starts=one)
    cross = fit(pk, K4, l1=50.0, kernel_sharing="class", l1_scope="cross", starts=one)
    full = fit(pk, K4, l1=50.0, kernel_sharing="class", starts=one)
    off = ~np.eye(K4, dtype=bool)
    assert cross.n[:, :K4][off].sum() < 0.8 * free.n[:, :K4][off].sum()
    assert full.n[:, K4:].sum() < cross.n[:, K4:].sum()
    assert np.trace(full.n) < np.trace(cross.n)
    with pytest.raises(ValueError):
        fit(pk, K4, l1=1.0, l1_scope="self")


def test_shared_squarem_reaches_ecm_fixed_point():
    days, _ = _simulate_shared(15, SEED + 25)
    pk = pack(days, K4, exo_names=EXO)
    a = fit(pk, K4, kernel_sharing="class", starts=("default",))
    e = fit(pk, K4, kernel_sharing="class", tol=1e-10, xtol=np.inf, max_iter=20000, accelerate=False,
            starts=("default",))
    assert a.converged and a.n_iter < e.n_iter / 3
    assert a.loglik[-1] == pytest.approx(e.loglik[-1], abs=0.5)
    assert np.abs(a.n - e.n).max() < 0.03 and np.abs(a.w - e.w).max() < 0.03


def test_nearly_empty_class_does_not_hold_the_fit_open():
    """A source that fired only a few times leaves its class shape on a flat
    ridge; the EM step test weighs parameters by the events they carry and the
    Newton stage moves along the ridge, so the fit still stops at the maximum
    instead of running to max_iter."""
    pk = pack(_simulate_shared(8, SEED + 27, rates=(8 / H, 0.05 / H))[0], K4, exo_names=EXO)
    assert 0 < sum(x[1].size for x in pk.exo_times()) <= 6
    f = fit(pk, K4, kernel_sharing="class")
    assert f.converged and f.n_iter < 1000
    g = fit(pk, K4, kernel_sharing="class", tol=1e-12, xtol=1e-7, max_iter=5000, init=(f.mu, f.alpha))
    assert g.loglik[-1] - f.loglik[-1] < 0.05
    a, b = decompose(pk, f).shares, decompose(pk, g).shares
    assert max(abs(a[s] - b[s]) for s in a) < 0.01


def test_shared_fit_is_certified_and_keeps_the_best_start(shared_recovery):
    """Shared-kernel fits run from STARTS, keep the highest objective, and end
    with a Newton certificate; a branching ratio pushed to ~0 (where EM grows
    it only geometrically) is revived."""
    _, _, pk, f = shared_recovery
    assert f.converged and f.newton_gain <= NEWTON_TOL
    assert f.starts == STARTS["class"] and f.start_objective.size == 3 and f.start in f.starts
    assert f.objective[-1] == f.start_objective.max() and f.start_spread >= 0
    assert np.all(np.diff(f.objective) >= -1e-9 * np.abs(f.objective[:-1]))
    n = f.n.copy()
    n[0, 1] = 1e-12                             # a strong true edge
    g = fit(pk, K4, kernel_sharing="class", init=(f.mu, SPEC.alpha_from(n, f.w[f.classes])))
    assert g.converged and g.start == "init" and g.starts == ("init",)
    assert g.objective[-1] == pytest.approx(f.objective[-1], abs=1e-3)
    assert g.n[0, 1] == pytest.approx(f.n[0, 1], abs=0.01) and f.n[0, 1] > 0.1
    one = fit(pk, K4, kernel_sharing="class", starts=("default",))
    assert one.starts == ("default",) and one.start_spread == 0 and one.converged
    for call in (lambda: fit(pk, K4, kernel_sharing="class", starts=("default", "bogus")),
                 lambda: fit(pk, K4, kernel_sharing="class", starts=()),
                 lambda: fit(pk, K4, kernel_sharing="class", starts=("cell",), init=(f.mu, f.alpha))):
        with pytest.raises(ValueError):
            call()


def test_shared_stop_regression_window():
    """Simulated window K = 10, dense, rep 2 of scripts/hawkes_recovery_grid.py,
    where the EM-only rule (count step below xtol for one iteration) stopped
    0.36 nats short of the maximum. With the Newton stage, continuing from the
    fit gains nothing."""
    from avsd.hawkes.synth import EXO as SYN_EXO, realistic_window
    _, days, _, _, _ = realistic_window(10, "dense", [SEED, 10, 1, 2])
    pk = pack(days, 10, exo_names=SYN_EXO)
    tight = {"tol": 1e-12, "xtol": 1e-9, "max_iter": 20000}
    em = _fit_pack(pk, np.ones(pk.n_days), kernel_sharing="class", starts=("default",), newton=False)
    f = fit(pk, 10, kernel_sharing="class", starts=("default",))
    g = fit(pk, 10, kernel_sharing="class", init=(f.mu, f.alpha), **tight)
    assert em.converged and g.objective[-1] - em.objective[-1] > 0.1
    assert f.converged and g.objective[-1] - f.objective[-1] < 0.05
    assert max(abs(a - b) for a, b in zip(decompose(pk, f).shares.values(), decompose(pk, g).shares.values())) < 0.002
    best = fit(pk, 10, kernel_sharing="class")
    assert best.objective[-1] >= f.objective[-1] - 1e-6


def test_nested_sharing_likelihoods():
    """global is a special case of class, class of cell, so the maxima are ordered."""
    days, _ = _simulate_shared(10, SEED + 24)
    pk = pack(days, K4, exo_names=EXO)
    ll = {s: fit(pk, K4, kernel_sharing=s).loglik[-1] for s in ("global", "class", "cell")}
    assert ll["global"] <= ll["class"] + 0.05 and ll["class"] <= ll["cell"] + 0.05, ll


def test_class_sharing_recovery(shared_recovery):
    """Data simulated from a class-shared model (20k events): the class fit
    recovers n, rho, the five-way decomposition and the 1 min weight of the
    classes with many events. The split of the rest between the 10 min and 1 h
    components is weakly identified (it trades off with the hourly baseline;
    errors up to 0.3 at 20k events, about 0.1 at 320k), so for it only the
    pooled mean delay is checked."""
    days, labels, pk, f = shared_recovery
    _, alpha_true, n_true, w_true = _truth_shared()
    assert f.converged and f.n_violations == 0
    err = np.abs(f.n - n_true)
    assert err.mean() < 0.035 and err.max() < 0.15, np.round(f.n, 3)
    assert f.rho == pytest.approx(0.5, abs=0.05)
    true = label_shares(days, labels, K4, EXO)
    got = decompose(pk, f).shares
    assert list(got) == list(true) == list(share_names(EXO))
    assert max(abs(got[s] - true[s]) for s in got) < 0.03, (got, true)
    assert np.allclose(f.w.sum(1), 1.0)
    assert np.abs(f.w[:3, 0] - w_true[:3, 0]).max() < 0.1, np.round(f.w, 3)  # self, other, human
    assert _mean_delay(f.alpha) == pytest.approx(_mean_delay(alpha_true), rel=0.5)


def test_several_exogenous_sources(shared_recovery):
    days, _, pk, f = shared_recovery
    d0 = days[0]
    a = pack([Day(d0.T, d0.agent_times, d0.agent_dims, d0.exo_times[0])], K4)
    b = pack([Day(d0.T, d0.agent_times, d0.agent_dims, exo_times=(d0.exo_times[0],))], K4)
    np.testing.assert_array_equal(a.W, b.W)
    assert a.exo_names == ("human",) and (a.ev_uid == b.ev_uid).all()
    assert pk.W.shape[1] == K4 + 2 and f.alpha.shape == (K4, K4 + 2, SPEC.M)
    assert all(np.array_equal(x, y) for p, d in zip(pk.exo_times(), days) for x, y in zip(p, d.exo_times))
    assert np.all(time_rescaling(pk, f).ks_pvalue > 1e-3)
    dec = decompose(pk, f)
    assert dec.by_dim.shape == (K4, 5) and np.allclose(dec.by_dim.sum(1), 1.0)
    assert dec.parents.filter(pl.col("parent_uid").str.contains(":x1_")).height > 0
    short = pack(days[:6], K4, exo_names=EXO)
    g = fit(short, K4, kernel_sharing="class")
    boot = bootstrap_reps(short, g, 0, 2, SEED, xtol=1e-4)
    assert boot.shares.shape == (2, 5) and boot.n.shape == (2, K4, K4 + 2)
    assert list(boot.shares_ci()) == list(share_names(EXO)) and boot.converged.all()
    rec = recovery_check(short, g, n_rep=2, seed=SEED)
    assert rec.shares.shape == (2, 5) and list(rec.bias) == list(share_names(EXO))
    assert np.allclose(rec.true_shares.sum(1), 1.0) and rec.converged.all()
    err = rec.shares - rec.true_shares
    pooled = np.column_stack([err[:, 0], err[:, 1] + err[:, 2], err[:, 3], err[:, 4]])
    np.testing.assert_allclose(rec.mae4, np.abs(pooled).mean(1))
    np.testing.assert_allclose(pool_exogenous(rec.shares).sum(1), 1.0)
    assert rec.n_bias.shape == (K4, K4 + 2) and np.array_equal(rec.n_true, g.n)
    assert set(rec.n_bias_summary()) == {f"n_{k}_{s}" for k in ("self", "other", "exogenous")
                                         for s in ("bias", "abs_bias")}
    parts = Recovery.concat([recovery_check(short, g, n_rep=1, seed=SEED, start=k) for k in (0, 1)])
    np.testing.assert_array_equal(parts.shares, rec.shares)
    np.testing.assert_array_equal(parts.true_shares, rec.true_shares)
    sel = select_l1(short, K4, grid=(0.0, 5.0), n_folds=3, kernel_sharing="class")
    assert np.isfinite(sel.score).all()
    one = select_l1(short, K4, grid=(0.0, 5.0), n_folds=3, kernel_sharing="class", starts=("default",))
    assert np.isfinite(one.score).all()
    for call in (lambda: pack(days[:2], K4, exo_names=("human",)),
                 lambda: pack([days[0], Day(1.0, np.empty(0), np.empty(0, np.int64))], K4),
                 lambda: decompose(pack(days[:2], K4, exo_names=("a", "b")), f),
                 lambda: fit(pk, K4, kernel_sharing="row"),
                 lambda: Day(1.0, np.empty(0), np.empty(0), np.array([0.5]), exo_times=(np.array([0.2]),))):
        with pytest.raises(ValueError):
            call()


def test_day_human_times_follow_exo_times():
    a, b = np.array([5.0, 7.0]), np.array([20.0])
    d = Day(100.0, np.array([10.0, 50.0]), np.array([0, 1]), exo_times=(a, b))
    np.testing.assert_array_equal(d.human_times, a)
    e = dataclasses.replace(d, T=120.0)
    assert e.T == 120.0 and e.H == 2 and np.array_equal(e.human_times, a)
    h = Day(100.0, np.array([10.0]), np.array([0]), a, human_uids=np.array(["x", "y"]))
    r = dataclasses.replace(h, T=90.0)
    assert r.exo_uids[0].tolist() == ["x", "y"] and np.array_equal(r.exo_times[0], a)
    assert Day(100.0, np.empty(0), np.empty(0, np.int64), a, exo_times=(a, b)).H == 2
    with pytest.raises(ValueError):
        Day(100.0, np.empty(0), np.empty(0, np.int64), b, exo_times=(a, b))
    with pytest.raises(ValueError):
        Day(100.0, np.empty(0), np.empty(0, np.int64), exo_times=(a,), exo_uids=(np.array(["x", "y"]),),
            human_uids=np.array(["x", "z"]))


def test_synthetic_window_arms_share_the_truth():
    """synth windows are reproducible; kappa and tilt change only the kernel shapes."""
    from avsd.hawkes.synth import realistic_window
    seed = [SEED, 7, 0, 1]
    t0, d0, _, D0, _ = realistic_window(7, "sparse", seed)
    _, d1, _, _, _ = realistic_window(7, "sparse", seed)
    assert all(np.array_equal(a.agent_times, b.agent_times) for a, b in zip(d0, d1))
    for kw in ({"kappa": 5.0}, {"tilt": 0.75}):
        t2, d2, _, D2, _ = realistic_window(7, "sparse", seed, **kw)
        assert D2 == D0 and np.allclose(SPEC.branching(t2.alpha), SPEC.branching(t0.alpha))
        assert np.array_equal(t2.mu, t0.mu) and not np.allclose(t2.alpha, t0.alpha)
        assert all(np.array_equal(a.exo_times[0], b.exo_times[0]) for a, b in zip(d0, d2))


# --- 4. edge cases ----------------------------------------------------------


def test_empty_dimension_and_human_only_day():
    rng = np.random.default_rng(SEED + 4)
    days = _tiny_days(rng, K=2)            # agents 0, 1 only; dimension 2 never fires
    f = fit(days, 3)
    assert f.n_violations == 0 and np.isfinite(f.loglik).all()
    assert np.all(f.mu[2] == 0) and np.all(f.alpha[2] == 0) and np.all(f.alpha[:, 2] == 0)
    assert f.loglik[-1] == pytest.approx(_ref_loglik(days, 3, f.mu, f.alpha), rel=1e-9)
    dec = decompose(days, f)
    assert dec.n_events[2] == 0 and np.isnan(dec.by_dim[2]).all()
    assert np.isnan(time_rescaling(days, f).ks_stat[2])


def test_ties_boundaries_and_end_of_day():
    L = SPEC.max_lag
    day = Day(7 * H, np.array([1000.0, 1000.0, 1030.0, L, 7 * H, 7 * H]), np.array([0, 1, 0, 2, 1, 2]),
              np.array([0.0, 1000.0, 7 * H - 50]))
    pk = pack([day, Day(2 * H, np.empty(0), np.empty(0, np.int64))], 3)
    pairs = [(pk.ev_t[pk.tgt_ev[k]], pk.ev_t[p]) for k in range(pk.tgt_ev.size)
             for p in pk.par_ev[pk.ptr[k]:pk.ptr[k + 1]]]
    assert (1000.0, 0.0) in pairs and (L, 0.0) in pairs          # dt == L is a parent
    assert not any(a == b for a, b in pairs)                      # ties never parent each other
    assert [p for p in pairs if p[0] == 7 * H] == [(7 * H, 7 * H - 50)] * 2
    assert len(pairs) == 2 + 4 + 5 + 2                            # 1000s, 1030, L, 7h targets
    assert pk.tgt_bin[pk.ev_t[pk.tgt_ev] == 7 * H].tolist() == [6, 6]
    assert pk.E[0, 7] == 0 and pk.E[1].sum() == 2 * H
    f = fit(pk, 3)
    assert np.isfinite(f.loglik).all() and f.n_violations == 0
    with pytest.raises(ValueError):
        pack([Day(0.0, np.array([0.0]), np.array([0]))], 1)


def test_kernel_is_normalized(recovery):
    f = recovery[3]
    for i, j in [(0, 0), (1, 4), (2, 3)]:
        tot = sum(integrate.quad(lambda x: f.kernel(i, j, x), a, b, epsrel=1e-10)[0]
                  for a, b in [(0, 600), (600, 3600), (3600, SPEC.max_lag)])
        assert tot == pytest.approx(1.0, rel=1e-8)
    assert f.kernel(0, 0, SPEC.max_lag + 1.0) == 0


def test_mismatched_fit_and_data_raise():
    rng = np.random.default_rng(SEED + 9)
    days = _tiny_days(rng)
    f3 = fit(days, 3)
    pk4 = pack(days, 4)
    for call in (lambda: decompose(pk4, f3), lambda: time_rescaling(pk4, f3),
                 lambda: bootstrap_reps(pk4, f3, 0, 1, SEED), lambda: fit(pk4, 3),
                 lambda: fit(pk4, 4, init=(f3.mu, f3.alpha)), lambda: loglik(pk4, 4, f3.mu, f3.alpha),
                 lambda: decompose(pack(days, 3, HawkesSpec(max_lag=H)), f3)):
        with pytest.raises(ValueError):
            call()


def test_spec_from_config():
    spec = HawkesSpec.from_config(load_config())
    assert spec.max_lag == 3 * H and spec.n_bins == 8
    np.testing.assert_allclose(spec.beta, SPEC.beta)


# --- 6. presence: agents absent on some days ----------------------------------


def _ref_loglik_present(days, K, mu, alpha, spec=SPEC):
    """_ref_loglik with each agent's compensator counted only on the days it is present."""
    ll = 0.0
    for day in days:
        on = np.ones(K, bool) if day.present is None else day.present
        for t, i in zip(day.agent_times, day.agent_dims):
            ll += np.log(_ref_intensity(day, K, i, t, mu, alpha, spec))
        src = _sources(day, K)
        for i in np.flatnonzero(on):
            for b in range(spec.n_bins):
                hi = day.T if b == spec.n_bins - 1 else min(day.T, (b + 1) * spec.bin_width)
                ll -= mu[i, b] * max(hi - b * spec.bin_width, 0.0)
            for tl, j in src:
                ll -= np.sum(alpha[i, j] * (1 - np.exp(-spec.beta * min(spec.max_lag, day.T - tl))))
    return ll


def _with_presence(days, K, rng):
    """Each day with a presence mask: agents with events are present, the others with probability 1/2."""
    out = []
    for day in days:
        on = rng.random(K) < 0.5
        on[np.asarray(day.agent_dims, dtype=np.int64)] = True
        out.append(dataclasses.replace(day, present=on))
    return out


def test_presence_loglik_matches_reference():
    rng = np.random.default_rng(SEED + 40)
    days = _with_presence(_tiny_exo_days(rng), 3, rng)
    assert any(not d.present.all() for d in days)
    pk = pack(days, 3, exo_names=EXO)
    assert pk.present.shape == (len(days), 3)
    for _ in range(3):
        mu = rng.uniform(1e-4, 1e-3, (3, SPEC.n_bins))
        alpha = rng.uniform(0, 0.05, (3, 5, SPEC.M))
        assert loglik(pk, 3, mu, alpha) == pytest.approx(_ref_loglik_present(days, 3, mu, alpha), rel=1e-9)
    f = fit(pk, 3, kernel_sharing="class")
    assert f.converged and f.n_violations == 0
    assert f.loglik[-1] == pytest.approx(_ref_loglik_present(days, 3, f.mu, f.alpha), rel=1e-9)
    with pytest.raises(ValueError):          # an event of an absent agent
        bad = dataclasses.replace(days[0], present=np.zeros(3, bool))
        pack([bad], 3, exo_names=EXO)
    with pytest.raises(ValueError):
        pack([dataclasses.replace(days[0], present=np.ones(2, bool))], 3, exo_names=EXO)


def test_presence_all_true_is_the_unmasked_model():
    days, _ = _simulate_shared(8, SEED + 41)
    a = fit(pack(days, K4, exo_names=EXO), K4, kernel_sharing="class")
    b = fit(pack([dataclasses.replace(d, present=np.ones(K4, bool)) for d in days], K4, exo_names=EXO), K4,
            kernel_sharing="class")
    assert b.objective[-1] == pytest.approx(a.objective[-1], rel=1e-12)
    np.testing.assert_allclose(b.n, a.n, rtol=1e-6, atol=1e-9)


def test_presence_removes_the_part_time_self_excitation_bias():
    """An agent present on a third of the days: counting its absent days as exposure drives its mu
    to about 0 and its n_ii to about 1, which sets rho above 1 (true rho 0.5); the presence-aware fit
    recovers n_ii, and simulation honours the mask."""
    mu, alpha, n, wc = _truth_shared()
    rng = np.random.default_rng(SEED + 42)
    D = 45
    Ts = rng.uniform(4 * H, 8 * H, D)
    exo = [tuple(np.sort(rng.uniform(0, T, rng.poisson(r * T))) for r in (8 / H, 3 / H)) for T in Ts]
    present = np.ones((D, K4), bool)
    present[np.arange(D) % 3 != 0, 3] = False
    days, labels = simulate(mu, alpha, list(Ts), exo, rng, present=present)
    assert all(not np.any(d.agent_dims == 3) for d, p in zip(days, present) if not p[3])
    assert all(np.array_equal(d.present, p) for d, p in zip(days, present))
    masked = fit(pack(days, K4, exo_names=EXO), K4, kernel_sharing="class")
    blind = fit(pack([dataclasses.replace(d, present=None) for d in days], K4, exo_names=EXO), K4,
                kernel_sharing="class")
    assert masked.converged and blind.converged
    assert abs(masked.n[3, 3] - n[3, 3]) < 0.15 and masked.rho < 0.7
    assert blind.n[3, 3] > 0.9 and blind.rho > 1.0
    assert blind.mu[3].mean() < 0.2 * masked.mu[3].mean()


def test_presence_compensator_total_equals_the_counts():
    """At the fitted maximum sum over present days of Lambda_i(T_d) = N_i, so time_rescaling's
    end-to-end axis skips the absent days."""
    rng = np.random.default_rng(SEED + 43)
    days, _ = _simulate_shared(10, SEED + 43)
    days = _with_presence(days, K4, rng)
    pk = pack(days, K4, exo_names=EXO)
    f = fit(pk, K4, kernel_sharing="class")
    total = (f.mu @ pk.E.T + np.einsum("ijm,djm->id", f.alpha, pk.W)) * pk.present.T
    np.testing.assert_allclose(total.sum(1), pk.counts(np.ones(pk.n_days)), rtol=1e-5)
    res = time_rescaling(pk, f)
    assert (res.n == pk.counts(np.ones(pk.n_days))).all()


def test_expected_counts_with_presence():
    from avsd.hawkes.matched import expected_counts

    rng = np.random.default_rng(SEED + 44)
    K = 3
    mu = rng.uniform(1e-4, 1e-3, (K, SPEC.n_bins))
    alpha = rng.uniform(0, 0.05, (K, K + 2, SPEC.M))
    Ts = [5000.0, 9000.0, 7000.0]
    exo = [(np.sort(rng.uniform(0, T, 5)), np.sort(rng.uniform(0, T, 3))) for T in Ts]
    pres = np.array([[True, True, True], [True, False, True], [False, True, False]])
    got = expected_counts(mu, alpha, Ts, exo, SPEC, present=pres)
    ref = sum(expected_counts(mu * p[:, None], alpha * p[:, None, None], [T], [x], SPEC)
              for T, x, p in zip(Ts, exo, pres))
    np.testing.assert_allclose(got, ref, rtol=1e-12)
    np.testing.assert_allclose(expected_counts(mu, alpha, Ts, exo, SPEC, present=np.ones((3, K), bool)),
                               expected_counts(mu, alpha, Ts, exo, SPEC), rtol=1e-12)


def test_bootstrap_draws_clusters_and_keeps_the_better_start():
    from avsd.hawkes.bootstrap import day_weights

    rng = np.random.default_rng(SEED)
    clusters = np.array([0, 1, 1, 2, 3])
    for _ in range(20):
        w = day_weights(rng, clusters)
        assert w[1] == w[2] and w.sum() == 4 + w[1]
    a, b = np.random.default_rng([SEED, 3]), np.random.default_rng([SEED, 3])
    np.testing.assert_array_equal(day_weights(a, np.arange(6)),
                                  np.bincount(b.integers(0, 6, 6), minlength=6).astype(float))
    days, _ = _simulate_shared(6, SEED + 45)
    pk = pack(days, K4, exo_names=EXO)
    f = fit(pk, K4, kernel_sharing="class")
    res = bootstrap_reps(pk, f, 0, 3, SEED, clusters=np.array([0, 0, 1, 2, 3, 4]))
    assert res.converged.all() and (res.n_violations == 0).all()
    assert np.isfinite(res.obj_starts).all() and res.n_clusters.max() <= 5
    warm = bootstrap_reps(pk, f, 0, 3, SEED, clusters=np.array([0, 0, 1, 2, 3, 4]), multistart=False)
    assert np.isnan(warm.obj_starts).all()
    np.testing.assert_array_equal(warm.obj_warm, res.obj_warm)
    for k in range(3):                       # the kept refit is the better one
        pick = res if res.obj_starts[k] > res.obj_warm[k] else warm
        assert res.rho[k] == pick.rho[k]
    with pytest.raises(ValueError):
        bootstrap_reps(pk, f, 0, 1, SEED, clusters=np.array([0, 0, 2, 2, 3, 4]))
