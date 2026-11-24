from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import app.models as m
from app.core.universe import load_universe
from app.database.base import Base
from app.ingestion.upcoming import run_upcoming
from app.prediction_engine.base_rate import (
    MIN_HISTORY,
    PredictionError,
    base_rate,
    evaluate_pending,
    predict_pre_release,
)

U = load_universe()
NOW = datetime.now(UTC).replace(microsecond=0)


@pytest.fixture
def s():
    e = create_engine("sqlite://")
    Base.metadata.create_all(e)
    with Session(e) as sess:
        yield sess


def _ev(s, ind, ref, ts, actual, **kw):
    i = U.indicators[ind]
    ev = m.EconomicEvent(indicator_key=ind, release_key=i.release, event_name=i.name,
                         event_category=i.category, importance=i.importance,
                         scheduled_release_time=ts, reference_period=ref, unit=i.unit,
                         source="fred", actual_value=actual, **kw)
    s.add(ev)
    s.flush()
    return ev


def test_upcoming_skips_released_event_without_value(s, monkeypatch):
    # Oct y/y was released last month but has no value (base month never published).
    _ev(s, "cpi_yoy", date(2026, 9, 1), NOW - timedelta(days=40), Decimal("3.0"))
    oct_ = _ev(s, "cpi_yoy", date(2026, 10, 1), NOW - timedelta(days=10), None)
    future = (NOW + timedelta(days=15)).date().isoformat()
    monkeypatch.setattr("app.providers.macro.fred.FredProvider._get",
                        lambda self, path, **kw: {"release_dates": [{"date": future}]})
    out = run_upcoming(s, U)
    assert out["events"]["cpi_yoy"][0]["reference_period"] == "2026-11-01"
    s.refresh(oct_)
    assert oct_.scheduled_release_time.replace(tzinfo=UTC) == NOW - timedelta(days=10)
    new = s.scalar(select(m.EconomicEvent).where(m.EconomicEvent.reference_period ==
                                                 date(2026, 11, 1)))
    assert new.actual_value is None and new.details["status"] == "upcoming"
    snaps = s.scalars(select(m.EconomicEventSnapshot).where(
        m.EconomicEventSnapshot.event_id == new.event_id)).all()
    assert [x.snapshot_kind for x in snaps] == ["forecast"]


def test_base_rate_frequencies_and_min_history():
    hist = [{"post_15m": {"r": 0.2, "vol": 0.1}, "post_5m": {"r": 0.1}, "post_60m": {"r": -0.2}}
            for _ in range(15)] + [{"post_15m": {"r": -0.2, "vol": 0.3}} for _ in range(5)]
    br = base_rate(hist, 15)
    assert br["n"] == 20 and br["p_bullish"] == 0.75 and br["p_bearish"] == 0.25
    assert br["expected_move_pct"] == pytest.approx(0.2)
    assert base_rate(hist[:MIN_HISTORY - 1], 15) is None


def _setup_history(s, n=25):
    inst = m.MarketInstrument(symbol="XAUUSD", display_name="XAU/USD", asset_class="metal",
                              base_currency="XAU", quote_currency="USD",
                              pip_size=Decimal("0.01"), price_precision=2)
    s.add(inst)
    s.flush()
    for i in range(n):
        t = NOW - timedelta(days=30 * (i + 2))
        ev = _ev(s, "cpi_mom", date(2020, 1, 1) + timedelta(days=31 * i), t, Decimal("0.2"))
        for lbl, r in (("post_15m", 0.3), ("post_60m", 0.1), ("post_5m", 0.2)):
            k = int(lbl.split("_")[1][:-1])
            s.add(m.SynchronizedEventWindow(
                event_id=ev.event_id, instrument_id=inst.instrument_id, provider="p",
                release_ts=t, window_label=lbl, window_start=t, window_end=t,
                return_pct=Decimal(str(r)), realized_vol=Decimal("0.1"), candle_count=k,
                expected_candle_count=k))
    s.flush()
    return inst


def test_predict_only_before_release_and_evaluate(s):
    inst = _setup_history(s)
    up = _ev(s, "cpi_mom", date(2026, 11, 1), NOW + timedelta(days=5), None)
    preds = predict_pre_release(s, up.event_id, "XAUUSD", "p", now=NOW)
    assert {p.horizon_minutes for p in preds} == {15, 60}
    p15 = next(p for p in preds if p.horizon_minutes == 15)
    assert float(p15.p_bullish) == 1.0 and p15.prediction_ts <= up.scheduled_release_time

    past = _ev(s, "cpi_mom", date(2026, 12, 1), NOW - timedelta(minutes=1), None)
    with pytest.raises(PredictionError):
        predict_pre_release(s, past.event_id, "XAUUSD", "p", now=NOW)

    assert evaluate_pending(s) == {"evaluated": 0, "waiting_for_price_data": 2}
    s.add(m.SynchronizedEventWindow(
        event_id=up.event_id, instrument_id=inst.instrument_id, provider="p",
        release_ts=up.scheduled_release_time, window_label="post_15m",
        window_start=up.scheduled_release_time, window_end=up.scheduled_release_time,
        return_pct=Decimal("-0.4"), candle_count=15, expected_candle_count=15))
    s.commit()
    assert evaluate_pending(s)["evaluated"] == 1
    s.refresh(p15)
    assert p15.realized_direction == "bearish" and float(p15.p_bullish) == 1.0  # untouched


def test_history_excludes_events_after_prediction_time(s):
    _setup_history(s, n=MIN_HISTORY)
    up = _ev(s, "cpi_mom", date(2026, 11, 1), NOW + timedelta(days=5), None)
    # Predicting "as of" a time before most history existed -> not enough data.
    with pytest.raises(PredictionError, match="fewer than"):
        predict_pre_release(s, up.event_id, "XAUUSD", "p", now=NOW - timedelta(days=400))
