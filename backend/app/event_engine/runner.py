"""Compute synchronized_event_windows for all events x one price source.

Only events whose release time is established (release_time_source != 'unknown') are processed.
Re-running replaces the rows for that provider/instrument (windows are derived data).
"""

from collections import defaultdict
from datetime import UTC
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.universe import Universe
from app.event_engine.windows import MAX_AFTER, MAX_BEFORE, compute_windows
from app.ingestion.jobs import track_job
from app.models import EconomicEvent, MarketInstrument, SynchronizedEventWindow
from app.services.price_store import load_windows


def _d(x: float | None) -> Decimal | None:
    return None if x is None else Decimal(repr(round(x, 10)))


def _utc(ts):
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def seed_instruments(session: Session, universe: Universe) -> dict[str, int]:
    have = {i.symbol: i.instrument_id for i in session.scalars(select(MarketInstrument))}
    for sym, d in universe.instruments.items():
        if sym not in have:
            inst = MarketInstrument(symbol=sym, display_name=d.display, asset_class=d.asset_class,
                                    base_currency=d.base, quote_currency=d.quote,
                                    pip_size=Decimal(str(d.pip_size)),
                                    price_precision=d.price_precision)
            session.add(inst)
            session.flush()
            have[sym] = inst.instrument_id
    session.commit()
    return have


def run_windows(session: Session, universe: Universe, provider: str, instrument: str) -> dict:
    with track_job(session, "event_engine", "event_windows",
                   {"provider": provider, "instrument": instrument}) as stats:
        inst_id = seed_instruments(session, universe)[instrument]
        events = session.scalars(select(EconomicEvent).where(
            EconomicEvent.release_time_source != "unknown")).all()
        by_time = defaultdict(list)
        for e in events:
            by_time[_utc(e.scheduled_release_time)].append(e.event_id)
        anchors = sorted(by_time)
        bars = load_windows(provider, instrument, anchors, MAX_BEFORE, MAX_AFTER)
        stats.rows_fetched = len(events)

        session.execute(delete(SynchronizedEventWindow).where(
            SynchronizedEventWindow.instrument_id == inst_id,
            SynchronizedEventWindow.provider == provider))
        rows, no_data = [], 0
        for e in events:
            t = _utc(e.scheduled_release_time)
            b = bars.get(t)
            if b is None or b.height == 0:
                no_data += 1
                continue
            concurrent = [i for i in by_time[t] if i != e.event_id]
            for w in compute_windows(b, t):
                rows.append(SynchronizedEventWindow(
                    event_id=e.event_id, instrument_id=inst_id, provider=provider,
                    release_ts=t, window_label=w.label, window_start=w.start, window_end=w.end,
                    anchor_price=_d(w.anchor_price), end_price=_d(w.end_price),
                    return_pct=_d(w.return_pct), abs_move=_d(w.abs_move), high=_d(w.high),
                    low=_d(w.low), mfe_pct=_d(w.mfe_pct), mae_pct=_d(w.mae_pct),
                    realized_vol=_d(w.realized_vol), minutes_to_extreme=w.minutes_to_extreme,
                    candle_count=w.candle_count, expected_candle_count=w.expected_candle_count,
                    has_gaps=w.has_gaps, concurrent_event_ids=concurrent or None,
                    details={k: (round(v, 8) if isinstance(v, float) else v)
                             for k, v in w.details.items()} or None,
                ))
        session.add_all(rows)
        session.commit()
        stats.rows_written = len(rows)
        stats.details = {"events": len(events), "events_without_price_data": no_data,
                         "windows": len(rows)}
        return stats.details
