export const fmtPct = (v: number | null | undefined, d = 3) =>
  v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(d)}%`

export const fmtNum = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined ? '—' : v.toLocaleString('en-US', { maximumFractionDigits: d })

export const fmtShare = (v: number | null | undefined) =>
  v === null || v === undefined ? '—' : `${v.toFixed(0)}%`

export const signClass = (v: number | null | undefined) =>
  v === null || v === undefined || v === 0 ? 'text-muted' : v > 0 ? 'text-up' : 'text-down'

const utcFmt = new Intl.DateTimeFormat('en-GB', {
  timeZone: 'UTC', year: 'numeric', month: 'short', day: '2-digit', hour: '2-digit',
  minute: '2-digit', hour12: false,
})
const nyFmt = new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/New_York', hour: '2-digit', minute: '2-digit', hour12: false,
  timeZoneName: 'short',
})
export const fmtUtc = (iso: string) => `${utcFmt.format(new Date(iso))} UTC`
export const fmtNy = (iso: string) => nyFmt.format(new Date(iso))
export const fmtDate = (iso: string) => iso.slice(0, 10)
export const fmtPeriod = (iso: string) => iso.slice(0, 7)

/** Value with the indicator's unit (%, thousands, ...). */
export const fmtValue = (v: number | null, unit: string) => {
  if (v === null) return '—'
  if (unit === '%') return `${v.toFixed(2)}%`
  if (unit === 'thousands') return `${v > 0 ? '+' : ''}${fmtNum(v, 0)}k`
  return fmtNum(v, 2)
}

export const WINDOW_LABELS: Record<string, string> = {
  pre_60m: '−60m', pre_30m: '−30m', pre_15m: '−15m', pre_5m: '−5m', pre_1m: '−1m',
  post_1m: '+1m', post_5m: '+5m', post_15m: '+15m', post_30m: '+30m', post_60m: '+60m',
  post_4h: '+4h',
}
export const WINDOW_ORDER = Object.keys(WINDOW_LABELS)
