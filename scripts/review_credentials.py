"""List the first occurrence of each distinct credential value found by
scan_credentials.py, with masked context, for a manual precision check.

Output stays in data/interim/credential_scan/ (gitignored).

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import os
from pathlib import Path

import polars as pl

ROOT = Path(os.environ.get("AVSD", Path.home() / "ai-village-swarm-dynamics"))
OUT = ROOT / "data/interim/credential_scan"


def main() -> None:
    hits = pl.read_parquet(OUT / "hits.parquet")
    rep = hits.filter((pl.col("strength") != "weak") & ~pl.col("training_context"))
    first = (
        rep.sort("created_at")
        .group_by("fp", maintain_order=True)
        .agg(
            pl.first("kind", "key", "service", "raw_file", "raw_field", "row_id", "agent", "created_pt",
                     "val_len", "val_classes", "jwt_expired", "near_redacted", "ctx"),
            n_rows=pl.struct("table", "row_id").n_unique(),
            n_files=pl.col("raw_file").n_unique(),
            files=pl.col("raw_file").unique().sort().str.join(","),
            last_pt=pl.col("created_pt").max(),
        )
        .with_columns(pl.col("created_pt").dt.date().alias("first_date"), pl.col("last_pt").dt.date().alias("last_date"))
        .drop("created_pt", "last_pt")
        .sort("kind", "n_rows", descending=[False, True])
    )
    first.write_parquet(OUT / "distinct_first.parquet")
    with pl.Config(tbl_rows=1000, fmt_str_lengths=150, tbl_width_chars=260, tbl_cols=20):
        for kind in ["private_key", "url_userinfo", "jwt", "assignment"]:
            x = first.filter(pl.col("kind") == kind)
            print(f"\n===== {kind}: {x.height} distinct values")
            print(x.select("row_id", "raw_file", "raw_field", "agent", "first_date", "last_date", "n_rows", "files",
                           "key", "service", "val_len", "val_classes", "jwt_expired", "ctx"))


if __name__ == "__main__":
    main()
