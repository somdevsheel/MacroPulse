"""Empirical timezone detection for vendor price files with an undocumented clock.

Idea: scheduled US releases at 08:30 ET (NFP, CPI, ...) produce a sharp 1-minute volatility spike.
For each release date and each candidate zone, convert the true release instant into that zone's
wall-clock time and measure the spike there relative to the preceding quiet period. The correct
zone wins consistently; a wrong one wins only on noise.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from itertools import groupby
from zoneinfo import ZoneInfo

import polars as pl


@dataclass(frozen=True)
class DateVerdict:
    day: date
    scores: dict[str, float]
    winner: str | None  # None = ambiguous / no data


def spike_score(bars: pl.DataFrame, local_start: datetime, minutes: int = 2) -> float | None:
    """max |1m return| in [start, start+minutes) divided by the median |return| over the prior
    ~45 minutes. `bars` must have naive `t` and `r` (abs 1m return) columns."""
    win = bars.filter((pl.col("t") >= local_start) &
                      (pl.col("t") < local_start + timedelta(minutes=minutes)))
    if win.height == 0:
        return None
    base = bars.filter(
        (pl.col("t") >= local_start - timedelta(minutes=45))
        & (pl.col("t") < local_start - timedelta(minutes=2))
    )["r"].median()
    return float(win["r"].max() or 0.0) / float(base or 1e-9)


def score_dates(
    bars: pl.DataFrame,
    release_instants_utc: Iterable[datetime],
    candidates: dict[str, str],
    min_score: float = 4.0,
    dominance: float = 2.0,
) -> list[DateVerdict]:
    """bars: naive local `t` + `Close`. candidates: label -> IANA zone name."""
    bars = bars.sort("t").with_columns(
        (pl.col("Close") / pl.col("Close").shift(1) - 1).abs().alias("r"),
        pl.col("t").dt.date().alias("_d"),
    )
    zones = {k: ZoneInfo(v) for k, v in candidates.items()}
    out = []
    for inst in sorted(release_instants_utc):
        local = {k: inst.astimezone(z).replace(tzinfo=None) for k, z in zones.items()}
        if len(set(local.values())) < len(local):
            continue  # candidates agree on this date -> not informative
        days = {lt.date() for lt in local.values()}
        day_bars = bars.filter(pl.col("_d").is_in(list(days)))
        scores = {k: s for k, lt in local.items() if (s := spike_score(day_bars, lt)) is not None}
        winner = None
        if scores:
            best = max(scores, key=scores.get)
            rest = [v for k, v in scores.items() if k != best] or [0.0]
            if scores[best] >= min_score and scores[best] >= dominance * max(max(rest), 1e-9):
                winner = best
        out.append(DateVerdict(inst.astimezone(UTC).date(), scores, winner))
    return out


def summarize_runs(verdicts: list[DateVerdict]) -> list[tuple[str, date, date, int]]:
    """Consecutive runs of the same winner: (zone, first_date, last_date, n)."""
    clear = [v for v in verdicts if v.winner]
    runs = []
    for zone, grp in groupby(clear, key=lambda v: v.winner):
        g = list(grp)
        runs.append((zone, g[0].day, g[-1].day, len(g)))
    return runs
