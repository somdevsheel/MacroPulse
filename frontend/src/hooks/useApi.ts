import { useEffect, useState } from 'react'

export interface ApiState<T> {
  data: T | null
  error: string | null
  loading: boolean
}

/** Runs `fn` whenever `deps` change; aborts stale requests. Pass `enabled=false` to skip. */
export function useApi<T>(fn: (signal: AbortSignal) => Promise<T>, deps: unknown[],
                          enabled = true): ApiState<T> {
  const [state, setState] = useState<ApiState<T>>({ data: null, error: null, loading: enabled })
  useEffect(() => {
    if (!enabled) { setState({ data: null, error: null, loading: false }); return }
    const ctrl = new AbortController()
    setState(s => ({ ...s, loading: true, error: null }))
    fn(ctrl.signal)
      .then(data => setState({ data, error: null, loading: false }))
      .catch(e => { if (!ctrl.signal.aborted) setState({ data: null, error: String(e.message ?? e), loading: false }) })
    return () => ctrl.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, enabled])
  return state
}
