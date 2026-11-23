from datetime import date

import pytest
import yaml

from app.core.config import CONFIG_DIR
from app.core.universe import load_universe


@pytest.fixture(scope="module")
def u():
    return load_universe()


def test_milestone_indicators_are_priority(u):
    keys = {i.key for i in u.priority_indicators()}
    for required in ["cpi_mom", "core_cpi_mom", "core_pce_mom", "nfp", "unemployment_rate",
                     "fomc_rate_upper"]:
        assert required in keys


def test_all_seven_instruments(u):
    assert set(u.instruments) == {
        "XAUUSD", "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "USDCAD", "AUDUSD"
    }


def test_simultaneous_indicators_share_release(u):
    nfp_release = {i.key for i in u.indicators_for_release("employment_situation")}
    assert {"nfp", "unemployment_rate", "avg_hourly_earnings_mom"} <= nfp_release


def test_scheduled_utc_and_reliability(u):
    fomc = u.releases["fomc_statement"]
    assert fomc.scheduled_utc(date(2024, 1, 31)).hour == 19  # 14:00 EST
    assert not fomc.time_is_reliable(date(2012, 6, 20))
    assert fomc.time_is_reliable(date(2024, 1, 31))


def test_unknown_release_reference_fails(tmp_path):
    events = yaml.safe_load((CONFIG_DIR / "events.yaml").read_text())
    events["indicators"]["bogus"] = {
        "name": "x", "release": "nope", "category": "x", "importance": "low",
        "fred_series_id": "X", "transform": "level", "unit": "x",
    }
    (tmp_path / "events.yaml").write_text(yaml.safe_dump(events))
    (tmp_path / "instruments.yaml").write_text((CONFIG_DIR / "instruments.yaml").read_text())
    with pytest.raises(ValueError, match="unknown release"):
        load_universe(tmp_path)
