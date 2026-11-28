import { useState } from 'react'
import { api, ApiError } from '../../api'
import { Segmented } from '../../components/motion'
import { Empty, ErrorBox, Pill, SkeletonRows } from '../../components/States'
import { int, pct, when } from '../../format'
import { useApi } from '../../hooks'
import { FinalMarks, WeakStudents } from './StudentResults'
import type { OfferingDetail } from './types'

type Reason = { feature: string; label: string; value: number; typical: number; effect: number }
type Flag = { usn: string; name: string; co_id: number; probability: string; reasons: Reason[] }
type StudentsData = {
  finished: boolean; target_pct: number | null; enrolled: number
  weak: { co_id: number; co_number: number; statement: string }[]
  early_warning: null | {
    stage: { type: string; rank: number; name: string }[]; flag_prob: string; computed_at: string; flagged: Flag[]
  }
}
type View = 'final' | 'weak' | 'warning'

/** Students: everyone's final marks, the weak students and why, and the early warning. */
export function StudentsTab({ offering, canEdit }: { offering: OfferingDetail; canEdit: boolean }) {
  const [view, setView] = useState<View>('final')
  const [msg, setMsg] = useState<string | null>(null)
  async function copy(usns: string[]) {
    try { await navigator.clipboard.writeText(usns.join('\n')); setMsg(`${usns.length} USNs copied.`) }
    catch { setMsg(usns.join(', ')) }
  }
  return (
    <div className="stack">
      <div className="filters" style={{ marginBottom: 0 }}>
        <Segmented<View> label="Students view" value={view} onChange={(v) => { setView(v); setMsg(null) }}
                         options={[{ value: 'final', label: 'Final marks' }, { value: 'weak', label: 'Weak students' },
                                   { value: 'warning', label: 'Early warning' }]} />
        <span className="spacer" />
        {msg && <span className="small" role="status">{msg}</span>}
      </div>
      {view === 'final' && <FinalMarks offeringId={offering.offering_id} />}
      {view === 'weak' && <WeakStudents offeringId={offering.offering_id} onCopy={copy} />}
      {view === 'warning' && <EarlyWarning offering={offering} canEdit={canEdit} onCopy={copy} onMessage={setMsg} />}
    </div>
  )
}

function EarlyWarning({ offering, canEdit, onCopy, onMessage }: {
  offering: OfferingDetail; canEdit: boolean; onCopy: (usns: string[]) => void; onMessage: (m: string | null) => void
}) {
  const id = offering.offering_id
  const data = useApi<StudentsData>(`/api/offerings/${id}/students`)
  const [co, setCo] = useState<number | 'all'>('all')
  const [busy, setBusy] = useState(false)
  if (data.error) return <ErrorBox message={data.error} onRetry={data.reload} />
  if (!data.data) return <SkeletonRows rows={4} />
  const d = data.data
  const ew = d.early_warning
  const coNumber = new Map(d.weak.map((w) => [w.co_id, w.co_number]))
  const flags = (ew?.flagged ?? []).filter((f) => co === 'all' || f.co_id === co)

  async function runNow() {
    setBusy(true); onMessage(null)
    try {
      const r = await api<{ flagged: number; predictions: number }>(`/api/offerings/${id}/early-warning`, { method: 'POST' })
      onMessage(`${int(r.flagged)} flagged.`)
      data.reload()
    } catch (e) { onMessage((e as ApiError).message) } finally { setBusy(false) }
  }

  return (
    <section className="panel" aria-labelledby="t-ew">
      <header>
        <h2 id="t-ew">Students at risk</h2>
        <span className="meta">{ew ? `After ${ew.stage.map((s) => s.name).join(', ')} · ${when(ew.computed_at)}` : ''}</span>
      </header>
      {ew && (
        <div className="filters">
          <select className="input" style={{ width: 'auto' }} aria-label="CO" value={co}
                  onChange={(e) => setCo(e.target.value === 'all' ? 'all' : Number(e.target.value))}>
            <option value="all">All COs</option>
            {d.weak.map((w) => <option key={w.co_id} value={w.co_id}>CO{w.co_number}</option>)}
          </select>
          <span className="spacer" />
          {flags.length > 0 && <button className="btn small ghost" onClick={() => onCopy([...new Set(flags.map((f) => f.usn))])}>Copy USNs</button>}
          {canEdit && !d.finished && <button className="btn small" disabled={busy} onClick={runNow}>{busy ? 'Running…' : 'Run again'}</button>}
        </div>
      )}
      {!ew ? (
        <Empty>
          <span>{d.finished ? 'The term is over; see Weak students.' : 'No early warning yet.'}</span>
          {canEdit && !d.finished && <button className="btn small" disabled={busy} onClick={runNow}>{busy ? 'Running…' : 'Run now'}</button>}
        </Empty>
      ) : flags.length === 0 ? <Empty>No student is at risk{co === 'all' ? '' : ` in CO${coNumber.get(co as number)}`}.</Empty> : (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Student</th><th>CO</th><th className="n">Risk</th><th>Why</th></tr></thead>
            <tbody>
              {flags.map((f) => (
                <tr key={`${f.usn}-${f.co_id}`}>
                  <td><span className="id">{f.usn}</span><span className="sub">{f.name}</span></td>
                  <td><span className="id">CO{coNumber.get(f.co_id)}</span></td>
                  <td className="n"><Pill kind={Number(f.probability) >= 0.75 ? 'neg' : 'warn'}>{pct(Number(f.probability) * 100)}</Pill></td>
                  <td className="small">{f.reasons.length ? f.reasons.map((r) => `${r.label} ${pct(r.value)}`).join(' · ') : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
