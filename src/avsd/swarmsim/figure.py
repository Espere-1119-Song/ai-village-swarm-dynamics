"""Coverage over time for one agent and swarms of 4 to 64 agents (SPEC 8.2 D1 figure).

Panel a is the standard swarm (Penn Blue tints), panel b the recursive swarm with three layers
(Penn Red tints). Each line is the average coverage over every task of every simulated family, on
the family's own T1 (the slowest single-agent run). The x axis is logarithmic. Only Penn Blue
(#011F5B), Penn Red (#990000) and their tints are used, text is never white, and `plot_coverage`
raises if two text labels overlap or a label leaves the canvas.

Source: Wenhao Chai, "Predictable Swarm Scaling", 2026,
https://wenhaochai.com/blogs/predictable-swarm-scaling.html
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors as mcolors  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.text import Text  # noqa: E402

PENN_BLUE, PENN_RED = "#011F5B", "#990000"
TEXT_PT, TICK_PT = 7.5, 7.0
WHITE_SHARE = {4: 0.68, 16: 0.46, 32: 0.24, 64: 0.0}


def tint(color: str, white: float) -> str:
    """`color` mixed with white (`white` = share of white, 0 to 1)."""
    return mcolors.to_hex([c + (1.0 - c) * white for c in mcolors.to_rgb(color)])


def _font() -> str:
    names = {f.name for f in font_manager.fontManager.ttflist}
    return next((f for f in ("Nimbus Sans", "Liberation Sans", "Arial") if f in names), "DejaVu Sans")


def _check_text(fig: plt.Figure) -> None:
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    boxes = [(t.get_text(), t.get_window_extent(r)) for t in fig.findobj(Text)
             if t.get_visible() and t.get_text().strip()]
    W, H = fig.bbox.width, fig.bbox.height
    for name, b in boxes:
        if b.x0 < -0.5 or b.y0 < -0.5 or b.x1 > W + 0.5 or b.y1 > H + 0.5:
            raise ValueError(f"swarmsim figure: text {name!r} leaves the canvas")
    for i, (n1, b1) in enumerate(boxes):
        for n2, b2 in boxes[i + 1:]:
            if b1.overlaps(b2):
                raise ValueError(f"swarmsim figure: texts {n1!r} and {n2!r} overlap")


def plot_coverage(grid: np.ndarray, single: np.ndarray, curves: dict[tuple[str, int], np.ndarray],
                  out_base: Path, layers: int = 3) -> list[Path]:
    """Write `<out_base>.pdf` and `.png`. `curves[(kind, n)]` is the average coverage on `grid`."""
    plt.rcParams.update({"font.family": _font(), "font.size": TEXT_PT, "pdf.fonttype": 42})
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.75), sharey=True)
    fig.subplots_adjust(left=0.075, right=0.985, bottom=0.17, top=0.88, wspace=0.07)
    panels = [("standard", PENN_BLUE, "Standard Swarm"),
              ("recursive", PENN_RED, f"Recursive Swarm, {layers} Layers")]
    for k, (ax, (kind, color, title)) in enumerate(zip(axes, panels, strict=True)):
        grid_c = tint(color, 0.9)
        ax.axhline(0.5, color=tint(color, 0.7), lw=0.7, ls=(0, (1.5, 2.0)), zorder=1)
        ax.plot(grid, single, color=tint(color, 0.15), lw=1.3, ls=(0, (4.0, 2.0)), label="1 Agent",
                zorder=3)
        for n, white in WHITE_SHARE.items():
            if (kind, n) in curves:
                ax.plot(grid, curves[(kind, n)], color=tint(color, white), lw=1.5,
                        label=f"{n} Agents", zorder=2)
        ax.set_xscale("log")
        ax.set_xlim(6e-4, 1.0)
        ax.set_ylim(0.0, 1.02)
        ax.set_xticks([1e-3, 1e-2, 1e-1, 1.0], ["0.001", "0.01", "0.1", "1"])
        ax.set_xticks([], minor=True)
        ax.set_yticks([0.0, 0.25, 0.5, 0.75, 1.0], ["0", "0.25", "0.5", "0.75", "1"])
        ax.tick_params(length=0, labelsize=TICK_PT, colors=PENN_BLUE)
        ax.grid(True, color=grid_c, lw=0.6)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(tint(PENN_BLUE, 0.35))
        ax.set_xlabel(r"Time in Units of $\mathregular{T_1}$", color=PENN_BLUE, labelpad=3)
        ax.text(0.0, 1.035, "ab"[k], transform=ax.transAxes, fontsize=TEXT_PT + 1.5,
                fontweight="bold", color=PENN_BLUE, va="baseline", ha="left")
        ax.text(0.05, 1.035, title, transform=ax.transAxes, fontsize=TEXT_PT + 0.5,
                color=PENN_BLUE, va="baseline", ha="left")
        leg = ax.legend(loc="upper left", frameon=False, fontsize=TEXT_PT, handlelength=2.2,
                        borderaxespad=0.4, labelspacing=0.3)
        for t in leg.get_texts():
            t.set_color(PENN_BLUE)
    axes[0].set_ylabel("Coverage", color=PENN_BLUE, labelpad=4)
    _check_text(fig)
    out_base.parent.mkdir(parents=True, exist_ok=True)
    paths = [out_base.with_suffix(".pdf"), out_base.with_suffix(".png")]
    fig.savefig(paths[0])
    fig.savefig(paths[1], dpi=300)
    plt.close(fig)
    return paths
