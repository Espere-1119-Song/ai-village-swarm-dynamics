"""Command line entry point: `avsd <command>`. See SPEC 3.3."""

from __future__ import annotations

import typer

from avsd.config import load_config

app = typer.Typer(no_args_is_help=True, add_completion=False)
hawkes_app = typer.Typer(no_args_is_help=True)
lineage_app = typer.Typer(no_args_is_help=True)
swarmsim_app = typer.Typer(no_args_is_help=True)
app.add_typer(hawkes_app, name="hawkes", help="Module A: multivariate Hawkes process.")
app.add_typer(lineage_app, name="lineage", help="Module B: transmission lineage.")
app.add_typer(swarmsim_app, name="swarmsim", help="Module D: swarm simulator.")

ConfigOpt = typer.Option(None, "--config", "-c", help="Path to a YAML config.")


def _todo(name: str) -> None:
    raise typer.Exit(f"`avsd {name}` is not implemented yet.")


@app.command()
def ingest(
    download: bool = typer.Option(True, help="Download from Hugging Face first."),
    tables: str = typer.Option("", help="Comma-separated subset of tables. Default all."),
    config: str = ConfigOpt,
) -> None:
    """Download the dataset and convert tables to parquet (SPEC 4.1 step 2)."""
    import time

    from avsd.io.download import download_tables
    from avsd.io.qa import write_ingest_report
    from avsd.io.tables import SPECS, convert_table

    cfg = load_config(config)
    if download:
        download_tables(cfg)
    names = [t for t in tables.split(",") if t] or list(SPECS)
    stats = {}
    for name in names:
        t0 = time.time()
        stats[name] = convert_table(SPECS[name], cfg["paths"]["raw"], cfg["paths"]["tables"])
        typer.echo(f"{name}: {stats[name].rows:,} rows in {time.time() - t0:.0f}s")
    report = cfg["paths"]["outputs"] / "qa" / "ingest.md"
    write_ingest_report(stats, cfg, report)
    typer.echo(f"QA report: {report}")


@app.command("build-events")
def build_events(
    workers: int = typer.Option(0, help="Processes for memory hashing. 0 = SLURM_CPUS_PER_TASK."),
    config: str = ConfigOpt,
) -> None:
    """Unified event table, run periods, agents, roster, rooms, CHANGELOG (SPEC 4.1 steps 3-8)."""
    from avsd.events.build import build_events as run

    cfg = load_config(config)
    res = run(cfg, n_workers=workers or None)
    s = res.stats
    typer.echo(
        f"events_unified: {res.unified.height:,} rows; run days {res.blocks['date'].n_unique()}; "
        f"{s['runtime_s']:.0f} s, peak RSS {s['peak_rss_gb']:.1f} GB"
    )
    typer.echo(f"QA report: {cfg['paths']['outputs'] / 'qa' / 'build_events.md'}")


@hawkes_app.command("fit")
def hawkes_fit(
    window: str = typer.Option("goal", help="goal | rolling"),
    workers: int = typer.Option(0, help="Processes. 0 = SLURM_CPUS_PER_TASK, else 1."),
    stage: str = typer.Option("", help="Run one stage only (accept, boot, matched, sens, valid, rolling, assemble)."),
    config: str = ConfigOpt,
) -> None:
    """Module A on the real data (SPEC 5): fits, acceptance, bootstrap, validation, outputs."""
    import os

    from avsd.hawkes.pipeline import STAGES, run_all, run_stage

    if window not in ("goal", "rolling"):
        raise typer.BadParameter("window must be goal or rolling")
    if stage and stage not in STAGES:
        raise typer.BadParameter(f"stage must be one of {STAGES}")
    cfg = load_config(config)
    n = workers or int(os.environ.get("SLURM_CPUS_PER_TASK", "1"))
    if stage:
        run_stage(cfg, stage, n)
    else:
        run_all(cfg, window, n)
    typer.echo(f"QA report: {cfg['paths']['outputs'] / 'qa' / 'hawkes.md'}")


@lineage_app.command("memory")
def lineage_memory(config: str = ConfigOpt) -> None:
    """Module B1: fact retention across memory consolidations (H2)."""
    from avsd.lineage.memory import run_memory

    result = run_memory(load_config(config))
    typer.echo(f"memory lineage done: {len(result)} QA fields")


@lineage_app.command("trees")
def lineage_trees(
    rules: str = typer.Option("v2", help="B1 fact-presence rule set for memory presence: v1, v2 or v3 (v2 is B1's "
                              "main rule set since 2026-10-03)."),
    env_rule: str = typer.Option("precede", help="env_i rule: precede (main) or any (SPEC 6.4.2 literal)."),
    exposure: str = typer.Option("main", help="Chat exposure: main, ever or all."),
    hawkes: str = typer.Option("auto", help="Module A kernels for same-day chat edges: auto, on or off."),
    gamma: str = typer.Option("tier1", help="tier1 (grid on tier-1 name labels); hand or composite (time term and "
                              "gamma chosen on the owner's labels, or the owner's plus Claude's elsewhere); or a "
                              "number."),
    units: bool = typer.Option(False, "--units", help="Rebuild the information units first."),
    workers: int = typer.Option(0, help="Processes. 0 = SLURM_CPUS_PER_TASK."),
    config: str = ConfigOpt,
) -> None:
    """Module B2: transmission trees between agents (SPEC 6.4)."""
    from pathlib import Path

    from avsd.lineage.b2_units import build_units
    from avsd.lineage.trees import run_trees

    cfg = load_config(config)
    if units or not (Path(cfg["paths"]["interim"]) / "b2" / "units.parquet").exists():
        build_units(cfg, workers or None)
    res = run_trees(cfg, rules=rules, env_rule=env_rule, exposure=exposure, hawkes=hawkes,
                    n_workers=workers or None, gamma_mode=gamma)
    typer.echo(f"{res['n_units']:,} units, {res['main']['n_edges']:,} transmission edges between agents, "
               f"gamma {res['gamma']}; "
               f"QA report: {Path(cfg['paths']['outputs']) / 'qa' / 'lineage_trees.md'}")


@app.command()
def changepoint(config: str = ConfigOpt) -> None:
    """Module C: change points aligned with the CHANGELOG."""
    from avsd.changepoint import run_changepoint

    result = run_changepoint(load_config(config))
    typer.echo(f"{result['n_changepoints']} change points; outputs: {result['outputs']}")


@swarmsim_app.command("reproduce")
def swarmsim_reproduce(config: str = ConfigOpt) -> None:
    """Module D1: reproduce the blog's swarm-scaling results."""
    from avsd.swarmsim import run_reproduction

    result = run_reproduction(load_config(config))
    typer.echo(f"{result['n_failed_required']} required checks failed; outputs: {result['outputs']}")


@swarmsim_app.command("calibrate")
def swarmsim_calibrate(
    force_extract: bool = typer.Option(False, "--force-extract", help="Re-extract the artifact touches."),
    rules: str = typer.Option("", help="Touch rules: v2 (main, confirmed by the owner; the default) or v1 "
                                       "(sensitivity version, outputs get _v1)."),
    workers: int = typer.Option(0, help="Processes. 0 = SLURM_CPUS_PER_TASK, else all cores."),
    config: str = ConfigOpt,
) -> None:
    """Modules D2 to D4: AI Village dependency graph, structure against the generator, continuation, F7."""
    from avsd.swarmsim.calibrate import run_calibration
    from avsd.swarmsim.touches import RULE_SETS

    if rules and rules not in RULE_SETS:
        raise typer.BadParameter(f"rules must be one of {sorted(RULE_SETS)}")
    cfg = load_config(config)
    if workers:
        cfg["swarmsim_calibrate"] = {**(cfg.get("swarmsim_calibrate") or {}), "workers": workers}
    result = run_calibration(cfg, force_extract=force_extract, log=typer.echo, rules=rules or None)
    typer.echo(f"QA report: {result['outputs']['qa']}")


@app.command()
def ethogram(config: str = ConfigOpt) -> None:
    """Module E: screenshot ethogram."""
    load_config(config)
    _todo("ethogram")


@app.command()
def report(config: str = ConfigOpt) -> None:
    """Collect figures and tables into reports/index.html (SPEC 10.1)."""
    from avsd.report.build import build_report

    path = build_report(load_config(config))
    typer.echo(f"{path} ({path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    app()
