"""Rule-based fact-unit anchors for module B1 (SPEC 6.3.2). No LLM.

One call handles one line of memory text (lines are the unit of caching, see
`avsd.lineage.memory`). An anchor is a typed, normalised value plus a context
key:

- Regex anchors, extracted in this priority order, each skipping text an
  earlier one claimed: email, URL (scheme, www., forge and Google hosts, and
  bare domains with a common TLD; normalised by `avsd.events.refs.normalize_url`,
  which drops tracking, cache-buster and credential query parameters), agent
  name, phone, date, time, money, percent and number. UUIDs, hex ids, long
  alphanumeric tokens and file paths are claimed without becoming anchors, so
  digits inside them are not numbers. Ordered-list and section numbers at the
  start of a line are not numbers either.
- spaCy NER (`en_core_web_sm`) entities of type ORG, PERSON, GPE, PRODUCT,
  EVENT and WORK_OF_ART that do not overlap a regex anchor (agent names are
  regex anchors, so "Claude" is never a PERSON).
- Agent names are the `agents.parquet` names and their common short forms
  ("Opus 4.5", "Sonnet 3.7", "Gemini 2.5", "Claude Code", ...), mapped to the
  canonical lowercased name. Bare family words ("Claude", "Gemini", "GPT")
  map to `bare:<word>`.

Normalised values: URLs as refs (`github:<owner>/<repo>`, `gdoc:<type>:<id>`
or the cleaned URL); dates as `YYYY-MM-DD`, `YYYY-MM`, `--MM-DD` or
`day:<n>` ("Day 123"); times as 24-hour `HH:MM`; money as `<ISO code>:<amount>`;
percent and numbers as canonical decimals (thousands separators removed,
k/M/B expanded); entities lowercased without a leading "the" or a trailing
possessive.

Context key: the lemma of the nearest noun phrase in the anchor's sentence,
from the spaCy dependency parse. First, if the anchor modifies a noun outside
itself (nummod, quantmod, compound, amod, nmod, appos, poss: "3 days",
"56 donors", "GitHub repo"), that noun. Otherwise the head noun of a noun chunk:
a chunk that contains the anchor as a modifier wins; then a preceding chunk
separated from the anchor only by punctuation ("Balance: $120"); then the
smallest token gap, with a preceding chunk winning a tie. Heads inside a named
entity (PERSON, ORG, ...) and time-zone or am/pm tokens are skipped. Heads tagged PROPN (title-case labels)
are kept but marked, so that the caller can show a context key only when it is
also a common noun (see `avsd.lineage.memory`). No candidate gives the empty
key.

Literal presence (B1 v2, v3): `LiteralIndex` answers whether a stored value
occurs literally in a memory version even where no anchor was extracted there
(case-insensitive, whitespace-normalised, word-boundary match of the value's
surface forms; hashed values are compared with the keyed hashes of candidate
strings found by the same regexes, or of capitalised word n-grams for names).
For quantities, `LiteralIndex.quantity_adjacent` (v3) also requires the
context word next to the value (`ctx_adjacent`).

Privacy (SPEC 0.2, 6.3.2): PERSON, email and phone values are replaced by a
keyed hash (`h:` plus 16 hex digits of HMAC-SHA256 under the secret in
`<paths.interim>/b1_anchor_salt`) before they leave this module. So is every
value on a sensitive line: a line that names a credential (password, PIN,
API key, login, ...) or sits under a heading that does (the caller passes that
flag). Display helpers show URLs only as their domain plus a short hash.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import hashlib
import hmac
import math
import os
import re
import secrets
from collections.abc import Iterable, Sequence
from pathlib import Path
from urllib.parse import urlsplit

from avsd.events.refs import hash_owner, normalize_url

TYPES: tuple[str, ...] = (
    "url", "email", "phone", "date", "time", "money", "percent", "number", "agent",
    "person", "org", "gpe", "product", "event", "work_of_art",
)
TYPE_CODE: dict[str, int] = {t: i for i, t in enumerate(TYPES)}
NER_TYPES: dict[str, str] = {
    "ORG": "org", "PERSON": "person", "GPE": "gpe", "PRODUCT": "product", "EVENT": "event",
    "WORK_OF_ART": "work_of_art",
}
# A quantity value means little without its context, so the context key is part
# of the fact unit's identity. Other values identify the fact on their own.
QUANTITY_TYPES: frozenset[str] = frozenset({"time", "money", "percent", "number"})
HASHED_TYPES: frozenset[str] = frozenset({"email", "phone", "person"})
SALT_FILE = "b1_anchor_salt"
HASH_HEX = 16
MAX_PIECE_CHARS = 5000  # longer lines are split for spaCy
PROPN_MARK = "^"  # prefix of a context lemma whose head was tagged PROPN


# --- keyed hashing ---------------------------------------------------------

def load_salt(interim: str | Path) -> bytes:
    """The 32-byte secret for anchor hashes, created once (mode 600) and reused."""
    path = Path(interim) / SALT_FILE
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
    if len(salt) != 32:
        raise ValueError(f"anchor salt {path} must hold 32 bytes")
    return salt


def keyed_hash(salt: bytes, kind: str, value: str, n_hex: int = HASH_HEX) -> str:
    """`h:` + HMAC-SHA256(salt, kind NUL value) in hex, truncated to n_hex digits."""
    msg = f"{kind}\x00{value}".encode("utf-8", "surrogatepass")
    return "h:" + hmac.new(salt, msg, hashlib.sha256).hexdigest()[:n_hex]


# --- display helpers (outputs show domains and hashes only) -----------------

def url_domain(ref: str) -> str:
    """Domain of a normalised URL ref; github.io owners are masked by `hash_owner`."""
    if ref.startswith("h:"):
        return "hashed"
    if ref.startswith("github:"):
        return "github.com"
    if ref.startswith(("gitlab:", "gitlab-pid:")):
        return "gitlab.com"
    if ref.startswith("gdoc:"):
        return "docs.google.com"
    try:
        host = urlsplit(hash_owner(ref)).hostname or ""
    except ValueError:
        host = ""
    return host.removeprefix("www.") or "unknown"


def display_value(kind: str, value: str, salt: bytes) -> str:
    """Value as shown in label files: URL domain + short hash, hashes as they are."""
    if value.startswith("h:"):
        return value
    if kind == "url":
        return f"{url_domain(value)}#{keyed_hash(salt, 'url', value, 8)[2:]}"
    if kind in HASHED_TYPES:
        return keyed_hash(salt, kind, value)
    return value if len(value) <= 80 else value[:77] + "..."


# --- regexes -----------------------------------------------------------------

_EMAIL = re.compile(
    r"(?<![\w.+\-])[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}(?![\w\-])"
)
_URL = re.compile(
    r"(?<![\w@./])(?:[Hh][Tt][Tt][Pp][Ss]?://|[Ww][Ww][Ww]\.|(?:github|gitlab)\.com/"
    r"|(?:docs|drive)\.google\.com/)[^\s<>\"'`|\[\]{}]+"
)
_TLDS = (
    "com|org|net|io|app|dev|ai|co|xyz|me|site|page|gg|tv|edu|gov|uk|us|ca|info|biz|blog|tech|"
    "online|store|cloud|so|sh|to|fm|ly|link|live|world|news|social|space|website|art"
)
_BARE_DOMAIN = re.compile(
    r"(?<![\w@./\-])(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+(?:" + _TLDS + r")"
    r"(?![\w\-])(?:/[^\s<>\"'`|\[\]{}]*)?"
)
_UUID = re.compile(r"(?i)(?<![\w-])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![\w-])")
_HEX = re.compile(r"(?i)(?<![\w-])(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,}(?![\w-])")
_TOKEN = re.compile(
    r"(?<![\w\-])(?=[A-Za-z0-9_\-]*\d)(?=[A-Za-z0-9_\-]*[A-Za-z])[A-Za-z0-9_\-]{16,}(?![\w\-])"
)
_PATH = re.compile(r"(?<![\w.:/])(?:~|\.\.?)?/[\w.\-~/+@%]+")
_PHONE = re.compile(
    r"(?<![\w+\-.])(?:\+?1[\s.\-]?)?\(?[2-9]\d{2}\)?[\s.\-]\d{3}[\s.\-]\d{4}(?![\w\-])"
    r"|(?<![\w+])\+[1-9]\d{0,2}[\s.\-]?(?:\(?\d{1,4}\)?[\s.\-]){1,4}\d{2,4}(?![\w\-])"
)
_MON = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?"
    r"|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?|JAN(?:UARY)?|FEB(?:RUARY)?"
    r"|MAR(?:CH)?|APR(?:IL)?|MAY|JUNE?|JULY?|AUG(?:UST)?|SEPT?(?:EMBER)?|OCT(?:OBER)?"
    r"|NOV(?:EMBER)?|DEC(?:EMBER)?)"
)
_MONTH_NUM = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_DATE_ISO = re.compile(
    r"(?<![\d.])((?:19|20)\d{2})[-/.](0?[1-9]|1[0-2])[-/.](0?[1-9]|[12]\d|3[01])(?!\d)"
)
_DATE_US = re.compile(r"(?<![\d./])(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])/((?:19|20)?\d{2})(?![\d/])")
_DATE_MD = re.compile(
    r"\b(" + _MON + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+((?:19|20)\d{2})\b)?"
)
_DATE_DM = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(" + _MON + r")\b\.?(?:,?\s+((?:19|20)\d{2})\b)?"
)
_DATE_MY = re.compile(r"\b(" + _MON + r")\.?,?\s+((?:19|20)\d{2})\b")
_DAY_N = re.compile(r"\b[Dd]ay\s*#?\s*(\d{1,4})\b")
_TIME_HM = re.compile(
    r"(?<![\d:.])([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d(?:\.\d+)?)?(?:\s*([AaPp])\.?[Mm]\.?(?![A-Za-z]))?"
)
_TIME_H = re.compile(r"(?<![\d:.])(1[0-2]|0?[1-9])\s*([AaPp])\.?[Mm]\.?(?![A-Za-z])")
_AMOUNT = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_MULT = r"(?:\s?(k|K|m|M|bn|b|B|thousand|million|billion)(?![A-Za-z]))?"
_MONEY_SYM = re.compile(r"(?<![\w$€£¥])([$€£¥])\s?" + _AMOUNT + _MULT)
_MONEY_WORD = re.compile(
    r"(?<![\w.,])" + _AMOUNT + _MULT + r"\s?(USD|EUR|GBP|dollars?|euros?|pounds?|bucks)\b"
)
_MONEY_CODE = re.compile(r"\b(USD|EUR|GBP)\s?" + _AMOUNT + _MULT)
_PERCENT = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s?(?:%|percent\b|pct\b)")
_NUMBER = re.compile(
    r"(?<![\w.,/:$€£¥#@])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?"
    r"(?:\s?([kKMB]|thousand|million|billion)(?![A-Za-z]))?(?:st|nd|rd|th)?(?![\w]|[.,]\d)"
)
# "1. item", "2) item", "### 3.2 Heading": list and section numbers.
_LIST_LEAD = re.compile(r"[\s#*>\-+|`_]*")
_LIST_MARK = re.compile(r"[.)](?:\*\*|__)?(?:\s|$)")
_SECTION_MARK = re.compile(r"[.):]?(?:\*\*|__)?(?:\s|$)")
_CURRENCY = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "usd": "USD", "eur": "EUR",
             "gbp": "GBP", "dollar": "USD", "dollars": "USD", "bucks": "USD", "euro": "EUR",
             "euros": "EUR", "pound": "GBP", "pounds": "GBP"}
_MULTIPLIER = {"k": 1e3, "K": 1e3, "thousand": 1e3, "m": 1e6, "M": 1e6, "million": 1e6,
               "b": 1e9, "B": 1e9, "bn": 1e9, "billion": 1e9}

# A line naming a credential: every value on it is hashed.
CRED_LINE = re.compile(
    r"(?i)\b(?:pass(?:word|wd|code|phrase)s?|pwd|pins?|pin\s?codes?|secrets?|credentials?"
    r"|api[\s_\-]?keys?|access[\s_\-]?keys?|private[\s_\-]?keys?|ssh[\s_\-]?keys?"
    r"|(?:auth|access|api|bearer|refresh|github|gitlab|personal)[\s_\-]?tokens?|tokens?\s*[:=]"
    r"|2fa|mfa|otp|one[\s\-]time\s(?:code|password)|security\s(?:code|answer|question)s?"
    r"|verification\scodes?|backup\scodes?|recovery\scodes?|log[\s\-]?ins?|usernames?|user\snames?"
    r"|ssn|social\ssecurity|card\snumbers?|credit\scards?|cvv|routing\snumbers?"
    r"|account\snumbers?|iban)\b"
)
# A heading naming credentials or accounts: lines under it are sensitive.
CRED_HEADING = re.compile(
    r"(?i)\b(?:secrets?|credentials?|passwords?|passcodes?|log[\s\-]?ins?|accounts?"
    r"|auth(?:entication)?|api[\s_\-]?keys?|access|tokens?|2fa|mfa)\b"
)
_HEADING = re.compile(
    r"^[ \t]{0,3}(#{1,6})[ \t]+\S|^[ \t]*\*\*[^*\n]{1,80}\*\*:?[ \t]*$"
    r"|^[ \t]*(?=[^a-z\n]*[A-Z]{3})[A-Z0-9][A-Z0-9 &/,:()'\-]{2,59}$"
)
_HEADING_ITER = re.compile(
    r"(?m)^[ \t]{0,3}(#{1,6})[ \t]+\S.*$|^[ \t]*\*\*[^*\n]{1,80}\*\*:?[ \t]*$"
    r"|^[ \t]*(?=[^a-z\n]*[A-Z]{3})[A-Z0-9][A-Z0-9 &/,:()'\-]{2,59}$"
)


def heading_level(line: str) -> int:
    """1-6 for markdown headings, 7 for bold-only or all-caps lines, 0 otherwise."""
    m = _HEADING.match(line)
    if not m:
        return 0
    return len(m.group(1)) if m.group(1) else 7


class HeadingStack:
    """Tracks the headings above the current line; sensitive under a credential heading."""

    def __init__(self) -> None:
        self.stack: list[tuple[int, bool]] = []

    def feed(self, line: str) -> bool:
        """Update with one line; True if the line itself or a heading above it is sensitive."""
        level = heading_level(line)
        if level:
            while self.stack and self.stack[-1][0] >= level:
                self.stack.pop()
            cred = bool(CRED_HEADING.search(line))
            self.stack.append((level, cred))
            return cred or any(c for _, c in self.stack)
        return any(c for _, c in self.stack)

    def feed_text(self, text: str, end: int) -> None:
        """Advance over the headings in text[:end] (used for the shared part of an append)."""
        for m in _HEADING_ITER.finditer(text, 0, end):
            self.feed(m.group(0))


# --- agent names -------------------------------------------------------------

_BARE_FAMILIES = ("claude", "gemini", "gpt", "grok", "deepseek", "kimi", "glm", "opus", "sonnet",
                  "haiku")
_SEP = r"[\s\-_()]*"
_VERSION = re.compile(r"\d+(?:\.\d+)?")


def _name_pattern(name: str) -> str:
    """Regex for a name: flexible separators, version dots may be '-' or '_'."""
    parts = []
    for tok in re.split(r"[\s\-_]+", name.strip()):
        tok = tok.strip("()[]")
        if not tok:
            continue
        parts.append(r"[.\-_]".join(re.escape(p) for p in tok.split(".")))
    return _SEP.join(parts)


def agent_aliases(names: Iterable[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """(alias pattern, value) pairs for agent names and short forms, and the alias texts.

    The value is the canonical lowercased agent name, or `bare:<alias>` for a
    short form that several agents share ("Fine-tuned Leader", "Claude").
    """
    cand: dict[str, tuple[str, set[str]]] = {}

    def add(alias: str, canon: str) -> None:
        alias = " ".join(alias.split())
        if len(re.sub(r"[^A-Za-z0-9]", "", alias)) >= 2:
            pat = _name_pattern(alias).lower()
            cand.setdefault(pat, (alias.lower(), set()))[1].add(canon)

    for raw in names:
        canon = raw.lower()
        name = re.sub(r"^\[[^\]]*\]\s*", "", raw).strip()  # "[Temporary] Fine-tuned Leader"
        add(name, canon)
        if "(claude code)" in name.lower():
            add("Claude Code", canon)
            continue
        toks = name.split()
        low = [t.lower() for t in toks]
        if low[0] == "claude" and len(toks) == 3:
            if _VERSION.fullmatch(toks[1]):  # "Claude 3.7 Sonnet"
                add(f"{toks[2]} {toks[1]}", canon)
                add(f"{toks[1]} {toks[2]}", canon)
                add(f"{toks[0]} {toks[1]}", canon)
            else:  # "Claude Opus 4.5"
                add(f"{toks[1]} {toks[2]}", canon)
        if low[0] == "gemini" and len(toks) == 3:  # "Gemini 2.5 Pro" -> "Gemini 2.5"
            add(f"{toks[0]} {toks[1]}", canon)
    pairs = [(pat, next(iter(cs)) if len(cs) == 1 else f"bare:{alias}", alias)
             for pat, (alias, cs) in cand.items()]
    # Longest first so that "Gemini 3.1 Pro" wins over "Gemini 3".
    pairs.sort(key=lambda kv: -len(kv[0]))
    pairs += [(re.escape(b), f"bare:{b}", b) for b in _BARE_FAMILIES]
    return [(p, v) for p, v, _ in pairs], [a for _, _, a in pairs]


def compile_agent_regex(names: Iterable[str]) -> tuple[re.Pattern[str], list[str], tuple[str, ...]]:
    """One regex over all aliases (one group each), the value per group, and cheap prefilter words."""
    pairs, aliases = agent_aliases(names)
    body = "|".join(f"({p})" for p, _ in pairs)
    rx = re.compile(r"(?i)(?<![\w.])(?:" + body + r")(?![\w]|\.\d)")
    hints = {re.split(r"[\s\-_()]+", a.strip("()"))[0] for a in aliases}
    return rx, [c for _, c in pairs], tuple(sorted(h for h in hints if h))


# --- value normalisation -------------------------------------------------------

def _canon_number(s: str) -> str:
    """'1,234.50' -> '1234.5'; integers without a decimal point."""
    s = s.replace(",", "")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    s = s.lstrip("0") or "0"
    return "0" + s if s.startswith(".") else s


def _scaled(amount: str, mult: str | None) -> str:
    if not mult:
        return _canon_number(amount)
    v = float(amount.replace(",", "")) * _MULTIPLIER[mult]
    if math.isfinite(v) and v == int(v):
        return str(int(v))
    return _canon_number(f"{v:.6f}")


def _year(y: str | None) -> str | None:
    if not y:
        return None
    return y if len(y) == 4 else "20" + y


def _month(mon: str) -> int:
    return _MONTH_NUM[mon[:3].lower()]


_ENT_STRIP = " \t\"'`*_#>[](){}:;,.!?-–—|“”‘’"


def norm_entity(text: str) -> str | None:
    """Lowercased entity text without a leading 'the' or a trailing possessive."""
    s = " ".join(text.split()).strip(_ENT_STRIP)
    s = re.sub(r"(?i)^the\s+", "", s)
    s = re.sub(r"['’]s$", "", s).strip(_ENT_STRIP)
    if not (2 <= len(s) <= 80) or not any(c.isalpha() for c in s):
        return None
    return s.lower()


_ALPHA = re.compile(r"[^\W\d_]")
# Context heads inside these entities are proper names, never context keys.
_NAME_ENTS = frozenset({"PERSON", "ORG", "GPE", "NORP", "FAC", "LOC", "PRODUCT", "EVENT",
                        "WORK_OF_ART", "LAW", "LANGUAGE"})
# Dependency relations by which an anchor modifies the noun that gives its context.
_MOD_DEPS = frozenset({"nummod", "quantmod", "compound", "amod", "nmod", "appos", "poss"})
# Time-zone and meridiem tokens say nothing about which fact a value belongs to.
_CTX_STOP = frozenset({"pt", "pst", "pdt", "et", "est", "edt", "ct", "cst", "cdt", "mt", "mst", "mdt",
                       "utc", "gmt", "am", "pm"})


def _overlaps(spans: list[tuple[int, int]], s: int, e: int) -> bool:
    return any(s < b and a < e for a, b in spans)


class AnchorExtractor:
    """Extract (type, value, context key) anchors from lines of memory text."""

    def __init__(self, agent_names: Sequence[str], salt: bytes, nlp=None) -> None:
        self.salt = salt
        self.agent_rx, self.agent_canon, self.agent_hints = compile_agent_regex(agent_names)
        self.nlp = nlp

    # -- regex part ------------------------------------------------------------
    def regex_anchors(self, text: str) -> tuple[list[tuple[int, int, str, str]], list[tuple[int, int]]]:
        """Regex anchors (start, end, type, value) and all claimed spans."""
        found: list[tuple[int, int, str, str]] = []
        claimed: list[tuple[int, int]] = []

        def take(m: re.Match, kind: str | None, value: str | None) -> None:
            s, e = m.span()
            if _overlaps(claimed, s, e):
                return
            claimed.append((s, e))
            if kind and value:
                found.append((s, e, kind, value))

        has_digit = any(c.isdigit() for c in text)
        if "@" in text:
            for m in _EMAIL.finditer(text):
                take(m, "email", m.group(0).lower())
        if "." in text or "/" in text:
            for m in _URL.finditer(text):
                take(m, "url", normalize_url(m.group(0)))
            for m in _BARE_DOMAIN.finditer(text):
                if _overlaps(claimed, *m.span()):
                    continue
                take(m, "url", normalize_url(m.group(0)))
        if has_digit:
            for m in _UUID.finditer(text):
                take(m, None, None)
        low = text.lower()
        if any(h in low for h in self.agent_hints):
            for m in self.agent_rx.finditer(text):
                take(m, "agent", self.agent_canon[m.lastindex - 1])
        if not has_digit:
            return found, claimed
        for rx in (_HEX, _TOKEN, _PATH):
            for m in rx.finditer(text):
                take(m, None, None)
        for m in _PHONE.finditer(text):
            digits = re.sub(r"\D", "", m.group(0))
            if len(digits) == 11 and digits.startswith("1"):
                digits = digits[1:]
            if len(digits) >= 10:
                take(m, "phone", digits)
        for m in _DATE_ISO.finditer(text):
            take(m, "date", f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}")
        for m in _DATE_US.finditer(text):
            take(m, "date", f"{_year(m.group(3))}-{int(m.group(1)):02d}-{int(m.group(2)):02d}")
        for m in _DATE_MD.finditer(text):
            mon, day, y = _month(m.group(1)), int(m.group(2)), m.group(3)
            if 1 <= day <= 31:
                take(m, "date", f"{y}-{mon:02d}-{day:02d}" if y else f"--{mon:02d}-{day:02d}")
        for m in _DATE_DM.finditer(text):
            day, mon, y = int(m.group(1)), _month(m.group(2)), m.group(3)
            if 1 <= day <= 31:
                take(m, "date", f"{y}-{mon:02d}-{day:02d}" if y else f"--{mon:02d}-{day:02d}")
        for m in _DATE_MY.finditer(text):
            take(m, "date", f"{m.group(2)}-{_month(m.group(1)):02d}")
        for m in _DAY_N.finditer(text):
            take(m, "date", f"day:{int(m.group(1))}")
        for m in _TIME_HM.finditer(text):
            h, mi, ap = int(m.group(1)), m.group(2), m.group(3)
            if ap:
                if h > 12 or h == 0:
                    take(m, None, None)
                    continue
                h = h % 12 + (12 if ap.lower() == "p" else 0)
            take(m, "time", f"{h:02d}:{mi}")
        for m in _TIME_H.finditer(text):
            h = int(m.group(1)) % 12 + (12 if m.group(2).lower() == "p" else 0)
            take(m, "time", f"{h:02d}:00")
        for m in _MONEY_SYM.finditer(text):
            take(m, "money", f"{_CURRENCY[m.group(1)]}:{_scaled(m.group(2), m.group(3))}")
        for m in _MONEY_WORD.finditer(text):
            cur = _CURRENCY[m.group(3).lower()]
            take(m, "money", f"{cur}:{_scaled(m.group(1), m.group(2))}")
        for m in _MONEY_CODE.finditer(text):
            take(m, "money", f"{m.group(1)}:{_scaled(m.group(2), m.group(3))}")
        for m in _PERCENT.finditer(text):
            take(m, "percent", _canon_number(m.group(1)))
        lead = _LIST_LEAD.match(text).end()
        heading = text[:lead].lstrip().startswith("#")
        for m in _NUMBER.finditer(text):
            s, e = m.span()
            if s == lead and (_LIST_MARK.match(text, e) or (heading and _SECTION_MARK.match(text, e))):
                continue  # "1. item", "2) item", "### 3.2 Heading"
            whole, frac, mult = m.group(1), m.group(2) or "", m.group(3)
            if "," not in whole and len(whole) >= 9 and not frac and not mult:
                # Long digit runs are account, phone or id numbers: kept only as a hash.
                take(m, "number", keyed_hash(self.salt, "number", whole))
                continue
            take(m, "number", _scaled(whole + frac, mult))
        return found, claimed

    # -- context keys ----------------------------------------------------------
    @staticmethod
    def _chunks(doc) -> tuple[list[tuple[int, int, int, str, int]], list[int]]:
        sent_of = [0] * len(doc)
        for sent in doc.sents:
            for i in range(sent.start, sent.end):
                sent_of[i] = sent.start
        chunks = []
        for nc in doc.noun_chunks:
            head = nc.root
            if head.pos_ not in ("NOUN", "PROPN"):
                head = next((t for t in reversed(nc) if t.pos_ in ("NOUN", "PROPN")), None)
                if head is None:
                    continue
            if head.ent_type_ in _NAME_ENTS:
                continue
            lem = head.lemma_.lower()
            if not (lem.isascii() and lem.isalpha() and 2 <= len(lem) <= 30) or lem in _CTX_STOP:
                continue
            if head.pos_ == "PROPN":
                lem = PROPN_MARK + lem
            chunks.append((nc.start, nc.end, head.i, lem, sent_of[head.i]))
        return chunks, sent_of

    @staticmethod
    def context_keys(doc, spans: Sequence[tuple[int, int]]) -> list[str]:
        """Context key per char span (see the module docstring); '' if none."""
        if not spans:
            return []
        chunks, sent_of = AnchorExtractor._chunks(doc)
        out = []
        for s, e in spans:
            sp = doc.char_span(s, e, alignment_mode="expand")
            if sp is None or len(sp) == 0:
                out.append("")
                continue
            ta, tb = sp.start, sp.end
            sid = sent_of[ta]
            # 1. The anchor modifies a noun outside it ("3 days", "56 donors", "GitHub repo").
            head_key = ""
            for t in sp:
                h = t.head
                if (h.i < ta or h.i >= tb) and t.dep_ in _MOD_DEPS and h.pos_ in ("NOUN", "PROPN") \
                        and h.ent_type_ not in _NAME_ENTS and sent_of[h.i] == sid:
                    lem = h.lemma_.lower()
                    if lem.isascii() and lem.isalpha() and 2 <= len(lem) <= 30 and lem not in _CTX_STOP:
                        head_key = PROPN_MARK + lem if h.pos_ == "PROPN" else lem
                        break
            if head_key:
                out.append(head_key)
                continue
            # 2. The nearest noun chunk in the sentence.
            best, best_d = "", math.inf
            for cs, ce, hi, lem, csid in chunks:
                if csid != sid or ta <= hi < tb:
                    continue
                if cs <= ta and tb <= ce:
                    d = -1.0
                elif ce <= ta:
                    between = doc[ce:ta]
                    if all(t.is_punct or t.is_space or t.text in ("=", "-", "–", "—") for t in between):
                        d = -0.5
                    else:
                        d = (ta - ce) - 0.5
                elif cs >= tb:
                    d = float(cs - tb)
                else:
                    d = -0.75
                if d < best_d:
                    best, best_d = lem, d
            out.append(best)
        return out

    # -- one doc ------------------------------------------------------------------
    def anchors_for(self, text: str, doc, sensitive: bool) -> list[tuple[int, str, str]]:
        """Distinct (type code, value, context key) for one piece of text and its doc."""
        found, claimed = self.regex_anchors(text)
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
        ctx = self.context_keys(doc, [(s, e) for s, e, _, _ in found]) if doc is not None else [""] * len(found)
        out = set()
        for (_, _, kind, v), c in zip(found, ctx):
            if kind in HASHED_TYPES or sensitive:
                v = keyed_hash(self.salt, kind, v)
            out.add((TYPE_CODE[kind], v, c))
        return sorted(out)

    def extract(self, texts: Sequence[str], sensitive: Sequence[bool], batch_size: int = 256
                ) -> list[list[tuple[int, str, str]]]:
        """Anchors for many lines. Long lines are split into pieces for spaCy."""
        pieces: list[str] = []
        owner: list[int] = []
        for i, t in enumerate(texts):
            if len(t) <= MAX_PIECE_CHARS:
                pieces.append(t)
                owner.append(i)
                continue
            start = 0
            while start < len(t):
                end = min(len(t), start + MAX_PIECE_CHARS)
                if end < len(t):
                    cut = t.rfind(" ", start + MAX_PIECE_CHARS // 2, end)
                    end = cut + 1 if cut > 0 else end
                pieces.append(t[start:end])
                owner.append(i)
                start = end
        out: list[set] = [set() for _ in texts]
        sens = [bool(s) or bool(CRED_LINE.search(t)) for t, s in zip(texts, sensitive)]
        has_alpha = [_ALPHA.search(p) is not None for p in pieces]
        docs = iter(self.nlp.pipe((p for p, a in zip(pieces, has_alpha) if a), batch_size=batch_size)
                    if self.nlp is not None else ())
        for p, i, a in zip(pieces, owner, has_alpha):
            doc = next(docs) if (a and self.nlp is not None) else None
            out[i].update(self.anchors_for(p, doc, sens[i]))
        return [sorted(s) for s in out]


def load_nlp():
    """en_core_web_sm with the parser (noun chunks, sentences) and NER."""
    import spacy

    return spacy.load("en_core_web_sm")


# --- literal presence (B1 v2 fallback) -----------------------------------------------

_WS = re.compile(r"[ \t\f\v\u00a0]+")
_MONTHS_FULL = ("january", "february", "march", "april", "may", "june", "july", "august", "september",
                "october", "november", "december")
_MONTHS_ABBR = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
ENTITY_TYPES: frozenset[str] = frozenset(NER_TYPES.values())
_WORD_TOKEN = re.compile(r"[A-Za-z0-9][\w'’&.\-]*")
_SESSION_LABEL = re.compile(r"PREVIOUS \(NOW ENDED\) (?:COMPUTER USE )?SESSION \(([^)\n]*)\)")


def literal_surfaces(kind: str, value: str) -> list[str]:
    """Lower-case surface forms under which a stored (not hashed) value can appear in text."""
    if value.startswith("h:"):
        return []
    if kind == "url":
        if value.startswith(("github:", "gitlab:")):
            forge, rest = value.split(":", 1)
            return [f"{forge}.com/{rest}".lower()]
        if value.startswith("gitlab-pid:"):
            return []
        if value.startswith("gdoc:"):
            return [value.rsplit(":", 1)[1].lower()]
        bare = value.split("://", 1)[-1].removeprefix("www.").lower()
        return [bare, "www." + bare]
    if kind == "date":
        if value.startswith("day:"):
            n = value[4:]
            return [f"day {n}", f"day #{n}"]
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", value)
        if m:
            y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
            full, abbr = _MONTHS_FULL[mo - 1], _MONTHS_ABBR[mo - 1]
            return [value, f"{mo}/{d}/{y}", f"{mo:02d}/{d:02d}/{y}", f"{full} {d}, {y}", f"{full} {d} {y}",
                    f"{abbr} {d}, {y}", f"{abbr} {d} {y}", f"{d} {full} {y}", f"{d} {abbr} {y}"]
        m = re.fullmatch(r"--(\d{2})-(\d{2})", value)
        if m:
            mo, d = int(m.group(1)), int(m.group(2))
            full, abbr = _MONTHS_FULL[mo - 1], _MONTHS_ABBR[mo - 1]
            return [f"{full} {d}", f"{abbr} {d}", f"{d} {full}", f"{d} {abbr}"]
        m = re.fullmatch(r"(\d{4})-(\d{2})", value)
        if m:
            mo = int(m.group(2))
            return [f"{_MONTHS_FULL[mo - 1]} {m.group(1)}", f"{_MONTHS_ABBR[mo - 1]} {m.group(1)}"]
        return [value]
    if kind == "time":
        m = re.fullmatch(r"(\d{2}):(\d{2})", value)
        if not m:
            return [value]
        h, mi = int(m.group(1)), m.group(2)
        h12, ap = (h % 12) or 12, ("pm" if h >= 12 else "am")
        out = [value, f"{h}:{mi}", f"{h12}:{mi} {ap}", f"{h12}:{mi}{ap}"]
        if mi == "00":
            out += [f"{h12} {ap}", f"{h12}{ap}"]
        return out
    if kind == "agent":
        return [value.removeprefix("bare:")]
    if kind in ENTITY_TYPES:
        return [value]
    return []


def _ctx_forms(lemma: str) -> str:
    forms = [re.escape(lemma) + r"(?:s|es|'s|’s)?"]
    if lemma.endswith("y") and len(lemma) > 2:
        forms.append(re.escape(lemma[:-1]) + "ies")
    return "(?:" + "|".join(forms) + ")"


_ADJ_CACHE: dict[str, tuple[re.Pattern[str], re.Pattern[str]]] = {}


def ctx_adjacent(text: str, s: int, e: int, lemma: str) -> bool:
    """True if the context word sits next to the value text[s:e] on the same line: right after it
    with up to two words between ("56 new donors"), or right before it with only punctuation
    between ("Donors: 56"). The same rule as the pre-labelling evidence (prelabel._ctx_adjacent)."""
    if not lemma:
        return False
    pats = _ADJ_CACHE.get(lemma)
    if pats is None:
        f = _ctx_forms(lemma)
        pats = _ADJ_CACHE[lemma] = (
            re.compile(r"(?i)[^\w\n]*(?:[A-Za-z][\w'’-]*[^\w\n]+){0,2}?" + f + r"(?![\w])"),
            re.compile(r"(?i)(?<![\w])" + f + r"[\s:=*_|()\[\]\-–—]*$"),
        )
    after, before = text[e:e + 60].split("\n", 1)[0], text[max(0, s - 40):s].rsplit("\n", 1)[-1]
    return bool(pats[0].match(after) or pats[1].search(before))


class LiteralIndex:
    """Literal presence of stored anchor values in one memory version (B1 v2 fallback).

    Lines are the version's raw lines (`text.split("\\n")`, so line j matches line
    hash j of the chain) with scaffold session labels blanked, runs of blanks
    collapsed and case folded.
    """

    def __init__(self, text: str, salt: bytes) -> None:
        lines = [_SESSION_LABEL.sub(" ", ln) if "PREVIOUS (NOW ENDED)" in ln else ln
                 for ln in (text or "").split("\n")]
        self.lines = [_WS.sub(" ", ln) for ln in lines]
        self.low_lines = [ln.lower() for ln in self.lines]
        self.low = "\n".join(self.low_lines)
        self.salt = salt
        self._rx: dict[tuple[str, str], re.Pattern[str]] = {}
        self._hashes: dict[str, set[str]] = {}
        self._found: dict[int, list] = {}

    def _pattern(self, kind: str, surface: str) -> re.Pattern[str]:
        key = (kind, surface)
        rx = self._rx.get(key)
        if rx is None:
            body = re.escape(_WS.sub(" ", surface.strip()))
            if kind == "url":
                rx = re.compile(r"(?<![\w.-])" + body + r"(?![\w/?&=#%-])")
            else:
                rx = re.compile(r"(?<![\w])" + body + r"(?![\w])")
            self._rx[key] = rx
        return rx

    def has_value(self, kind: str, value: str) -> bool:
        """True if one of the value's surface forms occurs in the version."""
        if value.startswith("h:"):
            return self.has_hashed(kind, value)
        for sf in literal_surfaces(kind, value):
            sf = _WS.sub(" ", sf.strip())
            if len(sf) >= 2 and _find_bounded(self.low, sf, kind == "url"):
                return True
        return False

    def line_has_context(self, j: int, lemma: str) -> bool:
        """True if line j contains the context lemma as a word (plural and possessive forms too)."""
        if not lemma or j >= len(self.low_lines):
            return False
        rx = self._rx.get(("ctx", lemma))
        if rx is None:
            rx = self._rx[("ctx", lemma)] = re.compile(r"(?<![\w])" + _ctx_forms(lemma.lower()) + r"(?![\w])")
        return rx.search(self.low_lines[j]) is not None

    def quantity_adjacent(self, j: int, kind: str, stored: str, lemma: str, extractor: "AnchorExtractor") -> bool:
        """True if line j holds the value (as the regex anchors normalise it, or its keyed hash)
        with the context word adjacent to it (`ctx_adjacent`)."""
        if not lemma or j >= len(self.lines):
            return False
        line = self.lines[j]
        found = self._found.get(j)
        if found is None:
            found = self._found[j] = extractor.regex_anchors(line)[0]
        for s, e, k, v in found:
            if k == kind and (v == stored or (stored.startswith("h:") and keyed_hash(self.salt, k, v) == stored)):
                if ctx_adjacent(line, s, e, lemma):
                    return True
        return False

    def has_hashed(self, kind: str, stored: str) -> bool:
        """True if a candidate string of this kind in the version hashes to `stored`."""
        hs = self._hashes.get(kind)
        if hs is None:
            hs = self._hashes[kind] = self._candidate_hashes(kind)
        return stored in hs

    def _candidate_hashes(self, kind: str) -> set[str]:
        out: set[str] = set()
        for line in self.lines:
            out |= candidate_hashes(line, kind, self.salt)
        return out


HASHABLE_KINDS: frozenset[str] = frozenset({"email", "phone"}) | ENTITY_TYPES
_NAME_PARTICLES = frozenset({"of", "the", "and", "&", "de", "da", "del", "della", "di", "du", "van", "von",
                             "der", "den", "la", "le", "bin", "ibn", "al", "el"})


def _find_bounded(text: str, sf: str, url: bool = False) -> bool:
    """True if `sf` occurs in `text` with no word character (for URLs, also . - / ? & = # %)
    glued to either side. str.find is used so that long texts are cheap to scan."""
    left_bad = "._-" if url else "_"
    right_bad = "_/?&=#%-" if url else "_"
    start = text.find(sf)
    while start >= 0:
        end = start + len(sf)
        before = text[start - 1] if start > 0 else " "
        after = text[end] if end < len(text) else " "
        if not (before.isalnum() or before in left_bad) and not (after.isalnum() or after in right_bad):
            return True
        start = text.find(sf, start + 1)
    return False


def name_candidates(line: str) -> frozenset[str]:
    """Normalised 1-4 word phrases on a line that could be a name: runs of capitalised words
    (particles such as 'van' or 'of' allowed inside), as `norm_entity` would store them."""
    toks = list(_WORD_TOKEN.finditer(line))
    out: set[str] = set()
    n = len(toks)
    i = 0
    while i < n:
        if not toks[i].group(0)[0].isupper():
            i += 1
            continue
        j = i  # extend the run of capitalised words and particles
        while j + 1 < n and (toks[j + 1].group(0)[0].isupper() or toks[j + 1].group(0).lower() in _NAME_PARTICLES):
            j += 1
        for a in range(i, j + 1):
            if not toks[a].group(0)[0].isupper():
                continue
            for b in range(a, min(j, a + 3) + 1):
                if toks[b].group(0)[0].isupper():
                    v = norm_entity(line[toks[a].start():toks[b].end()])
                    if v is not None:
                        out.add(v)
        i = j + 1
    return frozenset(out)


def candidate_hashes(line: str, kind: str, salt: bytes) -> set[str]:
    """Keyed hashes of the strings on one line that could be a hashed value of this kind:
    emails and phones by their regexes, names by capitalised word n-grams (1 to 4 words)."""
    out: set[str] = set()
    if kind == "email":
        for m in _EMAIL.finditer(line):
            out.add(keyed_hash(salt, "email", m.group(0).lower()))
    elif kind == "phone":
        for m in _PHONE.finditer(line):
            digits = re.sub(r"\D", "", m.group(0))
            if len(digits) == 11 and digits.startswith("1"):
                digits = digits[1:]
            if len(digits) >= 10:
                out.add(keyed_hash(salt, "phone", digits))
    elif kind in ENTITY_TYPES:
        for v in name_candidates(line):
            out.add(keyed_hash(salt, kind, v))
    return out
