"""Operational tables: provider registry and ingestion job log."""

from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, JSONType, TimestampMixin, UTCDateTime, utcnow


class DataProviderRegistry(TimestampMixin, Base):
    __tablename__ = "data_provider_registry"

    provider_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_key: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))  # economic | market | macro
    # connected | disconnected | degraded | error
    status: Mapped[str] = mapped_column(String(16), default="disconnected")
    requires_key: Mapped[bool] = mapped_column(Boolean, default=True)
    has_key: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    capabilities: Mapped[dict | None] = mapped_column(JSONType)
    coverage: Mapped[dict | None] = mapped_column(JSONType)
    notes: Mapped[str | None] = mapped_column(Text)


class IngestionJob(Base):
    """Every ingestion run is logged. Failures are recorded, never silently dropped."""

    __tablename__ = "ingestion_jobs"

    job_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_key: Mapped[str] = mapped_column(String(32), index=True)
    job_type: Mapped[str] = mapped_column(String(48))  # e.g. fred_vintages, candles_1m
    params: Mapped[dict | None] = mapped_column(JSONType)
    # pending | running | succeeded | partial | failed
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    rows_fetched: Mapped[int] = mapped_column(Integer, default=0)
    rows_written: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
