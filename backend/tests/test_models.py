"""Schema behaviour on SQLite (constraints are dialect-neutral). Postgres-specific checks are
in test_migrations.py."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.models as m
from app.database.base import Base


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _event(**kw) -> m.EconomicEvent:
    base = dict(
        indicator_key="cpi_mom", release_key="cpi", event_name="CPI m/m",
        event_category="inflation", importance="high",
        scheduled_release_time=datetime(2024, 3, 12, 12, 30, tzinfo=UTC),
        reference_period=date(2024, 2, 1), unit="%", source="fred",
    )
    return m.EconomicEvent(**(base | kw))


def test_all_required_tables_exist():
    required = {
        "economic_events", "economic_event_snapshots", "market_instruments", "market_candles",
        "macro_indicators", "synchronized_event_windows", "event_features", "event_studies",
        "historical_patterns", "model_registry", "model_predictions",
        "model_evaluation_results", "data_provider_registry", "ingestion_jobs",
    }
    assert required <= set(Base.metadata.tables)


def test_event_unique_per_indicator_period_source(session):
    session.add_all([_event(), _event()])
    with pytest.raises(IntegrityError):
        session.commit()


def test_snapshots_append_not_overwrite(session):
    ev = _event(actual_value=Decimal("0.4"), previous_value=Decimal("0.3"))
    session.add(ev)
    session.flush()
    t0 = datetime(2024, 3, 12, 12, 30, tzinfo=UTC)
    session.add_all([
        m.EconomicEventSnapshot(event_id=ev.event_id, snapshot_kind="release",
                                source_timestamp=t0, actual_value=Decimal("0.4"), provider="fred"),
        m.EconomicEventSnapshot(event_id=ev.event_id, snapshot_kind="revision",
                                source_timestamp=t0 + timedelta(days=30),
                                actual_value=Decimal("0.3"), provider="fred"),
    ])
    session.commit()
    vals = session.scalars(
        select(m.EconomicEventSnapshot.actual_value)
        .where(m.EconomicEventSnapshot.event_id == ev.event_id)
        .order_by(m.EconomicEventSnapshot.source_timestamp)
    ).all()
    assert [float(v) for v in vals] == [0.4, 0.3]
    assert float(session.get(m.EconomicEvent, ev.event_id).actual_value) == 0.4  # original kept


def test_prediction_cannot_use_future_features(session):
    ev = _event()
    inst = m.MarketInstrument(symbol="XAUUSD", display_name="XAU/USD", asset_class="metal",
                              base_currency="XAU", quote_currency="USD",
                              pip_size=Decimal("0.01"), price_precision=2)
    model = m.ModelRegistry(model_name="baseline", version="0.1", algorithm="logreg",
                            phase="pre_release", target="direction_15m", feature_set_version="v1")
    session.add_all([ev, inst, model])
    session.flush()
    t = datetime(2024, 3, 12, 12, 0, tzinfo=UTC)
    session.add(m.ModelPrediction(
        event_id=ev.event_id, instrument_id=inst.instrument_id, model_id=model.model_id,
        phase="pre_release", horizon_minutes=15, prediction_ts=t,
        features_as_of=t + timedelta(minutes=1),  # leak!
    ))
    with pytest.raises(IntegrityError):
        session.commit()
