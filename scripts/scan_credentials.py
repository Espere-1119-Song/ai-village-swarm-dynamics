"""Locate credentials that survived the publisher's redaction (SPEC 0.2).

Never stores or prints a secret value. Each hit keeps the table, column, row
id, credential kind, value length, character classes and a salted fingerprint.
The salt is random per run and never saved, so fingerprints only count
distinct values within one run.

Writes data/interim/credential_scan/{hits.parquet, locations.csv, summary.md}.
Run as a Slurm job:
    srun -A gu-account -p batch -c 16 --mem=120G -t 120 \
        bash -c "source scripts/env.sh && python scripts/scan_credentials.py"

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import hashlib
import os
import random
import re
import time
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq

ROOT = Path(os.environ.get("AVSD", Path.home() / "ai-village-swarm-dynamics"))
TABLES = ROOT / "data/processed/tables"
OUT = ROOT / "data/interim/credential_scan"
SALT = os.urandom(16)

# (table, parquet file, columns, original file, original field per column)
SOURCES = [
    ("agent_memories", "agent_memories_text.parquet", ["content"],
     "agent_memories.jsonl.gz", {"content": "content"}),
    ("events", "events_text.parquet",
     ["content", "query", "answer", "session_goal", "summary", "next_session_goal", "output", "data_json"],
     "events.jsonl.gz",
     {"content": "data.content", "query": "data.query", "answer": "data.answerToQuery",
      "session_goal": "data.sessionGoal", "summary": "data.summary",
      "next_session_goal": "data.nextSessionGoal", "output": "data.output", "data_json": "data (other keys)"}),
    ("computer_use_turns", "computer_use_turns.parquet", ["agent_action"],
     "computer_use_turns.jsonl.gz", {"agent_action": "agent_action"}),
    ("computer_use_turns", "computer_use_turns_text.parquet", ["output", "error", "agent_messages"],
     "computer_use_turns.jsonl.gz", {"output": "output", "error": "error", "agent_messages": "agent_messages"}),
    ("chat_messages", "chat_messages.parquet", ["content"], "chat_messages.jsonl.gz", {"content": "content"}),
    ("computer_use_sessions", "computer_use_sessions.parquet", ["session_goal"],
     "computer_use_sessions.jsonl.gz", {"session_goal": "session_goal"}),
    ("summaries", "summaries.parquet", ["content"], "summaries.jsonl.gz", {"content": "content"}),
    ("claude_code_messages", "claude_code_messages_text.parquet", ["content"],
     "claude_code_messages.jsonl.gz", {"content": "content"}),
]

_B = r"(?<![A-Za-z0-9_-])"
TOKEN_PATTERNS = {
    "anthropic_api_key": _B + r"(?P<val>sk-ant-[A-Za-z0-9_-]{32,})",
    "openai_api_key": _B + r"(?P<val>sk-(?!ant-)(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{32,})",
    "github_token": _B + r"(?P<val>gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})",
    "gitlab_token": _B + r"(?P<val>gl(?:pat|dt|rt|cbt|ptt|ft|imt|agent)-[A-Za-z0-9_-]{20,})",
    "aws_access_key_id": _B + r"(?P<val>(?:AKIA|ASIA)[0-9A-Z]{16})(?![0-9A-Z])",
    "google_api_key": _B + r"(?P<val>AIza[0-9A-Za-z_-]{35})",
    "slack_token": _B + r"(?P<val>xox[abposr]-[A-Za-z0-9-]{10,})",
    "huggingface_token": _B + r"(?P<val>hf_[A-Za-z0-9]{30,})",
    "npm_token": _B + r"(?P<val>npm_[A-Za-z0-9]{36})",
    "netlify_token": _B + r"(?P<val>nfp_[A-Za-z0-9]{30,})(?![A-Za-z0-9_-])",
    "stripe_live_key": _B + r"(?P<val>(?:sk|rk)_live_[A-Za-z0-9]{20,})",
    "sendgrid_key": _B + r"(?P<val>SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,})",
    "telegram_bot_token": _B + r"(?P<val>\d{8,10}:AA[A-Za-z0-9_-]{33})",
    "jwt": _B + r"(?P<val>eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})",
    "cloudflare_api_token": r"(?i)cloudflare_api_token[\"'`]?\s*[=:]\s*[\"'`]?(?P<val>[A-Za-z0-9_-]{30,})",
    "private_key": r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----(?P<val>[\s\S]{0,120})",
}
TOKEN_RES = {k: re.compile(v) for k, v in TOKEN_PATTERNS.items()}

_KEYS = (
    r"app[ _-]?passwords?|passwords?|passwd|passphrase|pwd|secret[ _-]?key|client[ _-]?secret|secret"
    r"|api[ _-]?key|apikey|access[ _-]?token|auth[ _-]?token|refresh[ _-]?token|bearer[ _-]?token|token"
    r"|private[ _-]?key|security[ _-]?answer|recovery[ _-]?codes?"
)
_Q = r"[\\\"'`*]*"  # closing quotes, escaped JSON quotes, markdown bold
_VAL = r"[^\s\"'`,;()\[\]{}<>\\|]"
ASSIGN = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?P<key>" + _KEYS + r")(?![A-Za-z0-9_])" + _Q + r"\s*(?:=|:|=>|->)\s*" + _Q
    + r"(?P<val>" + _VAL + r"{4,128})"
)
# "my password is X" phrasing, for password keys only ("token is expired" is prose).
ASSIGN_IS = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?P<key>(?:app[ _-]?)?passwords?|passwd|passphrase|pwd)(?![A-Za-z0-9_])" + _Q
    + r"\s+is\s+" + _Q + r"(?P<val>" + _VAL + r"{4,128})"
)
URLCRED = re.compile(
    r"(?i)\b[a-z][a-z0-9+.-]{1,15}://(?P<user>[^\s:/@\"'`\\]{1,64}):(?P<val>[^\s@/\"'`\\]{4,128})@(?P<host>[A-Za-z0-9.-]+)"
)
BEARER = re.compile(r"(?i)\bbearer\s+(?P<val>[A-Za-z0-9._~+/-]{20,}=*)")

# Rust-regex prefilter (no lookbehind): a superset of the Python patterns, so
# the slow Python pass only sees candidate cells.
PREFILTER = "|".join([
    r"sk-[A-Za-z0-9_-]{32,}",
    r"gh[pousr]_[A-Za-z0-9]{36,}",
    r"github_pat_[A-Za-z0-9_]{50,}",
    r"gl(?:pat|dt|rt|cbt|ptt|ft|imt|agent)-[A-Za-z0-9_-]{20,}",
    r"(?:AKIA|ASIA)[0-9A-Z]{16}",
    r"AIza[0-9A-Za-z_-]{35}",
    r"xox[abposr]-[A-Za-z0-9-]{10,}",
    r"hf_[A-Za-z0-9]{30,}",
    r"npm_[A-Za-z0-9]{36}",
    r"nfp_[A-Za-z0-9]{30,}",
    r"(?:sk|rk)_live_[A-Za-z0-9]{20,}",
    r"SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}",
    r"\d{8,10}:AA[A-Za-z0-9_-]{33}",
    r"eyJ[A-Za-z0-9_-]{10,}\.eyJ",
    r"(?i:cloudflare_api_token)",
    r"PRIVATE KEY",
    r"://[^\s:/@]+:[^\s@/]{4,}@",
    r"(?i:bearer)\s+[A-Za-z0-9._~+/-]{20,}",
    r"(?i:" + _KEYS + r")" + _Q + r"\s*(?:=|:|=>|->)\s*" + _Q + _VAL + r"{6,}",
    r"(?i:passwords?|passwd|passphrase|pwd)" + _Q + r"\s+is\s+" + _Q + _VAL + r"{6,}",
])

STOP = {
    "required", "provided", "unknown", "none", "null", "hidden", "stored", "saved", "needed", "sent",
    "incorrect", "correct", "changed", "reset", "updated", "protected", "encrypted", "masked", "redacted",
    "available", "missing", "same", "true", "false", "undefined", "empty", "invalid", "valid", "expired",
    "removed", "n/a", "tbd", "todo", "pending", "generated", "configured", "included", "shown", "below",
    "above", "here", "there", "field", "input", "prompt", "login", "manager", "vault", "keychain",
    "environment", "variable", "variables", "file", "string", "optional", "default", "not", "set",
    "unset", "known", "the", "a", "an", "in", "on", "for", "being", "still", "also", "now", "already",
}
BAD_SUB = (
    "redacted", "xxxx", "****", "....", "your", "example", "placeholder", "dummy", "changeme", "${", "$(",
    "process.env", "environ", "getenv", "getpass", "secrets.", "input(", "...", "password", "passwd",
    "token", "secret", "apikey", "api_key", "hash", "cred", "auth",
)
BAD_START = ("$", "%", "{{", "http", "/", "~/", "./", "@", "#", "&", "=", "-", "+")

SERVICES = (
    "gmail", "google", "github", "gitlab", "cloudflare", "openai", "anthropic", "twitter", "x.com", "reddit",
    "substack", "discord", "slack", "bluesky", "bsky", "linkedin", "facebook", "instagram", "mastodon",
    "medium", "wordpress", "hacker news", "devpost", "juice shop", "juice-sh.op", "dvwa", "webgoat",
    "hackthebox", "tryhackme", "protonmail", "proton", "outlook", "hotmail", "yahoo", "paypal", "stripe",
    "venmo", "gofundme", "every.org", "eventbrite", "luma", "meetup", "notion", "airtable", "vercel",
    "netlify", "render", "heroku", "supabase", "firebase", "mailchimp", "sendgrid", "twilio", "tinker",
    "huggingface", "hugging face", "kaggle", "lesswrong", "youtube", "tiktok", "patreon", "ko-fi",
    "shopify", "etsy", "printful", "gumroad", "itch.io", "steam", "zoom", "calendly", "typeform",
    "docusign", "ngrok", "replit", "glitch", "pythonanywhere", "digitalocean", "aws", "azure", "dropbox",
    "wikipedia", "wikimedia", "quora", "telegram", "whatsapp", "signal", "spotify", "soundcloud",
    "bandcamp", "canva", "figma", "trello", "asana", "jira", "zapier", "ifttt", "buttondown", "ghost",
    "beehiiv", "convertkit", "mailgun", "postmark", "zoho", "fastmail", "tutanota", "mail.tm", "temp-mail",
)
_SERVICE_RE = re.compile("(?i)" + "|".join(re.escape(s) for s in SERVICES))
# Deliberately vulnerable training apps (OWASP Juice Shop etc.), published example keys, fake test data.
_TRAINING_RE = re.compile(
    r"(?i)localhost|127\.0\.0\.1|0\.0\.0\.0|juice|dvwa|webgoat|owasp|ctf\b|vulnerable|morty|bjoern|bender"
    r"|\bunion\b|sql ?injection|payload|challenge|/rest/|web3|hardhat|example default|\bfake|dummy|\bmock"
)
_PEM_BODY = re.compile(r"^(?:\s|\\[rn])*(?P<b64>[A-Za-z0-9+/=]{40,})")


def _real_pem(body: str) -> bool:
    """A PEM body that starts with a diverse base64 line, not prose or a repeated fake pattern."""
    m = _PEM_BODY.match(body)
    if not m:
        return False
    b = m.group("b64")[:64]
    if len(set(b)) < 20:
        return False
    return not any(b.count(b[i:i + 8]) >= 3 for i in range(0, len(b) - 8))


def _jwt_flags(tok: str) -> tuple[bool | None, bool]:
    """(expired before the 2026-09-20 export, training-app token). The payload is decoded in
    memory only to read these two facts; nothing from it is stored."""
    import base64
    import json
    try:
        seg = tok.split(".")[1]
        payload = json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))
    except Exception:
        return None, False
    raw = json.dumps(payload).lower()
    exp = payload.get("exp") if isinstance(payload, dict) else None
    expired = (exp < 1789862400) if isinstance(exp, (int, float)) else None  # 2026-09-20 00:00 UTC
    return expired, any(k in raw for k in ("juice", "localhost", "owasp"))
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_LONGNUM_RE = re.compile(r"\d{7,}")


def _classes(v: str) -> str:
    out = ""
    if any(c.islower() for c in v):
        out += "L"
    if any(c.isupper() for c in v):
        out += "U"
    if any(c.isdigit() for c in v):
        out += "D"
    if any(not c.isalnum() for c in v):
        out += "S"
    return out


def _fp(v: str) -> str:
    return hashlib.sha256(SALT + v.encode()).hexdigest()[:16]


def _strength(v: str) -> str:
    n, k = len(v), len(_classes(v))
    if (n >= 8 and k >= 3) or (n >= 12 and k >= 2):
        return "strong"
    if n >= 8 and k >= 2:
        return "medium"
    return "weak"


def _plausible_assignment(v: str) -> bool:
    lv = v.lower().rstrip(".:!?")
    if len(lv) < 6 or lv in STOP or lv.startswith(BAD_START):
        return False
    if any(s in lv for s in BAD_SUB):
        return False
    if len(set(lv)) < 4:
        return False
    return True


def _service(text: str, start: int, end: int) -> str | None:
    lo, hi = max(0, start - 120), min(len(text), end + 120)
    best, dist = None, 10**9
    for m in _SERVICE_RE.finditer(text, lo, hi):
        d = min(abs(m.start() - start), abs(m.end() - end))
        if d < dist:
            best, dist = m.group(0).lower(), d
    return best


def _hits_in(text: str) -> list[dict]:
    hits = []
    for kind, rx in TOKEN_RES.items():
        for m in rx.finditer(text):
            v = m.group("val")
            if kind == "private_key":
                if not _real_pem(v):
                    continue
            elif "REDACTED" in v.upper() or len(set(v)) < 8 or not {"D", "U"} <= set(_classes(v)):
                continue
            hits.append((kind, None, m.start("val"), m.end("val"), v))
    for m in [*ASSIGN.finditer(text), *ASSIGN_IS.finditer(text)]:
        v = m.group("val").rstrip(".:!?")
        nxt = text[m.start("val") + len(v): m.start("val") + len(v) + 1]
        if not _plausible_assignment(v) or nxt == "(":
            continue
        key = re.sub(r"[ _-]", " ", m.group("key").lower())
        hits.append(("assignment", key, m.start("val"), m.start("val") + len(v), v))
    for m in URLCRED.finditer(text):
        v, user = m.group("val"), m.group("user")
        if ("REDACTED" in v.upper() or v.startswith(("$", "{", "%", "<")) or len(v) < 6
                or v.lower() in ("x-oauth-basic", "x-access-token") or user.startswith(("<", "$", "[", "{", "%"))):
            continue
        hits.append(("url_userinfo", m.group("host").lower(), m.start("val"), m.end("val"), v))
    for m in BEARER.finditer(text):
        v = m.group("val")
        if "REDACTED" in v.upper() or len(set(v)) < 8:
            continue
        hits.append(("bearer_token", None, m.start("val"), m.end("val"), v))
    out, kept = [], []
    for kind, key, s, e, v in hits:  # token formats come first and win overlaps
        if any(s < ke and ks < e for ks, ke in kept):
            continue
        kept.append((s, e))
        lo, hi = max(0, s - 300), min(len(text), e + 300)
        jwt_expired, jwt_training = _jwt_flags(v) if kind == "jwt" else (None, False)
        out.append({
            "jwt_expired": jwt_expired,
            "kind": kind,
            "key": key,
            "service": _service(text, s, e),
            "val_len": len(v),
            "val_classes": _classes(v),
            "strength": "token" if kind not in ("assignment", "url_userinfo") else _strength(v),
            "fp": _fp(v),
            "near_redacted": "[REDACTED]" in text[lo:hi],
            "training_context": jwt_training or bool(_TRAINING_RE.search(text, max(0, s - 200), min(len(text), e + 200))),
            "pos": s,
        })
    return out


def _masked_context(text: str, s: int, e: int, n: int, classes: str) -> str:
    """Context for manual precision checks. The value and any nearby secrets,
    emails and long numbers are masked."""
    before, after = text[max(0, s - 50):s], text[e:e + 25]

    def mask(t: str) -> str:
        t = _EMAIL_RE.sub("«EMAIL»", t)
        t = _LONGNUM_RE.sub("«NUM»", t)
        for rx in list(TOKEN_RES.values()) + [ASSIGN, ASSIGN_IS, URLCRED, BEARER]:
            t = rx.sub("«SECRET»", t)
        return t.replace("\n", "⏎")

    return f"{mask(before)}«VALUE len={n} {classes}»{mask(after)}"


def _init_worker(salt: bytes) -> None:
    global SALT
    SALT = salt


def _scan_unit(unit: tuple[int, int]) -> tuple[int, int, int, list[dict], list[dict]]:
    """Scan one row group of one source table."""
    si, rg = unit
    table, fname, cols, raw_file, fields = SOURCES[si]
    df = pl.from_arrow(pq.ParquetFile(TABLES / fname).read_row_group(rg, columns=["id", *cols]))
    rng = random.Random(20261003 + 1000 * si + rg)
    rows, samples, n_cand = [], [], 0
    for col in cols:
        cand = df.filter(pl.col(col).str.contains(PREFILTER)).select("id", col)
        n_cand += cand.height
        for rid, text in cand.iter_rows():
            for h in _hits_in(text):
                h.update(table=table, column=col, row_id=rid, raw_file=raw_file, raw_field=fields[col])
                rate = 0.05 if h["kind"] == "assignment" else 0.25
                if len(samples) < 60 and rng.random() < rate:
                    samples.append({
                        **{k: h[k] for k in ("table", "column", "kind", "key", "service", "strength", "training_context")},
                        "ctx": _masked_context(text, h["pos"], h["pos"] + h["val_len"], h["val_len"], h["val_classes"]),
                    })
                h["ctx"] = _masked_context(text, h["pos"], h["pos"] + h["val_len"], h["val_len"], h["val_classes"])
                rows.append(h)
    return si, df.height, n_cand, rows, samples


def scan(workers: int = 16) -> pl.DataFrame:
    import multiprocessing as mp

    units = [(si, rg) for si, src in enumerate(SOURCES) for rg in range(pq.ParquetFile(TABLES / src[1]).num_row_groups)]
    # Larger tables first so the pool stays busy at the end.
    units.sort(key=lambda u: -pq.ParquetFile(TABLES / SOURCES[u[0]][1]).metadata.row_group(u[1]).total_byte_size)
    os.environ["POLARS_MAX_THREADS"] = "1"
    rows, samples, stats = [], [], {}
    t0 = time.time()
    with mp.get_context("spawn").Pool(workers, initializer=_init_worker, initargs=(SALT,)) as pool:
        for k, (si, n_rows, n_cand, r, smp) in enumerate(pool.imap_unordered(_scan_unit, units), 1):
            rows += r
            samples += smp
            a = stats.setdefault(SOURCES[si][0] + "/" + SOURCES[si][1], [0, 0, 0])
            a[0] += n_rows
            a[1] += n_cand
            a[2] += len(r)
            if k % 25 == 0 or k == len(units):
                print(f"{k}/{len(units)} row groups, {len(rows):,} hits, {time.time() - t0:.0f}s", flush=True)
    for name, (n_rows, n_cand, n_hits) in stats.items():
        print(f"{name}: {n_rows:,} rows, {n_cand:,} candidate cells, {n_hits:,} hits", flush=True)
    pl.DataFrame(samples).write_parquet(OUT / "masked_samples.parquet")
    return pl.DataFrame(rows, infer_schema_length=None).drop("pos")


def attribute(hits: pl.DataFrame) -> pl.DataFrame:
    agents = pl.read_parquet(TABLES / "agents.parquet", columns=["id", "name"]).rename({"id": "agent_id", "name": "agent"})
    meta = [
        pl.read_parquet(TABLES / "agent_memories.parquet", columns=["id", "agent_id", "created_at"])
        .with_columns(table=pl.lit("agent_memories")),
        pl.read_parquet(TABLES / "events.parquet", columns=["id", "agent_id", "speaker_id", "created_at"])
        .with_columns(agent_id=pl.coalesce("agent_id", "speaker_id"), table=pl.lit("events")).drop("speaker_id"),
        pl.read_parquet(TABLES / "computer_use_turns.parquet", columns=["id", "session_id", "created_at"])
        .join(pl.read_parquet(TABLES / "computer_use_sessions.parquet", columns=["id", "agent_id"])
              .rename({"id": "session_id"}), on="session_id", how="left")
        .drop("session_id").with_columns(table=pl.lit("computer_use_turns")),
        pl.read_parquet(TABLES / "chat_messages.parquet", columns=["id", "agent_speaker_id", "created_at"])
        .rename({"agent_speaker_id": "agent_id"}).with_columns(table=pl.lit("chat_messages")),
        pl.read_parquet(TABLES / "computer_use_sessions.parquet", columns=["id", "agent_id", "created_at"])
        .with_columns(table=pl.lit("computer_use_sessions")),
        pl.read_parquet(TABLES / "summaries.parquet", columns=["id", "created_at"])
        .with_columns(agent_id=pl.lit(None, pl.String), table=pl.lit("summaries")),
        pl.read_parquet(TABLES / "claude_code_messages.parquet", columns=["id", "agent_id", "created_at"])
        .with_columns(table=pl.lit("claude_code_messages")),
    ]
    meta = pl.concat([m.select("table", "id", "agent_id", "created_at") for m in meta]).rename({"id": "row_id"})
    return (
        hits.join(meta, on=["table", "row_id"], how="left")
        .join(agents, on="agent_id", how="left")
        .with_columns(created_pt=pl.col("created_at").dt.convert_time_zone("America/Los_Angeles"))
    )


def summarize(hits: pl.DataFrame) -> str:
    rep = hits.filter((pl.col("strength") != "weak") & ~pl.col("training_context"))
    lines = ["# Credential scan", "",
             "Hits that look like real credentials (strong or medium assignments, token formats, URL credentials), "
             "excluding local training-app contexts. Values are never stored.", ""]
    by = (rep.group_by("table", "column", "kind")
          .agg(rows=pl.col("row_id").n_unique(), distinct_values=pl.col("fp").n_unique(),
               agents=pl.col("agent").n_unique(),
               first=pl.col("created_pt").min().dt.date(), last=pl.col("created_pt").max().dt.date())
          .sort("rows", descending=True))
    lines.append(str(by))
    lines += ["", "Distinct values overall: " + str(rep["fp"].n_unique()),
              "Rows overall: " + str(rep.select(pl.struct("table", "row_id").n_unique()).item()), ""]
    lines.append(str(rep.group_by("agent").agg(rows=pl.len(), distinct=pl.col("fp").n_unique())
                     .sort("distinct", descending=True).head(25)))
    lines.append(str(rep.group_by("service").agg(distinct=pl.col("fp").n_unique()).sort("distinct", descending=True).head(40)))
    lines.append(str(hits.group_by("kind", "strength", "training_context").agg(n=pl.len(), distinct=pl.col("fp").n_unique())
                     .sort("n", descending=True)))
    return "\n".join(lines)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pl.Config.set_tbl_rows(80)
    pl.Config.set_tbl_cols(12)
    pl.Config.set_fmt_str_lengths(60)
    hits = attribute(scan())
    hits.write_parquet(OUT / "hits.parquet")
    (hits.filter((pl.col("strength") != "weak") & ~pl.col("training_context"))
     .sort("raw_file", "created_at")
     .unique(subset=["raw_file", "row_id", "kind", "fp"], keep="first", maintain_order=True)
     .select("raw_file", "raw_field", "row_id", "agent", pl.col("created_at").dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
             "kind", "key", "service", "val_len", "jwt_expired")
     .write_csv(OUT / "locations.csv"))
    text = summarize(hits)
    (OUT / "summary.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
