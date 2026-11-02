import { level, num, pct } from '../format'

export type CoRow = {
  co_id: number; co_number: number; statement: string; pct_attained: string | number | null
  direct_level: number; indirect_level: number; final_level: string | number; target: string | number
}
type Rules = { target_pct: string | number; l1_pct: string | number; l2_pct: string | number; l3_pct: string | number }

/**
 * The CO attainment ladder: each CO's share of students at or above the target mark, against the
 * three level thresholds, with the final level (direct + indirect) at the end of the row.
 */
export function CoLadder({ cos, rules }: { cos: CoRow[]; rules: Rules }) {
  const ticks = [
    { v: num(rules.l1_pct)!, label: `L1 ${num(rules.l1_pct)}%` },
    { v: num(rules.l2_pct)!, label: `L2 ${num(rules.l2_pct)}%` },
    { v: num(rules.l3_pct)!, label: `L3 ${num(rules.l3_pct)}%` },
  ]
  return (
    <div>
      <div className="ladder-scale" aria-hidden="true">
        {ticks.map((t) => <span key={t.label} style={{ left: `${t.v}%` }}>{t.label}</span>)}
      </div>
      <div className="ladder" role="list">
        {cos.map((c) => {
          const p = num(c.pct_attained) ?? 0
          const miss = Number(c.final_level) < Number(c.target)
          return (
            <div className="ladder-row" role="listitem" key={c.co_id}
                 aria-label={`CO${c.co_number}: ${pct(p)} of students reached ${num(rules.target_pct)}%, final level ${level(c.final_level)}`}>
              <span className="co">CO{c.co_number}</span>
              <div style={{ minWidth: 0 }}>
                <div className="stmt" title={c.statement}>{c.statement}</div>
                <div className="track">
                  <div className={`fill ${miss ? 'miss' : ''}`} style={{ width: `${Math.min(100, p)}%` }} />
                  {ticks.map((t) => <div className="tick" key={t.label} style={{ left: `${t.v}%` }} />)}
                </div>
              </div>
              <span className="num" style={{ textAlign: 'right' }}>{pct(p)}</span>
              <span className={`level num ${miss ? 'below' : ''}`}>{level(c.final_level)}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
