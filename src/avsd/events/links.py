"""One-to-one record linking by time window (docs/decisions.md, duplicate turns).

`window_candidates` lists pairs of left and right records with equal keys
whose time difference falls in a window. `greedy_match` keeps a one-to-one
subset: the result of taking pairs in ascending cost order and skipping any
pair whose left or right record is already used. It is computed in rounds of
mutually best pairs, which gives the same matching as the sequential greedy
pass when the order is strict (ties are broken by the left and right ids).

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import polars as pl


def window_candidates(
    left: pl.DataFrame,
    right: pl.DataFrame,
    by: list[str],
    lo_s: float,
    hi_s: float,
    max_per_left: int = 16,
) -> pl.DataFrame:
    """Pairs with equal `by` keys and `rts - lts` in [lo_s, hi_s] seconds.

    left has `by`, `lid`, `lts`; right has `by`, `rid`, `rts`. Returns lid,
    rid, lts, rts and `dt` (seconds). At most `max_per_left` right records are
    considered per left record (the earliest in the window).
    """
    empty = pl.DataFrame(
        schema={"lid": pl.String, "rid": pl.String, "lts": left.schema["lts"],
                "rts": right.schema["rts"], "dt": pl.Float64}
    )
    if left.is_empty() or right.is_empty():
        return empty
    r = (
        right.select(*by, "rid", "rts")
        .sort("rts")
        .with_columns(pl.int_range(pl.len()).over(by).alias("_rn"))
    )
    lo = pl.duration(microseconds=int(round(lo_s * 1e6)))
    first = (
        left.select(*by, "lid", "lts")
        .with_columns((pl.col("lts") + lo).alias("_from"))
        .sort("_from")
        .join_asof(
            r.select(*by, pl.col("rts").alias("_at"), "_rn"),
            left_on="_from", right_on="_at", by=by, strategy="forward", check_sortedness=False)
        .filter(pl.col("_rn").is_not_null())
        .with_columns(pl.int_ranges("_rn", pl.col("_rn") + max_per_left).alias("_rn"))
        .explode("_rn", empty_as_null=True)
        .drop("_from", "_at")
    )
    return (
        first.join(r, on=[*by, "_rn"], how="inner")
        .with_columns(((pl.col("rts") - pl.col("lts")).dt.total_microseconds() / 1e6).alias("dt"))
        .filter((pl.col("dt") >= lo_s) & (pl.col("dt") <= hi_s))
        .select("lid", "rid", "lts", "rts", "dt")
    )


def greedy_match(cand: pl.DataFrame, cost: pl.Expr, max_rounds: int = 1000) -> pl.DataFrame:
    """One-to-one subset of `cand` (columns lid, rid, ...) by ascending `cost`."""
    c = (
        cand.with_columns(cost.alias("_cost"))
        .sort("_cost", "lid", "rid")
        .with_row_index("_r")
    )
    kept: list[pl.DataFrame] = []
    for _ in range(max_rounds):
        if c.is_empty():
            break
        best = c.filter(
            (pl.col("_r") == pl.col("_r").min().over("lid"))
            & (pl.col("_r") == pl.col("_r").min().over("rid"))
        )
        kept.append(best)
        c = c.filter(~pl.col("lid").is_in(best["lid"].implode())
                     & ~pl.col("rid").is_in(best["rid"].implode()))
    else:
        raise RuntimeError("greedy_match did not converge")
    if not kept:
        return cand.head(0)
    return pl.concat(kept).sort("_r").drop("_r", "_cost")
