"""External validation of module A against the LLM monitor (avsd.validate.monitor_hawkes): findings, V1
flags and the stratified estimate, V2 ranks and clusters, coverage and the privacy of the outputs."""

import re
from datetime import date, datetime, timedelta, timezone

import numpy as np
import polars as pl
import pytest

from avsd.validate import monitor_hawkes as M

UTC = timezone.utc
SEED = 20261003
D1, D2, D_OFF = date(2026, 6, 29), date(2026, 6, 30), date(2026, 7, 10)
HUMAN = "Alice Example"
FORBIDDEN = re.compile(r"heading|summar|evidence|why_flagged|text")


def _ts(d: date, h: int, m: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=UTC)


def _raw(rows: list[dict]) -> pl.DataFrame:
    base = {"ts_format": "pt_datetime", "window_label": None, "severity": "low", "confidence": "high",
            "unmatched_agents": [], "in_export": True, "fetched_at_utc": "2026-10-01T03:00:00+00:00"}
    out = [base | {"finding_id": f"f{k:03d}", **r} for k, r in enumerate(rows)]
    schema = {"finding_id": pl.String, "date": pl.Date, "ts_utc": pl.Datetime("us", "UTC"), "ts_format": pl.String,
              "window_label": pl.String, "category": pl.String, "severity": pl.String, "confidence": pl.String,
              "agent_ids": pl.List(pl.String), "unmatched_agents": pl.List(pl.String), "in_export": pl.Boolean,
              "fetched_at_utc": pl.String}
    return pl.DataFrame(out, schema=schema).select(M.FINDING_COLS)


# --- findings ---------------------------------------------------------------------------------------------


def test_prepare_findings_dedup_and_v1_set():
    raw = _raw([
        {"date": D1, "ts_utc": _ts(D1, 18), "category": "conflict", "agent_ids": ["A2", "A1"]},
        {"date": D1, "ts_utc": _ts(D1, 18), "category": "conflict", "agent_ids": ["A1", "A2", "A1"]},   # repeat
        {"date": D1, "ts_utc": _ts(D1, 18), "category": "off-goal", "agent_ids": ["A1", "A2"]},         # other category
        {"date": D1, "ts_utc": _ts(D1, 19), "category": "conflict", "agent_ids": ["A1"],
         "unmatched_agents": [HUMAN]},                                               # conflict, 1 agent
        {"date": D1, "ts_utc": _ts(D1, 20), "category": "good-tweet", "agent_ids": ["A3"]},   # 1 agent: not V1
        {"date": D1, "ts_utc": _ts(D1, 17), "category": "other", "agent_ids": ["A1", "A3"], "in_export": False},
    ])
    f, n_dup = M.prepare_findings(raw)
    assert n_dup == 1 and f.height == 4
    assert f["fid"].to_list() == [0, 1, 2, 3]
    assert f["agent_ids"].to_list()[0] == ["A1", "A2"]
    assert f["v1"].to_list() == [True, True, True, False]
    assert f.filter(pl.col("n_unmatched") > 0)["category"].to_list() == ["conflict"]
    assert f["t"][0] == pytest.approx(_ts(D1, 18).timestamp())


def test_label_check_handles_midnight():
    day, night = "07:00–19:00 UTC", "19:00–07:00 UTC"
    raw = _raw([
        {"date": D1, "ts_utc": _ts(D1, 18), "category": "other", "agent_ids": ["A1"], "window_label": day},
        {"date": D1, "ts_utc": _ts(D1, 23), "category": "other", "agent_ids": ["A1"], "window_label": day},
        {"date": D1, "ts_utc": _ts(D1, 2), "category": "other", "agent_ids": ["A1"], "window_label": night,
         "ts_format": "utc_time"},
    ])
    f, _ = M.prepare_findings(raw)
    assert M.label_check(f) == {"pt_datetime": [1, 2], "utc_time": [1, 1]}


# --- module A posterior ---------------------------------------------------------------------------------


def test_target_class_sums_match_module_a():
    from avsd.hawkes.model import Day, HawkesSpec, _posterior, _share_sums, decompose, fit, pack

    rng = np.random.default_rng(3)
    days = []
    for _ in range(3):
        T = 4 * 3600.0
        days.append(Day(T, np.sort(rng.uniform(0, T, 120)), rng.integers(0, 3, 120),
                        exo_times=(np.sort(rng.uniform(0, T, 10)), np.sort(rng.uniform(0, T, 5)))))
    pk = pack(days, 3, HawkesSpec(), exo_names=("human", "system"))
    f = fit(pk, 3, kernel_sharing="class")
    n = pk.tgt_dim.size
    p0, pp = _posterior(f.mu, f.alpha, np.ones(n), pk.tgt_dim, pk.tgt_bin, pk.ptr, pk.par_src, pk.phi)
    sums = M.target_class_sums(pk.tgt_dim, pk.ptr, pk.par_src, p0, pp, pk.K, pk.H)
    assert np.allclose(sums.sum(1), 1.0)
    by_dim = np.vstack([sums[pk.tgt_dim == k].sum(0) for k in range(3)])
    assert np.allclose(by_dim, _share_sums(pk, p0, pp, np.ones(n)))
    assert np.allclose(sums.mean(0), list(decompose(pk, f, min_prob=1.0).shares.values()))


# --- synthetic world: two groups on two dates ---------------------------------------------------------------


def _fits() -> dict:
    rng = np.random.default_rng(1)
    nb = np.full((4, 4), 0.02)
    nb[0, 1], nb[1, 0] = 0.30, 0.20          # A1-A2 is the strongest pair of best
    nb[2, 3] = 0.05
    np.fill_diagonal(nb, 0.4)
    nr = np.full((4, 4), 0.03)
    nr[1, 2] = 0.10
    np.fill_diagonal(nr, 0.3)
    boot = lambda n: np.clip(n[None] + rng.normal(0, 0.005, (6, *n.shape)), 0, None)
    best = M.WindowFit("g50", "best", D1, D2, ["A1", "A2", "A3", "A4"],
                       ["Model A1", "Model A2", "Model A3", "Model A4"],
                       nb, np.zeros(4, np.int64), boot(nb))
    rest = M.WindowFit("g50", "rest", D1, D2, ["A3", "A5", "A6", "A7"],
                       ["Model A3", "Model A5", "Model A6", "Model A7"],
                       nr, np.zeros(4, np.int64), boot(nr))
    return {best.key: best, rest.key: rest}


PLANTED = [(D1, 18, 0, ["A1", "A2"]), (D2, 19, 0, ["A1", "A2"])]


def _events(fits: dict, effect: float = 0.2) -> pl.DataFrame:
    """48 messages per agent, group and date; near a planted conflict the agent's other-agent share is
    `effect` higher. The other-agent share is split evenly over the window's other agents, so the share
    on one partner is p_other / (K - 1). Sets each window's per-source parent masses."""
    rng = np.random.default_rng(2)
    rows = []
    for w in fits.values():
        mass = []
        for rid, d in enumerate((D1, D2), start=100):
            start = _ts(d, 16)
            for a, nm in zip(w.agent_ids, w.agent_names):
                for k in range(48):
                    ts = start + timedelta(minutes=5 * k + float(rng.uniform(0, 4)))
                    near = any(dd == d and a in ags and abs((ts - _ts(dd, h, mm)).total_seconds()) <= 1800
                               for dd, h, mm, ags in PLANTED)
                    po = 0.3 + (effect if near else 0.0) + rng.normal(0, 0.02)
                    ph = 0.05 + rng.normal(0, 0.01)
                    p = {"baseline": 0.3, "human": ph, "system": 0.02, "other_agents": po}
                    p["self"] = 1.0 - sum(p.values())
                    row = np.full(w.K + 2, po / (w.K - 1))
                    row[w.dim[a]], row[w.K], row[w.K + 1] = p["self"], ph, 0.02
                    rows.append({"event_uid": f"chat:{w.group}-{a}-{rid}-{k}", "window_id": w.window_id,
                                 "group": w.group, "realization_id": rid, "run_date": d, "actor_id": a, "agent": nm,
                                 "ts_utc": ts, "t_run": (ts - start).total_seconds(), "src_row": len(mass),
                                 **{f"p_{c}": p[c] for c in M.CLASSES}, **{f"q_{c}": p[c] * 0.95 for c in M.CLASSES}})
                    mass.append(row)
        w.src_mass = np.array(mass)
        w.src_mass_q = w.src_mass * 0.95
    return M.finish_events(pl.DataFrame(rows))


def _findings() -> pl.DataFrame:
    rows = [{"date": d, "ts_utc": _ts(d, h, m), "category": "conflict", "agent_ids": ags,
             "unmatched_agents": [HUMAN]} for d, h, m, ags in PLANTED]
    rows += [
        {"date": D1, "ts_utc": _ts(D1, 17), "category": "off-goal", "agent_ids": ["A3", "A1"], "severity": "medium"},
        {"date": D1, "ts_utc": _ts(D1, 17, 30), "category": "other", "agent_ids": ["A3", "A5"]},
        {"date": D2, "ts_utc": _ts(D2, 17), "category": "interesting-content", "agent_ids": ["A1", "A5"]},
        {"date": D_OFF, "ts_utc": _ts(D_OFF, 17), "category": "conflict", "agent_ids": ["A1", "A2"]},
        {"date": D1, "ts_utc": _ts(D1, 18, 40), "category": "good-tweet", "agent_ids": ["A4"]},
    ]
    return M.prepare_findings(_raw(rows))[0]


def test_recent_counts_split_other_and_own():
    ev = pl.DataFrame({"event_uid": list("abcde"), "window_id": "w", "group": "g", "realization_id": 1,
                       "actor_id": ["x", "y", "x", "y", "x"], "t": [0.0, 100.0, 200.0, 650.0, 700.0]})
    other, own = M.recent_counts(ev, 600.0)
    # e (x at 700) sees y at 100 and 650: the window [t - 600, t) includes its start
    assert other.tolist() == [0, 1, 1, 1, 2]
    assert own.tolist() == [0, 0, 1, 1, 1]     # d (y at 650) sees its own message at 100


def test_finding_hits_and_near_mask():
    ev = _events(_fits())
    t, aidx = ev["t"].to_numpy(), M.actor_index(ev)
    tc = _ts(D1, 18).timestamp()
    (hits,) = M.finding_hits(t, aidx, [["A1", "A2"]], np.array([tc]), 1800.0)
    sel = ev.with_row_index("_i").filter(pl.col("_i").is_in(hits.tolist()))
    assert set(sel["actor_id"].to_list()) == {"A1", "A2"}
    assert (np.abs(sel["t"].to_numpy() - tc) <= 1800).all()
    inside = ev.filter(pl.col("actor_id").is_in(["A1", "A2"]) & ((pl.col("t") - tc).abs() <= 1800))
    assert len(hits) == inside.height
    near = M.near_mask(t, np.array([tc]), 1800.0)
    assert near.sum() == ev.filter((pl.col("t") - tc).abs() <= 1800).height


# --- V1 ---------------------------------------------------------------------------------------------------


def _strata_frame(rng, n_real=30, confound=False):
    rows = []
    for r in range(n_real):
        for a, base in (("A", 0.7 if confound else 0.4), ("B", 0.2 if confound else 0.4)):
            for k in range(20):
                flagged = (a == "A" and k < 10) if confound else k < 5
                v = base + (0.0 if confound else (0.2 if flagged else 0.0)) + rng.normal(0, 0.02)
                rows.append({"stratum": f"w|g|{r}|{a}", "actor_id": a, "realization_id": r, "flag": flagged,
                             **{f"p_{c}": v if c == "other_agents" else 0.1 for c in M.CLASSES},
                             "other_msgs_10min": 1.0})
    return pl.DataFrame(rows)


def test_v1_effect_recovers_a_planted_difference():
    df = _strata_frame(np.random.default_rng(5))
    fl = df["flag"].to_numpy()
    res = M.v1_effect(df, fl, ~fl, "realization_id", 500, SEED)
    o = res["measures"]["other_agents"]
    assert o["diff"] == pytest.approx(0.2, abs=0.01)
    assert o["diff_lo"] < 0.2 < o["diff_hi"] and o["diff_hi"] - o["diff_lo"] < 0.02
    assert res["n_strata"] == 60 and res["n_clusters"] == 30 and res["n_flagged_msgs"] == 300
    assert res["measures"]["human"]["diff"] == pytest.approx(0.0, abs=1e-12)


def test_v1_effect_is_stratified_by_agent():
    """A pooled comparison would credit A's higher share to the flag; within strata there is none."""
    df = _strata_frame(np.random.default_rng(6), confound=True)
    fl = df["flag"].to_numpy()
    pooled = df.filter(pl.col("flag"))["p_other_agents"].mean() - df.filter(~pl.col("flag"))["p_other_agents"].mean()
    assert pooled > 0.2
    res = M.v1_effect(df, fl, ~fl, "realization_id", 500, SEED)
    o = res["measures"]["other_agents"]
    assert abs(o["diff"]) < 0.01 and o["diff_lo"] < 0 < o["diff_hi"]
    assert res["n_agents"] == 1   # B has no flagged messages, so its strata do not count


def test_v1_effect_rejects_overlap():
    df = _strata_frame(np.random.default_rng(7))
    fl = df["flag"].to_numpy()
    with pytest.raises(ValueError):
        M.v1_effect(df, fl, np.ones_like(fl), "realization_id", 10, SEED)


def test_partner_share_uses_the_findings_other_agents():
    fits = _fits()
    ev, f = _events(fits), _findings()
    t, aidx = ev["t"].to_numpy(), M.actor_index(ev)
    conf = f.filter(pl.col("v1") & (pl.col("category") == "conflict"))
    hits = M.finding_hits(t, aidx, conf["agent_ids"].to_list(), conf["t"].to_numpy(), 1800.0)
    co = M.partner_share(ev, fits, hits, conf["agent_ids"].to_list())
    flagged = M.union_mask(ev.height, hits)
    po = ev["p_other_agents"].to_numpy()
    assert np.allclose(co[flagged], po[flagged] / 3)          # one partner of three other agents in best
    a3 = (ev["actor_id"] == "A3").to_numpy()
    assert np.isnan(co[a3]).all()                              # A3 has no conflict findings


def test_run_v1_on_planted_effect():
    fits = _fits()
    ev, f = _events(fits), _findings()
    v1, cov, flags = M.run_v1(ev, f, fits, 300, SEED)
    main = v1.filter(pl.col("analysis") == M.MAIN)
    assert set(main["measure"].to_list()) == set(M.MEASURES)
    conflict = main.filter(pl.col("subset") == "category: conflict")
    get = lambda m: conflict.filter(pl.col("measure") == m).row(0, named=True)
    c = get("other_agents")
    assert c["diff"] == pytest.approx(0.2, abs=0.03) and c["diff_lo"] > 0.1
    assert get("co_involved")["diff"] == pytest.approx(0.2 / 3, abs=0.015)
    assert get("own_msgs_10min")["diff"] == pytest.approx(0.0, abs=0.5)
    assert c["n_findings"] == 3 and c["n_findings_with_msgs"] == 2 and c["n_findings_used"] == 2
    assert set(v1["analysis"].to_list()) >= {"half width 15 min", "clusters = run dates",
                                             "parents table (prob >= 0.01)", "strata also by hour of the run"}
    hour = v1.filter((pl.col("analysis") == "strata also by hour of the run") & (pl.col("subset") == M.ALL)
                     & (pl.col("measure") == "other_agents")).row(0, named=True)
    assert hour["n_strata"] > main.filter((pl.col("subset") == M.ALL)
                                          & (pl.col("measure") == "other_agents"))["n_strata"][0]
    assert not (flags["flagged"] & flags["control"]).any()
    assert cov.height == f.filter(pl.col("v1")).height


# --- V2 ---------------------------------------------------------------------------------------------------


def test_pair_percentiles_midranks_and_null_mean():
    n = np.array([[0.0, 0.3, 0.1, 0.0], [0.2, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.1], [0.0, 0.0, 0.0, 0.0]])
    p = M.pair_percentiles(n)
    iu = np.triu_indices(4, 1)
    assert np.isnan(np.diag(p)).all() and np.allclose(p, p.T, equal_nan=True)
    assert p[iu].mean() == pytest.approx(0.5)
    assert p[0, 1] == pytest.approx(5.5 / 6)                        # largest of 6 pairs
    assert p[1, 2] == pytest.approx(p[0, 3]) == pytest.approx(1.5 / 6)   # three-way tie at 0: mid-rank
    assert M.pair_percentiles(np.stack([n, n.T])).shape == (2, 4, 4)


def test_cluster_shares_and_forced_blocks():
    assert M.within_share_from_sizes(np.array([0, 0, 1, 1, 1])) == pytest.approx(8 / 20)
    assert M.within_share_from_sizes(np.zeros(5, np.int64)) == 1.0
    from avsd.hawkes.report import spectral_blocks

    n = np.full((6, 6), 0.01)
    n[:3, :3], n[3:, 3:] = 0.3, 0.25
    np.fill_diagonal(n, 0.5)
    lab, k, _ = spectral_blocks(n)
    assert k == 2
    assert np.array_equal(M.forced_blocks(n, 2, SEED), lab)
    assert M.forced_blocks(n[:3, :3], 2, SEED).tolist() == [0, 0, 0]   # too few agents: one cluster


def test_pair_instances_choose_the_shared_group():
    fits, f = _fits(), _findings()
    ev = _events(fits)
    times = {(w, g, a): np.sort(np.asarray(t)) for w, g, a, t in
             ev.group_by("window_id", "group", "actor_id").agg("t").iter_rows()}
    inst = M.pair_instances(f.filter(pl.col("v1")), fits, times, 1800.0)
    got = {(r["category"], r["group"], r["reason"]) for r in inst.iter_rows(named=True)}
    assert ("off-goal", "best", "") in got                         # A3 is in both groups, A1 only in best
    assert ("other", "rest", "") in got
    assert ("interesting-content", None, "agent not a dimension") in got
    assert ("conflict", None, "no fitted window on the date") in got
    assert (inst["ia"] < inst["ib"]).fill_null(True).all()


def test_run_v2_ranks_the_planted_pair():
    fits = _fits()
    ev, f = _events(fits), _findings()
    v2, pairs, inst, facts = M.run_v2(f, ev, fits, 300, SEED)
    r = v2.filter((pl.col("subset") == "category: conflict") & (pl.col("statistic") == "mean_percentile")
                  & (pl.col("unit") == "finding pair")).row(0, named=True)
    assert r["value"] == pytest.approx(5.5 / 6) and r["ref_all_pairs"] == pytest.approx(0.5)
    assert r["n_instances"] == 2 and r["n_not_covered"] == 1 and r["n_dates"] == 2
    assert r["lo"] - 1e-9 <= r["value"] <= r["hi"] + 1e-9
    b = v2.filter((pl.col("blocks") == "module A (eigengap)")
                  & (pl.col("subset") == "category: conflict")).row(0, named=True)
    assert b["value"] == 1.0 and b["ref_all_pairs"] == 1.0 and b["n_windows_multi_cluster"] == 0
    top = pairs.row(0, named=True)
    assert (top["agent_a"], top["agent_b"], top["n_conflict"]) == ("Model A1", "Model A2", 2)
    assert top["n_a_from_b"] == pytest.approx(0.30) and top["n_b_from_a"] == pytest.approx(0.20)
    assert facts["multi_cluster"]["module A (eigengap)"] == 0


# --- coverage and privacy ---------------------------------------------------------------------------------


def test_coverage_and_report_hold_no_text_or_human_names(tmp_path):
    fits = _fits()
    ev, f = _events(fits), _findings()
    v1, cov1, _ = M.run_v1(ev, f, fits, 200, SEED)
    v2, pairs, inst, facts = M.run_v2(f, ev, fits, 200, SEED)
    cov = M.coverage_table(f, fits, cov1, inst)
    allrow = cov.filter(pl.col("category") == M.ALL).row(0, named=True)
    assert allrow["findings"] == 6 and allrow["date_in_fitted_window"] == 5 and allrow["with_unmatched_names"] == 2
    assert allrow["pairs"] == 6 and allrow["pairs_covered"] == 4
    checks = [{"window_id": w.window_id, "group": w.group, "date_start": w.date_start, "date_end": w.date_end,
               "K": w.K, "events": 10, "realizations": 2, "share_other_agents": 0.3, "dropped_mass_mean": 0.05,
               "stored_rows": 5, "only_stored": 0, "only_recomputed": 0, "max_abs_diff": 0.0, "events_not_stored": 0}
              for w in fits.values()]
    ctx = {"v1": v1, "v2": v2, "pairs": pairs, "coverage": cov, "checks": checks, "instances": inst,
           "v2_facts": facts, "n_boot": 200, "share_check": 1e-5, "labels": M.label_check(f), "fetched": "x",
           "findings_facts": {"in_export": 7, "dups": 0, "kept": 7, "v1": 6, "v1_conflict": 3, "v1_unmatched": 2},
           "v3": M.v3_status(tmp_path), "reading": M.reading_lines(v1, v2), "secs": 1.0}
    path = tmp_path / "qa" / "monitor_validation.md"
    M.write_report(path, ctx)
    text = path.read_text(encoding="utf-8")
    assert "## 3. V1" in text and "## 8. V3 (module C): status" in text and "not readable" in text
    for df in (v1, v2, pairs, cov):
        assert not any(FORBIDDEN.search(c) for c in df.columns)
        assert HUMAN not in df.write_csv()
    assert HUMAN not in text and "chat:" not in text
