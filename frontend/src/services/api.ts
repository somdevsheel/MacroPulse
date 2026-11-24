import type {
  BarsResponse,
  CalendarResponse,
  DataStatus,
  EconomicEvent,
  Indicator,
  ModelsResponse,
  Prediction,
  PriceSource,
  ProviderStatus,
  ReactionStudy,
  SimilarResponse,
  Universe,
} from '../types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function get<T>(path: string, params: Record<string, string | number | undefined> = {},
                      signal?: AbortSignal, method: 'GET' | 'POST' = 'GET'): Promise<T> {
  const qs = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== '') qs.set(k, String(v))
  const url = qs.size ? `${path}?${qs}` : path
  const res = await fetch(url, { signal, method })
  if (!res.ok) {
    let msg = res.statusText
    try { msg = (await res.json()).detail ?? msg } catch { /* not json */ }
    throw new ApiError(res.status, typeof msg === 'string' ? msg : JSON.stringify(msg))
  }
  return res.json() as Promise<T>
}

export const api = {
  indicators: (s?: AbortSignal) => get<Indicator[]>('/api/v1/indicators', {}, s),
  universe: (s?: AbortSignal) => get<Universe>('/api/v1/config/universe', {}, s),
  priceSources: (s?: AbortSignal) => get<PriceSource[]>('/api/v1/price-sources', {}, s),
  providers: (s?: AbortSignal) => get<ProviderStatus[]>('/api/v1/providers/status', {}, s),
  reactions: (p: { indicator: string; instrument: string; provider?: string; start?: string;
                   end?: string; neutral_pct?: number }, s?: AbortSignal) =>
    get<ReactionStudy>('/api/v1/analysis/reactions', p, s),
  event: (id: number, s?: AbortSignal) => get<EconomicEvent>(`/api/v1/events/${id}`, {}, s),
  bars: (id: number, p: { instrument: string; provider?: string; before_min: number;
                          after_min: number },
         s?: AbortSignal) => get<BarsResponse>(`/api/v1/events/${id}/bars`, p, s),
  calendar: (p: { days_back: number; days_ahead: number; instrument: string }, s?: AbortSignal) =>
    get<CalendarResponse>('/api/v1/calendar', p, s),
  predictPre: (eventId: number, instrument: string) =>
    get<{ predictions: Prediction[] }>(`/api/v1/predictions/pre-release/${eventId}`,
                                       { instrument }, undefined, 'POST'),
  dataStatus: (s?: AbortSignal) => get<DataStatus>('/api/v1/data/status', {}, s),
  models: (run?: string, s?: AbortSignal) => get<ModelsResponse>('/api/v1/models', { run }, s),
  similar: (id: number, p: { instrument: string; provider?: string; k?: number },
            s?: AbortSignal) =>
    get<SimilarResponse>(`/api/v1/events/${id}/similar`, p, s),
}
