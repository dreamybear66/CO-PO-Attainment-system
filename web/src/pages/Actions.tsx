import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import { Empty, ErrorBox, Pill, SkeletonRows } from '../components/States'
import { int, level, signed } from '../format'
import { useApi } from '../hooks'

type Action = {
  action_id: number; code: string; co_number: number; academic_year: string; section: string; offering_id: number
  description: string; status: string; source: string; level_before: string | null; level_after: string | null
  change: string | null; follow_up_year: string | null
}
const STATUS = { open: 'Open', in_progress: 'In progress', done: 'Done' } as const
type Status = keyof typeof STATUS

export function Actions() {
  const { user } = useAuth()
  const [filter, setFilter] = useState<Status | 'all'>('open')
  const list = useApi<Action[]>(filter === 'all' ? '/api/actions' : `/api/actions?status=${filter}`)
  const canEdit = user?.role === 'admin' || user?.role === 'faculty'
  const rows = list.data ?? []
  const followed = rows.filter((r) => r.level_after !== null)
  const improved = followed.filter((r) => Number(r.change) > 0).length

  const [failed, setFailed] = useState<string | null>(null)
  async function setStatus(id: number, status: Status) {
    setFailed(null)
    try {
      await api(`/api/actions/${id}`, { method: 'PATCH', body: { status } })
    } catch (e) {
      setFailed(`Couldn't change the status. ${(e as Error).message}`)
    } finally {
      list.reload()
    }
  }

  return (
    <>
      <div className="title-row">
        <div>
          <h1>Improvement actions</h1>
          <p className="sub">One action for every CO that missed its target. When the course runs again, its new level shows whether the action helped
            {followed.length ? `: ${improved} of ${followed.length} followed-up COs in this view improved.` : '.'}</p>
        </div>
      </div>
      {failed && <p className="note" role="alert">{failed}</p>}
      <div className="filters">
        <div className="segmented" role="group" aria-label="Status">
          {(['open', 'in_progress', 'done', 'all'] as const).map((s) => (
            <button key={s} aria-pressed={filter === s} onClick={() => setFilter(s)}>{s === 'all' ? 'All' : STATUS[s]}</button>
          ))}
        </div>
        <span className="spacer" /><span className="stamp num">{int(rows.length)} actions</span>
      </div>
      <section className="panel" aria-label="Actions">
        {list.error ? <ErrorBox message={list.error} onRetry={list.reload} />
          : !list.data ? <SkeletonRows rows={8} />
          : rows.length === 0 ? <Empty>No actions in this view.</Empty>
          : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>CO</th><th>Action</th><th className="n">Level then</th><th className="n">Next run</th><th className="n">Change</th><th>Status</th></tr></thead>
                <tbody>
                  {rows.slice(0, 200).map((a) => (
                    <tr key={a.action_id}>
                      <td><Link to={`/offerings/${a.offering_id}`}><span className="id">{a.code} CO{a.co_number}</span></Link><span className="sub">{a.academic_year} · {a.section}</span></td>
                      <td className="truncate" title={a.description}>{a.description}<span className="sub">{a.source === 'root_cause' ? 'From root-cause analysis' : 'Added when computed'}</span></td>
                      <td className="n num">{level(a.level_before)}</td>
                      <td className="n num">{a.level_after ? level(a.level_after) : <span className="dash">—</span>}<span className="sub">{a.follow_up_year ?? 'not run yet'}</span></td>
                      <td className="n">{a.change === null ? <span className="dash">—</span> : <Pill kind={Number(a.change) > 0 ? 'pos' : Number(a.change) < 0 ? 'neg' : 'neutral'}>{signed(a.change)}</Pill>}</td>
                      <td>
                        {canEdit ? (
                          <select className="input" aria-label={`Status of ${a.code} CO${a.co_number}`} value={a.status} onChange={(e) => setStatus(a.action_id, e.target.value as Status)}>
                            {(Object.keys(STATUS) as Status[]).map((s) => <option key={s} value={s}>{STATUS[s]}</option>)}
                          </select>
                        ) : STATUS[a.status as Status]}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {rows.length > 200 && <p className="small muted" style={{ marginTop: 12 }}>Showing the first 200 of {int(rows.length)}; filter by status to narrow.</p>}
            </div>
          )}
      </section>
    </>
  )
}
