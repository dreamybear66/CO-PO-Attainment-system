import { useCallback, useEffect, useState } from 'react'
import { api } from './api'

export type Load<T> = { data: T | null; error: string | null; loading: boolean; reload: () => void; setData: (d: T) => void }

/** Fetch `path` (skipped when null). While the same path reloads, the last good data stays on
 *  screen; when the path changes, data for the old path is never returned for the new one. */
export function useApi<T>(path: string | null): Load<T> {
  const [state, setState] = useState<{ path: string | null; data: T | null }>({ path: null, data: null })
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(Boolean(path))
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    if (!path) { setLoading(false); return }
    let alive = true
    setLoading(true)
    setError(null)
    api<T>(path)
      .then((d) => { if (alive) setState({ path, data: d }) })
      .catch((e: Error) => { if (alive) setError(e.message) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [path, nonce])

  const reload = useCallback(() => setNonce((x) => x + 1), [])
  const setData = useCallback((d: T) => setState({ path, data: d }), [path])
  return { data: state.path === path ? state.data : null, error, loading, reload, setData }
}

/** Fired after an unlock request is decided, so every count of pending requests reloads. */
export const UNLOCKS_CHANGED = 'copo:unlocks-changed'
