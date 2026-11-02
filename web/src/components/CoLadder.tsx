import { useRef } from 'react'
import { level, num, pct } from '../format'
import { gsap, reducedMotion, useGSAP } from './gsap'

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
  const ref = useRef<HTMLDivElement>(null)
  useGSAP(() => {
    if (reducedMotion()) return
    const q = gsap.utils.selector(ref)
    const tl = gsap.timeline()
    tl.from(q('.ladder-row'), { opacity: 0, y: 10, stagger: 0.07, duration: 0.45 })
      .from(q('.fill'), { scaleX: 0, transformOrigin: 'left center', stagger: 0.07, duration: 1, ease: 'expo.out', clearProps: 'transform' }, 0.1)
      .from(q('.tick'), { scaleY: 0, stagger: 0.02, duration: 0.3 }, 0.3)
      .from(q('.level, .pct'), { opacity: 0, x: 6, stagger: 0.07, duration: 0.4 }, 0.45)
  }, { scope: ref, dependencies: [cos] })
  return (
    <div ref={ref}>
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
              <span className="num pct" style={{ textAlign: 'right' }}>{pct(p)}</span>
              <span className={`level num ${miss ? 'below' : ''}`}>{level(c.final_level)}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
