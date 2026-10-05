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


def build_snapshot(
    portfolio: Portfolio,
    quotes: dict[str, Quote],
    *,
    missing_quotes: list[str] | None = None,
) -> PortfolioSnapshot:
    positions: list[PositionSnapshot] = []
    positions_value = 0.0
    total_cost = 0.0
    value_by_ticker: dict[str, float] = {}

    for position in portfolio.positions:
        quote = quotes.get(position.ticker)
        if quote is None:
            continue

        cost = position.quantity * position.avg_price
        value = position.quantity * quote.last_price
        pnl = value - cost
        pnl_pct = (pnl / cost * 100.0) if cost > 0 else None
        lots = (
            (position.quantity / quote.lot_size)
            if quote.lot_size and quote.lot_size > 0
            else None
        )

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
                short_name=quote.short_name,
                sec_name=quote.sec_name,
                isin=quote.isin,
                prev_price=quote.prev_price,
                open_price=quote.open_price,
                high_price=quote.high_price,
                low_price=quote.low_price,
                day_change_pct=quote.day_change_pct,
                day_range_pos_pct=_range_pos(
                    quote.last_price, quote.low_price, quote.high_price
                ),
                volume_today=quote.volume_today,
                value_today=quote.value_today,
                num_trades=quote.num_trades,
                bid=quote.bid,
                offer=quote.offer,
                spread=quote.spread,
                market_cap=quote.market_cap,
                lot_size=quote.lot_size,
                lots=lots,
                list_level=quote.list_level,
                trading_status=quote.trading_status,
                update_time=quote.update_time,
                return_1w_pct=quote.return_1w_pct,
                return_1m_pct=quote.return_1m_pct,
                return_3m_pct=quote.return_3m_pct,
                return_1y_pct=quote.return_1y_pct,
                high_52w=quote.high_52w,
                low_52w=quote.low_52w,
                range_52w_pos_pct=_range_pos(
                    quote.last_price, quote.low_52w, quote.high_52w
                ),
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
    _apply_class_weights(positions, classes)

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
        missing_quotes=list(missing_quotes or []),
    )


def _range_pos(last: float | None, low: float | None, high: float | None) -> float | None:
    if last is None or low is None or high is None:
        return None
    span = high - low
    if span <= 0:
        return None
    return (last - low) / span * 100.0


def _apply_class_weights(positions: list[PositionSnapshot], classes: list[ClassSnapshot]) -> None:
    by_ticker: dict[str, ClassSnapshot] = {}
    for item in classes:
        for ticker in item.tickers:
            by_ticker[ticker] = item
    for position in positions:
        owner = by_ticker.get(position.ticker)
        if owner is None:
            continue
        position.class_name = owner.name
        if owner.value > 0:
            position.weight_in_class = position.value / owner.value * 100.0


def _cash_outside(snapshot: PortfolioSnapshot) -> bool:
    return any(item.ticker == "Кэш" for item in snapshot.reference)


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
    # Free cash is not an investment. It leaves the class base unless a class claims it.
    cash_in_class = any(item.include_cash for item in allocation.classes)
    if not cash_in_class:
        allocation_base = max(allocation_base - cash, 0.0)

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
    if not cash_in_class and cash > 0:
        reference.insert(
            0,
            ReferenceSnapshot(
                ticker="Кэш",
                value=cash,
                weight_total=_weight(cash, total_value),
            ),
        )

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


def _fmt_num(value: float | None, spec: str = ",.2f", *, signed: bool = False) -> str:
    if value is None:
        return "—"
    if signed:
        return format(value, f"+{spec}")
    return format(value, spec)


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
        "| Тикер | Имя | Board | Кол-во | Ср. цена | Last | День % | Стоимость | P&L | Доля % |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for p in snapshot.positions:
        pnl_cell = f"{p.pnl:,.2f}"
        if p.pnl_pct is not None:
            pnl_cell += f" ({p.pnl_pct:+.2f}%)"
        name = p.short_name or "—"
        lines.append(
            f"| {p.ticker} | {name} | {p.board} | {p.quantity:g} | {p.avg_price:,.4f} "
            f"| {p.last_price:,.4f} | {_fmt_num(p.day_change_pct, '.2f', signed=True)} "
            f"| {p.value:,.2f} | {pnl_cell} | {p.weight:.2f} |"
        )

    lines.extend(
        [
            "",
            "## Рынок позиций",
            "",
            "День % и OHLC — сегодняшняя сессия MOEX. 1н/1м/3м/1г и 52н — "
            "по дневным свечам ISS. Капитализация — ISSUECAPITALIZATION. "
            "МСФО, мультипликаторы и дивиденды в снимке отсутствуют.",
            "",
            "| Тикер | Класс | Доля класса % | Open | High | Low | В дне % | "
            "Оборот ₽ | Спред | Капит. | 1н % | 1м % | 3м % | 1г % | "
            "52н min | 52н max | В 52н % |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | "
            "---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for p in snapshot.positions:
        lines.append(
            f"| {p.ticker} | {p.class_name or '—'} | {_fmt_num(p.weight_in_class)} "
            f"| {_fmt_num(p.open_price, ',.4f')} | {_fmt_num(p.high_price, ',.4f')} "
            f"| {_fmt_num(p.low_price, ',.4f')} | {_fmt_num(p.day_range_pos_pct)} "
            f"| {_fmt_num(p.value_today, ',.0f')} | {_fmt_num(p.spread, ',.4f')} "
            f"| {_fmt_num(p.market_cap, ',.0f')} "
            f"| {_fmt_num(p.return_1w_pct, '.2f', signed=True)} "
            f"| {_fmt_num(p.return_1m_pct, '.2f', signed=True)} "
            f"| {_fmt_num(p.return_3m_pct, '.2f', signed=True)} "
            f"| {_fmt_num(p.return_1y_pct, '.2f', signed=True)} "
            f"| {_fmt_num(p.low_52w, ',.4f')} | {_fmt_num(p.high_52w, ',.4f')} "
            f"| {_fmt_num(p.range_52w_pos_pct)} |"
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
                f"База классов = итого − allocation.exclude"
                f"{' − свободный кэш' if _cash_outside(snapshot) else ''} "
                f"(**{snapshot.allocation_base:,.2f}**). "
                "Свободный кэш — ещё не вложенная сумма, не класс «Деньги». "
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

    if snapshot.missing_quotes:
        lines.extend(
            [
                "",
                "## Нет котировки MOEX",
                "",
                "Эти позиции есть в файле, но в итог и доли не входят: "
                "на Мосбирже нет цены.",
                "",
            ]
        )
        lines.extend(f"- {ticker}" for ticker in snapshot.missing_quotes)

    lines.extend(
        [
            "",
            "## Как читать цифры",
            "",
            "Краткие определения для снимка. Это не оценка «покупать/продавать» "
            "и не вывод о здоровье бизнеса.",
            "",
            "- **Ср. цена** — ваша средняя цена покупки, не цена рынка.",
            "- **Last** — последняя сделка на Мосбирже.",
            "- **P&L** — сколько вы в плюсе или минусе относительно своей средней, "
            "а не относительно вчера или прошлого года.",
            "- **Доля %** в таблице позиций — кусок всего капитала, включая TPAY. "
            "**Доля класса %** — кусок только своего класса (акции / золото / деньги).",
            "- **День %** — ход цены сегодня к вчерашнему закрытию. Один день — шум.",
            "- **Open / High / Low** — открытие, максимум и минимум сегодняшней сессии.",
            "- **В дне %** — где last между сегодняшним low и high "
            "(0% у минимума дня, 100% у максимума).",
            "- **1н / 1м / 3м / 1г %** — ход бумаги за период по дневным свечам, "
            "не доходность вашего лота (лот смотри в P&L).",
            "- **52н min/max** — минимум и максимум цены примерно за год. "
            "**В 52н %** — где last в этом коридоре. Это не «дешёвая/дорогая компания».",
            "- **Оборот и спред** — насколько бумага торгуется и насколько "
            "широкая щель между покупкой и продажей. Узкий спред и большой оборот — "
            "проще выйти; это не сигнал сделки.",
            "- **Капит.** — оценка стоимости всей компании (капитализация выпуска). "
            "У БПИФ часто пусто — так и должно быть.",
            "- Пустые 3м/1г у фондов — мало истории на бирже, не ошибка.",
            "- В снимке нет МСФО, прибыли, долга, дивидендов и новостей.",
        ]
    )

    return "\n".join(lines)
