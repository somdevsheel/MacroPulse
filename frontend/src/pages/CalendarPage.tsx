import { useEffect, useState } from 'react'
import { Notice, Panel } from '../components/Panel'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import { fmtNy, fmtPct, fmtPeriod, fmtUtc, fmtValue } from '../services/format'
import type { CalendarEvent, Prediction } from '../types'

function countdown(sec: number) {
  if (sec <= 0) return 'released'
  const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60)
  return d ? `${d}d ${h}h ${m}m` : h ? `${h}h ${m}m` : `${m}m ${sec % 60}s`
}

export function CalendarPage() {
  const [tick, setTick] = useState(0)
  const [reload, setReload] = useState(0)
  const [busy, setBusy] = useState<number | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const cal = useApi(s => api.calendar({ days_back: 7, days_ahead: 60, instrument: 'XAUUSD' }, s), [reload])
  useEffect(() => { const t = setInterval(() => setTick(x => x + 1), 1000); return () => clearInterval(t) }, [])

  if (cal.error) return <Notice kind="error">{cal.error}</Notice>
  if (!cal.data) return <div className="text-muted">loading…</div>
  const loadedAt = new Date(cal.data.now).getTime()
  const elapsed = Math.floor((Date.now() - loadedAt) / 1000) + 0 * tick
  // One row per release timestamp: headline indicator, others listed alongside.
  const groups = new Map<string, CalendarEvent[]>()
  for (const e of cal.data.events) {
    const k = `${e.release_time}|${e.release}`
    groups.set(k, [...(groups.get(k) ?? []), e])
  }

  const predict = async (id: number) => {
    setBusy(id); setErr(null)
    try { await api.predictPre(id, 'XAUUSD'); setReload(r => r + 1) }
    catch (e) { setErr(String((e as Error).message)) }
    finally { setBusy(null) }
  }

  return (
    <div className="flex flex-col gap-4">
      <Notice kind="warn">
        Consensus forecasts are not connected. Predictions are <b>historical base rates</b> for XAU/USD
        (what gold did after earlier releases of the same type) — no trained model beat them out of sample.
        Confidence = how lopsided history is, not a probability of being right.
      </Notice>
      {err && <Notice kind="error">{err}</Notice>}
      <Panel title={`US economic calendar · last 7 days and next 60 days · times UTC (New York)`}>
        <table>
          <thead><tr><th>Release (UTC)</th><th>NY</th><th>Countdown</th><th>Event</th><th>Period</th>
            <th>Imp.</th><th className="text-right">Actual</th><th className="text-right">Consensus</th>
            <th className="text-right">Previous</th><th className="text-right" title="median |XAU/USD move| 15m after past releases">Gold |15m|</th>
            <th className="text-right" title="median post/pre realized vol, 15m">Vol ×</th><th>XAU/USD base rate (+15m / +60m)</th><th /></tr></thead>
          <tbody>
            {[...groups.values()].map(g => {
              const e = g.find(x => x.is_headline) ?? g[0]
              const others = g.filter(x => x !== e)
              const sec = e.countdown_seconds - elapsed
              const hv = e.historical_volatility
              const p15 = e.predictions.find(p => p.horizon_minutes === 15)
              const p60 = e.predictions.find(p => p.horizon_minutes === 60)
              return (
                <tr key={e.event_id} className={e.status === 'upcoming' ? '' : 'text-muted'}>
                  <td>{fmtUtc(e.release_time).replace(' UTC', '')}</td>
                  <td className="text-muted">{fmtNy(e.release_time)}</td>
                  <td className={sec > 0 && sec < 86400 ? 'text-accent' : ''}>{e.status === 'upcoming' ? countdown(sec) : e.status.replace('_', ' ')}</td>
                  <td>
                    <div>{e.name}{e.release_time_source === 'unknown' && <span className="text-accent"> (time unverified)</span>}</div>
                    {others.length > 0 && <div className="text-[11px] text-muted">+ {others.map(o => `${o.name}${o.actual !== null ? ' ' + fmtValue(o.actual, o.unit) : ''}`).join(' · ')}</div>}
                  </td>
                  <td className="text-muted">{e.kind.startsWith('fomc') ? '' : fmtPeriod(e.reference_period)}</td>
                  <td className={e.importance === 'high' ? 'text-accent' : 'text-muted'}>{e.importance}</td>
                  <td className="text-right">{fmtValue(e.actual, e.unit)}</td>
                  <td className="text-right text-muted">{e.consensus === null ? 'n/a' : fmtValue(e.consensus, e.unit)}</td>
                  <td className="text-right">{fmtValue(e.previous, e.unit)}</td>
                  <td className="text-right">{hv?.median_abs_move_15m_pct == null ? '—' : `${hv.median_abs_move_15m_pct.toFixed(2)}%`}</td>
                  <td className="text-right">{hv?.median_vol_ratio_15m == null ? '—' : `${hv.median_vol_ratio_15m.toFixed(1)}×`}</td>
                  <td>{p15 || p60 ? <span className="flex gap-3"><Pred p={p15} /><Pred p={p60} /></span> : <span className="text-muted">—</span>}</td>
                  <td>{e.status === 'upcoming' &&
                    <button disabled={busy === e.event_id} onClick={() => predict(e.event_id)}
                            className="px-2 py-0.5 rounded border border-line text-[11px] hover:border-accent hover:text-accent disabled:opacity-50">
                      {busy === e.event_id ? '…' : p15 ? 'refresh' : 'predict'}</button>}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </Panel>
      <div className="text-[11px] text-muted">
        Affected instruments: XAU/USD and all USD pairs (only XAU/USD has price data). Stored predictions
        keep their timestamp and model version and are scored automatically once post-release prices exist.
      </div>
    </div>
  )
}

function Pred({ p }: { p?: Prediction }) {
  if (!p) return null
  const pct = (v: number | null) => (v === null ? '—' : `${Math.round(v * 100)}%`)
  return (
    <span title={`${p.model} · made ${p.prediction_ts} · expected |move| ${fmtPct(p.expected_move_pct, 2)} · conf ${p.confidence?.toFixed(2)}${p.p_reversal != null ? ` · reversal ${pct(p.p_reversal)}` : ''}${p.realized_return_pct != null ? ` · realised ${fmtPct(p.realized_return_pct, 2)}` : ''}`}>
      <span className="text-up">▲{pct(p.p_bullish)}</span> <span className="text-down">▼{pct(p.p_bearish)}</span>{' '}
      <span className="text-muted">={pct(p.p_neutral)}</span>
      {p.realized_direction && <span className="text-accent"> → {p.realized_direction}</span>}
    </span>
  )
}
