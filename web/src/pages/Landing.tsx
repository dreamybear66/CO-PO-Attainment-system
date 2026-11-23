import { useEffect, useId, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Mark } from '../components/Shell'
import '../landing.css'

/* Public landing page, written for teachers and heads of department, not developers: no database,
   code or test talk. One motif, the attainment staircase (levels 0-3, reached at 50, 60 and 70 % of
   students): the hero shape, the button corner, the list bullet, the picture frame and the footer.
   Cursor effects (tilt, light, magnet, parallax) run only with a mouse or trackpad, and not at all
   when the visitor asks for reduced motion. */

// The department's current rules; the calculator uses exactly these.
const L1 = 50, L2 = 60, L3 = 70, DIRECT = 80, SURVEY = 20
const toLevel = (pct: number) => (pct >= L3 ? 3 : pct >= L2 ? 2 : pct >= L1 ? 1 : 0)

/** Staircase silhouette: three treads rising left to right. */
function Stairs({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 300 300" preserveAspectRatio="none" aria-hidden="true">
      <path d="M0 300V200H100V100H200V0H300V300Z" />
    </svg>
  )
}

function Bullet() {
  return <svg className="lp-bullet" viewBox="0 0 12 12" aria-hidden="true"><path d="M0 12V8h4V4h4V0h4v12Z" /></svg>
}

/** Adds .is-in to [data-reveal] blocks as they enter; children stagger by --i. */
function useReveal(root: React.RefObject<HTMLElement>) {
  useEffect(() => {
    const el = root.current
    if (!el) return
    const blocks = [...el.querySelectorAll<HTMLElement>('[data-reveal]')]
    if (!('IntersectionObserver' in window)) { blocks.forEach((b) => b.classList.add('is-in')); return }
    el.classList.add('lp-anim')
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => { if (e.isIntersecting) { e.target.classList.add('is-in'); io.unobserve(e.target) } })
    }, { rootMargin: '0px 0px -10% 0px' })
    blocks.forEach((b) => io.observe(b))
    return () => io.disconnect()
  }, [root])
}

/** Smooth scrolling for the in-page links while the landing page is shown. */
function useSmoothScroll() {
  useEffect(() => {
    const html = document.documentElement
    const before = html.style.scrollBehavior
    if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) html.style.scrollBehavior = 'smooth'
    return () => { html.style.scrollBehavior = before }
  }, [])
}

const FX = ['tilt', 'glow', 'magnet', 'track'] as const

/** Cursor effects. Elements marked data-tilt, data-glow, data-magnet or data-track get the pointer
    position as CSS variables (--px/--py from -0.5 to 0.5, --mx/--my in pixels) and the class
    .is-hot while the pointer is over them; landing.css turns those into tilt, a following light,
    a small pull toward the cursor and parallax. One listener, one update per frame. */
function usePointerFx(root: React.RefObject<HTMLElement>) {
  useEffect(() => {
    const el = root.current
    if (!el) return
    const fine = window.matchMedia('(hover: hover) and (pointer: fine)').matches
    const calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (!fine || calm) return
    let frame = 0
    let last: PointerEvent | null = null
    let active = new Set<HTMLElement>()
    const reset = (t: HTMLElement) => {
      t.classList.remove('is-hot')
      for (const v of ['--px', '--py', '--mx', '--my']) t.style.removeProperty(v)
    }
    const apply = () => {
      frame = 0
      if (!last) return
      const hit = new Set<HTMLElement>()
      for (let n = last.target as HTMLElement | null; n && n !== el; n = n.parentElement) {
        if (FX.some((k) => n!.dataset?.[k] !== undefined)) hit.add(n)
      }
      active.forEach((t) => { if (!hit.has(t)) reset(t) })
      hit.forEach((t) => {
        const r = t.getBoundingClientRect()
        const x = last!.clientX - r.left, y = last!.clientY - r.top
        t.style.setProperty('--px', (x / r.width - 0.5).toFixed(3))
        t.style.setProperty('--py', (y / r.height - 0.5).toFixed(3))
        t.style.setProperty('--mx', `${x.toFixed(0)}px`)
        t.style.setProperty('--my', `${y.toFixed(0)}px`)
        t.classList.add('is-hot')
      })
      active = hit
    }
    const move = (e: PointerEvent) => { last = e; if (!frame) frame = requestAnimationFrame(apply) }
    const leave = () => { last = null; active.forEach(reset); active = new Set() }
    el.addEventListener('pointermove', move)
    el.addEventListener('pointerleave', leave)
    return () => {
      el.removeEventListener('pointermove', move)
      el.removeEventListener('pointerleave', leave)
      cancelAnimationFrame(frame)
    }
  }, [root])
}

const STEPS = [
  {
    name: 'Marks go in',
    text: 'Scan the answer sheets of a test as one PDF: the quiz and the test are read together, and anything unclear is highlighted for a quick check. Experiential-learning marks are typed straight in. Every question is linked to the course outcome it tests, so each student gets a score for each outcome. An absent student counts as zero.',
    pic: { src: '/landing/marks.webp', w: 1600, h: 736, alt: 'A course with all six assessments entered and locked' },
  },
  {
    name: 'Each outcome gets a level',
    text: `For every outcome, the system counts how many students scored at least 60 %. If ${L3} % of the class did, the outcome is at level 3; ${L2} % gives level 2, ${L1} % level 1, fewer gives 0.`,
    pic: { src: '/landing/ladder.webp', w: 1058, h: 530, alt: 'Each course outcome as a bar, with the 50, 60 and 70 % marks shown' },
  },
  {
    name: 'Students have their say',
    text: 'At the end of the course, students rate each outcome in a short survey that the teacher shares on WhatsApp. Their answers give a second, student-side level for every outcome.',
    pic: { src: '/landing/evidence.webp', w: 920, h: 504, alt: 'For each outcome: students at target, how many answered the survey and how many rated it highly' },
  },
  {
    name: 'One final level per outcome',
    text: `Marks count for ${DIRECT} % and student feedback for ${SURVEY} %. The result is one clear number from 0 to 3 for every course outcome, worked out the same way for every teacher.`,
  },
  {
    name: 'Programme outcomes follow',
    text: 'Each course outcome feeds the programme outcomes it supports, weighted by how strongly it supports them. The department sees, course by course, where its graduates stand.',
    pic: { src: '/landing/matrix.webp', w: 1600, h: 544, alt: 'A grid linking course outcomes to programme outcomes, with each programme outcome’s level below' },
  },
]

const SCREENS = [
  {
    name: 'Find the reason', src: '/landing/rootcause.webp', w: 1600, h: 411, stage: 'var(--lp-field-1)',
    alt: 'For a weak outcome, the earlier topics most likely behind it, strongest first',
    fact: 'Database Management Systems outcome 4 dropped sharply in 2024-25. Looking back at what those same students did earlier, the system points to a topic from Data Structures, and rules out an unrelated one.',
  },
  {
    name: 'See it over the years', src: '/landing/trend.webp', w: 1056, h: 468, stage: 'var(--lp-field-3)',
    alt: 'One outcome’s level across four years, dipping below target in 2024-25',
    fact: 'The same outcome across four years: strong, then a dip for one batch, then back on target the year after.',
  },
  {
    name: 'Act on it', src: '/landing/actions.webp', w: 650, h: 541, stage: 'var(--lp-field-2)',
    alt: 'A list of improvement actions, each with how the next year turned out',
    fact: 'Every outcome below target gets an improvement action straight away, and next year’s results show whether it worked.',
  },
  {
    name: 'Try a change first', src: '/landing/whatif.webp', w: 1600, h: 380, stage: 'var(--lp-field-1)',
    alt: 'A form to try a different target, levels or weights',
    fact: 'Wondering what a different target would do? Try it on any course and compare. The official results never change.',
  },
  {
    name: 'Keep every year’s rules', src: '/landing/rules.webp', w: 1568, h: 300, stage: 'var(--lp-field-3)',
    alt: 'The department’s rules by year: 55 % target until August 2024, 60 % since',
    fact: 'When the department changes its rules, older results keep the rules of their own year, so past reports always match.',
  },
]

const SAVES: [string, string][] = [
  ['Scan, don’t type', 'Scan the answer sheets as one PDF. The marks are read for you, and anything unclear is highlighted for a quick check.'],
  ['Surveys on WhatsApp', 'One click makes the course-exit survey as a Google Form; one more shares it with the class group.'],
  ['Know who needs help early', 'After the first test, the students likely to fall short in an outcome are flagged, with the reason.'],
  ['Lists for extra classes', 'For every outcome, the students below target, ready to copy for a remedial class.'],
  ['The course file, done', 'A complete course-file report as a PDF, straight from the results.'],
]

export function Landing() {
  const root = useRef<HTMLDivElement>(null)
  useReveal(root)
  usePointerFx(root)
  useSmoothScroll()

  return (
    <div className="lp" ref={root}>
      <a className="lp-skip" href="#main">Skip to content</a>
      <header className="lp-bar">
        <Link to="/" className="lp-word" aria-label="CO-PO Attainment, home"><Mark /><span>CO-PO Attainment</span></Link>
        <nav aria-label="Sections">
          <a href="#method">How it works</a>
          <a href="#views">When an outcome falls</a>
          <a href="#saves">What it saves you</a>
          <Link to="/login" className="lp-bar-sign" data-magnet>Sign in</Link>
        </nav>
      </header>
      <main id="main">
        <Hero />
        <Method />
        <Rules />
        <Views />
        <Calculator />
        <Saves />
        <Start />
      </main>
      <Footer />
    </div>
  )
}

function Hero() {
  const shutter = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const t = requestAnimationFrame(() => shutter.current?.classList.add('is-in'))
    return () => cancelAnimationFrame(t)
  }, [])
  return (
    <section className="lp-hero" aria-labelledby="lp-title" data-track>
      <Stairs className="lp-hero-stairs" />
      <div className="lp-hero-copy">
        <h1 id="lp-title">CO-PO attainment, done for you</h1>
        <p className="lp-lede">
          Scan the answer sheets and the marks are read for you. Every course outcome and programme outcome is
          worked out for you, students share feedback through a survey on WhatsApp, the ones who need help
          are flagged early, and the course file is ready as a PDF.
        </p>
        <div className="lp-hero-actions">
          <Link to="/login" className="lp-btn" data-magnet>Open the demo</Link>
          <a href="#method" className="lp-link">See how it works</a>
        </div>
        <p className="lp-credit">A student project by Team 2 · Dept. of Information Science and Engineering, RV College of Engineering</p>
      </div>
      <figure className="lp-hero-shot" data-tilt>
        <div className="lp-shutter lp-frame" ref={shutter} data-glow>
          <img src="/landing/ladder.webp" width={1058} height={530}
               alt="Five course outcomes of Database Management Systems: one at its target, four below" />
        </div>
        <figcaption>Database Management Systems, 2024-25: one outcome on target, four that need attention.</figcaption>
      </figure>
    </section>
  )
}

function Method() {
  const [open, setOpen] = useState(0)
  const base = useId()
  return (
    <section className="lp-method" id="method" aria-labelledby="lp-method-h">
      <div className="lp-intro" data-reveal>
        <h2 id="lp-method-h" style={{ '--i': 0 } as React.CSSProperties}>How it works, in five steps</h2>
        <p style={{ '--i': 1 } as React.CSSProperties}>
          The department sets the rules once: the target score, what each level needs and how much marks and
          feedback count. Every teacher&rsquo;s results are then worked out the same way, automatically.
        </p>
      </div>
      <div className="lp-acc" data-reveal>
        {STEPS.map((s, i) => {
          const isOpen = open === i
          return (
            <div key={s.name} className={`lp-acc-panel t${i}`} data-open={isOpen} style={{ '--i': i } as React.CSSProperties}
                 onMouseEnter={() => setOpen(i)}>
              <h3>
                <button type="button" aria-expanded={isOpen} aria-controls={`${base}-${i}`} id={`${base}-b${i}`}
                        onClick={() => setOpen(i)} onFocus={() => setOpen(i)}>
                  <span className="lp-acc-name">{s.name}</span>
                </button>
              </h3>
              <div className="lp-acc-body" id={`${base}-${i}`} role="region" aria-labelledby={`${base}-b${i}`} hidden={!isOpen}>
                <p>{s.text}</p>
                {s.pic
                  ? <img src={s.pic.src} width={s.pic.w} height={s.pic.h} alt={s.pic.alt} loading="lazy" className="lp-frame" />
                  : <p className="lp-acc-formula" aria-hidden="true">80 % marks + 20 % feedback</p>}
              </div>
            </div>
          )
        })}
      </div>
    </section>
  )
}

function Rules() {
  return (
    <section className="lp-rules" id="rules" aria-labelledby="lp-rules-h">
      <div className="lp-rules-head" data-reveal>
        <h2 id="lp-rules-h" style={{ '--i': 0 } as React.CSSProperties}>Built to be trusted</h2>
        <p style={{ '--i': 1 } as React.CSSProperties}>
          Results only count when nobody can quietly change them. These safeguards are always on.
        </p>
      </div>
      <ul className="lp-tiles" data-reveal>
        <li style={{ '--i': 0 } as React.CSSProperties}>
          <div className="lp-tile f1" data-glow>
            <div className="lp-ui" data-ui>
              <div className="lp-ui-row"><span>CIE Test 2</span><span className="lp-pill">Locked</span></div>
              <div className="lp-ui-row"><span>Quiz 2</span><span className="lp-pill">Locked</span></div>
              <div className="lp-ui-err">Locked: ask the HoD to reopen</div>
            </div>
          </div>
          <h3>Marks are locked</h3>
          <p>Once every mark is in, the test is locked. Changing it needs the HoD&rsquo;s approval, and every attempt is recorded.</p>
        </li>
        <li className="wide" style={{ '--i': 1 } as React.CSSProperties}>
          <div className="lp-tile f2" data-glow>
            <img src="/landing/rules.webp" width={1568} height={300} loading="lazy" className="lp-frame"
                 alt="The department's rules by year: 55 % target until August 2024, 60 % since" />
          </div>
          <h3>Each year keeps its rules</h3>
          <p>A change to the target applies from that year on, so older reports never shift.</p>
        </li>
        <li style={{ '--i': 2 } as React.CSSProperties}>
          <div className="lp-tile f3" data-glow>
            <div className="lp-ui" data-ui>
              <div className="lp-ui-file">IS243 marks, section C</div>
              <div className="lp-ui-err">Row 14, Q3: 12 is more than the maximum of 10</div>
              <div className="lp-ui-muted">Nothing saved yet: fix and upload again</div>
            </div>
          </div>
          <h3>Mistakes are caught</h3>
          <p>Every mark is checked. One wrong entry and nothing is saved, with the exact row pointed out.</p>
        </li>
        <li style={{ '--i': 3 } as React.CSSProperties}>
          <div className="lp-tile f2" data-glow>
            <div className="lp-ui" data-ui>
              {[['HoD', 'every course'], ['Teacher', 'own courses'], ['Coordinator', 'everything, view only'], ['Student', 'own marks']].map(([r, s]) => (
                <div className="lp-ui-row" key={r}><span>{r}</span><span className="lp-ui-muted">{s}</span></div>
              ))}
            </div>
          </div>
          <h3>Everyone sees only their part</h3>
          <p>Teachers see their own courses, students only their own marks.</p>
        </li>
        <li style={{ '--i': 4 } as React.CSSProperties}>
          <div className="lp-tile f1" data-glow>
            <div className="lp-ui" data-ui>
              {[['10:42', 'Marks changed, Quiz 1'], ['10:45', 'Test 2 locked'], ['11:02', 'Reopen approved by HoD']].map(([t, w]) => (
                <div className="lp-ui-row" key={t}><span>{w}</span><span className="lp-ui-muted">{t}</span></div>
              ))}
            </div>
          </div>
          <h3>Every change is on record</h3>
          <p>Who changed what, and when, is kept in a history that cannot be edited without it showing.</p>
        </li>
        <li style={{ '--i': 5 } as React.CSSProperties}>
          <div className="lp-tile f3" data-glow>
            <div className="lp-ui" data-ui>
              <div className="lp-ui-row"><span>Student target</span><b>55 %</b></div>
              <div className="lp-ui-row"><span>Feedback weight</span><b>30 %</b></div>
              <div className="lp-ui-muted">A trial only: official results stay as they are</div>
            </div>
          </div>
          <h3>Try ideas safely</h3>
          <p>Test a different target or weighting on any course without touching the official results.</p>
        </li>
      </ul>
    </section>
  )
}

function Views() {
  const [sel, setSel] = useState(0)
  const s = SCREENS[sel]
  return (
    <section className="lp-views" id="views" aria-labelledby="lp-views-h">
      <div className="lp-views-stage" style={{ background: s.stage }} data-track>
        <Stairs className="lp-views-stairs" />
        {SCREENS.map((x, i) => (
          <img key={x.name} src={x.src} width={x.w} height={x.h} alt={x.alt} loading="lazy"
               className="lp-frame" data-on={i === sel} aria-hidden={i !== sel} />
        ))}
      </div>
      <div className="lp-views-list" data-reveal>
        <h2 id="lp-views-h" style={{ '--i': 0 } as React.CSSProperties}>When an outcome falls short</h2>
        <ul role="list">
          {SCREENS.map((x, i) => (
            <li key={x.name} style={{ '--i': i + 1 } as React.CSSProperties}>
              <button type="button" aria-pressed={i === sel} onClick={() => setSel(i)} onMouseEnter={() => setSel(i)}>
                <Bullet />{x.name}
              </button>
            </li>
          ))}
        </ul>
      </div>
      <p className="lp-views-fact" aria-live="polite">{s.fact}</p>
    </section>
  )
}

function Calculator() {
  const [atTarget, setAtTarget] = useState(58)
  const [favourable, setFavourable] = useState(74)
  const d = toLevel(atTarget), sv = toLevel(favourable)
  const final = (DIRECT * d + SURVEY * sv) / 100
  return (
    <section className="lp-calc" id="try" aria-labelledby="lp-calc-h">
      <div className="lp-calc-top">
        <h2 id="lp-calc-h">Try it: how many reached 60 %?</h2>
        <div className="lp-calc-ui" data-ui>
          <label className="lp-range">
            <span className="lp-range-label">Students who scored 60 % or more<output>{atTarget} %</output></span>
            <input type="range" min={0} max={100} value={atTarget} onChange={(e) => setAtTarget(+e.target.value)} />
          </label>
          <label className="lp-range">
            <span className="lp-range-label">Students who rated the outcome 4 or 5 out of 5<output>{favourable} %</output></span>
            <input type="range" min={0} max={100} value={favourable} onChange={(e) => setFavourable(+e.target.value)} />
          </label>
        </div>
      </div>
      <div className="lp-calc-bottom">
        <p className="lp-figure" aria-live="polite">
          <span className="visually-hidden">Final level </span>{final.toFixed(2)}<span className="lp-unit"> of 3</span>
        </p>
        <p className="lp-calc-why">
          {atTarget} % of the class at 60 % or more gives a marks level of {d}; {favourable} % happy students gives a
          feedback level of {sv}. Together that is {final.toFixed(2)}, {final >= 2 ? 'on or above' : 'below'} the target of 2.
        </p>
      </div>
    </section>
  )
}

function Saves() {
  return (
    <section className="lp-tests" id="saves" aria-labelledby="lp-saves-h">
      <ul className="lp-board" data-reveal>
        <li className="lp-board-head" style={{ '--i': 0 } as React.CSSProperties} data-glow>
          <h2 id="lp-saves-h">What it saves you</h2>
          <p>
            The hours that go into spreadsheets, forms and reports each term, handed back to teaching.
          </p>
        </li>
        {SAVES.map(([name, what], i) => (
          <li key={name} style={{ '--i': i + 1 } as React.CSSProperties} data-glow>
            <h3>{name}</h3>
            <p>{what}</p>
          </li>
        ))}
      </ul>
    </section>
  )
}

function Start() {
  const navigate = useNavigate()
  const [role, setRole] = useState<'hod' | 'faculty'>('hod')
  const [user, setUser] = useState('hod')
  function pick(r: 'hod' | 'faculty') { setRole(r); setUser(r === 'hod' ? 'hod' : 'fac06') }
  return (
    <section className="lp-start" id="start" aria-labelledby="lp-start-h">
      <div className="lp-start-copy">
        <h2 id="lp-start-h">See it for yourself</h2>
        <p>Open the demo as a head of department, who sees every course, or as a teacher, who sees their own.
          Use the demo password you were given.</p>
      </div>
      <form className="lp-dialog" data-ui onSubmit={(e) => { e.preventDefault(); navigate(`/login?u=${encodeURIComponent(user.trim())}`) }}>
        <h3>Sign in as</h3>
        <div className="lp-seg" role="radiogroup" aria-label="Role">
          {(['hod', 'faculty'] as const).map((r) => (
            <button key={r} type="button" role="radio" aria-checked={role === r} onClick={() => pick(r)}>
              {r === 'hod' ? 'Head of department' : 'Teacher'}
            </button>
          ))}
        </div>
        <label className="field">
          <span>Username</span>
          <input className="input" value={user} onChange={(e) => setUser(e.target.value)} autoComplete="username" required />
        </label>
        <p className="lp-dialog-note">Demo teachers are fac01 to fac14; fac06 teaches Database Management Systems.</p>
        <button className="lp-btn" type="submit" data-magnet>Continue to sign in</button>
      </form>
    </section>
  )
}

function Footer() {
  const blocks: [string, number][] = [['C', 62], ['O', 74], ['–', 50], ['P', 87], ['O', 100]]
  return (
    <footer className="lp-foot">
      <div className="lp-foot-mark" aria-hidden="true">
        {blocks.map(([ch, h], i) => <span key={i} style={{ height: `${h}%` }}>{ch}</span>)}
      </div>
      <div className="lp-foot-cols">
        <div>
          <h2>On this page</h2>
          <a href="#method">How it works</a><a href="#rules">Safeguards</a><a href="#views">When an outcome falls</a><a href="#saves">What it saves you</a>
        </div>
        <div>
          <h2>The app</h2>
          <Link to="/login">Sign in</Link><a href="#try">Try the calculator</a>
        </div>
        <div>
          <h2>Made for</h2>
          <p>Teachers, heads of department and programme coordinators</p>
        </div>
        <div className="lp-foot-addr">
          <p>Department of Information Science and Engineering, RV College of Engineering, Bengaluru</p>
          <p>A student project by Team 2. All names and marks shown are made up.</p>
        </div>
      </div>
      <div className="lp-foot-last">
        <p>© 2026 Team 2</p>
        <Link to="/login" className="lp-btn small" data-magnet>Sign in</Link>
      </div>
    </footer>
  )
}
