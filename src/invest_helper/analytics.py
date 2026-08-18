"""Deterministic portfolio analytics before LLM."""

from __future__ import annotations

from invest_helper.models import (
    Allocation,
    ClassSnapshot,
    Portfolio,
    PortfolioSnapshot,
    PositionSnapshot,
    Quote,
    ReferenceSnapshot,
)


def build_snapshot(portfolio: Portfolio, quotes: dict[str, Quote]) -> PortfolioSnapshot:
    positions: list[PositionSnapshot] = []
    positions_value = 0.0
    total_cost = 0.0
    value_by_ticker: dict[str, float] = {}

    for position in portfolio.positions:
        quote = quotes.get(position.ticker)
        if quote is None:
            raise KeyError(f"Missing quote for {position.ticker}")

        cost = position.quantity * position.avg_price
        value = position.quantity * quote.last_price
        pnl = value - cost
        pnl_pct = (pnl / cost * 100.0) if cost > 0 else None

        positions.append(
            PositionSnapshot(
                ticker=position.ticker,
                board=quote.board,
                quantity=position.quantity,
                avg_price=position.avg_price,
                last_price=quote.last_price,
                value=value,
                cost=cost,
                pnl=pnl,
                pnl_pct=pnl_pct,
                weight=0.0,
            )
        )
        positions_value += value
        total_cost += cost
        value_by_ticker[position.ticker] = value_by_ticker.get(position.ticker, 0.0) + value

    total_value = positions_value + portfolio.cash
    for item in positions:
        item.weight = (item.value / total_value * 100.0) if total_value > 0 else 0.0

    total_pnl = positions_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100.0) if total_cost > 0 else None

    ranked = sorted(positions, key=lambda p: p.weight, reverse=True)
    top_concentration = [(p.ticker, round(p.weight, 2)) for p in ranked[:5]]

    allocation_base, classes, reference, unmapped = _build_allocation(
        portfolio.allocation,
        value_by_ticker,
        cash=portfolio.cash,
        total_value=total_value,
    )

    return PortfolioSnapshot(
        currency=portfolio.currency,
        cash=portfolio.cash,
        positions_value=positions_value,
        total_value=total_value,
        total_cost=total_cost,
        total_pnl=total_pnl,
        total_pnl_pct=total_pnl_pct,
        positions=positions,
        top_concentration=top_concentration,
        allocation_base=allocation_base,
        classes=classes,
        reference=reference,
        unmapped=unmapped,
    )


def _weight(part: float, whole: float) -> float:
    return (part / whole * 100.0) if whole > 0 else 0.0


def _build_allocation(
    allocation: Allocation | None,
    value_by_ticker: dict[str, float],
    *,
    cash: float,
    total_value: float,
) -> tuple[float | None, list[ClassSnapshot], list[ReferenceSnapshot], list[ReferenceSnapshot]]:
    if allocation is None or not allocation.classes:
        return None, [], [], []

    exclude = set(allocation.exclude)
    assigned: set[str] = set()
    classes: list[ClassSnapshot] = []

    excluded_value = sum(value_by_ticker.get(ticker, 0.0) for ticker in exclude)
    allocation_base = max(total_value - excluded_value, 0.0)

    for item in allocation.classes:
        value = sum(value_by_ticker.get(ticker, 0.0) for ticker in item.tickers)
        if item.include_cash:
            value += cash
        assigned.update(item.tickers)
        weight = _weight(value, allocation_base)
        target = item.target_pct
        deviation = (weight - target) if target is not None else None
        classes.append(
            ClassSnapshot(
                name=item.name,
                value=value,
                weight=weight,
                target_pct=target,
                deviation_pp=deviation,
                tickers=list(item.tickers),
            )
        )

    reference = [
        ReferenceSnapshot(
            ticker=ticker,
            value=value_by_ticker.get(ticker, 0.0),
            weight_total=_weight(value_by_ticker.get(ticker, 0.0), total_value),
        )
        for ticker in allocation.exclude
        if value_by_ticker.get(ticker, 0.0) > 0
    ]

    unmapped: list[ReferenceSnapshot] = []
    for ticker, value in value_by_ticker.items():
        if ticker in exclude or ticker in assigned:
            continue
        unmapped.append(
            ReferenceSnapshot(
                ticker=ticker,
                value=value,
                weight_total=_weight(value, total_value),
            )
        )

    return allocation_base, classes, reference, unmapped


def format_snapshot_markdown(snapshot: PortfolioSnapshot) -> str:
    lines = [
        f"# Снимок портфеля ({snapshot.currency})",
        "",
        f"- Стоимость позиций: **{snapshot.positions_value:,.2f}**",
        f"- Кэш: **{snapshot.cash:,.2f}**",
        f"- Итого: **{snapshot.total_value:,.2f}**",
        f"- Себестоимость позиций: **{snapshot.total_cost:,.2f}**",
        f"- P&L: **{snapshot.total_pnl:,.2f}**"
        + (
            f" ({snapshot.total_pnl_pct:+.2f}%)"
            if snapshot.total_pnl_pct is not None
            else ""
        ),
        "",
        "## Позиции",
        "",
        "| Тикер | Board | Кол-во | Ср. цена | Last | Стоимость | P&L | Доля % |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for p in snapshot.positions:
        pnl_cell = f"{p.pnl:,.2f}"
        if p.pnl_pct is not None:
            pnl_cell += f" ({p.pnl_pct:+.2f}%)"
        lines.append(
            f"| {p.ticker} | {p.board} | {p.quantity:g} | {p.avg_price:,.4f} "
            f"| {p.last_price:,.4f} | {p.value:,.2f} | {pnl_cell} | {p.weight:.2f} |"
        )

    lines.extend(["", "## Концентрация (топ)", ""])
    for ticker, weight in snapshot.top_concentration:
        lines.append(f"- {ticker}: {weight:.2f}%")

    if snapshot.classes and snapshot.allocation_base is not None:
        lines.extend(
            [
                "",
                "## Классы активного портфеля",
                "",
                f"База классов = итого − бумаги из allocation.exclude "
                f"(**{snapshot.allocation_base:,.2f}**). "
                "Доли классов считай только от этой базы, не от всего портфеля.",
                "",
                "| Класс | Стоимость | Доля от активного % | Цель % | Откл. п.п. |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for item in snapshot.classes:
            target = f"{item.target_pct:g}" if item.target_pct is not None else "—"
            deviation = (
                f"{item.deviation_pp:+.2f}" if item.deviation_pp is not None else "—"
            )
            lines.append(
                f"| {item.name} | {item.value:,.2f} | {item.weight:.2f} "
                f"| {target} | {deviation} |"
            )

        if snapshot.reference:
            lines.extend(
                [
                    "",
                    "## Справочно (не в базе классов)",
                    "",
                    "| Тикер | Стоимость | Доля от всего портфеля % |",
                    "| --- | ---: | ---: |",
                ]
            )
            for item in snapshot.reference:
                lines.append(
                    f"| {item.ticker} | {item.value:,.2f} | {item.weight_total:.2f} |"
                )

        if snapshot.unmapped:
            lines.extend(
                [
                    "",
                    "## Вне заданных классов",
                    "",
                    "| Тикер | Стоимость | Доля от всего портфеля % |",
                    "| --- | ---: | ---: |",
                ]
            )
            for item in snapshot.unmapped:
                lines.append(
                    f"| {item.ticker} | {item.value:,.2f} | {item.weight_total:.2f} |"
                )

    return "\n".join(lines)
