"""Point-in-time feature/target dataset: one row per release timestamp x instrument.

Why per timestamp: indicators released together (CPI m/m, y/y, core...) share a single market
reaction. Counting them as separate samples would duplicate targets and inflate results.

Availability (the information cutoff, `as_of`):
  pre_release   as_of = T - 1 minute. Uses: previous values known before T, bars before T,
                daily macro observations dated before T's New York date, and statistics over
                EARLIER events only.
  post_release  as_of = T + 5 minutes. Adds: actual values, revisions, and bars in [T, T+5m).
Targets:
  pre:   r_15m, r_60m = return from the pre-release anchor to T+15m / T+60m (percent)
  post:  r_5_15m, r_5_60m = return from the T+5m price to T+15m / T+60m (percent)
  abs_r_60m = |r_60m| (event volatility proxy)
Class labels: +1 bullish / 0 neutral / -1 bearish with a +-NEUTRAL_PCT band.
"""

import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EconomicEvent, MarketInstrument, SynchronizedEventWindow
from app.services.price_store import scan_bars

FEATURE_SET_VERSION = "v1"
NEUTRAL_PCT = 0.05
NY = ZoneInfo("America/New_York")
# Headline indicator per release, used for value-based features.
HEADLINE = {"cpi": "cpi_mom", "employment_situation": "nfp",
            "personal_income_outlays": "core_pce_mom", "fomc_statement": "fomc_rate_upper"}
RELEASES = list(HEADLINE)
MACRO = ["DGS2", "DGS10", "DFII10", "VIXCLS", "DTWEXBGS"]

PRE_FEATURES = (
    [f"rel_{r}" for r in RELEASES]
    + ["hour_utc", "weekday", "prev_z", "prev_step_z",
       "pre_5m", "pre_15m", "pre_60m", "pre_60m_vol", "ret_24h", "ret_5d", "rvol_5d_hourly",
       "DGS2", "DGS10", "DFII10", "VIXCLS", "d5_DGS2", "d5_DGS10", "d5_DFII10", "d5_VIXCLS",
       "d5_DTWEXBGS_pct", "hist_abs_r15", "hist_n"]
)
POST_FEATURES = PRE_FEATURES + ["delta_z", "revision_z", "post_1m", "post_5m", "post_5m_vol"]


def _utc(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def label(r: float | None, thr: float = NEUTRAL_PCT) -> int | None:
    if r is None or (isinstance(r, float) and math.isnan(r)):
        return None
    return 1 if r > thr else (-1 if r < -thr else 0)


class _Expanding:
    """Running mean/std over values seen so far (strictly past)."""

    def __init__(self):
        self.vals: list[float] = []

    def z(self, x: float | None, min_n: int = 6) -> float | None:
        if x is None or len(self.vals) < min_n:
            return None
        mu = sum(self.vals) / len(self.vals)
        sd = math.sqrt(sum((v - mu) ** 2 for v in self.vals) / (len(self.vals) - 1))
        return (x - mu) / sd if sd > 0 else 0.0

    def mean(self) -> float | None:
        return sum(self.vals) / len(self.vals) if self.vals else None

    def add(self, x: float | None):
        if x is not None:
            self.vals.append(x)


def _macro_features(macro: pl.DataFrame, t: datetime) -> dict:
    ny_date = t.astimezone(NY).date()
    out = {}
    for sid in MACRO:
        s = macro.filter((pl.col("series_id") == sid) & (pl.col("date") < ny_date)).tail(6)
        vals = s["value"].to_list()
        if not vals:
            continue
        if sid != "DTWEXBGS":
            out[sid] = vals[-1]
            if len(vals) == 6:
                out[f"d5_{sid}"] = vals[-1] - vals[0]
        elif len(vals) == 6 and vals[0]:
            out["d5_DTWEXBGS_pct"] = (vals[-1] / vals[0] - 1) * 100
    return out


def _hourly_features(h1: pl.DataFrame, t: datetime) -> dict:
    """From closed 1h bars only (bar open + 1h <= t)."""
    closed = h1.filter(pl.col("ts") + timedelta(hours=1) <= t).tail(121)
    if closed.height < 30:
        return {}
    c = closed["close"].to_list()
    last = c[-1]
    out = {}
    if len(c) >= 25:
        out["ret_24h"] = (last / c[-25] - 1) * 100
    if len(c) >= 121:
        out["ret_5d"] = (last / c[0] - 1) * 100
    rets = [math.log(b / a) for a, b in zip(c, c[1:], strict=False) if a > 0]
    if len(rets) > 10:
        mu = sum(rets) / len(rets)
        out["rvol_5d_hourly"] = math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1)) * 100
    return out


def build_dataset(session: Session, instrument: str, provider: str, data_root: Path,
                  neutral_pct: float = NEUTRAL_PCT) -> pl.DataFrame:
    inst_id = session.scalar(select(MarketInstrument.instrument_id)
                             .where(MarketInstrument.symbol == instrument))
    events = session.scalars(select(EconomicEvent).where(
        EconomicEvent.release_time_source != "unknown",
        EconomicEvent.release_key.in_(RELEASES))).all()
    windows = defaultdict(dict)
    for w in session.scalars(select(SynchronizedEventWindow).where(
            SynchronizedEventWindow.instrument_id == inst_id,
            SynchronizedEventWindow.provider == provider)):
        cov = w.candle_count / w.expected_candle_count if w.expected_candle_count else 0
        ok = w.return_pct is not None and cov >= 0.8
        windows[w.event_id][w.window_label] = {
            "r": float(w.return_pct) if ok else None,
            "vol": float(w.realized_vol) if ok and w.realized_vol is not None else None}

    # Group indicators released together.
    groups: dict[tuple, list[EconomicEvent]] = defaultdict(list)
    for e in events:
        groups[(_utc(e.scheduled_release_time), e.release_key)].append(e)

    macro_p = data_root / "silver" / "market_features" / "macro_daily.parquet"
    macro = pl.read_parquet(macro_p) if macro_p.exists() else pl.DataFrame(
        schema={"series_id": pl.Utf8, "date": pl.Date, "value": pl.Float64})
    h1 = scan_bars(provider, instrument, "1h").select("ts", "close").sort("ts").collect()

    hist_prev = defaultdict(_Expanding)  # past headline actuals per release
    hist_step = defaultdict(_Expanding)  # past changes in headline
    hist_delta = defaultdict(_Expanding)  # past (actual - previous)
    hist_rev = defaultdict(_Expanding)  # past (revised_previous - previous)
    hist_abs = defaultdict(_Expanding)  # past |r_15m|
    last_prev: dict[str, float] = {}

    rows = []
    for (t, rel), evs in sorted(groups.items(), key=lambda kv: kv[0][0]):
        head = next((e for e in evs if e.indicator_key == HEADLINE[rel]), None)
        w = windows.get(head.event_id if head else evs[0].event_id, {})

        def g(k: str, f: str = "r", w: dict = w):
            return (w.get(k) or {}).get(f)

        prev = float(head.previous_value) if head and head.previous_value is not None else None
        act = float(head.actual_value) if head and head.actual_value is not None else None
        rprev = float(head.revised_previous_value) if head and \
            head.revised_previous_value is not None else None

        row = {"release_ts": t, "release": rel, "event_id": head.event_id if head else None,
               "hour_utc": t.hour, "weekday": t.weekday(),
               **{f"rel_{r}": int(r == rel) for r in RELEASES},
               "prev_z": hist_prev[rel].z(prev),
               "prev_step_z": hist_step[rel].z(prev - last_prev[rel])
               if prev is not None and rel in last_prev else None,
               "pre_5m": g("pre_5m"), "pre_15m": g("pre_15m"), "pre_60m": g("pre_60m"),
               "pre_60m_vol": g("pre_60m", "vol"),
               "hist_abs_r15": hist_abs[rel].mean(), "hist_n": len(hist_abs[rel].vals),
               **_macro_features(macro, t), **_hourly_features(h1, t),
               # post-release extras
               "delta_z": hist_delta[rel].z(act - prev) if act is not None and prev is not None
               else None,
               "revision_z": hist_rev[rel].z(rprev - prev, min_n=3)
               if rprev is not None and prev is not None else (0.0 if prev is not None else None),
               "post_1m": g("post_1m"), "post_5m": g("post_5m"),
               "post_5m_vol": g("post_5m", "vol")}
        r15, r60, r5 = g("post_15m"), g("post_60m"), g("post_5m")
        row["r_15m"], row["r_60m"] = r15, r60
        row["abs_r_60m"] = abs(r60) if r60 is not None else None
        row["r_5_15m"] = ((1 + r15 / 100) / (1 + r5 / 100) - 1) * 100 \
            if r15 is not None and r5 is not None else None
        row["r_5_60m"] = ((1 + r60 / 100) / (1 + r5 / 100) - 1) * 100 \
            if r60 is not None and r5 is not None else None
        for k in ("r_15m", "r_60m", "r_5_15m", "r_5_60m"):
            row[f"y_{k}"] = label(row[k], neutral_pct)
        rows.append(row)

        # Update history AFTER the row is built: only past information feeds later rows.
        hist_prev[rel].add(act)
        if prev is not None and rel in last_prev:
            hist_step[rel].add(prev - last_prev[rel])
        if prev is not None:
            last_prev[rel] = prev
        if act is not None and prev is not None:
            hist_delta[rel].add(act - prev)
        if rprev is not None and prev is not None:
            hist_rev[rel].add(rprev - prev)
        if r15 is not None:
            hist_abs[rel].add(abs(r15))

    cols = ["release_ts", "release", "event_id"] + POST_FEATURES + [
        "r_15m", "r_60m", "abs_r_60m", "r_5_15m", "r_5_60m",
        "y_r_15m", "y_r_60m", "y_r_5_15m", "y_r_5_60m"]
    df = pl.DataFrame(rows, infer_schema_length=None)
    for c in cols:
        if c not in df.columns:
            df = df.with_columns(pl.lit(None, dtype=pl.Float64).alias(c))
    return df.select(cols).sort("release_ts")
