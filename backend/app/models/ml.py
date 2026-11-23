"""Model registry, predictions and evaluation results."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, JSONType, UTCDateTime, utcnow


class ModelRegistry(Base):
    __tablename__ = "model_registry"
    __table_args__ = (UniqueConstraint("model_name", "version"),)

    model_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_name: Mapped[str] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32))
    algorithm: Mapped[str] = mapped_column(String(32))  # logreg | random_forest | xgboost ...
    phase: Mapped[str] = mapped_column(String(16))  # pre_release | post_release
    target: Mapped[str] = mapped_column(String(64))  # direction_15m, volatility_1h ...
    feature_set_version: Mapped[str] = mapped_column(String(32))
    train_start: Mapped[date | None] = mapped_column(Date)
    train_end: Mapped[date | None] = mapped_column(Date)
    validation_start: Mapped[date | None] = mapped_column(Date)
    validation_end: Mapped[date | None] = mapped_column(Date)
    test_start: Mapped[date | None] = mapped_column(Date)
    test_end: Mapped[date | None] = mapped_column(Date)
    hyperparameters: Mapped[dict | None] = mapped_column(JSONType)
    metrics: Mapped[dict | None] = mapped_column(JSONType)
    artifact_path: Mapped[str | None] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), default="trained")  # trained|active|retired
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ModelPrediction(Base):
    """Immutable prediction record. Pre- and post-release predictions are separate rows.

    Realised outcome columns are filled later by the evaluator; the prediction columns are
    never modified after insert.
    """

    __tablename__ = "model_predictions"
    __table_args__ = (
        CheckConstraint("features_as_of <= prediction_ts", name="no_future_features"),
        CheckConstraint("phase in ('pre_release','post_release')", name="phase_valid"),
        Index("ix_predictions_event", "event_id", "instrument_id", "phase"),
    )

    prediction_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("economic_events.event_id"))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("market_instruments.instrument_id"))
    model_id: Mapped[int] = mapped_column(ForeignKey("model_registry.model_id"))
    phase: Mapped[str] = mapped_column(String(16))
    horizon_minutes: Mapped[int] = mapped_column(Integer)
    prediction_ts: Mapped[datetime] = mapped_column(UTCDateTime)
    features_as_of: Mapped[datetime] = mapped_column(UTCDateTime)

    p_bullish: Mapped[Decimal | None] = mapped_column(Numeric)
    p_bearish: Mapped[Decimal | None] = mapped_column(Numeric)
    p_neutral: Mapped[Decimal | None] = mapped_column(Numeric)
    expected_return_pct: Mapped[Decimal | None] = mapped_column(Numeric)
    expected_move: Mapped[Decimal | None] = mapped_column(Numeric)
    expected_volatility: Mapped[Decimal | None] = mapped_column(Numeric)
    p_reversal: Mapped[Decimal | None] = mapped_column(Numeric)
    p_breakout: Mapped[Decimal | None] = mapped_column(Numeric)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric)
    similar_event_ids: Mapped[list | None] = mapped_column(JSONType)

    realized_return_pct: Mapped[Decimal | None] = mapped_column(Numeric)
    realized_direction: Mapped[str | None] = mapped_column(String(8))
    evaluated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ModelEvaluationResult(Base):
    __tablename__ = "model_evaluation_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("model_registry.model_id"), index=True)
    evaluation_type: Mapped[str] = mapped_column(String(24))  # walk_forward|test|paper
    fold: Mapped[int | None] = mapped_column(Integer)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    metric_name: Mapped[str] = mapped_column(String(32))
    metric_value: Mapped[Decimal | None] = mapped_column(Numeric)
    n_samples: Mapped[int] = mapped_column(Integer)
    details: Mapped[dict | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
