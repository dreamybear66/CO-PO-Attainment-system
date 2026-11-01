import { useState, type FormEvent } from 'react'
import { api } from '../../api'
import { Empty, Pill } from '../../components/States'
import { level, num } from '../../format'
import type { OfferingDetail } from './types'

type Compare = {
  targets: { baseline: { co: string; po: string }; scenario: { co: string; po: string } }
  cos: { co_id: number; co_number: number; baseline: string; scenario: string; change: string | null }[]
  pos: { po_id: number; code: string; baseline: string; scenario: string; change: string | null }[]
}
const FIELDS = [
  ['target_pct', 'Student target', '%'], ['l3_pct', 'Level 3 at', '%'], ['l2_pct', 'Level 2 at', '%'], ['l1_pct', 'Level 1 at', '%'],
  ['direct_weight', 'Direct weight', '%'], ['indirect_weight', 'Survey weight', '%'], ['co_target_level', 'CO target level', ''], ['po_target_level', 'PO target level', ''],
] as const
type Key = (typeof FIELDS)[number][0]

export function WhatIfTab({ offering, computed, canEdit }: { offering: OfferingDetail; computed: boolean; canEdit: boolean }) {
  const cfg = offering.config
  const [values, setValues] = useState<Record<Key, string>>(() =>
    Object.fromEntries(FIELDS.map(([k]) => [k, cfg ? String(num(cfg[k])) : ''])) as Record<Key, string>)
  const [result, setResult] = useState<Compare | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (!computed) return <Empty>Compute the official attainment first; a scenario is compared against it.</Empty>
  if (!canEdit) return <Empty>Scenarios are run by the course faculty and the HoD.</Empty>

  const sum = Number(values.direct_weight) + Number(values.indirect_weight)
  async function run(e: FormEvent) {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      const body = Object.fromEntries(FIELDS.map(([k]) => [k, Number(values[k])]))
      setResult(await api<Compare>(`/api/offerings/${offering.offering_id}/whatif`, { body: { name: 'Scenario', ...body } }))
    } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }
  const change = (c: string | null) => c === 'now meets' ? <Pill kind="pos">Now meets</Pill> : c === 'now misses' ? <Pill kind="neg">Now misses</Pill> : <span className="dash">—</span>

  return (
    <div className="stack">
      <section className="panel" aria-labelledby="t-rules">
        <header><h2 id="t-rules">Try different rules</h2><span className="meta">official results are not changed</span></header>
        <form onSubmit={run}>
          <div className="form-grid">
            {FIELDS.map(([k, label, unit]) => (
              <div className="field" key={k}>
                <label htmlFor={k}>{label}{unit && <span className="muted"> ({unit})</span>}</label>
                <input id={k} className="input num" type="number" step="any" min={0} max={unit ? 100 : 3} required
                       value={values[k]} onChange={(e) => setValues({ ...values, [k]: e.target.value })} />
              </div>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginTop: 16 }}>
            <button className="btn primary" disabled={busy || sum !== 100}>{busy ? 'Running…' : 'Run scenario'}</button>
            {sum !== 100 && <span className="small below">Direct and survey weights must add up to 100 (now {sum}).</span>}
            {error && <span className="small below" role="alert">{error}</span>}
          </div>
        </form>
      </section>

      {result && (
        <div className="grid top">
          <section className="panel span-6" aria-labelledby="t-wco">
            <header><h2 id="t-wco">COs</h2><span className="meta">target {level(result.targets.baseline.co)} → {level(result.targets.scenario.co)}</span></header>
            <table>
              <thead><tr><th>CO</th><th className="n">Official</th><th className="n">Scenario</th><th className="n">Change</th></tr></thead>
              <tbody>{result.cos.map((c) => (
                <tr key={c.co_id}><td><span className="id">CO{c.co_number}</span></td><td className="n num">{level(c.baseline)}</td><td className="n num">{level(c.scenario)}</td><td className="n">{change(c.change)}</td></tr>
              ))}</tbody>
            </table>
          </section>
          <section className="panel span-6" aria-labelledby="t-wpo">
            <header><h2 id="t-wpo">POs</h2><span className="meta">{result.pos.filter((p) => p.change).length} change status</span></header>
            <table>
              <thead><tr><th>PO</th><th className="n">Official</th><th className="n">Scenario</th><th className="n">Change</th></tr></thead>
              <tbody>{result.pos.map((p) => (
                <tr key={p.po_id}><td><span className="id">{p.code}</span></td><td className="n num">{level(p.baseline)}</td><td className="n num">{level(p.scenario)}</td><td className="n">{change(p.change)}</td></tr>
              ))}</tbody>
            </table>
          </section>
        </div>
      )}
    </div>
  )
}
