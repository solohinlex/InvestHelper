"""MOEX ISS market data client."""

from __future__ import annotations

from typing import Any

import httpx

from invest_helper.models import Position, Quote

MOEX_ISS_BASE = "https://iss.moex.com/iss"
PREFERRED_BOARDS = ("TQBR", "TQTF", "TQOB", "TQCB", "TQPI", "SPEQ")


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
            quotes[position.ticker] = self.fetch_quote(position.ticker, position.board)
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
            # Bonds / other markets: try bonds endpoint for known bond boards
            if board in {"TQOB", "TQCB", "TQIR"}:
                payload = self._get_json(
                    f"/engines/stock/markets/bonds/boards/{board}/securities/{ticker}.json",
                    params={"iss.meta": "off", "iss.only": "securities,marketdata"},
                )
                market = self._first_row(payload, "marketdata")
                security = self._first_row(payload, "securities")

        if market is None and security is None:
            return None

        last_price = self._pick_price(market, ("LAST", "LCURRENTPRICE", "MARKETPRICE"))
        prev_price = self._pick_price(
            market,
            ("PREVPRICE", "LCLOSEPRICE"),
        )
        if prev_price is None and security is not None:
            prev_price = self._pick_price(security, ("PREVPRICE", "PREVWAPRICE"))

        if last_price is None:
            last_price = prev_price
        if last_price is None and security is not None:
            last_price = self._pick_price(security, ("PREVPRICE", "PREVWAPRICE", "ISSUEPRICE"))

        if last_price is None or last_price <= 0:
            return None

        return Quote(
            ticker=ticker,
            board=board,
            last_price=float(last_price),
            prev_price=float(prev_price) if prev_price is not None else None,
        )

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
    def _pick_price(row: dict[str, Any] | None, keys: tuple[str, ...]) -> float | None:
        if row is None:
            return None
        for key in keys:
            value = row.get(key)
            if value is None or value == "":
                continue
            try:
                price = float(value)
            except (TypeError, ValueError):
                continue
            if price > 0:
                return price
        return None
