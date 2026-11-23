from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl

from app.ingestion.prices import aggregate, gap_report, validate, write_partitioned
from app.ingestion.tz_detect import score_dates
from app.providers.market.metatrader_csv import (
    FileSourceConfig,
    Quarantine,
    TzSegment,
    read_raw,
    to_utc,
)


def _cfg(path: Path) -> FileSourceConfig:
    return FileSourceConfig(
        key="t", instrument="XAUUSD", timeframe="1m", path=path, price_side="bid",
        volume_kind="tick", license="x", source_url="x",
        timezone_segments=[TzSegment(date(2000, 1, 1), date(2011, 5, 6), "Europe/Berlin"),
                           TzSegment(date(2011, 5, 12), date(2099, 1, 1), "Europe/Athens")],
        quarantine=[Quarantine(date(2011, 5, 7), date(2011, 5, 11), "switch")],
    )


def test_metatrader_segments_dst_and_quarantine(tmp_path):
    csv = tmp_path / "x.csv"
    csv.write_text("Date;Open;High;Low;Close;Volume\n"
                   "2010.01.15 15:30;1;1;1;1;1\n"   # CET winter  UTC+1 -> 14:30
                   "2010.07.15 15:30;1;1;1;1;1\n"   # CEST summer UTC+2 -> 13:30
                   "2011.05.09 10:00;1;1;1;1;1\n"   # quarantined
                   "2024.01.15 15:30;1;1;1;1;1\n"   # EET  UTC+2 -> 13:30
                   "2024.07.15 15:30;1;1;1;1;1\n")  # EEST UTC+3 -> 12:30
    df, counts = to_utc(read_raw(csv), _cfg(csv))
    got = [t.replace(tzinfo=None) for t in df.sort("ts")["ts"].to_list()]
    assert got == [datetime(2010, 1, 15, 14, 30), datetime(2010, 7, 15, 13, 30),
                   datetime(2024, 1, 15, 13, 30), datetime(2024, 7, 15, 12, 30)]
    assert counts["dropped_quarantine"] == 1


def _bars(n=10, start=datetime(2024, 1, 2, 10, tzinfo=UTC)):
    return pl.DataFrame({
        "ts": [start + timedelta(minutes=i) for i in range(n)],
        "open": [100.0 + i for i in range(n)], "high": [101.0 + i for i in range(n)],
        "low": [99.0 + i for i in range(n)], "close": [100.5 + i for i in range(n)],
        "volume": [1.0] * n,
    })


def test_validate_drops_bad_ohlc_and_conflicting_duplicates():
    df = _bars(5)
    bad = df.head(1).with_columns(pl.lit(50.0).alias("high"))  # high < open
    dup_conflict = df.slice(2, 1).with_columns(pl.lit(999.0).alias("close"),
                                               pl.lit(1000.0).alias("high"))
    out, rep = validate(pl.concat([df.slice(1), bad.with_columns(
        pl.col("ts") + timedelta(hours=1)), dup_conflict]))
    assert rep["dropped_invalid_ohlc"] == 1
    assert rep["duplicate_conflicting"] == 1
    assert out.height == 3  # 4 good - the conflicting timestamp (both copies)


def test_aggregate_no_fabricated_bars():
    df = pl.concat([_bars(3), _bars(2, datetime(2024, 1, 2, 10, 20, tzinfo=UTC))])
    agg = aggregate(df, "5m")
    assert agg["ts"].dt.minute().to_list() == [0, 20]  # 10:05-10:15 empty -> not emitted
    first = agg.row(0, named=True)
    assert (first["open"], first["high"], first["low"], first["close"], first["n_source_bars"]) \
        == (100.0, 103.0, 99.0, 102.5, 3)


def test_gap_report_separates_weekend_from_unexpected():
    fri = datetime(2024, 1, 5, 21, 58, tzinfo=UTC)
    sun = datetime(2024, 1, 7, 23, 0, tzinfo=UTC)
    tue = datetime(2024, 1, 9, 12, 0, tzinfo=UTC)
    df = pl.concat([_bars(2, fri), _bars(2, sun), _bars(2, tue)])
    rep = gap_report(df)
    assert rep["gaps_unexpected_gt_90m"] == 1  # Mon->Tue hole only
    assert rep["largest_unexpected"][0]["from"].startswith("2024-01-07T23:01")


def test_write_partitioned_by_year(tmp_path):
    df = pl.concat([_bars(2, datetime(2023, 12, 29, tzinfo=UTC)), _bars(2)])
    write_partitioned(df, tmp_path, "p", "XAUUSD", "1m")
    years = sorted(p.parent.name for p in tmp_path.rglob("part.parquet"))
    assert years == ["year=2023", "year=2024"]


def test_tz_detect_recovers_true_zone():
    # Synthetic file in Europe/Athens with a spike exactly at each 08:30 ET release.
    from zoneinfo import ZoneInfo

    from app.utils.timeutils import ny_local_to_utc

    days = [date(2024, 3, 8), date(2024, 6, 7), date(2024, 10, 4), date(2024, 12, 6)]
    rows = []
    for d in days:
        rel_local = ny_local_to_utc(d, datetime.min.time().replace(hour=8, minute=30)) \
            .astimezone(ZoneInfo("Europe/Athens")).replace(tzinfo=None)
        for i in range(-90, 30):
            t = rel_local + timedelta(minutes=i)
            px = 2000 + (0.01 if i % 2 else 0) + (5 if i >= 0 else 0)
            rows.append((t, px))
    bars = pl.DataFrame(rows, schema=["t", "Close"], orient="row")
    instants = [ny_local_to_utc(d, datetime.min.time().replace(hour=8, minute=30)) for d in days]
    v = score_dates(bars, instants, {"CET": "Europe/Berlin", "EET": "Europe/Athens"})
    assert v and all(x.winner == "EET" for x in v)


