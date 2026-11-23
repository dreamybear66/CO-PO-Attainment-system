// The motion layer's shared pieces. Framer Motion (`motion`) drives layout and value animation;
// every piece keeps its content visible without script and drops travel under reduced motion
// (MotionConfig reducedMotion="user" in main.tsx).
import { animate, motion, useInView, useReducedMotion } from 'motion/react'
import { useEffect, useId, useRef, type ReactNode } from 'react'

export const EASE_OUT = [0.22, 1, 0.36, 1] as const
export const SPRING = { type: 'spring', stiffness: 520, damping: 42, mass: 0.9 } as const

/**
 * A figure that counts up to its value when it scrolls into view, and glides between values when it
 * changes (ported from the 21st.dev number ticker). The final text is rendered first, so the markup
 * never shows a wrong number without script.
 */
export function NumberTicker({ value, format = (n) => Math.round(n).toLocaleString('en-IN'), className }: {
  value: number; format?: (n: number) => string; className?: string
}) {
  const ref = useRef<HTMLSpanElement>(null)
  const from = useRef(0)
  const inView = useInView(ref, { once: true, margin: '-40px' })
  const reduce = useReducedMotion()

  useEffect(() => {
    const el = ref.current
    if (!el || !inView) return
    if (reduce) { el.textContent = format(value); from.current = value; return }
    const controls = animate(from.current, value, {
      duration: from.current === 0 ? 1.1 : 0.6, ease: EASE_OUT,
      onUpdate: (v) => { el.textContent = format(v) },
    })
    from.current = value
    return () => controls.stop()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, inView, reduce])

  return <span ref={ref} className={className}>{format(value)}</span>
}

type Option<T> = { value: T; label: ReactNode }

/** Segmented control with a thumb that slides to the pressed option (21st.dev animated tabs). */
export function Segmented<T extends string | number>({ label, options, value, onChange }: {
  label: string; options: Option<T>[]; value: T | null; onChange: (v: T) => void
}) {
  const id = useId()
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={String(o.value)} type="button" aria-pressed={value === o.value} onClick={() => onChange(o.value)}>
          {value === o.value && <motion.span className="thumb" layoutId={`seg${id}`} transition={SPRING} aria-hidden="true" />}
          <span className="label">{o.label}</span>
        </button>
      ))}
    </div>
  )
}

/** Tab strip whose underline slides between tabs. */
export function Tabs<T extends string>({ label, tabs, value, onChange }: {
  label: string; tabs: Record<T, string>; value: T; onChange: (v: T) => void
}) {
  const id = useId()
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {(Object.keys(tabs) as T[]).map((t) => (
        <button key={t} role="tab" type="button" aria-selected={value === t} onClick={() => onChange(t)}>
          {tabs[t]}
          {value === t && <motion.span className="tab-line" layoutId={`tab${id}`} transition={SPRING} aria-hidden="true" />}
        </button>
      ))}
    </div>
  )
}

/** A thin progress meter for "x of y" figures; fills from zero once it is on screen. */
export function Meter({ value, max, tone = 'accent', label }: { value: number; max: number; tone?: 'accent' | 'neg'; label: string }) {
  const share = max > 0 ? Math.min(1, value / max) : 0
  return (
    <div className="meter" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={value}>
      <motion.span className={`meter-fill ${tone}`} initial={{ scaleX: 0 }} animate={{ scaleX: share }}
                   transition={{ duration: 0.9, ease: EASE_OUT, delay: 0.15 }} />
    </div>
  )
}

/** A status line that slides in and out instead of popping. */
export function Notice({ children, kind = 'warn' }: { children: ReactNode; kind?: 'warn' | 'ok' }) {
  return (
    <motion.p className={`note ${kind}`} role="status" layout
              initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}
              transition={{ duration: 0.28, ease: EASE_OUT }}>
      {children}
    </motion.p>
  )
}

/** Small inline spinner for busy buttons. */
export function Spinner() {
  return <span className="spinner" aria-hidden="true" />
}
