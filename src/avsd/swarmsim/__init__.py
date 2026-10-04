"""Module D: re-implementation of the swarm simulator of Wenhao Chai's blog post (SPEC 8).

D1: the task DAG generator (`dag`), one agent, pass@k, the standard and the recursive swarm with
scheduling overhead and communication cost (`sim`), the coverage and best-score metrics
(`metrics`), and the reproduction checks of SPEC 8.2 (`reproduce`). `run_reproduction(cfg)` runs
the checks and writes outputs/tables/swarmsim_reproduction.csv, outputs/figures/swarmsim_coverage.pdf
and outputs/qa/swarmsim_d1.md.

D2 to D4 (SPEC 8.3 to 8.5): artifact touches of computer-use turns and their read/write rules
(`touches`, `depgraph_data`), the work-dependency graph per village goal and its structure
statistics (`depgraph`), the continuation rule (`continuation`), figure F7 (`figure_f7`) and the
run with its QA report (`calibrate`, `calibrate_report`). `run_calibration(cfg)` (CLI
`avsd swarmsim calibrate`) writes outputs/tables/depgraph_*.csv, outputs/figures/F7_depgraph_generator
and outputs/qa/swarmsim_d2_d4.md.

Source: Wenhao Chai, "Predictable Swarm Scaling", 2026,
https://wenhaochai.com/blogs/predictable-swarm-scaling.html
"""

from avsd.swarmsim.dag import (
    BLOG, Dag, GenParams, Task, draw_task, grow_dag, score_scale, scores, structure_stats, task_dag,
)
from avsd.swarmsim.reproduce import ReproConfig, run_reproduction
from avsd.swarmsim.sim import BLOG_OVERHEADS, Overheads, Run, pass_at_k, simulate, single_agent

__all__ = [
    "BLOG", "BLOG_OVERHEADS", "Dag", "GenParams", "Overheads", "ReproConfig", "Run", "Task",
    "draw_task", "grow_dag", "pass_at_k", "run_reproduction", "score_scale", "scores",
    "simulate", "single_agent", "structure_stats", "task_dag",
]
