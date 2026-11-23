"""Import every model so Base.metadata is complete (used by Alembic and tests)."""

from app.models.analysis import (
    EventFeature,
    EventStudy,
    HistoricalPattern,
    SynchronizedEventWindow,
)
from app.models.economic import EconomicEvent, EconomicEventSnapshot, MacroIndicator
from app.models.market import MarketCandle, MarketInstrument
from app.models.ml import ModelEvaluationResult, ModelPrediction, ModelRegistry
from app.models.ops import DataProviderRegistry, IngestionJob

__all__ = [
    "DataProviderRegistry",
    "EconomicEvent",
    "EconomicEventSnapshot",
    "EventFeature",
    "EventStudy",
    "HistoricalPattern",
    "IngestionJob",
    "MacroIndicator",
    "MarketCandle",
    "MarketInstrument",
    "ModelEvaluationResult",
    "ModelPrediction",
    "ModelRegistry",
    "SynchronizedEventWindow",
]
