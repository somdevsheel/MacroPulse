"""Dukascopy historical datafeed (free, no key; bid/ask ticks and 1-minute candles).

Feed layout: https://datafeed.dukascopy.com/datafeed/{SYMBOL}/{YYYY}/{MM0}/{DD}/{file}.bi5
(month is 0-based; .bi5 = LZMA-compressed fixed-width binary records).

Status 2026-11-24: requests from this machine returned HTTP 429 then 503 -- the feed rate-limits
or blocks automated access. The Phase 2 implementation must throttle heavily, back off, cache
every downloaded file in data/bronze, and fall back to OANDA. Check Dukascopy's terms of use for
your use case before bulk download.
"""

from collections.abc import Iterable
from datetime import datetime

from app.providers.base import Candle, MarketDataProvider, ProviderHealth, ProviderStatus
from app.utils.http import make_client

FEED = "https://datafeed.dukascopy.com/datafeed"
# A small, known-good historical file used only as a reachability probe.
_PROBE = f"{FEED}/EURUSD/2024/00/10/13h_ticks.bi5"


class DukascopyProvider(MarketDataProvider):
    key = "dukascopy"
    name = "Dukascopy historical datafeed"
    requires_key = False

    def is_configured(self) -> bool:
        return True

    def check_health(self) -> ProviderHealth:
        try:
            with make_client(timeout=15) as c:
                r = c.get(_PROBE)
        except Exception as e:
            return ProviderHealth(self.key, ProviderStatus.ERROR, detail=str(e)[:300])
        if r.status_code == 200:
            return ProviderHealth(self.key, ProviderStatus.CONNECTED, detail="probe file OK")
        if r.status_code in (429, 503):
            return ProviderHealth(
                self.key, ProviderStatus.DEGRADED, detail=f"HTTP {r.status_code}: rate-limited"
            )
        return ProviderHealth(self.key, ProviderStatus.ERROR, detail=f"HTTP {r.status_code}")

    def candles_1m(self, symbol: str, start: datetime, end: datetime) -> Iterable[Candle]:
        raise NotImplementedError("Dukascopy candle download is implemented in Phase 2")
