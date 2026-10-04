"""Module C: change points in behavioural series and their alignment with the CHANGELOG (SPEC 7).

`run_changepoint(cfg)` runs the module end to end (pipeline.py). The parts are importable on their
own: series.py (series per run day), lexical.py (question flags and family words), detect.py (PELT,
penalties, block bootstrap), bocpd.py (Bayesian online change point detection), align.py (alignment
statistic and its nulls), documented.py (village goal transitions and agent goal changes),
monitor.py (AI Village LLM monitor findings as series, entries and annotations), refsets.py (the
entry sets, the window sweep and per change point flags) and figure.py (F5).

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from avsd.changepoint.pipeline import run_changepoint

__all__ = ["run_changepoint"]
