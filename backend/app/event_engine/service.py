"""Query layer for historical reaction analysis (used by the API and CLI).

Usability rule for a window: anchor price exists, and coverage (bars / minutes) >= min_coverage.
Events dropped by the rule are counted, not silently ignored.
"""

import math
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.event_engine.studies import DEFAULT_NEUTRAL_PCT, aggregate, direction, is_reversal
from app.models import EconomicEvent, MarketInstrument, SynchronizedEventWindow

DEFAULT_MIN_COVERAGE = 0.8


def _f(x):
    return None if x is None else float(x)


def _utc(ts):
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def event_rows(session: Session, indicator: str, instrument: str, provider: str,
               start: date | None = None, end: date | None = None,
               min_coverage: float = DEFAULT_MIN_COVERAGE) -> tuple[list[dict], dict]:
    q = (select(EconomicEvent, SynchronizedEventWindow)
         .join(SynchronizedEventWindow,
               SynchronizedEventWindow.event_id == EconomicEvent.event_id)
         .join(MarketInstrument,
               MarketInstrument.instrument_id == SynchronizedEventWindow.instrument_id)
         .where(EconomicEvent.indicator_key == indicator, MarketInstrument.symbol == instrument,
                SynchronizedEventWindow.provider == provider))
    if start:
        q = q.where(EconomicEvent.scheduled_release_time >= datetime.combine(start, datetime.min
                                                                              .time(), UTC))
    if end:
        q = q.where(EconomicEvent.scheduled_release_time <
                    datetime.combine(end + timedelta(days=1), datetime.min.time(), UTC))
    by_event: dict[int, dict] = {}
    dropped = 0
    for ev, w in session.execute(q).all():
        row = by_event.setdefault(ev.event_id, {
            "event_id": ev.event_id, "release_time": _utc(ev.scheduled_release_time).isoformat(),
            "reference_period": ev.reference_period.isoformat(),
            "actual": _f(ev.actual_value), "previous": _f(ev.previous_value),
            "revised_previous": _f(ev.revised_previous_value),
            "consensus": _f(ev.consensus_forecast),
            "release_time_source": ev.release_time_source,
            "concurrent_event_ids": w.concurrent_event_ids or [], "windows": {}})
        cov = w.candle_count / w.expected_candle_count if w.expected_candle_count else 0
        if w.anchor_price is None or w.return_pct is None or cov < min_coverage:
            dropped += 1
            continue
        row["windows"][w.window_label] = {
            "return_pct": _f(w.return_pct), "abs_move": _f(w.abs_move),
            "realized_vol": _f(w.realized_vol), "mfe_pct": _f(w.mfe_pct),
            "mae_pct": _f(w.mae_pct), "minutes_to_extreme": w.minutes_to_extreme,
            "coverage": round(cov, 3), "high": _f(w.high), "low": _f(w.low)}
    rows = sorted(by_event.values(), key=lambda r: r["release_time"])
    return rows, {"windows_dropped_low_coverage_or_no_anchor": dropped}


def reaction_study(session: Session, indicator: str, instrument: str, provider: str,
                   start: date | None = None, end: date | None = None,
                   neutral_pct: float = DEFAULT_NEUTRAL_PCT,
                   min_coverage: float = DEFAULT_MIN_COVERAGE) -> dict:
    rows, info = event_rows(session, indicator, instrument, provider, start, end, min_coverage)
    for r in rows:
        w = r["windows"]
        r["direction_post_15m"] = direction(w.get("post_15m", {}).get("return_pct"), neutral_pct)
        r["reversal_post_60m"] = is_reversal(w.get("post_5m", {}).get("return_pct"),
                                             w.get("post_60m", {}).get("return_pct"), neutral_pct)
        pre, post = w.get("pre_15m", {}).get("realized_vol"), w.get("post_15m", {}).get(
            "realized_vol")
        r["vol_ratio_15m"] = post / pre if post is not None and pre else None
    stats = [asdict(s) for s in aggregate([r["windows"] for r in rows], neutral_pct)]
    return {
        "indicator": indicator, "instrument": instrument, "provider": provider,
        "start": start.isoformat() if start else None, "end": end.isoformat() if end else None,
        "neutral_threshold_pct": neutral_pct, "min_coverage": min_coverage,
        "n_events": len(rows), **info, "stats": stats, "events": rows,
        "notes": ["consensus forecasts are not available from the configured providers; "
                  "'surprise' below is actual minus previous, not actual minus consensus"],
    }


def similar_events(session: Session, event_id: int, instrument: str, provider: str,
                   k: int = 10) -> dict:
    """Nearest earlier events of the same indicator (no look-ahead: only events released before
    the query event are candidates).

    Features (each z-scored over the candidate set):
      delta      = actual - previous  (surprise vs previous; consensus unavailable)
      pre_60m    = gold/fx return in the 60 minutes before release (market drift into the event)
      pre_vol    = realized vol of the 60 minutes before release
    Distance = Euclidean over available z-features; similarity = 1 / (1 + distance).
    For the query event's own features, `delta` uses its published actual (post-release view).
    """
    ev = session.get(EconomicEvent, event_id)
    if ev is None:
        raise KeyError(event_id)
    rows, _ = event_rows(session, ev.indicator_key, instrument, provider)
    t0 = _utc(ev.scheduled_release_time).isoformat()
    query = next((r for r in rows if r["event_id"] == event_id), None)
    cands = [r for r in rows if r["release_time"] < t0]

    def feats(r):
        delta = (r["actual"] - r["previous"]) if r["actual"] is not None and \
            r["previous"] is not None else None
        w = r["windows"]
        return {"delta": delta, "pre_60m": w.get("pre_60m", {}).get("return_pct"),
                "pre_vol": w.get("pre_60m", {}).get("realized_vol")}

    if query is None or not cands:
        return {"event_id": event_id, "method": "knn_euclidean_z", "matches": [],
                "reason": "no price windows for event" if query is None else "no earlier events"}
    qf = feats(query)
    cf = [(r, feats(r)) for r in cands]
    scales = {}
    for name in qf:
        vals = [f[name] for _, f in cf if f[name] is not None]
        if len(vals) > 2:
            mu = sum(vals) / len(vals)
            sd = math.sqrt(sum((v - mu) ** 2 for v in vals) / (len(vals) - 1))
            scales[name] = (mu, sd or 1.0)
    used = [n for n in qf if qf[n] is not None and n in scales]
    scored = []
    for r, f in cf:
        dims = [n for n in used if f[n] is not None]
        if len(dims) < len(used):
            continue
        dist = math.sqrt(sum(((qf[n] - f[n]) / scales[n][1]) ** 2 for n in dims))
        w = r["windows"]
        scored.append({
            "event_id": r["event_id"], "release_time": r["release_time"],
            "reference_period": r["reference_period"], "actual": r["actual"],
            "previous": r["previous"], "delta": f["delta"], "distance": round(dist, 4),
            "similarity": round(1 / (1 + dist), 4),
            "post_15m_pct": w.get("post_15m", {}).get("return_pct"),
            "post_60m_pct": w.get("post_60m", {}).get("return_pct"),
            "post_4h_pct": w.get("post_4h", {}).get("return_pct"),
            "minutes_to_extreme_60m": w.get("post_60m", {}).get("minutes_to_extreme"),
        })
    scored.sort(key=lambda x: x["distance"])
    return {"event_id": event_id, "method": "knn_euclidean_z", "features": used,
            "query_features": qf, "candidates": len(scored), "matches": scored[:k]}
