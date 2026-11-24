"""Live calendar, pre-release predictions and data-management endpoints."""

import statistics
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated

import polars as pl
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.analysis import resolve_provider
from app.core.config import get_settings
from app.core.universe import get_universe
from app.database.session import get_session
from app.feature_engineering.dataset import HEADLINE
from app.models import (
    EconomicEvent,
    IngestionJob,
    MarketInstrument,
    ModelPrediction,
    ModelRegistry,
    SynchronizedEventWindow,
)
from app.prediction_engine.base_rate import PredictionError, predict_pre_release
from app.services.price_store import available_sources, scan_bars

router = APIRouter(prefix="/api/v1")
DB = Annotated[Session, Depends(get_session)]


def _utc(ts):
    return ts if ts is None or ts.tzinfo else ts.replace(tzinfo=UTC)


def _f(x):
    return None if x is None else float(x)


def _pred_json(p: ModelPrediction, model: ModelRegistry | None) -> dict:
    return {
        "prediction_id": p.prediction_id, "event_id": p.event_id, "phase": p.phase,
        "horizon_minutes": p.horizon_minutes, "prediction_ts": _utc(p.prediction_ts).isoformat(),
        "model": f"{model.model_name}:{model.version}" if model else None,
        "p_bullish": _f(p.p_bullish), "p_bearish": _f(p.p_bearish),
        "p_neutral": _f(p.p_neutral), "expected_return_pct": _f(p.expected_return_pct),
        "expected_move_pct": _f(p.expected_move), "expected_volatility": _f(p.expected_volatility),
        "p_reversal": _f(p.p_reversal), "p_breakout": _f(p.p_breakout),
        "confidence": _f(p.confidence),
        "realized_return_pct": _f(p.realized_return_pct),
        "realized_direction": p.realized_direction,
        "evaluated_at": _utc(p.evaluated_at).isoformat() if p.evaluated_at else None,
    }


def _historical_vol(db: Session, indicator: str, inst_id: int) -> dict:
    rows = db.execute(
        select(SynchronizedEventWindow.window_label, SynchronizedEventWindow.return_pct,
               SynchronizedEventWindow.realized_vol, SynchronizedEventWindow.candle_count,
               SynchronizedEventWindow.expected_candle_count, SynchronizedEventWindow.event_id)
        .join(EconomicEvent, EconomicEvent.event_id == SynchronizedEventWindow.event_id)
        .where(EconomicEvent.indicator_key == indicator,
               SynchronizedEventWindow.instrument_id == inst_id,
               SynchronizedEventWindow.window_label.in_(["pre_15m", "post_15m"]))).all()
    per = defaultdict(dict)
    for lbl, r, v, c, e, eid in rows:
        if r is not None and e and c / e >= 0.8:
            per[eid][lbl] = (abs(float(r)), float(v) if v is not None else None)
    moves = [d["post_15m"][0] for d in per.values() if "post_15m" in d]
    ratios = [d["post_15m"][1] / d["pre_15m"][1] for d in per.values()
              if "post_15m" in d and "pre_15m" in d and d["post_15m"][1] and d["pre_15m"][1]]
    return {"n": len(moves),
            "median_abs_move_15m_pct": statistics.median(moves) if moves else None,
            "median_vol_ratio_15m": statistics.median(ratios) if ratios else None}


@router.get("/calendar")
def calendar(db: DB, days_back: int = Query(7, ge=0, le=365),
             days_ahead: int = Query(45, ge=0, le=365), instrument: str = "XAUUSD") -> dict:
    now = datetime.now(UTC)
    u = get_universe()
    evs = db.scalars(select(EconomicEvent).where(
        EconomicEvent.scheduled_release_time >= now - timedelta(days=days_back),
        EconomicEvent.scheduled_release_time <= now + timedelta(days=days_ahead))
        .order_by(EconomicEvent.scheduled_release_time)).all()
    inst = db.scalar(select(MarketInstrument).where(MarketInstrument.symbol == instrument))
    with_data = {s["instrument"] for s in available_sources() if s["timeframe"] == "1m"}
    vol_cache: dict[str, dict] = {}
    out = []
    for e in evs:
        t = _utc(e.scheduled_release_time)
        headline = HEADLINE.get(e.release_key, e.indicator_key)
        if inst and headline not in vol_cache:
            vol_cache[headline] = _historical_vol(db, headline, inst.instrument_id)
        preds = db.scalars(select(ModelPrediction).where(
            ModelPrediction.event_id == e.event_id,
            ModelPrediction.instrument_id == (inst.instrument_id if inst else -1))
            .order_by(ModelPrediction.prediction_ts.desc())).all()
        latest = {}
        for p in preds:
            latest.setdefault(p.horizon_minutes, p)
        status = "released" if e.actual_value is not None else (
            "upcoming" if t > now else "awaiting_data")
        out.append({
            "event_id": e.event_id, "indicator": e.indicator_key, "name": e.event_name,
            "release": e.release_key, "category": e.event_category, "importance": e.importance,
            "kind": e.event_kind, "release_time": t.isoformat(),
            "release_time_source": e.release_time_source,
            "countdown_seconds": int((t - now).total_seconds()), "status": status,
            "reference_period": e.reference_period.isoformat(), "unit": e.unit,
            "actual": _f(e.actual_value), "previous": _f(e.previous_value),
            "revised_previous": _f(e.revised_previous_value),
            "consensus": _f(e.consensus_forecast), "is_headline": e.indicator_key == headline,
            "affected_instruments": [{"symbol": s, "display": d.display, "has_data": s in with_data}
                                     for s, d in u.instruments.items()],
            "historical_volatility": vol_cache.get(headline),
            "predictions": [_pred_json(p, db.get(ModelRegistry, p.model_id))
                            for p in latest.values()],
        })
    return {"now": now.isoformat(), "instrument": instrument, "events": out,
            "notes": ["consensus forecasts: not connected",
                      "predictions are historical base rates (no ML model beat them "
                      "out of sample)"]}


@router.post("/predictions/pre-release/{event_id}")
def create_pre_release(event_id: int, db: DB, instrument: str = "XAUUSD",
                       provider: str | None = None) -> dict:
    prov = resolve_provider(instrument, provider)
    try:
        preds = predict_pre_release(db, event_id, instrument, prov)
    except PredictionError as e:
        raise HTTPException(409, str(e)) from None
    return {"event_id": event_id, "instrument": instrument, "provider": prov,
            "predictions": [_pred_json(p, db.get(ModelRegistry, p.model_id)) for p in preds]}


@router.get("/predictions")
def list_predictions(db: DB, event_id: int | None = None,
                     limit: int = Query(200, le=2000)) -> list[dict]:
    q = select(ModelPrediction).order_by(ModelPrediction.prediction_ts.desc())
    if event_id is not None:
        q = q.where(ModelPrediction.event_id == event_id)
    return [_pred_json(p, db.get(ModelRegistry, p.model_id)) for p in db.scalars(q.limit(limit))]


@router.get("/data/status")
def data_status(db: DB) -> dict:
    prices = []
    for s in available_sources():
        lf = scan_bars(s["provider"], s["instrument"], s["timeframe"])
        st = lf.select(pl.col("ts").min().alias("first"), pl.col("ts").max().alias("last"),
                       pl.len().alias("bars")).collect().row(0, named=True)
        prices.append({**s, "first": st["first"].isoformat(), "last": st["last"].isoformat(),
                       "bars": st["bars"]})
    ev = db.execute(select(
        EconomicEvent.indicator_key, EconomicEvent.source, func.count(),
        func.min(EconomicEvent.scheduled_release_time),
        func.max(EconomicEvent.scheduled_release_time),
        func.count() - func.count(EconomicEvent.actual_value))
        .group_by(EconomicEvent.indicator_key, EconomicEvent.source)).all()
    last_actual = dict(db.execute(select(
        EconomicEvent.indicator_key, func.max(EconomicEvent.scheduled_release_time))
        .where(EconomicEvent.actual_value.is_not(None))
        .group_by(EconomicEvent.indicator_key)).all())
    events = [{"indicator": k, "source": s, "events": n, "first": _utc(a).isoformat(),
               "last": _utc(b).isoformat(), "without_actual": int(na or 0),
               "last_published": _utc(last_actual.get(k)).isoformat()
               if last_actual.get(k) else None} for k, s, n, a, b, na in ev]
    jobs = db.scalars(select(IngestionJob).order_by(IngestionJob.job_id.desc()).limit(40)).all()
    macro_p = get_settings().resolved_data_dir() / "silver" / "market_features" / \
        "macro_daily.parquet"
    macro = []
    if macro_p.exists():
        m = pl.read_parquet(macro_p).group_by("series_id").agg(
            pl.col("date").min().alias("first"), pl.col("date").max().alias("last"),
            pl.len().alias("rows")).sort("series_id")
        macro = [{**r, "first": r["first"].isoformat(), "last": r["last"].isoformat()}
                 for r in m.iter_rows(named=True)]
    return {
        "prices": prices, "events": sorted(events, key=lambda x: x["indicator"]),
        "macro_context": macro,
        "jobs": [{"job_id": j.job_id, "provider": j.provider_key, "type": j.job_type,
                  "status": j.status, "rows_fetched": j.rows_fetched,
                  "rows_written": j.rows_written, "error": j.error_message,
                  "started_at": _utc(j.started_at).isoformat() if j.started_at else None,
                  "finished_at": _utc(j.finished_at).isoformat() if j.finished_at else None}
                 for j in jobs],
        "failed_jobs_total": db.scalar(select(func.count()).select_from(IngestionJob)
                                       .where(IngestionJob.status == "failed")),
        "credentials": get_settings().provider_key_status(),
    }
