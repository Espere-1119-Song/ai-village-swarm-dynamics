"""Module A on the real data: windows, merge rule, tied shapes, validation helpers and output schemas."""

from dataclasses import replace as dataclasses_replace
from datetime import date, datetime, timedelta, timezone

import numpy as np
import polars as pl
import pytest

from avsd.hawkes import HawkesSpec, fit, kernel_classes, pack
from avsd.hawkes.windows import Window, _Unit, attach_agent_messages, merge_units, window_data

SEED = 20261003
SPEC = HawkesSpec()
UTC = timezone.utc


# --- merge rule -------------------------------------------------------------------------------------


def _units(ns, start=1):
    return [_Unit("r", g, g, n) for g, n in enumerate(ns, start)]


def _spans(units):
    return [(u.lo, u.hi, u.n) for u in units]


def test_merge_smallest_first_with_smaller_neighbour():
    out = merge_units(_units([2000, 300, 900, 450, 5000]))
    # 300 (smallest) joins 900, its smaller neighbour; then 450 joins 2-3 (1200), smaller than 5000.
    assert _spans(out) == [(1, 1, 2000), (2, 4, 1650), (5, 5, 5000)]


def test_merge_ties_go_to_the_earlier_unit_and_gaps_block_merges():
    out = merge_units(_units([700, 100, 700]))
    assert _spans(out) == [(1, 2, 800), (3, 3, 700)]
    gap = [_Unit("r", 1, 1, 900), _Unit("r", 3, 3, 100), _Unit("r", 5, 5, 900)]
    assert _spans(merge_units(gap)) == [(1, 1, 900), (3, 3, 100), (5, 5, 900)]   # no adjacent unit


def test_merge_failed_one_round():
    units = _units([600, 800, 700, 650])
    out = merge_units(units, fail={(1, 1), (2, 2), (4, 4)}, reason="recovery")
    # 1 (600) fails and joins 2 (its only neighbour); 2 is consumed; 4 (650) joins 3 (700).
    assert _spans(out) == [(1, 2, 1400), (3, 4, 1350)]
    assert all(u.reason == "recovery" for u in out)
    out = merge_units(_units([600, 800, 700]), fail={(1, 1), (3, 3)}, reason="recovery")
    # 1 joins 2; the new unit is locked for this round, so 3 waits for the next round.
    assert _spans(out) == [(1, 2, 1400), (3, 3, 700)]


# --- events of a window -----------------------------------------------------------------------------


def _ts(d, h, m=0, s=0):
    return datetime(d.year, d.month, d.day, h, m, s, tzinfo=UTC)


def _msgs_blocks():
    d1, d2 = date(2026, 7, 1), date(2026, 7, 2)
    rows = [  # uid, kind, ts, actor, room
        ("a1", "agent", _ts(d1, 17), "x", "R"), ("a2", "agent", _ts(d1, 17, 30), "y", "R"),
        ("a3", "agent", _ts(d1, 20), "x", "R"), ("a4", "agent", _ts(d1, 20, 10), "y", "S"),
        ("a5", "agent", _ts(d2, 17, 5), "y", "R"),
        ("h1", "human", _ts(d1, 15), "u1", "R"),   # before the first block: t = 0 of block 0
        ("h2", "human", _ts(d1, 18, 30), "u1", "R"),  # between the blocks: t = 0 of block 1
        ("h3", "human", _ts(d1, 23), "u1", "R"),   # after the last block of the date: dropped
        ("n1", "system", _ts(d1, 17, 45), "bot", "R"), ("h4", "human", _ts(d1, 17, 50), "u1", "S"),
    ]
    msgs = pl.DataFrame(rows, schema=["event_uid", "kind", "ts_utc", "actor_id", "room_id"], orient="row").with_columns(
        pl.col("ts_utc").dt.cast_time_unit("us"), pl.col("ts_utc").dt.date().alias("date"),
        pl.col("room_id").alias("room"))
    blocks = pl.DataFrame({
        "realization_id": [0, 1, 2], "date": [d1, d1, d2], "run_day": [1, 1, 2],
        "start": [_ts(d1, 16, 55), _ts(d1, 19, 50), _ts(d2, 17)],
        "end": [_ts(d1, 18), _ts(d1, 21), _ts(d2, 18)], "goal": [1, 1, 1],
    }).with_columns(pl.col("start").dt.cast_time_unit("us"), pl.col("end").dt.cast_time_unit("us"))
    return msgs, blocks


def test_window_data_assigns_events_to_realizations():
    msgs, blocks = _msgs_blocks()
    am = attach_agent_messages(msgs, blocks)
    assert am.sort("event_uid")["realization_id"].to_list() == [0, 0, 1, 1, 2]
    w = Window("goal", "g01", "R", "R", (1,), (1, 2), date(2026, 7, 1), date(2026, 7, 2), 4, 0.8)
    d = window_data(w, msgs, am, blocks, {"x": "Agent B", "y": "Agent A"})
    assert d.agent_names == ["Agent A", "Agent B"] and d.realizations == [0, 1, 2]
    day0, day1, day2 = d.days
    assert day0.T == 3900.0 and np.allclose(day0.agent_times, [300.0, 2100.0])
    assert day0.agent_dims.tolist() == [1, 0]                        # x is "Agent B", dimension 1
    assert np.allclose(day0.exo_times[0], [0.0]) and np.allclose(day0.exo_times[1], [3000.0])
    assert np.allclose(day1.agent_times, [600.0]) and day1.agent_uids.tolist() == ["a3"]  # a4 is in room S
    assert np.allclose(day1.exo_times[0], [0.0]) and day1.exo_uids[0].tolist() == ["h2"]
    assert day2.agent_uids.tolist() == ["a5"] and day2.exo_times[0].size == 0
    assert d.counts == {"dropped_after_run": 1, "clipped_to_start": 2, "human": 2, "system": 1}
    w2 = Window("goal", "g01", "S", "S", (1,), (1, 2), date(2026, 7, 1), date(2026, 7, 2), 1, 0.2)
    d2 = window_data(w2, msgs, am, blocks, {})
    # Only realization 1 has an S message; h4 (S, before its start on the same date) is clipped.
    assert d2.realizations == [1] and np.allclose(d2.days[0].exo_times[0], [0.0])


# --- tied exogenous shapes -------------------------------------------------------------------------------


def test_kernel_classes_with_tie():
    cls, names = kernel_classes(3, ("human", "system"), "class", ("system",))
    assert names == ("self", "other", "human")
    assert cls[:, 3].tolist() == [2, 2, 2] and cls[:, 4].tolist() == [1, 1, 1]
    assert np.diag(cls[:, :3]).tolist() == [0, 0, 0]
    with pytest.raises(ValueError):
        kernel_classes(3, ("human", "system"), "cell", ("system",))
    with pytest.raises(ValueError):
        kernel_classes(3, ("human", "system"), "class", ("nudge",))


def _small_days(seed=SEED, K=3, n_days=4):
    from avsd.hawkes import simulate

    rng = np.random.default_rng(seed)
    n = np.full((K, K + 2), 0.05)
    np.fill_diagonal(n, 0.3)
    w = np.tile([0.3, 0.5, 0.2], (K, K + 2, 1))
    alpha = SPEC.alpha_from(n, w)
    mu = np.full((K, SPEC.n_bins), 4 / 3600)
    exo = [(np.sort(rng.uniform(0, 4 * 3600, 6)), np.empty(0)) for _ in range(n_days)]
    days, _ = simulate(mu, alpha, [4 * 3600.0] * n_days, exo, rng, SPEC)
    return days


def test_tie_without_events_leaves_the_likelihood_unchanged():
    days = _small_days()
    pk = pack(days, 3, exo_names=("human", "system"))
    a = fit(pk, 3, kernel_sharing="class")
    b = fit(pk, 3, kernel_sharing="class", tie_exo=("system",))
    assert b.tie_exo == ("system",) and b.class_names == ("self", "other", "human")
    assert b.converged and b.n_violations == 0
    assert b.objective[-1] == pytest.approx(a.objective[-1], abs=1e-3)
    assert np.allclose(b.weights[:, 4], b.w[1]) or np.allclose(b.n[:, 4], 0)


# --- matched arms and the action-opportunity features ------------------------------------------------------


def test_expected_counts_matches_reference_loop():
    import math

    from avsd.hawkes.matched import expected_counts

    rng = np.random.default_rng(SEED)
    K, H = 3, 2
    mu = rng.uniform(1e-4, 1e-3, (K, SPEC.n_bins))
    alpha = rng.uniform(0, 0.05, (K, K + H, SPEC.M))
    Ts = [5000.0, 9000.0]
    exo = [(np.sort(rng.uniform(0, T, 5)), np.sort(rng.uniform(0, T, 3))) for T in Ts]
    step = 30.0
    beta = SPEC.beta
    dec, lag = np.exp(-beta * step), round(SPEC.max_lag / step)
    coef = alpha * -np.expm1(-beta * step)
    ref = np.zeros(4)
    for T, x in zip(Ts, exo):
        steps = math.ceil(T / step)
        hist = np.zeros((steps, K + H))
        for h, t in enumerate(x):
            np.add.at(hist[:, K + h], np.minimum((t / step).astype(int), steps - 1), 1.0)
        b = SPEC.bins(np.minimum(np.arange(steps) * step, T), T)
        R = np.zeros((K + H, SPEC.M))
        for k in range(steps):
            exc = np.einsum("ijm,jm->ij", coef, R)
            base = mu[:, b[k]] * min(step, T - k * step)
            hist[k, :K] = base + exc.sum(1)
            ref += [base.sum(), exc[:, K:].sum(), exc[:, :K].sum() - np.trace(exc[:, :K]), np.trace(exc[:, :K])]
            R = dec * R + hist[k][:, None]
            if k >= lag:
                R -= dec ** lag * hist[k - lag][:, None]
    assert np.allclose(expected_counts(mu, alpha, Ts, exo, SPEC), ref, rtol=1e-10)


def test_decayed_counts_brute_force():
    from avsd.hawkes.opportunity import decayed_counts

    rng = np.random.default_rng(SEED)
    src_t = np.sort(rng.uniform(0, 1000, 30))
    src_t[5] = src_t[4]                               # tie
    src_j = rng.integers(0, 3, 30)
    act_t = np.sort(np.concatenate([rng.uniform(0, 1100, 10), [src_t[4], src_t[10]]]))
    beta = np.array([1 / 60, 1 / 600])
    x = decayed_counts(src_t, src_j, act_t, 3, beta)
    for a, t in enumerate(act_t):
        for j in range(3):
            sel = (src_j == j) & (src_t < t)
            assert np.allclose(x[a, j], np.exp(-np.outer(t - src_t[sel], beta)).sum(0))


def test_influence_ranks_the_driving_source_first():
    from avsd.hawkes.opportunity import influence

    rng = np.random.default_rng(SEED)
    n, J, M = 4000, 3, 3
    X = rng.exponential(0.5, (n, J, M))
    logit = -0.5 + 1.5 * X[:, 1, 2] + 0.8 * X[:, 1, 1]
    y = rng.random(n) < 1 / (1 + np.exp(-logit))
    infl = influence(X, y, SPEC.beta, SPEC.max_lag)
    assert np.argmax(infl) == 1 and infl[1] > 0
    assert influence(X[:25], y[:25], SPEC.beta, SPEC.max_lag) is None   # an outcome below MIN_CLASS


# --- reference labels ------------------------------------------------------------------------------------


def _chat(rows, d=date(2026, 3, 2)):
    out = []
    for k, (spk, is_agent, elig, text) in enumerate(rows):
        out.append({"id": f"m{k}", "speaker": spk, "is_agent": is_agent, "eligible": elig, "content": text,
                    "room_id": "R", "ts_utc": datetime(d.year, d.month, d.day, 17, tzinfo=UTC) + timedelta(seconds=k),
                    "date": d})
    return pl.DataFrame(out)


NAMES = {"a": "Claude Opus 4.8", "b": "GPT-5.5", "c": "Gemini 3.1 Pro"}


def test_tier1_labels_reciprocal_name_references_and_unique_quotes():
    from avsd.hawkes.references import tier1_labels

    rows = _chat([
        ("b", True, True, "@Claude Opus 4.8 can you check the deploy?"),                      # m0
        ("bot", False, False, "Run paused."),                                                    # m1 marker
        ("a", True, True, "@GPT-5.5 yes, the deploy is fixed now."),                             # m2 -> m0
        ("c", True, True, "Starting the survey analysis for the whole village team today"),     # m3
        ("a", True, True, "@Gemini 3.1 Pro thanks, looks good."),                                # m4: c never named a
        ("b", True, True, 'Agreed: "starting the survey analysis for the whole village" works'),  # m5 -> m3
        ("c", True, True, "Plan: the survey analysis for the whole village team today"),         # m6
        ("a", True, True, 'Re "the survey analysis for the whole village team" again'),          # m7: 2 matches
    ])
    lab = tier1_labels(rows, NAMES)
    got = {r["child_id"]: (r["parent_id"], r["label"], r["baseline_id"]) for r in lab.iter_rows(named=True)}
    assert got == {"m2": ("m0", "nameref", "m0"), "m5": ("m3", "quote", "m4")}
    early = tier1_labels(_chat([("b", True, True, "@Claude Opus 4.8 hi"), ("a", True, True, "@GPT-5.5 hi")],
                               d=date(2026, 2, 1)), NAMES)
    assert early.is_empty()


# --- block structure, F2 pooling and output schemas --------------------------------------------------------


def test_spectral_blocks_recovers_planted_groups():
    from avsd.hawkes.report import block_means, spectral_blocks

    rng = np.random.default_rng(SEED)
    K = 8
    n = rng.uniform(0, 0.01, (K, K))
    n[:4, :4] += 0.2
    n[4:, 4:] += 0.2
    np.fill_diagonal(n, 0.5)
    lab, k, gap = spectral_blocks(n)
    assert k == 2 and len(set(lab[:4])) == 1 and len(set(lab[4:])) == 1 and lab[0] != lab[4]
    within, between, self_mean = block_means(n, lab)
    assert within > 10 * between and self_mean == pytest.approx(0.5)
    assert spectral_blocks(n[:3, :3])[1] == 1


def _window(wid, d0, d1, group="R"):
    return Window("goal", wid, group, group, (1,), (1, 5), d0, d1, 1000, 1.0)


def test_f2_pools_overlapping_groups_by_event_rate():
    from types import SimpleNamespace

    from avsd.hawkes.figure import f2_series

    w1 = _window("g01", date(2026, 1, 1), date(2026, 1, 10), "A")
    w2 = _window("g01", date(2026, 1, 6), date(2026, 1, 10), "B")
    s1, s2 = np.array([0.2, 0.05, 0.05, 0.3, 0.4]), np.array([0.4, 0.0, 0.1, 0.2, 0.3])
    fits = {w1.key: SimpleNamespace(n_events=1000, n_days=10, shares=s1),
            w2.key: SimpleNamespace(n_events=300, n_days=5, shares=s2)}
    boots = {w1.key: (SimpleNamespace(shares=np.tile(s1, (7, 1))), None, 0.0),
             w2.key: (SimpleNamespace(shares=np.tile(s2, (5, 1))), None, 0.0)}
    s = f2_series([w1, w2], fits, boots)
    assert [a for a, _ in s["segments"]] == [date(2026, 1, 1), date(2026, 1, 6)]
    assert np.allclose(s["point"][0], [0.7, 0.1, 0.2])
    wt = np.array([100.0, 60.0])
    assert np.allclose(s["point"][1], (wt[0] * np.array([0.7, 0.1, 0.2]) + wt[1] * np.array([0.5, 0.1, 0.4])) / 160)
    assert s["reps"].shape == (5, 2, 3) and np.allclose(s["reps"][0], s["point"])


def test_rolling_table_loads_in_module_c(tmp_path):
    from avsd.changepoint.series import load_external
    from avsd.hawkes.report import ROLLING_SCHEMA

    rd = np.arange(1, 100, 5)
    roll = pl.DataFrame({
        "run_day": rd, "run_day_end": rd + 4, "date": [date(2025, 4, 1) + timedelta(days=int(x)) for x in rd],
        "group": ["general"] * rd.size, "share_baseline": np.linspace(0.2, 0.3, rd.size),
        "share_exogenous": np.full(rd.size, 0.02), "share_agent": np.linspace(0.78, 0.68, rd.size),
        "spectral_radius": np.linspace(0.8, 1.0, rd.size), "n_agents": np.repeat([7, 12], [10, rd.size - 10]),
    }, schema=ROLLING_SCHEMA)
    (tmp_path / "tables").mkdir()
    roll.write_parquet(tmp_path / "tables" / "hawkes_rolling.parquet")
    days = pl.DataFrame({"run_day": np.arange(1, 101, dtype=np.int32),
                         "date": [date(2025, 4, 2) + timedelta(days=i) for i in range(100)]})
    specs, values, status = load_external({"paths": {"outputs": tmp_path}}, days)
    ids = {s.series_id for s in specs}
    assert ids == {f"hawkes:general:{c}" for c in ("share_baseline", "share_exogenous", "share_agent",
                                                   "spectral_radius", "n_agents")}
    assert all(s.resolution == 5 and s.skipped is None for s in specs)
    sr = values.filter(pl.col("series_id") == "hawkes:general:spectral_radius")
    assert sr["n_agents"].to_list()[:2] == [7, 7] and sr["run_day_end"][0] == 5


def test_kernel_rows_follow_the_b2_schema():
    from types import SimpleNamespace

    from avsd.hawkes.report import KERNEL_SCHEMA, _kernel_rows

    days = _small_days()
    pk = pack(days, 3, exo_names=("human", "system"))
    f = fit(pk, 3, kernel_sharing="class")
    from avsd.hawkes.pipeline import expected_children

    kids, _ = expected_children(f, pk)
    w = _window("g01", date(2026, 1, 1), date(2026, 1, 5))
    rows = _kernel_rows(SimpleNamespace(window=w, fit=f, children=kids))
    df = pl.DataFrame(rows, schema=KERNEL_SCHEMA)
    assert list(df.columns) == ["window_kind", "window_id", "group", "date_start", "date_end", "source_class", "w_1m",
                                "w_10m", "w_1h", "L_s", "expected_children", "identified"]
    assert df["source_class"].to_list() == ["self", "other", "human", "system"]
    assert np.allclose(df.select("w_1m", "w_10m", "w_1h").sum_horizontal().to_numpy(), 1.0)
    assert df["L_s"].unique().to_list() == [10800.0]
    assert df.filter(pl.col("source_class") == "system")["expected_children"][0] == 0.0
    assert df["identified"].to_list() == (df["expected_children"] >= 50).to_list()


def test_argmax_parent():
    from avsd.hawkes.pipeline import _argmax_parent

    p0 = np.array([0.6, 0.2, 1.0])
    pp = np.array([0.4, 0.5, 0.3])
    ptr = np.array([0, 1, 3, 3])
    assert _argmax_parent(p0, pp, ptr).tolist() == [-1, 1, -1]


def test_settings_and_cli_guard_the_real_data_choices():
    from typer.testing import CliRunner

    from avsd.cli import app
    from avsd.hawkes import pipeline as P

    cfg = {"seed": SEED, "hawkes": {"recovery_reps": 4, "sensitivity_max_lag_hours": [2]}}
    P.apply_settings(cfg)
    assert P.N_REC == 4 and P.sens_variants() == ("L2", "G15", "G60", "tie")
    for bad in ({"kernel_sharing": "cell"}, {"l1": 1.0}):
        with pytest.raises(ValueError):
            P.apply_settings({"hawkes": bad})
    P.apply_settings({"seed": SEED, "hawkes": {}})
    assert P.N_REC == 20 and P.sens_variants() == ("L1", "L6", "G15", "G60", "tie")
    assert CliRunner().invoke(app, ["hawkes", "fit", "--window", "weekly"]).exit_code != 0


# --- presence, bootstrap units, acceptance rows, figures and the reference check -----------------------------


def test_window_data_presence_by_room_and_block():
    msgs, blocks = _msgs_blocks()
    am = attach_agent_messages(msgs, blocks)
    w = Window("goal", "g01", "R", "R", (1,), (1, 2), date(2026, 7, 1), date(2026, 7, 2), 4, 0.8)
    # Rows: both in R on realization 0; on 1, x in R and y in S; on 2, both in S.
    presence = pl.DataFrame({"realization_id": [0, 0, 1, 1, 2, 2], "actor_id": ["x", "y", "x", "y", "x", "y"],
                             "room_id": ["R", "R", "R", "S", "S", "S"]})
    d = window_data(w, msgs, am, blocks, {"x": "Agent B", "y": "Agent A"}, presence)
    # Dimensions: y (Agent A) = 0, x (Agent B) = 1. y is absent from R on realization 1 (its message a4 is in
    # S); on realization 2 its rows say S, but its message a5 is in R, so it is present.
    assert d.present.tolist() == [[True, True], [False, True], [True, False]]
    assert [day.present.tolist() for day in d.days] == d.present.tolist()
    assert d.n_dates == 2 and d.clusters().tolist() == [0, 0, 1]
    assert window_data(w, msgs, am, blocks, {}).present.all()


def test_kernel_rows_of_a_failed_window_are_not_identified():
    from types import SimpleNamespace

    from avsd.hawkes.pipeline import expected_children
    from avsd.hawkes.report import _kernel_rows

    days = _small_days()
    pk = pack(days, 3, exo_names=("human", "system"))
    f = fit(pk, 3, kernel_sharing="class")
    kids, _ = expected_children(f, pk)
    r = SimpleNamespace(window=_window("g01", date(2026, 1, 1), date(2026, 1, 5)), fit=f, children=kids)
    ok, failed = _kernel_rows(r), _kernel_rows(r, failed=True)
    assert any(x["identified"] for x in ok) and not any(x["identified"] for x in failed)
    assert [x["expected_children"] for x in ok] == [x["expected_children"] for x in failed]


def test_expected_children_count_only_present_days():
    from avsd.hawkes.pipeline import expected_children

    keep = []
    for k, d in enumerate(_small_days()):
        if k % 2:            # agent 2 absent: its events removed
            sel = d.agent_dims != 2
            d = dataclasses_replace(d, agent_times=d.agent_times[sel], agent_dims=d.agent_dims[sel],
                                    present=np.array([True, True, False]))
        keep.append(d)
    pk = pack(keep, 3, exo_names=("human", "system"))
    f = fit(pk, 3, kernel_sharing="class")
    kids, src = expected_children(f, pk)
    seen = pk.present.T.astype(float) @ pk.source_counts()
    ref = np.bincount(f.classes.ravel(), weights=(f.n * seen).ravel(), minlength=len(f.class_names))
    np.testing.assert_allclose(kids, ref)
    np.testing.assert_array_equal(src, pk.source_counts().sum(0))


def test_recovery_row_reports_bias_and_standard_error():
    from avsd.hawkes import pipeline as P
    from avsd.hawkes.validate import Recovery

    P.apply_settings({"seed": SEED, "hawkes": {}})
    true = np.tile([0.3, 0.05, 0.0, 0.3, 0.35], (4, 1))
    got = true + np.array([[0.02, 0.0, 0.0, 0.03, -0.05]] * 4) + np.linspace(-0.01, 0.01, 4)[:, None] * [1, 0, 0, 0, -1]
    n_true = np.full((2, 4), 0.2)
    rec = Recovery(true, got, np.ones(4), np.tile(n_true + 0.01, (4, 1, 1)), np.ones(4, bool), np.full(4, 100),
                   ("baseline", "human", "system", "other_agents", "self"), n_true, np.zeros(4, np.int64))
    row = P.recovery_row(rec)
    assert row["n_reps"] == 4 and row["bias_self"] == pytest.approx(-0.05)
    assert row["bias_other_agents"] == pytest.approx(0.03)
    assert row["n_self_bias"] == pytest.approx(0.01) and row["rec_violations"] == 0
    assert row["mae4_se"] == pytest.approx(rec.mae4.std(ddof=1) / 2)
    assert P.borderline(rec) == (abs(rec.mae4.mean() - P.BAR) < 2 * rec.mae4_se)


def test_cluster_boot_is_deterministic():
    from avsd.hawkes.report import REF_COLS, REF_DIFFS, _cluster_boot

    rng = np.random.default_rng(SEED)
    n = 400
    rows = pl.DataFrame({"realization": rng.integers(0, 60, n),
                         **{c: rng.random(n) < p for c, p in zip(REF_COLS, (0.2, 0.4, 0.35))}})
    a = _cluster_boot(rows, REF_COLS, REF_DIFFS)
    for _ in range(5):
        assert _cluster_boot(rows, REF_COLS, REF_DIFFS) == a
    assert _cluster_boot(rows.sample(fraction=1.0, shuffle=True, seed=1), REF_COLS, REF_DIFFS) == a


def test_figures_with_one_window(tmp_path):
    from types import SimpleNamespace

    from avsd.hawkes.figure import plot_f1, plot_qq
    from avsd.hawkes.pipeline import QQ_PROBS

    days = _small_days()
    f = fit(pack(days, 3, exo_names=("human", "system")), 3, kernel_sharing="class")
    w = _window("g12", date(2025, 9, 1), date(2025, 9, 5), "general")
    fits = {w.key: SimpleNamespace(K=3, fit=f)}
    assert len(plot_f1([w], fits, {w.key: np.zeros(3, np.int64)}, tmp_path / "f1")) == 2
    qq = np.tile(-np.log1p(-QQ_PROBS), (3, 1))
    valid = {w.key: {"qq": qq, "ks_n": np.array([30, 30, 30]), "qq_pooled": qq[0]}}
    assert len(plot_qq([w], fits, valid, tmp_path / "qq")) == 2


def test_recovery_check_stops_exploding_replicates():
    from avsd.hawkes import recovery_check
    from avsd.hawkes.model import HawkesFit
    from avsd.hawkes.pipeline import recovery_row

    days = _small_days()
    pk = pack(days, 3, exo_names=("human", "system"))
    f = fit(pk, 3, kernel_sharing="class")
    n = f.n.copy()
    n[0, 0] = 3.0                                      # a supercritical self-excitation
    hot = HawkesFit(f.spec, f.mu, f.spec.alpha_from(n, f.w[f.classes]), f.loglik, f.objective, f.n_iter, True, 0,
                    exo_names=f.exo_names, kernel_sharing="class", w=f.w, starts=f.starts)
    rec = recovery_check(pk, hot, n_rep=2, seed=SEED)
    assert rec.exploded.all() and np.isnan(rec.mae4).all() and rec.failed(0.05)
    row = recovery_row(rec)
    assert row["n_exploded"] == 2 and np.isnan(row["mae4"])
    ok = recovery_check(pk, f, n_rep=2, seed=SEED)
    assert not ok.exploded.any() and ok.failed(0.05) == (ok.mae4_mean >= 0.05)


def test_n_pairs_matches_pack():
    from avsd.hawkes.validate import n_pairs

    days = _small_days()
    pk = pack(days, 3, exo_names=("human", "system"))
    assert n_pairs(days, SPEC.max_lag) == pk.par_ev.size
    assert n_pairs(days, 600.0) == pack(days, 3, HawkesSpec(max_lag=600.0), exo_names=("human", "system")).par_ev.size
