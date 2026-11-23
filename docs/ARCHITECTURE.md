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
| **OANDA v20** | 1-min bid/ask/mid candles (fallback/reconciliation) | ⏳ | Needs a (free practice) API token. Adapter stub reports `disconnected`. |
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
| 2 | ✅ FRED vintages → events + snapshots (revision-date filtering, verified vs published NFP/CPI/PCE). ✅ Gold 1m from Kaggle/OctaFX → UTC silver Parquet + 5m/15m/1h/4h + quality report ([details](data_quality/kaggle_octafx_xauusd.md)). ✅ Ingestion job logging. ✅ FOMC calendar (federalreserve.gov) + policy rate (DFEDTAR/DFEDTARU) with statement minute verified by gold spikes; unscheduled/conference calls and conflicts excluded. ⏳ FX pairs 1m (no source yet). ⏳ Daily macro context. ⏳ Provider registry sync | in progress |
| 3 | ✅ Event windows + aggregate studies + similar-event kNN + API (`/api/v1/events`, `/events/{id}/bars`, `/analysis/reactions`, `/events/{id}/similar`) for gold. ⏳ Milestone 1 UI. FX pairs pending a data source. | in progress |
| 4 | Similar-event retrieval (kNN with documented distance), clustering | |
| 5 | Baselines (logreg, RF, XGBoost/LightGBM), walk-forward with embargo, registry | |
| 6 | Prediction API + full dashboard | |
| 7 | Scheduler, live pre/post predictions, paper evaluation | |

**Milestone 1 dependency:** 1-minute price data. FRED side is ready; Phase 2 must get Dukascopy
downloading reliably or an OANDA practice token must be added to `.env`.

## 7. Open decisions for the owner

1. Consensus forecasts: subscribe to Trading Economics (or equivalent), or run without true
   surprise for now?
2. OANDA practice account token — recommended as a second price source for reconciliation.
3. PostgreSQL: set `DATABASE_URL` in `.env` (local server on port 5433) and create database
   `macropulse`.
