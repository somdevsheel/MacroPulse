from datetime import UTC, date, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from app.backtesting.walkforward import (
    EMBARGO,
    classification_metrics,
    fixed_split,
    run_fold,
    yearly_folds,
)
from app.feature_engineering.dataset import _Expanding, _hourly_features, _macro_features, label
from app.prediction_engine.models import CLASSES, PriorClassifier, classifiers
from app.prediction_engine.train import paired_bootstrap


def test_yearly_folds_have_embargo_and_no_overlap():
    folds = yearly_folds(2020, 2022)
    for f in folds:
        assert f.test_start - f.train_end == EMBARGO
        assert f.train_end < f.test_start < f.test_end
    assert folds[0].test_end == folds[1].test_start


def test_fixed_split_matches_spec():
    s = fixed_split()
    assert s["validation"].test_start.year == 2022 and s["validation"].test_end.year == 2024
    assert s["test"].test_start.year == 2024 and s["test"].test_end.year == 2026


def test_run_fold_never_trains_on_test_or_embargo_period():
    seen = {}

    class Spy(PriorClassifier):
        def fit(self, X, y):
            seen["max_x"] = X[:, 0].max()
            return super().fit(X, y)

    ts = np.array([np.datetime64(datetime(2019, 1, 1) + timedelta(days=i)) for i in range(800)])
    X = np.arange(800, dtype=float)[:, None]
    y = np.random.default_rng(0).choice(CLASSES, 800)
    fold = yearly_folds(2020, 2020)[0]
    idx, _ = run_fold(Spy(), X, y, ts, fold, lambda m, x: m.predict_proba(x))
    last_train_day = (fold.train_end.replace(tzinfo=None) - datetime(2019, 1, 1)).days
    assert seen["max_x"] < last_train_day  # nothing from the embargo day or later
    assert ts[idx].min() >= np.datetime64(fold.test_start.replace(tzinfo=None))


def test_expanding_stats_use_only_past():
    e = _Expanding()
    for v in [1, 2, 3, 4, 5, 6]:
        e.add(v)
    z_before = e.z(10)
    e.add(1000)  # a future value must not affect an already computed z
    assert z_before == pytest.approx((10 - 3.5) / np.std([1, 2, 3, 4, 5, 6], ddof=1))


def test_macro_features_exclude_same_day_observation():
    macro = pl.DataFrame({"series_id": ["DGS10"] * 3,
                          "date": [date(2024, 3, 8), date(2024, 3, 11), date(2024, 3, 12)],
                          "value": [4.0, 4.1, 9.9]})
    f = _macro_features(macro, datetime(2024, 3, 12, 12, 30, tzinfo=UTC))
    assert f["DGS10"] == 4.1  # 2024-03-12's close is not known at 08:30 ET that day


def test_hourly_features_only_closed_bars():
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    h1 = pl.DataFrame({"ts": [t0 + timedelta(hours=i) for i in range(40)],
                       "close": [100.0 + i for i in range(40)]})
    t = t0 + timedelta(hours=39, minutes=30)  # bar 39 is still open at t
    f = _hourly_features(h1, t)
    assert f["ret_24h"] == pytest.approx((138 / 114 - 1) * 100)


def test_label_band():
    assert [label(x, 0.05) for x in (0.06, 0.05, -0.051, None)] == [1, 0, -1, None]


def test_prior_classifier_uses_group_frequencies():
    X = np.array([[1, 0]] * 20 + [[0, 1]] * 20, dtype=float)
    y = np.array([1] * 20 + [-1] * 20)
    p = PriorClassifier((0, 1)).fit(X, y).predict_proba(X)
    assert p[0].tolist() == [0, 0, 1] and p[-1].tolist() == [1, 0, 0]


def test_all_classifiers_return_valid_probabilities():
    rng = np.random.default_rng(1)
    X = rng.normal(size=(200, 5))
    X[:, 0] = (rng.random(200) > 0.5).astype(float)
    y = rng.choice(CLASSES, 200)
    for name, m in classifiers((0,)).items():
        p = m.fit(X, y).predict_proba(X)
        assert p.shape == (200, 3), name
        assert np.allclose(p.sum(1), 1), name
        classification_metrics(y, p)


def test_paired_bootstrap_detects_better_model():
    y = np.array([1, -1] * 100)
    good = np.where(y[:, None] == CLASSES[None, :], 0.8, 0.1)
    base = np.full((200, 3), 1 / 3)
    r = paired_bootstrap("clf", y, good, base)
    assert r["mean_diff"] < 0 and r["ci95"][1] < 0
