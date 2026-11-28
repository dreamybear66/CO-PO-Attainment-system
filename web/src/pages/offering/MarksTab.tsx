import { useRef, useState } from 'react'
import { api, ApiError, type RowError } from '../../api'
import { Empty, Pill } from '../../components/States'
import { COMPONENT, int, num } from '../../format'
import { ElMarks, NewEl } from './ElMarks'
import { OcrReview, type ScanResult } from './OcrReview'
import type { Assessment, OfferingDetail } from './types'

// One scanned PDF per sitting. A CIE paper has Part A (the quiz) and Part B (the test).
const SITTINGS = [
  { key: 'CIE1', label: 'CIE 1', fills: ['Quiz 1', 'CIE Test 1'] },
  { key: 'CIE2', label: 'CIE 2', fills: ['Quiz 2', 'CIE Test 2'] },
  { key: 'CIE3', label: 'CIE 3', fills: ['Quiz 3', 'CIE Test 3'] },
  { key: 'SEE', label: 'SEE', fills: ['SEE'] },
] as const

export function MarksTab({ offering, canEdit, onChange }: { offering: OfferingDetail; canEdit: boolean; onChange: () => void }) {
  const [errors, setErrors] = useState<{ name: string; rows: RowError[] } | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [review, setReview] = useState<ScanResult | null>(null)
  const [typing, setTyping] = useState<Assessment | null>(null)
  const [adding, setAdding] = useState(false)
  const open = offering.assessments.filter((a) => !a.locked)
  const weights = offering.config?.component_weights ?? {}
  const hasEl = offering.assessments.some((a) => a.type === 'EL')

  return (
    <div className="stack">
      {canEdit && (
        <section className="panel" aria-labelledby="t-scan">
          <header>
            <h2 id="t-scan">Scan answer sheets</h2>
          </header>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Sitting</th><th>Fills</th><th className="n">Action</th></tr></thead>
              <tbody>
                {SITTINGS.map((s) => (
                  <SittingRow key={s.key} sitting={s} offering={offering} onMessage={setMessage}
                              onReview={(r) => { setErrors(null); setTyping(null); setReview(r) }} />
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="panel" aria-labelledby="t-assess">
        <header>
          <h2 id="t-assess">Assessments</h2>
          <span className="meta">{open.length ? `${open.length} open` : offering.assessments.length ? 'All locked' : ''}</span>
        </header>
        {offering.assessments.length === 0 ? <Empty>No assessments yet.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Assessment</th><th className="n hide-phone">Questions</th><th className="n">Max</th><th className="n">Marks entered</th><th>Status</th>{canEdit && <th className="n">Actions</th>}</tr></thead>
              <tbody>
                {offering.assessments.map((a) => (
                  <AssessmentRow key={a.assessment_id} a={a} canEdit={canEdit} weight={weights[a.type]}
                                 onMessage={setMessage} onChange={onChange}
                                 onType={() => { setErrors(null); setReview(null); setTyping(typing?.assessment_id === a.assessment_id ? null : a) }} />
                ))}
              </tbody>
            </table>
          </div>
        )}
        {canEdit && !hasEl && !adding &&
          <div className="filters" style={{ marginTop: 12, marginBottom: 0 }}>
            <button className="btn small" onClick={() => setAdding(true)}>Add experiential learning</button>
          </div>}
        {message && <p className="small" role="status" style={{ marginTop: 12 }}>{message}</p>}
      </section>

      {adding && <NewEl offering={offering} onClose={() => setAdding(false)}
                        onCreated={(m) => { setAdding(false); setMessage(m); onChange() }} />}

      {review && (
        <OcrReview key={`${review.sitting}-${review.sheets.length}`} data={review} offering={offering}
                   onErrors={(rows) => setErrors(rows ? { name: review.label, rows } : null)}
                   onClose={() => setReview(null)}
                   onSaved={(m) => { setReview(null); setMessage(m); onChange() }} />
      )}

      {typing && (
        <ElMarks key={typing.assessment_id} a={typing}
                 onErrors={(rows) => setErrors(rows ? { name: typing.name, rows } : null)}
                 onClose={() => setTyping(null)}
                 onSaved={(m) => { setTyping(null); setMessage(m); onChange() }} />
      )}

      {errors && (
        <section className="panel" aria-labelledby="t-errors">
          <header><h2 id="t-errors">{errors.name}: {errors.rows.length} problem{errors.rows.length > 1 ? 's' : ''}</h2><span className="meta">Nothing was saved. Correct these and save again.</span></header>
          <div className="table-wrap">
            <table>
              <thead><tr><th className="n">Row or page</th><th>USN</th><th>Question</th><th>Problem</th></tr></thead>
              <tbody>
                {errors.rows.slice(0, 50).map((e, i) => (
                  <tr key={i}><td className="n num">{e.row ?? '—'}</td><td><span className="id">{e.usn ?? '—'}</span></td><td>{e.column ?? '—'}</td><td>{e.message}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}

function SittingRow({ sitting, offering, onMessage, onReview }: {
  sitting: (typeof SITTINGS)[number]; offering: OfferingDetail
  onMessage: (m: string | null) => void; onReview: (r: ScanResult) => void
}) {
  const pdf = useRef<HTMLInputElement>(null)
  const [reading, setReading] = useState(false)
  const targets = sitting.fills.map((name) => ({ name, a: offering.assessments.find((x) => x.name === name) }))
  const locked = targets.filter((t) => t.a?.locked).map((t) => t.name)

  async function read(f: File) {
    const form = new FormData()
    form.append('file', f)
    onMessage(null); setReading(true)
    try { onReview(await api<ScanResult>(`/api/offerings/${offering.offering_id}/scan?sitting=${sitting.key}`, { form })) }
    catch (e) { onMessage((e as ApiError).message) }
    finally { setReading(false); if (pdf.current) pdf.current.value = '' }
  }

  return (
    <tr>
      <td>{sitting.label}</td>
      <td>
        {targets.map((t, i) => (
          <span key={t.name} style={{ marginRight: 12, whiteSpace: 'nowrap' }}>
            {sitting.key !== 'SEE' && <span className="muted">{i === 0 ? 'Part A' : 'Part B'} → </span>}{t.name}{' '}
            {!t.a ? <Pill>Not yet</Pill> : t.a.locked ? <Pill>Locked</Pill>
              : t.a.marks_entered > 0 ? <Pill kind="pos">{int(t.a.marks_entered)} marks</Pill> : <Pill kind="warn">No marks</Pill>}
          </span>
        ))}
      </td>
      <td className="n">
        <button className="btn small" disabled={reading || locked.length > 0} onClick={() => pdf.current?.click()}
                title={locked.length ? `${locked.join(' and ')} locked; request an unlock first` : undefined}>
          {reading ? 'Reading…' : 'Scan answer sheets'}
        </button>
        <input ref={pdf} type="file" accept=".pdf,application/pdf" hidden aria-label={`Scanned answer sheets for ${sitting.label}`}
               onChange={(e) => e.target.files?.[0] && read(e.target.files[0])} />
      </td>
    </tr>
  )
}

function AssessmentRow({ a, canEdit, weight, onMessage, onChange, onType }: {
  a: Assessment; canEdit: boolean; weight?: number
  onMessage: (m: string | null) => void; onChange: () => void; onType: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [asking, setAsking] = useState(false)
  const [reason, setReason] = useState('')
  const complete = a.marks_entered === a.marks_expected && a.marks_expected > 0

  async function run(fn: () => Promise<unknown>, ok?: string) {
    setBusy(true); onMessage(null)
    try { await fn(); if (ok) onMessage(ok); onChange() }
    catch (e) { onMessage((e as ApiError).message) }
    finally { setBusy(false) }
  }

  const status = a.locked
    ? a.unlock_status === 'pending' ? <Pill kind="warn">Unlock requested</Pill>
      : a.unlock_status === 'approved' ? <Pill kind="warn">Unlock approved</Pill>
      : <Pill>Locked</Pill>
    : complete ? <Pill kind="pos">Ready to lock</Pill> : <Pill kind="warn">Open</Pill>

  return (
    <>
      <tr>
        <td>{a.name}<span className="sub">{COMPONENT[a.type]}{a.cie_no ? ` · CIE ${a.cie_no}` : ''}{a.type === 'EL' ? ' · one mark, final total only · typed'
          : `${weight ? ` · ${weight}% of the CO score` : ''} · scanned`}</span></td>
        <td className="n num hide-phone">{a.type === 'EL' ? '—' : a.questions}</td>
        <td className="n num">{int(num(a.max_marks))}</td>
        <td className="n num">{int(a.marks_entered)}<span className="sub">of {int(a.marks_expected)}</span></td>
        <td>{status}</td>
        {canEdit && (
          <td className="n">
            <div style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              {!a.locked && <>
                {a.type === 'EL' && <button className="btn small" disabled={busy || a.questions === 0} onClick={onType}>Type marks</button>}
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
