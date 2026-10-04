from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest
import ruptures as rpt
from ruptures.costs import CostL2, CostRbf

from avsd.changepoint import align as A
from avsd.changepoint.bocpd import bocpd_changepoints, run_length_posterior
from avsd.changepoint.detect import (
    CostL2Cum, CostRbfCum, bootstrap_locations, detect_series, noise_scale, pelt,
)
from avsd.changepoint.documented import agent_goal_groups, run_day_of
from avsd.changepoint.figure import plot_timeline
from avsd.changepoint.lexical import clean_text, log_odds, shape_ok, tokenize
from avsd.changepoint.monitor import Monitor, annotate, monitor_entries, monitor_series
from avsd.changepoint.pipeline import composition
from avsd.changepoint.refsets import documented_columns
from avsd.changepoint.weekday import adjust, detect_adjusted, monday_ratios, weekday_effects
from avsd.changepoint.series import METRICS, Components, SeriesSpec, load_external, series_points

SEED = 20261003
MSG = next(m for m in METRICS if m.name == "msg_count")


def _steps(rng, sizes, levels, sd=1.0):
    return np.concatenate([rng.normal(m, sd, n) for n, m in zip(sizes, levels)])


# --- costs and PELT -------------------------------------------------------------------------------

def test_cumulative_costs_equal_ruptures():
    rng = np.random.default_rng(SEED)
    x = _steps(rng, [60, 50, 70], [0, 2, -1])
    ours = {"l2": CostL2Cum().fit(x), "rbf": CostRbfCum().fit(x)}
    ref = {"l2": CostL2().fit(x), "rbf": CostRbf().fit(x)}
    for _ in range(200):
        a, b = sorted(rng.choice(len(x) + 1, 2, replace=False))
        if b - a < 2:
            continue
        for k in ours:
            assert ours[k].error(a, b) == pytest.approx(ref[k].error(a, b), rel=1e-9, abs=1e-8)
    for model in ("l2", "rbf"):
        pen = 2 * np.log(len(x)) * (1.0 if model == "l2" else 0.5)
        want = rpt.Pelt(model=model, min_size=5, jump=1).fit(x).predict(pen=pen)[:-1]
        assert pelt(x, model, pen, 5) == want


def test_noise_scale_ignores_mean_shifts():
    rng = np.random.default_rng(SEED)
    x = _steps(rng, [150, 150], [0, 10], sd=2.0)
    assert noise_scale(x) == pytest.approx(2.0, rel=0.15)
    assert noise_scale(np.ones(20)) == 0.0


def test_pelt_recovers_known_change_points():
    rng = np.random.default_rng(SEED)
    truth = [120, 200, 310]
    x = _steps(rng, [120, 80, 110, 79], [0, 1.5, -0.5, 1.0])
    det = detect_series("synthetic", x, 1, 5, SEED, n_boot=50)
    for method in ("l2", "rbf"):
        cps = det.cps[method]
        assert len(cps) == len(truth), (method, cps)
        assert all(abs(c - t) <= 3 for c, t in zip(cps, truth)), (method, cps)
    # Larger penalties never add change points.
    counts = [len(det.sweep[f"l2@{b:g}"]) for b in (0.5, 1, 2, 4, 8)]
    assert counts == sorted(counts, reverse=True)
    # Intervals cover the truth and the change points are found in most replicates.
    for (lo, hi, rate), t in zip(det.boot, truth):
        assert lo is not None and lo <= t <= hi and hi - lo <= 15
        assert rate >= 0.8


def test_pelt_finds_nothing_in_noise_and_rbf_sees_variance():
    rng = np.random.default_rng(SEED + 1)
    flat = detect_series("noise", rng.normal(0, 1, 300), 1, 5, SEED, n_boot=10)
    assert flat.cps["l2"] == [] and flat.cps["rbf"] == []
    x = np.concatenate([rng.normal(0, 0.5, 150), rng.normal(0, 3.0, 150)])
    det = detect_series("variance", x, 1, 5, SEED, n_boot=10)
    assert any(abs(c - 150) <= 10 for c in det.cps["rbf"])


def test_bootstrap_without_change_points():
    rng = np.random.default_rng(SEED)
    assert bootstrap_locations(rng.normal(size=50), [], 10.0, 5, 5, 10, rng) == []


def test_binned_series_use_bin_units():
    rng = np.random.default_rng(SEED)
    x = _steps(rng, [30, 30], [0, 2.0], sd=0.5)       # 60 bins of 5 run days
    det = detect_series("binned", x, 5, 5, SEED, n_boot=20)
    assert any(abs(c - 30) <= 1 for c in det.cps["l2"])
    assert det.sweep["l2@8"] == [30]
    assert all(2 <= c <= 58 for c in det.cps["l2"])   # minimum segment of 2 bins (10 run days)


# --- BOCPD ----------------------------------------------------------------------------------------

def test_bocpd_two_segments():
    rng = np.random.default_rng(SEED)
    x = _steps(rng, [80, 70], [0.0, 3.0])
    R = run_length_posterior(x, 1 / 100)
    assert np.allclose(R.sum(axis=1), 1.0)
    cps, support = bocpd_changepoints(x, 1 / 100, min_size=5)
    assert len(cps) == 1 and abs(cps[0] - 80) <= 2
    assert support[0] > 0.5
    # Seen 5 steps later, a segment starting at the change carries most of the mass.
    assert R[85, 5:8].sum() > 0.5


def test_bocpd_no_change_in_noise():
    rng = np.random.default_rng(SEED + 2)
    cps, _ = bocpd_changepoints(rng.normal(0, 1, 200), 1 / 100, min_size=5)
    assert cps == []


# --- alignment ------------------------------------------------------------------------------------

def _days(n=300, start=date(2025, 1, 1)):
    return pl.DataFrame({"run_day": np.arange(1, n + 1, dtype=np.int32),
                         "date": [start + timedelta(days=i) for i in range(n)]})


def _entries(run_days, lengths=None):
    n = len(run_days)
    lengths = lengths or [1] * n
    return pl.DataFrame({
        "entry_id": [f"e{i}" for i in range(n)], "source": ["changelog"] * n,
        "rd_start": np.asarray(run_days, dtype=np.int32),
        "rd_end": np.asarray(run_days, dtype=np.int32) + np.asarray(lengths, dtype=np.int32) - 1,
        "categories": [["prompt"]] * n, "date_start": [date(2025, 1, 1)] * n,
    })


def test_alignment_small_p_when_change_points_sit_on_entries():
    rng = np.random.default_rng(SEED)
    n_days, w = 300, 3
    ent = np.sort(rng.choice(np.arange(10, 290), 15, replace=False))
    entries = _entries(ent)
    cp = np.repeat(ent, 2)
    res = A.alignment_test(cp, cp, entries, n_days, w, 2000, rng)
    assert res["aligned"] == len(cp)
    assert res["null1_p"] < 0.01 and res["null2_p"] < 0.01 and res["null1_p_exact"] < 0.01
    # Random change points: p-values spread over (0, 1), rarely small.
    p1, p2 = [], []
    for k in range(20):
        rand = np.random.default_rng([SEED, k]).integers(1, n_days + 1, size=30)
        res = A.alignment_test(rand, rand, entries, n_days, w, 300, np.random.default_rng([SEED, 99, k]))
        p1.append(res["null1_p"])
        p2.append(res["null2_p"])
    for p in (np.array(p1), np.array(p2)):
        assert np.median(p) > 0.25 and np.mean(p < 0.05) <= 0.2


def _layout(e_lo, e_hi, n, domain=None, groups=None):
    dom = np.arange(1, n + 1) if domain is None else np.asarray(domain)
    return A.layout_entries(np.asarray(e_lo), np.asarray(e_hi), dom, groups)


def test_shift_null_matches_direct_count():
    rng = np.random.default_rng(SEED)
    n, w = 120, 3
    e_lo = np.array([5, 40, 41, 100]); e_hi = e_lo + np.array([0, 2, 0, 5])
    cp = rng.integers(1, n + 1, size=25)
    got = A.shift_null(A.cp_groups(cp, cp), _layout(e_lo, e_hi, n), n, w, np.arange(n))
    for k in (0, 7, 119):
        days = {((d - 1 + k) % n) + 1 for a, b in zip(e_lo, e_hi) for d in range(a, b + 1)}
        cover = {x for d in days for x in range(d - w, d + w + 1)}
        assert got[k] == sum(int(c in cover) for c in cp)


def test_uniform_null_mean_matches_coverage():
    n, w = 200, 3
    cp = np.arange(1, n + 1)                     # one change point per run day
    s = A.uniform_null(A.cp_groups(cp, cp), _layout([1], [1], n), n, w, 4000, np.random.default_rng(SEED))
    # One entry covers 7 run days, minus 3 + 2 + 1 at each edge.
    assert s.mean() == pytest.approx(7 - 12 / n, abs=0.1)


def test_distinct_starts_and_dense_sets():
    st = A.distinct_starts(np.random.default_rng(SEED), 50, 30, 25)
    assert all(len(set(r)) == 25 for r in st.tolist()) and st.min() >= 0 and st.max() < 30
    # 25 single-day entries on a 30-day domain keep their coverage under null 2.
    n = 30
    e = np.arange(1, 26)
    lay = _layout(e, e, n)
    cp = np.arange(1, n + 1)
    s = A.uniform_null(A.cp_groups(cp, cp), lay, n, 0, 200, np.random.default_rng(SEED))
    assert (s == 25).all()


def test_domain_restricts_the_nulls():
    n, w = 200, 1
    dom = np.arange(101, 151)
    entries = _entries([110, 130])
    cp_out = np.arange(1, 90)                    # change points far from the domain
    lay = A.layout_entries(entries["rd_start"].to_numpy(), entries["rd_end"].to_numpy(), dom)
    cps = A.cp_groups(cp_out, cp_out)
    rng = np.random.default_rng(SEED)
    assert A.shift_null(cps, lay, n, w, np.arange(len(dom))).max() == 0
    assert A.uniform_null(cps, lay, n, w, 500, rng).max() == 0
    # Change points on the entries inside the domain: small p, and coverage over domain days.
    cp = np.array([110, 110, 130, 130])
    res = A.alignment_test(cp, cp, entries, n, w, 2000, rng, domain=dom)
    assert res["aligned"] == 4 and res["n_domain_days"] == 50
    assert res["coverage_frac"] == pytest.approx(6 / 50)
    assert res["null2_p"] < 0.05


def test_group_specific_entries():
    n, w = 100, 2
    entries = _entries([30, 70])
    groups = [frozenset({1}), frozenset({2})]    # entry 0 concerns group 1, entry 1 group 2
    cp = np.array([30, 30, 70, 70])
    grp = np.array([1, 2, 1, 2])                 # only (30, g1) and (70, g2) are aligned
    res = A.alignment_test(cp, cp, entries, n, w, 500, np.random.default_rng(SEED),
                           cp_group=grp, entry_groups=groups)
    assert res["aligned"] == 2
    res = A.alignment_test(cp, cp, entries, n, w, 500, np.random.default_rng(SEED))
    assert res["aligned"] == 4                   # without groups every change point is aligned


def _weekday_dates(n_weeks: int, start=date(2025, 4, 7)):   # a Monday
    return np.array([start + timedelta(days=7 * k + d) for k in range(n_weeks) for d in range(5)],
                    dtype="datetime64[D]")


def test_week_shifts_keep_weekdays():
    dates = _weekday_dates(10)
    ks, period = A.week_shift_ks(dates, 1)
    assert period == 70 and ks.tolist() == list(range(1, 10))
    maps = A.week_shift_maps(dates, ks, period)
    wd = A.weekdays(dates)
    assert (wd[maps] == wd[None, :]).all()
    assert maps[0, 0] == 5 and maps[-1, 5] == 0          # one week on, and a wrap round the circle
    assert A.week_shift_ks(dates, 3)[0].tolist() == list(range(2, 9))   # +-1 week is within 2w


def test_week_nulls_absorb_a_weekday_pattern():
    dates = _weekday_dates(40)
    n = len(dates)
    mondays = np.flatnonzero(A.weekdays(dates) == 0) + 1    # run days
    cp = mondays                                            # a change point every Monday
    ent = _entries(mondays[::4])                            # entries on 10 of the Mondays
    res = A.alignment_test(cp, cp, ent, n, 0, 2000, np.random.default_rng(SEED), dom_dates=dates)
    assert res["aligned"] == 10
    assert res["null2_p"] < 0.01                            # uniform placement: spurious alignment
    assert res["null2w_p"] == 1.0 and res["null1w_p"] == 1.0   # weekday kept: none
    assert res["n_week_shifts"] == 39


def test_weekday_adjustment_removes_monday_effect():
    rng = np.random.default_rng(SEED)
    wd = np.tile(np.arange(5), 40)
    level = np.r_[np.zeros(100), np.full(100, 2.0)]
    x = level + 1.5 * (wd == 0) + rng.normal(0, 0.3, 200)
    eff = weekday_effects(x, wd)
    assert eff[wd == 0].mean() - eff[wd != 0].mean() == pytest.approx(1.5, abs=0.25)
    xa = adjust(x, wd)
    assert abs(xa[wd == 0].mean() - xa[(wd != 0)].mean()) < 0.25
    _, cps = detect_adjusted("s", x, wd)
    assert len(cps) == 1 and abs(cps[0] - 100) <= 2


def test_monday_ratios():
    days = _days(140, start=date(2026, 1, 5))               # Monday 2026-01-05, calendar days
    wdn = np.array([d.weekday() for d in days["date"].to_list()])
    values = pl.DataFrame({"series_id": "s", "run_day": days["run_day"],
                           "value": np.where(wdn == 0, 20.0, 10.0)})
    out = monday_ratios(values.filter(pl.Series(wdn < 5)), days)
    r = out.row(0, named=True)
    assert r["mean_ratio"] == pytest.approx(2.0) and r["share_weeks_monday_higher"] == 1.0
    assert r["n_pre_cu"] + r["n_post_cu"] == r["n_weeks"] - 1    # the rollout week is left out


def test_map_entries_moves_weekend_dates_forward():
    days = pl.DataFrame({"run_day": [1, 2, 3], "date": [date(2025, 4, 4), date(2025, 4, 7), date(2025, 4, 8)]})
    cl = pl.DataFrame({"entry_id": ["a", "b", "c"], "source": ["changelog"] * 3,
                       "date_start": [date(2025, 4, 5), date(2025, 4, 4), date(2025, 4, 9)],
                       "date_end": [date(2025, 4, 6), date(2025, 4, 7), date(2025, 4, 9)],
                       "categories": [["tool"]] * 3})
    m = A.map_entries(cl, days)
    assert m["rd_start"].to_list() == [2, 1] and m["rd_end"].to_list() == [2, 2]


def test_match_entries_and_bin_width():
    entries = _entries([50, 70])
    lo, hi = A.cp_interval(np.array([46, 46, 60]), np.array([1, 5, 1]), 300)
    m = A.match_entries(np.array([46, 46, 60]), lo, hi, entries, 3)
    assert m["aligned"].to_list() == [False, True, False]
    assert m["nearest_entry_id"].to_list() == ["e0", "e0", "e0"]
    assert m["nearest_entry_offset_run_days"].to_list() == [4, 4, -10]


def test_holm():
    assert A.holm(np.array([0.01, 0.04, 0.03])).tolist() == pytest.approx([0.03, 0.06, 0.06])


# --- lexical --------------------------------------------------------------------------------------

def test_clean_text_and_question_flags():
    df = pl.DataFrame({"content": [
        "See https://example.com/a?b=1 and mail x.y@example.org now.",
        "Is this genuinely done? Yes.", "`a?b` @Someone ok", None,
    ]})
    t = tokenize(df)
    assert t["is_question"].to_list() == [False, True, False, False]
    assert "example" not in t["tok"][0].to_list() and t["tok"][2].to_list() == ["ok"]
    assert "genuinely" in df.select(clean_text(pl.col("content")))["content"][1]


def test_log_odds_ranks_family_word_first():
    counts = pl.DataFrame({
        "w": ["the", "genuinely", "the", "cheers", "genuinely"],
        "family": ["A", "A", "B", "B", "B"], "n": [1000, 200, 1000, 150, 5],
    })
    lo = log_odds(counts, "A").sort("z", descending=True)
    assert lo["w"][0] == "genuinely" and lo.filter(pl.col("w") == "cheers")["z"][0] < 0


def test_shape_filter():
    assert shape_ok("genuinely") and not shape_ok("xkcdqwrt") and not shape_ok("ab") and not shape_ok("brr")


# --- series and composition -----------------------------------------------------------------------

def _daily(values_by_agent: dict[str, list[float]]) -> pl.DataFrame:
    rows = []
    for a, vals in values_by_agent.items():
        for d, v in enumerate(vals, 1):
            if v is not None:
                rows.append({"agent_id": a, "run_day": d, "active": 1.0, "n_msg": float(v)})
    return pl.DataFrame(rows)


def test_series_points_pool_bins():
    daily = _daily({"a": [10] * 10, "b": [30] * 5 + [None] * 5})
    day = series_points(daily, ("a", "b"), MSG, 1)
    assert day["value"].to_list() == [20.0] * 5 + [10.0] * 5
    binned = series_points(daily, ("a", "b"), MSG, 5)
    assert binned["run_day"].to_list() == [1, 6] and binned["value"].to_list() == [20.0, 10.0]


def _composition_case(shift_stayers: float, b_leaves: bool):
    rng = np.random.default_rng(SEED)
    noise = lambda: rng.normal(0, 0.5, 40).tolist()  # noqa: E731
    a = [10 + e for e in noise()] + [10 + shift_stayers + e for e in noise()]
    c = [10 + e for e in noise()] + [10 + shift_stayers + e for e in noise()]
    b = [50 + e for e in noise()] + ([None] * 40 if b_leaves else [50 + e for e in noise()])
    comp = Components(_daily({"a": a, "b": b, "c": c}), None, None, None)
    spec = SeriesSpec("family:X:msg_count", "family", "X", MSG, ("a", "b", "c"))
    pts = series_points(comp.daily, spec.agent_ids, MSG, 1)
    return composition(comp, spec, pts, [40], 0)


def test_composition_separates_roster_effects():
    out = _composition_case(0.0, b_leaves=True)     # the drop is only b leaving
    assert (out["comp_n_agents_before"], out["comp_n_agents_after"], out["comp_n_stayers"]) == (3, 2, 2)
    assert out["comp_verdict"] == "no shift among stayers"
    assert _composition_case(-3.0, b_leaves=True)["comp_verdict"] == "partial shift among stayers"
    out = _composition_case(-6.0, b_leaves=False)   # everyone stays, a and c drop
    assert out["comp_verdict"] == "shift among stayers" and out["comp_ratio"] == pytest.approx(1.0)


def test_external_series_hook(tmp_path):
    (tmp_path / "tables").mkdir()
    rd = np.arange(1, 100, 5)
    pl.DataFrame({
        "run_day": rd, "group": ["rest"] * len(rd), "spectral_radius": np.linspace(0.5, 0.9, len(rd)),
        "n_agents": np.repeat([8, 12], [10, len(rd) - 10]),
    }).write_parquet(tmp_path / "tables" / "hawkes_rolling.parquet")
    specs, values, status = load_external({"paths": {"outputs": tmp_path}}, _days(100))
    assert {s.series_id for s in specs} == {"hawkes:rest:spectral_radius", "hawkes:rest:n_agents"}
    assert all(s.resolution == 5 and s.level == "external" and s.skipped is None for s in specs)
    sr = values.filter(pl.col("series_id") == "hawkes:rest:spectral_radius")
    assert sr["n_agents"].to_list()[:2] == [8, 8] and sr["run_day_end"][0] == 5
    assert status["memory_hazard"].startswith("not available")


# --- documented goal changes and the monitor ------------------------------------------------------

def _run_days(n=10, start=date(2026, 7, 1)):
    """Run days on consecutive dates, each running 16:00 to 24:00 UTC."""
    from datetime import datetime, timezone
    dates = [start + timedelta(days=i) for i in range(n)]
    ends = [datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(hours=24) for d in dates]
    return pl.DataFrame({"run_day": np.arange(1, n + 1, dtype=np.int32), "date": dates,
                         "village_day": np.arange(1, n + 1, dtype=np.int32), "last_end": ends}
                        ).with_columns(pl.col("last_end").dt.cast_time_unit("us"))


def test_goal_start_maps_to_next_run():
    from datetime import datetime, timezone
    days = _run_days()
    ts = pl.Series([datetime(2026, 7, 1, 5, tzinfo=timezone.utc),     # before the run of day 1
                    datetime(2026, 7, 2, 20, tzinfo=timezone.utc),    # during the run of day 2
                    datetime(2026, 7, 4, 0, 30, tzinfo=timezone.utc),  # after day 3 ended
                    datetime(2026, 7, 30, tzinfo=timezone.utc)]).dt.cast_time_unit("us")
    assert run_day_of(ts, days).tolist() == [1, 2, 4, -1]
    groups = agent_goal_groups(pl.DataFrame({"agent_id": ["a1"]}), {"a1": "OpenAI"})
    assert groups == [{"agent:a1", "family:OpenAI", "family:All agents"}]


def test_documented_columns_respect_groups():
    goals = _entries([20])
    agoals = _entries([50, 80])
    groups = [{"agent:a1", "family:F", "family:All agents"}, {"agent:a2"}]
    cps = pl.DataFrame({"run_day": [21, 50, 50, 80, 80], "resolution_run_days": [1, 1, 1, 1, 1],
                        "group_key": ["agent:a1", "agent:a1", "agent:a2", "agent:a1", None]})
    d = documented_columns(cps, goals, agoals, groups, 3, 100)
    assert d["aligned_goal_transition"].to_list() == [True, False, False, False, False]
    assert d["aligned_agent_goal"].to_list() == [False, True, False, False, False]
    assert d["agent_goal_gap_run_days"].to_list() == [29, 0, 30, 30, None]


def _monitor():
    f = pl.DataFrame({
        "finding_id": [f"f{i}" for i in range(6)],
        "run_day": [10, 10, 11, 14, 20, 21],
        "category": ["likely-scaffolding-issue", "conflict", "likely-scaffolding-issue",
                     "emotional-or-erratic", "likely-scaffolding-issue", "other"],
        "severity": ["medium", "low", "low", "high", "high", "low"],
        "confidence": ["high"] * 6,
        "agent_ids": [["a1"], ["a2"], ["a1", "a2"], ["a2"], ["a1"], ["a1"]],
    })
    covered = np.array([10, 11, 12, 13, 14, 20, 21])
    return Monitor(f, covered, (10, 21))


def test_monitor_entries_and_annotations():
    mon = _monitor()
    days = _days(30)
    e = monitor_entries(mon, "likely-scaffolding-issue", days)
    assert e["rd_start"].to_list() == [10, 20]       # medium/high only
    assert monitor_entries(mon, "likely-scaffolding-issue", days, ("high",))["rd_start"].to_list() == [20]
    cps = pl.DataFrame({"series_id": ["agent:A:x", "family:All agents:x", "agent:A:x"],
                        "method": ["pelt_l2"] * 3, "cp_index": [1, 1, 2], "run_day": [11, 11, 30],
                        "resolution_run_days": [1, 1, 1]})
    cols, links = annotate(cps, mon, {"agent:A:x": {"a1"}, "family:All agents:x": None}, 1)
    assert cols["monitor_covered_days"].to_list() == [3, 3, 0]
    assert cols["monitor_n_findings"].to_list()[:2] == [3, 3]
    assert cols["monitor_n_series_agents"].to_list()[:2] == [2, 3]
    assert cols["monitor_series_agents_severe_ids"][0] == "f0"
    assert cols["monitor_by_severity"][0] == "medium:1;low:2"
    assert links.height == 5 and set(links["finding_id"]) == {"f0", "f1", "f2"}


def test_monitor_series_counts():
    mon = _monitor()
    agents = pl.DataFrame({"agent_id": ["a1", "a2"], "model_family": ["OpenAI", "Google"]})
    specs, values = monitor_series(mon, agents, 30)
    assert len(specs) == 11 * 3
    assert all(s.level == "external" for s in specs)
    # Seven covered days in the window: below MIN_POINTS, so every series is skipped.
    assert all(s.skipped is not None for s in specs) and values.is_empty()


# --- figure ---------------------------------------------------------------------------------------

def test_timeline_figure(tmp_path):
    d0 = date(2025, 4, 2)
    series = pl.DataFrame({"series_id": [f"s{i}" for i in range(30)],
                           "level": ["family"] * 5 + ["agent"] * 20 + ["lexical"] * 5})
    rng = np.random.default_rng(SEED)
    cps = pl.DataFrame({"series_id": [f"s{i}" for i in rng.integers(0, 30, 60)],
                        "date": [d0 + timedelta(days=int(k)) for k in rng.integers(0, 500, 60)],
                        "aligned": rng.random(60) < 0.5})
    entries = pl.DataFrame({"source": ["changelog", "roster", "changelog"],
                            "date_start": [d0, d0 + timedelta(days=100), d0 + timedelta(days=400)]})
    goals = pl.DataFrame({"date_start": [d0 + timedelta(days=50), d0 + timedelta(days=300)]})
    paths = plot_timeline(cps, entries, series, tmp_path / "F5", goals=goals)
    assert all(p.exists() and p.stat().st_size > 1000 for p in paths)
