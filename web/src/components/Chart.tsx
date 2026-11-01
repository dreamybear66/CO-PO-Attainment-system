import { useEffect, useRef } from 'react'

type Draw = (el: HTMLElement, charts: ChartsApi) => void

/** Hosts one taste-skill chart (public/charts.js); redraws when `deps` change and on resize. */
export function Chart({ draw, deps, label }: { draw: Draw; deps: unknown[]; label: string }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = ref.current
    if (!el || !window.Charts) return
    let width = el.clientWidth
    const render = () => { el.innerHTML = ''; draw(el, window.Charts!) }
    render()
    // redraw on width changes only: a redraw may change the height, which must not loop
    const ro = new ResizeObserver(() => { if (el.clientWidth !== width) { width = el.clientWidth; render() } })
    ro.observe(el)
    return () => ro.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return <div className="chart" ref={ref} aria-label={label} />
}
