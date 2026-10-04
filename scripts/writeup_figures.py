"""Figures of reports/writeup.md, drawn with the plot style of wenhaochai/claude-plugins (scripts/plot_style).

    python scripts/writeup_figures.py      # writes reports/figures/<name>.pdf and .png

Every number comes from an aggregate table in outputs/tables/:
  overview      no data; the question tree of the write-up
  depgraph_example depgraph_example_nodes.csv and depgraph_example_edges.csv (scripts/depgraph_example.py)
  sources       writeup_cis.csv (pooled shares) and hawkes_windows.csv (accepted windows in order of their start)
  rho           hawkes_windows.csv, spectral radius of each accepted window with its bootstrap interval
  memory        memory_retention_v2.csv and memory_hazard_v2.csv, rule set v2, scope family
  durability    memory_hazard_v2.csv and memory_h2_v2.csv (geometric and beta-geometric fits, rule set v2) and
                memory_v1_v2_v3.csv (shape c' among survivors of the first consolidation, three rule sets)
  switch        memory_h2_v2.csv (hazards before and after the switch, rule set v2) and
                memory_post_switch_rise.csv (paired differences, three rule sets)
  offspring     trees_generations.csv, MAP forest
  h1            trees_h1_intervals_determined.csv, medians on determined paths
  tk            trees_h1_tk.csv, mean and variance of T_k on the MAP forest with the weighted linear trend
  h3            trees_h3.csv, c by channel and the consolidation counterparts under rule sets v1 to v3
  continuation  depgraph_continuation.csv, measure with_parents, edges all
  structure     depgraph_structure.csv, scope pooled, all edges; observed and generator quantiles over the
                generator mean
  stepcost      depgraph_cost_by_layer.csv, all edges, relative depth
  changepoints  changepoints.csv (PELT l2, levels agent, family and lexical) and changelog_dates.csv,
                exported from data/processed/changelog.parquet (entry dates and categories only)
  weekdays      the weekday table of outputs/qa/changepoint.md, section 9 (run days, change points of daily
                series and village goal transitions)
  labels        memory_label_metrics.csv, weighted scheme, label loss
  reproduction  swarmsim_reproduction.csv, the 15 required checks
Colours are the style's Google GM2 tones: categories take blue, red, yellow and green in that order, bars the
400 tone, points and lines the 600 tone, and references and baselines grey. Labels are Latin, so no extra font is
needed.
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import matplotlib.dates as mdates
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "plot_style"))
from style import (GREY_300, GREY_400, GREY_500, GREY_600, GREY_700, INK, TEXT_PT, TICK, WIDTH_TEXT, apply_style,  # noqa: E402
                   canvas, nice_y, panel_label, room, save, tone, y_values)

TABLES = ROOT / "outputs" / "tables"
OUT = ROOT / "reports" / "figures"
B6, B4, B3, B2 = tone("blue", 600), tone("blue", 400), tone("blue", 300), tone("blue", 200)
R6, R4, R3 = tone("red", 600), tone("red", 400), tone("red", 300)
Y4, G4 = tone("yellow", 400), tone("green", 400)
KW = dict(width=WIDTH_TEXT, side=0, title_pt=10.5)


def rows(name: str) -> list[dict]:
    with open(TABLES / name, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def quantities(fig, texts):
    for q, t in zip(fig._style["quantities"], texts):
        q.set_text(t)


def xlabels(fig, axes, texts):
    for ax, t in zip(axes, texts):
        ax.set_xlabel(t, fontsize=TEXT_PT, weight="medium", color=INK, labelpad=6)


def whiskers(ax, x, lo, hi, color, lw=1.0):
    for xi, a, b in zip(x, lo, hi):
        ax.plot([xi, xi], [a, b], color=color, lw=lw, solid_capstyle="butt", zorder=2)


def hwhiskers(ax, y, lo, hi, color, lw=1.0):
    for yi, a, b in zip(y, lo, hi):
        ax.plot([a, b], [yi, yi], color=color, lw=lw, solid_capstyle="butt", zorder=2)


def date_axis(ax, start, end):
    ax.set_xlim(start, end)
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=(1, 4, 7, 10)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))


OVERVIEW = [
    ("Chat", "Excitation model", ("Self-excitation is the largest source", "Cascades between agents die out")),
    ("Memory", "Fact tracking", ("A third of new facts lost in one rewrite", "Facts that survive grow safer")),
    ("Retelling", "Transmission trees", ("Reaches fewer agents than it could", "Slower and changed with each retelling")),
    ("Shared work", "Dependency graphs", ("Agents continue their own work", "Denser graphs, flat cost with depth")),
    ("Scaffolding", "Change points", ("No alignment with changes beyond chance", "Clusters at goal starts and Mondays")),
]


def fig_overview():
    """The question tree of the write-up, drawn left to right like the task DAGs of Chai (2026)."""
    import matplotlib.pyplot as plt
    from matplotlib.path import Path as MPath
    from matplotlib.patches import PathPatch
    hues = ("blue", "red", "yellow", "green", "purple")
    W, H = WIDTH_TEXT, 3.05
    fig = plt.figure(figsize=(W, H))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.axis("off")
    x_root, x_q, x_m, x_f = 1.14, 1.92, 2.98, 4.06
    ys = np.linspace(H - 0.32, 0.3, len(OVERVIEW))
    y_root = float(np.mean(ys))

    def curve(x0, y0, x1, y1, color, lw=1.1):
        dx = (x1 - x0) * 0.5
        path = MPath([(x0, y0), (x0 + dx, y0), (x1 - dx, y1), (x1, y1)],
                     [MPath.MOVETO, MPath.CURVE4, MPath.CURVE4, MPath.CURVE4])
        ax.add_patch(PathPatch(path, facecolor="none", edgecolor=color, lw=lw, capstyle="round", zorder=1))

    def dot(x, y, color, size=5.2):
        ax.plot([x], [y], "o", ms=size, color=color, mec="white", mew=0.8, zorder=3)

    for (q, m, fs), hue, y in zip(OVERVIEW, hues, ys):
        strong, soft = tone(hue, 900 if hue == "yellow" else 600), tone(hue, 300)
        curve(x_root, y_root, x_q, y, soft)
        curve(x_q, y, x_m, y, soft)
        for k, f in enumerate(fs):
            yf = y + (0.15 if k == 0 else -0.15)
            curve(x_m, y, x_f, yf, soft)
            dot(x_f, yf, strong, 4.4)
            ax.text(x_f + 0.08, yf, f, ha="left", va="center", fontsize=TEXT_PT, color=INK)
        dot(x_q, y, strong)
        dot(x_m, y, strong)
        ax.text(x_q - 0.02, y - 0.075, q, ha="left", va="top", fontsize=TEXT_PT, weight="semibold", color=INK)
        ax.text(x_m + 0.02, y + 0.075, m, ha="right", va="bottom", fontsize=TEXT_PT, weight="medium", color=INK)
    dot(x_root, y_root, GREY_600, 6.2)
    ax.text(x_root - 0.1, y_root, "How strongly do\nagents influence\neach other?", ha="right", va="center",
            fontsize=TEXT_PT + 0.6, weight="semibold", color=INK, linespacing=1.25)
    save(fig, OUT / "overview", flush=True)


def fig_sources():
    cis = {r["quantity"]: r for r in rows("writeup_cis.csv")}
    key = "A: share of agent messages triggered by {}, event-weighted over the 43 goal windows (normal-interval alternative)"
    cats = [("self", "self", "Self", B4), ("other_agents", "other agents", "Other agents", R4), ("human", "human", "Human", Y4),
            ("system", "system", "System", G4), ("baseline", "baseline", "Baseline", GREY_400)]
    win = sorted((r for r in rows("hawkes_windows.csv") if r["accepted"].lower() == "true"),
                 key=lambda r: (r["date_start"], r["group"]))
    fig, axes = canvas(1, 1, panel_height=1.7, quantity="Share of agent messages (%)", ticks="left",
                       legend=[(name, col, "box") for _, _, name, col in cats], **KW)
    ax = axes[0, 0]
    pooled = [100 * float(cis[key.format(k)]["value"]) for _, k, _, _ in cats]
    xs = [0.0] + [4.0 + i for i in range(len(win))]
    shares = [pooled] + [[100 * float(r[f"share_{c}"]) for c, _, _, _ in cats] for r in win]
    bottom = np.zeros(len(xs))
    for j, (_, _, _, col) in enumerate(cats):
        v = np.array([s[j] for s in shares])
        ax.bar(xs, v, bottom=bottom, width=0.8, color=col, edgecolor="white", linewidth=0.3, zorder=2)
        bottom += v
    ticks, labels = [0.0], ["Pooled"]
    for y, m in ((2025, 4), (2025, 7), (2025, 10), (2026, 1), (2026, 4), (2026, 7)):
        first = next(i for i, r in enumerate(win) if date.fromisoformat(r["date_start"]) >= date(y, m, 1)) if (y, m) != (2025, 4) else 0
        ticks.append(xs[1 + first])
        labels.append(date(y, m, 1).strftime("%b %Y"))
    ax.set_xticks(ticks, labels)
    ax.xaxis.grid(False)
    ax.set_ylim(0, 100)
    y_values(ax, [0, 25, 50, 75, 100])
    ax.set_xlim(-0.7, xs[-1] + 0.7)
    save(fig, OUT / "sources", flush=True)


def fig_rho():
    win = [r for r in rows("hawkes_windows.csv") if r["accepted"].lower() == "true"]
    fig, axes = canvas(1, 1, panel_height=1.55, quantity="Spectral radius ρ of agent-to-agent excitation",
                       legend=[("Below 1", B6, "dot"), ("Above 1", R6, "dot")], **KW)
    ax = axes[0, 0]
    cap = 2.0
    for r in win:
        s, e = date.fromisoformat(r["date_start"]), date.fromisoformat(r["date_end"])
        x = s + (e - s) / 2
        rho, lo, hi = float(r["rho"]), float(r["rho_lo"]), min(float(r["rho_hi"]), cap)
        ax.plot([x, x], [lo, hi], color=B3 if rho < 1 else R3, lw=1.2, zorder=2)
        ax.plot([x], [rho], "o", ms=3.6, color=B6 if rho < 1 else R6, zorder=3)
    ax.set_ylim(0, cap)
    y_values(ax, [0, 0.5, 1.0, 1.5, 2.0], "{:.1f}")
    date_axis(ax, date(2025, 3, 20), date(2026, 9, 30))
    room(ax)
    panel_label(ax, "42 accepted goal windows")
    save(fig, OUT / "rho", flush=True)


def fig_memory():
    ret = [r for r in rows("memory_retention_v2.csv") if r["scope"] == "family"]
    haz = [r for r in rows("memory_hazard_v2.csv") if r["scope"] == "family" and r["g"].isdigit()]
    fams = ["Anthropic", "OpenAI", "Google", "Other"]
    fig, axes = canvas(1, 2, panel_height=1.6, quantity="x", xlabel="Consolidation g",
                       legend=[("All standard agents", B6), ("One model family", B3), ("Claude Code agent", R6)], **KW)
    quantities(fig, ["Units kept through consolidation g (%, log scale)", "Hazard of loss at consolidation g (%)"])
    a, b = axes[0, 0], axes[0, 1]
    for stratum, col, lw, z in [(f, B3, 0.9, 2) for f in fams] + [("Claude Code", R6, 0.9, 2), ("All standard", B6, 1.6, 3)]:
        rr = sorted((int(r["g"]), 100 * float(r["retention"])) for r in ret if r["stratum"] == stratum and int(r["g"]) <= 30)
        a.plot([0] + [g for g, _ in rr], [100] + [v for _, v in rr], color=col, lw=lw, zorder=z)
        hh = sorted((int(r["g"]), 100 * float(r["h"])) for r in haz if r["stratum"] == stratum and int(r["g"]) <= 20)
        b.plot([g for g, _ in hh], [v for _, v in hh], color=col, lw=lw, zorder=z)
    a.set_yscale("log")
    a.set_ylim(1, 100)
    y_values(a, [1, 3, 10, 30, 100], "{:g}")
    a.set_xticks([0, 5, 10, 15, 20, 25, 30])
    a.set_xlim(0, 30)
    room(a)
    panel_label(a, "Retention", x=5)
    nice_y(b, 0, max(100 * float(r["h"]) for r in haz if int(r["g"]) <= 20), zero=True)
    b.set_xticks([1, 5, 10, 15, 20])
    b.set_xlim(1, 20)
    room(b)
    panel_label(b, "Hazard")
    save(fig, OUT / "memory", flush=True)


def fig_durability():
    haz = sorted((int(r["g"]), 100 * float(r["h"])) for r in rows("memory_hazard_v2.csv")
                 if r["scope"] == "family" and r["stratum"] == "All standard" and r["g"].isdigit() and int(r["g"]) <= 20)
    fit = next(r for r in rows("memory_h2_v2.csv") if r["scope"] == "family" and r["stratum"] == "All standard")
    al, be, hg = float(fit["betageom_alpha"]), float(fit["betageom_beta"]), 100 * float(fit["h_geometric"])
    cp = {(r["version"], r["scope"]): r for r in rows("memory_v1_v2_v3.csv")
          if r["metric"] == "BdW c among survivors of g = 1 (clock restarted)"}
    fig, axes = canvas(1, 2, panel_height=1.6, quantity="x", xlabel=" ",
                       legend=[("Observed, literal match", B6), ("Beta-geometric fit", R6), ("Constant hazard fit", GREY_600, "dash"),
                               ("Anchor and context match", B3, "dot")], **KW)
    quantities(fig, ["Hazard of loss at consolidation g (%)", "Shape c′ among survivors of the first consolidation"])
    a, b = axes[0, 0], axes[0, 1]
    g = np.arange(1, 21)
    a.plot([x for x, _ in haz], [v for _, v in haz], color=B6, lw=1.6, zorder=3)
    a.plot(g, 100 * al / (al + be + g - 1), color=R6, lw=1.2, zorder=3)
    a.plot([1, 20], [hg, hg], color=GREY_600, lw=1.0, ls=(0, (3, 2)), zorder=2)
    nice_y(a, 0, max(v for _, v in haz), zero=True)
    a.set_xticks([1, 5, 10, 15, 20])
    a.set_xlim(1, 20)
    room(a)
    xlabels(fig, [a, b], ["Consolidation g", ""])
    groups = [("All standard", "All standard"), ("pre cohort", "Pre-switch cohort"), ("post cohort", "Post-switch cohort")]
    b.plot([-0.5, 2.5], [1, 1], color=GREY_600, lw=1.0, ls=(0, (3, 2)), zorder=2)
    for i, (scope, _) in enumerate(groups):
        for dx, v in ((-0.22, "v1"), (0.0, "v2"), (0.22, "v3")):
            r = cp[(v, scope)]
            col, soft = (B6, B3) if v == "v2" else (B3, B2)
            whiskers(b, [i + dx], [float(r["lo"])], [float(r["hi"])], soft, lw=1.4)
            b.plot([i + dx], [float(r["value"])], "o", ms=4, color=col, zorder=3)
    b.set_ylim(0.7, 1.05)
    y_values(b, [0.7, 0.8, 0.9, 1.0], "{:.1f}")
    b.set_xticks(range(3), [n for _, n in groups])
    b.xaxis.grid(False)
    b.set_xlim(-0.5, 2.5)
    room(b)
    save(fig, OUT / "durability", flush=True)


def fig_switch():
    h = {r["scope"]: r for r in rows("memory_h2_v2.csv") if r["stratum"] == "All standard"}
    rise = {r["rules"]: r for r in rows("memory_post_switch_rise.csv")}
    fig, axes = canvas(1, 2, panel_height=1.6, quantity="x",
                       legend=[("Consolidation 1", B3, "dot"), ("Consolidation 2", B6, "dot")], **KW)
    quantities(fig, ["Hazard of loss, literal match (%)", "Rise from consolidation 1 to 2 after the switch (points)"])
    a, b = axes[0, 0], axes[0, 1]
    for i, scope in enumerate(("regime:pre", "regime:post")):
        r = h[scope]
        pts = [(i - 0.13, "h1", B3, B2), (i + 0.13, "h2", B6, B3)]
        a.plot([p[0] for p in pts], [100 * float(r[p[1]]) for p in pts], color=GREY_400, lw=0.9, zorder=2)
        for x, k, col, soft in pts:
            whiskers(a, [x], [100 * float(r[f"{k}_lo"])], [100 * float(r[f"{k}_hi"])], soft, lw=1.4)
            a.plot([x], [100 * float(r[k])], "o", ms=4.5, color=col, zorder=3)
    a.set_ylim(0, 60)
    y_values(a, [0, 20, 40, 60])
    a.set_xticks([0, 1], ["Before the switch", "After the switch"])
    a.xaxis.grid(False)
    a.set_xlim(-0.5, 1.5)
    room(a)
    b.plot([-0.5, 2.5], [0, 0], color=GREY_600, lw=1.0, ls=(0, (3, 2)), zorder=2)
    for i, v in enumerate(("v1", "v2", "v3")):
        r = rise[v]
        whiskers(b, [i], [100 * float(r["diff_lo"])], [100 * float(r["diff_hi"])], B3, lw=1.4)
        b.plot([i], [100 * float(r["diff"])], "o", ms=4.5, color=B6, zorder=3)
    b.set_ylim(-5, 15)
    y_values(b, [-5, 0, 5, 10, 15], lambda v: "0" if v == 0 else f"{v:+.0f}".replace("-", "−"))
    b.set_xticks(range(3), ["Anchor match", "Literal match", "Context match"])
    b.xaxis.grid(False)
    b.set_xlim(-0.5, 2.5)
    room(b)
    save(fig, OUT / "switch", flush=True)


def fig_offspring():
    gen = {int(r["generation"]): r for r in rows("trees_generations.csv")}
    chans = [("share_chat_to_memory", "Into another agent's memory", B4), ("share_chat_other", "Chat to chat", R4),
             ("share_history", "Into search answers", Y4)]
    fig, axes = canvas(1, 2, panel_height=1.6, quantity="x", xlabel="Generation",
                       legend=[("Observed", B6, "dot"), ("Expected from agents that lack the unit", GREY_600, "ring")]
                       + [(n, c, "box") for _, n, c in chans], **KW)
    quantities(fig, ["Further acquisitions per acquisition", "Transmissions into the generation (%)"])
    a, b = axes[0, 0], axes[0, 1]
    ks = [0, 1, 2, 3, 4]
    a.plot(ks, [float(gen[k]["offspring_expected"]) for k in ks], color=GREY_400, lw=0.9, zorder=2)
    a.plot(ks, [float(gen[k]["offspring_expected"]) for k in ks], "o", ms=4.5, mfc="white", mec=GREY_600, mew=1.1, zorder=3)
    whiskers(a, ks, [float(gen[k]["offspring_lo"]) for k in ks], [float(gen[k]["offspring_hi"]) for k in ks], B3, lw=1.4)
    a.plot(ks, [float(gen[k]["offspring_mean"]) for k in ks], "o", ms=4.5, color=B6, zorder=4)
    a.set_ylim(0, 0.6)
    y_values(a, [0, 0.2, 0.4, 0.6], "{:.1f}")
    a.set_xticks(ks)
    a.xaxis.grid(False)
    a.set_xlim(-0.5, 4.5)
    room(a)
    gs = [1, 2, 3, 4]
    bottom = np.zeros(len(gs))
    for col_name, _, col in chans:
        v = np.array([100 * float(gen[k][col_name]) for k in gs])
        b.bar(gs, v, bottom=bottom, width=0.6, color=col, edgecolor="white", linewidth=0.3, zorder=2)
        bottom += v
    b.set_ylim(0, 100)
    y_values(b, [0, 25, 50, 75, 100])
    b.set_xticks(gs)
    b.xaxis.grid(False)
    b.set_xlim(0.5, 4.5)
    room(b)
    save(fig, OUT / "offspring", flush=True)


def fig_h1():
    d = [r for r in rows("trees_h1_intervals_determined.csv") if r["reported"].lower() == "true"]
    strata = [("chat_to_memory_other", "Into another agent's memory"), ("chat_to_chat_other", "Chat to chat"),
              ("chat_to_search_answer", "Into search answers")]
    fig, axes = canvas(1, 3, panel_height=1.55, quantity="x", xlabel="Generation", **KW)
    quantities(fig, ["Median serial interval (active hours, log scale)", "", ""])
    for ax, (ch, name) in zip(axes.flat, strata):
        rr = sorted((int(r["generation"]), float(r["median_h"]), float(r["median_lo"]), float(r["median_hi"])) for r in d if r["channel"] == ch)
        g = [x[0] for x in rr]
        whiskers(ax, g, [x[2] for x in rr], [x[3] for x in rr], B3, lw=1.4)
        ax.plot(g, [x[1] for x in rr], "o", ms=4, color=B6, zorder=3)
        ax.set_yscale("log")
        ax.set_ylim(0.03, 5)
        y_values(ax, [0.03, 0.1, 0.3, 1, 3], "{:g}")
        ax.set_xticks([1, 2, 3])
        ax.xaxis.grid(False)
        ax.set_xlim(0.5, 3.5)
        room(ax, right_in=0.05)
        panel_label(ax, name)
    save(fig, OUT / "h1", flush=True)


def fig_tk():
    t = rows("trees_h1_tk.csv")
    ks = [r for r in t if r["row_type"] == "k"]
    fits = {r["quantity"]: r for r in t if r["row_type"] != "k" and r.get("model") == "linear"}
    fig, axes = canvas(1, 2, panel_height=1.55, quantity="x", xlabel="Agent-level generation k",
                       legend=[("Estimate", B6, "dot"), ("Weighted linear trend", GREY_600)], **KW)
    quantities(fig, ["Mean of $T_k$ (active hours)", "Variance of $T_k$ (thousand active hours$^2$)"])
    for ax, (q, lo, hi, scale, fit) in zip(axes.flat, [("mean_h", "mean_lo", "mean_hi", 1, "mean"),
                                                       ("var_h2", "var_lo", "var_hi", 1e-3, "variance")]):
        k = [int(r["k"]) for r in ks]
        v = [scale * float(r[q]) for r in ks]
        whiskers(ax, k, [scale * float(r[lo]) for r in ks], [scale * float(r[hi]) for r in ks], B3, lw=1.4)
        f = fits[fit]
        xs = np.array([1, 5])
        ax.plot(xs, scale * (float(f["intercept"]) + float(f["slope"]) * xs), color=GREY_600, lw=0.9, zorder=2)
        ax.plot(k, v, "o", ms=4, color=B6, zorder=3)
        nice_y(ax, 0, max(scale * float(r[hi]) for r in ks), zero=True)
        ax.set_xticks([1, 2, 3, 4, 5])
        ax.xaxis.grid(False)
        ax.set_xlim(0.5, 5.5)
        room(ax, right_in=0.05)
        panel_label(ax, "Mean" if fit == "mean" else "Variance")
    save(fig, OUT / "tk", flush=True)


def fig_h3():
    h = {(r["channel"], r["rules"]): r for r in rows("trees_h3.csv")}
    items = [(("agent_retelling", "v2"), "All retelling between agents", R4),
             (("chat_to_chat_other", "v2"), "Chat to chat between agents", R4),
             (("chat_to_memory_other", "v2"), "Chat into another agent's memory", R4),
             (("chat_to_search_answer", "v2"), "Chat into search answers", R4),
             (("memory_consolidation_b1_quantities", "v2"), "Consolidation, literal match", B4),
             (("memory_consolidation_b1_quantities", "v3"), "Consolidation, context match", B2),
             (("memory_consolidation_b1_quantities", "v1"), "Consolidation, anchor match", B2)]
    fig, axes = canvas(1, 1, panel_height=1.75, quantity="Carried quantity contexts whose value changes (%)",
                       legend=[("Retelling between agents", R4, "box"), ("Memory consolidation, main rule", B4, "box"),
                               ("Memory consolidation, other rules", B2, "box")], **KW)
    ax = axes[0, 0]
    y = np.arange(len(items))[::-1]
    v = [100 * float(h[k]["c"]) for k, _, _ in items]
    ax.barh(y, v, height=0.62, color=[c for _, _, c in items], zorder=2)
    for yi, k in zip(y, [k for k, _, _ in items]):
        ax.plot([100 * float(h[k]["c_lo"]), 100 * float(h[k]["c_hi"])], [yi, yi], color=TICK, lw=1.0, zorder=3)
    ax.set_yticks(y, [n for _, n, _ in items])
    ax.yaxis.grid(False)
    ax.tick_params(axis="y", labelsize=TEXT_PT)
    ax.set_xlim(0, 50)
    ax.set_xticks([0, 10, 20, 30, 40, 50])
    save(fig, OUT / "h3", flush=True)


def _graph_positions(nodes, layer, parents, agent):
    """Barycentric order within each layer, one sweep left to right; roots grouped by agent."""
    by_layer = defaultdict(list)
    for n in nodes:
        by_layer[layer[n]].append(n)
    pos = {}
    for L in sorted(by_layer):
        def key(n):
            ps = [pos[p] for p in parents[n] if p in pos]
            return (float(np.mean(ps)) if ps else 0.0, agent.get(n, 0), n)
        ns = sorted(by_layer[L], key=(lambda n: (agent.get(n, 0), n)) if L == 0 else key)
        for i, n in enumerate(ns):
            pos[n] = i - (len(ns) - 1) / 2
    return pos, max(len(v) for v in by_layer.values()), max(by_layer) + 1


def _draw_graph(ax, nodes, layer, edges, agent, colour_of, size):
    from matplotlib.collections import PathCollection
    from matplotlib.path import Path as MPath
    parents = defaultdict(list)
    for p, c, _ in edges:
        parents[c].append(p)
    pos, tallest, n_layers = _graph_positions(nodes, layer, parents, agent)
    x = {n: layer[n] / (n_layers - 1) for n in nodes}
    for group in sorted({k for *_, k in edges}):
        paths = []
        for p, c, k in edges:
            if k != group:
                continue
            x0, y0, x1, y1 = x[p], pos[p], x[c], pos[c]
            dx = (x1 - x0) * 0.5
            paths.append(MPath([(x0, y0), (x0 + dx, y0), (x1 - dx, y1), (x1, y1)],
                               [MPath.MOVETO, MPath.CURVE4, MPath.CURVE4, MPath.CURVE4]))
        colour, alpha, z = colour_of[group]
        ax.add_collection(PathCollection(paths, facecolors="none", edgecolors=colour, linewidths=0.55,
                                         alpha=alpha, zorder=z))
    ax.scatter([x[n] for n in nodes], [pos[n] for n in nodes], s=size, color=GREY_700, edgecolors="white",
               linewidths=0.35, zorder=5)
    half = (tallest - 1) / 2
    ax.set_xlim(-0.012, 1.012)
    ax.set_ylim(-half - 0.8, half + 0.8)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.axis("off")


def fig_depgraph_example():
    """One goal's dependency graph and a generator DAG of the same size, drawn layer by layer."""
    nodes = defaultdict(dict)
    for r in rows("depgraph_example_nodes.csv"):
        if r["no_edge"] == "0":
            nodes[r["graph"]][int(r["node"])] = (int(r["layer"]), int(r["agent"]))
    edges = defaultdict(list)
    for r in rows("depgraph_example_edges.csv"):
        kind = "generator" if r["graph"] == "generator" else ("same" if r["same_agent"] == "1" else "other")
        edges[r["graph"]].append((int(r["parent"]), int(r["child"]), kind))
    colour_of = {"same": (B4, 0.55, 2), "other": (R4, 0.8, 3), "generator": (GREY_500, 0.45, 2)}
    fig, axes = canvas(2, 1, panel_height=1.62, gap_rows=0.32, extra=(-0.05, 0, 0, 0),
                       legend=[("Edge within one agent", B4), ("Edge between agents", R4),
                               ("Edge of the generator DAG", GREY_500)], **KW)
    for ax, graph, size, name in ((axes[0, 0], "ai_village", 7.5, "AI Village, goal G43"),
                                  (axes[1, 0], "generator", 3.2, "Generator DAG with the same number of steps")):
        nd = nodes[graph]
        _draw_graph(ax, sorted(nd), {n: v[0] for n, v in nd.items()}, edges[graph],
                    {n: v[1] for n, v in nd.items()}, colour_of, size)
        ax.text(0.0, 1.0, name, transform=ax.transAxes, ha="left", va="bottom", fontsize=TEXT_PT,
                weight="medium", color=INK)
    save(fig, OUT / "depgraph_example", flush=True)


def fig_continuation():
    d = {(r["window"], r["stratum"]): r for r in rows("depgraph_continuation.csv")
         if r["variant"] == "all" and r["measure"] == "with_parents"}
    fig, axes = canvas(1, 2, panel_height=1.55, quantity="Pairs whose earlier session is a parent (%)",
                       legend=[("Observed", B4, "box"), ("Random parents within the run day", GREY_500, "box"),
                               ("Random parents within the goal", GREY_300, "box")], **KW)
    a, b = axes[0, 0], axes[0, 1]
    g, day = d[("goal", "all")], d[("day", "all")]
    vals = [(float(g["rate"]), float(g["rate_ci_low"]), float(g["rate_ci_high"]), B4),
            (float(day["baseline"]), float(day["baseline_ci_low"]), float(day["baseline_ci_high"]), GREY_500),
            (float(g["baseline"]), float(g["baseline_ci_low"]), float(g["baseline_ci_high"]), GREY_300)]
    x = np.arange(3)
    a.bar(x, [100 * v for v, _, _, _ in vals], width=0.62, color=[c for *_, c in vals], zorder=2)
    whiskers(a, x, [100 * l for _, l, _, _ in vals], [100 * h for _, _, h, _ in vals], TICK)
    a.set_xticks(x, ["Observed", "Within day", "Within goal"])
    a.xaxis.grid(False)
    a.set_ylim(0, 100)
    y_values(a, [0, 25, 50, 75, 100])
    a.set_xlim(-0.6, 2.6)
    room(a)
    panel_label(a, "All 50,251 pairs")
    xs, labels = [], []
    for i, (st, name) in enumerate((("regime_pre", "Before the switch"), ("regime_post", "After the switch"))):
        r = d[("goal", st)]
        for j, (v, lo, hi, c) in enumerate(((r["rate"], r["rate_ci_low"], r["rate_ci_high"], B4),
                                            (r["baseline"], r["baseline_ci_low"], r["baseline_ci_high"], GREY_300))):
            xi = i + (j - 0.5) * 0.34
            b.bar([xi], [100 * float(v)], width=0.32, color=c, zorder=2)
            whiskers(b, [xi], [100 * float(lo)], [100 * float(hi)], TICK)
        xs.append(i)
        labels.append(name)
    b.set_xticks(xs, labels)
    b.xaxis.grid(False)
    b.set_ylim(0, 100)
    y_values(b, [0, 25, 50, 75, 100])
    b.set_xlim(-0.6, 1.6)
    room(b)
    panel_label(b, "Same-goal baseline")
    save(fig, OUT / "continuation", flush=True)


def fig_structure():
    s = {r["statistic"]: r for r in rows("depgraph_structure.csv") if r["scope"] == "pooled" and r["edges"] == "all"}
    stats = [("mean_parents", "Parents per step"), ("multi_parent_share", "Steps with two or more parents"),
             ("cross_layer_share", "Edges that skip two or more layers"), ("outdeg_gini", "Gini of children per step"),
             ("top10_child_share", "Children of the top 10% of steps"), ("sibling_merge_share", "Merges between siblings")]
    fig, axes = canvas(1, 1, panel_height=1.6, quantity="AI Village value over the generator mean (log scale)",
                       legend=[("AI Village dependency graphs", B6, "dot"), ("Generator, middle 95% of 64 replicates", GREY_300, "box")], **KW)
    ax = axes[0, 0]
    y = np.arange(len(stats))[::-1]
    for yi, (k, _) in zip(y, stats):
        r = s[k]
        m = float(r["gen_mean"])
        ax.barh([yi], [float(r["gen_p975"]) / m - float(r["gen_p025"]) / m], left=[float(r["gen_p025"]) / m],
                height=0.5, color=GREY_300, zorder=2)
        ax.plot([float(r["observed"]) / m], [yi], "o", ms=4.5, color=B6, zorder=3)
    ax.set_xscale("log")
    ax.set_xlim(0.7, 4)
    ax.set_xticks([0.7, 1, 1.5, 2, 3, 4], ["0.7", "1", "1.5", "2", "3", "4"])
    ax.minorticks_off()
    ax.set_yticks(y, [n for _, n in stats])
    ax.yaxis.grid(False)
    ax.tick_params(axis="y", labelsize=TEXT_PT)
    save(fig, OUT / "structure", flush=True)


def fig_stepcost():
    d = [r for r in rows("depgraph_cost_by_layer.csv") if r["edges"] == "all" and r["axis"] == "relative_depth"]
    mid = {"0": 0.0, "(0, 0.2]": 0.1, "(0.2, 0.4]": 0.3, "(0.4, 0.6]": 0.5, "(0.6, 0.8]": 0.7, "(0.8, 1]": 0.9}
    d = sorted(d, key=lambda r: mid[r["bin"]])
    x = [mid[r["bin"]] for r in d]
    fig, axes = canvas(1, 1, panel_height=1.6, quantity="Session cost relative to layer 0", xlabel="Relative depth in the goal's graph",
                       legend=[("Turns per session", B6), ("Active minutes per session", R6), ("Model cost per step", GREY_600, "dash")], **KW)
    ax = axes[0, 0]
    ax.plot(x, [float(r["blog_vs_layer0"]) for r in d], color=GREY_600, lw=1.1, ls=(0, (3, 2)), zorder=2)
    for col, soft, k, dx in ((B6, B3, "turns_vs_layer0", -0.012), (R6, R3, "active_vs_layer0", 0.012)):
        xs = [xi + dx for xi in x]
        whiskers(ax, xs, [float(r[f"{k}_ci_low"]) for r in d], [float(r[f"{k}_ci_high"]) for r in d], soft, lw=1.4)
        ax.plot(xs, [float(r[k]) for r in d], color=col, lw=1.2, zorder=3)
        ax.plot(xs, [float(r[k]) for r in d], "o", ms=3.8, color=col, zorder=4)
    ax.set_ylim(0, 10)
    y_values(ax, [0, 2, 4, 6, 8, 10])
    ax.set_xticks([0, 0.2, 0.4, 0.6, 0.8, 1.0], ["0", "0.2", "0.4", "0.6", "0.8", "1"])
    ax.set_xlim(-0.05, 1.0)
    room(ax)
    save(fig, OUT / "stepcost", flush=True)


def fig_changepoints():
    cps = [r for r in rows("changepoints.csv") if r["method"] == "pelt_l2" and r["level"] in ("agent", "family", "lexical")]
    ent = rows("changelog_dates.csv")
    start = date(2025, 3, 31)

    def week(d: str) -> date:
        x = date.fromisoformat(d)
        return x - timedelta(days=x.weekday())

    al, un, en = defaultdict(int), defaultdict(int), defaultdict(int)
    for r in cps:
        (al if r["aligned"].lower() == "true" else un)[week(r["date"])] += 1
    for r in ent:
        en[week(r["date_start"])] += 1
    weeks = [start + timedelta(weeks=i) for i in range(0, 80)]
    fig, axes = canvas(2, 1, panel_height=1.15, quantity="Count per week",
                       legend=[("Change points within 3 run days of an entry", B4, "box"), ("Change points without one", R4, "box"),
                               ("CHANGELOG entries", GREY_500, "box")], gap_rows=0.32, **KW)
    a, b = axes[0, 0], axes[1, 0]
    w6 = timedelta(days=5.5)
    a.bar(weeks, [en[w] for w in weeks], width=w6, align="edge", color=GREY_500, zorder=2)
    m = max(en.values())
    step = 5 if m <= 15 else 10
    a.set_ylim(0, step * (m // step + 2))
    y_values(a, list(range(0, step * (m // step + 2) + 1, step)))
    b.bar(weeks, [al[w] for w in weeks], width=w6, align="edge", color=B4, zorder=2)
    b.bar(weeks, [un[w] for w in weeks], width=w6, align="edge", bottom=[al[w] for w in weeks], color=R4, zorder=2)
    nice_y(b, 0, max(al[w] + un[w] for w in weeks), zero=True)
    for ax in (a, b):
        date_axis(ax, date(2025, 3, 24), date(2026, 9, 28))
        room(ax)
    a.tick_params(axis="x", labelbottom=False)
    panel_label(a, "CHANGELOG entries")
    panel_label(b, "PELT change points")
    save(fig, OUT / "changepoints", flush=True)


def qa_table(name: str, header: str) -> list[dict]:
    lines = (ROOT / "outputs" / "qa" / name).read_text(encoding="utf-8").splitlines()
    i = lines.index(header)
    body = []
    for line in lines[i:]:
        if not line.startswith("|"):
            break
        body.append([c.strip() for c in line.strip("|").split("|")])
    return [dict(zip(body[0], r)) for r in body[2:]]


def fig_weekdays():
    d = qa_table("changepoint.md", "| weekday | run_days | daily_series_changepoints | goal_transitions |")
    sets = [("run_days", "Run days", GREY_400), ("daily_series_changepoints", "Change points of daily series", B4),
            ("goal_transitions", "Village goal transitions", R4)]
    fig, axes = canvas(1, 1, panel_height=1.5, quantity="Share of each set (%)",
                       legend=[(n, c, "box") for _, n, c in sets], **KW)
    ax = axes[0, 0]
    x = np.arange(len(d))
    for j, (k, _, col) in enumerate(sets):
        tot = sum(int(r[k]) for r in d)
        ax.bar(x + (j - 1) * 0.26, [100 * int(r[k]) / tot for r in d], width=0.25, color=col, zorder=2)
    ax.set_xticks(x, [r["weekday"] for r in d])
    ax.xaxis.grid(False)
    ax.set_ylim(0, 80)
    y_values(ax, [0, 20, 40, 60, 80])
    ax.set_xlim(-0.6, len(d) - 0.4)
    room(ax)
    save(fig, OUT / "weekdays", flush=True)


def fig_labels():
    m = {r["metric"]: r for r in rows("memory_label_metrics.csv") if r["scheme"] == "weighted" and r["label"] == "loss"}
    raters = [("rule", "Anchor match", B6, B3), ("rule_v2", "Literal match", B6, B3), ("rule_v3", "Context match", B6, B3),
              ("claude", "Claude Opus 5.5", R6, R3), ("llm", "Qwen3-14B", R6, R3), ("qwen35_122b", "Qwen3.5-122B-A10B", R6, R3),
              ("gptoss_120b", "gpt-oss-120b", R6, R3), ("gemini", "Gemini 3.1 Pro", R6, R3)]
    fig, axes = canvas(1, 3, panel_height=1.9, quantity="x",
                       legend=[("Presence rules", B6, "dot"), ("LLM raters", R6, "dot")], **KW)
    quantities(fig, ["Precision of loss detection (%)", "Recall (%)", "F1 (%)"])
    y = np.arange(len(raters))[::-1].astype(float)
    y[3:] -= 0.5
    for ax, metric in zip(axes.flat, ("precision", "recall", "f1")):
        r = m[metric]
        for yi, (k, _, col, soft) in zip(y, raters):
            hwhiskers(ax, [yi], [100 * float(r[f"{k}_lo"])], [100 * float(r[f"{k}_hi"])], soft, lw=1.4)
            ax.plot([100 * float(r[k])], [yi], "o", ms=4.2, color=col, zorder=3)
        ax.set_xlim(0, 100)
        ax.set_xticks([0, 25, 50, 75, 100])
        labels = ax.get_xticklabels()
        labels[0].set_ha("left")
        labels[-1].set_ha("right")
        ax.set_ylim(y[-1] - 0.7, y[0] + 0.7)
        ax.set_yticks(y, [n for _, n, _, _ in raters] if metric == "precision" else [""] * len(raters))
        ax.yaxis.grid(False)
        ax.tick_params(axis="y", labelsize=TEXT_PT)
    save(fig, OUT / "labels", flush=True)


def fig_reproduction():
    d = [r for r in rows("swarmsim_reproduction.csv") if r["required"] == "true" and r["rel_deviation"] not in ("", "NaN")]
    names = {"Standard swarm@32 finishes every step (t / T1)": "Finish time, 32 agents",
             "Standard swarm@64 finishes every step (t / T1)": "Finish time, 64 agents",
             "Standard swarm finish time, 64 over 32 agents": "Finish time, 64 over 32 agents",
             "Standard swarm@64 speedup at half coverage, g50": "Speedup to half coverage, 64 agents",
             "Standard swarm@64 speedup at best score 0.8": "Speedup to best score 0.8, 64 agents"}
    for n in (4, 8, 16, 32, 64):
        names[f"Recursive swarm@{n}, 3 layers, lambda = ln g50 / ln N"] = f"λ, recursive swarm, {n} agents"
    for n in (4, 8, 16, 64):
        names[f"Standard swarm@{n}, lambda"] = f"λ, standard swarm, {n} agents"
    fig, axes = canvas(1, 1, panel_height=2.5, quantity="Deviation from the reference value or range (%)",
                       legend=[("Our re-implementation", B6, "dot"), ("Tolerance of 20%", GREY_600, "dash")], **KW)
    ax = axes[0, 0]
    y = np.arange(len(d))[::-1]
    for yi, r in zip(y, d):
        v = 100 * float(r["rel_deviation"])
        ax.plot([0, v], [yi, yi], color=B3, lw=1.4, solid_capstyle="butt", zorder=2)
        ax.plot([v], [yi], "o", ms=4.2, color=B6, zorder=3)
    ax.plot([20, 20], [y[-1] - 0.7, y[0] + 0.7], color=GREY_600, lw=1.0, ls=(0, (3, 2)), zorder=2)
    ax.set_xlim(0, 25)
    ax.set_xticks([0, 5, 10, 15, 20, 25])
    ax.set_ylim(y[-1] - 0.7, y[0] + 0.7)
    ax.set_yticks(y, [names[r["check"]] for r in d])
    ax.yaxis.grid(False)
    ax.tick_params(axis="y", labelsize=TEXT_PT)
    save(fig, OUT / "reproduction", flush=True)


FIGURES = (fig_overview, fig_sources, fig_rho, fig_memory, fig_durability, fig_switch, fig_offspring, fig_h1, fig_tk, fig_h3,
           fig_depgraph_example, fig_continuation, fig_structure, fig_stepcost, fig_changepoints, fig_weekdays, fig_labels, fig_reproduction)


def main() -> None:
    apply_style()
    OUT.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[1:])
    for f in FIGURES:
        if only and f.__name__[4:] not in only:
            continue
        f()
        print("drew", f.__name__[4:])


if __name__ == "__main__":
    main()
