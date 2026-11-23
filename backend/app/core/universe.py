"""Typed loader for config/events.yaml and config/instruments.yaml.

Validation fails loudly at startup if the config is inconsistent (e.g. an indicator points at
an unknown release), instead of failing silently during ingestion.
"""

from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, field_validator, model_validator

from app.core.config import CONFIG_DIR
from app.utils.timeutils import ny_local_to_utc, parse_hhmm

Transform = Literal["level", "change", "mom_pct", "yoy_pct", "qoq_saar"]
Importance = Literal["low", "medium", "high"]


class ReleaseDef(BaseModel):
    key: str
    name: str
    provider: Literal["fred", "none"]
    fred_release_id: int | None = None
    release_time_et: time
    release_time_reliable_from: date | None = None

    @field_validator("release_time_et", mode="before")
    @classmethod
    def _parse_time(cls, v):
        return parse_hhmm(v) if isinstance(v, str) else v

    @model_validator(mode="after")
    def _fred_needs_id(self):
        if self.provider == "fred" and self.fred_release_id is None:
            raise ValueError(f"release {self.key}: provider fred requires fred_release_id")
        return self

    def scheduled_utc(self, release_date: date) -> datetime:
        return ny_local_to_utc(release_date, self.release_time_et)

    def time_is_reliable(self, release_date: date) -> bool:
        return self.release_time_reliable_from is None or release_date >= (
            self.release_time_reliable_from
        )


class IndicatorDef(BaseModel):
    key: str
    name: str
    release: str
    category: str
    importance: Importance
    priority: bool = False
    fred_series_id: str | None = None
    transform: Transform
    unit: str
    country: str = "US"
    currency: str = "USD"


class InstrumentDef(BaseModel):
    symbol: str
    display: str
    asset_class: Literal["fx", "metal", "index", "rates"]
    base: str
    quote: str
    pip_size: float
    price_precision: int
    dukascopy_symbol: str | None = None
    oanda_symbol: str | None = None


class MacroSeriesDef(BaseModel):
    series_id: str
    name: str
    unit: str
    frequency: str


class Universe(BaseModel):
    releases: dict[str, ReleaseDef]
    indicators: dict[str, IndicatorDef]
    instruments: dict[str, InstrumentDef]
    macro_context: dict[str, MacroSeriesDef]

    @model_validator(mode="after")
    def _check_refs(self):
        for ind in self.indicators.values():
            if ind.release not in self.releases:
                raise ValueError(f"indicator {ind.key} references unknown release {ind.release}")
            if self.releases[ind.release].provider == "fred" and not ind.fred_series_id:
                raise ValueError(f"indicator {ind.key}: FRED release needs fred_series_id")
        return self

    def indicators_for_release(self, release_key: str) -> list[IndicatorDef]:
        return [i for i in self.indicators.values() if i.release == release_key]

    def priority_indicators(self) -> list[IndicatorDef]:
        return [i for i in self.indicators.values() if i.priority]


def _keyed(raw: dict, key_field: str) -> dict:
    return {k: {key_field: k, **v} for k, v in (raw or {}).items()}


def load_universe(config_dir: Path = CONFIG_DIR) -> Universe:
    events = yaml.safe_load((config_dir / "events.yaml").read_text())
    instr = yaml.safe_load((config_dir / "instruments.yaml").read_text())
    return Universe(
        releases=_keyed(events["releases"], "key"),
        indicators=_keyed(events["indicators"], "key"),
        instruments=_keyed(instr["instruments"], "symbol"),
        macro_context=_keyed(instr.get("macro_context"), "series_id"),
    )


@lru_cache
def get_universe() -> Universe:
    return load_universe()
