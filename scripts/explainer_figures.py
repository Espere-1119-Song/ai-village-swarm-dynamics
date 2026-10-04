"""Figures for the Chinese explainer (reports/findings_zh.md), one finding per figure.

    python scripts/explainer_figures.py      # writes reports/explainer_figures/*.png

Reads aggregate tables from outputs/tables/ only. The labels are Chinese, so run it on a machine
with a CJK font (Hiragino Sans GB, PingFang SC, Noto Sans CJK SC or Source Han Sans SC).
"""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[1]
TABLES = ROOT / "outputs" / "tables"
OUT = ROOT / "reports" / "explainer_figures"

BLUE, RED = "#1A73E8", "#D93025"
BLUE_50, BLUE_75 = "#669DF6", "#AECBFA"
RED_50, RED_75 = "#EE675C", "#F6AEA9"
GRID, INK = "#E8EAED", "#202124"

CJK = ("Hiragino Sans GB", "PingFang SC", "Noto Sans CJK SC", "Source Han Sans SC", "Arial Unicode MS")


def setup() -> None:
    have = {f.name for f in font_manager.fontManager.ttflist}
    fonts = [f for f in CJK if f in have]
    if not fonts:
        raise SystemExit(f"no CJK font found; install one of {CJK}")
    plt.rcParams.update({
        "font.family": fonts, "font.size": 13, "axes.titlesize": 16, "axes.titleweight": "bold",
        "axes.labelsize": 13, "axes.edgecolor": INK, "axes.labelcolor": INK, "xtick.color": INK,
        "ytick.color": INK, "text.color": INK, "axes.spines.top": False, "axes.spines.right": False,
        "savefig.dpi": 200, "savefig.bbox": "tight", "axes.unicode_minus": False,
    })


def rows(name: str) -> list[dict]:
    with open(TABLES / name, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / name)
    plt.close(fig)
    print(OUT / name)


def hbars(ax, labels, vals, los, his, colors, fmt="{:.1f}%"):
    y = list(range(len(labels)))[::-1]
    ax.barh(y, vals, color=colors, height=0.62)
    ax.errorbar(vals, y, xerr=[[v - l for v, l in zip(vals, los)], [h - v for v, h in zip(vals, his)]],
                fmt="none", ecolor=INK, elinewidth=1.4, capsize=4)
    for yi, v, h in zip(y, vals, his):
        ax.text(h + max(his) * 0.015, yi, fmt.format(v), va="center", fontsize=13, fontweight="bold")
    ax.set_yticks(y, labels)
    ax.tick_params(axis="y", length=0)
    ax.xaxis.grid(True, color=GRID)
    ax.set_axisbelow(True)


def fig_message_sources() -> None:
    cis = {r["quantity"]: r for r in rows("writeup_cis.csv")}
    key = "A: share of agent messages triggered by {}, event-weighted over the 43 goal windows (normal-interval alternative)"
    cats = [("self", "接着自己刚说的话"), ("baseline", "近期没有触发（自发）"), ("other agents", "回应其他 agent"),
            ("human", "人类的发言"), ("system", "系统提醒")]
    vals = [100 * float(cis[key.format(c)]["value"]) for c, _ in cats]
    los = [100 * float(cis[key.format(c)]["ci_lo"]) for c, _ in cats]
    his = [100 * float(cis[key.format(c)]["ci_hi"]) for c, _ in cats]
    fig, ax = plt.subplots(figsize=(9, 4.4))
    hbars(ax, [l for _, l in cats], vals, los, his, [BLUE, BLUE_75, RED, RED_50, RED_75])
    ax.set_xlim(0, 58)
    ax.set_xlabel("占全部 agent 发言的比例（%）")
    ax.set_title("agent 发言最常见的起因：接着自己刚说的话", loc="left")
    save(fig, "fig1_message_sources.png")


def fig_chain_reaction() -> None:
    import datetime as dt
    w = [r for r in rows("hawkes_windows.csv") if r["accepted"].lower() == "true"]
    cap = 1.5
    fig, ax = plt.subplots(figsize=(10, 4.6))
    ax.axhspan(1, cap + 0.05, color=RED_75, alpha=0.45, lw=0)
    ax.axhline(1, color=RED, lw=1.6)
    below = 0
    for r in w:
        x = dt.date.fromisoformat(r["date_start"])
        rho, lo, hi = float(r["rho"]), float(r["rho_lo"]), float(r["rho_hi"])
        below += rho < 1
        c = BLUE if rho < 1 else RED
        ax.plot([x, x], [lo, min(hi, cap)], color=BLUE_50, lw=1.3)
        if rho > cap:
            ax.plot(x, cap, marker="^", color=RED, ms=9)
            ax.annotate(f"{rho:.2f}，由一个只在 2 天\n出现的 agent 决定", (x, cap), xytext=(-150, -38),
                        textcoords="offset points", fontsize=11, color=RED,
                        arrowprops=dict(arrowstyle="-", color=RED, lw=1))
        else:
            ax.plot(x, rho, "o", color=c, ms=6.5)
    ax.text(0.01, 0.955, "高于 1：一轮比一轮多，会越滚越大", transform=ax.transAxes, fontsize=12, color=RED, va="top")
    ax.text(0.01, 0.04, "低于 1：一轮比一轮少，会自己平息", transform=ax.transAxes, fontsize=12, color=BLUE)
    ax.set_ylim(0.3, cap + 0.05)
    ax.set_ylabel("连锁放大倍数 ρ")
    ax.yaxis.grid(True, color=GRID)
    ax.set_axisbelow(True)
    ax.set_title(f"agent 之间的连锁反应几乎都会自己平息（{len(w)} 个时期中 {below} 个低于 1）", loc="left")
    save(fig, "fig2_chain_reaction.png")


def fig_memory_hazard() -> None:
    h = next(r for r in rows("memory_h2_v2.csv") if r["scope"] == "family" and r["stratum"] == "All standard")
    bins = [("h1", "第 1 次"), ("h2", "第 2 次"), ("h3_4", "第 3–4 次"), ("h5_8", "第 5–8 次"), ("h9plus", "第 9 次以后")]
    vals = [100 * float(h[b]) for b, _ in bins]
    los = [100 * float(h[f"{b}_lo"]) for b, _ in bins]
    his = [100 * float(h[f"{b}_hi"]) for b, _ in bins]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    x = list(range(len(bins)))
    ax.bar(x, vals, color=[RED, RED, RED_50, BLUE_50, BLUE], width=0.62)
    ax.errorbar(x, vals, yerr=[[v - l for v, l in zip(vals, los)], [hh - v for v, hh in zip(vals, his)]],
                fmt="none", ecolor=INK, elinewidth=1.4, capsize=4)
    for xi, v, hh in zip(x, vals, his):
        ax.text(xi, hh + 1.2, f"{v:.1f}%", ha="center", fontsize=13, fontweight="bold")
    ax.set_xticks(x, [l for _, l in bins])
    ax.set_xlabel("这条事实正在经历的重写次数")
    ax.set_ylabel("这次重写时被删的概率（%）")
    ax.set_ylim(0, 45)
    ax.yaxis.grid(True, color=GRID)
    ax.set_axisbelow(True)
    ax.set_title("新事实很容易被删，熬过多次重写的事实就很少再被删", loc="left")
    save(fig, "fig3_memory_hazard.png")


def fig_transmission_intervals() -> None:
    d = [r for r in rows("trees_h1_intervals_determined.csv")
         if r["channel"] == "chat_to_memory_other" and r["reported"].lower() == "true"]
    d.sort(key=lambda r: int(r["generation"]))
    med = [60 * float(r["median_h"]) for r in d]
    lo = [60 * float(r["median_lo"]) for r in d]
    hi = [60 * float(r["median_hi"]) for r in d]
    n = [int(r["n_edges"]) for r in d]
    cap = 42
    fig, ax = plt.subplots(figsize=(9, 4.6))
    x = list(range(len(d)))
    ax.bar(x, med, color=[BLUE_75, BLUE_50, BLUE][:len(d)], width=0.6)
    ax.text(0.02, 0.95, "红线：95% 置信区间", transform=ax.transAxes, ha="left", va="top", fontsize=11, color=RED)
    for xi, m, l, h, k in zip(x, med, lo, hi, n):
        ax.plot([xi, xi], [l, min(h, cap)], color=RED, lw=1.6)
        ax.plot([xi - 0.07, xi + 0.07], [l, l], color=RED, lw=1.6)
        if h > cap:
            ax.annotate("", (xi, cap + 1.5), (xi, cap - 2), arrowprops=dict(arrowstyle="->", color=RED, lw=1.6))
            ax.text(xi + 0.1, cap - 3.5, f"区间上限 {h:.0f} 分钟\n（只有 {k} 次，很不确定）", fontsize=11, color=RED)
            ax.text(xi - 0.05, m + 0.8, f"{m:.1f} 分钟", ha="right", fontsize=13, fontweight="bold")
        else:
            ax.plot([xi - 0.07, xi + 0.07], [h, h], color=RED, lw=1.6)
            ax.text(xi, max(h, m) + 0.9, f"{m:.1f} 分钟", ha="center", fontsize=13, fontweight="bold")
    ax.set_xticks(x, [f"第 {i + 1} 手\n（{k:,} 次）" for i, k in enumerate(n)])
    ax.set_ylabel("中位间隔（分钟，只算村子运行的时间）")
    ax.set_ylim(0, cap + 2)
    ax.yaxis.grid(True, color=GRID)
    ax.set_axisbelow(True)
    ax.set_title("信息每多传一手，间隔就更长（聊天 → 别的 agent 的记忆）", loc="left")
    save(fig, "fig4_transmission_intervals.png")


def fig_content_change() -> None:
    h = {(r["channel"], r["rules"]): r for r in rows("trees_h3.csv")}
    items = [(("agent_retelling", "v2"), "agent 之间转述", RED),
             (("memory_consolidation_b1_quantities", "v2"), "自己重写记忆\n（主规则 v2）", BLUE),
             (("memory_consolidation_b1_quantities", "v3"), "自己重写记忆\n（规则 v3）", BLUE_50),
             (("memory_consolidation_b1_quantities", "v1"), "自己重写记忆\n（规则 v1）", BLUE_75)]
    vals = [100 * float(h[k]["c"]) for k, _, _ in items]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    x = list(range(len(items)))
    ax.bar(x, vals, color=[c for _, _, c in items], width=0.6)
    for xi, v in zip(x, vals):
        ax.text(xi, v + 0.8, f"{v:.2f}%" if v < 1 else f"{v:.1f}%", ha="center", fontsize=13, fontweight="bold")
    ax.set_xticks(x, [l for _, l, _ in items])
    ax.set_ylabel("数字和上一手不同的比例（%）")
    ax.set_ylim(0, 36)
    ax.yaxis.grid(True, color=GRID)
    ax.set_axisbelow(True)
    ax.set_title("转述时数字和上一手不同的比例，高于自己重写记忆时", loc="left")
    save(fig, "fig5_content_change.png")


def fig_changelog_alignment() -> None:
    a = next(r for r in rows("changepoint_alignment.csv") if r["method"] == "pelt_l2" and r["cp_set"] == "all"
             and r["series_set"] == "all" and r["entry_set"] == "all" and r["w"] == "3")
    obs, mean = int(a["aligned"]), float(a["null1_mean"])
    lo, hi, n = float(a["null1_q025"]), float(a["null1_q975"]), int(a["n_changepoints"])
    fig, ax = plt.subplots(figsize=(9, 3.2))
    ax.barh([0], [hi - lo], left=[lo], height=0.42, color=BLUE_75)
    ax.plot([mean, mean], [-0.21, 0.21], color=BLUE, lw=2)
    ax.plot(obs, 0, "D", color=RED, ms=12)
    ax.annotate(f"实际：{obs:,} 个", (obs, 0), xytext=(obs - 45, 0.42), fontsize=13, color=RED, fontweight="bold",
                arrowprops=dict(arrowstyle="-", color=RED, lw=1))
    ax.text(lo, -0.42, f"随机把改动日期打乱 1 万次：95% 落在 {lo:,.0f} 到 {hi:,.0f}，平均 {mean:,.0f}",
            fontsize=12, va="top")
    ax.set_xlim(lo - 120, hi + 120)
    ax.set_ylim(-0.75, 0.75)
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)
    ax.set_xlabel(f"落在官方改动前后 3 天内的行为突变点个数（共 {n:,} 个）")
    ax.set_title("行为突变点靠近官方改动的个数，和随机情况差不多", loc="left")
    save(fig, "fig6_changelog_alignment.png")


def fig_continuation() -> None:
    d = {r["window"]: r for r in rows("depgraph_continuation.csv")
         if r["variant"] == "all" and r["measure"] == "with_parents" and r["stratum"] == "all"}
    g, day = d["goal"], d["day"]
    labels = ["实际：用到自己上一次的工作", "随机：从同一天写过的\n文件里挑", "随机：从同一目标写过的\n文件里挑"]
    vals = [100 * float(g["rate"]), 100 * float(day["baseline"]), 100 * float(g["baseline"])]
    los = [100 * float(g["rate_ci_low"]), 100 * float(day["baseline_ci_low"]), 100 * float(g["baseline_ci_low"])]
    his = [100 * float(g["rate_ci_high"]), 100 * float(day["baseline_ci_high"]), 100 * float(g["baseline_ci_high"])]
    fig, ax = plt.subplots(figsize=(9, 4.0))
    hbars(ax, labels, vals, los, his, [BLUE, BLUE_50, BLUE_75])
    ax.set_xlim(0, 80)
    ax.set_xlabel(f"有前置工作的电脑操作中，用到自己上一次工作成果的比例（%，{int(g['n_pairs']):,} 对）")
    ax.set_title("agent 大多接着自己上一次的工作做", loc="left")
    save(fig, "fig7_continuation.png")


def main() -> None:
    setup()
    for f in (fig_message_sources, fig_chain_reaction, fig_memory_hazard, fig_transmission_intervals,
              fig_content_change, fig_changelog_alignment, fig_continuation):
        f()


if __name__ == "__main__":
    main()
