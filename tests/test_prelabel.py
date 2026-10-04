"""Tests for the B1 pre-labelling helpers (SPEC 6.3.4): no GPU and no model needed.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

import csv
import json
from collections import Counter

import pytest

from avsd.lineage import memory as b1_memory
from avsd.lineage import prelabel as pre
from avsd.lineage.anchors import QUANTITY_TYPES, TYPES, AnchorExtractor, display_value, keyed_hash
from avsd.lineage.chains import KIND_FULL
from avsd.lineage.memory import segment_lines

SALT = bytes(range(32))
NAMES = ["Claude Opus 4.5", "GPT-5.1", "Gemini 2.5 Pro", "o3"]


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


MEMORY = (
    "# Fundraiser notes\n"
    "PREVIOUS (NOW ENDED) SESSION (Day 12): raised $1,234.50 from 56 donors by 2026-04-01.\n"
    "- Talked to GPT-5.1 at 3:30 PM about https://example.org/page?utm_source=x&id=5\n"
    "\n"
    "## Credentials\n"
    "- Mail: someone@example.com, code 4821\n"
    "## Plans\n"
    "Next goal: 120 donors and 15% more views on Day 14.\n"
)


def _b1_set(ex, text):
    """(type, stored value, lemma) of every anchor, as B1 extracts them line by line."""
    _, items = segment_lines(text, KIND_FULL, 0)
    res = ex.extract([t for _, t, _ in items], [s for _, _, s in items])
    return {(TYPES[t], v, c.removeprefix("^")) for an in res for t, v, c in an}


# --- recovery of B1 anchors with spans -------------------------------------------------------------

def test_quantity_types_match_b1():
    assert pre.QUANTITY == QUANTITY_TYPES


def test_text_occurrences_reproduce_b1_regex(rx):
    d = pre.text_occurrences(rx, MEMORY)
    assert {(o.type, o.stored, o.lemma) for o in d.occs} == _b1_set(rx, MEMORY)
    assert "PREVIOUS (NOW ENDED)" not in d.text and len(d.text.split("\n")) == len(MEMORY.split("\n"))
    money = [o for o in d.occs if o.type == "money"]
    assert [d.text[o.start:o.end] for o in money] == ["$1,234.50"] and money[0].raw == "USD:1234.5"
    # Values under a credential heading are hashed, as in B1; the span still points at the text.
    code = [o for o in d.occs if d.text[o.start:o.end] == "4821"]
    assert code and code[0].stored.startswith("h:") and code[0].raw == "4821"
    assert d.line_sens[MEMORY.split("\n").index("- Mail: someone@example.com, code 4821")]


def test_text_occurrences_reproduce_b1_with_spacy(nlp_ex):
    text = MEMORY + "Doctors Without Borders thanked Alice Smith for the 56 donors in Boston.\n"
    d = pre.text_occurrences(nlp_ex, text)
    assert {(o.type, o.stored, o.lemma) for o in d.occs} == _b1_set(nlp_ex, text)
    donors = [o for o in d.occs if o.type == "number" and d.text[o.start:o.end] == "56"]
    assert donors and any(o.lemma == "donor" for o in donors)


def test_long_lines_are_split_like_b1(rx):
    line = ("word " * 1500) + "$75 at 9 am " + ("filler " * 900)
    d = pre.text_occurrences(rx, line)
    assert {(o.type, o.stored, o.lemma) for o in d.occs} == _b1_set(rx, line)
    assert {d.text[o.start:o.end] for o in d.occs} >= {"$75", "9 am"}


def test_parse_unit_key_and_matcher():
    assert pre.parse_unit_key("work_of_art|a | b|story") == ("work_of_art", "a | b", "story")
    assert pre.parse_unit_key("number|56|") == ("number", "56", "")
    occ = pre.Occ(0, 2, "number", "56", "56", "donor")
    other_ctx = pre.Occ(5, 7, "number", "56", "56", "day")
    for key in ("number|56|donor", f"number|56|{keyed_hash(SALT, 'ctx', 'donor', 8)}"):
        um = pre.UnitMatcher(key, SALT)
        assert um.is_unit(occ) and not um.is_unit(other_ctx)
    doc = pre.DocInfo("56 x 56", [occ, other_ctx], [False])
    um = pre.UnitMatcher(f"number|56|{keyed_hash(SALT, 'ctx', 'donor', 8)}", SALT)
    assert um.recover_ctx([doc]) == "donor"
    # Non-quantities are identified by value alone; hashed and URL values match via display_value.
    org = pre.Occ(0, 9, "org", "red cross", "red cross", "partner")
    assert pre.UnitMatcher("org|red cross|sponsor", SALT).is_unit(org)
    email_hash = keyed_hash(SALT, "email", "a@b.org")
    em = pre.Occ(0, 7, "email", "a@b.org", email_hash, "")
    assert pre.UnitMatcher(f"email|{email_hash}|", SALT).is_unit(em)
    url = "https://example.org/page?id=5"
    u = pre.Occ(0, 10, "url", url, url, "")
    assert pre.UnitMatcher(f"url|{display_value('url', url, SALT)}|", SALT).is_unit(u)
    assert not pre.UnitMatcher("url|example.org#00000000|", SALT).is_unit(u)


# --- excerpts ---------------------------------------------------------------------------------------

def test_excerpt_windows_merge_and_limit():
    text = "".join(chr(97 + (i * 7919) % 26) if i % 5 else " " for i in range(10_000))  # varied words
    pos = [101, 181, 3001, 6001, 9001]
    for p in pos:
        text = text[:p] + "7" + text[p + 1:]
    marks = [pre.Mark(p, p + 1, "value") for p in pos]
    wins, left = pre.excerpt_windows(text, [marks], [])
    assert len(wins) == 3 and left == 1  # the two near seeds share one window; one seed did not fit
    assert wins[0].count("⟦7⟧") == 2 and all(len(w) <= pre.MAX_MERGED_CHARS + 20 for w in wins)
    # Seeds of a lower tier only get the windows that are left.
    ctx = [pre.Mark(5001, 5002, "ctx")]
    wins, left = pre.excerpt_windows(text, [marks[:2], ctx], [])
    assert len(wins) == 2 and "⟨" in wins[1] and left == 0


def test_render_window_markers_masks_and_breaks():
    text = "We had 56 donors.\nNow 60 donors; password: hunter2xyz end"
    masks = pre.credential_spans(text)
    marks = [pre.Mark(7, 9, "value"), pre.Mark(22, 24, "ctx")]
    s = pre.render_window(text, 0, len(text), marks, masks)
    assert s == "We had ⟦56⟧ donors. ↵ Now ⟨60⟩ donors; password: «masked» end"
    # A cut window shows ellipses; a value inside a credential is masked inside its marker.
    t2 = "x " * 50 + "PIN: 4821 " + "y " * 50
    m = [pre.Mark(t2.index("4821"), t2.index("4821") + 4, "value")]
    s2 = pre.render_window(t2, 60, 130, m, pre.credential_spans(t2))
    assert s2.startswith("…") and s2.endswith("…") and "⟦«masked»⟧" in s2 and "4821" not in s2


def test_version_evidence_tiers():
    um = pre.UnitMatcher("number|56|donor", SALT)
    prev_text = "Intro. We have 56 donors so far. " + "filler " * 80 + "Again 56 donors."
    p56 = [i for i in range(len(prev_text)) if prev_text.startswith("56", i)]
    prev = pre.DocInfo(prev_text, [pre.Occ(i, i + 2, "number", "56", "56", "donor") for i in p56], [False])
    ev = pre.version_evidence(prev, um, ["donor"], [])
    assert ev.n_unit == 2 and len(ev.windows) == 2 and all("⟦56⟧ donors" in w for w in ev.windows)
    # NEXT: the context now holds 60 -> shown as the other value (evidence for "modified").
    nxt_text = "Intro. We have 60 donors so far."
    i60 = nxt_text.index("60")
    nxt = pre.DocInfo(nxt_text, [pre.Occ(i60, i60 + 2, "number", "60", "60", "donor")], [False])
    ev = pre.version_evidence(nxt, um, ["donor"], ["56"])
    assert ev.n_unit == 0 and ev.n_literal == 0 and ev.n_ctx == 1
    assert ev.windows == ["Intro. We have ⟨60⟩ donors so far."]
    # The rules missed it, but the text still says it: literal match next to the context word.
    lit = pre.DocInfo("Still 56 donors here, and 56 days left.", [], [False])
    ev = pre.version_evidence(lit, um, ["donor"], ["56"])
    assert ev.n_literal == 1 and "⟦56⟧ donors" in ev.windows[0] and "⟦56⟧ days" not in ev.windows[0]
    # Nothing but the context word.
    word = pre.DocInfo("Donors: see the spreadsheet.", [], [False])
    ev = pre.version_evidence(word, um, ["donor"], ["56"])
    assert ev.n_ctxword == 1 and ev.windows == ["Donors: see the spreadsheet."]
    # Nothing at all.
    ev = pre.version_evidence(pre.DocInfo("Unrelated text.", [], [False]), um, ["donor"], ["56"])
    assert ev.windows == [] and pre.join_windows(ev.windows, ev.left) == ""


def test_join_windows_counts_hidden_matches():
    assert pre.join_windows(["a", "b"], 0) == "[1] a [2] b"
    assert pre.join_windows(["a"], 4) == "[1] a (+4 more matches)"


# --- masking -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,secret", [
    ("password: hunter2xyz", "hunter2xyz"),
    ("Gmail pwd = Village2025!", "Village2025!"),
    ("my password is Tr0ub4dor&3 now", "Tr0ub4dor&3"),
    ("PIN: 4821", "4821"),
    ("OTP 123456 expires soon", "123456"),
    ("api_key=sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123", "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123"),
    ("token ghp_abcdefghijklmnopqrstuvwxyz0123456789 works", "ghp_abcdefghijklmnopqrstuvwxyz0123456789"),
    ("deploy nfp_abcdefghijklmnopqrstuvwxyz0123456789", "nfp_abcdefghijklmnopqrstuvwxyz0123456789"),
    ("clone https://bob:s3cretPass@git.example.com/x.git", "s3cretPass"),
    ("Authorization: Bearer abcdefghijklmnop1234", "abcdefghijklmnop1234"),
    ("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N", "eyJhbGciOiJIUzI1NiJ9"),
    ("see https://x.org/cb?token=abcdef123456&page=2", "abcdef123456"),
])
def test_mask_text_hides_credentials(text, secret):
    masked = pre.mask_text(text)
    assert secret not in masked and pre.MASK in masked


@pytest.mark.parametrize("text", [
    "We raised $1,200 from 56 donors on 2026-03-05 at 15:30.",
    "Token count: 5000 tokens per call with GPT-5.1.",
    "The password reset page is at https://example.org/reset.",
    "Password: required",
    "Contact someone@example.com about the API key rotation.",
])
def test_mask_text_keeps_ordinary_text(text):
    assert pre.mask_text(text) == text


def test_sensitive_lines_mask_secret_like_tokens():
    text = "## Accounts\n- Mail: someone@example.com / Village2025xy\n## Plans\n- Village2025xy launch"
    flags = [True, True, False, False]  # B1's heading rule
    masked = pre.mask_text(text, flags)
    lines = masked.split("\n")
    assert "Village2025xy" not in lines[1] and "someone@example.com" in lines[1]
    assert lines[3] == "- Village2025xy launch"


def test_masked_value_flag(rx):
    text = "## Credentials\n- Bank PIN: 4821\n## Notes\n- 77 visitors"
    d = pre.text_occurrences(rx, text)
    pin = [o for o in d.occs if d.text[o.start:o.end] == "4821" and o.start < text.index("## Notes")]
    um = pre.UnitMatcher(f"number|{pin[0].stored}|", SALT)
    ev = pre.version_evidence(d, um, [], [])
    assert ev.masked_value and "4821" not in " ".join(ev.windows)


# --- prompts, cache keys and model output ----------------------------------------------------------

def _norm(s):
    return " ".join(s.split())


def test_definitions_are_quoted_from_memory_docstring():
    doc = _norm(b1_memory.__doc__)
    for line in pre.DEFINITIONS.split("\n")[:2]:
        body = _norm(line.removeprefix("- "))
        assert body.removeprefix("State: ").rstrip(".") in doc


def test_messages_and_cache_key():
    msgs = pre.build_messages("number", "56", "donor", (["We have ⟦56⟧ donors."], 1, 0), ([], 0, 0), None)
    user = msgs[1]["content"]
    assert msgs[0]["role"] == "system" and "kept (in the output)" in user
    assert "- value: 56" in user and "part of this unit's identity" in user
    assert "PREV (the input): the unit's value occurs 1 time in PREV (marked ⟦ ⟧);" in user
    assert "NEXT (the output): the unit's value does NOT occur in NEXT;" in user and "(no excerpt" in user
    assert "EARLIER" not in user.split("Unit:")[1] and "rule_label" not in user
    assert user.rstrip().endswith('and why>"}') and "Decide in three steps" in user
    msgs_e = pre.build_messages("org", "Red Cross", "partner", (["x"], 0, 1), (["y"], 1, 0),
                                (["⟦Red Cross⟧ helped"], "2026-01-02, 3 rewrites between it and NEXT"))
    tail = msgs_e[1]["content"].split("Unit:")[1]
    assert tail.index("EARLIER (an older version") < tail.index("PREV (the input)") < tail.index("NEXT (")
    k1, k2 = pre.request_key(msgs, 1), pre.request_key(msgs, 1)
    assert k1 == k2 and len(k1) == 64
    assert pre.request_key(msgs, 2) != k1 and pre.request_key(msgs_e, 1) != k1


@pytest.mark.parametrize("raw,label,conf,valid,error", [
    ('{"label": "kept", "confidence": "high", "rationale": "Same value in both."}', "kept", "high", True, ""),
    ('```json\n{"label": "Modified", "confidence": "Medium", "rationale": "56 became 60."}\n```',
     "modified", "medium", True, ""),
    ('Answer: {"label": "dropped", "confidence": "low", "rationale": "gone"} done', "dropped", "low", True, ""),
    ('<think>\n\n</think>\n{"label": "new", "confidence": "high", "rationale": "x"}', "new", "high", True, ""),
    ('{"label": "kept", "confidence": "sure", "rationale": "x"}', "kept", "", True, "bad_confidence"),
    ('{"label": "lost", "confidence": "high", "rationale": "x"}', "", "high", False, "bad_label"),
    ('{"confidence": "high"}', "", "high", False, "bad_label"),
    ('not json at all', "", "", False, "not_json"),
    ('{"label": "kept", "confidence": "high", "rationale": "unterminated', "", "", False, "not_json"),
    ("", "", "", False, "empty"),
])
def test_parse_model_output(raw, label, conf, valid, error):
    r = pre.parse_model_output(raw)
    assert (r["label"], r["confidence"], r["valid"], r["error"]) == (label, conf, valid, error)


def test_parse_model_output_truncates_rationale():
    words = " ".join(f"w{i}" for i in range(40))
    r = pre.parse_model_output(json.dumps({"label": "kept", "confidence": "low", "rationale": words}))
    assert r["truncated"] and r["rationale"].endswith("…") and len(r["rationale"].split()) == 25


# --- re-check models: cache keys, answers, retries ----------------------------------------------

def test_model_request_key_keeps_the_qwen14b_cache():
    msgs = [{"role": "user", "content": "unit"}]
    assert pre.model_request_key(pre.QWEN3_14B, msgs, 1) == pre.request_key(msgs, 1)
    assert pre.model_sampling(pre.QWEN3_14B, 1) == pre.sampling_params(1)
    k35 = pre.model_request_key(pre.QWEN35_122B, msgs, 1)
    assert k35 != pre.request_key(msgs, 1) and k35 != pre.model_request_key(pre.GPT_OSS_120B, msgs, 1)
    assert pre.model_request_key(pre.QWEN35_122B, msgs, 1, attempt=1) != k35
    s1 = pre.model_sampling(pre.QWEN35_122B, 1, attempt=1)
    assert s1["seed"] == 2 and s1["max_tokens"] == pre.QWEN35_122B.budgets[1] and s1["top_k"] == 20
    assert pre.cache_file(pre.QWEN3_14B) == "cache.jsonl"
    assert pre.cache_file(pre.GPT_OSS_120B) == "cache_gptoss_120b.jsonl"
    assert set(pre.STRONG) == {"qwen35_122b", "gptoss_120b"} and all(pre.MODELS[k].reasoning_parser for k in pre.STRONG)


@pytest.mark.parametrize("text,style,answer,finished", [
    ('reason {x}</think>\n\n{"a": 1}', "think", '{"a": 1}', True),
    ("reasoning that never ends", "think", "", False),
    ('<|channel|>analysis<|message|>hm {x}<|end|><|start|>assistant<|channel|>final<|message|>{"a": 1}<|return|>',
     "harmony", '{"a": 1}', True),
    ("<|channel|>analysis<|message|>never finished", "harmony", "", False),
    ('<|channel|>analysis<|message|>x<|end|><|start|>assistant<|channel|>final<|constrain|>json<|message|>{"a": 1}',
     "harmony", '{"a": 1}', True),
    ("<|channel|>analysis<|message|>x<|end|><|start|>assistant<|channel|>final", "harmony", "", False),
    ('{"a": 1}<|im_end|>', "", '{"a": 1}', True),
])
def test_split_answer(text, style, answer, finished):
    assert pre.split_answer(text, style) == (answer, finished)


def test_schema_check_and_parse_answer():
    good = '{"label": "kept", "confidence": "high", "rationale": "x"}'
    assert pre.schema_ok(good)
    for bad in ('{"label": "Kept", "confidence": "high", "rationale": "x"}', '{"label": "kept", "confidence": "high"}',
                '{"label": "kept", "confidence": "high", "rationale": "x", "extra": 1}', "kept", ""):
        assert not pre.schema_ok(bad)
    out = ("<|channel|>analysis<|message|>maybe {\"label\": \"new\"}<|end|><|start|>assistant<|channel|>final"
           f"<|message|>{good}")
    r = pre.parse_answer(out, "harmony")
    assert r["label"] == "kept" and r["schema_ok"] and r["finished"]
    r = pre.parse_answer("thinking only", "think")
    assert not r["valid"] and not r["schema_ok"] and r["error"] == "no_answer"


def test_answer_attempts_retry_once():
    spec, msgs = pre.QWEN35_122B, [{"role": "user", "content": "u"}]
    k0, k1 = (pre.model_request_key(spec, msgs, 3, a) for a in (0, 1))
    cache = {}
    assert pre.next_attempt(spec, msgs, 3, cache) == 0
    cache[k0] = {"key": k0, "output": "thinking without an end", "finish_reason": "length"}
    e, a, n = pre.answer_attempts(spec, msgs, 3, cache)
    assert (a, n) == (None, 1) and pre.next_attempt(spec, msgs, 3, cache) == 1
    cache[k1] = {"key": k1, "output": 'ok</think>\n\n{"label": "kept", "confidence": "high", "rationale": "x"}'}
    e, a, n = pre.answer_attempts(spec, msgs, 3, cache)
    assert (a, n) == (1, 2) and e is cache[k1] and pre.next_attempt(spec, msgs, 3, cache) is None
    cache[k1] = {"key": k1, "output": "still thinking", "finish_reason": "length"}
    assert pre.next_attempt(spec, msgs, 3, cache) is None  # retries are bounded
    # A valid first attempt is never retried.
    cache = {k0: {"key": k0, "output": 'x</think>{"label": "new", "confidence": "low", "rationale": ""}'}}
    assert pre.answer_attempts(spec, msgs, 3, cache)[1] == 0 and pre.next_attempt(spec, msgs, 3, cache) is None


# --- agreement and label metrics -------------------------------------------------------------------

def test_cohen_kappa():
    assert pre.cohen_kappa(["kept", "kept", "dropped", "dropped"],
                           ["kept", "dropped", "dropped", "dropped"]) == pytest.approx(0.5)
    assert pre.cohen_kappa(["kept", "new"], ["kept", "new"]) == pytest.approx(1.0)


class _FakeOut:
    def __init__(self, text, finish="stop"):
        self.text, self.finish_reason, self.token_ids = text, finish, [0] * 7


class _FakeReqOut:
    def __init__(self, rid, text, finished=True):
        self.request_id, self.finished, self.prompt_token_ids = rid, finished, [1, 2, 3]
        self.outputs = [_FakeOut(text)]


class _FakeEngine:
    """Finishes the enqueued requests in reverse order, one per step, with a running (unfinished) output too."""

    def __init__(self, answers):
        self.answers, self.queue = answers, []

    def has_unfinished_requests(self):
        return bool(self.queue)

    def step(self):
        rid, j = self.queue.pop()
        return [_FakeReqOut("999", "partial", finished=False), _FakeReqOut(rid, self.answers[j])]


class _FakeLLM:
    def __init__(self, answers):
        self.llm_engine = _FakeEngine(answers)

    def enqueue(self, prompts, sp, use_tqdm=False):
        ids = [f"{k}-abcd1234" for k in range(len(prompts))]  # vLLM adds a suffix; outputs carry the plain id
        self.llm_engine.queue = [(str(k), k) for k in range(len(prompts))]
        return ids


class _FakeTok:
    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True, **kw):
        return "PROMPT " + messages[-1]["content"]


def test_generate_streams_answers_to_the_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(pre, "_sampling_params", lambda spec, smp, schema=None: None)
    spec = pre.GPT_OSS_120B
    good = '<|channel|>analysis<|message|>x<|end|><|start|>assistant<|channel|>final<|message|>' + \
        json.dumps({"label": "kept", "confidence": "high", "rationale": "r"})
    batch = [{"messages": [{"role": "user", "content": f"u{i}"}]} for i in range(3)]
    run = {"prompt_tokens": 0, "output_tokens": 0, "generated": 0, "generated_by_attempt": {}}
    cache = {}
    res = pre._generate(_FakeLLM([good, "<|channel|>analysis<|message|>x", good]), _FakeTok(), spec, batch, 5, 0,
                        tmp_path, cache, run)
    assert [x["schema_ok"] for x in res] == [True, False, True]  # completion order: requests 2, 1, 0
    rows = [json.loads(x) for x in (tmp_path / pre.cache_file(spec)).read_text().splitlines()]
    assert [r["prompt"] for r in rows] == ["PROMPT u2", "PROMPT u1", "PROMPT u0"]
    assert all(r["key"] == pre.model_request_key(spec, b["messages"], 5, 0) for r, b in zip(rows, batch[::-1]))
    assert run["generated"] == 3 and run["generated_by_attempt"] == {"0": 3} and len(cache) == 3
    assert rows[0]["sampling"]["seed"] == 5 and rows[0]["chat_template_kwargs"] == {"reasoning_effort": "high"}
    # The probe stops a run whose first answers all fail.
    with pytest.raises(SystemExit):
        pre._generate(_FakeLLM(["no answer"] * 3), _FakeTok(), spec, batch, 5, 0, tmp_path, {}, dict(run,
                      generated_by_attempt={}), probe=2)


def test_boot_agreement_matches_cohen_kappa():
    import numpy as np

    a = ["kept", "kept", "dropped", "dropped", "new", ""]
    b = ["kept", "dropped", "dropped", "dropped", "new", "new"]
    po, kap, n = pre.boot_agreement(a, b, np.ones((1, 6)))
    assert n == 5 and po[0] == pytest.approx(4 / 5) and kap[0] == pytest.approx(pre.cohen_kappa(a, b))
    W = pre.pair_boot_weights(["1", "1", "2", "2", "3", "3"], 50, 1)
    assert W.shape == (51, 6) and np.allclose(W[0], 1) and np.allclose(W[:, 0], W[:, 1])  # pairs move together
    assert np.allclose(W[1:].sum(axis=1), 6)
    m = pre.agreement_matrix({"x": a, "y": b, "z": b}, ["x", "y", "z"], W)
    assert [(r["a"], r["b"]) for r in m] == [("x", "y"), ("x", "z"), ("y", "z")]
    assert m[2]["kappa"] == pytest.approx(1.0) and m[0]["agreed"] == 4 and m[0]["lo"] <= m[0]["hi"]


def test_evidence_groups_and_credential_like():
    g = pre.evidence_group
    assert g({"found": {"prev": 1, "next": 2}}) == pre.EVIDENCE_GROUPS[0]
    assert g({"found": {"lit_prev": 1, "ctx_next": 3}}) == pre.EVIDENCE_GROUPS[1]
    assert g({"found": {"prev": 1}}) == pre.EVIDENCE_GROUPS[2]
    assert g({"found": {"next": 1}, "earlier_excerpt": "(2026-01-02, 1 rewrite) [1] x"}) == pre.EVIDENCE_GROUPS[3]
    assert g({"found": {"lit_next": 1}, "earlier_excerpt": "(no earlier version holding the unit was found)"}) == \
        pre.EVIDENCE_GROUPS[4]
    assert g({"found": {}}) == pre.EVIDENCE_GROUPS[5]
    assert pre.credential_like({"unit_key": "number|h:0123456789abcdef|", "value": "x"})
    assert pre.credential_like({"unit_key": "number|4821|pin", "value": pre.MASK})
    assert not pre.credential_like({"unit_key": "person|h:0123456789abcdef|", "value": "Alice"})
    assert not pre.credential_like({"unit_key": "number|56|donor", "value": "56"})


def test_adjudication_frame_and_accuracy():
    reqs = [{"pair_id": str(i // 2 + 1), "unit_key": f"number|{i}|x", "value": str(i)} for i in range(12)]
    reqs[11]["value"] = pre.MASK  # credential-like: left out of the frame
    q35 = ["kept", "kept", "dropped", "new", "kept", "kept", "kept", "kept", "new", "new", "kept", "dropped"]
    oss = ["dropped", "kept", "dropped", "new", "kept", "kept", "kept", "kept", "new", "new", "kept", "kept"]
    q14 = ["kept", "dropped", "dropped", "kept", "kept", "kept", "kept", "kept", "new", "new", "kept", "kept"]
    labels = {"qwen35_122b": q35, "gptoss_120b": oss, "qwen3_14b": q14}
    sample, info = pre.adjudication_frame(reqs, labels, seed=1, per_stratum=5)
    assert info["N"] == {"D1": 1, "D2": 2} and info["skipped"] == {"D1": 1, "D2": 0}
    assert sorted((s["row"], s["stratum"]) for s in sample) == [(0, "D1"), (1, "D2"), (3, "D2")]
    judged = {("1", "number|0|x"): {"judge_label": "dropped", "judge_confidence": "high"},
              ("1", "number|1|x"): {"judge_label": "kept", "judge_confidence": "high"},
              ("2", "number|3|x"): {"judge_label": "kept", "judge_confidence": "low"}}
    acc = pre.adjudication_accuracy(sample, info, judged, labels, ["qwen35_122b", "gptoss_120b", "qwen3_14b"])
    m = acc["methods"]
    assert m["qwen35_122b"]["D1"] == (0, 1, 0.0) and m["qwen35_122b"]["D2"] == (1, 2, 0.5)
    assert m["qwen35_122b"]["overall"][0] == pytest.approx(1 / 3)
    assert m["gptoss_120b"]["overall"][0] == pytest.approx(2 / 3)
    assert m["qwen3_14b"]["overall"][0] == pytest.approx(1 / 3)
    lo, hi = m["gptoss_120b"]["overall"][1:]
    assert 0 <= lo <= 2 / 3 <= hi <= 1
    # An undecided judgment is counted, not scored; without judged D2 units there is no overall value.
    judged[("1", "number|1|x")] = {"judge_label": "", "judge_confidence": "low", "judge_note": "undecided"}
    del judged[("2", "number|3|x")]
    acc = pre.adjudication_accuracy(sample, info, judged, labels, ["qwen35_122b"])
    assert acc["undecided"] == {"D2": 1} and acc["methods"]["qwen35_122b"]["overall"] is None


# --- review design ----------------------------------------------------------------------------------

def test_allocate_proportional_with_each_label():
    sizes = {"kept": 98, "modified": 14, "dropped": 75, "new": 79, "restored": 44}  # the real agreement rows
    assert pre.allocate(sizes, 60) == {"kept": 19, "modified": 3, "dropped": 15, "new": 15, "restored": 8}
    a = pre.allocate({"kept": 30, "modified": 3, "dropped": 15, "new": 10, "restored": 2}, 20)
    assert a == {"kept": 10, "modified": 1, "dropped": 5, "new": 3, "restored": 1}  # every label drawn
    assert pre.allocate({"kept": 3, "new": 2}, 60) == {"kept": 3, "new": 2}  # small strata: take all
    assert sum(pre.allocate({"kept": 1, "new": 1, "dropped": 100}, 2).values()) == 2


def _recheck_rows():
    """Rows for review_design: the strong-model labels and the three rule labels."""
    rows, k = [], 0
    for q, g, v1, v2, v3, n in (("kept", "dropped", "kept", "kept", "kept", 5),      # A: models disagree
                                ("kept", "", "kept", "kept", "kept", 1),             # A: no valid answer
                                ("dropped", "dropped", "modified", "dropped", "dropped", 4),  # B: v1 differs
                                ("kept", "kept", "kept", "kept", "", 1),             # B: v3 label missing
                                ("kept", "kept", "kept", "kept", "kept", 40),        # C:kept
                                ("new", "new", "new", "new", "new", 20),             # C:new
                                ("dropped", "dropped", "dropped", "dropped", "dropped", 10)):  # C:dropped
        for _ in range(n):
            k += 1
            rows.append({"pair_id": str(k // 4 + 1), "unit_key": f"number|{k}|x", "qwen35_label": q,
                         "gptoss_label": g, "rule_v1": v1, "rule_v2": v2, "rule_v3": v3})
    return rows


def test_review_design_strata_priorities_and_probabilities():
    rows = _recheck_rows()
    des, info = pre.review_design(rows, seed=20261003, target=30, min_sample=10)
    st = [d["stratum"] for d in des]
    assert (st.count("A"), st.count("B"), st.count("C:kept"), st.count("C:new"), st.count("C:dropped")) == \
        (6, 5, 40, 20, 10)
    assert (info["A"], info["B"], info["n_sample"]) == (6, 5, 19)  # max(10, 30 - 11)
    assert info["sample_by_label"] == {"kept": 11, "modified": 0, "dropped": 3, "new": 5, "restored": 0}
    assert info["counts"] == {pre.PRIORITIES[0]: 11, pre.PRIORITIES[1]: 19, pre.PRIORITIES[2]: 51}
    for d in des:
        if d["stratum"] in ("A", "B"):
            assert d["priority"] == pre.PRIORITIES[0] and d["inclusion_prob"] == 1.0
        else:
            want = {"C:kept": 11 / 40, "C:new": 5 / 20, "C:dropped": 3 / 10}[d["stratum"]]
            assert d["inclusion_prob"] == pytest.approx(want) and d["priority"] in pre.PRIORITIES[1:]
    assert [d["suggested"] for d in des[:6]] == [""] * 6 and des[6]["suggested"] == "dropped"
    sampled = Counter(d["stratum"] for d in des if d["priority"] == pre.PRIORITIES[1])
    assert sampled == {"C:kept": 11, "C:new": 5, "C:dropped": 3}
    assert pre.review_design(rows, seed=20261003, target=30, min_sample=10)[0] == des  # fixed
    assert pre.review_design(rows, seed=1, target=30, min_sample=10)[0] != des
    # Permanent random numbers: dropping a non-sampled C:kept row (allocation unchanged) keeps the sample.
    drop = next(i for i, d in enumerate(des) if d["priority"] == pre.PRIORITIES[2] and d["stratum"] == "C:kept")
    rows2 = rows[:drop] + rows[drop + 1:]
    des2, info2 = pre.review_design(rows2, seed=20261003, target=30, min_sample=10)
    assert info2["sample_by_label"] == info["sample_by_label"]
    assert [r["unit_key"] for r, d in zip(rows2, des2) if d["priority"] == pre.PRIORITIES[1]] == \
        [r["unit_key"] for r, d in zip(rows, des) if d["priority"] == pre.PRIORITIES[1]]
    # A small target still samples min_sample all-agree rows.
    _, info3 = pre.review_design(rows, seed=20261003, target=5, min_sample=10)
    assert info3["n_sample"] == 10 and info3["counts"][pre.PRIORITIES[1]] == 10


def test_rule_disagreements_are_certainty_rows():
    # Wherever two rule versions disagree, the consensus differs from one of them (or there is none).
    rows = _recheck_rows()
    des, _ = pre.review_design(rows, seed=3, target=20, min_sample=5)
    for r, d in zip(rows, des):
        if len({r["rule_v1"], r["rule_v2"], r["rule_v3"]}) > 1:
            assert d["stratum"] in ("A", "B") and d["inclusion_prob"] == 1.0


# --- label metrics -----------------------------------------------------------------------------------

def _write_sheet(path, rows):
    """rows: (priority, pair_id, rule, llm, human) or (rule, llm, human)."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(pre.REVIEW_COLUMNS))
        wr.writeheader()
        for i, row in enumerate(rows):
            pri, pair, rule, llm, human = row if len(row) == 5 else ("", i + 1, *row)
            wr.writerow({c: "" for c in pre.REVIEW_COLUMNS} | {
                "review_priority": pri, "pair_id": pair, "rule_label": rule, "llm_label": llm,
                "human_label": human, "unit_key": f"number|{i}|"})


P1, P2, P3 = pre.PRIORITIES
# Disagreements d1-d4 all labelled; agreements: 4 kept and 4 new, 2 of each labelled (weight 2).
DESIGN_SHEET = [
    (P1, 1, "kept", "dropped", "dropped"), (P1, 2, "modified", "dropped", "modified"),
    (P1, 3, "new", "kept", "kept"), (P1, 4, "dropped", "kept", "dropped"),
    (P2, 5, "kept", "kept", "kept"), (P2, 6, "kept", "kept", "kept"), (P3, 7, "kept", "kept", ""),
    (P3, 8, "kept", "kept", ""), (P2, 9, "new", "new", "new"), (P2, 10, "new", "new", "Dropped "),
    (P3, 11, "new", "new", ""), (P3, 12, "new", "new", ""),
]


def _metrics(tmp_path, sheet_rows, v2=None, reps=400):
    labels = tmp_path / "labels"
    labels.mkdir(exist_ok=True)
    _write_sheet(labels / pre.REVIEW_FILE, sheet_rows)
    if v2 is not None:
        with open(labels / pre.RULE_V2_FILE, "w", encoding="utf-8", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(["pair_id", "unit_key", "rule_label_v2"])
            wr.writerows(v2)
    cfg = {"seed": 5, "paths": {"labels": str(labels), "outputs": str(tmp_path / "out")}}
    rows = pre.compute_label_metrics(cfg, reps=reps)
    return {(r["scheme"], r["label"], r["metric"]): r for r in rows}, rows


def test_weighted_metrics_by_hand(tmp_path):
    get, rows = _metrics(tmp_path, DESIGN_SHEET)

    def w(lab, met):
        return get[("weighted", lab, met)]["rule"]

    assert (w("kept", "precision"), w("kept", "recall"), w("kept", "f1")) == pytest.approx((0.8, 0.8, 0.8))
    assert (w("dropped", "precision"), w("dropped", "recall"), w("dropped", "f1")) == pytest.approx((1, 0.25, 0.4))
    assert (w("new", "precision"), w("new", "recall"), w("new", "f1")) == pytest.approx((0.4, 1, 4 / 7))
    assert w("restored", "f1") == 0.0
    assert w("macro", "f1") == pytest.approx((0.8 + 1 + 0.4 + 4 / 7) / 4)  # labels present
    assert w("all", "accuracy") == pytest.approx(8 / 12)
    assert get[("weighted", "dropped", "f1")]["support"] == pytest.approx(4.0)
    assert get[("weighted", "all", "accuracy")]["llm"] == pytest.approx(8 / 12)
    u = get[("unweighted", "kept", "precision")]
    assert u["rule"] == pytest.approx(2 / 3) and u["rule_lo"] == ""
    assert get[("unweighted", "all", "accuracy")]["rule"] == pytest.approx(5 / 8)
    r = get[("weighted", "all", "accuracy")]
    assert 0 <= r["rule_lo"] <= r["rule"] <= r["rule_hi"] <= 1
    assert r["rule_v2"] == "" and r["v2_minus_v1"] == ""  # no v2 file
    assert (r["n_labelled"], r["n_labelled_disagree"], r["N_disagree"], r["n_labelled_agree"], r["N_agree"]) == \
        (8, 4, 4, 4, 8)
    assert "8 of 12 rows labelled" in r["note"] and "all priority 1-2 rows labelled" in r["note"]
    assert "agreement per rule label" in r["note"]
    out = tmp_path / "out" / "tables" / pre.METRICS_FILE
    with open(out, encoding="utf-8") as f:
        written = list(csv.DictReader(f))
    assert len(written) == len(rows) == 2 * (6 * 3 + 1 + 2 * 3) and list(written[0]) == list(pre.METRIC_COLUMNS)
    assert "accuracy" in pre.format_metrics(rows)


def test_metrics_v2_joined_side_by_side(tmp_path):
    # v2 fixes every labelled row; one sheet row has no v2 label, one file row matches nothing.
    v2 = [(pair, f"number|{i}|", "dropped" if i in (0, 9) else "kept" if i == 2 else rule)
          for i, (_, pair, rule, _, _) in enumerate(DESIGN_SHEET) if i != 11]
    v2.append((99, "number|99|", "kept"))
    get, _ = _metrics(tmp_path, DESIGN_SHEET, v2=v2)
    r = get[("weighted", "all", "accuracy")]
    assert r["rule_v2"] == pytest.approx(1.0) and r["rule_v2_lo"] == r["rule_v2_hi"] == pytest.approx(1.0)
    assert r["v2_minus_v1"] == pytest.approx(1 - 8 / 12)
    assert r["v2_minus_v1_lo"] <= r["v2_minus_v1"] <= r["v2_minus_v1_hi"]
    assert get[("unweighted", "kept", "f1")]["rule_v2"] == pytest.approx(1.0)
    assert "11 of 12 sheet rows matched, 1 file rows unmatched" in r["note"]


def test_metrics_partial_and_fallback(tmp_path):
    # Only part of the agreement sample is labelled and the 'new' cell has no label: the agreement
    # stratum falls back to one weight (8 rows / 1 labelled row).
    sheet = [row if row[1] not in (6, 9, 10) else (*row[:4], "") for row in DESIGN_SHEET]
    sheet[1] = (*sheet[1][:4], "")  # one disagreement unlabelled
    get, _ = _metrics(tmp_path, sheet)
    r = get[("weighted", "all", "accuracy")]
    assert (r["n_labelled"], r["n_labelled_disagree"], r["n_labelled_agree"]) == (4, 3, 1)
    assert "only labelled rows are used" in r["note"] and "agreement stratum" in r["note"]
    # disagreement: 3 labelled rows stand for 4 (per rule label is impossible, 'modified' unlabelled)
    assert "disagreement stratum" in r["note"]
    # weighted accuracy: d1, d3 wrong, d4 right at weight 4/3; a1 right at weight 8 -> (4/3 + 8) / 12
    assert r["rule"] == pytest.approx((4 / 3 + 8) / 12)
    # No agreement row labelled: no weighted estimate, unweighted still reported.
    sheet2 = [row if row[0] == P1 else (*row[:4], "") for row in DESIGN_SHEET]
    get2, _ = _metrics(tmp_path, sheet2)
    assert get2[("weighted", "all", "accuracy")]["rule"] == ""
    assert get2[("unweighted", "all", "accuracy")]["rule"] == pytest.approx(0.5)
    assert "weighted estimates need labelled rows in both strata" in get2[("weighted", "all", "accuracy")]["note"]


def test_metrics_empty_sheet_and_old_sheet_without_priority(tmp_path):
    get, rows = _metrics(tmp_path, [("kept", "kept", ""), ("new", "new", "")])
    assert all(r["n_labelled"] == 0 and r["rule"] == "" for r in rows)
    # Without review_priority the strata come from rule label vs LLM label; bad labels are ignored.
    get, _ = _metrics(tmp_path, [("kept", "kept", "kept"), ("new", "kept", "keep"), ("new", "", "new")])
    r = get[("unweighted", "all", "accuracy")]
    assert r["n_labelled"] == 2 and r["N_disagree"] == 2 and r["N_agree"] == 1 and r["rule"] == 1.0
    assert r["llm"] == 0.5 and "1 unrecognised human labels ignored" in r["note"]
    assert "1 labelled rows without a llm label" in r["note"]


def test_design_weights_calibrate_rule_labels():
    import numpy as np

    strata = ["disagree", "agree", "agree", "agree"]
    cells = ["new", "kept", "kept", "new"]
    clusters = ["1", "2", "3", "4"]
    N_cell = {("disagree", "new"): 2, ("agree", "kept"): 6, ("agree", "new"): 3}
    W, how = pre.design_weights(strata, cells, clusters, {"disagree": 2, "agree": 9}, N_cell, reps=50, seed=1)
    assert how == {"disagree": "per rule label", "agree": "per rule label"}
    assert np.allclose(W[0], [2, 3, 3, 3]) and np.allclose(W.sum(axis=1), 11)  # every replicate sums to N
    assert np.allclose(W[:, 1:3].sum(axis=1), 6)  # rule label 'kept' keeps its true count


# Re-check design: A and B are certainty strata; C:kept has 4 rows (2 sampled), C:new 2 rows (1 sampled).
RECHECK_SHEET = [  # stratum, priority, inclusion, rule v1, Qwen3-14B, Qwen3.5, gpt-oss, human
    ("A", P1, 1.0, "kept", "kept", "dropped", "kept", "dropped"),
    ("A", P1, 1.0, "modified", "modified", "dropped", "modified", "modified"),
    ("B", P1, 1.0, "new", "new", "kept", "kept", "kept"),
    ("B", P1, 1.0, "dropped", "dropped", "dropped", "dropped", "dropped"),
    ("C:kept", P2, 0.5, "kept", "kept", "kept", "kept", "kept"),
    ("C:kept", P2, 0.5, "kept", "kept", "kept", "kept", "kept"),
    ("C:kept", P3, 0.5, "kept", "kept", "kept", "kept", "dropped"),  # labelled outside the sample
    ("C:kept", P3, 0.5, "kept", "kept", "kept", "kept", ""),
    ("C:new", P2, 0.5, "new", "new", "new", "new", "new"),
    ("C:new", P3, 0.5, "new", "new", "new", "new", ""),
]


def _recheck_metrics(tmp_path, sheet_rows, reps=400):
    labels = tmp_path / "labels"
    labels.mkdir(exist_ok=True)
    with open(labels / pre.REVIEW_FILE, "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(pre.SHEET_COLUMNS))
        wr.writeheader()
        for i, (st, pri, prob, _, _, q35, oss, human) in enumerate(sheet_rows):
            wr.writerow({c: "" for c in pre.SHEET_COLUMNS} | {
                "review_priority": pri, "pair_id": i + 1, "design_stratum": st, "inclusion_prob": f"{prob:.6f}",
                "qwen35_label": q35, "gptoss_label": oss, "human_label": human, "unit_key": f"number|{i}|"})
    with open(labels / pre.PAIRS_FILE, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["pair_id", "agent_id", "prev_uid", "next_uid", "unit_key", "rule_label", "human_label", "notes"])
        wr.writerows((i + 1, "a", "p", "n", f"number|{i}|", row[3], "", "") for i, row in enumerate(sheet_rows))
    with open(labels / pre.LLM_LABELS_FILE, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["pair_id", "unit_key", *pre.LLM_KEYS])
        wr.writerows((i + 1, f"number|{i}|", row[4], row[5], row[6]) for i, row in enumerate(sheet_rows))
    cfg = {"seed": 5, "paths": {"labels": str(labels), "outputs": str(tmp_path / "out")}}
    rows = pre.compute_label_metrics(cfg, reps=reps)
    return {(r["scheme"], r["label"], r["metric"]): r for r in rows}, rows


def test_recheck_design_weighted_metrics_by_hand(tmp_path):
    get, rows = _recheck_metrics(tmp_path, RECHECK_SHEET)

    def w(lab, met, m="rule"):
        return get[("weighted", lab, met)][m]

    # Weights: A and B rows 1, sampled C:kept rows 4/2 = 2, the sampled C:new row 2/1 = 2 (= 1/inclusion).
    assert w("all", "accuracy") == pytest.approx(8 / 10)
    assert (w("kept", "precision"), w("kept", "recall")) == pytest.approx((0.8, 0.8))
    assert (w("dropped", "precision"), w("dropped", "recall"), w("dropped", "f1")) == pytest.approx((1, 0.5, 2 / 3))
    assert (w("new", "precision"), w("new", "recall"), w("new", "f1")) == pytest.approx((2 / 3, 1, 0.8))
    assert w("macro", "f1") == pytest.approx((0.8 + 1 + 2 / 3 + 0.8) / 4)
    assert w("all", "accuracy", "llm") == pytest.approx(0.8)  # Qwen3-14B joined from the LLM label file
    assert w("all", "accuracy", "qwen35_122b") == pytest.approx(0.9) == w("all", "accuracy", "gptoss_120b")
    assert w("dropped", "precision", "qwen35_122b") == pytest.approx(2 / 3)
    assert w("dropped", "precision", "gptoss_120b") == pytest.approx(1.0)
    r = get[("weighted", "all", "accuracy")]
    assert 0 <= r["rule_lo"] <= r["rule"] <= r["rule_hi"] <= 1 and r["qwen35_122b_lo"] <= 0.9 <= r["qwen35_122b_hi"]
    assert (r["n_labelled"], r["n_labelled_disagree"], r["N_disagree"], r["n_labelled_agree"], r["N_agree"]) == \
        (8, 4, 4, 3, 6)
    assert "re-check design" in r["note"] and "all priority 1-2 rows labelled" in r["note"]
    assert "certainty per design stratum, sample per design stratum" in r["note"]
    assert "1 labelled priority-3 rows outside the sample count in the unweighted scheme only" in r["note"]
    assert "WARNING" not in r["note"] and "rule (v1) joined from memory_pairs.csv: 10 of 10" in r["note"]
    # Unweighted: all 8 labelled rows, including the one outside the sample.
    assert get[("unweighted", "all", "accuracy")]["rule"] == pytest.approx(5 / 8)
    out = tmp_path / "out" / "tables" / pre.METRICS_FILE
    with open(out, encoding="utf-8") as f:
        assert next(csv.reader(f)) == list(pre.METRIC_COLUMNS)
    text = pre.format_metrics(rows)
    assert "qwen35_122b" in text and "gptoss_120b" in text


def test_recheck_design_pooling_and_probability_check(tmp_path):
    # The only sampled C:new row is unlabelled: stratum C is weighted as one group (6 rows / 2 labelled).
    sheet = [row if i != 8 else (*row[:7], "") for i, row in enumerate(RECHECK_SHEET)]
    get, _ = _recheck_metrics(tmp_path, sheet)
    r = get[("weighted", "kept", "precision")]
    assert r["rule"] == pytest.approx(6 / 7) and "sample stratum" in r["note"]
    assert "only labelled rows are used" in r["note"]
    # Recorded inclusion probabilities that do not match the sampled fractions are flagged.
    bad = [(*row[:2], 0.25, *row[3:]) if row[0] == "C:kept" else row for row in RECHECK_SHEET]
    get, _ = _recheck_metrics(tmp_path, bad)
    assert "WARNING" in get[("weighted", "all", "accuracy")]["note"]


# --- report stage on a synthetic cache --------------------------------------------------------------

def _strong_output(spec, label, finished=True):
    js = json.dumps({"label": label, "confidence": "medium", "rationale": "reason words"})
    if spec.reasoning == "think":
        return f"Let me check {{the value}}.\n</think>\n\n{js}" if finished else "Let me check and check"
    if finished:
        return ("<|channel|>analysis<|message|>Check {braces} and kept.<|end|><|start|>assistant<|channel|>final"
                f"<|message|>{js}")
    return "<|channel|>analysis<|message|>Check"


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r) + "\n" for r in rows)


def test_report_recheck_design(tmp_path, monkeypatch):
    secret_text = "UNIQUE-EXCERPT-TEXT"
    cfg = {"seed": 7, "paths": {"labels": str(tmp_path / "labels"), "outputs": str(tmp_path / "out"),
                                "interim": str(tmp_path / "interim")},
           "llm": {"cache_dir": str(tmp_path / "llm_cache")}}
    cdir = pre.cache_dir(cfg)
    cdir.mkdir(parents=True)
    labels = tmp_path / "labels"
    labels.mkdir()
    units = [  # rule v1, v2, v3, Qwen3-14B, Qwen3.5 (None: no answer after the retry), gpt-oss
        ("kept", "kept", "kept", "kept", "kept", "kept"),  # C:kept
        ("kept", "kept", "kept", "kept", "kept", "kept"),  # C:kept
        ("new", "new", "new", "new", "new", "new"),  # C:new
        ("modified", "kept", "kept", "dropped", "kept", "kept"),  # B, overturns Qwen3-14B
        ("dropped", "dropped", "dropped", "dropped", "dropped", "kept"),  # A
        ("new", "new", "kept", "kept", None, "kept"),  # A
    ]
    reqs, c14, c35, coss = [], [], [], []
    for i, (v1, v2, v3, l14, l35, loss) in enumerate(units):
        msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": f"unit {i}"}]
        key = pre.request_key(msgs, 7)
        t = "number" if i % 2 else "org"
        reqs.append({"row": i, "pair_id": str(i // 2 + 1), "agent_id": "a", "agent": "Claude Opus 4.5",
                     "prev_uid": "p", "next_uid": "n", "unit_key": f"{t}|{i}|day", "rule_label": v1,
                     "unit_type": t, "value": "=1+1" if i == 0 else str(i), "context_key": "day",
                     "prev_excerpt": f"[1] {secret_text} {i}", "next_excerpt": "[1] x", "earlier_excerpt": "",
                     "found": {"prev": 1, "next": int(v1 == "kept"), "ctx_next": i % 2}, "messages": msgs,
                     "key": key})
        c14.append({"key": key, "output": json.dumps({"label": l14, "confidence": "high", "rationale": "r"}),
                    "finish_reason": "stop", "output_tokens": 20})
        for spec, lab, sink in ((pre.QWEN35_122B, l35, c35), (pre.GPT_OSS_120B, loss, coss)):
            if lab is None:  # every attempt ends inside the reasoning
                for a in range(len(spec.budgets)):
                    sink.append({"key": pre.model_request_key(spec, msgs, 7, a), "finish_reason": "length",
                                 "output": _strong_output(spec, "kept", False), "output_tokens": spec.budgets[a]})
            else:
                sink.append({"key": pre.model_request_key(spec, msgs, 7, 0), "finish_reason": "stop",
                             "output": _strong_output(spec, lab), "output_tokens": 300})
    _write_jsonl(cdir / "requests.jsonl", reqs)
    _write_jsonl(cdir / "cache.jsonl", c14)
    _write_jsonl(cdir / pre.cache_file(pre.QWEN35_122B), c35)
    _write_jsonl(cdir / pre.cache_file(pre.GPT_OSS_120B), coss)
    for k, v in ((2, "v2"), (3, "v3")):
        with open(labels / f"memory_pairs_rule_{v}.csv", "w", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(["pair_id", "unit_key", f"rule_label_{v}"])
            wr.writerows((r["pair_id"], r["unit_key"], u[k - 1]) for r, u in zip(reqs, units))
    with open(labels / pre.PAIRS_FILE, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["pair_id", "agent_id", "prev_uid", "next_uid", "unit_key", "rule_label", "human_label", "notes"])
        wr.writerows((r["pair_id"], "a", "p", "n", r["unit_key"], r["rule_label"], "", "") for r in reqs)
    # The Qwen3-14B sheet with one label already filled: backed up, and the label carried over.
    with open(labels / pre.REVIEW_FILE, "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(pre.REVIEW_COLUMNS))
        wr.writeheader()
        wr.writerow({c: "" for c in pre.REVIEW_COLUMNS} | {"pair_id": reqs[3]["pair_id"], "human_label": "kept",
                                                         "unit_key": reqs[3]["unit_key"]})
    monkeypatch.setattr(pre, "REVIEW_TARGET", 5)
    monkeypatch.setattr(pre, "MIN_SAMPLE", 2)
    res = pre.report(cfg, log=lambda *_: None)
    P1, P2, P3 = pre.PRIORITIES
    assert res["design"]["counts"] == {P1: 3, P2: 2, P3: 1} and (res["design"]["A"], res["design"]["B"]) == (2, 1)
    assert (labels / pre.BACKUP_FILE).exists() and (labels / pre.BACKUP_FILE).stat().st_mode & 0o077 == 0
    sheet = labels / pre.REVIEW_FILE
    assert sheet.read_bytes().startswith(b"\xef\xbb\xbf") and (sheet.stat().st_mode & 0o077) == 0
    with open(sheet, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == list(pre.SHEET_COLUMNS) and "rule_label" not in rows[0] and "llm_label" not in rows[0]
    by = {r["unit_key"]: r for r in rows}
    k = [r["unit_key"] for r in reqs]
    assert [r["review_priority"] for r in rows] == [P1, P1, P1, P2, P2, P3]
    assert {by[k[i]]["design_stratum"] for i in (4, 5)} == {"A"} and by[k[3]]["design_stratum"] == "B"
    assert by[k[4]]["suggested_label"] == "" and by[k[3]]["suggested_label"] == "kept"
    assert by[k[5]]["qwen35_label"] == "" and by[k[5]]["qwen35_rationale"] == "(no valid model output)"
    assert by[k[5]]["gptoss_label"] == "kept" and by[k[4]]["qwen35_label"] == "dropped"
    assert by[k[3]]["inclusion_prob"] == "1.000000" and by[k[2]]["inclusion_prob"] == "1.000000"
    assert {by[k[0]]["inclusion_prob"], by[k[1]]["inclusion_prob"]} == {"0.500000"}
    assert by[k[0]]["value"] == " =1+1" and by[k[3]]["human_label"] == "kept"
    with open(labels / pre.LLM_LABELS_FILE, encoding="utf-8") as f:
        llm = {r["unit_key"]: r for r in csv.DictReader(f)}
    assert llm[k[5]]["qwen35_122b"] == "" and llm[k[3]]["qwen3_14b"] == "dropped" and llm[k[4]]["gptoss_120b"] == "kept"
    readme = (labels / pre.README_FILE).read_text()
    assert readme.startswith("# memory_pairs_review.csv") and "5 rows" in readme and "{" not in readme
    qa = (tmp_path / "out" / "qa" / pre.QA_FILE).read_text()
    assert secret_text not in qa and "## 6. Agreement between labellers" in qa and "## 11. Review design" in qa
    assert "No judgments recorded yet." in qa and "Qwen3-14B → consensus" in qa
    # The metrics read the new sheet: v1 from memory_pairs.csv, Qwen3-14B from the label file.
    m = pre.compute_label_metrics(cfg, reps=20)
    acc = next(r for r in m if r["scheme"] == "unweighted" and r["label"] == "all")
    assert acc["n_labelled"] == 1 and acc["rule"] == 0.0 and acc["llm"] == 0.0 and acc["qwen35_122b"] == 1.0
    assert "re-check design" in acc["note"] and "rule (v1) joined from memory_pairs.csv: 6 of 6" in acc["note"]
    # Third-judge labels enter the QA as accuracies (blind judgments recorded per sampled unit).
    with open(labels / pre.ADJUDICATION_FILE, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(pre.ADJ_COLUMNS))
        wr.writeheader()
        wr.writerow({"pair_id": reqs[4]["pair_id"], "unit_key": k[4], "stratum": "D1", "judge_label": "dropped",
                     "judge_confidence": "high"})
        wr.writerow({"pair_id": reqs[3]["pair_id"], "unit_key": k[3], "stratum": "D2", "judge_label": "kept",
                     "judge_confidence": "medium"})
    res2 = pre.report(cfg, log=lambda *_: None)
    assert res2["adjudication"]["N"] == {"D1": 2, "D2": 1}
    qa = (tmp_path / "out" / "qa" / pre.QA_FILE).read_text()
    assert "Accuracy against the third judge" in qa and secret_text not in qa
    with open(sheet, encoding="utf-8-sig") as f:
        assert {r["unit_key"]: r for r in csv.DictReader(f)}[k[3]]["human_label"] == "kept"  # survives a rerun


def test_scanner_ignores_the_mask():
    hits = pre._scanner_hits(["password: «masked» and more"])
    if hits is None:
        pytest.skip("scripts/scan_credentials.py not available")
    assert hits == {} and sum(pre._scanner_hits(["password: Tr0ub4dor&3xyz"]).values()) == 1


def test_repeated_passages_are_shown_once():
    block = "Scene list: 3 scenes recorded today. "
    text = ("x " * 200 + block) * 3 + "x " * 200 + "Later: 3 scenes again, new wording."
    marks = [pre.Mark(i, i + 1, "value") for i in range(len(text)) if text.startswith("3 scenes", i)]
    wins, left = pre.excerpt_windows(text, [marks], [])
    assert len(wins) == 2 and left == 0  # three identical passages collapse into one window
    assert sum("Later" in w for w in wins) == 1


# --- B2 parent sheet: re-check models ---------------------------------------------------------------

def test_parent_choice_check_and_cache_key():
    from avsd.lineage import prelabel_parents as pp

    req = {"candidates": [{"n": 1, "uid": "a"}, {"n": 2, "uid": "env"}]}
    ok = {"choice": "1", "confidence": "high", "rationale": "same number"}
    assert pp.choice_ok(json.dumps(ok), req) and pp.choice_ok(json.dumps(ok | {"choice": "ENV"}), req)
    assert pp.choice_ok(json.dumps(ok | {"choice": "none"}), req)
    for bad in (ok | {"choice": "3"}, ok | {"choice": "the first"}, ok | {"confidence": "sure"},
                {"choice": "1", "confidence": "high"}, ok | {"extra": 1}):
        assert not pp.choice_ok(json.dumps(bad), req)
    assert not pp.choice_ok("not json", req)
    msgs = [{"role": "user", "content": "child"}]
    k = pre.model_request_key(pre.GPT_OSS_120B, msgs, 3, 0, pp.PARENT_TASK)
    assert k != pre.model_request_key(pre.GPT_OSS_120B, msgs, 3) and len(k) == 64
    out = ("<|channel|>analysis<|message|>x<|end|><|start|>assistant<|channel|>final<|constrain|>json<|message|>"
           + json.dumps(ok | {"choice": "2"}))
    cache = {k: {"key": k, "output": out}}
    _, a, n = pre.answer_attempts(pre.GPT_OSS_120B, msgs, 3, cache, pp.PARENT_TASK, req)
    assert (a, n) == (0, 1)
    assert pp.normalize_label(pp.parse_choice(pre.split_answer(out, "harmony")[0], 2)["choice"],
                              req["candidates"]) == "env"


def test_parent_report_with_strong_models(tmp_path):
    from avsd.lineage import prelabel_parents as pp

    secret = "UNIQUE-PARENT-EXCERPT"
    cfg = {"seed": 7, "paths": {"labels": str(tmp_path / "labels"), "outputs": str(tmp_path / "out"),
                                "interim": str(tmp_path / "interim")},
           "llm": {"cache_dir": str(tmp_path / "llm_cache")}}
    out = pp.cache_dir(cfg)
    out.mkdir(parents=True)
    labels = tmp_path / "labels"
    labels.mkdir()
    # (MAP candidate, Qwen3-14B, Qwen3.5, gpt-oss); candidate 3 is the env candidate.
    items = [("1", "1", "1", "1"), ("1", "2", "2", "2"), ("1", "1", "1", "3"), ("3", "ENV", "ENV", "3"),
             ("1", "NONE", None, "1")]
    reqs, c14, c35, coss = [], [], [], []

    def js(ch):
        return json.dumps({"choice": ch, "confidence": "medium", "rationale": "shared number"})

    for i, (mp, l14, l35, loss) in enumerate(items):
        msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": f"child {i}"}]
        cands = [{"n": 1, "row": 0, "uid": f"chat:{i}a", "who": "o3", "channel": "chat message by another agent",
                  "key": "chat>chat:other", "dt_h": 0.5, "post": 0.7, "excerpt": f"{secret} {i}"},
                 {"n": 2, "row": 1, "uid": f"chat:{i}b", "who": "human", "channel": "chat message",
                  "key": "chat>human", "dt_h": 1.0, "post": 0.2, "excerpt": "x"},
                 {"n": 3, "row": 2, "uid": "env", "who": "o3", "channel": "ENV: its own computer", "key": "env>chat",
                  "dt_h": 2.0, "post": 0.1, "excerpt": "y"}]
        reqs.append({"item": i + 1, "stratum": "env" if mp == "3" else "chat_other", "gi": i, "child_uid": f"c{i}",
                     "child_src": "chat", "child_agent": "o3", "child_excerpt": f"{secret} child",
                     "unit_kind": "anchor",
                     "unit_type": "number", "unit_value": "56", "candidates": cands, "map_n": int(mp),
                     "map_post": 0.7, "messages": msgs, "key": pp.request_key(msgs, 7)})
        c14.append({"key": reqs[-1]["key"], "output": js(l14), "finish_reason": "stop"})
        for spec, lab, sink in ((pre.QWEN35_122B, l35, c35), (pre.GPT_OSS_120B, loss, coss)):
            for a in range(len(spec.budgets) if lab is None else 1):
                ans = _strong_output(spec, "kept", lab is not None).replace(
                    json.dumps({"label": "kept", "confidence": "medium", "rationale": "reason words"}), js(lab or "1"))
                sink.append({"key": pre.model_request_key(spec, msgs, 7, a, pp.PARENT_TASK), "output": ans,
                             "finish_reason": "stop" if lab else "length", "output_tokens": 100})
    _write_jsonl(out / "requests.jsonl", reqs)
    _write_jsonl(out / "cache.jsonl", c14)
    _write_jsonl(out / pre.cache_file(pre.QWEN35_122B), c35)
    _write_jsonl(out / pre.cache_file(pre.GPT_OSS_120B), coss)
    # Without the strong models' answers: the first design (Qwen3-14B columns only), then the owner labels a row.
    os_ = out / pre.cache_file(pre.QWEN35_122B)
    hidden = os_.with_suffix(".hidden")
    os_.rename(hidden)
    r0 = pp.report(cfg, log=lambda *_: None)
    assert not r0["recheck"]
    sheet = labels / pp.REVIEW_FILE
    with open(sheet, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert "qwen35_choice" not in rows[0]
    for r in rows:
        if r["child_uid"] == "c1":
            r["human_parent"], r["notes"] = "2", "direct reply"
    with open(sheet, "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    hidden.rename(os_)
    res = pp.report(cfg, log=lambda *_: None)
    assert res["recheck"] and res["priority1"] == 3
    assert (labels / pp.BACKUP_FILE).exists() and (labels / pp.BACKUP_FILE).stat().st_mode & 0o077 == 0
    with open(sheet, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    by = {r["child_uid"]: r for r in rows}
    for c in ("human_parent", "child_uid", "cand_1_uid", "model_map", "llm_choice", "suggested_parent",
              "qwen35_choice", "gptoss_choice", "gptoss_rationale"):
        assert c in rows[0]
    assert by["c0"]["review_priority"] == "2" and by["c0"]["suggested_parent"] == "1"
    assert by["c1"]["suggested_parent"] == "2" and by["c1"]["review_priority"] == "1"  # agree, not the MAP parent
    assert by["c2"]["suggested_parent"] == "" and by["c2"]["gptoss_choice"] == "env"  # candidate 3 is env
    assert by["c3"]["suggested_parent"] == "env" and by["c3"]["model_map"] == "env"
    assert by["c3"]["review_priority"] == "2"
    assert by["c4"]["qwen35_choice"] == "" and by["c4"]["qwen35_rationale"] == "(no valid model output)"
    assert by["c1"]["human_parent"] == "2" and by["c1"]["notes"] == "direct reply"  # kept
    assert [r["review_priority"] for r in rows] == sorted(r["review_priority"] for r in rows)
    readme = (labels / pp.README_FILE).read_text()
    assert "suggested_parent" in readme and "{" not in readme and "priority 1: 3 rows" in readme
    qa = (tmp_path / "out" / "qa" / pp.QA_FILE).read_text()
    assert secret not in qa and "Re-check with two stronger models" in qa and "| MAP parent / gpt-oss-120b | 5 |" in qa
    pytest.importorskip("scipy")
    m = {r["labeller"]: r for r in pp.metrics(cfg, log=lambda *_: None)}
    assert m["model_map"]["accuracy"] == 0.0 and m["qwen35_122b"]["accuracy"] == 1.0
    assert m["gptoss_120b"]["agree_with_owner"] == 1 and m["suggested_parent"]["n_labelled"] == 1


# --- Gemini rater: redaction, prompts, metrics and the run loop -------------------------------------

class _Ent:
    def __init__(self, text, start, label="PERSON"):
        self.text, self.start_char, self.end_char, self.label_ = text, start, start + len(text), label


class _FakeNLP:
    """Tags the first occurrence of each listed name as PERSON (a real model can miss repeats)."""

    def __init__(self, names):
        self.names = names

    def __call__(self, text):
        class D:
            pass

        d = D()
        d.ents = [_Ent(n, text.index(n)) for n in self.names if n in text]
        return d


AGENTS = ["Claude Opus 4.5", "GPT-5.2", "Gemini 2.5 Pro", "o3"]


def test_redactor_placeholders_are_consistent_and_keep_agents():
    red = pre.Redactor(AGENTS, _FakeNLP(["Alice Smith", "Bob", "Opus 4.6", "Claude Opus 4.5"]))
    fields = {"prev": "Alice Smith wrote to bob@x.org; Bob called 415-555-0123. Opus 4.6 agreed.",
              "next": "⟦Alice Smith⟧ again (Alice Smith), mail bob@x.org, Claude Opus 4.5 and Bob."}
    out, counts = red.redact(fields)
    assert out["prev"] == "[PERSON_1] wrote to [EMAIL_1]; [PERSON_2] called [PHONE_1]. Opus 4.6 agreed."
    assert out["next"] == "⟦[PERSON_1]⟧ again ([PERSON_1]), mail [EMAIL_1], Claude Opus 4.5 and [PERSON_2]."
    assert counts == {"PERSON": 2, "EMAIL": 1, "PHONE": 1}
    assert red.is_agent("Opus 4.6") and red.is_agent("GPT-5.2's") and not red.is_agent("Alice")


def test_redactor_pseudonymises_the_units_own_value():
    red = pre.Redactor(AGENTS, _FakeNLP([]))
    out, _ = red.redact({"value": "Dana Wu", "prev": "Met Dana Wu.", "next": "Dana replied; dana@q.io"},
                             "value", "PERSON")
    assert out == {"value": "[PERSON_1]", "prev": "Met [PERSON_1].", "next": "[PERSON_1] replied; [EMAIL_1]"}
    out, _ = red.redact({"value": "Ann.Lee@site.org", "prev": "write to ann.lee@site.org"}, "value", "EMAIL")
    assert out == {"value": "[EMAIL_1]", "prev": "write to [EMAIL_1]"}
    # a common word is not replaced in lower case
    red2 = pre.Redactor(AGENTS, _FakeNLP(["Will"]))
    out, _ = red2.redact({"prev": "Will said we will see."})
    assert out["prev"] == "[PERSON_1] said we will see."
    # spans are trimmed of bullets and line marks; spans with digits, paths or file names are not names
    red3 = pre.Redactor(AGENTS, _FakeNLP(["↵ - Adam", "index.html", "Batch 51", "↵ ↵ - *"]))
    out, counts = red3.redact({"prev": "x ↵ - Adam ran index.html in Batch 51 ↵ ↵ - * done"})
    assert out["prev"] == "x ↵ - [PERSON_1] ran index.html in Batch 51 ↵ ↵ - * done" and counts == {"PERSON": 1}


def test_gemini_b1_prompt_has_no_marks_or_counts():
    red = pre.Redactor(AGENTS, _FakeNLP(["Alice Smith"]))
    row = {"unit_type": "number", "value": " =56", "context_key": "donor",
           "prev_excerpt": "[1] We have ⟦56⟧ donors and ⟨60⟩ days, thanks Alice Smith. (+2 more matches)",
           "next_excerpt": "(neither the value nor its context occurs in NEXT)",
           "earlier_excerpt": "(2026-01-02, 3 rewrites between it and NEXT) [1] Old: ⟦56⟧ donors"}
    msgs, counts = pre.gemini_b1_messages(row, red)
    user = msgs[1]["content"]
    assert not any(c in user for c in "⟦⟧⟨⟩") and "more match" not in user and "occurs" not in user
    assert "We have 56 donors and 60 days, thanks [PERSON_1]." in user and "Alice" not in user
    assert "NEXT (the output):\n(no passage)" in user and "- value: =56" in user
    earlier = "EARLIER (an older version before PREV; 2026-01-02, 3 rewrites between it and NEXT):"
    assert earlier + "\n[1] Old: 56 donors" in user
    assert "Two warnings:" in user and "unrelated means new" in user and "do not rely on exact string matches" in user
    assert "part of the fact" in user and counts == {"PERSON": 1}
    row2 = dict(row, unit_type="person", value="Alice Smith", context_key="",
                earlier_excerpt="(no earlier version holding the unit was found)")
    user2 = pre.gemini_b1_messages(row2, red)[0][1]["content"]
    assert "- value: [PERSON_1]" in user2 and "EARLIER" not in user2.split("Text:")[1] and "Alice" not in user2


def test_gemini_b2_prompt_uses_the_blind_order():
    from avsd.lineage import prelabel_parents as pp

    red = pre.Redactor(AGENTS, _FakeNLP(["Bob Ray"]))
    row = {"child_agent": "o3", "child_source": "chat", "child_excerpt": "see ⟦the river map⟧ from Bob Ray",
           "cand_1_channel": "ENV: its own computer", "cand_1_who": "o3", "cand_1_dt_h": "2.5",
           "cand_1_excerpt": "screen shows ⟦the river map⟧",
           "cand_2_channel": "chat message", "cand_2_who": "human", "cand_2_dt_h": "0.25",
           "cand_2_excerpt": "Bob Ray: ⟦the river map⟧ is up"}
    msgs, cands, counts = pp.gemini_b2_messages(row, red)
    user = msgs[1]["content"]
    assert cands == [1, 2]
    assert "[1] ENV: its own computer (o3), 2.50 active hours before: screen shows ⟦the river" in user
    assert "[2] chat message (human), 0.25 active hours before: [PERSON_1]: ⟦the river map⟧ is up" in user
    assert "Bob" not in user and "post" not in user.lower().replace("posted", "") and counts == {"PERSON": 1}
    sheet_row = {"cand_1_uid": "chat:a", "cand_2_uid": "chat:b", "cand_3_uid": "env"}
    assert pp.gemini_parent("2", {"1": "3", "2": "1"}, sheet_row) == "1"
    assert pp.gemini_parent("1", {"1": "3", "2": "1"}, sheet_row) == "env"
    assert pp.gemini_parent("ENV", {}, sheet_row) == "env" and pp.gemini_parent("9", {"1": "3"}, sheet_row) == ""


def test_metrics_score_gemini_on_its_rows_only(tmp_path):
    labels = tmp_path / "labels"
    labels.mkdir()
    # Gemini labelled 8 of the 10 rows: right on rows 0, 2, 3, 4, 8; wrong on row 1; invalid (empty) on row 5;
    # row 6 (outside the sample) right; rows 7 and 9 not labelled.
    gem = {0: "dropped", 1: "kept", 2: "kept", 3: "dropped", 4: "kept", 5: "", 6: "dropped", 8: "new"}
    with open(labels / pre.GEMINI_LABELS_FILE, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["pair_id", "unit_key", "gemini_label", "gemini_model"])
        wr.writerows((i + 1, f"number|{i}|", g, "gemini-2.5-flash") for i, g in gem.items())
    get, rows = _recheck_metrics(tmp_path, RECHECK_SHEET)
    w = get[("weighted", "all", "accuracy")]
    # weighted rows 0-5 and 8: weights 1, 1, 1, 1, 2, 2 (C:kept: 4 rows / 2 labelled) and 2; row 5 counts wrong
    assert w["gemini"] == pytest.approx((1 + 0 + 1 + 1 + 2 + 0 + 2) / 10)
    assert get[("unweighted", "all", "accuracy")]["gemini"] == pytest.approx(6 / 8)
    assert w["rule"] == pytest.approx(0.8) and "gemini_lo" in w and w["gemini_lo"] <= w["gemini"] <= w["gemini_hi"]
    assert "8 of 10 sheet rows have a Gemini answer" in w["note"]
    assert "1 labelled rows without a gemini label" in w["note"]
    assert "gemini" in pre.format_metrics(rows)


def test_parent_metrics_include_gemini(tmp_path):
    from avsd.lineage import prelabel_parents as pp

    pytest.importorskip("scipy")
    labels = tmp_path / "labels"
    labels.mkdir()
    cols = ["review_priority", "item", "child_uid", "cand_1_uid", "cand_2_uid", "model_map", "llm_choice",
            "human_parent", "notes"]
    with open(labels / pp.REVIEW_FILE, "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=cols)
        wr.writeheader()
        wr.writerow({"review_priority": "1", "item": 1, "child_uid": "c1", "cand_1_uid": "a", "cand_2_uid": "env",
                     "model_map": "1", "llm_choice": "1", "human_parent": "env", "notes": ""})
        wr.writerow({"review_priority": "1", "item": 2, "child_uid": "c2", "cand_1_uid": "b", "cand_2_uid": "env",
                     "model_map": "1", "llm_choice": "env", "human_parent": "1", "notes": ""})
    with open(labels / pp.GEMINI_FILE, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["child_uid", "gemini_choice_blind", "gemini_parent", "gemini_model"])
        wr.writerow(["c1", "ENV", "env", "gemini-3.1-pro-preview"])
    cfg = {"seed": 1, "paths": {"labels": str(labels), "outputs": str(tmp_path / "out")}}
    m = {r["labeller"]: r for r in pp.metrics(cfg, log=lambda *_: None)}
    assert m["gemini"]["n_labelled"] == 1 and m["gemini"]["accuracy"] == 1.0
    assert m["model_map"]["accuracy"] == 0.5 and m["llm"]["accuracy"] == 0.0


def _gemini_module():
    import importlib.util

    from avsd.config import REPO_ROOT

    path = REPO_ROOT / "scripts" / "gemini_label.py"
    if not path.exists():
        pytest.skip("scripts/gemini_label.py not available")
    spec = importlib.util.spec_from_file_location("_avsd_gemini_label", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gemini_api_sends_the_key_in_the_header_only(tmp_path, monkeypatch):
    g = _gemini_module()
    key = tmp_path / "k"
    key.write_text("TEST-KEY-123\n")
    monkeypatch.setattr(g, "KEY_PATH", key)
    seen = {}

    class R:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok": 1}'

    def fake_open(req, timeout=None):
        seen["url"], seen["headers"] = req.full_url, dict(req.header_items())
        return R()

    monkeypatch.setattr(g._OPENER, "open", fake_open)
    assert g.api("POST", "/models/m:generateContent", {"a": 1}) == (200, {"ok": 1})
    assert "TEST-KEY" not in seen["url"] and seen["url"].startswith("https://generativelanguage.googleapis.com/")
    assert seen["headers"].get("X-goog-api-key") == "TEST-KEY-123"
    import urllib.error

    with pytest.raises(urllib.error.HTTPError):
        g._NoRedirect().redirect_request(type("Q", (), {"full_url": "u"})(), None, 302, "m", {},
                                         "https://evil.example/")


def test_gemini_run_handles_quota_and_falls_back(tmp_path, monkeypatch):
    g = _gemini_module()
    monkeypatch.setattr(g, "LADDERS", {"hard": ("gemini-3.1-pro-preview", "gemini-2.5-pro"),
                                       "main": ("gemini-3.1-pro-preview", "gemini-2.5-flash")})
    cfg = {"seed": 7, "paths": {"labels": str(tmp_path / "labels"), "outputs": str(tmp_path / "out"),
                                "interim": str(tmp_path / "interim")}, "llm": {"cache_dir": str(tmp_path / "llm")}}
    out = g.cache_dir(cfg)
    out.mkdir(parents=True)
    b1 = {"task": "memory", "prompt_version": "b1-gemini-v1", "schema": g.b1_schema()}
    items = [dict(b1, id="b1:a", group="A", tier="hard", messages=[{"role": "system", "content": "s"},
                                                                   {"role": "user", "content": "u1"}]),
             dict(b1, id="b1:b", group="B", tier="main", messages=[{"role": "system", "content": "s"},
                                                                   {"role": "user", "content": "u2"}]),
             dict(b1, id="b1:c", group="B", tier="main", messages=[{"role": "system", "content": "s"},
                                                                   {"role": "user", "content": "u3"}])]
    _write_jsonl(out / "requests.jsonl", items)
    ok = {"candidates": [{"content": {"parts": [{"text": "thinking", "thought": True},
                                                {"text": '{"label": "kept", "confidence": "high", "rationale": "x"}'}]},
                          "finishReason": "STOP"}], "modelVersion": "v"}
    per_day = {"error": {"details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
        {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier", "quotaValue": "1"}]}]}}
    per_min = {"error": {"details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [
        {"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "2s"}]}}
    script = {"gemini-3.1-pro-preview": [(429, per_day)],
              "gemini-2.5-pro": [(200, {"candidates": [{"content": {"parts": [{"text": "{not json"}]}}]}), (200, ok)],
              "gemini-2.5-flash": [(429, per_min), (200, ok), (429, per_day)]}
    calls, sleeps = [], []

    def fake_call(method, path, body):
        m = path.split("/models/")[1].split(":")[0]
        calls.append((m, body["generationConfig"]["seed"]))
        assert "key" not in json.dumps(body).lower()
        return script[m].pop(0)

    rc = g.run(cfg, call=fake_call, sleep=sleeps.append, log=lambda *_: None)
    assert rc == 3  # item c waits for the reset; a and b wait for an upgrade to 3.1 Pro
    assert calls == [("gemini-3.1-pro-preview", 7), ("gemini-2.5-pro", 7), ("gemini-2.5-pro", 8),
                     ("gemini-2.5-flash", 7), ("gemini-2.5-flash", 7), ("gemini-2.5-flash", 7)]
    assert 3.0 in sleeps  # retry delay of the per-minute limit plus one second
    quota = json.loads((out / "quota.json").read_text())
    assert set(quota) == {"gemini-3.1-pro-preview", "gemini-2.5-flash"}
    cache = [json.loads(x) for x in (out / "cache.jsonl").read_text().splitlines()]
    assert [(e["id"], e["model"], e["attempt"], e["valid"]) for e in cache] == [
        ("b1:a", "gemini-2.5-pro", 0, False), ("b1:a", "gemini-2.5-pro", 1, True),
        ("b1:b", "gemini-2.5-flash", 0, True)]
    assert all("TEST-KEY" not in json.dumps(e) for e in cache) and cache[1]["output"].startswith('{"label"')
    _, ans = g.final_answers(cfg)
    assert set(ans) == {"b1:a", "b1:b"} and ans["b1:a"]["model"] == "gemini-2.5-pro"
    assert ans["b1:b"]["model"] == "gemini-2.5-flash"
    # After the reset: the row without an answer first, then the fallback answers are upgraded to 3.1 Pro.
    (out / "quota.json").unlink()
    calls.clear()
    script["gemini-3.1-pro-preview"] = [(200, ok)] * 3
    assert g.run(cfg, call=fake_call, sleep=sleeps.append, log=lambda *_: None) == 0
    assert [c[0] for c in calls] == ["gemini-3.1-pro-preview"] * 3
    _, ans = g.final_answers(cfg)
    assert {k: v["model"] for k, v in ans.items()} == {k: "gemini-3.1-pro-preview" for k in ("b1:a", "b1:b", "b1:c")}
    assert g.run(cfg, call=fake_call, sleep=sleeps.append, log=lambda *_: None) == 0 and len(calls) == 3


def test_gemini_next_reset_is_midnight_pacific():
    from datetime import UTC, datetime

    g = _gemini_module()
    r = g.next_reset(datetime(2026, 10, 1, 20, 0, tzinfo=UTC))  # 13:00 PDT
    assert r == datetime(2026, 10, 2, 7, 5, tzinfo=UTC)


# --- validation of 2026-10-03: audit design, Claude's blind labels, loss detection --------------------

def test_loss_prf_by_hand():
    import numpy as np

    truth = ["dropped", "kept", "modified", "kept", "new"]
    pred = ["modified", "dropped", "kept", "kept", "dropped"]
    r = pre.loss_prf(np.ones((1, 5)), truth, pred)  # rows 0-3: TP 1 (row 0), FP 1 (row 1), FN 1 (row 2)
    assert (r["precision"][0], r["recall"][0], r["f1"][0]) == pytest.approx((0.5, 0.5, 0.5))
    a = pre.loss_prf(np.ones((1, 5)), truth, pred, at_risk_only=False)  # row 4 adds a false positive
    assert (a["precision"][0], a["recall"][0]) == pytest.approx((1 / 3, 0.5))
    W = pre.audit_weights(["a", "a", "b"], [1.0, 2.0, 3.0], 200, 1)
    assert W.shape == (201, 3) and list(W[0]) == [1.0, 2.0, 3.0]
    assert np.allclose(W[1:, 2], 3.0) and np.allclose(W[1:, :2].sum(axis=1) / 1.0 % 1, 0)  # b is one row


AUDIT = {0: ("A", 0.5), 2: ("B", 1.0), 3: ("B", 1.0), 4: ("C", 2 / 3), 8: ("C", 2 / 3)}
CLAUDE = {0: "dropped", 1: "modified", 2: "kept", 3: "modified", 4: "kept", 5: "kept", 8: "dropped"}


def _audit_setup(tmp_path):
    labels = tmp_path / "labels"
    labels.mkdir(exist_ok=True)
    (labels / pre.AUDIT_FILE).write_text(json.dumps({"seed": 1, "b1": {
        f"number|{i}|": {"stratum": s_, "p_audit": p_} for i, (s_, p_) in AUDIT.items()}}))
    with open(labels / pre.CLAUDE_LABELS_FILE, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["unit_key", "claude_label", "bad_unit", "confidence", "reason"])
        wr.writerows((f"number|{i}|", lab, int(i == 1), "high", "r") for i, lab in CLAUDE.items())
    v2 = [row[7] or "kept" for row in RECHECK_SHEET]
    for v, labs in (("v2", v2), ("v3", [row[3] for row in RECHECK_SHEET])):
        with open(labels / f"memory_pairs_rule_{v}.csv", "w", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(["pair_id", "unit_key", f"rule_label_{v}"])
            wr.writerows((i + 1, f"number|{i}|", lab) for i, lab in enumerate(labs))
    return labels


def test_audit_design_metrics_by_hand(tmp_path):
    _audit_setup(tmp_path)
    get, rows = _recheck_metrics(tmp_path, RECHECK_SHEET)
    assert [s_ for s_ in dict.fromkeys(r["scheme"] for r in rows)] == ["weighted", "unweighted", "weighted_owner71",
                                                                        "weighted_claude277"]
    # weights 1 / (inclusion x p_audit): rows 0, 2, 3, 4, 8 -> 2, 1, 1, 3, 3
    assert get[("weighted", "all", "accuracy")]["rule"] == pytest.approx(7 / 10)
    assert get[("weighted", "all", "accuracy")]["claude"] == pytest.approx(6 / 10)
    lw = get[("weighted", "loss", "f1")]
    assert lw["rule"] == pytest.approx(0.5) and lw["rule_v2"] == pytest.approx(1.0)
    assert lw["claude"] == pytest.approx(1.0)
    assert get[("weighted", "loss_all", "f1")]["claude"] == pytest.approx(2 * 3 / (6 + 3))  # row 8: truth new
    assert get[("weighted", "loss", "precision")]["rule"] == pytest.approx(1.0)
    assert get[("weighted", "loss", "recall")]["rule"] == pytest.approx(1 / 3)
    assert get[("unweighted", "all", "accuracy")]["rule"] == pytest.approx(3 / 5)
    assert get[("weighted_owner71", "all", "accuracy")]["rule"] == pytest.approx(8 / 10)
    c = get[("weighted_claude277", "all", "accuracy")]
    assert c["rule"] == pytest.approx(5 / 10) and c["claude"] == ""
    r = get[("weighted", "all", "accuracy")]
    assert r["rule_lo"] <= r["rule"] <= r["rule_hi"] and (r["n_labelled"], r["N_disagree"], r["N_agree"]) == (5, 4, 6)
    assert "Audit design: 5 of 5 audit rows labelled (A 1/1, B 2/2, C 2/2)" in r["note"]
    assert get[("weighted", "loss", "f1")]["pairs"]["v3_minus_v2"][0] == pytest.approx(-0.5)
    rec = pre.recommend_rule_set(rows)
    assert rec["best"] == "v2" and set(rec["f1"]) == {"v1", "v2", "v3"}
    assert rec["precision"]["v1"] == pytest.approx(1.0) and rec["recall"]["v1"] == pytest.approx(1 / 3)
    assert pre.recommend_rule_set(rows, "weighted_claude277")["best"] in ("v1", "v2", "v3")
    with open(tmp_path / "out" / "tables" / pre.METRICS_FILE, encoding="utf-8") as f:
        head = next(csv.reader(f))
    assert head[:len(pre.METRIC_COLUMNS)] == list(pre.METRIC_COLUMNS) and "claude" in head and "pairs" not in head
    text = pre.render_validation({"paths": {"labels": str(tmp_path / "labels")}}, rows, None)
    assert any("Rule-set recommendation" in x for x in text) and any("rules v2" in x for x in text)
    assert any("Loss precision: v1 1.00" in x and "Paired differences in loss F1" in x for x in text)


def test_claude_owner_agreement(tmp_path):
    labels = _audit_setup(tmp_path)
    _recheck_metrics(tmp_path, RECHECK_SHEET)
    a = pre.claude_owner_agreement({"seed": 1, "paths": {"labels": str(labels)}}, reps=50)
    assert a["n"] == 5 and a["unweighted"] == pytest.approx(0.6) and a["w_all"][0] == pytest.approx(0.6)
    assert a["w_blind"][0] == pytest.approx(4.5 / 7) and a["w_all_coarse"][0] == pytest.approx(0.7)
    assert a["by_stratum"] == {"A": (1, 1), "B": (1, 2), "C": (1, 2)} and a["bad_unit"] == (1, 7)
    assert a["confusion"][("dropped", "modified")] == 1 and a["confusion"][("new", "dropped")] == 1
    lines = pre.render_validation({"paths": {"labels": str(labels)}}, [], a)
    assert any("Claude's blind labels against the owner's" in x for x in lines)


def test_import_claude_labels(tmp_path):
    labels = tmp_path / "labels"
    (labels / "claude_blind").mkdir(parents=True)
    with open(labels / "memory_pairs_blind.csv", "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["pair_id", "unit_key", "human_label"])
        wr.writerows([(1, "number|1|", ""), (2, "org|x|", "")])
    parts = ((1, [(1, "org|x|", "Kept", 1, "high", "r1")]), (2, [(0, "number|1|", "modified", 0, "low", "r0")]))
    for k, rows_ in parts:
        with open(labels / "claude_blind" / f"b1_part{k}.csv", "w", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(["row_index", "unit_key", "claude_label", "bad_unit", "confidence", "reason"])
            wr.writerows(rows_)
    info = pre.import_claude_labels({"paths": {"labels": str(labels)}}, log=lambda *_: None)
    assert info["rows"] == 2 and info["in_blind_sheet"] == 2 and info["bad_unit"] == 1
    out = labels / pre.CLAUDE_LABELS_FILE
    assert out.stat().st_mode & 0o077 == 0
    with open(out, encoding="utf-8") as f:
        got = list(csv.DictReader(f))
    assert [(r["unit_key"], r["claude_label"]) for r in got] == [("number|1|", "modified"), ("org|x|", "kept")]
    assert list(got[0]) == ["unit_key", "claude_label", "bad_unit", "confidence", "reason"]
    with open(labels / "claude_blind" / "b1_part3.csv", "w", newline="") as f:
        f.write("row_index,unit_key,claude_label,bad_unit,confidence,reason\n5,org|x|,kept,0,high,dup\n")
    with pytest.raises(SystemExit):
        pre.import_claude_labels({"paths": {"labels": str(labels)}}, log=lambda *_: None)
