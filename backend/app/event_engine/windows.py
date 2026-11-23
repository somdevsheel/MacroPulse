"""Per-event price-window metrics around a release instant T (UTC).

Conventions (1-minute bars, `ts` = bar open):
  anchor price  = close of the last bar that opened before T (i.e. last price before release),
                  only if that bar is within ANCHOR_MAX_STALENESS of T; otherwise no anchor.
  pre_k window  = bars in [T-k, T).  return = anchor / close(last bar before T-k) - 1
  post_k window = bars in [T, T+k).  return = close(last bar in window) / anchor - 1
  initial direction = sign of the post_1m return (first minute after release).
  MFE / MAE (post windows) = largest excursion in / against the initial direction, from anchor,
                  using bar highs/lows.  max_up / max_down are reported direction-free in details.
  realized_vol  = sqrt(sum of squared 1-minute log returns) within the window, in percent
                  (not annualised).
  minutes_to_extreme = minutes from T to the bar with the largest |excursion| (post windows).
  coverage      = bars present / minutes in window. has_gaps = coverage < 1.
Missing bars are never filled; metrics are computed from what exists and coverage is reported.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import polars as pl

PRE_WINDOWS = {"pre_60m": 60, "pre_30m": 30, "pre_15m": 15, "pre_5m": 5, "pre_1m": 1}
POST_WINDOWS = {"post_1m": 1, "post_5m": 5, "post_15m": 15, "post_30m": 30, "post_60m": 60,
                "post_4h": 240}
ALL_WINDOWS = {**PRE_WINDOWS, **POST_WINDOWS}
ANCHOR_MAX_STALENESS = timedelta(minutes=5)
MAX_BEFORE = timedelta(minutes=max(PRE_WINDOWS.values()) + 10)
MAX_AFTER = timedelta(minutes=max(POST_WINDOWS.values()))


@dataclass
class WindowResult:
    label: str
    start: datetime
    end: datetime
    anchor_price: float | None
    end_price: float | None
    return_pct: float | None
    abs_move: float | None
    high: float | None
    low: float | None
    mfe_pct: float | None
    mae_pct: float | None
    realized_vol: float | None
    minutes_to_extreme: int | None
    candle_count: int
    expected_candle_count: int
    details: dict = field(default_factory=dict)

    @property
    def has_gaps(self) -> bool:
        return self.candle_count < self.expected_candle_count


def _last_close_before(bars: pl.DataFrame, t: datetime, max_stale: timedelta | None = None
                       ) -> float | None:
    prior = bars.filter(pl.col("ts") < t)
    if prior.height == 0:
        return None
    row = prior.row(-1, named=True)
    # A bar opening at ts covers [ts, ts+1m); it is "before t" when ts+1m <= t.
    if row["ts"] + timedelta(minutes=1) > t:
        return None
    if max_stale is not None and t - (row["ts"] + timedelta(minutes=1)) > max_stale:
        return None
    return row["close"]


def _rvol(closes: list[float]) -> float | None:
    if len(closes) < 2:
        return None
    s = sum(math.log(b / a) ** 2 for a, b in zip(closes, closes[1:], strict=False) if a > 0)
    return math.sqrt(s) * 100


def compute_windows(bars: pl.DataFrame, release: datetime) -> list[WindowResult]:
    """bars: 1m bars (ts, open, high, low, close) covering [release-70m, release+4h)."""
    bars = bars.sort("ts")
    anchor = _last_close_before(bars, release, ANCHOR_MAX_STALENESS)
    first_min = bars.filter((pl.col("ts") >= release) &
                            (pl.col("ts") < release + timedelta(minutes=1)))
    init_dir = 0
    if anchor and first_min.height:
        d = first_min["close"][0] - anchor
        init_dir = 1 if d > 0 else (-1 if d < 0 else 0)

    out = []
    for label, k in PRE_WINDOWS.items():
        w0 = release - timedelta(minutes=k)
        win = bars.filter((pl.col("ts") >= w0) & (pl.col("ts") < release))
        start_px = _last_close_before(bars, w0, ANCHOR_MAX_STALENESS)
        ret = (anchor / start_px - 1) * 100 if anchor and start_px else None
        closes = ([start_px] if start_px else []) + win["close"].to_list()
        out.append(WindowResult(
            label, w0, release, start_px, anchor, ret,
            (anchor - start_px) if anchor and start_px else None,
            win["high"].max() if win.height else None, win["low"].min() if win.height else None,
            None, None, _rvol(closes), None, win.height, k,
        ))

    for label, k in POST_WINDOWS.items():
        w1 = release + timedelta(minutes=k)
        win = bars.filter((pl.col("ts") >= release) & (pl.col("ts") < w1))
        if not anchor or win.height == 0:
            out.append(WindowResult(label, release, w1, anchor, None, None, None, None, None,
                                    None, None, None, None, win.height, k,
                                    {"initial_direction": init_dir}))
            continue
        end_px = win["close"][-1]
        hi, lo = win["high"].max(), win["low"].min()
        up, down = (hi / anchor - 1) * 100, (lo / anchor - 1) * 100
        direction = init_dir or 1
        mfe = up if direction > 0 else -down
        mae = -down if direction > 0 else up
        exc = win.with_columns(pl.max_horizontal((pl.col("high") / anchor - 1).abs(),
                                                 (pl.col("low") / anchor - 1).abs()).alias("x"))
        t_ext = exc.row(exc["x"].arg_max(), named=True)["ts"]
        out.append(WindowResult(
            label, release, w1, anchor, end_px, (end_px / anchor - 1) * 100, end_px - anchor,
            hi, lo, mfe, mae, _rvol([anchor] + win["close"].to_list()),
            int((t_ext - release).total_seconds() // 60), win.height, k,
            {"initial_direction": init_dir, "max_up_pct": up, "max_down_pct": down},
        ))
    return out
