"""Artifact touches of computer-use turns (SPEC 8.3, module D2).

A touch is one turn of a computer-use session acting on an artifact. Each touch has a mode:

- `write`: the turn changed the artifact (typed text into it, saved, submitted, sent a request
  body to it, committed or pushed it, or ran a command that modifies it);
- `read`: the turn accessed the artifact without changing it (opened or fetched it, listed or
  printed it, cloned or pulled it, entered its directory, ran it);
- `observed`: the artifact's identifier only appeared in the turn's tool output or error text;
- `mention`: the identifier only appeared in text the agent wrote about it (chat messages, typed
  or written file content, commit messages, search queries, the provider response).

Only `write` and `read` touches make edges in the main graph. `observed` and `mention` are kept
for counts and for a sensitivity variant. Every touch also records the rule that produced it
(`RULES`). The rules follow the SPEC 2.3-7 verification (docs/schema_notes.md 4.7). Rules v2
(`RULE_SETS`, `MAIN_RULES`) were confirmed by the owner on 2026-10-01 (SPEC 8.3) and are the main
version; v1, the first draft, is kept as a sensitivity version.

Sources per turn: the agent_action text (bash `command`, typed `text`, chat `content`, element
`description`, search `query`), the tool output and error text (refs already extracted into
`events_unified.refs_obs`) and the provider response (`agent_messages`, text, thinking and
reasoning parts only).

GUI turns carry no target. A session's GUI focus is the last URL it navigated to (a typed URL,
or a URL opened from bash). Text typed while a page is in focus, ctrl+s or ctrl+Enter, and a
click on a located button whose description names a write (save, submit, send, ...) are writes
to the focused artifact. Without a focus such GUI writes are counted but tied to no artifact.

Bash commands are split into simple commands (heredoc bodies removed first, quotes respected).
The working directory is tracked through `cd` and `pushd` within a session, so relative write
targets resolve to paths. A per-agent map from local directories to remote repositories
(`git clone`, `gh repo clone`, `glab repo clone`, `git remote add|set-url`, and the remote named
in a `git push` output) ties pushes, pulls and forge commands without a repository argument to
the remote repository.

Artifact keys (`artifact_key`) normalise refs as SPEC 8.3 says, on top of `avsd.events.refs`:
Google Docs, Sheets, Slides, Forms and Drive files by document id; GitHub and GitLab by
owner/repo/path (the container is owner/repo); GitLab API calls by numeric project id, mapped to
the project path when the API output names it; GitHub and GitLab Pages URLs map to their
repository; other URLs without query and fragment (pages without a path, search engines,
sign-in, CDN and XML-namespace hosts are not artifacts); file paths and localhost URLs are local
to the agent's own computer, so their key includes the agent, and their container is the
project directory (the first directory below the home directory or below /tmp and similar
roots).

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import math
import posixpath
import re
import shlex
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from avsd.events.refs import AGENT_HOME, _candidate_ref, _command_ref, normalize_path

WRITE, READ, OBSERVED, MENTION = "write", "read", "observed", "mention"
EDGE_MODES = (WRITE, READ)

# rule id -> (mode, description). Descriptions are written for the QA report and the owner.
RULES: dict[str, tuple[str, str]] = {
    # bash
    "B-redirect": (WRITE, "target of a shell redirection (> or >>) or of tee"),
    "B-inplace": (WRITE, "file edited in place (sed -i, perl -i)"),
    "B-fileop": (WRITE, "destination or argument of cp, mv, rsync, scp, install, ln, touch, mkdir, "
                        "rm, rmdir, chmod, truncate, unzip -d, tar -C or tar -f with c"),
    "B-fileop-src": (READ, "source of cp, rsync, scp, install, ln, or an archive that is unpacked"),
    "B-code-write": (WRITE, "path or URL written by code in a heredoc or -c string (open with w, a "
                            "or x, write_text, to_csv, savefig, writeFile, requests post, put, patch "
                            "or delete, fetch with a write method)"),
    "B-code-read": (READ, "path or URL that code in a heredoc or -c string opens, reads, lists, runs or "
                          "fetches (directly or through a variable)"),
    "B-git-local": (WRITE, "local repository directory of git add, commit, rm, mv, merge, rebase, "
                           "reset, checkout, switch, stash, tag, init, apply, am, cherry-pick, "
                           "restore or pull"),
    "B-git-push": (WRITE, "remote repository of git push (directory map, or the remote named in "
                          "the push output)"),
    "B-git-clone-dir": (WRITE, "local directory created by git clone, gh repo clone, glab repo clone"),
    "B-git-remote-read": (READ, "remote repository of git clone, pull or fetch"),
    "B-git-read": (READ, "local repository directory of git log, status, diff, show, branch and "
                         "other read-only git commands"),
    "B-forge-write": (WRITE, "repository, issue or merge request named by gh or glab create, edit, "
                             "comment, merge, close, reopen, review, delete, upload, fork, or api "
                             "with a write method or fields"),
    "B-forge-read": (READ, "repository named by other gh or glab commands (view, list, api GET)"),
    "B-http-write": (WRITE, "URL of curl, wget or httpie with a write method or a request body"),
    "B-http-read": (READ, "URL fetched by curl, wget or httpie without a body"),
    "B-download": (WRITE, "local file written by curl -o, wget -O or similar"),
    "B-upload-src": (READ, "local file sent as a request body (-d @file, -F x=@file, -T file)"),
    "B-open": (READ, "URL or file opened in a browser or viewer (xdg-open, firefox, chrome); "
                     "a URL becomes the GUI focus"),
    "B-cd": (READ, "project directory entered with cd or pushd (container level)"),
    "B-run": (READ, "script that is executed (python x.py, node x.js, bash x.sh, ./x)"),
    "B-other": (READ, "any other path or URL in a command (cat, grep, ls, head, find, ...)"),
    "B-content": (MENTION, "path or URL inside text the command writes or sends as content (echo, "
                           "printf, heredoc file bodies, commit messages, --body, --title and API fields, "
                           "request bodies, string templates in code)"),
    "B-xdotool": (WRITE, "xdotool type or key ctrl+s / ctrl+Return from bash, applied to the GUI focus"),
    # GUI
    "G-nav": (READ, "URL typed as the whole text of a type action (address bar); becomes the GUI focus"),
    "G-type": (WRITE, "other text typed while a page is in focus, written to the focused artifact"),
    "G-key": (WRITE, "ctrl+s or ctrl+Enter while a page is in focus"),
    "G-click": (WRITE, "click right after locating an element whose description names a write "
                       "(save, submit, send, post, publish, commit, create, upload, share, reply, "
                       "comment, confirm, update, apply) while a page is in focus"),
    "G-content": (MENTION, "path or URL inside typed text"),
    "G-search": (MENTION, "rules v2: text typed into the address bar or a located search box that is a "
                          "search query, not a document write (refs inside it are mentions)"),
    "G-input": (MENTION, "rules v2: a typed sign-in value or a short input (one or two characters, or "
                         "a one-word game or menu command), not a document write"),
    # tools
    "T-chat": (MENTION, "path or URL in a chat message sent from the computer"),
    "T-search": (MENTION, "path or URL in a search_history query"),
    "T-other": (MENTION, "path or URL in other tool arguments (element descriptions, helper requests)"),
    # observation and provider response
    "O-output": (OBSERVED, "path or URL in the tool output or error text"),
    "M-message": (MENTION, "path or URL in the provider response (text, thinking, reasoning)"),
}

GUI_WRITE_KEYS = frozenset({"ctrl+s", "ctrl+enter", "ctrl+return", "ctrl+kp_enter", "cmd+s",
                            "super+s", "ctrl+shift+s"})
ADDR_KEYS = frozenset({"ctrl+l", "f6", "alt+d", "ctrl+k", "ctrl+e"})
PROGRAM_KW_BITS = 1 | 256    # `kw` bits (avsd.swarmsim.gui_gap.KEYWORDS) for terminal and game in the agent's words


@dataclass(frozen=True)
class GuiRules:
    """Switches for GUI turns. v1 uses none of them (docs/decisions.md, D2 follow-up)."""

    name: str = "v1"
    reclassify: bool = False                # typed text that is not a document write is no GUI write
    shell_as_bash: bool = False             # typed shell commands are parsed as bash commands
    search_clears_focus: bool = False       # an address-bar search leaves the focused page
    strict_buttons: bool = False            # a click is a write only on a named button (is_write_button)
    carry_gap_min: float | None = None      # focus carried over from the previous session within this gap
    narrative_window: int | None = None     # focus named in the agent's words within this many turns


MAIN_RULES = "v2"            # confirmed by the owner on 2026-10-01; v1 is kept as a sensitivity version
RULE_SETS: dict[str, GuiRules] = {
    "v1": GuiRules(),
    "v2": GuiRules("v2", reclassify=True, shell_as_bash=True, search_clears_focus=True, strict_buttons=True,
                   carry_gap_min=None, narrative_window=None),
}
WRITE_VERB_RE = re.compile(
    r"(?i)\b(?:save|submit|send|post|publish|commit|create|upload|share|reply|comment|confirm|"
    r"update|apply)\b")
CLICK_ACTIONS = frozenset({"left_click", "double_click", "triple_click"})
# Rules v2: a located element counts as a write button only if it is named a button and is not a text
# box, a field, a link, a menu, a tab or an icon (clicking those selects or opens something).
BUTTON_RE = re.compile(r"(?i)\bbutton\b|\bbtn\b")
NOT_BUTTON_RE = re.compile(r"(?i)\btext ?box\b|\binput\b|\bfield\b|\btext ?area\b|\blink\b|\bmenu\b|"
                           r"\bdropdown\b|\bicon\b|\bplaceholder\b|\btab\b|\bcheck ?box\b|\bradio\b|\bbox\b")


def is_write_button(desc: str | None, strict: bool) -> bool:
    """v1: the description names a write verb. v2 (`strict`): it also names a button, and no box, field,
    link, menu, tab or icon comes before the word button ("the send button next to the input box" is a
    button; "the copy link button" and "the reply text box" are not)."""
    d = desc or ""
    if not WRITE_VERB_RE.search(d):
        return False
    if not strict:
        return True
    b = BUTTON_RE.search(d)
    if not b:
        return False
    nb = NOT_BUTTON_RE.search(d)
    return nb is None or nb.start() > b.start()

# --- candidates in free text (Python approximation of avsd.events.refs.CANDIDATE_RE) -----------
_URL_CHARS = r"[^\s<>\"'`\\|^\[\]{}*…“”‘’«»]+"
_URL_RE = re.compile(
    r"(?i)(?:https?://|(?<![\w.@/])www\.|(?<![\w.@/])(?:github|gitlab)\.com/|"
    r"(?<![\w.@/])(?:docs|drive)\.google\.com/|(?:ssh://)?git@(?:github|gitlab)\.com[:/])"
    + _URL_CHARS)
_PATH_RE = re.compile(r"(?:(?<=^)|(?<=[\s(\[<{\"'=,;|>*`:]))(?:~|\$\{?HOME\}?|\.\.?)?/[\w.\-~/+@%]+")


def find_candidates(text: str) -> list[tuple[int, int, str]]:
    """URL and path candidates in `text` as (start, end, string), paths inside URLs left out."""
    out: list[tuple[int, int, str]] = []
    taken: list[tuple[int, int]] = []
    for m in _URL_RE.finditer(text):
        out.append((m.start(), m.end(), m.group(0)))
        taken.append((m.start(), m.end()))
    for m in _PATH_RE.finditer(text):
        s, e = m.start(), m.end()
        if any(a <= s < b for a, b in taken):
            continue
        out.append((s, e, m.group(0)))
    out.sort()
    return out


def norm_ref(raw: str) -> str | None:
    """A refs.py ref for one candidate string (None if it is not a ref)."""
    s = raw.strip().strip("\"'`")
    if not s:
        return None
    try:
        return _candidate_ref(s)
    except Exception:  # noqa: BLE001 - malformed candidates are simply not refs
        return None


def text_refs(text: str | None) -> list[str]:
    """Distinct refs in free text, in order of first appearance."""
    if not text:
        return []
    seen: dict[str, None] = {}
    for _, _, c in find_candidates(text):
        r = norm_ref(c)
        if r:
            seen.setdefault(r, None)
    return list(seen)


# --- shell parsing ------------------------------------------------------------------------------
_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][\w.\-]*)\1")
_CODE_INTERP = re.compile(r"(?:^|[\s;&|(])(?:python[\d.]*|node|nodejs|deno|ruby|perl|php|bash|sh|zsh)\b")
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_PREFIX_CMDS = frozenset({"sudo", "nohup", "time", "env", "command", "exec", "builtin", "nice",
                          "stdbuf", "xargs"})
_SKIP_VALUE_OPTS = {"timeout": 1}
_REDIRECT_RE = re.compile(r"(?<![<>&\d])(?:\d?>>?|&>>?)\s*(?!&)([^\s;&|<>()]+)")
_DEVNULL = frozenset({"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"})
_CONTENT_OPTS = frozenset({"-m", "--message", "--body", "-b", "--title", "-t", "--description",
                           "--notes", "--note", "--comment", "--subject", "--text", "--content"})
_FIELD_OPTS = frozenset({"-f", "-F", "--field", "--raw-field"})
_API_VALUE_OPTS = frozenset({"-X", "--method", "-H", "--header", "-f", "-F", "--field", "--raw-field",
                             "--jq", "-q", "--template", "-t", "--input", "--hostname", "--cache", "-p",
                             "--preview"})
_HTTP_DATA_OPTS = frozenset({"-d", "--data", "--data-raw", "--data-binary", "--data-urlencode", "--json",
                             "-F", "--form", "--form-string", "--post-data", "--body-data"})
_FILEOP_WRITE_ALL = frozenset({"touch", "mkdir", "rm", "rmdir", "chmod", "chown", "truncate",
                               "shred", "unlink"})
_FILEOP_COPY = frozenset({"cp", "rsync", "scp", "install", "ln"})
_OPENERS = frozenset({"xdg-open", "firefox", "firefox-esr", "google-chrome", "google-chrome-stable",
                      "chromium", "chromium-browser", "open", "sensible-browser", "x-www-browser",
                      "eog", "feh", "evince", "okular"})
_RUNNERS = frozenset({"python", "python3", "python3.11", "python3.12", "node", "nodejs", "bash", "sh",
                      "zsh", "ruby", "perl", "php", "deno", "bun", "tsx", "ts-node"})
_GIT_LOCAL_WRITE = frozenset({"add", "commit", "rm", "mv", "merge", "rebase", "reset", "checkout",
                              "switch", "stash", "tag", "init", "apply", "am", "cherry-pick",
                              "restore", "revert"})
_FORGE_WRITE = frozenset({"create", "edit", "comment", "merge", "close", "reopen", "review",
                          "delete", "upload", "fork", "note", "update", "approve", "transfer",
                          "archive", "rename", "set", "add", "remove", "lock", "unlock"})
_HTTP_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_CODE_WRITE_CALL = re.compile(
    r"open\([^\n]*?['\"](?:[wax]b?\+?|[rw]\+|ab)['\"]|\.write_(?:text|bytes)\(|\.to_(?:csv|json|"
    r"parquet|excel|html)\(|\.savefig\(|writeFile(?:Sync)?\(|json\.dump\(|shutil\.(?:copy\w*|move)\(|"
    r"os\.(?:makedirs|mkdir|rename|replace|remove)\(|\.mkdir\(|\.unlink\(|\.rename\(")
_CODE_HTTP_WRITE = re.compile(
    r"(?:requests|httpx|session|s|client)\.(?:post|put|patch|delete)\(|method\s*[=:]\s*['\"]"
    r"(?:POST|PUT|PATCH|DELETE)['\"]|urlopen\(\s*(?:urllib\.request\.)?Request\([^\n]*data\s*=",
    re.I)
_CODE_READ_CALL = re.compile(
    r"open\(|\.read_(?:text|bytes)\(|read_(?:csv|json|parquet|excel|table)\(|json\.load\(|"
    r"yaml\.(?:safe_)?load\(|listdir\(|scandir\(|glob\(|iterdir\(|\.exists\(|\.is_(?:file|dir)\(|"
    r"\.stat\(|urlopen\(|Request\(|(?:requests|httpx|session|client)\.(?:get|head)\(|"
    r"\bget\(\s*[rfb]?['\"]https?|fetch\(|subprocess\.|os\.system\(|check_output\(|Popen\(|\bcurl\b|"
    r"\bwget\b|webbrowser\.open|\.goto\(|driver\.get\(|readFileSync\(|fs\.readFile\(|axios\.get\(|"
    r"sqlite3\.connect\(|load_workbook\(|Image\.open\(|imread\(|np\.load|pd\.read|copy(?:file)?\(|"
    r"\bsource\b|import_module\(", re.I)
# NAME = 'literal' or NAME = Path('literal') (optionally with a trailing comment) on a line of its own
_ASSIGN_LITERAL = re.compile(
    r"(?m)^\s*([A-Za-z_]\w*)\s*=\s*(?:Path\(|pathlib\.Path\(|os\.path\.expanduser\()?\s*[rfb]?"
    r"['\"]([^'\"\n]+)['\"]\)?\s*(?:#.*)?$")


@dataclass
class Touch:
    """One raw touch: `ref` is a refs.py ref (or the focus ref for GUI writes).

    `via` says how a GUI write found its artifact in rules v2: "" (in-session focus, or not a GUI
    write), "carry" (the focus the agent's previous session ended with), "narrative" (an artifact
    the agent named in its own words just before), "gui-shell" (a command typed into a terminal
    window and parsed as bash).
    """

    ref: str
    mode: str
    rule: str
    container_level: bool = False
    via: str = ""


@dataclass
class AgentState:
    """Per-agent state carried across sessions: local directory -> remote repository ref."""

    remotes: dict[str, str] = field(default_factory=dict)
    repo_roots: set[str] = field(default_factory=set)
    last_focus: str | None = None          # GUI focus at the end of the agent's previous session
    last_focus_ts: float | None = None

    def remote_of(self, path_ref: str | None) -> str | None:
        """The remote of a local directory, walking up to the nearest mapped ancestor."""
        if not path_ref or not path_ref.startswith("path:"):
            return None
        p = path_ref[5:]
        while p and p not in ("/", "~", "."):
            r = self.remotes.get(p)
            if r:
                return r
            p = posixpath.dirname(p)
        return None


@dataclass
class SessionState:
    cwd: str = "~"
    focus: str | None = None
    gui_writes_unattributed: int = 0
    gui_writes: int = 0
    reclassify_xdotool: bool = False      # rules v2: classify xdotool-typed text like GUI-typed text
    gui_nondoc: int = 0                   # xdotool inputs that are not document writes (rules v2)


def split_heredocs(cmd: str) -> tuple[str, list[tuple[str, str]]]:
    """The script with heredoc bodies removed, and (opener line, body) pairs."""
    lines = cmd.split("\n")
    keep: list[str] = []
    bodies: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        keep.append(line)
        markers = [m.group(2) for m in _HEREDOC_RE.finditer(line)]
        i += 1
        for mk in markers:
            body: list[str] = []
            while i < len(lines) and lines[i].strip() != mk:
                body.append(lines[i])
                i += 1
            i += 1  # the terminator line
            bodies.append((line, "\n".join(body)))
    return "\n".join(keep), bodies


MAX_QUOTE = 20_000  # a quote that does not close within this many characters is a literal


def scan_segments(script: str) -> list[tuple[str, str]]:
    """Simple commands of a script as (text, mask) pairs.

    Commands end at newlines, `;`, `&&`, `||` and `|` outside quotes; a quoted string may span lines
    (multi-line `-c` code, commit messages, request bodies). `mask` has the same length as `text`
    with every character inside quotes replaced by `_`, so redirections are found only outside
    quotes. Comments are dropped. A quote that never closes (or closes only after MAX_QUOTE
    characters) is read as a literal character.
    """
    segs: list[tuple[str, str]] = []
    buf: list[str] = []
    mbuf: list[str] = []
    q: str | None = None
    i, n = 0, len(script)

    def flush() -> None:
        t, m = "".join(buf), "".join(mbuf)
        lo = len(m) - len(m.lstrip())
        hi = len(m.rstrip())
        if hi > lo:
            segs.append((t[lo:hi], m[lo:hi]))
        buf.clear()
        mbuf.clear()

    while i < n:
        ch = script[i]
        if q is not None:
            if q == '"' and ch == "\\" and i + 1 < n:
                buf.append(script[i:i + 2])
                mbuf.append("__")
                i += 2
                continue
            if ch == q:
                q = None
                mbuf.append(ch)
            else:
                mbuf.append(" " if ch == "\n" else "_")
            buf.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            if script[i + 1] == "\n":       # line continuation
                buf.append("  ")
                mbuf.append("  ")
            else:
                buf.append(script[i:i + 2])
                mbuf.append(script[i:i + 2])
            i += 2
            continue
        if ch in "'\"":
            j = script.find(ch, i + 1)
            if j < 0 or j - i > MAX_QUOTE:
                buf.append(ch)
                mbuf.append("_")
            else:
                q = ch
                buf.append(ch)
                mbuf.append(ch)
            i += 1
            continue
        if ch == "#" and (not mbuf or mbuf[-1][-1:] in (" ", "\t", ";", "&", "|", "(")):
            j = script.find("\n", i)
            i = n if j < 0 else j
            continue
        if ch == "\n":
            flush()
            i += 1
            continue
        if ch in ";|&":
            prev = mbuf[-1][-1:] if mbuf else ""
            nxt = script[i + 1] if i + 1 < n else ""
            if (ch == "&" and nxt == ">") or (ch == "|" and prev == ">") or (ch == "&" and prev in ("<", ">")):
                buf.append(ch)
                mbuf.append(ch)
                i += 1
                continue
            flush()
            i += 2 if script[i:i + 2] in ("&&", "||") else 1
            continue
        buf.append(ch)
        mbuf.append(ch)
        i += 1
    flush()
    return segs


def split_segments(script: str) -> list[str]:
    """Simple commands of a script (see `scan_segments`)."""
    return [t for t, _ in scan_segments(script)]


def _tokens(seg: str) -> list[str]:
    try:
        return shlex.split(seg, comments=False, posix=True)
    except ValueError:
        return seg.split()


def _strip_prefix(tokens: list[str]) -> list[str]:
    """Drop env assignments and wrapper commands (sudo, nohup, timeout N, ...)."""
    i = 0
    while i < len(tokens):
        t = tokens[i]
        base = t.rsplit("/", 1)[-1]
        if _ENV_ASSIGN.match(t) and not t.startswith("="):
            i += 1
        elif base in _PREFIX_CMDS:
            i += 1
            while i < len(tokens) and tokens[i].startswith("-"):
                i += 1
        elif base in _SKIP_VALUE_OPTS:
            i += 1
            while i < len(tokens) and tokens[i].startswith("-"):
                i += 1
            i += _SKIP_VALUE_OPTS[base]
        else:
            break
    return tokens[i:]


def _clean_path_token(t: str) -> str | None:
    """A path-like token cut before globs and variables; None when nothing usable is left."""
    t = t.strip().strip("\"'`").rstrip(",;")
    if "=" in t and not t.startswith(("/", "~", ".", "$")):
        t = t.split("=", 1)[1]
    t = re.sub(r"^\$\{?HOME\}?(?=/|$)", "~", t)
    m = re.search(r"[*?\[{$`]", t)
    if m:
        t = posixpath.dirname(t[:m.start()]) if "/" in t[:m.start()] else ""
    if not t or t.startswith("-") or "://" in t:
        return None
    return t


def resolve_path(token: str, cwd: str) -> str | None:
    """`path:` ref of a file token, relative names resolved against `cwd`."""
    t = _clean_path_token(token)
    if t is None or t in (".", "..", "~"):
        return None
    if t.startswith(AGENT_HOME):
        t = "~" + t[len(AGENT_HOME):]
    if not t.startswith(("/", "~")):
        if not re.match(r"^[\w.\-+@%/~]+$", t):
            return None
        t = posixpath.join(cwd, t)
    if t.startswith("~"):
        t = "~" + posixpath.normpath("/" + t[1:].lstrip("/"))
        if t == "~/":
            return None
    try:
        return normalize_path(t)
    except Exception:  # noqa: BLE001
        return None


def _new_cwd(arg: str | None, cwd: str) -> str:
    if not arg or arg == "~":
        return "~"
    if arg == "-":
        return cwd
    t = re.sub(r"^\$\{?HOME\}?(?=/|$)", "~", arg.strip("\"'"))
    if t.startswith(AGENT_HOME):
        t = "~" + t[len(AGENT_HOME):]
    if "$" in t or "`" in t:
        return cwd
    if t.startswith("~"):
        return "~" + posixpath.normpath("/" + t[1:].lstrip("/")).rstrip("/") if t != "~" else "~"
    if t.startswith("/"):
        return posixpath.normpath(t)
    joined = posixpath.normpath(posixpath.join(cwd, t))
    return joined


def _token_refs(token: str) -> list[str]:
    """Refs inside one token (URLs and absolute or home paths)."""
    out = []
    for _, _, c in find_candidates(token):
        r = norm_ref(c)
        if r:
            out.append(r)
    return out


def _forge_target(tool: str, toks: list[str]) -> list[str]:
    """Repository refs named by a gh or glab command (-R/--repo, repo <sub> X, api X)."""
    refs: list[str] = []
    for i, t in enumerate(toks):
        val = None
        if t in ("-R", "--repo") and i + 1 < len(toks):
            val = toks[i + 1]
        elif t.startswith("--repo="):
            val = t.split("=", 1)[1]
        if val:
            r = _command_ref(f"{tool} x -R {val}") if not val.startswith("http") else norm_ref(val)
            if r:
                refs.append(r)
    if len(toks) >= 3 and toks[1] == "repo" and not toks[2].startswith("-"):
        for t in toks[3:]:
            if t.startswith("-"):
                continue
            r = norm_ref(t) if t.startswith("http") else _command_ref(f"{tool} repo view {t}")
            if r:
                refs.append(r)
            break
    if len(toks) >= 3 and toks[1] == "api":
        skip = False
        for t in toks[2:]:
            if skip:
                skip = False
                continue
            if t in _API_VALUE_OPTS:
                skip = True
                continue
            if t.startswith("-"):
                continue
            r = _command_ref(f"{tool} api {t}")
            if r:
                refs.append(r)
            break
    return refs


def _http_method(toks: list[str]) -> tuple[bool, list[str], list[str], set[int]]:
    """(is_write, local files written, local files read, indices of body tokens) for curl, wget or
    httpie tokens."""
    write = False
    outs: list[str] = []
    ins: list[str] = []
    body: set[int] = set()
    cmd = toks[0]
    i = 1
    while i < len(toks):
        t = toks[i]
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        if t in ("-X", "--request", "--method"):
            write |= nxt.upper() in _HTTP_WRITE_METHODS
            i += 2
            continue
        if t.startswith("-X") and len(t) > 2:
            write |= t[2:].upper() in _HTTP_WRITE_METHODS
        elif t.startswith("--request="):
            write |= t.split("=", 1)[1].upper() in _HTTP_WRITE_METHODS
        elif t in _HTTP_DATA_OPTS or t in ("--post-file", "--body-file"):
            write = True
            if t in _HTTP_DATA_OPTS:
                body.add(i + 1)
            if nxt.startswith("@"):
                ins.append(nxt[1:])
            elif "=@" in nxt:
                ins.append(nxt.split("=@", 1)[1].split(";")[0])
            elif t in ("--post-file", "--body-file"):
                ins.append(nxt)
            i += 2
            continue
        elif t in ("-T", "--upload-file") and cmd == "curl":
            write = True
            ins.append(nxt)
            i += 2
            continue
        elif t.startswith(("--data=", "--data-raw=", "--json=", "--post-data=")):
            write = True
            body.add(i)
        elif t in ("-D", "--dump-header") and nxt and nxt != "-" and not nxt.startswith("-"):
            outs.append(nxt)
            i += 2
            continue
        elif t in ("-o", "--output", "-O", "--output-document") and nxt and not nxt.startswith("-"):
            if not (cmd == "curl" and t == "-O"):
                outs.append(nxt)
                i += 2
                continue
        elif t.startswith("--output="):
            outs.append(t.split("=", 1)[1])
        elif cmd in ("http", "https", "httpie") and i == 1 and t.upper() in _HTTP_WRITE_METHODS:
            write = True
        i += 1
    return write, outs, ins, body


def _uses(var: str | None, lines: list[str]) -> bool:
    """True when variable `var` appears in any of `lines`."""
    return bool(var) and any(re.search(rf"\b{re.escape(var)}\b", ln) for ln in lines)


def _code_touches(code: str) -> list[Touch]:
    """Touches from code (heredoc body or -c string).

    A path or URL on a line with a write call (or held in a variable that a write line uses) is
    written; one on a line with a read or fetch call (or held in a variable that such a line uses)
    is read; any other path or URL in code (string templates, HTML, comments) is a mention.
    """
    out: list[Touch] = []
    lines = code.split("\n")
    writers = [ln for ln in lines if _CODE_WRITE_CALL.search(ln) or _CODE_HTTP_WRITE.search(ln)]
    readers = [ln for ln in lines if _CODE_READ_CALL.search(ln)]
    assigned = {m.group(2): m.group(1) for m in _ASSIGN_LITERAL.finditer(code)}
    seen: set[tuple[str, str]] = set()
    for ln in lines:
        cands = find_candidates(ln)
        if not cands:
            continue
        line_writes = bool(_CODE_WRITE_CALL.search(ln) or _CODE_HTTP_WRITE.search(ln))
        line_reads = bool(_CODE_READ_CALL.search(ln))
        for _, _, c in cands:
            r = norm_ref(c)
            if not r:
                continue
            var = assigned.get(c.strip("\"'"))
            if line_writes or _uses(var, writers):
                mode, rule = WRITE, "B-code-write"
            elif line_reads or _uses(var, readers):
                mode, rule = READ, "B-code-read"
            else:
                mode, rule = MENTION, "B-content"
            key = (r, mode)
            if key not in seen:
                seen.add(key)
                out.append(Touch(r, mode, rule))
    return out


def parse_bash(cmd: str, sess: SessionState, agent: AgentState,
               output_refs: Sequence[str] = ()) -> list[Touch]:
    """Touches of one bash command. Updates the session's cwd and focus and the agent's map."""
    touches: list[Touch] = []
    script, bodies = split_heredocs(cmd)
    for opener, body in bodies:
        if _CODE_INTERP.search(opener.split("<<", 1)[0]):
            touches += _code_touches(body)
        else:
            touches += [Touch(r, MENTION, "B-content") for r in text_refs(body)]
    for seg, mseg in scan_segments(script):
        toks = _strip_prefix(_tokens(seg))
        if not toks:
            continue
        name = toks[0].rsplit("/", 1)[-1]
        cwd = sess.cwd
        handled: set[int] = set()

        def add_tok(i: int, mode: str, rule: str, container: bool = False, toks: list[str] = toks,
                    cwd: str = cwd, handled: set[int] = handled, touches: list[Touch] = touches) -> None:
            handled.add(i)
            r = resolve_path(toks[i], cwd) if not re.search(r"://|^www\.|^git@", toks[i]) else None
            refs = [r] if r else _token_refs(toks[i])
            for x in refs:
                touches.append(Touch(x, mode, rule, container))

        # redirections outside quotes (also inside other commands)
        for m in _REDIRECT_RE.finditer(mseg):
            tgt = seg[m.start(1):m.end(1)].strip("\"'")
            if tgt in _DEVNULL or tgt.startswith("&"):
                continue
            r = resolve_path(tgt, cwd)
            if r:
                touches.append(Touch(r, WRITE, "B-redirect"))
            for k, t in enumerate(toks):
                if t == tgt or t.endswith(">" + tgt) or t.endswith(">>" + tgt):
                    handled.add(k)
        args = [(k, t) for k, t in enumerate(toks) if k > 0]
        nonopt = [(k, t) for k, t in args if not t.startswith("-") and k not in handled
                  and t not in (">", ">>", "2>", "&>", "2>&1", "|")]
        if name in ("cd", "pushd"):
            target = nonopt[0][1] if nonopt else None
            sess.cwd = _new_cwd(target, cwd)
            r = resolve_path(sess.cwd, "~")
            if r:
                touches.append(Touch(r, READ, "B-cd", True))
            continue
        if name == "tee":
            for k, _ in nonopt:
                add_tok(k, WRITE, "B-redirect")
        elif name in ("sed", "perl") and any(t == "-i" or t.startswith("-i") or t == "--in-place"
                                             for _, t in args):
            has_e = any(t in ("-e", "--expression") for _, t in args)
            files = nonopt if has_e else nonopt[1:]
            for k, _ in files:
                add_tok(k, WRITE, "B-inplace")
        elif name in _FILEOP_WRITE_ALL:
            recursive = any(re.match(r"^-[a-zA-Z]*[rR]", t) or t == "--recursive" for _, t in args)
            is_dir = name in ("mkdir", "rmdir") or (name == "rm" and recursive)
            for k, _ in nonopt:
                add_tok(k, WRITE, "B-fileop", is_dir)
        elif name in _FILEOP_COPY or name == "mv":
            recursive = any(re.match(r"^-[a-zA-Z]*[rRa]", t) or t in ("--recursive", "--archive")
                            for _, t in args)
            if len(nonopt) >= 2:
                for k, _ in nonopt[:-1]:
                    add_tok(k, WRITE if name == "mv" else READ,
                            "B-fileop" if name == "mv" else "B-fileop-src")
                add_tok(nonopt[-1][0], WRITE, "B-fileop", recursive and name != "mv")
        elif name in ("unzip", "tar"):
            for i2, (k, t) in enumerate(args):
                if t in ("-d", "-C", "--directory") and i2 + 1 < len(args):
                    add_tok(args[i2 + 1][0], WRITE, "B-fileop", True)
            create = name == "tar" and any(re.match(r"^-?[a-zA-Z]*c", t) for _, t in args[:1])
            for k, t in nonopt:
                if k in handled:
                    continue
                add_tok(k, WRITE if create and k == nonopt[0][0] else READ,
                        "B-fileop" if create and k == nonopt[0][0] else "B-fileop-src")
        elif name == "git":
            touches += _parse_git(toks, sess, agent, output_refs)
            continue
        elif name in ("gh", "glab"):
            touches += _parse_forge(name, toks, sess, agent)
            continue
        elif name in ("curl", "wget", "http", "https", "httpie", "xh"):
            write, outs, ins, body = _http_method(toks)
            for k in body:
                if k < len(toks):
                    touches += [Touch(x, MENTION, "B-content") for x in text_refs(toks[k])]
                    handled.add(k)
            for k, t in args:
                if k in handled:
                    continue
                if re.search(r"://|^www\.", t):
                    for x in _token_refs(t):
                        touches.append(Touch(x, WRITE if write else READ,
                                             "B-http-write" if write else "B-http-read"))
                    handled.add(k)
            for f in outs:
                r = resolve_path(f, cwd)
                if r:
                    touches.append(Touch(r, WRITE, "B-download"))
            for f in ins:
                r = resolve_path(f, cwd)
                if r:
                    touches.append(Touch(r, READ, "B-upload-src"))
            for k, t in args:
                if k not in handled and t in outs + ins:
                    handled.add(k)
        elif name in _OPENERS:
            for k, t in nonopt:
                refs = _token_refs(t) or ([resolve_path(t, cwd)] if resolve_path(t, cwd) else [])
                for x in refs:
                    touches.append(Touch(x, READ, "B-open"))
                    if not x.startswith("path:"):
                        sess.focus = x
                handled.add(k)
        elif name == "xdotool":
            sub = toks[1] if len(toks) > 1 else ""
            keys = " ".join(toks[2:]).lower()
            if sub == "type" or (sub == "key" and any(kk in keys for kk in GUI_WRITE_KEYS)):
                if sub == "type" and sess.reclassify_xdotool and \
                        classify_typed(xdotool_text(toks[2:])) in NOT_DOCUMENT:
                    sess.gui_nondoc += 1
                    continue
                sess.gui_writes += 1
                if sess.focus:
                    touches.append(Touch(sess.focus, WRITE, "B-xdotool"))
                else:
                    sess.gui_writes_unattributed += 1
            continue
        elif name in ("echo", "printf"):
            for k, t in args:
                if k not in handled:
                    for x in _token_refs(t):
                        touches.append(Touch(x, MENTION, "B-content"))
            continue
        elif name in _RUNNERS:
            code_flag = next((i2 for i2, (_, t) in enumerate(args) if t in ("-c", "-e", "--eval")), None)
            if code_flag is not None and code_flag + 1 < len(args):
                touches += _code_touches(args[code_flag + 1][1])
                handled.add(args[code_flag + 1][0])
            elif nonopt and nonopt[0][1] != "-":
                add_tok(nonopt[0][0], READ, "B-run")
        elif toks[0].startswith("./") or (toks[0].startswith(("~/", "/")) and name.endswith((".sh", ".py"))):
            r = resolve_path(toks[0], cwd)
            if r:
                touches.append(Touch(r, READ, "B-run"))
            handled.add(0)
        # remaining tokens: content options are mentions, everything else is read
        skip_next = False
        for k, t in args:
            if skip_next:
                skip_next = False
                for x in _token_refs(t):
                    touches.append(Touch(x, MENTION, "B-content"))
                continue
            if t in _CONTENT_OPTS:
                skip_next = True
                continue
            if k in handled:
                continue
            for x in _token_refs(t):
                touches.append(Touch(x, READ, "B-other"))
    return touches


_XDO_VALUE_OPTS = frozenset({"--delay", "--window", "--repeat", "--repeat-delay", "--terminator", "--file", "--args"})


def xdotool_text(args: list[str]) -> str:
    """The text of `xdotool type [options] TEXT...`."""
    out: list[str] = []
    skip = False
    for a in args:
        if skip:
            skip = False
        elif a in _XDO_VALUE_OPTS:
            skip = True
        elif a.startswith("--"):
            continue
        else:
            out.append(a)
    return " ".join(out)


def xdotool_inputs(cmd: str) -> list[tuple[str, str]]:
    """(subcommand, typed text) of every xdotool input in a bash command, in the order parse_bash counts them."""
    out = []
    script, _ = split_heredocs(cmd)
    for seg, _m in scan_segments(script):
        toks = _strip_prefix(_tokens(seg))
        if not toks or toks[0].rsplit("/", 1)[-1] != "xdotool":
            continue
        sub = toks[1] if len(toks) > 1 else ""
        keys = " ".join(toks[2:]).lower()
        if sub == "type":
            out.append(("type", xdotool_text(toks[2:])))
        elif sub == "key" and any(kk in keys for kk in GUI_WRITE_KEYS):
            out.append(("key", ""))
    return out


def _repo_dir(toks: list[str], cwd: str) -> str:
    """Working directory of a git command (-C dir or the cwd)."""
    for i, t in enumerate(toks[:-1]):
        if t == "-C":
            return _new_cwd(toks[i + 1], cwd)
    return cwd


def _parse_git(toks: list[str], sess: SessionState, agent: AgentState,
               output_refs: Sequence[str]) -> list[Touch]:
    out: list[Touch] = []
    i = 1
    while i < len(toks) and toks[i].startswith("-"):
        i += 2 if toks[i] in ("-C", "-c", "--git-dir", "--work-tree") else 1
    if i >= len(toks):
        return out
    sub = toks[i]
    rest = toks[i + 1:]
    wd = _repo_dir(toks, sess.cwd)
    wd_ref = resolve_path(wd, "~")
    remote = agent.remote_of(wd_ref)
    if wd_ref and sub not in ("clone", "config", "--version", "version", "help"):
        agent.repo_roots.add(wd_ref[5:])
    if sub == "clone":
        args = [t for t in rest if not t.startswith("-")]
        # options with values (--depth N, -b BRANCH, --branch X)
        vals: set[str] = set()
        for k, t in enumerate(rest[:-1]):
            if t in ("--depth", "-b", "--branch", "--origin", "-o", "--reference", "--config", "-c",
                     "--filter", "--jobs", "-j", "--shallow-since", "--template"):
                vals.add(rest[k + 1])
        args = [t for t in args if t not in vals]
        if not args:
            return out
        url = args[0]
        rref = norm_ref(url)
        if rref is None and "/" in url and not url.startswith((".", "/", "~")):
            rref = norm_ref("https://github.com/" + url)
        name = posixpath.basename(url.rstrip("/")).removesuffix(".git")
        dest = args[1] if len(args) > 1 else name
        dref = resolve_path(dest, sess.cwd) if dest else None
        if rref:
            out.append(Touch(rref, READ, "B-git-remote-read", True))
        if dref:
            out.append(Touch(dref, WRITE, "B-git-clone-dir", True))
            agent.repo_roots.add(dref[5:])
            if rref:
                agent.remotes[dref[5:]] = _repo_container_ref(rref)
        return out
    if sub == "remote" and len(rest) >= 3 and rest[0] in ("add", "set-url"):
        rref = norm_ref(rest[-1])
        if rref and wd_ref:
            agent.remotes[wd_ref[5:]] = rref
        return out
    if sub == "push":
        if wd_ref:
            out.append(Touch(wd_ref, READ, "B-git-read", True))
        named = [norm_ref(t) for t in rest if re.search(r"://|^git@", t)]
        named = [r for r in named if r]
        from_output = [r for r in output_refs if r.startswith(("github:", "gitlab:", "gitlab-pid:"))]
        targets = named or from_output or ([remote] if remote else [])
        for r in dict.fromkeys(targets):
            out.append(Touch(_repo_container_ref(r), WRITE, "B-git-push", True))
        if wd_ref and len(set(map(_repo_container_ref, targets))) == 1 and not remote:
            agent.remotes[wd_ref[5:]] = _repo_container_ref(targets[0])
        return out
    if sub in ("pull", "fetch"):
        if remote:
            out.append(Touch(remote, READ, "B-git-remote-read", True))
        if sub == "pull" and wd_ref:
            out.append(Touch(wd_ref, WRITE, "B-git-local", True))
        return out
    if sub in _GIT_LOCAL_WRITE:
        if wd_ref:
            out.append(Touch(wd_ref, WRITE, "B-git-local", True))
        files = [t for t in rest if not t.startswith("-") and t not in (".", "--")]
        if sub in ("add", "rm", "mv", "restore") and files:
            for t in files:
                r = resolve_path(t, wd)
                if r:
                    out.append(Touch(r, WRITE, "B-git-local"))
        msg_next = False
        for t in rest:
            if msg_next:
                out += [Touch(x, MENTION, "B-content") for x in text_refs(t)]
                msg_next = False
            elif t in ("-m", "--message", "-F"):
                msg_next = t != "-F"
        return out
    if wd_ref:
        out.append(Touch(wd_ref, READ, "B-git-read", True))
    return out


def _repo_container_ref(r: str) -> str:
    """owner/repo part of a github/gitlab ref; other refs unchanged."""
    if r.startswith(("github:", "gitlab:")):
        forge, rest = r.split(":", 1)
        return f"{forge}:{'/'.join(rest.split('/')[:2])}"
    if r.startswith("gitlab-pid:"):
        return r.split("/", 1)[0]
    return r


def _parse_forge(tool: str, toks: list[str], sess: SessionState, agent: AgentState) -> list[Touch]:
    out: list[Touch] = []
    sub = [t for t in toks[1:4] if not t.startswith("-")]
    verb = sub[1] if len(sub) > 1 else (sub[0] if sub else "")
    is_api = bool(sub) and sub[0] == "api"
    write = False
    if is_api:
        for k, t in enumerate(toks):
            nxt = toks[k + 1] if k + 1 < len(toks) else ""
            if t in ("-X", "--method") and nxt.upper() in _HTTP_WRITE_METHODS:
                write = True
            elif t.startswith("--method=") and t.split("=", 1)[1].upper() in _HTTP_WRITE_METHODS:
                write = True
            elif t.startswith("-X") and t[2:].upper() in _HTTP_WRITE_METHODS:
                write = True
            elif t in ("-f", "-F", "--field", "--raw-field", "--input"):
                write = True
    else:
        write = verb in _FORGE_WRITE
    if sub and sub[0] == "repo" and verb == "clone":
        args = [t for t in toks[3:] if not t.startswith("-") and t != "--"]
        if args:
            rref = _command_ref(f"{tool} repo view {args[0]}") if not args[0].startswith("http") else norm_ref(args[0])
            dest = args[1] if len(args) > 1 else posixpath.basename(args[0].rstrip("/")).removesuffix(".git")
            dref = resolve_path(dest, sess.cwd)
            if rref:
                out.append(Touch(rref, READ, "B-git-remote-read", True))
            if dref:
                out.append(Touch(dref, WRITE, "B-git-clone-dir", True))
                agent.repo_roots.add(dref[5:])
                if rref:
                    agent.remotes[dref[5:]] = _repo_container_ref(rref)
        return out
    refs = _forge_target(tool, toks)
    content_vals = {k + 1 for k, t in enumerate(toks[:-1]) if t in _CONTENT_OPTS or t in _FIELD_OPTS}
    content_vals |= {k for k, t in enumerate(toks) if t.startswith(("--field=", "--raw-field=", "--body=",
                                                                    "--title="))}
    for k, t in enumerate(toks):
        if k > 0 and k not in content_vals and re.search(r"://|^www\.", t):
            refs += _token_refs(t)
    if not refs:
        wd_ref = resolve_path(sess.cwd, "~")
        remote = agent.remote_of(wd_ref)
        if remote:
            refs = [remote]
    rule = "B-forge-write" if write else "B-forge-read"
    for r in dict.fromkeys(refs):
        out.append(Touch(r, WRITE if write else READ, rule, r == _repo_container_ref(r)))
    # bodies, titles and API fields are content
    for k in sorted(content_vals):
        if k < len(toks):
            out += [Touch(x, MENTION, "B-content") for x in text_refs(toks[k])]
    return out


_NAV_RE = re.compile(r"^\s*(?:https?://\S+|www\.\S+|(?:[\w-]+\.)+[a-z]{2,}(?:/\S*)?)\s*$", re.I)


def is_navigation(text: str | None) -> bool:
    """Typed text that is one URL (address-bar navigation)."""
    if not text or "\n" in text.strip() or len(text) > 2000:
        return False
    return bool(_NAV_RE.match(text))


def nav_ref(text: str) -> str | None:
    t = text.strip()
    if not re.match(r"(?i)^https?://", t):
        t = "https://" + t
    return norm_ref(t)


def _turn_ts(t: dict[str, Any]) -> float | None:
    v = t.get("ts")
    if v is None and t.get("created_at") is not None:
        v = t["created_at"].timestamp()
    return v


def session_touches(turns: Iterable[dict[str, Any]], agent: AgentState, rules: str | GuiRules = "v1"
                    ) -> tuple[list[tuple[int, Touch]], dict[str, int]]:
    """Touches of one session's turns, in order.

    Each turn is a dict with `action` (action_name), `cmd`, `text`, `content`, `description`,
    `query`, `goal` (helper request), `obs` (refs from tool output and error, list), `msg`
    (refs from the provider response, list) and `ts` or `created_at`. Returns (turn index, Touch)
    pairs and counters. `rules` picks a rule version (RULE_SETS); v1 is the original D2 draft.
    Sessions of one agent must come in start order with the same `agent`, because rules v2 carry
    the GUI focus over from the agent's previous session.
    """
    gr = RULE_SETS[rules] if isinstance(rules, str) else rules
    sess = SessionState()
    out: list[tuple[int, Touch]] = []
    turns = list(turns)
    stats = {"gui_writes": 0, "gui_writes_unattributed": 0, "gui_via_carry": 0, "gui_via_narrative": 0,
             "gui_shell": 0, "gui_search": 0, "gui_input": 0, "gui_nav_extra": 0, "gui_click_nonwrite": 0}
    sess.reclassify_xdotool = gr.reclassify
    s_ts = _turn_ts(turns[0]) if turns else None
    carry = None
    if gr.carry_gap_min is not None and agent.last_focus and agent.last_focus_ts is not None \
            and s_ts is not None and (s_ts - agent.last_focus_ts) / 60.0 <= gr.carry_gap_min:
        carry = agent.last_focus
    narr: list[tuple[int, list[str]]] = []
    addr_at = -99
    prog_at = -99            # last turn whose provider response names a game or a terminal

    def gui_write(i: int, rule: str) -> None:
        stats["gui_writes"] += 1
        if sess.focus:
            out.append((i, Touch(sess.focus, WRITE, rule)))
            return
        unfocused(i, rule)

    def unfocused(i: int, rule: str) -> None:
        """A GUI write without an in-session focus: carry-over, then named artifact, else a gap."""
        if carry:
            stats["gui_via_carry"] += 1
            out.append((i, Touch(carry, WRITE, rule, via="carry")))
            return
        if gr.narrative_window is not None:
            named = [r for j, rs in narr if j >= i - gr.narrative_window for r in rs]
            if named:
                stats["gui_via_narrative"] += 1
                out.append((i, Touch(named[-1], WRITE, rule, via="narrative")))
                return
        stats["gui_writes_unattributed"] += 1

    for i, t in enumerate(turns):
        a = t.get("action")
        obs = list(t.get("obs") or [])
        msg = list(t.get("msg") or [])
        narr.append((i, [r for r in msg if not r.startswith("path:")]))
        if int(t.get("kw") or 0) & PROGRAM_KW_BITS:
            prog_at = i
        before = len(out)
        if a == "bash" and t.get("cmd"):
            w0, u0 = sess.gui_writes, sess.gui_writes_unattributed
            for x in parse_bash(t["cmd"], sess, agent, obs):
                out.append((i, x))
            # xdotool input: parse_bash counts it and touches the in-session focus if there is one
            stats["gui_writes"] += sess.gui_writes - w0
            for _ in range(sess.gui_writes_unattributed - u0):
                unfocused(i, "B-xdotool")
        elif a == "type":
            txt = t.get("text") or ""
            if is_navigation(txt):
                r = nav_ref(txt)
                if r:
                    out.append((i, Touch(r, READ, "G-nav")))
                    sess.focus = r
            elif txt.strip():
                cls = ""
                in_addr = (i - addr_at) <= 3
                addr_at = -99                      # an address-bar key applies to the next typed text only
                if gr.reclassify:
                    prev = turns[i - 1] if i > 0 else {}
                    located = prev.get("action") == "get_pixel_coords_of_element"
                    pdesc = (prev.get("description") or "") if located else ""
                    nxt = turns[i + 1] if i + 1 < len(turns) else {}
                    entered = nxt.get("action") in ("key", "hold_key") and \
                        (nxt.get("text") or "").strip().lower() in ("return", "enter", "kp_enter")
                    cls = classify_typed(txt, addr_bar=in_addr, search_box=bool(SEARCH_BOX_RE.search(pdesc)),
                                         credential_box=bool(CRED_BOX_RE.search(pdesc)),
                                         entered_in_program=entered and (i - prog_at) <= 10)
                if cls == "url":
                    r = nav_ref(txt.split()[0] if len(txt.split()) <= 2 else txt)
                    if r:
                        stats["gui_nav_extra"] += 1
                        out.append((i, Touch(r, READ, "G-nav")))
                        sess.focus = r
                    else:
                        stats["gui_input"] += 1
                elif cls == "shell" and gr.shell_as_bash:
                    stats["gui_shell"] += 1
                    for x in parse_bash(txt, sess, agent, obs):
                        x.via = "gui-shell"
                        out.append((i, x))
                elif cls == "search":
                    stats["gui_search"] += 1
                    out += [(i, Touch(r, MENTION, "G-search")) for r in text_refs(txt)]
                    if gr.search_clears_focus and in_addr:
                        sess.focus = None
                        carry = None
                elif cls in ("credential", "short_input"):
                    stats["gui_input"] += 1
                else:
                    gui_write(i, "G-type")
                    for r in text_refs(txt):
                        out.append((i, Touch(r, MENTION, "G-content")))
        elif a in ("key", "hold_key"):
            k = (t.get("text") or "").strip().lower().replace(" ", "")
            if k in GUI_WRITE_KEYS:
                gui_write(i, "G-key")
            elif k in ADDR_KEYS:
                addr_at = i
        elif a in CLICK_ACTIONS:
            addr_at = -99
            prev = turns[i - 1] if i > 0 else None
            if prev is not None and prev.get("action") == "get_pixel_coords_of_element" \
                    and WRITE_VERB_RE.search(prev.get("description") or ""):
                if is_write_button(prev.get("description"), strict=gr.strict_buttons):
                    gui_write(i, "G-click")
                else:
                    stats["gui_click_nonwrite"] += 1
        elif a == "send_message_back_to_chat":
            out += [(i, Touch(r, MENTION, "T-chat")) for r in text_refs(t.get("content"))]
        elif a == "search_history":
            out += [(i, Touch(r, MENTION, "T-search")) for r in text_refs(t.get("query"))]
        elif a in ("get_pixel_coords_of_element", "request_human_helper"):
            txt = t.get("description") or t.get("goal")
            out += [(i, Touch(r, MENTION, "T-other")) for r in text_refs(txt)]
        acted = {x.ref for _, x in out[before:]}
        for r in obs:
            if r not in acted:
                out.append((i, Touch(r, OBSERVED, "O-output")))
                acted.add(r)
        for r in msg:
            if r not in acted:
                out.append((i, Touch(r, MENTION, "M-message")))
                acted.add(r)
    stats["gui_input"] += sess.gui_nondoc
    end_focus = sess.focus or carry
    if end_focus and turns:
        agent.last_focus, agent.last_focus_ts = end_focus, _turn_ts(turns[-1])
    return out, stats


# --- typed text (rules v2) --------------------------------------------------------------------------------------
TEXT_CLASSES = ("shell", "credential", "url", "code", "search", "short_input", "form_field", "prose", "other")
NOT_DOCUMENT = ("shell", "credential", "url", "search", "short_input")   # not a write to a persistent document
_SHELL_HEAD = re.compile(
    r"^\s*(?:sudo\s+)?(?:cd|ls|ll|cat|echo|printf|git|python[\d.]*|pip3?|npm|npx|node|yarn|pnpm|curl|wget|mkdir|"
    r"rm|cp|mv|chmod|chown|grep|egrep|rg|find|touch|nano|vim?|code|gh|glab|export|source|bash|sh|zsh|apt|"
    r"apt-get|head|tail|less|more|wc|clear|exit|ps|kill|pkill|killall|top|htop|df|du|which|whoami|pwd|"
    r"history|unzip|zip|tar|ssh|scp|rsync|make|docker|jq|sed|awk|xdg-open|firefox|gedit|libreoffice|"
    r"soffice|xdotool|wmctrl|xclip|date|sleep|timeout|nohup|env|uv|pytest|ruby|java|javac|go|cargo|rustc|"
    r"gcc|g\+\+|ln|tee|sort|uniq|cut|diff|base64|openssl|crontab|systemctl|service|frotz|man|tree|"
    r"open|stat|file|basename|dirname|realpath|readlink|codex|claude|gemini|aider|llm|ollama|psql|sqlite3|"
    r"mysql|kubectl|terraform|aws|gcloud|firebase|netlify|vercel|wrangler|heroku|deno|bun|poetry|conda|"
    r"http|ffmpeg|convert|magick|pdftotext|playwright|chromium|google-chrome|set|unset|alias|read|"
    r"printenv|true|false|test|watch|seq|xargs|nl|tr|paste|column|md5sum|sha256sum|curlie)(?:\s|$|;|&|\|)"
    r"|^\s*[A-Za-z_][A-Za-z0-9_]*=\S*(?:\s*;|\s*&&|\s+[a-z./~]|\s*$)"
    r"|^\s*(?:for|while|until|if)\s.*;\s*(?:do|then)\b|^\s*[\w-]+\(\)\s*\{|^.*<<-?\s*['\"]?[A-Za-z_]+['\"]?\s*$")
_SHELL_PATH = re.compile(r"^\s*(?:\./|~/|/)[\w.\-/]+(?:\s|$)")
_SHELL_OPS = re.compile(r"(?:\s&&\s|\s\|\|\s|\s\|\s|\s>>?\s?[\w~./]|\$\(|`[^`]+`|\s2>&1)")
_CODE_MARKS = re.compile(
    r"\bdef \w+\(|\bimport \w|\bfrom \w+ import\b|\bfunction\s*\w*\(|\bconst \w+\s*=|\blet \w+\s*=|"
    r"\bvar \w+\s*=|=>|\breturn\b|\bclass \w+[:(\s{]|#include|console\.log|print\(|</?[a-z][a-z0-9]*[\s>]|"
    r"\{\s*$|^\s*\}|;\s*$|\bif\s*\(|\bfor\s*\(|\bwhile\s*\(|\belse\b\s*\{|\bself\.|\bdocument\.|querySelector|"
    r"\.forEach\(|\.map\(|JSON\.|^\s*[{\[]\s*\"|\"\s*:\s*[\"\d{\[tfn]", re.M)
_URLISH = re.compile(r"(?i)^(?:https?://\S+|www\.\S+|(?:[\w-]+\.)+[a-z]{2,}(?:[/:?#]\S*)?|"
                     r"(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|\d{1,3}(?:\.\d{1,3}){3})(?::\d+)?(?:/\S*)?)$")
_SPECIAL_SCHEME = re.compile(r"(?i)^(?:file|view-source|javascript|data|about|chrome|moz-extension|blob):\S*")
_FILE_EXT = frozenset({"py", "js", "ts", "sh", "md", "txt", "json", "csv", "css", "rb", "go", "rs", "c", "h",
                       "cpp", "java", "pdf", "png", "jpg", "jpeg", "gif", "svg", "zip", "gz", "tar", "log",
                       "yml", "yaml", "toml", "ini", "cfg", "env", "sql", "db", "html", "htm", "xml", "mjs",
                       "ipynb", "docx", "xlsx", "pptx", "mp4", "mp3", "wav", "z3", "z5", "z8", "sav", "qzl"})
_MAIL_SEARCH = re.compile(r"(?i)(?:^|\s)(?:from|to|cc|subject|label|is|in|has|newer_than|older_than|after|before|"
                          r"filename|owner|type):\S")
_CHESS = re.compile(r"^(?:[KQRBN]?[a-h]?[1-8]?x?[a-h][1-8](?:=[QRBN])?[+#]?|O-O(?:-O)?|[a-h][1-8][a-h][1-8][qrbn]?)$")
_GAME_LINE = re.compile(r"^[a-z0-9][a-z0-9 ,.'\-]*$")


def _is_urlish(tok: str) -> bool:
    """A URL or host; a bare file name such as `app.py` or `index.html` is not one."""
    if _SPECIAL_SCHEME.match(tok):
        return True
    if not _URLISH.match(tok):
        return False
    if re.match(r"(?i)^(?:https?://|www\.)", tok) or _LOCAL_URL.match(tok) or "/" in tok:
        return True
    return tok.rsplit(".", 1)[-1].lower() not in _FILE_EXT


_LOCAL_URL = re.compile(r"(?i)^(?:https?://)?(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|"
                        r"\d{1,3}(?:\.\d{1,3}){3})(?::\d+)?(?:/\S*)?$")
_SENTENCE = re.compile(r"[.!?:]\s|[.!?]$")
_WORD = re.compile(r"[^\W\d_]{2,}")
_CRED = re.compile(r"\[REDACTED\]|\[BLOB_REMOVED\]")


def _program_input(raw: str, lines: list[str]) -> bool:
    """Commands typed into a running program: short lower-case lines entered with a newline (game moves,
    REPL commands), several of them in one go, or chess moves."""
    if all(_CHESS.match(ln.strip()) for ln in lines) and len(lines) <= 4:
        return True
    entered = raw.rstrip(" ").endswith(("\n", "\\n")) or len(lines) > 1
    if not entered or len(lines) > 30:
        return False
    for ln in lines:
        x = ln.strip().removesuffix("\\n").strip()
        parts = [p.strip() for p in x.split(".") if p.strip()] or [x]
        if not all(_GAME_LINE.match(p) and len(p.split()) <= 6 for p in parts):
            return False
    return True


def classify_typed(text: str, addr_bar: bool = False, search_box: bool = False,
                   credential_box: bool = False, entered_in_program: bool = False) -> str:
    """Class of a typed text; the context flags come from the turns before (rules v2).

    First match wins: `shell` (a shell command line, as typed into a terminal window), `credential`
    (a scrubbed value or a located password field), `url` (a URL, a host, a local address, or a
    file:, view-source: or javascript: address), `code` (two or more code markers), `search` (a
    short query after an address-bar key or into a located search box, or mail search operators),
    `short_input` (one or two characters, one lower-case word, chess moves, or short lower-case
    commands entered with a newline, or with Return right after in a game or terminal context
    (`entered_in_program`), as typed into a game or another running program), `form_field`
    (a short single-line value), `prose` (a sentence or longer text), `other`. The first five classes
    are not writes to a persistent document (NOT_DOCUMENT).
    """
    raw = text or ""
    t = raw.strip()
    if not t:
        return "other"
    lines = [ln for ln in t.splitlines() if ln.strip()]
    words = t.split()
    body = [ln for ln in lines if not ln.lstrip().startswith("#")] or lines   # shell comments are neutral
    shell_lines = sum(1 for ln in body if _SHELL_HEAD.match(ln) or _SHELL_PATH.match(ln) or _SHELL_OPS.search(ln))
    mostly_shell = shell_lines >= max(1, math.ceil(0.5 * len(body))) and not _SENTENCE.search(body[0][-80:] + " ")
    open_quote = bool(_SHELL_HEAD.match(body[0])) and (body[0].count('"') % 2 == 1 or body[0].count("'") % 2 == 1)
    first_heredoc = bool(re.search(r"<<-?\s*['\"]?[A-Za-z_]+['\"]?\s*$", lines[0])) \
        and bool(_SHELL_HEAD.match(lines[0]))
    one_command = len(lines) == 1 and bool(_SHELL_HEAD.match(lines[0])) and len(words) <= 12 \
        and not t.endswith((".", "!", "?"))
    if (shell_lines and mostly_shell) or one_command or first_heredoc or open_quote:
        return "shell"
    if credential_box or (_CRED.search(t) and len(t) <= 40):
        return "credential"
    if len(words) <= 2 and any(_is_urlish(w.strip(",;")) for w in words):
        return "url"
    if len(_CODE_MARKS.findall(t)) >= 2:
        return "code"
    if ((addr_bar or search_box) and len(lines) == 1 and len(words) <= 12) or \
            (len(lines) == 1 and len(words) <= 8 and _MAIL_SEARCH.search(t)):
        return "search"
    if len(t) <= 2 or (len(words) == 1 and len(t) <= 12 and t.isalpha() and t.lower() == t and not addr_bar) \
            or _program_input(raw, lines) \
            or (entered_in_program and len(lines) == 1 and len(words) <= 4 and _GAME_LINE.match(t)):
        return "short_input"
    letters = len(_WORD.findall(t))
    if len(lines) == 1 and len(words) <= 4 and len(t) <= 40 and not _SENTENCE.search(t + " "):
        return "form_field"
    if letters >= 4 and (len(words) >= 5 or _SENTENCE.search(t + " ")):
        return "prose"
    return "other"


SEARCH_BOX_RE = re.compile(r"(?i)\bsearch\b")
CRED_BOX_RE = re.compile(r"(?i)\bpassword\b|\bpasscode\b|\b2fa\b|\bverification code\b|\botp\b")


# --- artifact keys ---------------------------------------------------------------------------------
NOT_ARTIFACT_HOSTS = frozenset({
    "google.com", "bing.com", "duckduckgo.com", "html.duckduckgo.com", "lite.duckduckgo.com",
    "search.yahoo.com", "yandex.com", "search.brave.com", "startpage.com", "w3.org", "schema.org",
    "sitemaps.org", "fonts.googleapis.com", "fonts.gstatic.com", "cdn.jsdelivr.net",
    "cdnjs.cloudflare.com", "unpkg.com", "example.com", "example.org", "example.net",
    "accounts.google.com", "myaccount.google.com", "securetoken.googleapis.com",
    "oauth2.googleapis.com", "identitytoolkit.googleapis.com", "creativecommons.org",
    "ogp.me", "purl.org", "xmlns.com", "json-schema.org", "gmpg.org", "rdfs.org",
})
ACCOUNT_HOSTS = frozenset({
    "mail.google.com", "calendar.google.com", "contacts.google.com", "drive.google.com",
    "docs.google.com", "studio.youtube.com", "analytics.google.com", "search.google.com",
    "myactivity.google.com", "photos.google.com", "keep.google.com", "gmail.googleapis.com",
})
_LOCAL_HOST = re.compile(r"^(?:localhost|127\.\d+\.\d+\.\d+|0\.0\.0\.0|\[::1\]|10\.\d+\.\d+\.\d+|"
                         r"192\.168\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)(?::\d+)?$")
_UNIQUE_PAGES = re.compile(r"^(?P<project>[a-z0-9][a-z0-9\-]*)-[0-9a-f]{6}\.gitlab\.io$")


@dataclass
class KeyMaps:
    """Global maps for artifact keys: GitLab project id -> project, unique Pages domain -> project."""

    gitlab_pid: dict[str, str] = field(default_factory=dict)
    pages_project: dict[str, str] = field(default_factory=dict)
    repo_roots: dict[str, frozenset[str]] = field(default_factory=dict)   # agent -> local repo roots


GENERIC_PARENTS = frozenset({
    "work", "projects", "project", "repos", "repo", "git", "github", "gitlab", "code", "src",
    "workspace", "dev", "documents", "desktop", "downloads", "sites", "clones", "tmp", "scratch",
    "apps", "tools", "builds", "build", "village", "ai-village",
})


def local_container(p: str, roots: frozenset[str] | set[str] = frozenset()) -> str:
    """Project directory of a normalised local path.

    The deepest known repository root of the agent (a clone target or a directory where it ran git)
    that contains the path; otherwise the first directory below the home directory or below a top
    root such as /tmp (`~/a/b` -> `~/a`, `/tmp/a/b` -> `/tmp/a`), one level deeper under generic
    parents such as `~/work` or `~/projects`.
    """
    if roots:
        q = p
        while q and q not in ("/", "~"):
            if q in roots:
                return q
            q = posixpath.dirname(q)
    segs = p.split("/")
    if p.startswith("~"):
        n = 2
    elif p.startswith(("/home/", "/Users/", "/mnt/", "/media/")):
        n = 4
    else:
        n = 3
    if len(segs) > n and segs[n - 1].lower() in GENERIC_PARENTS:
        n += 1
    return "/".join(segs[:n]) if len(segs) > n else p


def artifact_key(ref: str, agent: str, maps: KeyMaps | None = None) -> tuple[str, str, str] | None:
    """(key, container, kind) of a refs.py ref, or None when the ref is not an artifact.

    `kind` is gdoc, github, gitlab, url or local. Keys are private (they hold document ids,
    repository paths and file paths) and stay under data/.
    """
    maps = maps or KeyMaps()
    if ref.startswith("gdoc:"):
        doc_id = ref.rsplit(":", 1)[-1]
        k = f"gdoc:{doc_id}"
        return k, k, "gdoc"
    if ref.startswith("gitlab-pid:"):
        pid, _, sub = ref[len("gitlab-pid:"):].partition("/")
        proj = maps.gitlab_pid.get(pid)
        if proj:
            ref = f"gitlab:{proj}" + (f"/{sub}" if sub else "")
        else:
            c = f"gitlab-pid:{pid}"
            return (f"{c}/{sub}" if sub else c), c, "gitlab"
    if ref.startswith(("github:", "gitlab:")):
        forge, rest = ref.split(":", 1)
        segs = rest.split("/")
        if len(segs) < 2:
            return None  # an account, not a repository
        c = f"{forge}:{segs[0]}/{segs[1]}"
        return f"{forge}:{rest}", c, forge
    if ref.startswith("path:"):
        p = ref[5:]
        if p.startswith(("./", "../")):
            return None
        first = p.split("/")[1] if p.startswith("~/") else ""
        if first.startswith("."):
            return None  # dot directories and files under home: environment, not work
        k = f"local:{agent}:{p}"
        return k, f"local:{agent}:{local_container(p, maps.repo_roots.get(agent, frozenset()))}", "local"
    if ref.startswith(("http://", "https://")):
        u = ref.split("#", 1)[0].split("?", 1)[0]
        scheme_rest = u.split("://", 1)[1]
        host, _, path = scheme_rest.partition("/")
        host = host.lower().removeprefix("www.")
        path = path.strip("/")
        if _LOCAL_HOST.match(host):
            k = f"local:{agent}:{host}/{path}" if path else f"local:{agent}:{host}"
            return k, f"local:{agent}:{host}", "local"
        bare = host.split(":")[0]
        if bare in NOT_ARTIFACT_HOSTS or bare.endswith((".example", ".test", ".invalid")):
            return None
        pages = _pages_repo(bare, path, maps)
        if pages:
            return pages, pages, pages.split(":", 1)[0]
        if bare in ACCOUNT_HOSTS:
            k = f"local:{agent}:{bare}/{path}" if path else f"local:{agent}:{bare}"
            return k, k, "local"
        if not path:
            return None
        k = f"url:{host}/{path}"
        return k, k, "url"
    return None


def _pages_repo(host: str, path: str, maps: KeyMaps) -> str | None:
    """Repository container of a GitHub or GitLab Pages URL."""
    labels = host.split(".")
    first = path.split("/", 1)[0] if path else ""
    if len(labels) == 3 and labels[1:] == ["github", "io"]:
        owner = labels[0]
        if first and "." not in first:
            return f"github:{owner}/{first}"
        return f"github:{owner}/{owner}.github.io"
    m = _UNIQUE_PAGES.match(host)
    if m:
        return maps.pages_project.get(m.group("project"))
    if len(labels) == 3 and labels[1:] == ["gitlab", "io"]:
        group = labels[0]
        if first and "." not in first:
            return f"gitlab:{group}/{first}"
        return f"gitlab:{group}/{group}.gitlab.io"
    return None


def build_key_maps(pid_votes: Iterable[tuple[str, str]], gitlab_containers: Iterable[str],
                   min_votes: int = 2, min_share: float = 2 / 3) -> KeyMaps:
    """GitLab project id and unique Pages domain maps from observations.

    `pid_votes` holds (project id, gitlab container) pairs from turns whose action names exactly one
    project id and whose output names exactly one GitLab project. A project id maps to the project
    with at least `min_votes` votes and `min_share` of its votes. A unique Pages domain
    `<project>-<6 hex>.gitlab.io` maps to the GitLab project with that name when exactly one
    observed project has it.
    """
    from collections import Counter, defaultdict

    votes: dict[str, Counter] = defaultdict(Counter)
    for pid, cont in pid_votes:
        votes[pid][cont] += 1
    pid_map = {}
    for pid, c in votes.items():
        (best, n), tot = c.most_common(1)[0], sum(c.values())
        if n >= min_votes and n / tot >= min_share:
            pid_map[pid] = best.split(":", 1)[1]
    by_name: dict[str, set[str]] = defaultdict(set)
    for cont in gitlab_containers:
        if cont.startswith("gitlab:") and cont.count("/") == 1:
            by_name[cont.split("/", 1)[1]].add(cont)
    pages = {name: next(iter(s)) for name, s in by_name.items() if len(s) == 1}
    return KeyMaps(pid_map, pages)
