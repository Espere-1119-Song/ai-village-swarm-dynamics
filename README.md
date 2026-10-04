# avsd: swarm dynamics in the AI Village logs

`avsd` turns the logs of the AI Village (AI Digest, 2026) into one unified event table and runs five analyses on it.

| Analysis | Question | Method |
|---|---|---|
| Excitation model | Who triggers whom in the chat | Multivariate Hawkes process with class-shared kernels and presence masks |
| Memory retention | How fact units survive the memory that agents rewrite for themselves | Discrete hazards per consolidation, beta-geometric and beta-discrete-Weibull models |
| Transmission trees | How serial intervals and content change across generations of transmission between agents | Transmission trees with exposure constraints, MAP and posterior forests |
| Change points | Which behavioural shifts coincide with documented scaffolding changes | PELT and BOCPD change points aligned with the CHANGELOG |
| Simulator and dependency graphs | Whether a generative model of swarm work matches real agent work | Simulator of task DAGs and agent swarms, dependency graphs of computer-use sessions |

A one-page summary of the project and its findings is in `reports/project_summary.md`. The full write-up is in `reports/writeup.md`. `python scripts/writeup_figures.py` draws its figures from the aggregate tables, and `python scripts/writeup_pdf.py` typesets it as `reports/writeup.pdf`. The results browser is online at https://espere-1119-song.github.io/ai-village-swarm-dynamics/reports/, and `avsd report` builds a self-contained interactive page of every figure and table in `reports/index.html`. `SPEC.md` holds the plan, `docs/decisions.md` every analysis decision.

A demo video of 1 min 54 s with an English voice-over is `reports/demo.mp4`. `scripts/demo_video/build_video.sh` renders it from the aggregate tables: `scenes.html` draws each frame, headless Chrome captures the frames, `narration.py` speaks the script with the Kokoro TTS model and ffmpeg encodes both.

## Install

Python 3.11 with [uv](https://github.com/astral-sh/uv):

```bash
uv venv --python 3.11 .venv
source .venv/bin/activate
uv pip install -e ".[dev]"
python -m spacy download en_core_web_sm
```

The optional extras `embed` and `ethogram` are only needed for a screenshot analysis that this release does not include.

## Data

The dataset is gated on Hugging Face. Request access at https://huggingface.co/datasets/aidigestorg/ai-village and export a token as `HF_TOKEN`. `configs/default.yaml` pins revision `838b4150303ca8228e8edb432d8b8ccae353d258` (export of 2026-09-20), and every number in the write-up refers to it. The files without screenshots take 5.8 GB, and the 171 GB of screenshots are not needed.

Terms that every step follows (SPEC 0.2):

- The data serve research and analysis only. No AI system may be trained or fine-tuned on them without written permission from AI Digest, and every model in this toolkit runs inference only.
- No attempt is made to identify any person. Human speakers appear only as `human`, and no output carries names, emails, phone numbers or account names.
- Credentials that survived the dataset's scrubbing are recorded by location, reported to AI Digest and never used.
- Raw data, message text, labels and intermediate parquet files stay under `data/`, which `.gitignore` excludes. `outputs/` holds aggregates only.

## Usage

Every command reads `configs/default.yaml`, or another file given with `--config`. The project seed is 20261003. The runtimes below come from the QA reports of the published run on a Slurm cluster, and `scripts/*.sbatch` holds the matching job scripts.

| Step | Command | Writes | Runtime |
|---|---|---|---|
| Ingest | `avsd ingest` | `data/raw/`, `data/processed/tables/`, `outputs/qa/ingest.md` | about 5 min |
| Event table | `avsd build-events` | `data/processed/events_unified.parquet`, run periods, roster, rooms, CHANGELOG, `outputs/qa/build_events.md` | 55 s |
| Excitation model, goal windows | `avsd hawkes fit --window goal` | `outputs/tables/hawkes_*.csv`, F1, F2, `outputs/qa/hawkes.md` | about 1 h on 12 parallel 16-core jobs (`scripts/hawkes_submit.py`), mostly the bootstrap |
| Excitation model, rolling windows | `avsd hawkes fit --window rolling` | `outputs/tables/hawkes_rolling.parquet` for change-point detection | under 1 min |
| Memory retention | `avsd lineage memory`, then `python -m avsd.lineage.memory --rules v2` and `--rules v3`, then `python scripts/b1_post_switch_rise.py` | `outputs/tables/memory_*` (the default run gives anchor match, `--rules v2` literal match, the main rule, in the `_v2` files, and `--rules v3` context match), F6, `outputs/qa/lineage_memory*.md` | 26 min for the first extraction, then 11 to 32 min per rule set, and about 1 min for the paired test |
| Transmission trees | `avsd lineage trees --units --gamma composite` | `outputs/tables/trees_*`, F3, F4, `outputs/qa/lineage_trees.md` | about 24 min for the units on 48 CPUs, then 26 min |
| Change points | `avsd changepoint` | `outputs/tables/changepoint*.csv`, F5, `outputs/qa/changepoint.md` | 144 s |
| Simulator reproduction | `avsd swarmsim reproduce` | `outputs/tables/swarmsim_*`, `outputs/qa/swarmsim_d1.md` | 77 s |
| Dependency graphs | `avsd swarmsim calibrate`, and `--rules v1` for the sensitivity version, then `python scripts/depgraph_example.py` for the example graph of the write-up | `outputs/tables/depgraph_*`, F7, `outputs/qa/swarmsim_d2_d4.md` | about 5 min, 2 min with cached touches |
| Monitor validation | `python -m avsd.validate.monitor_hawkes` | `outputs/tables/monitor_v*.csv`, `outputs/qa/monitor_validation.md` | 14 s |
| Report | `avsd report` | `reports/index.html` | 78 s |

Change-point detection reads the outputs of the excitation model, the memory step and the monitor findings, and the transmission trees read the excitation-model kernels, so run them in the order above. The monitor findings are fetched once from the public AI Digest monitor with `avsd.validate.monitor.run_monitor_ingest`, which takes about 22 minutes at one request per 1.5 s.

Useful options:

- `avsd hawkes fit --stage accept|boot|matched|sens|valid|rolling|assemble` runs one stage, so the stages can be spread over jobs.
- `avsd lineage trees --rules v1|v2|v3 --env-rule precede|any --exposure main|ever|all --hawkes auto|on|off --gamma tier1|hand|composite|<number>` sets the memory presence rule (v1, v2 and v3 are anchor, literal and context match), the independent-observation rule, the exposure rule, the time term and γ. The published run uses `--gamma composite`, which chooses the time term and γ on the private label sheets. Without them, `--hawkes off --gamma 0.25` gives the same posterior.
- `avsd swarmsim calibrate --force-extract` re-extracts the artifact touches.

## Label validation

The fact units of B1 and the parents of B2 are checked against blind labels. Claude labelled every row of the blind sheets, and the project owner labelled a stratified random audit sample (`data/labels/audit_sample.json`) as the reference. Metrics weight the audit rows by their inclusion probabilities.

```bash
python scripts/blind_labels.py make                                  # blind sheets in data/labels/
python scripts/blind_fulltext.py                                     # masked full memory texts for the page
python scripts/blind_labels.py merge                                 # owner's labels back into the review sheets
python -m avsd.lineage.prelabel import-claude                        # Claude's B1 labels
python -m avsd.lineage.prelabel_parents claude                       # Claude's B2 labels
python -m avsd.lineage.prelabel metrics                              # precision and recall of anchor, literal and context match
python -m avsd.lineage.prelabel_parents metrics                      # accuracy of the B2 parent posterior
avsd lineage trees --gamma composite                                 # rerun B2 with γ and the time term chosen on the labels
```

The labelling page embeds personal data from the logs. Keep it on the labeller's machine and never publish it.

## Outputs

- `outputs/tables/`: aggregate tables, one family per analysis (`hawkes_*`, `memory_*`, `trees_*`, `changepoint*`, `swarmsim_*`, `depgraph_*`, `monitor_*`), plus `writeup_cis.csv` with the intervals quoted in the write-up.
- `outputs/figures/`: F1 excitation matrices, F2 activity shares, F3 serial intervals by generation, F4 time to generation k, F5 change-point timeline, F6 memory retention, F7 dependency-graph statistics against the generator.
- `outputs/qa/`: one QA report per step, with inputs, checks, acceptance items and runtimes.
- `reports/index.html` and `reports/writeup.md`.


`reports/findings_zh.md` (and the self-contained `reports/findings_zh.html`) explains the main findings in plain Chinese for readers outside the field. `python scripts/explainer_figures.py` draws its figures from `outputs/tables/` (it needs a CJK font, so run it on a machine that has one), and `python scripts/explainer_html.py` builds the HTML page.

## Tests

```bash
pytest
```

The suite covers every analysis, including synthetic recovery of the Hawkes estimator. The Hawkes tests take about 4 minutes.

## License

The code is released under the MIT License, see `LICENSE`. The aggregate outputs in `outputs/` and `reports/` derive from the AI Village dataset and remain subject to its research terms, so they may not be used to train or fine-tune AI systems without written permission from AI Digest.

## Citation

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village (Hugging Face `aidigestorg/ai-village`, revision 838b4150).

Authors: Enxin Song and Wenhao Chai. We thank AI Digest for the data and the public monitor findings.
