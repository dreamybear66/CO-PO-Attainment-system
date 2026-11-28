import { useState } from 'react'
import { Segmented } from '../../components/motion'
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
const matches = (q: string, s: { usn: string; name: string }) =>
  !q || s.usn.toLowerCase().includes(q) || s.name.toLowerCase().includes(q)

/** Each student's CIE 1-3, EL, SEE and final total out of 100. */
export function FinalMarks({ offeringId }: { offeringId: number }) {
  const data = useApi<FinalData>(`/api/offerings/${offeringId}/final-marks`)
  const [all, setAll] = useState(false)
  const [query, setQuery] = useState('')
  if (data.error) return <ErrorBox message={data.error} onRetry={data.reload} />
  if (!data.data) return <SkeletonRows rows={4} />
  const { students } = data.data
  const q = query.trim().toLowerCase()
  const found = students.filter((s) => matches(q, s))
  const rows = all || q ? found : found.slice(0, SHOWN)
  const cie = (s: FinalRow, n: 1 | 2 | 3) => {
    const v = s[`cie${n}`]
    if (v === null) return <span className="dash">—</span>
    return s.dropped.includes(n)
      ? <span className="muted" title="Not counted"><s className="num">{pct(v)}</s></span>
      : <span className="num">{pct(v)}</span>
  }
  return (
    <section className="panel" aria-labelledby="t-final">
      <header>
        <h2 id="t-final">Final marks</h2>
        <span className="meta">{int(students.length)} students</span>
      </header>
      {students.length === 0 ? <Empty>No students enrolled.</Empty> : <>
        <div className="filters">
          <input className="input" type="search" placeholder="Search USN or name" aria-label="Search students"
                 value={query} onChange={(e) => setQuery(e.target.value)} style={{ width: 240 }} />
        </div>
        {found.length === 0 ? <Empty>No student matches “{query}”.</Empty> : (
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
        {!q && found.length > SHOWN && (
          <div style={{ marginTop: 12 }}><button className="btn small ghost" onClick={() => setAll((x) => !x)}>{all ? 'Show fewer' : `Show all ${int(found.length)}`}</button></div>
        )}
      </>}
    </section>
  )
}

/** Weak students: the COs each one missed, the questions that cost them most, and the earlier
 *  prerequisite COs they were also weak in. */
export function WeakStudents({ offeringId, onCopy }: { offeringId: number; onCopy: (usns: string[]) => void }) {
  const data = useApi<WeakData>(`/api/offerings/${offeringId}/weak-students`)
  const [all, setAll] = useState(false)
  const [co, setCo] = useState<number | 'all'>('all')
  if (data.error) return <ErrorBox message={data.error} onRetry={data.reload} />
  if (!data.data) return <SkeletonRows rows={4} />
  const { students } = data.data
  const perCo = new Map<number, number>()
  for (const s of students) for (const c of s.missed) perCo.set(c.co_number, (perCo.get(c.co_number) ?? 0) + 1)
  const coNumbers = [...perCo.keys()].sort((a, b) => a - b)
  const shown = co === 'all' ? students : students.filter((s) => s.missed.some((c) => c.co_number === co))
  const rows = all ? shown : shown.slice(0, SHOWN)
  return (
    <section className="panel" aria-labelledby="t-rca">
      <header>
        <h2 id="t-rca">Weak students</h2>
        <span className="meta">{int(students.length)} below target in a CO</span>
      </header>
      {students.length === 0 ? <Empty>Every student reached the target in every CO.</Empty> : <>
        <div className="filters">
          <Segmented<number | 'all'> label="CO" value={co} onChange={(v) => { setCo(v); setAll(false) }}
                                     options={[{ value: 'all', label: `All ${students.length}` },
                                               ...coNumbers.map((n) => ({ value: n, label: `CO${n} · ${perCo.get(n)}` }))]} />
          <span className="spacer" />
          <button className="btn small ghost" onClick={() => onCopy(shown.map((s) => s.usn))}>Copy USNs</button>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Student</th><th>COs missed</th><th>Lost most marks on</th><th>Also weak earlier in</th></tr></thead>
            <tbody>
              {rows.map((s) => {
                const weakEarlier = s.missed.flatMap((c) => c.prereqs.filter((p) => p.below))
                  .filter((p, i, a) => a.findIndex((x) => x.course_code === p.course_code && x.co_number === p.co_number) === i)
                return (
                  <tr key={s.usn} style={{ verticalAlign: 'top' }}>
                    <td><span className="id">{s.usn}</span><span className="sub">{s.name}</span></td>
                    <td>
                      <div className="pill-list">
                        {s.missed.map((c) => <span key={c.co_id} title={c.statement}><Pill kind="neg">CO{c.co_number} · {pct(c.pct)}</Pill></span>)}
                      </div>
                    </td>
                    <td>
                      {s.questions.length === 0 ? <span className="dash">—</span> : s.questions.map((q, i) => (
                        <div key={i} className="small">
                          {q.assessment} {q.q_no}: <span className="num">{num(q.got)} / {num(q.max_marks)}</span>{q.is_absent ? ' (absent)' : ''}
                        </div>
                      ))}
                    </td>
                    <td>
                      {weakEarlier.length === 0 ? <span className="dash">—</span> : weakEarlier.map((p) => (
                        <div key={`${p.course_code}-${p.co_number}`} className="small" title={p.statement}>
                          <span className="id">{p.course_code} CO{p.co_number}</span> <span className="muted">{p.academic_year}</span> <span className="below num">{pct(p.pct)}</span>
                        </div>
                      ))}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        {shown.length > SHOWN && (
          <div style={{ marginTop: 12 }}><button className="btn small ghost" onClick={() => setAll((x) => !x)}>{all ? 'Show fewer' : `Show all ${int(shown.length)}`}</button></div>
        )}
      </>}
    </section>
  )
}
