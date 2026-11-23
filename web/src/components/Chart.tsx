import { useEffect, useRef } from 'react'
import { gsap, reducedMotion } from './gsap'

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
    animateIn(el)
    // redraw on width changes only: a redraw may change the height, which must not loop
    const ro = new ResizeObserver(() => { if (el.clientWidth !== width) { width = el.clientWidth; render() } })
    ro.observe(el)
    return () => ro.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return <div className="chart" ref={ref} aria-label={label} />
}

/** First draw only: data lines trace from the left, bars grow from the baseline, marks pop in. */
function animateIn(el: HTMLElement) {
  if (reducedMotion()) return
  const svg = el.querySelector('svg')
  if (!svg) return
  const lines = [...svg.querySelectorAll<SVGPathElement>('path')].filter((p) => p.getAttribute('fill') === 'none' && p.getTotalLength() > 40)
  lines.forEach((p) => {
    const len = p.getTotalLength()
    gsap.fromTo(p, { strokeDasharray: len, strokeDashoffset: len }, { strokeDashoffset: 0, duration: 1.2, ease: 'power2.inOut',
      onComplete: () => { p.style.strokeDasharray = ''; p.style.strokeDashoffset = '' } })
  })
  const bars = [...svg.querySelectorAll<SVGRectElement>('rect')].filter((r) => Number(r.getAttribute('height')) > 2 && r.getAttribute('fill') !== 'transparent')
  gsap.from(bars, { scaleY: 0, transformOrigin: '50% 100%', stagger: 0.05, duration: 0.8, ease: 'expo.out' })
  gsap.from(svg.querySelectorAll('circle'), { scale: 0, transformOrigin: '50% 50%', stagger: 0.08, duration: 0.4, delay: 0.6, ease: 'back.out(2)' })
}
