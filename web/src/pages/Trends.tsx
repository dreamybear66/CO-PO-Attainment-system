import { useMemo, useState } from 'react'
import { Chart } from '../components/Chart'
import { Empty, ErrorBox, SkeletonRows } from '../components/States'
import { level, num, signed } from '../format'
import { useApi } from '../hooks'

type Course = { course_id: number; code: string; title: string; semester: number }
type TrendRow = { co_id: number; co_number: number; statement: string; academic_year: string; final_level: string; sections: number; target: string; change_vs_prev_year: string | null }
type Weak = { weakest_rank: number; code: string; title: string; co_number: number; statement: string; final_level: string; sections: number; target: string }
type ProgramPo = { po_id: number; po_code: string; type: string; statement: string; academic_year: string; offerings: number; attainment: string; target: string }

export function Trends() {
  const courses = useApi<Course[]>('/api/courses')
  const years = useApi<string[]>('/api/academic-years')
  const [courseId, setCourseId] = useState<number | null>(null)
  const [coPick, setCoNo] = useState<number | null>(null)
  const [year, setYear] = useState<string | null>(null)
  const course = courseId ?? courses.data?.find((c) => c.code === 'IS243')?.course_id ?? courses.data?.[0]?.course_id ?? null
  const activeYear = year ?? years.data?.[0] ?? null

  const trend = useApi<TrendRow[]>(course ? `/api/analytics/trend?course_id=${course}` : null)
  const weak = useApi<Weak[]>(activeYear ? `/api/analytics/weakest?academic_year=${activeYear}&limit=8` : null)
  const po = useApi<ProgramPo[]>('/api/analytics/program-po')

  const trendYears = useMemo(() => [...new Set((trend.data ?? []).map((r) => r.academic_year))].sort(), [trend.data])
  const coNumbers = useMemo(() => [...new Set((trend.data ?? []).map((r) => r.co_number))].sort(), [trend.data])
  // open on the CO with the deepest dip in any year, the one most worth a look
  const deepest = useMemo(() => (trend.data ?? []).reduce<TrendRow | null>((m, r) => (!m || Number(r.final_level) < Number(m.final_level) ? r : m), null), [trend.data])
  const coNo = coPick ?? deepest?.co_number ?? 1
  const series = trendYears.map((y) => num(trend.data?.find((r) => r.co_number === coNo && r.academic_year === y)?.final_level) ?? null)
  const target = num(trend.data?.[0]?.target) ?? 2
  const poYear = (po.data ?? []).filter((p) => p.academic_year === activeYear)
  const selected = courses.data?.find((c) => c.course_id === course)
  const coStatement = trend.data?.find((r) => r.co_number === coNo)?.statement
  const lastTwo = series.slice(-2)
  const finding = lastTwo.length === 2 && lastTwo[0] !== null && lastTwo[1] !== null
    ? `Moved ${signed(lastTwo[1] - lastTwo[0])} in ${trendYears[trendYears.length - 1]} against ${trendYears[trendYears.length - 2]}.` : ''

  return (
    <>
      <div className="title-row">
        <div>
          <h1>Trends</h1>
          <p className="sub">How each course's COs moved year on year, the weakest COs of a year, and programme-level PO attainment (plain average of offerings).</p>
        </div>
      </div>
      <div className="filters">
        <label className="visually-hidden" htmlFor="course">Course</label>
        <select id="course" className="input" value={course ?? ''} onChange={(e) => { setCourseId(Number(e.target.value)); setCoNo(null) }}>
          {(courses.data ?? []).map((c) => <option key={c.course_id} value={c.course_id}>{c.code} · {c.title}</option>)}
        </select>
        <label className="visually-hidden" htmlFor="ay">Academic year for ranking and POs</label>
        <select id="ay" className="input" value={activeYear ?? ''} onChange={(e) => setYear(e.target.value)}>
          {(years.data ?? []).map((y) => <option key={y} value={y}>{y}</option>)}
        </select>
      </div>

      <div className="grid top">
        <section className="panel span-8" aria-labelledby="t-trend">
          <header>
            <h2 id="t-trend"><span className="id">{selected?.code}</span> CO{coNo} final level by year</h2>
            <div className="segmented" role="group" aria-label="CO">
              {coNumbers.map((n) => <button key={n} aria-pressed={coNo === n} onClick={() => setCoNo(n)}>CO{n}</button>)}
            </div>
          </header>
          <p className="small muted" style={{ marginBottom: 8 }}>{coStatement ? `${coStatement}. ` : ''}{finding}</p>
          {trend.error ? <ErrorBox message={trend.error} onRetry={trend.reload} />
            : !trend.data ? <SkeletonRows rows={5} />
            : trendYears.length === 0 ? <Empty>No computed offerings of this course yet.</Empty>
            : <Chart label={`CO${coNo} final level by academic year`} deps={[coNo, trend.data]}
                     draw={(el, C) => C.line(el, { labels: trendYears, series: [{ name: `CO${coNo}`, values: series }], format: C.fmt.dec(2), yTicks: [0, 1, 2, 3], height: 220, reference: { value: target, label: `Target ${level(target)}` } })} />}
        </section>

        <section className="panel span-4" aria-labelledby="t-table">
          <header><h2 id="t-table">All COs</h2><span className="meta">sections averaged</span></header>
          {trend.data && trendYears.length > 0 ? (
            <div className="table-wrap">
              <table>
                <thead><tr><th>CO</th>{trendYears.slice(-3).map((y) => <th key={y} className="n">{y}</th>)}</tr></thead>
                <tbody>
                  {coNumbers.map((n) => (
                    <tr key={n}>
                      <td><span className="id">CO{n}</span></td>
                      {trendYears.slice(-3).map((y) => {
                        const r = trend.data!.find((x) => x.co_number === n && x.academic_year === y)
                        return <td key={y} className={`n num ${r && Number(r.final_level) < Number(r.target) ? 'below' : ''}`}>{r ? level(r.final_level) : <span className="dash">—</span>}</td>
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <SkeletonRows rows={5} />}
        </section>

        <section className="panel span-7" aria-labelledby="t-po">
          <header><h2 id="t-po">Programme PO attainment · {activeYear}</h2><span className="meta">target {level(poYear[0]?.target ?? 2)}</span></header>
          {po.error ? <ErrorBox message={po.error} onRetry={po.reload} />
            : !po.data ? <SkeletonRows rows={5} />
            : poYear.length === 0 ? <Empty>No PO results for {activeYear}.</Empty>
            : <Chart label={`Programme PO attainment in ${activeYear}`} deps={[activeYear, po.data]}
                     draw={(el, C) => C.bars(el, { labels: poYear.map((p) => p.po_code), values: poYear.map((p) => Number(p.attainment)), format: C.fmt.dec(2), height: 220, reference: { value: Number(poYear[0].target), label: 'Target' }, highlight: poYear.map((_, i) => i) })} />}
        </section>

        <section className="panel span-5" aria-labelledby="t-weak">
          <header><h2 id="t-weak">Weakest COs · {activeYear}</h2><span className="meta">ranked by final level</span></header>
          {weak.error ? <ErrorBox message={weak.error} onRetry={weak.reload} />
            : !weak.data ? <SkeletonRows rows={6} />
            : weak.data.length === 0 ? <Empty>No results for {activeYear}.</Empty>
            : (
              <table>
                <thead><tr><th className="n">Rank</th><th>CO</th><th className="n">Level</th></tr></thead>
                <tbody>
                  {weak.data.map((w) => (
                    <tr key={`${w.code}${w.co_number}`}>
                      <td className="n num">{w.weakest_rank}</td>
                      <td><span className="id">{w.code} CO{w.co_number}</span><span className="sub truncate">{w.title}</span></td>
                      <td className={`n num ${Number(w.final_level) < Number(w.target) ? 'below' : ''}`}>{level(w.final_level)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
        </section>
      </div>
    </>
  )
}
