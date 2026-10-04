"""Blind copies of the B1 and B2 review sheets for the owner, and merging the labels back.

The owner chose blind labelling on 2026-10-01: the copies drop every model label, posterior and
inferred parent, and the B2 candidates are shuffled per row so that candidate 1 is no longer the
MAP parent. Only the rows to label are kept (B1 priorities 1 and 2, all 50 B2 rows).

    python scripts/blind_labels.py make    # writes data/labels/{memory_pairs,parents}_blind.csv
    python scripts/blind_labels.py merge   # copies human labels back into the full review sheets

merge reads the blind sheets from data/labels/ (copy the owner's files there first), maps B2
candidate numbers back through data/labels/parents_blind_map.json, and keeps a backup of each
full sheet before writing it. Then run the metrics commands in the two sheets' READMEs.
"""

from __future__ import annotations

import csv
import json
import random
import shutil
import sys
from pathlib import Path

LABELS = Path(__file__).resolve().parents[1] / "data" / "labels"
B1_FULL, B1_BLIND = LABELS / "memory_pairs_review.csv", LABELS / "memory_pairs_blind.csv"
B2_FULL, B2_BLIND = LABELS / "parents_review.csv", LABELS / "parents_blind.csv"
B2_MAP = LABELS / "parents_blind_map.json"
SEED = 20261003
B1_COLS = ["pair_id", "agent", "unit_type", "value", "context_key", "prev_excerpt", "next_excerpt",
           "earlier_excerpt", "human_label", "notes", "unit_key"]
CAND_FIELDS = ("channel", "who", "dt_h", "excerpt")
B2_COLS = (["item", "child_uid", "child_agent", "child_source", "unit_type", "unit_value", "child_excerpt"]
           + [f"cand_{j}_{f}" for j in range(1, 7) for f in CAND_FIELDS] + ["human_parent", "notes"])
B1_LABELS = {"kept", "modified", "dropped", "new", "restored"}


def read(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write(path: Path, rows: list[dict], cols: list[str]) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    path.chmod(0o600)


def make() -> None:
    rng = random.Random(SEED)
    b1 = [r for r in read(B1_FULL) if r["review_priority"].startswith(("1", "2"))]
    write(B1_BLIND, [{c: r.get(c, "") for c in B1_COLS} | {"human_label": "", "notes": ""} for r in b1], B1_COLS)
    out, mapping = [], {}
    rows = read(B2_FULL)
    rng.shuffle(rows)
    for r in rows:
        cands = [k for k in range(1, 7) if r.get(f"cand_{k}_uid", "").strip()]
        rng.shuffle(cands)
        mapping[r["child_uid"]] = {str(j): str(k) for j, k in enumerate(cands, start=1)}
        o = {c: r.get(c, "") for c in B2_COLS[:7]} | {"human_parent": "", "notes": ""}
        for j, k in enumerate(cands, start=1):
            o |= {f"cand_{j}_{f}": r.get(f"cand_{k}_{f}", "") for f in CAND_FIELDS}
        out.append(o)
    write(B2_BLIND, out, B2_COLS)
    B2_MAP.write_text(json.dumps(mapping, indent=1))
    B2_MAP.chmod(0o600)
    print(f"{B1_BLIND.name}: {len(b1)} rows; {B2_BLIND.name}: {len(out)} rows; map {B2_MAP.name}")


def _backup(path: Path) -> None:
    """Keep the first pre-merge copy; a second merge must not overwrite it with merged labels."""
    dst = path.with_suffix(".before_merge.csv")
    if not dst.exists():
        shutil.copy2(path, dst)


def merge() -> None:
    blind1 = {r["unit_key"]: r for r in read(B1_BLIND)}
    full1 = read(B1_FULL)
    bad = [r["human_label"] for r in blind1.values() if r["human_label"].strip() and
           r["human_label"].strip().lower() not in B1_LABELS]
    if bad:
        sys.exit(f"B1: unknown labels {sorted(set(bad))}")
    n1 = 0
    for r in full1:
        b = blind1.get(r["unit_key"])
        if b and (b["human_label"].strip() or b["notes"].strip()):
            r["human_label"], r["notes"] = b["human_label"].strip().lower(), b["notes"].strip()
            n1 += b["human_label"].strip() != ""
    _backup(B1_FULL)
    write(B1_FULL, full1, list(full1[0]))
    mapping = json.loads(B2_MAP.read_text())
    blind2 = {r["child_uid"]: r for r in read(B2_BLIND)}
    full2 = read(B2_FULL)
    n2 = 0
    for r in full2:
        b = blind2.get(r["child_uid"])
        if not b:
            continue
        h = b["human_parent"].strip().lower()
        if h and h not in ("env", "none"):
            if h not in mapping[r["child_uid"]]:
                sys.exit(f"B2 item {b['item']}: candidate {h!r} does not exist")
            h = mapping[r["child_uid"]][h]
        if h or b["notes"].strip():
            r["human_parent"], r["notes"] = h, b["notes"].strip()
            n2 += h != ""
    _backup(B2_FULL)
    write(B2_FULL, full2, list(full2[0]))
    print(f"merged {n1} B1 labels into {B1_FULL.name} and {n2} B2 parents into {B2_FULL.name}")


if __name__ == "__main__":
    {"make": make, "merge": merge}[sys.argv[1] if len(sys.argv) > 1 else "make"]()
