"""Third-judge check of B1 pre-label disagreements (SPEC 6.3.4; owner's request of 2026-10-01).

A stratified random sample of the units on which the LLM pre-labellers disagree
(`avsd.lineage.prelabel.adjudication_frame`: D1, the two strong models disagree; D2, they agree and
Qwen3-14B differs; credential-like units left out) is judged from the same excerpts the models saw,
blind to every model and rule label. The report stage then estimates each labeller's accuracy on
the disagreements (outputs/qa/memory_prelabel.md, aggregates only).

Commands (project env on GRASP, `source scripts/env.sh` first):
  python scripts/prelabel_adjudicate.py sample            write the sample to the judgment file (empty
                                                          judge columns; judgments already made are kept)
  python scripts/prelabel_adjudicate.py show N [M]        print the unit and excerpts of sample items N..M
                                                          (1-based), without labels; stdout only
  python scripts/prelabel_adjudicate.py set               read "N LABEL CONFIDENCE [NOTE]" lines from stdin
  python scripts/prelabel_adjudicate.py status            counts only

The judgment file data/labels/memory_pairs_adjudication.csv is private (mode 600). Notes are short
reason codes, never memory text.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

from avsd.config import load_config
from avsd.lineage import prelabel as pre


def _paths(cfg: dict) -> tuple[Path, Path]:
    return pre.cache_dir(cfg), Path(cfg["paths"]["labels"]) / pre.ADJUDICATION_FILE


def _sample(cfg: dict) -> tuple[list[dict], dict, list[dict]]:
    out, _ = _paths(cfg)
    reqs = pre._read_jsonl(out / "requests.jsonl")
    seed = int(cfg["seed"])
    answers = pre.model_answers(reqs, out, seed)
    missing = [k for k in pre.LLM_KEYS if k not in answers or any(p is None for p in answers[k])]
    if missing:
        raise SystemExit(f"no answers of {', '.join(missing)} for every request yet")
    labels = pre.model_label_lists(answers)
    sample, info = pre.adjudication_frame(reqs, labels, seed)
    return sample, info, reqs


def _write(path: Path, rows: list[dict]) -> None:
    with pre._private_open(path, "w", encoding="utf-8", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(pre.ADJ_COLUMNS))
        wr.writeheader()
        for r in rows:
            wr.writerow({c: r.get(c, "") for c in pre.ADJ_COLUMNS})


def _rows(cfg: dict) -> tuple[list[dict], dict, list[dict]]:
    """The sample in order, merged with the judgments on file."""
    sample, info, reqs = _sample(cfg)
    _, path = _paths(cfg)
    old = pre.read_adjudication(path)
    rows = []
    for s in sample:
        j = old.get((s["pair_id"], s["unit_key"]), {})
        rows.append({"pair_id": s["pair_id"], "unit_key": s["unit_key"], "stratum": s["stratum"], "_row": s["row"],
                     **{c: j.get(c, "") for c in ("judge_label", "judge_confidence", "judge_note")}})
    return rows, info, reqs


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sample")
    sp = sub.add_parser("show")
    sp.add_argument("first", type=int)
    sp.add_argument("last", type=int, nargs="?")
    sub.add_parser("set")
    sub.add_parser("status")
    args = p.parse_args(argv)
    cfg = load_config()
    _, path = _paths(cfg)
    rows, info, reqs = _rows(cfg)
    if args.cmd == "sample":
        _write(path, rows)
        print(f"sample: {len(rows)} units ({dict(Counter(r['stratum'] for r in rows))}); frame {info['N']}, "
              f"credential-like left out {info['skipped']}; file {path}")
    elif args.cmd == "show":
        last = args.last or args.first
        for k in range(args.first, last + 1):
            r = rows[k - 1]
            msg = reqs[r["_row"]]["messages"][1]["content"]
            body = msg.split("Unit:", 1)[1].rsplit("\n\nReply with JSON", 1)[0]
            print(f"===== item {k} =====\nUnit:{body}\n")
    elif args.cmd == "set":
        n = 0
        for line in sys.stdin:
            parts = line.strip().split(maxsplit=3)
            if not parts or parts[0].startswith("#"):
                continue
            k, lab, conf = int(parts[0]), parts[1].lower(), parts[2].lower()
            if lab not in (*pre.LABELS, "undecided") or conf not in pre.CONFIDENCES:
                raise SystemExit(f"bad line: {line.strip()}")
            r = rows[k - 1]
            r["judge_label"] = "" if lab == "undecided" else lab
            r["judge_confidence"] = conf
            r["judge_note"] = (parts[3] if len(parts) > 3 else "") or ("undecided" if lab == "undecided" else "")
            n += 1
        _write(path, rows)
        print(f"set: {n} judgments recorded; {sum(1 for r in rows if r['judge_label'])} of {len(rows)} labelled")
    else:
        print(f"{sum(1 for r in rows if r['judge_label'])} of {len(rows)} judged; "
              f"{dict(Counter((r['stratum'], bool(r['judge_label'])) for r in rows))}")


if __name__ == "__main__":
    main(sys.argv[1:])
