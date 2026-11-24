"""Milestone-1 API: events, price bars around events, reaction studies, similar events."""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.universe import get_universe
from app.database.session import get_session
from app.event_engine.service import reaction_study, similar_events
from app.models import EconomicEvent
from app.services.price_store import available_sources, load_bars

router = APIRouter(prefix="/api/v1")
DB = Annotated[Session, Depends(get_session)]


def _utc(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def _f(x):
    return None if x is None else float(x)


def resolve_provider(instrument: str, provider: str | None) -> str:
    srcs = [s for s in available_sources() if s["instrument"] == instrument and
            s["timeframe"] == "1m"]
    if provider:
        if not any(s["provider"] == provider for s in srcs):
            raise HTTPException(404, f"no 1m data for {instrument} from {provider}")
        return provider
    if not srcs:
        raise HTTPException(404, f"no price data ingested for {instrument}")
    names = [s["provider"] for s in srcs]
    # Prefer OANDA (UTC timestamps, bid/ask, live-updatable) when it covers the instrument.
    return "oanda" if "oanda" in names else names[0]


def _event_json(e: EconomicEvent) -> dict:
    return {
        "event_id": e.event_id, "indicator": e.indicator_key, "name": e.event_name,
        "category": e.event_category, "importance": e.importance, "kind": e.event_kind,
        "release_time": _utc(e.scheduled_release_time).isoformat(),
        "release_time_source": e.release_time_source,
        "release_time_verified": e.release_time_verified,
        "reference_period": e.reference_period.isoformat(), "unit": e.unit,
        "actual": _f(e.actual_value), "previous": _f(e.previous_value),
        "revised_previous": _f(e.revised_previous_value),
        "consensus": _f(e.consensus_forecast), "consensus_source": e.consensus_source,
        "source": e.source, "details": e.details,
    }


@router.get("/indicators")
def indicators() -> list[dict]:
    u = get_universe()
    return [{"key": i.key, "name": i.name, "category": i.category, "importance": i.importance,
             "priority": i.priority, "unit": i.unit, "release": i.release,
             "provider": u.releases[i.release].provider} for i in u.indicators.values()]


@router.get("/price-sources")
def price_sources() -> list[dict]:
    return available_sources()


@router.get("/events")
def list_events(db: DB, indicator: str | None = None, start: date | None = None,
                end: date | None = None, limit: int = Query(500, le=5000)) -> list[dict]:
    q = select(EconomicEvent).order_by(EconomicEvent.scheduled_release_time.desc())
    if indicator:
        q = q.where(EconomicEvent.indicator_key == indicator)
    if start:
        q = q.where(EconomicEvent.scheduled_release_time >= datetime.combine(start,
                                                                              datetime.min.time(),
                                                                              UTC))
    if end:
        q = q.where(EconomicEvent.scheduled_release_time <
                    datetime.combine(end + timedelta(days=1), datetime.min.time(), UTC))
    return [_event_json(e) for e in db.scalars(q.limit(limit))]


@router.get("/events/{event_id}")
def get_event(event_id: int, db: DB) -> dict:
    e = db.get(EconomicEvent, event_id)
    if e is None:
        raise HTTPException(404, "event not found")
    t = _utc(e.scheduled_release_time)
    concurrent = db.scalars(select(EconomicEvent).where(
        EconomicEvent.scheduled_release_time == e.scheduled_release_time,
        EconomicEvent.event_id != event_id)).all()
    return _event_json(e) | {"concurrent": [_event_json(c) for c in concurrent
                                            if _utc(c.scheduled_release_time) == t]}


@router.get("/events/{event_id}/bars")
def event_bars(event_id: int, db: DB, instrument: str = "XAUUSD", provider: str | None = None,
               before_min: int = Query(60, ge=1, le=1440),
               after_min: int = Query(240, ge=1, le=1440)) -> dict:
    """1-minute bars around the release. `time` = UTC epoch seconds (bar open). Missing minutes
    are simply absent."""
    e = db.get(EconomicEvent, event_id)
    if e is None:
        raise HTTPException(404, "event not found")
    prov = resolve_provider(instrument, provider)
    t = _utc(e.scheduled_release_time)
    bars = load_bars(prov, instrument, t - timedelta(minutes=before_min),
                     t + timedelta(minutes=after_min))
    return {
        "event_id": event_id, "instrument": instrument, "provider": prov,
        "release_time": t.isoformat(), "release_epoch": int(t.timestamp()),
        "expected_bars": before_min + after_min, "bar_count": bars.height,
        "bars": [{"time": int(r["ts"].timestamp()), "open": r["open"], "high": r["high"],
                  "low": r["low"], "close": r["close"], "volume": r["volume"]}
                 for r in bars.iter_rows(named=True)],
    }


@router.get("/analysis/reactions")
def reactions(db: DB, indicator: str, instrument: str = "XAUUSD", provider: str | None = None,
              start: date | None = None, end: date | None = None,
              neutral_pct: float = Query(0.05, ge=0, le=5),
              min_coverage: float = Query(0.8, ge=0, le=1)) -> dict:
    if indicator not in get_universe().indicators:
        raise HTTPException(404, f"unknown indicator {indicator}")
    return reaction_study(db, indicator, instrument, resolve_provider(instrument, provider),
                          start, end, neutral_pct, min_coverage)


@router.get("/events/{event_id}/similar")
def similar(event_id: int, db: DB, instrument: str = "XAUUSD", provider: str | None = None,
            k: int = Query(10, ge=1, le=50)) -> dict:
    try:
        return similar_events(db, event_id, instrument, resolve_provider(instrument, provider), k)
    except KeyError:
        raise HTTPException(404, "event not found") from None


@router.get("/models")
def models(db: DB, run: str | None = None) -> dict:
    """Model registry for one training run (default: latest), grouped by task."""
    from app.models import ModelRegistry

    runs = sorted({v for (v,) in db.execute(select(ModelRegistry.version).distinct())},
                  reverse=True)
    if not runs:
        return {"runs": [], "run": None, "tasks": {}}
    run = run or runs[0]
    if run not in runs:
        raise HTTPException(404, f"unknown run {run}")
    tasks: dict[str, dict] = {}
    for m in db.scalars(select(ModelRegistry).where(ModelRegistry.version == run)
                        .order_by(ModelRegistry.model_id)):
        t = tasks.setdefault(m.target, {"task": m.target, "phase": m.phase, "models": []})
        metrics = m.metrics or {}
        t["models"].append({
            "model_id": m.model_id, "algorithm": m.algorithm, "status": m.status,
            "selected": metrics.get("selected", False),
            "beats_prior": metrics.get("beats_prior"),
            "vs_prior_walk_forward": metrics.get("vs_prior_walk_forward"),
            "walk_forward": metrics.get("walk_forward"), "validation": metrics.get("validation"),
            "test": metrics.get("test"), "per_fold": metrics.get("per_fold"),
            "calibration_p_bullish": metrics.get("calibration_p_bullish"),
            "feature_set_version": m.feature_set_version,
        })
    return {"runs": runs, "run": run, "tasks": tasks,
            "protocol": "expanding walk-forward by year 2012-2025 with 1-day embargo; fixed "
                        "split train<=2021 / validation 2022-23 / test 2024-25; selection on "
                        "validation only; 'beats prior' = paired-bootstrap 95% CI of the "
                        "walk-forward loss difference entirely below 0"}
