"""Upcoming scheduled releases (FRED release calendar) -> economic_events with actual = NULL.

For each FRED release that has ingested indicators, future release dates come from
`fred/release/dates`. Reference periods are assigned in sequence after the newest published
period (step inferred from history: 1 month, 3 months...). The first upcoming event gets
previous_value = the latest value currently known (including revisions); a 'forecast' snapshot
records what was known at capture time. When the release happens, the FRED pipeline fills the
same row in (it never overwrites a published value).
"""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.universe import Universe
from app.ingestion.jobs import track_job
from app.models import EconomicEvent, EconomicEventSnapshot
from app.providers.macro.fred import FredProvider


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def _utc(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def _latest_known_value(session: Session, ev: EconomicEvent):
    """Newest value of an event as currently known (latest snapshot incl. revisions)."""
    snap = session.scalars(select(EconomicEventSnapshot)
                           .where(EconomicEventSnapshot.event_id == ev.event_id,
                                  EconomicEventSnapshot.actual_value.is_not(None))
                           .order_by(EconomicEventSnapshot.source_timestamp.desc())).first()
    return snap.actual_value if snap else ev.actual_value


def run_upcoming(session: Session, universe: Universe, horizon_days: int = 75) -> dict:
    now_utc = datetime.now(UTC)
    today = now_utc.date()
    fred = FredProvider()
    out: dict[str, list] = {}
    with track_job(session, "fred", "upcoming_calendar", {"horizon_days": horizon_days}) as st:
        ingested = {k for (k,) in session.execute(
            select(EconomicEvent.indicator_key).where(EconomicEvent.source == "fred").distinct())}
        releases = {universe.indicators[k].release for k in ingested if k in universe.indicators}
        created = updated = 0
        for rkey in sorted(releases):
            rel = universe.releases[rkey]
            data = fred._get("release/dates", release_id=rel.fred_release_id,
                             realtime_start=today.isoformat(), realtime_end="9999-12-31",
                             include_release_dates_with_no_data="true", sort_order="asc",
                             limit=50)
            dates = [date.fromisoformat(r["date"]) for r in data.get("release_dates", [])]
            dates = [d for d in dates if today <= d <= today + timedelta(days=horizon_days)]
            for ind in universe.indicators_for_release(rkey):
                if ind.key not in ingested:
                    continue
                # "Released" = release time has passed, whether or not a headline value could
                # be computed (e.g. y/y is undefined when its base month was never published).
                published = session.scalars(
                    select(EconomicEvent).where(EconomicEvent.indicator_key == ind.key,
                                                EconomicEvent.source == "fred",
                                                EconomicEvent.scheduled_release_time < now_utc)
                    .order_by(EconomicEvent.reference_period.desc()).limit(2)).all()
                if len(published) < 2:
                    continue
                last = published[0]
                step = (last.reference_period.year - published[1].reference_period.year) * 12 + \
                    last.reference_period.month - published[1].reference_period.month
                if step not in (1, 3):
                    continue  # weekly/irregular series: not scheduled here
                ref = last.reference_period
                for i, d in enumerate(dates):
                    ref = _add_months(ref, step)
                    ts = rel.scheduled_utc(d)
                    prev = _latest_known_value(session, last) if i == 0 else None
                    ev = session.scalar(select(EconomicEvent).where(
                        EconomicEvent.indicator_key == ind.key,
                        EconomicEvent.reference_period == ref, EconomicEvent.source == "fred"))
                    if ev is not None and (ev.actual_value is not None or
                                           _utc(ev.scheduled_release_time) <= now_utc):
                        continue  # already released: never touch
                    if ev is None:
                        ev = EconomicEvent(
                            provider_event_id=f"fred:{ind.fred_series_id}:{ref}",
                            indicator_key=ind.key, release_key=rkey, event_name=ind.name,
                            event_category=ind.category, country=ind.country,
                            currency=ind.currency, importance=ind.importance,
                            scheduled_release_time=ts, release_time_verified=False,
                            release_time_source="config", event_kind="scheduled_release",
                            reference_period=ref, unit=ind.unit, source="fred",
                            previous_value=prev, details={"status": "upcoming"})
                        session.add(ev)
                        session.flush()
                        created += 1
                    else:
                        ev.scheduled_release_time, ev.previous_value = ts, prev
                        ev.details = {**(ev.details or {}), "status": "upcoming"}
                        updated += 1
                    now = datetime.now(UTC).replace(microsecond=0)
                    exists = session.scalar(select(func.count()).select_from(
                        EconomicEventSnapshot).where(
                        EconomicEventSnapshot.event_id == ev.event_id,
                        EconomicEventSnapshot.snapshot_kind == "forecast",
                        EconomicEventSnapshot.previous_value == prev))
                    if not exists:
                        session.add(EconomicEventSnapshot(
                            event_id=ev.event_id, snapshot_kind="forecast",
                            source_timestamp=now, previous_value=prev, provider="fred",
                            ingestion_job_id=st.job_id,
                            raw={"scheduled_date": d.isoformat(), "consensus": None}))
                    out.setdefault(ind.key, []).append(
                        {"reference_period": ref.isoformat(), "release": ts.isoformat()})
        session.commit()
        st.rows_written = created + updated
        st.details = {"created": created, "updated": updated}
    return {"created": created, "updated": updated, "events": out}
