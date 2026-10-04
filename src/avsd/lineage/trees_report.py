"""Tables, figures F3 and F4, and the QA report of module B2 (SPEC 6.4, 10.3).

Everything written to outputs/ is an aggregate: counts, rates, intervals and
keyed unit ids. No anchor values, text, 4-grams or human names (SPEC 0.2).

F3: ECDF of forward serial intervals of edges between agents (active hours, log
scale) by agent-level generation, one panel per stratum with at least two
reported generations.
F4: mean and variance of T_k (time from the tree root to the acquisition at
agent-level generation k) with 95% cluster-bootstrap intervals and the weighted
linear fit, two panels of equal height.
Both follow the house style of F5 and F6: Penn Blue #011F5B, Penn Red #990000
and their tints, no white text, capitalised labels, light grid, bold panel
letters, legend below the panels.

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
import polars as pl

from avsd.lineage import trees_stats as ts
from avsd.lineage.trees_kernel import KEYS

PENN_BLUE, PENN_RED = "#011F5B", "#990000"
ECDF_POINTS = 2000
GEN_STYLE = (
    (PENN_BLUE, "-"), ("#7F8FAD", "-"), (PENN_RED, "--"), ("#CC7F7F", "--"), ("#4D6284", ":"), ("#B84D4D", ":"),
)


_SECOND_LEVEL = frozenset({"ac", "co", "com", "edu", "gov", "net", "org"})


def site_domain(host: str | None) -> str | None:
    """Registrable part of a host: its last two labels, or three under a country code's second level
    (example.co.uk). Hosting platforms put account names in subdomains, so outputs drop subdomains."""
    if not host or "." not in host:
        return host
    if all(x.isdigit() for x in host.split(".")):
        return "ip address"
    lab = host.split(".")
    k = 3 if len(lab) >= 3 and len(lab[-1]) == 2 and lab[-2] in _SECOND_LEVEL else 2
    return ".".join(lab[-k:])


def human_name_tokens(cfg: dict) -> set[str]:
    """Lower-case tokens of 4 or more letters from the human speaker names. Used only to suppress domains;
    never written anywhere."""
    paths = cfg["paths"]
    f = Path(paths.get("tables", Path(paths["processed"]) / "tables")) / "events_text.parquet"
    a = Path(paths["processed"]) / "agents.parquet"
    if not f.exists():
        return set()
    agents = set(pl.read_parquet(a, columns=["name"])["name"].to_list()) if a.exists() else set()
    names = pl.read_parquet(f, columns=["speaker_name"])["speaker_name"].drop_nulls().unique().to_list()
    return {t.lower() for n in names if n not in agents for t in re.split(r"[^A-Za-z]+", n) if len(t) >= 4}


def public_domains(domain: pl.Series, name_tokens: set[str], min_units: int = 3) -> pl.Series:
    """Registrable domain of each URL unit, kept only when at least min_units units share it and it holds no
    human-name token; other URL units show "other" (personal sites sit in the long tail)."""
    site = domain.map_elements(site_domain, return_dtype=pl.String)
    counts = dict(site.drop_nulls().value_counts().iter_rows())
    keep = {d for d, n in counts.items() if n >= min_units and not any(t in d.lower() for t in name_tokens)}
    return site.map_elements(lambda d: d if d in keep else "other", return_dtype=pl.String).alias(domain.name)


def _tint(hex_color: str, t: float) -> str:
    rgb = [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(c + (255 - c) * t):02X}" for c in rgb)


def fmt(x, nd: int = 3) -> str:
    if x is None:
        return "n/a"
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return str(x)
    if not math.isfinite(xf):
        return "n/a"
    if isinstance(x, (int, np.integer)) or (float(xf).is_integer() and abs(xf) < 1e15
                                                  and not isinstance(x, (float, np.floating))):
        return f"{int(xf):,}"
    if float(xf).is_integer() and abs(xf) >= 1:
        return f"{int(xf):,}"
    if xf != 0 and abs(xf) < 10 ** -nd:
        return f"{xf:.{nd}g}"
    return f"{xf:.{nd}f}"


def fci(x, lo, hi, nd: int = 3) -> str:
    return f"{fmt(x, nd)} [{fmt(lo, nd)}, {fmt(hi, nd)}]"


def md_table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for r in rows:
        out.append("| " + " | ".join(fmt(v) if isinstance(v, (int, float, np.integer, np.floating)) else str(v)
                                     for v in r) + " |")
    return "\n".join(out)


def _csv(rows: list[dict] | pl.DataFrame, path: Path) -> None:
    df = rows if isinstance(rows, pl.DataFrame) else pl.DataFrame(rows, infer_schema_length=None)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_csv(path, float_precision=6)


# --- figures ------------------------------------------------------------------------------------------------

def _style():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    names = {f.name for f in font_manager.fontManager.ttflist}
    font = next((f for f in ("Nimbus Sans", "Liberation Sans", "Arial") if f in names), "DejaVu Sans")
    plt.rcParams.update({
        "font.family": [font, "DejaVu Sans"], "font.size": 10, "text.color": PENN_BLUE,
        "axes.edgecolor": _tint(PENN_BLUE, 0.35), "axes.labelcolor": PENN_BLUE, "xtick.color": PENN_BLUE,
        "ytick.color": PENN_BLUE, "axes.titlecolor": PENN_BLUE, "legend.fontsize": 9.5, "pdf.fonttype": 42,
        "axes.spines.top": False, "axes.spines.right": False, "xtick.major.size": 0, "ytick.major.size": 0,
        "mathtext.fontset": "custom", "mathtext.rm": font, "mathtext.it": f"{font}:italic",
        "mathtext.bf": f"{font}:bold", "mathtext.cal": font, "mathtext.sf": font,
    })
    return plt


def _letter(ax, s: str) -> None:
    ax.text(-0.13, 1.03, s, transform=ax.transAxes, fontsize=13, fontweight="bold", color=PENN_BLUE, va="bottom")


def _label_where_free(ax, text: str, renderer) -> None:
    """Put a panel label in the upper-left or lower-right corner, whichever covers less of the curves."""
    best = None
    for x, y, ha, va in ((0.03, 0.97, "left", "top"), (0.97, 0.04, "right", "bottom")):
        t = ax.text(x, y, text, transform=ax.transAxes, ha=ha, va=va, fontsize=9.5, color=PENN_BLUE)
        bb = t.get_window_extent(renderer).expanded(1.04, 1.1)
        hits = 0
        for ln in ax.get_lines():
            xy = ln.get_transform().transform(ln.get_path().vertices)
            xy = xy[np.isfinite(xy).all(axis=1)]
            if len(xy) < 2:
                continue
            d = np.diff(xy, axis=0)
            k = np.maximum(1, np.ceil(np.hypot(d[:, 0], d[:, 1]) / 2.0)).astype(np.int64)
            seg = np.repeat(np.arange(len(d)), k)
            frac = (np.arange(int(k.sum())) - np.repeat(np.cumsum(k) - k, k)) / np.repeat(k, k)
            pts = xy[seg] + d[seg] * frac[:, None]
            hits += int(((pts[:, 0] >= bb.x0) & (pts[:, 0] <= bb.x1)
                         & (pts[:, 1] >= bb.y0) & (pts[:, 1] <= bb.y1)).sum())
        t.remove()
        if best is None or hits < best[0]:
            best = (hits, x, y, ha, va)
    _, x, y, ha, va = best
    ax.text(x, y, text, transform=ax.transAxes, ha=ha, va=va, fontsize=9.5, color=PENN_BLUE)


def plot_f3(edges: ts.Edges, ok: np.ndarray, min_edges: int, base: Path) -> list[str]:
    """F3: ECDF of serial intervals by generation, faceted by channel (kernel key)."""
    plt = _style()
    from matplotlib.lines import Line2D

    panels = []
    est = edges.strata()
    for ci_, ch in enumerate(ts.H1_STRATA):
        m = ok & (est == ci_)
        gens, cnt = np.unique(edges.gen[m], return_counts=True)
        keep = [int(g) for g, n in zip(gens, cnt) if n >= min_edges and 1 <= g <= len(GEN_STYLE)]
        if len(keep) >= 2:
            panels.append((ch, keep))
    if not panels:
        panels = [(ts.H1_STRATA[0], [])]
    n = len(panels)
    ncol = min(n, 3)
    nrow = int(math.ceil(n / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(3.6 * ncol, 2.9 * nrow + 0.55), squeeze=False,
                             constrained_layout=True)
    used_gens: set[int] = set()
    for k, (ch, keep) in enumerate(panels):
        ax = axes[k // ncol][k % ncol]
        m = ok & (est == ts.H1_STRATA.index(ch))
        for g in keep:
            x = np.sort(np.maximum(edges.dt[m & (edges.gen == g)] / 3600.0, 1 / 3600))
            y = np.arange(1, len(x) + 1) / len(x)
            if len(x) > ECDF_POINTS:  # quantiles at ECDF_POINTS levels: the same curve, a small file
                lv = np.linspace(0, len(x) - 1, ECDF_POINTS).round().astype(int)
                x, y = x[lv], y[lv]
            col, ls = GEN_STYLE[g - 1]
            ax.step(x, y, where="post", color=col, ls=ls, lw=1.5)
            used_gens.add(g)
        ax.set_xscale("log")
        ax.set_ylim(0, 1.02)
        ax.grid(True, color=_tint(PENN_BLUE, 0.9), lw=0.6)
        ax.set_xlabel("Serial Interval (Active Hours)")
        if k % ncol == 0:
            ax.set_ylabel("Cumulative Share of Edges")
        _letter(ax, "abcdefghijklmnop"[k])
    for k in range(n, nrow * ncol):
        axes[k // ncol][k % ncol].set_visible(False)
    gl = sorted(used_gens)
    handles = [Line2D([0], [0], color=GEN_STYLE[g - 1][0], ls=GEN_STYLE[g - 1][1], lw=1.5) for g in gl]
    if handles:
        fig.legend(handles, [f"Generation {g}" for g in gl], loc="outside lower center", ncol=min(len(gl), 6),
                   frameon=False)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for k, (ch, _) in enumerate(panels):
        n_ch = int((ok & (est == ts.H1_STRATA.index(ch))).sum())
        _label_where_free(axes[k // ncol][k % ncol], f"{ts.H1_LABELS[ch]}\n{n_ch:,} Edges", renderer)
    base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(base) + ".pdf")
    fig.savefig(str(base) + ".png", dpi=200)
    plt.close(fig)
    return [p[0] for p in panels]


def plot_f4(tk: dict, base: Path) -> None:
    """F4: mean and variance of T_k with 95% intervals and the weighted linear fit over every reported k
    (log k axis when k goes beyond 20, so that the first generations, which hold most nodes, stay readable)."""
    plt = _style()
    from matplotlib.lines import Line2D
    from matplotlib.ticker import FixedLocator, MaxNLocator, NullLocator

    rows = tk.get("rows", [])
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.2, 3.9), constrained_layout=True)
    fits = {(f["quantity"], f["model"]): f for f in tk.get("fits", [])}
    kmax = max((r["k"] for r in rows), default=1)
    for ax, q, ylab, key, lo, hi in ((a1, "mean", "Mean of $T_k$ (Active Hours)", "mean_h", "mean_lo", "mean_hi"),
                                      (a2, "variance", "Variance of $T_k$ (Active Hours²)", "var_h2", "var_lo",
                                       "var_hi")):
        if rows:
            k = np.array([r["k"] for r in rows], dtype=float)
            y = np.array([r[key] for r in rows], dtype=float)
            yl = np.array([r[lo] for r in rows], dtype=float)
            yh = np.array([r[hi] for r in rows], dtype=float)
            err = np.vstack([np.clip(y - yl, 0, None), np.clip(yh - y, 0, None)])
            ax.errorbar(k, y, yerr=np.nan_to_num(err), fmt="o", color=PENN_BLUE, ecolor=_tint(PENN_BLUE, 0.4),
                        elinewidth=1.2, capsize=2.5, ms=4.5, zorder=3)
            f = fits.get((q, "linear"))
            if f is not None:
                xx = np.geomspace(1, kmax, 200) if kmax > 20 else np.linspace(0, kmax + 0.5, 50)
                ax.plot(xx, f["intercept"] + f["slope"] * xx, color=PENN_RED, ls="--", lw=1.4, zorder=2)
        if kmax > 20:
            ax.set_xscale("log")
            ticks = [t for t in (1, 2, 5, 10, 20, 50, 100, 200, 500) if t <= kmax * 1.05]
            ax.xaxis.set_major_locator(FixedLocator(ticks))
            ax.xaxis.set_minor_locator(NullLocator())
            ax.set_xticklabels([str(t) for t in ticks])
            ax.set_xlim(0.85, kmax * 1.15)
        else:
            ax.xaxis.set_major_locator(MaxNLocator(integer=True))
            ax.set_xlim(0.4, kmax + 0.6)
        ax.set_xlabel("Agent-Level Generation, k")
        ax.set_ylabel(ylab)
        ax.grid(True, color=_tint(PENN_BLUE, 0.9), lw=0.6)
        ax.set_ylim(bottom=0)
    _letter(a1, "a")
    _letter(a2, "b")
    handles = [Line2D([0], [0], color=PENN_BLUE, marker="o", ls="none", ms=5.5),
               Line2D([0], [0], color=PENN_RED, ls="--", lw=1.4)]
    fig.legend(handles, ["Observed With 95% CI", "Weighted Linear Fit"], loc="outside lower center", ncol=2,
               frameon=False)
    base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(base) + ".pdf")
    fig.savefig(str(base) + ".png", dpi=200)
    plt.close(fig)


def tk_from_csv(path: Path) -> dict:
    """The T_k rows and fits of trees_h1_tk.csv, in the form plot_f4 takes."""
    df = pl.read_csv(path, infer_schema_length=None)
    rows = [r for r in df.filter(pl.col("row_type") == "k").iter_rows(named=True)]
    for r in rows:
        r["k"] = int(r["k"])
    fits = [r for r in df.filter(pl.col("row_type") == "fit").iter_rows(named=True)]
    return {"rows": rows, "fits": fits}


# --- tables ---------------------------------------------------------------------------------------------------

def draw_summary(draws: pl.DataFrame) -> pl.DataFrame:
    rows = []
    for col in draws.columns:
        if col == "sample":
            continue
        v = draws[col].cast(pl.Float64, strict=False).to_numpy()
        v = v[np.isfinite(v)]
        if not len(v):
            continue
        r = {"statistic": col, "n_draws": len(v), "median": float(np.median(v)), "q025": float(np.quantile(v, 0.025)),
             "q975": float(np.quantile(v, 0.975))}
        if col.startswith("h1_p_"):
            r["share_below_005"] = float((v < 0.05).mean())
        rows.append(r)
    return pl.DataFrame(rows)


def synthetic_tables(synth: dict) -> tuple[pl.DataFrame, pl.DataFrame]:
    from scipy import stats

    reps = pl.DataFrame(synth["rows"], infer_schema_length=None)
    out = []
    for alt in sorted(set(reps["alt_scale"].to_list())):
        sub = reps.filter(pl.col("alt_scale") == alt)
        scen = "null (H1 true)" if alt == 1.0 else f"alternative (intervals between agents x {alt}^(g-1))"
        for m in ("parent_accuracy", "parent_accuracy_transmission", "env_recall", "generation_accuracy",
                  "generation_accuracy_nonroot", "agent_generation_accuracy", "generation_mae",
                  "determined_share", "determined_parent_accuracy", "determined_agent_generation_accuracy"):
            if m not in sub.columns:
                continue
            v = sub[m].drop_nulls().to_numpy()
            if len(v):
                out.append({"scenario": scen, "statistic": m, "n_replicates": len(v), "estimate": float(v.mean()),
                            "lo": float(np.quantile(v, 0.025)), "hi": float(np.quantile(v, 0.975)),
                            "interval": "2.5 and 97.5 percentiles over replicates"})
        for pre, tree, ch in [(pre, tree, ch) for pre in ("", "occ_") for tree in ("true", "inferred", "determined")
                              for ch in (*ts.H1_STRATA, "combined")]:
            col = f"{pre}p_{tree}_{ch}"
            if col not in sub.columns:
                continue
            v = sub[col].drop_nulls().to_numpy()
            v = v[np.isfinite(v)]
            if not len(v):
                continue
            k = int((v < 0.05).sum())
            lo, hi = stats.binomtest(k, len(v)).proportion_ci(confidence_level=0.95, method="wilson")
            out.append({"scenario": scen, "statistic": ("occurrence_" if pre else "") + f"rejection_rate_{tree}_{ch}",
                        "n_replicates": len(v), "estimate": k / len(v), "lo": float(lo), "hi": float(hi),
                        "interval": "Wilson 95% over replicates (alpha 0.05)"})
    return pl.DataFrame(out), reps


def write_all(cfg: dict, s: dict, inp: dict, c, post, chosen, cases, refs, labels_dir: Path, tag: str, log) -> None:
    outputs = Path(cfg["paths"]["outputs"])
    pre = "pilot_" if tag else ""
    tdir, fdir, qdir = outputs / "tables", outputs / "figures", outputs / "qa"
    main = s["main"]
    cl = s["cl"]
    # Units.
    ut: pl.DataFrame = s["unit_trees"]
    ut = ut.with_columns(public_domains(ut["domain"], human_name_tokens(cfg)))
    ut.write_parquet(tdir / f"{pre}trees_units.parquet")
    summ = (ut.with_columns(pl.when(pl.col("unit_kind") == "gram").then(pl.lit("gram")).otherwise(pl.col("anchor_type"))
                            .alias("type"))
            .group_by("type").agg(pl.len().alias("n_units"), pl.col("n_occurrences").sum().alias("n_occurrences"),
                                  pl.col("n_agents").mean().alias("mean_agents"),
                                  (pl.col("n_transmission_edges") > 0).sum().alias("units_with_edges"),
                                  pl.col("n_transmission_edges").sum().alias("transmission_edges"),
                                  pl.col("n_independent").sum().alias("independent"),
                                  pl.col("n_trees").sum().alias("trees"),
                                  (pl.col("max_generation") >= 2).sum().alias("units_depth_2plus"),
                                  pl.col("max_generation").max().alias("max_generation"))
            .sort("n_units", descending=True))
    tot = ut.select(pl.lit("all").alias("type"), pl.len().alias("n_units"),
                    pl.col("n_occurrences").sum().alias("n_occurrences"), pl.col("n_agents").mean().alias("mean_agents"),
                    (pl.col("n_transmission_edges") > 0).sum().alias("units_with_edges"),
                    pl.col("n_transmission_edges").sum().alias("transmission_edges"),
                    pl.col("n_independent").sum().alias("independent"), pl.col("n_trees").sum().alias("trees"),
                    (pl.col("max_generation") >= 2).sum().alias("units_depth_2plus"),
                    pl.col("max_generation").max().alias("max_generation"))
    summ = pl.concat([tot, summ], how="vertical_relaxed")
    _csv(summ, tdir / f"{pre}trees_unit_summary.csv")
    # Kernels.
    krows = []
    for k, info in s["kernel"].items():
        r = dict(info)
        r["used_by_module_a_hook"] = bool(s.get("hook_is_main", s["hawkes_hook"])) and KEYS[k] in (
            "chat>chat:other", "chat>chat:self")
        krows.append(r)
    _csv(krows, tdir / f"{pre}trees_kernels.csv")
    # Synthetic validation first: the H1 tables carry each test's synthetic error rates.
    if s["synthetic"]:
        syn, reps = synthetic_tables(s["synthetic"])
        _csv(syn, tdir / f"{pre}trees_synthetic.csv")
        _csv(reps, tdir / f"{pre}trees_synthetic_replicates.csv")
    else:
        syn = None

    def with_rates(rows: list[dict], tree: str, prefix: str = "", power: bool = False) -> list[dict]:
        out = []
        for r in rows:
            r = dict(r)
            for scen, col in (("null", "synthetic_type1"),) + ((("alternative", "synthetic_power"),) if power else ()):
                hit = (syn.filter(pl.col("scenario").str.starts_with(scen)
                                  & (pl.col("statistic") == f"{prefix}rejection_rate_{tree}_{r['channel']}"))
                       if syn is not None else None)
                h = hit.row(0, named=True) if hit is not None and hit.height else None
                r[col], r[f"{col}_lo"], r[f"{col}_hi"] = (h["estimate"], h["lo"], h["hi"]) if h else (None,) * 3
            out.append(r)
        return out

    # Generations (MAP) and draws.
    if s.get("time_term"):
        _csv(s["time_term"], tdir / f"{pre}trees_time_term.csv")
    if s.get("label_selection_rows"):
        _csv(s["label_selection_rows"], tdir / f"{pre}trees_label_selection.csv")
    _csv(main["generations"], tdir / f"{pre}trees_generations.csv")
    _csv(main["intervals"], tdir / f"{pre}trees_h1_intervals.csv")
    _csv(with_rates(main["h1_ad"], "inferred"), tdir / f"{pre}trees_h1_tests.csv")
    _csv(with_rates(main["h1_ad_det"], "determined", power=True), tdir / f"{pre}trees_h1_tests_determined.csv")
    if main.get("h1_ad_occ"):
        _csv([dict(r, tree="map") for r in with_rates(main["h1_ad_occ"], "inferred", "occurrence_")]
             + [dict(r, tree="determined") for r in with_rates(main["h1_ad_det_occ"], "determined", "occurrence_")],
             tdir / f"{pre}trees_h1_tests_occurrence_level.csv")
    rs = main.get("restatement")
    if rs:
        rrows = [{"measure": "summary", "key": k, "value": v} for k, v in rs.items()
                 if not isinstance(v, (list, dict))]
        rrows += [{"measure": "restatement_depth", "key": r["depth"], "value": r["n_acquisitions"]}
                  for r in rs["depth"]]
        _csv([{**r, "value": float(r["value"])} for r in rrows], tdir / f"{pre}trees_restatement.csv")
    tkd = main.get("tk_det", {})
    _csv([{"row_type": "k", **r} for r in tkd.get("rows", [])] + [{"row_type": "fit", **f} for f in tkd.get("fits", [])],
         tdir / f"{pre}trees_h1_tk_determined.csv")
    e_, okd = main["edges"], main["ok"] & main["det_edges"]
    bd = ts.ClusterBoot(e_.root[okd], cl["boot_reps"], np.random.default_rng([int(s["seed"]), 6]))
    _csv(ts.interval_table(e_, okd, bd, cl["min_edges"]), tdir / f"{pre}trees_h1_intervals_determined.csv")
    tk_rows = [{"row_type": "k", **r} for r in main["tk"]["rows"]] + [{"row_type": "fit", **f} for f in main["tk"]["fits"]]
    _csv(tk_rows, tdir / f"{pre}trees_h1_tk.csv")
    _csv([{"statistic": "spearman_consecutive_intervals", **main["adjacent"]}], tdir / f"{pre}trees_h1_adjacent.csv")
    h3 = [dict(r, rules=s["rules"], source="B2 MAP edges") for r in main["h3_rows"]]
    h3 += [dict(r, source="B1 tables") for r in s["b1_c"]]
    _csv(h3, tdir / f"{pre}trees_h3.csv")
    _csv(main["attractor"], tdir / f"{pre}trees_attractor.csv")
    _csv(s["ablation"], tdir / f"{pre}trees_ablation.csv")
    _csv(s["grid"], tdir / f"{pre}trees_gamma_grid.csv")
    ds = draw_summary(s["draws"])
    _csv(ds, tdir / f"{pre}trees_posterior_samples.csv")
    if s["sensitivity"]:
        _csv(s["sensitivity"], tdir / f"{pre}trees_sensitivity.csv")
    ea = main.get("edges_all", main["edges"])
    av = main.get("agent")
    pl.DataFrame({"stratum": ea.strata(), "generation_occurrence": ea.gen,
                  "generation_agent": av.gen[ea.child] if av is not None else ea.gen,
                  "into_acquisition": av.acq[ea.child] if av is not None else np.ones(len(ea.child), bool),
                  "dt_s": ea.dt, "forward": main.get("ok_all", main["ok"]),
                  "determined": main.get("det_all", main.get("det_edges"))}).write_parquet(
        inp["dir"] / "map_edges.parquet")
    panels = plot_f3(main["edges"], main["ok"], cl["min_edges"], fdir / f"{pre}F3_interval_ecdf")
    plot_f4(main["tk"], fdir / f"{pre}F4_tk_mean_variance")
    qa = render_qa(s, summ, ds, syn, panels)
    qdir.mkdir(parents=True, exist_ok=True)
    (qdir / f"{pre}lineage_trees.md").write_text(qa, encoding="utf-8")
    log(f"outputs written: {tdir}/{pre}trees_*.csv, {fdir}/{pre}F3_*, F4_*, {qdir}/{pre}lineage_trees.md")


# --- QA report -------------------------------------------------------------------------------------------------

def valid_strata(syn: pl.DataFrame | None, tree: str) -> list[str]:
    """Strata whose rejection rate under the synthetic null has a 95% interval that contains 0.05."""
    if syn is None or not syn.height:
        return []
    out = []
    pre = f"rejection_rate_{tree}_"
    for r in syn.filter(pl.col("scenario").str.starts_with("null")).iter_rows(named=True):
        st = r["statistic"]
        if st.startswith(pre) and not st.endswith("_combined") and r["lo"] <= 0.05 <= r["hi"]:
            out.append(st[len(pre):])
    return out


def gamma_source(s: dict) -> str:
    sel = s.get("label_selection")
    if sel:
        return f"chosen with the time term on the {sel['label_set']} labels: parent accuracy, then mean log posterior"
    mode = s.get("gamma_mode", "tier1")
    if mode == "tier1":
        return "maximum of the tier-1 name-reference log posterior; provisional"
    return "fixed on the command line"


def render_label_selection(w, s: dict, sel: dict) -> None:
    """QA section 4.1: the choice of time term and gamma on the hand labels."""
    rows = s.get("label_selection_rows") or []
    ag = s.get("label_agreement") or {}
    w("### 4.1 Time term and gamma chosen on the labels")
    w("")
    n = {r["label_set"]: r["n_cases"] for r in rows}
    txt = (f"Label set {sel['label_set']} ({fmt(n.get(sel['label_set']))} cases that match a candidate). "
           "composite takes the owner's label where the owner answered the row (none included) and the blind label "
           "from Claude elsewhere; owner and claude are the two sets alone.")
    if ag.get("both"):
        txt += (f" Claude and the owner agree on {ag['agree']} of {ag['both']} rows "
                f"({100 * ag['agree'] / ag['both']:.0f}%; an ENV candidate counts as env).")
    w(txt + f" Chosen: {sel['time_term']}, gamma = {fmt(sel['gamma'])}.")
    w("")
    bests = sel.get("best_by_set", {})
    if bests:
        w("Best time term and gamma by label set: " + "; ".join(
            f"{k} {v[0]}, gamma {fmt(v[1])}" for k, v in bests.items()) + ".")
        w("")
    keep = [r for r in rows if r["gamma"] in (0.0, float(sel["gamma"]))]
    w(md_table(["Time term", "gamma", "Label set", "Cases", "Accuracy", "Mean log P", "Best for the set"],
               [[r["time_term"], r["gamma"], r["label_set"], r["n_cases"], r["accuracy"], r["mean_logp"],
                 "yes" if r["best_for_set"] else ""] for r in keep]))
    w("")
    w("Accuracy is the expected top-1 accuracy of the posterior (ties split evenly), on all rows of a set (no "
      "cross-fitting; the choice and its evaluation use the same labels). Every grid point: "
      "trees_label_selection.csv.")
    w("")


def syn_rate(syn: pl.DataFrame | None, tree: str, stratum: str, scenario: str = "null", prefix: str = "") -> str:
    """Rejection rate of the H1 test of one stratum on synthetic trees, as "estimate [lo, hi]"."""
    if syn is None or not syn.height:
        return "n/a"
    hit = syn.filter(pl.col("scenario").str.starts_with(scenario)
                     & (pl.col("statistic") == f"{prefix}rejection_rate_{tree}_{stratum}"))
    if not hit.height:
        return "n/a"
    r = hit.row(0, named=True)
    return fci(r["estimate"], r["lo"], r["hi"])


def render_qa(s: dict, summ: pl.DataFrame, ds: pl.DataFrame, syn: pl.DataFrame | None, panels: list[str]) -> str:
    main, cl, meta = s["main"], s["cl"], s.get("meta", {})
    L = []
    w = L.append
    w("# QA: module B2, transmission trees between agents (SPEC 6.4)")
    w("")
    w('Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village')
    w("")
    w("All numbers below are aggregates. No anchor values, message text, 4-grams or human names appear in this "
      "report or in outputs/tables/trees_*.csv. Units are shown by keyed ids. A URL unit shows its registrable "
      "domain only when at least 3 units share it (subdomains hold account names on hosting platforms, and "
      'personal sites sit in the long tail); the others show "other".')
    w("")
    w("## 1. Settings")
    w("")
    w(md_table(["Setting", "Value"], [
        ["B1 fact-presence rule set", f"{s['rules']} ("
         + ("B1's main rule set since 2026-10-03" if s["rules"] == "v2" else "B1's main rule set is v2")
         + "; it sets the memory presence of re-mentions, so agent-level numbers change only through the KDE "
           "fitted on single-candidate edges)"],
        ["Exposure rule (chat)", s["exposure"]], ["Independent observation rule", s["env_rule"]],
        ["L_B", f"{cl['L_B']} run days"], ["Minimum edges per reported generation", cl["min_edges"]],
        ["gamma", f"{s['gamma']} ({gamma_source(s)})"],
        ["Time term", ("module A kernels plus KDE" if s.get("hook_is_main", s["hawkes_hook"]) else
                       "empirical KDE per kernel key") + (" (chosen on the labels)" if s.get("label_selection") else "")],
        ["Posterior draws", cl["samples"]], ["Cluster-bootstrap replicates", cl["boot_reps"]],
        ["H1 permutations (MAP; draws)", f"{cl['perms']}; {cl['perms_draws']}"], ["Seed", s["seed"]],
    ]))
    w("")
    w("## 2. Information units and occurrences")
    w("")
    docs = meta.get("docs", {})
    w(f"We read {fmt(docs.get('chat', 0))} chat messages of agents and humans and {fmt(docs.get('search', 0))} "
      f"search-history answers. Typed candidates: {fmt(meta.get('typed_candidates'))}; gram message sets: "
      f"{fmt((meta.get('gram_candidates') or {}).get('units'))}. Units above the size cap "
      f"({meta.get('max_unit_occurrences')} occurrences) were left out: {fmt(meta.get('typed_size_excluded'))} typed "
      f"and {fmt(meta.get('gram_size_excluded'))} gram units.")
    w("")
    w(f"We kept {fmt(s['n_units'])} units with {fmt(s['n_occ'])} occurrences: "
      + ", ".join(f"{k} {fmt(v)}" for k, v in s["occ_by_src"].items()) + ". Turn observations (env_i hits): "
      f"{fmt(meta.get('env_hits'))}.")
    w("")
    rows = [[r["type"], r["n_units"], r["n_occurrences"], r["mean_agents"], r["units_with_edges"],
             r["transmission_edges"], r["independent"], r["units_depth_2plus"], r["max_generation"]]
            for r in summ.iter_rows(named=True)]
    w(md_table(["Unit type", "Units", "Occurrences", "Mean agents", "Units with edges", "Edges", "Independent",
                "Units with depth >= 2", "Max generation"], rows))
    w("")
    n_tree_units = int(summ.filter(pl.col("type") == "all")["units_with_edges"][0]) if summ.height else 0
    w(f"Acceptance (SPEC 6.4.6): {fmt(n_tree_units)} units have an inferred tree with at least one transmission "
      f"edge (required: 100).")
    w("")
    w("## 3. Time term")
    w("")
    krows = [[v["key"], v["n_single"], v["fit_on"], v.get("n_fit"), fmt(v.get("dt_median_h")),
              f"{fmt(v.get('dt_q25_h'))} to {fmt(v.get('dt_q75_h'))}"] for v in s["kernel"].values()]
    w(md_table(["Kernel key", "Single-candidate edges", "Fitted on", "Edges in fit", "Median (active h)", "IQR (active h)"],
               krows))
    w("")
    w(f"Candidate rows: {fmt(s['cands'])}. env candidates dropped because an earlier exposure existed: "
      f"{fmt(s['cand_stats'].get('env_dropped_by_precede'))}.")
    w("")
    if s.get("hawkes_used"):
        w("### 3.1 Module A kernels")
        w("")
        hf = s.get("hawkes_file") or {}
        if hf:
            w(f"outputs/tables/hawkes_kernels.parquet as read by this run: modified {hf.get('modified')}, sha256 "
              f"{str(hf.get('sha256'))[:12]}.")
            w("")
        if s.get("hook_is_main") is False:
            w("The main run uses the KDE alone, chosen on the labels (section 4.1). The counts below show the edges "
              "that the module A kernel covers, for the sensitivity run with it.")
            w("")
        hu = s["hawkes_used"]
        tot = sum(hu.values())
        w(f"Time term by candidate edge of the main run ({tot:,} edges): module A kernel for "
          f"{hu.get('hawkes', 0):,} ({100 * hu.get('hawkes', 0) / max(tot, 1):.1f}%), the KDE for the rest: "
          + ", ".join(f"{k.removeprefix('fallback_').removeprefix('kde_').replace('_', ' ')} {v:,}"
                      for k, v in hu.items() if k != "hawkes") + ".")
        w("")
        tt = s.get("time_term") or []
        if tt:
            cand = {(r["window_id"], r["group"]): r for r in tt if r["scope"] == "candidate_edges"}
            mp = {(r["window_id"], r["group"]): r for r in tt if r["scope"] == "map_edges"}

            def share(r):
                return f"{fmt(r['hawkes'])} ({100 * r['share_hawkes']:.1f}%)" if r and r["n_chat_edges"] else "0"

            rows = []
            for key, r in cand.items():
                if not r["n_chat_edges"]:
                    continue
                m = mp.get(key)
                dates = f"{r['date_start']} to {r['date_end']}" if r["date_start"] else ""
                rows.append([r["window_id"], r["group"], dates, r.get("identified_classes", ""), r["n_chat_edges"],
                             share(r), r["kde_cross_day"], r["kde_no_window"], r["kde_not_identified"],
                             r["kde_beyond_L"], m["n_chat_edges"] if m else 0, share(m)])
            w(md_table(["Window", "Room", "Dates", "Identified classes", "Candidate chat edges", "Module A kernel",
                        "KDE: cross-day", "KDE: no window", "KDE: not identified", "KDE: tau > L",
                        "MAP chat edges", "MAP: module A kernel"], rows))
            w("")
            w("Chat edges are chat-to-chat candidate edges (an agent child, a chat parent). A window is found by the "
              "child's room and PT date together (group = room name, date_start <= date <= date_end). Window "
              "\"none\" counts edges in a room with no goal window on the child's date. The KDE also serves "
              "cross-day edges, unidentified source classes (expected_children < 50) and intervals beyond L. "
              "MAP columns count the chat edges chosen as MAP parents. Windows without chat edges are left out "
              "here; trees_time_term.csv has every window.")
            w("")
    w("## 4. Labels, gamma and ablation (SPEC 6.4.5)")
    w("")
    w(f"Explicit references: {fmt(s['n_refs'])}. Usable cases (the labelled message is a candidate parent for a "
      f"shared unit): {fmt(s['n_cases'])} ("
      + ", ".join(f"{k} {fmt(v)}" for k, v in s.get("cases_by_kind", {}).items()) + ").")
    w("")
    if s["grid"]:
        suf = next((x for x in ("_kde_only", "_module_a") if f"name_tier1_mean_logp{x}" in s["grid"][0]), None)
        main_t = "module A + KDE" if s.get("hook_is_main", s["hawkes_hook"]) else "KDE only"
        alt_t = {"_kde_only": "KDE only", "_module_a": "module A + KDE"}.get(suf or "", "")
        hdr = ["gamma", "Tier-1 name cases", "Mean log P(label)", "Accuracy"]
        if suf:
            hdr = ["gamma", "Tier-1 name cases", f"Mean log P ({main_t})", f"Accuracy ({main_t})",
                   f"Mean log P ({alt_t})", f"Accuracy ({alt_t})"]
        w(md_table(hdr, [[r["gamma"], r.get("name_tier1_n"), r.get("name_tier1_mean_logp"),
                          r.get("name_tier1_accuracy")]
                         + ([r.get(f"name_tier1_mean_logp{suf}"), r.get(f"name_tier1_accuracy{suf}")]
                            if suf else []) for r in s["grid"]]))
        w("")
    w(f"We use gamma = {s['gamma']} ({gamma_source(s)})."
      + (f" With the other time term the same rule would give gamma = {s['gamma_kde_only']}."
         if s.get("gamma_kde_only") is not None and not s.get("label_selection") else ""))
    w("")
    sel = s.get("label_selection")
    if sel:
        render_label_selection(w, s, sel)
    if s["ablation"]:
        w(md_table(["Label set", "Method", "Cases", "Child messages", "Accuracy [95% CI]", "Mean log P",
                    "Mean candidates"],
                   [[r["label_set"], r["method"], r["n_cases"], r["n_child_messages"],
                     fci(r["accuracy"], r.get("accuracy_lo"), r.get("accuracy_hi")), r.get("mean_logp"),
                     r["mean_candidates"]] for r in s["ablation"]]))
        w("")
        w("Accuracy counts ties as split evenly. "
          + ("gamma is fixed at the value chosen on the labels (section 4.1), so these rows are not cross-fitted. "
             if s.get("label_selection") else
             "gamma for the tier-1 rows is chosen on the other fold of child messages (two folds). ")
          + "Quote labels share text with their parent by construction, so for them only "
          "the time term is informative. Methods ending in _kde_only take the time term from the KDE alone, and "
          "methods ending in _module_a from the module A kernels, whichever is not the main time term. hand is the "
          "owner's audit labels, claude the blind labels from Claude, and composite the owner's label where it "
          "exists and the label from Claude elsewhere. CIs: cluster bootstrap by child message.")
        w("")
    w("## 5. Agent-level forest by generation (SPEC 6.4.4)")
    w("")
    w("The main view counts transmission between agents. Each actor's first occurrence of a unit is its "
      "acquisition (all humans count as one actor). The MAP parent of an acquisition (the carrier) is an "
      "occurrence of another actor, and that actor's acquisition is one generation up. Later occurrences of an "
      "actor are re-mentions: they keep the actor's generation whatever their own MAP parent, and section 5.2 "
      "summarises them as restatement depth. Offspring of an acquisition are the acquisitions it carried, "
      "through any of its actor's occurrences.")
    w("")
    g = main["generations"]
    w(f"Acquisitions {fmt(main.get('n_acquisitions'))}: transmitted {fmt(main['n_edges'])}, independent (env) "
      f"{fmt(main['n_env'])}, roots without a candidate {fmt(main['n_roots'])}. Transmissions with complete "
      f"follow-up {fmt(main['n_edges_forward'])}. Maximum agent-level generation {main['max_gen']} "
      f"(occurrence-level {main.get('max_gen_occurrence')}).")
    w("")
    w(md_table(["g", "Acquisitions", "Trees", "Offspring [95% CI]", "Expected offspring", "Chat to chat",
                "Chat to memory", "Chat to search answer", "Chat to human", "Content change [95% CI]",
                "Independent [95% CI]"],
               [[r["generation"], r["n_nodes"], r["n_trees"],
                 fci(r.get("offspring_mean"), r.get("offspring_lo"), r.get("offspring_hi")),
                 r.get("offspring_expected", np.nan), r.get("share_chat_other"), r.get("share_chat_to_memory"),
                 r.get("share_history"), r.get("share_human"),
                 fci(r.get("content_change_rate"), r.get("content_change_lo"), r.get("content_change_hi")),
                 fci(r.get("independent_share"), r.get("independent_lo"), r.get("independent_hi"))] for r in g]))
    w("")
    w("Channel shares are of the transmissions into g. Offspring counts only acquisitions at least L_B before "
      "the end of the data. Expected offspring scales the generation-0 mean by the share of active agents "
      "without the unit yet (finite population, SPEC 6.2). Content change: share of a node's non-root values "
      "(quantity values under a context key that the root holds with another value, SPEC appendix A) that its "
      "carrier lacks. Independent: share of acquisitions whose MAP parent is env_i, by the agent-level generation "
      "they have when env_i is not allowed. CIs: cluster bootstrap by agent-level tree root.")
    w("")
    rs = main.get("restatement")
    if rs:
        w("### 5.2 Restatement depth")
        w("")
        nr = max(rs["n_remention"], 1)
        w(f"{fmt(rs['n_remention'])} of the {fmt(rs['n_occurrences'])} occurrences are re-mentions by an actor "
          f"that already holds the unit. Their MAP parent is the actor's own earlier occurrence for "
          f"{fmt(rs['remention_parent_own'])} ({100 * rs['remention_parent_own'] / nr:.1f}%), another actor's "
          f"occurrence for {fmt(rs['remention_parent_other_actor'])} "
          f"({100 * rs['remention_parent_other_actor'] / nr:.1f}%), env_i for "
          f"{fmt(rs['remention_parent_env'])} and none for {fmt(rs['remention_no_parent'])}. Counting every edge as "
          f"a generation gives a maximum of {rs['max_generation_occurrence_level']} generations; transmission to "
          f"new agents reaches {rs['max_generation_agent_level']}. Restatement depth (re-mentions per acquisition): "
          f"mean {fmt(rs['depth_mean'])}, median {fmt(rs['depth_median'])}, maximum {rs['depth_max']} "
          f"({fmt(rs['n_acquisitions'])} acquisitions).")
        w("")
        tot = max(rs["n_acquisitions"], 1)
        w(md_table(["Restatement depth", "Acquisitions", "Share"],
                   [[r["depth"], r["n_acquisitions"], r["n_acquisitions"] / tot] for r in rs["depth"]]))
        w("")
        if main.get("h1_ad_occ"):
            w("For reference, H1 with occurrence-level generations (every MAP edge counts as a generation), "
              f"{cl.get('perms_sensitivity', cl['perms'])} permutations:")
            w("")
            occ_det = {r["channel"]: r for r in main.get("h1_ad_det_occ", [])}
            w(md_table(["Stratum", "Generations", "Edges", "p (MAP)", "Synthetic type I error (MAP)",
                        "p (determined)", "Synthetic type I error (determined)"],
                       [[ts.H1_LABELS.get(r["channel"], r["channel"]), r["n_generations"], r["n_edges"], r["p_perm"],
                         syn_rate(syn, "inferred", r["channel"], prefix="occurrence_"),
                         occ_det.get(r["channel"], {}).get("p_perm", "n/a"),
                         syn_rate(syn, "determined", r["channel"], prefix="occurrence_")]
                        for r in main["h1_ad_occ"] if r["n_edges"]]))
            w("")
    w("## 6. H1: serial intervals and generation (SPEC 6.2)")
    w("")
    w("H1 compares the forward serial intervals of transmissions (carrier to acquisition) across agent-level "
      "generations. It is "
      "stratified by kernel key (channel, child source); a channel group that pools two keys changes its mix with "
      "the generation, and on synthetic trees with intervals independent of the generation such a pooled test "
      "rejected in most replicates. p uses permutations of generation labels within a stratum "
      f"({cl['perms']} for the MAP forest, smallest attainable p {fmt(1 / (cl['perms'] + 1), 4)}; "
      f"{cl['perms_draws']} per posterior draw). The permutation null treats edges as exchangeable and ignores "
      "dependence within trees, so section 9 measures the error rate of each test on synthetic trees.")
    w("")
    d_p = {r["statistic"]: r for r in ds.iter_rows(named=True)} if ds.height else {}

    def gens(txt: str) -> str:
        g = [int(x) for x in txt.split(",") if x] if txt else []
        return "n/a" if not g else (f"{g[0]} to {g[-1]} ({len(g)})" if len(g) > 3 else ", ".join(map(str, g)))

    w("### 6.1 Headline: determined paths")
    w("")
    acc = None
    if syn is not None and syn.height:
        hit = syn.filter(pl.col("scenario").str.starts_with("null")
                         & (pl.col("statistic") == "determined_parent_accuracy"))
        if hit.height:
            r0 = hit.row(0, named=True)
            acc = (f" On synthetic trees {fci(r0['estimate'], r0['lo'], r0['hi'])} of these parents are correct "
                   f"({r0['n_replicates']} replicates).")
    w(f"Transmissions whose whole agent-level path from the root uses acquisitions with a single candidate "
      f"parent ({fmt(main['n_determined_edges'])} of the transmissions with complete follow-up). Each parent on "
      "such a path is the only candidate, so this test does not depend on the parent posterior." + (acc or ""))
    w("")
    vd, vm = valid_strata(syn, "determined"), valid_strata(syn, "inferred")
    w("Strata whose test keeps its nominal 5% level on synthetic trees with intervals independent of the "
      "generation (the 95% interval of the null rejection rate contains 0.05): on determined paths "
      + (", ".join(ts.H1_LABELS.get(x, x) for x in vd) if vd else "none")
      + "; on the MAP forest " + (", ".join(ts.H1_LABELS.get(x, x) for x in vm) if vm else "none")
      + ". Only these tests bear on H1.")
    w("")
    w(md_table(["Stratum", "Generations (count)", "Edges", "A2", "z vs permutation null", "p (permutation)",
                "Synthetic type I error [95% CI]", "Synthetic power [95% CI]", "Posterior draws: median p"],
               [[ts.H1_LABELS.get(r["channel"], r["channel"]), gens(r["generations"]), r["n_edges"], r["ad_stat"],
                 r.get("z_vs_null"), r["p_perm"], syn_rate(syn, "determined", r["channel"]),
                 syn_rate(syn, "determined", r["channel"], scenario="alternative"),
                 d_p.get(f"h1det_p_{r['channel']}", {}).get("median")]
                for r in main["h1_ad_det"] if r["n_edges"]]))
    w("")
    w("Power: synthetic trees whose transmission intervals grow by a factor 1.5 per agent-level generation "
      "after the first. Intervals by generation on determined paths: trees_h1_intervals_determined.csv.")
    w("")
    tkd = main.get("tk_det", {})
    if tkd.get("rows"):
        w("T_k on determined paths (time from the tree root to the acquisition at hop k):")
        w("")
        w(md_table(["k", "Acquisitions", "Trees", "Mean h [95% CI]", "Variance h2 [95% CI]", "Median h [95% CI]"],
                   [[r["k"], r["n_nodes"], r["n_trees"], fci(r["mean_h"], r["mean_lo"], r["mean_hi"]),
                     fci(r["var_h2"], r["var_lo"], r["var_hi"]), fci(r["median_h"], r["median_lo"], r["median_hi"])]
                    for r in tkd["rows"] if r["k"] <= QA_MAX_K]))
        w("")
        if tkd.get("fits"):
            w(md_table(["Quantity", "Model", "k values", "Slope [95% CI]", "k^2 coefficient [95% CI]",
                        "p (k^2, bootstrap)"],
                       [[f["quantity"], f["model"], f["n_k"],
                         fci(f["slope"], f.get("slope_lo"), f.get("slope_hi")) if f["model"] == "linear"
                         else fmt(f["slope"]),
                         fci(f.get("k2"), f.get("k2_lo"), f.get("k2_hi")) if f["model"] == "quadratic" else "",
                         f.get("p_k2_boot", "")] for f in tkd["fits"]]))
            w("")
    w("### 6.2 MAP forest, with its synthetic type I error")
    w("")
    w("The MAP-forest test is shown for completeness. Its synthetic type I error (MAP trees inferred from "
      "synthetic data where H1 holds) is far above 5% in most strata, so a rejection here does not show that "
      "intervals change with the generation.")
    w("")
    w(md_table(["Stratum", "Generations (count)", "Edges", "A2", "z vs permutation null", "p (permutation)",
                "Synthetic type I error [95% CI]", "Posterior draws: median p", "Draws with p < 0.05"],
               [[ts.H1_LABELS.get(r["channel"], r["channel"]), gens(r["generations"]), r["n_edges"], r["ad_stat"],
                 r.get("z_vs_null"), r["p_perm"], syn_rate(syn, "inferred", r["channel"]),
                 d_p.get(f"h1_p_{r['channel']}", {}).get("median"),
                 d_p.get(f"h1_p_{r['channel']}", {}).get("share_below_005")] for r in main["h1_ad"] if r["n_edges"]]))
    w("")
    w("### 6.3 Forward intervals by stratum and generation")
    w("")
    w(md_table(["Stratum", "g", "Edges", "Trees", "Median h [95% CI]", "IQR h", "Mean h [95% CI]"],
               [[ts.H1_LABELS.get(r["channel"], r["channel"]), r["generation"], r["n_edges"], r["n_trees"],
                 fci(r["median_h"], r.get("median_lo"), r.get("median_hi")),
                 f"{fmt(r['q25_h'])} to {fmt(r['q75_h'])}", fci(r["mean_h"], r.get("mean_lo"), r.get("mean_hi"))]
                for r in main["intervals"] if r["reported"] and r["generation"] <= QA_MAX_G]))
    w("")
    n_more = sum(1 for r in main["intervals"] if r["reported"] and r["generation"] > QA_MAX_G)
    w(f"MAP forest, transmissions. Only generations with at least {cl['min_edges']} edges are reported; "
      f"this table stops at g = {QA_MAX_G} ({n_more} more rows in trees_h1_intervals.csv). Intervals are in active "
      f"hours. F3 shows the ECDFs of generations 1 to 6 for the strata with at least two "
      f"({', '.join(ts.H1_LABELS.get(p, p) for p in panels)}).")
    w("")
    w("### 6.4 T_k against k")
    w("")
    w("T_k is the time from the tree root to an acquisition at agent-level generation k (MAP forest).")
    w("")
    tk = main["tk"]
    w(md_table(["k", "Acquisitions", "Trees", "Mean h [95% CI]", "Variance h2 [95% CI]", "Median h [95% CI]", "IQR h"],
               [[r["k"], r["n_nodes"], r["n_trees"], fci(r["mean_h"], r["mean_lo"], r["mean_hi"]),
                 fci(r["var_h2"], r["var_lo"], r["var_hi"]), fci(r["median_h"], r["median_lo"], r["median_hi"]),
                 f"{fmt(r['q25_h'])} to {fmt(r['q75_h'])}"] for r in tk.get("rows", []) if r["k"] <= QA_MAX_K]))
    w("")
    n_more = sum(1 for r in tk.get("rows", []) if r["k"] > QA_MAX_K)
    if n_more:
        w(f"The table stops at k = {QA_MAX_K}; {n_more} more values of k with at least {cl['min_edges']} nodes are in "
          f"trees_h1_tk.csv. They enter the fits, and F4 shows them on a log k axis.")
        w("")
    if tk.get("fits"):
        w(md_table(["Quantity", "Model", "k values", "Slope [95% CI]", "k^2 coefficient [95% CI]", "p (k^2, bootstrap)"],
                   [[f["quantity"], f["model"], f["n_k"],
                     fci(f["slope"], f.get("slope_lo"), f.get("slope_hi")) if f["model"] == "linear" else fmt(f["slope"]),
                     fci(f.get("k2"), f.get("k2_lo"), f.get("k2_hi")) if f["model"] == "quadratic" else "",
                     f.get("p_k2_boot", "")] for f in tk["fits"]]))
        w("")
    w(f"Trees enter if their root lies more than {TK_MARGIN_TEXT} run days before the end of the data. Fits are "
      "weighted by the number of acquisitions per k. F4 shows the means and variances with the linear fits.")
    w("")
    a = main["adjacent"]
    w(f"Consecutive transmission intervals along an agent-level path: Spearman rho "
      f"{fci(a['rho'], a['rho_lo'], a['rho_hi'])}, n = {fmt(a['n_pairs'])} pairs.")
    w("")
    w("## 7. H3: content change per generation")
    w("")
    h3 = main["h3_rows"] + s["b1_c"]
    w(md_table(["Channel", "Edges", "Contexts carried", "Contexts changed", "c [95% CI]", "Inherited by children",
                "Reverted"],
               [[r["channel"] + (f" ({r['rules']})" if r["channel"].startswith("memory_consolidation") else ""),
                 r.get("n_edges", ""), r["contexts_carried"], r["contexts_changed"],
                 fci(r["c"], r.get("c_lo"), r.get("c_hi")), r.get("inherited_share", ""), r.get("reverted_share", "")]
                for r in h3]))
    w("")
    w("c is the share of quantity contexts carried from parent to child (same context key in both) whose value "
      "changed. For B1 it is the share of quantity facts whose context stays at a consolidation and whose value "
      f"changed (rule set in brackets; the main rule set is {s['rules']}, and the quantities row is also given for "
      "the other rule sets; Wilson CI, which ignores clustering by agent). B2 CIs: cluster bootstrap by tree root.")
    w("")
    w("## 8. Attractor test")
    w("")
    w(md_table(["Measure", "g", "Nodes", "Units", "Mean [95% CI]"],
               [[r["measure"], r["generation"] if r["generation"] >= 0 else "slope", r["n_nodes"], r["n_units"],
                 fci(r["mean"], r.get("mean_lo"), r.get("mean_hi"))] for r in main["attractor"]
                if r.get("reported", True)]))
    w("")
    w("Windows are the 41 tokens around the anchor. Similarity is the token Jaccard index with the unit's most common "
      "window. g is the agent-level generation of the occurrence. Slope rows give the within-unit slope on "
      "generation (cluster bootstrap by unit).")
    w("")
    w("## 9. Synthetic validation")
    w("")
    if syn is not None and syn.height:
        sp = s["synthetic"]["params"]
        w(f"{s['synthetic']['reps']} null replicates of {fmt(s['synthetic']['n_units'])} units each, plus power "
          f"replicates. Parameters from the MAP forest: R by generation {', '.join(fmt(x) for x in sp['R'])}; "
          f"independent share {fmt(sp['p_env'])}; spurious env share {fmt(sp['p_spur'])}; content change "
          f"probability {fmt(sp['c'])}; gamma {fmt(sp['gamma'])}.")
        w("")
        w(md_table(["Scenario", "Statistic", "Replicates", "Estimate [95% interval]"],
                   [[r["scenario"], r["statistic"], r["n_replicates"], fci(r["estimate"], r["lo"], r["hi"])]
                    for r in syn.iter_rows(named=True)]))
        w("")
    else:
        w("Not run.")
        w("")
    w("## 10. Sensitivity")
    w("")
    if s["sensitivity"]:
        cols = ["variant", "value", "n_edges", "n_env", "max_generation", "max_generation_occurrence",
                "independent_share_of_acquisitions", "h3_c_agent_retelling", "h1det_p_chat_to_chat_other",
                "h1_p_combined"]
        w(md_table(["Variant", "Value", "Transmissions", "Independent", "Max generation",
                    "Max occurrence-level generation", "Independent share of acquisitions", "H3 c",
                    "H1 determined p, chat to chat", "H1 MAP combined p"],
                   [[r.get(k_, "") for k_ in cols] for r in s["sensitivity"]]))
        w("")
        w(f"Permutations: {cl['perms_sensitivity']}; no bootstrap intervals for these runs.")
        w("")
    w("## 11. Posterior draws")
    w("")
    if ds.height:
        w(md_table(["Statistic", "Draws", "Median", "2.5%", "97.5%"],
                   [[r["statistic"], r["n_draws"], r["median"], r["q025"], r["q975"]] for r in ds.iter_rows(named=True)]))
        w("")
    w("## 12. Runtime")
    w("")
    w(", ".join(f"{k} {v:.0f} s" for k, v in s["timings"].items()) + ".")
    w("")
    return "\n".join(L)


TK_MARGIN_TEXT = "30"
QA_MAX_G = 10
QA_MAX_K = 20
