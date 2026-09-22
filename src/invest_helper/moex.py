"""MOEX ISS market data client."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import httpx

from invest_helper.models import Position, Quote

MOEX_ISS_BASE = "https://iss.moex.com/iss"
PREFERRED_BOARDS = ("TQBR", "TQTF", "TQOB", "TQCB", "TQPI", "SPEQ")
BOND_BOARDS = {"TQOB", "TQCB", "TQIR"}
CANDLE_LOOKBACK_DAYS = 370


class MoexError(RuntimeError):
    """Raised when MOEX ISS cannot provide a usable quote."""


class MoexClient:
    def __init__(self, timeout: float = 30.0) -> None:
        self._timeout = timeout
        self._client = httpx.Client(
            base_url=MOEX_ISS_BASE,
            timeout=timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; InvestHelper/0.1; "
                    "+https://github.com/solohinlex/InvestHelper)"
                ),
                "Accept": "application/json",
            },
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> MoexClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def fetch_quotes(self, positions: list[Position]) -> dict[str, Quote]:
        quotes: dict[str, Quote] = {}
        for position in positions:
            quote = self.fetch_quote(position.ticker, position.board)
            self._apply_candle_stats(quote)
            quotes[position.ticker] = quote
        return quotes

    def fetch_quote(self, ticker: str, board: str | None = None) -> Quote:
        ticker = ticker.upper()
        if board:
            quote = self._quote_on_board(ticker, board.upper())
            if quote is not None:
                return quote
            # Explicit board may be outdated (e.g. ETF moved TQTF → TQBR)
            for candidate in self._discover_boards(ticker):
                if candidate == board.upper():
                    continue
                quote = self._quote_on_board(ticker, candidate)
                if quote is not None:
                    return quote
            raise MoexError(f"No quote for {ticker} on board {board}")

        boards = self._discover_boards(ticker)
        for candidate in boards:
            quote = self._quote_on_board(ticker, candidate)
            if quote is not None:
                return quote

        raise MoexError(f"No quote found for {ticker} on MOEX ISS")

    def _discover_boards(self, ticker: str) -> list[str]:
        payload = self._get_json(
            f"/securities/{ticker}.json",
            params={"iss.meta": "off", "iss.only": "boards"},
        )
        rows = self._table_rows(payload, "boards")
        found: list[str] = []
        for row in rows:
            is_traded = row.get("is_traded", row.get("is_trading"))
            board = row.get("boardid") or row.get("board")
            market = str(row.get("market") or "").lower()
            if not board:
                continue
            # Prefer primary cash equity/ETF boards; skip repo/mamc noise
            if market and market not in {"shares", "bonds", "index"}:
                continue
            board_id = str(board).upper()
            if is_traded in (1, True, "1") and board_id not in found:
                found.append(board_id)

        ordered: list[str] = []
        for preferred in PREFERRED_BOARDS:
            if preferred in found and preferred not in ordered:
                ordered.append(preferred)
        for board_id in found:
            if board_id not in ordered:
                ordered.append(board_id)

        if not ordered:
            ordered = list(PREFERRED_BOARDS)
        return ordered

    def _quote_on_board(self, ticker: str, board: str) -> Quote | None:
        payload = self._get_json(
            f"/engines/stock/markets/shares/boards/{board}/securities/{ticker}.json",
            params={"iss.meta": "off", "iss.only": "securities,marketdata"},
        )

        market = self._first_row(payload, "marketdata")
        security = self._first_row(payload, "securities")
        if market is None and security is None:
            if board in BOND_BOARDS:
                payload = self._get_json(
                    f"/engines/stock/markets/bonds/boards/{board}/securities/{ticker}.json",
                    params={"iss.meta": "off", "iss.only": "securities,marketdata"},
                )
                market = self._first_row(payload, "marketdata")
                security = self._first_row(payload, "securities")

        if market is None and security is None:
            return None

        last_price = self._pick_float(
            market, ("LAST", "LCURRENTPRICE", "MARKETPRICE"), positive=True
        )
        # Previous session close — not today's LCLOSEPRICE (legal close of this day).
        prev_price = self._pick_float(security, ("PREVPRICE", "PREVWAPRICE"), positive=True)
        if prev_price is None:
            prev_price = self._pick_float(market, ("PREVPRICE",), positive=True)

        if last_price is None:
            last_price = prev_price
        if last_price is None:
            last_price = self._pick_float(
                security, ("PREVPRICE", "PREVWAPRICE", "ISSUEPRICE"), positive=True
            )

        if last_price is None or last_price <= 0:
            return None

        day_change = self._pick_float(market, ("LASTTOPREVPRICE",))
        if day_change is None and prev_price:
            day_change = (last_price / prev_price - 1.0) * 100.0

        return Quote(
            ticker=ticker,
            board=board,
            last_price=float(last_price),
            prev_price=float(prev_price) if prev_price is not None else None,
            short_name=self._pick_str(security, ("SHORTNAME",)),
            sec_name=self._pick_str(security, ("SECNAME",)),
            isin=self._pick_str(security, ("ISIN",)),
            open_price=self._pick_float(market, ("OPEN",), positive=True),
            high_price=self._pick_float(market, ("HIGH",), positive=True),
            low_price=self._pick_float(market, ("LOW",), positive=True),
            day_change_pct=day_change,
            volume_today=self._pick_float(market, ("VOLTODAY",)),
            value_today=self._pick_float(market, ("VALTODAY", "VALTODAY_RUR")),
            num_trades=self._pick_int(market, ("NUMTRADES",)),
            bid=self._pick_float(market, ("BID",), positive=True),
            offer=self._pick_float(market, ("OFFER",), positive=True),
            spread=self._pick_float(market, ("SPREAD",)),
            market_cap=self._pick_float(market, ("ISSUECAPITALIZATION",), positive=True),
            lot_size=self._pick_float(security, ("LOTSIZE",), positive=True),
            list_level=self._pick_int(security, ("LISTLEVEL",)),
            trading_status=self._pick_str(market, ("TRADINGSTATUS",)),
            update_time=self._pick_str(market, ("UPDATETIME", "TIME", "SYSTIME")),
        )

    def _apply_candle_stats(self, quote: Quote) -> None:
        try:
            rows = self._fetch_candles(quote.ticker, quote.board)
        except Exception:  # noqa: BLE001 — candles are optional enrichment
            return
        stats = _stats_from_candles(rows)
        if stats is None:
            return
        quote.return_1w_pct = stats["return_1w_pct"]
        quote.return_1m_pct = stats["return_1m_pct"]
        quote.return_3m_pct = stats["return_3m_pct"]
        quote.return_1y_pct = stats["return_1y_pct"]
        quote.high_52w = stats["high_52w"]
        quote.low_52w = stats["low_52w"]

    def _fetch_candles(self, ticker: str, board: str) -> list[dict[str, Any]]:
        from_date = (date.today() - timedelta(days=CANDLE_LOOKBACK_DAYS)).isoformat()
        markets = ("bonds", "shares") if board in BOND_BOARDS else ("shares", "bonds")
        for market in markets:
            try:
                payload = self._get_json(
                    f"/engines/stock/markets/{market}/boards/{board}"
                    f"/securities/{ticker}/candles.json",
                    params={
                        "iss.meta": "off",
                        "iss.only": "candles",
                        "interval": "24",
                        "from": from_date,
                    },
                )
            except (httpx.HTTPError, MoexError):
                continue
            rows = self._table_rows(payload, "candles")
            if rows:
                return rows
        return []

    def _get_json(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        response = self._client.get(path, params=params)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise MoexError(f"Unexpected MOEX response for {path}")
        return data

    @staticmethod
    def _table_rows(payload: dict[str, Any], table: str) -> list[dict[str, Any]]:
        block = payload.get(table)
        if not isinstance(block, dict):
            return []
        columns = block.get("columns")
        data = block.get("data")
        if not isinstance(columns, list) or not isinstance(data, list):
            return []
        rows: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, list):
                continue
            rows.append(dict(zip(columns, item, strict=False)))
        return rows

    def _first_row(self, payload: dict[str, Any], table: str) -> dict[str, Any] | None:
        rows = self._table_rows(payload, table)
        return rows[0] if rows else None

    @staticmethod
    def _cell(row: dict[str, Any] | None, key: str) -> Any:
        if row is None:
            return None
        if key in row:
            return row[key]
        lower = key.lower()
        if lower in row:
            return row[lower]
        return None

    @classmethod
    def _pick_float(
        cls,
        row: dict[str, Any] | None,
        keys: tuple[str, ...],
        *,
        positive: bool = False,
    ) -> float | None:
        if row is None:
            return None
        for key in keys:
            value = cls._cell(row, key)
            if value is None or value == "":
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if positive and number <= 0:
                continue
            return number
        return None

    @classmethod
    def _pick_int(cls, row: dict[str, Any] | None, keys: tuple[str, ...]) -> int | None:
        number = cls._pick_float(row, keys)
        if number is None:
            return None
        return int(number)

    @classmethod
    def _pick_str(cls, row: dict[str, Any] | None, keys: tuple[str, ...]) -> str | None:
        if row is None:
            return None
        for key in keys:
            value = cls._cell(row, key)
            if value is None or value == "":
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    @staticmethod
    def _pick_price(row: dict[str, Any] | None, keys: tuple[str, ...]) -> float | None:
        return MoexClient._pick_float(row, keys, positive=True)


def _parse_candle_begin(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def _stats_from_candles(rows: list[dict[str, Any]]) -> dict[str, float | None] | None:
    points: list[tuple[date, float, float, float]] = []
    for row in rows:
        begin = _parse_candle_begin(row.get("begin") or row.get("BEGIN"))
        close = MoexClient._pick_float(row, ("close", "CLOSE"), positive=True)
        high = MoexClient._pick_float(row, ("high", "HIGH"), positive=True)
        low = MoexClient._pick_float(row, ("low", "LOW"), positive=True)
        if begin is None or close is None:
            continue
        points.append((begin, close, high or close, low or close))

    if len(points) < 2:
        return None

    points.sort(key=lambda item: item[0])
    last_date, last_close, _, _ = points[-1]
    window = [item for item in points if item[0] >= last_date - timedelta(days=365)]
    if not window:
        window = points

    highs = [item[2] for item in window]
    lows = [item[3] for item in window]

    return {
        "return_1w_pct": _return_vs(points, last_date, last_close, days=7),
        "return_1m_pct": _return_vs(points, last_date, last_close, days=30),
        "return_3m_pct": _return_vs(points, last_date, last_close, days=91),
        "return_1y_pct": _return_vs(points, last_date, last_close, days=365),
        "high_52w": max(highs) if highs else None,
        "low_52w": min(lows) if lows else None,
    }


def _return_vs(
    points: list[tuple[date, float, float, float]],
    last_date: date,
    last_close: float,
    *,
    days: int,
) -> float | None:
    target = last_date - timedelta(days=days)
    prior = [item for item in points if item[0] <= target]
    if not prior:
        return None
    base = prior[-1][1]
    if base <= 0:
        return None
    return (last_close / base - 1.0) * 100.0
