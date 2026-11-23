"""FRED -> bronze Parquet + macro_indicators + economic_events + economic_event_snapshots.

Idempotent: re-running inserts only rows that don't exist yet. Existing events are never
overwritten (original prints are immutable); new revisions are appended as snapshots.
"""

import logging
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.universe import Universe
from app.ingestion.fred_events import BuiltEvent, UnsupportedIndicator, build_events
from app.ingestion.jobs import track_job
from app.models import EconomicEvent, EconomicEventSnapshot, MacroIndicator
from app.providers.base import Observation
from app.providers.macro.fred import FredProvider

log = logging.getLogger(__name__)
LOOKBACK_DAYS = 400  # enough history for y/y and prior-period values at `start`


def write_bronze(obs: list[Observation], root: Path, series_id: str) -> Path:
    d = root / "macroeconomic_data" / "fred" / f"series={series_id}"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"fetched={datetime.now(UTC):%Y%m%dT%H%M%SZ}.parquet"
    pl.DataFrame([asdict(o) for o in obs], schema={
        "series_id": pl.Utf8, "observation_date": pl.Date, "value": pl.Decimal(38, 6),
        "realtime_start": pl.Date, "realtime_end": pl.Date,
    }).write_parquet(p)
    return p


def store_vintages(session: Session, obs: list[Observation], unit: str | None,
                   frequency: str | None) -> int:
    existing = set(session.execute(
        select(MacroIndicator.observation_date, MacroIndicator.realtime_start)
        .where(MacroIndicator.series_id == obs[0].series_id, MacroIndicator.source == "fred")
    ).all()) if obs else set()
    new = [
        MacroIndicator(series_id=o.series_id, observation_date=o.observation_date, value=o.value,
                       realtime_start=o.realtime_start, realtime_end=o.realtime_end, unit=unit,
                       frequency=frequency, source="fred")
        for o in obs if (o.observation_date, o.realtime_start) not in existing
    ]
    session.add_all(new)
    return len(new)


def store_events(session: Session, universe: Universe, built: list[BuiltEvent],
                 job_id: int | None) -> tuple[int, int]:
    n_events = n_snaps = 0
    for b in built:
        ind = universe.indicators[b.indicator_key]
        ev = session.scalar(select(EconomicEvent).where(
            EconomicEvent.indicator_key == b.indicator_key,
            EconomicEvent.reference_period == b.reference_period,
            EconomicEvent.source == "fred"))
        if ev is None:
            ev = EconomicEvent(
                provider_event_id=f"fred:{ind.fred_series_id}:{b.reference_period}",
                indicator_key=ind.key, release_key=ind.release, event_name=ind.name,
                event_category=ind.category, country=ind.country, currency=ind.currency,
                importance=ind.importance, scheduled_release_time=b.scheduled_release_time,
                actual_release_time=None,  # unverified intraday time; see release_time_verified
                release_time_verified=False, reference_period=b.reference_period,
                actual_value=b.actual_value, consensus_forecast=None, consensus_source=None,
                previous_value=b.previous_value, revised_previous_value=b.revised_previous_value,
                unit=ind.unit, source="fred",
            )
            session.add(ev)
            session.flush()
            n_events += 1
        have = set(session.scalars(select(EconomicEventSnapshot.source_timestamp).where(
            EconomicEventSnapshot.event_id == ev.event_id,
            EconomicEventSnapshot.provider == "fred")).all())
        have = {t.replace(tzinfo=UTC) if t.tzinfo is None else t for t in have}
        snaps = [EconomicEventSnapshot(
            event_id=ev.event_id, snapshot_kind="release",
            source_timestamp=b.scheduled_release_time, actual_value=b.actual_value,
            previous_value=b.previous_value, revised_previous_value=b.revised_previous_value,
            provider="fred", ingestion_job_id=job_id,
            raw={"release_date": b.release_date.isoformat(),
                 "in_fred_release_calendar": b.in_fred_release_calendar,
                 "release_time_reliable": b.time_reliable},
        )]
        release = universe.releases[ind.release]
        for r in b.revisions:
            snaps.append(EconomicEventSnapshot(
                event_id=ev.event_id, snapshot_kind="revision",
                # Vintage date is exact; intraday time is approximated with the release time.
                source_timestamp=release.scheduled_utc(r.vintage_date), actual_value=r.value,
                provider="fred", ingestion_job_id=job_id,
                raw={"vintage_date": r.vintage_date.isoformat(), "time_approximate": True},
            ))
        for s in snaps:
            if s.source_timestamp not in have:
                session.add(s)
                n_snaps += 1
    return n_events, n_snaps


def run_fred_events(session: Session, universe: Universe, provider: FredProvider,
                    indicator_keys: list[str], start: date, end: date, data_root: Path) -> dict:
    summary: dict = {}
    release_dates_cache: dict[int, set[date]] = {}
    for key in indicator_keys:
        ind = universe.indicators[key]
        rel = universe.releases[ind.release]
        params = {"indicator": key, "series": ind.fred_series_id, "start": str(start),
                  "end": str(end)}
        with track_job(session, "fred", "fred_events", params) as stats:
            try:
                if rel.provider != "fred" or not ind.fred_series_id:
                    raise UnsupportedIndicator(f"{key}: not a FRED indicator")
                if rel.key == "fomc_statement":
                    raise UnsupportedIndicator("FOMC needs the Fed calendar adapter")
            except UnsupportedIndicator as e:
                stats.warnings.append(str(e))
                summary[key] = {"skipped": str(e)}
                continue
            obs = list(provider.observations(ind.fred_series_id,
                                             start - timedelta(days=LOOKBACK_DAYS), end))
            stats.rows_fetched = len(obs)
            write_bronze(obs, data_root / "bronze", ind.fred_series_id)
            n_vint = store_vintages(session, obs, ind.unit, None)
            if rel.fred_release_id not in release_dates_cache:
                release_dates_cache[rel.fred_release_id] = set(
                    provider.release_dates(rel.fred_release_id, start - timedelta(days=60), end))
            built, warns = build_events(ind, rel, obs, release_dates_cache[rel.fred_release_id],
                                        start, end)
            stats.warnings.extend(warns)
            n_ev, n_sn = store_events(session, universe, built, stats.job_id)
            session.commit()
            stats.rows_written = n_ev + n_sn + n_vint
            stats.details = {"events_new": n_ev, "snapshots_new": n_sn, "vintages_new": n_vint,
                             "events_built": len(built)}
            summary[key] = stats.details | {"warnings": len(warns)}
    return summary
