"""Central list of provider adapters. Add a provider by appending its class here."""

from app.providers.base import BaseProvider, ProviderHealth
from app.providers.economic.fed_calendar import FedCalendarProvider
from app.providers.macro.fred import FredProvider
from app.providers.market.dukascopy import DukascopyProvider
from app.providers.market.oanda import OandaProvider
from app.providers.stubs import TradingEconomicsProvider, TwelveDataProvider

PROVIDER_CLASSES: list[type[BaseProvider]] = [
    FredProvider,
    FedCalendarProvider,
    DukascopyProvider,
    OandaProvider,
    TwelveDataProvider,
    TradingEconomicsProvider,
]


def all_providers() -> list[BaseProvider]:
    return [cls() for cls in PROVIDER_CLASSES]


def health_report() -> list[ProviderHealth]:
    return [p.check_health() for p in all_providers()]
