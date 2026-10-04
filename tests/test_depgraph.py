"""Tests of the AI Village dependency graph, its structure statistics and the continuation rule
(SPEC 8.3 to 8.5, modules D2 to D4).

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import itertools
import math

import numpy as np
import polars as pl
import pytest

from avsd.swarmsim.continuation import _p_hit, continuation_pairs, summarize
from avsd.swarmsim.dag import BLOG, grow_dag, structure_stats
from avsd.swarmsim.depgraph import (
    build_edges, gini, graph_parts, layers_of, parent_lists, quantile_of, stats_from_parts,
    top_share,
)
from avsd.swarmsim.touches import (
    MENTION, OBSERVED, READ, RULES, WRITE, AgentState, SessionState, artifact_key,
    build_key_maps, is_navigation, local_container, parse_bash, session_touches, split_heredocs,
    split_segments,
)

DOC = "1AbCdEfGhIjKlMnOpQrStUvWxYz012345"


def touches(cmd: str, sess: SessionState | None = None, agent: AgentState | None = None, out=()):
    sess = sess or SessionState()
    return {(t.ref, t.mode, t.rule) for t in parse_bash(cmd, sess, agent or AgentState(), out)}


# --- shell parsing --------------------------------------------------------------------------------

def test_split_segments_respects_quotes_and_comments() -> None:
    segs = split_segments("cd ~/a && echo 'x; y' | tee b.txt # note\nls -la; git status")
    assert segs == ["cd ~/a", "echo 'x; y'", "tee b.txt", "ls -la", "git status"]


def test_split_heredocs() -> None:
    script, bodies = split_heredocs("cat > a.md << 'EOF'\nline https://x.org/p\nEOF\nls ~/b")
    assert script == "cat > a.md << 'EOF'\nls ~/b"
    assert bodies == [("cat > a.md << 'EOF'", "line https://x.org/p")]


def test_redirect_resolves_relative_target_against_cwd() -> None:
    sess = SessionState()
    got = touches("cd ~/proj && echo 'more text' >> ch12.txt", sess)
    assert ("path:~/proj", READ, "B-cd") in got
    assert ("path:~/proj/ch12.txt", WRITE, "B-redirect") in got
    assert sess.cwd == "~/proj"


def test_dev_null_is_not_a_target() -> None:
    assert touches("ls ~/a > /dev/null 2>&1") == {("path:~/a", READ, "B-other")}


def test_inplace_copy_move_and_remove() -> None:
    assert ("path:~/site/index.html", WRITE, "B-inplace") in touches("sed -i 's/a/b/' ~/site/index.html")
    got = touches("cp /tmp/a.json ~/dash/b.json")
    assert ("path:/tmp/a.json", READ, "B-fileop-src") in got
    assert ("path:~/dash/b.json", WRITE, "B-fileop") in got
    got = touches("mv ~/a/x.md ~/b/y.md")
    assert {("path:~/a/x.md", WRITE, "B-fileop"), ("path:~/b/y.md", WRITE, "B-fileop")} <= got
    assert ("path:~/old.txt", WRITE, "B-fileop") in touches("rm ~/old.txt")


def test_code_in_heredoc_writes_through_a_variable() -> None:
    cmd = "python3 << 'PY'\nOUT = '/tmp/site/index.html'\nwith open(OUT, 'w') as f:\n    f.write(x)\nPY"
    assert ("path:/tmp/site/index.html", WRITE, "B-code-write") in touches(cmd)
    cmd = "python3 - <<'PY'\nprint(open('/tmp/site/a.txt').read())\nPY"
    assert ("path:/tmp/site/a.txt", READ, "B-code-read") in touches(cmd)


def test_heredoc_file_content_and_echo_are_mentions() -> None:
    got = touches("cat > /tmp/b.md << 'EOF'\nsee https://example.org/page\nEOF")
    assert ("https://example.org/page", MENTION, "B-content") in got
    assert ("path:/tmp/b.md", WRITE, "B-redirect") in got
    assert touches("echo 'see https://x.org/y'") == {("https://x.org/y", MENTION, "B-content")}


def test_quoted_multiline_strings_are_not_commands() -> None:
    cmd = "python3 -c \"\nold = '<h3><a href=x.html>Title</a></h3>'\nprint(old)\n\" > /tmp/out.txt"
    got = touches(cmd)
    assert ("path:/tmp/out.txt", WRITE, "B-redirect") in got
    assert all(r.startswith("path:/tmp/out.txt") for r, mode, _ in got if mode == WRITE)
    assert touches("echo '>> not a target' >> ~/notes/a.txt") == {("path:~/notes/a.txt", WRITE, "B-redirect")}


def test_request_bodies_and_code_templates_are_mentions() -> None:
    got = touches("curl -s -X POST https://forum.example.net/api/posts -d '{\"text\": \"see https://x.org/page\"}'")
    assert ("https://forum.example.net/api/posts", WRITE, "B-http-write") in got
    assert ("https://x.org/page", MENTION, "B-content") in got
    assert ("https://x.org/page", WRITE, "B-http-write") not in got
    got = touches("gh api -X POST repos/o/r/issues/3/comments -f body='live at https://x.org/site'")
    assert ("github:o/r/issues/3", WRITE, "B-forge-write") in got
    assert ("https://x.org/site", MENTION, "B-content") in got
    code = ("python3 - <<'PY'\nimport urllib.request\nhtml = '<a href=\"https://x.org/linked\">x</a>'\n"
            "data = urllib.request.urlopen('https://x.org/feed').read()\n"
            "old = Path('/tmp/site/a.py').read_text()\nPath('/tmp/site/b.py').write_text(old)\nPY")
    got = touches(code)
    assert ("https://x.org/linked", MENTION, "B-content") in got
    assert ("https://x.org/feed", READ, "B-code-read") in got
    assert ("path:/tmp/site/a.py", READ, "B-code-read") in got
    assert ("path:/tmp/site/b.py", WRITE, "B-code-write") in got


def test_git_clone_map_then_push_and_pull() -> None:
    agent = AgentState()
    got = touches("git clone https://gitlab.com/ai-village-agents/proj.git /tmp/proj", agent=agent)
    assert ("gitlab:ai-village-agents/proj", READ, "B-git-remote-read") in got
    assert ("path:/tmp/proj", WRITE, "B-git-clone-dir") in got
    sess = SessionState()
    got = touches("cd /tmp/proj/sub && git add a.md && git commit -m 'msg' && git push", sess, agent)
    assert ("path:/tmp/proj/sub", WRITE, "B-git-local") in got
    assert ("gitlab:ai-village-agents/proj", WRITE, "B-git-push") in got
    got = touches("git -C /tmp/proj pull", agent=agent)
    assert ("gitlab:ai-village-agents/proj", READ, "B-git-remote-read") in got


def test_push_remote_from_output_when_directory_unknown() -> None:
    agent = AgentState()
    got = touches("cd ~/work/site && git push origin main", agent=agent, out=["github:o/site"])
    assert ("github:o/site", WRITE, "B-git-push") in got
    assert agent.remotes == {"~/work/site": "github:o/site"}


def test_http_and_forge_commands() -> None:
    got = touches("curl -s -X POST 'https://forum.example.net/api/posts' -d '{\"a\": 1}'")
    assert ("https://forum.example.net/api/posts", WRITE, "B-http-write") in got
    got = touches("curl -sS https://x.org/feed.xml -o /tmp/feed.xml")
    assert {("https://x.org/feed.xml", READ, "B-http-read"), ("path:/tmp/feed.xml", WRITE, "B-download")} <= got
    got = touches("gh issue create -R ai-village-agents/proj --title 'See https://a.org/b' --body x")
    assert ("github:ai-village-agents/proj", WRITE, "B-forge-write") in got
    assert ("https://a.org/b", MENTION, "B-content") in got
    assert ("https://a.org/b", WRITE, "B-forge-write") not in got
    got = touches("gh api repos/o/r/contents/docs/a.md -X PUT -f x=y")
    assert ("github:o/r/docs/a.md", WRITE, "B-forge-write") in got
    assert ("github:o/r", READ, "B-forge-read") in touches("gh pr list -R o/r")


def test_gui_focus_rules() -> None:
    turns = [
        {"action": "type", "text": f"https://docs.google.com/document/d/{DOC}/edit"},
        {"action": "key", "text": "Return"},
        {"action": "type", "text": "A new paragraph, see https://x.org/p"},
        {"action": "key", "text": "ctrl+s"},
        {"action": "get_pixel_coords_of_element", "description": "the blue Submit button"},
        {"action": "left_click"},
        {"action": "bash", "cmd": "ls ~/proj", "obs": ["path:~/proj/a.md"], "msg": ["https://x.org/q"]},
        {"action": "send_message_back_to_chat", "content": "Done https://x.org/r"},
    ]
    got, stats = session_touches(turns, AgentState())
    doc = f"gdoc:document:{DOC}"
    rules = [(i, t.rule, t.ref, t.mode) for i, t in got]
    assert (0, "G-nav", doc, READ) in rules
    assert (2, "G-type", doc, WRITE) in rules
    assert (2, "G-content", "https://x.org/p", MENTION) in rules
    assert (3, "G-key", doc, WRITE) in rules
    assert (5, "G-click", doc, WRITE) in rules
    assert (6, "O-output", "path:~/proj/a.md", OBSERVED) in rules
    assert (6, "M-message", "https://x.org/q", MENTION) in rules
    assert (7, "T-chat", "https://x.org/r", MENTION) in rules
    assert (stats["gui_writes"], stats["gui_writes_unattributed"]) == (3, 0)
    _, stats = session_touches([{"action": "type", "text": "hello there"}], AgentState())
    assert (stats["gui_writes"], stats["gui_writes_unattributed"]) == (1, 1)


def test_navigation_detection() -> None:
    assert is_navigation("https://example.org/a?b=1")
    assert is_navigation("thecolony.cc/post/3")
    assert not is_navigation("Hello world")
    assert not is_navigation("https://a.org\nmore")


def test_every_rule_has_a_mode() -> None:
    assert all(mode in (WRITE, READ, OBSERVED, MENTION) for mode, _ in RULES.values())


# --- artifact keys ----------------------------------------------------------------------------------

def test_artifact_keys() -> None:
    maps = build_key_maps([("123", "gitlab:grp/proj")] * 2, ["gitlab:grp/compass"])
    assert artifact_key(f"gdoc:document:{DOC}", "A", maps)[0] == artifact_key(f"gdoc:file:{DOC}", "B", maps)[0]
    assert artifact_key("github:o/r/docs/a.md", "A", maps) == ("github:o/r/docs/a.md", "github:o/r", "github")
    assert artifact_key("github:o", "A", maps) is None
    assert artifact_key("gitlab-pid:123/a.md", "A", maps) == ("gitlab:grp/proj/a.md", "gitlab:grp/proj", "gitlab")
    assert artifact_key("gitlab-pid:999", "A", maps) == ("gitlab-pid:999", "gitlab-pid:999", "gitlab")
    assert artifact_key("path:~/proj/a/b.md", "A", maps) == ("local:A:~/proj/a/b.md", "local:A:~/proj", "local")
    assert artifact_key("path:~/proj/a/b.md", "B", maps)[0] != artifact_key("path:~/proj/a/b.md", "A", maps)[0]
    assert artifact_key("path:~/.config/x", "A", maps) is None
    assert artifact_key("https://o.github.io/site/p.html", "A", maps)[0] == "github:o/site"
    assert artifact_key("https://compass-409cf0.gitlab.io/a", "A", maps)[0] == "gitlab:grp/compass"
    assert artifact_key("https://x.org/post/12?utm=1#c", "A", maps)[0] == "url:x.org/post/12"
    assert artifact_key("https://x.org", "A", maps) is None
    assert artifact_key("https://www.google.com/search", "A", maps) is None
    assert artifact_key("http://localhost:8000/a", "A", maps) == (
        "local:A:localhost:8000/a", "local:A:localhost:8000", "local")
    assert artifact_key("https://mail.google.com/mail/u/0", "A", maps)[0].startswith("local:A:")


def test_local_container() -> None:
    assert local_container("~/proj/a/b.md") == "~/proj"
    assert local_container("~/notes.md") == "~/notes.md"
    assert local_container("/tmp/site/x/y") == "/tmp/site"
    assert local_container("/tmp/build/x/y") == "/tmp/build/x"
    assert local_container("~/work/site/index.html") == "~/work/site"
    assert local_container("~/a/b/c.md", frozenset({"~/a/b"})) == "~/a/b"


def test_gitlab_id_map_needs_a_clear_majority() -> None:
    m = build_key_maps([("1", "gitlab:a/x"), ("1", "gitlab:a/x"), ("1", "gitlab:a/y"), ("2", "gitlab:a/z")], [])
    assert m.gitlab_pid == {"1": "a/x"}
    m = build_key_maps([], ["gitlab:a/x", "gitlab:b/x", "gitlab:a/w"])
    assert m.pages_project == {"w": "gitlab:a/w"}


# --- edges ------------------------------------------------------------------------------------------

def _touch(rows: list[tuple]) -> pl.DataFrame:
    """rows: (s, k, c, first_t, write_ts, clevel)."""
    return pl.DataFrame({
        "s": [r[0] for r in rows], "k": [r[1] for r in rows], "c": [r[2] for r in rows],
        "first_t": [float(r[3]) for r in rows], "wrote": [bool(r[4]) for r in rows],
        "write_ts": [[float(x) for x in r[4]] for r in rows], "clevel": [r[5] for r in rows],
        "kind": ["gdoc"] * len(rows), "rule": ["x"] * len(rows)},
        schema_overrides={"write_ts": pl.List(pl.Float64)})


def test_last_writer_edges_and_labels() -> None:
    t = _touch([
        (0, 1, 1, 1, [1, 2], False),     # session 0 writes key 1
        (1, 1, 1, 3, [], False),         # session 1 reads key 1 -> 0 -> 1 read
        (2, 1, 1, 4, [4], False),        # session 2 writes key 1 -> 0 -> 2 write
        (3, 1, 1, 5, [], False),         # session 3 reads -> last writer 2
        (2, 2, 2, 6, [6], False),
        (3, 2, 2, 7, [], False),         # second key gives the same pair 2 -> 3
    ])
    e = build_edges(t, np.arange(4)).edges.sort("parent", "child")
    assert e.select("parent", "child", "label", "n_keys").rows() == [
        (0, 1, "read", 1), (0, 2, "write", 1), (2, 3, "read", 2)]


def test_own_writes_are_skipped_and_order_is_enforced() -> None:
    t = _touch([
        (0, 1, 1, 1, [1], False),
        (1, 1, 1, 2, [2], False),        # 1 writes after 0; its own write never makes it its parent
        (1, 2, 2, 3, [3], False),
        (2, 1, 1, 4, [], False),         # last writer of key 1 is 1
    ])
    e = build_edges(t, np.arange(3)).edges.sort("parent", "child")
    assert e.select("parent", "child").rows() == [(0, 1), (1, 2)]
    # session 1 started before session 0 in start order: the 0 -> 1 edge is dropped
    b = build_edges(t, np.array([1, 0, 2]))
    assert b.dropped_order == 1
    assert (0, 1) not in b.edges.select("parent", "child").rows()


def test_container_matching() -> None:
    t = _touch([
        (0, 10, 1, 1, [1], False),       # write to a path inside container 1
        (1, 11, 1, 2, [], False),        # another path in the container: no shared key, no edge
        (2, 1, 1, 3, [], True),          # container-level read sees any write inside it
        (3, 1, 1, 4, [4], True),         # container-level write (e.g. a push)
        (4, 11, 1, 5, [], False),        # path-level read sees the container-level write
    ])
    e = build_edges(t, np.arange(5)).edges.sort("parent", "child")
    assert e.select("parent", "child").rows() == [(0, 2), (0, 3), (3, 4)]
    exact = build_edges(t, np.arange(5), hierarchical=False).edges
    assert exact.select("parent", "child").rows() == []


# --- layers and statistics ---------------------------------------------------------------------------

def test_layers_one_below_deepest_parent() -> None:
    ps = parent_lists(5, [(0, 1), (1, 2), (0, 3), (2, 3), (3, 4)])
    assert layers_of(ps).tolist() == [0, 1, 2, 3, 4]
    assert layers_of([[], [], [0, 1]]).tolist() == [0, 0, 1]


def test_stats_agree_with_d1_on_generated_dags() -> None:
    for seed, n in ((1, 723), (2, 150)):
        dag = grow_dag(n, 17, BLOG.peak, BLOG.merge_p, np.random.default_rng(seed))
        ours = stats_from_parts([graph_parts(dag.parents)])
        d1 = structure_stats(dag)
        for k in ("cross_layer_share", "multi_parent_share", "mean_parents", "sibling_merge_share",
                  "outdeg_gini", "top10_child_share"):
            assert ours[k] == pytest.approx(d1[k], abs=1e-12), k
        assert ours["root_share"] == pytest.approx(1 / n)


def test_hand_built_statistics() -> None:
    # 0 -> 1, 0 -> 2, (1, 2) -> 3: one merge of two siblings; 0 -> 3 would skip a layer
    ps = parent_lists(4, [(0, 1), (0, 2), (1, 3), (2, 3), (0, 3)])
    s = stats_from_parts([graph_parts(ps)])
    assert s["multi_parent_share"] == pytest.approx(1 / 3)
    assert s["mean_parents"] == pytest.approx(5 / 3)
    assert s["sibling_merge_share"] == 1.0
    assert s["cross_layer_share"] == pytest.approx(1 / 5)
    assert s["parents_1"] == pytest.approx(2 / 3) and s["parents_3"] == pytest.approx(1 / 3)
    pooled = stats_from_parts([graph_parts(ps), graph_parts([[], [0]])])
    assert pooled["n_nodes"] == 6 and pooled["n_edges"] == 6
    assert pooled["mean_parents"] == pytest.approx(6 / 4)


def test_gini_top_share_and_quantile() -> None:
    assert gini(np.array([1, 1, 1, 1])) == pytest.approx(0.0)
    assert gini(np.array([0, 0, 0, 4])) == pytest.approx(0.75)
    assert top_share(np.array([5] + [1] * 9)) == pytest.approx(5 / 14)
    g = np.array([0.1, 0.2, 0.3, 0.4])
    assert quantile_of(0.25, g) == 0.5
    assert quantile_of(0.2, g) == pytest.approx(0.375)
    assert quantile_of(1.0, g) == 1.0
    assert math.isnan(quantile_of(math.nan, g))


# --- continuation ------------------------------------------------------------------------------------

def test_hypergeometric_hit_probability() -> None:
    W, m, k = 7, 2, 3
    items = range(W)
    combos = list(itertools.combinations(items, k))
    brute = sum(any(i < m for i in c) for c in combos) / len(combos)
    assert _p_hit(W, m, k) == pytest.approx(brute)
    assert _p_hit(5, 0, 2) == 0.0 and _p_hit(5, 4, 2) == 1.0 and _p_hit(5, 1, 0) == 0.0


def test_continuation_pairs_and_baseline() -> None:
    # agent A: sessions 0, 2; agent B: 1. Session 0 writes containers 10 and 11, B writes 12.
    ses = pl.DataFrame({"s": [0, 1, 2], "agent_id": ["A", "B", "A"], "start_t": [0.0, 1.0, 5.0],
                        "goal_id": ["g"] * 3, "run_day": [1] * 3, "regime_cu": ["post"] * 3})
    writes = pl.DataFrame({"s": [0, 0, 1], "c": [10, 11, 12], "t": [0.5, 0.6, 2.0],
                           "local": [True, False, False]})
    found = pl.DataFrame({"child": [2], "c": [10], "parent": [0]})
    pairs = continuation_pairs(ses, writes, found)
    r = pairs.row(0, named=True)
    assert (r["child"], r["prev"], r["cont"], r["k"], r["k_own"]) == (2, 0, 1, 1, 1)
    # pool: shared {11, 12} plus A's local {10}; A's previous session last wrote 10 and 11
    assert (r["W_goal"], r["m_goal"], r["Wown_goal"]) == (3, 2, 2)
    assert r["e_goal"] == pytest.approx(2 / 3)
    assert r["eown_goal"] == pytest.approx(1.0)
    rows = summarize(pairs, "all", np.random.default_rng(0), B=50)
    main = next(x for x in rows if x["window"] == "goal" and x["measure"] == "with_parents"
                and x["stratum"] == "all")
    assert main["rate"] == 1.0 and main["baseline"] == pytest.approx(2 / 3) and main["n_pairs"] == 1


# --- figure ----------------------------------------------------------------------------------------

def test_f7_figure(tmp_path) -> None:
    from avsd.swarmsim.depgraph import STAT_NAMES
    from avsd.swarmsim.figure_f7 import plot_f7

    rng = np.random.default_rng(0)
    gen = {st: rng.normal(0.4, 0.02, 64) for st in STAT_NAMES}
    obs = {"all": {st: 0.1 for st in STAT_NAMES}, "write": {st: 0.2 for st in STAT_NAMES}}
    paths = plot_f7(gen, obs, list(STAT_NAMES), tmp_path / "F7", 51, 64)
    assert all(p.exists() and p.stat().st_size > 0 for p in paths)


# --- GUI rules v2 and the focus-gap diagnosis ----------------------------------------------------------

def test_classify_typed() -> None:
    from avsd.swarmsim.touches import classify_typed

    assert classify_typed("cd ~/proj && git status\n") == "shell"
    assert classify_typed("python3 app.py") == "shell"
    assert classify_typed("localhost:8000/index.html") == "url"
    assert classify_typed("best pizza near me", addr_bar=True) == "search"
    assert classify_typed("climate report", search_box=True) == "search"
    assert classify_typed("n") == "short_input"
    assert classify_typed("[REDACTED]") == "credential"
    assert classify_typed("secret-value", credential_box=True) == "credential"
    assert classify_typed("Thanks for the update! I will review the draft tomorrow.") == "prose"
    assert classify_typed("def f(x):\n    return x + 1\n") == "code"
    assert classify_typed("Jane Smith") == "form_field"
    assert classify_typed("index.html") == "form_field"


def _gui_session(*turns: tuple, t0: float = 0.0) -> list[dict]:
    out = []
    for k, (action, text, extra) in enumerate(turns):
        out.append({"action": action, "text": text, "ts": t0 + 30 * k, **(extra or {})})
    return out


def test_rules_v2_reclassify_and_shell() -> None:
    from avsd.swarmsim.touches import RULE_SETS

    s = _gui_session(("type", "cd ~/site && echo hi >> notes.md\n", None), ("key", "ctrl+l", None),
                     ("type", "weather in paris", None), ("type", "n", None))
    got1, st1 = session_touches(s, AgentState(), "v1")
    assert (st1["gui_writes"], st1["gui_writes_unattributed"]) == (3, 3)
    got2, st2 = session_touches(s, AgentState(), RULE_SETS["v2"])
    assert st2["gui_writes"] == 0 and (st2["gui_shell"], st2["gui_search"], st2["gui_input"]) == (1, 1, 1)
    shell = {(t.ref, t.mode, t.rule, t.via) for _, t in got2 if t.via == "gui-shell"}
    assert ("path:~/site/notes.md", WRITE, "B-redirect", "gui-shell") in shell


def test_rules_v2_search_clears_focus_and_carry_over() -> None:
    from avsd.swarmsim.touches import GuiRules

    rules = GuiRules("t", reclassify=True, shell_as_bash=True, search_clears_focus=True, carry_gap_min=60)
    doc = f"https://docs.google.com/document/d/{DOC}/edit"
    agent = AgentState()
    s1 = _gui_session(("type", doc, None), ("type", "A first paragraph of the shared report.", None), t0=0)
    got, st = session_touches(s1, agent, rules)
    assert st["gui_writes_unattributed"] == 0 and agent.last_focus is not None
    s2 = _gui_session(("type", "A second paragraph, written in the next session.", None), t0=1200)
    got, st = session_touches(s2, agent, rules)
    assert [(t.rule, t.via) for _, t in got if t.mode == WRITE] == [("G-type", "carry")]
    s3 = _gui_session(("key", "ctrl+l", None), ("type", "weather in paris", None),
                      ("type", "Typed after the search, target unknown.", None), t0=2400)
    got, st = session_touches(s3, agent, rules)
    assert st["gui_writes_unattributed"] == 1 and st["gui_search"] == 1
    late = _gui_session(("type", "Much later, the carried focus has expired.", None), t0=2400 + 3 * 3600)
    _, st = session_touches(late, AgentState(last_focus=doc, last_focus_ts=0.0), rules)
    assert st["gui_writes_unattributed"] == 1


def test_rules_v2_narrative_focus() -> None:
    from avsd.swarmsim.touches import GuiRules

    rules = GuiRules("t", reclassify=True, narrative_window=2)
    s = _gui_session(("screenshot", None, {"msg": [f"gdoc:document:{DOC}"]}),
                     ("type", "Adding the paragraph the agent just named.", None))
    got, st = session_touches(s, AgentState(), rules)
    assert [(t.ref, t.via) for _, t in got if t.mode == WRITE] == [(f"gdoc:document:{DOC}", "narrative")]


def test_gui_gap_walk_and_evaluate() -> None:
    from avsd.swarmsim.gui_gap import evaluate, walk_agent

    doc = f"https://docs.google.com/document/d/{DOC}/edit"
    s1 = [{"id": "a", "session_id": "s1", "action": "type", "text": doc, "ts": 0.0},
          {"id": "b", "session_id": "s1", "action": "type", "text": "First paragraph of the report text.", "ts": 30.0}]
    s2 = [{"id": "c", "session_id": "s2", "action": "type", "text": "Second paragraph, no navigation here.",
           "ts": 600.0, "msg": [f"gdoc:document:{DOC}"]},
          {"id": "d", "session_id": "s2", "action": "key", "text": "ctrl+l", "ts": 630.0},
          {"id": "e", "session_id": "s2", "action": "type", "text": "weather in paris", "ts": 660.0}]
    s3 = [{"id": "f", "session_id": "s3", "action": "type", "text": doc, "ts": 1200.0},
          {"id": "g", "session_id": "s3", "action": "type", "text": "Third paragraph after navigating again.",
           "ts": 1230.0}]
    w = walk_agent("A", [s1, s2, s3])
    assert [(r["turn_id"], r["text_class"], r["focus_v1"] is not None) for r in w] == [
        ("b", "prose", True), ("c", "prose", False), ("e", "search", False), ("g", "prose", True)]
    assert w[1]["carry_ref"] is not None and w[1]["near_refs"] == [f"gdoc:document:{DOC}"]
    ev = {r["heuristic"]: r for r in evaluate(w).iter_rows(named=True)}
    assert ev["carry"]["known_predicted"] == 1 and ev["carry"]["accuracy_key"] == 1.0
    assert ev["narr_near"]["coverage"] == 1.0


# --- main rule version and robustness subsets -------------------------------------------------------------

def test_main_rules_and_file_names(tmp_path) -> None:
    from avsd.swarmsim.calibrate import CalibConfig
    from avsd.swarmsim.depgraph_data import paths
    from avsd.swarmsim.touches import MAIN_RULES

    assert MAIN_RULES == "v2" and CalibConfig().rules == "v2"
    assert CalibConfig.from_cfg({"swarmsim_calibrate": {"rules": "v1"}}).rules == "v1"
    cfg = {"paths": {"interim": tmp_path}}
    assert paths(cfg)["touches"].name == "touches.parquet"
    assert paths(cfg, "v1")["touches"].name == "touches_v1.parquet"


def test_goal_subsets() -> None:
    from datetime import date

    from avsd.swarmsim.robustness import goal_subsets

    cov = pl.DataFrame({"goal_id": ["a", "e", "b", "c", "d"],
                        "start": [date(2025, 5, 1), date(2025, 6, 1), date(2025, 8, 1), date(2025, 11, 1),
                                  date(2026, 3, 1)],
                        "gap": [0.9, 0.75, 0.15, 0.05, 0.85], "touch_share": [0.2, 0.3, 0.5, 0.9, 0.85]})
    s = goal_subsets(cov)
    assert s["full"][1] == ["a", "e", "b", "c", "d"]
    assert s["gap < 20%"][1] == ["b", "c"] and s["gap < 10%"][1] == ["c"]
    assert s["touch share >= 80%"][1] == ["c", "d"]
    assert s["from 2025-10"][1] == ["c", "d"]
    assert s["no GUI-heavy early goals"][1] == ["e", "b", "c", "d"]    # only early goals at 80%+ go


def test_conclusion_checks() -> None:
    from avsd.swarmsim.robustness import CONCLUSIONS, conclusion_checks

    rows = []
    for st, q in (("mean_parents", 1.0), ("multi_parent_share", 1.0), ("cross_layer_share", 1.0),
                  ("outdeg_gini", 0.0), ("top10_child_share", 0.4)):
        rows.append({"subset": "full", "analysis": "D3", "edges": "all", "statistic": st, "window": "",
                     "value": 0.5, "quantile": q})
    for c in ("turns", "active_min"):
        rows.append({"subset": "full", "analysis": "step cost", "edges": "all", "statistic": f"slope of {c}",
                     "window": "", "value": 0.1, "ci_low": -0.1, "ci_high": 0.3})
    for w, b in (("goal", 0.06), ("day", 0.25)):
        rows.append({"subset": "full", "analysis": "D4", "edges": "all", "statistic": "with_parents", "window": w,
                     "value": 0.6, "ci_low": 0.53, "ci_high": 0.67, "baseline": b, "baseline_ci_low": b - 0.02,
                     "baseline_ci_high": b + 0.03, "n": 100, "n_agents": 10})
    ch = conclusion_checks(pl.DataFrame(rows, infer_schema_length=None))
    holds = dict(zip(ch["conclusion"].to_list(), ch["holds"].to_list(), strict=True))
    assert holds[CONCLUSIONS[0]] and holds[CONCLUSIONS[1]] and holds[CONCLUSIONS[3]] and holds[CONCLUSIONS[4]]
    assert not holds[CONCLUSIONS[2]]          # top-10% share inside the generator range
