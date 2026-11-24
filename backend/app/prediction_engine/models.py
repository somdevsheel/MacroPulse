"""Baseline model zoo. Hyperparameters are FIXED and deliberately conservative (shallow trees,
strong regularisation) -- with ~900 samples there is no room for tuning without overfitting the
validation years. Every model is compared against a naive prior baseline.
"""

import numpy as np
from lightgbm import LGBMClassifier, LGBMRegressor
from sklearn.base import BaseEstimator, ClassifierMixin, RegressorMixin
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier, XGBRegressor

CLASSES = np.array([-1, 0, 1])  # bearish, neutral, bullish
SEED = 7


class PriorClassifier(ClassifierMixin, BaseEstimator):
    """Predicts the training-set class frequencies of the sample's release type
    (falls back to overall frequencies). The bar every model has to clear."""

    def __init__(self, group_cols: tuple[int, ...] = ()):
        self.group_cols = group_cols

    def fit(self, X, y):
        self.classes_ = CLASSES
        y = np.asarray(y)
        self.overall_ = np.array([(y == c).mean() for c in CLASSES])
        self.by_group_ = {}
        for j in self.group_cols:
            m = X[:, j] == 1
            if m.sum() >= 10:
                self.by_group_[j] = np.array([(y[m] == c).mean() for c in CLASSES])
        return self

    def predict_proba(self, X):
        out = np.tile(self.overall_, (len(X), 1))
        for j, p in self.by_group_.items():
            out[X[:, j] == 1] = p
        return out

    def predict(self, X):
        return CLASSES[self.predict_proba(X).argmax(1)]


class PriorRegressor(RegressorMixin, BaseEstimator):
    """Mean of the target per release type in the training data."""

    def __init__(self, group_cols: tuple[int, ...] = ()):
        self.group_cols = group_cols

    def fit(self, X, y):
        y = np.asarray(y, dtype=float)
        self.overall_ = float(y.mean())
        self.by_group_ = {j: float(y[X[:, j] == 1].mean()) for j in self.group_cols
                          if (X[:, j] == 1).sum() >= 10}
        return self

    def predict(self, X):
        out = np.full(len(X), self.overall_)
        for j, v in self.by_group_.items():
            out[X[:, j] == 1] = v
        return out


class _Shift(ClassifierMixin, BaseEstimator):
    """Wrap a classifier that needs labels 0..K-1 (XGBoost)."""

    def __init__(self, est):
        self.est = est

    def fit(self, X, y):
        self.classes_ = CLASSES
        self.est.fit(X, np.searchsorted(CLASSES, y))
        return self

    def predict_proba(self, X):
        p = self.est.predict_proba(X)
        if p.shape[1] < len(CLASSES):  # a class absent from a training fold
            full = np.zeros((len(X), len(CLASSES)))
            full[:, self.est.classes_] = p
            p = full
        p = p.astype(np.float64)
        return p / p.sum(1, keepdims=True)  # float32 output may not sum exactly to 1

    def predict(self, X):
        return CLASSES[self.predict_proba(X).argmax(1)]


def classifiers(group_cols: tuple[int, ...]) -> dict:
    imp = lambda: SimpleImputer(strategy="median", keep_empty_features=True)  # noqa: E731
    return {
        "prior": PriorClassifier(group_cols),
        "logreg": make_pipeline(imp(), StandardScaler(),
                                LogisticRegression(C=0.1, max_iter=2000)),
        "random_forest": make_pipeline(imp(), RandomForestClassifier(
            n_estimators=400, max_depth=4, min_samples_leaf=20, random_state=SEED, n_jobs=-1)),
        "xgboost": _Shift(XGBClassifier(
            n_estimators=200, max_depth=2, learning_rate=0.03, subsample=0.8,
            colsample_bytree=0.8, reg_lambda=5.0, random_state=SEED, n_jobs=4,
            objective="multi:softprob", eval_metric="mlogloss")),
        "lightgbm": LGBMClassifier(
            n_estimators=200, num_leaves=4, learning_rate=0.03, min_child_samples=30,
            subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=5.0,
            random_state=SEED, verbose=-1),
    }


def regressors(group_cols: tuple[int, ...]) -> dict:
    imp = lambda: SimpleImputer(strategy="median", keep_empty_features=True)  # noqa: E731
    return {
        "prior": PriorRegressor(group_cols),
        "ridge": make_pipeline(imp(), StandardScaler(), Ridge(alpha=10.0)),
        "random_forest": make_pipeline(imp(), RandomForestRegressor(
            n_estimators=400, max_depth=4, min_samples_leaf=20, random_state=SEED, n_jobs=-1)),
        "xgboost": XGBRegressor(n_estimators=200, max_depth=2, learning_rate=0.03,
                                subsample=0.8, colsample_bytree=0.8, reg_lambda=5.0,
                                random_state=SEED, n_jobs=4),
        "lightgbm": LGBMRegressor(n_estimators=200, num_leaves=4, learning_rate=0.03,
                                  min_child_samples=30, subsample=0.8, subsample_freq=1,
                                  colsample_bytree=0.8, reg_lambda=5.0, random_state=SEED,
                                  verbose=-1),
    }
