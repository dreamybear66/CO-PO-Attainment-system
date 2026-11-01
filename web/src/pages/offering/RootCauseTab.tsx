import { useState } from 'react'
import { api } from '../../api'
import { Empty, ErrorBox, Pill, SkeletonRows } from '../../components/States'
import { level } from '../../format'
import { useApi } from '../../hooks'
import type { AttainmentData, OfferingDetail } from './types'

type Candidate = {
  up_co_id: number; up_course_code: string; up_co_number: number; up_statement: string; depth: number
  path_strength: string; correlation: string | null; n: number; up_final_level: string | null
  up_shortfall: string | null; passes: boolean; likely_cause_rank: number | null
}

export function RootCauseTab({ offering, att, canEdit, onAction }: {
  offering: OfferingDetail; att: AttainmentData | null; canEdit: boolean; onAction: () => void
}) {
  const cos = att?.cos ?? []
  const below = cos.filter((c) => Number(c.final_level) < Number(c.target))
  const [co, setCo] = useState<number | null>(null)
  const active = co ?? below[0]?.co_id ?? cos[0]?.co_id ?? null
  const res = useApi<Candidate[]>(active ? `/api/offerings/${offering.offering_id}/cos/${active}/root-cause` : null)
  const [msg, setMsg] = useState<string | null>(null)

  if (!cos.length) return <Empty>Compute attainment first; the analysis starts from a CO that missed its target.</Empty>
  const chosen = cos.find((c) => c.co_id === active)
  const passing = (res.data ?? []).filter((r) => r.passes)

  async function addAction() {
    setMsg(null)
    try {
      await api(`/api/offerings/${offering.offering_id}/cos/${active}/root-cause/action`, { method: 'POST' })
      setMsg('Improvement action added from the top-ranked cause.')
      onAction()
    } catch (e) { setMsg((e as Error).message) }
  }

  return (
    <div className="stack">
      <div className="filters" style={{ marginBottom: 0 }}>
        <div className="segmented" role="group" aria-label="CO to analyse">
          {cos.map((c) => (
            <button key={c.co_id} aria-pressed={active === c.co_id} onClick={() => setCo(c.co_id)}>
              <span className="id">CO{c.co_number}</span>{Number(c.final_level) < Number(c.target) ? ' · below' : ''}
            </button>
          ))}
        </div>
        <span className="spacer" />
        {canEdit && passing.length > 0 && <button className="btn primary" onClick={addAction}>Add action from top cause</button>}
      </div>
      {msg && <p className="note" role="status">{msg}</p>}

      <section className="panel" aria-labelledby="t-cause">
        <header>
          <h2 id="t-cause">Likely upstream causes of <span className="id">{offering.code} CO{chosen?.co_number}</span></h2>
          <span className="meta">final level {level(chosen?.final_level)} · target {level(chosen?.target)}</span>
        </header>
        <p className="small muted" style={{ marginBottom: 12 }}>
          Walks the declared CO dependencies up to three courses back and correlates the same students' scores.
          A candidate counts with at least {offering.config?.rc_min_n ?? 20} students and r ≥ {offering.config?.rc_min_r ?? '0.40'}.
          Correlation is evidence for review, not proof of cause.
        </p>
        {res.error ? <ErrorBox message={res.error} onRetry={res.reload} />
          : res.loading && !res.data ? <SkeletonRows rows={3} />
          : (res.data ?? []).length === 0 ? <Empty>No CO dependencies are declared for this CO, so there is nothing upstream to check.</Empty>
          : (
            <div className="table-wrap">
              <table>
                <thead><tr><th className="n">Rank</th><th>Upstream CO</th><th className="n">Depth</th><th className="n">Path strength</th><th className="n">r</th><th className="n">Students</th><th className="n">Its level</th><th>Verdict</th></tr></thead>
                <tbody>
                  {res.data!.map((r) => (
                    <tr key={r.up_co_id}>
                      <td className="n num">{r.likely_cause_rank ?? <span className="dash">—</span>}</td>
                      <td><span className="id">{r.up_course_code} CO{r.up_co_number}</span><span className="sub truncate">{r.up_statement}</span></td>
                      <td className="n num">{r.depth}</td>
                      <td className="n num">{Number(r.path_strength).toFixed(2)}</td>
                      <td className="n num">{r.correlation ?? '—'}</td>
                      <td className="n num">{r.n}</td>
                      <td className="n num">{level(r.up_final_level)}</td>
                      <td>{r.passes ? <Pill kind="warn">Likely cause</Pill> : <span className="muted small">{r.n < (offering.config?.rc_min_n ?? 20) ? 'Too few students' : 'Weak link'}</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
      </section>
    </div>
  )
}
