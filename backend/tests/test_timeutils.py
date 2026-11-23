from datetime import UTC, date, datetime, time

import pytest

from app.utils.timeutils import ensure_utc, ny_local_to_utc


@pytest.mark.parametrize(
    ("d", "expected_utc_hour"),
    [
        (date(2024, 1, 11), 13),  # EST, UTC-5
        (date(2024, 3, 8), 13),  # Friday before DST starts (Mar 10 2024)
        (date(2024, 3, 12), 12),  # EDT, UTC-4
        (date(2024, 11, 1), 12),  # Friday before DST ends (Nov 3 2024)
        (date(2024, 11, 13), 13),  # back to EST
    ],
)
def test_830_et_release_respects_dst(d, expected_utc_hour):
    ts = ny_local_to_utc(d, time(8, 30))
    assert ts.tzinfo == UTC
    assert (ts.hour, ts.minute) == (expected_utc_hour, 30)
    assert ts.date() == d


def test_fomc_2pm_et():
    expected = datetime(2024, 7, 31, 18, 0, tzinfo=UTC)
    assert ny_local_to_utc(date(2024, 7, 31), time(14, 0)) == expected


def test_naive_datetimes_rejected():
    with pytest.raises(ValueError):
        ensure_utc(datetime(2024, 1, 1, 12, 0))
