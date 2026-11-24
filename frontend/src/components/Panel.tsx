import type { ReactNode } from 'react'

export function Panel({ title, right, children, className = '' }:
  { title: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`bg-panel border border-line rounded flex flex-col min-h-0 ${className}`}>
      <header className="flex items-center justify-between px-3 py-2 border-b border-line">
        <h2 className="text-[11px] uppercase tracking-wider text-muted">{title}</h2>
        {right}
      </header>
      <div className="min-h-0 overflow-auto">{children}</div>
    </section>
  )
}

export function Notice({ kind = 'info', children }: { kind?: 'info' | 'warn' | 'error';
                                                       children: ReactNode }) {
  const c = kind === 'error' ? 'border-down/50 text-down' : kind === 'warn'
    ? 'border-accent/40 text-accent' : 'border-line text-muted'
  return <div className={`border rounded px-3 py-2 text-[12px] ${c}`}>{children}</div>
}
