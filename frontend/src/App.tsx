import { useState } from 'react'
import { AppLayout } from './layouts/AppLayout'
import { CalendarPage } from './pages/CalendarPage'
import { DataPage } from './pages/DataPage'
import { ModelPerformancePage } from './pages/ModelPerformancePage'
import { ReactionPage } from './pages/ReactionPage'

const PAGES = {
  calendar: { label: 'Economic calendar', el: <CalendarPage /> },
  reaction: { label: 'Historical event analysis', el: <ReactionPage /> },
  models: { label: 'Model performance', el: <ModelPerformancePage /> },
  data: { label: 'Data management', el: <DataPage /> },
} as const
type PageKey = keyof typeof PAGES

export default function App() {
  const [page, setPage] = useState<PageKey>(
    (new URLSearchParams(location.search).get('page') as PageKey) in PAGES
      ? new URLSearchParams(location.search).get('page') as PageKey : 'calendar')
  const go = (p: PageKey) => { setPage(p); history.replaceState(null, '', `?page=${p}`) }
  return (
    <AppLayout nav={(Object.keys(PAGES) as PageKey[]).map(k => (
      <button key={k} onClick={() => go(k)}
              className={`px-3 py-1 rounded text-[12px] ${k === page ? 'bg-line text-text' : 'text-muted hover:text-text'}`}>
        {PAGES[k].label}</button>))}>
      {PAGES[page].el}
    </AppLayout>
  )
}
