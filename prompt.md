# MASTER DEVELOPMENT PROMPT: MACROECONOMIC NEWS-DRIVEN MARKET PREDICTION PLATFORM-MacroPulse

Act as a senior quantitative developer, financial data engineer, machine learning engineer, backend architect and frontend developer.

Your task is to design and build a complete, production-oriented **Macroeconomic News-Driven Market Prediction Platform**.

Do not build a generic quantitative research platform. This is a specialized financial intelligence application that studies how financial markets react to economic news and predicts the possible reactions to upcoming economic announcements.

The primary markets are:

- Gold: XAU/USD
- EUR/USD
- GBP/USD
- USD/JPY
- USD/CHF
- USD/CAD
- AUD/USD

The initial focus must be US economic announcements and their effects on gold and USD Forex pairs.

The system must collect historical economic announcements, collect historical market prices, synchronize both datasets, analyze historical reactions, identify recurring patterns, train predictive models and generate predictions for upcoming economic releases.

---

# 1. CORE OBJECTIVES

Build a platform with the following capabilities:

1. Collect historical US economic announcement data.
2. Collect historical Forex and gold market data.
3. Store actual, forecast, previous and revised previous economic values.
4. Preserve point-in-time snapshots of information available before each announcement.
5. Analyze market movements before and after economic announcements.
6. Identify historical patterns and similar announcement scenarios.
7. Train machine learning models to predict market reactions.
8. Generate predictions before an economic announcement.
9. Update predictions immediately after the announcement.
10. Display historical analysis, model predictions and performance through a professional dashboard.

The platform must distinguish historical research, predictive analytics and actual trading execution.

Do not implement automatic real-money trading in this version. Design the architecture so that a separate trading execution system can integrate with the prediction API in the future.

# 2. DATA COLLECTION SYSTEM

Build an extensible data ingestion framework.

Each provider must have an independent adapter. Do not tightly couple the application to one provider.

## 2.1 Economic calendar data

Investigate and integrate the following sources:

**Primary candidate: Trading Economics API**

Documentation:
https://docs.tradingeconomics.com/

Calendar:
https://tradingeconomics.com/calendar

Use it to investigate availability of:

- Historical economic announcements.
- Event timestamps.
- Actual values.
- Consensus forecasts.
- Previous values.
- Revised previous values.
- Event importance.
- Country and category.
- Historical point-in-time calendar snapshots.

Before implementing, verify the API endpoints, subscription requirements, historical coverage, rate limits and licensing.

Other sources:

- BLS: https://www.bls.gov/developers/
- BEA: https://apps.bea.gov/api/
- FRED: https://fred.stlouisfed.org/docs/api/fred/
- ALFRED: https://fred.stlouisfed.org/docs/api/alfred.html
- Federal Reserve: https://www.federalreserve.gov/data.htm

Use official government sources to verify released economic values.

Important: Official government sources generally do not provide historical market-consensus forecasts. Do not treat official released values as substitutes for consensus data.

## 2.2 Economic announcements to collect

Start with these events:

**Inflation**
- CPI
- Core CPI
- PCE Price Index
- Core PCE Price Index

**Employment**
- Nonfarm Payrolls
- Unemployment Rate
- Average Hourly Earnings
- ADP Employment
- Initial Jobless Claims
- JOLTS Job Openings

**Federal Reserve**
- FOMC Interest Rate Decision
- FOMC Meeting Minutes
- Federal Reserve press conferences
- Federal Reserve economic projections
- Important speeches by the Federal Reserve Chair

**Economic growth**
- GDP
- Retail Sales
- ISM Manufacturing PMI
- ISM Services PMI
- Durable Goods Orders
- Consumer Confidence
- Industrial Production

Initially prioritize CPI, Core CPI, Core PCE, NFP, Unemployment Rate and FOMC decisions.

Make the event list configurable.

## 2.3 Economic event database

Create an economic_events table containing:

- event_id
- provider_event_id
- event_name
- event_category
- country
- currency
- importance
- scheduled_release_time
- actual_release_time
- reference_period
- actual_value
- consensus_forecast
- previous_value
- revised_previous_value
- unit
- source
- created_at
- updated_at

Create a separate economic_event_snapshots table.

Every time a provider updates an event, preserve the snapshot instead of overwriting previous information.

Store:

- event_id
- snapshot_timestamp
- forecast_value
- previous_value
- revised_previous_value
- actual_value
- provider
- source_timestamp

The system must distinguish the original previous value from a revised value.

The system must also distinguish the original forecast from subsequent forecast updates.

Never use information that was unavailable at the prediction timestamp.

## 2.4 Forex and gold market data

Investigate these providers:

1. Dukascopy historical data:
   https://www.dukascopy.com/swiss/english/marketwatch/historical/

2. OANDA API:
   https://developer.oanda.com/rest-live-v20/introduction/

3. Twelve Data:
   https://twelvedata.com/docs

4. Other reputable historical Forex market-data providers where necessary.

Verify actual availability of historical XAU/USD and Forex one-minute candles, bid/ask prices, data coverage, API restrictions and licensing.

Do not assume every provider supplies five years of one-minute data.

Collect:

- Timestamp in UTC
- Open
- High
- Low
- Close
- Bid OHLC where available
- Ask OHLC where available
- Midpoint OHLC where available
- Volume or tick volume where available
- Provider identifier
- Instrument
- Timeframe

Start with one-minute data.

Support five-minute, fifteen-minute, one-hour and four-hour aggregation.

Instruments:

- XAU/USD
- EUR/USD
- GBP/USD
- USD/JPY
- USD/CHF
- USD/CAD
- AUD/USD

Design the system so more instruments can be added later.

Forex volume is decentralized. Clearly identify provider-specific tick volume and never present it as centralized exchange volume.

## 2.5 Cross-market data

Collect additional market indicators:

- US Dollar Index (DXY)
- US 2-year Treasury yield
- US 10-year Treasury yield
- US 10-year real yield
- VIX
- Relevant macroeconomic indicators

Use FRED and other appropriate sources.

For every dataset, record the source, units, timestamp, frequency and coverage.

# 3. DATA ENGINEERING AND STORAGE

Use a reliable ingestion architecture.

Recommended technologies:

- Python 3.11+
- Pandas or Polars
- NumPy
- Requests or HTTPX
- PostgreSQL
- DuckDB
- Apache Parquet
- AWS S3-compatible object storage

Use PostgreSQL for application metadata, economic events, snapshots, model metadata and predictions.

Use Parquet for large historical market datasets.

Use DuckDB for efficient historical analytical queries.

Organize the data lake:

bronze/
- economic_calendar/
- forex_prices/
- gold_prices/
- macroeconomic_data/
- central_bank_events/

silver/
- cleaned_calendar/
- cleaned_prices/
- synchronized_events/
- normalized_surprises/
- market_features/

gold/
- event_studies/
- historical_patterns/
- training_datasets/
- model_predictions/
- backtest_results/

Implement:

- Data validation
- Duplicate detection
- Missing candle detection
- Timestamp normalization
- Timezone conversion
- Provider reconciliation
- Data quality reports
- Incremental ingestion
- Retry handling
- API rate-limit handling
- Logging and error recovery

Store timestamps internally in UTC.

Convert US announcement times using the correct America/New_York timezone, including daylight-saving changes.

Do not assume all US releases happen at the same local time.

Do not silently fill missing market candles with fabricated values.

# 4. HISTORICAL NEWS REACTION ENGINE

This is the most important initial module.

Build a historical event analysis engine before attempting complex machine learning.

For each historical economic announcement, retrieve market prices around the exact release timestamp.

Analyze these windows:

- 60 minutes before release
- 30 minutes before release
- 15 minutes before release
- 5 minutes before release
- 1 minute before release
- 1 minute after release
- 5 minutes after release
- 15 minutes after release
- 30 minutes after release
- 1 hour after release
- 4 hours after release

Calculate:

- Percentage return
- Absolute price movement
- Maximum favorable excursion
- Maximum adverse excursion
- Realized volatility
- Initial direction
- Reversal probability
- Breakout probability
- Sell-off probability
- Time to maximum movement
- Price recovery duration
- Pre-release volatility
- Post-release volatility

Build historical statistics for each event and instrument.

For example:

CPI announcement:
- Number of historical observations
- Average gold reaction
- Median gold reaction
- Percentage of bullish reactions
- Percentage of bearish reactions
- Percentage of neutral reactions
- Average volatility increase
- Reversal frequency
- Largest positive reaction
- Largest negative reaction

Display the actual historical price chart around each announcement.

Allow users to select an event, date, instrument and time window.

Handle simultaneous announcements separately and identify when multiple announcements occur at the same timestamp.

# 5. MACROECONOMIC SURPRISE ENGINE

Calculate the difference between actual and consensus forecast.

For example:

Surprise = Actual - Consensus Forecast

Also calculate normalized surprise:

Normalized Surprise = (Actual - Forecast) / Historical Standard Deviation of Surprises

Implement event-specific normalization.

Do not assume that a positive surprise always has the same market interpretation.

For example:
- Higher inflation can influence expectations for interest rates.
- Stronger employment can influence expectations for Federal Reserve policy.
- Gold can react differently depending on Treasury yields, real yields and market positioning.

Preserve the economic indicator's units and release-specific interpretation.

For pre-release predictions, actual values must be unavailable to the model.

For post-release predictions, actual values may be used only after their actual publication time.

# 6. HISTORICAL PATTERN RECOGNITION ENGINE

Build an engine that identifies similar historical announcement scenarios.

Compare historical events using:

- Event category
- Normalized economic surprise
- Previous values
- Market trend before release
- Pre-release volatility
- DXY movement
- Treasury yield movement
- Real yield movement
- Broader market regime
- Historical price reaction

Investigate:

- K-Nearest Neighbors
- K-Means clustering
- HDBSCAN
- Dynamic Time Warping
- Similarity-based historical event retrieval

For each prediction, provide a list of similar historical events.

Display:
- Historical event date
- Event surprise
- Similarity score
- Price movement
- Reaction duration
- Outcome

Do not use arbitrary similarity scores without a documented calculation.

# 7. MACHINE LEARNING PREDICTION ENGINE

Build separate models for different prediction targets.

Start with:

- Logistic Regression
- Random Forest
- XGBoost
- LightGBM, if available

Do not immediately build deep learning models.

First establish strong statistical baselines.

## 7.1 Pre-release prediction

The pre-release model must use only information available before the announcement.

Inputs:

- Event category
- Scheduled release time
- Consensus forecast
- Previous value
- Previous revisions already known
- Historical event reactions
- Current market returns
- Market volatility
- Technical indicators
- DXY
- Treasury yields
- Market regime
- Time and trading session

Predictions:

- Bullish probability
- Bearish probability
- Neutral probability
- Expected return
- Expected volatility
- Potential breakout probability
- Potential reversal probability
- Prediction confidence

## 7.2 Post-release prediction

After actual economic data is released, update the prediction.

Additional inputs:

- Actual value
- Consensus forecast
- Normalized surprise
- Revised previous value
- Immediate gold and Forex price reaction
- Immediate DXY movement
- Immediate Treasury yield movement

Generate updated predictions for:

- 5 minutes
- 15 minutes
- 30 minutes
- 1 hour
- 4 hours

Keep pre-release and post-release predictions as separate records.

## 7.3 Prediction outputs

For every instrument, produce:

- Directional probabilities
- Expected percentage return
- Expected price movement
- Volatility estimate
- Reversal probability
- Similar historical scenarios
- Model confidence
- Prediction timestamp
- Prediction horizon
- Model version

Do not present model confidence as a guaranteed probability of profit.

# 8. BACKTESTING AND MODEL VALIDATION

Implement rigorous chronological validation.

Do not use random train/test splitting for time-series forecasting.

Use:

- Walk-forward validation
- Expanding-window validation
- Chronological training and testing
- Purging or embargo where event windows overlap
- Out-of-sample evaluation

Example historical split:

- Training: 2016–2021
- Validation: 2022–2023
- Testing: 2024–2025
- Paper evaluation: 2026 onward

Adjust the dates based on actual data coverage.

Evaluate:

- Accuracy
- Precision
- Recall
- F1 score
- ROC-AUC where appropriate
- Mean Absolute Error
- Root Mean Squared Error
- Brier score
- Probability calibration
- Profit factor
- Expectancy
- Maximum drawdown

If a trading simulation is added, include:

- Bid/ask spread
- Slippage
- Commissions
- Execution delay
- Spread widening around economic releases

Do not use the same event window for both training and testing.

Prevent look-ahead bias and data leakage.

# 9. LIVE ECONOMIC CALENDAR AND PREDICTION SYSTEM

Build a live economic calendar interface.

Display:

- Upcoming US economic announcements
- Scheduled time
- Event importance
- Forecast
- Previous value
- Countdown
- Affected instruments
- Historical volatility around the event

For each upcoming announcement, allow users to generate a pre-release prediction.

When actual figures become available:

1. Retrieve the released actual value.
2. Validate the event timestamp.
3. Calculate the surprise.
4. Retrieve immediate market prices.
5. Update the post-release prediction.
6. Save both predictions.
7. Compare predictions with subsequent market outcomes.

Build a scheduler for data updates.

Do not generate fake real-time data if the provider is unavailable.

Show data freshness and connection status.

# 10. APPLICATION DASHBOARD

Build a professional financial terminal-style interface.

Use:

Frontend:
- React
- TypeScript
- Tailwind CSS
- TradingView Lightweight Charts

Backend:
- Python
- FastAPI
- PostgreSQL
- DuckDB
- Parquet

Use WebSockets for live updates where appropriate.

Create the following screens:

### Dashboard
- Upcoming US economic events
- Gold market overview
- Forex market overview
- Latest model predictions
- Market volatility
- Data ingestion status

### Economic Calendar
- Historical and upcoming announcements
- Event filters
- Actual versus forecast
- Revised previous values
- Event importance
- Event detail page

### Historical Event Analysis
- Event selector
- Instrument selector
- Historical reaction chart
- Before-and-after event comparison
- Average and median reaction
- Bullish/bearish frequency
- Reversal and volatility statistics

### Pattern Recognition
- Similar historical announcements
- Pattern clusters
- Similarity scores
- Historical outcomes

### Prediction Center
- Pre-release predictions
- Post-release predictions
- Directional probabilities
- Expected return
- Expected volatility
- Confidence
- Historical comparisons

### Model Performance
- Model comparison
- Walk-forward results
- Prediction accuracy
- Calibration
- Error metrics
- Model versions

### Data Management
- Provider connections
- API configuration status
- Historical coverage
- Last ingestion timestamp
- Data quality reports
- Failed ingestion jobs

### Settings
- Instrument configuration
- Event configuration
- Prediction horizons
- Data-provider settings
- Model configuration

# 11. DATABASE AND API DESIGN

Create well-defined database models and migrations.

At minimum, implement:

- economic_events
- economic_event_snapshots
- market_instruments
- market_candles
- macro_indicators
- synchronized_event_windows
- event_features
- event_studies
- historical_patterns
- model_registry
- model_predictions
- model_evaluation_results
- data_provider_registry
- ingestion_jobs

Design REST API endpoints for:

- Economic calendar
- Historical events
- Historical price data
- Event analysis
- Pattern retrieval
- Pre-release predictions
- Post-release predictions
- Model performance
- Data ingestion status

Document APIs using OpenAPI/Swagger.

# 12. SECURITY AND CONFIGURATION

Use environment variables for all API credentials.

Create a .env.example file.

Never hardcode API keys.

Never expose provider credentials to the frontend.

Implement authentication and appropriate access control.

Add structured logging and error handling.

Do not scrape websites in violation of their terms or bypass subscription restrictions.

Respect API rate limits, data licensing and redistribution restrictions.

# 13. PROJECT STRUCTURE

Create a maintainable modular structure similar to:

backend/
  app/
    api/
    core/
    database/
    models/
    schemas/
    services/
    providers/
      economic/
      market/
      macro/
    ingestion/
    event_engine/
    feature_engineering/
    pattern_engine/
    prediction_engine/
    backtesting/
    scheduler/
    utils/
  tests/
  migrations/

frontend/
  src/
    components/
    pages/
    charts/
    services/
    hooks/
    types/
    layouts/

data/
  bronze/
  silver/
  gold/

models/
  trained/
  evaluation/
  registry/

scripts/
docs/
docker/

Adapt the structure if the existing repository has an established architecture.

# 14. IMPLEMENTATION PLAN

Build the platform in phases.

**Phase 1: Repository inspection and architecture**

- Inspect the existing project.
- Identify the current stack and existing reusable code.
- Produce an implementation plan.
- Identify missing dependencies and data providers.
- Do not overwrite existing working code without a reason.

**Phase 2: Data ingestion**

- Implement provider adapters.
- Implement economic calendar ingestion.
- Implement market data ingestion.
- Implement macroeconomic data ingestion.
- Store raw data.
- Implement validation and synchronization.

**Phase 3: Historical event analysis**

- Implement event windows.
- Calculate returns and volatility.
- Build historical reaction statistics.
- Build historical event charts.

**Phase 4: Pattern recognition**

- Implement similar-event retrieval.
- Implement clustering.
- Implement historical pattern comparisons.

**Phase 5: Machine learning**

- Build baseline models.
- Build pre-release models.
- Build post-release models.
- Implement chronological validation.
- Save model versions and metrics.

**Phase 6: Prediction API and dashboard**

- Implement prediction endpoints.
- Build the economic calendar.
- Build historical analysis screens.
- Build the prediction center.
- Build model performance screens.

**Phase 7: Live data and paper evaluation**

- Implement scheduled updates.
- Generate predictions for upcoming releases.
- Store predictions before outcomes are known.
- Evaluate predictions after each event.
- Produce performance reports.

# 15. IMPORTANT DEVELOPMENT RULES

1. Build real functionality, not a static UI mockup.
2. Do not fabricate historical data, forecasts, API responses or prediction results.
3. If an API key is unavailable, build the provider adapter and configuration interface, then clearly mark that provider as disconnected.
4. Never assume historical consensus forecasts exist simply because actual economic data is available.
5. Do not use future information to train or evaluate historical predictions.
6. Preserve every prediction with its timestamp and model version.
7. Preserve original economic announcement values and revisions.
8. Make all data sources configurable.
9. Use modular, testable and documented code.
10. Add unit tests and integration tests for critical data and prediction workflows.
11. Do not silently ignore ingestion failures.
12. Do not build automatic real-money trading.
13. Do not claim that the model can reliably predict every news-driven price movement.
14. Clearly communicate data limitations and model uncertainty.
15. Prefer a working, tested implementation over generating large amounts of incomplete code.

# 16. FIRST MILESTONE: HISTORICAL NEWS REACTION ENGINE

Before building sophisticated machine learning, deliver a working first milestone.

It must allow me to:

1. Select CPI, Core CPI, Core PCE, NFP, Unemployment or FOMC.
2. Select XAU/USD or any supported Forex pair.
3. Select a historical date range.
4. Retrieve available historical announcements.
5. View the corresponding one-minute price chart.
6. Compare market movement before and after the announcement.
7. Calculate average and median reactions.
8. See bullish, bearish and neutral reaction frequencies.
9. Identify reversals and volatility spikes.
10. View similar historical announcements.

The milestone must work with real data from configured providers.

# 17. FINAL EXPECTATION

I want a complete, modular, extensible application that can eventually operate as an independent financial market intelligence platform.

The system's main purpose is to answer questions such as:

- How did gold react to previous CPI announcements?
- What happened to EUR/USD and USD/JPY after NFP releases?
- How frequently did gold reverse after an initial CPI-driven move?
- What happened when actual CPI was significantly above or below consensus?
- Which historical announcements most closely resemble the upcoming event?
- What is the model's estimated probability of bullish, bearish or neutral movement?
- How does the prediction change after actual economic data is released?

Start by inspecting the repository and producing a clear architecture and implementation plan.

Then implement Phase 1 and Phase 2.

Do not attempt to generate the entire application in one untested code dump. Work in verifiable milestones, run tests, document completed functionality and identify remaining dependencies.

The final system must use real, timestamped, verifiable data and maintain strict protection against look-ahead bias and data leakage.
