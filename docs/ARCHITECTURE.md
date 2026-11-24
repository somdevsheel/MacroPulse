# MacroPulse — Architecture & Implementation Plan

Status: **Phases 1–2 mostly complete, Phase 3 backend done (gold)** (2026-11-24). Source requirements: [`prompt.md`](../prompt.md).

## 1. What the system does

Studies how XAU/USD and the six USD majors react to scheduled US macro releases, using only
information that was public at each point in time, then (later phases) predicts reactions to
upcoming releases. Research and prediction only — no trade execution.

## 2. Data source verification (done 2026-11-24, from this machine)

| Source | Use | Verified | Finding |
|---|---|---|---|
| **FRED / ALFRED** | Actual values, original vs revised, release dates, daily yields/VIX | ✅ live | Key works. Every series & release ID in `config/events.yaml` resolved. ALFRED returns every vintage with `realtime_start/end` → true point-in-time history. 120 req/min limit. |
| FRED release dates | Announcement calendar | ✅ live | Includes **revision-only dates** (e.g. CPI 2024-02-09 seasonal factors). Ingestion must keep only dates where a new reference period first appears. |
| FRED release 101 | FOMC decision dates | ❌ | Lists **every calendar day** — unusable for meeting dates. Needs the Federal Reserve meeting calendar. DFEDTARU shows a new target effective the day *after* the decision. |
| Kaggle XAU/USD (OctaFX MT) | Gold 1m bars 2004-06 → 2026-01 | ✅ ingested | CC0. Broker clock CET→EET (detected empirically). Gaps in Sep–Oct 2025 and Jan 2026. See data_quality/. |
| **Dukascopy** | 1-min bid/ask candles, all 7 instruments | ⚠️ | Free datafeed returns 429 and points to its data-export wiki: bulk history is now an AWS S3 **Requester Pays** bucket (`cfg-public-proper-wallaby`, eu-west-1) — needs an AWS account; you pay transfer costs. |
| **OANDA v20** | 1-min bid/ask/mid candles, all 7 instruments | ✅ ingested | Practice token. UTC. 54.1M bars 2005→now, 0 invalid; gaps = market holidays. Hourly incremental updates. See data_quality/oanda.md. |
| Twelve Data | Optional candles | ⏳ | Needs key; free tier is limited. |
| **Trading Economics** | Consensus forecasts | ❌ | Paid. **No other legitimate source of historical consensus is available.** |
| ISM PMI, Conference Board | Indicators | ❌ | Licensed, not on FRED. Configured with `provider: none`. |

### Hard data limitations (must be shown in the UI)

1. **No consensus → no true "surprise".** Until a consensus provider is connected, the surprise
   engine can only compute *actual vs previous* / *actual vs trend*, labelled as such.
   `economic_events.consensus_forecast` stays NULL; it is never back-filled from official data.
2. **Forecast-revision history cannot be reconstructed for the past.** Snapshots of forecasts
   start the day a calendar provider is connected.
3. **Cross-market intraday data is not free.** Yields, VIX, broad USD index are *daily* (FRED).
   DXY is not on FRED; an intraday DXY proxy can be computed from its 6 component FX rates
   (needs USD/SEK added to market ingestion).
4. **Fed speeches/minutes/pressers** have no numeric value; tracked as timestamped events only.
5. **FX volume is provider tick volume**, never exchange volume (`volume_kind='tick'`).

## 3. Architecture

```
 config/events.yaml, instruments.yaml   ← configurable universe (validated at startup)
            │
 providers/ (one adapter per source, common interfaces in providers/base.py)
   macro/fred.py          MacroDataProvider      ✅ implemented + live-tested
   market/dukascopy.py    MarketDataProvider     health check only (Phase 2)
   stubs.py               OANDA, TwelveData, TradingEconomics → "disconnected"
            │
 ingestion/ (Phase 2)  ── raw responses ─→ data/bronze/   (immutable, as received)
            │          ── cleaned ───────→ data/silver/   (Parquet, UTC, validated)
            │          ── metadata/events/snapshots ─→ PostgreSQL
            ▼
 event_engine/ (Phase 3) → synchronized_event_windows, event_studies, data/gold/event_studies
 pattern_engine/ (4)     → historical_patterns
 prediction_engine/ (5)  → model_registry, model_predictions, model_evaluation_results
 api/ (FastAPI, OpenAPI at /docs)  ←→  frontend/ (React + TS + Tailwind + Lightweight Charts, Phase 6)
```

Storage split:
- **PostgreSQL**: events, snapshots, macro vintages, instruments, studies, models, predictions,
  provider registry, ingestion jobs. Schema managed by Alembic (`backend/migrations`).
- **Parquet** (`data/silver/cleaned_prices/instrument=…/year=…/`): bulk 1-minute candles.
- **DuckDB**: analytical queries over Parquet (event windows across years of minute data).
- `market_candles` table mirrors the Parquet layout for recent/live candles.

## 4. Point-in-time & leakage rules (enforced, not just documented)

| Rule | Where enforced |
|---|---|
| All timestamps UTC; ET→UTC via `America/New_York` per date | `utils/timeutils.py` (DST tests) |
| Naive datetimes rejected | `ensure_utc` |
| Original values never overwritten; revisions appended | `economic_event_snapshots` (append-only), `previous_value` vs `revised_previous_value` |
| Macro values queried "as known at T" | `macro_indicators.realtime_start/end` |
| A prediction can't use features from after its timestamp | DB `CHECK (features_as_of <= prediction_ts)` |
| Pre-release features must predate the release | service check (Phase 5) on `event_features.as_of_ts` |
| Predictions immutable; outcomes stored alongside | `model_predictions` (outcome columns only filled by evaluator) |
| Missing candles never fabricated | `has_gaps`, `candle_count` vs `expected_candle_count` |
| Ingestion failures recorded | `ingestion_jobs.status/error_message` |
| Credentials never leave the backend | `SecretStr`, URL redaction, status endpoint returns booleans/status only |

## 5. Event model

- A **release** (e.g. Employment Situation) has one timestamp and carries several
  **indicators** (NFP, unemployment rate, AHE). Indicators sharing a release are recorded as
  simultaneous announcements (`synchronized_event_windows.concurrent_event_ids`).
- `economic_events` = one row per indicator × reference period × source.
- Headline values are derived from FRED levels via `transform` (`change`, `mom_pct`, `yoy_pct`,
  `qoq_saar`, `level`), computed from the **first-release vintage** and the vintage known just
  before it (for `previous_value`).

## 6. Phase plan

| Phase | Scope | Status |
|---|---|---|
| 1 | Repo setup, config, schema + migrations, provider interfaces, FRED adapter, tests | ✅ done |
| 2 | ✅ FRED vintages → events + snapshots (revision-date filtering, verified vs published NFP/CPI/PCE). ✅ Gold 1m from Kaggle/OctaFX → UTC silver Parquet + 5m/15m/1h/4h + quality report ([details](data_quality/kaggle_octafx_xauusd.md)). ✅ Ingestion job logging. ✅ FOMC calendar (federalreserve.gov) + policy rate (DFEDTAR/DFEDTARU) with statement minute verified by gold spikes; unscheduled/conference calls and conflicts excluded. ✅ FX pairs + XAU 1m bid/ask/mid from OANDA (2005→now). ⏳ Daily macro context. ⏳ Provider registry sync | in progress |
| 3 | ✅ Event windows + aggregate studies + similar-event kNN + API (`/api/v1/events`, `/events/{id}/bars`, `/analysis/reactions`, `/events/{id}/similar`) for gold. ✅ Milestone 1 UI (React/TS/Tailwind/Lightweight Charts): event/instrument/date filters, 11-window stats, event list, 1m chart with release marker, per-window metrics, simultaneous releases, similar events. FX pairs pending a data source. | ✅ gold |
| 4 | ✅ Similar-event kNN (documented z-score Euclidean, past events only). ⏳ Clustering (k-means/HDBSCAN/DTW) — deferred: little value until consensus surprise and FX data exist. | partial |
| 5 | ✅ Point-in-time feature set v1 (one sample per release timestamp), prior / logreg / RF / XGBoost / LightGBM, yearly expanding walk-forward 2012–2025 with embargo, fixed 2022–23 val / 2024–25 test split, paired-bootstrap test vs baseline, registry + per-fold metrics + OOS predictions + artifacts, Model Performance UI. **Result (gold): no model beats the baseline** — see §8. | ✅ gold |
| 6 | ✅ Prediction + calendar + data-status API; UI tabs: Economic calendar, Historical event analysis, Model performance, Data management. ⏳ Settings screen, auth, WebSockets (polling/countdown only for now). | mostly |
| 7 | ✅ Upcoming releases from FRED calendar (+ Fed meetings), fill-in on publication, scheduler loop, stored pre-release predictions (historical base rate — the only predictor with no worse out-of-sample loss), automatic evaluation when post-release prices exist. ⏳ Needs a live price feed (OANDA) for evaluation of new events; post-release live predictions pending a model with demonstrated edge. | partial |

**Milestone 1 dependency:** 1-minute price data. FRED side is ready; Phase 2 must get Dukascopy
downloading reliably or an OANDA practice token must be added to `.env`.

## 8. Baseline model results (gold, run 2026-11-24)

~890 release events (CPI, NFP, Core PCE, FOMC) 2004–2026. Baseline = historical up/flat/down
frequencies (or mean |move|) per release type, fitted on the training window only.

| Task | Selected (on validation) | Δ loss vs baseline, walk-forward 2012–2025 (95% CI) |
|---|---|---|
| pre-release direction +15m | random forest | +0.002 [−0.011, +0.016] |
| pre-release direction +60m | random forest | +0.004 [−0.012, +0.020] |
| pre-release \|move\| +60m | XGBoost | −0.001 [−0.012, +0.012] |
| post-release (+5m) direction →+15m | XGBoost | +0.015 [−0.008, +0.040] |
| post-release (+5m) direction →+60m | random forest | −0.007 [−0.021, +0.006] |

No task shows a statistically supported improvement over the baseline, so no model is marked
`active`. Expected with this data: no consensus (so no true surprise), one instrument, daily-only
cross-market context. The highest-value next inputs are consensus forecasts and intraday
DXY/yields; the pipeline will re-evaluate automatically when they are added.

### 8b. All 7 instruments, OANDA 1m (runs 2026-11-24 06:52–06:56 UTC)

~940 release timestamps per pair (2005–2026), 35 instrument × task tests. A model is `active`
only if the paired-bootstrap 95% CI on walk-forward 2012–2025 is below 0 **and** it also beats
the baseline on the 2024–25 hold-out.

| Active | Δ log loss WF | Δ hold-out 2024–25 | Direction hit |
|---|---|---|---|
| USD/CHF post-release 5→15m | −0.036 [−0.054, −0.019] | −0.067 | 51% |
| USD/CAD post-release 5→15m | −0.031 [−0.057, −0.005] | −0.058 | 52% |
| EUR/USD post-release 5→15m | −0.022 [−0.037, −0.008] | −0.020 | 49% |
| GBP/USD post-release 5→15m | −0.020 [−0.035, −0.005] | −0.036 | 53% |
| XAU/USD pre-release \|move\| 60m (MAE) | −0.009 [−0.018, −0.000] | −0.012 | – |

Interpretation:
- **Multiple testing:** with Holm correction over the 35 tests only USD/CHF 5→15m remains
  individually significant. The *consistency* of the 5→15m result across four USD pairs, in both
  the walk-forward and the hold-out years, is the stronger evidence.
- **Not a directional edge.** Directional hit rates are 49–53% (coin flip). The gain comes from
  estimating whether the move after the first 5 minutes stays large or fades (the neutral-band
  probability) — useful for volatility/risk, not for calling direction.
- Pre-release direction: no edge on any instrument. USD/JPY's walk-forward "wins" failed the
  hold-out and were demoted.

## 7. Open decisions for the owner

1. Consensus forecasts: subscribe to Trading Economics (or equivalent), or run without true
   surprise for now?
2. OANDA practice account token — recommended as a second price source for reconciliation.
3. PostgreSQL: set `DATABASE_URL` in `.env` (local server on port 5433) and create database
   `macropulse`.
