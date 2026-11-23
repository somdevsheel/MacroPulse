from datetime import date
from decimal import Decimal

import pytest

from app.core.universe import load_universe
from app.ingestion.fred_events import UnsupportedIndicator, VintageStore, build_events, headline
from app.providers.base import Observation

U = load_universe()


def ob(p, v, rs, re=None, sid="X"):
    return Observation(sid, date.fromisoformat(p), None if v is None else Decimal(str(v)),
                       date.fromisoformat(rs), date.fromisoformat(re) if re else None)


# Synthetic level series released monthly; Feb value revised in Apr; a revision-only vintage
# on 2024-03-05 restates Jan without publishing a new period.
ROWS = [
    ob("2023-12-01", 100, "2024-01-10"),
    ob("2024-01-01", 101, "2024-02-10", "2024-03-04"),
    ob("2024-01-01", 101.5, "2024-03-05"),  # revision-only vintage
    ob("2024-02-01", 102, "2024-03-12", "2024-04-09"),
    ob("2024-02-01", 103, "2024-04-10"),  # revised in the March-data release
    ob("2024-03-01", 104, "2024-04-10"),
]


def _build(transform, rows=ROWS, cal=None):
    ind = U.indicators["nfp"].model_copy(update={"transform": transform})
    return build_events(ind, U.releases["employment_situation"], rows, cal or set(),
                        date(2024, 1, 1), date(2024, 12, 31))


def test_release_dates_are_first_appearance_not_revision_vintages():
    events, _ = _build("level")
    assert [e.release_date for e in events] == [
        date(2024, 1, 10), date(2024, 2, 10), date(2024, 3, 12), date(2024, 4, 10)]
    assert date(2024, 3, 5) not in {e.release_date for e in events}


def test_change_previous_vs_revised_previous():
    events, _ = _build("change")
    mar = next(e for e in events if e.reference_period == date(2024, 3, 1))
    assert mar.actual_value == Decimal("1")  # 104 - 103 (Feb as revised in same release)
    assert mar.previous_value == Decimal("0.5")  # Feb as known the day before: 102 - 101.5
    assert mar.revised_previous_value == Decimal("1.5")  # Feb restated: 103 - 101.5


def test_previous_unchanged_means_no_revised_value():
    events, _ = _build("level")
    feb = next(e for e in events if e.reference_period == date(2024, 2, 1))
    assert feb.previous_value == Decimal("101.5") and feb.revised_previous_value is None


def test_revisions_become_snapshots_and_first_print_is_kept():
    events, _ = _build("level")
    feb = next(e for e in events if e.reference_period == date(2024, 2, 1))
    assert feb.actual_value == Decimal("102")
    assert [(r.vintage_date, r.value) for r in feb.revisions] == [
        (date(2024, 4, 10), Decimal("103"))]


def test_bulk_backload_vintage_rejected():
    # Series entered ALFRED on 2024-05-01 with 3 old periods at once: only the newest counts,
    # and it fails the lag check -> no fake announcements on 2024-05-01.
    rows = [ob("2023-10-01", 1, "2024-05-01"), ob("2023-11-01", 2, "2024-05-01"),
            ob("2023-12-01", 3, "2024-05-01")]
    events, warns = _build("level", rows)
    assert events == [] and any("lag" in w for w in warns)


def test_mom_pct_uses_point_in_time_base():
    st = VintageStore(ROWS)
    # March m/m on its release day uses revised Feb (103): 104/103-1
    assert headline(st, date(2024, 3, 1), date(2024, 4, 10), "mom_pct") == Decimal("0.9709")


def test_calendar_mismatch_is_warned():
    _, warns = _build("level", cal={date(2024, 1, 10)})
    assert any("not in FRED release calendar" in w for w in warns)


def test_fomc_refused():
    with pytest.raises(UnsupportedIndicator):
        build_events(U.indicators["fomc_rate_upper"], U.releases["fomc_statement"], [], set(),
                     date(2024, 1, 1), date(2024, 2, 1))


@pytest.mark.live
def test_live_nfp_jan_2024_matches_published():
    from app.providers.macro.fred import FredProvider

    obs = list(FredProvider().observations("PAYEMS", date(2023, 1, 1), date(2024, 3, 1)))
    events, _ = build_events(U.indicators["nfp"], U.releases["employment_situation"], obs, set(),
                             date(2024, 1, 1), date(2024, 3, 31))
    jan = next(e for e in events if e.reference_period == date(2024, 1, 1))
    assert jan.release_date == date(2024, 2, 2)
    assert (jan.actual_value, jan.previous_value, jan.revised_previous_value) == (
        Decimal(353), Decimal(216), Decimal(333))
    assert jan.scheduled_release_time.isoformat() == "2024-02-02T13:30:00+00:00"
