"""Load system prompts from markdown files."""

from __future__ import annotations

from pathlib import Path

DEFAULT_PROMPTS_DIR = Path("prompts")
BASE_PROMPT_NAME = "system.md"
PROMPT_SUFFIXES = {".md", ".txt"}


def _project_root() -> Path:
    # editable/src layout: src/invest_helper/prompts.py -> project root
    return Path(__file__).resolve().parents[2]


def _prompt_directories() -> list[Path]:
    return [
        Path.cwd() / DEFAULT_PROMPTS_DIR,
        _project_root() / DEFAULT_PROMPTS_DIR,
    ]


def _list_prompt_files(directory: Path) -> list[Path]:
    files = [
        path
        for path in directory.iterdir()
        if path.is_file()
        and path.suffix.lower() in PROMPT_SUFFIXES
        and not path.name.startswith(".")
    ]
    base = directory / BASE_PROMPT_NAME
    rest = sorted(
        (path for path in files if path.name != BASE_PROMPT_NAME),
        key=lambda path: path.name.lower(),
    )
    ordered: list[Path] = []
    if base.is_file():
        ordered.append(base)
    ordered.extend(rest)
    return ordered


def resolve_prompt_files(path: Path | str | None = None) -> list[Path]:
    """Resolve prompt sources: a single file, a directory, or default prompts/."""
    if path is not None:
        candidate = Path(path).expanduser()
        if candidate.is_file():
            return [candidate]
        if candidate.is_dir():
            files = _list_prompt_files(candidate)
            if files:
                return files
            raise FileNotFoundError(
                f"No .md/.txt prompt files in directory: {candidate}"
            )
        raise FileNotFoundError(f"System prompt path not found: {candidate}")

    seen: set[Path] = set()
    for directory in _prompt_directories():
        resolved = directory.resolve() if directory.exists() else directory
        if resolved in seen or not directory.is_dir():
            continue
        seen.add(resolved)
        files = _list_prompt_files(directory)
        if files:
            return files

    raise FileNotFoundError(
        "System prompt files not found. Expected .md/.txt in prompts/ "
        "or pass --system-prompt / SYSTEM_PROMPT_PATH."
    )


def resolve_system_prompt_path(path: Path | str | None = None) -> Path:
    """Return the first resolved prompt file (kept for callers that need a path)."""
    return resolve_prompt_files(path)[0]


def format_prompt_files(files: list[Path]) -> str:
    parts: list[str] = []
    cwd = Path.cwd()
    for file in files:
        try:
            parts.append(str(file.resolve().relative_to(cwd)))
        except ValueError:
            parts.append(str(file))
    return ", ".join(parts)


def load_system_prompt(path: Path | str | None = None) -> str:
    files = resolve_prompt_files(path)
    parts: list[str] = []
    for file in files:
        text = file.read_text(encoding="utf-8").strip()
        if text:
            parts.append(text)
    if not parts:
        names = format_prompt_files(files)
        raise ValueError(f"System prompt file is empty: {names}")
    return "\n\n".join(parts)
