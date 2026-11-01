/// <reference types="vite/client" />

// public/charts.js (taste-skill chart helper) attaches itself to window.
type ChartFormat = (v: number) => string
interface ChartsApi {
  line(el: HTMLElement, opts: {
    labels: string[]
    series: { name: string; values: (number | null)[] }[]
    format?: ChartFormat
    height?: number
    reference?: { value: number; label: string }
    yTicks?: number[]
    min?: number
    max?: number
  }): unknown
  bars(el: HTMLElement, opts: {
    labels: string[]
    values: number[]
    format?: ChartFormat
    height?: number
    highlight?: number | number[] | null
    dim?: number[]
    reference?: { value: number; label: string }
  }): unknown
  fmt: { int: ChartFormat; dec: (d: number) => ChartFormat; pct: (d?: number) => ChartFormat }
}
interface Window { Charts?: ChartsApi }
