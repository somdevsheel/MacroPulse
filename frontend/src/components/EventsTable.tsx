import { fmtDate, fmtNum, fmtPct, fmtPeriod, fmtValue, signClass } from '../services/format'
import type { ReactionEvent } from '../types'

interface Props {
  events: ReactionEvent[]
  unit: string
  selected: number | null
  onSelect: (id: number) => void
}

export function EventsTable({ events, unit, selected, onSelect }: Props) {
  const rows = [...events].reverse()
  return (
    <table>
      <thead className="sticky top-0 bg-panel">
        <tr>
          <th>Release</th><th>Period</th><th className="text-right">Actual</th>
          <th className="text-right">Previous</th><th className="text-right">Revised</th>
          <th className="text-right" title="actual − previous (no consensus available)">Δ vs prev</th>
          <th className="text-right">−15m</th><th className="text-right">+5m</th>
          <th className="text-right">+15m</th><th className="text-right">+60m</th>
          <th className="text-right">+4h</th><th>Rev 60m</th>
          <th className="text-right">Vol ×</th><th />
        </tr>
      </thead>
      <tbody>
        {rows.map(e => {
          const w = (k: string) => e.windows[k]?.return_pct ?? null
          const delta = e.actual !== null && e.previous !== null ? e.actual - e.previous : null
          return (
            <tr key={e.event_id} onClick={() => onSelect(e.event_id)}
                className={`cursor-pointer hover:bg-line/40 ${selected === e.event_id ? 'bg-line/70' : ''}`}>
              <td>{fmtDate(e.release_time)}</td>
              <td className="text-muted">{fmtPeriod(e.reference_period)}</td>
              <td className="text-right">{fmtValue(e.actual, unit)}</td>
              <td className="text-right text-muted">{fmtValue(e.previous, unit)}</td>
              <td className="text-right text-muted">{fmtValue(e.revised_previous, unit)}</td>
              <td className={`text-right ${signClass(delta)}`}>
                {delta === null ? '—' : fmtNum(delta, 2)}</td>
              <td className={`text-right ${signClass(w('pre_15m'))}`}>{fmtPct(w('pre_15m'), 2)}</td>
              <td className={`text-right ${signClass(w('post_5m'))}`}>{fmtPct(w('post_5m'), 2)}</td>
              <td className={`text-right ${signClass(w('post_15m'))}`}>{fmtPct(w('post_15m'), 2)}</td>
              <td className={`text-right ${signClass(w('post_60m'))}`}>{fmtPct(w('post_60m'), 2)}</td>
              <td className={`text-right ${signClass(w('post_4h'))}`}>{fmtPct(w('post_4h'), 2)}</td>
              <td>{e.reversal_post_60m === null ? <span className="text-muted">—</span>
                   : e.reversal_post_60m ? <span className="text-accent">reversal</span>
                   : <span className="text-muted">held</span>}</td>
              <td className={`text-right ${e.vol_ratio_15m && e.vol_ratio_15m >= 3 ? 'text-accent' : ''}`}>
                {e.vol_ratio_15m ? `${fmtNum(e.vol_ratio_15m, 1)}×` : '—'}</td>
              <td>{e.concurrent_event_ids.length > 0 &&
                <span className="text-[10px] border border-line rounded px-1 text-muted"
                      title="other indicators released at the same timestamp">+{e.concurrent_event_ids.length} simultaneous</span>}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
