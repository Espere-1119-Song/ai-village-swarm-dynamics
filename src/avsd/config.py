"""Load configs/default.yaml and resolve paths against the repo root."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "configs" / "default.yaml"


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg_path = Path(path) if path else DEFAULT_CONFIG
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    cfg["paths"] = {k: (REPO_ROOT / v).resolve() for k, v in cfg["paths"].items()}
    return cfg
