import { Fragment, useState } from 'react'
import { api, ApiError } from '../../api'
import { Empty, ErrorBox, Pill, SkeletonRows } from '../../components/States'
import { int, pct, when } from '../../format'
import { useApi } from '../../hooks'
import { FinalMarks, WeakStudents } from './StudentResults'
import type { OfferingDetail } from './types'

type Reason = { feature: string; label: string; value: number; typical: number; effect: number }
type Flag = { usn: string; name: string; co_id: number; probability: string; reasons: Reason[] }
type StudentsData = {
  finished: boolean; target_pct: number | null; enrolled: number
  weak: { co_id: number; co_number: number; statement: string; scored: number; below: { usn: string; name: string; pct: string }[] }[]
  early_warning: null | {
    stage: { type: string; rank: number; name: string }[]; flag_prob: string; computed_at: string; flagged: Flag[]
    model: { training_offerings: number; training_rows: number; training_auc: number }
  }
}

/** Students who need help: early warning during the term, who is below target in each CO, why each
 *  weak student is weak, and everyone's final marks. */
export function StudentsTab({ offering, canEdit }: { offering: OfferingDetail; canEdit: boolean }) {
  const id = offering.offering_id
  const data = useApi<StudentsData>(`/api/offerings/${id}/students`)
  const [co, setCo] = useState<number | 'all'>('all')
  const [open, setOpen] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  if (data.error) return <ErrorBox message={data.error} onRetry={data.reload} />
  if (!data.data) return <SkeletonRows rows={4} />
  const d = data.data
  const ew = d.early_warning
  const coNumber = new Map(d.weak.map((w) => [w.co_id, w.co_number]))
  const flags = (ew?.flagged ?? []).filter((f) => co === 'all' || f.co_id === co)

  async function runNow() {
    setBusy(true); setMsg(null)
    try {
      const r = await api<{ flagged: number; predictions: number }>(`/api/offerings/${id}/early-warning`, { method: 'POST' })
      setMsg(`${int(r.flagged)} of ${int(r.predictions)} student-CO pairs flagged.`)
      data.reload()
    } catch (e) { setMsg((e as ApiError).message) } finally { setBusy(false) }
  }
  async function copy(usns: string[]) {
    try { await navigator.clipboard.writeText(usns.join('\n')); setMsg(`${usns.length} USNs copied.`) }
    catch { setMsg(usns.join(', ')) }
  }

  return (
    <div className="stack">
      <section className="panel" aria-labelledby="t-ew">
        <header>
          <h2 id="t-ew">Early warning</h2>
          <span className="meta">
            {ew ? `After ${ew.stage.map((s) => s.name).join(', ')} · ${when(ew.computed_at)}` : d.finished ? 'The term is over' : 'Runs when a CIE test or quiz is locked'}
          </span>
        </header>
        <p className="small muted" style={{ marginBottom: 12 }}>
          The chance each student ends the term below the CO target, learned from earlier offerings of this course at the same point
          of the term. A student is flagged at {ew ? pct(Number(ew.flag_prob) * 100) : 'the rule version’s cut-off'} or more.
          It is advice for early help; it never changes the official results.
        </p>
        {ew && <p className="small" style={{ marginBottom: 12 }}>Learned from {int(ew.model.training_offerings)} earlier offerings ({int(ew.model.training_rows)} student-CO results).</p>}
        <div className="filters">
          <label className="small" htmlFor="ew-co">CO</label>
          <select id="ew-co" className="input" style={{ width: 'auto' }} value={co} onChange={(e) => setCo(e.target.value === 'all' ? 'all' : Number(e.target.value))}>
            <option value="all">All COs</option>
            {d.weak.map((w) => <option key={w.co_id} value={w.co_id}>CO{w.co_number}</option>)}
          </select>
          <span className="spacer" />
          {canEdit && !d.finished && <button className="btn small" disabled={busy} onClick={runNow}>{busy ? 'Running…' : ew ? 'Run again' : 'Run now'}</button>}
          {ew && flags.length > 0 && <button className="btn small ghost" onClick={() => copy([...new Set(flags.map((f) => f.usn))])}>Copy USNs</button>}
        </div>
        {!ew ? <Empty>{d.finished ? 'The term’s results are in; see the list below.' : 'No early warning yet. Lock CIE Test 1 (or run it now) once its marks are in.'}</Empty>
          : flags.length === 0 ? <Empty>No student is flagged{co === 'all' ? '' : ` for CO${coNumber.get(co as number)}`}.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Student</th><th>CO</th><th className="n">Chance of missing</th><th>Why</th></tr></thead>
              <tbody>
                {flags.map((f) => (
                  <tr key={`${f.usn}-${f.co_id}`}>
                    <td><span className="id">{f.usn}</span><span className="sub">{f.name}</span></td>
                    <td><span className="id">CO{coNumber.get(f.co_id)}</span></td>
                    <td className="n"><Pill kind={Number(f.probability) >= 0.75 ? 'neg' : 'warn'}>{pct(Number(f.probability) * 100)}</Pill></td>
                    <td className="small">{f.reasons.length ? f.reasons.map((r) => `${r.label} ${pct(r.value)} (typical ${pct(r.typical)})`).join('; ') : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {msg && <p className="small" role="status" style={{ marginTop: 12 }}>{msg}</p>}
      </section>

      <section className="panel" aria-labelledby="t-weak">
        <header>
          <h2 id="t-weak">Below target{d.finished ? '' : ' so far'}</h2>
          <span className="meta">CO score under {d.target_pct === null ? 'the target' : pct(d.target_pct)}{d.finished ? '' : ', from the marks entered so far'}</span>
        </header>
        <div className="table-wrap">
          <table>
            <thead><tr><th>CO</th><th className="n">Below target</th><th className="n">Share</th><th className="n">Students</th></tr></thead>
            <tbody>
              {d.weak.map((w) => (
                <Fragment key={w.co_id}>
                  <tr>
                    <td><span className="id">CO{w.co_number}</span><span className="sub">{w.statement}</span></td>
                    {w.scored === 0 ? <td className="n small muted" colSpan={2}>Not assessed yet</td> : <>
                      <td className="n num">{int(w.below.length)}<span className="sub">of {int(w.scored)}</span></td>
                      <td className="n num">{pct((100 * w.below.length) / w.scored)}</td>
                    </>}
                    <td className="n">
                      {w.below.length > 0 && <>
                        <button className="btn small ghost" aria-expanded={open === w.co_id} onClick={() => setOpen(open === w.co_id ? null : w.co_id)}>{open === w.co_id ? 'Hide' : 'Show'}</button>
                        <button className="btn small ghost" onClick={() => copy(w.below.map((s) => s.usn))}>Copy USNs</button>
                      </>}
                    </td>
                  </tr>
                  {open === w.co_id && (
                    <tr>
                      <td colSpan={4}>
                        <div className="weak-list">
                          {w.below.map((s) => <span key={s.usn}><span className="id">{s.usn}</span> {s.name} <span className="muted num">{pct(Number(s.pct))}</span></span>)}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <WeakStudents offeringId={id} onCopy={copy} />
      <FinalMarks offeringId={id} />
    </div>
  )
}
