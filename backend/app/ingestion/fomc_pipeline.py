"""FOMC decisions -> economic_events (indicator fomc_rate_upper).

Dates:  Federal Reserve calendar pages (FedCalendarProvider).
Value:  policy rate from FRED -- DFEDTAR (single target, to 2008-12-15) then DFEDTARU (upper bound).
        The series changes on D in some years and D+1 in others, so previous = last value before
        D and actual = first value after D.
Time:   statement times are not stated on the Fed's pages ("For immediate release"). Each era has
        a known set of possible statement times (allowed_times_et). The 1-minute gold spike at
        12:30 / 14:00 / 14:15 ET is then scored:
          - clear winner inside the allowed set  -> that minute, source=empirical_spike (verified)
          - clear winner OUTSIDE the allowed set -> conflict, source=unknown (excluded)
          - no clear winner, one allowed time    -> that time, source=config (unverified)
          - no clear winner, several allowed     -> source=unknown (excluded)
        Unscheduled meetings / conference calls -> source=unknown (the announcement is often on
        a different day/time than the call).
"""

import logging
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import polars as pl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.universe import Universe
from app.ingestion.jobs import track_job
from app.ingestion.tz_detect import spike_score
from app.models import EconomicEvent, EconomicEventSnapshot
from app.providers.economic.fed_calendar import FedCalendarProvider, FomcMeeting
from app.providers.macro.fred import FredProvider
from app.services.price_store import load_windows
from app.utils.timeutils import ny_local_to_utc

log = logging.getLogger(__name__)
CANDIDATE_TIMES_ET = [time(12, 30), time(14, 0), time(14, 15)]
STANDARD_SINCE_2013 = time(14, 0)


def allowed_times_et(d: date) -> list[time]:
    """Possible scheduled-statement times by era: ~2:15 pm until 2010; 12:30 pm (meetings with a
    press conference) or 2:15 pm in 2011-2012; 2:00 pm from January 2013."""
    if d < date(2011, 1, 1):
        return [time(14, 15)]
    if d < date(2013, 1, 1):
        return [time(12, 30), time(14, 15)]
    return [STANDARD_SINCE_2013]
SWITCH_TO_RANGE = date(2008, 12, 16)


def rate_series(fred: FredProvider, start: date, end: date) -> dict[date, Decimal]:
    out: dict[date, Decimal] = {}
    for sid, a, b in (("DFEDTAR", start, SWITCH_TO_RANGE - timedelta(days=1)),
                      ("DFEDTARU", SWITCH_TO_RANGE, end)):
        if a > b:
            continue
        for o in fred.observations(sid, a, b, all_vintages=False):
            if o.value is not None:
                out[o.observation_date] = o.value
    return out


def rate_around(rates: dict[date, Decimal], d: date) -> tuple[Decimal | None, Decimal | None]:
    """previous = last value strictly before D; actual = first value after D. The target series
    changes on D in some years and on D+1 in others, so D itself is ambiguous and skipped."""
    before = [k for k in rates if k < d]
    after = [k for k in rates if k > d]
    prev = rates[max(before)] if before else None
    actual = rates[min(after)] if after and (min(after) - d).days <= 7 else None
    return prev, actual


def detect_minute(bars_by_anchor: dict[datetime, pl.DataFrame], d: date,
                  min_score: float = 4.0, dominance: float = 2.0
                  ) -> tuple[time | None, dict[str, float]]:
    scores = {}
    for t in CANDIDATE_TIMES_ET:
        anchor = ny_local_to_utc(d, t)
        bars = bars_by_anchor.get(anchor)
        if bars is None or bars.height < 20:
            continue
        b = bars.select(pl.col("ts").alias("t"),
                        (pl.col("close") / pl.col("close").shift(1) - 1).abs().alias("r"))
        s = spike_score(b, anchor)
        if s is not None:
            scores[t.strftime("%H:%M")] = round(s, 2)
    if not scores:
        return None, scores
    best = max(scores, key=scores.get)
    rest = [v for k, v in scores.items() if k != best] or [0.0]
    if scores[best] >= min_score and scores[best] >= dominance * max(max(rest), 1e-9):
        return time.fromisoformat(best), scores
    return None, scores


def resolve_time(m: FomcMeeting, detected: time | None) -> tuple[time, str, bool, str | None]:
    """-> (time ET, release_time_source, verified, note)"""
    allowed = allowed_times_et(m.decision_date)
    if m.kind != "fomc_scheduled":
        return allowed[-1], "unknown", False, "unscheduled/conference call: time not established"
    if detected is not None:
        if detected in allowed:
            return detected, "empirical_spike", True, None
        return allowed[-1], "unknown", False, (
            f"empirical_conflict: spike at {detected:%H:%M} ET, outside allowed "
            f"{[t.strftime('%H:%M') for t in allowed]}")
    if len(allowed) == 1:
        return allowed[0], "config", False, None
    return allowed[-1], "unknown", False, "ambiguous era and no clear spike"


def run_fomc(session: Session, universe: Universe, start: date, end: date,
             price_source: tuple[str, str] | None = ("kaggle_octafx_xauusd", "XAUUSD")) -> dict:
    ind = universe.indicators["fomc_rate_upper"]
    with track_job(session, "fed_calendar", "fomc_events",
                   {"start": str(start), "end": str(end)}) as stats:
        meetings = FedCalendarProvider().meetings(start.year, end.year)
        meetings = [m for m in meetings if start <= m.decision_date <= end]
        stats.rows_fetched = len(meetings)
        rates = rate_series(FredProvider(), start - timedelta(days=30),
                            min(end + timedelta(days=10), datetime.now(UTC).date()))

        bars = {}
        if price_source:
            anchors = [ny_local_to_utc(m.decision_date, t) for m in meetings
                       if m.kind == "fomc_scheduled" for t in CANDIDATE_TIMES_ET]
            try:
                bars = load_windows(*price_source, anchors, timedelta(minutes=50),
                                    timedelta(minutes=3))
            except FileNotFoundError as e:
                stats.warnings.append(f"no price data for time verification: {e}")

        n_new = 0
        counts: dict[str, int] = {}
        for m in meetings:
            detected, scores = detect_minute(bars, m.decision_date) if bars else (None, {})
            t, source, verified, note = resolve_time(m, detected)
            counts[source] = counts.get(source, 0) + 1
            prev, actual = rate_around(rates, m.decision_date)
            ts = ny_local_to_utc(m.decision_date, t)
            exists = session.scalar(select(EconomicEvent.event_id).where(
                EconomicEvent.indicator_key == ind.key,
                EconomicEvent.reference_period == m.decision_date,
                EconomicEvent.source == "fed_calendar"))
            if exists:
                continue
            ev = EconomicEvent(
                provider_event_id=f"fomc:{m.decision_date}", indicator_key=ind.key,
                release_key=ind.release, event_name=f"FOMC {m.kind.removeprefix('fomc_')}",
                event_category=ind.category, country="US", currency="USD",
                importance=ind.importance, scheduled_release_time=ts,
                release_time_verified=verified, release_time_source=source, event_kind=m.kind,
                reference_period=m.decision_date, actual_value=actual, previous_value=prev,
                unit=ind.unit, source="fed_calendar",
                details={"label": m.label, "has_sep": m.has_sep, "spike_scores": scores,
                         "time_note": note,
                         "rate_series": "DFEDTAR" if m.decision_date < SWITCH_TO_RANGE
                         else "DFEDTARU"},
            )
            session.add(ev)
            session.flush()
            session.add(EconomicEventSnapshot(
                event_id=ev.event_id, snapshot_kind="release", source_timestamp=ts,
                actual_value=actual, previous_value=prev, provider="fed_calendar",
                ingestion_job_id=stats.job_id, raw={"label": m.label, "source_page":
                                                     m.source_page}))
            n_new += 1
        session.commit()
        stats.rows_written = n_new
        stats.details = {"meetings": len(meetings), "new_events": n_new, "time_source": counts}
        return stats.details
