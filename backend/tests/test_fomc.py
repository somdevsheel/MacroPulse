from datetime import date, time
from decimal import Decimal

from app.ingestion.fomc_pipeline import rate_around, resolve_time
from app.providers.economic.fed_calendar import FomcMeeting, parse_current, parse_historical

CURRENT = """
<div class="panel-heading"><h4><a id="1">2024 FOMC Meetings</a></h4></div>
<div class="fomc-meeting__month col"><strong>Apr/May</strong></div>
<div class="fomc-meeting__date col">30-1</div>
<div class="fomc-meeting__month col"><strong>June</strong></div>
<div class="fomc-meeting__date col">11-12*</div>
<div class="panel-heading"><h4><a id="2">2025 FOMC Meetings</a></h4></div>
<div class="fomc-meeting__month col"><strong>August</strong></div>
<div class="fomc-meeting__date col">22 (notation vote)</div>
"""

HIST = """<h5>January 21 Conference Call - 2008</h5><h5 class="x">January 29-30 Meeting - 2008</h5>
<h5>March 2 (unscheduled) Meeting - 2020</h5><h5>March 17-18 (cancelled) Meeting - 2020</h5>
<h5>March 19 (notation vote) - 2020</h5>"""


def test_parse_current_cross_month_sep_and_notation_vote():
    ms = parse_current(CURRENT, "current")
    assert [(m.decision_date, m.has_sep) for m in ms] == [
        (date(2024, 5, 1), False), (date(2024, 6, 12), True)]


def test_parse_historical_kinds():
    ms = parse_historical(HIST, "h")
    assert [(m.decision_date, m.kind) for m in ms] == [
        (date(2008, 1, 21), "fomc_conference_call"),
        (date(2008, 1, 30), "fomc_scheduled"),
        (date(2020, 3, 2), "fomc_unscheduled"),
    ]


def test_rate_around_handles_same_day_and_next_day_effective():
    same_day = {date(2015, 12, 15): Decimal("0.25"), date(2015, 12, 16): Decimal("0.50"),
                date(2015, 12, 17): Decimal("0.50")}
    next_day = {date(2024, 9, 17): Decimal("5.5"), date(2024, 9, 18): Decimal("5.5"),
                date(2024, 9, 19): Decimal("5.0")}
    assert rate_around(same_day, date(2015, 12, 16)) == (Decimal("0.25"), Decimal("0.50"))
    assert rate_around(next_day, date(2024, 9, 18)) == (Decimal("5.5"), Decimal("5.0"))
    assert rate_around(next_day, date(2026, 1, 1))[1] is None  # future: no actual


def _m(d, kind="fomc_scheduled"):
    return FomcMeeting(d, kind, "x", None, "x")


def test_resolve_time_rules():
    # confirmed inside allowed set
    assert resolve_time(_m(date(2024, 9, 18)), time(14, 0))[1:3] == ("empirical_spike", True)
    # conflict -> excluded
    t, src, ver, note = resolve_time(_m(date(2014, 4, 30)), time(14, 15))
    assert src == "unknown" and "conflict" in note
    # no spike, single allowed time -> config
    assert resolve_time(_m(date(2006, 1, 31)), None)[:2] == (time(14, 15), "config")
    # no spike, ambiguous era -> unknown
    assert resolve_time(_m(date(2012, 3, 13)), None)[1] == "unknown"
    # pressconf-era 12:30 confirmed
    assert resolve_time(_m(date(2011, 6, 22)), time(12, 30))[:2] == (time(12, 30),
                                                                    "empirical_spike")
    # emergency meetings never get a guessed time
    assert resolve_time(_m(date(2020, 3, 15), "fomc_unscheduled"), time(14, 0))[1] == "unknown"
