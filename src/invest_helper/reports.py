"""Save analysis reports as timestamped markdown files."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re

DEFAULT_REPORTS_DIR = Path("reports")
_UNSAFE = re.compile(r"[^\w\-]+", re.UNICODE)


def slugify(text: str, max_len: int = 48) -> str:
    slug = _UNSAFE.sub("-", text.strip()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug or "report"


def report_filename(prompt: str, when: datetime | None = None) -> str:
    stamp = (when or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
    return f"{stamp}_{slugify(prompt)}.md"


def unique_path(directory: Path, name: str) -> Path:
    candidate = directory / name
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for index in range(2, 100):
        alt = directory / f"{stem}_{index}{suffix}"
        if not alt.exists():
            return alt
    raise FileExistsError(f"Too many reports with prefix {stem}")


def build_report_markdown(
    *,
    prompt: str,
    snapshot_md: str,
    recommendations: str | None,
    created: datetime | None = None,
) -> str:
    created = created or datetime.now()
    lines = [
        f"# {prompt.strip() or 'Отчёт'}",
        "",
        f"- Дата: {created.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Запрос: {prompt.strip()}",
        "",
        snapshot_md.strip(),
        "",
    ]
    if recommendations is not None:
        lines.extend(["## Рекомендации", "", recommendations.strip(), ""])
    else:
        lines.extend(["## Рекомендации", "", "_--dry-run: модель не вызывалась._", ""])
    return "\n".join(lines).rstrip() + "\n"


def save_report(
    content: str,
    *,
    prompt: str,
    reports_dir: Path | str = DEFAULT_REPORTS_DIR,
    created: datetime | None = None,
) -> Path:
    directory = Path(reports_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = unique_path(directory, report_filename(prompt, created))
    path.write_text(content, encoding="utf-8")
    return path
