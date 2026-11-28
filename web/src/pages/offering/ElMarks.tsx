import { useEffect, useState } from 'react'
import { api, ApiError, type RowError } from '../../api'
import { ErrorBox, SkeletonRows } from '../../components/States'
import { useApi } from '../../hooks'
import { int } from '../../format'
import type { Assessment, OfferingDetail } from './types'

type Cell = number | 'AB' | null
type MarksSheet = {
  assessment_id: number; name: string; type: string; locked: boolean
  questions: { q_no: string; max_marks: number }[]
  students: { usn: string; name: string; marks: Record<string, Cell> }[]
}

const isAbsent = (t: string) => ['AB', 'A', 'ABSENT'].includes(t.trim().toUpperCase())

/** Experiential learning is one final mark per student (stored as its single question Q1). Empty
 *  boxes are left as they are; everything else is saved together or not at all. */
export function ElMarks({ a, onSaved, onClose, onErrors }: {
  a: Assessment; onSaved: (message: string) => void; onClose: () => void; onErrors: (rows: RowError[] | null) => void
}) {
  const sheet = useApi<MarksSheet>(`/api/assessments/${a.assessment_id}/marks`)
  const [text, setText] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const q = sheet.data?.questions[0]

  useEffect(() => {
    if (!sheet.data || !q) return
    setText(Object.fromEntries(sheet.data.students.map((s) => [s.usn, s.marks[q.q_no] === null ? '' : String(s.marks[q.q_no])])))
  }, [sheet.data, q])

  if (sheet.error) return <section className="panel"><ErrorBox message={sheet.error} onRetry={sheet.reload} /></section>
  if (!sheet.data || !q) return <section className="panel"><SkeletonRows rows={6} /></section>
  const { students } = sheet.data
  const max = q.max_marks

  const problem = (t: string) => {
    if (t.trim() === '' || isAbsent(t)) return null
    const v = Number(t)
    return Number.isFinite(v) && v >= 0 && v <= max ? null : `0 to ${max} or AB`
  }
  const bad = students.filter((s) => problem(text[s.usn] ?? '')).map((s) => s.usn)
  const filled = students.filter((s) => (text[s.usn] ?? '').trim() !== '').length

  async function save() {
    setBusy(true); setError(null); onErrors(null)
    const rows = students.map((s) => ({ usn: s.usn, t: (text[s.usn] ?? '').trim() })).filter((r) => r.t !== '')
      .map((r) => ({ usn: r.usn, marks: { [q!.q_no]: isAbsent(r.t) ? 'AB' : Number(r.t) } }))
    try {
      const r = await api<{ saved: number }>(`/api/assessments/${a.assessment_id}/marks`, { method: 'PUT', body: rows })
      onSaved(`${a.name}: ${int(r.saved)} marks saved.`)
    } catch (e) {
      const err = e as ApiError
      if (err.errors) onErrors(err.errors)
      setError(err.message)
    } finally { setBusy(false) }
  }

  return (
    <section className="panel ocr" aria-labelledby="t-el">
      <header>
        <h2 id="t-el">Type marks: {a.name}</h2>
        <span className="meta">Out of {max} · {int(filled)} of {int(students.length)} filled · <span className="id">AB</span> = absent</span>
      </header>
      <div className="table-wrap">
        <table>
          <thead><tr><th>USN</th><th className="hide-phone">Name</th><th className="n">Mark<span className="sub">of {max}</span></th></tr></thead>
          <tbody>
            {students.map((s) => {
              const t = text[s.usn] ?? ''
              const p = problem(t)
              return (
                <tr key={s.usn}>
                  <td><span className="id">{s.usn}</span></td>
                  <td className="hide-phone small">{s.name}</td>
                  <td className={`n ${p ? 'ocr-flag' : ''}`}>
                    <input className="input ocr-num" inputMode="decimal" value={t} aria-label={`EL mark of ${s.usn}`} disabled={a.locked}
                           onChange={(e) => setText((all) => ({ ...all, [s.usn]: e.target.value }))} />
                    {p && <span className="sub">{p}</span>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {bad.length > 0 && <div className="note" role="status" style={{ marginTop: 12 }}>{bad.length} value{bad.length > 1 ? 's are' : ' is'} out of range: {bad.slice(0, 6).join(', ')}{bad.length > 6 ? '…' : ''}</div>}
      {error && <div className="error-box" role="alert">{error}</div>}
      <div className="filters" style={{ marginTop: 16, marginBottom: 0 }}>
        <span className="spacer" />
        <button className="btn ghost" disabled={busy} onClick={onClose}>Close</button>
        <button className="btn primary" disabled={busy || bad.length > 0 || a.locked || filled === 0} onClick={save}>{busy ? 'Saving…' : 'Save marks'}</button>
      </div>
    </section>
  )
}

/** Add experiential learning: only its maximum (e.g. 40). Each student then gets one mark. */
export function NewEl({ offering, onCreated, onClose }: { offering: OfferingDetail; onCreated: (message: string) => void; onClose: () => void }) {
  const [max, setMax] = useState('40')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const value = Number(max)
  const ok = Number.isInteger(value) && value >= 1 && value <= 999

  async function create() {
    setBusy(true); setError(null)
    try {
      await api(`/api/offerings/${offering.offering_id}/assessments`, { body: { type: 'EL', max_marks: value } })
      onCreated(`Experiential learning added, out of ${value}. Type each student's mark next.`)
    } catch (e) { setError((e as ApiError).message) } finally { setBusy(false) }
  }

  return (
    <section className="panel ocr" aria-labelledby="t-newel">
      <header><h2 id="t-newel">Add experiential learning</h2></header>
      <form className="filters" style={{ marginBottom: 0 }} onSubmit={(e) => { e.preventDefault(); if (ok) create() }}>
        <label htmlFor="el-max">Maximum marks</label>
        <input id="el-max" className="input ocr-num" type="number" min={1} max={999} value={max} onChange={(e) => setMax(e.target.value)} />
        {!ok && <span className="small below">1 to 999</span>}
        <span className="spacer" />
        <button type="button" className="btn ghost" disabled={busy} onClick={onClose}>Cancel</button>
        <button className="btn primary" disabled={busy || !ok}>{busy ? 'Adding…' : 'Add'}</button>
      </form>
      {error && <div className="error-box" role="alert">{error}</div>}
    </section>
  )
}
