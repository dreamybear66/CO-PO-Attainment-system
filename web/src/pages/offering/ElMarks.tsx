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

/** Typed marks for an experiential-learning assessment: one row per student, one box per question.
 *  Empty boxes are left as they are; everything else is saved together or not at all. */
export function ElMarks({ a, onSaved, onClose, onErrors }: {
  a: Assessment; onSaved: (message: string) => void; onClose: () => void; onErrors: (rows: RowError[] | null) => void
}) {
  const sheet = useApi<MarksSheet>(`/api/assessments/${a.assessment_id}/marks`)
  const [text, setText] = useState<Record<string, Record<string, string>>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!sheet.data) return
    setText(Object.fromEntries(sheet.data.students.map((s) => [s.usn, Object.fromEntries(
      sheet.data!.questions.map((q) => [q.q_no, s.marks[q.q_no] === null ? '' : String(s.marks[q.q_no])]))])))
  }, [sheet.data])

  if (sheet.error) return <section className="panel"><ErrorBox message={sheet.error} onRetry={sheet.reload} /></section>
  if (!sheet.data) return <section className="panel"><SkeletonRows rows={6} /></section>
  const { questions, students } = sheet.data

  const problem = (q: { max_marks: number }, t: string) => {
    if (t.trim() === '' || isAbsent(t)) return null
    const v = Number(t)
    return Number.isFinite(v) && v >= 0 && v <= q.max_marks ? null : `0 to ${q.max_marks} or AB`
  }
  const bad = students.flatMap((s) => questions.filter((q) => problem(q, text[s.usn]?.[q.q_no] ?? '')).map((q) => `${s.usn} ${q.q_no}`))
  const filled = students.reduce((n, s) => n + questions.filter((q) => (text[s.usn]?.[q.q_no] ?? '').trim() !== '').length, 0)

  async function save() {
    setBusy(true); setError(null); onErrors(null)
    const rows = students.map((s) => ({
      usn: s.usn,
      marks: Object.fromEntries(questions.map((q) => [q.q_no, (text[s.usn]?.[q.q_no] ?? '').trim()])
        .filter(([, t]) => t !== '').map(([q, t]) => [q, isAbsent(t) ? 'AB' : Number(t)])),
    })).filter((r) => Object.keys(r.marks).length)
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
        <span className="meta">{int(students.length)} students · {int(filled)} of {int(students.length * questions.length)} boxes filled</span>
      </header>
      <p className="small muted" style={{ marginBottom: 12 }}>
        Enter each student's marks per question, or <span className="id">AB</span> for an absent student (counts as zero).
        Empty boxes are left as they are. Nothing is saved if any value is out of range.
      </p>
      <div className="table-wrap">
        <table>
          <thead><tr><th>USN</th><th className="hide-phone">Name</th>{questions.map((q) => <th key={q.q_no}>{q.q_no}<span className="sub">of {q.max_marks}</span></th>)}<th className="n">Total</th></tr></thead>
          <tbody>
            {students.map((s) => (
              <tr key={s.usn}>
                <td><span className="id">{s.usn}</span></td>
                <td className="hide-phone small">{s.name}</td>
                {questions.map((q) => {
                  const t = text[s.usn]?.[q.q_no] ?? ''
                  const p = problem(q, t)
                  return (
                    <td key={q.q_no} className={p ? 'ocr-flag' : undefined}>
                      <input className="input ocr-num" inputMode="decimal" value={t} aria-label={`${q.q_no} mark of ${s.usn}`} disabled={a.locked}
                             onChange={(e) => setText((all) => ({ ...all, [s.usn]: { ...all[s.usn], [q.q_no]: e.target.value } }))} />
                      {p && <span className="sub">{p}</span>}
                    </td>
                  )
                })}
                <td className="n num">{questions.reduce((sum, q) => sum + (Number(text[s.usn]?.[q.q_no]) || 0), 0)}</td>
              </tr>
            ))}
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

/** Add an experiential-learning assessment: its questions, maxima and COs. Its maximum is their sum. */
export function NewEl({ offering, onCreated, onClose }: { offering: OfferingDetail; onCreated: (message: string) => void; onClose: () => void }) {
  const [rows, setRows] = useState([{ max: 10, cos: '', bloom: '' }, { max: 10, cos: '', bloom: '' }])
  const [name, setName] = useState('Experiential Learning')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const coNumbers = new Set(offering.cos.map((c) => c.co_number))
  const parsed = rows.map((r) => r.cos.split(/[\s,]+/).filter(Boolean).map((c) => Number(c.replace(/^co/i, ''))))
  const problems = rows.map((r, i) => !parsed[i].length || parsed[i].some((c) => !coNumbers.has(c)) ? 'COs of this course, e.g. 1, 2'
    : !(Number.isInteger(r.max) && r.max >= 1 && r.max <= 99) ? 'Max 1 to 99' : null)
  const set = (i: number, patch: Partial<(typeof rows)[number]>) => setRows((all) => all.map((r, j) => j === i ? { ...r, ...patch } : r))

  async function create() {
    setBusy(true); setError(null)
    try {
      await api(`/api/offerings/${offering.offering_id}/assessments`, {
        body: { type: 'EL', name, questions: rows.map((r, i) => ({ q_no: `Q${i + 1}`, max_marks: r.max, cos: parsed[i], bloom: r.bloom ? Number(r.bloom) : null })) },
      })
      onCreated(`${name} added, out of ${rows.reduce((t, r) => t + r.max, 0)}. Type its marks next.`)
    } catch (e) { setError((e as ApiError).message) } finally { setBusy(false) }
  }

  return (
    <section className="panel ocr" aria-labelledby="t-newel">
      <header><h2 id="t-newel">Add experiential learning</h2><span className="meta">Out of {rows.reduce((t, r) => t + (r.max || 0), 0)}</span></header>
      <div className="filters">
        <label htmlFor="el-name" className="small">Name</label>
        <input id="el-name" className="input" value={name} onChange={(e) => setName(e.target.value)} style={{ minWidth: 240 }} />
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Question</th><th className="n">Max marks</th><th>COs</th><th className="n">Bloom level</th><th /></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className={problems[i] ? 'ocr-flag' : undefined}>
                <td><span className="id">Q{i + 1}</span></td>
                <td className="n"><input className="input ocr-num" type="number" min={1} max={99} value={r.max} aria-label={`Q${i + 1} max marks`} onChange={(e) => set(i, { max: Number(e.target.value) })} /></td>
                <td><input className="input ocr-cos" value={r.cos} placeholder="1, 2" aria-label={`Q${i + 1} CO numbers`} onChange={(e) => set(i, { cos: e.target.value })} />
                  {problems[i] && <span className="sub">{problems[i]}</span>}</td>
                <td className="n"><input className="input ocr-num" type="number" min={1} max={6} value={r.bloom} aria-label={`Q${i + 1} Bloom level`} onChange={(e) => set(i, { bloom: e.target.value })} /></td>
                <td className="n">{rows.length > 1 && <button className="btn small ghost" onClick={() => setRows((all) => all.filter((_, j) => j !== i))}>Remove</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {error && <div className="error-box" role="alert">{error}</div>}
      <div className="filters" style={{ marginTop: 16, marginBottom: 0 }}>
        <button className="btn small" disabled={rows.length >= 20} onClick={() => setRows((all) => [...all, { max: 10, cos: '', bloom: '' }])}>Add a question</button>
        <span className="spacer" />
        <button className="btn ghost" disabled={busy} onClick={onClose}>Cancel</button>
        <button className="btn primary" disabled={busy || problems.some(Boolean) || name.trim().length < 2} onClick={create}>{busy ? 'Adding…' : 'Add assessment'}</button>
      </div>
    </section>
  )
}
