"""Load portfolio from YAML or JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from invest_helper.models import Portfolio, Position


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


def replace_holdings(path: Path, *, cash: float, positions: list[Position]) -> None:
    """Replace cash and positions. Keep currency, allocation, and any other keys."""
    data = _load_raw(path)
    boards = _existing_boards(data.get("positions"))
    data["cash"] = cash
    data["positions"] = [_position_row(position, boards) for position in positions]
    _dump_raw(path, data)


def _load_raw(path: Path) -> dict[str, Any]:
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
    return data


def _dump_raw(path: Path, data: dict[str, Any]) -> None:
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        text = yaml.safe_dump(
            data,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
    elif suffix == ".json":
        text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    else:
        raise ValueError(
            f"Unsupported portfolio format '{suffix}'. Use .yaml, .yml, or .json"
        )
    path.write_text(text, encoding="utf-8")


def _existing_boards(positions: object) -> dict[str, str]:
    boards: dict[str, str] = {}
    if not isinstance(positions, list):
        return boards
    for item in positions:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "").strip().upper()
        board = str(item.get("board") or "").strip().upper()
        if ticker and board:
            boards[ticker] = board
    return boards


def _position_row(position: Position, boards: dict[str, str]) -> dict[str, object]:
    row: dict[str, object] = {
        "ticker": position.ticker,
        "quantity": position.quantity,
        "avg_price": position.avg_price,
    }
    board = position.board or boards.get(position.ticker)
    if board:
        row["board"] = board
    return row
