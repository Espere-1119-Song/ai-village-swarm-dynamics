"""Data for the demo video, read from the project's aggregated outputs: writes data.js and copies the fonts and
figure thumbnails that scenes.html loads (both copies are git-ignored)."""
import json
import shutil
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import writeup_figures as wf  # noqa: E402

out = {}

win = sorted((r for r in wf.rows("hawkes_windows.csv") if r["accepted"].lower() == "true"), key=lambda r: r["date_start"])
out["rho"] = [round(float(r["rho"]), 3) for r in win]

haz = [r for r in wf.rows("memory_hazard_v2.csv") if r["scope"] == "family" and r["stratum"] == "All standard" and r["g"].isdigit()]
out["hazard"] = [round(100 * float(r["h"]), 2) for r in sorted(haz, key=lambda r: int(r["g"])) if int(r["g"]) <= 20]

cps = [r for r in wf.rows("changepoints.csv") if r["method"] == "pelt_l2" and r["level"] in ("agent", "family", "lexical")]
ent = wf.rows("changelog_dates.csv")
start = date(2025, 3, 31)


def week(d):
    x = date.fromisoformat(d)
    return x - timedelta(days=x.weekday())


al, un, en = defaultdict(int), defaultdict(int), defaultdict(int)
for r in cps:
    (al if r["aligned"].lower() == "true" else un)[week(r["date"])] += 1
for r in ent:
    en[week(r["date_start"])] += 1
weeks = [start + timedelta(weeks=i) for i in range(80)]
out["weekly"] = {"entries": [en[w] for w in weeks], "aligned": [al[w] for w in weeks], "unaligned": [un[w] for w in weeks]}
out["n_cp"] = len(cps)

d = wf.qa_table("changepoint.md", "| weekday | run_days | daily_series_changepoints | goal_transitions |")
out["weekdays"] = [{"day": r["weekday"], "run_days": int(r["run_days"]), "cps": int(r["daily_series_changepoints"]),
                    "goals": int(r["goal_transitions"])} for r in d]

nodes = defaultdict(dict)
for r in wf.rows("depgraph_example_nodes.csv"):
    if r["no_edge"] == "0":
        nodes[r["graph"]][int(r["node"])] = (int(r["layer"]), int(r["agent"]))
edges = defaultdict(list)
for r in wf.rows("depgraph_example_edges.csv"):
    kind = "g" if r["graph"] == "generator" else ("s" if r["same_agent"] == "1" else "o")
    edges[r["graph"]].append((int(r["parent"]), int(r["child"]), kind))
graphs = {}
for g in ("ai_village", "generator"):
    nd = nodes[g]
    layer = {n: v[0] for n, v in nd.items()}
    agent = {n: v[1] for n, v in nd.items()}
    parents = defaultdict(list)
    for p, c, _ in edges[g]:
        parents[c].append(p)
    pos, tallest, n_layers = wf._graph_positions(sorted(nd), layer, parents, agent)
    half = max((tallest - 1) / 2, 1)
    ids = sorted(nd)
    idx = {n: i for i, n in enumerate(ids)}
    graphs[g] = {"layers": n_layers,
                 "nodes": [[round(layer[n] / (n_layers - 1), 4), round(pos[n] / half, 4), layer[n]] for n in ids],
                 "edges": [[idx[p], idx[c], k] for p, c, k in edges[g]]}
out["graphs"] = graphs

js = "window.DATA = " + json.dumps(out, separators=(",", ":")) + ";\n"
(HERE / "data.js").write_text(js, encoding="utf-8")
(HERE / "fonts").mkdir(exist_ok=True)
(HERE / "assets").mkdir(exist_ok=True)
for f in (ROOT / "scripts" / "plot_style" / "fonts").glob("InstrumentSans-*.ttf"):
    shutil.copy(f, HERE / "fonts" / f.name)
for k in ("overview", "sources", "memory", "depgraph_example"):
    shutil.copy(ROOT / "reports" / "figures" / f"{k}.png", HERE / "assets" / f"{k}.png")
print("rho", len(out["rho"]), "below 1:", sum(r < 1 for r in out["rho"]), "| hazard", out["hazard"][:3], out["hazard"][-2:],
      "| cps", out["n_cp"], "| weekdays", [w["day"] for w in out["weekdays"]],
      "| graph nodes", {g: len(v["nodes"]) for g, v in graphs.items()}, "| bytes", len(js))
