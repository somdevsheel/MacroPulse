"""Periodic data updates. Run:  python -m app.ingestion.cli scheduler   (or --once)

Each job is recorded in ingestion_jobs by the pipeline it calls; a failing job is logged and
retried at its next interval -- it never stops the other jobs and is never silently ignored.

No live price feed is configured, so post-event price windows / prediction evaluation only
progress when new price data is ingested (e.g. an OANDA adapter).
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.universe import get_universe

log = logging.getLogger("scheduler")


@dataclass
class Job:
    name: str
    every: timedelta
    fn: Callable[[Session], object]
    next_run: datetime | None = None


def _jobs() -> list[Job]:
    from app.event_engine.runner import run_windows
    from app.ingestion.fomc_pipeline import run_fomc
    from app.ingestion.fred_pipeline import run_fred_events
    from app.ingestion.macro_context import run_macro_context
    from app.ingestion.upcoming import run_upcoming
    from app.prediction_engine.base_rate import evaluate_pending
    from app.providers.macro.fred import FredProvider
    from app.services.price_store import available_sources

    u = get_universe()
    data = get_settings().resolved_data_dir()
    today = lambda: datetime.now(UTC).date()  # noqa: E731

    def fred(s):
        keys = sorted({k for k in (i.key for i in u.priority_indicators())
                       if u.releases[u.indicators[k].release].provider == "fred"
                       and k != "fomc_rate_upper"})
        return run_fred_events(s, u, FredProvider(), keys, today() - timedelta(days=400),
                               today(), data)

    def oanda_incremental(s):
        from app.core.config import get_settings as _gs
        from app.ingestion.oanda_pipeline import run_oanda
        from app.providers.market.oanda import OandaProvider

        if not OandaProvider().is_configured():
            return "skipped: OANDA_API_TOKEN not configured"
        now = datetime.now(UTC)
        start = datetime(now.year - (now.month == 1), (now.month - 2) % 12 + 1, 1, tzinfo=UTC)
        out = run_oanda(s, u, _gs().resolved_data_dir(), list(u.instruments), start, now)
        res = {sym: (r.get("error") or r["silver"]["last"]) for sym, r in out.items()}
        for sym in u.instruments:
            if "error" not in out.get(sym, {"error": 1}):
                run_windows(s, u, "oanda", sym)
        return res

    def windows(s):
        return [run_windows(s, u, src["provider"], src["instrument"])
                for src in available_sources() if src["timeframe"] == "1m"]

    return [
        Job("fred_events", timedelta(hours=6), fred),
        Job("upcoming_calendar", timedelta(hours=6), lambda s: run_upcoming(s, u)),
        Job("fomc", timedelta(hours=24),
            lambda s: run_fomc(s, u, date(today().year - 1, 1, 1), date(today().year + 1, 12, 31))),
        Job("macro_context", timedelta(hours=24),
            lambda s: run_macro_context(s, u, data, date(2003, 1, 1), today())),
        Job("event_windows", timedelta(hours=24), windows),
        Job("oanda_prices", timedelta(hours=1), oanda_incremental),
        Job("evaluate_predictions", timedelta(hours=1), evaluate_pending),
    ]


def run_scheduler(session: Session, once: bool = False, tick_seconds: int = 60) -> None:
    jobs = _jobs()
    log.info("scheduler started with jobs: %s", [j.name for j in jobs])
    while True:
        now = datetime.now(UTC)
        for j in jobs:
            if j.next_run and now < j.next_run:
                continue
            try:
                result = j.fn(session)
                log.info("job %s ok: %s", j.name, str(result)[:300])
            except Exception:
                session.rollback()
                log.exception("job %s failed; retry at next interval", j.name)
            j.next_run = now + j.every
        if once:
            return
        time.sleep(tick_seconds)
