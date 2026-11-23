import { motion } from 'motion/react'
import { useRef, useState, type FormEvent } from 'react'
import { useAuth } from '../auth'
import { gsap, reducedMotion, useGSAP } from '../components/gsap'
import { EASE_OUT, Spinner } from '../components/motion'
import { Mark } from '../components/Shell'

// An illustrative CO-PO mapping (strength 1-3), drawn as the network the system computes over.
const COS = [1, 2, 3, 4, 5]
const POS = ['PO1', 'PO2', 'PO3', 'PO5', 'PO12', 'PSO1']
const LINKS: [number, number, 1 | 2 | 3][] = [
  [0, 0, 2], [0, 4, 3], [0, 3, 1], [1, 0, 2], [1, 2, 3], [1, 4, 1], [2, 0, 2], [2, 1, 1], [2, 2, 3], [2, 5, 2],
  [3, 0, 3], [3, 1, 2], [3, 4, 2], [4, 0, 2], [4, 4, 2], [4, 5, 1],
]
const W = 440, H = 360
const coY = (i: number) => 40 + i * ((H - 80) / (COS.length - 1))
const poY = (i: number) => 30 + i * ((H - 60) / (POS.length - 1))
const X1 = 64, X2 = W - 76

function Network() {
  const ref = useRef<SVGSVGElement>(null)
  useGSAP(() => {
    if (reducedMotion()) return
    const q = gsap.utils.selector(ref)
    const tl = gsap.timeline({ delay: 0.2 })
    tl.from(q('.n-co'), { scale: 0, transformOrigin: 'center', stagger: 0.06, duration: 0.5, ease: 'back.out(2)' })
      .from(q('.n-po'), { scale: 0, transformOrigin: 'center', stagger: 0.05, duration: 0.5, ease: 'back.out(2)' }, '<0.1')
      .from(q('.n-label'), { opacity: 0, x: (_: number, el: Element) => (el.classList.contains('right') ? 8 : -8), stagger: 0.03, duration: 0.4 }, '<0.2')
      .fromTo(q('.link'), { strokeDashoffset: 1 }, { strokeDashoffset: 0, duration: 0.9, stagger: 0.04, ease: 'power2.inOut' }, '<')
    // pulses: a mark travels each link, CO to PO, on a loose loop
    q('.pulse').forEach((p: Element, i: number) => {
      const [c, o] = LINKS[i]
      gsap.fromTo(p, { attr: { cx: X1, cy: coY(c) }, opacity: 0 }, {
        attr: { cx: X2, cy: poY(o) }, keyframes: { opacity: [0, 1, 1, 0] },
        duration: 2.2, ease: 'none', repeat: -1, repeatDelay: 1.6 + (i % 5) * 0.7, delay: 1.6 + i * 0.27,
      })
    })
  }, { scope: ref })

  return (
    <svg ref={ref} viewBox={`0 0 ${W} ${H}`} className="network" role="img"
         aria-label="Course outcomes CO1 to CO5 mapped to programme outcomes with strengths from 1 to 3">
      {LINKS.map(([c, o, s], i) => (
        <line key={i} className={`link s${s}`} x1={X1} y1={coY(c)} x2={X2} y2={poY(o)} pathLength={1} />
      ))}
      {LINKS.map((_, i) => <circle key={`p${i}`} className="pulse" r={2.5} cx={X1} cy={-10} />)}
      {COS.map((n, i) => (
        <g key={n}>
          <circle className="n-co" cx={X1} cy={coY(i)} r={7} />
          <text className="n-label" x={X1 - 16} y={coY(i) + 4} textAnchor="end">CO{n}</text>
        </g>
      ))}
      {POS.map((p, i) => (
        <g key={p}>
          <circle className="n-po" cx={X2} cy={poY(i)} r={9} />
          <text className="n-label right" x={X2 + 18} y={poY(i) + 4}>{p}</text>
        </g>
      ))}
    </svg>
  )
}

const rise = {
  hidden: { opacity: 0, y: 14 },
  show: (i: number) => ({ opacity: 1, y: 0, transition: { delay: 0.08 + i * 0.06, duration: 0.5, ease: EASE_OUT } }),
}

export function Login() {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try { await login(username, password) } catch (err) { setError((err as Error).message) } finally { setBusy(false) }
  }

  return (
    <div className="login">
      <section className="login-art" aria-labelledby="login-title">
        <div className="brand on-dark">
          <Mark />
          <div><b>CO-PO Attainment</b><span>Dept. of ISE · RVCE</span></div>
        </div>
        <Network />
        <div className="login-copy">
          <h1 id="login-title">Every mark, traced to an outcome</h1>
          <p>Question-wise marks and course-exit surveys become CO levels, then programme outcomes, under the rules your department sets.</p>
        </div>
      </section>

      <div className="login-side">
        <motion.form onSubmit={submit} aria-describedby={error ? 'login-error' : undefined} initial="hidden" animate="show">
          <motion.div variants={rise} custom={0}>
            <h2>Sign in</h2>
            <p className="muted" style={{ marginTop: 4 }}>Faculty use their staff ID, students their USN.</p>
          </motion.div>
          <motion.div className="field" variants={rise} custom={1}>
            <label htmlFor="u">Username</label>
            <input id="u" className="input" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
          </motion.div>
          <motion.div className="field" variants={rise} custom={2}>
            <label htmlFor="p">Password</label>
            <input id="p" className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </motion.div>
          {error && (
            <motion.div id="login-error" className="error-box" role="alert"
                        initial={{ opacity: 0, x: 0 }} animate={{ opacity: 1, x: [0, -6, 6, -4, 4, 0] }} transition={{ duration: 0.4 }}>
              {error}
            </motion.div>
          )}
          <motion.button className="btn primary big" type="submit" disabled={busy} variants={rise} custom={3} whileTap={{ scale: 0.98 }}>
            {busy ? <><Spinner />Signing in…</> : 'Sign in'}
          </motion.button>
        </motion.form>
      </div>
    </div>
  )
}
