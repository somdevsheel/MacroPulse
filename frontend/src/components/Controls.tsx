import type { Indicator, Instrument, PriceSource } from '../types'

export interface Filters {
  indicator: string
  instrument: string
  start: string
  end: string
  neutralPct: number
  provider: string
}

interface Props {
  filters: Filters
  onChange: (f: Filters) => void
  indicators: Indicator[]
  instruments: Record<string, Instrument>
  instrumentsWithData: Set<string>
  sources: PriceSource[]
}

export function Controls({ filters, onChange, indicators, instruments, instrumentsWithData, sources }:
  Props) {
  const set = (patch: Partial<Filters>) => onChange({ ...filters, ...patch })
  const priority = indicators.filter(i => i.priority)
  const others = indicators.filter(i => !i.priority && i.provider !== 'none')
  return (
    <div className="flex flex-wrap items-end gap-4">
      <Field label="Event">
        <select value={filters.indicator} onChange={e => set({ indicator: e.target.value })}>
          <optgroup label="Milestone events">
            {priority.map(i => <option key={i.key} value={i.key}>{i.name}</option>)}
          </optgroup>
          <optgroup label="Other (events not ingested yet)">
            {others.map(i => <option key={i.key} value={i.key}>{i.name}</option>)}
          </optgroup>
        </select>
      </Field>
      <Field label="Instrument">
        <select value={filters.instrument} onChange={e => set({ instrument: e.target.value, provider: '' })}>
          {Object.entries(instruments).map(([sym, d]) => (
            <option key={sym} value={sym} disabled={!instrumentsWithData.has(sym)}>
              {d.display}{instrumentsWithData.has(sym) ? '' : ' — no data'}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Price source">
        <select value={filters.provider} onChange={e => set({ provider: e.target.value })}>
          {sources.filter(s => s.instrument === filters.instrument && s.timeframe === '1m')
            .map(s => <option key={s.provider} value={s.provider}>{s.provider}</option>)}
        </select>
      </Field>
      <Field label="From">
        <input type="date" value={filters.start} onChange={e => set({ start: e.target.value })} />
      </Field>
      <Field label="To">
        <input type="date" value={filters.end} onChange={e => set({ end: e.target.value })} />
      </Field>
      <Field label="Neutral band ±%">
        <input type="number" step="0.01" min="0" max="2" className="w-20"
               value={filters.neutralPct}
               onChange={e => set({ neutralPct: Number(e.target.value) || 0 })} />
      </Field>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] text-muted uppercase tracking-wider">{label}</span>
      {children}
    </label>
  )
}
