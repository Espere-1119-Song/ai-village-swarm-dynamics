"""Locations of sign-in values typed into GUI fields (SPEC 0.2: record unredacted credentials and tell the owner).

    python scripts/depgraph_gui_signin.py

Never writes or prints a typed value. Writes data/interim/credential_scan/gui_signin_values.csv (mode 600)
with one row per typed value: turn id, session id, Pacific date, agent, the kind of field (from the
located-element description just before the typing: password, username/email, code; or a password inferred
from the login order: a username or email typed, then Tab, then this value), whether the value looks like a
password, whether it is already scrubbed, whether the context is a training app, how it was typed and its
length. Prints counts only, including the overlap with the credential report
data/interim/credential_scan/locations.csv (written by scripts/scan_credentials.py and sent to AI Digest on
2026-10-01): by location (the same turn is in the report) and by value (the same value is one of the report's
values; values are compared in memory through hashes with a random salt that is never saved).

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import re
from pathlib import Path

import polars as pl

from avsd.config import load_config
from avsd.swarmsim.touches import xdotool_inputs

PASSWORD_RE = re.compile(r"(?i)\bpass(?:word|code|phrase)?s?\b|\bpwd\b|\bpin\b")
CODE_RE = re.compile(r"(?i)\b(?:verification|security|confirmation|authentication|auth|login|access|one[- ]time|"
                     r"sms|6[- ]digit|backup|recovery)\b[^.]{0,30}\bcodes?\b|\b(?:2fa|otp|mfa|totp)\b")
USER_RE = re.compile(r"(?i)\buser ?names?\b|\blog ?in\b|\bsign ?in\b|\be-?mail\b|\bemail address\b|"
                     r"\baccount name\b|\buser ?id\b|\bhandle\b|\bphone\b")
EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")
SCRUB_RE = re.compile(r"\[REDACTED\]|\[BLOB_REMOVED\]")
TRAINING_RE = re.compile(r"(?i)localhost|127\.0\.0\.1|0\.0\.0\.0|juice|owasp|dvwa|webgoat|hackthebox|tryhackme")
SALT = os.urandom(16)            # in memory only


def field_kind(desc: str) -> str | None:
    if PASSWORD_RE.search(desc):
        return "password"
    if CODE_RE.search(desc):
        return "code"
    if USER_RE.search(desc):
        return "username/email"
    return None


def _classes(v: str) -> int:
    return sum((any(c.islower() for c in v), any(c.isupper() for c in v), any(c.isdigit() for c in v),
                any(not c.isalnum() for c in v)))


def looks_like_password(v: str) -> bool:
    """No spaces, not an email, URL or plain number, 6 to 64 characters, and at least the scanner's
    medium strength (8+ characters of two classes, or 12+ of two, or 8+ of three)."""
    v = v.strip()
    if not v or any(c.isspace() for c in v) or SCRUB_RE.search(v) or EMAIL_RE.match(v) or v.isdigit():
        return False
    if v.lower().startswith(("http://", "https://", "www.")) or not 6 <= len(v) <= 64:
        return False
    return len(v) >= 8 and _classes(v) >= 2


def _h(v: str) -> str:
    return hashlib.sha256(SALT + v.strip().encode()).hexdigest()


def typed_values(cfg: dict) -> tuple[pl.DataFrame, set[str], dict[str, str]]:
    """Rows (no values) plus, in memory only, the hash of each password-like value by turn."""
    T, P = Path(cfg["paths"]["tables"]), Path(cfg["paths"]["processed"])
    aa = pl.col("agent_action")
    turns = (pl.scan_parquet(T / "computer_use_turns.parquet")
             .select("id", "session_id", "action_name", "created_at",
                     aa.str.json_path_match("$.text").alias("text"),
                     aa.str.json_path_match("$.description").alias("description"),
                     pl.when(aa.str.contains("xdotool")).then(aa.str.json_path_match("$.command")).alias("cmd"))
             .filter(pl.col("action_name").is_in(["type", "key", "get_pixel_coords_of_element", "left_click",
                                                   "double_click", "triple_click", "bash"]))
             .collect())
    ses = pl.read_parquet(T / "computer_use_sessions.parquet", columns=["id", "agent_id", "created_at"]) \
        .rename({"id": "session_id", "created_at": "s_start"})
    agents = pl.read_parquet(T / "agents.parquet", columns=["id", "name"]).rename({"id": "agent_id", "name": "agent"})
    goal = (pl.scan_parquet(P / "events_unified.parquet").filter(pl.col("source").cast(pl.String) == "session")
            .select("session_id", "goal_id").collect())
    turns = (turns.join(ses, on="session_id").join(agents, on="agent_id", how="left")
             .sort("agent_id", "s_start", "session_id", "created_at", "id"))
    rows, hashes = [], {}
    for (sid,), g in turns.group_by(["session_id"], maintain_order=True):
        recs = g.to_dicts()
        last_nav = ""
        recent: list[tuple[int, str, str]] = []       # (index, action, info) of the last turns
        for i, t in enumerate(recs):
            a = t["action_name"]
            if a == "type":
                v = t["text"] or ""
                if re.match(r"(?i)^\s*(?:https?://|www\.|localhost|127\.0\.0\.1)\S*\s*$", v):
                    last_nav = v.strip()
                    recent.append((i, "nav", ""))
                    continue
                descs = [info for j, act, info in recent if act == "gpc" and j >= i - 3]
                kind = field_kind(descs[-1]) if descs else None
                if kind is None:
                    # login order: a username or email typed, then Tab, then this value
                    tab = any(act == "key" and info in ("tab", "\t") for j, act, info in recent if j >= i - 2)
                    user = any(act == "typed_user" for j, act, info in recent if j >= i - 4)
                    if tab and user and looks_like_password(v):
                        kind = "password (inferred from login order)"
                scrubbed = bool(SCRUB_RE.search(v))
                if kind is None and scrubbed:
                    kind = "unknown (scrubbed value)"
                if kind is not None:
                    ctx = " ".join([last_nav] + descs)
                    pw = looks_like_password(v)
                    rows.append({"turn_id": t["id"], "session_id": sid, "created_at": t["created_at"],
                                 "agent": t["agent"], "field_kind": kind, "looks_like_password": pw,
                                 "scrubbed": scrubbed, "training_context": bool(TRAINING_RE.search(ctx)),
                                 "typed_via": "type action", "val_len": len(v.strip())})
                    if pw:
                        hashes[t["id"]] = _h(v)
                if kind == "username/email" or EMAIL_RE.match(v.strip()):
                    recent.append((i, "typed_user", ""))
                else:
                    recent.append((i, "type", ""))
            elif a == "key":
                recent.append((i, "key", (t["text"] or "").strip().lower()))
            elif a == "get_pixel_coords_of_element":
                recent.append((i, "gpc", t["description"] or ""))
            elif a == "bash" and t["cmd"]:
                for sub, v in xdotool_inputs(t["cmd"]):
                    if sub != "type" or not v.strip():
                        continue
                    kind = field_kind(t["cmd"].replace(v, " ")) if v else None
                    if kind is None:
                        continue
                    pw = looks_like_password(v)
                    rows.append({"turn_id": t["id"], "session_id": sid, "created_at": t["created_at"],
                                 "agent": t["agent"], "field_kind": kind, "looks_like_password": pw,
                                 "scrubbed": bool(SCRUB_RE.search(v)), "training_context": bool(TRAINING_RE.search(
                                     last_nav + " " + t["cmd"].replace(v, " "))),
                                 "typed_via": "xdotool type", "val_len": len(v.strip())})
                    if pw:
                        hashes[t["id"]] = _h(v)
            else:
                recent.append((i, a, ""))
            recent = recent[-8:]
    df = pl.DataFrame(rows, infer_schema_length=None)
    df = (df.join(goal, on="session_id", how="left")
          .with_columns(pl.col("created_at").dt.convert_time_zone("America/Los_Angeles").dt.date().alias("pt_date")))
    return df, set(hashes.values()), hashes


def reported_value_hashes(cfg: dict) -> set[str]:
    """Hashes (in memory) of the values behind every row of the earlier credential report."""
    root = Path(cfg["paths"]["interim"]).parent.parent
    spec = importlib.util.spec_from_file_location("scan_credentials", root / "scripts" / "scan_credentials.py")
    sc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sc)
    rep = pl.read_csv(Path(cfg["paths"]["interim"]) / "credential_scan" / "locations.csv",
                      schema_overrides={"row_id": pl.String})
    out: set[str] = set()
    for table, fname, cols, raw_file, fields in sc.SOURCES:
        rev = {v: k for k, v in fields.items()}
        sel = rep.filter(pl.col("raw_file") == raw_file)
        if sel.is_empty():
            continue
        want = {}
        for r in sel.iter_rows(named=True):
            col = rev.get(r["raw_field"])
            if col in cols:
                want.setdefault((r["row_id"], col), set()).add((r["kind"], int(r["val_len"])))
        ids = list({k[0] for k in want})
        if not ids:
            continue
        df = (pl.scan_parquet(Path(cfg["paths"]["tables"]) / fname).select("id", *cols)
              .filter(pl.col("id").is_in(ids)).collect())
        for r in df.iter_rows(named=True):
            for col in cols:
                need = want.get((r["id"], col))
                text = r.get(col)
                if not need or not text:
                    continue
                for m in _matches(sc, text):
                    if (m[0], len(m[1])) in need:
                        out.add(_h(m[1]))
    return out


def _matches(sc, text: str) -> list[tuple[str, str]]:
    """(kind, value) of the scanner's hits in a text, using the scanner's own patterns (in memory)."""
    res = []
    for kind, rx in sc.TOKEN_RES.items():
        for m in rx.finditer(text):
            res.append((kind, m.group("val")))
    for m in [*sc.ASSIGN.finditer(text), *sc.ASSIGN_IS.finditer(text)]:
        res.append(("assignment", m.group("val").rstrip(".:!?")))
    for m in sc.URLCRED.finditer(text):
        res.append(("url_userinfo", m.group("val")))
    for m in sc.BEARER.finditer(text):
        res.append(("bearer_token", m.group("val")))
    return res


def main() -> None:
    cfg = load_config()
    df, pw_hashes, by_turn = typed_values(cfg)
    out = Path(cfg["paths"]["interim"]) / "credential_scan" / "gui_signin_values.csv"
    (df.select("turn_id", "session_id", "pt_date", "agent", "field_kind", "looks_like_password", "scrubbed",
               "training_context", "typed_via", "val_len")
     .sort("pt_date", "session_id", "turn_id").write_csv(out))
    os.chmod(out, 0o600)
    rep = pl.read_csv(Path(cfg["paths"]["interim"]) / "credential_scan" / "locations.csv",
                      schema_overrides={"row_id": pl.String})
    rep_turns = set(rep.filter(pl.col("raw_file") == "computer_use_turns.jsonl.gz")["row_id"].to_list())
    rep_vals = reported_value_hashes(cfg)
    pw = df.filter(pl.col("looks_like_password"))
    pw = pw.with_columns(pl.col("turn_id").is_in(list(rep_turns)).alias("in_report_location"),
                         pl.col("turn_id").map_elements(lambda t: by_turn.get(t) in rep_vals,
                                                        return_dtype=pl.Boolean).alias("in_report_value"))
    new = pw.filter(~pl.col("in_report_location") & ~pl.col("in_report_value"))
    distinct = len(pw_hashes)
    distinct_new = len({by_turn[t] for t in new["turn_id"].to_list()})
    print(f"rows written: {df.height} ({out}, mode 600)")
    print("rows by field kind:", dict(df.group_by("field_kind").len().iter_rows()))
    print("rows by typing:", dict(df.group_by("typed_via").len().iter_rows()))
    print(f"scrubbed values: {int(df['scrubbed'].sum())}; password-like values: {pw.height} rows, {distinct} distinct; "
          f"in training contexts: {int(pw['training_context'].sum())} rows")
    print("password-like rows by field kind:", dict(pw.group_by("field_kind").len().iter_rows()))
    print(f"password-like rows at a turn listed in the report: {int(pw['in_report_location'].sum())}; whose value is "
          f"one of the report's values: {int(pw['in_report_value'].sum())}")
    print(f"new (neither): {new.height} rows, {distinct_new} distinct values, {new['session_id'].n_unique()} sessions, "
          f"{new['agent'].n_unique()} agents, PT dates {new['pt_date'].min()} to {new['pt_date'].max()}; "
          f"of these in training contexts: {int(new['training_context'].sum())} rows")
    print("new rows by field kind:", dict(new.group_by("field_kind").len().iter_rows()))
    for label, sel in (("password field or login order", pl.col("field_kind").str.starts_with("password")),
                       ("username/email field", pl.col("field_kind") == "username/email")):
        a, b = pw.filter(sel), new.filter(sel)
        print(f"{label}: password-like {a.height} rows / {len({by_turn[t] for t in a['turn_id'].to_list()})} distinct; "
              f"new {b.height} rows / {len({by_turn[t] for t in b['turn_id'].to_list()})} distinct, "
              f"{b['session_id'].n_unique()} sessions, {b['agent'].n_unique()} agents, "
              f"training {int(b['training_context'].sum())}")
    print(f"report rows from computer-use turns: {len(rep_turns)}; report values re-found: {len(rep_vals)}")


if __name__ == "__main__":
    main()
