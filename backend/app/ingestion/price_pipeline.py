"""File-based market source -> silver Parquet (1m + aggregates) + data-quality report."""

from pathlib import Path

from sqlalchemy.orm import Session

from app.ingestion.jobs import track_job
from app.ingestion.prices import (
    AGG_TIMEFRAMES,
    aggregate,
    gap_report,
    validate,
    write_partitioned,
    write_report,
)
from app.providers.market.metatrader_csv import FileSourceConfig, read_raw, to_utc


def run_file_source(cfg: FileSourceConfig, data_root: Path, session: Session | None) -> dict:
    silver = data_root / "silver" / "cleaned_prices"
    params = {"source": cfg.key, "path": str(cfg.path)}
    with track_job(session, cfg.key, f"prices_{cfg.timeframe}_file", params) as stats:
        if not cfg.path.exists():
            raise FileNotFoundError(f"{cfg.path} missing -- download it to the bronze layer first")
        df, tz_counts = to_utc(read_raw(cfg.path), cfg)
        stats.rows_fetched = tz_counts["rows_in"]
        df, val = validate(df)
        gaps = gap_report(df)
        written = {cfg.timeframe: write_partitioned(df, silver, cfg.key, cfg.instrument,
                                                    cfg.timeframe)}
        for tf, every in AGG_TIMEFRAMES.items():
            written[tf] = write_partitioned(aggregate(df, every), silver, cfg.key,
                                            cfg.instrument, tf)
        vendor = {}
        for tf, path in cfg.vendor_timeframes.items():
            if not path.exists():
                stats.warnings.append(f"vendor {tf} file missing: {path}")
                continue
            vdf, vcounts = to_utc(read_raw(path), cfg)
            vdf, vval = validate(vdf)
            written[tf] = write_partitioned(vdf, silver, cfg.key, cfg.instrument, tf)
            vendor[tf] = {"timezone_conversion": vcounts,
                          "dropped_invalid_ohlc": vval["dropped_invalid_ohlc"],
                          "duplicate_timestamps": vval["duplicate_timestamps"],
                          "first_ts_utc": vdf["ts"].min(), "last_ts_utc": vdf["ts"].max()}
        report = {
            "source": cfg.key, "instrument": cfg.instrument, "license": cfg.license,
            "source_url": cfg.source_url, "price_side": cfg.price_side,
            "volume_kind": cfg.volume_kind,
            "timezone_segments": [s.__dict__ for s in cfg.timezone_segments],
            "quarantine": [q.__dict__ for q in cfg.quarantine],
            "first_ts_utc": df["ts"].min(), "last_ts_utc": df["ts"].max(),
            "timezone_conversion": tz_counts, "validation": val, "gaps": gaps,
            "rows_written": written, "vendor_timeframes": vendor,
        }
        report_path = write_report(report, silver, cfg.key)
        stats.rows_written = sum(written.values())
        stats.details = {"report": str(report_path), "rows_written": written}
        dropped = tz_counts["dropped_no_tz_segment"] + tz_counts["dropped_tz_ambiguous"]
        if dropped or val["duplicate_conflicting"]:
            stats.warnings.append(
                f"dropped {dropped} rows without a determinable timezone, "
                f"{val['duplicate_conflicting']} conflicting duplicates")
    return report | {"report_path": str(report_path)}
