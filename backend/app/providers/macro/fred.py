"""FRED / ALFRED adapter (St. Louis Fed). One key serves both.

Docs: https://fred.stlouisfed.org/docs/api/fred/  and  .../alfred.html
Limits: 120 requests/minute per key. Observations come back with realtime_start/realtime_end,
which is exactly what point-in-time reconstruction needs.
"""

import logging
import time as _time
from collections.abc import Iterator
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

from app.core.config import get_settings
from app.providers.base import (
    MacroDataProvider,
    Observation,
    ProviderHealth,
    ProviderStatus,
)
from app.utils.http import get_with_retry, make_client, redact

log = logging.getLogger(__name__)

BASE_URL = "https://api.stlouisfed.org/fred"
FRED_FAR_FUTURE = "9999-12-31"  # FRED's sentinel for "still current"
MIN_INTERVAL_S = 0.55  # stay under 120 req/min


class FredError(RuntimeError):
    pass


def _parse_value(raw: str) -> Decimal | None:
    if raw in (".", ""):  # FRED's missing-value marker
        return None
    try:
        return Decimal(raw)
    except InvalidOperation as e:
        raise FredError(f"unparseable FRED value {raw!r}") from e


def _parse_rt_end(raw: str) -> date | None:
    return None if raw == FRED_FAR_FUTURE else date.fromisoformat(raw)


class FredProvider(MacroDataProvider):
    key = "fred"
    name = "FRED / ALFRED (St. Louis Fed)"

    def __init__(self, api_key: str | None = None, client: httpx.Client | None = None):
        secret = get_settings().fred_api_key
        self._api_key = api_key or (secret.get_secret_value() if secret else None)
        self._client = client or make_client()
        self._last_call = 0.0

    def is_configured(self) -> bool:
        return bool(self._api_key)

    # -- low level -----------------------------------------------------------------------
    def _get(self, path: str, **params) -> dict:
        if not self._api_key:
            raise FredError("FRED_API_KEY not configured")
        wait = MIN_INTERVAL_S - (_time.monotonic() - self._last_call)
        if wait > 0:
            _time.sleep(wait)
        self._last_call = _time.monotonic()
        resp = get_with_retry(
            self._client,
            f"{BASE_URL}/{path}",
            params={**params, "api_key": self._api_key, "file_type": "json"},
        )
        if resp.status_code != 200:
            # FRED returns {"error_code":..,"error_message":..}; never echo the key.
            try:
                msg = resp.json().get("error_message", resp.text[:200])
            except ValueError:
                msg = resp.text[:200]
            raise FredError(f"FRED {resp.status_code} on {redact(str(resp.url))}: {msg}")
        return resp.json()

    def _paged(self, path: str, list_key: str, **params) -> Iterator[dict]:
        offset, limit = 0, int(params.pop("limit", 100000))
        while True:
            data = self._get(path, offset=offset, limit=limit, **params)
            items = data.get(list_key, [])
            yield from items
            count = int(data.get("count", len(items)))
            offset += len(items)
            if not items or offset >= count:
                return

    # -- interface -----------------------------------------------------------------------
    def check_health(self) -> ProviderHealth:
        if not self.is_configured():
            return ProviderHealth(self.key, ProviderStatus.DISCONNECTED, detail="no FRED_API_KEY")
        try:
            data = self._get("series", series_id="CPIAUCSL")
            end = data["seriess"][0]["observation_end"]
            return ProviderHealth(self.key, ProviderStatus.CONNECTED, detail=f"CPI to {end}")
        except Exception as e:  # report, don't raise: health checks must not crash the app
            return ProviderHealth(self.key, ProviderStatus.ERROR, detail=str(e)[:300])

    def release_dates(self, release_id: int, start: date, end: date) -> list[date]:
        """All dates FRED recorded a publication for the release (incl. revision-only dates).

        Callers must still filter to dates where a new reference period first appeared.
        """
        rows = self._paged(
            "release/dates",
            "release_dates",
            release_id=release_id,
            realtime_start=start.isoformat(),
            realtime_end=end.isoformat(),
            include_release_dates_with_no_data="true",
            sort_order="asc",
            limit=10000,
        )
        return sorted({date.fromisoformat(r["date"]) for r in rows})

    def observations(
        self, series_id: str, start: date, end: date, *, all_vintages: bool = True
    ) -> Iterator[Observation]:
        """Observations for [start, end]. With all_vintages=True every historical version of
        every value is returned (ALFRED), each with its realtime validity interval."""
        params = {
            "series_id": series_id,
            "observation_start": start.isoformat(),
            "observation_end": end.isoformat(),
        }
        if all_vintages:
            params |= {"realtime_start": "1776-07-04", "realtime_end": FRED_FAR_FUTURE}
        for r in self._paged("series/observations", "observations", **params):
            yield Observation(
                series_id=series_id,
                observation_date=date.fromisoformat(r["date"]),
                value=_parse_value(r["value"]),
                realtime_start=date.fromisoformat(r["realtime_start"]),
                realtime_end=_parse_rt_end(r["realtime_end"]),
            )
