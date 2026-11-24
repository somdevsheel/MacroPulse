export interface Indicator {
  key: string
  name: string
  category: string
  importance: string
  priority: boolean
  unit: string
  release: string
  provider: string
}

export interface Instrument {
  display: string
  asset_class: string
  price_precision: number
}

export interface Universe {
  instruments: Record<string, Instrument>
}

export interface PriceSource {
  provider: string
  instrument: string
  timeframe: string
}

export interface ProviderStatus {
  provider: string
  status: 'connected' | 'disconnected' | 'unverified' | 'degraded' | 'error'
  checked_at: string
  detail: string
}

export interface WindowMetrics {
  return_pct: number | null
  abs_move: number | null
  realized_vol: number | null
  mfe_pct: number | null
  mae_pct: number | null
  minutes_to_extreme: number | null
  coverage: number
  high: number | null
  low: number | null
}

export interface ReactionEvent {
  event_id: number
  release_time: string
  reference_period: string
  actual: number | null
  previous: number | null
  revised_previous: number | null
  consensus: number | null
  release_time_source: string
  concurrent_event_ids: number[]
  windows: Record<string, WindowMetrics>
  direction_post_15m: 'bullish' | 'bearish' | 'neutral' | null
  reversal_post_60m: boolean | null
  vol_ratio_15m: number | null
}

export interface WindowStats {
  window: string
  n: number
  mean_pct: number | null
  median_pct: number | null
  pct_bullish: number | null
  pct_bearish: number | null
  pct_neutral: number | null
  reversal_frequency: number | null
  reversal_n: number
  avg_vol_ratio: number | null
  max_positive_pct: number | null
  max_negative_pct: number | null
  std_pct: number | null
}

export interface ReactionStudy {
  indicator: string
  instrument: string
  provider: string
  neutral_threshold_pct: number
  min_coverage: number
  n_events: number
  windows_dropped_low_coverage_or_no_anchor: number
  stats: WindowStats[]
  events: ReactionEvent[]
  notes: string[]
}

export interface EconomicEvent {
  event_id: number
  indicator: string
  name: string
  kind: string
  release_time: string
  release_time_source: string
  reference_period: string
  unit: string
  actual: number | null
  previous: number | null
  revised_previous: number | null
  consensus: number | null
  concurrent?: EconomicEvent[]
}

export interface Bar {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number | null
}

export interface BarsResponse {
  event_id: number
  instrument: string
  provider: string
  release_time: string
  release_epoch: number
  expected_bars: number
  bar_count: number
  bars: Bar[]
}

export interface SimilarMatch {
  event_id: number
  release_time: string
  reference_period: string
  actual: number | null
  previous: number | null
  delta: number | null
  distance: number
  similarity: number
  post_15m_pct: number | null
  post_60m_pct: number | null
  post_4h_pct: number | null
  minutes_to_extreme_60m: number | null
}

export interface SimilarResponse {
  event_id: number
  method: string
  features?: string[]
  candidates?: number
  matches: SimilarMatch[]
  reason?: string
}

export type Metrics = Record<string, number | null>

export interface ModelEntry {
  model_id: number
  algorithm: string
  status: 'active' | 'trained' | 'candidate'
  selected: boolean
  beats_prior: boolean | null
  vs_prior_walk_forward: { mean_diff: number; ci95: [number, number]; loss: string } | null
  walk_forward: Metrics | null
  validation: Metrics | null
  test: Metrics | null
  per_fold: Record<string, Metrics> | null
  calibration_p_bullish: { p_mean: number; observed: number; n: number }[] | null
}

export interface ModelsResponse {
  runs: string[]
  run: string | null
  protocol?: string
  tasks: Record<string, { task: string; phase: string; models: ModelEntry[] }>
}

export interface Prediction {
  prediction_id: number
  event_id: number
  phase: string
  horizon_minutes: number
  prediction_ts: string
  model: string | null
  p_bullish: number | null
  p_bearish: number | null
  p_neutral: number | null
  expected_return_pct: number | null
  expected_move_pct: number | null
  expected_volatility: number | null
  p_reversal: number | null
  p_breakout: number | null
  confidence: number | null
  realized_return_pct: number | null
  realized_direction: string | null
  evaluated_at: string | null
}

export interface CalendarEvent {
  event_id: number
  indicator: string
  name: string
  release: string
  importance: string
  kind: string
  release_time: string
  release_time_source: string
  countdown_seconds: number
  status: 'upcoming' | 'released' | 'awaiting_data'
  reference_period: string
  unit: string
  actual: number | null
  previous: number | null
  revised_previous: number | null
  consensus: number | null
  is_headline: boolean
  affected_instruments: { symbol: string; display: string; has_data: boolean }[]
  historical_volatility: { n: number; median_abs_move_15m_pct: number | null;
                           median_vol_ratio_15m: number | null } | null
  predictions: Prediction[]
}

export interface CalendarResponse {
  now: string
  instrument: string
  events: CalendarEvent[]
  notes: string[]
}

export interface DataStatus {
  prices: { provider: string; instrument: string; timeframe: string; first: string; last: string; bars: number }[]
  events: { indicator: string; source: string; events: number; first: string; last: string;
            without_actual: number; last_published: string | null }[]
  macro_context: { series_id: string; first: string; last: string; rows: number }[]
  jobs: { job_id: number; provider: string; type: string; status: string; rows_fetched: number;
          rows_written: number; error: string | null; started_at: string | null;
          finished_at: string | null }[]
  failed_jobs_total: number
  credentials: Record<string, boolean>
}
