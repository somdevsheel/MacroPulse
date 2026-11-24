# Data quality: OANDA v20 1-minute candles (all 7 instruments)

- Source: OANDA v20 REST `GET /v3/instruments/{instrument}/candles`, granularity M1, price=BAM
  (bid, ask, mid). Practice account, read-only. Downloaded 2026-11-24. Used for research under
  the account terms; not redistributed.
- Timestamps: **UTC** (RFC3339) — no broker-clock conversion needed. Only `complete` candles kept.
- Volume: OANDA **tick volume** (number of price updates), not traded volume.
- Bronze: `data/bronze/{forex_prices,gold_prices}/oanda/instrument=X/month=YYYY-MM.parquet`
  (one file per month, re-runs skip completed months; the current month is always refreshed).
- Silver: `provider=oanda`, 1m keeps `bid_*`, `ask_*`, `spread_close`; `open/high/low/close` =
  **mid**. 5m/15m/1h/4h built from 1m mid.

| Instrument | 1m bars | First (UTC) | Median close spread |
|---|---|---|---|
| EUR/USD | 7,988,770 | 2005-01-02 | 1.4 pips |
| GBP/USD | 7,851,956 | 2005-01-02 | |
| USD/JPY | 7,951,676 | 2005-01-02 | |
| USD/CHF | 7,568,342 | 2005-01-02 | |
| USD/CAD | 7,788,349 | 2005-01-02 | |
| AUD/USD | 7,753,758 | 2005-01-02 | |
| XAU/USD | 7,190,785 | 2006-03-19 | $0.35 |

All series end at the download time (2026-11-24) and are kept current by the scheduler's hourly
`oanda_prices` job.

## Validation

- 54.1M bars, **0** invalid OHLC, **0** duplicate timestamps, **0** bars with |1m move| > 3%.
- ~370k bars/year for majors (≈ every trading minute). XAU/USD 2006 is thinner (~225k).
- ~900 non-weekend gaps > 90 min per instrument. The largest are all **market holidays**
  (Christmas, New Year, Easter long weekends) — expected closures, not data loss. Full lists in
  `data/silver/cleaned_prices/_reports/oanda_*.json`.
- 157 transient HTTP 504 responses during the download; all retried successfully.

## Cross-check with the Kaggle/OctaFX gold file

January 2024, same minutes: median |OANDA bid − OctaFX close| = **$0.06** with no time shift,
vs $1.50 with ±1 hour. This independently confirms the broker-clock conversion (CET→EET) that
was inferred for the Kaggle file from release spikes.
