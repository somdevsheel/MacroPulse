"""Adapters whose fetch logic is not built yet. They report real configuration state
(disconnected when no credential) and refuse to return data rather than fabricate it."""

from collections.abc import Iterable
from datetime import date, datetime

from app.core.config import get_settings
from app.providers.base import (
    CalendarEntry,
    Candle,
    EconomicCalendarProvider,
    MarketDataProvider,
)


def _has(secret) -> bool:
    return bool(secret and secret.get_secret_value().strip())


class TradingEconomicsProvider(EconomicCalendarProvider):
    """Paid. The only planned source of historical CONSENSUS forecasts.
    Docs: https://docs.tradingeconomics.com/ (verify plan coverage before implementing)."""

    key = "trading_economics"
    name = "Trading Economics calendar"

    def is_configured(self) -> bool:
        return _has(get_settings().trading_economics_api_key)

    def calendar(self, start: date, end: date) -> Iterable[CalendarEntry]:
        raise NotImplementedError("Trading Economics adapter pending (needs paid subscription)")


class TwelveDataProvider(MarketDataProvider):
    key = "twelve_data"
    name = "Twelve Data"

    def is_configured(self) -> bool:
        return _has(get_settings().twelve_data_api_key)

    def candles_1m(self, symbol: str, start: datetime, end: datetime) -> Iterable[Candle]:
        raise NotImplementedError("Twelve Data adapter pending")
