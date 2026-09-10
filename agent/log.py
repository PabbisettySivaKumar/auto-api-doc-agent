"""Trajectory logging (PRD section 5.8).

Every agent run appends one JSON line capturing the full trajectory:
input diff -> detected changes -> reasoning/draft -> output. This is the
minimal eval substrate; a SQLite table or LangSmith/Langfuse can be added
later behind the same `log_run` call.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any


def _serialize(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _serialize(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [_serialize(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    return obj


def log_run(output_dir: str, record: dict[str, Any]) -> str:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    log_path = out / "trajectories.jsonl"

    entry = {"ts": time.time(), "iso": time.strftime("%Y-%m-%dT%H:%M:%S"), **record}
    with log_path.open("a") as f:
        f.write(json.dumps(_serialize(entry)) + "\n")
    return str(log_path)
