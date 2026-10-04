"""Figure F7 (SPEC 10.3): AI Village dependency-graph statistics against the swarm generator.

One small histogram per D3 statistic. Bars are the generator distribution: 64 replicates, each
pooling one generated DAG per village goal with that goal's session count (the blog's generator,
17 layers). Vertical lines are the AI Village values pooled over goals: all edges (solid) and write
edges (dashed). Only Penn Blue (#011F5B), Penn Red (#990000) and their tints are used, text is
never white, every label is capitalised, and `plot_f7` raises if two texts overlap or a text leaves
the canvas (the D1 figure check).

Source of the generator: Wenhao Chai, "Predictable Swarm Scaling", 2026,
https://wenhaochai.com/blogs/predictable-swarm-scaling.html
Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

from avsd.swarmsim.figure import PENN_BLUE, PENN_RED, TEXT_PT, TICK_PT, _check_text, _font, tint  # noqa: E402

F7_TITLES = {
    "multi_parent_share": "Steps With 2+ Parents",
    "mean_parents": "Mean Parents per Step",
    "sibling_merge_share": "Merges Between Siblings",
    "outdeg_gini": "Out-Degree Gini",
    "top10_child_share": "Children of Top 10% Parents",
    "cross_layer_share": "Edges Skipping 2+ Layers",
}
F7_UNITS = {
    "multi_parent_share": "Share of Non-Root Steps",
    "mean_parents": "Parents",
    "sibling_merge_share": "Share of Merge Steps",
    "outdeg_gini": "Gini Coefficient",
    "top10_child_share": "Share of Child Links",
    "cross_layer_share": "Share of Edges",
}


def plot_f7(gen: Mapping[str, np.ndarray], obs: Mapping[str, Mapping[str, float]],
            stats: Sequence[str], out_base: Path, n_goals: int, n_reps: int) -> list[Path]:
    """Write `<out_base>.pdf` and `.png`.

    `gen[stat]` holds the pooled generator values (one per replicate); `obs[label][stat]` the
    pooled AI Village value for edge label `all` and `write`.
    """
    plt.rcParams.update({"font.family": _font(), "font.size": TEXT_PT, "pdf.fonttype": 42})
    ncol = 3
    nrow = math.ceil(len(stats) / ncol)
    fig, axes = plt.subplots(nrow, ncol, figsize=(7.0, 1.8 * nrow + 0.55))
    fig.subplots_adjust(left=0.04, right=0.985, bottom=0.2 if nrow == 2 else 0.3, top=0.92,
                        wspace=0.22, hspace=0.72)
    axes = np.atleast_1d(axes).ravel()
    bar_c = tint(PENN_BLUE, 0.55)
    edge_c = tint(PENN_BLUE, 0.2)
    styles = {"all": dict(color=PENN_RED, lw=1.6, ls="-"),
              "write": dict(color=tint(PENN_RED, 0.3), lw=1.4, ls=(0, (3.0, 1.6)))}
    for k, (ax, st) in enumerate(zip(axes, stats, strict=False)):
        g = np.asarray(gen[st], dtype=float)
        g = g[np.isfinite(g)]
        vals = [obs[lab][st] for lab in styles if lab in obs and math.isfinite(obs[lab].get(st, math.nan))]
        lo = min([*g, *vals]) if len(g) or vals else 0.0
        hi = max([*g, *vals]) if len(g) or vals else 1.0
        span = hi - lo if hi > lo else max(abs(hi), 1e-3)
        pad = 0.08 * span
        xlo, xhi = lo - pad, hi + pad
        if len(g):
            gspan = g.max() - g.min()
            nb = 14
            width = gspan / nb if gspan > 0 else span / 60
            bins = np.arange(g.min() - width / 2, g.max() + width, width) if gspan > 0 else \
                np.array([g.min() - width / 2, g.min() + width / 2])
            ax.hist(g, bins=bins, color=bar_c, edgecolor=edge_c, linewidth=0.4, zorder=2)
        for lab, sty in styles.items():
            if lab in obs and math.isfinite(obs[lab].get(st, math.nan)):
                ax.axvline(obs[lab][st], zorder=3, **sty)
        ax.set_xlim(xlo, xhi)
        ticks = [v for v in MaxNLocator(nbins=4, steps=[1, 2, 2.5, 5, 10]).tick_values(xlo, xhi)
                 if xlo <= v <= xhi]
        step = ticks[1] - ticks[0] if len(ticks) > 1 else span
        nd = max(0, -int(math.floor(math.log10(step)))) if step > 0 else 2
        ax.set_xticks(ticks, [f"{v:.{nd}f}" for v in ticks])
        ax.set_yticks([])
        ax.tick_params(length=0, labelsize=TICK_PT, colors=PENN_BLUE, pad=2)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(tint(PENN_BLUE, 0.35))
        ax.set_xlabel(F7_UNITS[st], color=PENN_BLUE, labelpad=2, fontsize=TICK_PT)
        ax.text(0.0, 1.07, "abcdefghij"[k], transform=ax.transAxes, fontsize=TEXT_PT + 1.5,
                fontweight="bold", color=PENN_BLUE, va="baseline", ha="left")
        ax.text(0.085, 1.07, F7_TITLES[st], transform=ax.transAxes, fontsize=TEXT_PT,
                color=PENN_BLUE, va="baseline", ha="left")
    for ax in axes[len(stats):]:
        ax.set_visible(False)
    handles = [Patch(facecolor=bar_c, edgecolor=edge_c, linewidth=0.4,
                     label=f"Generator ({n_reps} Replicates, One DAG per Goal)"),
               Line2D([], [], label=f"AI Village, All Edges ({n_goals} Goals)", **styles["all"]),
               Line2D([], [], label="AI Village, Write Edges", **styles["write"])]
    leg = fig.legend(handles=handles, loc="lower center", ncol=3, frameon=False, fontsize=TEXT_PT,
                     handlelength=2.0, columnspacing=1.6, bbox_to_anchor=(0.5, 0.0))
    for t in leg.get_texts():
        t.set_color(PENN_BLUE)
    _check_text(fig)
    out_base.parent.mkdir(parents=True, exist_ok=True)
    paths = [out_base.with_suffix(".pdf"), out_base.with_suffix(".png")]
    fig.savefig(paths[0])
    fig.savefig(paths[1], dpi=300)
    plt.close(fig)
    return paths
