# Data quality: Kaggle XAU/USD 1-minute (OctaFX / MetaTrader)

- Source: https://www.kaggle.com/datasets/novandraanugrah/xauusd-gold-price-historical-data-2004-2024
- License: CC0-1.0. Origin per author: MetaTrader export, broker OctaFX.
- File: `data/bronze/gold_prices/kaggle_octafx/XAU_1m_data.csv` (348 MB, 6,789,606 rows,
  2004-06-11 → 2026-01-30). Downloaded 2026-11-24.
- Prices: assumed **bid** (MetaTrader chart convention); no ask/spread available.
- Volume: broker **tick volume**, not exchange volume.

## Timestamp clock (critical)

The file has no timezone. It was established empirically (`python -m app.ingestion.cli tz-check`):
for every 08:30 ET release (NFP, CPI, Core PCE, Retail Sales; 1,005 dates), the 1-minute
volatility spike was located under each candidate clock. On the 626 dates where the candidates
disagree and one wins clearly:

| Server-local dates | Clock | Notes |
|---|---|---|
| 2004-06-11 → 2011-05-06 | Europe/Berlin (CET/CEST, UTC+1/+2) | contrary verdicts are isolated single dates (noise) |
| 2011-05-07 → 2011-05-11 | **quarantined** (2,720 rows dropped) | broker switch-over; clock unknown |
| 2011-05-12 → 2026-01-30 | Europe/Athens (EET/EEST, UTC+2/+3) | |

The EU daylight-saving schedule (not US) is confirmed by dates in the 1–3 week windows where EU
and US DST differ (e.g. NFP 2012-11-02 sits between the EU and US autumn changes).

End-to-end check on silver data: NFP spikes land at 12:30 UTC (EDT dates) and 13:30 UTC (EST
dates) in both clock eras (2009-06-05, 2009-12-04, 2024-07-05, 2024-12-06).

## Coverage and gaps

Bars per year: ~80k (2004, partial) · 141k (2005) · 166k (2006) · 242k (2007) · 315k–356k
(2008–2024) · 322k (2025). A fully traded year is ~350k bars.

- **2004–2007 is sparse** (many minutes without a bar). Treat reactions in these years as lower
  quality; event windows report `candle_count` vs `expected_candle_count`.
- **Missing: 2025-09-12 20:47 → 2025-10-15 04:59 UTC** (~32 days) and
  **2026-01-13 12:19 → 2026-01-22 16:52 UTC** (~9 days). Releases in these ranges have no gold data.
- 952 non-weekend gaps > 90 minutes in total (holidays, thin early data, the holes above). Full
  list in `data/silver/cleaned_prices/_reports/`.
- 4 bars flagged with >3% 1-minute moves: two on 2006-10-01 (Sunday open) and two at the end of
  the gaps above (price jump across missing data, not a real 1-minute move). Kept, flagged.
- No invalid OHLC rows, no duplicate timestamps.

Missing bars are never filled. Gaps are reported and windows that touch them are flagged.

## Other timeframe files (downloaded 2026-11-24)

All 9 files of the dataset are in `data/bronze/gold_prices/kaggle_octafx/` (1m, 5m, 15m, 30m, 1h,
4h, 1d, 1w, 1Month; ~470 MB, all 2004-06 → 2026-01).

- **Consistency check:** after the same clock conversion, the vendor's 5m (1,442,903 bars) and 1h
  (125,160 bars) files match the bars we build from 1m **exactly** (0 OHLC differences, 0
  missing/extra bars). The vendor files are derived from the same 1m data, which also confirms our
  aggregation and timezone handling.
- **Silver timeframes:** 1m (source), 5m/15m/1h/4h (built from 1m, UTC-aligned), 30m/1d/1w/1M
  (vendor files, converted to UTC).
- **Daily/weekly/monthly bars open at broker midnight**: 21:00/22:00 UTC since 2011-05 (= 17:00
  New York, the standard forex day boundary) and 22:00/23:00 UTC before (CET midnight = 18:00
  New York). They are *not* UTC-midnight bars. The vendor 4h file is also server-aligned, so it
  differs from our UTC-aligned 4h bars (vendor file kept in bronze only).
