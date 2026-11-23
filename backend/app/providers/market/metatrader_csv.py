"""Reader for MetaTrader-style OHLCV CSV exports (e.g. the Kaggle OctaFX XAU/USD dataset).

Format: `Date;Open;High;Low;Close;Volume` with `Date` = `YYYY.MM.DD HH:MM` in broker server time.
Converts to UTC using explicitly configured timezone segments; rows outside every segment or
inside a quarantine window are dropped and counted (never guessed).
"""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import polars as pl
import yaml

from app.core.config import CONFIG_DIR, REPO_ROOT


@dataclass(frozen=True)
class TzSegment:
    start: date  # inclusive, server-local calendar date
    end: date  # inclusive
    tz: str


@dataclass(frozen=True)
class Quarantine:
    start: date
    end: date
    reason: str


@dataclass(frozen=True)
class FileSourceConfig:
    key: str
    instrument: str
    timeframe: str
    path: Path
    price_side: str
    volume_kind: str
    license: str
    source_url: str
    timezone_segments: list[TzSegment]
    quarantine: list[Quarantine] = field(default_factory=list)
    vendor_timeframes: dict[str, Path] = field(default_factory=dict)


def _abs(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else REPO_ROOT / path


def load_file_sources(config_dir: Path = CONFIG_DIR) -> dict[str, FileSourceConfig]:
    raw = yaml.safe_load((config_dir / "market_sources.yaml").read_text())["sources"]
    out = {}
    for key, s in raw.items():
        out[key] = FileSourceConfig(
            key=key,
            instrument=s["instrument"],
            timeframe=s["timeframe"],
            path=_abs(s["path"]),
            price_side=s["price_side"],
            volume_kind=s["volume_kind"],
            license=s["license"],
            source_url=s["source_url"],
            timezone_segments=[
                TzSegment(date.fromisoformat(t["start"]), date.fromisoformat(t["end"]), t["tz"])
                for t in s["timezone_segments"]
            ],
            quarantine=[
                Quarantine(date.fromisoformat(q["start"]), date.fromisoformat(q["end"]),
                           q["reason"])
                for q in s.get("quarantine", [])
            ],
            vendor_timeframes={tf: _abs(p) for tf, p in (s.get("vendor_timeframes") or {})
                               .items()},
        )
    return out


def read_raw(path: Path) -> pl.LazyFrame:
    """Raw rows with naive server-local timestamp `t_local`."""
    return pl.scan_csv(path, separator=";").select(
        pl.col("Date").str.strptime(pl.Datetime("us"), "%Y.%m.%d %H:%M").alias("t_local"),
        pl.col("Open").cast(pl.Float64).alias("open"),
        pl.col("High").cast(pl.Float64).alias("high"),
        pl.col("Low").cast(pl.Float64).alias("low"),
        pl.col("Close").cast(pl.Float64).alias("close"),
        pl.col("Volume").cast(pl.Float64).alias("volume"),
    )


def to_utc(lf: pl.LazyFrame, cfg: FileSourceConfig) -> tuple[pl.DataFrame, dict]:
    """Apply timezone segments + quarantine. Returns (frame with `ts` UTC, drop counts)."""
    df = lf.with_columns(pl.col("t_local").dt.date().alias("_d")).collect()
    total = df.height
    counts = {"rows_in": total}

    q_mask = pl.lit(False)
    for q in cfg.quarantine:
        q_mask = q_mask | pl.col("_d").is_between(q.start, q.end)
    counts["dropped_quarantine"] = int(df.select(q_mask.sum()).item())
    df = df.filter(~q_mask)

    parts = []
    covered = 0
    for seg in cfg.timezone_segments:
        part = df.filter(pl.col("_d").is_between(seg.start, seg.end))
        covered += part.height
        parts.append(
            part.with_columns(
                pl.col("t_local")
                # Weekend DST transitions: gold is closed then; ambiguous/non-existent -> null.
                .dt.replace_time_zone(seg.tz, ambiguous="null", non_existent="null")
                .dt.convert_time_zone("UTC")
                .alias("ts")
            )
        )
    counts["dropped_no_tz_segment"] = df.height - covered
    out = pl.concat(parts) if parts else df.head(0)
    counts["dropped_tz_ambiguous"] = int(out["ts"].null_count())
    out = out.filter(pl.col("ts").is_not_null()).drop("_d", "t_local")
    return out, counts
