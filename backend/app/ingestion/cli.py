"""Ingestion command line.

  uv run python -m app.ingestion.cli prices --source kaggle_octafx_xauusd
  uv run python -m app.ingestion.cli fred-events --priority --start 2004-01-01
  uv run python -m app.ingestion.cli tz-check --source kaggle_octafx_xauusd

--database-url overrides DATABASE_URL (e.g. sqlite:///dev.db for a quick local run).
"""

import argparse
import json
from datetime import UTC, date, datetime, time

import polars as pl
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.universe import get_universe
from app.database.base import Base


def _session(url: str | None) -> Session | None:
    url = url or get_settings().database_url
    if not url:
        return None
    engine = create_engine(url)
    if url.startswith("sqlite"):
        import app.models  # noqa: F401

        Base.metadata.create_all(engine)  # dev convenience; Postgres uses Alembic
    return Session(engine, expire_on_commit=False)


def cmd_prices(a) -> None:
    from app.ingestion.price_pipeline import run_file_source
    from app.providers.market.metatrader_csv import load_file_sources

    cfg = load_file_sources()[a.source]
    rep = run_file_source(cfg, get_settings().resolved_data_dir(), _session(a.database_url))
    print(json.dumps({k: rep[k] for k in ("first_ts_utc", "last_ts_utc", "timezone_conversion",
                                          "rows_written", "report_path")}, default=str, indent=2))
    v, g = rep["validation"], rep["gaps"]
    print(f"invalid OHLC dropped: {v['dropped_invalid_ohlc']}, duplicate ts: "
          f"{v['duplicate_timestamps']} ({v['duplicate_conflicting']} conflicting), "
          f"spikes flagged: {len(v['flagged_spikes'])}, unexpected gaps >90m: "
          f"{g['gaps_unexpected_gt_90m']}")


def cmd_fred_events(a) -> None:
    from app.ingestion.fred_pipeline import run_fred_events
    from app.providers.macro.fred import FredProvider

    u = get_universe()
    keys = a.indicators or ([i.key for i in u.priority_indicators()] if a.priority else
                            [k for k, i in u.indicators.items()
                             if u.releases[i.release].provider == "fred"])
    session = _session(a.database_url)
    if session is None:
        raise SystemExit("DATABASE_URL not set; pass --database-url (e.g. sqlite:///dev.db)")
    end = date.fromisoformat(a.end) if a.end else datetime.now(UTC).date()
    summary = run_fred_events(session, u, FredProvider(), keys, date.fromisoformat(a.start), end,
                              get_settings().resolved_data_dir())
    print(json.dumps(summary, indent=2, default=str))


def cmd_fomc(a) -> None:
    from app.ingestion.fomc_pipeline import run_fomc

    session = _session(a.database_url)
    if session is None:
        raise SystemExit("DATABASE_URL not set; pass --database-url (e.g. sqlite:///dev.db)")
    end = date.fromisoformat(a.end) if a.end else date(datetime.now(UTC).year + 1, 12, 31)
    print(json.dumps(run_fomc(session, get_universe(), date.fromisoformat(a.start), end),
                     indent=2, default=str))


def cmd_windows(a) -> None:
    from app.event_engine.runner import run_windows

    session = _session(a.database_url)
    if session is None:
        raise SystemExit("DATABASE_URL not set; pass --database-url (e.g. sqlite:///dev.db)")
    print(json.dumps(run_windows(session, get_universe(), a.provider, a.instrument), indent=2))


def cmd_macro(a) -> None:
    from app.ingestion.macro_context import run_macro_context

    print(json.dumps(run_macro_context(_session(a.database_url), get_universe(),
                                       get_settings().resolved_data_dir(),
                                       date.fromisoformat(a.start), datetime.now(UTC).date()),
                     indent=2))


def cmd_train(a) -> None:
    from app.core.config import REPO_ROOT
    from app.prediction_engine.train import format_summary, run_training

    session = _session(a.database_url)
    if session is None:
        raise SystemExit("DATABASE_URL not set; pass --database-url (e.g. sqlite:///dev.db)")
    out = run_training(session, a.instrument, a.provider, get_settings().resolved_data_dir(),
                       REPO_ROOT / "models")
    if a.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        print(format_summary(out))


def cmd_upcoming(a) -> None:
    from app.ingestion.upcoming import run_upcoming

    print(json.dumps(run_upcoming(_require_session(a), get_universe(), a.days), indent=2))


def cmd_evaluate(a) -> None:
    from app.prediction_engine.base_rate import evaluate_pending

    print(json.dumps(evaluate_pending(_require_session(a)), indent=2))


def cmd_scheduler(a) -> None:
    from app.scheduler.runner import run_scheduler

    run_scheduler(_require_session(a), once=a.once)


def _require_session(a) -> Session:
    s = _session(a.database_url)
    if s is None:
        raise SystemExit("DATABASE_URL not set; pass --database-url (e.g. sqlite:///dev.db)")
    return s


def cmd_oanda(a) -> None:
    from app.ingestion.oanda_pipeline import run_oanda

    u = get_universe()
    symbols = a.symbols or list(u.instruments)
    start = datetime.fromisoformat(a.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(a.end).replace(tzinfo=UTC) if a.end else None
    out = run_oanda(_session(a.database_url), u, get_settings().resolved_data_dir(), symbols,
                    start, end, workers=a.workers)
    print(json.dumps(out, indent=2, default=str))


def cmd_tz_check(a) -> None:
    from app.ingestion.fred_events import VintageStore
    from app.ingestion.tz_detect import score_dates, summarize_runs
    from app.providers.macro.fred import FredProvider
    from app.providers.market.metatrader_csv import load_file_sources
    from app.utils.timeutils import ny_local_to_utc

    cfg = load_file_sources()[a.source]
    f = FredProvider()
    days = set()
    for sid in ("PAYEMS", "CPIAUCSL", "PCEPILFE", "RSAFS"):  # all 08:30 ET releases
        st = VintageStore(f.observations(sid, date(2000, 1, 1), date.today()))
        days |= {d for p in st.obs_dates if (d := st.first_published(p))}
    bars = pl.scan_csv(cfg.path, separator=";").select(
        pl.col("Date").str.strptime(pl.Datetime, "%Y.%m.%d %H:%M").alias("t"), "Close").collect()
    lo, hi = bars["t"].min().date(), bars["t"].max().date()
    instants = [ny_local_to_utc(d, time(8, 30)) for d in days if lo <= d <= hi]
    cands = dict(kv.split("=") for kv in a.candidates.split(","))
    verdicts = score_dates(bars, instants, cands)
    for run in summarize_runs(verdicts):
        print(*run)
    print(f"informative dates: {len(verdicts)}, decided: {sum(1 for v in verdicts if v.winner)}")


def main() -> None:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    p = argparse.ArgumentParser(prog="macropulse-ingest")
    p.add_argument("--database-url")
    sub = p.add_subparsers(required=True)

    sp = sub.add_parser("prices", help="ingest a file-based price source to silver Parquet")
    sp.add_argument("--source", required=True)
    sp.set_defaults(fn=cmd_prices)

    sf = sub.add_parser("fred-events", help="build economic events from FRED/ALFRED vintages")
    sf.add_argument("--indicators", nargs="*")
    sf.add_argument("--priority", action="store_true", help="milestone-1 indicators only")
    sf.add_argument("--start", default="2004-01-01")
    sf.add_argument("--end")
    sf.set_defaults(fn=cmd_fred_events)

    so = sub.add_parser("fomc", help="FOMC decisions from the Fed calendar + FRED rates")
    so.add_argument("--start", default="2004-01-01")
    so.add_argument("--end")
    so.set_defaults(fn=cmd_fomc)

    sw = sub.add_parser("windows", help="compute event price windows for one price source")
    sw.add_argument("--provider", default="kaggle_octafx_xauusd")
    sw.add_argument("--instrument", default="XAUUSD")
    sw.set_defaults(fn=cmd_windows)

    sm = sub.add_parser("macro", help="daily yields/VIX/USD index from FRED to silver")
    sm.add_argument("--start", default="2003-01-01")
    sm.set_defaults(fn=cmd_macro)

    sx = sub.add_parser("train", help="train/evaluate baseline models (walk-forward)")
    sx.add_argument("--provider", default="kaggle_octafx_xauusd")
    sx.add_argument("--instrument", default="XAUUSD")
    sx.add_argument("--json", action="store_true")
    sx.set_defaults(fn=cmd_train)

    su = sub.add_parser("upcoming", help="scheduled future releases from the FRED calendar")
    su.add_argument("--days", type=int, default=75)
    su.set_defaults(fn=cmd_upcoming)

    se = sub.add_parser("evaluate", help="score stored predictions whose outcome is known")
    se.set_defaults(fn=cmd_evaluate)

    sc = sub.add_parser("scheduler", help="run periodic update jobs (Ctrl-C to stop)")
    sc.add_argument("--once", action="store_true", help="run every job once and exit")
    sc.set_defaults(fn=cmd_scheduler)

    sa = sub.add_parser("oanda", help="OANDA 1m bid/ask/mid history (resumable) -> silver")
    sa.add_argument("--symbols", nargs="*", help="e.g. EURUSD XAUUSD (default: all)")
    sa.add_argument("--start", default="2005-01-01")
    sa.add_argument("--end")
    sa.add_argument("--workers", type=int, default=4)
    sa.set_defaults(fn=cmd_oanda)

    st = sub.add_parser("tz-check", help="infer a price file's clock from release spikes")
    st.add_argument("--source", required=True)
    st.add_argument("--candidates", default="CET=Europe/Berlin,EET=Europe/Athens")
    st.set_defaults(fn=cmd_tz_check)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
