import { useEffect, useMemo, useState } from 'react'
import { Controls, type Filters } from '../components/Controls'
import { EventDetail } from '../components/EventDetail'
import { EventsTable } from '../components/EventsTable'
import { Notice, Panel } from '../components/Panel'
import { SimilarEvents } from '../components/SimilarEvents'
import { StatsTable } from '../components/StatsTable'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'

const DEFAULTS: Filters = {
  indicator: 'cpi_mom', instrument: 'XAUUSD', start: '2010-01-01',
  end: new Date().toISOString().slice(0, 10), neutralPct: 0.05, provider: '',
}

export function ReactionPage() {
  const [filters, setFilters] = useState<Filters>(DEFAULTS)
  const [selected, setSelected] = useState<number | null>(null)
  const indicators = useApi(s => api.indicators(s), [])
  const universe = useApi(s => api.universe(s), [])
  const sources = useApi(s => api.priceSources(s), [])
  const withData = useMemo(() => new Set((sources.data ?? []).filter(s => s.timeframe === '1m')
                                                            .map(s => s.instrument)), [sources.data])
  // Default source: OANDA (UTC, bid/ask) when available, else the first one with data.
  const instSources = (sources.data ?? []).filter(s => s.instrument === filters.instrument &&
                                                       s.timeframe === '1m').map(s => s.provider)
  const provider = filters.provider || (instSources.includes('oanda') ? 'oanda' : instSources[0] ?? '')
  const study = useApi(s => api.reactions({ indicator: filters.indicator,
                                            instrument: filters.instrument, provider,
                                            start: filters.start, end: filters.end,
                                            neutral_pct: filters.neutralPct }, s),
                       [filters, provider], withData.has(filters.instrument) && !!provider)

  const indicator = indicators.data?.find(i => i.key === filters.indicator)
  const precision = universe.data?.instruments[filters.instrument]?.price_precision ?? 2
  const events = study.data?.events ?? []
  const current = events.find(e => e.event_id === selected) ?? null

  // Default selection: most recent event with price data.
  useEffect(() => {
    if (events.length && !events.some(e => e.event_id === selected)) {
      setSelected([...events].reverse().find(e => Object.keys(e.windows).length)?.event_id ?? null)
    }
  }, [events, selected])

  if (indicators.error) return <Notice kind="error">Cannot reach the API: {indicators.error}</Notice>
  if (!indicators.data || !universe.data) return <div className="text-muted">loading…</div>

  return (
    <div className="flex flex-col gap-4">
      <Controls filters={{ ...filters, provider }} onChange={f => { setFilters(f) }}
                sources={sources.data ?? []}
                indicators={indicators.data} instruments={universe.data.instruments}
                instrumentsWithData={withData} />

      <Notice kind="warn">
        Consensus forecasts are not connected (paid source required). "Δ vs prev" is actual minus
        previous, <b>not</b> a market surprise. Gold data: Kaggle/OctaFX bid, gaps 2025-09-12→10-15
        and 2026-01-13→01-22. OANDA: UTC mid prices with bid/ask, tick volume.
      </Notice>

      {study.error && <Notice kind="error">{study.error}</Notice>}
      {study.loading && <div className="text-muted">computing reaction statistics…</div>}
      {study.data && (
        <>
          <Panel title={<>{indicator?.name} → {universe.data.instruments[filters.instrument]?.display}
                           · {study.data.n_events} announcements</>}
                 right={study.data.windows_dropped_low_coverage_or_no_anchor > 0 &&
                   <span className="text-[11px] text-muted">
                     {study.data.windows_dropped_low_coverage_or_no_anchor} windows excluded
                     (missing data / &lt;{study.data.min_coverage * 100}% minutes present)</span>}>
            {study.data.n_events === 0
              ? <div className="p-3"><Notice>No announcements with price data in this range.
                  {indicator && !indicator.priority && ' This indicator is not ingested yet.'}</Notice></div>
              : <StatsTable stats={study.data.stats} neutralPct={study.data.neutral_threshold_pct} />}
          </Panel>

          {study.data.n_events > 0 && (
            <div className="grid grid-cols-1 2xl:grid-cols-2 gap-4">
              <Panel title="Announcements (click to chart)" className="max-h-[720px]">
                <EventsTable events={events} unit={indicator?.unit ?? ''} selected={selected}
                             onSelect={setSelected} />
              </Panel>
              <div className="flex flex-col gap-4">
                {current
                  ? <>
                      <EventDetail event={current} instrument={filters.instrument} provider={provider}
                                   precision={precision} unit={indicator?.unit ?? ''} />
                      <SimilarEvents eventId={current.event_id} instrument={filters.instrument} provider={provider}
                                     unit={indicator?.unit ?? ''} onSelect={setSelected} />
                    </>
                  : selected !== null &&
                    <Notice>That announcement is outside the selected date range — widen the range to view it.</Notice>}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
