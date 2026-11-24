import { useState } from 'react'
import { EventChart } from '../charts/EventChart'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import { fmtNum, fmtNy, fmtPct, fmtUtc, fmtValue, signClass, WINDOW_LABELS, WINDOW_ORDER }
  from '../services/format'
import type { ReactionEvent } from '../types'
import { Notice, Panel } from './Panel'

const RANGES = [
  { label: '−60m / +60m', before: 60, after: 60 },
  { label: '−60m / +4h', before: 60, after: 240 },
  { label: '−4h / +8h', before: 240, after: 480 },
]

interface Props {
  event: ReactionEvent
  instrument: string
  provider: string
  precision: number
  unit: string
}

export function EventDetail({ event, instrument, provider, precision, unit }: Props) {
  const [range, setRange] = useState(RANGES[1])
  const bars = useApi(s => api.bars(event.event_id, { instrument, provider,
                                                      before_min: range.before,
                                                      after_min: range.after }, s),
                      [event.event_id, instrument, provider, range])
  const meta = useApi(s => api.event(event.event_id, s), [event.event_id])
  const coverage = bars.data ? bars.data.bar_count / bars.data.expected_bars : null

  return (
    <Panel
      title={<>Event · {fmtUtc(event.release_time)} <span className="normal-case">({fmtNy(event.release_time)})</span></>}
      right={<div className="flex gap-1">{RANGES.map(r => (
        <button key={r.label} onClick={() => setRange(r)}
                className={`px-2 py-0.5 rounded border text-[11px] ${r === range ? 'border-accent text-accent' : 'border-line text-muted hover:text-text'}`}>
          {r.label}</button>))}</div>}>
      <div className="p-3 flex flex-col gap-3">
        <div className="flex flex-wrap gap-x-6 gap-y-1">
          <Kv k="Actual" v={fmtValue(event.actual, unit)} />
          <Kv k="Previous (known before)" v={fmtValue(event.previous, unit)} />
          <Kv k="Previous (revised)" v={fmtValue(event.revised_previous, unit)} />
          <Kv k="Consensus" v={event.consensus === null ? 'not available' : fmtValue(event.consensus, unit)} />
          <Kv k="Release time" v={event.release_time_source.replace('_', ' ')} />
          {meta.data?.concurrent && meta.data.concurrent.length > 0 &&
            <Kv k="Simultaneous" v={meta.data.concurrent.map(c => `${c.name} ${fmtValue(c.actual, c.unit)}`).join(' · ')} />}
        </div>

        {bars.loading && <div className="h-[380px] grid place-items-center text-muted">loading bars…</div>}
        {bars.error && <Notice kind="error">{bars.error}</Notice>}
        {bars.data && (bars.data.bar_count === 0
          ? <Notice kind="warn">No price data for this event in {bars.data.provider}.</Notice>
          : <>
              <EventChart data={bars.data} precision={precision} />
              <div className="text-[11px] text-muted flex gap-4">
                <span>{bars.data.instrument} · 1-minute · {bars.data.provider} · UTC axis</span>
                <span className={coverage !== null && coverage < 0.8 ? 'text-accent' : ''}>
                  {bars.data.bar_count}/{bars.data.expected_bars} minutes present
                  {coverage !== null && coverage < 1 ? ' (gaps shown as empty space, not filled)' : ''}
                </span>
              </div>
            </>)}

        <table>
          <thead><tr><th>Window</th>{WINDOW_ORDER.map(w => <th key={w} className="text-right">{WINDOW_LABELS[w]}</th>)}</tr></thead>
          <tbody>
            <tr><td className="text-muted">Return</td>{WINDOW_ORDER.map(w => {
              const v = event.windows[w]?.return_pct ?? null
              return <td key={w} className={`text-right ${signClass(v)}`}>{fmtPct(v, 2)}</td>
            })}</tr>
            <tr><td className="text-muted">Move</td>{WINDOW_ORDER.map(w =>
              <td key={w} className="text-right">{fmtNum(event.windows[w]?.abs_move ?? null, precision)}</td>)}</tr>
            <tr><td className="text-muted">MFE / MAE</td>{WINDOW_ORDER.map(w => {
              const m = event.windows[w]
              return <td key={w} className="text-right">{m?.mfe_pct == null ? '—' : `${m.mfe_pct.toFixed(2)} / ${m.mae_pct?.toFixed(2)}`}</td>
            })}</tr>
            <tr><td className="text-muted">Realized vol</td>{WINDOW_ORDER.map(w =>
              <td key={w} className="text-right">{fmtNum(event.windows[w]?.realized_vol ?? null, 3)}</td>)}</tr>
            <tr><td className="text-muted">Min to extreme</td>{WINDOW_ORDER.map(w =>
              <td key={w} className="text-right">{event.windows[w]?.minutes_to_extreme ?? '—'}</td>)}</tr>
          </tbody>
        </table>
      </div>
    </Panel>
  )
}

function Kv({ k, v }: { k: string; v: string }) {
  return <div><span className="text-muted text-[11px]">{k}: </span><span>{v}</span></div>
}
