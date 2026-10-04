"""Lexical indicators of module C (SPEC 7.1): question flags, "genuinely" and family words.

Text is the full content of agent chat messages (`chat_messages.content`). Before counting, code
spans, URLs, e-mail addresses and @-handles are removed and curly apostrophes straightened. A
message is a question when a "?" ends a clause (followed by space, a closing mark or the end).
Tokens are runs of ASCII letters (with inner apostrophes), lower-cased.

Family-characteristic words are the TOP_K words per model family with the largest z-scored
log-odds ratio under an informative Dirichlet prior (Monroe, Colaresi and Quinn 2008, eq. 22),
each family against all other families pooled:

    delta_w = log((y_fw + a_w) / (n_f + a_0 - y_fw - a_w)) - log((y_rw + a_w) / (n_r + a_0 - y_rw - a_w)),
    var_w = 1 / (y_fw + a_w) + 1 / (y_rw + a_w),    z_w = delta_w / sqrt(var_w),

with token counts y, token totals n, and prior a_w = a_0 * (corpus share of w), a_0 = PRIOR_SIZE.
The corpus is the standard-scaffold agents (the Claude Code agent is analysed separately).

Outputs carry words and rates only. A candidate word must be used MIN_COUNT times in the family, on
MIN_DAYS run days and by MIN_AGENTS agents, and pass these filters (agent-family vocabulary, the
tokens of agent names and providers, is exempt from the first two):
- proper nouns: capitalised in more than MAX_CAP_SHARE of its mid-sentence uses (names of people);
- human display names: tokens of any viewer display name (`events_text.speaker_name`, read in
  memory only and never written);
- shape: 3 to 20 letters, a vowel, no run of 6 consonants (key-like strings).
E-mail addresses, URLs and handles never become tokens. English stop words (scikit-learn's list)
are not candidates: in a corpus this large their z-scores are high, while their rates per message
mostly follow message length, which has its own series.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

FOCUS_WORD = "genuinely"
TOP_K = 20
PRIOR_SIZE = 1000.0
MIN_COUNT = 50
MIN_DAYS = 10
MIN_AGENTS = 2
MIN_MID_USES = 10
MAX_CAP_SHARE = 0.5
WORD_LEN = (3, 20)
PROVIDER_WORDS = ("anthropic", "openai", "google", "deepmind", "xai", "moonshot", "zhipu", "meta",
                  "tinker", "deepseek")

CODE = r"```[\s\S]*?```|`[^`\n]*`"
URL = r"(?:https?://|www\.)\S+"
EMAIL = r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
HANDLE = r"@[\w.-]+"
TOKEN = r"[A-Za-z]+(?:'[A-Za-z]+)*"
INITIAL = r"(?:^|[.!?]\s+|\n\s*)[^A-Za-z\s]{0,3}[A-Za-z]+(?:'[A-Za-z]+)*"
QUESTION = r"\?(?:[\s\"'”’)\]*_]|$)"


def clean_text(expr: pl.Expr) -> pl.Expr:
    """Message text without code spans, URLs, e-mail addresses and handles."""
    e = expr.fill_null("").str.replace_all("’", "'", literal=True)
    for pat in (CODE, URL, EMAIL, HANDLE):
        e = e.str.replace_all(pat, " ")
    return e


def _is_cap(tok: pl.Expr) -> pl.Expr:
    """Capitalised (Title case), not an all-caps acronym."""
    caps = tok.str.contains(r"^[A-Z]+(?:'[A-Z]+)*$") & (tok.str.len_chars() > 1)
    return tok.str.contains(r"^[A-Z]") & ~caps


def name_tokens(names: list[str]) -> set[str]:
    """Lower-case letter tokens of at least 3 letters."""
    out: set[str] = set()
    for n in names:
        out.update(t.lower() for t in re.findall(r"[A-Za-z]+", n or "") if len(t) >= 3)
    return out


_NEG = {"don", "doesn", "didn", "isn", "aren", "wasn", "weren", "won", "can", "couldn", "shouldn",
        "wouldn", "haven", "hasn", "hadn"}


def is_stop_word(word: str) -> bool:
    """scikit-learn English stop word, or a contraction of one (we're, it's, don't)."""
    base = word.split("'")[0]
    return word in ENGLISH_STOP_WORDS or ("'" in word and (base in ENGLISH_STOP_WORDS or base in _NEG))


def shape_ok(word: str) -> bool:
    """3 to 20 letters, a vowel, and no run of 6 consonants."""
    return (WORD_LEN[0] <= len(word) <= WORD_LEN[1] and re.search(r"[aeiouy]", word) is not None
            and re.search(r"[^aeiouy']{6}", word) is None)


@dataclass
class Lexical:
    """Per agent-day question and word counts, and the family word table."""

    question: pl.DataFrame                 # agent_id, run_day, n_question
    word_counts: pl.DataFrame              # agent_id, run_day, w_<word> ...
    words: pl.DataFrame                    # family, rank, word, z, delta, counts and rates
    family_words: dict[str, list[str]]     # family -> words with a series (FOCUS_WORD first)
    filter_counts: dict[str, int] = field(default_factory=dict)   # candidates removed, by filter
    list_sizes: dict[str, int] = field(default_factory=dict)      # sizes of the filter lists


def tokenize(msgs: pl.DataFrame) -> pl.DataFrame:
    """Add `is_question`, `tok` (original case) and `tok_init` (sentence-initial tokens)."""
    m = msgs.with_columns(clean_text(pl.col("content")).alias("_clean"))
    return m.with_columns(
        pl.col("_clean").str.contains(QUESTION).alias("is_question"),
        pl.col("_clean").str.extract_all(TOKEN).alias("tok"),
        pl.col("_clean").str.extract_all(INITIAL)
        .list.eval(pl.element().str.extract(TOKEN + "$", 0)).alias("tok_init"),
    ).drop("_clean", "content")


def log_odds(counts: pl.DataFrame, family: str, prior_size: float = PRIOR_SIZE) -> pl.DataFrame:
    """z-scored log-odds (informative Dirichlet prior) of `family` against the rest.

    `counts` has columns w, family, n (token counts). Returns w, y_f, y_r, delta, z.
    """
    tot = counts.group_by("w").agg(pl.col("n").sum().alias("y"))
    yf = counts.filter(pl.col("family") == family).select("w", pl.col("n").alias("y_f"))
    d = tot.join(yf, on="w", how="left").with_columns(pl.col("y_f").fill_null(0))
    d = d.with_columns((pl.col("y") - pl.col("y_f")).alias("y_r"))
    n = float(d["y"].sum())
    nf, nr = float(d["y_f"].sum()), float(d["y_r"].sum())
    a = prior_size * pl.col("y") / n
    yf_, yr_ = pl.col("y_f") + a, pl.col("y_r") + a
    delta = ((yf_ / (nf + prior_size - yf_)).log() - (yr_ / (nr + prior_size - yr_)).log())
    var = 1.0 / yf_ + 1.0 / yr_
    return d.with_columns(delta.alias("delta"), (delta / var.sqrt()).alias("z")).select(
        "w", "y_f", "y_r", "delta", "z")


def lexical_components(
    msgs: pl.DataFrame, agents: pl.DataFrame, display_names: list[str], families: tuple[str, ...],
    top_k: int = TOP_K,
) -> Lexical:
    """Question and word counts per agent-day and the family word table.

    `msgs`: agent_id, run_day, content (one row per agent chat message). `agents`: agent_id, name,
    model_family, scaffold.
    """
    meta = agents.select("agent_id", "model_family", "scaffold")
    t = tokenize(msgs.join(meta, on="agent_id", how="left"))
    question = t.group_by("agent_id", "run_day").agg(pl.col("is_question").sum().alias("n_question"))

    long = (
        t.select("agent_id", "run_day", "model_family", "scaffold", "tok")
        .explode("tok").drop_nulls("tok")
        .with_columns(pl.col("tok").str.to_lowercase().alias("w"), _is_cap(pl.col("tok")).alias("cap"))
        .drop("tok")
    )
    init = (
        t.select("tok_init").explode("tok_init").drop_nulls("tok_init")
        .select(pl.col("tok_init").str.to_lowercase().alias("w"), _is_cap(pl.col("tok_init")).alias("cap"))
        .group_by("w").agg(pl.len().alias("n_init"), pl.col("cap").sum().alias("cap_init"))
    )
    case = (
        long.group_by("w").agg(pl.len().alias("n_all"), pl.col("cap").sum().alias("cap_all"))
        .join(init, on="w", how="left")
        .with_columns(pl.col("n_init").fill_null(0), pl.col("cap_init").fill_null(0))
        .with_columns((pl.col("n_all") - pl.col("n_init")).alias("n_mid"),
                      (pl.col("cap_all") - pl.col("cap_init")).alias("cap_mid"))
    )
    proper = set(
        case.filter((pl.col("n_mid") >= MIN_MID_USES)
                    & (pl.col("cap_mid") > MAX_CAP_SHARE * pl.col("n_mid")))["w"].to_list()
    )
    vocab = name_tokens(agents["name"].to_list()) | {f.lower() for f in families} | set(PROVIDER_WORDS)
    blocked = name_tokens(display_names) - vocab
    proper -= vocab

    std = long.filter(pl.col("scaffold") == "standard")
    fam_counts = std.group_by("model_family", "w").agg(
        pl.len().alias("n"), pl.col("run_day").n_unique().alias("n_days"),
        pl.col("agent_id").n_unique().alias("n_agents"),
    ).rename({"model_family": "family"})
    n_msgs = dict(
        t.filter(pl.col("scaffold") == "standard").group_by("model_family").len().iter_rows()
    )
    fam_agents = dict(
        t.filter(pl.col("scaffold") == "standard").group_by("model_family")
        .agg(pl.col("agent_id").n_unique()).iter_rows()
    )
    filters = {"stop word": 0, "proper noun": 0, "display name": 0, "shape": 0}
    rows, family_words = [], {}
    for fam in families:
        lo = log_odds(fam_counts.select("w", "family", "n"), fam)
        f = fam_counts.filter(pl.col("family") == fam).select("w", "n_days", "n_agents")
        cand = (
            lo.join(f, on="w", how="left")
            .filter((pl.col("y_f") >= MIN_COUNT) & (pl.col("n_days") >= MIN_DAYS)
                    & (pl.col("n_agents") >= min(MIN_AGENTS, fam_agents.get(fam, 1)))
                    & (pl.col("z") > 0))
            .sort("z", descending=True)
        )
        chosen = []
        for r in cand.iter_rows(named=True):
            w = r["w"]
            reason = ("stop word" if is_stop_word(w) and w != FOCUS_WORD
                      else "proper noun" if w in proper else "display name" if w in blocked
                      else None if w in vocab or shape_ok(w) else "shape")
            if reason:
                filters[reason] += 1
                continue
            chosen.append(r)
            if len(chosen) == top_k:
                break
        nf, nr = n_msgs.get(fam, 0), sum(n_msgs.values()) - n_msgs.get(fam, 0)
        for rank, r in enumerate(chosen, 1):
            rows.append({
                "family": fam, "rank": rank, "word": r["w"], "z": r["z"], "delta": r["delta"],
                "count_family": int(r["y_f"]), "count_rest": int(r["y_r"]),
                "rate_family_per_1000_msgs": 1000.0 * r["y_f"] / max(nf, 1),
                "rate_rest_per_1000_msgs": 1000.0 * r["y_r"] / max(nr, 1),
            })
        family_words[fam] = [FOCUS_WORD, *[r["w"] for r in chosen if r["w"] != FOCUS_WORD]]
    words = pl.DataFrame(rows)
    keep = sorted({w for ws in family_words.values() for w in ws})
    wc = (
        long.filter(pl.col("w").is_in(keep))
        .group_by("agent_id", "run_day", "w").len()
        .pivot(on="w", index=["agent_id", "run_day"], values="len")
    )
    for w in keep:
        if w not in wc.columns:
            wc = wc.with_columns(pl.lit(0, dtype=pl.UInt32).alias(w))
    wc = wc.select("agent_id", "run_day", *[pl.col(w).fill_null(0).alias(f"w_{w}") for w in keep])
    sizes = {"display-name tokens": len(blocked), "proper-noun tokens": len(proper)}
    return Lexical(question, wc, words, family_words, filters, sizes)


def load_display_names(tables: Path) -> list[str]:
    """Distinct viewer display names (in memory only, for the blocklist)."""
    return (
        pl.scan_parquet(Path(tables) / "events_text.parquet")
        .select("speaker_name").drop_nulls().unique().collect()["speaker_name"].to_list()
    )
