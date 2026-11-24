"""Chronological validation: expanding-window walk-forward by calendar year + a fixed
train / validation / test split. No random splits, ever.

Embargo: a training sample must be released at least EMBARGO before the first test sample.
Targets span at most 4 hours, so a 1-day embargo guarantees no training target overlaps a test
window.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np
from sklearn.base import clone
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    log_loss,
    mean_absolute_error,
    roc_auc_score,
)

from app.prediction_engine.models import CLASSES

EMBARGO = timedelta(days=1)


@dataclass(frozen=True)
class Fold:
    name: str
    train_end: datetime  # exclusive (before embargo)
    test_start: datetime
    test_end: datetime  # exclusive


def yearly_folds(first_test_year: int, last_test_year: int) -> list[Fold]:
    out = []
    for y in range(first_test_year, last_test_year + 1):
        s = datetime(y, 1, 1, tzinfo=UTC)
        out.append(Fold(str(y), s - EMBARGO, s, datetime(y + 1, 1, 1, tzinfo=UTC)))
    return out


def fixed_split(train_end_year=2021, val=(2022, 2023), test=(2024, 2025)) -> dict[str, Fold]:
    v0 = datetime(val[0], 1, 1, tzinfo=UTC)
    t0 = datetime(test[0], 1, 1, tzinfo=UTC)
    return {
        "validation": Fold("validation", v0 - EMBARGO, v0, datetime(val[1] + 1, 1, 1, tzinfo=UTC)),
        "test": Fold("test", t0 - EMBARGO, t0, datetime(test[1] + 1, 1, 1, tzinfo=UTC)),
    }


def brier_multiclass(y: np.ndarray, p: np.ndarray) -> float:
    onehot = (y[:, None] == CLASSES[None, :]).astype(float)
    return float(((p - onehot) ** 2).sum(1).mean())


def calibration_table(y: np.ndarray, p_bull: np.ndarray, bins: int = 5) -> list[dict]:
    edges = np.quantile(p_bull, np.linspace(0, 1, bins + 1))
    out = []
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        m = (p_bull >= lo) & ((p_bull <= hi) if i == bins - 1 else (p_bull < hi))
        if m.sum():
            out.append({"p_mean": float(p_bull[m].mean()), "observed": float((y[m] == 1).mean()),
                        "n": int(m.sum())})
    return out


def _clip_norm(p: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    """Avoid log(0) for hard 0 probabilities, then renormalise rows to sum to 1."""
    q = np.clip(p, eps, 1)
    return q / q.sum(1, keepdims=True)


def classification_metrics(y: np.ndarray, p: np.ndarray) -> dict:
    pred = CLASSES[p.argmax(1)]
    out = {"n": len(y), "accuracy": accuracy_score(y, pred),
           "macro_f1": f1_score(y, pred, average="macro", labels=CLASSES, zero_division=0),
           "log_loss": log_loss(y, _clip_norm(p), labels=CLASSES),
           "brier": brier_multiclass(y, p)}
    try:
        out["roc_auc_ovr"] = roc_auc_score(y, p, multi_class="ovr", labels=CLASSES)
    except ValueError:
        out["roc_auc_ovr"] = None
    # Directional hit rate on non-neutral outcomes, predicting the likelier of up/down.
    nn = y != 0
    if nn.any():
        out["directional_hit_rate"] = float(
            (np.where(p[nn, 2] >= p[nn, 0], 1, -1) == y[nn]).mean())
    return {k: (float(v) if v is not None else None) for k, v in out.items()}


def regression_metrics(y: np.ndarray, yhat: np.ndarray) -> dict:
    return {"n": len(y), "mae": float(mean_absolute_error(y, yhat)),
            "rmse": float(np.sqrt(np.mean((y - yhat) ** 2))),
            "corr": float(np.corrcoef(y, yhat)[0, 1]) if len(y) > 2 and yhat.std() > 0 else None}


def run_fold(model, X: np.ndarray, y: np.ndarray, ts: np.ndarray, fold: Fold,
             predict: Callable) -> tuple[np.ndarray, np.ndarray] | None:
    tr = ts < np.datetime64(fold.train_end.replace(tzinfo=None))
    te = (ts >= np.datetime64(fold.test_start.replace(tzinfo=None))) & \
         (ts < np.datetime64(fold.test_end.replace(tzinfo=None)))
    if tr.sum() < 50 or te.sum() == 0:
        return None
    m = clone(model).fit(X[tr], y[tr])
    return np.where(te)[0], predict(m, X[te])
