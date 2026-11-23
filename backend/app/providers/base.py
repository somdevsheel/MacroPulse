"""Provider adapter contracts.

Each data source gets its own adapter implementing one of the interfaces below, so the app is
never coupled to a single vendor. Fetch methods return plain records; persistence, validation
and snapshotting live in app/ingestion.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum


class ProviderKind(StrEnum):
    ECONOMIC = "economic"
    MARKET = "market"
    MACRO = "macro"


class ProviderStatus(StrEnum):
    CONNECTED = "connected"  # health check passed just now
    DISCONNECTED = "disconnected"  # missing credentials / not configured
    UNVERIFIED = "unverified"  # configured, but no health check implemented yet
    DEGRADED = "degraded"  # reachable but rate-limited / partial
    ERROR = "error"  # health check failed


@dataclass
class ProviderHealth:
    provider_key: str
    status: ProviderStatus
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    detail: str = ""


# ---- Record types returned by adapters -------------------------------------------------


@dataclass(frozen=True)
class Observation:
    """A vintage-aware observation (ALFRED semantics)."""

    series_id: str
    observation_date: date
    value: Decimal | None
    realtime_start: date
    realtime_end: date | None


@dataclass(frozen=True)
class Candle:
    ts: datetime  # bar open, UTC
    bid: tuple[Decimal, Decimal, Decimal, Decimal] | None = None  # O,H,L,C
    ask: tuple[Decimal, Decimal, Decimal, Decimal] | None = None
    mid: tuple[Decimal, Decimal, Decimal, Decimal] | None = None
    volume: Decimal | None = None
    volume_kind: str = "tick"


@dataclass(frozen=True)
class CalendarEntry:
    """A calendar provider's view of an event at a point in time (with consensus)."""

    provider_event_id: str
    indicator_key: str | None
    scheduled_time: datetime
    reference_period: date | None
    actual: Decimal | None
    forecast: Decimal | None
    previous: Decimal | None
    revised_previous: Decimal | None
    source_timestamp: datetime | None
    raw: dict


# ---- Interfaces --------------------------------------------------------------------------


class BaseProvider(ABC):
    key: str
    name: str
    kind: ProviderKind
    requires_key: bool = True

    @abstractmethod
    def is_configured(self) -> bool: ...

    def check_health(self) -> ProviderHealth:
        """Default: report configuration state only. Adapters override with a real call."""
        if not self.is_configured():
            return ProviderHealth(self.key, ProviderStatus.DISCONNECTED, detail="no credentials")
        return ProviderHealth(self.key, ProviderStatus.UNVERIFIED, detail="adapter pending")


class MacroDataProvider(BaseProvider):
    kind = ProviderKind.MACRO

    @abstractmethod
    def release_dates(self, release_id: int, start: date, end: date) -> list[date]: ...

    @abstractmethod
    def observations(
        self, series_id: str, start: date, end: date, *, all_vintages: bool = True
    ) -> Iterable[Observation]: ...


class MarketDataProvider(BaseProvider):
    kind = ProviderKind.MARKET

    @abstractmethod
    def candles_1m(self, symbol: str, start: datetime, end: datetime) -> Iterable[Candle]: ...


class EconomicCalendarProvider(BaseProvider):
    kind = ProviderKind.ECONOMIC

    @abstractmethod
    def calendar(self, start: date, end: date) -> Iterable[CalendarEntry]: ...
