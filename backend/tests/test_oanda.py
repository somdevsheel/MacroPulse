from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.ingestion.oanda_pipeline import _months
from app.providers.market import oanda as oanda_mod
from app.providers.market.oanda import OandaError, OandaProvider

TOKEN = "t" * 40


def _candle(t: datetime, px: float, complete=True):
    p = {"o": str(px), "h": str(px + 1), "l": str(px - 1), "c": str(px)}
    return {"time": t.strftime("%Y-%m-%dT%H:%M:%S.000000000Z"), "volume": 5,
            "complete": complete, "bid": p, "ask": {k: str(float(v) + 0.5) for k, v in p.items()},
            "mid": {k: str(float(v) + 0.25) for k, v in p.items()}}


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(oanda_mod, "MAX_COUNT", 3)
    monkeypatch.setattr(oanda_mod.LIMITER, "interval", 0)


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler),
                        headers={"Authorization": f"Bearer {TOKEN}"})


def test_paginates_filters_end_and_incomplete():
    t0 = datetime(2024, 1, 2, 10, 0, tzinfo=UTC)
    calls = []

    def handler(req):
        frm = datetime.fromisoformat(req.url.params["from"].replace("Z", "+00:00"))
        calls.append(frm)
        assert req.url.params["price"] == "BAM" and req.url.params["granularity"] == "M1"
        if frm == t0:
            return httpx.Response(200, json={"candles": [
                _candle(t0 + timedelta(minutes=i), 100 + i) for i in range(3)]})
        if frm > t0 + timedelta(minutes=3):
            return httpx.Response(200, json={"candles": []})
        return httpx.Response(200, json={"candles": [
            _candle(t0 + timedelta(minutes=3), 103),
            _candle(t0 + timedelta(minutes=4), 104),
            _candle(t0 + timedelta(minutes=5), 105, complete=False)]})

    p = OandaProvider(token=TOKEN, environment="practice")
    df = p.candles(_client(handler), "EUR_USD", t0, t0 + timedelta(minutes=10))
    # second page starts right after the last candle; third returns nothing -> stop
    assert calls == [t0, t0 + timedelta(minutes=3), t0 + timedelta(minutes=6)]
    assert df.height == 5  # incomplete candle dropped
    r = df.row(0, named=True)
    assert (r["bid_close"], r["ask_close"], r["mid_close"]) == (100.0, 100.5, 100.25)
    assert df["ts"].dtype.time_zone == "UTC"


def test_no_progress_raises_instead_of_looping():
    t0 = datetime(2024, 1, 2, 10, 0, tzinfo=UTC)

    def handler(req):  # always the same full page
        return httpx.Response(200, json={"candles": [
            _candle(t0 + timedelta(minutes=i), 100) for i in range(3)]})

    with pytest.raises(OandaError, match="no progress"):
        OandaProvider(token=TOKEN, environment="practice").candles(
            _client(handler), "EUR_USD", t0, t0 + timedelta(minutes=30))


def test_end_is_exclusive():
    t0 = datetime(2024, 1, 2, 10, 0, tzinfo=UTC)

    def handler(req):
        return httpx.Response(200, json={"candles": [
            _candle(t0 + timedelta(minutes=i), 100) for i in range(3)]})

    df = OandaProvider(token=TOKEN, environment="practice").candles(
        _client(handler), "EUR_USD", t0, t0 + timedelta(minutes=2))
    assert df["ts"].max() == t0 + timedelta(minutes=1)


def test_errors_do_not_leak_token():
    def handler(req):
        return httpx.Response(401, json={"errorMessage": "Insufficient authorization"})

    p = OandaProvider(token=TOKEN, environment="practice")
    with pytest.raises(OandaError) as e:
        p.candles(_client(handler), "EUR_USD", datetime(2024, 1, 1, tzinfo=UTC),
                  datetime(2024, 1, 2, tzinfo=UTC))
    assert TOKEN not in str(e.value) and "Insufficient" in str(e.value)


def test_unconfigured_is_disconnected():
    p = OandaProvider(token=TOKEN, environment="practice")
    p._token = ""
    assert p.check_health().status.value == "disconnected"


def test_month_chunks():
    m = _months(datetime(2023, 11, 15, tzinfo=UTC), datetime(2024, 2, 1, tzinfo=UTC))
    assert [x.strftime("%Y-%m") for x in m] == ["2023-11", "2023-12", "2024-01"]
