import { useCallback, useEffect, useState } from 'react'
import { api } from './api'

export type Load<T> = { data: T | null; error: string | null; loading: boolean; reload: () => void; setData: (d: T) => void }

/** Fetch `path` (skipped when null) and keep the last good data while reloading. */
export function useApi<T>(path: string | null): Load<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(Boolean(path))
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    if (!path) { setLoading(false); return }
    let alive = true
    setLoading(true)
    api<T>(path)
      .then((d) => { if (alive) { setData(d); setError(null) } })
      .catch((e: Error) => { if (alive) setError(e.message) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [path, nonce])

  const reload = useCallback(() => setNonce((x) => x + 1), [])
  return { data, error, loading, reload, setData }
}
