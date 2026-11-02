import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import { Empty, ErrorBox, Pill, SkeletonRows } from '../components/States'
import { day, int, term } from '../format'
import { UNLOCKS_CHANGED, useApi } from '../hooks'

export type Offering = {
  offering_id: number; course_id: number; code: string; title: string; semester: number
  academic_year: string; term: string; section: string; faculty: string
  assessments: number; locked: number; computed_at: string | null; cos_below_target: number
}
type Unlock = { request_id: number; assessment: string; code: string; academic_year: string; section: string; reason: string; requested_at: string; offering_id: number }
type Action = { action_id: number; code: string; co_number: number; academic_year: string; section: string; description: string; offering_id: number; status: string }

const VIEWS = { all: 'All', open: 'Marks still open', ready: 'Ready to compute', done: 'Computed' } as const
type View = keyof typeof VIEWS

const state = (o: Offering): View =>
  o.computed_at ? 'done' : o.assessments > 0 && o.locked === o.assessments ? 'ready' : 'open'

export function Offerings() {
  const { user } = useAuth()
  const nav = useNavigate()
  const list = useApi<Offering[]>('/api/offerings')
  const years = useMemo(() => [...new Set((list.data ?? []).map((o) => o.academic_year))], [list.data])
  const [year, setYear] = useState<string | null>(null)
  const [view, setView] = useState<View>('all')
  const activeYear = year ?? years[0] ?? null

  const inYear = (list.data ?? []).filter((o) => o.academic_year === activeYear)
  const rows = inYear.filter((o) => view === 'all' || state(o) === view)
  const totals = {
    offerings: inYear.length,
    assessments: inYear.reduce((s, o) => s + o.assessments, 0),
    locked: inYear.reduce((s, o) => s + o.locked, 0),
    computed: inYear.filter((o) => o.computed_at).length,
    below: inYear.reduce((s, o) => s + o.cos_below_target, 0),
  }
  const open = totals.assessments - totals.locked

  return (
    <>
      <div className="title-row">
        <div>
          <h1>Offerings</h1>
          <p className="sub">
            {activeYear ? <>{activeYear}: {open > 0 ? `${int(open)} assessments are still open for marks` : 'every assessment is locked'}
              {totals.below > 0 ? `, and ${int(totals.below)} COs are below target across ${int(totals.computed)} computed offerings.` : '.'}</> : 'No offerings yet.'}
          </p>
        </div>
      </div>

      <div className="filters">
        <label className="visually-hidden" htmlFor="year">Academic year</label>
        <select id="year" className="input" value={activeYear ?? ''} onChange={(e) => setYear(e.target.value)}>
          {years.map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
        <div className="segmented" role="group" aria-label="Show">
          {(Object.keys(VIEWS) as View[]).map((v) => (
            <button key={v} aria-pressed={view === v} onClick={() => setView(v)}>{VIEWS[v]}</button>
          ))}
        </div>
        <span className="spacer" />
        <span className="stamp">{user?.role === 'faculty' ? 'Your offerings' : 'All sections of the programme'}</span>
      </div>

      <div className="kpis" aria-label={`Totals for ${activeYear ?? ''}`}>
        <div className="kpi"><div className="kpi-label">Offerings</div><div className="kpi-value num">{int(totals.offerings)}</div><div className="delta">course sections in {activeYear}</div></div>
        <div className="kpi"><div className="kpi-label">Assessments locked</div><div className="kpi-value num">{int(totals.locked)}<small>of {int(totals.assessments)}</small></div><div className="delta">locked marks can no longer change</div></div>
        <div className="kpi"><div className="kpi-label">Attainment computed</div><div className="kpi-value num">{int(totals.computed)}<small>of {int(totals.offerings)}</small></div><div className="delta">offerings with CO and PO results</div></div>
        <div className="kpi"><div className="kpi-label">COs below target</div>
          {totals.computed
            ? <><div className={`kpi-value num ${totals.below ? 'below' : ''}`}>{int(totals.below)}</div><div className="delta">each has an improvement action</div></>
            : <><div className="kpi-value dash">—</div><div className="delta">shown once attainment is computed</div></>}
        </div>
      </div>

      <div className="with-rail">
        <section className="panel" aria-labelledby="t-list">
          <header><h2 id="t-list">{VIEWS[view]} · {activeYear}</h2><span className="meta num">{int(rows.length)} shown</span></header>
          {list.error ? <ErrorBox message={`Couldn't load offerings. ${list.error}`} onRetry={list.reload} />
            : list.loading && !list.data ? <SkeletonRows rows={6} />
            : rows.length === 0 ? <Empty>No offerings match this view.</Empty>
            : (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Course</th><th className="hide-phone">Section</th><th className="hide-phone">Faculty</th><th className="n">Locked</th><th className="n hide-phone">Computed</th><th className="n">Below target</th></tr></thead>
                  <tbody>
                    {rows.map((o) => (
                      <tr key={o.offering_id} className="link" onClick={() => nav(`/offerings/${o.offering_id}`)}>
                        <td><Link to={`/offerings/${o.offering_id}`}><span className="id">{o.code}</span> {o.title}</Link>
                          <span className="sub">Semester {o.semester} · {term(o.term).toLowerCase()}<span className="show-phone"> · section {o.section}</span></span></td>
                        <td className="hide-phone">{o.section}</td>
                        <td className="hide-phone truncate">{o.faculty}</td>
                        <td className="n num">{o.locked} of {o.assessments}</td>
                        <td className="n hide-phone">{o.computed_at ? day(o.computed_at) : <span className="dash">Not yet</span>}</td>
                        <td className="n">{o.computed_at ? (o.cos_below_target ? <Pill kind="neg">{o.cos_below_target} CO{o.cos_below_target > 1 ? 's' : ''}</Pill> : <span className="num">0</span>) : <span className="dash">—</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
        </section>
        <aside className="rail">{user?.role === 'admin' ? <UnlockQueue /> : <OpenActions />}</aside>
      </div>
    </>
  )
}

function UnlockQueue() {
  const q = useApi<Unlock[]>('/api/unlock-requests')
  const [busy, setBusy] = useState<number | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  async function decide(id: number, approve: boolean) {
    setBusy(id)
    setFailed(null)
    try {
      await api(`/api/unlock-requests/${id}/decision`, { body: { approve } })
    } catch (e) {
      setFailed((e as Error).message)        // e.g. already decided by someone else
    } finally {
      setBusy(null)
      q.reload()                             // the list is current either way
      window.dispatchEvent(new Event(UNLOCKS_CHANGED))
    }
  }
  return (
    <>
      <h2>Unlock requests</h2>
      {failed && <p className="note" role="alert">{failed}</p>}
      <div className="panel">
        {q.error ? <ErrorBox message={q.error} onRetry={q.reload} />
          : !q.data ? <SkeletonRows rows={3} />
          : q.data.length === 0 ? <Empty>No requests waiting. Faculty ask here when locked marks need a correction.</Empty>
          : (
            <div className="rows">
              {q.data.map((r) => (
                <div className="row" key={r.request_id} style={{ alignItems: 'flex-start', flexDirection: 'column', gap: 6 }}>
                  <div><span className="id">{r.code}</span> {r.assessment} · {r.academic_year} {r.section}</div>
                  <div className="small muted">“{r.reason}” · {day(r.requested_at)}</div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button className="btn small primary" disabled={busy === r.request_id} onClick={() => decide(r.request_id, true)}>Approve</button>
                    <button className="btn small" disabled={busy === r.request_id} onClick={() => decide(r.request_id, false)}>Reject</button>
                  </div>
                </div>
              ))}
            </div>
          )}
      </div>
    </>
  )
}

function OpenActions() {
  const a = useApi<Action[]>('/api/actions?status=open')
  const shown = (a.data ?? []).slice(0, 5)
  return (
    <>
      <h2>Open improvement actions</h2>
      <div className="panel">
        {a.error ? <ErrorBox message={a.error} onRetry={a.reload} />
          : !a.data ? <SkeletonRows rows={4} />
          : shown.length === 0 ? <Empty>No open actions.</Empty>
          : (
            <div className="rows">
              {shown.map((x) => (
                <Link className="row" key={x.action_id} to={`/offerings/${x.offering_id}`} style={{ alignItems: 'flex-start', flexDirection: 'column', gap: 2 }}>
                  <div><span className="id">{x.code} CO{x.co_number}</span> · {x.academic_year} {x.section}</div>
                  <div className="small muted truncate" style={{ maxWidth: '100%' }}>{x.description}</div>
                </Link>
              ))}
            </div>
          )}
        {a.data && a.data.length > 5 && <div style={{ marginTop: 12 }}><Link className="card-link" to="/actions">View all {int(a.data.length)}</Link></div>}
      </div>
    </>
  )
}
