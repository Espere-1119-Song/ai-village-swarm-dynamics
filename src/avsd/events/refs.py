"""Reference extraction and normalisation (SPEC 4.1 `refs`, 6.3.2, 8.3).

Pulls URLs, file paths and git remotes out of free text and maps each to one
comparable key:

- `gdoc:<type>:<id>` for Google Docs, Sheets, Slides, Forms and Drive
  (`<type>` is the URL segment: document, spreadsheets, presentation, forms,
  drawings, file, folder; the id is the join key),
- `github:<owner>/<repo>[/<path>]` and `gitlab:<group>/.../<repo>[/<path>]`,
  with owner and repo lowercased; `<path>` is a file path, or
  `issues/<n>`, `pull/<n>`, `merge_requests/<n>`, `commit/<sha>`,
- `gitlab-pid:<n>[/<path>]` for GitLab API calls by numeric project id,
- `path:<p>` for file paths (`/home/computeruse` and `$HOME` become `~`),
- the normalised URL for everything else.

The extractor does not know who produced a text. Callers put references from
the actor's own text in `refs` and those from tool output, errors and search
answers in `refs_obs` (docs/decisions.md, unified event table conventions).

Credentials never survive: query keys that name a secret (after lowercasing
and dropping `-` and `_`, e.g. `api-key`, `x-signature`, `claim_token`) are
dropped, and tokens with known prefixes and JWTs are replaced by `REDACTED`.

Raw refs can hold third-party account names; `hash_owner` masks them for
public outputs, which otherwise show URL domains only (SPEC 6.3.2). The
pseudonym is `owner_` plus 10 hex digits of HMAC-SHA256 of the lowercased name,
keyed with a project secret (`<paths.interim>/owner_hash_salt`, under the
gitignored `data/`, created on first use). It is stable across runs of one
project, so joins on masked refs work, but without the secret nobody can match
a list of candidate account names against it.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import hashlib
import hmac
import os
import posixpath
import re
import secrets
from collections.abc import Collection
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urlsplit

import polars as pl

# --- owners kept in clear text ----------------------------------------------
# Confirmed on the pinned export (2026-09-30). The shared organisation is the
# most used GitHub owner (29 agents) and GitLab group (32 agents) in
# agent_action text. Agent accounts are the logins reported by `gh auth status`
# / `glab auth status` in tool output, each seen for exactly one agent, plus
# o3-ux, which agents push to. Everything else is hashed by `hash_owner`.
VILLAGE_ORGS: frozenset[str] = frozenset({"ai-village-agents"})
AGENT_ACCOUNTS: frozenset[str] = frozenset({
    # GitHub
    "claude-3-7-sonnet", "claude-opus-4-6", "claude-opus-4-7-village", "claude-opus-4-8",
    "claude-sonnet-4-6", "claude-sonnet-45", "claudehaiku45", "deepseek-v32",
    "fine-tuned-leader", "gemini-25-pro-collab", "gemini-3-1-pro", "gemini-3-5-flash",
    "gemini-3-pro-ai-village", "gpt-5-1", "gpt-5-2", "gpt-5-4", "gpt-5-5-village",
    "gpt-5-ai-village", "kimi-k26", "o3-ux", "opus-4-5-claude-code",
    # GitLab
    "claude-fable-5", "claude-haiku-4-5", "claude-opus-4-5", "claude-opus-5",
    "claude-sonnet-5", "deepseek-v3-2", "deepseek-v4-pro", "glm-5-2", "gpt-5-5",
    "gpt-5-6-luna", "gpt-5-6-sol", "grok-4-5", "kimi-k3", "muse-spark-1-3",
})
KEEP_OWNERS: frozenset[str] = VILLAGE_ORGS | AGENT_ACCOUNTS
# Home directory of the agents' computers; `~` and `$HOME` point here.
AGENT_HOME = "/home/computeruse"
# User directory names that are generic accounts or placeholders rather than
# people (hash_owner compares them lowercased).
GENERIC_HOME_USERS = frozenset({
    "computeruse", "computeruser", "agent", "user", "ubuntu", "root", "oai", "runner", "shared",
    "guest", "public", "default", "admin", "administrator", "home", "test", "username", "yourname",
    "your_username", "yourusername", "you", "me", "name", "example",
})
# Secret for owner pseudonyms, under paths.interim (see the module docstring).
SALT_FILE = "owner_hash_salt"

# --- query parameters dropped -----------------------------------------------
TRACKING_PARAMS = frozenset({
    "fbclid", "gclid", "dclid", "gbraid", "wbraid", "msclkid", "yclid", "twclid", "ttclid",
    "li_fat_id", "mc_cid", "mc_eid", "ref_src", "ref_url", "igshid", "igsh", "si", "spm", "scm",
    "_hsenc", "_hsmi", "mkt_tok", "vero_id", "oly_anr_id", "oly_enc_id", "rb_clickid", "s_cid",
    "trk", "usp", "fclid", "feature", "share_id", "_ga", "_gl",
})
TRACKING_PREFIXES = ("utm_", "pk_", "mtm_", "hsa_")
# Cache busters: agents append these to defeat CDN caches, so they do not
# identify a resource.
CACHE_BUST_PARAMS = frozenset({
    "cb", "nocache", "no_cache", "cachebust", "cachebuster", "cache_bust", "cache_buster", "bust", "_",
})
# Timestamp-valued versions of these keys are cache busters too.
_TS_KEYS = frozenset({"t", "v", "ts", "_t", "time", "timestamp", "ver", "version", "r", "nc"})
# Credentials never kept in a ref. Keys are compared after `_norm_key`
# (lowercase, no `-` or `_`): a key is dropped if it is one of SECRET_PARAMS or
# contains one of SECRET_KEY_PARTS, unless it is one of NOT_SECRET_KEYS.
SECRET_PARAMS = frozenset({
    "token", "access_token", "private_token", "auth_token", "id_token", "refresh_token",
    "api_key", "apikey", "key", "secret", "client_secret", "password", "passwd", "pwd", "pass",
    "sig", "signature", "x-amz-signature", "x-amz-credential", "x-amz-security-token",
    "x-goog-signature", "x-goog-credential", "auth", "authorization", "session", "sessionid",
    "code",
})
SECRET_KEY_PARTS = ("token", "secret", "password", "passwd", "apikey", "accesskey", "signature",
                    "credential", "jwt", "privatekey", "authkey")
NOT_SECRET_KEYS = frozenset({"tokenid", "tokenaddress", "tokentype", "tokenusage", "maxtokens"})
_TOKEN_RE = re.compile(
    r"(?:glpat-|gldt-|ghp_|gho_|ghu_|ghs_|ghr_|github_pat_|sk-(?:proj-|ant-)?|xox[abprs]-|AKIA|AIza)"
    r"[A-Za-z0-9_\-]{8,}"
    r"|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}(?:\.[A-Za-z0-9_\-]*)?"  # JWT
)

# --- candidate regex (Rust syntax, run by polars) ---------------------------
# Every alternative may start with one delimiter character; it is stripped in
# Python. Requiring a delimiter keeps paths out of URLs and words.
_LEAD = " \t\n\r\f\v([<{\"'=,;|>*`:"
_D = r"(?:^|[\s(\[<{\"'=,;|>*`])"
_DP = r"(?:^|[\s(\[<{\"'=,;|>*`:])"  # paths may also follow ":" (PATH lists)
_URL_TAIL = r"[^\s<>\"'`\\|^\[\]*…“”‘’«»—–。，、；：！？（）【】\x00-\x1f\x{200B}]+"
_SEG = r"[\w.\-‐‑]+"
# ASCII word boundary: a Unicode \b disables the lazy DFA on non-ASCII text
# and makes the scan about 15x slower.
_B = r"(?-u:\b)"
CANDIDATE_RE = "|".join([
    # URLs with a scheme; bare www.* and a few bare hosts.
    r"(?i:https?://)" + _URL_TAIL,
    _D + r"(?i:www\.|(?:github|gitlab)\.com/|(?:docs|drive)\.google\.com/)" + _URL_TAIL,
    # SSH git remotes.
    r"(?:ssh://)?git@(?:github|gitlab)\.com[:/][\w.\-/‐‑]+",
    # gh/glab commands that name a repository.
    _B + r"gh\s+repo\s+[a-z][a-z\-]*\s+[\"']?" + _SEG + r"/" + _SEG + r"(?:/" + _SEG + r")?",
    _B + r"glab\s+repo\s+[a-z][a-z\-]*\s+[\"']?" + _SEG + r"(?:/" + _SEG + r")+",
    _B + r"(?:gh|glab)\s[^\n;&|]*?\s(?:-R|--repo)(?:\s+|=)[\"']?[\w.\-‐‑:/]+",
    _B + r"gh\s+api(?-u:\b)[^\n;&|]*?[\s\"']/?repos/[^\s\"'<>`\\|]+",
    _B + r"glab\s+api(?-u:\b)[^\n;&|]*?[\s\"']/?projects/[^\s\"'<>`\\|]+",
    # File paths: /abs, ~/, ./, ../, $HOME/.
    _DP + r"(?:~|\$\{?HOME\}?|\.\.?)?/[\w.\-~/+@%‐‑]+",
])

# Absolute paths are kept only under these roots; other roots are mostly web
# routes (/api/..., /articles/...) or system files (/dev/null, /usr/bin/env).
PATH_ROOTS = frozenset({
    "home", "root", "tmp", "workspace", "workspaces", "mnt", "media", "opt", "srv", "var",
    "data", "app", "Users", "scratch",
})

_GITHUB_RESERVED = frozenset({
    "about", "account", "apps", "codespaces", "collections", "contact", "copilot", "customer-stories",
    "dashboard", "enterprise", "events", "explore", "features", "issues", "join", "login", "logout",
    "marketplace", "new", "notifications", "organizations", "orgs", "password_reset", "pricing",
    "pulls", "readme", "search", "security", "sessions", "settings", "signup", "site", "sponsors",
    "stars", "topics", "trending", "users", "watching", "repos",
})
_GITLAB_RESERVED = frozenset({
    "-", "admin", "api", "assets", "dashboard", "explore", "groups", "help", "oauth", "profile",
    "projects", "search", "snippets", "uploads", "users", "s",
})
_FILE_KINDS = frozenset({"blob", "tree", "raw", "blame", "edit"})
_GDOC_HOSTS = frozenset({
    "docs.google.com", "drive.google.com", "sheets.google.com", "slides.google.com",
    "forms.google.com",
})
_GDOC_ID = re.compile(r"[A-Za-z0-9_\-]{20,}")
_OWNER = re.compile(r"[a-z0-9](?:[a-z0-9\-_.]*[a-z0-9_])?")
_REPO = re.compile(r"[a-z0-9_.\-]+")
_HOST = re.compile(r"[a-z0-9](?:[a-z0-9\-_.]*[a-z0-9])?|\[[0-9a-f:.]+\]")
_SHA = re.compile(r"[0-9a-f]{7,40}")
_TEMPLATE = re.compile(r"[${}<>]|%7B|%7D|%24|%3C|%3E", re.I)
_TS_VALUE = re.compile(r"[\d\-T:.]{8,}")
_CMD = re.compile(r"(?:gh|glab)\s")
_CMD_API = re.compile(r"(?:gh|glab)\s+api\s")
_DASHES = str.maketrans({"‐": "-", "‑": "-"})
_OPEN = {")": "(", "]": "[", "}": "{"}


# --- helpers -----------------------------------------------------------------
def _strip_trailing(s: str) -> str:
    """Drop punctuation a regex picks up after a URL or path."""
    while s:
        c = s[-1]
        if c in ".,;:!?'\"*>`&":
            s = s[:-1]
        elif c in _OPEN and s.count(c) > s.count(_OPEN[c]):
            s = s[:-1]
        else:
            break
    return s


def _redact(s: str) -> str:
    return _TOKEN_RE.sub("REDACTED", s)


def _norm_key(key: str) -> str:
    return key.lower().replace("-", "").replace("_", "")


_SECRET_KEYS = frozenset(_norm_key(k) for k in SECRET_PARAMS)


def is_secret_param(key: str) -> bool:
    """True for a query key that names a credential (see SECRET_PARAMS)."""
    k = _norm_key(unquote(key).strip())
    if k in NOT_SECRET_KEYS:
        return False
    return k in _SECRET_KEYS or any(p in k for p in SECRET_KEY_PARTS)


def _keep_param(piece: str) -> bool:
    key, _, value = piece.partition("=")
    k = unquote(key).strip().lower()
    if not k and not value:
        return False
    if k in TRACKING_PARAMS or k.startswith(TRACKING_PREFIXES):
        return False
    if k in CACHE_BUST_PARAMS or is_secret_param(key):
        return False
    if _TEMPLATE.search(value):  # unexpanded shell or template value
        return False
    if k in _TS_KEYS and _TS_VALUE.fullmatch(value):
        return False
    return True


def _segments(path: str) -> list[str]:
    """Split a raw URL path and decode each segment (keeps %2F inside one)."""
    out = []
    for s in path.split("/"):
        if not s:
            continue
        if _TEMPLATE.search(s):  # stop at the first placeholder segment
            break
        out.append(unquote(s))
    return out


def _repo_ref(forge: str, project: list[str], tail: list[str]) -> str | None:
    """`github:`/`gitlab:` ref from project segments and the part after them."""
    if not project:
        return None
    project = [p.lower() for p in project]
    # "repo.git@v1" in pip/npm specs names a ref of the repository.
    project[-1] = project[-1].split("@", 1)[0].removesuffix(".git")
    if not _OWNER.fullmatch(project[0]) or not all(_REPO.fullmatch(p) for p in project[1:]):
        return None
    if len(project) > 1 and project[-1] in ("", ".", ".."):
        return None
    ref = f"{forge}:{'/'.join(project)}"
    sub = _subresource(tail)
    return f"{ref}/{sub}" if sub else ref


def _subresource(tail: list[str]) -> str | None:
    """File path or issue/PR/commit id below a repository, else None."""
    if not tail:
        return None
    kind = tail[0]
    if kind in _FILE_KINDS and len(tail) >= 2:
        rest = tail[2:]
        if tail[1] == "refs" and len(tail) >= 4 and tail[2] in ("heads", "tags"):
            rest = tail[4:]
        return "/".join(rest) or None
    if len(tail) >= 2:
        n = tail[1]
        if kind in ("issues", "pull", "pulls", "merge_requests", "work_items", "discussions") and n.isdigit():
            return f"{'pull' if kind == 'pulls' else kind}/{n}"
        if kind in ("commit", "commits") and _SHA.fullmatch(n.lower()):
            return f"commit/{n.lower()}"
    return None


def _github(host: str, segs: list[str]) -> str | None | bool:
    """Ref for a GitHub URL; False when the URL is not a repository form."""
    if host == "raw.githubusercontent.com":
        if len(segs) < 2:
            return False
        rest = segs[2:]
        if rest[:1] == ["refs"] and len(rest) >= 3:
            rest = rest[2:]
        return _repo_ref("github", segs[:2], ["blob", *rest]) if rest else _repo_ref("github", segs[:2], [])
    if host == "codeload.github.com":
        return _repo_ref("github", segs[:2], []) if len(segs) >= 2 else False
    if host == "api.github.com":
        if segs[:1] == ["repos"] and len(segs) >= 3:
            tail = segs[3:]
            if tail[:1] == ["contents"]:
                tail = ["blob", "HEAD", *tail[1:]]
            return _repo_ref("github", segs[1:3], tail)
        if segs[:1] in (["users"], ["orgs"]) and len(segs) >= 2:
            return _repo_ref("github", segs[1:2], [])
        return False
    if not segs:
        return False
    head = segs[0].lower()
    if head in ("orgs", "users") and len(segs) >= 2:
        return _repo_ref("github", segs[1:2], [])
    if head in _GITHUB_RESERVED:
        return False
    if not _OWNER.fullmatch(head):
        return False
    return _repo_ref("github", segs[:2], segs[2:])


def _gitlab(segs: list[str]) -> str | None | bool:
    """Ref for a gitlab.com URL; False when it is not a project form."""
    if not segs:
        return False
    head = segs[0].lower()
    if head == "api":
        # api/v4/projects/<id or url-encoded path>/...
        if len(segs) >= 4 and segs[2] == "projects":
            pid, tail = segs[3], segs[4:]
            if tail[:2] == ["repository", "files"] and len(tail) >= 3:
                tail = ["blob", "HEAD", tail[2]]
            elif tail[:2] == ["repository", "commits"] and len(tail) >= 3:
                tail = ["commit", tail[2]]
            if pid.isdigit():
                sub = _subresource(tail)
                return f"gitlab-pid:{pid}" + (f"/{sub}" if sub else "")
            return _repo_ref("gitlab", pid.split("/"), tail)
        if len(segs) >= 4 and segs[2] == "groups":
            return _repo_ref("gitlab", segs[3].split("/"), [])
        return False
    if head == "groups" and len(segs) >= 2:
        end = segs.index("-") if "-" in segs else len(segs)
        return _repo_ref("gitlab", segs[1:end], [])
    if head in _GITLAB_RESERVED:
        return False
    if "-" in segs:
        i = segs.index("-")
        return _repo_ref("gitlab", segs[:i], segs[i + 1:])
    for i, s in enumerate(segs[2:], start=2):  # legacy routes without "/-/"
        if s in _FILE_KINDS or s in ("issues", "merge_requests", "commit", "commits"):
            return _repo_ref("gitlab", segs[:i], segs[i:])
    return _repo_ref("gitlab", segs, [])


def _gdoc(segs: list[str], query: str) -> str | None | bool:
    """`gdoc:<type>:<id>`; None for a placeholder id; False if no doc form."""
    s = list(segs)
    if s[:1] == ["a"] and len(s) >= 2:  # Workspace domain prefix
        s = s[2:]
    s = [x for i, x in enumerate(s) if not (x == "u" and s[i + 1:i + 2] and s[i + 1].isdigit())
         and not (i > 0 and s[i - 1] == "u" and x.isdigit())]
    doc_type, doc_id = None, None
    if "d" in s:
        i = s.index("d")
        doc_type = s[i - 1] if i > 0 else "file"
        rest = s[i + 1:]
        if rest[:1] == ["e"]:
            rest = rest[1:]
        doc_id = rest[0] if rest else ""
    elif "folders" in s:
        i = s.index("folders")
        doc_type, doc_id = "folder", (s[i + 1] if i + 1 < len(s) else "")
    elif s[:1] in (["open"], ["uc"], ["thumbnail"]):
        for piece in query.split("&"):
            k, _, v = piece.partition("=")
            if k == "id":
                doc_type, doc_id = "file", v
                break
    if doc_type is None:
        return False
    if not doc_id or not _GDOC_ID.fullmatch(doc_id):
        return None
    return f"gdoc:{doc_type.lower()}:{doc_id}"


# --- public API ----------------------------------------------------------------
@lru_cache(maxsize=1 << 18)
def normalize_url(url: str) -> str | None:
    """Normalise one URL, or map it to a gdoc/github/gitlab ref.

    Lowercases scheme and host, drops userinfo, default ports, the fragment,
    tracking, cache-buster and credential query parameters, a trailing slash
    and trailing punctuation. Other query parameters keep their order and
    encoding. Returns None for templates and malformed URLs.
    """
    u = _strip_trailing(url.strip().lstrip("<([{\"'`*")).translate(_DASHES).replace("&amp;", "&")
    if "://" not in u[:10]:
        u = "https://" + u.lstrip("/")
    try:
        p = urlsplit(u)
        port = p.port
    except ValueError:
        return None
    scheme = p.scheme.lower()
    host = (p.hostname or "").rstrip(".")
    if ":" in host:
        host = f"[{host}]"
    if scheme not in ("http", "https") or not _HOST.fullmatch(host):
        return None
    if "." not in host and host != "localhost" and not host.startswith("["):
        return None
    segs = _segments(p.path)
    query = p.query
    if host in ("github.com", "www.github.com", "api.github.com", "raw.githubusercontent.com",
                "codeload.github.com"):
        ref = _github(host.removeprefix("www."), segs)
        if ref is not False:
            return _redact(ref) if ref else None
    elif host in ("gitlab.com", "www.gitlab.com"):
        ref = _gitlab(segs)
        if ref is not False:
            return _redact(ref) if ref else None
    elif host in _GDOC_HOSTS:
        ref = _gdoc(segs, query)
        if ref is not False:
            return ref
    netloc = host if port is None or (scheme, port) in (("http", 80), ("https", 443)) else f"{host}:{port}"
    # Keep the raw path up to the first placeholder segment; collapse "//".
    raw = [s for s in p.path.split("/") if s]
    kept = []
    for s in raw:
        if _TEMPLATE.search(s):
            break
        kept.append(s)
    path = "/" + "/".join(kept) if kept else ""
    q = "&".join(x for x in query.split("&") if x and _keep_param(x))
    return _redact(f"{scheme}://{netloc}{path}" + (f"?{q}" if q else ""))


def normalize_path(path: str) -> str | None:
    """`path:<p>` for an absolute, home-relative or ./ ../ path, else None."""
    p = _strip_trailing(path.strip()).translate(_DASHES)
    p = re.sub(r"^\$\{?HOME\}?(?=/|$)", "~", p)
    if p == AGENT_HOME or p.startswith(AGENT_HOME + "/"):
        p = "~" + p[len(AGENT_HOME):]
    if not p.startswith(("/", "~/", "./", "../")):
        return None
    if p.startswith("//"):
        p = "/" + p.lstrip("/")
    lead = "./" if p.startswith("./") else ""
    p = posixpath.normpath(p) if not p.startswith("~") else "~" + posixpath.normpath(p[1:])
    p = lead + p if lead and not p.startswith(("..", "/")) else p
    segs = [s for s in p.split("/") if s not in ("", ".", "..", "~")]
    if not segs:
        return None
    if p.startswith("/"):
        if segs[0] not in PATH_ROOTS or len(segs) < (3 if segs[0] == "home" else 2):
            return None
    return "path:" + _redact(p)


@lru_cache(maxsize=1 << 20)
def _candidate_ref(c: str) -> str | None:
    """Ref for one regex candidate (leading delimiter already stripped)."""
    if _CMD.match(c):
        return _command_ref(c)
    lc = c[:12].lower()
    if lc.startswith(("git@", "ssh://git@")):
        m = re.match(r"(?:ssh://)?git@(github|gitlab)\.com[:/](.+)", _strip_trailing(c))
        if not m:
            return None
        segs = [s for s in m.group(2).translate(_DASHES).split("/") if s]
        if not segs:
            return None
        return _repo_ref(m.group(1), segs if m.group(1) == "gitlab" else segs[:2], [])
    if lc.startswith(("http://", "https://", "www.", "github.com/", "gitlab.com/", "docs.google", "drive.google")):
        return normalize_url(c)
    return normalize_path(c)


def _command_ref(c: str) -> str | None:
    tool = "gitlab" if c.startswith("glab") else "github"
    target = _strip_trailing(c.split()[-1]).strip("\"'")
    target = target.split("=", 1)[1] if target.startswith("--repo=") else target
    if target.startswith(("http://", "https://")):
        return normalize_url(target)
    target = target.translate(_DASHES).lstrip("/")
    if _CMD_API.match(c):
        base = "https://api.github.com/" if tool == "github" else "https://gitlab.com/api/v4/"
        ref = normalize_url(base + target)
        return ref if ref and ref.startswith(tool) else None
    segs = [s for s in target.split("/") if s]
    if segs and "." in segs[0] and len(segs) >= 3:  # HOST/OWNER/REPO
        segs = segs[1:]
    if len(segs) < 2:
        return None
    return _repo_ref(tool, segs if tool == "gitlab" else segs[:2], [])


def extract_refs_batch(texts: pl.Series) -> pl.Series:
    """Refs per text as `list[str]`, deduplicated in order of first appearance.

    Polars finds the candidates; Python normalises each distinct candidate
    once (cached across calls). Null texts give empty lists.
    """
    df = pl.DataFrame({"t": texts.cast(pl.String)}).with_row_index("row")
    # The streaming engine runs the regex scan on all cores.
    found = (
        df.lazy()
        .select("row", pl.col("t").str.extract_all(CANDIDATE_RE).alias("c"))
        .collect(engine="streaming")
        .sort("row")
    )
    cand = (
        found.filter(pl.col("c").list.len() > 0)
        .explode("c", empty_as_null=True)
        .with_columns(pl.col("c").str.strip_chars_start(_LEAD), pl.int_range(pl.len()).alias("pos"))
    )
    uniq = cand["c"].unique()
    mapping = pl.DataFrame(
        {"c": uniq, "ref": pl.Series([_candidate_ref(c) for c in uniq.to_list()], dtype=pl.String)}
    ).drop_nulls("ref")
    per_row = (
        cand.join(mapping, on="c", how="inner")
        .sort("pos")
        .group_by("row", maintain_order=True)
        .agg(pl.col("ref").unique(maintain_order=True))
    )
    out = (
        df.select("row")
        .join(per_row, on="row", how="left")
        .sort("row")
        .select(pl.col("ref").fill_null(pl.lit([], dtype=pl.List(pl.String))))
    )
    return out["ref"].alias(texts.name or "refs")


def extract_refs(text: str | None) -> list[str]:
    """Refs in one text; same rules as `extract_refs_batch`."""
    if not text:
        return []
    return extract_refs_batch(pl.Series([text], dtype=pl.String))[0].to_list()


@lru_cache(maxsize=16)
def _lower_set(keep: frozenset[str]) -> frozenset[str]:
    return frozenset(k.lower() for k in keep)


_salt: bytes | None = None


def owner_salt() -> bytes:
    """The project secret for owner pseudonyms, created once under paths.interim."""
    global _salt
    if _salt is None:
        from avsd.config import load_config

        path = Path(load_config()["paths"]["interim"]) / SALT_FILE
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{SALT_FILE}.{os.getpid()}.tmp")
            tmp.write_bytes(secrets.token_bytes(32))
            tmp.chmod(0o600)
            try:
                os.link(tmp, path)  # atomic: concurrent first uses keep one secret
            except FileExistsError:
                pass
            finally:
                tmp.unlink(missing_ok=True)
        salt = path.read_bytes()
        if len(salt) < 16:
            raise ValueError(f"owner hash secret {path} is shorter than 16 bytes")
        _salt = salt
    return _salt


def set_owner_salt(salt: bytes | None) -> None:
    """Use `salt` for owner pseudonyms in this process; None reverts to the project secret."""
    global _salt
    _salt = salt


@lru_cache(maxsize=1 << 16)
def _hmac10(owner: str, salt: bytes) -> str:
    return "owner_" + hmac.new(salt, owner.encode(), hashlib.sha256).hexdigest()[:10]


def _owner_hash(owner: str, salt: bytes | None = None) -> str:
    return _hmac10(owner.lower(), owner_salt() if salt is None else salt)


# GitLab Pages unique domains (`<project>-<6 hex>.gitlab.io`) name a project, not an owner.
_UNIQUE_DOMAIN = re.compile(r"-[0-9a-f]{6}$")
# Paths whose first segment below the root is an account name.
_USER_DIR = re.compile(r"path:((?:/mnt/[^/]+)?/(?:home|Users)|/media)/([^/]+)")


def _mask_pages_host(ref: str, keep: frozenset[str], salt: bytes | None) -> str:
    """Hash the owner subdomain of a github.io / gitlab.io URL, whatever follows the host."""
    try:
        p = urlsplit(ref)
        port = p.port
    except ValueError:
        return ref
    labels = (p.hostname or "").split(".")
    if len(labels) < 3 or labels[-1] != "io" or labels[-2] not in ("github", "gitlab"):
        return ref
    owner, forge = labels[-3], labels[-2]
    if owner in keep or (forge == "gitlab" and _UNIQUE_DOMAIN.search(owner)):
        return ref
    start = ref.index("//") + 2  # netloc follows the scheme
    netloc = f"{_owner_hash(owner, salt)}.{forge}.io" + (f":{port}" if port is not None else "")
    return ref[:start] + netloc + ref[start + len(p.netloc):]


def hash_owner(
    ref: str, keep_orgs: Collection[str] = KEEP_OWNERS, salt: bytes | None = None
) -> str:
    """Mask third-party account names in a ref for public outputs.

    Replaces with `owner_<hmac[:10]>` (module docstring; `salt` overrides the
    project secret) the GitHub owner or top GitLab group unless it is in
    `keep_orgs` (also inside a repo name such as `<owner>.github.io`); the
    owner subdomain of github.io / gitlab.io URLs (any labels before it are
    dropped), with any path, query or fragment; and the user of
    `/home/<user>`, `/Users/<user>`, `/mnt/<drive>/Users/<user>` and
    `/media/<user>` paths unless it is a generic name (GENERIC_HOME_USERS).
    """
    keep = _lower_set(frozenset(keep_orgs))
    if ref.startswith(("github:", "gitlab:")):
        forge, rest = ref.split(":", 1)
        owner, sep, tail = rest.partition("/")
        if owner in keep:
            return ref
        h = _owner_hash(owner, salt)
        if tail and len(owner) >= 3:  # e.g. <owner>.github.io
            repo, sep2, more = tail.partition("/")
            repo = re.sub(rf"(?<![a-z0-9]){re.escape(owner)}(?![a-z0-9])", h, repo)
            tail = repo + sep2 + more
        return f"{forge}:{h}{sep}{tail}"
    if ref.startswith(("http://", "https://")):
        return _mask_pages_host(ref, keep, salt)
    m = _USER_DIR.match(ref)
    if m and m.group(2).lower() not in GENERIC_HOME_USERS:
        return f"path:{m.group(1)}/{_owner_hash(m.group(2), salt)}{ref[m.end():]}"
    return ref


def ref_type(ref: str) -> str:
    """Aggregation key for QA: github, gitlab, gdoc:<type>, path:<root>, url:<host>."""
    if ref.startswith(("github:", "gitlab:", "gitlab-pid:")):
        return ref.split(":", 1)[0]
    if ref.startswith("gdoc:"):
        return ref.rsplit(":", 1)[0]
    if ref.startswith("path:"):
        p = ref[5:]
        if p.startswith(("~", "./", "../")):
            return "path:" + p.split("/", 1)[0]
        return "path:/" + p.split("/")[1]
    host = urlsplit(hash_owner(ref)).hostname or ""
    return "url:" + host
