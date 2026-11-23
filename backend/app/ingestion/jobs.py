"""Ingestion job tracking: every run is recorded in ingestion_jobs (when a DB session is given)
and logged. Failures are re-raised after being recorded -- never swallowed."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.database.base import utcnow
from app.models import IngestionJob

log = logging.getLogger("ingestion")


@dataclass
class JobStats:
    rows_fetched: int = 0
    rows_written: int = 0
    warnings: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)
    job_id: int | None = None


@contextmanager
def track_job(
    session: Session | None, provider_key: str, job_type: str, params: dict | None = None
) -> Iterator[JobStats]:
    stats = JobStats()
    job = None
    if session is not None:
        job = IngestionJob(provider_key=provider_key, job_type=job_type, params=params or {},
                           status="running", attempts=1, started_at=utcnow())
        session.add(job)
        session.commit()
        stats.job_id = job.job_id
    log.info("job start provider=%s type=%s params=%s", provider_key, job_type, params)
    try:
        yield stats
    except Exception as e:
        log.exception("job failed provider=%s type=%s", provider_key, job_type)
        if job is not None:
            session.rollback()
            job.status, job.error_message, job.finished_at = "failed", str(e)[:4000], utcnow()
            job.rows_fetched, job.rows_written = stats.rows_fetched, stats.rows_written
            session.add(job)
            session.commit()
        raise
    status = "partial" if stats.warnings else "succeeded"
    log.info("job %s provider=%s type=%s fetched=%d written=%d warnings=%d", status,
             provider_key, job_type, stats.rows_fetched, stats.rows_written, len(stats.warnings))
    if job is not None:
        job.status, job.finished_at = status, utcnow()
        job.rows_fetched, job.rows_written = stats.rows_fetched, stats.rows_written
        if stats.warnings:
            job.error_message = "; ".join(stats.warnings)[:4000]
        job.params = {**(params or {}), "details": stats.details}
        session.commit()
