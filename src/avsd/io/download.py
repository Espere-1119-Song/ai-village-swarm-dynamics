"""Download the non-screenshot part of the AI Village dataset (SPEC 2.4).

Data: AI Digest, "AI Village dataset", 2026, https://theaidigest.org/village
"""

from __future__ import annotations

import os
from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download


def download_tables(cfg: dict) -> Path:
    if not os.environ.get("HF_TOKEN"):
        from huggingface_hub import get_token

        if not get_token():
            raise RuntimeError("No Hugging Face token. Set HF_TOKEN or run `hf auth login`.")
    ds = cfg["dataset"]
    root = snapshot_download(
        repo_id=ds["repo_id"],
        repo_type=ds["repo_type"],
        revision=ds["revision"],
        local_dir=str(cfg["paths"]["raw"]),
        allow_patterns=ds["allow_patterns"],
    )
    return Path(root)


def fetch_screenshot_day(cfg: dict, day: str) -> Path:
    """One Pacific-time day of screenshots. Check the size budget before calling."""
    ds = cfg["dataset"]
    return Path(
        hf_hub_download(
            ds["repo_id"],
            f"images/computer-use-turns/{day}.tar",
            repo_type=ds["repo_type"],
            revision=ds["revision"],
            local_dir=str(cfg["paths"]["raw"]),
        )
    )
