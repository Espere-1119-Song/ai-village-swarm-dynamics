"""Full PREV and NEXT memory texts for the pairs of the B1 blind sheet, for the offline labelling page.

    python scripts/blind_fulltext.py      # writes data/labels/memory_pairs_fulltext.json (mode 600)

Credentials are masked with the sheets' rule plus B1's heading rule and a stricter pass on credential lines (mask_full). The file holds raw memory text
with personal data: keep it under data/labels/ and on the labeller's machine only.
"""

import csv
import json
from pathlib import Path

import re

from avsd.config import load_config
from avsd.lineage.anchors import CRED_LINE, HeadingStack
from avsd.lineage.prelabel import MASK, mask_text, read_texts

import importlib.util

_spec = importlib.util.spec_from_file_location("scan_credentials", Path(__file__).with_name("scan_credentials.py"))
_scan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_scan)

_TOK = re.compile(r"[^\s\"'`,;()\[\]{}<>|]+")
_EDGE = "*_`'\".,:;!?()[]{}<>|-#"


_SESSION = re.compile(r"(?i)\b(?:jsessionid|phpsessid|asp\.net_sessionid|session[_\s-]?(?:id|token|cookie)|sessionid|sid|connect\.sid|csrf[_-]?token)"
                      r"\s*[:=]\s*[\"']?(?P<val>[A-Za-z0-9._%~+/-]{8,})")


def mask_full(text: str) -> str:
    """mask_text with B1's heading rule, plus a stricter pass on credential lines.

    A line is sensitive when it names a credential, login or account (anchors.CRED_LINE) or sits
    under a heading that does. On such lines any token of 6 or more characters that mixes letters
    with digits or symbols, or mixes upper and lower case, is masked too.
    """
    hs = HeadingStack()
    lines = text.split("\n")
    sens = [hs.feed(line) or bool(CRED_LINE.search(line)) for line in lines]
    text = _SESSION.sub(lambda m: m.group(0).replace(m.group("val"), MASK), text)
    masked = mask_text(text, sens).split("\n")
    out = []
    for line, s in zip(masked, sens):
        if s:
            def sub(m):
                tok = m.group(0)
                core = tok.strip(_EDGE)
                if MASK in tok or len(core) < 6 or "://" in core or ("@" in core and "." in core.rsplit("@", 1)[-1]):
                    return tok
                has_d, has_a = any(c.isdigit() for c in core), any(c.isalpha() for c in core)
                has_sym = any(c in "!#$%^&*+=?~@" for c in core)
                mixed = any(c.isupper() for c in core[1:]) and any(c.islower() for c in core)
                return tok.replace(core, MASK) if (has_a and (has_d or has_sym)) or mixed else tok
            line = _TOK.sub(sub, line)
        out.append(line)
    text = "\n".join(out)
    for _ in range(3):  # finally, whatever the project's credential scanner still finds
        hits = sorted(_scan._hits_in(text), key=lambda h: h["pos"], reverse=True)
        if not hits:
            break
        for h in hits:
            text = text[:h["pos"]] + MASK + text[h["pos"] + h["val_len"]:]
    return text


def main() -> None:
    cfg = load_config(None)
    labels = Path(cfg["paths"]["labels"])
    want = {r["pair_id"] for r in csv.DictReader(open(labels / "memory_pairs_blind.csv", encoding="utf-8-sig"))}
    pairs: dict[str, tuple[str, str]] = {}
    for r in csv.DictReader(open(labels / "memory_pairs.csv", encoding="utf-8-sig")):
        if r["pair_id"] in want:
            if pairs.setdefault(r["pair_id"], (r["prev_uid"], r["next_uid"])) != (r["prev_uid"], r["next_uid"]):
                raise SystemExit(f"pair {r['pair_id']} has more than one version pair")
    texts = read_texts(Path(cfg["paths"]["tables"]) / "agent_memories_text.parquet",
                       {u for p in pairs.values() for u in p})
    out = {pid: {"prev": mask_full(texts.get(p, "")), "next": mask_full(texts.get(n, ""))} for pid, (p, n) in pairs.items()}
    path = labels / "memory_pairs_fulltext.json"
    path.write_text(json.dumps(out, ensure_ascii=False))
    path.chmod(0o600)
    missing = sum(1 for p, n in pairs.values() if p not in texts or n not in texts)
    print(f"{path}: {len(out)} pairs, {sum(len(v['prev']) + len(v['next']) for v in out.values()):,} chars, {missing} pairs missing a text")


if __name__ == "__main__":
    main()
