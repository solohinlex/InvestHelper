"""Load portfolio from YAML or JSON."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from invest_helper.models import Portfolio


def load_portfolio(path: Path) -> Portfolio:
    if not path.exists():
        raise FileNotFoundError(f"Portfolio file not found: {path}")

    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")

    if suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
    elif suffix == ".json":
        data = json.loads(text)
    else:
        raise ValueError(
            f"Unsupported portfolio format '{suffix}'. Use .yaml, .yml, or .json"
        )

    if data is None:
        raise ValueError(f"Portfolio file is empty: {path}")
    if not isinstance(data, dict):
        raise ValueError("Portfolio root must be a mapping/object")

    return Portfolio.model_validate(data)
