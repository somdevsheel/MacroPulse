"""Federal Reserve FOMC meeting calendar (federalreserve.gov, public US government data).

Pages:
  current (recent ~5 years + upcoming): /monetarypolicy/fomccalendars.htm
  historical (one per year):            /monetarypolicy/fomchistorical{YYYY}.htm
Raw HTML is cached in data/bronze/central_bank_events/fed/ and re-parsed from there.
"""

import re
import time as _time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from app.providers.base import BaseProvider, ProviderHealth, ProviderKind, ProviderStatus
from app.utils.http import get_with_retry, make_client

BASE = "https://www.federalreserve.gov/monetarypolicy"
MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September",
     "October", "November", "December"], start=1)}
MONTH_ABBR = {m[:3]: i for m, i in MONTHS.items()}


@dataclass(frozen=True)
class FomcMeeting:
    decision_date: date  # last day of the meeting / day of the call
    kind: str  # fomc_scheduled | fomc_unscheduled | fomc_conference_call
    label: str  # original text, e.g. "January 29-30 Meeting - 2008"
    has_sep: bool | None  # Summary of Economic Projections (None = unknown on that page)
    source_page: str


def _last_day(year: int, month_text: str, days_text: str) -> date:
    """'Apr/May' + '30-1' -> May 1; 'January' + '27-28' -> Jan 28; 'March' + '15' -> Mar 15."""
    months = [MONTHS.get(m) or MONTH_ABBR[m[:3]] for m in month_text.split("/")]
    nums = [int(x) for x in re.findall(r"\d+", days_text)]
    month = months[-1] if len(months) > 1 and len(nums) > 1 else months[0]
    return date(year, month, nums[-1])


def _classify(text: str) -> str | None:
    t = text.lower()
    if "notation vote" in t or "cancelled" in t:
        return None
    if "conference call" in t:
        return "fomc_conference_call"
    if "unscheduled" in t:
        return "fomc_unscheduled"
    return "fomc_scheduled"


def parse_historical(html: str, page: str) -> list[FomcMeeting]:
    out = []
    for h in re.findall(r"<h5[^>]*>([^<]+)</h5>", html):
        m = re.match(r"\s*([A-Za-z/]+)\s+([\d\-]+)\s*(.*?)\s*-\s*(\d{4})\s*$", h.strip())
        if not m:
            continue
        month, days, rest, year = m.groups()
        kind = _classify(rest)
        if kind:
            out.append(FomcMeeting(_last_day(int(year), month, days), kind, h.strip(), None, page))
    return out


def parse_current(html: str, page: str) -> list[FomcMeeting]:
    out = []
    panels = re.findall(
        r'<h4><a id="\d+">(\d{4}) FOMC Meetings</a></h4>(.*?)'
        r'(?=<h4><a id="\d+">\d{4} FOMC Meetings|\Z)', html, re.S)
    for year, body in panels:
        rows = re.findall(r'fomc-meeting__month[^>]*><strong>([^<]+)</strong></div>\s*'
                          r'<div class="fomc-meeting__date[^>]*>([^<]*)<', body)
        for month, days in rows:
            kind = _classify(days)
            if kind and re.search(r"\d", days):
                out.append(FomcMeeting(_last_day(int(year), month, days), kind,
                                       f"{month} {days.strip()} - {year}", "*" in days, page))
    return out


class FedCalendarProvider(BaseProvider):
    key = "fed_calendar"
    name = "Federal Reserve FOMC calendar"
    kind = ProviderKind.ECONOMIC
    requires_key = False

    def __init__(self, cache_dir: Path | None = None, min_interval_s: float = 2.0):
        from app.core.config import get_settings

        self.cache_dir = cache_dir or (
            get_settings().resolved_data_dir() / "bronze" / "central_bank_events" / "fed")
        self.min_interval_s = min_interval_s
        self._last = 0.0

    def is_configured(self) -> bool:
        return True

    def _fetch(self, name: str, refresh: bool) -> str:
        path = self.cache_dir / name
        if path.exists() and not refresh:
            return path.read_text()
        wait = self.min_interval_s - (_time.monotonic() - self._last)
        if wait > 0:
            _time.sleep(wait)
        self._last = _time.monotonic()
        with make_client(user_agent="Mozilla/5.0 (compatible; MacroPulse research)") as c:
            r = get_with_retry(c, f"{BASE}/{name}")
        r.raise_for_status()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(r.text)
        return r.text

    def check_health(self) -> ProviderHealth:
        try:
            n = len(parse_current(self._fetch("fomccalendars.htm", refresh=True), "current"))
            return ProviderHealth(self.key, ProviderStatus.CONNECTED, detail=f"{n} meetings")
        except Exception as e:
            return ProviderHealth(self.key, ProviderStatus.ERROR, detail=str(e)[:300])

    def meetings(self, start_year: int, end_year: int, refresh_current: bool = True
                 ) -> list[FomcMeeting]:
        cur = parse_current(self._fetch("fomccalendars.htm", refresh_current), "current")
        covered = {m.decision_date.year for m in cur}
        out = list(cur)
        this_year = datetime.now(UTC).year
        for y in range(start_year, end_year + 1):
            if y in covered or y > this_year:
                continue
            out += parse_historical(self._fetch(f"fomchistorical{y}.htm", refresh=False),
                                    f"historical{y}")
        return sorted({m.decision_date: m for m in out
                       if start_year <= m.decision_date.year <= end_year}.values(),
                      key=lambda m: m.decision_date)
