// Figures: fixed decimals per metric, a true minus on changes, a grey dash for what is missing.
const nf2 = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const nf1 = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const nf0 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 })

type Num = number | string | null | undefined
const n = (v: Num) => (v === null || v === undefined || v === '' ? null : Number(v))

export const level = (v: Num) => { const x = n(v); return x === null ? '—' : nf2.format(x) }
export const pct = (v: Num) => { const x = n(v); return x === null ? '—' : `${nf1.format(x)}%` }
export const int = (v: Num) => { const x = n(v); return x === null ? '—' : nf0.format(x) }
export const signed = (v: Num) => {
  const x = n(v)
  if (x === null) return '—'
  if (x === 0) return '0.00'
  return `${x > 0 ? '+' : '−'}${nf2.format(Math.abs(x))}`
}
export const num = n

export function when(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}
export function day(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
}

export const COMPONENT: Record<string, string> = {
  CIE_THEORY: 'CIE theory', CIE_QUIZ: 'CIE quiz', EL: 'Experiential learning', SEE: 'SEE',
}
export const term = (t: string) => (t === 'odd' ? 'Odd term' : 'Even term')
