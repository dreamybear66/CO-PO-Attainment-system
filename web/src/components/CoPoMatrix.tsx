import { level } from '../format'
import type { CoRow } from './CoLadder'

export type PoRow = { po_id: number; code: string; type: string; statement: string; attainment: string | number; target: string | number }
export type MapCell = { co_id: number; po_id: number; strength: number }

/** CO x PO: mapping strength as a one-hue tint, each CO's final level, each PO's attainment below. */
export function CoPoMatrix({ cos, pos, map }: { cos: CoRow[]; pos: PoRow[]; map: MapCell[] }) {
  const strength = new Map(map.map((m) => [`${m.co_id}:${m.po_id}`, m.strength]))
  return (
    <div className="table-wrap">
      <table className="matrix">
        <caption className="visually-hidden">CO-PO mapping strengths with CO final levels and PO attainment</caption>
        <thead>
          <tr>
            <th scope="col">CO</th>
            {pos.map((p) => <th scope="col" key={p.po_id} title={p.statement}><span className="id">{p.code}</span></th>)}
            <th scope="col" className="n">CO level</th>
          </tr>
        </thead>
        <tbody>
          {cos.map((c) => (
            <tr key={c.co_id}>
              <th scope="row" style={{ fontWeight: 400, color: 'var(--text)' }}><span className="id">CO{c.co_number}</span></th>
              {pos.map((p) => {
                const s = strength.get(`${c.co_id}:${p.po_id}`)
                return <td key={p.po_id} className={s ? `cell s${s}` : 'cell'} aria-label={s ? `strength ${s}` : 'not mapped'}>{s ?? ''}</td>
              })}
              <td className={`n num ${Number(c.final_level) < Number(c.target) ? 'below' : ''}`}>{level(c.final_level)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td>PO value</td>
            {pos.map((p) => (
              <td key={p.po_id} className={`num ${Number(p.attainment) < Number(p.target) ? 'below' : ''}`}>{level(p.attainment)}</td>
            ))}
            <td />
          </tr>
        </tfoot>
      </table>
      <p className="small muted" style={{ marginTop: 10 }}>
        Mapping strength
        <span className="key"><i style={{ background: 'rgba(27,108,128,.1)' }} />1 low</span>
        <span className="key"><i style={{ background: 'rgba(27,108,128,.22)' }} />2 medium</span>
        <span className="key"><i style={{ background: 'rgba(27,108,128,.38)' }} />3 high</span>
        <span className="key">Values in red are below target.</span>
      </p>
    </div>
  )
}
