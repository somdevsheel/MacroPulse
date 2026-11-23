from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from app.event_engine.studies import aggregate, direction, is_reversal
from app.event_engine.windows import compute_windows

T = datetime(2024, 3, 12, 12, 30, tzinfo=UTC)


def _bars(closes: dict[int, float]) -> pl.DataFrame:
    """minute offset from T -> close; open=prev close, high/low = max/min(open, close)."""
    rows, prev = [], None
    for m in sorted(closes):
        c = closes[m]
        o = prev if prev is not None else c
        rows.append((T + timedelta(minutes=m), o, max(o, c), min(o, c), c))
        prev = c
    return pl.DataFrame(rows, schema=["ts", "open", "high", "low", "close"], orient="row")


def _w(res, label):
    return next(w for w in res if w.label == label)


def test_anchor_is_last_close_before_release_and_returns():
    closes = {m: 100.0 for m in range(-70, 0)}
    closes |= {0: 101.0, 1: 102.0, 2: 101.5, 3: 101.0, 4: 100.5}
    res = compute_windows(_bars(closes), T)
    post1, post5 = _w(res, "post_1m"), _w(res, "post_5m")
    assert post1.anchor_price == 100.0 and post1.return_pct == pytest.approx(1.0)
    assert post5.return_pct == pytest.approx(0.5)
    assert post5.mfe_pct == pytest.approx(2.0)  # initial direction up; best = 102
    assert post5.minutes_to_extreme == 1
    assert not post5.has_gaps


def test_release_minute_bar_is_post_not_pre():
    closes = {m: 100.0 for m in range(-70, 0)} | {0: 110.0}
    res = compute_windows(_bars(closes), T)
    assert _w(res, "pre_1m").return_pct == pytest.approx(0.0)
    assert _w(res, "post_1m").return_pct == pytest.approx(10.0)


def test_gaps_reported_not_filled():
    closes = {m: 100.0 for m in range(-70, 0)} | {0: 101.0, 14: 103.0}  # 13 missing minutes
    w = _w(compute_windows(_bars(closes), T), "post_15m")
    assert w.candle_count == 2 and w.expected_candle_count == 15 and w.has_gaps
    assert w.return_pct == pytest.approx(3.0)


def test_stale_anchor_rejected():
    closes = {-30: 100.0, 0: 101.0}  # last pre-release price 29 minutes old
    w = _w(compute_windows(_bars(closes), T), "post_1m")
    assert w.anchor_price is None and w.return_pct is None


def test_direction_and_reversal_definitions():
    assert direction(0.04, 0.05) == "neutral" and direction(-0.2, 0.05) == "bearish"
    assert is_reversal(0.3, -0.2, 0.05) is True
    assert is_reversal(0.3, 0.2, 0.05) is False
    assert is_reversal(0.01, -0.5, 0.05) is None  # no clear initial move


def test_aggregate_stats():
    events = [
        {"post_5m": {"return_pct": 0.2}, "post_60m": {"return_pct": -0.3, "realized_vol": 2},
         "pre_60m": {"return_pct": 0.0, "realized_vol": 1}},
        {"post_5m": {"return_pct": 0.2}, "post_60m": {"return_pct": 0.4, "realized_vol": 3},
         "pre_60m": {"return_pct": 0.0, "realized_vol": 1}},
        {"post_5m": {"return_pct": -0.01}, "post_60m": {"return_pct": 0.01, "realized_vol": 1},
         "pre_60m": {"return_pct": 0.0, "realized_vol": 1}},
    ]
    s = {x.window: x for x in aggregate(events, 0.05)}["post_60m"]
    assert s.n == 3 and s.median_pct == pytest.approx(0.01)
    assert (s.pct_bullish, s.pct_bearish) == (pytest.approx(100 / 3), pytest.approx(100 / 3))
    assert s.reversal_n == 2 and s.reversal_frequency == pytest.approx(50.0)
    assert s.avg_vol_ratio == pytest.approx(2.0)  # median of [2, 3, 1]
    assert (s.max_positive_pct, s.max_negative_pct) == (0.4, -0.3)
