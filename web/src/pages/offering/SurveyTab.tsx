import { useState } from 'react'
import { api, ApiError } from '../../api'
import { Empty, ErrorBox, Pill, SkeletonRows } from '../../components/States'
import { int, pct, when } from '../../format'
import { useApi } from '../../hooks'
import type { OfferingDetail } from './types'

type Sync = { read: number; accepted: number; already: number; rejected: Record<string, number> }
type FormInfo = {
  form_id: string; responder_uri: string; edit_uri: string; created_at: string
  last_synced_at: string | null; last_sync: Sync | null; mine: boolean
}
type CoRow = { co_id: number; co_number: number; statement: string; counts: number[]; favourable_pct: number | null }
type SurveyData = {
  form: FormInfo | null; google_configured: boolean
  dashboard: { enrolled: number; responses: number; yet_to_respond: number; response_rate: number | null
    finished: boolean; favourable_rating: number; cos: CoRow[] }
}
type GoogleStatus = { configured: boolean; connected: boolean; email: string | null }

/** Course-exit survey as a Google Form: create it, share it on WhatsApp, fetch and read responses. */
export function SurveyTab({ offering, canEdit }: { offering: OfferingDetail; canEdit: boolean }) {
  const id = offering.offering_id
  const data = useApi<SurveyData>(`/api/offerings/${id}/survey-form`)
  const google = useApi<GoogleStatus>(canEdit ? '/api/google/status' : null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const level2 = Number(offering.config?.l2_pct ?? 60)     // the share that earns level 2 under the rules

  if (data.error) return <ErrorBox message={data.error} onRetry={data.reload} />
  if (!data.data) return <SkeletonRows rows={4} />
  const { form, dashboard: d } = data.data

  async function run(fn: () => Promise<unknown>) {
    setBusy(true); setMsg(null)
    try { await fn() } catch (e) { setMsg((e as ApiError).message) } finally { setBusy(false) }
  }
  const connect = () => run(async () => {
    const r = await api<{ url: string }>(`/api/google/connect?return_to=${encodeURIComponent(`/offerings/${id}?tab=survey`)}`)
    window.location.assign(r.url)
  })
  const disconnect = () => run(async () => { await api('/api/google/disconnect', { method: 'POST' }); google.reload() })
  const create = () => run(async () => { await api(`/api/offerings/${id}/survey-form`, { method: 'POST' }); data.reload() })
  const fetchNow = () => run(async () => {
    const s = await api<Sync>(`/api/offerings/${id}/survey-form/sync`, { method: 'POST' })
    const turned = Object.values(s.rejected).reduce((a, b) => a + b, 0)
    setMsg(`Read ${s.read} response${s.read === 1 ? '' : 's'}: ${s.accepted} new, ${s.already} already saved${turned ? `, ${turned} turned away` : ''}.`)
    data.reload()
  })

  const share = form && `Course-exit survey for ${offering.code} ${offering.title} (${offering.academic_year}, section ${offering.section}). ` +
    `Please fill it in with your college email and USN: ${form.responder_uri}`
  async function copy() {
    if (!form) return
    try { await navigator.clipboard.writeText(form.responder_uri); setCopied(true); setTimeout(() => setCopied(false), 1500) }
    catch { setMsg(`Copy this link: ${form.responder_uri}`) }
  }

  return (
    <div className="stack">
      <section className="panel" aria-labelledby="t-form">
        <header>
          <h2 id="t-form">Course-exit survey form</h2>
          {form && <span className="meta">Created {when(form.created_at)}</span>}
        </header>

        {!form && !canEdit && <Empty>No survey form has been created for this offering yet.</Empty>}
        {!form && canEdit && !data.data.google_configured && (
          <p className="note">Google is not set up on this server yet. Follow “Google Forms surveys (setup, once)” in the README, then restart the API.</p>
        )}
        {!form && canEdit && data.data.google_configured && google.data && (
          <div className="survey-steps">
            <div>
              <span className="step-no">1</span>
              {google.data.connected
                ? <span>Connected to Google as <strong>{google.data.email}</strong>. <button className="btn small ghost" disabled={busy} onClick={disconnect}>Disconnect</button></span>
                : <span>Connect your Google account. <button className="btn small" disabled={busy} onClick={connect}>Connect Google</button></span>}
            </div>
            <div>
              <span className="step-no">2</span>
              <span>Create the form.{' '}
                <button className="btn small primary" disabled={busy || !google.data.connected} onClick={create}>Create the survey form</button></span>
            </div>
          </div>
        )}

        {form && (
          <>
            <div className="survey-link">
              <input className="input" readOnly value={form.responder_uri} aria-label="Link students open" onFocus={(e) => e.target.select()} />
              <button className="btn small" onClick={copy}>{copied ? 'Copied' : 'Copy link'}</button>
              <a className="btn small primary" href={`https://wa.me/?text=${encodeURIComponent(share ?? '')}`} target="_blank" rel="noreferrer">Share on WhatsApp</a>
              {form.mine && <a className="btn small ghost" href={form.edit_uri} target="_blank" rel="noreferrer">Open in Google Forms</a>}
            </div>
            <div className="filters" style={{ marginTop: 12, marginBottom: 0 }}>
              {form.mine && <button className="btn small" disabled={busy} onClick={fetchNow}>{busy ? 'Fetching…' : 'Fetch responses'}</button>}
              <span className="small muted">
                {form.last_synced_at ? `Last fetched ${when(form.last_synced_at)}` : 'Not fetched yet'}
                {form.last_sync && ` · ${form.last_sync.read} in the form, ${form.last_sync.accepted} new last time`}
              </span>
            </div>
            {form.last_sync && Object.keys(form.last_sync.rejected).length > 0 && (
              <div className="note" style={{ marginTop: 12, marginBottom: 0 }}>
                Turned away last time: {Object.entries(form.last_sync.rejected).map(([why, n]) => `${why} (${n})`).join(' · ')}
              </div>
            )}
          </>
        )}
        {msg && <p className="small" role="status" style={{ marginTop: 12 }}>{msg}</p>}
      </section>

      <section className="panel" aria-labelledby="t-dash">
        <header>
          <h2 id="t-dash">Responses</h2>
        </header>
        <div className="kpis">
          <div className="kpi"><div className="kpi-label">Answered</div><div className="kpi-value">{int(d.responses)}<small>of {int(d.enrolled)}</small></div></div>
          <div className="kpi"><div className="kpi-label">Response rate</div><div className="kpi-value">{pct(d.response_rate)}</div></div>
          <div className="kpi"><div className="kpi-label">Yet to respond</div><div className="kpi-value">{int(d.yet_to_respond)}</div></div>
        </div>
        {d.responses === 0 ? <Empty>No responses yet. Share the form, then fetch the responses.</Empty> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>CO</th><th>Ratings 1 → 5</th><th className="n">Favourable</th></tr></thead>
              <tbody>
                {d.cos.map((c) => {
                  const total = c.counts.reduce((a, b) => a + b, 0)
                  return (
                    <tr key={c.co_id}>
                      <td><span className="id">CO{c.co_number}</span><span className="sub">{c.statement}</span></td>
                      <td style={{ minWidth: 220 }}>
                        <div className="rating-bar" role="img" aria-label={`CO${c.co_number}: ${c.counts.map((n, i) => `${n} rated ${i + 1}`).join(', ')}`}>
                          {c.counts.map((n, i) => n > 0 && <span key={i} className={`r${i + 1}`} style={{ flexGrow: n }} title={`${n} rated ${i + 1}`}>{n / total >= 0.08 ? n : ''}</span>)}
                        </div>
                      </td>
                      <td className="n num">{c.favourable_pct === null ? '—' : <Pill kind={c.favourable_pct >= level2 ? 'pos' : 'warn'}>{pct(c.favourable_pct)}</Pill>}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
