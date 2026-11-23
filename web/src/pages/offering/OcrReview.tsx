import { useMemo, useState } from 'react'
import { api, ApiError, type RowError } from '../../api'
import { Pill } from '../../components/States'
import { int } from '../../format'
import type { OfferingDetail } from './types'

// What POST /api/assessments/{id}/ocr returns: suggestions only, nothing is saved yet.
export type OcrQuestion = { q_no: string; text: string; max_marks: number; cos: number[]; bloom: number | null; problems: string[] }
type OcrMark = { q_no: string; value: number; blank: boolean; confidence: number; check: boolean; image: string }
type OcrSheet = {
  page: number; usn: string | null; usn_confidence: number; usn_image: string; check: boolean; problems: string[]
  marks: OcrMark[]; total: { value: number | null; confidence: number; image: string } | null
}
export type OcrResult = {
  assessment: { assessment_id: number; name: string; max_marks: string }
  paper: { questions: OcrQuestion[]; warnings: string[]; paper_max: number | null; same_as_saved: boolean; marks_entered: number }
  sheets: OcrSheet[]; absent: string[]; threshold: number
}

/** Review screen for one read PDF: the teacher corrects what OCR suggested and confirms it. */
export function OcrReview({ data, offering, onSaved, onClose, onErrors }: {
  data: OcrResult; offering: OfferingDetail
  onSaved: (message: string) => void; onClose: () => void; onErrors: (rows: RowError[] | null) => void
}) {
  const [questions, setQuestions] = useState(() => data.paper.questions.map((q) => ({ ...q, cosText: q.cos.join(', ') })))
  const [sheets, setSheets] = useState(() => data.sheets.map((s) => ({ ...s, marks: s.marks.map((m) => ({ ...m, text: String(m.value) })) })))
  const [onlyCheck, setOnlyCheck] = useState(true)
  const [checked, setChecked] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const coNumbers = new Set(offering.cos.map((c) => c.co_number))
  const allUsns = useMemo(() => [...new Set([...data.sheets.map((s) => s.usn).filter(Boolean) as string[], ...data.absent])].sort(), [data])

  const usnCount = new Map<string, number>()
  sheets.forEach((s) => s.usn && usnCount.set(s.usn, (usnCount.get(s.usn) ?? 0) + 1))
  const absent = allUsns.filter((u) => !usnCount.has(u))
  const parsedCos = questions.map((q) => q.cosText.split(/[\s,]+/).filter(Boolean).map(Number))
  const questionProblems = questions.map((q, i) =>
    !parsedCos[i].length || parsedCos[i].some((c) => !coNumbers.has(c)) ? 'COs must be CO numbers of this course' :
    !(q.max_marks >= 1 && q.max_marks <= 99) ? 'Max marks must be 1 to 99' : null)
  const markProblem = (s: (typeof sheets)[number], i: number) => {
    const v = Number(s.marks[i].text)
    const max = questions[i]?.max_marks ?? 0
    return s.marks[i].text === '' || !Number.isInteger(v) || v < 0 || v > max ? `0 to ${max}` : null
  }
  const blocking = [
    ...questionProblems.filter(Boolean),
    ...sheets.filter((s) => !s.usn).map((s) => `Page ${s.page} has no USN`),
    ...[...usnCount].filter(([, n]) => n > 1).map(([u]) => `${u} is on more than one sheet`),
    ...sheets.flatMap((s) => s.marks.map((_, i) => markProblem(s, i) ? `Page ${s.page} ${s.marks[i].q_no}: enter a mark ${markProblem(s, i)}` : null)).filter(Boolean),
  ] as string[]
  const flagged = sheets.filter((s) => s.check).length
  const shown = onlyCheck ? sheets.filter((s) => s.check || !s.usn || (usnCount.get(s.usn) ?? 0) > 1) : sheets

  function setMark(page: number, i: number, text: string) {
    setSheets((all) => all.map((s) => s.page !== page ? s : { ...s, marks: s.marks.map((m, j) => j === i ? { ...m, text } : m) }))
  }

  async function save() {
    setBusy(true); setError(null); onErrors(null)
    const id = data.assessment.assessment_id
    try {
      const payload = { questions: questions.map((q, i) => ({ q_no: q.q_no, max_marks: q.max_marks, cos: parsedCos[i], bloom: q.bloom })) }
      const unchanged = data.paper.same_as_saved && questions.every((q, i) =>
        q.max_marks === data.paper.questions[i].max_marks && parsedCos[i].join() === data.paper.questions[i].cos.join() && q.bloom === data.paper.questions[i].bloom)
      if (!unchanged) await api(`/api/assessments/${id}/questions`, { method: 'PUT', body: payload })
      // The confirmed marks go through the same CSV upload as a hand-made file.
      const lines = [['usn', ...questions.map((q) => q.q_no)].join(',')]
      for (const s of sheets) lines.push([s.usn, ...s.marks.map((m) => m.text)].join(','))
      for (const u of absent) lines.push([u, ...questions.map(() => 'AB')].join(','))
      const form = new FormData()
      form.append('file', new Blob([lines.join('\n')], { type: 'text/csv' }), 'ocr.csv')
      const r = await api<{ saved: number }>(`/api/assessments/${id}/marks`, { form })
      onSaved(`${data.assessment.name}: ${unchanged ? '' : `${questions.length} questions and `}${int(r.saved)} marks saved from the scanned sheets.`)
    } catch (e) {
      const err = e as ApiError
      if (err.errors) onErrors(err.errors)
      setError(err.message)
    } finally { setBusy(false) }
  }

  return (
    <section className="panel ocr" aria-labelledby="t-ocr">
      <header>
        <h2 id="t-ocr">Check the scanned sheets: {data.assessment.name}</h2>
        <span className="meta">{sheets.length} sheets · {flagged} to check · {absent.length} without a sheet</span>
      </header>
      <p className="small muted" style={{ marginBottom: 12 }}>
        Nothing is saved yet. Values read with less than {Math.round(data.threshold * 100)}% confidence, totals that do not add up and
        unclear USNs are highlighted. Correct anything that is wrong, then confirm.
      </p>
      {data.paper.warnings.map((w) => <p key={w} className="note">{w}</p>)}

      <h3 className="ocr-h">Question paper (page 1)</h3>
      {data.paper.marks_entered > 0 && !data.paper.same_as_saved &&
        <p className="note">Marks are already entered for this assessment, so only CO tags and Bloom levels can change.</p>}
      <div className="table-wrap">
        <table>
          <thead><tr><th>Question</th><th>Read as</th><th className="n">Max marks</th><th>COs</th><th className="n">Bloom level</th></tr></thead>
          <tbody>
            {questions.map((q, i) => (
              <tr key={q.q_no} className={questionProblems[i] ? 'ocr-flag' : undefined}>
                <td><span className="id">{q.q_no}</span></td>
                <td className="small">{q.text || '—'}</td>
                <td className="n"><input className="input ocr-num" type="number" min={1} max={99} value={q.max_marks} aria-label={`${q.q_no} max marks`}
                  onChange={(e) => setQuestions((all) => all.map((x, j) => j === i ? { ...x, max_marks: Number(e.target.value) } : x))} /></td>
                <td><input className="input ocr-cos" value={q.cosText} aria-label={`${q.q_no} CO numbers`}
                  onChange={(e) => setQuestions((all) => all.map((x, j) => j === i ? { ...x, cosText: e.target.value } : x))} />
                  {questionProblems[i] && <span className="sub">{questionProblems[i]}</span>}</td>
                <td className="n"><input className="input ocr-num" type="number" min={1} max={6} value={q.bloom ?? ''} aria-label={`${q.q_no} Bloom level`}
                  onChange={(e) => setQuestions((all) => all.map((x, j) => j === i ? { ...x, bloom: e.target.value ? Number(e.target.value) : null } : x))} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="filters" style={{ marginTop: 20 }}>
        <h3 className="ocr-h" style={{ margin: 0 }}>Cover pages</h3>
        <span className="spacer" />
        <label className="small"><input type="checkbox" checked={onlyCheck} onChange={(e) => setOnlyCheck(e.target.checked)} /> Only sheets to check ({flagged})</label>
      </div>
      {shown.length === 0 ? <p className="small muted">Every sheet was read clearly. Untick the filter to see them all.</p> : (
        <div className="table-wrap">
          <table>
            <thead><tr><th className="n">Page</th><th>USN</th>{questions.map((q) => <th key={q.q_no}>{q.q_no}<span className="sub">of {q.max_marks}</span></th>)}<th>Total on sheet</th></tr></thead>
            <tbody>
              {shown.map((s) => (
                <tr key={s.page} className={s.check ? 'ocr-row-flag' : undefined}>
                  <td className="n num">{s.page}</td>
                  <td className={s.usn_confidence < data.threshold || !s.usn || (usnCount.get(s.usn) ?? 0) > 1 ? 'ocr-flag' : undefined}>
                    <img className="ocr-crop" src={s.usn_image} alt={`USN as written on page ${s.page}`} />
                    <select className="input" value={s.usn ?? ''} aria-label={`USN on page ${s.page}`}
                            onChange={(e) => setSheets((all) => all.map((x) => x.page === s.page ? { ...x, usn: e.target.value || null } : x))}>
                      <option value="">Choose…</option>
                      {allUsns.map((u) => <option key={u} value={u}>{u}</option>)}
                    </select>
                    {s.problems.map((p) => <span key={p} className="sub">{p}</span>)}
                  </td>
                  {s.marks.map((m, i) => (
                    <td key={m.q_no} className={m.check || markProblem(s, i) ? 'ocr-flag' : undefined}>
                      <img className="ocr-crop" src={m.image} alt={`${m.q_no} mark as written on page ${s.page}`} />
                      <input className="input ocr-num" inputMode="numeric" value={m.text} aria-label={`${m.q_no} mark on page ${s.page}`}
                             onChange={(e) => setMark(s.page, i, e.target.value)} />
                      {m.check && <span className="sub">{Math.round(m.confidence * 100)}% sure</span>}
                    </td>
                  ))}
                  <td>{s.total && <img className="ocr-crop" src={s.total.image} alt={`Total written on page ${s.page}`} />}
                    <span className="sub">read {s.total?.value ?? '—'} · sum {s.marks.reduce((t, m) => t + (Number(m.text) || 0), 0)}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3 className="ocr-h" style={{ marginTop: 20 }}>No sheet ({absent.length})</h3>
      <p className="small">{absent.length ? <>Saved as absent (<span className="id">AB</span>, counts as zero): {absent.map((u) => <span key={u} className="id ocr-usn">{u}</span>)}</> : 'Every enrolled student has a sheet.'}</p>

      {blocking.length > 0 && <div className="note" role="status">{blocking.slice(0, 6).map((b) => <div key={b}>{b}</div>)}{blocking.length > 6 && <div>…and {blocking.length - 6} more</div>}</div>}
      {error && <div className="error-box" role="alert">{error}</div>}
      <div className="filters" style={{ marginTop: 16, marginBottom: 0 }}>
        <label className="small"><input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} /> I have checked the highlighted values against the sheets</label>
        <span className="spacer" />
        <button className="btn ghost" disabled={busy} onClick={onClose}>Discard</button>
        <button className="btn primary" disabled={busy || !checked || blocking.length > 0} onClick={save}>
          {busy ? 'Saving…' : 'Save questions and marks'}
        </button>
      </div>
      {flagged === 0 && <p className="small muted" style={{ marginTop: 8 }}><Pill kind="pos">All clear</Pill> Every value was read with high confidence.</p>}
    </section>
  )
}
