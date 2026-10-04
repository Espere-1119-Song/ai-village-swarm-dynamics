"""Paired test of the post-switch rise in B1: is h2 above h1 for trials after perma-computer-use?

    python scripts/b1_post_switch_rise.py     # writes outputs/tables/memory_post_switch_rise.csv

B1 reports h1 and h2 of the post-switch regime with separate agent-bootstrap intervals, which
overlap. This script rebuilds the regime risk counts of trials 1 and 2 from the fact spells
(data/interim/memory_facts{,_v2,_v3}.parquet) and the live memory rows, compares them with
outputs/tables/memory_hazard{,_v2,_v3}.csv (the rebuilt counts fall short by at most 44 of about 3 million
trials, cause unidentified), and resamples agents to get an interval for h2 - h1
with both hazards computed on the same replicates. Standard agents only, as in the B1 tables.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import polars as pl

from avsd.config import load_config
from avsd.lineage.memory import live_rows

REPS = 2000
SEED = 20261003 + 101


def cons_regimes(cfg: dict) -> tuple[dict[str, np.ndarray], dict[str, dict[str, int]], set[str]]:
    """Per agent: the regime (1 = post) of each consolidation in order, the number of consolidations
    at or before each live row, and the set of Claude Code agents."""
    mv = pl.read_parquet(Path(cfg["paths"]["interim"]) / "memory_versions.parquet")
    rows, _ = live_rows(mv)
    reg, ncons, cc = {}, {}, set()
    for (a,), g in rows.group_by(["agent_id"], maintain_order=True):
        is_cons = g["is_cons"].to_numpy()
        reg[a] = (g.filter(pl.col("is_cons"))["regime_cu"].cast(pl.String).to_numpy() == "post").astype(np.int8)
        ncons[a] = dict(zip(g["id"].to_list(), np.cumsum(is_cons).tolist()))
        if (g["scaffold"].cast(pl.String) == "claude_code").any():
            cc.add(a)
    return reg, ncons, cc


def counts(facts: Path, reg: dict, ncons: dict, cc: set) -> tuple[list[str], np.ndarray]:
    """(agents, array agents x [n1, d1, n2, d2]) for post-regime trials of first spells."""
    f = pl.read_parquet(facts, columns=["agent_id", "spell", "spell_start_row_id", "trials", "lost_event"])
    f = f.filter((pl.col("spell") == 0) & ~pl.col("agent_id").is_in(list(cc)))
    agents = sorted(f["agent_id"].unique().to_list())
    out = np.zeros((len(agents), 4))
    for i, a in enumerate(agents):
        g = f.filter(pl.col("agent_id") == a)
        e = np.array([ncons[a].get(r, -1) for r in g["spell_start_row_id"].to_list()], dtype=np.int64)
        if (e < 0).any():
            raise SystemExit(f"{a}: {(e < 0).sum()} spell starts are not live rows")
        L = g["trials"].fill_null(0).to_numpy().astype(np.int64)
        ev = g["lost_event"].is_in(["dropped", "modified"]).fill_null(False).to_numpy().astype(bool)
        r = np.append(reg[a], 0)  # trial g happens at consolidation e + g (1-based)
        for j, gg in enumerate((1, 2)):
            at = (L >= gg) & (e + gg <= len(reg[a]))
            post = np.zeros(len(L), dtype=bool)
            post[at] = r[e[at] + gg - 1] == 1
            out[i, 2 * j] = post.sum()
            out[i, 2 * j + 1] = (post & ev & (L == gg)).sum()
    return agents, out


def main() -> None:
    cfg = load_config(None)
    tables = Path(cfg["paths"]["outputs"]) / "tables"
    interim = Path(cfg["paths"]["interim"])
    reg, ncons, cc = cons_regimes(cfg)
    rows = []
    for v, sfx in (("v1", ""), ("v2", "_v2"), ("v3", "_v3")):
        agents, c = counts(interim / f"memory_facts{sfx}.parquet", reg, ncons, cc)
        pub = {r["g"]: r for r in csv.DictReader(open(tables / f"memory_hazard{sfx}.csv"))
               if r["scope"] == "regime:post" and r["stratum"] == "All standard"}
        tot = c.sum(0)
        gap = max(abs(int(tot[0]) - int(pub["1"]["n_at_risk"])), abs(int(tot[1]) - int(pub["1"]["n_lost"])),
                  abs(int(tot[2]) - int(pub["2"]["n_at_risk"])), abs(int(tot[3]) - int(pub["2"]["n_lost"])))
        rng = np.random.default_rng(SEED)
        draws = rng.integers(0, len(agents), size=(REPS, len(agents)))
        w = np.zeros((REPS, len(agents)))
        for b in range(REPS):
            np.add.at(w[b], draws[b], 1.0)
        cb = w @ c
        with np.errstate(divide="ignore", invalid="ignore"):
            h1b, h2b = cb[:, 1] / cb[:, 0], cb[:, 3] / cb[:, 2]
        diff = h2b - h1b
        diff = diff[np.isfinite(diff)]
        h1, h2 = tot[1] / tot[0], tot[3] / tot[2]
        lo, hi = np.percentile(diff, [2.5, 97.5])
        agents_post = int(((c[:, 0] > 0) | (c[:, 2] > 0)).sum())
        rise = (c[:, 3] / np.maximum(c[:, 2], 1)) > (c[:, 1] / np.maximum(c[:, 0], 1))
        both = (c[:, 0] >= 30) & (c[:, 2] >= 30)
        rows.append({"rules": v, "agents": len(agents), "agents_with_post_trials": agents_post,
                     "n1": int(tot[0]), "d1": int(tot[1]), "n2": int(tot[2]), "d2": int(tot[3]),
                     "h1": h1, "h2": h2, "diff": h2 - h1, "diff_lo": lo, "diff_hi": hi,
                     "share_reps_diff_le_0": float((diff <= 0).mean()),
                     "agents_rise": int((rise & both).sum()), "agents_compared": int(both.sum()),
                     "max_count_gap_vs_published": gap})
    path = tables / "memory_post_switch_rise.csv"
    with open(path, "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    for r in rows:
        print(f"{r['rules']}: h1 {r['h1']:.3f}, h2 {r['h2']:.3f}, h2 - h1 {r['diff']:+.3f} "
              f"[{r['diff_lo']:+.3f}, {r['diff_hi']:+.3f}], P(diff <= 0) {r['share_reps_diff_le_0']:.4f}, "
              f"agents rising {r['agents_rise']}/{r['agents_compared']}, largest count gap to the B1 table {r['max_count_gap_vs_published']}")
    print(path)


if __name__ == "__main__":
    main()
