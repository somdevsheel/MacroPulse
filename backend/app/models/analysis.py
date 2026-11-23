"""Event-study outputs: synchronized windows, features, aggregated studies, similar events."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, JSONType, UTCDateTime, utcnow


class SynchronizedEventWindow(Base):
    """Price behaviour of one instrument in one window around one announcement.

    window_label e.g. 'pre_60m', 'pre_1m', 'post_5m', 'post_4h'. Returns are measured from the
    last price at/before release_ts (anchor) unless noted in `details`.
    """

    __tablename__ = "synchronized_event_windows"
    __table_args__ = (
        UniqueConstraint("event_id", "instrument_id", "provider", "window_label"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("economic_events.event_id"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("market_instruments.instrument_id"))
    provider: Mapped[str] = mapped_column(String(32))
    release_ts: Mapped[datetime] = mapped_column(UTCDateTime)
    window_label: Mapped[str] = mapped_column(String(16))
    window_start: Mapped[datetime] = mapped_column(UTCDateTime)
    window_end: Mapped[datetime] = mapped_column(UTCDateTime)

    anchor_price: Mapped[Decimal | None] = mapped_column(Numeric)
    end_price: Mapped[Decimal | None] = mapped_column(Numeric)
    return_pct: Mapped[Decimal | None] = mapped_column(Numeric)
    abs_move: Mapped[Decimal | None] = mapped_column(Numeric)
    high: Mapped[Decimal | None] = mapped_column(Numeric)
    low: Mapped[Decimal | None] = mapped_column(Numeric)
    mfe_pct: Mapped[Decimal | None] = mapped_column(Numeric)  # max favourable excursion
    mae_pct: Mapped[Decimal | None] = mapped_column(Numeric)  # max adverse excursion
    realized_vol: Mapped[Decimal | None] = mapped_column(Numeric)
    minutes_to_extreme: Mapped[int | None] = mapped_column(Integer)

    candle_count: Mapped[int] = mapped_column(Integer, default=0)
    expected_candle_count: Mapped[int] = mapped_column(Integer, default=0)
    has_gaps: Mapped[bool] = mapped_column(Boolean, default=False)
    # Other events released at the same timestamp (simultaneous announcements).
    concurrent_event_ids: Mapped[list | None] = mapped_column(JSONType)
    details: Mapped[dict | None] = mapped_column(JSONType)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class EventFeature(Base):
    """Feature vector for an event at a point in time.

    as_of_ts is the information cutoff: every input must have become public at or before it.
    phase='pre_release' requires as_of_ts < scheduled_release_time (enforced in service code).
    """

    __tablename__ = "event_features"
    __table_args__ = (
        UniqueConstraint("event_id", "instrument_id", "feature_set_version", "phase"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("economic_events.event_id"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("market_instruments.instrument_id"))
    phase: Mapped[str] = mapped_column(String(16))  # pre_release | post_release
    feature_set_version: Mapped[str] = mapped_column(String(32))
    as_of_ts: Mapped[datetime] = mapped_column(UTCDateTime)
    features: Mapped[dict] = mapped_column(JSONType)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class EventStudy(Base):
    """Aggregate reaction statistics for indicator x instrument x window over a date range."""

    __tablename__ = "event_studies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    indicator_key: Mapped[str] = mapped_column(String(64), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("market_instruments.instrument_id"))
    window_label: Mapped[str] = mapped_column(String(16))
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    neutral_threshold_pct: Mapped[Decimal] = mapped_column(Numeric)

    n_observations: Mapped[int] = mapped_column(Integer)
    mean_return_pct: Mapped[Decimal | None] = mapped_column(Numeric)
    median_return_pct: Mapped[Decimal | None] = mapped_column(Numeric)
    pct_bullish: Mapped[Decimal | None] = mapped_column(Numeric)
    pct_bearish: Mapped[Decimal | None] = mapped_column(Numeric)
    pct_neutral: Mapped[Decimal | None] = mapped_column(Numeric)
    reversal_frequency: Mapped[Decimal | None] = mapped_column(Numeric)
    avg_volatility_ratio: Mapped[Decimal | None] = mapped_column(Numeric)
    max_positive_pct: Mapped[Decimal | None] = mapped_column(Numeric)
    max_negative_pct: Mapped[Decimal | None] = mapped_column(Numeric)
    stats: Mapped[dict | None] = mapped_column(JSONType)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class HistoricalPattern(Base):
    """A retrieved similar historical event. similarity_score must come from a documented
    method (see `method` + `method_params`), never an arbitrary number."""

    __tablename__ = "historical_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    query_event_id: Mapped[int] = mapped_column(
        ForeignKey("economic_events.event_id"), index=True
    )
    matched_event_id: Mapped[int] = mapped_column(ForeignKey("economic_events.event_id"))
    instrument_id: Mapped[int | None] = mapped_column(
        ForeignKey("market_instruments.instrument_id")
    )
    method: Mapped[str] = mapped_column(String(32))  # knn | kmeans | hdbscan | dtw
    feature_set_version: Mapped[str] = mapped_column(String(32))
    distance: Mapped[Decimal | None] = mapped_column(Numeric)
    similarity_score: Mapped[Decimal | None] = mapped_column(Numeric)
    rank: Mapped[int | None] = mapped_column(Integer)
    cluster_id: Mapped[int | None] = mapped_column(Integer)
    method_params: Mapped[dict | None] = mapped_column(JSONType)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
