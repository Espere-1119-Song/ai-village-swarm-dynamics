"""F5, the change-point timeline (SPEC 10.3): a full-width thin strip.

x is the date (PT). The top band marks CHANGELOG entries, scaffolding bullets and roster joins and
leaves on one row each, and the village goal transitions on a third row in Penn Red tint. Below it every analysed series has one row, grouped into bands by level
(family and all-agent behaviour, agent behaviour, family words, and external series: monitor
counts and module A and B1 series when they exist), and each PELT (l2) change point is a vertical mark at its date: Penn Blue when a CHANGELOG
entry lies within w run days, Penn Red when none does. Only Penn Blue (#011F5B), Penn Red (#990000)
and their tints are used, text is never white, and the layout is set in inches after the plot skill
of github.com/wenhaochai/claude-plugins (light grid, baseline axis only, no tick marks, no title).
`plot_timeline` raises if any two text labels overlap or a label leaves the canvas.

Data: outputs/tables/changepoints.csv and data/processed/changelog.parquet. AI Digest, "AI
Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors as mcolors  # noqa: E402
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import polars as pl  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.text import Text  # noqa: E402

PENN_BLUE, PENN_RED = "#011F5B", "#990000"
TEXT_PT, TICK_PT = 7.35, 7.0
WIDTH = 7.6
M_SIDE, M_TOP, M_LEFT = 0.19, 0.19, 0.82
LEGEND_H, GAP_LEGEND, XTICKS_H, M_BOTTOM = 0.12, 0.16, 0.17, 0.10
ENTRY_ROW, ENTRY_GAP, BAND_GAP, PAD_BOTTOM = 0.13, 0.07, 0.05, 0.04
BANDS_TOTAL, BAND_MIN = 1.25, 0.22
LEVELS = {"family": "Family", "agent": "Agent", "lexical": "Lexical", "external": "External"}


def tint(color: str, white: float) -> str:
    """`color` mixed with white (`white` = share of white, 0 to 1)."""
    return mcolors.to_hex([c + (1.0 - c) * white for c in mcolors.to_rgb(color)])


ENTRY_COLOR, GRID_COLOR, AXIS_COLOR = tint(PENN_BLUE, 0.45), tint(PENN_BLUE, 0.9), tint(PENN_BLUE, 0.35)
GOAL_COLOR = tint(PENN_RED, 0.45)


def _font() -> str:
    names = {f.name for f in font_manager.fontManager.ttflist}
    return next((f for f in ("Nimbus Sans", "Liberation Sans", "Arial") if f in names), "DejaVu Sans")


def _check_text(fig: plt.Figure) -> None:
    """Raise when two visible text labels overlap or one leaves the canvas."""
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    boxes = []
    for t in fig.findobj(Text):
        if not t.get_visible() or not t.get_text().strip():
            continue
        boxes.append((t.get_text(), t.get_window_extent(r)))
    W, H = fig.bbox.width, fig.bbox.height
    for name, b in boxes:
        if b.x0 < -0.5 or b.y0 < -0.5 or b.x1 > W + 0.5 or b.y1 > H + 0.5:
            raise ValueError(f"F5: text {name!r} leaves the canvas")
    for i, (n1, b1) in enumerate(boxes):
        for n2, b2 in boxes[i + 1:]:
            if b1.overlaps(b2):
                raise ValueError(f"F5: texts {n1!r} and {n2!r} overlap")


def plot_timeline(cps: pl.DataFrame, entries: pl.DataFrame, series: pl.DataFrame, out_base: Path,
                  goals: pl.DataFrame | None = None) -> list[Path]:
    """Draw F5 and write `<out_base>.pdf` and `.png`.

    `cps`: series_id, date, aligned (one method). `entries`: source, date_start (CHANGELOG).
    `series`: series_id, level of every analysed series, in row order. `goals`: date_start of the
    village goal transitions, drawn on a third top row in Penn Red tint.
    """
    plt.rcParams.update({
        "font.family": [_font(), "DejaVu Sans"], "font.size": TEXT_PT, "text.color": PENN_BLUE,
        "axes.edgecolor": AXIS_COLOR, "axes.labelcolor": PENN_BLUE, "xtick.color": PENN_BLUE,
        "ytick.color": PENN_BLUE, "xtick.labelsize": TICK_PT, "ytick.labelsize": TEXT_PT,
        "xtick.major.size": 0, "ytick.major.size": 0, "xtick.minor.size": 0, "ytick.minor.size": 0,
        "pdf.fonttype": 42, "savefig.bbox": None,
    })
    levels = [lv for lv in LEVELS if series.filter(pl.col("level") == lv).height]
    n_lv = {lv: series.filter(pl.col("level") == lv).height for lv in levels}
    weight = {lv: n ** 0.5 for lv, n in n_lv.items()}
    total_w = sum(weight.values()) or 1.0
    room = BANDS_TOTAL - BAND_GAP * (len(levels) - 1)
    heights = {lv: max(BAND_MIN, room * weight[lv] / total_w) for lv in levels}
    top_rows = [("changelog", "Scaffolding", ENTRY_COLOR), ("roster", "Roster", ENTRY_COLOR)]
    if goals is not None and goals.height:
        top_rows.append(("goal", "Goal", GOAL_COLOR))
    ax_h = (len(top_rows) * ENTRY_ROW + ENTRY_GAP + sum(heights.values()) + BAND_GAP * (len(levels) - 1)
            + PAD_BOTTOM)
    fig_h = M_TOP + LEGEND_H + GAP_LEGEND + ax_h + XTICKS_H + M_BOTTOM
    fig = plt.figure(figsize=(WIDTH, fig_h))
    ax = fig.add_axes((M_LEFT / WIDTH, (XTICKS_H + M_BOTTOM) / fig_h,
                       (WIDTH - M_LEFT - M_SIDE) / WIDTH, ax_h / fig_h))
    ax.set_ylim(0, ax_h)  # one y unit is one inch
    pt = 1.0 / 72.0

    # CHANGELOG rows at the top.
    yticks, ylabels = [], []
    top = ax_h
    for src, label, color in top_rows:
        d = (goals if src == "goal" else entries.filter(pl.col("source") == src))["date_start"].to_list()
        ax.vlines(mdates.date2num(d), top - ENTRY_ROW + 1.5 * pt, top - 1.5 * pt, color=color,
                  linewidth=0.7)
        yticks.append(top - ENTRY_ROW / 2)
        ylabels.append(label)
        top -= ENTRY_ROW
    top -= ENTRY_GAP
    ax.axhline(top + ENTRY_GAP / 2, color=GRID_COLOR, linewidth=0.6)

    # Change-point bands.
    row = {}
    for i, lv in enumerate(levels):
        ids = series.filter(pl.col("level") == lv)["series_id"].to_list()
        h = heights[lv]
        pitch = h / len(ids)
        for k, sid in enumerate(ids):
            row[sid] = (top - (k + 0.5) * pitch, max(pitch / 2, 1.1 * pt))
        yticks.append(top - h / 2)
        ylabels.append(LEVELS[lv])
        top -= h
        if i < len(levels) - 1:
            ax.axhline(top - BAND_GAP / 2, color=GRID_COLOR, linewidth=0.6)
            top -= BAND_GAP
    pos = cps.filter(pl.col("series_id").is_in(list(row)))
    for aligned, color in ((True, PENN_BLUE), (False, PENN_RED)):
        sub = pos.filter(pl.col("aligned") == aligned)
        if sub.is_empty():
            continue
        y = [row[s] for s in sub["series_id"].to_list()]
        ax.vlines(mdates.date2num(sub["date"].to_list()), [c - h for c, h in y], [c + h for c, h in y],
                  color=color, linewidth=0.55)

    all_dates = [*entries["date_start"].to_list(), *cps["date"].to_list(),
                 *(goals["date_start"].to_list() if goals is not None else [])]
    lo, hi = min(all_dates), max(all_dates)
    x0, x1 = date(lo.year, lo.month, 1), date(hi.year + (hi.month == 12), hi.month % 12 + 1, 1)
    ax.set_xlim(mdates.date2num(x0) - 3, mdates.date2num(x1) + 3)
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 4, 7, 10)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_minor_locator(mdates.MonthLocator())
    ax.grid(True, axis="x", which="both", color=GRID_COLOR, linewidth=0.5)
    ax.set_axisbelow(True)
    ax.set_yticks(yticks, ylabels)
    for side in ("left", "right", "top"):
        ax.spines[side].set_visible(False)
    ax.tick_params(axis="both", length=0, pad=3.5)

    handles = [
        Line2D([], [], color=PENN_BLUE, marker="|", linestyle="None", markersize=8, markeredgewidth=1.4,
               label="Aligned change point"),
        Line2D([], [], color=PENN_RED, marker="|", linestyle="None", markersize=8, markeredgewidth=1.4,
               label="Unaligned change point"),
        Line2D([], [], color=ENTRY_COLOR, marker="|", linestyle="None", markersize=8,
               markeredgewidth=1.4, label="CHANGELOG entry"),
    ]
    if any(src == "goal" for src, _, _ in top_rows):
        handles.append(Line2D([], [], color=GOAL_COLOR, marker="|", linestyle="None", markersize=8,
                              markeredgewidth=1.4, label="Goal transition"))
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(M_LEFT / WIDTH, 1 - M_TOP / fig_h),
               ncol=len(handles), frameon=False, fontsize=TEXT_PT, handlelength=0.8, handletextpad=0.4,
               columnspacing=1.8, borderaxespad=0.0, borderpad=0.0)
    _check_text(fig)
    out_base = Path(out_base)
    out_base.parent.mkdir(parents=True, exist_ok=True)
    paths = [out_base.with_suffix(".pdf"), out_base.with_suffix(".png")]
    fig.savefig(paths[0])
    fig.savefig(paths[1], dpi=300)
    plt.close(fig)
    return paths
