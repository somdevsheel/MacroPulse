"""Economic announcements and their point-in-time history."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, JSONType, TimestampMixin, UTCDateTime, utcnow


class EconomicEvent(TimestampMixin, Base):
    """One announcement of one indicator for one reference period (e.g. CPI m/m for 2024-03).

    Value semantics (all as FIRST published at actual_release_time):
      actual_value            value for reference_period in the release vintage
      previous_value          prior period's value as it was known BEFORE this release
      revised_previous_value  prior period's value as restated IN this release (null if unchanged
                              or unknown). previous_value is never overwritten by a revision.
      consensus_forecast      market consensus; NULL unless a consensus provider supplied it.
                              Official sources never populate it.
    Later revisions to actual_value are captured in economic_event_snapshots, not here.
    """

    __tablename__ = "economic_events"
    __table_args__ = (
        UniqueConstraint("indicator_key", "reference_period", "source"),
        Index("ix_economic_events_scheduled", "scheduled_release_time"),
    )

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(128))
    indicator_key: Mapped[str] = mapped_column(String(64), index=True)  # config/events.yaml
    release_key: Mapped[str] = mapped_column(String(64), index=True)
    event_name: Mapped[str] = mapped_column(String(200))
    event_category: Mapped[str] = mapped_column(String(32))
    country: Mapped[str] = mapped_column(String(8), default="US")
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    importance: Mapped[str] = mapped_column(String(8))

    scheduled_release_time: Mapped[datetime] = mapped_column(UTCDateTime)
    actual_release_time: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # False when the intraday time is inferred from config but not verified for that date.
    release_time_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    # How scheduled_release_time was established:
    #   config          standard time from config/events.yaml (not checked for this date)
    #   empirical_spike confirmed by a 1-minute price spike at that minute (see details)
    #   official        stated by the publisher for this specific release
    #   unknown         date known, intraday time not established -> excluded from studies
    release_time_source: Mapped[str] = mapped_column(
        String(16), default="config", server_default="config")
    # scheduled_release | fomc_scheduled | fomc_unscheduled | fomc_conference_call
    event_kind: Mapped[str] = mapped_column(
        String(24), default="scheduled_release", server_default="scheduled_release")
    details: Mapped[dict | None] = mapped_column(JSONType)
    reference_period: Mapped[date] = mapped_column(Date)

    actual_value: Mapped[Decimal | None] = mapped_column(Numeric)
    consensus_forecast: Mapped[Decimal | None] = mapped_column(Numeric)
    consensus_source: Mapped[str | None] = mapped_column(String(64))
    previous_value: Mapped[Decimal | None] = mapped_column(Numeric)
    revised_previous_value: Mapped[Decimal | None] = mapped_column(Numeric)
    unit: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(64))  # provider that supplied actual_value

    snapshots: Mapped[list["EconomicEventSnapshot"]] = relationship(back_populates="event")


class EconomicEventSnapshot(Base):
    """Append-only history. Every provider update is a new row; nothing is overwritten.

    snapshot_timestamp: when WE captured it.
    source_timestamp:   when the information became public (e.g. ALFRED realtime_start,
                        provider's last-update time). Point-in-time queries filter on this.
    """

    __tablename__ = "economic_event_snapshots"
    __table_args__ = (
        UniqueConstraint("event_id", "provider", "source_timestamp", "snapshot_kind"),
        Index("ix_snapshots_event_known", "event_id", "source_timestamp"),
    )

    snapshot_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("economic_events.event_id"))
    snapshot_kind: Mapped[str] = mapped_column(String(16))  # forecast | release | revision
    snapshot_timestamp: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    source_timestamp: Mapped[datetime] = mapped_column(UTCDateTime)
    forecast_value: Mapped[Decimal | None] = mapped_column(Numeric)
    previous_value: Mapped[Decimal | None] = mapped_column(Numeric)
    revised_previous_value: Mapped[Decimal | None] = mapped_column(Numeric)
    actual_value: Mapped[Decimal | None] = mapped_column(Numeric)
    provider: Mapped[str] = mapped_column(String(64))
    raw: Mapped[dict | None] = mapped_column(JSONType)
    ingestion_job_id: Mapped[int | None] = mapped_column(ForeignKey("ingestion_jobs.job_id"))

    event: Mapped[EconomicEvent] = relationship(back_populates="snapshots")


class MacroIndicator(Base):
    """Vintage-aware macro observations (FRED/ALFRED).

    A row is the value of `series_id` for `observation_date` as known during
    [realtime_start, realtime_end]. Point-in-time lookup at T: realtime_start <= T.date() and
    (realtime_end is NULL or realtime_end >= T.date()).
    """

    __tablename__ = "macro_indicators"
    __table_args__ = (
        UniqueConstraint("series_id", "observation_date", "realtime_start", "source"),
        Index("ix_macro_pit", "series_id", "observation_date", "realtime_start"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    series_id: Mapped[str] = mapped_column(String(64))
    observation_date: Mapped[date] = mapped_column(Date)
    value: Mapped[Decimal | None] = mapped_column(Numeric)  # NULL = provider reported missing
    realtime_start: Mapped[date] = mapped_column(Date)
    realtime_end: Mapped[date | None] = mapped_column(Date)  # NULL = still current
    unit: Mapped[str | None] = mapped_column(String(64))
    frequency: Mapped[str | None] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(32), default="fred")
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
