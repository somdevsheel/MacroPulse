"""OANDA v20 REST adapter: historical candles (bid / ask / mid) for FX and XAU.

Docs: https://developer.oanda.com/rest-live-v20/instrument-ep/
  GET /v3/instruments/{instrument}/candles?granularity=M1&price=BAM&from=...&count=5000
Timestamps are UTC (RFC3339). `volume` is OANDA tick volume (price updates), not traded volume.
Only `complete` candles are kept. Data is used for research under the account's terms; it is
not redistributed.

Verified 2026-11-24 (practice account): M1 bid/ask/mid available from 2005 for EUR_USD and from
2006-03 for XAU_USD.
"""

import threading
import time as _time
from datetime import UTC, datetime, timedelta

import httpx
import polars as pl

from app.core.config import get_settings
from app.providers.base import MarketDataProvider, ProviderHealth, ProviderStatus
from app.utils.http import get_with_retry

HOSTS = {"practice": "https://api-fxpractice.oanda.com",
         "live": "https://api-fxtrade.oanda.com"}
MAX_COUNT = 5000
GRAN = {"1m": "M1", "5m": "M5", "15m": "M15", "1h": "H1", "4h": "H4", "1d": "D"}
SCHEMA = {"ts": pl.Datetime("us", "UTC"),
          **{f"{s}_{f}": pl.Float64 for s in ("bid", "ask", "mid")
             for f in ("open", "high", "low", "close")},
          "volume": pl.Float64}


class OandaError(RuntimeError):
    pass


class _RateLimiter:
    """Process-wide minimum interval between requests (shared across threads)."""

    def __init__(self, per_second: float):
        self.interval = 1.0 / per_second
        self.lock = threading.Lock()
        self.next_at = 0.0

    def wait(self):
        with self.lock:
            now = _time.monotonic()
            delay = self.next_at - now
            self.next_at = max(now, self.next_at) + self.interval
        if delay > 0:
            _time.sleep(delay)


LIMITER = _RateLimiter(per_second=15)  # well under OANDA's documented REST limits


def _parse(c: dict) -> dict:
    row = {"ts": datetime.fromisoformat(c["time"][:19] + "+00:00"),
           "volume": float(c["volume"])}
    for side in ("bid", "ask", "mid"):
        p = c.get(side) or {}
        for k, f in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close")):
            row[f"{side}_{f}"] = float(p[k]) if k in p else None
    return row


class OandaProvider(MarketDataProvider):
    key = "oanda"
    name = "OANDA v20"

    def __init__(self, token: str | None = None, environment: str | None = None):
        s = get_settings()
        self._token = token or (s.oanda_api_token.get_secret_value()
                                if s.oanda_api_token else None)
        self.base = HOSTS[environment or s.oanda_environment]

    def is_configured(self) -> bool:
        return bool(self._token and self._token.strip())

    def client(self) -> httpx.Client:
        if not self.is_configured():
            raise OandaError("OANDA_API_TOKEN not configured")
        return httpx.Client(timeout=60, headers={
            "Authorization": f"Bearer {self._token}", "Accept-Datetime-Format": "RFC3339",
            "User-Agent": "MacroPulse/0.1"})

    def _get(self, c: httpx.Client, path: str, params: dict | None = None) -> dict:
        LIMITER.wait()
        r = get_with_retry(c, f"{self.base}{path}", params=params)
        if r.status_code != 200:
            try:
                msg = r.json().get("errorMessage", r.text[:200])
            except ValueError:
                msg = r.text[:200]
            raise OandaError(f"OANDA {r.status_code} on {path}: {msg}")
        return r.json()

    def check_health(self) -> ProviderHealth:
        if not self.is_configured():
            return ProviderHealth(self.key, ProviderStatus.DISCONNECTED, detail="no credentials")
        try:
            with self.client() as c:
                n = len(self._get(c, "/v3/accounts").get("accounts", []))
            return ProviderHealth(self.key, ProviderStatus.CONNECTED,
                                  detail=f"{n} account(s), historical candles")
        except Exception as e:
            return ProviderHealth(self.key, ProviderStatus.ERROR, detail=str(e)[:300])

    def candles(self, c: httpx.Client, instrument: str, start: datetime, end: datetime,
                timeframe: str = "1m") -> pl.DataFrame:
        """Complete candles with start <= ts < end, bid/ask/mid. Paginates by `count`."""
        rows: list[dict] = []
        cursor = start
        step = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}[timeframe]
        while cursor < end:
            data = self._get(c, f"/v3/instruments/{instrument}/candles", {
                "granularity": GRAN[timeframe], "price": "BAM",
                "from": cursor.strftime("%Y-%m-%dT%H:%M:%SZ"), "count": MAX_COUNT})
            got = data.get("candles", [])
            if not got:
                break
            parsed = [_parse(x) for x in got if x.get("complete")]
            rows += [r for r in parsed if r["ts"] < end]
            last = datetime.fromisoformat(got[-1]["time"][:19] + "+00:00")
            if last < cursor:
                raise OandaError(f"{instrument}: pagination made no progress at {cursor}")
            if last >= end or len(got) < MAX_COUNT:
                break
            cursor = last + timedelta(minutes=step)
        return pl.DataFrame(rows, schema=SCHEMA) if rows else pl.DataFrame(schema=SCHEMA)

    def candles_1m(self, symbol, start, end):  # interface compatibility
        with self.client() as c:
            df = self.candles(c, symbol, start.astimezone(UTC), end.astimezone(UTC))
        return df.iter_rows(named=True)
