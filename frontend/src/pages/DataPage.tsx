import { Notice, Panel } from '../components/Panel'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import { fmtNum } from '../services/format'

const d = (iso: string | null) => (iso ? iso.slice(0, 16).replace('T', ' ') : '—')
const STATUS: Record<string, string> = { succeeded: 'text-up', partial: 'text-accent', failed: 'text-down', running: 'text-muted' }

export function DataPage() {
  const st = useApi(s => api.dataStatus(s), [])
  const prov = useApi(s => api.providers(s), [])
  if (st.error) return <Notice kind="error">{st.error}</Notice>
  if (!st.data) return <div className="text-muted">loading…</div>
  const s = st.data
  return (
    <div className="grid grid-cols-1 2xl:grid-cols-2 gap-4">
      <Panel title="Provider connections">
        <table>
          <thead><tr><th>Provider</th><th>Status</th><th>Detail</th><th>Credential</th></tr></thead>
          <tbody>{(prov.data ?? []).map(p => (
            <tr key={p.provider}><td>{p.provider}</td>
              <td className={p.status === 'connected' ? 'text-up' : p.status === 'disconnected' ? 'text-muted' : 'text-accent'}>{p.status}</td>
              <td className="text-muted whitespace-normal">{p.detail}</td>
              <td>{p.provider in s.credentials ? (s.credentials[p.provider] ? 'configured' : 'missing') : 'not required'}</td></tr>))}
          </tbody>
        </table>
      </Panel>

      <Panel title="Market price coverage (silver)">
        <table>
          <thead><tr><th>Source</th><th>Instrument</th><th>TF</th><th>First (UTC)</th><th>Last (UTC)</th><th className="text-right">Bars</th></tr></thead>
          <tbody>{s.prices.map(p => (
            <tr key={p.provider + p.timeframe}><td>{p.provider}</td><td>{p.instrument}</td><td>{p.timeframe}</td>
              <td>{d(p.first)}</td><td>{d(p.last)}</td><td className="text-right">{fmtNum(p.bars, 0)}</td></tr>))}
          </tbody>
        </table>
      </Panel>

      <Panel title="Economic events">
        <table>
          <thead><tr><th>Indicator</th><th>Source</th><th className="text-right">Events</th><th>First</th><th>Last scheduled</th><th>Last published</th><th className="text-right">No value</th></tr></thead>
          <tbody>{s.events.map(e => (
            <tr key={e.indicator + e.source}><td>{e.indicator}</td><td className="text-muted">{e.source}</td>
              <td className="text-right">{e.events}</td><td>{e.first.slice(0, 10)}</td><td>{e.last.slice(0, 10)}</td>
              <td>{e.last_published?.slice(0, 10) ?? '—'}</td>
              <td className="text-right text-muted" title="upcoming, or not computable (e.g. missing base month)">{e.without_actual}</td></tr>))}
          </tbody>
        </table>
      </Panel>

      <Panel title="Daily macro context (FRED)">
        <table>
          <thead><tr><th>Series</th><th>First</th><th>Last</th><th className="text-right">Rows</th></tr></thead>
          <tbody>{s.macro_context.map(m => (
            <tr key={m.series_id}><td>{m.series_id}</td><td>{m.first}</td><td>{m.last}</td><td className="text-right">{fmtNum(m.rows, 0)}</td></tr>))}
          </tbody>
        </table>
      </Panel>

      <Panel title={`Ingestion jobs · ${s.failed_jobs_total} failed in total`} className="2xl:col-span-2 max-h-[520px]">
        <table>
          <thead className="sticky top-0 bg-panel"><tr><th>#</th><th>Provider</th><th>Type</th><th>Status</th><th>Started (UTC)</th><th className="text-right">Fetched</th><th className="text-right">Written</th><th>Error / warnings</th></tr></thead>
          <tbody>{s.jobs.map(j => (
            <tr key={j.job_id}><td className="text-muted">{j.job_id}</td><td>{j.provider}</td><td>{j.type}</td>
              <td className={STATUS[j.status] ?? ''}>{j.status}</td><td>{d(j.started_at)}</td>
              <td className="text-right">{fmtNum(j.rows_fetched, 0)}</td><td className="text-right">{fmtNum(j.rows_written, 0)}</td>
              <td className="text-muted whitespace-normal max-w-[600px] truncate" title={j.error ?? ''}>{j.error ?? ''}</td></tr>))}
          </tbody>
        </table>
      </Panel>
    </div>
  )
}
