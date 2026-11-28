import { useState } from 'react'
import { Empty, ErrorBox, Pill, SkeletonRows } from '../../components/States'
import { int, num, pct } from '../../format'
import { useApi } from '../../hooks'

type Num = number | string | null
type FinalRow = {
  usn: string; name: string; cie1: Num; cie2: Num; cie3: Num; cies: number; dropped: number[]; cie_pct: Num
  el: Num; el_max: Num; see: Num; see_max: Num; total: Num; out_of: Num
}
type FinalData = { best_of: number | null; weights: { cie: Num; el: Num; see: Num } | null; students: FinalRow[] }

type Prereq = { course_code: string; co_number: number; statement: string; depth: number; academic_year: string; pct: Num; target_pct: Num; below: boolean }
type Missed = { co_id: number; co_number: number; statement: string; pct: Num; prereqs: Prereq[] }
type Lost = { assessment: string; q_no: string; cos: number[]; max_marks: Num; got: Num; is_absent: boolean; lost: Num }
type WeakStudent = { usn: string; name: string; missed: Missed[]; questions: Lost[]; weak_prereqs: number }
type WeakData = { target_pct: Num; students: WeakStudent[] }

const SHOWN = 15
const marks = (got: Num, max: Num) => (max === null ? '—' : `${num(got)} / ${num(max)}`)

/** Each student's final total out of 100: their best CIEs, EL and SEE (partial while the term runs). */
export function FinalMarks({ offeringId }: { offeringId: number }) {
  const data = useApi<FinalData>(`/api/offerings/${offeringId}/final-marks`)
  const [all, setAll] = useState(false)
  if (data.error) return <ErrorBox message={data.error} onRetry={data.reload} />
  if (!data.data) return <SkeletonRows rows={4} />
  const { weights, best_of: bestOf, students } = data.data
  const rows = all ? students : students.slice(0, SHOWN)
  const cie = (s: FinalRow, n: 1 | 2 | 3) => {
    const v = s[`cie${n}`]
    if (v === null) return <span className="dash">—</span>
    return s.dropped.includes(n)
      ? <span title="Dropped: not among this student's best CIEs" className="muted"><s className="num">{pct(v)}</s> <Pill>dropped</Pill></span>
      : <span className="num">{pct(v)}</span>
  }
  return (
    <section className="panel" aria-labelledby="t-final">
      <header>
        <h2 id="t-final">Final marks</h2>
        <span className="meta">{weights ? `Best ${bestOf} CIEs × ${num(weights.cie)} + EL × ${num(weights.el)} + SEE × ${num(weights.see)} = 100` : 'No rule version for this term'}</span>
      </header>
      <p className="small muted" style={{ marginBottom: 12 }}>
        A CIE is its quiz and test together. Each student keeps their best {bestOf ?? 2} CIEs; the dropped one counts neither here nor in their CO scores.
        While the term runs, the total counts only the parts with marks, out of the number shown.
      </p>
      {students.length === 0 ? <Empty>No students enrolled.</Empty> : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Student</th><th className="n">CIE 1</th><th className="n">CIE 2</th><th className="n">CIE 3</th>
              <th className="n">EL</th><th className="n">SEE</th><th className="n">Total</th></tr></thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.usn}>
                  <td><span className="id">{s.usn}</span><span className="sub">{s.name}</span></td>
                  <td className="n">{cie(s, 1)}</td><td className="n">{cie(s, 2)}</td><td className="n">{cie(s, 3)}</td>
                  <td className="n num">{marks(s.el, s.el_max)}</td>
                  <td className="n num">{marks(s.see, s.see_max)}</td>
                  <td className="n num"><b>{Number(s.out_of) ? num(s.total)?.toFixed(1) : '—'}</b><span className="sub">of {int(s.out_of)}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {students.length > SHOWN && (
        <div style={{ marginTop: 12 }}><button className="btn small ghost" onClick={() => setAll((x) => !x)}>{all ? 'Show fewer' : `Show all ${int(students.length)}`}</button></div>
      )}
    </section>
  )
}

/** Root cause per student: the COs each weak student missed, the questions that cost them most, and
 *  whether they were also weak in the related CO of a prerequisite course. */
export function WeakStudents({ offeringId, onCopy }: { offeringId: number; onCopy: (usns: string[]) => void }) {
  const data = useApi<WeakData>(`/api/offerings/${offeringId}/weak-students`)
  const [all, setAll] = useState(false)
  if (data.error) return <ErrorBox message={data.error} onRetry={data.reload} />
  if (!data.data) return <SkeletonRows rows={4} />
  const { students, target_pct: target } = data.data
  const rows = all ? students : students.slice(0, SHOWN)
  const withPrereq = students.filter((s) => s.weak_prereqs > 0).length
  return (
    <section className="panel" aria-labelledby="t-rca">
      <header>
        <h2 id="t-rca">Why each weak student is weak</h2>
        <span className="meta">{int(students.length)} student{students.length === 1 ? '' : 's'} below {target === null ? 'the target' : pct(target)} in a CO
          {withPrereq ? ` · ${int(withPrereq)} also weak in a prerequisite` : ''}</span>
      </header>
      <p className="small muted" style={{ marginBottom: 12 }}>
        For each student: the COs they missed, the questions where they lost the most marks (from their best CIEs and the SEE), and the
        prerequisite-course COs these COs build on, with the student's earlier score. A weak prerequisite is a likely place to start remedial work.
      </p>
      {students.length === 0 ? <Empty>No student is below the target in any CO.</Empty> : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Student</th><th>Missed COs</th><th>Lost the most marks on</th><th>Prerequisites</th></tr></thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.usn} style={{ verticalAlign: 'top' }}>
                  <td><span className="id">{s.usn}</span><span className="sub">{s.name}</span></td>
                  <td>
                    {s.missed.map((c) => (
                      <div key={c.co_id} className="small" title={c.statement}>
                        <span className="id">CO{c.co_number}</span> <span className="below num">{pct(c.pct)}</span>
                      </div>
                    ))}
                  </td>
                  <td>
                    {s.questions.length === 0 ? <span className="dash">—</span> : s.questions.map((q, i) => (
                      <div key={i} className="small">
                        {q.assessment} {q.q_no} <span className="muted">(CO{q.cos.join(', CO')})</span>: lost <span className="num">{num(q.lost)}</span> of <span className="num">{num(q.max_marks)}</span>{q.is_absent ? ' (absent)' : ''}
                      </div>
                    ))}
                  </td>
                  <td>
                    {s.missed.every((c) => c.prereqs.length === 0) ? <span className="small muted">No earlier score on a prerequisite CO</span>
                      : s.missed.flatMap((c) => c.prereqs.map((p) => (
                        <div key={`${c.co_id}-${p.course_code}-${p.co_number}`} className="small" title={p.statement}>
                          CO{c.co_number} ← <span className="id">{p.course_code} CO{p.co_number}</span> {p.academic_year}:{' '}
                          {p.below ? <Pill kind="neg">weak {pct(p.pct)}</Pill> : <span className="num muted">{pct(p.pct)} ok</span>}
                        </div>
                      )))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="filters" style={{ marginTop: 12, marginBottom: 0 }}>
        {students.length > SHOWN && <button className="btn small ghost" onClick={() => setAll((x) => !x)}>{all ? 'Show fewer' : `Show all ${int(students.length)}`}</button>}
        <span className="spacer" />
        {students.length > 0 && <button className="btn small ghost" onClick={() => onCopy(students.map((s) => s.usn))}>Copy USNs</button>}
      </div>
    </section>
  )
}
