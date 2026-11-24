import type { ReactNode } from 'react'
import { useApi } from '../hooks/useApi'
import { api } from '../services/api'

const DOT: Record<string, string> = {
  connected: 'bg-up', degraded: 'bg-accent', unverified: 'bg-muted', disconnected: 'bg-line',
  error: 'bg-down',
}

export function AppLayout({ children, nav }: { children: ReactNode; nav?: ReactNode }) {
  const providers = useApi(s => api.providers(s), [])
  return (
    <div className="h-full flex flex-col">
      <header className="flex items-center justify-between px-4 py-2 border-b border-line">
        <div className="flex items-baseline gap-3">
          <span className="text-accent font-semibold tracking-wide">MACROPULSE</span>
          <span className="text-muted text-[12px]">research only · not trading advice</span>
          <nav className="flex gap-1 ml-4">{nav}</nav>
        </div>
        <div className="flex gap-3 text-[11px] text-muted">
          {providers.error && <span className="text-down">API unreachable</span>}
          {providers.data?.map(p => (
            <span key={p.provider} className="flex items-center gap-1" title={`${p.status}: ${p.detail}`}>
              <span className={`inline-block w-2 h-2 rounded-full ${DOT[p.status] ?? 'bg-line'}`} />
              {p.provider}
            </span>
          ))}
        </div>
      </header>
      <main className="flex-1 min-h-0 overflow-auto p-4">{children}</main>
    </div>
  )
}
