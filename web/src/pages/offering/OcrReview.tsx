import { useMemo, useState } from 'react'
import { api, ApiError, type RowError } from '../../api'
import { Pill } from '../../components/States'
import { int } from '../../format'
import type { OfferingDetail } from './types'

// What POST /api/offerings/{id}/scan returns: suggestions only, nothing is saved yet.
type Part = 'A' | 'B'
export type ScanQuestion = {
  q_no: string; text: string; max_marks: number; cos: number[]; bloom: number | null
  part: Part | null; number: string | null; problems: string[]
}
type ScanPart = {
  part: Part; heading: string; name: string; type: string; assessment_id: number | null; create: boolean
  max_marks: number | null; marks_entered: number; same_as_saved: boolean; absent_with_marks: string[]
}
type OcrMark = { q_no: string; value: number | null; blank: boolean; confidence: number; check: boolean; image: string | null }
type OcrSheet = {
  page: number; usn: string | null; usn_confidence: number; usn_image: string; check: boolean; problems: string[]
  marks: OcrMark[]; total: { value: number | null; confidence: number; image: string } | null
}
export type ScanResult = {
  sitting: 'CIE1' | 'CIE2' | 'SEE'; label: string; offering_id: number; parts: ScanPart[]
  paper: { questions: ScanQuestion[]; warnings: string[]; paper_max: number | null }
  sheets: OcrSheet[]; absent: string[]; threshold: number
}
type Saved = { assessments: { name: string; created: boolean; questions_saved: boolean; marks_saved: number }[]; saved: number }

/** Review screen for one scanned sitting: the teacher corrects what OCR suggested and confirms it.
 *  Confirming saves the questions and marks of both parts; locking stays a separate step. */
export function OcrReview({ data, offering, onSaved, onClose, onErrors }: {
  data: ScanResult; offering: OfferingDetail
  onSaved: (message: string) => void; onClose: () => void; onErrors: (rows: RowError[] | null) => void
}) {
  const see = data.sitting === 'SEE'
  const [questions, setQuestions] = useState(() => data.paper.questions.map((q) => ({ ...q, cosText: q.cos.join(', ') })))
  const [sheets, setSheets] = useState(() => data.sheets.map((s) => ({ ...s, marks: s.marks.map((m) => ({ ...m, text: m.value === null ? '' : String(m.value) })) })))
  const [skipped, setSkipped] = useState<Set<number>>(new Set())
  const [overwriteAbsent, setOverwriteAbsent] = useState(false)
  const [onlyCheck, setOnlyCheck] = useState(true)
  const [checked, setChecked] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const coNumbers = new Set(offering.cos.map((c) => c.co_number))
  const allUsns = useMemo(() => [...new Set([...data.sheets.map((s) => s.usn).filter(Boolean) as string[], ...data.absent])].sort(), [data])
  const partOf = new Map(data.parts.map((p) => [p.part, p]))

  // Within each assessment the questions are numbered from Q1 in paper order, as the server saves them.
  const numberOf = new Map<string, string>()
  const seen: Record<string, number> = {}
  for (const q of [...questions].sort((a, b) => Number(a.q_no.slice(1)) - Number(b.q_no.slice(1)))) {
    if (!q.part) continue
    seen[q.part] = (seen[q.part] ?? 0) + 1
    numberOf.set(q.q_no, `Q${seen[q.part]}`)
  }

  const usnCount = new Map<string, number>()
  sheets.forEach((s) => s.usn && !skipped.has(s.page) && usnCount.set(s.usn, (usnCount.get(s.usn) ?? 0) + 1))
  const kept = sheets.filter((s) => !skipped.has(s.page))
  const absent = allUsns.filter((u) => !usnCount.has(u))
  // A student with no sheet here but marks already saved (e.g. scanned in another PDF) keeps them,
  // unless the teacher explicitly marks them absent too.
  const hasMarks = new Set(data.parts.flatMap((p) => p.absent_with_marks))
  const absentNew = absent.filter((u) => !hasMarks.has(u))
  const absentKept = absent.filter((u) => hasMarks.has(u))
  const maxOf = new Map(questions.map((q) => [q.q_no, q.max_marks]))
  const parsedCos = questions.map((q) => q.cosText.split(/[\s,]+/).filter(Boolean).map(Number))
  const questionProblems = questions.map((q, i) =>
    !parsedCos[i].length || parsedCos[i].some((c) => !coNumbers.has(c)) ? 'COs must be CO numbers of this course' :
    !(q.max_marks >= 1 && q.max_marks <= 99) ? 'Max marks must be 1 to 99' :
    !q.part ? 'Choose Part A or Part B' : null)
  const markProblem = (s: (typeof sheets)[number], i: number) => {
    const v = Number(s.marks[i].text)
    const max = maxOf.get(s.marks[i].q_no) ?? 0
    return s.marks[i].text === '' || !Number.isInteger(v) || v < 0 || v > max ? `0 to ${max}` : null
  }
  const blocking = [
    ...questionProblems.map((p, i) => p ? `${questions[i].q_no}: ${p}` : null).filter(Boolean),
    ...kept.filter((s) => !s.usn).map((s) => `Page ${s.page} has no USN (choose one, or skip the page)`),
    ...[...usnCount].filter(([, n]) => n > 1).map(([u]) => `${u} is on more than one sheet`),
    ...kept.flatMap((s) => s.marks.map((_, i) => markProblem(s, i) ? `Page ${s.page} ${s.marks[i].q_no}: enter a mark ${markProblem(s, i)}` : null)).filter(Boolean),
  ] as string[]
  const flagged = sheets.filter((s) => s.check).length
  const shown = onlyCheck ? sheets.filter((s) => s.check || !s.usn || (usnCount.get(s.usn) ?? 0) > 1) : sheets
  const target = (q: { part: Part | null }) => (q.part ? partOf.get(q.part) : undefined)

  function setMark(page: number, i: number, text: string) {
    setSheets((all) => all.map((s) => s.page !== page ? s : { ...s, marks: s.marks.map((m, j) => j === i ? { ...m, text } : m) }))
  }
  function setQuestion(i: number, patch: Partial<(typeof questions)[number]>) {
    setQuestions((all) => all.map((x, j) => j === i ? { ...x, ...patch } : x))
  }

  async function save() {
    setBusy(true); setError(null); onErrors(null)
    try {
      const r = await api<Saved>(`/api/offerings/${data.offering_id}/scan/confirm`, {
        body: {
          sitting: data.sitting,
          questions: questions.map((q, i) => ({ q_no: q.q_no, max_marks: q.max_marks, cos: parsedCos[i], bloom: q.bloom, part: q.part })),
          sheets: kept.map((s) => ({ page: s.page, usn: s.usn, marks: Object.fromEntries(s.marks.map((m) => [m.q_no, Number(m.text)])) })),
          overwrite_absent: overwriteAbsent,
        },
      })
      const what = r.assessments.map((a) => `${a.name} ${a.created ? 'created' : 'filled'}`).join(', ')
      onSaved(`${data.label}: ${what}; ${int(r.saved)} marks saved from the scanned sheets. Lock each assessment when it is final.`)
    } catch (e) {
      const err = e as ApiError
      if (err.errors) onErrors(err.errors)
      setError(err.message)
    } finally { setBusy(false) }
  }

  // Mark columns grouped by part (Part A, Part B, then any question without a part yet).
  const groups = [...(['A', 'B'] as Part[]).map((p) => ({ key: p as string, label: `${partOf.get(p)?.heading} · ${partOf.get(p)?.name}`, qs: questions.filter((q) => q.part === p) })),
    { key: 'none', label: 'No part yet', qs: questions.filter((q) => !q.part) }].filter((g) => g.qs.length)
  const columns = groups.flatMap((g) => g.qs.map((q) => q.q_no))

  return (
    <section className="panel ocr" aria-labelledby="t-ocr">
      <header>
        <h2 id="t-ocr">Check the scanned sheets: {data.label}</h2>
        <span className="meta">{sheets.length} sheets · {flagged} to check · {skipped.size} skipped · {absent.length} without a sheet</span>
      </header>
      <p className="small muted" style={{ marginBottom: 12 }}>
        Nothing is saved yet. Values read with less than {Math.round(data.threshold * 100)}% confidence, totals that do not add up and
        unclear USNs are highlighted. Correct anything that is wrong, then confirm.
      </p>
      {data.paper.warnings.map((w) => <p key={w} className="note">{w}</p>)}

      <div className="table-wrap" style={{ marginBottom: 16 }}>
        <table>
          <thead><tr><th>{see ? 'Paper' : 'Part'}</th><th>Saved to</th><th className="n">Questions</th><th className="n">Out of</th><th>Note</th></tr></thead>
          <tbody>
            {data.parts.map((p) => {
              const qs = questions.filter((q) => q.part === p.part)
              return (
                <tr key={p.part}>
                  <td>{p.heading}</td>
                  <td>{p.name} {p.create ? <Pill kind="warn">New</Pill> : <Pill>Existing</Pill>}</td>
                  <td className="n num">{qs.length}</td>
                  <td className="n num">{qs.reduce((t, q) => t + q.max_marks, 0)}</td>
                  <td className="small">{qs.length === 0 ? 'No questions on this paper; nothing is saved here'
                    : p.create ? 'Created when you save'
                    : p.marks_entered > 0 && !p.same_as_saved ? 'Marks are already entered, so only CO tags and Bloom levels can change'
                    : p.marks_entered > 0 ? `${int(p.marks_entered)} marks already entered; these sheets replace theirs` : 'Filled when you save'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <h3 className="ocr-h">Question paper (page 1)</h3>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Question</th>{!see && <th>Part</th>}<th>Saved as</th><th>Read as</th><th className="n">Max marks</th><th>COs</th><th className="n">Bloom level</th></tr></thead>
          <tbody>
            {questions.map((q, i) => (
              <tr key={q.q_no} className={questionProblems[i] ? 'ocr-flag' : undefined}>
                <td><span className="id">{q.q_no}</span></td>
                {!see && <td>
                  <select className="input" value={q.part ?? ''} aria-label={`${q.q_no} part`}
                          onChange={(e) => setQuestion(i, { part: (e.target.value || null) as Part | null })}>
                    <option value="">Choose…</option>
                    <option value="A">Part A - Quiz</option>
                    <option value="B">Part B - Test</option>
                  </select>
                </td>}
                <td className="small">{target(q) ? <>{target(q)!.name} <span className="id">{numberOf.get(q.q_no)}</span></> : '—'}</td>
                <td className="small">{q.text || '—'}</td>
                <td className="n"><input className="input ocr-num" type="number" min={1} max={99} value={q.max_marks} aria-label={`${q.q_no} max marks`}
                  onChange={(e) => setQuestion(i, { max_marks: Number(e.target.value) })} /></td>
                <td><input className="input ocr-cos" value={q.cosText} aria-label={`${q.q_no} CO numbers`}
                  onChange={(e) => setQuestion(i, { cosText: e.target.value })} />
                  {questionProblems[i] && <span className="sub">{questionProblems[i]}</span>}</td>
                <td className="n"><input className="input ocr-num" type="number" min={1} max={6} value={q.bloom ?? ''} aria-label={`${q.q_no} Bloom level`}
                  onChange={(e) => setQuestion(i, { bloom: e.target.value ? Number(e.target.value) : null })} /></td>
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
            <thead>
              {!see && (
                <tr>
                  <th colSpan={2} />
                  {groups.map((g) => <th key={g.key} colSpan={g.qs.length}>{g.label}</th>)}
                  <th />
                </tr>
              )}
              <tr><th className="n">Page</th><th>USN</th>{columns.map((qn) => <th key={qn}>{qn}<span className="sub">of {maxOf.get(qn)}</span></th>)}<th>Total on sheet</th></tr>
            </thead>
            <tbody>
              {shown.map((s) => (
                <tr key={s.page} className={skipped.has(s.page) ? 'ocr-skipped' : s.check ? 'ocr-row-flag' : undefined}>
                  <td className="n num">{s.page}
                    <label className="sub"><input type="checkbox" checked={skipped.has(s.page)} aria-label={`Skip page ${s.page}`}
                      onChange={(e) => setSkipped((all) => { const n = new Set(all); if (e.target.checked) { n.add(s.page) } else { n.delete(s.page) } return n })} /> skip</label></td>
                  <td className={s.usn_confidence < data.threshold || !s.usn || (usnCount.get(s.usn) ?? 0) > 1 ? 'ocr-flag' : undefined}>
                    <img className="ocr-crop" src={s.usn_image} alt={`USN as written on page ${s.page}`} />
                    <select className="input" value={s.usn ?? ''} aria-label={`USN on page ${s.page}`}
                            onChange={(e) => setSheets((all) => all.map((x) => x.page === s.page ? { ...x, usn: e.target.value || null } : x))}>
                      <option value="">Choose…</option>
                      {allUsns.map((u) => <option key={u} value={u}>{u}</option>)}
                    </select>
                    {s.problems.map((p) => <span key={p} className="sub">{p}</span>)}
                  </td>
                  {columns.map((qn) => {
                    const i = s.marks.findIndex((x) => x.q_no === qn)
                    const m = s.marks[i]
                    if (!m) return <td key={qn} />
                    return (
                      <td key={m.q_no} className={m.check || markProblem(s, i) ? 'ocr-flag' : undefined}>
                        {m.image && <img className="ocr-crop" src={m.image} alt={`${m.q_no} mark as written on page ${s.page}`} />}
                        <input className="input ocr-num" inputMode="numeric" value={m.text} aria-label={`${m.q_no} mark on page ${s.page}`}
                               onChange={(e) => setMark(s.page, i, e.target.value)} />
                        {m.check && <span className="sub">{Math.round(m.confidence * 100)}% sure</span>}
                      </td>
                    )
                  })}
                  <td>{s.total && <img className="ocr-crop" src={s.total.image} alt={`Total written on page ${s.page}`} />}
                    <span className="sub">read {s.total?.value ?? '—'} · sum {s.marks.reduce((t, m) => t + (Number(m.text) || 0), 0)}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3 className="ocr-h" style={{ marginTop: 20 }}>No sheet ({absent.length})</h3>
      {absent.length === 0 && <p className="small">Every enrolled student has a sheet.</p>}
      {absentNew.length > 0 && <p className="small">Saved as absent in {data.parts.map((p) => p.name).join(' and ')} (<span className="id">AB</span>, counts as zero): {absentNew.map((u) => <span key={u} className="id ocr-usn">{u}</span>)}</p>}
      {absentKept.length > 0 && (
        <p className="small">
          Already have marks here, kept as they are: {absentKept.map((u) => <span key={u} className="id ocr-usn">{u}</span>)}
          <br /><label><input type="checkbox" checked={overwriteAbsent} onChange={(e) => setOverwriteAbsent(e.target.checked)} /> Mark these {absentKept.length} as absent too, replacing their marks</label>
        </p>
      )}

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
