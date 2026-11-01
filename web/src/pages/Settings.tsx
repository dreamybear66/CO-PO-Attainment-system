import { useState, type FormEvent } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'
import { Empty, ErrorBox, Pill, SkeletonRows } from '../components/States'
import { COMPONENT, day, int, num, when } from '../format'
import { useApi } from '../hooks'
import type { Config } from './offering/types'

type Version = Config & { results_using: number }
type Verify = {
  ok: boolean; checked: number; first_broken_seq: number | null; reason: string | null
  head: { seq: number; hash: string }; anchors: { seq: number; head_hash: string; anchored_at: string }[]; pending_outbox: number | null
}

export function Settings() {
  const { user } = useAuth()
  return (
    <>
      <div className="title-row">
        <div><h1>Rules and audit</h1><p className="sub">Attainment rules are versioned: every result keeps the version it was computed with. The audit trail is hash-chained and anchored daily.</p></div>
      </div>
      <Versions admin={user?.role === 'admin'} />
      <Audit />
    </>
  )
}

function Versions({ admin }: { admin: boolean }) {
  const v = useApi<Version[]>('/api/configs')
  const latest = v.data?.[0]
  return (
    <div className="settings-row">
      <div>
        <h2>Rule versions</h2>
        <p className="desc">Targets, level thresholds and weights. A new version starts on its date and ends the open one; offerings use the version valid when their term began.</p>
        {latest && <p className="desc small">Current: target {num(latest.target_pct)}%, levels at {num(latest.l3_pct)}/{num(latest.l2_pct)}/{num(latest.l1_pct)}%, weights {num(latest.direct_weight)}/{num(latest.indirect_weight)}.</p>}
      </div>
      <div className="settings-panel">
        {v.error ? <ErrorBox message={v.error} onRetry={v.reload} /> : !v.data ? <SkeletonRows rows={3} /> : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Valid</th><th className="n">Target</th><th className="n">L3 · L2 · L1</th><th className="n">Direct · survey</th><th className="n hide-phone">Components</th><th className="n">Results</th></tr></thead>
              <tbody>
                {v.data.map((c) => (
                  <tr key={c.config_id}>
                    <td>{day(c.valid_from)} – {c.valid_to ? day(c.valid_to) : 'open'}</td>
                    <td className="n num">{num(c.target_pct)}%</td>
                    <td className="n num">{num(c.l3_pct)} · {num(c.l2_pct)} · {num(c.l1_pct)}</td>
                    <td className="n num">{num(c.direct_weight)} · {num(c.indirect_weight)}</td>
                    <td className="n num hide-phone">{Object.values(c.component_weights).join(' · ')}</td>
                    <td className="n num">{int(c.results_using)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {admin && latest && <NewVersion base={latest} onSaved={v.reload} />}
      </div>
    </div>
  )
}

function NewVersion({ base, onSaved }: { base: Version; onSaved: () => void }) {
  const fields = ['target_pct', 'l3_pct', 'l2_pct', 'l1_pct', 'direct_weight', 'indirect_weight', 'co_target_level', 'po_target_level'] as const
  const labels = ['Student target %', 'Level 3 at %', 'Level 2 at %', 'Level 1 at %', 'Direct weight %', 'Survey weight %', 'CO target level', 'PO target level']
  const [form, setForm] = useState<Record<string, string>>(() => ({
    valid_from: '', ...Object.fromEntries(fields.map((f) => [f, String(num(base[f]))])),
    ...Object.fromEntries(Object.entries(base.component_weights).map(([k, w]) => [`w_${k}`, String(w)])),
  }))
  const [msg, setMsg] = useState<string | null>(null)
  async function save(e: FormEvent) {
    e.preventDefault()
    setMsg(null)
    try {
      await api('/api/configs', { body: {
        valid_from: form.valid_from, ...Object.fromEntries(fields.map((f) => [f, Number(form[f])])),
        component_weights: Object.fromEntries(Object.keys(base.component_weights).map((k) => [k, Number(form[`w_${k}`])])),
      } })
      setMsg('Saved. New offerings from that date use this version.')
      onSaved()
    } catch (err) { setMsg((err as Error).message) }
  }
  return (
    <form onSubmit={save} style={{ marginTop: 24 }}>
      <h3 style={{ fontSize: 14, fontWeight: 500, marginBottom: 12 }}>Start a new version</h3>
      <div className="form-grid">
        <div className="field"><label htmlFor="vf">Valid from</label><input id="vf" className="input" type="date" required value={form.valid_from} onChange={(e) => setForm({ ...form, valid_from: e.target.value })} /></div>
        {fields.map((f, i) => (
          <div className="field" key={f}><label htmlFor={f}>{labels[i]}</label>
            <input id={f} className="input num" type="number" step="any" required value={form[f]} onChange={(e) => setForm({ ...form, [f]: e.target.value })} /></div>
        ))}
        {Object.keys(base.component_weights).map((k) => (
          <div className="field" key={k}><label htmlFor={`w_${k}`}>{COMPONENT[k]} %</label>
            <input id={`w_${k}`} className="input num" type="number" step="any" required value={form[`w_${k}`]} onChange={(e) => setForm({ ...form, [`w_${k}`]: e.target.value })} /></div>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 16 }}>
        <button className="btn primary">Save version</button>
        {msg && <span className="small" role="status">{msg}</span>}
      </div>
    </form>
  )
}

function Audit() {
  const [res, setRes] = useState<Verify | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  async function verify() {
    setBusy(true); setErr(null)
    try { setRes(await api<Verify>('/api/audit/verify')) } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <div className="settings-row">
      <div>
        <h2>Audit trail</h2>
        <p className="desc">Every change to marks, mappings, rules and results is a MongoDB document whose hash covers the previous one. Verification recomputes the chain and checks it against the daily anchors kept in PostgreSQL.</p>
      </div>
      <div className="settings-panel">
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          <button className="btn primary" onClick={verify} disabled={busy}>{busy ? 'Verifying…' : 'Verify the chain'}</button>
          {res && (res.ok ? <Pill kind="pos">Intact</Pill> : <Pill kind="neg">Broken at #{res.first_broken_seq}</Pill>)}
        </div>
        {err && <div style={{ marginTop: 12 }}><ErrorBox message={err} /></div>}
        {!res && !err && <div style={{ marginTop: 16 }}><Empty>Run a verification to see the chain's state.</Empty></div>}
        {res && (
          <div className="rows" style={{ marginTop: 12 }}>
            <div className="row"><span className="grow muted">Records checked</span><span className="num">{int(res.checked)}</span></div>
            {!res.ok && <div className="row"><span className="grow muted">Problem</span><span className="below">{res.reason}</span></div>}
            <div className="row"><span className="grow muted">Chain head</span><span className="id">#{int(res.head.seq)} · {res.head.hash.slice(0, 12)}…</span></div>
            {res.pending_outbox !== null && <div className="row"><span className="grow muted">Waiting to be chained</span><span className="num">{int(res.pending_outbox)}</span></div>}
            {res.anchors.map((a) => (
              <div className="row" key={a.seq}><span className="grow muted">Anchor {when(a.anchored_at)}</span><span className="id">#{int(a.seq)} · {a.head_hash.slice(0, 12)}…</span></div>
            ))}
            {res.anchors.length === 0 && <div className="row"><span className="grow muted">Anchors</span><span className="dash">none yet</span></div>}
          </div>
        )}
      </div>
    </div>
  )
}
