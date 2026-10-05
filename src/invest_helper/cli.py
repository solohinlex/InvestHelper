"""Typer CLI entrypoints."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from invest_helper import __version__
from invest_helper.analytics import build_snapshot, format_snapshot_markdown
from invest_helper.config import get_settings
from invest_helper.llm import generate_recommendations
from invest_helper.moex import MoexClient, MoexError
from invest_helper.portfolio import load_portfolio
from invest_helper.prompts import format_prompt_files, resolve_prompt_files
from invest_helper.reports import DEFAULT_REPORTS_DIR, build_report_markdown, save_report
from invest_helper.tinvest import TinvestError, sync_holdings

app = typer.Typer(
    name="invest-helper",
    help="Анализ российского портфеля (MOEX) + рекомендации через OpenAI-compatible LLM.",
    no_args_is_help=True,
)
console = Console()
err_console = Console(stderr=True)


@app.callback()
def main() -> None:
    """InvestHelper CLI."""


@app.command("analyze")
def analyze(
    portfolio: Path = typer.Option(
        ...,
        "--portfolio",
        "-p",
        exists=True,
        dir_okay=False,
        readable=True,
        help="Путь к portfolio.yaml / .json",
    ),
    prompt: str = typer.Option(
        ...,
        "--prompt",
        "-m",
        help="Текстовый запрос к модели (рекомендации)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Сохранить снимок портфеля без вызова LLM",
    ),
    system_prompt: Path | None = typer.Option(
        None,
        "--system-prompt",
        "-s",
        exists=True,
        dir_okay=True,
        file_okay=True,
        readable=True,
        help="Файл или каталог промптов. По умолчанию все .md/.txt из prompts/",
    ),
    reports_dir: Path = typer.Option(
        DEFAULT_REPORTS_DIR,
        "--reports-dir",
        "-o",
        file_okay=False,
        help="Каталог для markdown-отчётов",
    ),
) -> None:
    """Загрузить портфель, подтянуть котировки MOEX и получить рекомендации."""
    settings = get_settings()

    try:
        loaded = load_portfolio(portfolio)
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        err_console.print(f"[red]Ошибка портфеля:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if not loaded.positions and loaded.cash <= 0:
        err_console.print("[red]Портфель пуст: нет позиций и кэша.[/red]")
        raise typer.Exit(code=1)

    try:
        with MoexClient(timeout=settings.moex_timeout_seconds) as moex:
            quotes = moex.fetch_quotes(loaded.positions) if loaded.positions else {}
        snapshot = build_snapshot(loaded, quotes)
    except MoexError as exc:
        err_console.print(f"[red]MOEX:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except Exception as exc:  # noqa: BLE001
        err_console.print(f"[red]Ошибка котировок:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    snapshot_md = format_snapshot_markdown(snapshot)
    recommendations: str | None = None

    if dry_run:
        console.print("[dim]--dry-run: LLM не вызывался[/dim]")
    else:
        console.print("[dim]Снимок готов, запрос к модели…[/dim]")
        try:
            recommendations = generate_recommendations(
                settings,
                prompt,
                snapshot,
                system_prompt_path=system_prompt,
            )
        except Exception as exc:  # noqa: BLE001
            err_console.print(f"[red]LLM:[/red] {exc}")
            raise typer.Exit(code=1) from exc

    report_md = build_report_markdown(
        prompt=prompt,
        snapshot_md=snapshot_md,
        recommendations=recommendations,
    )
    try:
        saved = save_report(report_md, prompt=prompt, reports_dir=reports_dir)
    except OSError as exc:
        err_console.print(f"[red]Не удалось сохранить отчёт:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"Отчёт сохранён: [bold]{saved}[/bold]")


@app.command("doctor")
def doctor() -> None:
    """Проверить версию, .env и доступность MOEX ISS."""
    settings = get_settings()

    table = Table(title="InvestHelper doctor")
    table.add_column("Проверка")
    table.add_column("Статус")

    table.add_row("Версия", __version__)
    table.add_row(
        "OPENAI_API_KEY",
        "задан" if settings.openai_api_key.strip() else "[yellow]не задан[/yellow]",
    )
    table.add_row("OPENAI_BASE_URL", settings.openai_base_url or "—")
    table.add_row(
        "OPENAI_MODEL",
        settings.openai_model or "[yellow]не задан[/yellow]",
    )
    table.add_row(
        "LLM готов",
        "[green]да[/green]" if settings.llm_configured() else "[yellow]нет[/yellow]",
    )

    try:
        prompt_files = resolve_prompt_files(settings.system_prompt_path.strip() or None)
        prompt_status = f"[green]ok[/green] ({format_prompt_files(prompt_files)})"
    except Exception as exc:  # noqa: BLE001
        prompt_status = f"[red]ошибка[/red] ({exc})"
    table.add_row("System prompt", prompt_status)

    moex_status = "[green]ok[/green]"
    try:
        with MoexClient(timeout=settings.moex_timeout_seconds) as moex:
            quote = moex.fetch_quote("SBER", "TQBR")
        moex_status = f"[green]ok[/green] (SBER={quote.last_price})"
    except Exception as exc:  # noqa: BLE001
        moex_status = f"[red]ошибка[/red] ({exc})"

    table.add_row("MOEX ISS", moex_status)
    console.print(table)


@app.command("sync")
def sync(
    portfolio: Path = typer.Option(
        Path("portfolio.yaml"),
        "--portfolio",
        "-p",
        exists=True,
        dir_okay=False,
        readable=True,
        writable=True,
        help="Файл портфеля: обновить cash и positions со счёта Т-Инвестиций",
    ),
) -> None:
    """Записать в файл портфеля фактические деньги и позиции со счёта Т-Инвестиций."""
    settings = get_settings()
    try:
        result = sync_holdings(
            portfolio,
            token=settings.tinvest_token,
            url=settings.tinvest_mcp_url,
            timeout=settings.tinvest_timeout_seconds,
        )
    except TinvestError as exc:
        err_console.print(f"[red]T-Invest:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"Счета ({len(result.account_ids)}): [bold]{', '.join(result.account_ids)}[/bold]"
    )
    console.print(f"Кэш: {result.cash:g} ₽")
    if result.tickers:
        console.print(f"Позиции ({len(result.tickers)}): {', '.join(result.tickers)}")
    else:
        console.print("Позиции: нет")
    if result.skipped:
        console.print("Пропущено: " + "; ".join(result.skipped))
    console.print(f"Файл обновлён: [bold]{portfolio}[/bold]")


def run() -> None:
    app()


if __name__ == "__main__":
    run()
