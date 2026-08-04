"""Deterministic portfolio analytics before LLM."""

from __future__ import annotations

from invest_helper.models import (
    Portfolio,
    PortfolioSnapshot,
    PositionSnapshot,
    Quote,
)


def build_snapshot(portfolio: Portfolio, quotes: dict[str, Quote]) -> PortfolioSnapshot:
    positions: list[PositionSnapshot] = []
    positions_value = 0.0
    total_cost = 0.0

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

    total_value = positions_value + portfolio.cash
    for item in positions:
        item.weight = (item.value / total_value * 100.0) if total_value > 0 else 0.0

    total_pnl = positions_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100.0) if total_cost > 0 else None

    ranked = sorted(positions, key=lambda p: p.weight, reverse=True)
    top_concentration = [(p.ticker, round(p.weight, 2)) for p in ranked[:5]]

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
    )


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

    return "\n".join(lines)
