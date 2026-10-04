"""LLM pre-labels for the module B1 validation set (SPEC 6.3.4, 3.4).

SPEC 6.3.4: the owner labels the state of 500 fact units in 100 adjacent memory
version pairs (`data/labels/memory_pairs.csv`, appendix C), and "the LLM
pre-labels, then the user reviews". The owner chose on 2026-10-01 a local
open-weight model on one GPU node and no paid API (decisions "No paid LLM
API"); the model only runs inference (SPEC 0.2).

Stages (`python -m avsd.lineage.prelabel <stage>`, scripts/prelabel_memory.sbatch):

1. prepare (project env, CPU). A pair is a consolidation: PREV is its input row
   (`prev_uid`), NEXT its output (`next_uid`). The B1 anchor extractor
   (`avsd.lineage.anchors`; same salt, agent names and spaCy model) is re-run on
   the full text of both, line by line as in `avsd.lineage.memory`, keeping
   character spans. An occurrence matches the unit key when its type and its
   displayed value (`display_value`, so hashes for PERSON, email, phone and
   values on credential lines) are equal, and, for quantities, its context
   lemma or that lemma's keyed hash equals the key's context. This recovers
   the raw value. Each version then gets up to MAX_WINDOWS windows of about
   WINDOW_CHARS characters, seeded in this order: the unit's occurrences
   (value marked ⟦ ⟧); if there are none, literal matches of the value's
   surface text (quantities only next to their context word); other values of
   the same type in one of the unit's contexts (marked ⟨ ⟩, the evidence for
   "modified"); if all are empty, the context word itself. Snapshots often
   repeat a passage, so a window with the same text as one already shown is
   skipped. A unit with rule label "restored" also gets one window from the most
   recent earlier live row that held it (B1's presence spells in
   memory_facts.parquet; a short backward scan if no spell matches).
   Credential-like strings are masked («masked») before any text is written.
   Writes requests.jsonl.
2. infer (separate vLLM env, GPUs of one node; `--model`, MODELS). The prompt
   quotes the B1 state definitions, gives a three-step decision procedure and
   states, for each version, how many value matches and context values it holds
   (the rule label itself is not shown). Qwen3-14B (scripts/prelabel_memory.sbatch):
   thinking disabled, greedy decoding (temperature 0, fixed seed), JSON-schema
   structured output. The owner then asked (2026-10-01) for a re-check by two
   stronger models (scripts/prelabel_strong.sbatch): Qwen3.5-122B-A10B-FP8
   (thinking, tensor parallel 4, text only) and gpt-oss-120b (reasoning effort
   high, tensor parallel 2), each on the same cached requests, with the
   sampling of its model card and a vLLM reasoning parser so that the JSON
   schema applies to the final answer only; an answer that does not validate
   is retried once with a larger token budget. Each attempt is cached under a
   key over model, revision, messages, chat-template switches, sampling,
   schema and reasoning parser, with the rendered prompt and the raw output
   (SPEC 3.4), so a rerun generates nothing. This stage needs only the
   standard library, PyYAML (config) and vLLM.
3. report (project env). The review sheet (UTF-8 with BOM, one row per unit),
   its README in Chinese, data/labels/memory_pairs_llm_labels.csv and
   outputs/qa/memory_prelabel.md (aggregates only: the Qwen3-14B run, the
   agreement of the three LLMs and rule sets v1-v3 with kappa intervals,
   confusion matrices, overturns of Qwen3-14B by the strong-model consensus,
   the third-judge check of scripts/prelabel_adjudicate.py and the design).
   Review design (`review_design`): units where the two strong models disagree
   (A) or agree against any rule version (B) are priority 1-必标 with inclusion
   probability 1; a random sample of the rest (C, everyone agrees), stratified
   by label with proportional allocation, is 2-抽样 with probability n/N, so
   about REVIEW_TARGET rows are labelled. The sheet shows the strong models'
   labels and their agreed suggestion, not the rule or Qwen3-14B labels; it is
   sorted by priority and keeps any human_label and notes already filled.
4. metrics. `compute_label_metrics` scores rule sets v1, v2, v3 (every
   data/labels/memory_pairs_rule_v<K>.csv present), Qwen3-14B and the two
   strong models against the owner's human_label (only filled rows count):
   design-weighted (1 / inclusion probability, adjusted within strata for
   unlabelled rows) with pair-bootstrap 95% intervals and paired differences
   against v1, and unweighted for reference. It also reads sheets of the first
   (Qwen3-14B) design. Writes outputs/tables/memory_label_metrics.csv.

Privacy (SPEC 0.2): memory text holds names, emails, phone numbers and some
unredacted credentials. Raw text goes only to data/ (requests, cache, review
sheet; files are created with mode 600). Credential-like strings are masked in
everything this module writes, using the token, assignment, URL-userinfo and
bearer patterns of scripts/scan_credentials.py plus PIN and one-time-code
phrasing, and secret-looking tokens on lines that B1 treats as sensitive.
Logs and outputs/ hold counts only.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

LABELS: tuple[str, ...] = ("kept", "modified", "dropped", "new", "restored")
CONFIDENCES: tuple[str, ...] = ("low", "medium", "high")
MODEL_ID = "Qwen/Qwen3-14B"
MODEL_REVISION = "40c069824f4251a91eefaf281ebe4c544efd3e18"  # Apache-2.0
PROMPT_VERSION = "b1-prelabel-v4"
WINDOW_CHARS = 300
MAX_WINDOWS = 3
MAX_MERGED_CHARS = 2 * WINDOW_CHARS
RATIONALE_WORDS = 25
MAX_TOKENS = 256
EARLIER_SCAN_ROWS = 40  # backward scan when no presence spell matches a restored unit
MASK = "«masked»"
OPEN = {"value": "⟦", "ctx": "⟨"}
CLOSE = {"value": "⟧", "ctx": "⟩"}
NEWLINE = " ↵ "
CACHE_SUBDIR = "memory_prelabel"
PAIRS_FILE = "memory_pairs.csv"
REVIEW_FILE = "memory_pairs_review.csv"
README_FILE = "memory_pairs_review_README.md"
METRICS_FILE = "memory_label_metrics.csv"
QA_FILE = "memory_prelabel.md"
RULE_V2_FILE = "memory_pairs_rule_v2.csv"  # pair_id, unit_key, rule_label_v2 (revised B1 rules)
# Sheet of the Qwen3-14B design (2026-10-01 morning; backed up as BACKUP_FILE). compute_label_metrics
# still reads sheets in this format (rule and Qwen3-14B labels in the sheet, no design columns).
REVIEW_COLUMNS: tuple[str, ...] = (
    "review_priority", "pair_id", "agent", "unit_type", "value", "context_key", "prev_excerpt",
    "next_excerpt", "earlier_excerpt", "rule_label", "llm_label", "llm_confidence", "llm_rationale",
    "human_label", "notes", "unit_key",
)
# Sheet of the re-check design: the two strong models' labels and their suggestion; rule labels and
# the Qwen3-14B label are not shown (they are what the owner's labels evaluate) and are joined by
# unit from memory_pairs.csv, memory_pairs_rule_v<K>.csv and LLM_LABELS_FILE.
SHEET_COLUMNS: tuple[str, ...] = (
    "review_priority", "pair_id", "agent", "unit_type", "value", "context_key", "prev_excerpt",
    "next_excerpt", "earlier_excerpt", "suggested_label", "qwen35_label", "qwen35_confidence",
    "qwen35_rationale", "gptoss_label", "gptoss_confidence", "gptoss_rationale", "human_label", "notes",
    "design_stratum", "inclusion_prob", "unit_key",
)
BACKUP_FILE = "memory_pairs_review_qwen14b.csv"
LLM_LABELS_FILE = "memory_pairs_llm_labels.csv"  # pair_id, unit_key, one label column per model
ADJUDICATION_FILE = "memory_pairs_adjudication.csv"  # third-judge labels on a sample of disagreements
PRIORITIES: tuple[str, ...] = ("1-必标", "2-抽样", "3-可选")
SAMPLE_SIZE = 60  # agreement rows in the random sample (priority 2, Qwen3-14B design)
STRATA: tuple[str, ...] = ("disagree", "agree")
REVIEW_TARGET = 250  # rows to label in the re-check design (certainty rows plus the sample)
MIN_SAMPLE = 30  # smallest random sample of the all-agree rows
# Design strata of the re-check design: A and B are labelled in full (inclusion probability 1),
# C:<label> are the all-agree rows by suggested label, sampled with proportional allocation.
STRATUM_A = "A"  # the two strong models disagree (or one has no valid answer)
STRATUM_B = "B"  # they agree, and at least one rule version (v1, v2, v3) says otherwise
STRATUM_C = "C"  # they agree with each other and with every rule version
ADJ_PER_STRATUM = 25  # third-judge sample per disagreement stratum
GEMINI_LABELS_FILE = "memory_pairs_gemini.csv"  # Gemini rater (scripts/gemini_label.py), private
# Validation of 2026-10-03: the owner labels a stratified random audit of the blind sheet (AUDIT_FILE) and
# Claude blind-labels every row of it (CLAUDE_BLIND_GLOB, gathered into CLAUDE_LABELS_FILE).
AUDIT_FILE = "audit_sample.json"  # {"b1": {unit_key: {stratum, p_audit}}, ...}
CLAUDE_BLIND_GLOB = "claude_blind/b1_part*.csv"
CLAUDE_LABELS_FILE = "memory_pairs_claude.csv"
LOSS_LABELS: tuple[str, ...] = ("dropped", "modified")  # the event of the B1 hazards
BOOT_REPS = 2000
NO_LABEL = "(none)"
OUTPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": list(LABELS)},
        "confidence": {"type": "string", "enum": list(CONFIDENCES)},
        "rationale": {"type": "string"},
    },
    "required": ["label", "confidence", "rationale"],
    "additionalProperties": False,
}
TYPE_GLOSS: dict[str, str] = {
    "url": "a web address", "email": "an email address", "phone": "a phone number",
    "date": "a calendar date or a village day number", "time": "a time of day",
    "money": "an amount of money", "percent": "a percentage", "number": "a count or other number",
    "agent": "the name of an AI agent", "person": "a person's name", "org": "an organisation",
    "gpe": "a country, state or city", "product": "a product", "event": "a named event",
    "work_of_art": "a title of a work (book, article, song, ...)",
}
QUANTITY = frozenset({"time", "money", "percent", "number"})  # == anchors.QUANTITY_TYPES (tested)


@dataclass(frozen=True)
class ModelSpec:
    """A local open-weight labelling model (inference only) with its serving and decoding settings.

    reasoning: "" (the answer only), "think" (Qwen: <think> ... </think>, then the answer) or
    "harmony" (gpt-oss: analysis channel, then the final channel). With a reasoning parser, vLLM
    applies the JSON schema only after the reasoning ends. budgets: max new tokens of the first
    attempt and of each retry (a retry also moves the seed by one); a request is retried only when
    no earlier attempt gave an answer that validates against OUTPUT_SCHEMA.
    """

    key: str  # file names and sheet columns
    name: str
    model_id: str
    revision: str
    license: str
    dir_name: str  # weights in ~/models/<dir_name>
    size_gb: float
    tensor_parallel: int = 1
    dtype: str = "auto"
    reasoning: str = ""
    reasoning_parser: str = ""
    template_kwargs: tuple[tuple[str, object], ...] = ()
    temperature: float = 0.0
    top_p: float = 1.0
    top_k: int = 0  # 0: off
    min_p: float = 0.0
    presence_penalty: float = 0.0
    budgets: tuple[int, ...] = (MAX_TOKENS,)
    text_only: bool = False  # image-text models: load the language model only
    exclude: tuple[str, ...] = ()  # repository files not downloaded
    max_model_len: int = 8192
    prefix_caching: bool = True
    # vLLM 0.19 sizes the KV cache without the CUDA-graph memory, and the graph capture of both
    # re-check models then ran out of memory on 48 GB GPUs; all runs use eager mode.
    enforce_eager: bool = True
    gpu_memory_utilization: float = 0.90
    note: str = ""


QWEN3_14B = ModelSpec(
    key="qwen3_14b", name="Qwen3-14B", model_id=MODEL_ID, revision=MODEL_REVISION, license="Apache-2.0",
    dir_name="Qwen3-14B", size_gb=29.5, dtype="bfloat16", template_kwargs=(("enable_thinking", False),),
    note="thinking disabled, greedy")
# The two re-check models (owner's approval 2026-10-01). Sampling follows each model card: Qwen3.5
# thinking mode for precise tasks (no presence penalty, which would also push the final label away
# from labels named in the reasoning); gpt-oss temperature 1 and top_p 1 with reasoning effort high.
QWEN35_122B = ModelSpec(
    key="qwen35_122b", name="Qwen3.5-122B-A10B-FP8", model_id="Qwen/Qwen3.5-122B-A10B-FP8",
    revision="a099dee70ccfcd8d5dda56aaa0b60cb8ecadabc9", license="Apache-2.0",
    dir_name="Qwen3.5-122B-A10B-FP8", size_gb=127.2, tensor_parallel=4, reasoning="think",
    reasoning_parser="qwen3", template_kwargs=(("enable_thinking", True),), temperature=0.6, top_p=0.95,
    top_k=20, budgets=(8192, 32768), text_only=True, max_model_len=36864, prefix_caching=False,
    gpu_memory_utilization=0.92, note="thinking on, text only")
GPT_OSS_120B = ModelSpec(
    key="gptoss_120b", name="gpt-oss-120b", model_id="openai/gpt-oss-120b",
    revision="b5c939de8f754692c1647ca79fbf85e8c1e70f8a", license="Apache-2.0", dir_name="gpt-oss-120b",
    size_gb=65.3, tensor_parallel=2, reasoning="harmony", reasoning_parser="openai_gptoss",
    template_kwargs=(("reasoning_effort", "high"),), temperature=1.0, top_p=1.0, budgets=(8192, 32768),
    exclude=("original/*", "metal/*"), max_model_len=36864, gpu_memory_utilization=0.92,
    note="reasoning effort high")
MODELS: dict[str, ModelSpec] = {m.key: m for m in (QWEN3_14B, QWEN35_122B, GPT_OSS_120B)}
STRONG: tuple[str, ...] = (QWEN35_122B.key, GPT_OSS_120B.key)  # the re-check pair

SYSTEM_PROMPT = (
    "You annotate how one fact changes when an AI agent rewrites its memory notes. "
    "Reply with one JSON object and nothing else."
)
# The first two definition lines are quoted from avsd.lineage.memory (module docstring);
# "new" is the pair label of avsd.lineage.chains for a unit absent from the input.
DEFINITIONS = (
    "- Fact unit: (anchor type, normalised value or keyed hash, context key); the context key is part "
    "of the identity only for quantities (number, money, percent, time).\n"
    "- State: kept (in the output), modified (absent, but one of its contexts holds a value the previous "
    "version did not hold), dropped (absent otherwise), restored (back after a loss).\n"
    "- new: absent from the input, in the output, and never lost before."
)
EXCERPT_NOTE = (
    "Each version is shown as up to three windows of about 300 characters, first around the places where "
    "the unit's value was found (marked ⟦ ⟧), then around other values in the unit's context (marked ⟨ ⟩). "
    "The header of each version says how often the unit's value occurs in the full version and how many "
    "other values its context holds, shown or not. … marks cut text, ↵ a line break and «masked» a hidden "
    "credential."
)
# Prompt history (all outputs stay cached). v1 left presence to the model, which often called the
# value that replaced an old one "modified". v2 added this procedure with the rationale first; the
# model then claimed presence in versions without a match. v3 put the match counts in the headers.
# A comparison of three variants on all 500 units (rationale first or label first, counts as numbers
# or as a sentence) chose label first with a sentence (agreement with the marks 458/500 against
# 425-435). v4 also stops asking whether PREV already had the new value: B1 compares with the
# previous rewrite's output, and an update often arrives in the notes appended to PREV.
PROCEDURE = (
    "1. Is the unit in PREV? Yes if PREV has a ⟦ ⟧ match that is the unit's value used for the same thing; "
    "for a quantity it must also belong to the unit's context (\"56 donors\" and \"56 days\" are different "
    "units). If the header says the value does not occur, the answer is no, unless an excerpt states the "
    "same value in another format (\"3 pm\" for \"15:00\"). ⟨ ⟩ values are different values and never count.\n"
    "2. Is the unit in NEXT? The same test on NEXT.\n"
    "3. Choose the label:\n"
    "- in PREV and in NEXT: kept.\n"
    "- in PREV, not in NEXT: modified if NEXT gives another value for the same thing (an update, usually "
    "one of the ⟨ ⟩ values), otherwise dropped.\n"
    "- not in PREV, in NEXT: restored if the EARLIER excerpt shows the unit, otherwise new. This holds even "
    "when the value replaced an older one: only the replaced value is modified.\n"
    "- in neither: the label that fits best, with low confidence.\n"
    "Confidence: high if the excerpts settle the question, medium if some doubt remains (another format, an "
    "unclear context), low if they do not settle it."
)


# --- small helpers (standard library only; the infer stage runs in the vLLM env) ---------------

def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _private_open(path: Path, mode: str = "w", **kw):
    """Open a file for writing with mode 600 (it holds memory text)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if "a" in mode else os.O_TRUNC)
    fd = os.open(path, flags, 0o600)
    os.chmod(path, 0o600)
    return os.fdopen(fd, mode, **kw)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # a line cut by a killed job
    return out


def cache_dir(cfg: dict) -> Path:
    """data/interim/llm_cache/memory_prelabel (llm.cache_dir from the config, SPEC 3.4)."""
    from avsd.config import REPO_ROOT

    base = cfg.get("llm", {}).get("cache_dir")
    root = (REPO_ROOT / base) if base else Path(cfg["paths"]["interim"]) / "llm_cache"
    return Path(root).resolve() / CACHE_SUBDIR


def sampling_params(seed: int) -> dict:
    return {"temperature": 0.0, "max_tokens": MAX_TOKENS, "seed": int(seed)}


def request_key(messages: list[dict], seed: int, model_id: str = MODEL_ID,
                revision: str = MODEL_REVISION) -> str:
    """Cache key of the Qwen3-14B request (`model_request_key` of QWEN3_14B)."""
    blob = json.dumps({
        "model": model_id, "revision": revision, "messages": messages,
        "chat_template_kwargs": {"enable_thinking": False}, "sampling": sampling_params(seed),
        "schema": OUTPUT_SCHEMA,
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def model_sampling(spec: ModelSpec, seed: int, attempt: int = 0) -> dict:
    """Sampling parameters of one attempt (part of the cache key); a retry moves the seed by one and
    uses the next token budget. Parameters at their vLLM default are left out, so the Qwen3-14B
    key equals `request_key`."""
    s = {"temperature": float(spec.temperature),
         "max_tokens": int(spec.budgets[min(attempt, len(spec.budgets) - 1)]), "seed": int(seed) + attempt}
    for k, v, default in (("top_p", spec.top_p, 1.0), ("top_k", spec.top_k, 0), ("min_p", spec.min_p, 0.0),
                          ("presence_penalty", spec.presence_penalty, 0.0)):
        if v != default:
            s[k] = v
    return s


def model_request_key(spec: ModelSpec, messages: list[dict], seed: int, attempt: int = 0,
                      task: LabelTask | None = None) -> str:
    """Cache key: model, revision, messages, chat-template switches, sampling, schema, (for a
    reasoning model) the reasoning parser after which the schema applies and, for a task that asks
    for it, the prompt version. task None is B1."""
    blob = {"model": spec.model_id, "revision": spec.revision, "messages": messages,
            "chat_template_kwargs": dict(spec.template_kwargs), "sampling": model_sampling(spec, seed, attempt),
            "schema": OUTPUT_SCHEMA if task is None else task.schema}
    if spec.reasoning_parser:
        blob["reasoning_parser"] = spec.reasoning_parser
    if task is not None and task.key_prompt_version:
        blob["prompt_version"] = task.prompt_version
    return hashlib.sha256(json.dumps(blob, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def cache_file(spec: ModelSpec) -> str:
    """Cache file of one model in the cache dir (Qwen3-14B keeps the original cache.jsonl)."""
    return "cache.jsonl" if spec.key == QWEN3_14B.key else f"cache_{spec.key}.jsonl"


def runs_file(spec: ModelSpec) -> str:
    return "runs.jsonl" if spec.key == QWEN3_14B.key else f"runs_{spec.key}.jsonl"


_HARMONY_FINAL = "<|channel|>final"
_HARMONY_MESSAGE = "<|message|>"
_END_MARKS = ("<|return|>", "<|end|>", "<|call|>", "<|im_end|>", "<|endoftext|>")


def split_answer(text: str | None, reasoning: str = "") -> tuple[str, bool]:
    """The final answer of one model output and whether the model got to it.

    think: the text after the last </think>; harmony: the message of the final channel (gpt-oss, decoded
    with special tokens; the header may carry a constraint, "<|channel|>final<|constrain|>json<|message|>");
    otherwise the whole output."""
    text = text or ""
    if reasoning == "think":
        if "</think>" not in text:
            return "", False
        ans = text.rsplit("</think>", 1)[1]
    elif reasoning == "harmony":
        k = text.rfind(_HARMONY_FINAL)
        m = text.find(_HARMONY_MESSAGE, k) if k >= 0 else -1
        if k < 0 or m < 0 or "<|end|>" in text[k:m] or m - k > 80:
            return "", False
        ans = text[m + len(_HARMONY_MESSAGE):]
    else:
        ans = text
    for mark in _END_MARKS:
        ans = ans.split(mark, 1)[0]
    return ans.strip(), True


def schema_ok(answer: str) -> bool:
    """The answer is exactly one JSON object that validates against OUTPUT_SCHEMA."""
    try:
        obj = json.loads(answer)
    except (json.JSONDecodeError, TypeError):
        return False
    return (isinstance(obj, dict) and set(obj) == set(OUTPUT_SCHEMA["required"])
            and obj["label"] in LABELS and obj["confidence"] in CONFIDENCES and isinstance(obj["rationale"], str))


def parse_answer(text: str | None, reasoning: str = "") -> dict:
    """`parse_model_output` of the final answer, plus schema_ok (strict) and finished (the model
    left its reasoning). An unfinished reasoning output has error 'no_answer'."""
    ans, finished = split_answer(text, reasoning)
    if not finished:
        res = parse_model_output(None)
        res["error"] = "no_answer"
    else:
        res = parse_model_output(ans)
    res["schema_ok"] = finished and schema_ok(ans)
    res["finished"] = finished
    return res


@dataclass(frozen=True)
class LabelTask:
    """A pre-label task other than B1 for the infer stage: the output schema, a check of the final
    answer against its request, and the prompt version (written with every cached output). B1 is
    task None; `avsd.lineage.prelabel_parents.PARENT_TASK` is module B2's parent sheet."""

    name: str
    schema: dict
    prompt_version: str
    check: object  # (answer text, request dict) -> True when the answer validates
    key_prompt_version: bool = False  # the cache key includes the prompt version


def answer_ok(spec: ModelSpec, output: str | None, task: LabelTask | None = None, req: dict | None = None) -> bool:
    """The model's final answer validates (B1: `parse_answer`'s strict schema check; else task.check)."""
    if task is None:
        return parse_answer(output, spec.reasoning)["schema_ok"]
    ans, finished = split_answer(output, spec.reasoning)
    return finished and bool(task.check(ans, req or {}))


# --- credential masking -----------------------------------------------------------------------

# Token formats and assignments follow scripts/scan_credentials.py; thresholds are lower,
# because masking a harmless string costs little here.
_B = r"(?<![A-Za-z0-9_-])"
_TOKEN_PATTERNS = (
    r"sk-ant-[A-Za-z0-9_-]{20,}",
    r"sk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{20,}",
    r"gh[pousr]_[A-Za-z0-9]{20,}",
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"gl(?:pat|dt|rt|cbt|ptt|ft|imt|agent)-[A-Za-z0-9_-]{20,}",
    r"(?:AKIA|ASIA)[0-9A-Z]{16}(?![0-9A-Z])",
    r"AIza[0-9A-Za-z_-]{35}",
    r"ya29\.[0-9A-Za-z_-]{20,}",
    r"xox[abposr]-[A-Za-z0-9-]{10,}",
    r"hf_[A-Za-z0-9]{30,}",
    r"npm_[A-Za-z0-9]{36}",
    r"nfp_[A-Za-z0-9]{30,}",
    r"(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}",
    r"SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}",
    r"\d{8,10}:AA[A-Za-z0-9_-]{33}",
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
)
_TOKEN_RE = re.compile(_B + "(?:" + "|".join(_TOKEN_PATTERNS) + ")")
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----(?:(?!-----END)[\s\S]){0,6000}"
    r"(?:-----END (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----)?"
)
_KEYS = (
    r"app[ _-]?passwords?|passwords?|passwd|passphrase|passcodes?|pwd|secret[ _-]?key|client[ _-]?secret"
    r"|secret|api[ _-]?key|apikey|access[ _-]?key|access[ _-]?token|auth[ _-]?token|refresh[ _-]?token"
    r"|bearer[ _-]?token|token|private[ _-]?key|security[ _-]?answer|recovery[ _-]?codes?|backup[ _-]?codes?"
)
_Q = r"[\\\"'`*]*"
_VAL = r"[^\s\"'`,;()\[\]{}<>\\|]"
_ASSIGN_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:" + _KEYS + r")(?![A-Za-z0-9_])" + _Q + r"\s*(?:=|:|=>|->)\s*" + _Q
    + r"(?P<val>" + _VAL + r"{3,128})"
)
_ASSIGN_IS_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:(?:app[ _-]?)?passwords?|passwd|passphrase|passcodes?|pwd|pin)(?![A-Za-z0-9_])"
    + _Q + r"\s+(?:is|was)\s+" + _Q + r"(?P<val>" + _VAL + r"{3,128})"
)
# PINs, one-time codes and account-like numbers: "PIN: 4821", "OTP 123456", "card number 4111 1111 ...".
_CODE_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:pins?|pin[ _-]?codes?|passcodes?|otp|2fa[ _-]?codes?|mfa[ _-]?codes?"
    r"|verification[ _-]?codes?|security[ _-]?codes?|one[ _-]time[ _-](?:codes?|passwords?)|cvv|cvc"
    r"|card[ _-]?numbers?|credit[ _-]?card(?:[ _-]?numbers?)?|account[ _-]?numbers?|routing[ _-]?numbers?"
    r"|iban|ssn|social[ _-]security(?:[ _-]numbers?)?)(?![A-Za-z0-9_])[^A-Za-z0-9\n]{0,4}(?:is\s+)?"
    r"(?P<val>[A-Za-z]{0,2}\d[\d -]{2,32}\d)"
)
_URLCRED_RE = re.compile(
    r"(?i)\b[a-z][a-z0-9+.-]{1,15}://[^\s:/@\"'`\\]{1,64}:(?P<val>[^\s@/\"'`\\]{3,128})@[A-Za-z0-9.-]+"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+(?P<val>[A-Za-z0-9._~+/-]{16,}=*)")
_URL_PARAM_RE = re.compile(
    r"(?i)[?&](?:key|api[_-]?key|token|access[_-]?token|auth|secret|password|pwd|sig|signature)"
    r"=(?P<val>[^&\s#\"'`<>]{6,})"
)
_STOP = frozenset({
    "required", "provided", "unknown", "none", "null", "hidden", "stored", "saved", "needed", "sent",
    "incorrect", "correct", "changed", "reset", "updated", "protected", "encrypted", "masked", "redacted",
    "available", "missing", "same", "true", "false", "undefined", "empty", "invalid", "valid", "expired",
    "removed", "n/a", "tbd", "todo", "pending", "generated", "configured", "included", "shown", "below",
    "above", "here", "there", "field", "input", "prompt", "login", "manager", "vault", "keychain", "not",
    "set", "unset", "known", "the", "and", "for", "being", "still", "also", "now", "already", "yes", "no",
})
# Lines on which bare numbers and mixed tokens are secrets: anchors.CRED_LINE without the
# account words (login, username, credentials), which only flag identifiers.
_STRONG_LINE_RE = re.compile(
    r"(?i)\b(?:pass(?:word|wd|code|phrase)s?|pwd|pins?|pin\s?codes?|secrets?|api[\s_\-]?keys?"
    r"|access[\s_\-]?keys?|private[\s_\-]?keys?|ssh[\s_\-]?keys?"
    r"|(?:auth|access|api|bearer|refresh|github|gitlab|personal)[\s_\-]?tokens?|tokens?\s*[:=]"
    r"|2fa|mfa|otp|one[\s\-]time\s(?:code|password)|security\s(?:code|answer|question)s?"
    r"|verification\scodes?|backup\scodes?|recovery\scodes?|ssn|social\ssecurity|card\snumbers?"
    r"|credit\scards?|cvv|routing\snumbers?|account\snumbers?|iban)\b"
)
_WORD_RE = re.compile(r"[^\s\"'`,;()\[\]{}<>|]+")
_EDGE = "*_`'\".,:;!?()[]{}<>|-#"
_DATE_TIME_RE = re.compile(r"(?i)\d{1,4}[-/.]\d{1,2}(?:[-/.]\d{1,4})?|\d{1,2}:\d{2}(?::\d{2})?(?:[ap]m)?")


def _secret_like(tok: str, strong: bool) -> bool:
    """A token on a sensitive line that may be a secret (strong: the line names a secret)."""
    if MASK in tok or len(tok) < 4 or len(tok) > 300:
        return False
    if "://" in tok or tok.lower().startswith("www.") or _DATE_TIME_RE.fullmatch(tok):
        return False
    if "@" in tok and "." in tok.rsplit("@", 1)[-1]:
        return False  # an email address identifies an account, it is not a secret
    digits = sum(c.isdigit() for c in tok)
    alpha = sum(c.isalpha() for c in tok)
    if tok.isdigit():
        return strong and 4 <= len(tok) <= 19
    if strong:
        special = any(c in "!#$%^&*+=?~@" for c in tok)
        return len(tok) >= 6 and ((digits > 0 and alpha > 0) or (special and digits + alpha > 0))
    return len(tok) >= 8 and digits >= 2 and alpha >= 2


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    for s, e in sorted(spans):
        if e <= s:
            continue
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def credential_spans(text: str, sensitive_lines: list[bool] | None = None) -> list[tuple[int, int]]:
    """Character spans of credential-like strings in `text` (merged, sorted).

    sensitive_lines: one flag per line of text.split('\\n') (B1's heading rule); without it only
    the line's own wording counts.
    """
    spans: list[tuple[int, int]] = []
    for m in _TOKEN_RE.finditer(text):
        spans.append(m.span())
    for m in _PRIVATE_KEY_RE.finditer(text):
        spans.append(m.span())
    for rx in (_ASSIGN_RE, _ASSIGN_IS_RE):
        for m in rx.finditer(text):
            v = m.group("val")
            core = v.strip(_EDGE)
            if not core or core.lower() in _STOP or MASK in v:
                continue
            spans.append(m.span("val"))
    for rx in (_CODE_RE, _URLCRED_RE, _BEARER_RE, _URL_PARAM_RE):
        for m in rx.finditer(text):
            spans.append(m.span("val"))
    pos = 0
    lines = text.split("\n")
    for i, line in enumerate(lines):
        strong = bool(_STRONG_LINE_RE.search(line))
        sens = strong or (sensitive_lines[i] if sensitive_lines is not None and i < len(sensitive_lines)
                          else False)
        if sens:
            for m in _WORD_RE.finditer(line):
                tok = m.group(0)
                core = tok.strip(_EDGE)
                if core and _secret_like(core, strong):
                    a = m.start() + tok.find(core)
                    spans.append((pos + a, pos + a + len(core)))
        pos += len(line) + 1
    return _merge(spans)


def mask_text(text: str, sensitive_lines: list[bool] | None = None) -> str:
    """`text` with every credential-like span replaced by MASK."""
    out, last = [], 0
    for s, e in credential_spans(text, sensitive_lines):
        out.append(text[last:s])
        out.append(MASK)
        last = e
    out.append(text[last:])
    return "".join(out)


# --- windows and excerpts -----------------------------------------------------------------------

@dataclass(frozen=True)
class Mark:
    start: int
    end: int
    kind: str  # "value" (⟦ ⟧), "ctx" (⟨ ⟩) or "" (window seed without a marker)


def _overlap(a0: int, a1: int, b0: int, b1: int) -> bool:
    return a0 < b1 and b0 < a1


def _snap(text: str, a: int, b: int, marks: list[Mark], slack: int = 25) -> tuple[int, int]:
    """Move window edges to whitespace (so words are not cut) without cutting a mark."""
    if a > 0 and not text[a - 1].isspace():
        m = re.search(r"\s", text[a:min(len(text), a + slack)])
        if m:
            a += m.end()
    if b < len(text) and not text[b].isspace():
        seg = text[max(a, b - slack):b]
        k = max(seg.rfind(" "), seg.rfind("\n"), seg.rfind("\t"))
        if k >= 0:
            b = max(a, b - slack) + k
    for mk in marks:  # never cut a mark
        if mk.start < a < mk.end:
            a = mk.start
        if mk.start < b < mk.end:
            b = mk.end
    return a, b


def render_window(text: str, a: int, b: int, marks: list[Mark], masks: list[tuple[int, int]]) -> str:
    """text[a:b] with value and context markers, masked spans and visible line breaks.

    A mark that overlaps a masked span grows to cover it, so a hidden value reads ⟦«masked»⟧.
    """
    mk = [(max(a, s), min(b, e)) for s, e in masks if e > a and s < b]
    grown: dict[tuple[int, int], str] = {}
    for m in marks:
        if not m.kind or m.end <= a or m.start >= b:
            continue
        s, e = m.start, m.end
        for ms_, me_ in mk:
            if _overlap(s, e, ms_, me_):
                s, e = min(s, ms_), max(e, me_)
        if grown.get((s, e)) != "value":  # one marker per span, value wins
            grown[(s, e)] = m.kind
    ms = [Mark(s, e, k) for (s, e), k in sorted(grown.items())]
    ms = [m for i, m in enumerate(ms) if not any(_overlap(m.start, m.end, o.start, o.end) for o in ms[:i])]
    pts = sorted({a, b, *(p for m in ms for p in (max(a, m.start), min(b, m.end))),
                  *(p for s, e in mk for p in (s, e))})
    out: list[str] = []
    for i in range(len(pts) - 1):
        p, q = pts[i], pts[i + 1]
        for m in ms:
            if min(b, m.end) == p and max(a, m.start) < p:
                out.append(CLOSE[m.kind])
        for m in ms:
            if max(a, m.start) == p:
                out.append(OPEN[m.kind])
        if any(s <= p and q <= e for s, e in mk):
            if not out or out[-1] != MASK:
                out.append(MASK)
        else:
            out.append(text[p:q])
    for m in ms:
        if min(b, m.end) == b and max(a, m.start) < b:
            out.append(CLOSE[m.kind])
    s = "".join(out).replace("\r\n", "\n").replace("\r", "\n").replace("\n", NEWLINE)
    s = re.sub(r"[ \t\f\v]+", " ", s).strip()
    return ("…" if a > 0 else "") + s + ("…" if b < len(text) else "")


def excerpt_windows(text: str, tiers: list[list[Mark]], masks: list[tuple[int, int]],
                    max_windows: int = MAX_WINDOWS, width: int = WINDOW_CHARS) -> tuple[list[str], int]:
    """Rendered windows for seed tiers in priority order, and the number of value matches left out.

    Each seed not yet shown gets a window of about `width` characters centred on it. A window that
    overlaps a chosen one is merged with it while the result stays within MAX_MERGED_CHARS, and is
    clipped against it otherwise. Memory snapshots often repeat a passage: a window whose text
    equals one already shown is skipped (its matches count as shown) and the slot goes to the
    next seed. Every mark that falls inside a chosen window is drawn.
    """
    marks = [m for tier in tiers for m in tier]
    if not marks:
        return [], 0
    n, half = len(text), width // 2

    def render(a: int, b: int) -> str:
        a, b = _snap(text, a, b, marks)
        return render_window(text, a, b, marks, masks)

    chosen: list[list] = []  # [start, end, rendered]
    dups: list[tuple[int, int]] = []
    seen: set[str] = set()
    for m in marks:
        s, e = m.start, m.end
        if any(w[0] <= s and e <= w[1] for w in chosen) or any(a <= s and e <= b for a, b in dups):
            continue
        c = (s + e) // 2
        a, b = max(0, min(s, c - half)), min(n, max(e, c + half))
        r = render(a, b)
        if r.strip("…") in seen:
            dups.append((a, b))
            continue
        target = next((w for w in chosen if _overlap(a, b, w[0], w[1])), None)
        if target is not None and max(b, target[1]) - min(a, target[0]) <= max(MAX_MERGED_CHARS, b - a):
            seen.discard(target[2].strip("…"))
            target[0], target[1] = min(a, target[0]), max(b, target[1])
            target[2] = render(target[0], target[1])
            seen.add(target[2].strip("…"))
            continue
        if len(chosen) >= max_windows:
            continue
        for w in chosen:  # clip so that no text is shown twice
            if _overlap(a, b, w[0], w[1]):
                if s >= w[1]:
                    a = max(a, w[1])
                else:
                    b = min(b, w[0])
        r = render(a, b)
        seen.add(r.strip("…"))
        chosen.append([a, b, r])
    chosen.sort(key=lambda w: w[0])
    spans = [(w[0], w[1]) for w in chosen] + dups
    left = sum(1 for m in marks if m.kind == "value" and not any(a <= m.start and m.end <= b for a, b in spans))
    return [w[2] for w in chosen], left


def join_windows(windows: list[str], left: int) -> str:
    """One sheet cell: '[1] … [2] …', plus a count of matches that did not fit."""
    s = " ".join(f"[{i}] {w}" for i, w in enumerate(windows, 1))
    if left:
        s += f" (+{left} more match{'es' if left > 1 else ''})"
    return s


# --- unit keys and occurrences ----------------------------------------------------------------------

def parse_unit_key(key: str) -> tuple[str, str, str]:
    """'type|value|ctx' -> (type, displayed value, context); the value may contain '|'."""
    t, rest = key.split("|", 1)
    v, c = rest.rsplit("|", 1)
    return t, v, c


@dataclass(frozen=True)
class Occ:
    """One anchor occurrence with its span in the display text."""

    start: int
    end: int
    type: str
    raw: str  # normalised value before hashing
    stored: str  # value as B1 stores it (keyed hash for PERSON, email, phone and sensitive lines)
    lemma: str  # context lemma without the PROPN mark, '' if none


@dataclass
class DocInfo:
    text: str  # memory text with scaffold session labels blanked (B1 line cleaning)
    occs: list[Occ]
    line_sens: list[bool]
    masks: list[tuple[int, int]] = field(default_factory=list)


def anchor_spans(ex, text: str, doc, sensitive: bool) -> list[tuple[int, int, str, str, str, str]]:
    """`AnchorExtractor.anchors_for` with spans: (start, end, type, raw value, stored value, context)."""
    from avsd.lineage.anchors import CRED_LINE, HASHED_TYPES, NER_TYPES, _overlaps, keyed_hash, norm_entity

    found, claimed = ex.regex_anchors(text)
    if doc is not None:
        for ent in doc.ents:
            kind = NER_TYPES.get(ent.label_)
            if kind is None or _overlaps(claimed, ent.start_char, ent.end_char):
                continue
            v = norm_entity(ent.text)
            if v is not None:
                found.append((ent.start_char, ent.end_char, kind, v))
    if not found:
        return []
    sensitive = sensitive or bool(CRED_LINE.search(text))
    ctx = ex.context_keys(doc, [(s, e) for s, e, _, _ in found]) if doc is not None else [""] * len(found)
    out = []
    for (s, e, kind, v), c in zip(found, ctx):
        stored = keyed_hash(ex.salt, kind, v) if (kind in HASHED_TYPES or sensitive) else v
        out.append((s, e, kind, v, stored, c))
    return out


def _pieces(t: str) -> list[tuple[int, str]]:
    """The spaCy pieces of one line, as in `AnchorExtractor.extract`."""
    from avsd.lineage.anchors import MAX_PIECE_CHARS

    if len(t) <= MAX_PIECE_CHARS:
        return [(0, t)]
    out, start = [], 0
    while start < len(t):
        end = min(len(t), start + MAX_PIECE_CHARS)
        if end < len(t):
            cut = t.rfind(" ", start + MAX_PIECE_CHARS // 2, end)
            end = cut + 1 if cut > 0 else end
        out.append((start, t[start:end]))
        start = end
    return out


def text_occurrences(ex, text: str, batch_size: int = 256) -> DocInfo:
    """B1 anchors of a full memory snapshot with spans (lines as in `memory.segment_lines`)."""
    from avsd.lineage.anchors import _ALPHA, CRED_LINE, PROPN_MARK, HeadingStack
    from avsd.lineage.memory import SESSION_LABEL, clean_line

    stack = HeadingStack()
    disp, line_sens = [], []
    pieces: list[str] = []
    meta: list[tuple[int, bool]] = []
    pos = 0
    for raw in (text or "").split("\n"):
        sens = stack.feed(raw)
        line = SESSION_LABEL.sub(" ", raw) if "PREVIOUS (NOW ENDED)" in raw else raw
        clean = clean_line(raw)
        if clean is not None:
            off = pos + len(line) - len(line.lstrip())
            sens = sens or bool(CRED_LINE.search(clean))
            for p0, piece in _pieces(clean):
                pieces.append(piece)
                meta.append((off + p0, sens))
        disp.append(line)
        line_sens.append(sens)
        pos += len(line) + 1
    has_alpha = [_ALPHA.search(p) is not None for p in pieces]
    nlp = ex.nlp
    docs = iter(nlp.pipe((p for p, a in zip(pieces, has_alpha) if a), batch_size=batch_size)
                if nlp is not None else ())
    occs: list[Occ] = []
    for piece, (base, sens), a in zip(pieces, meta, has_alpha):
        doc = next(docs) if (a and nlp is not None) else None
        for s, e, kind, raw_v, stored, c in anchor_spans(ex, piece, doc, sens):
            occs.append(Occ(base + s, base + e, kind, raw_v, stored, c.removeprefix(PROPN_MARK)))
    d = "\n".join(disp)
    return DocInfo(d, occs, line_sens, credential_spans(d, line_sens))


class UnitMatcher:
    """Matches occurrences against one unit key (type, displayed value, context)."""

    def __init__(self, unit_key: str, salt: bytes):
        self.t, self.kv, self.kc = parse_unit_key(unit_key)
        self.salt = salt
        self.quantity = self.t in QUANTITY
        self._disp: dict[str, str] = {}

    def ctx_ok(self, lemma: str, key_ctx: str | None = None) -> bool:
        from avsd.lineage.anchors import keyed_hash

        kc = self.kc if key_ctx is None else key_ctx
        if not lemma:
            return kc == ""
        return kc == lemma or kc == keyed_hash(self.salt, "ctx", lemma, 8)

    def value_ok(self, o: Occ) -> bool:
        from avsd.lineage.anchors import display_value

        if o.type != self.t:
            return False
        d = self._disp.get(o.stored)
        if d is None:
            d = self._disp[o.stored] = display_value(o.type, o.stored, self.salt)
        return d == self.kv

    def is_unit(self, o: Occ) -> bool:
        return self.value_ok(o) and (not self.quantity or self.ctx_ok(o.lemma))

    def find(self, doc: DocInfo) -> list[Occ]:
        return [o for o in doc.occs if self.is_unit(o)]

    def recover_ctx(self, docs: list[DocInfo]) -> str | None:
        """The lemma behind the key's context (plain, or found by hashing candidate lemmas)."""
        if not self.kc:
            return ""
        if not self.kc.startswith("h:"):
            return self.kc
        for d in docs:
            for o in d.occs:
                if o.lemma and self.ctx_ok(o.lemma):
                    return o.lemma
        return None


def _ctx_forms(lemma: str) -> str:
    forms = [re.escape(lemma) + r"(?:s|es|'s|’s)?"]
    if lemma.endswith("y") and len(lemma) > 2:
        forms.append(re.escape(lemma[:-1]) + "ies")
    return "(?:" + "|".join(forms) + ")"


def _ctx_word_re(lemma: str) -> re.Pattern[str]:
    return re.compile(r"(?i)(?<![\w])" + _ctx_forms(lemma) + r"(?![\w])")


def _ctx_adjacent(text: str, s: int, e: int, lemmas: list[str]) -> bool:
    """A context word right after the value (up to two words between, "56 new donors") or right
    before it with only punctuation between ("Donors: 56"), as in B1's context rules."""
    after, before = text[e:e + 60].split("\n", 1)[0], text[max(0, s - 40):s].rsplit("\n", 1)[-1]
    for lem in lemmas:
        f = _ctx_forms(lem)
        if re.match(r"(?i)[^\w\n]*(?:[A-Za-z][\w'’-]*[^\w\n]+){0,2}?" + f + r"(?![\w])", after):
            return True
        if re.search(r"(?i)(?<![\w])" + f + r"[\s:=*_|()\[\]\-–—]*$", before):
            return True
    return False


def literal_marks(text: str, surfaces: list[str], quantity: bool, ctx_lemmas: list[str]) -> list[Mark]:
    """Case-insensitive literal matches of the value's surface forms.

    For quantities a match counts only next to a context word (`_ctx_adjacent`), or, without a
    context, when the surface is long and not a bare number.
    """
    lemmas = [c for c in ctx_lemmas if c]
    spans: list[tuple[int, int]] = []
    for sf in sorted({s.strip() for s in surfaces if s and s.strip()}, key=len, reverse=True):
        if len(sf) < 2:
            continue
        rx = re.compile(r"(?i)(?<![\w])" + re.escape(sf) + r"(?![\w])")
        for m in rx.finditer(text):
            if quantity:
                if lemmas:
                    if not _ctx_adjacent(text, m.start(), m.end(), lemmas):
                        continue
                elif len(sf) < 5 or sf.replace(",", "").replace(".", "").isdigit():
                    continue
            if not any(_overlap(m.start(), m.end(), s, e) for s, e in spans):
                spans.append(m.span())
    return [Mark(s, e, "value") for s, e in sorted(spans)]


def ctx_word_marks(text: str, lemmas: list[str], limit: int = MAX_WINDOWS) -> list[Mark]:
    out: list[Mark] = []
    for lem in lemmas:
        if not lem:
            continue
        for m in _ctx_word_re(lem).finditer(text):
            out.append(Mark(m.start(), m.end(), ""))
            if len(out) >= limit:
                return out
    return out


@dataclass
class Evidence:
    """What one version shows about a unit."""

    windows: list[str]
    left: int
    n_unit: int  # occurrences matched by the B1 rules
    n_literal: int
    n_ctx: int  # other values in the unit's contexts
    n_ctxword: int
    masked_value: bool


def version_evidence(doc: DocInfo, um: UnitMatcher, contexts: list[str], surfaces: list[str],
                     max_windows: int = MAX_WINDOWS) -> Evidence:
    unit = sorted(um.find(doc), key=lambda o: o.start)
    tier1 = [Mark(o.start, o.end, "value") for o in unit]
    tier2 = [] if tier1 else literal_marks(doc.text, surfaces, um.quantity, contexts)
    taken = [(m.start, m.end) for m in tier1 + tier2]
    ctx_set = {c for c in contexts if c}
    tier3 = [Mark(o.start, o.end, "ctx") for o in sorted(doc.occs, key=lambda o: o.start)
             if o.type == um.t and o.lemma in ctx_set and not um.value_ok(o)
             and not any(_overlap(o.start, o.end, s, e) for s, e in taken)]
    tier4 = [] if (tier1 or tier2 or tier3) else ctx_word_marks(doc.text, sorted(ctx_set))
    windows, left = excerpt_windows(doc.text, [tier1, tier2, tier3, tier4], doc.masks, max_windows)
    masked = any(_overlap(m.start, m.end, s, e) for m in tier1 + tier2 for s, e in doc.masks)
    return Evidence(windows, left, len(tier1), len(tier2), len(tier3), len(tier4), masked)


# --- prompts ------------------------------------------------------------------------------------

def _block(name: str, note: str, windows: list[str], n_value: int | None = None,
           n_ctx: int | None = None) -> str:
    head = f"{name} ({note})"
    if n_value is not None:
        occ = (f"the unit's value occurs {n_value} time{'s' if n_value != 1 else ''} in {name} (marked ⟦ ⟧)"
               if n_value else f"the unit's value does NOT occur in {name}")
        head += f": {occ}; other values in the unit's context: {n_ctx or 0} (marked ⟨ ⟩)"
    if not windows:
        return head + "\n(no excerpt: neither the value nor its context occurs)"
    return "\n".join([head] + [f"[{i}] {w}" for i, w in enumerate(windows, 1)])


def build_messages(unit_type: str, value: str, context: str, prev: tuple[list[str], int, int],
                   nxt: tuple[list[str], int, int], earlier: tuple[list[str], str] | None) -> list[dict]:
    """Chat messages for one unit; prev and nxt are (windows, value matches, context values).

    The rule label is not shown to the model.
    """
    if context:
        ctx_line = (f"- context key: {context} (part of this unit's identity)" if unit_type in QUANTITY
                    else f"- context key: {context} (for reference; not part of this unit's identity)")
    else:
        ctx_line = "- context key: none"
    parts = [
        ("An AI agent keeps memory notes and regularly rewrites them. PREV is the memory just before one "
         "rewrite (its input) and NEXT is the rewritten memory (its output). A rule-based extractor found "
         "the fact unit below in this pair of versions. Decide what happened to this unit from PREV to NEXT."),
        "Definitions (from the rule method):\n" + DEFINITIONS,
        "Excerpts: " + EXCERPT_NOTE,
        "Decide in three steps:\n" + PROCEDURE,
        ("Unit:\n"
         f"- type: {unit_type} ({TYPE_GLOSS.get(unit_type, unit_type)})\n"
         f"- value: {value}\n" + ctx_line),
    ]
    if earlier and earlier[0]:
        parts.append(_block("EARLIER", f"an older version, before PREV, that holds the unit; {earlier[1]}",
                            earlier[0]))
    parts += [_block("PREV", "the input", *prev), _block("NEXT", "the output", *nxt)]
    parts.append(
        'Reply with JSON: {"label": "kept" | "modified" | "dropped" | "new" | "restored", '
        '"confidence": "low" | "medium" | "high", '
        '"rationale": "<at most 25 words: whether the value is in PREV and in NEXT, and why>"}'
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "\n\n".join(parts)}]


# --- model output -------------------------------------------------------------------------------

def parse_model_output(text: str | None) -> dict:
    """Parse and validate one model reply.

    Returns label ('' if invalid), confidence ('' if invalid), rationale (at most
    RATIONALE_WORDS words), valid (label usable), error ('' or a short reason) and
    truncated (rationale was cut).
    """
    res = {"label": "", "confidence": "", "rationale": "", "valid": False, "error": "", "truncated": False}
    if not text or not text.strip():
        res["error"] = "empty"
        return res
    s = re.sub(r"(?s)<think>.*?</think>", "", text).strip()
    fence = re.search(r"(?s)```(?:json)?\s*(.*?)```", s)
    if fence:
        s = fence.group(1).strip()
    obj = None
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"(?s)\{.*\}", s)
        if m:
            try:
                obj = json.loads(m.group(0))
            except json.JSONDecodeError:
                obj = None
    if not isinstance(obj, dict):
        res["error"] = "not_json"
        return res
    label = str(obj.get("label", "")).strip().lower()
    conf = str(obj.get("confidence", "")).strip().lower()
    words = " ".join(str(obj.get("rationale", "") or "").split()).split(" ")
    words = [w for w in words if w]
    res["truncated"] = len(words) > RATIONALE_WORDS
    res["rationale"] = " ".join(words[:RATIONALE_WORDS]) + ("…" if res["truncated"] else "")
    res["confidence"] = conf if conf in CONFIDENCES else ""
    if label not in LABELS:
        res["error"] = "bad_label"
        return res
    res["label"] = label
    res["valid"] = True
    if not res["confidence"]:
        res["error"] = "bad_confidence"
    return res


# --- agreement statistics ---------------------------------------------------------------------

def cohen_kappa(a: list[str], b: list[str], labels: tuple[str, ...] = LABELS) -> float:
    """Cohen's kappa of two label lists (pairs with a label outside `labels` are skipped)."""
    pairs = [(x, y) for x, y in zip(a, b) if x in labels and y in labels]
    n = len(pairs)
    if n == 0:
        return float("nan")
    po = sum(x == y for x, y in pairs) / n
    ca, cb = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    pe = sum(ca[k] * cb[k] for k in labels) / (n * n)
    return float("nan") if pe >= 1 else (po - pe) / (1 - pe)


# --- review design ---------------------------------------------------------------------------

def _prn(seed: int, pair_id, unit_key: str) -> float:
    """Permanent random number of a unit in [0, 1): SHA-256 of the seed, pair id and unit key.

    Taking the smallest numbers of a stratum gives a simple random sample that does not change
    when the sheet is regenerated, and changes only locally if the stratum itself changes.
    """
    h = hashlib.sha256(f"{seed}\x00{str(pair_id).strip()}\x00{unit_key.strip()}".encode()).digest()
    return int.from_bytes(h[:8], "big") / 2.0**64


def allocate(sizes: dict[str, int], n: int, order: tuple[str, ...] = LABELS) -> dict[str, int]:
    """Proportional allocation of n draws over strata (largest remainder in exact integer
    arithmetic, ties to the earlier stratum in `order`), at least one per non-empty stratum."""
    keys = [k for k in order if sizes.get(k, 0) > 0] + sorted(k for k in sizes if k not in order and sizes[k] > 0)
    total = sum(sizes[k] for k in keys)
    if total <= n:
        return {k: sizes[k] for k in keys}
    least = 1 if n >= len(keys) else 0
    a = {k: min(sizes[k], max(least, n * sizes[k] // total)) for k in keys}

    def rem(k: str) -> int:  # (quota - allocation) * total
        return n * sizes[k] - a[k] * total

    while sum(a.values()) < n:
        k = max((k for k in keys if a[k] < sizes[k]), key=lambda k: (rem(k), -keys.index(k)))
        a[k] += 1
    while sum(a.values()) > n:
        k = min((k for k in keys if a[k] > least), key=lambda k: (rem(k), -keys.index(k)))
        a[k] -= 1
    return a


def review_design(rows: list[dict], seed: int, target: int = REVIEW_TARGET, min_sample: int = MIN_SAMPLE,
                  rule_cols: tuple[str, ...] = ("rule_v1", "rule_v2", "rule_v3")) -> tuple[list[dict], dict]:
    """Priority, design stratum and inclusion probability of each row (re-check design).

    rows: dicts with qwen35_label and gptoss_label ('' when a model gave no valid answer), the rule
    labels named in `rule_cols` ('' when missing), pair_id and unit_key.
    - A (1-必标, probability 1): the two strong models disagree, or one has no valid answer.
    - B (1-必标, probability 1): they agree and at least one rule version says otherwise (a missing
      rule label counts as otherwise).
    - C:<label> (the rest): both models and every rule version say <label>. A random sample of
      max(min_sample, target - |A| - |B|) of these rows is 2-抽样, allocated to the labels in
      proportion (`allocate`, at least one per non-empty label) and drawn with permanent random
      numbers (`_prn`); the others are 3-可选. Every row of C:<label> has inclusion probability
      n_label / N_label, sampled or not.
    Every unit on which two rule versions disagree is in A or B, so paired comparisons of the rule
    sets carry no sampling error from the design. Returns one dict per row (priority, stratum,
    inclusion_prob, suggested: the agreed label or '') and a summary of the design.
    """
    out: list[dict] = []
    c_by: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(rows):
        a, b = (r.get("qwen35_label") or "").strip(), (r.get("gptoss_label") or "").strip()
        sug = a if a and a == b else ""
        if not sug:
            st = STRATUM_A
        elif any((r.get(c) or "").strip() != sug for c in rule_cols):
            st = STRATUM_B
        else:
            st = f"{STRATUM_C}:{sug}"
            c_by[sug].append(i)
        out.append({"stratum": st, "suggested": sug})
    n_cert = sum(1 for o in out if not o["stratum"].startswith(STRATUM_C))
    n_c = sum(len(v) for v in c_by.values())
    n_sample = min(n_c, max(min_sample, target - n_cert))
    alloc = allocate({k: len(v) for k, v in c_by.items()}, n_sample) if n_sample else {}
    sample: set[int] = set()
    for k, idx in c_by.items():
        idx.sort(key=lambda i: (_prn(seed, rows[i]["pair_id"], rows[i]["unit_key"]), i))
        sample.update(idx[:alloc.get(k, 0)])
    for i, o in enumerate(out):
        if o["stratum"].startswith(STRATUM_C):
            k = o["suggested"]
            o["priority"] = PRIORITIES[1] if i in sample else PRIORITIES[2]
            o["inclusion_prob"] = alloc.get(k, 0) / len(c_by[k])
        else:
            o["priority"] = PRIORITIES[0]
            o["inclusion_prob"] = 1.0
    strata = Counter(o["stratum"] for o in out)
    info = {
        "counts": {p: sum(1 for o in out if o["priority"] == p) for p in PRIORITIES}, "seed": seed,
        "target": target, "min_sample": min_sample, "n_sample": n_sample,
        "A": strata.get(STRATUM_A, 0), "B": strata.get(STRATUM_B, 0),
        "C_by_label": {k: len(c_by.get(k, [])) for k in LABELS},
        "sample_by_label": {k: alloc.get(k, 0) for k in LABELS},
    }
    return out, info


# --- label metrics against the owner's labels ----------------------------------------------------

def _div(a, b):
    import numpy as np

    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    return np.divide(a, b, out=np.zeros(np.broadcast(a, b).shape), where=b > 0)


def weighted_prf(W, truth, pred, labels: tuple[str, ...] = LABELS) -> dict:
    """Precision, recall and F1 per label for every row of the weight matrix W (R x n).

    Zero when undefined (scikit-learn's zero_division=0); 'macro' averages the labels present in
    truth or predictions; ('all', 'accuracy') is the weighted share of correct predictions.
    Predictions outside `labels` are always wrong. Returns {label: {metric: array (R,)}}.
    """
    import numpy as np

    W = np.atleast_2d(np.asarray(W, dtype=float))
    truth, pred = np.asarray(truth), np.asarray(pred)
    out: dict[str, dict] = {}
    present = []
    for lab in labels:
        t, p = (truth == lab).astype(float), (pred == lab).astype(float)
        tp, pp, ap = W @ (t * p), W @ p, W @ t
        out[lab] = {"precision": _div(tp, pp), "recall": _div(tp, ap), "f1": _div(2 * tp, pp + ap),
                    "support": ap}
        if t.any() or p.any():
            present.append(lab)
    if present:
        out["macro"] = {m: np.mean([out[lab][m] for lab in present], axis=0)
                        for m in ("precision", "recall", "f1")}
        out["macro"]["support"] = W.sum(axis=1)
    out["all"] = {"accuracy": _div(W @ (truth == pred).astype(float), W.sum(axis=1)), "support": W.sum(axis=1)}
    return out


def _stratum_of(row: dict) -> str:
    """'disagree' or 'agree': from review_priority when present, else rule label vs LLM label."""
    p = (row.get("review_priority") or "").strip()[:1]
    if p in ("1", "2", "3"):
        return "disagree" if p == "1" else "agree"
    rl, ll = ((row.get(c) or "").strip().lower() for c in ("rule_label", "llm_label"))
    return "agree" if ll and ll == rl else "disagree"


def design_weights(strata: list[str], cells: list[str], clusters: list[str], N_stratum: dict[str, int],
                   N_cell: dict[tuple[str, str], int], reps: int, seed: int,
                   strata_names: tuple[str, ...] = STRATA, cell_name: str = "rule label"):
    """Weights of the labelled rows for the point estimate and `reps` bootstrap replicates.

    strata, cells and clusters describe the labelled rows (stratum, cell, pair id; the cell is the
    rule label in the Qwen3-14B design and the design stratum in the re-check design). Within a
    stratum the labelled rows stand for the whole stratum: per cell (N_cell / n_cell) when every
    cell of the stratum has a labelled row, else by the labelled fraction of the stratum. With
    every sampled row labelled, a row's weight is 1 / inclusion probability. Replicates resample
    pairs with replacement within each weighting group and scale back to its size. Returns (W of
    shape (reps + 1, n) with row 0 the point estimate, or None if a non-empty stratum has no
    labelled row; the weighting used per stratum).
    """
    import numpy as np

    n = len(strata)
    how: dict[str, str] = {}
    groups: dict[tuple, tuple[int, list[int]]] = {}
    for s in strata_names:
        members = [j for j in range(n) if strata[j] == s]
        if not members:
            how[s] = "no rows" if N_stratum.get(s, 0) == 0 else "unlabelled"
            continue
        cells_s = sorted(c for (st, c) in N_cell if st == s and N_cell[(st, c)] > 0)
        if all(any(cells[j] == c for j in members) for c in cells_s):
            how[s] = f"per {cell_name}"
            for c in cells_s:
                groups[(s, c)] = (N_cell[(s, c)], [j for j in members if cells[j] == c])
        else:
            how[s] = "stratum"
            groups[(s,)] = (N_stratum[s], members)
    if any(h == "unlabelled" for h in how.values()) or n == 0:
        return None, how
    rng = np.random.default_rng(seed)
    W = np.zeros((reps + 1, n))
    for g in sorted(groups):
        Ng, members = groups[g]
        cl = np.array([clusters[j] for j in members])
        _, inv = np.unique(cl, return_inverse=True)
        k = int(inv.max()) + 1
        counts = np.zeros((reps, k))
        draws = rng.integers(0, k, size=(reps, k))
        np.add.at(counts, (np.repeat(np.arange(reps), k), draws.ravel()), 1.0)
        M = np.vstack([np.ones((1, k)), counts])[:, inv]
        W[:, members] = M * (Ng / M.sum(axis=1, keepdims=True))
    return W, how


# Methods: rule = B1 v1, rule_v<K> = revised rule sets, llm = Qwen3-14B, then the two re-check models, Gemini
# and Claude (each scored only on the rows it labelled, GEMINI_LABELS_FILE, CLAUDE_LABELS_FILE). Labels: the five
# classes, macro, all (accuracy), loss and loss_all (`loss_prf`).
# n_labelled_disagree / N_disagree are the certainty strata (A, B) in the re-check design and the
# rule/Qwen3-14B disagreements in the Qwen3-14B design; *_agree the sampled stratum.
METRIC_COLUMNS: tuple[str, ...] = (
    "scheme", "label", "metric", "rule", "rule_lo", "rule_hi", "rule_v2", "rule_v2_lo", "rule_v2_hi",
    "v2_minus_v1", "v2_minus_v1_lo", "v2_minus_v1_hi", "llm", "llm_lo", "llm_hi",
    "qwen35_122b", "qwen35_122b_lo", "qwen35_122b_hi", "gptoss_120b", "gptoss_120b_lo", "gptoss_120b_hi",
    "gemini", "gemini_lo", "gemini_hi", "claude", "claude_lo", "claude_hi",
    "support", "n_labelled", "n_labelled_disagree", "N_disagree", "n_labelled_agree", "N_agree", "note",
)
SHEET_PREFIX: dict[str, str] = {"qwen35_122b": "qwen35", "gptoss_120b": "gptoss"}  # sheet column prefixes
RULE_FILE_RE = re.compile(r"memory_pairs_rule_v(\d+)\.csv")


def rule_version_files(labels_dir: str | Path, v2_path: str | Path | None = None) -> dict[str, Path]:
    """Revised rule-label files present in labels_dir, {"v2": path, "v3": path, ...} in version order.

    Each file has the columns pair_id, unit_key and rule_label_v<K>. `v2_path`, when given,
    replaces the v2 file."""
    found: dict[str, Path] = {}
    for f in Path(labels_dir).glob("memory_pairs_rule_v*.csv"):
        m = RULE_FILE_RE.fullmatch(f.name)
        if m and int(m.group(1)) >= 2:
            found[f"v{int(m.group(1))}"] = f
    if v2_path is not None:
        if Path(v2_path).exists():
            found["v2"] = Path(v2_path)
        else:
            found.pop("v2", None)
    return dict(sorted(found.items(), key=lambda kv: int(kv[0][1:])))


def metric_columns(versions) -> list[str]:
    """METRIC_COLUMNS, then for each rule version beyond v2 its estimate, CI and paired difference
    against v1 (appended, so the columns of the v1/v2 format keep their positions)."""
    cols = list(METRIC_COLUMNS)
    for v in versions:
        if v != "v2":
            cols += [f"rule_{v}", f"rule_{v}_lo", f"rule_{v}_hi", f"{v}_minus_v1", f"{v}_minus_v1_lo",
                     f"{v}_minus_v1_hi"]
    return cols


def _float(v) -> float | None:
    try:
        x = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return x if 0.0 <= x <= 1.0 else None


def loss_prf(W, truth, pred, at_risk_only: bool = True) -> dict:
    """Loss detection, the event of the B1 hazards: positive dropped or modified, negative kept.

    at_risk_only: only rows whose truth is kept, dropped or modified (a prediction of new or restored
    there counts as not lost); otherwise every row, with truth new and restored counting as negatives.
    Precision, recall and F1 of 'lost' for every row of the weight matrix W (zero when undefined)."""
    import numpy as np

    W = np.atleast_2d(np.asarray(W, dtype=float))
    t = np.array([x in LOSS_LABELS for x in truth], dtype=float)
    p = np.array([x in LOSS_LABELS for x in pred], dtype=float)
    m = (np.array([x in LOSS_LABELS or x == "kept" for x in truth], dtype=float) if at_risk_only
         else np.ones(len(truth)))
    tp, pp, ap = W @ (t * p * m), W @ (p * m), W @ (t * m)
    return {"precision": _div(tp, pp), "recall": _div(tp, ap), "f1": _div(2 * tp, pp + ap), "support": ap}


def audit_weights(strata: list[str], base, reps: int, seed: int):
    """(reps + 1) x n weights: row 0 the base weights, then a stratified bootstrap that resamples the rows
    with replacement within each stratum (each row keeps its base weight)."""
    import numpy as np

    base = np.asarray(base, dtype=float)
    n = len(strata)
    rng = np.random.default_rng(seed)
    W = np.zeros((reps + 1, n))
    W[0] = base
    for s in sorted(set(strata)):
        idx = np.array([j for j in range(n) if strata[j] == s])
        k = len(idx)
        counts = np.zeros((reps, k))
        np.add.at(counts, (np.repeat(np.arange(reps), k), rng.integers(0, k, size=(reps, k)).ravel()), 1.0)
        W[1:, idx] = counts * base[idx]
    return W


def read_audit(labels_dir: str | Path) -> dict[str, dict]:
    """The owner's B1 audit sample (AUDIT_FILE): {unit_key: {stratum, p_audit}}; {} without the file."""
    path = Path(labels_dir) / AUDIT_FILE
    if not path.exists():
        return {}
    return {str(k).strip(): v for k, v in (json.loads(path.read_text()).get("b1") or {}).items()}


def import_claude_labels(cfg: dict, log=print) -> dict:
    """data/labels/memory_pairs_claude.csv from Claude's blind labels (claude_blind/b1_part*.csv): one row per
    blind-sheet unit with unit_key, claude_label, bad_unit, confidence and reason (mode 600)."""
    labels_dir = Path(cfg["paths"]["labels"])
    rows: list[dict] = []
    for p in sorted(labels_dir.glob(CLAUDE_BLIND_GLOB)):
        with open(p, encoding="utf-8-sig", newline="") as f:
            rows += list(csv.DictReader(f))
    if not rows:
        raise SystemExit(f"no Claude label files ({CLAUDE_BLIND_GLOB}) in {labels_dir}")
    keys = [(r.get("unit_key") or "").strip() for r in rows]
    dup = [k for k, c in Counter(keys).items() if c > 1]
    bad = [r.get("claude_label") for r in rows if (r.get("claude_label") or "").strip().lower() not in LABELS]
    if dup or bad:
        raise SystemExit(f"Claude labels: {len(dup)} duplicated unit keys, {len(bad)} labels outside {LABELS}")
    with open(labels_dir / "memory_pairs_blind.csv", encoding="utf-8-sig", newline="") as f:
        blind = {(r.get("unit_key") or "").strip() for r in csv.DictReader(f)}
    with _private_open(labels_dir / CLAUDE_LABELS_FILE, "w", encoding="utf-8", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["unit_key", "claude_label", "bad_unit", "confidence", "reason"])
        for k, r in sorted(zip(keys, rows), key=lambda kr: int(kr[1].get("row_index") or 0)):
            wr.writerow([k, r["claude_label"].strip().lower(), (r.get("bad_unit") or "").strip(),
                         (r.get("confidence") or "").strip(), (r.get("reason") or "").strip()])
    info = {"rows": len(rows), "in_blind_sheet": len(set(keys) & blind), "blind_rows": len(blind),
            "bad_unit": sum(1 for r in rows if (r.get("bad_unit") or "").strip() == "1"),
            "labels": dict(Counter(r["claude_label"].strip().lower() for r in rows))}
    log(f"import-claude: {info}")
    return info


def compute_label_metrics(cfg: dict | None = None, review_path: str | Path | None = None,
                          out_path: str | Path | None = None, v2_path: str | Path | None = None,
                          reps: int = BOOT_REPS, seed: int | None = None) -> list[dict]:
    """Precision, recall and F1 of the rule labels (v1 and every revised version available) and of the
    LLM raters (Qwen3-14B, the two re-check models, Gemini, Claude) against the owner's human_label.

    Reads the review sheet (data/labels/memory_pairs_review.csv) and uses rows whose human_label is one of
    LABELS. Predictions are joined by (pair_id, unit_key): v1 from the sheet's rule_label column or from
    memory_pairs.csv; revised rule labels from every memory_pairs_rule_v<K>.csv present (`v2_path`
    overrides v2); LLM labels from the sheet or LLM_LABELS_FILE; Gemini from GEMINI_LABELS_FILE and Claude
    from CLAUDE_LABELS_FILE (by unit_key), each scored only on the rows it labelled. A labelled row without
    a label of some other method counts as a wrong prediction for that method. Besides per-class metrics,
    'loss' is loss detection (`loss_prf`: dropped or modified against kept, on rows the truth labels kept,
    dropped or modified) and 'loss_all' the same over every row.

    Schemes (95% intervals from `reps` bootstrap replicates; differences between rule versions use the
    same replicates):
    - Audit design (the sheet has inclusion_prob and AUDIT_FILE exists, owner's choice of 2026-10-03):
      weighted = the audit rows, each weighted by 1 / (review inclusion probability x p_audit), adjusted
      within an audit stratum for audit rows left unlabelled, with a bootstrap that resamples rows within
      the audit strata; unweighted = the audit rows as they are; weighted_owner71 = every row the owner
      labelled, the rows outside the audit treated as a random sample of their review stratum;
      weighted_claude277 = Claude's labels as the truth on every row Claude labelled, weighted by the
      review design (`design_weights`).
    - Re-check design without an audit: weighted = rows of the design sample (priorities 1 and 2) weighted
      up to their design stratum (`design_weights`); unweighted = every labelled row.
    - Qwen3-14B design (no inclusion_prob): disagreement and agreement strata, each weighted up to its size
      per rule-label cell.
    Writes outputs/tables/memory_label_metrics.csv (`metric_columns`) and returns its rows; each row also
    carries 'pairs' (every difference between two rule versions with its interval), which is not written.
    """
    import numpy as np

    if cfg is None:
        from avsd.config import load_config

        cfg = load_config()
    paths = cfg["paths"]
    seed = int(cfg.get("seed", 20261003) if seed is None else seed)
    labels_dir = Path(paths["labels"])
    review_path = Path(review_path) if review_path else labels_dir / REVIEW_FILE
    version_files = rule_version_files(labels_dir, v2_path)
    out_path = Path(out_path) if out_path else Path(paths["outputs"]) / "tables" / METRICS_FILE
    with open(review_path, encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        sheet = list(rd)
        cols = set(rd.fieldnames or [])

    def key(r: dict) -> tuple[str, str]:
        return str(r.get("pair_id") or "").strip(), (r.get("unit_key") or "").strip()

    def lab(v) -> str:
        v = (v or "").strip().lower()
        return v if v in LABELS else NO_LABEL

    def join(path: Path, col: str, by=key) -> dict | None:
        if not path.exists():
            return None
        with open(path, encoding="utf-8-sig", newline="") as f:
            rd_ = csv.DictReader(f)
            if col not in (rd_.fieldnames or []):
                return None
            return {by(r): r.get(col) for r in rd_}

    def ukey(r: dict) -> str:
        return (r.get("unit_key") or "").strip()

    notes = []
    preds: dict[str, list[str]] = {}
    if "rule_label" in cols:
        preds["rule"] = [lab(r.get("rule_label")) for r in sheet]
    else:
        j = join(labels_dir / PAIRS_FILE, "rule_label") or {}
        preds["rule"] = [lab(j.get(key(r))) for r in sheet]
        notes.append(f"rule (v1) joined from {PAIRS_FILE}: {sum(1 for r in sheet if key(r) in j)} of "
                     f"{len(sheet)} sheet rows matched")
    for v, path in version_files.items():
        vk = join(path, f"rule_label_{v}") or {}
        preds[f"rule_{v}"] = [lab(vk.get(key(r))) for r in sheet]
        matched = sum(1 for r in sheet if key(r) in vk)
        notes.append(f"rule_{v} joined from {path.name}: {matched} of {len(sheet)} sheet rows matched, "
                     f"{len(vk) - matched} file rows unmatched")
    llm_cols = {QWEN3_14B.key: "llm_label", **{k: f"{SHEET_PREFIX[k]}_label" for k in STRONG}}
    for k, col in llm_cols.items():
        name = "llm" if k == QWEN3_14B.key else k
        if col in cols:
            preds[name] = [lab(r.get(col)) for r in sheet]
        else:
            j = join(labels_dir / LLM_LABELS_FILE, k)
            if j is not None:
                preds[name] = [lab(j.get(key(r))) for r in sheet]
                notes.append(f"{name} joined from {LLM_LABELS_FILE}: {sum(1 for r in sheet if key(r) in j)} "
                             f"of {len(sheet)} sheet rows matched")
    pri = [(r.get("review_priority") or "").strip()[:1] for r in sheet]
    covered: dict[str, list[bool]] = {}
    gem = join(labels_dir / GEMINI_LABELS_FILE, "gemini_label")
    if gem is not None:
        preds["gemini"] = [lab(gem.get(key(r))) for r in sheet]
        covered["gemini"] = [key(r) in gem for r in sheet]
        notes.append(f"gemini joined from {GEMINI_LABELS_FILE}: {sum(covered['gemini'])} of {len(sheet)} sheet rows "
                     "have a Gemini answer; Gemini is scored on those rows only")
    cla = join(labels_dir / CLAUDE_LABELS_FILE, "claude_label", by=ukey)
    if cla is not None:
        # unit keys are unique among the rows Claude labels (the design sample); a key repeated elsewhere
        # in the sheet (priority 3) never matches a Claude row
        design_keys = Counter(ukey(r) for r, p in zip(sheet, pri) if p in ("1", "2"))
        ok = [ukey(r) in cla and (pri[i] in ("1", "2") or not design_keys) for i, r in enumerate(sheet)]
        preds["claude"] = [lab(cla.get(ukey(r))) if ok[i] else NO_LABEL for i, r in enumerate(sheet)]
        covered["claude"] = ok
        notes.append(f"claude joined from {CLAUDE_LABELS_FILE}: {sum(ok)} of {len(sheet)} sheet rows have a Claude "
                     "label; Claude is scored on those rows only")
    columns = metric_columns(version_files)
    human = [(r.get("human_label") or "").strip().lower() for r in sheet]
    lab_all = [i for i, h in enumerate(human) if h in LABELS]
    unknown = sum(1 for h in human if h and h not in LABELS)
    clusters = [str(r.get("pair_id") or "").strip() for r in sheet]
    probs = [_float(r.get("inclusion_prob")) for r in sheet]
    n = len(lab_all)
    audit = read_audit(labels_dir)
    schemes: list[dict] = []  # name, idx (sheet rows), truth, weights(sub) -> W, note, counts

    def ones(sub: list[int]):
        return np.ones((1, len(sub)))

    def fixed(idx: list[int], strata: list[str], base: list[float]):
        W_full = audit_weights(strata, base, reps, seed)
        col = {i: j for j, i in enumerate(idx)}
        return lambda sub: W_full[:, [col[i] for i in sub]]

    if "inclusion_prob" in cols and any(x is not None for x in probs):
        st = [(r.get("design_stratum") or "").strip() for r in sheet]
        top = ["certain" if x in (STRATUM_A, STRATUM_B) else "sample" for x in st]
        in_design = [top[i] == "certain" or pri[i] == "2" for i in range(len(sheet))]
        N = Counter(top)

        def make_weights(sub: list[int]):
            return design_weights([top[i] for i in sub], [st[i] for i in sub], [clusters[i] for i in sub],
                                  dict(N), dict(Counter(zip(top, st))), reps, seed,
                                  strata_names=("certain", "sample"), cell_name="design stratum")

        def counts(idx: list[int]) -> dict:
            c = Counter(top[i] for i in idx)
            return {"n_labelled_disagree": c["certain"], "N_disagree": N["certain"],
                    "n_labelled_agree": c["sample"], "N_agree": N["sample"]}

        drift = [abs(probs[i] - sum(1 for j in range(len(sheet)) if st[j] == st[i] and in_design[j])
                     / sum(1 for j in range(len(sheet)) if st[j] == st[i]))
                 for i in {st.index(x) for x in set(st)} if probs[i] is not None]
        warn = ("; WARNING the recorded inclusion probabilities differ from the sampled fractions"
                if drift and max(drift) > 1e-4 else "")
        if audit:
            akeys = Counter(ukey(sheet[i]) for i in range(len(sheet)) if in_design[i])
            if any(akeys[k] > 1 for k in audit):
                raise SystemExit("audit sample: a unit key occurs more than once in the design sample")
            in_audit = [in_design[i] and ukey(r) in audit for i, r in enumerate(sheet)]
            a_st = {i: str(audit[ukey(sheet[i])]["stratum"]) for i in range(len(sheet)) if in_audit[i]}
            aud = [i for i in lab_all if in_audit[i]]
            n_aud = Counter(a_st.values())
            n_aud_lab = Counter(a_st[i] for i in aud)
            base = [1.0 / (probs[i] * float(audit[ukey(sheet[i])]["p_audit"])) * n_aud[a_st[i]] / n_aud_lab[a_st[i]]
                    for i in aud]
            head = (f"Audit design: {len(aud)} of {sum(in_audit)} audit rows labelled ("
                    + ", ".join(f"{s} {n_aud_lab[s]}/{n_aud[s]}" for s in sorted(n_aud)) + "); weight 1 / (review "
                    "inclusion probability x p_audit), stratified bootstrap within the audit strata" + warn)
            schemes.append({"name": "weighted", "idx": aud, "truth": human, "w": fixed(aud, [a_st[i] for i in aud],
                                                                                        base),
                            "note": head, **counts(aud)})
            schemes.append({"name": "unweighted", "idx": aud, "truth": human, "w": ones,
                            "note": f"The {len(aud)} labelled audit rows, unweighted", **counts(aud)})
            lab_d = [i for i in lab_all if in_design[i]]
            rs = {i: st[i].split(":")[0] for i in lab_d}
            N_d = Counter(st[i].split(":")[0] for i in range(len(sheet)) if in_design[i])
            n_d = Counter(rs.values())
            base71 = [1.0 / (probs[i] * n_d[rs[i]] / N_d[rs[i]]) for i in lab_d]
            extra = len(lab_d) - len(aud)
            schemes.append({"name": "weighted_owner71", "idx": lab_d, "truth": human,
                            "w": fixed(lab_d, [rs[i] for i in lab_d], base71),
                            "note": (f"Sensitivity: all {len(lab_d)} rows the owner labelled, the {extra} rows outside "
                                     "the audit treated as random; per review stratum p = labelled / blind rows ("
                                     + ", ".join(f"{s} {n_d[s]}/{N_d[s]}" for s in sorted(N_d)) + ")"),
                            **counts(lab_d)})
            if "claude" in preds:
                cl_idx = [i for i in range(len(sheet)) if covered["claude"][i] and in_design[i]
                          and preds["claude"][i] in LABELS]
                schemes.append({"name": "weighted_claude277", "idx": cl_idx, "truth": preds["claude"],
                                "w": lambda sub: make_weights(sub)[0],
                                "note": (f"Sensitivity: Claude's labels as the truth on the {len(cl_idx)} design rows "
                                         "Claude labelled, weighted by the review design"), **counts(cl_idx)})
        else:
            lab_w = [i for i in lab_all if in_design[i]]
            n_lab = Counter(top[i] for i in lab_w)
            n_des = sum(in_design)
            n_samp = sum(1 for i in range(len(sheet)) if in_design[i] and top[i] == "sample")
            W, how = make_weights(lab_w)
            head = (f"{n} of {len(sheet)} rows labelled (re-check design: certainty strata A and B "
                    f"{n_lab['certain']}/{N['certain']}, sample of stratum C {n_lab['sample']}/{n_samp} drawn from "
                    f"{N['sample']}; priority 1-2 rows {len(lab_w)}/{n_des})")
            head += ("; all priority 1-2 rows labelled" if n_des and len(lab_w) == n_des
                     else "; only labelled rows are used")
            head += (f". Weighting: certainty {how['certain']}, sample {how['sample']} (1 / inclusion probability "
                     "when every sampled row is labelled)") + warn
            vol = n - len(lab_w)
            if vol:
                head += f"; {vol} labelled priority-3 rows outside the sample count in the unweighted scheme only"
            if W is None and lab_w:
                head += "; weighted estimates need labelled rows in both strata"
            schemes.append({"name": "weighted", "idx": lab_w, "truth": human, "w": lambda sub: make_weights(sub)[0],
                            "note": head, "n_labelled": n, **counts(lab_w)})
            schemes.append({"name": "unweighted", "idx": lab_all, "truth": human, "w": ones, "note": head,
                            "n_labelled": n, **counts(lab_w)})
    else:
        strata_all = [_stratum_of(r) for r in sheet]
        N = Counter(strata_all)
        n_lab = Counter(strata_all[i] for i in lab_all)

        def make_weights(sub: list[int]):
            return design_weights([strata_all[i] for i in sub], [preds["rule"][i] for i in sub],
                                  [clusters[i] for i in sub], dict(N), dict(Counter(zip(strata_all, preds["rule"]))),
                                  reps, seed)

        W, how = make_weights(lab_all)
        has_pri = any(pri)
        pri12 = [i for i in range(len(sheet)) if pri[i] in ("1", "2")]
        lab12 = sum(1 for i in pri12 if human[i] in LABELS)
        head = (f"{n} of {len(sheet)} rows labelled (disagreement {n_lab['disagree']}/{N['disagree']}, "
                f"agreement {n_lab['agree']}/{N['agree']}")
        head += f"; priority 1-2 rows {lab12}/{len(pri12)})" if has_pri else ")"
        if has_pri and pri12 and lab12 == len(pri12):
            head += "; all priority 1-2 rows labelled"
        else:
            head += "; only labelled rows are used"
        head += f". Weighting: disagreement {how['disagree']}, agreement {how['agree']}"
        if W is None and lab_all:
            head += "; weighted estimates need labelled rows in both strata"
        c = {"n_labelled_disagree": n_lab["disagree"], "N_disagree": N["disagree"],
             "n_labelled_agree": n_lab["agree"], "N_agree": N["agree"]}
        schemes.append({"name": "weighted", "idx": lab_all, "truth": human, "w": lambda sub: make_weights(sub)[0],
                        "note": head, **c})
        schemes.append({"name": "unweighted", "idx": lab_all, "truth": human, "w": ones, "note": head, **c})

    extra_notes = []
    if unknown:
        extra_notes.append(f"{unknown} unrecognised human labels ignored")
    for m in preds:
        cov = covered.get(m)
        miss = sum(1 for i in lab_all if preds[m][i] == NO_LABEL and (cov is None or cov[i]))
        if miss:
            extra_notes.append(f"{miss} labelled rows without a {m} label (counted wrong)")
    for m, cov in covered.items():
        extra_notes.append(f"{sum(1 for i in lab_all if cov[i])} of {n} labelled rows have a {m} answer")

    methods = ("rule", *(f"rule_{v}" for v in version_files), "llm", *STRONG, "gemini", "claude")
    res: dict[tuple[str, str], dict] = {}
    for sc in schemes:
        for m in methods:
            if m not in preds or (sc["name"] == "weighted_claude277" and m == "claude"):
                continue
            cov = covered.get(m)
            sub = [i for i in sc["idx"] if cov is None or cov[i]]
            Wm = sc["w"](sub) if sub else None
            if Wm is None:
                continue
            T = np.array([sc["truth"][i] for i in sub], dtype=object)
            P = np.array([preds[m][i] for i in sub], dtype=object)
            r = weighted_prf(Wm, T, P)
            r["loss"] = loss_prf(Wm, T, P, True)
            r["loss_all"] = loss_prf(Wm, T, P, False)
            res[(sc["name"], m)] = r

    def cell(scheme: str, m: str, label: str, metric: str):
        return res.get((scheme, m), {}).get(label, {}).get(metric)

    def ci(v) -> tuple[float, float]:
        return tuple(float(x) for x in np.percentile(v[1:], [2.5, 97.5]))

    rule_ms = ["rule", *(f"rule_{v}" for v in version_files)]
    vname = {"rule": "v1", **{f"rule_{v}": v for v in version_files}}
    rows: list[dict] = []
    specs = ([(lb, mt) for lb in (*LABELS, "macro") for mt in ("precision", "recall", "f1")] + [("all", "accuracy")]
             + [(lb, mt) for lb in ("loss", "loss_all") for mt in ("precision", "recall", "f1")])
    for sc in schemes:
        note = ". ".join([sc["note"], *extra_notes, *notes]) + "."
        for label, metric in specs:
            row = {c: "" for c in columns}
            row.update(scheme=sc["name"], label=label, metric=metric, n_labelled=sc.get("n_labelled", len(sc["idx"])),
                       note=note,
                       **{k: sc[k] for k in ("n_labelled_disagree", "N_disagree", "n_labelled_agree", "N_agree")})
            for m in methods:
                v = cell(sc["name"], m, label, metric)
                if v is None:
                    continue
                row[m] = float(v[0])
                if len(v) > 1:
                    row[f"{m}_lo"], row[f"{m}_hi"] = ci(v)
            pairs = {}
            for a_i, a in enumerate(rule_ms):
                for b in rule_ms[a_i + 1:]:
                    va, vb = cell(sc["name"], a, label, metric), cell(sc["name"], b, label, metric)
                    if va is not None and vb is not None:
                        d = vb - va  # paired: the same weight replicates for both versions
                        pairs[f"{vname[b]}_minus_{vname[a]}"] = (float(d[0]), *(ci(d) if len(d) > 1 else ("", "")))
            for ver in version_files:
                p_ = pairs.get(f"{ver}_minus_v1")
                if p_:
                    row[f"{ver}_minus_v1"] = p_[0]
                    if p_[1] != "":
                        row[f"{ver}_minus_v1_lo"], row[f"{ver}_minus_v1_hi"] = p_[1], p_[2]
            row["pairs"] = pairs
            sup = cell(sc["name"], "rule", label, "support")
            if sup is not None:
                row["support"] = float(sup[0])
            rows.append(row)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=columns)
        wr.writeheader()
        for r in rows:
            wr.writerow({k: (f"{r[k]:.4f}" if isinstance(r[k], float) else r[k]) for k in columns})
    return rows


def format_metrics(rows: list[dict], scheme: str = "weighted") -> str:
    """F1 per label, macro F1 and accuracy of each method side by side (plain text)."""

    def fmt(r: dict, m: str) -> str:
        v = r.get(m)
        if v in ("", None):
            return "-"
        lo, hi = r.get(f"{m}_lo"), r.get(f"{m}_hi")
        return f"{v:.3f}" + (f" [{lo:.2f}, {hi:.2f}]" if lo not in ("", None) else "")

    sel = [r for r in rows if r["scheme"] == scheme and (r["metric"] in ("f1", "accuracy"))]  # incl. loss F1
    versions = sorted({k[5:] for r in sel for k in r if re.fullmatch(r"rule_v\d+", k)}, key=lambda v: int(v[1:]))
    order = ("rule", *(m for v in versions for m in (f"rule_{v}", f"{v}_minus_v1")), "llm", *STRONG, "gemini",
             "claude")
    methods = [m for m in order if any(r.get(m) not in ("", None) for r in sel)]
    if not methods:
        return f"{scheme}: no estimates"
    title = f"{scheme} ({'labelled rows only' if scheme == 'unweighted' else '95% CI'})"
    width = max(len(title), 18) + 2
    lines = [title.ljust(width) + "".join(m.ljust(24) for m in methods)]
    for r in sel:
        name = f"{r['label']} {r['metric']}" if r["metric"] != "accuracy" else "accuracy"
        lines.append(name.ljust(width) + "".join(fmt(r, m).ljust(24) for m in methods))
    return "\n".join(lines)


# --- stage 1: prepare ------------------------------------------------------------------------------

_WORKER_EX = None


def _init_worker(agent_names: list[str], salt: bytes) -> None:
    global _WORKER_EX
    from avsd.lineage.anchors import AnchorExtractor, load_nlp

    _WORKER_EX = AnchorExtractor(agent_names, salt, load_nlp())


def _occ_worker(item: tuple[str, str]) -> tuple[str, DocInfo]:
    rid, text = item
    return rid, text_occurrences(_WORKER_EX, text)


def read_texts(text_path: Path, ids: set[str]) -> dict[str, str]:
    """content of the given memory rows, reading one row group at a time."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    if not ids:
        return {}
    pf = pq.ParquetFile(text_path)
    want = pa.array(sorted(ids))
    out: dict[str, str] = {}
    for g in range(pf.metadata.num_row_groups):
        idcol = pf.read_row_group(g, columns=["id"]).column("id")
        if not pc.any(pc.is_in(idcol, value_set=want)).as_py():
            continue
        tb = pf.read_row_group(g, columns=["id", "content"])
        tb = tb.filter(pc.is_in(tb.column("id"), value_set=want))
        for rid, text in zip(tb.column("id").to_pylist(), tb.column("content").to_pylist()):
            out[rid] = text or ""
    return out


def _earlier_from_spells(restored: list[dict], facts_path: Path, pos: dict, salt: bytes) -> dict[int, int]:
    """Row index (in the agent's live rows) of the last row holding each restored unit before PREV.

    Uses B1's presence spells (memory_facts.parquet): a spell ends at the first row without the
    unit, so the last row with it is the row before spell_end_row_id.
    """
    import polars as pl

    from avsd.lineage.anchors import display_value

    if not restored or not facts_path.exists():
        return {}
    agents = sorted({u["agent_id"] for u in restored})
    types = sorted({parse_unit_key(u["unit_key"])[0] for u in restored})
    facts = (pl.scan_parquet(facts_path)
             .filter(pl.col("agent_id").is_in(agents) & pl.col("anchor_type").is_in(types)
                     & pl.col("spell_end_row_id").is_not_null())
             .select("agent_id", "anchor_type", "value", "ctx", "spell_end_row_id")
             .collect())
    out: dict[int, int] = {}
    for u in restored:
        t, kv, kc = parse_unit_key(u["unit_key"])
        f = facts.filter((pl.col("agent_id") == u["agent_id"]) & (pl.col("anchor_type") == t))
        if t in QUANTITY:
            f = f.filter(pl.col("ctx") == kc)
        if t == "url" and not kv.startswith("h:"):
            vals = f["value"].to_list()
            keep = [display_value(t, v, salt) == kv for v in vals]
            f = f.filter(pl.Series(keep, dtype=pl.Boolean))
        elif kv.endswith("...") and len(kv) == 80:
            f = f.filter(pl.col("value").str.starts_with(kv[:77]) & (pl.col("value").str.len_chars() > 80))
        else:
            f = f.filter(pl.col("value") == kv)
        prev_idx = pos[(u["agent_id"], u["prev_uid"])]
        ends = [pos.get((u["agent_id"], e)) for e in f["spell_end_row_id"].to_list()]
        ends = [e for e in ends if e is not None and e <= prev_idx]
        if ends:
            out[u["row"]] = max(ends) - 1
    return out


def prepare(cfg: dict, workers: int = 4, log=print) -> dict:
    """Stage 1: recover units, build masked excerpts and prompts, write requests.jsonl."""
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor

    import polars as pl

    from avsd.lineage.anchors import QUANTITY_TYPES, AnchorExtractor, load_nlp, load_salt
    from avsd.lineage.memory import live_rows

    assert QUANTITY == QUANTITY_TYPES
    t0 = time.perf_counter()
    paths = cfg["paths"]
    labels_dir, interim, processed = Path(paths["labels"]), Path(paths["interim"]), Path(paths["processed"])
    pairs_path = labels_dir / PAIRS_FILE
    pairs_sha = hashlib.sha256(pairs_path.read_bytes()).hexdigest()
    with open(pairs_path, encoding="utf-8", newline="") as f:
        units = [dict(r, row=i) for i, r in enumerate(csv.DictReader(f))]
    agents = pl.read_parquet(processed / "agents.parquet")
    agent_names = agents["name"].to_list()
    name_of = dict(agents.select("agent_id", "name").iter_rows())
    salt = load_salt(interim)
    seed = int(cfg["seed"])

    # Live rows (B1 order) of the agents in the sample.
    a_ids = sorted({u["agent_id"] for u in units})
    mv = pl.read_parquet(interim / "memory_versions.parquet").filter(pl.col("agent_id").is_in(a_ids))
    rows, _ = live_rows(mv)
    rows = rows.select("id", "agent_id", "created_at", "is_cons", "idx")
    pos = {(a, rid): int(i) for rid, a, i in rows.select("id", "agent_id", "idx").iter_rows()}
    row_ids = {a: g.sort("idx")["id"].to_list() for (a,), g in rows.group_by(["agent_id"])}
    created = dict(zip(rows["id"].to_list(), rows["created_at"].to_list()))
    cons_cum = {a: list(itertools.accumulate(int(x) for x in g.sort("idx")["is_cons"].to_list()))
                for (a,), g in rows.group_by(["agent_id"])}
    bad_pairs = sum(1 for u in units
                    if pos.get((u["agent_id"], u["next_uid"]), -9) - pos.get((u["agent_id"], u["prev_uid"]), -99) != 1)

    restored = [u for u in units if u["rule_label"] == "restored"]
    earlier_idx = _earlier_from_spells(restored, interim / "memory_facts.parquet", pos, salt)
    need = {u["prev_uid"] for u in units} | {u["next_uid"] for u in units}
    for u in restored:
        if earlier_idx.get(u["row"]) is not None:
            need.add(row_ids[u["agent_id"]][earlier_idx[u["row"]]])
    texts = read_texts(Path(paths["tables"]) / "agent_memories_text.parquet", need)
    missing_text = len(need - texts.keys())
    t1 = time.perf_counter()
    log(f"prepare: {len(units)} units, {len({u['pair_id'] for u in units})} pairs, {len(texts)} texts "
        f"({sum(len(t) for t in texts.values()):,} chars); earlier rows from spells {len(earlier_idx)}/"
        f"{len(restored)}")

    docs: dict[str, DocInfo] = {}
    items = sorted(texts.items(), key=lambda kv: -len(kv[1]))
    with ProcessPoolExecutor(max(1, min(workers, len(items))), mp_context=mp.get_context("spawn"),
                             initializer=_init_worker, initargs=(agent_names, salt)) as ex:
        for rid, d in ex.map(_occ_worker, items, chunksize=1):
            docs[rid] = d
    t2 = time.perf_counter()
    log(f"prepare: anchors with spans for {len(docs)} texts in {t2 - t1:.0f} s")

    extractor = None
    st = Counter()
    records = []
    for u in units:
        t, kv, kc = parse_unit_key(u["unit_key"])
        um = UnitMatcher(u["unit_key"], salt)
        prev_d, next_d = docs.get(u["prev_uid"]), docs.get(u["next_uid"])
        if prev_d is None or next_d is None:
            st["missing_text"] += 1
            continue
        occ_p, occ_n = um.find(prev_d), um.find(next_d)
        lemma = um.recover_ctx([prev_d, next_d])
        if um.quantity:
            contexts = [lemma] if lemma else []
        else:
            contexts = sorted({o.lemma for o in occ_p + occ_n if o.lemma} | ({lemma} if lemma else set()))
        surf_p = [prev_d.text[o.start:o.end] for o in occ_p]
        surf_n = [next_d.text[o.start:o.end] for o in occ_n]
        plain = not (kv.startswith("h:") or kv.endswith("...") or t == "url")
        fallback = [kv] if plain and not (surf_p or surf_n) else []
        ev_p = version_evidence(prev_d, um, contexts, surf_n or fallback)
        ev_n = version_evidence(next_d, um, contexts, surf_p or fallback)

        # Earlier version for rule label "restored".
        earlier = None
        earlier_cell = ""
        e_src = ""
        if u["rule_label"] == "restored":
            a = u["agent_id"]
            ei = earlier_idx.get(u["row"])
            e_doc = None
            if ei is not None and ei >= 0:
                e_src = "spell"
                e_doc = docs.get(row_ids[a][ei])
            if e_doc is None or not um.find(e_doc):
                # Backward scan (rare): recompute anchors on earlier rows until the unit appears.
                if extractor is None:
                    extractor = AnchorExtractor(agent_names, salt, load_nlp())
                p_idx = pos[(a, u["prev_uid"])]
                ei, e_doc, e_src = None, None, ""
                ids_back = row_ids[a][max(0, p_idx - EARLIER_SCAN_ROWS):p_idx][::-1]
                back_texts = read_texts(Path(paths["tables"]) / "agent_memories_text.parquet",
                                        {x for x in ids_back if x not in docs})
                for k, rid in enumerate(ids_back):
                    if rid not in docs:
                        docs[rid] = text_occurrences(extractor, back_texts.get(rid, ""))
                    if um.find(docs[rid]):
                        ei, e_doc, e_src = p_idx - 1 - k, docs[rid], "scan"
                        break
            if e_doc is not None and ei is not None:
                ev_e = version_evidence(e_doc, um, contexts, surf_p + surf_n or fallback, max_windows=1)
                # Rewrites after the earlier version and before NEXT.
                n_cons = cons_cum[a][pos[(a, u["next_uid"])] - 1] - cons_cum[a][ei]
                when = created.get(row_ids[a][ei])
                day = f"{when:%Y-%m-%d}, " if when is not None else ""
                note = f"{day}{n_cons} rewrite{'s' if n_cons != 1 else ''} between it and NEXT"
                earlier = (ev_e.windows, note)
                earlier_cell = f"({note}) " + join_windows(ev_e.windows, 0) if ev_e.windows else ""
                st["earlier_found"] += bool(ev_e.windows)
                st[f"earlier_{e_src}"] += 1
            if not earlier_cell:
                earlier_cell = "(no earlier version holding the unit was found)"
                st["earlier_missing"] += 1

        # Raw value: the first surface form, masked when it is credential-like.
        surfaces = surf_p + surf_n
        value = surfaces[0] if surfaces else ("" if kv.startswith("h:") else kv)
        masked_value = ev_p.masked_value or ev_n.masked_value or bool(value and mask_text(value) != value)
        if masked_value:
            value = MASK
        st["masked_value"] += masked_value
        ctx_disp = lemma if lemma is not None else kc
        value_for_prompt = value or "(not recovered; see the marked text in the excerpts)"
        value = value or "(not recovered)"
        messages = build_messages(t, value_for_prompt, ctx_disp or "",
                                  (ev_p.windows, ev_p.n_unit + ev_p.n_literal, ev_p.n_ctx),
                                  (ev_n.windows, ev_n.n_unit + ev_n.n_literal, ev_n.n_ctx), earlier)
        present_p, present_n = bool(occ_p), bool(occ_n)
        expect = {"kept": (True, True), "modified": (True, False), "dropped": (True, False),
                  "new": (False, True), "restored": (False, True)}[u["rule_label"]]
        st["consistent"] += (present_p, present_n) == expect
        st["unit_found_prev"] += present_p
        st["unit_found_next"] += present_n
        st["literal_prev"] += ev_p.n_literal > 0
        st["literal_next"] += ev_n.n_literal > 0
        st["ctx_prev"] += ev_p.n_ctx > 0
        st["ctx_next"] += ev_n.n_ctx > 0
        st["no_window_prev"] += not ev_p.windows
        st["no_window_next"] += not ev_n.windows
        st["value_unrecovered"] += not surfaces
        st["ctx_hash_unrecovered"] += lemma is None
        records.append({
            "row": u["row"], "pair_id": u["pair_id"], "agent_id": u["agent_id"],
            "agent": name_of.get(u["agent_id"], ""), "prev_uid": u["prev_uid"], "next_uid": u["next_uid"],
            "unit_key": u["unit_key"], "rule_label": u["rule_label"], "unit_type": t, "value": value,
            "context_key": ctx_disp or "",
            "prev_excerpt": join_windows(ev_p.windows, ev_p.left) or "(neither the value nor its context occurs in PREV)",
            "next_excerpt": join_windows(ev_n.windows, ev_n.left) or "(neither the value nor its context occurs in NEXT)",
            "earlier_excerpt": earlier_cell,
            "found": {"prev": len(occ_p), "next": len(occ_n), "lit_prev": ev_p.n_literal,
                      "lit_next": ev_n.n_literal, "ctx_prev": ev_p.n_ctx, "ctx_next": ev_n.n_ctx,
                      "consistent": (present_p, present_n) == expect, "earlier": e_src},
            "messages": messages,
            "key": request_key(messages, seed),
        })
    t3 = time.perf_counter()
    out = cache_dir(cfg)
    out.mkdir(parents=True, exist_ok=True)
    os.chmod(out, 0o700)
    with _private_open(out / "requests.jsonl", "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    by_label = Counter(u["rule_label"] for u in units)
    cons_by_label = Counter(r["rule_label"] for r in records if r["found"]["consistent"])
    stats = {
        "created": _now(), "pairs_file_sha256": pairs_sha, "units": len(units), "records": len(records),
        "pairs": len({u["pair_id"] for u in units}), "agents": len(a_ids), "texts": len(texts),
        "text_chars": sum(len(t) for t in texts.values()), "missing_text": missing_text,
        "pairs_not_adjacent": bad_pairs, "by_label": dict(by_label), "consistent_by_label": dict(cons_by_label),
        "restored": len(restored), "counts": dict(st), "seconds": round(t3 - t0, 1),
        "seconds_anchors": round(t2 - t1, 1), "prompt_version": PROMPT_VERSION,
    }
    (out / "prepare_stats.json").write_text(json.dumps(stats, indent=1))
    log(f"prepare: {len(records)} requests; unit presence consistent with the rule label for "
        f"{st['consistent']}/{len(records)}; masked values {st['masked_value']}; {t3 - t0:.0f} s")
    return stats


# --- stage 2: infer (vLLM env) ---------------------------------------------------------------------

def _structured_kwargs(schema: dict) -> dict:
    """SamplingParams keyword for JSON-schema decoding across vLLM versions."""
    try:
        from vllm.sampling_params import StructuredOutputsParams

        try:
            return {"structured_outputs": StructuredOutputsParams(json=schema, disable_any_whitespace=True)}
        except TypeError:
            return {"structured_outputs": StructuredOutputsParams(json=schema)}
    except ImportError:
        from vllm.sampling_params import GuidedDecodingParams

        try:
            return {"guided_decoding": GuidedDecodingParams(json=schema, disable_any_whitespace=True)}
        except TypeError:
            return {"guided_decoding": GuidedDecodingParams(json=schema)}


def _gpu_name() -> str:
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                           capture_output=True, text=True, timeout=30, check=False)
        return "; ".join(x.strip() for x in r.stdout.splitlines() if x.strip())
    except (OSError, subprocess.SubprocessError):
        return "unknown"


PROBE = 16  # the run stops if none of the first PROBE finished answers validates


def load_model_cache(out: Path, spec: ModelSpec) -> dict[str, dict]:
    """Cached entries of one model with an output, by key."""
    return {e["key"]: e for e in _read_jsonl(out / cache_file(spec)) if e.get("output") is not None}


def answer_attempts(spec: ModelSpec, messages: list[dict], seed: int, cache: dict[str, dict],
                    task: LabelTask | None = None, req: dict | None = None) -> tuple[dict | None, int | None, int]:
    """(entry of the first attempt whose answer validates, its attempt index, attempts cached).

    Without a valid attempt the entry is the last cached one (or None) and the index None."""
    last, n = None, 0
    for a in range(len(spec.budgets)):
        e = cache.get(model_request_key(spec, messages, seed, a, task))
        if e is None:
            break
        n, last = n + 1, e
        if answer_ok(spec, e["output"], task, req):
            return e, a, n
    return last, None, n


def next_attempt(spec: ModelSpec, messages: list[dict], seed: int, cache: dict[str, dict],
                 task: LabelTask | None = None, req: dict | None = None) -> int | None:
    """Index of the attempt to generate next, or None (valid answer cached, or retries used up)."""
    _, a, n = answer_attempts(spec, messages, seed, cache, task, req)
    if a is not None or n >= len(spec.budgets):
        return None
    return n


def infer(cfg: dict, model_dir: str | Path, spec: ModelSpec = QWEN3_14B, max_model_len: int | None = None,
          gpu_memory_utilization: float | None = None, enforce_eager: bool | None = None,
          limit: int | None = None, log=print, tasks: list | None = None) -> list[dict]:
    """Stage 2: generate the requests that one model has not answered yet, for one or more tasks.

    tasks: (LabelTask or None for B1, cache dir) pairs; default B1 in `cache_dir(cfg)`. Each task reads
    the cached requests of its dir (the same messages for every model) and writes cache_<model>.jsonl
    (Qwen3-14B on B1 keeps cache.jsonl) and runs_<model>.jsonl there; the model is loaded once for
    all tasks. A reasoning model may reason freely; vLLM's reasoning parser starts the JSON-schema
    constraint at the end of the reasoning, and an output without an answer that validates is
    retried with the next budget (`ModelSpec.budgets`). Every attempt is cached with the rendered
    prompt and the raw output (special tokens kept for reasoning models). `limit` generates only the
    first `limit` requests of each task (a smoke test). Returns one run record per task."""
    tasks = tasks or [(None, cache_dir(cfg))]
    state: dict = {"llm": None, "tok": None, "load_s": 0.0}
    settings = {"eager": spec.enforce_eager if enforce_eager is None else bool(enforce_eager),
                "gmu": gpu_memory_utilization or spec.gpu_memory_utilization,
                "mml": int(max_model_len or spec.max_model_len), "model_dir": model_dir}
    return [_infer_task(cfg, spec, task, Path(out), settings, state, limit, log) for task, out in tasks]


def _load_llm(spec: ModelSpec, settings: dict, seed: int, state: dict, log=print) -> None:
    md = Path(settings["model_dir"]).expanduser()
    marker = md / ".avsd_revision"
    if not (marker.exists() and marker.read_text().strip() == spec.revision and _weights_complete(md)):
        raise SystemExit(f"infer: no complete {spec.model_id}@{spec.revision[:12]} weights in {md}; "
                         "run the download stage first")
    import vllm
    from vllm import LLM

    t0 = time.perf_counter()
    kw = {"model": str(md), "tokenizer": str(md), "dtype": spec.dtype, "seed": seed,
          "max_model_len": settings["mml"], "gpu_memory_utilization": settings["gmu"],
          "enforce_eager": settings["eager"], "enable_prefix_caching": spec.prefix_caching,
          "tensor_parallel_size": spec.tensor_parallel}
    if spec.reasoning_parser:
        kw["reasoning_parser"] = spec.reasoning_parser
    if spec.text_only:
        kw["language_model_only"] = True
    state["llm"] = LLM(**kw)
    state["tok"] = state["llm"].get_tokenizer()
    state["load_s"] = round(time.perf_counter() - t0, 1)
    state["vllm"] = getattr(vllm, "__version__", "?")
    try:
        import torch

        state["torch"] = torch.__version__
    except ImportError:
        pass
    log(f"infer: {spec.name} loaded in {state['load_s']:.0f} s")


def _infer_task(cfg: dict, spec: ModelSpec, task: LabelTask | None, out: Path, settings: dict, state: dict,
                limit: int | None, log=print) -> dict:
    reqs = _read_jsonl(out / "requests.jsonl")
    if not reqs:
        raise SystemExit(f"no requests in {out}; run the prepare stage first")
    seed = int(cfg["seed"])
    name = task.name if task else "memory"
    if spec.key == QWEN3_14B.key and task is None:
        assert all(model_request_key(spec, r["messages"], seed) == r["key"] for r in reqs[:5]), "cache key drift"
    uniq: dict[str, dict] = {}
    for r in reqs:
        uniq.setdefault(model_request_key(spec, r["messages"], seed, 0, task), r)
    pool = list(uniq.values())[:limit] if limit else list(uniq.values())
    cache = load_model_cache(out, spec)
    run = {"started": _now(), "task": name, "model": spec.model_id, "revision": spec.revision,
           "model_key": spec.key, "requests": len(reqs), "unique_prompts": len(uniq), "limit": limit,
           "generated": 0, "generated_by_attempt": {}, "prompt_tokens": 0, "output_tokens": 0, "seed": seed,
           "sampling": model_sampling(spec, seed), "budgets": list(spec.budgets),
           "chat_template_kwargs": dict(spec.template_kwargs), "reasoning": spec.reasoning,
           "reasoning_parser": spec.reasoning_parser, "structured_output": "json_schema" + (
               " after the reasoning" if spec.reasoning_parser else ""),
           "tensor_parallel": spec.tensor_parallel, "language_model_only": spec.text_only,
           "enforce_eager": settings["eager"], "max_model_len": settings["mml"],
           "gpu_memory_utilization": settings["gmu"],
           "prompt_version": task.prompt_version if task else PROMPT_VERSION}
    run["cached"] = sum(1 for r in pool if next_attempt(spec, r["messages"], seed, cache, task, r) is None)
    t0 = time.perf_counter()
    gen_s = 0.0
    while True:
        todo = [(r, next_attempt(spec, r["messages"], seed, cache, task, r)) for r in pool]
        todo = [(r, a) for r, a in todo if a is not None]
        if not todo:
            break
        attempt = min(a for _, a in todo)
        batch = [r for r, a in todo if a == attempt]
        if state["llm"] is None:
            _load_llm(spec, settings, seed, state, log)
            run["seconds_load"] = state["load_s"]
        t1 = time.perf_counter()
        # A broken setup stops after the first PROBE answers, not after hours.
        res = _generate(state["llm"], state["tok"], spec, batch, seed, attempt, out, cache, run,
                        probe=PROBE if attempt == 0 and not run["generated"] else 0, log=log, task=task)
        gen_s += time.perf_counter() - t1
        log(f"infer: {spec.key} {name} attempt {attempt}: {len(batch)} generated, "
            f"{sum(1 for x in res if x['schema_ok'])} valid, {time.perf_counter() - t1:.0f} s; finish reasons "
            + ", ".join(f"{k} {v}" for k, v in sorted(Counter(x['finish_reason'] for x in res).items())))
    for k in ("vllm", "torch"):
        if k in state:
            run[k] = state[k]
    final = [answer_attempts(spec, r["messages"], seed, cache, task, r) for r in pool]
    run["valid"] = sum(1 for _, a, _ in final if a is not None)
    run["valid_by_attempt"] = dict(Counter(str(a) for _, a, _ in final if a is not None))
    run["invalid_after_retries"] = sum(1 for _, a, n in final if a is None and n >= len(spec.budgets))
    run["seconds_generate"] = round(gen_s, 1)
    run["gpu"] = _gpu_name()
    run["seconds"] = round(time.perf_counter() - t0, 1)
    run["finished"] = _now()
    run["slurm_job"] = os.environ.get("SLURM_JOB_ID", "")
    run["node"] = os.uname().nodename
    with _private_open(out / runs_file(spec), "a", encoding="utf-8") as f:
        f.write(json.dumps(run) + "\n")
    log(f"infer: {spec.key} {name}: {run['generated']} generated, {run['cached']} cached, valid {run['valid']}/"
        f"{len(pool)}, {run['seconds']:.0f} s, GPU {run['gpu']}")
    return run


def _sampling_params(spec: ModelSpec, smp: dict, schema: dict = OUTPUT_SCHEMA):
    """vLLM SamplingParams of one attempt: JSON-schema output, special tokens kept for reasoning models."""
    from vllm import SamplingParams

    kw = {k: v for k, v in smp.items() if k not in ("max_tokens", "seed")}
    return SamplingParams(max_tokens=smp["max_tokens"], seed=smp["seed"], skip_special_tokens=not spec.reasoning,
                          **kw, **_structured_kwargs(schema))


def _finished_outputs(llm, prompts: list[str], sp):
    """(index, RequestOutput) of every prompt, as soon as each one finishes.

    Uses LLM.enqueue and the engine's step loop (as LLM.generate does) so that a caller can store
    answers while the rest still run; falls back to LLM.generate on vLLM versions without enqueue."""
    if not hasattr(llm, "enqueue"):
        yield from enumerate(llm.generate(prompts, sp, use_tqdm=False))
        return
    ids = llm.enqueue(prompts, sp, use_tqdm=False)
    pos: dict[str, int] = {}
    for j, rid in enumerate(ids):
        pos[str(rid)] = j
        pos.setdefault(str(rid).rsplit("-", 1)[0], j)  # outputs carry the id given before vLLM's suffix
    engine = llm.llm_engine
    while engine.has_unfinished_requests():
        for o in engine.step():
            if not getattr(o, "finished", False):
                continue
            rid = str(o.request_id)
            j = pos.get(rid, pos.get(rid.rsplit("-", 1)[0]))
            if j is None:
                raise RuntimeError(f"unknown request id {rid!r} in the engine output")
            yield j, o


def _generate(llm, tok, spec: ModelSpec, batch: list[dict], seed: int, attempt: int, out: Path,
              cache: dict[str, dict], run: dict, probe: int = 0, log=print, every: float = 300.0,
              task: LabelTask | None = None) -> list[dict]:
    """Generate one attempt for a batch and append each answer to the cache file as soon as it is
    finished (flushed, so a killed job keeps what it has). Logs progress every `every` seconds.
    probe: stop the run when none of the first `probe` finished answers validates. Returns the parse
    results in completion order (task None, B1: `parse_answer`; else schema_ok and error only)."""
    schema = OUTPUT_SCHEMA if task is None else task.schema
    smp = model_sampling(spec, seed, attempt)
    sp = _sampling_params(spec, smp, schema)
    tkw = dict(spec.template_kwargs)
    prompts = [tok.apply_chat_template(r["messages"], tokenize=False, add_generation_prompt=True, **tkw)
               for r in batch]
    res: list[dict] = []
    toks = 0
    t0 = last = time.perf_counter()
    with _private_open(out / cache_file(spec), "a", encoding="utf-8") as f:
        for j, o in _finished_outputs(llm, prompts, sp):
            r, p, c = batch[j], prompts[j], o.outputs[0]
            key = model_request_key(spec, r["messages"], seed, attempt, task)
            entry = {
                "key": key, "created": _now(), "model": spec.model_id, "revision": spec.revision,
                "model_key": spec.key, "attempt": attempt, "task": task.name if task else "memory",
                "prompt_version": task.prompt_version if task else PROMPT_VERSION,
                "messages": r["messages"], "chat_template_kwargs": tkw, "prompt": p, "sampling": smp,
                "schema": schema, "reasoning_parser": spec.reasoning_parser, "output": c.text,
                "finish_reason": c.finish_reason, "prompt_tokens": len(o.prompt_token_ids or []),
                "output_tokens": len(c.token_ids or []),
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
            cache[key] = entry
            run["prompt_tokens"] += entry["prompt_tokens"]
            run["output_tokens"] += entry["output_tokens"]
            run["generated"] += 1
            run["generated_by_attempt"][str(attempt)] = run["generated_by_attempt"].get(str(attempt), 0) + 1
            toks += entry["output_tokens"]
            if task is None:
                pr = parse_answer(c.text, spec.reasoning)
            else:
                ok = answer_ok(spec, c.text, task, r)
                pr = {"schema_ok": ok, "error": "" if ok else "invalid"}
            pr["finish_reason"] = c.finish_reason
            res.append(pr)
            if probe and len(res) == probe and not any(x["schema_ok"] for x in res):
                raise SystemExit(f"infer: none of the first {probe} answers of {spec.key} validates "
                                 f"(errors: {dict(Counter(x['error'] for x in res))}); stopping")
            now = time.perf_counter()
            if now - last >= every:
                log(f"infer: {spec.key} attempt {attempt}: {len(res)}/{len(batch)} done, "
                    f"{sum(1 for x in res if x['schema_ok'])} valid, {toks:,} output tokens, {now - t0:.0f} s")
                last = now
    return res


# --- stage 3: report --------------------------------------------------------------------------------

def _cell(v) -> str:
    """CSV cell; a leading space keeps Excel from reading '=', '+', '-' or '@' as a formula."""
    s = "" if v is None else str(v)
    return " " + s if s[:1] in ("=", "+", "-", "@") else s


README_TEXT = """# memory_pairs_review.csv 复核说明

这张表有 {n_rows} 行，每行是一个事实单元在一对相邻 memory 版本之间的状态，用于校验 B1 规则方法（SPEC 6.3.4）。PREV 是某次 memory 重写（consolidation）的输入版本，NEXT 是重写后的输出版本。prev_excerpt、next_excerpt 是两个版本中围绕这个值截取的片段，每段约 300 字符：⟦ ⟧ 标出与单元取值相同的文字，⟨ ⟩ 标出同一上下文中的其他取值，… 表示截断，↵ 是换行，«masked» 是遮掉的密码、token 等凭证，(+N more matches) 表示还有 N 处同样的取值没有列出。earlier_excerpt 取自 PREV 之前最近一个含有该单元的版本；只有规则 v1 判为 restored 的单元检索过更早的版本，其他行没有这一列的内容。用 Excel 或 Numbers 直接打开即可。

两个本地模型各自独立预标：qwen35_label、qwen35_confidence、qwen35_rationale 来自 Qwen3.5-122B-A10B，gptoss_label、gptoss_confidence、gptoss_rationale 来自 gpt-oss-120b。它们看到的片段和表中相同，看不到规则的结果，也看不到对方的结果。两个模型一致时 suggested_label 填这个标签，不一致时留空。模型也会出错（抽查结果见 outputs/qa/memory_prelabel.md），suggested_label 只供参考，请按片段独立判断。规则方法 v1、v2、v3 的结果和早先 Qwen3-14B 的预标不在表中显示，因为人工标注正是用来评估它们的，统计时按 unit_key 从其他文件对回。旧表备份为 memory_pairs_review_qwen14b.csv，不需要再看。

第一列 review_priority 是复核优先级，表格已按它排序。1-必标 共 {n1} 行：design_stratum 为 A 的 {nA} 行是两个模型不一致（或有一个没有给出有效答案）；为 B 的 {nB} 行是两个模型一致，但三版规则中至少一版给出不同结果。其余 {nC} 行两个模型与三版规则全部一致（design_stratum 为 C:标签），从中按建议标签分层随机抽出 {n2} 行作为 2-抽样（种子 {seed}），剩下 {n3} 行是 3-可选。请标完全部 1-必标 和 2-抽样，共 {n12} 行；3-可选 不用标，标了也只进入不加权的参考统计。inclusion_prob 是这一行进入必标或抽样的概率：A、B 层为 1，C 层为该层抽样行数除以该层行数。统计时每个已标行按 1/inclusion_prob 加权，代表全部 {n_rows} 行。三版规则之间互相不一致的单元全部在 A、B 层，所以比较 v1、v2、v3 时不受抽样误差影响。

请在 human_label 列填写 kept、modified、dropped、new、restored 之一（小写英文）。只看片段无法判断时，在 notes 写明原因，human_label 留空，留空的行不进入统计。单元本身抽错了（比如把编号当成数字），仍按这个值在两个版本中是否出现来填，并在 notes 写 bad_unit。数字、金额、百分比和时刻要连同上下文一起看，“56 位捐款人”和“56 天”是两个单元；其他类型只看取值。
- kept：PREV 和 NEXT 都有这个事实，写法可以不同。
- modified：PREV 有；NEXT 里这个事实还在，但取值换了，例如捐款人数从 56 变成 60。
- dropped：PREV 有；NEXT 里既没有这个值，也没有同一事实的新值。
- new：PREV 没有，NEXT 有，表中也没有更早的版本含有它。
- restored：PREV 没有，NEXT 有，更早的版本里出现过（见 earlier_excerpt）。

两个容易出错的地方（第三方抽查时模型常在这里出错）：一是 ⟦ ⟧ 只标出程序找到的匹配，同一个值换了写法（例如日期里用了别的连字符，或 “56 位捐款人” 写成 “捐款人：56”）不会被标出，请以片段原文为准；二是 earlier_excerpt 只说明更早的版本出现过相同的取值和上下文词，只有那里说的是同一个事实才算 restored，同一个数字或词用在不相关的地方应标 new。

表中有 memory 原文片段，含人名、邮箱、电话等个人信息。文件只能留在 `data/labels/`（已写入 .gitignore），不要分享、上传或提交到 git。design_stratum、inclusion_prob 和最后一列 unit_key 用于统计和对回 memory_pairs.csv，请勿修改。填完或填完一部分后，在 GRASP 上 `source scripts/env.sh`，再运行 `python -m avsd.lineage.prelabel metrics`，结果写入 `outputs/tables/memory_label_metrics.csv`：三版规则（rule、rule_v2、rule_v3）、Qwen3-14B（llm）和两个模型（qwen35_122b、gptoss_120b）相对人工标注的精确率、召回率与 F1，含按设计加权的估计和 95% 置信区间，也列出不加权的结果；只用已填写的行。
"""


def _fmt(x: float, nd: int = 3) -> str:
    return "n/a" if x is None or math.isnan(x) else f"{x:.{nd}f}"


def _md_table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _scanner_hits(cells: list[str]) -> Counter | None:
    """Hits of scripts/scan_credentials.py in the sheet (kinds only), or None if unavailable.

    A hit whose value is the mask is not a credential and is not counted.
    """
    import importlib.util

    from avsd.config import REPO_ROOT

    path = REPO_ROOT / "scripts" / "scan_credentials.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("_avsd_scan_credentials", path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:  # noqa: BLE001 - the check is optional
        return None
    c: Counter = Counter()
    for cell in cells:
        if cell:
            for h in mod._hits_in(cell):
                # "password: «masked»" reads as an assignment whose value is the mask itself.
                if h["strength"] != "weak" and not h["training_context"] \
                        and not cell.startswith(MASK, h["pos"]):
                    c[h["kind"]] += 1
    return c


# --- re-check comparison (aggregates only) -----------------------------------------------------------

METHOD_NAMES: dict[str, str] = {
    "qwen3_14b": "Qwen3-14B", "qwen35_122b": "Qwen3.5-122B", "gptoss_120b": "gpt-oss-120b",
    "rule_v1": "rules v1", "rule_v2": "rules v2", "rule_v3": "rules v3",
    "gemini": "Gemini 3.1 Pro (new prompt)", "claude": "Claude (blind)",
}
LLM_KEYS: tuple[str, ...] = (QWEN3_14B.key, *STRONG)
EVIDENCE_GROUPS: tuple[str, ...] = (
    "value in PREV and NEXT",
    "value in PREV only; another value in its context in NEXT",
    "value in PREV only; nothing else in its context in NEXT",
    "value in NEXT only; earlier version shown",
    "value in NEXT only; no earlier version shown",
    "value in neither",
)
ADJ_STRATA: tuple[str, ...] = ("D1", "D2")  # strong models disagree; they agree against Qwen3-14B
ADJ_COLUMNS: tuple[str, ...] = ("pair_id", "unit_key", "stratum", "judge_label", "judge_confidence",
                                "judge_note")


def model_answers(reqs: list[dict], out: Path, seed: int, specs=None) -> dict[str, list[dict | None]]:
    """Per model with a cache file and per request: `parse_answer` of the first attempt that validates
    (or of the last attempt cached), with attempt (index of the valid attempt, None if none),
    attempts (number cached), finish_reason and output_tokens; None if never generated."""
    res: dict[str, list[dict | None]] = {}
    for spec in (specs or MODELS.values()):
        cache = load_model_cache(out, spec)
        if not cache:
            continue
        rows: list[dict | None] = []
        for r in reqs:
            e, a, n = answer_attempts(spec, r["messages"], seed, cache)
            if e is None:
                rows.append(None)
                continue
            p = parse_answer(e["output"], spec.reasoning)
            p.update(attempt=a, attempts=n, finish_reason=e.get("finish_reason"),
                     output_tokens=int(e.get("output_tokens") or 0))
            rows.append(p)
        res[spec.key] = rows
    return res


def model_label_lists(answers: dict[str, list[dict | None]]) -> dict[str, list[str]]:
    """The label of each model's valid answer, '' when it has none."""
    return {k: [(p["label"] if p and p.get("attempt") is not None else "") for p in v] for k, v in answers.items()}


def rule_labels(reqs: list[dict], labels_dir: Path) -> tuple[dict[str, list[str]], list[str]]:
    """Rule labels per request: v1 from the requests, v2, v3, ... joined by (pair_id, unit_key) from
    memory_pairs_rule_v<K>.csv; '' when missing or not one of LABELS."""
    out = {"rule_v1": [r["rule_label"] if r["rule_label"] in LABELS else "" for r in reqs]}
    notes = []
    for v, path in rule_version_files(labels_dir).items():
        with open(path, encoding="utf-8-sig", newline="") as f:
            m = {(str(x.get("pair_id") or "").strip(), (x.get("unit_key") or "").strip()):
                 (x.get(f"rule_label_{v}") or "").strip().lower() for x in csv.DictReader(f)}
        labs = [m.get((str(r["pair_id"]).strip(), r["unit_key"].strip()), "") for r in reqs]
        out[f"rule_{v}"] = [x if x in LABELS else "" for x in labs]
        notes.append(f"rule_{v}: {sum(1 for x in out[f'rule_{v}'] if x)} of {len(reqs)} units joined from {path.name}")
    return out, notes


def pair_boot_weights(groups: list[str], reps: int, seed: int):
    """(reps + 1) x n multiplicities: row 0 all ones, then bootstrap replicates that resample the
    pairs (units of one pair move together)."""
    import numpy as np

    n = len(groups)
    if n == 0:
        return np.ones((reps + 1, 0))
    _, inv = np.unique(np.array([str(g) for g in groups]), return_inverse=True)
    k = int(inv.max()) + 1
    rng = np.random.default_rng(seed)
    counts = np.zeros((reps, k))
    draws = rng.integers(0, k, size=(reps, k))
    np.add.at(counts, (np.repeat(np.arange(reps), k), draws.ravel()), 1.0)
    return np.vstack([np.ones((1, n)), counts[:, inv]])


def boot_agreement(a: list[str], b: list[str], W):
    """Share of equal labels and Cohen's kappa for every row of the weight matrix W (units with a
    label outside LABELS on either side are skipped, as in `cohen_kappa`). Returns (agreement per
    row, kappa per row, units with both labels)."""
    import numpy as np

    code = {k: i for i, k in enumerate(LABELS)}
    A = np.array([code.get(x, -1) for x in a])
    B = np.array([code.get(x, -1) for x in b])
    ok = ((A >= 0) & (B >= 0)).astype(float)
    Wm = np.atleast_2d(np.asarray(W, dtype=float)) * ok
    tot = Wm.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        po = (Wm * (A == B)).sum(axis=1) / tot
        pa = np.stack([(Wm * (A == k)).sum(axis=1) for k in range(len(LABELS))], axis=1) / tot[:, None]
        pb = np.stack([(Wm * (B == k)).sum(axis=1) for k in range(len(LABELS))], axis=1) / tot[:, None]
        pe = (pa * pb).sum(axis=1)
        kappa = np.where(pe < 1, (po - pe) / (1 - pe), np.nan)
    return po, kappa, int(ok.sum())


def agreement_matrix(labels: dict[str, list[str]], methods: list[str], W) -> list[dict]:
    """Agreement and Cohen's kappa (95% pair-bootstrap interval) of every two methods."""
    import numpy as np

    out = []
    for i, m1 in enumerate(methods):
        for m2 in methods[i + 1:]:
            po, kap, n = boot_agreement(labels[m1], labels[m2], W)
            ks = kap[1:][~np.isnan(kap[1:])]
            lo, hi = (float(x) for x in np.percentile(ks, [2.5, 97.5])) if ks.size else (float("nan"),) * 2
            out.append({"a": m1, "b": m2, "n": n, "agreed": round(float(po[0]) * n) if n else 0,
                        "agree": float(po[0]), "kappa": float(kap[0]), "lo": lo, "hi": hi})
    return out


def evidence_group(r: dict) -> str:
    """What the excerpt headers told the models about a unit (counts only): whether its value occurs
    in PREV and NEXT (B1 match or literal match), and, when it is only in PREV, whether NEXT holds
    another value in its context."""
    f = r.get("found") or {}
    in_p = int(f.get("prev", 0)) + int(f.get("lit_prev", 0)) > 0
    in_n = int(f.get("next", 0)) + int(f.get("lit_next", 0)) > 0
    if in_p and in_n:
        return EVIDENCE_GROUPS[0]
    if in_p:
        return EVIDENCE_GROUPS[1] if int(f.get("ctx_next", 0)) > 0 else EVIDENCE_GROUPS[2]
    if in_n:
        e = r.get("earlier_excerpt") or ""
        return EVIDENCE_GROUPS[3] if e and not e.startswith("(no earlier") else EVIDENCE_GROUPS[4]
    return EVIDENCE_GROUPS[5]


def credential_like(r: dict) -> bool:
    """A unit whose value was masked as a credential, or hashed for a reason other than its type (a
    credential line or heading, or a long digit run). The third judge skips these."""
    from avsd.lineage.anchors import HASHED_TYPES

    t, v, _ = parse_unit_key(r["unit_key"])
    return MASK in (r.get("value") or "") or (v.startswith("h:") and t not in HASHED_TYPES)


def adjudication_frame(reqs: list[dict], labels: dict[str, list[str]], seed: int,
                       per_stratum: int = ADJ_PER_STRATUM) -> tuple[list[dict], dict]:
    """Stratified random sample of disagreement units for a third judge.

    D1: the two strong models disagree (or one has no valid answer). D2: they agree and Qwen3-14B
    says otherwise. Credential-like units (`credential_like`) are left out of the frame. In each
    stratum the per_stratum units with the smallest permanent random numbers (`_prn`, a salt apart
    from the review sample) are drawn. Returns the sample (row, pair_id, unit_key, stratum) and the
    frame sizes."""
    a, b, c = labels[QWEN35_122B.key], labels[GPT_OSS_120B.key], labels[QWEN3_14B.key]
    frame: dict[str, list[int]] = defaultdict(list)
    skipped: Counter = Counter()
    for i, r in enumerate(reqs):
        if a[i] and a[i] == b[i]:
            if a[i] == c[i]:
                continue
            st = ADJ_STRATA[1]
        else:
            st = ADJ_STRATA[0]
        if credential_like(r):
            skipped[st] += 1
            continue
        frame[st].append(i)
    sample = []
    for st in ADJ_STRATA:
        idx = sorted(frame[st], key=lambda i: (_prn(seed, f"adj:{reqs[i]['pair_id']}", reqs[i]["unit_key"]), i))
        sample += [{"row": i, "pair_id": str(reqs[i]["pair_id"]).strip(), "unit_key": reqs[i]["unit_key"],
                    "stratum": st} for i in idx[:per_stratum]]
    info = {"N": {st: len(frame[st]) for st in ADJ_STRATA}, "skipped": {st: skipped[st] for st in ADJ_STRATA},
            "per_stratum": per_stratum}
    return sample, info


def read_adjudication(path: Path) -> dict[tuple[str, str], dict]:
    if not Path(path).exists():
        return {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {(str(r.get("pair_id") or "").strip(), (r.get("unit_key") or "").strip()): r for r in csv.DictReader(f)}


def adjudication_accuracy(sample: list[dict], info: dict, judged: dict, labels: dict[str, list[str]],
                          methods: list[str]) -> dict:
    """Accuracy of each method against the third judge on the disagreement units.

    Per stratum: the sampled units the judge labelled (the judge may leave a unit undecided).
    Overall: stratum accuracies weighted by the frame sizes N_h, with a normal 95% interval from
    the stratified variance (finite-population correction); None unless every non-empty stratum
    has judged units."""
    by: dict[str, list[tuple[int, str]]] = defaultdict(list)
    undecided: Counter = Counter()
    conf: Counter = Counter()
    for s in sample:
        j = judged.get((s["pair_id"], s["unit_key"])) or {}
        lab = (j.get("judge_label") or "").strip().lower()
        if lab in LABELS:
            by[s["stratum"]].append((s["row"], lab))
            conf[(j.get("judge_confidence") or "").strip().lower() or "(none)"] += 1
        elif (j.get("judge_confidence") or "").strip():  # judged, but no label decided
            undecided[s["stratum"]] += 1
    N = info["N"]
    total = sum(N.values())
    complete = total > 0 and all(by.get(h) for h in ADJ_STRATA if N.get(h, 0) > 0)
    res: dict = {"judged": {h: len(by.get(h, [])) for h in ADJ_STRATA}, "undecided": dict(undecided),
                 "confidence": dict(conf), "methods": {}}
    for m in methods:
        r: dict = {}
        est, var = 0.0, 0.0
        for h in ADJ_STRATA:
            items = by.get(h, [])
            if not items:
                r[h] = None
                continue
            k = sum(1 for i, lab in items if labels[m][i] == lab)
            n = len(items)
            p = k / n
            r[h] = (k, n, p)
            wh = N[h] / total
            est += wh * p
            fpc = max(0.0, 1 - n / N[h]) if N[h] else 0.0
            var += wh * wh * p * (1 - p) / max(n - 1, 1) * fpc
        r["overall"] = (est, max(0.0, est - 1.96 * math.sqrt(var)), min(1.0, est + 1.96 * math.sqrt(var))) \
            if complete else None
        res["methods"][m] = r
    return res


# --- Gemini rater: redaction and prompt (owner's request 2026-10-01) ------------------------------
#
# Prompt history (continued from PROCEDURE above): b1-gemini-v1 (2026-10-01) is for Gemini as an extra
# rater of the rows the owner labels blind. It drops the rule-based occurrence counts and the ⟦ ⟧ ⟨ ⟩
# marks (the model finds the value itself), gives the fact and the owner's label guide with its two
# warnings (format or wording variants are the same fact; an unrelated earlier use of the value means
# new, not restored), and is sent only after personal data is replaced (`Redactor`).

GEMINI_PROMPT_VERSION = "b1-gemini-v1"
_MARKS_RE = re.compile("[⟦⟧⟨⟩]")
_EDGE_CHARS = frozenset(" \t\n↵-–—*•§#>:;,.()[]\"'`")
# PERSON entities that cannot be a human name (digits, paths, addresses, file names) are kept.
_NOT_NAME_RE = re.compile(r"\d|[/@_\\]|https?|www\.|\.[a-z]{1,5}\b")
_MORE_RE = re.compile(r"\s*\(\+\d+ more match(?:es)?\)")
_AGENT_WORDS = frozenset({
    "claude", "gpt", "chatgpt", "gemini", "grok", "opus", "sonnet", "haiku", "deepseek", "kimi", "glm", "qwen",
    "llama", "mistral", "o1", "o3", "o4", "mini", "pro", "flash", "fable", "code", "openai", "anthropic",
})
GEMINI_LABEL_GUIDE = (
    "- kept: PREV and NEXT both contain this fact; the wording or format may differ.\n"
    "- modified: PREV contains it; NEXT still has the same fact but with another value (for example a donor "
    "count that changed from 56 to 60).\n"
    "- dropped: PREV contains it; NEXT has neither this value nor a new value for the same fact.\n"
    "- new: PREV does not contain it, NEXT does, and no earlier version shown here contains it.\n"
    "- restored: PREV does not contain it, NEXT does, and the EARLIER version shows the same fact."
)
GEMINI_WARNINGS = (
    "1. A different format or wording of the same value is the same fact and counts as present (for example a "
    "date written with other separators, \"Donors: 56\" for \"56 donors\", or a time given inside a range). Read "
    "the text; do not rely on exact string matches.\n"
    "2. The EARLIER version only shows that an older version used the same value near the same word. Label "
    "restored only if it is the same fact; the same number or word used for something unrelated means new."
)
GEMINI_TEXT_NOTE = (
    "Each version is shown as up to three passages taken around places that mention the value or its context; "
    "\"(no passage)\" means none was found. … marks cut text, ↵ a line break and «masked» a hidden credential. "
    "[PERSON_1], [EMAIL_1] and [PHONE_1] stand for redacted personal data; the same placeholder means the same "
    "person, address or number."
)


def strip_marks(text: str) -> str:
    """An excerpt without the ⟦ ⟧ ⟨ ⟩ marks and the '(+N more matches)' count."""
    return _MORE_RE.sub("", _MARKS_RE.sub("", text or "")).strip()


def uncell(v: str | None) -> str:
    """A sheet cell without `_cell`'s formula guard (a space before a leading = + - @)."""
    v = v or ""
    return v[1:] if v[:1] == " " and v[1:2] in ("=", "+", "-", "@") else v


class Redactor:
    """Per-unit placeholders for human names, emails and phone numbers (the owner's condition for sending
    text to an external API).

    Names are spaCy PERSON entities that are not AI agents of the roster (a full agent name, or words that
    all belong to agent names or model families, such as "Opus 4.6"), trimmed of bullets and quotes and
    skipped when they hold a digit, a path or a file name (not a human name); the false positives that
    remain (product names and the like) are replaced too. Emails and phones use the B1 anchor patterns
    (`avsd.lineage.anchors`; phones with at least 10 digits). Within one unit the same surface
    always gets the same placeholder, [PERSON_1], [EMAIL_1], [PHONE_1], ... in order of first appearance,
    and every other literal occurrence of a replaced name is replaced too. ⟦ ⟧ ⟨ ⟩ marks stay in place.
    """

    def __init__(self, agent_names, nlp=None):
        self.nlp = nlp
        names = [n for n in (agent_names or []) if n]
        self.agent_full = {self._norm(n) for n in names}
        self.agent_words = set(_AGENT_WORDS)
        for n in names:
            self.agent_words.update(t for t in re.split(r"[\s\-_/]+", n.lower()) if t)

    @staticmethod
    def _norm(text: str) -> str:
        t = " ".join((text or "").split()).strip(".,;:!?'\"()[]*`")
        return re.sub(r"['’]s$", "", t).lower()

    def is_agent(self, text: str) -> bool:
        t = self._norm(text)
        if t in self.agent_full:
            return True
        words = [w for w in re.split(r"[\s\-_/]+", t) if w]
        return bool(words) and all(w in self.agent_words or re.fullmatch(r"v?\d+(?:\.\d+)*[a-z]?", w)
                                   for w in words)

    def spans(self, text: str) -> list[tuple[int, int, str]]:
        """(start, end, kind) of emails, phone numbers and non-agent PERSON entities, without overlaps."""
        from avsd.lineage.anchors import _EMAIL, _PHONE

        found = [(m.start(), m.end(), "EMAIL") for m in _EMAIL.finditer(text)]
        for m in _PHONE.finditer(text):
            if len(re.sub(r"\D", "", m.group(0))) >= 10:
                found.append((m.start(), m.end(), "PHONE"))
        if self.nlp is not None and re.search("[A-Za-z]", text):
            for ent in self.nlp(_MARKS_RE.sub(" ", text)).ents:  # same length, so offsets hold
                if ent.label_ != "PERSON":
                    continue
                a, b = ent.start_char, ent.end_char  # trim bullets, line marks and quotes at the edges
                while a < b and text[a] in _EDGE_CHARS:
                    a += 1
                while b > a and text[b - 1] in _EDGE_CHARS:
                    b -= 1
                name = text[a:b]
                if a < b and re.search("[A-Za-zÀ-ÿ]", name) and not _NOT_NAME_RE.search(name) \
                        and not self.is_agent(name):
                    found.append((a, b, "PERSON"))
        out: list[tuple[int, int, str]] = []
        for s_, e_, k in sorted(found, key=lambda x: (x[0], -(x[1] - x[0]))):
            if not any(s_ < b and a < e_ for a, b, _ in out):
                out.append((s_, e_, k))
        return out

    def redact(self, fields: dict[str, str], value_field: str | None = None,
               value_kind: str | None = None) -> tuple[dict[str, str], Counter]:
        """Redacted copies of the unit's text fields (in their order) and the number of placeholders by kind.

        value_field names the field with the unit's own value; with value_kind PERSON, EMAIL or PHONE the
        value becomes a placeholder too, and for a name each of its words of three or more letters stands
        for the same person, so presence can still be judged."""
        mapping: dict[tuple[str, str], str] = {}
        surfaces: dict[str, str] = {}  # name as written -> placeholder, for the literal pass
        counts: Counter = Counter()

        def key(kind: str, surface: str) -> tuple[str, str]:
            if kind == "PHONE":
                d = re.sub(r"\D", "", surface)
                return kind, d[1:] if len(d) == 11 and d.startswith("1") else d
            return kind, self._norm(surface)

        def ph(kind: str, surface: str) -> str:
            k = key(kind, surface)
            if k not in mapping:
                counts[kind] += 1
                mapping[k] = f"[{kind}_{counts[kind]}]"
            if kind == "PERSON":
                surfaces.setdefault(re.sub(r"['’]s$", "", surface.strip()), mapping[k])
            return mapping[k]

        out = dict(fields)
        if value_field and value_kind in ("PERSON", "EMAIL", "PHONE") and (fields.get(value_field) or "").strip():
            v = fields[value_field].strip()
            p = ph(value_kind, v)
            out[value_field] = p
            if value_kind == "PERSON":
                for w in re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’\-]{2,}", v):
                    if not self.is_agent(w):
                        mapping.setdefault(key("PERSON", w), p)
                        surfaces.setdefault(w, p)
        for f, text in fields.items():
            if f == value_field and value_kind:
                continue
            text = text or ""
            parts, last = [], 0
            for s_, e_, kind in self.spans(text):
                parts += [text[last:s_], ph(kind, text[s_:e_])]
                last = e_
            out[f] = "".join(parts) + text[last:]
        lit = sorted((x for x in surfaces if len(x) >= 3), key=len, reverse=True)
        if lit:  # other occurrences of the replaced names as written (case-sensitive), in every field
            rx = re.compile(r"(?<![\w\[])(" + "|".join(re.escape(x) for x in lit) + r")(?![\w\]])")
            out = {f: rx.sub(lambda m: surfaces[m.group(1)], t) for f, t in out.items()}
        return out, counts


def gemini_b1_messages(row: dict, redactor: Redactor) -> tuple[list[dict], Counter]:
    """Chat messages for one B1 blind-sheet row (b1-gemini-v1): the fact, the owner's label guide with
    its two warnings and the excerpts without marks or counts, personal data replaced."""
    t = (row.get("unit_type") or "").strip()
    earlier = (row.get("earlier_excerpt") or "").strip()
    e_note, e_text = "", ""
    if earlier and not earlier.startswith("(no earlier"):
        m = re.match(r"\(([^)]*)\)\s*(.*)", earlier, re.DOTALL)
        e_note, e_text = (m.group(1), m.group(2)) if m else ("", earlier)

    def cell(c: str) -> str:
        v = uncell(row.get(c))
        return "(no passage)" if not v.strip() or v.startswith("(neither") else strip_marks(v)

    fields = {"value": uncell(row.get("value")).strip(), "context": (row.get("context_key") or "").strip(),
              "earlier": strip_marks(e_text), "prev": cell("prev_excerpt"), "next": cell("next_excerpt")}
    kind = {"person": "PERSON", "email": "EMAIL", "phone": "PHONE"}.get(t)
    red, counts = redactor.redact(fields, "value", kind)
    if red["context"]:
        ctx = (f"- context: {red['context']} (part of the fact: numbers, money, percentages and times are judged "
               "together with their context, so \"56 donors\" and \"56 days\" are different facts)"
               if t in QUANTITY else
               f"- context: {red['context']} (for reference only; this type is judged by its value alone)")
    else:
        ctx = "- context: none"
    parts = [
        ("An AI agent keeps memory notes and regularly rewrites them. PREV is the memory just before one rewrite "
         "(its input) and NEXT is the rewritten memory (its output). Decide what happened to the fact below from "
         "PREV to NEXT."),
        f"Fact:\n- type: {t} ({TYPE_GLOSS.get(t, t)})\n- value: {red['value'] or '(not recovered)'}\n{ctx}",
        "Labels:\n" + GEMINI_LABEL_GUIDE,
        "Two warnings:\n" + GEMINI_WARNINGS,
        ("If the fact itself looks mis-extracted (for example an ID read as a number), still label whether this "
         "value is in PREV and in NEXT. If the passages do not settle it, give the most likely label with low "
         "confidence."),
        "Text: " + GEMINI_TEXT_NOTE,
    ]
    if red["earlier"]:
        parts.append(f"EARLIER (an older version before PREV; {e_note}):\n{red['earlier']}" if e_note
                     else f"EARLIER (an older version before PREV):\n{red['earlier']}")
    parts += [f"PREV (the input):\n{red['prev']}", f"NEXT (the output):\n{red['next']}",
              ('Reply with JSON: {"label": "kept" | "modified" | "dropped" | "new" | "restored", '
               '"confidence": "low" | "medium" | "high", "rationale": "<at most 25 words>"}')]
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "\n\n".join(parts)}], counts


# --- stage 3: report --------------------------------------------------------------------------------

def report(cfg: dict, log=print) -> dict:
    """Stage 3: review sheet (re-check design), its README, the LLM label file and the QA report.

    Needs cached answers of Qwen3-14B and of both re-check models for every request. The current
    sheet is copied to BACKUP_FILE first if it is in the Qwen3-14B format and no backup exists; any
    human_label or notes already filled are carried over by (pair_id, unit_key)."""
    import shutil

    paths = cfg["paths"]
    out = cache_dir(cfg)
    reqs = _read_jsonl(out / "requests.jsonl")
    if not reqs:
        raise SystemExit(f"no requests in {out}; run the prepare stage first")
    stats = json.loads((out / "prepare_stats.json").read_text()) if (out / "prepare_stats.json").exists() else {}
    seed = int(cfg["seed"])
    labels_dir = Path(paths["labels"])
    answers = model_answers(reqs, out, seed)
    missing = [k for k in LLM_KEYS if k not in answers or any(p is None for p in answers[k])]
    if missing:
        raise SystemExit(f"report: no cached answers of {', '.join(missing)} for every request; "
                         "run the infer stage first")
    labels = model_label_lists(answers)
    rules, rule_notes = rule_labels(reqs, labels_dir)
    labels.update(rules)
    rule_cols = tuple(rules)

    rows = []
    for i, r in enumerate(reqs):
        row = {"pair_id": r["pair_id"], "agent": r["agent"], "unit_type": r["unit_type"], "value": r["value"],
               "context_key": r["context_key"], "prev_excerpt": r["prev_excerpt"],
               "next_excerpt": r["next_excerpt"], "earlier_excerpt": r["earlier_excerpt"], "human_label": "",
               "notes": "", "unit_key": r["unit_key"], "_row": r["row"]}
        for k in STRONG:
            p, pre = answers[k][i], SHEET_PREFIX[k]
            ok = p.get("attempt") is not None
            row[f"{pre}_label"] = p["label"] if ok else ""
            row[f"{pre}_confidence"] = p["confidence"] if ok else ""
            row[f"{pre}_rationale"] = (mask_text(p["rationale"]) if p["rationale"] else "") if ok \
                else "(no valid model output)"
        for v in rule_cols:
            row[v] = labels[v][i]
        rows.append(row)
    design, dinfo = review_design(rows, seed, target=REVIEW_TARGET, min_sample=MIN_SAMPLE, rule_cols=rule_cols)
    for row, d in zip(rows, design):
        row.update(review_priority=d["priority"], design_stratum=d["stratum"], suggested_label=d["suggested"],
                   inclusion_prob=f"{d['inclusion_prob']:.6f}")
    order = sorted(range(len(rows)), key=lambda i: (PRIORITIES.index(rows[i]["review_priority"]),
                                                     int(rows[i]["pair_id"]), rows[i]["_row"]))
    review_path = labels_dir / REVIEW_FILE
    if review_path.exists():
        with open(review_path, encoding="utf-8-sig", newline="") as f:
            rd = csv.DictReader(f)
            old = list(rd)
            old_cols = list(rd.fieldnames or [])
        if "inclusion_prob" not in old_cols and not (labels_dir / BACKUP_FILE).exists():
            shutil.copyfile(review_path, labels_dir / BACKUP_FILE)
            os.chmod(labels_dir / BACKUP_FILE, 0o600)
            log(f"report: copied the Qwen3-14B sheet to {labels_dir / BACKUP_FILE}")
        filled = [x for x in old if (x.get("human_label") or "").strip() or (x.get("notes") or "").strip()]
        if filled:
            keep = {((x.get("pair_id") or "").strip(), (x.get("unit_key") or "").strip()): x for x in filled}
            kept = 0
            for r in rows:  # never overwrite the owner's labels
                k = keep.get((str(r["pair_id"]).strip(), r["unit_key"].strip()))
                if k:
                    r["human_label"], r["notes"] = k.get("human_label") or "", k.get("notes") or ""
                    kept += 1
            log(f"report: kept human_label/notes of {kept} of {len(filled)} filled rows of the previous sheet")
            if kept < len(filled):
                log(f"report: WARNING {len(filled) - kept} filled rows had no matching unit; the previous "
                    "sheet is kept as a .bak copy")
                with _private_open(review_path.with_name(review_path.name + ".bak"), "w", encoding="utf-8-sig",
                                   newline="") as f:
                    wr = csv.DictWriter(f, fieldnames=old_cols)
                    wr.writeheader()
                    wr.writerows(old)
    with _private_open(review_path, "w", encoding="utf-8-sig", newline="") as f:
        wr = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        wr.writerow(SHEET_COLUMNS)
        for i in order:
            wr.writerow([_cell(rows[i][c]) for c in SHEET_COLUMNS])
    with _private_open(labels_dir / LLM_LABELS_FILE, "w", encoding="utf-8", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["pair_id", "unit_key", *LLM_KEYS])
        for i, r in enumerate(reqs):
            wr.writerow([r["pair_id"], r["unit_key"], *(labels[k][i] for k in LLM_KEYS)])
    c = dinfo["counts"]
    with _private_open(labels_dir / README_FILE, "w", encoding="utf-8") as f:
        f.write(README_TEXT.format(
            n_rows=len(rows), n1=c[PRIORITIES[0]], nA=dinfo["A"], nB=dinfo["B"], nC=sum(dinfo["C_by_label"].values()),
            n2=c[PRIORITIES[1]], n3=c[PRIORITIES[2]], n12=c[PRIORITIES[0]] + c[PRIORITIES[1]], seed=seed))

    # --- QA (aggregates only) ---
    parsed = answers[QWEN3_14B.key]
    rule = labels["rule_v1"]
    llm = [p["label"] for p in parsed]
    valid = [p["valid"] for p in parsed]
    n = len(rows)
    agree = sum(a == b for a, b in zip(rule, llm))
    disagree = n - agree
    groups = [str(r["pair_id"]) for r in reqs]
    W = pair_boot_weights(groups, BOOT_REPS, seed)
    _, kap, _ = boot_agreement(rule, llm, W)
    import numpy as np

    kappa = float(kap[0])
    lo, hi = (float(x) for x in np.percentile(kap[1:][~np.isnan(kap[1:])], [2.5, 97.5]))
    conf = Counter(p["confidence"] or "(none)" for p in parsed)
    conf_agree = Counter((p["confidence"] or "(none)", a == b) for p, a, b in zip(parsed, rule, llm))
    errors = Counter(p["error"] for p in parsed if p["error"])
    trunc = sum(p["truncated"] for p in parsed)
    finish = Counter(p["finish_reason"] for p in parsed if p["finish_reason"])
    cols = list(LABELS) + (["(invalid)"] if any(not v for v in valid) else [])
    cm = Counter((a, b if b else "(invalid)") for a, b in zip(rule, llm))
    by_type = Counter((r["unit_type"], a == b) for r, a, b in zip(reqs, rule, llm))
    scan = _scanner_hits([rows[i][c] for i in range(n) for c in SHEET_COLUMNS if c != "unit_key"])
    evidence = evidence_table(reqs, llm)
    runs = _read_jsonl(out / runs_file(QWEN3_14B))
    # Runs that generated outputs for the current prompts (earlier prompt versions stay cached).
    gen_runs = [x for x in runs if x.get("generated") and x.get("prompt_version") == PROMPT_VERSION]
    last = gen_runs[-1] if gen_runs else (runs[-1] if runs else {})
    qa = render_qa(stats, rows, rule, llm, n, agree, disagree, kappa, (lo, hi), conf, conf_agree, errors,
                   trunc, finish, cols, cm, by_type, scan, gen_runs, last, sum(valid), evidence)
    adj_sample, adj_info = adjudication_frame(reqs, labels, seed)
    judged = read_adjudication(labels_dir / ADJUDICATION_FILE)
    owner = sum(1 for r in rows if (r.get("human_label") or "").strip().lower() in LABELS)
    if owner:  # once the owner has labelled, Gemini and Claude enter the third-judge table too
        for name, path, col, by in (("gemini", GEMINI_LABELS_FILE, "gemini_label", "pair"),
                                    ("claude", CLAUDE_LABELS_FILE, "claude_label", "unit")):
            if (labels_dir / path).exists():
                with open(labels_dir / path, encoding="utf-8-sig", newline="") as f:
                    got = {((x.get("pair_id") or "").strip() if by == "pair" else "",
                            (x.get("unit_key") or "").strip()): (x.get(col) or "").strip().lower()
                           for x in csv.DictReader(f)}
                labels[name] = [got.get((str(r["pair_id"]).strip() if by == "pair" else "", r["unit_key"].strip()),
                                        "") for r in reqs]
    qa += "\n".join(render_recheck(reqs, answers, labels, rule_notes, W, out, adj_sample, adj_info, judged,
                                   dinfo, seed, labelled=bool(owner)))
    if owner:
        mrows = compute_label_metrics(cfg)
        qa += "\n".join(render_validation(cfg, mrows, claude_owner_agreement(cfg)))
        gc = cache_dir(cfg).parent / "gemini_hard" / "compare.md"
        if gc.exists():  # Gemini's aggregates, private until the owner had labelled
            body = [x.replace(f"outputs/qa/{QA_FILE} section 10", "section 10")
                    for x in gc.read_text(encoding="utf-8").splitlines()
                    if not x.startswith("# ") and not x.startswith("Data: ")]
            while body and not body[0].strip():
                body.pop(0)
            qa += "\n".join(["", "", "## 15. Gemini as an extra rater (before the owner's labels)", "", *body])
        qa += "\n"
    qa_path = Path(paths["outputs"]) / "qa" / QA_FILE
    qa_path.parent.mkdir(parents=True, exist_ok=True)
    qa_path.write_text(qa, encoding="utf-8")
    log(f"report: {n} rows; review priorities " + ", ".join(f"{k} {v}" for k, v in c.items())
        + f" (A {dinfo['A']}, B {dinfo['B']}); sheet {review_path}; QA {qa_path}")
    return {"rows": n, "agree": agree, "disagree": disagree, "kappa": kappa, "kappa_ci": (lo, hi),
            "valid": sum(valid), "scanner_hits": dict(scan) if scan is not None else None, "design": dinfo,
            "adjudication": adj_info}


def claude_owner_agreement(cfg: dict, reps: int = BOOT_REPS) -> dict | None:
    """Claude's blind labels against the owner's on the labelled audit rows (aggregates only).

    Agreement weighted to all units (1 / (review inclusion probability x p_audit)), weighted to the blind
    sheet (1 / p_audit), unweighted and per audit stratum; agreement on kept / lost / entry (lost = dropped
    or modified, entry = new or restored); the confusion matrix (owner rows, Claude columns); and Claude's
    bad_unit share over every row it labelled. None without audit or Claude labels."""
    import numpy as np

    labels_dir = Path(cfg["paths"]["labels"])
    audit = read_audit(labels_dir)
    if not audit or not (labels_dir / CLAUDE_LABELS_FILE).exists():
        return None
    with open(labels_dir / CLAUDE_LABELS_FILE, encoding="utf-8-sig", newline="") as f:
        cl = {(r.get("unit_key") or "").strip(): r for r in csv.DictReader(f)}
    with open(labels_dir / REVIEW_FILE, encoding="utf-8-sig", newline="") as f:
        sheet = [r for r in csv.DictReader(f) if (r.get("review_priority") or "").strip()[:1] in ("1", "2")]
    rows = []
    for r in sheet:
        k = (r.get("unit_key") or "").strip()
        h = (r.get("human_label") or "").strip().lower()
        if k in audit and h in LABELS and k in cl:
            pa, pr = float(audit[k]["p_audit"]), _float(r.get("inclusion_prob")) or 1.0
            rows.append({"stratum": str(audit[k]["stratum"]), "owner": h, "claude": cl[k]["claude_label"],
                         "w_all": 1.0 / (pr * pa), "w_blind": 1.0 / pa})
    if not rows:
        return None

    def coarse(x: str) -> str:
        return "lost" if x in LOSS_LABELS else "entry" if x in ("new", "restored") else x

    strata = [x["stratum"] for x in rows]
    same = np.array([x["owner"] == x["claude"] for x in rows], dtype=float)
    same3 = np.array([coarse(x["owner"]) == coarse(x["claude"]) for x in rows], dtype=float)
    out: dict = {"n": len(rows), "unweighted": float(same.mean())}
    for w in ("w_all", "w_blind"):
        W = audit_weights(strata, [x[w] for x in rows], reps, int(cfg.get("seed", 20261003)))
        for name, v in ((w, same), (w + "_coarse", same3)):
            est = (W @ v) / W.sum(axis=1)
            out[name] = (float(est[0]), *(float(x) for x in np.percentile(est[1:], [2.5, 97.5])))
    out["by_stratum"] = {s: (int(sum(same[i] for i in range(len(rows)) if strata[i] == s)),
                             sum(1 for i in range(len(rows)) if strata[i] == s)) for s in sorted(set(strata))}
    out["confusion"] = Counter((x["owner"], x["claude"]) for x in rows)
    out["confusion_w"] = Counter()
    for x in rows:
        out["confusion_w"][(x["owner"], x["claude"])] += x["w_all"]
    out["owner_labels"] = Counter(x["owner"] for x in rows)
    out["claude_labels_audit"] = Counter(x["claude"] for x in rows)
    out["claude_labels_all"] = Counter(r["claude_label"] for r in cl.values())
    out["bad_unit"] = (sum(1 for r in cl.values() if (r.get("bad_unit") or "").strip() == "1"), len(cl))
    return out


def _rated(rows: list[dict], scheme: str, label: str, metric: str, m: str) -> str:
    r = next((x for x in rows if x["scheme"] == scheme and x["label"] == label and x["metric"] == metric), None)
    if r is None or r.get(m) in ("", None):
        return "-"
    v, lo, hi = r[m], r.get(f"{m}_lo"), r.get(f"{m}_hi")
    return f"{v:.2f}" + (f" [{lo:.2f}, {hi:.2f}]" if lo not in ("", None) else "")


def recommend_rule_set(rows: list[dict], scheme: str = "weighted") -> dict:
    """The rule version with the highest loss-detection F1 in a scheme, every version's F1 with its
    interval, the paired differences, and whether the intervals overlap."""
    r = next((x for x in rows if x["scheme"] == scheme and x["label"] == "loss" and x["metric"] == "f1"), None)
    if r is None:
        return {}
    vers = {"v1": "rule", **{k[5:]: k for k in r if re.fullmatch(r"rule_v\d+", k)}}
    f1 = {v: (r[m], r.get(f"{m}_lo"), r.get(f"{m}_hi")) for v, m in vers.items() if r.get(m) not in ("", None)}
    if not f1:
        return {}
    best = max(f1, key=lambda v: f1[v][0])
    overlap = {v: not (f1[v][2] < f1[best][1] or f1[best][2] < f1[v][1]) for v in f1 if v != best
               and f1[v][1] not in ("", None)}
    pr = {}
    for mt in ("precision", "recall"):
        x = next((x for x in rows if x["scheme"] == scheme and x["label"] == "loss" and x["metric"] == mt), {})
        pr[mt] = {v: x[vers[v]] for v in f1 if x.get(vers[v]) not in ("", None)}
    return {"best": best, "f1": f1, "overlap": overlap, "pairs": r.get("pairs", {}), **pr}


def render_validation(cfg: dict, rows: list[dict], agree: dict | None) -> list[str]:
    """QA sections on the owner's audit labels (aggregates only): metrics, sensitivity checks, Claude
    against the owner, and the rule-set recommendation."""
    names = {"rule": "rules v1", "rule_v2": "rules v2", "rule_v3": "rules v3", "llm": "Qwen3-14B",
             "qwen35_122b": "Qwen3.5-122B", "gptoss_120b": "gpt-oss-120b", "gemini": "Gemini 3.1 Pro",
             "claude": "Claude (blind)"}
    present = [m for m in names if any(r.get(m) not in ("", None) for r in rows if r["scheme"] == "weighted")]
    w0 = next((r for r in rows if r["scheme"] == "weighted"), {})
    L = ["", "## 12. Validation against the owner's labels", "",
         ("Owner's design of 2026-10-03: a stratified random audit of the blind sheet (seed 20261003), 15 of the 29 "
          "rows of stratum A, 30 of the 218 rows of B and 15 of the 30 sampled rows of C, all labelled by the owner "
          "without seeing any model or rule label; 11 more rows the owner labelled (the first rows of the sheet, "
          "not random) enter only the sensitivity check (a). Each audit row is weighted by 1 / (review inclusion "
          "probability x audit inclusion probability), so the estimates stand for all 500 units; intervals come "
          "from 2,000 bootstrap replicates that resample rows within the audit strata. 'Loss' is loss detection, "
          "the event of the B1 hazards: dropped or modified (positive) against kept (negative), on rows the owner "
          "labelled kept, dropped or modified; 'loss, all rows' also counts rows labelled new or restored as "
          "negatives. The owner flagged no unit as mis-extracted (bad_unit)."), ""]
    if w0:
        L += [f"Scheme notes: {w0['note']}", ""]
    L += ["Main estimates (audit rows, design-weighted, 95% CI):", "",
          "| rater | loss precision | loss recall | loss F1 | loss F1, all rows | macro F1 | accuracy |",
          "|---|---|---|---|---|---|---|"]
    for m in present:
        L.append(f"| {names[m]} | " + " | ".join(_rated(rows, "weighted", lb, mt, m) for lb, mt in (
            ("loss", "precision"), ("loss", "recall"), ("loss", "f1"), ("loss_all", "f1"), ("macro", "f1"),
            ("all", "accuracy"))) + " |")
    L += ["", ("F1 per class (audit rows, design-weighted, 95% CI; the owner gave no audit row new or restored, so "
               "those classes can only collect false positives):"), "",
          "| rater | " + " | ".join(LABELS) + " |", "|---|" + "---|" * len(LABELS)]
    for m in present:
        L.append(f"| {names[m]} | " + " | ".join(_rated(rows, "weighted", lb, "f1", m) for lb in LABELS) + " |")
    rec = recommend_rule_set(rows, "weighted")
    if rec:
        L += ["", "Paired differences in loss-detection F1 between the rule sets (same bootstrap replicates):", "",
              "| difference | estimate | 95% CI |", "|---|---|---|"]
        for k, (d, lo, hi) in rec["pairs"].items():
            L.append(f"| {k.replace('_minus_', ' - ')} | {d:+.3f} | "
                     + (f"{lo:+.3f} to {hi:+.3f}" if lo != "" else "-") + " |")
    L += ["", ("Sensitivity checks (loss-detection F1 and accuracy, 95% CI): (a) all rows the owner labelled, the 11 "
               "extra rows treated as random; (b) Claude's blind labels as the truth on all 277 rows of the blind "
               "sheet, weighted by the review design; for reference, the 60 audit rows unweighted."), "",
          "| rater | (a) loss F1 | (a) accuracy | (b) loss F1 | (b) accuracy | audit unweighted loss F1 |",
          "|---|---|---|---|---|---|"]
    for m in present:
        L.append(f"| {names[m]} | " + " | ".join([
            _rated(rows, "weighted_owner71", "loss", "f1", m), _rated(rows, "weighted_owner71", "all", "accuracy", m),
            _rated(rows, "weighted_claude277", "loss", "f1", m),
            _rated(rows, "weighted_claude277", "all", "accuracy", m),
            _rated(rows, "unweighted", "loss", "f1", m)]) + " |")
    if agree:
        a, b, c3 = agree["w_all"], agree["w_blind"], agree["w_all_coarse"]
        L += ["", "## 13. Claude's blind labels against the owner's", "",
              (f"On the {agree['n']} audit rows Claude gives the owner's label on {_fmt(a[0], 3)} of all units "
               f"(weighted to the 500 units; 95% CI {_fmt(a[1], 2)} to {_fmt(a[2], 2)}), {_fmt(b[0], 3)} of the blind "
               f"sheet (weighted to its 277 rows; {_fmt(b[1], 2)} to {_fmt(b[2], 2)}) and "
               f"{_fmt(agree['unweighted'], 3)} "
               "of the audit rows unweighted. By audit stratum: "
               + ", ".join(f"{s} {k}/{nn} ({_fmt(k / nn, 2)})" for s, (k, nn) in agree["by_stratum"].items())
               + f". On kept / lost / entry the agreement is {_fmt(c3[0], 3)} (weighted to all units; {_fmt(c3[1], 2)} "
               f"to {_fmt(c3[2], 2)})."), "",
              "Confusion matrix on the audit rows (rows: owner, columns: Claude; counts, unweighted):", ""]
        labs = [x for x in LABELS if agree["owner_labels"].get(x) or agree["claude_labels_audit"].get(x)]
        L.append(_md_table(["owner \\ Claude", *labs, "total"],
                           [[o, *(agree["confusion"].get((o, c), 0) for c in labs),
                             sum(agree["confusion"].get((o, c), 0) for c in labs)] for o in labs]))
        bu, nb = agree["bad_unit"]
        L += ["", (f"Claude's label counts on all {nb} rows: " + ", ".join(
            f"{k} {agree['claude_labels_all'].get(k, 0)}" for k in LABELS) + f". Claude flagged {bu} of {nb} rows "
            f"({_fmt(bu / nb if nb else float('nan'), 3)}) as mis-extracted units (bad_unit); no human has validated "
            "that flag, and the owner flagged none in the 71 rows labelled.")]
    if rec:
        f1, best = rec["f1"], rec["best"]
        others = [v for v in f1 if v != best]
        ov = [v for v, o in rec["overlap"].items() if o]
        sig = {k: (lo != "" and (lo > 0 or hi < 0)) for k, (d, lo, hi) in rec["pairs"].items()}
        rc = recommend_rule_set(rows, "weighted_claude277")
        p, q = rec.get("precision", {}), rec.get("recall", {})
        trade = ""
        if best in p and best in q and others:
            hp = all(p[best] >= p.get(v, -1) for v in others)
            lq = any(q[best] < q.get(v, -1) for v in others)
            trade = ("Loss precision: " + "; ".join(f"{v} {p[v]:.2f}" for v in p) + "; loss recall: "
                     + "; ".join(f"{v} {q[v]:.2f}" for v in q) + "."
                     + (f" So {best} gains by flagging fewer kept units as lost, at a small cost in caught losses."
                        if hp and lq else "") + " ")
        L += ["", "## 14. Rule-set recommendation", "",
              (f"Rule set {best} has the best loss-detection F1 against the owner's audit labels: "
               + "; ".join(f"{v} {f1[v][0]:.2f} [{f1[v][1]:.2f}, {f1[v][2]:.2f}]" for v in f1) + ". "
               + (f"Its 95% interval overlaps {'that' if len(ov) == 1 else 'those'} of {' and '.join(ov)}, so the "
                  "intervals alone do not separate the rule sets. " if ov
                  else f"Its interval does not overlap those of {' and '.join(others)}. ")
               + trade
               + "Paired differences in loss F1 (same bootstrap replicates): " + "; ".join(
                   f"{k.replace('_minus_', ' - ')} {d:+.2f} "
                   + (f"(95% CI {lo:+.3f} to {hi:+.3f}, {'excludes' if sig[k] else 'includes'} 0)" if lo != ""
                      else "")
                   for k, (d, lo, hi) in rec["pairs"].items()) + ". "
               + (f"Against Claude's blind labels on all 277 rows the best rule set is {rc['best']} ("
                  + "; ".join(f"{v} {rc['f1'][v][0]:.2f}" for v in rc["f1"]) + "), "
                  + ("which agrees." if rc.get("best") == best else "which differs.") if rc else ""))]
    return L


def evidence_table(reqs: list[dict], llm: list[str]) -> list[list]:
    """Rule/LLM agreement by what the excerpts show (counts only)."""

    def f_(r: dict, k: str) -> int:
        return int((r.get("found") or {}).get(k, 0))

    groups = [
        ("rule modified/dropped; value text still in NEXT (literal match, missed by the rules)",
         lambda r: r["rule_label"] in ("modified", "dropped") and f_(r, "lit_next") > 0),
        ("rule modified/dropped; another value in the unit's context in NEXT",
         lambda r: r["rule_label"] in ("modified", "dropped") and f_(r, "lit_next") == 0
         and f_(r, "ctx_next") > 0),
        ("rule modified/dropped; neither value text nor context value in NEXT",
         lambda r: r["rule_label"] in ("modified", "dropped") and f_(r, "lit_next") == 0
         and f_(r, "ctx_next") == 0),
        ("rule new/restored; value text already in PREV (literal match, missed by the rules)",
         lambda r: r["rule_label"] in ("new", "restored") and f_(r, "lit_prev") > 0),
        ("rule new/restored; value text not in PREV",
         lambda r: r["rule_label"] in ("new", "restored") and f_(r, "lit_prev") == 0),
        ("rule kept", lambda r: r["rule_label"] == "kept"),
    ]
    out = []
    for name, f in groups:
        idx = [i for i, r in enumerate(reqs) if f(r)]
        dis = [i for i in idx if llm[i] != reqs[i]["rule_label"]]
        top = Counter(llm[i] or "(invalid)" for i in dis).most_common(2)
        out.append([name, len(idx), len(dis), ", ".join(f"{k} {v}" for k, v in top) or "-"])
    return out


def _confusion_table(a: list[str], b: list[str], name_a: str, name_b: str, idx=None) -> str:
    """Counts of (a, b) label pairs over idx (all units by default); '(none)' is no valid label."""
    idx = range(len(a)) if idx is None else idx
    cm = Counter((a[i] or "(none)", b[i] or "(none)") for i in idx)
    rows_ = [x for x in (*LABELS, "(none)") if any(k[0] == x for k in cm)]
    cols_ = [x for x in (*LABELS, "(none)") if any(k[1] == x for k in cm)]
    body = []
    for x in rows_:
        tot = sum(cm.get((x, y), 0) for y in cols_)
        same = cm.get((x, x), 0) / tot if tot else float("nan")
        body.append([x, *(cm.get((x, y), 0) for y in cols_), tot, _fmt(same, 2)])
    return _md_table([f"{name_a} \\ {name_b}", *cols_, "total", "same"], body)


def _transitions(a: list[str], b: list[str], idx, k: int = 3) -> str:
    c = Counter(f"{a[i] or '(none)'}→{b[i] or '(none)'}" for i in idx if a[i] != b[i])
    return ", ".join(f"{t} {v}" for t, v in c.most_common(k)) or "-"


def _gpu_list(gpu: str) -> str:
    """'A; A; A; A' (one entry per GPU, as `_gpu_name` writes it) as '4x A'."""
    parts = [x.strip() for x in (gpu or "").split(";") if x.strip()]
    return f"{len(parts)}x {parts[0]}" if len(parts) > 1 and len(set(parts)) == 1 else (gpu or "?")


def _gpu_precision(spec: ModelSpec, gpu: str) -> str:
    g = gpu or ""
    if spec.key == QWEN35_122B.key:
        if "L40" in g:
            return "FP8 block-quantized weights (128x128), FP8 activations (W8A8, sm_89)"
        if "A40" in g or "A6000" in g:
            return "FP8 block-quantized weights (128x128), weight-only on Ampere (bf16 activations)"
        return "FP8 block-quantized weights (128x128)"
    if spec.key == GPT_OSS_120B.key:
        return "MXFP4 MoE weights as released, bf16 activations"
    return "bf16"


def render_recheck(reqs: list[dict], answers: dict, labels: dict[str, list[str]], rule_notes: list[str], W,
                   out: Path, adj_sample: list[dict], adj_info: dict, judged: dict, dinfo: dict,
                   seed: int, labelled: bool = False) -> list[str]:
    """QA sections 5 to 12: the re-check with the two strong models (aggregates only)."""
    import numpy as np

    n = len(reqs)
    q35, oss, q14 = labels[QWEN35_122B.key], labels[GPT_OSS_120B.key], labels[QWEN3_14B.key]
    cons = [a if a and a == b else "" for a, b in zip(q35, oss)]
    C = [i for i in range(n) if cons[i]]
    over = [i for i in C if cons[i] != q14[i]]
    types = [r["unit_type"] for r in reqs]
    ev = [evidence_group(r) for r in reqs]
    rule_keys = [k for k in ("rule_v1", "rule_v2", "rule_v3") if k in labels]
    methods = [*LLM_KEYS, *rule_keys]
    L = ["", "## 5. Re-check with two stronger models", "",
         ("The owner asked on 2026-10-01 that two stronger local open-weight models re-check the Qwen3-14B "
          "pre-labels before the owner's review. Each model labels the same 500 cached requests (`requests.jsonl`, "
          f"prompt version {PROMPT_VERSION}: the same prompts and excerpts as Qwen3-14B) on its own. The prompts "
          "contain no rule label and no Qwen3-14B label, and neither model sees the other's answer. The prompt "
          "design has one link to rule v1: the EARLIER excerpt is retrieved only for units that v1 labels "
          "restored, so a model can only support \"restored\" where v1 says so. Weights came from the official "
          "Hugging Face repositories without a token and were deleted after the run."),
         ""]
    hdr = ["item", *(MODELS[k].name for k in STRONG)]
    info: dict[str, dict] = {}
    for k in STRONG:
        spec = MODELS[k]
        runs = [x for x in _read_jsonl(out / runs_file(spec))
                if x.get("generated") and x.get("prompt_version") == PROMPT_VERSION]
        last = runs[-1] if runs else {}
        ans = answers[k]
        fin = [p for p in ans if p]
        toks = np.array([p["output_tokens"] for p in fin]) if fin else np.zeros(1)
        val = Counter(p["attempt"] for p in fin if p["attempt"] is not None)
        gen = Counter()
        for x in runs:
            for a, v in (x.get("generated_by_attempt") or {}).items():
                gen[int(a)] += v
        smp = model_sampling(spec, seed)
        dec = f"temperature {smp['temperature']:g}" + "".join(
            f", {kk} {smp[kk]:g}" for kk in ("top_p", "top_k", "min_p", "presence_penalty") if kk in smp)
        dec += f", seed {seed}; at most {spec.budgets[0]:,} new tokens"
        if len(spec.budgets) > 1:
            dec += (f"; answers that do not validate are retried once with {spec.budgets[1]:,} tokens and "
                    "seed + 1")
        tk = ", ".join(f"{a}={b}" for a, b in spec.template_kwargs)
        info[k] = {
            "model": f"`{spec.model_id}` (revision `{spec.revision[:12]}`, {spec.license}, {spec.size_gb:.0f} GB)",
            "precision": _gpu_precision(spec, last.get("gpu", "")),
            "serving": (f"vLLM {last.get('vllm', '?')} (torch {last.get('torch', '?')}), offline batch, tensor "
                        f"parallel {spec.tensor_parallel}" + (", language model only" if spec.text_only else "")
                        + (", eager" if last.get("enforce_eager") else ", CUDA graphs")),
            "reasoning": (f"chat template {tk}; vLLM reasoning parser `{spec.reasoning_parser}`, JSON-schema "
                          "structured output after the reasoning; the answer is validated against the schema"),
            "decoding": dec,
            "GPU": (f"{_gpu_list(last.get('gpu', '?'))}; node {last.get('node', '?')}, Slurm job(s) "
                    + ", ".join(sorted({str(x.get('slurm_job')) for x in runs})) if runs else "?"),
            "generated": ", ".join(f"attempt {a + 1}: {v}" for a, v in sorted(gen.items())) or "0",
            "valid answers": (f"{sum(val.values())} / {n} (" + ", ".join(f"attempt {a + 1}: {v}"
                                                                          for a, v in sorted(val.items()))
                              + f"); no valid answer: {n - sum(val.values())}"),
            "finish reasons (answer used)": ", ".join(f"{a} {b}" for a, b in sorted(
                Counter(p["finish_reason"] or "?" for p in fin).items())),
            "output tokens per request (with reasoning)": (f"mean {toks.mean():,.0f}, median "
                                                           f"{np.median(toks):,.0f}, max {toks.max():,}"),
            "tokens": (f"{sum(x.get('prompt_tokens', 0) for x in runs):,} prompt, "
                       f"{sum(x.get('output_tokens', 0) for x in runs):,} output"),
            "runtime": (f"model load {sum(x.get('seconds_load', 0) for x in runs):.0f} s, generation "
                        f"{sum(x.get('seconds_generate', 0) for x in runs):.0f} s, total "
                        f"{sum(x.get('seconds', 0) for x in runs):.0f} s"),
            "cache": f"`{CACHE_SUBDIR}/{cache_file(spec)}`, runs in `{runs_file(spec)}`",
        }
    items = list(next(iter(info.values())).keys()) if info else []
    L += [_md_table(hdr, [[it, *(info[k][it] for k in STRONG)] for it in items]), ""]

    # 6. agreement
    agr = agreement_matrix(labels, methods, W)
    look = {(x["a"], x["b"]): x for x in agr}
    sq = []
    for i, m1 in enumerate(methods):
        cells = []
        for j, m2 in enumerate(methods):
            if i == j:
                cells.append("-")
            elif i < j:
                cells.append(_fmt(look[(m1, m2)]["agree"], 2))
            else:
                cells.append(_fmt(look[(m2, m1)]["kappa"], 2))
        sq.append([METHOD_NAMES.get(m1, m1), *cells])
    L += ["## 6. Agreement between labellers", "",
          ("Six labellers on the same 500 units: the three LLMs and rule sets v1, v2 and v3 "
           f"({'; '.join(rule_notes) or 'no revised rule files'}). Upper triangle: share of units with the same "
           "label; lower triangle: Cohen's kappa. Units without a valid label on either side are skipped."), "",
          _md_table(["", *(METHOD_NAMES.get(m, m) for m in methods)], sq), "",
          "Cohen's kappa with 95% intervals (2,000 bootstrap replicates over the 100 pairs):", "",
          _md_table(["pair", "units", "same label", "agreement", "kappa", "95% CI"],
                    [[f"{METHOD_NAMES.get(x['a'])} / {METHOD_NAMES.get(x['b'])}", x["n"], x["agreed"],
                      _fmt(x["agree"], 3), _fmt(x["kappa"], 3), f"{_fmt(x['lo'], 3)} to {_fmt(x['hi'], 3)}"]
                     for x in agr]), ""]

    # 7. confusion matrices
    L += ["## 7. Confusion matrices", "",
          f"Qwen3.5-122B (rows) against gpt-oss-120b (columns), all {n} units:", "",
          _confusion_table(q35, oss, "Qwen3.5", "gpt-oss"), "",
          (f"Qwen3-14B (rows) against the strong-model consensus (columns), on the {len(C)} units where the two "
           "strong models agree:"), "",
          _confusion_table(q14, cons, "Qwen3-14B", "consensus", C), ""]
    for rk in rule_keys:
        L += [f"{METHOD_NAMES[rk]} (rows) against the consensus (columns), same {len(C)} units:", "",
              _confusion_table(labels[rk], cons, METHOD_NAMES[rk], "consensus", C), ""]

    # 8. by anchor type
    trow = []
    for t in sorted(set(types), key=lambda t: (-types.count(t), t)):
        idx = [i for i in range(n) if types[i] == t]
        ci = [i for i in idx if cons[i]]
        trow.append([t, len(idx), sum(1 for i in idx if q35[i] and q35[i] == oss[i]), len(ci),
                     sum(1 for i in ci if cons[i] == q14[i]),
                     *(sum(1 for i in ci if cons[i] == labels[rk][i]) for rk in rule_keys),
                     _transitions(q14, cons, ci, 2)])
    L += ["## 8. By anchor type", "",
          ("Units per anchor type; how often the two strong models agree; on the consensus units, how often "
           "Qwen3-14B and each rule set give the consensus label; the most common Qwen3-14B → consensus changes."),
          "",
          _md_table(["type", "units", "strong models agree", "consensus units", "= Qwen3-14B",
                     *(f"= {METHOD_NAMES[rk]}" for rk in rule_keys), "Qwen3-14B → consensus"], trow), ""]

    # 9. overturns
    ind_c = np.array([1.0 if cons[i] else 0.0 for i in range(n)])
    ind_o = np.array([1.0 if (cons[i] and cons[i] != q14[i]) else 0.0 for i in range(n)])
    with np.errstate(invalid="ignore", divide="ignore"):
        rate = (W @ ind_o) / (W @ ind_c)
    r_lo, r_hi = (float(x) for x in np.percentile(rate[1:][~np.isnan(rate[1:])], [2.5, 97.5]))
    by14 = []
    for lab in LABELS:
        ci = [i for i in C if q14[i] == lab]
        o = [i for i in ci if cons[i] != lab]
        by14.append([lab, len(ci), len(o), _fmt(len(o) / len(ci) if ci else float("nan"), 2),
                     ", ".join(f"{k} {v}" for k, v in Counter(cons[i] for i in o).most_common()) or "-"])
    byev = []
    for g in EVIDENCE_GROUPS:
        ci = [i for i in C if ev[i] == g]
        o = [i for i in ci if cons[i] != q14[i]]
        byev.append([g, sum(1 for i in range(n) if ev[i] == g), len(ci), len(o),
                     _fmt(len(o) / len(ci) if ci else float("nan"), 2), _transitions(q14, cons, ci)])
    bytype = []
    for t in sorted(set(types), key=lambda t: (-types.count(t), t)):
        ci = [i for i in C if types[i] == t]
        o = [i for i in ci if cons[i] != q14[i]]
        bytype.append([t, len(ci), len(o), _fmt(len(o) / len(ci) if ci else float("nan"), 2)])
    L += ["## 9. Overturns of Qwen3-14B by the strong-model consensus", "",
          (f"The two strong models agree on {len(C)} of {n} units ({_fmt(len(C) / n, 3)}). Their label differs "
           f"from Qwen3-14B's on {len(over)} of these ({_fmt(len(over) / len(C) if C else float('nan'), 3)}; 95% "
           f"CI {_fmt(r_lo, 3)} to {_fmt(r_hi, 3)}, bootstrap over pairs)."), "",
          "By Qwen3-14B label:", "",
          _md_table(["Qwen3-14B label", "consensus units", "overturned", "rate", "consensus label when overturned"],
                    by14), "",
          ("By what the excerpt headers say (where the value occurs: rule match or literal match; whether NEXT "
           "holds another value in the unit's context; whether an EARLIER excerpt is shown):"), "",
          _md_table(["evidence", "units", "consensus units", "overturned", "rate", "Qwen3-14B → consensus"], byev),
          "",
          "By anchor type:", "",
          _md_table(["type", "consensus units", "overturned", "rate"], bytype), ""]

    # 10. adjudication
    L += ["## 10. Third-judge check of disagreements", ""]
    N = adj_info["N"]
    L.append(
        f"Frame: D1, the strong models disagree ({N['D1']} units); D2, they agree and Qwen3-14B differs "
        f"({N['D2']} units). Credential-like units are left out (D1 {adj_info['skipped']['D1']}, D2 "
        f"{adj_info['skipped']['D2']}). A random sample of up to {adj_info['per_stratum']} units per stratum "
        "(permanent random numbers, seed {seed}) was judged from the same excerpts, blind to every model and "
        "rule label, with the definitions of the owner's guide: a value counts as present when an excerpt shows the "
        "same fact even where no match is marked (another format or wording); modified needs the same item to hold "
        "a new value in NEXT; restored needs the earlier excerpt to show the same fact, and an unrelated earlier use "
        "of the same value counts as new. The judgments are in `data/labels/memory_pairs_adjudication.csv` "
        "(private).".replace("{seed}", str(seed)))
    L.append("")
    adj_methods = [*methods, *(m for m in ("gemini", "claude") if m in labels)]
    acc = adjudication_accuracy(adj_sample, adj_info, judged, labels, adj_methods)
    if not any(acc["judged"].values()):
        L += ["No judgments recorded yet.", ""]
    else:
        L += [(f"Judged: D1 {acc['judged']['D1']}, D2 {acc['judged']['D2']}; left undecided: "
               + (", ".join(f"{k} {v}" for k, v in sorted(acc["undecided"].items())) or "none")
               + "; judge confidence: " + ", ".join(f"{k} {v}" for k, v in sorted(acc["confidence"].items())) + "."),
              "",
              ("Accuracy against the third judge (D1 and D2 are the units each stratum stands for; overall weights "
               "the strata by their frame sizes):"), ""]
        body = []
        for m in adj_methods:
            r = acc["methods"][m]
            cells = [f"{x[0]}/{x[1]} ({_fmt(x[2], 2)})" if x else "-" for x in (r["D1"], r["D2"])]
            o = r["overall"]
            cells.append(f"{_fmt(o[0], 2)} [{_fmt(o[1], 2)}, {_fmt(o[2], 2)}]" if o else "-")
            body.append([METHOD_NAMES.get(m, m), *cells])
        L += [_md_table(["labeller", "D1 correct", "D2 correct", "all disagreements (95% CI)"], body), ""]

    # 11. review design
    cb, sb = dinfo["C_by_label"], dinfo["sample_by_label"]
    c = dinfo["counts"]
    L += ["## 11. Review design", "",
          (f"Priority 1-必标 (inclusion probability 1): stratum A, the strong models disagree or one has no valid "
           f"answer ({dinfo['A']}); stratum B, they agree and at least one rule version (v1, v2, v3) says "
           f"otherwise ({dinfo['B']}). Every unit on which two rule versions disagree is in A or B, so the paired "
           "rule-set comparisons have no sampling error from the design. Stratum C (both models and all rule "
           f"versions agree, {sum(cb.values())} units): a random sample of {dinfo['n_sample']} units (target "
           f"{dinfo['target']} rows to label, at least {dinfo['min_sample']} sampled), allocated to the labels in "
           f"proportion (seed {dinfo['seed']}, permanent random numbers) is priority 2-抽样; the other "
           f"{c[PRIORITIES[2]]} are 3-可选. Rows to label: {c[PRIORITIES[0]] + c[PRIORITIES[1]]}. The sheet records "
           "each row's design_stratum and inclusion_prob; `compute_label_metrics` weights labelled rows by 1 / "
           "inclusion probability (adjusted within a stratum for rows left unlabelled)."), "",
          _md_table(["stratum", "units", "priority", "sampled", "inclusion probability"],
                    [["A", dinfo["A"], PRIORITIES[0], dinfo["A"], "1"],
                     ["B", dinfo["B"], PRIORITIES[0], dinfo["B"], "1"]]
                    + [[f"C:{k}", cb[k], f"{PRIORITIES[1]} / {PRIORITIES[2]}", sb[k],
                        _fmt(sb[k] / cb[k] if cb[k] else float("nan"), 3)] for k in LABELS if cb[k]]), "",
          ]
    if not labelled:
        L += ["## 12. Next step", "",
              ("The owner fills `human_label` in `data/labels/memory_pairs_review.csv` (guide: "
               "`data/labels/memory_pairs_review_README.md`) for all priority 1 and 2 rows. "
               "`python -m avsd.lineage.prelabel metrics` then writes `outputs/tables/memory_label_metrics.csv`: "
               "design-weighted precision, recall and F1 with 95% intervals for rules v1, v2, v3, Qwen3-14B and the "
               "two strong models, paired v2 - v1 and v3 - v1 differences, and unweighted values for reference."), ""]
    return L


def render_qa(stats, rows, rule, llm, n, agree, disagree, kappa, ci, conf, conf_agree, errors, trunc,
              finish, cols, cm, by_type, scan, gen_runs, last, n_valid, evidence=None) -> str:
    """QA sections 1 to 4: the Qwen3-14B run, unit recovery, model output, rule v1 against Qwen3-14B."""
    c = stats.get("counts", {})
    gen_s = sum(x.get("seconds", 0) for x in gen_runs)
    out = [
        "# Module B1 validation set: LLM pre-labels (SPEC 6.3.4)",
        "",
        (f"Generated {_now()}. Aggregates only: no memory text, values, names or credentials. The review sheet "
         "`data/labels/memory_pairs_review.csv` and the prompt/output cache "
         "`data/interim/llm_cache/memory_prelabel/` stay in `data/` (gitignored)."),
        "",
        "Data: AI Digest, \"AI Village dataset\", 2026, https://theaidigest.org/village",
        "",
        "## 1. Model and run",
        "",
        _md_table(["item", "value"], [
            ["model", (f"{last.get('model', MODEL_ID)} (revision `{last.get('revision', MODEL_REVISION)[:12]}`, "
                       "Apache-2.0, bf16, inference only)")],
            ["serving", (f"vLLM {last.get('vllm', '?')} (torch {last.get('torch', '?')}), offline batch, "
                         "JSON-schema structured output, thinking disabled")],
            ["decoding", f"temperature 0 (greedy), seed {last.get('seed', '?')}, max {MAX_TOKENS} new tokens"],
            ["GPU", (f"{last.get('gpu', '?')} (one GPU), node {last.get('node', '?')}, "
                     f"Slurm job {last.get('slurm_job', '?')}")],
            ["requests", (f"{n} ({sum(x.get('generated', 0) for x in gen_runs)} generated over "
                          f"{len(gen_runs)} run(s); the rest from the cache)")],
            ["tokens", (f"{sum(x.get('prompt_tokens', 0) for x in gen_runs):,} prompt, "
                        f"{sum(x.get('output_tokens', 0) for x in gen_runs):,} output")],
            ["runtime", (f"prepare {stats.get('seconds', '?')} s (anchors {stats.get('seconds_anchors', '?')} s); "
                         f"inference {_fmt(gen_s, 0)} s (model load {last.get('seconds_load', '?')} s, "
                         f"generation {last.get('seconds_generate', '?')} s)")],
            ["prompt version", stats.get("prompt_version", PROMPT_VERSION)],
            ["input", f"`data/labels/memory_pairs.csv` sha256 `{stats.get('pairs_file_sha256', '?')[:16]}`"],
        ]),
        "",
        "## 2. Unit recovery and excerpts",
        "",
        ("Each unit is re-matched by re-running the B1 extractor on the full PREV and NEXT texts. "
         "\"Consistent\" means the presence of the unit in PREV and NEXT agrees with its rule label "
         "(kept: both; modified, dropped: PREV only; new, restored: NEXT only)."),
        "",
        _md_table(["item", "count"], [
            ["units", stats.get("units", n)], ["pairs", stats.get("pairs", "?")], ["agents", stats.get("agents", "?")],
            ["memory texts read", f"{stats.get('texts', '?')} ({stats.get('text_chars', 0):,} chars)"],
            ["pairs whose rows are not adjacent live rows", stats.get("pairs_not_adjacent", "?")],
            ["units consistent with the rule label", f"{c.get('consistent', 0)} / {stats.get('records', n)}"],
            ["unit found in PREV / NEXT by the rules", f"{c.get('unit_found_prev', 0)} / {c.get('unit_found_next', 0)}"],
            ["literal value match used (PREV / NEXT)", f"{c.get('literal_prev', 0)} / {c.get('literal_next', 0)}"],
            ["other value in the unit's context shown (PREV / NEXT)", f"{c.get('ctx_prev', 0)} / {c.get('ctx_next', 0)}"],
            ["no window at all (PREV / NEXT)", f"{c.get('no_window_prev', 0)} / {c.get('no_window_next', 0)}"],
            ["value not recovered", c.get("value_unrecovered", 0)],
            ["hashed context not recovered", c.get("ctx_hash_unrecovered", 0)],
            ["restored units with an earlier window",
             (f"{c.get('earlier_found', 0)} / {stats.get('restored', '?')} "
              f"(spells {c.get('earlier_spell', 0)}, scan {c.get('earlier_scan', 0)})")],
            ["values masked as credential-like", c.get("masked_value", 0)],
        ]),
        "",
        "Consistent units by rule label: " + ", ".join(
            f"{k} {stats.get('consistent_by_label', {}).get(k, 0)}/{stats.get('by_label', {}).get(k, 0)}" for k in LABELS),
        "",
        "## 3. Model output",
        "",
        _md_table(["item", "count"], [
            ["valid label", f"{n_valid} / {n}"],
            ["errors", ", ".join(f"{k} {v}" for k, v in sorted(errors.items())) or "none"],
            ["rationales cut to 25 words", trunc],
            ["finish reasons", ", ".join(f"{k} {v}" for k, v in sorted(finish.items())) or "n/a"],
            ["credential-scanner hits left in the sheet (scripts/scan_credentials.py)",
             "check unavailable" if scan is None else (", ".join(f"{k} {v}" for k, v in scan.items()) or "0")],
        ]),
        "",
        "## 4. Rule labels (v1) against Qwen3-14B labels",
        "",
        (f"Agreement {agree}/{n} ({_fmt(agree / n if n else float('nan'), 3)}); Cohen's kappa {_fmt(kappa)} "
         f"(95% CI {_fmt(ci[0])} to {_fmt(ci[1])}, bootstrap over pairs). Disagreements: {disagree} (the "
         "priority-1 rows of the first review design, which section 11 replaces)."),
        "",
        "Confusion matrix (rows: rule label, columns: LLM label):",
        "",
        _md_table(["rule \\ LLM", *cols, "total", "agree"],
                  [[a, *[cm.get((a, b), 0) for b in cols], sum(cm.get((a, b), 0) for b in cols),
                    _fmt(cm.get((a, a), 0) / max(1, sum(cm.get((a, b), 0) for b in cols)), 2)] for a in LABELS]),
        "",
        "LLM confidence:",
        "",
        _md_table(["confidence", "units", "agree with rule", "disagree"],
                  [[k, conf.get(k, 0), conf_agree.get((k, True), 0), conf_agree.get((k, False), 0)]
                   for k in (*CONFIDENCES, "(none)") if conf.get(k, 0)]),
        "",
        ("By what the excerpts show (a literal match is the value's text found where the B1 rules found "
         "no occurrence; these rows are the most likely rule errors):"),
        "",
        _md_table(["evidence", "units", "LLM disagrees", "LLM labels when disagreeing"], evidence or []),
        "",
        "By anchor type:",
        "",
        _md_table(["type", "units", "agree", "disagree"],
                  [[t, by_type.get((t, True), 0) + by_type.get((t, False), 0), by_type.get((t, True), 0),
                    by_type.get((t, False), 0)]
                   for t in sorted({t for t, _ in by_type}, key=lambda t: -(by_type.get((t, True), 0)
                                                                          + by_type.get((t, False), 0)))]),
        "",
    ]
    return "\n".join(out)


# --- stage 0: model weights ------------------------------------------------------------------------

def _weights_complete(dest: Path) -> bool:
    idx = dest / "model.safetensors.index.json"
    if not (idx.exists() and (dest / "config.json").exists() and (dest / "tokenizer.json").exists()):
        return False
    try:
        files = set(json.loads(idx.read_text())["weight_map"].values())
    except (ValueError, KeyError):
        return False
    return all((dest / f).exists() and (dest / f).stat().st_size > 0 for f in files)


WEIGHT_PATTERNS: tuple[str, ...] = ("*.json", "*.safetensors", "*.txt", "*.jinja", "LICENSE", "README.md")


def download(model_id: str, revision: str, dest: str | Path, log=print,
             ignore_patterns: list[str] | tuple[str, ...] = ()) -> Path:
    """Public weights, downloaded once and anonymously (no token, one snapshot request).

    Only the files of WEIGHT_PATTERNS are fetched, minus `ignore_patterns` (e.g. the original/ and
    metal/ copies of gpt-oss)."""
    dest = Path(dest).expanduser()
    marker = dest / ".avsd_revision"
    if marker.exists() and marker.read_text().strip() == revision and _weights_complete(dest):
        log(f"download: {model_id}@{revision[:12]} already in {dest}")
        return dest
    if _weights_complete(dest) and not marker.exists():
        marker.write_text(revision + "\n")
        log(f"download: found complete weights in {dest}; marked revision {revision[:12]}")
        return dest
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    for var in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        os.environ.pop(var, None)
    from huggingface_hub import snapshot_download

    t0 = time.perf_counter()
    snapshot_download(repo_id=model_id, revision=revision, local_dir=str(dest), token=False, max_workers=8,
                      allow_patterns=list(WEIGHT_PATTERNS), ignore_patterns=list(ignore_patterns) or None)
    if not _weights_complete(dest):
        raise SystemExit(f"download: {model_id}@{revision[:12]} in {dest} is incomplete")
    marker.write_text(revision + "\n")
    log(f"download: {model_id}@{revision[:12]} to {dest} in {time.perf_counter() - t0:.0f} s")
    return dest


# --- command line -----------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="LLM pre-labels for the B1 validation set (SPEC 6.3.4).")
    p.add_argument("--config", default=None)
    sub = p.add_subparsers(dest="stage", required=True)
    sp = sub.add_parser("prepare", help="recover units, build excerpts and prompts (CPU)")
    sp.add_argument("--workers", type=int, default=int(os.environ.get("SLURM_CPUS_PER_TASK") or 4))
    sp = sub.add_parser("infer", help="run one model on the requests it has not answered (vLLM env, GPU)")
    sp.add_argument("--model", choices=sorted(MODELS), default=QWEN3_14B.key)
    sp.add_argument("--model-dir", default=None, help="default ~/models/<model dir>")
    sp.add_argument("--model-id", default=None, help="Qwen3-14B only: override the repository id")
    sp.add_argument("--revision", default=None, help="Qwen3-14B only: override the revision")
    sp.add_argument("--max-model-len", type=int, default=None)
    sp.add_argument("--gpu-memory-utilization", type=float, default=None, help="default: the model's setting")
    sp.add_argument("--enforce-eager", action=argparse.BooleanOptionalAction, default=None,
                    help="default: the model's setting (eager)")
    sp.add_argument("--limit", type=int, default=None, help="only the first N requests (smoke test)")
    sp.add_argument("--task", action="append", choices=("memory", "parents"), default=None,
                    help="memory (B1, default) and/or parents (B2 parent sheet, avsd.lineage.prelabel_parents); "
                         "the model is loaded once for all")
    sub.add_parser("report", help="review sheet, README and QA report")
    sub.add_parser("metrics", help="precision/recall/F1 against the owner's human labels")
    sub.add_parser("import-claude", help="gather Claude's blind labels into data/labels/memory_pairs_claude.csv")
    sp = sub.add_parser("download", help="download the model weights once (anonymous)")
    sp.add_argument("--model", choices=sorted(MODELS), default=None,
                    help="a registered model (sets id, revision, destination and skipped files)")
    sp.add_argument("--model-id", default=MODEL_ID)
    sp.add_argument("--revision", default=MODEL_REVISION)
    sp.add_argument("--dest", default=None, help="default ~/models/<model dir>")
    sp.add_argument("--exclude", action="append", default=[], help="glob of repository files to skip")
    args = p.parse_args(argv)
    if args.stage == "download":
        if args.model:
            m = MODELS[args.model]
            download(m.model_id, m.revision, args.dest or Path.home() / "models" / m.dir_name,
                     ignore_patterns=[*m.exclude, *args.exclude])
        else:
            download(args.model_id, args.revision, args.dest or Path.home() / "models" / "Qwen3-14B",
                     ignore_patterns=args.exclude)
        return
    from avsd.config import load_config

    cfg = load_config(args.config)

    def log(*a):  # flushed, so job logs show progress while a long generation runs
        print(*a, flush=True)

    if args.stage == "prepare":
        prepare(cfg, workers=args.workers, log=log)
    elif args.stage == "infer":
        spec = MODELS[args.model]
        if args.model_id or args.revision:
            if spec.key != QWEN3_14B.key:
                raise SystemExit("--model-id and --revision only apply to Qwen3-14B")
            spec = replace(spec, model_id=args.model_id or spec.model_id, revision=args.revision or spec.revision)
        tasks = []
        for t in args.task or ["memory"]:
            if t == "parents":
                from avsd.lineage import prelabel_parents

                tasks.append((prelabel_parents.PARENT_TASK, prelabel_parents.cache_dir(cfg)))
            else:
                tasks.append((None, cache_dir(cfg)))
        infer(cfg, args.model_dir or Path.home() / "models" / spec.dir_name, spec, args.max_model_len,
              args.gpu_memory_utilization, args.enforce_eager, args.limit, log=log, tasks=tasks)
    elif args.stage == "report":
        report(cfg, log=log)
    elif args.stage == "import-claude":
        import_claude_labels(cfg, log=log)
    else:
        rows = compute_label_metrics(cfg)
        for scheme in dict.fromkeys(r["scheme"] for r in rows):
            sel = [r for r in rows if r["scheme"] == scheme]
            print(sel[0]["note"])
            print(format_metrics(rows, scheme))
            print()


if __name__ == "__main__":
    main(sys.argv[1:])
