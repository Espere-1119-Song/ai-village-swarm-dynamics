"""Why most GUI writes have no focus: diagnosis of the D2 GUI rules (follow-up to SPEC 8.3).

The D2 rules (`avsd.swarmsim.touches`, v1) tie a GUI write (typed text, ctrl+s or ctrl+Enter, a
click on a located write button, xdotool input) to the session's GUI focus, the last URL the
session navigated to. Most GUI writes have no focus. This module measures why, from text data
only (no screenshots, no external model):

- `walk_agent` replays every session of one agent turn by turn with the v1 focus logic and records
  each GUI write with its context: the action, the typed text's class (`classify_typed`), the key or
  the located element, what happened in the turns before it (address-bar keys, window switches,
  app launches, link clicks), the agent's own words around it (`narrative_flags` and the artifact
  refs of the provider response), the focus the agent's previous session ended with, and its
  position in the session.
- `breakdowns` splits the unattributed writes by action kind, month, computer-use regime, model
  family, text class and position.
- `evaluate` measures each focus heuristic: coverage on the unattributed writes, and accuracy on
  the writes whose v1 focus is known, with that focus hidden (the heuristic must name the same
  artifact key, or at least the same container).

Typed-text classes (checkable heuristics, first match wins): `credential` (a scrubbed or password
value), `url` (a URL or host, possibly local, that v1 missed), `shell` (a shell command line, as
typed into a terminal window), `code` (two or more code markers), `search` (a short query typed
after an address-bar key or into a located search box), `short_input` (one or two characters, or
a one-word game or menu command), `form_field` (a short single-line value), `prose` (a sentence or
longer text), `other`.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from typing import Any

import polars as pl

from avsd.swarmsim.touches import (
    CLICK_ACTIONS, CRED_BOX_RE, GUI_WRITE_KEYS, SEARCH_BOX_RE, WRITE_VERB_RE, AgentState, KeyMaps,
    SessionState, artifact_key, classify_typed, is_navigation, is_write_button, nav_ref, parse_bash,
    xdotool_inputs,
)

# --- the agent's own words ------------------------------------------------------------------------
KEYWORDS: dict[str, str] = {
    "terminal": r"\bterminal\b|\bxterm\b|\bkonsole\b|\bcommand line\b|\bshell\b|\bconsole\b",
    "doc": r"google doc|\bthe doc\b|\bdocument\b|google sheet|spreadsheet|\bsheet\b|google slides|\bslides\b",
    "mail": r"\bgmail\b|\bemail\b|\be-mail\b|\binbox\b|\bcompose\b",
    "chat": r"\bchat\b|\bdiscord\b|\bslack\b|\bmessage box\b|\bdirect message\b|\bdm\b",
    "social": r"\bforum\b|\bthread\b|\btweet\b|\btwitter\b|\breddit\b|\bsubstack\b|\bcomment\b|\breply\b",
    "search": r"\bsearch\b",
    "editor": r"\beditor\b|\bgedit\b|\bvs ?code\b|\bnotepad\b|\btext file\b|\bnano\b|\bvim\b|\blibreoffice\b",
    "form": r"\bform\b|\bfield\b|\binput box\b|\bsign ?up\b|\blog ?in\b|\bpassword\b|\bcheckout\b",
    "game": r"\bgame\b|\bchess\b|\bpuzzle\b|\bplayer\b|\blevel\b",
    "browser": r"\bbrowser\b|\bfirefox\b|\bchrome\b|\baddress bar\b|\burl bar\b|\bnew tab\b",
}
KW_BITS = {k: 1 << i for i, k in enumerate(KEYWORDS)}
_KW_RES = {k: re.compile(v, re.I) for k, v in KEYWORDS.items()}


def narrative_flags(text: str | None) -> int:
    """Bitmask of the KEYWORDS classes named in the agent's words."""
    if not text:
        return 0
    m = 0
    for k, rx in _KW_RES.items():
        if rx.search(text):
            m |= KW_BITS[k]
    return m


def flag_names(mask: int) -> list[str]:
    return [k for k, b in KW_BITS.items() if mask & b]


# --- located elements and keys ----------------------------------------------------------------------
LINK_RE = re.compile(r"(?i)\b(?:link|tab|bookmark|result|title|headline|article|post|thread|card|item|"
                     r"file|document|doc|sheet|email|message|conversation|inbox|notification|repo|"
                     r"repository|issue|pull request|merge request|channel|folder|row|entry|icon)\b")
TERMINAL_RE = re.compile(r"(?i)\bterminal\b|\bxterm\b|\bkonsole\b|\bconsole\b")
ADDR_KEYS = frozenset({"ctrl+l", "f6", "alt+d", "ctrl+k", "ctrl+e"})
SWITCH_KEYS = frozenset({"alt+tab", "super", "ctrl+alt+t", "alt+shift+tab", "ctrl+tab", "ctrl+shift+tab",
                         "ctrl+pagedown", "ctrl+pageup", "super_l", "alt+f2", "ctrl+t", "ctrl+n",
                         "ctrl+w", "ctrl+shift+n"})
APP_RE = {
    "browser": re.compile(r"\b(?:firefox|google-chrome|chromium(?:-browser)?|sensible-browser|x-www-browser)\b"),
    "editor": re.compile(r"\b(?:gedit|mousepad|kate|code|subl|xed|pluma|leafpad|libreoffice|soffice)\b"),
    "terminal": re.compile(r"\b(?:xterm|gnome-terminal|konsole|xfce4-terminal|lxterminal|terminator|tilix)\b"),
    "window": re.compile(r"\bxdotool\b[^\n]*\b(?:windowactivate|windowfocus|search|key\s+(?:alt|super))|\bwmctrl\b"),
}
_OPEN_RE = re.compile(r"\b(?:xdg-open|firefox|google-chrome|chromium|chromium-browser|sensible-browser|"
                      r"x-www-browser|xdotool)\b")
NARRATIVE_WINDOW = 3         # turns before the write (and the write itself) searched for named artifacts


def _artifact_refs(refs: Iterable[str] | None) -> list[str]:
    """Refs that can be a GUI focus (URLs, documents, repositories; not file paths)."""
    return [r for r in (refs or ()) if not r.startswith("path:")]


def walk_agent(agent: str, sessions: Sequence[Sequence[dict[str, Any]]]) -> list[dict[str, Any]]:
    """GUI writes of one agent's sessions (in start order) with their context.

    Each turn dict has `id`, `action`, `text`, `description`, `cmd`, `ts` (seconds), `msg` (refs in
    the provider response) and `kw` (narrative_flags of the provider response). The v1 focus logic
    is replayed exactly; nothing here changes the D2 outputs.
    """
    out: list[dict[str, Any]] = []
    carry_ref: str | None = None          # the focus the agent's previous session ended with
    carry_ts: float | None = None
    for turns in sessions:
        sess = SessionState()
        ag = AgentState()
        n = len(turns)
        first_nav = -1
        focus_turn = -1
        focus_src = ""
        last_desc = ""
        addr_at = sw_at = term_at = -99
        links_since_focus = 0
        apps: set[str] = set()
        narr: list[tuple[int, list[str], int]] = []      # (turn, artifact refs, kw mask)
        last_narr_ref: str | None = None
        last_narr_at = -1
        start_carry, start_carry_ts = carry_ref, carry_ts
        s_ts = turns[0]["ts"] if turns else None
        sess_recs: list[dict[str, Any]] = []
        navs = 0
        for i, t in enumerate(turns):
            a = t.get("action")
            refs = _artifact_refs(t.get("msg"))
            kw = int(t.get("kw") or 0)
            narr.append((i, refs, kw))
            if refs:
                last_narr_ref, last_narr_at = refs[-1], i
            if kw & KW_BITS["terminal"]:
                term_at = i
            rec = None
            if a == "bash" and t.get("cmd"):
                cmd = t["cmd"]
                for name, rx in APP_RE.items():
                    if rx.search(cmd):
                        apps.add(name)
                        if name == "window":
                            sw_at = i
                        if name == "terminal":
                            term_at = i
                if _OPEN_RE.search(cmd):
                    f0, w0, u0 = sess.focus, sess.gui_writes, sess.gui_writes_unattributed
                    parse_bash(cmd, sess, ag, [])
                    if sess.focus != f0:
                        focus_turn, focus_src, links_since_focus = i, "B-open", 0
                        first_nav = i if first_nav < 0 else first_nav
                        navs += 1
                    if sess.gui_writes > w0:
                        # one record per xdotool input, as D2 counts them (a command can hold several)
                        n_new, n_unattr = sess.gui_writes - w0, sess.gui_writes_unattributed - u0
                        rec = {"kind": "xdotool", "focus_v1": sess.focus if n_unattr == 0 else None,
                               "xdo": xdotool_inputs(cmd)[-n_new:]}
            elif a == "type":
                txt = t.get("text") or ""
                if is_navigation(txt):
                    r = nav_ref(txt)
                    if r:
                        sess.focus = r
                        focus_turn, focus_src, links_since_focus = i, "G-nav", 0
                        first_nav = i if first_nav < 0 else first_nav
                        navs += 1
                elif txt.strip():
                    rec = {"kind": "type", "focus_v1": sess.focus, "text": txt, "in_addr": (i - addr_at) <= 3}
                addr_at = -99 if txt.strip() and not is_navigation(txt) else addr_at
            elif a in ("key", "hold_key"):
                k = (t.get("text") or "").strip().lower().replace(" ", "")
                if k in GUI_WRITE_KEYS:
                    rec = {"kind": "key", "focus_v1": sess.focus, "key": k}
                elif k in ADDR_KEYS:
                    addr_at = i
                elif k in SWITCH_KEYS:
                    sw_at = i
                    if k == "ctrl+alt+t":
                        term_at = i
            elif a in CLICK_ACTIONS:
                addr_at = -99
                prev = turns[i - 1] if i > 0 else None
                located = prev is not None and prev.get("action") == "get_pixel_coords_of_element"
                pdesc = (prev.get("description") or "") if located else ""
                if pdesc and WRITE_VERB_RE.search(pdesc):
                    rec = {"kind": "click", "focus_v1": sess.focus, "desc": pdesc,
                           "button_v2": is_write_button(pdesc, strict=True)}
                elif pdesc and LINK_RE.search(pdesc):
                    links_since_focus += 1
                elif not pdesc:
                    links_since_focus += 0
            elif a == "get_pixel_coords_of_element":
                last_desc = t.get("description") or ""
                if TERMINAL_RE.search(last_desc):
                    term_at = i
            if rec is None:
                continue
            k_from = max(0, i - NARRATIVE_WINDOW)
            win = [x for x in narr if x[0] >= k_from]
            near_refs = [r for _, rs, _ in win for r in rs]
            near_after = [r for j, rs, _ in win if j > focus_turn for r in rs]
            near_kw = 0
            for _, _, m in win:
                near_kw |= m
            txt = rec.get("text")
            pdesc = last_desc if i > 0 and turns[i - 1].get("action") == "get_pixel_coords_of_element" else ""
            in_addr = bool(rec.pop("in_addr", False))
            nxt = turns[i + 1] if i + 1 < n else None
            nkey = (nxt.get("text") or "").strip().lower() if nxt and nxt.get("action") in ("key", "hold_key") else ""
            entered = nkey in ("return", "enter", "kp_enter") and \
                any(m & (KW_BITS["terminal"] | KW_BITS["game"]) for j, _, m in narr if j >= i - 10)
            cls = classify_typed(txt, addr_bar=in_addr, search_box=bool(SEARCH_BOX_RE.search(pdesc)),
                                 credential_box=bool(CRED_BOX_RE.search(pdesc)),
                                 entered_in_program=entered) if txt is not None else ""
            rec.update({
                "agent_id": agent, "session_id": t.get("session_id"), "turn_id": t.get("id"), "ts": t.get("ts"),
                "i": i, "n": n, "first_nav": first_nav, "focus_turn": focus_turn, "focus_src": focus_src,
                "text_class": cls, "text_len": len(txt) if txt is not None else 0,
                "n_lines": len([ln for ln in (txt or "").splitlines() if ln.strip()]),
                "addr_bar_recent": in_addr, "switch_recent": (i - sw_at) <= 10,
                "terminal_ctx": (i - term_at) <= 10, "links_since_focus": links_since_focus,
                "apps": ",".join(sorted(apps)), "next_key": nkey,
                "near_refs": near_refs, "near_refs_after_focus": near_after, "near_kw": near_kw,
                "narr_ref_session": last_narr_ref, "narr_ref_age": (i - last_narr_at) if last_narr_at >= 0 else -1,
                "carry_ref": start_carry,
                "carry_gap_min": ((s_ts - start_carry_ts) / 60.0) if (start_carry and s_ts is not None
                                                                     and start_carry_ts is not None) else math.nan,
            })
            rec.setdefault("text", None)
            rec.setdefault("key", None)
            rec.setdefault("desc", None)
            rec.setdefault("button_v2", None)
            xdo = rec.pop("xdo", None)
            for k in range(len(xdo) if xdo else 1):
                r2 = dict(rec)
                if xdo:
                    sub, xt = xdo[k]
                    r2["key"] = "xdotool " + sub
                    if sub == "type":
                        r2["text"], r2["text_len"] = xt, len(xt)
                        r2["text_class"] = classify_typed(xt)
                out.append(r2)
                sess_recs.append(r2)
        for r in sess_recs:
            r["session_navs"] = navs
        if sess.focus:
            carry_ref, carry_ts = sess.focus, turns[-1]["ts"]
    return out


# --- heuristics ------------------------------------------------------------------------------------------

def heuristic_predictions(w: dict[str, Any]) -> dict[str, str | None]:
    """Focus predicted by each heuristic for one GUI write (None: no prediction).

    Heuristics never look at the v1 focus or the navigation that set it.
    - carry: the focus the agent's previous session ended with.
    - carry_30m: the same when the previous session ended at most 30 minutes before this one started.
    - narr_near: the last URL or document the agent named in its own words in this turn or the
      NARRATIVE_WINDOW turns before.
    - narr_near_after_focus: the same, counting only turns after the navigation that set the v1
      focus (for unattributed writes there is none, so it equals narr_near). On known-focus writes
      this keeps the agent's words about the navigation itself out of the test.
    - narr_session: the last URL or document the agent named earlier in this session.
    """
    near = w.get("near_refs") or []
    after = w.get("near_refs_after_focus") or []
    gap = w.get("carry_gap_min")
    return {
        "carry": w.get("carry_ref"),
        "carry_30m": w.get("carry_ref") if (gap is not None and not math.isnan(gap) and gap <= 30) else None,
        "narr_near": near[-1] if near else None,
        "narr_near_after_focus": after[-1] if after else None,
        "narr_session": w.get("narr_ref_session"),
    }


def _key(ref: str | None, agent: str) -> tuple[str | None, str | None]:
    if not ref:
        return None, None
    k = artifact_key(ref, agent, KeyMaps())
    return (k[0], k[1]) if k else (None, None)


def evaluate(writes: list[dict[str, Any]]) -> pl.DataFrame:
    """Coverage on unattributed writes and accuracy on known-focus writes, per heuristic."""
    rows = []
    names = list(heuristic_predictions({}).keys())
    known = [w for w in writes if w.get("focus_v1")]
    unknown = [w for w in writes if not w.get("focus_v1")]
    for h in names:
        hit_k = hit_c = pred_k = 0
        for w in known:
            p = heuristic_predictions(w)[h]
            if not p:
                continue
            pred_k += 1
            pk, pc = _key(p, w["agent_id"])
            tk, tc = _key(w["focus_v1"], w["agent_id"])
            hit_k += int(pk is not None and pk == tk)
            hit_c += int(pc is not None and pc == tc)
        cov_u = sum(1 for w in unknown if heuristic_predictions(w)[h])
        rows.append({"heuristic": h, "known_writes": len(known), "known_predicted": pred_k,
                     "accuracy_key": hit_k / pred_k if pred_k else math.nan,
                     "accuracy_container": hit_c / pred_k if pred_k else math.nan,
                     "unattributed_writes": len(unknown), "unattributed_covered": cov_u,
                     "coverage": cov_u / len(unknown) if unknown else math.nan})
    return pl.DataFrame(rows)


# --- the run on the real data ------------------------------------------------------------------------------

def _flag_worker(args: tuple[str, int]) -> pl.DataFrame:
    """narrative_flags of every provider response in one row group (only non-zero masks kept)."""
    import pyarrow.parquet as pq

    from avsd.swarmsim.depgraph_data import narrative_text

    path, rg = args
    tb = pq.ParquetFile(path).read_row_group(rg, columns=["id", "agent_messages"])
    ids, msgs = tb.column("id").to_pylist(), tb.column("agent_messages").to_pylist()
    keep_i, keep_m = [], []
    for i, raw in zip(ids, msgs, strict=True):
        m = narrative_flags(narrative_text(raw)) if raw else 0
        if m:
            keep_i.append(i)
            keep_m.append(m)
    return pl.DataFrame({"id": keep_i, "kw": keep_m}, schema={"id": pl.String, "kw": pl.Int64})


def message_flags(cfg: dict, workers: int, force: bool = False, log=print) -> pl.DataFrame:
    """Keyword masks of all provider responses (cached under data/interim/depgraph/)."""
    from concurrent.futures import ProcessPoolExecutor
    from multiprocessing import get_context
    from pathlib import Path

    import pyarrow.parquet as pq

    out = Path(cfg["paths"]["interim"]) / "depgraph" / "message_flags.parquet"
    if out.exists() and not force:
        return pl.read_parquet(out)
    src = Path(cfg["paths"]["tables"]) / "computer_use_turns_text.parquet"
    n_rg = pq.ParquetFile(src).num_row_groups
    with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as ex:
        parts = list(ex.map(_flag_worker, [(str(src), rg) for rg in range(n_rg)], chunksize=1))
    df = pl.concat(parts)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out)
    log(f"message flags: {df.height:,} turns with a keyword")
    return df


def _walk_job(args: tuple[str, pl.DataFrame]) -> list[dict[str, Any]]:
    agent, df = args
    sessions = [g.to_dicts() for _, g in df.group_by(["session_id"], maintain_order=True)]
    return walk_agent(agent, sessions)


_CMD_KEEP = r"xdg-open|firefox|chrom|sensible-browser|x-www-browser|xdotool|wmctrl|gedit|mousepad|kate|\bcode\b|" \
            r"subl|xed|pluma|leafpad|libreoffice|soffice|xterm|gnome-terminal|konsole|terminal|tilix|terminator"


def load_gui_writes(cfg: dict, workers: int, log=print) -> pl.DataFrame:
    """Every GUI write with its context (private; written to data/interim/depgraph/gui_writes.parquet)."""
    from concurrent.futures import ProcessPoolExecutor
    from multiprocessing import get_context
    from pathlib import Path

    from avsd.swarmsim.depgraph_data import message_refs

    T = Path(cfg["paths"]["tables"])
    aa = pl.col("agent_action")
    cmd = aa.str.json_path_match("$.command")
    turns = (pl.scan_parquet(T / "computer_use_turns.parquet")
             .select("id", "session_id", pl.col("action_name").alias("action"),
                     (pl.col("created_at").dt.epoch("us") / 1e6).alias("ts"),
                     aa.str.json_path_match("$.text").alias("text"),
                     aa.str.json_path_match("$.description").alias("description"),
                     pl.when(cmd.str.contains(_CMD_KEEP)).then(cmd).alias("cmd"))
             .collect())
    msg = message_refs(cfg, workers, log=log)
    kw = message_flags(cfg, workers, log=log)
    ses = pl.read_parquet(T / "computer_use_sessions.parquet", columns=["id", "agent_id", "created_at"]) \
        .rename({"id": "session_id", "created_at": "s_start"})
    turns = (turns.join(msg, on="id", how="left").join(kw, on="id", how="left")
             .join(ses, on="session_id", how="inner")
             .sort("agent_id", "s_start", "session_id", "ts", "id"))
    jobs = [(a, g.drop("agent_id", "s_start")) for (a,), g in turns.group_by(["agent_id"], maintain_order=True)]
    jobs.sort(key=lambda j: -j[1].height)
    del turns
    recs: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as ex:
        for part in ex.map(_walk_job, jobs, chunksize=1):
            recs += part
    df = pl.DataFrame(recs, infer_schema_length=None)
    out = Path(cfg["paths"]["interim"]) / "depgraph" / "gui_writes.parquet"
    df.write_parquet(out)
    log(f"GUI writes: {df.height:,}, unattributed {df.filter(pl.col('focus_v1').is_null()).height:,}")
    return df


# --- aggregates ----------------------------------------------------------------------------------------------

def session_info(cfg: dict) -> pl.DataFrame:
    """Session attributes for the breakdowns: agent, regime, model, family, scaffold, bash use."""
    from pathlib import Path

    P, T = Path(cfg["paths"]["processed"]), Path(cfg["paths"]["tables"])
    ses = (pl.scan_parquet(P / "events_unified.parquet")
           .filter(pl.col("source").cast(pl.String) == "session")
           .select("session_id", pl.col("regime_cu").cast(pl.String), "model", "model_family", "scaffold")
           .collect())
    mix = (pl.scan_parquet(T / "computer_use_turns.parquet").select("session_id", "action_name")
           .group_by("session_id")
           .agg((pl.col("action_name") == "bash").sum().alias("n_bash"), pl.len().alias("n_turns"),
                (pl.col("action_name") == "get_pixel_coords_of_element").sum().alias("n_gpc"))
           .collect())
    return ses.join(mix, on="session_id", how="left")


def with_attributes(w: pl.DataFrame, info: pl.DataFrame) -> pl.DataFrame:
    """GUI writes with month, regime, family, model, bash use and position bins."""
    pt = pl.from_epoch(pl.col("ts"), time_unit="s").dt.replace_time_zone("UTC") \
        .dt.convert_time_zone("America/Los_Angeles")
    rel = pl.when(pl.col("n") > 1).then(pl.col("i") / (pl.col("n") - 1)).otherwise(0.0)
    return (w.join(info, on="session_id", how="left")
            .with_columns(pt.dt.strftime("%Y-%m").alias("month"),
                          pl.col("focus_v1").is_not_null().alias("attributed"),
                          (pl.col("n_bash").fill_null(0) > 0).alias("session_has_bash"),
                          (pl.col("n_gpc").fill_null(0) > 0).alias("session_locates"),
                          (pl.col("session_navs").fill_null(0) > 0).alias("session_navigates"),
                          (rel * 10).floor().clip(0, 9).cast(pl.Int64).alias("pos_decile"),
                          pl.when(pl.col("i") < 3).then(pl.lit("turns 0-2"))
                          .when(pl.col("i") < 10).then(pl.lit("turns 3-9"))
                          .when(pl.col("i") < 25).then(pl.lit("turns 10-24")).otherwise(pl.lit("turns 25+"))
                          .alias("pos_bin")))


def breakdown(w: pl.DataFrame, dims: Sequence[str]) -> pl.DataFrame:
    """Writes, unattributed writes and the unattributed share by the given dimensions."""
    tot_u = max(1, w.filter(~pl.col("attributed")).height)
    return (w.group_by(list(dims))
            .agg(pl.len().alias("gui_writes"), (~pl.col("attributed")).sum().alias("unattributed"))
            .with_columns((pl.col("unattributed") / pl.col("gui_writes")).alias("unattributed_rate"),
                          (pl.col("unattributed") / tot_u).alias("share_of_unattributed"))
            .sort(list(dims)))


EMAIL_LIST = r"^\s*[\w.+-]+@[\w-]+\.[\w.-]+(?:\s*[,;]\s*[\w.+-]+@[\w-]+\.[\w.-]+)*\s*$"


def target_class(w: pl.DataFrame) -> pl.DataFrame:
    """What each GUI write most likely is, from its text class, key or element and the agent's words.

    `not_document` targets are not writes to a persistent document: terminal commands, searches,
    navigation the v1 rule missed, sign-in values and short inputs (game moves, menu keys).
    """
    kwc = pl.col("near_kw").fill_null(0)
    bit = lambda k: (kwc & KW_BITS[k]) > 0  # noqa: E731
    tc = pl.col("text_class").fill_null("")
    target = (
        pl.when((pl.col("kind") == "click") & ~pl.col("button_v2").fill_null(False))
        .then(pl.lit("click on a box, link or menu"))
        .when(pl.col("kind") == "click").then(pl.lit("write button"))
        .when(tc == "shell").then(pl.lit("terminal command"))
        .when(tc == "search").then(pl.lit("search query"))
        .when(tc == "url").then(pl.lit("navigation missed"))
        .when(tc == "credential").then(pl.lit("sign-in value"))
        .when(tc == "short_input").then(pl.lit("short input"))
        .when(pl.col("kind").is_in(["type", "xdotool"]) & pl.col("terminal_ctx") & tc.is_in(["other", "form_field"]))
        .then(pl.lit("terminal or program input"))
        .when(tc == "code").then(pl.lit("code"))
        .when((tc == "prose") & (bit("mail") | bit("chat") | bit("social"))).then(pl.lit("message or post"))
        .when((tc == "form_field") & pl.col("text").fill_null("").str.contains(EMAIL_LIST))
        .then(pl.lit("message or post"))
        .when((tc == "prose") & (bit("doc") | bit("editor"))).then(pl.lit("document text"))
        .when(tc == "prose").then(pl.lit("prose, target unnamed"))
        .when(tc == "form_field").then(pl.lit("form field"))
        .when(pl.col("kind").is_in(["key", "xdotool"])).then(pl.lit("save or submit key"))
        .otherwise(pl.lit("other text"))
    )
    nd = ["terminal command", "terminal or program input", "search query", "navigation missed", "sign-in value",
          "short input", "click on a box, link or menu"]
    return w.with_columns(target.alias("target"), target.is_in(nd).alias("not_document"))


# --- signals, eras and validation ---------------------------------------------------------------------------

ACCOUNT_HOSTS_RE = re.compile(r"^https?://(?:mail|drive|docs|calendar|studio)\.google\.com|^https?://(?:www\.)?"
                              r"(?:github|gitlab)\.com/?$|^https?://(?:outlook|mail)\.")


def signal_table(w: pl.DataFrame) -> pl.DataFrame:
    """Share of unattributed (and attributed) GUI writes that show each focus signal the v1 rules miss."""
    kwc = pl.col("near_kw").fill_null(0)
    sig = {
        "address-bar key in the 3 turns before (ctrl+l, F6, alt+d)": pl.col("addr_bar_recent"),
        "typed text is a URL or host that v1 misses (local host, URL plus a word)": pl.col("text_class") == "url",
        "located link, tab, bookmark, result or item clicked earlier in the session": pl.col("links_since_focus") > 0,
        "focus carried from the previous session is a Drive, Gmail, Docs or forge home page":
            pl.col("carry_ref").fill_null("").str.contains(ACCOUNT_HOSTS_RE.pattern),
        "window switch or new-window key in the 10 turns before": pl.col("switch_recent"),
        "app launched from bash earlier in the session": pl.col("apps").fill_null("") != "",
        "terminal named, opened or clicked in the 10 turns before": pl.col("terminal_ctx"),
        "agent named a URL or document in this turn or the 3 before": pl.col("near_refs").list.len() > 0,
        "agent named a document, mail, chat, post, editor or terminal in its words":
            (kwc & (KW_BITS["doc"] | KW_BITS["mail"] | KW_BITS["chat"] | KW_BITS["social"] | KW_BITS["editor"]
                    | KW_BITS["terminal"])) > 0,
        "previous session of the agent ended with a focus": pl.col("carry_ref").is_not_null(),
        "previous session ended at most 30 minutes before": pl.col("carry_gap_min") <= 30,
    }
    rows = []
    for label, expr in sig.items():
        for scope, df in (("unattributed", w.filter(~pl.col("attributed"))),
                          ("attributed", w.filter(pl.col("attributed")))):
            hit = df.select(expr.fill_null(False).sum()).item()
            rows.append({"signal": label, "writes": scope, "n": df.height, "with_signal": int(hit),
                         "share": hit / df.height if df.height else math.nan})
    return pl.DataFrame(rows)


def carry_accuracy_by_gap(writes: list[dict[str, Any]]) -> pl.DataFrame:
    """Carry-over accuracy on known-focus writes by the gap since the previous session ended."""
    bins = ((0, 5), (5, 30), (30, 120), (120, 24 * 60), (24 * 60, math.inf))
    rows = []
    for lo, hi in bins:
        sel = [w for w in writes if w.get("focus_v1") and w.get("carry_ref")
               and lo <= (w.get("carry_gap_min") if w.get("carry_gap_min") == w.get("carry_gap_min") else -1) < hi]
        hit_k = hit_c = 0
        for w in sel:
            pk, pc = _key(w["carry_ref"], w["agent_id"])
            tk, tc = _key(w["focus_v1"], w["agent_id"])
            hit_k += int(pk is not None and pk == tk)
            hit_c += int(pc is not None and pc == tc)
        unk = sum(1 for w in writes if not w.get("focus_v1") and w.get("carry_ref")
                  and lo <= (w.get("carry_gap_min") if w.get("carry_gap_min") == w.get("carry_gap_min") else -1) < hi)
        rows.append({"gap_min_from": lo, "gap_min_to": hi if math.isfinite(hi) else None, "known_writes": len(sel),
                     "accuracy_key": hit_k / len(sel) if sel else math.nan,
                     "accuracy_container": hit_c / len(sel) if sel else math.nan, "unattributed_writes": unk})
    return pl.DataFrame(rows)


def era_table(cfg: dict) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Per month: sessions, bash use, GUI action shares; first and last date of each action name."""
    from pathlib import Path

    T = Path(cfg["paths"]["tables"])
    gui = ["left_click", "double_click", "triple_click", "right_click", "middle_click", "type", "key", "hold_key",
           "scroll", "screenshot", "mouse_move", "left_click_drag", "get_pixel_coords_of_element"]
    t = (pl.scan_parquet(T / "computer_use_turns.parquet")
         .select("session_id", "action_name", "action_keys", "created_at")
         .with_columns(pl.col("created_at").dt.convert_time_zone("America/Los_Angeles").dt.strftime("%Y-%m")
                       .alias("month"))
         .collect())
    s = t.group_by("session_id").agg(pl.col("month").first(), (pl.col("action_name") == "bash").any().alias("bash"),
                                     pl.col("action_name").is_in(gui).any().alias("gui"))
    months = (t.group_by("month").agg(
        pl.len().alias("turns"),
        (pl.col("action_name") == "bash").mean().alias("bash_turn_share"),
        pl.col("action_name").is_in(gui).mean().alias("gui_turn_share"),
        (pl.col("action_name") == "type").mean().alias("type_turn_share"),
        (pl.col("action_name") == "get_pixel_coords_of_element").mean().alias("locate_turn_share"),
        (pl.col("action_keys").fill_null("").str.contains("scrollDirection")).mean().alias("seven_key_share"))
        .join(s.group_by("month").agg(pl.len().alias("sessions"), pl.col("bash").mean().alias("sessions_with_bash"),
                                      pl.col("gui").mean().alias("sessions_with_gui")), on="month")
        .sort("month"))
    first = (t.group_by("action_name").agg(pl.col("created_at").min().dt.date().alias("first"),
                                           pl.col("created_at").max().dt.date().alias("last"), pl.len().alias("turns"))
             .sort("first"))
    return months, first


# --- the run --------------------------------------------------------------------------------------------------

def run_gui_gap(cfg: dict, workers: int, log=print) -> dict[str, Any]:
    """Diagnose the GUI focus gap; write outputs/qa/swarmsim_gui_gap.md and depgraph_gui_gap*.csv."""
    from pathlib import Path

    from avsd.swarmsim.gui_gap_report import write_gap_report

    w0 = load_gui_writes(cfg, workers, log=log)
    info = session_info(cfg)
    w = target_class(with_attributes(w0, info))
    recs = w0.to_dicts()
    tables = {
        "kind": breakdown(w, ["kind"]),
        "month": breakdown(w, ["month"]),
        "regime": breakdown(w, ["regime_cu"]),
        "family": breakdown(w, ["model_family"]),
        "model": breakdown(w, ["model_family", "model"]),
        "scaffold": breakdown(w, ["scaffold"]),
        "bash": breakdown(w, ["session_has_bash"]),
        "locate": breakdown(w, ["session_locates"]),
        "regime_bash": breakdown(w, ["regime_cu", "session_has_bash"]),
        "navigates": breakdown(w, ["session_navigates"]),
        "position": breakdown(w, ["pos_bin"]),
        "text_class": breakdown(w.filter(pl.col("kind") == "type"), ["text_class"]),
        "target": breakdown(w, ["target", "not_document"]),
        "family_target": breakdown(w, ["model_family", "not_document"]),
        "month_target": breakdown(w, ["month", "not_document"]),
    }
    signals = signal_table(w)
    heur = evaluate(recs)
    gap = carry_accuracy_by_gap(recs)
    months, first = era_table(cfg)
    out = Path(cfg["paths"]["outputs"])
    long = pl.concat([
        df.with_columns(pl.lit(name).alias("table"),
                        pl.concat_str([pl.col(c).cast(pl.String) for c in df.columns
                                       if c not in ("gui_writes", "unattributed", "unattributed_rate",
                                                    "share_of_unattributed")], separator=" | ").alias("group"))
        .select("table", "group", "gui_writes", "unattributed", "unattributed_rate", "share_of_unattributed")
        for name, df in tables.items()])
    files = {"breakdowns": out / "tables" / "depgraph_gui_gap.csv",
             "heuristics": out / "tables" / "depgraph_gui_heuristics.csv",
             "eras": out / "tables" / "depgraph_gui_eras.csv",
             "qa": out / "qa" / "swarmsim_gui_gap.md"}
    long.write_csv(files["breakdowns"], float_precision=4)
    pl.concat([heur.with_columns(pl.lit("all").alias("gap")),
               ], how="diagonal").write_csv(files["heuristics"], float_precision=4)
    months.write_csv(files["eras"], float_precision=4)
    write_gap_report(files["qa"], cfg, w, tables, signals, heur, gap, months, first)
    log(f"GUI gap report: {files['qa']}")
    return {"files": {k: str(v) for k, v in files.items()}, "tables": tables, "signals": signals,
            "heuristics": heur, "gap": gap, "months": months}
