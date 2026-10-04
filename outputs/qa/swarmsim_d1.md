# QA: swarm simulator reproduction (module D1)

Source: Wenhao Chai, "Predictable Swarm Scaling", 2026, https://wenhaochai.com/blogs/predictable-swarm-scaling.html. Re-implemented without the author's code (SPEC 8.1, 8.2, appendix B).

## Summary

- Families simulated: 256 of 16 tasks each (4096 task DAGs, 65536 single-agent runs, 49152 swarm runs). Seed 20261003.
- Required SPEC 8.2 checks: 15 of 15 within the 20% tolerance.
- Standard swarm@64: g50 = 31.7 (95% CI 31.5 to 31.9) (blog 33); speedup at best score 0.8 = 18.1 (95% CI 17.8 to 18.4) (blog 16); finishes every step at 0.0812 (95% CI 0.0787 to 0.0836) T1, and at 0.0856 (95% CI 0.0834 to 0.0879) T1 with 32 agents (blog about 0.10 for both).
- lambda = ln g50 / ln N for N = 4 to 64: recursive swarm (3 layers) 0.885 to 0.931 (blog 0.88 to 0.93); standard swarm 0.889, 0.914, 0.913, 0.889, 0.831 (blog 0.89 to 0.92 for N = 4 to 16, 0.84 at 64).
- Runtime: 77 s wall on 32 processes (dj-l40-0.grasp.maas), 2235 s of simulation CPU time.
- No parameter was tuned to the blog's numbers; every parameter value is the blog's.

## What is implemented

- `avsd.swarmsim.dag`: the generator (`grow_dag`, `layer_sizes`, `draw_task`, `task_dag`), the task score scale (`score_scale`, `scores`) and structure statistics (`structure_stats`, `relayer`).
- `avsd.swarmsim.sim`: readiness, the deepest-first step rule, one agent (`single_agent`), the standard swarm (`simulate(..., layers=1)`), the recursive swarm (`simulate(..., layers=L)`), pass@k (`pass_at_k`), scheduling overhead and communication cost (`Overheads`, `comm_factor`), best-score events (`record_events`).
- `avsd.swarmsim.metrics`: averaged coverage and best-score curves, first-reach times, speedup g_x and lambda = ln g50 / ln N.
- `avsd.swarmsim.reproduce`: the family protocol, the checks, outputs and this report. `avsd.swarmsim.run_reproduction(cfg)` runs everything.

## Ambiguities and how we resolved them

- **Sources.** Blog: The project owner has no code from the author. Ours: Implemented from the blog text (English and Chinese versions) and SPEC appendix B. The blog page also loads its own simulator (assets/data/edgebench-logsigmoid.js v47 and assets/swarm-worker.js v31). We read those files as a specification only, never executed them, and used them to settle the points below where the text is silent.
- **Clamps on task draws.** Blog: Steps 723 e^{0.4z}, layers 17 e^{0.2z}, peak 0.28 + 0.07z, merge probability 0.46 e^{0.3z}, no bounds given. Ours: Rounded to integers and clamped as in the blog's code: steps to [10, 1500], layers to [3, 30], peak to [0.1, 0.9], merge probability to [0, 0.9]. The steps clamp binds when z > 1.82, about 3.4% of tasks (our share is under Generator statistics).
- **Layer-size rounding.** Blog: Layer d gets the logistic rise across that layer times noise. Ours: Layer 0 holds the root, the other n - 1 steps are split by the noisy rises and rounded; the rounding residue is added to or taken from the fullest layer (blog code).
- **Main parent layer.** Blog: Drawn from the layer above. Ours: From the previous non-empty layer (identical unless noise empties a layer).
- **Sibling.** Blog: An extra parent is a sibling of the main parent with probability 0.2. Ours: A sibling is another main child of the main parent's main parent, drawn with the same softmax weights; when the main parent has no sibling the layer route is taken (blog code).
- **Layer b of an extra parent.** Blog: P(b) proportional to 0.8^b as far as the root. Ours: b starts at 1 (the main parent's layer) and moves up one more layer with probability 0.8, stopping at the root. The root and any ancestor of a chosen parent are skipped as candidates; a skipped or empty-layer draw uses up one of at most 8K tries, so a step can end with fewer than K extra parents (blog code).
- **Improvement delta.** Blog: delta is a parent's own improvement over what it built on. Ours: delta = the step's change, its value minus its best parent's value (root 0).
- **Score scale.** Blog: 90th percentile of the best recipes of 64 DAGs grown like the task's. Ours: 64 DAGs with the task's steps, layers, peak and merge probability, each with its own layer noise and fertility; the value at sorted index round(0.9 x 63) = 57 is worth 1. Values below the root's 0 count as 0.
- **Clock and T1.** Blog: Each task's clock is stretched by e^{delta_b}; T1 is how long the slowest single-agent run takes to finish every step. Ours: Each task's raw times are divided by the mean time of its 16 single-agent runs to finish every step and multiplied by e^{delta_b}; then all times of the family are divided by the slowest of its 256 single-agent runs, so that run ends at exactly 1 (blog code).
- **Averaging and speedup.** Blog: g_x is how many times sooner a swarm reaches level x than one agent. Ours: Scores are averaged over the family's tasks first (one agent over all 16 runs per task, a swarm over one run per task); g_x is the ratio of the first times the two averages reach x (blog code). We use exact step functions where the blog evaluates one agent on a grid of about 0.7% in log time.
- **Finish time.** Blog: It finishes every step at about 0.10 T1. Ours: The first time the family-average coverage reaches 1, i.e. the latest task finish. The mean over tasks is in swarmsim_scaling.csv (task_finish_mean).
- **Scheduling overhead.** Blog: 5% of a median step whenever an agent starts or builds on another agent's work. Ours: The median step is the median layer cost c_d over steps (no time noise). A new agent pays 5% on its first step, and any step with a parent finished by another agent pays 5%, so the first step of a dispatched or forked agent pays 10% (blog code adds both). One agent on its own pays nothing.
- **Communication cost.** Blog: +15% per step while two group members are active, +1% per further active member. Ours: Charged as a share of the step's work (time noise included), from the group sizes when the step starts, after all starts and stops of that instant, and fixed for the whole step. Alive agents count as active; an agent is never idle while alive (blog code).
- **Who holds a ready step.** Blog: The running agent that made that step ready holds it. Ours: The agent that finished its last parent puts it on its list; it also joins the list of every other alive agent that finished one of its parents. A free slot draws uniformly among all ready, unstarted steps.
- **Standard swarm refill.** Blog: An agent that empties its list stops and the coordinator starts a new agent on a random ready step. Ours: The coordinator fills every free slot whenever ready steps wait, also while the swarm is first growing ('no budget sits idle while ready steps wait').
- **Recursive forks.** Blog: Keep one new step, fork sub-agents for the rest within budget, up to the layer cap. Ours: The opened steps are shuffled; the agent keeps the first and forks for the others while fewer than N agents are alive and its own layer is below the cap. A free slot drawn to a step whose holder sits at the cap goes to the coordinator, which starts a new layer-1 agent. Standard and recursive runs of one task and size share a random stream (blog code).
- **pass@k.** Blog: k agents that each follow the rule on their own. Ours: k independent single-agent runs; `pass_at_k` takes one DAG per part (the arena gives each part a DAG of its own) and the best score is the best over parts. Not part of the SPEC 8.2 checks.
- **Diffusion-size depth check.** Blog: 88% at the diffusion DAG's size. Ours: Not checked; the blog does not give that DAG's steps or layers.

## SPEC appendix B against the blog

Appendix B agrees with the blog text on every parameter and rule it states; we found no contradiction. It leaves out details the blog gives, which we take from the blog: the running agent that made a step ready holds it, a merge step can sit on several lists, and a sub-agent's group is its forker and the forker's other sub-agents. 'Each figure runs 16 tasks' (appendix B: 每张图 16 个任务) means 16 tasks, each with its own DAG, per family; a family is the unit behind one figure and behind T1.

## Reproduction table

`Ours` is the mean over units (families, unless the range column names DAGs or tasks) with a bootstrap 95% CI of that mean. `Range` is the 2.5% to 97.5% range of single units; for families it is the spread expected for one 16-task family like the blog's. `Blog pctl` is the share of single units below the blog's value, i.e. where the blog's single family would sit among ours. For qualitative checks `Ours` is the share of families where the statement holds, and the status is set by the family means. Deviation is relative to the blog value, or to the nearest end of a blog range (0 inside it). Pass means a deviation of at most 20%.

| Check | Required | Blog | Ours | 95% CI | Range | n | Blog pctl | Deviation | Status |
|---|---|---|---|---|---|---|---|---|---|
| Standard swarm coverage curve shifts earlier at every larger N (N = 1 to 64) | yes | earlier as the swarm grows | 1 |  |  | 256 |  |  | pass |
| Standard swarm best score curve shifts earlier at every larger N (N = 1 to 64) | no | earlier as the swarm grows | 0.982 |  |  | 221 |  |  | pass |
| Standard swarm@32 finishes every step (t / T1) | yes | about 0.10 | 0.0856 | 0.0834 to 0.0879 | 0.0632 to 0.132 (family) | 256 | 83% | 0.144 | pass |
| Standard swarm@64 finishes every step (t / T1) | yes | about 0.10 | 0.0812 | 0.0787 to 0.0836 | 0.0542 to 0.13 (family) | 256 | 86% | 0.188 | pass |
| Standard swarm finish time, 64 over 32 agents | yes | about 1 (no sooner) | 0.944 | 0.936 to 0.951 | 0.823 to 1.07 (family) | 256 | 79% | 0.0562 | pass |
| Standard swarm@64 speedup at half coverage, g50 | yes | 33 | 31.7 | 31.5 to 31.9 | 28.6 to 34.4 (family) | 256 | 82% | 0.0391 | pass |
| Standard swarm@64 speedup at best score 0.8 | yes | 16 | 18.1 | 17.8 to 18.4 | 13.3 to 21.2 (family) | 221 | 17% | 0.131 | pass |
| Recursive swarm@4, 3 layers, lambda = ln g50 / ln N | yes | 0.88 to 0.93 | 0.886 | 0.885 to 0.887 | 0.867 to 0.908 (family) | 256 |  | 0 | pass |
| Recursive swarm@8, 3 layers, lambda = ln g50 / ln N | yes | 0.88 to 0.93 | 0.917 | 0.917 to 0.918 | 0.905 to 0.932 (family) | 256 |  | 0 | pass |
| Recursive swarm@16, 3 layers, lambda = ln g50 / ln N | yes | 0.88 to 0.93 | 0.931 | 0.93 to 0.931 | 0.92 to 0.941 (family) | 256 |  | 0.000611 | pass |
| Recursive swarm@32, 3 layers, lambda = ln g50 / ln N | yes | 0.88 to 0.93 | 0.926 | 0.925 to 0.926 | 0.912 to 0.938 (family) | 256 |  | 0 | pass |
| Recursive swarm@64, 3 layers, lambda = ln g50 / ln N | yes | 0.88 to 0.93 | 0.885 | 0.883 to 0.886 | 0.857 to 0.907 (family) | 256 |  | 0 | pass |
| Standard swarm@4, lambda | yes | 0.89 to 0.92 | 0.889 | 0.888 to 0.89 | 0.871 to 0.909 (family) | 256 |  | 0.00113 | pass |
| Standard swarm@8, lambda | yes | 0.89 to 0.92 | 0.914 | 0.913 to 0.915 | 0.902 to 0.928 (family) | 256 |  | 0 | pass |
| Standard swarm@16, lambda | yes | 0.89 to 0.92 | 0.913 | 0.912 to 0.913 | 0.902 to 0.924 (family) | 256 |  | 0 | pass |
| Standard swarm@64, lambda | yes | 0.84 | 0.831 | 0.83 to 0.832 | 0.807 to 0.851 (family) | 256 | 80% | 0.0108 | pass |
| Recursive (3 layers) over standard g50 at N = 16 | no | 1.04 | 1.05 | 1.05 to 1.05 | 1.03 to 1.07 (family) | 256 | 12% | 0.0103 | pass |
| Recursive (3 layers) over standard g50 at N = 64 | no | 1.2 | 1.25 | 1.25 to 1.25 | 1.22 to 1.28 (family) | 256 | 0% | 0.0424 | pass |
| Standard swarm@4 speedup at best score 0.5 below g50 | no | smaller from 4 agents on | 0.984 |  |  | 256 |  |  | pass |
| Standard swarm@8 speedup at best score 0.5 below g50 | no | smaller from 4 agents on | 1 |  |  | 256 |  |  | pass |
| Standard swarm@16 speedup at best score 0.5 below g50 | no | smaller from 4 agents on | 1 |  |  | 256 |  |  | pass |
| Standard swarm@32 speedup at best score 0.5 below g50 | no | smaller from 4 agents on | 1 |  |  | 256 |  |  | pass |
| Standard swarm@64 speedup at best score 0.5 below g50 | no | smaller from 4 agents on | 1 |  |  | 256 |  |  | pass |
| Generator best recipe depth, language-modelling size | no | 94% | 0.927 | 0.922 to 0.932 | 0.688 to 1 (DAG) | 1024 | 56% | 0.0136 | pass |
| Generator best recipe depth, diffusion size | no | 88% |  |  |  | 0 |  |  | not checked |
| Generator cross-layer edge share | no | 18% | 0.186 | 0.186 to 0.187 | 0.156 to 0.214 (DAG) | 1024 | 33% | 0.036 | pass |
| Generator leaf share (steps without children) | no | about half | 0.481 | 0.48 to 0.483 | 0.44 to 0.527 (DAG) | 1024 | 80% | 0.0376 | pass |
| Best recipe of a typical task DAG on the task's scale | no | about 0.83 | 0.835 | 0.83 to 0.84 | 0.608 to 1 (task) | 4096 | 49% | 0.00619 | pass |
| Share of task DAGs whose best recipe reaches 0.95 | no | about 1 in 6 | 0.19 | 0.177 to 0.203 | 0 to 0.414 (family) | 256 | 43% | 0.14 | pass |

Notes: Standard swarm coverage curve shifts earlier at every larger N (N = 1 to 64): levels 0.25, 0.5, 0.75, 0.9; ours = share of families where every level is reached strictly sooner at each larger N; family-mean times to cov50: 0.297 > 0.172 > 0.0866 > 0.0444 > 0.0236 > 0.0136 > 0.00938. Standard swarm best score curve shifts earlier at every larger N (N = 1 to 64): levels 0.5, 0.8; ours = share of families where every level is reached strictly sooner at each larger N; family-mean times to best80: 0.678 > 0.408 > 0.22 > 0.121 > 0.0702 > 0.0464 > 0.0385. Standard swarm@32 finishes every step (t / T1): first time the family-average coverage reaches 1. Standard swarm@64 finishes every step (t / T1): first time the family-average coverage reaches 1. Standard swarm@64 speedup at best score 0.8: families whose average best score never reaches 0.8 are left out. Standard swarm@4 speedup at best score 0.5 below g50: ours = share of families; family means 2.67 against 3.43. Standard swarm@8 speedup at best score 0.5 below g50: ours = share of families; family means 4.33 against 6.69. Standard swarm@16 speedup at best score 0.5 below g50: ours = share of families; family means 6.68 against 12.6. Standard swarm@32 speedup at best score 0.5 below g50: ours = share of families; family means 9.4 against 21.8. Standard swarm@64 speedup at best score 0.5 below g50: ours = share of families; family means 11.9 against 31.7. Generator best recipe depth, language-modelling size: 1024 DAGs of 723 steps and 17 layers without task variation; layer of the best value over the deepest layer. Generator best recipe depth, diffusion size: the blog does not give the diffusion DAG's size. Generator cross-layer edge share: 1024 DAGs of 723 steps and 17 layers without task variation; edges spanning 2 or more layers after relayering each step one layer below its deepest parent. Generator leaf share (steps without children): 1024 DAGs of 723 steps and 17 layers without task variation. Best recipe of a typical task DAG on the task's scale: ours = median over task DAGs, CI by bootstrap over tasks. Share of task DAGs whose best recipe reaches 0.95: ours = mean over families of the share of their tasks.

## Scaling by swarm size

Means over families (95% CI in swarmsim_scaling.csv). Times in T1.

| Kind | N | t50 | t at 0.8 best | Finish | g50 | g90 | g at 0.8 best | lambda | Scheduling share | Comm share |
|---|---|---|---|---|---|---|---|---|---|---|
| recursive | 2 | 0.172 | 0.408 | 0.577 | 1.73 | 1.73 | 1.67 | 0.792 | 0.0216 | 0.145 |
| recursive | 4 | 0.087 | 0.22 | 0.302 | 3.42 | 3.39 | 3.09 | 0.886 | 0.031 | 0.168 |
| recursive | 8 | 0.0441 | 0.119 | 0.166 | 6.74 | 6.64 | 5.72 | 0.917 | 0.0392 | 0.188 |
| recursive | 16 | 0.0225 | 0.0657 | 0.103 | 13.2 | 12.8 | 10.3 | 0.931 | 0.0474 | 0.203 |
| recursive | 32 | 0.012 | 0.0411 | 0.0801 | 24.7 | 23.3 | 16.7 | 0.926 | 0.0556 | 0.227 |
| recursive | 64 | 0.0075 | 0.0329 | 0.0752 | 39.7 | 34 | 21.4 | 0.885 | 0.0624 | 0.268 |
| standard | 2 | 0.172 | 0.408 | 0.579 | 1.73 | 1.73 | 1.66 | 0.79 | 0.0215 | 0.15 |
| standard | 4 | 0.0866 | 0.22 | 0.302 | 3.43 | 3.4 | 3.09 | 0.889 | 0.031 | 0.17 |
| standard | 8 | 0.0444 | 0.121 | 0.168 | 6.69 | 6.55 | 5.63 | 0.914 | 0.0391 | 0.209 |
| standard | 16 | 0.0236 | 0.0702 | 0.108 | 12.6 | 12.1 | 9.68 | 0.913 | 0.0473 | 0.283 |
| standard | 32 | 0.0136 | 0.0464 | 0.0856 | 21.8 | 20.2 | 14.8 | 0.889 | 0.0555 | 0.417 |
| standard | 64 | 0.00938 | 0.0385 | 0.0812 | 31.7 | 27.3 | 18.1 | 0.831 | 0.0623 | 0.611 |

One agent: t50 = 0.297, t at best 0.8 = 0.678, mean task finish = 0.771 T1. Scheduling and comm shares are paid time over work time, averaged over runs.

## Generator statistics

1024 DAGs of 723 steps and 17 layers (no task variation), mean and 2.5% to 97.5% range over DAGs. The blog reports only the first two (94%, 18%); the others are the fitted shape statistics it names without values.

| Statistic | Mean | Range |
|---|---|---|
| best_depth_share | 0.927 | 0.688 to 1 |
| cross_layer_share | 0.186 | 0.156 to 0.214 |
| leaf_share | 0.481 | 0.44 to 0.527 |
| multi_parent_share | 0.422 | 0.381 to 0.463 |
| mean_parents | 1.73 | 1.62 to 1.84 |
| sibling_merge_share | 0.455 | 0.376 to 0.532 |
| outdeg_gini | 0.508 | 0.473 to 0.546 |
| top10_child_share | 0.416 | 0.372 to 0.466 |
| peak_layer_share | 0.279 | 0.0625 to 0.5 |

Task DAGs (4096, with task variation): steps 775 on average, layers 17.4, cross-layer share 0.184, best-recipe depth 0.927, leaf share 0.477; steps clamped at 1500 in 3.9% of tasks.

## Deviations

No check exceeds the 20% tolerance, so nothing goes to docs/decisions.md under SPEC 8.2.
- Standard swarm@32 finishes every step (t / T1): blog about 0.10, ours 0.0856 (deviation 14%, pass); the blog's value lies inside our family range 0.0632 to 0.132, so one 16-task family like the blog's can show it.
- Standard swarm@64 finishes every step (t / T1): blog about 0.10, ours 0.0812 (deviation 19%, pass); the blog's value lies inside our family range 0.0542 to 0.13, so one 16-task family like the blog's can show it.
- Standard swarm@64 speedup at best score 0.8: blog 16, ours 18.1 (deviation 13%, pass); the blog's value lies inside our family range 13.3 to 21.2, so one 16-task family like the blog's can show it.
- Share of task DAGs whose best recipe reaches 0.95: blog about 1 in 6, ours 0.19 (deviation 14%, pass); the blog's value lies inside our family range 0 to 0.414, so one 16-task family like the blog's can show it.

Blog values outside the 5% to 95% band of our single-unit distribution:
- Recursive (3 layers) over standard g50 at N = 64: blog 1.2 sits at the 0.0% point of our families (range 1.22 to 1.28).
The blog states the 64-agent ratio of recursive to standard g50 with one decimal (1.2) and the 16-agent ratio with two (1.04).

Where the blog's single family sits among ours: Standard swarm@32 finishes every step (t / T1) at 83%; Standard swarm@64 finishes every step (t / T1) at 86%; Standard swarm finish time, 64 over 32 agents at 79%; Standard swarm@64 speedup at half coverage, g50 at 82%; Standard swarm@64 speedup at best score 0.8 at 17%; Standard swarm@64, lambda at 80%. Within a family, g50 and the finish time at 64 agents are negatively correlated (r = -0.44), and 1.2% of our families have both g50 of at least 32.5 and a finish time of at least 0.095 (the values that round to the blog's 33 and 0.10). The blog gives the finish time only as 'about 0.10', read off figures whose time axis is linear from 0 to 1 T1. Cause unidentified; no parameter was changed in response.

## Figure

`outputs/figures/swarmsim_coverage.pdf`: average coverage against time in units of T1 (log axis) over 4096 tasks, each family on its own T1. Panel a is the standard swarm, panel b the recursive swarm with 3 layers; the dashed line is one agent and darker lines are larger swarms (4, 16, 32, 64 agents). The dotted line marks half coverage, where g50 is read.

## Outputs and command

- `outputs/tables/swarmsim_reproduction.csv`
- `outputs/tables/swarmsim_scaling.csv`
- `outputs/figures/swarmsim_coverage.pdf`
- `outputs/qa/swarmsim_d1.md`
- `data/interim/swarmsim_family_stats.parquet`
- `outputs/figures/swarmsim_coverage.png`

Command: `python scripts/swarmsim_reproduce.py` (Slurm: `sbatch scripts/swarmsim_reproduce.sbatch`). Library: `avsd.swarmsim.run_reproduction(load_config())`.
Python 3.11.16, numpy 2.4.6.
