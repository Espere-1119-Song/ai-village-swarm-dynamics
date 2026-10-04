"""Tier-1 explicit parent labels for the reference check of module A (SPEC 5.6-3).

docs/decisions.md ("Parent labels"; schema_notes 4.1): chat rows carry no reply field, so labels
come from the message text. Tier 1, used here, is from 2026-02-25 on (precision about 0.9 on a
small sample):

- single-target reciprocal name references: the agent message names exactly one other agent
  (an @-mention, an address at the start, an attribution such as "as X said" or "X's point", or a
  response marker such as "building on X"), that agent has a message among the previous 50 rows
  of the room (the latest one is the parent), and that parent message names the child's author;
- quotes with a unique match: a quoted span (straight or curly quotes, or a "> " line) of at least
  20 characters and 4 words occurs in exactly one of the previous 50 rows of the room by someone
  other than the child's author, which is the parent.

A child with two tier-1 labels that disagree is dropped. Only agent children are labelled (agent
messages are the modelled events). The baseline parent of SPEC 5.6-3 is the most recent earlier
row of the room by someone else among the rows module A uses (agent messages, human messages,
nudges; the bot's run markers are left out). This module ports the rules of the SPEC 2.3
verification (schema_notes 4.1) unchanged. Labels hold message ids only and stay in data/.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from pathlib import Path

import polars as pl

TIER1_FROM = date(2026, 2, 25)
LOOKBACK = 50          # rows of the room searched for the parent
RECENT = 200           # rows whose agents resolve an ambiguous alias
_DASH = "\\s\\-‐‑‒– "


def _flex(s: str) -> str:
    out = ""
    for ch in s:
        if ch in " -":
            out += f"[{_DASH}]?"
        elif ch == ".":
            out += r"\."
        elif ch in "()[]":
            out += "\\" + ch
        else:
            out += ch
    return out


def _key(s: str) -> str:
    return re.sub(f"[{_DASH}]", "", s.lower())


class AliasMatcher:
    """Agent-name references in text: (start, end, is_at, candidate agent ids, family alias)."""

    def __init__(self, names: dict[str, str]):
        aliases: dict[tuple[str, bool], tuple[set[str], bool]] = {}

        def add(alias: str, ns: list[str], fam: bool = False, cs: bool = False) -> None:
            k = (alias, cs)
            old = aliases.get(k, (set(), False))
            aliases[k] = (old[0] | set(ns), old[1] or fam)

        all_names = list(names.values())
        for n in all_names:
            if n.startswith("[Temporary]") or "Leader" in n:
                continue
            add(n, [n])
            m = re.match(r"Claude (Opus|Sonnet|Haiku|Fable) ([\d.]+)$", n)
            if m:
                add(f"{m[1]} {m[2]}", [n]), add(f"Claude {m[2]} {m[1]}", [n]), add(f"{m[2]} {m[1]}", [n])
                add(m[1], [n], fam=True)
            m = re.match(r"Claude ([\d.]+) Sonnet$", n)
            if m:
                for a in (f"Claude {m[1]}", f"Sonnet {m[1]}", f"{m[1]} Sonnet", f"Claude Sonnet {m[1]}"):
                    add(a, [n])
                add("Sonnet", [n], fam=True)
            m = re.match(r"Gemini ([\d.]+) (Pro|Flash)$", n)
            if m:
                add(f"Gemini {m[1]}", [n]), add(f"{m[1]} {m[2]}", [n]), add(f"Gemini {m[2]}", [n], fam=True)
            if n.startswith("Gemini"):
                add("Gemini", [n], fam=True)
            m = re.match(r"GPT-([\d.]+)( (\w+))?$", n)
            if m:
                add(f"GPT-{m[1]}", [n], fam=bool(m[2]))
                if m[3]:
                    add(m[3], [n], cs=True)
                add("GPT", [n], fam=True)
            if n.startswith("Grok"):
                add("Grok", [n], fam=True), add(n.replace(" ", "-"), [n])
            if n.startswith("Kimi"):
                add("Kimi", [n], fam=True), add(n.split()[1], [n], cs=True)
            if n.startswith("GLM"):
                add("GLM", [n], fam=True), add(n.split()[0], [n])
            if n.startswith("DeepSeek"):
                add("DeepSeek", [n], fam=True)
            if n.startswith("Claude"):
                add("Claude", [n], fam=True)
            if n == "GPT-4o":
                add("4o", [n])
            if n == "DeepSeek-V3.2":
                add("V3.2", [n], cs=True)
            if n == "DeepSeek-V4-Pro":
                add("DeepSeek V4", [n]), add("V4-Pro", [n])
            if n == "Muse Spark 1.3":
                add("Muse Spark", [n]), add("Muse", [n], cs=True)
            if n == "Opus 4.5 (Claude Code)":
                add("Claude Code", [n])
            if n in ("o1", "o3", "o4-mini"):
                aliases.pop((n, False), None)
                add(n, [n], cs=True)
        leaders = [n for n in all_names if "Leader" in n]
        if leaders:
            add("Fine-tuned Leader", leaders), add("Fine tuned Leader", leaders)
        bound_l, bound_r = "(?<![\\w.\\-/‑])", r"(?![\w]|[.\-]?\d|[.\-]\w)"

        def build(cs: bool) -> re.Pattern | None:
            items = sorted([k[0] for k in aliases if k[1] == cs], key=len, reverse=True)
            if not items:
                return None
            return re.compile(bound_l + "(@)?(" + "|".join(_flex(a) for a in items) + ")" + bound_r,
                              0 if cs else re.I)

        self.rx = [build(False), build(True)]
        name_to_id = {}
        for i, n in names.items():
            name_to_id.setdefault(n, i)
        self.lookup: dict[tuple[str, bool], tuple[frozenset[str], bool]] = {}
        for (a, cs), (ns, fam) in aliases.items():
            k = (_key(a), cs)
            old = self.lookup.get(k, (frozenset(), False))
            self.lookup[k] = (old[0] | frozenset(name_to_id[n] for n in ns), old[1] or fam)

    def find(self, text: str) -> list[tuple[int, int, bool, frozenset[str], bool]]:
        out = []
        for i, rx in enumerate(self.rx):
            if rx is None:
                continue
            for m in rx.finditer(text):
                cands, fam = self.lookup[(_key(m[2]), i == 1)]
                out.append((m.start(), m.end(), bool(m[1]), cands, fam))
        out.sort(key=lambda r: (r[0], -(r[1] - r[0])))
        res, last = [], -1
        for r in out:                     # overlapping matches: keep the longest
            if r[0] >= last:
                res.append(r)
                last = r[1]
        return res


_GREET = (r"(?:(?:hi|hey|hello|thanks|thank you|thx|ty|great|good|nice|perfect|excellent|agreed|agree|yes|ok|okay|"
          r"congrats|congratulations|welcome|welcome back|good catch|great catch|great work|nice work|great point|"
          r"good point|re|reply to|replying to|to|cc|ping|quick q(?:uestion)? for|question for|update for|note for)"
          r"[\s,!:.\-–—]+(?:so much[\s,!]+)?(?:to\s+)?)")
_LEAD = r'^[\s>*_#\[\(`"“]*'
_SAYV = (r"(?:said|says|mentioned|mentions|noted|notes|suggested|suggests|pointed out|points out|reported|reports|"
         r"wrote|writes|asked|asks|proposed|proposes|flagged|flags|confirmed|confirms|shared|shares|posted|posts|"
         r"found|observed|indicated|stated|explained|raised|highlighted|recommended|announced|described|claimed|"
         r"argued)")
_POSS = (r"(?:'s|’s)\s+(?:message|messages|point|points|suggestion|suggestions|idea|ideas|update|updates|report|"
         r"question|questions|proposal|note|notes|finding|findings|analysis|comment|comments|plan|request|concern|"
         r"concerns|observation|feedback|summary|list|draft|work|fix|post|reply|response|answer|advice|"
         r"recommendation|insight|catch|offer|framing|approach|data|numbers|results|guidance|reminder|ask|"
         r"point about)\b")
_RESP = (r"(?:per|building on|build on|following up on|following up with|responding to|replying to|in response to|"
         r"re:|agree with|agreed with|agreeing with|echoing|echo|seconding|second|to answer|answering|thanks to|"
         r"thank you|thanks|thank you,|as requested by|at the request of)\s+@?$")
_QUOTES = (re.compile(r'"([^"\n]{12,400})"'), re.compile(r"“([^”\n]{12,400})”"),
           re.compile(r"(?m)^\s*>\s?(.{12,400})$"))


def _referenced(text: str, refs) -> list[tuple[frozenset[str], bool]]:
    """Candidate sets of the name references in the four groups (mention, address, attribution,
    response or possessive) of the verification."""
    out = []
    for s, e, at, cands, fam in refs:
        hit = at
        pre = text[:s]
        if re.fullmatch(_LEAD + r"@?", pre, re.I) and (
                re.match(r"\s*[,:!—–\-]|\s*\)|\s+(?:—|–|-)|\s*[,:]", text[e:e + 4]) or at):
            hit = True
        if s < 80 and re.fullmatch(_LEAD + r"(?:@?[^\s,]+(?:\s[^\s,]+)?\s*(?:,|&|and)\s*)*" + _GREET
                                   + r"?@?(?:[\w.\-]+\s*(?:,|&|and)\s*)*@?", pre, re.I):
            hit = True
        tail, pre40 = text[e:e + 40], text[max(0, s - 40):s]
        if re.match(r"\s+(?:just\s+|already\s+|also\s+|earlier\s+|previously\s+|correctly\s+|rightly\s+|"
                    r"helpfully\s+)?" + _SAYV + r"\b", tail, re.I) or re.match(_POSS, tail, re.I):
            hit = True
        if re.search(r"(?:^|[\s(,;:])" + _RESP, pre40, re.I):
            hit = True
        if hit:
            out.append((cands, fam))
    return out


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"\s+", " ", s.lower()).strip()
    return s.strip(" .,:;!?*_`\"'…-")


def quote_spans(text: str) -> list[str]:
    spans = []
    for rx in _QUOTES:
        for m in rx.finditer(text):
            q = _norm(m[1])
            if len(q) >= 20 and len(q.split()) >= 4:
                spans.append(q)
    return spans


def tier1_labels(rows: pl.DataFrame, names: dict[str, str], since: date = TIER1_FROM) -> pl.DataFrame:
    """Tier-1 labels for agent children on or after `since`.

    rows: every chat row with id, speaker (agent id, account id or "bot"), is_agent, eligible (a
    row module A uses: agent message, human message or nudge), content, room_id, ts_utc, date (PT).
    Returns child_id, parent_id, label ("nameref", "quote" or "both"), baseline_id."""
    matcher = AliasMatcher(names)
    out = []
    for room in rows.partition_by("room_id", maintain_order=True):
        room = room.sort("ts_utc", "id")
        ids, spk, agent = room["id"].to_list(), room["speaker"].to_list(), room["is_agent"].to_list()
        elig, txt = room["eligible"].to_list(), [t or "" for t in room["content"].to_list()]
        dates = room["date"].to_list()
        first = next((i for i, d in enumerate(dates) if d >= since), None)
        if first is None:
            continue
        refs: dict[int, list] = {}
        norm: dict[int, str] = {}

        def refs_of(j: int):
            if j not in refs:
                refs[j] = matcher.find(txt[j])
            return refs[j]

        for i in range(first, len(ids)):
            if not agent[i]:
                continue
            me = spk[i]
            recent = {spk[j] for j in range(max(0, i - RECENT), i) if agent[j]}

            def resolve(cands: frozenset[str]) -> str | None:
                if len(cands) == 1:
                    return next(iter(cands))
                c = cands & recent
                return next(iter(c)) if len(c) == 1 else None

            labels = defaultdict(set)
            targets = {r for r in (resolve(c) for c, _ in _referenced(txt[i], refs_of(i))) if r and r != me}
            if len(targets) == 1:
                tg = next(iter(targets))
                p = next((j for j in range(i - 1, max(-1, i - 1 - LOOKBACK), -1) if spk[j] == tg), None)
                if p is not None and any(me in r[3] and len(r[3]) == 1 for r in refs_of(p)) or (
                        p is not None and any(resolve(r[3]) == me for r in refs_of(p))):
                    labels[p].add("nameref")
            spans = quote_spans(txt[i])
            if spans:
                hits = []
                for j in range(i - 1, max(-1, i - 1 - LOOKBACK), -1):
                    if spk[j] == me:
                        continue
                    if j not in norm:
                        norm[j] = _norm(txt[j])
                    if any(q in norm[j] for q in spans):
                        hits.append(j)
                if len(hits) == 1:
                    labels[hits[0]].add("quote")
            if len(labels) != 1:
                continue
            p, kinds = next(iter(labels.items()))
            base = next((j for j in range(i - 1, -1, -1) if elig[j] and spk[j] != me), None)
            out.append({"child_id": ids[i], "parent_id": ids[p], "label": "both" if len(kinds) == 2 else
                        next(iter(kinds)), "baseline_id": ids[base] if base is not None else None})
    schema = {"child_id": pl.String, "parent_id": pl.String, "label": pl.String, "baseline_id": pl.String}
    return pl.DataFrame(out, schema=schema)


def load_label_rows(processed: Path, tables: Path) -> tuple[pl.DataFrame, dict[str, str]]:
    """Chat rows for tier1_labels and the agent names (id -> name)."""
    cm = pl.read_parquet(Path(tables) / "chat_messages.parquet",
                         columns=["id", "speaker_type", "agent_speaker_id", "user_speaker_id", "content", "room_id",
                                  "created_at"])
    ev = (pl.scan_parquet(Path(processed) / "events_unified.parquet")
          .filter(pl.col("source") == "chat")
          .select(pl.col("event_uid").str.strip_prefix("chat:").alias("id"), "kind", "subkind", "actor_type")
          .collect())
    rows = cm.join(ev, on="id", how="left").with_columns(
        (pl.col("speaker_type") == "agent").alias("is_agent"),
        pl.coalesce("agent_speaker_id", "user_speaker_id").alias("speaker"),
        (pl.col("kind").is_in(["agent_msg", "human_msg"])
         | ((pl.col("kind") == "system_msg") & (pl.col("subkind") == "nudge"))).fill_null(False).alias("eligible"),
        pl.col("created_at").dt.replace_time_zone("UTC").alias("ts_utc"),
    ).with_columns(pl.col("ts_utc").dt.convert_time_zone("America/Los_Angeles").dt.date().alias("date"))
    names = dict(pl.read_parquet(Path(processed) / "agents.parquet", columns=["agent_id", "name"]).iter_rows())
    return rows.select("id", "speaker", "is_agent", "eligible", "content", "room_id", "ts_utc", "date"), names
