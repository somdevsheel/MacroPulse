"""Price cleaning, validation, gap analysis, Parquet storage and timeframe aggregation.

Silver layout (hive-partitioned, readable by DuckDB/Polars):
  data/silver/cleaned_prices/provider=<p>/instrument=<i>/timeframe=<tf>/year=<y>/part.parquet
Columns: ts (UTC, bar open), open, high, low, close, volume, n_source_bars (aggregates only).

Missing bars are reported, never filled.
"""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

AGG_TIMEFRAMES = {"5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h"}
SPIKE_FLAG_PCT = 3.0  # |1m return| above this is flagged for review (not removed)


def validate(df: pl.DataFrame) -> tuple[pl.DataFrame, dict]:
    """Drop structurally invalid bars and duplicate timestamps; report everything."""
    rep: dict = {}
    n0 = df.height

    bad = (
        (pl.col("open") <= 0) | (pl.col("high") <= 0) | (pl.col("low") <= 0)
        | (pl.col("close") <= 0)
        | (pl.col("high") < pl.max_horizontal("open", "close", "low"))
        | (pl.col("low") > pl.min_horizontal("open", "close", "high"))
        | pl.any_horizontal(pl.col("open", "high", "low", "close").is_null())
    )
    rep["dropped_invalid_ohlc"] = int(df.select(bad.sum()).item())
    df = df.filter(~bad)

    dup_groups = df.group_by("ts").agg(pl.len().alias("n"),
                                       pl.struct("open", "high", "low", "close").n_unique()
                                       .alias("variants")).filter(pl.col("n") > 1)
    rep["duplicate_timestamps"] = dup_groups.height
    rep["duplicate_conflicting"] = int(dup_groups.filter(pl.col("variants") > 1).height)
    # Conflicting duplicates are ambiguous -> drop all copies. Exact duplicates -> keep one.
    conflicting = dup_groups.filter(pl.col("variants") > 1)["ts"]
    df = df.filter(~pl.col("ts").is_in(conflicting.implode())).unique("ts", keep="first")
    df = df.sort("ts")

    ret = (df["close"] / df["close"].shift(1) - 1).abs() * 100
    spikes = df.filter(ret > SPIKE_FLAG_PCT).select("ts")
    rep["flagged_spikes_gt_pct"] = SPIKE_FLAG_PCT
    rep["flagged_spikes"] = [t.isoformat() for t in spikes["ts"].to_list()[:100]]
    rep["rows_valid"] = df.height
    rep["rows_dropped_total"] = n0 - df.height
    return df, rep


def gap_report(df: pl.DataFrame, top_n: int = 40) -> dict:
    """Gaps between consecutive 1m bars. Weekend closures and the ~1h daily break are expected;
    only gaps outside those are listed as unexpected."""
    g = df.select(
        pl.col("ts").shift(1).alias("from"), pl.col("ts").alias("to"),
        ((pl.col("ts") - pl.col("ts").shift(1)).dt.total_minutes() - 1).alias("missing"),
    ).filter(pl.col("missing") > 0)
    weekend = (pl.col("from").dt.weekday().is_in([5, 6])) & (pl.col("to").dt.weekday().is_in(
        [7, 1])) & (pl.col("missing") < 72 * 60)
    daily_break = pl.col("missing") <= 90
    unexpected = g.filter(~weekend & ~daily_break).sort("missing", descending=True)
    years = (
        df.group_by(pl.col("ts").dt.year().alias("year"))
        .agg(pl.len().alias("bars"), pl.col("ts").min().alias("first"),
             pl.col("ts").max().alias("last"))
        .sort("year")
    )
    return {
        "gaps_total": g.height,
        "gaps_short_le_90m": int(g.filter(pl.col("missing") <= 90).height),
        "gaps_unexpected_gt_90m": unexpected.height,
        "largest_unexpected": [
            {"from": r["from"].isoformat(), "to": r["to"].isoformat(),
             "missing_minutes": int(r["missing"])}
            for r in unexpected.head(top_n).iter_rows(named=True)
        ],
        # ~1,380 trading minutes/day x ~260 days ~= 359k bars/year when every minute trades.
        "bars_per_year": {int(r["year"]): int(r["bars"]) for r in years.iter_rows(named=True)},
    }


def aggregate(df_1m: pl.DataFrame, every: str) -> pl.DataFrame:
    """OHLCV resample from 1m bars, UTC-aligned, left-closed/left-labelled. Only intervals that
    contain at least one source bar are emitted; n_source_bars tells how complete each bar is."""
    return (
        df_1m.sort("ts")
        .group_by_dynamic("ts", every=every, closed="left", label="left")
        .agg(
            pl.col("open").first(), pl.col("high").max(), pl.col("low").min(),
            pl.col("close").last(), pl.col("volume").sum(),
            pl.len().alias("n_source_bars"),
        )
    )


def partition_dir(root: Path, provider: str, instrument: str, timeframe: str) -> Path:
    return root / f"provider={provider}" / f"instrument={instrument}" / f"timeframe={timeframe}"


def write_partitioned(df: pl.DataFrame, root: Path, provider: str, instrument: str,
                      timeframe: str) -> int:
    """Replace this provider/instrument/timeframe slice atomically-ish (write tmp, swap)."""
    final = partition_dir(root, provider, instrument, timeframe)
    tmp = final.with_name(final.name + ".tmp")
    if tmp.exists():
        shutil.rmtree(tmp)
    for (year,), part in df.with_columns(pl.col("ts").dt.year().alias("_y")).group_by("_y"):
        d = tmp / f"year={year}"
        d.mkdir(parents=True, exist_ok=True)
        part.drop("_y").sort("ts").write_parquet(d / "part.parquet", compression="zstd")
    if final.exists():
        shutil.rmtree(final)
    tmp.rename(final)
    return df.height


def write_report(report: dict, root: Path, name: str) -> Path:
    d = root / "_reports"
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    p = d / f"{name}_{stamp}.json"
    p.write_text(json.dumps(report, indent=2, default=str))
    return p
