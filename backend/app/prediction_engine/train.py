"""Train + evaluate baseline models for every task with chronological validation, and persist
registry entries, per-fold metrics, out-of-sample predictions and final model artifacts.

Selection protocol (no peeking at the test years):
  1. Walk-forward by year (expanding window, 1-day embargo) -> OOS predictions 2012..2025.
  2. Fixed split: fit < 2022 -> score validation 2022-2023; fit < 2024 -> score test 2024-2025.
  3. Per task, the model with the best VALIDATION score is selected; its TEST score is reported
     next to the prior baseline with a paired-bootstrap 95% CI of the difference.
  4. A selected model is marked 'active' only if (a) the paired-bootstrap 95% CI shows it beats
     the prior baseline on the walk-forward OOS predictions AND (b) it also beats it on the
     2024-2025 hold-out years. Otherwise it is stored as 'trained'.
  Across many instruments x tasks, apply a multiple-testing correction (e.g. Holm) before
  treating any single 'active' result as evidence -- see docs/ARCHITECTURE.md §8.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import polars as pl
from sklearn.base import clone
from sqlalchemy.orm import Session

from app.backtesting.walkforward import (
    calibration_table,
    classification_metrics,
    fixed_split,
    regression_metrics,
    run_fold,
    yearly_folds,
)
from app.feature_engineering.dataset import (
    FEATURE_SET_VERSION,
    NEUTRAL_PCT,
    POST_FEATURES,
    PRE_FEATURES,
    RELEASES,
    build_dataset,
)
from app.ingestion.jobs import track_job
from app.models import ModelEvaluationResult, ModelRegistry
from app.prediction_engine.models import CLASSES, classifiers, regressors

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Task:
    name: str
    phase: str
    features: list[str]
    target: str
    kind: str  # clf | reg
    horizon_min: int


TASKS = [
    Task("pre_direction_15m", "pre_release", PRE_FEATURES, "y_r_15m", "clf", 15),
    Task("pre_direction_60m", "pre_release", PRE_FEATURES, "y_r_60m", "clf", 60),
    Task("pre_volatility_60m", "pre_release", PRE_FEATURES, "abs_r_60m", "reg", 60),
    Task("post_direction_5_15m", "post_release", POST_FEATURES, "y_r_5_15m", "clf", 15),
    Task("post_direction_5_60m", "post_release", POST_FEATURES, "y_r_5_60m", "clf", 60),
]
FIRST_TEST_YEAR, LAST_TEST_YEAR = 2012, 2025
HOLDOUT_FROM_YEAR = 2024  # the fixed-split test years


def _predict(kind):
    return (lambda m, X: m.predict_proba(X)) if kind == "clf" else (lambda m, X: m.predict(X))


def _score(kind, y, p) -> dict:
    return classification_metrics(y, p) if kind == "clf" else regression_metrics(y, p)


def _loss_vec(kind, y, p) -> np.ndarray:
    if kind == "clf":
        idx = np.searchsorted(CLASSES, y.astype(int))
        return -np.log(np.clip(p[np.arange(len(y)), idx], 1e-6, 1))
    return np.abs(y - p)


def paired_bootstrap(kind, y, p_model, p_base, n=2000, seed=7) -> dict:
    """CI of mean(loss_model - loss_base). Negative = model better."""
    d = _loss_vec(kind, y, p_model) - _loss_vec(kind, y, p_base)
    rng = np.random.default_rng(seed)
    boots = np.array([d[rng.integers(0, len(d), len(d))].mean() for _ in range(n)])
    return {"mean_diff": float(d.mean()), "ci95": [float(np.quantile(boots, 0.025)),
                                                   float(np.quantile(boots, 0.975))],
            "loss": "log_loss" if kind == "clf" else "abs_error"}


def run_training(session: Session, instrument: str, provider: str, data_root: Path,
                 models_dir: Path) -> dict:
    run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{instrument}-{provider}"
    out_dir = data_root / "gold" / "backtest_results" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (models_dir / "trained").mkdir(parents=True, exist_ok=True)
    summary = {"run_id": run_id, "instrument": instrument, "provider": provider, "tasks": {}}

    with track_job(session, "prediction_engine", "train_baselines",
                   {"instrument": instrument, "provider": provider, "run": run_id}) as stats:
        df = build_dataset(session, instrument, provider, data_root)
        df.write_parquet(data_root / "gold" / "training_datasets" /
                         f"{instrument}_{FEATURE_SET_VERSION}_{run_id}.parquet", mkdir=True)
        folds = yearly_folds(FIRST_TEST_YEAR, LAST_TEST_YEAR)
        split = fixed_split()

        for task in TASKS:
            d = df.filter(pl.col(task.target).is_not_null())
            X = d.select(task.features).cast(pl.Float64).to_numpy()
            y = d[task.target].cast(pl.Float64).to_numpy()
            if task.kind == "clf":
                y = y.astype(int)
            ts = d["release_ts"].dt.replace_time_zone(None).to_numpy()
            groups = tuple(task.features.index(f"rel_{r}") for r in RELEASES)
            zoo = classifiers(groups) if task.kind == "clf" else regressors(groups)
            pred = _predict(task.kind)
            res: dict[str, dict] = {}
            oos_frames = []

            for name, model in zoo.items():
                # walk-forward
                idx_all, p_all, per_fold = [], [], {}
                for f in folds:
                    r = run_fold(model, X, y, ts, f, pred)
                    if r is None:
                        continue
                    idx, p = r
                    idx_all.append(idx)
                    p_all.append(p)
                    per_fold[f.name] = _score(task.kind, y[idx], p)
                idx_all = np.concatenate(idx_all)
                p_all = np.concatenate(p_all).astype(np.float64)
                wf = _score(task.kind, y[idx_all], p_all)
                # fixed split
                fixed = {}
                for k, f in split.items():
                    r = run_fold(model, X, y, ts, f, pred)
                    if r:
                        fixed[k] = _score(task.kind, y[r[0]], r[1])
                res[name] = {"walk_forward": wf, "per_fold": per_fold, **fixed,
                             "_idx": idx_all, "_p": p_all}
                frame = {"release_ts": d["release_ts"].to_numpy()[idx_all],
                         "release": d["release"].to_numpy()[idx_all],
                         "y": y[idx_all], "model": [name] * len(idx_all)}
                if task.kind == "clf":
                    frame |= {"p_bearish": p_all[:, 0], "p_neutral": p_all[:, 1],
                              "p_bullish": p_all[:, 2]}
                else:
                    frame["yhat"] = p_all
                oos_frames.append(pl.DataFrame(frame))

            pl.concat(oos_frames).write_parquet(out_dir / f"{task.name}.parquet")

            # selection on validation only
            key = "log_loss" if task.kind == "clf" else "mae"
            candidates = {n: r for n, r in res.items() if n != "prior" and "validation" in r}
            best = min(candidates, key=lambda n: candidates[n]["validation"][key])
            base = res["prior"]
            assert np.array_equal(base["_idx"], res[best]["_idx"])
            yb = y[base["_idx"]]
            boot = paired_bootstrap(task.kind, yb, res[best]["_p"], base["_p"])
            # Hold-out check: the same OOS predictions restricted to the test years.
            hold = d["release_ts"].dt.year().to_numpy()[base["_idx"]] >= HOLDOUT_FROM_YEAR
            diff = _loss_vec(task.kind, yb, res[best]["_p"]) - _loss_vec(task.kind, yb, base["_p"])
            boot["holdout_mean_diff"] = float(diff[hold].mean()) if hold.any() else None
            boot["holdout_n"] = int(hold.sum())
            boot["directional_hit_rate"] = res[best]["walk_forward"].get("directional_hit_rate")
            beats = boot["ci95"][1] < 0 and (boot["holdout_mean_diff"] or 0) < 0
            if task.kind == "clf":
                res[best]["calibration_p_bullish"] = calibration_table(
                    y[res[best]["_idx"]], res[best]["_p"][:, 2])

            # final model on all data for the selected algorithm (for live use later)
            final = clone(zoo[best]).fit(X, y)
            art = models_dir / "trained" / f"{task.name}__{best}__{run_id}.joblib"
            joblib.dump({"model": final, "features": task.features, "task": task.name,
                         "neutral_pct": NEUTRAL_PCT, "classes": CLASSES.tolist(),
                         "feature_set_version": FEATURE_SET_VERSION}, art)

            for name, r in res.items():
                selected = name == best
                reg = ModelRegistry(
                    model_name=f"{task.name}__{name}", version=run_id, algorithm=name,
                    phase=task.phase, target=task.name, feature_set_version=FEATURE_SET_VERSION,
                    train_start=d["release_ts"].min().date(),
                    train_end=datetime(2021, 12, 31).date(),
                    validation_start=datetime(2022, 1, 1).date(),
                    validation_end=datetime(2023, 12, 31).date(),
                    test_start=datetime(2024, 1, 1).date(), test_end=datetime(2025, 12, 31).date(),
                    hyperparameters={"repr": repr(zoo[name])[:2000]},
                    metrics={k: v for k, v in r.items() if not k.startswith("_")} | (
                        {"selected": True, "vs_prior_walk_forward": boot,
                         "beats_prior": beats} if selected else {"selected": False}),
                    artifact_path=str(art) if selected else None,
                    status=("active" if beats else "trained") if selected else "candidate",
                )
                session.add(reg)
                session.flush()
                rows = [("walk_forward", None, f, m) for f, m in r["per_fold"].items()]
                rows += [("walk_forward_total", None, "all", r["walk_forward"])]
                rows += [(k, None, k, r[k]) for k in ("validation", "test") if k in r]
                for etype, fold, period, metrics in rows:
                    y0, y1 = (period, period) if period.isdigit() else (
                        {"validation": ("2022", "2023"), "test": ("2024", "2025")}.get(
                            period, (str(FIRST_TEST_YEAR), str(LAST_TEST_YEAR))))
                    for mk, mv in metrics.items():
                        if mk == "n":
                            continue
                        session.add(ModelEvaluationResult(
                            model_id=reg.model_id, evaluation_type=etype, fold=fold,
                            period_start=datetime(int(y0), 1, 1).date(),
                            period_end=datetime(int(y1), 12, 31).date(),
                            metric_name=mk, metric_value=None if mv is None else round(mv, 8),
                            n_samples=int(metrics["n"])))
            session.commit()

            summary["tasks"][task.name] = {
                "n_samples": int(len(y)), "selected": best, "beats_prior": beats,
                "vs_prior_walk_forward": boot,
                "models": {n: {k: r.get(k) for k in ("walk_forward", "validation", "test")}
                           for n, r in res.items()},
            }
        stats.rows_written = len(TASKS)
        stats.details = {"run_id": run_id}
    return summary


def format_summary(out: dict) -> str:
    def f(v):
        return "-" if v is None else f"{v:.4f}"

    lines = [f"run {out['run_id']}  {out['instrument']} ({out['provider']})"]
    for t, r in out["tasks"].items():
        clf = "log_loss" in (r["models"]["prior"]["walk_forward"] or {})
        cols = ["log_loss", "brier", "accuracy", "directional_hit_rate"] if clf else \
            ["mae", "rmse", "corr"]
        b = r["vs_prior_walk_forward"]
        lines += ["", f"{t}  n={r['n_samples']}  selected={r['selected']}  "
                      f"beats_prior={r['beats_prior']}  diff={b['mean_diff']:+.4f} "
                      f"CI95=[{b['ci95'][0]:+.4f}, {b['ci95'][1]:+.4f}]",
                  f"  {'model':14}" + "".join(f"{'WF ' + c:>24}" for c in cols)
                  + f"{'VAL ' + cols[0]:>16}{'TEST ' + cols[0]:>16}"]
        for m, mr in r["models"].items():
            wf, va, te = mr["walk_forward"], mr["validation"] or {}, mr["test"] or {}
            lines.append(f"  {m:14}" + "".join(f"{f(wf.get(c)):>24}" for c in cols)
                         + f"{f(va.get(cols[0])):>16}{f(te.get(cols[0])):>16}")
    return "\n".join(lines)
