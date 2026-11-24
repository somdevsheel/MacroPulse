import { useState } from 'react'
import { Notice, Panel } from '../components/Panel'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'
import type { ModelEntry } from '../types'

const TASK_LABEL: Record<string, string> = {
  pre_direction_15m: 'Pre-release · direction at +15m',
  pre_direction_60m: 'Pre-release · direction at +60m',
  pre_volatility_60m: 'Pre-release · |move| at +60m (volatility)',
  post_direction_5_15m: 'Post-release (as of +5m) · direction +5m→+15m',
  post_direction_5_60m: 'Post-release (as of +5m) · direction +5m→+60m',
}

const f = (v: number | null | undefined, d = 4) => (v === null || v === undefined ? '—' : v.toFixed(d))

export function ModelPerformancePage() {
  const [run, setRun] = useState<string | undefined>()
  const res = useApi(s => api.models(run, s), [run])
  if (res.error) return <Notice kind="error">{res.error}</Notice>
  if (!res.data) return <div className="text-muted">loading…</div>
  if (!res.data.run) return <Notice>No trained models yet. Run <code>python -m app.ingestion.cli train</code>.</Notice>

  const tasks = Object.values(res.data.tasks)
  const anyBeats = tasks.some(t => t.models.some(m => m.selected && m.beats_prior))
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-end gap-4">
        <label className="flex flex-col gap-1">
          <span className="text-[11px] text-muted uppercase tracking-wider">Training run</span>
          <select value={res.data.run} onChange={e => setRun(e.target.value)}>
            {res.data.runs.map(r => <option key={r}>{r}</option>)}
          </select>
        </label>
        <span className="text-[11px] text-muted max-w-[900px]">{res.data.protocol}</span>
      </div>

      <Notice kind={anyBeats ? 'info' : 'warn'}>
        {anyBeats
          ? 'At least one selected model beats its baseline on out-of-sample data. Probabilities are still estimates, not guarantees of profit.'
          : <>No model beats the naive baseline (historical class frequencies / mean move per release type) out of sample.
             Predictions from these models carry <b>no demonstrated edge</b>; they are kept as registered baselines for comparison
             as data improves (consensus forecasts, more instruments).</>}
      </Notice>

      {tasks.map(t => <TaskPanel key={t.task} task={t.task} models={t.models} />)}
    </div>
  )
}

function TaskPanel({ task, models }: { task: string; models: ModelEntry[] }) {
  const clf = !!models[0]?.walk_forward && 'log_loss' in (models[0].walk_forward ?? {})
  const key = clf ? 'log_loss' : 'mae'
  const cols = clf ? ['log_loss', 'brier', 'accuracy', 'macro_f1', 'roc_auc_ovr', 'directional_hit_rate']
                   : ['mae', 'rmse', 'corr']
  const sel = models.find(m => m.selected)
  const prior = models.find(m => m.algorithm === 'prior')
  const folds = Object.keys(sel?.per_fold ?? {})
  return (
    <Panel title={TASK_LABEL[task] ?? task}
           right={sel && <span className={`text-[11px] ${sel.beats_prior ? 'text-up' : 'text-accent'}`}>
             selected: {sel.algorithm} · {sel.beats_prior ? 'beats baseline' : 'no edge vs baseline'}
             {sel.vs_prior_walk_forward && ` · Δ${sel.vs_prior_walk_forward.loss} ${sel.vs_prior_walk_forward.mean_diff >= 0 ? '+' : ''}${f(sel.vs_prior_walk_forward.mean_diff)} [${f(sel.vs_prior_walk_forward.ci95[0])}, ${f(sel.vs_prior_walk_forward.ci95[1])}]`}
           </span>}>
      <div className="p-3 flex flex-col gap-3">
        <table>
          <thead><tr><th>Model</th>{cols.map(c => <th key={c} className="text-right">WF {c}</th>)}
            <th className="text-right">Val {key}</th><th className="text-right">Test {key}</th><th>Status</th></tr></thead>
          <tbody>{models.map(m => (
            <tr key={m.model_id} className={m.selected ? 'text-text' : 'text-muted'}>
              <td>{m.algorithm}{m.algorithm === 'prior' && ' (baseline)'}</td>
              {cols.map(c => {
                const v = m.walk_forward?.[c] ?? null
                const pv = prior?.walk_forward?.[c] ?? null
                const lowerBetter = ['log_loss', 'brier', 'mae', 'rmse'].includes(c)
                const better = v !== null && pv !== null && m.algorithm !== 'prior' &&
                  (lowerBetter ? v < pv : v > pv)
                return <td key={c} className={`text-right ${better ? 'text-up' : ''}`}>{f(v)}</td>
              })}
              <td className="text-right">{f(m.validation?.[key])}</td>
              <td className="text-right">{f(m.test?.[key])}</td>
              <td>{m.status}</td>
            </tr>))}</tbody>
        </table>

        {sel && folds.length > 0 && (
          <div>
            <div className="text-[11px] text-muted mb-1">Walk-forward by test year · {key} (selected vs baseline; green = better than baseline that year)</div>
            <div className="flex flex-wrap gap-1">
              {folds.map(y => {
                const a = sel.per_fold?.[y]?.[key] ?? null
                const b = prior?.per_fold?.[y]?.[key] ?? null
                const better = a !== null && b !== null && a < b
                return <div key={y} className={`border rounded px-2 py-1 text-[11px] ${better ? 'border-up/50 text-up' : 'border-line text-muted'}`}
                            title={`${sel.algorithm} ${f(a)} vs prior ${f(b)} (n=${sel.per_fold?.[y]?.n})`}>
                  {y} <span className="text-text">{f(a, 3)}</span> / {f(b, 3)}</div>
              })}
            </div>
          </div>
        )}

        {sel?.calibration_p_bullish && (
          <div>
            <div className="text-[11px] text-muted mb-1">Calibration of P(bullish), walk-forward (quintiles): predicted → observed</div>
            <div className="flex gap-3 text-[11px]">
              {sel.calibration_p_bullish.map((c, i) => (
                <span key={i} className="border border-line rounded px-2 py-1">
                  {(c.p_mean * 100).toFixed(0)}% → {(c.observed * 100).toFixed(0)}% <span className="text-muted">(n={c.n})</span></span>
              ))}
            </div>
          </div>
        )}
      </div>
    </Panel>
  )
}
