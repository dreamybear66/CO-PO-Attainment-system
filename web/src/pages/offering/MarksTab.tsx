import { useRef, useState } from 'react'
import { api, ApiError, download, type RowError } from '../../api'
import { Empty, Pill } from '../../components/States'
import { COMPONENT, int, num } from '../../format'
import type { Assessment, OfferingDetail } from './types'

export function MarksTab({ offering, canEdit, onChange }: { offering: OfferingDetail; canEdit: boolean; onChange: () => void }) {
  const [errors, setErrors] = useState<{ name: string; rows: RowError[] } | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const open = offering.assessments.filter((a) => !a.locked)
  const weights = offering.config?.component_weights ?? {}

  return (
    <div className="stack">
      <section className="panel" aria-labelledby="t-assess">
        <header>
          <h2 id="t-assess">Assessments</h2>
          <span className="meta">{open.length ? `${open.length} open · upload a CSV per assessment, then lock it` : 'All locked'}</span>
        </header>
        {offering.assessments.length === 0 ? <Empty>No assessments defined for this offering yet.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Assessment</th><th className="n hide-phone">Questions</th><th className="n">Max</th><th className="n">Marks entered</th><th>Status</th>{canEdit && <th className="n">Actions</th>}</tr></thead>
              <tbody>
                {offering.assessments.map((a) => (
                  <AssessmentRow key={a.assessment_id} a={a} canEdit={canEdit} weight={weights[a.type]}
                                 onErrors={(rows) => setErrors(rows ? { name: a.name, rows } : null)}
                                 onMessage={setMessage} onChange={onChange} />
                ))}
              </tbody>
            </table>
          </div>
        )}
        {message && <p className="small" role="status" style={{ marginTop: 12 }}>{message}</p>}
      </section>

      {errors && (
        <section className="panel" aria-labelledby="t-errors">
          <header><h2 id="t-errors">{errors.name}: {errors.rows.length} problem{errors.rows.length > 1 ? 's' : ''} in the file</h2><span className="meta">Nothing was saved. Fix the rows and upload again.</span></header>
          <div className="table-wrap">
            <table>
              <thead><tr><th className="n">Row</th><th>USN</th><th>Column</th><th>Problem</th></tr></thead>
              <tbody>
                {errors.rows.slice(0, 50).map((e, i) => (
                  <tr key={i}><td className="n num">{e.row}</td><td><span className="id">{e.usn ?? '—'}</span></td><td>{e.column ?? '—'}</td><td>{e.message}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      <p className="small muted">
        CSV columns: <span className="id">usn</span>, then one column per question (<span className="id">Q1</span>, <span className="id">Q2</span>, …).
        Enter <span className="id">AB</span> for an absent student; an absence counts as zero. Download the template for the exact columns.
      </p>
    </div>
  )
}

function AssessmentRow({ a, canEdit, weight, onErrors, onMessage, onChange }: {
  a: Assessment; canEdit: boolean; weight?: number
  onErrors: (rows: RowError[] | null) => void; onMessage: (m: string | null) => void; onChange: () => void
}) {
  const file = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [asking, setAsking] = useState(false)
  const [reason, setReason] = useState('')
  const complete = a.marks_entered === a.marks_expected && a.marks_expected > 0

  async function run(fn: () => Promise<unknown>, ok?: string) {
    setBusy(true); onMessage(null)
    try { await fn(); if (ok) onMessage(ok); onChange() }
    catch (e) { const err = e as ApiError; if (err.errors) onErrors(err.errors); onMessage(err.message) }
    finally { setBusy(false) }
  }
  async function upload(f: File) {
    const form = new FormData()
    form.append('file', f)
    onErrors(null)
    await run(async () => {
      const r = await api<{ saved: number }>(`/api/assessments/${a.assessment_id}/marks`, { form })
      onMessage(`${a.name}: ${int(r.saved)} marks saved.`)
    })
    if (file.current) file.current.value = ''
  }

  const status = a.locked
    ? a.unlock_status === 'pending' ? <Pill kind="warn">Unlock requested</Pill>
      : a.unlock_status === 'approved' ? <Pill kind="warn">Unlock approved</Pill>
      : <Pill>Locked</Pill>
    : complete ? <Pill kind="pos">Ready to lock</Pill> : <Pill kind="warn">Open</Pill>

  return (
    <>
      <tr>
        <td>{a.name}<span className="sub">{COMPONENT[a.type]}{weight ? ` · ${weight}% of the CO score` : ''}</span></td>
        <td className="n num hide-phone">{a.questions}</td>
        <td className="n num">{int(num(a.max_marks))}</td>
        <td className="n num">{int(a.marks_entered)}<span className="sub">of {int(a.marks_expected)}</span></td>
        <td>{status}</td>
        {canEdit && (
          <td className="n">
            <div style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              {!a.locked && <>
                <button className="btn small ghost" disabled={busy} onClick={() => download(`/api/assessments/${a.assessment_id}/template`, `${a.name}.csv`)}>Template</button>
                <button className="btn small" disabled={busy} onClick={() => file.current?.click()}>Upload CSV</button>
                <input ref={file} type="file" accept=".csv,text/csv" hidden aria-label={`Upload marks for ${a.name}`}
                       onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
                <button className="btn small primary" disabled={busy || !complete} title={complete ? undefined : 'Every student needs a mark or AB first'}
                        onClick={() => run(() => api(`/api/assessments/${a.assessment_id}/lock`, { method: 'POST' }), `${a.name} locked.`)}>Lock</button>
              </>}
              {a.locked && a.unlock_status === 'approved' &&
                <button className="btn small" disabled={busy} onClick={() => run(() => api(`/api/assessments/${a.assessment_id}/unlock`, { method: 'POST' }), `${a.name} unlocked for correction.`)}>Unlock</button>}
              {a.locked && !a.unlock_status?.match(/pending|approved/) &&
                <button className="btn small ghost" disabled={busy} onClick={() => setAsking((x) => !x)}>Request unlock</button>}
            </div>
          </td>
        )}
      </tr>
      {asking && (
        <tr>
          <td colSpan={6}>
            <form style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}
                  onSubmit={(e) => { e.preventDefault(); run(() => api(`/api/assessments/${a.assessment_id}/unlock-requests`, { body: { reason } }), 'Request sent to the HoD.').then(() => setAsking(false)) }}>
              <label htmlFor={`r${a.assessment_id}`}>Why do the marks need to change?</label>
              <input id={`r${a.assessment_id}`} className="input" style={{ flex: 1, minWidth: 220 }} value={reason} minLength={5} required
                     onChange={(e) => setReason(e.target.value)} placeholder="e.g. Q3 marks of two students were swapped" />
              <button className="btn small primary" disabled={busy}>Send to HoD</button>
            </form>
          </td>
        </tr>
      )}
    </>
  )
}
