"""Read-only T-Invest MCP client. Used by sync, not by analyze."""

from __future__ import annotations

import json
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from invest_helper import __version__
from invest_helper.models import Position
from invest_helper.portfolio import replace_holdings

MCP_PROTOCOL = "2025-03-26"
RUB_TICKERS = {"RUB", "RUR", "RUB000UTSTOM"}
SKIP_TYPES = {"futures", "future", "option", "sp", "structured"}
CASH_TYPES = {"currency", "money", "cash"}
CURRENCY_BOARDS = {"CETS", "CNGDOTC", "EES_CETS"}
# Python trusts the OpenSSL bundle, which often omits this root even when the file is installed.
RUSSIAN_ROOT_CANDIDATES = (
    Path("/etc/ssl/certs/russian_trusted_root_ca_pem.pem"),
    Path("/usr/local/share/ca-certificates/russian-trusted/russian_trusted_root_ca_pem.crt"),
)


class TinvestError(RuntimeError):
    """Raised when T-Invest MCP cannot provide holdings."""


@dataclass(frozen=True)
class SyncResult:
    account_ids: list[str]
    cash: float
    tickers: list[str]
    skipped: list[str]


class TinvestClient:
    def __init__(self, token: str, url: str, timeout: float) -> None:
        self._url = url.rstrip("/")
        self._protocol = MCP_PROTOCOL
        self._session_id: str | None = None
        self._next_id = 0
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "User-Agent": f"InvestHelper/{__version__}",
            },
            follow_redirects=True,
            verify=_ssl_context(),
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> TinvestClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def initialize(self) -> None:
        result = self._rpc(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "invest-helper", "version": __version__},
            },
        )
        if isinstance(result, dict) and result.get("protocolVersion"):
            self._protocol = str(result["protocolVersion"])
        self._rpc("notifications/initialized", notify=True)

    def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params = {"cursor": cursor} if cursor else {}
            result = self._rpc("tools/list", params)
            if not isinstance(result, dict):
                break
            batch = result.get("tools") or []
            tools.extend(item for item in batch if isinstance(item, dict))
            cursor = result.get("nextCursor") or None
            if not cursor:
                break
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        if not isinstance(result, dict):
            raise TinvestError(f"Пустой ответ инструмента {name}")
        if result.get("isError"):
            text = _content_text(result) or f"инструмент {name} вернул ошибку"
            raise TinvestError(text)
        if "structuredContent" in result:
            return result["structuredContent"]
        text = _content_text(result)
        if not text:
            return result
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    def _rpc(self, method: str, params: dict[str, Any] | None = None, *, notify: bool = False) -> Any:
        self._next_id += 1
        request_id = None if notify else self._next_id
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if request_id is not None:
            body["id"] = request_id
        if params is not None:
            body["params"] = params

        headers = {"MCP-Protocol-Version": self._protocol}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        try:
            response = self._client.post(self._url, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise TinvestError("T-Invest MCP не ответил вовремя") from exc
        except httpx.HTTPError as exc:
            raise TinvestError(_connect_message(exc)) from exc

        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self._session_id = session_id

        if response.status_code in {401, 403}:
            raise TinvestError(
                "T-Invest отклонил токен. Проверьте TINVEST_TOKEN в .env "
                "и что у токена есть право чтения."
            )
        if notify and response.status_code in {200, 202, 204}:
            return None

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise TinvestError(
                f"T-Invest MCP вернул HTTP {response.status_code}"
            ) from exc

        if notify:
            return None

        payload = _parse_body(response, request_id)
        if "error" in payload:
            error = payload["error"]
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise TinvestError(f"T-Invest MCP: {message}")
        return payload.get("result")


def sync_holdings(
    path: Path,
    *,
    token: str,
    url: str,
    timeout: float,
) -> SyncResult:
    if not token.strip():
        raise TinvestError(
            "TINVEST_TOKEN не задан. Выпустите токен «только чтение» в кабинете "
            "Т-Инвестиций и добавьте строку TINVEST_TOKEN=... в .env "
            "(образец в .env.example)."
        )

    with TinvestClient(token.strip(), url.strip(), timeout) as client:
        client.initialize()
        tools = client.list_tools()
        _tool_by_name(tools, "invest_list_broker_accounts")
        _tool_by_name(tools, "invest_get_portfolio")
        accounts = _open_accounts(
            _accounts(
                client.call_tool(
                    "invest_list_broker_accounts",
                    {"status": "ACCOUNT_STATUS_OPEN"},
                )
            )
        )
        parts: list[tuple[float, list[Position], list[str]]] = []
        for account_id in accounts:
            payload = client.call_tool(
                "invest_get_portfolio",
                {"accountId": account_id, "responseView": ["DETAILED"]},
            )
            parts.append(_map_portfolio(payload))

    cash, positions, skipped = _merge_holdings(parts)
    if not positions and cash <= 0:
        detail = "; ".join(skipped) if skipped else "пустой ответ"
        raise TinvestError(f"Не удалось прочитать портфель, файл не изменён ({detail})")

    replace_holdings(path, cash=cash, positions=positions)
    return SyncResult(
        account_ids=accounts,
        cash=cash,
        tickers=[position.ticker for position in positions],
        skipped=skipped,
    )


def _tool_by_name(tools: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for tool in tools:
        if tool.get("name") == name:
            return tool
    available = ", ".join(str(tool.get("name")) for tool in tools) or "—"
    raise TinvestError(f"Среди инструментов MCP нет {name}. Доступны: {available}")


def _accounts(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("accounts", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        if any(key in payload for key in ("id", "accountId", "account_id")):
            return [payload]
    raise TinvestError("Не удалось прочитать список счетов")


def _open_accounts(accounts: list[dict[str, Any]]) -> list[str]:
    open_ids: list[str] = []
    for item in accounts:
        account_id = _account_id(item)
        if not account_id or _is_closed(item):
            continue
        if account_id not in open_ids:
            open_ids.append(account_id)
    if not open_ids:
        raise TinvestError("Список открытых счетов пуст")
    return open_ids


def _is_closed(item: dict[str, Any]) -> bool:
    status = item.get("status")
    if not isinstance(status, str):
        return False
    return "clos" in status.lower()


def _account_id(item: dict[str, Any]) -> str:
    for key in ("id", "accountId", "account_id"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _merge_holdings(
    parts: list[tuple[float, list[Position], list[str]]],
) -> tuple[float, list[Position], list[str]]:
    cash = 0.0
    merged: dict[str, tuple[float, float, str | None]] = {}
    skipped: list[str] = []
    for part_cash, positions, part_skipped in parts:
        cash += part_cash
        skipped.extend(part_skipped)
        for position in positions:
            prev_qty, prev_cost, prev_board = merged.get(position.ticker, (0.0, 0.0, None))
            merged[position.ticker] = (
                prev_qty + position.quantity,
                prev_cost + position.quantity * position.avg_price,
                position.board or prev_board,
            )
    positions = [
        Position(
            ticker=ticker,
            quantity=quantity,
            avg_price=cost / quantity,
            board=board,
        )
        for ticker, (quantity, cost, board) in merged.items()
    ]
    return cash, positions, skipped


def _map_portfolio(payload: Any) -> tuple[float, list[Position], list[str]]:
    rows = _position_rows(payload)
    cash = 0.0
    saw_rub_cash = False
    merged: dict[str, tuple[float, float, str]] = {}
    skipped: list[str] = []

    for item in rows:
        kind = _instrument_type(item)
        ticker = _ticker(item)
        class_code = _class_code(item)
        if kind in SKIP_TYPES or class_code == "DFA":
            skipped.append(ticker or kind or class_code)
            continue
        if _is_currency_line(ticker, class_code) or _is_cash(kind, ticker):
            if _is_rub(item, ticker):
                amount = _quantity(item)
                if amount is not None and amount > 0:
                    cash += amount
                    saw_rub_cash = True
            else:
                skipped.append(ticker or kind or "валюта")
            continue
        if not ticker:
            skipped.append(kind or class_code or "позиция без тикера")
            continue
        quantity = _quantity(item)
        price = _avg_price(item)
        if quantity is None or quantity <= 0:
            continue
        if price is None:
            skipped.append(f"{ticker}: нет средней цены")
            continue
        prev_qty, prev_cost, prev_board = merged.get(ticker, (0.0, 0.0, ""))
        merged[ticker] = (
            prev_qty + quantity,
            prev_cost + quantity * price,
            class_code or prev_board,
        )

    if not saw_rub_cash:
        fallback = _rub_cash_fallback(payload)
        if fallback is not None:
            cash = fallback

    positions = [
        Position(
            ticker=ticker,
            quantity=quantity,
            avg_price=cost / quantity,
            board=class_code or None,
        )
        for ticker, (quantity, cost, class_code) in merged.items()
    ]
    return cash, positions, skipped


def _position_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("positions", "securities", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    keys = list(payload) if isinstance(payload, dict) else type(payload).__name__
    raise TinvestError(f"В ответе портфеля нет списка позиций ({keys})")


def _instrument_type(item: dict[str, Any]) -> str:
    for key in ("instrumentType", "instrument_type", "type"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return ""


def _ticker(item: dict[str, Any]) -> str | None:
    for key in ("ticker", "tickerName"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            ticker = value.strip().upper()
            if ticker.endswith("@"):
                ticker = ticker[:-1]
            return ticker
    instrument = item.get("instrument")
    if isinstance(instrument, dict):
        return _ticker(instrument)
    return None


def _class_code(item: dict[str, Any]) -> str:
    for key in ("classCode", "class_code", "board"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    return ""


def _is_currency_line(ticker: str | None, class_code: str) -> bool:
    if class_code in CURRENCY_BOARDS:
        return True
    symbol = ticker or ""
    return symbol in RUB_TICKERS or symbol.endswith("UTSTOM") or "_TOM" in symbol


def _is_cash(kind: str, ticker: str | None) -> bool:
    if kind in CASH_TYPES:
        return True
    return (ticker or "") in RUB_TICKERS


def _is_rub(item: dict[str, Any], ticker: str | None) -> bool:
    if (ticker or "") in RUB_TICKERS:
        return True
    for key in ("currency", "nominalCurrency"):
        value = item.get(key)
        if isinstance(value, str) and value.strip().lower() in {"rub", "rur"}:
            return True
    return False


def _quantity(item: dict[str, Any]) -> float | None:
    for key in ("quantity", "balance"):
        if key in item:
            return _number(item[key])
    return None


def _avg_price(item: dict[str, Any]) -> float | None:
    for key in (
        "averagePositionPrice",
        "averagePositionPriceFifo",
        "avgPrice",
        "averagePrice",
        "avg_price",
    ):
        if key in item and item[key] not in (None, {}):
            return _number(item[key])
    return None


def _rub_cash_fallback(payload: Any) -> float | None:
    if not isinstance(payload, dict):
        return None
    for key in ("totalAmountCurrencies", "currencies", "money"):
        if key not in payload:
            continue
        amount = _number(payload[key])
        if amount is not None:
            return amount
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "."))
        except ValueError:
            return None
    if isinstance(value, dict):
        if "units" in value:
            try:
                units = float(value.get("units") or 0)
            except (TypeError, ValueError):
                return None
            try:
                nano = float(value.get("nano") or 0) / 1_000_000_000
            except (TypeError, ValueError):
                nano = 0.0
            return units + nano
        for key in ("value", "amount", "balance"):
            if key in value:
                return _number(value[key])
    return None


def _content_text(result: dict[str, Any]) -> str:
    parts: list[str] = []
    content = result.get("content") or []
    if not isinstance(content, list):
        return ""
    for block in content:
        if isinstance(block, dict) and "text" in block:
            parts.append(str(block["text"]))
    return "\n".join(parts).strip()


def _parse_body(response: httpx.Response, request_id: int | None) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        return _parse_sse(response.text, request_id)
    if not response.content:
        raise TinvestError("Пустой ответ T-Invest MCP")
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise TinvestError("T-Invest MCP вернул не JSON") from exc
    if not isinstance(payload, dict):
        raise TinvestError("T-Invest MCP вернул не объект JSON-RPC")
    return payload


def _parse_sse(text: str, request_id: int | None) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    data_lines: list[str] = []

    def flush() -> None:
        if not data_lines:
            return
        raw = "\n".join(data_lines).strip()
        data_lines.clear()
        if not raw or raw == "[DONE]":
            return
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        if isinstance(payload, dict):
            messages.append(payload)

    for line in text.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif line == "":
            flush()
    flush()

    if request_id is not None:
        for message in messages:
            if message.get("id") == request_id:
                return message
    if messages:
        return messages[-1]
    raise TinvestError("Пустой поток T-Invest MCP")


def _ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    for path in RUSSIAN_ROOT_CANDIDATES:
        if path.is_file():
            context.load_verify_locations(cafile=str(path))
            break
    return context


def _connect_message(exc: httpx.HTTPError) -> str:
    text = str(exc).lower()
    if "certificate" in text or "ssl" in text or "tls" in text:
        return (
            "Не удалось установить TLS с T-Invest MCP. "
            "Проверьте, что в системе установлены сертификаты Минцифры."
        )
    return f"Не удалось подключиться к T-Invest MCP ({exc.__class__.__name__})"
