"""Historical base-rate pre-release prediction + post-event evaluation.

This is the honest default predictor: none of the trained ML models beat it out of sample
(docs/ARCHITECTURE.md §8). For an upcoming event it reports what happened after earlier
releases of the same type, using ONLY events released before the prediction time.

Per horizon h in {15, 60} minutes, from earlier releases' price windows (headline indicator per
timestamp, coverage >= 80%):
  p_bullish / p_bearish / p_neutral  frequencies of r_h beyond +-NEUTRAL_PCT
  expected_return_pct                mean r_h
  expected_move                      median |r_h|, in percent
  expected_volatility                median realized vol of the post_h window (1m, not annualised)
  p_reversal (h=60 only)             share of clear +5m moves that had flipped sign by +60m
  p_breakout                         not estimated (no validated definition) -> NULL
  confidence                         1 - normalised entropy of the 3 probabilities. It measures
                                     how lopsided history is, NOT a probability of being right.
"""

import math
import statistics
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.event_engine.studies import is_reversal
from app.feature_engineering.dataset import HEADLINE, NEUTRAL_PCT, label
from app.models import (
    EconomicEvent,
    MarketInstrument,
    ModelPrediction,
    ModelRegistry,
    SynchronizedEventWindow,
)

MODEL_NAME, MODEL_VERSION = "historical_base_rate", "v1"
HORIZONS = (15, 60)
MIN_HISTORY = 20


class PredictionError(Exception):
    pass


def _utc(ts):
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def _d(x):
    return None if x is None else Decimal(repr(round(float(x), 8)))


def registry_row(session: Session) -> ModelRegistry:
    m = session.scalar(select(ModelRegistry).where(ModelRegistry.model_name == MODEL_NAME,
                                                   ModelRegistry.version == MODEL_VERSION))
    if m is None:
        m = ModelRegistry(model_name=MODEL_NAME, version=MODEL_VERSION,
                          algorithm="historical_base_rate", phase="pre_release",
                          target="direction_15m,direction_60m", feature_set_version="none",
                          hyperparameters={"neutral_pct": NEUTRAL_PCT, "min_coverage": 0.8,
                                           "min_history": MIN_HISTORY},
                          status="baseline")
        session.add(m)
        session.flush()
    return m


def _history(session: Session, event: EconomicEvent, inst_id: int, provider: str,
             as_of: datetime) -> list[dict[str, dict]]:
    headline = HEADLINE.get(event.release_key, event.indicator_key)
    cutoff = min(as_of, _utc(event.scheduled_release_time))
    q = (select(EconomicEvent.event_id, SynchronizedEventWindow)
         .join(SynchronizedEventWindow,
               SynchronizedEventWindow.event_id == EconomicEvent.event_id)
         .where(EconomicEvent.indicator_key == headline,
                EconomicEvent.release_time_source != "unknown",
                EconomicEvent.scheduled_release_time < cutoff,
                SynchronizedEventWindow.instrument_id == inst_id,
                SynchronizedEventWindow.provider == provider))
    by_ev: dict[int, dict] = {}
    for eid, w in session.execute(q).all():
        cov = w.candle_count / w.expected_candle_count if w.expected_candle_count else 0
        if w.return_pct is not None and cov >= 0.8:
            by_ev.setdefault(eid, {})[w.window_label] = {
                "r": float(w.return_pct),
                "vol": float(w.realized_vol) if w.realized_vol is not None else None}
    return list(by_ev.values())


def base_rate(history: list[dict[str, dict]], horizon: int) -> dict | None:
    key = f"post_{horizon}m"
    rs = [h[key]["r"] for h in history if key in h]
    if len(rs) < MIN_HISTORY:
        return None
    labels = [label(r, NEUTRAL_PCT) for r in rs]
    n = len(rs)
    p = {c: labels.count(v) / n for c, v in (("bullish", 1), ("bearish", -1), ("neutral", 0))}
    ent = -sum(x * math.log(x) for x in p.values() if x > 0) / math.log(3)
    vols = [h[key]["vol"] for h in history if key in h and h[key]["vol"] is not None]
    out = {"n": n, **{f"p_{k}": v for k, v in p.items()},
           "expected_return_pct": statistics.fmean(rs),
           "expected_move_pct": statistics.median(abs(r) for r in rs),
           "expected_volatility": statistics.median(vols) if vols else None,
           "confidence": 1 - ent, "p_reversal": None}
    if horizon == 60:
        revs = [r for h in history
                if (r := is_reversal(h.get("post_5m", {}).get("r"), h.get(key, {}).get("r"),
                                     NEUTRAL_PCT)) is not None]
        out["p_reversal"] = sum(revs) / len(revs) if revs else None
    return out


def predict_pre_release(session: Session, event_id: int, instrument: str, provider: str,
                        now: datetime | None = None) -> list[ModelPrediction]:
    now = (now or datetime.now(UTC)).replace(microsecond=0)
    ev = session.get(EconomicEvent, event_id)
    if ev is None:
        raise PredictionError("event not found")
    if now >= _utc(ev.scheduled_release_time):
        raise PredictionError("pre-release predictions can only be made before the release")
    inst = session.scalar(select(MarketInstrument).where(MarketInstrument.symbol == instrument))
    if inst is None:
        raise PredictionError(f"unknown instrument {instrument}")
    hist = _history(session, ev, inst.instrument_id, provider, now)
    model = registry_row(session)
    preds = []
    for h in HORIZONS:
        br = base_rate(hist, h)
        if br is None:
            continue
        preds.append(ModelPrediction(
            event_id=ev.event_id, instrument_id=inst.instrument_id, model_id=model.model_id,
            phase="pre_release", horizon_minutes=h, prediction_ts=now, features_as_of=now,
            p_bullish=_d(br["p_bullish"]), p_bearish=_d(br["p_bearish"]),
            p_neutral=_d(br["p_neutral"]), expected_return_pct=_d(br["expected_return_pct"]),
            expected_move=_d(br["expected_move_pct"]),
            expected_volatility=_d(br["expected_volatility"]), p_reversal=_d(br["p_reversal"]),
            p_breakout=None, confidence=_d(br["confidence"]),
            similar_event_ids=None))
    if not preds:
        raise PredictionError(f"fewer than {MIN_HISTORY} earlier releases with price data")
    session.add_all(preds)
    session.commit()
    return preds


def evaluate_pending(session: Session) -> dict:
    """Fill realised outcomes for predictions whose event windows now exist. Prediction columns
    are never modified."""
    pending = session.scalars(select(ModelPrediction).where(
        ModelPrediction.evaluated_at.is_(None))).all()
    done = waiting = 0
    for p in pending:
        w = session.scalar(select(SynchronizedEventWindow).where(
            SynchronizedEventWindow.event_id == p.event_id,
            SynchronizedEventWindow.instrument_id == p.instrument_id,
            SynchronizedEventWindow.window_label == f"post_{p.horizon_minutes}m"))
        cov = w.candle_count / w.expected_candle_count if w and w.expected_candle_count else 0
        if w is None or w.return_pct is None or cov < 0.8:
            waiting += 1
            continue
        r = float(w.return_pct)
        p.realized_return_pct = _d(r)
        p.realized_direction = {1: "bullish", -1: "bearish", 0: "neutral"}[label(r, NEUTRAL_PCT)]
        p.evaluated_at = datetime.now(UTC)
        done += 1
    session.commit()
    return {"evaluated": done, "waiting_for_price_data": waiting}
