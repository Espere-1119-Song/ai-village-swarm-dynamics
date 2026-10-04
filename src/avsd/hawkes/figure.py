"""Module A figures (SPEC 10.3): F1 excitation heatmaps, F2 activity shares, and the QQ plots of
the time-rescaling check (SPEC 5.6-2).

Style as F5 and F6: Penn Blue #011F5B, Penn Red #990000 and their tints only, no white text, every
label capitalised, a light grid, no tick marks and no titles; sizes are set in inches. Every figure
raises if two text labels overlap or a label leaves the canvas (changepoint.figure._check_text).

F1: one small heatmap of N = [n_ij] per accepted goal window and group, in date order, wrapped into
rows of PER_ROW panels. Rows are target agents and columns source agents, both ordered by spectral
cluster (report.spectral_blocks), then the human and system columns after a gap. Thin Penn Red
lines separate the clusters. One colour scale (square-root) for all panels.

F2: activity shares over time as a stacked area, in three SPEC categories (SPEC 10.3 "three parts";
SPEC 5.5 four-way with self and other agents pooled): agent-triggered (other agents and self),
human and system (the exogenous sources pooled, as in the SPEC 5.5 human share), and baseline.
Each goal window is a step over its dates. Where groups overlap (best and rest in R2) their shares
are pooled with weights equal to their agent events per run day. A step runs to the start of the
next window across gaps of at most a week (weekends between goals); longer gaps (a window left
out) stay empty. The hatched bands are 95% bootstrap intervals of the two boundaries (replicate r
of every group pooled the same way).

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import math
from datetime import timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, PowerNorm  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from avsd.changepoint.figure import PENN_BLUE, PENN_RED, _check_text, _font, tint  # noqa: E402

TEXT_PT, TICK_PT = 7.35, 7.0
WIDTH = 7.6
PER_ROW = 9
GRID_COLOR, AXIS_COLOR = tint(PENN_BLUE, 0.9), tint(PENN_BLUE, 0.35)


def _style() -> None:
    plt.rcParams.update({
        "font.family": [_font(), "DejaVu Sans"], "font.size": TEXT_PT, "text.color": PENN_BLUE,
        "axes.edgecolor": AXIS_COLOR, "axes.labelcolor": PENN_BLUE, "xtick.color": PENN_BLUE,
        "ytick.color": PENN_BLUE, "xtick.labelsize": TICK_PT, "ytick.labelsize": TICK_PT,
        "xtick.major.size": 0, "ytick.major.size": 0, "xtick.minor.size": 0, "ytick.minor.size": 0,
        "pdf.fonttype": 42, "savefig.bbox": None, "hatch.linewidth": 0.5,
    })


def _save(fig: plt.Figure, base: Path) -> list[Path]:
    base = Path(base)
    try:
        _check_text(fig)
    except ValueError as e:      # the shared check names F5 in its message
        raise ValueError(f"{base.name}: {str(e).removeprefix('F5: ')}") from None
    base.parent.mkdir(parents=True, exist_ok=True)
    paths = [base.with_suffix(".pdf"), base.with_suffix(".png")]
    fig.savefig(paths[0])
    fig.savefig(paths[1], dpi=300)
    plt.close(fig)
    return paths


def panel_label(w) -> str:
    """"G12, General"; long room names keep their first word ("Universe")."""
    parts = w.group.split("-")
    room = parts[0].capitalize() if len(w.group) > 12 else "-".join(p.capitalize() for p in parts)
    return f"{w.window_id.upper()}, {room}"


def _sorted(windows):
    return sorted(windows, key=lambda w: (w.date_start, w.group))


def _panel_label(ax, w) -> None:
    """The panel label 2 pt above the panel's top left corner, whatever the panel size."""
    ax.annotate(panel_label(w), xy=(0.0, 1.0), xycoords="axes fraction", xytext=(0.0, 2.0),
                textcoords="offset points", fontsize=5.6, va="bottom", ha="left")


# --- F1 -------------------------------------------------------------------------------------------


def plot_f1(windows, fits, blocks, out_base: Path) -> list[Path]:
    from avsd.hawkes.report import agent_order

    _style()
    ws = _sorted(windows)
    n = len(ws)
    cols = min(PER_ROW, n)
    rows = math.ceil(n / cols)
    left, right, top, bottom = 0.30, 0.12, 0.10, 0.62
    gap_x, gap_y, label_h = 0.06, 0.06, 0.15
    cell = (WIDTH - left - right - gap_x * (cols - 1)) / cols
    height = top + rows * (label_h + cell) + (rows - 1) * gap_y + bottom
    fig = plt.figure(figsize=(WIDTH, height))
    cmap = LinearSegmentedColormap.from_list("penn", [tint(PENN_BLUE, 0.97), tint(PENN_BLUE, 0.5), PENN_BLUE])
    vals = np.concatenate([fits[w.key].fit.n.ravel() for w in ws])
    vmax = float(np.quantile(vals, 0.99)) or 1.0
    norm = PowerNorm(0.5, vmin=0.0, vmax=vmax)
    im = None
    for k, w in enumerate(ws):
        r = fits[w.key]
        K = r.K
        lab = blocks[w.key]
        order = agent_order(lab, r.fit.n[:, :K])
        m = np.full((K, K + 3), np.nan)
        m[:, :K] = r.fit.n[np.ix_(order, order)]
        m[:, K + 1:] = r.fit.n[order, K:]
        row, col = divmod(k, cols)
        x0 = left + col * (cell + gap_x)
        y0 = height - top - label_h - row * (label_h + cell + gap_y) - cell
        ax = fig.add_axes((x0 / WIDTH, y0 / height, cell / WIDTH, cell / height))
        im = ax.imshow(np.ma.masked_invalid(np.minimum(m, vmax)), cmap=cmap, norm=norm, aspect="auto",
                       interpolation="nearest")
        ls = lab[order]
        for b in np.flatnonzero(np.diff(ls)) + 0.5:
            ax.axhline(b, color=PENN_RED, linewidth=0.4)
            ax.axvline(b, color=PENN_RED, linewidth=0.4)
        ax.set_xticks([]), ax.set_yticks([])
        for s in ax.spines.values():
            s.set_linewidth(0.4)
        _panel_label(ax, w)
    cb_x, cb_w = left + 0.45 * (WIDTH - left - right), 0.45 * (WIDTH - left - right)
    cax = fig.add_axes((cb_x / WIDTH, 0.26 / height, cb_w / WIDTH, 0.07 / height))
    cb = fig.colorbar(im, cax=cax, orientation="horizontal")
    cb.outline.set_linewidth(0.4)
    cb.ax.tick_params(labelsize=TICK_PT, pad=2)
    fig.text((cb_x - 0.08) / WIDTH, 0.295 / height, "Branching Ratio n_ij (Square-Root Scale)", ha="right",
             va="center")
    fig.text(left / 2 / WIDTH, (height - top - (height - top - bottom) / 2) / height, "Target Agent", rotation=90,
             va="center", ha="center")
    fig.text((left + (WIDTH - left - right) / 2) / WIDTH, (bottom - 0.12) / height,
             "Source: Agents by Cluster, Then Human and System", ha="center", va="center")
    return _save(fig, out_base)


# --- F2 -------------------------------------------------------------------------------------------


def f2_series(windows, fits, boots) -> dict:
    """Pooled three-way shares (agent-triggered, exogenous, baseline) per date segment, with
    bootstrap replicates (module docstring)."""
    ws = [w for w in windows if boots.get(w.key) is not None]
    edges = sorted({w.date_start for w in ws} | {w.date_end + timedelta(days=1) for w in ws})
    R = min(int(boots[w.key][0].shares.shape[0]) for w in ws)
    seg_x, point, reps = [], [], []
    for a, b in zip(edges[:-1], edges[1:]):
        on = [w for w in ws if w.date_start <= a and w.date_end >= b - timedelta(days=1)]
        if not on:
            continue
        wt = np.array([fits[w.key].n_events / fits[w.key].n_days for w in on])
        s3 = np.array([_three(fits[w.key].shares) for w in on])
        r3 = np.stack([_three(boots[w.key][0].shares[:R]) for w in on])       # (G, R, 3)
        seg_x.append((a, b))
        point.append(wt @ s3 / wt.sum())
        reps.append(np.einsum("g,grc->rc", wt, r3) / wt.sum())
    return {"segments": seg_x, "point": np.array(point), "reps": np.stack(reps, 1)}   # reps (R, S, 3)


def _three(s: np.ndarray) -> np.ndarray:
    """(..., 5) shares -> (..., 3): agent-triggered (other + self), exogenous (human + system), baseline."""
    s = np.asarray(s)
    return np.stack([s[..., 3] + s[..., 4], s[..., 1] + s[..., 2], s[..., 0]], -1)


def plot_f2(windows, fits, boots, out_base: Path) -> list[Path]:
    if not any(boots.get(w.key) is not None for w in windows):
        return []
    _style()
    s = f2_series(windows, fits, boots)
    segs = s["segments"]
    cum = np.cumsum(s["point"], 1)                # boundaries: agent, agent + exogenous, 1
    rc = np.cumsum(s["reps"], 2)
    lo, hi = np.quantile(rc, [0.025, 0.975], axis=0)
    runs, xs = [[]], []                           # runs of segments joined across short gaps
    for k, (a, b) in enumerate(segs):
        nxt = segs[k + 1][0] if k + 1 < len(segs) else b
        joined = (nxt - b).days <= 7
        xs.append((mdates.date2num(a), mdates.date2num(nxt if joined else b)))
        runs[-1].append(k)
        if not joined and k + 1 < len(segs):
            runs.append([])
    fig = plt.figure(figsize=(WIDTH, 2.4))
    ax = fig.add_axes((0.08, 0.12, 0.90, 0.74))
    colors = (tint(PENN_BLUE, 0.45), tint(PENN_RED, 0.25), tint(PENN_BLUE, 0.85))
    names = ("Agent-Triggered", "Human and System", "Baseline")
    for run in runs:
        x = np.array([v for k in run for v in xs[k]])
        base = np.zeros(x.size)
        for c in range(3):
            y = np.repeat(cum[run, c], 2)
            ax.fill_between(x, base, y, color=colors[c], linewidth=0)
            base = y
        for c, color in ((0, PENN_BLUE), (1, PENN_RED)):
            ax.fill_between(x, np.repeat(lo[run, c], 2), np.repeat(hi[run, c], 2), facecolor="none",
                            edgecolor=color, hatch="//////", linewidth=0.0)
    ax.set_ylim(0, 1)
    ax.set_xlim(xs[0][0] - 3, xs[-1][1] + 3)
    ax.set_ylabel("Share of Agent Messages")
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 4, 7, 10)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_minor_locator(mdates.MonthLocator())
    ax.grid(True, axis="x", which="both", color=GRID_COLOR, linewidth=0.5)
    ax.grid(True, axis="y", color=GRID_COLOR, linewidth=0.5)
    ax.tick_params(axis="x", pad=6)        # keeps the first month label clear of the "0.0" tick label
    ax.set_axisbelow(False)
    for side in ("right", "top"):
        ax.spines[side].set_visible(False)
    handles = [Patch(facecolor=c, label=n) for c, n in zip(colors, names)]
    handles.append(Patch(facecolor="none", edgecolor=PENN_BLUE, hatch="//////", linewidth=0.0, label="95% Interval"))
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.08, 0.99), ncol=4, frameon=False,
               fontsize=TEXT_PT, handlelength=1.2, columnspacing=1.6, borderaxespad=0.0)
    return _save(fig, out_base)


# --- QQ (SPEC 5.6-2) -----------------------------------------------------------------------------------


def plot_qq(windows, fits, valids, out_base: Path) -> list[Path]:
    from avsd.hawkes.pipeline import QQ_PROBS

    _style()
    ws = [w for w in _sorted(windows) if valids.get(w.key) is not None]
    n = len(ws)
    cols = min(PER_ROW, n)
    rows = math.ceil(n / cols)
    left, right, top, bottom, gap_x, gap_y, label_h = 0.42, 0.10, 0.30, 0.36, 0.10, 0.08, 0.15
    cell = (WIDTH - left - right - gap_x * (cols - 1)) / cols
    height = top + rows * (label_h + cell) + (rows - 1) * gap_y + bottom
    fig = plt.figure(figsize=(WIDTH, height))
    theo = -np.log1p(-QQ_PROBS)
    lim = 6.0
    for k, w in enumerate(ws):
        v = valids[w.key]
        row, col = divmod(k, cols)
        x0 = left + col * (cell + gap_x)
        y0 = height - top - label_h - row * (label_h + cell + gap_y) - cell
        ax = fig.add_axes((x0 / WIDTH, y0 / height, cell / WIDTH, cell / height))
        ax.plot([0, lim], [0, lim], color=PENN_RED, linewidth=0.6, linestyle="--")
        for q, m in zip(v["qq"], v["ks_n"]):
            if m >= 20 and np.isfinite(q).all():
                ax.plot(theo, np.minimum(q, lim), color=tint(PENN_BLUE, 0.65), linewidth=0.35)
        if v["qq_pooled"] is not None:
            ax.plot(theo, np.minimum(v["qq_pooled"], lim), color=PENN_BLUE, linewidth=0.9)
        ax.set_xlim(0, lim), ax.set_ylim(0, lim)
        ax.set_xticks([]), ax.set_yticks([])
        for s in ax.spines.values():
            s.set_linewidth(0.4)
        _panel_label(ax, w)
    handles = [plt.Line2D([], [], color=PENN_BLUE, linewidth=0.9, label="All Agents"),
               plt.Line2D([], [], color=tint(PENN_BLUE, 0.65), linewidth=0.6, label="One Agent (20+ Gaps)"),
               plt.Line2D([], [], color=PENN_RED, linewidth=0.6, linestyle="--", label="Exp(1)")]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(left / WIDTH, 1 - 0.04 / height), ncol=3,
               frameon=False, fontsize=TEXT_PT, handlelength=1.4, columnspacing=1.6, borderaxespad=0.0)
    fig.text(left / 2 / WIDTH, 0.5, "Rescaled Gap Quantile (0 to 6)", rotation=90, va="center", ha="center")
    fig.text(0.5, (bottom / 2) / height, "Exp(1) Quantile (0 to 6)", ha="center", va="center")
    return _save(fig, out_base)
