import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import { fmtDate, fmtNum, fmtPct, fmtPeriod, fmtValue, signClass } from '../services/format'
import { Notice, Panel } from './Panel'

interface Props {
  eventId: number
  instrument: string
  provider: string
  unit: string
  onSelect: (id: number) => void
}

export function SimilarEvents({ eventId, instrument, provider, unit, onSelect }: Props) {
  const sim = useApi(s => api.similar(eventId, { instrument, provider, k: 10 }, s),
                     [eventId, instrument, provider])
  return (
    <Panel title="Similar earlier announcements"
           right={sim.data?.features && <span className="text-[11px] text-muted">
             kNN on z-scored [{sim.data.features.join(', ')}] · similarity = 1/(1+distance) · {sim.data.candidates} candidates</span>}>
      {sim.loading && <div className="p-3 text-muted">loading…</div>}
      {sim.error && <div className="p-3"><Notice kind="error">{sim.error}</Notice></div>}
      {sim.data && sim.data.matches.length === 0 &&
        <div className="p-3"><Notice>{sim.data.reason ?? 'No comparable earlier events.'}</Notice></div>}
      {sim.data && sim.data.matches.length > 0 && (
        <table>
          <thead><tr><th>Release</th><th>Period</th><th className="text-right">Actual</th>
            <th className="text-right">Δ vs prev</th><th className="text-right">Similarity</th>
            <th className="text-right">+15m</th><th className="text-right">+60m</th>
            <th className="text-right">+4h</th><th className="text-right" title="minutes to largest excursion within 60m">Peak at</th></tr></thead>
          <tbody>{sim.data.matches.map(m => (
            <tr key={m.event_id} className="cursor-pointer hover:bg-line/40" onClick={() => onSelect(m.event_id)}>
              <td>{fmtDate(m.release_time)}</td><td className="text-muted">{fmtPeriod(m.reference_period)}</td>
              <td className="text-right">{fmtValue(m.actual, unit)}</td>
              <td className={`text-right ${signClass(m.delta)}`}>{fmtNum(m.delta, 2)}</td>
              <td className="text-right">{m.similarity.toFixed(3)}</td>
              <td className={`text-right ${signClass(m.post_15m_pct)}`}>{fmtPct(m.post_15m_pct, 2)}</td>
              <td className={`text-right ${signClass(m.post_60m_pct)}`}>{fmtPct(m.post_60m_pct, 2)}</td>
              <td className={`text-right ${signClass(m.post_4h_pct)}`}>{fmtPct(m.post_4h_pct, 2)}</td>
              <td className="text-right">{m.minutes_to_extreme_60m == null ? '—' : `${m.minutes_to_extreme_60m}m`}</td>
            </tr>))}</tbody>
        </table>
      )}
    </Panel>
  )
}
