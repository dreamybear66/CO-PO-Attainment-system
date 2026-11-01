import { useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'
import { Empty, ErrorBox, Pill, SkeletonRows } from '../components/States'
import { num, pct, term } from '../format'
import { useApi } from '../hooks'

type Score = { offering_id: number; code: string; title: string; academic_year: string; term: string; co_id: number; co_number: number; statement: string; pct: string; target_pct: string }
type Survey = { offering_id: number; code: string; title: string; academic_year: string; term: string; answered: boolean; cos: { co_id: number; co_number: number; statement: string }[] }

export function MyScores() {
  const { user } = useAuth()
  const s = useApi<Score[]>('/api/me/scores')
  const groups = new Map<number, Score[]>()
  for (const r of s.data ?? []) groups.set(r.offering_id, [...(groups.get(r.offering_id) ?? []), r])
  const all = s.data ?? []
  const met = all.filter((r) => Number(r.pct) >= Number(r.target_pct)).length

  return (
    <>
      <div className="title-row">
        <div>
          <h1>My CO scores</h1>
          <p className="sub"><span className="id">{user?.usn}</span> · {all.length ? `you reached the target mark on ${met} of ${all.length} course outcomes.` : 'your scores appear once marks are entered.'}</p>
        </div>
      </div>
      {s.error ? <ErrorBox message={s.error} onRetry={s.reload} /> : !s.data ? <SkeletonRows rows={6} /> : groups.size === 0 ? <Empty>No marks recorded for you yet.</Empty> : (
        <div className="stack">
          {[...groups.values()].map((rows) => (
            <section className="panel" key={rows[0].offering_id} aria-label={rows[0].title}>
              <header><h2><span className="id">{rows[0].code}</span> {rows[0].title}</h2><span className="meta">{rows[0].academic_year} · {term(rows[0].term)} · target {num(rows[0].target_pct)}%</span></header>
              <table>
                <thead><tr><th>CO</th><th>Outcome</th><th className="n">Your score</th><th className="n">Target met</th></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.co_id}>
                      <td><span className="id">CO{r.co_number}</span></td>
                      <td className="truncate" title={r.statement}>{r.statement}</td>
                      <td className="n num">{pct(r.pct)}</td>
                      <td className="n">{Number(r.pct) >= Number(r.target_pct) ? <Pill kind="pos">Yes</Pill> : <Pill>Not yet</Pill>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ))}
        </div>
      )}
    </>
  )
}

export function Surveys() {
  const s = useApi<Survey[]>('/api/me/surveys')
  const pending = (s.data ?? []).filter((x) => !x.answered)
  return (
    <>
      <div className="title-row">
        <div><h1>Course-exit surveys</h1>
          <p className="sub">Rate how well you can do each course outcome, from 1 (not at all) to 5 (confidently). Answers are stored without your USN.</p></div>
      </div>
      {s.error ? <ErrorBox message={s.error} onRetry={s.reload} /> : !s.data ? <SkeletonRows rows={4} /> : s.data.length === 0 ? <Empty>No finished courses to rate yet.</Empty> : (
        <div className="stack">
          {pending.length === 0 && <p className="note">You have answered every survey. Thank you.</p>}
          {s.data.map((x) => <SurveyCard key={x.offering_id} survey={x} onDone={s.reload} />)}
        </div>
      )}
    </>
  )
}

function SurveyCard({ survey, onDone }: { survey: Survey; onDone: () => void }) {
  const [ratings, setRatings] = useState<Record<number, number>>({})
  const [msg, setMsg] = useState<string | null>(null)
  const complete = survey.cos.every((c) => ratings[c.co_id])
  async function submit() {
    setMsg(null)
    try {
      await api('/api/me/surveys', { body: { offering_id: survey.offering_id, answers: survey.cos.map((c) => ({ co_id: c.co_id, rating: ratings[c.co_id] })) } })
      onDone()
    } catch (e) { setMsg((e as Error).message) }
  }
  return (
    <section className="panel" aria-label={`Survey for ${survey.title}`}>
      <header><h2><span className="id">{survey.code}</span> {survey.title}</h2>
        {survey.answered ? <Pill kind="pos">Answered</Pill> : <span className="meta">{survey.academic_year} · {term(survey.term)}</span>}</header>
      {!survey.answered && (
        <>
          <div className="rows">
            {survey.cos.map((c) => (
              <div className="row" key={c.co_id} style={{ flexWrap: 'wrap' }}>
                <span className="id" style={{ width: 40 }}>CO{c.co_number}</span>
                <span className="grow">{c.statement}</span>
                <div className="segmented" role="group" aria-label={`Rating for CO${c.co_number}`}>
                  {[1, 2, 3, 4, 5].map((n) => <button key={n} aria-pressed={ratings[c.co_id] === n} onClick={() => setRatings({ ...ratings, [c.co_id]: n })}>{n}</button>)}
                </div>
              </div>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 12 }}>
            <button className="btn primary" disabled={!complete} onClick={submit}>Submit ratings</button>
            {!complete && <span className="small muted">Rate every outcome to submit.</span>}
            {msg && <span className="small below" role="alert">{msg}</span>}
          </div>
        </>
      )}
    </section>
  )
}
