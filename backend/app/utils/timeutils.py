"""Timezone handling. All timestamps are stored in UTC.

US releases are scheduled in America/New_York local time; the UTC offset changes with DST
(UTC-5 in winter, UTC-4 in summer), so a fixed offset must never be used.
"""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")


def ny_local_to_utc(release_date: date, local_time: time) -> datetime:
    """Combine a New York calendar date + wall-clock time into an aware UTC datetime."""
    local = datetime.combine(release_date, local_time, tzinfo=NEW_YORK)
    return local.astimezone(UTC)


def ensure_utc(ts: datetime) -> datetime:
    """Normalise a datetime to aware UTC. Naive datetimes are rejected, not guessed."""
    if ts.tzinfo is None:
        raise ValueError(f"naive datetime {ts!r}: timezone must be explicit")
    return ts.astimezone(UTC)


def parse_hhmm(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))
