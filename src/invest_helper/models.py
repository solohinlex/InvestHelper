"""Domain models for portfolio and market snapshot."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class Position(BaseModel):
    ticker: str
    quantity: float = Field(gt=0)
    avg_price: float = Field(ge=0)
    board: str | None = None

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        ticker = value.strip().upper()
        if not ticker:
            raise ValueError("ticker must not be empty")
        return ticker

    @field_validator("board")
    @classmethod
    def normalize_board(cls, value: str | None) -> str | None:
        if value is None:
            return None
        board = value.strip().upper()
        return board or None


class AllocationClass(BaseModel):
    name: str
    tickers: list[str] = Field(default_factory=list)
    target_pct: float | None = None
    include_cash: bool = False

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("allocation class name must not be empty")
        return name

    @field_validator("tickers")
    @classmethod
    def normalize_tickers(cls, values: list[str]) -> list[str]:
        tickers: list[str] = []
        for item in values:
            ticker = item.strip().upper()
            if ticker and ticker not in tickers:
                tickers.append(ticker)
        return tickers


class Allocation(BaseModel):
    """Optional per-portfolio mix. Excluded tickers are out of the class-weight denominator."""

    exclude: list[str] = Field(default_factory=list)
    classes: list[AllocationClass] = Field(default_factory=list)

    @field_validator("exclude")
    @classmethod
    def normalize_exclude(cls, values: list[str]) -> list[str]:
        tickers: list[str] = []
        for item in values:
            ticker = item.strip().upper()
            if ticker and ticker not in tickers:
                tickers.append(ticker)
        return tickers


class Portfolio(BaseModel):
    currency: str = "RUB"
    cash: float = Field(default=0.0, ge=0)
    positions: list[Position] = Field(default_factory=list)
    allocation: Allocation | None = None

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        currency = value.strip().upper()
        if not currency:
            raise ValueError("currency must not be empty")
        return currency


class Quote(BaseModel):
    ticker: str
    board: str
    last_price: float
    prev_price: float | None = None
    source: str = "moex_iss"
    short_name: str | None = None
    sec_name: str | None = None
    isin: str | None = None
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    day_change_pct: float | None = None
    volume_today: float | None = None
    value_today: float | None = None
    num_trades: int | None = None
    bid: float | None = None
    offer: float | None = None
    spread: float | None = None
    market_cap: float | None = None
    lot_size: float | None = None
    list_level: int | None = None
    trading_status: str | None = None
    update_time: str | None = None
    return_1w_pct: float | None = None
    return_1m_pct: float | None = None
    return_3m_pct: float | None = None
    return_1y_pct: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None


class PositionSnapshot(BaseModel):
    ticker: str
    board: str
    quantity: float
    avg_price: float
    last_price: float
    value: float
    cost: float
    pnl: float
    pnl_pct: float | None
    weight: float
    short_name: str | None = None
    sec_name: str | None = None
    isin: str | None = None
    prev_price: float | None = None
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    day_change_pct: float | None = None
    day_range_pos_pct: float | None = None
    volume_today: float | None = None
    value_today: float | None = None
    num_trades: int | None = None
    bid: float | None = None
    offer: float | None = None
    spread: float | None = None
    market_cap: float | None = None
    lot_size: float | None = None
    lots: float | None = None
    list_level: int | None = None
    trading_status: str | None = None
    update_time: str | None = None
    return_1w_pct: float | None = None
    return_1m_pct: float | None = None
    return_3m_pct: float | None = None
    return_1y_pct: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    range_52w_pos_pct: float | None = None
    class_name: str | None = None
    weight_in_class: float | None = None


class ClassSnapshot(BaseModel):
    name: str
    value: float
    weight: float
    target_pct: float | None = None
    deviation_pp: float | None = None
    tickers: list[str] = Field(default_factory=list)


class ReferenceSnapshot(BaseModel):
    ticker: str
    value: float
    weight_total: float


class PortfolioSnapshot(BaseModel):
    currency: str
    cash: float
    positions_value: float
    total_value: float
    total_cost: float
    total_pnl: float
    total_pnl_pct: float | None
    positions: list[PositionSnapshot]
    top_concentration: list[tuple[str, float]]
    allocation_base: float | None = None
    classes: list[ClassSnapshot] = Field(default_factory=list)
    reference: list[ReferenceSnapshot] = Field(default_factory=list)
    unmapped: list[ReferenceSnapshot] = Field(default_factory=list)
    missing_quotes: list[str] = Field(default_factory=list)
