import { CoLadder } from '../../components/CoLadder'
import { CoPoMatrix } from '../../components/CoPoMatrix'
import { Empty, ErrorBox, Pill, SkeletonRows } from '../../components/States'
import { COMPONENT, day, int, level, num, pct, signed } from '../../format'
import type { Load } from '../../hooks'
import type { AttainmentData, OfferingDetail } from './types'

export function AttainmentTab({ offering, att, canEdit, onCompute, allLocked }: {
  offering: OfferingDetail; att: Load<AttainmentData>; canEdit: boolean; onCompute: () => void; allLocked: boolean
}) {
  if (att.error) return <ErrorBox message={`Couldn't load attainment. ${att.error}`} onRetry={att.reload} />
  if (!att.data) return <SkeletonRows rows={5} height={24} />
  const { cos, pos, map, actions } = att.data
  const cfg = offering.config

  if (cos.length === 0) {
    return (
      <Empty>
        <span>{allLocked ? 'Every assessment is locked. Attainment has not been computed yet.' : 'Attainment is computed once every assessment is locked.'}</span>
        {canEdit && allLocked && <button className="btn primary" onClick={onCompute}>Compute attainment</button>}
      </Empty>
    )
  }
  const below = cos.filter((c) => Number(c.final_level) < Number(c.target))
  const posBelow = pos.filter((p) => Number(p.attainment) < Number(p.target))
  const own = actions.filter((a) => a.offering_id === offering.offering_id)
  const followed = actions.filter((a) => a.follow_up_offering_id === offering.offering_id)

  return (
    <div className="grid top">
      <section className="panel span-8" aria-labelledby="t-ladder">
        <header>
          <h2 id="t-ladder">CO attainment</h2>
          <span className="meta">{below.length ? `${below.length} of ${cos.length} COs below ${level(cos[0].target)}` : `All ${cos.length} COs at or above ${level(cos[0].target)}`}</span>
        </header>
        <p className="small muted" style={{ marginBottom: 12 }}>
          Bar: share of the <span className="num">{int(cos[0].students)}</span> students scoring at least {cfg ? `${num(cfg.target_pct)}%` : 'the target'} on the CO.
          Ticks mark the level thresholds{cfg ? ` (${num(cfg.l1_pct)}, ${num(cfg.l2_pct)} and ${num(cfg.l3_pct)}%)` : ''}; the figure on the right is the final level ({cfg ? `${num(cfg.direct_weight)}% direct + ${num(cfg.indirect_weight)}% survey` : 'direct + survey'}).
        </p>
        {cfg && <CoLadder cos={cos} rules={cfg} />}
      </section>

      <section className="panel span-4" aria-labelledby="t-rules">
        <header><h2 id="t-rules">Rules used</h2><span className="meta">version from {day(cfg?.valid_from)}</span></header>
        {cfg ? (
          <div className="rows">
            <div className="row"><span className="grow muted">Student target</span><span className="num">{num(cfg.target_pct)}%</span></div>
            <div className="row"><span className="grow muted">Level 3 · 2 · 1 at</span><span className="num">{num(cfg.l3_pct)} · {num(cfg.l2_pct)} · {num(cfg.l1_pct)}%</span></div>
            <div className="row"><span className="grow muted">Direct · survey weight</span><span className="num">{num(cfg.direct_weight)} · {num(cfg.indirect_weight)}%</span></div>
            <div className="row"><span className="grow muted">CO · PO target level</span><span className="num">{level(cfg.co_target_level)} · {level(cfg.po_target_level)}</span></div>
            <div className="row" style={{ alignItems: 'flex-start' }}>
              <span className="grow muted">Components<span className="sub small">{Object.keys(cfg.component_weights).map((k) => COMPONENT[k]).join(' · ')}</span></span>
              <span className="num">{Object.values(cfg.component_weights).join(' · ')}%</span>
            </div>
          </div>
        ) : <Empty>No rule version applies.</Empty>}
      </section>

      <section className="panel span-12" aria-labelledby="t-matrix">
        <header>
          <h2 id="t-matrix">CO-PO matrix</h2>
          <span className="meta">{posBelow.length ? `${posBelow.map((p) => p.code).join(', ')} below ${level(pos[0].target)}` : `All ${pos.length} POs at or above target`}</span>
        </header>
        <CoPoMatrix cos={cos} pos={pos} map={map} />
      </section>

      <section className="panel span-7" aria-labelledby="t-survey">
        <header><h2 id="t-survey">Direct and survey evidence</h2><span className="meta">course-exit survey, rating 4 or 5 counts as favourable</span></header>
        <div className="table-wrap">
          <table>
            <thead><tr><th>CO</th><th className="n">At target</th><th className="n">Direct</th><th className="n">Respondents</th><th className="n">Favourable</th><th className="n">Survey</th><th className="n">Final</th></tr></thead>
            <tbody>
              {cos.map((c) => (
                <tr key={c.co_id}>
                  <td><span className="id">CO{c.co_number}</span></td>
                  <td className="n num">{pct(c.pct_attained)}</td>
                  <td className="n num">{c.direct_level}</td>
                  <td className="n num">{c.respondents ?? <span className="dash">—</span>}</td>
                  <td className="n num">{c.pct_favourable ? pct(c.pct_favourable) : <span className="dash">—</span>}</td>
                  <td className="n num">{c.indirect_level}</td>
                  <td className={`n num ${Number(c.final_level) < Number(c.target) ? 'below' : ''}`}>{level(c.final_level)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel span-5" aria-labelledby="t-actions">
        <header><h2 id="t-actions">Improvement actions</h2><span className="meta">{own.length} for this offering</span></header>
        {own.length === 0 && followed.length === 0 ? <Empty>No CO is below target, so no action is needed.</Empty> : (
          <div className="rows">
            {own.map((a) => (
              <div className="row" key={a.action_id} style={{ alignItems: 'flex-start' }}>
                <span className="id" style={{ width: 40 }}>CO{a.co_number}</span>
                <div className="grow"><div>{a.description}</div>
                  <div className="small muted">{a.source === 'root_cause' ? 'From root-cause analysis' : 'Added when computed'}{a.follow_up_year ? ` · follow-up in ${a.follow_up_year}: ${level(a.level_after)} (${signed(a.change)})` : ''}</div>
                </div>
                <Pill kind={a.status === 'done' ? 'pos' : 'neutral'}>{a.status.replace('_', ' ')}</Pill>
              </div>
            ))}
            {followed.map((a) => (
              <div className="row" key={`f${a.action_id}`} style={{ alignItems: 'flex-start' }}>
                <span className="id" style={{ width: 40 }}>CO{a.co_number}</span>
                <div className="grow"><div>Follow-up of {a.from_year}: {level(a.level_before)} then, {level(a.level_after)} now</div>
                  <div className="small muted truncate" style={{ maxWidth: '100%' }}>{a.description}</div></div>
                <Pill kind={Number(a.change) > 0 ? 'pos' : Number(a.change) < 0 ? 'neg' : 'neutral'}>{signed(a.change)}</Pill>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
