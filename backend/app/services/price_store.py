"""Read access to silver price Parquet (hive-partitioned). All timestamps UTC."""

from datetime import datetime, timedelta
from pathlib import Path

import polars as pl

from app.core.config import get_settings


def silver_prices_root() -> Path:
    return get_settings().resolved_data_dir() / "silver" / "cleaned_prices"


def available_sources(root: Path | None = None) -> list[dict]:
    """[{provider, instrument, timeframe}] present on disk."""
    root = root or silver_prices_root()
    out = []
    for p in sorted(root.glob("provider=*/instrument=*/timeframe=*")):
        if p.name.endswith(".tmp"):
            continue
        prov, inst, tf = (x.split("=", 1)[1] for x in p.parts[-3:])
        out.append({"provider": prov, "instrument": inst, "timeframe": tf})
    return out


def scan_bars(provider: str, instrument: str, timeframe: str = "1m",
              root: Path | None = None) -> pl.LazyFrame:
    root = root or silver_prices_root()
    d = root / f"provider={provider}" / f"instrument={instrument}" / f"timeframe={timeframe}"
    if not d.exists():
        raise FileNotFoundError(f"no silver data for {provider}/{instrument}/{timeframe}")
    return pl.scan_parquet(d / "year=*" / "part.parquet")


def load_bars(provider: str, instrument: str, start: datetime, end: datetime,
              timeframe: str = "1m", root: Path | None = None) -> pl.DataFrame:
    """Bars with start <= ts < end (UTC-aware datetimes)."""
    return (
        scan_bars(provider, instrument, timeframe, root)
        .filter((pl.col("ts") >= start) & (pl.col("ts") < end))
        .sort("ts")
        .collect()
    )


def load_windows(provider: str, instrument: str, anchors: list[datetime],
                 before: timedelta, after: timedelta, timeframe: str = "1m",
                 root: Path | None = None) -> dict[datetime, pl.DataFrame]:
    """Bars around many anchors in one scan: {anchor: bars in [anchor-before, anchor+after)}."""
    if not anchors:
        return {}
    win = pl.DataFrame({"anchor": anchors}).with_columns(
        (pl.col("anchor") - before).alias("w0"), (pl.col("anchor") + after).alias("w1"))
    lo, hi = win["w0"].min(), win["w1"].max()
    bars = (scan_bars(provider, instrument, timeframe, root)
            .filter((pl.col("ts") >= lo) & (pl.col("ts") < hi)).sort("ts").collect())
    out = {}
    for a in anchors:
        out[a] = bars.filter((pl.col("ts") >= a - before) & (pl.col("ts") < a + after))
    return out
