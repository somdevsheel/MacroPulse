"""OANDA 1-minute history -> bronze monthly Parquet -> silver (bid/ask/mid + aggregates).

Bronze: data/bronze/{forex_prices|gold_prices}/oanda/instrument=EUR_USD/month=2024-01.parquet
  One file per completed month; re-runs skip completed months (resumable, incremental). The
  current month is always re-fetched.
Silver: data/silver/cleaned_prices/provider=oanda/instrument=EURUSD/timeframe=1m/...
  1m: ts, open/high/low/close (= MID), bid_*, ask_*, spread_close, volume (tick)
  5m/15m/1h/4h: built from 1m mid (same aggregation as other sources).
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
from sqlalchemy.orm import Session

from app.core.universe import Universe
from app.ingestion.jobs import track_job
from app.ingestion.prices import (
    AGG_TIMEFRAMES,
    aggregate,
    gap_report,
    validate,
    write_partitioned,
    write_report,
)
from app.providers.market.oanda import SCHEMA, OandaProvider

log = logging.getLogger(__name__)
PROVIDER = "oanda"


def _months(start: datetime, end: datetime) -> list[datetime]:
    out, y, m = [], start.year, start.month
    while datetime(y, m, 1, tzinfo=UTC) < end:
        out.append(datetime(y, m, 1, tzinfo=UTC))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def bronze_dir(data_root: Path, oanda_symbol: str) -> Path:
    kind = "gold_prices" if oanda_symbol.startswith("XAU") else "forex_prices"
    return data_root / "bronze" / kind / "oanda" / f"instrument={oanda_symbol}"


def fetch_instrument(oanda: OandaProvider, oanda_symbol: str, start: datetime, end: datetime,
                     data_root: Path) -> dict:
    d = bronze_dir(data_root, oanda_symbol)
    d.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    fetched = skipped = rows = 0
    with oanda.client() as c:
        for m0 in _months(start, end):
            m1 = datetime(m0.year + (m0.month == 12), m0.month % 12 + 1, 1, tzinfo=UTC)
            path = d / f"month={m0:%Y-%m}.parquet"
            complete = m1 <= now
            if path.exists() and complete:
                skipped += 1
                continue
            df = oanda.candles(c, oanda_symbol, m0, min(m1, end))
            tmp = path.with_suffix(".tmp")
            df.write_parquet(tmp)
            tmp.replace(path)
            fetched += 1
            rows += df.height
    return {"months_fetched": fetched, "months_skipped": skipped, "rows": rows}


def build_silver(data_root: Path, oanda_symbol: str, symbol: str) -> dict:
    files = sorted(bronze_dir(data_root, oanda_symbol).glob("month=*.parquet"))
    if not files:
        raise FileNotFoundError(f"no bronze OANDA data for {oanda_symbol}")
    df = pl.concat([pl.read_parquet(f) for f in files], how="vertical").cast(SCHEMA)
    df = df.with_columns(
        pl.col("mid_open").alias("open"), pl.col("mid_high").alias("high"),
        pl.col("mid_low").alias("low"), pl.col("mid_close").alias("close"),
        (pl.col("ask_close") - pl.col("bid_close")).alias("spread_close"),
    ).select("ts", "open", "high", "low", "close", "volume", "spread_close",
             *[c for c in SCHEMA if c.startswith(("bid_", "ask_"))])
    df, val = validate(df)
    neg_spread = int(df.filter(pl.col("spread_close") < 0).height)
    gaps = gap_report(df)
    silver = data_root / "silver" / "cleaned_prices"
    written = {"1m": write_partitioned(df, silver, PROVIDER, symbol, "1m")}
    for tf, every in AGG_TIMEFRAMES.items():
        written[tf] = write_partitioned(aggregate(df, every), silver, PROVIDER, symbol, tf)
    report = {"source": PROVIDER, "instrument": symbol, "oanda_instrument": oanda_symbol,
              "price_side": "mid (bid/ask kept in 1m)", "volume_kind": "tick",
              "first_ts_utc": df["ts"].min(), "last_ts_utc": df["ts"].max(),
              "validation": val, "negative_spread_bars": neg_spread, "gaps": gaps,
              "median_spread_close": df["spread_close"].median(), "rows_written": written}
    report_path = write_report(report, silver, f"oanda_{symbol}")
    return {"rows_1m": df.height, "first": str(report["first_ts_utc"]),
            "last": str(report["last_ts_utc"]), "invalid_dropped": val["dropped_invalid_ohlc"],
            "unexpected_gaps": gaps["gaps_unexpected_gt_90m"], "report": str(report_path)}


def run_oanda(session: Session | None, universe: Universe, data_root: Path,
              symbols: list[str], start: datetime, end: datetime | None = None,
              workers: int = 4) -> dict:
    oanda = OandaProvider()
    end = end or datetime.now(UTC)
    results: dict[str, dict] = {}
    with track_job(session, PROVIDER, "candles_1m",
                   {"symbols": symbols, "start": start.isoformat()}) as stats:
        todo = {s: universe.instruments[s].oanda_symbol for s in symbols}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(fetch_instrument, oanda, o, start, end, data_root): s
                    for s, o in todo.items()}
            for f in as_completed(futs):
                s = futs[f]
                try:
                    results[s] = {"fetch": f.result()}
                    log.info("oanda %s fetched: %s", s, results[s]["fetch"])
                except Exception as e:  # one instrument failing must not hide the others
                    results[s] = {"error": str(e)[:500]}
                    stats.warnings.append(f"{s}: {e}"[:300])
        for s, o in todo.items():
            if "error" in results[s]:
                continue
            try:
                results[s]["silver"] = build_silver(data_root, o, s)
            except Exception as e:
                results[s]["error"] = str(e)[:500]
                stats.warnings.append(f"{s} silver: {e}"[:300])
        stats.rows_fetched = sum(r.get("fetch", {}).get("rows", 0) for r in results.values())
        stats.rows_written = sum(r.get("silver", {}).get("rows_1m", 0) for r in results.values())
        stats.details = results
    return results
