"""Build point-in-time economic events from FRED/ALFRED vintages.

For each reference period P of an indicator:
  release date D     = first vintage date in which P has a value, accepted only if P is the
                       newest period known on D (rejects bulk back-loads and revision-only
                       vintages) and D - P is within `max_lag_days`.
  actual_value       = headline(P) using values as known on D        (first print)
  previous_value     = headline(P-1) as known on D-1                 (what the market knew)
  revised_previous   = headline(P-1) as known on D, if it changed    (restated in this release)
  revisions          = headline(P) on each later vintage where it changed -> snapshots

FRED vintages are daily-granular, so "as known on D-1" = everything public before release day.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal

from app.core.universe import IndicatorDef, ReleaseDef
from app.providers.base import Observation

Q = Decimal("0.0001")


class UnsupportedIndicator(Exception):
    pass


@dataclass
class Revision:
    vintage_date: date
    value: Decimal


@dataclass
class BuiltEvent:
    indicator_key: str
    reference_period: date
    release_date: date
    scheduled_release_time: datetime
    time_reliable: bool
    actual_value: Decimal | None
    previous_value: Decimal | None
    revised_previous_value: Decimal | None
    in_fred_release_calendar: bool
    revisions: list[Revision] = field(default_factory=list)


class VintageStore:
    """ALFRED rows indexed for 'value of obs_date as known on day D' lookups."""

    def __init__(self, rows: Iterable[Observation]):
        self._by_obs: dict[date, list[Observation]] = defaultdict(list)
        for r in rows:
            self._by_obs[r.observation_date].append(r)
        for v in self._by_obs.values():
            v.sort(key=lambda r: r.realtime_start)
        self.obs_dates = sorted(self._by_obs)

    def asof(self, obs_date: date, day: date) -> Decimal | None:
        for r in reversed(self._by_obs.get(obs_date, ())):
            if r.realtime_start <= day and (r.realtime_end is None or r.realtime_end >= day):
                return r.value
        return None

    def first_published(self, obs_date: date) -> date | None:
        dates = [r.realtime_start for r in self._by_obs.get(obs_date, ()) if r.value is not None]
        return min(dates) if dates else None

    def vintage_dates(self, obs_dates: Iterable[date]) -> list[date]:
        return sorted({r.realtime_start for d in obs_dates for r in self._by_obs.get(d, ())})

    def previous_obs(self, obs_date: date) -> date | None:
        i = self.obs_dates.index(obs_date)
        return self.obs_dates[i - 1] if i > 0 else None


def _lag_date(store: VintageStore, p: date, transform: str) -> date | None:
    if transform in ("change", "mom_pct", "qoq_saar"):
        return store.previous_obs(p)
    if transform == "yoy_pct":
        try:
            return p.replace(year=p.year - 1)
        except ValueError:  # Feb 29
            return p.replace(year=p.year - 1, day=28)
    return None


def headline(store: VintageStore, p: date, day: date, transform: str) -> Decimal | None:
    """Market headline number for period p using only values known on `day`."""
    v = store.asof(p, day)
    if v is None:
        return None
    if transform == "level":
        return v
    lag = _lag_date(store, p, transform)
    base = store.asof(lag, day) if lag else None
    if base is None or base == 0:
        return None
    if transform == "change":
        return v - base
    ratio = v / base
    if transform in ("mom_pct", "yoy_pct"):
        out = (ratio - 1) * 100
    elif transform == "qoq_saar":
        out = (Decimal(float(ratio) ** 4) - 1) * 100
    else:
        raise ValueError(transform)
    return out.quantize(Q, rounding=ROUND_HALF_EVEN)


def build_events(
    indicator: IndicatorDef,
    release: ReleaseDef,
    observations: Iterable[Observation],
    fred_release_dates: set[date],
    start: date,
    end: date,
    max_lag_days: int = 150,
) -> tuple[list[BuiltEvent], list[str]]:
    if release.key == "fomc_statement":
        raise UnsupportedIndicator(
            "FOMC dates cannot be derived from FRED (release 101 lists every day); "
            "use the Federal Reserve meeting calendar adapter"
        )
    store = VintageStore(observations)
    warnings: list[str] = []
    events: list[BuiltEvent] = []
    newest_released: date | None = None

    candidates = sorted(
        ((store.first_published(p), p) for p in store.obs_dates if store.first_published(p)),
    )
    for d, p in candidates:
        # P must be newer than anything already released (rejects bulk/back-filled vintages).
        if newest_released and p <= newest_released:
            continue
        newer_same_day = [q for dd, q in candidates if dd == d and q > p]
        if newer_same_day:
            continue
        newest_released = p
        if not (start <= d <= end):
            continue
        if (d - p).days > max_lag_days or d < p:
            warnings.append(f"{indicator.key}: {p} first seen {d} (lag {(d - p).days}d) skipped")
            continue

        prev_p = store.previous_obs(p)
        actual = headline(store, p, d, indicator.transform)
        prev_known = headline(store, prev_p, d - timedelta(days=1), indicator.transform) \
            if prev_p else None
        prev_now = headline(store, prev_p, d, indicator.transform) if prev_p else None
        revised_prev = prev_now if (prev_now is not None and prev_now != prev_known) else None

        lag = _lag_date(store, p, indicator.transform)
        deps = [x for x in (p, lag) if x]
        revisions, last = [], actual
        for v in store.vintage_dates(deps):
            if v <= d:
                continue
            val = headline(store, p, v, indicator.transform)
            if val is not None and val != last:
                revisions.append(Revision(v, val))
                last = val

        in_cal = d in fred_release_dates
        if fred_release_dates and not in_cal:
            warnings.append(f"{indicator.key}: release date {d} not in FRED release calendar")
        events.append(
            BuiltEvent(
                indicator_key=indicator.key,
                reference_period=p,
                release_date=d,
                scheduled_release_time=release.scheduled_utc(d),
                time_reliable=release.time_is_reliable(d),
                actual_value=actual,
                previous_value=prev_known,
                revised_previous_value=revised_prev,
                in_fred_release_calendar=in_cal,
                revisions=revisions,
            )
        )
    return events, warnings
