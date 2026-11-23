"""Instruments and price candles.

Bulk historical 1-minute history lives in Parquet (data/silver/cleaned_prices) and is queried
with DuckDB. `market_candles` holds recent/live candles and any slice the API needs to serve
transactionally. Both use the same column layout.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, TimestampMixin, UTCDateTime, utcnow


class MarketInstrument(TimestampMixin, Base):
    __tablename__ = "market_instruments"

    instrument_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), unique=True)  # XAUUSD
    display_name: Mapped[str] = mapped_column(String(32))  # XAU/USD
    asset_class: Mapped[str] = mapped_column(String(16))
    base_currency: Mapped[str] = mapped_column(String(8))
    quote_currency: Mapped[str] = mapped_column(String(8))
    pip_size: Mapped[Decimal] = mapped_column(Numeric)
    price_precision: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class MarketCandle(Base):
    """OHLC bar. `ts` = bar OPEN time in UTC. Missing bars are absent, never fabricated.

    volume is provider-specific TICK volume for FX/metals (decentralised market) -- see
    volume_kind. It is not exchange volume.
    """

    __tablename__ = "market_candles"
    __table_args__ = (
        UniqueConstraint("instrument_id", "provider", "timeframe", "ts"),
        Index("ix_candles_lookup", "instrument_id", "timeframe", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("market_instruments.instrument_id"))
    provider: Mapped[str] = mapped_column(String(32))
    timeframe: Mapped[str] = mapped_column(String(8))  # 1m 5m 15m 1h 4h
    ts: Mapped[datetime] = mapped_column(UTCDateTime)

    bid_open: Mapped[Decimal | None] = mapped_column(Numeric)
    bid_high: Mapped[Decimal | None] = mapped_column(Numeric)
    bid_low: Mapped[Decimal | None] = mapped_column(Numeric)
    bid_close: Mapped[Decimal | None] = mapped_column(Numeric)
    ask_open: Mapped[Decimal | None] = mapped_column(Numeric)
    ask_high: Mapped[Decimal | None] = mapped_column(Numeric)
    ask_low: Mapped[Decimal | None] = mapped_column(Numeric)
    ask_close: Mapped[Decimal | None] = mapped_column(Numeric)
    mid_open: Mapped[Decimal | None] = mapped_column(Numeric)
    mid_high: Mapped[Decimal | None] = mapped_column(Numeric)
    mid_low: Mapped[Decimal | None] = mapped_column(Numeric)
    mid_close: Mapped[Decimal | None] = mapped_column(Numeric)

    volume: Mapped[Decimal | None] = mapped_column(Numeric)
    volume_kind: Mapped[str] = mapped_column(String(16), default="tick")  # tick | none
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
