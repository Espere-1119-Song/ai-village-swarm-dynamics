"""Tests for module B1 (memory chains): anchors, chain states, survival statistics.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from datetime import date, datetime, timedelta, timezone

import numpy as np
import polars as pl
import pytest

from avsd.lineage import survival as sv
from avsd.lineage.anchors import (
    TYPE_CODE, TYPES, AnchorExtractor, LiteralIndex, ctx_adjacent, display_value, keyed_hash, load_salt,
    url_domain,
)
from avsd.lineage.chains import (
    EVENT_CENSORED, EVENT_DROPPED, EVENT_MODIFIED, KIND_COPY, KIND_EXT, KIND_FULL, REL_CODE,
    SRC_RECREATED, SRC_REAPPENDED, AgentInput, LineAligner, V2Data, run_chain,
)
from avsd.lineage.memory import (
    live_rows, monthly_hazards, second_spells, segment_lines, states_from_snapshots,
)

SALT = bytes(range(32))
NAMES = ["Claude Opus 4.5", "Claude Sonnet 4.5", "Claude 3.7 Sonnet", "GPT-5.1", "GPT-5",
         "Gemini 2.5 Pro", "Gemini 3.1 Pro", "o3", "Opus 4.5 (Claude Code)", "Fine-Tuned Leader",
         "[Temporary] Fine-tuned Leader"]


@pytest.fixture(scope="module")
def rx():
    return AnchorExtractor(NAMES, SALT, nlp=None)


@pytest.fixture(scope="module")
def nlp_ex():
    spacy = pytest.importorskip("spacy")
    try:
        nlp = spacy.load("en_core_web_sm")
    except OSError:
        pytest.skip("en_core_web_sm not installed")
    return AnchorExtractor(NAMES, SALT, nlp=nlp)


def _vals(rx, text, kind=None):
    found, _ = rx.regex_anchors(text)
    return sorted(v for _, _, t, v in found if kind is None or t == kind)


# --- anchors -------------------------------------------------------------------

def test_regex_normalisation(rx):
    t = "Raised $1,234.50 (12%) by 2026-04-01 at 3:30 PM; goal $5k, 2.5 million views, Apr 3, 2026"
    assert _vals(rx, t, "money") == ["USD:1234.5", "USD:5000"]
    assert _vals(rx, t, "percent") == ["12"]
    assert _vals(rx, t, "date") == ["2026-04-01", "2026-04-03"]
    assert _vals(rx, t, "time") == ["15:30"]
    assert _vals(rx, t, "number") == ["2500000"]
    assert _vals(rx, "Day 12: 5 tasks, 1,200 visits", "date") == ["day:12"]
    assert _vals(rx, "Day 12: 5 tasks, 1,200 visits", "number") == ["1200", "5"]


def test_list_and_section_numbers_skipped(rx):
    assert _vals(rx, "1. First item with 3 agents", "number") == ["3"]
    assert _vals(rx, "2) second", "number") == []
    assert _vals(rx, "### 3.2 Results", "number") == []
    assert _vals(rx, "- 4 issues closed", "number") == ["4"]
    # Digits inside ids, UUIDs, hex and paths are not numbers.
    assert _vals(rx, "commit 3f2a9c1d in /home/user/v2/file 54b95baa-85ed-4efb-8444-84b61dd5b77d",
                 "number") == []


def test_urls_drop_tracking_and_secrets(rx):
    v = _vals(rx, "See https://example.org/page?utm_source=x&id=5&token=abc).", "url")
    assert v == ["https://example.org/page?id=5"]
    assert _vals(rx, "repo github.com/Owner/Repo/blob/main/a.py", "url") == ["github:owner/repo/a.py"]
    assert _vals(rx, "site: myproject.netlify.app/", "url") == ["https://myproject.netlify.app"]
    assert url_domain("https://www.example.org/x?y=1") == "example.org"
    assert url_domain("github:owner/repo") == "github.com"


def test_agent_names(rx):
    t = "Opus 4.5 and Claude Sonnet 4.5 met GPT-5.1, gpt-5, Sonnet 3.7, Claude Code and Claude"
    assert _vals(rx, t, "agent") == sorted([
        "claude opus 4.5", "claude sonnet 4.5", "gpt-5.1", "gpt-5", "claude 3.7 sonnet",
        "opus 4.5 (claude code)", "bare:claude"])
    # A short form shared by two agents is a bare mention; versions are not numbers.
    assert _vals(rx, "Fine-tuned Leader posted", "agent") == ["bare:fine-tuned leader"]
    assert _vals(rx, "Gemini 3.1 Pro vs Gemini 2.5", "number") == []
    assert _vals(rx, "Gemini 3.1 Pro vs Gemini 2.5", "agent") == ["gemini 2.5 pro", "gemini 3.1 pro"]


def test_pii_hashed(rx):
    out = rx.anchors_for("Email a.b@example.com or call (215) 555-0134, acct 123456789012", None, False)
    kinds = {TYPES[t]: v for t, v, _ in out}
    assert kinds["email"].startswith("h:") and kinds["phone"].startswith("h:")
    assert kinds["number"].startswith("h:")  # long digit run
    assert all(v.startswith("h:") and len(v) == 18 for _, v, _ in out)
    assert kinds["email"] == keyed_hash(SALT, "email", "a.b@example.com")
    assert kinds["phone"] == keyed_hash(SALT, "phone", "2155550134")


def test_credential_lines_hashed(rx):
    out = rx.anchors_for("Password reset code 4821, expires 10:30", None, False)
    assert out and all(v.startswith("h:") for _, v, _ in out)
    plain = rx.anchors_for("Expires 10:30", None, False)
    assert [v for _, v, _ in plain] == ["10:30"]


def test_heading_sensitivity():
    text = "## Notes\n- Visits: 42\n## Accounts & Credentials\n- Visits: 42\n## Plan\n- Visits: 42\n"
    hs, items = segment_lines(text, KIND_FULL, 0)
    sens = {i: s for i, (_, _, s) in enumerate(items)}
    lines = [t for _, t, _ in items]
    assert lines.count("- Visits: 42") == 3
    flags = [s for _, t, s in items if t == "- Visits: 42"]
    assert flags == [False, True, False]
    # The same text under the credential heading is a different line.
    assert len({h for h, t, _ in items if t == "- Visits: 42"}) == 2
    assert len(hs) == 7 and hs[-1] == 0 and sens


def test_session_label_removed():
    text = "Notes\n\nPREVIOUS (NOW ENDED) SESSION (Day 5, 10:00 to 12:00)\nOpened 3 tabs"
    _, items = segment_lines(text, KIND_FULL, 0)
    assert [t for _, t, _ in items] == ["Notes", "Opened 3 tabs"]


def test_display_value_privacy():
    assert display_value("person", "alice smith", SALT).startswith("h:")
    assert display_value("email", "h:0123456789abcdef", SALT) == "h:0123456789abcdef"
    d = display_value("url", "https://example.org/private/path?q=1", SALT)
    assert d.startswith("example.org#") and "private" not in d


def test_salt_file(tmp_path):
    s1 = load_salt(tmp_path)
    s2 = load_salt(tmp_path)
    assert s1 == s2 and len(s1) == 32
    assert oct((tmp_path / "b1_anchor_salt").stat().st_mode & 0o777) == "0o600"


def test_context_keys(nlp_ex):
    res = nlp_ex.extract(["- Balance: $120", "We thanked 56 donors yesterday."], [False, False])
    money = [(v, c) for t, v, c in res[0] if t == TYPE_CODE["money"]]
    assert money == [("USD:120", "^balance")] or money == [("USD:120", "balance")]
    nums = [(v, c) for t, v, c in res[1] if t == TYPE_CODE["number"]]
    assert nums == [("56", "donor")]
    # A head inside a DATE entity ("3 days") is still a context key.
    res = nlp_ex.extract(["We waited 3 days for the approval."], [False])
    assert [(v, c) for t, v, c in res[0] if t == TYPE_CODE["number"]] == [("3", "day")]
    # Time zones are not context keys.
    res = nlp_ex.extract(["The standup meeting starts at 10:00 PT."], [False])
    times = [(v, c) for t, v, c in res[0] if t == TYPE_CODE["time"]]
    assert len(times) == 1 and times[0][0] == "10:00" and times[0][1].lstrip("^") not in ("pt", "")


# --- chain states on abstract units ------------------------------------------------

def _abstract_input(label_rows=frozenset()):
    """Lines A..G carry one occurrence each. Occurrence = unit except B/B2 share a context."""
    # occurrence: (unit, tc, value)
    occ = {
        "A": (0, 100, 10),   # url, kept throughout
        "B": (1, 200, 20),   # balance 120
        "B2": (2, 200, 21),  # balance 95 (same context, new value)
        "C": (3, 300, 30),   # date: dropped, then restored by a consolidation
        "D": (4, 400, 40),   # person in an appended block: dropped
        "E": (5, 500, 50),   # appended later, dropped
        "F": (6, 600, 60),   # appended then undone by a revert
    }
    h = {k: i + 1 for i, k in enumerate(occ)}
    keys = sorted(occ, key=lambda k: h[k])
    rows = [
        ("first", KIND_FULL, -1, ["A", "B", "C", 0]),
        ("append_note", KIND_EXT, 0, [0, "D", 0]),
        ("rewrite", KIND_FULL, 1, ["A", "B2", 0]),            # c=1
        ("append_session", KIND_EXT, 2, [0, "E", 0]),
        ("rewrite", KIND_FULL, 3, ["A", "B2", "C", 0]),       # c=2
        ("append_note", KIND_EXT, 4, [0, "F", 0]),
        ("revert", KIND_COPY, 4, []),
        ("rewrite", KIND_FULL, 6, ["A", 0]),                  # c=3
    ]
    seg = [np.array([h[x] if x else 0 for x in r[3]], dtype=np.int64) for r in rows]
    return AgentInput(
        agent_id="a",
        rel=np.array([REL_CODE[r[0]] for r in rows], dtype=np.int8),
        kind=np.array([r[1] for r in rows], dtype=np.int8),
        base=np.array([r[2] for r in rows], dtype=np.int64),
        is_cons=np.array([r[0] == "rewrite" for r in rows]),
        seg=seg,
        line_hash=np.array([h[k] for k in keys], dtype=np.int64),
        line_ptr=np.arange(len(keys) + 1, dtype=np.int64),
        line_occ=np.arange(len(keys), dtype=np.int32),
        occ_unit=np.array([occ[k][0] for k in keys], dtype=np.int32),
        occ_tc=np.array([occ[k][1] for k in keys], dtype=np.int64),
        occ_val=np.array([occ[k][2] for k in keys], dtype=np.int64),
        label_rows=label_rows,
    )


def test_chain_states_abstract():
    r = run_chain(_abstract_input(label_rows=frozenset({2, 4})))
    assert r.n_cons == 3
    u = {int(x): i for i, x in enumerate(r.units["unit"])}
    col = {k: v for k, v in r.units.items()}

    def get(unit, key):
        return int(col[key][u[unit]])

    assert 6 not in u  # F: undone by the revert, never tracked
    # A: kept through all three consolidations, censored with 3 trials.
    assert get(0, "event") == EVENT_CENSORED and get(0, "entry_cons") == 0 and r.n_cons - get(0, "entry_cons") == 3
    # B (120): modified at c=1 (same context, value new since the previous version).
    assert get(1, "event") == EVENT_MODIFIED and get(1, "loss_cons") == 1
    # C: dropped at c=1, restored at c=2 by the consolidation, re-lost at c=3.
    assert get(3, "event") == EVENT_DROPPED and get(3, "loss_cons") == 1
    assert get(3, "restore_cons") == 2 and get(3, "restore_src") == SRC_RECREATED
    assert get(3, "n_restore") == 1 and get(3, "n_reloss") == 1
    # D: entered in an append before c=1, dropped at c=1.
    assert get(4, "event") == EVENT_DROPPED and get(4, "entry_cons") == 0 and get(4, "loss_cons") == 1
    # B2 (95): entered in the output of c=1, kept at c=2, dropped at c=3.
    assert get(2, "entry_cons") == 1 and get(2, "loss_cons") == 3 and get(2, "event") == EVENT_DROPPED
    # E: appended after c=1, dropped at c=2.
    assert get(5, "entry_cons") == 1 and get(5, "loss_cons") == 2
    assert r.qa["untracked_by_undo"] == 1
    # Per-consolidation counts.
    assert list(r.cons["at_risk"]) == [4, 3, 2]
    assert list(r.cons["modified"]) == [1, 0, 0]
    assert list(r.cons["restored"]) == [0, 1, 0]
    # Pair labels (input row vs output row).
    lab1 = {x[0]: x[1] for x in r.pairs[2]}
    assert lab1 == {0: "kept", 1: "modified", 3: "dropped", 4: "dropped", 2: "new"}
    lab2 = {x[0]: x[1] for x in r.pairs[4]}
    assert lab2 == {0: "kept", 2: "kept", 5: "dropped", 3: "restored"}


def test_restoration_by_reappend():
    inp = _abstract_input()
    # Replace row 3's appended line E by C: C comes back in appended text, then is kept.
    inp.seg[3] = np.array([0, 4, 0], dtype=np.int64)  # hash of "C" is 4
    r = run_chain(inp)
    i = int(np.flatnonzero(r.units["unit"] == 3)[0])
    assert r.units["restore_cons"][i] == 2 and r.units["restore_src"][i] == SRC_REAPPENDED


# --- end to end on text (spaCy) -------------------------------------------------------

def test_states_from_text(nlp_ex):
    r0 = "- Website: https://example.org/home\n- Balance: $120\n- Meeting on 2026-04-01\n"
    r1 = r0 + "- Talked to Alice Smith about the plan\n"
    r2 = "- Website: https://example.org/home\n- Balance: $95\n"
    r3 = r2 + "- Meeting on 2026-04-01\n"
    snaps = [("first", r0, -1), ("append_note", r1, 0), ("rewrite", r2, 1), ("rewrite", r3, 2)]
    res, units = states_from_snapshots(snaps, nlp_ex)
    uv = dict(zip(units["unit_gid"].to_list(), zip(units["type"].to_list(), units["value"].to_list())))
    st = {}
    for i, g in enumerate(res.units["unit"].tolist()):
        st[uv[g]] = {k: int(v[i]) for k, v in res.units.items()}
    url = (TYPE_CODE["url"], "https://example.org/home")
    m120, m95 = (TYPE_CODE["money"], "USD:120"), (TYPE_CODE["money"], "USD:95")
    date = (TYPE_CODE["date"], "2026-04-01")
    assert st[url]["event"] == EVENT_CENSORED and res.n_cons - st[url]["entry_cons"] == 2
    assert st[m120]["event"] == EVENT_MODIFIED and st[m120]["loss_cons"] == 1
    assert st[date]["event"] == EVENT_DROPPED and st[date]["restore_cons"] == 2
    assert st[m95]["entry_cons"] == 1 and st[m95]["event"] == EVENT_CENSORED
    persons = [k for k in st if k[0] == TYPE_CODE["person"]]
    assert persons and all(v.startswith("h:") for _, v in persons)
    assert all(st[p]["event"] == EVENT_DROPPED for p in persons)


# --- live rows ------------------------------------------------------------------------

def test_live_rows_drop_dead_branch_and_ident():
    t0 = datetime(2026, 1, 5, tzinfo=timezone.utc)
    # g0 first, a1 append, g2 rewrite (dead), a3 append on g2, f4 fork on a1, x5 ident of f4,
    # a6 append on x5, g7 rewrite (parent g0 lineage).
    recs = [
        ("g0", "first", None, None, "g0", True, 10),
        ("a1", "append_note", "g0", None, "g0", False, 20),
        ("g2", "rewrite", "a1", "g0", "g2", True, 8),
        ("a3", "append_note", "g2", None, "g2", False, 12),
        ("f4", "fork_append", "a1", None, "g0", False, 30),
        ("x5", "ident", "f4", None, "g0", False, 30),
        ("a6", "append_note", "x5", None, "g0", False, 35),
        ("g7", "rewrite", "a6", "g0", "g7", True, 9),
    ]
    mv = pl.DataFrame({
        "id": [r[0] for r in recs], "agent_id": "A",
        "created_at": [t0 + timedelta(minutes=i) for i in range(len(recs))],
        "rel": [r[1] for r in recs], "base_id": [r[2] for r in recs],
        "parent_gen_id": [r[3] for r in recs], "gen_id": [r[4] for r in recs],
        "is_generation": [r[5] for r in recs], "content_len": [r[6] for r in recs],
    })
    rows, qa = live_rows(mv)
    assert rows["id"].to_list() == ["g0", "a1", "f4", "a6", "g7"]
    assert qa["dead_rows"] == 2 and qa["ident_rows"] == 1 and qa["consolidations"] == 1
    b = dict(zip(rows["id"].to_list(), rows["base_idx"].to_list()))
    assert b["f4"] == 1 and b["a6"] == 2  # a6's base x5 is an ident of f4
    k = dict(zip(rows["id"].to_list(), rows["kind"].to_list()))
    assert k["f4"] == KIND_EXT and k["g7"] == KIND_FULL


# --- survival statistics -----------------------------------------------------------------

def test_geometric_hazard_recovered():
    rng = np.random.default_rng(20261003)
    sim = sv.simulate_geometric(n_agents=20, units_per_agent=4000, cons_per_agent=60, h=0.25, rng=rng)
    rc = sv.risk_counts(sim["e"], sim["L"], sim["event"], sim["agent"], 20, 100)
    n, d, _ = rc.pooled(0)
    h = sv.hazard(n[1:11], d[1:11])
    assert np.all(np.abs(h - 0.25) < 0.02)
    w = sv.bootstrap_weights(np.arange(20), 20, 300, rng)
    t = sv.h2_test(rc.n[0], rc.d[0], 100, w)
    assert abs(t.h_geom - 0.25) < 0.005
    assert t.p_lr > 0.001 and t.p_wald > 0.001
    s = sv.km(h)
    assert np.allclose(s, 0.75 ** np.arange(1, 11), atol=0.02)


def test_heterogeneous_hazards_reject_h2():
    rng = np.random.default_rng(7)
    n_ag, per = 10, 3000
    agent = np.repeat(np.arange(n_ag), per)
    hz = rng.beta(2.0, 6.0, size=len(agent))
    life = rng.geometric(hz)
    L = np.minimum(life, 40)
    event = (life <= 40).astype(np.int8)
    e = np.zeros(len(agent), dtype=np.int64)
    rc = sv.risk_counts(e, L, event, agent, n_ag, 50)
    w = sv.bootstrap_weights(np.arange(n_ag), n_ag, 300, rng)
    t = sv.h2_test(rc.n[0], rc.d[0], 50, w)
    assert t.p_lr < 1e-6 and t.bin_h[0] > t.bin_h[-1]
    assert abs(t.bg_alpha / (t.bg_alpha + t.bg_beta) - 0.25) < 0.03
    assert t.aic_betageom < t.aic_geom


def test_risk_counts_trial_strata():
    # One agent with 4 consolidations: strata 0, 0, 1, 1.
    e = np.array([0, 1, 2])
    L = np.array([4, 2, 1])
    ev = np.array([1, 0, 1])
    strata = [np.array([0, 0, 1, 1])]
    rc = sv.risk_counts(e, L, ev, np.zeros(3, dtype=np.int64), 1, 10, strata, 2)
    # Unit 0: trials g=1..4 at c=1..4 (strata 0,0,1,1), lost at g=4 (stratum 1).
    # Unit 1: g=1..2 at c=2..3 (strata 0,1), censored. Unit 2: g=1 at c=3 (stratum 1), lost.
    assert list(rc.n[0, 0, 1:5]) == [2, 1, 0, 0]
    assert list(rc.n[1, 0, 1:5]) == [1, 1, 1, 1]
    assert rc.d[1, 0, 1] == 1 and rc.d[1, 0, 4] == 1 and rc.d[0].sum() == 0


# --- beta-discrete-Weibull ---------------------------------------------------------

def _counts(L, event, g_max):
    n = np.zeros(g_max + 2)
    d = np.zeros(g_max + 2)
    np.add.at(d, L[event > 0], 1.0)
    n[1:g_max + 1] = np.cumsum(np.bincount(L, minlength=g_max + 1)[::-1])[::-1][1:g_max + 1]
    return n, d


def test_bdw_reduces_to_beta_geometric():
    g = np.arange(1, 50)
    h = sv.bdw_hazard(1.3, 2.7, 1.0, g)
    assert np.allclose(h, 1.3 / (1.3 + 2.7 + g - 1))
    # c < 1: individual hazards fall, so the population hazard falls faster than the beta-geometric.
    assert np.all(np.diff(sv.bdw_hazard(1.3, 2.7, 0.6, g)) < 0)


@pytest.mark.parametrize("c_true", [0.6, 1.0])
def test_bdw_recovers_shape(c_true):
    rng = np.random.default_rng(20261003)
    L, ev = sv.simulate_bdw(80_000, 1.5, 3.0, c_true, 40, rng)
    n, d = _counts(L, ev, 40)
    assert n[1] == 80_000 and d[1:].sum() == ev.sum()
    fit = sv.fit_bdw(n, d)
    bg = sv.fit_bdw(n, d, c_fixed=1.0)
    assert abs(fit.c - c_true) < 0.06
    assert abs(fit.alpha / (fit.alpha + fit.beta) - 1.5 / 4.5) < 0.04
    assert fit.ll >= bg.ll - 1e-6
    lr = 2 * (fit.ll - bg.ll)
    if c_true == 1.0:
        assert lr < 10.83  # chi2(1) at p = 0.001
        lo, hi = sv.bdw_profile_ci(n, d, fit, level=0.999)  # covers 1 iff LR < 10.83
        assert lo < 1.0 < hi
    else:
        assert lr > 100
    # Dropping g = 1 gives the likelihood conditional on surviving it, which is still exact.
    n2, d2 = n.copy(), d.copy()
    n2[1], d2[1] = 0, 0
    assert abs(sv.fit_bdw(n2, d2).c - c_true) < 0.1
    # The beta-geometric of the BdW module equals the separate beta-geometric fit.
    a, b, ll = sv.fit_beta_geometric(n[1:41], d[1:41], np.arange(1, 41, dtype=float))
    assert abs(ll - bg.ll) < 0.5


def test_bdw_bootstrap_shape():
    rng = np.random.default_rng(1)
    n_ag = np.zeros((4, 12))
    d_ag = np.zeros((4, 12))
    for a in range(4):
        L, ev = sv.simulate_bdw(3000, 1.0, 2.0, 0.8, 10, rng)
        n_ag[a], d_ag[a] = _counts(L, ev, 10)
    w = sv.bootstrap_weights(np.arange(4), 4, 5, rng)
    fit = sv.fit_bdw(n_ag.sum(0), d_ag.sum(0))
    out = sv.bdw_bootstrap(n_ag, d_ag, w, (fit.alpha, fit.beta, fit.c))
    assert out.shape == (5, 4) and np.isfinite(out[:, 2]).all()


def test_bdw_score_matches_likelihood():
    # Shape c = 3.5 over 300 trials puts k^c near 5e8, where a plain digamma difference
    # psi(b + k^c) - psi(a + b + k^c) has lost almost every digit.
    assert sv._psi_gap(1e15, 0.3) == pytest.approx(-0.3e-15, rel=1e-9)
    assert sv._psi_gap(np.array([1e4 * (1 - 1e-12), 1e4 * (1 + 1e-12)]), 0.7)[0] == pytest.approx(
        sv._psi_gap(1e4 * (1 + 1e-12), 0.7), rel=1e-9)
    rng = np.random.default_rng(7)
    L, ev = sv.simulate_bdw(20_000, 0.4, 0.5, 3.5, 300, rng)
    n, d = _counts(L, ev, 300)
    for x, c_fixed in ((np.log([0.5, 0.4, 3.2]), False), (np.log([0.5, 0.4]), True)):
        def ll(xx, c_fixed=c_fixed):
            return sv.bdw_loglik(n, d, np.exp(xx[0]), np.exp(xx[1]), 1.0 if c_fixed else np.exp(xx[2]))
        num = [(ll(x + h) - ll(x - h)) / 2e-5 for h in np.eye(len(x)) * 1e-5]
        a, b = np.exp(x[:2])
        sc = sv.bdw_score(n, d, a, b, 1.0 if c_fixed else np.exp(x[2]), c_fixed)
        assert np.allclose(sc, num, rtol=1e-4, atol=1e-3)


def test_bdw_converged_flag_is_the_newton_check(monkeypatch):
    # At |ll| near 1e6 Nelder-Mead's absolute tolerances (1e-7) can fail on rounding noise alone
    # (the B1 runs flagged fits 1e-5 nats from the maximum as not converged). `converged` must
    # follow the predicted remaining gain, not the optimiser's own flag.
    rng = np.random.default_rng(20261003)
    L, ev = sv.simulate_bdw(1_000_000, 0.4, 0.4, 2.5, 500, rng)
    n, d = _counts(L, ev, 500)
    fit = sv.fit_bdw(n, d)
    assert fit.converged and 0 <= fit.gain_left <= sv.BDW_GAIN_TOL and abs(fit.c_left) <= sv.BDW_C_TOL
    assert abs(sv.bdw_loglik(n, d, fit.alpha, fit.beta, fit.c)) > 1e6
    real_minimize = sv.optimize.minimize

    def no_success(*args, **kwargs):
        r = real_minimize(*args, **kwargs)
        r.success = False
        return r

    monkeypatch.setattr(sv.optimize, "minimize", no_success)
    again = sv.fit_bdw(n, d)
    assert again.converged and (again.alpha, again.beta, again.c, again.ll) == (fit.alpha, fit.beta, fit.c, fit.ll)
    monkeypatch.undo()
    # A fit stopped far from the maximum is flagged, and the predicted gain matches the real one.
    short = sv.fit_bdw(n, d, start=(5.0, 0.2, 0.6), maxiter=10)
    assert not short.converged and short.gain_left > 1.0
    x = np.log([fit.alpha, fit.beta, fit.c]) + np.array([0.0, 0.0, 2e-3])
    gain, dc, saddle = sv.bdw_newton_check(n, d, *np.exp(x))
    lost = fit.ll - sv.bdw_loglik(n, d, *np.exp(x))
    assert not saddle and gain == pytest.approx(lost, rel=0.05) and dc == pytest.approx(fit.c - np.exp(x[2]), rel=0.05)
    # Mixing distributions at the limit of their range are marked as weakly identified.
    assert sv.bdw_boundary(9.7e7, 5.2e6) and sv.bdw_boundary(1.6, 1e-8) and not sv.bdw_boundary(0.33, 0.38)


# --- repeated spells -------------------------------------------------------------------

def test_second_spells():
    r = run_chain(_abstract_input())
    L2, ev2, bad = second_spells(r)
    i = int(np.flatnonzero(r.units["unit"] == 3)[0])  # C: restored at c = 2, lost again at c = 3
    assert (L2[i], ev2[i], bad) == (1, 1, 0)
    assert all(L2[j] == -1 for j in range(len(L2)) if j != i)
    # If the last consolidation keeps C, the second spell is censored after one trial.
    inp = _abstract_input()
    inp.seg[7] = np.array([1, 4, 0], dtype=np.int64)  # lines A and C
    r = run_chain(inp)
    L2, ev2, bad = second_spells(r)
    i = int(np.flatnonzero(r.units["unit"] == 3)[0])
    assert (L2[i], ev2[i], bad) == (1, 0, 0)
    assert r.units["n_reloss"][i] == 0


# --- monthly hazards ------------------------------------------------------------------

def test_monthly_hazards():
    # One agent, consolidations c = 1..4 in months 0, 0, 1, 1 (as in test_risk_counts_trial_strata).
    e = np.array([0, 1, 2])
    L = np.array([4, 2, 1])
    ev = np.array([1, 0, 1], dtype=np.int8)
    months = [date(2026, 3, 1), date(2026, 4, 1)]
    groups = {"All standard": np.array([0]), "Anthropic": np.array([0])}
    df = monthly_hazards(e, L, ev, np.zeros(3, dtype=np.int64), 1, 10, [np.array([0, 0, 1, 1])], months,
                         groups, min_units=1)
    assert df.columns == ["date", "group", "h1", "h2", "h3_4", "n_at_risk"]
    assert df.height == 2 * 5  # every group gets every month
    row = df.filter((pl.col("group") == "All standard") & (pl.col("date") == date(2026, 4, 1))).row(0, named=True)
    assert row["h1"] == 1.0 and row["h2"] == 0.0 and row["h3_4"] == 0.5 and row["n_at_risk"] == 4
    first = df.filter((pl.col("group") == "All standard") & (pl.col("date") == date(2026, 3, 1))).row(0, named=True)
    assert first["h1"] == 0.0 and first["h2"] == 0.0 and first["n_at_risk"] == 3
    empty = df.filter(pl.col("group") == "Google")
    assert empty["h1"].null_count() == 2 and empty["n_at_risk"].sum() == 0


# --- rules v2: literal presence and line-aligned modification ---------------------------

def test_literal_index():
    text = ("- Partner: ACME  Labs (since April 1, 2026)\n- Standup at 9:30 am daily\n"
            "- Visit https://www.example.org/page?id=5 now\n- Day 12 review with Alice Smith\n"
            "PREVIOUS (NOW ENDED) SESSION (Day 7, 10:00 to 12:00)\n- 56 donors so far")
    idx = LiteralIndex(text, SALT)
    assert len(idx.lines) == 6
    assert idx.has_value("org", "acme labs") and not idx.has_value("org", "acme lab")
    assert idx.has_value("date", "2026-04-01") and idx.has_value("date", "day:12")
    assert not idx.has_value("date", "day:7") and not idx.has_value("time", "10:00")  # session label
    assert idx.has_value("time", "09:30")
    assert idx.has_value("url", "https://example.org/page?id=5")
    assert not idx.has_value("url", "https://example.org/page")  # a longer URL is another resource
    assert idx.has_value("person", keyed_hash(SALT, "person", "alice smith"))
    assert not idx.has_value("person", keyed_hash(SALT, "person", "bob jones"))
    assert idx.line_has_context(5, "donor") and not idx.line_has_context(0, "donor")


def test_line_aligner():
    sig = {4: frozenset({"x"}), 8: frozenset({"x"}), 7: frozenset()}.get
    al = LineAligner([1, 2, 3, 4, 5], [1, 9, 3, 8, 7, 5], lambda h: sig(h, frozenset()))
    assert al.replacement(0) == []  # kept verbatim
    assert al.replacement(1) == [1]  # same offset in a block of equal length
    assert al.replacement(3) == [3]  # unequal block: the line sharing anchor keys
    assert LineAligner([1, 2, 3], [1, 3], lambda h: frozenset()).replacement(1) == []  # deleted


def _v2_input():
    """Two consolidations. Units: 0 org 'acme labs' (no anchor in R_1, literal there), 1 number 120
    'balance' (replaced on its aligned line by 95), 3 number 7 'task' (line deleted; a new value sits
    elsewhere), 5 number 56 'donor' (the same value on a line with 'donors' under another context)."""
    num, org = TYPES.index("number"), TYPES.index("org")
    # occurrence: (line hash, unit, type, value id, (type, context) id)
    occ = [(12, 0, org, 0, -1), (13, 1, num, 1, 100), (22, 2, num, 2, 100), (15, 3, num, 3, 200),
           (24, 4, num, 4, 200), (16, 5, num, 5, 300), (23, 6, num, 5, 400)]
    occ.sort()
    hashes = sorted({o[0] for o in occ})
    ptr = [0]
    for h in hashes:
        ptr.append(ptr[-1] + sum(o[0] == h for o in occ))
    r0 = ["# Notes", "- Partner ACME Labs", "- Balance: $120", "## Mid", "- 7 tasks open", "- 56 donors so far",
          "## End"]
    r1 = ["# Notes", "- Partner: ACME Labs", "- Balance: $95", "## Mid", "- 56 donors to the fund", "## End",
          "- 4 tasks open"]
    r2 = ["# Notes", "## Mid", "## End"]
    seg = [np.array(x, dtype=np.int64) for x in ([11, 12, 13, 14, 15, 16, 17], [11, 21, 22, 14, 23, 17, 24],
                                                 [11, 14, 17])]
    v2 = V2Data(cons_text={1: "\n".join(r1), 2: "\n".join(r2)}, in_text={1: "\n".join(r0)},
                unit_info={0: ("acme labs", ""), 1: ("120", "balance"), 2: ("95", "balance"), 3: ("7", "task"),
                           4: ("4", "task"), 5: ("56", "donor"), 6: ("56", "fund")},
                occ_type=np.array([o[2] for o in occ]), salt=SALT)
    return AgentInput(
        agent_id="a", rel=np.array([REL_CODE["first"], REL_CODE["rewrite"], REL_CODE["rewrite"]], dtype=np.int8),
        kind=np.array([KIND_FULL] * 3, dtype=np.int8), base=np.array([-1, 0, 1]),
        is_cons=np.array([False, True, True]), seg=seg, line_hash=np.array(hashes, dtype=np.int64),
        line_ptr=np.array(ptr, dtype=np.int64), line_occ=np.arange(len(occ), dtype=np.int32),
        occ_unit=np.array([o[1] for o in occ], dtype=np.int32), occ_tc=np.array([o[4] for o in occ]),
        occ_val=np.array([o[3] for o in occ]), label_rows=frozenset({1}), v2=v2)


def test_v2_rules_against_v1():
    r = run_chain(_v2_input())
    i = {int(x): j for j, x in enumerate(r.units["unit"])}

    def st(units, u):
        return int(units["loss_cons"][i[u]]), int(units["event"][i[u]])

    # v1: org dropped, 120 modified, 7 modified (new value elsewhere), 56 donors dropped (context changed).
    assert [st(r.units, u) for u in (0, 1, 3, 5)] == [(1, EVENT_DROPPED), (1, EVENT_MODIFIED),
                                                      (1, EVENT_MODIFIED), (1, EVENT_DROPPED)]
    # v2: org kept by its literal text, 120 still modified (aligned line), 7 now a drop, 56 kept.
    assert [st(r.units2, u) for u in (0, 1, 3, 5)] == [(2, EVENT_DROPPED), (1, EVENT_MODIFIED),
                                                       (1, EVENT_DROPPED), (2, EVENT_DROPPED)]
    assert int(r.units2["n_fallback"][i[0]]) == 1 and int(r.units2["n_fallback"][i[5]]) == 1
    assert list(r.cons2["kept_fallback"]) == [2, 0] and list(r.cons2["modified"]) == [1, 0]
    lab1 = {u: lb for u, lb, _ in r.pairs[1]}
    lab2 = {u: lb for u, lb, _ in r.pairs2[1]}
    assert lab1 == {0: "dropped", 1: "modified", 3: "modified", 5: "dropped", 2: "new", 4: "new", 6: "new"}
    assert lab2 == {0: "kept", 1: "modified", 3: "dropped", 5: "kept", 2: "new", 4: "new", 6: "new"}


def test_v2_leaves_v1_unchanged():
    base = run_chain(_abstract_input(label_rows=frozenset({2, 4})))
    inp = _abstract_input(label_rows=frozenset({2, 4}))
    inp.v2 = V2Data(cons_text={}, in_text={}, unit_info={}, occ_type=np.zeros(len(inp.occ_unit), dtype=np.int64),
                    salt=SALT)
    both = run_chain(inp)
    for key, arr in base.units.items():
        assert np.array_equal(arr, both.units[key]), key
    assert {k: list(v) for k, v in base.cons.items()} == {k: list(v) for k, v in both.cons.items()}
    assert base.pairs == both.pairs
    # Without any text, v2 has nothing to add, so its losses equal v1's apart from the modified rule.
    assert np.array_equal(both.units2["loss_cons"], base.units["loss_cons"])


# --- rules v3: context word adjacent to quantity values -------------------------------------

def test_ctx_adjacent_matches_prelabel():
    from avsd.lineage import prelabel as pre

    cases = [("We thanked 56 new donors today", "56", "donor"), ("Donors: 56 so far", "56", "donor"),
             ("56 to the fund; donors thanked", "56", "donor"), ("Standup at 10:00 daily", "10:00", "standup"),
             ("Standup: 10:00", "10:00", "standup"), ("10:00 standup", "10:00", "standup"),
             ("3 entries left", "3", "entry"), ("donor's gift: $5", "$5", "donor")]
    for text, val, lemma in cases:
        s = text.index(val)
        assert ctx_adjacent(text, s, s + len(val), lemma) == pre._ctx_adjacent(text, s, s + len(val), [lemma]), text
    assert ctx_adjacent("We thanked 56 new donors", 11, 13, "donor")
    assert not ctx_adjacent("56 to the fund; donors thanked", 0, 2, "donor")


def test_quantity_adjacent():
    ex = AnchorExtractor(NAMES, SALT)
    idx = LiteralIndex("- We thanked 56 new donors\n- 56 to the fund; donors thanked\n- Standup: 10:00\n"
                       "- Standup at 10:00 daily\n- Raised $1,234 from donors", SALT)
    assert idx.quantity_adjacent(0, "number", "56", "donor", ex)
    assert not idx.quantity_adjacent(1, "number", "56", "donor", ex)
    assert idx.quantity_adjacent(2, "time", "10:00", "standup", ex)
    assert not idx.quantity_adjacent(3, "time", "10:00", "standup", ex)  # "at" between, as in the prelabel rule
    assert idx.quantity_adjacent(4, "money", "USD:1234", "donor", ex)  # "from" is one word between
    assert idx.quantity_adjacent(0, "number", keyed_hash(SALT, "number", "56"), "donor", ex)  # hashed value


def _v3_input():
    inp = _v2_input()
    inp.v2.versions = ("v2", "v3")
    inp.v2.agent_names = tuple(NAMES)
    r1 = inp.v2.cons_text[1].split("\n")
    r1[4] = "- 56 to the fund; donors thanked"  # the context word on the line, but not next to the value
    inp.v2.cons_text[1] = "\n".join(r1)
    return inp


def test_v3_rules_against_v2():
    r = run_chain(_v3_input())
    i = {int(x): j for j, x in enumerate(r.units["unit"])}

    def st(units, u):
        return int(units["loss_cons"][i[u]]), int(units["event"][i[u]])

    # v2 keeps 56 'donor' (the word is on the line); v3 needs it next to the value and drops it.
    assert st(r.units2, 5) == (2, EVENT_DROPPED) and st(r.units3, 5) == (1, EVENT_DROPPED)
    # Entity fallback and line-aligned modification are the same in v2 and v3.
    for u, want in ((0, (2, EVENT_DROPPED)), (1, (1, EVENT_MODIFIED)), (3, (1, EVENT_DROPPED))):
        assert st(r.units2, u) == want and st(r.units3, u) == want
    assert list(r.cons3["kept_fallback"]) == [1, 0] and list(r.cons2["kept_fallback"]) == [2, 0]
    lab3 = {u: lb for u, lb, _ in r.pairs3[1]}
    assert lab3 == {0: "kept", 1: "modified", 3: "dropped", 5: "dropped", 2: "new", 4: "new", 6: "new"}
    # v1 is unaffected by the extra rule sets.
    assert st(r.units, 5) == (1, EVENT_DROPPED) and st(r.units, 3) == (1, EVENT_MODIFIED)


def test_label_metrics_join_every_rule_version(tmp_path):
    import csv

    from avsd.lineage import prelabel as pre

    labels = tmp_path / "labels"
    labels.mkdir()
    rows = [("1-必标", 1, "kept", "dropped", "dropped"), ("1-必标", 2, "modified", "dropped", "dropped"),
            ("2-抽样", 3, "kept", "kept", "kept"), ("2-抽样", 4, "new", "new", "new")]
    with open(labels / pre.REVIEW_FILE, "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(pre.REVIEW_COLUMNS))
        wr.writeheader()
        for i, (pri, pair, rule, llm, human) in enumerate(rows):
            wr.writerow({c: "" for c in pre.REVIEW_COLUMNS} | {
                "review_priority": pri, "pair_id": pair, "rule_label": rule, "llm_label": llm,
                "human_label": human, "unit_key": f"number|{i}|"})
    for v, labs in (("v2", ["dropped", "modified", "kept", "new"]), ("v3", ["dropped", "dropped", "kept", "new"])):
        with open(labels / f"memory_pairs_rule_{v}.csv", "w", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(["pair_id", "unit_key", f"rule_label_{v}"])
            wr.writerows((pair, f"number|{i}|", lab) for i, ((_, pair, *_), lab) in enumerate(zip(rows, labs)))
    cfg = {"seed": 5, "paths": {"labels": str(labels), "outputs": str(tmp_path / "out")}}
    out = pre.compute_label_metrics(cfg, reps=50)
    get = {(r["scheme"], r["label"], r["metric"]): r for r in out}
    acc = get[("unweighted", "all", "accuracy")]
    assert (acc["rule"], acc["rule_v2"], acc["rule_v3"]) == pytest.approx((0.5, 0.75, 1.0))
    assert acc["v2_minus_v1"] == pytest.approx(0.25) and acc["v3_minus_v1"] == pytest.approx(0.5)
    w = get[("weighted", "all", "accuracy")]
    assert w["v3_minus_v1_lo"] <= w["v3_minus_v1"] <= w["v3_minus_v1_hi"]
    assert "rule_v3 joined from memory_pairs_rule_v3.csv: 4 of 4" in w["note"]
    with open(tmp_path / "out" / "tables" / pre.METRICS_FILE, encoding="utf-8") as f:
        header = next(csv.reader(f))
    assert header[:len(pre.METRIC_COLUMNS)] == list(pre.METRIC_COLUMNS)  # v1/v2 columns keep their positions
    assert header[len(pre.METRIC_COLUMNS):] == ["rule_v3", "rule_v3_lo", "rule_v3_hi", "v3_minus_v1",
                                                 "v3_minus_v1_lo", "v3_minus_v1_hi"]
    text = pre.format_metrics(out)
    assert "rule_v3" in text and "v3_minus_v1" in text
