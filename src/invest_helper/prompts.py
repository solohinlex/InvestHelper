"""Load system prompts from markdown files."""

from __future__ import annotations

from pathlib import Path

DEFAULT_SYSTEM_PROMPT_PATH = Path("prompts/system.md")


def resolve_system_prompt_path(path: Path | str | None = None) -> Path:
    """Resolve prompt file: explicit path, cwd, then project root near the package."""
    if path is not None:
        candidate = Path(path).expanduser()
        if candidate.is_file():
            return candidate
        raise FileNotFoundError(f"System prompt file not found: {candidate}")

    cwd_candidate = Path.cwd() / DEFAULT_SYSTEM_PROMPT_PATH
    if cwd_candidate.is_file():
        return cwd_candidate

    # editable/src layout: src/invest_helper/prompts.py -> project root
    project_root = Path(__file__).resolve().parents[2]
    project_candidate = project_root / DEFAULT_SYSTEM_PROMPT_PATH
    if project_candidate.is_file():
        return project_candidate

    raise FileNotFoundError(
        "System prompt file not found. Expected prompts/system.md "
        "in the project root or pass --system-prompt / SYSTEM_PROMPT_PATH."
    )


def load_system_prompt(path: str | None = None) -> str:
    prompt_path = resolve_system_prompt_path(path)
    text = prompt_path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"System prompt file is empty: {prompt_path}")
    return text
