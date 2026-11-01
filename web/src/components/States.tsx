import type { ReactNode } from 'react'

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="error-box" role="alert">
      <span>{message}</span>
      {onRetry && <button className="btn small" onClick={onRetry}>Retry</button>}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>
}

/** Loading: the final layout's rows as flat grey bars at their real size. */
export function SkeletonRows({ rows = 4, height = 20 }: { rows?: number; height?: number }) {
  return (
    <div className="rows" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <div className="row" key={i}><div className="skeleton" style={{ height, width: `${70 - i * 8}%` }} /></div>
      ))}
    </div>
  )
}

export function Pill({ kind = 'neutral', children }: { kind?: 'pos' | 'neg' | 'warn' | 'neutral'; children: ReactNode }) {
  return <span className={`pill ${kind === 'neutral' ? '' : kind}`}>{children}</span>
}
