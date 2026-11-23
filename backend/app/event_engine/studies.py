"""Aggregate reaction statistics across many events (pure functions over window rows).

Definitions:
  direction     bullish if return > +threshold, bearish if < -threshold, else neutral
                (threshold = neutral_threshold_pct, default 0.05%).
  reversal      for a post window w: the initial move (post_5m, non-neutral) and the w return
                have opposite signs and |w return| > threshold. Only defined for w longer than 5m.
  vol ratio     realized vol post_k / realized vol pre_k for matching k (15m, 30m, 60m);
                the MEDIAN ratio across events is reported (robust to quiet pre-windows).
"""

import statistics
from dataclasses import dataclass

DEFAULT_NEUTRAL_PCT = 0.05
VOL_PAIRS = {"post_15m": "pre_15m", "post_30m": "pre_30m", "post_60m": "pre_60m"}
REVERSAL_BASE = "post_5m"


def direction(ret: float | None, thr: float) -> str | None:
    if ret is None:
        return None
    return "bullish" if ret > thr else ("bearish" if ret < -thr else "neutral")


def is_reversal(initial: float | None, later: float | None, thr: float) -> bool | None:
    if initial is None or later is None or abs(initial) <= thr:
        return None  # no clear initial move -> reversal undefined
    return (initial > 0) != (later > 0) and abs(later) > thr


@dataclass
class WindowStats:
    window: str
    n: int
    mean_pct: float | None
    median_pct: float | None
    pct_bullish: float | None
    pct_bearish: float | None
    pct_neutral: float | None
    reversal_frequency: float | None
    reversal_n: int
    avg_vol_ratio: float | None
    max_positive_pct: float | None
    max_negative_pct: float | None
    std_pct: float | None


def aggregate(events: list[dict[str, dict]], thr: float = DEFAULT_NEUTRAL_PCT
              ) -> list[WindowStats]:
    """events: [{window_label: {"return_pct":.., "realized_vol":..}, ...}, ...] (usable only)."""
    labels = list(dict.fromkeys(k for e in events for k in e))
    out = []
    for w in labels:
        rets = [e[w]["return_pct"] for e in events if e.get(w, {}).get("return_pct") is not None]
        n = len(rets)
        dirs = [direction(r, thr) for r in rets]
        revs = []
        if w.startswith("post_") and w not in ("post_1m", "post_5m"):
            revs = [r for e in events
                    if (r := is_reversal(e.get(REVERSAL_BASE, {}).get("return_pct"),
                                         e.get(w, {}).get("return_pct"), thr)) is not None]
        ratios = []
        if w in VOL_PAIRS:
            for e in events:
                post = e.get(w, {}).get("realized_vol")
                pre = e.get(VOL_PAIRS[w], {}).get("realized_vol")
                if post is not None and pre:
                    ratios.append(post / pre)
        out.append(WindowStats(
            window=w, n=n,
            mean_pct=statistics.fmean(rets) if n else None,
            median_pct=statistics.median(rets) if n else None,
            pct_bullish=100 * dirs.count("bullish") / n if n else None,
            pct_bearish=100 * dirs.count("bearish") / n if n else None,
            pct_neutral=100 * dirs.count("neutral") / n if n else None,
            reversal_frequency=100 * sum(revs) / len(revs) if revs else None,
            reversal_n=len(revs),
            avg_vol_ratio=statistics.median(ratios) if ratios else None,
            max_positive_pct=max(rets) if n else None,
            max_negative_pct=min(rets) if n else None,
            std_pct=statistics.stdev(rets) if n > 1 else None,
        ))
    return out
