from datetime import date
from decimal import Decimal

import httpx
import pytest

from app.providers.base import ProviderStatus
from app.providers.macro.fred import FredError, FredProvider
from app.utils.http import redact

FAKE_KEY = "a" * 32


def _fred(handler) -> FredProvider:
    p = FredProvider(api_key=FAKE_KEY, client=httpx.Client(transport=httpx.MockTransport(handler)))
    p._last_call = -1e9
    return p


def test_observations_parse_vintages_missing_and_sentinel(monkeypatch):
    monkeypatch.setattr("app.providers.macro.fred.MIN_INTERVAL_S", 0)
    pages = [
        {"count": 3, "observations": [
            {"date": "2024-01-01", "value": "308.417", "realtime_start": "2024-02-13",
             "realtime_end": "2025-02-11"},
            {"date": "2024-01-01", "value": "308.4", "realtime_start": "2025-02-12",
             "realtime_end": "9999-12-31"},
        ]},
        {"count": 3, "observations": [
            {"date": "2024-02-01", "value": ".", "realtime_start": "2024-03-12",
             "realtime_end": "9999-12-31"},
        ]},
    ]
    offsets = []

    def handler(req: httpx.Request):
        offsets.append(int(req.url.params["offset"]))
        assert req.url.params["realtime_start"] == "1776-07-04"
        return httpx.Response(200, json=pages[len(offsets) - 1])

    obs = list(_fred(handler).observations("CPIAUCSL", date(2024, 1, 1), date(2024, 2, 1)))
    assert offsets == [0, 2]  # paginated
    assert obs[0].value == Decimal("308.417") and obs[0].realtime_end == date(2025, 2, 11)
    assert obs[1].realtime_end is None  # 9999-12-31 -> current
    assert obs[2].value is None  # "." -> missing, not zero


def test_errors_never_leak_api_key(monkeypatch):
    monkeypatch.setattr("app.providers.macro.fred.MIN_INTERVAL_S", 0)

    def handler(req):
        return httpx.Response(400, json={"error_code": 400, "error_message": "Bad series"})

    with pytest.raises(FredError) as ei:
        list(_fred(handler).observations("NOPE", date(2024, 1, 1), date(2024, 1, 2)))
    assert FAKE_KEY not in str(ei.value) and "Bad series" in str(ei.value)


def test_health_disconnected_without_key(monkeypatch):
    p = FredProvider(api_key=None)
    p._api_key = None
    assert p.check_health().status == ProviderStatus.DISCONNECTED


def test_redact():
    assert redact("https://x/y?series_id=A&api_key=SECRET&src=keep") == (
        "https://x/y?series_id=A&api_key=***&src=keep"
    )
    assert redact("https://api.tradingeconomics.com/calendar?c=guest:guest") == (
        "https://api.tradingeconomics.com/calendar?c=***"
    )


# ---- live checks (uv run pytest -m live) -------------------------------------------------


@pytest.mark.live
def test_live_fred_health():
    assert FredProvider().check_health().status == ProviderStatus.CONNECTED


@pytest.mark.live
def test_live_cpi_first_release_vintage():
    """Jan-2024 CPI index level as first published on 2024-02-13 is retrievable."""
    obs = [
        o for o in FredProvider().observations("CPIAUCSL", date(2024, 1, 1), date(2024, 1, 1))
    ]
    first = min(obs, key=lambda o: o.realtime_start)
    assert first.realtime_start == date(2024, 2, 13)
    assert first.value is not None
    assert len(obs) >= 2  # has been revised since


@pytest.mark.live
def test_live_cpi_release_dates_include_revision_only_dates():
    dates = FredProvider().release_dates(10, date(2024, 1, 1), date(2024, 3, 31))
    assert date(2024, 2, 13) in dates  # Jan CPI report
    assert date(2024, 2, 9) in dates  # seasonal-factor revision: NOT a CPI report
