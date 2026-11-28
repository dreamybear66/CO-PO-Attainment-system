import { CoLadder } from '../../components/CoLadder'
import { Empty, ErrorBox, Pill, SkeletonRows } from '../../components/States'
import { int, level, signed } from '../../format'
import type { Load } from '../../hooks'
import type { AttainmentData, OfferingDetail } from './types'

export function AttainmentTab({ offering, att, canEdit, onCompute, allLocked }: {
  offering: OfferingDetail; att: Load<AttainmentData>; canEdit: boolean; onCompute: () => void; allLocked: boolean
}) {
  if (att.error) return <ErrorBox message={`Couldn't load attainment. ${att.error}`} onRetry={att.reload} />
  if (!att.data) return <SkeletonRows rows={5} height={24} />
  const { cos, pos, actions } = att.data

  if (cos.length === 0) {
    return (
      <Empty>
        <span>{allLocked ? 'Attainment has not been computed yet.' : 'Lock every assessment to compute attainment.'}</span>
        {canEdit && allLocked && <button className="btn primary" onClick={onCompute}>Compute attainment</button>}
      </Empty>
    )
  }
  const coMet = cos.filter((c) => Number(c.final_level) >= Number(c.target)).length
  const poMet = pos.filter((p) => Number(p.attainment) >= Number(p.target)).length
  const own = actions.filter((a) => a.offering_id === offering.offering_id)
  const followed = actions.filter((a) => a.follow_up_offering_id === offering.offering_id)

  return (
    <div className="stack">
      <div className="kpis">
        <div className="kpi"><div className="kpi-label">COs met</div><div className="kpi-value">{coMet}<small>of {cos.length}</small></div></div>
        <div className="kpi"><div className="kpi-label">POs met</div><div className="kpi-value">{poMet}<small>of {pos.length}</small></div></div>
        <div className="kpi"><div className="kpi-label">Students</div><div className="kpi-value">{int(cos[0].students)}</div></div>
      </div>

      <div className="grid top">
        <section className="panel span-7" aria-labelledby="t-co">
          <header><h2 id="t-co">CO attainment</h2><span className="meta">Target level {level(cos[0].target)}</span></header>
          <CoLadder cos={cos} />
        </section>

        <section className="panel span-5" aria-labelledby="t-po">
          <header><h2 id="t-po">PO attainment</h2>{pos.length > 0 && <span className="meta">Target level {level(pos[0].target)}</span>}</header>
          {pos.length === 0 ? <Empty>No PO is mapped to this course.</Empty> : (
            <div className="rows">
              {pos.map((p) => {
                const miss = Number(p.attainment) < Number(p.target)
                return (
                  <div className="row" key={p.po_id}>
                    <span className="id" style={{ width: 48 }}>{p.code}</span>
                    <span className="grow small muted truncate" title={p.statement}>{p.statement}</span>
                    <span className="num">{level(p.attainment)}</span>
                    <Pill kind={miss ? 'neg' : 'pos'}>{miss ? 'Below' : 'Met'}</Pill>
                  </div>
                )
              })}
            </div>
          )}
        </section>

        <section className="panel span-12" aria-labelledby="t-actions">
          <header><h2 id="t-actions">Improvement actions</h2>{own.length > 0 && <span className="meta">{own.length} for this offering</span>}</header>
          {own.length === 0 && followed.length === 0 ? <Empty>Every CO met its target.</Empty> : (
            <div className="rows">
              {own.map((a) => (
                <div className="row" key={a.action_id} style={{ alignItems: 'flex-start' }}>
                  <span className="id" style={{ width: 40 }}>CO{a.co_number}</span>
                  <div className="grow"><div>{a.description}</div>
                    {a.follow_up_year && <div className="small muted">{a.follow_up_year}: {level(a.level_after)} ({signed(a.change)})</div>}
                  </div>
                  <Pill kind={a.status === 'done' ? 'pos' : 'neutral'}>{a.status.replace('_', ' ')}</Pill>
                </div>
              ))}
              {followed.map((a) => (
                <div className="row" key={`f${a.action_id}`} style={{ alignItems: 'flex-start' }}>
                  <span className="id" style={{ width: 40 }}>CO{a.co_number}</span>
                  <div className="grow"><div>Action from {a.from_year}: {level(a.level_before)} then, {level(a.level_after)} now</div>
                    <div className="small muted truncate" style={{ maxWidth: '100%' }}>{a.description}</div></div>
                  <Pill kind={Number(a.change) > 0 ? 'pos' : Number(a.change) < 0 ? 'neg' : 'neutral'}>{signed(a.change)}</Pill>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
