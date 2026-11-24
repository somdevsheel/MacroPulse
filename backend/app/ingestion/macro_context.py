"""Daily cross-market context from FRED -> data/silver/market_features/macro_daily.parquet.

Series (config/instruments.yaml `macro_context`): DGS2, DGS10, DFII10, VIXCLS, DTWEXBGS.

Point-in-time rule (applied by feature engineering, not here): an observation dated d is a
market close (or noon fixing) and is treated as known only from the NEXT New York calendar day.
So an event at T may use observations with date < T's New York date. Market rates are not
revised, so the current vintage is used.
"""

from datetime import date
from pathlib import Path

import polars as pl

from app.core.universe import Universe
from app.ingestion.jobs import track_job
from app.providers.macro.fred import FredProvider


def macro_path(data_root: Path) -> Path:
    return data_root / "silver" / "market_features" / "macro_daily.parquet"


def run_macro_context(session, universe: Universe, data_root: Path, start: date,
                      end: date) -> dict:
    fred = FredProvider()
    frames, counts = [], {}
    with track_job(session, "fred", "macro_context_daily",
                   {"series": list(universe.macro_context), "start": str(start)}) as stats:
        for sid in universe.macro_context:
            obs = [o for o in fred.observations(sid, start, end, all_vintages=False)
                   if o.value is not None]
            counts[sid] = len(obs)
            frames.append(pl.DataFrame({
                "series_id": [sid] * len(obs),
                "date": [o.observation_date for o in obs],
                "value": [float(o.value) for o in obs],
            }, schema={"series_id": pl.Utf8, "date": pl.Date, "value": pl.Float64}))
        df = pl.concat(frames).sort("series_id", "date")
        p = macro_path(data_root)
        p.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(p)
        stats.rows_fetched = stats.rows_written = df.height
        stats.details = {"rows_per_series": counts, "path": str(p)}
    return {"rows_per_series": counts, "path": str(p)}
