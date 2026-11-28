import { useRef } from 'react'
import { level, num, pct } from '../format'
import { gsap, reducedMotion, useGSAP } from './gsap'
import { Pill } from './States'

export type CoRow = {
  co_id: number; co_number: number; statement: string; pct_attained: string | number | null
  direct_level: number; indirect_level: number; final_level: string | number; target: string | number
}

/** One row per CO: its statement, the share of students who reached it as a bar, and its level,
 *  marked met or below target. */
export function CoLadder({ cos }: { cos: CoRow[] }) {
  const ref = useRef<HTMLDivElement>(null)
  useGSAP(() => {
    if (reducedMotion()) return
    const q = gsap.utils.selector(ref)
    const tl = gsap.timeline()
    tl.from(q('.ladder-row'), { opacity: 0, y: 10, stagger: 0.07, duration: 0.45 })
      .from(q('.fill'), { scaleX: 0, transformOrigin: 'left center', stagger: 0.07, duration: 1, ease: 'expo.out', clearProps: 'transform' }, 0.1)
      .from(q('.level, .pct'), { opacity: 0, x: 6, stagger: 0.07, duration: 0.4 }, 0.45)
  }, { scope: ref, dependencies: [cos] })
  return (
    <div ref={ref}>
      <div className="ladder-head" aria-hidden="true"><span /><span>Outcome</span><span>Students</span><span>Level</span></div>
      <div className="ladder" role="list">
        {cos.map((c) => {
          const p = num(c.pct_attained) ?? 0
          const miss = Number(c.final_level) < Number(c.target)
          return (
            <div className="ladder-row" role="listitem" key={c.co_id}
                 aria-label={`CO${c.co_number}: ${pct(p)} of students, level ${level(c.final_level)}, ${miss ? 'below target' : 'met'}`}>
              <span className="co">CO{c.co_number}</span>
              <div style={{ minWidth: 0 }}>
                <div className="stmt" title={c.statement}>{c.statement}</div>
                <div className="track"><div className={`fill ${miss ? 'miss' : ''}`} style={{ width: `${Math.min(100, p)}%` }} /></div>
              </div>
              <span className="num pct">{pct(p)}</span>
              <span className="level"><span className="num">{level(c.final_level)}</span> <Pill kind={miss ? 'neg' : 'pos'}>{miss ? 'Below' : 'Met'}</Pill></span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
