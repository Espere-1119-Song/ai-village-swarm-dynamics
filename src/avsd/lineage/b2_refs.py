"""Explicit-reference parent labels for module B2 (SPEC 6.4.5, 5.6-3; decisions "Parent labels").

`chat_messages` has no reply field (schema_notes 4.1), so labels come from the
message text, as in the SPEC 2.3-1 verification:

- Name references to another agent: an @-mention, an address at the start of
  the message (after an optional greeting), an attribution ("X said", "as X
  noted") or an extended reference ("agree with X", "X's point"). Agent names
  and short forms come from `anchors.agent_aliases` (B1); a bare family word
  ("Claude", "Gemini") counts when exactly one agent of that family spoke in
  the room within the last 200 messages. The labelled parent is the target's
  latest message in the same room within the previous 50 messages.
- Quotes: a quoted span of 20 to 500 characters and at least 4 words ("...",
  “...”) or a block-quote line, matched after normalisation against the
  previous 50 messages of the room by other speakers; only a span that matches
  exactly one earlier message gives a label (its latest match).

Tiers (decisions "Parent labels"): tier 1 holds single-target name references
whose parent names the child's author (reciprocal) and unique quote matches,
from 2026-02-25 on (precision about 0.9 on a small sample). Tier 2 holds the
other single-target name references (precision undetermined). Earlier quotes
are left out (precision about 0.35). Name labels serve the content-term
ablation and the gamma grid; quote labels share text with their parent by
construction, so they serve only the time term.

Only agent messages are children. Humans and the scaffolding bot can be
parents; humans appear as `human` in every output.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import polars as pl

from avsd.lineage.anchors import agent_aliases

TIER1_FROM = date(2026, 2, 25)
NAME_WINDOW = 50
FAMILY_WINDOW = 200
QUOTE_WINDOW = 50
FAMILY_WORDS = ("claude", "gemini", "gpt", "grok", "deepseek", "kimi", "glm", "opus", "sonnet", "haiku", "fable")
_GREET = (r"(?:hi|hey|hello|thanks|thank you|thank you so much|thanks so much|great|good|excellent|perfect|yes|"
          r"ok|okay|welcome|congrats|congratulations|dear|to|re|absolutely|agreed|nice|wonderful|understood|"
          r"got it|confirmed|noted|well done|good catch|great work|excellent work|nice work|nice catch|"
          r"great catch|great question|sure|done|replying to|responding to|update for|note for|question for|"
          r"for|cc|attn|and|&)")
PRE_STRICT = re.compile(r"^[\s*_>#]*@?\s?$")
PRE_LOOSE = re.compile(r"^[\s*_>#\-•\d.)]*(?:" + _GREET + r"\b[\s,!.:;—–\-]*)*[\s*_]*@?\s?$", re.I)
FOLLOW_PUN = re.compile(r"^[*_]*\s*[,:;!—–\-]")
_VERBS = (r"(?:said|says|mentioned|mentions|noted|notes|suggested|suggests|pointed out|points out|proposed|"
          r"proposes|reported|reports|flagged|flags|raised|asked|asks|requested|explained|confirmed|confirms|"
          r"recommended|stated|wrote|shared|highlighted|observed|argued|posted|announced|indicated|clarified|"
          r"emphasized)")
ATTR_AFTER = re.compile(r"^[*_]*(?:\s*\([^)]{0,30}\))?\s+(?:(?:has|had|just|already|also|correctly|rightly|"
                        r"helpfully|earlier|previously|kindly|then|now)\s+)*" + _VERBS + r"\b", re.I)
AS_BEFORE = re.compile(r"\bas\s+[*_]*@?\s?$", re.I)
EXT_POSS = re.compile(r"^[*_]*['’]s\s+(?:point|suggestion|idea|update|message|note|question|proposal|comment|"
                      r"feedback|report|analysis|summary|finding|findings|plan|request|work|observation|concern|"
                      r"catch|reply|response)\b", re.I)
EXT_BEFORE = re.compile(r"(?:\bagree(?:d|s)?\s+with|\bthanks?(?: you)?,?\s+(?:to\s+)?|\bper|building on|"
                        r"following up on|responding to|replying to|\bre:?)\s+[*_]*@?\s?$", re.I)
QUOTE_RX = (re.compile(r'"([^"\n]{20,500})"'), re.compile(r"“([^”\n]{20,500})”"))
BLOCK_QUOTE = re.compile(r"^\s*>\s?(.+)$", re.M)
CORE_KINDS = frozenset({"at", "loose", "attr", "asx"})


def _name_rx(alias: str) -> str:
    out = ""
    for ch in alias:
        if ch == "-":
            out += r"[\-‐‑‒– ]?"
        elif ch == " ":
            out += r"[\s\-‑]+"
        else:
            out += re.escape(ch)
    return out


class NameMatcher:
    """Name references in chat text (aliases from B1, family words resolved by recent speakers)."""

    def __init__(self, agents: pl.DataFrame):
        name_to_id = {n.lower(): a for a, n in agents.select("agent_id", "name").iter_rows()}
        family: dict[str, list[str]] = {f: [] for f in FAMILY_WORDS}
        for a, n in agents.select("agent_id", "name").iter_rows():
            low = n.lower()
            for f in FAMILY_WORDS:
                if f in low:
                    family[f].append(a)
        pairs, _ = agent_aliases(agents["name"].to_list())
        parts, self.groups = [], {}
        k = 0
        for pat, canon in pairs:
            if canon.startswith("bare:"):
                word = canon[5:]
                if word in family:
                    parts.append(f"(?P<g{k}>{pat})")
                    self.groups[f"g{k}"] = ("FAM", word)
                    k += 1
                continue
            aid = name_to_id.get(canon)
            if aid is None:
                continue
            parts.append(f"(?P<g{k}>{pat})")
            self.groups[f"g{k}"] = aid
            k += 1
        self.family = family
        self.rx = re.compile(r"(?i)(?<![\w@.‑\-])@?\s?(?:" + "|".join(parts) + r")(?![\w‑]|\.\d|-\d)")

    def refs(self, text: str, recent: set[str], author: str | None) -> list[tuple[str | None, set[str]]]:
        """(target agent id or None, kinds) for every name in the text."""
        out = []
        prev_end, prev_addr = None, False
        for m in self.rx.finditer(text or ""):
            tgt = self.groups[m.lastgroup]
            if isinstance(tgt, tuple):
                cands = [a for a in self.family.get(tgt[1], []) if a in recent and a != author]
                tgt = cands[0] if len(cands) == 1 else None
            s, pre, post = m.group(0), text[:m.start()], text[m.end():]
            kinds = {"any"}
            has_at = "@" in s
            if has_at:
                kinds.add("at")
            chain = prev_addr and re.fullmatch(r"[\s,&*_]*(?:and\s*)?[\s*_]*@?\s?", text[prev_end:m.start()], re.I)
            if (PRE_STRICT.match(pre) and (has_at or FOLLOW_PUN.match(post))) or chain:
                kinds.update({"strict", "loose"})
            elif PRE_LOOSE.match(pre):
                kinds.add("loose")
            if ATTR_AFTER.match(post):
                kinds.add("attr")
                if AS_BEFORE.search(pre):
                    kinds.add("asx")
            if EXT_POSS.match(post) or EXT_BEFORE.search(pre):
                kinds.add("ext")
            prev_addr = "loose" in kinds and len(pre.strip()) < 80
            prev_end = m.end()
            out.append((tgt, kinds))
        return out


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("‑", "-")
    s = re.sub(r"[*_`]", "", s)
    return re.sub(r"\s+", " ", s).strip().lower()


def quote_spans(text: str) -> list[str]:
    out = []
    for rx in QUOTE_RX:
        out += [m.group(1) for m in rx.finditer(text or "")]
    out += [m.group(1) for m in BLOCK_QUOTE.finditer(text or "")]
    res = []
    for s in out:
        frags = re.split(r"\.\.\.|…|\[\.\.\.\]", s)
        fr = _norm(max(frags, key=len)).strip(" .,;:!?\"'-—–")
        if len(fr) >= 20 and len(fr.split()) >= 4:
            res.append(fr)
    return res


def explicit_refs(cfg: dict) -> pl.DataFrame:
    """child_uid, parent_uid, kind (name | quote), tier (1 | 2), reciprocal, n_targets, pt_date."""
    P, T = Path(cfg["paths"]["processed"]), Path(cfg["paths"]["tables"])
    agents = pl.read_parquet(P / "agents.parquet")
    eu = (pl.scan_parquet(P / "events_unified.parquet")
          .filter(pl.col("source").cast(pl.String) == "chat")
          .select("event_uid", "actor_id", pl.col("actor_type").cast(pl.String), "room_id", "ts_utc").collect())
    cm = pl.read_parquet(T / "chat_messages.parquet", columns=["id", "content"]).select(
        (pl.lit("chat:") + pl.col("id")).alias("event_uid"), pl.col("content").alias("text"))
    df = (eu.join(cm, on="event_uid", how="inner")
          .with_columns(pl.col("ts_utc").dt.convert_time_zone("America/Los_Angeles").dt.date().alias("pt_date"))
          .sort("room_id", "ts_utc", "event_uid"))
    uid, actor, atype = df["event_uid"].to_list(), df["actor_id"].to_list(), df["actor_type"].to_list()
    room, text, day = df["room_id"].to_list(), df["text"].to_list(), df["pt_date"].to_list()
    speaker = [a if t == "agent" else ("human" if t == "human" else "system") for a, t in zip(actor, atype)]
    norm = [_norm(x or "") for x in text]
    nm = NameMatcher(agents)
    N = len(uid)
    out = []

    def recent_agents(i: int, k: int) -> set[str]:
        s, j = set(), i - 1
        while j >= 0 and room[j] == room[i] and i - j <= k:
            if atype[j] == "agent":
                s.add(actor[j])
            j -= 1
        return s

    for i in range(N):
        if atype[i] != "agent":
            continue
        me = actor[i]
        refs = nm.refs(text[i] or "", recent_agents(i, FAMILY_WINDOW), me)
        core = {tgt for tgt, k in refs if tgt and tgt != me and (k & CORE_KINDS)}
        ext = {tgt for tgt, k in refs if tgt and tgt != me and "ext" in k}
        targets = core | ext
        parents = {}
        for tg in targets:
            j = i - 1
            while j >= 0 and room[j] == room[i] and i - j <= NAME_WINDOW:
                if atype[j] == "agent" and actor[j] == tg:
                    parents[tg] = j
                    break
                j -= 1
        if len(parents) == 1:
            tg, j = next(iter(parents.items()))
            back = nm.refs(text[j] or "", recent_agents(j, FAMILY_WINDOW), actor[j])
            recip = any(t == me for t, _ in back)
            tier = 1 if (recip and day[i] >= TIER1_FROM and tg in core) else 2
            out.append((uid[i], uid[j], "name", tier, recip, len(targets), day[i]))
        spans = quote_spans(text[i] or "")
        if spans and day[i] >= TIER1_FROM:
            hits = set()
            j = i - 1
            while j >= 0 and room[j] == room[i] and i - j <= QUOTE_WINDOW:
                if speaker[j] != speaker[i] and any(s in norm[j] for s in spans):
                    hits.add(j)
                j -= 1
            if len(hits) == 1:
                j = hits.pop()
                out.append((uid[i], uid[j], "quote", 1, False, 0, day[i]))
    return pl.DataFrame(out, schema={"child_uid": pl.String, "parent_uid": pl.String, "kind": pl.String,
                                     "tier": pl.Int8, "reciprocal": pl.Boolean, "n_targets": pl.Int16,
                                     "pt_date": pl.Date}, orient="row")
